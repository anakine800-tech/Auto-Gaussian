"""Private successor adapter over the reviewed, bounded RTwin process owner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
import sys
from threading import Event, RLock, Thread
import time
from types import MappingProxyType
from contextvars import ContextVar

from auto_g16.execution.models import ResolvedServerProfile, ServerProfile
from auto_g16.execution.program import ProgramExecutionSnapshot
from auto_g16.execution.project_provisioning import _ProjectAttestor

from . import _bridge, _driver, program
from ._canonical import TransportBoundaryError, canonical_json_bytes, strict_canonical_json

_COLLECTION_WIRE_OWNER = ContextVar("collection_wire_owner", default=None)


def _emit_collection_transfer_progress(event: Mapping[str, object]) -> None:
    line = canonical_json_bytes(dict(event)).decode("utf-8")
    sys.stderr.write(f"AUTO_G16_TRANSFER_PROGRESS {line}\n")
    sys.stderr.flush()


class _CollectionTransferProgress:
    """Best-effort diagnostics that never run on the transport I/O thread."""

    def __init__(
        self, operation: str, *, interval_seconds: float = 10.0,
        emit: object = _emit_collection_transfer_progress,
    ) -> None:
        if operation != "FETCH_EXACT_FILE" or not callable(emit):
            raise TransportBoundaryError("collection progress configuration is invalid")
        self._operation = operation
        self._interval = interval_seconds
        self._emit = emit
        self._started = time.monotonic()
        self._finished = Event()
        self._final: Mapping[str, object] | None = None
        Thread(target=self._run, name="auto-g16-collection-progress", daemon=True).start()

    def _event(self, phase: str, **fields: object) -> Mapping[str, object]:
        return {
            "schema": "auto-g16-v31-transfer-progress/1",
            "operation": self._operation,
            "phase": phase,
            "elapsed_milliseconds": max(0, int((time.monotonic() - self._started) * 1000)),
            **fields,
        }

    def _send(self, event: Mapping[str, object]) -> None:
        try:
            self._emit(event)
        except Exception:
            # Diagnostics are not an effect owner and cannot alter transport.
            pass

    def _run(self) -> None:
        self._send(self._event("started"))
        while not self._finished.wait(self._interval):
            self._send(self._event("waiting"))
        final = self._final
        if final is not None:
            self._send(self._event("finished", **dict(final)))

    def finish(
        self, *, status: str, returncode: int | None,
        stdout_bytes: int, stderr_bytes: int, eof_stdout: bool, eof_stderr: bool,
    ) -> None:
        self._final = MappingProxyType({
            "status": status,
            "returncode": returncode,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "eof_stdout": eof_stdout,
            "eof_stderr": eof_stderr,
        })
        self._finished.set()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _closed_copy(value: Mapping[str, object]) -> Mapping[str, object]:
    from ._canonical import strict_canonical_json
    return strict_canonical_json(canonical_json_bytes(_plain(value)), "successor wire")


@dataclass(frozen=True, slots=True)
class _ProgramRTWinInvocation:
    operation: _driver._Operation
    authority: _driver._DeploymentAuthority
    current_profile: ServerProfile
    request: Mapping[str, object]
    scope_identity: str


def _prepare_program_invocation(
    scope: object, invocation: _ProgramRTWinInvocation,
) -> tuple[tuple[str, ...], bytes]:
    """Reclose current deployment before reaching the sole subprocess call."""
    if type(invocation) is not _ProgramRTWinInvocation:
        raise TransportBoundaryError("exact successor invocation is required")
    name = invocation.operation.name
    expected_operation = _project_operation(name) if name in {"OBSERVE_PROJECT", "PROVISION_PROJECT"} else _driver._operation(name)
    if invocation.operation != expected_operation:
        raise TransportBoundaryError("successor operation limits differ from the reviewed table")
    if type(scope) is ProgramExecutionSnapshot:
        scope.assert_identity_closed()
        profile = scope.resolved_server_profile
        scope_id = scope.program_execution_snapshot_id
    elif type(scope) is ResolvedServerProfile:
        scope.assert_identity_closed()
        profile = scope
        scope_id = scope.resolved_server_profile_id
    else:
        raise TransportBoundaryError("successor scope must be identity-closed")
    authority = _driver._resolve_closed_profile_authority(
        profile, invocation.current_profile, scope_id, successor=True,
    )
    if authority != invocation.authority or scope_id != invocation.scope_identity:
        raise TransportBoundaryError("successor deployment changed before subprocess")
    if not authority.resource_dialect.live_capable or type(authority.ssh_effect) is not _driver._MacProxyJumpEffectAuthority:
        raise TransportBoundaryError("successor requires the qualified RTwin ProxyJump deployment")
    if type(scope) is ProgramExecutionSnapshot and scope.program_execution_spec.adapter_contract_version == 3:
        collection = _COLLECTION_WIRE_OWNER.get()
        if collection is None:
            fixed = _read_fixed_publisher_deployment(authority, scope)
            fixed.close()
        else:
            owner, owned_invocation = collection
            if type(owner) is not _RTWinProgramEffectDriver or not owner._collection_only or owner._snapshot is not scope or owned_invocation is not invocation or name not in owner._read_operations():
                raise _publisher_failure("wire collection owner differs")
            if type(owner._publisher) is not _CollectionDeploymentRead:
                raise _publisher_failure("wire collection installation missing")
            owner._publisher.assert_current()
    request = _closed_copy(invocation.request)
    program._exact_keys(request, {"protocol", "operation", "binding", "payload"}, "successor wire request")
    if request.get("protocol") != _bridge._PROGRAM_BOOTSTRAP_PROTOCOL or request.get("operation") != invocation.operation.name:
        raise TransportBoundaryError("successor wire protocol/operation drifted")
    _assert_wire_scope(scope, invocation.scope_identity, request)
    source = _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES
    if (sha256(source).hexdigest(), len(source)) != (authority.bootstrap_source_sha256, authority.bootstrap_source_size_bytes):
        raise TransportBoundaryError("successor bootstrap bytes drifted")
    if name == "RECONCILE_SUBMISSION" and request["payload"]["request_payload"].get("schema") == "v31-exact-observed-job-reconciliation-request/1":
        from . import _submission_recovery as recovery
        collection = _COLLECTION_WIRE_OWNER.get()
        if collection is None or not collection[0]._recovery_only:
            raise _publisher_failure("exact reconciliation requires fixed recovery owner")
        source = recovery.source_bytes()
        reviewed = collection[0]._publisher.document["reconciliation"]["probe_source"]
        if reviewed != {"sha256": sha256(source).hexdigest(), "size_bytes": len(source)}:
            raise _publisher_failure("read-only recovery source differs")
    frame = _bridge._encode_frame(request)
    if len(frame) > invocation.operation.stdin_cap:
        raise TransportBoundaryError("successor request exceeds operation cap")
    # Only these source-owned bootstrap bytes may contain literal newlines.
    quoted_source = "'" + source.decode("utf-8").replace("'", "'\"'\"'") + "'"
    roots = authority.manifest.trust_roots
    if roots["server_remote_shell"].shell_grammar != "posix-sh-v1":
        raise TransportBoundaryError("successor server shell grammar is unsupported")
    tokens = (roots["server_python"].path, "-I", "-S", "-B", "-c")
    import base64
    server_command = " ".join((*(_bridge._posix_quote_v1(token) for token in tokens), quoted_source, _bridge._posix_quote_v1(base64.b64encode(authority.manifest.raw_bytes).decode("ascii"))))
    effect = authority.ssh_effect
    return (roots["mac_ssh"].path, "-F", effect.config.path, "--", effect.final_target.alias, server_command), frame


def _assert_wire_scope(scope: object, scope_id: str, request: Mapping[str, object]) -> None:
    binding = request["binding"]
    payload = request["payload"]
    name = request["operation"]
    if not isinstance(binding, Mapping) or not isinstance(payload, Mapping):
        raise TransportBoundaryError("successor wire binding/payload is malformed")
    if type(scope) is ResolvedServerProfile:
        from auto_g16.execution.project_provisioning import _validate_remote_target
        path = _validate_remote_target(scope, binding.get("project_directory"))
        expected = _wire_binding(scope, scope_id, path)
        if name == "PROVISION_PROJECT":
            expected["parent_physical_identity"] = _directory_token(binding.get("parent_physical_identity"), path.rsplit("/", 1)[0])
            program._exact_keys(payload, {"provision_intent_id"}, "Project intent payload")
            program._text(payload["provision_intent_id"], "Project provision intent")
        elif name == "OBSERVE_PROJECT":
            program._exact_keys(payload, set(), "Project observation payload")
        else:
            raise TransportBoundaryError("Project scope cannot perform Attempt operations")
    else:
        if name not in program._OPERATIONS:
            raise TransportBoundaryError("Attempt scope cannot perform Project operations")
        project = scope.project_physical_binding
        expected = _wire_binding(scope.resolved_server_profile, scope_id, project.remote_project_dir)
        workspace_token = None if name == "ALLOCATE_WORKSPACE" else _directory_token(binding.get("workspace_physical_token"), scope.workspace_binding.remote_attempt_dir)
        expected.update(parent_physical_identity=project.parent_physical_identity, project_physical_identity=project.project_physical_identity, attempt_id=scope.attempt_id, program_execution_snapshot_id=scope.program_execution_snapshot_id, effect_intent_id=scope.effect_intent_id, remote_workspace=scope.workspace_binding.remote_attempt_dir, workspace_physical_token=workspace_token)
        recovering = name == "RECONCILE_SUBMISSION" and payload.get("request_payload", {}).get("schema") == "v31-exact-observed-job-reconciliation-request/1"
        program._exact_keys(payload, {"request_payload", "executable", "resources", "staged"} | ({"recovery_identity"} if recovering else set()), "successor wire payload")
        if recovering:
            owner = _COLLECTION_WIRE_OWNER.get()
            if owner is None or not owner[0]._recovery_only:
                raise _publisher_failure("recovery wire owner missing")
            marker = canonical_json_bytes({"program_execution_snapshot_id": scope.program_execution_snapshot_id, "effect_intent_id": scope.effect_intent_id})
            expected_identity = {"host": owner[0]._publisher.document["reconciliation"]["host"], "marker_sha256": sha256(marker).hexdigest(), "marker_size": len(marker)}
            if payload["recovery_identity"] != expected_identity:
                raise _publisher_failure("recovery wire identity differs")
            document = owner[0]._publisher.document
            exact_payload = {"schema": "v31-exact-observed-job-reconciliation-request/1",
                             "submit_receipt_id": document["reconciliation"]["submit_receipt_id"],
                             "observed_job_id": document["original"]["job_id"],
                             "continuation_sha256": owner[0]._publisher.installation.continuation.sha256}
            if payload["request_payload"] != exact_payload or document["reconciliation"]["prior_recovery_authority"] is not None:
                raise _publisher_failure("recovery wire differs from first exact continuation")
        executable = scope.program_execution_spec.invocation["executable_identity"]
        resources = scope.resolved_resource_request
        if payload["executable"] != {"path": executable["absolute_path"], "size_bytes": executable["size_bytes"], "sha256": executable["sha256"]} or payload["resources"] != {"cores": resources.cores, "memory_mb": resources.memory_mb, "walltime_seconds": resources.walltime_seconds, "queue": resources.queue}:
            raise TransportBoundaryError("successor wire runtime/resources differ from snapshot")
        original = dict(payload["request_payload"])
        content = original.pop("content_base64", None) if name == "STAGE_EXACT_FILE" else None
        if name == "SUBMIT_QSUB_ONCE" and isinstance(original.get("program_input_artifact_authority_ids"), list):
            original["program_input_artifact_authority_ids"] = tuple(original["program_input_artifact_authority_ids"])
        if name == "SUBMIT_QSUB_ONCE" and isinstance(original.get("startup_payload_artifact_authority_ids"), list):
            original["startup_payload_artifact_authority_ids"] = tuple(original["startup_payload_artifact_authority_ids"])
        program._validate_operation_payload(name, original)
        stages = [
            {"artifact_kind": item["logical_role"] if kind == "scheduler-script" else kind, **{key: item[key] for key in ("logical_role", "portable_name", "format", "sha256", "size_bytes")}}
            for kind, declarations in (("program-input", scope.program_execution_spec.exact_inputs), ("scheduler-script", scope.scheduler_artifacts))
            for item in declarations
        ]
        if name == "STAGE_EXACT_FILE":
            if original not in stages or not isinstance(content, str) or len(content) > 4 * ((134217728 + 2) // 3):
                raise TransportBoundaryError("successor stage is not snapshot-declared or exceeds cap")
            data = _driver._canonical_b64(content)
            if len(data) != original["size_bytes"] or sha256(data).hexdigest() != original["sha256"]:
                raise TransportBoundaryError("successor wire stage bytes differ from declaration")
        if name == "SUBMIT_QSUB_ONCE" and (("startup_payload_artifact_authority_ids" in original) != (len(scope.scheduler_artifacts) == 2)):
            raise TransportBoundaryError("successor submit startup authority tuple differs")
        if name == "SUBMIT_QSUB_ONCE" and original["scheduler_portable_name"] != scope.scheduler_artifacts[0]["portable_name"]:
            raise TransportBoundaryError("successor wire scheduler differs from snapshot")
        if name in {"STAT_EXACT_FILE", "FETCH_EXACT_FILE"}:
            outputs = (*scope.program_execution_spec.required_outputs, *scope.program_execution_spec.optional_outputs)
            if scope.program_execution_spec.adapter_contract_version == 3:
                outputs = (*outputs, {"logical_role": "completion-receipt", "portable_name": "v31-completion.json", "format": "json", "max_size_bytes": 65536})
            matched = [item for item in outputs if all(original[key] == item[key] for key in ("logical_role", "portable_name", "format"))]
            if len(matched) != 1 or name == "FETCH_EXACT_FILE" and original["expected_size_bytes"] > matched[0]["max_size_bytes"]:
                raise TransportBoundaryError("successor wire output exceeds exact declaration")
        if not isinstance(payload["staged"], list):
            raise TransportBoundaryError("successor wire staged authority is not a closed list")
        seen = []
        for item in payload["staged"]:
            program._exact_keys(item, program._STAGE_FIELDS | {"artifact_physical_token"}, "wire staged authority")
            declaration = {key: item[key] for key in program._STAGE_FIELDS}
            if declaration not in stages or declaration in seen:
                raise TransportBoundaryError("wire staged authority is undeclared or duplicated")
            program._text(item["artifact_physical_token"], "wire artifact token")
            seen.append(declaration)
        if name == "SUBMIT_QSUB_ONCE" and len(seen) != len(stages):
            raise TransportBoundaryError("wire submission lacks exact staged authority")
    if binding != expected:
        raise TransportBoundaryError("successor wire target differs from its exact scope")


def _project_operation(name: str) -> _driver._Operation:
    if name not in {"OBSERVE_PROJECT", "PROVISION_PROJECT"}:
        raise TransportBoundaryError("unknown private Project operation")
    # The same reviewed control-message bounds, independently named operations.
    reference = _driver._operation("ALLOCATE_WORKSPACE")
    return _driver._Operation(name, name.lower().replace("_", "-"), reference.timeout_seconds, reference.stdin_cap, reference.stdout_cap, reference.stderr_cap)


def _wire_call(scope: object, invocation: _ProgramRTWinInvocation) -> Mapping[str, object]:
    progress = _CollectionTransferProgress(invocation.operation.name) if _COLLECTION_WIRE_OWNER.get() is not None and invocation.operation.name == "FETCH_EXACT_FILE" else None
    try:
        stdout, stderr, code, state, eofout, eoferr = _driver._SubprocessRTWinDriver()._run(scope, invocation)
    except BaseException:
        if progress is not None:
            progress.finish(status="interrupted", returncode=None, stdout_bytes=0, stderr_bytes=0, eof_stdout=False, eof_stderr=False)
        raise
    if progress is not None:
        progress.finish(status=state, returncode=code, stdout_bytes=len(stdout), stderr_bytes=len(stderr), eof_stdout=eofout, eof_stderr=eoferr)
    if state != "completed" or code != 0 or stderr or not eofout or not eoferr:
        raise program._ProgramEffectUnknown("RTwin successor completion is ambiguous")
    response = _bridge._decode_frame(stdout, cap=invocation.operation.stdout_cap, field="successor response")
    program._exact_keys(response, {"protocol", "operation", "result", "status"}, "successor response")
    if response["protocol"] != _bridge._PROGRAM_BOOTSTRAP_PROTOCOL or response["operation"] != invocation.operation.name or response["status"] != "ok" or not isinstance(response["result"], Mapping):
        raise program._ProgramEffectUnknown("RTwin successor response is not exact")
    return response["result"]


def _wire_binding(profile: ResolvedServerProfile, scope_id: str, path: str) -> dict[str, object]:
    return {
        "scope_identity": scope_id,
        "resolved_server_profile_id": profile.resolved_server_profile_id,
        "project_directory": path,
        "parent_physical_identity": None, "project_physical_identity": None,
        "attempt_id": None, "program_execution_snapshot_id": None,
        "effect_intent_id": None, "remote_workspace": None,
        "workspace_physical_token": None,
    }


def _directory_token(value: object, path: str) -> str:
    from ._canonical import strict_canonical_json
    raw = _driver._canonical_b64(value)
    if len(raw) > 4096:
        raise TransportBoundaryError("directory identity exceeds cap")
    token = strict_canonical_json(raw, "directory identity")
    if not isinstance(token, list) or len(token) != 3 or token[:2] != ["v31-directory/1", path]:
        raise TransportBoundaryError("directory identity differs from exact path")
    chain = token[2]
    if not isinstance(chain, list) or len(chain) != len(path.split("/")) or any(not isinstance(pair, list) or len(pair) != 2 or any(type(x) is not int or x < 0 for x in pair) for pair in chain):
        raise TransportBoundaryError("directory identity chain is malformed")
    return str(value)


class _RTWinProjectAttestor(_ProjectAttestor):
    """Private exact-target seam; it neither classifies nor adopts Projects."""

    def __init__(self, *, current_profile: ServerProfile, target: ResolvedServerProfile) -> None:
        self._profile = current_profile
        self._target = target
        self._authority()

    def _authority(self) -> _driver._DeploymentAuthority:
        authority = _driver._resolve_closed_profile_authority(self._target, self._profile, self._target.resolved_server_profile_id, successor=True)
        if not authority.resource_dialect.live_capable or type(authority.ssh_effect) is not _driver._MacProxyJumpEffectAuthority:
            raise TransportBoundaryError("production Project authority requires qualified ProxyJump")
        return authority

    @property
    def authority_identity(self) -> str:
        authority = self._authority()
        return program._identity("project-runtime", {"profile": self._target.resolved_server_profile_id, "manifest": authority.manifest.sha256, "bootstrap": authority.bootstrap_source_sha256})

    def _assert_current_authority(self, target: ResolvedServerProfile) -> str:
        target.assert_identity_closed()
        if target != self._target:
            raise TransportBoundaryError("Project semantic target differs from closed deployment")
        return self.authority_identity

    def _invoke(self, target: ResolvedServerProfile, path: str, operation: str, parent: str | None = None, intent: str | None = None) -> tuple[str, str, str | None]:
        from auto_g16.execution.project_provisioning import _validate_remote_target
        _validate_remote_target(target, path)
        if target != self._target:
            raise TransportBoundaryError("Project operation target differs from closed deployment")
        binding = _wire_binding(target, target.resolved_server_profile_id, path)
        binding["parent_physical_identity"] = parent
        if parent is not None:
            _directory_token(parent, path.rsplit("/", 1)[0])
        request = {"protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, "operation": operation, "binding": binding, "payload": {} if operation == "OBSERVE_PROJECT" else {"provision_intent_id": program._text(intent, "Project intent")}}
        invocation = _ProgramRTWinInvocation(_project_operation(operation), self._authority(), self._profile, _closed_copy(request), target.resolved_server_profile_id)
        result = _wire_call(target, invocation)
        program._exact_keys(result, {"state", "parent_physical_identity", "project_physical_identity"}, "Project observation")
        parent_id = _directory_token(result["parent_physical_identity"], path.rsplit("/", 1)[0])
        state = result["state"]
        if state == "ABSENT" and result["project_physical_identity"] is None and operation == "OBSERVE_PROJECT":
            return "ABSENT", parent_id, None
        if state != "EXISTING":
            raise TransportBoundaryError("Project operation returned invalid physical evidence")
        project_id = _directory_token(result["project_physical_identity"], path)
        if parent is not None and parent_id != parent:
            raise TransportBoundaryError("Project parent changed during provisioning")
        return "EXISTING", parent_id, project_id

    def _observe_current(self, target: ResolvedServerProfile, remote_project_dir: str) -> tuple[str, str, str | None]:
        return self._invoke(target, remote_project_dir, "OBSERVE_PROJECT")

    def _provision_absent(self, target: ResolvedServerProfile, remote_project_dir: str, *, parent_identity: str, intent_id: str) -> tuple[str, str]:
        _state, parent, project = self._invoke(target, remote_project_dir, "PROVISION_PROJECT", parent_identity, intent_id)
        if project is None:
            raise TransportBoundaryError("provisioning returned no Project identity")
        return parent, project


def _parse_scheduler(value: Mapping[str, object], job_id: str) -> Mapping[str, object]:
    _driver._validate_result("QUERY_SCHEDULER", value)
    out = _driver._canonical_b64(value["stdout_base64"])
    err = _driver._canonical_b64(value["stderr_base64"])
    unknown = {"job_id": job_id, "state": "unknown"}
    if len(out) > 262144 or len(err) > 65536:
        return unknown
    if value["returncode"] == 153 and not out and err in (f"qstat: Unknown Job Id {job_id}\n".encode("ascii"), f"qstat: Unknown Job Id Error {job_id}\n".encode("ascii")):
        return {"job_id": job_id, "state": "absent"}
    if value["returncode"] != 0 or err or b"\x00" in out or b"\r" in out:
        return unknown
    try:
        text = out.decode("utf-8")
    except UnicodeError:
        return unknown
    if not text.endswith("\n"):
        return unknown
    lines = text[:-1].split("\n")
    # Torque 6.1.0 display_single_job adds one LF after the final attribute.
    # Remove only that optional record separator, never arbitrary whitespace.
    if lines[-1] == "":
        lines.pop()
    if not lines:
        return unknown
    if lines[0] != f"Job Id: {job_id}":
        return unknown
    fields: dict[str, str] = {}
    previous_field: str | None = None
    for line in lines[1:]:
        # prt_attr folds with LF + TAB (including a bare TAB at a wrap edge).
        # Opaque continuation data must never supply scheduler authority.
        if line.startswith("\t"):
            if previous_field is None or previous_field.lower() in {"job_state", "exit_status"}:
                return unknown
            if re.fullmatch(r"\t[^\x00-\x1f\x7f]*", line) is None or re.match(
                r"\t *(?:job_state|exit_status|Job Id)(?:[ =:]|$)", line, re.IGNORECASE,
            ):
                return unknown
            continue
        match = re.fullmatch(r"    ([A-Za-z_][A-Za-z0-9_.-]*) = (.+)", line)
        if match is None or match[1] in fields:
            return unknown
        fields[match[1]] = match[2]
        previous_field = match[1]
    state = {"Q": "queued", "W": "queued", "R": "running", "B": "running", "H": "held", "S": "held", "E": "exiting", "T": "exiting", "C": "terminal", "F": "terminal", "X": "terminal"}.get(fields.get("job_state"), "unknown")
    result: dict[str, object] = {"job_id": job_id, "state": state}
    if state == "terminal":
        exit_status = fields.get("exit_status")
        if exit_status is None or re.fullmatch(r"0|-?[1-9][0-9]{0,9}", exit_status) is None:
            return unknown
        result["exit_status"] = int(exit_status)
    return result


class _RTWinProgramEffectDriver:
    """Seven successor operations, with ephemeral execution-owned context."""

    def __init__(self, *, snapshot: ProgramExecutionSnapshot, current_profile: ServerProfile, program_transport_store: program._ProgramTransportStore) -> None:
        self._initialize(snapshot, current_profile, program_transport_store)
        self._collection_only = False
        self._recovery_only = False
        self._open_authority()

    @classmethod
    def _for_fixed_collection(cls, *, snapshot, current_profile, program_transport_store):
        value = cls.__new__(cls)
        value._initialize(snapshot, current_profile, program_transport_store)
        value._collection_only = True
        value._recovery_only = False
        value._open_authority()
        return value

    @classmethod
    def _for_fixed_recovery(cls, *, snapshot, current_profile, program_transport_store):
        value = cls.__new__(cls)
        value._initialize(snapshot, current_profile, program_transport_store)
        value._collection_only = True
        value._recovery_only = True
        value._open_authority()
        from . import _submission_recovery as recovery
        if value._publisher.document["schema"] != recovery.SCHEMA:
            value.close()
            raise _publisher_failure("recovery installation missing")
        return value

    def _read_operations(self):
        return (*_COLLECTION_OPERATIONS, "RECONCILE_SUBMISSION") if self._recovery_only else _COLLECTION_OPERATIONS

    def _initialize(self, snapshot, current_profile, program_transport_store):
        if type(snapshot) is not ProgramExecutionSnapshot or type(program_transport_store) is not program._ProgramTransportStore:
            raise TransportBoundaryError("production successor dependencies are not exact")
        if snapshot.program_execution_spec.adapter_contract_version == 3 and not any(snapshot.scheduler_artifacts[0]["content_utf8"].startswith("#!/bin/bash\n# auto-g16-v31-scheduler/" + version + "\n") for version in (("4", "5") if snapshot.program_execution_spec.program_kind == "crest" else ("3",))):
            raise TransportBoundaryError("publisher-not-qualified")
        self._publisher = None
        self._snapshot = snapshot
        self._profile = current_profile
        self._store = program_transport_store
        self._lock = RLock()
        self._active: tuple[Mapping[str, object], tuple[Mapping[str, object], ...]] | None = None

    def _open_authority(self):
        try:
            self._authority()
        except BaseException:
            self.close()
            raise

    def _authority(self) -> _driver._DeploymentAuthority:
        self._snapshot.assert_identity_closed()
        executable = self._snapshot.program_execution_spec.invocation["executable_identity"]
        if str(executable["absolute_path"]).startswith("/opt/auto-g16-fixtures/"):
            raise TransportBoundaryError("synthetic executables cannot qualify a production driver")
        authority = _driver._resolve_closed_profile_authority(self._snapshot.resolved_server_profile, self._profile, self._snapshot.program_execution_snapshot_id, successor=True)
        if not authority.resource_dialect.live_capable or type(authority.ssh_effect) is not _driver._MacProxyJumpEffectAuthority:
            raise TransportBoundaryError("production successor requires qualified ProxyJump")
        if self._snapshot.program_execution_spec.adapter_contract_version == 3:
            if self._publisher is None:
                reader = _read_fixed_collection_deployment if self._collection_only else _read_fixed_publisher_deployment
                self._publisher = reader(authority, self._snapshot)
            else:
                self._publisher.assert_current()
                if (self._publisher.basis["resolved_server_profile_id"], self._publisher.basis["effective_config_sha256"]) != (authority.resolved_server_profile_id, authority.effective_config_sha256):
                    raise _publisher_failure("current deployment differs")
        resources = self._snapshot.resolved_resource_request
        _driver._render_qsub_argv(
            _driver._ResourceEnactment(self._snapshot.program_execution_snapshot_id, resources.resolved_resource_request_id, resources.cores, resources.memory_mb, resources.walltime_seconds, resources.queue, authority.resource_dialect.dialect_id),
            str(self._snapshot.scheduler_artifacts[0]["portable_name"]),
            self._snapshot.workspace_binding.remote_attempt_dir,
        )
        project = self._snapshot.project_physical_binding
        _directory_token(project.parent_physical_identity, project.remote_project_dir.rsplit("/", 1)[0])
        _directory_token(project.project_physical_identity, project.remote_project_dir)
        self._store._attest()
        return authority

    def close(self):
        if self._publisher is not None:
            self._publisher.close()
            self._publisher = None

    @property
    def runtime_qualification(self) -> Mapping[str, object]:
        authority = self._authority()
        return MappingProxyType({"deployment_id": authority.manifest.deployment_id, "bootstrap_protocol": authority.manifest.bootstrap_protocol, "bootstrap_source_sha256": authority.bootstrap_source_sha256, "bootstrap_source_size_bytes": authority.bootstrap_source_size_bytes})

    def _invoke_owned(self, request: Mapping[str, object], receipts: tuple[Mapping[str, object], ...], *args: object) -> Mapping[str, object]:
        """Execution has reclosed Core state and every dual-source predecessor."""
        if self._collection_only and request.get("operation") not in self._read_operations():
            raise _publisher_failure("collection forbids mutation/reconciliation")
        if self._recovery_only and request.get("operation") == "RECONCILE_SUBMISSION" and request.get("payload", {}).get("schema") != "v31-exact-observed-job-reconciliation-request/1":
            raise _publisher_failure("fixed recovery forbids marker-only fallback")
        methods = dict(zip(program._OPERATIONS, (self.allocate_workspace, self.stage_exact_file, self.submit_qsub_once, self.query_scheduler, self.stat_exact_file, self.fetch_exact_file, self.reconcile_submission)))
        with self._lock:
            if self._active is not None:
                raise TransportBoundaryError("successor invocation context is already active")
            self._active = (request, receipts)
            try:
                return program._call(methods[str(request["operation"])], request, *args)
            finally:
                self._active = None

    def _invoke(self, operation: str, request: Mapping[str, object], content: bytes | None = None) -> Mapping[str, object]:
        if self._collection_only and operation not in self._read_operations():
            raise _publisher_failure("collection forbids mutation/reconciliation")
        if self._active is None or self._active[0] != request:
            raise TransportBoundaryError("production operation requires execution-owned predecessor closure")
        _bound, receipts = self._active
        self._active = None  # One-use, even when the process outcome is ambiguous.
        authority = self._authority()
        snapshot = self._snapshot
        base = request["binding"]
        if not isinstance(base, Mapping) or request.get("operation") != operation:
            raise TransportBoundaryError("production operation request differs")
        expected = {
            "program_transport_store_id": self._store.program_transport_store_id,
            "store_instance_id": self._store.store_instance_id,
            "runtime_attestation_id": self._store.attest_runtime(program_execution_snapshot_id=snapshot.program_execution_snapshot_id, resolved_server_profile_id=snapshot.resolved_server_profile.resolved_server_profile_id, qualification=self.runtime_qualification, persist=False),
            "attempt_id": snapshot.attempt_id,
            "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
            "effect_intent_id": snapshot.effect_intent_id,
            "program_execution_spec_id": snapshot.program_execution_spec_id,
            "project_physical_binding_id": snapshot.project_physical_binding_id,
            "workspace_binding_id": snapshot.workspace_binding.workspace_binding_id,
            "resolved_server_profile_id": snapshot.resolved_server_profile.resolved_server_profile_id,
            "remote_workspace": snapshot.workspace_binding.remote_attempt_dir,
        }
        if any(base.get(key) != value for key, value in expected.items()):
            raise TransportBoundaryError("production request binding differs from current snapshot")
        program._validate_program_effect_request(request, base)
        workspace = None
        staged = []
        for index, receipt in enumerate(receipts, 1):
            if receipt["effect_sequence"] != index or receipt["program_execution_snapshot_id"] != snapshot.program_execution_snapshot_id or receipt["effect_intent_id"] != snapshot.effect_intent_id:
                raise TransportBoundaryError("production predecessors are cross-spliced")
            prior_request = receipt["request"]
            response = receipt["response"]
            job_id = response.get("job_id") if receipt["operation"] in {"SUBMIT_QSUB_ONCE", "RECONCILE_SUBMISSION"} and receipt["outcome"] == "SUCCEEDED" else None
            self._store.require_matching_effect(binding=prior_request["binding"], request=prior_request, classification=receipt["outcome"], response=response, job_id=job_id)
            if receipt["operation"] == "ALLOCATE_WORKSPACE" and receipt["outcome"] == "SUCCEEDED":
                workspace = response["workspace_physical_token"]
            if receipt["operation"] == "STAGE_EXACT_FILE" and receipt["outcome"] == "SUCCEEDED":
                staged.append(dict(response))
            if receipt["operation"] == operation and operation in {"ALLOCATE_WORKSPACE", "SUBMIT_QSUB_ONCE"}:
                raise TransportBoundaryError("an ambiguous or completed mutation cannot repeat")
        project = snapshot.project_physical_binding
        binding = _wire_binding(snapshot.resolved_server_profile, snapshot.program_execution_snapshot_id, project.remote_project_dir)
        binding.update(parent_physical_identity=project.parent_physical_identity, project_physical_identity=project.project_physical_identity, attempt_id=snapshot.attempt_id, program_execution_snapshot_id=snapshot.program_execution_snapshot_id, effect_intent_id=snapshot.effect_intent_id, remote_workspace=snapshot.workspace_binding.remote_attempt_dir, workspace_physical_token=workspace)
        _directory_token(project.parent_physical_identity, project.remote_project_dir.rsplit("/", 1)[0])
        _directory_token(project.project_physical_identity, project.remote_project_dir)
        if operation != "ALLOCATE_WORKSPACE":
            _directory_token(workspace, snapshot.workspace_binding.remote_attempt_dir)
        payload = dict(request["payload"])
        if operation == "STAGE_EXACT_FILE":
            if type(content) is not bytes or len(content) != payload["size_bytes"] or sha256(content).hexdigest() != payload["sha256"]:
                raise TransportBoundaryError("production stage content differs from request")
            import base64
            payload["content_base64"] = base64.b64encode(content).decode("ascii")
        resources = snapshot.resolved_resource_request
        executable = snapshot.program_execution_spec.invocation["executable_identity"]
        wire = {"protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, "operation": operation, "binding": binding, "payload": {"request_payload": payload, "executable": {"path": executable["absolute_path"], "size_bytes": executable["size_bytes"], "sha256": executable["sha256"]}, "resources": {"cores": resources.cores, "memory_mb": resources.memory_mb, "walltime_seconds": resources.walltime_seconds, "queue": resources.queue}, "staged": staged}}
        exact_recovery = operation == "RECONCILE_SUBMISSION" and payload.get("schema") == "v31-exact-observed-job-reconciliation-request/1"
        if exact_recovery:
            if not self._recovery_only:
                raise _publisher_failure("exact recovery owner required")
            marker = canonical_json_bytes({"program_execution_snapshot_id": snapshot.program_execution_snapshot_id, "effect_intent_id": snapshot.effect_intent_id})
            wire["payload"]["recovery_identity"] = {"host": self._publisher.document["reconciliation"]["host"], "marker_sha256": sha256(marker).hexdigest(), "marker_size": len(marker)}
        invocation = _ProgramRTWinInvocation(_driver._operation(operation), authority, self._profile, _closed_copy(wire), snapshot.program_execution_snapshot_id)
        token = None
        try:
            if self._collection_only:
                if _COLLECTION_WIRE_OWNER.get() is not None:
                    raise _publisher_failure("nested collection wire owner")
                token = _COLLECTION_WIRE_OWNER.set((self, invocation))
            if operation == "RECONCILE_SUBMISSION" and request["payload"].get("schema") == "v31-exact-observed-job-reconciliation-request/1":
                if not self._recovery_only:
                    raise _publisher_failure("exact recovery owner required")
                import base64
                from ._recovery_process import _RecoveryProcessOwner
                out, err, code, state, eofout, eoferr = _RecoveryProcessOwner()._run(snapshot, invocation)
                result = {"stdout_base64": base64.b64encode(out).decode(), "stderr_base64": base64.b64encode(err).decode(),
                          "returncode": code, "completion_status": state, "eof_stdout": eofout, "eof_stderr": eoferr}
            else:
                result = _wire_call(snapshot, invocation)
        finally:
            if token is not None:
                _COLLECTION_WIRE_OWNER.reset(token)
        if self._collection_only and not exact_recovery:
            self._authority()
        if operation == "QUERY_SCHEDULER":
            self._store._record_scheduler_raw(request=request, result=result)
            return _parse_scheduler(result, str(payload["job_id"]))
        if operation == "FETCH_EXACT_FILE":
            program._exact_keys(result, {"portable_name", "content_base64", "size_bytes", "sha256", "file_physical_token"}, "fetch wire result")
            return {key: value for key, value in result.items() if key != "content_base64"} | {"content": _driver._canonical_b64(result["content_base64"])}
        return result

    def allocate_workspace(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._invoke("ALLOCATE_WORKSPACE", request)

    def stage_exact_file(self, request: Mapping[str, object], content: bytes) -> Mapping[str, object]:
        return self._invoke("STAGE_EXACT_FILE", request, content)

    def submit_qsub_once(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._invoke("SUBMIT_QSUB_ONCE", request)

    def query_scheduler(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._invoke("QUERY_SCHEDULER", request)

    def stat_exact_file(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._invoke("STAT_EXACT_FILE", request)

    def fetch_exact_file(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._invoke("FETCH_EXACT_FILE", request)

    def reconcile_submission(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self._invoke("RECONCILE_SUBMISSION", request)


__all__: tuple[str, ...] = ()

# No actual deployment locator has been acquired or installed. There is no
# setter, environment lookup, CLI path, profile-path fallback, or file search.
# Only a separately reviewed installation may fix this private source binding.
@dataclass(frozen=True, slots=True)
class _PublisherFileBinding:
    path: str
    parent_chain: tuple[tuple[int, int], ...]
    file_identity: tuple[int, int]
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _FixedPublisherInstallation:
    basis: _PublisherFileBinding
    qualification: _PublisherFileBinding
    evidence: tuple[_PublisherFileBinding, ...]
    source_commit: str
    source_tree: str


_FIXED_PUBLISHER_INSTALLATION: _FixedPublisherInstallation | None = None
_PUBLISHER_BASIS_KEYS = frozenset({
    "schema", "source_commit", "source_tree", "resolved_server_profile_id",
    "effective_config_sha256", "program_execution_snapshot_id",
    "qualification_payload_sha256", "qualification_file_sha256", "qualification_size_bytes",
    "qualification_path", "qualification_parent_chain", "qualification_file_identity",
    "probe_evidence_manifest_sha256", "owner_q_acceptance_evidence_sha256",
    "pilot_live_gate_evidence_sha256", "pilot_window",
})


def _publisher_failure(reason):
    return TransportBoundaryError("publisher-not-qualified: " + reason)


class _PinnedPublisherFile:
    """Read-only descriptors retained across each effect boundary; no path reopening."""

    def __init__(self, binding, cap):
        import os
        import stat
        self.binding = binding
        self.fds = []
        self.raw = b""
        try:
            path = binding.path
            if type(binding) is not _PublisherFileBinding or type(path) is not str or not path.startswith("/") or any(x in {"", ".", ".."} for x in path[1:].split("/")) or len(path.encode()) > 4096 or any(x in path for x in "\x00\r\n"):
                raise _publisher_failure("invalid installed path")
            if type(binding.size_bytes) is not int or not 1 <= binding.size_bytes <= cap or re.fullmatch("[0-9a-f]{64}", binding.sha256) is None:
                raise _publisher_failure("invalid installed content identity")
            parts = path[1:].split("/")
            if len(binding.parent_chain) != len(parts) or not 1 <= len(parts) <= 128:
                raise _publisher_failure("invalid installed parent inventory")
            nodes = (*binding.parent_chain, binding.file_identity)
            if any(type(n) is not tuple or len(n) != 2 or type(n[0]) is not int or not 0 <= n[0] <= 2**63-1 or type(n[1]) is not int or not 1 <= n[1] <= 2**63-1 for n in nodes):
                raise _publisher_failure("invalid installed physical identity")
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            self.fds.append(os.open("/", flags | os.O_DIRECTORY))
            for part in parts[:-1]:
                self.fds.append(os.open(part, flags | os.O_DIRECTORY, dir_fd=self.fds[-1]))
            self.fds.append(os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=self.fds[-1]))
            if not stat.S_ISREG(os.fstat(self.fds[-1]).st_mode):
                raise _publisher_failure("installed object is not a regular file")
            self._read_and_check()
        except BaseException:
            self.close()
            raise

    def _read_and_check(self):
        import os
        import stat
        binding = self.binding
        parts = binding.path[1:].split("/")
        expected = (*binding.parent_chain, binding.file_identity)
        self._check_names()
        fd = self.fds[-1]
        before = os.fstat(fd)
        if before.st_size != binding.size_bytes:
            raise _publisher_failure("installed size drift")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks, remaining = [], binding.size_bytes
        while remaining:
            block = os.read(fd, min(remaining, 1048576))
            if not block:
                raise _publisher_failure("short installed read")
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        named = os.stat(parts[-1], dir_fd=self.fds[-2], follow_symlinks=False)
        key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if os.read(fd, 1) or key(before) != key(after) or key(after) != key(named) or sha256(raw).hexdigest() != binding.sha256 or self.raw and raw != self.raw:
            raise _publisher_failure("installed bytes/identity drift")
        self._check_names()
        self.raw = raw
        return raw

    def _check_names(self):
        import os
        import stat
        parts = self.binding.path[1:].split("/")
        expected = (*self.binding.parent_chain, self.binding.file_identity)
        for i, (fd, node) in enumerate(zip(self.fds, expected)):
            observed = os.fstat(fd)
            named = os.stat("/", follow_symlinks=False) if i == 0 else os.stat(parts[i-1], dir_fd=self.fds[i-1], follow_symlinks=False)
            if (observed.st_dev, observed.st_ino) != node or (named.st_dev, named.st_ino) != node or (not stat.S_ISDIR(named.st_mode) if i < len(self.fds)-1 else not stat.S_ISREG(named.st_mode)):
                raise _publisher_failure("installed path/descriptor drift")

    def close(self):
        import os
        while self.fds:
            os.close(self.fds.pop())


@dataclass(slots=True)
class _PublisherDeploymentRead:
    installation: _FixedPublisherInstallation
    basis: Mapping[str, object]
    qualification: Mapping[str, object]
    evidence: Mapping[str, bytes]
    pins: tuple[_PinnedPublisherFile, ...]

    def assert_identity(self):
        if _FIXED_PUBLISHER_INSTALLATION is not self.installation:
            raise _publisher_failure("fixed installation changed")
        for pin in self.pins:
            pin._read_and_check()

    def assert_current(self):
        self.assert_identity()
        _publisher_window(self.basis["pilot_window"], self.qualification["payload"]["observation_window"])

    def close(self):
        for pin in reversed(self.pins):
            pin.close()


def _publisher_window(window, observation):
    from datetime import datetime, timezone
    program._exact_keys(window, {"started_at", "finished_at"}, "pilot window")
    for stamp in window.values():
        if type(stamp) is not str or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", stamp) is None:
            raise _publisher_failure("invalid pilot timestamp")
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if not observation["finished_at"] <= window["started_at"] <= now <= window["finished_at"]:
        raise _publisher_failure("outside exact pilot window")


def _read_fixed_publisher_deployment(authority, snapshot):
    result = _read_publisher_deployment_identity(authority, snapshot)
    try:
        result.assert_current()
        return result
    except BaseException:
        result.close()
        raise


def _read_publisher_deployment_identity(authority, snapshot):
    """Only mechanical identity comparisons; Approval/Core are Controller-owned."""
    import base64
    from ._canonical import strict_canonical_json
    installation = _FIXED_PUBLISHER_INSTALLATION
    if type(installation) is not _FixedPublisherInstallation:
        raise _publisher_failure("fixed deployment locator NOT_ACQUIRED")
    pins = []
    try:
        snapshot.assert_identity_closed()
        if type(authority) is not _driver._DeploymentAuthority:
            raise _publisher_failure("closed deployment authority required")
        if not any(snapshot.scheduler_artifacts[0]["content_utf8"].startswith("#!/bin/bash\n# auto-g16-v31-scheduler/" + version + "\n") for version in (("4", "5") if snapshot.program_execution_spec.program_kind == "crest" else ("3",))):
            raise _publisher_failure("old receipt source cannot gain production qualification")
        basis_pin = _PinnedPublisherFile(installation.basis, 65536); pins.append(basis_pin)
        if installation.basis.path.rsplit("/", 1)[-1] != "v31-publisher-pilot-deployment.json":
            raise _publisher_failure("fixed deployment basename differs")
        basis = strict_canonical_json(basis_pin.raw, "publisher deployment basis")
        program._exact_keys(basis, set(_PUBLISHER_BASIS_KEYS), "publisher deployment basis")
        startup = len(snapshot.scheduler_artifacts) == 2
        if basis["schema"] != ("auto-g16-v31-publisher-pilot-deployment/3" if startup else "auto-g16-v31-publisher-pilot-deployment/2" if snapshot.program_execution_spec.program_kind == "crest" else "auto-g16-v31-publisher-pilot-deployment/1"):
            raise _publisher_failure("unknown deployment basis")
        for key in ("source_commit", "source_tree"):
            if type(basis[key]) is not str or re.fullmatch("[0-9a-f]{40}", basis[key]) is None or basis[key] != getattr(installation, key):
                raise _publisher_failure("installed source identity differs")
        if (basis["resolved_server_profile_id"], basis["effective_config_sha256"], basis["program_execution_snapshot_id"]) != (authority.resolved_server_profile_id, authority.effective_config_sha256, snapshot.program_execution_snapshot_id) or authority.execution_snapshot_id != snapshot.program_execution_snapshot_id:
            raise _publisher_failure("installed snapshot/profile differs")
        qpin = _PinnedPublisherFile(installation.qualification, 1024*1024); pins.append(qpin)
        qbinding = installation.qualification
        expected = {"qualification_path": qbinding.path, "qualification_parent_chain": [{"device": d, "inode": i} for d, i in qbinding.parent_chain], "qualification_file_identity": {"device": qbinding.file_identity[0], "inode": qbinding.file_identity[1]}, "qualification_file_sha256": qbinding.sha256, "qualification_size_bytes": qbinding.size_bytes}
        if type(basis["qualification_size_bytes"]) is not int or any(canonical_json_bytes(basis[k]) != canonical_json_bytes(v) for k,v in expected.items()):
            raise _publisher_failure("Q installation readback differs")
        # Public snapshot identity closure above has already validated full Q grammar,
        # profile projection, source and tuple. No private Execution import here.
        if startup:
            material = strict_canonical_json(snapshot.scheduler_artifacts[1]["content_utf8"].encode(), "startup payload")["config"]["material"]
        else:
            line = snapshot.scheduler_artifacts[0]["content_utf8"].splitlines()[2]
            material = strict_canonical_json(base64.b64decode(line.split(": ", 1)[1], validate=True), "publisher material")
        if base64.b64decode(material["publisher_qualification_base64"], validate=True) != qpin.raw:
            raise _publisher_failure("installed Q differs from snapshot")
        q = strict_canonical_json(qpin.raw, "publisher Q")
        p = q["payload"]
        if basis["qualification_payload_sha256"] != q["payload_sha256"] or basis["probe_evidence_manifest_sha256"] != p["evidence_manifest_sha256"] or (p["implementation"]["commit"], p["implementation"]["tree"]) != (installation.source_commit, installation.source_tree):
            raise _publisher_failure("Q source/payload/evidence mismatch")
        evidence = {}
        for binding in installation.evidence:
            pin = _PinnedPublisherFile(binding, 16*1024*1024); pins.append(pin)
            if binding.sha256 in evidence:
                raise _publisher_failure("duplicate installed evidence identity")
            evidence[binding.sha256] = pin.raw
        digests = [p["execution_domain"]["scheduler_scope_evidence"], p["controller_probe"]["evidence"]]
        if startup:
            digests.append(p["delivery_probe"]["evidence"])
        for host in p["hosts"]:
            digests.extend([host["identity_evidence"], *(loc["evidence"] for loc in host["locations"]), *(probe["evidence"] for probe in host["probes"])])
        for digest in digests:
            if digest["sha256"] not in evidence or len(evidence[digest["sha256"]]) != digest["size_bytes"]:
                raise _publisher_failure("raw probe evidence missing or size differs")
        for key in ("probe_evidence_manifest_sha256", "owner_q_acceptance_evidence_sha256", "pilot_live_gate_evidence_sha256"):
            if type(basis[key]) is not str or re.fullmatch("[0-9a-f]{64}", basis[key]) is None or basis[key] not in evidence:
                raise _publisher_failure("installed original evidence missing")
        if p["schema"] in {"auto-g16-v31-publisher-qualification/2", "auto-g16-v31-publisher-qualification/3"}:
            closure = p["runtime"]["crest_loader_closure"]
            for digest in (closure["evidence_manifest_sha256"], closure["loading_policy"]["dynamic_loading_review_sha256"]):
                if digest not in evidence:
                    raise _publisher_failure("installed CREST loader evidence missing")
        result = _PublisherDeploymentRead(installation, basis, q, MappingProxyType(evidence), tuple(pins))
        result.assert_identity()
        return result
    except BaseException as exc:
        for pin in reversed(pins):
            pin.close()
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise _publisher_failure("fixed deployment ingestion rejected") from exc


_COLLECTION_OPERATIONS = ("QUERY_SCHEDULER", "STAT_EXACT_FILE", "FETCH_EXACT_FILE")
_COLLECTION_SCHEMA = "auto-g16-v31-collection-continuation/1"
_COLLECTION_KEYS = {"schema", "original", "stores", "collector_source", "original_source", "window", "scope", "review_evidence"}
_COLLECTION_ORIGINAL_KEYS = {
    "attempt_id", "snapshot_id", "effect_intent_id", "job_id", "project_physical_binding_id",
    "resolved_server_profile_id", "original_basis_sha256", "snapshot_semantics_sha256",
    "scientific_approval_id", "batch_submit_approval_id", "operational_confirmation_id",
}


@dataclass(frozen=True, slots=True)
class _FixedCollectionInstallation:
    continuation: _PublisherFileBinding
    reviewed_scope: _PublisherFileBinding
    evidence: tuple[_PublisherFileBinding, ...]
    code_root: str
    code_files: tuple[_PublisherFileBinding, ...]
    source_commit: str
    source_tree: str


_FIXED_COLLECTION_INSTALLATION: _FixedCollectionInstallation | None = None


def _collection_nodes(value):
    program._exact_keys(value, {"device", "inode"}, "collection physical node")
    for name in ("device", "inode"):
        if type(value[name]) is not int or value[name] < (1 if name == "inode" else 0):
            raise _publisher_failure("invalid collection physical node")


def _collection_digest(value):
    program._exact_keys(value, {"sha256", "size_bytes"}, "collection digest")
    if type(value["sha256"]) is not str or re.fullmatch("[0-9a-f]{64}", value["sha256"]) is None or type(value["size_bytes"]) is not int or not 0 < value["size_bytes"] <= 16*1024*1024:
        raise _publisher_failure("invalid collection digest")


def _collection_source_files(installation, document):
    """Pin actual project imports; metadata paths never select executable code."""
    import sys
    from pathlib import Path
    source = document["collector_source"]
    program._exact_keys(source, {"commit", "tree", "files"}, "collector source")
    if (source["commit"], source["tree"]) != (installation.source_commit, installation.source_tree) or any(type(source[k]) is not str or re.fullmatch("[0-9a-f]{40}", source[k]) is None for k in ("commit", "tree")):
        raise _publisher_failure("collector source differs from installation")
    if type(source["files"]) is not list or not 1 <= len(source["files"]) <= 256:
        raise _publisher_failure("collector source inventory missing")
    root = Path(installation.code_root)
    expected = []
    for binding in installation.code_files:
        relative = str(Path(binding.path).relative_to(root))
        expected.append({"path": relative, "sha256": binding.sha256, "size_bytes": binding.size_bytes})
    if canonical_json_bytes(source["files"]) != canonical_json_bytes(sorted(expected, key=lambda v: v["path"])) or len({v["path"] for v in expected}) != len(expected):
        raise _publisher_failure("collector installed inventory differs")
    paths = {b.path for b in installation.code_files}
    required = {str(root / name) for name in (
        "auto_g16/execution/program.py", "auto_g16/execution/program_runtime.py",
        "auto_g16/execution/_program_completion.py", "auto_g16/execution/_program_completion_wrapper.py",
        "auto_g16/transport/_program_rtwin.py", "scripts/run_v31_publisher_pilot.py",
    )}
    if document["schema"] == "auto-g16-v31-exact-job-recovery-continuation/1":
        required.update(str(root / name) for name in (
            "auto_g16/execution/_submission_recovery.py", "auto_g16/transport/_submission_recovery.py",
            "auto_g16/transport/_recovery_process.py", "auto_g16/transport/program.py",
        ))
    if not required <= paths or str(Path(__file__).absolute()) not in paths:
        raise _publisher_failure("collection owner code is not pinned")
    for name, module in tuple(sys.modules.items()):
        if name == "auto_g16" or name.startswith("auto_g16.") or name == "scripts.run_v31_publisher_pilot":
            path = getattr(module, "__file__", None)
            if path is None or str(Path(path).absolute()) not in paths:
                raise _publisher_failure("unreviewed collection import")


def _validate_collection_document(document, original, installation, snapshot):
    recovering = document.get("schema") == "auto-g16-v31-exact-job-recovery-continuation/1"
    program._exact_keys(document, _COLLECTION_KEYS | ({"reconciliation"} if recovering else set()), "collection continuation")
    if document["schema"] not in {_COLLECTION_SCHEMA, "auto-g16-v31-exact-job-recovery-continuation/1"}:
        raise _publisher_failure("unknown collection schema")
    bound = program._exact_keys(document["original"], _COLLECTION_ORIGINAL_KEYS, "collection original")
    for key, value in bound.items():
        program._text(value, key)
    for key in ("original_basis_sha256", "snapshot_semantics_sha256"):
        if re.fullmatch("[0-9a-f]{64}", bound[key]) is None:
            raise _publisher_failure("invalid original digest")
    from hashlib import sha256 as hash_bytes
    expected = {"attempt_id": snapshot.attempt_id, "snapshot_id": snapshot.program_execution_snapshot_id,
                "effect_intent_id": snapshot.effect_intent_id, "project_physical_binding_id": snapshot.project_physical_binding_id,
                "resolved_server_profile_id": snapshot.resolved_server_profile.resolved_server_profile_id,
                "original_basis_sha256": original.installation.basis.sha256,
                "snapshot_semantics_sha256": hash_bytes(canonical_json_bytes(_plain(snapshot._approval_semantics()))).hexdigest()}
    if any(bound[k] != v for k, v in expected.items()):
        raise _publisher_failure("collection original snapshot differs")
    program._job_id(bound["job_id"])
    old_source = {"commit": original.installation.source_commit, "tree": original.installation.source_tree,
                  "wrapper_source": original.qualification["payload"]["implementation"]["wrapper_source"],
                  "qualification_file_sha256": original.installation.qualification.sha256,
                  "qualification_payload_sha256": original.qualification["payload_sha256"]}
    if canonical_json_bytes(document["original_source"]) != canonical_json_bytes(old_source):
        raise _publisher_failure("original Q does not qualify new collector code")
    # Metadata is a fixed declaration, not a caller-selected subset.
    names = ["v31-completion.json", *(v["portable_name"] for v in snapshot.program_execution_spec.required_outputs), *(v["portable_name"] for v in snapshot.program_execution_spec.optional_outputs)]
    scope = {"action": "collect-existing-job", "maximum_remote_epochs": 1,
             "operations": list(_COLLECTION_OPERATIONS), "files": names, "local_replay": True}
    if recovering:
        from . import _submission_recovery as recovery
        scope.update(action="reconcile-exact-job-and-collect", maximum_reconciliation_epochs=1)
        scope["operations"] = ["RECONCILE_SUBMISSION", *_COLLECTION_OPERATIONS]
        rec = program._exact_keys(document["reconciliation"], {"submit_receipt_id", "job_owner", "server", "host", "probe_source", "prior_recovery_authority"}, "exact recovery scope")
        if rec["prior_recovery_authority"] is not None:
            _collection_digest(rec["prior_recovery_authority"])
            from auto_g16.execution import _submission_recovery as native_recovery
            native_recovery.document(snapshot)
        for key in ("submit_receipt_id", "job_owner", "server"):
            program._text(rec[key], key)
        program._exact_keys(rec["host"], {"machine_id_sha256", "boot_id"}, "recovery host")
        if re.fullmatch(r"[0-9a-f]{64}", rec["host"]["machine_id_sha256"]) is None or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", rec["host"]["boot_id"]) is None:
            raise _publisher_failure("invalid recovery host")
        source = recovery.source_bytes()
        if canonical_json_bytes(rec["probe_source"]) != canonical_json_bytes({"sha256": sha256(source).hexdigest(), "size_bytes": len(source)}):
            raise _publisher_failure("recovery source not separately pinned")
    if canonical_json_bytes(document["scope"]) != canonical_json_bytes(scope):
        raise _publisher_failure("collection scope is not exact")
    stores = document["stores"]
    if type(stores) is not list or len(stores) != 4:
        raise _publisher_failure("collection requires four original stores")
    for item, role in zip(stores, ("core", "approval", "transport", "project-journal")):
        fields = {"role", "path", "parent_chain", "file_identity"}
        if role == "transport":
            fields |= {"program_transport_store_id", "store_instance_id", "runtime_attestation_id"}
        if role == "project-journal":
            fields.add("journal_identity")
        program._exact_keys(item, fields, "collection store")
        if item["role"] != role or type(item["path"]) is not str or not item["path"].startswith("/") or any(p in {"", ".", ".."} for p in item["path"][1:].split("/")):
            raise _publisher_failure("collection store path/role differs")
        if type(item["parent_chain"]) is not list or len(item["parent_chain"]) != len(item["path"][1:].split("/")):
            raise _publisher_failure("collection store chain differs")
        for node in [*item["parent_chain"], item["file_identity"]]:
            _collection_nodes(node)
        for key in fields - {"role", "path", "parent_chain", "file_identity"}:
            program._text(item[key], key)
    if len({v["path"] for v in stores}) != 4 or len({(v["file_identity"]["device"], v["file_identity"]["inode"]) for v in stores}) != 4:
        raise _publisher_failure("collection stores are not distinct")
    review = program._exact_keys(document["review_evidence"], {"owner_continuation", "source_compatibility"}, "collection review")
    for value in review.values():
        _collection_digest(value)
    _collection_source_files(installation, document)
    _publisher_window(document["window"], original.qualification["payload"]["observation_window"])


@dataclass(slots=True)
class _CollectionDeploymentRead:
    original: _PublisherDeploymentRead
    installation: _FixedCollectionInstallation
    document: Mapping[str, object]
    snapshot: ProgramExecutionSnapshot
    pins: tuple[_PinnedPublisherFile, ...]

    @property
    def basis(self):
        return self.original.basis

    def assert_current(self):
        if _FIXED_COLLECTION_INSTALLATION is not self.installation:
            raise _publisher_failure("fixed collection installation changed")
        self.original.assert_identity()
        for pin in self.pins:
            pin._read_and_check()
        _validate_collection_document(self.document, self.original, self.installation, self.snapshot)

    def close(self):
        for pin in reversed(self.pins):
            pin.close()
        self.original.close()


def _read_fixed_collection_deployment(authority, snapshot):
    """Old qualification identity plus new finite read scope, both independently fixed."""
    installation = _FIXED_COLLECTION_INSTALLATION
    if type(installation) is not _FixedCollectionInstallation:
        raise _publisher_failure("collection installation NOT_ACQUIRED")
    original = _read_publisher_deployment_identity(authority, snapshot)
    pins = []
    try:
        continuation = _PinnedPublisherFile(installation.continuation, 1024*1024); pins.append(continuation)
        document = strict_canonical_json(continuation.raw, "collection continuation")
        pins.append(_PinnedPublisherFile(installation.reviewed_scope, 65536))
        evidence = {}
        for binding in installation.evidence:
            pin = _PinnedPublisherFile(binding, 16*1024*1024); pins.append(pin)
            if binding.sha256 in evidence:
                raise _publisher_failure("duplicate collection evidence")
            evidence[binding.sha256] = {"sha256": binding.sha256, "size_bytes": len(pin.raw)}
        _validate_collection_document(document, original, installation, snapshot)
        if any(evidence.get(v["sha256"]) != v for v in document["review_evidence"].values()):
            raise _publisher_failure("collection review originals missing")
        for binding in installation.code_files:
            pins.append(_PinnedPublisherFile(binding, 4*1024*1024))
        result = _CollectionDeploymentRead(original, installation, document, snapshot, tuple(pins))
        result.assert_current()
        return result
    except BaseException:
        for pin in reversed(pins):
            pin.close()
        original.close()
        raise
