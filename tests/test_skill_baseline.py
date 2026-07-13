#!/usr/bin/env python3
"""Offline baseline checks for version-controlled Gaussian Skills."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PBS_SCRIPTS = ROOT / "skills" / "gaussian-rtwin-pbs" / "scripts"
MODULE = PBS_SCRIPTS / "gaussian_rtwin_pbs.py"
sys.path.insert(0, str(PBS_SCRIPTS))
SPEC = importlib.util.spec_from_file_location("gaussian_rtwin_pbs", MODULE)
assert SPEC and SPEC.loader
PBS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PBS)


class RepositoryBaselineTests(unittest.TestCase):
    def test_fixed_server_root(self) -> None:
        self.assertEqual(PBS.DEFAULT_REMOTE_ROOT, "/home/user100/SDL")
        self.assertEqual(
            PBS.remote_project_dir("safe_job"), "/home/user100/SDL/safe_job"
        )

    def test_existing_and_empty_directory_guards_are_contained(self) -> None:
        for script in (
            PBS.remote_existing_directory_guard("safe_job"),
            PBS.remote_empty_directory_guard("safe_job"),
        ):
            self.assertIn("/home/user100/SDL", script)
            self.assertIn("realpath", script)
            self.assertNotIn("codex-gaussian", script)
        self.assertIn(
            "REFUSING_OVERWRITE", PBS.remote_empty_directory_guard("safe_job")
        )

    def test_pbs_scratch_is_inside_project(self) -> None:
        script = PBS.pbs_text("safe_job", "safe_job.gjf", 8)
        self.assertIn('scratch="$work_real/scratch"', script)
        self.assertIn('export GAUSS_SCRDIR="$scratch_real"', script)
        self.assertNotIn("/tmp", script)

    def test_zombie_requires_repeated_stable_evidence(self) -> None:
        observation = {
            "pbs_job_name": "safe_job",
            "pbs_state": "R",
            "pbs_record_present": True,
            "session_id": "1234",
            "process_alive": False,
            "log_size": 100,
            "log_mtime_epoch": 200,
            "workflow_expected_stages": 3,
            "full_normal_termination_count": 3,
            "full_error_termination_count": 0,
            "analysis": {},
        }
        result = PBS.assess_zombie_observations(
            "safe_job", "123.master", [observation, dict(observation)]
        )
        self.assertTrue(result["cleanup_eligible"])
        live = dict(observation, process_alive=True)
        refused = PBS.assess_zombie_observations(
            "safe_job", "123.master", [observation, live]
        )
        self.assertFalse(refused["cleanup_eligible"])

    def test_opt_freq_sp_fixture_is_sanitized_and_complete(self) -> None:
        manifest = json.loads(
            (ROOT / "tests" / "fixtures" / "opt_freq_sp_success.json").read_text()
        )
        self.assertEqual(manifest["schema"], "gaussian-opt-freq-sp/1")
        self.assertEqual(manifest["expected_stage_count"], 3)
        self.assertEqual(manifest["chemical_identity"]["formula"], "H2O")


if __name__ == "__main__":
    unittest.main()
