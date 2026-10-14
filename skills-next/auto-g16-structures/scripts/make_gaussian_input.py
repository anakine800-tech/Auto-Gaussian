#!/usr/bin/env python3
# Source: archive/skills/auto-g16-chemdraw-pipeline/scripts/make_gaussian_input.py (T4 migration).
"""Create a Gaussian input and summary from XYZ, ChemDraw, MOL, SDF, or SMILES.

This is intentionally conservative: it refuses unassigned tetrahedral
stereochemistry and stops on radicals, metals, and coordination systems.
Route, charge, and multiplicity must be provided explicitly.
It is a geometry-preparation utility, not a substitute for method selection
or review of unusual chemical systems.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from cdx_stereo import load_chemdraw_molecules, structure_stereo_invariants


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_rdkit():
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
    except ImportError as exc:
        fail(
            "RDKit is required; run this script in the chem environment."
        )
    return Chem, AllChem, Descriptors, rdMolDescriptors


def read_molecule(source: str, Chem):
    import_diagnostics = None
    path = Path(source).expanduser()
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


def assign_and_validate(mol, Chem) -> list[dict[str, Any]]:
    Chem.SanitizeMol(mol)
    Chem.AssignStereochemistry(mol, force=True, cleanIt=True)
    centers = Chem.FindMolChiralCenters(
        mol, includeUnassigned=True, useLegacyImplementation=False
    )
    chiral_centers = [{"atom_index": int(index), "cip": cip} for index, cip in centers]
    unresolved = [center for center in chiral_centers if center["cip"] == "?"]
    if unresolved:
        indices = ", ".join(str(item["atom_index"]) for item in unresolved)
        fail(
            f"Unassigned tetrahedral stereochemistry at atom index/indices {indices}. "
            "Resolve the source stereochemistry before continuing."
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


def coordinate_lines(mol, Chem) -> list[str]:
    if mol.GetNumConformers() == 0:
        fail("No 3D conformer is available")
    conformer = mol.GetConformer()
    lines = []
    for atom in mol.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol():<3} {point.x: .8f} {point.y: .8f} {point.z: .8f}")
    return lines


COMMON_MAIN_GROUP = {"H", "B", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I", "Si"}


def validate_scope(mol, Chem, import_diagnostics=None):
    # Prevent unsupported bonding/electronic states entering organic force fields.
    if any(atom.GetNumRadicalElectrons() for atom in mol.GetAtoms()):
        fail("Radicals are outside this Skill; ask the researcher")
    if any(atom.GetSymbol() not in COMMON_MAIN_GROUP for atom in mol.GetAtoms()):
        fail("Metals or unsupported elements are outside this Skill; ask the researcher")
    if any("DATIVE" in str(bond.GetBondType()) or str(bond.GetBondType()) in {"ZERO", "UNSPECIFIED"}
           for bond in mol.GetBonds()):
        fail("Coordination systems are outside this Skill; ask the researcher")
    if len(Chem.GetMolFrags(mol)) != 1:
        fail("Disconnected salts/complexes need manual review outside this Skill")
    if import_diagnostics:
        diagnostic = import_diagnostics[0]
        if diagnostic["conflicting_bond_cfg"] or diagnostic["unsupported_bond_cfg"]:
            fail("ChemDraw contains conflicting or unsupported bond CFG values")
    return assign_and_validate(mol, Chem)


def validate_multiplicity(value):
    if value != 1:
        fail("This Skill handles closed-shell singlets only; ask the researcher about the electronic state")


def output_directory(study, name):
    # A name must not escape structures/; a fresh directory prevents overwriting prior geometry.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        fail("name must contain only letters, digits, underscores or hyphens")
    root = Path(study).expanduser().resolve()
    if not root.is_dir():
        fail("study directory must already exist")
    structures = root / "structures"
    if structures.is_symlink():
        fail("study structures directory must not be a symlink")
    structures.mkdir(exist_ok=True)
    output = structures / name
    try:
        output.mkdir()
    except FileExistsError:
        fail("output directory already exists; choose a new name (files are never overwritten)")
    return output


def main() -> int:
    from audit_cartesian_input import parse, min_pair_distance

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Single-frame XYZ, structure file, or unambiguous SMILES")
    parser.add_argument("--study", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--charge", type=int, required=True)
    parser.add_argument("--multiplicity", type=int, required=True)
    parser.add_argument("--mem", required=True)
    parser.add_argument("--nprocshared", type=int, required=True)
    parser.add_argument("--chk", required=True, help="Checkpoint filename, without any directory")
    parser.add_argument("--title", default="Reviewed structure")
    parser.add_argument("--seed", type=int, default=0xF00D)
    parser.add_argument("--no-optimize", action="store_true")
    args = parser.parse_args()
    validate_multiplicity(args.multiplicity)
    if args.nprocshared < 1:
        fail("nprocshared must be positive")
    # Prevent line injection from changing the reviewed Link0/route or adding another job.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.chk", args.chk):
        fail("chk must be a filename ending in .chk, without a path")
    if not re.fullmatch(r"[1-9][0-9]*(?:KB|MB|GB|TB)", args.mem, re.I):
        fail("mem must be a positive integer with KB, MB, GB, or TB units")
    if any(c in args.route + args.title for c in "\r\n\x00"):
        fail("route and title must each be a single line")
    if not args.title.strip():
        fail("title must not be empty")
    route = gaussian_route(args.route)
    source_path = Path(args.input).expanduser()
    warnings = []
    identity = None
    if source_path.suffix.lower() == ".xyz" and source_path.is_file():
        coordinates, _, raw_lines = parse(source_path)
        if any(line.strip() for line in raw_lines[2 + len(coordinates):]):
            fail("XYZ input must contain exactly one frame; select one frame after deduplication")
        if any(atom[0] not in COMMON_MAIN_GROUP for atom in coordinates):
            fail("Metals or unsupported elements are outside this Skill")
        if min_pair_distance(coordinates)[0] < 0.4:
            fail("XYZ contains atoms closer than 0.4 angstrom")
        lines = [f"{symbol:<3} {x: .8f} {y: .8f} {z: .8f}" for symbol, x, y, z in coordinates]
        warnings.append("XYZ has no bond or stereochemistry information; use the human-confirmed source identity.")
    else:
        Chem, AllChem, Descriptors, rdMolDescriptors = load_rdkit()
        mol, source, diagnostics = read_molecule(args.input, Chem)
        validate_scope(mol, Chem, diagnostics)
        geometry, embedding, optimization = make_3d(mol, AllChem, Chem, args.seed, not args.no_optimize)
        lines = coordinate_lines(geometry, Chem)
        identity = structure_stereo_invariants(mol, Chem, rdMolDescriptors, diagnostics[0] if diagnostics else None)
        if rdMolDescriptors.CalcMolFormula(geometry) != identity["formula"]:
            fail("formula changed while adding explicit hydrogens for Cartesian input")
        if geometry.GetNumAtoms() != len(lines):
            fail("Cartesian atom count differs from the explicit-hydrogen geometry")
        if args.charge != Chem.GetFormalCharge(mol):
            warnings.append("Requested charge differs from structure formal charge; confirm protonation/salt state.")
        if optimization == "UFF":
            warnings.append("UFF fallback used; inspect boron and unusual main-group geometries carefully.")
        if optimization.startswith("failed"):
            warnings.append("Force-field optimization failed; inspect the embedded geometry.")
        identity["geometry"] = {"embedding": embedding, "optimization": optimization}
    out = output_directory(args.study, args.name)
    output = out / f"{args.name}.gjf"
    output.write_text(
        f"%chk={args.chk}\n%mem={args.mem}\n%nprocshared={args.nprocshared}\n{route}\n\n"
        f"{args.title}\n\n{args.charge} {args.multiplicity}\n" + "\n".join(lines) + "\n\n",
        encoding="utf-8",
    )
    xyz = out / f"{args.name}.xyz"
    xyz.write_text(f"{len(lines)}\n{args.title}\n" + "\n".join(lines) + "\n", encoding="utf-8")
    summary = {"gaussian_input": output.name, "xyz": xyz.name, "atom_count": len(lines),
               "charge": args.charge, "multiplicity": args.multiplicity, "route": route,
               "nprocshared": args.nprocshared, "mem": args.mem, "chk": args.chk,
               "identity": identity, "warnings": warnings}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(out), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
