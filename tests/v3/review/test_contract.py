"""Exact public-shape and dependency evidence for ReviewBundle."""

from __future__ import annotations

import ast
from dataclasses import fields
import inspect
from pathlib import Path
import unittest
from uuid import UUID, uuid5

import auto_g16.review as review


class ReviewContractTests(unittest.TestCase):
    def test_public_inventory_enum_and_error_are_exact(self) -> None:
        self.assertEqual(
            set(review.__all__),
            {
                "ReviewAcceptanceState",
                "ReviewBundle",
                "ReviewBundleError",
                "build_review_bundle",
                "render_review_bundle_json",
            },
        )
        self.assertEqual(
            tuple((item.name, item.value) for item in review.ReviewAcceptanceState),
            (
                ("INELIGIBLE", "ineligible"),
                ("ELIGIBLE_UNACCEPTED", "eligible-unaccepted"),
                ("ACCEPTED", "accepted"),
            ),
        )
        self.assertIs(review.ReviewBundleError.__base__, ValueError)

    def test_bundle_fields_and_service_creation_are_exact(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(review.ReviewBundle)),
            (
                "schema_version",
                "review_bundle_id",
                "calculation_plan",
                "attempt",
                "input_binding",
                "execution_snapshot_id",
                "output_envelope",
                "parse_outcome",
                "selected_final_geometry",
                "selected_frequency_blocks",
                "selected_frequencies_cm1",
                "minimum_validation_outcome",
                "minimum_validation_classification",
                "primary_reason_code",
                "scientific_acceptance_state",
                "scientific_acceptances",
            ),
        )
        with self.assertRaises(TypeError):
            review.ReviewBundle()

    def test_public_signatures_are_exact(self) -> None:
        self.assertEqual(
            str(inspect.signature(review.build_review_bundle)),
            "(core_store: 'SQLiteRuntimeStore', validation_store: 'SQLiteScientificValidationStore', *, input_binding: 'InputBinding', output_envelope: 'OutputEnvelope', parse_outcome: 'ParseOutcome', minimum_validation_outcome_id: 'str', scientific_acceptance_ids: 'tuple[str, ...]' = ()) -> 'ReviewBundle'",
        )
        self.assertEqual(
            str(inspect.signature(review.render_review_bundle_json)),
            "(bundle: 'ReviewBundle') -> 'str'",
        )

    def test_namespace_is_exact(self) -> None:
        root = UUID("061dffea-e54e-580e-9928-e284abc0997f")
        self.assertEqual(
            str(uuid5(root, "auto_g16.review/v1/review-bundle")),
            "62e6a827-7dbf-5efe-8625-729e43bc9d46",
        )

    def test_dependency_direction_and_zero_effect_imports_are_static(self) -> None:
        package = Path(review.__file__).resolve().parent
        forbidden_modules = {
            "auto_g16.approval",
            "auto_g16.execution",
            "auto_g16.observe",
            "auto_g16.workflow",
            "subprocess",
        }
        forbidden_calls = {"open", "exec", "eval"}
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module, forbidden_modules)
                    self.assertFalse(node.module.startswith("auto_g16.core."))
                    self.assertFalse(node.module.startswith("auto_g16.result."))
                    self.assertFalse(
                        node.module.startswith("auto_g16.scientific_validation.")
                    )
                if isinstance(node, ast.Import):
                    self.assertTrue(
                        all(alias.name not in forbidden_modules for alias in node.names)
                    )
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
