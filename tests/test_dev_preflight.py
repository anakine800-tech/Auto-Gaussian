#!/usr/bin/env python3
"""Offline tests for the read-only development preflight."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "dev_preflight.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_dev_preflight_test", MODULE_PATH)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


def run_git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], check=False, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)


class DevelopmentPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        run_git(self.root, "init", "-b", "main")
        for relative in PREFLIGHT.REQUIRED_PATHS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("placeholder\n", encoding="utf-8")
        run_git(self.root, "add", *PREFLIGHT.REQUIRED_PATHS)
        run_git(
            self.root,
            "-c",
            "user.name=Auto G16 Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        )
        run_git(self.root, "switch", "-c", "codex/safe-feature")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def check_by_id(self, report: dict[str, object], check_id: str) -> dict[str, object]:
        return next(item for item in report["checks"] if item["id"] == check_id)  # type: ignore[index,union-attr]

    def test_safe_feature_branch_and_subdirectory_root_discovery(self) -> None:
        subdirectory = self.root / "docs" / "nested"
        subdirectory.mkdir()
        report = PREFLIGHT.inspect(PREFLIGHT.find_git_root(subdirectory), environment={})
        self.assertEqual(report["summary"]["blockers"], 0)
        self.assertEqual(self.check_by_id(report, "branch")["status"], "pass")
        self.assertEqual(self.check_by_id(report, "working_tree")["status"], "pass")

    def test_main_and_detached_head_are_blockers(self) -> None:
        run_git(self.root, "switch", "main")
        main_report = PREFLIGHT.inspect(self.root, environment={})
        self.assertEqual(self.check_by_id(main_report, "branch")["status"], "blocker")
        run_git(self.root, "switch", "--detach")
        detached_report = PREFLIGHT.inspect(self.root, environment={})
        self.assertEqual(self.check_by_id(detached_report, "branch")["status"], "blocker")
        self.assertIsNone(detached_report["branch"])

    def test_dirty_tree_is_classified_without_reading_contents(self) -> None:
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")
        (self.root / "new-file.txt").write_text("synthetic\n", encoding="utf-8")
        run_git(self.root, "add", "README.md")
        report = PREFLIGHT.inspect(self.root, environment={})
        check = self.check_by_id(report, "working_tree")
        self.assertEqual(check["status"], "warning")
        self.assertEqual(check["details"], {"staged": 1, "unstaged": 0, "untracked": 1, "total": 2})
        self.assertEqual(report["summary"]["blockers"], 0)

    def test_missing_config_and_private_path_are_blockers(self) -> None:
        (self.root / "config" / "required-checks.json").unlink()
        private = self.root / "secrets" / "credential-name.txt"
        private.parent.mkdir()
        private.write_text("not-a-secret\n", encoding="utf-8")
        report = PREFLIGHT.inspect(self.root, environment={})
        self.assertEqual(self.check_by_id(report, "required_files")["status"], "blocker")
        private_check = self.check_by_id(report, "private_paths")
        self.assertEqual(private_check["status"], "blocker")
        self.assertNotIn("credential-name", json.dumps(report))

    def test_rename_from_private_path_is_still_blocked(self) -> None:
        private = self.root / "secrets" / "fixture.txt"
        private.parent.mkdir()
        private.write_text("synthetic\n", encoding="utf-8")
        run_git(self.root, "add", "secrets/fixture.txt")
        run_git(
            self.root,
            "-c",
            "user.name=Auto G16 Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "private-path fixture",
        )
        private.rename(self.root / "ordinary.txt")
        run_git(self.root, "add", "-A")
        report = PREFLIGHT.inspect(self.root, environment={})
        self.assertEqual(self.check_by_id(report, "private_paths")["status"], "blocker")

    def test_live_flag_names_block_without_exposing_values(self) -> None:
        report = PREFLIGHT.inspect(self.root, environment={"AUTO_G16_LIVE_SUBMIT": "do-not-print"})
        check = self.check_by_id(report, "live_opt_in")
        self.assertEqual(check["status"], "blocker")
        rendered = json.dumps(report)
        self.assertIn("AUTO_G16_LIVE_SUBMIT", rendered)
        self.assertNotIn("do-not-print", rendered)

    def test_json_cli_has_machine_readable_status_and_exit_code(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--repo", str(self.root / "docs"), "--json"],
            check=False,
            capture_output=True,
            text=True,
            env={},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], PREFLIGHT.SCHEMA)
        self.assertIn(payload["status"], {"pass", "pass_with_warnings"})


if __name__ == "__main__":
    unittest.main()
