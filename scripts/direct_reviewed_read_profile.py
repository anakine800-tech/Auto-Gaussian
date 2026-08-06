#!/usr/bin/env python3
"""Sole backend owner for the exact direct qstat read profile.

Production reads one fixed no-override file.  The controller and server each
issue their own process-local capability from that same reviewed byte identity;
portable bytes or hashes are never authority.  The fake-local factory is
explicitly token-gated and is not reachable from production.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
import threading
import types
import weakref
from pathlib import Path
from typing import Any, NamedTuple


MODULE_NAME = "direct_reviewed_read_profile"
OWNER = "auto-g16-direct-reviewed-read-profile-owner"
OWNER_VERSION = "direct-reviewed-read-profile-owner/1"
CAPABILITY_SCHEMA = "auto-g16-direct-reviewed-read-profile-capability/1"
FIXED_PRODUCTION_READ_PROFILE_PATH = Path("/etc/auto-g16/direct-qstat-read-profile.json")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ZERO_SHA = "0" * 64

_EXECUTED_SOURCE_SHA256 = globals().get("__reviewed_source_sha256__")
if _EXECUTED_SOURCE_SHA256 is None:
    with open(__file__, "rb") as _source_handle:
        _EXECUTED_SOURCE_SHA256 = hashlib.sha256(_source_handle.read()).hexdigest()

_SCRIPTS = str(Path(__file__).resolve().parent)
_INSERTED = _SCRIPTS not in sys.path
if _INSERTED:
    sys.path.insert(0, _SCRIPTS)
try:
    import direct_shared_fixed_ssh_channel as CHANNEL
finally:
    if _INSERTED:
        sys.path.remove(_SCRIPTS)


class DirectReviewedReadProfileError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectReviewedReadProfileError(message)


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
        raise DirectReviewedReadProfileError("value is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and SHA_RE.fullmatch(value) is not None and value != ZERO_SHA,
        f"{label} differs",
    )
    return value


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode), info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _identity_sha(identity: tuple[int, ...]) -> str:
    return digest(
        {"schema": "auto-g16-reviewed-read-profile-file-identity/1", "fields": [str(item) for item in identity]}
    )


def _close_descriptor_quiet(descriptor: int) -> None:
    if type(descriptor) is int and descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _read_descriptor_bytes(descriptor: int, size: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = size
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(descriptor, min(65536, remaining))
        _require(bool(chunk), "fixed reviewed read-profile ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    _require(os.read(descriptor, 1) == b"", "fixed reviewed read-profile grew")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return b"".join(chunks)


def _open_fixed_profile() -> tuple[bytes, str, int, tuple[int, ...]]:
    path = FIXED_PRODUCTION_READ_PROFILE_PATH
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        identity = _file_identity(before)
        named = os.stat(path, follow_symlinks=False)
        _require(
            stat.S_ISREG(before.st_mode)
            and identity == _file_identity(named)
            and before.st_uid == 0
            and before.st_nlink == 1
            and before.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
            and 0 < before.st_size <= CHANNEL.MAX_PROFILE_BYTES,
            "fixed reviewed read-profile file owner, mode, type, or size differs",
        )
        raw = _read_descriptor_bytes(descriptor, before.st_size)
        after = os.fstat(descriptor)
        _require(identity == _file_identity(after), "fixed reviewed read-profile identity drifted")
        return raw, _identity_sha(identity), descriptor, identity
    except BaseException:
        _close_descriptor_quiet(descriptor)
        raise


def _assert_fixed_source_current(
    descriptor: int,
    identity: tuple[int, ...],
    profile_raw: bytes,
) -> None:
    try:
        before = os.fstat(descriptor)
        named = os.stat(FIXED_PRODUCTION_READ_PROFILE_PATH, follow_symlinks=False)
        _require(
            _file_identity(before) == identity == _file_identity(named)
            and _read_descriptor_bytes(descriptor, len(profile_raw)) == profile_raw
            and _file_identity(os.fstat(descriptor)) == identity,
            "fixed reviewed read-profile descriptor, identity, or bytes drifted",
        )
    except OSError as exc:
        raise DirectReviewedReadProfileError(
            "fixed reviewed read-profile descriptor currentness failed"
        ) from exc


class DirectReviewedReadProfileCapability:
    __slots__ = ("capability_id", "_pid", "_epoch", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("reviewed read-profile capabilities are owner-issued only")

    def assert_current(self) -> None:
        _CAP_ASSERT(self, "capability")

    def portable_projection(self) -> dict[str, Any]:
        return copy.deepcopy(json.loads(_CAP_PROJECT(self, "capability").decode("utf-8")))

    def __copy__(self) -> Any:
        raise TypeError("reviewed read-profile capabilities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("reviewed read-profile capabilities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("reviewed read-profile capabilities are not serializable")


class DirectReviewedReadProfileLease:
    __slots__ = ("capability_id", "_pid", "_epoch", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("reviewed read-profile leases are owner-issued only")

    def assert_current(self) -> None:
        _CAP_ASSERT(self, "lease")

    def close_once(self) -> None:
        _CAP_CLOSE(self)

    def __copy__(self) -> Any:
        raise TypeError("reviewed read-profile leases are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("reviewed read-profile leases are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("reviewed read-profile leases are not serializable")


class _CapabilityRecord(NamedTuple):
    kind: str
    pid: int
    epoch: object
    seal: object
    capability_id: str
    projection_raw: bytes
    profile_raw: bytes
    source_descriptor: int
    source_identity: tuple[int, ...] | None
    source_finalizer: object | None


def _build_capability_owner() -> tuple[Any, Any, Any, Any, Any, Any]:
    registry: weakref.WeakKeyDictionary[object, _CapabilityRecord] = weakref.WeakKeyDictionary()
    issued: set[str] = set()
    lock = threading.RLock()
    epoch = object()

    def exact(value: object, kind: str) -> _CapabilityRecord:
        expected = DirectReviewedReadProfileCapability if kind == "capability" else DirectReviewedReadProfileLease
        with lock:
            record = registry.get(value)
            _require(
                type(value) is expected
                and type(record) is _CapabilityRecord
                and record.kind == kind
                and record.pid == os.getpid() == value._pid
                and record.epoch is epoch is value._epoch
                and record.seal is value._seal
                and record.capability_id == value.capability_id,
                f"reviewed read-profile {kind} is foreign, forged, forked, rebound, or terminal",
            )
            if record.source_descriptor >= 0:
                _require(
                    type(record.source_identity) is tuple,
                    "fixed reviewed read-profile source identity differs",
                )
                _assert_fixed_source_current(
                    record.source_descriptor,
                    record.source_identity,
                    record.profile_raw,
                )
            else:
                _require(
                    record.source_identity is None and record.source_finalizer is None,
                    "fake reviewed read-profile source descriptor differs",
                )
            return record

    def issue(
        profile_raw: bytes,
        projection: dict[str, Any],
        source_descriptor: int,
        source_identity: tuple[int, ...] | None,
    ) -> DirectReviewedReadProfileCapability:
        nonlocal epoch
        projection = validate_capability_projection(projection)
        capability_id = projection["capability_id"]
        with lock:
            _require(capability_id not in issued, "duplicate reviewed read-profile capability differs")
            value = object.__new__(DirectReviewedReadProfileCapability)
            value.capability_id = capability_id
            value._pid = os.getpid()
            value._epoch = epoch
            value._seal = object()
            source_finalizer = (
                None
                if source_descriptor < 0
                else weakref.finalize(value, _close_descriptor_quiet, source_descriptor)
            )
            registry[value] = _CapabilityRecord(
                "capability", os.getpid(), epoch, value._seal,
                capability_id, canonical_bytes(projection), bytes(profile_raw),
                source_descriptor, source_identity, source_finalizer,
            )
            issued.add(capability_id)
        exact(value, "capability")
        return value

    def assert_current(value: object, kind: str) -> None:
        exact(value, kind)

    def project(value: object, kind: str) -> bytes:
        return bytes(exact(value, kind).projection_raw)

    def consume(value: DirectReviewedReadProfileCapability) -> tuple[DirectReviewedReadProfileLease, bytes]:
        nonlocal epoch
        record = exact(value, "capability")
        with lock:
            _require(registry.get(value) is record, "reviewed read-profile consume raced")
            del registry[value]
            if record.source_finalizer is not None:
                record.source_finalizer.detach()
            lease = object.__new__(DirectReviewedReadProfileLease)
            lease.capability_id = record.capability_id
            lease._pid = os.getpid()
            lease._epoch = epoch
            lease._seal = object()
            source_finalizer = (
                None
                if record.source_descriptor < 0
                else weakref.finalize(lease, _close_descriptor_quiet, record.source_descriptor)
            )
            registry[lease] = _CapabilityRecord(
                "lease", os.getpid(), epoch, lease._seal,
                record.capability_id, record.projection_raw, record.profile_raw,
                record.source_descriptor, record.source_identity, source_finalizer,
            )
        exact(lease, "lease")
        return lease, bytes(record.profile_raw)

    def close(value: DirectReviewedReadProfileLease) -> None:
        record = exact(value, "lease")
        with lock:
            _require(registry.get(value) is record, "reviewed read-profile close raced")
            del registry[value]
            if record.source_finalizer is not None:
                record.source_finalizer.detach()
            _close_descriptor_quiet(record.source_descriptor)

    def after_fork() -> None:
        nonlocal lock, epoch
        for record in tuple(registry.values()):
            if record.source_finalizer is not None:
                record.source_finalizer.detach()
            _close_descriptor_quiet(record.source_descriptor)
        registry.clear()
        issued.clear()
        lock = threading.RLock()
        epoch = object()

    return issue, assert_current, project, consume, close, after_fork


(
    _CAP_ISSUE,
    _CAP_ASSERT,
    _CAP_PROJECT,
    _CAP_CONSUME,
    _CAP_CLOSE,
    _CAP_FORK_CHILD,
) = _build_capability_owner()


def _projection(
    profile_raw: bytes,
    profile: dict[str, Any],
    transport_raw: bytes,
    *,
    source: str,
    source_identity_sha256: str,
    issuance_nonce_sha256: str,
) -> dict[str, Any]:
    profile_bytes_sha256 = hashlib.sha256(profile_raw).hexdigest()
    transport_bytes_sha256 = hashlib.sha256(transport_raw).hexdigest()
    capability_id = "direct-reviewed-read-profile-" + digest(
        {
            "schema": "auto-g16-direct-reviewed-read-profile-capability-id/1",
            "profile_bytes_sha256": profile_bytes_sha256,
            "profile_payload_sha256": profile["read_profile_payload_sha256"],
            "transport_profile_bytes_sha256": transport_bytes_sha256,
            "source_identity_sha256": source_identity_sha256,
            "issuance_nonce_sha256": issuance_nonce_sha256,
        }
    )
    document = {
        "schema": CAPABILITY_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "capability_id": capability_id,
        "profile_source": source,
        "fixed_path": str(FIXED_PRODUCTION_READ_PROFILE_PATH),
        "source_identity_sha256": source_identity_sha256,
        "issuance_nonce_sha256": issuance_nonce_sha256,
        "profile_bytes_sha256": profile_bytes_sha256,
        "profile_payload_sha256": profile["read_profile_payload_sha256"],
        "transport_profile_bytes_sha256": transport_bytes_sha256,
        "transport_profile_payload_sha256": profile["transport_binding"]["transport_profile_payload_sha256"],
        "qstat_executable": profile["server_read"]["qstat"]["executable"],
        "qstat_executable_sha256": profile["server_read"]["qstat"]["executable_sha256"],
        "qstat_executable_owner_uid": profile["server_read"]["qstat"]["executable_owner_uid"],
        "qstat_executable_mode": profile["server_read"]["qstat"]["executable_mode"],
        "qstat_timeout_seconds": profile["server_read"]["qstat"]["timeout_seconds"],
        "qstat_max_stdout_bytes": profile["server_read"]["qstat"]["max_stdout_bytes"],
        "authority": {
            "portable_projection_is_authority": False,
            "caller_profile_override": False,
            "authorizes_effect": False,
            "qsub": False,
            "qdel": False,
            "retry": False,
        },
        "projection_payload_sha256": "",
    }
    document["projection_payload_sha256"] = digest(document)
    return validate_capability_projection(document)


def validate_capability_projection(value: Any) -> dict[str, Any]:
    fields = {
        "schema", "owner", "owner_version", "capability_id", "profile_source",
        "fixed_path", "source_identity_sha256", "issuance_nonce_sha256", "profile_bytes_sha256",
        "profile_payload_sha256", "transport_profile_bytes_sha256",
        "transport_profile_payload_sha256", "qstat_executable",
        "qstat_executable_sha256", "qstat_executable_owner_uid",
        "qstat_executable_mode", "qstat_timeout_seconds", "qstat_max_stdout_bytes",
        "authority", "projection_payload_sha256",
    }
    _require(type(value) is dict and set(value) == fields, "reviewed read-profile projection fields differ")
    document = copy.deepcopy(value)
    _require(
        document["schema"] == CAPABILITY_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and re.fullmatch(r"direct-reviewed-read-profile-[a-f0-9]{64}", document["capability_id"]) is not None
        and document["profile_source"] in {"fixed_backend_file", "offline_fake_reviewed_profile"}
        and document["fixed_path"] == str(FIXED_PRODUCTION_READ_PROFILE_PATH)
        and document["qstat_executable"] == "/usr/bin/qstat"
        and document["qstat_executable_owner_uid"] == "0"
        and document["qstat_executable_mode"] == "0755"
        and document["qstat_max_stdout_bytes"] == "65536"
        and document["authority"]
        == {
            "portable_projection_is_authority": False,
            "caller_profile_override": False,
            "authorizes_effect": False,
            "qsub": False,
            "qdel": False,
            "retry": False,
        },
        "reviewed read-profile projection constants differ",
    )
    for field in (
        "source_identity_sha256", "profile_bytes_sha256", "profile_payload_sha256",
        "issuance_nonce_sha256",
        "transport_profile_bytes_sha256", "transport_profile_payload_sha256",
        "qstat_executable_sha256", "projection_payload_sha256",
    ):
        _sha(document[field], f"reviewed read-profile {field}")
    _require(
        re.fullmatch(r"(?:0|[1-9][0-9]{0,9})", document["qstat_executable_owner_uid"]) is not None
        and re.fullmatch(r"0[0-7]{3}", document["qstat_executable_mode"]) is not None
        and document["qstat_timeout_seconds"] == "30",
        "reviewed read-profile executable policy differs",
    )
    executable_mode = int(document["qstat_executable_mode"], 8)
    _require(
        executable_mode & 0o111 != 0 and executable_mode & 0o022 == 0,
        "reviewed read-profile executable mode is not executable or is writable by group/other",
    )
    expected_capability_id = "direct-reviewed-read-profile-" + digest(
        {
            "schema": "auto-g16-direct-reviewed-read-profile-capability-id/1",
            "profile_bytes_sha256": document["profile_bytes_sha256"],
            "profile_payload_sha256": document["profile_payload_sha256"],
            "transport_profile_bytes_sha256": document["transport_profile_bytes_sha256"],
            "source_identity_sha256": document["source_identity_sha256"],
            "issuance_nonce_sha256": document["issuance_nonce_sha256"],
        }
    )
    _require(
        document["capability_id"] == expected_capability_id,
        "reviewed read-profile capability id differs",
    )
    _require(
        document["projection_payload_sha256"]
        == digest({**document, "projection_payload_sha256": ""}),
        "reviewed read-profile projection hash differs",
    )
    return document


_TEST_OWNER_TOKEN = object()


class DirectReviewedReadProfileOwner:
    __slots__ = ("_source", "_profile_raw", "_source_identity_sha256", "_pid", "_used", "_seal", "_lock")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("reviewed read-profile owners use a fixed factory")

    @classmethod
    def production(cls) -> "DirectReviewedReadProfileOwner":
        _assert_module_binding()
        return _new_owner("fixed_backend_file", b"", ZERO_SHA, cls)

    @classmethod
    def _for_fake_local_testing(
        cls,
        *,
        profile_raw: bytes,
        _test_token: object,
    ) -> "DirectReviewedReadProfileOwner":
        _require(_test_token is _TEST_OWNER_TOKEN, "reviewed read-profile test token differs")
        _require(type(profile_raw) is bytes and bool(profile_raw), "fake reviewed read-profile bytes differ")
        identity_sha256 = digest(
            {"schema": "auto-g16-offline-fake-read-profile-source/1", "bytes_sha256": hashlib.sha256(profile_raw).hexdigest()}
        )
        return _new_owner("offline_fake_reviewed_profile", profile_raw, identity_sha256, _TEST_OWNER_TOKEN)

    def issue_once(self, transport_profile_raw: bytes) -> DirectReviewedReadProfileCapability:
        with self._lock:
            _require(
                type(self) is DirectReviewedReadProfileOwner
                and self._pid == os.getpid()
                and self._used is False
                and self._seal in {DirectReviewedReadProfileOwner, _TEST_OWNER_TOKEN},
                "reviewed read-profile owner is foreign, forked, or terminal",
            )
            self._used = True
        _assert_module_binding()
        source_descriptor = -1
        try:
            if self._seal is DirectReviewedReadProfileOwner:
                profile_raw, source_identity_sha256, source_descriptor, source_identity = (
                    _open_fixed_profile()
                )
            else:
                profile_raw = self._profile_raw
                source_identity_sha256 = self._source_identity_sha256
                source_identity = None
            profile = CHANNEL.load_read_profile(profile_raw, transport_profile_raw)
            projection = _projection(
                profile_raw,
                profile,
                transport_profile_raw,
                source=self._source,
                source_identity_sha256=source_identity_sha256,
                issuance_nonce_sha256=hashlib.sha256(os.urandom(32)).hexdigest(),
            )
            capability = _CAP_ISSUE(
                profile_raw,
                projection,
                source_descriptor,
                source_identity,
            )
            source_descriptor = -1
            return capability
        finally:
            _close_descriptor_quiet(source_descriptor)


def _new_owner(source: str, raw: bytes, identity_sha256: str, seal: object) -> DirectReviewedReadProfileOwner:
    value = object.__new__(DirectReviewedReadProfileOwner)
    value._source = source
    value._profile_raw = bytes(raw)
    value._source_identity_sha256 = identity_sha256
    value._pid = os.getpid()
    value._used = False
    value._seal = seal
    value._lock = threading.RLock()
    return value


def _consume_for_q1_once(
    capability: DirectReviewedReadProfileCapability,
) -> tuple[DirectReviewedReadProfileLease, bytes, dict[str, Any]]:
    _assert_module_binding()
    _require(
        type(capability) is DirectReviewedReadProfileCapability,
        "exact reviewed read-profile capability is required",
    )
    lease, raw = _CAP_CONSUME(capability)
    projection = json.loads(_CAP_PROJECT(lease, "lease").decode("utf-8"))
    validate_capability_projection(projection)
    return lease, raw, projection


class _ModuleBinding(NamedTuple):
    module: types.ModuleType
    source_sha256: str
    channel: types.ModuleType
    entries: tuple[object, ...]
    os_entries: tuple[object, ...]
    weakref_entries: tuple[object, ...]


def _capture_module_binding() -> _ModuleBinding:
    _require(__name__ == MODULE_NAME, "reviewed read-profile owner requires canonical import")
    module = sys.modules.get(MODULE_NAME)
    _require(type(module) is types.ModuleType, "canonical reviewed read-profile module is unavailable")
    return _ModuleBinding(
        module,
        _EXECUTED_SOURCE_SHA256,
        CHANNEL,
        (
            _close_descriptor_quiet, _read_descriptor_bytes, _open_fixed_profile,
            _assert_fixed_source_current, _projection, validate_capability_projection,
            _CAP_ISSUE, _CAP_ASSERT, _CAP_PROJECT, _CAP_CONSUME, _CAP_CLOSE,
            _CAP_FORK_CHILD, _consume_for_q1_once,
        ),
        (os.open, os.read, os.close, os.lseek, os.fstat, os.stat, os.urandom),
        (weakref.finalize, weakref.WeakKeyDictionary),
    )


_MODULE_BINDING = _capture_module_binding()


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    with open(__file__, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(
        type(binding) is _ModuleBinding
        and sys.modules.get(MODULE_NAME) is binding.module
        and source_sha256 == binding.source_sha256 == _EXECUTED_SOURCE_SHA256
        and CHANNEL is binding.channel
        and binding.entries
        == (
            _close_descriptor_quiet, _read_descriptor_bytes, _open_fixed_profile,
            _assert_fixed_source_current, _projection, validate_capability_projection,
            _CAP_ISSUE, _CAP_ASSERT, _CAP_PROJECT, _CAP_CONSUME, _CAP_CLOSE,
            _CAP_FORK_CHILD, _consume_for_q1_once,
        )
        and binding.os_entries
        == (os.open, os.read, os.close, os.lseek, os.fstat, os.stat, os.urandom)
        and binding.weakref_entries
        == (weakref.finalize, weakref.WeakKeyDictionary)
        and FIXED_PRODUCTION_READ_PROFILE_PATH
        == Path("/etc/auto-g16/direct-qstat-read-profile.json"),
        "reviewed read-profile source, function, path, or OS binding differs",
    )
    CHANNEL._assert_production_binding()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_CAP_FORK_CHILD)


__all__ = [
    "DirectReviewedReadProfileCapability",
    "DirectReviewedReadProfileError",
    "DirectReviewedReadProfileOwner",
]
