from __future__ import annotations

import ast
from pathlib import Path
import unittest

import auto_g16.approval as approval


# Frozen V30-3A acceptance conditions -> executable owning evidence.
ACCEPTANCE_CASES = {
    1: ("test_scientific_identity_replay_and_nonauthority_metadata_invariance",),
    2: ("test_each_scientific_authority_change_changes_identity_or_is_stale",),
    3: ("test_each_scientific_authority_change_changes_identity_or_is_stale",),
    4: ("test_operational_confirmation_replay_and_nested_snapshot_drift",),
    5: ("test_batch_is_exact_order_invariant_and_deduplicated",),
    6: ("test_batch_rejects_unlisted_future_replacement_and_recovery_child",),
    7: ("test_recovery_child_reuses_science_but_requires_new_batch_membership",),
    8: ("test_unknown_attempt_cannot_acquire_batch_or_retry_authority",),
    9: ("test_operational_confirmation_replay_and_nested_snapshot_drift",),
    10: ("test_operational_confirmation_replay_and_nested_snapshot_drift",),
    11: ("test_pure_chain_validation_is_unspliced_and_zero_effect",),
    12: ("test_no_effectful_composition_api_is_public",),
    13: ("test_chain_rejects_cross_attempt_plan_snapshot_and_stale_member",),
    14: ("test_unknown_attempt_cannot_acquire_batch_or_retry_authority",),
    15: ("test_three_domains_are_separated", "test_same_identity_different_payload_conflicts_for_every_domain"),
    16: ("test_acceptance_inventory_covers_all_frozen_conditions",),
    17: ("test_dependency_direction_is_approval_to_public_core_and_execution_only",),
}


class ApprovalContractInventoryTests(unittest.TestCase):
    def test_acceptance_inventory_covers_all_frozen_conditions(self) -> None:
        self.assertEqual(set(ACCEPTANCE_CASES), set(range(1, 18)))
        self.assertTrue(all(names for names in ACCEPTANCE_CASES.values()))

    def test_dependency_direction_is_approval_to_public_core_and_execution_only(self) -> None:
        repository = Path(__file__).resolve().parents[3]
        approval_sources = sorted((repository / "auto_g16" / "approval").glob("*.py"))
        for source in approval_sources:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("auto_g16.core.", node.module)
                    self.assertNotIn("auto_g16.execution.", node.module)
        for package in ("core", "execution", "result"):
            for source in (repository / "auto_g16" / package).glob("*.py"):
                self.assertNotIn(
                    "auto_g16.approval",
                    source.read_text(encoding="utf-8"),
                    msg=f"reverse approval dependency in {source}",
                )
        self.assertIn("validate_effect_authority", approval.__all__)
        self.assertNotIn("execute_once", approval.__all__)


if __name__ == "__main__":
    unittest.main()
