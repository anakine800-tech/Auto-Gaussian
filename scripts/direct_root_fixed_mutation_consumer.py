#!/usr/bin/env python3
"""Process-isolated consumer for W1 direct-root POSIX descriptor capability.

The existing :mod:`direct_root_owner_contract` remains the sole profile,
approval, observation, capability, descriptor-lifecycle, and close owner.
This module adds only a fixed local-filesystem consumer.  It cannot select a
root, accept commands, use a shell or transport, submit PBS/Gaussian work,
retry, rename, delete, clean up, or authorize a remote effect.
"""

from __future__ import annotations

import array
import copy
import hashlib
import hmac
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import direct_root_fixed_mutation_helper as HELPER
import direct_root_owner_contract as ROOT


MODULE_NAME = "direct_root_fixed_mutation_consumer"
OWNER = "auto-g16-direct-root-fixed-mutation-consumer"
OWNER_VERSION = "direct-root-fixed-mutation-consumer/1"
RESULT_SCHEMA = "auto-g16-direct-root-fixed-mutation-result/1"
BACKEND_KIND = "direct_ssh_pbs"
READY = "ready"
ZERO_EFFECT_TERMINAL = "zero_effect_terminal"
OUTCOME_UNCERTAIN = "outcome_uncertain"
COMPLETED = "completed"
OPERATIONS = (
    "create_project_directory_exclusive",
    "create_scratch_directory_exclusive",
)
FIXED_TIMEOUT_SECONDS = 5.0
ZERO_SHA = "0" * 64


class DirectRootFixedMutationError(ValueError):
    pass


class DurableJournalSeamDocument(TypedDict):
    """Non-authorizing integration seam for the separate W2 durable owner."""

    schema: str
    journal_id: str
    binding_payload_sha256: str
    receipt_payload_sha256: str
    authorization_scope_sha256: str
    workspace_binding_sha256: str
    descriptor_set_sha256: str
    outcome: str
    authorizes_effect: bool


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, int, int, int, int]
    sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectRootFixedMutationError(message)


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


def _finalize(document: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(document)
    value["result_payload_sha256"] = ""
    value["result_payload_sha256"] = digest(value)
    return value


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and len(value) == 64
        and value != ZERO_SHA
        and all(character in "0123456789abcdef" for character in value),
        f"{label} differs",
    )
    return value


def validate_durable_journal_seam(value: Any) -> DurableJournalSeamDocument:
    """Validate a closed value seam; it is evidence, never journal authority."""
    _require(type(value) is dict, "durable journal seam must be an exact object")
    required = {
        "schema",
        "journal_id",
        "binding_payload_sha256",
        "receipt_payload_sha256",
        "authorization_scope_sha256",
        "workspace_binding_sha256",
        "descriptor_set_sha256",
        "outcome",
        "authorizes_effect",
    }
    _require(set(value) == required, "durable journal seam fields differ")
    _require(
        value["schema"] == "auto-g16-direct-durable-journal-claim-seam/1",
        "durable journal seam schema differs",
    )
    journal_id = value["journal_id"]
    _require(
        type(journal_id) is str
        and journal_id.startswith("direct-durable-submission-journal-")
        and len(journal_id) == len("direct-durable-submission-journal-") + 64
        and all(character in "0123456789abcdef" for character in journal_id[-64:]),
        "durable journal seam id differs",
    )
    for field in (
        "binding_payload_sha256",
        "receipt_payload_sha256",
        "authorization_scope_sha256",
        "workspace_binding_sha256",
        "descriptor_set_sha256",
    ):
        _sha(value[field], f"durable journal seam {field}")
    _require(
        type(value["outcome"]) is str
        and value["outcome"] == "started"
        and type(value["authorizes_effect"]) is bool
        and value["authorizes_effect"] is False,
        "durable journal seam state differs",
    )
    return copy.deepcopy(value)


def _authority(outcome: str) -> dict[str, Any]:
    return {
        "schema_valid_is_capability": False,
        "helper_process_isolation_required": True,
        "descriptor_relative_required": True,
        "fixed_operation_set": True,
        "filesystem_mutation_completion_confirmed": outcome == COMPLETED,
        "durable_journal_owner_integrated": False,
        "remote_effect_authorized": False,
        "transport_authorized": False,
        "shell_authorized": False,
        "ssh_authorized": False,
        "pbs_authorized": False,
        "gaussian_authorized": False,
        "qsub_authorized": False,
        "qdel_authorized": False,
        "delete_authorized": False,
        "cleanup_authorized": False,
        "rename_authorized": False,
        "automatic_retry": False,
        "path_reopen_allowed": False,
    }


def validate_fixed_mutation_result(value: Any) -> dict[str, Any]:
    _require(type(value) is dict, "fixed mutation result must be an exact object")
    required = {
        "schema",
        "owner",
        "owner_version",
        "backend_kind",
        "helper_protocol",
        "journal_id",
        "binding_payload_sha256",
        "receipt_payload_sha256",
        "authorization_scope_sha256",
        "workspace_binding_sha256",
        "descriptor_set_sha256",
        "project_basename_sha256",
        "outcome",
        "effect_boundary_crossed",
        "operations_completed",
        "authority",
        "result_payload_sha256",
    }
    _require(set(value) == required, "fixed mutation result fields differ")
    result = copy.deepcopy(value)
    _require(
        result["schema"] == RESULT_SCHEMA
        and result["owner"] == OWNER
        and result["owner_version"] == OWNER_VERSION
        and result["backend_kind"] == BACKEND_KIND
        and result["helper_protocol"] == HELPER.PROTOCOL,
        "fixed mutation result constants differ",
    )
    journal = validate_durable_journal_seam({
        "schema": "auto-g16-direct-durable-journal-claim-seam/1",
        "journal_id": result["journal_id"],
        "binding_payload_sha256": result["binding_payload_sha256"],
        "receipt_payload_sha256": result["receipt_payload_sha256"],
        "authorization_scope_sha256": result["authorization_scope_sha256"],
        "workspace_binding_sha256": result["workspace_binding_sha256"],
        "descriptor_set_sha256": result["descriptor_set_sha256"],
        "outcome": "started",
        "authorizes_effect": False,
    })
    del journal
    _sha(result["project_basename_sha256"], "fixed mutation project hash")
    _sha(result["result_payload_sha256"], "fixed mutation result hash")
    outcome = result["outcome"]
    _require(
        type(outcome) is str
        and outcome in {ZERO_EFFECT_TERMINAL, OUTCOME_UNCERTAIN, COMPLETED},
        "fixed mutation outcome differs",
    )
    crossed = result["effect_boundary_crossed"]
    _require(type(crossed) is bool, "fixed mutation effect marker differs")
    operations = result["operations_completed"]
    _require(
        type(operations) is list
        and all(type(item) is str for item in operations)
        and tuple(operations) in {(), OPERATIONS[:1], OPERATIONS},
        "fixed mutation operation prefix differs",
    )
    if outcome == ZERO_EFFECT_TERMINAL:
        _require(crossed is False and operations == [], "zero-effect result differs")
    elif outcome == COMPLETED:
        _require(crossed is True and tuple(operations) == OPERATIONS, "completed result differs")
    else:
        _require(crossed is True, "uncertain result must cross the effect boundary")
    _require(result["authority"] == _authority(outcome), "fixed mutation authority differs")
    projection = copy.deepcopy(result)
    projection["result_payload_sha256"] = ""
    _require(
        hmac.compare_digest(result["result_payload_sha256"], digest(projection)),
        "fixed mutation result hash differs",
    )
    return result


def _stable_source(path: Path) -> _SourceSnapshot:
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
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    _require(
        stat.S_ISREG(before.st_mode)
        and identity
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        "fixed mutation source changed during capture",
    )
    return _SourceSnapshot(path, identity, hashlib.sha256(b"".join(chunks)).hexdigest())


def _open_bound_helper_source(snapshot: _SourceSnapshot) -> int:
    descriptor = os.open(
        snapshot.path,
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
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        _require(
            stat.S_ISREG(before.st_mode)
            and identity == snapshot.identity
            and identity
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and hashlib.sha256(b"".join(chunks)).hexdigest() == snapshot.sha256,
            "fixed helper source descriptor differs",
        )
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _request_from_capability(
    capability: ROOT.SingleUseWorkspaceDescriptorCapability,
    journal_seam: DurableJournalSeamDocument,
) -> tuple[bytes, tuple[int, ...], str]:
    ROOT._assert_owner_binding()
    _require(
        type(capability) is ROOT.SingleUseWorkspaceDescriptorCapability,
        "exact W1 direct-root capability is required",
    )
    ROOT.SingleUseWorkspaceDescriptorCapability.assert_current(capability)
    descriptor_set = capability._descriptor_set
    _require(
        descriptor_set._mode == "posix_nofollow"
        and type(descriptor_set._opaque_handles) is tuple
        and all(type(item) is int for item in descriptor_set._opaque_handles),
        "fixed helper requires W1 retained POSIX descriptors",
    )
    receipt = ROOT.validate_fresh_root_observation_receipt(capability.portable_receipt())
    authorization = ROOT.validate_direct_execution_authorization(
        json.loads(capability._authorization_bytes)
    )
    project = authorization["workspace"]["project"]
    _require(
        receipt["observed_root"]["project"] == project
        and receipt["observed_root"]["workspace_binding_sha256"]
        == authorization["workspace"]["workspace_binding_sha256"]
        and receipt["observed_root"]["descriptor_set_sha256"]
        == descriptor_set.descriptor_set_sha256,
        "W1 project or descriptor binding differs",
    )
    _require(
        authorization["live_ready"] is False
        and receipt["authority"]["portable_receipt_authorizes_effect"] is False
        and receipt["authority"]["descriptor_relative_operations_required"] is True
        and receipt["authority"]["path_reopen_allowed"] is False
        and receipt["authority"]["automatic_retry"] is False,
        "W1 non-authority or descriptor policy differs",
    )
    expected_seam = {
        "receipt_payload_sha256": receipt["receipt_payload_sha256"],
        "authorization_scope_sha256": authorization["scope"]["authorization_scope_sha256"],
        "workspace_binding_sha256": authorization["workspace"]["workspace_binding_sha256"],
        "descriptor_set_sha256": descriptor_set.descriptor_set_sha256,
    }
    _require(
        all(journal_seam[field] == expected for field, expected in expected_seam.items()),
        "durable journal seam does not bind the W1 capability",
    )
    request = {
        "protocol": HELPER.PROTOCOL,
        "operation_set": list(OPERATIONS),
        "project_basename": project,
        "scratch_label": ROOT.SCRATCH_COMPONENT,
        "component_names": list(descriptor_set._component_names),
        "component_identities": [list(item) for item in descriptor_set._component_identities],
        "descriptor_count": len(descriptor_set._opaque_handles),
        **expected_seam,
    }
    return canonical_bytes(request), descriptor_set._opaque_handles, project


def _recv_frame(control: socket.socket) -> dict[str, Any]:
    header = b""
    while len(header) < 4:
        chunk = control.recv(4 - len(header))
        _require(bool(chunk), "helper response closed during its header")
        header += chunk
    size = struct.unpack("!I", header)[0]
    _require(0 < size <= HELPER.MAX_FRAME_BYTES, "helper response frame size differs")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = control.recv(remaining)
        _require(bool(chunk), "helper response closed during its body")
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    _require(0 < len(raw) <= HELPER.MAX_FRAME_BYTES, "helper response frame size differs")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectRootFixedMutationError("helper response is not strict JSON") from exc
    _require(type(value) is dict and canonical_bytes(value) == raw, "helper response is not canonical")
    return value


def _send_frame(control: socket.socket, value: dict[str, Any]) -> None:
    payload = canonical_bytes(value)
    _require(len(payload) <= HELPER.MAX_FRAME_BYTES, "helper command is oversized")
    control.sendall(struct.pack("!I", len(payload)) + payload)


def _send_request_with_descriptors(
    control: socket.socket,
    request: bytes,
    descriptors: tuple[int, ...],
) -> None:
    _require(0 < len(request) <= HELPER.MAX_FRAME_BYTES, "helper request is oversized")
    rights = array.array("i", descriptors)
    header = struct.pack("!I", len(request))
    sent = control.sendmsg(
        [header],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
    )
    _require(0 < sent <= len(header), "fixed helper request header was not sent")
    if sent < len(header):
        control.sendall(header[sent:])
    control.sendall(request)


def _terminate_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=FIXED_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _result(
    *,
    seam: DurableJournalSeamDocument,
    project: str,
    outcome: str,
    effect_boundary_crossed: bool,
    operations_completed: tuple[str, ...],
) -> dict[str, Any]:
    document = {
        "schema": RESULT_SCHEMA,
        "owner": OWNER,
        "owner_version": OWNER_VERSION,
        "backend_kind": BACKEND_KIND,
        "helper_protocol": HELPER.PROTOCOL,
        "journal_id": seam["journal_id"],
        "binding_payload_sha256": seam["binding_payload_sha256"],
        "receipt_payload_sha256": seam["receipt_payload_sha256"],
        "authorization_scope_sha256": seam["authorization_scope_sha256"],
        "workspace_binding_sha256": seam["workspace_binding_sha256"],
        "descriptor_set_sha256": seam["descriptor_set_sha256"],
        "project_basename_sha256": hashlib.sha256(project.encode("utf-8")).hexdigest(),
        "outcome": outcome,
        "effect_boundary_crossed": effect_boundary_crossed,
        "operations_completed": list(operations_completed),
        "authority": _authority(outcome),
        "result_payload_sha256": "",
    }
    return validate_fixed_mutation_result(_finalize(document))


class SingleUseDirectRootFixedMutation:
    __slots__ = (
        "_capability",
        "_journal_seam",
        "_lock",
        "_outcome",
        "_project",
        "_seal",
    )

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fixed mutation transactions are owner-issued only")

    def outcome(self) -> str:
        with self._lock:
            return self._outcome

    def apply_once(self) -> dict[str, Any]:
        with self._lock:
            _require(
                type(self) is SingleUseDirectRootFixedMutation
                and self._seal is _TRANSACTION_TOKEN
                and self._outcome == READY,
                "fixed mutation transaction is already consumed or terminal",
            )
            try:
                _assert_module_binding()
            except BaseException:
                self._outcome = ZERO_EFFECT_TERMINAL
                raise
            return _MODULE_BINDING.execute(self)


class DirectRootFixedMutationOwner:
    __slots__ = ("_issued", "_lock", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("fixed mutation owners use the fixed backend factory")

    @classmethod
    def for_posix_backend(cls) -> "DirectRootFixedMutationOwner":
        _assert_module_binding()
        _require(cls is DirectRootFixedMutationOwner, "fixed mutation owner class differs")
        value = object.__new__(cls)
        value._issued = False
        value._lock = threading.Lock()
        value._seal = _OWNER_TOKEN
        return value

    def issue_once(
        self,
        *,
        root_capability: ROOT.SingleUseWorkspaceDescriptorCapability,
        durable_journal_seam: DurableJournalSeamDocument,
    ) -> SingleUseDirectRootFixedMutation:
        _assert_module_binding()
        with self._lock:
            _require(
                type(self) is DirectRootFixedMutationOwner
                and self._seal is _OWNER_TOKEN
                and self._issued is False,
                "fixed mutation owner is foreign or already used",
            )
            seam = validate_durable_journal_seam(durable_journal_seam)
            _request, _descriptors, project = _request_from_capability(
                root_capability,
                seam,
            )
            transaction = object.__new__(SingleUseDirectRootFixedMutation)
            transaction._capability = root_capability
            transaction._journal_seam = seam
            transaction._lock = threading.Lock()
            transaction._outcome = READY
            transaction._project = project
            transaction._seal = _TRANSACTION_TOKEN
            self._issued = True
            return transaction


_OWNER_TOKEN = object()
_TRANSACTION_TOKEN = object()


def _build_executor() -> Any:
    owner_require = _require
    popen = subprocess.Popen
    socketpair = socket.socketpair
    source_opener = _open_bound_helper_source
    helper_source = _stable_source(Path(HELPER.__file__).resolve())
    python_executable = Path(sys.executable).resolve()
    helper_child_flag = HELPER.CHILD_FLAG
    helper_protocol = HELPER.PROTOCOL
    helper_ready = copy.deepcopy(HELPER.READY)
    helper_validated = copy.deepcopy(HELPER.VALIDATED)
    helper_project_created = copy.deepcopy(HELPER.PROJECT_CREATED)
    helper_completed = copy.deepcopy(HELPER.COMPLETED)
    timeout = FIXED_TIMEOUT_SECONDS
    operations = OPERATIONS
    devnull = subprocess.DEVNULL
    close_fd = os.close
    seam_validator = validate_durable_journal_seam
    request_builder = _request_from_capability
    response_reader = _recv_frame
    command_sender = _send_frame
    request_sender = _send_request_with_descriptors
    child_terminator = _terminate_child
    result_builder = _result
    root_assert = ROOT.SingleUseWorkspaceDescriptorCapability.assert_current
    root_consume = ROOT.SingleUseWorkspaceDescriptorCapability.consume_once
    root_lease_assert = ROOT.ConsumedWorkspaceDescriptorLease.assert_owner_sealed
    root_close = ROOT._close_descriptor_bundle_once

    def execute(transaction: SingleUseDirectRootFixedMutation) -> dict[str, Any]:
        seam = seam_validator(transaction._journal_seam)
        project = transaction._project
        request = b""
        descriptors: tuple[int, ...] = ()
        control_parent: socket.socket | None = None
        control_child: socket.socket | None = None
        process: subprocess.Popen[bytes] | None = None
        helper_source_fd = -1
        lease: ROOT.ConsumedWorkspaceDescriptorLease | None = None
        effect_boundary_crossed = False
        operations_completed: tuple[str, ...] = ()
        try:
            _assert_module_binding()
            request, descriptors, current_project = request_builder(
                transaction._capability,
                seam,
            )
            owner_require(current_project == project, "fixed project binding changed")
            control_parent, control_child = socketpair(
                socket.AF_UNIX,
                socket.SOCK_STREAM,
            )
            control_parent.settimeout(timeout)
            child_fd = control_child.fileno()
            helper_source_fd = source_opener(helper_source)
            process = popen(
                [
                    str(python_executable),
                    f"/dev/fd/{helper_source_fd}",
                    helper_child_flag,
                    str(child_fd),
                    str(helper_source_fd),
                ],
                close_fds=True,
                pass_fds=(child_fd, helper_source_fd),
                stdin=devnull,
                stdout=devnull,
                stderr=devnull,
                env={},
                cwd="/",
            )
            close_fd(helper_source_fd)
            helper_source_fd = -1
            control_child.close()
            control_child = None
            owner_require(response_reader(control_parent) == helper_ready, "fixed helper did not exec cleanly")
            root_assert(transaction._capability)
            lease = root_consume(transaction._capability)
            root_lease_assert(lease)
            owner_require(
                lease._descriptor_set is transaction._capability._descriptor_set
                and lease._descriptor_set._opaque_handles is descriptors,
                "consumed W1 descriptor lease differs",
            )
            request_sender(control_parent, request, descriptors)
            response = response_reader(control_parent)
            owner_require(response == helper_validated, "fixed helper rejected before effect")
            effect_boundary_crossed = True
            transaction._outcome = OUTCOME_UNCERTAIN
            command_sender(
                control_parent,
                {"protocol": helper_protocol, "command": "begin_project"},
            )
            response = response_reader(control_parent)
            owner_require(response == helper_project_created, "fixed helper project outcome is uncertain")
            operations_completed = operations[:1]
            command_sender(
                control_parent,
                {"protocol": helper_protocol, "command": "continue_scratch"},
            )
            response = response_reader(control_parent)
            owner_require(response == helper_completed, "fixed helper scratch outcome is uncertain")
            operations_completed = operations
            exit_code = process.wait(timeout=timeout)
            owner_require(exit_code == 0, "fixed helper exit status differs")
            transaction._outcome = COMPLETED
            return result_builder(
                seam=seam,
                project=project,
                outcome=COMPLETED,
                effect_boundary_crossed=True,
                operations_completed=operations,
            )
        except BaseException:
            if effect_boundary_crossed:
                transaction._outcome = OUTCOME_UNCERTAIN
                return result_builder(
                    seam=seam,
                    project=project,
                    outcome=OUTCOME_UNCERTAIN,
                    effect_boundary_crossed=True,
                    operations_completed=operations_completed,
                )
            transaction._outcome = ZERO_EFFECT_TERMINAL
            return result_builder(
                seam=seam,
                project=project,
                outcome=ZERO_EFFECT_TERMINAL,
                effect_boundary_crossed=False,
                operations_completed=(),
            )
        finally:
            if process is not None:
                child_terminator(process)
            if control_child is not None:
                control_child.close()
            if control_parent is not None:
                control_parent.close()
            if helper_source_fd >= 0:
                close_fd(helper_source_fd)
            if lease is not None:
                bundle = lease._descriptor_set._descriptor_bundle
                if bundle is not None:
                    root_close(bundle, owner="capability")

    return (
        execute,
        popen,
        socketpair,
        seam_validator,
        request_builder,
        response_reader,
        command_sender,
        request_sender,
        child_terminator,
        result_builder,
        root_assert,
        root_consume,
        root_lease_assert,
        root_close,
        source_opener,
        helper_source,
        python_executable,
    )


(
    _EXECUTE,
    _FROZEN_POPEN,
    _FROZEN_SOCKETPAIR,
    _FROZEN_SEAM_VALIDATOR,
    _FROZEN_REQUEST_BUILDER,
    _FROZEN_RESPONSE_READER,
    _FROZEN_COMMAND_SENDER,
    _FROZEN_REQUEST_SENDER,
    _FROZEN_CHILD_TERMINATOR,
    _FROZEN_RESULT_BUILDER,
    _FROZEN_ROOT_ASSERT,
    _FROZEN_ROOT_CONSUME,
    _FROZEN_ROOT_LEASE_ASSERT,
    _FROZEN_ROOT_CLOSE,
    _FROZEN_SOURCE_OPENER,
    _FROZEN_HELPER_SOURCE,
    _FROZEN_PYTHON_EXECUTABLE,
) = _build_executor()
del _build_executor


@dataclass(frozen=True, slots=True)
class _ModuleBinding:
    module: types.ModuleType
    source: _SourceSnapshot
    stable_source: Any
    helper_module: types.ModuleType
    helper_source: _SourceSnapshot
    helper_protocol: str
    helper_child_flag: str
    helper_ready: dict[str, Any]
    helper_validated: dict[str, Any]
    helper_project_created: dict[str, Any]
    helper_completed: dict[str, Any]
    root_module: types.ModuleType
    python_executable: Path
    execute: Any
    popen: Any
    socketpair: Any
    source_opener: Any
    seam_validator: Any
    request_builder: Any
    response_reader: Any
    command_sender: Any
    request_sender: Any
    child_terminator: Any
    result_builder: Any
    root_assert: Any
    root_consume: Any
    root_close: Any
    root_assert_binding: Any
    root_validate_receipt: Any
    root_validate_authorization: Any
    root_lease_assert: Any
    root_scratch_label: str
    transaction_type: type
    owner_type: type
    apply_descriptor: Any
    issue_descriptor: Any


def _capture_module_binding() -> _ModuleBinding:
    _require(__name__ == MODULE_NAME, "fixed mutation consumer must use its canonical module name")
    module = sys.modules.get(MODULE_NAME)
    _require(isinstance(module, types.ModuleType), "fixed mutation consumer module is unavailable")
    python_executable = Path(sys.executable).resolve()
    _require(python_executable.is_file(), "fixed helper Python executable is unavailable")
    return _ModuleBinding(
        module=module,
        source=_stable_source(Path(__file__).resolve()),
        stable_source=_stable_source,
        helper_module=HELPER,
        helper_source=_FROZEN_HELPER_SOURCE,
        helper_protocol=HELPER.PROTOCOL,
        helper_child_flag=HELPER.CHILD_FLAG,
        helper_ready=copy.deepcopy(HELPER.READY),
        helper_validated=copy.deepcopy(HELPER.VALIDATED),
        helper_project_created=copy.deepcopy(HELPER.PROJECT_CREATED),
        helper_completed=copy.deepcopy(HELPER.COMPLETED),
        root_module=ROOT,
        python_executable=_FROZEN_PYTHON_EXECUTABLE,
        execute=_EXECUTE,
        popen=_FROZEN_POPEN,
        socketpair=_FROZEN_SOCKETPAIR,
        source_opener=_FROZEN_SOURCE_OPENER,
        seam_validator=_FROZEN_SEAM_VALIDATOR,
        request_builder=_FROZEN_REQUEST_BUILDER,
        response_reader=_FROZEN_RESPONSE_READER,
        command_sender=_FROZEN_COMMAND_SENDER,
        request_sender=_FROZEN_REQUEST_SENDER,
        child_terminator=_FROZEN_CHILD_TERMINATOR,
        result_builder=_FROZEN_RESULT_BUILDER,
        root_assert=_FROZEN_ROOT_ASSERT,
        root_consume=_FROZEN_ROOT_CONSUME,
        root_close=_FROZEN_ROOT_CLOSE,
        root_assert_binding=ROOT._assert_owner_binding,
        root_validate_receipt=ROOT.validate_fresh_root_observation_receipt,
        root_validate_authorization=ROOT.validate_direct_execution_authorization,
        root_lease_assert=_FROZEN_ROOT_LEASE_ASSERT,
        root_scratch_label=ROOT.SCRATCH_COMPONENT,
        transaction_type=SingleUseDirectRootFixedMutation,
        owner_type=DirectRootFixedMutationOwner,
        apply_descriptor=SingleUseDirectRootFixedMutation.__dict__["apply_once"],
        issue_descriptor=DirectRootFixedMutationOwner.__dict__["issue_once"],
    )


def _assert_module_binding() -> None:
    binding = _MODULE_BINDING
    _require(
        isinstance(binding, _ModuleBinding)
        and sys.modules.get(MODULE_NAME) is binding.module
        and sys.modules.get(HELPER.__name__) is binding.helper_module
        and sys.modules.get(ROOT.__name__) is binding.root_module
        and _stable_source is binding.stable_source
        and _stable_source(binding.source.path) == binding.source
        and _stable_source(binding.helper_source.path) == binding.helper_source
        and HELPER.PROTOCOL == binding.helper_protocol
        and HELPER.CHILD_FLAG == binding.helper_child_flag
        and HELPER.READY == binding.helper_ready
        and HELPER.VALIDATED == binding.helper_validated
        and HELPER.PROJECT_CREATED == binding.helper_project_created
        and HELPER.COMPLETED == binding.helper_completed
        and subprocess.Popen is binding.popen
        and socket.socketpair is binding.socketpair
        and _open_bound_helper_source is binding.source_opener
        and validate_durable_journal_seam is binding.seam_validator
        and _request_from_capability is binding.request_builder
        and _recv_frame is binding.response_reader
        and _send_frame is binding.command_sender
        and _send_request_with_descriptors is binding.request_sender
        and _terminate_child is binding.child_terminator
        and _result is binding.result_builder
        and ROOT.SingleUseWorkspaceDescriptorCapability.assert_current is binding.root_assert
        and ROOT.SingleUseWorkspaceDescriptorCapability.consume_once is binding.root_consume
        and ROOT._close_descriptor_bundle_once is binding.root_close
        and ROOT._assert_owner_binding is binding.root_assert_binding
        and ROOT.validate_fresh_root_observation_receipt is binding.root_validate_receipt
        and ROOT.validate_direct_execution_authorization is binding.root_validate_authorization
        and ROOT.ConsumedWorkspaceDescriptorLease.assert_owner_sealed is binding.root_lease_assert
        and ROOT.SCRATCH_COMPONENT == binding.root_scratch_label
        and SingleUseDirectRootFixedMutation is binding.transaction_type
        and DirectRootFixedMutationOwner is binding.owner_type
        and SingleUseDirectRootFixedMutation.__dict__.get("apply_once") is binding.apply_descriptor
        and DirectRootFixedMutationOwner.__dict__.get("issue_once") is binding.issue_descriptor,
        "fixed mutation module, helper, function, or source binding differs",
    )
    ROOT._assert_owner_binding()


_MODULE_BINDING: _ModuleBinding | None = None
_MODULE_BINDING = _capture_module_binding()


__all__ = [
    "COMPLETED",
    "DirectRootFixedMutationError",
    "DirectRootFixedMutationOwner",
    "DurableJournalSeamDocument",
    "OUTCOME_UNCERTAIN",
    "RESULT_SCHEMA",
    "SingleUseDirectRootFixedMutation",
    "ZERO_EFFECT_TERMINAL",
    "validate_durable_journal_seam",
    "validate_fixed_mutation_result",
]
