#!/usr/bin/env python3
"""Create a reviewed Gaussian input and manifest from ChemDraw, MOL, SDF, or SMILES.

This is intentionally conservative: it refuses unassigned tetrahedral
stereochemistry and requires both an explicit multiplicity and an explicit
route for radical inputs.
It is a geometry-preparation utility, not a substitute for method selection
or review of unusual chemical systems.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cdx_stereo import load_chemdraw_molecules, structure_stereo_invariants


DEFAULT_CLOSED_SHELL_ROUTE = "#p b3lyp/6-31g(d) opt"
OPEN_SHELL_DRAFT_WARNING = (
    "Open-shell Gaussian input is an offline draft only; explicit route and "
    "multiplicity do not confer electronic-state scientific acceptance or submission authorization."
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_rdkit():
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
    except ImportError as exc:
        fail(
            "RDKit is required. Set AUTO_G16_RDKIT_PYTHON or use another "
            "Python environment containing rdkit."
        )
    return Chem, AllChem, Descriptors, rdMolDescriptors


def read_molecule(source: str, Chem):
    import_diagnostics = None
    path = Path(source)
    if path.exists():
        suffix = path.suffix.lower()
        if suffix in {".cdx", ".cdxml"}:
            if not Chem.HasChemDrawCDXSupport():
                fail("This RDKit build does not include ChemDraw CDX/CDXML support")
            try:
                molecules, import_diagnostics = load_chemdraw_molecules(str(path), Chem)
            except Exception as exc:
                fail(f"Could not parse ChemDraw file {path}: {exc}")
            if not molecules:
                fail(f"No readable molecule found in {path}")
            if len(molecules) != 1:
                fail("ChemDraw input must contain exactly one molecule for a Gaussian job")
            mol = molecules[0]
        elif suffix == ".sdf":
            supplier = Chem.SDMolSupplier(str(path), removeHs=False, sanitize=True)
            molecules = [mol for mol in supplier if mol is not None]
            if not molecules:
                fail(f"No readable molecule found in {path}")
            if len(molecules) != 1:
                fail("SDF input must contain exactly one molecule; use one MOL file per job")
            mol = molecules[0]
        elif suffix in {".mol", ".mdl"}:
            mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=True)
            if mol is None:
                fail(f"Could not parse MOL file: {path}")
        elif suffix in {".smi", ".smiles", ".txt"}:
            text = path.read_text(encoding="utf-8").splitlines()
            line = next((line.strip() for line in text if line.strip() and not line.lstrip().startswith("#")), "")
            if not line:
                fail(f"No SMILES found in {path}")
            smiles = line.split()[0]
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                fail(f"Could not parse SMILES from {path}")
        else:
            fail("Supported file inputs are .cdx, .cdxml, .mol, .mdl, .sdf, .smi, .smiles, and .txt")
        return mol, str(path), import_diagnostics

    mol = Chem.MolFromSmiles(source)
    if mol is None:
        fail("Input is neither an existing structure file nor a valid SMILES string")
    return mol, "SMILES argument", import_diagnostics


def assign_and_validate(mol, Chem, allow_ambiguous_stereo: bool) -> list[dict[str, Any]]:
    Chem.SanitizeMol(mol)
    Chem.AssignStereochemistry(mol, force=True, cleanIt=True)
    centers = Chem.FindMolChiralCenters(
        mol, includeUnassigned=True, useLegacyImplementation=False
    )
    chiral_centers = [{"atom_index": int(index), "cip": cip} for index, cip in centers]
    unresolved = [center for center in chiral_centers if center["cip"] == "?"]
    if unresolved and not allow_ambiguous_stereo:
        indices = ", ".join(str(item["atom_index"]) for item in unresolved)
        fail(
            f"Unassigned tetrahedral stereochemistry at atom index/indices {indices}. "
            "Resolve the ChemDraw stereobonds or pass --allow-ambiguous-stereo after review."
        )
    return chiral_centers


def make_3d(mol, AllChem, Chem, seed: int, optimize: bool):
    with_h = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    params.enforceChirality = True
    result = AllChem.EmbedMolecule(with_h, params)
    embedding = "ETKDGv3"
    if result < 0:
        params.useRandomCoords = True
        result = AllChem.EmbedMolecule(with_h, params)
        embedding = "ETKDGv3 random coordinates"
    if result < 0:
        fail("RDKit could not generate a 3D conformer; provide reviewed 3D coordinates")

    optimization = "none"
    if optimize:
        try:
            if AllChem.MMFFHasAllMoleculeParams(with_h):
                AllChem.MMFFOptimizeMolecule(with_h, mmffVariant="MMFF94s")
                optimization = "MMFF94s"
            else:
                AllChem.UFFOptimizeMolecule(with_h)
                optimization = "UFF"
        except Exception as exc:  # force fields are optional for unusual molecules
            optimization = f"failed ({type(exc).__name__})"

    # Gaussian Cartesian input needs coordinates for every atom, including
    # hydrogens. Keep the hydrogenated conformer instead of removing H after
    # embedding; the original heavy-atom molecule is still used for identity
    # and stereochemistry in the manifest.
    return with_h, embedding, optimization


def gaussian_route(route: str) -> str:
    route = route.strip()
    if not route:
        fail("--route cannot be empty")
    return route if route.startswith("#") else f"#p {route}"


def resolve_draft_protocol(radical_electrons: int, route: str | None, multiplicity: int | None) -> tuple[str, int, list[str]]:
    """Preserve the closed-shell default while refusing radical defaults."""
    if radical_electrons:
        if multiplicity is None:
            fail("Radical input detected; provide --multiplicity explicitly")
        if route is None:
            fail("Radical input detected; provide --route explicitly")
        return route, multiplicity, [OPEN_SHELL_DRAFT_WARNING]
    return route if route is not None else DEFAULT_CLOSED_SHELL_ROUTE, 1 if multiplicity is None else multiplicity, []


def coordinate_lines(mol, Chem) -> list[str]:
    if mol.GetNumConformers() == 0:
        fail("No 3D conformer is available")
    conformer = mol.GetConformer()
    lines = []
    for atom in mol.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol():<3} {point.x: .8f} {point.y: .8f} {point.z: .8f}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="CDX/CDXML/MOL/SDF/SMILES file, or a SMILES string")
    parser.add_argument("--output", required=True, help="Output Gaussian .gjf path")
    parser.add_argument("--route", default=None)
    parser.add_argument("--charge", type=int, default=None)
    parser.add_argument("--multiplicity", type=int, default=None)
    parser.add_argument("--mem", default="1200MB")
    parser.add_argument("--nproc", type=int, default=3)
    parser.add_argument("--title", default=None)
    parser.add_argument("--seed", type=int, default=0xF00D)
    parser.add_argument("--no-optimize", action="store_true")
    parser.add_argument("--allow-ambiguous-stereo", action="store_true")
    args = parser.parse_args()

    if args.nproc < 1:
        fail("--nproc must be at least 1")
    if args.multiplicity is not None and args.multiplicity < 1:
        fail("--multiplicity must be at least 1")

    Chem, AllChem, Descriptors, rdMolDescriptors = load_rdkit()
    mol, source, import_diagnostics = read_molecule(args.input, Chem)
    if import_diagnostics:
        diagnostic = import_diagnostics[0]
        unsafe_cfg = diagnostic["conflicting_bond_cfg"] or diagnostic["unsupported_bond_cfg"]
        if unsafe_cfg and not args.allow_ambiguous_stereo:
            fail(
                "Conflicting or unsupported ChemDraw bond CFG values remain. "
                "Review the source drawing, or use --allow-ambiguous-stereo for preview only."
            )
    chiral_centers = assign_and_validate(mol, Chem, args.allow_ambiguous_stereo)

    formal_charge = int(Chem.GetFormalCharge(mol))
    charge = formal_charge if args.charge is None else args.charge
    radical_electrons = sum(atom.GetNumRadicalElectrons() for atom in mol.GetAtoms())
    route_argument, multiplicity, draft_warnings = resolve_draft_protocol(
        radical_electrons, args.route, args.multiplicity
    )

    geometry, embedding, optimization = make_3d(
        mol, AllChem, Chem, args.seed, not args.no_optimize
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    chk_name = f"{output.stem}.chk"
    route = gaussian_route(route_argument)
    title = args.title or output.stem
    coordinates = coordinate_lines(geometry, Chem)
    stereo_invariants = structure_stereo_invariants(
        mol, Chem, rdMolDescriptors, import_diagnostics[0] if import_diagnostics else None
    )
    geometry_formula = rdMolDescriptors.CalcMolFormula(geometry)
    if geometry_formula != stereo_invariants["formula"]:
        fail("formula changed while adding explicit hydrogens for Cartesian input")
    if int(geometry.GetNumAtoms()) != len(coordinates):
        fail("Cartesian atom count differs from the explicit-hydrogen geometry")
    input_text = (
        f"%chk={chk_name}\n"
        f"%mem={args.mem}\n"
        f"%nprocshared={args.nproc}\n"
        f"{route}\n\n"
        f"{title}\n\n"
        f"{charge} {multiplicity}\n"
        + "\n".join(coordinates)
        + "\n\n"
    )
    output.write_text(input_text, encoding="utf-8")
    xyz_path = output.with_suffix(".xyz")
    xyz_path.write_text(
        f"{len(coordinates)}\n{title}\n" + "\n".join(coordinates) + "\n",
        encoding="utf-8",
    )

    symbols = sorted({atom.GetSymbol() for atom in geometry.GetAtoms()})
    common_main_group = {"H", "B", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I", "Si"}
    warnings = list(draft_warnings)
    if import_diagnostics:
        diagnostic = import_diagnostics[0]
        if diagnostic["conflicting_bond_cfg"]:
            warnings.append("Conflicting ChemDraw bond directions are present; review the source drawing.")
        if diagnostic["unsupported_bond_cfg"]:
            warnings.append("Unsupported ChemDraw bond CFG values are present; review the source drawing.")
    component_count = len(Chem.GetMolFrags(mol, asMols=False))
    if component_count > 1:
        warnings.append(
            f"Input contains {component_count} disconnected components; review salt/solvate and ion-pair intent."
        )
    if args.charge is not None and charge != formal_charge:
        warnings.append(
            f"Requested charge {charge} differs from structure formal charge {formal_charge}; confirm protonation/salt state."
        )
    unusual = sorted(set(symbols) - common_main_group)
    if unusual:
        warnings.append(
            "Non-main-group element(s) present: "
            + ", ".join(unusual)
            + "; review basis/ECP and coordination protocol."
        )
    if args.allow_ambiguous_stereo and any(c["cip"] == "?" for c in chiral_centers):
        warnings.append("Unassigned tetrahedral stereochemistry was explicitly allowed")
    if optimization.startswith("failed"):
        warnings.append("Force-field optimization failed; Gaussian will start from the embedded geometry")

    manifest = {
        "schema": "chemdraw-gaussian/1",
        "source": source,
        "input_argument": args.input,
        "gaussian_input": str(output),
        "xyz_coordinates": str(xyz_path),
        "checkpoint": chk_name,
        "canonical_isomeric_smiles": Chem.MolToSmiles(mol, isomericSmiles=True),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "molecular_weight": round(float(Descriptors.MolWt(mol)), 6),
        "source_atom_count": int(mol.GetNumAtoms()),
        "heavy_atom_count": int(mol.GetNumHeavyAtoms()),
        "atom_count_in_gaussian_input": int(geometry.GetNumAtoms()),
        "component_count": component_count,
        "formal_charge_in_structure": formal_charge,
        "charge_used": charge,
        "radical_electrons": int(radical_electrons),
        "multiplicity_used": multiplicity,
        "multiplicity_was_explicit": args.multiplicity is not None,
        "chiral_centers": chiral_centers,
        "cdx_stereo_import": import_diagnostics[0] if import_diagnostics else None,
        "structure_invariants": {
            **stereo_invariants,
            "gaussian_formula": geometry_formula,
            "gaussian_atom_count": len(coordinates),
            "formula_conserved": True,
            "atom_count_conserved": True,
        },
        "geometry": {
            "embedding": embedding,
            "force_field_optimization": optimization,
            "explicit_hydrogens_written": True,
            "seed": args.seed,
        },
        "route": route,
        "route_was_explicit": args.route is not None,
        "scientific_acceptance": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "mem": args.mem,
        "nprocshared": args.nproc,
        "warnings": warnings,
    }
    manifest_path = output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"gaussian_input": str(output), "xyz": str(xyz_path), "manifest": str(manifest_path), "warnings": warnings}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted")
