#!/usr/bin/env python3
"""Offline tests for the timed unittest runner."""

from __future__ import annotations

import copy
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


MANIFEST = ROOT / "config" / "validation-selection.json"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def candidate(root: Path, path: str) -> tuple[str, str, dict[str, object]]:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Runner Test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "runner@example.invalid"],
        check=True,
    )
    manifest_path = root / TEST_RUNNER.SELECTOR.MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    changed = root / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    base = git(root, "rev-parse", "HEAD")
    changed.write_text("value = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", path], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "candidate"], check=True)
    head = git(root, "rev-parse", "HEAD")
    return base, head, TEST_RUNNER.SELECTOR.compute_selection(root, base, head)


def write_selection(directory: Path, value: dict[str, object]) -> Path:
    selected = directory / "selection.json"
    selected.write_text(json.dumps(value), encoding="utf-8")
    return selected


class TimedTestRunnerTests(unittest.TestCase):
    def test_normal_focused_selection_is_recomputed_and_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            base, head, canonical = candidate(root, "auto_g16/core/models.py")
            selected = write_selection(Path(temporary), canonical)
            lane, tests = TEST_RUNNER.resolve_authoritative_selection(
                selected,
                repository=root,
                base=base,
                head=head,
            )
        self.assertEqual(lane, "focused")
        self.assertEqual(tests, ["tests.v3.core.test_models"])

    def test_original_forged_core_selection_exploit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            base, head, canonical = candidate(root, "auto_g16/core/store.py")
            forged = copy.deepcopy(canonical)
            forged["lane"] = "focused"
            forged["tests"] = ["tests.test_runtime_config"]
            forged["safety_evidence"] = []
            forged["matched_routes"] = []
            selected = write_selection(Path(temporary), forged)
            with self.assertRaisesRegex(
                TEST_RUNNER.SelectionError,
                "lane, matched_routes, safety_evidence, tests",
            ):
                TEST_RUNNER.resolve_authoritative_selection(
                    selected,
                    repository=root,
                    base=base,
                    head=head,
                )

    def test_each_decision_and_authority_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            base, head, canonical = candidate(root, "auto_g16/core/store.py")
            mutations = {
                "route": ("matched_routes", []),
                "lane": ("lane", "focused"),
                "tests": ("tests", ["tests.test_runtime_config"]),
                "safety": ("safety_evidence", []),
                "manifest path": ("manifest_path", "config/external.json"),
                "manifest blob": ("manifest_blob", "0" * 40),
                "base": ("base", "0" * 40),
                "head": ("head", "1" * 40),
                "tree": ("head_tree", "2" * 40),
                "repository root": ("repository_root", "/tmp/forged-root"),
                "repository identity": ("repository_identity", "/tmp/forged-git"),
                "git executable": ("git_executable", "/tmp/forged-git"),
                "git version": ("git_version", "git version forged"),
            }
            for label, (field, replacement) in mutations.items():
                with self.subTest(label=label):
                    tampered = copy.deepcopy(canonical)
                    tampered[field] = replacement
                    selected = write_selection(Path(temporary), tampered)
                    with self.assertRaisesRegex(TEST_RUNNER.SelectionError, field):
                        TEST_RUNNER.resolve_authoritative_selection(
                            selected,
                            repository=root,
                            base=base,
                            head=head,
                        )

            changed = copy.deepcopy(canonical)
            changed["changes"] = [{"status": "M", "paths": ["auto_g16/core/models.py"]}]
            changed["changed_paths"] = ["auto_g16/core/models.py"]
            selected = write_selection(Path(temporary), changed)
            with self.assertRaisesRegex(TEST_RUNNER.SelectionError, "changed_paths, changes"):
                TEST_RUNNER.resolve_authoritative_selection(
                    selected,
                    repository=root,
                    base=base,
                    head=head,
                )

            status = copy.deepcopy(canonical)
            status["changes"][0]["status"] = "A"
            selected = write_selection(Path(temporary), status)
            with self.assertRaisesRegex(TEST_RUNNER.SelectionError, "changes"):
                TEST_RUNNER.resolve_authoritative_selection(
                    selected,
                    repository=root,
                    base=base,
                    head=head,
                )

    def test_missing_extra_malformed_and_conflicting_selection_fail_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            base, head, canonical = candidate(root, "auto_g16/core/models.py")
            cases = []
            missing = copy.deepcopy(canonical)
            del missing["manifest_blob"]
            cases.append(missing)
            extra = copy.deepcopy(canonical)
            extra["authority_signature"] = "not permitted"
            cases.append(extra)
            malformed = copy.deepcopy(canonical)
            malformed["fail_closed"] = "yes"
            cases.append(malformed)
            for value in cases:
                selected = write_selection(Path(temporary), value)
                with self.assertRaises(TEST_RUNNER.SelectionError):
                    TEST_RUNNER.resolve_authoritative_selection(
                        selected,
                        repository=root,
                        base=base,
                        head=head,
                    )

            selected = write_selection(Path(temporary), canonical)
            with self.assertRaises(SystemExit):
                TEST_RUNNER.main(["tests.test_runtime_config", "--selection", str(selected)])
            with self.assertRaises(SystemExit):
                TEST_RUNNER.main(["--selection", str(selected)])

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
