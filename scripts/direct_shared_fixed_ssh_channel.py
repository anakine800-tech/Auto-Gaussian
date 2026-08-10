#!/usr/bin/env python3
"""Sole fixed-SSH channel owner for direct submit and read codecs.

Only :class:`SubmitChannelOperation` has a production channel entrypoint.  The
query and fetch operations are closed, non-authorizing codec identities; this
module deliberately contains no qstat/fetch execution or project access.
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
from typing import Any, NamedTuple


TRANSPORT_PROFILE_SCHEMA = "auto-g16-direct-one-hop-transport-profile/1"
READ_PROFILE_SCHEMA = "auto-g16-direct-shared-fixed-ssh-read-profile/1"
OPERATION_PROJECTION_SCHEMA = "auto-g16-direct-shared-fixed-ssh-operation/1"
SUBMIT_PROTOCOL = "auto-g16-direct-one-hop-transport/1"
READ_PROTOCOL = "auto-g16-direct-one-hop-read/1"
BACKEND_KIND = "direct_ssh_pbs"
TOPOLOGY = "mac_controller_direct_ssh_server_child"
SCHEDULER_DIALECT = "pbs_legacy_v1"
SUBMIT_SUBSYSTEM = "auto-g16-direct-one-hop-v1"
READ_SUBSYSTEM = "auto-g16-direct-one-hop-read-v1"
MAX_FETCH_TOTAL_BYTES = 1_092_943_959
MAX_FETCH_CHUNK_BYTES = 4 * 1024 * 1024
MAX_BUFFERED_FETCH_TEST_BYTES = 2 * 1024 * 1024
SSH_EXECUTABLE = "/usr/bin/ssh"
PBS_BASENAME = "auto-g16-job.pbs"
FIXED_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C"}
SSH_FIXED_OPTIONS = (
    "-F", "none",
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "IdentityFile=none",
    "-o", "IdentityAgent=none",
    "-o", "CertificateFile=none",
    "-o", "PKCS11Provider=none",
    "-o", "SecurityKeyProvider=none",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "GlobalKnownHostsFile=none",
    "-o", "KnownHostsCommand=none",
    "-o", "VerifyHostKeyDNS=no",
    "-o", "UpdateHostKeys=no",
    "-o", "ProxyCommand=none",
    "-o", "ProxyJump=none",
    "-o", "PermitLocalCommand=no",
    "-o", "LocalCommand=none",
    "-o", "ControlMaster=no",
    "-o", "ControlPath=none",
    "-o", "ForwardAgent=no",
    "-o", "ForwardX11=no",
    "-o", "ClearAllForwardings=yes",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "RequestTTY=no",
)
TRANSPORT_POLICY = {
    "one_hop_only": True,
    "arbitrary_shell": False,
    "arbitrary_argv": False,
    "caller_override": False,
    "path_reopen": False,
    "descriptor_relative_upload": True,
    "immutable_no_overwrite": True,
    "qsub_max_calls": "1",
    "automatic_retry": False,
    "reconciliation_only_after_unknown": True,
    "qdel": False,
    "cancel": False,
    "inspect": False,
    "fetch": False,
    "cleanup": False,
    "delete": False,
    "portable_result_authorizes_effect": False,
}
READ_POLICY = {
    "read_only": True,
    "authorizes_effect": False,
    "qsub_calls": "0",
    "qdel": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
    "project_access": False,
    "remote_execution_present": False,
    "automatic_retry": False,
    "caller_override": False,
}
MAX_PROFILE_BYTES = 256 * 1024
MAX_CONTROL_FRAME_BYTES = 32 * 1024 * 1024
MAX_QUERY_RESPONSE_FRAME_BYTES = 512 * 1024
MAX_TERMINAL_OPERATION_RECORDS = 8
CHANNEL_TIMEOUT_SECONDS = 30.0
RESPONSE_TIMEOUT_SECONDS = 30.0
CHILD_RETIRE_TIMEOUT_SECONDS = 5.0
SUBMIT_OPERATION_TIMEOUT_SECONDS = (
    CHANNEL_TIMEOUT_SECONDS + RESPONSE_TIMEOUT_SECONDS + CHILD_RETIRE_TIMEOUT_SECONDS
)
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
POSITIVE_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")
JOB_ID_RE = re.compile(r"^[1-9][0-9]{0,19}\.[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
OPERATION_ID_RE = re.compile(r"^fixed-ssh-operation-[a-f0-9]{64}$")
_EXECUTED_SOURCE_SHA256 = globals().get("__reviewed_source_sha256__")
if _EXECUTED_SOURCE_SHA256 is None:
    with open(__file__, "rb") as _source_handle:
        _EXECUTED_SOURCE_SHA256 = hashlib.sha256(_source_handle.read()).hexdigest()


class SharedFixedSSHChannelError(ValueError):
    pass


class ControllerTransportUnknown(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SharedFixedSSHChannelError(message)


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
        raise SharedFixedSSHChannelError("value is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _text(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and bool(value)
        and value == value.strip()
        and all(0x20 <= ord(character) < 0x7F for character in value),
        f"{label} differs",
    )
    return value


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and SHA_RE.fullmatch(value) is not None and value != ZERO_SHA,
        f"{label} differs",
    )
    return value


def _positive_decimal(value: Any, label: str, *, maximum: int | None = None) -> str:
    _require(type(value) is str and POSITIVE_DECIMAL_RE.fullmatch(value) is not None, f"{label} differs")
    number = int(value, 10)
    _require(maximum is None or number <= maximum, f"{label} differs")
    return value


def _absolute_file(value: Any, label: str) -> str:
    path = _text(value, label)
    _require(
        path.startswith("/")
        and "//" not in path
        and not path.endswith("/")
        and all(component not in {"", ".", ".."} for component in path.split("/")[1:]),
        f"{label} differs",
    )
    return path


def validate_transport_profile(document: Any) -> dict[str, Any]:
    profile = _exact(
        copy.deepcopy(document),
        {
            "schema", "profile_id", "backend_kind", "topology",
            "scheduler_dialect", "ssh", "server", "qsub", "pbs_artifact", "safety",
            "profile_payload_sha256",
        },
        "transport profile",
    )
    _require(profile["schema"] == TRANSPORT_PROFILE_SCHEMA, "transport profile schema differs")
    _text(profile["profile_id"], "transport profile id")
    _require(
        profile["backend_kind"] == BACKEND_KIND
        and profile["topology"] == TOPOLOGY
        and profile["scheduler_dialect"] == SCHEDULER_DIALECT,
        "transport topology differs",
    )
    ssh = _exact(
        profile["ssh"],
        {
            "executable", "executable_sha256", "configuration_files",
            "system_policy_evidence_sha256", "host", "user", "port", "identity_file",
            "known_hosts_file", "batch_mode", "identities_only",
            "strict_host_key_checking", "subsystem",
        },
        "SSH profile",
    )
    _require(ssh["executable"] == SSH_EXECUTABLE, "SSH executable differs")
    _sha(ssh["executable_sha256"], "SSH executable")
    _sha(ssh["system_policy_evidence_sha256"], "SSH system policy evidence")
    _require(ssh["configuration_files"] == "disabled_by_F_none", "SSH configuration-file policy differs")
    _require(type(ssh["host"]) is str and HOST_RE.fullmatch(ssh["host"]) is not None, "SSH host differs")
    _require(type(ssh["user"]) is str and USER_RE.fullmatch(ssh["user"]) is not None, "SSH user differs")
    _positive_decimal(ssh["port"], "SSH port", maximum=65535)
    _absolute_file(ssh["identity_file"], "SSH identity file")
    _absolute_file(ssh["known_hosts_file"], "SSH known-hosts file")
    _require(
        ssh["batch_mode"] is True
        and ssh["identities_only"] is True
        and ssh["strict_host_key_checking"] is True
        and ssh["subsystem"] == SUBMIT_SUBSYSTEM,
        "SSH identity or subsystem policy differs",
    )
    server = _exact(
        profile["server"],
        {
            "python_executable", "python_executable_sha256", "isolated_flags",
            "working_directory", "environment", "allowed_root", "entrypoint_source_sha256",
        },
        "server profile",
    )
    _absolute_file(server["python_executable"], "server Python executable")
    _sha(server["python_executable_sha256"], "server Python executable")
    _require(
        server["isolated_flags"] == ["-I", "-S"]
        and server["working_directory"] == "/"
        and server["environment"] == FIXED_ENVIRONMENT,
        "server clean-exec policy differs",
    )
    _absolute_file(server["allowed_root"], "server allowed root")
    _sha(server["entrypoint_source_sha256"], "server entrypoint source")
    qsub = _exact(
        profile["qsub"],
        {"executable", "executable_sha256", "argv", "working_directory", "stdout_grammar"},
        "qsub profile",
    )
    qsub_executable = _absolute_file(qsub["executable"], "qsub executable")
    _require(
        qsub["argv"] == [qsub_executable, "--", PBS_BASENAME]
        and qsub["working_directory"] == "already_open_project_fd"
        and qsub["stdout_grammar"] == "independent_pbs_job_id_v1",
        "qsub executable, argv, cwd, or grammar differs",
    )
    _sha(qsub["executable_sha256"], "qsub executable")
    pbs_artifact = _exact(
        profile["pbs_artifact"],
        {"basename", "sha256", "size_bytes", "review_payload_sha256", "owner"},
        "reviewed PBS artifact",
    )
    _require(
        pbs_artifact["basename"] == PBS_BASENAME
        and bool(_positive_decimal(pbs_artifact["size_bytes"], "reviewed PBS artifact size"))
        and pbs_artifact["owner"] == "reviewed_direct_pbs_artifact_owner",
        "reviewed PBS artifact identity differs",
    )
    _sha(pbs_artifact["sha256"], "reviewed PBS artifact")
    _sha(pbs_artifact["review_payload_sha256"], "reviewed PBS artifact review")
    _require(profile["safety"] == TRANSPORT_POLICY, "transport safety policy differs")
    supplied = _sha(profile["profile_payload_sha256"], "transport profile hash")
    _require(supplied == digest({**profile, "profile_payload_sha256": ""}), "transport profile self-hash differs")
    return profile


def load_transport_profile(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PROFILE_BYTES, "transport profile bytes differ")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SharedFixedSSHChannelError("transport profile is not exact JSON") from exc
    profile = validate_transport_profile(value)
    _require(raw == canonical_bytes(profile), "transport profile bytes are not canonical")
    return profile


def validate_read_profile(document: Any, transport_profile_raw: bytes) -> dict[str, Any]:
    transport = load_transport_profile(transport_profile_raw)
    profile = _exact(
        copy.deepcopy(document),
        {"schema", "profile_id", "transport_binding", "server_read", "safety", "read_profile_payload_sha256"},
        "read profile",
    )
    _require(profile["schema"] == READ_PROFILE_SCHEMA, "read profile schema differs")
    _text(profile["profile_id"], "read profile id")
    binding = _exact(
        profile["transport_binding"],
        {"schema", "transport_profile_bytes_sha256", "transport_profile_payload_sha256"},
        "read transport binding",
    )
    _require(
        binding["schema"] == "exact_w5_transport_profile_bytes/1"
        and binding["transport_profile_bytes_sha256"] == hashlib.sha256(transport_profile_raw).hexdigest()
        and binding["transport_profile_payload_sha256"] == transport["profile_payload_sha256"],
        "read profile is not bound to exact W5 transport-profile bytes",
    )
    server_read = _exact(profile["server_read"], {"source_sha256", "qstat", "fetch"}, "server read profile")
    _require(server_read["source_sha256"] == _EXECUTED_SOURCE_SHA256, "server read source differs")
    qstat = _exact(
        server_read["qstat"],
        {
            "executable", "executable_sha256", "executable_owner_uid",
            "executable_mode", "max_stdout_bytes", "timeout_seconds",
        },
        "qstat limits",
    )
    _require(qstat["executable"] == "/usr/bin/qstat", "qstat executable differs")
    _sha(qstat["executable_sha256"], "qstat executable")
    _require(
        type(qstat["executable_owner_uid"]) is str
        and re.fullmatch(r"(?:0|[1-9][0-9]{0,9})", qstat["executable_owner_uid"]) is not None
        and type(qstat["executable_mode"]) is str
        and re.fullmatch(r"0[0-7]{3}", qstat["executable_mode"]) is not None,
        "qstat reviewed owner or mode differs",
    )
    _require(
        qstat["executable_owner_uid"] == "0"
        and qstat["executable_mode"] == "0755",
        "qstat executable must be root-owned mode 0755",
    )
    _require(qstat["max_stdout_bytes"] == "65536", "qstat stdout limit differs")
    _require(qstat["timeout_seconds"] == "30", "qstat timeout differs")
    fetch = _exact(
        server_read["fetch"],
        {"max_total_bytes", "max_chunk_bytes", "max_chunks", "timeout_seconds"},
        "fetch limits",
    )
    _positive_decimal(
        fetch["max_total_bytes"],
        "fetch total limit",
        maximum=MAX_FETCH_TOTAL_BYTES,
    )
    _positive_decimal(
        fetch["max_chunk_bytes"],
        "fetch chunk limit",
        maximum=MAX_FETCH_CHUNK_BYTES,
    )
    _positive_decimal(fetch["max_chunks"], "fetch chunk-count limit", maximum=1_000_000)
    _positive_decimal(fetch["timeout_seconds"], "fetch timeout", maximum=3600)
    _require(
        int(fetch["max_chunk_bytes"], 10) <= int(fetch["max_total_bytes"], 10),
        "fetch chunk limit exceeds total limit",
    )
    _require(profile["safety"] == READ_POLICY, "read safety policy differs")
    supplied = _sha(profile["read_profile_payload_sha256"], "read profile hash")
    _require(supplied == digest({**profile, "read_profile_payload_sha256": ""}), "read profile self-hash differs")
    return profile


def load_read_profile(raw: bytes, transport_profile_raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PROFILE_BYTES, "read profile bytes differ")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SharedFixedSSHChannelError("read profile is not exact JSON") from exc
    profile = validate_read_profile(value, transport_profile_raw)
    _require(raw == canonical_bytes(profile), "read profile bytes are not canonical")
    return profile


def build_controller_argv(profile_raw: bytes, operation: object) -> tuple[str, ...]:
    _require(
        type(operation) in {
            SubmitChannelOperation,
            QueryExactJobOperation,
            FetchTerminalMinimumBundleOperation,
        },
        "exact fixed SSH operation type is required",
    )
    snapshot = _operation_snapshot(operation, type(operation), {"issued", "running"})
    _require(snapshot.transport_profile_raw == profile_raw, "operation/profile cross-splice differs")
    profile = load_transport_profile(profile_raw)
    ssh = profile["ssh"]
    subsystem = _subsystem_for_operation(operation)
    return (
        SSH_EXECUTABLE,
        "-T",
        *SSH_FIXED_OPTIONS,
        "-o", f"UserKnownHostsFile={ssh['known_hosts_file']}",
        "-i", ssh["identity_file"],
        "-p", ssh["port"],
        "-s",
        f"{ssh['user']}@{ssh['host']}",
        subsystem,
    )


_OPERATION_TOKEN = object()
_W5_OWNER_BINDING_LOCK = threading.RLock()
_W5_OWNER_BINDING: tuple[types.ModuleType, object, object, type, str] | None = None
_QSTAT_OWNER_BINDING_LOCK = threading.RLock()
_QSTAT_OWNER_BINDING: tuple[types.ModuleType, object, object, type, str] | None = None
_QSTAT_ISSUANCE_BINDING_LOCK = threading.RLock()
_QSTAT_ISSUANCE_BINDING: tuple[types.ModuleType, object, object, type, str] | None = None
_QUERY_CODEC_TEST_TOKEN = object()
_FETCH_ISSUANCE_BINDING_LOCK = threading.RLock()
_FETCH_ISSUANCE_BINDING: tuple[types.ModuleType, object, object, type, str] | None = None
_FETCH_OPERATION_TEST_TOKEN = object()


class _SealedOperation:
    __slots__ = ("operation_id", "_seal", "__weakref__")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fixed SSH operations are owner-issued only")

    def assert_owner_sealed(self) -> None:
        _operation_snapshot(self, type(self), {"issued", "running"})

    def portable_projection(self) -> dict[str, Any]:
        return _operation_projection(self)

    def __copy__(self) -> Any:
        raise TypeError("fixed SSH operations are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("fixed SSH operations are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("fixed SSH operations are not serializable")


class SubmitChannelOperation(_SealedOperation):
    __slots__ = ()


class QueryExactJobOperation(_SealedOperation):
    __slots__ = ()


class FetchTerminalMinimumBundleOperation(_SealedOperation):
    __slots__ = ()


@dataclasses.dataclass(frozen=True, slots=True)
class _OperationRecord:
    owner_seal: object
    pid: int
    status: str
    operation_id: str
    operation_type: type[_SealedOperation]
    operation_name: str
    sequence: int
    transport_profile_raw: bytes
    read_profile_raw: bytes | None
    job_id: str | None
    submit_request_frame: bytes | None
    submit_request_id: str | None
    projection_raw: bytes
    commitment: str


@dataclasses.dataclass(frozen=True, slots=True)
class _OperationSnapshot:
    status: str
    operation_id: str
    operation_type: type[_SealedOperation]
    operation_name: str
    sequence: int
    transport_profile_raw: bytes
    read_profile_raw: bytes | None
    job_id: str | None
    submit_request_frame: bytes | None
    submit_request_id: str | None
    projection_raw: bytes


def _record_commitment(record: _OperationRecord) -> str:
    return digest(
        {
            "pid": record.pid,
            "status": record.status,
            "operation_id": record.operation_id,
            "operation_type": record.operation_type.__name__,
            "operation_name": record.operation_name,
            "sequence": record.sequence,
            "transport_profile_bytes_sha256": hashlib.sha256(record.transport_profile_raw).hexdigest(),
            "read_profile_bytes_sha256": (
                None if record.read_profile_raw is None else hashlib.sha256(record.read_profile_raw).hexdigest()
            ),
            "job_id": record.job_id,
            "submit_request_frame_sha256": (
                None
                if record.submit_request_frame is None
                else hashlib.sha256(record.submit_request_frame).hexdigest()
            ),
            "submit_request_id": record.submit_request_id,
            "projection_bytes_sha256": hashlib.sha256(record.projection_raw).hexdigest(),
        }
    )


def _sealed_record(**fields: Any) -> _OperationRecord:
    record = _OperationRecord(commitment="", **fields)
    return dataclasses.replace(record, commitment=_record_commitment(record))


def _record_snapshot(record: _OperationRecord) -> _OperationSnapshot:
    return _OperationSnapshot(
        status=record.status,
        operation_id=record.operation_id,
        operation_type=record.operation_type,
        operation_name=record.operation_name,
        sequence=record.sequence,
        transport_profile_raw=bytes(record.transport_profile_raw),
        read_profile_raw=None if record.read_profile_raw is None else bytes(record.read_profile_raw),
        job_id=record.job_id,
        submit_request_frame=(
            None if record.submit_request_frame is None else bytes(record.submit_request_frame)
        ),
        submit_request_id=record.submit_request_id,
        projection_raw=bytes(record.projection_raw),
    )


def _subsystem_for_operation(operation: object) -> str:
    if type(operation) is SubmitChannelOperation:
        return SUBMIT_SUBSYSTEM
    _require(type(operation) in {QueryExactJobOperation, FetchTerminalMinimumBundleOperation}, "operation type differs")
    return READ_SUBSYSTEM


def _resolve_w5_submit_authority_owner() -> tuple[object, object]:
    global _W5_OWNER_BINDING
    module = sys.modules.get("direct_one_hop_transport")
    expected_path = os.path.realpath(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "direct_one_hop_transport.py")
    )
    module_path = os.path.realpath(getattr(module, "__file__", ""))
    production_assert = getattr(module, "_assert_production_binding", None)
    authority_assert = getattr(module, "_assert_shared_channel_request_authority", None)
    authority_type = getattr(module, "_ControllerRequestJoin", None)
    executed_sha256 = getattr(module, "_EXECUTED_SOURCE_SHA256", None)
    _require(
        type(module) is types.ModuleType
        and module_path == expected_path
        and type(executed_sha256) is str
        and SHA_RE.fullmatch(executed_sha256) is not None
        and type(authority_type) is type
        and authority_type.__module__ == "direct_one_hop_transport"
        and callable(production_assert)
        and callable(authority_assert)
        and getattr(module, "_CANONICAL_W5_MODULE", None) is module,
        "canonical W5 submit authority owner differs",
    )
    with open(expected_path, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(source_sha256 == executed_sha256, "canonical W5 submit authority source differs")
    production_assert()
    candidate = (module, production_assert, authority_assert, authority_type, source_sha256)
    with _W5_OWNER_BINDING_LOCK:
        if _W5_OWNER_BINDING is None:
            _W5_OWNER_BINDING = candidate
        _require(
            _W5_OWNER_BINDING == candidate,
            "canonical W5 submit authority owner was reloaded or rebound",
        )
    return production_assert, authority_assert


def _resolve_qstat_query_authority_owner() -> tuple[object, type]:
    """Resolve Q1's exact request join without importing or selecting a runner."""

    global _QSTAT_OWNER_BINDING
    module = sys.modules.get("direct_qstat_acquisition")
    expected_path = os.path.realpath(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "direct_qstat_acquisition.py")
    )
    module_path = os.path.realpath(getattr(module, "__file__", ""))
    authority_assert = getattr(module, "_assert_shared_channel_query_authority", None)
    module_assert = getattr(module, "_assert_module_binding", None)
    authority_type = getattr(module, "_ControllerQueryJoin", None)
    executed_sha256 = getattr(module, "_EXECUTED_SOURCE_SHA256", None)
    _require(
        type(module) is types.ModuleType
        and module_path == expected_path
        and callable(authority_assert)
        and callable(module_assert)
        and getattr(module_assert, "__module__", None) == "direct_qstat_acquisition"
        and getattr(module_assert, "__name__", None) == "_assert_module_binding"
        and type(authority_type) is type
        and authority_type.__module__ == "direct_qstat_acquisition"
        and type(executed_sha256) is str
        and SHA_RE.fullmatch(executed_sha256) is not None,
        "canonical qstat query authority owner differs",
    )
    with open(expected_path, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(source_sha256 == executed_sha256, "canonical qstat query authority source differs")
    module_assert()
    candidate = (module, module_assert, authority_assert, authority_type, source_sha256)
    with _QSTAT_OWNER_BINDING_LOCK:
        if _QSTAT_OWNER_BINDING is None:
            _QSTAT_OWNER_BINDING = candidate
        _require(
            _QSTAT_OWNER_BINDING == candidate,
            "canonical qstat query authority owner was reloaded or rebound",
        )
    return authority_assert, authority_type


def _resolve_qstat_query_issuance_owner() -> tuple[object, type]:
    global _QSTAT_ISSUANCE_BINDING
    module = sys.modules.get("direct_qstat_acquisition")
    expected_path = os.path.realpath(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "direct_qstat_acquisition.py")
    )
    module_path = os.path.realpath(getattr(module, "__file__", ""))
    authority_assert = getattr(module, "_assert_shared_channel_query_issuance_authority", None)
    module_assert = getattr(module, "_assert_module_binding", None)
    authority_type = getattr(module, "_ExactQueryIssuanceJoin", None)
    executed_sha256 = getattr(module, "_EXECUTED_SOURCE_SHA256", None)
    _require(
        type(module) is types.ModuleType
        and module_path == expected_path
        and callable(authority_assert)
        and callable(module_assert)
        and getattr(module_assert, "__module__", None) == "direct_qstat_acquisition"
        and getattr(module_assert, "__name__", None) == "_assert_module_binding"
        and type(authority_type) is type
        and authority_type.__module__ == "direct_qstat_acquisition"
        and type(executed_sha256) is str
        and SHA_RE.fullmatch(executed_sha256) is not None,
        "canonical qstat query issuance owner differs",
    )
    with open(expected_path, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(source_sha256 == executed_sha256, "canonical qstat query issuance source differs")
    module_assert()
    candidate = (module, module_assert, authority_assert, authority_type, source_sha256)
    with _QSTAT_ISSUANCE_BINDING_LOCK:
        if _QSTAT_ISSUANCE_BINDING is None:
            _QSTAT_ISSUANCE_BINDING = candidate
        _require(
            _QSTAT_ISSUANCE_BINDING == candidate,
            "canonical qstat query issuance owner was reloaded or rebound",
        )
    return authority_assert, authority_type


def _resolve_terminal_fetch_issuance_owner() -> tuple[object, type]:
    """Resolve only the canonical terminal-grant successor authority."""

    global _FETCH_ISSUANCE_BINDING
    module = sys.modules.get("direct_minimum_production_closure")
    expected_path = os.path.realpath(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "direct_minimum_production_closure.py",
        )
    )
    module_path = os.path.realpath(getattr(module, "__file__", ""))
    authority_assert = getattr(
        module, "_assert_shared_channel_fetch_issuance_authority", None,
    )
    module_assert = getattr(module, "_assert_module_binding", None)
    authority_type = getattr(module, "_ExactFetchIssuanceAuthority", None)
    _require(
        type(module) is types.ModuleType
        and module_path == expected_path
        and callable(authority_assert)
        and callable(module_assert)
        and getattr(module_assert, "__module__", None)
        == "direct_minimum_production_closure"
        and type(authority_type) is type
        and authority_type.__module__ == "direct_minimum_production_closure",
        "canonical terminal fetch issuance owner differs",
    )
    module_assert()
    with open(expected_path, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    candidate = (
        module, module_assert, authority_assert, authority_type, source_sha256,
    )
    with _FETCH_ISSUANCE_BINDING_LOCK:
        if _FETCH_ISSUANCE_BINDING is None:
            _FETCH_ISSUANCE_BINDING = candidate
        _require(
            _FETCH_ISSUANCE_BINDING == candidate,
            "canonical terminal fetch issuance owner was reloaded or rebound",
        )
    return authority_assert, authority_type


def _make_operation_owner() -> tuple[object, ...]:
    registry: weakref.WeakKeyDictionary[_SealedOperation, _OperationRecord] = weakref.WeakKeyDictionary()
    terminal_order: collections.deque[weakref.ReferenceType[_SealedOperation]] = collections.deque()
    lock = threading.RLock()
    record_seal = object()
    urandom = os.urandom
    owner_epoch = urandom(32)
    sequence = 0

    def validate_locked(
        operation: object,
        exact_type: type[_SealedOperation],
        statuses: set[str],
    ) -> _OperationRecord:
        _require(type(operation) is exact_type, f"exact {exact_type.__name__} is required")
        record = registry.get(operation)
        valid = (
            type(record) is _OperationRecord
            and record.owner_seal is record_seal
            and record.pid == os.getpid()
            and record.status in statuses
            and record.operation_type is exact_type
            and record.operation_id == getattr(operation, "operation_id", None)
            and getattr(operation, "_seal", None) is _OPERATION_TOKEN
            and record.commitment == _record_commitment(record)
        )
        if not valid:
            if operation in registry:
                del registry[operation]
            raise SharedFixedSSHChannelError(
                "fixed SSH operation is foreign, forged, forked, reloaded, mutated, reclaimed, or terminal"
            )
        return record

    def register(
        operation_type: type[_SealedOperation],
        operation_name: str,
        transport_profile_raw: bytes,
        transport: dict[str, Any],
        *,
        read_profile_raw: bytes | None,
        read_profile: dict[str, Any] | None,
        job_id: str | None,
        submit_request_frame: bytes | None,
        submit_request_id: str | None,
    ) -> _SealedOperation:
        nonlocal sequence
        with lock:
            sequence += 1
            current_sequence = sequence
            nonce = urandom(32)
            _require(type(nonce) is bytes and len(nonce) == 32, "fixed SSH operation nonce differs")
            operation_id = "fixed-ssh-operation-" + digest(
                {
                    "owner_epoch": owner_epoch.hex(),
                    "sequence": current_sequence,
                    "nonce": nonce.hex(),
                    "operation": operation_name,
                    "transport_profile_bytes_sha256": hashlib.sha256(transport_profile_raw).hexdigest(),
                    "read_profile_payload_sha256": (
                        None if read_profile is None else read_profile["read_profile_payload_sha256"]
                    ),
                    "submit_request_frame_sha256": (
                        None
                        if submit_request_frame is None
                        else hashlib.sha256(submit_request_frame).hexdigest()
                    ),
                    "submit_request_id": submit_request_id,
                    "job_id": job_id,
                }
            )
            projection = {
                "schema": OPERATION_PROJECTION_SCHEMA,
                "operation": operation_name,
                "operation_id": operation_id,
                "transport_profile_bytes_sha256": hashlib.sha256(transport_profile_raw).hexdigest(),
                "transport_profile_payload_sha256": transport["profile_payload_sha256"],
                "read_profile_payload_sha256": (
                    None if read_profile is None else read_profile["read_profile_payload_sha256"]
                ),
                "submit_request_frame_sha256": (
                    None
                    if submit_request_frame is None
                    else hashlib.sha256(submit_request_frame).hexdigest()
                ),
                "submit_request_id": submit_request_id,
                "job_id": job_id,
                "authority": {
                    "authorizes_effect": False,
                    "portable_projection_is_authority": False,
                    "qsub_calls": (
                        "typed_w5_seam_only" if operation_type is SubmitChannelOperation else "0"
                    ),
                    "automatic_retry": False,
                },
            }
            operation = object.__new__(operation_type)
            operation.operation_id = operation_id
            operation._seal = _OPERATION_TOKEN
            registry[operation] = _sealed_record(
                owner_seal=record_seal,
                pid=os.getpid(),
                status="issued",
                operation_id=operation_id,
                operation_type=operation_type,
                operation_name=operation_name,
                sequence=current_sequence,
                transport_profile_raw=bytes(transport_profile_raw),
                read_profile_raw=(
                    None if read_profile_raw is None else bytes(read_profile_raw)
                ),
                job_id=job_id,
                submit_request_frame=(
                    None if submit_request_frame is None else bytes(submit_request_frame)
                ),
                submit_request_id=submit_request_id,
                projection_raw=canonical_bytes(projection),
            )
            return operation

    def issue_submit(
        transport_profile_raw: bytes,
        w5_request_authority: object,
        request_frame: bytes,
    ) -> SubmitChannelOperation:
        """The only submit issuer; it consumes W5's exact private request join."""
        _assert_production_binding()
        _production_assert, authority_assert = _resolve_w5_submit_authority_owner()
        request_id = authority_assert(w5_request_authority, transport_profile_raw, request_frame)
        _require(
            type(request_id) is str
            and re.fullmatch(r"direct-controller-request-[a-f0-9]{64}", request_id) is not None,
            "canonical W5 submit request identity differs",
        )
        _validate_single_canonical_frame_bytes(request_frame)
        transport = load_transport_profile(transport_profile_raw)
        return register(
            SubmitChannelOperation,
            "submit_channel",
            transport_profile_raw,
            transport,
            read_profile_raw=None,
            read_profile=None,
            job_id=None,
            submit_request_frame=request_frame,
            submit_request_id=request_id,
        )  # type: ignore[return-value]

    def issue_query(
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
        query_issuance_authority: object,
    ) -> QueryExactJobOperation:
        _assert_production_binding()
        authority_assert, authority_type = _resolve_qstat_query_issuance_owner()
        _require(
            type(query_issuance_authority) is authority_type,
            "exact qstat query issuance authority is required",
        )
        job_id = authority_assert(
            query_issuance_authority,
            transport_profile_raw,
            read_profile_raw,
        )
        _require(type(job_id) is str and JOB_ID_RE.fullmatch(job_id) is not None, "query job ID differs")
        transport = load_transport_profile(transport_profile_raw)
        read_profile = load_read_profile(read_profile_raw, transport_profile_raw)
        return register(
            QueryExactJobOperation,
            "query_exact_job",
            transport_profile_raw,
            transport,
            read_profile_raw=read_profile_raw,
            read_profile=read_profile,
            job_id=job_id,
            submit_request_frame=None,
            submit_request_id=None,
        )  # type: ignore[return-value]

    def issue_query_for_testing(
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
        job_id: str,
        *,
        _test_token: object = _FETCH_OPERATION_TEST_TOKEN,
    ) -> QueryExactJobOperation:
        _require(_test_token is _QUERY_CODEC_TEST_TOKEN, "query codec test token differs")
        _require(type(job_id) is str and JOB_ID_RE.fullmatch(job_id) is not None, "query job ID differs")
        transport = load_transport_profile(transport_profile_raw)
        read_profile = load_read_profile(read_profile_raw, transport_profile_raw)
        return register(
            QueryExactJobOperation,
            "query_exact_job",
            transport_profile_raw,
            transport,
            read_profile_raw=read_profile_raw,
            read_profile=read_profile,
            job_id=job_id,
            submit_request_frame=None,
            submit_request_id=None,
        )  # type: ignore[return-value]

    def issue_fetch(
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
        fetch_issuance_authority: object,
    ) -> FetchTerminalMinimumBundleOperation:
        _assert_production_binding()
        authority_assert, authority_type = _resolve_terminal_fetch_issuance_owner()
        _require(
            type(fetch_issuance_authority) is authority_type,
            "exact terminal fetch issuance authority is required",
        )
        issued = authority_assert(
            fetch_issuance_authority,
            transport_profile_raw,
            read_profile_raw,
        )
        _require(
            type(issued) is tuple and len(issued) == 2,
            "terminal fetch issuance result differs",
        )
        job_id, evidence_raw = issued
        _require(type(job_id) is str and JOB_ID_RE.fullmatch(job_id) is not None, "fetch job ID differs")
        _require(
            type(evidence_raw) is bytes
            and 0 < len(evidence_raw) <= MAX_CONTROL_FRAME_BYTES,
            "terminal fetch evidence bytes differ",
        )
        try:
            evidence = json.loads(evidence_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SharedFixedSSHChannelError(
                "terminal fetch evidence is malformed"
            ) from exc
        _require(
            type(evidence) is dict and canonical_bytes(evidence) == evidence_raw,
            "terminal fetch evidence is not canonical",
        )
        transport = load_transport_profile(transport_profile_raw)
        read_profile = load_read_profile(read_profile_raw, transport_profile_raw)
        return register(
            FetchTerminalMinimumBundleOperation,
            "fetch_terminal_minimum_bundle",
            transport_profile_raw,
            transport,
            read_profile_raw=read_profile_raw,
            read_profile=read_profile,
            job_id=job_id,
            submit_request_frame=evidence_raw,
            submit_request_id=None,
        )  # type: ignore[return-value]

    def issue_fetch_for_testing(
        transport_profile_raw: bytes,
        read_profile_raw: bytes,
        job_id: str,
        *,
        _test_token: object = _FETCH_OPERATION_TEST_TOKEN,
    ) -> FetchTerminalMinimumBundleOperation:
        _require(
            _test_token is _FETCH_OPERATION_TEST_TOKEN,
            "fetch operation test token differs",
        )
        _require(type(job_id) is str and JOB_ID_RE.fullmatch(job_id) is not None, "fetch job ID differs")
        transport = load_transport_profile(transport_profile_raw)
        read_profile = load_read_profile(read_profile_raw, transport_profile_raw)
        return register(
            FetchTerminalMinimumBundleOperation,
            "fetch_terminal_minimum_bundle",
            transport_profile_raw,
            transport,
            read_profile_raw=read_profile_raw,
            read_profile=read_profile,
            job_id=job_id,
            submit_request_frame=None,
            submit_request_id=None,
        )  # type: ignore[return-value]

    def snapshot(
        operation: object,
        exact_type: type[_SealedOperation],
        statuses: set[str],
    ) -> _OperationSnapshot:
        with lock:
            return _record_snapshot(validate_locked(operation, exact_type, statuses))

    def projection(operation: object) -> dict[str, Any]:
        exact_type = type(operation)
        _require(
            exact_type in {
                SubmitChannelOperation,
                QueryExactJobOperation,
                FetchTerminalMinimumBundleOperation,
            },
            "exact fixed SSH operation type is required",
        )
        record = snapshot(operation, exact_type, {"issued", "running", "terminal"})
        return json.loads(record.projection_raw.decode("utf-8"))

    def terminalize_locked(operation: _SealedOperation, record: _OperationRecord) -> None:
        terminal = dataclasses.replace(record, status="terminal", commitment="")
        terminal = dataclasses.replace(terminal, commitment=_record_commitment(terminal))
        registry[operation] = terminal
        terminal_order.append(weakref.ref(operation))
        while len(terminal_order) > MAX_TERMINAL_OPERATION_RECORDS:
            retired_ref = terminal_order.popleft()
            retired = retired_ref()
            if retired is None:
                continue
            retired_record = registry.get(retired)
            if type(retired_record) is _OperationRecord and retired_record.status == "terminal":
                del registry[retired]

    def claim_submit(operation: object, request_frame: bytes) -> _OperationSnapshot:
        _require(type(operation) is SubmitChannelOperation, "exact SubmitChannelOperation is required")
        with lock:
            record = validate_locked(operation, SubmitChannelOperation, {"issued"})
            running = dataclasses.replace(record, status="running", commitment="")
            running = dataclasses.replace(running, commitment=_record_commitment(running))
            registry[operation] = running
            if type(request_frame) is not bytes or request_frame != running.submit_request_frame:
                terminalize_locked(operation, running)
                raise SharedFixedSSHChannelError("submit request frame is foreign or cross-spliced")
            return _record_snapshot(running)

    def claim_query(operation: object) -> _OperationSnapshot:
        _require(type(operation) is QueryExactJobOperation, "exact QueryExactJobOperation is required")
        with lock:
            record = validate_locked(operation, QueryExactJobOperation, {"issued"})
            running = dataclasses.replace(record, status="running", commitment="")
            running = dataclasses.replace(running, commitment=_record_commitment(running))
            registry[operation] = running
            return _record_snapshot(running)

    def claim_fetch(operation: object) -> _OperationSnapshot:
        _require(
            type(operation) is FetchTerminalMinimumBundleOperation,
            "exact FetchTerminalMinimumBundleOperation is required",
        )
        with lock:
            record = validate_locked(operation, FetchTerminalMinimumBundleOperation, {"issued"})
            running = dataclasses.replace(record, status="running", commitment="")
            running = dataclasses.replace(running, commitment=_record_commitment(running))
            registry[operation] = running
            return _record_snapshot(running)

    def finish(operation: object) -> None:
        exact_type = type(operation)
        if exact_type not in {
            SubmitChannelOperation,
            QueryExactJobOperation,
            FetchTerminalMinimumBundleOperation,
        }:
            return
        with lock:
            record = registry.get(operation)
            if (
                type(record) is _OperationRecord
                and record.owner_seal is record_seal
                and record.pid == os.getpid()
                and record.operation_type is exact_type
                and record.status == "running"
                and record.commitment == _record_commitment(record)
            ):
                terminalize_locked(operation, record)
            elif operation in registry:
                del registry[operation]

    def clear_after_fork() -> None:
        nonlocal lock, owner_epoch, record_seal, sequence
        registry.clear()
        terminal_order.clear()
        lock = threading.RLock()
        record_seal = object()
        owner_epoch = urandom(32)
        sequence = 0

    return (
        issue_submit,
        issue_query,
        issue_query_for_testing,
        issue_fetch,
        issue_fetch_for_testing,
        snapshot,
        projection,
        claim_submit,
        claim_query,
        claim_fetch,
        finish,
        clear_after_fork,
    )


(
    issue_submit_channel_operation,
    issue_query_exact_job_operation,
    _issue_query_exact_job_operation_for_testing,
    issue_fetch_terminal_minimum_bundle_operation,
    _issue_fetch_terminal_minimum_bundle_operation_for_testing,
    _operation_snapshot,
    _operation_projection,
    _claim_submit_operation,
    _claim_query_operation,
    _claim_fetch_operation,
    _finish_operation,
    _clear_operation_owner_after_fork,
) = _make_operation_owner()


def project_submit_controller_argv_for_review(transport_profile_raw: bytes) -> tuple[str, ...]:
    """Return the fixed non-executing submit argv projection for review/tests."""
    profile = load_transport_profile(transport_profile_raw)
    ssh = profile["ssh"]
    return (
        SSH_EXECUTABLE,
        "-T",
        *SSH_FIXED_OPTIONS,
        "-o", f"UserKnownHostsFile={ssh['known_hosts_file']}",
        "-i", ssh["identity_file"],
        "-p", ssh["port"],
        "-s",
        f"{ssh['user']}@{ssh['host']}",
        SUBMIT_SUBSYSTEM,
    )


def _canonical_frame(value: dict[str, Any], *, maximum: int = MAX_CONTROL_FRAME_BYTES) -> bytes:
    payload = canonical_bytes(value)
    _require(0 < len(payload) <= maximum, "canonical frame size differs")
    return struct.pack("!I", len(payload)) + payload


def _validate_single_canonical_frame_bytes(frame: bytes) -> None:
    _require(type(frame) is bytes and len(frame) >= 5, "canonical frame differs")
    size = struct.unpack("!I", frame[:4])[0]
    _require(0 < size <= MAX_CONTROL_FRAME_BYTES and len(frame) == 4 + size, "canonical frame size differs")
    try:
        value = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SharedFixedSSHChannelError("canonical frame is malformed") from exc
    _require(type(value) is dict and canonical_bytes(value) == frame[4:], "canonical frame bytes differ")


def project_query_request_frame_for_review(operation: QueryExactJobOperation) -> bytes:
    """Project non-authorizing query bytes without consuming the operation."""
    _require(type(operation) is QueryExactJobOperation, "exact QueryExactJobOperation is required")
    _assert_production_binding()
    snapshot = _operation_snapshot(operation, QueryExactJobOperation, {"issued"})
    return _canonical_frame(
        {
            "protocol": READ_PROTOCOL,
            "operation": "query_exact_job",
            "operation_id": snapshot.operation_id,
            "job_id": snapshot.job_id,
            "authority": {"authorizes_effect": False, "qsub_calls": "0"},
        }
    )


def project_fetch_request_frame_for_review(operation: FetchTerminalMinimumBundleOperation) -> bytes:
    """Project non-authorizing fetch bytes without consuming the operation."""
    _require(
        type(operation) is FetchTerminalMinimumBundleOperation,
        "exact FetchTerminalMinimumBundleOperation is required",
    )
    _assert_production_binding()
    snapshot = _operation_snapshot(operation, FetchTerminalMinimumBundleOperation, {"issued"})
    if snapshot.submit_request_frame is None:
        return _canonical_frame(
            {
                "protocol": READ_PROTOCOL,
                "operation": "fetch_terminal_minimum_bundle",
                "operation_id": snapshot.operation_id,
                "job_id": snapshot.job_id,
                "bundle": "terminal_minimum_v1",
                "authority": {"authorizes_effect": False, "qsub_calls": "0"},
            }
        )
    try:
        evidence = json.loads(snapshot.submit_request_frame.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SharedFixedSSHChannelError("fetch operation evidence is malformed") from exc
    _require(
        type(evidence) is dict
        and canonical_bytes(evidence) == snapshot.submit_request_frame,
        "fetch operation evidence differs",
    )
    return _canonical_frame(
        {
            "protocol": READ_PROTOCOL,
            "operation": "fetch_terminal_minimum_bundle",
            "operation_id": snapshot.operation_id,
            "job_id": snapshot.job_id,
            "bundle": "terminal_minimum_v1",
            "evidence": evidence,
            "authority": {"authorizes_effect": False, "qsub_calls": "0"},
        }
    )


def _pipe_cloexec() -> tuple[int, int]:
    if hasattr(os, "pipe2"):
        return os.pipe2(getattr(os, "O_CLOEXEC", 0))
    left, right = os.pipe()
    for descriptor in (left, right):
        fcntl.fcntl(descriptor, fcntl.F_SETFD, fcntl.fcntl(descriptor, fcntl.F_GETFD) | fcntl.FD_CLOEXEC)
    return left, right


def _close_quiet(*descriptors: int) -> None:
    for descriptor in descriptors:
        if type(descriptor) is int and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _executable_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_absolute_no_follow(path: str, *, final_flags: int) -> int:
    canonical = _absolute_file(path, "reviewed executable path")
    components = canonical.split("/")[1:]
    directory = os.open(
        "/",
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        for component in components[:-1]:
            successor = os.open(
                component,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory,
            )
            os.close(directory)
            directory = successor
        return os.open(
            components[-1],
            final_flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory,
        )
    finally:
        os.close(directory)


def _assert_reviewed_executable_descriptor(descriptor: int, path: str, expected_sha256: str) -> None:
    _sha(expected_sha256, "reviewed executable")
    before = os.fstat(descriptor)
    _require(stat.S_ISREG(before.st_mode) and before.st_mode & 0o111, "reviewed executable type or mode differs")
    os.lseek(descriptor, 0, os.SEEK_SET)
    hasher = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        hasher.update(chunk)
    after = os.fstat(descriptor)
    current = _open_absolute_no_follow(path, final_flags=os.O_RDONLY)
    try:
        _require(
            _executable_identity(before) == _executable_identity(after)
            == _executable_identity(os.fstat(current))
            and hasher.hexdigest() == expected_sha256,
            "reviewed executable identity or hash differs",
        )
    finally:
        os.close(current)


def _open_reviewed_executable(path: str, expected_sha256: str) -> int:
    descriptor = _open_absolute_no_follow(path, final_flags=os.O_RDONLY)
    try:
        _assert_reviewed_executable_descriptor(descriptor, path, expected_sha256)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _descriptor_execve(descriptor: int, argv: tuple[str, ...], environment: dict[str, str]) -> None:
    _require(type(descriptor) is int and descriptor >= 0 and type(argv) is tuple, "descriptor exec differs")
    if os.execve in os.supports_fd:  # pragma: no cover - platform production feature
        _FROZEN_EXECVE(descriptor, list(argv), environment)
        raise AssertionError("descriptor exec unexpectedly returned")
    _require(os.path.isdir("/proc/self/fd"), "descriptor exec is unavailable; path fallback forbidden")
    alias = f"/proc/self/fd/{descriptor}"
    try:
        _require(
            _executable_identity(os.fstat(descriptor)) == _executable_identity(os.stat(alias)),
            "descriptor exec alias identity differs",
        )
    except OSError as exc:
        raise SharedFixedSSHChannelError("descriptor exec is unavailable; path fallback forbidden") from exc
    _FROZEN_EXECVE(alias, list(argv), environment)
    raise AssertionError("descriptor exec unexpectedly returned")


def _require_descriptor_exec_available() -> None:
    _require(
        os.execve in os.supports_fd or os.path.isdir("/proc/self/fd"),
        "descriptor exec is unavailable; path fallback forbidden",
    )


def _write_frame_until(descriptor: int, payload: bytes, deadline: float) -> None:
    _require(type(descriptor) is int and type(payload) is bytes and bool(payload) and type(deadline) is float, "frame write differs")
    try:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        _require(bool(fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_NONBLOCK), "channel request FD is not nonblocking")
    except BaseException as exc:
        raise ControllerTransportUnknown("channel request FD setup failed") from exc
    offset = 0
    while offset < len(payload):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControllerTransportUnknown("channel request write timed out")
        try:
            _, writable, exceptional = select.select([], [descriptor], [descriptor], remaining)
        except InterruptedError:
            continue
        except (OSError, ValueError) as exc:
            raise ControllerTransportUnknown("channel request write observation failed") from exc
        if exceptional:
            raise ControllerTransportUnknown("channel request peer failed")
        if not writable:
            raise ControllerTransportUnknown("channel request write timed out")
        try:
            written = os.write(descriptor, payload[offset:])
        except (BlockingIOError, InterruptedError):
            continue
        except OSError as exc:
            raise ControllerTransportUnknown("channel request peer closed") from exc
        if type(written) is not int or written <= 0:
            raise ControllerTransportUnknown("channel request write made no progress")
        offset += written


def _write_all(descriptor: int, payload: bytes) -> None:
    _require(type(descriptor) is int and type(payload) is bytes and bool(payload), "fixed frame write differs")
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        _require(type(written) is int and written > 0, "fixed frame write made no progress")
        offset += written


def _send_frame_until(descriptor: int, frame: bytes, deadline: float) -> None:
    try:
        _write_frame_until(descriptor, frame, deadline)
        os.close(descriptor)
    except BaseException as exc:
        raise ControllerTransportUnknown("channel request may have been delivered") from exc


def _read_exact_until(descriptor: int, size: int, deadline: float, label: str) -> bytes:
    _require(type(descriptor) is int and type(size) is int and size >= 0 and type(deadline) is float, f"{label} read differs")
    chunks: list[bytes] = []
    remaining_size = size
    while remaining_size:
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            raise ControllerTransportUnknown(f"{label} timed out")
        try:
            ready, _, _ = select.select([descriptor], [], [], remaining_time)
        except InterruptedError:
            continue
        except (OSError, ValueError) as exc:
            raise ControllerTransportUnknown(f"{label} observation failed") from exc
        if not ready:
            raise ControllerTransportUnknown(f"{label} timed out")
        try:
            chunk = os.read(descriptor, min(65536, remaining_size))
        except InterruptedError:
            continue
        except OSError as exc:
            raise ControllerTransportUnknown(f"{label} read failed") from exc
        if not chunk:
            raise ControllerTransportUnknown(f"{label} ended early")
        chunks.append(chunk)
        remaining_size -= len(chunk)
    return b"".join(chunks)


def _require_eof_until(descriptor: int, deadline: float, label: str) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ControllerTransportUnknown(f"{label} EOF timed out")
    try:
        ready, _, _ = select.select([descriptor], [], [], remaining)
    except (OSError, ValueError) as exc:
        raise ControllerTransportUnknown(f"{label} EOF observation failed") from exc
    if not ready:
        raise ControllerTransportUnknown(f"{label} EOF timed out")
    try:
        trailing = os.read(descriptor, 1)
    except OSError as exc:
        raise ControllerTransportUnknown(f"{label} EOF read failed") from exc
    _require(trailing == b"", f"{label} contains extra bytes or a second frame")


def _read_canonical_frame_until(descriptor: int, deadline: float, maximum: int, label: str) -> dict[str, Any]:
    header = _read_exact_until(descriptor, 4, deadline, label)
    size = struct.unpack("!I", header)[0]
    _require(0 < size <= maximum, f"{label} size differs")
    raw = _read_exact_until(descriptor, size, deadline, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerTransportUnknown(f"{label} is malformed") from exc
    _require(type(value) is dict and canonical_bytes(value) == raw, f"{label} is not canonical")
    return value


def read_single_response_until(descriptor: int, deadline: float) -> dict[str, Any]:
    value = _read_canonical_frame_until(descriptor, deadline, MAX_CONTROL_FRAME_BYTES, "channel response")
    _require_eof_until(descriptor, deadline, "channel response")
    return value


def read_single_response(descriptor: int, timeout_seconds: float) -> dict[str, Any]:
    _require(type(timeout_seconds) is float and timeout_seconds > 0, "response timeout differs")
    return read_single_response_until(descriptor, time.monotonic() + timeout_seconds)


def _wait_child_until(pid: int, deadline: float) -> int:
    while True:
        waited, status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return os.waitstatus_to_exitcode(status)
        _require(waited == 0, "fixed channel child identity differs")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControllerTransportUnknown("fixed channel child exit timed out")
        select.select([], [], [], min(0.01, remaining))


def _retire_child_bounded(pid: int) -> bool:
    try:
        _wait_child_until(pid, time.monotonic() + CHILD_RETIRE_TIMEOUT_SECONDS)
        return True
    except BaseException:
        return False


class _QueryChildHandle:
    __slots__ = ("pid", "nonce", "_seal", "__weakref__")

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "_QueryChildHandle":
        raise TypeError("query child handles are owner-issued")

    def __copy__(self) -> Any:
        raise TypeError("query child handles are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("query child handles are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("query child handles are not serializable")


class _QueryChildRecord(NamedTuple):
    pid: int
    operation_id: str
    creator_pid: int
    creator_thread: int
    epoch: object
    nonce: str
    state: str
    seal: object


def _make_query_child_owner() -> tuple[Any, Any, Any, Any, Any]:
    registry: weakref.WeakKeyDictionary[_QueryChildHandle, _QueryChildRecord] = weakref.WeakKeyDictionary()
    forked_operations: weakref.WeakKeyDictionary[QueryExactJobOperation, str] = weakref.WeakKeyDictionary()
    lock = threading.RLock()
    epoch = object()
    seal = object()
    operation_snapshot = _operation_snapshot

    def require_environment() -> None:
        _assert_production_binding()
        _require(
            signal.getsignal(signal.SIGCHLD) is signal.SIG_DFL,
            "query child requires default SIGCHLD and its exclusive reaper",
        )

    def exact(handle: object, state: str = "live") -> _QueryChildRecord:
        with lock:
            record = registry.get(handle) if type(handle) is _QueryChildHandle else None
            _require(
                type(record) is _QueryChildRecord
                and record.pid == getattr(handle, "pid", None)
                and OPERATION_ID_RE.fullmatch(record.operation_id) is not None
                and record.creator_pid == os.getpid()
                and record.creator_thread == threading.get_ident()
                and record.epoch is epoch
                and record.nonce == getattr(handle, "nonce", None)
                and record.state == state
                and record.seal is seal is getattr(handle, "_seal", None),
                "query child handle is foreign, forged, forked, reused, or terminal",
            )
            require_environment()
            return record

    def retire_unregistered_child(pid: int) -> bool:
        """Reap only the PID just returned by this closure's own fork."""

        def probe() -> tuple[bool, bool]:
            try:
                waited, _status = os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                return False, False
            if waited == pid:
                return True, True
            return waited == 0, False

        def wait_reaped(deadline: float) -> bool:
            while True:
                valid, reaped = probe()
                if not valid or reaped:
                    return reaped
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                select.select([], [], [], min(0.01, remaining))

        half_window = CHILD_RETIRE_TIMEOUT_SECONDS / 2.0
        valid, reaped = probe()
        if not valid or reaped:
            return reaped
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            valid, reaped = probe()
            return valid and reaped
        except OSError:
            return False
        if wait_reaped(time.monotonic() + half_window):
            return True
        valid, reaped = probe()
        if not valid or reaped:
            return reaped
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            valid, reaped = probe()
            return valid and reaped
        except OSError:
            return False
        return wait_reaped(time.monotonic() + half_window)

    def fork_for_query_operation(
        operation: QueryExactJobOperation | FetchTerminalMinimumBundleOperation,
    ) -> tuple[int, _QueryChildHandle | None]:
        require_environment()
        _require(
            type(operation) in {
                QueryExactJobOperation, FetchTerminalMinimumBundleOperation,
            },
            "exact running read operation is required for child fork",
        )
        snapshot = operation_snapshot(
            operation, type(operation), {"running"}
        )
        operation_id = snapshot.operation_id
        with lock:
            _require(
                operation not in forked_operations,
                "query operation already forked its sole child",
            )
            forked_operations[operation] = operation_id
        handle = object.__new__(_QueryChildHandle)
        handle.nonce = os.urandom(16).hex()
        handle._seal = seal
        try:
            pid = _FROZEN_FORK()
        except BaseException:
            with lock:
                forked_operations.pop(operation, None)
            raise
        if pid == 0:  # at-fork clearing revokes the child's pending objects
            return 0, None
        _require(type(pid) is int and pid > 0, "query fork child PID differs")
        try:
            handle.pid = pid
            record = _QueryChildRecord(
                pid, operation_id, os.getpid(), threading.get_ident(), epoch,
                handle.nonce, "live", seal,
            )
            with lock:
                registry[handle] = record
            return pid, handle
        except BaseException:
            retire_unregistered_child(pid)
            raise

    def terminal(handle: _QueryChildHandle, record: _QueryChildRecord) -> None:
        with lock:
            if registry.get(handle) is record:
                del registry[handle]

    def wait_until(handle: _QueryChildHandle, deadline: float) -> int:
        record = exact(handle)
        _require(type(deadline) is float, "query child deadline differs")
        try:
            while True:
                waited, status = os.waitpid(record.pid, os.WNOHANG)
                if waited == record.pid:
                    terminal(handle, record)
                    return os.waitstatus_to_exitcode(status)
                _require(waited == 0, "query child identity differs")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ControllerTransportUnknown("query child exit timed out")
                select.select([], [], [], min(0.01, remaining))
        except BaseException:
            raise

    def retire(handle: _QueryChildHandle) -> bool:
        try:
            record = exact(handle)
        except BaseException:
            return False
        with lock:
            _require(registry.get(handle) is record, "query child retirement raced")
            retiring = record._replace(state="retiring")
            registry[handle] = retiring

        def probe() -> tuple[bool, bool]:
            try:
                waited, _status = os.waitpid(retiring.pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                return False, False
            if waited == retiring.pid:
                return True, True
            return waited == 0, False

        def wait_reaped(deadline: float) -> bool:
            while True:
                valid, reaped = probe()
                if not valid or reaped:
                    return reaped
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                select.select([], [], [], min(0.01, remaining))

        def signal_exact(signum: int) -> tuple[bool, bool]:
            valid, reaped = probe()
            if not valid or reaped:
                return False, reaped
            try:
                os.kill(retiring.pid, signum)
            except ProcessLookupError:
                valid, reaped = probe()
                return False, valid and reaped
            except OSError:
                return False, False
            return True, False

        success = False
        half_window = CHILD_RETIRE_TIMEOUT_SECONDS / 2.0
        try:
            sent, reaped = signal_exact(signal.SIGTERM)
            if reaped:
                success = True
            elif sent and wait_reaped(time.monotonic() + half_window):
                success = True
            elif sent:
                sent_kill, reaped = signal_exact(signal.SIGKILL)
                success = reaped or (
                    sent_kill and wait_reaped(time.monotonic() + half_window)
                )
            return success
        finally:
            terminal(handle, retiring)

    def after_fork() -> None:
        nonlocal lock, epoch, seal
        registry.clear()
        forked_operations.clear()
        lock = threading.RLock()
        epoch = object()
        seal = object()

    return require_environment, fork_for_query_operation, wait_until, retire, after_fork


(
    _assert_query_child_owner_environment,
    _fork_query_child_for_operation,
    _wait_query_child_until,
    _retire_query_child_bounded,
    _clear_query_child_owner_after_fork,
) = _make_query_child_owner()


def run_submit_channel_once(operation: SubmitChannelOperation, request_frame: bytes) -> dict[str, Any]:
    """Run the sole production fixed-SSH path for the typed W5 submit seam."""
    _require(type(operation) is SubmitChannelOperation, "exact SubmitChannelOperation is required")
    _assert_production_binding()
    snapshot = _claim_submit_operation(operation, request_frame)
    ssh_fd = -1
    read_in = -1
    write_in = -1
    read_out = -1
    write_out = -1
    pid = -1
    forked = False
    child_reaped = False
    child_wait_attempted = False
    try:
        _require_descriptor_exec_available()
        profile_raw = snapshot.transport_profile_raw
        profile = load_transport_profile(profile_raw)
        argv = build_controller_argv(profile_raw, operation)
        ssh_fd = _open_reviewed_executable(
            SSH_EXECUTABLE,
            profile["ssh"]["executable_sha256"],
        )
        read_in, write_in = _pipe_cloexec()
        read_out, write_out = _pipe_cloexec()
        pid = _FROZEN_FORK()
        if pid == 0:  # pragma: no cover - real controller only
            try:
                os.dup2(read_in, 0)
                os.dup2(write_out, 1)
                _assert_reviewed_executable_descriptor(
                    ssh_fd,
                    SSH_EXECUTABLE,
                    profile["ssh"]["executable_sha256"],
                )
                for descriptor in (read_in, write_in, read_out, write_out):
                    if descriptor > 2:
                        _close_quiet(descriptor)
                _descriptor_execve(ssh_fd, argv, FIXED_ENVIRONMENT)
            except BaseException:
                os._exit(127)
        forked = True
        _close_quiet(read_in, write_out, ssh_fd)
        read_in = -1
        write_out = -1
        ssh_fd = -1
        operation_deadline = time.monotonic() + SUBMIT_OPERATION_TIMEOUT_SECONDS
        try:
            write_deadline = min(
                operation_deadline,
                time.monotonic() + CHANNEL_TIMEOUT_SECONDS,
            )
            _send_frame_until(write_in, request_frame, write_deadline)
            write_in = -1
            response_deadline = min(
                operation_deadline,
                time.monotonic() + RESPONSE_TIMEOUT_SECONDS,
            )
            response = read_single_response_until(read_out, response_deadline)
            child_wait_attempted = True
            child_deadline = min(
                operation_deadline,
                time.monotonic() + CHILD_RETIRE_TIMEOUT_SECONDS,
            )
            child_exit = _wait_child_until(pid, child_deadline)
            child_reaped = True
            _require(child_exit == 0, "fixed channel child exit is uncertain")
            return response
        except BaseException as exc:
            raise ControllerTransportUnknown(
                "remote effect may have occurred; reconciliation only"
            ) from exc
    finally:
        _finish_operation(operation)
        _close_quiet(read_in, write_in, read_out, write_out, ssh_fd)
        if forked and not child_reaped and not child_wait_attempted:
            _retire_child_bounded(pid)


def _read_query_transport_until(
    response_descriptor: int,
    stderr_descriptor: int,
    deadline: float,
) -> dict[str, Any]:
    """Read one canonical response and empty SSH stderr under one deadline."""

    _require(
        type(response_descriptor) is int
        and response_descriptor >= 0
        and type(stderr_descriptor) is int
        and stderr_descriptor >= 0
        and type(deadline) is float,
        "query transport descriptors differ",
    )
    descriptors = {response_descriptor: bytearray(), stderr_descriptor: bytearray()}
    limits = {
        response_descriptor: MAX_QUERY_RESPONSE_FRAME_BYTES + 4,
        stderr_descriptor: 64 * 1024,
    }
    for descriptor in descriptors:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    open_descriptors = set(descriptors)
    while open_descriptors:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControllerTransportUnknown("query response deadline expired")
        readable, _, exceptional = select.select(
            tuple(open_descriptors), (), tuple(open_descriptors), remaining
        )
        if exceptional:
            raise ControllerTransportUnknown("query response descriptor failed")
        if not readable:
            raise ControllerTransportUnknown("query response deadline expired")
        for descriptor in readable:
            try:
                chunk = os.read(descriptor, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                open_descriptors.remove(descriptor)
                continue
            descriptors[descriptor].extend(chunk)
            _require(
                len(descriptors[descriptor]) <= limits[descriptor],
                "query response or SSH stderr exceeds its bound",
            )
    stderr = bytes(descriptors[stderr_descriptor])
    _require(stderr == b"", "fixed SSH query emitted stderr")
    frame = bytes(descriptors[response_descriptor])
    _validate_single_canonical_frame_bytes(frame)
    return json.loads(frame[4:].decode("utf-8"))


def run_query_channel_once(
    operation: QueryExactJobOperation,
    request_frame: bytes,
    query_authority: object,
) -> dict[str, Any]:
    """Run Q1's sole fixed-SSH query path; no caller-selected job or argv exists."""

    _require(type(operation) is QueryExactJobOperation, "exact QueryExactJobOperation is required")
    _assert_production_binding()
    snapshot = _claim_query_operation(operation)
    operation_deadline = time.monotonic() + SUBMIT_OPERATION_TIMEOUT_SECONDS
    ssh_fd = -1
    read_in = write_in = read_out = write_out = read_err = write_err = -1
    pid = -1
    forked = False
    child_reaped = False
    child_handle = None
    try:
        authority_assert, authority_type = _resolve_qstat_query_authority_owner()
        _require(type(query_authority) is authority_type, "exact qstat query authority is required")
        authority_assert(query_authority, operation, request_frame)
        _validate_single_canonical_frame_bytes(request_frame)
        _require_descriptor_exec_available()
        profile_raw = snapshot.transport_profile_raw
        profile = load_transport_profile(profile_raw)
        argv = build_controller_argv(profile_raw, operation)
        ssh_fd = _open_reviewed_executable(SSH_EXECUTABLE, profile["ssh"]["executable_sha256"])
        read_in, write_in = _pipe_cloexec()
        read_out, write_out = _pipe_cloexec()
        read_err, write_err = _pipe_cloexec()
        try:
            pid, child_handle = _fork_query_child_for_operation(operation)
        except BaseException as exc:
            raise ControllerTransportUnknown(
                "query child fork/registration is unknown; no retry"
            ) from exc
        if pid == 0:  # pragma: no cover - real controller only
            try:
                os.dup2(read_in, 0)
                os.dup2(write_out, 1)
                os.dup2(write_err, 2)
                _assert_reviewed_executable_descriptor(
                    ssh_fd, SSH_EXECUTABLE, profile["ssh"]["executable_sha256"]
                )
                for descriptor in (
                    read_in, write_in, read_out, write_out, read_err, write_err
                ):
                    if descriptor > 2:
                        _close_quiet(descriptor)
                _descriptor_execve(ssh_fd, argv, FIXED_ENVIRONMENT)
            except BaseException:
                os._exit(127)
        forked = True
        _require(
            type(child_handle) is _QueryChildHandle,
            "query fork did not return its exact child handle",
        )
        _close_quiet(read_in, write_out, write_err, ssh_fd)
        read_in = write_out = write_err = ssh_fd = -1
        try:
            _send_frame_until(write_in, request_frame, operation_deadline)
            write_in = -1
            response = _read_query_transport_until(read_out, read_err, operation_deadline)
            child_exit = _wait_query_child_until(child_handle, operation_deadline)
            child_reaped = True
            _require(child_exit == 0, "fixed SSH query child exit is uncertain")
            return response
        except BaseException as exc:
            raise ControllerTransportUnknown(
                "read-only query transport is unknown; no retry"
            ) from exc
    finally:
        _finish_operation(operation)
        _close_quiet(read_in, write_in, read_out, write_out, read_err, write_err, ssh_fd)
        if forked and not child_reaped and child_handle is not None:
            _retire_query_child_bounded(child_handle)


def run_fetch_channel_once(
    operation: FetchTerminalMinimumBundleOperation,
    request_frame: bytes,
) -> tuple[object, dict[str, Any]]:
    """Start one fixed SSH fetch and return the owner-held stream session."""

    _require(
        type(operation) is FetchTerminalMinimumBundleOperation,
        "exact FetchTerminalMinimumBundleOperation is required",
    )
    _assert_production_binding()
    expected_frame = project_fetch_request_frame_for_review(operation)
    _require(
        type(request_frame) is bytes
        and request_frame == expected_frame,
        "fetch request differs from the exact operation",
    )
    snapshot = _claim_fetch_operation(operation)
    profile = load_read_profile(
        snapshot.read_profile_raw, snapshot.transport_profile_raw,
    )
    deadline = time.monotonic() + int(
        profile["server_read"]["fetch"]["timeout_seconds"], 10,
    )
    ssh_fd = -1
    read_in = write_in = read_out = write_out = read_err = write_err = -1
    child_handle = None
    stream_started = False
    try:
        _require_descriptor_exec_available()
        transport = load_transport_profile(snapshot.transport_profile_raw)
        argv = build_controller_argv(snapshot.transport_profile_raw, operation)
        ssh_fd = _open_reviewed_executable(
            SSH_EXECUTABLE, transport["ssh"]["executable_sha256"],
        )
        read_in, write_in = _pipe_cloexec()
        read_out, write_out = _pipe_cloexec()
        read_err, write_err = _pipe_cloexec()
        try:
            pid, child_handle = _fork_query_child_for_operation(operation)
        except BaseException as exc:
            raise ControllerTransportUnknown(
                "fetch child fork/registration is unknown; no retry"
            ) from exc
        if pid == 0:  # pragma: no cover - real controller only
            try:
                os.dup2(read_in, 0)
                os.dup2(write_out, 1)
                os.dup2(write_err, 2)
                _assert_reviewed_executable_descriptor(
                    ssh_fd, SSH_EXECUTABLE,
                    transport["ssh"]["executable_sha256"],
                )
                for descriptor in (
                    read_in, write_in, read_out, write_out, read_err, write_err,
                ):
                    if descriptor > 2:
                        _close_quiet(descriptor)
                _descriptor_execve(ssh_fd, argv, FIXED_ENVIRONMENT)
            except BaseException:
                os._exit(127)
        _require(
            type(child_handle) is _QueryChildHandle,
            "fetch child owner did not issue its exact handle",
        )
        _close_quiet(read_in, write_out, write_err, ssh_fd)
        read_in = write_out = write_err = ssh_fd = -1
        _send_frame_until(write_in, request_frame, deadline)
        write_in = -1
        session, header = _FETCH_STREAM_BEGIN(
            read_out,
            operation,
            deadline,
            already_claimed=True,
            child_handle=child_handle,
            stderr_descriptor=read_err,
        )
        stream_started = True
        child_handle = None
        read_err = -1
        return session, header
    except ControllerTransportUnknown:
        raise
    except BaseException as exc:
        raise ControllerTransportUnknown(
            "fixed fetch transport is unknown; no retry"
        ) from exc
    finally:
        _close_quiet(
            read_in, write_in, read_out, write_out, read_err, write_err, ssh_fd,
        )
        if child_handle is not None:
            _retire_query_child_bounded(child_handle)
        if not stream_started:
            _finish_operation(operation)


def _validate_query_response_snapshot(
    snapshot: _OperationSnapshot,
    response: Any,
    profile: dict[str, Any],
) -> dict[str, Any]:
    value = _exact(
        copy.deepcopy(response),
        {
            "protocol", "status", "operation_id", "job_id", "qstat_stdout_base64",
            "qstat_stdout_sha256", "authority", "response_payload_sha256",
        },
        "query response",
    )
    supplied = _sha(value["response_payload_sha256"], "query response hash")
    _require(
        value["protocol"] == READ_PROTOCOL
        and value["status"] == "completed"
        and value["operation_id"] == snapshot.operation_id
        and value["job_id"] == snapshot.job_id
        and value["authority"] == {"authorizes_effect": False, "qsub_calls": "0"}
        and supplied == digest({**value, "response_payload_sha256": ""}),
        "query response identity or authority differs",
    )
    try:
        raw = base64.b64decode(value["qstat_stdout_base64"], validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise SharedFixedSSHChannelError("query response qstat bytes differ") from exc
    _require(
        0 < len(raw) <= int(profile["server_read"]["qstat"]["max_stdout_bytes"], 10)
        and hashlib.sha256(raw).hexdigest() == value["qstat_stdout_sha256"],
        "query response qstat bytes differ",
    )
    return value


def read_query_response_until(
    descriptor: int,
    operation: QueryExactJobOperation,
    deadline: float,
) -> dict[str, Any]:
    _require(type(operation) is QueryExactJobOperation, "exact QueryExactJobOperation is required")
    _assert_production_binding()
    _require(
        type(descriptor) is int and descriptor >= 0 and type(deadline) is float,
        "query acquisition arguments differ",
    )
    snapshot = _claim_query_operation(operation)
    try:
        _require(type(snapshot.read_profile_raw) is bytes, "query read profile differs")
        profile = load_read_profile(snapshot.read_profile_raw, snapshot.transport_profile_raw)
        maximum = min(
            MAX_CONTROL_FRAME_BYTES,
            int(profile["server_read"]["qstat"]["max_stdout_bytes"], 10) * 2 + 4096,
        )
        value = _read_canonical_frame_until(descriptor, deadline, maximum, "query response")
        _require_eof_until(descriptor, deadline, "query response")
        return _validate_query_response_snapshot(snapshot, value, profile)
    finally:
        _finish_operation(operation)


_FETCH_BUFFER_TEST_TOKEN = object()


def _read_fetch_response_buffered_for_tests_until(
    descriptor: int,
    operation: FetchTerminalMinimumBundleOperation,
    deadline: float,
    *,
    _test_token: object,
) -> tuple[dict[str, Any], bytearray, dict[str, Any]]:
    _require(
        _test_token is _FETCH_BUFFER_TEST_TOKEN,
        "buffered fetch response test token differs",
    )
    _require(
        type(operation) is FetchTerminalMinimumBundleOperation,
        "exact FetchTerminalMinimumBundleOperation is required",
    )
    _assert_production_binding()
    _require(
        type(descriptor) is int and descriptor >= 0 and type(deadline) is float,
        "fetch acquisition arguments differ",
    )
    snapshot = _claim_fetch_operation(operation)
    try:
        _require(type(snapshot.read_profile_raw) is bytes, "fetch read profile differs")
        profile = load_read_profile(snapshot.read_profile_raw, snapshot.transport_profile_raw)
        limits = profile["server_read"]["fetch"]
        max_total = int(limits["max_total_bytes"], 10)
        max_chunk = int(limits["max_chunk_bytes"], 10)
        max_chunks = int(limits["max_chunks"], 10)
        header = _read_canonical_frame_until(descriptor, deadline, 65536, "fetch control header")
        header = _exact(
            header,
            {"protocol", "status", "operation_id", "job_id", "chunk_count", "total_size_bytes", "bundle_commitment_sha256", "authority"},
            "fetch control header",
        )
        _require(
            header["protocol"] == READ_PROTOCOL
            and header["status"] == "streaming_terminal_minimum_bundle"
            and header["operation_id"] == snapshot.operation_id
            and header["job_id"] == snapshot.job_id
            and _sha(
                header["bundle_commitment_sha256"],
                "fetch bundle commitment",
            )
            and header["authority"] == {"authorizes_effect": False, "qsub_calls": "0"},
            "fetch control header identity or authority differs",
        )
        chunk_count = int(
            _positive_decimal(header["chunk_count"], "fetch chunk count", maximum=max_chunks),
            10,
        )
        total_size = int(
            _positive_decimal(header["total_size_bytes"], "fetch total size", maximum=max_total),
            10,
        )
        _require(
            total_size <= MAX_BUFFERED_FETCH_TEST_BYTES,
            "buffered fetch test exceeds its fixed small cap",
        )
        bundle_buffer = bytearray(total_size)
        observed = 0
        for _index in range(chunk_count):
            size = struct.unpack(
                "!I",
                _read_exact_until(descriptor, 4, deadline, "fetch chunk header"),
            )[0]
            _require(
                0 < size <= max_chunk and observed + size <= total_size,
                "fetch chunk size differs",
            )
            chunk = _read_exact_until(descriptor, size, deadline, "fetch chunk")
            bundle_buffer[observed:observed + size] = chunk
            observed += size
        _require(observed == total_size, "fetch stream total size differs")
        trailer = _read_canonical_frame_until(descriptor, deadline, 65536, "fetch trailer")
        trailer = _exact(
            trailer,
            {"protocol", "status", "operation_id", "job_id", "chunk_count", "total_size_bytes", "bundle_commitment_sha256", "bundle_sha256", "authority", "trailer_payload_sha256"},
            "fetch trailer",
        )
        bundle = bundle_buffer
        supplied = _sha(trailer["trailer_payload_sha256"], "fetch trailer hash")
        _require(
            trailer["protocol"] == READ_PROTOCOL
            and trailer["status"] == "completed"
            and trailer["operation_id"] == snapshot.operation_id
            and trailer["job_id"] == snapshot.job_id
            and trailer["chunk_count"] == header["chunk_count"]
            and trailer["total_size_bytes"] == header["total_size_bytes"]
            and trailer["bundle_sha256"] == hashlib.sha256(bundle).hexdigest()
            and trailer["bundle_commitment_sha256"]
            == header["bundle_commitment_sha256"]
            and trailer["authority"] == {"authorizes_effect": False, "qsub_calls": "0"}
            and supplied == digest({**trailer, "trailer_payload_sha256": ""}),
            "fetch trailer identity, digest, or authority differs",
        )
        _require_eof_until(descriptor, deadline, "fetch response")
        return header, bundle, trailer
    finally:
        _finish_operation(operation)


_FETCH_STREAM_TOKEN = object()


class _FetchResponseStreamSession:
    __slots__ = ("_key", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fetch response stream sessions are module-issued only")

    def __copy__(self) -> Any:
        raise TypeError("fetch response stream sessions are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("fetch response stream sessions are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("fetch response stream sessions are not serializable")


@dataclasses.dataclass(slots=True)
class _FetchStreamRecord:
    session: _FetchResponseStreamSession
    descriptor: int
    operation: FetchTerminalMinimumBundleOperation
    snapshot: _OperationSnapshot
    deadline: float
    header: dict[str, Any]
    max_chunk: int
    chunk_count: int
    total_size: int
    chunks_seen: int
    chunk_remaining: int
    observed: int
    hasher: Any
    creator_pid: int
    lock: Any
    child_handle: _QueryChildHandle | None
    stderr_descriptor: int


def _make_fetch_stream_owner() -> tuple[object, ...]:
    registry: dict[int, _FetchStreamRecord] = {}
    registry_lock = threading.RLock()

    def exact(session: Any) -> _FetchStreamRecord:
        _require(
            type(session) is _FetchResponseStreamSession
            and session._seal is _FETCH_STREAM_TOKEN,
            "exact fetch response stream session is required",
        )
        with registry_lock:
            record = registry.get(session._key)
        _require(
            type(record) is _FetchStreamRecord
            and record.session is session
            and record.creator_pid == os.getpid(),
            "fetch response stream session is absent, forked, or terminal",
        )
        return record

    def terminalize(record: _FetchStreamRecord, *, completed: bool) -> None:
        with registry_lock:
            if registry.get(record.session._key) is record:
                del registry[record.session._key]
        try:
            os.close(record.descriptor)
        except OSError:
            pass
        try:
            if record.child_handle is not None:
                if completed:
                    try:
                        stderr = bytearray()
                        while True:
                            remaining = record.deadline - time.monotonic()
                            _require(
                                remaining > 0,
                                "fetch child stderr deadline expired",
                            )
                            ready, _, exceptional = select.select(
                                [record.stderr_descriptor], [],
                                [record.stderr_descriptor], remaining,
                            )
                            _require(
                                not exceptional and bool(ready),
                                "fetch child stderr is unknown",
                            )
                            chunk = os.read(record.stderr_descriptor, 65536)
                            if not chunk:
                                break
                            stderr.extend(chunk)
                            _require(
                                len(stderr) <= 64 * 1024,
                                "fetch child stderr exceeds its fixed cap",
                            )
                        _require(stderr == b"", "fixed SSH fetch emitted stderr")
                        child_exit = _wait_query_child_until(
                            record.child_handle, record.deadline,
                        )
                        _require(child_exit == 0, "fixed fetch child exit differs")
                    except BaseException:
                        _retire_query_child_bounded(record.child_handle)
                        raise
                else:
                    _retire_query_child_bounded(record.child_handle)
        finally:
            if record.child_handle is not None:
                _close_quiet(record.stderr_descriptor)
            _finish_operation(record.operation)

    def begin(
        descriptor: int,
        operation: FetchTerminalMinimumBundleOperation,
        deadline: float,
        *,
        already_claimed: bool = False,
        child_handle: _QueryChildHandle | None = None,
        stderr_descriptor: int = -1,
    ) -> tuple[_FetchResponseStreamSession, dict[str, Any]]:
        _assert_production_binding()
        _require(
            type(descriptor) is int and descriptor >= 0
            and type(operation) is FetchTerminalMinimumBundleOperation
            and type(deadline) is float,
            "fetch response stream arguments differ",
        )
        _require(
            type(already_claimed) is bool
            and (
                (child_handle is None and stderr_descriptor == -1)
                or (
                    already_claimed
                    and type(child_handle) is _QueryChildHandle
                    and type(stderr_descriptor) is int
                    and stderr_descriptor >= 0
                )
            ),
            "fetch response child ownership differs",
        )
        snapshot = (
            _operation_snapshot(
                operation, FetchTerminalMinimumBundleOperation, {"running"},
            )
            if already_claimed
            else _claim_fetch_operation(operation)
        )
        owned_descriptor = -1
        try:
            _require(
                type(snapshot.read_profile_raw) is bytes,
                "fetch read profile differs",
            )
            profile = load_read_profile(
                snapshot.read_profile_raw, snapshot.transport_profile_raw,
            )
            limits = profile["server_read"]["fetch"]
            owned_descriptor = os.dup(descriptor)
            fcntl.fcntl(
                owned_descriptor,
                fcntl.F_SETFD,
                fcntl.fcntl(owned_descriptor, fcntl.F_GETFD)
                | fcntl.FD_CLOEXEC,
            )
            _require(
                bool(
                    fcntl.fcntl(owned_descriptor, fcntl.F_GETFD)
                    & fcntl.FD_CLOEXEC
                ),
                "fetch response stream descriptor is not close-on-exec",
            )
            header = _read_canonical_frame_until(
                owned_descriptor,
                deadline,
                65536,
                "fetch control header",
            )
            header = _exact(
                header,
                {
                    "protocol", "status", "operation_id", "job_id",
                    "chunk_count", "total_size_bytes",
                    "bundle_commitment_sha256", "authority",
                },
                "fetch control header",
            )
            max_chunks = int(limits["max_chunks"], 10)
            max_total = int(limits["max_total_bytes"], 10)
            chunk_count = int(
                _positive_decimal(
                    header["chunk_count"],
                    "fetch chunk count",
                    maximum=max_chunks,
                ),
                10,
            )
            total_size = int(
                _positive_decimal(
                    header["total_size_bytes"],
                    "fetch total size",
                    maximum=max_total,
                ),
                10,
            )
            _require(
                header["protocol"] == READ_PROTOCOL
                and header["status"]
                == "streaming_terminal_minimum_bundle"
                and header["operation_id"] == snapshot.operation_id
                and header["job_id"] == snapshot.job_id
                and _sha(
                    header["bundle_commitment_sha256"],
                    "fetch bundle commitment",
                )
                and header["authority"]
                == {"authorizes_effect": False, "qsub_calls": "0"},
                "fetch control header identity or authority differs",
            )
            session = object.__new__(_FetchResponseStreamSession)
            session._key = id(session)
            session._seal = _FETCH_STREAM_TOKEN
            record = _FetchStreamRecord(
                session=session,
                descriptor=owned_descriptor,
                operation=operation,
                snapshot=snapshot,
                deadline=deadline,
                header=copy.deepcopy(header),
                max_chunk=int(limits["max_chunk_bytes"], 10),
                chunk_count=chunk_count,
                total_size=total_size,
                chunks_seen=0,
                chunk_remaining=0,
                observed=0,
                hasher=hashlib.sha256(),
                creator_pid=os.getpid(),
                lock=threading.Lock(),
                child_handle=child_handle,
                stderr_descriptor=stderr_descriptor,
            )
            with registry_lock:
                _require(
                    session._key not in registry,
                    "fetch response stream key collision",
                )
                registry[session._key] = record
            owned_descriptor = -1
            return session, copy.deepcopy(header)
        except BaseException:
            if owned_descriptor >= 0:
                try:
                    os.close(owned_descriptor)
                except OSError:
                    pass
            if child_handle is not None:
                _retire_query_child_bounded(child_handle)
                _close_quiet(stderr_descriptor)
            _finish_operation(operation)
            raise

    def read_exact(session: Any, size: int) -> bytes:
        record = exact(session)
        _require(
            type(size) is int and 0 < size <= MAX_FETCH_CHUNK_BYTES,
            "fetch response stream read size differs",
        )
        try:
            with record.lock:
                output = bytearray()
                while len(output) < size:
                    if record.chunk_remaining == 0:
                        _require(
                            record.chunks_seen < record.chunk_count,
                            "fetch response stream ended early",
                        )
                        next_size = struct.unpack(
                            "!I",
                            _read_exact_until(
                                record.descriptor,
                                4,
                                record.deadline,
                                "fetch chunk header",
                            ),
                        )[0]
                        _require(
                            0 < next_size <= record.max_chunk
                            and record.observed + next_size
                            <= record.total_size,
                            "fetch chunk size differs",
                        )
                        record.chunk_remaining = next_size
                        record.chunks_seen += 1
                    take = min(
                        size - len(output), record.chunk_remaining,
                    )
                    chunk = _read_exact_until(
                        record.descriptor,
                        take,
                        record.deadline,
                        "fetch chunk",
                    )
                    output.extend(chunk)
                    record.hasher.update(chunk)
                    record.chunk_remaining -= take
                    record.observed += take
                return bytes(output)
        except BaseException:
            terminalize(record, completed=False)
            raise

    def assert_current(session: Any) -> None:
        exact(session)

    def exact_operation_snapshot(
        session: Any,
        operation: FetchTerminalMinimumBundleOperation,
    ) -> _OperationSnapshot:
        """Join one live production stream to its exact running operation."""

        record = exact(session)
        _require(
            type(operation) is FetchTerminalMinimumBundleOperation
            and record.operation is operation,
            "fetch response stream and operation are spliced",
        )
        snapshot = _operation_snapshot(
            operation, FetchTerminalMinimumBundleOperation, {"running"},
        )
        _require(
            snapshot == record.snapshot,
            "fetch response stream operation snapshot differs",
        )
        return snapshot

    def finish(session: Any) -> dict[str, Any]:
        record = exact(session)
        try:
            with record.lock:
                _require(
                    record.observed == record.total_size
                    and record.chunk_remaining == 0
                    and record.chunks_seen == record.chunk_count,
                    "fetch response stream is incomplete",
                )
                trailer = _read_canonical_frame_until(
                    record.descriptor,
                    record.deadline,
                    65536,
                    "fetch trailer",
                )
                trailer = _exact(
                    trailer,
                    {
                        "protocol", "status", "operation_id", "job_id",
                        "chunk_count", "total_size_bytes",
                        "bundle_commitment_sha256", "bundle_sha256",
                        "authority", "trailer_payload_sha256",
                    },
                    "fetch trailer",
                )
                supplied = _sha(
                    trailer["trailer_payload_sha256"],
                    "fetch trailer hash",
                )
                _require(
                    trailer["protocol"] == READ_PROTOCOL
                    and trailer["status"] == "completed"
                    and trailer["operation_id"]
                    == record.snapshot.operation_id
                    and trailer["job_id"] == record.snapshot.job_id
                    and trailer["chunk_count"]
                    == record.header["chunk_count"]
                    and trailer["total_size_bytes"]
                    == record.header["total_size_bytes"]
                    and trailer["bundle_sha256"]
                    == record.hasher.hexdigest()
                    and trailer["bundle_commitment_sha256"]
                    == record.header["bundle_commitment_sha256"]
                    and trailer["authority"]
                    == {"authorizes_effect": False, "qsub_calls": "0"}
                    and supplied
                    == digest({**trailer, "trailer_payload_sha256": ""}),
                    "fetch trailer identity, digest, or authority differs",
                )
                _require_eof_until(
                    record.descriptor,
                    record.deadline,
                    "fetch response",
                )
            terminalize(record, completed=True)
            return copy.deepcopy(trailer)
        except BaseException:
            terminalize(record, completed=False)
            raise

    def abandon(session: Any) -> None:
        terminalize(exact(session), completed=False)

    def after_fork_child() -> None:
        nonlocal registry_lock
        for record in tuple(registry.values()):
            try:
                os.close(record.descriptor)
            except OSError:
                pass
        registry.clear()
        registry_lock = threading.RLock()

    return (
        begin, read_exact, assert_current, exact_operation_snapshot,
        finish, abandon, after_fork_child,
    )


(
    _FETCH_STREAM_BEGIN,
    _FETCH_STREAM_READ_EXACT,
    _FETCH_STREAM_ASSERT,
    _FETCH_STREAM_OPERATION_SNAPSHOT,
    _FETCH_STREAM_FINISH,
    _FETCH_STREAM_ABANDON,
    _FETCH_STREAM_FORK_CHILD,
) = _make_fetch_stream_owner()


def _after_fork_child() -> None:
    global _OPERATION_TOKEN, _W5_OWNER_BINDING, _W5_OWNER_BINDING_LOCK
    global _QSTAT_OWNER_BINDING, _QSTAT_OWNER_BINDING_LOCK
    global _QSTAT_ISSUANCE_BINDING, _QSTAT_ISSUANCE_BINDING_LOCK
    _FETCH_STREAM_FORK_CHILD()
    _clear_operation_owner_after_fork()
    _clear_query_child_owner_after_fork()
    _OPERATION_TOKEN = object()
    _W5_OWNER_BINDING = None
    _W5_OWNER_BINDING_LOCK = threading.RLock()
    _QSTAT_OWNER_BINDING = None
    _QSTAT_OWNER_BINDING_LOCK = threading.RLock()
    _QSTAT_ISSUANCE_BINDING = None
    _QSTAT_ISSUANCE_BINDING_LOCK = threading.RLock()


_FROZEN_FORK = os.fork
_FROZEN_EXECVE = os.execve
_FROZEN_URANDOM = os.urandom
_FROZEN_PROFILE_VALIDATOR = validate_transport_profile
_FROZEN_PROFILE_LOADER = load_transport_profile
_FROZEN_READ_PROFILE_VALIDATOR = validate_read_profile
_FROZEN_READ_PROFILE_LOADER = load_read_profile
_FROZEN_ARGV_BUILDER = build_controller_argv
_FROZEN_REQUIRE = _require
_FROZEN_TEXT_VALIDATOR = _text
_FROZEN_ABSOLUTE_FILE_VALIDATOR = _absolute_file
_FROZEN_NO_FOLLOW_OPENER = _open_absolute_no_follow
_FROZEN_EXECUTABLE_OPENER = _open_reviewed_executable
_FROZEN_EXECUTABLE_ASSERT = _assert_reviewed_executable_descriptor
_FROZEN_DESCRIPTOR_EXEC = _descriptor_execve
_FROZEN_DESCRIPTOR_REQUIRE = _require_descriptor_exec_available
_FROZEN_PIPE_CLOEXEC = _pipe_cloexec
_FROZEN_CLOSE_QUIET = _close_quiet
_FROZEN_FRAME_WRITER = _write_frame_until
_FROZEN_FRAME_SENDER = _send_frame_until
_FROZEN_FRAME_READER = read_single_response_until
_FROZEN_CHILD_WAITER = _wait_child_until
_FROZEN_CHILD_RETIRER = _retire_child_bounded
_FROZEN_QUERY_CHILD_ENVIRONMENT = _assert_query_child_owner_environment
_FROZEN_QUERY_CHILD_FORK = _fork_query_child_for_operation
_FROZEN_QUERY_CHILD_WAITER = _wait_query_child_until
_FROZEN_QUERY_CHILD_RETIRER = _retire_query_child_bounded
_FROZEN_QUERY_CHILD_FORK_CLEAR = _clear_query_child_owner_after_fork
_FROZEN_QUERY_CHILD_OWNER_FACTORY = _make_query_child_owner
_FROZEN_QUERY_CHILD_HANDLE_TYPE = _QueryChildHandle
_FROZEN_QUERY_CHILD_RECORD_TYPE = _QueryChildRecord
_FROZEN_SUBMIT_ISSUER = issue_submit_channel_operation
_FROZEN_SUBMIT_ARGV_PROJECTION = project_submit_controller_argv_for_review
_FROZEN_W5_OWNER_RESOLVER = _resolve_w5_submit_authority_owner
_FROZEN_SUBMIT_RUNNER = run_submit_channel_once
_FROZEN_QSTAT_OWNER_RESOLVER = _resolve_qstat_query_authority_owner
_FROZEN_QSTAT_ISSUANCE_RESOLVER = _resolve_qstat_query_issuance_owner
_FROZEN_QUERY_TRANSPORT_READER = _read_query_transport_until
_FROZEN_QUERY_RUNNER = run_query_channel_once
_FROZEN_QUERY_ISSUER = issue_query_exact_job_operation
_FROZEN_QUERY_TEST_ISSUER = _issue_query_exact_job_operation_for_testing
_FROZEN_FETCH_ISSUER = issue_fetch_terminal_minimum_bundle_operation
_FROZEN_FETCH_TEST_ISSUER = _issue_fetch_terminal_minimum_bundle_operation_for_testing
_FROZEN_FETCH_ISSUANCE_RESOLVER = _resolve_terminal_fetch_issuance_owner
_FROZEN_QUERY_PROJECTION = project_query_request_frame_for_review
_FROZEN_FETCH_PROJECTION = project_fetch_request_frame_for_review
_FROZEN_FETCH_RUNNER = run_fetch_channel_once
_FROZEN_CANONICAL_FRAME = _canonical_frame
_FROZEN_CANONICAL_FRAME_VALIDATOR = _validate_single_canonical_frame_bytes
_FROZEN_RECORD_COMMITMENT = _record_commitment
_FROZEN_SEALED_RECORD = _sealed_record
_FROZEN_RECORD_SNAPSHOT = _record_snapshot
_FROZEN_QUERY_RESPONSE_VALIDATOR = _validate_query_response_snapshot
_FROZEN_QUERY_CODEC = read_query_response_until
_FROZEN_FETCH_CODEC = _read_fetch_response_buffered_for_tests_until
_FROZEN_FETCH_STREAM_BEGIN = _FETCH_STREAM_BEGIN
_FROZEN_FETCH_STREAM_READ_EXACT = _FETCH_STREAM_READ_EXACT
_FROZEN_FETCH_STREAM_ASSERT = _FETCH_STREAM_ASSERT
_FROZEN_FETCH_STREAM_OPERATION_SNAPSHOT = _FETCH_STREAM_OPERATION_SNAPSHOT
_FROZEN_FETCH_STREAM_FINISH = _FETCH_STREAM_FINISH
_FROZEN_FETCH_STREAM_ABANDON = _FETCH_STREAM_ABANDON
_FROZEN_FETCH_STREAM_FORK_CHILD = _FETCH_STREAM_FORK_CHILD
_FROZEN_FETCH_STREAM_TYPE = _FetchResponseStreamSession
_FROZEN_OPERATION_OWNER_FACTORY = _make_operation_owner
_FROZEN_OPERATION_SNAPSHOT = _operation_snapshot
_FROZEN_OPERATION_PROJECTION = _operation_projection
_FROZEN_SUBMIT_CLAIM = _claim_submit_operation
_FROZEN_QUERY_CLAIM = _claim_query_operation
_FROZEN_FETCH_CLAIM = _claim_fetch_operation
_FROZEN_OPERATION_FINISH = _finish_operation
_FROZEN_OPERATION_FORK_CLEAR = _clear_operation_owner_after_fork
_FROZEN_SUBSYSTEM_MAPPER = _subsystem_for_operation
_FROZEN_SELECT = select.select
_FROZEN_FCNTL = fcntl.fcntl
_FROZEN_OS_OPEN = os.open
_FROZEN_OS_READ = os.read
_FROZEN_OS_WRITE = os.write
_FROZEN_OS_CLOSE = os.close
_FROZEN_OS_WAITPID = os.waitpid
_FROZEN_OS_KILL = os.kill
_FROZEN_GETSIGNAL = signal.getsignal
_FROZEN_OS_STAT = os.stat
_FROZEN_OS_FSTAT = os.fstat
_FROZEN_OS_DUP2 = os.dup2
_FROZEN_OS_DUP = os.dup
_FROZEN_MONOTONIC = time.monotonic
_FROZEN_SIGTERM = signal.SIGTERM
_FROZEN_SIGKILL = signal.SIGKILL
_FROZEN_SIGCHLD = signal.SIGCHLD
_FROZEN_SIG_DFL = signal.SIG_DFL
_FROZEN_GET_IDENT = threading.get_ident
_FROZEN_WEAK_KEY_DICTIONARY = weakref.WeakKeyDictionary
_FROZEN_SUBMIT_OPERATION_TYPE = SubmitChannelOperation
_FROZEN_QUERY_OPERATION_TYPE = QueryExactJobOperation
_FROZEN_FETCH_OPERATION_TYPE = FetchTerminalMinimumBundleOperation
_FROZEN_OPTIONS = SSH_FIXED_OPTIONS
_FROZEN_ENVIRONMENT = copy.deepcopy(FIXED_ENVIRONMENT)
_FROZEN_TRANSPORT_POLICY = copy.deepcopy(TRANSPORT_POLICY)
_FROZEN_READ_POLICY = copy.deepcopy(READ_POLICY)
_FROZEN_SSH_EXECUTABLE = SSH_EXECUTABLE
_FROZEN_SUBMIT_SUBSYSTEM = SUBMIT_SUBSYSTEM
_FROZEN_READ_SUBSYSTEM = READ_SUBSYSTEM
_FROZEN_CHANNEL_TIMEOUT_SECONDS = CHANNEL_TIMEOUT_SECONDS
_FROZEN_RESPONSE_TIMEOUT_SECONDS = RESPONSE_TIMEOUT_SECONDS
_FROZEN_CHILD_RETIRE_TIMEOUT_SECONDS = CHILD_RETIRE_TIMEOUT_SECONDS
_FROZEN_SUBMIT_OPERATION_TIMEOUT_SECONDS = SUBMIT_OPERATION_TIMEOUT_SECONDS
_FROZEN_MAX_TERMINAL_OPERATION_RECORDS = MAX_TERMINAL_OPERATION_RECORDS
_FROZEN_MAX_QUERY_RESPONSE_FRAME_BYTES = MAX_QUERY_RESPONSE_FRAME_BYTES
_FROZEN_MAX_FETCH_TOTAL_BYTES = MAX_FETCH_TOTAL_BYTES
_FROZEN_MAX_FETCH_CHUNK_BYTES = MAX_FETCH_CHUNK_BYTES
_FROZEN_MAX_BUFFERED_FETCH_TEST_BYTES = MAX_BUFFERED_FETCH_TEST_BYTES
_FROZEN_PBS_BASENAME = PBS_BASENAME


def _assert_production_binding() -> None:
    with open(__file__, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _FROZEN_REQUIRE(
        source_sha256 == _EXECUTED_SOURCE_SHA256
        and os.fork is _FROZEN_FORK
        and os.execve is _FROZEN_EXECVE
        and os.urandom is _FROZEN_URANDOM
        and validate_transport_profile is _FROZEN_PROFILE_VALIDATOR
        and load_transport_profile is _FROZEN_PROFILE_LOADER
        and validate_read_profile is _FROZEN_READ_PROFILE_VALIDATOR
        and load_read_profile is _FROZEN_READ_PROFILE_LOADER
        and build_controller_argv is _FROZEN_ARGV_BUILDER
        and _require is _FROZEN_REQUIRE
        and _text is _FROZEN_TEXT_VALIDATOR
        and _absolute_file is _FROZEN_ABSOLUTE_FILE_VALIDATOR
        and _open_absolute_no_follow is _FROZEN_NO_FOLLOW_OPENER
        and _open_reviewed_executable is _FROZEN_EXECUTABLE_OPENER
        and _assert_reviewed_executable_descriptor is _FROZEN_EXECUTABLE_ASSERT
        and _descriptor_execve is _FROZEN_DESCRIPTOR_EXEC
        and _require_descriptor_exec_available is _FROZEN_DESCRIPTOR_REQUIRE
        and _pipe_cloexec is _FROZEN_PIPE_CLOEXEC
        and _close_quiet is _FROZEN_CLOSE_QUIET
        and _write_frame_until is _FROZEN_FRAME_WRITER
        and _send_frame_until is _FROZEN_FRAME_SENDER
        and read_single_response_until is _FROZEN_FRAME_READER
        and _wait_child_until is _FROZEN_CHILD_WAITER
        and _retire_child_bounded is _FROZEN_CHILD_RETIRER
        and _assert_query_child_owner_environment is _FROZEN_QUERY_CHILD_ENVIRONMENT
        and _fork_query_child_for_operation is _FROZEN_QUERY_CHILD_FORK
        and _wait_query_child_until is _FROZEN_QUERY_CHILD_WAITER
        and _retire_query_child_bounded is _FROZEN_QUERY_CHILD_RETIRER
        and _clear_query_child_owner_after_fork is _FROZEN_QUERY_CHILD_FORK_CLEAR
        and _make_query_child_owner is _FROZEN_QUERY_CHILD_OWNER_FACTORY
        and _QueryChildHandle is _FROZEN_QUERY_CHILD_HANDLE_TYPE
        and _QueryChildRecord is _FROZEN_QUERY_CHILD_RECORD_TYPE
        and issue_submit_channel_operation is _FROZEN_SUBMIT_ISSUER
        and project_submit_controller_argv_for_review is _FROZEN_SUBMIT_ARGV_PROJECTION
        and _resolve_w5_submit_authority_owner is _FROZEN_W5_OWNER_RESOLVER
        and run_submit_channel_once is _FROZEN_SUBMIT_RUNNER
        and _resolve_qstat_query_authority_owner is _FROZEN_QSTAT_OWNER_RESOLVER
        and _resolve_qstat_query_issuance_owner is _FROZEN_QSTAT_ISSUANCE_RESOLVER
        and _read_query_transport_until is _FROZEN_QUERY_TRANSPORT_READER
        and run_query_channel_once is _FROZEN_QUERY_RUNNER
        and issue_query_exact_job_operation is _FROZEN_QUERY_ISSUER
        and _issue_query_exact_job_operation_for_testing is _FROZEN_QUERY_TEST_ISSUER
        and issue_fetch_terminal_minimum_bundle_operation is _FROZEN_FETCH_ISSUER
        and _issue_fetch_terminal_minimum_bundle_operation_for_testing
        is _FROZEN_FETCH_TEST_ISSUER
        and _resolve_terminal_fetch_issuance_owner
        is _FROZEN_FETCH_ISSUANCE_RESOLVER
        and project_query_request_frame_for_review is _FROZEN_QUERY_PROJECTION
        and project_fetch_request_frame_for_review is _FROZEN_FETCH_PROJECTION
        and run_fetch_channel_once is _FROZEN_FETCH_RUNNER
        and _canonical_frame is _FROZEN_CANONICAL_FRAME
        and _validate_single_canonical_frame_bytes is _FROZEN_CANONICAL_FRAME_VALIDATOR
        and _record_commitment is _FROZEN_RECORD_COMMITMENT
        and _sealed_record is _FROZEN_SEALED_RECORD
        and _record_snapshot is _FROZEN_RECORD_SNAPSHOT
        and _validate_query_response_snapshot is _FROZEN_QUERY_RESPONSE_VALIDATOR
        and read_query_response_until is _FROZEN_QUERY_CODEC
        and _read_fetch_response_buffered_for_tests_until is _FROZEN_FETCH_CODEC
        and _FETCH_STREAM_BEGIN is _FROZEN_FETCH_STREAM_BEGIN
        and _FETCH_STREAM_READ_EXACT is _FROZEN_FETCH_STREAM_READ_EXACT
        and _FETCH_STREAM_ASSERT is _FROZEN_FETCH_STREAM_ASSERT
        and _FETCH_STREAM_OPERATION_SNAPSHOT
        is _FROZEN_FETCH_STREAM_OPERATION_SNAPSHOT
        and _FETCH_STREAM_FINISH is _FROZEN_FETCH_STREAM_FINISH
        and _FETCH_STREAM_ABANDON is _FROZEN_FETCH_STREAM_ABANDON
        and _FETCH_STREAM_FORK_CHILD is _FROZEN_FETCH_STREAM_FORK_CHILD
        and _FetchResponseStreamSession is _FROZEN_FETCH_STREAM_TYPE
        and _make_operation_owner is _FROZEN_OPERATION_OWNER_FACTORY
        and _operation_snapshot is _FROZEN_OPERATION_SNAPSHOT
        and _operation_projection is _FROZEN_OPERATION_PROJECTION
        and _claim_submit_operation is _FROZEN_SUBMIT_CLAIM
        and _claim_query_operation is _FROZEN_QUERY_CLAIM
        and _claim_fetch_operation is _FROZEN_FETCH_CLAIM
        and _finish_operation is _FROZEN_OPERATION_FINISH
        and _clear_operation_owner_after_fork is _FROZEN_OPERATION_FORK_CLEAR
        and _subsystem_for_operation is _FROZEN_SUBSYSTEM_MAPPER
        and select.select is _FROZEN_SELECT
        and fcntl.fcntl is _FROZEN_FCNTL
        and os.open is _FROZEN_OS_OPEN
        and os.read is _FROZEN_OS_READ
        and os.write is _FROZEN_OS_WRITE
        and os.close is _FROZEN_OS_CLOSE
        and os.waitpid is _FROZEN_OS_WAITPID
        and os.kill is _FROZEN_OS_KILL
        and signal.getsignal is _FROZEN_GETSIGNAL
        and os.stat is _FROZEN_OS_STAT
        and os.fstat is _FROZEN_OS_FSTAT
        and os.dup2 is _FROZEN_OS_DUP2
        and os.dup is _FROZEN_OS_DUP
        and time.monotonic is _FROZEN_MONOTONIC
        and signal.SIGTERM == _FROZEN_SIGTERM
        and signal.SIGKILL == _FROZEN_SIGKILL
        and signal.SIGCHLD == _FROZEN_SIGCHLD
        and signal.SIG_DFL is _FROZEN_SIG_DFL
        and threading.get_ident is _FROZEN_GET_IDENT
        and weakref.WeakKeyDictionary is _FROZEN_WEAK_KEY_DICTIONARY
        and SubmitChannelOperation is _FROZEN_SUBMIT_OPERATION_TYPE
        and QueryExactJobOperation is _FROZEN_QUERY_OPERATION_TYPE
        and FetchTerminalMinimumBundleOperation is _FROZEN_FETCH_OPERATION_TYPE
        and SSH_FIXED_OPTIONS == _FROZEN_OPTIONS
        and FIXED_ENVIRONMENT == _FROZEN_ENVIRONMENT
        and TRANSPORT_POLICY == _FROZEN_TRANSPORT_POLICY
        and READ_POLICY == _FROZEN_READ_POLICY
        and SSH_EXECUTABLE == _FROZEN_SSH_EXECUTABLE == "/usr/bin/ssh"
        and SUBMIT_SUBSYSTEM == _FROZEN_SUBMIT_SUBSYSTEM == "auto-g16-direct-one-hop-v1"
        and READ_SUBSYSTEM == _FROZEN_READ_SUBSYSTEM == "auto-g16-direct-one-hop-read-v1"
        and CHANNEL_TIMEOUT_SECONDS == _FROZEN_CHANNEL_TIMEOUT_SECONDS == 30.0
        and RESPONSE_TIMEOUT_SECONDS == _FROZEN_RESPONSE_TIMEOUT_SECONDS == 30.0
        and CHILD_RETIRE_TIMEOUT_SECONDS == _FROZEN_CHILD_RETIRE_TIMEOUT_SECONDS == 5.0
        and SUBMIT_OPERATION_TIMEOUT_SECONDS == _FROZEN_SUBMIT_OPERATION_TIMEOUT_SECONDS == 65.0
        and MAX_TERMINAL_OPERATION_RECORDS == _FROZEN_MAX_TERMINAL_OPERATION_RECORDS == 8
        and MAX_QUERY_RESPONSE_FRAME_BYTES
        == _FROZEN_MAX_QUERY_RESPONSE_FRAME_BYTES
        == 512 * 1024
        and MAX_FETCH_TOTAL_BYTES == _FROZEN_MAX_FETCH_TOTAL_BYTES == 1_092_943_959
        and MAX_FETCH_CHUNK_BYTES == _FROZEN_MAX_FETCH_CHUNK_BYTES == 4 * 1024 * 1024
        and MAX_BUFFERED_FETCH_TEST_BYTES
        == _FROZEN_MAX_BUFFERED_FETCH_TEST_BYTES == 2 * 1024 * 1024
        and PBS_BASENAME == _FROZEN_PBS_BASENAME == "auto-g16-job.pbs",
        "shared fixed SSH production source, function, executable, or option binding differs",
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


__all__ = [
    "ControllerTransportUnknown",
    "FetchTerminalMinimumBundleOperation",
    "QueryExactJobOperation",
    "SharedFixedSSHChannelError",
    "SubmitChannelOperation",
    "issue_fetch_terminal_minimum_bundle_operation",
    "issue_submit_channel_operation",
    "load_read_profile",
    "load_transport_profile",
    "project_submit_controller_argv_for_review",
    "project_fetch_request_frame_for_review",
    "project_query_request_frame_for_review",
    "read_query_response_until",
    "run_submit_channel_once",
    "run_fetch_channel_once",
    "validate_read_profile",
    "validate_transport_profile",
]
