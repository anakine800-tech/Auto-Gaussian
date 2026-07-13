#!/usr/bin/env python3
"""Create ChemDraw-compatible MOL/SDF files from a CSV of names and SMILES."""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Descriptors, Draw, rdDepictor, rdMolDescriptors


if hasattr(rdDepictor, "SetPreferCoordGen"):
    rdDepictor.SetPreferCoordGen(True)


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return slug.strip("_") or "structure"


def chiral_centers(mol: Chem.Mol) -> list[tuple[int, str]]:
    Chem.AssignStereochemistry(mol, force=True, cleanIt=True)
    return Chem.FindMolChiralCenters(
        mol, includeUnassigned=True, useLegacyImplementation=False
    )


def expected_matches(centers: list[tuple[int, str]], expected: str) -> bool:
    expected = expected.strip()
    if not expected:
        return True
    observed = ",".join(cip for _, cip in centers)
    return observed == expected


def phosphoramidite_warnings(mol: Chem.Mol, label: str) -> list[str]:
    """Return warnings for likely phosphoramidite ligand mistakes."""
    text = label.lower()
    if "phosphoramidite" not in text and "phosphoramidite" not in Chem.MolToSmiles(mol):
        return []

    warnings: list[str] = []
    p_atoms = [atom for atom in mol.GetAtoms() if atom.GetSymbol() == "P"]
    if len(p_atoms) != 1:
        warnings.append(f"expected one phosphorus atom, found {len(p_atoms)}")
        return warnings

    p_atom = p_atoms[0]
    neighbors = [atom.GetSymbol() for atom in p_atom.GetNeighbors()]
    p_o = neighbors.count("O")
    p_n = neighbors.count("N")
    p_double_o = any(
        bond.GetBondTypeAsDouble() == 2.0
        and bond.GetOtherAtom(p_atom).GetSymbol() == "O"
        for bond in p_atom.GetBonds()
    )

    if p_atom.GetFormalCharge() != 0:
        warnings.append(f"phosphorus formal charge is {p_atom.GetFormalCharge()}, expected 0")
    if p_atom.GetDegree() != 3:
        warnings.append(f"phosphorus degree is {p_atom.GetDegree()}, expected 3 for P(III)")
    if p_o != 2 or p_n != 1:
        warnings.append(f"phosphorus neighbors are {neighbors}, expected two O and one N")
    if p_double_o:
        warnings.append("contains P=O; simple phosphoramidite ligands should be P(III), not phosphoryl")

    return warnings


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"name", "smiles"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Missing required columns: {', '.join(sorted(missing))}")
        return [dict(row) for row in reader]


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: create_chemdraw_structures.py input.csv output_dir",
            file=sys.stderr,
        )
        return 2

    input_csv = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_rows(input_csv)
    mols: list[Chem.Mol] = []
    manifest: list[dict[str, str]] = []

    for row in rows:
        name = row["name"].strip()
        smiles = row["smiles"].strip()
        expected_cip = row.get("expected_cip", "").strip()
        note = row.get("note", "").strip()

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise SystemExit(f"Could not parse SMILES for {name}: {smiles}")

        rdDepictor.Compute2DCoords(mol)
        centers = chiral_centers(mol)
        if not expected_matches(centers, expected_cip):
            raise SystemExit(
                f"Unexpected stereochemistry for {name}: expected "
                f"{expected_cip!r}, observed {centers!r}"
            )
        warnings = phosphoramidite_warnings(mol, f"{name} {note}")

        formula = rdMolDescriptors.CalcMolFormula(mol)
        mol_wt = f"{Descriptors.MolWt(mol):.3f}"
        canonical = Chem.MolToSmiles(mol, isomericSmiles=True)

        mol.SetProp("_Name", name)
        mol.SetProp("Input_SMILES", smiles)
        mol.SetProp("Canonical_SMILES", canonical)
        mol.SetProp("Molecular_formula", formula)
        mol.SetProp("Molecular_weight", mol_wt)
        mol.SetProp("Chiral_centers", str(centers))
        if warnings:
            mol.SetProp("Warnings", "; ".join(warnings))
        if note:
            mol.SetProp("Note", note)

        mol_file = f"{slugify(name)}.mol"
        (out_dir / mol_file).write_text(Chem.MolToMolBlock(mol), encoding="utf-8")
        mols.append(mol)
        manifest.append(
            {
                "name": name,
                "formula": formula,
                "mol_wt": mol_wt,
                "chiral_centers": str(centers),
                "expected_cip": expected_cip,
                "canonical_smiles": canonical,
                "mol_file": mol_file,
                "warnings": "; ".join(warnings),
                "note": note,
            }
        )

    sdf_path = out_dir / f"{out_dir.name}.sdf"
    writer = Chem.SDWriter(str(sdf_path))
    for mol in mols:
        writer.write(mol)
    writer.close()

    manifest_path = out_dir / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(manifest[0].keys()) if manifest else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest)

    preview_path = out_dir / "preview.png"
    if mols:
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

    print(sdf_path)
    print(manifest_path)
    print(preview_path)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
