#!/usr/bin/env python3
"""Build a fail-closed file map for one repository-owned named Skill.

The Skill directory remains the normal source.  A reviewed
``deployment-package.json`` may additionally map repository-root contracts or
owner validators into the installed Skill without duplicating those files in
version control.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_NAME = "deployment-package.json"
MANIFEST_SCHEMA = "auto-g16-named-skill-package/1"
SKILL_RE = re.compile(r"^auto-g16-[a-z0-9]+(?:-[a-z0-9]+)*$")
IGNORED_NAMES = {".DS_Store", "__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


class PackageError(ValueError):
    """A named-Skill deployment package is unsafe or ambiguous."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def _reject_constant(value: str) -> None:
    raise PackageError(f"non-standard JSON numeric constant is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"invalid deployment package {path}: {exc}") from exc
    require(isinstance(value, dict), "deployment package must be a JSON object")
    return value


def included(relative: Path) -> bool:
    return not any(part in IGNORED_NAMES for part in relative.parts) and relative.suffix not in IGNORED_SUFFIXES


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _relative(value: Any, label: str) -> Path:
    require(isinstance(value, str) and value, f"{label} must be a non-empty string")
    require("\\" not in value, f"{label} must use portable forward slashes")
    pure = PurePosixPath(value)
    require(not pure.is_absolute(), f"{label} must be relative")
    require(all(part not in {"", ".", ".."} for part in pure.parts), f"{label} contains unsafe traversal")
    return Path(*pure.parts)


def _assert_contained_no_symlink(root: Path, path: Path, label: str) -> Path:
    lexical_root = root.expanduser().absolute()
    require(not lexical_root.is_symlink(), f"{label} root must not be a symlink")
    resolved_root = lexical_root.resolve()
    absolute = path.expanduser().absolute() if path.is_absolute() else lexical_root / path
    try:
        relative = absolute.relative_to(lexical_root)
    except ValueError as exc:
        try:
            relative = absolute.relative_to(resolved_root)
        except ValueError:
            raise PackageError(f"{label} escapes its allowed root") from exc
    current = resolved_root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), f"{label} contains a symlink: {current}")
    return absolute


def _tree_files(root: Path, source: Path, target: Path, label: str) -> dict[Path, Path]:
    source = _assert_contained_no_symlink(root, source, label)
    require(source.exists(), f"{label} does not exist: {source}")
    if source.is_file():
        require(included(source.relative_to(root)), f"{label} is excluded from deployment")
        return {target: source}
    require(source.is_dir(), f"{label} must be a regular file or directory")
    result: dict[Path, Path] = {}
    for candidate in sorted(source.rglob("*")):
        _assert_contained_no_symlink(root, candidate, label)
        if candidate.is_dir():
            continue
        require(candidate.is_file(), f"{label} contains a non-regular file: {candidate}")
        relative = candidate.relative_to(source)
        if included(relative):
            result[target / relative] = candidate
    require(bool(result), f"{label} directory contains no deployable files")
    return result


def package_files(repo_root: Path, skill_name: str) -> dict[Path, Path]:
    """Return exact installed-relative paths mapped to authoritative sources."""
    repo_root = repo_root.expanduser().resolve()
    require(SKILL_RE.fullmatch(skill_name) is not None, "deployment requires a valid auto-g16-* Skill name")
    skill_root = _assert_contained_no_symlink(
        repo_root, repo_root / "skills" / skill_name, "repository Skill"
    )
    require((skill_root / "SKILL.md").is_file(), f"unknown repository Skill: {skill_name}")
    files = _tree_files(repo_root, skill_root, Path(), "repository Skill")
    manifest_path = skill_root / MANIFEST_NAME
    if not manifest_path.exists():
        return files
    manifest_path = _assert_contained_no_symlink(repo_root, manifest_path, "deployment package")
    manifest = load_json(manifest_path)
    require(set(manifest) == {"schema", "skill", "include"}, "deployment package has unknown or missing fields")
    require(manifest["schema"] == MANIFEST_SCHEMA, "deployment package schema is unsupported")
    require(manifest["skill"] == skill_name, "deployment package Skill name mismatch")
    include = manifest["include"]
    require(isinstance(include, list) and include, "deployment package include must be non-empty")
    seen_sources: set[str] = set()
    for index, raw in enumerate(include):
        require(isinstance(raw, dict) and set(raw) == {"source", "target"}, f"deployment include[{index}] is not closed")
        source_relative = _relative(raw["source"], f"deployment include[{index}].source")
        target_relative = _relative(raw["target"], f"deployment include[{index}].target")
        source_key = source_relative.as_posix()
        require(source_key not in seen_sources, f"duplicate deployment source: {source_key}")
        seen_sources.add(source_key)
        mapped = _tree_files(
            repo_root,
            repo_root / source_relative,
            target_relative,
            f"deployment include[{index}]",
        )
        overlap = sorted(path.as_posix() for path in set(files) & set(mapped))
        require(not overlap, f"deployment target conflicts with Skill source: {', '.join(overlap)}")
        files.update(mapped)
    return dict(sorted(files.items(), key=lambda item: item[0].as_posix()))


def inventory(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        return {}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not included(relative):
            continue
        _assert_contained_no_symlink(root, path, "installed Skill")
        if path.is_file():
            result[relative.as_posix()] = digest(path)
    return result


def package_inventory(repo_root: Path, skill_name: str) -> dict[str, str]:
    return {target.as_posix(): digest(source) for target, source in package_files(repo_root, skill_name).items()}
