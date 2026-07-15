#!/usr/bin/env python3
"""Audit the portable Gaussian learning skill for integrity and privacy."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CARD_PATTERN = re.compile(r"^#{2,4}\s+(GKB-\d{4})\b", re.MULTILINE)
FORBIDDEN_CONTENT = {
    "provenance identifier": re.compile(r"SRC-\d{4}"),
    "citation field": re.compile(r"(?:来源|验证等级|推导来源)："),
    "internal classification": re.compile(r"source-stated|obsolete-context", re.I),
    "local absolute path": re.compile(r"/" r"Users/[^\s`]+"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "credential label": re.compile(r"账号|密码"),
}
DISALLOWED_SUFFIXES = {".pdf", ".ppt", ".pptx", ".jsonl", ".key"}
REQUIRED_REFERENCES = {
    "knowledge-map.md",
    "learning-roadmap.md",
    "theory-and-methods.md",
    "basis-sets.md",
    "gaussian-input-output.md",
    "core-job-types.md",
    "advanced-properties.md",
    "research-workflow.md",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, help="Defaults to the parent of scripts/")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    root = (args.skill_root or Path(__file__).resolve().parents[1]).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    references = root / "references"

    for required in (root / "SKILL.md", root / "agents" / "openai.yaml", references):
        if not required.exists():
            errors.append(f"missing required path: {required.relative_to(root)}")

    present_references = {path.name for path in references.glob("*.md")} if references.is_dir() else set()
    for name in sorted(REQUIRED_REFERENCES - present_references):
        errors.append(f"missing required reference: {name}")

    files = [path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    for path in files:
        if path.suffix.casefold() in DISALLOWED_SUFFIXES:
            errors.append(f"non-portable source artifact included: {path.relative_to(root)}")

    cards: dict[str, str] = {}
    scan_paths = [root / "SKILL.md", root / "agents" / "openai.yaml"]
    scan_paths.extend(sorted(references.glob("*.md")) if references.is_dir() else [])
    for path in scan_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            errors.append(f"empty file: {path.relative_to(root)}")
        for label, pattern in FORBIDDEN_CONTENT.items():
            if pattern.search(text):
                errors.append(f"{path.relative_to(root)} contains {label}")
        for card_id in CARD_PATTERN.findall(text):
            if card_id in cards:
                errors.append(
                    f"duplicate knowledge card {card_id}: {cards[card_id]} and {path.relative_to(root)}"
                )
            cards[card_id] = str(path.relative_to(root))
        if path.parent == references and len(text.splitlines()) > 100 and "## 目录" not in text:
            errors.append(f"long reference lacks a contents section: {path.name}")

    if len(cards) != 72:
        errors.append(f"expected 72 knowledge cards, found {len(cards)}")

    skill_text = (root / "SKILL.md").read_text(encoding="utf-8", errors="replace") if (root / "SKILL.md").is_file() else ""
    if not skill_text.startswith("---\nname: auto-g16-gaussian-learning-library\n"):
        errors.append("SKILL.md frontmatter name is missing or invalid")
    if "Do not add a source or references section." not in skill_text:
        warnings.append("the no-citation answer rule is not stated verbatim")

    report = {
        "ok": not errors,
        "knowledge_card_count": len(cards),
        "reference_count": len(present_references),
        "file_count": len(files),
        "errors": errors,
        "warnings": warnings,
    }
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Audit {'passed' if report['ok'] else 'failed'}: {len(cards)} knowledge cards")
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
