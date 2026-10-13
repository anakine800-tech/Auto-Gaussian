#!/usr/bin/env python3
# Source: skills/auto-g16-view-rt-win/scripts/prepare_conformers.py (T4 migration).
"""Generate stereochemistry-preserving force-field conformers for ag dedup."""

from __future__ import annotations

import argparse
import json
import math
from typing import Any

import make_gaussian_input as gaussian_input
from make_gaussian_input import fail, output_directory, validate_scope, validate_multiplicity


def coordinate_lines(mol, conformer_id: int) -> list[str]:
    conformer = mol.GetConformer(conformer_id)
    lines = []
    for atom in mol.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol():<3} {point.x: .8f} {point.y: .8f} {point.z: .8f}")
    return lines


def command_generate(args) -> None:
    if not 2 <= args.num_conformers <= 1000:
        fail("num-conformers must be between 2 and 1000")
    if not 1 <= args.max_keep <= args.num_conformers:
        fail("max-keep must be between 1 and num-conformers")
    # NaN would silently disable the scientific filters requested by the user.
    if any(not math.isfinite(v) or v < 0 for v in (args.energy_window, args.rmsd_threshold)):
        fail("energy-window and rmsd-threshold must be finite and non-negative")
    if args.max_iters < 1:
        fail("max-iters must be positive")
    validate_multiplicity(args.multiplicity)
    Chem, AllChem, Descriptors, rdMolDescriptors = gaussian_input.load_rdkit()
    from rdkit.Chem import rdMolAlign

    mol, source, import_diagnostics = gaussian_input.read_molecule(args.source, Chem)
    chiral_centers = validate_scope(mol, Chem, import_diagnostics)
    formal_charge = int(Chem.GetFormalCharge(mol))
    charge = formal_charge if args.charge is None else args.charge
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
    if any(not math.isfinite(item["energy"]) for item in scored):
        fail("force-field returned non-finite energy")
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

    if rdMolDescriptors.CalcMolFormula(geometry) != rdMolDescriptors.CalcMolFormula(mol):
        fail("formula changed while adding explicit hydrogens for Cartesian input")
    warnings = []
    if force_field == "UFF":
        warnings.append("UFF fallback used; inspect boron and unusual main-group geometries carefully.")
    if charge != formal_charge:
        warnings.append("Requested charge differs from structure formal charge; confirm protonation/salt state.")
    frames = []
    candidates = []
    for rank, item in enumerate(kept, 1):
        lines = coordinate_lines(geometry, item["conformer_id"])
        if len(lines) != geometry.GetNumAtoms():
            fail("Cartesian atom count differs from the explicit-hydrogen geometry")
        note = [] if item["converged"] else ["Force-field minimization did not converge within the iteration limit"]
        frames.append(f"{len(lines)}\n{item['energy']:.10f} {force_field} kcal/mol; rank={rank}\n" + "\n".join(lines) + "\n")
        candidates.append({"rank": rank, "conformer_id": item["conformer_id"],
                           "force_field_energy_kcal_mol": item["energy"],
                           "relative_force_field_energy_kcal_mol": item["relative_energy"],
                           "force_field_converged": item["converged"],
                           "nearest_kept_rmsd_angstrom": item["nearest_rmsd"], "warnings": note})
    identity = gaussian_input.structure_stereo_invariants(
        mol, Chem, rdMolDescriptors, import_diagnostics[0] if import_diagnostics else None)
    summary = {"identity": identity, "atom_count": geometry.GetNumAtoms(),
               "charge": charge, "formal_charge": formal_charge, "multiplicity": args.multiplicity,
               "chiral_centers": chiral_centers, "embedding": "ETKDGv3; enforceChirality=True",
               "force_field": force_field, "energy_unit": "kcal/mol", "seed": args.seed,
               "requested_conformers": args.num_conformers, "embedded_conformers": len(conformer_ids),
               "kept_conformers": len(candidates), "max_keep": args.max_keep, "max_iters": args.max_iters,
               "energy_window_kcal_mol": args.energy_window, "rmsd_threshold_angstrom": args.rmsd_threshold,
               "ensemble_xyz": "conformers.xyz", "warnings": warnings, "candidates": candidates,
               "review_notes": ["Force-field energies are prescreening values, not DFT energies or populations.",
                                "Axial/atropisomeric chirality is not validated; inspect explicitly."]}
    output = output_directory(args.study, args.name)
    (output / "conformers.xyz").write_text("".join(frames), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(output), **summary}, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="embed, minimize and write a multi-frame XYZ and summary")
    generate.add_argument("source")
    generate.add_argument("--study", required=True)
    generate.add_argument("--name", required=True)
    generate.add_argument("--charge", type=int)
    generate.add_argument("--multiplicity", type=int, required=True)
    generate.add_argument("--num-conformers", type=int, default=50)
    generate.add_argument("--max-keep", type=int, default=10)
    generate.add_argument("--energy-window", type=float, default=6.0)
    generate.add_argument("--rmsd-threshold", type=float, default=0.5)
    generate.add_argument("--max-iters", type=int, default=1000)
    generate.add_argument("--seed", type=int, default=0xF00D)
    generate.set_defaults(func=command_generate)
    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
