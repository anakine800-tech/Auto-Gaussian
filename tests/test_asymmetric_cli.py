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
TOOL = ROOT / "skills" / "gaussian-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
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
            "design-metal-support", "propose-smoke",
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
