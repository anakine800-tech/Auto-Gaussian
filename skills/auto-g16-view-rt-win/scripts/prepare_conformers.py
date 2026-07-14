#!/usr/bin/env python3
"""Generate, rank, review-gate, and select stereochemistry-preserving conformers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from runtime_config import setting

CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
PIPELINE = Path(
    setting(
        "AUTO_G16_PIPELINE_SCRIPTS",
        "chemdraw_pipeline_scripts",
        str(CODEX_HOME / "skills" / "auto-g16-chemdraw-pipeline" / "scripts"),
    )
)


def load_gaussian_input():
    sys.path.insert(0, str(PIPELINE))
    try:
        import make_gaussian_input
    except ImportError as exc:
        raise SystemExit(
            f"ERROR: could not import ChemDraw Gaussian pipeline from {PIPELINE}: {exc}"
        ) from exc
    return make_gaussian_input


RESOURCE_TIERS = {
    "simple": {"mem": "12GB", "nproc": 8},
    "general": {"mem": "50GB", "nproc": 22},
    "complex": {"mem": "120GB", "nproc": 44},
}


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_project(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", value):
        fail("project must be 1-40 safe filename characters, starting alphanumeric")
    return value


def memory_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?B)\s*", value, re.I)
    if not match:
        fail("mem must use B, KB, MB, GB, or TB")
    powers = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}
    return int(float(match.group(1)) * 1024 ** powers[match.group(2).upper()])


def coordinate_lines(mol, conformer_id: int) -> list[str]:
    conformer = mol.GetConformer(conformer_id)
    lines = []
    for atom in mol.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol():<3} {point.x: .8f} {point.y: .8f} {point.z: .8f}")
    return lines


def write_candidate(
    *,
    mol,
    conformer_id: int,
    rank: int,
    output_dir: Path,
    project: str,
    route: str,
    mem: str,
    nproc: int,
    charge: int,
    multiplicity: int,
    source: str,
    identity: dict[str, Any],
    chiral_centers: list[dict[str, Any]],
    force_field: str,
    energy: float,
    relative_energy: float,
    converged: bool,
    nearest_kept_rmsd: float | None,
    review_notes: list[str],
    global_warnings: list[str],
) -> dict[str, Any]:
    stem = f"{project}_c{rank:03d}"
    gjf = output_dir / f"{stem}.gjf"
    xyz = output_dir / f"{stem}.xyz"
    manifest_path = output_dir / f"{stem}.json"
    coordinates = coordinate_lines(mol, conformer_id)
    title = f"{project} conformer {rank}; {force_field} relative energy {relative_energy:.6f} kcal/mol"
    gjf.write_text(
        f"%chk={stem}.chk\n%mem={mem}\n%nprocshared={nproc}\n{route}\n\n"
        f"{title}\n\n{charge} {multiplicity}\n"
        + "\n".join(coordinates) + "\n\n",
        encoding="utf-8",
    )
    xyz.write_text(
        f"{len(coordinates)}\n{title}\n" + "\n".join(coordinates) + "\n",
        encoding="utf-8",
    )
    warnings = list(global_warnings)
    if not converged:
        warnings.append("Force-field minimization did not converge within the requested iteration limit")
    manifest = {
        "schema": "gaussian-conformer-candidate/1",
        "candidate_only": True,
        "calculation_ready": False,
        "source": source,
        "gaussian_input": str(gjf),
        "xyz_coordinates": str(xyz),
        "checkpoint": f"{stem}.chk",
        "rank": rank,
        "rdkit_conformer_id": conformer_id,
        "canonical_isomeric_smiles": identity["smiles"],
        "formula": identity["formula"],
        "source_atom_count": identity["source_atom_count"],
        "heavy_atom_count": identity["heavy_atom_count"],
        "atom_count_in_gaussian_input": len(coordinates),
        "component_count": identity["component_count"],
        "formal_charge_in_structure": identity["formal_charge"],
        "charge_used": charge,
        "multiplicity_used": multiplicity,
        "chiral_centers": chiral_centers,
        "force_field": force_field,
        "force_field_converged": converged,
        "force_field_energy_kcal_mol": energy,
        "relative_force_field_energy_kcal_mol": relative_energy,
        "nearest_kept_rmsd_angstrom": nearest_kept_rmsd,
        "route": route,
        "mem": mem,
        "nprocshared": nproc,
        "review_notes": review_notes,
        "warnings": warnings,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "rank": rank,
        "conformer_id": conformer_id,
        "gaussian_input": str(gjf),
        "xyz": str(xyz),
        "manifest": str(manifest_path),
        "input_sha256": sha256(gjf),
        "force_field_energy_kcal_mol": energy,
        "relative_force_field_energy_kcal_mol": relative_energy,
        "nearest_kept_rmsd_angstrom": nearest_kept_rmsd,
        "warnings": warnings,
    }


def command_generate(args) -> None:
    gaussian_input = load_gaussian_input()
    project = safe_project(args.project)
    if not 2 <= args.num_conformers <= 1000:
        fail("num-conformers must be between 2 and 1000")
    if not 1 <= args.max_keep <= args.num_conformers:
        fail("max-keep must be between 1 and num-conformers")
    if args.energy_window < 0 or args.rmsd_threshold < 0:
        fail("energy-window and rmsd-threshold must be non-negative")
    if args.max_iters < 1:
        fail("max-iters must be positive")
    route = gaussian_input.gaussian_route(args.route)
    if not re.search(r"(?i)(?:^|\s)opt(?:$|\s|=|\()", route):
        fail("conformer Gaussian route must contain Opt")
    tier = RESOURCE_TIERS[args.resource_tier]
    mem = args.mem or tier["mem"]
    nproc = args.nproc or tier["nproc"]
    if memory_bytes(mem) > 120 * 1024**3:
        fail("mem exceeds the 120 GB server ceiling")
    if nproc < 1 or nproc > 44:
        fail("nproc must be between 1 and 44")

    Chem, AllChem, Descriptors, rdMolDescriptors = gaussian_input.load_rdkit()
    from rdkit.Chem import rdMolAlign

    mol, source, import_diagnostics = gaussian_input.read_molecule(args.source, Chem)
    if import_diagnostics:
        diagnostic = import_diagnostics[0]
        if diagnostic["conflicting_bond_cfg"] or diagnostic["unsupported_bond_cfg"]:
            fail("ChemDraw contains conflicting or unsupported bond CFG values")
    chiral_centers = gaussian_input.assign_and_validate(mol, Chem, False)
    component_count = len(Chem.GetMolFrags(mol, asMols=False))
    if component_count > 1 and not args.allow_disconnected:
        fail("disconnected components require --allow-disconnected and explicit geometry review")
    formal_charge = int(Chem.GetFormalCharge(mol))
    charge = formal_charge if args.charge is None else args.charge
    radical_electrons = sum(atom.GetNumRadicalElectrons() for atom in mol.GetAtoms())
    if radical_electrons and args.multiplicity is None:
        fail("radical input requires explicit multiplicity")
    multiplicity = 1 if args.multiplicity is None else args.multiplicity
    if multiplicity < 1:
        fail("multiplicity must be positive")

    geometry = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = args.seed
    params.enforceChirality = True
    params.pruneRmsThresh = 0.1
    params.numThreads = 0
    conformer_ids = list(AllChem.EmbedMultipleConfs(geometry, numConfs=args.num_conformers, params=params))
    if not conformer_ids:
        params.useRandomCoords = True
        conformer_ids = list(AllChem.EmbedMultipleConfs(geometry, numConfs=args.num_conformers, params=params))
    if not conformer_ids:
        fail("RDKit could not embed any conformer")

    if AllChem.MMFFHasAllMoleculeParams(geometry):
        force_field = "MMFF94s"
        optimization_results = AllChem.MMFFOptimizeMoleculeConfs(
            geometry, numThreads=0, maxIters=args.max_iters, mmffVariant="MMFF94s"
        )
    else:
        if hasattr(AllChem, "UFFHasAllMoleculeParams") and not AllChem.UFFHasAllMoleculeParams(geometry):
            fail("neither MMFF94s nor UFF has parameters for the complete structure")
        force_field = "UFF"
        optimization_results = AllChem.UFFOptimizeMoleculeConfs(
            geometry, numThreads=0, maxIters=args.max_iters
        )
    if len(optimization_results) != len(conformer_ids):
        fail("force-field results do not match embedded conformers")
    scored = sorted(
        (
            {"conformer_id": int(cid), "converged": int(status) == 0, "energy": float(energy)}
            for cid, (status, energy) in zip(conformer_ids, optimization_results)
        ),
        key=lambda item: item["energy"],
    )
    minimum_energy = scored[0]["energy"]
    kept: list[dict[str, Any]] = []
    for item in scored:
        relative = item["energy"] - minimum_energy
        if relative > args.energy_window:
            continue
        rmsds = [
            float(rdMolAlign.GetBestRMS(geometry, geometry, item["conformer_id"], previous["conformer_id"]))
            for previous in kept
        ]
        nearest = min(rmsds) if rmsds else None
        if nearest is not None and nearest < args.rmsd_threshold:
            continue
        item["relative_energy"] = relative
        item["nearest_rmsd"] = nearest
        kept.append(item)
        if len(kept) >= args.max_keep:
            break
    if not kept:
        fail("all conformers were removed by filters")

    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        fail("output directory is not empty; choose a new directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = sorted({atom.GetSymbol() for atom in geometry.GetAtoms()})
    review_notes = [
        "Force-field energies are prescreening values only and must not be reported as Gaussian energies.",
        "Axial/atropisomeric chirality is not validated by this conformer enumeration; inspect such candidates explicitly.",
    ]
    if force_field == "UFF":
        review_notes.append("UFF fallback was used; inspect boron and unusual main-group geometries carefully.")
    global_warnings = []
    if component_count > 1:
        global_warnings.append("Disconnected components were embedded; relative placement requires explicit review")
    if args.charge is not None and charge != formal_charge:
        global_warnings.append("Requested charge differs from the structure formal charge")
    identity = {
        "smiles": Chem.MolToSmiles(mol, isomericSmiles=True),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "molecular_weight": round(float(Descriptors.MolWt(mol)), 6),
        "source_atom_count": int(mol.GetNumAtoms()),
        "heavy_atom_count": int(mol.GetNumHeavyAtoms()),
        "component_count": component_count,
        "formal_charge": formal_charge,
        "elements": symbols,
    }
    candidates = [
        write_candidate(
            mol=geometry,
            conformer_id=item["conformer_id"],
            rank=rank,
            output_dir=output_dir,
            project=project,
            route=route,
            mem=mem,
            nproc=nproc,
            charge=charge,
            multiplicity=multiplicity,
            source=source,
            identity=identity,
            chiral_centers=chiral_centers,
            force_field=force_field,
            energy=item["energy"],
            relative_energy=item["relative_energy"],
            converged=item["converged"],
            nearest_kept_rmsd=item["nearest_rmsd"],
            review_notes=review_notes,
            global_warnings=global_warnings,
        )
        for rank, item in enumerate(kept, 1)
    ]

    sdf = output_dir / f"{project}_conformers.sdf"
    writer = Chem.SDWriter(str(sdf))
    for item, candidate in zip(kept, candidates):
        record = Chem.Mol(geometry)
        selected_conf = Chem.Conformer(geometry.GetConformer(item["conformer_id"]))
        record.RemoveAllConformers()
        record.AddConformer(selected_conf, assignId=True)
        record.SetProp("_Name", Path(candidate["gaussian_input"]).stem)
        record.SetProp("ConformerRank", str(candidate["rank"]))
        record.SetProp("RelativeEnergyKcalMol", f"{candidate['relative_force_field_energy_kcal_mol']:.8f}")
        writer.write(record)
    writer.close()
    source_path = Path(args.source).expanduser()
    ensemble = {
        "schema": "gaussian-conformer-ensemble/1",
        "project": project,
        "source": str(source_path.resolve()) if source_path.is_file() else args.source,
        "source_sha256": sha256(source_path.resolve()) if source_path.is_file() else None,
        "identity": identity,
        "charge": charge,
        "multiplicity": multiplicity,
        "chiral_centers": chiral_centers,
        "embedding": "ETKDGv3; enforceChirality=True",
        "force_field": force_field,
        "requested_conformers": args.num_conformers,
        "embedded_conformers": len(conformer_ids),
        "kept_conformers": len(candidates),
        "energy_window_kcal_mol": args.energy_window,
        "rmsd_threshold_angstrom": args.rmsd_threshold,
        "resource_tier": args.resource_tier,
        "route": route,
        "mem": mem,
        "nprocshared": nproc,
        "ensemble_sdf": str(sdf),
        "candidate_only": True,
        "review_notes": review_notes,
        "warnings": global_warnings,
        "candidates": candidates,
    }
    ensemble_path = output_dir / f"{project}_conformers.json"
    ensemble_path.write_text(json.dumps(ensemble, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ensemble": str(ensemble_path), **ensemble}, ensure_ascii=False, indent=2))


def command_select(args) -> None:
    if not args.confirmed:
        fail("select requires --confirmed after structure, stereochemistry, and candidate review")
    ensemble_path = Path(args.ensemble).expanduser().resolve()
    ensemble = json.loads(ensemble_path.read_text(encoding="utf-8"))
    if ensemble.get("schema") != "gaussian-conformer-ensemble/1":
        fail("input is not a conformer ensemble manifest")
    matches = [item for item in ensemble["candidates"] if int(item["rank"]) == args.rank]
    if not matches:
        fail("requested rank is not present in the ensemble")
    candidate = matches[0]
    candidate_input = Path(candidate["gaussian_input"]).resolve()
    if sha256(candidate_input) != candidate.get("input_sha256"):
        fail("candidate Gaussian input hash differs from the ensemble manifest")
    manifest_path = Path(candidate["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("warnings"):
        fail("candidate contains unresolved warnings and cannot be selected")
    if any(center.get("cip") == "?" for center in manifest.get("chiral_centers", [])):
        fail("candidate contains unassigned tetrahedral stereochemistry")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        fail("selection output directory is not empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_files = []
    for key in ("gaussian_input", "xyz", "manifest"):
        source = Path(candidate[key]).resolve()
        target = output_dir / source.name
        shutil.copy2(source, target)
        selected_files.append(str(target))
    selected_manifest_path = output_dir / manifest_path.name
    selected_manifest = json.loads(selected_manifest_path.read_text(encoding="utf-8"))
    selected_manifest.update(
        {
            "candidate_only": False,
            "calculation_ready": True,
            "selection": {
                "confirmed": True,
                "rank": args.rank,
                "ensemble": str(ensemble_path),
                "ensemble_sha256": sha256(ensemble_path),
            },
            "gaussian_input": str(output_dir / Path(candidate["gaussian_input"]).name),
            "xyz_coordinates": str(output_dir / Path(candidate["xyz"]).name),
        }
    )
    selected_manifest_path.write_text(json.dumps(selected_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected_rank": args.rank, "files": selected_files, "manifest": str(selected_manifest_path)}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="embed, minimize, rank, and write candidate inputs")
    generate.add_argument("source")
    generate.add_argument("--output-dir", required=True)
    generate.add_argument("--project", required=True)
    generate.add_argument("--route", required=True)
    generate.add_argument("--resource-tier", choices=sorted(RESOURCE_TIERS), default="general")
    generate.add_argument("--mem")
    generate.add_argument("--nproc", type=int)
    generate.add_argument("--charge", type=int)
    generate.add_argument("--multiplicity", type=int)
    generate.add_argument("--num-conformers", type=int, default=50)
    generate.add_argument("--max-keep", type=int, default=10)
    generate.add_argument("--energy-window", type=float, default=6.0)
    generate.add_argument("--rmsd-threshold", type=float, default=0.5)
    generate.add_argument("--max-iters", type=int, default=1000)
    generate.add_argument("--seed", type=int, default=0xF00D)
    generate.add_argument("--allow-disconnected", action="store_true")
    generate.set_defaults(func=command_generate)

    select = sub.add_parser("select", help="promote one reviewed candidate to calculation-ready")
    select.add_argument("ensemble")
    select.add_argument("--rank", type=int, required=True)
    select.add_argument("--output-dir", required=True)
    select.add_argument("--confirmed", action="store_true")
    select.set_defaults(func=command_select)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted", code=130)
