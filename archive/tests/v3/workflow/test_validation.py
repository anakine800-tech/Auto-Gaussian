"""Adversarial finite graph, mapping, branch, gate, and Core closure tests."""

from __future__ import annotations

import unittest

import auto_g16.core as core
import auto_g16.workflow as workflow
from auto_g16.workflow._validation import graph_order

from . import _fixtures as fx


class DefinitionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core = core.SQLiteRuntimeStore()
        fx.populate_core(self.core)

    def tearDown(self) -> None:
        self.core.close()

    def assert_invalid(self, definition: workflow.WorkflowDefinition, pattern: str) -> None:
        with self.assertRaisesRegex((ValueError, core.RuntimeStoreError), pattern):
            workflow.validate_workflow_definition(self.core, definition)

    def test_exact_core_workflow_task_and_plan_bindings_validate(self) -> None:
        definition = fx.definition(nodes=(fx.node(1),))
        self.assertIsNone(workflow.validate_workflow_definition(self.core, definition))

    def test_cross_run_cross_task_and_stale_plan_bindings_fail_closed(self) -> None:
        cross_task = workflow.Node(
            node_id="node", task_id="task-1", calculation_plan_id="plan-2",
            calculation_plan_revision=2, node_kind="opaque", input_roles=(), output_roles=(),
        )
        stale = workflow.Node(
            node_id="node", task_id="task-1", calculation_plan_id="plan-1",
            calculation_plan_revision=99, node_kind="opaque", input_roles=(), output_roles=(),
        )
        for item, pattern in ((cross_task, "cross-Task|stale"), (stale, "cross-Task|stale")):
            self.assert_invalid(fx.definition(nodes=(item,)), pattern)

        self.core.store_project(core.Project(project_id="project-2"))
        self.core.store_workflow_run(
            core.WorkflowRun(
                workflow_run_id="run-2", project_id="project-2",
                workflow_name="synthetic-workflow",
            )
        )
        self.core.store_task(
            core.Task(task_id="task-x", workflow_run_id="run-2", task_kind="synthetic")
        )
        self.core.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id="plan-x", task_id="task-x", revision=1, intent={}
            )
        )
        cross_run = workflow.Node(
            node_id="node", task_id="task-x", calculation_plan_id="plan-x",
            calculation_plan_revision=1, node_kind="opaque", input_roles=(), output_roles=(),
        )
        self.assert_invalid(fx.definition(nodes=(cross_run,)), "another WorkflowRun")

    def test_missing_nodes_unknown_roles_self_edges_and_orphan_inputs_fail_closed(self) -> None:
        cases = (
            fx.definition(
                nodes=(fx.node(1, outputs=("out",)),),
                edges=(fx.edge("e", "node-1", "missing"),),
            ),
            fx.definition(
                nodes=(fx.node(1, outputs=("out",)), fx.node(2, inputs=("in",))),
                edges=(fx.edge("e", "node-1", "node-2", source_role="missing"),),
            ),
            fx.definition(
                nodes=(fx.node(1, inputs=("in",), outputs=("out",)),),
                edges=(fx.edge("e", "node-1", "node-1"),),
            ),
            fx.definition(nodes=(fx.node(1, inputs=("orphan",)),)),
        )
        for definition in cases:
            with self.subTest(definition=definition.workflow_definition_id), self.assertRaises(ValueError):
                workflow.validate_workflow_definition(self.core, definition)

    def test_edge_only_map_only_and_mixed_cycles_fail_closed(self) -> None:
        edge_cycle = fx.definition(
            nodes=(
                fx.node(1, inputs=("in",), outputs=("out",)),
                fx.node(2, inputs=("in",), outputs=("out",)),
            ),
            edges=(fx.edge("a", "node-1", "node-2"), fx.edge("b", "node-2", "node-1")),
        )
        map_cycle = fx.definition(
            nodes=(
                fx.node(1, inputs=("in",), outputs=("out",)),
                fx.node(2, inputs=("in",), outputs=("out",)),
            ),
            maps=(
                workflow.Map(map_id="a", source_node_id="node-1", source_output_role="out", items=(("x", "node-2", "in"),)),
                workflow.Map(map_id="b", source_node_id="node-2", source_output_role="out", items=(("x", "node-1", "in"),)),
            ),
        )
        mixed = fx.definition(
            nodes=(
                fx.node(1, inputs=("in",), outputs=("out",)),
                fx.node(2, inputs=("in",), outputs=("out",)),
            ),
            edges=(fx.edge("a", "node-1", "node-2"),),
            maps=(workflow.Map(map_id="b", source_node_id="node-2", source_output_role="out", items=(("x", "node-1", "in"),)),),
        )
        for definition in (edge_cycle, map_cycle, mixed):
            self.assert_invalid(definition, "acyclic")

    def test_combined_graph_topological_order_is_lexical_and_input_order_independent(self) -> None:
        nodes = (
            fx.node(4, inputs=("edge-in", "map-in")),
            fx.node(3, outputs=("out",)),
            fx.node(2, outputs=("out",)),
            fx.node(1),
        )
        definition = fx.definition(
            nodes=nodes,
            edges=(fx.edge(
                "edge", "node-2", "node-4", target_role="edge-in"
            ),),
            maps=(workflow.Map(
                map_id="map", source_node_id="node-3", source_output_role="out",
                items=(("item", "node-4", "map-in"),),
            ),),
        )
        reverse = fx.definition(
            nodes=tuple(reversed(nodes)),
            edges=tuple(reversed(definition.edges)),
            maps=tuple(reversed(definition.maps)),
        )
        self.assertEqual(graph_order(definition), ("node-1", "node-2", "node-3", "node-4"))
        self.assertEqual(graph_order(definition), graph_order(reverse))

    def test_map_items_are_predeclared_role_closed_and_unambiguous(self) -> None:
        source = fx.node(1, outputs=("out",))
        target = fx.node(2, inputs=("in",))
        valid = fx.definition(
            nodes=(target, source),
            maps=(workflow.Map(
                map_id="map", source_node_id="node-1", source_output_role="out",
                items=(("item", "node-2", "in"),),
            ),),
        )
        workflow.validate_workflow_definition(self.core, valid)
        invalid = fx.definition(
            nodes=(target, source),
            maps=(workflow.Map(
                map_id="map", source_node_id="node-1", source_output_role="out",
                items=(("item", "node-2", "missing"),),
            ),),
        )
        self.assert_invalid(invalid, "unknown target input role")

    def test_condition_and_edge_metadata_are_one_exact_closed_relation(self) -> None:
        nodes = (
            fx.node(1, outputs=("out",)),
            fx.node(2, inputs=("in",)),
            fx.node(3, inputs=("in",)),
        )
        valid_condition = workflow.Condition(
            condition_id="c", source_node_id="node-1", predicate="attempt_state_in",
            expected_states=(core.AttemptState.SUCCEEDED,),
            true_edge_ids=("true",), false_edge_ids=("false",),
        )
        valid = fx.definition(
            nodes=nodes,
            edges=(
                fx.edge("true", "node-1", "node-2", condition_id="c", branch="true"),
                fx.edge("false", "node-1", "node-3", condition_id="c", branch="false"),
            ),
            conditions=(valid_condition,),
        )
        workflow.validate_workflow_definition(self.core, valid)
        mismatch = fx.definition(
            nodes=nodes,
            edges=(
                fx.edge("true", "node-1", "node-2", condition_id="c", branch="false"),
                fx.edge("false", "node-1", "node-3", condition_id="c", branch="true"),
            ),
            conditions=(valid_condition,),
        )
        self.assert_invalid(mismatch, "disagree")

    def test_mutually_exclusive_producers_are_legal_but_coactive_producers_are_rejected(self) -> None:
        nodes = (
            fx.node(1, outputs=("out",)),
            fx.node(2, outputs=("out",)),
            fx.node(3, inputs=("in",)),
        )
        ambiguous = fx.definition(
            nodes=nodes,
            edges=(
                fx.edge("one", "node-1", "node-3"),
                fx.edge("two", "node-2", "node-3"),
            ),
        )
        self.assert_invalid(ambiguous, "ambiguous producers")

        exclusive = fx.definition(
            nodes=(fx.node(1, outputs=("out",)), fx.node(3, inputs=("in",))),
            edges=(
                fx.edge("yes", "node-1", "node-3", condition_id="c", branch="true"),
                fx.edge("no", "node-1", "node-3", condition_id="c", branch="false"),
            ),
            conditions=(workflow.Condition(
                condition_id="c", source_node_id="node-1", predicate="attempt_state_in",
                expected_states=(core.AttemptState.SUCCEEDED,),
                true_edge_ids=("yes",), false_edge_ids=("no",),
            ),),
        )
        workflow.validate_workflow_definition(self.core, exclusive)

    def test_overlapping_human_gate_targets_fail_closed(self) -> None:
        definition = fx.definition(
            nodes=(fx.node(1),),
            gates=(
                workflow.HumanGate(human_gate_id="a", target_node_ids=("node-1",), prompt="a"),
                workflow.HumanGate(human_gate_id="b", target_node_ids=("node-1",), prompt="b"),
            ),
        )
        self.assert_invalid(definition, "globally disjoint")


if __name__ == "__main__":
    unittest.main()
