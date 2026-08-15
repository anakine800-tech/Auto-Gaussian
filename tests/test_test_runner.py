#!/usr/bin/env python3
"""Offline tests for the timed unittest runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "scripts" / "run_tests.py"
SPEC = importlib.util.spec_from_file_location("timed_test_runner", RUNNER)
assert SPEC and SPEC.loader
TEST_RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TEST_RUNNER)


def selection(lane: str, tests: list[str]) -> dict[str, object]:
    return {
        "schema": "auto-g16-validation-selection-result/1",
        "version": 1,
        "base": None,
        "head": None,
        "merge_base": None,
        "head_tree": None,
        "changed_paths": [],
        "changes": [],
        "lane": lane,
        "tests": tests,
        "matched_routes": [],
        "safety_evidence": [],
        "fail_closed": False,
        "reasons": ["synthetic runner test"],
    }


class TimedTestRunnerTests(unittest.TestCase):
    def test_closed_selection_runs_only_the_named_lightweight_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "selection.json"
            selected.write_text(
                json.dumps(selection("focused", ["tests.test_runtime_config"])),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--selection",
                    str(selected),
                    "--verbosity",
                    "0",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("VALIDATION SELECTION lane=focused tests=1", completed.stdout)
        self.assertIn("Ran 6 tests", completed.stderr)

    def test_invalid_or_conflicting_selection_fails_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "selection.json"
            selected.write_text(
                json.dumps(selection("legacy-release", ["tests.test_runtime_config"])),
                encoding="utf-8",
            )
            invalid = subprocess.run(
                [sys.executable, str(RUNNER), "--selection", str(selected)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            selected.write_text(
                json.dumps(selection("focused", ["tests.test_runtime_config"])),
                encoding="utf-8",
            )
            conflicting = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "tests.test_runtime_config",
                    "--selection",
                    str(selected),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("legacy-release must use full discovery", invalid.stderr)
        self.assertEqual(conflicting.returncode, 2)
        self.assertIn("cannot be combined", conflicting.stderr)

    def test_valid_fail_closed_selection_resolves_to_full_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "selection.json"
            value = selection("legacy-release", [])
            value["fail_closed"] = True
            selected.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(
                TEST_RUNNER.load_selection(selected),
                ("legacy-release", []),
            )

            value["fail_closed"] = "yes"
            selected.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(TEST_RUNNER.SelectionError, "changes/fail_closed"):
                TEST_RUNNER.load_selection(selected)

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
