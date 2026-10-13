#!/usr/bin/env python3
"""Generate and canonicalize the built-in common-scaffold depiction templates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import Draw, rdDepictor
from rdkit.Chem.Scaffolds import MurckoScaffold


SKILL_ROOT = Path(__file__).resolve().parent.parent
CATALOG = SKILL_ROOT / "references" / "common-depictions.json"


def transform(molecule: Chem.Mol, spec: dict[str, Any]) -> None:
    conf = molecule.GetConformer()
    coords = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y) for i in range(molecule.GetNumAtoms())]
    cx = sum(x for x, _ in coords) / len(coords)
    cy = sum(y for _, y in coords) / len(coords)
    settings = spec.get("template_transform", {})
    angle = math.radians(float(settings.get("rotate", 0.0)))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    mirror_x = -1.0 if settings.get("mirror_x", False) else 1.0
    mirror_y = -1.0 if settings.get("mirror_y", False) else 1.0
    for idx, (x, y) in enumerate(coords):
        x = (x - cx) * mirror_x
        y = (y - cy) * mirror_y
        conf.SetAtomPosition(idx, (x * cos_a - y * sin_a, x * sin_a + y * cos_a, 0.0))


def build(catalog_path: Path, contact_sheet: Path | None) -> None:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    molecules: list[Chem.Mol] = []
    legends: list[str] = []
    for entry in entries:
        molecule = Chem.MolFromSmiles(str(entry["smiles"]))
        if molecule is None:
            raise SystemExit(f"Invalid SMILES for {entry.get('key')}: {entry.get('smiles')}")
        canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
        scaffold = MurckoScaffold.GetScaffoldForMol(molecule)
        entry["canonical_smiles"] = canonical
        entry["scaffold_smiles"] = (
            Chem.MolToSmiles(scaffold, canonical=True, isomericSmiles=True)
            if scaffold.GetNumAtoms()
            else ""
        )
        rdDepictor.Compute2DCoords(molecule, canonOrient=True)
        transform(molecule, entry)
        destination = SKILL_ROOT / str(entry["template_mol"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        # V2000 templates are stored in a Kekule form so [nH]-containing azoles
        # survive strict Mol-file sanitization in every downstream RDKit path.
        Chem.MolToMolFile(molecule, str(destination), kekulize=True)
        molecules.append(molecule)
        legends.append(str(entry["key"]))
    data["count"] = len(entries)
    catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if contact_sheet:
        contact_sheet.parent.mkdir(parents=True, exist_ok=True)
        image = Draw.MolsToGridImage(
            molecules,
            molsPerRow=5,
            subImgSize=(300, 230),
            legends=legends,
            useSVG=False,
        )
        image.save(contact_sheet)
    print(json.dumps({"generated": len(entries), "catalog": str(catalog_path)}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--contact-sheet", type=Path)
    args = parser.parse_args()
    build(args.catalog.resolve(), args.contact_sheet.resolve() if args.contact_sheet else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
