"""Pure validation, decision recording, and deterministic Workflow replay."""

from __future__ import annotations

from collections.abc import Mapping

from auto_g16.core import AttemptState, SQLiteRuntimeStore

from ._validation import validate_definition_structure
from .models import (
    ConditionDecision,
    HumanGateDecision,
    WorkflowDefinition,
    WorkflowEvaluationInput,
    WorkflowRunView,
    WorkflowValueError,
)
from .store import SQLiteWorkflowStore, WorkflowStoreConflictError


_TERMINAL = frozenset(
    {AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.NOT_SUBMITTED}
)


def _workflow_store(value: object) -> SQLiteWorkflowStore:
    if not isinstance(value, SQLiteWorkflowStore):
        raise WorkflowValueError("store must be a SQLiteWorkflowStore")
    return value


def _core_store(value: object) -> SQLiteRuntimeStore:
    if not isinstance(value, SQLiteRuntimeStore):
        raise WorkflowValueError("core_store must be a SQLiteRuntimeStore")
    return value


def validate_workflow_definition(
    core_store: SQLiteRuntimeStore, definition: WorkflowDefinition
) -> None:
    """Validate one complete finite definition against exact public Core records."""

    core_store = _core_store(core_store)
    if not isinstance(definition, WorkflowDefinition):
        raise WorkflowValueError("definition must be a WorkflowDefinition")
    validate_definition_structure(definition)
    run = core_store.load_workflow_run(definition.workflow_run_id)
    if run.workflow_name != definition.workflow_name:
        raise WorkflowValueError("WorkflowDefinition name does not match its Core WorkflowRun")

    for node in definition.nodes:
        task = core_store.load_task(node.task_id)
        if task.workflow_run_id != definition.workflow_run_id:
            raise WorkflowValueError("Node Task belongs to another WorkflowRun")
        plan = core_store.load_calculation_plan(node.calculation_plan_id)
        if (
            plan.task_id != node.task_id
            or plan.revision != node.calculation_plan_revision
        ):
            raise WorkflowValueError("Node CalculationPlan binding is cross-Task or stale")

def record_workflow_definition(
    store: SQLiteWorkflowStore,
    core_store: SQLiteRuntimeStore,
    definition: WorkflowDefinition,
) -> WorkflowDefinition:
    store = _workflow_store(store)
    validate_workflow_definition(core_store, definition)
    store._record_definition(definition)
    return definition


def _evaluation_states(
    core_store: SQLiteRuntimeStore,
    definition: WorkflowDefinition,
    evaluation_input: WorkflowEvaluationInput,
) -> dict[str, AttemptState]:
    if not isinstance(evaluation_input, WorkflowEvaluationInput):
        raise WorkflowValueError("evaluation_input must be a WorkflowEvaluationInput")
    if evaluation_input.workflow_definition_id != definition.workflow_definition_id:
        raise WorkflowValueError("evaluation input belongs to another WorkflowDefinition")
    nodes = {node.node_id: node for node in definition.nodes}
    states: dict[str, AttemptState] = {}
    for node_id, attempt_id in evaluation_input.node_attempt_ids.items():
        node = nodes.get(node_id)
        if node is None:
            raise WorkflowValueError("evaluation input references an unknown Node")
        attempt = core_store.load_attempt(str(attempt_id))
        if attempt.task_id != node.task_id:
            raise WorkflowValueError("evaluation Attempt belongs to another Task")
        states[node_id] = core_store.attempt_state(attempt.attempt_id)
    return states


def record_condition_decision(
    store: SQLiteWorkflowStore,
    core_store: SQLiteRuntimeStore,
    workflow_definition_id: str,
    evaluation_input: WorkflowEvaluationInput,
    condition_id: str,
) -> ConditionDecision:
    store = _workflow_store(store)
    core_store = _core_store(core_store)
    definition = store._load_definition(workflow_definition_id)
    validate_workflow_definition(core_store, definition)
    states = _evaluation_states(core_store, definition, evaluation_input)
    conditions = {item.condition_id: item for item in definition.conditions}
    condition = conditions.get(condition_id)
    if condition is None:
        raise WorkflowValueError("condition_id does not belong to the WorkflowDefinition")
    attempt_id = evaluation_input.node_attempt_ids.get(condition.source_node_id)
    if attempt_id is None:
        raise WorkflowValueError("Condition source Node has no supplied Attempt")
    observed_state = states[condition.source_node_id]
    if observed_state not in _TERMINAL:
        raise WorkflowValueError("Condition requires exact closed terminal Attempt state")
    selected = (
        condition.true_edge_ids
        if observed_state in condition.expected_states
        else condition.false_edge_ids
    )
    decision = ConditionDecision._create(
        workflow_definition_id=definition.workflow_definition_id,
        workflow_run_id=definition.workflow_run_id,
        condition_id=condition.condition_id,
        node_id=condition.source_node_id,
        attempt_id=str(attempt_id),
        observed_state=observed_state,
        selected_edge_ids=selected,
    )
    store._record_condition_decision(decision)
    return decision


def record_human_gate_decision(
    store: SQLiteWorkflowStore,
    workflow_definition_id: str,
    human_gate_id: str,
    decision: str,
    reviewer_id: str,
    review_evidence: Mapping[str, object],
) -> HumanGateDecision:
    store = _workflow_store(store)
    definition = store._load_definition(workflow_definition_id)
    if human_gate_id not in {gate.human_gate_id for gate in definition.human_gates}:
        raise WorkflowValueError("human_gate_id does not belong to the WorkflowDefinition")
    record = HumanGateDecision._create(
        workflow_definition_id=definition.workflow_definition_id,
        workflow_run_id=definition.workflow_run_id,
        human_gate_id=human_gate_id,
        decision=decision,
        reviewer_id=reviewer_id,
        review_evidence=review_evidence,
    )
    store._record_human_gate_decision(record)
    return record


def replay_workflow(
    store: SQLiteWorkflowStore,
    core_store: SQLiteRuntimeStore,
    workflow_definition_id: str,
    evaluation_input: WorkflowEvaluationInput,
) -> WorkflowRunView:
    store = _workflow_store(store)
    core_store = _core_store(core_store)
    definition = store._load_definition(workflow_definition_id)
    validate_workflow_definition(core_store, definition)
    states = _evaluation_states(core_store, definition, evaluation_input)
    nodes = {node.node_id: node for node in definition.nodes}
    condition_history = store._load_condition_decisions(workflow_definition_id)
    # The load attests all append-only history; replay projects only the exact
    # source Attempt authority supplied for this evaluation.
    condition_records = tuple(
        record
        for record in condition_history
        if evaluation_input.node_attempt_ids.get(record.node_id) == record.attempt_id
    )
    gate_records = store._load_human_gate_decisions(workflow_definition_id)
    condition_decisions = {record.condition_id: record for record in condition_records}
    gate_decisions = {record.human_gate_id: record for record in gate_records}

    for record in condition_records:
        expected_attempt = evaluation_input.node_attempt_ids.get(record.node_id)
        if expected_attempt != record.attempt_id or states.get(record.node_id) is not record.observed_state:
            raise WorkflowStoreConflictError(
                "persisted ConditionDecision cannot be spliced into the evaluation input/Core state"
            )

    incoming_all = {node_id: 0 for node_id in nodes}
    for edge in definition.edges:
        incoming_all[edge.target_node_id] += 1
    for mapping in definition.maps:
        for _key, target_node_id, _role in mapping.items:
            incoming_all[target_node_id] += 1
    active = {node_id for node_id, count in incoming_all.items() if count == 0}
    active_edges: set[str] = set()
    active_map_items: set[tuple[str, str]] = set()
    changed = True
    while changed:
        changed = False
        for edge in definition.edges:
            if edge.source_node_id not in active:
                continue
            selected = edge.branch == "always"
            if edge.branch != "always":
                decision = condition_decisions.get(str(edge.condition_id))
                selected = decision is not None and edge.edge_id in decision.selected_edge_ids
            if selected:
                active_edges.add(edge.edge_id)
                if edge.target_node_id not in active:
                    active.add(edge.target_node_id)
                    changed = True
        for mapping in definition.maps:
            if mapping.source_node_id not in active:
                continue
            for item_key, target_node_id, _role in mapping.items:
                active_map_items.add((mapping.map_id, item_key))
                if target_node_id not in active:
                    active.add(target_node_id)
                    changed = True

    producer_nodes: dict[tuple[str, str], list[str]] = {}
    predecessor_requirements: dict[str, list[tuple[str, bool]]] = {
        node_id: [] for node_id in nodes
    }
    for edge in definition.edges:
        if edge.edge_id in active_edges:
            producer_nodes.setdefault((edge.target_node_id, edge.target_input_role), []).append(
                edge.source_node_id
            )
            predecessor_requirements[edge.target_node_id].append(
                (edge.source_node_id, edge.branch == "always")
            )
    for mapping in definition.maps:
        for item_key, target_node_id, target_role in mapping.items:
            if (mapping.map_id, item_key) in active_map_items:
                producer_nodes.setdefault((target_node_id, target_role), []).append(
                    mapping.source_node_id
                )
                predecessor_requirements[target_node_id].append(
                    (mapping.source_node_id, True)
                )

    gate_for_node: dict[str, str] = {}
    for gate in definition.human_gates:
        for node_id in gate.target_node_ids:
            gate_for_node[node_id] = gate.human_gate_id
    conditions_for_node: dict[str, list[str]] = {}
    for condition in definition.conditions:
        conditions_for_node.setdefault(condition.source_node_id, []).append(condition.condition_id)

    ready: set[str] = set()
    pending: set[str] = set()
    blocked: set[str] = set()
    terminal = {node_id for node_id in active if states.get(node_id) in _TERMINAL}
    nonterminal_attempt = False
    for node_id in sorted(active):
        state = states.get(node_id)
        node = nodes[node_id]
        reasons_blocked = state is AttemptState.UNKNOWN
        reasons_pending = False
        if state is not None and state not in _TERMINAL and state is not AttemptState.UNKNOWN:
            nonterminal_attempt = True
        for condition_id in conditions_for_node.get(node_id, []):
            if state in _TERMINAL and condition_id not in condition_decisions:
                reasons_pending = True
        gate_id = gate_for_node.get(node_id)
        if gate_id is not None:
            gate = gate_decisions.get(gate_id)
            if gate is None:
                reasons_pending = True
            elif gate.decision == "rejected":
                reasons_blocked = True
        for role in node.input_roles:
            producers = producer_nodes.get((node_id, role), [])
            if len(producers) != 1:
                reasons_pending = True
        for predecessor, require_success in predecessor_requirements[node_id]:
            predecessor_state = states.get(predecessor)
            if predecessor_state is AttemptState.UNKNOWN:
                reasons_blocked = True
            elif require_success and predecessor_state in {
                AttemptState.FAILED,
                AttemptState.NOT_SUBMITTED,
            }:
                reasons_blocked = True
            elif require_success and predecessor_state is not AttemptState.SUCCEEDED:
                reasons_pending = True
            elif not require_success and predecessor_state not in _TERMINAL:
                reasons_pending = True
        if reasons_blocked:
            blocked.add(node_id)
        elif reasons_pending:
            pending.add(node_id)
        elif state is None:
            ready.add(node_id)

    required_condition_ids = {
        condition.condition_id
        for condition in definition.conditions
        if condition.source_node_id in active and states.get(condition.source_node_id) in _TERMINAL
    }
    required_gate_ids = {
        gate.human_gate_id
        for gate in definition.human_gates
        if any(node_id in active for node_id in gate.target_node_ids)
    }
    decisions_closed = required_condition_ids.issubset(condition_decisions) and all(
        gate_decisions.get(gate_id) is not None
        and gate_decisions[gate_id].decision == "approved"
        for gate_id in required_gate_ids
    )
    if active.issubset(terminal) and decisions_closed and not blocked:
        outcome = "completed"
    elif ready or nonterminal_attempt:
        outcome = "active"
    elif blocked:
        outcome = "blocked"
    else:
        outcome = "pending"

    return WorkflowRunView(
        workflow_definition_id=definition.workflow_definition_id,
        workflow_run_id=definition.workflow_run_id,
        active_node_ids=tuple(active),
        ready_node_ids=tuple(ready),
        pending_node_ids=tuple(pending),
        blocked_node_ids=tuple(blocked),
        terminal_node_ids=tuple(terminal),
        condition_decision_ids=tuple(record.condition_decision_id for record in condition_records),
        human_gate_decision_ids=tuple(record.human_gate_decision_id for record in gate_records),
        run_outcome=outcome,
    )
