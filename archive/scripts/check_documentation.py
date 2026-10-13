#!/usr/bin/env python3
"""Check reviewed documentation and bind the optional chemistry work to Git."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import select_validation as selector
# Exact reviewed navigation/explanation surfaces; no suffix or directory waiver.
DOCUMENTS = frozenset({"README.md", "docs/v3/INDEX.md", "docs/documentation-guide.md"})
DOCUMENT_ROUTES = frozenset({"low-risk-readme", "low-risk-documentation"})
DOCUMENT_TESTS = {"tests.test_release_hygiene", "tests.test_documentation_validation"}


def is_lightweight(selection: dict) -> bool:
    """Internal predicate; callers must first recompute authoritative selection."""
    paths = selection["changed_paths"]
    return bool(
        paths
        and set(paths) <= DOCUMENTS
        and selection["lane"] == "focused"
        and not selection["fail_closed"]
        and selection["matched_routes"]
        and set(selection["matched_routes"]) <= DOCUMENT_ROUTES
        and set(selection["tests"]) == DOCUMENT_TESTS
        and not selection["safety_evidence"]
        and all(change["status"] == "M" and len(change["paths"]) == 1
                and change["paths"][0] in paths for change in selection["changes"])
        and len(selection["changes"]) == len(paths)
    )


def check_documents(root: Path, paths: list[str]) -> None:
    """Validate readable UTF-8 documents and local inline-link destinations.

    This is a structural check, not semantic permission or a remote URL audit.
    Independent review owns any change in meaning or authority.
    """
    root = root.resolve(strict=True)
    for relative in paths:
        if relative not in DOCUMENTS:
            raise ValueError(f"unreviewed documentation path: {relative}")
        path = root / relative
        if (any(part.is_symlink() for part in [path, *path.parents] if part != root)
                or not path.is_file() or not path.resolve().is_relative_to(root)):
            raise ValueError(f"document is not a contained regular file: {relative}")
        text = path.read_text(encoding="utf-8")
        if not text.strip() or "\0" in text or not text.startswith("# Auto-G16"):
            raise ValueError(f"invalid document content: {relative}")
        for target in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = path.parent / unquote(parsed.path)
            if (destination.is_symlink() or not destination.exists()
                    or not destination.resolve().is_relative_to(root)):
                raise ValueError(f"invalid local link in {relative}: {target}")


def chemistry_required(root: Path, base: str, head: str) -> bool:
    selection = selector.compute_selection(root, base, head)
    if not is_lightweight(selection):
        return True
    check_documents(root, selection["changed_paths"])
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    try:
        required = chemistry_required(ROOT, args.base, args.head)
    except (selector.SelectionError, OSError, UnicodeError, ValueError) as exc:
        print(f"documentation scope blocked: {exc}", file=sys.stderr)
        return 2
    print(f"chemistry-required={'true' if required else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
