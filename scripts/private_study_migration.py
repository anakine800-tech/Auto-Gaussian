#!/usr/bin/env python3
"""Plan, review, and explicitly apply a no-delete private-study copy migration."""

from __future__ import annotations

import argparse
import codecs
import copy
import errno
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
DESTINATION_RECEIPT_NAME = ".auto-g16-migration-destination-receipt.json"
STREAM_CHUNK_SIZE = 1024 * 1024
MAX_TEXT_REWRITE_BYTES = 8 * 1024 * 1024
REFERENCE_SCAN_OVERLAP_CHARS = 8192


class MigrationError(ValueError):
    """The private-study migration contract was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MigrationError(message)


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
SOURCE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)


def _unsafe_path_error(label: str, exc: OSError) -> MigrationError:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        return MigrationError(f"{label} contains a symlink or non-directory component")
    return MigrationError(f"could not safely open {label}: {exc}")


def _absolute_parts(path: Path, label: str) -> tuple[str, ...]:
    require(path.is_absolute(), f"{label} must be absolute")
    parts = path.parts[1:]
    require(all(part not in {"", ".", ".."} for part in parts), f"{label} is unsafe")
    return parts


def _relative_parts(path: Path, label: str) -> tuple[str, ...]:
    require(not path.is_absolute(), f"{label} must be relative")
    parts = path.parts
    require(parts and all(part not in {"", ".", ".."} for part in parts), f"{label} is unsafe")
    return parts


def _open_directory_at(parent_fd: int, name: str, label: str, *, create: bool = False) -> int:
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _unsafe_path_error(label, exc) from exc
    try:
        fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise _unsafe_path_error(label, exc) from exc
    opened = os.fstat(fd)
    if not stat.S_ISDIR(opened.st_mode):
        os.close(fd)
        raise MigrationError(f"{label} must be a directory")
    return fd


def _open_absolute_directory(path: Path, label: str) -> int:
    parts = _absolute_parts(path, label)
    fd = os.open(path.anchor, DIRECTORY_FLAGS)
    try:
        for index, part in enumerate(parts):
            next_fd = _open_directory_at(fd, part, f"{label} component {index + 1}")
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_fd(fd: int, label: str) -> bytes:
    chunks: list[bytes] = []
    try:
        while True:
            chunk = os.read(fd, STREAM_CHUNK_SIZE)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as exc:
        raise MigrationError(f"could not read {label}: {exc}") from exc


def _read_source_at(source_fd: int, relative: Path) -> bytes:
    parts = _relative_parts(relative, "source relative path")
    parent_fd = os.dup(source_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            next_fd = _open_directory_at(parent_fd, part, f"source ancestor {index + 1}")
            os.close(parent_fd)
            parent_fd = next_fd
        try:
            leaf_fd = os.open(parts[-1], SOURCE_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise _unsafe_path_error(f"source leaf {relative.as_posix()}", exc) from exc
        try:
            opened = os.fstat(leaf_fd)
            require(stat.S_ISREG(opened.st_mode), f"source leaf is not a regular file: {relative.as_posix()}")
            return _read_fd(leaf_fd, f"source leaf {relative.as_posix()}")
        finally:
            os.close(leaf_fd)
    finally:
        os.close(parent_fd)


def _source_identity_at(source_fd: int, relative: Path) -> tuple[int, int, int, int, int]:
    """Return a no-follow identity without repeating the full source read."""
    parts = _relative_parts(relative, "source relative path")
    parent_fd = os.dup(source_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            next_fd = _open_directory_at(parent_fd, part, f"source ancestor {index + 1}")
            os.close(parent_fd)
            parent_fd = next_fd
        try:
            leaf_fd = os.open(parts[-1], SOURCE_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise _unsafe_path_error(f"source leaf {relative.as_posix()}", exc) from exc
        try:
            opened = os.fstat(leaf_fd)
            require(stat.S_ISREG(opened.st_mode), f"source leaf is not a regular file: {relative.as_posix()}")
            return (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
        finally:
            os.close(leaf_fd)
    finally:
        os.close(parent_fd)


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
    source_fd = _open_absolute_directory(source, "source root")
    try:
        for path in _iter_source_files(source):
            relative = path.relative_to(source)
            require(not relative.is_absolute() and ".." not in relative.parts, "source relative path is unsafe")
            require(relative.as_posix() != DESTINATION_RECEIPT_NAME, "source contains the reserved destination receipt path")
            destination = target / relative
            conflict = destination.exists() or destination.is_symlink()
            if conflict:
                conflicts.append(relative.as_posix())
            entry = _inspect_plan_entry(source_fd, relative, source, target, conflict)
            rewrite_count += sum(item["rewrite_to"] is not None for item in entry["absolute_path_references"])
            entries.append(entry)
    finally:
        os.close(source_fd)
    receipt_destination = target / DESTINATION_RECEIPT_NAME
    if os.path.lexists(receipt_destination):
        conflicts.append(DESTINATION_RECEIPT_NAME)
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
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, canonical_bytes(value))
        os.fsync(fd)
    finally:
        os.close(fd)


def _open_regular_source_at(source_fd: int, relative: Path) -> int:
    """Open one source leaf through no-follow directory descriptors."""
    parts = _relative_parts(relative, "source relative path")
    parent_fd = os.dup(source_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            next_fd = _open_directory_at(parent_fd, part, f"source ancestor {index + 1}")
            os.close(parent_fd)
            parent_fd = next_fd
        try:
            leaf_fd = os.open(parts[-1], SOURCE_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise _unsafe_path_error(f"source leaf {relative.as_posix()}", exc) from exc
        opened = os.fstat(leaf_fd)
        if not stat.S_ISREG(opened.st_mode):
            os.close(leaf_fd)
            raise MigrationError(f"source leaf is not a regular file: {relative.as_posix()}")
        return leaf_fd
    finally:
        os.close(parent_fd)


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _stream_planned_entry(
    source_fd: int,
    entry: dict[str, Any],
    source: Path,
    target: Path,
    destination_fd: int | None = None,
    *,
    validate_expected: bool = True,
) -> dict[str, Any]:
    """Hash and optionally copy one entry using bounded buffers."""
    relative = Path(entry["relative_path"])
    leaf_fd = _open_regular_source_at(source_fd, relative)
    source_hash = hashlib.sha256(); planned_hash = hashlib.sha256()
    source_size = 0; planned_size = 0
    before = os.fstat(leaf_fd)
    needle = str(source).encode("utf-8")
    replacement = str(target).encode("utf-8")
    text_mode = entry["content_kind"] == "utf8_text"
    pending = b""

    def emit(raw: bytes) -> None:
        nonlocal planned_size
        if not raw:
            return
        planned_hash.update(raw); planned_size += len(raw)
        if destination_fd is not None:
            _write_all(destination_fd, raw)

    try:
        while True:
            chunk = os.read(leaf_fd, STREAM_CHUNK_SIZE)
            if not chunk:
                break
            source_hash.update(chunk); source_size += len(chunk)
            if not text_mode:
                emit(chunk); continue
            pending += chunk
            while True:
                index = pending.find(needle)
                if index >= 0:
                    emit(pending[:index]); emit(replacement)
                    pending = pending[index + len(needle):]
                    continue
                retained = min(max(len(needle) - 1, 0), len(pending))
                emit(pending[:-retained] if retained else pending)
                pending = pending[-retained:] if retained else b""
                break
        if text_mode:
            emit(pending)
        after = os.fstat(leaf_fd)
    finally:
        os.close(leaf_fd)
    require(_identity(before) == _identity(after), f"source identity changed while streaming: {relative.as_posix()}")
    observed = {
        "identity": _identity(before), "source_size_bytes": source_size,
        "source_sha256": source_hash.hexdigest(), "planned_size_bytes": planned_size,
        "planned_sha256": planned_hash.hexdigest(),
    }
    if validate_expected:
        for key in ("source_size_bytes", "source_sha256", "planned_size_bytes", "planned_sha256"):
            require(observed[key] == entry[key], f"{key.replace('_', ' ')} changed before apply: {relative.as_posix()}")
    return observed


def _reference_records(found: set[str], source: Path, target: Path) -> list[dict[str, Any]]:
    source_text = str(source); target_text = str(target)
    records = []
    for value in sorted(found):
        if value == source_text or value.startswith(source_text + os.sep):
            records.append({"value": value, "rewrite_to": target_text + value[len(source_text):], "action": "rewrite_source_root_to_target_root"})
        else:
            records.append({"value": value, "rewrite_to": None, "action": "review_external_absolute_reference"})
    return records


def _inspect_plan_entry(
    source_fd: int, relative: Path, source: Path, target: Path, conflict: bool,
) -> dict[str, Any]:
    """Plan one entry with bounded reads and no resident whole-file bytes."""
    leaf_fd = _open_regular_source_at(source_fd, relative)
    before = os.fstat(leaf_fd)
    source_hash = hashlib.sha256(); source_size = 0; found: set[str] = set()
    text_candidate = before.st_size <= MAX_TEXT_REWRITE_BYTES
    decoder = codecs.getincrementaldecoder("utf-8")("strict") if text_candidate else None
    scan_tail = ""; saw_nul = False

    def scan_text(decoded: str, *, final: bool = False) -> None:
        nonlocal scan_tail
        combined = scan_tail + decoded
        cutoff = len(combined) if final else max(0, len(combined) - REFERENCE_SCAN_OVERLAP_CHARS)
        searchable = combined[:cutoff]
        found.update(POSIX_PATH_RE.findall(searchable)); found.update(WINDOWS_PATH_RE.findall(searchable))
        scan_tail = combined[cutoff:]

    try:
        while True:
            chunk = os.read(leaf_fd, STREAM_CHUNK_SIZE)
            if not chunk: break
            source_hash.update(chunk); source_size += len(chunk); saw_nul = saw_nul or b"\x00" in chunk
            if decoder is not None:
                try: scan_text(decoder.decode(chunk))
                except UnicodeDecodeError:
                    decoder = None; found.clear(); scan_tail = ""
        if decoder is not None:
            try: scan_text(decoder.decode(b"", final=True), final=True)
            except UnicodeDecodeError:
                decoder = None; found.clear(); scan_tail = ""
        after = os.fstat(leaf_fd)
    finally:
        os.close(leaf_fd)
    require(_identity(before) == _identity(after), f"source identity changed while planning: {relative.as_posix()}")
    content_kind = "utf8_text" if decoder is not None and not saw_nul else ("opaque_large" if before.st_size > MAX_TEXT_REWRITE_BYTES else "binary")
    references = _reference_records(found, source, target) if content_kind == "utf8_text" else []
    entry = {
        "relative_path": relative.as_posix(), "source_size_bytes": source_size,
        "source_sha256": source_hash.hexdigest(), "planned_size_bytes": 0,
        "planned_sha256": "", "content_kind": content_kind,
        "conflict": conflict, "absolute_path_references": references,
    }
    observed = _stream_planned_entry(source_fd, entry, source, target, validate_expected=False)
    require(observed["identity"] == _identity(before), f"source identity changed between planning passes: {relative.as_posix()}")
    require(observed["source_size_bytes"] == source_size and observed["source_sha256"] == entry["source_sha256"], f"source changed between planning passes: {relative.as_posix()}")
    entry["planned_size_bytes"] = observed["planned_size_bytes"]
    entry["planned_sha256"] = observed["planned_sha256"]
    return entry


def _preflight_source_entries(
    source_fd: int,
    entries: list[dict[str, Any]],
    source: Path,
    target: Path,
) -> dict[str, dict[str, Any]]:
    return {entry["relative_path"]: _stream_planned_entry(source_fd, entry, source, target) for entry in entries}


def _target_root_handles(target: Path) -> tuple[int, int | None, str]:
    parts = _absolute_parts(target, "target root")
    require(parts, "target root must not be the filesystem root")
    parent_fd = _open_absolute_directory(target.parent, "target parent")
    leaf = parts[-1]
    try:
        target_fd = _open_directory_at(parent_fd, leaf, "target root")
    except MigrationError as exc:
        try:
            os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return parent_fd, None, leaf
        except OSError as stat_exc:
            os.close(parent_fd)
            raise _unsafe_path_error("target root", stat_exc) from stat_exc
        os.close(parent_fd)
        raise exc
    target_stat = os.fstat(target_fd)
    if target_stat.st_uid != os.getuid() or stat.S_IMODE(target_stat.st_mode) != 0o700:
        os.close(target_fd)
        os.close(parent_fd)
        raise MigrationError("target root must be owned by the current user with exact mode 0700")
    return parent_fd, target_fd, leaf


def _destination_exists(target_fd: int, relative: Path) -> bool:
    parts = _relative_parts(relative, "migration destination path")
    parent_fd = os.dup(target_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            try:
                next_fd = _open_directory_at(parent_fd, part, f"destination ancestor {index + 1}")
            except MigrationError:
                try:
                    os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return False
                raise
            os.close(parent_fd)
            parent_fd = next_fd
        try:
            os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _unsafe_path_error(f"destination leaf {relative.as_posix()}", exc) from exc
        return True
    finally:
        os.close(parent_fd)


def _preflight_destination_conflicts(target_fd: int | None, entries: list[dict[str, Any]]) -> None:
    if target_fd is None:
        return
    conflicts = [
        entry["relative_path"]
        for entry in entries
        if _destination_exists(target_fd, Path(entry["relative_path"]))
    ]
    if _destination_exists(target_fd, Path(DESTINATION_RECEIPT_NAME)):
        conflicts.append(DESTINATION_RECEIPT_NAME)
    require(not conflicts, f"target conflicts appeared before apply: {conflicts}")


def _create_target_root(parent_fd: int, target_fd: int | None, leaf: str) -> int:
    if target_fd is not None:
        return target_fd
    try:
        os.mkdir(leaf, mode=0o700, dir_fd=parent_fd)
    except OSError as exc:
        raise MigrationError(f"target root changed after preflight; no files were copied: {exc}") from exc
    fd = _open_directory_at(parent_fd, leaf, "new target root")
    os.fchmod(fd, 0o700)
    return fd


def _write_all(fd: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        if written <= 0:
            raise OSError("zero-byte write")
        offset += written


def _write_destination(target_fd: int, relative: Path, raw: bytes) -> None:
    parts = _relative_parts(relative, "migration destination path")
    parent_fd = os.dup(target_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            next_fd = _open_directory_at(
                parent_fd,
                part,
                f"destination ancestor {index + 1}",
                create=True,
            )
            os.close(parent_fd)
            parent_fd = next_fd
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            leaf_fd = os.open(parts[-1], flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            raise MigrationError(f"refusing unsafe or existing migration destination: {relative.as_posix()}: {exc}") from exc
        try:
            os.fchmod(leaf_fd, 0o600)
            _write_all(leaf_fd, raw)
            os.fsync(leaf_fd)
        finally:
            os.close(leaf_fd)
    finally:
        os.close(parent_fd)


def _stream_destination(
    source_fd: int, target_fd: int, entry: dict[str, Any], source: Path, target: Path,
    expected_identity: tuple[int, int, int, int, int],
) -> dict[str, Any]:
    relative = Path(entry["relative_path"])
    require(_source_identity_at(source_fd, relative) == expected_identity, f"source identity changed after preflight: {relative.as_posix()}")
    parts = _relative_parts(relative, "migration destination path")
    parent_fd = os.dup(target_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            next_fd = _open_directory_at(parent_fd, part, f"destination ancestor {index + 1}", create=True)
            os.close(parent_fd); parent_fd = next_fd
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            destination_fd = os.open(parts[-1], flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            raise MigrationError(f"refusing unsafe or existing migration destination: {relative.as_posix()}: {exc}") from exc
        try:
            os.fchmod(destination_fd, 0o600)
            observed = _stream_planned_entry(source_fd, entry, source, target, destination_fd)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(parent_fd)
    # Re-read the source after the write and reject any in-flight replacement or drift.
    after = _stream_planned_entry(source_fd, entry, source, target)
    require(after["identity"] == expected_identity, f"source identity changed after copy: {relative.as_posix()}")
    destination_fd = _open_regular_source_at(target_fd, relative)
    try:
        destination_hash = hashlib.sha256(); destination_size = 0
        while True:
            chunk = os.read(destination_fd, STREAM_CHUNK_SIZE)
            if not chunk: break
            destination_hash.update(chunk); destination_size += len(chunk)
    finally:
        os.close(destination_fd)
    digest = destination_hash.hexdigest()
    require(destination_size == entry["planned_size_bytes"] and digest == entry["planned_sha256"], f"destination rehash differs after apply: {relative.as_posix()}")
    return {"relative_path": relative.as_posix(), "sha256": digest, "size_bytes": destination_size, "mode": "0600"}


def apply_plan(path: Path, *, confirmation: str, reviewer: str) -> dict[str, Any]:
    require(bool(reviewer.strip()), "apply requires a non-empty reviewer identity")
    plan = review_plan(path)
    require(confirmation == plan["plan_sha256"], "apply confirmation does not match the exact reviewed plan SHA-256")
    source = Path(plan["source_root"])
    target = Path(plan["target_root"])
    _target_state(target)
    source_fd = _open_absolute_directory(source, "apply source root")
    target_parent_fd: int | None = None
    target_fd: int | None = None
    copied_file_count = 0
    copied_size_bytes = 0
    destination_receipts: list[dict[str, Any]] = []
    persisted_receipt: dict[str, Any] | None = None
    try:
        # No target directory or file is created until every source byte/hash and
        # every destination conflict has passed this descriptor-bound preflight.
        source_metadata = _preflight_source_entries(source_fd, plan["entries"], source, target)
        target_parent_fd, target_fd, target_leaf = _target_root_handles(target)
        _preflight_destination_conflicts(target_fd, plan["entries"])
        target_fd = _create_target_root(target_parent_fd, target_fd, target_leaf)
        try:
            for entry in plan["entries"]:
                relative = Path(entry["relative_path"])
                metadata = source_metadata[entry["relative_path"]]
                destination_receipts.append(_stream_destination(source_fd, target_fd, entry, source, target, metadata["identity"]))
                copied_file_count += 1
                copied_size_bytes += entry["planned_size_bytes"]
            receipt_document = {
                "schema": "auto-g16-private-study-migration-destination-receipt/1",
                "plan_sha256": plan["plan_sha256"], "reviewer": reviewer.strip(),
                "entries": destination_receipts, "source_deleted": False, "overwrites": 0,
                "payload_sha256": None,
            }
            receipt_document["payload_sha256"] = hashlib.sha256(canonical_bytes({key: value for key, value in receipt_document.items() if key != "payload_sha256"})).hexdigest()
            receipt_relative = Path(DESTINATION_RECEIPT_NAME)
            receipt_bytes = canonical_bytes(receipt_document); _write_destination(target_fd, receipt_relative, receipt_bytes)
            persisted = _read_source_at(target_fd, receipt_relative)
            require(persisted == receipt_bytes, "persisted destination migration receipt rehash differs")
            persisted_receipt = {"relative_path": receipt_relative.as_posix(), "sha256": hashlib.sha256(persisted).hexdigest(), "size_bytes": len(persisted), "payload_sha256": receipt_document["payload_sha256"]}
        except Exception as exc:
            raise MigrationError(
                "apply stopped after "
                f"{copied_file_count} file(s) and {copied_size_bytes} byte(s); "
                "a partial copy may remain and requires manual inspection; "
                "automatic rollback deletion is forbidden"
            ) from exc
    finally:
        os.close(source_fd)
        if target_fd is not None:
            os.close(target_fd)
        if target_parent_fd is not None:
            os.close(target_parent_fd)
    return {
        "schema": "auto-g16-private-study-migration-apply-result/2",
        "plan_sha256": plan["plan_sha256"],
        "reviewer": reviewer.strip(),
        "copied_file_count": copied_file_count,
        "copied_size_bytes": copied_size_bytes,
        "source_deleted": False,
        "overwrites": 0,
        "partial_copy": False,
        "manual_partial_copy_review_required": False,
        "automatic_rollback_deletion": False,
        "destination_receipt": persisted_receipt,
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
