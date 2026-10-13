"""Synthetic, offline fixtures for V30 approval contract tests."""

from __future__ import annotations

from pathlib import Path

import auto_g16.approval as approval
import auto_g16.core as core
import auto_g16.execution as execution


INPUT_BYTES = b"%mem=12GB\n%nprocshared=8\n#p b3lyp/6-31g(d) opt\n\njob\n\n0 1\nH 0 0 0\n\n"
TEMPLATE_BYTES = b"#!/bin/bash\n#PBS -N synthetic\nexec g16 input.gjf\n"
DISPLAYED_MEANING = {
    "method": "B3LYP/6-31G(d)",
    "job": "minimum optimization",
}


def populate_runtime_store(store: core.SQLiteRuntimeStore) -> None:
    store.store_project(core.Project(project_id="project-1"))
    store.store_workflow_run(
        core.WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="minimum",
        )
    )
    store.store_task(
        core.Task(
            task_id="task-1",
            workflow_run_id="run-1",
            task_kind="gaussian-minimum",
        )
    )
    store.store_calculation_plan(plan())
    store.store_task(
        core.Task(
            task_id="task-2",
            workflow_run_id="run-1",
            task_kind="gaussian-minimum",
        )
    )
    store.store_calculation_plan(plan_two())
    store.store_resource_spec(
        core.ResourceSpec(
            resource_spec_id="resources-1",
            task_id="task-1",
            resources={"tier": "simple"},
        )
    )
    store.create_attempt(core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1))
    store.create_attempt(core.Attempt(attempt_id="attempt-2", task_id="task-2", ordinal=1))


def plan(**changes: object) -> core.CalculationPlan:
    values: dict[str, object] = {
        "calculation_plan_id": "plan-1",
        "task_id": "task-1",
        "revision": 3,
        "intent": {
            "route": "#p b3lyp/6-31g(d) opt",
            "charge": 0,
            "multiplicity": 1,
        },
    }
    values.update(changes)
    return core.CalculationPlan(**values)  # type: ignore[arg-type]


def plan_two() -> core.CalculationPlan:
    return core.CalculationPlan(
        calculation_plan_id="plan-2",
        task_id="task-2",
        revision=1,
        intent={"route": "#p b3lyp/6-31g(d) opt", "charge": 0, "multiplicity": 1},
    )


def scientific(
    runtime_store: core.SQLiteRuntimeStore,
    current_plan: core.CalculationPlan | None = None,
    **changes: object,
) -> approval.ScientificApproval:
    values: dict[str, object] = {
        "displayed_semantic_meaning": DISPLAYED_MEANING,
        "reviewer_id": "reviewer-1",
        "reviewer_evidence": {"statement": "reviewed semantic plan"},
        "decision": approval.ApprovalDecision.APPROVED,
    }
    values.update(changes)
    return approval.ScientificApproval.for_plan(
        runtime_store, current_plan or plan(), **values  # type: ignore[arg-type]
    )


def scientific_two(runtime_store: core.SQLiteRuntimeStore) -> approval.ScientificApproval:
    return scientific(runtime_store, plan_two())


def profile() -> execution.ServerProfile:
    return execution.ServerProfile(
        server_profile_id="profile-1",
        profile_revision=7,
        transport_kind="legacy_rtwin_pbs",
        target_host="10.0.0.50",
        target_port=22,
        remote_user="user100",
        jump_topology=[("100.64.0.1", 22, "rtwin-user")],
        host_key_policy="strict",
        batch_mode=True,
        identities_only=True,
        remote_root=execution.LEGACY_REMOTE_ROOT,
        platform_paths={
            "rtwin_root": r"C:\RTWIN",
            "known_hosts": "/etc/ssh/ssh_known_hosts",
        },
        config_files=[("ssh_config", b"Host RTwin\n  HostName 100.64.0.1\n")],
        runtime_contents={
            "pbs-wrapper": b"qsub -- synthetic",
            "known-hosts": b"10.0.0.50 ssh-ed25519 synthetic",
        },
    )


def snapshot(
    store: core.SQLiteRuntimeStore,
    local_root: Path,
    *,
    attempt_id: str = "attempt-1",
    cores: int = 8,
) -> execution.ExecutionSnapshot:
    local_project = local_root / "project-1"
    local_project.mkdir(parents=True, exist_ok=True)
    prepared = execution.PreparedInputBinding(
        attempt_id=attempt_id,
        calculation_plan_id="plan-1",
        calculation_plan_revision=3,
        input_format="gaussian-gjf",
        logical_name="input.gjf",
        prepared_bytes=INPUT_BYTES,
    )
    resources = execution.ResolvedResourceRequest(
        resource_spec=store.load_resource_spec("resources-1"),
        cores=cores,
        memory_mb=12_288,
        walltime_seconds=3_600,
        queue="simple",
    )
    workspace = execution.WorkspaceBinding(
        project=store.load_project("project-1"),
        attempt_id=attempt_id,
        local_approved_root=str(local_root),
        local_attempt_dir=str(local_project / attempt_id),
        rtwin_approved_root=r"C:\RTWIN",
        rtwin_attempt_dir=rf"C:\RTWIN\project-1\{attempt_id}",
        remote_approved_root=execution.LEGACY_REMOTE_ROOT,
        remote_attempt_dir=f"/home/user100/SDL/project-1/{attempt_id}",
    )
    template = execution.PbsTemplateBinding(
        logical_name="job.pbs",
        template_bytes=TEMPLATE_BYTES,
        template_contract_version="pbs-template-v1",
        prepared_input_logical_name="input.gjf",
    )
    return execution.prepare_execution_snapshot(
        store,
        attempt_id=attempt_id,
        calculation_plan_id="plan-1",
        resource_spec_id="resources-1",
        prepared_input_binding=prepared,
        resolved_resource_request=resources,
        resolved_server_profile=execution.resolve_server_profile(profile()),
        workspace_binding=workspace,
        pbs_template_binding=template,
        adapter_contract_version="synthetic-rtwin-v1",
    )
