"""Public inventory, immutable records, identities, and dependency tests."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
import unittest

import auto_g16.core as core
import auto_g16.workflow as workflow

from . import _fixtures as fx


ROOT = Path(__file__).resolve().parents[3]


class PublicContractTests(unittest.TestCase):
    def test_public_inventory_is_exact(self) -> None:
        self.assertEqual(
            set(workflow.__all__),
            {
                "Node", "Edge", "Map", "Condition", "HumanGate",
                "WorkflowDefinition", "WorkflowEvaluationInput",
                "ConditionDecision", "HumanGateDecision", "WorkflowRunView",
                "SQLiteWorkflowStore", "record_workflow_definition",
                "validate_workflow_definition", "record_condition_decision",
                "record_human_gate_decision", "replay_workflow",
            },
        )
        for forbidden in (
            "execute", "submit", "retry", "cancel", "cleanup", "callback",
            "plugin", "shell", "eval",
        ):
            self.assertNotIn(forbidden, workflow.__all__)

    def test_record_fields_are_exact_keyword_only_and_frozen(self) -> None:
        expected = {
            workflow.Node: (
                "node_id", "task_id", "calculation_plan_id",
                "calculation_plan_revision", "node_kind", "input_roles", "output_roles",
            ),
            workflow.Edge: (
                "edge_id", "source_node_id", "source_output_role", "target_node_id",
                "target_input_role", "condition_id", "branch",
            ),
            workflow.Map: ("map_id", "source_node_id", "source_output_role", "items"),
            workflow.Condition: (
                "condition_id", "source_node_id", "predicate", "expected_states",
                "true_edge_ids", "false_edge_ids",
            ),
            workflow.HumanGate: ("human_gate_id", "target_node_ids", "prompt"),
            workflow.WorkflowDefinition: (
                "schema_version", "workflow_definition_id", "workflow_run_id",
                "workflow_name", "nodes", "edges", "maps", "conditions", "human_gates",
            ),
            workflow.WorkflowEvaluationInput: (
                "workflow_definition_id", "node_attempt_ids",
            ),
            workflow.ConditionDecision: (
                "condition_decision_id", "workflow_definition_id", "workflow_run_id",
                "condition_id", "node_id", "attempt_id", "observed_state",
                "selected_edge_ids",
            ),
            workflow.HumanGateDecision: (
                "human_gate_decision_id", "workflow_definition_id", "workflow_run_id",
                "human_gate_id", "decision", "reviewer_id", "review_evidence",
            ),
            workflow.WorkflowRunView: (
                "workflow_definition_id", "workflow_run_id", "active_node_ids",
                "ready_node_ids", "pending_node_ids", "blocked_node_ids",
                "terminal_node_ids", "condition_decision_ids",
                "human_gate_decision_ids", "run_outcome",
            ),
        }
        for record, names in expected.items():
            with self.subTest(record=record.__name__):
                fields = dataclasses.fields(record)
                self.assertEqual(tuple(item.name for item in fields), names)
                self.assertTrue(all(item.kw_only for item in fields))
        item = fx.node(1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.node_id = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            workflow.Node("node", "task", "plan", 1, "kind", (), ())  # type: ignore[misc]

    def test_store_public_lifecycle_is_exact(self) -> None:
        names = {
            name
            for name, value in inspect.getmembers(workflow.SQLiteWorkflowStore)
            if not name.startswith("_") and callable(value)
        }
        self.assertEqual(names, {"create_new", "open_existing", "close"})
        with self.assertRaises(TypeError):
            workflow.SQLiteWorkflowStore()  # type: ignore[call-arg]

    def test_public_function_signatures_have_no_callback_or_effect_seam(self) -> None:
        expected = {
            workflow.record_workflow_definition: ("store", "core_store", "definition"),
            workflow.validate_workflow_definition: ("core_store", "definition"),
            workflow.record_condition_decision: (
                "store", "core_store", "workflow_definition_id",
                "evaluation_input", "condition_id",
            ),
            workflow.record_human_gate_decision: (
                "store", "workflow_definition_id", "human_gate_id", "decision",
                "reviewer_id", "review_evidence",
            ),
            workflow.replay_workflow: (
                "store", "core_store", "workflow_definition_id", "evaluation_input",
            ),
        }
        for function, parameters in expected.items():
            with self.subTest(function=function.__name__):
                self.assertEqual(tuple(inspect.signature(function).parameters), parameters)

    def test_component_collections_are_canonical_and_definition_identity_is_order_invariant(self) -> None:
        first = fx.definition(nodes=(fx.node(2), fx.node(1)))
        second = fx.definition(nodes=(fx.node(1), fx.node(2)))
        self.assertEqual(first, second)
        self.assertEqual(first.workflow_definition_id, second.workflow_definition_id)
        self.assertEqual(tuple(node.node_id for node in first.nodes), ("node-1", "node-2"))

    def test_local_identifier_reuse_with_changed_semantics_changes_definition_identity(self) -> None:
        first = fx.definition(nodes=(fx.node(1, node_id="local"),))
        changed = workflow.Node(
            node_id="local",
            task_id="task-1",
            calculation_plan_id="plan-1",
            calculation_plan_revision=1,
            node_kind="changed-opaque-kind",
            input_roles=(),
            output_roles=(),
        )
        second = fx.definition(nodes=(changed,))
        self.assertNotEqual(first.workflow_definition_id, second.workflow_definition_id)
        self.assertEqual(first.nodes[0].node_id, second.nodes[0].node_id)

    def test_component_local_ids_are_not_uuid_authority_and_no_circular_computation_occurs(self) -> None:
        condition = workflow.Condition(
            condition_id="condition-local",
            source_node_id="source",
            predicate="attempt_state_in",
            expected_states=(core.AttemptState.SUCCEEDED,),
            true_edge_ids=("edge-true",),
            false_edge_ids=("edge-false",),
        )
        definition = fx.definition(
            nodes=(
                fx.node(1, node_id="source", outputs=("out",)),
                fx.node(2, node_id="true", inputs=("in",)),
                fx.node(3, node_id="false", inputs=("in",)),
            ),
            edges=(
                fx.edge("edge-true", "source", "true", condition_id="condition-local", branch="true"),
                fx.edge("edge-false", "source", "false", condition_id="condition-local", branch="false"),
            ),
            conditions=(condition,),
        )
        self.assertEqual(definition.conditions[0].condition_id, "condition-local")
        self.assertEqual(definition.edges[0].condition_id, "condition-local")
        self.assertEqual(len(definition.workflow_definition_id), 36)

    def test_canonical_roles_map_items_states_and_evidence_are_deeply_immutable(self) -> None:
        item = workflow.Node(
            node_id="node", task_id="task-1", calculation_plan_id="plan-1",
            calculation_plan_revision=1, node_kind="opaque",
            input_roles=("z", "a"), output_roles=("y", "b"),
        )
        mapping = workflow.Map(
            map_id="map", source_node_id="node", source_output_role="b",
            items=(("z", "node-3", "in"), ("a", "node-2", "in")),
        )
        self.assertEqual(item.input_roles, ("a", "z"))
        self.assertEqual(tuple(row[0] for row in mapping.items), ("a", "z"))
        evaluation = workflow.WorkflowEvaluationInput(
            workflow_definition_id="definition", node_attempt_ids={"node": "attempt"}
        )
        with self.assertRaises(TypeError):
            evaluation.node_attempt_ids["node"] = "changed"  # type: ignore[index]

    def test_value_records_reject_duplicates_open_predicates_and_dynamic_values(self) -> None:
        invalid = (
            lambda: fx.node(1, inputs=("x", "x")),
            lambda: workflow.Map(
                map_id="m", source_node_id="node-1", source_output_role="out",
                items=(("same", "node-2", "in"), ("same", "node-3", "in")),
            ),
            lambda: workflow.Condition(
                condition_id="c", source_node_id="node-1", predicate="python_callback",
                expected_states=(core.AttemptState.SUCCEEDED,),
                true_edge_ids=("a",), false_edge_ids=("b",),
            ),
            lambda: workflow.WorkflowEvaluationInput(
                workflow_definition_id="definition", node_attempt_ids={"node": object()}
            ),
        )
        for factory in invalid:
            with self.subTest(factory=factory), self.assertRaises((TypeError, ValueError)):
                factory()

    def test_dependency_direction_and_source_exclude_effect_frameworks(self) -> None:
        workflow_sources = sorted((ROOT / "auto_g16" / "workflow").glob("*.py"))
        for source in workflow_sources:
            text = source.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(source))
            for forbidden in (
                "subprocess", "socket", "paramiko", "asyncio", "eval(", "exec(",
                "auto_g16.approval", "auto_g16.execution", "auto_g16.result",
            ):
                self.assertNotIn(forbidden, text, msg=f"forbidden surface in {source}")
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    if node.module.startswith("auto_g16"):
                        self.assertEqual(node.module, "auto_g16.core")
        for package in ("core", "approval", "execution", "result"):
            for source in (ROOT / "auto_g16" / package).glob("*.py"):
                self.assertNotIn("auto_g16.workflow", source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
