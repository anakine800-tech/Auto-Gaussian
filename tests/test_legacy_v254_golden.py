#!/usr/bin/env python3
"""Synthetic offline characterization of the released v2.5.4 RTwin/PBS surface."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "rtwin_pbs"
GOLDEN_PATH = FIXTURES / "legacy_v2_5_4_golden.json"
INPUT_PATH = FIXTURES / "legacy_v2_5_4_input.gjf"
sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_runtime_module(values: dict[str, str] | None = None) -> types.ModuleType:
    module = types.ModuleType("runtime_config")
    configured = dict(values or {})

    def setting(env_name: str, key: str, default: str) -> str:
        return os.environ.get(env_name, configured.get(key, default))

    module.setting = setting  # type: ignore[attr-defined]
    return module


with mock.patch.dict(sys.modules, {"runtime_config": fake_runtime_module()}):
    PBS = load_module("legacy_v254_gaussian_rtwin_pbs", SCRIPTS / "gaussian_rtwin_pbs.py")
with mock.patch.dict(sys.modules, {"gaussian_rtwin_pbs": PBS}):
    AUTO = load_module("legacy_v254_gaussian_auto", SCRIPTS / "gaussian_auto.py")


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(data)


def stable_identity(value: object | None) -> str | None:
    if value is None:
        return None
    target = value if isinstance(value, type) or callable(value) else type(value)
    module = getattr(target, "__module__", type(target).__module__)
    qualname = getattr(target, "__qualname__", type(target).__qualname__)
    return f"{module}.{qualname}"


def normalized_value(value: object) -> dict[str, object]:
    if value is None or isinstance(value, (bool, int, float, str)):
        return {"type": type(value).__name__, "value": value}
    if isinstance(value, Path):
        return {"type": "pathlib.Path", "value": str(value)}
    if isinstance(value, tuple):
        return {"type": "tuple", "value": [normalized_value(item) for item in value]}
    if isinstance(value, list):
        return {"type": "list", "value": [normalized_value(item) for item in value]}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "value": [
                [normalized_value(key), normalized_value(item)]
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            ],
        }
    if callable(value):
        return {"type": "callable", "value": stable_identity(value)}
    raise AssertionError(f"unsupported argparse semantic value: {type(value).__name__}")


def normalized_choices(value: object | None) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            "type": "mapping_keys",
            "value": [normalized_value(key) for key in sorted(value, key=str)],
        }
    items = list(value)  # type: ignore[arg-type]
    if isinstance(value, (set, frozenset)):
        items.sort(key=str)
    return {
        "type": stable_identity(value),
        "value": [normalized_value(item) for item in items],
    }


def normalized_action_default(
    action: argparse.Action, *, repository_root: Path
) -> dict[str, object]:
    known_repository_default = str(repository_root / "config" / "ssh_config")
    if (
        action.dest == "mac_ssh_config"
        and action.option_strings == ["--mac-ssh-config"]
        and isinstance(action.default, str)
        and action.default == known_repository_default
    ):
        return {"type": "str", "value": "<REPO>/config/ssh_config"}
    return normalized_value(action.default)


def action_projection(
    subcommand: str, action: argparse.Action, *, repository_root: Path
) -> dict[str, object]:
    return {
        "subcommand": subcommand,
        "option_strings": list(action.option_strings),
        "dest": action.dest,
        "action_class": type(action).__name__,
        "nargs": action.nargs,
        "required": action.required,
        "default": normalized_action_default(action, repository_root=repository_root),
        "type_identity": stable_identity(action.type),
        "choices": normalized_choices(action.choices),
        "const": normalized_value(action.const),
        "metavar": normalized_value(action.metavar),
    }


def parser_snapshot(builder, program: str, *, repository_root: Path = ROOT) -> dict:
    with mock.patch.object(sys, "argv", [program]):
        parser = builder()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    actions = {
        "__top__": [
            action_projection("__top__", action, repository_root=repository_root)
            for action in parser._actions
        ],
        **{
            name: [
                action_projection(name, action, repository_root=repository_root)
                for action in child._actions
            ]
            for name, child in sorted(subparsers.choices.items())
        },
    }
    return {
        "parser": parser,
        "subparsers": subparsers,
        "subcommands": sorted(subparsers.choices),
        "actions": actions,
        "action_semantics_sha256": canonical_sha256(actions),
    }


class LegacyV254GoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    def test_manifest_is_placeholder_only_and_every_surface_is_classified(self) -> None:
        self.assertEqual(self.golden["golden_origin"]["commit"], "aa1c4614fc0d1cdecfc445a4db39a70700e2d7c6")
        self.assertTrue(self.golden["golden_origin"]["offline_only"])
        self.assertTrue(self.golden["golden_origin"]["placeholder_only"])
        self.assertFalse(
            self.golden["classification_policy"]["p0_p1_may_be_accepted_by_updating_golden"]
        )
        allowed = set(self.golden["classification_policy"]["allowed"])
        known_defects = []
        for name, surface in self.golden["surfaces"].items():
            with self.subTest(surface=name):
                self.assertIn(surface["classification"], allowed)
            if surface["classification"] == "known_defect_requiring_separate_reviewed_change":
                known_defects.append(name)
        self.assertEqual(known_defects, ["submit_help_defect"])
        fixture_text = GOLDEN_PATH.read_text(encoding="utf-8") + INPUT_PATH.read_text(encoding="utf-8")
        posix_user_root = "/" + "Users" + "/"
        for forbidden in (posix_user_root, "BEGIN PRIVATE KEY", "password", "token"):
            self.assertNotIn(forbidden, fixture_text)

    def _load_pbs_for_precedence(self, values: dict[str, str], environment: dict[str, str]):
        runtime = fake_runtime_module(values)
        name = "legacy_v254_precedence_" + hashlib.sha256(
            json.dumps([values, environment], sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.dict(
            sys.modules, {"runtime_config": runtime}
        ):
            return load_module(name, SCRIPTS / "gaussian_rtwin_pbs.py")

    def test_runtime_json_environment_fallback_and_cli_precedence(self) -> None:
        expected = self.golden["surfaces"]["runtime_precedence"]["order"]
        self.assertEqual(expected, ["cli", "environment", "runtime_json", "legacy_fallback", "repository_default"])

        from_json = self._load_pbs_for_precedence(
            {"rtwin_ssh_config": "/placeholder/runtime-json"}, {}
        )
        self.assertEqual(str(from_json.DEFAULT_MAC_SSH_CONFIG), "/placeholder/runtime-json")

        from_fallback = self._load_pbs_for_precedence(
            {}, {"GAUSSIAN_RTWIN_SSH_CONFIG": "/placeholder/legacy-fallback"}
        )
        self.assertEqual(str(from_fallback.DEFAULT_MAC_SSH_CONFIG), "/placeholder/legacy-fallback")

        from_environment = self._load_pbs_for_precedence(
            {"rtwin_ssh_config": "/placeholder/runtime-json"},
            {
                "GAUSSIAN_RTWIN_SSH_CONFIG": "/placeholder/legacy-fallback",
                "AUTO_G16_RTWIN_SSH_CONFIG": "/placeholder/environment",
            },
        )
        self.assertEqual(str(from_environment.DEFAULT_MAC_SSH_CONFIG), "/placeholder/environment")

        repository_default = self._load_pbs_for_precedence({}, {})
        self.assertEqual(repository_default.DEFAULT_MAC_SSH_CONFIG.name, "ssh_config")
        parsed = from_environment.build_parser().parse_args([
            "status", "--job-id", "123.placeholder",
            "--mac-ssh-config", "/placeholder/cli",
        ])
        self.assertEqual(parsed.mac_ssh_config, "/placeholder/cli")

    def test_public_cli_option_help_and_error_categories_are_characterized(self) -> None:
        expected = self.golden["surfaces"]["public_cli"]
        transport = parser_snapshot(PBS.build_parser, "gaussian_rtwin_pbs.py")
        wrapper = parser_snapshot(AUTO.build_parser, "gaussian_auto.py")
        additive_subcommands = [
            "build-fixed-constraint-audit",
            "finalize-fixed-constraint-input-review",
        ]
        self.assertEqual(
            sorted(
                set(transport["subcommands"])
                - set(expected["transport"]["subcommands"])
            ),
            additive_subcommands,
        )
        historical_subcommands = [
            name
            for name in transport["subcommands"]
            if name not in additive_subcommands
        ]
        self.assertEqual(
            historical_subcommands,
            expected["transport"]["subcommands"],
        )

        historical_actions = json.loads(
            json.dumps(transport["actions"], ensure_ascii=False)
        )
        for subcommand in additive_subcommands:
            historical_actions.pop(subcommand)
        top_level_subcommands = next(
            action
            for action in historical_actions["__top__"]
            if action["choices"] is not None
            and action["choices"]["type"] == "mapping_keys"
        )
        top_level_choices = top_level_subcommands["choices"]["value"]
        self.assertEqual(
            sorted(
                choice["value"]
                for choice in top_level_choices
                if choice["value"] in additive_subcommands
            ),
            additive_subcommands,
        )
        top_level_subcommands["choices"]["value"] = [
            choice
            for choice in top_level_choices
            if choice["value"] not in additive_subcommands
        ]
        fixed_constraint_actions = [
            (subcommand, action)
            for subcommand in expected["transport"]["subcommands"]
            for action in historical_actions[subcommand]
            if action["option_strings"] == ["--fixed-constraint-audit"]
        ]
        self.assertEqual(
            [subcommand for subcommand, _ in fixed_constraint_actions],
            ["build-input-approval"],
        )
        historical_actions["build-input-approval"] = [
            action
            for action in historical_actions["build-input-approval"]
            if action["option_strings"] != ["--fixed-constraint-audit"]
        ]
        self.assertEqual(
            canonical_sha256(historical_actions),
            expected["transport"]["action_semantics_sha256"],
        )
        self.assertEqual(wrapper["subcommands"], expected["wrapper"]["subcommands"])
        self.assertEqual(
            wrapper["action_semantics_sha256"],
            expected["wrapper"]["action_semantics_sha256"],
        )
        expected_projection_keys = {
            "subcommand", "option_strings", "dest", "action_class", "nargs", "required",
            "default", "type_identity", "choices", "const", "metavar",
        }
        for label, snapshot in (("transport", transport), ("wrapper", wrapper)):
            self.assertEqual(
                sorted(snapshot["actions"]),
                ["__top__", *snapshot["subcommands"]],
            )
            for subcommand, actions in snapshot["actions"].items():
                with self.subTest(parser=label, subcommand=subcommand):
                    self.assertTrue(actions)
                    self.assertTrue(all(set(action) == expected_projection_keys for action in actions))

        confirmed = next(
            action for action in transport["actions"]["submit"]
            if action["option_strings"] == ["--confirmed"]
        )
        self.assertEqual(confirmed, expected["transport"]["submit_confirmed"])
        self.assertEqual(confirmed["action_class"], "_StoreTrueAction")
        self.assertEqual(confirmed["default"], {"type": "bool", "value": False})
        self.assertEqual(confirmed["const"], {"type": "bool", "value": True})

        canonical_actions = json.dumps(
            {"transport": transport["actions"], "wrapper": wrapper["actions"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        repository_default_actions = [
            action
            for snapshot in (transport, wrapper)
            for actions in snapshot["actions"].values()
            for action in actions
            if action["option_strings"] == ["--mac-ssh-config"]
        ]
        self.assertTrue(repository_default_actions)
        self.assertTrue(all(
            action["default"] == {
                "type": "str", "value": "<REPO>/config/ssh_config",
            }
            for action in repository_default_actions
        ))
        self.assertNotIn(str(ROOT), canonical_actions)
        self.assertNotIn("/" + "Users" + "/", canonical_actions)
        with tempfile.TemporaryDirectory() as raw:
            relocated_root = Path(raw) / "source-archive"
            relocated_default = relocated_root / "config" / "ssh_config"
            with mock.patch.object(PBS, "DEFAULT_MAC_SSH_CONFIG", relocated_default):
                relocated_transport = parser_snapshot(
                    PBS.build_parser,
                    "gaussian_rtwin_pbs.py",
                    repository_root=relocated_root,
                )
                relocated_wrapper = parser_snapshot(
                    AUTO.build_parser,
                    "gaussian_auto.py",
                    repository_root=relocated_root,
                )
            self.assertEqual(relocated_transport["actions"], transport["actions"])
            self.assertEqual(relocated_wrapper["actions"], wrapper["actions"])
            self.assertEqual(
                relocated_transport["action_semantics_sha256"],
                transport["action_semantics_sha256"],
            )
            self.assertEqual(
                relocated_wrapper["action_semantics_sha256"],
                wrapper["action_semantics_sha256"],
            )

            unrelated_default = "/placeholder/external/ssh_config"
            with mock.patch.object(PBS, "DEFAULT_MAC_SSH_CONFIG", unrelated_default):
                unrelated = parser_snapshot(
                    PBS.build_parser,
                    "gaussian_rtwin_pbs.py",
                    repository_root=relocated_root,
                )
            unrelated_actions = [
                action
                for actions in unrelated["actions"].values()
                for action in actions
                if action["option_strings"] == ["--mac-ssh-config"]
            ]
            self.assertTrue(unrelated_actions)
            self.assertTrue(all(
                action["default"] == {"type": "str", "value": unrelated_default}
                for action in unrelated_actions
            ))
            self.assertNotEqual(
                unrelated["action_semantics_sha256"],
                transport["action_semantics_sha256"],
            )

        defect = self.golden["surfaces"]["submit_help_defect"]
        self.assertEqual(defect["exception"], "ValueError")
        self.assertFalse(defect["production_fix_in_scope"])
        submit_parser = transport["subparsers"].choices["submit"]
        with self.assertRaisesRegex(ValueError, defect["message_category"]):
            submit_parser.format_help()

        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            transport["parser"].parse_args([])
        self.assertEqual(stopped.exception.code, expected["error_categories"]["argparse_contract"]["exit"])
        self.assertTrue(error.getvalue().startswith(expected["error_categories"]["argparse_contract"]["prefix"]))
        for category, code in (("policy_validation", 2), ("interrupted", 130)):
            error = io.StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
                PBS.fail("synthetic category", code=code)
            self.assertEqual(stopped.exception.code, expected["error_categories"][category]["exit"])
            self.assertTrue(error.getvalue().startswith(expected["error_categories"][category]["prefix"]))

    def test_preflight_stage_and_dry_run_field_sets_are_non_authorizing(self) -> None:
        expected = self.golden["surfaces"]["dry_run_json"]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with mock.patch.object(PBS.subprocess, "run", side_effect=AssertionError("network/process boundary crossed")), \
                 mock.patch.object(PBS.time, "time", return_value=1_700_000_000.0), \
                 mock.patch.object(PBS.time, "sleep", side_effect=AssertionError("sleep boundary crossed")), \
                 mock.patch.object(PBS.random, "uniform", return_value=0.0), \
                 mock.patch.object(PBS, "utc_now", return_value="2026-01-01T00:00:00Z"):
                preflight = PBS.parse_gaussian(INPUT_PATH)
                preflight.update({
                    "project": "goldenjob",
                    "remote_workdir": PBS.remote_project_dir("goldenjob"),
                })
                self.assertEqual(sorted(preflight), expected["preflight_fields"])

                job, files = PBS.stage(INPUT_PATH, "goldenjob", root / "stage")
                self.assertEqual(sorted({"job": job, "files": files}), expected["stage_output_fields"])
                self.assertEqual(sorted(job), expected["stage_job_fields"])
                for marker, value in expected["stage_markers"].items():
                    self.assertEqual(job[marker], value)

                prepare_args = AUTO.build_parser().parse_args([
                    "prepare", str(INPUT_PATH), "--project", "goldenjob",
                    "--local-dir", str(root / "wrapper"), "--work-kind", "ordinary",
                ])
                wrapper_summary = AUTO.prepare_source(prepare_args)
                self.assertEqual(sorted(wrapper_summary), expected["wrapper_preflight_fields"])
                self.assertTrue(wrapper_summary["input_approval"]["no_submission_authorization"])

                submit_args = PBS.build_parser().parse_args([
                    "submit", str(INPUT_PATH), "--project", "goldenjob",
                    "--local-dir", str(root / "submit"), "--confirmed", "--dry-run",
                    "--work-kind", "ordinary",
                ])
                output = io.StringIO()
                with redirect_stdout(output):
                    submit_args.func(submit_args)
                plan = json.loads(output.getvalue())
                self.assertEqual(sorted(plan), expected["submit_dry_run_fields"])
                self.assertFalse(plan["live_submission_ready"])
                self.assertTrue(plan["input_approval"]["no_submission_authorization"])

            auto_args = AUTO.build_parser().parse_args([
                "auto", str(INPUT_PATH), "--project", "goldenjob",
                "--local-dir", str(root / "auto"), "--confirmed", "--dry-run",
                "--work-kind", "ordinary",
            ])
            child = subprocess.CompletedProcess([], 0, "", "")
            output = io.StringIO()
            with mock.patch.object(AUTO.subprocess, "run", return_value=child) as invoked, \
                 mock.patch.object(AUTO.transport.time, "time", return_value=1_700_000_000.0), \
                 mock.patch.object(AUTO.transport.random, "uniform", return_value=0.0), \
                 redirect_stdout(output):
                AUTO.command_auto(auto_args)
            child_argv = invoked.call_args.args[0]
            for token in expected["child_contains"]:
                self.assertIn(token, child_argv)
            approved = json.loads(output.getvalue())["approved_preflight"]
            self.assertTrue(approved["input_approval"]["no_submission_authorization"])

    def test_pbs_template_and_rendered_bytes_are_exact(self) -> None:
        expected = self.golden["surfaces"]["pbs_bytes"]
        template = (ROOT / "templates" / "g16_job.pbs.template").read_bytes()
        self.assertEqual(hashlib.sha256(template).hexdigest(), expected["template_sha256"])
        plain = PBS.pbs_text("goldenjob", "input.gjf", 8)
        resource = PBS.pbs_text(
            "goldenjob", "input.gjf", 8,
            mem_gb=12, walltime_seconds=86400, resource_tier="simple",
        )
        self.assertEqual(sha256_text(plain), expected["plain_sha256"])
        self.assertEqual(sha256_text(resource), expected["resource_bound_sha256"])
        for text in (plain, resource):
            self.assertIn('allowed_root="/home/user100/SDL"', text)
            self.assertIn('scratch="$work_real/scratch"', text)
            self.assertIn('export GAUSS_SCRDIR="$scratch_real"', text)
            self.assertTrue(text.endswith('g16 "input.gjf"\n'))

    def test_structured_argv_powershell_and_remote_script_bytes_are_exact(self) -> None:
        expected = self.golden["surfaces"]["command_scripts"]
        args = SimpleNamespace(
            mac_ssh_config="/placeholder/mac_ssh_config",
            rtwin_alias="rtwin-placeholder",
            windows_server_config=r"C:\Placeholder\server_config",
            server_alias="server-placeholder",
        )
        with mock.patch.object(Path, "is_file", return_value=True):
            self.assertEqual(
                PBS.ssh_base(args),
                ["ssh", "-F", "/placeholder/mac_ssh_config", "rtwin-placeholder"],
            )
            self.assertEqual(
                PBS.nested_ssh(args, "qstat", "-f", "123.placeholder"),
                [
                    "ssh", "-F", "/placeholder/mac_ssh_config", "rtwin-placeholder",
                    "ssh", "-F", r"C:\Placeholder\server_config", "server-placeholder",
                    "qstat", "-f", "123.placeholder",
                ],
            )
            self.assertEqual(
                PBS.nested_ssh(args, "qdel", "123.placeholder"),
                [
                    "ssh", "-F", "/placeholder/mac_ssh_config", "rtwin-placeholder",
                    "ssh", "-F", r"C:\Placeholder\server_config", "server-placeholder",
                    "qdel", "123.placeholder",
                ],
            )
        self.assertEqual(
            PBS.powershell_encoded("Write-Output placeholder"),
            expected["powershell_utf16le_base64"],
        )
        scripts = {
            "remote_claim": PBS.remote_empty_directory_guard("goldenjob"),
            "remote_read": PBS.remote_existing_directory_guard("goldenjob"),
            "job_snapshot": PBS.server_job_snapshot_script("goldenjob", "input", "123.placeholder"),
            "fetch_inventory": PBS.server_fetch_inventory_script(
                "goldenjob", ["input.gjf", "input.log"], ["input.chk"]
            ),
            "fetch_hash": PBS.server_fetch_hash_script(
                "goldenjob", {"input.gjf": 10, "input.log": 20}
            ),
        }
        for name, script in scripts.items():
            with self.subTest(script=name):
                self.assertEqual(len(script.encode("utf-8")), expected[name]["bytes"])
                self.assertEqual(sha256_text(script), expected[name]["sha256"])
                self.assertNotRegex(script, r"(^|[;&|\s])(?:rm|rmdir|truncate)(?:\s|$)")
                self.assertNotIn("/tmp", script)

    def test_protected_submit_upload_hash_and_qsub_plan_is_an_exact_mocked_snapshot(self) -> None:
        # Reuse the existing package-4 synthetic artifact builder, but execute only
        # through a fully mocked command boundary and replace every machine value.
        from tests import test_resource_monitor_efficiency as package4

        expected = self.golden["surfaces"]["command_scripts"]
        helper = package4.ResourceMonitorEfficiencyTests(
            "test_v2_to_v3_is_explicit_and_v2_interface_remains_historical"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            calls: list[tuple[list[str], bytes | None, int, bool]] = []

            def mocked_run(command, *, input_bytes=None, check=True,
                           timeout_seconds=package4.PBS.DEFAULT_COMMAND_TIMEOUT_SECONDS):
                calls.append((command, input_bytes, timeout_seconds, check))
                if "-EncodedCommand" in command:
                    script = base64.b64decode(command[-1]).decode("utf-16le")
                    if "Get-FileHash" in script:
                        bundle = root / "bundle"
                        ignored = {
                            "job.json", "job.events.jsonl", "job.json.lock",
                            "live-approval-consumption.json",
                        }
                        lines = [
                            f"{path.name} {package4.PBS.sha256(path)}"
                            for path in bundle.iterdir()
                            if path.is_file() and path.name not in ignored
                        ]
                        return subprocess.CompletedProcess(command, 0, "\n".join(lines), "")
                if input_bytes and b"qsub -v " in input_bytes:
                    return subprocess.CompletedProcess(command, 0, "123.placeholder\n", "")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(
                package4.PBS, "utc_now", return_value="2026-01-01T00:04:00Z"
            ), mock.patch.object(
                package4.PBS.time, "time", return_value=1_767_225_840.0
            ), mock.patch.object(
                package4.PBS.time, "time_ns", return_value=1_767_225_840_000_000_000
            ), mock.patch.object(
                package4.PBS.os, "getpid", return_value=4242
            ):
                args, _, _, input_approval, live = helper.make_live_submit_fixture(root)
                args.windows_root = r"C:\Placeholder\GaussianProjects"
                args.windows_server_config = r"C:\Placeholder\server_config"
                args.rtwin_alias = "rtwin-placeholder"
                args.server_alias = "server-placeholder"
                with mock.patch.object(
                    package4.PBS, "validate_input_approval", return_value=input_approval
                ), mock.patch.object(
                    package4.PBS, "validate_live_approval_binding", return_value=(live, "d" * 64)
                ), mock.patch.object(
                    package4.PBS, "run", side_effect=mocked_run
                ), mock.patch.object(
                    package4.PBS.subprocess, "run",
                    side_effect=AssertionError("direct subprocess boundary crossed"),
                ), mock.patch.object(
                    package4.PBS.time, "sleep", side_effect=AssertionError("sleep boundary crossed")
                ), mock.patch.object(
                    package4.PBS.random, "uniform", return_value=0.0
                ), redirect_stdout(io.StringIO()):
                    package4.PBS.LegacyCLICompatibilityAdapter()._run_offline_differential_transaction(args)

            normalized = []
            for command, input_bytes, timeout_seconds, check in calls:
                argv = []
                for index, value in enumerate(command):
                    value = str(value).replace(str(root), "<TMP>")
                    if index == len(command) - 1 and "-EncodedCommand" in command:
                        value = base64.b64decode(value).decode("utf-16le").replace(
                            str(root), "<TMP>"
                        )
                    argv.append(value)
                normalized.append({
                    "argv": argv,
                    "stdin": input_bytes.decode("utf-8") if input_bytes else None,
                    "timeout": timeout_seconds,
                    "check": check,
                })

        self.assertEqual(len(normalized), expected["protected_submit_network_call_count"])
        self.assertEqual(canonical_sha256(normalized), expected["protected_submit_plan_sha256"])
        combined = json.dumps(normalized, ensure_ascii=False)
        self.assertEqual(combined.count("qsub -v "), 1)
        self.assertIn("gaussian-remote-submission-receipt/1", combined)
        self.assertIn("Get-FileHash", combined)
        self.assertIn("sha256sum -c checksums.sha256", combined)
        self.assertNotIn("qdel", combined)
        self.assertNotRegex(combined, r"(^|[;&|\s])(?:rm|rmdir|truncate)(?:\s|$)")
        self.assertNotIn("/" + "Users" + "/", combined)
        self.assertNotRegex(combined, r"C:\\+Users\\+")

    def test_fetch_per_hop_plan_is_an_exact_mocked_snapshot(self) -> None:
        from tests import test_runtime_safety_hardening as safety

        expected = self.golden["surfaces"]["command_scripts"]
        helper = safety.RuntimeSafetyHardeningTests(
            "test_fetch_snapshot_selects_exact_log_and_verifies_both_hops"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            calls: list[tuple[list[str], bytes | None, int, bool]] = []

            def mocked_run(command, *, input_bytes=None, check=True,
                           timeout_seconds=safety.PBS.DEFAULT_COMMAND_TIMEOUT_SECONDS):
                index = len(calls)
                calls.append((command, input_bytes, timeout_seconds, check))
                if index == 0:
                    return safety.completed(0, helper.inventory_text(files))
                if index == 1:
                    return safety.completed(0, helper.server_hash_text(files))
                if index in {2, 3}:
                    return safety.completed()
                if index == 4:
                    return safety.completed(0, helper.rtwin_hash_text(files))
                if index == 5:
                    staging = Path(command[-1])
                    for name, data in files.items():
                        (staging / name).write_bytes(data)
                    return safety.completed()
                raise AssertionError(f"unexpected fetch command: {command}")

            with mock.patch.object(
                safety.PBS, "utc_now", return_value="2026-01-01T00:08:00Z"
            ), mock.patch.object(
                safety.PBS.time, "time", return_value=1_767_226_080.0
            ), mock.patch.object(
                safety.PBS.time, "time_ns", return_value=1_700_000_000_000_000_000
            ), mock.patch.object(
                safety.PBS.os, "getpid", return_value=4242
            ):
                args, _, files = helper.make_fetch_case(root)
                output = root / "snapshot"
                args.windows_root = r"C:\Placeholder\GaussianProjects"
                args.windows_server_config = r"C:\Placeholder\server_config"
                args.rtwin_alias = "rtwin-placeholder"
                args.server_alias = "server-placeholder"
                with mock.patch.object(
                    safety.PBS, "run", side_effect=mocked_run
                ), mock.patch.object(
                    safety.PBS.subprocess, "run",
                    side_effect=AssertionError("direct subprocess boundary crossed"),
                ), mock.patch.object(
                    safety.PBS, "analyze_log_file", return_value={"status": "completed"}
                ), mock.patch.object(
                    safety.PBS.time, "sleep", side_effect=AssertionError("sleep boundary crossed")
                ), mock.patch.object(
                    safety.PBS.random, "uniform", return_value=0.0
                ):
                    safety.PBS.fetch_results(args, "safe_job", output)

            def normalize(value: object) -> str:
                text = str(value).replace(str(root), "<TMP>").replace(
                    "123.master", "123.placeholder"
                )
                return re.sub(r"<TMP>/\.fetch-network-[^/]+/", "<FETCH_STAGING>/", text)

            normalized = []
            for command, input_bytes, timeout_seconds, check in calls:
                argv = []
                for index, value in enumerate(command):
                    value = normalize(value)
                    if index == len(command) - 1 and "-EncodedCommand" in command:
                        value = normalize(base64.b64decode(value).decode("utf-16le"))
                    argv.append(value)
                normalized.append({
                    "argv": argv,
                    "stdin": normalize(input_bytes.decode("utf-8")) if input_bytes else None,
                    "timeout": timeout_seconds,
                    "check": check,
                })

        self.assertEqual(len(normalized), expected["fetch_network_call_count"])
        self.assertEqual(canonical_sha256(normalized), expected["fetch_plan_sha256"])
        combined = json.dumps(normalized, ensure_ascii=False)
        self.assertIn("Get-FileHash", combined)
        self.assertIn("sha256sum", combined)
        self.assertNotIn("scratch", combined)
        self.assertNotIn("qsub", combined)
        self.assertNotIn("qdel", combined)
        self.assertNotRegex(combined, r"(^|[;&|\s])(?:rm|rmdir|truncate)(?:\s|$)")

    @staticmethod
    def _completed_from_case(case: dict[str, object]) -> subprocess.CompletedProcess:
        return completed(
            int(case["returncode"]),
            str(case.get("stdout", "")),
            str(case.get("stderr", "")),
        )

    def _assert_state_matrix_cases(self, matrix: dict[str, object]) -> None:
        classifiers = {
            "qsub": PBS.classify_qsub_outcome,
            "qstat": PBS.classify_qstat_evidence,
            "process": PBS.classify_process_evidence,
            "qdel": PBS.classify_qdel_outcome,
        }
        for family, classifier in classifiers.items():
            for case_id, case in matrix[family].items():  # type: ignore[index,union-attr]
                with self.subTest(family=family, case=case_id):
                    actual = classifier(self._completed_from_case(case["input"]))
                    self.assertEqual(actual, case["expected"])

        for case_id, case in matrix["inspection"].items():  # type: ignore[index,union-attr]
            with self.subTest(family="inspection", case=case_id):
                state, expected_stages, workflow_complete, workflow_failed = (
                    PBS.classify_inspection_state(**case["input"])
                )
                self.assertEqual(
                    {
                        "state": state,
                        "expected_stages": expected_stages,
                        "workflow_complete": workflow_complete,
                        "workflow_failed": workflow_failed,
                    },
                    case["expected"],
                )

        for case_id, case in matrix["submission_reconciliation"].items():  # type: ignore[index,union-attr]
            with self.subTest(family="submission_reconciliation", case=case_id):
                actual = PBS.classify_submission_reconciliation(**case["input"])
                self.assertEqual(actual, case["expected"])
                self.assertIs(actual["automatic_qsub_authorized"], False)

    def test_qsub_qstat_process_qdel_inspection_and_reconciliation_case_mappings(self) -> None:
        self._assert_state_matrix_cases(self.golden["surfaces"]["state_matrix"])

    def test_state_matrix_case_keys_reject_classification_permutations(self) -> None:
        expected = self.golden["surfaces"]["state_matrix"]
        qsub_mutation = json.loads(json.dumps(expected))
        unique = qsub_mutation["qsub"]["success_unique"]["expected"]
        uncertain = qsub_mutation["qsub"]["success_without_job_id"]["expected"]
        unique["classification"], uncertain["classification"] = (
            uncertain["classification"], unique["classification"]
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                PBS.classify_qsub_outcome(
                    self._completed_from_case(
                        qsub_mutation["qsub"]["success_unique"]["input"]
                    )
                ),
                qsub_mutation["qsub"]["success_unique"]["expected"],
            )

        reconciliation_mutation = json.loads(json.dumps(expected))
        submitted = reconciliation_mutation["submission_reconciliation"][
            "exact_qstat_and_intent"
        ]["expected"]
        absent = reconciliation_mutation["submission_reconciliation"][
            "directory_absent_no_job"
        ]["expected"]
        submitted["classification"], absent["classification"] = (
            absent["classification"], submitted["classification"]
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                PBS.classify_submission_reconciliation(
                    **reconciliation_mutation["submission_reconciliation"][
                        "exact_qstat_and_intent"
                    ]["input"]
                ),
                reconciliation_mutation["submission_reconciliation"][
                    "exact_qstat_and_intent"
                ]["expected"],
            )

    def test_fetch_allowlist_and_cross_cutting_prohibitions_remain_closed(self) -> None:
        surface = self.golden["surfaces"]["fetch_and_historical_owners"]
        self.assertFalse(surface["automatic_retry"])
        self.assertFalse(surface["delete_server_data"])
        self.assertFalse(surface["remote_root_override"])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            job, _ = PBS.stage(INPUT_PATH, "goldenjob", root)
            required, optional, hashes = PBS.load_fetch_allowlist(root, job, "legacy_v2_5_4_input")
        self.assertEqual(
            required,
            ["checksums.sha256", "goldenjob.pbs", "legacy_v2_5_4_input.gjf", "legacy_v2_5_4_input.log"],
        )
        self.assertEqual(optional, ["goldenjob.pbs.out", "legacy_v254.chk"])
        self.assertEqual(set(hashes), {"checksums.sha256", "goldenjob.pbs", "legacy_v2_5_4_input.gjf"})
        parser = PBS.build_parser()
        subparsers = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        every_option = {
            option
            for child in subparsers.choices.values()
            for action in child._actions
            for option in action.option_strings
        }
        self.assertNotIn("--remote-root", every_option)
        self.assertNotIn("delete", subparsers.choices)
        self.assertNotIn("cleanup-files", subparsers.choices)


if __name__ == "__main__":
    unittest.main()
