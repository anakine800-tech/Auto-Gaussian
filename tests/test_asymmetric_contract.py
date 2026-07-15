#!/usr/bin/env python3
"""Offline tests for asymmetric-catalysis schemas and semantic contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "scripts" / "validate_asymmetric_contract.py"
FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
SCHEMAS = ROOT / "contracts" / "asymmetric-catalysis"
SPEC = importlib.util.spec_from_file_location("validate_asymmetric_contract", MODULE)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)
BUILDER_PATH = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
BUILDER_SPEC = importlib.util.spec_from_file_location("asymmetric_catalysis_contract_fixture", BUILDER_PATH)
assert BUILDER_SPEC and BUILDER_SPEC.loader
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(BUILDER)


class AsymmetricCatalysisContractTests(unittest.TestCase):
    def load(self, name: str) -> dict:
        return CONTRACT.load_json(FIXTURES / name)

    def test_schema_documents_are_valid_json_with_expected_draft(self) -> None:
        expected = {
            "study", "candidate", "result", "analysis", "space", "ledger",
            "energy-record", "materializations", "metal-support", "smoke-proposal",
            "metal-ts-audit-template", "metal-scientific-review-source",
            "metal-scientific-review", "metal-input-observation", "metal-result-observation",
            "metal-acceptance-review-source", "metal-acceptance-review",
            "live-smoke-evidence", "literature-benchmark",
        }
        found = set()
        for path in SCHEMAS.glob("*.schema.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(document["type"], "object")
            self.assertFalse(document["additionalProperties"])
            found.add(path.name.removesuffix(".schema.json"))
        self.assertEqual(found, expected)

    def test_metal_scope_evidence_contract_rejects_scope_only_laundering(self) -> None:
        m1_source = self.load("metal_scientific_review_complete.json")
        CONTRACT.validate_metal_scientific_review_source(m1_source)
        m1_scope_flip = copy.deepcopy(m1_source)
        m1_scope_flip["provenance"]["scope_kind"] = "primary_literature_bound_review"
        with self.assertRaises(CONTRACT.ContractError):
            CONTRACT.validate_metal_scientific_review_source(m1_scope_flip)

        m2_source = self.load("metal_acceptance_review_complete.json")
        CONTRACT.validate_metal_acceptance_review_source(m2_source)
        m2_scope_flip = copy.deepcopy(m2_source)
        m2_scope_flip["scope"]["scope_kind"] = "reviewer_bound_real_case"
        with self.assertRaises(CONTRACT.ContractError):
            CONTRACT.validate_metal_acceptance_review_source(m2_scope_flip)

        invalid_real_date = copy.deepcopy(m2_scope_flip)
        invalid_real_date["scope"]["review_date"] = "2026-02-30"
        for section in invalid_real_date["sections"].values():
            for evidence in section["evidence"]:
                evidence["evidence_kind"] = "reviewer_record"
        with self.assertRaisesRegex(CONTRACT.ContractError, "valid ISO review date"):
            CONTRACT.validate_metal_acceptance_review_source(invalid_real_date)

        missing_real_reviewer = copy.deepcopy(invalid_real_date)
        missing_real_reviewer["scope"]["review_date"] = "2026-07-15"
        missing_real_reviewer["scope"]["reviewer"] = ""
        with self.assertRaises(CONTRACT.ContractError):
            CONTRACT.validate_metal_acceptance_review_source(missing_real_reviewer)

    def test_boron_fixture_chain_passes_cross_artifact_validation(self) -> None:
        study_path = FIXTURES / "boron_study.json"
        study = self.load("boron_study.json")
        CONTRACT.validate_study(study)

        candidates = {}
        results = {}
        for suffix in ("r", "s"):
            candidate_path = FIXTURES / f"boron_candidate_{suffix}.json"
            candidate = CONTRACT.load_json(candidate_path)
            CONTRACT.validate_candidate(candidate, study, study_path)
            candidates[candidate["candidate_id"]] = (candidate, candidate_path)

            result_path = FIXTURES / f"boron_result_{suffix}.json"
            result = CONTRACT.load_json(result_path)
            CONTRACT.validate_result(result, candidate, candidate_path)
            results[result["result_id"]] = (result, result_path)

        CONTRACT.validate_analysis(self.load("boron_analysis.json"), study, study_path, results)
        self.assertEqual(set(candidates), {"boron_ts_r_conf_a", "boron_ts_s_conf_a"})

    def test_metal_fixture_remains_non_promotable(self) -> None:
        study_path = FIXTURES / "metal_study.json"
        study = self.load("metal_study.json")
        candidate = self.load("metal_candidate.json")
        CONTRACT.validate_study(study)
        CONTRACT.validate_candidate(candidate, study, study_path)

        promoted = copy.deepcopy(candidate)
        promoted["review_status"] = "promoted_offline"
        promoted["review"]["decision"] = "promoted_offline"
        with self.assertRaisesRegex(CONTRACT.ContractError, "unsupported metal candidate promoted"):
            CONTRACT.validate_candidate(promoted, study, study_path)

        with tempfile.TemporaryDirectory() as tmp:
            design_path = Path(tmp) / "metal-support.json"
            design = BUILDER.design_metal_support(study_path, design_path)
            CONTRACT.validate_metal_support(design, study, study_path)
            self.assertEqual(design["scope"]["priority"], "transition_metal_ts_design_first")
            self.assertEqual(design["submission_decision"], "refused")
            self.assertEqual(design["ts_search_families"][0]["elementary_step_class"], "unassigned_requires_review")

            legacy_design = copy.deepcopy(design)
            legacy_design["extension_milestones"] = [
                item for item in legacy_design["extension_milestones"]
                if item["milestone_id"] not in {
                    "metal_m1_review_contract", "metal_m2c_input_observation",
                    "metal_m2d_acceptance_review_contract",
                }
            ]
            legacy_design["design_payload_sha256"] = CONTRACT.payload_sha256(
                {
                    key: value
                    for key, value in legacy_design.items()
                    if key != "design_payload_sha256"
                }
            )
            CONTRACT.validate_metal_support(legacy_design)

            tampered = copy.deepcopy(design)
            tampered["ts_search_families"][0]["seed_strategy_candidates"][0]["status"] = "selected"
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_support(tampered, study, study_path)

            template_path = Path(tmp) / "metal-ts-audit-template.json"
            template = BUILDER.build_metal_ts_audit_template(
                design_path, FIXTURES / "metal_candidate.json", template_path
            )
            CONTRACT.validate_metal_ts_audit_template(
                template,
                design,
                design_path,
                candidate,
                FIXTURES / "metal_candidate.json",
            )
            self.assertEqual(template["submission_decision"], "refused")
            self.assertTrue(all(
                section["status"] == "blocked_pending_review"
                for section in template["audit_sections"].values()
            ))
            self.assertIsNone(template["seed_strategy_gate"]["selected_strategy_id"])

            bypass = copy.deepcopy(template)
            bypass["audit_sections"]["wavefunction"]["status"] = "accepted"
            bypass["template_payload_sha256"] = CONTRACT.payload_sha256(bypass)
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_ts_audit_template(bypass)

            contact_drift = copy.deepcopy(template)
            contact_drift["identity_binding"]["coordination_contacts"][0]["donor_atom"] = 2
            contact_drift["template_payload_sha256"] = CONTRACT.payload_sha256(
                {
                    key: value
                    for key, value in contact_drift.items()
                    if key != "template_payload_sha256"
                }
            )
            with self.assertRaisesRegex(CONTRACT.ContractError, "coordination contacts mismatch"):
                CONTRACT.validate_metal_ts_audit_template(
                    contact_drift,
                    design,
                    design_path,
                    candidate,
                    FIXTURES / "metal_candidate.json",
                )

            review_source_path = FIXTURES / "metal_scientific_review_complete.json"
            review_source = CONTRACT.load_json(review_source_path)
            review_path = Path(tmp) / "metal-scientific-review.json"
            review = BUILDER.build_metal_scientific_review(
                design_path,
                template_path,
                FIXTURES / "metal_candidate.json",
                review_source_path,
                review_path,
            )
            CONTRACT.validate_metal_scientific_review(
                review,
                design,
                design_path,
                template,
                template_path,
                candidate,
                FIXTURES / "metal_candidate.json",
                review_source,
                review_source_path,
            )
            self.assertEqual(review["status"], "review_contract_complete_runtime_unsupported")
            self.assertEqual(
                review["completion"]["metal_m1_scientific_review_status"],
                "not_satisfied_synthetic_fixture",
            )
            self.assertEqual(review["scientific_acceptance_decision"], "not_granted_by_artifact")
            self.assertTrue(all(
                section["status"] == "blocked_pending_review"
                for section in template["audit_sections"].values()
            ))

            input_observation_path = Path(tmp) / "metal-input-observation.json"
            input_observation = BUILDER.audit_metal_input_observation(
                template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                FIXTURES / "metal_input_observation.gjf",
                input_observation_path,
            )
            CONTRACT.validate_metal_input_observation(
                input_observation,
                template,
                template_path,
                candidate,
                FIXTURES / "metal_candidate.json",
                review,
                review_path,
                FIXTURES / "metal_input_observation.gjf",
            )
            self.assertEqual(input_observation["input_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(input_observation["protocol_selection_decision"], "absent_not_authorized")
            self.assertEqual(input_observation["promotion_decision"], "refused")

            accepted_input = copy.deepcopy(input_observation)
            accepted_input["input_acceptance_decision"] = "accepted"
            accepted_input["audit_payload_sha256"] = CONTRACT.payload_sha256({
                key: value for key, value in accepted_input.items()
                if key != "audit_payload_sha256"
            })
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_input_observation(accepted_input)

            route_flag_drift = copy.deepcopy(input_observation)
            route_flag_drift["input_observations"]["task_text_observations"]["ts_text_observed"] = False
            route_flag_drift["audit_payload_sha256"] = CONTRACT.payload_sha256({
                key: value for key, value in route_flag_drift.items()
                if key != "audit_payload_sha256"
            })
            with self.assertRaisesRegex(CONTRACT.ContractError, "task-text flags"):
                CONTRACT.validate_metal_input_observation(route_flag_drift)

            incomplete_source_path = FIXTURES / "metal_scientific_review_incomplete.json"
            incomplete_path = Path(tmp) / "metal-scientific-review-incomplete.json"
            incomplete = BUILDER.build_metal_scientific_review(
                design_path,
                template_path,
                FIXTURES / "metal_candidate.json",
                incomplete_source_path,
                incomplete_path,
            )
            CONTRACT.validate_metal_scientific_review(incomplete)
            self.assertEqual(incomplete["status"], "blocked_incomplete_scientific_review")
            self.assertEqual(len(incomplete["completion"]["blocked_sections"]), 6)

            accepted = copy.deepcopy(review)
            accepted["scientific_acceptance_decision"] = "accepted"
            accepted["review_payload_sha256"] = CONTRACT.payload_sha256(
                {key: value for key, value in accepted.items() if key != "review_payload_sha256"}
            )
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_scientific_review(accepted)

            literature_default = copy.deepcopy(review)
            literature_default["literature_values_are_defaults"] = True
            literature_default["review_payload_sha256"] = CONTRACT.payload_sha256(
                {key: value for key, value in literature_default.items() if key != "review_payload_sha256"}
            )
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_scientific_review(literature_default)

            observation_path = Path(tmp) / "metal-result-observation.json"
            observation = BUILDER.audit_metal_result_observation(
                template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_observation_success.txt",
                observation_path,
            )
            CONTRACT.validate_metal_result_observation(
                observation,
                template,
                template_path,
                candidate,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_observation_success.txt",
            )
            self.assertEqual(observation["promotion_decision"], "refused")
            self.assertEqual(
                observation["claim_ceiling"],
                "parsed_observation_only_no_ts_or_selectivity_claim",
            )

            promoted_observation = copy.deepcopy(observation)
            promoted_observation["promotion_decision"] = "accepted"
            promoted_observation["audit_payload_sha256"] = CONTRACT.payload_sha256(
                {
                    key: value
                    for key, value in promoted_observation.items()
                    if key != "audit_payload_sha256"
                }
            )
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_result_observation(promoted_observation)

            inferred_window = copy.deepcopy(observation)
            inferred_window["coordination_observations"]["contacts"][0]["distance_window_angstrom"] = [1.5, 2.5]
            inferred_window["audit_payload_sha256"] = CONTRACT.payload_sha256(
                {
                    key: value
                    for key, value in inferred_window.items()
                    if key != "audit_payload_sha256"
                }
            )
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_result_observation(inferred_window)

            acceptance_source_path = FIXTURES / "metal_acceptance_review_complete.json"
            acceptance_source = CONTRACT.load_json(acceptance_source_path)
            acceptance_path = Path(tmp) / "metal-acceptance-review.json"
            acceptance = BUILDER.build_metal_acceptance_review(
                template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                input_observation_path,
                observation_path,
                acceptance_source_path,
                acceptance_path,
            )
            CONTRACT.validate_metal_acceptance_review(
                acceptance,
                template, template_path,
                candidate, FIXTURES / "metal_candidate.json",
                review, review_path,
                input_observation, input_observation_path,
                observation, observation_path,
                acceptance_source, acceptance_source_path,
            )
            self.assertEqual(acceptance["scientific_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(acceptance["mode_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(acceptance["promotion_decision"], "refused")

            real_scope_with_synthetic_upstream = copy.deepcopy(acceptance)
            real_scope_with_synthetic_upstream["scope"]["scope_kind"] = "reviewer_bound_real_case"
            for section in real_scope_with_synthetic_upstream["sections"].values():
                for evidence in section["evidence"]:
                    evidence["evidence_kind"] = "reviewer_record"
            real_scope_with_synthetic_upstream["decision_summary"]["metal_m2_acceptance_review_status"] = "reviewed_bounded_example_runtime_unsupported"
            real_scope_with_synthetic_upstream["review_payload_sha256"] = CONTRACT.payload_sha256({
                key: value for key, value in real_scope_with_synthetic_upstream.items()
                if key != "review_payload_sha256"
            })
            with self.assertRaisesRegex(CONTRACT.ContractError, "bound upstream M1 artifact"):
                CONTRACT.validate_metal_acceptance_review(real_scope_with_synthetic_upstream)
            with self.assertRaisesRegex(CONTRACT.ContractError, "upstream real non-synthetic M1"):
                CONTRACT.validate_metal_acceptance_review(
                    real_scope_with_synthetic_upstream,
                    scientific_review=review,
                    scientific_review_path=review_path,
                )

            promoted_acceptance = copy.deepcopy(acceptance)
            promoted_acceptance["promotion_decision"] = "accepted"
            promoted_acceptance["review_payload_sha256"] = CONTRACT.payload_sha256({
                key: value for key, value in promoted_acceptance.items()
                if key != "review_payload_sha256"
            })
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_acceptance_review(promoted_acceptance)

    def test_mode_reviewed_result_requires_exactly_one_imaginary_mode(self) -> None:
        candidate_path = FIXTURES / "boron_candidate_r.json"
        candidate = self.load("boron_candidate_r.json")
        result = self.load("boron_result_r.json")
        result["frequency_evidence"]["raw_imaginary_frequency_count"] = 2
        with self.assertRaisesRegex(CONTRACT.ContractError, "exactly one raw imaginary"):
            CONTRACT.validate_result(result, candidate, candidate_path)

    def test_validated_analysis_refuses_incomplete_coverage(self) -> None:
        study_path = FIXTURES / "boron_study.json"
        study = self.load("boron_study.json")
        results = {}
        for suffix in ("r", "s"):
            path = FIXTURES / f"boron_result_{suffix}.json"
            result = CONTRACT.load_json(path)
            results[result["result_id"]] = (result, path)
        analysis = self.load("boron_analysis.json")
        analysis["status"] = "validated"
        analysis["coverage"][0]["coverage_status"] = "incomplete"
        with self.assertRaisesRegex(CONTRACT.ContractError, "incomplete coverage"):
            CONTRACT.validate_analysis(analysis, study, study_path, results)


if __name__ == "__main__":
    unittest.main()
