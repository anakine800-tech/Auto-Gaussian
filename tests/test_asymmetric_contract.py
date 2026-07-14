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
BUILDER_PATH = ROOT / "skills" / "gaussian-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
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

            tampered = copy.deepcopy(design)
            tampered["ts_search_families"][0]["seed_strategy_candidates"][0]["status"] = "selected"
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_metal_support(tampered, study, study_path)

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
