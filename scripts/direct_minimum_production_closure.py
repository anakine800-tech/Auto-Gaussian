#!/usr/bin/env python3
"""Exact terminal gate for the direct submit-query-fetch-materialize closure.

This owner joins an exact Q1 final inspection to one F1 fetch transition.  It
does not parse qstat, open a server path, read an artifact, write a local file,
or implement transport.  Those effects remain with Q1, F1, T4, and the shared
fixed SSH channel.  Portable projections are evidence only.
"""

from __future__ import annotations

if globals().get("_AUTO_G16_DIRECT_MINIMUM_CLOSURE_EXECUTED", False):
    raise ImportError("direct minimum closure owner module already executed")
_AUTO_G16_DIRECT_MINIMUM_CLOSURE_EXECUTED = True

import copy
import base64
import hashlib
import json
import os
import re
import sys
import threading
import types
import weakref
from pathlib import Path
from typing import Any, NamedTuple

import direct_fetch_acquisition as FETCH
import direct_local_fetch_materializer as MATERIALIZER
import direct_one_hop_transport as W5
import direct_qstat_acquisition as Q1
import direct_reviewed_read_profile as READ_PROFILE
import direct_shared_fixed_ssh_channel as CHANNEL
import direct_trusted_session_composition as SESSION


MODULE_NAME = "direct_minimum_production_closure"
OWNER = "auto-g16-direct-terminal-fetch-grant-owner"
OWNER_VERSION = "direct-terminal-fetch-grant/1"
GRANT_SCHEMA = "auto-g16-direct-terminal-fetch-grant/1"
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
GRANT_ID_RE = re.compile(r"^direct-terminal-fetch-grant-[a-f0-9]{64}$")
TERMINAL_PRESENT_STATES = frozenset({"C", "F"})
RESUME_SCHEMA = "auto-g16-direct-minimum-resume-result/1"


class DirectMinimumProductionClosureError(ValueError):
    """The exact minimum closure transition could not be proved."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectMinimumProductionClosureError(message)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DirectMinimumProductionClosureError(
            "value is not canonical JSON"
        ) from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and SHA_RE.fullmatch(value) is not None
        and value != ZERO_SHA,
        f"{label} differs",
    )
    return value


def _source_sha(module: types.ModuleType) -> str:
    path = Path(module.__file__).resolve(strict=True)
    _require(path.parent == Path(__file__).resolve().parent, "owner module origin differs")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        hasher = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
         before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns),
        "owner source identity drifted",
    )
    return hasher.hexdigest()


class TerminalFetchGrant:
    __slots__ = ("grant_id", "_key", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("terminal fetch grants are owner-issued only")

    def assert_current(self) -> None:
        _GRANT_ASSERT(self)

    def portable_projection(self) -> dict[str, Any]:
        return json.loads(_GRANT_PROJECT(self).decode("utf-8"))

    def __copy__(self) -> Any:
        raise TypeError("terminal fetch grants are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("terminal fetch grants are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("terminal fetch grants are not serializable")


class _GrantRecord(NamedTuple):
    value: TerminalFetchGrant
    pid: int
    epoch: object
    seal: object
    projection_raw: bytes


class _ExactFetchIssuanceAuthority:
    __slots__ = ("_key", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fetch issuance authorities are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("fetch issuance authorities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("fetch issuance authorities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("fetch issuance authorities are not serializable")


class _IssuanceRecord(NamedTuple):
    value: _ExactFetchIssuanceAuthority
    pid: int
    epoch: object
    seal: object
    job_id: str
    transport_profile_raw: bytes
    read_profile_raw: bytes
    grant_payload_sha256: str
    evidence_raw: bytes


class _ExactFetchClientJoin:
    __slots__ = ("_key", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fetch client joins are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("fetch client joins are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("fetch client joins are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("fetch client joins are not serializable")


class _ClientJoinRecord(NamedTuple):
    value: _ExactFetchClientJoin
    pid: int
    epoch: object
    seal: object
    job_id: str
    lineage_id: str
    target_binding_sha256: str
    grant_payload_sha256: str
    lineage_payload_sha256: str
    journal_payload_sha256: str
    remote_receipt_bytes_sha256: str


def _build_fetch_client_join_owner() -> tuple[Any, Any, Any]:
    registry: weakref.WeakKeyDictionary[
        _ExactFetchClientJoin, _ClientJoinRecord
    ] = weakref.WeakKeyDictionary()
    lock = threading.RLock()
    epoch = object()

    def issue(
        projection: dict[str, Any],
        target_capability: MATERIALIZER.LocalFetchTargetCapability,
    ) -> _ExactFetchClientJoin:
        projection = validate_terminal_fetch_grant_projection(projection)
        _require(
            type(target_capability) is MATERIALIZER.LocalFetchTargetCapability,
            "exact local target capability is required",
        )
        target = target_capability.portable_projection()
        binding = target["binding"]
        _require(
            binding["project"] == projection["binding"]["project"]
            and binding["attempt_id"] == projection["binding"]["attempt_id"]
            and binding["job_id"] == projection["binding"]["job_id"]
            and binding["read_profile_sha256"]
            == projection["qstat"]["read_profile_payload_sha256"],
            "terminal grant and local target are spliced",
        )
        value = object.__new__(_ExactFetchClientJoin)
        value._key = id(value)
        value._seal = object()
        record = _ClientJoinRecord(
            value, os.getpid(), epoch, value._seal,
            projection["binding"]["job_id"],
            projection["binding"]["lineage_id"],
            target["target_binding_sha256"],
            projection["grant_payload_sha256"],
            projection["binding"]["lineage_payload_sha256"],
            projection["binding"]["w2_journal_payload_sha256"],
            binding["w5_receipt_sha256"],
        )
        with lock:
            registry[value] = record
        return value

    def consume(
        value: object,
        target_capability: object,
        operation: object,
        acquisition_projection: dict[str, Any],
    ) -> None:
        _assert_module_binding()
        _require(
            type(target_capability) is MATERIALIZER.LocalFetchTargetCapability
            and type(operation) is CHANNEL.FetchTerminalMinimumBundleOperation,
            "exact target and fetch operation are required",
        )
        target = target_capability.portable_projection()
        operation_projection = operation.portable_projection()
        acquisition = FETCH.validate_acquisition_projection(
            acquisition_projection
        )
        with lock:
            record = (
                registry.get(value) if type(value) is _ExactFetchClientJoin
                else None
            )
            _require(
                type(record) is _ClientJoinRecord
                and record.value is value
                and record.pid == os.getpid()
                and record.epoch is epoch
                and record.seal is value._seal
                and record.job_id == operation_projection["job_id"]
                == acquisition["binding"]["job_id"]
                and record.lineage_id == acquisition["lineage_id"]
                and record.lineage_payload_sha256
                == acquisition["lineage_result_payload_sha256"]
                and record.journal_payload_sha256
                == acquisition["durable"]["journal_payload_sha256"]
                and record.remote_receipt_bytes_sha256
                == acquisition["binding"]["remote_receipt_bytes_sha256"]
                and record.grant_payload_sha256
                == acquisition["controller_grant_payload_sha256"]
                and record.target_binding_sha256
                == target["target_binding_sha256"],
                "fetch client join is foreign, forked, spliced, or terminal",
            )
            del registry[value]

    def after_fork() -> None:
        nonlocal lock, epoch
        registry.clear()
        lock = threading.RLock()
        epoch = object()

    return issue, consume, after_fork


(
    _ISSUE_FETCH_CLIENT_JOIN,
    _assert_f1_controller_join_once,
    _CLEAR_FETCH_CLIENT_JOIN_AFTER_FORK,
) = _build_fetch_client_join_owner()


def _build_fetch_issuance_owner() -> tuple[Any, Any, Any]:
    registry: weakref.WeakKeyDictionary[
        _ExactFetchIssuanceAuthority, _IssuanceRecord
    ] = weakref.WeakKeyDictionary()
    lock = threading.RLock()
    epoch = object()

    def issue(
        projection: dict[str, Any],
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
        portable_receipt_bytes: bytes,
        artifacts: SESSION.DirectServerSessionArtifacts,
    ) -> _ExactFetchIssuanceAuthority:
        projection = validate_terminal_fetch_grant_projection(projection)
        CHANNEL.load_read_profile(read_profile_raw, transport_profile_raw)
        value = object.__new__(_ExactFetchIssuanceAuthority)
        value._key = id(value)
        value._seal = object()
        _require(
            type(portable_receipt_bytes) is bytes
            and 0 < len(portable_receipt_bytes) <= CHANNEL.MAX_CONTROL_FRAME_BYTES
            and type(artifacts) is SESSION.DirectServerSessionArtifacts,
            "fetch issuance evidence differs",
        )
        evidence = {
            "schema": "auto-g16-direct-fetch-server-evidence/1",
            "portable_receipt": base64.b64encode(
                portable_receipt_bytes
            ).decode("ascii"),
            "artifacts": {
                name: base64.b64encode(getattr(artifacts, name)).decode("ascii")
                for name in artifacts.__dataclass_fields__
            },
            "grant_payload_sha256": projection["grant_payload_sha256"],
            "authority": {
                "authorizes_effect": False,
                "qsub_calls": "0",
                "qdel_calls": "0",
            },
        }
        evidence_raw = canonical_bytes(evidence)
        _require(
            len(evidence_raw) <= CHANNEL.MAX_CONTROL_FRAME_BYTES,
            "fetch issuance evidence exceeds its fixed cap",
        )
        record = _IssuanceRecord(
            value, os.getpid(), epoch, value._seal,
            projection["binding"]["job_id"], bytes(transport_profile_raw),
            bytes(read_profile_raw), projection["grant_payload_sha256"],
            evidence_raw,
        )
        with lock:
            registry[value] = record
        return value

    def consume(
        value: object,
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
    ) -> tuple[str, bytes]:
        _assert_module_binding()
        with lock:
            record = (
                registry.get(value)
                if type(value) is _ExactFetchIssuanceAuthority
                else None
            )
            _require(
                type(record) is _IssuanceRecord
                and record.value is value
                and record.pid == os.getpid()
                and record.epoch is epoch
                and record.seal is value._seal
                and record.transport_profile_raw == transport_profile_raw
                and record.read_profile_raw == read_profile_raw,
                "fetch issuance authority is foreign, forged, forked, spliced, or terminal",
            )
            del registry[value]
        return record.job_id, bytes(record.evidence_raw)

    def after_fork() -> None:
        nonlocal lock, epoch
        registry.clear()
        lock = threading.RLock()
        epoch = object()

    return issue, consume, after_fork


(
    _ISSUE_FETCH_ISSUANCE_AUTHORITY,
    _assert_shared_channel_fetch_issuance_authority,
    _CLEAR_FETCH_ISSUANCE_AFTER_FORK,
) = _build_fetch_issuance_owner()


def validate_terminal_fetch_grant_projection(value: Any) -> dict[str, Any]:
    _require(
        type(value) is dict
        and set(value) == {
            "schema", "owner", "owner_version", "grant_id", "classification",
            "binding", "qstat", "successor", "authority", "grant_payload_sha256",
        },
        "terminal fetch grant fields differ",
    )
    document = copy.deepcopy(value)
    _require(
        document["schema"] == GRANT_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION
        and GRANT_ID_RE.fullmatch(document["grant_id"] or "") is not None,
        "terminal fetch grant constants differ",
    )
    classification = document["classification"]
    _require(
        type(classification) is dict
        and set(classification) == {
            "status", "state", "record_present", "pbs_state", "freshness",
            "terminal_fetch_allowed",
        }
        and classification["freshness"] == "fresh"
        and classification["terminal_fetch_allowed"] is True,
        "terminal fetch classification differs",
    )
    allowed_present = (
        classification["status"] == "present"
        and classification["state"] == "terminal"
        and classification["record_present"] is True
        and classification["pbs_state"] in TERMINAL_PRESENT_STATES
    )
    allowed_absent = (
        classification["status"] == "absent"
        and classification["state"] == "absent"
        and classification["record_present"] is False
        and classification["pbs_state"] is None
    )
    _require(allowed_present or allowed_absent, "nonterminal inspection cannot grant fetch")
    binding = document["binding"]
    _require(
        type(binding) is dict
        and set(binding) == {
            "project", "job_id", "attempt_id", "input_sha256",
            "authorization_payload_sha256", "authorization_scope_sha256",
            "transport_profile_payload_sha256", "w5_result_payload_sha256",
            "w2_journal_payload_sha256", "lineage_id", "lineage_payload_sha256",
            "qstat_acquisition_id", "qstat_acquisition_payload_sha256",
            "final_inspection_id", "final_inspection_evidence_sha256",
            "final_inspection_bytes_sha256",
        },
        "terminal fetch binding fields differ",
    )
    _require(
        type(binding["project"]) is str and bool(binding["project"])
        and CHANNEL.JOB_ID_RE.fullmatch(binding["job_id"]) is not None
        and Q1.ACQUISITION_ID_RE.fullmatch(binding["qstat_acquisition_id"]) is not None
        and Q1.INSPECTION_ID_RE.fullmatch(binding["final_inspection_id"]) is not None,
        "terminal fetch binding identifiers differ",
    )
    for field, item in binding.items():
        if field.endswith("sha256"):
            _sha(item, f"terminal fetch binding {field}")
    qstat = document["qstat"]
    _require(
        type(qstat) is dict
        and set(qstat) == {
            "qstat_evidence_sha256", "operation_id", "request_id",
            "request_frame_sha256", "response_frame_sha256",
            "read_profile_payload_sha256", "qstat_executable_sha256",
            "qstat_executable_identity_sha256",
        },
        "terminal fetch qstat fields differ",
    )
    for field, item in qstat.items():
        if field.endswith("sha256"):
            _sha(item, f"terminal fetch qstat {field}")
    _require(
        CHANNEL.OPERATION_ID_RE.fullmatch(qstat["operation_id"]) is not None
        and re.fullmatch(r"direct-qstat-request-[a-f0-9]{64}", qstat["request_id"] or "") is not None,
        "terminal fetch qstat identifiers differ",
    )
    successor = document["successor"]
    _require(
        type(successor) is dict
        and set(successor) == {
            "operation", "f1_source_sha256", "channel_source_sha256",
            "materializer_source_sha256", "single_use",
        }
        and successor["operation"] == "fetch_terminal_minimum_bundle"
        and successor["single_use"] is True,
        "terminal fetch successor differs",
    )
    for field in (
        "f1_source_sha256", "channel_source_sha256", "materializer_source_sha256",
    ):
        _sha(successor[field], f"terminal fetch successor {field}")
    _require(
        document["authority"] == {
            "portable_projection_is_authority": False,
            "authorizes_effect": False,
            "authorizes_fetch_transition": False,
            "authorizes_materialization": False,
            "scientific_acceptance": False,
            "gaussian_completion": False,
            "qsub": False,
            "qdel": False,
            "cancel": False,
            "retry": False,
            "delete": False,
            "cleanup": False,
            "single_use": True,
            "automatic_retry": False,
        },
        "terminal fetch portable authority differs",
    )
    expected_id = "direct-terminal-fetch-grant-" + digest({
        "schema": "auto-g16-direct-terminal-fetch-grant-id/1",
        "classification": classification,
        "binding": binding,
        "qstat": qstat,
        "successor": successor,
    })
    _require(document["grant_id"] == expected_id, "terminal fetch grant id differs")
    _sha(document["grant_payload_sha256"], "terminal fetch grant payload")
    _require(
        document["grant_payload_sha256"]
        == digest({**document, "grant_payload_sha256": ""}),
        "terminal fetch grant payload hash differs",
    )
    return document


def _inspection_is_fresh_terminal(
    inspection_document: dict[str, Any],
) -> bool:
    scheduler = inspection_document["scheduler"]
    return (
        scheduler["freshness"] == "fresh"
        and (
            (
                scheduler["status"] == "present"
                and scheduler["state"] == "terminal"
                and scheduler["record_present"] is True
                and scheduler["pbs_state"] in TERMINAL_PRESENT_STATES
            )
            or (
                scheduler["status"] == "absent"
                and scheduler["state"] == "absent"
                and scheduler["record_present"] is False
                and scheduler["pbs_state"] is None
            )
        )
    )


def _build_grant_owner() -> tuple[Any, ...]:
    registry: weakref.WeakKeyDictionary[TerminalFetchGrant, _GrantRecord] = (
        weakref.WeakKeyDictionary()
    )
    used_inspections: set[str] = set()
    lock = threading.RLock()
    epoch = object()

    def exact(value: object) -> _GrantRecord:
        _assert_module_binding()
        with lock:
            record = registry.get(value) if type(value) is TerminalFetchGrant else None
            _require(
                type(record) is _GrantRecord
                and record.value is value
                and record.pid == os.getpid()
                and record.epoch is epoch
                and record.seal is value._seal
                and record.value.grant_id
                == json.loads(record.projection_raw)["grant_id"],
                "terminal fetch grant is foreign, forged, forked, rebound, or terminal",
            )
            validate_terminal_fetch_grant_projection(
                json.loads(record.projection_raw.decode("utf-8"))
            )
            return record

    def route(
        inspection: Q1.GaussianJobInspection3,
    ) -> tuple[dict[str, Any], TerminalFetchGrant | None]:
        inspection_document, inspection_raw_sha256 = (
            Q1._INSPECTION_CONSUME_FOR_TERMINAL_FETCH(inspection)
        )
        scheduler = inspection_document["scheduler"]
        binding = inspection_document["binding"]
        allowed = _inspection_is_fresh_terminal(inspection_document)
        if not allowed:
            return copy.deepcopy(inspection_document), None
        _require(
            inspection_document["inspection_id"] not in used_inspections,
            "final inspection already issued a fetch grant",
        )
        document = {
            "schema": GRANT_SCHEMA,
            "owner": OWNER,
            "owner_version": OWNER_VERSION,
            "grant_id": "",
            "classification": {
                "status": scheduler["status"],
                "state": scheduler["state"],
                "record_present": scheduler["record_present"],
                "pbs_state": scheduler["pbs_state"],
                "freshness": scheduler["freshness"],
                "terminal_fetch_allowed": True,
            },
            "binding": {
                "project": binding["project"],
                "job_id": binding["job_id"],
                "attempt_id": binding["attempt_id"],
                "input_sha256": binding["input_sha256"],
                "authorization_payload_sha256": binding["authorization_payload_sha256"],
                "authorization_scope_sha256": binding["authorization_scope_sha256"],
                "transport_profile_payload_sha256": binding["transport_profile_payload_sha256"],
                "w5_result_payload_sha256": binding["w5_result_payload_sha256"],
                "w2_journal_payload_sha256": binding["w2_journal_payload_sha256"],
                "lineage_id": binding["lineage_id"],
                "lineage_payload_sha256": binding["lineage_payload_sha256"],
                "qstat_acquisition_id": binding["acquisition_id"],
                "qstat_acquisition_payload_sha256": binding["acquisition_payload_sha256"],
                "final_inspection_id": inspection_document["inspection_id"],
                "final_inspection_evidence_sha256": inspection_document["evidence_sha256"],
                "final_inspection_bytes_sha256": inspection_raw_sha256,
            },
            "qstat": {
                "qstat_evidence_sha256": scheduler["qstat_evidence_sha256"],
                "operation_id": inspection_document["transport"]["operation_id"],
                "request_id": inspection_document["transport"]["request_id"],
                "request_frame_sha256": inspection_document["transport"]["request_frame_sha256"],
                "response_frame_sha256": inspection_document["transport"]["response_frame_sha256"],
                "read_profile_payload_sha256": inspection_document["transport"]["read_profile_payload_sha256"],
                "qstat_executable_sha256": inspection_document["transport"]["qstat_executable_sha256"],
                "qstat_executable_identity_sha256": inspection_document["transport"]["qstat_executable_identity_sha256"],
            },
            "successor": {
                "operation": "fetch_terminal_minimum_bundle",
                "f1_source_sha256": _MODULE_BINDING.fetch_source_sha256,
                "channel_source_sha256": _MODULE_BINDING.channel_source_sha256,
                "materializer_source_sha256": _MODULE_BINDING.materializer_source_sha256,
                "single_use": True,
            },
            "authority": {
                "portable_projection_is_authority": False,
                "authorizes_effect": False,
                "authorizes_fetch_transition": False,
                "authorizes_materialization": False,
                "scientific_acceptance": False,
                "gaussian_completion": False,
                "qsub": False,
                "qdel": False,
                "cancel": False,
                "retry": False,
                "delete": False,
                "cleanup": False,
                "single_use": True,
                "automatic_retry": False,
            },
            "grant_payload_sha256": "",
        }
        document["grant_id"] = "direct-terminal-fetch-grant-" + digest({
            "schema": "auto-g16-direct-terminal-fetch-grant-id/1",
            "classification": document["classification"],
            "binding": document["binding"],
            "qstat": document["qstat"],
            "successor": document["successor"],
        })
        document["grant_payload_sha256"] = digest(document)
        projection = validate_terminal_fetch_grant_projection(document)
        value = object.__new__(TerminalFetchGrant)
        value.grant_id = projection["grant_id"]
        value._key = id(value)
        value._seal = object()
        record = _GrantRecord(
            value, os.getpid(), epoch, value._seal, canonical_bytes(projection)
        )
        with lock:
            registry[value] = record
            used_inspections.add(inspection_document["inspection_id"])
        exact(value)
        return copy.deepcopy(inspection_document), value

    def issue(inspection: Q1.GaussianJobInspection3) -> TerminalFetchGrant:
        _inspection_document, value = route(inspection)
        _require(
            type(value) is TerminalFetchGrant,
            "final inspection is not fresh terminal fetch evidence",
        )
        return value

    def assert_current(value: object) -> None:
        exact(value)

    def project(value: object) -> bytes:
        return bytes(exact(value).projection_raw)

    def consume(
        value: object,
        portable_receipt_bytes: bytes,
        artifacts: SESSION.DirectServerSessionArtifacts,
        read_profile_capability: READ_PROFILE.DirectReviewedReadProfileCapability,
        target_capability: MATERIALIZER.LocalFetchTargetCapability,
    ) -> tuple[
        dict[str, Any], _ExactFetchIssuanceAuthority, _ExactFetchClientJoin,
        READ_PROFILE.DirectReviewedReadProfileLease, bytes,
    ]:
        record = exact(value)
        # A grant authorizes at most one attempt.  Terminalize it before any
        # caller-controlled bytes are decoded or any downstream capability is
        # consumed, so malformed/spliced first attempts can never be repaired
        # into a second effect attempt.
        with lock:
            _require(registry.get(value) is record, "terminal fetch grant consume raced")
            del registry[value]
        lease = None
        try:
            _require(
                type(portable_receipt_bytes) is bytes
                and bool(portable_receipt_bytes)
                and type(artifacts) is SESSION.DirectServerSessionArtifacts,
                "exact portable receipt bytes and server session artifacts are required",
            )
            lease, read_profile_raw, read_projection = (
                READ_PROFILE._consume_for_q1_once(read_profile_capability)
            )
        except BaseException:
            if type(target_capability) is MATERIALIZER.LocalFetchTargetCapability:
                try:
                    target_capability.abandon_once()
                except BaseException:
                    pass
            raise
        try:
            projection = validate_terminal_fetch_grant_projection(
                json.loads(record.projection_raw.decode("utf-8"))
            )
            try:
                receipt = W5.validate_submission_receipt(
                    json.loads(portable_receipt_bytes.decode("utf-8"))
                )
                authorization = SESSION.W1.validate_direct_execution_authorization(
                    json.loads(artifacts.authorization.decode("utf-8"))
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DirectMinimumProductionClosureError(
                    "portable submission receipt bytes are malformed"
                ) from exc
            _require(
                W5.canonical_bytes(receipt) == portable_receipt_bytes
                and receipt["project"] == projection["binding"]["project"]
                and receipt["attempt_id"] == projection["binding"]["attempt_id"]
                and receipt["input_sha256"] == projection["binding"]["input_sha256"]
                and receipt["authorization_payload_sha256"]
                == projection["binding"]["authorization_payload_sha256"]
                and authorization["scope"]["authorization_scope_sha256"]
                == projection["binding"]["authorization_scope_sha256"]
                and receipt["transport_profile_payload_sha256"]
                == projection["binding"]["transport_profile_payload_sha256"]
                and receipt["result_payload_sha256"]
                == projection["binding"]["w5_result_payload_sha256"]
                and receipt["qsub"]["job_id"] == projection["binding"]["job_id"]
                and receipt["qsub"]["calls"] == "1",
                "terminal grant and exact W5 receipt are spliced",
            )
            transport_profile = CHANNEL.load_transport_profile(
                artifacts.transport_profile
            )
            _require(
                projection["binding"]["transport_profile_payload_sha256"]
                == transport_profile["profile_payload_sha256"]
                and projection["qstat"]["read_profile_payload_sha256"]
                == read_projection["profile_payload_sha256"]
                and hashlib.sha256(artifacts.transport_profile).hexdigest()
                == read_projection["transport_profile_bytes_sha256"],
                "terminal grant, transport profile, or read profile is spliced",
            )
            authority = _ISSUE_FETCH_ISSUANCE_AUTHORITY(
                projection,
                artifacts.transport_profile,
                read_profile_raw,
                portable_receipt_bytes,
                artifacts,
            )
            client_join = _ISSUE_FETCH_CLIENT_JOIN(
                projection, target_capability,
            )
            return projection, authority, client_join, lease, read_profile_raw
        except BaseException:
            if lease is not None:
                lease.close_once()
            if type(target_capability) is MATERIALIZER.LocalFetchTargetCapability:
                try:
                    target_capability.abandon_once()
                except BaseException:
                    pass
            raise

    def after_fork() -> None:
        nonlocal lock, epoch
        registry.clear()
        used_inspections.clear()
        lock = threading.RLock()
        epoch = object()

    return route, issue, assert_current, project, consume, after_fork


(
    _ROUTE_INSPECTION_ONCE,
    _GRANT_ISSUE,
    _GRANT_ASSERT,
    _GRANT_PROJECT,
    _GRANT_CONSUME_FOR_F1,
    _GRANT_CLEAR_AFTER_FORK,
) = _build_grant_owner()


def issue_terminal_fetch_grant_once(
    inspection: Q1.GaussianJobInspection3,
) -> TerminalFetchGrant:
    """Consume one exact Q1 final inspection into a terminal-only grant."""

    _assert_module_binding()
    _require(
        type(inspection) is Q1.GaussianJobInspection3,
        "exact Q1 final inspection is required",
    )
    return _GRANT_ISSUE(inspection)


def validate_minimum_resume_result(value: Any) -> dict[str, Any]:
    """Validate the closed, portable result union; never issue authority."""

    _require(
        type(value) is dict and set(value) == {
            "schema", "status", "submission", "query",
            "terminal_fetch_grant", "materialization_manifest", "authority",
            "result_payload_sha256",
        },
        "minimum resume result fields differ",
    )
    document = copy.deepcopy(value)
    _require(
        document["schema"] == RESUME_SCHEMA
        and document["status"] in {
            "query_nonterminal", "query_unknown",
            "query_transport_unknown", "materialized",
        },
        "minimum resume result constants differ",
    )
    submission = document["submission"]
    _require(
        type(submission) is dict and set(submission) == {
            "receipt_bytes_sha256", "result_payload_sha256", "project",
            "attempt_id", "job_id", "prior_submission_qsub_calls",
        }
        and submission["prior_submission_qsub_calls"] == "1"
        and type(submission["project"]) is str and bool(submission["project"])
        and type(submission["attempt_id"]) is str and bool(submission["attempt_id"])
        and CHANNEL.JOB_ID_RE.fullmatch(submission["job_id"] or "") is not None,
        "minimum resume submission binding differs",
    )
    _sha(submission["receipt_bytes_sha256"], "minimum resume receipt bytes")
    _sha(submission["result_payload_sha256"], "minimum resume receipt result")
    query = document["query"]
    _require(
        type(query) is dict and set(query) == {
            "attempted", "inspection", "transport_unknown",
        }
        and query["attempted"] is True
        and type(query["transport_unknown"]) is bool,
        "minimum resume query fields differ",
    )
    status = document["status"]
    inspection = query["inspection"]
    grant = document["terminal_fetch_grant"]
    manifest = document["materialization_manifest"]
    if status == "query_transport_unknown":
        _require(
            query["transport_unknown"] is True
            and inspection is None and grant is None and manifest is None,
            "transport-unknown resume result differs",
        )
    else:
        _require(
            query["transport_unknown"] is False and type(inspection) is dict,
            "resume inspection evidence differs",
        )
        inspection = Q1.validate_final_inspection(inspection)
        binding = inspection["binding"]
        _require(
            binding["project"] == submission["project"]
            and binding["attempt_id"] == submission["attempt_id"]
            and binding["job_id"] == submission["job_id"],
            "resume inspection and submission are spliced",
        )
        query["inspection"] = inspection
    materialized = status == "materialized"
    if materialized:
        grant = validate_terminal_fetch_grant_projection(grant)
        manifest = MATERIALIZER.validate_manifest(manifest)
        inspection_binding = inspection["binding"]
        inspection_scheduler = inspection["scheduler"]
        inspection_transport = inspection["transport"]
        expected_grant_binding = {
            "project": inspection_binding["project"],
            "job_id": inspection_binding["job_id"],
            "attempt_id": inspection_binding["attempt_id"],
            "input_sha256": inspection_binding["input_sha256"],
            "authorization_payload_sha256": inspection_binding[
                "authorization_payload_sha256"
            ],
            "authorization_scope_sha256": inspection_binding[
                "authorization_scope_sha256"
            ],
            "transport_profile_payload_sha256": inspection_binding[
                "transport_profile_payload_sha256"
            ],
            "w5_result_payload_sha256": inspection_binding[
                "w5_result_payload_sha256"
            ],
            "w2_journal_payload_sha256": inspection_binding[
                "w2_journal_payload_sha256"
            ],
            "lineage_id": inspection_binding["lineage_id"],
            "lineage_payload_sha256": inspection_binding[
                "lineage_payload_sha256"
            ],
            "qstat_acquisition_id": inspection_binding["acquisition_id"],
            "qstat_acquisition_payload_sha256": inspection_binding[
                "acquisition_payload_sha256"
            ],
            "final_inspection_id": inspection["inspection_id"],
            "final_inspection_evidence_sha256": inspection["evidence_sha256"],
            "final_inspection_bytes_sha256": hashlib.sha256(
                canonical_bytes(inspection)
            ).hexdigest(),
        }
        expected_grant_qstat = {
            "qstat_evidence_sha256": inspection_scheduler[
                "qstat_evidence_sha256"
            ],
            "operation_id": inspection_transport["operation_id"],
            "request_id": inspection_transport["request_id"],
            "request_frame_sha256": inspection_transport[
                "request_frame_sha256"
            ],
            "response_frame_sha256": inspection_transport[
                "response_frame_sha256"
            ],
            "read_profile_payload_sha256": inspection_transport[
                "read_profile_payload_sha256"
            ],
            "qstat_executable_sha256": inspection_transport[
                "qstat_executable_sha256"
            ],
            "qstat_executable_identity_sha256": inspection_transport[
                "qstat_executable_identity_sha256"
            ],
        }
        expected_classification = {
            "status": inspection_scheduler["status"],
            "state": inspection_scheduler["state"],
            "record_present": inspection_scheduler["record_present"],
            "pbs_state": inspection_scheduler["pbs_state"],
            "freshness": inspection_scheduler["freshness"],
            "terminal_fetch_allowed": True,
        }
        _require(
            _inspection_is_fresh_terminal(inspection)
            and inspection_binding["w5_result_payload_sha256"]
            == submission["result_payload_sha256"]
            and grant["classification"] == expected_classification
            and grant["binding"] == expected_grant_binding
            and grant["qstat"] == expected_grant_qstat
            and manifest["binding"]["project"] == submission["project"]
            and manifest["binding"]["attempt_id"] == submission["attempt_id"]
            and manifest["binding"]["job_id"] == submission["job_id"]
            and manifest["binding"]["w5_receipt_sha256"]
            == submission["receipt_bytes_sha256"]
            and manifest["binding"]["read_profile_sha256"]
            == grant["qstat"]["read_profile_payload_sha256"]
            and manifest["stream"]["stream_mode"]
            == MATERIALIZER.CLOSED_STREAM_MODE
            and manifest["authority"]["remote_fetch_performed"] is True
            and manifest["authority"]["scheduler_inspection_performed"] is True
            and manifest["integration"]["production_integration"] is True,
            "materialized resume result is spliced",
        )
        document["terminal_fetch_grant"] = grant
        document["materialization_manifest"] = manifest
    else:
        _require(
            grant is None and manifest is None,
            "query-only resume result claimed terminal artifacts",
        )
        if status == "query_unknown":
            _require(
                inspection["scheduler"]["status"] == "unknown"
                or inspection["scheduler"]["freshness"] != "fresh",
                "query-unknown resume result has non-unknown inspection",
            )
        elif status == "query_nonterminal":
            _require(
                inspection["scheduler"]["status"] != "unknown"
                and inspection["scheduler"]["freshness"] == "fresh"
                and not _inspection_is_fresh_terminal(inspection),
                "query-nonterminal resume result has terminal or unknown inspection",
            )
    _require(
        document["authority"] == {
            "portable_result": True,
            "authorizes_effect": False,
            "this_call_qsub_calls": "0",
            "qdel_calls": "0",
            "automatic_retry": False,
            "fetch_performed": materialized,
            "local_materialization_performed": materialized,
            "cancel_performed": False,
            "advanced_inspect_performed": False,
            "scientific_acceptance": False,
            "explicit_future_query_required": not materialized,
        },
        "minimum resume authority differs",
    )
    _sha(document["result_payload_sha256"], "minimum resume result payload")
    _require(
        document["result_payload_sha256"]
        == digest({**document, "result_payload_sha256": ""}),
        "minimum resume result payload hash differs",
    )
    return document


def _resume_result(
    receipt_raw: bytes,
    receipt: dict[str, Any],
    status: str,
    inspection: dict[str, Any] | None,
    grant: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    materialized = status == "materialized"
    document = {
        "schema": RESUME_SCHEMA,
        "status": status,
        "submission": {
            "receipt_bytes_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "result_payload_sha256": receipt["result_payload_sha256"],
            "project": receipt["project"],
            "attempt_id": receipt["attempt_id"],
            "job_id": receipt["qsub"]["job_id"],
            "prior_submission_qsub_calls": "1",
        },
        "query": {
            "attempted": True,
            "inspection": copy.deepcopy(inspection),
            "transport_unknown": status == "query_transport_unknown",
        },
        "terminal_fetch_grant": copy.deepcopy(grant),
        "materialization_manifest": copy.deepcopy(manifest),
        "authority": {
            "portable_result": True,
            "authorizes_effect": False,
            "this_call_qsub_calls": "0",
            "qdel_calls": "0",
            "automatic_retry": False,
            "fetch_performed": materialized,
            "local_materialization_performed": materialized,
            "cancel_performed": False,
            "advanced_inspect_performed": False,
            "scientific_acceptance": False,
            "explicit_future_query_required": not materialized,
        },
        "result_payload_sha256": "",
    }
    document["result_payload_sha256"] = digest(document)
    return validate_minimum_resume_result(document)


def submit_minimum_once(
    artifacts: SESSION.DirectServerSessionArtifacts,
) -> bytes:
    """Perform the sole qsub transition and return canonical receipt bytes."""

    _assert_module_binding()
    _require(
        type(artifacts) is SESSION.DirectServerSessionArtifacts,
        "exact reviewed server session artifacts are required",
    )
    receipt = W5.run_controller_once(artifacts)
    return canonical_bytes(W5.validate_submission_receipt(receipt))


def canonical_completed_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    """Encode one validated completed W5 receipt for a later read invocation."""

    _assert_module_binding()
    return canonical_bytes(W5.validate_submission_receipt(receipt))


def resume_minimum_once(
    portable_receipt_bytes: bytes,
    artifacts: SESSION.DirectServerSessionArtifacts,
) -> dict[str, Any]:
    """Query an existing submission once; fetch only when freshly terminal.

    This successor contains no qsub call.  Q/R/unknown/stale observations
    return a non-authorizing query result that may later be queried again with
    the same exact durable receipt; they never route back through submission.
    """

    _assert_module_binding()
    _require(
        type(portable_receipt_bytes) is bytes and bool(portable_receipt_bytes)
        and type(artifacts) is SESSION.DirectServerSessionArtifacts,
        "exact durable receipt bytes and reviewed server artifacts are required",
    )
    try:
        receipt = W5.validate_submission_receipt(
            json.loads(portable_receipt_bytes.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectMinimumProductionClosureError(
            "portable submission receipt bytes are malformed"
        ) from exc
    _require(
        W5.canonical_bytes(receipt) == portable_receipt_bytes
        and receipt["qsub"]["calls"] == "1",
        "durable submission receipt bytes differ",
    )
    receipt_raw = portable_receipt_bytes
    query_profile = READ_PROFILE.DirectReviewedReadProfileOwner.production().issue_once(
        artifacts.transport_profile
    )
    try:
        acquisition = Q1.acquire_qstat_once(
            receipt_raw, artifacts, query_profile,
        )
    except Q1.DirectQstatTransportUnknown:
        return _resume_result(
            receipt_raw, receipt, "query_transport_unknown",
            None, None, None,
        )
    inspection = Q1.build_final_scheduler_inspection_once(acquisition)
    inspection_document, grant = _ROUTE_INSPECTION_ONCE(inspection)
    scheduler = inspection_document["scheduler"]
    if grant is None:
        return _resume_result(
            receipt_raw,
            receipt,
            (
                "query_unknown"
                if scheduler["status"] == "unknown"
                or scheduler["freshness"] != "fresh"
                else "query_nonterminal"
            ),
            inspection_document,
            None,
            None,
        )
    fetch_profile = READ_PROFILE.DirectReviewedReadProfileOwner.production().issue_once(
        artifacts.transport_profile
    )
    fetch_profile_projection = fetch_profile.portable_projection()
    target = MATERIALIZER.LocalFetchTargetOwner.production().issue_target_once(
        project=receipt["project"],
        attempt_id=receipt["attempt_id"],
        job_id=receipt["qsub"]["job_id"],
        w5_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
        read_profile_sha256=fetch_profile_projection[
            "profile_payload_sha256"
        ],
    )
    read_lease = None
    channel_result = None
    stream = None
    try:
        (
            grant_projection,
            issuance_authority,
            client_join,
            read_lease,
            read_profile_raw,
        ) = _GRANT_CONSUME_FOR_F1(
            grant, receipt_raw, artifacts, fetch_profile, target,
        )
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            artifacts.transport_profile,
            read_profile_raw,
            issuance_authority,
        )
        request_frame = CHANNEL.project_fetch_request_frame_for_review(operation)
        channel_result = CHANNEL.run_fetch_channel_once(
            operation, request_frame,
        )
        stream = FETCH.acquire_controller_fetch_stream_once(
            target, operation, channel_result, client_join,
        )
        channel_result = None
        stream_lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(
            target, stream,
        )
        stream = None
        manifest = MATERIALIZER.materialize_direct_fetch_once(
            target, stream_lease,
        )
        return _resume_result(
            receipt_raw, receipt, "materialized",
            inspection_document, grant_projection, manifest,
        )
    finally:
        if stream is not None:
            try:
                stream.abandon_once()
            except BaseException:
                pass
        if channel_result is not None:
            try:
                CHANNEL._FETCH_STREAM_ABANDON(channel_result[0])
            except BaseException:
                pass
        if read_lease is not None:
            try:
                read_lease.close_once()
            except BaseException:
                pass
        try:
            target.abandon_once()
        except BaseException:
            pass


class _ModuleBinding(NamedTuple):
    module: types.ModuleType
    source_sha256: str
    q1_source_sha256: str
    w5_source_sha256: str
    fetch_source_sha256: str
    channel_source_sha256: str
    materializer_source_sha256: str
    entries: tuple[object, ...]


def _capture_module_binding() -> _ModuleBinding:
    module = sys.modules.get(MODULE_NAME)
    _require(
        __name__ == MODULE_NAME and type(module) is types.ModuleType,
        "minimum closure owner requires canonical import",
    )
    return _ModuleBinding(
        module,
        _source_sha(module),
        _source_sha(Q1),
        _source_sha(W5),
        _source_sha(FETCH),
        _source_sha(CHANNEL),
        _source_sha(MATERIALIZER),
        (
            validate_terminal_fetch_grant_projection,
            _inspection_is_fresh_terminal,
            validate_minimum_resume_result,
            _resume_result,
            issue_terminal_fetch_grant_once,
            submit_minimum_once,
            canonical_completed_receipt_bytes,
            resume_minimum_once,
            _GRANT_ISSUE,
            _ROUTE_INSPECTION_ONCE,
            _GRANT_ASSERT,
            _GRANT_PROJECT,
            _GRANT_CONSUME_FOR_F1,
            _GRANT_CLEAR_AFTER_FORK,
            _ISSUE_FETCH_ISSUANCE_AUTHORITY,
            _assert_shared_channel_fetch_issuance_authority,
            _CLEAR_FETCH_ISSUANCE_AFTER_FORK,
            _ISSUE_FETCH_CLIENT_JOIN,
            _assert_f1_controller_join_once,
            _CLEAR_FETCH_CLIENT_JOIN_AFTER_FORK,
        ),
    )


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    _require(
        type(binding) is _ModuleBinding
        and sys.modules.get(MODULE_NAME) is binding.module
        and _source_sha(binding.module) == binding.source_sha256
        and _source_sha(Q1) == binding.q1_source_sha256
        and _source_sha(W5) == binding.w5_source_sha256
        and _source_sha(FETCH) == binding.fetch_source_sha256
        and _source_sha(CHANNEL) == binding.channel_source_sha256
        and _source_sha(MATERIALIZER) == binding.materializer_source_sha256
        and binding.entries == (
            validate_terminal_fetch_grant_projection,
            _inspection_is_fresh_terminal,
            validate_minimum_resume_result,
            _resume_result,
            issue_terminal_fetch_grant_once,
            submit_minimum_once,
            canonical_completed_receipt_bytes,
            resume_minimum_once,
            _GRANT_ISSUE,
            _ROUTE_INSPECTION_ONCE,
            _GRANT_ASSERT,
            _GRANT_PROJECT,
            _GRANT_CONSUME_FOR_F1,
            _GRANT_CLEAR_AFTER_FORK,
            _ISSUE_FETCH_ISSUANCE_AUTHORITY,
            _assert_shared_channel_fetch_issuance_authority,
            _CLEAR_FETCH_ISSUANCE_AFTER_FORK,
            _ISSUE_FETCH_CLIENT_JOIN,
            _assert_f1_controller_join_once,
            _CLEAR_FETCH_CLIENT_JOIN_AFTER_FORK,
        ),
        "minimum closure module, source, predecessor, or entry binding differs",
    )
    Q1._assert_module_binding()
    FETCH._assert_module_binding()
    CHANNEL._assert_production_binding()
    MATERIALIZER._assert_owner_binding()
    READ_PROFILE._assert_module_binding()


_MODULE_BINDING = _capture_module_binding()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_GRANT_CLEAR_AFTER_FORK)
    os.register_at_fork(after_in_child=_CLEAR_FETCH_ISSUANCE_AFTER_FORK)
    os.register_at_fork(after_in_child=_CLEAR_FETCH_CLIENT_JOIN_AFTER_FORK)


__all__ = [
    "DirectMinimumProductionClosureError",
    "TerminalFetchGrant",
    "issue_terminal_fetch_grant_once",
    "submit_minimum_once",
    "canonical_completed_receipt_bytes",
    "resume_minimum_once",
    "validate_terminal_fetch_grant_projection",
    "validate_minimum_resume_result",
]
