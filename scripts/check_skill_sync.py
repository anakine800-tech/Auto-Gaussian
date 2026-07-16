#!/usr/bin/env python3
"""Compare version-controlled Skill sources with installed runtime copies."""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from skill_package import PackageError, inventory, package_inventory


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

    print(
        f"runtime: python={Path(sys.executable).resolve()} "
        f"version={platform.python_version()}"
    )

    repo_root = Path(args.repo_root).expanduser().resolve()
    source_root = repo_root / "skills"
    installed_root = Path(args.installed_root).expanduser().resolve()
    names = args.skills or sorted(
        path.name for path in source_root.iterdir() if (path / "SKILL.md").is_file()
    )
    drift = False
    for name in names:
        try:
            source = package_inventory(repo_root, name)
        except PackageError as exc:
            print(f"{name}: INVALID PACKAGE: {exc}")
            drift = True
            continue
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
