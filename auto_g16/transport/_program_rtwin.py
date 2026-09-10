"""Private successor adapter over the reviewed, bounded RTwin process owner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from threading import RLock
from types import MappingProxyType

from auto_g16.execution.models import ResolvedServerProfile, ServerProfile
from auto_g16.execution.program import ProgramExecutionSnapshot
from auto_g16.execution.project_provisioning import _ProjectAttestor

from . import _bridge, _driver, program
from ._canonical import TransportBoundaryError, canonical_json_bytes


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
    request = _closed_copy(invocation.request)
    program._exact_keys(request, {"protocol", "operation", "binding", "payload"}, "successor wire request")
    if request.get("protocol") != _bridge._PROGRAM_BOOTSTRAP_PROTOCOL or request.get("operation") != invocation.operation.name:
        raise TransportBoundaryError("successor wire protocol/operation drifted")
    _assert_wire_scope(scope, invocation.scope_identity, request)
    source = _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES
    if (sha256(source).hexdigest(), len(source)) != (authority.bootstrap_source_sha256, authority.bootstrap_source_size_bytes):
        raise TransportBoundaryError("successor bootstrap bytes drifted")
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
        program._exact_keys(payload, {"request_payload", "executable", "resources", "staged"}, "successor wire payload")
        executable = scope.program_execution_spec.invocation["executable_identity"]
        resources = scope.resolved_resource_request
        if payload["executable"] != {"path": executable["absolute_path"], "size_bytes": executable["size_bytes"], "sha256": executable["sha256"]} or payload["resources"] != {"cores": resources.cores, "memory_mb": resources.memory_mb, "walltime_seconds": resources.walltime_seconds, "queue": resources.queue}:
            raise TransportBoundaryError("successor wire runtime/resources differ from snapshot")
        original = dict(payload["request_payload"])
        content = original.pop("content_base64", None) if name == "STAGE_EXACT_FILE" else None
        if name == "SUBMIT_QSUB_ONCE" and isinstance(original.get("program_input_artifact_authority_ids"), list):
            original["program_input_artifact_authority_ids"] = tuple(original["program_input_artifact_authority_ids"])
        program._validate_operation_payload(name, original)
        stages = [
            {"artifact_kind": kind, **{key: item[key] for key in ("logical_role", "portable_name", "format", "sha256", "size_bytes")}}
            for kind, declarations in (("program-input", scope.program_execution_spec.exact_inputs), ("scheduler-script", scope.scheduler_artifacts))
            for item in declarations
        ]
        if name == "STAGE_EXACT_FILE":
            if original not in stages or not isinstance(content, str) or len(content) > 4 * ((134217728 + 2) // 3):
                raise TransportBoundaryError("successor stage is not snapshot-declared or exceeds cap")
            data = _driver._canonical_b64(content)
            if len(data) != original["size_bytes"] or sha256(data).hexdigest() != original["sha256"]:
                raise TransportBoundaryError("successor wire stage bytes differ from declaration")
        if name == "SUBMIT_QSUB_ONCE" and original["scheduler_portable_name"] != scope.scheduler_artifacts[0]["portable_name"]:
            raise TransportBoundaryError("successor wire scheduler differs from snapshot")
        if name in {"STAT_EXACT_FILE", "FETCH_EXACT_FILE"}:
            outputs = (*scope.program_execution_spec.required_outputs, *scope.program_execution_spec.optional_outputs)
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
    stdout, stderr, code, state, eofout, eoferr = _driver._SubprocessRTWinDriver()._run(scope, invocation)
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
        if type(snapshot) is not ProgramExecutionSnapshot or type(program_transport_store) is not program._ProgramTransportStore:
            raise TransportBoundaryError("production successor dependencies are not exact")
        self._snapshot = snapshot
        self._profile = current_profile
        self._store = program_transport_store
        self._lock = RLock()
        self._active: tuple[Mapping[str, object], tuple[Mapping[str, object], ...]] | None = None
        self._authority()

    def _authority(self) -> _driver._DeploymentAuthority:
        self._snapshot.assert_identity_closed()
        executable = self._snapshot.program_execution_spec.invocation["executable_identity"]
        if str(executable["absolute_path"]).startswith("/opt/auto-g16-fixtures/"):
            raise TransportBoundaryError("synthetic executables cannot qualify a production driver")
        authority = _driver._resolve_closed_profile_authority(self._snapshot.resolved_server_profile, self._profile, self._snapshot.program_execution_snapshot_id, successor=True)
        if not authority.resource_dialect.live_capable or type(authority.ssh_effect) is not _driver._MacProxyJumpEffectAuthority:
            raise TransportBoundaryError("production successor requires qualified ProxyJump")
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

    @property
    def runtime_qualification(self) -> Mapping[str, object]:
        authority = self._authority()
        return MappingProxyType({"deployment_id": authority.manifest.deployment_id, "bootstrap_protocol": authority.manifest.bootstrap_protocol, "bootstrap_source_sha256": authority.bootstrap_source_sha256, "bootstrap_source_size_bytes": authority.bootstrap_source_size_bytes})

    def _invoke_owned(self, request: Mapping[str, object], receipts: tuple[Mapping[str, object], ...], *args: object) -> Mapping[str, object]:
        """Execution has reclosed Core state and every dual-source predecessor."""
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
        result = _wire_call(snapshot, _ProgramRTWinInvocation(_driver._operation(operation), authority, self._profile, _closed_copy(wire), snapshot.program_execution_snapshot_id))
        if operation == "QUERY_SCHEDULER":
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
