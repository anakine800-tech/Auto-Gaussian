"""Public-shape and dependency contract evidence."""

from __future__ import annotations

import ast
from dataclasses import fields
import inspect
from pathlib import Path
import unittest
from uuid import UUID, uuid5

import auto_g16.scientific_validation as scientific_validation


class ScientificValidationContractTests(unittest.TestCase):
    def test_public_inventory_is_exactly_the_frozen_eleven_names(self) -> None:
        self.assertEqual(
            set(scientific_validation.__all__),
            {
                "MinimumValidationClassification",
                "MinimumValidationOutcome",
                "ScientificAcceptance",
                "SQLiteScientificValidationStore",
                "validate_minimum",
                "record_minimum_validation",
                "record_scientific_acceptance",
                "require_scientific_acceptance",
                "ScientificValidationError",
                "ScientificValidationConflictError",
                "ScientificValidationPersistenceIntegrityError",
            },
        )

    def test_record_field_inventories_are_exact_and_caller_construction_is_closed(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(scientific_validation.MinimumValidationOutcome)),
            (
                "schema_version",
                "minimum_validation_outcome_id",
                "validation_policy_id",
                "validation_policy_version",
                "calculation_plan_id",
                "calculation_plan_revision",
                "attempt_id",
                "input_binding_observation_id",
                "envelope_observation_id",
                "parse_result_id",
                "parser_name",
                "parser_version",
                "result_kind",
                "source_artifact",
                "job_section",
                "accepted_optimization_span",
                "accepted_stationary_span",
                "selected_geometry_block",
                "selected_frequency_blocks",
                "selected_frequencies_cm1",
                "classification",
                "reason_code",
            ),
        )
        self.assertEqual(
            tuple(item.name for item in fields(scientific_validation.ScientificAcceptance)),
            (
                "schema_version",
                "scientific_acceptance_id",
                "minimum_validation_outcome_id",
                "validation_policy_id",
                "validation_policy_version",
                "calculation_plan_id",
                "calculation_plan_revision",
                "attempt_id",
                "parse_result_id",
                "classification",
                "reviewer_id",
                "review_evidence",
            ),
        )
        with self.assertRaises(TypeError):
            scientific_validation.MinimumValidationOutcome()
        with self.assertRaises(TypeError):
            scientific_validation.ScientificAcceptance()

    def test_service_and_store_signatures_are_exact(self) -> None:
        self.assertEqual(
            str(inspect.signature(scientific_validation.validate_minimum)),
            "(core_store: 'SQLiteRuntimeStore', input_binding: 'InputBinding', envelope: 'OutputEnvelope', parse_outcome: 'ParseOutcome') -> 'MinimumValidationOutcome'",
        )
        self.assertEqual(
            str(inspect.signature(scientific_validation.record_minimum_validation)),
            "(store: 'SQLiteScientificValidationStore', outcome: 'MinimumValidationOutcome') -> 'MinimumValidationOutcome'",
        )
        self.assertEqual(
            str(inspect.signature(scientific_validation.record_scientific_acceptance)),
            "(store: 'SQLiteScientificValidationStore', *, minimum_validation_outcome_id: 'str', reviewer_id: 'str', review_evidence: 'Mapping[str, object]') -> 'ScientificAcceptance'",
        )
        self.assertEqual(
            str(inspect.signature(scientific_validation.require_scientific_acceptance)),
            "(store: 'SQLiteScientificValidationStore', *, minimum_validation_outcome_id: 'str', scientific_acceptance_id: 'str') -> 'tuple[MinimumValidationOutcome, ScientificAcceptance]'",
        )
        store = scientific_validation.SQLiteScientificValidationStore
        self.assertEqual(
            str(inspect.signature(store.create_new)),
            "(path: 'str | Path') -> 'SQLiteScientificValidationStore'",
        )
        self.assertEqual(
            str(inspect.signature(store.open_existing)),
            "(path: 'str | Path') -> 'SQLiteScientificValidationStore'",
        )

    def test_error_hierarchy_is_exact(self) -> None:
        self.assertIs(
            scientific_validation.ScientificValidationError.__base__, ValueError
        )
        self.assertIs(
            scientific_validation.ScientificValidationConflictError.__base__,
            scientific_validation.ScientificValidationError,
        )
        self.assertIs(
            scientific_validation.ScientificValidationPersistenceIntegrityError.__base__,
            scientific_validation.ScientificValidationError,
        )

    def test_identity_namespaces_match_the_frozen_domains(self) -> None:
        root = UUID("f4617d31-5b90-5c79-888a-9b9ccec5e612")
        self.assertEqual(
            str(uuid5(root, "auto_g16.scientific_validation/v1/minimum-validation-outcome")),
            "6b963167-a628-5135-ad33-a38383cbf137",
        )
        self.assertEqual(
            str(uuid5(root, "auto_g16.scientific_validation/v1/scientific-acceptance")),
            "333f02d6-ee57-53e6-bd43-3e02a7046e85",
        )

    def test_dependency_direction_uses_only_public_core_and_result(self) -> None:
        package = Path(scientific_validation.__file__).resolve().parent
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("auto_g16.workflow", node.module)
                    self.assertNotIn("auto_g16.approval", node.module)
                    self.assertNotIn("auto_g16.execution", node.module)
                    self.assertNotIn("auto_g16.core.", node.module)
                    self.assertNotIn("auto_g16.result.", node.module)


if __name__ == "__main__":
    unittest.main()
