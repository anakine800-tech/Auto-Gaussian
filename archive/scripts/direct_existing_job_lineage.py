#!/usr/bin/env python3
"""Server-local W5 -> W6 existing-job lineage and read-capability owner.

This module performs descriptor-relative, read-only reconciliation only.  It
does not implement SSH, qstat, fetch, materialization, qsub, qdel, retry,
cleanup, deletion, or scientific acceptance.  Portable documents are evidence
inputs and projections; only the live owner registry plus retained descriptors
can authorize a future separately reviewed read successor.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

if globals().get("_AUTO_G16_EXISTING_JOB_LINEAGE_EXECUTED"):
    raise ImportError("direct existing-job lineage owner module has already executed")
_AUTO_G16_EXISTING_JOB_LINEAGE_EXECUTED = True

import direct_durable_submission_journal as W2
import direct_one_hop_transport as W5
import direct_trusted_session_composition as SESSION


MODULE_NAME = "direct_existing_job_lineage"
OWNER = "auto-g16-direct-existing-job-lineage-owner"
OWNER_VERSION = "direct-existing-job-lineage-owner/1"
RESULT_SCHEMA = "auto-g16-direct-submitted-job-read-lineage/1"
BACKEND_KIND = "direct_ssh_pbs"
MAX_DOCUMENT_BYTES = 1024 * 1024
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
JOURNAL_RE = re.compile(r"^direct-durable-submission-journal-[a-f0-9]{64}$")
LINEAGE_RE = re.compile(r"^direct-submitted-job-read-[a-f0-9]{64}$")

POLICY = {
    "server_local_clean_exec_required": True,
    "existing_workspace_read_only": True,
    "component_by_component_no_follow": True,
    "descriptor_relative_only": True,
    "portable_document_is_authority": False,
    "single_use_read_capability": True,
    "fork_revoked": True,
    "qsub": False,
    "second_qsub": False,
    "qstat": False,
    "fetch": False,
    "materialize": False,
    "qdel": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
    "scientific_acceptance": False,
}

AUTHORITY = {
    "authorizes_effect": False,
    "authorizes_read_successor": True,
    "portable_projection_authorizes_effect": False,
    "portable_projection_authorizes_read": False,
    "scientific_acceptance": False,
    "query_implemented": False,
    "fetch_implemented": False,
    "remote_effects": 0,
    "qsub_calls": 0,
    "qdel_calls": 0,
}


class DirectExistingJobLineageError(ValueError):
    """Existing-job lineage could not be proved exactly."""


class ExistingJobReconciliationOnly(DirectExistingJobLineageError):
    """The durable outcome is not completed and no read capability may issue."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectExistingJobLineageError(message)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DirectExistingJobLineageError("value is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _strict_json_bytes(
    raw: bytes,
    label: str,
    canonicalizer: Any = canonical_bytes,
) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_DOCUMENT_BYTES, f"{label} bytes differ")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DirectExistingJobLineageError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    def reject_float(token: str) -> Any:
        raise DirectExistingJobLineageError(f"{label} contains a non-integer number: {token}")

    def reject_constant(token: str) -> Any:
        raise DirectExistingJobLineageError(f"{label} contains a non-standard number: {token}")

    try:
        normalized = raw[:-1] if raw.endswith(b"\n") else raw
        value = json.loads(
            normalized.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectExistingJobLineageError(f"{label} is not strict UTF-8 JSON") from exc
    _require(type(value) is dict and canonicalizer(value) == raw, f"{label} bytes are not canonical")
    return value


def _load_reviewed(
    raw: bytes,
    label: str,
    validator: Any,
    canonicalizer: Any = canonical_bytes,
) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_DOCUMENT_BYTES, f"{label} bytes differ")
    value = _strict_json_bytes(raw, label, canonicalizer)
    validated = validator(value)
    _require(canonicalizer(validated) == raw, f"{label} canonical bytes differ")
    return validated


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and SHA_RE.fullmatch(value) is not None and value != ZERO_SHA, f"{label} differs")
    return value


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
    )


def _identity_sha256(identity: tuple[int, ...], schema: str) -> str:
    return digest({"schema": schema, "fields": [str(item) for item in identity]})


def _read_fd_exact(descriptor: int, expected_identity: tuple[int, ...], label: str) -> bytes:
    before = os.fstat(descriptor)
    _require(_file_identity(before) == expected_identity, f"{label} descriptor identity drifted")
    _require(
        stat.S_ISREG(before.st_mode)
        and before.st_uid == os.geteuid()
        and before.st_nlink == 1
        and before.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
        and 0 < before.st_size <= MAX_DOCUMENT_BYTES,
        f"{label} is not a bounded single-link owner file",
    )
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = before.st_size
    while remaining:
        chunk = os.read(descriptor, min(65536, remaining))
        _require(bool(chunk), f"{label} ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    _require(os.read(descriptor, 1) == b"", f"{label} grew during read")
    after = os.fstat(descriptor)
    _require(_file_identity(after) == expected_identity, f"{label} changed during read")
    return b"".join(chunks)


def _open_regular_at(parent_fd: int, basename: str, label: str) -> tuple[int, tuple[int, ...], bytes]:
    _require("/" not in basename and basename not in {"", ".", ".."}, f"{label} basename differs")
    descriptor = os.open(
        basename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    try:
        info = os.fstat(descriptor)
        identity = _file_identity(info)
        named = os.stat(basename, dir_fd=parent_fd, follow_symlinks=False)
        _require(identity == _file_identity(named), f"{label} named identity drifted")
        raw = _read_fd_exact(descriptor, identity, label)
        return descriptor, identity, raw
    except BaseException:
        os.close(descriptor)
        raise


def _open_lock_at(parent_fd: int) -> tuple[int, tuple[int, ...]]:
    descriptor = os.open(
        W2.LOCK_BASENAME,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    try:
        info = os.fstat(descriptor)
        identity = _file_identity(info)
        named = os.stat(W2.LOCK_BASENAME, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            identity == _file_identity(named)
            and stat.S_ISREG(info.st_mode)
            and info.st_uid == os.geteuid()
            and info.st_nlink == 1
            and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
            "durable lock identity differs",
        )
        return descriptor, identity
    except BaseException:
        os.close(descriptor)
        raise


def _open_absolute_directory_chain(path: Path, label: str) -> tuple[tuple[int, ...], tuple[str, ...], tuple[tuple[int, ...], ...]]:
    _require(isinstance(path, Path) and path.is_absolute(), f"{label} must be an absolute Path")
    names = tuple(PurePosixPath(str(path)).parts[1:])
    _require(bool(names) and all(name not in {"", ".", ".."} for name in names), f"{label} is unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    try:
        descriptor = os.open("/", flags)
        descriptors.append(descriptor)
        identities.append(_directory_identity(os.fstat(descriptor)))
        for name in names:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            _require(stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode), f"{label} contains a symlink or non-directory")
            child = os.open(name, flags, dir_fd=descriptor)
            child_info = os.fstat(child)
            after = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            child_identity = _directory_identity(child_info)
            _require(
                child_identity == _directory_identity(before) == _directory_identity(after),
                f"{label} component identity drifted",
            )
            descriptors.append(child)
            identities.append(child_identity)
            descriptor = child
        final = os.fstat(descriptors[-1])
        _require(
            final.st_uid == os.geteuid() and final.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"{label} owner or mode differs",
        )
        return tuple(descriptors), names, tuple(identities)
    except BaseException:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


class _DescriptorRecord(NamedTuple):
    root_fds: tuple[int, ...]
    root_names: tuple[str, ...]
    root_identities: tuple[tuple[int, ...], ...]
    project_fd: int
    project_identity: tuple[int, ...]
    receipt_fd: int
    receipt_identity: tuple[int, ...]
    state_fds: tuple[int, ...]
    state_names: tuple[str, ...]
    state_identities: tuple[tuple[int, ...], ...]
    journal_fd: int
    journal_identity: tuple[int, ...]
    lock_fd: int
    lock_identity: tuple[int, ...]
    manifest_fd: int
    manifest_identity: tuple[int, ...]
    started_fd: int
    started_identity: tuple[int, ...]
    terminal_fd: int
    terminal_identity: tuple[int, ...]
    project_name: str
    journal_name: str
    receipt_raw: bytes
    manifest_raw: bytes
    started_raw: bytes
    terminal_raw: bytes


def _all_descriptors(record: _DescriptorRecord) -> tuple[int, ...]:
    return (
        *record.root_fds,
        record.project_fd,
        record.receipt_fd,
        *record.state_fds,
        record.journal_fd,
        record.lock_fd,
        record.manifest_fd,
        record.started_fd,
        record.terminal_fd,
    )


def _close_record(record: _DescriptorRecord) -> None:
    for descriptor in reversed(_all_descriptors(record)):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _assert_named_directory(parent_fd: int, name: str, descriptor: int, identity: tuple[int, ...], label: str) -> None:
    current = os.fstat(descriptor)
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    _require(
        stat.S_ISDIR(current.st_mode)
        and not stat.S_ISLNK(named.st_mode)
        and _directory_identity(current) == identity == _directory_identity(named),
        f"{label} descriptor or named identity drifted",
    )


def _assert_named_file(parent_fd: int, name: str, descriptor: int, identity: tuple[int, ...], raw: bytes, label: str) -> None:
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    _require(_file_identity(named) == identity, f"{label} named identity drifted")
    _require(_read_fd_exact(descriptor, identity, label) == raw, f"{label} bytes drifted")


def _assert_descriptor_record_current(record: _DescriptorRecord) -> None:
    _require(type(record) is _DescriptorRecord, "descriptor record differs")
    _require(
        len(record.root_fds) == len(record.root_identities) == len(record.root_names) + 1
        and len(record.state_fds) == len(record.state_identities) == len(record.state_names) + 1,
        "descriptor chain shape differs",
    )
    for descriptors, names, identities, label in (
        (record.root_fds, record.root_names, record.root_identities, "allowed root"),
        (record.state_fds, record.state_names, record.state_identities, "durable state root"),
    ):
        for descriptor, identity in zip(descriptors, identities, strict=True):
            _require(
                _directory_identity(os.fstat(descriptor)) == identity
                and fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC,
                f"{label} retained descriptor drifted",
            )
        for index, name in enumerate(names, start=1):
            _assert_named_directory(descriptors[index - 1], name, descriptors[index], identities[index], f"{label} component")
    _assert_named_directory(record.root_fds[-1], record.project_name, record.project_fd, record.project_identity, "existing project")
    _assert_named_file(record.project_fd, W5.SUBMISSION_RECEIPT_BASENAME, record.receipt_fd, record.receipt_identity, record.receipt_raw, "remote submission receipt")
    _assert_named_directory(record.state_fds[-1], record.journal_name, record.journal_fd, record.journal_identity, "durable journal")
    for name, descriptor, identity, raw, label in (
        (W2.LOCK_BASENAME, record.lock_fd, record.lock_identity, b"", "durable lock"),
        (W2.MANIFEST_BASENAME, record.manifest_fd, record.manifest_identity, record.manifest_raw, "durable manifest"),
        (W2.STARTED_BASENAME, record.started_fd, record.started_identity, record.started_raw, "durable started event"),
        (W2.TERMINAL_BASENAME, record.terminal_fd, record.terminal_identity, record.terminal_raw, "durable terminal event"),
    ):
        named = os.stat(name, dir_fd=record.journal_fd, follow_symlinks=False)
        _require(_file_identity(named) == identity, f"{label} named identity drifted")
        if name == W2.LOCK_BASENAME:
            current = os.fstat(descriptor)
            _require(
                _file_identity(current) == identity
                and stat.S_ISREG(current.st_mode)
                and current.st_uid == os.geteuid()
                and current.st_nlink == 1
                and current.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
                "durable lock descriptor drifted",
            )
        else:
            _require(_read_fd_exact(descriptor, identity, label) == raw, f"{label} bytes drifted")


def _parse_w2_completed(
    state_root: Path,
    receipt: dict[str, Any],
) -> tuple[_DescriptorRecord, dict[str, Any]]:
    W2._assert_module_binding()
    journal_id = receipt["journal_id"]
    _require(type(journal_id) is str and JOURNAL_RE.fullmatch(journal_id) is not None, "W2 journal id differs")
    state_fds: tuple[int, ...] = ()
    journal_fd = lock_fd = manifest_fd = started_fd = terminal_fd = -1
    try:
        state_fds, state_names, state_identities = _open_absolute_directory_chain(state_root, "durable state root")
        journal_fd = os.open(
            journal_id,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=state_fds[-1],
        )
        journal_info = os.fstat(journal_fd)
        journal_identity = _directory_identity(journal_info)
        _assert_named_directory(state_fds[-1], journal_id, journal_fd, journal_identity, "durable journal")
        _require(
            journal_info.st_uid == os.geteuid() and journal_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
            "durable journal owner or mode differs",
        )
        lock_fd, lock_identity = _open_lock_at(journal_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        manifest_fd, manifest_identity, manifest_raw = _open_regular_at(journal_fd, W2.MANIFEST_BASENAME, "durable manifest")
        started_fd, started_identity, started_raw = _open_regular_at(journal_fd, W2.STARTED_BASENAME, "durable started event")
        try:
            terminal_fd, terminal_identity, terminal_raw = _open_regular_at(journal_fd, W2.TERMINAL_BASENAME, "durable terminal event")
        except FileNotFoundError as exc:
            raise ExistingJobReconciliationOnly("W2 started-only journal is reconciliation-only") from exc
        names = set(os.listdir(journal_fd))
        _require(
            names == {W2.LOCK_BASENAME, W2.MANIFEST_BASENAME, W2.STARTED_BASENAME, W2.TERMINAL_BASENAME},
            "W2 journal inventory differs",
        )
        manifest_document = _strict_json_bytes(manifest_raw, "durable manifest", W2.canonical_bytes)
        identity = W2._validate_identity(manifest_document.get("identity"))
        manifest = W2._validate_manifest(manifest_document, identity, journal_id)
        _require(W2._journal_id(identity) == journal_id, "W2 identity and journal id differ")
        started = W2._validate_event(
            _strict_json_bytes(started_raw, "durable started event", W2.canonical_bytes),
            journal_id=journal_id,
            binding_sha256=identity["binding_payload_sha256"],
            sequence=0,
            previous_event_sha256=W2.ZERO_SHA,
        )
        terminal = W2._validate_event(
            _strict_json_bytes(terminal_raw, "durable terminal event", W2.canonical_bytes),
            journal_id=journal_id,
            binding_sha256=identity["binding_payload_sha256"],
            sequence=1,
            previous_event_sha256=started["event_payload_sha256"],
        )
        if terminal["outcome"] != "completed" or terminal["state"] != "completed":
            raise ExistingJobReconciliationOnly("W2 unknown journal is reconciliation-only")
        _require(
            terminal["evidence_sha256"] == receipt["result_payload_sha256"],
            "W2 completed evidence and remote receipt hash differ",
        )
        snapshot = W2._finalize(
            {
                "schema": W2.SNAPSHOT_SCHEMA,
                "owner": W2.OWNER,
                "owner_version": W2.OWNER_VERSION,
                "journal_id": journal_id,
                "manifest_payload_sha256": manifest["manifest_payload_sha256"],
                "identity": copy.deepcopy(identity),
                "state": "completed",
                "last_recorded_outcome": "completed",
                "effective_outcome": "completed",
                "events": [copy.deepcopy(started), copy.deepcopy(terminal)],
                "reconciliation": {
                    "mode": "read_only_reconciliation_only",
                    "read_only": True,
                    "mutation_performed": False,
                    "automatic_retry": False,
                    "second_effect_allowed": False,
                    "started_without_terminal_is_unknown": True,
                },
                "policy": copy.deepcopy(W2.POLICY),
                "journal_payload_sha256": "",
            },
            "journal_payload_sha256",
        )
        snapshot = W2.validate_durable_journal_snapshot(snapshot)
        placeholder = _DescriptorRecord(
            (), (), (), -1, (), -1, (),
            state_fds, state_names, state_identities,
            journal_fd, journal_identity,
            lock_fd, lock_identity,
            manifest_fd, manifest_identity,
            started_fd, started_identity,
            terminal_fd, terminal_identity,
            "", journal_id, b"", manifest_raw, started_raw, terminal_raw,
        )
        state_fds = ()
        journal_fd = lock_fd = manifest_fd = started_fd = terminal_fd = -1
        return placeholder, snapshot
    except BaseException:
        for descriptor in (terminal_fd, started_fd, manifest_fd, lock_fd, journal_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        for descriptor in reversed(state_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _validate_reviewed_chain(
    portable_receipt_bytes: bytes,
    artifacts: SESSION.DirectServerSessionArtifacts,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    _require(type(artifacts) is SESSION.DirectServerSessionArtifacts, "exact reviewed W5 artifacts are required")
    W5._assert_production_binding()
    policy = _load_reviewed(artifacts.profile_policy, "profile policy", SESSION.W1.validate_profile_policy, SESSION.W1.canonical_bytes)
    stable = _load_reviewed(artifacts.stable_evidence, "stable root evidence", SESSION.W1.validate_stable_root_identity_evidence, SESSION.W1.canonical_bytes)
    profile = _load_reviewed(artifacts.profile, "direct profile", SESSION.W1.validate_direct_execution_profile, SESSION.W1.canonical_bytes)
    authorization = _load_reviewed(artifacts.authorization, "direct authorization", SESSION.W1.validate_direct_execution_authorization, SESSION.W1.canonical_bytes)
    transport = W5._validate_controller_artifact_join(artifacts)
    expected = W5._expected_controller_receipt_fields(artifacts, transport)
    receipt = _load_reviewed(portable_receipt_bytes, "portable W5 receipt", W5.validate_submission_receipt)
    _require(
        stable["profile_policy"]["profile_payload_sha256"] == policy["profile_payload_sha256"]
        and stable["reviewed_root_policy"]["declared_allowed_root"] == policy["declared_allowed_root"]
        and profile["profile_policy"]["profile_payload_sha256"] == policy["profile_payload_sha256"]
        and profile["stable_root_identity_evidence_sha256"] == stable["evidence_payload_sha256"]
        and authorization["profile"]["profile_payload_sha256"] == profile["profile_payload_sha256"]
        and authorization["root_evidence"]["evidence_payload_sha256"] == stable["evidence_payload_sha256"]
        and profile["transport_identity_binding_sha256"] == transport["profile_payload_sha256"]
        and policy["declared_allowed_root"] == profile["declared_allowed_root"] == authorization["workspace"]["allowed_root"] == transport["server"]["allowed_root"],
        "reviewed W5 profile, stable evidence, authorization, transport, or root join differs",
    )
    _require(
        all(receipt[field] == value for field, value in expected.items())
        and receipt["qsub"]["calls"] == "1"
        and receipt["invocation"]["call_count"] == "1"
        and receipt["authority"]["authorizes_effect"] is False,
        "portable W5 receipt is stale, foreign, or unbound",
    )
    binding_projection = {
        "workspace": {"project": authorization["workspace"]["project"]},
        "input": copy.deepcopy(authorization["input"]),
        "resources": copy.deepcopy(authorization["resources"]),
    }
    W5._validate_pbs_review(
        artifacts.pbs_review,
        artifacts.pbs_script,
        binding_projection,
        transport,
        transport["server"]["allowed_root"],
    )
    return policy, stable, profile, authorization, transport, receipt


def _open_existing_project_and_receipt(
    allowed_root: str,
    project: str,
    receipt_raw: bytes,
) -> _DescriptorRecord:
    _require(type(project) is str and PROJECT_RE.fullmatch(project) is not None, "existing project component differs")
    root_fds: tuple[int, ...] = ()
    project_fd = receipt_fd = -1
    try:
        root_fds, root_names, root_identities = _open_absolute_directory_chain(Path(allowed_root), "allowed root")
        project_fd = os.open(
            project,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fds[-1],
        )
        project_info = os.fstat(project_fd)
        project_identity = _directory_identity(project_info)
        _assert_named_directory(root_fds[-1], project, project_fd, project_identity, "existing project")
        _require(
            project_info.st_uid == os.geteuid() and project_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0,
            "existing project owner or mode differs",
        )
        receipt_fd, receipt_identity, remote_raw = _open_regular_at(project_fd, W5.SUBMISSION_RECEIPT_BASENAME, "remote submission receipt")
        _require(remote_raw == receipt_raw, "remote canonical receipt bytes differ from exact portable W5 receipt bytes")
        result = _DescriptorRecord(
            root_fds, root_names, root_identities,
            project_fd, project_identity,
            receipt_fd, receipt_identity,
            (), (), (), -1, (), -1, (), -1, (), -1, (), -1, (),
            project, "", remote_raw, b"", b"", b"",
        )
        root_fds = ()
        project_fd = receipt_fd = -1
        return result
    except BaseException:
        for descriptor in (receipt_fd, project_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        for descriptor in reversed(root_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _merge_records(project: _DescriptorRecord, journal: _DescriptorRecord) -> _DescriptorRecord:
    return _DescriptorRecord(
        project.root_fds, project.root_names, project.root_identities,
        project.project_fd, project.project_identity,
        project.receipt_fd, project.receipt_identity,
        journal.state_fds, journal.state_names, journal.state_identities,
        journal.journal_fd, journal.journal_identity,
        journal.lock_fd, journal.lock_identity,
        journal.manifest_fd, journal.manifest_identity,
        journal.started_fd, journal.started_identity,
        journal.terminal_fd, journal.terminal_identity,
        project.project_name, journal.journal_name,
        project.receipt_raw, journal.manifest_raw, journal.started_raw, journal.terminal_raw,
    )


def _assert_stable_root_chain(record: _DescriptorRecord, stable: dict[str, Any]) -> None:
    path_parts: list[str] = []
    components: list[dict[str, str]] = []
    for ordinal, (name, descriptor) in enumerate(
        zip(record.root_names, record.root_fds[1:], strict=True)
    ):
        path_parts.append(name)
        components.append(
            {
                "ordinal": str(ordinal),
                "component_path_sha256": hashlib.sha256(
                    ("/" + "/".join(path_parts)).encode("utf-8")
                ).hexdigest(),
                "identity_sha256": SESSION.W1._directory_identity_sha256(
                    os.fstat(descriptor)
                ),
            }
        )
    expected = stable["expected_root_identity"]
    _require(
        expected["canonical_root"] == "/" + "/".join(record.root_names)
        and expected["components"] == components,
        "current allowed-root descriptor chain differs from stable reviewed evidence",
    )


def _lineage_projection(
    artifacts: SESSION.DirectServerSessionArtifacts,
    profile: dict[str, Any],
    stable: dict[str, Any],
    authorization: dict[str, Any],
    transport: dict[str, Any],
    receipt: dict[str, Any],
    snapshot: dict[str, Any],
    descriptors: _DescriptorRecord,
) -> dict[str, Any]:
    identity = snapshot["identity"]
    _require(
        identity["binding_payload_sha256"] == receipt["binding_payload_sha256"]
        and identity["profile_payload_sha256"] == profile["profile_payload_sha256"]
        and identity["stable_root_evidence_sha256"] == stable["evidence_payload_sha256"]
        and identity["resource_catalog_sha256"] == profile["resource_catalog_sha256"]
        and identity["authorization_id"] == authorization["authorization_id"]
        and identity["authorization_payload_sha256"] == receipt["authorization_payload_sha256"]
        and identity["authorization_scope_sha256"] == authorization["scope"]["authorization_scope_sha256"]
        and identity["workspace_binding_sha256"] == authorization["workspace"]["workspace_binding_sha256"]
        and identity["project"] == receipt["project"]
        and identity["attempt_id"] == receipt["attempt_id"]
        and identity["input_sha256"] == receipt["input_sha256"]
        and identity["resources_sha256"] == W2.digest(authorization["resources"]),
        "W2 identity and reviewed W5 artifacts or receipt are spliced",
    )
    artifact_hashes = W5._artifact_hashes(artifacts)
    binding = {
        "journal_id": receipt["journal_id"],
        "binding_payload_sha256": receipt["binding_payload_sha256"],
        "attempt_id": receipt["attempt_id"],
        "project": receipt["project"],
        "input_sha256": receipt["input_sha256"],
        "authorization_payload_sha256": receipt["authorization_payload_sha256"],
        "authorization_scope_sha256": authorization["scope"]["authorization_scope_sha256"],
        "transport_profile_payload_sha256": transport["profile_payload_sha256"],
        "job_id": receipt["qsub"]["job_id"],
        "qsub_calls": receipt["qsub"]["calls"],
        "invocation_payload_sha256": receipt["qsub"]["invocation_payload_sha256"],
        "outcome_payload_sha256": receipt["qsub"]["outcome_payload_sha256"],
        "result_payload_sha256": receipt["result_payload_sha256"],
        "receipt_id": receipt["receipt_id"],
        "remote_receipt_bytes_sha256": hashlib.sha256(descriptors.receipt_raw).hexdigest(),
    }
    lineage_id = "direct-submitted-job-read-" + digest(
        {
            "schema": "auto-g16-direct-submitted-job-read-id/1",
            "binding": binding,
            "project_descriptor_identity_sha256": _identity_sha256(descriptors.project_identity, "auto-g16-project-descriptor-identity/1"),
            "receipt_descriptor_identity_sha256": _identity_sha256(descriptors.receipt_identity, "auto-g16-receipt-descriptor-identity/1"),
            "journal_descriptor_identity_sha256": _identity_sha256(descriptors.journal_identity, "auto-g16-journal-descriptor-identity/1"),
        }
    )
    document = {
        "schema": RESULT_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "lineage_id": lineage_id,
        "backend_kind": BACKEND_KIND,
        "artifact_sha256": artifact_hashes,
        "binding": binding,
        "durable": {
            "state": "completed",
            "effective_outcome": "completed",
            "manifest_payload_sha256": snapshot["manifest_payload_sha256"],
            "started_event_payload_sha256": snapshot["events"][0]["event_payload_sha256"],
            "terminal_event_payload_sha256": snapshot["events"][1]["event_payload_sha256"],
            "terminal_evidence_sha256": snapshot["events"][1]["evidence_sha256"],
            "journal_payload_sha256": snapshot["journal_payload_sha256"],
            "reconciliation_only_after_noncompleted": True,
        },
        "descriptor_identity": {
            "project_sha256": _identity_sha256(descriptors.project_identity, "auto-g16-project-descriptor-identity/1"),
            "receipt_sha256": _identity_sha256(descriptors.receipt_identity, "auto-g16-receipt-descriptor-identity/1"),
            "journal_sha256": _identity_sha256(descriptors.journal_identity, "auto-g16-journal-descriptor-identity/1"),
        },
        "policy": copy.deepcopy(POLICY),
        "authority": copy.deepcopy(AUTHORITY),
        "result_payload_sha256": "",
    }
    document["result_payload_sha256"] = digest(document)
    return validate_lineage_projection(document)


def validate_lineage_projection(value: Any) -> dict[str, Any]:
    _require(type(value) is dict, "lineage projection must be an object")
    required = {
        "schema", "owner", "owner_version", "lineage_id", "backend_kind",
        "artifact_sha256", "binding", "durable", "descriptor_identity",
        "policy", "authority", "result_payload_sha256",
    }
    _require(set(value) == required, "lineage projection fields differ")
    document = copy.deepcopy(value)
    _require(
        document["schema"] == RESULT_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and document["backend_kind"] == BACKEND_KIND
        and type(document["lineage_id"]) is str
        and LINEAGE_RE.fullmatch(document["lineage_id"]) is not None
        and document["policy"] == POLICY
        and document["authority"] == AUTHORITY,
        "lineage projection constants differ",
    )
    artifact_names = set(SESSION.DirectServerSessionArtifacts.__dataclass_fields__)
    _require(
        type(document["artifact_sha256"]) is dict
        and set(document["artifact_sha256"]) == artifact_names,
        "lineage artifact hashes differ",
    )
    for field, item in document["artifact_sha256"].items():
        _sha(item, f"lineage artifact {field}")
    binding_fields = {
        "journal_id", "binding_payload_sha256", "attempt_id", "project", "input_sha256",
        "authorization_payload_sha256", "authorization_scope_sha256",
        "transport_profile_payload_sha256", "job_id", "qsub_calls",
        "invocation_payload_sha256", "outcome_payload_sha256",
        "result_payload_sha256", "receipt_id", "remote_receipt_bytes_sha256",
    }
    binding = document["binding"]
    _require(type(binding) is dict and set(binding) == binding_fields, "lineage binding fields differ")
    for field in (
        "binding_payload_sha256", "input_sha256", "authorization_payload_sha256",
        "authorization_scope_sha256", "transport_profile_payload_sha256",
        "invocation_payload_sha256", "outcome_payload_sha256", "result_payload_sha256",
        "remote_receipt_bytes_sha256",
    ):
        _sha(binding[field], f"lineage binding {field}")
    _require(
        JOURNAL_RE.fullmatch(binding["journal_id"]) is not None
        and binding["qsub_calls"] == "1"
        and W5.JOB_ID_RE.fullmatch(binding["job_id"] + "\n") is not None
        and W5.ATTEMPT_ID_RE.fullmatch(binding["attempt_id"]) is not None
        and W5.RECEIPT_ID_RE.fullmatch(binding["receipt_id"]) is not None
        and type(binding["project"]) is str
        and bool(binding["project"]),
        "lineage binding identifiers differ",
    )
    durable = document["durable"]
    _require(
        type(durable) is dict
        and set(durable) == {
            "state", "effective_outcome", "manifest_payload_sha256",
            "started_event_payload_sha256", "terminal_event_payload_sha256",
            "terminal_evidence_sha256", "journal_payload_sha256",
            "reconciliation_only_after_noncompleted",
        }
        and durable["state"] == "completed"
        and durable["effective_outcome"] == "completed"
        and durable["reconciliation_only_after_noncompleted"] is True,
        "lineage durable outcome differs",
    )
    for field in (
        "manifest_payload_sha256", "started_event_payload_sha256",
        "terminal_event_payload_sha256", "terminal_evidence_sha256",
        "journal_payload_sha256",
    ):
        _sha(durable[field], f"lineage durable {field}")
    _require(
        durable["terminal_evidence_sha256"] == binding["result_payload_sha256"],
        "lineage terminal evidence and receipt result differ",
    )
    descriptor = document["descriptor_identity"]
    _require(
        type(descriptor) is dict
        and set(descriptor) == {"project_sha256", "receipt_sha256", "journal_sha256"},
        "lineage descriptor identities differ",
    )
    for field in descriptor:
        _sha(descriptor[field], f"lineage descriptor {field}")
    expected_lineage_id = "direct-submitted-job-read-" + digest(
        {
            "schema": "auto-g16-direct-submitted-job-read-id/1",
            "binding": binding,
            "project_descriptor_identity_sha256": descriptor["project_sha256"],
            "receipt_descriptor_identity_sha256": descriptor["receipt_sha256"],
            "journal_descriptor_identity_sha256": descriptor["journal_sha256"],
        }
    )
    _require(
        document["lineage_id"] == expected_lineage_id,
        "lineage id derivation differs",
    )
    _sha(document["result_payload_sha256"], "lineage result")
    projection = copy.deepcopy(document)
    projection["result_payload_sha256"] = ""
    _require(document["result_payload_sha256"] == digest(projection), "lineage result hash differs")
    return document


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str


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
    identity = _file_identity(before)
    _require(
        stat.S_ISREG(before.st_mode) and identity == _file_identity(after),
        "existing-job lineage owner source identity drifted",
    )
    return _SourceSnapshot(path, identity, hashlib.sha256(b"".join(chunks)).hexdigest())


class _CapabilityRecord(NamedTuple):
    capability: object
    creator_pid: int
    epoch: object
    seal: object
    lineage_id: str
    projection_bytes: bytes
    descriptors: _DescriptorRecord
    transport_profile_raw: bytes


class DirectSubmittedJobReadCapability:
    """Process-local single-use authority for one future read successor."""

    __slots__ = ("lineage_id", "_creator_pid", "_epoch", "_projection_bytes", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("submitted-job read capabilities are owner-issued only")

    def assert_current(self) -> None:
        _CAPABILITY_ASSERT(self, "capability")

    def portable_projection(self) -> dict[str, Any]:
        return copy.deepcopy(_strict_json_bytes(_CAPABILITY_PROJECT(self, "capability"), "lineage projection"))

    def consume_once(self) -> "DirectSubmittedJobReadLease":
        return _CAPABILITY_CONSUME(self)

    def __copy__(self) -> Any:
        raise TypeError("submitted-job read capabilities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("submitted-job read capabilities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("submitted-job read capabilities are not serializable")


class DirectSubmittedJobReadLease:
    """Descriptor-retaining lease for one fixed reviewed read successor."""

    __slots__ = ("lineage_id", "_creator_pid", "_epoch", "_projection_bytes", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("submitted-job read leases are owner-issued only")

    def assert_current(self) -> None:
        _CAPABILITY_ASSERT(self, "lease")

    def portable_projection(self) -> dict[str, Any]:
        return copy.deepcopy(_strict_json_bytes(_CAPABILITY_PROJECT(self, "lease"), "lineage projection"))

    def close_once(self) -> None:
        _CAPABILITY_CLOSE(self)

    def __copy__(self) -> Any:
        raise TypeError("submitted-job read leases are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("submitted-job read leases are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("submitted-job read leases are not serializable")


def _build_capability_owner_entries() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    lock = threading.RLock()
    registry: dict[int, tuple[str, _CapabilityRecord]] = {}
    issued_lineage: set[str] = set()
    epoch = object()
    descriptor_checker = _assert_descriptor_record_current
    projection_validator = validate_lineage_projection

    def exact_live(value: Any, kind: str) -> _CapabilityRecord:
        nonlocal epoch
        expected_type = DirectSubmittedJobReadCapability if kind == "capability" else DirectSubmittedJobReadLease
        with lock:
            entry = registry.get(id(value))
            _require(type(entry) is tuple and len(entry) == 2 and entry[0] == kind, f"submitted-job read {kind} is absent or terminal")
            record = entry[1]
            _require(
                type(value) is expected_type
                and type(record) is _CapabilityRecord
                and record.capability is value
                and record.creator_pid == os.getpid() == value._creator_pid
                and record.epoch is epoch is value._epoch
                and record.seal is value._seal
                and record.lineage_id == value.lineage_id
                and record.projection_bytes == value._projection_bytes,
                f"submitted-job read {kind} is foreign, forked, forged, or rebound",
            )
            descriptor_checker(record.descriptors)
            return record

    def issue(
        projection: dict[str, Any],
        descriptors: _DescriptorRecord,
        transport_profile_raw: bytes,
    ) -> DirectSubmittedJobReadCapability:
        nonlocal epoch
        projection = projection_validator(projection)
        lineage_id = projection["lineage_id"]
        raw = canonical_bytes(projection)
        with lock:
            _require(lineage_id not in issued_lineage, "duplicate existing-job lineage acquisition is blocked in this process")
            capability = object.__new__(DirectSubmittedJobReadCapability)
            seal = object()
            capability.lineage_id = lineage_id
            capability._creator_pid = os.getpid()
            capability._epoch = epoch
            capability._projection_bytes = raw
            capability._seal = seal
            _require(
                type(transport_profile_raw) is bytes
                and hashlib.sha256(transport_profile_raw).hexdigest()
                == projection["artifact_sha256"]["transport_profile"],
                "existing-job transport-profile bytes differ",
            )
            record = _CapabilityRecord(
                capability, os.getpid(), epoch, seal, lineage_id, raw,
                descriptors, bytes(transport_profile_raw),
            )
            registry[id(capability)] = ("capability", record)
            issued_lineage.add(lineage_id)
        exact_live(capability, "capability")
        return capability

    def assert_current(value: Any, kind: str) -> None:
        exact_live(value, kind)

    def projection_bytes(value: Any, kind: str) -> bytes:
        return bytes(exact_live(value, kind).projection_bytes)

    def consume(capability: DirectSubmittedJobReadCapability) -> DirectSubmittedJobReadLease:
        nonlocal epoch
        record = exact_live(capability, "capability")
        with lock:
            current = registry.get(id(capability))
            _require(current == ("capability", record), "submitted-job read capability consume raced")
            del registry[id(capability)]
            lease = object.__new__(DirectSubmittedJobReadLease)
            seal = object()
            lease.lineage_id = record.lineage_id
            lease._creator_pid = os.getpid()
            lease._epoch = epoch
            lease._projection_bytes = record.projection_bytes
            lease._seal = seal
            lease_record = _CapabilityRecord(
                lease, os.getpid(), epoch, seal, record.lineage_id,
                record.projection_bytes, record.descriptors,
                record.transport_profile_raw,
            )
            registry[id(lease)] = ("lease", lease_record)
        exact_live(lease, "lease")
        return lease

    def handoff_to_fetch_successor(
        lease: DirectSubmittedJobReadLease,
        successor_owner: object,
        test_token: object,
    ) -> object:
        """Consume into the one canonical fetch successor without exposing FDs."""
        record = exact_live(lease, "lease")
        successor = sys.modules.get("direct_fetch_acquisition")
        expected_path = Path(__file__).resolve().with_name("direct_fetch_acquisition.py")
        accept = getattr(successor, "_accept_lineage_handoff_once", None)
        owner_type = getattr(successor, "DirectFetchAcquisitionOwner", None)
        expected_test_token = getattr(successor, "_TEST_TOKEN", None)
        expected_production_token = getattr(
            successor, "_PRODUCTION_OWNER_TOKEN", None,
        )
        assert_binding = getattr(successor, "_assert_module_binding", None)
        _require(
            type(successor) is types.ModuleType
            and Path(getattr(successor, "__file__", "")).resolve() == expected_path
            and type(owner_type) is type
            and type(successor_owner) is owner_type
            and test_token in {expected_test_token, expected_production_token}
            and callable(accept)
            and callable(assert_binding),
            "canonical direct fetch successor binding differs",
        )
        assert_binding()
        with lock:
            current = registry.get(id(lease))
            _require(current == ("lease", record), "submitted-job read successor handoff raced")
            del registry[id(lease)]
        try:
            return accept(
                successor_owner,
                bytes(record.projection_bytes),
                record.descriptors,
                bytes(record.transport_profile_raw),
                test_token,
            )
        except BaseException:
            _close_record(record.descriptors)
            raise

    def close(lease: DirectSubmittedJobReadLease) -> None:
        record = exact_live(lease, "lease")
        with lock:
            current = registry.get(id(lease))
            _require(current == ("lease", record), "submitted-job read lease close raced")
            del registry[id(lease)]
        _close_record(record.descriptors)

    def after_fork_child() -> None:
        nonlocal lock, epoch
        for _kind, record in tuple(registry.values()):
            _close_record(record.descriptors)
        registry.clear()
        issued_lineage.clear()
        lock = threading.RLock()
        epoch = object()

    return (
        issue, assert_current, projection_bytes, consume, close,
        handoff_to_fetch_successor, after_fork_child,
    )


(
    _CAPABILITY_ISSUE,
    _CAPABILITY_ASSERT,
    _CAPABILITY_PROJECT,
    _CAPABILITY_CONSUME,
    _CAPABILITY_CLOSE,
    _CAPABILITY_HANDOFF_FETCH,
    _CAPABILITY_FORK_CHILD,
) = _build_capability_owner_entries()

os.register_at_fork(after_in_child=_CAPABILITY_FORK_CHILD)


_QSTAT_SUCCESSOR_BINDING_LOCK = threading.RLock()
_QSTAT_SUCCESSOR_BINDING: tuple[types.ModuleType, object, object, type, str] | None = None


def _resolve_qstat_successor_owner() -> tuple[object, type]:
    """Resolve the sole Q1 successor without importing or reconstructing it."""

    global _QSTAT_SUCCESSOR_BINDING
    module = sys.modules.get("direct_qstat_acquisition")
    expected_path = os.path.realpath(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "direct_qstat_acquisition.py")
    )
    module_path = os.path.realpath(getattr(module, "__file__", ""))
    join_type = getattr(module, "_ExactLineageConsumerJoin", None)
    join_assert = getattr(module, "_assert_exact_lineage_consumer_join", None)
    module_assert = getattr(module, "_assert_module_binding", None)
    executed_sha256 = getattr(module, "_EXECUTED_SOURCE_SHA256", None)
    _require(
        type(module) is types.ModuleType
        and module_path == expected_path
        and type(join_type) is type
        and join_type.__module__ == "direct_qstat_acquisition"
        and callable(join_assert)
        and callable(module_assert)
        and getattr(module_assert, "__module__", None) == "direct_qstat_acquisition"
        and getattr(module_assert, "__name__", None) == "_assert_module_binding"
        and type(executed_sha256) is str
        and SHA_RE.fullmatch(executed_sha256) is not None,
        "canonical qstat acquisition successor differs",
    )
    with open(expected_path, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(source_sha256 == executed_sha256, "canonical qstat acquisition source differs")
    module_assert()
    candidate = (module, module_assert, join_assert, join_type, source_sha256)
    with _QSTAT_SUCCESSOR_BINDING_LOCK:
        if _QSTAT_SUCCESSOR_BINDING is None:
            _QSTAT_SUCCESSOR_BINDING = candidate
        _require(
            _QSTAT_SUCCESSOR_BINDING == candidate,
            "canonical qstat acquisition successor was reloaded or rebound",
        )
    return join_assert, join_type


def _consume_for_exact_qstat_once(
    capability: DirectSubmittedJobReadCapability,
    consumer_join: object,
) -> tuple[DirectSubmittedJobReadLease, bytes]:
    """Consume L1 only for the exact Q1 owner and retain its live lease.

    The returned projection bytes are evidence carried alongside the exact
    owner-registered lease.  They are never sufficient without that lease.
    """

    _assert_module_binding()
    join_assert, join_type = _resolve_qstat_successor_owner()
    _require(type(consumer_join) is join_type, "exact qstat lineage consumer join is required")
    join_assert(consumer_join, capability)
    lease = capability.consume_once()
    try:
        lease.assert_current()
        projection_raw = _CAPABILITY_PROJECT(lease, "lease")
        _strict_json_bytes(projection_raw, "lineage projection")
        return lease, projection_raw
    except BaseException:
        try:
            lease.close_once()
        except BaseException:
            pass
        raise


def _clear_qstat_successor_after_fork() -> None:
    global _QSTAT_SUCCESSOR_BINDING, _QSTAT_SUCCESSOR_BINDING_LOCK
    _QSTAT_SUCCESSOR_BINDING = None
    _QSTAT_SUCCESSOR_BINDING_LOCK = threading.RLock()


os.register_at_fork(after_in_child=_clear_qstat_successor_after_fork)


@dataclass(frozen=True, slots=True)
class _ModuleBinding:
    module: types.ModuleType
    source: _SourceSnapshot
    w2_module: types.ModuleType
    w5_module: types.ModuleType
    session_module: types.ModuleType
    w2_assert: object
    w5_assert: object
    w2_entries: tuple[object, ...]
    owner_entries: tuple[object, ...]
    validator: object
    issued_types: tuple[type, ...]


def _capture_module_binding() -> _ModuleBinding:
    _require(__name__ == MODULE_NAME, "existing-job lineage owner must use its canonical module name")
    module = sys.modules.get(MODULE_NAME)
    _require(type(module) is types.ModuleType, "canonical existing-job lineage module is unavailable")
    issued = (DirectSubmittedJobReadCapability, DirectSubmittedJobReadLease)
    for issued_type in issued:
        _require(issued_type.__module__ == MODULE_NAME and getattr(module, issued_type.__name__, None) is issued_type, "existing-job issued type identity differs")
    return _ModuleBinding(
        module,
        _stable_source(Path(__file__).resolve()),
        W2,
        W5,
        SESSION,
        W2._assert_module_binding,
        W5._assert_production_binding,
        (
            W2._validate_identity,
            W2._validate_manifest,
            W2._validate_event,
            W2._journal_id,
            W2._finalize,
            W2.validate_durable_journal_snapshot,
            W2.canonical_bytes,
            W2.digest,
        ),
        (
            _CAPABILITY_ISSUE,
            _CAPABILITY_ASSERT,
            _CAPABILITY_PROJECT,
            _CAPABILITY_CONSUME,
            _CAPABILITY_CLOSE,
            _CAPABILITY_HANDOFF_FETCH,
            _CAPABILITY_FORK_CHILD,
            _resolve_qstat_successor_owner,
            _consume_for_exact_qstat_once,
            _clear_qstat_successor_after_fork,
        ),
        validate_lineage_projection,
        issued,
    )


_MODULE_BINDING = _capture_module_binding()


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    _require(
        type(binding) is _ModuleBinding
        and sys.modules.get(MODULE_NAME) is binding.module
        and sys.modules.get(binding.w2_module.__name__) is binding.w2_module
        and sys.modules.get(binding.w5_module.__name__) is binding.w5_module
        and sys.modules.get(binding.session_module.__name__) is binding.session_module
        and W2 is binding.w2_module
        and W5 is binding.w5_module
        and SESSION is binding.session_module
        and W2._assert_module_binding is binding.w2_assert
        and W5._assert_production_binding is binding.w5_assert
        and binding.w2_entries == (
            W2._validate_identity,
            W2._validate_manifest,
            W2._validate_event,
            W2._journal_id,
            W2._finalize,
            W2.validate_durable_journal_snapshot,
            W2.canonical_bytes,
            W2.digest,
        )
        and binding.owner_entries == (
            _CAPABILITY_ISSUE,
            _CAPABILITY_ASSERT,
            _CAPABILITY_PROJECT,
            _CAPABILITY_CONSUME,
            _CAPABILITY_CLOSE,
            _CAPABILITY_HANDOFF_FETCH,
            _CAPABILITY_FORK_CHILD,
            _resolve_qstat_successor_owner,
            _consume_for_exact_qstat_once,
            _clear_qstat_successor_after_fork,
        )
        and validate_lineage_projection is binding.validator
        and _stable_source(Path(__file__).resolve()) == binding.source,
        "existing-job lineage source, module, or predecessor owner binding differs",
    )
    W2._assert_module_binding()
    W5._assert_production_binding()
    for issued_type in binding.issued_types:
        _require(getattr(binding.module, issued_type.__name__, None) is issued_type, "existing-job issued type identity differs")


_PRODUCTION_OWNER_TOKEN = object()
_TEST_OWNER_TOKEN = object()


class DirectExistingJobLineageOwner:
    """Sole issuer for existing submitted-job read capabilities."""

    __slots__ = ("_state_root", "_pid", "_lock", "_used", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("existing-job lineage owners use a fixed factory")

    @classmethod
    def production(cls) -> "DirectExistingJobLineageOwner":
        _assert_module_binding()
        _require(
            sys.flags.isolated == 1
            and sys.flags.no_site == 1
            and Path.cwd() == Path("/")
            and os.environ.get("LANG") == "C"
            and os.environ.get("LC_ALL") == "C",
            "production existing-job lineage requires the fixed -I -S server process",
        )
        return _new_owner(
            SESSION.FIXED_PRODUCTION_DURABLE_STATE_ROOT,
            _PRODUCTION_OWNER_TOKEN,
        )

    @classmethod
    def _for_fake_local_testing(
        cls,
        *,
        durable_state_root: Path,
        _test_token: object,
    ) -> "DirectExistingJobLineageOwner":
        _require(_test_token is _TEST_OWNER_TOKEN, "existing-job lineage test token differs")
        return _new_owner(durable_state_root, _TEST_OWNER_TOKEN)

    def issue_once(
        self,
        portable_receipt_bytes: bytes,
        artifacts: SESSION.DirectServerSessionArtifacts,
    ) -> DirectSubmittedJobReadCapability:
        with self._lock:
            _require(
                type(self) is DirectExistingJobLineageOwner
                and self._pid == os.getpid()
                and self._used is False,
                "existing-job lineage owner is foreign, forked, or already used",
            )
            _require(
                self._seal is _PRODUCTION_OWNER_TOKEN or self._seal is _TEST_OWNER_TOKEN,
                "existing-job lineage owner seal differs",
            )
            if self._seal is _PRODUCTION_OWNER_TOKEN:
                _require(
                    self._state_root is SESSION.FIXED_PRODUCTION_DURABLE_STATE_ROOT
                    and sys.flags.isolated == 1
                    and sys.flags.no_site == 1
                    and Path.cwd() == Path("/")
                    and os.environ.get("LANG") == "C"
                    and os.environ.get("LC_ALL") == "C",
                    "production existing-job lineage root or clean-exec binding differs",
                )
            self._used = True
        _assert_module_binding()
        project_record: _DescriptorRecord | None = None
        journal_record: _DescriptorRecord | None = None
        merged: _DescriptorRecord | None = None
        try:
            _policy, stable, profile, authorization, transport, receipt = _validate_reviewed_chain(
                portable_receipt_bytes,
                artifacts,
            )
            project_record = _open_existing_project_and_receipt(
                transport["server"]["allowed_root"],
                receipt["project"],
                portable_receipt_bytes,
            )
            _assert_stable_root_chain(project_record, stable)
            journal_record, snapshot = _parse_w2_completed(self._state_root, receipt)
            merged = _merge_records(project_record, journal_record)
            project_record = journal_record = None
            _assert_descriptor_record_current(merged)
            projection = _lineage_projection(
                artifacts,
                profile,
                stable,
                authorization,
                transport,
                receipt,
                snapshot,
                merged,
            )
            capability = _CAPABILITY_ISSUE(
                projection, merged, artifacts.transport_profile,
            )
            merged = None
            return capability
        except ExistingJobReconciliationOnly:
            raise
        except DirectExistingJobLineageError:
            raise
        except Exception as exc:
            raise DirectExistingJobLineageError(
                f"existing-job lineage observation failed closed: {exc}"
            ) from exc
        finally:
            for record in (merged, project_record, journal_record):
                if record is not None:
                    _close_record(record)


def _new_owner(state_root: Path, seal: object) -> DirectExistingJobLineageOwner:
    _require(isinstance(state_root, Path) and state_root.is_absolute(), "existing-job durable state root differs")
    _require(
        seal is _PRODUCTION_OWNER_TOKEN or seal is _TEST_OWNER_TOKEN,
        "existing-job lineage owner factory seal differs",
    )
    value = object.__new__(DirectExistingJobLineageOwner)
    value._state_root = state_root
    value._pid = os.getpid()
    value._lock = threading.RLock()
    value._used = False
    value._seal = seal
    return value


__all__ = [
    "DirectExistingJobLineageError",
    "ExistingJobReconciliationOnly",
    "DirectExistingJobLineageOwner",
    "DirectSubmittedJobReadCapability",
    "DirectSubmittedJobReadLease",
    "validate_lineage_projection",
]
