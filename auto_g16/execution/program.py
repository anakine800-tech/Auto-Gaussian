"""Closed offline xTB/CREST execution successor for Auto-G16 V31."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import re
import shlex
from typing import Callable, Final

from auto_g16.core import CalculationPlan, Project, ResourceSpec, SQLiteRuntimeStore

from ._identity import (
    ExecutionValueError,
    freeze_mapping,
    require_positive_integer,
    require_sha256,
    require_text,
    semantic_id,
    semantic_sha256,
)
from ._paths import (
    require_contained,
    require_windows_contained,
    validate_portable_name,
    validate_posix_path,
)
from .models import (
    ResolvedResourceRequest,
    ResolvedServerProfile,
    WorkspaceBinding,
)
from .project_provisioning import (
    ProjectPhysicalBinding,
    _ProjectBindingReattestation,
    _consume_project_binding_reattestation,
)


_PROGRAM_KINDS: Final = frozenset({"gaussian", "xtb", "crest"})
_TOKEN: Final = re.compile(r"^[A-Za-z0-9_./:@%+=,-]+$")
_OUTPUT_FIELDS: Final = {
    "logical_role",
    "portable_name",
    "format",
    "cardinality",
    "max_size_bytes",
    "capture_policy",
    "completeness",
}
_INPUT_FIELDS: Final = {"logical_role", "portable_name", "format", "sha256", "size_bytes"}
_INVOCATION_FIELDS: Final = {"executable_identity", "argv", "stdin", "environment"}


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ExecutionValueError(f"{label} must have an exact closed field set")


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionValueError(f"{label} must be a non-negative integer")
    return value


def _fixed_milli(value: object, label: str) -> str:
    integer = require_positive_integer(value, label)
    whole, fraction = divmod(integer, 1000)
    return f"{whole}.{fraction:03d}"


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutionValueError(f"{label} must be an integer")
    return value


def _token(value: object, label: str) -> str:
    text = require_text(value, label)
    if _TOKEN.fullmatch(text) is None or any(character in text for character in ";&|<>$`(){}[]!\\\"'"):
        raise ExecutionValueError(f"{label} must be one non-shell argv token")
    return text


def _validated_input(value: Mapping[str, object], index: int) -> Mapping[str, object]:
    label = f"exact_inputs[{index}]"
    _exact_keys(value, _INPUT_FIELDS, label)
    for key in ("logical_role", "portable_name", "format"):
        require_text(value[key], f"{label}.{key}")
    validate_portable_name(value["portable_name"], f"{label}.portable_name")  # type: ignore[arg-type]
    require_sha256(value["sha256"], f"{label}.sha256")
    require_positive_integer(value["size_bytes"], f"{label}.size_bytes")
    return freeze_mapping(dict(value), label)


def _validated_output(value: Mapping[str, object], index: int, group: str) -> Mapping[str, object]:
    label = f"{group}[{index}]"
    _exact_keys(value, _OUTPUT_FIELDS, label)
    for key in ("logical_role", "portable_name", "format"):
        require_text(value[key], f"{label}.{key}")
    validate_portable_name(value["portable_name"], f"{label}.portable_name")  # type: ignore[arg-type]
    if value["cardinality"] not in {"exactly-one", "zero-or-one"}:
        raise ExecutionValueError(f"{label}.cardinality is outside the closed set")
    require_positive_integer(value["max_size_bytes"], f"{label}.max_size_bytes")
    if value["capture_policy"] != "exact-file":
        raise ExecutionValueError(f"{label}.capture_policy must be exact-file")
    if value["completeness"] not in {"program-success", "explicit-absence"}:
        raise ExecutionValueError(f"{label}.completeness is outside the closed set")
    return freeze_mapping(dict(value), label)


def _validate_invocation(value: Mapping[str, object], program_kind: str) -> Mapping[str, object]:
    _exact_keys(value, _INVOCATION_FIELDS, "invocation")
    executable = value["executable_identity"]
    if not isinstance(executable, Mapping):
        raise ExecutionValueError("invocation.executable_identity must be a closed mapping")
    _exact_keys(
        executable,
        {"absolute_path", "size_bytes", "sha256"},
        "executable_identity",
    )
    executable_path = validate_posix_path(
        require_text(executable["absolute_path"], "executable_identity.absolute_path"),
        "executable_identity.absolute_path",
    )
    if executable_path.rsplit("/", 1)[-1] != program_kind:
        raise ExecutionValueError("executable basename differs from program_kind")
    require_positive_integer(executable["size_bytes"], "executable_identity.size_bytes")
    require_sha256(executable["sha256"], "executable_identity.sha256")
    argv = value["argv"]
    if not isinstance(argv, tuple) or not argv:
        raise ExecutionValueError("invocation.argv must be an ordered non-empty tuple")
    for index, item in enumerate(argv):
        _token(item, f"invocation.argv[{index}]")
    if argv[0] != executable_path:
        raise ExecutionValueError("argv[0] must be the exact bound absolute executable path")
    stdin = value["stdin"]
    if not isinstance(stdin, Mapping):
        raise ExecutionValueError("invocation.stdin must be a closed mapping")
    _exact_keys(stdin, {"mode", "logical_role"}, "invocation.stdin")
    if stdin["mode"] != "none" or stdin["logical_role"] is not None:
        raise ExecutionValueError("initial xTB/CREST adapters accept no stdin authority")
    environment = value["environment"]
    if environment != (
        freeze_mapping(
            {"name": "OMP_NUM_THREADS", "source": "resolved-resource-request.cores"},
            "OMP_NUM_THREADS",
        ),
    ):
        raise ExecutionValueError("invocation environment is not the exact closed adapter input")
    return freeze_mapping(dict(value), "invocation")


def _validate_xtb_data(value: Mapping[str, object]) -> Mapping[str, object]:
    _exact_keys(value, {"model", "charge", "unpaired_electrons", "task", "solvent"}, "xtb program_data")
    if value["model"] not in {"gfn1", "gfn2"}:
        raise ExecutionValueError("xTB model is outside the closed adapter set")
    _integer(value["charge"], "xtb charge")
    _nonnegative_integer(value["unpaired_electrons"], "xtb unpaired_electrons")
    if value["task"] not in {"single-point", "optimize"}:
        raise ExecutionValueError("xTB task is outside the closed adapter set")
    if value["solvent"] is not None:
        validate_portable_name(require_text(value["solvent"], "xtb solvent"), "xtb solvent")
    return freeze_mapping(dict(value), "xtb program_data")


def _validate_crest_data(value: Mapping[str, object]) -> Mapping[str, object]:
    _exact_keys(
        value,
        {
            "model",
            "search_mode",
            "preset",
            "charge",
            "unpaired_electrons",
            "energy_window_millikcal_per_mol",
            "rmsd_threshold_milliangstrom",
            "temperature_millikelvin",
            "random_seed",
        },
        "CREST program_data",
    )
    if value["model"] not in {"gfn1", "gfn2"}:
        raise ExecutionValueError("CREST model is outside the closed adapter set")
    if value["search_mode"] != "ttconf" or value["preset"] not in {
        "fast",
        "normal",
        "accurate",
    }:
        raise ExecutionValueError("CREST search mode/preset is outside the closed adapter set")
    _integer(value["charge"], "CREST charge")
    _nonnegative_integer(value["unpaired_electrons"], "CREST unpaired_electrons")
    require_positive_integer(value["energy_window_millikcal_per_mol"], "CREST energy window")
    require_positive_integer(value["rmsd_threshold_milliangstrom"], "CREST RMSD threshold")
    require_positive_integer(value["temperature_millikelvin"], "CREST temperature")
    _nonnegative_integer(value["random_seed"], "CREST random seed")
    return freeze_mapping(dict(value), "CREST program_data")


def _outputs(*, required: tuple[tuple[str, str, str], ...], optional: tuple[tuple[str, str, str], ...]) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    required_values = tuple(
        freeze_mapping(
            {
                "logical_role": role,
                "portable_name": name,
                "format": format_name,
                "cardinality": "exactly-one",
                "max_size_bytes": 64 * 1024 * 1024,
                "capture_policy": "exact-file",
                "completeness": "program-success",
            },
            f"required output {role}",
        )
        for role, name, format_name in required
    )
    optional_values = tuple(
        freeze_mapping(
            {
                "logical_role": role,
                "portable_name": name,
                "format": format_name,
                "cardinality": "zero-or-one",
                "max_size_bytes": 64 * 1024 * 1024,
                "capture_policy": "exact-file",
                "completeness": "explicit-absence",
            },
            f"optional output {role}",
        )
        for role, name, format_name in optional
    )
    return required_values, optional_values


def _render_xtb(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    argv = [str(executable["absolute_path"]), input_name, "--gfn", str(data["model"])[-1], "--chrg", str(data["charge"]), "--uhf", str(data["unpaired_electrons"])]
    if data["task"] == "optimize":
        argv.append("--opt")
    if data["solvent"] is not None:
        argv.extend(("--alpb", str(data["solvent"])))
    required = (("program-log", "xtb.out", "text"),)
    optional = (("optimized-geometry", "xtbopt.xyz", "xyz"),)
    if data["task"] == "optimize":
        required += (("optimized-geometry", "xtbopt.xyz", "xyz"),)
        optional = ()
    required_values, optional_values = _outputs(required=required, optional=optional)
    return _invocation(executable, tuple(argv)), required_values, optional_values


def _render_crest(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    argv = (
        str(executable["absolute_path"]),
        input_name,
        "-ttconf",
        str(data["preset"]),
        f"--{data['model']}",
        "--chrg",
        str(data["charge"]),
        "--uhf",
        str(data["unpaired_electrons"]),
        "-ttewin",
        _fixed_milli(data["energy_window_millikcal_per_mol"], "CREST energy window"),
        "-ttseed",
        str(data["random_seed"]),
        "--rthr",
        _fixed_milli(data["rmsd_threshold_milliangstrom"], "CREST RMSD threshold"),
        "--temp",
        _fixed_milli(data["temperature_millikelvin"], "CREST temperature"),
    )
    return (
        _invocation(executable, argv),
        _outputs(
            required=(
                ("program-log", "crest.out", "text"),
                ("conformer-ensemble", "crest_conformers.xyz", "xyz-trajectory"),
            ),
            optional=(("conformer-energies", "crest.energies", "text"),),
        )[0],
        _outputs(required=(), optional=(("conformer-energies", "crest.energies", "text"),))[1],
    )


def _invocation(
    executable: Mapping[str, object], argv: tuple[str, ...]
) -> Mapping[str, object]:
    return freeze_mapping(
        {
            "executable_identity": executable,
            "argv": argv,
            "stdin": {"mode": "none", "logical_role": None},
            "environment": (
                {
                    "name": "OMP_NUM_THREADS",
                    "source": "resolved-resource-request.cores",
                },
            ),
        },
        "closed program invocation",
    )


_Adapter = tuple[
    str,
    int,
    Callable[[Mapping[str, object]], Mapping[str, object]],
    Callable[[Mapping[str, object], str, Mapping[str, object]], tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]],
]
_ADAPTERS: Final[Mapping[str, _Adapter | None]] = {
    "gaussian": None,
    "xtb": ("auto-g16-v31-xtb", 1, _validate_xtb_data, _render_xtb),
    "crest": ("auto-g16-v31-crest", 1, _validate_crest_data, _render_crest),
}


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ProgramExecutionSpec:
    program_execution_spec_id: str
    program_kind: str
    adapter_id: str
    adapter_contract_version: int
    exact_inputs: tuple[Mapping[str, object], ...]
    program_data: Mapping[str, object]
    invocation: Mapping[str, object]
    required_outputs: tuple[Mapping[str, object], ...]
    optional_outputs: tuple[Mapping[str, object], ...]
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ProgramExecutionSpec is created only by the closed adapter registry")

    @classmethod
    def _from_closed(
        cls,
        *,
        program_kind: str,
        adapter_id: str,
        adapter_contract_version: int,
        exact_inputs: tuple[Mapping[str, object], ...],
        program_data: Mapping[str, object],
        invocation: Mapping[str, object],
        required_outputs: tuple[Mapping[str, object], ...],
        optional_outputs: tuple[Mapping[str, object], ...],
    ) -> ProgramExecutionSpec:
        if program_kind not in _PROGRAM_KINDS:
            raise ExecutionValueError("program_kind is outside the closed V31 registry")
        adapter = _ADAPTERS.get(program_kind)
        if adapter is None:
            raise ExecutionValueError("Gaussian successor is reserved but not implemented")
        expected_id, expected_version, validate_data, _renderer = adapter
        if adapter_id != expected_id or adapter_contract_version != expected_version:
            raise ExecutionValueError("unknown private adapter identity or version")
        if not isinstance(exact_inputs, tuple) or len(exact_inputs) != 1:
            raise ExecutionValueError("initial adapters require exactly one immutable input")
        inputs = tuple(_validated_input(item, index) for index, item in enumerate(exact_inputs))
        if inputs[0]["logical_role"] != "structure" or inputs[0]["format"] != "xyz":
            raise ExecutionValueError("initial adapters require one XYZ structure input")
        data = validate_data(program_data)
        closed_invocation = _validate_invocation(invocation, program_kind)
        required = tuple(_validated_output(item, index, "required_outputs") for index, item in enumerate(required_outputs))
        optional = tuple(_validated_output(item, index, "optional_outputs") for index, item in enumerate(optional_outputs))
        if not required:
            raise ExecutionValueError("required_outputs must be non-empty")
        output_keys = tuple((item["logical_role"], item["portable_name"]) for item in (*required, *optional))
        if len(set(output_keys)) != len(output_keys):
            raise ExecutionValueError("required and optional outputs must be disjoint")
        payload = freeze_mapping(
            {
                "program_kind": program_kind,
                "adapter_id": adapter_id,
                "adapter_contract_version": adapter_contract_version,
                "exact_inputs": inputs,
                "program_data": data,
                "invocation": closed_invocation,
                "required_outputs": required,
                "optional_outputs": optional,
            },
            "ProgramExecutionSpec identity payload",
        )
        value = object.__new__(cls)
        for name, item in payload.items():
            object.__setattr__(value, name, item)
        object.__setattr__(value, "_identity_payload", payload)
        object.__setattr__(value, "program_execution_spec_id", semantic_id("program-execution-spec", payload))
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {"program_execution_spec_id": self.program_execution_spec_id, **{key: self._identity_payload[key] for key in self._identity_payload}},
            "ProgramExecutionSpec",
        )

    def assert_identity_closed(self) -> None:
        rebuilt = ProgramExecutionSpec._from_closed(
            program_kind=self.program_kind,
            adapter_id=self.adapter_id,
            adapter_contract_version=self.adapter_contract_version,
            exact_inputs=self.exact_inputs,
            program_data=self.program_data,
            invocation=self.invocation,
            required_outputs=self.required_outputs,
            optional_outputs=self.optional_outputs,
        )
        if rebuilt.semantic_payload() != self.semantic_payload():
            raise ExecutionValueError("ProgramExecutionSpec identity is stale")


def _prepare_program_execution_spec(
    *,
    program_kind: str,
    executable_path: str,
    executable_size_bytes: int,
    executable_sha256: str,
    input_name: str,
    input_bytes: bytes,
    program_data: Mapping[str, object],
) -> ProgramExecutionSpec:
    if program_kind not in _PROGRAM_KINDS:
        raise ExecutionValueError("unknown program kind")
    adapter = _ADAPTERS.get(program_kind)
    if adapter is None:
        raise ExecutionValueError("Gaussian successor is reserved but not implemented")
    validate_portable_name(input_name, "input_name")
    if not isinstance(input_bytes, bytes) or not input_bytes:
        raise ExecutionValueError("program input must be non-empty immutable bytes")
    adapter_id, version, validate_data, renderer = adapter
    data = validate_data(program_data)
    absolute_path = validate_posix_path(executable_path, "executable_path")
    if absolute_path.rsplit("/", 1)[-1] != program_kind:
        raise ExecutionValueError("executable path basename differs from program_kind")
    executable = freeze_mapping(
        {
            "absolute_path": absolute_path,
            "size_bytes": require_positive_integer(
                executable_size_bytes, "executable_size_bytes"
            ),
            "sha256": require_sha256(executable_sha256, "executable_sha256"),
        },
        "closed executable identity",
    )
    invocation, required, optional = renderer(executable, input_name, data)
    exact_input = freeze_mapping(
        {
            "logical_role": "structure",
            "portable_name": input_name,
            "format": "xyz",
            "sha256": sha256(input_bytes).hexdigest(),
            "size_bytes": len(input_bytes),
        },
        "structure input declaration",
    )
    return ProgramExecutionSpec._from_closed(
        program_kind=program_kind,
        adapter_id=adapter_id,
        adapter_contract_version=version,
        exact_inputs=(exact_input,),
        program_data=data,
        invocation=invocation,
        required_outputs=required,
        optional_outputs=optional,
    )


def _render_scheduler_artifact(
    spec: ProgramExecutionSpec,
    resources: ResolvedResourceRequest,
    cwd: str,
) -> tuple[Mapping[str, object], ...]:
    argv = tuple(spec.invocation["argv"])
    command = " ".join(shlex.quote(str(token)) for token in argv)
    program_log = next(
        str(item["portable_name"])
        for item in spec.required_outputs
        if item["logical_role"] == "program-log"
    )
    lines = [
        "#!/bin/bash",
        "# auto-g16-v31-scheduler/1",
        f"#PBS -l nodes=1:ppn={resources.cores}",
        f"#PBS -l mem={resources.memory_mb}mb",
        f"#PBS -l walltime={resources.walltime_seconds}",
    ]
    if resources.queue is not None:
        lines.append(f"#PBS -q {resources.queue}")
    lines.extend(
        (
            f"cd -- {shlex.quote(cwd)}",
            f"export OMP_NUM_THREADS={resources.cores}",
            f"exec {command} > {shlex.quote(program_log)} 2>&1",
        )
    )
    content = ("\n".join(lines) + "\n").encode("utf-8")
    return (
        freeze_mapping(
            {
                "logical_role": "scheduler-script",
                "portable_name": f"{spec.program_kind}.pbs",
                "format": "pbs-shell-utf8",
                "sha256": sha256(content).hexdigest(),
                "size_bytes": len(content),
                "content_utf8": content.decode("utf-8"),
            },
            "scheduler artifact",
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ProgramExecutionSnapshot:
    program_execution_snapshot_id: str
    attempt_id: str
    effect_intent_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    program_execution_spec: ProgramExecutionSpec
    program_execution_spec_payload_sha256: str
    project_physical_binding: ProjectPhysicalBinding
    resolved_resource_request: ResolvedResourceRequest
    resolved_server_profile: ResolvedServerProfile
    workspace_binding: WorkspaceBinding
    cwd_binding: Mapping[str, object]
    scheduler_artifacts: tuple[Mapping[str, object], ...]
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ProgramExecutionSnapshot is created only by the successor service")

    @property
    def program_execution_spec_id(self) -> str:
        return self.program_execution_spec.program_execution_spec_id

    @property
    def project_physical_binding_id(self) -> str:
        return self.project_physical_binding.project_physical_binding_id

    @classmethod
    def _from_verified(cls, *, payload: Mapping[str, object], effect_intent_id: str, snapshot_id: str, spec: ProgramExecutionSpec, binding: ProjectPhysicalBinding, resources: ResolvedResourceRequest, profile: ResolvedServerProfile, workspace: WorkspaceBinding) -> ProgramExecutionSnapshot:
        value = object.__new__(cls)
        object.__setattr__(value, "program_execution_snapshot_id", snapshot_id)
        object.__setattr__(value, "effect_intent_id", effect_intent_id)
        object.__setattr__(value, "program_execution_spec", spec)
        object.__setattr__(value, "project_physical_binding", binding)
        object.__setattr__(value, "resolved_resource_request", resources)
        object.__setattr__(value, "resolved_server_profile", profile)
        object.__setattr__(value, "workspace_binding", workspace)
        for name in ("attempt_id", "calculation_plan_id", "calculation_plan_revision", "program_execution_spec_payload_sha256", "cwd_binding", "scheduler_artifacts"):
            object.__setattr__(value, name, payload[name])
        object.__setattr__(value, "_identity_payload", payload)
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {"program_execution_snapshot_id": self.program_execution_snapshot_id, "effect_intent_id": self.effect_intent_id, **{key: self._identity_payload[key] for key in self._identity_payload}},
            "ProgramExecutionSnapshot",
        )

    def assert_identity_closed(self) -> None:
        self.program_execution_spec.assert_identity_closed()
        self.project_physical_binding.assert_identity_closed()
        self.resolved_resource_request.assert_identity_closed()
        self.resolved_server_profile.assert_identity_closed()
        self.workspace_binding.assert_identity_closed()
        if semantic_sha256(self.program_execution_spec.semantic_payload()) != self.program_execution_spec_payload_sha256:
            raise ExecutionValueError("ProgramExecutionSpec payload hash is stale")
        expected_intent = semantic_id("program-effect-intent", self._identity_payload)
        if expected_intent != self.effect_intent_id:
            raise ExecutionValueError("successor effect intent identity is stale")
        snapshot_payload = freeze_mapping(
            {"effect_intent_id": expected_intent, **{key: self._identity_payload[key] for key in self._identity_payload}},
            "ProgramExecutionSnapshot verification payload",
        )
        if semantic_id("program-execution-snapshot", snapshot_payload) != self.program_execution_snapshot_id:
            raise ExecutionValueError("ProgramExecutionSnapshot identity is stale")


def _reattested_project_location(
    binding: ProjectPhysicalBinding,
    workspace: WorkspaceBinding,
    *,
    location_kind: str,
    project_directory: str,
) -> tuple[str, str]:
    attempt_directories = {
        "local": workspace.local_attempt_dir,
        "server": workspace.remote_attempt_dir,
        "rtwin": workspace.rtwin_attempt_dir,
    }
    attempt_directory = attempt_directories.get(location_kind)
    if attempt_directory is None:
        raise ExecutionValueError(
            "fresh Project proof has no matching Attempt workspace"
        )
    matching = tuple(
        location
        for location in binding.locations
        if location["location_kind"] == location_kind
        and location["project_directory"] == project_directory
    )
    if len(matching) != 1:
        raise ExecutionValueError(
            "fresh Project proof does not select one exact bound location"
        )
    if location_kind == "rtwin":
        require_windows_contained(
            attempt_directory,
            project_directory,
            "successor Attempt workspace",
        )
    else:
        require_contained(
            attempt_directory,
            project_directory,
            "successor Attempt workspace",
        )
    return location_kind, attempt_directory


def _prepare_program_execution_snapshot(
    store: SQLiteRuntimeStore,
    *,
    attempt_id: str,
    calculation_plan_id: str,
    resource_spec_id: str,
    program_execution_spec: ProgramExecutionSpec,
    project_physical_binding: ProjectPhysicalBinding,
    resolved_resource_request: ResolvedResourceRequest,
    resolved_server_profile: ResolvedServerProfile,
    workspace_binding: WorkspaceBinding,
    project_reattestation: _ProjectBindingReattestation,
) -> ProgramExecutionSnapshot:
    if not isinstance(store, SQLiteRuntimeStore):
        raise ExecutionValueError("successor preparation requires the exact Core store")
    attempt = store.load_attempt(require_text(attempt_id, "attempt_id"))
    task = store.load_task(attempt.task_id)
    workflow = store.load_workflow_run(task.workflow_run_id)
    project = store.load_project(workflow.project_id)
    plan: CalculationPlan = store.load_calculation_plan(require_text(calculation_plan_id, "calculation_plan_id"))
    resource: ResourceSpec = store.load_resource_spec(require_text(resource_spec_id, "resource_spec_id"))
    if plan.task_id != task.task_id or resource.task_id != task.task_id:
        raise ExecutionValueError("Attempt, plan, and resources must belong to one Task")
    for value, expected, label in (
        (program_execution_spec, ProgramExecutionSpec, "program_execution_spec"),
        (project_physical_binding, ProjectPhysicalBinding, "project_physical_binding"),
        (resolved_resource_request, ResolvedResourceRequest, "resolved_resource_request"),
        (resolved_server_profile, ResolvedServerProfile, "resolved_server_profile"),
        (workspace_binding, WorkspaceBinding, "workspace_binding"),
    ):
        if not isinstance(value, expected):
            raise ExecutionValueError(f"{label} has an invalid type")
        value.assert_identity_closed()
    if project_physical_binding.project_id != project.project_id or workspace_binding.project_id != project.project_id:
        raise ExecutionValueError("Project physical or workspace binding belongs to another Project")
    if workspace_binding.attempt_id != attempt.attempt_id:
        raise ExecutionValueError("workspace binding belongs to another Attempt")
    if resolved_resource_request.resource_spec_id != resource.resource_spec_id:
        raise ExecutionValueError("resolved resources differ from the loaded ResourceSpec")
    executable = program_execution_spec.invocation["executable_identity"]
    runtime_identity = resolved_server_profile.runtime_identities.get(
        program_execution_spec.program_kind
    )
    if not isinstance(runtime_identity, Mapping):
        raise ExecutionValueError("resolved target/profile lacks the exact program runtime identity")
    if (
        runtime_identity.get("sha256") != executable["sha256"]  # type: ignore[index]
        or runtime_identity.get("size_bytes") != executable["size_bytes"]  # type: ignore[index]
    ):
        raise ExecutionValueError("bound executable differs from resolved runtime identity")
    proof_kind, proof_project_directory = _consume_project_binding_reattestation(
        project_physical_binding, project_reattestation
    )
    target_location_kind = "server"
    if proof_kind != target_location_kind:
        raise ExecutionValueError(
            "fresh Project proof does not reattest the resolved target location"
        )
    matching_target = tuple(
        location
        for location in project_physical_binding.locations
        if location["location_kind"] == target_location_kind
        and location["reviewed_root"] == resolved_server_profile.remote_root
        and location["project_directory"] == proof_project_directory
    )
    if len(matching_target) != 1:
        raise ExecutionValueError(
            "fresh Project proof does not match the resolved target root"
        )
    cwd_kind, cwd = _reattested_project_location(
        project_physical_binding,
        workspace_binding,
        location_kind=proof_kind,
        project_directory=proof_project_directory,
    )
    scheduler = _render_scheduler_artifact(program_execution_spec, resolved_resource_request, cwd)
    spec_digest = semantic_sha256(program_execution_spec.semantic_payload())
    payload = freeze_mapping(
        {
            "attempt_id": attempt.attempt_id,
            "calculation_plan_id": plan.calculation_plan_id,
            "calculation_plan_revision": plan.revision,
            "program_execution_spec_id": program_execution_spec.program_execution_spec_id,
            "program_execution_spec_payload_sha256": spec_digest,
            "project_physical_binding_id": project_physical_binding.project_physical_binding_id,
            "resolved_resource_request_id": resolved_resource_request.resolved_resource_request_id,
            "resolved_server_profile_id": resolved_server_profile.resolved_server_profile_id,
            "workspace_binding_id": workspace_binding.workspace_binding_id,
            "cwd_binding": {"location_kind": cwd_kind, "path": cwd},
            "scheduler_artifacts": scheduler,
        },
        "ProgramExecutionSnapshot identity payload",
    )
    effect_intent_id = semantic_id("program-effect-intent", payload)
    snapshot_payload = freeze_mapping(
        {"effect_intent_id": effect_intent_id, **{key: payload[key] for key in payload}},
        "ProgramExecutionSnapshot payload",
    )
    snapshot_id = semantic_id("program-execution-snapshot", snapshot_payload)
    snapshot = ProgramExecutionSnapshot._from_verified(
        payload=payload,
        effect_intent_id=effect_intent_id,
        snapshot_id=snapshot_id,
        spec=program_execution_spec,
        binding=project_physical_binding,
        resources=resolved_resource_request,
        profile=resolved_server_profile,
        workspace=workspace_binding,
    )
    snapshot.assert_identity_closed()
    return snapshot


__all__ = ["ProgramExecutionSnapshot", "ProgramExecutionSpec"]
