#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def centers(mol: Chem.Mol) -> list[dict[str, object]]:
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    return [
        {"atom_index": int(index), "cip": cip}
        for index, cip in Chem.FindMolChiralCenters(
            mol, includeUnassigned=True, useLegacyImplementation=False
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve one unassigned tetrahedral center to a requested CIP descriptor."
    )
    parser.add_argument("input")
    parser.add_argument("--atom-index", type=int, required=True)
    parser.add_argument("--target-cip", choices=("R", "S"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stem", required=True)
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mol = Chem.MolFromMolFile(str(source), removeHs=False)
    if mol is None:
        raise SystemExit(f"Could not read molecule: {source}")

    original_centers = centers(Chem.Mol(mol))
    original_assigned_indices = {
        int(item["atom_index"])
        for item in original_centers
        if item["cip"] != "?" and int(item["atom_index"]) != args.atom_index
    }
    original_tags = {
        index: int(mol.GetAtomWithIdx(index).GetChiralTag())
        for index in original_assigned_indices
    }

    target_atom = mol.GetAtomWithIdx(args.atom_index)
    selected_tag = None
    for tag in (
        Chem.ChiralType.CHI_TETRAHEDRAL_CW,
        Chem.ChiralType.CHI_TETRAHEDRAL_CCW,
    ):
        candidate = Chem.Mol(mol)
        candidate.GetAtomWithIdx(args.atom_index).SetChiralTag(tag)
        candidate_centers = centers(candidate)
        descriptor = next(
            (
                item["cip"]
                for item in candidate_centers
                if item["atom_index"] == args.atom_index
            ),
            None,
        )
        if descriptor == args.target_cip:
            selected_tag = tag
            break

    if selected_tag is None:
        raise SystemExit(
            f"Could not assign atom {args.atom_index} as {args.target_cip}"
        )

    target_atom.SetChiralTag(selected_tag)
    final_centers_before_write = centers(mol)
    if any(item["cip"] == "?" for item in final_centers_before_write):
        raise SystemExit("Unassigned tetrahedral stereochemistry remains")

    sdf_path = output_dir / f"{args.stem}.sdf"
    mol_path = output_dir / f"{args.stem}.mol"
    preview_path = output_dir / f"{args.stem}.png"
    report_path = output_dir / f"{args.stem}.json"

    writer = Chem.SDWriter(str(sdf_path))
    writer.write(mol)
    writer.close()
    mol_path.write_text(Chem.MolToMolBlock(mol), encoding="utf-8")
    Draw.MolToFile(
        mol,
        str(preview_path),
        size=(1400, 900),
        legend=f"{args.stem}: atom {args.atom_index} assigned {args.target_cip}",
    )

    roundtrip = Chem.MolFromMolFile(str(sdf_path), removeHs=False)
    if roundtrip is None:
        raise SystemExit("Could not read the corrected SDF after writing")
    final_centers = centers(roundtrip)
    final_target = next(
        (
            item["cip"]
            for item in final_centers
            if item["atom_index"] == args.atom_index
        ),
        None,
    )
    if final_target != args.target_cip:
        raise SystemExit(
            f"Round-trip CIP mismatch at atom {args.atom_index}: {final_target}"
        )

    retained_tags = {
        str(index): (
            int(roundtrip.GetAtomWithIdx(index).GetChiralTag()) == original_tags[index]
        )
        for index in sorted(original_assigned_indices)
    }
    if not all(retained_tags.values()):
        raise SystemExit("An existing assigned stereochemical tag changed on round trip")

    report = {
        "source": str(source),
        "source_sha256": sha256(source),
        "requested_assignment": {
            "atom_index": args.atom_index,
            "target_cip": args.target_cip,
        },
        "original_centers": original_centers,
        "final_centers": final_centers,
        "existing_chiral_tags_retained": retained_tags,
        "canonical_isomeric_smiles": Chem.MolToSmiles(
            roundtrip, isomericSmiles=True
        ),
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
