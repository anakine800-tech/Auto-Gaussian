#!/usr/bin/env python3
"""Offline tests for the read-only development preflight."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
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


def clean_cli_environment() -> dict[str, str]:
    """Bind the parent-selected Git once; never retry another dependency."""
    parent_path = os.environ.get("PATH")
    selected = shutil.which("git", path=parent_path) if parent_path else None
    if selected is None or not Path(selected).is_absolute():
        raise AssertionError("CLI tests require an absolute parent-selected Git")
    git = Path(selected).resolve(strict=True)
    if git.name != "git" or not git.is_file() or not os.access(git, os.X_OK):
        raise AssertionError("CLI tests require a valid physical Git executable")
    # These real CLI tests need a clean environment with an explicit dependency,
    # rather than env={}. Suppress ambient config without overriding local hooks.
    environment = {
        "PATH": str(git.parent),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    version = subprocess.run(
        [str(git), "--version"], env=environment, check=False,
        capture_output=True, text=True,
    )
    if version.returncode or not version.stdout.startswith("git version "):
        raise AssertionError("Selected Git dependency failed its version check")
    return environment


class DevelopmentPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli_environment = clean_cli_environment()

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

    def test_require_clean_promotes_dirty_tree_to_blocker(self) -> None:
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")
        run_git(self.root, "add", "README.md")
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--repo",
                str(self.root),
                "--require-clean",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=self.cli_environment,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        check = self.check_by_id(payload, "working_tree")
        self.assertEqual(check["status"], "blocker")
        self.assertEqual(payload["summary"]["blockers"], 1)

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
            env=self.cli_environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], PREFLIGHT.SCHEMA)
        self.assertIn(payload["status"], {"pass", "pass_with_warnings"})

    def test_clean_cli_environment_excludes_ambient_state_and_keeps_local_hooks(self) -> None:
        home = self.root / "synthetic-home"
        home.mkdir()
        config = home / ".gitconfig"
        config.write_text('[sentinel]\n global = inherited\n', encoding="utf-8")
        system_config = home / "system-config"
        system_config.write_text('[sentinel]\n system = inherited\n', encoding="utf-8")
        run_git(self.root, "config", "sentinel.local", "retained")
        run_git(self.root, "config", "user.name", "Auto G16 Test")
        run_git(self.root, "config", "user.email", "test@example.invalid")
        hook = self.root / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\n"
            "Path('.git/local-hook-ran').write_text('retained')\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        # Only synthetic ambient inputs enter this probe's parent. The nested
        # process receives the same closed environment used by the real CLI.
        ambient = {
            "PATH": self.cli_environment["PATH"],
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_SYSTEM": str(system_config),
            "GH_TOKEN": "synthetic-sensitive-sentinel",
            "UNRELATED_SENTINEL": "synthetic-unrelated-sentinel",
            "AUTO_G16_LIVE_SUBMIT": "synthetic-live-sentinel",
            "AUTO_G16_SKIP_PRESSURE_TESTS": "synthetic-coverage-sentinel",
        }
        probe = """
import json, os, runpy, subprocess, sys
module = runpy.run_path(sys.argv[1])
environment = module['clean_cli_environment']()
def git(*args, env):
    return subprocess.run(['git', '-C', sys.argv[2], *args], env=env,
                          check=True, capture_output=True, text=True).stdout
ambient = git('config', '--list', '--show-scope', env=os.environ)
isolated = git('config', '--list', '--show-scope', env=environment)
child = subprocess.run([sys.executable, '-c',
                        'import json, os; print(json.dumps(dict(os.environ)))'],
                       env=environment, check=True, capture_output=True, text=True)
git('commit', '--allow-empty', '-m', 'local hook probe', env=environment)
print(json.dumps({'ambient': ambient, 'isolated': isolated,
                  'supplied_keys': sorted(environment),
                  'child': json.loads(child.stdout)}))
"""
        result = subprocess.run(
            [sys.executable, "-c", probe, str(Path(__file__).resolve()), str(self.root)],
            env=ambient, check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("global\tsentinel.global=inherited", payload["ambient"])
        self.assertIn("system\tsentinel.system=inherited", payload["ambient"])
        self.assertNotIn("global\t", payload["isolated"])
        self.assertNotIn("system\t", payload["isolated"])
        self.assertIn("local\tsentinel.local=retained", payload["isolated"])
        self.assertEqual((self.root / ".git/local-hook-ran").read_text(), "retained")
        self.assertEqual(payload["supplied_keys"], ["GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "PATH"])
        self.assertEqual(payload["child"]["PATH"], self.cli_environment["PATH"])
        self.assertEqual(payload["child"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(payload["child"]["GIT_CONFIG_NOSYSTEM"], "1")
        # CPython may synthesize LC_CTYPE during startup; it is not an input key.
        self.assertLessEqual(set(payload["child"]), set(payload["supplied_keys"]) | {"LC_CTYPE"})
        for key in set(ambient) - {"PATH", "GIT_CONFIG_GLOBAL"}:
            self.assertNotIn(key, payload["child"])
        self.assertNotIn("synthetic-", json.dumps(payload["child"]))

    def test_missing_or_invalid_git_dependency_fails_in_real_process(self) -> None:
        empty = self.root / "empty-bin"
        empty.mkdir()
        invalid = self.root / "invalid-bin"
        invalid.mkdir()
        executable = invalid / "git"
        executable.write_text("invalid executable format\n", encoding="utf-8")
        executable.chmod(0o755)
        probe = (
            "import runpy, sys; "
            "runpy.run_path(sys.argv[1])['clean_cli_environment'](); "
            "print('DEPENDENCY_ACCEPTED')"
        )
        cases = ({}, {"PATH": str(empty)}, {"PATH": "empty-bin"},
                 {"PATH": str(invalid) + os.pathsep + self.cli_environment["PATH"]})
        for environment in cases:
            with self.subTest(environment=environment):
                result = subprocess.run(
                    [sys.executable, "-c", probe, str(Path(__file__).resolve())],
                    cwd=self.root, env=environment, check=False, capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("DEPENDENCY_ACCEPTED", result.stdout)
                self.assertIn("clean_cli_environment", result.stderr)


if __name__ == "__main__":
    unittest.main()
