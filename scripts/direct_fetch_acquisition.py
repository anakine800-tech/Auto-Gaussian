#!/usr/bin/env python3
"""Fixed allowlisted direct fetch acquisition and production stream seam.

The server side consumes the exact live existing-job lease, retains its
project descriptor, observes exactly the five terminal-minimum artifacts, and
emits one bounded canonical bundle.  The controller side accepts that bundle
only through the exact shared-channel fetch codec and issues a process-local
stream capability for the local no-clobber materializer.  Portable projections
are splice evidence only and never recreate either capability.
"""

from __future__ import annotations

if globals().get("_AUTO_G16_DIRECT_FETCH_ACQUISITION_EXECUTED", False):
    raise ImportError("direct fetch acquisition owner module already executed")
_AUTO_G16_DIRECT_FETCH_ACQUISITION_EXECUTED = True

import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import sys
import threading
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import direct_existing_job_lineage as LINEAGE
import direct_local_fetch_materializer as MATERIALIZER
import direct_shared_fixed_ssh_channel as CHANNEL


MODULE_NAME = "direct_fetch_acquisition"
OWNER = "auto-g16-direct-fetch-acquisition-owner"
OWNER_VERSION = "direct-fetch-acquisition/1"
ACQUISITION_SCHEMA = "auto-g16-direct-fetch-acquisition/1"
STREAM_SCHEMA = "auto-g16-direct-closed-fetch-stream/1"
BUNDLE_SCHEMA = "auto-g16-direct-terminal-minimum-bundle/1"
BUNDLE_MAGIC = b"AUTO_G16_DIRECT_TERMINAL_MINIMUM_BUNDLE_V1\n"
BACKEND_KIND = "direct_ssh_pbs"
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_HEADER_BYTES = 1024 * 1024
MAX_BUFFERED_TEST_BUNDLE_BYTES = 2 * 1024 * 1024
REQUIRED_PRODUCTION_PREDECESSOR = "Q1_backend_owned_reviewed_read_authority_exact_type"
_TEST_TOKEN = object()


class DirectFetchAcquisitionError(ValueError):
    """The fixed fetch acquisition could not be proved exactly."""


class DirectFetchTransportUnknown(RuntimeError):
    """A fixed read transport ended without one complete exact result."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectFetchAcquisitionError(message)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DirectFetchAcquisitionError("value is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str, *, empty_allowed: bool = False) -> str:
    _require(
        type(value) is str and SHA_RE.fullmatch(value) is not None
        and value != ZERO_SHA
        and (empty_allowed or value != hashlib.sha256(b"").hexdigest()),
        f"{label} differs",
    )
    return value


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _decimal(value: Any, label: str, maximum: int) -> int:
    _require(
        type(value) is str
        and re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", value) is not None,
        f"{label} differs",
    )
    number = int(value, 10)
    _require(number <= maximum, f"{label} exceeds its fixed cap")
    return number


class _SourceSnapshot(NamedTuple):
    path: Path
    identity: tuple[int, ...]
    sha256: str


def _source_snapshot(path: Path) -> _SourceSnapshot:
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
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
    identity = (
        before.st_dev, before.st_ino, before.st_mode, before.st_uid,
        before.st_gid, before.st_size, before.st_mtime_ns, before.st_ctime_ns,
    )
    _require(
        stat.S_ISREG(before.st_mode)
        and identity == (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid,
            after.st_gid, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        ),
        "owner source identity drifted",
    )
    return _SourceSnapshot(path, identity, hashlib.sha256(b"".join(chunks)).hexdigest())


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_uid, info.st_gid,
        stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_nlink,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _identity_sha256(identity: tuple[int, ...]) -> str:
    return digest({
        "schema": "auto-g16-direct-fetch-file-identity/1",
        "fields": [str(item) for item in identity],
    })


@dataclass(frozen=True, slots=True)
class _ObservedFile:
    basename: str
    descriptor: int
    identity: tuple[int, ...]
    size_bytes: int
    sha256: str


def _read_current_file(
    project_fd: int,
    observed: _ObservedFile,
    cap: int,
    deadline: float,
) -> bytes:
    return b"".join(
        _iter_current_file_chunks(project_fd, observed, cap, deadline)
    )


def _iter_current_file_chunks(
    project_fd: int,
    observed: _ObservedFile,
    cap: int,
    deadline: float,
):
    """Yield one descriptor-bound file in fixed chunks and replay at EOF."""
    _require(time.monotonic() < deadline, "fetch acquisition deadline expired")
    before = os.fstat(observed.descriptor)
    named = os.stat(observed.basename, dir_fd=project_fd, follow_symlinks=False)
    _require(
        _file_identity(before) == observed.identity == _file_identity(named),
        f"{observed.basename} identity drifted",
    )
    os.lseek(observed.descriptor, 0, os.SEEK_SET)
    remaining = observed.size_bytes
    hasher = hashlib.sha256()
    total = 0
    while remaining:
        _require(time.monotonic() < deadline, "fetch acquisition deadline expired")
        chunk = os.read(
            observed.descriptor,
            min(MATERIALIZER.CHUNK_SIZE_BYTES, remaining),
        )
        _require(bool(chunk), f"{observed.basename} ended early")
        hasher.update(chunk)
        remaining -= len(chunk)
        total += len(chunk)
        yield chunk
    _require(os.read(observed.descriptor, 1) == b"", f"{observed.basename} grew during read")
    after = os.fstat(observed.descriptor)
    named_after = os.stat(
        observed.basename, dir_fd=project_fd, follow_symlinks=False,
    )
    _require(
        _file_identity(after) == observed.identity == _file_identity(named_after)
        and total <= cap
        and total == observed.size_bytes
        and (observed.sha256 == "" or hasher.hexdigest() == observed.sha256),
        f"{observed.basename} changed during read",
    )


def _observe_file(
    project_fd: int,
    project_info: os.stat_result,
    basename: str,
    cap: int,
    deadline: float,
) -> _ObservedFile:
    _require(
        basename in MATERIALIZER.ARTIFACT_BASENAMES
        and "/" not in basename and basename not in {"", ".", ".."},
        "fetch basename differs",
    )
    named_before = os.stat(basename, dir_fd=project_fd, follow_symlinks=False)
    _require(
        stat.S_ISREG(named_before.st_mode)
        and not stat.S_ISLNK(named_before.st_mode)
        and named_before.st_uid == project_info.st_uid == os.geteuid()
        and named_before.st_gid == project_info.st_gid
        and stat.S_IMODE(named_before.st_mode) == 0o600
        and named_before.st_nlink == 1
        and 0 <= named_before.st_size <= cap,
        f"{basename} type, owner, mode, link count, or size differs",
    )
    descriptor = os.open(
        basename,
        os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=project_fd,
    )
    try:
        info = os.fstat(descriptor)
        identity = _file_identity(info)
        _require(
            identity == _file_identity(named_before)
            and bool(fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC),
            f"{basename} descriptor identity differs",
        )
        temporary = _ObservedFile(basename, descriptor, identity, info.st_size, "")
        hasher = hashlib.sha256()
        size = 0
        for chunk in _iter_current_file_chunks(
            project_fd, temporary, cap, deadline,
        ):
            hasher.update(chunk)
            size += len(chunk)
        return _ObservedFile(
            basename, descriptor, identity, size, hasher.hexdigest(),
        )
    except BaseException:
        os.close(descriptor)
        raise


def _close_descriptors(
    lineage_descriptors: Any,
    files: tuple[_ObservedFile, ...],
) -> None:
    for item in reversed(files):
        try:
            os.close(item.descriptor)
        except OSError:
            pass
    if type(lineage_descriptors) is LINEAGE._DescriptorRecord:
        LINEAGE._close_record(lineage_descriptors)


class _ServerRecord(NamedTuple):
    capability: object
    pid: int
    epoch: object
    projection_raw: bytes
    lineage_descriptors: Any
    files: tuple[_ObservedFile, ...]
    read_profile_raw: bytes
    transport_profile_raw: bytes
    deadline: float
    commitment_sha256: str


class _ControllerRecord(NamedTuple):
    capability: object
    pid: int
    epoch: object
    projection_raw: bytes
    channel_session: object
    files: tuple[tuple[str, str, str], ...]
    target_binding_sha256: str
    commitment_sha256: str


@dataclass(slots=True)
class _ReaderRecord:
    capability: object
    pid: int
    epoch: object
    projection_raw: bytes
    channel_session: object
    files: tuple[tuple[str, str, str], ...]
    bundle_sha256: str
    file_index: int
    file_remaining: int | None
    file_hasher: Any
    lock: Any


_SERVER_TOKEN = object()
_CONTROLLER_TOKEN = object()
_READER_TOKEN = object()
_OWNER_TOKEN = object()
_PROCESS_EPOCH = object()
_LOCK = threading.RLock()
_OWNER_REGISTRY: dict[int, tuple[object, bytes, int, object, bool]] = {}


class DirectFetchAcquisitionOwner:
    __slots__ = ("_key", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("direct fetch acquisition owners are module-issued only")

    def __copy__(self) -> Any:
        raise TypeError("direct fetch acquisition owners are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("direct fetch acquisition owners are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("direct fetch acquisition owners are not serializable")


class DirectServerFetchAcquisitionCapability:
    __slots__ = ("acquisition_id", "_key", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("server fetch acquisition capabilities are owner-issued only")

    def assert_current(self) -> None:
        _SERVER_ASSERT(self)

    def portable_projection(self) -> dict[str, Any]:
        return _SERVER_PROJECT(self)

    def abandon_once(self) -> None:
        """Terminalize an unused fake/server capability and close every FD."""
        _SERVER_ABANDON(self)

    def __copy__(self) -> Any:
        raise TypeError("server fetch acquisition capabilities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("server fetch acquisition capabilities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("server fetch acquisition capabilities are not serializable")


class ClosedDirectFetchStreamCapability:
    __slots__ = ("stream_id", "target_binding_sha256", "_key", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("closed fetch stream capabilities are owner-issued only")

    def assert_current(self) -> None:
        _CONTROLLER_ASSERT(self)

    def portable_projection(self) -> dict[str, Any]:
        return _CONTROLLER_PROJECT(self)

    def __copy__(self) -> Any:
        raise TypeError("closed fetch stream capabilities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("closed fetch stream capabilities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("closed fetch stream capabilities are not serializable")


class ClosedDirectFetchReaderCapability:
    __slots__ = ("stream_id", "_key", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("closed fetch readers are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("closed fetch readers are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("closed fetch readers are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("closed fetch readers are not serializable")


def _new_owner(
    read_profile_raw: bytes,
    *,
    _test_token: object,
) -> DirectFetchAcquisitionOwner:
    _assert_module_binding()
    _require(_test_token is _TEST_TOKEN, "fetch acquisition owner test token differs")
    _require(type(read_profile_raw) is bytes and bool(read_profile_raw), "read profile bytes differ")
    owner = object.__new__(DirectFetchAcquisitionOwner)
    owner._key = id(owner)
    owner._seal = _OWNER_TOKEN
    with _LOCK:
        _OWNER_REGISTRY[owner._key] = (
            owner, bytes(read_profile_raw), os.getpid(), _PROCESS_EPOCH, False,
        )
    return owner


def _issue_server_fetch_acquisition_for_tests_once(
    lease: LINEAGE.DirectSubmittedJobReadLease,
    read_profile_raw: bytes,
    *,
    _test_token: object,
) -> DirectServerFetchAcquisitionCapability:
    """Offline fake authority only; no caller-signed production profile seam."""
    _assert_module_binding()
    _require(_test_token is _TEST_TOKEN, "fetch acquisition test token differs")
    _require(
        type(lease) is LINEAGE.DirectSubmittedJobReadLease,
        "exact existing-job read lease is required",
    )
    owner = _new_owner(read_profile_raw, _test_token=_test_token)
    result = LINEAGE._CAPABILITY_HANDOFF_FETCH(lease, owner, _test_token)
    _require(
        type(result) is DirectServerFetchAcquisitionCapability,
        "existing-job successor returned a foreign capability",
    )
    return result


def _accept_lineage_handoff_once(
    owner: DirectFetchAcquisitionOwner,
    lineage_projection_raw: bytes,
    descriptors: Any,
    transport_profile_raw: bytes,
    test_token: object,
) -> DirectServerFetchAcquisitionCapability:
    """Fixed L1 callback; L1 invokes this only after terminalizing its lease."""
    _assert_module_binding()
    _require(
        test_token is _TEST_TOKEN
        and
        type(owner) is DirectFetchAcquisitionOwner and owner._seal is _OWNER_TOKEN
        and type(descriptors) is LINEAGE._DescriptorRecord,
        "direct fetch successor handoff differs",
    )
    with _LOCK:
        state = _OWNER_REGISTRY.get(owner._key)
        _require(
            type(state) is tuple and len(state) == 5 and state[0] is owner
            and state[2] == os.getpid() and state[3] is _PROCESS_EPOCH
            and state[4] is False,
            "direct fetch successor owner is foreign, forked, or already used",
        )
        del _OWNER_REGISTRY[owner._key]
    try:
        lineage = LINEAGE.validate_lineage_projection(json.loads(lineage_projection_raw))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectFetchAcquisitionError("lineage projection bytes are malformed") from exc
    _require(
        LINEAGE.canonical_bytes(lineage) == lineage_projection_raw,
        "lineage projection bytes are not canonical",
    )
    read_profile = CHANNEL.load_read_profile(state[1], transport_profile_raw)
    _require(
        lineage["artifact_sha256"]["transport_profile"]
        == hashlib.sha256(transport_profile_raw).hexdigest()
        and lineage["binding"]["transport_profile_payload_sha256"]
        == CHANNEL.load_transport_profile(transport_profile_raw)["profile_payload_sha256"],
        "lineage and read transport profiles are spliced",
    )
    timeout = int(read_profile["server_read"]["fetch"]["timeout_seconds"], 10)
    deadline = time.monotonic() + timeout
    files: list[_ObservedFile] = []
    try:
        LINEAGE._assert_descriptor_record_current(descriptors)
        project_info = os.fstat(descriptors.project_fd)
        for basename, cap in MATERIALIZER.ARTIFACT_SPECS:
            files.append(_observe_file(
                descriptors.project_fd, project_info, basename, cap, deadline,
            ))
        total = sum(item.size_bytes for item in files)
        limits = read_profile["server_read"]["fetch"]
        _require(
            total <= int(limits["max_total_bytes"], 10),
            "terminal minimum bundle exceeds reviewed read profile",
        )
        file_projection = [
            {
                "basename": item.basename,
                "order": str(index),
                "size_bytes": str(item.size_bytes),
                "sha256": item.sha256,
                "identity_sha256": _identity_sha256(item.identity),
            }
            for index, item in enumerate(files, 1)
        ]
        projection = {
            "schema": ACQUISITION_SCHEMA,
            "owner": OWNER,
            "owner_version": OWNER_VERSION,
            "backend_kind": BACKEND_KIND,
            "acquisition_id": "",
            "lineage_id": lineage["lineage_id"],
            "lineage_projection_sha256": hashlib.sha256(lineage_projection_raw).hexdigest(),
            "lineage_result_payload_sha256": lineage["result_payload_sha256"],
            "binding": copy.deepcopy(lineage["binding"]),
            "durable": copy.deepcopy(lineage["durable"]),
            "descriptor_identity": copy.deepcopy(lineage["descriptor_identity"]),
            "read_profile_payload_sha256": read_profile["read_profile_payload_sha256"],
            "transport_profile_bytes_sha256": hashlib.sha256(transport_profile_raw).hexdigest(),
            "files": file_projection,
            "file_count": "5",
            "total_size_bytes": str(total),
            "allowlist_sha256": digest({"artifact_specs": list(MATERIALIZER.ARTIFACT_SPECS)}),
            "source_binding": {
                "lineage_source_sha256": _MODULE_BINDING.lineage_source.sha256,
                "channel_source_sha256": _MODULE_BINDING.channel_source.sha256,
                "materializer_source_sha256": _MODULE_BINDING.materializer_source.sha256,
                "acquisition_source_sha256": _MODULE_BINDING.source.sha256,
            },
            "authority": {
                "authorizes_effect": False,
                "portable_projection_authorizes_read": False,
                "read_only": True,
                "qsub_calls": "0",
                "qdel_calls": "0",
                "automatic_retry": False,
                "single_use": True,
                "production_stream_seam": False,
                "required_production_predecessor": REQUIRED_PRODUCTION_PREDECESSOR,
            },
            "result_payload_sha256": "",
        }
        projection["acquisition_id"] = "direct-fetch-acquisition-" + digest({
            "lineage_id": projection["lineage_id"],
            "read_profile_payload_sha256": projection["read_profile_payload_sha256"],
            "files": file_projection,
        })
        projection["result_payload_sha256"] = digest(projection)
        projection = validate_acquisition_projection(projection)
        _require(
            _bundle_wire_size(projection)
            <= int(limits["max_total_bytes"], 10),
            "encoded terminal minimum bundle exceeds reviewed read profile",
        )
        return _SERVER_ISSUE(
            projection,
            descriptors,
            tuple(files),
            bytes(state[1]),
            bytes(transport_profile_raw),
            deadline,
        )
    except BaseException:
        _close_descriptors(descriptors, tuple(files))
        raise


def validate_acquisition_projection(value: Any) -> dict[str, Any]:
    document = copy.deepcopy(_exact(value, {
        "schema", "owner", "owner_version", "backend_kind", "acquisition_id",
        "lineage_id", "lineage_projection_sha256", "lineage_result_payload_sha256",
        "binding", "durable", "descriptor_identity", "read_profile_payload_sha256",
        "transport_profile_bytes_sha256", "files", "file_count", "total_size_bytes",
        "allowlist_sha256", "source_binding", "authority", "result_payload_sha256",
    }, "fetch acquisition projection"))
    _require(
        document["schema"] == ACQUISITION_SCHEMA and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and document["backend_kind"] == BACKEND_KIND
        and re.fullmatch(r"direct-fetch-acquisition-[a-f0-9]{64}", document["acquisition_id"] or "") is not None
        and re.fullmatch(r"direct-submitted-job-read-[a-f0-9]{64}", document["lineage_id"] or "") is not None
        and document["file_count"] == "5",
        "fetch acquisition constants differ",
    )
    for field in (
        "lineage_projection_sha256", "lineage_result_payload_sha256",
        "read_profile_payload_sha256", "transport_profile_bytes_sha256",
        "allowlist_sha256", "result_payload_sha256",
    ):
        _sha(document[field], f"fetch acquisition {field}")
    _require(
        document["allowlist_sha256"] == digest({"artifact_specs": list(MATERIALIZER.ARTIFACT_SPECS)}),
        "fetch acquisition allowlist differs",
    )
    _require(type(document["files"]) is list and len(document["files"]) == 5, "fetch acquisition files differ")
    total = 0
    for index, ((basename, cap), item) in enumerate(zip(
        MATERIALIZER.ARTIFACT_SPECS, document["files"], strict=True,
    ), 1):
        _exact(item, {"basename", "order", "size_bytes", "sha256", "identity_sha256"}, "fetch acquisition file")
        _require(item["basename"] == basename and item["order"] == str(index), "fetch acquisition order differs")
        total += _decimal(item["size_bytes"], f"{basename} size", cap)
        _sha(item["sha256"], f"{basename} hash", empty_allowed=True)
        _sha(item["identity_sha256"], f"{basename} identity")
    _require(
        _decimal(document["total_size_bytes"], "fetch acquisition total", MATERIALIZER.TOTAL_CAP_BYTES) == total,
        "fetch acquisition total differs",
    )
    _require(
        document["authority"] == {
            "authorizes_effect": False,
            "portable_projection_authorizes_read": False,
            "read_only": True,
            "qsub_calls": "0",
            "qdel_calls": "0",
            "automatic_retry": False,
            "single_use": True,
            "production_stream_seam": False,
            "required_production_predecessor": REQUIRED_PRODUCTION_PREDECESSOR,
        },
        "fetch acquisition authority differs",
    )
    _exact(document["source_binding"], {
        "lineage_source_sha256", "channel_source_sha256",
        "materializer_source_sha256", "acquisition_source_sha256",
    }, "fetch acquisition source binding")
    for item in document["source_binding"].values():
        _sha(item, "fetch acquisition source")
    expected_id = "direct-fetch-acquisition-" + digest({
        "lineage_id": document["lineage_id"],
        "read_profile_payload_sha256": document["read_profile_payload_sha256"],
        "files": document["files"],
    })
    _require(document["acquisition_id"] == expected_id, "fetch acquisition id differs")
    projection = copy.deepcopy(document)
    projection["result_payload_sha256"] = ""
    _require(document["result_payload_sha256"] == digest(projection), "fetch acquisition result hash differs")
    return document


def _bundle_components(
    projection: dict[str, Any],
    payloads: tuple[bytes, ...],
) -> tuple[bytes, ...]:
    raw_header = _bundle_header_raw(projection)
    files = projection["files"]
    _require(len(payloads) == len(files) == 5, "terminal bundle exact-five files differ")
    _require(
        all(
            len(raw) == int(declared["size_bytes"], 10)
            and hashlib.sha256(raw).hexdigest() == declared["sha256"]
            for raw, declared in zip(payloads, files, strict=True)
        ),
        "terminal bundle payload differs from acquisition",
    )
    components: list[bytes] = [
        BUNDLE_MAGIC,
        struct.pack("!I", len(raw_header)),
        raw_header,
    ]
    for raw in payloads:
        components.extend((struct.pack("!Q", len(raw)), raw))
    return tuple(components)


def _bundle_bytes(projection: dict[str, Any], payloads: tuple[bytes, ...]) -> bytes:
    return b"".join(_bundle_components(projection, payloads))


def _bundle_header_raw(projection: dict[str, Any]) -> bytes:
    files = projection["files"]
    header = {
        "schema": BUNDLE_SCHEMA,
        "acquisition": projection,
        "files": copy.deepcopy(files),
        "file_count": "5",
        "total_size_bytes": projection["total_size_bytes"],
        "authority": {
            "authorizes_effect": False,
            "qsub_calls": "0",
            "qdel_calls": "0",
        },
    }
    raw_header = canonical_bytes(header)
    _require(len(raw_header) <= MAX_HEADER_BYTES, "terminal bundle header exceeds cap")
    return raw_header


def _bundle_wire_size(projection: dict[str, Any]) -> int:
    raw_header = _bundle_header_raw(projection)
    payload_size = sum(int(item["size_bytes"], 10) for item in projection["files"])
    return len(BUNDLE_MAGIC) + 4 + len(raw_header) + 8 * 5 + payload_size


def _validate_fetch_request(request_frame: bytes, expected_job_id: str) -> dict[str, Any]:
    try:
        CHANNEL._validate_single_canonical_frame_bytes(request_frame)
        request = json.loads(request_frame[4:])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectFetchAcquisitionError("fetch request frame is malformed") from exc
    _exact(
        request,
        {"protocol", "operation", "operation_id", "job_id", "bundle", "authority"},
        "fetch request",
    )
    _require(
        request["protocol"] == CHANNEL.READ_PROTOCOL
        and request["operation"] == "fetch_terminal_minimum_bundle"
        and request["bundle"] == "terminal_minimum_v1"
        and re.fullmatch(
            r"fixed-ssh-operation-[a-f0-9]{64}", request["operation_id"] or "",
        ) is not None
        and request["job_id"] == expected_job_id
        and request["authority"] == {
            "authorizes_effect": False, "qsub_calls": "0",
        },
        "fetch request identity or authority differs",
    )
    return request


def _commitment_update(hasher: Any, label: str, raw: bytes) -> None:
    """Incrementally bind one labeled byte field without concatenating it."""
    label_raw = label.encode("ascii")
    hasher.update(struct.pack("!I", len(label_raw)))
    hasher.update(label_raw)
    hasher.update(struct.pack("!Q", len(raw)))
    hasher.update(raw)


def _server_record_commitment(record: _ServerRecord) -> str:
    """Incrementally commit immutable metadata and bounded owner raw fields."""
    descriptors = record.lineage_descriptors
    descriptor_metadata = {
        "root_fds": list(descriptors.root_fds),
        "root_names": list(descriptors.root_names),
        "root_identities": [list(item) for item in descriptors.root_identities],
        "project_fd": descriptors.project_fd,
        "project_identity": list(descriptors.project_identity),
        "receipt_fd": descriptors.receipt_fd,
        "receipt_identity": list(descriptors.receipt_identity),
        "state_fds": list(descriptors.state_fds),
        "state_names": list(descriptors.state_names),
        "state_identities": [list(item) for item in descriptors.state_identities],
        "journal_fd": descriptors.journal_fd,
        "journal_identity": list(descriptors.journal_identity),
        "lock_fd": descriptors.lock_fd,
        "lock_identity": list(descriptors.lock_identity),
        "manifest_fd": descriptors.manifest_fd,
        "manifest_identity": list(descriptors.manifest_identity),
        "started_fd": descriptors.started_fd,
        "started_identity": list(descriptors.started_identity),
        "terminal_fd": descriptors.terminal_fd,
        "terminal_identity": list(descriptors.terminal_identity),
        "project_name": descriptors.project_name,
        "journal_name": descriptors.journal_name,
    }
    file_metadata = [
        {
            "basename": item.basename,
            "descriptor": item.descriptor,
            "identity": list(item.identity),
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
        }
        for item in record.files
    ]
    hasher = hashlib.sha256()
    for label, raw in (
        ("capability_id", str(id(record.capability)).encode("ascii")),
        ("pid", str(record.pid).encode("ascii")),
        ("epoch_id", str(id(record.epoch)).encode("ascii")),
        ("projection", record.projection_raw),
        ("descriptor_metadata", canonical_bytes(descriptor_metadata)),
        ("file_metadata", canonical_bytes(file_metadata)),
        ("receipt_raw", descriptors.receipt_raw),
        ("manifest_raw", descriptors.manifest_raw),
        ("started_raw", descriptors.started_raw),
        ("terminal_raw", descriptors.terminal_raw),
        ("read_profile", record.read_profile_raw),
        ("transport_profile", record.transport_profile_raw),
        ("deadline", record.deadline.hex().encode("ascii")),
    ):
        _commitment_update(hasher, label, raw)
    return hasher.hexdigest()


def _build_server_owner_entries() -> tuple[object, ...]:
    """Keep descriptor-bearing server state in one closure-private registry."""
    registry: dict[int, _ServerRecord] = {}
    lock = threading.RLock()
    artifact_specs = tuple(MATERIALIZER.ARTIFACT_SPECS)
    read_current = _read_current_file
    iter_current = _iter_current_file_chunks
    close_descriptors = _close_descriptors
    record_commitment = _server_record_commitment
    validate_request = _validate_fetch_request
    write_until = CHANNEL._write_frame_until
    binding_guard: object | None = None

    def assert_binding() -> None:
        if not callable(binding_guard):
            raise DirectFetchAcquisitionError("server binding guard is not installed")
        binding_guard()

    def install_binding_guard(guard: object) -> None:
        nonlocal binding_guard
        if binding_guard is not None or not callable(guard):
            raise DirectFetchAcquisitionError("server binding guard installation differs")
        binding_guard = guard

    def validate_record(record: _ServerRecord) -> dict[str, Any]:
        _require(
            type(record) is _ServerRecord
            and type(record.capability) is DirectServerFetchAcquisitionCapability
            and record.capability._seal is _SERVER_TOKEN
            and record.pid == os.getpid()
            and record.epoch is _PROCESS_EPOCH
            and type(record.projection_raw) is bytes
            and type(record.read_profile_raw) is bytes
            and type(record.transport_profile_raw) is bytes
            and type(record.files) is tuple
            and type(record.lineage_descriptors) is LINEAGE._DescriptorRecord
            and type(record.deadline) is float
            and record.commitment_sha256 == record_commitment(record._replace(commitment_sha256="")),
            "server acquisition immutable registry commitment differs",
        )
        try:
            projection = validate_acquisition_projection(json.loads(record.projection_raw))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectFetchAcquisitionError("server acquisition projection bytes are malformed") from exc
        _require(
            canonical_bytes(projection) == record.projection_raw
            and record.capability.acquisition_id == projection["acquisition_id"],
            "server acquisition projection or capability identity differs",
        )
        profile = CHANNEL.load_read_profile(
            record.read_profile_raw, record.transport_profile_raw,
        )
        _require(
            projection["read_profile_payload_sha256"]
            == profile["read_profile_payload_sha256"]
            and projection["transport_profile_bytes_sha256"]
            == hashlib.sha256(record.transport_profile_raw).hexdigest(),
            "server acquisition immutable profile binding differs",
        )
        LINEAGE._assert_descriptor_record_current(record.lineage_descriptors)
        for (basename, cap), observed in zip(artifact_specs, record.files, strict=True):
            _require(
                type(observed) is _ObservedFile
                and basename == observed.basename
                and _file_identity(os.fstat(observed.descriptor)) == observed.identity
                and _file_identity(os.stat(
                    basename,
                    dir_fd=record.lineage_descriptors.project_fd,
                    follow_symlinks=False,
                )) == observed.identity
                and observed.size_bytes <= cap,
                f"{basename} acquisition currentness differs",
            )
        _require(time.monotonic() < record.deadline, "fetch acquisition deadline expired")
        return projection

    def exact_live(capability: Any) -> tuple[_ServerRecord, dict[str, Any]]:
        assert_binding()
        _require(
            type(capability) is DirectServerFetchAcquisitionCapability
            and capability._seal is _SERVER_TOKEN,
            "exact server fetch acquisition capability is required",
        )
        with lock:
            record = registry.get(capability._key)
        _require(
            type(record) is _ServerRecord and record.capability is capability,
            "server fetch acquisition capability is absent, forked, forged, or terminal",
        )
        return record, validate_record(record)

    def issue(
        projection: dict[str, Any],
        descriptors: Any,
        files: tuple[_ObservedFile, ...],
        read_profile_raw: bytes,
        transport_profile_raw: bytes,
        deadline: float,
    ) -> DirectServerFetchAcquisitionCapability:
        assert_binding()
        projection = validate_acquisition_projection(projection)
        projection_raw = canonical_bytes(projection)
        capability = object.__new__(DirectServerFetchAcquisitionCapability)
        capability.acquisition_id = projection["acquisition_id"]
        capability._key = id(capability)
        capability._seal = _SERVER_TOKEN
        provisional = _ServerRecord(
            capability, os.getpid(), _PROCESS_EPOCH, projection_raw,
            descriptors, tuple(files), bytes(read_profile_raw),
            bytes(transport_profile_raw), float(deadline), "",
        )
        record = provisional._replace(
            commitment_sha256=record_commitment(provisional),
        )
        validate_record(record)
        with lock:
            _require(capability._key not in registry, "server acquisition key collision")
            registry[capability._key] = record
        return capability

    def assert_current(capability: Any) -> None:
        exact_live(capability)

    def project(capability: Any) -> dict[str, Any]:
        _record, projection = exact_live(capability)
        return copy.deepcopy(projection)

    def terminal_record(capability: Any) -> _ServerRecord:
        assert_binding()
        _require(
            type(capability) is DirectServerFetchAcquisitionCapability
            and capability._seal is _SERVER_TOKEN,
            "exact server fetch acquisition capability is required",
        )
        with lock:
            record = registry.get(capability._key)
            _require(
                type(record) is _ServerRecord and record.capability is capability,
                "server acquisition is absent, forged, forked, or terminal",
            )
            del registry[capability._key]
        return record

    def build_response(capability: Any, request_frame: bytes) -> bytearray:
        """Terminalize before validating any request; every exit closes FDs."""
        record = terminal_record(capability)
        try:
            projection = validate_record(record)
            _require(
                _bundle_wire_size(projection)
                <= MAX_BUFFERED_TEST_BUNDLE_BYTES,
                "buffered test bundle exceeds its fixed small cap",
            )
            request = validate_request(
                request_frame, projection["binding"]["job_id"],
            )
            payloads = tuple(
                read_current(
                    record.lineage_descriptors.project_fd,
                    observed,
                    cap,
                    record.deadline,
                )
                for (_basename, cap), observed in zip(
                    artifact_specs, record.files, strict=True,
                )
            )
            components = _bundle_components(projection, payloads)
            bundle_size = sum(len(item) for item in components)
            profile = CHANNEL.load_read_profile(
                record.read_profile_raw, record.transport_profile_raw,
            )
            limits = profile["server_read"]["fetch"]
            max_total = int(limits["max_total_bytes"], 10)
            max_chunk = int(limits["max_chunk_bytes"], 10)
            max_chunks = int(limits["max_chunks"], 10)
            _require(
                0 < bundle_size <= max_total,
                "encoded terminal bundle exceeds read profile",
            )
            chunk_count = (bundle_size + max_chunk - 1) // max_chunk
            _require(
                0 < chunk_count <= max_chunks,
                "encoded terminal bundle chunk count exceeds read profile",
            )
            bundle_hasher = hashlib.sha256()
            for component in components:
                bundle_hasher.update(component)
            header = {
                "protocol": CHANNEL.READ_PROTOCOL,
                "status": "streaming_terminal_minimum_bundle",
                "operation_id": request["operation_id"],
                "job_id": request["job_id"],
                "chunk_count": str(chunk_count),
                "total_size_bytes": str(bundle_size),
                "bundle_sha256": bundle_hasher.hexdigest(),
                "authority": {"authorizes_effect": False, "qsub_calls": "0"},
            }
            trailer = {
                "protocol": CHANNEL.READ_PROTOCOL,
                "status": "completed",
                "operation_id": request["operation_id"],
                "job_id": request["job_id"],
                "chunk_count": str(chunk_count),
                "total_size_bytes": str(bundle_size),
                "bundle_sha256": bundle_hasher.hexdigest(),
                "authority": {"authorizes_effect": False, "qsub_calls": "0"},
                "trailer_payload_sha256": "",
            }
            trailer["trailer_payload_sha256"] = CHANNEL.digest(trailer)
            response = bytearray(CHANNEL._canonical_frame(header))
            component_index = 0
            component_offset = 0
            remaining_bundle = bundle_size
            for _index in range(chunk_count):
                chunk_size = min(max_chunk, remaining_bundle)
                response.extend(struct.pack("!I", chunk_size))
                remaining_chunk = chunk_size
                while remaining_chunk:
                    component = memoryview(components[component_index])
                    available = len(component) - component_offset
                    take = min(available, remaining_chunk)
                    response.extend(
                        component[component_offset:component_offset + take]
                    )
                    component_offset += take
                    remaining_chunk -= take
                    remaining_bundle -= take
                    if component_offset == len(component):
                        component_index += 1
                        component_offset = 0
            _require(
                remaining_bundle == 0 and component_index == len(components),
                "encoded terminal bundle framing differs",
            )
            response.extend(CHANNEL._canonical_frame(trailer))
            return response
        finally:
            close_descriptors(record.lineage_descriptors, record.files)

    def write_response(
        capability: Any,
        request_frame: bytes,
        descriptor: int,
    ) -> None:
        """Terminally stream one response with one absolute deadline."""
        record = terminal_record(capability)
        response_started = False
        try:
            _require(
                type(descriptor) is int and descriptor >= 0,
                "terminal response descriptor differs",
            )
            projection = validate_record(record)
            request = validate_request(
                request_frame, projection["binding"]["job_id"],
            )
            profile = CHANNEL.load_read_profile(
                record.read_profile_raw, record.transport_profile_raw,
            )
            limits = profile["server_read"]["fetch"]
            max_total = int(limits["max_total_bytes"], 10)
            max_chunk = int(limits["max_chunk_bytes"], 10)
            max_chunks = int(limits["max_chunks"], 10)
            raw_header = _bundle_header_raw(projection)
            bundle_size = _bundle_wire_size(projection)
            _require(
                0 < bundle_size <= max_total,
                "encoded terminal bundle exceeds read profile",
            )
            chunk_count = (bundle_size + max_chunk - 1) // max_chunk
            _require(
                0 < chunk_count <= max_chunks,
                "encoded terminal bundle chunk count exceeds read profile",
            )
            bundle_hasher = hashlib.sha256()
            bundle_hasher.update(BUNDLE_MAGIC)
            bundle_hasher.update(struct.pack("!I", len(raw_header)))
            bundle_hasher.update(raw_header)
            for (basename, cap), observed, declared in zip(
                artifact_specs,
                record.files,
                projection["files"],
                strict=True,
            ):
                _require(
                    observed.basename == basename
                    and str(observed.size_bytes) == declared["size_bytes"]
                    and observed.sha256 == declared["sha256"],
                    f"{basename} acquisition metadata drifted",
                )
                bundle_hasher.update(struct.pack("!Q", observed.size_bytes))
                for payload_chunk in iter_current(
                    record.lineage_descriptors.project_fd,
                    observed,
                    cap,
                    record.deadline,
                ):
                    bundle_hasher.update(payload_chunk)
            header = {
                "protocol": CHANNEL.READ_PROTOCOL,
                "status": "streaming_terminal_minimum_bundle",
                "operation_id": request["operation_id"],
                "job_id": request["job_id"],
                "chunk_count": str(chunk_count),
                "total_size_bytes": str(bundle_size),
                "bundle_sha256": bundle_hasher.hexdigest(),
                "authority": {"authorizes_effect": False, "qsub_calls": "0"},
            }
            write_until(
                descriptor, CHANNEL._canonical_frame(header), record.deadline,
            )
            response_started = True

            def parts():
                yield BUNDLE_MAGIC
                yield struct.pack("!I", len(raw_header))
                yield raw_header
                for (basename, cap), observed, declared in zip(
                    artifact_specs,
                    record.files,
                    projection["files"],
                    strict=True,
                ):
                    _require(
                        observed.basename == basename
                        and str(observed.size_bytes) == declared["size_bytes"]
                        and observed.sha256 == declared["sha256"],
                        f"{basename} acquisition metadata drifted",
                    )
                    yield struct.pack("!Q", observed.size_bytes)
                    yield from iter_current(
                        record.lineage_descriptors.project_fd,
                        observed,
                        cap,
                        record.deadline,
                    )

            hasher = hashlib.sha256()
            buffer = bytearray()
            observed_total = 0
            emitted_chunks = 0
            for part in parts():
                view = memoryview(part)
                offset = 0
                while offset < len(view):
                    take = min(max_chunk - len(buffer), len(view) - offset)
                    piece = view[offset:offset + take]
                    buffer.extend(piece)
                    hasher.update(piece)
                    observed_total += take
                    offset += take
                    if len(buffer) == max_chunk:
                        write_until(
                            descriptor,
                            struct.pack("!I", len(buffer)),
                            record.deadline,
                        )
                        write_until(descriptor, bytes(buffer), record.deadline)
                        buffer.clear()
                        emitted_chunks += 1
            if buffer:
                write_until(
                    descriptor,
                    struct.pack("!I", len(buffer)),
                    record.deadline,
                )
                write_until(descriptor, bytes(buffer), record.deadline)
                buffer.clear()
                emitted_chunks += 1
            _require(
                observed_total == bundle_size
                and emitted_chunks == chunk_count
                and hasher.hexdigest() == header["bundle_sha256"],
                "terminal bundle streamed size or chunk count differs",
            )
            trailer = {
                "protocol": CHANNEL.READ_PROTOCOL,
                "status": "completed",
                "operation_id": request["operation_id"],
                "job_id": request["job_id"],
                "chunk_count": str(chunk_count),
                "total_size_bytes": str(bundle_size),
                "bundle_sha256": hasher.hexdigest(),
                "authority": {"authorizes_effect": False, "qsub_calls": "0"},
                "trailer_payload_sha256": "",
            }
            trailer["trailer_payload_sha256"] = CHANNEL.digest(trailer)
            write_until(
                descriptor, CHANNEL._canonical_frame(trailer), record.deadline,
            )
        except CHANNEL.ControllerTransportUnknown as exc:
            raise DirectFetchTransportUnknown(
                "terminal response transport is unknown; no retry"
            ) from exc
        except BaseException as exc:
            if response_started:
                raise DirectFetchTransportUnknown(
                    "terminal response ended after output began; no retry"
                ) from exc
            raise
        finally:
            close_descriptors(record.lineage_descriptors, record.files)

    def abandon(capability: Any) -> None:
        record = terminal_record(capability)
        close_descriptors(record.lineage_descriptors, record.files)

    def after_fork_child() -> None:
        nonlocal lock
        for record in tuple(registry.values()):
            close_descriptors(record.lineage_descriptors, record.files)
        registry.clear()
        lock = threading.RLock()

    return (
        issue, assert_current, project, build_response, write_response, abandon,
        after_fork_child, install_binding_guard,
    )


(
    _SERVER_ISSUE,
    _SERVER_ASSERT,
    _SERVER_PROJECT,
    _SERVER_BUILD_RESPONSE,
    _SERVER_WRITE_RESPONSE,
    _SERVER_ABANDON,
    _SERVER_FORK_CHILD,
    _SERVER_INSTALL_BINDING_GUARD,
) = _build_server_owner_entries()


def _build_terminal_minimum_response_for_tests_once(
    capability: DirectServerFetchAcquisitionCapability,
    request_frame: bytes,
    *,
    _test_token: object,
) -> bytearray:
    """Buffered small-fixture response; never a production server path."""
    _require(_test_token is _TEST_TOKEN, "buffered response test token differs")
    return _SERVER_BUILD_RESPONSE(capability, request_frame)


def _write_terminal_minimum_response_for_tests_once(
    capability: DirectServerFetchAcquisitionCapability,
    request_frame: bytes,
    descriptor: int,
    *,
    _test_token: object,
) -> None:
    """Offline fixed-descriptor streaming server harness."""
    _require(_test_token is _TEST_TOKEN, "streaming response test token differs")
    _SERVER_WRITE_RESPONSE(capability, request_frame, descriptor)


def _parse_bundle(
    raw: bytes | bytearray,
) -> tuple[
    dict[str, Any],
    tuple[tuple[str, memoryview, str, str], ...],
]:
    _require(
        type(raw) in {bytes, bytearray} and raw.startswith(BUNDLE_MAGIC),
        "terminal bundle magic differs",
    )
    raw_view = memoryview(raw).toreadonly()
    offset = len(BUNDLE_MAGIC)
    _require(len(raw) >= offset + 4, "terminal bundle header is truncated")
    header_size = struct.unpack("!I", raw[offset:offset + 4])[0]
    offset += 4
    _require(0 < header_size <= MAX_HEADER_BYTES and len(raw) >= offset + header_size, "terminal bundle header size differs")
    header_raw = raw[offset:offset + header_size]
    offset += header_size
    try:
        header = json.loads(header_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectFetchAcquisitionError("terminal bundle header is malformed") from exc
    _require(canonical_bytes(header) == header_raw, "terminal bundle header is not canonical")
    _exact(header, {"schema", "acquisition", "files", "file_count", "total_size_bytes", "authority"}, "terminal bundle header")
    acquisition = validate_acquisition_projection(header["acquisition"])
    _require(
        header["schema"] == BUNDLE_SCHEMA
        and header["files"] == acquisition["files"]
        and header["file_count"] == "5"
        and header["authority"] == {"authorizes_effect": False, "qsub_calls": "0", "qdel_calls": "0"},
        "terminal bundle constants differ",
    )
    files: list[tuple[str, memoryview, str, str]] = []
    total = 0
    for (basename, cap), declared in zip(MATERIALIZER.ARTIFACT_SPECS, acquisition["files"], strict=True):
        _require(len(raw) >= offset + 8, f"{basename} length is truncated")
        size = struct.unpack("!Q", raw[offset:offset + 8])[0]
        offset += 8
        _require(size <= cap and len(raw) >= offset + size, f"{basename} payload is truncated or oversized")
        payload = raw_view[offset:offset + size]
        offset += size
        _require(
            str(size) == declared["size_bytes"]
            and hashlib.sha256(payload).hexdigest() == declared["sha256"],
            f"{basename} size or hash differs",
        )
        files.append((basename, payload, str(size), declared["sha256"]))
        total += size
    _require(offset == len(raw), "terminal bundle contains extra bytes or a second frame")
    _require(
        header["total_size_bytes"] == str(total)
        and acquisition["total_size_bytes"] == str(total),
        "terminal bundle total differs",
    )
    return acquisition, tuple(files)


def validate_closed_stream_projection(value: Any) -> dict[str, Any]:
    document = copy.deepcopy(_exact(value, {
        "schema", "owner", "owner_version", "backend_kind", "stream_id",
        "target_binding_sha256", "acquisition_id",
        "acquisition_result_payload_sha256", "lineage_id", "operation_id",
        "read_profile_payload_sha256", "bundle_sha256", "files",
        "file_count", "total_size_bytes", "authority",
        "stream_projection_sha256",
    }, "closed fetch stream projection"))
    _require(
        document["schema"] == STREAM_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and document["backend_kind"] == BACKEND_KIND
        and re.fullmatch(
            r"direct-closed-fetch-stream-[a-f0-9]{64}",
            document["stream_id"] or "",
        ) is not None
        and re.fullmatch(
            r"direct-fetch-acquisition-[a-f0-9]{64}",
            document["acquisition_id"] or "",
        ) is not None
        and re.fullmatch(
            r"direct-submitted-job-read-[a-f0-9]{64}",
            document["lineage_id"] or "",
        ) is not None
        and re.fullmatch(
            r"fixed-ssh-operation-[a-f0-9]{64}",
            document["operation_id"] or "",
        ) is not None
        and document["file_count"] == "5",
        "closed fetch stream constants differ",
    )
    for field in (
        "target_binding_sha256",
        "acquisition_result_payload_sha256",
        "read_profile_payload_sha256",
        "bundle_sha256",
        "stream_projection_sha256",
    ):
        _sha(document[field], f"closed fetch stream {field}")
    _require(
        type(document["files"]) is list and len(document["files"]) == 5,
        "closed fetch stream exact-five files differ",
    )
    total = 0
    for index, ((basename, cap), item) in enumerate(zip(
        MATERIALIZER.ARTIFACT_SPECS, document["files"], strict=True,
    ), 1):
        _exact(
            item,
            {"basename", "order", "size_bytes", "sha256", "identity_sha256"},
            "closed fetch stream file",
        )
        _require(
            item["basename"] == basename and item["order"] == str(index),
            "closed fetch stream file order differs",
        )
        total += _decimal(item["size_bytes"], f"{basename} stream size", cap)
        _sha(item["sha256"], f"{basename} stream hash", empty_allowed=True)
        _sha(item["identity_sha256"], f"{basename} stream identity")
    _require(
        _decimal(
            document["total_size_bytes"],
            "closed fetch stream total",
            MATERIALIZER.TOTAL_CAP_BYTES,
        ) == total,
        "closed fetch stream total differs",
    )
    _require(document["authority"] == {
        "authorizes_effect": False,
        "portable_projection_authorizes_stream": False,
        "remote_fetch_acquired": True,
        "closed_stream_owner": True,
        "production_integration": False,
        "required_production_predecessor": REQUIRED_PRODUCTION_PREDECESSOR,
        "qsub_calls": "0",
        "qdel_calls": "0",
        "automatic_retry": False,
        "single_use": True,
    }, "closed fetch stream authority differs")
    expected_id = "direct-closed-fetch-stream-" + digest({
        "target_binding_sha256": document["target_binding_sha256"],
        "acquisition_result_payload_sha256": document[
            "acquisition_result_payload_sha256"
        ],
        "operation_id": document["operation_id"],
        "bundle_sha256": document["bundle_sha256"],
    })
    _require(document["stream_id"] == expected_id, "closed fetch stream id differs")
    projection = copy.deepcopy(document)
    projection["stream_projection_sha256"] = ""
    _require(
        document["stream_projection_sha256"] == digest(projection),
        "closed fetch stream projection hash differs",
    )
    return document


def _controller_record_commitment(record: _ControllerRecord) -> str:
    hasher = hashlib.sha256()
    for label, raw in (
        ("capability_id", str(id(record.capability)).encode("ascii")),
        ("pid", str(record.pid).encode("ascii")),
        ("epoch_id", str(id(record.epoch)).encode("ascii")),
        ("projection", record.projection_raw),
        ("channel_session_id", str(id(record.channel_session)).encode("ascii")),
        ("target_binding", record.target_binding_sha256.encode("ascii")),
    ):
        _commitment_update(hasher, label, raw)
    for index, item in enumerate(record.files, 1):
        basename, declared_size, declared_sha = item
        cap = MATERIALIZER.ARTIFACT_CAPS.get(basename, -1)
        metadata = canonical_bytes({
            "basename": basename,
            "cap_bytes": str(cap),
            "declared_sha256": declared_sha,
            "declared_size_bytes": declared_size,
            "order": str(index),
        })
        _commitment_update(hasher, "file_metadata", metadata)
    return hasher.hexdigest()


def _build_controller_owner_entries() -> tuple[object, ...]:
    registry: dict[int, _ControllerRecord] = {}
    reader_registry: dict[int, _ReaderRecord] = {}
    lock = threading.RLock()
    record_commitment = _controller_record_commitment
    validate_projection = validate_closed_stream_projection
    binding_guard: object | None = None

    def assert_binding() -> None:
        if not callable(binding_guard):
            raise DirectFetchAcquisitionError("controller binding guard is not installed")
        binding_guard()

    def install_binding_guard(guard: object) -> None:
        nonlocal binding_guard
        if binding_guard is not None or not callable(guard):
            raise DirectFetchAcquisitionError(
                "controller binding guard installation differs"
            )
        binding_guard = guard

    def validate_record(record: _ControllerRecord) -> dict[str, Any]:
        if not (
            type(record) is _ControllerRecord
            and type(record.capability) is ClosedDirectFetchStreamCapability
            and record.capability._seal is _CONTROLLER_TOKEN
            and record.pid == os.getpid()
            and record.epoch is _PROCESS_EPOCH
            and type(record.projection_raw) is bytes
            and type(record.channel_session)
            is CHANNEL._FetchResponseStreamSession
            and type(record.files) is tuple
            and type(record.target_binding_sha256) is str
            and record.commitment_sha256
            == record_commitment(record._replace(commitment_sha256=""))
        ):
            raise DirectFetchAcquisitionError(
                "controller immutable registry commitment differs"
            )
        try:
            projection = validate_projection(json.loads(record.projection_raw))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectFetchAcquisitionError(
                "controller stream projection bytes are malformed"
            ) from exc
        if not (
            canonical_bytes(projection) == record.projection_raw
            and record.capability.stream_id == projection["stream_id"]
            and record.capability.target_binding_sha256
            == projection["target_binding_sha256"]
            == record.target_binding_sha256
            and len(record.files) == 5
        ):
            raise DirectFetchAcquisitionError(
                "controller capability or projection identity differs"
            )
        for declared, item in zip(projection["files"], record.files, strict=True):
            if not (
                type(item) is tuple
                and len(item) == 3
                and item[0] == declared["basename"]
                and item[1] == declared["size_bytes"]
                and item[2] == declared["sha256"]
            ):
                raise DirectFetchAcquisitionError(
                    "controller immutable file commitment differs"
                )
        CHANNEL._FETCH_STREAM_ASSERT(record.channel_session)
        return projection

    def exact_live(capability: Any) -> tuple[_ControllerRecord, dict[str, Any]]:
        assert_binding()
        if not (
            type(capability) is ClosedDirectFetchStreamCapability
            and capability._seal is _CONTROLLER_TOKEN
        ):
            raise DirectFetchAcquisitionError(
                "exact closed fetch stream capability is required"
            )
        with lock:
            record = registry.get(capability._key)
        if not (
            type(record) is _ControllerRecord and record.capability is capability
        ):
            raise DirectFetchAcquisitionError(
                "closed fetch stream capability is absent, forked, forged, or terminal"
            )
        return record, validate_record(record)

    def issue(
        projection: dict[str, Any],
        channel_session: CHANNEL._FetchResponseStreamSession,
        files: tuple[tuple[str, str, str], ...],
        target_binding_sha256: str,
    ) -> ClosedDirectFetchStreamCapability:
        assert_binding()
        projection = validate_projection(projection)
        if projection["target_binding_sha256"] != target_binding_sha256:
            raise DirectFetchAcquisitionError("controller target binding differs")
        CHANNEL._FETCH_STREAM_ASSERT(channel_session)
        capability = object.__new__(ClosedDirectFetchStreamCapability)
        capability.stream_id = projection["stream_id"]
        capability.target_binding_sha256 = target_binding_sha256
        capability._key = id(capability)
        capability._seal = _CONTROLLER_TOKEN
        provisional = _ControllerRecord(
            capability,
            os.getpid(),
            _PROCESS_EPOCH,
            canonical_bytes(projection),
            channel_session,
            tuple(files),
            target_binding_sha256,
            "",
        )
        record = provisional._replace(
            commitment_sha256=record_commitment(provisional),
        )
        validate_record(record)
        with lock:
            if capability._key in registry:
                raise DirectFetchAcquisitionError("controller registry key collision")
            registry[capability._key] = record
        return capability

    def assert_current(capability: Any) -> None:
        exact_live(capability)

    def project(capability: Any) -> dict[str, Any]:
        _record, projection = exact_live(capability)
        return copy.deepcopy(projection)

    def consume(
        capability: Any,
        target_binding_sha256: str,
    ) -> tuple[
        dict[str, Any],
        ClosedDirectFetchReaderCapability,
    ]:
        record, projection = exact_live(capability)
        if target_binding_sha256 != record.target_binding_sha256:
            raise DirectFetchAcquisitionError(
                "closed stream and materialization target are spliced"
            )
        with lock:
            if registry.get(capability._key) is not record:
                raise DirectFetchAcquisitionError(
                    "closed fetch stream consume raced"
                )
            del registry[capability._key]
        reader = object.__new__(ClosedDirectFetchReaderCapability)
        reader.stream_id = projection["stream_id"]
        reader._key = id(reader)
        reader._seal = _READER_TOKEN
        reader_record = _ReaderRecord(
            capability=reader,
            pid=os.getpid(),
            epoch=_PROCESS_EPOCH,
            projection_raw=record.projection_raw,
            channel_session=record.channel_session,
            files=record.files,
            bundle_sha256=projection["bundle_sha256"],
            file_index=0,
            file_remaining=None,
            file_hasher=None,
            lock=threading.Lock(),
        )
        with lock:
            _require(reader._key not in reader_registry, "reader key collision")
            reader_registry[reader._key] = reader_record
        return copy.deepcopy(projection), reader

    def exact_reader(capability: Any) -> _ReaderRecord:
        assert_binding()
        _require(
            type(capability) is ClosedDirectFetchReaderCapability
            and capability._seal is _READER_TOKEN,
            "exact closed fetch reader is required",
        )
        with lock:
            record = reader_registry.get(capability._key)
        _require(
            type(record) is _ReaderRecord
            and record.capability is capability
            and record.pid == os.getpid()
            and record.epoch is _PROCESS_EPOCH,
            "closed fetch reader is absent, forked, or terminal",
        )
        CHANNEL._FETCH_STREAM_ASSERT(record.channel_session)
        return record

    def assert_reader(capability: Any) -> None:
        exact_reader(capability)

    def read_reader(
        capability: Any,
        basename: str,
        maximum: int,
    ) -> bytes:
        record = exact_reader(capability)
        _require(
            type(maximum) is int
            and 0 < maximum <= MATERIALIZER.CHUNK_SIZE_BYTES,
            "closed fetch reader chunk cap differs",
        )
        try:
            with record.lock:
                _require(
                    record.file_index < len(record.files),
                    "closed fetch reader has no remaining file",
                )
                expected_name, declared_size, declared_sha = record.files[
                    record.file_index
                ]
                _require(
                    basename == expected_name,
                    "closed fetch reader file order differs",
                )
                if record.file_remaining is None:
                    encoded_size = struct.unpack(
                        "!Q",
                        CHANNEL._FETCH_STREAM_READ_EXACT(
                            record.channel_session, 8,
                        ),
                    )[0]
                    _require(
                        str(encoded_size) == declared_size,
                        f"{basename} encoded size differs",
                    )
                    record.file_remaining = encoded_size
                    record.file_hasher = hashlib.sha256()
                _require(
                    type(record.file_remaining) is int
                    and record.file_remaining > 0,
                    f"{basename} stream state differs",
                )
                chunk = CHANNEL._FETCH_STREAM_READ_EXACT(
                    record.channel_session,
                    min(maximum, record.file_remaining),
                )
                record.file_hasher.update(chunk)
                record.file_remaining -= len(chunk)
                if record.file_remaining == 0:
                    _require(
                        record.file_hasher.hexdigest() == declared_sha,
                        f"{basename} streamed hash differs",
                    )
                    record.file_index += 1
                    record.file_remaining = None
                    record.file_hasher = None
                return chunk
        except BaseException:
            abandon_reader(capability)
            raise

    def finish_reader(capability: Any) -> str:
        record = exact_reader(capability)
        try:
            with record.lock:
                _require(
                    record.file_index == len(record.files)
                    and record.file_remaining is None,
                    "closed fetch reader files are incomplete",
                )
            trailer = CHANNEL._FETCH_STREAM_FINISH(record.channel_session)
            _require(
                trailer["bundle_sha256"] == record.bundle_sha256,
                "closed fetch reader terminal bundle hash differs",
            )
            with lock:
                _require(
                    reader_registry.get(capability._key) is record,
                    "closed fetch reader finish raced",
                )
                del reader_registry[capability._key]
            return trailer["bundle_sha256"]
        except BaseException:
            abandon_reader(capability)
            raise

    def abandon_reader(capability: Any) -> None:
        with lock:
            record = reader_registry.get(getattr(capability, "_key", -1))
            if type(record) is _ReaderRecord and record.capability is capability:
                del reader_registry[capability._key]
            else:
                return
        try:
            CHANNEL._FETCH_STREAM_ABANDON(record.channel_session)
        except (CHANNEL.SharedFixedSSHChannelError, OSError):
            pass

    def after_fork_child() -> None:
        nonlocal lock
        registry.clear()
        reader_registry.clear()
        lock = threading.RLock()

    return (
        issue,
        assert_current,
        project,
        consume,
        assert_reader,
        read_reader,
        finish_reader,
        abandon_reader,
        after_fork_child,
        install_binding_guard,
    )


(
    _CONTROLLER_ISSUE,
    _CONTROLLER_ASSERT,
    _CONTROLLER_PROJECT,
    _CONTROLLER_CONSUME,
    _READER_ASSERT,
    _READER_READ,
    _READER_FINISH,
    _READER_ABANDON,
    _CONTROLLER_FORK_CHILD,
    _CONTROLLER_INSTALL_BINDING_GUARD,
) = _build_controller_owner_entries()


def _acquire_controller_fetch_stream_for_tests_once(
    target_capability: MATERIALIZER.LocalFetchTargetCapability,
    operation: CHANNEL.FetchTerminalMinimumBundleOperation,
    response_descriptor: int,
    expected_lineage_projection: dict[str, Any],
    *,
    _test_token: object,
) -> ClosedDirectFetchStreamCapability:
    """Offline exact-codec seam pending the Q1 backend-owned authority."""
    _assert_module_binding()
    _require(_test_token is _TEST_TOKEN, "controller fetch acquisition test token differs")
    _require(type(target_capability) is MATERIALIZER.LocalFetchTargetCapability, "exact local target capability is required")
    _require(type(operation) is CHANNEL.FetchTerminalMinimumBundleOperation, "exact fetch operation is required")
    _require(type(response_descriptor) is int and response_descriptor >= 0, "fixed response descriptor differs")
    target_capability.assert_current()
    expected = LINEAGE.validate_lineage_projection(expected_lineage_projection)
    snapshot = CHANNEL._operation_snapshot(operation, CHANNEL.FetchTerminalMinimumBundleOperation, {"issued"})
    _require(type(snapshot.read_profile_raw) is bytes, "fetch operation read profile differs")
    profile = CHANNEL.load_read_profile(snapshot.read_profile_raw, snapshot.transport_profile_raw)
    deadline = time.monotonic() + int(profile["server_read"]["fetch"]["timeout_seconds"], 10)
    channel_session = None
    try:
        channel_session, outer_header = CHANNEL._FETCH_STREAM_BEGIN(
            response_descriptor, operation, deadline,
        )
        magic = CHANNEL._FETCH_STREAM_READ_EXACT(
            channel_session, len(BUNDLE_MAGIC),
        )
        _require(magic == BUNDLE_MAGIC, "terminal bundle magic differs")
        header_size = struct.unpack(
            "!I", CHANNEL._FETCH_STREAM_READ_EXACT(channel_session, 4),
        )[0]
        _require(
            0 < header_size <= MAX_HEADER_BYTES,
            "terminal bundle header size differs",
        )
        header_raw = CHANNEL._FETCH_STREAM_READ_EXACT(
            channel_session, header_size,
        )
        try:
            header = json.loads(header_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectFetchAcquisitionError(
                "terminal bundle header is malformed"
            ) from exc
        _require(
            canonical_bytes(header) == header_raw,
            "terminal bundle header is not canonical",
        )
        _exact(
            header,
            {
                "schema", "acquisition", "files", "file_count",
                "total_size_bytes", "authority",
            },
            "terminal bundle header",
        )
        acquisition = validate_acquisition_projection(header["acquisition"])
        _require(
            header["schema"] == BUNDLE_SCHEMA
            and header["files"] == acquisition["files"]
            and header["file_count"] == "5"
            and header["total_size_bytes"]
            == acquisition["total_size_bytes"]
            and header["authority"]
            == {
                "authorizes_effect": False,
                "qsub_calls": "0",
                "qdel_calls": "0",
            }
            and outer_header["total_size_bytes"]
            == str(_bundle_wire_size(acquisition)),
            "terminal bundle header, total, or authority differs",
        )
        files = tuple(
            (item["basename"], item["size_bytes"], item["sha256"])
            for item in acquisition["files"]
        )
    except CHANNEL.ControllerTransportUnknown as exc:
        raise DirectFetchTransportUnknown("fixed fetch response is unknown; no retry") from exc
    except BaseException:
        if channel_session is not None:
            CHANNEL._FETCH_STREAM_ABANDON(channel_session)
        raise
    try:
        _require(
            acquisition["lineage_id"] == expected["lineage_id"]
            and acquisition["lineage_projection_sha256"]
            == hashlib.sha256(LINEAGE.canonical_bytes(expected)).hexdigest()
            and acquisition["lineage_result_payload_sha256"] == expected["result_payload_sha256"]
            and acquisition["binding"] == expected["binding"]
            and acquisition["durable"] == expected["durable"]
            and acquisition["descriptor_identity"] == expected["descriptor_identity"],
            "remote live acquisition and expected lineage projection are spliced",
        )
        target = target_capability.portable_projection()
        target_fields = target["binding"]
        _require(
            target_fields["project"] == expected["binding"]["project"]
            and target_fields["attempt_id"] == expected["binding"]["attempt_id"]
            and target_fields["job_id"] == expected["binding"]["job_id"] == outer_header["job_id"]
            and target_fields["w5_receipt_sha256"] == expected["binding"]["remote_receipt_bytes_sha256"]
            and target_fields["read_profile_sha256"] == profile["read_profile_payload_sha256"]
            and acquisition["read_profile_payload_sha256"] == profile["read_profile_payload_sha256"]
            and acquisition["transport_profile_bytes_sha256"] == hashlib.sha256(snapshot.transport_profile_raw).hexdigest(),
            "target, W2/W5 lineage, read profile, job, or transport binding differs",
        )
        target_binding = target["target_binding_sha256"]
        projection = {
        "schema": STREAM_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "backend_kind": BACKEND_KIND,
        "stream_id": "",
        "target_binding_sha256": target_binding,
        "acquisition_id": acquisition["acquisition_id"],
        "acquisition_result_payload_sha256": acquisition["result_payload_sha256"],
        "lineage_id": expected["lineage_id"],
        "operation_id": outer_header["operation_id"],
        "read_profile_payload_sha256": profile["read_profile_payload_sha256"],
        "bundle_sha256": outer_header["bundle_sha256"],
        "files": copy.deepcopy(acquisition["files"]),
        "file_count": "5",
        "total_size_bytes": acquisition["total_size_bytes"],
        "authority": {
            "authorizes_effect": False,
            "portable_projection_authorizes_stream": False,
            "remote_fetch_acquired": True,
            "closed_stream_owner": True,
            "production_integration": False,
            "required_production_predecessor": REQUIRED_PRODUCTION_PREDECESSOR,
            "qsub_calls": "0",
            "qdel_calls": "0",
            "automatic_retry": False,
            "single_use": True,
        },
        "stream_projection_sha256": "",
        }
        projection["stream_id"] = "direct-closed-fetch-stream-" + digest({
        "target_binding_sha256": target_binding,
        "acquisition_result_payload_sha256": acquisition["result_payload_sha256"],
        "operation_id": outer_header["operation_id"],
        "bundle_sha256": projection["bundle_sha256"],
        })
        projection["stream_projection_sha256"] = digest(projection)
        return _CONTROLLER_ISSUE(
            projection, channel_session, files, target_binding,
        )
    except BaseException:
        CHANNEL._FETCH_STREAM_ABANDON(channel_session)
        raise


def _consume_for_materializer_once(
    capability: ClosedDirectFetchStreamCapability,
    target_binding_sha256: str,
) -> tuple[
    dict[str, Any],
    ClosedDirectFetchReaderCapability,
]:
    """Fixed T4 transition to one sequential reader capability."""
    return _CONTROLLER_CONSUME(capability, target_binding_sha256)


def _assert_materializer_reader_current(
    capability: ClosedDirectFetchReaderCapability,
) -> None:
    _READER_ASSERT(capability)


def _read_for_materializer_once(
    capability: ClosedDirectFetchReaderCapability,
    basename: str,
    maximum: int,
) -> bytes:
    try:
        return _READER_READ(capability, basename, maximum)
    except CHANNEL.ControllerTransportUnknown as exc:
        raise DirectFetchTransportUnknown(
            "fixed fetch stream is unknown; no retry"
        ) from exc


def _finish_for_materializer_once(
    capability: ClosedDirectFetchReaderCapability,
) -> str:
    try:
        return _READER_FINISH(capability)
    except CHANNEL.ControllerTransportUnknown as exc:
        raise DirectFetchTransportUnknown(
            "fixed fetch trailer is unknown; no retry"
        ) from exc


def _abandon_materializer_reader_once(
    capability: ClosedDirectFetchReaderCapability,
) -> None:
    _READER_ABANDON(capability)


def _after_fork_child() -> None:
    global _LOCK, _PROCESS_EPOCH
    _SERVER_FORK_CHILD()
    _CONTROLLER_FORK_CHILD()
    _OWNER_REGISTRY.clear()
    _PROCESS_EPOCH = object()
    _LOCK = threading.RLock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


@dataclass(frozen=True, slots=True)
class _ModuleBinding:
    module: types.ModuleType
    source: _SourceSnapshot
    lineage_module: types.ModuleType
    channel_module: types.ModuleType
    materializer_module: types.ModuleType
    lineage_source: _SourceSnapshot
    channel_source: _SourceSnapshot
    materializer_source: _SourceSnapshot
    entries: tuple[object, ...]
    effect_helpers: tuple[object, ...]
    os_primitives: tuple[object, ...]
    constants: tuple[object, ...]
    issued_types: tuple[type, ...]


def _capture_module_binding() -> _ModuleBinding:
    module = sys.modules.get(MODULE_NAME)
    _require(type(module) is types.ModuleType and __name__ == MODULE_NAME, "canonical acquisition module is unavailable")
    issued = (
        DirectFetchAcquisitionOwner,
        DirectServerFetchAcquisitionCapability,
        ClosedDirectFetchStreamCapability,
        ClosedDirectFetchReaderCapability,
    )
    return _ModuleBinding(
        module,
        _source_snapshot(Path(__file__).resolve()),
        LINEAGE,
        CHANNEL,
        MATERIALIZER,
        _source_snapshot(Path(LINEAGE.__file__).resolve()),
        _source_snapshot(Path(CHANNEL.__file__).resolve()),
        _source_snapshot(Path(MATERIALIZER.__file__).resolve()),
        (
            _assert_module_binding,
            _new_owner,
            _issue_server_fetch_acquisition_for_tests_once,
            _accept_lineage_handoff_once,
            _build_terminal_minimum_response_for_tests_once,
            _write_terminal_minimum_response_for_tests_once,
            _acquire_controller_fetch_stream_for_tests_once,
            _consume_for_materializer_once,
            _assert_materializer_reader_current,
            _read_for_materializer_once,
            _finish_for_materializer_once,
            _abandon_materializer_reader_once,
            validate_acquisition_projection,
            _SERVER_ISSUE,
            _SERVER_ASSERT,
            _SERVER_PROJECT,
            _SERVER_BUILD_RESPONSE,
            _SERVER_WRITE_RESPONSE,
            _SERVER_ABANDON,
            _SERVER_FORK_CHILD,
            _SERVER_INSTALL_BINDING_GUARD,
            _CONTROLLER_ISSUE,
            _CONTROLLER_ASSERT,
            _CONTROLLER_PROJECT,
            _CONTROLLER_CONSUME,
            _READER_ASSERT,
            _READER_READ,
            _READER_FINISH,
            _READER_ABANDON,
            _CONTROLLER_FORK_CHILD,
            _CONTROLLER_INSTALL_BINDING_GUARD,
        ),
        (
            _require,
            canonical_bytes,
            digest,
            _sha,
            _exact,
            _decimal,
            _source_snapshot,
            _file_identity,
            _identity_sha256,
            _read_current_file,
            _iter_current_file_chunks,
            _observe_file,
            _close_descriptors,
            _commitment_update,
            _server_record_commitment,
            _bundle_header_raw,
            _bundle_wire_size,
            _bundle_components,
            _bundle_bytes,
            _validate_fetch_request,
            _parse_bundle,
            validate_acquisition_projection,
            validate_closed_stream_projection,
            _controller_record_commitment,
        ),
        (
            os.open,
            os.fstat,
            os.stat,
            os.read,
            os.lseek,
            os.close,
            os.geteuid,
            time.monotonic,
            fcntl.fcntl,
            hashlib.sha256,
            json.loads,
            struct.pack,
            struct.unpack,
        ),
        (
            BUNDLE_MAGIC,
            MAX_HEADER_BYTES,
            MAX_BUFFERED_TEST_BUNDLE_BYTES,
            REQUIRED_PRODUCTION_PREDECESSOR,
            tuple(MATERIALIZER.ARTIFACT_SPECS),
            tuple(MATERIALIZER.ARTIFACT_BASENAMES),
            MATERIALIZER.CHUNK_SIZE_BYTES,
            os.O_RDONLY,
            getattr(os, "O_NONBLOCK", 0),
            getattr(os, "O_NOFOLLOW", 0),
            getattr(os, "O_CLOEXEC", 0),
        ),
        issued,
    )


_MODULE_BINDING: _ModuleBinding | None = None


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    exact = (
        type(binding) is _ModuleBinding
        and sys.modules.get(MODULE_NAME) is binding.module
        and sys.modules.get(LINEAGE.__name__) is binding.lineage_module
        and sys.modules.get(CHANNEL.__name__) is binding.channel_module
        and sys.modules.get(MATERIALIZER.__name__) is binding.materializer_module
        and not hasattr(binding.module, "_SERVER_REGISTRY")
        and not hasattr(binding.module, "_server_record")
        and not hasattr(binding.module, "_CONTROLLER_REGISTRY")
        and not hasattr(binding.module, "_controller_record")
        and binding.entries == (
            _assert_module_binding,
            _new_owner,
            _issue_server_fetch_acquisition_for_tests_once,
            _accept_lineage_handoff_once,
            _build_terminal_minimum_response_for_tests_once,
            _write_terminal_minimum_response_for_tests_once,
            _acquire_controller_fetch_stream_for_tests_once,
            _consume_for_materializer_once,
            _assert_materializer_reader_current,
            _read_for_materializer_once,
            _finish_for_materializer_once,
            _abandon_materializer_reader_once,
            validate_acquisition_projection,
            _SERVER_ISSUE,
            _SERVER_ASSERT,
            _SERVER_PROJECT,
            _SERVER_BUILD_RESPONSE,
            _SERVER_WRITE_RESPONSE,
            _SERVER_ABANDON,
            _SERVER_FORK_CHILD,
            _SERVER_INSTALL_BINDING_GUARD,
            _CONTROLLER_ISSUE,
            _CONTROLLER_ASSERT,
            _CONTROLLER_PROJECT,
            _CONTROLLER_CONSUME,
            _READER_ASSERT,
            _READER_READ,
            _READER_FINISH,
            _READER_ABANDON,
            _CONTROLLER_FORK_CHILD,
            _CONTROLLER_INSTALL_BINDING_GUARD,
        )
        and binding.effect_helpers == (
            _require,
            canonical_bytes,
            digest,
            _sha,
            _exact,
            _decimal,
            _source_snapshot,
            _file_identity,
            _identity_sha256,
            _read_current_file,
            _iter_current_file_chunks,
            _observe_file,
            _close_descriptors,
            _commitment_update,
            _server_record_commitment,
            _bundle_header_raw,
            _bundle_wire_size,
            _bundle_components,
            _bundle_bytes,
            _validate_fetch_request,
            _parse_bundle,
            validate_acquisition_projection,
            validate_closed_stream_projection,
            _controller_record_commitment,
        )
        and binding.os_primitives == (
            os.open,
            os.fstat,
            os.stat,
            os.read,
            os.lseek,
            os.close,
            os.geteuid,
            time.monotonic,
            fcntl.fcntl,
            hashlib.sha256,
            json.loads,
            struct.pack,
            struct.unpack,
        )
        and binding.constants == (
            BUNDLE_MAGIC,
            MAX_HEADER_BYTES,
            MAX_BUFFERED_TEST_BUNDLE_BYTES,
            REQUIRED_PRODUCTION_PREDECESSOR,
            tuple(MATERIALIZER.ARTIFACT_SPECS),
            tuple(MATERIALIZER.ARTIFACT_BASENAMES),
            MATERIALIZER.CHUNK_SIZE_BYTES,
            os.O_RDONLY,
            getattr(os, "O_NONBLOCK", 0),
            getattr(os, "O_NOFOLLOW", 0),
            getattr(os, "O_CLOEXEC", 0),
        )
        and _source_snapshot(Path(__file__).resolve()) == binding.source
        and _source_snapshot(Path(LINEAGE.__file__).resolve()) == binding.lineage_source
        and _source_snapshot(Path(CHANNEL.__file__).resolve()) == binding.channel_source
        and _source_snapshot(Path(MATERIALIZER.__file__).resolve()) == binding.materializer_source
    )
    if not exact:
        raise DirectFetchAcquisitionError(
            "fetch acquisition module, source, or predecessor binding differs"
        )
    LINEAGE._assert_module_binding()
    CHANNEL._assert_production_binding()
    MATERIALIZER._assert_owner_binding()
    for issued_type in binding.issued_types:
        if getattr(binding.module, issued_type.__name__, None) is not issued_type:
            raise DirectFetchAcquisitionError(
                "fetch acquisition issued type differs"
            )


_MODULE_BINDING = _capture_module_binding()
_SERVER_INSTALL_BINDING_GUARD(_assert_module_binding)
_CONTROLLER_INSTALL_BINDING_GUARD(_assert_module_binding)


__all__ = [
    "DirectFetchAcquisitionError",
    "DirectFetchTransportUnknown",
    "DirectFetchAcquisitionOwner",
    "DirectServerFetchAcquisitionCapability",
    "ClosedDirectFetchStreamCapability",
    "validate_acquisition_projection",
]
