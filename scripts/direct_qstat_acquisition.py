#!/usr/bin/env python3
"""Exact read-only qstat acquisition and final scheduler-evidence owner.

This Q1 module is deliberately narrow.  The controller accepts reviewed W5
artifacts, a portable W5 receipt and the exact read profile; no public entry
accepts a job id, command, path, host, argv, environment or callback.  The
server re-observes the existing project through the L1 owner, consumes its
exact same-process read capability, and derives the qstat job id only from the
resulting live lease.  Portable documents never become authority.

Production-shaped entrypoints exist, but repository validation uses only the
explicit fake-local owners below.  Nothing in this module authorizes a live
SSH/PBS/Gaussian action, retry, qsub, qdel, fetch, cleanup or deletion.
"""

from __future__ import annotations

import base64
import binascii
import collections
import copy
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import select
import signal
import stat
import struct
import sys
import threading
import time
import types
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple


MODULE_NAME = "direct_qstat_acquisition"
_EXECUTED_SOURCE_SHA256 = globals().get("__reviewed_source_sha256__")
if _EXECUTED_SOURCE_SHA256 is None:
    with open(__file__, "rb") as _source_handle:
        _EXECUTED_SOURCE_SHA256 = hashlib.sha256(_source_handle.read()).hexdigest()

# A fixed owner-derived scripts directory is the only bootstrap path.  It is
# removed immediately after importing the reviewed predecessor owners.
_SCRIPTS_DIRECTORY = str(Path(__file__).resolve().parent)
_BOOTSTRAP_INSERTED = _SCRIPTS_DIRECTORY not in sys.path
if _BOOTSTRAP_INSERTED:
    sys.path.insert(0, _SCRIPTS_DIRECTORY)
try:
    import direct_existing_job_lineage as LINEAGE
    import direct_one_hop_transport as W5
    import direct_read_only_evidence as EVIDENCE
    import direct_reviewed_read_profile as READ_PROFILE
    import direct_shared_fixed_ssh_channel as CHANNEL
    import direct_trusted_session_composition as SESSION
finally:
    if _BOOTSTRAP_INSERTED:
        try:
            sys.path.remove(_SCRIPTS_DIRECTORY)
        except ValueError:
            pass


REQUEST_SCHEMA = "auto-g16-direct-qstat-acquisition-request/1"
RESPONSE_SCHEMA = "auto-g16-direct-qstat-acquisition-response/1"
ACQUISITION_SCHEMA = "gaussian-direct-qstat-acquisition/1"
INSPECTION_SCHEMA = "gaussian-job-inspection/3"
OWNER = "auto-g16-direct-qstat-acquisition-owner"
OWNER_VERSION = "direct-qstat-acquisition-owner/1"
FINAL_OWNER = "auto-g16-direct-final-scheduler-inspection-owner"
FINAL_OWNER_VERSION = "direct-final-scheduler-inspection-owner/1"
QSTAT_EXECUTABLE = "/usr/bin/qstat"
QSTAT_ARGV_PREFIX = (QSTAT_EXECUTABLE, "-f")
QSTAT_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C"}
MAX_QSTAT_STREAM_BYTES = 64 * 1024
MAX_QSTAT_COMBINED_BYTES = 64 * 1024
QSTAT_CHILD_RETIRE_GRACE_SECONDS = 2.5
MAX_REQUEST_BYTES = CHANNEL.MAX_CONTROL_FRAME_BYTES
MAX_RESPONSE_BYTES = 512 * 1024
MAX_FRESH_AGE_SECONDS = EVIDENCE.MAX_FRESH_AGE_SECONDS
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ACQUISITION_ID_RE = re.compile(r"^direct-qstat-acquisition-[a-f0-9]{64}$")
INSPECTION_ID_RE = re.compile(r"^direct-scheduler-inspection-[a-f0-9]{64}$")
DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]{0,19})$")
SIGNED_DECIMAL_RE = re.compile(r"^(?:0|-?[1-9][0-9]{0,9})$")
TIMESTAMP_RE = EVIDENCE.TIMESTAMP_RE
AUTHORITY = {
    "authorizes_effect": False,
    "scientific_acceptance": False,
    "gaussian_completion": False,
    "qsub": False,
    "qdel": False,
    "delete": False,
    "cleanup": False,
    "retry": False,
    "fetch": False,
    "materialize": False,
}
FINAL_AUTHORITY = {
    **AUTHORITY,
    "scheduler_evidence_only": True,
}


class DirectQstatAcquisitionError(ValueError):
    """The exact qstat acquisition or final evidence failed closed."""


class DirectQstatTransportUnknown(RuntimeError):
    """The read-only transport outcome is unknown and must not be retried."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectQstatAcquisitionError(message)


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
        raise DirectQstatAcquisitionError("value is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _sha(value: Any, label: str, *, allow_empty: bool = False) -> str:
    _require(
        type(value) is str
        and SHA_RE.fullmatch(value) is not None
        and value != ZERO_SHA,
        f"{label} differs",
    )
    if not allow_empty:
        _require(value != hashlib.sha256(b"").hexdigest(), f"{label} binds empty bytes")
    return value


def _decimal(value: Any, label: str, *, signed: bool = False) -> int:
    pattern = SIGNED_DECIMAL_RE if signed else DECIMAL_RE
    _require(type(value) is str and pattern.fullmatch(value) is not None, f"{label} differs")
    return int(value, 10)


def _timestamp(value: Any, label: str) -> datetime:
    _require(type(value) is str and TIMESTAMP_RE.fullmatch(value) is not None, f"{label} differs")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DirectQstatAcquisitionError(f"{label} differs") from exc
    _require(parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == value, f"{label} differs")
    return parsed


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _freshness(requested_at: str, collected_at: str, received_at: str) -> tuple[str, str | None]:
    requested = _timestamp(requested_at, "requested_at")
    collected = _timestamp(collected_at, "collected_at")
    received = _timestamp(received_at, "received_at")
    if not requested <= collected <= received:
        return "unknown", None
    elapsed = received - collected
    rounded = elapsed.days * 86400 + elapsed.seconds + (1 if elapsed.microseconds else 0)
    return (
        "fresh" if elapsed <= timedelta(seconds=MAX_FRESH_AGE_SECONDS) else "stale",
        str(rounded),
    )


def _b64(raw: bytes) -> str:
    _require(type(raw) is bytes, "base64 source differs")
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: Any, label: str, maximum: int) -> bytes:
    _require(type(value) is str and len(value) <= maximum * 2 + 16, f"{label} differs")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DirectQstatAcquisitionError(f"{label} differs") from exc
    _require(len(raw) <= maximum and _b64(raw) == value, f"{label} differs")
    return raw


def _canonical_frame(document: dict[str, Any], maximum: int) -> bytes:
    payload = canonical_bytes(document)
    _require(0 < len(payload) <= maximum, "qstat frame size differs")
    return struct.pack("!I", len(payload)) + payload


def _decode_canonical_frame(frame: bytes, maximum: int, label: str) -> dict[str, Any]:
    _require(type(frame) is bytes and len(frame) >= 5, f"{label} differs")
    size = struct.unpack("!I", frame[:4])[0]
    _require(0 < size <= maximum and len(frame) == size + 4, f"{label} size differs")
    try:
        value = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectQstatAcquisitionError(f"{label} is malformed") from exc
    _require(type(value) is dict and canonical_bytes(value) == frame[4:], f"{label} is not canonical")
    return value


def _artifact_hashes(artifacts: SESSION.DirectServerSessionArtifacts) -> dict[str, str]:
    _require(type(artifacts) is SESSION.DirectServerSessionArtifacts, "exact reviewed artifacts are required")
    return {
        name: hashlib.sha256(getattr(artifacts, name)).hexdigest()
        for name in artifacts.__dataclass_fields__
    }


def _artifacts_document(artifacts: SESSION.DirectServerSessionArtifacts) -> dict[str, str]:
    _artifact_hashes(artifacts)
    return {name: _b64(getattr(artifacts, name)) for name in artifacts.__dataclass_fields__}


def _artifacts_from_document(value: Any) -> SESSION.DirectServerSessionArtifacts:
    fields = set(SESSION.DirectServerSessionArtifacts.__dataclass_fields__)
    document = _exact(value, fields, "reviewed artifact bundle")
    decoded = {
        name: _unb64(document[name], f"reviewed artifact {name}", W5.MAX_FRAME_BYTES)
        for name in sorted(fields)
    }
    return SESSION.DirectServerSessionArtifacts(**decoded)


class _ControllerQueryJoin:
    __slots__ = ("request_id", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("controller query joins are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("controller query joins are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("controller query joins are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("controller query joins are not serializable")


class _ExactLineageConsumerJoin:
    __slots__ = ("lineage_id", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("lineage consumer joins are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("lineage consumer joins are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("lineage consumer joins are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("lineage consumer joins are not serializable")


class _ExactQueryIssuanceJoin:
    __slots__ = ("issuance_id", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("query issuance joins are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("query issuance joins are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("query issuance joins are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("query issuance joins are not serializable")


class _ControllerJoinRecord(NamedTuple):
    pid: int
    status: str
    operation: CHANNEL.QueryExactJobOperation
    request_frame: bytes
    request_id: str
    seal: object


class _LineageJoinRecord(NamedTuple):
    pid: int
    status: str
    capability: LINEAGE.DirectSubmittedJobReadCapability
    lineage_id: str
    seal: object


class _IssuanceJoinRecord(NamedTuple):
    pid: int
    status: str
    issuance_id: str
    job_id: str
    transport_profile_bytes_sha256: str
    read_profile_bytes_sha256: str
    profile_capability_id: str
    receipt_bytes_sha256: str
    seal: object


def _make_join_owners() -> tuple[Any, ...]:
    controller_registry: weakref.WeakKeyDictionary[_ControllerQueryJoin, _ControllerJoinRecord] = weakref.WeakKeyDictionary()
    lineage_registry: weakref.WeakKeyDictionary[_ExactLineageConsumerJoin, _LineageJoinRecord] = weakref.WeakKeyDictionary()
    issuance_registry: weakref.WeakKeyDictionary[_ExactQueryIssuanceJoin, _IssuanceJoinRecord] = weakref.WeakKeyDictionary()
    lock = threading.RLock()
    controller_seal = object()
    lineage_seal = object()
    issuance_seal = object()

    def issue_issuance(
        job_id: str,
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
        profile_capability_id: str,
        receipt_bytes_sha256: str,
    ) -> _ExactQueryIssuanceJoin:
        nonlocal issuance_seal
        _require(CHANNEL.JOB_ID_RE.fullmatch(job_id) is not None, "query issuance job id differs")
        transport_sha = hashlib.sha256(transport_profile_raw).hexdigest()
        read_sha = hashlib.sha256(read_profile_raw).hexdigest()
        _sha(receipt_bytes_sha256, "query issuance receipt bytes")
        _require(
            re.fullmatch(r"direct-reviewed-read-profile-[a-f0-9]{64}", profile_capability_id) is not None,
            "query issuance profile capability differs",
        )
        issuance_id = "direct-qstat-query-issuance-" + digest(
            {
                "schema": "auto-g16-direct-qstat-query-issuance-id/1",
                "job_id": job_id,
                "transport_profile_bytes_sha256": transport_sha,
                "read_profile_bytes_sha256": read_sha,
                "profile_capability_id": profile_capability_id,
                "receipt_bytes_sha256": receipt_bytes_sha256,
            }
        )
        join = object.__new__(_ExactQueryIssuanceJoin)
        join.issuance_id = issuance_id
        join._seal = issuance_seal
        with lock:
            issuance_registry[join] = _IssuanceJoinRecord(
                os.getpid(), "issued", issuance_id, job_id,
                transport_sha, read_sha, profile_capability_id,
                receipt_bytes_sha256, issuance_seal,
            )
        return join

    def assert_issuance(
        join: object,
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
    ) -> str:
        with lock:
            record = issuance_registry.get(join) if type(join) is _ExactQueryIssuanceJoin else None
            valid = (
                type(record) is _IssuanceJoinRecord
                and record.pid == os.getpid()
                and record.status == "issued"
                and record.issuance_id == getattr(join, "issuance_id", None)
                and record.transport_profile_bytes_sha256 == hashlib.sha256(transport_profile_raw).hexdigest()
                and record.read_profile_bytes_sha256 == hashlib.sha256(read_profile_raw).hexdigest()
                and record.seal is issuance_seal is getattr(join, "_seal", None)
            )
            if not valid:
                if join in issuance_registry:
                    del issuance_registry[join]
                raise DirectQstatAcquisitionError(
                    "query issuance join is foreign, forged, forked, spliced, or terminal"
                )
            issuance_registry[join] = record._replace(status="terminal")
            job_id = record.job_id
            del issuance_registry[join]
            return job_id

    def issue_controller(
        operation: CHANNEL.QueryExactJobOperation,
        request_frame: bytes,
    ) -> _ControllerQueryJoin:
        nonlocal controller_seal
        _require(type(operation) is CHANNEL.QueryExactJobOperation, "exact query operation is required")
        operation.assert_owner_sealed()
        request = validate_request(_decode_canonical_frame(request_frame, MAX_REQUEST_BYTES, "qstat request frame"))
        _require(
            request["operation_id"] == operation.operation_id
            and request["expected_job_id"] == operation.portable_projection()["job_id"],
            "query operation and request differ",
        )
        join = object.__new__(_ControllerQueryJoin)
        join.request_id = request["request_id"]
        join._seal = controller_seal
        with lock:
            controller_registry[join] = _ControllerJoinRecord(
                os.getpid(), "issued", operation, bytes(request_frame),
                join.request_id, controller_seal,
            )
        return join

    def assert_controller(join: object, operation: object, request_frame: bytes) -> None:
        with lock:
            record = controller_registry.get(join) if type(join) is _ControllerQueryJoin else None
            valid = (
                type(record) is _ControllerJoinRecord
                and record.pid == os.getpid()
                and record.status == "issued"
                and record.operation is operation
                and record.request_frame == request_frame
                and record.request_id == getattr(join, "request_id", None)
                and record.seal is controller_seal is getattr(join, "_seal", None)
            )
            if not valid:
                if join in controller_registry:
                    del controller_registry[join]
                raise DirectQstatAcquisitionError(
                    "controller query join is foreign, forged, forked, spliced, or terminal"
                )
            controller_registry[join] = record._replace(status="terminal")
            del controller_registry[join]

    def issue_lineage(
        capability: LINEAGE.DirectSubmittedJobReadCapability,
    ) -> _ExactLineageConsumerJoin:
        nonlocal lineage_seal
        _require(
            type(capability) is LINEAGE.DirectSubmittedJobReadCapability,
            "exact L1 read capability is required",
        )
        capability.assert_current()
        join = object.__new__(_ExactLineageConsumerJoin)
        join.lineage_id = capability.lineage_id
        join._seal = lineage_seal
        with lock:
            lineage_registry[join] = _LineageJoinRecord(
                os.getpid(), "issued", capability, capability.lineage_id,
                lineage_seal,
            )
        return join

    def assert_lineage(join: object, capability: object) -> None:
        with lock:
            record = lineage_registry.get(join) if type(join) is _ExactLineageConsumerJoin else None
            valid = (
                type(record) is _LineageJoinRecord
                and record.pid == os.getpid()
                and record.status == "issued"
                and record.capability is capability
                and record.lineage_id == getattr(capability, "lineage_id", None)
                and record.lineage_id == getattr(join, "lineage_id", None)
                and record.seal is lineage_seal is getattr(join, "_seal", None)
            )
            if not valid:
                if join in lineage_registry:
                    del lineage_registry[join]
                raise DirectQstatAcquisitionError(
                    "lineage consumer join is foreign, forged, forked, spliced, or terminal"
                )
            lineage_registry[join] = record._replace(status="terminal")
            del lineage_registry[join]

    def after_fork() -> None:
        nonlocal lock, controller_seal, lineage_seal, issuance_seal
        controller_registry.clear()
        lineage_registry.clear()
        issuance_registry.clear()
        lock = threading.RLock()
        controller_seal = object()
        lineage_seal = object()
        issuance_seal = object()

    return (
        issue_issuance, assert_issuance, issue_controller, assert_controller,
        issue_lineage, assert_lineage, after_fork,
    )


(
    _ISSUE_QUERY_ISSUANCE_JOIN,
    _ASSERT_QUERY_ISSUANCE_JOIN,
    _ISSUE_CONTROLLER_JOIN,
    _ASSERT_CONTROLLER_JOIN,
    _ISSUE_LINEAGE_JOIN,
    _ASSERT_LINEAGE_JOIN,
    _CLEAR_JOINS_AFTER_FORK,
) = _make_join_owners()


def _assert_shared_channel_query_issuance_authority(
    join: _ExactQueryIssuanceJoin,
    transport_profile_raw: bytes,
    read_profile_raw: bytes,
) -> str:
    return _ASSERT_QUERY_ISSUANCE_JOIN(join, transport_profile_raw, read_profile_raw)


def _assert_shared_channel_query_authority(
    join: _ControllerQueryJoin,
    operation: CHANNEL.QueryExactJobOperation,
    request_frame: bytes,
) -> None:
    _ASSERT_CONTROLLER_JOIN(join, operation, request_frame)


def _assert_exact_lineage_consumer_join(
    join: _ExactLineageConsumerJoin,
    capability: LINEAGE.DirectSubmittedJobReadCapability,
) -> None:
    _ASSERT_LINEAGE_JOIN(join, capability)


def _request_id(
    artifact_sha256: dict[str, str],
    receipt_raw: bytes,
    read_profile_raw: bytes,
    operation_id: str,
    expected_job_id: str,
) -> str:
    return "direct-qstat-request-" + digest(
        {
            "schema": "auto-g16-direct-qstat-request-id/1",
            "artifact_sha256": artifact_sha256,
            "portable_receipt_bytes_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "read_profile_bytes_sha256": hashlib.sha256(read_profile_raw).hexdigest(),
            "operation_id": operation_id,
            "expected_job_id": expected_job_id,
        }
    )


def build_request(
    operation: CHANNEL.QueryExactJobOperation,
    portable_receipt_bytes: bytes,
    artifacts: SESSION.DirectServerSessionArtifacts,
    read_profile_raw: bytes,
    read_profile_capability_projection: dict[str, Any],
) -> dict[str, Any]:
    _assert_module_binding()
    _require(type(operation) is CHANNEL.QueryExactJobOperation, "exact query operation is required")
    operation.assert_owner_sealed()
    receipt = W5.validate_submission_receipt(
        json.loads(portable_receipt_bytes.decode("utf-8"))
    )
    _require(W5.canonical_bytes(receipt) == portable_receipt_bytes, "portable W5 receipt bytes differ")
    artifact_sha256 = _artifact_hashes(artifacts)
    read_profile = CHANNEL.load_read_profile(read_profile_raw, artifacts.transport_profile)
    reviewed_profile = READ_PROFILE.validate_capability_projection(
        read_profile_capability_projection
    )
    _require(
        reviewed_profile["profile_bytes_sha256"] == hashlib.sha256(read_profile_raw).hexdigest()
        and reviewed_profile["profile_payload_sha256"] == read_profile["read_profile_payload_sha256"]
        and reviewed_profile["transport_profile_bytes_sha256"]
        == hashlib.sha256(artifacts.transport_profile).hexdigest(),
        "controller reviewed read-profile capability differs",
    )
    expected_job_id = receipt["qsub"]["job_id"]
    _require(
        operation.portable_projection()["job_id"] == expected_job_id,
        "query operation job binding differs",
    )
    request_id = _request_id(
        artifact_sha256,
        portable_receipt_bytes,
        read_profile_raw,
        operation.operation_id,
        expected_job_id,
    )
    document = {
        "schema": REQUEST_SCHEMA,
        "protocol": CHANNEL.READ_PROTOCOL,
        "operation": "acquire_exact_qstat",
        "operation_id": operation.operation_id,
        "request_id": request_id,
        "expected_job_id": expected_job_id,
        "portable_receipt_base64": _b64(portable_receipt_bytes),
        "portable_receipt_bytes_sha256": hashlib.sha256(portable_receipt_bytes).hexdigest(),
        "artifacts": _artifacts_document(artifacts),
        "artifact_sha256": artifact_sha256,
        "read_profile_base64": _b64(read_profile_raw),
        "read_profile_bytes_sha256": hashlib.sha256(read_profile_raw).hexdigest(),
        "read_profile_payload_sha256": read_profile["read_profile_payload_sha256"],
        "controller_read_profile_capability": copy.deepcopy(reviewed_profile),
        "authority": copy.deepcopy(AUTHORITY),
        "request_payload_sha256": "",
    }
    document["request_payload_sha256"] = digest(document)
    return validate_request(document)


def validate_request(value: Any) -> dict[str, Any]:
    _assert_module_binding()
    document = _exact(
        copy.deepcopy(value),
        {
            "schema", "protocol", "operation", "operation_id", "request_id",
            "expected_job_id", "portable_receipt_base64",
            "portable_receipt_bytes_sha256", "artifacts", "artifact_sha256",
            "read_profile_base64", "read_profile_bytes_sha256",
            "read_profile_payload_sha256", "controller_read_profile_capability",
            "authority", "request_payload_sha256",
        },
        "qstat acquisition request",
    )
    _require(
        document["schema"] == REQUEST_SCHEMA
        and document["protocol"] == CHANNEL.READ_PROTOCOL
        and document["operation"] == "acquire_exact_qstat"
        and CHANNEL.OPERATION_ID_RE.fullmatch(document["operation_id"]) is not None
        and re.fullmatch(r"direct-qstat-request-[a-f0-9]{64}", document["request_id"]) is not None
        and CHANNEL.JOB_ID_RE.fullmatch(document["expected_job_id"]) is not None
        and document["authority"] == AUTHORITY,
        "qstat acquisition request constants differ",
    )
    receipt_raw = _unb64(document["portable_receipt_base64"], "portable W5 receipt", W5.MAX_FRAME_BYTES)
    _sha(document["portable_receipt_bytes_sha256"], "portable receipt bytes")
    _require(
        hashlib.sha256(receipt_raw).hexdigest() == document["portable_receipt_bytes_sha256"],
        "portable receipt byte hash differs",
    )
    artifacts = _artifacts_from_document(document["artifacts"])
    expected_artifact_hashes = _artifact_hashes(artifacts)
    _require(document["artifact_sha256"] == expected_artifact_hashes, "reviewed artifact hashes differ")
    read_profile_raw = _unb64(document["read_profile_base64"], "read profile", CHANNEL.MAX_PROFILE_BYTES)
    _require(
        hashlib.sha256(read_profile_raw).hexdigest()
        == _sha(document["read_profile_bytes_sha256"], "read profile bytes"),
        "read profile byte hash differs",
    )
    read_profile = CHANNEL.load_read_profile(read_profile_raw, artifacts.transport_profile)
    reviewed_profile = READ_PROFILE.validate_capability_projection(
        document["controller_read_profile_capability"]
    )
    _require(
        read_profile["read_profile_payload_sha256"]
        == document["read_profile_payload_sha256"]
        and reviewed_profile["profile_bytes_sha256"]
        == document["read_profile_bytes_sha256"]
        and reviewed_profile["profile_payload_sha256"]
        == document["read_profile_payload_sha256"]
        and reviewed_profile["transport_profile_bytes_sha256"]
        == hashlib.sha256(artifacts.transport_profile).hexdigest(),
        "read profile payload hash differs",
    )
    receipt = W5.validate_submission_receipt(json.loads(receipt_raw.decode("utf-8")))
    _require(
        W5.canonical_bytes(receipt) == receipt_raw
        and receipt["qsub"]["job_id"] == document["expected_job_id"],
        "portable receipt job binding differs",
    )
    expected_request_id = _request_id(
        expected_artifact_hashes,
        receipt_raw,
        read_profile_raw,
        document["operation_id"],
        document["expected_job_id"],
    )
    _require(document["request_id"] == expected_request_id, "qstat request id differs")
    supplied = _sha(document["request_payload_sha256"], "qstat request payload")
    _require(
        supplied == digest({**document, "request_payload_sha256": ""}),
        "qstat request payload hash differs",
    )
    return document


@dataclasses.dataclass(frozen=True, slots=True)
class _QstatObservation:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    eof_complete: bool
    child_exit_code: int | None
    requested_at: str
    collected_at: str
    executable_identity_sha256: str
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _require(type(self.stdout) is bytes and type(self.stderr) is bytes, "qstat observation streams differ")
        _require(len(self.stdout) <= MAX_QSTAT_STREAM_BYTES, "qstat stdout exceeds 64 KiB")
        _require(len(self.stderr) <= MAX_QSTAT_STREAM_BYTES, "qstat stderr exceeds 64 KiB")
        _require(
            len(self.stdout) + len(self.stderr) <= MAX_QSTAT_COMBINED_BYTES,
            "qstat combined streams exceed 64 KiB",
        )
        _require(type(self.timed_out) is bool and type(self.eof_complete) is bool, "qstat observation flags differ")
        _require(
            self.returncode is None or type(self.returncode) is int,
            "qstat returncode differs",
        )
        _require(
            self.child_exit_code is None or type(self.child_exit_code) is int,
            "qstat child exit differs",
        )
        _timestamp(self.requested_at, "qstat requested_at")
        _timestamp(self.collected_at, "qstat collected_at")
        _sha(self.executable_identity_sha256, "qstat executable identity")
        _require(
            self.failure_reason
            in (
                {None, "child_exit_ambiguous"}
                | set(EVIDENCE.UNKNOWN_REASONS)
            ),
            "qstat failure reason differs",
        )


def _normalize_observation(
    job_id: str,
    project: str,
    observation: _QstatObservation,
) -> _QstatObservation:
    _require(type(observation) is _QstatObservation, "exact qstat observation is required")
    low_level = {"timeout", "incomplete_eof", "output_too_large", "child_exit_ambiguous"}
    if observation.failure_reason in low_level:
        expected = {
            "timeout": (True, False, None, None),
            "incomplete_eof": (False, False, None, None),
            "output_too_large": (False, False, None, None),
            "child_exit_ambiguous": (False, True, None, None),
        }[observation.failure_reason]
        _require(
            (
                observation.timed_out,
                observation.eof_complete,
                observation.returncode,
                observation.child_exit_code,
            )
            == expected,
            "qstat low-level failure outcome is contradictory",
        )
        return observation
    _require(
        observation.timed_out is False
        and observation.eof_complete is True
        and type(observation.returncode) is int
        and observation.child_exit_code == observation.returncode,
        "qstat completed outcome is contradictory",
    )
    classification = EVIDENCE.classify_qstat_bytes(
        expected_job_id=job_id,
        expected_job_name=project,
        returncode=observation.returncode,
        stdout=observation.stdout,
        stderr=observation.stderr,
        timed_out=False,
        eof_complete=True,
    )
    if classification.status == "unknown":
        _require(
            observation.failure_reason in {None, classification.reason},
            "qstat classified failure reason conflicts with exact bytes",
        )
        return dataclasses.replace(observation, failure_reason=classification.reason)
    _require(
        observation.failure_reason is None,
        "qstat classifiable outcome carries a failure reason",
    )
    return observation


class _FakeQstatDriver:
    """Explicit offline-only driver; it is never accepted by production."""

    __slots__ = ("observation", "calls", "production")

    def __init__(self, observation: _QstatObservation) -> None:
        _require(type(observation) is _QstatObservation, "fake qstat observation differs")
        self.observation = observation
        self.calls = 0
        self.production = False

    def acquire_once(self, job_id: str, read_profile: dict[str, Any]) -> _QstatObservation:
        _require(CHANNEL.JOB_ID_RE.fullmatch(job_id) is not None, "fake qstat job id differs")
        _require(read_profile["server_read"]["qstat"]["executable"] == QSTAT_EXECUTABLE, "fake read profile differs")
        self.calls += 1
        _require(self.calls == 1, "fake qstat driver is single-use")
        return self.observation


_TEST_OWNER_TOKEN = object()


class DirectQstatServerOwner:
    __slots__ = ("_lineage_owner", "_read_profile_owner", "_driver", "_pid", "_used", "_seal", "_lock")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("qstat server owners use a fixed factory")

    @classmethod
    def production(cls) -> "DirectQstatServerOwner":
        _assert_module_binding()
        _require(
            sys.flags.isolated == 1
            and sys.flags.no_site == 1
            and Path.cwd() == Path("/")
            and os.environ.get("LANG") == "C"
            and os.environ.get("LC_ALL") == "C",
            "production qstat server owner requires fixed -I -S clean exec",
        )
        value = object.__new__(cls)
        value._lineage_owner = LINEAGE.DirectExistingJobLineageOwner.production()
        value._read_profile_owner = READ_PROFILE.DirectReviewedReadProfileOwner.production()
        value._driver = None
        value._pid = os.getpid()
        value._used = False
        value._seal = cls
        value._lock = threading.RLock()
        return value

    @classmethod
    def _for_fake_local_testing(
        cls,
        *,
        durable_state_root: Path,
        driver: _FakeQstatDriver,
        read_profile_owner: READ_PROFILE.DirectReviewedReadProfileOwner,
        _test_token: object,
    ) -> "DirectQstatServerOwner":
        _require(_test_token is _TEST_OWNER_TOKEN, "qstat server test token differs")
        _require(type(driver) is _FakeQstatDriver and driver.production is False, "fake qstat driver differs")
        _require(
            type(read_profile_owner) is READ_PROFILE.DirectReviewedReadProfileOwner
            and read_profile_owner._seal is READ_PROFILE._TEST_OWNER_TOKEN,
            "fake server reviewed read-profile owner differs",
        )
        value = object.__new__(cls)
        value._lineage_owner = LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
            durable_state_root=durable_state_root,
            _test_token=LINEAGE._TEST_OWNER_TOKEN,
        )
        value._read_profile_owner = read_profile_owner
        value._driver = driver
        value._pid = os.getpid()
        value._used = False
        value._seal = _TEST_OWNER_TOKEN
        value._lock = threading.RLock()
        return value

    def handle_once(self, request_frame: bytes) -> bytes:
        _require(
            self._seal is _TEST_OWNER_TOKEN,
            "production qstat requires the fixed dispatcher budget seam",
        )
        response, _deadline = self._handle_once(request_frame, None)
        return response

    def _handle_dispatched_once(
        self,
        request_frame: bytes,
        dispatch_budget: object,
    ) -> bytes:
        _require(
            self._seal is DirectQstatServerOwner
            and dispatch_budget is not None,
            "fixed dispatcher qstat budget differs",
        )
        response, deadline = self._handle_once(
            request_frame, dispatch_budget,
        )
        _require(
            deadline is dispatch_budget,
            "fixed dispatcher qstat budget identity differs",
        )
        return response

    def _handle_once(
        self,
        request_frame: bytes,
        dispatch_budget: object | None,
    ) -> tuple[bytes, object | None]:
        with self._lock:
            _require(
                type(self) is DirectQstatServerOwner
                and self._pid == os.getpid()
                and self._used is False
                and self._seal in {DirectQstatServerOwner, _TEST_OWNER_TOKEN},
                "qstat server owner is foreign, forked, or terminal",
            )
            self._used = True
        _assert_module_binding()
        decoded_request = _decode_canonical_frame(
            request_frame, MAX_REQUEST_BYTES, "qstat request"
        )
        if (type(decoded_request) is dict
                and type(decoded_request.get("artifacts")) is dict):
            candidate_artifacts = _artifacts_from_document(
                decoded_request["artifacts"]
            )
            try:
                transport_document = json.loads(
                    candidate_artifacts.transport_profile.decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DirectQstatAcquisitionError(
                    "reviewed transport profile is not exact JSON"
                ) from exc
            if (type(transport_document) is dict
                    and transport_document.get("schema")
                    == CHANNEL.LEGACY_TRANSPORT_PROFILE_SCHEMA):
                CHANNEL.validate_legacy_transport_profile_for_replay(
                    transport_document
                )
                raise DirectQstatAcquisitionError(
                    "historical transport profile is replay-only before qstat"
                )
        request = validate_request(decoded_request)
        artifacts = _artifacts_from_document(request["artifacts"])
        _require(
            W5._validate_controller_artifact_join(artifacts)["schema"]
            == CHANNEL.TRANSPORT_PROFILE_SCHEMA,
            "historical transport profile is replay-only before qstat",
        )
        receipt_raw = _unb64(request["portable_receipt_base64"], "portable W5 receipt", W5.MAX_FRAME_BYTES)
        requested_read_profile_raw = _unb64(
            request["read_profile_base64"], "read profile", CHANNEL.MAX_PROFILE_BYTES
        )
        profile_capability = self._read_profile_owner.issue_once(artifacts.transport_profile)
        profile_lease: READ_PROFILE.DirectReviewedReadProfileLease | None = None
        capability = self._lineage_owner.issue_once(receipt_raw, artifacts)
        consumer_join = _ISSUE_LINEAGE_JOIN(capability)
        lease: LINEAGE.DirectSubmittedJobReadLease | None = None
        try:
            profile_lease, read_profile_raw, profile_projection = READ_PROFILE._consume_for_q1_once(
                profile_capability
            )
            profile_lease.assert_current()
            _require(
                read_profile_raw == requested_read_profile_raw
                and profile_projection["profile_bytes_sha256"]
                == request["read_profile_bytes_sha256"]
                and profile_projection["profile_payload_sha256"]
                == request["read_profile_payload_sha256"],
                "server backend-owned read profile differs from controller evidence",
            )
            read_profile = CHANNEL.load_read_profile(read_profile_raw, artifacts.transport_profile)
            lease, lineage_raw = LINEAGE._consume_for_exact_qstat_once(capability, consumer_join)
            lease.assert_current()
            lineage = LINEAGE.validate_lineage_projection(json.loads(lineage_raw.decode("utf-8")))
            job_id = lineage["binding"]["job_id"]
            _require(
                job_id == request["expected_job_id"],
                "controller expected job id differs from exact L1 capability",
            )
            effective_budget = None
            if self._seal is DirectQstatServerOwner:
                if dispatch_budget is not None:
                    dispatcher = sys.modules.get(
                        "direct_read_subsystem_dispatcher"
                    )
                    consume_budget = getattr(
                        dispatcher, "_consume_dispatch_budget_once", None,
                    )
                    _require(
                        callable(consume_budget),
                        "canonical read dispatcher budget consumer is unavailable",
                    )
                    effective_budget = consume_budget(
                        dispatch_budget,
                        request_frame,
                        "acquire_exact_qstat",
                        int(
                            read_profile["server_read"]["qstat"]
                            ["timeout_seconds"],
                            10,
                        ),
                    )
                observation = _production_qstat_once(
                    job_id, read_profile, effective_budget,
                )
            else:
                _require(type(self._driver) is _FakeQstatDriver, "fake qstat driver is unavailable")
                observation = self._driver.acquire_once(job_id, read_profile)
            observation = _normalize_observation(
                job_id,
                lineage["binding"]["project"],
                observation,
            )
            lease.assert_current()
            profile_lease.assert_current()
            response = _build_response(
                request,
                lineage_raw,
                lineage,
                read_profile,
                profile_projection,
                observation,
            )
            return _canonical_frame(response, MAX_RESPONSE_BYTES), effective_budget
        finally:
            if lease is not None:
                lease.close_once()
            if profile_lease is not None:
                profile_lease.close_once()


def _executable_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_uid, info.st_gid, stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode), info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _identity_sha(identity: tuple[int, ...]) -> str:
    return digest(
        {"schema": "auto-g16-qstat-executable-identity/1", "fields": [str(item) for item in identity]}
    )


def _read_qstat_descriptor_sha256(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    hasher = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        hasher.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return hasher.hexdigest()


def _assert_qstat_descriptor_current(
    descriptor: int,
    expected_identity: tuple[int, ...],
    expected_sha256: str,
) -> None:
    """Replay exact fixed-path descriptor identity and bytes immediately before exec."""

    try:
        before = os.fstat(descriptor)
        before_identity = _executable_identity(before)
        _require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == 0
            and stat.S_IMODE(before.st_mode) == 0o755
            and before.st_nlink == 1
            and before.st_mode & (stat.S_IWGRP | stat.S_IWOTH) == 0
            and before_identity == expected_identity,
            "qstat descriptor runtime owner, mode, link, or identity differs",
        )
        actual_sha256 = _read_qstat_descriptor_sha256(descriptor)
        after = os.fstat(descriptor)
        named = os.stat(QSTAT_EXECUTABLE, follow_symlinks=False)
        _require(
            _executable_identity(after)
            == _executable_identity(named)
            == expected_identity
            and actual_sha256 == expected_sha256,
            "qstat descriptor effect-immediate identity or hash differs",
        )
    except OSError as exc:
        raise DirectQstatAcquisitionError(
            "qstat descriptor effect-immediate currentness failed"
        ) from exc


def _exec_reviewed_qstat_child_once(
    descriptor: int,
    expected_identity: tuple[int, ...],
    expected_sha256: str,
    argv: tuple[str, ...],
) -> None:
    _assert_qstat_descriptor_current(descriptor, expected_identity, expected_sha256)
    CHANNEL._descriptor_execve(descriptor, argv, QSTAT_ENVIRONMENT)
    raise AssertionError("qstat descriptor exec unexpectedly returned")


def _open_reviewed_qstat(
    read_profile: dict[str, Any],
) -> tuple[int, str, tuple[int, ...]]:
    qstat = read_profile["server_read"]["qstat"]
    _require(
        qstat["executable"] == QSTAT_EXECUTABLE
        and qstat["executable_owner_uid"] == "0"
        and qstat["executable_mode"] == "0755",
        "qstat executable path, root owner, or mode differs",
    )
    descriptor = os.open(
        QSTAT_EXECUTABLE,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        identity = _executable_identity(before)
        _assert_qstat_descriptor_current(
            descriptor,
            identity,
            qstat["executable_sha256"],
        )
        return descriptor, _identity_sha(identity), identity
    except BaseException:
        os.close(descriptor)
        raise


def _read_qstat_streams_until(
    stdout_fd: int,
    stderr_fd: int,
    deadline: float,
) -> tuple[bytes, bytes, bool, str | None]:
    buffers = {stdout_fd: bytearray(), stderr_fd: bytearray()}
    for descriptor in buffers:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    open_fds = set(buffers)
    failure: str | None = None
    while open_fds:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd]), False, "timeout"
        readable, _, exceptional = select.select(tuple(open_fds), (), tuple(open_fds), remaining)
        if exceptional:
            return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd]), False, "incomplete_eof"
        if not readable:
            return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd]), False, "timeout"
        for descriptor in readable:
            try:
                chunk = os.read(descriptor, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                open_fds.remove(descriptor)
                continue
            remaining_stream = MAX_QSTAT_STREAM_BYTES - len(buffers[descriptor])
            buffers[descriptor].extend(chunk[:remaining_stream])
            if len(chunk) > remaining_stream or sum(len(value) for value in buffers.values()) > MAX_QSTAT_COMBINED_BYTES:
                failure = "output_too_large"
                return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd]), False, failure
    return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd]), True, failure


def _production_qstat_once(
    job_id: str,
    read_profile: dict[str, Any],
    dispatch_budget: object | None = None,
    *,
    _test_token: object | None = None,
) -> _QstatObservation:
    """Execute exact descriptor-bound qstat once; no shell, fallback or retry."""

    _assert_module_binding()
    _require(CHANNEL.JOB_ID_RE.fullmatch(job_id) is not None, "exact L1 qstat job id differs")
    qstat_fd = -1
    qstat_identity: tuple[int, ...] | None = None
    stdout_r = stdout_w = stderr_r = stderr_w = -1
    pid = -1
    child_reaped = False
    retire_exact_child: Any = None
    requested_at = _utc_now_text()
    timeout = int(read_profile["server_read"]["qstat"]["timeout_seconds"], 10)
    if dispatch_budget is None:
        _require(
            _test_token is _TEST_OWNER_TOKEN,
            "production qstat requires exact dispatcher authority",
        )
        deadline = time.monotonic() + float(timeout)
    else:
        dispatcher = sys.modules.get("direct_read_subsystem_dispatcher")
        assert_dispatcher = getattr(
            dispatcher, "_assert_dispatcher_binding", None,
        )
        deadline_value = getattr(
            dispatcher, "_dispatch_deadline_value", None,
        )
        _require(
            callable(assert_dispatcher) and callable(deadline_value),
            "canonical dispatcher deadline capability is unavailable",
        )
        assert_dispatcher()
        deadline = deadline_value(dispatch_budget)
        _require(
            type(deadline) is float and time.monotonic() < deadline,
            "dispatcher qstat deadline capability expired",
        )
    try:
        qstat_fd, executable_identity_sha256, qstat_identity = _open_reviewed_qstat(
            read_profile
        )
        stdout_r, stdout_w = CHANNEL._pipe_cloexec()
        stderr_r, stderr_w = CHANNEL._pipe_cloexec()
        argv = (*QSTAT_ARGV_PREFIX, job_id)
        _assert_module_binding()
        creator_pid = os.getpid()
        creator_thread = threading.get_ident()
        ownership = (creator_pid, creator_thread, object())
        ownership_seal = ownership[2]
        _require(
            signal.getsignal(signal.SIGCHLD) is signal.SIG_DFL,
            "qstat child requires default SIGCHLD and its exclusive reaper",
        )

        def retire_exact_child() -> bool:
            if (
                type(pid) is not int
                or pid <= 0
                or os.getpid() != ownership[0]
                or threading.get_ident() != ownership[1]
                or ownership[2] is not ownership_seal
            ):
                return False
            try:
                _assert_module_binding()
            except BaseException:
                return False
            if signal.getsignal(signal.SIGCHLD) is not signal.SIG_DFL:
                return False

            terminal = False

            def probe() -> str:
                nonlocal terminal
                if terminal:
                    return "terminal"
                try:
                    waited, _status = os.waitpid(pid, os.WNOHANG)
                except (ChildProcessError, OSError):
                    return "foreign"
                if waited == pid:
                    terminal = True
                    return "reaped"
                if waited == 0:
                    return "live"
                return "foreign"

            def wait_reaped() -> bool:
                retirement_deadline = min(
                    deadline,
                    time.monotonic() + QSTAT_CHILD_RETIRE_GRACE_SECONDS,
                )
                while True:
                    state = probe()
                    if state == "reaped":
                        return True
                    if state != "live":
                        return False
                    remaining = retirement_deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    try:
                        select.select([], [], [], min(0.01, remaining))
                    except BaseException:
                        return False

            def signal_exact(signum: int) -> tuple[bool, bool]:
                state = probe()
                if state == "reaped":
                    return False, True
                if state != "live":
                    return False, False
                try:
                    os.kill(pid, signum)
                except ProcessLookupError:
                    return False, probe() == "reaped"
                except OSError:
                    return False, False
                return True, False

            sent, reaped = signal_exact(signal.SIGTERM)
            if reaped:
                return True
            if not sent:
                return False
            if wait_reaped():
                return True
            sent, reaped = signal_exact(signal.SIGKILL)
            return reaped or (sent and wait_reaped())

        pid = os.fork()
        if pid == 0:  # pragma: no cover - production server only
            try:
                os.dup2(stdout_w, 1)
                os.dup2(stderr_w, 2)
                for descriptor in (stdout_r, stdout_w, stderr_r, stderr_w):
                    if descriptor > 2:
                        CHANNEL._close_quiet(descriptor)
                _require(
                    type(qstat_identity) is tuple,
                    "qstat executable identity is unavailable",
                )
                _exec_reviewed_qstat_child_once(
                    qstat_fd,
                    qstat_identity,
                    read_profile["server_read"]["qstat"]["executable_sha256"],
                    argv,
                )
            except BaseException:
                os._exit(127)
        CHANNEL._close_quiet(stdout_w, stderr_w, qstat_fd)
        stdout_w = stderr_w = qstat_fd = -1
        stdout, stderr, eof_complete, failure = _read_qstat_streams_until(stdout_r, stderr_r, deadline)
        returncode: int | None = None
        child_exit: int | None = None
        if eof_complete:
            try:
                child_exit = CHANNEL._wait_child_until(pid, deadline)
                child_reaped = True
                returncode = child_exit
            except BaseException:
                failure = "child_exit_ambiguous"
        timed_out = failure == "timeout"
        if failure is None and not eof_complete:
            failure = "incomplete_eof"
        return _QstatObservation(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            eof_complete=eof_complete,
            child_exit_code=child_exit,
            requested_at=requested_at,
            collected_at=_utc_now_text(),
            executable_identity_sha256=executable_identity_sha256,
            failure_reason=failure,
        )
    finally:
        CHANNEL._close_quiet(qstat_fd, stdout_r, stdout_w, stderr_r, stderr_w)
        if pid > 0 and not child_reaped and retire_exact_child is not None:
            try:
                child_reaped = bool(retire_exact_child())
            except BaseException:
                child_reaped = False
            if not child_reaped:
                raise DirectQstatAcquisitionError(
                    "exact qstat child retirement is unknown; no retry"
                )


def _acquire_terminal_fetch_eligibility_once(
    *,
    project: str,
    job_id: str,
    attempt_id: str,
    input_sha256: str,
    direct_binding_sha256: str,
    read_profile: dict[str, Any],
    dispatch_budget: object,
) -> dict[str, Any]:
    """Sole Q1 effect-time owner for server-local terminal fetch eligibility."""

    _assert_module_binding()
    observation = _normalize_observation(
        job_id,
        project,
        _production_qstat_once(job_id, read_profile, dispatch_budget),
    )
    binding = EVIDENCE.DirectJobBinding(
        project=project,
        job_id=job_id,
        attempt_id=attempt_id,
        input_sha256=input_sha256,
        direct_binding_sha256=direct_binding_sha256,
    )
    evidence = EVIDENCE.build_qstat_evidence(
        binding,
        EVIDENCE.QstatObservation(
            returncode=observation.returncode,
            stdout=observation.stdout,
            stderr=observation.stderr,
            timed_out=observation.timed_out,
            eof_complete=observation.eof_complete,
            requested_at=observation.requested_at,
            collected_at=observation.collected_at,
            received_at=observation.collected_at,
        ),
    ).document()
    qstat = evidence["qstat"]
    allowed = (
        evidence["collection"]["freshness"] == "fresh"
        and (
            (
                qstat["status"] == "present"
                and qstat["record_present"] is True
                and qstat["lifecycle"] == "terminal"
                and qstat["pbs_state"] in {"C", "F"}
            )
            or (
                qstat["status"] == "absent"
                and qstat["record_present"] is False
                and qstat["lifecycle"] == "absent"
                and qstat["pbs_state"] is None
            )
        )
    )
    _require(allowed, "server effect-time qstat is not terminal fetch eligible")
    _require(
        evidence["authority"]["authorizes_effect"] is False,
        "server terminal eligibility evidence authority differs",
    )
    return evidence


def _build_response(
    request: dict[str, Any],
    lineage_raw: bytes,
    lineage: dict[str, Any],
    read_profile: dict[str, Any],
    server_profile_projection: dict[str, Any],
    observation: _QstatObservation,
) -> dict[str, Any]:
    qstat_profile = read_profile["server_read"]["qstat"]
    server_profile_projection = READ_PROFILE.validate_capability_projection(
        server_profile_projection
    )
    _require(
        server_profile_projection["profile_bytes_sha256"]
        == request["read_profile_bytes_sha256"]
        and server_profile_projection["profile_payload_sha256"]
        == request["read_profile_payload_sha256"],
        "server reviewed read-profile capability differs",
    )
    job_id = lineage["binding"]["job_id"]
    document = {
        "schema": RESPONSE_SCHEMA,
        "protocol": CHANNEL.READ_PROTOCOL,
        "status": "acquired",
        "operation_id": request["operation_id"],
        "request_id": request["request_id"],
        "job_id": job_id,
        "lineage_projection_base64": _b64(lineage_raw),
        "lineage_projection_bytes_sha256": hashlib.sha256(lineage_raw).hexdigest(),
        "lineage_payload_sha256": lineage["result_payload_sha256"],
        "artifact_sha256": copy.deepcopy(lineage["artifact_sha256"]),
        "read_profile": {
            "bytes_sha256": request["read_profile_bytes_sha256"],
            "payload_sha256": read_profile["read_profile_payload_sha256"],
            "controller_capability_id": request["controller_read_profile_capability"]["capability_id"],
            "controller_capability_projection_sha256": request["controller_read_profile_capability"]["projection_payload_sha256"],
            "server_capability_id": server_profile_projection["capability_id"],
            "server_capability_projection_sha256": server_profile_projection["projection_payload_sha256"],
        },
        "qstat": {
            "executable": QSTAT_EXECUTABLE,
            "executable_sha256": qstat_profile["executable_sha256"],
            "executable_identity_sha256": observation.executable_identity_sha256,
            "acquisition_source_sha256": _EXECUTED_SOURCE_SHA256,
            "argv": [*QSTAT_ARGV_PREFIX, job_id],
            "environment": copy.deepcopy(QSTAT_ENVIRONMENT),
            "returncode": None if observation.returncode is None else str(observation.returncode),
            "child_exit_code": None if observation.child_exit_code is None else str(observation.child_exit_code),
            "stdout_base64": _b64(observation.stdout),
            "stdout_sha256": hashlib.sha256(observation.stdout).hexdigest(),
            "stdout_size_bytes": str(len(observation.stdout)),
            "stderr_base64": _b64(observation.stderr),
            "stderr_sha256": hashlib.sha256(observation.stderr).hexdigest(),
            "stderr_size_bytes": str(len(observation.stderr)),
            "timed_out": observation.timed_out,
            "eof_complete": observation.eof_complete,
            "failure_reason": observation.failure_reason,
        },
        "collection": {
            "requested_at": observation.requested_at,
            "collected_at": observation.collected_at,
        },
        "authority": copy.deepcopy(AUTHORITY),
        "response_payload_sha256": "",
    }
    document["response_payload_sha256"] = digest(document)
    return validate_response(document, request=request)


def validate_response(value: Any, *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    _assert_module_binding()
    document = _exact(
        copy.deepcopy(value),
        {
            "schema", "protocol", "status", "operation_id", "request_id", "job_id",
            "lineage_projection_base64", "lineage_projection_bytes_sha256",
            "lineage_payload_sha256", "artifact_sha256", "read_profile", "qstat",
            "collection", "authority", "response_payload_sha256",
        },
        "qstat acquisition response",
    )
    _require(
        document["schema"] == RESPONSE_SCHEMA
        and document["protocol"] == CHANNEL.READ_PROTOCOL
        and document["status"] == "acquired"
        and CHANNEL.OPERATION_ID_RE.fullmatch(document["operation_id"]) is not None
        and re.fullmatch(r"direct-qstat-request-[a-f0-9]{64}", document["request_id"]) is not None
        and CHANNEL.JOB_ID_RE.fullmatch(document["job_id"]) is not None
        and document["authority"] == AUTHORITY,
        "qstat acquisition response constants differ",
    )
    lineage_raw = _unb64(document["lineage_projection_base64"], "lineage projection", LINEAGE.MAX_DOCUMENT_BYTES)
    _require(
        hashlib.sha256(lineage_raw).hexdigest()
        == _sha(document["lineage_projection_bytes_sha256"], "lineage projection bytes"),
        "lineage projection bytes hash differs",
    )
    lineage = LINEAGE.validate_lineage_projection(json.loads(lineage_raw.decode("utf-8")))
    _require(
        LINEAGE.canonical_bytes(lineage) == lineage_raw
        and lineage["result_payload_sha256"] == document["lineage_payload_sha256"]
        and lineage["artifact_sha256"] == document["artifact_sha256"]
        and lineage["binding"]["job_id"] == document["job_id"],
        "L1 lineage response join differs",
    )
    read_profile = _exact(
        document["read_profile"],
        {
            "bytes_sha256", "payload_sha256", "controller_capability_id",
            "controller_capability_projection_sha256", "server_capability_id",
            "server_capability_projection_sha256",
        },
        "response read profile",
    )
    _sha(read_profile["bytes_sha256"], "response read profile bytes")
    _sha(read_profile["payload_sha256"], "response read profile payload")
    for field in ("controller_capability_id", "server_capability_id"):
        _require(
            re.fullmatch(r"direct-reviewed-read-profile-[a-f0-9]{64}", read_profile[field]) is not None,
            f"response read profile {field} differs",
        )
    _sha(
        read_profile["controller_capability_projection_sha256"],
        "controller read-profile capability projection",
    )
    _sha(
        read_profile["server_capability_projection_sha256"],
        "server read-profile capability projection",
    )
    qstat = _exact(
        document["qstat"],
        {
            "executable", "executable_sha256", "executable_identity_sha256",
            "acquisition_source_sha256", "argv", "environment", "returncode",
            "child_exit_code", "stdout_base64", "stdout_sha256", "stdout_size_bytes",
            "stderr_base64", "stderr_sha256", "stderr_size_bytes", "timed_out",
            "eof_complete", "failure_reason",
        },
        "qstat response",
    )
    _require(
        qstat["executable"] == QSTAT_EXECUTABLE
        and qstat["argv"] == [*QSTAT_ARGV_PREFIX, document["job_id"]]
        and qstat["environment"] == QSTAT_ENVIRONMENT
        and qstat["acquisition_source_sha256"] == _EXECUTED_SOURCE_SHA256,
        "qstat executable source, argv, or environment differs",
    )
    for field in ("executable_sha256", "executable_identity_sha256", "acquisition_source_sha256"):
        _sha(qstat[field], f"qstat {field}")
    for field in ("returncode", "child_exit_code"):
        _require(
            qstat[field] is None
            or (type(qstat[field]) is str and SIGNED_DECIMAL_RE.fullmatch(qstat[field]) is not None),
            f"qstat {field} differs",
        )
    stdout = _unb64(qstat["stdout_base64"], "qstat stdout", MAX_QSTAT_STREAM_BYTES)
    stderr = _unb64(qstat["stderr_base64"], "qstat stderr", MAX_QSTAT_STREAM_BYTES)
    _require(
        len(stdout) + len(stderr) <= MAX_QSTAT_COMBINED_BYTES,
        "qstat response combined streams exceed 64 KiB",
    )
    for name, raw in (("stdout", stdout), ("stderr", stderr)):
        _require(
            hashlib.sha256(raw).hexdigest() == _sha(qstat[f"{name}_sha256"], f"qstat {name} hash", allow_empty=True)
            and len(raw) == _decimal(qstat[f"{name}_size_bytes"], f"qstat {name} size"),
            f"qstat {name} bytes differ",
        )
    _require(type(qstat["timed_out"]) is bool and type(qstat["eof_complete"]) is bool, "qstat flags differ")
    _require(
        qstat["failure_reason"]
        in ({None, "child_exit_ambiguous"} | set(EVIDENCE.UNKNOWN_REASONS)),
        "qstat failure reason differs",
    )
    returncode = None if qstat["returncode"] is None else int(qstat["returncode"], 10)
    child_exit = None if qstat["child_exit_code"] is None else int(qstat["child_exit_code"], 10)
    low_level = {"timeout", "incomplete_eof", "output_too_large", "child_exit_ambiguous"}
    if qstat["failure_reason"] in low_level:
        expected = {
            "timeout": (True, False, None, None),
            "incomplete_eof": (False, False, None, None),
            "output_too_large": (False, False, None, None),
            "child_exit_ambiguous": (False, True, None, None),
        }[qstat["failure_reason"]]
        _require(
            (qstat["timed_out"], qstat["eof_complete"], returncode, child_exit) == expected,
            "qstat low-level failure relation differs",
        )
    else:
        _require(
            qstat["timed_out"] is False
            and qstat["eof_complete"] is True
            and type(returncode) is int
            and child_exit == returncode,
            "qstat completed outcome relation differs",
        )
        classification = EVIDENCE.classify_qstat_bytes(
            expected_job_id=lineage["binding"]["job_id"],
            expected_job_name=lineage["binding"]["project"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            eof_complete=True,
        )
        if qstat["failure_reason"] is None:
            _require(
                classification.status in {"present", "absent"},
                "qstat response would upgrade an unknown completed outcome",
            )
        else:
            _require(
                classification.status == "unknown"
                and classification.reason == qstat["failure_reason"],
                "qstat response failure reason conflicts with exact bytes",
            )
    collection = _exact(document["collection"], {"requested_at", "collected_at"}, "response collection")
    _require(
        _timestamp(collection["requested_at"], "response requested_at")
        <= _timestamp(collection["collected_at"], "response collected_at"),
        "response collection chronology differs",
    )
    if request is not None:
        request = validate_request(request)
        request_artifacts = _artifacts_from_document(request["artifacts"])
        requested_read_profile_raw = _unb64(
            request["read_profile_base64"], "request read profile", CHANNEL.MAX_PROFILE_BYTES
        )
        requested_read_profile = CHANNEL.load_read_profile(
            requested_read_profile_raw, request_artifacts.transport_profile
        )
        _require(
            document["operation_id"] == request["operation_id"]
            and document["request_id"] == request["request_id"]
            and document["job_id"] == request["expected_job_id"]
            and document["artifact_sha256"] == request["artifact_sha256"]
            and read_profile["bytes_sha256"] == request["read_profile_bytes_sha256"]
            and read_profile["payload_sha256"] == request["read_profile_payload_sha256"],
            "qstat response/request splice differs",
        )
        _require(
            read_profile["controller_capability_id"]
            == request["controller_read_profile_capability"]["capability_id"]
            and read_profile["controller_capability_projection_sha256"]
            == request["controller_read_profile_capability"]["projection_payload_sha256"],
            "controller reviewed read-profile capability response binding differs",
        )
        _require(
            qstat["executable_sha256"]
            == requested_read_profile["server_read"]["qstat"]["executable_sha256"],
            "qstat response executable differs from backend-reviewed profile",
        )
    supplied = _sha(document["response_payload_sha256"], "qstat response payload")
    _require(
        supplied == digest({**document, "response_payload_sha256": ""}),
        "qstat response payload hash differs",
    )
    return document


class _FakeQueryTransport:
    """Offline local transport that never invokes SSH or a subprocess."""

    __slots__ = ("server_owner", "calls", "production")

    def __init__(self, server_owner: DirectQstatServerOwner) -> None:
        _require(
            type(server_owner) is DirectQstatServerOwner
            and server_owner._seal is _TEST_OWNER_TOKEN,
            "fake query transport requires the fake server owner",
        )
        self.server_owner = server_owner
        self.calls = 0
        self.production = False

    def run_once(
        self,
        operation: CHANNEL.QueryExactJobOperation,
        request_frame: bytes,
        join: _ControllerQueryJoin,
    ) -> dict[str, Any]:
        self.calls += 1
        _require(self.calls == 1, "fake query transport is single-use")
        _ASSERT_CONTROLLER_JOIN(join, operation, request_frame)
        response_frame = self.server_owner.handle_once(request_frame)
        return _decode_canonical_frame(response_frame, MAX_RESPONSE_BYTES, "fake qstat response")


class ExactQstatAcquisitionResult:
    __slots__ = ("acquisition_id", "_pid", "_epoch", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("qstat acquisition results are owner-issued only")

    def assert_current(self) -> None:
        _RESULT_ASSERT(self)

    def portable_projection(self) -> dict[str, Any]:
        return json.loads(_RESULT_PROJECT(self).decode("utf-8"))

    def __copy__(self) -> Any:
        raise TypeError("qstat acquisition results are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("qstat acquisition results are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("qstat acquisition results are not serializable")


class _ResultRecord(NamedTuple):
    pid: int
    epoch: object
    seal: object
    projection_raw: bytes
    stdout: bytes
    stderr: bytes
    finalizer: object


def _build_result_owner() -> tuple[Any, Any, Any, Any, Any]:
    registry: weakref.WeakKeyDictionary[ExactQstatAcquisitionResult, _ResultRecord] = weakref.WeakKeyDictionary()
    live_ids: set[str] = set()
    terminal_ids: set[str] = set()
    terminal_order: collections.deque[str] = collections.deque()
    lock = threading.RLock()
    epoch = object()

    def terminalize_id(acquisition_id: str) -> None:
        terminal_ids.add(acquisition_id)
        terminal_order.append(acquisition_id)
        while len(terminal_order) > CHANNEL.MAX_TERMINAL_OPERATION_RECORDS:
            terminal_ids.discard(terminal_order.popleft())

    def abandon(acquisition_id: str, issued_epoch: object) -> None:
        with lock:
            if epoch is issued_epoch and acquisition_id in live_ids:
                live_ids.remove(acquisition_id)
                terminalize_id(acquisition_id)

    def validate_exact_bytes(
        projection: dict[str, Any],
        stdout: bytes,
        stderr: bytes,
    ) -> None:
        qstat = projection["qstat"]
        _require(
            type(stdout) is bytes
            and type(stderr) is bytes
            and len(stdout) <= MAX_QSTAT_STREAM_BYTES
            and len(stderr) <= MAX_QSTAT_STREAM_BYTES
            and len(stdout) + len(stderr) <= MAX_QSTAT_COMBINED_BYTES
            and hashlib.sha256(stdout).hexdigest() == qstat["stdout_sha256"]
            and hashlib.sha256(stderr).hexdigest() == qstat["stderr_sha256"]
            and len(stdout) == int(qstat["stdout_size_bytes"], 10)
            and len(stderr) == int(qstat["stderr_size_bytes"], 10),
            "qstat acquisition private bytes, hashes, or sizes differ",
        )
        if qstat["failure_reason"] in {
            "timeout", "incomplete_eof", "output_too_large", "child_exit_ambiguous"
        }:
            return
        classification = EVIDENCE.classify_qstat_bytes(
            expected_job_id=projection["lineage"]["job_id"],
            expected_job_name=projection["lineage"]["project"],
            returncode=(
                None
                if qstat["returncode"] is None
                else int(qstat["returncode"], 10)
            ),
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            eof_complete=True,
        )
        if qstat["failure_reason"] is None:
            _require(
                classification.status in {"present", "absent"},
                "qstat acquisition private bytes would upgrade unknown evidence",
            )
        else:
            _require(
                classification.status == "unknown"
                and classification.reason == qstat["failure_reason"],
                "qstat acquisition private failure reason differs from bytes",
            )

    def exact(value: object) -> _ResultRecord:
        with lock:
            record = registry.get(value) if type(value) is ExactQstatAcquisitionResult else None
            _require(
                type(record) is _ResultRecord
                and record.pid == os.getpid() == value._pid
                and record.epoch is epoch is value._epoch
                and record.seal is value._seal
                and value.acquisition_id not in terminal_ids,
                "qstat acquisition result is foreign, forged, forked, rebound, or terminal",
            )
            projection = validate_acquisition_projection(json.loads(record.projection_raw.decode("utf-8")))
            _require(projection["acquisition_id"] == value.acquisition_id, "qstat acquisition result id differs")
            validate_exact_bytes(projection, record.stdout, record.stderr)
            return record

    def issue(projection: dict[str, Any], stdout: bytes, stderr: bytes) -> ExactQstatAcquisitionResult:
        nonlocal epoch
        projection = validate_acquisition_projection(projection)
        validate_exact_bytes(projection, stdout, stderr)
        result = object.__new__(ExactQstatAcquisitionResult)
        result.acquisition_id = projection["acquisition_id"]
        result._pid = os.getpid()
        result._epoch = epoch
        result._seal = object()
        with lock:
            _require(
                result.acquisition_id not in live_ids
                and result.acquisition_id not in terminal_ids,
                "duplicate qstat acquisition id differs",
            )
            live_ids.add(result.acquisition_id)
        finalizer = None
        try:
            finalizer = weakref.finalize(result, abandon, result.acquisition_id, epoch)
            record = _ResultRecord(
                os.getpid(), epoch, result._seal, canonical_bytes(projection),
                bytes(stdout), bytes(stderr), finalizer,
            )
            with lock:
                registry[result] = record
            exact(result)
            return result
        except BaseException:
            if finalizer is not None:
                finalizer.detach()
            with lock:
                registry.pop(result, None)
                live_ids.discard(result.acquisition_id)
            raise

    def assert_current(value: ExactQstatAcquisitionResult) -> None:
        exact(value)

    def project(value: ExactQstatAcquisitionResult) -> bytes:
        return bytes(exact(value).projection_raw)

    def consume(value: ExactQstatAcquisitionResult) -> tuple[dict[str, Any], bytes, bytes]:
        record = exact(value)
        with lock:
            _require(registry.get(value) is record, "qstat acquisition consume raced")
            del registry[value]
            record.finalizer.detach()
            live_ids.remove(value.acquisition_id)
            terminalize_id(value.acquisition_id)
        return (
            validate_acquisition_projection(json.loads(record.projection_raw.decode("utf-8"))),
            bytes(record.stdout),
            bytes(record.stderr),
        )

    def after_fork() -> None:
        nonlocal lock, epoch
        for record in tuple(registry.values()):
            record.finalizer.detach()
        registry.clear()
        live_ids.clear()
        terminal_ids.clear()
        terminal_order.clear()
        lock = threading.RLock()
        epoch = object()

    return issue, assert_current, project, consume, after_fork


(
    _RESULT_ISSUE,
    _RESULT_ASSERT,
    _RESULT_PROJECT,
    _RESULT_CONSUME,
    _CLEAR_RESULTS_AFTER_FORK,
) = _build_result_owner()


def _acquisition_projection(
    request: dict[str, Any],
    response: dict[str, Any],
    response_frame: bytes,
    received_at: str,
) -> tuple[dict[str, Any], bytes, bytes]:
    response = validate_response(response, request=request)
    lineage_raw = _unb64(response["lineage_projection_base64"], "lineage projection", LINEAGE.MAX_DOCUMENT_BYTES)
    lineage = LINEAGE.validate_lineage_projection(json.loads(lineage_raw.decode("utf-8")))
    qstat = response["qstat"]
    stdout = _unb64(qstat["stdout_base64"], "qstat stdout", MAX_QSTAT_STREAM_BYTES)
    stderr = _unb64(qstat["stderr_base64"], "qstat stderr", MAX_QSTAT_STREAM_BYTES)
    freshness, age = _freshness(
        response["collection"]["requested_at"],
        response["collection"]["collected_at"],
        received_at,
    )
    lineage_binding = lineage["binding"]
    acquisition_id = "direct-qstat-acquisition-" + digest(
        {
            "schema": "auto-g16-direct-qstat-acquisition-id/1",
            "lineage_id": lineage["lineage_id"],
            "operation_id": response["operation_id"],
            "request_id": response["request_id"],
            "response_payload_sha256": response["response_payload_sha256"],
            "received_at": received_at,
        }
    )
    projection = {
        "schema": ACQUISITION_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "acquisition_id": acquisition_id,
        "lineage": {
            "lineage_id": lineage["lineage_id"],
            "projection_bytes_sha256": hashlib.sha256(lineage_raw).hexdigest(),
            "projection_payload_sha256": lineage["result_payload_sha256"],
            "journal_id": lineage_binding["journal_id"],
            "binding_payload_sha256": lineage_binding["binding_payload_sha256"],
            "attempt_id": lineage_binding["attempt_id"],
            "project": lineage_binding["project"],
            "job_id": lineage_binding["job_id"],
            "input_sha256": lineage_binding["input_sha256"],
            "authorization_payload_sha256": lineage_binding["authorization_payload_sha256"],
            "authorization_scope_sha256": lineage_binding["authorization_scope_sha256"],
            "transport_profile_payload_sha256": lineage_binding["transport_profile_payload_sha256"],
            "w5_result_payload_sha256": lineage_binding["result_payload_sha256"],
            "w2_journal_payload_sha256": lineage["durable"]["journal_payload_sha256"],
            "artifact_sha256": copy.deepcopy(lineage["artifact_sha256"]),
        },
        "channel": {
            "operation_type": "QueryExactJobOperation",
            "operation_id": response["operation_id"],
            "request_id": response["request_id"],
            "request_frame_sha256": hashlib.sha256(_canonical_frame(request, MAX_REQUEST_BYTES)).hexdigest(),
            "response_frame_sha256": hashlib.sha256(response_frame).hexdigest(),
            "response_payload_sha256": response["response_payload_sha256"],
            "transport_profile_bytes_sha256": hashlib.sha256(
                _artifacts_from_document(request["artifacts"]).transport_profile
            ).hexdigest(),
            "read_profile_bytes_sha256": response["read_profile"]["bytes_sha256"],
            "read_profile_payload_sha256": response["read_profile"]["payload_sha256"],
            "controller_read_profile_capability_id": response["read_profile"]["controller_capability_id"],
            "controller_read_profile_capability_projection_sha256": response["read_profile"]["controller_capability_projection_sha256"],
            "server_read_profile_capability_id": response["read_profile"]["server_capability_id"],
            "server_read_profile_capability_projection_sha256": response["read_profile"]["server_capability_projection_sha256"],
            "one_request": True,
            "one_response": True,
            "eof_complete": True,
            "ssh_child_exit_zero": True,
        },
        "qstat": {
            "executable": qstat["executable"],
            "executable_sha256": qstat["executable_sha256"],
            "executable_identity_sha256": qstat["executable_identity_sha256"],
            "acquisition_source_sha256": qstat["acquisition_source_sha256"],
            "argv": copy.deepcopy(qstat["argv"]),
            "environment": copy.deepcopy(qstat["environment"]),
            "returncode": qstat["returncode"],
            "child_exit_code": qstat["child_exit_code"],
            "stdout_sha256": qstat["stdout_sha256"],
            "stdout_size_bytes": qstat["stdout_size_bytes"],
            "stderr_sha256": qstat["stderr_sha256"],
            "stderr_size_bytes": qstat["stderr_size_bytes"],
            "timed_out": qstat["timed_out"],
            "eof_complete": qstat["eof_complete"],
            "failure_reason": qstat["failure_reason"],
        },
        "collection": {
            "requested_at": response["collection"]["requested_at"],
            "collected_at": response["collection"]["collected_at"],
            "received_at": received_at,
            "maximum_age_seconds": str(MAX_FRESH_AGE_SECONDS),
            "age_seconds": age,
            "freshness": freshness,
        },
        "authority": copy.deepcopy(AUTHORITY),
        "acquisition_payload_sha256": "",
    }
    projection["acquisition_payload_sha256"] = digest(projection)
    return validate_acquisition_projection(projection), stdout, stderr


def validate_acquisition_projection(value: Any) -> dict[str, Any]:
    _assert_module_binding()
    document = _exact(
        copy.deepcopy(value),
        {
            "schema", "owner", "owner_version", "acquisition_id", "lineage",
            "channel", "qstat", "collection", "authority", "acquisition_payload_sha256",
        },
        "qstat acquisition projection",
    )
    _require(
        document["schema"] == ACQUISITION_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and ACQUISITION_ID_RE.fullmatch(document["acquisition_id"]) is not None
        and document["authority"] == AUTHORITY,
        "qstat acquisition projection constants differ",
    )
    lineage = _exact(
        document["lineage"],
        {
            "lineage_id", "projection_bytes_sha256", "projection_payload_sha256",
            "journal_id", "binding_payload_sha256", "attempt_id", "project", "job_id",
            "input_sha256", "authorization_payload_sha256", "authorization_scope_sha256",
            "transport_profile_payload_sha256", "w5_result_payload_sha256",
            "w2_journal_payload_sha256", "artifact_sha256",
        },
        "acquisition lineage",
    )
    _require(
        LINEAGE.LINEAGE_RE.fullmatch(lineage["lineage_id"]) is not None
        and LINEAGE.JOURNAL_RE.fullmatch(lineage["journal_id"]) is not None
        and W5.ATTEMPT_ID_RE.fullmatch(lineage["attempt_id"]) is not None
        and CHANNEL.JOB_ID_RE.fullmatch(lineage["job_id"]) is not None
        and type(lineage["project"]) is str
        and bool(lineage["project"]),
        "acquisition lineage identifiers differ",
    )
    for field in (
        "projection_bytes_sha256", "projection_payload_sha256", "binding_payload_sha256",
        "input_sha256", "authorization_payload_sha256", "authorization_scope_sha256",
        "transport_profile_payload_sha256", "w5_result_payload_sha256",
        "w2_journal_payload_sha256",
    ):
        _sha(lineage[field], f"acquisition lineage {field}")
    _require(
        type(lineage["artifact_sha256"]) is dict
        and set(lineage["artifact_sha256"]) == set(SESSION.DirectServerSessionArtifacts.__dataclass_fields__),
        "acquisition artifact hash inventory differs",
    )
    for field, item in lineage["artifact_sha256"].items():
        _sha(item, f"acquisition artifact {field}")
    channel = _exact(
        document["channel"],
        {
            "operation_type", "operation_id", "request_id", "request_frame_sha256",
            "response_frame_sha256", "response_payload_sha256",
            "transport_profile_bytes_sha256", "read_profile_bytes_sha256",
            "read_profile_payload_sha256", "controller_read_profile_capability_id",
            "controller_read_profile_capability_projection_sha256",
            "server_read_profile_capability_id",
            "server_read_profile_capability_projection_sha256",
            "one_request", "one_response",
            "eof_complete", "ssh_child_exit_zero",
        },
        "acquisition channel",
    )
    _require(
        channel["operation_type"] == "QueryExactJobOperation"
        and CHANNEL.OPERATION_ID_RE.fullmatch(channel["operation_id"]) is not None
        and re.fullmatch(r"direct-qstat-request-[a-f0-9]{64}", channel["request_id"]) is not None
        and all(channel[field] is True for field in ("one_request", "one_response", "eof_complete", "ssh_child_exit_zero")),
        "acquisition channel completion differs",
    )
    for field in (
        "request_frame_sha256", "response_frame_sha256", "response_payload_sha256",
        "transport_profile_bytes_sha256", "read_profile_bytes_sha256", "read_profile_payload_sha256",
        "controller_read_profile_capability_projection_sha256",
        "server_read_profile_capability_projection_sha256",
    ):
        _sha(channel[field], f"acquisition channel {field}")
    for field in (
        "controller_read_profile_capability_id", "server_read_profile_capability_id",
    ):
        _require(
            re.fullmatch(r"direct-reviewed-read-profile-[a-f0-9]{64}", channel[field]) is not None,
            f"acquisition channel {field} differs",
        )
    qstat = _exact(
        document["qstat"],
        {
            "executable", "executable_sha256", "executable_identity_sha256",
            "acquisition_source_sha256", "argv", "environment", "returncode",
            "child_exit_code", "stdout_sha256", "stdout_size_bytes", "stderr_sha256",
            "stderr_size_bytes", "timed_out", "eof_complete", "failure_reason",
        },
        "acquisition qstat",
    )
    _require(
        qstat["executable"] == QSTAT_EXECUTABLE
        and qstat["argv"] == [*QSTAT_ARGV_PREFIX, lineage["job_id"]]
        and qstat["environment"] == QSTAT_ENVIRONMENT,
        "acquisition qstat fixed execution differs",
    )
    for field in (
        "executable_sha256", "executable_identity_sha256", "acquisition_source_sha256",
        "stdout_sha256", "stderr_sha256",
    ):
        _sha(qstat[field], f"acquisition qstat {field}", allow_empty=field in {"stdout_sha256", "stderr_sha256"})
    _require(
        qstat["acquisition_source_sha256"] == _EXECUTED_SOURCE_SHA256,
        "acquisition qstat source differs",
    )
    stdout_size = _decimal(qstat["stdout_size_bytes"], "acquisition stdout size")
    stderr_size = _decimal(qstat["stderr_size_bytes"], "acquisition stderr size")
    _require(
        stdout_size <= MAX_QSTAT_STREAM_BYTES
        and stderr_size <= MAX_QSTAT_STREAM_BYTES
        and stdout_size + stderr_size <= MAX_QSTAT_COMBINED_BYTES,
        "acquisition qstat stream bound differs",
    )
    for field in ("returncode", "child_exit_code"):
        _require(
            qstat[field] is None
            or (type(qstat[field]) is str and SIGNED_DECIMAL_RE.fullmatch(qstat[field]) is not None),
            f"acquisition qstat {field} differs",
        )
    _require(
        type(qstat["timed_out"]) is bool
        and type(qstat["eof_complete"]) is bool
        and qstat["failure_reason"]
        in ({None, "child_exit_ambiguous"} | set(EVIDENCE.UNKNOWN_REASONS)),
        "acquisition qstat failure relation differs",
    )
    returncode = None if qstat["returncode"] is None else int(qstat["returncode"], 10)
    child_exit = None if qstat["child_exit_code"] is None else int(qstat["child_exit_code"], 10)
    if qstat["failure_reason"] in {"timeout", "incomplete_eof", "output_too_large", "child_exit_ambiguous"}:
        expected = {
            "timeout": (True, False, None, None),
            "incomplete_eof": (False, False, None, None),
            "output_too_large": (False, False, None, None),
            "child_exit_ambiguous": (False, True, None, None),
        }[qstat["failure_reason"]]
        _require(
            (qstat["timed_out"], qstat["eof_complete"], returncode, child_exit) == expected,
            "acquisition qstat low-level outcome differs",
        )
    else:
        _require(
            qstat["timed_out"] is False
            and qstat["eof_complete"] is True
            and type(returncode) is int
            and child_exit == returncode,
            "acquisition qstat completed outcome differs",
        )
    collection = _exact(
        document["collection"],
        {
            "requested_at", "collected_at", "received_at", "maximum_age_seconds",
            "age_seconds", "freshness",
        },
        "acquisition collection",
    )
    _require(collection["maximum_age_seconds"] == str(MAX_FRESH_AGE_SECONDS), "acquisition freshness limit differs")
    expected_freshness, expected_age = _freshness(
        collection["requested_at"], collection["collected_at"], collection["received_at"]
    )
    _require(
        collection["freshness"] == expected_freshness
        and collection["age_seconds"] == expected_age,
        "acquisition freshness differs",
    )
    expected_acquisition_id = "direct-qstat-acquisition-" + digest(
        {
            "schema": "auto-g16-direct-qstat-acquisition-id/1",
            "lineage_id": lineage["lineage_id"],
            "operation_id": channel["operation_id"],
            "request_id": channel["request_id"],
            "response_payload_sha256": channel["response_payload_sha256"],
            "received_at": collection["received_at"],
        }
    )
    _require(
        document["acquisition_id"] == expected_acquisition_id,
        "acquisition id differs",
    )
    supplied = _sha(document["acquisition_payload_sha256"], "acquisition payload")
    _require(
        supplied == digest({**document, "acquisition_payload_sha256": ""}),
        "acquisition payload hash differs",
    )
    return document


def _prepare_controller_request(
    portable_receipt_bytes: bytes,
    artifacts: SESSION.DirectServerSessionArtifacts,
    read_profile_capability: READ_PROFILE.DirectReviewedReadProfileCapability,
) -> tuple[
    CHANNEL.QueryExactJobOperation,
    dict[str, Any],
    bytes,
    _ControllerQueryJoin,
    READ_PROFILE.DirectReviewedReadProfileLease,
]:
    _assert_module_binding()
    _require(type(portable_receipt_bytes) is bytes, "portable receipt bytes differ")
    receipt = W5.validate_submission_receipt(json.loads(portable_receipt_bytes.decode("utf-8")))
    _require(W5.canonical_bytes(receipt) == portable_receipt_bytes, "portable W5 receipt bytes differ")
    _require(
        type(read_profile_capability) is READ_PROFILE.DirectReviewedReadProfileCapability,
        "exact backend-owned read-profile capability is required",
    )
    profile_lease, read_profile_raw, profile_projection = READ_PROFILE._consume_for_q1_once(
        read_profile_capability
    )
    operation: CHANNEL.QueryExactJobOperation | None = None
    try:
        profile_lease.assert_current()
        _require(
            profile_projection["transport_profile_bytes_sha256"]
            == hashlib.sha256(artifacts.transport_profile).hexdigest(),
            "backend-owned read profile and reviewed transport differ",
        )
        CHANNEL.load_read_profile(read_profile_raw, artifacts.transport_profile)
        issuance_join = _ISSUE_QUERY_ISSUANCE_JOIN(
            receipt["qsub"]["job_id"],
            artifacts.transport_profile,
            read_profile_raw,
            profile_projection["capability_id"],
            hashlib.sha256(portable_receipt_bytes).hexdigest(),
        )
        operation = CHANNEL.issue_query_exact_job_operation(
            artifacts.transport_profile,
            read_profile_raw,
            issuance_join,
        )
        request = build_request(
            operation,
            portable_receipt_bytes,
            artifacts,
            read_profile_raw,
            profile_projection,
        )
        frame = _canonical_frame(request, MAX_REQUEST_BYTES)
        join = _ISSUE_CONTROLLER_JOIN(operation, frame)
        return operation, request, frame, join, profile_lease
    except BaseException:
        if operation is not None:
            CHANNEL._finish_operation(operation)
        profile_lease.close_once()
        raise


def acquire_qstat_once(
    portable_receipt_bytes: bytes,
    artifacts: SESSION.DirectServerSessionArtifacts,
    read_profile_capability: READ_PROFILE.DirectReviewedReadProfileCapability,
) -> ExactQstatAcquisitionResult:
    """Production-shaped controller entry; no job-id or transport override."""

    operation, request, frame, join, profile_lease = _prepare_controller_request(
        portable_receipt_bytes, artifacts, read_profile_capability
    )
    try:
        try:
            response = CHANNEL.run_query_channel_once(operation, frame, join)
        except CHANNEL.ControllerTransportUnknown as exc:
            raise DirectQstatTransportUnknown("exact qstat transport is unknown; no retry") from exc
        profile_lease.assert_current()
        received_at = _utc_now_text()
        response_frame = _canonical_frame(response, MAX_RESPONSE_BYTES)
        projection, stdout, stderr = _acquisition_projection(
            request, response, response_frame, received_at
        )
        return _RESULT_ISSUE(projection, stdout, stderr)
    finally:
        profile_lease.close_once()


def _acquire_with_fake_transport_once(
    portable_receipt_bytes: bytes,
    artifacts: SESSION.DirectServerSessionArtifacts,
    read_profile_capability: READ_PROFILE.DirectReviewedReadProfileCapability,
    transport: _FakeQueryTransport,
    *,
    received_at: str,
    _test_token: object,
) -> ExactQstatAcquisitionResult:
    _require(_test_token is _TEST_OWNER_TOKEN, "fake qstat acquisition token differs")
    _require(type(transport) is _FakeQueryTransport and transport.production is False, "fake transport differs")
    operation, request, frame, join, profile_lease = _prepare_controller_request(
        portable_receipt_bytes, artifacts, read_profile_capability
    )
    try:
        try:
            response = transport.run_once(operation, frame, join)
        finally:
            CHANNEL._finish_operation(operation)
        profile_lease.assert_current()
        response_frame = _canonical_frame(response, MAX_RESPONSE_BYTES)
        projection, stdout, stderr = _acquisition_projection(
            request, response, response_frame, received_at
        )
        return _RESULT_ISSUE(projection, stdout, stderr)
    finally:
        profile_lease.close_once()


class GaussianJobInspection3:
    __slots__ = ("_key", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("final scheduler inspections are owner-issued only")

    def document(self) -> dict[str, Any]:
        return json.loads(_INSPECTION_PROJECT(self).decode("utf-8"))

    def assert_current(self) -> None:
        _INSPECTION_ASSERT(self)

    def __copy__(self) -> Any:
        raise TypeError("final scheduler inspections are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("final scheduler inspections are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("final scheduler inspections are not serializable")


class _InspectionRecord(NamedTuple):
    value: GaussianJobInspection3
    pid: int
    epoch: object
    seal: object
    raw: bytes


def _build_inspection_owner() -> tuple[Any, Any, Any, Any]:
    registry: weakref.WeakKeyDictionary[GaussianJobInspection3, _InspectionRecord] = (
        weakref.WeakKeyDictionary()
    )
    lock = threading.RLock()
    epoch = object()

    def exact(value: object) -> _InspectionRecord:
        with lock:
            record = registry.get(value) if type(value) is GaussianJobInspection3 else None
            _require(
                type(record) is _InspectionRecord
                and record.value is value
                and record.pid == os.getpid()
                and record.epoch is epoch
                and record.seal is value._seal
                and record.raw == canonical_bytes(
                    validate_final_inspection(json.loads(record.raw.decode("utf-8")))
                ),
                "final scheduler inspection is foreign, forged, forked, rebound, or terminal",
            )
            return record

    def issue(document: dict[str, Any]) -> GaussianJobInspection3:
        nonlocal epoch
        raw = canonical_bytes(validate_final_inspection(document))
        value = object.__new__(GaussianJobInspection3)
        value._key = id(value)
        value._seal = object()
        record = _InspectionRecord(value, os.getpid(), epoch, value._seal, raw)
        with lock:
            registry[value] = record
        exact(value)
        return value

    def assert_current(value: object) -> None:
        exact(value)

    def project(value: object) -> bytes:
        return bytes(exact(value).raw)

    def consume(value: object) -> tuple[dict[str, Any], str]:
        record = exact(value)
        with lock:
            _require(registry.get(value) is record, "final scheduler inspection consume raced")
            del registry[value]
        document = validate_final_inspection(json.loads(record.raw.decode("utf-8")))
        return document, hashlib.sha256(record.raw).hexdigest()

    def after_fork() -> None:
        nonlocal lock, epoch
        registry.clear()
        lock = threading.RLock()
        epoch = object()

    return issue, assert_current, project, consume, after_fork


(
    _INSPECTION_ISSUE,
    _INSPECTION_ASSERT,
    _INSPECTION_PROJECT,
    _INSPECTION_CONSUME_FOR_TERMINAL_FETCH,
    _CLEAR_INSPECTIONS_AFTER_FORK,
) = _build_inspection_owner()


def build_final_scheduler_inspection_once(
    acquisition: ExactQstatAcquisitionResult,
) -> GaussianJobInspection3:
    """Consume the exact Q1 result and reuse W6C0 classification only."""

    _assert_module_binding()
    _require(type(acquisition) is ExactQstatAcquisitionResult, "exact qstat acquisition result is required")
    projection, stdout, stderr = _RESULT_CONSUME(acquisition)
    lineage = projection["lineage"]
    qstat = projection["qstat"]
    binding = EVIDENCE.DirectJobBinding(
        project=lineage["project"],
        job_id=lineage["job_id"],
        attempt_id=lineage["attempt_id"],
        input_sha256=lineage["input_sha256"],
        direct_binding_sha256=lineage["projection_payload_sha256"],
    )
    observation = EVIDENCE.QstatObservation(
        returncode=None if qstat["returncode"] is None else int(qstat["returncode"], 10),
        stdout=stdout,
        stderr=stderr,
        timed_out=qstat["timed_out"],
        eof_complete=qstat["eof_complete"],
        requested_at=projection["collection"]["requested_at"],
        collected_at=projection["collection"]["collected_at"],
        received_at=projection["collection"]["received_at"],
    )
    provisional = EVIDENCE.build_qstat_evidence(binding, observation).document()
    # An executable/child acquisition failure is never upgraded by parseable
    # bytes.  W6C0 still owns byte classification for all complete observations.
    if qstat["failure_reason"] is not None:
        scheduler_status = "unknown"
        scheduler_state = "unknown"
        reason = qstat["failure_reason"]
        record_present = None
        pbs_state = None
        lifecycle = "unknown"
    elif projection["collection"]["freshness"] != "fresh":
        scheduler_status = "unknown"
        scheduler_state = "unknown"
        reason = "stale_or_invalid_freshness"
        record_present = None
        pbs_state = None
        lifecycle = "unknown"
    else:
        scheduler_status = provisional["qstat"]["status"]
        scheduler_state = provisional["state"]
        reason = provisional["qstat"]["reason"]
        record_present = provisional["qstat"]["record_present"]
        pbs_state = provisional["qstat"]["pbs_state"]
        lifecycle = provisional["qstat"]["lifecycle"]
    inspection_id = "direct-scheduler-inspection-" + digest(
        {
            "schema": "auto-g16-direct-scheduler-inspection-id/1",
            "acquisition_id": projection["acquisition_id"],
            "acquisition_payload_sha256": projection["acquisition_payload_sha256"],
            "qstat_evidence_sha256": provisional["qstat_evidence_sha256"],
            "scheduler_status": scheduler_status,
            "scheduler_state": scheduler_state,
        }
    )
    document = {
        "schema": INSPECTION_SCHEMA,
        "owner": FINAL_OWNER,
        "owner_version": FINAL_OWNER_VERSION,
        "inspection_id": inspection_id,
        "source": "exact_owner_issued_qstat_acquisition",
        "binding": {
            "project": lineage["project"],
            "job_id": lineage["job_id"],
            "attempt_id": lineage["attempt_id"],
            "input_sha256": lineage["input_sha256"],
            "authorization_payload_sha256": lineage["authorization_payload_sha256"],
            "authorization_scope_sha256": lineage["authorization_scope_sha256"],
            "transport_profile_payload_sha256": lineage["transport_profile_payload_sha256"],
            "w5_result_payload_sha256": lineage["w5_result_payload_sha256"],
            "w2_journal_payload_sha256": lineage["w2_journal_payload_sha256"],
            "lineage_id": lineage["lineage_id"],
            "lineage_payload_sha256": lineage["projection_payload_sha256"],
            "acquisition_id": projection["acquisition_id"],
            "acquisition_payload_sha256": projection["acquisition_payload_sha256"],
        },
        "scheduler": {
            "dialect": EVIDENCE.SCHEDULER_DIALECT,
            "status": scheduler_status,
            "state": scheduler_state,
            "record_present": record_present,
            "pbs_state": pbs_state,
            "lifecycle": lifecycle,
            "reason": reason,
            "parser": EVIDENCE.PARSER_VERSION,
            "qstat_evidence_sha256": provisional["qstat_evidence_sha256"],
            "freshness": projection["collection"]["freshness"],
            "collected_at": projection["collection"]["collected_at"],
            "pbs_terminal_is_gaussian_completion": False,
            "pbs_terminal_is_scientific_acceptance": False,
        },
        "transport": {
            "operation_type": projection["channel"]["operation_type"],
            "operation_id": projection["channel"]["operation_id"],
            "request_id": projection["channel"]["request_id"],
            "request_frame_sha256": projection["channel"]["request_frame_sha256"],
            "response_frame_sha256": projection["channel"]["response_frame_sha256"],
            "read_profile_payload_sha256": projection["channel"]["read_profile_payload_sha256"],
            "qstat_executable_sha256": qstat["executable_sha256"],
            "qstat_executable_identity_sha256": qstat["executable_identity_sha256"],
            "qstat_argv": copy.deepcopy(qstat["argv"]),
            "stdout_sha256": qstat["stdout_sha256"],
            "stdout_size_bytes": qstat["stdout_size_bytes"],
            "stderr_sha256": qstat["stderr_sha256"],
            "stderr_size_bytes": qstat["stderr_size_bytes"],
        },
        "authority": copy.deepcopy(FINAL_AUTHORITY),
        "evidence_sha256": "",
    }
    document["evidence_sha256"] = digest(document)
    validated = validate_final_inspection(document)
    return _INSPECTION_ISSUE(validated)


def validate_final_inspection(value: Any) -> dict[str, Any]:
    _assert_module_binding()
    document = _exact(
        copy.deepcopy(value),
        {
            "schema", "owner", "owner_version", "inspection_id", "source",
            "binding", "scheduler", "transport", "authority", "evidence_sha256",
        },
        "final scheduler inspection",
    )
    _require(
        document["schema"] == INSPECTION_SCHEMA
        and document["owner"] == FINAL_OWNER
        and document["owner_version"] == FINAL_OWNER_VERSION
        and INSPECTION_ID_RE.fullmatch(document["inspection_id"]) is not None
        and document["source"] == "exact_owner_issued_qstat_acquisition"
        and document["authority"] == FINAL_AUTHORITY,
        "final scheduler inspection constants differ",
    )
    binding = _exact(
        document["binding"],
        {
            "project", "job_id", "attempt_id", "input_sha256",
            "authorization_payload_sha256", "authorization_scope_sha256",
            "transport_profile_payload_sha256", "w5_result_payload_sha256",
            "w2_journal_payload_sha256", "lineage_id", "lineage_payload_sha256",
            "acquisition_id", "acquisition_payload_sha256",
        },
        "final scheduler binding",
    )
    _require(
        type(binding["project"]) is str
        and bool(binding["project"])
        and CHANNEL.JOB_ID_RE.fullmatch(binding["job_id"]) is not None
        and W5.ATTEMPT_ID_RE.fullmatch(binding["attempt_id"]) is not None
        and LINEAGE.LINEAGE_RE.fullmatch(binding["lineage_id"]) is not None
        and ACQUISITION_ID_RE.fullmatch(binding["acquisition_id"]) is not None,
        "final scheduler binding identifiers differ",
    )
    for field in (
        "input_sha256", "authorization_payload_sha256", "authorization_scope_sha256",
        "transport_profile_payload_sha256", "w5_result_payload_sha256",
        "w2_journal_payload_sha256", "lineage_payload_sha256", "acquisition_payload_sha256",
    ):
        _sha(binding[field], f"final scheduler binding {field}")
    scheduler = _exact(
        document["scheduler"],
        {
            "dialect", "status", "state", "record_present", "pbs_state", "lifecycle",
            "reason", "parser", "qstat_evidence_sha256", "freshness", "collected_at",
            "pbs_terminal_is_gaussian_completion", "pbs_terminal_is_scientific_acceptance",
        },
        "final scheduler evidence",
    )
    _require(
        scheduler["dialect"] == EVIDENCE.SCHEDULER_DIALECT
        and scheduler["parser"] == EVIDENCE.PARSER_VERSION
        and scheduler["status"] in {"present", "absent", "unknown"}
        and scheduler["state"] in {"queued", "running", "held", "exiting", "terminal", "absent", "unknown"}
        and scheduler["freshness"] in {"fresh", "stale", "unknown"}
        and scheduler["pbs_terminal_is_gaussian_completion"] is False
        and scheduler["pbs_terminal_is_scientific_acceptance"] is False,
        "final scheduler evidence constants differ",
    )
    _sha(scheduler["qstat_evidence_sha256"], "final qstat evidence")
    _timestamp(scheduler["collected_at"], "final scheduler collected_at")
    if scheduler["status"] == "present":
        _require(
            scheduler["record_present"] is True
            and scheduler["pbs_state"] in EVIDENCE.PBS_STATE_TO_LIFECYCLE
            and scheduler["lifecycle"] == EVIDENCE.PBS_STATE_TO_LIFECYCLE[scheduler["pbs_state"]]
            and scheduler["state"] == scheduler["lifecycle"]
            and scheduler["freshness"] == "fresh"
            and scheduler["reason"] is None,
            "final present scheduler evidence differs",
        )
    elif scheduler["status"] == "absent":
        _require(
            scheduler["record_present"] is False
            and scheduler["pbs_state"] is None
            and scheduler["lifecycle"] == "absent"
            and scheduler["state"] == "absent"
            and scheduler["freshness"] == "fresh"
            and scheduler["reason"] is None,
            "final absent scheduler evidence differs",
        )
    else:
        _require(
            scheduler["record_present"] is None
            and scheduler["pbs_state"] is None
            and scheduler["lifecycle"] == "unknown"
            and scheduler["state"] == "unknown"
            and scheduler["reason"]
            in set(EVIDENCE.UNKNOWN_REASONS)
            | {"child_exit_ambiguous", "stale_or_invalid_freshness"},
            "final unknown scheduler evidence differs",
        )
    transport = _exact(
        document["transport"],
        {
            "operation_type", "operation_id", "request_id", "request_frame_sha256",
            "response_frame_sha256", "read_profile_payload_sha256",
            "qstat_executable_sha256", "qstat_executable_identity_sha256", "qstat_argv",
            "stdout_sha256", "stdout_size_bytes", "stderr_sha256", "stderr_size_bytes",
        },
        "final scheduler transport",
    )
    _require(
        transport["operation_type"] == "QueryExactJobOperation"
        and CHANNEL.OPERATION_ID_RE.fullmatch(transport["operation_id"]) is not None
        and re.fullmatch(r"direct-qstat-request-[a-f0-9]{64}", transport["request_id"]) is not None
        and transport["qstat_argv"] == [*QSTAT_ARGV_PREFIX, binding["job_id"]],
        "final scheduler transport identity differs",
    )
    for field in (
        "request_frame_sha256", "response_frame_sha256", "read_profile_payload_sha256",
        "qstat_executable_sha256", "qstat_executable_identity_sha256",
        "stdout_sha256", "stderr_sha256",
    ):
        _sha(transport[field], f"final scheduler transport {field}", allow_empty=field in {"stdout_sha256", "stderr_sha256"})
    _decimal(transport["stdout_size_bytes"], "final stdout size")
    _decimal(transport["stderr_size_bytes"], "final stderr size")
    expected_inspection_id = "direct-scheduler-inspection-" + digest(
        {
            "schema": "auto-g16-direct-scheduler-inspection-id/1",
            "acquisition_id": binding["acquisition_id"],
            "acquisition_payload_sha256": binding["acquisition_payload_sha256"],
            "qstat_evidence_sha256": scheduler["qstat_evidence_sha256"],
            "scheduler_status": scheduler["status"],
            "scheduler_state": scheduler["state"],
        }
    )
    _require(
        document["inspection_id"] == expected_inspection_id,
        "final scheduler inspection id differs",
    )
    supplied = _sha(document["evidence_sha256"], "final scheduler evidence hash")
    _require(supplied == digest({**document, "evidence_sha256": ""}), "final scheduler evidence hash differs")
    return document


class _ModuleBinding(NamedTuple):
    module: types.ModuleType
    source_sha256: str
    dependencies: tuple[types.ModuleType, ...]
    dependency_paths: tuple[str, ...]
    dependency_source_sha256: tuple[str, ...]
    entries: tuple[object, ...]
    predecessor_entries: tuple[object, ...]
    os_entries: tuple[object, ...]
    runtime_entries: tuple[object, ...]
    constants: tuple[object, ...]


def _capture_module_binding() -> _ModuleBinding:
    _require(__name__ == MODULE_NAME, "qstat acquisition owner requires its canonical module name")
    module = sys.modules.get(MODULE_NAME)
    _require(type(module) is types.ModuleType, "canonical qstat acquisition module is unavailable")
    dependencies = (LINEAGE, W5, EVIDENCE, READ_PROFILE, CHANNEL, SESSION)
    expected_directory = Path(__file__).resolve().parent
    paths = tuple(str(Path(item.__file__).resolve()) for item in dependencies)
    source_hashes = tuple(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths
    )
    _require(
        all(Path(path).parent == expected_directory for path in paths),
        "qstat acquisition predecessor module origin differs",
    )
    return _ModuleBinding(
        module,
        _EXECUTED_SOURCE_SHA256,
        dependencies,
        paths,
        source_hashes,
        (
            _require, canonical_bytes, digest, _exact, _sha, _decimal,
            _timestamp, _utc_now_text, _freshness, _b64, _unb64,
            _canonical_frame, _decode_canonical_frame, _artifact_hashes,
            _artifacts_document, _artifacts_from_document, _make_join_owners,
            _ISSUE_QUERY_ISSUANCE_JOIN, _ASSERT_QUERY_ISSUANCE_JOIN,
            _ISSUE_CONTROLLER_JOIN, _ASSERT_CONTROLLER_JOIN, _ISSUE_LINEAGE_JOIN,
            _ASSERT_LINEAGE_JOIN, _CLEAR_JOINS_AFTER_FORK, _RESULT_ISSUE,
            _RESULT_ASSERT, _RESULT_PROJECT, _RESULT_CONSUME, _CLEAR_RESULTS_AFTER_FORK,
            _INSPECTION_ISSUE, _INSPECTION_ASSERT, _INSPECTION_PROJECT,
            _INSPECTION_CONSUME_FOR_TERMINAL_FETCH,
            _CLEAR_INSPECTIONS_AFTER_FORK,
            _assert_shared_channel_query_issuance_authority,
            _assert_shared_channel_query_authority,
            _assert_exact_lineage_consumer_join,
            _request_id, build_request, validate_request, validate_response,
            _build_response,
            _normalize_observation, _production_qstat_once,
            _acquire_terminal_fetch_eligibility_once, _open_reviewed_qstat,
            _executable_identity, _identity_sha, _read_qstat_descriptor_sha256,
            _assert_qstat_descriptor_current, _exec_reviewed_qstat_child_once,
            _read_qstat_streams_until, _prepare_controller_request,
            acquire_qstat_once, _acquisition_projection,
            validate_acquisition_projection, build_final_scheduler_inspection_once,
            validate_final_inspection, DirectQstatServerOwner.production,
            DirectQstatServerOwner.handle_once, _read_stdin_frame_once,
            _server_subsystem_main, main,
        ),
        (
            LINEAGE._consume_for_exact_qstat_once,
            LINEAGE._assert_module_binding,
            LINEAGE.DirectSubmittedJobReadCapability,
            LINEAGE.DirectSubmittedJobReadLease,
            W5.validate_submission_receipt,
            W5._assert_production_binding,
            EVIDENCE.classify_qstat_bytes,
            EVIDENCE.build_qstat_evidence,
            EVIDENCE.DirectJobBinding,
            EVIDENCE.QstatObservation,
            READ_PROFILE._consume_for_q1_once,
            READ_PROFILE._assert_module_binding,
            READ_PROFILE.DirectReviewedReadProfileCapability,
            READ_PROFILE.DirectReviewedReadProfileLease,
            CHANNEL.issue_query_exact_job_operation,
            CHANNEL.run_query_channel_once,
            CHANNEL._pipe_cloexec,
            CHANNEL._close_quiet,
            CHANNEL._descriptor_execve,
            CHANNEL._read_exact_until,
            CHANNEL._require_eof_until,
            CHANNEL._write_frame_until,
            CHANNEL._wait_child_until,
            CHANNEL._QueryChildHandle,
            CHANNEL._make_query_child_owner,
            CHANNEL._assert_query_child_owner_environment,
            CHANNEL._fork_query_child_for_operation,
            CHANNEL._wait_query_child_until,
            CHANNEL._retire_query_child_bounded,
            CHANNEL._clear_query_child_owner_after_fork,
            CHANNEL._assert_production_binding,
        ),
        (
            os.open, os.read, os.close, os.fork, os.execve, os.fstat, os.stat,
            os.waitpid, os.kill, os.dup2, os._exit, os.getpid, os.lseek,
            signal.getsignal, select.select, fcntl.fcntl, time.monotonic,
        ),
        (
            base64.b64encode, base64.b64decode, binascii.Error,
            hashlib.sha256, json.loads, json.dumps, struct.pack, struct.unpack,
            stat.S_IFMT, stat.S_ISREG, stat.S_IMODE, signal.SIGTERM,
            signal.SIGKILL, signal.SIGCHLD, signal.SIG_DFL, os.WNOHANG,
            copy.deepcopy,
            dataclasses.replace, re.fullmatch, datetime, timedelta, timezone, Path,
            threading.get_ident,
            SHA_RE, ACQUISITION_ID_RE, INSPECTION_ID_RE, DECIMAL_RE,
            SIGNED_DECIMAL_RE, TIMESTAMP_RE,
            weakref.finalize, weakref.WeakKeyDictionary,
        ),
        (
            REQUEST_SCHEMA, RESPONSE_SCHEMA, ACQUISITION_SCHEMA, INSPECTION_SCHEMA,
            OWNER, OWNER_VERSION, FINAL_OWNER, FINAL_OWNER_VERSION,
            QSTAT_EXECUTABLE, QSTAT_ARGV_PREFIX, copy.deepcopy(QSTAT_ENVIRONMENT),
            MAX_QSTAT_STREAM_BYTES, MAX_QSTAT_COMBINED_BYTES,
            QSTAT_CHILD_RETIRE_GRACE_SECONDS, MAX_REQUEST_BYTES,
            MAX_RESPONSE_BYTES, MAX_FRESH_AGE_SECONDS, ZERO_SHA,
            copy.deepcopy(AUTHORITY), copy.deepcopy(FINAL_AUTHORITY),
            READ_PROFILE.FIXED_PRODUCTION_READ_PROFILE_PATH,
            EVIDENCE.SCHEDULER_DIALECT, EVIDENCE.PARSER_VERSION,
        ),
    )


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    with open(__file__, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(
        type(binding) is _ModuleBinding
        and sys.modules.get(MODULE_NAME) is binding.module
        and source_sha256 == binding.source_sha256 == _EXECUTED_SOURCE_SHA256
        and (LINEAGE, W5, EVIDENCE, READ_PROFILE, CHANNEL, SESSION) == binding.dependencies
        and tuple(str(Path(item.__file__).resolve()) for item in binding.dependencies)
        == binding.dependency_paths
        and tuple(
            hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in binding.dependency_paths
        )
        == binding.dependency_source_sha256
        and binding.entries
        == (
            _require, canonical_bytes, digest, _exact, _sha, _decimal,
            _timestamp, _utc_now_text, _freshness, _b64, _unb64,
            _canonical_frame, _decode_canonical_frame, _artifact_hashes,
            _artifacts_document, _artifacts_from_document, _make_join_owners,
            _ISSUE_QUERY_ISSUANCE_JOIN, _ASSERT_QUERY_ISSUANCE_JOIN,
            _ISSUE_CONTROLLER_JOIN, _ASSERT_CONTROLLER_JOIN, _ISSUE_LINEAGE_JOIN,
            _ASSERT_LINEAGE_JOIN, _CLEAR_JOINS_AFTER_FORK, _RESULT_ISSUE,
            _RESULT_ASSERT, _RESULT_PROJECT, _RESULT_CONSUME, _CLEAR_RESULTS_AFTER_FORK,
            _INSPECTION_ISSUE, _INSPECTION_ASSERT, _INSPECTION_PROJECT,
            _INSPECTION_CONSUME_FOR_TERMINAL_FETCH,
            _CLEAR_INSPECTIONS_AFTER_FORK,
            _assert_shared_channel_query_issuance_authority,
            _assert_shared_channel_query_authority,
            _assert_exact_lineage_consumer_join,
            _request_id, build_request, validate_request, validate_response,
            _build_response,
            _normalize_observation, _production_qstat_once,
            _acquire_terminal_fetch_eligibility_once, _open_reviewed_qstat,
            _executable_identity, _identity_sha, _read_qstat_descriptor_sha256,
            _assert_qstat_descriptor_current, _exec_reviewed_qstat_child_once,
            _read_qstat_streams_until, _prepare_controller_request,
            acquire_qstat_once, _acquisition_projection,
            validate_acquisition_projection, build_final_scheduler_inspection_once,
            validate_final_inspection, DirectQstatServerOwner.production,
            DirectQstatServerOwner.handle_once, _read_stdin_frame_once,
            _server_subsystem_main, main,
        )
        and binding.predecessor_entries
        == (
            LINEAGE._consume_for_exact_qstat_once,
            LINEAGE._assert_module_binding,
            LINEAGE.DirectSubmittedJobReadCapability,
            LINEAGE.DirectSubmittedJobReadLease,
            W5.validate_submission_receipt,
            W5._assert_production_binding,
            EVIDENCE.classify_qstat_bytes,
            EVIDENCE.build_qstat_evidence,
            EVIDENCE.DirectJobBinding,
            EVIDENCE.QstatObservation,
            READ_PROFILE._consume_for_q1_once,
            READ_PROFILE._assert_module_binding,
            READ_PROFILE.DirectReviewedReadProfileCapability,
            READ_PROFILE.DirectReviewedReadProfileLease,
            CHANNEL.issue_query_exact_job_operation,
            CHANNEL.run_query_channel_once,
            CHANNEL._pipe_cloexec,
            CHANNEL._close_quiet,
            CHANNEL._descriptor_execve,
            CHANNEL._read_exact_until,
            CHANNEL._require_eof_until,
            CHANNEL._write_frame_until,
            CHANNEL._wait_child_until,
            CHANNEL._QueryChildHandle,
            CHANNEL._make_query_child_owner,
            CHANNEL._assert_query_child_owner_environment,
            CHANNEL._fork_query_child_for_operation,
            CHANNEL._wait_query_child_until,
            CHANNEL._retire_query_child_bounded,
            CHANNEL._clear_query_child_owner_after_fork,
            CHANNEL._assert_production_binding,
        )
        and binding.os_entries
        == (
            os.open, os.read, os.close, os.fork, os.execve, os.fstat, os.stat,
            os.waitpid, os.kill, os.dup2, os._exit, os.getpid, os.lseek,
            signal.getsignal, select.select, fcntl.fcntl, time.monotonic,
        )
        and binding.runtime_entries
        == (
            base64.b64encode, base64.b64decode, binascii.Error,
            hashlib.sha256, json.loads, json.dumps, struct.pack, struct.unpack,
            stat.S_IFMT, stat.S_ISREG, stat.S_IMODE, signal.SIGTERM,
            signal.SIGKILL, signal.SIGCHLD, signal.SIG_DFL, os.WNOHANG,
            copy.deepcopy,
            dataclasses.replace, re.fullmatch, datetime, timedelta, timezone, Path,
            threading.get_ident,
            SHA_RE, ACQUISITION_ID_RE, INSPECTION_ID_RE, DECIMAL_RE,
            SIGNED_DECIMAL_RE, TIMESTAMP_RE,
            weakref.finalize, weakref.WeakKeyDictionary,
        )
        and (
            REQUEST_SCHEMA, RESPONSE_SCHEMA, ACQUISITION_SCHEMA, INSPECTION_SCHEMA,
            OWNER, OWNER_VERSION, FINAL_OWNER, FINAL_OWNER_VERSION,
            QSTAT_EXECUTABLE, QSTAT_ARGV_PREFIX, copy.deepcopy(QSTAT_ENVIRONMENT),
            MAX_QSTAT_STREAM_BYTES, MAX_QSTAT_COMBINED_BYTES,
            QSTAT_CHILD_RETIRE_GRACE_SECONDS, MAX_REQUEST_BYTES,
            MAX_RESPONSE_BYTES, MAX_FRESH_AGE_SECONDS, ZERO_SHA,
            copy.deepcopy(AUTHORITY), copy.deepcopy(FINAL_AUTHORITY),
            READ_PROFILE.FIXED_PRODUCTION_READ_PROFILE_PATH,
            EVIDENCE.SCHEDULER_DIALECT, EVIDENCE.PARSER_VERSION,
        )
        == binding.constants
        == (
            "auto-g16-direct-qstat-acquisition-request/1",
            "auto-g16-direct-qstat-acquisition-response/1",
            "gaussian-direct-qstat-acquisition/1", "gaussian-job-inspection/3",
            "auto-g16-direct-qstat-acquisition-owner",
            "direct-qstat-acquisition-owner/1",
            "auto-g16-direct-final-scheduler-inspection-owner",
            "direct-final-scheduler-inspection-owner/1",
            "/usr/bin/qstat", ("/usr/bin/qstat", "-f"), {"LANG": "C", "LC_ALL": "C"},
            65536, 65536, 2.5, 33554432, 524288, 120, "0" * 64,
            {
                "authorizes_effect": False, "scientific_acceptance": False,
                "gaussian_completion": False, "qsub": False, "qdel": False,
                "delete": False, "cleanup": False, "retry": False,
                "fetch": False, "materialize": False,
            },
            {
                "authorizes_effect": False, "scientific_acceptance": False,
                "gaussian_completion": False, "qsub": False, "qdel": False,
                "delete": False, "cleanup": False, "retry": False,
                "fetch": False, "materialize": False,
                "scheduler_evidence_only": True,
            },
            Path("/etc/auto-g16/direct-qstat-read-profile.json"),
            "pbs_legacy_v1", "pbs_legacy_v1-qstat-single-job/1",
        ),
        "qstat acquisition source, module, predecessor, or owner binding differs",
    )
    LINEAGE._assert_module_binding()
    W5._assert_production_binding()
    READ_PROFILE._assert_module_binding()
    CHANNEL._assert_production_binding()


def _after_fork_child() -> None:
    global _MODULE_BINDING
    _CLEAR_JOINS_AFTER_FORK()
    _CLEAR_RESULTS_AFTER_FORK()
    _CLEAR_INSPECTIONS_AFTER_FORK()


def _read_stdin_frame_once(deadline: float) -> bytes:
    header = CHANNEL._read_exact_until(0, 4, deadline, "qstat subsystem request header")
    size = struct.unpack("!I", header)[0]
    _require(0 < size <= MAX_REQUEST_BYTES, "qstat subsystem request size differs")
    payload = CHANNEL._read_exact_until(0, size, deadline, "qstat subsystem request")
    CHANNEL._require_eof_until(0, deadline, "qstat subsystem request")
    frame = header + payload
    _decode_canonical_frame(frame, MAX_REQUEST_BYTES, "qstat subsystem request")
    return frame


def _server_subsystem_main() -> int:
    _assert_module_binding()
    raise DirectQstatAcquisitionError(
        "standalone qstat subsystem is disabled; fixed read dispatcher required"
    )


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    _require(arguments == ["--fixed-read-subsystem"], "qstat subsystem argv differs")
    return _server_subsystem_main()


_MODULE_BINDING = _capture_module_binding()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


__all__ = [
    "DirectQstatAcquisitionError",
    "DirectQstatTransportUnknown",
    "ExactQstatAcquisitionResult",
    "GaussianJobInspection3",
    "acquire_qstat_once",
    "build_final_scheduler_inspection_once",
    "validate_acquisition_projection",
    "validate_final_inspection",
]


if __name__ == "__main__":  # pragma: no cover - fixed server subsystem only
    raise SystemExit(main())
