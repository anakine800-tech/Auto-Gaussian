#!/usr/bin/env python3
"""Plan or apply one exact fail-closed named-Skill deployment package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from skill_package import PackageError, digest, inventory, package_files, require


def _safe_target(installed_root: Path, relative: Path) -> Path:
    root = installed_root.resolve()
    require(not installed_root.is_symlink(), "installed root must not be a symlink")
    require(not relative.is_absolute() and ".." not in relative.parts, "installed target path is unsafe")
    target = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), f"installed target contains a symlink: {current}")
    return target


def plan(
    repo_root: Path, installed_root: Path, skill_name: str
) -> tuple[dict[Path, Path], dict[str, str], dict[str, str], list[str], list[str], list[str]]:
    sources = package_files(repo_root, skill_name)
    desired = {path.as_posix(): digest(source) for path, source in sources.items()}
    installed = inventory(installed_root / skill_name)
    missing = sorted(set(desired) - set(installed))
    changed = sorted(path for path in set(desired) & set(installed) if desired[path] != installed[path])
    extra = sorted(set(installed) - set(desired))
    return sources, desired, installed, missing, changed, extra


def sync_skill(
    repo_root: Path,
    installed_root: Path,
    skill_name: str,
    *,
    apply: bool,
    confirmed: bool,
    plan_sha256: str | None = None,
) -> dict[str, object]:
    repo_root = repo_root.expanduser().resolve()
    installed_root = installed_root.expanduser()
    sources, _desired, installed, missing, changed, extra = plan(
        repo_root, installed_root, skill_name
    )
    details = {
        relative.as_posix(): {
            "source": source.relative_to(repo_root).as_posix(),
            "sha256": digest(source),
            "size_bytes": source.stat().st_size,
            "installed_sha256": installed.get(relative.as_posix()),
        }
        for relative, source in sources.items()
        if relative.as_posix() in set(missing + changed)
    }
    plan_document = {
        "schema": "auto-g16-named-skill-sync-plan/1",
        "skill": skill_name,
        "missing": missing,
        "changed": changed,
        "extra": extra,
        "details": details,
        "extra_sha256": {path: installed[path] for path in extra},
    }
    calculated_plan_sha256 = hashlib.sha256(
        (json.dumps(plan_document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    ).hexdigest()
    result: dict[str, object] = {
        "skill": skill_name,
        "missing": missing,
        "changed": changed,
        "extra": extra,
        "details": details,
        "extra_sha256": plan_document["extra_sha256"],
        "plan_sha256": calculated_plan_sha256,
        "applied": False,
    }
    if not apply:
        return result
    require(confirmed, "--apply requires --confirmed after exact plan review")
    require(
        isinstance(plan_sha256, str) and plan_sha256 == calculated_plan_sha256,
        "--apply requires the exact current dry-run --plan-sha256",
    )
    require(not extra, "refusing deployment because installed Skill has extra files")
    require(not installed_root.is_symlink(), "installed root must not be a symlink")
    root = installed_root.resolve()
    require(root.is_dir(), f"installed root does not exist: {root}")
    skill_root = _safe_target(root, Path(skill_name))
    require(not skill_root.exists() or skill_root.is_dir(), "installed Skill target is not a directory")
    skill_root.mkdir(exist_ok=True)
    for relative_text in missing + changed:
        relative = Path(skill_name) / Path(relative_text)
        target = _safe_target(root, relative)
        parent = target.parent
        chain: list[Path] = []
        current = parent
        while current != root and not current.exists():
            chain.append(current)
            current = current.parent
        require(current == root or (current.is_dir() and not current.is_symlink()), "installed parent is unsafe")
        for directory in reversed(chain):
            directory.mkdir()
        source = sources[Path(relative_text)]
        expected = details[relative_text]
        handle = tempfile.NamedTemporaryFile(prefix=f".{target.name}.", dir=parent, delete=False)
        temporary = Path(handle.name)
        try:
            with handle:
                with source.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, source.stat().st_mode & 0o777)
            require(
                digest(temporary) == expected["sha256"]
                and temporary.stat().st_size == expected["size_bytes"],
                f"source changed while packaging {relative_text}",
            )
            require(not target.is_symlink(), f"installed target became a symlink: {target}")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
    (
        _sources, _desired, _installed,
        remaining_missing, remaining_changed, remaining_extra,
    ) = plan(repo_root, root, skill_name)
    require(
        not remaining_missing and not remaining_changed and not remaining_extra,
        "post-deployment package comparison failed",
    )
    result["applied"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--installed-root", default=str(Path.home() / ".codex" / "skills"))
    parser.add_argument("--skill", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    try:
        result = sync_skill(
            Path(args.repo_root), Path(args.installed_root), args.skill,
            apply=args.apply, confirmed=args.confirmed, plan_sha256=args.plan_sha256,
        )
    except (PackageError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"{result['skill']}: {'applied' if result['applied'] else 'dry-run'}")
    print(f"  plan_sha256: {result['plan_sha256']}")
    for label in ("missing", "changed", "extra"):
        for path in result[label]:
            if label == "extra":
                print(f"  extra: {path} installed_sha256={result['extra_sha256'][path]}")
                continue
            detail = result["details"][path]
            previous = (
                f" installed_sha256={detail['installed_sha256']}"
                if detail["installed_sha256"] is not None else ""
            )
            print(
                f"  {label}: {path} <- {detail['source']} "
                f"sha256={detail['sha256']} size_bytes={detail['size_bytes']}{previous}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
