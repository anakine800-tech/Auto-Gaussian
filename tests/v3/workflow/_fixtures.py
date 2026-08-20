"""Synthetic offline fixtures for V30-4 Workflow tests."""

from __future__ import annotations

from collections.abc import Sequence

import auto_g16.core as core
import auto_g16.workflow as workflow


def populate_core(store: core.SQLiteRuntimeStore, *, count: int = 5) -> None:
    store.store_project(core.Project(project_id="project-1"))
    store.store_workflow_run(
        core.WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="synthetic-workflow",
        )
    )
    for index in range(1, count + 1):
        store.store_task(
            core.Task(
                task_id=f"task-{index}",
                workflow_run_id="run-1",
                task_kind="synthetic",
            )
        )
        store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id=f"plan-{index}",
                task_id=f"task-{index}",
                revision=index,
                intent={"fixture": index},
            )
        )
        store.create_attempt(
            core.Attempt(
                attempt_id=f"attempt-{index}",
                task_id=f"task-{index}",
                ordinal=1,
            )
        )


def node(
    index: int,
    *,
    node_id: str | None = None,
    inputs: Sequence[str] = (),
    outputs: Sequence[str] = (),
) -> workflow.Node:
    return workflow.Node(
        node_id=node_id or f"node-{index}",
        task_id=f"task-{index}",
        calculation_plan_id=f"plan-{index}",
        calculation_plan_revision=index,
        node_kind="opaque-synthetic",
        input_roles=tuple(inputs),
        output_roles=tuple(outputs),
    )


def definition(
    *,
    nodes: Sequence[workflow.Node],
    edges: Sequence[workflow.Edge] = (),
    maps: Sequence[workflow.Map] = (),
    conditions: Sequence[workflow.Condition] = (),
    gates: Sequence[workflow.HumanGate] = (),
) -> workflow.WorkflowDefinition:
    return workflow.WorkflowDefinition(
        schema_version=1,
        workflow_run_id="run-1",
        workflow_name="synthetic-workflow",
        nodes=tuple(nodes),
        edges=tuple(edges),
        maps=tuple(maps),
        conditions=tuple(conditions),
        human_gates=tuple(gates),
    )


def edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    source_role: str = "out",
    target_role: str = "in",
    condition_id: str | None = None,
    branch: str = "always",
) -> workflow.Edge:
    return workflow.Edge(
        edge_id=edge_id,
        source_node_id=source,
        source_output_role=source_role,
        target_node_id=target,
        target_input_role=target_role,
        condition_id=condition_id,
        branch=branch,
    )


def finish(
    store: core.SQLiteRuntimeStore,
    attempt_id: str,
    state: core.AttemptState,
) -> None:
    intent_id = f"intent-{attempt_id}"
    store.record_submission_intent(attempt_id, intent_id)
    if state is core.AttemptState.UNKNOWN:
        store.record_submission_outcome(
            attempt_id, intent_id, core.SubmissionOutcome.UNKNOWN
        )
        return
    store.record_submission_outcome(
        attempt_id, intent_id, core.SubmissionOutcome.SUBMITTED
    )
    if state is core.AttemptState.RUNNING:
        store.advance_attempt(attempt_id, state)
    elif state in {core.AttemptState.SUCCEEDED, core.AttemptState.FAILED}:
        store.advance_attempt(attempt_id, state)
    else:
        raise AssertionError(f"unsupported fixture terminal state: {state}")
