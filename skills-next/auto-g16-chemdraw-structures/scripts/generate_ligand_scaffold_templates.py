#!/usr/bin/env python3
"""Generate the built-in ligand-scaffold prototypes and their review sheet."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from urllib.parse import quote
from urllib.request import urlretrieve
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import Draw, rdDepictor
from rdkit.Chem.Scaffolds import MurckoScaffold


SKILL_ROOT = Path(__file__).resolve().parent.parent
CATALOG = SKILL_ROOT / "references" / "common-ligand-scaffolds.json"


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


def expected_cip(molecule: Chem.Mol) -> dict[str, str]:
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    return {
        str(atom.GetIdx()): atom.GetProp("_CIPCode")
        for atom in molecule.GetAtoms()
        if atom.HasProp("_CIPCode")
    }


def pubchem_2d(name: str) -> Chem.Mol:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(name, safe='')}/SDF?record_type=2d"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "record.sdf"
        urlretrieve(url, path)
        molecule = Chem.MolFromMolFile(str(path), sanitize=True, removeHs=True)
    if molecule is None:
        raise SystemExit(f"PubChem returned an unreadable 2D record for {name}")
    return molecule


def build(catalog_path: Path, contact_sheet: Path | None, refresh_pubchem: bool) -> None:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    molecules: list[Chem.Mol] = []
    legends: list[str] = []
    skipped: list[str] = []
    for entry in entries:
        molecule = Chem.MolFromSmiles(str(entry["smiles"]))
        if molecule is None:
            raise SystemExit(f"Invalid SMILES for {entry.get('key')}: {entry.get('smiles')}")
        entry["canonical_smiles"] = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
        scaffold = MurckoScaffold.GetScaffoldForMol(molecule)
        entry["scaffold_smiles"] = (
            Chem.MolToSmiles(scaffold, canonical=True, isomericSmiles=True)
            if scaffold.GetNumAtoms()
            else ""
        )
        destination_name = entry.get("template_mol")
        if not destination_name:
            if not entry.get("native_review_required"):
                raise SystemExit(f"Missing template without native-review policy: {entry.get('key')}")
            entry.pop("expected_cip", None)
            skipped.append(str(entry["key"]))
            continue

        destination = SKILL_ROOT / str(destination_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if refresh_pubchem and entry.get("pubchem_2d_name"):
            sourced = pubchem_2d(str(entry["pubchem_2d_name"]))
            expected = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
            observed = Chem.MolToSmiles(sourced, canonical=True, isomericSmiles=True)
            if expected != observed:
                raise SystemExit(
                    f"PubChem 2D identity mismatch for {entry['key']}: expected {expected}, observed {observed}"
                )
            molecule = sourced
            entry["coordinate_provenance"] = "PubChem PUG REST 2D record"
        elif entry.get("preserve_curated_coordinates") and destination.exists():
            sourced = Chem.MolFromMolFile(str(destination), sanitize=True, removeHs=True)
            if sourced is None:
                raise SystemExit(f"Unreadable curated template: {destination}")
            molecule = sourced
        else:
            rdDepictor.Compute2DCoords(molecule, canonOrient=True)
            transform(molecule, entry)
            if expected_cip(molecule):
                Chem.WedgeMolBonds(molecule, molecule.GetConformer())
        cips = expected_cip(molecule)
        if cips:
            entry["expected_cip"] = cips
        else:
            entry.pop("expected_cip", None)
        Chem.MolToMolFile(molecule, str(destination), kekulize=True)
        molecules.append(molecule)
        legends.append(str(entry["key"]))

    data["count"] = len(entries)
    catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if contact_sheet:
        contact_sheet.parent.mkdir(parents=True, exist_ok=True)
        image = Draw.MolsToGridImage(
            molecules,
            molsPerRow=4,
            subImgSize=(360, 280),
            legends=legends,
            useSVG=False,
        )
        image.save(contact_sheet)
    print(json.dumps({"catalog_entries": len(entries), "templates": len(molecules), "native_only": skipped}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument(
        "--refresh-pubchem",
        action="store_true",
        help="Refresh selected literature-style 2D coordinates from PubChem and cache them in the skill.",
    )
    args = parser.parse_args()
    build(
        args.catalog.resolve(),
        args.contact_sheet.resolve() if args.contact_sheet else None,
        args.refresh_pubchem,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
