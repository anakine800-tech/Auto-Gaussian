"""Executable ownership map for all frozen V30-4 acceptance conditions."""

from __future__ import annotations

import unittest


ACCEPTANCE_CASES = {
    1: ("test_public_inventory_is_exact", "test_dependency_direction_and_source_exclude_effect_frameworks"),
    2: ("test_public_inventory_is_exact", "test_store_public_lifecycle_is_exact", "test_public_function_signatures_have_no_callback_or_effect_seam"),
    3: ("test_local_identifier_reuse_with_changed_semantics_changes_definition_identity", "test_component_local_ids_are_not_uuid_authority_and_no_circular_computation_occurs"),
    4: ("test_exact_core_workflow_task_and_plan_bindings_validate",),
    5: ("test_cross_run_cross_task_and_stale_plan_bindings_fail_closed", "test_missing_nodes_unknown_roles_self_edges_and_orphan_inputs_fail_closed"),
    6: ("test_edge_only_map_only_and_mixed_cycles_fail_closed", "test_combined_graph_topological_order_is_lexical_and_input_order_independent"),
    7: ("test_map_items_are_predeclared_role_closed_and_unambiguous",),
    8: ("test_condition_and_edge_metadata_are_one_exact_closed_relation",),
    9: ("test_condition_rejects_missing_running_unknown_and_cross_task_attempts", "test_condition_decision_derives_complete_branch_and_survives_reopen"),
    10: ("test_gate_filters_active_target_and_inactive_approval_never_activates_branch", "test_human_gate_decision_is_deterministic_append_only_and_conflicting_review_fails"),
    11: ("test_public_inventory_is_exact",),
    12: ("test_create_new_rejects_existing_and_open_existing_rejects_missing", "test_reopen_rejects_wrong_version_extra_schema_and_noncanonical_payload"),
    13: ("test_definition_replay_is_idempotent_and_durable_reopen_is_deterministic",),
    14: ("test_condition_rejects_missing_running_unknown_and_cross_task_attempts", "test_gate_filters_active_target_and_inactive_approval_never_activates_branch"),
    15: (
        "test_condition_decision_derives_complete_branch_and_survives_reopen",
        "test_recovery_child_uses_its_exact_decision_without_parent_history_poisoning",
        "test_replay_never_applies_a_decision_without_its_exact_attempt",
    ),
    16: ("test_map_dependency_participates_in_active_projection_and_readiness", "test_unknown_and_failed_always_predecessor_block_without_retry_or_core_transition"),
    17: ("test_unknown_and_failed_always_predecessor_block_without_retry_or_core_transition",),
    18: ("test_unknown_and_failed_always_predecessor_block_without_retry_or_core_transition", "test_dependency_direction_and_source_exclude_effect_frameworks"),
    19: ("test_public_inventory_is_exact", "test_dependency_direction_and_source_exclude_effect_frameworks"),
    20: ("test_acceptance_inventory_is_complete",),
}


class AcceptanceInventoryTests(unittest.TestCase):
    def test_acceptance_inventory_is_complete(self) -> None:
        self.assertEqual(set(ACCEPTANCE_CASES), set(range(1, 21)))
        self.assertTrue(all(names for names in ACCEPTANCE_CASES.values()))


if __name__ == "__main__":
    unittest.main()
