#!/usr/bin/env python3
# Source: skills/auto-g16-view-rt-win/scripts/prepare_preview.py (T4 migration).
"""Read a structure and write its identity summary and 2D preview for milestone 1."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cdx_stereo import molblock_stereo_roundtrip, structure_stereo_invariants
from make_gaussian_input import load_rdkit, read_molecule, validate_scope, validate_multiplicity, output_directory


def prepare(source, study, name, multiplicity):
    validate_multiplicity(multiplicity)
    Chem, AllChem, Descriptors, rdMolDescriptors = load_rdkit()
    from rdkit.Chem import Draw

    # Read ChemDraw directly, never through a potentially lossy MOL/SDF round trip.
    mol, origin, diagnostics = read_molecule(source, Chem)
    validate_scope(mol, Chem, diagnostics)
    identity = structure_stereo_invariants(mol, Chem, rdMolDescriptors, diagnostics[0] if diagnostics else None)
    roundtrip = molblock_stereo_roundtrip(mol, Chem)
    warnings = ["Axial/atropisomeric chirality is not validated; inspect the source drawing explicitly."]
    if identity["boron_atom_count"]:
        warnings.append("Boron may require UFF fallback; review the force field and geometry after screening.")
    if not roundtrip["stereo_preserved"]:
        warnings.append("MOL/SDF serialization changes stereochemistry; use the original source or stereo.smi downstream.")
    source_path = Path(source).expanduser()
    report = {**identity, "charge": int(Chem.GetFormalCharge(mol)), "multiplicity": multiplicity,
              "molecular_weight": round(float(Descriptors.MolWt(mol)), 6),
              "explicit_h_atom_count": Chem.AddHs(mol).GetNumAtoms(),
              "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path.is_file() else None,
              "cdx_stereo_import": diagnostics[0] if diagnostics else None,
              "molblock_stereo_roundtrip": roundtrip, "warnings": warnings,
              "preview": "preview.png", "stereo_smiles": "stereo.smi"}
    out = output_directory(study, name)
    (out / "imported.mol").write_text(Chem.MolToMolBlock(mol), encoding="utf-8")
    with Chem.SDWriter(str(out / "imported.sdf")) as writer:
        writer.write(mol)
    Draw.MolToFile(mol, str(out / "preview.png"), size=(1400, 900), legend=name)
    (out / "stereo.smi").write_text(identity["canonical_isomeric_smiles"] + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(out), **report}, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="ChemDraw/MOL/SDF/SMILES file or unambiguous SMILES")
    parser.add_argument("--study", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--multiplicity", type=int, required=True, help="From the researcher or study.md")
    args = parser.parse_args()
    return prepare(args.source, args.study, args.name, args.multiplicity)


if __name__ == "__main__":
    raise SystemExit(main())
