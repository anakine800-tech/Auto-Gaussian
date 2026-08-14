"""Focused acceptance tests for V30-CORE-01."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import dataclasses
import inspect
import math
import unittest
from pathlib import Path

import auto_g16.core as core


ROOT = Path(__file__).resolve().parents[3]


class PublicInterfaceTests(unittest.TestCase):
    def test_public_exports_are_exact_and_exclude_execution_snapshot(self) -> None:
        expected = {
            "Attempt",
            "AttemptState",
            "AttemptStateError",
            "Batch",
            "CalculationPlan",
            "CoreValidationError",
            "Observation",
            "Project",
            "RecoveryProposal",
            "ReconciliationResolution",
            "RecordConflictError",
            "RecordNotFoundError",
            "ResourceSpec",
            "Result",
            "RuntimeStoreError",
            "RuntimeStoreSchemaError",
            "SQLiteRuntimeStore",
            "SubmissionIntentClaim",
            "SubmissionOutcome",
            "Task",
            "WorkflowRun",
        }
        self.assertEqual(set(core.__all__), expected)
        self.assertFalse(hasattr(core, "CanonicalRecord"))
        self.assertFalse(hasattr(core, "CanonicalValue"))
        self.assertFalse(hasattr(core, "ExecutionSnapshot"))

    def test_payload_signature_and_values_do_not_expose_private_encoding(self) -> None:
        signature = inspect.signature(core.CalculationPlan)
        annotation = str(signature.parameters["intent"].annotation)
        self.assertIn("Mapping[str, object]", annotation)
        self.assertNotIn("_CanonicalRecord", annotation)

        plan = core.CalculationPlan(
            calculation_plan_id="plan-1",
            task_id="task-1",
            revision=1,
            intent={"charge": 0, "route": {"method": "reviewed"}, "steps": [1, 2]},
        )
        self.assertIsInstance(plan.intent, Mapping)
        self.assertNotIsInstance(plan.intent, tuple)
        self.assertEqual(plan.intent["charge"], 0)
        self.assertEqual(plan.intent["steps"], (1, 2))
        route = plan.intent["route"]
        self.assertIsInstance(route, Mapping)
        self.assertEqual(route["method"], "reviewed")  # type: ignore[index]
        self.assertNotIn("('record'", repr(plan.intent))
        with self.assertRaises(TypeError):
            plan.intent["charge"] = 1  # type: ignore[index]
        with self.assertRaises(TypeError):
            route["method"] = "changed"  # type: ignore[index]

    def test_record_fields_match_the_frozen_contract(self) -> None:
        expected = {
            core.Project: ("project_id",),
            core.WorkflowRun: ("workflow_run_id", "project_id", "workflow_name"),
            core.Batch: ("batch_id", "workflow_run_id", "purpose"),
            core.Task: ("task_id", "workflow_run_id", "task_kind", "batch_id"),
            core.Attempt: ("attempt_id", "task_id", "ordinal"),
            core.CalculationPlan: ("calculation_plan_id", "task_id", "revision", "intent"),
            core.ResourceSpec: ("resource_spec_id", "task_id", "resources"),
            core.Observation: ("observation_id", "attempt_id", "observation_type", "data"),
            core.Result: ("result_id", "attempt_id", "result_type", "data"),
            core.RecoveryProposal: (
                "recovery_proposal_id",
                "attempt_id",
                "reason",
                "proposed_calculation_plan_id",
            ),
        }
        for record, field_names in expected.items():
            with self.subTest(record=record.__name__):
                self.assertEqual(
                    tuple(field.name for field in dataclasses.fields(record)), field_names
                )
                self.assertTrue(all(field.kw_only for field in dataclasses.fields(record)))

    def test_core_source_has_only_standard_library_or_relative_imports(self) -> None:
        allowed_roots = {
            "__future__",
            "collections",
            "contextlib",
            "dataclasses",
            "enum",
            "json",
            "math",
            "pathlib",
            "sqlite3",
            "typing",
        }
        for path in sorted((ROOT / "auto_g16" / "core").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".", 1)[0], allowed_roots)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIsNotNone(node.module)
                    self.assertIn(node.module.split(".", 1)[0], allowed_roots)


class RecordBehaviorTests(unittest.TestCase):
    def test_all_records_construct_and_preserve_references(self) -> None:
        records = (
            core.Project(project_id="project-1"),
            core.WorkflowRun(
                workflow_run_id="run-1",
                project_id="project-1",
                workflow_name="minimum",
            ),
            core.Batch(batch_id="batch-1", workflow_run_id="run-1", purpose="review"),
            core.Task(
                task_id="task-1",
                workflow_run_id="run-1",
                task_kind="calculation",
                batch_id="batch-1",
            ),
            core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1),
            core.CalculationPlan(
                calculation_plan_id="plan-1",
                task_id="task-1",
                revision=1,
                intent={"charge": 0, "method": "reviewed"},
            ),
            core.ResourceSpec(
                resource_spec_id="resources-1",
                task_id="task-1",
                resources={"cores": 8, "memory_mib": 12288},
            ),
            core.Observation(
                observation_id="observation-1",
                attempt_id="attempt-1",
                observation_type="state",
                data={"value": "planned"},
            ),
            core.Result(
                result_id="result-1",
                attempt_id="attempt-1",
                result_type="parsed",
                data={"complete": False},
            ),
            core.RecoveryProposal(
                recovery_proposal_id="recovery-1",
                attempt_id="attempt-1",
                reason="review required",
                proposed_calculation_plan_id="plan-2",
            ),
        )
        self.assertEqual(records[1].project_id, "project-1")
        self.assertEqual(records[3].batch_id, "batch-1")
        self.assertEqual(records[4].task_id, "task-1")
        self.assertEqual(records[-1].proposed_calculation_plan_id, "plan-2")

    def test_records_are_keyword_only_immutable_and_value_comparable(self) -> None:
        first = core.Project(project_id="project-1")
        second = core.Project(project_id="project-1")
        self.assertEqual(first, second)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.project_id = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            core.Project("project-1")  # type: ignore[misc]

    def test_string_contract_fails_closed_for_every_record(self) -> None:
        invalid_factories = (
            lambda: core.Project(project_id=""),
            lambda: core.WorkflowRun(
                workflow_run_id=" run-1", project_id="project-1", workflow_name="minimum"
            ),
            lambda: core.Batch(batch_id="batch-1", workflow_run_id="", purpose="review"),
            lambda: core.Task(task_id="task-1", workflow_run_id="run-1", task_kind=" "),
            lambda: core.Task(
                task_id="task-1", workflow_run_id="run-1", task_kind="kind", batch_id=""
            ),
            lambda: core.Attempt(attempt_id="attempt-1 ", task_id="task-1", ordinal=1),
            lambda: core.CalculationPlan(
                calculation_plan_id="", task_id="task-1", revision=1, intent={}
            ),
            lambda: core.ResourceSpec(resource_spec_id="resources-1", task_id=" ", resources={}),
            lambda: core.Observation(
                observation_id="observation-1",
                attempt_id="attempt-1",
                observation_type="",
            ),
            lambda: core.Result(result_id="", attempt_id="attempt-1", result_type="parsed"),
            lambda: core.RecoveryProposal(
                recovery_proposal_id="recovery-1",
                attempt_id="attempt-1",
                reason=" reason",
                proposed_calculation_plan_id="plan-2",
            ),
        )
        for factory in invalid_factories:
            with self.subTest(factory=factory), self.assertRaises(core.CoreValidationError):
                factory()

    def test_positive_integers_reject_zero_negative_and_boolean_values(self) -> None:
        for value in (0, -1, True, False, 1.5):
            with self.subTest(field="ordinal", value=value), self.assertRaises(
                core.CoreValidationError
            ):
                core.Attempt(
                    attempt_id="attempt-1",
                    task_id="task-1",
                    ordinal=value,  # type: ignore[arg-type]
                )
            with self.subTest(field="revision", value=value), self.assertRaises(
                core.CoreValidationError
            ):
                core.CalculationPlan(
                    calculation_plan_id="plan-1",
                    task_id="task-1",
                    revision=value,  # type: ignore[arg-type]
                    intent={},
                )


class CanonicalPayloadTests(unittest.TestCase):
    def test_payload_is_deeply_frozen_sorted_and_isolated_from_caller_mutation(self) -> None:
        source = {"z": [1, {"b": 2}], "a": {"x": True}}
        plan = core.CalculationPlan(
            calculation_plan_id="plan-1",
            task_id="task-1",
            revision=1,
            intent=source,
        )
        same_value = core.CalculationPlan(
            calculation_plan_id="plan-1",
            task_id="task-1",
            revision=1,
            intent={"a": {"x": True}, "z": (1, {"b": 2})},
        )
        self.assertEqual(plan, same_value)
        source["a"]["x"] = False  # type: ignore[index]
        source["z"].append(3)  # type: ignore[union-attr]
        self.assertEqual(plan, same_value)

    def test_mapping_and_sequence_shapes_remain_distinct(self) -> None:
        mapped = core.Result(
            result_id="result-1",
            attempt_id="attempt-1",
            result_type="parsed",
            data={"value": {}},
        )
        sequenced = core.Result(
            result_id="result-1",
            attempt_id="attempt-1",
            result_type="parsed",
            data={"value": []},
        )
        self.assertNotEqual(mapped, sequenced)

    def test_boolean_integer_and_float_shapes_remain_distinct(self) -> None:
        payloads = []
        for index, value in enumerate((True, 1, 1.0), start=1):
            payloads.append(
                core.Result(
                    result_id=f"result-{index}",
                    attempt_id="attempt-1",
                    result_type="parsed",
                    data={"value": value},
                ).data
            )
        self.assertEqual(len(set(payloads)), 3)

    def test_equivalent_mapping_order_produces_equal_records(self) -> None:
        first = core.ResourceSpec(
            resource_spec_id="resources-1",
            task_id="task-1",
            resources={"memory": 12, "cores": 8},
        )
        second = core.ResourceSpec(
            resource_spec_id="resources-1",
            task_id="task-1",
            resources={"cores": 8, "memory": 12},
        )
        self.assertEqual(first, second)

    def test_noncanonical_payloads_fail_closed(self) -> None:
        cycle: list[object] = []
        cycle.append(cycle)
        invalid_payloads = (
            {1: "non-string-key"},
            {"value": math.nan},
            {"value": math.inf},
            {"value": object()},
            {"value": cycle},
            ["not", "a", "mapping"],
            ("sequence", ()),
            ("record", (("b", ("integer", 1)), ("a", ("integer", 2)))),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(core.CoreValidationError):
                core.Result(
                    result_id="result-1",
                    attempt_id="attempt-1",
                    result_type="parsed",
                    data=payload,  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
