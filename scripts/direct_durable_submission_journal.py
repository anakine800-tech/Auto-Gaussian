#!/usr/bin/env python3
"""Durable, local-only single-use journal for ``direct_ssh_pbs``.

This owner persists an at-most-once claim before returning control to a future
effect owner.  It has no SSH, transport, scheduler, command, remote-path,
resource, live-approval, deletion, cleanup, or retry implementation.
"""

from __future__ import annotations

if globals().get("_AUTO_G16_DIRECT_DURABLE_JOURNAL_EXECUTED", False):
    raise ImportError("direct durable journal owner module has already executed")
_AUTO_G16_DIRECT_DURABLE_JOURNAL_EXECUTED = True

import copy
import fcntl
import hashlib
import json
import marshal
import os
import re
import stat
import sys
import threading
import types
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.machinery import BuiltinImporter, FrozenImporter, PathFinder
from pathlib import Path
from typing import Any, NamedTuple

import direct_ssh_pbs_offline as DIRECT


MODULE_NAME = "direct_durable_submission_journal"
OWNER = "auto-g16-direct-durable-submission-journal-owner"
OWNER_VERSION = "direct-durable-submission-journal-owner/1"
MANIFEST_SCHEMA = "auto-g16-direct-durable-submission-manifest/1"
EVENT_SCHEMA = "auto-g16-direct-durable-submission-event/1"
SNAPSHOT_SCHEMA = "auto-g16-direct-durable-submission-journal/1"
REGISTRATION_ATTRIBUTE = "_auto_g16_direct_durable_journal_owner_registration_v1"
BACKEND_KIND = "direct_ssh_pbs"
JOURNAL_PREFIX = "direct-durable-submission-journal-"
LOCK_BASENAME = ".owner.lock"
MANIFEST_BASENAME = "manifest.json"
STARTED_BASENAME = "000000-submission-uncertain.json"
TERMINAL_BASENAME = "000001-terminal.json"
MAX_DOCUMENT_BYTES = 1024 * 1024
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
JOURNAL_RE = re.compile(r"^direct-durable-submission-journal-[a-f0-9]{64}$")
IDENTITY_FIELDS = {
    "backend_kind",
    "binding_payload_sha256",
    "profile_id",
    "profile_payload_sha256",
    "stable_root_evidence_sha256",
    "resource_catalog_sha256",
    "receipt_payload_sha256",
    "authorization_id",
    "authorization_payload_sha256",
    "authorization_scope_sha256",
    "project",
    "workspace_binding_sha256",
    "descriptor_set_sha256",
    "input_sha256",
    "resources_sha256",
    "scientific_task_id",
    "attempt_id",
    "idempotency_key",
}

POLICY = {
    "local_state_only": True,
    "append_only": True,
    "no_clobber": True,
    "cross_process_single_use": True,
    "submission_uncertain_before_effect": True,
    "creator_process_claim_only": True,
    "forked_claim_rejected": True,
    "closure_private_claim_registry": True,
    "immutable_claim_registry_records": True,
    "claim_canonical_state_replay": True,
    "descriptor_identity_replay_before_terminal": True,
    "arbitrary_same_process_reflection_isolated": False,
    "single_terminal_slot": True,
    "restart_read_only_reconciliation_only": True,
    "automatic_retry": False,
    "second_effect_allowed": False,
    "portable_document_authorizes_effect": False,
    "remote_effect_performed": False,
    "qsub_authorized": False,
    "delete_allowed": False,
    "cleanup_allowed": False,
}

class DirectDurableJournalError(ValueError):
    """The durable direct submission state cannot be proved safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectDurableJournalError(message)


class _DescriptorIdentity(NamedTuple):
    descriptor: int
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    device_type: int
    status_flags: int
    descriptor_flags: int


class _ClaimRecord(NamedTuple):
    registry_nonce: object
    creator_pid: int
    process_epoch: object
    claim_reference: weakref.ReferenceType[Any]
    binding_sha256: str
    journal_id: str
    started_event_sha256: str
    directory_identity: _DescriptorIdentity
    lock_identity: _DescriptorIdentity
    thread_lock: Any


class _ClaimAccess(NamedTuple):
    registry_nonce: object
    binding_sha256: str
    journal_id: str
    started_event_sha256: str
    directory_identity: _DescriptorIdentity
    lock_identity: _DescriptorIdentity
    thread_lock: Any


def _descriptor_identity(descriptor: int, label: str) -> _DescriptorIdentity:
    _require(type(descriptor) is int and descriptor >= 0, f"{label} descriptor differs")
    try:
        info = os.fstat(descriptor)
        status_flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
    except OSError as exc:
        raise DirectDurableJournalError(f"{label} descriptor is closed or invalid: {exc}") from exc
    return _DescriptorIdentity(
        descriptor=descriptor,
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        uid=info.st_uid,
        gid=info.st_gid,
        device_type=info.st_rdev,
        status_flags=status_flags,
        descriptor_flags=descriptor_flags,
    )


def _close_record_descriptors(record: _ClaimRecord) -> None:
    for label, expected in (
        ("claim lock", record.lock_identity),
        ("claim directory", record.directory_identity),
    ):
        try:
            current = _descriptor_identity(expected.descriptor, label)
        except DirectDurableJournalError:
            continue
        if current == expected:
            try:
                os.close(expected.descriptor)
            except OSError:
                pass


def _mark_claim_closed(claim: Any) -> None:
    for name, value in (("_directory_fd", -1), ("_lock_fd", -1), ("_closed", True)):
        try:
            object.__setattr__(claim, name, value)
        except (AttributeError, TypeError):
            pass


def canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DirectDurableJournalError(
            f"durable journal value is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[field] = ""
    result[field] = digest(result)
    return result


def _sha(value: Any, label: str, *, nonzero: bool = True) -> str:
    _require(
        type(value) is str
        and SHA_RE.fullmatch(value) is not None
        and (not nonzero or value != ZERO_SHA),
        f"{label} must be a lowercase{' nonzero' if nonzero else ''} SHA-256",
    )
    return value


def _text(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and bool(value)
        and value == value.strip()
        and all(ord(character) >= 0x20 for character in value),
        f"{label} must be non-empty trimmed control-free text",
    )
    return value


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _strict_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_DOCUMENT_BYTES, f"{label} size differs")
    _require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} contains a UTF-8 BOM")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DirectDurableJournalError(f"{label} repeats JSON key: {key}")
            result[key] = value
        return result

    def reject_float(token: str) -> Any:
        raise DirectDurableJournalError(f"{label} contains a non-integer number: {token}")

    def reject_constant(token: str) -> Any:
        raise DirectDurableJournalError(f"{label} contains a non-standard number: {token}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectDurableJournalError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    _require(type(value) is dict, f"{label} must contain one object")
    return value


def _validate_identity(value: Any) -> dict[str, Any]:
    identity = _exact(value, IDENTITY_FIELDS, "durable identity")
    _require(identity["backend_kind"] == BACKEND_KIND, "durable identity backend differs")
    for field in (
        "binding_payload_sha256",
        "profile_payload_sha256",
        "stable_root_evidence_sha256",
        "resource_catalog_sha256",
        "receipt_payload_sha256",
        "authorization_payload_sha256",
        "authorization_scope_sha256",
        "workspace_binding_sha256",
        "descriptor_set_sha256",
        "input_sha256",
        "resources_sha256",
    ):
        _sha(identity[field], f"durable identity {field}")
    for field in (
        "profile_id",
        "authorization_id",
        "project",
        "scientific_task_id",
        "attempt_id",
        "idempotency_key",
    ):
        _text(identity[field], f"durable identity {field}")
    return copy.deepcopy(identity)


def _validated_binding(binding: DIRECT.Binding) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_module_binding()
    _require(type(binding) is DIRECT.Binding, "exact direct binding is required")
    try:
        document = binding.document()
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DirectDurableJournalError(f"direct binding is unreadable: {exc}") from exc
    document = _exact(
        document,
        {
            "schema", "backend_kind", "transport_kind", "scheduler_dialect",
            "profile", "receipt_payload_sha256", "authorization", "workspace",
            "input", "resources", "scope", "owner_gaps", "live_ready",
            "binding_payload_sha256",
        },
        "direct binding",
    )
    _require(
        document["schema"] == "auto-g16-direct-ssh-pbs-offline-binding/1"
        and document["backend_kind"] == BACKEND_KIND
        and document["transport_kind"] == "direct_ssh"
        and document["scheduler_dialect"] == "pbs_legacy_v1"
        and document["live_ready"] is False,
        "direct binding topology differs",
    )
    profile = _exact(
        document["profile"],
        {"profile_id", "profile_payload_sha256", "stable_root_evidence_sha256", "resource_catalog_sha256"},
        "direct binding profile",
    )
    authorization = _exact(
        document["authorization"],
        {"authorization_id", "authorization_payload_sha256", "authorization_scope_sha256"},
        "direct binding authorization",
    )
    workspace = _exact(
        document["workspace"],
        {"project", "workspace_binding_sha256", "descriptor_set_sha256"},
        "direct binding workspace",
    )
    approved_input = _exact(document["input"], {"basename", "sha256", "size_bytes"}, "direct binding input")
    scope = _exact(
        document["scope"],
        {"scientific_task_id", "attempt_id", "idempotency_key"},
        "direct binding scope",
    )
    _require(type(document["resources"]) is dict and bool(document["resources"]), "direct binding resources differ")
    _require(
        document["owner_gaps"] == [gap.document() for gap in DIRECT.OWNER_GAPS],
        "direct binding owner gaps differ",
    )
    for label, value in (
        ("binding payload", document["binding_payload_sha256"]),
        ("profile payload", profile["profile_payload_sha256"]),
        ("stable root evidence", profile["stable_root_evidence_sha256"]),
        ("resource catalog", profile["resource_catalog_sha256"]),
        ("receipt payload", document["receipt_payload_sha256"]),
        ("authorization payload", authorization["authorization_payload_sha256"]),
        ("authorization scope", authorization["authorization_scope_sha256"]),
        ("workspace binding", workspace["workspace_binding_sha256"]),
        ("descriptor set", workspace["descriptor_set_sha256"]),
        ("input", approved_input["sha256"]),
    ):
        _sha(value, label)
    for label, value in (
        ("profile id", profile["profile_id"]),
        ("authorization id", authorization["authorization_id"]),
        ("project", workspace["project"]),
        ("input basename", approved_input["basename"]),
        ("input size", approved_input["size_bytes"]),
        ("scientific task", scope["scientific_task_id"]),
        ("attempt", scope["attempt_id"]),
        ("idempotency key", scope["idempotency_key"]),
    ):
        _text(value, label)
    projection = copy.deepcopy(document)
    projection["binding_payload_sha256"] = ""
    _require(
        document["binding_payload_sha256"] == DIRECT.digest(projection)
        and binding._bytes == DIRECT.canonical_bytes(document),
        "direct binding hash or canonical bytes differ",
    )
    identity = {
        "backend_kind": BACKEND_KIND,
        "binding_payload_sha256": document["binding_payload_sha256"],
        "profile_id": profile["profile_id"],
        "profile_payload_sha256": profile["profile_payload_sha256"],
        "stable_root_evidence_sha256": profile["stable_root_evidence_sha256"],
        "resource_catalog_sha256": profile["resource_catalog_sha256"],
        "receipt_payload_sha256": document["receipt_payload_sha256"],
        "authorization_id": authorization["authorization_id"],
        "authorization_payload_sha256": authorization["authorization_payload_sha256"],
        "authorization_scope_sha256": authorization["authorization_scope_sha256"],
        "project": workspace["project"],
        "workspace_binding_sha256": workspace["workspace_binding_sha256"],
        "descriptor_set_sha256": workspace["descriptor_set_sha256"],
        "input_sha256": approved_input["sha256"],
        "resources_sha256": digest(document["resources"]),
        "scientific_task_id": scope["scientific_task_id"],
        "attempt_id": scope["attempt_id"],
        "idempotency_key": scope["idempotency_key"],
    }
    return copy.deepcopy(document), _validate_identity(identity)


def _journal_id(identity: dict[str, Any]) -> str:
    return JOURNAL_PREFIX + digest({"schema": "auto-g16-direct-durable-journal-id/1", "identity": identity})


def journal_id_for_binding(binding: DIRECT.Binding) -> str:
    """Return the deterministic local journal id; it is never authority."""
    _document, identity = _validated_binding(binding)
    return _journal_id(identity)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _open_local_state_dir(path: Path) -> int:
    _require(isinstance(path, Path) and path.is_absolute(), "local state directory must be an absolute Path")
    parts = path.parts[1:]
    _require(bool(parts) and all(part not in {"", ".", ".."} for part in parts), "local state directory is unsafe")
    descriptor = os.open(
        path.anchor,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        for part in parts:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        _require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.geteuid()
            and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
            "local state directory ownership or mode differs",
        )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_journal_dir(local_fd: int, journal_id: str) -> int:
    _require(JOURNAL_RE.fullmatch(journal_id) is not None, "journal id is malformed")
    descriptor = os.open(
        journal_id,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=local_fd,
    )
    info = os.fstat(descriptor)
    _require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
        "journal directory ownership or mode differs",
    )
    return descriptor


def _write_new_file(directory_fd: int, basename: str, raw: bytes, *, mode: int = 0o600) -> None:
    _require("/" not in basename and basename not in {"", ".", ".."}, "journal basename is unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(basename, flags, mode, dir_fd=directory_fd)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            _require(written > 0, "journal write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory_fd)


def _read_file(directory_fd: int, basename: str) -> bytes:
    descriptor = os.open(
        basename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_fd,
    )
    try:
        info = os.fstat(descriptor)
        _require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.geteuid()
            and info.st_nlink == 1
            and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
            and 0 < info.st_size <= MAX_DOCUMENT_BYTES,
            f"{basename} is not a bounded owner file",
        )
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            _require(bool(chunk), f"{basename} ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        _require(os.read(descriptor, 1) == b"", f"{basename} grew during read")
        after = os.fstat(descriptor)
        _require(
            (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            f"{basename} changed during read",
        )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _manifest(identity: dict[str, Any], journal_id: str) -> dict[str, Any]:
    return _finalize(
        {
            "schema": MANIFEST_SCHEMA,
            "owner": OWNER,
            "owner_version": OWNER_VERSION,
            "journal_id": journal_id,
            "identity": copy.deepcopy(identity),
            "policy": copy.deepcopy(POLICY),
            "manifest_payload_sha256": "",
        },
        "manifest_payload_sha256",
    )


def _event(
    *,
    journal_id: str,
    binding_sha256: str,
    sequence: int,
    event_type: str,
    outcome: str,
    previous_event_sha256: str,
    evidence_sha256: str,
) -> dict[str, Any]:
    return _finalize(
        {
            "schema": EVENT_SCHEMA,
            "owner": OWNER,
            "journal_id": journal_id,
            "binding_payload_sha256": binding_sha256,
            "sequence": sequence,
            "event_type": event_type,
            "state": "submission_uncertain" if outcome in {"started", "unknown"} else "completed",
            "outcome": outcome,
            "previous_event_sha256": previous_event_sha256,
            "evidence_sha256": evidence_sha256,
            "recorded_at": _utc_now(),
            "event_payload_sha256": "",
        },
        "event_payload_sha256",
    )


def _validate_manifest(document: Any, identity: dict[str, Any], journal_id: str) -> dict[str, Any]:
    document = _exact(
        document,
        {"schema", "owner", "owner_version", "journal_id", "identity", "policy", "manifest_payload_sha256"},
        "durable manifest",
    )
    _require(
        document["schema"] == MANIFEST_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and document["journal_id"] == journal_id
        and document["identity"] == identity
        and document["policy"] == POLICY,
        "durable manifest identity or policy differs",
    )
    _sha(document["manifest_payload_sha256"], "manifest payload")
    projection = copy.deepcopy(document)
    projection["manifest_payload_sha256"] = ""
    _require(document["manifest_payload_sha256"] == digest(projection), "manifest payload hash differs")
    return document


def _validate_event(
    document: Any,
    *,
    journal_id: str,
    binding_sha256: str,
    sequence: int,
    previous_event_sha256: str,
) -> dict[str, Any]:
    document = _exact(
        document,
        {
            "schema", "owner", "journal_id", "binding_payload_sha256", "sequence",
            "event_type", "state", "outcome", "previous_event_sha256",
            "evidence_sha256", "recorded_at", "event_payload_sha256",
        },
        "durable event",
    )
    allowed = {
        0: {("submission_uncertain", "submission_uncertain", "started", ZERO_SHA)},
        1: {
            ("effect_completed", "completed", "completed", None),
            ("effect_outcome_unknown", "submission_uncertain", "unknown", None),
        },
    }
    _require(
        document["schema"] == EVENT_SCHEMA
        and document["owner"] == OWNER
        and document["journal_id"] == journal_id
        and document["binding_payload_sha256"] == binding_sha256
        and type(document["sequence"]) is int
        and document["sequence"] == sequence,
        "durable event identity differs",
    )
    key = (document["event_type"], document["state"], document["outcome"], document["previous_event_sha256"] if sequence == 0 else None)
    _require(sequence in allowed and key in allowed[sequence], "durable event transition differs")
    _require(document["previous_event_sha256"] == previous_event_sha256, "durable event chain differs")
    _sha(document["previous_event_sha256"], "previous event", nonzero=sequence > 0)
    _sha(document["evidence_sha256"], "event evidence", nonzero=sequence > 0)
    if sequence == 0:
        _require(document["evidence_sha256"] == ZERO_SHA, "started event evidence differs")
    recorded_at = _text(document["recorded_at"], "event recorded_at")
    try:
        parsed = datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise DirectDurableJournalError("event recorded_at is not canonical UTC") from exc
    _require(parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == recorded_at, "event recorded_at is not canonical UTC")
    _sha(document["event_payload_sha256"], "event payload")
    projection = copy.deepcopy(document)
    projection["event_payload_sha256"] = ""
    _require(document["event_payload_sha256"] == digest(projection), "event payload hash differs")
    return document


@dataclass(frozen=True, slots=True)
class DurableJournalSnapshot:
    _bytes: bytes

    def document(self) -> dict[str, Any]:
        document = _strict_json_bytes(self._bytes, "durable journal snapshot")
        return validate_durable_journal_snapshot(document)

    def __copy__(self) -> Any:
        raise TypeError("durable journal snapshots are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("durable journal snapshots are not clonable")


class DurableEffectClaim:
    """Process-local, non-serializable proof that uncertainty is durable."""

    __slots__ = (
        "_binding_sha256", "_closed", "_creator_pid", "_directory_fd",
        "_journal_id", "_lock", "_lock_fd", "_process_epoch",
        "_registry_nonce", "_started_event_sha256", "_token", "__weakref__",
    )

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("durable effect claims are owner-issued only")

    @property
    def journal_id(self) -> str:
        return self._journal_id

    @property
    def binding_payload_sha256(self) -> str:
        return self._binding_sha256

    @property
    def outcome(self) -> str:
        return "started"

    @property
    def authorizes_effect(self) -> bool:
        return False

    def __copy__(self) -> Any:
        raise TypeError("durable effect claims are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("durable effect claims are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("durable effect claims are not serializable")

    def __del__(self) -> None:
        retire = globals().get("_claim_owner_retire")
        if callable(retire):
            try:
                retire(self, require_active=False)
            except Exception:
                pass


def _build_claim_owner(claim_type: type) -> tuple[Any, Any, Any, Any]:
    """Build the sole in-process owner without exporting its mutable state."""
    registry: dict[int, _ClaimRecord] = {}
    registry_lock = threading.Lock()
    claim_token = object()
    process_epoch = object()
    owner_require = _require
    owner_descriptor_identity = _descriptor_identity
    owner_close_descriptors = _close_record_descriptors
    owner_mark_closed = _mark_claim_closed
    record_type = _ClaimRecord
    access_type = _ClaimAccess

    def issue(
        claim: Any,
        directory_fd: int,
        lock_fd: int,
        journal_id: str,
        binding_sha256: str,
        started_event_sha256: str,
    ) -> None:
        owner_require(type(claim) is claim_type, "durable effect claims are owner-issued only")
        creator_pid = os.getpid()
        registry_nonce = object()
        thread_lock = threading.Lock()
        object.__setattr__(claim, "_binding_sha256", binding_sha256)
        object.__setattr__(claim, "_closed", False)
        object.__setattr__(claim, "_creator_pid", creator_pid)
        object.__setattr__(claim, "_directory_fd", directory_fd)
        object.__setattr__(claim, "_journal_id", journal_id)
        object.__setattr__(claim, "_lock", thread_lock)
        object.__setattr__(claim, "_lock_fd", lock_fd)
        object.__setattr__(claim, "_process_epoch", process_epoch)
        object.__setattr__(claim, "_registry_nonce", registry_nonce)
        object.__setattr__(claim, "_started_event_sha256", started_event_sha256)
        object.__setattr__(claim, "_token", claim_token)
        record = record_type(
            registry_nonce=registry_nonce,
            creator_pid=creator_pid,
            process_epoch=process_epoch,
            claim_reference=weakref.ref(claim),
            binding_sha256=binding_sha256,
            journal_id=journal_id,
            started_event_sha256=started_event_sha256,
            directory_identity=owner_descriptor_identity(directory_fd, "claim directory"),
            lock_identity=owner_descriptor_identity(lock_fd, "claim lock"),
            thread_lock=thread_lock,
        )
        with registry_lock:
            owner_require(id(claim) not in registry, "durable claim registry identity already exists")
            registry[id(claim)] = record

    def access(claim: Any, *, expected_nonce: object | None = None) -> _ClaimAccess:
        owner_require(
            type(claim) is claim_type
            and getattr(claim, "_token", None) is claim_token
            and type(getattr(claim, "_creator_pid", None)) is int
            and getattr(claim, "_creator_pid", None) == os.getpid()
            and getattr(claim, "_process_epoch", None) is process_epoch,
            "forked, foreign, or wrong-process durable effect claim",
        )
        owner_require(getattr(claim, "_closed", None) is False, "durable effect claim is already terminal")
        with registry_lock:
            record = registry.get(id(claim))
            owner_require(
                type(record) is record_type
                and record.claim_reference() is claim
                and (expected_nonce is None or record.registry_nonce is expected_nonce),
                "durable effect claim is absent from the owner-private registry",
            )
            owner_require(
                getattr(claim, "_registry_nonce", None) is record.registry_nonce
                and getattr(claim, "_creator_pid", None) == record.creator_pid
                and getattr(claim, "_process_epoch", None) is record.process_epoch,
                "durable effect claim registry identity differs",
            )
            owner_require(
                type(getattr(claim, "_binding_sha256", None)) is str
                and claim._binding_sha256 == record.binding_sha256
                and type(getattr(claim, "_journal_id", None)) is str
                and claim._journal_id == record.journal_id
                and type(getattr(claim, "_started_event_sha256", None)) is str
                and claim._started_event_sha256 == record.started_event_sha256
                and getattr(claim, "_lock", None) is record.thread_lock,
                "durable effect claim canonical fields differ",
            )
            owner_require(
                type(getattr(claim, "_directory_fd", None)) is int
                and claim._directory_fd == record.directory_identity.descriptor
                and type(getattr(claim, "_lock_fd", None)) is int
                and claim._lock_fd == record.lock_identity.descriptor,
                "durable effect claim descriptor fields differ",
            )
            owner_require(
                owner_descriptor_identity(claim._directory_fd, "claim directory")
                == record.directory_identity
                and owner_descriptor_identity(claim._lock_fd, "claim lock")
                == record.lock_identity,
                "durable effect claim descriptor identity differs",
            )
            return access_type(
                registry_nonce=record.registry_nonce,
                binding_sha256=record.binding_sha256,
                journal_id=record.journal_id,
                started_event_sha256=record.started_event_sha256,
                directory_identity=record.directory_identity,
                lock_identity=record.lock_identity,
                thread_lock=record.thread_lock,
            )

    def retire(
        claim: Any,
        *,
        require_active: bool,
        expected_nonce: object | None = None,
    ) -> None:
        retired: _ClaimRecord | None = None
        with registry_lock:
            record = registry.get(id(claim))
            matches = (
                type(record) is record_type
                and record.claim_reference() is claim
                and (expected_nonce is None or record.registry_nonce is expected_nonce)
            )
            if require_active:
                owner_require(matches, "durable effect claim registry identity differs")
            if matches:
                retired = record
                del registry[id(claim)]
        if retired is not None:
            owner_close_descriptors(retired)
            owner_mark_closed(claim)

    def after_fork_child() -> None:
        nonlocal registry, registry_lock, claim_token, process_epoch
        inherited = registry
        for record in inherited.values():
            owner_close_descriptors(record)
            claim = record.claim_reference()
            if claim is not None:
                owner_mark_closed(claim)
        registry = {}
        registry_lock = threading.Lock()
        claim_token = object()
        process_epoch = object()

    return issue, access, retire, after_fork_child


(
    _claim_owner_issue,
    _claim_owner_access,
    _claim_owner_retire,
    _claim_owner_after_fork,
) = _build_claim_owner(DurableEffectClaim)
del _build_claim_owner


def _new_claim(directory_fd: int, lock_fd: int, journal_id: str, binding_sha256: str, event_sha256: str) -> DurableEffectClaim:
    claim = object.__new__(DurableEffectClaim)
    try:
        _claim_owner_issue(
            claim,
            directory_fd,
            lock_fd,
            journal_id,
            binding_sha256,
            event_sha256,
        )
    except BaseException:
        _mark_claim_closed(claim)
        raise
    return claim


def _close_claim(
    claim: DurableEffectClaim,
    *,
    expected_nonce: object | None = None,
) -> None:
    _claim_owner_retire(
        claim,
        require_active=expected_nonce is not None,
        expected_nonce=expected_nonce,
    )


def _consume_binding_once(
    local_state_dir: Path,
    binding: DIRECT.Binding,
) -> DurableEffectClaim:
    """Atomically consume one validated binding and publish uncertainty.

    Existing or partial state is never repaired or resumed.  The caller gets
    a non-authorizing process-local claim only after directory, manifest, and
    started-event fsyncs complete.
    """
    _assert_module_binding()
    _document, identity = _validated_binding(binding)
    journal_id = _journal_id(identity)
    local_fd = _open_local_state_dir(local_state_dir)
    directory_fd = -1
    lock_fd = -1
    try:
        try:
            os.mkdir(journal_id, mode=0o700, dir_fd=local_fd)
        except FileExistsError as exc:
            raise DirectDurableJournalError(
                "durable journal already exists; mutation is forbidden and only read-only reconciliation is allowed"
            ) from exc
        os.fsync(local_fd)
        directory_fd = _open_journal_dir(local_fd, journal_id)
        lock_fd = os.open(
            LOCK_BASENAME,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        os.fsync(lock_fd)
        os.fsync(directory_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        manifest = _manifest(identity, journal_id)
        _write_new_file(directory_fd, MANIFEST_BASENAME, canonical_bytes(manifest))
        started = _event(
            journal_id=journal_id,
            binding_sha256=identity["binding_payload_sha256"],
            sequence=0,
            event_type="submission_uncertain",
            outcome="started",
            previous_event_sha256=ZERO_SHA,
            evidence_sha256=ZERO_SHA,
        )
        _write_new_file(directory_fd, STARTED_BASENAME, canonical_bytes(started))
        claim = _new_claim(
            directory_fd,
            lock_fd,
            journal_id,
            identity["binding_payload_sha256"],
            started["event_payload_sha256"],
        )
        directory_fd = -1
        lock_fd = -1
        return claim
    except OSError as exc:
        raise DirectDurableJournalError(f"durable claim publication failed closed: {exc}") from exc
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(local_fd)


def consume_for_effect_once(
    local_state_dir: Path,
    binding: DIRECT.Binding,
) -> DurableEffectClaim:
    """Compatibility owner entry for an exact direct binding."""
    return _consume_binding_once(local_state_dir, binding)


def record_outcome_once(claim: DurableEffectClaim, *, outcome: str, evidence_sha256: str) -> None:
    """Append exactly one terminal observation using the live process claim."""
    _assert_module_binding()
    _require(outcome in {"completed", "unknown"}, "outcome must be completed or unknown")
    _sha(evidence_sha256, "outcome evidence")
    try:
        access = _claim_owner_access(claim)
    except DirectDurableJournalError:
        _claim_owner_retire(claim, require_active=False)
        raise
    with access.thread_lock:
        try:
            current = _claim_owner_access(
                claim,
                expected_nonce=access.registry_nonce,
            )
            event_type = "effect_completed" if outcome == "completed" else "effect_outcome_unknown"
            event = _event(
                journal_id=current.journal_id,
                binding_sha256=current.binding_sha256,
                sequence=1,
                event_type=event_type,
                outcome=outcome,
                previous_event_sha256=current.started_event_sha256,
                evidence_sha256=evidence_sha256,
            )
            current = _claim_owner_access(
                claim,
                expected_nonce=access.registry_nonce,
            )
            _write_new_file(
                current.directory_identity.descriptor,
                TERMINAL_BASENAME,
                canonical_bytes(event),
            )
        except OSError as exc:
            raise DirectDurableJournalError(f"durable terminal append failed closed: {exc}") from exc
        finally:
            _close_claim(claim, expected_nonce=access.registry_nonce)


def _read_exact_document(directory_fd: int, basename: str) -> dict[str, Any]:
    raw = _read_file(directory_fd, basename)
    document = _strict_json_bytes(raw, basename)
    _require(raw == canonical_bytes(document), f"{basename} bytes are not canonical")
    return document


def reconcile_read_only(local_state_dir: Path, journal_id: str, binding: DIRECT.Binding) -> DurableJournalSnapshot:
    """Read and validate one journal without creating or changing any file."""
    _assert_module_binding()
    _document, identity = _validated_binding(binding)
    _require(JOURNAL_RE.fullmatch(journal_id) is not None, "journal id is malformed")
    _require(journal_id == _journal_id(identity), "scope, hash, profile, or attempt drift")
    local_fd = _open_local_state_dir(local_state_dir)
    directory_fd = -1
    lock_fd = -1
    try:
        directory_fd = _open_journal_dir(local_fd, journal_id)
        lock_fd = os.open(
            LOCK_BASENAME,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        lock_info = os.fstat(lock_fd)
        _require(
            stat.S_ISREG(lock_info.st_mode)
            and lock_info.st_uid == os.geteuid()
            and lock_info.st_nlink == 1
            and lock_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
            "journal owner lock differs",
        )
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        manifest = _validate_manifest(_read_exact_document(directory_fd, MANIFEST_BASENAME), identity, journal_id)
        started = _validate_event(
            _read_exact_document(directory_fd, STARTED_BASENAME),
            journal_id=journal_id,
            binding_sha256=identity["binding_payload_sha256"],
            sequence=0,
            previous_event_sha256=ZERO_SHA,
        )
        names = set(os.listdir(directory_fd))
        allowed = {
            LOCK_BASENAME,
            MANIFEST_BASENAME,
            STARTED_BASENAME,
            TERMINAL_BASENAME,
        }
        _require(names <= allowed, "journal contains an unknown entry")
        events = [started]
        if TERMINAL_BASENAME in names:
            terminal = _validate_event(
                _read_exact_document(directory_fd, TERMINAL_BASENAME),
                journal_id=journal_id,
                binding_sha256=identity["binding_payload_sha256"],
                sequence=1,
                previous_event_sha256=started["event_payload_sha256"],
            )
            events.append(terminal)
        last_recorded = events[-1]["outcome"]
        effective = "unknown" if last_recorded == "started" else last_recorded
        state = "completed" if effective == "completed" else "submission_uncertain"
        snapshot = _finalize(
            {
                "schema": SNAPSHOT_SCHEMA,
                "owner": OWNER,
                "owner_version": OWNER_VERSION,
                "journal_id": journal_id,
                "manifest_payload_sha256": manifest["manifest_payload_sha256"],
                "identity": copy.deepcopy(identity),
                "state": state,
                "last_recorded_outcome": last_recorded,
                "effective_outcome": effective,
                "events": copy.deepcopy(events),
                "reconciliation": {
                    "mode": "read_only_reconciliation_only",
                    "read_only": True,
                    "mutation_performed": False,
                    "automatic_retry": False,
                    "second_effect_allowed": False,
                    "started_without_terminal_is_unknown": True,
                },
                "policy": copy.deepcopy(POLICY),
                "journal_payload_sha256": "",
            },
            "journal_payload_sha256",
        )
        validate_durable_journal_snapshot(snapshot)
        return DurableJournalSnapshot(canonical_bytes(snapshot))
    except FileNotFoundError as exc:
        raise DirectDurableJournalError("durable journal is absent or incomplete") from exc
    except OSError as exc:
        raise DirectDurableJournalError(f"read-only reconciliation failed closed: {exc}") from exc
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(local_fd)


def validate_durable_journal_snapshot(value: Any) -> dict[str, Any]:
    document = _exact(
        value,
        {
            "schema", "owner", "owner_version", "journal_id", "manifest_payload_sha256",
            "identity", "state", "last_recorded_outcome", "effective_outcome", "events",
            "reconciliation", "policy", "journal_payload_sha256",
        },
        "durable journal snapshot",
    )
    _require(
        document["schema"] == SNAPSHOT_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and type(document["journal_id"]) is str
        and JOURNAL_RE.fullmatch(document["journal_id"]) is not None
        and document["state"] in {"submission_uncertain", "completed"}
        and document["last_recorded_outcome"] in {"started", "completed", "unknown"}
        and document["effective_outcome"] in {"completed", "unknown"}
        and document["policy"] == POLICY,
        "durable journal snapshot constants differ",
    )
    _sha(document["manifest_payload_sha256"], "snapshot manifest")
    _sha(document["journal_payload_sha256"], "snapshot payload")
    identity = _validate_identity(document["identity"])
    _require(document["journal_id"] == _journal_id(identity), "snapshot journal identity differs")
    expected_manifest = _manifest(identity, document["journal_id"])
    _require(
        document["manifest_payload_sha256"] == expected_manifest["manifest_payload_sha256"],
        "snapshot manifest binding differs",
    )
    events = document["events"]
    _require(type(events) is list and len(events) in {1, 2}, "snapshot events differ")
    first = _validate_event(
        events[0], journal_id=document["journal_id"], binding_sha256=identity["binding_payload_sha256"], sequence=0, previous_event_sha256=ZERO_SHA
    )
    if len(events) == 2:
        _validate_event(
            events[1], journal_id=document["journal_id"], binding_sha256=identity["binding_payload_sha256"], sequence=1, previous_event_sha256=first["event_payload_sha256"]
        )
    last_recorded = events[-1]["outcome"]
    effective = "unknown" if last_recorded == "started" else last_recorded
    expected_state = "completed" if effective == "completed" else "submission_uncertain"
    _require(
        document["last_recorded_outcome"] == last_recorded
        and document["effective_outcome"] == effective
        and document["state"] == expected_state,
        "snapshot outcome projection differs",
    )
    reconciliation = _exact(
        document["reconciliation"],
        {"mode", "read_only", "mutation_performed", "automatic_retry", "second_effect_allowed", "started_without_terminal_is_unknown"},
        "snapshot reconciliation",
    )
    _require(
        reconciliation == {
            "mode": "read_only_reconciliation_only",
            "read_only": True,
            "mutation_performed": False,
            "automatic_retry": False,
            "second_effect_allowed": False,
            "started_without_terminal_is_unknown": True,
        },
        "snapshot reconciliation differs",
    )
    projection = copy.deepcopy(document)
    projection["journal_payload_sha256"] = ""
    _require(document["journal_payload_sha256"] == digest(projection), "snapshot payload hash differs")
    return copy.deepcopy(document)


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, int, int, int, int]
    sha256: str


@dataclass(frozen=True, slots=True)
class _ModuleBinding:
    module: types.ModuleType
    source: _SourceSnapshot
    issued_types: tuple[type, ...]
    direct_module: types.ModuleType
    direct_binding_type: type
    w3_activation_entry: object
    server_session_entry: object


def _stable_source(path: Path) -> _SourceSnapshot:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    _require(
        stat.S_ISREG(before.st_mode)
        and identity == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        "durable journal owner source changed during capture",
    )
    return _SourceSnapshot(path, identity, hashlib.sha256(b"".join(chunks)).hexdigest())


_ISSUED_TYPES = (DurableEffectClaim, DurableJournalSnapshot)
_SOURCE = Path(__file__).resolve()


def _capture_module_binding() -> _ModuleBinding:
    _require(__name__ == MODULE_NAME, "durable journal owner must use its canonical module name")
    module = sys.modules.get(MODULE_NAME)
    _require(isinstance(module, types.ModuleType), "canonical durable journal owner module is unavailable")
    _require(sys.modules.get(DIRECT.__name__) is DIRECT and getattr(DIRECT, "Binding", None) is DIRECT.Binding, "direct binding owner identity differs")
    registered = vars(DIRECT).setdefault(REGISTRATION_ATTRIBUTE, module)
    _require(registered is module, "canonical durable journal owner is already registered")
    for issued_type in _ISSUED_TYPES:
        _require(issued_type.__module__ == MODULE_NAME and getattr(module, issued_type.__name__, None) is issued_type, "durable journal issued type identity differs")
    return _ModuleBinding(
        module,
        _stable_source(_SOURCE),
        _ISSUED_TYPES,
        DIRECT,
        DIRECT.Binding,
        _activate_canonical_w3_owner_once,
        consume_for_server_session_replay_once,
    )


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    _require(
        isinstance(binding, _ModuleBinding)
        and sys.modules.get(MODULE_NAME) is binding.module
        and vars(binding.direct_module).get(REGISTRATION_ATTRIBUTE) is binding.module
        and sys.modules.get(binding.direct_module.__name__) is binding.direct_module
        and getattr(binding.direct_module, "Binding", None) is binding.direct_binding_type
        and _activate_canonical_w3_owner_once is binding.w3_activation_entry
        and vars(binding.module).get("_activate_canonical_w3_owner_once")
        is binding.w3_activation_entry
        and consume_for_server_session_replay_once is binding.server_session_entry
        and vars(binding.module).get("consume_for_server_session_replay_once")
        is binding.server_session_entry
        and _stable_source(_SOURCE) == binding.source,
        "durable journal owner module or source identity differs",
    )
    for issued_type in binding.issued_types:
        _require(getattr(binding.module, issued_type.__name__, None) is issued_type, "durable journal issued type identity differs")


def _build_server_session_w3_owner_entries() -> tuple[object, object]:
    """Build a no-argument active W3 bootstrap and private exact consumer."""
    owner_assert = _assert_module_binding
    owner_require = _require
    consume_binding = _consume_binding_once
    stable_source = _stable_source
    sys_modules = sys.modules
    module_type = types.ModuleType
    marshal_dumps = marshal.dumps
    sha256 = hashlib.sha256
    builtin_compile = compile
    builtin_exec = exec
    w3_module_name = "direct_effect_time_replay_ingress"
    w3_registration_attribute = (
        "_auto_g16_direct_effect_time_replay_ingress_owner_registration_v1"
    )
    w3_source = stable_source(
        _SOURCE.with_name("direct_effect_time_replay_ingress.py")
    )
    expected_w3_source_sha256 = (
        "9c1f09fba92b36e667ea5584ac9cc7462a97101b5385dccc615e96455e9ccc63"
    )
    expected_descriptor_code_sha256 = (
        "7482dd635263ca75901c508301dfa6e4feebdf3cb69d0ed66b673be62b373be5"
    )
    fixed_meta_path = tuple(sys.meta_path)
    isolated_meta_path = (BuiltinImporter, FrozenImporter, PathFinder)
    transaction_type = DIRECT.DirectServerSessionTransaction
    activation_lock = threading.Lock()
    activation_status = "uninitialized"
    canonical_binding: tuple[types.ModuleType, type, object] | None = None

    owner_require(
        w3_source.sha256 == expected_w3_source_sha256,
        "reviewed canonical W3 source bytes differ",
    )

    def assert_fixed_import_resolution() -> None:
        owner_require(
            type(sys.meta_path) is list
            and len(sys.meta_path) == len(fixed_meta_path)
            and all(
                current is expected
                for current, expected in zip(sys.meta_path, fixed_meta_path, strict=True)
            ),
            "canonical W3 fixed import resolution binding differs",
        )

    def load_reviewed_w3_source() -> types.ModuleType:
        """Execute only the owner-bound reviewed W3 bytes, bypassing finders."""
        owner_require(
            sys_modules.get(w3_module_name) is None,
            "canonical W3 module appeared before fixed source execution",
        )
        assert_fixed_import_resolution()
        owner_require(
            type(sys.meta_path) is list
            and len(sys.meta_path) == len(isolated_meta_path)
            and all(
                current is expected
                for current, expected in zip(
                    sys.meta_path,
                    isolated_meta_path,
                    strict=True,
                )
            ),
            "canonical W3 source execution requires isolated import resolution",
        )
        descriptor = os.open(
            w3_source.path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            before = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        source_bytes = b"".join(chunks)
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        owner_require(
            stat.S_ISREG(before.st_mode)
            and identity == w3_source.identity
            and identity
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            and len(source_bytes) == before.st_size
            and sha256(source_bytes).hexdigest() == expected_w3_source_sha256,
            "reviewed canonical W3 source identity or bytes differ",
        )
        code = builtin_compile(
            source_bytes,
            str(w3_source.path),
            "exec",
            dont_inherit=True,
            optimize=0,
        )
        module = module_type(w3_module_name)
        module.__file__ = str(w3_source.path)
        module.__package__ = ""
        module.__loader__ = None
        module.__spec__ = None
        sys_modules[w3_module_name] = module
        try:
            builtin_exec(code, vars(module))
        except BaseException:
            if sys_modules.get(w3_module_name) is module:
                del sys_modules[w3_module_name]
            raise
        return module

    def descriptor_code_sha256(descriptor: object) -> str:
        owner_require(
            type(descriptor) is types.FunctionType,
            "canonical W3 predecessor descriptor type differs",
        )
        code = descriptor.__code__.replace(
            co_filename="",
            co_firstlineno=1,
            co_name="",
            co_qualname="",
        )
        return sha256(marshal_dumps(code)).hexdigest()

    def validate_w3_candidate(
        w3_module: object,
        w3_capability_type: object,
        w3_descriptor: object,
    ) -> None:
        assert_fixed_import_resolution()
        owner_require(
            type(w3_module) is module_type
            and sys_modules.get(w3_module_name) is w3_module
            and vars(DIRECT).get(w3_registration_attribute) is w3_module
            and stable_source(w3_source.path) == w3_source
            and w3_source.sha256 == expected_w3_source_sha256
            and type(w3_capability_type) is type
            and vars(w3_module).get("DirectEffectTimeReplayIngressCapability")
            is w3_capability_type
            and vars(w3_capability_type).get(
                "assert_server_session_pre_w2_current"
            )
            is w3_descriptor
            and descriptor_code_sha256(w3_descriptor)
            == expected_descriptor_code_sha256,
            "canonical W3 module, type, exact descriptor code, or source binding differs",
        )

    def activate_w3_once() -> None:
        nonlocal activation_status, canonical_binding
        owner_assert()
        with activation_lock:
            if activation_status == "active":
                current = canonical_binding
            else:
                owner_require(
                    activation_status == "uninitialized",
                    "canonical W3 active bootstrap is unavailable",
                )
                activation_status = "activating"
                current = None
        if current is not None:
            validate_w3_candidate(*current)
            return
        try:
            w3_module = sys_modules.get(w3_module_name)
            if w3_module is None:
                w3_module = load_reviewed_w3_source()
            w3_capability_type = vars(w3_module).get(
                "DirectEffectTimeReplayIngressCapability"
            ) if type(w3_module) is module_type else None
            w3_descriptor = vars(w3_capability_type).get(
                "assert_server_session_pre_w2_current"
            ) if type(w3_capability_type) is type else None
            validate_w3_candidate(
                w3_module,
                w3_capability_type,
                w3_descriptor,
            )
            with activation_lock:
                owner_require(
                    activation_status == "activating"
                    and canonical_binding is None,
                    "canonical W3 active bootstrap raced",
                )
                canonical_binding = (
                    w3_module,
                    w3_capability_type,
                    w3_descriptor,
                )
                activation_status = "active"
        except BaseException:
            with activation_lock:
                activation_status = "failed"
            raise

    def assert_w3_binding() -> None:
        with activation_lock:
            current = canonical_binding
            status = activation_status
        owner_require(
            status == "active" and type(current) is tuple and len(current) == 3,
            "canonical W3 owner was not actively bootstrapped",
        )
        validate_w3_candidate(*current)

    def consume_server_session(
        local_state_dir: Path,
        direct_transaction: object,
        w3_capability: object,
    ) -> DurableEffectClaim:
        """Publish started only from the canonical exact W3 predecessor."""
        owner_assert()
        assert_w3_binding()
        with activation_lock:
            current = canonical_binding
        owner_require(type(current) is tuple, "canonical W3 binding is unavailable")
        _w3_module, w3_capability_type, w3_descriptor = current
        owner_require(
            type(direct_transaction) is transaction_type
            and type(w3_capability) is w3_capability_type,
            "exact canonical server-session transaction and W3 capability are required",
        )
        direct_transaction.assert_current()
        assert_w3_binding()
        owner_require(
            w3_descriptor(w3_capability, direct_transaction) is w3_capability,
            "pre-W3 server-session capability binding differs",
        )
        assert_w3_binding()
        direct_transaction.assert_current()
        assert_w3_binding()
        return consume_binding(local_state_dir, direct_transaction._binding)

    consume_server_session.__name__ = "consume_for_server_session_replay_once"
    consume_server_session.__qualname__ = "consume_for_server_session_replay_once"
    activate_w3_once.__name__ = "_activate_canonical_w3_owner_once"
    activate_w3_once.__qualname__ = "_activate_canonical_w3_owner_once"
    return activate_w3_once, consume_server_session


(
    _activate_canonical_w3_owner_once,
    consume_for_server_session_replay_once,
) = _build_server_session_w3_owner_entries()
del _build_server_session_w3_owner_entries


_MODULE_BINDING: _ModuleBinding | None = None
_MODULE_BINDING = _capture_module_binding()

if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_claim_owner_after_fork)
