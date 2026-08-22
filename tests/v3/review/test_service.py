"""Projection, provenance, acceptance, and zero-authority tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from auto_g16.core import AttemptState, SQLiteRuntimeStore
from auto_g16.result import InputBinding, OutputEnvelope, ParseOutcome
from auto_g16.review import (
    ReviewAcceptanceState,
    ReviewBundleError,
    build_review_bundle,
)
from auto_g16.scientific_validation import SQLiteScientificValidationStore

from ._fixtures import ReviewAuthority, authority


class ReviewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chain = authority()
        self.addCleanup(self.chain.close)

    def build(
        self,
        chain: ReviewAuthority | None = None,
        *,
        acceptance_ids: tuple[str, ...] = (),
        **overrides: object,
    ):
        current = self.chain if chain is None else chain
        values = {
            "input_binding": current.input_binding,
            "output_envelope": current.output_envelope,
            "parse_outcome": current.parse_outcome,
            "minimum_validation_outcome_id": current.outcome.minimum_validation_outcome_id,
            "scientific_acceptance_ids": acceptance_ids,
        }
        values.update(overrides)
        return build_review_bundle(current.core, current.validation, **values)  # type: ignore[arg-type]

    def test_exact_projections_close_derived_ids_and_all_public_fields(self) -> None:
        bundle = self.build()
        self.assertEqual(
            set(bundle.input_binding),
            {
                "schema_version", "observation_id", "attempt_id",
                "calculation_plan_id", "calculation_plan_revision",
                "prepared_input_binding_id", "execution_snapshot_id",
                "input_format", "logical_name", "sha256", "size_bytes",
            },
        )
        self.assertEqual(
            set(bundle.output_envelope),
            {
                "schema_version", "observation_id", "attempt_id",
                "input_binding_observation_id", "execution_snapshot_id",
                "capture_source_id", "capture_sequence", "capture_status",
                "capture_completeness", "artifacts", "capture_manifest_sha256",
                "captured_at_utc",
            },
        )
        self.assertEqual(
            set(bundle.output_envelope["artifacts"][0]),  # type: ignore[index]
            {"artifact_kind", "logical_name", "sha256", "size_bytes"},
        )
        self.assertEqual(
            set(bundle.parse_outcome),
            {
                "schema_version", "result_id", "attempt_id",
                "envelope_observation_id", "parser_name", "parser_version",
                "result_kind", "parse_status", "facts", "diagnostics",
            },
        )
        self.assertEqual(
            set(bundle.minimum_validation_outcome),
            set(self.chain.outcome.__dataclass_fields__),
        )
        self.assertEqual(bundle.input_binding["observation_id"], self.chain.input_binding.observation_id)
        self.assertEqual(bundle.output_envelope["observation_id"], self.chain.output_envelope.observation_id)
        self.assertEqual(bundle.parse_outcome["result_id"], self.chain.parse_outcome.result_id)

    def test_exact_replay_is_deterministic_deeply_immutable_and_zero_effect(self) -> None:
        state = self.chain.core.attempt_state("attempt-1")
        observations = self.chain.core.observations_for_attempt("attempt-1")
        results = self.chain.core.results_for_attempt("attempt-1")
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first.review_bundle_id, second.review_bundle_id)
        with self.assertRaises(TypeError):
            first.calculation_plan["task_id"] = "other"  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            first.primary_reason_code = "other"  # type: ignore[misc]
        self.assertIs(self.chain.core.attempt_state("attempt-1"), state)
        self.assertEqual(self.chain.core.observations_for_attempt("attempt-1"), observations)
        self.assertEqual(self.chain.core.results_for_attempt("attempt-1"), results)
        self.assertEqual(
            self.chain.validation.minimum_validations_for_attempt("attempt-1"),
            (self.chain.outcome,),
        )

    def test_all_three_acceptance_states_and_sorted_explicit_set(self) -> None:
        eligible = self.build()
        self.assertIs(
            eligible.scientific_acceptance_state,
            ReviewAcceptanceState.ELIGIBLE_UNACCEPTED,
        )
        first = self.chain.accept("reviewer-z", evidence={"decision": "accept", "n": 1})
        second = self.chain.accept("reviewer-a", evidence={"decision": "accept", "n": 2})
        accepted = self.build(
            acceptance_ids=(first.scientific_acceptance_id, second.scientific_acceptance_id)
        )
        ids = tuple(item["scientific_acceptance_id"] for item in accepted.scientific_acceptances)
        self.assertEqual(ids, tuple(sorted(ids)))
        self.assertIs(accepted.scientific_acceptance_state, ReviewAcceptanceState.ACCEPTED)

        negative = authority(frequencies=(-1.0, 100.0, 200.0))
        self.addCleanup(negative.close)
        ineligible = self.build(negative)
        self.assertIs(ineligible.scientific_acceptance_state, ReviewAcceptanceState.INELIGIBLE)
        with self.assertRaises(ReviewBundleError):
            self.build(acceptance_ids=(first.scientific_acceptance_id,) * 2)

    def test_every_nonvalidated_classification_remains_a_legal_factual_bundle(self) -> None:
        cases = (
            ({"frequencies": (-1.0, 100.0, 200.0)}, "NOT_MINIMUM"),
            ({"optimization_spans": (), "stationary_spans": ()}, "INCOMPLETE"),
            ({"atom_numbers": (8, 0, 1)}, "UNSUPPORTED"),
        )
        for options, classification in cases:
            with self.subTest(classification=classification):
                chain = authority(**options)
                self.addCleanup(chain.close)
                bundle = self.build(chain)
                self.assertEqual(bundle.minimum_validation_classification.value, classification)
                self.assertIs(
                    bundle.scientific_acceptance_state,
                    ReviewAcceptanceState.INELIGIBLE,
                )
                self.assertEqual(bundle.scientific_acceptances, ())

    def test_exact_projection_survives_public_store_reopen(self) -> None:
        before = self.build()
        self.chain.core.close()
        self.chain.validation.close()
        reopened_core = SQLiteRuntimeStore(self.chain.core_path)
        reopened_validation = SQLiteScientificValidationStore.open_existing(
            self.chain.validation_path
        )
        self.addCleanup(reopened_core.close)
        self.addCleanup(reopened_validation.close)
        after = build_review_bundle(
            reopened_core,
            reopened_validation,
            input_binding=self.chain.input_binding,
            output_envelope=self.chain.output_envelope,
            parse_outcome=self.chain.parse_outcome,
            minimum_validation_outcome_id=self.chain.outcome.minimum_validation_outcome_id,
        )
        self.assertEqual(after, before)
        self.assertEqual(after.review_bundle_id, before.review_bundle_id)

    def test_selected_evidence_is_an_exact_deep_copy(self) -> None:
        bundle = self.build()
        self.assertEqual(bundle.selected_final_geometry, self.chain.outcome.selected_geometry_block)
        self.assertEqual(bundle.selected_frequency_blocks, self.chain.outcome.selected_frequency_blocks)
        self.assertEqual(bundle.selected_frequencies_cm1, self.chain.outcome.selected_frequencies_cm1)
        self.assertEqual(bundle.primary_reason_code, self.chain.outcome.reason_code)
        self.assertEqual(
            bundle.minimum_validation_classification, self.chain.outcome.classification
        )

    def test_cross_splice_and_unpersisted_typed_records_fail_closed(self) -> None:
        forged_binding = InputBinding(
            attempt_id=self.chain.input_binding.attempt_id,
            calculation_plan_id=self.chain.input_binding.calculation_plan_id,
            calculation_plan_revision=self.chain.input_binding.calculation_plan_revision,
            prepared_input_binding_id="forged",
            execution_snapshot_id=self.chain.input_binding.execution_snapshot_id,
            input_format=self.chain.input_binding.input_format,
            logical_name=self.chain.input_binding.logical_name,
            sha256=self.chain.input_binding.sha256,
            size_bytes=self.chain.input_binding.size_bytes,
        )
        forged_envelope = OutputEnvelope.from_payload(
            {
                **self.chain.output_envelope.payload(),
                "execution_snapshot_id": "snapshot-forged",
            }
        )
        forged_parse = ParseOutcome(
            attempt_id=self.chain.parse_outcome.attempt_id,
            envelope_observation_id=self.chain.parse_outcome.envelope_observation_id,
            parser_name="auto-g16-v3-gaussian-log",
            parser_version="1.0.0",
            result_kind="gaussian-log-facts",
            parse_status="parsed",
            facts={},
        )
        for override in (
            {"input_binding": forged_binding},
            {"output_envelope": forged_envelope},
            {"parse_outcome": forged_parse},
            {"minimum_validation_outcome_id": "missing"},
        ):
            with self.subTest(override=tuple(override)):
                with self.assertRaises(ReviewBundleError):
                    self.build(**override)

    def test_input_type_and_closed_acceptance_set_fail_closed(self) -> None:
        with self.assertRaises(ReviewBundleError):
            build_review_bundle(  # type: ignore[arg-type]
                self.chain.core,
                self.chain.validation,
                input_binding=self.chain.input_binding,
                output_envelope=self.chain.output_envelope,
                parse_outcome=self.chain.parse_outcome,
                minimum_validation_outcome_id=self.chain.outcome.minimum_validation_outcome_id,
                scientific_acceptance_ids=["not-a-tuple"],
            )
        self.assertIs(self.chain.core.attempt_state("attempt-1"), AttemptState.PLANNED)


if __name__ == "__main__":
    unittest.main()
