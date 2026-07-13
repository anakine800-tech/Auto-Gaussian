#!/usr/bin/env python3
"""Compare version-controlled Skill sources with installed runtime copies."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


IGNORED_NAMES = {".DS_Store", "__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def included(path: Path) -> bool:
    return not any(part in IGNORED_NAMES for part in path.parts) and path.suffix not in IGNORED_SUFFIXES


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        str(path.relative_to(root)): digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and included(path.relative_to(root))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="repository root containing skills/",
    )
    parser.add_argument(
        "--installed-root",
        default=str(Path.home() / ".codex" / "skills"),
        help="installed Codex Skill root",
    )
    parser.add_argument("--skill", action="append", dest="skills")
    args = parser.parse_args()

    source_root = Path(args.repo_root).expanduser().resolve() / "skills"
    installed_root = Path(args.installed_root).expanduser().resolve()
    names = args.skills or sorted(
        path.name for path in source_root.iterdir() if (path / "SKILL.md").is_file()
    )
    drift = False
    for name in names:
        source = inventory(source_root / name)
        installed = inventory(installed_root / name)
        missing = sorted(set(source) - set(installed))
        extra = sorted(set(installed) - set(source))
        changed = sorted(path for path in set(source) & set(installed) if source[path] != installed[path])
        if missing or extra or changed:
            drift = True
            print(f"{name}: DRIFT")
            for label, paths in (
                ("missing-installed", missing),
                ("extra-installed", extra),
                ("changed", changed),
            ):
                for path in paths:
                    print(f"  {label}: {path}")
        else:
            print(f"{name}: synchronized ({len(source)} files)")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
