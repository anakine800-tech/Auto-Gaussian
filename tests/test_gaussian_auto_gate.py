#!/usr/bin/env python3
"""Fail-closed tests for the exact-input Auto-G16 runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
MODULE = SCRIPTS / "gaussian_auto.py"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("gaussian_auto", MODULE)
assert SPEC and SPEC.loader
AUTO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTO)


class GaussianAutoGateTests(unittest.TestCase):
    def approval_summary(self) -> dict:
        return {
            "project": "reviewed_job",
            "remote_workdir": "/home/user100/SDL/reviewed_job",
            "input_sha256": "a" * 64,
            "protocol": {
                "route": "#p hf/sto-3g opt",
                "mem": "12GB",
                "nproc": 8,
            },
            "charge": 0,
            "multiplicity": 1,
        }

    def approval_record(self) -> dict:
        return {
            "schema": "auto-g16-live-submission-approval/1",
            "decision": "approved",
            "explicit_confirmation": True,
            "scope": {
                "project": "reviewed_job",
                "remote_workdir": "/home/user100/SDL/reviewed_job",
                "input_sha256": "a" * 64,
                "route": "#p hf/sto-3g opt",
                "mem": "12GB",
                "nprocshared": 8,
                "charge": 0,
                "multiplicity": 1,
            },
            "authorizations": {
                "create_server_directory": True,
                "submit": True,
                "retry": False,
                "cancel": False,
                "cleanup": False,
                "delete_server_data": False,
            },
        }

    def test_raw_structure_cannot_bypass_protocol_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            process = subprocess.run(
                [
                    sys.executable,
                    str(MODULE),
                    "prepare",
                    "O",
                    "--project",
                    "water",
                    "--local-dir",
                    temp,
                ],
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("accepts only an existing reviewed", process.stderr)

    def test_live_approval_must_match_exact_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            approval = self.approval_record()
            path.write_text(json.dumps(approval), encoding="utf-8")
            self.assertEqual(
                AUTO.validate_live_approval(path, self.approval_summary()), approval
            )
            approval["scope"]["input_sha256"] = "b" * 64
            path.write_text(json.dumps(approval), encoding="utf-8")
            with self.assertRaises(SystemExit):
                AUTO.validate_live_approval(path, self.approval_summary())


if __name__ == "__main__":
    unittest.main()
