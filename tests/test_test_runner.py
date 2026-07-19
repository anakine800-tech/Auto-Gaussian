#!/usr/bin/env python3
"""Offline tests for the timed unittest runner."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "scripts" / "run_tests.py"


class TimedTestRunnerTests(unittest.TestCase):
    def test_repository_tests_directory_is_discoverable_without_package_marker(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--pattern",
                "test_runtime_config.py",
                "--slow-threshold",
                "0",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("test_example_matches_closed_schema", completed.stderr)

    def test_runner_reports_slow_tests_and_preserves_failure_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "synthetic_tests"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            test_path = package / "test_synthetic.py"
            test_path.write_text(
                "import unittest\n"
                "class Synthetic(unittest.TestCase):\n"
                "    def test_pass(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--start-directory",
                    str(package),
                    "--slow-threshold",
                    "0",
                    "--top-slow",
                    "1",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("SLOW TESTS", completed.stdout)
            self.assertIn("test_pass", completed.stdout)

            test_path.write_text(
                "import unittest\n"
                "class Synthetic(unittest.TestCase):\n"
                "    def test_fail(self): self.fail('synthetic')\n",
                encoding="utf-8",
            )
            failed = subprocess.run(
                [sys.executable, str(RUNNER), "--start-directory", str(package)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 1)


if __name__ == "__main__":
    unittest.main()
