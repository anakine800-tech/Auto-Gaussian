#!/usr/bin/env python3
"""Offline differential tests for the private legacy raw-effect owner."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
SOURCE = SCRIPTS / "legacy_rtwin_pbs.py"
MECHANICAL_FIXTURE = (
    ROOT
    / "tests/fixtures/rtwin_pbs/legacy_effect_owner_mechanical_extraction.json"
)
BASE_COMMIT = "fc7b59dc6c280db6cdba435ae7e11f27cf30dd19"
PLACEHOLDER_RUNTIME_CONFIG = (
    Path("/private/tmp")
    / "auto-g16-pr4j-placeholder-runtime-config-does-not-exist.json"
)
NOW = "2026-01-01T00:05:00Z"
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(PLACEHOLDER_RUNTIME_CONFIG)
sys.path.insert(0, str(SCRIPTS))

import legacy_rtwin_pbs as legacy  # noqa: E402


def _base_source() -> bytes:
    return subprocess.run(
        [
            "git",
            "show",
            f"{BASE_COMMIT}:skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py",
        ],
        check=True,
        capture_output=True,
    ).stdout


def _load_source(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _identity(digest: str) -> dict[str, str]:
    return {
        "structure_sha256": "1" * 64,
        "chemical_hypothesis_sha256": "2" * 64,
        "method_protocol_sha256": "3" * 64,
        "calculation_objective_sha256": "4" * 64,
        "relevant_input_sha256": digest,
    }


def _make_live_fixture(
    module: types.ModuleType,
    root: Path,
) -> tuple[object, dict[str, object], dict[str, object]]:
    batch = module.execution_batch
    resource = module.resource_efficiency
    source = root / "source.gjf"
    source.write_text(
        "%chk=source.chk\n"
        "%mem=12GB\n"
        "%nprocshared=8\n"
        "#p hf/sto-3g\n\n"
        "placeholder effect-owner differential\n\n"
        "0 1\n"
        "H 0 0 0\n\n",
        encoding="utf-8",
    )
    digest = module.sha256(source)
    review = batch.finalize_review(
        json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/execution_batch_review.template.json"
            ).read_text(encoding="utf-8")
        )
    )
    review_path = root / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    ledger_path = root / "ledger.json"
    batch.initialize(
        review_path,
        ledger_path,
        timestamp="2026-01-01T00:00:00Z",
    )
    task = batch.admit_task(
        ledger_path,
        _identity(digest),
        estimated_core_hours=4,
        reason="placeholder exact differential",
        reviewer="placeholder",
        reviewed_at="2026-01-01T00:01:00Z",
    )
    batch.migrate_to_submission_ledger(
        ledger_path,
        migrated_at="2026-01-01T00:02:00Z",
        migration_source="placeholder differential",
    )
    resource.migrate_v2_to_v3(
        ledger_path,
        migrated_at="2026-01-01T00:03:00Z",
        migration_source="placeholder differential",
    )
    policy = resource.finalize_policy(
        {
            "schema": resource.POLICY_SCHEMA,
            "policy_id": "placeholder-policy",
            "reviewed_at": "2026-01-01T00:00:00Z",
            "reviewer": "placeholder",
            "limits": {
                "max_estimated_core_hours": 100,
                "max_remaining_core_hours": 100,
                "max_concurrent_unresolved_attempts": 3,
                "max_concurrent_active_attempts": 3,
                "max_total_cores": 64,
                "max_total_memory_gb": 256,
                "max_job_cores": 44,
                "max_job_memory_gb": 120,
                "max_job_walltime_seconds": 172800,
            },
            "governance": {
                "unknown_scheduler_or_ledger_state_fails_closed": True,
                "resources_must_be_exact_reviewed_bindings": True,
                "walltime_must_be_explicitly_reviewed": True,
                "automatic_resource_change": False,
                "automatic_retry": False,
                "monitoring_changes_scientific_conclusion": False,
            },
            "payload_sha256": "",
        }
    )
    scheduler = resource.finalize_scheduler_snapshot(
        {
            "schema": resource.SCHEDULER_SNAPSHOT_SCHEMA,
            "snapshot_id": "placeholder-snapshot",
            "collected_at": "2026-01-01T00:04:00Z",
            "source": "placeholder recording runner",
            "scope": {
                "kind": "complete_user_active_jobs",
                "owner": "placeholder",
                "completeness": "complete",
                "batch_evidence_sha256": "e" * 64,
            },
            "transport": {"classification": "success", "status": "known"},
            "freshness": {
                "classification": "fresh",
                "age_seconds": 0,
                "max_age_seconds": 3600,
            },
            "attempts": [],
            "payload_sha256": "",
        }
    )
    scheduler_path = root / "scheduler.json"
    scheduler_path.write_text(
        json.dumps(scheduler, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scheduler_document, scheduler_sha, scheduler_size = resource.load_artifact(
        scheduler_path
    )
    ledger = resource.validate_ledger(resource.load(ledger_path))
    attempt_id = batch.attempt_id_for(
        ledger["batch"]["batch_id"],
        "placeholder-submit-key",
    )
    gate = resource.evaluate_gate(
        ledger,
        policy,
        scheduler_document,
        gate_id="placeholder-gate",
        evaluated_at=NOW,
        scientific_task_id=task["scientific_task_id"],
        attempt_id=attempt_id,
        project="effectjob",
        input_sha256=digest,
        resource_tier="simple",
        cores=8,
        memory_gb=12,
        walltime_seconds=3600,
        estimated_core_hours=4,
        scheduler_artifact_sha256=scheduler_sha,
        scheduler_artifact_size=scheduler_size,
    )
    policy_path = root / "policy.json"
    gate_path = root / "gate.json"
    policy_path.write_text(
        json.dumps(policy, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gate_path.write_text(
        json.dumps(gate, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    input_approval_path = root / "input-approval.json"
    live_approval_path = root / "live-approval.json"
    input_approval_path.write_text("{}\n", encoding="utf-8")
    live_approval_path.write_text("{}\n", encoding="utf-8")
    ssh_config = root / "placeholder-ssh-config"
    ssh_config.write_text("Host placeholder\n", encoding="utf-8")
    args = module.build_parser().parse_args(
        [
            "submit",
            str(source),
            "--project",
            "effectjob",
            "--local-dir",
            str(root / "bundle"),
            "--work-kind",
            "ordinary",
            "--input-approval-record",
            str(input_approval_path),
            "--approval-record",
            str(live_approval_path),
            "--execution-batch-ledger",
            str(ledger_path),
            "--scientific-task-id",
            task["scientific_task_id"],
            "--idempotency-key",
            "placeholder-submit-key",
            "--estimated-core-hours",
            "4",
            "--estimated-core-hours-evidence-source",
            "placeholder",
            "--estimated-core-hours-evidence-sha256",
            "f" * 64,
            "--resource-policy",
            str(policy_path),
            "--resource-gate",
            str(gate_path),
            "--scheduler-resource-snapshot",
            str(scheduler_path),
            "--resource-tier",
            "simple",
            "--resource-cores",
            "8",
            "--resource-memory-gb",
            "12",
            "--walltime-seconds",
            "3600",
            "--mac-ssh-config",
            str(ssh_config),
            "--confirmed",
        ]
    )
    input_approval: dict[str, object] = {
        "status": "validated_exact_input_approval",
        "schema": module.INPUT_APPROVAL_SCHEMA,
        "sha256": "a" * 64,
        "payload_sha256": "b" * 64,
        "input_sha256": digest,
        "work_kind": "ordinary",
        "protocol_options_schema": "gaussian-protocol-options/1",
        "protocol_selection_schema": "gaussian-protocol-selection/1",
        "input_review_schema": "gaussian-input-draft-review/2",
        "no_submission_authorization": True,
    }
    live_approval: dict[str, object] = {
        "schema": module.LIVE_APPROVAL_V9_SCHEMA,
        "approval_id": "placeholder-approval",
        "approver_identity": "placeholder",
    }
    return args, input_approval, live_approval


def _artifact_bytes(root: Path) -> dict[str, bytes | None]:
    paths = {
        "state": root / "bundle/job.json",
        "events": root / "bundle/job.events.jsonl",
        "checksums": root / "bundle/checksums.sha256",
        "intent": root / "bundle/submission-intent.json",
        "consumption": root / "bundle/live-approval-consumption.json",
        "receipt": root / "bundle/submission-receipt.json",
        "ledger": root / "ledger.json",
    }
    return {
        name: path.read_bytes() if path.is_file() else None
        for name, path in paths.items()
    }


def _run_case(
    module: types.ModuleType,
    root: Path,
    *,
    target_step: int | None,
    mode: str,
) -> dict[str, object]:
    args, input_approval, live_approval = _make_live_fixture(module, root)
    calls: list[dict[str, object]] = []

    def deterministic_mkdtemp(*, prefix: str, dir: str | os.PathLike[str]) -> str:
        path = Path(dir) / f"{prefix}placeholder"
        path.mkdir()
        return str(path)

    def recording_runner(
        command: list[str],
        *,
        input_bytes: bytes | None = None,
        check: bool = True,
        timeout_seconds: int = module.DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess:
        index = len(calls)
        calls.append(
            {
                "argv": list(command),
                "input_bytes": input_bytes,
                "timeout_seconds": timeout_seconds,
                "check": check,
            }
        )
        if target_step == index:
            if mode == "raise":
                raise RuntimeError(f"synthetic effect exception {index}")
            if mode == "nonzero":
                result = subprocess.CompletedProcess(
                    command,
                    71,
                    "synthetic stdout",
                    "synthetic stderr",
                )
                if check:
                    module.fail("command failed (71): synthetic stderr")
                return result
            if mode == "unknown":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    "",
                    "synthetic unknown",
                )
            if mode == "timeout":
                result = subprocess.CompletedProcess(
                    command,
                    124,
                    "partial",
                    "\nAUTO_G16_COMMAND_TIMEOUT",
                )
                if check:
                    module.fail(
                        "command failed (124): AUTO_G16_COMMAND_TIMEOUT"
                    )
                return result
        if index == 2:
            hashes = []
            copied_paths = calls[1]["argv"][3:-1]
            for raw_path in copied_paths:
                path = Path(raw_path)
                hashes.append(f"{path.name} {module.sha256(path)}")
            return subprocess.CompletedProcess(
                command,
                0,
                "\n".join(hashes) + "\n",
                "",
            )
        if index == 5:
            return subprocess.CompletedProcess(command, 0, "123.master\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with mock.patch.object(module, "utc_now", return_value=NOW), mock.patch.object(
            module.tempfile,
            "mkdtemp",
            side_effect=deterministic_mkdtemp,
        ), mock.patch.object(
            module,
            "validate_input_approval",
            return_value=input_approval,
        ), mock.patch.object(
            module,
            "validate_live_approval_binding",
            return_value=(live_approval, "d" * 64),
        ), mock.patch.object(
            module,
            "run",
            side_effect=recording_runner,
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            module._legacy_transaction_once(
                args,
                _transaction_token=module._BACKEND_TRANSACTION_TOKEN,
            )
    except BaseException as exc:
        exception: dict[str, object] | None = {
            "type": type(exc).__name__,
            "args": exc.args,
            "code": exc.code if isinstance(exc, SystemExit) else None,
        }
    else:
        exception = None
    return {
        "exception": exception,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "calls": calls,
        "artifacts": _artifact_bytes(root),
    }


def _call_name(node: ast.Call) -> str:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


class LegacyEffectOwnerTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-pr4j-effect-owner-"
        )
        cls.root = Path(cls.temporary.name).resolve()
        cls.base_path = cls.root / "legacy-effect-base.py"
        cls.base_path.write_bytes(_base_source())
        cls.base = _load_source("auto_g16_pr4j_effect_base", cls.base_path)
        cls.candidate = legacy

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_only_raw_effect_owner_calls_run_and_outer_state_calls_stay_ordered(
        self,
    ) -> None:
        base_tree = ast.parse(_base_source())
        candidate_tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        base_owner = _function(base_tree, "_execute_legacy_transaction_once")
        candidate_owner = _function(
            candidate_tree,
            "_execute_legacy_transaction_once",
        )
        self.assertEqual(
            [_call_name(node) for node in ast.walk(candidate_owner) if isinstance(node, ast.Call) and _call_name(node) == "run"],
            [],
        )
        raw_owner = next(
            node
            for node in candidate_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "_LegacyRawEffectOwner"
        )
        self.assertEqual(
            [
                _call_name(node)
                for node in ast.walk(raw_owner)
                if isinstance(node, ast.Call) and _call_name(node) == "run"
            ],
            ["run"],
        )
        excluded = {
            "run",
            "ssh_base",
            "nested_ssh",
            "powershell_encoded",
            "remote_empty_directory_guard",
            "remote_existing_directory_guard",
            "Path",
            "str",
            "map",
            "windows_dir.replace",
            "join",
            "submit_script.encode",
            "expanduser",
            "encode",
            "_legacy_effect_plan_from_transaction",
            "_legacy_raw_effect_owner_from_plan",
            "_consume_legacy_effect_observation",
            "effect_owner.claim_windows_directory_once",
            "effect_owner.copy_mac_to_windows_once",
            "effect_owner.hash_windows_files_once",
            "effect_owner.claim_server_directory_once",
            "effect_owner.copy_windows_to_server_once",
            "effect_owner.submit_qsub_once",
        }

        def state_calls(function: ast.FunctionDef) -> list[str]:
            return [
                _call_name(node)
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and _call_name(node) not in excluded
            ]

        self.assertEqual(state_calls(candidate_owner), state_calls(base_owner))
        self.assertEqual(
            [
                ast.unparse(node.type) if node.type is not None else None
                for node in ast.walk(candidate_owner)
                if isinstance(node, ast.ExceptHandler)
            ],
            [
                ast.unparse(node.type) if node.type is not None else None
                for node in ast.walk(base_owner)
                if isinstance(node, ast.ExceptHandler)
            ],
        )
        calls = [
            _call_name(node)
            for node in ast.walk(candidate_tree)
            if isinstance(node, ast.Call)
        ]
        self.assertEqual(
            calls.count("_legacy_effect_plan_from_transaction"),
            1,
        )
        self.assertEqual(
            calls.count("_legacy_raw_effect_owner_from_plan"),
            1,
        )
        for method in (
            "effect_owner.claim_windows_directory_once",
            "effect_owner.copy_mac_to_windows_once",
            "effect_owner.hash_windows_files_once",
            "effect_owner.claim_server_directory_once",
            "effect_owner.copy_windows_to_server_once",
            "effect_owner.submit_qsub_once",
        ):
            self.assertEqual(calls.count(method), 1)

    def test_successor_fixture_binds_exact_base_and_candidate_source(self) -> None:
        fixture = json.loads(MECHANICAL_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["base_commit"], BASE_COMMIT)
        binding = fixture["files"][
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
        ]
        self.assertEqual(
            hashlib.sha256(_base_source()).hexdigest(),
            binding["before_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            binding["after_sha256"],
        )
        self.assertFalse(binding["legacy_semantics_changed"])
        self.assertFalse(binding["behavior_parity"]["automatic_retry"])
        self.assertFalse(binding["behavior_parity"]["live_actions"])

    def test_plan_result_failure_and_owner_reject_unissued_or_direct_use(
        self,
    ) -> None:
        for value_type in (
            legacy._LegacyEffectPlan,
            legacy._LegacyEffectResult,
            legacy._LegacyEffectFailure,
            legacy._LegacyRawEffectOwner,
        ):
            with self.subTest(value_type=value_type.__name__), self.assertRaises(
                TypeError
            ):
                value_type()
        forged_plan = object.__new__(legacy._LegacyEffectPlan)
        object.__setattr__(forged_plan, "_owner_seal", object())
        with self.assertRaises(SystemExit):
            forged_plan._assert_owner_sealed()
        with self.assertRaises(SystemExit):
            legacy._legacy_raw_effect_owner_from_plan(forged_plan)
        forged_owner = object.__new__(legacy._LegacyRawEffectOwner)
        object.__setattr__(forged_owner, "_owner_seal", object())
        with self.assertRaises(SystemExit):
            forged_owner.claim_windows_directory_once()
        for value_type in (
            legacy._LegacyEffectPlan,
            legacy._LegacyEffectResult,
            legacy._LegacyEffectFailure,
        ):
            self.assertFalse(hasattr(object.__new__(value_type), "__dict__"))
            for forbidden in (
                "from_mapping",
                "callback",
                "runner",
                "command",
                "backend",
                "runtime_override",
            ):
                self.assertFalse(hasattr(value_type, forbidden))
        self.assertEqual(
            tuple(
                inspect.signature(
                    legacy._LegacyRawEffectOwner._invoke
                ).parameters
            ),
            ("self", "step", "_effect_token"),
        )

    def test_recording_success_matches_exact_calls_and_artifact_bytes(
        self,
    ) -> None:
        case_root = self.root / "success"
        case_root.mkdir()
        base = _run_case(
            self.base,
            case_root,
            target_step=None,
            mode="success",
        )
        shutil.rmtree(case_root)
        case_root.mkdir()
        candidate = _run_case(
            self.candidate,
            case_root,
            target_step=None,
            mode="success",
        )
        self.assertEqual(candidate, base)
        self.assertIsNone(candidate["exception"])
        calls = candidate["calls"]
        self.assertEqual(len(calls), 6)
        self.assertEqual(
            [call["check"] for call in calls],
            [True, True, True, True, True, False],
        )
        self.assertTrue(candidate["artifacts"]["receipt"])

    def test_each_effect_failure_mode_matches_base_with_zero_retry(self) -> None:
        for target_step in range(6):
            for mode in ("raise", "nonzero", "unknown", "timeout"):
                with self.subTest(target_step=target_step, mode=mode):
                    case_root = self.root / f"failure-{target_step}-{mode}"
                    case_root.mkdir()
                    base = _run_case(
                        self.base,
                        case_root,
                        target_step=target_step,
                        mode=mode,
                    )
                    shutil.rmtree(case_root)
                    case_root.mkdir()
                    candidate = _run_case(
                        self.candidate,
                        case_root,
                        target_step=target_step,
                        mode=mode,
                    )
                    self.assertEqual(candidate, base)
                    self.assertLessEqual(len(candidate["calls"]), 6)
                    self.assertEqual(
                        sum(
                            1
                            for index, _call in enumerate(candidate["calls"])
                            if index == target_step
                        ),
                        1,
                    )


if __name__ == "__main__":
    unittest.main()
