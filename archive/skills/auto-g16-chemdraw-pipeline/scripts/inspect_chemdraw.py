#!/usr/bin/env python3
"""Normalize one ChemDraw CDX/CDXML file for review before Gaussian conversion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Descriptors, Draw, rdMolDescriptors

from cdx_stereo import load_chemdraw_molecules, molblock_stereo_roundtrip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="ChemDraw .cdx or .cdxml file")
    parser.add_argument("output_dir", help="Directory for normalized review artifacts")
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() not in {".cdx", ".cdxml"}:
        raise SystemExit("input must be a .cdx or .cdxml file")
    if not Chem.HasChemDrawCDXSupport():
        raise SystemExit("This RDKit build does not include ChemDraw CDX/CDXML support")

    molecules, import_diagnostics = load_chemdraw_molecules(str(source), Chem)
    if len(molecules) != 1:
        raise SystemExit(f"Expected exactly one molecule, found {len(molecules)}")
    mol = molecules[0]
    Chem.AssignStereochemistry(mol, force=True, cleanIt=True)
    centers = Chem.FindMolChiralCenters(
        mol, includeUnassigned=True, useLegacyImplementation=False
    )

    stem = source.stem
    mol_path = out_dir / f"{stem}_imported.mol"
    sdf_path = out_dir / f"{stem}_imported.sdf"
    preview_path = out_dir / f"{stem}_imported.png"
    manifest_path = out_dir / f"{stem}_imported.json"
    smiles_path = out_dir / f"{stem}_stereo.smi"

    mol_path.write_text(Chem.MolToMolBlock(mol), encoding="utf-8")
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(mol)
    writer.close()
    Draw.MolToFile(mol, str(preview_path), size=(1400, 900), legend=f"{stem} imported from ChemDraw")
    canonical_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    smiles_path.write_text(canonical_smiles + "\n", encoding="utf-8")
    roundtrip = molblock_stereo_roundtrip(mol, Chem)
    diagnostic = import_diagnostics[0]
    import_warnings = []
    if diagnostic["conflicting_bond_cfg"]:
        import_warnings.append("Conflicting ChemDraw bond directions are present; review the source drawing.")
    if diagnostic["unsupported_bond_cfg"]:
        import_warnings.append("Unsupported ChemDraw bond CFG values are present; review the source drawing.")
    if any(cip == "?" for _, cip in centers):
        import_warnings.append(
            "Unassigned tetrahedral stereochemistry remains after preserving explicit H and restoring ChemDraw bond CFG."
        )
    artifact_warnings = []
    if not roundtrip["stereo_preserved"]:
        artifact_warnings.append(
            "MOL/SDF serialization changes stereochemistry; use the source CDX/CDXML or *_stereo.smi for calculation, not the review MOL/SDF."
        )

    manifest = {
        "source": str(source),
        "canonical_isomeric_smiles": canonical_smiles,
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "molecular_weight": round(float(Descriptors.MolWt(mol)), 6),
        "atom_count": mol.GetNumAtoms(),
        "bond_count": mol.GetNumBonds(),
        "formal_charge": Chem.GetFormalCharge(mol),
        "chiral_centers": [{"atom_index": int(i), "cip": cip} for i, cip in centers],
        "cdx_stereo_import": diagnostic,
        "warnings": import_warnings,
        "review_artifact_warnings": artifact_warnings,
        "molblock_stereo_roundtrip": roundtrip,
        "review_artifacts": {
            "mol": str(mol_path),
            "sdf": str(sdf_path),
            "preview": str(preview_path),
            "stereo_smiles": str(smiles_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for path in (mol_path, sdf_path, smiles_path, preview_path, manifest_path):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
