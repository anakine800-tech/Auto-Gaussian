#!/usr/bin/env python3
"""Offline compatibility tests for the private legacy transaction owner."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
SOURCE = SCRIPTS / "legacy_rtwin_pbs.py"
FIXTURE = ROOT / "tests" / "fixtures" / "rtwin_pbs" / "legacy_v2_5_4_input.gjf"
sys.path.insert(0, str(SCRIPTS))

import legacy_rtwin_pbs as legacy  # noqa: E402


def submit_args(local_dir: Path, *, confirmed: bool = True) -> object:
    argv = [
        "submit",
        str(FIXTURE),
        "--project",
        "goldenjob",
        "--local-dir",
        str(local_dir),
        "--dry-run",
        "--work-kind",
        "ordinary",
    ]
    if confirmed:
        argv.append("--confirmed")
    return legacy.build_parser().parse_args(argv)


def normalize_state(value: object, root: Path) -> object:
    if isinstance(value, dict):
        return {
            key: normalize_state(item, root)
            for key, item in value.items()
            if key not in {"event_sha256", "previous_event_sha256", "state_event_sha256", "state_sha256"}
        }
    if isinstance(value, list):
        return [normalize_state(item, root) for item in value]
    if isinstance(value, str):
        normalized = value.replace(str(root), "<LOCAL_DIR>")
        return re.sub(r"\.submit-snapshot-[^/]+", ".submit-snapshot-<TOKEN>", normalized)
    return value


class LegacyTransactionOwnerTests(unittest.TestCase):
    maxDiff = None

    def test_private_plan_rejects_ordinary_construction_and_is_frozen_slots(self) -> None:
        with self.assertRaisesRegex(TypeError, "legacy CLI owner"):
            legacy._LegacyTransactionPlan()  # type: ignore[call-arg]
        forged = object.__new__(legacy._LegacyTransactionPlan)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
            legacy._execute_legacy_transaction_once(
                forged,
                _transaction_token=legacy._BACKEND_TRANSACTION_TOKEN,
            )
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(
            stderr.getvalue(),
            "ERROR: legacy transaction plan lacks the CLI owner seal\n",
        )
        with tempfile.TemporaryDirectory() as raw:
            args = submit_args(Path(raw) / "bundle")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
                legacy._legacy_transaction_plan_from_cli_namespace(args)
            self.assertEqual(stopped.exception.code, 2)
            self.assertEqual(
                stderr.getvalue(),
                "ERROR: legacy transaction is internal to the sole backend dispatch\n",
            )
            plan = legacy._legacy_transaction_plan_from_cli_namespace(
                args,
                _factory_token=legacy._BACKEND_TRANSACTION_TOKEN,
            )
        self.assertFalse(hasattr(plan, "__dict__"))
        with self.assertRaisesRegex(AttributeError, "is frozen"):
            plan.project = "other"  # type: ignore[misc]
        for forbidden in (
            "from_mapping",
            "callback",
            "runner",
            "command",
            "backend",
            "argv",
        ):
            self.assertFalse(hasattr(plan, forbidden))

    def test_namespace_is_consumed_only_by_factory_and_one_owner_is_called(self) -> None:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        factory = functions["_legacy_transaction_plan_from_cli_namespace"]
        wrapper = functions["_legacy_transaction_once"]
        owner = functions["_execute_legacy_transaction_once"]
        self.assertTrue(any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "args"
            for node in ast.walk(factory)
        ))
        for function in (wrapper, owner):
            self.assertFalse(any(
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "args"
                for node in ast.walk(function)
            ))
        self.assertEqual(
            [argument.arg for argument in owner.args.args],
            ["plan"],
        )
        owner_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_execute_legacy_transaction_once"
        ]
        self.assertEqual(len(owner_calls), 1)

        with tempfile.TemporaryDirectory() as raw:
            args = submit_args(Path(raw) / "bundle")
            with mock.patch.object(legacy, "_execute_legacy_transaction_once") as invoked:
                legacy._legacy_transaction_once(
                    args,
                    _transaction_token=legacy._BACKEND_TRANSACTION_TOKEN,
                )
        invoked.assert_called_once()
        called_plan = invoked.call_args.args[0]
        self.assertIsInstance(called_plan, legacy._LegacyTransactionPlan)
        self.assertIsNot(called_plan, args)

    def test_dry_run_preserves_effect_order_output_and_staged_bytes(self) -> None:
        ordered_functions = (
            "validate_project",
            "capture_submission_snapshot",
            "parse_gaussian",
            "audit_scientific_maturity",
            "input_approval_compatibility",
            "stage",
            "update_job",
            "verify_staged_submission",
        )
        expected_order = [
            "validate_project",
            "capture_submission_snapshot",
            "parse_gaussian",
            "audit_scientific_maturity",
            "input_approval_compatibility",
            "stage",
            "parse_gaussian",
            "validate_project",
            "update_job",
            "verify_staged_submission",
            "parse_gaussian",
            "validate_project",
        ]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            wrapper_dir = root / "wrapper"
            owner_dir = root / "owner"
            wrapper_args = submit_args(wrapper_dir)
            owner_args = submit_args(owner_dir)
            calls: list[str] = []
            wrapper_stdout = io.StringIO()
            with contextlib.ExitStack() as stack:
                for name in ordered_functions:
                    original = getattr(legacy, name)

                    def record(*args, _name=name, _original=original, **kwargs):
                        calls.append(_name)
                        return _original(*args, **kwargs)

                    stack.enter_context(mock.patch.object(legacy, name, side_effect=record))
                stack.enter_context(mock.patch.object(
                    legacy,
                    "run",
                    side_effect=AssertionError("runner boundary crossed during dry-run"),
                ))
                stack.enter_context(mock.patch.object(
                    legacy,
                    "utc_now",
                    return_value="2026-07-24T00:00:00Z",
                ))
                stack.enter_context(contextlib.redirect_stdout(wrapper_stdout))
                legacy._legacy_transaction_once(
                    wrapper_args,
                    _transaction_token=legacy._BACKEND_TRANSACTION_TOKEN,
                )
            self.assertEqual(calls, expected_order)

            owner_stdout = io.StringIO()
            owner_plan = legacy._legacy_transaction_plan_from_cli_namespace(
                owner_args,
                _factory_token=legacy._BACKEND_TRANSACTION_TOKEN,
            )
            with mock.patch.object(
                legacy,
                "run",
                side_effect=AssertionError("runner boundary crossed during dry-run"),
            ), mock.patch.object(
                legacy,
                "utc_now",
                return_value="2026-07-24T00:00:00Z",
            ), contextlib.redirect_stdout(owner_stdout):
                legacy._execute_legacy_transaction_once(
                    owner_plan,
                    _transaction_token=legacy._BACKEND_TRANSACTION_TOKEN,
                )

            wrapper_output = json.loads(wrapper_stdout.getvalue())
            owner_output = json.loads(owner_stdout.getvalue())
            wrapper_output["local_dir"] = "<LOCAL_DIR>"
            owner_output["local_dir"] = "<LOCAL_DIR>"
            self.assertEqual(wrapper_output, owner_output)
            stable_files = (
                "legacy_v2_5_4_input.gjf",
                "goldenjob.pbs",
                "checksums.sha256",
            )
            self.assertEqual(
                {name: (wrapper_dir / name).read_bytes() for name in stable_files},
                {name: (owner_dir / name).read_bytes() for name in stable_files},
            )
            self.assertEqual(
                normalize_state(json.loads((wrapper_dir / "job.json").read_text()), wrapper_dir),
                normalize_state(json.loads((owner_dir / "job.json").read_text()), owner_dir),
            )
            wrapper_events = [
                normalize_state(json.loads(line), wrapper_dir)
                for line in (wrapper_dir / "job.events.jsonl").read_text().splitlines()
            ]
            owner_events = [
                normalize_state(json.loads(line), owner_dir)
                for line in (owner_dir / "job.events.jsonl").read_text().splitlines()
            ]
            self.assertEqual(wrapper_events, owner_events)
            self.assertTrue(wrapper_output["dry_run"])
            self.assertFalse(wrapper_output["live_submission_ready"])

    def test_legacy_entry_error_text_exit_code_and_zero_files_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            local_dir = Path(raw) / "bundle"
            args = submit_args(local_dir, confirmed=False)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
                legacy._legacy_transaction_once(
                    args,
                    _transaction_token=legacy._BACKEND_TRANSACTION_TOKEN,
                )
            self.assertEqual(stopped.exception.code, 2)
            self.assertEqual(
                stderr.getvalue(),
                "ERROR: submit requires --confirmed after the exact preflight is approved\n",
            )
            self.assertFalse(local_dir.exists())


if __name__ == "__main__":
    unittest.main()
