#!/usr/bin/env python3
"""Fixed trusted server-local W1/W2/W3/W4 composition (offline seam)."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_FIXED_DEPENDENCY_ORDER = (
    ("execution_facade", "skill", "e7a3127b4729ee1db99fa9691c0d0b7f00cd953e179d750f3af5ee99cd4dcdc3"),
    ("legacy_rtwin_pbs", "skill", "3471014b9358380938e98839aaacb9cd3f9f20146fc79c1a9738483021c2cb8e"),
    ("protected_lifecycle_contract", "root", "166e8b398922682eb94c9705e8ee1ccf0ed13546a75c49010090f7d7182fbafb"),
    ("protected_local_materialization", "root", "e79a703c9f68a7d047210cf3b939caac06cef25f7d664ecece335ea5c444e2d7"),
    ("protected_legacy_effect_handoff", "root", "ceb4ff659070f077b095a76fdcac589bda9dd5d217a5d6680f4bdb31c738d479"),
    ("protected_runtime_state_contract", "root", "3c8a5b523c695b9ecba3345af5ab56a85fd4d578cfbd00832c07751e97d86d9f"),
    ("protected_owner_consumer_contract", "root", "01fe0e30fdbd155e982962d8c4258d4d773d9d0de0b1323e119a6ab3573cd899"),
    ("protected_production_ingress_contract", "root", "0cb8d84271968dbc5641a2a2f625d3f3a950a793952104f773c73f71ff45e2df"),
)


def _read_fixed_dependency_source(path: Path) -> tuple[tuple[int, ...], str]:
    descriptor = os.open(
        path,
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
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or identity
        != (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    ):
        raise ImportError("trusted session dependency source identity differs")
    raw = b"".join(chunks)
    if len(raw) != before.st_size:
        raise ImportError("trusted session dependency source size differs")
    return identity, hashlib.sha256(raw).hexdigest()


def _fixed_dependency_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if type(raw_file) is not str or type(raw_origin) is not str:
        raise ImportError("trusted session dependency origin is unavailable")
    return Path(raw_file).resolve(strict=True), Path(raw_origin).resolve(strict=True)


def _assert_fixed_dependency_chain(
    bindings: tuple[tuple[str, types.ModuleType, Path, tuple[int, ...], str], ...],
) -> None:
    if len(bindings) != len(_FIXED_DEPENDENCY_ORDER):
        raise ImportError("trusted session dependency binding count differs")
    modules: dict[str, types.ModuleType] = {}
    for binding, expected in zip(bindings, _FIXED_DEPENDENCY_ORDER, strict=True):
        name, module, path, identity, source_sha256 = binding
        expected_name, _layout, expected_sha256 = expected
        current_identity, current_sha256 = _read_fixed_dependency_source(path)
        if (
            name != expected_name
            or type(module) is not types.ModuleType
            or sys.modules.get(name) is not module
            or _fixed_dependency_origin(module) != (path, path)
            or identity != current_identity
            or source_sha256 != expected_sha256
            or current_sha256 != expected_sha256
        ):
            raise ImportError(f"trusted session dependency binding differs: {name}")
        modules[name] = module
    local = modules["protected_local_materialization"]
    handoff = modules["protected_legacy_effect_handoff"]
    runtime = modules["protected_runtime_state_contract"]
    consumer = modules["protected_owner_consumer_contract"]
    ingress = modules["protected_production_ingress_contract"]
    local._assert_lifecycle_owner_binding(local._LIFECYCLE_OWNER_BINDING)
    handoff._assert_binding_current(
        handoff._MATERIALIZATION_BINDING,
        path=handoff._materialization_owner_path(),
        issued_type_name="SealedProtectedLocalMaterialization",
    )
    handoff._assert_binding_current(
        handoff._LEGACY_BINDING,
        path=handoff._legacy_owner_path(),
        issued_type_name="_LegacyEffectLifecycleReadinessWitness",
    )
    runtime._assert_sources_current()
    consumer._assert_bindings_current()
    ingress._assert_bindings_current()


def _bootstrap_fixed_dependencies() -> tuple[
    tuple[str, types.ModuleType, Path, tuple[int, ...], str], ...
]:
    session_source = Path(__file__).resolve(strict=True)
    scripts = session_source.parent
    repository = scripts.parent
    skill_scripts = repository / "skills" / "auto-g16-rtwin-pbs" / "scripts"
    if (
        session_source.is_symlink()
        or scripts.is_symlink()
        or skill_scripts.is_symlink()
        or not skill_scripts.is_dir()
    ):
        raise ImportError("trusted session fixed dependency roots differ")
    inserted = (str(skill_scripts), str(scripts))
    for value in reversed(inserted):
        sys.path.insert(0, value)
    bindings: list[tuple[str, types.ModuleType, Path, tuple[int, ...], str]] = []
    try:
        for name, layout, expected_sha256 in _FIXED_DEPENDENCY_ORDER:
            parent = skill_scripts if layout == "skill" else scripts
            path = (parent / f"{name}.py").resolve(strict=True)
            if path.parent != parent.resolve() or path.is_symlink() or not path.is_file():
                raise ImportError(f"trusted session dependency path differs: {name}")
            identity, source_sha256 = _read_fixed_dependency_source(path)
            if source_sha256 != expected_sha256:
                raise ImportError(f"trusted session reviewed dependency bytes differ: {name}")
            module = importlib.import_module(name)
            if (
                type(module) is not types.ModuleType
                or _fixed_dependency_origin(module) != (path, path)
            ):
                raise ImportError(f"trusted session dependency origin differs: {name}")
            bindings.append((name, module, path, identity, source_sha256))
    finally:
        for value in inserted:
            try:
                sys.path.remove(value)
            except ValueError:
                pass
    result = tuple(bindings)
    _assert_fixed_dependency_chain(result)
    return result


_FIXED_DEPENDENCY_BINDINGS = _bootstrap_fixed_dependencies()

import direct_root_fixed_mutation_consumer as W4
import direct_root_owner_contract as W1
import direct_ssh_pbs_offline as DIRECT
import live_approval_effect_time_replay as LIVE
import resource_effect_time_replay_owner as RESOURCE_REPLAY
import resource_efficiency as RESOURCE
import direct_trusted_session_clean_exec as CLEAN_EXEC


def _load_fixed_session_w3() -> types.ModuleType:
    name = "direct_effect_time_replay_ingress"
    expected_sha256 = "9c1f09fba92b36e667ea5584ac9cc7462a97101b5385dccc615e96455e9ccc63"
    path = Path(__file__).resolve(strict=True).with_name(f"{name}.py")
    identity, source_sha256 = _read_fixed_dependency_source(path)
    if source_sha256 != expected_sha256:
        raise ImportError("trusted session reviewed W3 source bytes differ")
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("trusted session fixed W3 loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            if sys.modules.get(name) is module:
                del sys.modules[name]
            raise
    current_identity, current_sha256 = _read_fixed_dependency_source(path)
    if (
        type(module) is not types.ModuleType
        or sys.modules.get(name) is not module
        or _fixed_dependency_origin(module) != (path, path)
        or current_identity != identity
        or current_sha256 != expected_sha256
        or vars(DIRECT).get(module.REGISTRATION_ATTRIBUTE) is not module
    ):
        raise ImportError("trusted session canonical W3 binding differs")
    module._assert_module_binding()
    return module


W3 = _load_fixed_session_w3()
import direct_durable_submission_journal as W2


W2._activate_canonical_w3_owner_once()


MODULE_NAME = "direct_trusted_session_composition"
OWNER = "auto-g16-direct-trusted-server-local-session"
RESULT_SCHEMA = "auto-g16-direct-trusted-session-result/1"
FIXED_PRODUCTION_DURABLE_STATE_ROOT = Path(
    "/var/lib/auto-g16/direct-session-journal"
)
FIXED_CLEAN_EXEC_CWD = "/"
FIXED_CLEAN_EXEC_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C"}
FIXED_CLEAN_EXEC_TIMEOUT_SECONDS = 5.0
W5_TRANSITION_OPERATION = "consume_for_w5_once"
ZERO_SHA = "0" * 64

POLICY = {
    "fixed_clean_exec_required": True,
    "trusted_server_local_session_required": True,
    "untrusted_arbitrary_same_process_code_allowed": False,
    "same_process_reflection_is_security_boundary": False,
    "caller_module_override_allowed": False,
    "caller_command_override_allowed": False,
    "caller_path_override_allowed": False,
    "caller_environment_override_allowed": False,
    "portable_artifacts_are_authority": False,
    "capability_serialization_allowed": False,
    "path_reopen_allowed": False,
    "automatic_retry": False,
    "restart_effect_capability_recovery_allowed": False,
    "restart_reconciliation_read_only_only": True,
    "production_closure": False,
}

AUTHORITY = {
    "authorizes_effect": False,
    "transport_connected": False,
    "backend_supported": False,
    "live_ready": False,
    "external_effects": 0,
    "qsub_calls": 0,
    "qsub_authorized": False,
    "qdel_authorized": False,
    "upload_authorized": False,
    "delete_authorized": False,
    "cleanup_authorized": False,
    "production_closure": False,
}


class DirectTrustedSessionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class _ExecutableSnapshot:
    path: Path
    identity: tuple[int, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectTrustedSessionError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _file_snapshot(path: Path) -> _FileSnapshot:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
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
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    _require(
        stat.S_ISREG(before.st_mode)
        and identity
        == (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        "fixed clean-exec source changed during capture",
    )
    return _FileSnapshot(path, identity, hashlib.sha256(b"".join(chunks)).hexdigest())


def _open_bound_source(snapshot: _FileSnapshot) -> int:
    descriptor = os.open(
        snapshot.path,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        current = _file_snapshot(snapshot.path)
        info = os.fstat(descriptor)
        identity = (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        _require(
            current == snapshot and identity == snapshot.identity,
            "fixed clean-exec source binding differs",
        )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _executable_snapshot(path: Path) -> _ExecutableSnapshot:
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    identity = (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    _require(stat.S_ISREG(info.st_mode), "fixed clean-exec executable differs")
    return _ExecutableSnapshot(resolved, identity)


def _open_descriptors() -> tuple[int, ...]:
    descriptor_directory = Path("/dev/fd")
    if not descriptor_directory.is_dir():
        descriptor_directory = Path("/proc/self/fd")
    values: list[int] = []
    for name in os.listdir(descriptor_directory):
        if name.isascii() and name.isdigit():
            descriptor = int(name, 10)
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            values.append(descriptor)
    return tuple(sorted(set(values)))


def _recv_clean_exec_frame(control: socket.socket) -> dict[str, Any]:
    header = b""
    while len(header) < 4:
        chunk = control.recv(4 - len(header))
        _require(bool(chunk), "fixed clean-exec closed during frame header")
        header += chunk
    size = struct.unpack("!I", header)[0]
    _require(
        0 < size <= CLEAN_EXEC.MAX_FRAME_BYTES,
        "fixed clean-exec frame size differs",
    )
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = control.recv(remaining)
        _require(bool(chunk), "fixed clean-exec closed during frame body")
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectTrustedSessionError("fixed clean-exec response is not JSON") from exc
    _require(
        type(value) is dict and canonical_bytes(value) == raw,
        "fixed clean-exec response is not canonical",
    )
    return value


def _send_clean_exec_frame(control: socket.socket, value: dict[str, Any]) -> None:
    raw = canonical_bytes(value)
    _require(
        0 < len(raw) <= CLEAN_EXEC.MAX_FRAME_BYTES,
        "fixed clean-exec request size differs",
    )
    control.sendall(struct.pack("!I", len(raw)) + raw)


def _same_exact(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(value) is dict:
        return set(value) == set(expected) and all(
            _same_exact(value[key], expected[key]) for key in expected
        )
    if type(value) is list:
        return len(value) == len(expected) and all(
            _same_exact(item, wanted)
            for item, wanted in zip(value, expected, strict=True)
        )
    return value == expected


def _strict_prefixed_sha(value: Any, prefix: str, label: str) -> str:
    _require(
        type(value) is str
        and len(value) == len(prefix) + 64
        and value.startswith(prefix)
        and all(character in "0123456789abcdef" for character in value[len(prefix):]),
        f"trusted session {label} differs",
    )
    return value


def validate_trusted_session_result(value: Any) -> dict[str, Any]:
    _assert_module_binding()
    required = {
        "schema", "owner", "session_id", "binding_payload_sha256", "journal_id",
        "w3_ingress_id", "w3_result_payload_sha256", "w4_project_session_id",
        "project_identity_sha256", "status", "durable_terminal_outcome", "policy",
        "authority", "result_payload_sha256",
    }
    _require(type(value) is dict and set(value) == required, "trusted session result fields differ")
    result = copy.deepcopy(value)
    _require(
        result["schema"] == RESULT_SCHEMA
        and result["owner"] == OWNER
        and result["status"] == "ready_for_w5"
        and result["durable_terminal_outcome"] == "none"
        and _same_exact(result["policy"], POLICY)
        and _same_exact(result["authority"], AUTHORITY),
        "trusted session result constants or non-authority differ",
    )
    for field in (
        "binding_payload_sha256", "w3_result_payload_sha256",
        "project_identity_sha256", "result_payload_sha256",
    ):
        item = result[field]
        _require(
            type(item) is str and len(item) == 64 and item != ZERO_SHA
            and all(character in "0123456789abcdef" for character in item),
            f"trusted session {field} differs",
        )
    for field, prefix in (
        ("session_id", "direct-trusted-session-"),
        ("journal_id", "direct-durable-submission-journal-"),
        ("w3_ingress_id", "direct-effect-time-replay-ingress-"),
        ("w4_project_session_id", "direct-project-session-"),
    ):
        _strict_prefixed_sha(result[field], prefix, field)
    projection = copy.deepcopy(result)
    projection["result_payload_sha256"] = ""
    _require(digest(projection) == result["result_payload_sha256"], "trusted session result hash differs")
    return result


def _fixed_w5_transition_request(readiness: dict[str, Any]) -> dict[str, Any]:
    document = validate_trusted_session_result(readiness)
    return {
        "protocol": CLEAN_EXEC.PROTOCOL,
        "operation": W5_TRANSITION_OPERATION,
        "session_id": document["session_id"],
        "readiness_payload_sha256": document["result_payload_sha256"],
    }


def _validate_w5_lease_ready_ack(
    value: Any,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    document = validate_trusted_session_result(readiness)
    _require(
        type(value) is dict
        and set(value)
        == {
            "protocol", "status", "session_id", "readiness_payload_sha256",
            "authorizes_effect", "transport_connected", "external_effects",
            "qsub_calls", "production_closure",
        }
        and value["protocol"] == CLEAN_EXEC.PROTOCOL
        and value["status"] == "w5_lease_ready"
        and value["session_id"] == document["session_id"]
        and value["readiness_payload_sha256"] == document["result_payload_sha256"]
        and value["authorizes_effect"] is False
        and value["transport_connected"] is False
        and type(value["external_effects"]) is int
        and value["external_effects"] == 0
        and type(value["qsub_calls"]) is int
        and value["qsub_calls"] == 0
        and value["production_closure"] is False,
        "fixed child W5 lease-ready acknowledgement differs",
    )
    return copy.deepcopy(value)


def _consume_fixed_child_w5_transition_once(
    capability: "TrustedServerLocalSessionCapability",
    readiness: dict[str, Any],
    request: Any,
) -> tuple["TrustedServerLocalW5Lease", dict[str, Any]]:
    """Consume the fixed transition while retaining the opaque lease locally."""
    document = validate_trusted_session_result(readiness)
    _require(
        type(capability) is TrustedServerLocalSessionCapability
        and type(request) is dict
        and request == _fixed_w5_transition_request(document),
        "fixed child W5 transition frame differs",
    )
    capability.assert_current()
    lease = capability.consume_for_w5_once()
    lease.assert_current()
    ack = {
        "protocol": CLEAN_EXEC.PROTOCOL,
        "status": "w5_lease_ready",
        "session_id": document["session_id"],
        "readiness_payload_sha256": document["result_payload_sha256"],
        "authorizes_effect": False,
        "transport_connected": False,
        "external_effects": 0,
        "qsub_calls": 0,
        "production_closure": False,
    }
    return lease, _validate_w5_lease_ready_ack(ack, document)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    _require(value.tzinfo is not None and value.utcoffset() is not None, "trusted UTC time differs")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class DirectServerSessionArtifacts:
    """Portable reviewed bytes; this value is never effect authority."""

    profile_policy: bytes
    stable_evidence: bytes
    profile: bytes
    authorization: bytes
    input_bytes: bytes
    resource_ledger: bytes
    resource_policy: bytes
    resource_gate: bytes
    scheduler_snapshot: bytes
    live_approval: bytes

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            _require(type(value) is bytes and bool(value), f"{name} must be non-empty exact bytes")


def _assert_fixed_static_binding() -> None:
    _require(
        globals().get("FIXED_PRODUCTION_DURABLE_STATE_ROOT") is _FIXED_PRODUCTION_ROOT,
        "fixed production state-root binding differs",
    )
    _assert_module_binding()
    _require(
        _file_snapshot(_FIXED_SESSION_SOURCE.path) == _FIXED_SESSION_SOURCE
        and _file_snapshot(_FIXED_HELPER_SOURCE.path) == _FIXED_HELPER_SOURCE
        and _executable_snapshot(_FIXED_EXECUTABLE.path) == _FIXED_EXECUTABLE
        and Path(__file__).resolve() == _FIXED_SESSION_SOURCE.path
        and Path(CLEAN_EXEC.__file__).resolve() == _FIXED_HELPER_SOURCE.path,
        "fixed clean-exec executable or source binding differs",
    )


def _expected_child_argv(
    control_descriptor: int,
    helper_source_descriptor: int,
    session_source_descriptor: int,
) -> tuple[str, ...]:
    return (
        f"/dev/fd/{helper_source_descriptor}",
        CLEAN_EXEC.CHILD_FLAG,
        str(control_descriptor),
        str(helper_source_descriptor),
        str(session_source_descriptor),
        str(_FIXED_SCRIPTS_DIRECTORY),
    )


def _activate_fixed_clean_exec_child(
    *,
    control_descriptor: int,
    helper_source_sha256: str,
    helper_source_identity: tuple[int, ...],
    session_source_sha256: str,
    session_source_identity: tuple[int, ...],
    scripts_directory: str,
    original_argv: tuple[str, ...],
) -> dict[str, Any]:
    """Activate production issuance only after the fixed child self-checks."""
    _assert_fixed_static_binding()
    expected_argv = _expected_child_argv(
        control_descriptor,
        int(original_argv[3], 10) if len(original_argv) == 6 else -1,
        int(original_argv[4], 10) if len(original_argv) == 6 else -1,
    )
    allowed_fds = (0, 1, 2, control_descriptor)
    _require(
        type(control_descriptor) is int
        and control_descriptor >= 3
        and type(original_argv) is tuple
        and original_argv == expected_argv
        and tuple(sys.argv) == expected_argv
        and scripts_directory == str(_FIXED_SCRIPTS_DIRECTORY)
        and helper_source_sha256 == _FIXED_HELPER_SOURCE.sha256
        and tuple(helper_source_identity) == _FIXED_HELPER_SOURCE.identity
        and session_source_sha256 == _FIXED_SESSION_SOURCE.sha256
        and tuple(session_source_identity) == _FIXED_SESSION_SOURCE.identity
        and _executable_snapshot(Path(sys.executable)) == _FIXED_EXECUTABLE
        and sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_user_site == 1
        and sys.flags.safe_path is True
        and os.getcwd() == _FIXED_CLEAN_EXEC_CWD
        and dict(os.environ) == dict(_FIXED_CLEAN_EXEC_ENVIRONMENT)
        and _open_descriptors() == allowed_fds
        and not _CLEAN_EXEC_CHILD_STATE,
        "fixed clean-exec executable, source, entrypoint, argv, env, cwd, or FD allowlist differs",
    )
    _CLEAN_EXEC_CHILD_STATE.update(
        {
            "pid": os.getpid(),
            "control_descriptor": control_descriptor,
            "argv": expected_argv,
            "allowed_fds": allowed_fds,
            "interpreter_flags": ("-I", "-S"),
        }
    )
    return {
        "protocol": CLEAN_EXEC.PROTOCOL,
        "status": "ready_no_artifacts_no_effect",
        "executable": str(_FIXED_EXECUTABLE.path),
        "executable_identity": list(_FIXED_EXECUTABLE.identity),
        "helper_source_sha256": _FIXED_HELPER_SOURCE.sha256,
        "session_source_sha256": _FIXED_SESSION_SOURCE.sha256,
        "entrypoint": expected_argv[0],
        "argv": list(expected_argv),
        "environment": dict(_FIXED_CLEAN_EXEC_ENVIRONMENT),
        "cwd": _FIXED_CLEAN_EXEC_CWD,
        "open_fds": list(allowed_fds),
        "interpreter_flags": ["-I", "-S"],
        "artifacts_received": False,
        "external_effects": 0,
    }


def _assert_fixed_clean_exec_child() -> None:
    _assert_fixed_static_binding()
    state = _CLEAN_EXEC_CHILD_STATE
    _require(
        type(state) is dict
        and set(state)
        == {"pid", "control_descriptor", "argv", "allowed_fds", "interpreter_flags"}
        and state["pid"] == os.getpid()
        and state["interpreter_flags"] == ("-I", "-S")
        and sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_user_site == 1
        and sys.flags.safe_path is True
        and tuple(sys.argv) == state["argv"]
        and _open_descriptors() == state["allowed_fds"]
        and os.getcwd() == _FIXED_CLEAN_EXEC_CWD
        and dict(os.environ) == dict(_FIXED_CLEAN_EXEC_ENVIRONMENT),
        "production owner requires the current fixed clean-exec child",
    )


def _spawn_fixed_clean_exec(
    artifacts: DirectServerSessionArtifacts | None,
) -> Any:
    _assert_fixed_static_binding()
    _require(
        artifacts is None or type(artifacts) is DirectServerSessionArtifacts,
        "fixed clean-exec accepts only exact portable artifact bytes",
    )
    parent: socket.socket | None = None
    child: socket.socket | None = None
    process: subprocess.Popen[bytes] | None = None
    helper_fd = -1
    session_fd = -1
    try:
        parent, child = _FROZEN_SOCKETPAIR(socket.AF_UNIX, socket.SOCK_STREAM)
        parent.settimeout(_FIXED_CLEAN_EXEC_TIMEOUT_SECONDS)
        child_fd = child.fileno()
        helper_fd = _FROZEN_SOURCE_OPENER(_FIXED_HELPER_SOURCE)
        session_fd = _FROZEN_SOURCE_OPENER(_FIXED_SESSION_SOURCE)
        argv = _expected_child_argv(child_fd, helper_fd, session_fd)
        process = _FROZEN_POPEN(
            [str(_FIXED_EXECUTABLE.path), "-I", "-S", *argv],
            close_fds=True,
            pass_fds=(child_fd, helper_fd, session_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=dict(_FIXED_CLEAN_EXEC_ENVIRONMENT),
            cwd=_FIXED_CLEAN_EXEC_CWD,
        )
        os.close(helper_fd)
        helper_fd = -1
        os.close(session_fd)
        session_fd = -1
        child.close()
        child = None
        ready = _FROZEN_FRAME_READER(parent)
        expected_ready = {
            "protocol": CLEAN_EXEC.PROTOCOL,
            "status": "ready_no_artifacts_no_effect",
            "executable": str(_FIXED_EXECUTABLE.path),
            "executable_identity": list(_FIXED_EXECUTABLE.identity),
            "helper_source_sha256": _FIXED_HELPER_SOURCE.sha256,
            "session_source_sha256": _FIXED_SESSION_SOURCE.sha256,
            "entrypoint": argv[0],
            "argv": list(argv),
            "environment": dict(_FIXED_CLEAN_EXEC_ENVIRONMENT),
            "cwd": _FIXED_CLEAN_EXEC_CWD,
            "open_fds": [0, 1, 2, child_fd],
            "interpreter_flags": ["-I", "-S"],
            "artifacts_received": False,
            "external_effects": 0,
        }
        _require(ready == expected_ready, "fixed clean-exec attestation differs")
        _assert_fixed_static_binding()
        if artifacts is None:
            parent.close()
            parent = None
            _require(
                process.wait(timeout=_FIXED_CLEAN_EXEC_TIMEOUT_SECONDS) == 0,
                "fixed clean-exec probe exit differs",
            )
            return ready
        encoded = {
            name: base64.b64encode(getattr(artifacts, name)).decode("ascii")
            for name in artifacts.__dataclass_fields__
        }
        _FROZEN_FRAME_SENDER(
            parent,
            {"protocol": CLEAN_EXEC.PROTOCOL, "artifacts": encoded},
        )
        response = _FROZEN_FRAME_READER(parent)
        _require(
            set(response) == {"protocol", "status", "readiness"}
            and response["protocol"] == CLEAN_EXEC.PROTOCOL
            and response["status"] == "ready_for_w5",
            "fixed clean-exec composition was rejected or uncertain",
        )
        readiness = validate_trusted_session_result(response["readiness"])
        handle = _issue_child_session_handle(
            process=process,
            control=parent,
            readiness=readiness,
        )
        process = None
        parent = None
        return handle
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=_FIXED_CLEAN_EXEC_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        for descriptor in (helper_fd, session_fd):
            if descriptor >= 0:
                os.close(descriptor)
        if child is not None:
            child.close()
        if parent is not None:
            parent.close()


def compose_production_in_fixed_clean_exec_once(
    artifacts: DirectServerSessionArtifacts,
) -> "FixedTrustedServerLocalChildSession":
    """Start and retain one real long-lived clean child at READY_FOR_W5."""
    return _spawn_fixed_clean_exec(artifacts)


def _probe_fixed_clean_exec_for_testing(*, _test_token: object) -> dict[str, Any]:
    _require(_test_token is _TEST_TOKEN, "trusted session test token differs")
    return _spawn_fixed_clean_exec(None)


def _write_exact(directory: Path, name: str, raw: bytes) -> Path:
    directory_fd = os.open(
        directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                _require(written > 0, "session artifact write made no progress")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return directory / name


def _load_exact_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectTrustedSessionError(f"{label} is not exact JSON") from exc
    _require(type(value) is dict, f"{label} must be an exact object")
    return value


class TrustedServerLocalSessionCapability:
    __slots__ = ("session_id", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("trusted session capabilities are owner-issued only")

    def assert_current(self) -> None:
        _assert_session_capability(self, "issued")

    def consume_for_w5_once(self) -> "TrustedServerLocalW5Lease":
        with _SESSION_LOCK:
            record = _assert_session_capability(self, "issued")
            record["status"] = "claiming"
        try:
            with _SESSION_LOCK:
                _require(
                    record["status"] == "claiming",
                    "trusted session W5 transition raced",
                )
                lease = object.__new__(TrustedServerLocalW5Lease)
                lease.lease_id = "direct-trusted-w5-lease-" + digest(
                    [self.session_id, record["journal"].journal_id]
                )
                lease._seal = _W5_LEASE_TOKEN
                _W5_LEASE_REGISTRY[lease] = {
                    "lease": lease,
                    "pid": os.getpid(),
                    "status": "ready_for_w5",
                    "session_record": record,
                }
                record["status"] = "leased_to_w5"
            lease.assert_current()
            return lease
        except BaseException:
            with _SESSION_LOCK:
                record["status"] = "failed"
            _record_unknown_best_effort(record["journal"], self.session_id)
            raise

    def __copy__(self) -> Any:
        raise TypeError("trusted session capabilities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("trusted session capabilities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("trusted session capabilities are not serializable")


class TrustedServerLocalW5Lease:
    """Opaque same-process lease; future W5 remains the only consumer owner."""

    __slots__ = ("lease_id", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("trusted W5 leases are owner-issued only")

    def assert_current(self) -> None:
        _assert_w5_lease(self)

    def __copy__(self) -> Any:
        raise TypeError("trusted W5 leases are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("trusted W5 leases are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("trusted W5 leases are not serializable")


class FixedTrustedServerLocalChildSession:
    """Parent-side lifetime handle; it is evidence, never the W5 capability."""

    __slots__ = ("session_id", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fixed child sessions are owner-issued only")

    def readiness(self) -> dict[str, Any]:
        record = _assert_child_session_handle(
            self,
            {"ready_for_w5", "w5_lease_ready"},
        )
        return copy.deepcopy(record["readiness"])

    def transition_to_w5_once(self) -> dict[str, Any]:
        return _transition_child_session_to_w5_once(self)

    def __copy__(self) -> Any:
        raise TypeError("fixed child sessions are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("fixed child sessions are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("fixed child sessions are not serializable")


class FixedTrustedServerLocalSessionOwner:
    __slots__ = ("_durable_state_root", "_lock", "_pid", "_seal", "_status")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("trusted session owners use a fixed factory")

    @classmethod
    def production(cls) -> "FixedTrustedServerLocalSessionOwner":
        _assert_fixed_clean_exec_child()
        return _new_owner(_FIXED_PRODUCTION_ROOT, _PRODUCTION_OWNER_TOKEN)

    @classmethod
    def _for_fake_local_testing(
        cls,
        *,
        durable_state_root: Path,
        _test_token: object,
    ) -> "FixedTrustedServerLocalSessionOwner":
        _require(_test_token is _TEST_TOKEN, "trusted session test token differs")
        return _new_owner(durable_state_root, _TEST_OWNER_TOKEN)

    def compose_once(
        self,
        artifacts: DirectServerSessionArtifacts,
    ) -> TrustedServerLocalSessionCapability:
        with self._lock:
            _require(
                type(self) is FixedTrustedServerLocalSessionOwner
                and self._pid == os.getpid()
                and self._status == "issued"
                and self._seal in {_PRODUCTION_OWNER_TOKEN, _TEST_OWNER_TOKEN}
                and type(artifacts) is DirectServerSessionArtifacts,
                "trusted session owner, process, or artifacts differ",
            )
            self._status = "claiming"
            journal: W2.DurableEffectClaim | None = None
            project: W4.DirectProjectSessionCapability | None = None
            root_capability: W1.SingleUseWorkspaceDescriptorCapability | None = None
            try:
                _assert_module_binding()
                if self._seal is _PRODUCTION_OWNER_TOKEN:
                    _assert_fixed_clean_exec_child()
                with tempfile.TemporaryDirectory(
                    prefix="auto-g16-direct-session-",
                    dir="/tmp",
                ) as raw_directory:
                    directory = Path(raw_directory).resolve()
                    policy_path = _write_exact(directory, "resource-policy.json", artifacts.resource_policy)
                    gate_path = _write_exact(directory, "resource-gate.json", artifacts.resource_gate)
                    scheduler_path = _write_exact(directory, "scheduler-snapshot.json", artifacts.scheduler_snapshot)
                    ledger_path = _write_exact(directory, "resource-ledger.json", artifacts.resource_ledger)
                    approval_path = _write_exact(directory, "live-approval.json", artifacts.live_approval)

                    root_owner = W1.DirectRootOwnerContractOwner.for_posix_backend()
                    root_capability = root_owner.issue_server_session_capability_from_exact_artifacts_once(
                        profile_policy_bytes=artifacts.profile_policy,
                        stable_evidence_bytes=artifacts.stable_evidence,
                        profile_bytes=artifacts.profile,
                        authorization_bytes=artifacts.authorization,
                    )
                    authorization = W1.validate_direct_execution_authorization(
                        _load_exact_json(artifacts.authorization, "authorization")
                    )
                    transaction = DIRECT.DirectServerSessionTransactionOwner.production().issue_once(
                        root_capability=root_capability,
                        immutable_input=DIRECT.ImmutableInput(
                            authorization["input"]["basename"],
                            artifacts.input_bytes,
                        ),
                    )
                    approval = _load_exact_json(artifacts.live_approval, "live approval")
                    scope = approval["scope"]
                    execution = scope["execution"]
                    ledger = RESOURCE.validate_ledger(RESOURCE.load(ledger_path))
                    task = next(
                        (
                            item
                            for item in ledger["tasks"]
                            if item["scientific_task_id"] == execution["scientific_task_id"]
                        ),
                        None,
                    )
                    _require(type(task) is dict, "resource ledger lacks the exact scientific task")
                    scheduler = RESOURCE.load(scheduler_path)
                    scheduler_raw = scheduler_path.read_bytes()
                    reservation = RESOURCE.reserve_attempt_capability(
                        ledger_path,
                        execution["scientific_task_id"],
                        identity=task["identity"],
                        idempotency_key=execution["idempotency_key"],
                        project=scope["project"],
                        remote_workdir=scope["remote_workdir"],
                        input_sha256=scope["input_sha256"],
                        live_approval_id=approval["approval_id"],
                        live_approval_sha256=hashlib.sha256(artifacts.live_approval).hexdigest(),
                        estimated_core_hours_evidence=execution["estimated_core_hours_evidence"],
                        reserved_at=_utc_text(_utc_now()),
                        audit_reason="fixed trusted server-local session exact artifact replay",
                        policy=RESOURCE.load(policy_path),
                        gate=RESOURCE.load(gate_path),
                        scheduler_snapshot=scheduler,
                        scheduler_artifact_sha256=hashlib.sha256(scheduler_raw).hexdigest(),
                        scheduler_artifact_size=len(scheduler_raw),
                    )
                    resource_capability = RESOURCE_REPLAY.issue_resource_effect_time_replay_capability(
                        reservation_capability=reservation,
                        ledger_path=ledger_path,
                        policy_path=policy_path,
                        gate_path=gate_path,
                        scheduler_path=scheduler_path,
                    )
                    live_capability = LIVE.LiveApprovalEffectTimeReplayOwner.production().issue_direct_server_session_once(
                        transaction,
                        approval_path,
                    )
                    w3_capability = W3.DirectEffectTimeReplayIngressOwner.production().seal_server_session_once(
                        direct_transaction=transaction,
                        resource_replay=resource_capability,
                        live_approval_replay=live_capability,
                    )
                    journal = W2.consume_for_server_session_replay_once(
                        self._durable_state_root,
                        transaction,
                        w3_capability,
                    )
                    w3_claim = w3_capability.consume_once()
                    w3_claim.assert_owner_sealed()
                    w4_transaction = W4.DirectRootFixedMutationOwner.for_posix_backend().issue_session_once(
                        root_capability=root_capability,
                        durable_journal_claim=journal,
                        direct_binding=transaction._binding,
                    )
                    project = w4_transaction.apply_for_session_once()
                    project.assert_current()

                capability = _issue_session_capability(
                    transaction=transaction,
                    w3=w3_claim,
                    journal=journal,
                    project=project,
                )
                self._status = "consumed"
                return capability
            except BaseException:
                self._status = "failed"
                if project is not None:
                    try:
                        project.consume_once().close_once()
                    except BaseException:
                        pass
                if root_capability is not None:
                    try:
                        W1._close_descriptor_bundle_once(
                            root_capability._descriptor_set._descriptor_bundle,
                            owner="capability",
                        )
                    except BaseException:
                        pass
                if journal is not None:
                    _record_unknown_best_effort(journal, "composition-failed")
                raise


_PRODUCTION_OWNER_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_TEST_TOKEN = object()
_SESSION_TOKEN = object()
_W5_LEASE_TOKEN = object()
_CHILD_SESSION_TOKEN = object()
_SESSION_LOCK = threading.RLock()
_SESSION_REGISTRY: dict[object, dict[str, Any]] = {}
_W5_LEASE_REGISTRY: dict[object, dict[str, Any]] = {}
_CHILD_SESSION_REGISTRY: dict[object, dict[str, Any]] = {}
_FIXED_PRODUCTION_ROOT = FIXED_PRODUCTION_DURABLE_STATE_ROOT
_FIXED_SCRIPTS_DIRECTORY = Path(__file__).resolve().parent
_FIXED_SESSION_SOURCE = _file_snapshot(Path(__file__).resolve())
_FIXED_HELPER_SOURCE = _file_snapshot(Path(CLEAN_EXEC.__file__).resolve())
_FIXED_EXECUTABLE = _executable_snapshot(Path(sys.executable))
_FIXED_CLEAN_EXEC_CWD = FIXED_CLEAN_EXEC_CWD
_FIXED_CLEAN_EXEC_ENVIRONMENT = copy.deepcopy(FIXED_CLEAN_EXEC_ENVIRONMENT)
_FIXED_CLEAN_EXEC_TIMEOUT_SECONDS = FIXED_CLEAN_EXEC_TIMEOUT_SECONDS
_FROZEN_POPEN = subprocess.Popen
_FROZEN_SOCKETPAIR = socket.socketpair
_FROZEN_SOURCE_OPENER = _open_bound_source
_FROZEN_FRAME_READER = _recv_clean_exec_frame
_FROZEN_FRAME_SENDER = _send_clean_exec_frame
_CLEAN_EXEC_CHILD_STATE: dict[str, Any] = {}


def _new_owner(path: Path, token: object) -> FixedTrustedServerLocalSessionOwner:
    _assert_module_binding()
    _require(
        isinstance(path, Path)
        and path.is_absolute()
        and path.is_dir()
        and not path.is_symlink()
        and token in {_PRODUCTION_OWNER_TOKEN, _TEST_OWNER_TOKEN},
        "fixed durable state root is unavailable or unsafe",
    )
    value = object.__new__(FixedTrustedServerLocalSessionOwner)
    value._durable_state_root = path
    value._lock = threading.Lock()
    value._pid = os.getpid()
    value._seal = token
    value._status = "issued"
    return value


def _issue_child_session_handle(
    *,
    process: subprocess.Popen[bytes],
    control: socket.socket,
    readiness: dict[str, Any],
) -> FixedTrustedServerLocalChildSession:
    document = validate_trusted_session_result(readiness)
    _require(
        type(process) is subprocess.Popen
        and process.poll() is None
        and type(control) is socket.socket
        and control.fileno() >= 0,
        "fixed clean-exec child lifetime differs",
    )
    value = object.__new__(FixedTrustedServerLocalChildSession)
    value.session_id = document["session_id"]
    value._seal = _CHILD_SESSION_TOKEN
    with _SESSION_LOCK:
        _CHILD_SESSION_REGISTRY[value] = {
            "handle": value,
            "pid": os.getpid(),
            "status": "ready_for_w5",
            "process": process,
            "control": control,
            "readiness": copy.deepcopy(document),
        }
    _assert_child_session_handle(value, {"ready_for_w5"})
    return value


def _assert_child_session_handle(
    handle: FixedTrustedServerLocalChildSession,
    expected_statuses: set[str],
) -> dict[str, Any]:
    _assert_module_binding()
    with _SESSION_LOCK:
        record = _CHILD_SESSION_REGISTRY.get(handle)
        _require(
            type(handle) is FixedTrustedServerLocalChildSession
            and handle._seal is _CHILD_SESSION_TOKEN
            and type(record) is dict
            and record["handle"] is handle
            and record["pid"] == os.getpid()
            and record["status"] in expected_statuses
            and record["process"].poll() is None
            and record["control"].fileno() >= 0
            and record["readiness"]["session_id"] == handle.session_id,
            "fixed clean-exec child is foreign, forked, exited, or terminal",
        )
        validate_trusted_session_result(record["readiness"])
        return record


def _transition_child_session_to_w5_once(
    handle: FixedTrustedServerLocalChildSession,
) -> dict[str, Any]:
    try:
        record = _assert_child_session_handle(handle, {"ready_for_w5"})
    except BaseException:
        with _SESSION_LOCK:
            duplicate = _CHILD_SESSION_REGISTRY.get(handle)
            if (
                type(duplicate) is dict
                and duplicate.get("handle") is handle
                and duplicate.get("pid") == os.getpid()
                and duplicate.get("status") == "w5_lease_ready"
            ):
                duplicate["status"] = "failed_duplicate_transition"
                try:
                    duplicate["control"].close()
                except BaseException:
                    pass
        raise
    with _SESSION_LOCK:
        _require(
            record["status"] == "ready_for_w5",
            "fixed child W5 transition raced",
        )
        record["status"] = "transitioning_to_w5"
    try:
        request = _fixed_w5_transition_request(record["readiness"])
        _FROZEN_FRAME_SENDER(record["control"], request)
        response = _FROZEN_FRAME_READER(record["control"])
        ack = _validate_w5_lease_ready_ack(response, record["readiness"])
        _require(
            record["process"].poll() is None,
            "fixed child exited during W5 transition",
        )
        with _SESSION_LOCK:
            _require(
                record["status"] == "transitioning_to_w5",
                "fixed child W5 transition state differs",
            )
            record["status"] = "w5_lease_ready"
            record["w5_ack"] = copy.deepcopy(ack)
        return ack
    except BaseException:
        with _SESSION_LOCK:
            record["status"] = "failed_w5_transition"
        try:
            record["control"].close()
        except BaseException:
            pass
        raise


def _abort_child_session_for_testing(
    handle: FixedTrustedServerLocalChildSession,
    *,
    _test_token: object,
) -> int:
    _require(_test_token is _TEST_TOKEN, "trusted session test token differs")
    record = _assert_child_session_handle(
        handle,
        {"ready_for_w5", "w5_lease_ready"},
    )
    with _SESSION_LOCK:
        record["status"] = "aborting_for_testing"
    record["control"].close()
    exit_code = record["process"].wait(
        timeout=_FIXED_CLEAN_EXEC_TIMEOUT_SECONDS
    )
    with _SESSION_LOCK:
        record["status"] = "aborted_for_testing"
    return exit_code


def _issue_session_capability(
    *,
    transaction: DIRECT.DirectServerSessionTransaction,
    w3: W3.ClaimedDirectEffectTimeReplayIngress,
    journal: W2.DurableEffectClaim,
    project: W4.DirectProjectSessionCapability,
) -> TrustedServerLocalSessionCapability:
    session_id = "direct-trusted-session-" + digest(
        {
            "binding": transaction._binding.sha256,
            "w3": w3.ingress_id,
            "journal": journal.journal_id,
            "project": project.session_id,
        }
    )
    value = object.__new__(TrustedServerLocalSessionCapability)
    value.session_id = session_id
    value._seal = _SESSION_TOKEN
    with _SESSION_LOCK:
        _SESSION_REGISTRY[value] = {
            "capability": value,
            "pid": os.getpid(),
            "status": "issued",
            "session_id": session_id,
            "transaction": transaction,
            "w3": w3,
            "journal": journal,
            "project": project,
        }
    value.assert_current()
    return value


def _assert_session_capability(
    capability: TrustedServerLocalSessionCapability,
    status: str,
) -> dict[str, Any]:
    _assert_module_binding()
    with _SESSION_LOCK:
        record = _SESSION_REGISTRY.get(capability)
        _require(
            type(capability) is TrustedServerLocalSessionCapability
            and capability._seal is _SESSION_TOKEN
            and type(record) is dict
            and record["capability"] is capability
            and record["pid"] == os.getpid()
            and record["status"] == status
            and record["session_id"] == capability.session_id
            and type(record["transaction"]) is DIRECT.DirectServerSessionTransaction
            and type(record["w3"]) is W3.ClaimedDirectEffectTimeReplayIngress
            and type(record["journal"]) is W2.DurableEffectClaim
            and type(record["project"]) is W4.DirectProjectSessionCapability,
            "trusted session capability is foreign, forked, consumed, or terminal",
        )
        record["transaction"].assert_current()
        record["w3"].assert_owner_sealed()
        record["project"].assert_current()
        _require(
            record["journal"].journal_id
            == W2.journal_id_for_binding(record["transaction"]._binding)
            and record["journal"].binding_payload_sha256
            == record["transaction"]._binding.sha256
            and record["journal"].outcome == "started"
            and record["journal"].authorizes_effect is False,
            "trusted session W2 claim drifted",
        )
        return record


def _assert_w5_lease(lease: TrustedServerLocalW5Lease) -> dict[str, Any]:
    _assert_module_binding()
    with _SESSION_LOCK:
        record = _W5_LEASE_REGISTRY.get(lease)
        _require(
            type(lease) is TrustedServerLocalW5Lease
            and lease._seal is _W5_LEASE_TOKEN
            and type(record) is dict
            and record["lease"] is lease
            and record["pid"] == os.getpid()
            and record["status"] == "ready_for_w5",
            "trusted W5 lease is foreign, forked, consumed, or terminal",
        )
        session = record["session_record"]
        _require(
            type(session) is dict
            and session["status"] == "leased_to_w5"
            and type(session["transaction"]) is DIRECT.DirectServerSessionTransaction
            and type(session["w3"]) is W3.ClaimedDirectEffectTimeReplayIngress
            and type(session["journal"]) is W2.DurableEffectClaim
            and type(session["project"]) is W4.DirectProjectSessionCapability,
            "trusted W5 exact-object join differs",
        )
        session["transaction"].assert_current()
        session["w3"].assert_owner_sealed()
        session["project"].assert_current()
        _require(
            session["journal"].outcome == "started"
            and session["journal"].authorizes_effect is False
            and session["journal"].binding_payload_sha256
            == session["transaction"]._binding.sha256,
            "trusted W5 durable started claim drifted",
        )
        return record


def _session_ready_document(
    capability: TrustedServerLocalSessionCapability,
) -> dict[str, Any]:
    record = _assert_session_capability(capability, "issued")
    project_record = W4._SESSION_REGISTRY.get(record["project"])
    _require(
        type(project_record) is dict
        and project_record["capability"] is record["project"]
        and project_record["status"] == "issued",
        "trusted session project owner record differs",
    )
    w3_document = record["w3"].document()
    document = {
        "schema": RESULT_SCHEMA,
        "owner": OWNER,
        "session_id": capability.session_id,
        "binding_payload_sha256": record["transaction"]._binding.sha256,
        "journal_id": record["journal"].journal_id,
        "w3_ingress_id": record["w3"].ingress_id,
        "w3_result_payload_sha256": w3_document["result_payload_sha256"],
        "w4_project_session_id": record["project"].session_id,
        "project_identity_sha256": digest(list(project_record["project_identity"])),
        "status": "ready_for_w5",
        "durable_terminal_outcome": "none",
        "policy": copy.deepcopy(POLICY),
        "authority": copy.deepcopy(AUTHORITY),
        "result_payload_sha256": "",
    }
    document["result_payload_sha256"] = digest(document)
    return validate_trusted_session_result(document)


def _retire_session_unknown_once(
    capability: TrustedServerLocalSessionCapability,
    evidence: str,
) -> None:
    with _SESSION_LOCK:
        record = _SESSION_REGISTRY.get(capability)
        _require(
            type(record) is dict
            and record["capability"] is capability
            and record["pid"] == os.getpid()
            and record["status"] in {"issued", "leased_to_w5"},
            "trusted session retirement state differs",
        )
        record["status"] = "failed"
    _record_unknown_best_effort(record["journal"], evidence)
    try:
        record["project"].consume_once().close_once()
    except BaseException:
        try:
            W4._close_project_session_capability(
                record["project"],
                expected_status=None,
            )
        except BaseException:
            pass


def _retire_w5_lease_for_testing(
    lease: TrustedServerLocalW5Lease,
    *,
    _test_token: object,
) -> None:
    _require(_test_token is _TEST_TOKEN, "trusted session test token differs")
    record = _assert_w5_lease(lease)
    with _SESSION_LOCK:
        record["status"] = "retired_for_testing"
    _retire_session_unknown_once(
        record["session_record"]["capability"],
        lease.lease_id,
    )


def _record_unknown_best_effort(claim: W2.DurableEffectClaim, evidence: str) -> None:
    try:
        W2.record_outcome_once(
            claim,
            outcome="unknown",
            evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        )
    except BaseException:
        pass


@dataclass(frozen=True, slots=True)
class _ModuleBinding:
    module: types.ModuleType
    modules: tuple[tuple[str, types.ModuleType], ...]
    dependency_bindings: tuple[tuple[str, types.ModuleType, Path, tuple[int, ...], str], ...]
    dependency_order: tuple[tuple[str, str, str], ...]
    dependency_bootstrap: Any
    dependency_assert: Any
    dependency_reader: Any
    dependency_origin: Any
    w3_loader: Any
    production_methods: tuple[object, ...]
    production_root: Path
    scripts_directory: Path
    session_source: _FileSnapshot
    helper_source: _FileSnapshot
    executable: _ExecutableSnapshot
    clean_exec_module: types.ModuleType
    clean_exec_protocol: str
    clean_exec_child_flag: str
    clean_exec_environment: dict[str, str]
    clean_exec_cwd: str
    clean_exec_timeout: float
    popen: Any
    socketpair: Any
    source_opener: Any
    frame_reader: Any
    frame_sender: Any
    expected_argv: Any
    activation: Any
    launcher: Any
    public_launcher: Any
    child_state: dict[str, Any]


def _capture_module_binding() -> _ModuleBinding:
    module = sys.modules.get(MODULE_NAME)
    _require(__name__ == MODULE_NAME and isinstance(module, types.ModuleType), "canonical session module differs")
    modules = tuple(
        (item.__name__, item)
        for item in (W1, W2, W3, W4, DIRECT, LIVE, RESOURCE_REPLAY, RESOURCE, CLEAN_EXEC)
    )
    return _ModuleBinding(
        module=module,
        modules=modules,
        dependency_bindings=_FIXED_DEPENDENCY_BINDINGS,
        dependency_order=_FIXED_DEPENDENCY_ORDER,
        dependency_bootstrap=_bootstrap_fixed_dependencies,
        dependency_assert=_assert_fixed_dependency_chain,
        dependency_reader=_read_fixed_dependency_source,
        dependency_origin=_fixed_dependency_origin,
        w3_loader=_load_fixed_session_w3,
        production_methods=(
            _require,
            _same_exact,
            _strict_prefixed_sha,
            validate_trusted_session_result,
            W1.DirectRootOwnerContractOwner.__dict__["for_posix_backend"],
            W1.DirectRootOwnerContractOwner.__dict__["issue_server_session_capability_from_exact_artifacts_once"],
            DIRECT.DirectServerSessionTransactionOwner.__dict__["production"],
            DIRECT.DirectServerSessionTransactionOwner.__dict__["issue_once"],
            LIVE.LiveApprovalEffectTimeReplayOwner.__dict__["production"],
            LIVE.LiveApprovalEffectTimeReplayOwner.__dict__["issue_direct_server_session_once"],
            W3.DirectEffectTimeReplayIngressOwner.__dict__["production"],
            W3.DirectEffectTimeReplayIngressOwner.__dict__["seal_server_session_once"],
            W3.DirectEffectTimeReplayIngressCapability.__dict__["assert_server_session_pre_w2_current"],
            W2._activate_canonical_w3_owner_once,
            W2.consume_for_server_session_replay_once,
            W4.DirectRootFixedMutationOwner.__dict__["for_posix_backend"],
            W4.DirectRootFixedMutationOwner.__dict__["issue_session_once"],
            FixedTrustedServerLocalSessionOwner.__dict__["production"],
            FixedTrustedServerLocalSessionOwner.__dict__["compose_once"],
            TrustedServerLocalSessionCapability.__dict__["consume_for_w5_once"],
            TrustedServerLocalW5Lease.__dict__["assert_current"],
            FixedTrustedServerLocalChildSession.__dict__["readiness"],
            FixedTrustedServerLocalChildSession.__dict__["transition_to_w5_once"],
            _fixed_w5_transition_request,
            _validate_w5_lease_ready_ack,
            _consume_fixed_child_w5_transition_once,
            _transition_child_session_to_w5_once,
        ),
        production_root=_FIXED_PRODUCTION_ROOT,
        scripts_directory=_FIXED_SCRIPTS_DIRECTORY,
        session_source=_FIXED_SESSION_SOURCE,
        helper_source=_FIXED_HELPER_SOURCE,
        executable=_FIXED_EXECUTABLE,
        clean_exec_module=CLEAN_EXEC,
        clean_exec_protocol=CLEAN_EXEC.PROTOCOL,
        clean_exec_child_flag=CLEAN_EXEC.CHILD_FLAG,
        clean_exec_environment=copy.deepcopy(_FIXED_CLEAN_EXEC_ENVIRONMENT),
        clean_exec_cwd=_FIXED_CLEAN_EXEC_CWD,
        clean_exec_timeout=_FIXED_CLEAN_EXEC_TIMEOUT_SECONDS,
        popen=_FROZEN_POPEN,
        socketpair=_FROZEN_SOCKETPAIR,
        source_opener=_FROZEN_SOURCE_OPENER,
        frame_reader=_FROZEN_FRAME_READER,
        frame_sender=_FROZEN_FRAME_SENDER,
        expected_argv=_expected_child_argv,
        activation=_activate_fixed_clean_exec_child,
        launcher=_spawn_fixed_clean_exec,
        public_launcher=compose_production_in_fixed_clean_exec_once,
        child_state=_CLEAN_EXEC_CHILD_STATE,
    )


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    _require(
        isinstance(binding, _ModuleBinding)
        and sys.modules.get(MODULE_NAME) is binding.module
        and all(sys.modules.get(name) is module for name, module in binding.modules)
        and _FIXED_DEPENDENCY_BINDINGS is binding.dependency_bindings
        and _FIXED_DEPENDENCY_ORDER is binding.dependency_order
        and _bootstrap_fixed_dependencies is binding.dependency_bootstrap
        and _assert_fixed_dependency_chain is binding.dependency_assert
        and _read_fixed_dependency_source is binding.dependency_reader
        and _fixed_dependency_origin is binding.dependency_origin
        and _load_fixed_session_w3 is binding.w3_loader
        and binding.production_methods
        == (
            _require,
            _same_exact,
            _strict_prefixed_sha,
            validate_trusted_session_result,
            W1.DirectRootOwnerContractOwner.__dict__.get("for_posix_backend"),
            W1.DirectRootOwnerContractOwner.__dict__.get("issue_server_session_capability_from_exact_artifacts_once"),
            DIRECT.DirectServerSessionTransactionOwner.__dict__.get("production"),
            DIRECT.DirectServerSessionTransactionOwner.__dict__.get("issue_once"),
            LIVE.LiveApprovalEffectTimeReplayOwner.__dict__.get("production"),
            LIVE.LiveApprovalEffectTimeReplayOwner.__dict__.get("issue_direct_server_session_once"),
            W3.DirectEffectTimeReplayIngressOwner.__dict__.get("production"),
            W3.DirectEffectTimeReplayIngressOwner.__dict__.get("seal_server_session_once"),
            W3.DirectEffectTimeReplayIngressCapability.__dict__.get("assert_server_session_pre_w2_current"),
            W2._activate_canonical_w3_owner_once,
            W2.consume_for_server_session_replay_once,
            W4.DirectRootFixedMutationOwner.__dict__.get("for_posix_backend"),
            W4.DirectRootFixedMutationOwner.__dict__.get("issue_session_once"),
            FixedTrustedServerLocalSessionOwner.__dict__.get("production"),
            FixedTrustedServerLocalSessionOwner.__dict__.get("compose_once"),
            TrustedServerLocalSessionCapability.__dict__.get("consume_for_w5_once"),
            TrustedServerLocalW5Lease.__dict__.get("assert_current"),
            FixedTrustedServerLocalChildSession.__dict__.get("readiness"),
            FixedTrustedServerLocalChildSession.__dict__.get("transition_to_w5_once"),
            _fixed_w5_transition_request,
            _validate_w5_lease_ready_ack,
            _consume_fixed_child_w5_transition_once,
            _transition_child_session_to_w5_once,
        )
        and FIXED_PRODUCTION_DURABLE_STATE_ROOT is binding.production_root
        and _FIXED_PRODUCTION_ROOT is binding.production_root
        and _FIXED_SCRIPTS_DIRECTORY is binding.scripts_directory
        and _FIXED_SESSION_SOURCE is binding.session_source
        and _FIXED_HELPER_SOURCE is binding.helper_source
        and _FIXED_EXECUTABLE is binding.executable
        and sys.modules.get(CLEAN_EXEC.__name__) is binding.clean_exec_module
        and CLEAN_EXEC.PROTOCOL == binding.clean_exec_protocol
        and CLEAN_EXEC.CHILD_FLAG == binding.clean_exec_child_flag
        and FIXED_CLEAN_EXEC_ENVIRONMENT == binding.clean_exec_environment
        and _FIXED_CLEAN_EXEC_ENVIRONMENT == binding.clean_exec_environment
        and FIXED_CLEAN_EXEC_CWD == binding.clean_exec_cwd
        and _FIXED_CLEAN_EXEC_CWD == binding.clean_exec_cwd
        and FIXED_CLEAN_EXEC_TIMEOUT_SECONDS == binding.clean_exec_timeout
        and _FIXED_CLEAN_EXEC_TIMEOUT_SECONDS == binding.clean_exec_timeout
        and subprocess.Popen is binding.popen
        and _FROZEN_POPEN is binding.popen
        and socket.socketpair is binding.socketpair
        and _FROZEN_SOCKETPAIR is binding.socketpair
        and _open_bound_source is binding.source_opener
        and _FROZEN_SOURCE_OPENER is binding.source_opener
        and _recv_clean_exec_frame is binding.frame_reader
        and _FROZEN_FRAME_READER is binding.frame_reader
        and _send_clean_exec_frame is binding.frame_sender
        and _FROZEN_FRAME_SENDER is binding.frame_sender
        and _expected_child_argv is binding.expected_argv
        and _activate_fixed_clean_exec_child is binding.activation
        and _spawn_fixed_clean_exec is binding.launcher
        and compose_production_in_fixed_clean_exec_once is binding.public_launcher
        and _CLEAN_EXEC_CHILD_STATE is binding.child_state,
        "trusted session production owner binding differs",
    )
    binding.dependency_assert(binding.dependency_bindings)


def _after_fork_child() -> None:
    with _SESSION_LOCK:
        for record in tuple(_CHILD_SESSION_REGISTRY.values()):
            try:
                record["control"].close()
            except BaseException:
                pass
        _SESSION_REGISTRY.clear()
        _W5_LEASE_REGISTRY.clear()
        _CHILD_SESSION_REGISTRY.clear()


_MODULE_BINDING: _ModuleBinding | None = None
_MODULE_BINDING = _capture_module_binding()
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


__all__ = [
    "AUTHORITY",
    "DirectServerSessionArtifacts",
    "DirectTrustedSessionError",
    "FixedTrustedServerLocalChildSession",
    "FixedTrustedServerLocalSessionOwner",
    "POLICY",
    "RESULT_SCHEMA",
    "TrustedServerLocalSessionCapability",
    "TrustedServerLocalW5Lease",
    "compose_production_in_fixed_clean_exec_once",
    "validate_trusted_session_result",
]
