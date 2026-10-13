#!/usr/bin/env python3
"""Create validated ChemDraw-compatible MOL/SDF files from resolved SMILES."""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Descriptors, Draw, rdDepictor, rdMolDescriptors


if hasattr(rdDepictor, "SetPreferCoordGen"):
    rdDepictor.SetPreferCoordGen(True)


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return slug.strip("_") or "structure"


def unique_filename(name: str, used: set[str]) -> str:
    stem = slugify(name)
    candidate = f"{stem}.mol"
    counter = 2
    while candidate.casefold() in used:
        candidate = f"{stem}_{counter}.mol"
        counter += 1
    used.add(candidate.casefold())
    return candidate


def chiral_centers(mol: Chem.Mol) -> list[tuple[int, str]]:
    Chem.AssignStereochemistry(mol, force=True, cleanIt=True)
    return Chem.FindMolChiralCenters(
        mol, includeUnassigned=True, useLegacyImplementation=False
    )


def expected_matches(centers: list[tuple[int, str]], expected: str) -> bool:
    labels = [token.strip().upper() for token in expected.split(",") if token.strip()]
    if not labels:
        return True
    observed = [cip.upper() for _, cip in centers]
    return Counter(observed) == Counter(labels)


def canonical_smiles(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def generate_2d_coordinates(
    mol: Chem.Mol, row: dict[str, str], input_dir: Path
) -> tuple[str, str, str]:
    """Generate ordinary or literature-template-constrained 2D coordinates."""
    template_value = row.get("template_mol", "").strip()
    if not template_value:
        rdDepictor.Compute2DCoords(mol)
        return "coordgen", "", ""

    template_path = Path(template_value).expanduser()
    if not template_path.is_absolute():
        template_path = input_dir / template_path
    template_path = template_path.resolve()
    if not template_path.is_file():
        raise SystemExit(f"Depiction template does not exist: {template_path}")

    template = Chem.MolFromMolFile(str(template_path), sanitize=True, removeHs=False)
    if template is None:
        raise SystemExit(f"Could not parse depiction template: {template_path}")
    if template.GetNumConformers() == 0:
        raise SystemExit(f"Depiction template has no coordinates: {template_path}")
    if template.GetConformer().Is3D():
        raise SystemExit(f"Depiction template must contain 2D coordinates: {template_path}")

    try:
        atom_map = rdDepictor.GenerateDepictionMatching2DStructure(mol, template)
    except Exception as exc:
        raise SystemExit(
            f"Could not constrain depiction to literature template {template_path}: {exc}"
        ) from exc
    return "template-constrained", str(template_path), str(len(atom_map))


def molblock_roundtrip(mol: Chem.Mol) -> tuple[bool, str]:
    block = Chem.MolToMolBlock(mol)
    restored = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
    if restored is None:
        return False, "MOL block could not be parsed after serialization"
    source = canonical_smiles(mol)
    result = canonical_smiles(restored)
    if source != result:
        return False, f"MOL round trip changed isomeric SMILES: {source} -> {result}"
    return True, ""


def phosphoramidite_warnings(mol: Chem.Mol, label: str) -> list[str]:
    """Return warnings for likely phosphoramidite ligand mistakes."""
    if "phosphoramidite" not in label.lower():
        return []

    warnings: list[str] = []
    p_atoms = [atom for atom in mol.GetAtoms() if atom.GetSymbol() == "P"]
    if len(p_atoms) != 1:
        return [f"expected one phosphorus atom, found {len(p_atoms)}"]

    p_atom = p_atoms[0]
    neighbors = [atom.GetSymbol() for atom in p_atom.GetNeighbors()]
    p_double_o = any(
        bond.GetBondTypeAsDouble() == 2.0
        and bond.GetOtherAtom(p_atom).GetSymbol() == "O"
        for bond in p_atom.GetBonds()
    )
    if p_atom.GetFormalCharge() != 0:
        warnings.append(f"phosphorus formal charge is {p_atom.GetFormalCharge()}, expected 0")
    if p_atom.GetDegree() != 3:
        warnings.append(f"phosphorus degree is {p_atom.GetDegree()}, expected 3 for P(III)")
    if neighbors.count("O") != 2 or neighbors.count("N") != 1:
        warnings.append(f"phosphorus neighbors are {neighbors}, expected two O and one N")
    if p_double_o:
        warnings.append("contains P=O; a simple phosphoramidite should be P(III)")
    return warnings


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"name", "smiles"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Missing required columns: {', '.join(sorted(missing))}")
        rows = [{key: (value or "") for key, value in row.items()} for row in reader]
    if not rows:
        raise SystemExit("Input CSV contains no structures")
    return rows


def prepare_molecule(
    row: dict[str, str], input_dir: Path
) -> tuple[Chem.Mol, dict[str, str]]:
    name = row["name"].strip()
    smiles = row["smiles"].strip()
    if not name or not smiles:
        raise SystemExit("Every row requires non-empty name and smiles values")

    mol = Chem.MolFromSmiles(smiles, sanitize=True)
    if mol is None:
        raise SystemExit(f"Could not parse or sanitize SMILES for {name}: {smiles}")

    expected_cip = row.get("expected_cip", "").strip()
    note = row.get("note", "").strip()
    centers = chiral_centers(mol)
    if expected_cip and any(cip == "?" for _, cip in centers):
        raise SystemExit(f"Unassigned stereocenter for {name}: {centers!r}")
    if not expected_matches(centers, expected_cip):
        raise SystemExit(
            f"Unexpected stereochemistry for {name}: expected {expected_cip!r}, "
            f"observed {centers!r}"
        )

    depiction_method, template_path, constrained_atoms = generate_2d_coordinates(
        mol, row, input_dir
    )
    roundtrip_ok, roundtrip_warning = molblock_roundtrip(mol)
    if not roundtrip_ok:
        raise SystemExit(f"Serialization validation failed for {name}: {roundtrip_warning}")

    warnings = phosphoramidite_warnings(mol, f"{name} {note}")
    confidence = row.get("confidence", "").strip().lower()
    if confidence and confidence not in {"verified", "supported", "provisional", "unresolved"}:
        raise SystemExit(f"Invalid confidence for {name}: {confidence!r}")
    if confidence == "unresolved":
        raise SystemExit(f"Refusing to finalize unresolved structure: {name}")

    canonical = canonical_smiles(mol)
    formula = rdMolDescriptors.CalcMolFormula(mol)
    formal_charge = sum(atom.GetFormalCharge() for atom in mol.GetAtoms())
    fragments = len(Chem.GetMolFrags(mol))
    try:
        inchi_key = Chem.MolToInchiKey(mol)
    except Exception:
        inchi_key = ""

    properties = {
        "Input_SMILES": smiles,
        "Canonical_SMILES": canonical,
        "InChIKey": inchi_key,
        "Molecular_formula": formula,
        "Molecular_weight": f"{Descriptors.MolWt(mol):.3f}",
        "Formal_charge": str(formal_charge),
        "Fragment_count": str(fragments),
        "Chiral_centers": str(centers),
        "Expected_CIP": expected_cip,
        "Depiction_method": depiction_method,
        "Template_mol": template_path,
        "Constrained_atoms": constrained_atoms,
        "Depiction_reference_URL": row.get("depiction_reference_url", "").strip(),
        "Literature_examples": row.get("literature_examples", "").strip(),
        "Literature_consensus": row.get("literature_consensus", "").strip(),
        "Source_URL": row.get("source_url", "").strip(),
        "Source_ID": row.get("source_id", "").strip(),
        "Source_role": row.get("source_role", "").strip(),
        "Secondary_source_URL": row.get("secondary_source_url", "").strip(),
        "Secondary_source_ID": row.get("secondary_source_id", "").strip(),
        "Accessed_at": row.get("accessed_at", "").strip(),
        "Confidence": confidence,
        "Representation_limits": row.get("representation_limits", "").strip(),
        "Warnings": "; ".join(warnings),
        "Note": note,
    }
    mol.SetProp("_Name", name)
    for key, value in properties.items():
        if value:
            mol.SetProp(key, value)

    manifest = {"name": name, **{key.lower(): value for key, value in properties.items()}}
    manifest["roundtrip_valid"] = "true"
    return mol, manifest


def validate_sdf(path: Path, expected: list[Chem.Mol]) -> None:
    restored = [mol for mol in Chem.SDMolSupplier(str(path), removeHs=False) if mol is not None]
    if len(restored) != len(expected):
        raise SystemExit(
            f"SDF validation failed: expected {len(expected)} records, read {len(restored)}"
        )
    for index, (source, result) in enumerate(zip(expected, restored), start=1):
        if canonical_smiles(source) != canonical_smiles(result):
            raise SystemExit(f"SDF round trip changed structure at record {index}")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: create_chemdraw_structures.py input.csv output_dir", file=sys.stderr)
        return 2

    input_csv = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty; choose or clear a run directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    prepared = [prepare_molecule(row, input_csv.resolve().parent) for row in read_rows(input_csv)]
    mols = [item[0] for item in prepared]
    manifest = [item[1] for item in prepared]
    used_names: set[str] = set()

    for mol, record in zip(mols, manifest):
        mol_file = unique_filename(record["name"], used_names)
        (out_dir / mol_file).write_text(Chem.MolToMolBlock(mol), encoding="utf-8")
        record["mol_file"] = mol_file

    sdf_path = out_dir / f"{out_dir.name}.sdf"
    writer = Chem.SDWriter(str(sdf_path))
    for mol in mols:
        writer.write(mol)
    writer.close()
    validate_sdf(sdf_path, mols)

    manifest_path = out_dir / "manifest.csv"
    fieldnames = list(manifest[0].keys())
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        csv_writer = csv.DictWriter(handle, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(manifest)

    preview_path = out_dir / "preview.png"
    per_row = 1 if len(mols) <= 3 else 2
    image = Draw.MolsToGridImage(
        mols,
        molsPerRow=per_row,
        subImgSize=(850, 430),
        legends=[mol.GetProp("_Name") for mol in mols],
    )
    image.save(str(preview_path))

    zip_path = out_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out_dir.iterdir()):
            archive.write(path, arcname=f"{out_dir.name}/{path.name}")

    for path in (sdf_path, manifest_path, preview_path, zip_path):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
