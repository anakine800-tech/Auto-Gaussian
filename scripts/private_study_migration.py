#!/usr/bin/env python3
"""Plan, review, and explicitly apply a no-delete private-study copy migration."""

from __future__ import annotations

import argparse
import codecs
import collections
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
SCHEMA = "auto-g16-private-study-migration-plan/2"
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
    "reference_scan_status",
    "rewrite_occurrence_count",
    "conflict",
    "absolute_path_references",
}
REFERENCE_KEYS = {"value", "rewrite_to", "action", "occurrences", "ambiguity"}
POSIX_PATH_RE = re.compile(r"/(?:[^\x00\r\n\"'<>|]+)")
WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\(?:[^\x00\r\n\"'<>|]+)")
DESTINATION_RECEIPT_NAME = ".auto-g16-migration-destination-receipt.json"
STREAM_CHUNK_SIZE = 1024 * 1024
MAX_AUDITED_REFERENCE_CHARS = 64 * 1024
REFERENCE_TERMINATORS = frozenset(" \t\r\n\x00\"'<>|,;[]{}()")
SOURCE_PREFIX_DISALLOWED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
UNQUOTED_REFERENCE_TERMINATORS = frozenset("\t\r\n\x00\"'<>|,;[]{}()")


class MigrationError(ValueError):
    """The private-study migration contract was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MigrationError(message)


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


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
            rewrite_count += entry["rewrite_occurrence_count"]
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
    for key in ("file_count", "source_size_bytes", "planned_size_bytes", "rewrite_count"):
        require(_nonnegative_int(plan[key]), f"migration plan {key.replace('_', ' ')} is invalid")
    require(plan["file_count"] == len(plan["entries"]), "migration plan file count mismatch")
    expected_plan_rewrites = 0
    expected_source_size = 0
    expected_planned_size = 0
    for entry in plan["entries"]:
        require(isinstance(entry, dict) and set(entry) == ENTRY_KEYS, "migration entry is not closed-schema")
        require(entry["content_kind"] in {"utf8_text", "binary"}, "migration entry content kind is invalid")
        for key in ("source_size_bytes", "planned_size_bytes", "rewrite_occurrence_count"):
            require(_nonnegative_int(entry[key]), f"migration entry {key.replace('_', ' ')} is invalid")
        expected_source_size += entry["source_size_bytes"]
        expected_planned_size += entry["planned_size_bytes"]
        if entry["content_kind"] == "binary":
            require(entry["reference_scan_status"] == "not_applicable_binary", "migration entry reference scan status is invalid")
        else:
            require(entry["reference_scan_status"] in {"complete_utf8", "review_required_ambiguous"}, "migration entry reference scan status is invalid")
        require(isinstance(entry["absolute_path_references"], list), "absolute-path references must be an array")
        has_ambiguity = False
        for reference in entry["absolute_path_references"]:
            require(isinstance(reference, dict) and set(reference) == REFERENCE_KEYS, "absolute-path reference is not closed-schema")
            require(type(reference["occurrences"]) is int and reference["occurrences"] >= 1, "absolute-path reference occurrence count is invalid")
            require(reference["ambiguity"] in {None, "unquoted_space_boundary", "unterminated_quoted_path"}, "absolute-path reference ambiguity is invalid")
            if reference["ambiguity"] is not None:
                has_ambiguity = True
                require(reference["action"] == "review_ambiguous_absolute_reference" and reference["rewrite_to"] is None, "ambiguous absolute-path reference cannot be rewritten")
            elif reference["rewrite_to"] is None:
                require(reference["action"] == "review_external_absolute_reference", "external absolute-path reference action is invalid")
            else:
                require(reference["action"] == "rewrite_source_root_to_target_root", "source-root absolute-path reference action is invalid")
        if entry["content_kind"] == "utf8_text":
            require((entry["reference_scan_status"] == "review_required_ambiguous") == has_ambiguity, "migration entry ambiguity status differs from audited references")
        expected_rewrites = sum(
            reference["occurrences"] for reference in entry["absolute_path_references"]
            if reference["rewrite_to"] is not None
        )
        require(entry["rewrite_occurrence_count"] == expected_rewrites, "migration entry rewrite occurrence count differs from audited references")
        expected_plan_rewrites += expected_rewrites
        if entry["content_kind"] == "binary":
            require(not entry["absolute_path_references"] and entry["rewrite_occurrence_count"] == 0, "binary migration entry cannot claim a completed text reference scan")
    require(plan["rewrite_count"] == expected_plan_rewrites, "migration plan rewrite count differs from entries")
    require(plan["source_size_bytes"] == expected_source_size, "migration plan source size differs from entries")
    require(plan["planned_size_bytes"] == expected_planned_size, "migration plan planned size differs from entries")
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
    require(
        all(entry["reference_scan_status"] != "review_required_ambiguous" for entry in plan["entries"]),
        "migration plan contains review-required ambiguous or unterminated absolute paths; quote or escape them and rebuild/review a /2 plan",
    )
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


def _decode_path_candidate(raw: str) -> str:
    """Decode only path-safe textual escapes; do not interpret general strings."""
    decoded: list[str] = []
    index = 0
    while index < len(raw):
        if raw[index] == "\\" and index + 1 < len(raw) and raw[index + 1] in {" ", "\\", "/"}:
            decoded.append(raw[index + 1])
            index += 2
        else:
            decoded.append(raw[index])
            index += 1
    return "".join(decoded)


def _source_reference(value: str, source_text: str) -> bool:
    return value == source_text or value.startswith(source_text + os.sep)


def _raw_source_prefix_end(raw: str, source_text: str) -> int | None:
    """Return the raw offset after an exact possibly-space-escaped source root."""
    raw_index = 0
    source_index = 0
    while source_index < len(source_text) and raw_index < len(raw):
        if (
            raw[raw_index] == "\\"
            and raw_index + 1 < len(raw)
            and raw[raw_index + 1] in {" ", "\\", "/"}
            and raw[raw_index + 1] == source_text[source_index]
        ):
            raw_index += 2
        elif raw[raw_index] == source_text[source_index]:
            raw_index += 1
        else:
            return None
        source_index += 1
    return raw_index if source_index == len(source_text) else None


def _rewrite_source_reference(raw: str, source_text: str, target_text: str) -> str:
    prefix_end = _raw_source_prefix_end(raw, source_text)
    require(prefix_end is not None, "source reference raw spelling does not match its decoded path")
    raw_prefix = raw[:prefix_end]
    replacement = target_text
    if "\\ " in raw_prefix:
        replacement = replacement.replace(" ", "\\ ")
    return replacement + raw[prefix_end:]


class _ReferenceScanner:
    """Incrementally retain exact occurrence spans and quoting ambiguity."""

    def __init__(self, source_text: str) -> None:
        self.source_text = source_text
        self.offset = 0
        self.history = ""
        self.quote: str | None = None
        self.candidate: list[str] | None = None
        self.candidate_start = 0
        self.candidate_quote: str | None = None
        self.candidate_unquoted_space = False
        self.candidate_trailing_backslashes = 0
        self.occurrences: list[dict[str, Any]] = []

    def _append(self, character: str) -> None:
        require(self.candidate is not None, "internal absolute-path scanner state is invalid")
        self.candidate.append(character)
        self.candidate_trailing_backslashes = (
            self.candidate_trailing_backslashes + 1 if character == "\\" else 0
        )
        require(len(self.candidate) <= MAX_AUDITED_REFERENCE_CHARS, "absolute-path reference exceeds the bounded audit limit")

    def _finish(self, end: int, *, forced_ambiguity: str | None = None) -> None:
        if self.candidate is None:
            return
        joined = "".join(self.candidate)
        raw = joined.rstrip(" ")
        end -= len(joined) - len(raw)
        normalized = _decode_path_candidate(raw)
        valid = bool(POSIX_PATH_RE.fullmatch(normalized) or WINDOWS_PATH_RE.fullmatch(normalized))
        if valid and normalized not in {"/"}:
            source_match = _source_reference(normalized, self.source_text)
            ambiguity = forced_ambiguity
            if ambiguity is None and self.candidate_quote is None and self.candidate_unquoted_space and not source_match:
                ambiguity = "unquoted_space_boundary"
            self.occurrences.append({
                "raw": raw,
                "normalized": normalized,
                "start": self.candidate_start,
                "end": end,
                "ambiguity": ambiguity,
            })
        self.candidate = None
        self.candidate_quote = None
        self.candidate_unquoted_space = False
        self.candidate_trailing_backslashes = 0

    def feed(self, decoded: str) -> None:
        for character in decoded:
            if self.candidate is not None:
                if self.candidate_quote is not None:
                    if character in {"\r", "\n"}:
                        self._finish(self.offset, forced_ambiguity="unterminated_quoted_path")
                        self.quote = None
                    elif character == self.candidate_quote and self.candidate_trailing_backslashes % 2 == 0:
                        self._finish(self.offset)
                        self.quote = None
                    else:
                        self._append(character)
                elif character in UNQUOTED_REFERENCE_TERMINATORS:
                    self._finish(self.offset)
                    if character in {"\"", "'"}:
                        self.quote = character
                else:
                    if character == " " and (not self.candidate or self.candidate[-1] != "\\"):
                        self.candidate_unquoted_space = True
                    self._append(character)
                self.history = (self.history + character)[-3:]
                self.offset += 1
                continue

            if character in {"\"", "'"}:
                self.quote = None if self.quote == character else character
            elif character == "/" and (not self.history or self.history[-1] not in SOURCE_PREFIX_DISALLOWED):
                self.candidate = ["/"]
                self.candidate_start = self.offset
                self.candidate_quote = self.quote
                self.candidate_trailing_backslashes = 0
            elif (
                character == "\\" and len(self.history) >= 2 and self.history[-1] == ":"
                and self.history[-2].isalpha() and (len(self.history) < 3 or not self.history[-3].isalnum())
            ):
                self.candidate = [self.history[-2], ":", "\\"]
                self.candidate_start = self.offset - 2
                self.candidate_quote = self.quote
                self.candidate_trailing_backslashes = 1
            self.history = (self.history + character)[-3:]
            self.offset += 1

    def finish(self) -> list[dict[str, Any]]:
        self._finish(
            self.offset,
            forced_ambiguity="unterminated_quoted_path" if self.candidate_quote is not None else None,
        )
        return self.occurrences


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
    text_mode = entry["content_kind"] == "utf8_text"
    rewrite_pairs = sorted(
        [
            (reference["value"].encode("utf-8"), reference["rewrite_to"].encode("utf-8"), reference["value"])
            for reference in entry["absolute_path_references"]
            if reference["rewrite_to"] is not None
        ],
        key=lambda item: (-len(item[0]), item[0]),
    )
    maximum_needle = max((len(item[0]) for item in rewrite_pairs), default=1)
    pending = b""
    previous_source_byte: int | None = None
    replacement_count = 0
    rewritten_references: collections.Counter[str] = collections.Counter()

    def emit(raw: bytes) -> None:
        nonlocal planned_size
        if not raw:
            return
        planned_hash.update(raw); planned_size += len(raw)
        if destination_fd is not None:
            _write_all(destination_fd, raw)

    def emit_original(raw: bytes) -> None:
        nonlocal previous_source_byte
        emit(raw)
        if raw:
            previous_source_byte = raw[-1]

    def source_boundary_before(value: int | None) -> bool:
        return value is None or chr(value) not in SOURCE_PREFIX_DISALLOWED

    def source_boundary_after(value: int | None) -> bool:
        return value is None or chr(value) in REFERENCE_TERMINATORS

    def flush_text(*, final: bool) -> None:
        nonlocal pending, previous_source_byte, replacement_count
        while pending:
            matches = [
                (pending.find(needle), -len(needle), needle, replacement, value)
                for needle, replacement, value in rewrite_pairs
                if pending.find(needle) >= 0
            ]
            if not matches:
                retained = 0 if final else min(maximum_needle - 1, len(pending))
                emitted = pending[:-retained] if retained else pending
                emit_original(emitted)
                pending = pending[-retained:] if retained else b""
                return
            index, _negative_length, needle, replacement, reference_value = min(matches)
            end = index + len(needle)
            if end == len(pending) and not final:
                emit_original(pending[:index])
                pending = pending[index:]
                return
            prefix = pending[:index]
            previous = prefix[-1] if prefix else previous_source_byte
            following = pending[end] if end < len(pending) else None
            emit_original(prefix)
            if source_boundary_before(previous) and source_boundary_after(following):
                emit(replacement)
                replacement_count += 1
                rewritten_references[reference_value] += 1
                previous_source_byte = needle[-1]
                pending = pending[end:]
            else:
                emit_original(pending[index:index + 1])
                pending = pending[index + 1:]

    try:
        while True:
            chunk = os.read(leaf_fd, STREAM_CHUNK_SIZE)
            if not chunk:
                break
            source_hash.update(chunk); source_size += len(chunk)
            if not text_mode:
                emit(chunk); continue
            pending += chunk
            flush_text(final=False)
        if text_mode:
            flush_text(final=True)
        after = os.fstat(leaf_fd)
    finally:
        os.close(leaf_fd)
    require(_identity(before) == _identity(after), f"source identity changed while streaming: {relative.as_posix()}")
    observed = {
        "identity": _identity(before), "source_size_bytes": source_size,
        "source_sha256": source_hash.hexdigest(), "planned_size_bytes": planned_size,
        "planned_sha256": planned_hash.hexdigest(), "rewrite_occurrence_count": replacement_count,
        "rewritten_references": rewritten_references,
    }
    if validate_expected:
        for key in ("source_size_bytes", "source_sha256", "planned_size_bytes", "planned_sha256", "rewrite_occurrence_count"):
            require(observed[key] == entry[key], f"{key.replace('_', ' ')} changed before apply: {relative.as_posix()}")
        expected_references = collections.Counter({
            reference["value"]: reference["occurrences"]
            for reference in entry["absolute_path_references"]
            if reference["rewrite_to"] is not None
        })
        require(rewritten_references == expected_references, f"source-path rewrite occurrences changed before apply: {relative.as_posix()}")
    return observed


def _reference_records(occurrences: list[dict[str, Any]], source: Path, target: Path) -> list[dict[str, Any]]:
    source_text = str(source); target_text = str(target)
    grouped: collections.Counter[tuple[str, str | None, str, str | None]] = collections.Counter()
    for occurrence in occurrences:
        value = occurrence["raw"]
        ambiguity = occurrence["ambiguity"]
        if ambiguity is not None:
            key = (value, None, "review_ambiguous_absolute_reference", ambiguity)
        elif _source_reference(occurrence["normalized"], source_text):
            key = (value, _rewrite_source_reference(value, source_text, target_text), "rewrite_source_root_to_target_root", None)
        else:
            key = (value, None, "review_external_absolute_reference", None)
        grouped[key] += 1
    return [
        {"value": value, "rewrite_to": rewrite_to, "action": action, "occurrences": count, "ambiguity": ambiguity}
        for (value, rewrite_to, action, ambiguity), count in sorted(grouped.items())
    ]


def _inspect_plan_entry(
    source_fd: int, relative: Path, source: Path, target: Path, conflict: bool,
) -> dict[str, Any]:
    """Plan one entry with bounded reads and no resident whole-file bytes."""
    leaf_fd = _open_regular_source_at(source_fd, relative)
    before = os.fstat(leaf_fd)
    source_hash = hashlib.sha256(); source_size = 0
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    valid_utf8 = True; saw_nul = False

    try:
        while True:
            chunk = os.read(leaf_fd, STREAM_CHUNK_SIZE)
            if not chunk: break
            source_hash.update(chunk); source_size += len(chunk)
            if b"\x00" in chunk:
                saw_nul = True
            if valid_utf8 and not saw_nul:
                try: decoder.decode(chunk)
                except UnicodeDecodeError:
                    valid_utf8 = False
        if valid_utf8 and not saw_nul:
            try: decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                valid_utf8 = False
        after = os.fstat(leaf_fd)
    finally:
        os.close(leaf_fd)
    require(_identity(before) == _identity(after), f"source identity changed while planning: {relative.as_posix()}")
    content_kind = "utf8_text" if valid_utf8 and not saw_nul else "binary"
    occurrences: list[dict[str, Any]] = []
    if content_kind == "utf8_text":
        scan_fd = _open_regular_source_at(source_fd, relative)
        scanner = _ReferenceScanner(str(source))
        scan_decoder = codecs.getincrementaldecoder("utf-8")("strict")
        try:
            scan_before = os.fstat(scan_fd)
            while True:
                chunk = os.read(scan_fd, STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                scanner.feed(scan_decoder.decode(chunk))
            scanner.feed(scan_decoder.decode(b"", final=True))
            occurrences = scanner.finish()
            scan_after = os.fstat(scan_fd)
        finally:
            os.close(scan_fd)
        require(_identity(scan_before) == _identity(scan_after) == _identity(before), f"source identity changed while scanning references: {relative.as_posix()}")
    references = _reference_records(occurrences, source, target) if content_kind == "utf8_text" else []
    scan_status = (
        "not_applicable_binary" if content_kind == "binary"
        else "review_required_ambiguous" if any(item["ambiguity"] is not None for item in references)
        else "complete_utf8"
    )
    entry = {
        "relative_path": relative.as_posix(), "source_size_bytes": source_size,
        "source_sha256": source_hash.hexdigest(), "planned_size_bytes": 0,
        "planned_sha256": "", "content_kind": content_kind,
        "reference_scan_status": scan_status,
        "rewrite_occurrence_count": 0,
        "conflict": conflict, "absolute_path_references": references,
    }
    observed = _stream_planned_entry(source_fd, entry, source, target, validate_expected=False)
    require(observed["identity"] == _identity(before), f"source identity changed between planning passes: {relative.as_posix()}")
    require(observed["source_size_bytes"] == source_size and observed["source_sha256"] == entry["source_sha256"], f"source changed between planning passes: {relative.as_posix()}")
    require(
        sum(item["occurrences"] for item in references if item["rewrite_to"] is not None)
        == observed["rewrite_occurrence_count"],
        f"audited source-path references differ from streamed rewrites: {relative.as_posix()}",
    )
    entry["rewrite_occurrence_count"] = observed["rewrite_occurrence_count"]
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
