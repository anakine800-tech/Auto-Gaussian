"""Append-only persistence, decisions, deterministic replay, and zero-effect tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import auto_g16.core as core
import auto_g16.workflow as workflow
from auto_g16.workflow.models import _payload_text
from auto_g16.workflow.store import WorkflowStoreConflictError, WorkflowStoreSchemaError

from . import _fixtures as fx


class WorkflowStoreReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "workflow.sqlite3"
        self.core = core.SQLiteRuntimeStore()
        fx.populate_core(self.core)
        self.store = workflow.SQLiteWorkflowStore.create_new(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self.core.close()
        self.temporary.cleanup()

    def record(self, definition: workflow.WorkflowDefinition) -> None:
        workflow.record_workflow_definition(self.store, self.core, definition)

    def test_create_new_rejects_existing_and_open_existing_rejects_missing(self) -> None:
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.create_new(self.path)
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.open_existing(Path(self.temporary.name) / "missing.sqlite3")

    def test_definition_replay_is_idempotent_and_durable_reopen_is_deterministic(self) -> None:
        definition = fx.definition(nodes=(fx.node(1),))
        first = workflow.record_workflow_definition(self.store, self.core, definition)
        second = workflow.record_workflow_definition(self.store, self.core, definition)
        self.assertEqual(first, second)
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={},
        )
        before = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.store.close()
        self.store = workflow.SQLiteWorkflowStore.open_existing(self.path)
        after = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertEqual(before, after)
        self.assertEqual(after.ready_node_ids, ("node-1",))
        self.assertEqual(after.run_outcome, "active")

    def test_reopen_rejects_wrong_version_extra_schema_and_noncanonical_payload(self) -> None:
        definition = fx.definition(nodes=(fx.node(1),))
        self.record(definition)
        self.store.close()
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE extra(value TEXT)")
        connection.close()
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.open_existing(self.path)

        other = Path(self.temporary.name) / "wrong.sqlite3"
        connection = sqlite3.connect(other)
        connection.execute("PRAGMA user_version = 99")
        connection.close()
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.open_existing(other)

        semantic = Path(self.temporary.name) / "semantic-invalid.sqlite3"
        semantic_store = workflow.SQLiteWorkflowStore.create_new(semantic)
        semantic_store.close()
        invalid = fx.definition(
            nodes=(fx.node(1, inputs=("in",), outputs=("out",)),),
            edges=(fx.edge("self", "node-1", "node-1"),),
        )
        connection = sqlite3.connect(semantic)
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "INSERT INTO workflow_definitions(workflow_definition_id,payload_json) VALUES(?,?)",
            (invalid.workflow_definition_id, _payload_text(invalid._payload())),
        )
        connection.commit()
        connection.close()
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.open_existing(semantic)

        noncanonical = Path(self.temporary.name) / "noncanonical.sqlite3"
        noncanonical_store = workflow.SQLiteWorkflowStore.create_new(noncanonical)
        noncanonical_store.close()
        valid = fx.definition(nodes=(fx.node(1),))
        canonical_payload = _payload_text(valid._payload())
        pretty_payload = json.dumps(json.loads(canonical_payload), indent=2)
        connection = sqlite3.connect(noncanonical)
        connection.execute(
            "INSERT INTO workflow_definitions(workflow_definition_id,payload_json) VALUES(?,?)",
            (valid.workflow_definition_id, pretty_payload),
        )
        connection.commit()
        connection.close()
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.open_existing(noncanonical)

    def test_reopen_rejects_symlink_and_replacement_identity(self) -> None:
        target = Path(self.temporary.name) / "target.sqlite3"
        target.write_bytes(b"not sqlite")
        link = Path(self.temporary.name) / "link.sqlite3"
        link.symlink_to(target)
        with self.assertRaises(Exception):
            workflow.SQLiteWorkflowStore.open_existing(link)

    def test_human_gate_decision_is_deterministic_append_only_and_conflicting_review_fails(self) -> None:
        definition = fx.definition(
            nodes=(fx.node(1),),
            gates=(workflow.HumanGate(
                human_gate_id="gate", target_node_ids=("node-1",), prompt="review",
            ),),
        )
        self.record(definition)
        first = workflow.record_human_gate_decision(
            self.store, definition.workflow_definition_id, "gate", "approved",
            "reviewer", {"ticket": "synthetic"},
        )
        second = workflow.record_human_gate_decision(
            self.store, definition.workflow_definition_id, "gate", "approved",
            "reviewer", {"ticket": "synthetic"},
        )
        self.assertEqual(first, second)
        with self.assertRaises(Exception):
            workflow.record_human_gate_decision(
                self.store, definition.workflow_definition_id, "gate", "rejected",
                "reviewer", {"ticket": "changed"},
            )

    def test_gate_filters_active_target_and_inactive_approval_never_activates_branch(self) -> None:
        condition = workflow.Condition(
            condition_id="condition", source_node_id="node-1", predicate="attempt_state_in",
            expected_states=(core.AttemptState.SUCCEEDED,),
            true_edge_ids=("true",), false_edge_ids=("false",),
        )
        definition = fx.definition(
            nodes=(
                fx.node(1, outputs=("out",)),
                fx.node(2, inputs=("in",)),
                fx.node(3, inputs=("in",)),
            ),
            edges=(
                fx.edge("true", "node-1", "node-2", condition_id="condition", branch="true"),
                fx.edge("false", "node-1", "node-3", condition_id="condition", branch="false"),
            ),
            conditions=(condition,),
            gates=(
                workflow.HumanGate(
                    human_gate_id="inactive-gate", target_node_ids=("node-2",), prompt="review true",
                ),
                workflow.HumanGate(
                    human_gate_id="active-gate", target_node_ids=("node-3",), prompt="review false",
                ),
            ),
        )
        self.record(definition)
        workflow.record_human_gate_decision(
            self.store, definition.workflow_definition_id, "inactive-gate", "approved",
            "reviewer", {"scope": "inactive"},
        )
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        fx.finish(self.core, "attempt-1", core.AttemptState.FAILED)
        workflow.record_condition_decision(
            self.store, self.core, definition.workflow_definition_id, evaluation, "condition"
        )
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertEqual(view.active_node_ids, ("node-1", "node-3"))
        self.assertNotIn("node-2", view.active_node_ids)
        self.assertEqual(view.pending_node_ids, ("node-3",))
        workflow.record_human_gate_decision(
            self.store, definition.workflow_definition_id, "active-gate", "approved",
            "reviewer", {"scope": "active"},
        )
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertEqual(view.ready_node_ids, ("node-3",))

    def test_condition_decision_derives_complete_branch_and_survives_reopen(self) -> None:
        condition = workflow.Condition(
            condition_id="condition", source_node_id="node-1", predicate="attempt_state_in",
            expected_states=(core.AttemptState.SUCCEEDED,),
            true_edge_ids=("z-true", "a-true"), false_edge_ids=("false",),
        )
        definition = fx.definition(
            nodes=(
                fx.node(1, outputs=("out",)),
                fx.node(2, inputs=("in",)),
                fx.node(3, inputs=("in",)),
                fx.node(4, inputs=("in",)),
            ),
            edges=(
                fx.edge("z-true", "node-1", "node-2", condition_id="condition", branch="true"),
                fx.edge("a-true", "node-1", "node-3", condition_id="condition", branch="true"),
                fx.edge("false", "node-1", "node-4", condition_id="condition", branch="false"),
            ),
            conditions=(condition,),
        )
        self.record(definition)
        fx.finish(self.core, "attempt-1", core.AttemptState.SUCCEEDED)
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        decision = workflow.record_condition_decision(
            self.store, self.core, definition.workflow_definition_id, evaluation, "condition"
        )
        self.assertEqual(decision.selected_edge_ids, ("a-true", "z-true"))
        self.store.close()
        self.store = workflow.SQLiteWorkflowStore.open_existing(self.path)
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertEqual(view.active_node_ids, ("node-1", "node-2", "node-3"))
        self.assertEqual(view.ready_node_ids, ("node-2", "node-3"))
        self.assertEqual(view.condition_decision_ids, (decision.condition_decision_id,))

    def test_recovery_child_uses_its_exact_decision_without_parent_history_poisoning(self) -> None:
        condition = workflow.Condition(
            condition_id="condition", source_node_id="node-1",
            predicate="attempt_state_in",
            expected_states=(core.AttemptState.SUCCEEDED,),
            true_edge_ids=("true",), false_edge_ids=("false",),
        )
        definition = fx.definition(
            nodes=(
                fx.node(1, outputs=("out",)),
                fx.node(2, inputs=("in",)),
                fx.node(3, inputs=("in",)),
            ),
            edges=(
                fx.edge(
                    "true", "node-1", "node-2",
                    condition_id="condition", branch="true",
                ),
                fx.edge(
                    "false", "node-1", "node-3",
                    condition_id="condition", branch="false",
                ),
            ),
            conditions=(condition,),
        )
        self.record(definition)

        fx.finish(self.core, "attempt-1", core.AttemptState.FAILED)
        parent_evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        parent_decision = workflow.record_condition_decision(
            self.store, self.core, definition.workflow_definition_id,
            parent_evaluation, "condition",
        )
        self.core.create_child_attempt(
            "attempt-1",
            core.Attempt(
                attempt_id="attempt-child", task_id="task-1", ordinal=2,
            ),
        )
        fx.finish(self.core, "attempt-child", core.AttemptState.SUCCEEDED)
        child_evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-child"},
        )

        before_child_decision = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id,
            child_evaluation,
        )
        self.assertEqual(before_child_decision.active_node_ids, ("node-1",))
        self.assertEqual(before_child_decision.pending_node_ids, ("node-1",))
        self.assertEqual(before_child_decision.condition_decision_ids, ())

        child_decision = workflow.record_condition_decision(
            self.store, self.core, definition.workflow_definition_id,
            child_evaluation, "condition",
        )
        child_view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id,
            child_evaluation,
        )
        self.assertEqual(child_view.active_node_ids, ("node-1", "node-2"))
        self.assertEqual(
            child_view.condition_decision_ids, (child_decision.condition_decision_id,)
        )

        parent_view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id,
            parent_evaluation,
        )
        self.assertEqual(parent_view.active_node_ids, ("node-1", "node-3"))
        self.assertEqual(
            parent_view.condition_decision_ids, (parent_decision.condition_decision_id,)
        )
        self.assertEqual(
            {record.condition_decision_id for record in self.store._load_condition_decisions(
                definition.workflow_definition_id
            )},
            {parent_decision.condition_decision_id, child_decision.condition_decision_id},
        )

        competing_child = workflow.ConditionDecision._create(
            workflow_definition_id=definition.workflow_definition_id,
            workflow_run_id=definition.workflow_run_id,
            condition_id="condition", node_id="node-1",
            attempt_id="attempt-child", observed_state=core.AttemptState.FAILED,
            selected_edge_ids=("false",),
        )
        with self.assertRaises(WorkflowStoreConflictError):
            self.store._record_condition_decision(competing_child)
        spliced_node = workflow.ConditionDecision._create(
            workflow_definition_id=definition.workflow_definition_id,
            workflow_run_id=definition.workflow_run_id,
            condition_id="condition", node_id="node-2",
            attempt_id="attempt-2", observed_state=core.AttemptState.SUCCEEDED,
            selected_edge_ids=("true",),
        )
        with self.assertRaises(WorkflowStoreSchemaError):
            self.store._record_condition_decision(spliced_node)
        spliced_condition = workflow.ConditionDecision._create(
            workflow_definition_id=definition.workflow_definition_id,
            workflow_run_id=definition.workflow_run_id,
            condition_id="other-condition", node_id="node-1",
            attempt_id="attempt-2", observed_state=core.AttemptState.SUCCEEDED,
            selected_edge_ids=("true",),
        )
        with self.assertRaises(WorkflowStoreSchemaError):
            self.store._record_condition_decision(spliced_condition)

        cross_attempt = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-2"},
        )
        with self.assertRaises(ValueError):
            workflow.replay_workflow(
                self.store, self.core, definition.workflow_definition_id,
                cross_attempt,
            )
        cross_definition = workflow.WorkflowEvaluationInput(
            workflow_definition_id="another-definition",
            node_attempt_ids={"node-1": "attempt-child"},
        )
        with self.assertRaises(ValueError):
            workflow.replay_workflow(
                self.store, self.core, definition.workflow_definition_id,
                cross_definition,
            )

        self.store.close()
        self.store = workflow.SQLiteWorkflowStore.open_existing(self.path)
        replayed_child = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id,
            child_evaluation,
        )
        self.assertEqual(replayed_child, child_view)
        self.assertEqual(
            len(self.store._load_condition_decisions(definition.workflow_definition_id)), 2
        )

    def test_condition_rejects_missing_running_unknown_and_cross_task_attempts(self) -> None:
        definition = fx.definition(
            nodes=(
                fx.node(1, outputs=("out",)),
                fx.node(2, inputs=("in",)),
                fx.node(3, inputs=("in",)),
            ),
            edges=(
                fx.edge("yes", "node-1", "node-2", condition_id="c", branch="true"),
                fx.edge("no", "node-1", "node-3", condition_id="c", branch="false"),
            ),
            conditions=(workflow.Condition(
                condition_id="c", source_node_id="node-1", predicate="attempt_state_in",
                expected_states=(core.AttemptState.SUCCEEDED,),
                true_edge_ids=("yes",), false_edge_ids=("no",),
            ),),
        )
        self.record(definition)
        missing = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id, node_attempt_ids={}
        )
        with self.assertRaises(ValueError):
            workflow.record_condition_decision(
                self.store, self.core, definition.workflow_definition_id, missing, "c"
            )
        planned = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        with self.assertRaises(ValueError):
            workflow.record_condition_decision(
                self.store, self.core, definition.workflow_definition_id, planned, "c"
            )
        cross = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-2"},
        )
        with self.assertRaises(ValueError):
            workflow.record_condition_decision(
                self.store, self.core, definition.workflow_definition_id, cross, "c"
            )
        fx.finish(self.core, "attempt-1", core.AttemptState.UNKNOWN)
        with self.assertRaises(ValueError):
            workflow.record_condition_decision(
                self.store, self.core, definition.workflow_definition_id, planned, "c"
            )
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, planned
        )
        self.assertEqual(view.condition_decision_ids, ())

    def test_unknown_and_failed_always_predecessor_block_without_retry_or_core_transition(self) -> None:
        definition = fx.definition(
            nodes=(fx.node(1, outputs=("out",)), fx.node(2, inputs=("in",))),
            edges=(fx.edge("edge", "node-1", "node-2"),),
        )
        self.record(definition)
        fx.finish(self.core, "attempt-1", core.AttemptState.UNKNOWN)
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        before = self.core.attempt_state("attempt-1")
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        after = self.core.attempt_state("attempt-1")
        self.assertIs(before, core.AttemptState.UNKNOWN)
        self.assertIs(after, before)
        self.assertEqual(view.blocked_node_ids, ("node-1", "node-2"))
        self.assertEqual(view.run_outcome, "blocked")
        self.assertEqual(self.core.parent_attempt_id("attempt-1"), None)

    def test_map_dependency_participates_in_active_projection_and_readiness(self) -> None:
        definition = fx.definition(
            nodes=(fx.node(1, outputs=("out",)), fx.node(2, inputs=("in",))),
            maps=(workflow.Map(
                map_id="map", source_node_id="node-1", source_output_role="out",
                items=(("item", "node-2", "in"),),
            ),),
        )
        self.record(definition)
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        first = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertIn("node-2", first.pending_node_ids)
        fx.finish(self.core, "attempt-1", core.AttemptState.SUCCEEDED)
        second = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertEqual(second.ready_node_ids, ("node-2",))

    def test_replay_never_applies_a_decision_without_its_exact_attempt(self) -> None:
        definition = fx.definition(
            nodes=(
                fx.node(1, outputs=("out",)), fx.node(2, inputs=("in",)),
                fx.node(3, inputs=("in",)),
            ),
            edges=(
                fx.edge("yes", "node-1", "node-2", condition_id="c", branch="true"),
                fx.edge("no", "node-1", "node-3", condition_id="c", branch="false"),
            ),
            conditions=(workflow.Condition(
                condition_id="c", source_node_id="node-1", predicate="attempt_state_in",
                expected_states=(core.AttemptState.SUCCEEDED,),
                true_edge_ids=("yes",), false_edge_ids=("no",),
            ),),
        )
        self.record(definition)
        fx.finish(self.core, "attempt-1", core.AttemptState.SUCCEEDED)
        bound = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        workflow.record_condition_decision(
            self.store, self.core, definition.workflow_definition_id, bound, "c"
        )
        unbound = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={},
        )
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, unbound
        )
        self.assertEqual(view.active_node_ids, ("node-1",))
        self.assertEqual(view.ready_node_ids, ("node-1",))
        self.assertEqual(view.condition_decision_ids, ())

    def test_single_terminal_root_is_orchestration_complete_not_scientific_acceptance(self) -> None:
        definition = fx.definition(nodes=(fx.node(1),))
        self.record(definition)
        fx.finish(self.core, "attempt-1", core.AttemptState.SUCCEEDED)
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id=definition.workflow_definition_id,
            node_attempt_ids={"node-1": "attempt-1"},
        )
        view = workflow.replay_workflow(
            self.store, self.core, definition.workflow_definition_id, evaluation
        )
        self.assertEqual(view.terminal_node_ids, ("node-1",))
        self.assertEqual(view.run_outcome, "completed")
        self.assertFalse(hasattr(view, "scientific_acceptance"))
        self.assertFalse(hasattr(view, "execution_success"))


if __name__ == "__main__":
    unittest.main()
