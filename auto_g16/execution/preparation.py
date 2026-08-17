"""Deterministic preparation of an immutable execution snapshot."""

from __future__ import annotations

from collections.abc import Mapping

from auto_g16.core import SQLiteRuntimeStore

from ._identity import ExecutionValueError, freeze_mapping, require_text, semantic_id
from ._paths import (
    require_contained,
    require_windows_contained,
    verify_local_parent_identity,
)
from .models import (
    ExecutionSnapshot,
    PbsTemplateBinding,
    PreparedInputBinding,
    ResolvedResourceRequest,
    ResolvedServerProfile,
    WorkspaceBinding,
)


def _without_identity(value: Mapping[str, object], identity_key: str) -> Mapping[str, object]:
    return freeze_mapping(
        {key: value[key] for key in value if key != identity_key},
        f"expanded {identity_key} payload",
    )


def assert_execution_snapshot_identity(snapshot: ExecutionSnapshot) -> None:
    """Reject a stale or forged effect-relevant snapshot before any effect seam."""

    if not isinstance(snapshot, ExecutionSnapshot):
        raise ExecutionValueError("snapshot must be an ExecutionSnapshot")
    for value, expected_type in (
        (snapshot.prepared_input_binding, PreparedInputBinding),
        (snapshot.resolved_resource_request, ResolvedResourceRequest),
        (snapshot.resolved_server_profile, ResolvedServerProfile),
        (snapshot.workspace_binding, WorkspaceBinding),
        (snapshot.pbs_template_binding, PbsTemplateBinding),
    ):
        if not isinstance(value, expected_type):
            raise ExecutionValueError("ExecutionSnapshot contains an invalid nested record")
        value.assert_identity_closed()

    if snapshot.attempt_id != snapshot.prepared_input_binding.attempt_id:
        raise ExecutionValueError("ExecutionSnapshot Attempt binding is stale")
    if snapshot.attempt_id != snapshot.workspace_binding.attempt_id:
        raise ExecutionValueError("ExecutionSnapshot workspace binding is stale")
    if snapshot.calculation_plan_id != snapshot.prepared_input_binding.calculation_plan_id:
        raise ExecutionValueError("ExecutionSnapshot plan binding is stale")
    if (
        snapshot.calculation_plan_revision
        != snapshot.prepared_input_binding.calculation_plan_revision
    ):
        raise ExecutionValueError("ExecutionSnapshot plan revision binding is stale")
    if (
        snapshot.pbs_template_binding._prepared_input_logical_name
        != snapshot.prepared_input_binding.logical_name
    ):
        raise ExecutionValueError("ExecutionSnapshot PBS input binding is stale")
    verify_local_parent_identity(
        snapshot.workspace_binding.local_attempt_dir,
        snapshot.workspace_binding._local_parent_identity,
    )
    require_contained(
        snapshot.workspace_binding.remote_attempt_dir,
        snapshot.resolved_server_profile.remote_root,
        "remote_attempt_dir",
    )
    if snapshot.workspace_binding.rtwin_attempt_dir is not None:
        rtwin_root = snapshot.resolved_server_profile.platform_paths.get("rtwin_root")
        if not isinstance(rtwin_root, str):
            raise ExecutionValueError(
                "resolved profile must provide rtwin_root for an RTwin workspace"
            )
        require_windows_contained(
            snapshot.workspace_binding.rtwin_attempt_dir,
            rtwin_root,
            "rtwin_attempt_dir",
        )

    expanded = freeze_mapping(
        {
            "attempt_id": snapshot.attempt_id,
            "calculation_plan_id": snapshot.calculation_plan_id,
            "calculation_plan_revision": snapshot.calculation_plan_revision,
            "prepared_input_binding": _without_identity(
                snapshot.prepared_input_binding.semantic_payload(),
                "prepared_input_binding_id",
            ),
            "resolved_resource_request": _without_identity(
                snapshot.resolved_resource_request.semantic_payload(),
                "resolved_resource_request_id",
            ),
            "resolved_server_profile": _without_identity(
                snapshot.resolved_server_profile.semantic_payload(),
                "resolved_server_profile_id",
            ),
            "workspace_binding": _without_identity(
                snapshot.workspace_binding.semantic_payload(), "workspace_binding_id"
            ),
            "pbs_template_binding": _without_identity(
                snapshot.pbs_template_binding.semantic_payload(),
                "pbs_template_binding_id",
            ),
            "adapter_contract_version": snapshot.adapter_contract_version,
        },
        "expanded execution inputs verification",
    )
    expected_intent = semantic_id("submission-intent", expanded)
    if expected_intent != snapshot.submission_intent_id:
        raise ExecutionValueError("ExecutionSnapshot submission intent identity is stale")
    snapshot_payload = freeze_mapping(
        {
            **{key: expanded[key] for key in expanded},
            "submission_intent_id": expected_intent,
        },
        "execution snapshot verification payload",
    )
    if semantic_id("execution-snapshot", snapshot_payload) != snapshot.execution_snapshot_id:
        raise ExecutionValueError("ExecutionSnapshot identity is stale")


def prepare_execution_snapshot(
    store: SQLiteRuntimeStore,
    *,
    attempt_id: str,
    calculation_plan_id: str,
    resource_spec_id: str,
    prepared_input_binding: PreparedInputBinding,
    resolved_resource_request: ResolvedResourceRequest,
    resolved_server_profile: ResolvedServerProfile,
    workspace_binding: WorkspaceBinding,
    pbs_template_binding: PbsTemplateBinding,
    adapter_contract_version: str,
) -> ExecutionSnapshot:
    """Load the complete Core chain and freeze one effect-relevant snapshot."""

    if not isinstance(store, SQLiteRuntimeStore):
        raise ExecutionValueError("store must be a public Core SQLiteRuntimeStore")
    require_text(attempt_id, "attempt_id")
    require_text(calculation_plan_id, "calculation_plan_id")
    require_text(resource_spec_id, "resource_spec_id")
    require_text(adapter_contract_version, "adapter_contract_version")

    attempt = store.load_attempt(attempt_id)
    task = store.load_task(attempt.task_id)
    workflow_run = store.load_workflow_run(task.workflow_run_id)
    project = store.load_project(workflow_run.project_id)
    plan = store.load_calculation_plan(calculation_plan_id)
    resources = store.load_resource_spec(resource_spec_id)

    if plan.task_id != task.task_id or resources.task_id != task.task_id:
        raise ExecutionValueError(
            "Attempt, CalculationPlan, and ResourceSpec must belong to the same Task"
        )
    if prepared_input_binding.attempt_id != attempt.attempt_id:
        raise ExecutionValueError("prepared input binding belongs to another Attempt")
    if (
        prepared_input_binding.calculation_plan_id != plan.calculation_plan_id
        or prepared_input_binding.calculation_plan_revision != plan.revision
    ):
        raise ExecutionValueError("prepared input binding does not match the loaded plan")
    if resolved_resource_request.resource_spec_id != resources.resource_spec_id:
        raise ExecutionValueError("resolved resource request does not match ResourceSpec")
    if workspace_binding.project_id != project.project_id:
        raise ExecutionValueError("workspace binding belongs to another Project")
    if workspace_binding.attempt_id != attempt.attempt_id:
        raise ExecutionValueError("workspace binding belongs to another Attempt")
    if (
        pbs_template_binding._prepared_input_logical_name
        != prepared_input_binding.logical_name
    ):
        raise ExecutionValueError("PBS template does not target the exact prepared input")
    require_contained(
        workspace_binding.remote_attempt_dir,
        resolved_server_profile.remote_root,
        "remote_attempt_dir",
    )
    if workspace_binding.rtwin_attempt_dir is not None:
        rtwin_root = resolved_server_profile.platform_paths.get("rtwin_root")
        if not isinstance(rtwin_root, str):
            raise ExecutionValueError(
                "resolved profile must provide rtwin_root for an RTwin workspace"
            )
        require_windows_contained(
            workspace_binding.rtwin_attempt_dir,
            rtwin_root,
            "rtwin_attempt_dir",
        )

    expanded = freeze_mapping(
        {
            "attempt_id": attempt.attempt_id,
            "calculation_plan_id": plan.calculation_plan_id,
            "calculation_plan_revision": plan.revision,
            "prepared_input_binding": _without_identity(
                prepared_input_binding.semantic_payload(), "prepared_input_binding_id"
            ),
            "resolved_resource_request": _without_identity(
                resolved_resource_request.semantic_payload(),
                "resolved_resource_request_id",
            ),
            "resolved_server_profile": _without_identity(
                resolved_server_profile.semantic_payload(),
                "resolved_server_profile_id",
            ),
            "workspace_binding": _without_identity(
                workspace_binding.semantic_payload(), "workspace_binding_id"
            ),
            "pbs_template_binding": _without_identity(
                pbs_template_binding.semantic_payload(), "pbs_template_binding_id"
            ),
            "adapter_contract_version": adapter_contract_version,
        },
        "expanded execution inputs",
    )
    submission_intent_id = semantic_id("submission-intent", expanded)
    snapshot_payload = freeze_mapping(
        {**{key: expanded[key] for key in expanded}, "submission_intent_id": submission_intent_id},
        "execution snapshot payload",
    )
    snapshot_id = semantic_id("execution-snapshot", snapshot_payload)
    snapshot = ExecutionSnapshot._from_verified(
        attempt_id=attempt.attempt_id,
        submission_intent_id=submission_intent_id,
        calculation_plan_id=plan.calculation_plan_id,
        calculation_plan_revision=plan.revision,
        prepared_input_binding=prepared_input_binding,
        resolved_resource_request=resolved_resource_request,
        resolved_server_profile=resolved_server_profile,
        workspace_binding=workspace_binding,
        pbs_template_binding=pbs_template_binding,
        adapter_contract_version=adapter_contract_version,
        execution_snapshot_id=snapshot_id,
    )
    assert_execution_snapshot_identity(snapshot)
    return snapshot
