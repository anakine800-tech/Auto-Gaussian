"""Adversarial minimum-classification evidence over attributed Result facts."""

from __future__ import annotations

import unittest

from auto_g16.core import AttemptState
from auto_g16.result import CaptureCompleteness, InputBinding, ParseStatus
from auto_g16.scientific_validation import (
    MinimumValidationClassification as Classification,
    validate_minimum,
)

from ._fixtures import stored_chain


class MinimumValidationServiceTests(unittest.TestCase):
    def validate(self, **options: object):  # type: ignore[no-untyped-def]
        core, binding, envelope, outcome = stored_chain(**options)
        self.addCleanup(core.close)
        return core, validate_minimum(core, binding, envelope, outcome)

    def test_exact_supported_minimum_is_deterministic_and_zero_effect(self) -> None:
        core, first = self.validate()
        before = core.attempt_state("attempt-1")
        _core, second = self.validate()
        self.assertEqual(first, second)
        self.assertEqual(first.minimum_validation_outcome_id, second.minimum_validation_outcome_id)
        self.assertIs(first.classification, Classification.VALIDATED_MINIMUM)
        self.assertEqual(first.reason_code, "validated-minimum")
        self.assertEqual(core.attempt_state("attempt-1"), before)
        self.assertIs(before, AttemptState.PLANNED)

    def test_negative_threshold_is_exact_and_zero_is_non_imaginary(self) -> None:
        for frequencies, classification, reason in (
            ((-1e-12, 100.0, 200.0), Classification.NOT_MINIMUM, "negative-frequency"),
            ((0.0, 100.0, 200.0), Classification.VALIDATED_MINIMUM, "validated-minimum"),
        ):
            with self.subTest(frequencies=frequencies):
                _core, item = self.validate(facts_options={"frequencies": frequencies})
                self.assertIs(item.classification, classification)
                self.assertEqual(item.reason_code, reason)

    def test_atom_and_mode_support_boundaries_follow_frozen_precedence(self) -> None:
        cases = (
            ({"atom_numbers": (1, 1), "frequencies": ()}, Classification.UNSUPPORTED, "unsupported-atom-cardinality"),
            ({"atom_numbers": (8, 0, 1)}, Classification.UNSUPPORTED, "unsupported-dummy-center"),
            ({"frequencies": (100.0, 200.0)}, Classification.INCOMPLETE, "incomplete-mode-count"),
            ({"frequencies": (100.0, 200.0, 300.0, 400.0)}, Classification.UNSUPPORTED, "unsupported-mode-count"),
        )
        for facts_options, classification, reason in cases:
            with self.subTest(reason=reason):
                _core, item = self.validate(facts_options=facts_options)
                self.assertIs(item.classification, classification)
                self.assertEqual(item.reason_code, reason)

    def test_only_complete_post_stationary_frequency_suffix_is_used(self) -> None:
        options = {
            "frequency_specs": (
                (70, 80, (-999.0,)),
                (140, 150, (0.0, 100.0)),
                (160, 170, (200.0,)),
            )
        }
        _core, item = self.validate(facts_options=options)
        self.assertIs(item.classification, Classification.VALIDATED_MINIMUM)
        self.assertEqual(item.selected_frequencies_cm1, (0.0, 100.0, 200.0))
        self.assertEqual(len(item.selected_frequency_blocks), 2)

    def test_grammar2_composite_terminals_and_cross_component_opt_freq_validate(self) -> None:
        _core, item = self.validate(
            parser_version="1.1.0",
            facts_options={
                "terminal_specs": (
                    ("normal-termination", 200, 220),
                    ("normal-termination", 880, 900),
                ),
                "optimization_spans": ((100, 110), (400, 410)),
                "stationary_spans": ((120, 130), (420, 430)),
                "frequency_specs": ((140, 150, (100.0, 200.0, 300.0)),),
            },
        )
        self.assertIs(item.classification, Classification.VALIDATED_MINIMUM)
        self.assertEqual(item.reason_code, "validated-minimum")
        self.assertEqual(item.accepted_optimization_span["start"], 100)  # type: ignore[index]
        self.assertEqual(item.accepted_stationary_span["start"], 120)  # type: ignore[index]
        self.assertEqual(item.selected_frequencies_cm1, (100.0, 200.0, 300.0))

    def test_grammar2_requires_frequency_after_an_accepted_stationary_pair(self) -> None:
        _core, item = self.validate(
            parser_version="1.1.0",
            facts_options={
                "terminal_specs": (
                    ("normal-termination", 200, 220),
                    ("normal-termination", 880, 900),
                ),
                "optimization_spans": ((300, 310),),
                "stationary_spans": ((320, 330),),
                "frequency_specs": ((140, 150, (100.0, 200.0, 300.0)),),
            },
        )
        self.assertIs(item.classification, Classification.INCOMPLETE)
        self.assertEqual(item.reason_code, "incomplete-marker-pair")

    def test_unique_rightmost_pre_optimization_geometry_is_selected(self) -> None:
        options = {
            "geometry_specs": (
                (10, 20, (6, 1, 1)),
                (40, 60, (8, 1, 1)),
                (200, 220, (7, 1, 1)),
            )
        }
        _core, item = self.validate(facts_options=options)
        selected = item.selected_geometry_block
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected["source_span"]["start"], 40)  # type: ignore[index]
        self.assertEqual(selected["atoms"][0]["atomic_number"], 8)  # type: ignore[index]

    def test_missing_marker_owns_combined_missing_evidence(self) -> None:
        _core, item = self.validate(
            facts_options={
                "optimization_spans": (),
                "stationary_spans": (),
                "geometry_specs": (),
                "frequency_specs": (),
            }
        )
        self.assertIs(item.classification, Classification.INCOMPLETE)
        self.assertEqual(item.reason_code, "incomplete-marker-pair")
        self.assertIsNone(item.accepted_optimization_span)
        self.assertEqual(item.selected_frequencies_cm1, ())

    def test_missing_eligible_geometry_is_incomplete_after_marker_pair(self) -> None:
        _core, item = self.validate(facts_options={"geometry_specs": ()})
        self.assertIs(item.classification, Classification.INCOMPLETE)
        self.assertEqual(item.reason_code, "incomplete-final-geometry")
        self.assertIsNotNone(item.accepted_stationary_span)

    def test_error_termination_is_incomplete(self) -> None:
        _core, item = self.validate(facts_options={"program_status": "error-termination"})
        self.assertIs(item.classification, Classification.INCOMPLETE)
        self.assertEqual(item.reason_code, "incomplete-error-termination")

    def test_parser_and_capture_matrix_precedence_is_exact(self) -> None:
        cases = (
            (
                {
                    "completeness": CaptureCompleteness.PARTIAL,
                    "parse_status": ParseStatus.PARTIAL,
                    "diagnostics": ("capture-partial",),
                },
                Classification.INCOMPLETE,
                "incomplete-capture",
            ),
            (
                {
                    "parser_name": "auto-g16-v3-gaussian-log",
                    "result_kind": "gaussian-log-facts",
                },
                Classification.UNSUPPORTED,
                "unsupported-result-tuple",
            ),
            (
                {
                    "parse_status": ParseStatus.UNSUPPORTED,
                    "diagnostics": ("unsupported-program",),
                },
                Classification.UNSUPPORTED,
                "unsupported-parse-status",
            ),
            (
                {
                    "parse_status": ParseStatus.UNPARSEABLE,
                    "diagnostics": ("unparseable-terminal",),
                },
                Classification.INCOMPLETE,
                "incomplete-parse",
            ),
        )
        for options, classification, reason in cases:
            with self.subTest(reason=reason):
                _core, item = self.validate(**options)
                self.assertIs(item.classification, classification)
                self.assertEqual(item.reason_code, reason)

    def test_unstored_or_cross_source_binding_is_incomplete_provenance(self) -> None:
        core, binding, envelope, outcome = stored_chain()
        self.addCleanup(core.close)
        forged = InputBinding(
            attempt_id=binding.attempt_id,
            calculation_plan_id=binding.calculation_plan_id,
            calculation_plan_revision=binding.calculation_plan_revision,
            prepared_input_binding_id="prepared-forged",
            execution_snapshot_id=binding.execution_snapshot_id,
            input_format=binding.input_format,
            logical_name=binding.logical_name,
            sha256=binding.sha256,
            size_bytes=binding.size_bytes,
        )
        item = validate_minimum(core, forged, envelope, outcome)
        self.assertIs(item.classification, Classification.INCOMPLETE)
        self.assertEqual(item.reason_code, "incomplete-provenance")
        self.assertIsNone(item.source_artifact)

        spliced_core, spliced_binding, spliced_envelope, spliced_outcome = stored_chain(
            facts_options={"source_changes": {"sha256": "d" * 64}},
            bypass_result_service=True,
        )
        self.addCleanup(spliced_core.close)
        spliced = validate_minimum(
            spliced_core, spliced_binding, spliced_envelope, spliced_outcome
        )
        self.assertIs(spliced.classification, Classification.INCOMPLETE)
        self.assertEqual(spliced.reason_code, "incomplete-provenance")


if __name__ == "__main__":
    unittest.main()
