#!/usr/bin/env python3
"""Offline command-line end-to-end tests for asymmetric-catalysis tooling."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
VALIDATOR = ROOT / "scripts" / "validate_asymmetric_contract.py"
FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
BF3 = ROOT / "studies" / "wang_2024_bf3_ts"


class AsymmetricCommandLineTests(unittest.TestCase):
    def run_python(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_success(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_all_offline_subcommands_expose_help(self) -> None:
        commands = (
            "build-study", "enumerate-boron", "build-literature-benchmark",
            "build-candidates", "ingest-result", "aggregate",
            "design-metal-support", "build-metal-ts-audit-template",
            "build-metal-scientific-review", "audit-metal-input",
            "audit-metal-result", "build-metal-acceptance-review", "propose-smoke",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_success(self.run_python(TOOL, command, "--help"))

    def test_validator_cli_accepts_standalone_artifacts_and_full_chain(self) -> None:
        artifacts = self.run_python(
            VALIDATOR,
            "--artifact", str(BF3 / "candidate-ledger.json"),
            "--artifact", str(ROOT / "docs" / "asymmetric-catalysis-smoke-proposal.json"),
        )
        self.assert_success(artifacts)
        artifact_summary = json.loads(artifacts.stdout)
        self.assertEqual(artifact_summary["artifact_count"], 2)
        self.assertEqual(artifact_summary["artifact_kinds"], ["literature-benchmark", "smoke-proposal"])
        self.assertFalse(artifact_summary["live_actions"])

        chain = self.run_python(
            VALIDATOR,
            "--study", str(FIXTURES / "boron_study.json"),
            "--candidate", str(FIXTURES / "boron_candidate_r.json"),
            "--candidate", str(FIXTURES / "boron_candidate_s.json"),
            "--result", str(FIXTURES / "boron_result_r.json"),
            "--result", str(FIXTURES / "boron_result_s.json"),
            "--analysis", str(FIXTURES / "boron_analysis.json"),
        )
        self.assert_success(chain)
        chain_summary = json.loads(chain.stdout)
        self.assertEqual(chain_summary["candidate_count"], 2)
        self.assertEqual(chain_summary["result_count"], 2)
        self.assertTrue(chain_summary["analysis_checked"])
        self.assertFalse(chain_summary["live_actions"])

    def test_builders_reproduce_checked_artifacts_and_refuse_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "candidate-ledger.json"
            built = self.run_python(
                TOOL,
                "build-literature-benchmark", str(BF3 / "benchmark-source.json"),
                "--output", str(ledger),
            )
            self.assert_success(built)
            self.assertEqual(ledger.read_bytes(), (BF3 / "candidate-ledger.json").read_bytes())

            smoke = root / "smoke-proposal.json"
            proposed = self.run_python(
                TOOL,
                "propose-smoke", str(ledger),
                "--candidate-id", "wang2024_bf3_ts1",
                "--output", str(smoke),
            )
            self.assert_success(proposed)
            proposal = json.loads(smoke.read_text(encoding="utf-8"))
            self.assertEqual(proposal["status"], "planned_not_submitted")
            self.assertIsNone(proposal["proposed_gaussian"]["route"])
            self.assertFalse(proposal["calculation_ready"])

            metal = root / "metal-support.json"
            designed = self.run_python(
                TOOL,
                "design-metal-support", str(FIXTURES / "metal_study.json"),
                "--output", str(metal),
            )
            self.assert_success(designed)
            design = json.loads(metal.read_text(encoding="utf-8"))
            self.assertEqual(design["submission_decision"], "refused")
            self.assertFalse(design["calculation_ready"])
            self.assertEqual(design["scope"]["priority"], "transition_metal_ts_design_first")
            validated_metal = self.run_python(VALIDATOR, "--artifact", str(metal))
            self.assert_success(validated_metal)
            self.assertFalse(json.loads(validated_metal.stdout)["live_actions"])

            metal_template = root / "metal-ts-audit-template.json"
            templated = self.run_python(
                TOOL,
                "build-metal-ts-audit-template", str(metal),
                str(FIXTURES / "metal_candidate.json"),
                "--output", str(metal_template),
            )
            self.assert_success(templated)
            template = json.loads(metal_template.read_text(encoding="utf-8"))
            self.assertEqual(template["submission_decision"], "refused")
            validated_template = self.run_python(
                VALIDATOR, "--artifact", str(metal_template)
            )
            self.assert_success(validated_template)
            self.assertFalse(json.loads(validated_template.stdout)["live_actions"])

            metal_review = root / "metal-scientific-review.json"
            reviewed = self.run_python(
                TOOL,
                "build-metal-scientific-review", str(metal), str(metal_template),
                str(FIXTURES / "metal_candidate.json"),
                str(FIXTURES / "metal_scientific_review_complete.json"),
                "--output", str(metal_review),
            )
            self.assert_success(reviewed)
            review = json.loads(metal_review.read_text(encoding="utf-8"))
            self.assertEqual(review["scientific_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(
                review["completion"]["metal_m1_scientific_review_status"],
                "not_satisfied_synthetic_fixture",
            )
            validated_review = self.run_python(
                VALIDATOR, "--artifact", str(metal_review)
            )
            self.assert_success(validated_review)
            review_summary = json.loads(validated_review.stdout)
            self.assertEqual(review_summary["artifact_kinds"], ["metal-scientific-review"])
            self.assertFalse(review_summary["live_actions"])

            review_dry_run = self.run_python(
                TOOL,
                "build-metal-scientific-review", str(metal), str(metal_template),
                str(FIXTURES / "metal_candidate.json"),
                str(FIXTURES / "metal_scientific_review_incomplete.json"),
                "--output", str(root / "dry-review-must-not-exist.json"),
                "--dry-run",
            )
            self.assert_success(review_dry_run)
            review_dry_summary = json.loads(review_dry_run.stdout)
            self.assertTrue(review_dry_summary["dry_run"])
            self.assertEqual(review_dry_summary["status"], "blocked_incomplete_scientific_review")
            self.assertEqual(review_dry_summary["scientific_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(
                review_dry_summary["would_write"],
                str(root / "dry-review-must-not-exist.json"),
            )
            self.assertFalse(review_dry_summary["live_actions"])
            self.assertFalse((root / "dry-review-must-not-exist.json").exists())

            review_missing_output = self.run_python(
                TOOL,
                "build-metal-scientific-review", str(metal), str(metal_template),
                str(FIXTURES / "metal_candidate.json"),
                str(FIXTURES / "metal_scientific_review_complete.json"),
            )
            self.assertEqual(review_missing_output.returncode, 2)
            self.assertIn("requires --output unless --dry-run", review_missing_output.stderr)

            metal_input_observation = root / "metal-input-observation.json"
            input_observed = self.run_python(
                TOOL,
                "audit-metal-input", str(metal_template),
                str(FIXTURES / "metal_candidate.json"), str(metal_review),
                str(FIXTURES / "metal_input_observation.gjf"),
                "--output", str(metal_input_observation),
            )
            self.assert_success(input_observed)
            input_observation = json.loads(metal_input_observation.read_text(encoding="utf-8"))
            self.assertEqual(input_observation["status"], "parsed_input_observation_blocked")
            self.assertEqual(input_observation["input_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(input_observation["submission_decision"], "refused")
            validated_input_observation = self.run_python(
                VALIDATOR, "--artifact", str(metal_input_observation)
            )
            self.assert_success(validated_input_observation)
            input_summary = json.loads(validated_input_observation.stdout)
            self.assertEqual(input_summary["artifact_kinds"], ["metal-input-observation"])
            self.assertFalse(input_summary["live_actions"])

            input_dry_path = root / "dry-input-observation-must-not-exist.json"
            input_dry_run = self.run_python(
                TOOL,
                "audit-metal-input", str(metal_template),
                str(FIXTURES / "metal_candidate.json"), str(metal_review),
                str(FIXTURES / "metal_input_observation.gjf"),
                "--output", str(input_dry_path), "--dry-run",
            )
            self.assert_success(input_dry_run)
            input_dry_summary = json.loads(input_dry_run.stdout)
            self.assertTrue(input_dry_summary["dry_run"])
            self.assertEqual(input_dry_summary["input_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(input_dry_summary["would_write"], str(input_dry_path))
            self.assertFalse(input_dry_summary["live_actions"])
            self.assertFalse(input_dry_path.exists())

            input_missing_output = self.run_python(
                TOOL,
                "audit-metal-input", str(metal_template),
                str(FIXTURES / "metal_candidate.json"), str(metal_review),
                str(FIXTURES / "metal_input_observation.gjf"),
            )
            self.assertEqual(input_missing_output.returncode, 2)
            self.assertIn("requires --output unless --dry-run", input_missing_output.stderr)

            metal_observation = root / "metal-result-observation.json"
            observed = self.run_python(
                TOOL,
                "audit-metal-result", str(metal_template),
                str(FIXTURES / "metal_candidate.json"),
                str(FIXTURES / "metal_observation_success.txt"),
                "--output", str(metal_observation),
            )
            self.assert_success(observed)
            observation = json.loads(metal_observation.read_text(encoding="utf-8"))
            self.assertEqual(observation["status"], "parsed_observation_blocked")
            self.assertEqual(observation["promotion_decision"], "refused")
            validated_observation = self.run_python(
                VALIDATOR, "--artifact", str(metal_observation)
            )
            self.assert_success(validated_observation)
            summary = json.loads(validated_observation.stdout)
            self.assertEqual(summary["artifact_kinds"], ["metal-result-observation"])
            self.assertFalse(summary["live_actions"])

            dry_run = self.run_python(
                TOOL,
                "audit-metal-result", str(metal_template),
                str(FIXTURES / "metal_candidate.json"),
                str(FIXTURES / "metal_observation_success.txt"),
                "--dry-run",
            )
            self.assert_success(dry_run)
            dry_summary = json.loads(dry_run.stdout)
            self.assertTrue(dry_summary["dry_run"])
            self.assertEqual(dry_summary["promotion_decision"], "refused")
            self.assertFalse(dry_summary["live_actions"])

            missing_output = self.run_python(
                TOOL,
                "audit-metal-result", str(metal_template),
                str(FIXTURES / "metal_candidate.json"),
                str(FIXTURES / "metal_observation_success.txt"),
            )
            self.assertEqual(missing_output.returncode, 2)
            self.assertIn("requires --output unless --dry-run", missing_output.stderr)

            metal_acceptance = root / "metal-acceptance-review.json"
            accepted = self.run_python(
                TOOL, "build-metal-acceptance-review", str(metal_template),
                str(FIXTURES / "metal_candidate.json"), str(metal_review),
                str(metal_input_observation), str(metal_observation),
                str(FIXTURES / "metal_acceptance_review_complete.json"),
                "--output", str(metal_acceptance),
            )
            self.assert_success(accepted)
            acceptance = json.loads(metal_acceptance.read_text(encoding="utf-8"))
            self.assertEqual(acceptance["status"], "acceptance_record_complete_runtime_unsupported")
            self.assertEqual(acceptance["input_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(acceptance["mode_acceptance_decision"], "not_granted_by_artifact")
            validated_acceptance = self.run_python(VALIDATOR, "--artifact", str(metal_acceptance))
            self.assert_success(validated_acceptance)
            self.assertEqual(json.loads(validated_acceptance.stdout)["artifact_kinds"], ["metal-acceptance-review"])

            acceptance_dry_path = root / "dry-acceptance-must-not-exist.json"
            acceptance_dry = self.run_python(
                TOOL, "build-metal-acceptance-review", str(metal_template),
                str(FIXTURES / "metal_candidate.json"), str(metal_review),
                str(metal_input_observation), str(metal_observation),
                str(FIXTURES / "metal_acceptance_review_incomplete.json"),
                "--output", str(acceptance_dry_path), "--dry-run",
            )
            self.assert_success(acceptance_dry)
            acceptance_summary = json.loads(acceptance_dry.stdout)
            self.assertTrue(acceptance_summary["dry_run"])
            self.assertEqual(acceptance_summary["status"], "blocked_incomplete_acceptance_review")
            self.assertFalse(acceptance_summary["live_actions"])
            self.assertFalse(acceptance_dry_path.exists())

            acceptance_missing = self.run_python(
                TOOL, "build-metal-acceptance-review", str(metal_template),
                str(FIXTURES / "metal_candidate.json"), str(metal_review),
                str(metal_input_observation), str(metal_observation),
                str(FIXTURES / "metal_acceptance_review_complete.json"),
            )
            self.assertEqual(acceptance_missing.returncode, 2)
            self.assertIn("requires --output unless --dry-run", acceptance_missing.stderr)

            study = root / "study.json"
            built_study = self.run_python(
                TOOL,
                "build-study", str(FIXTURES / "boron_study.json"),
                "--output", str(study),
            )
            self.assert_success(built_study)
            self.assertEqual(json.loads(study.read_text(encoding="utf-8"))["study_id"], "fixture_boron_selectivity")

            overwrite = self.run_python(
                TOOL,
                "build-study", str(FIXTURES / "boron_study.json"),
                "--output", str(study),
            )
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("refusing to overwrite", overwrite.stderr)


if __name__ == "__main__":
    unittest.main()
