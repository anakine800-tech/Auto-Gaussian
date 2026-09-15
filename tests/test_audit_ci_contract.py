#!/usr/bin/env python3
"""Offline tests for the static required-check contract audit."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "audit_ci_contract.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_ci_contract_test", MODULE_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


WORKFLOW = """name: Offline tests

on: [pull_request]

jobs:
  python-compatibility:
    name: python-compatibility (${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [\"3.11\", \"3.12\", \"3.13\"]
    steps:
      - run: python -m unittest
  source-archive-release:
    name: source-archive-release
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/run_tests.py
  chemistry-dependencies:
    name: chemistry-dependencies
    runs-on: ubuntu-latest
    steps:
      - run: python -m unittest tests.test_rdkit_smoke
"""


def contract() -> dict[str, object]:
    checks = [
        {
            "context": f"python-compatibility ({version})",
            "workflow_file": ".github/workflows/offline-tests.yml",
            "workflow_name": "Offline tests",
            "job_id": "python-compatibility",
            "matrix": {"python-version": version},
        }
        for version in ("3.11", "3.12", "3.13")
    ]
    checks.extend(
        {
            "context": name,
            "workflow_file": ".github/workflows/offline-tests.yml",
            "workflow_name": "Offline tests",
            "job_id": name,
            "matrix": {},
        }
        for name in ("source-archive-release", "chemistry-dependencies")
    )
    return {
        "schema": AUDIT.SCHEMA,
        "version": 1,
        "description": "fixture",
        "source_evidence": {
            "observed_at": "2026-07-20",
            "successful_run_id": 29736511783,
            "workflow_name": "Offline tests",
            "basis": "fixture",
        },
        "required_checks": checks,
        "remote_branch_protection_snapshot": {
            "observed_at": "2026-07-21",
            "strict": True,
            "app_id": 15368,
            "required_contexts": [item["context"] for item in checks],
            "enforce_admins": True,
            "required_conversation_resolution": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "rulesets_count": 0,
            "status": "aligned",
            "note": "fixture snapshot",
        },
        "limitations": ["static only"],
    }


class CIContractAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "-C", str(self.root), "init", "-b", "main"], check=True, capture_output=True)
        self.workflow = self.root / ".github" / "workflows" / "offline-tests.yml"
        self.workflow.parent.mkdir(parents=True)
        self.workflow.write_text(WORKFLOW, encoding="utf-8")
        self.config = self.root / "config" / "required-checks.json"
        self.config.parent.mkdir()
        self.write_contract(contract())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_contract(self, value: dict[str, object]) -> None:
        self.config.write_text(json.dumps(value), encoding="utf-8")

    def auxiliary_fixture(self, text: str | None = None) -> tuple[Path, Path, dict[str, object]]:
        workflow = self.workflow.parent / "r4-linux.yml"
        workflow.write_text(text if text is not None else (ROOT / ".github/workflows/r4-linux.yml").read_text())
        value = json.loads((ROOT / "config/auxiliary-workflows.json").read_text())
        value["workflow"]["sha256"] = hashlib.sha256(workflow.read_bytes()).hexdigest()
        config = self.config.parent / "auxiliary-workflows.json"
        config.write_text(json.dumps(value))
        return workflow, config, value

    def test_auxiliary_preserves_required_and_historical_evidence(self) -> None:
        required_bytes = self.config.read_bytes()
        self.auxiliary_fixture()
        value = AUDIT.load_contract(self.config)
        before = copy.deepcopy(value)
        report = AUDIT.audit(self.root, value)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(value, before)
        self.assertEqual(self.config.read_bytes(), required_bytes)
        self.assertEqual(len(value["required_checks"]), 5)
        self.assertEqual(report["summary"]["declared_contexts"], 6)
        self.assertEqual(report["snapshot_difference"], {"missing_expected_contexts": [], "unexpected_contexts": []})
        self.assertFalse(report["actual_ci_success_verified"])

    def test_unregistered_extra_workflow_still_fails(self) -> None:
        self.auxiliary_fixture()
        (self.workflow.parent / "rogue.yml").write_text("name: Rogue\njobs:\n  rogue:\n    name: Rogue\n")
        report = AUDIT.audit(self.root, contract())
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("missing from the required" in item for item in report["errors"]))

    def test_missing_auxiliary_registration_preserves_old_rejection(self) -> None:
        _, config, _ = self.auxiliary_fixture()
        config.rename(config.with_suffix(".retained"))
        self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")

    def test_auxiliary_never_fills_missing_required_workflow(self) -> None:
        self.auxiliary_fixture()
        self.workflow.rename(self.workflow.with_suffix(".retained"))
        report = AUDIT.audit(self.root, contract())
        self.assertEqual(report["status"], "fail")
        self.assertEqual(sum("not declared" in e for e in report["errors"]), 5)

    def test_auxiliary_does_not_relax_required_mapping_or_duplicates(self) -> None:
        self.auxiliary_fixture()
        for text in (WORKFLOW.replace("  chemistry-dependencies:", "  renamed:"),
                     WORKFLOW + "  duplicate:\n    name: source-archive-release\n"):
            with self.subTest(text=text):
                self.workflow.write_text(text)
                self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")

    def test_auxiliary_missing_symlink_and_hash_drift_fail(self) -> None:
        workflow, config, _ = self.auxiliary_fixture()
        original = workflow.read_bytes()
        workflow.write_bytes(original + b"\n")
        self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")
        retained = workflow.with_suffix(".retained")
        workflow.rename(retained)
        self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")
        workflow.symlink_to(retained)
        self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")
        config.rename(config.with_suffix(".retained"))
        config.symlink_to(config.with_suffix(".retained"))
        self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")

    def test_auxiliary_closed_registration_rejects_invalid_and_mixed_fields(self) -> None:
        _, config, original = self.auxiliary_fixture()
        mutations = [
            {**original, "enabled": True},
            {**original, "workflow": [original["workflow"]]},
            {**original, "schema": "auto-g16-r4-auxiliary/2"},
        ]
        for key, value in (("context", "source-archive-release"), ("branch", "main"),
                           ("paths", ["**"]), ("workflow_file", "../escape.yml"),
                           ("sha256", True), ("matrix", {})):
            changed = copy.deepcopy(original)
            changed["workflow"][key] = value
            mutations.append(changed)
        for value in mutations:
            with self.subTest(value=value):
                config.write_text(json.dumps(value))
                self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")
        for raw in ('{"schema": 1, "schema": 2}', '{"value": NaN}', '{', '[]'):
            config.write_text(raw)
            self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")

    def test_rehashed_auxiliary_cannot_widen_trigger_or_job_scope(self) -> None:
        original = (ROOT / ".github/workflows/r4-linux.yml").read_text()
        mutations = [
            original.replace("branches: [codex/v31-r4-linux-harness]", "branches: [main]"),
            original.replace("  push:\n", "  pull_request:\n"),
            original.replace("permissions:\n", "on: [pull_request]\n\npermissions:\n"),
            original.replace("  contents: read", "  contents: write"),
            original.replace("    timeout-minutes: 26", "    timeout-minutes: 60"),
            original.replace("    runs-on: ubuntu-24.04", "    runs-on: self-hosted"),
            original + "\non: [push]\n",
            original + "\n  other:\n    name: other\n",
            original + "\n    permissions: write-all\n",
            original.replace("      - validation/r4/**", "      - '**'"),
        ]
        for text in mutations:
            with self.subTest(text=text):
                self.auxiliary_fixture(text)
                self.assertEqual(AUDIT.audit(self.root, contract())["status"], "fail")

    def test_auxiliary_cannot_be_registered_as_required(self) -> None:
        self.auxiliary_fixture()
        value = contract()
        value["required_checks"][0]["context"] = "R4 bounded Linux evidence"
        report = AUDIT.audit(self.root, value)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("cannot replace" in e for e in report["errors"]))

    def test_simple_matrix_expands_to_exact_actual_check_names(self) -> None:
        value = AUDIT.load_contract(self.config)
        report = AUDIT.audit(self.root, value)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["warnings"], 0)
        self.assertEqual(report["declared_contexts"], sorted(item["context"] for item in value["required_checks"]))
        self.assertFalse(report["remote_branch_protection_verified"])
        self.assertEqual(report["snapshot_difference"]["missing_expected_contexts"], [])
        self.assertEqual(report["snapshot_difference"]["unexpected_contexts"], [])

    def test_synthetic_snapshot_mismatch_remains_a_warning(self) -> None:
        value = contract()
        snapshot = value["remote_branch_protection_snapshot"]  # type: ignore[assignment]
        snapshot["required_contexts"] = [  # type: ignore[index]
            "python-compatibility (3.11)",
            "python-compatibility (3.12)",
        ]
        snapshot["status"] = "known_mismatch"  # type: ignore[index]
        report = AUDIT.audit(self.root, value)
        self.assertEqual(report["status"], "pass_with_warnings")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["warnings"], 1)
        self.assertEqual(
            report["snapshot_difference"]["missing_expected_contexts"],
            ["chemistry-dependencies", "python-compatibility (3.13)", "source-archive-release"],
        )

    def test_duplicate_required_context_is_rejected(self) -> None:
        value = contract()
        value["required_checks"].append(copy.deepcopy(value["required_checks"][0]))  # type: ignore[union-attr,index]
        self.write_contract(value)
        with self.assertRaisesRegex(AUDIT.ContractError, "unique"):
            AUDIT.load_contract(self.config)

    def test_wrong_snapshot_field_type_is_rejected(self) -> None:
        value = contract()
        value["remote_branch_protection_snapshot"]["strict"] = "true"  # type: ignore[index]
        self.write_contract(value)
        with self.assertRaisesRegex(AUDIT.ContractError, "must be boolean"):
            AUDIT.load_contract(self.config)

    def test_snapshot_status_is_closed_and_consistent_with_content(self) -> None:
        value = contract()
        value["remote_branch_protection_snapshot"]["status"] = "stale"  # type: ignore[index]
        self.write_contract(value)
        with self.assertRaisesRegex(AUDIT.ContractError, "snapshot status"):
            AUDIT.load_contract(self.config)

        for status, contexts in (
            ("aligned", ["python-compatibility (3.11)"]),
            ("known_mismatch", [item["context"] for item in contract()["required_checks"]]),  # type: ignore[index]
        ):
            with self.subTest(status=status):
                changed = contract()
                snapshot = changed["remote_branch_protection_snapshot"]  # type: ignore[assignment]
                snapshot["status"] = status  # type: ignore[index]
                snapshot["required_contexts"] = contexts  # type: ignore[index]
                report = AUDIT.audit(self.root, changed)
                self.assertEqual(report["status"], "fail")
                self.assertTrue(any("labelled" in item for item in report["errors"]))

    def test_aligned_snapshot_requires_contract_order(self) -> None:
        value = contract()
        snapshot = value["remote_branch_protection_snapshot"]  # type: ignore[assignment]
        snapshot["required_contexts"] = list(reversed(snapshot["required_contexts"]))  # type: ignore[index]
        report = AUDIT.audit(self.root, value)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("context order" in item for item in report["errors"]))

    def test_boolean_run_id_and_nonstandard_json_number_are_rejected(self) -> None:
        value = contract()
        value["source_evidence"]["successful_run_id"] = True  # type: ignore[index]
        self.write_contract(value)
        with self.assertRaisesRegex(AUDIT.ContractError, "successful_run_id"):
            AUDIT.load_contract(self.config)
        self.config.write_text('{"value": NaN}', encoding="utf-8")
        with self.assertRaisesRegex(AUDIT.ContractError, "non-standard JSON"):
            AUDIT.load_contract(self.config)

    def test_boolean_contract_version_is_rejected(self) -> None:
        value = contract()
        value["version"] = True
        self.write_contract(value)
        with self.assertRaisesRegex(AUDIT.ContractError, "schema/version"):
            AUDIT.load_contract(self.config)

    def test_workflow_job_or_context_mismatch_fails(self) -> None:
        value = contract()
        value["required_checks"][0]["job_id"] = "wrong-job"  # type: ignore[index]
        self.write_contract(value)
        report = AUDIT.audit(self.root, AUDIT.load_contract(self.config))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("mapping" in item for item in report["errors"]))

    def test_missing_config_is_machine_readable_error(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--repo", str(self.root), "--config", str(self.root / "missing.json"), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")

    def test_unsupported_multiline_matrix_fails_closed(self) -> None:
        self.workflow.write_text(
            WORKFLOW.replace(
                '        python-version: ["3.11", "3.12", "3.13"]',
                "        python-version:\n          - \"3.11\"\n          - \"3.12\"\n          - \"3.13\"",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AUDIT.ContractError, "inline string-array"):
            AUDIT.parse_workflow(self.workflow)

    def test_duplicate_top_level_jobs_mapping_fails_closed(self) -> None:
        self.workflow.write_text(
            WORKFLOW + "\njobs:\n  replacement:\n    name: replacement\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AUDIT.ContractError, "exactly one top-level jobs"):
            AUDIT.parse_workflow(self.workflow)

    def test_find_root_does_not_fall_back_for_an_unrelated_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(AUDIT.ContractError, "not inside this source archive"):
                AUDIT.find_root(Path(outside))

    def test_find_root_retains_source_archive_fallback_inside_script_root(self) -> None:
        failed = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="")
        with mock.patch.object(AUDIT.subprocess, "run", return_value=failed):
            self.assertEqual(AUDIT.find_root(ROOT / "docs"), ROOT.resolve())

    def test_json_cli_reports_static_limits_not_remote_success(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--repo", str(self.root), "--config", str(self.config), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], AUDIT.RESULT_SCHEMA)
        self.assertFalse(payload["remote_branch_protection_verified"])
        self.assertFalse(payload["actual_ci_success_verified"])


if __name__ == "__main__":
    unittest.main()
