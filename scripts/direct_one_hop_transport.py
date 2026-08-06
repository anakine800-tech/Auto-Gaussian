#!/usr/bin/env python3
"""Fixed direct-SSH / pbs_legacy_v1 W5 effect consumer.

The production entrypoints accept no host, path, command, argv, environment,
callback, or transport object.  The server-side operation consumes only the
same-process typed seam issued by ``direct_trusted_session_composition``.
Tests use the private deterministic driver factory; that driver is rejected by
the production entrypoint and can never become production authority.
"""

from __future__ import annotations

import copy
import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import select
import stat
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any

import direct_durable_submission_journal as W2
import direct_root_fixed_mutation_consumer as W4
import direct_trusted_session_composition as SESSION


TRANSPORT_PROFILE_SCHEMA = "auto-g16-direct-one-hop-transport-profile/1"
PBS_REVIEW_SCHEMA = "auto-g16-reviewed-direct-pbs-script/1"
RESULT_SCHEMA = "auto-g16-direct-one-hop-submission-result/1"
PROTOCOL = "auto-g16-direct-one-hop-transport/1"
BACKEND_KIND = "direct_ssh_pbs"
TOPOLOGY = "mac_controller_direct_ssh_server_child"
SCHEDULER_DIALECT = "pbs_legacy_v1"
INPUT_BASENAME = "approved-input.gjf"
PBS_BASENAME = "auto-g16-job.pbs"
CHECKSUMS_BASENAME = "checksums.sha256"
SUBMISSION_RECEIPT_BASENAME = "submission-receipt.json"
ALLOWLIST = (INPUT_BASENAME, PBS_BASENAME, CHECKSUMS_BASENAME, SUBMISSION_RECEIPT_BASENAME)
QSUB_EXECUTABLE = "/usr/bin/qsub"
QSUB_ARGV = (QSUB_EXECUTABLE, "--", PBS_BASENAME)
SSH_EXECUTABLE = "/usr/bin/ssh"
SSH_SUBSYSTEM = "auto-g16-direct-one-hop-v1"
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
MAX_PROFILE_BYTES = 256 * 1024
MAX_STDOUT_BYTES = 4096
MAX_FRAME_BYTES = 32 * 1024 * 1024
CONTROLLER_WRITE_TIMEOUT_SECONDS = 30.0
CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS = 5.0
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
POSITIVE_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")
JOB_ID_RE = re.compile(r"^(?P<sequence>[1-9][0-9]{0,19})\.(?P<server>[A-Za-z0-9][A-Za-z0-9.-]{0,127})\n$")
JOURNAL_ID_RE = re.compile(r"^direct-durable-submission-journal-[a-f0-9]{64}$")
ATTEMPT_ID_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
RECEIPT_ID_RE = re.compile(r"^direct-submission-receipt-[a-f0-9]{64}$")
CONTROLLER_REQUEST_ID_RE = re.compile(r"^direct-controller-request-[a-f0-9]{64}$")
FIXED_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C"}
_EXECUTED_SOURCE_SHA256 = globals().get("__reviewed_source_sha256__")
if _EXECUTED_SOURCE_SHA256 is None:
    with open(__file__, "rb") as _source_handle:
        _EXECUTED_SOURCE_SHA256 = hashlib.sha256(_source_handle.read()).hexdigest()
POLICY = {
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


class DirectOneHopTransportError(ValueError):
    pass


class SubmissionOutcomeUnknown(RuntimeError):
    pass


class ControllerTransportUnknown(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectOneHopTransportError(message)


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
        raise DirectOneHopTransportError("value is not canonical JSON") from exc


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
            "executable", "executable_sha256", "configuration_files", "system_policy_evidence_sha256", "host", "user", "port", "identity_file",
            "known_hosts_file", "batch_mode", "identities_only",
            "strict_host_key_checking", "subsystem",
        },
        "SSH profile",
    )
    _require(ssh["executable"] == SSH_EXECUTABLE, "SSH executable differs")
    _sha(ssh["executable_sha256"], "SSH executable")
    _sha(ssh["system_policy_evidence_sha256"], "SSH system policy evidence")
    _require(
        ssh["configuration_files"] == "disabled_by_F_none",
        "SSH configuration-file policy differs",
    )
    _require(type(ssh["host"]) is str and HOST_RE.fullmatch(ssh["host"]) is not None, "SSH host differs")
    _require(type(ssh["user"]) is str and USER_RE.fullmatch(ssh["user"]) is not None, "SSH user differs")
    _positive_decimal(ssh["port"], "SSH port", maximum=65535)
    _absolute_file(ssh["identity_file"], "SSH identity file")
    _absolute_file(ssh["known_hosts_file"], "SSH known-hosts file")
    _require(
        ssh["batch_mode"] is True
        and ssh["identities_only"] is True
        and ssh["strict_host_key_checking"] is True
        and ssh["subsystem"] == SSH_SUBSYSTEM,
        "SSH identity or subsystem policy differs",
    )
    server = _exact(
        profile["server"],
        {"python_executable", "python_executable_sha256", "isolated_flags", "working_directory", "environment", "allowed_root", "entrypoint_source_sha256"},
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
    qsub = _exact(profile["qsub"], {"executable", "executable_sha256", "argv", "working_directory", "stdout_grammar"}, "qsub profile")
    _require(
        qsub["executable"] == QSUB_EXECUTABLE
        and SHA_RE.fullmatch(qsub["executable_sha256"]) is not None
        and qsub["argv"] == list(QSUB_ARGV)
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
        and _positive_decimal(pbs_artifact["size_bytes"], "reviewed PBS artifact size")
        and pbs_artifact["owner"] == "reviewed_direct_pbs_artifact_owner",
        "reviewed PBS artifact identity differs",
    )
    _sha(pbs_artifact["sha256"], "reviewed PBS artifact")
    _sha(pbs_artifact["review_payload_sha256"], "reviewed PBS artifact review")
    _require(profile["safety"] == POLICY, "transport safety policy differs")
    supplied = _sha(profile["profile_payload_sha256"], "transport profile hash")
    check = copy.deepcopy(profile)
    check["profile_payload_sha256"] = ""
    _require(supplied == digest(check), "transport profile self-hash differs")
    return profile


def load_transport_profile(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PROFILE_BYTES, "transport profile bytes differ")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectOneHopTransportError("transport profile is not exact JSON") from exc
    profile = validate_transport_profile(value)
    _require(raw == canonical_bytes(profile), "transport profile bytes are not canonical")
    return profile


def build_controller_argv(profile_raw: bytes) -> tuple[str, ...]:
    """Build the only production SSH argv from the reviewed hash-bound profile."""
    profile = load_transport_profile(profile_raw)
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
        SSH_SUBSYSTEM,
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
    named = os.stat(path, follow_symlinks=False)
    _require(
        _executable_identity(before) == _executable_identity(after) == _executable_identity(named)
        and hasher.hexdigest() == expected_sha256,
        "reviewed executable identity or hash differs",
    )


def _open_reviewed_executable(path: str, expected_sha256: str) -> int:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        _assert_reviewed_executable_descriptor(descriptor, path, expected_sha256)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _descriptor_execve(descriptor: int, argv: tuple[str, ...], environment: dict[str, str]) -> None:
    """Exec only the already-verified FD; never fall back to its original path."""
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
        raise DirectOneHopTransportError("descriptor exec is unavailable; path fallback forbidden") from exc
    _FROZEN_EXECVE(alias, list(argv), environment)
    raise AssertionError("descriptor exec unexpectedly returned")


def _require_descriptor_exec_available() -> None:
    _require(
        os.execve in os.supports_fd or os.path.isdir("/proc/self/fd"),
        "descriptor exec is unavailable; path fallback forbidden",
    )


_CONTROLLER_REQUEST_TOKEN = object()
_CONTROLLER_REQUEST_LOCK = threading.RLock()
_CONTROLLER_REQUEST_REGISTRY: dict[object, dict[str, Any]] = {}


class _ControllerRequestJoin:
    """Controller-owned one-use identity; its wire projection grants nothing."""

    __slots__ = ("request_id", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("controller request joins are owner-issued only")

    def assert_owner_sealed(self) -> None:
        with _CONTROLLER_REQUEST_LOCK:
            record = _CONTROLLER_REQUEST_REGISTRY.get(self)
            _require(
                type(self) is _ControllerRequestJoin
                and self._seal is _CONTROLLER_REQUEST_TOKEN
                and type(record) is dict
                and record.get("join") is self
                and record.get("pid") == os.getpid()
                and record.get("status") == "issued"
                and record.get("request_id") == self.request_id,
                "controller request join is foreign, forked, or terminal",
            )

    def __copy__(self) -> Any:
        raise TypeError("controller request joins are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("controller request joins are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("controller request joins are not serializable")


def _artifact_hashes(artifacts: SESSION.DirectServerSessionArtifacts) -> dict[str, str]:
    _require(type(artifacts) is SESSION.DirectServerSessionArtifacts, "exact reviewed artifact bundle is required")
    return {
        name: hashlib.sha256(getattr(artifacts, name)).hexdigest()
        for name in artifacts.__dataclass_fields__
    }


def _controller_request_id(nonce: str, artifact_sha256: dict[str, str]) -> str:
    _require(type(nonce) is str and SHA_RE.fullmatch(nonce) is not None, "controller request nonce differs")
    _require(
        type(artifact_sha256) is dict
        and set(artifact_sha256) == set(SESSION.DirectServerSessionArtifacts.__dataclass_fields__)
        and all(type(value) is str and SHA_RE.fullmatch(value) is not None for value in artifact_sha256.values()),
        "controller request artifact commitment differs",
    )
    return "direct-controller-request-" + digest(
        {
            "schema": "auto-g16-direct-one-hop-controller-request-id/1",
            "request_nonce": nonce,
            "artifact_sha256": artifact_sha256,
        }
    )


def _issue_controller_request_join(
    artifacts: SESSION.DirectServerSessionArtifacts,
) -> _ControllerRequestJoin:
    artifact_sha256 = _artifact_hashes(artifacts)
    nonce_bytes = _FROZEN_URANDOM(32)
    _require(type(nonce_bytes) is bytes and len(nonce_bytes) == 32, "controller request nonce source differs")
    nonce = nonce_bytes.hex()
    request_id = _controller_request_id(nonce, artifact_sha256)
    join = object.__new__(_ControllerRequestJoin)
    join.request_id = request_id
    join._seal = _CONTROLLER_REQUEST_TOKEN
    with _CONTROLLER_REQUEST_LOCK:
        _require(join not in _CONTROLLER_REQUEST_REGISTRY, "controller request join identity already exists")
        _CONTROLLER_REQUEST_REGISTRY[join] = {
            "join": join,
            "pid": os.getpid(),
            "status": "issued",
            "request_id": request_id,
            "request_nonce": nonce,
            "artifact_sha256": artifact_sha256,
        }
    join.assert_owner_sealed()
    return join


def _retire_controller_request_join(join: _ControllerRequestJoin) -> None:
    with _CONTROLLER_REQUEST_LOCK:
        record = _CONTROLLER_REQUEST_REGISTRY.get(join)
        if type(record) is dict and record.get("join") is join and record.get("pid") == os.getpid():
            record["status"] = "retired"
            del _CONTROLLER_REQUEST_REGISTRY[join]


def _artifact_frame(
    artifacts: SESSION.DirectServerSessionArtifacts,
    request_join: _ControllerRequestJoin,
) -> bytes:
    request_join.assert_owner_sealed()
    with _CONTROLLER_REQUEST_LOCK:
        record = _CONTROLLER_REQUEST_REGISTRY[request_join]
        _require(record["artifact_sha256"] == _artifact_hashes(artifacts), "controller request artifact bytes drifted")
    payload = canonical_bytes(
        {
            "protocol": PROTOCOL,
            "operation": "compose_and_submit_once",
            "request_nonce": record["request_nonce"],
            "request_id": request_join.request_id,
            "artifacts": {
                name: base64.b64encode(getattr(artifacts, name)).decode("ascii")
                for name in artifacts.__dataclass_fields__
            },
        }
    )
    _require(0 < len(payload) <= MAX_FRAME_BYTES, "controller artifact frame differs")
    return struct.pack("!I", len(payload)) + payload


def _read_framed_descriptor(descriptor: int, timeout_seconds: float) -> dict[str, Any]:
    _require(type(descriptor) is int and type(timeout_seconds) is float and timeout_seconds > 0, "frame reader differs")
    buffer = bytearray()
    required = 4
    deadline = time.monotonic() + timeout_seconds
    while len(buffer) < required:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControllerTransportUnknown("fixed controller response timed out")
        ready, _, _ = select.select([descriptor], [], [], remaining)
        if not ready:
            raise ControllerTransportUnknown("fixed controller response timed out")
        chunk = os.read(descriptor, min(65536, required - len(buffer)))
        if not chunk:
            raise ControllerTransportUnknown("fixed controller response ended early")
        buffer.extend(chunk)
        if required == 4 and len(buffer) == 4:
            size = struct.unpack("!I", buffer)[0]
            _require(0 < size <= MAX_FRAME_BYTES, "controller response size differs")
            required = 4 + size
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ControllerTransportUnknown("fixed controller response EOF timed out")
    ready, _, _ = select.select([descriptor], [], [], remaining)
    if not ready:
        raise ControllerTransportUnknown("fixed controller response EOF timed out")
    _require(os.read(descriptor, 1) == b"", "controller response contains extra bytes or a second frame")
    try:
        value = json.loads(bytes(buffer[4:]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerTransportUnknown("fixed controller response is malformed") from exc
    _require(type(value) is dict and canonical_bytes(value) == bytes(buffer[4:]), "controller response is not canonical")
    return value


def _write_all(descriptor: int, payload: bytes) -> None:
    _require(type(descriptor) is int and type(payload) is bytes and bool(payload), "fixed frame write differs")
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        _require(type(written) is int and written > 0, "fixed controller write made no progress")
        offset += written


def _write_controller_frame_until(descriptor: int, payload: bytes, deadline: float) -> None:
    """Write a controller frame through its dedicated nonblocking FD."""
    _require(
        type(descriptor) is int
        and type(payload) is bytes
        and bool(payload)
        and type(deadline) is float,
        "fixed controller frame write differs",
    )
    try:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        _require(
            bool(fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_NONBLOCK),
            "fixed controller request FD is not nonblocking",
        )
    except BaseException as exc:
        raise ControllerTransportUnknown("fixed controller request FD setup failed") from exc

    offset = 0
    while offset < len(payload):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControllerTransportUnknown("fixed controller request write timed out")
        try:
            _, writable, exceptional = select.select([], [descriptor], [descriptor], remaining)
        except InterruptedError:
            continue
        except (OSError, ValueError) as exc:
            raise ControllerTransportUnknown("fixed controller request write observation failed") from exc
        if exceptional:
            raise ControllerTransportUnknown("fixed controller request peer failed")
        if not writable:
            raise ControllerTransportUnknown("fixed controller request write timed out")
        try:
            written = os.write(descriptor, payload[offset:])
        except (BlockingIOError, InterruptedError):
            continue
        except OSError as exc:
            raise ControllerTransportUnknown("fixed controller request peer closed") from exc
        if type(written) is not int or written <= 0:
            raise ControllerTransportUnknown("fixed controller request write made no progress")
        offset += written


def _send_controller_request(descriptor: int, frame: bytes, deadline: float) -> None:
    """Once entered, any write or close failure is transport-uncertain."""
    try:
        _write_controller_frame_until(descriptor, frame, deadline)
        os.close(descriptor)
    except BaseException as exc:
        raise ControllerTransportUnknown("controller request may have been delivered") from exc


def _wait_child_bounded(pid: int, timeout_seconds: float) -> int:
    deadline = time.monotonic() + timeout_seconds
    while True:
        waited, status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return os.waitstatus_to_exitcode(status)
        _require(waited == 0, "fixed controller child identity differs")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControllerTransportUnknown("fixed controller child exit timed out")
        select.select([], [], [], min(0.01, remaining))


def _retire_controller_child_bounded(pid: int) -> bool:
    """Observe local SSH-child retirement without a signal or unbounded wait."""
    try:
        _wait_child_bounded(pid, CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS)
        return True
    except BaseException:
        return False


def _validate_controller_artifact_join(
    artifacts: SESSION.DirectServerSessionArtifacts,
) -> dict[str, Any]:
    _require(type(artifacts) is SESSION.DirectServerSessionArtifacts, "exact reviewed artifact bundle is required")
    profile = load_transport_profile(artifacts.transport_profile)
    try:
        direct_profile = SESSION.W1.validate_direct_execution_profile(
            json.loads(artifacts.profile.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectOneHopTransportError("direct profile artifact is not exact JSON") from exc
    try:
        system_policy_evidence = json.loads(artifacts.ssh_system_policy_evidence.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectOneHopTransportError("SSH configuration-file evidence is not exact JSON") from exc
    expected_system_policy_evidence = {
        "schema": "auto-g16-ssh-configuration-files-disabled-evidence/1",
        "ssh_executable_sha256": profile["ssh"]["executable_sha256"],
        "fixed_option": ["-F", "none"],
        "configuration_files_read": False,
        "global_known_hosts_file": "none",
        "user_known_hosts_file": profile["ssh"]["known_hosts_file"],
        "strict_host_key_checking": True,
        "known_hosts_command": "none",
        "verify_host_key_dns": False,
        "update_host_keys": False,
        "default_identity_files": "disabled_by_IdentityFile_none",
        "identity_agent": "none",
        "certificate_file": "none",
        "pkcs11_provider": "none",
        "security_key_provider": "none",
        "portable_evidence_authorizes_effect": False,
    }
    _require(
        direct_profile["transport_identity_binding_sha256"] == profile["profile_payload_sha256"]
        and direct_profile["declared_allowed_root"] == profile["server"]["allowed_root"]
        and system_policy_evidence == expected_system_policy_evidence
        and artifacts.ssh_system_policy_evidence == canonical_bytes(system_policy_evidence)
        and hashlib.sha256(artifacts.ssh_system_policy_evidence).hexdigest()
        == profile["ssh"]["system_policy_evidence_sha256"],
        "controller direct profile, transport identity, root, or system-policy evidence differs",
    )
    return profile


def _expected_controller_receipt_fields(
    artifacts: SESSION.DirectServerSessionArtifacts,
    profile: dict[str, Any],
) -> dict[str, str]:
    try:
        authorization_source = json.loads(artifacts.authorization.decode("utf-8"))
        direct_profile_source = json.loads(artifacts.profile.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectOneHopTransportError("controller profile or authorization artifact is not exact JSON") from exc
    authorization = SESSION.W1.validate_direct_execution_authorization(authorization_source)
    direct_profile = SESSION.W1.validate_direct_execution_profile(direct_profile_source)
    _require(
        artifacts.authorization == SESSION.W1.canonical_bytes(authorization)
        and artifacts.profile == SESSION.W1.canonical_bytes(direct_profile)
        and authorization["profile"]["profile_payload_sha256"] == direct_profile["profile_payload_sha256"]
        and direct_profile["transport_identity_binding_sha256"] == profile["profile_payload_sha256"]
        and authorization["workspace"]["allowed_root"] == profile["server"]["allowed_root"]
        and hashlib.sha256(artifacts.input_bytes).hexdigest() == authorization["input"]["sha256"]
        and str(len(artifacts.input_bytes)) == authorization["input"]["size_bytes"],
        "controller authorization, root, or immutable input join differs",
    )
    return {
        "transport_profile_payload_sha256": profile["profile_payload_sha256"],
        "attempt_id": authorization["scope"]["attempt_id"],
        "project": authorization["workspace"]["project"],
        "input_sha256": authorization["input"]["sha256"],
        "authorization_payload_sha256": authorization["authorization_payload_sha256"],
    }


def _build_controller_completed_response(
    request_id: str,
    readiness_document: dict[str, Any],
    receipt_document: dict[str, Any],
) -> dict[str, Any]:
    _require(
        type(request_id) is str and CONTROLLER_REQUEST_ID_RE.fullmatch(request_id) is not None,
        "controller request identity differs",
    )
    readiness = SESSION.validate_trusted_session_result(readiness_document)
    receipt = validate_submission_receipt(receipt_document)
    _require(
        readiness["status"] == "ready_for_w5"
        and readiness["durable_terminal_outcome"] == "none"
        and readiness["authority"]["authorizes_effect"] is False
        and receipt["binding_payload_sha256"] == readiness["binding_payload_sha256"]
        and receipt["journal_id"] == readiness["journal_id"],
        "server owner session/result join differs",
    )
    response = {
        "protocol": PROTOCOL,
        "status": "completed",
        "request_id": request_id,
        "server_session_join": readiness,
        "receipt": receipt,
        "response_payload_sha256": "",
    }
    response["response_payload_sha256"] = digest(response)
    return response


def _validate_controller_response(
    response_document: Any,
    artifacts: SESSION.DirectServerSessionArtifacts,
    profile: dict[str, Any],
    request_join: _ControllerRequestJoin,
) -> dict[str, Any]:
    request_join.assert_owner_sealed()
    response = _exact(
        copy.deepcopy(response_document),
        {
            "protocol", "status", "request_id", "server_session_join",
            "receipt", "response_payload_sha256",
        },
        "fixed controller response",
    )
    _require(
        response["protocol"] == PROTOCOL
        and response["status"] == "completed"
        and response["request_id"] == request_join.request_id
        and response["response_payload_sha256"]
        == digest({**response, "response_payload_sha256": ""}),
        "fixed controller request/result commitment differs",
    )
    readiness = SESSION.validate_trusted_session_result(response["server_session_join"])
    receipt = validate_submission_receipt(response["receipt"])
    expected = _expected_controller_receipt_fields(artifacts, profile)
    _require(
        readiness["status"] == "ready_for_w5"
        and readiness["durable_terminal_outcome"] == "none"
        and readiness["authority"]["authorizes_effect"] is False
        and receipt["binding_payload_sha256"] == readiness["binding_payload_sha256"]
        and receipt["journal_id"] == readiness["journal_id"]
        and all(receipt[field] == value for field, value in expected.items())
        and receipt["authority"]["authorizes_effect"] is False
        and receipt["qsub"]["calls"] == "1",
        "fixed controller receipt is stale, foreign, or unbound",
    )
    return copy.deepcopy(receipt)


def _decode_controller_request(
    request_document: Any,
) -> tuple[SESSION.DirectServerSessionArtifacts, str]:
    request = _exact(
        copy.deepcopy(request_document),
        {"protocol", "operation", "request_nonce", "request_id", "artifacts"},
        "server subsystem request",
    )
    _require(
        request["protocol"] == PROTOCOL
        and request["operation"] == "compose_and_submit_once"
        and type(request["request_nonce"]) is str
        and SHA_RE.fullmatch(request["request_nonce"]) is not None
        and type(request["request_id"]) is str
        and CONTROLLER_REQUEST_ID_RE.fullmatch(request["request_id"]) is not None
        and type(request["artifacts"]) is dict
        and set(request["artifacts"]) == set(SESSION.DirectServerSessionArtifacts.__dataclass_fields__),
        "server subsystem request differs",
    )
    try:
        decoded = {
            name: base64.b64decode(request["artifacts"][name], validate=True)
            for name in SESSION.DirectServerSessionArtifacts.__dataclass_fields__
        }
    except (TypeError, ValueError, binascii.Error) as exc:
        raise DirectOneHopTransportError("server subsystem artifacts are not exact base64") from exc
    artifacts = SESSION.DirectServerSessionArtifacts(**decoded)
    _require(
        request["request_id"]
        == _controller_request_id(request["request_nonce"], _artifact_hashes(artifacts)),
        "server subsystem request commitment differs",
    )
    return artifacts, request["request_id"]


def run_controller_once(artifacts: SESSION.DirectServerSessionArtifacts) -> dict[str, Any]:
    """Execute one fixed SSH-subsystem framed lifecycle; no retry or override."""
    _assert_production_binding()
    _require(type(artifacts) is SESSION.DirectServerSessionArtifacts, "exact reviewed artifact bundle is required")
    profile = _validate_controller_artifact_join(artifacts)
    _require_descriptor_exec_available()
    argv = build_controller_argv(artifacts.transport_profile)
    ssh_fd = _open_reviewed_executable(SSH_EXECUTABLE, profile["ssh"]["executable_sha256"])
    read_in, write_in = _pipe_cloexec()
    read_out, write_out = _pipe_cloexec()
    try:
        request_join = _issue_controller_request_join(artifacts)
    except BaseException:
        _close_quiet(read_in, write_in, read_out, write_out, ssh_fd)
        raise
    try:
        pid = _FROZEN_FORK()
    except BaseException:
        _close_quiet(read_in, write_in, read_out, write_out, ssh_fd)
        _retire_controller_request_join(request_join)
        raise
    if pid == 0:  # pragma: no cover - real controller only
        try:
            os.dup2(read_in, 0)
            os.dup2(write_out, 1)
            _assert_reviewed_executable_descriptor(ssh_fd, SSH_EXECUTABLE, profile["ssh"]["executable_sha256"])
            for descriptor in (read_in, write_in, read_out, write_out):
                if descriptor > 2:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
            _descriptor_execve(ssh_fd, argv, FIXED_ENVIRONMENT)
        except BaseException:
            os._exit(127)
    _close_quiet(read_in, write_out, ssh_fd)
    effect_possible = False
    child_reaped = False
    child_wait_attempted = False
    try:
        frame = _artifact_frame(artifacts, request_join)
        effect_possible = True
        write_deadline = time.monotonic() + CONTROLLER_WRITE_TIMEOUT_SECONDS
        _send_controller_request(write_in, frame, write_deadline)
        write_in = -1
        response = _read_framed_descriptor(read_out, 30.0)
        child_wait_attempted = True
        child_exit = _wait_child_bounded(pid, CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS)
        child_reaped = True
        _require(child_exit == 0, "fixed controller child exit is uncertain")
        return _validate_controller_response(response, artifacts, profile, request_join)
    except BaseException as exc:
        if effect_possible:
            raise ControllerTransportUnknown("remote effect may have occurred; reconciliation only") from exc
        raise
    finally:
        _retire_controller_request_join(request_join)
        for descriptor in (write_in, read_out):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if not child_reaped and not child_wait_attempted:
            _retire_controller_child_bounded(pid)


def server_subsystem_once() -> int:
    """Fixed SSH subsystem endpoint; stdin/stdout carry exactly one frame."""
    _assert_production_binding()
    try:
        artifacts, request_id = _decode_controller_request(_read_framed_descriptor(0, 30.0))
        profile = load_transport_profile(artifacts.transport_profile)
        python_fd = _open_reviewed_executable(
            profile["server"]["python_executable"],
            profile["server"]["python_executable_sha256"],
        )
        os.close(python_fd)
        child = SESSION.compose_production_in_fixed_clean_exec_once(artifacts)
        readiness = child.readiness()
        child.transition_to_w5_once()
        receipt = child.submit_once()
        payload = canonical_bytes(_build_controller_completed_response(request_id, readiness, receipt))
        frame = struct.pack("!I", len(payload)) + payload
        _write_all(1, frame)
        return 0
    except BaseException:
        return 3


def _validate_pbs_review(
    raw: bytes,
    script: bytes,
    binding: dict[str, Any],
    profile: dict[str, Any],
    allowed_root: str,
) -> dict[str, Any]:
    _require(type(raw) is bytes and bool(raw) and type(script) is bytes and bool(script), "reviewed PBS bytes differ")
    try:
        review = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectOneHopTransportError("PBS review is not exact JSON") from exc
    review = _exact(
        review,
        {"schema", "review_id", "script", "workspace", "input", "resources", "gaussian", "safety", "review_payload_sha256"},
        "PBS review",
    )
    _require(review["schema"] == PBS_REVIEW_SCHEMA, "PBS review schema differs")
    _text(review["review_id"], "PBS review id")
    script_ref = _exact(review["script"], {"basename", "sha256", "size_bytes"}, "PBS review script")
    _require(
        script_ref == {
            "basename": PBS_BASENAME,
            "sha256": hashlib.sha256(script).hexdigest(),
            "size_bytes": str(len(script)),
        }
        and script_ref == {
            "basename": profile["pbs_artifact"]["basename"],
            "sha256": profile["pbs_artifact"]["sha256"],
            "size_bytes": profile["pbs_artifact"]["size_bytes"],
        },
        "reviewed PBS script bytes differ",
    )
    _require(
        review["workspace"] == {
            "allowed_root": allowed_root,
            "project": binding["workspace"]["project"],
            "working_directory_check": "pbs_o_workdir_equals_submission_directory",
            "scratch_policy": "project_relative_scratch",
            "scratch_basename": "scratch",
        },
        "reviewed PBS workdir or scratch identity differs",
    )
    _require(
        review["input"] == {
            "source_sha256": binding["input"]["sha256"],
            "uploaded_basename": INPUT_BASENAME,
            "route_bytes_unchanged": True,
        }
        and review["resources"] == {
            "tier": binding["resources"]["tier"],
            "cores": str(int(binding["resources"]["cores"])),
            "memory_gb": str(int(binding["resources"]["memory_gb"])),
            "walltime_seconds": str(int(binding["resources"]["walltime_seconds"])),
        }
        and review["gaussian"] == {
            "executable": "g16",
            "invocation": "filename_argument",
            "input_basename": INPUT_BASENAME,
            "scientific_route_owned_by_input": True,
        }
        and review["safety"] == {
            "set_eu": True,
            "allowed_root_checked": True,
            "project_workdir_checked": True,
            "scratch_identity_checked": True,
            "nested_ssh": False,
            "legacy_transport_called": False,
        },
        "reviewed PBS execution semantics differ",
    )
    supplied = _sha(review["review_payload_sha256"], "PBS review")
    _require(supplied == profile["pbs_artifact"]["review_payload_sha256"], "PBS review binding differs")
    check = copy.deepcopy(review)
    check["review_payload_sha256"] = ""
    _require(supplied == digest(check) and raw == canonical_bytes(review), "PBS review bytes or self-hash differ")
    return copy.deepcopy(review)


def _checksums(files: dict[str, bytes]) -> bytes:
    _require(tuple(sorted(files)) == tuple(sorted((INPUT_BASENAME, PBS_BASENAME))), "checksum inputs differ")
    return b"".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n".encode("ascii")
        for name in sorted(files)
    )


def _fd_identity(descriptor: int) -> tuple[int, ...]:
    info = os.fstat(descriptor)
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def _write_new_file(project_fd: int, basename: str, payload: bytes) -> None:
    _require(basename in ALLOWLIST and type(payload) is bytes and bool(payload), "upload file differs")
    before = _fd_identity(project_fd)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(basename, flags, 0o600, dir_fd=project_fd)
    try:
        _require(stat.S_ISREG(os.fstat(descriptor).st_mode), "upload target is not regular")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            _require(type(written) is int and written > 0, "immutable upload made no progress")
            offset += written
        _require(offset == len(payload), "immutable upload length differs")
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = bytearray()
        while len(observed) < len(payload) + 1:
            chunk = os.read(descriptor, min(65536, len(payload) + 1 - len(observed)))
            if not chunk:
                break
            observed.extend(chunk)
        _require(bytes(observed) == payload, "immutable upload bytes drifted")
        opened = os.fstat(descriptor)
        named = os.stat(basename, dir_fd=project_fd, follow_symlinks=False)
        _require(
            stat.S_ISREG(named.st_mode)
            and _executable_identity(opened) == _executable_identity(named)
            and named.st_size == len(payload),
            "uploaded file identity differs",
        )
    finally:
        os.close(descriptor)
    _require(_fd_identity(project_fd) == before, "project FD identity drifted")
    os.fsync(project_fd)


@dataclass(frozen=True, slots=True)
class _EffectObservation:
    qsub_calls: int
    stdout: bytes
    stderr: bytes
    returncode: int | None
    uncertain: bool


_TEST_DRIVER_TOKEN = object()


class _DeterministicTestDriver:
    __slots__ = ("_observation", "_calls", "_raise_inside", "_seal", "_lock")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("test drivers use the private factory")

    def invoke_once(self, project_fd: int) -> _EffectObservation:
        _require(self._seal is _TEST_DRIVER_TOKEN and type(project_fd) is int, "test driver differs")
        with self._lock:
            _require(self._calls == 0, "second qsub forbidden")
            self._calls = 1
        if self._raise_inside:
            raise RuntimeError("deterministic invoke-inside failure")
        return self._observation

    @property
    def calls(self) -> int:
        return self._calls


def _test_driver(*, stdout: bytes, stderr: bytes = b"", returncode: int | None = 0, uncertain: bool = False, raise_inside: bool = False) -> _DeterministicTestDriver:
    _require(type(stdout) is bytes and type(stderr) is bytes and type(uncertain) is bool and type(raise_inside) is bool, "test observation differs")
    value = object.__new__(_DeterministicTestDriver)
    value._observation = _EffectObservation(1, stdout, stderr, returncode, uncertain)
    value._calls = 0
    value._raise_inside = raise_inside
    value._seal = _TEST_DRIVER_TOKEN
    value._lock = threading.Lock()
    return value


def _production_qsub_once(project_fd: int, expected_executable_sha256: str) -> _EffectObservation:
    """Invoke the fixed qsub program once; never retries and never uses a shell."""
    _require(type(project_fd) is int and stat.S_ISDIR(os.fstat(project_fd).st_mode), "project FD differs")
    _require_descriptor_exec_available()
    qsub_fd = _open_reviewed_executable(QSUB_EXECUTABLE, expected_executable_sha256)
    read_out, write_out = _pipe_cloexec()
    read_err, write_err = _pipe_cloexec()
    try:
        pid = _FROZEN_FORK()
    except BaseException:
        _close_quiet(read_out, write_out, read_err, write_err, qsub_fd)
        raise
    if pid == 0:  # pragma: no cover - live production only
        try:
            os.fchdir(project_fd)
            _assert_reviewed_executable_descriptor(qsub_fd, QSUB_EXECUTABLE, expected_executable_sha256)
            os.dup2(write_out, 1)
            os.dup2(write_err, 2)
            for descriptor in (read_out, read_err, write_out, write_err, project_fd):
                if descriptor > 2:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
            _descriptor_execve(qsub_fd, QSUB_ARGV, FIXED_ENVIRONMENT)
        except BaseException:
            os._exit(127)
    _close_quiet(write_out, write_err, qsub_fd)
    chunks: dict[int, bytearray] = {read_out: bytearray(), read_err: bytearray()}
    stdout = chunks[read_out]
    stderr = chunks[read_err]
    uncertain = False
    deadline = time.monotonic() + 30.0
    try:
        while chunks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                uncertain = True
                break
            ready, _, _ = select.select(list(chunks), [], [], remaining)
            if not ready:
                uncertain = True
                break
            for descriptor in ready:
                data = os.read(descriptor, 4096)
                if not data:
                    os.close(descriptor)
                    del chunks[descriptor]
                else:
                    chunks[descriptor].extend(data)
                    if len(chunks[descriptor]) > MAX_STDOUT_BYTES:
                        uncertain = True
                        break
            if uncertain:
                break
        waited, status = os.waitpid(pid, os.WNOHANG)
        while waited == 0 and not uncertain:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                uncertain = True
                break
            select.select([], [], [], min(0.01, remaining))
            waited, status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            returncode = os.waitstatus_to_exitcode(status)
        else:
            _require(waited == 0, "qsub wait identity differs")
            uncertain = True
            returncode = None
    except BaseException:
        uncertain = True
        try:
            waited, status = os.waitpid(pid, os.WNOHANG)
            returncode = os.waitstatus_to_exitcode(status) if waited == pid else None
        except BaseException:
            returncode = None
    finally:
        for descriptor in tuple(chunks):
            try:
                os.close(descriptor)
            except OSError:
                pass
    return _EffectObservation(1, bytes(stdout), bytes(stderr), returncode, uncertain)


def _job_id(stdout: bytes, stderr: bytes, returncode: int | None, uncertain: bool) -> str:
    _require(not uncertain, "qsub outcome is transport-uncertain")
    _require(returncode == 0 and stderr == b"", "qsub exit or stderr is ambiguous")
    _require(0 < len(stdout) <= MAX_STDOUT_BYTES, "qsub stdout size differs")
    try:
        text = stdout.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DirectOneHopTransportError("qsub stdout is not ASCII") from exc
    match = JOB_ID_RE.fullmatch(text)
    _require(match is not None, "qsub stdout is not one exact PBS job ID")
    return text[:-1]


_RECEIPT_TOKEN = object()
_RECEIPT_LOCK = threading.RLock()
_RECEIPT_REGISTRY: dict[object, dict[str, Any]] = {}


class ExactSubmissionReceipt:
    """Owner-issued immutable in-process identity; its projection grants nothing."""

    __slots__ = ("receipt_id", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("submission receipts are owner-issued only")

    def assert_owner_sealed(self) -> None:
        with _RECEIPT_LOCK:
            record = _RECEIPT_REGISTRY.get(self)
            _require(
                type(self) is ExactSubmissionReceipt
                and self._seal is _RECEIPT_TOKEN
                and type(record) is dict
                and record.get("receipt") is self
                and record.get("pid") == os.getpid()
                and record.get("document", {}).get("receipt_id") == self.receipt_id,
                "submission receipt is foreign, forked, or reconstructed",
            )

    def portable_projection(self) -> dict[str, Any]:
        self.assert_owner_sealed()
        with _RECEIPT_LOCK:
            return copy.deepcopy(_RECEIPT_REGISTRY[self]["document"])

    def __copy__(self) -> Any:
        raise TypeError("submission receipts are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("submission receipts are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("submission receipts are not serializable")


def _issue_receipt(
    binding: dict[str, Any],
    profile: dict[str, Any],
    journal_id: str,
    job_id: str,
    files: dict[str, bytes],
) -> ExactSubmissionReceipt:
    invocation = {
        "executable": QSUB_EXECUTABLE,
        "argv": list(QSUB_ARGV),
        "working_directory": "already_open_project_fd",
        "call_count": "1",
    }
    invocation["invocation_payload_sha256"] = digest(invocation)
    outcome = {
        "classification": "exact_job_id_accepted",
        "returncode": "0",
        "stderr_empty": True,
        "raw_stdout_retained": False,
        "job_id": job_id,
    }
    outcome["outcome_payload_sha256"] = digest(outcome)
    document = {
        "schema": RESULT_SCHEMA,
        "protocol": PROTOCOL,
        "backend_kind": BACKEND_KIND,
        "topology": TOPOLOGY,
        "scheduler_dialect": SCHEDULER_DIALECT,
        "transport_profile_payload_sha256": profile["profile_payload_sha256"],
        "binding_payload_sha256": binding["binding_payload_sha256"],
        "journal_id": journal_id,
        "attempt_id": binding["scope"]["attempt_id"],
        "project": binding["workspace"]["project"],
        "input_sha256": binding["input"]["sha256"],
        "authorization_payload_sha256": binding["authorization"]["authorization_payload_sha256"],
        "uploaded": [
            {"basename": name, "sha256": hashlib.sha256(files[name]).hexdigest(), "size_bytes": str(len(files[name]))}
            for name in (INPUT_BASENAME, PBS_BASENAME, CHECKSUMS_BASENAME)
        ],
        "qsub": {
            "calls": "1",
            "job_id": job_id,
            "raw_stdout_included": False,
            "invocation_payload_sha256": invocation["invocation_payload_sha256"],
            "outcome_payload_sha256": outcome["outcome_payload_sha256"],
        },
        "invocation": invocation,
        "outcome": outcome,
        "durable_outcome": "completed",
        "authority": {
            "authorizes_effect": False,
            "portable_result_is_authority": False,
            "automatic_retry": False,
            "second_qsub": False,
            "qdel": False,
            "delete": False,
        },
        "receipt_id": "",
        "result_payload_sha256": "",
    }
    document["receipt_id"] = "direct-submission-receipt-" + digest(
        {key: value for key, value in document.items() if key not in {"receipt_id", "result_payload_sha256"}}
    )
    document["result_payload_sha256"] = digest(document)
    document = validate_submission_receipt(document)
    receipt = object.__new__(ExactSubmissionReceipt)
    receipt.receipt_id = document["receipt_id"]
    receipt._seal = _RECEIPT_TOKEN
    with _RECEIPT_LOCK:
        _require(receipt not in _RECEIPT_REGISTRY, "submission receipt identity already exists")
        _RECEIPT_REGISTRY[receipt] = {
            "receipt": receipt,
            "pid": os.getpid(),
            "document": copy.deepcopy(document),
        }
    receipt.assert_owner_sealed()
    return receipt


def validate_submission_receipt(document: Any) -> dict[str, Any]:
    value = _exact(
        copy.deepcopy(document),
        {
            "schema", "protocol", "backend_kind", "topology", "scheduler_dialect",
            "transport_profile_payload_sha256", "binding_payload_sha256", "journal_id",
            "attempt_id", "project", "input_sha256", "authorization_payload_sha256",
            "uploaded", "qsub", "invocation", "outcome", "durable_outcome", "authority",
            "receipt_id", "result_payload_sha256",
        },
        "submission receipt",
    )
    _require(
        value["schema"] == RESULT_SCHEMA
        and value["protocol"] == PROTOCOL
        and value["backend_kind"] == BACKEND_KIND
        and value["topology"] == TOPOLOGY
        and value["scheduler_dialect"] == SCHEDULER_DIALECT
        and value["durable_outcome"] == "completed",
        "submission receipt fixed identity differs",
    )
    for field in (
        "transport_profile_payload_sha256", "binding_payload_sha256", "input_sha256",
        "authorization_payload_sha256", "result_payload_sha256",
    ):
        _sha(value[field], f"submission receipt {field}")
    _require(
        type(value["journal_id"]) is str and JOURNAL_ID_RE.fullmatch(value["journal_id"]) is not None
        and type(value["attempt_id"]) is str and ATTEMPT_ID_RE.fullmatch(value["attempt_id"]) is not None
        and type(value["receipt_id"]) is str and RECEIPT_ID_RE.fullmatch(value["receipt_id"]) is not None
        and type(value["project"]) is str and bool(value["project"]),
        "submission receipt identifiers differ",
    )
    _require(
        type(value["uploaded"]) is list
        and [item.get("basename") for item in value["uploaded"]]
        == [INPUT_BASENAME, PBS_BASENAME, CHECKSUMS_BASENAME]
        and all(
            type(item) is dict
            and set(item) == {"basename", "sha256", "size_bytes"}
            and SHA_RE.fullmatch(item["sha256"]) is not None
            and bool(_positive_decimal(item["size_bytes"], "submission receipt upload size"))
            for item in value["uploaded"]
        ),
        "submission receipt upload inventory differs",
    )
    invocation = _exact(value["invocation"], {"executable", "argv", "working_directory", "call_count", "invocation_payload_sha256"}, "submission invocation")
    invocation_hash = invocation["invocation_payload_sha256"]
    _require(
        invocation["executable"] == QSUB_EXECUTABLE
        and invocation["argv"] == list(QSUB_ARGV)
        and invocation["working_directory"] == "already_open_project_fd"
        and invocation["call_count"] == "1"
        and invocation_hash == digest({key: item for key, item in invocation.items() if key != "invocation_payload_sha256"}),
        "submission invocation differs",
    )
    outcome = _exact(value["outcome"], {"classification", "returncode", "stderr_empty", "raw_stdout_retained", "job_id", "outcome_payload_sha256"}, "submission outcome")
    outcome_hash = outcome["outcome_payload_sha256"]
    _require(
        outcome["classification"] == "exact_job_id_accepted"
        and outcome["returncode"] == "0"
        and outcome["stderr_empty"] is True
        and outcome["raw_stdout_retained"] is False
        and JOB_ID_RE.fullmatch(outcome["job_id"] + "\n") is not None
        and outcome_hash == digest({key: item for key, item in outcome.items() if key != "outcome_payload_sha256"}),
        "submission outcome differs",
    )
    _require(
        value["qsub"] == {
            "calls": "1",
            "job_id": outcome["job_id"],
            "raw_stdout_included": False,
            "invocation_payload_sha256": invocation_hash,
            "outcome_payload_sha256": outcome_hash,
        }
        and value["authority"] == {
            "authorizes_effect": False,
            "portable_result_is_authority": False,
            "automatic_retry": False,
            "second_qsub": False,
            "qdel": False,
            "delete": False,
        },
        "submission receipt authority differs",
    )
    expected_receipt_id = "direct-submission-receipt-" + digest(
        {key: item for key, item in value.items() if key not in {"receipt_id", "result_payload_sha256"}}
    )
    _require(value["receipt_id"] == expected_receipt_id, "submission receipt id derivation differs")
    _require(value["result_payload_sha256"] == digest({**value, "result_payload_sha256": ""}), "submission receipt hash differs")
    return value


def _record_unknown(claim: W2.DurableEffectClaim, evidence: str) -> None:
    try:
        W2.record_outcome_once(
            claim,
            outcome="unknown",
            evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        )
    except BaseException:
        pass


def _consume_once(seam: SESSION.TrustedW5OperationSeam, driver: _DeterministicTestDriver | None) -> ExactSubmissionReceipt:
    seam.assert_owner_sealed()
    claim = seam.durable_claim
    project: W4.ConsumedDirectProjectSession | None = None
    effect_possible = False
    try:
        project = seam.project_session
        project.assert_owner_sealed()
        binding_object = seam.direct_binding
        binding = binding_object.document()
        profile = load_transport_profile(seam.transport_profile_bytes)
        _require(
            profile["profile_payload_sha256"] == seam.transport_binding_sha256
            and profile["server"]["allowed_root"] == seam.allowed_root,
            "transport profile is not the exact backend-owned binding",
        )
        _require(
            profile["server"]["entrypoint_source_sha256"] == _EXECUTED_SOURCE_SHA256,
            "reviewed server entrypoint source differs",
        )
        _require(
            profile["server"]["python_executable"] == str(SESSION._FIXED_EXECUTABLE.path)
            and profile["server"]["python_executable_sha256"] == SESSION._FIXED_EXECUTABLE.sha256,
            "reviewed server Python executable identity differs",
        )
        input_bytes = seam.input_bytes
        _require(
            hashlib.sha256(input_bytes).hexdigest() == binding["input"]["sha256"]
            and len(input_bytes) == int(binding["input"]["size_bytes"]),
            "approved input bytes drifted",
        )
        pbs_script = seam.pbs_script_bytes
        _validate_pbs_review(seam.pbs_review_bytes, pbs_script, binding, profile, seam.allowed_root)
        files = {INPUT_BASENAME: input_bytes, PBS_BASENAME: pbs_script}
        files[CHECKSUMS_BASENAME] = _checksums(files)
        project_fd = project._project_descriptor
        for name in (INPUT_BASENAME, PBS_BASENAME, CHECKSUMS_BASENAME):
            _write_new_file(project_fd, name, files[name])
        effect_possible = True
        observation = driver.invoke_once(project_fd) if driver is not None else _production_qsub_once(
            project_fd,
            profile["qsub"]["executable_sha256"],
        )
        _require(observation.qsub_calls == 1, "qsub call count differs")
        job_id = _job_id(observation.stdout, observation.stderr, observation.returncode, observation.uncertain)
        receipt = _issue_receipt(binding, profile, claim.journal_id, job_id, files)
        projection = receipt.portable_projection()
        receipt_raw = canonical_bytes(projection)
        _write_new_file(project_fd, SUBMISSION_RECEIPT_BASENAME, receipt_raw)
        W2.record_outcome_once(claim, outcome="completed", evidence_sha256=projection["result_payload_sha256"])
        project.close_once()
        return receipt
    except BaseException as exc:
        _record_unknown(claim, "effect-possible-submission-unknown" if effect_possible else "pre-qsub-effect-chain-failed")
        try:
            if project is not None:
                project.close_once()
        except BaseException:
            pass
        if effect_possible:
            raise SubmissionOutcomeUnknown("qsub may have occurred; reconciliation only") from exc
        raise


def consume_production_once(seam: SESSION.TrustedW5OperationSeam) -> ExactSubmissionReceipt:
    """The sole real W5 server-side consumer; no caller-provided effect seam."""
    _assert_production_binding()
    _require(type(seam) is SESSION.TrustedW5OperationSeam, "exact W4B W5 seam is required")
    return _consume_once(seam, None)


def _consume_with_test_driver_once(
    seam: SESSION.TrustedW5OperationSeam,
    driver: _DeterministicTestDriver,
    *,
    _test_token: object,
) -> ExactSubmissionReceipt:
    _require(
        _test_token is _TEST_DRIVER_TOKEN
        and type(seam) is SESSION.TrustedW5OperationSeam
        and type(driver) is _DeterministicTestDriver
        and driver._seal is _TEST_DRIVER_TOKEN,
        "offline test seam differs",
    )
    return _consume_once(seam, driver)


_FROZEN_FORK = os.fork
_FROZEN_EXECVE = os.execve
_FROZEN_URANDOM = os.urandom
_FROZEN_PRODUCTION_QSUB = _production_qsub_once
_FROZEN_CONSUME = _consume_once
_FROZEN_WRITE_NEW_FILE = _write_new_file
_FROZEN_JOB_ID = _job_id
_FROZEN_CONTROLLER_ARGV = build_controller_argv
_FROZEN_ARTIFACT_FRAME = _artifact_frame
_FROZEN_FRAME_READER = _read_framed_descriptor
_FROZEN_CONTROLLER_FRAME_WRITER = _write_controller_frame_until
_FROZEN_CONTROLLER_SENDER = _send_controller_request
_FROZEN_CHILD_WAITER = _wait_child_bounded
_FROZEN_CONTROLLER_CHILD_RETIRER = _retire_controller_child_bounded
_FROZEN_PROFILE_LOADER = load_transport_profile
_FROZEN_PBS_REVIEW = _validate_pbs_review
_FROZEN_RECEIPT_ISSUER = _issue_receipt
_FROZEN_RECORD_UNKNOWN = _record_unknown
_FROZEN_PROFILE_VALIDATOR = validate_transport_profile
_FROZEN_RECEIPT_VALIDATOR = validate_submission_receipt
_FROZEN_CONTROLLER_JOIN = _validate_controller_artifact_join
_FROZEN_ARTIFACT_HASHES = _artifact_hashes
_FROZEN_CONTROLLER_REQUEST_ID = _controller_request_id
_FROZEN_CONTROLLER_REQUEST_ISSUER = _issue_controller_request_join
_FROZEN_CONTROLLER_REQUEST_RETIRER = _retire_controller_request_join
_FROZEN_CONTROLLER_REQUEST_DECODER = _decode_controller_request
_FROZEN_EXPECTED_CONTROLLER_RECEIPT = _expected_controller_receipt_fields
_FROZEN_CONTROLLER_RESPONSE_BUILDER = _build_controller_completed_response
_FROZEN_CONTROLLER_RESPONSE_VALIDATOR = _validate_controller_response
_FROZEN_CONTROLLER_REQUEST_TYPE = _ControllerRequestJoin
_FROZEN_BASE64_DECODER = base64.b64decode
_FROZEN_SESSION_RESULT_VALIDATOR = SESSION.validate_trusted_session_result
_FROZEN_W1_PROFILE_VALIDATOR = SESSION.W1.validate_direct_execution_profile
_FROZEN_W1_AUTHORIZATION_VALIDATOR = SESSION.W1.validate_direct_execution_authorization
_FROZEN_W1_CANONICAL_BYTES = SESSION.W1.canonical_bytes
_FROZEN_EXECUTABLE_OPENER = _open_reviewed_executable
_FROZEN_DESCRIPTOR_EXEC = _descriptor_execve
_FROZEN_SESSION_CONSUMER = SESSION.consume_w5_operation_seam_once
_CANONICAL_SESSION_MODULE = SESSION
_CANONICAL_W2_MODULE = W2
_CANONICAL_W4_MODULE = W4
_FROZEN_SSH_FIXED_OPTIONS = SSH_FIXED_OPTIONS
_FROZEN_CONTROLLER_WRITE_TIMEOUT_SECONDS = CONTROLLER_WRITE_TIMEOUT_SECONDS
_FROZEN_CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS = CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS
_FROZEN_ENVIRONMENT = copy.deepcopy(FIXED_ENVIRONMENT)
_FROZEN_POLICY = copy.deepcopy(POLICY)


def _assert_production_binding() -> None:
    with open(__file__, "rb") as source:
        source_sha256 = hashlib.sha256(source.read()).hexdigest()
    _require(
        source_sha256 == _EXECUTED_SOURCE_SHA256
        and os.fork is _FROZEN_FORK
        and os.execve is _FROZEN_EXECVE
        and os.urandom is _FROZEN_URANDOM
        and _production_qsub_once is _FROZEN_PRODUCTION_QSUB
        and _consume_once is _FROZEN_CONSUME
        and _write_new_file is _FROZEN_WRITE_NEW_FILE
        and _job_id is _FROZEN_JOB_ID
        and build_controller_argv is _FROZEN_CONTROLLER_ARGV
        and _artifact_frame is _FROZEN_ARTIFACT_FRAME
        and _read_framed_descriptor is _FROZEN_FRAME_READER
        and _write_controller_frame_until is _FROZEN_CONTROLLER_FRAME_WRITER
        and _send_controller_request is _FROZEN_CONTROLLER_SENDER
        and _wait_child_bounded is _FROZEN_CHILD_WAITER
        and _retire_controller_child_bounded is _FROZEN_CONTROLLER_CHILD_RETIRER
        and load_transport_profile is _FROZEN_PROFILE_LOADER
        and _validate_pbs_review is _FROZEN_PBS_REVIEW
        and _issue_receipt is _FROZEN_RECEIPT_ISSUER
        and _record_unknown is _FROZEN_RECORD_UNKNOWN
        and validate_transport_profile is _FROZEN_PROFILE_VALIDATOR
        and validate_submission_receipt is _FROZEN_RECEIPT_VALIDATOR
        and _validate_controller_artifact_join is _FROZEN_CONTROLLER_JOIN
        and _artifact_hashes is _FROZEN_ARTIFACT_HASHES
        and _controller_request_id is _FROZEN_CONTROLLER_REQUEST_ID
        and _issue_controller_request_join is _FROZEN_CONTROLLER_REQUEST_ISSUER
        and _retire_controller_request_join is _FROZEN_CONTROLLER_REQUEST_RETIRER
        and _decode_controller_request is _FROZEN_CONTROLLER_REQUEST_DECODER
        and _expected_controller_receipt_fields is _FROZEN_EXPECTED_CONTROLLER_RECEIPT
        and _build_controller_completed_response is _FROZEN_CONTROLLER_RESPONSE_BUILDER
        and _validate_controller_response is _FROZEN_CONTROLLER_RESPONSE_VALIDATOR
        and _ControllerRequestJoin is _FROZEN_CONTROLLER_REQUEST_TYPE
        and base64.b64decode is _FROZEN_BASE64_DECODER
        and SESSION.validate_trusted_session_result is _FROZEN_SESSION_RESULT_VALIDATOR
        and SESSION.W1.validate_direct_execution_profile is _FROZEN_W1_PROFILE_VALIDATOR
        and SESSION.W1.validate_direct_execution_authorization is _FROZEN_W1_AUTHORIZATION_VALIDATOR
        and SESSION.W1.canonical_bytes is _FROZEN_W1_CANONICAL_BYTES
        and _open_reviewed_executable is _FROZEN_EXECUTABLE_OPENER
        and _descriptor_execve is _FROZEN_DESCRIPTOR_EXEC
        and SESSION is _CANONICAL_SESSION_MODULE
        and W2 is _CANONICAL_W2_MODULE
        and W4 is _CANONICAL_W4_MODULE
        and SESSION.consume_w5_operation_seam_once is _FROZEN_SESSION_CONSUMER
        and SSH_FIXED_OPTIONS == _FROZEN_SSH_FIXED_OPTIONS
        and CONTROLLER_WRITE_TIMEOUT_SECONDS == _FROZEN_CONTROLLER_WRITE_TIMEOUT_SECONDS
        and CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS == _FROZEN_CONTROLLER_CHILD_RETIRE_TIMEOUT_SECONDS
        and FIXED_ENVIRONMENT == _FROZEN_ENVIRONMENT
        and POLICY == _FROZEN_POLICY
        and QSUB_ARGV == ("/usr/bin/qsub", "--", "auto-g16-job.pbs")
        and SSH_SUBSYSTEM == "auto-g16-direct-one-hop-v1",
        "production transport source, module, function, executable, or argv binding differs",
    )


__all__ = [
    "DirectOneHopTransportError",
    "ExactSubmissionReceipt",
    "SubmissionOutcomeUnknown",
    "build_controller_argv",
    "consume_production_once",
    "load_transport_profile",
    "run_controller_once",
    "server_subsystem_once",
    "validate_submission_receipt",
    "validate_transport_profile",
]
