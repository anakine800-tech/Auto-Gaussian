#!/usr/bin/env python3
"""Offline baseline checks for version-controlled Gaussian Skills."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
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

    def test_oldcheckpoint_is_explicit_hashed_companion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            bundle = root / "bundle"
            source.mkdir()
            checkpoint = source / "reviewed_ts.chk"
            checkpoint.write_bytes(b"reviewed checkpoint")
            input_path = source / "irc_f.gjf"
            input_path.write_text(
                "%oldchk=reviewed_ts.chk\n"
                "%chk=irc_f.chk\n"
                "%mem=12GB\n"
                "%nprocshared=8\n"
                "#p b3lyp/6-31g(d) irc=(rcfc,forward,maxpoints=30) guess=read\n\n"
                "IRC forward\n\n"
                "0 1\n"
                "H 0.0 0.0 0.0\n"
                "H 0.0 0.0 0.7\n\n",
                encoding="utf-8",
            )
            job, files = PBS.stage(input_path, "irc_f", bundle)
            names = {path.name for path in files}
            self.assertEqual(job["gaussian"]["oldcheckpoint"], "reviewed_ts.chk")
            self.assertIn("reviewed_ts.chk", names)
            checksums = (bundle / "checksums.sha256").read_text()
            self.assertIn("reviewed_ts.chk", checksums)

    def test_oldcheckpoint_rejects_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unsafe.gjf"
            path.write_text(
                "%oldchk=../outside.chk\n%chk=new.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p b3lyp/6-31g(d) irc=(rcfc,forward)\n\nTitle\n\n0 1\nH 0 0 0\n\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                PBS.parse_gaussian(path)

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

    def test_live_freq_stage_is_not_completed_from_opt_marker(self) -> None:
        analysis = {
            "normal_termination": True,
            "error_termination": False,
            "scf_calculations": 1,
            "final_coordinate_count": 1,
            "normal_termination_count": 1,
            "error_termination_count": 0,
        }
        state, _, _, _ = PBS.classify_inspection_state(
            workflow_manifest=None,
            full_normal_count=1,
            full_error_count=0,
            analysis=analysis,
            qstate="R",
            process_alive=True,
        )
        self.assertEqual(state, "running")

    def test_opt_freq_sp_fixture_is_sanitized_and_complete(self) -> None:
        manifest = json.loads(
            (ROOT / "tests" / "fixtures" / "opt_freq_sp_success.json").read_text()
        )
        self.assertEqual(manifest["schema"], "gaussian-opt-freq-sp/1")
        self.assertEqual(manifest["expected_stage_count"], 3)
        self.assertEqual(manifest["chemical_identity"]["formula"], "H2O")


if __name__ == "__main__":
    unittest.main()
