#!/usr/bin/env python3
"""Plan, review, and explicitly apply a no-delete private-study copy migration."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "auto-g16-private-study-migration-plan/1"
PLAN_KEYS = {
    "schema",
    "created_at",
    "source_root",
    "target_root",
    "file_count",
    "source_size_bytes",
    "planned_size_bytes",
    "source_tree_sha256",
    "planned_tree_sha256",
    "entries",
    "conflicts",
    "rewrite_count",
    "safety",
    "plan_sha256",
}
ENTRY_KEYS = {
    "relative_path",
    "source_size_bytes",
    "source_sha256",
    "planned_size_bytes",
    "planned_sha256",
    "content_kind",
    "conflict",
    "absolute_path_references",
}
REFERENCE_KEYS = {"value", "rewrite_to", "action"}
POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^/\s\x00\"'<>|]+/)*[^/\s\x00\"'<>|]+")
WINDOWS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\(?:[^\\\r\n\t\x00\"<>|]+\\)*[^\\\r\n\t\x00\"<>|]+")


class MigrationError(ValueError):
    """The private-study migration contract was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MigrationError(message)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def plan_digest(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("plan_sha256", None)
    return digest_value(payload)


def _reject_symlink_chain(path: Path, label: str) -> Path:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for depth, part in enumerate(absolute.parts[1:], start=1):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError(f"could not inspect {label} path component {current}: {exc}") from exc
        if stat.S_ISLNK(mode) and depth == 1:
            try:
                current = current.resolve(strict=True)
            except OSError as exc:
                raise MigrationError(f"could not resolve trusted OS path alias {current}: {exc}") from exc
            continue
        require(not stat.S_ISLNK(mode), f"{label} path contains a symlink: {current}")
    return absolute


def _outside_checkout(path: Path, label: str) -> None:
    resolved = path.resolve(strict=False)
    require(not resolved.is_relative_to(ROOT), f"{label} must remain outside the public checkout")


def _target_state(target: Path) -> None:
    _reject_symlink_chain(target, "target root")
    _outside_checkout(target, "target root")
    if not target.exists():
        require(target.parent.exists() and target.parent.is_dir(), "target parent must already exist")
        return
    require(target.is_dir(), "target root must be a directory")
    target_stat = target.stat()
    require(target_stat.st_uid == os.getuid(), "target root must be owned by the current user")
    require(stat.S_IMODE(target_stat.st_mode) == 0o700, "target root must have owner-only mode 0700")


def _iter_source_files(source: Path) -> list[Path]:
    require(source.exists() and source.is_dir(), "source root must be an existing directory")
    _reject_symlink_chain(source, "source root")
    require(source.resolve() != ROOT, "refusing to migrate the repository root")
    files: list[Path] = []
    for candidate in sorted(source.rglob("*")):
        _reject_symlink_chain(candidate, "source entry")
        mode = candidate.lstat().st_mode
        require(not stat.S_ISLNK(mode), f"source entry is a symlink: {candidate}")
        require(stat.S_ISDIR(mode) or stat.S_ISREG(mode), f"source entry is not a regular file or directory: {candidate}")
        if stat.S_ISREG(mode):
            files.append(candidate)
    return files


def _text(raw: bytes) -> str | None:
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _absolute_references(text: str, source: Path, target: Path) -> list[dict[str, Any]]:
    found = sorted(set(POSIX_PATH_RE.findall(text)) | set(WINDOWS_PATH_RE.findall(text)))
    references: list[dict[str, Any]] = []
    source_text = str(source)
    target_text = str(target)
    for value in found:
        if value == source_text or value.startswith(source_text + os.sep):
            rewrite_to = target_text + value[len(source_text):]
            action = "rewrite_source_root_to_target_root"
        else:
            rewrite_to = None
            action = "review_external_absolute_reference"
        references.append({"value": value, "rewrite_to": rewrite_to, "action": action})
    return references


def _planned_bytes(raw: bytes, source: Path, target: Path) -> bytes:
    if _text(raw) is None:
        return raw
    return raw.replace(str(source).encode("utf-8"), str(target).encode("utf-8"))


def _tree_digest(entries: list[dict[str, Any]], *, planned: bool) -> str:
    prefix = "planned" if planned else "source"
    manifest = [
        {
            "relative_path": item["relative_path"],
            "size_bytes": item[f"{prefix}_size_bytes"],
            "sha256": item[f"{prefix}_sha256"],
        }
        for item in entries
    ]
    return digest_value(manifest)


def build_plan(source: Path, target: Path, *, created_at: str | None = None) -> dict[str, Any]:
    source = _reject_symlink_chain(source.expanduser(), "source root").resolve()
    target = _reject_symlink_chain(target.expanduser(), "target root").resolve(strict=False)
    require(source != target, "source and target roots must differ")
    require(not target.is_relative_to(source), "target root must not be inside the source tree")
    _target_state(target)
    entries: list[dict[str, Any]] = []
    conflicts: list[str] = []
    rewrite_count = 0
    for path in _iter_source_files(source):
        relative = path.relative_to(source)
        require(not relative.is_absolute() and ".." not in relative.parts, "source relative path is unsafe")
        raw = path.read_bytes()
        planned = _planned_bytes(raw, source, target)
        text = _text(raw)
        references = [] if text is None else _absolute_references(text, source, target)
        rewrite_count += sum(item["rewrite_to"] is not None for item in references)
        destination = target / relative
        conflict = destination.exists() or destination.is_symlink()
        if conflict:
            conflicts.append(relative.as_posix())
        entries.append({
            "relative_path": relative.as_posix(),
            "source_size_bytes": len(raw),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "planned_size_bytes": len(planned),
            "planned_sha256": hashlib.sha256(planned).hexdigest(),
            "content_kind": "utf8_text" if text is not None else "binary",
            "conflict": conflict,
            "absolute_path_references": references,
        })
    plan = {
        "schema": SCHEMA,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "source_root": str(source),
        "target_root": str(target),
        "file_count": len(entries),
        "source_size_bytes": sum(item["source_size_bytes"] for item in entries),
        "planned_size_bytes": sum(item["planned_size_bytes"] for item in entries),
        "source_tree_sha256": _tree_digest(entries, planned=False),
        "planned_tree_sha256": _tree_digest(entries, planned=True),
        "entries": entries,
        "conflicts": conflicts,
        "rewrite_count": rewrite_count,
        "safety": {
            "dry_run": True,
            "copy_only": True,
            "source_deletion_authorized": False,
            "overwrite_authorized": False,
            "live_actions": False,
            "apply_requires_exact_plan_sha256": True,
        },
        "plan_sha256": None,
    }
    plan["plan_sha256"] = plan_digest(plan)
    return plan


def _validate_plan_shape(plan: dict[str, Any]) -> None:
    require(set(plan) == PLAN_KEYS, "migration plan is not a closed-schema object")
    require(plan["schema"] == SCHEMA, "unsupported migration plan schema")
    require(plan.get("plan_sha256") == plan_digest(plan), "migration plan SHA-256 mismatch")
    require(isinstance(plan["entries"], list), "migration plan entries must be an array")
    require(isinstance(plan["conflicts"], list), "migration plan conflicts must be an array")
    require(plan["file_count"] == len(plan["entries"]), "migration plan file count mismatch")
    for entry in plan["entries"]:
        require(isinstance(entry, dict) and set(entry) == ENTRY_KEYS, "migration entry is not closed-schema")
        require(isinstance(entry["absolute_path_references"], list), "absolute-path references must be an array")
        for reference in entry["absolute_path_references"]:
            require(isinstance(reference, dict) and set(reference) == REFERENCE_KEYS, "absolute-path reference is not closed-schema")
    require(plan["safety"] == {
        "dry_run": True,
        "copy_only": True,
        "source_deletion_authorized": False,
        "overwrite_authorized": False,
        "live_actions": False,
        "apply_requires_exact_plan_sha256": True,
    }, "migration plan safety constants changed")


def load_plan(path: Path) -> dict[str, Any]:
    path = _reject_symlink_chain(path.expanduser(), "migration plan")
    require(path.is_absolute(), "migration plan path must be absolute")
    require(path.is_file(), "migration plan is missing")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"could not read migration plan: {exc}") from exc
    require(isinstance(plan, dict), "migration plan must be a JSON object")
    _validate_plan_shape(plan)
    return plan


def review_plan(path: Path) -> dict[str, Any]:
    plan = load_plan(path)
    fresh = build_plan(
        Path(plan["source_root"]),
        Path(plan["target_root"]),
        created_at=plan["created_at"],
    )
    require(fresh == plan, "migration plan is stale: source, target, hashes, paths, or conflicts changed")
    require(not plan["conflicts"], "migration plan has target conflicts and cannot be applied")
    return plan


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = _reject_symlink_chain(path.expanduser(), "plan output")
    require(path.is_absolute(), "plan output path must be absolute")
    _outside_checkout(path, "plan output")
    require(path.parent.exists() and path.parent.is_dir(), "plan output parent must already exist")
    require(not os.path.lexists(path), "refusing to overwrite an existing plan output")
    with path.open("xb") as handle:
        handle.write(canonical_bytes(value))
    os.chmod(path, 0o600)


def apply_plan(path: Path, *, confirmation: str, reviewer: str) -> dict[str, Any]:
    require(bool(reviewer.strip()), "apply requires a non-empty reviewer identity")
    plan = review_plan(path)
    require(confirmation == plan["plan_sha256"], "apply confirmation does not match the exact reviewed plan SHA-256")
    source = Path(plan["source_root"])
    target = Path(plan["target_root"])
    _target_state(target)
    if not target.exists():
        target.mkdir(mode=0o700)
    os.chmod(target, 0o700)
    for entry in plan["entries"]:
        relative = Path(entry["relative_path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "migration entry path is unsafe")
        source_path = source / relative
        destination = target / relative
        _reject_symlink_chain(source_path, "apply source")
        _reject_symlink_chain(destination, "apply destination")
        require(not os.path.lexists(destination), f"refusing to overwrite migration destination: {relative.as_posix()}")
        raw = source_path.read_bytes()
        require(len(raw) == entry["source_size_bytes"], f"source size changed before apply: {relative.as_posix()}")
        require(hashlib.sha256(raw).hexdigest() == entry["source_sha256"], f"source hash changed before apply: {relative.as_posix()}")
        planned = _planned_bytes(raw, source, target)
        require(len(planned) == entry["planned_size_bytes"], f"planned size changed before apply: {relative.as_posix()}")
        require(hashlib.sha256(planned).hexdigest() == entry["planned_sha256"], f"planned hash changed before apply: {relative.as_posix()}")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(planned)
        os.chmod(destination, 0o600)
    return {
        "schema": "auto-g16-private-study-migration-apply-result/1",
        "plan_sha256": plan["plan_sha256"],
        "reviewer": reviewer.strip(),
        "copied_file_count": plan["file_count"],
        "copied_size_bytes": plan["planned_size_bytes"],
        "source_deleted": False,
        "overwrites": 0,
        "live_actions": False,
    }


def _summary(plan: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "schema": "auto-g16-private-study-migration-summary/1",
        "status": status,
        "plan_sha256": plan["plan_sha256"],
        "file_count": plan["file_count"],
        "source_size_bytes": plan["source_size_bytes"],
        "planned_size_bytes": plan["planned_size_bytes"],
        "conflict_count": len(plan["conflicts"]),
        "rewrite_count": plan["rewrite_count"],
        "copy_only": True,
        "source_deleted": False,
        "live_actions": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="create a dry-run manifest outside the checkout")
    plan_parser.add_argument("source", type=Path)
    plan_parser.add_argument(
        "--target",
        type=Path,
        default=Path.home() / "Documents" / "Auto-G16-Private-Studies",
    )
    plan_parser.add_argument("--plan-out", type=Path, required=True)
    review_parser = subparsers.add_parser("review", help="replay an exact plan without writing data")
    review_parser.add_argument("plan", type=Path)
    apply_parser = subparsers.add_parser("apply", help="copy an exact reviewed plan without deleting source data")
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("--confirm-plan-sha256", required=True)
    apply_parser.add_argument("--reviewed-by", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = build_plan(args.source, args.target)
            write_new(args.plan_out, plan)
            print(json.dumps(_summary(plan, "planned_dry_run"), indent=2, sort_keys=True))
            return 0
        if args.command == "review":
            plan = review_plan(args.plan)
            print(json.dumps(_summary(plan, "reviewed_no_apply"), indent=2, sort_keys=True))
            return 0
        result = apply_plan(
            args.plan,
            confirmation=args.confirm_plan_sha256,
            reviewer=args.reviewed_by,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (MigrationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
