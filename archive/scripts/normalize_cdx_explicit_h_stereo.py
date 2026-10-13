#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Descriptors, Draw, rdMolDescriptors


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def chiral_centers(mol: Chem.Mol) -> list[dict[str, object]]:
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    return [
        {"atom_index": int(index), "cip": cip}
        for index, cip in Chem.FindMolChiralCenters(
            mol, includeUnassigned=True, useLegacyImplementation=False
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preserve explicit-H CDX wedge CFG values in a reviewed SDF."
    )
    parser.add_argument("source")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stem", required=True)
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    molecules = list(Chem.MolsFromCDXMLFile(str(source), True, False))
    if len(molecules) != 1:
        raise SystemExit(f"Expected one molecule, found {len(molecules)}")
    mol = molecules[0]

    applied_cfg: list[dict[str, object]] = []
    for bond in mol.GetBonds():
        if not bond.HasProp("_MolFileBondCfg"):
            continue
        cfg = bond.GetIntProp("_MolFileBondCfg")
        if cfg == 1:
            direction = Chem.BondDir.BEGINWEDGE
        elif cfg == 3:
            direction = Chem.BondDir.BEGINDASH
        else:
            raise SystemExit(
                f"Unsupported or ambiguous MolFile bond CFG={cfg} on bond {bond.GetIdx()}"
            )
        bond.SetBondDir(direction)
        applied_cfg.append(
            {
                "bond_index": bond.GetIdx(),
                "begin_atom": bond.GetBeginAtomIdx(),
                "end_atom": bond.GetEndAtomIdx(),
                "cfg": cfg,
                "bond_dir": str(direction),
            }
        )

    Chem.AssignChiralTypesFromBondDirs(mol, replaceExistingTags=False)
    centers_before_write = chiral_centers(mol)
    unresolved = [item for item in centers_before_write if item["cip"] == "?"]
    if unresolved:
        raise SystemExit(f"Unassigned stereochemistry remains: {unresolved}")

    sdf_path = output_dir / f"{args.stem}.sdf"
    mol_path = output_dir / f"{args.stem}.mol"
    preview_path = output_dir / f"{args.stem}.png"
    report_path = output_dir / f"{args.stem}.json"

    writer = Chem.SDWriter(str(sdf_path))
    writer.SetForceV3000(True)
    writer.write(mol)
    writer.close()
    mol_path.write_text(
        Chem.MolToMolBlock(mol, forceV3000=True, includeStereo=True),
        encoding="utf-8",
    )
    Draw.MolToFile(
        mol,
        str(preview_path),
        size=(1400, 900),
        legend=f"{args.stem}: explicit-H CDX wedge CFG preserved",
    )

    roundtrip = Chem.MolFromMolFile(str(sdf_path), removeHs=False)
    if roundtrip is None:
        raise SystemExit("Could not read normalized SDF after writing")
    centers_after_write = chiral_centers(roundtrip)
    if centers_after_write != centers_before_write:
        raise SystemExit(
            "Stereochemistry changed on SDF round trip: "
            f"before={centers_before_write}, after={centers_after_write}"
        )

    smiles_mol = Chem.RemoveHs(Chem.Mol(roundtrip))
    report = {
        "schema": "cdx-explicit-h-stereo/1",
        "source": str(source),
        "source_sha256": sha256(source),
        "explicit_hydrogens_preserved": True,
        "applied_molfile_cfg": applied_cfg,
        "chiral_centers": centers_after_write,
        "canonical_isomeric_smiles": Chem.MolToSmiles(
            smiles_mol, isomericSmiles=True
        ),
        "formula": rdMolDescriptors.CalcMolFormula(roundtrip),
        "molecular_weight": round(float(Descriptors.MolWt(roundtrip)), 6),
        "formal_charge": Chem.GetFormalCharge(roundtrip),
        "atom_count_with_preserved_explicit_h": roundtrip.GetNumAtoms(),
        "sdf": str(sdf_path),
        "sdf_sha256": sha256(sdf_path),
        "mol": str(mol_path),
        "preview": str(preview_path),
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
