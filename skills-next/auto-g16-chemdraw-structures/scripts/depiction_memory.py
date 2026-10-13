#!/usr/bin/env python3
"""Persistent lookup/record utility for user-approved ChemDraw depiction conventions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold


SKILL_ROOT = Path(__file__).resolve().parent.parent
BUILT_IN_CATALOGS = {
    "common": SKILL_ROOT / "references" / "common-depictions.json",
    "ligand-scaffold": SKILL_ROOT / "references" / "common-ligand-scaffolds.json",
}


def memory_root() -> Path:
    configured = os.environ.get("CHEMDRAW_DEPICTION_MEMORY")
    return Path(configured).expanduser().resolve() if configured else Path.cwd() / ".chemdraw-depiction-memory"


def canonicalize(smiles: str) -> tuple[str, str]:
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise SystemExit(f"Invalid SMILES: {smiles}")
    canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    scaffold = MurckoScaffold.GetScaffoldForMol(molecule)
    scaffold_smiles = Chem.MolToSmiles(scaffold, canonical=True, isomericSmiles=True) if scaffold.GetNumAtoms() else ""
    return canonical, scaffold_smiles


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read depiction memory {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
        raise SystemExit(f"Invalid depiction memory schema: {path}")
    return data


def built_in_entries(catalog_filter: str | None = None) -> list[dict[str, Any]]:
    result = []
    for catalog, source in BUILT_IN_CATALOGS.items():
        if catalog_filter and catalog != catalog_filter:
            continue
        entries = load_json(source, {"entries": []}).get("entries", [])
        for raw in entries:
            entry = dict(raw)
            entry["catalog"] = catalog
            template = str(entry.get("template_mol", "")).strip()
            if template:
                path = Path(template)
                if not path.is_absolute():
                    path = SKILL_ROOT / path
                entry["template_mol"] = str(path.resolve())
            result.append(entry)
    return result


def combined_entries(root: Path) -> list[dict[str, Any]]:
    built_in = built_in_entries()
    user = load_json(root / "index.json", {"entries": []}).get("entries", [])
    return [*user, *built_in]


def command_init(root: Path) -> None:
    (root / "templates").mkdir(parents=True, exist_ok=True)
    index = root / "index.json"
    if not index.exists():
        index.write_text('{"version": 1, "entries": []}\n', encoding="utf-8")
    print(root)


def find_matches(root: Path, name: str | None, smiles: str | None) -> list[dict[str, Any]]:
    query_name = (name or "").strip().casefold()
    canonical = scaffold = ""
    if smiles:
        canonical, scaffold = canonicalize(smiles)
    matches = []
    for entry in combined_entries(root):
        names = [str(value).casefold() for value in entry.get("names", [])]
        score = 0
        match = ""
        if canonical and entry.get("canonical_smiles") == canonical:
            score, match = 100, "exact-structure"
        elif scaffold and entry.get("scaffold_smiles") == scaffold:
            score, match = 80, "scaffold"
        elif query_name and (query_name == str(entry.get("key", "")).casefold() or query_name in names):
            score, match = 60, "name"
        elif query_name and any(
            len(query_name) >= 3
            and len(value) >= 3
            and (query_name in value or value in query_name)
            for value in names
            if value
        ):
            score, match = 40, "name-partial"
        if score:
            item = dict(entry)
            item["match"] = match
            item["score"] = score
            matches.append(item)
    matches.sort(key=lambda item: (-int(item["score"]), str(item.get("key", ""))))
    return matches[:5]


def command_lookup(root: Path, names: list[str], smiles_values: list[str]) -> None:
    queries = [
        *({"name": value, "smiles": None} for value in names),
        *({"name": None, "smiles": value} for value in smiles_values),
    ]
    if not queries:
        raise SystemExit("lookup requires at least one --name or --smiles")
    results = [
        {
            **({"name": query["name"]} if query["name"] else {"smiles": query["smiles"]}),
            "matches": find_matches(root, query["name"], query["smiles"]),
        }
        for query in queries
    ]
    payload: dict[str, Any] = {"memory_root": str(root)}
    if len(results) == 1:
        payload.update(results[0])
    else:
        payload["queries"] = results
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_list_builtins(catalog: str | None) -> None:
    entries = built_in_entries(catalog)
    print(json.dumps({
        "count": len(entries),
        "entries": [
            {
                "key": entry.get("key"),
                "catalog": entry.get("catalog"),
                "names": entry.get("names", []),
                "canonical_smiles": entry.get("canonical_smiles", ""),
                "template_mol": entry.get("template_mol", ""),
            }
            for entry in entries
        ],
    }, ensure_ascii=False, indent=2))


def command_validate_builtins(catalog: str | None) -> None:
    entries = built_in_entries(catalog)
    errors: list[str] = []
    keys: set[str] = set()
    canonicals: set[str] = set()
    for entry in entries:
        key = str(entry.get("key", "")).strip()
        if not key or key in keys:
            errors.append(f"missing or duplicate key: {key!r}")
        keys.add(key)
        names = entry.get("names", [])
        if not isinstance(names, list) or not names:
            errors.append(f"{key}: names must be a non-empty list")
        smiles = str(entry.get("smiles", "")).strip()
        try:
            canonical, scaffold = canonicalize(smiles)
        except SystemExit as exc:
            errors.append(f"{key}: {exc}")
            continue
        if entry.get("canonical_smiles") != canonical:
            errors.append(f"{key}: canonical_smiles is stale")
        if entry.get("scaffold_smiles") != scaffold:
            errors.append(f"{key}: scaffold_smiles is stale")
        if canonical in canonicals:
            errors.append(f"{key}: duplicate canonical structure")
        canonicals.add(canonical)
        template_text = str(entry.get("template_mol", "")).strip()
        if not template_text and entry.get("native_review_required", False):
            chirality = entry.get("chirality", {})
            if chirality and not entry.get("mirror_forbidden", False):
                errors.append(f"{key}: stereo-sensitive native-only entry must forbid mirroring")
            continue
        template = Path(template_text)
        if not template.is_file():
            errors.append(f"{key}: missing template {template}")
            continue
        molecule = Chem.MolFromMolFile(str(template), sanitize=True, removeHs=False)
        if molecule is None or molecule.GetNumConformers() == 0:
            errors.append(f"{key}: unreadable template or missing coordinates")
        elif Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True) != canonical:
            errors.append(f"{key}: template structure does not match canonical_smiles")
        else:
            Chem.AssignStereochemistry(molecule, force=True, cleanIt=True)
            actual_cip = {
                str(atom.GetIdx()): atom.GetProp("_CIPCode")
                for atom in molecule.GetAtoms()
                if atom.HasProp("_CIPCode")
            }
            expected_cip = {
                str(index): str(value)
                for index, value in entry.get("expected_cip", {}).items()
            }
            if expected_cip != actual_cip:
                errors.append(f"{key}: CIP mismatch expected={expected_cip} actual={actual_cip}")
            chirality = entry.get("chirality", {})
            if chirality.get("encoding") == "visual-only":
                if not entry.get("mirror_forbidden", False) or not entry.get("native_review_required", False):
                    errors.append(f"{key}: visual-only chirality requires mirror_forbidden and native_review_required")
            conformer = molecule.GetConformer()
            if entry.get("ring_geometry") == "preserve":
                continue
            for ring in molecule.GetRingInfo().AtomRings():
                if len(ring) not in (3, 4, 5, 6):
                    continue
                points = [
                    (conformer.GetAtomPosition(index).x, conformer.GetAtomPosition(index).y)
                    for index in ring
                ]
                lengths = [
                    math.hypot(
                        points[(i + 1) % len(points)][0] - points[i][0],
                        points[(i + 1) % len(points)][1] - points[i][1],
                    )
                    for i in range(len(points))
                ]
                mean_length = sum(lengths) / len(lengths)
                side_cv = math.sqrt(
                    sum((value - mean_length) ** 2 for value in lengths) / len(lengths)
                ) / max(mean_length, 1e-12)
                target = 180.0 * (len(points) - 2) / len(points)
                angle_errors = []
                for i, point in enumerate(points):
                    left = (
                        points[i - 1][0] - point[0],
                        points[i - 1][1] - point[1],
                    )
                    right = (
                        points[(i + 1) % len(points)][0] - point[0],
                        points[(i + 1) % len(points)][1] - point[1],
                    )
                    dot = left[0] * right[0] + left[1] * right[1]
                    norms = math.hypot(*left) * math.hypot(*right)
                    cosine = max(-1.0, min(1.0, dot / max(norms, 1e-12)))
                    angle_errors.append(abs(math.degrees(math.acos(cosine)) - target))
                if side_cv > 0.03 or max(angle_errors) > 4.0:
                    errors.append(
                        f"{key}: non-regular {len(ring)}-member ring "
                        f"(side CV={side_cv:.3f}, max angle error={max(angle_errors):.1f} deg)"
                    )
    if errors:
        raise SystemExit("Built-in depiction validation failed:\n- " + "\n- ".join(errors))
    counts: dict[str, int] = {}
    for entry in entries:
        counts[str(entry.get("catalog", "unknown"))] = counts.get(str(entry.get("catalog", "unknown")), 0) + 1
    print(json.dumps({"status": "validated", "count": len(entries), "catalogs": counts}, indent=2))


def command_record(args: argparse.Namespace, root: Path) -> None:
    if args.status not in {"user-approved", "literature-reviewed"}:
        raise SystemExit("Only user-approved or literature-reviewed depictions may be recorded")
    canonical, scaffold = canonicalize(args.smiles)
    command_init(root)
    template_path = ""
    if args.template:
        source = Path(args.template).expanduser().resolve()
        molecule = Chem.MolFromMolFile(str(source), sanitize=True, removeHs=False)
        if molecule is None or molecule.GetNumConformers() == 0:
            raise SystemExit("Template must be a readable MOL file with 2D coordinates")
        if Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True) != canonical:
            raise SystemExit("Template does not match the recorded SMILES")
        key_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        destination = root / "templates" / f"{key_hash}.mol"
        shutil.copy2(source, destination)
        template_path = str(destination)
    index_path = root / "index.json"
    data = load_json(index_path, {"version": 1, "entries": []})
    entries = [entry for entry in data["entries"] if entry.get("canonical_smiles") != canonical]
    entries.append({
        "key": args.name.strip().casefold().replace(" ", "-"),
        "names": [args.name],
        "canonical_smiles": canonical,
        "scaffold_smiles": scaffold,
        "orientation": args.orientation,
        "template_mol": template_path,
        "source": args.source,
        "status": args.status,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    entries.sort(key=lambda entry: str(entry.get("key", "")))
    data["entries"] = entries
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(index_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    lookup = subparsers.add_parser("lookup")
    lookup.add_argument("--name", action="append", default=[])
    lookup.add_argument("--smiles", action="append", default=[])
    list_builtins = subparsers.add_parser("list-builtins")
    list_builtins.add_argument("--catalog", choices=sorted(BUILT_IN_CATALOGS))
    validate_builtins = subparsers.add_parser("validate-builtins")
    validate_builtins.add_argument("--catalog", choices=sorted(BUILT_IN_CATALOGS))
    record = subparsers.add_parser("record")
    record.add_argument("--name", required=True)
    record.add_argument("--smiles", required=True)
    record.add_argument("--orientation", required=True)
    record.add_argument("--source", required=True)
    record.add_argument("--status", required=True)
    record.add_argument("--template")
    args = parser.parse_args()
    root = memory_root()
    if args.command == "init":
        command_init(root)
    elif args.command == "lookup":
        command_lookup(root, args.name, args.smiles)
    elif args.command == "list-builtins":
        command_list_builtins(args.catalog)
    elif args.command == "validate-builtins":
        command_validate_builtins(args.catalog)
    else:
        command_record(args, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
