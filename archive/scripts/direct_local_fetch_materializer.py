#!/usr/bin/env python3
"""Repo-external, descriptor-relative, no-clobber local fetch materializer.

This module owns only local target selection, a single-use target capability,
an offline synthetic stream lease, and fixed artifact materialization.  It has
no network, SSH, scheduler, remote-fetch, cancellation, inspection, retry,
resume, overwrite, rename-replace, deletion, cleanup, or scientific-acceptance
surface.  Production stream integration remains blocked until the T3 shared-
channel owner and its exact lease type are frozen and independently reviewed.
"""

from __future__ import annotations

if globals().get("_AUTO_G16_DIRECT_LOCAL_FETCH_MATERIALIZER_EXECUTED", False):
    raise ImportError("direct local fetch materializer owner module already executed")
_AUTO_G16_DIRECT_LOCAL_FETCH_MATERIALIZER_EXECUTED = True

import copy
import errno
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import threading
import types
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple


MODULE_NAME = "direct_local_fetch_materializer"
OWNER = "auto-g16-direct-local-fetch-materializer-owner"
OWNER_VERSION = "direct-local-fetch-materializer/1"
POLICY_SCHEMA = "auto-g16-direct-local-fetch-target-policy/1"
STREAM_SCHEMA = "auto-g16-direct-fetch-stream-projection/1"
MANIFEST_SCHEMA = "auto-g16-direct-fetch-manifest/1"
BACKEND_KIND = "direct_ssh_pbs"
MATERIALIZATION_MODE = "descriptor_relative_no_clobber"
STREAM_MODE = "offline_synthetic"
LEGACY_CLOSED_STREAM_MODE = "closed_fetch_acquisition_offline_fake"
CLOSED_STREAM_MODE = "closed_fetch_acquisition_exact_owner"
PRODUCTION_SUCCESSOR = "T3_shared_channel_owner_exact_type_not_frozen"
CLOSED_PRODUCTION_SUCCESSOR = "Q1_backend_owned_reviewed_read_authority_exact_type"
LEGACY_PRODUCTION_TARGET_PREDECESSOR = (
    "reviewed_local_policy_owner_exact_type_not_frozen"
)
PRODUCTION_TARGET_PREDECESSOR = (
    "backend_owned_fixed_local_fetch_target_policy_exact_type"
)
FIXED_PRODUCTION_TARGET_POLICY_PATH = Path(
    "/Library/Application Support/Auto-G16/direct-local-fetch-target-v1.json"
)
MAX_PRODUCTION_TARGET_POLICY_BYTES = 64 * 1024
MANIFEST_BASENAME = "direct-fetch-manifest.json"
CHUNK_SIZE_BYTES = 1024 * 1024
ZERO_SHA = "0" * 64
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
JOB_RE = re.compile(r"^[1-9][0-9]{0,19}\.[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
LEAF_RE = re.compile(r"^direct-fetch-[a-f0-9]{48}$")

ARTIFACT_SPECS = (
    ("approved-input.gjf", 16 * 1024 * 1024),
    ("auto-g16-job.pbs", 1 * 1024 * 1024),
    ("checksums.sha256", 64 * 1024),
    ("submission-receipt.json", 256 * 1024),
    ("approved-input.log", 1 * 1024 * 1024 * 1024),
)
ARTIFACT_BASENAMES = tuple(item[0] for item in ARTIFACT_SPECS)
ARTIFACT_CAPS = dict(ARTIFACT_SPECS)
TOTAL_CAP_BYTES = sum(item[1] for item in ARTIFACT_SPECS)

_CAPABILITY_TOKEN = object()
_LEASE_TOKEN = object()
_OWNER_TOKEN = object()
_PROCESS_EPOCH = object()
_PROCESS_EPOCH_SHA256 = hashlib.sha256(
    f"{os.getpid()}:{id(_PROCESS_EPOCH)}".encode("ascii")
).hexdigest()
_REGISTRY_LOCK = threading.RLock()
_TARGET_REGISTRY: dict[int, "_TargetRecord"] = {}
_STREAM_REGISTRY: dict[int, "_StreamRecord"] = {}


class DirectLocalFetchMaterializerError(ValueError):
    """The fixed local materialization contract cannot be proved safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectLocalFetchMaterializerError(message)


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
        raise DirectLocalFetchMaterializerError(
            f"value is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[field] = ""
    result[field] = digest(result)
    return result


def _sha(value: Any, label: str, *, allow_empty: bool = False) -> str:
    _require(
        type(value) is str
        and SHA_RE.fullmatch(value) is not None
        and value != ZERO_SHA
        and (allow_empty or value != EMPTY_SHA),
        f"{label} must be a lowercase nonzero SHA-256",
    )
    return value


def _decimal(value: Any, label: str, *, maximum: int | None = None) -> int:
    _require(
        type(value) is str
        and re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", value) is not None,
        f"{label} must be a canonical decimal string",
    )
    number = int(value)
    _require(maximum is None or number <= maximum, f"{label} exceeds its fixed cap")
    return number


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


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


def _descriptor_identity(descriptor: int, label: str) -> _DescriptorIdentity:
    _require(type(descriptor) is int and descriptor >= 0, f"{label} descriptor differs")
    try:
        info = os.fstat(descriptor)
        status_flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
    except OSError as exc:
        raise DirectLocalFetchMaterializerError(
            f"{label} descriptor is closed or invalid: {exc}"
        ) from exc
    return _DescriptorIdentity(
        descriptor,
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_rdev,
        status_flags,
        descriptor_flags,
    )


def _directory_tuple(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
    )


def _regular_tuple(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
        info.st_nlink,
    )


def _close_if_same(identity: _DescriptorIdentity) -> None:
    try:
        current = _descriptor_identity(identity.descriptor, "owned")
    except DirectLocalFetchMaterializerError:
        return
    if current == identity:
        try:
            os.close(identity.descriptor)
        except OSError:
            pass


def _canonical_absolute_directory(path: Any, label: str) -> str:
    _require(type(path) is str and path.startswith("/"), f"{label} must be absolute")
    _require(
        path == os.path.normpath(path)
        and path == os.path.realpath(path)
        and path not in {"/", ""},
        f"{label} must be a canonical non-root path without symlinks",
    )
    return path


def _open_directory_chain_no_follow(path: str) -> tuple[tuple[str, ...], tuple[tuple[int, ...], ...], _DescriptorIdentity]:
    _require(
        all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")),
        "descriptor-relative no-follow support is unavailable",
    )
    parts = tuple(part for part in path.split("/") if part)
    _require(parts and all(part not in {".", ".."} for part in parts), "target-root components differ")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    current = os.open("/", flags)
    opened: list[int] = [current]
    identities: list[tuple[int, ...]] = []
    try:
        for part in parts:
            before = os.stat(part, dir_fd=current, follow_symlinks=False)
            _require(stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode), "target-root ancestor is not a no-follow directory")
            following = os.open(part, flags, dir_fd=current)
            opened.append(following)
            after = os.stat(part, dir_fd=current, follow_symlinks=False)
            opened_info = os.fstat(following)
            expected = _directory_tuple(before)
            _require(expected == _directory_tuple(after) == _directory_tuple(opened_info), "target-root ancestor identity drifted")
            identities.append(expected)
            current = following
        final_info = os.fstat(current)
        _require(
            stat.S_ISDIR(final_info.st_mode)
            and final_info.st_uid == os.geteuid()
            and not (stat.S_IMODE(final_info.st_mode) & 0o022),
            "target root must be an owner-held non-group/world-writable directory",
        )
        retained = os.dup(current)
        retained_flags = fcntl.fcntl(retained, fcntl.F_GETFD)
        fcntl.fcntl(retained, fcntl.F_SETFD, retained_flags | fcntl.FD_CLOEXEC)
        return parts, tuple(identities), _descriptor_identity(retained, "target root")
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _open_fixed_production_policy_no_follow() -> int:
    """Open the fixed root-owned policy without following any ancestor."""

    _require(
        all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")),
        "descriptor-relative no-follow support is unavailable",
    )
    path = FIXED_PRODUCTION_TARGET_POLICY_PATH
    _require(path.is_absolute(), "fixed production target policy path differs")
    parts = path.parts[1:]
    _require(
        len(parts) >= 2 and all(part not in {"", ".", ".."} for part in parts),
        "fixed production target policy components differ",
    )
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    current = os.open("/", directory_flags)
    opened = [current]
    try:
        for part in parts[:-1]:
            before = os.stat(part, dir_fd=current, follow_symlinks=False)
            _require(
                stat.S_ISDIR(before.st_mode)
                and not stat.S_ISLNK(before.st_mode)
                and before.st_uid == 0
                and not (stat.S_IMODE(before.st_mode) & 0o022),
                "fixed production target policy ancestor differs",
            )
            following = os.open(part, directory_flags, dir_fd=current)
            opened.append(following)
            after = os.stat(part, dir_fd=current, follow_symlinks=False)
            opened_info = os.fstat(following)
            _require(
                _directory_tuple(before)
                == _directory_tuple(after)
                == _directory_tuple(opened_info),
                "fixed production target policy ancestor identity drifted",
            )
            current = following
        leaf = parts[-1]
        named_before = os.stat(leaf, dir_fd=current, follow_symlinks=False)
        descriptor = os.open(
            leaf,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=current,
        )
        try:
            opened_info = os.fstat(descriptor)
            named_after = os.stat(leaf, dir_fd=current, follow_symlinks=False)
            _require(
                _regular_tuple(named_before)
                == _regular_tuple(opened_info)
                == _regular_tuple(named_after),
                "fixed production target policy leaf identity drifted",
            )
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        for directory in reversed(opened):
            try:
                os.close(directory)
            except OSError:
                pass


def _build_reviewed_target_policy_for_tests(*, target_root: str, review_id: str) -> dict[str, Any]:
    """Build an offline fixture; production must load separately reviewed bytes."""
    root = _canonical_absolute_directory(target_root, "target root")
    _require(
        type(review_id) is str
        and re.fullmatch(r"local-fetch-target-review-[a-f0-9]{64}", review_id) is not None,
        "target-root review id differs",
    )
    document = {
        "schema": POLICY_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "backend_kind": BACKEND_KIND,
        "target_root": root,
        "review_id": review_id,
        "review_status": "reviewed",
        "policy": {
            "repo_external_required": True,
            "descriptor_traversal_required": True,
            "no_follow_required": True,
            "owner_derived_unique_leaf": True,
            "caller_path_override_allowed": False,
            "caller_root_override_allowed": False,
            "overwrite_allowed": False,
            "delete_allowed": False,
            "cleanup_allowed": False,
        },
        "authority": {
            "portable_policy": True,
            "authorizes_effect": False,
            "production_integration": False,
            "caller_bytes_can_issue_owner": False,
            "required_production_predecessor": (
                LEGACY_PRODUCTION_TARGET_PREDECESSOR
            ),
        },
        "policy_payload_sha256": "",
    }
    return validate_target_policy(_finalize(document, "policy_payload_sha256"))


def validate_target_policy(value: Any) -> dict[str, Any]:
    policy = copy.deepcopy(_exact(value, {
        "schema", "owner", "owner_version", "backend_kind", "target_root",
        "review_id", "review_status", "policy", "authority",
        "policy_payload_sha256",
    }, "target policy"))
    _require(
        policy["schema"] == POLICY_SCHEMA
        and policy["owner"] == OWNER
        and policy["owner_version"] == OWNER_VERSION
        and policy["backend_kind"] == BACKEND_KIND
        and policy["review_status"] == "reviewed",
        "target policy constants differ",
    )
    _canonical_absolute_directory(policy["target_root"], "target root")
    _require(
        type(policy["review_id"]) is str
        and re.fullmatch(r"local-fetch-target-review-[a-f0-9]{64}", policy["review_id"]) is not None,
        "target policy review id differs",
    )
    expected_rules = {
        "repo_external_required": True,
        "descriptor_traversal_required": True,
        "no_follow_required": True,
        "owner_derived_unique_leaf": True,
        "caller_path_override_allowed": False,
        "caller_root_override_allowed": False,
        "overwrite_allowed": False,
        "delete_allowed": False,
        "cleanup_allowed": False,
    }
    _require(policy["policy"] == expected_rules, "target policy rules differ")
    offline_authority = {
        "portable_policy": True,
        "authorizes_effect": False,
        "production_integration": False,
        "caller_bytes_can_issue_owner": False,
        "required_production_predecessor": (
            LEGACY_PRODUCTION_TARGET_PREDECESSOR
        ),
    }
    production_authority = {
        "portable_policy": True,
        "authorizes_effect": False,
        "production_integration": True,
        "caller_bytes_can_issue_owner": False,
        "fixed_policy_path": str(FIXED_PRODUCTION_TARGET_POLICY_PATH),
        "policy_file_is_authority": False,
        "backend_owner_descriptor_issuance_required": True,
    }
    _require(
        policy["authority"] in (offline_authority, production_authority),
        "target policy authority differs",
    )
    _sha(policy["policy_payload_sha256"], "target policy payload", allow_empty=True)
    projection = copy.deepcopy(policy)
    projection["policy_payload_sha256"] = ""
    _require(hmac.compare_digest(policy["policy_payload_sha256"], digest(projection)), "target policy hash differs")
    return policy


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class LocalFetchTargetCapability:
    project: str
    attempt_id: str
    job_id: str
    w5_receipt_sha256: str
    read_profile_sha256: str
    target_policy_sha256: str
    root_identity_sha256: str
    repo_external_evidence_sha256: str
    leaf_basename_sha256: str
    creator_pid: str
    process_epoch_sha256: str
    nonce_sha256: str
    _registry_key: int
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "LocalFetchTargetCapability":
        raise TypeError("local fetch target capabilities are owner-issued only")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("local fetch target capabilities cannot be subclassed")

    @classmethod
    def _from_owner(cls, *, fields: dict[str, str], registry_key: int, token: object) -> "LocalFetchTargetCapability":
        _assert_owner_binding()
        if cls is not LocalFetchTargetCapability or token is not _CAPABILITY_TOKEN:
            raise DirectLocalFetchMaterializerError("target capability seal differs")
        value = object.__new__(cls)
        for name, item in fields.items():
            object.__setattr__(value, name, item)
        object.__setattr__(value, "_registry_key", registry_key)
        object.__setattr__(value, "_seal", _CAPABILITY_TOKEN)
        return value

    def assert_current(self) -> "LocalFetchTargetCapability":
        _assert_target_current(self)
        return self

    def portable_projection(self) -> dict[str, Any]:
        _assert_target_current(self)
        record = _target_record(self)
        return _target_projection(record)

    def abandon_once(self) -> None:
        """Terminalize unused local authority without deleting any bytes."""

        _abandon_target_once(self)

    def __copy__(self) -> "LocalFetchTargetCapability":
        raise TypeError("local fetch target capabilities are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "LocalFetchTargetCapability":
        del memo
        raise TypeError("local fetch target capabilities are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("local fetch target capabilities are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("local fetch target capabilities are not serializable")


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DirectFetchStreamLease:
    target_binding_sha256: str
    stream_projection_sha256: str
    creator_pid: str
    process_epoch_sha256: str
    nonce_sha256: str
    authorizes_effect: bool
    production_integration: bool
    _registry_key: int
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "DirectFetchStreamLease":
        raise TypeError("direct fetch stream leases are owner-issued only")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("direct fetch stream leases cannot be subclassed")

    @classmethod
    def _from_owner(cls, *, fields: dict[str, Any], registry_key: int, token: object) -> "DirectFetchStreamLease":
        _assert_owner_binding()
        if cls is not DirectFetchStreamLease or token is not _LEASE_TOKEN:
            raise DirectLocalFetchMaterializerError("stream lease seal differs")
        value = object.__new__(cls)
        for name, item in fields.items():
            object.__setattr__(value, name, item)
        object.__setattr__(value, "_registry_key", registry_key)
        object.__setattr__(value, "_seal", _LEASE_TOKEN)
        return value

    def assert_current(self) -> "DirectFetchStreamLease":
        _assert_stream_current(self)
        return self

    def portable_projection(self) -> dict[str, Any]:
        _assert_stream_current(self)
        return copy.deepcopy(_stream_record(self).projection)

    def __copy__(self) -> "DirectFetchStreamLease":
        raise TypeError("direct fetch stream leases are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "DirectFetchStreamLease":
        del memo
        raise TypeError("direct fetch stream leases are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("direct fetch stream leases are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("direct fetch stream leases are not serializable")


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class LocalFetchTargetOwner:
    _registry_key: int
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "LocalFetchTargetOwner":
        raise TypeError("local fetch target owners are module-issued only")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("local fetch target owners cannot be subclassed")

    @classmethod
    def production(cls) -> "LocalFetchTargetOwner":
        """Load only the backend-owned fixed reviewed target policy."""

        _assert_owner_binding()
        descriptor = _open_fixed_production_policy_no_follow()
        try:
            before = os.fstat(descriptor)
            _require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == 0
                and not (stat.S_IMODE(before.st_mode) & 0o022)
                and before.st_nlink == 1
                and 0 < before.st_size <= MAX_PRODUCTION_TARGET_POLICY_BYTES,
                "fixed production target policy identity or mode differs",
            )
            raw = os.read(descriptor, MAX_PRODUCTION_TARGET_POLICY_BYTES + 1)
            _require(
                0 < len(raw) <= MAX_PRODUCTION_TARGET_POLICY_BYTES
                and os.read(descriptor, 1) == b"",
                "fixed production target policy exceeds its byte cap",
            )
            after = os.fstat(descriptor)
            _require(
                _regular_tuple(before) == _regular_tuple(after)
                and before.st_size == after.st_size == len(raw),
                "fixed production target policy identity drifted",
            )
            try:
                policy = validate_target_policy(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DirectLocalFetchMaterializerError(
                    "fixed production target policy is malformed"
                ) from exc
            _require(
                canonical_bytes(policy) == raw
                and policy["authority"]["production_integration"] is True
                and policy["authority"]["fixed_policy_path"]
                == str(FIXED_PRODUCTION_TARGET_POLICY_PATH),
                "fixed production target policy bytes or authority differ",
            )
            return _issue_target_owner_from_policy(policy, production=True)
        finally:
            os.close(descriptor)

    def issue_target_once(self, *, project: str, attempt_id: str, job_id: str, w5_receipt_sha256: str, read_profile_sha256: str) -> LocalFetchTargetCapability:
        _assert_owner_binding()
        state = _owner_state(self)
        with state.lock:
            _require(not state.issued, "local fetch target owner issuance is single-use")
            _binding_fields(project, attempt_id, job_id, w5_receipt_sha256, read_profile_sha256)
            _require(os.getpid() == state.creator_pid and _PROCESS_EPOCH is state.process_epoch, "target owner is fork-revoked")
            _require(_descriptor_identity(state.root_identity.descriptor, "target root") == state.root_identity, "target-root descriptor identity drifted")
            nonce = os.urandom(32)
            nonce_sha = hashlib.sha256(nonce).hexdigest()
            leaf = "direct-fetch-" + hashlib.sha256(canonical_bytes({
                "project": project,
                "attempt_id": attempt_id,
                "job_id": job_id,
                "w5_receipt_sha256": w5_receipt_sha256,
                "read_profile_sha256": read_profile_sha256,
                "target_policy_sha256": state.policy["policy_payload_sha256"],
                "root_identity_sha256": state.root_identity_sha256,
                "pid": str(state.creator_pid),
                "process_epoch_sha256": _PROCESS_EPOCH_SHA256,
                "nonce_sha256": nonce_sha,
            })).hexdigest()[:48]
            fields = {
                "project": project,
                "attempt_id": attempt_id,
                "job_id": job_id,
                "w5_receipt_sha256": w5_receipt_sha256,
                "read_profile_sha256": read_profile_sha256,
                "target_policy_sha256": state.policy["policy_payload_sha256"],
                "root_identity_sha256": state.root_identity_sha256,
                "repo_external_evidence_sha256": state.repo_external_evidence_sha256,
                "leaf_basename_sha256": hashlib.sha256(leaf.encode("ascii")).hexdigest(),
                "creator_pid": str(state.creator_pid),
                "process_epoch_sha256": _PROCESS_EPOCH_SHA256,
                "nonce_sha256": nonce_sha,
            }
            key = id(nonce)
            capability = LocalFetchTargetCapability._from_owner(fields=fields, registry_key=key, token=_CAPABILITY_TOKEN)
            record = _TargetRecord(
                registry_nonce=object(), capability_ref=weakref.ref(capability),
                creator_pid=state.creator_pid, process_epoch=state.process_epoch,
                root_identity=state.root_identity, fields=fields, leaf_basename=leaf,
                production_integration=state.production_integration,
                consumed=False, lock=threading.Lock(),
            )
            with _REGISTRY_LOCK:
                while key in _TARGET_REGISTRY:
                    key += 1
                    object.__setattr__(capability, "_registry_key", key)
                _TARGET_REGISTRY[key] = record
            state.issued = True
            return capability.assert_current()

    def __copy__(self) -> "LocalFetchTargetOwner":
        raise TypeError("local fetch target owners are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "LocalFetchTargetOwner":
        del memo
        raise TypeError("local fetch target owners are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("local fetch target owners are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("local fetch target owners are not serializable")


def _issue_offline_target_owner_for_tests(
    *, target_root: str, review_id: str
) -> LocalFetchTargetOwner:
    """Issue an offline fixture owner; no production root-selection API exists."""
    _assert_owner_binding()
    policy = _build_reviewed_target_policy_for_tests(
        target_root=target_root,
        review_id=review_id,
    )
    policy_bytes = canonical_bytes(policy)
    _require(canonical_bytes(validate_target_policy(json.loads(policy_bytes))) == policy_bytes, "offline target policy bytes differ")
    return _issue_target_owner_from_policy(policy, production=False)


def _issue_target_owner_from_policy(
    policy: dict[str, Any], *, production: bool,
) -> LocalFetchTargetOwner:
    """Common descriptor owner; caller bytes can never enter production."""

    policy = validate_target_policy(policy)
    _require(
        type(production) is bool
        and policy["authority"]["production_integration"] is production,
        "target policy production binding differs",
    )
    target_root = policy["target_root"]
    repository_root = str(Path(__file__).resolve(strict=True).parent.parent)
    common = os.path.commonpath((repository_root, target_root))
    _require(common not in {repository_root, target_root}, "target root must be repo-external and not a repository ancestor")
    parts, component_identities, root_identity = _open_directory_chain_no_follow(target_root)
    root_projection = {
        "schema": "auto-g16-local-fetch-root-identity/1",
        "target_policy_sha256": policy["policy_payload_sha256"],
        "component_count": str(len(parts)),
        "component_names_sha256": digest({"components": list(parts)}),
        "component_identities": [list(item) for item in component_identities],
        "final_identity": list(_directory_tuple(os.fstat(root_identity.descriptor))),
    }
    external = {
        "schema": "auto-g16-local-fetch-repo-external-evidence/1",
        "repository_root_sha256": hashlib.sha256(repository_root.encode("utf-8")).hexdigest(),
        "target_root_sha256": hashlib.sha256(target_root.encode("utf-8")).hexdigest(),
        "neither_contains_other": True,
        "target_root_owner_uid_matches": True,
        "target_root_group_world_writable": False,
    }
    owner_key = id(object())
    state = _OwnerState(
        registry_nonce=object(),
        creator_pid=os.getpid(),
        process_epoch=_PROCESS_EPOCH,
        policy=policy,
        root_identity=root_identity,
        root_identity_sha256=digest(root_projection),
        repo_external_evidence_sha256=digest(external),
        production_integration=production,
        issued=False,
        lock=threading.Lock(),
    )
    with _REGISTRY_LOCK:
        while owner_key in _OWNER_REGISTRY:
            owner_key += 1
        value = object.__new__(LocalFetchTargetOwner)
        object.__setattr__(value, "_registry_key", owner_key)
        object.__setattr__(value, "_seal", _OWNER_TOKEN)
        _OWNER_REGISTRY[owner_key] = (weakref.ref(value), state)
    return value


@dataclass(slots=True)
class _OwnerState:
    registry_nonce: object
    creator_pid: int
    process_epoch: object
    policy: dict[str, Any]
    root_identity: _DescriptorIdentity
    root_identity_sha256: str
    repo_external_evidence_sha256: str
    production_integration: bool
    issued: bool
    lock: Any


@dataclass(slots=True)
class _TargetRecord:
    registry_nonce: object
    capability_ref: weakref.ReferenceType[Any]
    creator_pid: int
    process_epoch: object
    root_identity: _DescriptorIdentity
    fields: dict[str, str]
    leaf_basename: str
    production_integration: bool
    consumed: bool
    lock: Any


@dataclass(frozen=True, slots=True)
class _SyntheticFileRecord:
    basename: str
    chunks: tuple[bytes, ...]
    declared_size_bytes: str
    declared_sha256: str
    disconnect_after_chunks: int | None = None


@dataclass(frozen=True, slots=True)
class _ClosedFileRecord:
    """Exact sequential reader binding; bytes are pulled lazily by sole owner."""

    basename: str
    reader: object
    declared_size_bytes: str
    declared_sha256: str


@dataclass(slots=True)
class _StreamRecord:
    registry_nonce: object
    lease_ref: weakref.ReferenceType[Any]
    creator_pid: int
    process_epoch: object
    target_binding_sha256: str
    projection: dict[str, Any]
    files: tuple[_SyntheticFileRecord | _ClosedFileRecord, ...]
    consumed: bool
    lock: Any


_OWNER_REGISTRY: dict[int, tuple[weakref.ReferenceType[Any], _OwnerState]] = {}


def _owner_state(owner: LocalFetchTargetOwner) -> _OwnerState:
    _require(type(owner) is LocalFetchTargetOwner and owner._seal is _OWNER_TOKEN, "exact target owner is required")
    with _REGISTRY_LOCK:
        pair = _OWNER_REGISTRY.get(owner._registry_key)
    _require(pair is not None and pair[0]() is owner, "target owner private registry differs")
    return pair[1]


def _binding_fields(project: Any, attempt_id: Any, job_id: Any, w5_receipt_sha256: Any, read_profile_sha256: Any) -> dict[str, str]:
    _require(type(project) is str and PROJECT_RE.fullmatch(project) is not None, "project differs")
    _require(type(attempt_id) is str and ATTEMPT_RE.fullmatch(attempt_id) is not None, "attempt id differs")
    _require(type(job_id) is str and JOB_RE.fullmatch(job_id) is not None, "job id differs")
    _sha(w5_receipt_sha256, "W5 receipt")
    _sha(read_profile_sha256, "read profile")
    return {
        "project": project, "attempt_id": attempt_id, "job_id": job_id,
        "w5_receipt_sha256": w5_receipt_sha256,
        "read_profile_sha256": read_profile_sha256,
    }


def _target_record(capability: LocalFetchTargetCapability) -> _TargetRecord:
    _require(type(capability) is LocalFetchTargetCapability and capability._seal is _CAPABILITY_TOKEN, "exact local fetch target capability is required")
    with _REGISTRY_LOCK:
        record = _TARGET_REGISTRY.get(capability._registry_key)
    _require(record is not None and record.capability_ref() is capability, "target capability private registry differs")
    return record


def _target_binding_sha256(fields: dict[str, str]) -> str:
    return digest({"schema": "auto-g16-local-fetch-target-binding/1", **fields})


def _target_projection(record: _TargetRecord) -> dict[str, Any]:
    return {
        "schema": "auto-g16-local-fetch-target-capability-projection/1",
        "binding": copy.deepcopy(record.fields),
        "target_binding_sha256": _target_binding_sha256(record.fields),
        "leaf_basename_sha256": record.fields["leaf_basename_sha256"],
        "descriptor_relative_required": True,
        "single_use": True,
        "portable_projection": True,
        "authorizes_effect": False,
        "production_integration": record.production_integration,
    }


def _assert_target_current(capability: LocalFetchTargetCapability) -> None:
    _assert_owner_binding()
    record = _target_record(capability)
    with record.lock:
        _require(not record.consumed, "target capability already consumed")
        _require(os.getpid() == record.creator_pid and _PROCESS_EPOCH is record.process_epoch, "target capability is fork-revoked")
        _require(record.fields == {name: getattr(capability, name) for name in record.fields}, "target capability fields drifted")
        _require(_descriptor_identity(record.root_identity.descriptor, "target root") == record.root_identity, "target-root descriptor identity drifted")


def _abandon_target_once(capability: LocalFetchTargetCapability) -> None:
    _assert_owner_binding()
    record = _target_record(capability)
    with record.lock:
        _require(not record.consumed, "target capability already consumed")
        record.consumed = True
    with _REGISTRY_LOCK:
        _require(
            _TARGET_REGISTRY.get(capability._registry_key) is record,
            "target capability abandon raced",
        )
        del _TARGET_REGISTRY[capability._registry_key]
    _close_if_same(record.root_identity)


def _stream_record(lease: DirectFetchStreamLease) -> _StreamRecord:
    _require(type(lease) is DirectFetchStreamLease and lease._seal is _LEASE_TOKEN, "exact direct fetch stream lease is required")
    with _REGISTRY_LOCK:
        record = _STREAM_REGISTRY.get(lease._registry_key)
    _require(record is not None and record.lease_ref() is lease, "stream lease private registry differs")
    return record


def _assert_stream_current(lease: DirectFetchStreamLease) -> None:
    _assert_owner_binding()
    record = _stream_record(lease)
    with record.lock:
        _require(not record.consumed, "stream lease already consumed")
        _require(os.getpid() == record.creator_pid and _PROCESS_EPOCH is record.process_epoch, "stream lease is fork-revoked")
        _require(
            lease.target_binding_sha256 == record.target_binding_sha256
            and lease.stream_projection_sha256 == record.projection["stream_projection_sha256"]
            and lease.creator_pid == str(record.creator_pid)
            and lease.process_epoch_sha256 == _PROCESS_EPOCH_SHA256
            and lease.authorizes_effect is False
            and lease.production_integration
            is record.projection["production_integration"],
            "stream lease fields drifted",
        )
        closed = tuple(
            item for item in record.files if type(item) is _ClosedFileRecord
        )
        if closed:
            _require(
                len(closed) == len(record.files)
                and all(item.reader is closed[0].reader for item in closed),
                "closed fetch reader binding differs",
            )
            module = sys.modules.get("direct_fetch_acquisition")
            assert_reader = getattr(
                module, "_assert_materializer_reader_current", None,
            )
            _require(
                callable(assert_reader),
                "canonical closed fetch reader assertion differs",
            )
            assert_reader(closed[0].reader)


def _synthetic_record_for_tests(basename: str, raw: bytes, *, declared_size_bytes: str | None = None, declared_sha256: str | None = None, chunks: tuple[bytes, ...] | None = None, disconnect_after_chunks: int | None = None) -> _SyntheticFileRecord:
    _require(type(raw) is bytes, "synthetic bytes differ")
    actual_chunks = chunks if chunks is not None else tuple(
        raw[index:index + CHUNK_SIZE_BYTES] for index in range(0, len(raw), CHUNK_SIZE_BYTES)
    )
    return _SyntheticFileRecord(
        basename=basename,
        chunks=actual_chunks,
        declared_size_bytes=str(len(raw)) if declared_size_bytes is None else declared_size_bytes,
        declared_sha256=hashlib.sha256(raw).hexdigest() if declared_sha256 is None else declared_sha256,
        disconnect_after_chunks=disconnect_after_chunks,
    )


def issue_offline_synthetic_stream_lease_once(target_capability: LocalFetchTargetCapability, payloads: tuple[bytes, ...]) -> DirectFetchStreamLease:
    """Issue the only current test lease; this is explicitly not production T3."""
    _assert_target_current(target_capability)
    _require(type(payloads) is tuple and len(payloads) == len(ARTIFACT_SPECS) and all(type(item) is bytes for item in payloads), "offline synthetic payloads must be an exact five-byte tuple")
    records = tuple(
        _synthetic_record_for_tests(name, raw)
        for (name, _cap), raw in zip(ARTIFACT_SPECS, payloads, strict=True)
    )
    return _issue_synthetic_stream_records_for_tests_once(target_capability, records)


def _issue_synthetic_stream_records_for_tests_once(target_capability: LocalFetchTargetCapability, records: tuple[_SyntheticFileRecord, ...]) -> DirectFetchStreamLease:
    _assert_target_current(target_capability)
    _require(type(records) is tuple and all(type(item) is _SyntheticFileRecord for item in records), "synthetic stream records differ")
    target = _target_record(target_capability)
    target_binding = _target_binding_sha256(target.fields)
    file_projection = [
        {"basename": item.basename, "order": str(index), "size_bytes": item.declared_size_bytes, "sha256": item.declared_sha256}
        for index, item in enumerate(records, 1)
    ]
    projection = {
        "schema": STREAM_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "backend_kind": BACKEND_KIND,
        "stream_mode": STREAM_MODE,
        "target_binding_sha256": target_binding,
        "files": file_projection,
        "file_count": str(len(records)),
        "total_size_bytes": str(sum(int(item.declared_size_bytes) for item in records if type(item.declared_size_bytes) is str and item.declared_size_bytes.isdecimal())),
        "chunk_size_bytes": str(CHUNK_SIZE_BYTES),
        "portable_projection": True,
        "authorizes_effect": False,
        "production_integration": False,
        "required_production_successor": PRODUCTION_SUCCESSOR,
        "stream_projection_sha256": "",
    }
    projection = _finalize(projection, "stream_projection_sha256")
    nonce = os.urandom(32)
    key = id(nonce)
    fields = {
        "target_binding_sha256": target_binding,
        "stream_projection_sha256": projection["stream_projection_sha256"],
        "creator_pid": str(os.getpid()),
        "process_epoch_sha256": _PROCESS_EPOCH_SHA256,
        "nonce_sha256": hashlib.sha256(nonce).hexdigest(),
        "authorizes_effect": False,
        "production_integration": False,
    }
    lease = DirectFetchStreamLease._from_owner(fields=fields, registry_key=key, token=_LEASE_TOKEN)
    record = _StreamRecord(
        registry_nonce=object(), lease_ref=weakref.ref(lease), creator_pid=os.getpid(),
        process_epoch=_PROCESS_EPOCH, target_binding_sha256=target_binding,
        projection=projection, files=records, consumed=False, lock=threading.Lock(),
    )
    with _REGISTRY_LOCK:
        while key in _STREAM_REGISTRY:
            key += 1
            object.__setattr__(lease, "_registry_key", key)
        _STREAM_REGISTRY[key] = record
    return lease.assert_current()


def issue_closed_fetch_stream_lease_once(
    target_capability: LocalFetchTargetCapability,
    acquisition_capability: object,
) -> DirectFetchStreamLease:
    """Consume one exact offline or terminal-grant acquisition into T4."""
    _assert_target_current(target_capability)
    module = sys.modules.get("direct_fetch_acquisition")
    expected_path = Path(__file__).resolve().with_name("direct_fetch_acquisition.py")
    capability_type = getattr(module, "ClosedDirectFetchStreamCapability", None)
    reader_type = getattr(module, "ClosedDirectFetchReaderCapability", None)
    consume = getattr(module, "_consume_for_materializer_once", None)
    validate_source = getattr(module, "validate_closed_stream_projection", None)
    assert_binding = getattr(module, "_assert_module_binding", None)
    _require(
        type(module) is types.ModuleType
        and Path(getattr(module, "__file__", "")).resolve() == expected_path
        and type(capability_type) is type and type(reader_type) is type
        and type(acquisition_capability) is capability_type
        and callable(consume) and callable(validate_source)
        and callable(assert_binding),
        "canonical closed fetch acquisition successor differs",
    )
    assert_binding()
    target_record = _target_record(target_capability)
    target_binding = _target_binding_sha256(target_record.fields)
    try:
        source_projection, reader = consume(
            acquisition_capability, target_binding,
        )
    except BaseException:
        try:
            acquisition_capability.abandon_once()
        except BaseException:
            pass
        raise
    try:
        return _issue_closed_fetch_stream_lease_from_reader_once(
            target_record,
            target_binding,
            source_projection,
            reader,
            reader_type,
            validate_source,
            module,
        )
    except BaseException:
        try:
            reader.abandon_once()
        except BaseException:
            pass
        raise


def _issue_closed_fetch_stream_lease_from_reader_once(
    target_record: _TargetRecord,
    target_binding: str,
    source_projection: object,
    reader: object,
    reader_type: type,
    validate_source: Any,
    module: types.ModuleType,
) -> DirectFetchStreamLease:
    """Validate and commit one already-transferred exact reader."""

    source_projection = validate_source(source_projection)
    _require(
        type(source_projection) is dict
        and source_projection.get("target_binding_sha256") == target_binding
        and source_projection.get("production_integration") is None,
        "closed fetch acquisition projection differs",
    )
    source_authority = source_projection.get("authority")
    offline_authority = {
        "authorizes_effect": False,
        "portable_projection_authorizes_stream": False,
        "remote_fetch_acquired": True,
        "closed_stream_owner": True,
        "production_integration": False,
        "required_production_predecessor": CLOSED_PRODUCTION_SUCCESSOR,
        "qsub_calls": "0",
        "qdel_calls": "0",
        "automatic_retry": False,
        "single_use": True,
    }
    production_authority = {
        **offline_authority,
        "production_integration": True,
        "required_production_predecessor": (
            "terminal_fetch_grant_exact_controller_join"
        ),
    }
    production = source_authority == production_authority
    _require(
        source_authority in (offline_authority, production_authority)
        and target_record.production_integration is production,
        "closed fetch acquisition authority differs",
    )
    _require(
        type(reader) is reader_type,
        "exact closed fetch reader capability is required",
    )
    assert_reader = getattr(module, "_assert_materializer_reader_current", None)
    _require(callable(assert_reader), "closed fetch reader assertion differs")
    assert_reader(reader)
    records: list[_ClosedFileRecord] = []
    file_projection: list[dict[str, str]] = []
    for index, ((name, cap), item) in enumerate(zip(
        ARTIFACT_SPECS, source_projection["files"], strict=True,
    ), 1):
        _require(
            item["basename"] == name
            and item["order"] == str(index),
            "closed fetch file order differs",
        )
        _decimal(
            item["size_bytes"],
            f"{name} closed fetch size",
            maximum=cap,
        )
        _sha(item["sha256"], f"{name} closed fetch hash", allow_empty=True)
        records.append(_ClosedFileRecord(
            basename=name,
            reader=reader,
            declared_size_bytes=item["size_bytes"],
            declared_sha256=item["sha256"],
        ))
        file_projection.append({
            "basename": name,
            "order": str(index),
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        })
    projection = {
        "schema": STREAM_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "backend_kind": BACKEND_KIND,
        "stream_mode": (
            CLOSED_STREAM_MODE if production else LEGACY_CLOSED_STREAM_MODE
        ),
        "target_binding_sha256": target_binding,
        "files": file_projection,
        "file_count": "5",
        "total_size_bytes": str(
            sum(int(item.declared_size_bytes, 10) for item in records)
        ),
        "chunk_size_bytes": str(CHUNK_SIZE_BYTES),
        "portable_projection": True,
        "authorizes_effect": False,
        "production_integration": production,
        "required_production_successor": CLOSED_PRODUCTION_SUCCESSOR,
        "source_stream_projection_sha256": source_projection["stream_projection_sha256"],
        "source_acquisition_result_payload_sha256": source_projection["acquisition_result_payload_sha256"],
        "source_bundle_commitment_sha256": source_projection[
            "bundle_commitment_sha256"
        ],
        "source_lineage_id": source_projection["lineage_id"],
        "stream_projection_sha256": "",
    }
    projection = _finalize(projection, "stream_projection_sha256")
    nonce = os.urandom(32)
    key = id(nonce)
    fields = {
        "target_binding_sha256": target_binding,
        "stream_projection_sha256": projection["stream_projection_sha256"],
        "creator_pid": str(os.getpid()),
        "process_epoch_sha256": _PROCESS_EPOCH_SHA256,
        "nonce_sha256": hashlib.sha256(nonce).hexdigest(),
        "authorizes_effect": False,
        "production_integration": production,
    }
    lease = DirectFetchStreamLease._from_owner(fields=fields, registry_key=key, token=_LEASE_TOKEN)
    record = _StreamRecord(
        registry_nonce=object(), lease_ref=weakref.ref(lease), creator_pid=os.getpid(),
        process_epoch=_PROCESS_EPOCH, target_binding_sha256=target_binding,
        projection=projection, files=tuple(records), consumed=False, lock=threading.Lock(),
    )
    with _REGISTRY_LOCK:
        while key in _STREAM_REGISTRY:
            key += 1
            object.__setattr__(lease, "_registry_key", key)
        _STREAM_REGISTRY[key] = record
    return lease.assert_current()


def _validate_stream_projection(projection: Any) -> dict[str, Any]:
    _require(type(projection) is dict, "stream projection fields differ")
    closed = projection.get("stream_mode") in {
        LEGACY_CLOSED_STREAM_MODE, CLOSED_STREAM_MODE,
    }
    fields = {
        "schema", "owner", "owner_version", "backend_kind", "stream_mode",
        "target_binding_sha256", "files", "file_count", "total_size_bytes",
        "chunk_size_bytes", "portable_projection", "authorizes_effect",
        "production_integration", "required_production_successor",
        "stream_projection_sha256",
    }
    if closed:
        fields |= {
            "source_stream_projection_sha256",
            "source_acquisition_result_payload_sha256",
            "source_bundle_commitment_sha256", "source_lineage_id",
        }
    value = copy.deepcopy(_exact(projection, fields, "stream projection"))
    _require(
        value["schema"] == STREAM_SCHEMA and value["owner"] == OWNER
        and value["owner_version"] == OWNER_VERSION and value["backend_kind"] == BACKEND_KIND
        and value["stream_mode"] in {
            STREAM_MODE, LEGACY_CLOSED_STREAM_MODE, CLOSED_STREAM_MODE,
        }
        and value["portable_projection"] is True
        and value["authorizes_effect"] is False
        and type(value["production_integration"]) is bool
        and value["production_integration"]
        == (value["stream_mode"] == CLOSED_STREAM_MODE)
        and value["required_production_successor"]
        == (CLOSED_PRODUCTION_SUCCESSOR if closed else PRODUCTION_SUCCESSOR),
        "stream projection constants differ",
    )
    if closed:
        for field in (
            "source_stream_projection_sha256",
            "source_acquisition_result_payload_sha256",
            "source_bundle_commitment_sha256",
        ):
            _sha(value[field], f"stream {field}")
        _require(
            type(value["source_lineage_id"]) is str
            and re.fullmatch(r"direct-submitted-job-read-[a-f0-9]{64}", value["source_lineage_id"]) is not None,
            "stream source lineage differs",
        )
    _sha(value["target_binding_sha256"], "stream target binding")
    _require(value["chunk_size_bytes"] == str(CHUNK_SIZE_BYTES), "stream chunk cap differs")
    _require(value["file_count"] == "5" and type(value["files"]) is list and len(value["files"]) == 5, "stream exact-five topology differs")
    total = 0
    for index, ((expected_name, cap), item) in enumerate(zip(ARTIFACT_SPECS, value["files"], strict=True), 1):
        _exact(item, {"basename", "order", "size_bytes", "sha256"}, "stream file")
        _require(item["basename"] == expected_name and item["order"] == str(index), "stream basename or order differs")
        total += _decimal(item["size_bytes"], f"{expected_name} size", maximum=cap)
        _sha(item["sha256"], f"{expected_name} hash", allow_empty=True)
    _require(_decimal(value["total_size_bytes"], "stream total", maximum=TOTAL_CAP_BYTES) == total, "stream total is not the exact five-file sum")
    _sha(value["stream_projection_sha256"], "stream projection hash")
    unhashed = copy.deepcopy(value)
    unhashed["stream_projection_sha256"] = ""
    _require(hmac.compare_digest(value["stream_projection_sha256"], digest(unhashed)), "stream projection hash differs")
    return value


class _TargetAccess(NamedTuple):
    root_identity: _DescriptorIdentity
    fields: dict[str, str]
    leaf_basename: str
    production_integration: bool


def _consume_target_once(capability: LocalFetchTargetCapability) -> _TargetAccess:
    record = _target_record(capability)
    with record.lock:
        _require(not record.consumed, "target capability already consumed")
        record.consumed = True
        _require(os.getpid() == record.creator_pid and _PROCESS_EPOCH is record.process_epoch, "target capability is fork-revoked")
        _require(record.fields == {name: getattr(capability, name) for name in record.fields}, "target capability fields drifted")
        _require(_descriptor_identity(record.root_identity.descriptor, "target root") == record.root_identity, "target-root descriptor identity drifted")
        return _TargetAccess(
            record.root_identity,
            copy.deepcopy(record.fields),
            record.leaf_basename,
            record.production_integration,
        )


def _consume_stream_once(
    lease: DirectFetchStreamLease,
) -> tuple[
    dict[str, Any],
    tuple[_SyntheticFileRecord | _ClosedFileRecord, ...],
]:
    record = _stream_record(lease)
    with record.lock:
        _require(not record.consumed, "stream lease already consumed")
        record.consumed = True
        _require(os.getpid() == record.creator_pid and _PROCESS_EPOCH is record.process_epoch, "stream lease is fork-revoked")
        _require(lease.target_binding_sha256 == record.target_binding_sha256, "stream target binding drifted")
        projection = copy.deepcopy(record.projection)
        files = record.files
    with _REGISTRY_LOCK:
        _require(
            _STREAM_REGISTRY.get(lease._registry_key) is record,
            "stream lease consume raced",
        )
        del _STREAM_REGISTRY[lease._registry_key]
    return projection, files


def _write_full(descriptor: int, chunk: bytes | memoryview) -> None:
    _require(
        type(chunk) in {bytes, memoryview}
        and 0 < len(chunk) <= CHUNK_SIZE_BYTES,
        "stream chunk size differs",
    )
    view = chunk if type(chunk) is memoryview else memoryview(chunk)
    offset = 0
    while offset < len(view):
        try:
            written = os.write(descriptor, view[offset:])
        except OSError as exc:
            raise DirectLocalFetchMaterializerError(f"artifact write failed: {exc}") from exc
        _require(type(written) is int and written > 0, "artifact write made no progress")
        offset += written


def _same_fd_size_hash(descriptor: int) -> tuple[int, str]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        hasher = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, CHUNK_SIZE_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
        return size, hasher.hexdigest()
    except OSError as exc:
        raise DirectLocalFetchMaterializerError(
            f"same-FD artifact verification failed: {exc}"
        ) from exc


def _verify_file_identity(leaf_fd: int, basename: str, descriptor: int, initial: tuple[int, ...], expected_size: int) -> None:
    current = os.fstat(descriptor)
    named = os.stat(basename, dir_fd=leaf_fd, follow_symlinks=False)
    expected = (
        initial[0], initial[1], os.geteuid(), initial[3], stat.S_IFREG, 0o600, 1,
    )
    _require(
        _regular_tuple(current) == expected
        and _regular_tuple(named) == expected
        and current.st_size == named.st_size == expected_size
        and not stat.S_ISLNK(named.st_mode),
        "materialized file identity, type, mode, link count, or size drifted",
    )


def _materialize_file(
    leaf_fd: int,
    record: _SyntheticFileRecord | _ClosedFileRecord,
    declared: dict[str, Any],
) -> dict[str, str]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(record.basename, flags, 0o600, dir_fd=leaf_fd)
        initial_info = os.fstat(descriptor)
        initial = _regular_tuple(initial_info)
        _require(
            stat.S_ISREG(initial_info.st_mode) and stat.S_IMODE(initial_info.st_mode) == 0o600
            and initial_info.st_nlink == 1 and initial_info.st_size == 0,
            "new artifact is not an exclusive private regular file",
        )
        hasher = hashlib.sha256()
        size = 0
        if type(record) is _ClosedFileRecord:
            def closed_chunks():
                remaining = int(record.declared_size_bytes, 10)
                module = sys.modules.get("direct_fetch_acquisition")
                read_once = getattr(module, "_read_for_materializer_once", None)
                _require(
                    callable(read_once),
                    "canonical closed fetch reader differs",
                )
                while remaining:
                    chunk = read_once(
                        record.reader,
                        record.basename,
                        min(CHUNK_SIZE_BYTES, remaining),
                    )
                    _require(
                        type(chunk) is bytes and bool(chunk)
                        and len(chunk) <= remaining,
                        "closed fetch reader chunk differs",
                    )
                    yield chunk
                    remaining -= len(chunk)

            chunks = closed_chunks()
            disconnect_after_chunks = None
        else:
            chunks = iter(record.chunks)
            disconnect_after_chunks = record.disconnect_after_chunks
        chunk_count = 0
        for index, chunk in enumerate(chunks):
            if disconnect_after_chunks is not None and index == disconnect_after_chunks:
                raise DirectLocalFetchMaterializerError("synthetic stream disconnected")
            _require(
                type(chunk) in {bytes, memoryview}
                and 0 < len(chunk) <= CHUNK_SIZE_BYTES,
                "stream chunk size differs",
            )
            _require(
                size + len(chunk) <= ARTIFACT_CAPS[record.basename],
                "artifact exceeded its fixed cap",
            )
            _write_full(descriptor, chunk)
            hasher.update(chunk)
            size += len(chunk)
            chunk_count += 1
        if disconnect_after_chunks is not None and disconnect_after_chunks == chunk_count:
            raise DirectLocalFetchMaterializerError("synthetic stream disconnected")
        expected_size = _decimal(declared["size_bytes"], f"{record.basename} declared size", maximum=ARTIFACT_CAPS[record.basename])
        _require(size == expected_size, "artifact stream size differs")
        _require(hmac.compare_digest(hasher.hexdigest(), declared["sha256"]), "artifact stream hash differs")
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise DirectLocalFetchMaterializerError(f"artifact fsync failed: {exc}") from exc
        same_fd_size, same_fd_sha256 = _same_fd_size_hash(descriptor)
        _require(
            same_fd_size == expected_size
            and hmac.compare_digest(same_fd_sha256, declared["sha256"]),
            "same-FD artifact size or hash differs",
        )
        _verify_file_identity(leaf_fd, record.basename, descriptor, initial, expected_size)
        return {
            "basename": record.basename,
            "size_bytes": str(same_fd_size),
            "sha256": same_fd_sha256,
        }
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _manifest_document(
    access: _TargetAccess,
    stream: dict[str, Any],
    files: list[dict[str, str]],
    terminal_bundle_sha256: str | None,
) -> dict[str, Any]:
    total = sum(int(item["size_bytes"]) for item in files)
    production = (
        access.production_integration is True
        and stream["production_integration"] is True
    )
    stream_document = {
        "stream_mode": stream["stream_mode"],
        "stream_projection_sha256": stream["stream_projection_sha256"],
        "chunk_size_bytes": str(CHUNK_SIZE_BYTES),
    }
    if stream["stream_mode"] == CLOSED_STREAM_MODE:
        _sha(terminal_bundle_sha256, "terminal bundle")
        stream_document.update({
            "source_bundle_commitment_sha256": stream[
                "source_bundle_commitment_sha256"
            ],
            "terminal_bundle_sha256": terminal_bundle_sha256,
        })
    elif stream["stream_mode"] == LEGACY_CLOSED_STREAM_MODE:
        _sha(terminal_bundle_sha256, "legacy closed terminal bundle")
    else:
        _require(
            terminal_bundle_sha256 is None,
            "offline stream cannot claim a terminal remote bundle",
        )
    document = {
        "schema": MANIFEST_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "backend_kind": BACKEND_KIND,
        "materialization": {
            "mode": MATERIALIZATION_MODE,
            "status": "completed",
            "creator_pid": access.fields["creator_pid"],
            "process_epoch_sha256": access.fields["process_epoch_sha256"],
            "nonce_sha256": access.fields["nonce_sha256"],
        },
        "binding": {
            "project": access.fields["project"],
            "attempt_id": access.fields["attempt_id"],
            "job_id": access.fields["job_id"],
            "w5_receipt_sha256": access.fields["w5_receipt_sha256"],
            "read_profile_sha256": access.fields["read_profile_sha256"],
            "target_binding_sha256": _target_binding_sha256(access.fields),
        },
        "target": {
            "target_policy_sha256": access.fields["target_policy_sha256"],
            "root_identity_sha256": access.fields["root_identity_sha256"],
            "repo_external_evidence_sha256": access.fields["repo_external_evidence_sha256"],
            "leaf_basename": access.leaf_basename,
            "leaf_basename_sha256": access.fields["leaf_basename_sha256"],
        },
        "stream": stream_document,
        "files": [
            {**item, "order": str(index), "cap_bytes": str(ARTIFACT_CAPS[item["basename"]])}
            for index, item in enumerate(files, 1)
        ],
        "totals": {
            "file_count": "5",
            "total_size_bytes": str(total),
            "total_cap_bytes": str(TOTAL_CAP_BYTES),
        },
        "safety": {
            "bytes_safely_materialized": True,
            "descriptor_relative": True,
            "no_clobber": True,
            "files_fsynced": True,
            "directory_fsynced_before_manifest": True,
            "manifest_written_last_exclusive": True,
            "partial_retained_on_failure": True,
            "overwrite_allowed": False,
            "delete_allowed": False,
            "cleanup_allowed": False,
            "rename_replace_allowed": False,
            "resume_allowed": False,
            "automatic_retry": False,
        },
        "authority": {
            "portable_manifest": True,
            "authorizes_effect": False,
            "scientific_acceptance": False,
            "remote_fetch_performed": production,
            "scheduler_inspection_performed": production,
        },
        "integration": {
            "production_integration": production,
            "required_production_successor": stream["required_production_successor"],
            "required_production_target_predecessor": (
                PRODUCTION_TARGET_PREDECESSOR
                if production
                else LEGACY_PRODUCTION_TARGET_PREDECESSOR
            ),
            "portable_bytes_can_reconstruct_lease": False,
        },
        "manifest_payload_sha256": "",
    }
    return _finalize(document, "manifest_payload_sha256")


def validate_manifest(value: Any) -> dict[str, Any]:
    result = copy.deepcopy(_exact(value, {
        "schema", "owner", "owner_version", "backend_kind", "materialization",
        "binding", "target", "stream", "files", "totals", "safety", "authority",
        "integration", "manifest_payload_sha256",
    }, "direct fetch manifest"))
    _require(result["schema"] == MANIFEST_SCHEMA and result["owner"] == OWNER and result["owner_version"] == OWNER_VERSION and result["backend_kind"] == BACKEND_KIND, "manifest constants differ")
    materialization = _exact(result["materialization"], {"mode", "status", "creator_pid", "process_epoch_sha256", "nonce_sha256"}, "manifest materialization")
    _require(materialization["mode"] == MATERIALIZATION_MODE and materialization["status"] == "completed", "manifest materialization differs")
    _require(_decimal(materialization["creator_pid"], "manifest creator pid") > 0, "manifest creator pid must be positive")
    _sha(materialization["process_epoch_sha256"], "manifest process epoch")
    _sha(materialization["nonce_sha256"], "manifest nonce")
    binding = _exact(result["binding"], {"project", "attempt_id", "job_id", "w5_receipt_sha256", "read_profile_sha256", "target_binding_sha256"}, "manifest binding")
    _binding_fields(binding["project"], binding["attempt_id"], binding["job_id"], binding["w5_receipt_sha256"], binding["read_profile_sha256"])
    _sha(binding["target_binding_sha256"], "manifest target binding")
    target = _exact(result["target"], {"target_policy_sha256", "root_identity_sha256", "repo_external_evidence_sha256", "leaf_basename", "leaf_basename_sha256"}, "manifest target")
    for field in ("target_policy_sha256", "root_identity_sha256", "repo_external_evidence_sha256", "leaf_basename_sha256"):
        _sha(target[field], f"manifest {field}")
    _require(type(target["leaf_basename"]) is str and LEAF_RE.fullmatch(target["leaf_basename"]) is not None and hashlib.sha256(target["leaf_basename"].encode("ascii")).hexdigest() == target["leaf_basename_sha256"], "manifest leaf differs")
    manifest_target_fields = {
        "project": binding["project"],
        "attempt_id": binding["attempt_id"],
        "job_id": binding["job_id"],
        "w5_receipt_sha256": binding["w5_receipt_sha256"],
        "read_profile_sha256": binding["read_profile_sha256"],
        "target_policy_sha256": target["target_policy_sha256"],
        "root_identity_sha256": target["root_identity_sha256"],
        "repo_external_evidence_sha256": target["repo_external_evidence_sha256"],
        "leaf_basename_sha256": target["leaf_basename_sha256"],
        "creator_pid": materialization["creator_pid"],
        "process_epoch_sha256": materialization["process_epoch_sha256"],
        "nonce_sha256": materialization["nonce_sha256"],
    }
    _require(
        hmac.compare_digest(
            binding["target_binding_sha256"],
            _target_binding_sha256(manifest_target_fields),
        ),
        "manifest target binding replay differs",
    )
    stream_fields = {
        "stream_mode", "stream_projection_sha256", "chunk_size_bytes",
    }
    if result["stream"].get("stream_mode") == CLOSED_STREAM_MODE:
        stream_fields |= {
            "source_bundle_commitment_sha256", "terminal_bundle_sha256",
        }
    stream = _exact(result["stream"], stream_fields, "manifest stream")
    _require(
        stream["stream_mode"] in {
            STREAM_MODE, LEGACY_CLOSED_STREAM_MODE, CLOSED_STREAM_MODE,
        }
        and stream["chunk_size_bytes"] == str(CHUNK_SIZE_BYTES),
        "manifest stream constants differ",
    )
    _sha(stream["stream_projection_sha256"], "manifest stream projection")
    if stream["stream_mode"] == CLOSED_STREAM_MODE:
        _sha(
            stream["source_bundle_commitment_sha256"],
            "manifest source bundle commitment",
        )
        _sha(stream["terminal_bundle_sha256"], "manifest terminal bundle")
    _require(type(result["files"]) is list and len(result["files"]) == 5, "manifest exact-five files differ")
    total = 0
    for index, ((name, cap), item) in enumerate(zip(ARTIFACT_SPECS, result["files"], strict=True), 1):
        _exact(item, {"basename", "order", "size_bytes", "sha256", "cap_bytes"}, "manifest file")
        _require(item["basename"] == name and item["order"] == str(index) and item["cap_bytes"] == str(cap), "manifest file order or cap differs")
        total += _decimal(item["size_bytes"], f"manifest {name} size", maximum=cap)
        _sha(item["sha256"], f"manifest {name} hash", allow_empty=True)
    totals = _exact(result["totals"], {"file_count", "total_size_bytes", "total_cap_bytes"}, "manifest totals")
    _require(totals["file_count"] == "5" and totals["total_cap_bytes"] == str(TOTAL_CAP_BYTES) and _decimal(totals["total_size_bytes"], "manifest total", maximum=TOTAL_CAP_BYTES) == total, "manifest totals differ")
    _require(result["safety"] == {
        "bytes_safely_materialized": True, "descriptor_relative": True, "no_clobber": True,
        "files_fsynced": True, "directory_fsynced_before_manifest": True,
        "manifest_written_last_exclusive": True, "partial_retained_on_failure": True,
        "overwrite_allowed": False, "delete_allowed": False, "cleanup_allowed": False,
        "rename_replace_allowed": False, "resume_allowed": False, "automatic_retry": False,
    }, "manifest safety differs")
    offline_authority = {
        "portable_manifest": True, "authorizes_effect": False, "scientific_acceptance": False,
        "remote_fetch_performed": False, "scheduler_inspection_performed": False,
    }
    production_authority = {
        **offline_authority,
        "remote_fetch_performed": True,
        "scheduler_inspection_performed": True,
    }
    _require(
        result["authority"] in (offline_authority, production_authority),
        "manifest authority differs",
    )
    expected_successor = (
        CLOSED_PRODUCTION_SUCCESSOR
        if stream["stream_mode"] in {
            LEGACY_CLOSED_STREAM_MODE, CLOSED_STREAM_MODE,
        }
        else PRODUCTION_SUCCESSOR
    )
    production = result["authority"] == production_authority
    _require(
        production == (stream["stream_mode"] == CLOSED_STREAM_MODE),
        "manifest stream and production authority differ",
    )
    _require(result["integration"] == {
        "production_integration": production, "required_production_successor": expected_successor,
        "required_production_target_predecessor": (
            PRODUCTION_TARGET_PREDECESSOR
            if production
            else LEGACY_PRODUCTION_TARGET_PREDECESSOR
        ),
        "portable_bytes_can_reconstruct_lease": False,
    }, "manifest integration differs")
    _sha(result["manifest_payload_sha256"], "manifest payload")
    projection = copy.deepcopy(result)
    projection["manifest_payload_sha256"] = ""
    _require(hmac.compare_digest(result["manifest_payload_sha256"], digest(projection)), "manifest payload hash differs")
    return result


def materialize_direct_fetch_once(target_capability: LocalFetchTargetCapability, stream_lease: DirectFetchStreamLease) -> dict[str, Any]:
    """Consume two exact owner-issued capabilities and create one fixed snapshot."""
    _assert_owner_binding()
    _require(type(target_capability) is LocalFetchTargetCapability, "exact local fetch target capability is required")
    _require(type(stream_lease) is DirectFetchStreamLease, "exact direct fetch stream lease is required")
    target_capability.assert_current()
    stream_lease.assert_current()
    _require(
        stream_lease.production_integration
        is _target_record(target_capability).production_integration,
        "target and stream production integration differ",
    )
    _require(stream_lease.target_binding_sha256 == _target_binding_sha256(_target_record(target_capability).fields), "target and stream binding differ")
    access = _consume_target_once(target_capability)
    root_identity = access.root_identity
    leaf_fd = -1
    records: tuple[_SyntheticFileRecord | _ClosedFileRecord, ...] = ()
    reader_finished = False
    terminal_bundle_sha256: str | None = None
    try:
        stream_projection, records = _consume_stream_once(stream_lease)
        validated_stream = _validate_stream_projection(stream_projection)
        _require(tuple(item.basename for item in records) == ARTIFACT_BASENAMES, "stream record order differs")
        _require(len(records) == 5, "stream must contain exactly five records")
        _require(_descriptor_identity(root_identity.descriptor, "target root") == root_identity, "target-root descriptor identity drifted before mkdir")
        try:
            os.mkdir(access.leaf_basename, mode=0o700, dir_fd=root_identity.descriptor)
        except OSError as exc:
            raise DirectLocalFetchMaterializerError(f"exclusive target leaf creation failed: {exc}") from exc
        created = os.stat(access.leaf_basename, dir_fd=root_identity.descriptor, follow_symlinks=False)
        _require(stat.S_ISDIR(created.st_mode) and not stat.S_ISLNK(created.st_mode) and stat.S_IMODE(created.st_mode) == 0o700, "new target leaf type or mode differs")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        leaf_fd = os.open(access.leaf_basename, directory_flags, dir_fd=root_identity.descriptor)
        opened = os.fstat(leaf_fd)
        named = os.stat(access.leaf_basename, dir_fd=root_identity.descriptor, follow_symlinks=False)
        _require(_directory_tuple(created) == _directory_tuple(opened) == _directory_tuple(named), "target leaf identity drifted during mkdir/open")
        files: list[dict[str, str]] = []
        for record, declared in zip(records, validated_stream["files"], strict=True):
            files.append(_materialize_file(leaf_fd, record, declared))
        closed = tuple(
            record for record in records if type(record) is _ClosedFileRecord
        )
        if closed:
            _require(
                len(closed) == len(records)
                and all(record.reader is closed[0].reader for record in closed),
                "closed fetch reader completion binding differs",
            )
            module = sys.modules.get("direct_fetch_acquisition")
            finish_reader = getattr(
                module, "_finish_for_materializer_once", None,
            )
            _require(
                callable(finish_reader),
                "canonical closed fetch reader finish differs",
            )
            terminal_bundle_sha256 = finish_reader(closed[0].reader)
            _sha(terminal_bundle_sha256, "terminal bundle")
            reader_finished = True
        try:
            os.fsync(leaf_fd)
        except OSError as exc:
            raise DirectLocalFetchMaterializerError(f"target directory fsync failed: {exc}") from exc
        manifest = validate_manifest(
            _manifest_document(
                access, validated_stream, files, terminal_bundle_sha256,
            )
        )
        raw = canonical_bytes(manifest)
        manifest_fd = -1
        try:
            manifest_fd = os.open(
                MANIFEST_BASENAME,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=leaf_fd,
            )
            initial = _regular_tuple(os.fstat(manifest_fd))
            _write_full(manifest_fd, raw)
            os.fsync(manifest_fd)
            same_fd_size, same_fd_sha256 = _same_fd_size_hash(manifest_fd)
            _require(
                same_fd_size == len(raw)
                and hmac.compare_digest(same_fd_sha256, hashlib.sha256(raw).hexdigest()),
                "same-FD manifest size or hash differs",
            )
            _verify_file_identity(leaf_fd, MANIFEST_BASENAME, manifest_fd, initial, len(raw))
        except OSError as exc:
            raise DirectLocalFetchMaterializerError(f"manifest create/write/fsync failed: {exc}") from exc
        finally:
            if manifest_fd >= 0:
                try:
                    os.close(manifest_fd)
                except OSError:
                    pass
        try:
            os.fsync(leaf_fd)
        except OSError as exc:
            raise DirectLocalFetchMaterializerError(f"final target directory fsync failed: {exc}") from exc
        return manifest
    finally:
        if leaf_fd >= 0:
            try:
                os.close(leaf_fd)
            except OSError:
                pass
        closed = tuple(
            record for record in records if type(record) is _ClosedFileRecord
        )
        if closed and not reader_finished:
            module = sys.modules.get("direct_fetch_acquisition")
            abandon_reader = getattr(
                module, "_abandon_materializer_reader_once", None,
            )
            if callable(abandon_reader):
                abandon_reader(closed[0].reader)
        _close_if_same(root_identity)


def _fork_before() -> None:
    _REGISTRY_LOCK.acquire()


def _fork_parent() -> None:
    _REGISTRY_LOCK.release()


def _fork_child() -> None:
    global _REGISTRY_LOCK, _PROCESS_EPOCH, _PROCESS_EPOCH_SHA256
    try:
        for _ref, state in _OWNER_REGISTRY.values():
            _close_if_same(state.root_identity)
        for record in _TARGET_REGISTRY.values():
            _close_if_same(record.root_identity)
        _OWNER_REGISTRY.clear()
        _TARGET_REGISTRY.clear()
        _STREAM_REGISTRY.clear()
    finally:
        _PROCESS_EPOCH = object()
        _PROCESS_EPOCH_SHA256 = hashlib.sha256(f"{os.getpid()}:{id(_PROCESS_EPOCH)}".encode("ascii")).hexdigest()
        _REGISTRY_LOCK = threading.RLock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(before=_fork_before, after_in_parent=_fork_parent, after_in_child=_fork_child)


class _SourceSnapshot(NamedTuple):
    path: str
    identity: tuple[int, int, int, int, int]
    sha256: str


def _source_snapshot() -> _SourceSnapshot:
    path = str(Path(__file__).resolve(strict=True))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    _require(stat.S_ISREG(before.st_mode) and identity == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "owner source identity drifted")
    return _SourceSnapshot(path, identity, hashlib.sha256(b"".join(chunks)).hexdigest())


class _ModuleBinding(NamedTuple):
    module: object
    target_type: type
    lease_type: type
    owner_type: type
    materializer: object
    closed_stream_issuer: object
    source: _SourceSnapshot


_OWNER_BINDING = _ModuleBinding(
    module=sys.modules[__name__],
    target_type=LocalFetchTargetCapability,
    lease_type=DirectFetchStreamLease,
    owner_type=LocalFetchTargetOwner,
    materializer=materialize_direct_fetch_once,
    closed_stream_issuer=issue_closed_fetch_stream_lease_once,
    source=_source_snapshot(),
)


def _assert_owner_binding() -> None:
    binding = _OWNER_BINDING
    _require(
        __name__ == MODULE_NAME
        and sys.modules.get(MODULE_NAME) is binding.module
        and LocalFetchTargetCapability is binding.target_type
        and DirectFetchStreamLease is binding.lease_type
        and LocalFetchTargetOwner is binding.owner_type
        and materialize_direct_fetch_once is binding.materializer
        and issue_closed_fetch_stream_lease_once is binding.closed_stream_issuer
        and _source_snapshot() == binding.source,
        "local fetch owner module/source binding differs",
    )
