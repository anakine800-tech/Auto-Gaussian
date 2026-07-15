#!/usr/bin/env python3
"""Strict standard-library schema validation tests for asymmetric artifacts."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "scripts" / "validate_asymmetric_contract.py"
FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
SCHEMAS = ROOT / "contracts" / "asymmetric-catalysis"
SPEC = importlib.util.spec_from_file_location("validate_asymmetric_contract_strict", MODULE)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def load(path: Path) -> dict:
    return CONTRACT.load_json(path)


def artifact(path: str = "fixture://artifact") -> dict:
    return {"path": path, "sha256": "a" * 64}


def space_instance() -> dict:
    dimensions = []
    for number in range(5):
        dimensions.append(
            {
                "dimension_id": f"dimension_{number}",
                "levels": [{"level_id": f"level_{number}", "equivalence_key": f"eq_{number}", "metadata": {}}],
            }
        )
    return {
        "schema": "gaussian-asymmetric-candidate-space-spec/1",
        "study_id": "study_fixture",
        "study_sha256": "b" * 64,
        "comparison_group_id": "group_fixture",
        "candidate_id_prefix": "candidate_fixture",
        "catalyst_state_ids": ["state_fixture"],
        "geometry_dedup_tolerance_angstrom": 0.01,
        "dimensions": dimensions,
        "exclusion_rules": [],
    }


def ledger_instance() -> dict:
    return {
        "schema": "gaussian-asymmetric-candidate-ledger/1",
        "study_id": "study_fixture",
        "study_sha256": "b" * 64,
        "comparison_group_id": "group_fixture",
        "mechanism_id": "mechanism_fixture",
        "protocol_id": "protocol_fixture",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "candidate_space_spec": artifact("fixture://space"),
        "geometry_dedup_tolerance_angstrom": 0.01,
        "dimension_ids": [f"dimension_{number}" for number in range(5)],
        "entries": [],
        "excluded_combinations": [],
        "counts": {
            "enumerated": 0,
            "retained": 0,
            "logical_duplicates": 0,
            "excluded": 0,
            "materialized_unique": 0,
            "geometry_duplicates": 0,
        },
    }


def energy_instance() -> dict:
    return {
        "schema": "gaussian-asymmetric-energy-record/1",
        "result_id": "result_fixture",
        "candidate_id": "candidate_fixture",
        "energy_unit": "kcal_mol",
        "electronic_energy": -100.0,
        "thermal_gibbs_correction": 0.1,
        "comparison_free_energy": 10.0,
        "comparison_energy_definition": "common fixture zero",
        "temperature_k": 298.15,
        "standard_state": "1M",
        "low_frequency_policy": "raw harmonic fixture",
        "inventory_key": "fixture_inventory",
        "degeneracy": 1,
    }


def materializations_instance() -> dict:
    return {"schema": "gaussian-asymmetric-materializations/1", "ledger_sha256": "c" * 64, "records": []}


def metal_support_instance() -> dict:
    review_block = {
        "status": "review_required",
        "declared": {},
        "required_review": ["scientific review"],
        "blockers": ["unresolved"],
    }
    return {
        "schema": "gaussian-asymmetric-metal-support-design/1",
        "study_id": "study_fixture",
        "study_sha256": "d" * 64,
        "design_payload_sha256": "e" * 64,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "scope": {
            "priority": "transition_metal_ts_design_first",
            "current_capability": "deterministic_offline_design_and_refusal_audit",
            "output_scope": "state_space_and_ts_search_plan_only",
            "execution_scope": "no_transition_metal_execution",
            "chiral_boron_priority": "deferred_until_after_transition_metal_design",
        },
        "states": [
            {
                "state_id": "state_fixture",
                "support_status": "unsupported_transition_metal",
                "submission_decision": "refused",
                "metal_centers": [
                    {
                        "atom_index": 1,
                        "element": "Pd",
                        "formal_oxidation_state": 0,
                        "d_electron_count": None,
                        "coordination_number": 2,
                        "geometry": "unreviewed linear hypothesis",
                        "spin_hypothesis": "unreviewed singlet hypothesis",
                        "assignment_basis": "fixture",
                        "review_status": "unreviewed_hypothesis",
                    }
                ],
                "electron_accounting": review_block,
                "spin_state_space": review_block,
                "wavefunction": {**review_block, "status": "unresolved"},
                "coordination": review_block,
                "method_protocol": {**review_block, "status": "unresolved"},
                "ts_search_readiness": {
                    "status": "blocked_offline_design_only",
                    "mechanism_ids": ["mechanism_fixture"],
                    "blocking_reasons": ["runtime unavailable"],
                },
                "known_hypotheses": [],
                "unresolved": ["offline only"],
            }
        ],
        "ts_search_families": [
            {
                "mechanism_id": "mechanism_fixture",
                "active_state_id": "state_fixture",
                "channel_ids": ["channel_fixture"],
                "coordinate_changes": [
                    {"kind": "forming", "atoms": [1, 2], "description": "fixture coordinate"}
                ],
                "elementary_step_class": "unassigned_requires_review",
                "surface_model": {**review_block, "status": "unresolved"},
                "seed_strategy_candidates": [
                    {
                        "strategy_id": "strategy_single",
                        "strategy": "single_guess_hessian_guided",
                        "status": "design_candidate_not_selected",
                        "prerequisites": ["review"],
                        "limitations": ["offline only"],
                    },
                    {
                        "strategy_id": "strategy_qst",
                        "strategy": "endpoint_qst2_qst3",
                        "status": "design_candidate_not_selected",
                        "prerequisites": ["review"],
                        "limitations": ["offline only"],
                    },
                    {
                        "strategy_id": "strategy_scan",
                        "strategy": "reviewed_relaxed_coordinate_scan",
                        "status": "design_candidate_not_selected",
                        "prerequisites": ["review"],
                        "limitations": ["offline only"],
                    },
                ],
                "required_pre_ts_evidence": ["review"],
                "blockers": ["execution unavailable"],
            }
        ],
        "cross_state_rules": ["no cross-state comparison"],
        "extension_milestones": [
            {"milestone_id": "metal_m0_offline_design", "status": "implemented_offline", "deliverable": "offline design"},
            {"milestone_id": "metal_m1_review_contract", "status": "implemented_offline", "deliverable": "offline M1 review sidecar contract"},
            {"milestone_id": "metal_m1_scientific_review", "status": "pending_scientific_review", "deliverable": "scientific review"},
            {"milestone_id": "metal_m2a_candidate_audit_template", "status": "implemented_offline", "deliverable": "candidate audit template"},
        ],
        "acceptance_gates": ["review required"],
        "refusal_tests": ["submission remains refused"],
    }


def metal_ts_audit_instance() -> dict:
    instance = {
        "schema": "gaussian-asymmetric-metal-ts-audit-template/1",
        "template_id": "metal_audit_fixture",
        "design_source": {"sha256": "1" * 64},
        "candidate_source": {"sha256": "2" * 64},
        "study_id": "study_fixture",
        "candidate_id": "candidate_fixture",
        "mechanism_id": "mechanism_fixture",
        "channel_id": "channel_fixture",
        "catalyst_state_id": "state_fixture",
        "status": "blocked_pending_scientific_review",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "identity_binding": {
            "charge": 0,
            "multiplicity": 1,
            "atom_count": 2,
            "atom_order": [
                {"index": 1, "element": "Pd", "role": "metal_center"},
                {"index": 2, "element": "P", "role": "ligand_donor"},
            ],
            "metal_centers": [
                {
                    "atom_index": 1,
                    "element": "Pd",
                    "formal_oxidation_state": 0,
                    "d_electron_count": None,
                    "coordination_number": 1,
                    "geometry": "unreviewed",
                    "review_status": "unreviewed_hypothesis",
                }
            ],
            "coordinate_changes": [
                {"kind": "forming", "atoms": [1, 2], "description": "fixture coordinate"}
            ],
            "coordination_contacts": [
                {
                    "donor_atom": 2,
                    "acceptor_atom": 1,
                    "kind": "metal_coordination",
                    "distance_window_angstrom": None,
                    "review_status": "pending",
                }
            ],
        },
        "audit_sections": {
            name: {
                "status": "blocked_pending_review",
                "required_evidence": ["review evidence"],
                "rejection_conditions": ["unresolved"],
            }
            for name in (
                "electron_accounting", "spin_surface", "wavefunction",
                "coordination", "method_protocol", "ts_and_path",
            )
        },
        "seed_strategy_gate": {
            "inventory": [
                {"strategy_id": "strategy_single", "strategy": "single_guess_hessian_guided", "status": "design_candidate_not_selected"},
                {"strategy_id": "strategy_qst", "strategy": "endpoint_qst2_qst3", "status": "design_candidate_not_selected"},
                {"strategy_id": "strategy_scan", "strategy": "reviewed_relaxed_coordinate_scan", "status": "design_candidate_not_selected"},
            ],
            "selected_strategy_id": None,
            "selection_status": "not_selected",
            "selection_required": True,
        },
        "hard_rejections": ["no execution"],
        "claim_ceiling": "design_only_no_ts_or_selectivity_claim",
    }
    instance["template_payload_sha256"] = CONTRACT.payload_sha256(instance)
    return instance


def metal_result_observation_instance() -> dict:
    instance = {
        "schema": "gaussian-asymmetric-metal-result-observation/1",
        "audit_id": "metal_obs_fixture",
        "template_source": {"sha256": "1" * 64},
        "candidate_source": {"sha256": "2" * 64},
        "log_source": {"sha256": "3" * 64},
        "study_id": "study_fixture",
        "candidate_id": "candidate_fixture",
        "mechanism_id": "mechanism_fixture",
        "channel_id": "channel_fixture",
        "catalyst_state_id": "state_fixture",
        "status": "parsed_observation_blocked",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "promotion_decision": "refused",
        "parser": {
            "parser_id": "auto_g16_asymmetric_metal_log_observer_v1",
            "scope": "offline_read_only_observation",
            "g16_revision_observed": "Revision C.01",
        },
        "identity_binding": {
            "charge": 0,
            "multiplicity": 1,
            "atom_count": 2,
            "atom_order": [
                {"index": 1, "atomic_number": 46, "element": "Pd"},
                {"index": 2, "atomic_number": 15, "element": "P"},
            ],
            "charge_multiplicity_record_count": 1,
            "orientation_count": 2,
            "identity_observation_status": "matched_candidate",
        },
        "termination_observations": {
            "normal_termination_count": 1,
            "error_termination_count": 0,
            "optimization_completed_observed": True,
            "stationary_point_observed": True,
        },
        "frequency_observations": {
            "frequency_count": 2,
            "frequencies_cm_1": [-100.0, 50.0],
            "raw_imaginary_frequency_count": 1,
            "imaginary_frequencies_cm_1": [-100.0],
            "exactly_one_raw_imaginary_observed": True,
            "completeness_status": "unassessed_requires_expected_mode_count",
            "mode_review_status": "not_performed",
        },
        "wavefunction_observations": {
            "scf_done_count": 1,
            "s2_observations": [
                {"before_annihilation": 0.01, "after_annihilation": 0.0}
            ],
            "stability_statement_observed": True,
            "threshold_assessment": "not_performed_no_approved_policy",
        },
        "coordination_observations": {
            "contacts": [
                {
                    "donor_atom": 2,
                    "acceptor_atom": 1,
                    "kind": "metal_coordination",
                    "initial_distance_angstrom": 2.0,
                    "final_distance_angstrom": 2.1,
                    "distance_change_angstrom": 0.1,
                    "distance_window_angstrom": None,
                    "review_status": "observed_unreviewed_no_window",
                }
            ],
            "inventory_assessment": "not_performed_no_reviewed_windows_or_hapticity_rules",
        },
        "audit_sections": {
            name: {"status": "blocked_pending_review", "reason": "review required"}
            for name in (
                "electron_accounting", "spin_surface", "wavefunction",
                "coordination", "method_protocol", "ts_and_path",
            )
        },
        "diagnostics": ["observation only"],
        "claim_ceiling": "parsed_observation_only_no_ts_or_selectivity_claim",
    }
    instance["audit_payload_sha256"] = CONTRACT.payload_sha256(instance)
    return instance


def metal_input_observation_instance() -> dict:
    route = "#p synthetic opt=(ts) freq"
    instance = {
        "schema": "gaussian-asymmetric-metal-input-observation/1",
        "audit_id": "metal_input_obs_fixture",
        "template_source": {"sha256": "1" * 64},
        "candidate_source": {"sha256": "2" * 64},
        "scientific_review_source": {"sha256": "3" * 64},
        "input_source": {"sha256": "4" * 64},
        "study_id": "study_fixture",
        "candidate_id": "candidate_fixture",
        "mechanism_id": "mechanism_fixture",
        "channel_id": "channel_fixture",
        "catalyst_state_id": "state_fixture",
        "status": "parsed_input_observation_blocked",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "input_acceptance_decision": "not_granted_by_artifact",
        "protocol_selection_decision": "absent_not_authorized",
        "submission_decision": "refused",
        "promotion_decision": "refused",
        "parser": {
            "parser_id": "auto_g16_asymmetric_metal_input_observer_v1",
            "scope": "offline_read_only_existing_input_observation",
            "renders_input": False,
        },
        "review_binding": {
            "review_id": "review_fixture",
            "review_status": "review_contract_complete_runtime_unsupported",
            "metal_m1_scientific_review_status": "not_satisfied_synthetic_fixture",
            "scientific_acceptance_decision": "not_granted_by_artifact",
        },
        "identity_binding": {
            "charge": 0,
            "multiplicity": 1,
            "atom_count": 2,
            "atom_order": [
                {"index": 1, "atomic_number": 46, "element": "Pd"},
                {"index": 2, "atomic_number": 15, "element": "P"},
            ],
            "identity_observation_status": "matched_candidate_template_review",
        },
        "input_observations": {
            "link0_directives": [{"key": "chk", "value": "fixture.chk"}],
            "route_text": route,
            "route_sha256": hashlib.sha256(route.encode("utf-8")).hexdigest(),
            "title_line_count": 1,
            "title_sha256": "5" * 64,
            "charge": 0,
            "multiplicity": 1,
            "atom_count": 2,
            "atom_order": [
                {"index": 1, "atomic_number": 46, "element": "Pd"},
                {"index": 2, "atomic_number": 15, "element": "P"},
            ],
            "coordinate_block_sha256": "6" * 64,
            "explicit_cartesian_geometry_status": "parsed",
            "trailing_section_line_count": 0,
            "trailing_section_sha256": None,
            "contains_absolute_link0_path_observed": False,
            "task_text_observations": {
                "opt_text_observed": True,
                "freq_text_observed": True,
                "ts_text_observed": True,
                "geom_check_text_observed": False,
                "gen_or_genecp_text_observed": False,
            },
            "protocol_selection_binding_status": "absent_not_accepted",
            "remote_path_validation_status": "not_performed_offline_no_execution_authority",
        },
        "audit_sections": {
            name: {"status": "blocked_pending_review", "reason": "review required"}
            for name in (
                "electron_accounting", "spin_surface", "wavefunction",
                "coordination", "method_protocol", "ts_and_path",
            )
        },
        "completion": {
            "metal_m2c_input_observation": "implemented_offline",
            "metal_m2_offline_runtime_contract": "blocked",
            "metal_m3_execution_boundary": "blocked",
            "metal_m4_live_smoke": "blocked",
        },
        "diagnostics": ["observation only"],
        "hard_rejections": ["no execution"],
        "claim_ceiling": "existing_input_observation_only_no_acceptance_execution_ts_or_selectivity_claim",
    }
    instance["audit_payload_sha256"] = CONTRACT.payload_sha256(instance)
    return instance


def metal_scientific_review_source_instance() -> dict:
    return load(FIXTURES / "metal_scientific_review_complete.json")


def metal_scientific_review_instance() -> dict:
    source = metal_scientific_review_source_instance()
    instance = {
        "schema": "gaussian-asymmetric-metal-scientific-review/1",
        "review_id": source["review_id"],
        "design_source": {
            "sha256": "1" * 64,
            "design_payload_sha256": source["design_payload_sha256"],
        },
        "template_source": {
            "sha256": "2" * 64,
            "template_payload_sha256": source["template_payload_sha256"],
        },
        "candidate_source": {"sha256": source["candidate_sha256"]},
        "review_source": {"sha256": "3" * 64},
        "study_id": source["study_id"],
        "candidate_id": source["candidate_id"],
        "channel_id": source["channel_id"],
        "catalyst_state_id": source["catalyst_state_id"],
        "mechanism_id": source["mechanism_id"],
        "status": "review_contract_complete_runtime_unsupported",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "promotion_decision": "refused",
        "scientific_acceptance_decision": "not_granted_by_artifact",
        "literature_values_are_defaults": False,
        "review_scope": source["provenance"],
        "identity_binding": {
            "total_charge": 0,
            "multiplicity": 1,
            "atom_count": 7,
            "atom_order": [
                {"index": 1, "element": "Pd", "role": "metal_center"},
                {"index": 2, "element": "P", "role": "chiral_ligand_donor"},
                {"index": 3, "element": "C", "role": "alkene_carbon_a"},
                {"index": 4, "element": "C", "role": "alkene_carbon_b"},
                {"index": 5, "element": "H", "role": "substrate_hydrogen"},
                {"index": 6, "element": "H", "role": "substrate_hydrogen"},
                {"index": 7, "element": "H", "role": "ligand_hydrogen"},
            ],
            "metal_centers": [{"atom_index": 1, "element": "Pd"}],
            "coordinate_changes": [
                {"kind": "forming", "atoms": [1, 4], "description": "Synthetic Pd-C contact change."}
            ],
            "coordination_contacts": [
                {"donor_atom": 3, "acceptor_atom": 1, "kind": "metal_coordination", "distance_window_angstrom": None, "review_status": "pending"},
                {"donor_atom": 4, "acceptor_atom": 1, "kind": "metal_coordination", "distance_window_angstrom": None, "review_status": "pending"},
            ],
        },
        "sections": source["sections"],
        "completion": {
            "reviewed_sections": sorted(source["sections"]),
            "blocked_sections": [],
            "unresolved_blockers": [],
            "metal_m1_scientific_review_status": "not_satisfied_synthetic_fixture",
            "metal_m2_offline_runtime_contract": "blocked",
            "metal_m3_execution_boundary": "blocked",
            "metal_m4_live_smoke": "blocked",
        },
        "hard_rejections": ["no execution"],
        "claim_ceiling": "bounded_review_record_only_no_scientific_acceptance_ts_or_selectivity_claim",
    }
    instance["review_payload_sha256"] = CONTRACT.payload_sha256(instance)
    return instance


def metal_acceptance_review_source_instance() -> dict:
    return load(FIXTURES / "metal_acceptance_review_complete.json")


def metal_acceptance_review_instance() -> dict:
    source = metal_acceptance_review_source_instance()
    instance = {
        "schema": "gaussian-asymmetric-metal-acceptance-review/1",
        "review_id": source["review_id"],
        "template_source": {"sha256": "1" * 64},
        "candidate_source": {"sha256": "2" * 64},
        "scientific_review_source": {"sha256": "3" * 64},
        "input_observation_source": {"sha256": "4" * 64},
        "result_observation_source": {"sha256": "5" * 64},
        "decision_source": {"sha256": "6" * 64},
        "study_id": source["study_id"], "candidate_id": source["candidate_id"],
        "mechanism_id": source["mechanism_id"], "channel_id": source["channel_id"],
        "catalyst_state_id": source["catalyst_state_id"],
        "status": "acceptance_record_complete_runtime_unsupported",
        "calculation_ready": False, "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "scientific_acceptance_decision": "not_granted_by_artifact",
        "input_acceptance_decision": "not_granted_by_artifact",
        "mode_acceptance_decision": "not_granted_by_artifact",
        "promotion_decision": "refused", "submission_decision": "refused",
        "scope": source["scope"],
        "identity_binding": {
            "charge": 0, "multiplicity": 1, "atom_count": 7,
            "atom_order": [
                {"index": 1, "atomic_number": 46, "element": "Pd"},
                {"index": 2, "atomic_number": 15, "element": "P"},
                {"index": 3, "atomic_number": 6, "element": "C"},
                {"index": 4, "atomic_number": 6, "element": "C"},
                {"index": 5, "atomic_number": 1, "element": "H"},
                {"index": 6, "atomic_number": 1, "element": "H"},
                {"index": 7, "atomic_number": 1, "element": "H"},
            ],
        },
        "sections": source["sections"],
        "decision_summary": {
            "accepted_sections": ["coordination", "input_acceptance", "mode", "wavefunction"],
            "rejected_sections": [], "blocked_sections": [],
            "metal_m2_acceptance_review_status": "not_satisfied_synthetic_fixture",
        },
        "completion": {
            "metal_m2d_acceptance_review_contract": "implemented_offline",
            "metal_m2_offline_runtime_contract": "blocked",
            "metal_m3_execution_boundary": "blocked", "metal_m4_live_smoke": "blocked",
        },
        "hard_rejections": ["no runtime authority"],
        "claim_ceiling": "manual_decision_record_only_no_runtime_promotion_ts_path_or_selectivity_claim",
    }
    instance["review_payload_sha256"] = CONTRACT.payload_sha256(instance)
    return instance


def live_smoke_evidence_instance() -> dict:
    evidence = {
        "schema": "gaussian-asymmetric-live-smoke-evidence/1",
        "evidence_id": "bf3_ts1_smoke_evidence_fixture",
        "status": "passed",
        "recorded_date": "2026-07-14",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "sanitized": True,
        "contains_job_id": False,
        "contains_server_path": False,
        "contains_gaussian_log": False,
        "contains_checkpoint": False,
        "source_bindings": {
            name: {"sha256": character * 64}
            for name, character in zip(
                (
                    "smoke_proposal", "literature_ledger", "protocol_options",
                    "protocol_selection", "input_approval", "input", "job_record",
                    "parsed_ts_result", "mode_review", "mode_decision",
                ),
                "abcdef0123",
                strict=True,
            )
        },
        "chemical_system": {
            "candidate_id": "wang2024_bf3_ts1",
            "formula": "C18H30BF3N4O",
            "atom_count": 57,
            "charge": 0,
            "multiplicity": 1,
            "canonical_coordinate_block_sha256": "9" * 64,
        },
        "execution": {
            "g16_revision": "Gaussian 16 reviewed revision",
            "route": "reviewed exact route bound by the input hash",
            "resource_tier": "simple",
            "memory": "12GB",
            "nprocshared": 8,
            "terminal_state_confirmed": True,
            "transport_hashes_verified": True,
            "fresh_project_guard_passed": True,
            "resource_policy_reviewed": True,
        },
        "ts_validation": {
            "normal_termination": True,
            "error_termination": False,
            "stationary_point": True,
            "frequency_complete": True,
            "raw_imaginary_frequency_count": 1,
            "first_order_saddle_candidate": True,
            "featured_imaginary_frequency_cm1": -1455.35,
        },
        "mode_validation": {
            "decision": "accepted",
            "confirmed": True,
            "intended_coordinate": "H14 displacement along the reviewed C13-H14-N23 coordinate",
            "coordinate_projection_reviewed": True,
        },
        "limitations": [
            "Sanitized workflow evidence only; it does not authorize another job or an IRC calculation."
        ],
    }
    evidence["evidence_payload_sha256"] = CONTRACT.payload_sha256(evidence)
    return evidence


class AsymmetricSchemaValidationTests(unittest.TestCase):
    def artifact_instances(self) -> dict[str, dict]:
        result = load(FIXTURES / "boron_result_r.json")
        result["artifacts"].setdefault("checkpoint_audit", None)
        result["artifacts"].setdefault("irc_plan", None)
        return {
            "study": load(FIXTURES / "boron_study.json"),
            "candidate": load(FIXTURES / "boron_candidate_r.json"),
            "result": result,
            "analysis": load(FIXTURES / "boron_analysis.json"),
            "space": space_instance(),
            "ledger": ledger_instance(),
            "energy-record": energy_instance(),
            "materializations": materializations_instance(),
            "metal-support": metal_support_instance(),
            "metal-ts-audit-template": metal_ts_audit_instance(),
            "metal-scientific-review-source": metal_scientific_review_source_instance(),
            "metal-scientific-review": metal_scientific_review_instance(),
            "metal-input-observation": metal_input_observation_instance(),
            "metal-result-observation": metal_result_observation_instance(),
            "metal-acceptance-review-source": metal_acceptance_review_source_instance(),
            "metal-acceptance-review": metal_acceptance_review_instance(),
            "smoke-proposal": load(ROOT / "docs" / "asymmetric-catalysis-smoke-proposal.json"),
            "live-smoke-evidence": live_smoke_evidence_instance(),
            "literature-benchmark": load(ROOT / "studies" / "wang_2024_bf3_ts" / "candidate-ledger.json"),
        }

    def test_all_schema_documents_use_supported_keywords(self) -> None:
        expected = set(CONTRACT.SCHEMA_IDS)
        found = set()
        for path in SCHEMAS.glob("*.schema.json"):
            schema = load(path)
            CONTRACT.validate_schema_document(schema)
            found.add(path.name.removesuffix(".schema.json"))
        self.assertEqual(found, expected)

        unsupported = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "if": {}}
        with self.assertRaisesRegex(CONTRACT.ContractError, "unsupported keyword"):
            CONTRACT.validate_schema_document(unsupported)

    def test_all_artifact_types_have_a_structural_entry_point(self) -> None:
        instances = self.artifact_instances()
        self.assertEqual(set(instances), set(CONTRACT.SCHEMA_IDS))
        for kind, instance in instances.items():
            with self.subTest(kind=kind):
                self.assertEqual(CONTRACT.validate_structure(instance), kind)
                self.assertEqual(CONTRACT.validate_structure(instance, kind), kind)

    def test_internal_refs_required_fields_and_additional_properties_are_enforced(self) -> None:
        bad_id = energy_instance()
        bad_id["candidate_id"] = "INVALID-ID"
        with self.assertRaisesRegex(CONTRACT.ContractError, "pattern"):
            CONTRACT.validate_structure(bad_id, "energy-record")

        missing = energy_instance()
        missing.pop("degeneracy")
        with self.assertRaisesRegex(CONTRACT.ContractError, "missing required"):
            CONTRACT.validate_structure(missing, "energy-record")

        extra = energy_instance()
        extra["submission_authorized"] = True
        with self.assertRaisesRegex(CONTRACT.ContractError, "additional property"):
            CONTRACT.validate_structure(extra, "energy-record")

    def test_non_finite_numbers_and_non_standard_json_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            record = energy_instance()
            record["comparison_free_energy"] = value
            with self.subTest(value=value), self.assertRaisesRegex(CONTRACT.ContractError, "type|non-finite"):
                CONTRACT.validate_structure(record, "energy-record")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for token in ("NaN", "Infinity", "-Infinity"):
                path = root / f"{token.replace('-', 'minus')}.json"
                path.write_text(f'{{"value": {token}}}\n', encoding="utf-8")
                with self.subTest(token=token), self.assertRaisesRegex(CONTRACT.ContractError, "non-standard JSON"):
                    CONTRACT.load_json(path)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")
            with self.assertRaisesRegex(CONTRACT.ContractError, "duplicate JSON object key"):
                CONTRACT.load_json(path)

    def test_integer_constraints_do_not_accept_booleans_or_zero_degeneracy(self) -> None:
        for value in (False, 0, -1):
            record = energy_instance()
            record["degeneracy"] = value
            with self.subTest(value=value), self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_energy_record(record)

    def test_offline_refusal_boundaries_are_structural_and_hash_bound(self) -> None:
        smoke = self.artifact_instances()["smoke-proposal"]
        ledger_path = ROOT / "studies" / "wang_2024_bf3_ts" / "candidate-ledger.json"
        literature = load(ledger_path)
        CONTRACT.validate_smoke_proposal(smoke, literature, ledger_path)

        calculation_ready = copy.deepcopy(smoke)
        calculation_ready["calculation_ready"] = True
        with self.assertRaisesRegex(CONTRACT.ContractError, "const"):
            CONTRACT.validate_smoke_proposal(calculation_ready)

        route = copy.deepcopy(smoke)
        route["proposed_gaussian"]["route"] = "#p opt=(ts) freq"
        route["proposal_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in route.items() if key != "proposal_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "runnable route"):
            CONTRACT.validate_smoke_proposal(route)

        tampered = copy.deepcopy(smoke)
        tampered["purpose"] += " tampered"
        with self.assertRaisesRegex(CONTRACT.ContractError, "payload hash mismatch"):
            CONTRACT.validate_smoke_proposal(tampered)

        metal_observation = metal_result_observation_instance()
        wrong_atomic_number = copy.deepcopy(metal_observation)
        wrong_atomic_number["identity_binding"]["atom_order"][0]["atomic_number"] = 45
        wrong_atomic_number["audit_payload_sha256"] = CONTRACT.payload_sha256(
            {
                key: value
                for key, value in wrong_atomic_number.items()
                if key != "audit_payload_sha256"
            }
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "atomic number and element differ"):
            CONTRACT.validate_metal_result_observation(wrong_atomic_number)

    def test_literature_payload_and_atom_inventory_are_bound(self) -> None:
        ledger = self.artifact_instances()["literature-benchmark"]
        CONTRACT.validate_literature_benchmark(ledger)

        tampered = copy.deepcopy(ledger)
        tampered["candidates"][0]["atom_inventory"]["atom_count"] += 1
        with self.assertRaisesRegex(CONTRACT.ContractError, "payload hash mismatch"):
            CONTRACT.validate_literature_benchmark(tampered)

        bad_inventory = copy.deepcopy(ledger)
        bad_inventory["candidates"][0]["atom_inventory"]["atom_count"] += 1
        bad_inventory["ledger_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in bad_inventory.items() if key != "ledger_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "atom order/count mismatch"):
            CONTRACT.validate_literature_benchmark(bad_inventory)

    def test_live_smoke_evidence_requires_complete_approval_and_mode_chain(self) -> None:
        evidence = live_smoke_evidence_instance()
        CONTRACT.validate_live_smoke_evidence(evidence)

        tampered = copy.deepcopy(evidence)
        tampered["source_bindings"]["input"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(CONTRACT.ContractError, "payload hash mismatch"):
            CONTRACT.validate_live_smoke_evidence(tampered)

        missing_approval = copy.deepcopy(evidence)
        missing_approval["source_bindings"].pop("input_approval")
        missing_approval["evidence_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in missing_approval.items() if key != "evidence_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "missing required"):
            CONTRACT.validate_live_smoke_evidence(missing_approval)

        legacy_protocol_selection = copy.deepcopy(evidence)
        legacy_protocol_selection["source_bindings"]["protocol_selection"] = None
        legacy_protocol_selection["evidence_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in legacy_protocol_selection.items() if key != "evidence_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "pre-input protocol selection"):
            CONTRACT.validate_live_smoke_evidence(legacy_protocol_selection)

        legacy_protocol_selection["status"] = "incomplete"
        legacy_protocol_selection["limitations"].append(
            "This run predates the three-tier protocol selection gate and cannot be retroactively signed."
        )
        legacy_protocol_selection["evidence_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in legacy_protocol_selection.items() if key != "evidence_payload_sha256"}
        )
        CONTRACT.validate_live_smoke_evidence(legacy_protocol_selection)

        unreviewed_mode = copy.deepcopy(evidence)
        unreviewed_mode["mode_validation"].update(
            decision="not_reviewed", confirmed=False, coordinate_projection_reviewed=False
        )
        unreviewed_mode["evidence_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in unreviewed_mode.items() if key != "evidence_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "accepted mode decision"):
            CONTRACT.validate_live_smoke_evidence(unreviewed_mode)

    def test_ledger_rejects_cross_channel_deduplication_and_bad_counts(self) -> None:
        ledger = ledger_instance()
        dimensions = {dimension_id: "level" for dimension_id in ledger["dimension_ids"]}
        base = {
            "candidate_id": "candidate_one",
            "channel_id": "channel_one",
            "catalyst_state_id": "state_fixture",
            "dimensions": dimensions,
            "canonical_key": "1" * 64,
            "logical_equivalence_key": "2" * 64,
            "status": "unmaterialized",
            "duplicate_of": None,
            "candidate_artifact": None,
            "geometry_fingerprint": None,
            "diagnostics": [],
        }
        duplicate = copy.deepcopy(base)
        duplicate.update(
            candidate_id="candidate_two",
            channel_id="channel_two",
            canonical_key="3" * 64,
            status="duplicate_logical",
            duplicate_of="candidate_one",
        )
        ledger["entries"] = [base, duplicate]
        ledger["counts"].update(enumerated=2, retained=1, logical_duplicates=1)
        with self.assertRaisesRegex(CONTRACT.ContractError, "cross-channel deduplication"):
            CONTRACT.validate_ledger(ledger)

        bad_counts = ledger_instance()
        bad_counts["counts"]["enumerated"] = 1
        with self.assertRaisesRegex(CONTRACT.ContractError, "enumerated count mismatch"):
            CONTRACT.validate_ledger(bad_counts)

    def test_materialization_is_hash_bound_to_ledger(self) -> None:
        ledger = ledger_instance()
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.json"
            ledger_path.write_text(json.dumps(ledger) + "\n", encoding="utf-8")
            materializations = materializations_instance()
            with self.assertRaisesRegex(CONTRACT.ContractError, "ledger hash mismatch"):
                CONTRACT.validate_materializations(materializations, ledger, ledger_path)

    def test_path_validated_result_requires_bound_checkpoint_and_irc_artifacts(self) -> None:
        candidate_path = FIXTURES / "boron_candidate_r.json"
        candidate = load(candidate_path)
        result = load(FIXTURES / "boron_result_r.json")
        result["validation_level"] = "path_validated"
        result["path_evidence"].update(
            forward="completed_and_identified",
            reverse="completed_and_identified",
            endpoint_identity_reviewed=True,
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "checkpoint_audit artifact required"):
            CONTRACT.validate_result(result, candidate, candidate_path)


if __name__ == "__main__":
    unittest.main()
