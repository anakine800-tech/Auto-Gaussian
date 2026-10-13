"""Tagged identity, rendering, and adversarial drift evidence."""

from __future__ import annotations

import json
import math
import unittest

from auto_g16.review import ReviewBundleError, build_review_bundle, render_review_bundle_json
from auto_g16.review._canonical import bundle_identity, freeze_mapping

from ._fixtures import authority


class ReviewIdentityRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chain = authority()
        self.addCleanup(self.chain.close)

    def bundle(self):  # type: ignore[no-untyped-def]
        return build_review_bundle(
            self.chain.core,
            self.chain.validation,
            input_binding=self.chain.input_binding,
            output_envelope=self.chain.output_envelope,
            parse_outcome=self.chain.parse_outcome,
            minimum_validation_outcome_id=self.chain.outcome.minimum_validation_outcome_id,
        )

    def test_tagged_identity_distinguishes_bool_integer_and_sorts_mappings(self) -> None:
        self.assertNotEqual(bundle_identity({"value": True}), bundle_identity({"value": 1}))
        self.assertEqual(
            bundle_identity({"z": 2, "a": {"y": 1, "x": 0}}),
            bundle_identity({"a": {"x": 0, "y": 1}, "z": 2}),
        )

    def test_nonfinite_cycles_and_unsupported_values_fail_closed(self) -> None:
        for value in (math.inf, math.nan, object()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ValueError):
                    bundle_identity({"value": value})
        cycle: dict[str, object] = {}
        cycle["self"] = cycle
        with self.assertRaises(ValueError):
            freeze_mapping(cycle, "cycle")

    def test_json_is_exact_complete_deterministic_utf8_and_one_lf(self) -> None:
        bundle = self.bundle()
        first = render_review_bundle_json(bundle)
        second = render_review_bundle_json(bundle)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))
        decoded = json.loads(first)
        self.assertEqual(set(decoded), set(bundle.__dataclass_fields__))
        self.assertEqual(decoded["review_bundle_id"], bundle.review_bundle_id)
        self.assertEqual(first.encode("utf-8").decode("utf-8"), first)
        self.assertNotIn("current", decoded)
        self.assertNotIn("latest", decoded)

    def test_every_authority_change_changes_identity_and_forgery_rejects_render(self) -> None:
        bundle = self.bundle()
        original = bundle.review_bundle_id
        object.__setattr__(bundle, "primary_reason_code", "forged-reason")
        with self.assertRaises(ReviewBundleError):
            render_review_bundle_json(bundle)
        self.assertEqual(bundle.review_bundle_id, original)

    def test_render_rejects_non_bundle_and_has_no_filesystem_output(self) -> None:
        with self.assertRaises(ReviewBundleError):
            render_review_bundle_json({})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
