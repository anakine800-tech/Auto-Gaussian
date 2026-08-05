#!/usr/bin/env python3
"""Hostile offline tests for the local pinned Draft validation runner."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "run_schema_validation.py"
SPEC = importlib.util.spec_from_file_location(
    "auto_g16_run_schema_validation_test", MODULE_PATH
)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class LocalSchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.env = self.root / "schema-env"
        self.python = self.env / "bin" / "python"
        self.python.parent.mkdir(parents=True)
        self.python.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        self.python.chmod(0o755)
        self.site_packages = self.env / "lib" / "python3.13" / "site-packages"
        self.site_packages.mkdir(parents=True)
        self.pins = {"jsonschema": "4.26.0", "attrs": "26.1.0"}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def payload(
        self,
        *,
        versions: dict[str, str | None] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "auto-g16-schema-validation-probe/1",
            "python_version": "3.13.13",
            "versions": versions or dict(self.pins),
        }

    @staticmethod
    def completed(payload: object, returncode: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=json.dumps(payload),
            stderr="probe-error" if returncode else "",
        )

    def test_explicit_paths_are_absolute_and_environment_is_conventional(self) -> None:
        with self.assertRaisesRegex(RUNNER.BlockedError, "absolute path"):
            RUNNER.discover_candidates(
                self.root, [Path("relative/bin/python")], [], {}
            )
        with self.assertRaisesRegex(RUNNER.BlockedError, "bin/ or Scripts"):
            RUNNER.discover_candidates(
                self.root, [self.root / "python"], [], {}
            )
        candidates = RUNNER.discover_candidates(self.root, [], [self.env], {})
        self.assertEqual(
            candidates,
            [
                RUNNER.Candidate(
                    self.python, self.env, self.site_packages, "--env #1"
                )
            ],
        )

    def test_missing_environment_is_actionable_blocked_not_pass(self) -> None:
        with mock.patch.object(RUNNER, "_default_envs", return_value=()):
            with self.assertRaisesRegex(
                RUNNER.BlockedError, "never installs packages"
            ):
                RUNNER.discover_candidates(self.root, [], [], {})

    def test_probe_is_isolated_minimal_and_reads_only_locked_versions(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            return self.completed(self.payload())

        payload = RUNNER.validate_candidate(
            RUNNER.Candidate(
                self.python, self.env, self.site_packages, "explicit"
            ),
            self.pins,
            ["3.11", "3.12", "3.13"],
            runner=fake,
        )
        self.assertEqual(payload["versions"], self.pins)
        command, kwargs = calls[0]
        self.assertEqual(command[1:4], ["-I", "-S", "-c"])
        self.assertEqual(command[-2], str(self.site_packages))
        self.assertEqual(json.loads(command[-1]), sorted(self.pins))
        self.assertEqual(kwargs["env"], {"PYTHONNOUSERSITE": "1"})
        self.assertNotIn("HOME", kwargs["env"])
        self.assertNotIn("PYTHONPATH", kwargs["env"])

    def test_wrong_missing_or_extra_package_inventory_blocks_before_tests(self) -> None:
        candidate = RUNNER.Candidate(
            self.python, self.env, self.site_packages, "explicit"
        )
        wrong = dict(self.pins)
        wrong["jsonschema"] = "4.25.1"
        for payload, message in (
            (self.payload(versions=wrong), "lock mismatch"),
            (self.payload(versions={"jsonschema": "4.26.0"}), "incomplete"),
            (
                self.payload(
                    versions={**self.pins, "private-config": "secret"}
                ),
                "incomplete",
            ),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(RUNNER.BlockedError, message):
                    RUNNER.validate_candidate(
                        candidate,
                        self.pins,
                        ["3.11", "3.12", "3.13"],
                        runner=lambda *args, payload=payload, **kwargs: self.completed(payload),
                    )

    def test_missing_or_ambiguous_site_packages_blocks(self) -> None:
        self.site_packages.rmdir()
        with self.assertRaisesRegex(RUNNER.BlockedError, "exactly one non-symlink"):
            RUNNER.discover_candidates(self.root, [], [self.env], {})
        self.site_packages.mkdir()
        second = self.env / "lib" / "python3.12" / "site-packages"
        second.mkdir(parents=True)
        with self.assertRaisesRegex(RUNNER.BlockedError, "exactly one non-symlink"):
            RUNNER.discover_candidates(self.root, [], [self.env], {})

    @unittest.skipUnless(os.name == "posix", "POSIX permission hardening")
    def test_group_writable_environment_blocks_before_execution(self) -> None:
        self.env.chmod(0o775)
        with self.assertRaisesRegex(RUNNER.BlockedError, "trusted user-owned"):
            RUNNER.discover_candidates(self.root, [], [self.env], {})

    def test_malformed_or_failed_probe_blocks(self) -> None:
        candidate = RUNNER.Candidate(
            self.python, self.env, self.site_packages, "explicit"
        )
        malformed = subprocess.CompletedProcess([], 0, "not-json", "")
        failed = subprocess.CompletedProcess([], 9, "", "denied")
        for completed, message in (
            (malformed, "one JSON"),
            (failed, "exit 9"),
        ):
            with self.assertRaisesRegex(RUNNER.BlockedError, message):
                RUNNER.validate_candidate(
                    candidate,
                    self.pins,
                    ["3.11", "3.12", "3.13"],
                    runner=lambda *args, completed=completed, **kwargs: completed,
                )

    def test_duplicate_probe_key_blocks(self) -> None:
        completed = subprocess.CompletedProcess(
            [],
            0,
            '{"schema":"auto-g16-schema-validation-probe/1",'
            '"schema":"replaced","python_version":"3.13.13",'
            '"versions":{"attrs":"26.1.0","jsonschema":"4.26.0"}}',
            "",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "duplicate JSON key"):
            RUNNER.validate_candidate(
                RUNNER.Candidate(
                    self.python, self.env, self.site_packages, "explicit"
                ),
                self.pins,
                ["3.11", "3.12", "3.13"],
                runner=lambda *args, **kwargs: completed,
            )

    def test_unsupported_python_minor_blocks(self) -> None:
        payload = self.payload()
        payload["python_version"] = "3.10.19"
        with self.assertRaisesRegex(RUNNER.BlockedError, "outside the reviewed minor"):
            RUNNER.validate_candidate(
                RUNNER.Candidate(
                    self.python, self.env, self.site_packages, "explicit"
                ),
                self.pins,
                ["3.11", "3.12", "3.13"],
                runner=lambda *args, **kwargs: self.completed(payload),
            )

    def test_canonical_run_uses_given_ci_order_and_fail_closed_environment(self) -> None:
        modules = (
            "tests.test_first_schema_draft202012",
            "tests.test_second_schema_draft202012",
        )
        observed: dict[str, object] = {}

        def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            observed["command"] = command
            observed.update(kwargs)
            return subprocess.CompletedProcess(command, 0)

        result = RUNNER.run_inventory(
            RUNNER.Candidate(
                self.python, self.env, self.site_packages, "explicit"
            ),
            self.root,
            modules,
            runner=fake,
        )
        self.assertEqual(result, 0)
        command = observed["command"]
        self.assertIsInstance(command, list)
        self.assertEqual(command[-2:], list(modules))
        self.assertEqual(command[1:4], ["-I", "-S", "-c"])
        self.assertEqual(command[-3], str(self.site_packages))
        self.assertEqual(
            observed["env"],
            {
                "AUTO_G16_REQUIRE_JSONSCHEMA": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            },
        )
        self.assertNotIn("HOME", observed["env"])
        self.assertNotIn("AUTO_G16_CORE_PYTHON", observed["env"])

    def test_environment_variable_is_explicit_and_deduplicated(self) -> None:
        candidates = RUNNER.discover_candidates(
            self.root,
            [self.python],
            [],
            {RUNNER.EXPLICIT_PYTHON_ENV: str(self.python)},
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].python, self.python)

    def test_main_reports_blocked_without_claiming_pass(self) -> None:
        with mock.patch.object(
            RUNNER, "discover_candidates", side_effect=RUNNER.BlockedError("missing")
        ):
            with mock.patch("builtins.print") as printed:
                result = RUNNER.main(["--repo", str(ROOT)])
        self.assertEqual(result, 2)
        rendered = " ".join(str(call) for call in printed.call_args_list)
        self.assertIn("BLOCKED", rendered)
        self.assertNotIn("PASS", rendered)


if __name__ == "__main__":
    unittest.main()
