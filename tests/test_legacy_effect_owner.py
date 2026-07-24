#!/usr/bin/env python3
"""Offline differential tests for the private legacy raw-effect owner."""

from __future__ import annotations

import ast
import copy
import contextlib
import gc
import hashlib
import importlib.util
import io
import inspect
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
SOURCE = SCRIPTS / "legacy_rtwin_pbs.py"
MECHANICAL_FIXTURE = (
    ROOT
    / "tests/fixtures/rtwin_pbs/legacy_effect_owner_mechanical_extraction.json"
)
CONCURRENCY_FIXTURE = (
    ROOT
    / "tests/fixtures/rtwin_pbs/legacy_effect_owner_concurrency_fix.json"
)
PLAN_SINGLE_USE_FIXTURE = (
    ROOT
    / "tests/fixtures/rtwin_pbs/legacy_effect_plan_single_use_fix.json"
)
LIFECYCLE_FIXTURE = (
    ROOT
    / "tests/fixtures/rtwin_pbs/legacy_effect_owner_lifecycle_fix.json"
)
HANDOFF_FIXTURE = (
    ROOT
    / "tests/fixtures/rtwin_pbs/protected_legacy_effect_handoff.json"
)
BASE_COMMIT = "fc7b59dc6c280db6cdba435ae7e11f27cf30dd19"
PR4J_COMMIT = "9f9190a201acc148bdcee134a71ec3f1e3e983cb"
CONCURRENCY_FIX_COMMIT = "aaa004a88131f244c19e6d39c74eb936e9eb55b6"
PLAN_SINGLE_USE_COMMIT = "477bada8c5b0342ebd8a8faab1acf3d08dc2814e"
LIFECYCLE_BASE_COMMIT = "88f03149a59f7b7648cb92718b7705c93b09691d"
PLACEHOLDER_RUNTIME_CONFIG = (
    Path("/private/tmp")
    / "auto-g16-pr4j-placeholder-runtime-config-does-not-exist.json"
)
NOW = "2026-01-01T00:05:00Z"
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(PLACEHOLDER_RUNTIME_CONFIG)
sys.path.insert(0, str(SCRIPTS))

import legacy_rtwin_pbs as legacy  # noqa: E402


def _source_at(commit: str) -> bytes:
    return subprocess.run(
        [
            "git",
            "show",
            f"{commit}:skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py",
        ],
        check=True,
        capture_output=True,
    ).stdout


def _base_source() -> bytes:
    return _source_at(BASE_COMMIT)


def _pr4j_source() -> bytes:
    return _source_at(PR4J_COMMIT)


def _concurrency_fix_source() -> bytes:
    return _source_at(CONCURRENCY_FIX_COMMIT)


def _plan_single_use_source() -> bytes:
    return _source_at(PLAN_SINGLE_USE_COMMIT)


def _lifecycle_base_source() -> bytes:
    return _source_at(LIFECYCLE_BASE_COMMIT)


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
    approval_failure_call: int | None = None,
) -> dict[str, object]:
    args, input_approval, live_approval = _make_live_fixture(module, root)
    calls: list[dict[str, object]] = []
    approval_calls = 0

    def replay_live_approval(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[dict[str, object], str]:
        nonlocal approval_calls
        approval_calls += 1
        if approval_failure_call == approval_calls:
            raise KeyboardInterrupt(
                f"synthetic approval replay BaseException {approval_calls}"
            )
        return live_approval, "d" * 64

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
            if mode == "baseexception":
                raise KeyboardInterrupt(
                    f"synthetic effect BaseException {index}"
                )
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
            side_effect=replay_live_approval,
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


def _make_raw_plan(
    module: types.ModuleType,
    root: Path,
    *,
    project: str,
) -> object:
    source = root / f"{project}.gjf"
    source.write_bytes(b"# synthetic raw effect owner concurrency fixture\n")
    ssh_config = root / "placeholder-ssh-config"
    ssh_config.write_text("Host placeholder\n", encoding="utf-8")
    digest = module.sha256(source)
    transaction_plan = object.__new__(module._LegacyTransactionPlan)
    transaction_fields = {
        "mac_ssh_config": str(ssh_config),
        "rtwin_alias": "rtwin",
        "windows_server_config": r".ssh\gaussian_server_config",
        "server_alias": "gaussian-server",
        "_owner_seal": module._BACKEND_TRANSACTION_TOKEN,
    }
    for name, value in transaction_fields.items():
        object.__setattr__(transaction_plan, name, value)
    transaction_plan._assert_owner_sealed()
    return module._legacy_effect_plan_from_transaction(
        transaction_plan,
        project=project,
        windows_dir=rf"C:\GaussianProjects\{project}",
        remote_dir=module.remote_project_dir(project),
        files=[source],
        expected_bindings={source.name: digest},
        upload_timeout_seconds=60,
        upload_hash_timeout_seconds=60,
        attempt_id=f"{project}-attempt",
        input_sha256=digest,
        _factory_token=module._LEGACY_EFFECT_OWNER_TOKEN,
    )


def _make_raw_owner(
    module: types.ModuleType,
    root: Path,
    *,
    project: str,
) -> object:
    plan = _make_raw_plan(module, root, project=project)
    return module._legacy_raw_effect_owner_from_plan(
        plan,
        _factory_token=module._LEGACY_EFFECT_OWNER_TOKEN,
    )


def _call_owner_step(
    module: types.ModuleType,
    owner: object,
    method: str,
) -> tuple[str, object]:
    try:
        return (
            "result",
            getattr(owner, method)(
                _effect_token=module._LEGACY_EFFECT_OWNER_TOKEN,
            ),
        )
    except BaseException as exc:
        return ("exception", exc)


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
        cls.pr4j_path = cls.root / "legacy-effect-pr4j.py"
        cls.pr4j_path.write_bytes(_pr4j_source())
        cls.pr4j = _load_source("auto_g16_pr4j_effect_race", cls.pr4j_path)
        cls.concurrency_fix_path = cls.root / "legacy-effect-concurrency-fix.py"
        cls.concurrency_fix_path.write_bytes(_concurrency_fix_source())
        cls.concurrency_fix = _load_source(
            "auto_g16_pr4j_effect_concurrency_fix",
            cls.concurrency_fix_path,
        )
        cls.candidate = legacy

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _fresh_candidate(self, label: str) -> types.ModuleType:
        path = self.root / f"legacy-effect-lifecycle-{label}.py"
        path.write_bytes(SOURCE.read_bytes())
        return _load_source(
            f"auto_g16_pr4m_effect_lifecycle_{label}",
            path,
        )

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

        class LifecycleWrapperNormalizer(ast.NodeTransformer):
            def visit_Assign(
                self,
                node: ast.Assign,
            ) -> ast.Assign | None:
                if (
                    isinstance(node.value, ast.Call)
                    and _call_name(node.value)
                    == "_legacy_effect_owner_lifecycle_from_owner"
                ):
                    return None
                return self.generic_visit(node)

            def visit_With(
                self,
                node: ast.With,
            ) -> ast.With | list[ast.stmt]:
                normalized = self.generic_visit(node)
                assert isinstance(normalized, ast.With)
                if (
                    len(normalized.items) == 1
                    and isinstance(normalized.items[0].context_expr, ast.Name)
                    and normalized.items[0].context_expr.id == "effect_lifecycle"
                ):
                    return normalized.body
                return normalized

        normalized_candidate = LifecycleWrapperNormalizer().visit(
            copy.deepcopy(candidate_owner)
        )
        assert isinstance(normalized_candidate, ast.FunctionDef)
        self.assertEqual(
            state_calls(normalized_candidate),
            state_calls(base_owner),
        )
        self.assertEqual(
            [
                ast.unparse(node.type) if node.type is not None else None
                for node in ast.walk(normalized_candidate)
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
        self.assertEqual(
            calls.count("_legacy_effect_owner_lifecycle_from_owner"),
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

    def test_historical_fixture_keeps_exact_pr4j_bytes_frozen(self) -> None:
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
            hashlib.sha256(_pr4j_source()).hexdigest(),
            binding["after_sha256"],
        )
        self.assertFalse(binding["legacy_semantics_changed"])
        self.assertFalse(binding["behavior_parity"]["automatic_retry"])
        self.assertFalse(binding["behavior_parity"]["live_actions"])

    def test_concurrency_successor_keeps_exact_aaa004a_bytes_frozen(self) -> None:
        fixture = json.loads(CONCURRENCY_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["base_commit"], PR4J_COMMIT)
        binding = fixture["files"][
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
        ]
        self.assertEqual(
            hashlib.sha256(_pr4j_source()).hexdigest(),
            binding["before_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(_concurrency_fix_source()).hexdigest(),
            binding["after_sha256"],
        )
        self.assertTrue(binding["concurrency_semantics_changed"])
        self.assertFalse(binding["behavior_parity"]["command_bytes_changed"])
        self.assertFalse(binding["behavior_parity"]["automatic_retry"])
        self.assertFalse(binding["behavior_parity"]["live_actions"])

    def test_plan_single_use_successor_keeps_exact_477bada_bytes_frozen(
        self,
    ) -> None:
        fixture = json.loads(PLAN_SINGLE_USE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["base_commit"], CONCURRENCY_FIX_COMMIT)
        binding = fixture["files"][
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
        ]
        self.assertEqual(
            hashlib.sha256(_concurrency_fix_source()).hexdigest(),
            binding["before_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(_plan_single_use_source()).hexdigest(),
            binding["after_sha256"],
        )
        self.assertTrue(binding["plan_factory_semantics_changed"])
        self.assertFalse(binding["behavior_parity"]["command_bytes_changed"])
        self.assertFalse(binding["behavior_parity"]["automatic_retry"])
        self.assertFalse(binding["behavior_parity"]["live_actions"])

    def test_lifecycle_successor_binds_exact_base_and_current_source(
        self,
    ) -> None:
        fixture = json.loads(LIFECYCLE_FIXTURE.read_text(encoding="utf-8"))
        handoff = json.loads(HANDOFF_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["base_commit"], LIFECYCLE_BASE_COMMIT)
        self.assertEqual(
            fixture["base_tree"],
            "a4c475b20ef72e20881e2bc488b2023394b3d807",
        )
        self.assertEqual(
            fixture["base_parent"],
            "7ea0ae19156ad3b6daeefc787ca6dda471669355",
        )
        binding = fixture["files"][
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
        ]
        self.assertEqual(
            hashlib.sha256(_lifecycle_base_source()).hexdigest(),
            binding["before_sha256"],
        )
        self.assertEqual(
            handoff["files"][
                "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
            ]["before_sha256"],
            binding["after_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            handoff["files"][
                "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
            ]["sha256"],
        )
        self.assertTrue(binding["lifecycle_semantics_changed"])
        self.assertFalse(binding["behavior_parity"]["command_bytes_changed"])
        self.assertFalse(binding["behavior_parity"]["automatic_retry"])
        self.assertFalse(binding["behavior_parity"]["live_actions"])

    def test_plan_result_failure_and_owner_reject_unissued_or_direct_use(
        self,
    ) -> None:
        for value_type in (
            legacy._LegacyEffectPlan,
            legacy._LegacyEffectPlanFactoryState,
            legacy._LegacyEffectResult,
            legacy._LegacyEffectFailure,
            legacy._LegacyEffectOwnerState,
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
            legacy._legacy_raw_effect_owner_from_plan(
                forged_plan,
                _factory_token=legacy._LEGACY_EFFECT_OWNER_TOKEN,
            )

        class PlanSubclass(legacy._LegacyEffectPlan):
            pass

        subclass_plan = object.__new__(PlanSubclass)
        object.__setattr__(
            subclass_plan,
            "_owner_seal",
            legacy._LEGACY_EFFECT_OWNER_TOKEN,
        )
        with self.assertRaises(SystemExit):
            legacy._legacy_raw_effect_owner_from_plan(
                subclass_plan,
                _factory_token=legacy._LEGACY_EFFECT_OWNER_TOKEN,
            )
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
        self.assertEqual(
            tuple(
                inspect.signature(
                    legacy._legacy_raw_effect_owner_from_plan
                ).parameters
            ),
            ("plan", "_factory_token"),
        )

    def test_pr4j_race_reproduces_two_same_step_effects_before_fix(self) -> None:
        owner = _make_raw_owner(
            self.pr4j,
            self.root,
            project="oldrace",
        )
        dispatch = self.pr4j._LegacyRawEffectOwner._assert_dispatch
        source_lines, first_line = inspect.getsourcelines(dispatch)
        target_line = first_line + next(
            index
            for index, line in enumerate(source_lines)
            if 'object.__setattr__(self, "_next_step"' in line
        )
        before_write = threading.Barrier(2)
        call_lock = threading.Lock()
        calls: list[list[str]] = []

        def trace(frame: types.FrameType, event: str, arg: object) -> object:
            if (
                event == "line"
                and frame.f_code is dispatch.__code__
                and frame.f_lineno == target_line
            ):
                before_write.wait(timeout=5)
            return trace

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            with call_lock:
                calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        previous_trace = threading.gettrace()
        threading.settrace(trace)
        try:
            with mock.patch.object(
                self.pr4j,
                "run",
                side_effect=recording_runner,
            ), ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = [
                    future.result(timeout=5)
                    for future in (
                        pool.submit(
                            _call_owner_step,
                            self.pr4j,
                            owner,
                            "claim_windows_directory_once",
                        ),
                        pool.submit(
                            _call_owner_step,
                            self.pr4j,
                            owner,
                            "claim_windows_directory_once",
                        ),
                    )
                ]
        finally:
            threading.settrace(previous_trace)
        self.assertEqual([kind for kind, _value in outcomes], ["result", "result"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(owner._next_step, 1)

    def test_frozen_aaa004a_allows_two_owners_and_two_effects_for_one_plan(
        self,
    ) -> None:
        plan = _make_raw_plan(
            self.concurrency_fix,
            self.root,
            project="oldplanreplay",
        )
        owners = [
            self.concurrency_fix._legacy_raw_effect_owner_from_plan(
                plan,
                _factory_token=self.concurrency_fix._LEGACY_EFFECT_OWNER_TOKEN,
            )
            for _index in range(2)
        ]
        calls = 0

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(
            self.concurrency_fix,
            "run",
            side_effect=recording_runner,
        ):
            outcomes = [
                _call_owner_step(
                    self.concurrency_fix,
                    owner,
                    "claim_windows_directory_once",
                )
                for owner in owners
            ]
        self.assertEqual(
            tuple(kind for kind, _value in outcomes),
            ("result", "result"),
        )
        self.assertEqual(calls, 2)
        self.assertIs(owners[0]._plan, owners[1]._plan)
        self.assertIsNot(owners[0]._effect_state, owners[1]._effect_state)

    def test_same_plan_sequential_factory_is_single_use_before_effect(
        self,
    ) -> None:
        plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="seqfactory",
        )
        owner = self.candidate._legacy_raw_effect_owner_from_plan(
            plan,
            _factory_token=self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
        )
        with self.assertRaises(SystemExit):
            self.candidate._legacy_raw_effect_owner_from_plan(
                plan,
                _factory_token=self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
            )
        self.assertIs(plan._factory_state._owner, owner)
        self.assertEqual(plan._factory_state._status, "claimed")
        self.assertEqual(owner._effect_state._next_step, 0)

    def test_same_plan_concurrent_factory_issues_exactly_one_owner(self) -> None:
        for round_index in range(24):
            with self.subTest(round_index=round_index):
                plan = _make_raw_plan(
                    self.candidate,
                    self.root,
                    project=f"factory{round_index}",
                )
                start = threading.Barrier(3)

                def create_owner() -> tuple[str, object]:
                    start.wait(timeout=5)
                    try:
                        return (
                            "owner",
                            self.candidate._legacy_raw_effect_owner_from_plan(
                                plan,
                                _factory_token=(
                                    self.candidate._LEGACY_EFFECT_OWNER_TOKEN
                                ),
                            ),
                        )
                    except BaseException as exc:
                        return ("exception", exc)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(create_owner) for _index in range(2)]
                    start.wait(timeout=5)
                    outcomes = [
                        future.result(timeout=5) for future in futures
                    ]
                self.assertEqual(
                    sorted(kind for kind, _value in outcomes),
                    ["exception", "owner"],
                )
                owner = next(
                    value for kind, value in outcomes if kind == "owner"
                )
                refusal = next(
                    value for kind, value in outcomes if kind == "exception"
                )
                self.assertIsInstance(refusal, SystemExit)
                self.assertIs(plan._factory_state._owner, owner)
                self.assertEqual(plan._factory_state._status, "claimed")
                self.assertEqual(owner._effect_state._next_step, 0)

    def test_factory_exception_is_terminal_for_the_plan(self) -> None:
        plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="factoryfailure",
        )

        class FactoryFailure(BaseException):
            pass

        failure = FactoryFailure("synthetic factory failure")
        with mock.patch.object(
            self.candidate._LegacyEffectOwnerState,
            "_assert_bound",
            side_effect=failure,
        ), self.assertRaises(FactoryFailure) as raised:
            self.candidate._legacy_raw_effect_owner_from_plan(
                plan,
                _factory_token=self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
            )
        self.assertIs(raised.exception, failure)
        self.assertEqual(plan._factory_state._status, "failed")
        self.assertIsNone(plan._factory_state._owner)
        with self.assertRaises(SystemExit):
            self.candidate._legacy_raw_effect_owner_from_plan(
                plan,
                _factory_token=self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
            )

    def test_shared_exchanged_plan_and_cross_owner_state_fail_before_effect(
        self,
    ) -> None:
        first_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="shareplanone",
        )
        second_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="shareplantwo",
        )
        object.__setattr__(second_owner, "_plan", first_owner._plan)
        calls = 0

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ):
            shared = _call_owner_step(
                self.candidate,
                second_owner,
                "claim_windows_directory_once",
            )
        self.assertEqual(shared[0], "exception")
        self.assertIsInstance(shared[1], SystemExit)
        self.assertEqual(calls, 0)

        first_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="swapplanone",
        )
        second_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="swapplantwo",
        )
        first_plan = first_owner._plan
        second_plan = second_owner._plan
        object.__setattr__(first_owner, "_plan", second_plan)
        object.__setattr__(second_owner, "_plan", first_plan)
        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ):
            exchanged = [
                _call_owner_step(
                    self.candidate,
                    owner,
                    "claim_windows_directory_once",
                )
                for owner in (first_owner, second_owner)
            ]
        self.assertEqual(
            [kind for kind, _value in exchanged],
            ["exception", "exception"],
        )
        self.assertEqual(calls, 0)

        first_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="swapstateone",
        )
        second_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="swapstatetwo",
        )
        object.__setattr__(
            second_owner,
            "_effect_state",
            first_owner._effect_state,
        )
        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ):
            cross_state = _call_owner_step(
                self.candidate,
                second_owner,
                "claim_windows_directory_once",
            )
        self.assertEqual(cross_state[0], "exception")
        self.assertIsInstance(cross_state[1], SystemExit)
        self.assertEqual(calls, 0)

        first_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="crosspstateone",
        )
        second_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="crosspstatetwo",
        )
        object.__setattr__(
            second_owner._effect_state,
            "_plan_factory_state",
            first_owner._plan._factory_state,
        )
        object.__setattr__(
            second_owner._plan._factory_state,
            "_owner",
            first_owner,
        )
        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ):
            cross_plan_state = _call_owner_step(
                self.candidate,
                second_owner,
                "claim_windows_directory_once",
            )
        self.assertEqual(cross_plan_state[0], "exception")
        self.assertIsInstance(cross_plan_state[1], SystemExit)
        self.assertEqual(calls, 0)

    def test_plan_factory_state_forgery_and_cross_plan_copy_fail_closed(
        self,
    ) -> None:
        first_plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="crossplanone",
        )
        second_plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="crossplantwo",
        )
        object.__setattr__(
            first_plan,
            "_factory_state",
            second_plan._factory_state,
        )
        with self.assertRaises(SystemExit):
            self.candidate._legacy_raw_effect_owner_from_plan(
                first_plan,
                _factory_token=self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
            )

        adversarial_plans = []
        exact_fake_plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="exactstate",
        )
        exact_fake = object.__new__(
            self.candidate._LegacyEffectPlanFactoryState
        )
        for name, value in (
            ("_lock", threading.Lock()),
            ("_plan", exact_fake_plan),
            ("_owner", None),
            ("_status", "unclaimed"),
            (
                "_factory_seal",
                self.candidate._LEGACY_EFFECT_PLAN_STATE_TOKEN,
            ),
        ):
            object.__setattr__(exact_fake, name, value)
        object.__setattr__(exact_fake_plan, "_factory_state", exact_fake)
        adversarial_plans.append(exact_fake_plan)

        class PlanStateSubclass(
            self.candidate._LegacyEffectPlanFactoryState
        ):
            pass

        subclass_plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="subclassstate",
        )
        subclass_state = object.__new__(PlanStateSubclass)
        object.__setattr__(
            subclass_plan,
            "_factory_state",
            subclass_state,
        )
        adversarial_plans.append(subclass_plan)

        fake_lock_plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="fakelock",
        )
        object.__setattr__(
            fake_lock_plan._factory_state,
            "_lock",
            threading.Lock(),
        )
        adversarial_plans.append(fake_lock_plan)

        fake_seal_plan = _make_raw_plan(
            self.candidate,
            self.root,
            project="fakeseal",
        )
        object.__setattr__(
            fake_seal_plan._factory_state,
            "_factory_seal",
            object(),
        )
        adversarial_plans.append(fake_seal_plan)

        for plan in adversarial_plans:
            with self.subTest(project=plan.project), self.assertRaises(
                SystemExit
            ):
                self.candidate._legacy_raw_effect_owner_from_plan(
                    plan,
                    _factory_token=self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
                )

    def test_same_step_concurrency_reaches_runner_at_most_once(self) -> None:
        owner = _make_raw_owner(self.candidate, self.root, project="onerun")
        start = threading.Barrier(3)
        runner_entered = threading.Event()
        release_runner = threading.Event()
        call_lock = threading.Lock()
        calls: list[list[str]] = []

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            with call_lock:
                calls.append(list(command))
            runner_entered.set()
            self.assertTrue(release_runner.wait(timeout=5))
            return subprocess.CompletedProcess(command, 0, "", "")

        def invoke() -> tuple[str, object]:
            start.wait(timeout=5)
            return _call_owner_step(
                self.candidate,
                owner,
                "claim_windows_directory_once",
            )

        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke), pool.submit(invoke)]
            start.wait(timeout=5)
            self.assertTrue(runner_entered.wait(timeout=5))
            self.assertEqual(len(calls), 1)
            release_runner.set()
            outcomes = [future.result(timeout=5) for future in futures]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            sorted(kind for kind, _value in outcomes),
            ["exception", "result"],
        )
        refusal = next(value for kind, value in outcomes if kind == "exception")
        self.assertIsInstance(refusal, SystemExit)

    def test_consecutive_steps_cannot_reorder_or_overlap(self) -> None:
        owner = _make_raw_owner(self.candidate, self.root, project="ordered")
        first_entered = threading.Event()
        release_first = threading.Event()
        second_attempted = threading.Event()
        second_entered = threading.Event()
        call_lock = threading.Lock()
        calls = 0
        active = 0
        max_active = 0

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls, active, max_active
            with call_lock:
                index = calls
                calls += 1
                active += 1
                max_active = max(max_active, active)
            if index == 0:
                first_entered.set()
                self.assertTrue(release_first.wait(timeout=5))
            else:
                second_entered.set()
            with call_lock:
                active -= 1
            return subprocess.CompletedProcess(command, 0, "", "")

        def invoke_second() -> tuple[str, object]:
            second_attempted.set()
            return _call_owner_step(
                self.candidate,
                owner,
                "copy_mac_to_windows_once",
            )

        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                _call_owner_step,
                self.candidate,
                owner,
                "claim_windows_directory_once",
            )
            self.assertTrue(first_entered.wait(timeout=5))
            second = pool.submit(invoke_second)
            self.assertTrue(second_attempted.wait(timeout=5))
            self.assertFalse(second_entered.is_set())
            self.assertEqual(calls, 1)
            release_first.set()
            outcomes = [
                first.result(timeout=5),
                second.result(timeout=5),
            ]
        self.assertEqual([kind for kind, _value in outcomes], ["result", "result"])
        self.assertTrue(second_entered.is_set())
        self.assertEqual(calls, 2)
        self.assertEqual(max_active, 1)

    def test_baseexception_is_terminal_and_lock_is_released(self) -> None:
        owner = _make_raw_owner(self.candidate, self.root, project="terminal")
        calls = 0

        class FatalEffect(BaseException):
            pass

        failure = FatalEffect("synthetic fatal effect")

        def fatal_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            calls += 1
            raise failure

        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=fatal_runner,
        ):
            kind, observation = _call_owner_step(
                self.candidate,
                owner,
                "claim_windows_directory_once",
            )
            self.assertEqual(kind, "result")
            self.assertIsInstance(observation, self.candidate._LegacyEffectFailure)
            self.assertIs(observation.exception, failure)
            retry = _call_owner_step(
                self.candidate,
                owner,
                "claim_windows_directory_once",
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                next_step = pool.submit(
                    _call_owner_step,
                    self.candidate,
                    owner,
                    "copy_mac_to_windows_once",
                ).result(timeout=5)
        self.assertEqual(calls, 1)
        self.assertEqual(retry[0], "exception")
        self.assertEqual(next_step[0], "exception")
        self.assertIsInstance(retry[1], SystemExit)
        self.assertIsInstance(next_step[1], SystemExit)
        self.assertTrue(owner._effect_state._terminal_failed)

    def test_different_owners_have_independent_effect_locks(self) -> None:
        first_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="ownerone",
        )
        second_owner = _make_raw_owner(
            self.candidate,
            self.root,
            project="ownertwo",
        )
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        call_lock = threading.Lock()
        calls = 0

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            with call_lock:
                index = calls
                calls += 1
            if index == 0:
                first_entered.set()
                self.assertTrue(release_first.wait(timeout=5))
            else:
                second_entered.set()
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                _call_owner_step,
                self.candidate,
                first_owner,
                "claim_windows_directory_once",
            )
            self.assertTrue(first_entered.wait(timeout=5))
            second = pool.submit(
                _call_owner_step,
                self.candidate,
                second_owner,
                "claim_windows_directory_once",
            )
            self.assertTrue(second_entered.wait(timeout=5))
            self.assertEqual(second.result(timeout=5)[0], "result")
            release_first.set()
            self.assertEqual(first.result(timeout=5)[0], "result")
        self.assertEqual(calls, 2)
        self.assertIsNot(
            first_owner._effect_state._lock,
            second_owner._effect_state._lock,
        )

    def test_state_forgery_copy_and_pickle_fail_before_effect(self) -> None:
        owner = _make_raw_owner(self.candidate, self.root, project="sealed")
        with self.assertRaises(TypeError):
            self.candidate._LegacyEffectOwnerState()
        with self.assertRaises(TypeError):
            self.candidate._LegacyEffectPlanFactoryState()
        for name, value in (
            ("owner", owner),
            ("plan", owner._plan),
            ("plan_state", owner._plan._factory_state),
            ("effect_state", owner._effect_state),
        ):
            for operation_name, operation in (
                ("copy", lambda value=value: copy.copy(value)),
                ("deepcopy", lambda value=value: copy.deepcopy(value)),
                ("pickle", lambda value=value: pickle.dumps(value)),
            ):
                with self.subTest(
                    value=name,
                    operation=operation_name,
                ), self.assertRaises(TypeError):
                    operation()

        calls = 0

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(command, 0, "", "")

        forged_owners = []
        missing_state = object.__new__(self.candidate._LegacyRawEffectOwner)
        object.__setattr__(missing_state, "_plan", owner._plan)
        object.__setattr__(
            missing_state,
            "_owner_seal",
            self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
        )
        forged_owners.append(missing_state)

        copied_state = object.__new__(self.candidate._LegacyRawEffectOwner)
        object.__setattr__(copied_state, "_plan", owner._plan)
        object.__setattr__(
            copied_state,
            "_owner_seal",
            self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
        )
        object.__setattr__(copied_state, "_effect_state", owner._effect_state)
        forged_owners.append(copied_state)

        for seal, lock in (
            (object(), threading.Lock()),
            (self.candidate._LEGACY_EFFECT_STATE_TOKEN, object()),
        ):
            forged = object.__new__(self.candidate._LegacyRawEffectOwner)
            object.__setattr__(forged, "_plan", owner._plan)
            object.__setattr__(
                forged,
                "_owner_seal",
                self.candidate._LEGACY_EFFECT_OWNER_TOKEN,
            )
            state = object.__new__(self.candidate._LegacyEffectOwnerState)
            object.__setattr__(state, "_lock", lock)
            object.__setattr__(state, "_next_step", 0)
            object.__setattr__(state, "_owner", forged)
            object.__setattr__(state, "_terminal_failed", False)
            object.__setattr__(state, "_factory_seal", seal)
            object.__setattr__(forged, "_effect_state", state)
            forged_owners.append(forged)

        replaced_lock = _make_raw_owner(
            self.candidate,
            self.root,
            project="replacedlock",
        )
        object.__setattr__(
            replaced_lock._effect_state,
            "_lock",
            threading.Lock(),
        )
        forged_owners.append(replaced_lock)

        with mock.patch.object(
            self.candidate,
            "run",
            side_effect=recording_runner,
        ):
            outcomes = [
                _call_owner_step(
                    self.candidate,
                    forged,
                    "claim_windows_directory_once",
                )
                for forged in forged_owners
            ]
        self.assertEqual(calls, 0)
        self.assertEqual(
            [kind for kind, _value in outcomes],
            ["exception"] * len(forged_owners),
        )
        self.assertTrue(
            all(isinstance(value, SystemExit) for _kind, value in outcomes)
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    self.candidate._legacy_raw_effect_owner_from_plan
                ).parameters
            ),
            ("plan", "_factory_token"),
        )

    def test_lifecycle_retires_exact_binding_and_replay_fails_before_effect(
        self,
    ) -> None:
        module = self._fresh_candidate("exact")
        owner = _make_raw_owner(module, self.root, project="lifecycleexact")
        plan = owner._plan
        state = owner._effect_state
        baseline = (
            len(module._LEGACY_EFFECT_PLAN_BINDINGS),
            len(module._LEGACY_EFFECT_OWNER_BINDINGS),
        )
        lifecycle = module._legacy_effect_owner_lifecycle_from_owner(
            owner,
            _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
        )
        for operation in (
            lambda: copy.copy(lifecycle),
            lambda: copy.deepcopy(lifecycle),
            lambda: pickle.dumps(lifecycle),
        ):
            with self.assertRaises(TypeError):
                operation()
        calls = 0

        def recording_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(command, 0, "", "")

        methods = (
            "claim_windows_directory_once",
            "copy_mac_to_windows_once",
            "hash_windows_files_once",
            "claim_server_directory_once",
            "copy_windows_to_server_once",
            "submit_qsub_once",
        )
        with mock.patch.object(
            module,
            "run",
            side_effect=recording_runner,
        ), lifecycle as active_owner:
            self.assertIs(active_owner, owner)
            for method in methods:
                kind, _value = _call_owner_step(module, owner, method)
                self.assertEqual(kind, "result")
        self.assertEqual(calls, 6)
        self.assertEqual(lifecycle._status, "retired")
        self.assertTrue(state._retirement_requested)
        self.assertTrue(state._retired)
        self.assertIsNone(state._owner)
        self.assertIsNone(state._plan)
        self.assertIsNone(state._plan_factory_state)
        self.assertIsNone(state._lifecycle)
        self.assertEqual(plan._factory_state._status, "retired")
        self.assertIsNone(plan._factory_state._owner)
        self.assertIsNone(plan._factory_state._plan)
        self.assertEqual(
            (
                len(module._LEGACY_EFFECT_PLAN_BINDINGS),
                len(module._LEGACY_EFFECT_OWNER_BINDINGS),
            ),
            (baseline[0] - 1, baseline[1] - 1),
        )
        module._retire_legacy_effect_owner_lifecycle(
            lifecycle,
            _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
        )
        with mock.patch.object(
            module,
            "run",
            side_effect=recording_runner,
        ):
            replay = _call_owner_step(
                module,
                owner,
                "claim_windows_directory_once",
            )
            with self.assertRaises(SystemExit):
                module._legacy_raw_effect_owner_from_plan(
                    plan,
                    _factory_token=module._LEGACY_EFFECT_OWNER_TOKEN,
                )
        self.assertEqual(replay[0], "exception")
        self.assertIsInstance(replay[1], SystemExit)
        self.assertEqual(calls, 6)

    def test_transaction_terminal_paths_retire_without_gc_or_tombstones(
        self,
    ) -> None:
        module = self._fresh_candidate("terminalpaths")
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            cases = [(None, "success")]
            cases.extend((step, "raise") for step in range(6))
            cases.extend((step, "baseexception") for step in range(6))
            for index, (target_step, mode) in enumerate(cases):
                with self.subTest(target_step=target_step, mode=mode):
                    case_root = self.root / f"lifecycle-terminal-{index}"
                    case_root.mkdir()
                    outcome = _run_case(
                        module,
                        case_root,
                        target_step=target_step,
                        mode=mode,
                    )
                    self.assertLessEqual(len(outcome["calls"]), 6)
                    self.assertEqual(
                        len(module._LEGACY_EFFECT_PLAN_BINDINGS),
                        0,
                    )
                    self.assertEqual(
                        len(module._LEGACY_EFFECT_OWNER_BINDINGS),
                        0,
                    )
        finally:
            if was_enabled:
                gc.enable()

    def test_post_transfer_local_failures_always_retire_before_propagation(
        self,
    ) -> None:
        class FatalLocalReplay(BaseException):
            pass

        resource_module = self._fresh_candidate("resourcefailure")
        resource_failure = FatalLocalReplay("synthetic resource replay failure")
        resource_root = self.root / "lifecycle-resource-failure"
        resource_root.mkdir()
        with mock.patch.object(
            resource_module,
            "replay_resource_artifacts_before_qsub",
            side_effect=resource_failure,
        ):
            resource_outcome = _run_case(
                resource_module,
                resource_root,
                target_step=None,
                mode="success",
            )
        self.assertEqual(resource_outcome["exception"]["type"], "FatalLocalReplay")
        self.assertEqual(len(resource_outcome["calls"]), 5)
        self.assertEqual(len(resource_module._LEGACY_EFFECT_PLAN_BINDINGS), 0)
        self.assertEqual(len(resource_module._LEGACY_EFFECT_OWNER_BINDINGS), 0)

        approval_module = self._fresh_candidate("approvalfailure")
        approval_root = self.root / "lifecycle-approval-failure"
        approval_root.mkdir()
        approval_outcome = _run_case(
            approval_module,
            approval_root,
            target_step=None,
            mode="success",
            approval_failure_call=3,
        )
        self.assertEqual(approval_outcome["exception"]["type"], "KeyboardInterrupt")
        self.assertEqual(len(approval_outcome["calls"]), 5)
        self.assertEqual(len(approval_module._LEGACY_EFFECT_PLAN_BINDINGS), 0)
        self.assertEqual(len(approval_module._LEGACY_EFFECT_OWNER_BINDINGS), 0)

    def test_inflight_retirement_allows_at_most_one_runner_call(self) -> None:
        module = self._fresh_candidate("inflight")
        owner = _make_raw_owner(module, self.root, project="inflightretire")
        lifecycle = module._legacy_effect_owner_lifecycle_from_owner(
            owner,
            _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
        )
        state = owner._effect_state
        runner_entered = threading.Event()
        release_runner = threading.Event()
        retire_started = threading.Event()
        second_started = threading.Event()
        calls = 0
        call_lock = threading.Lock()

        def blocking_runner(
            command: list[str],
            *,
            input_bytes: bytes | None = None,
            check: bool = True,
            timeout_seconds: int = 60,
        ) -> subprocess.CompletedProcess:
            nonlocal calls
            with call_lock:
                calls += 1
            runner_entered.set()
            self.assertTrue(release_runner.wait(timeout=5))
            return subprocess.CompletedProcess(command, 0, "", "")

        def retire() -> None:
            retire_started.set()
            module._retire_legacy_effect_owner_lifecycle(
                lifecycle,
                _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
            )

        def invoke_second() -> tuple[str, object]:
            second_started.set()
            return _call_owner_step(
                module,
                owner,
                "copy_mac_to_windows_once",
            )

        with mock.patch.object(
            module,
            "run",
            side_effect=blocking_runner,
        ), lifecycle, ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(
                _call_owner_step,
                module,
                owner,
                "claim_windows_directory_once",
            )
            self.assertTrue(runner_entered.wait(timeout=5))
            owner._plan._factory_state._lock.acquire()
            try:
                retiring = pool.submit(retire)
                self.assertTrue(retire_started.wait(timeout=5))
                second = pool.submit(invoke_second)
                self.assertTrue(second_started.wait(timeout=5))
            finally:
                owner._plan._factory_state._lock.release()
            for _index in range(1000):
                if state._retirement_requested:
                    break
                threading.Event().wait(0.001)
            self.assertTrue(state._retirement_requested)
            release_runner.set()
            first_outcome = first.result(timeout=5)
            second_outcome = second.result(timeout=5)
            retiring.result(timeout=5)
        self.assertEqual(first_outcome[0], "result")
        self.assertEqual(second_outcome[0], "exception")
        self.assertIsInstance(second_outcome[1], SystemExit)
        self.assertEqual(calls, 1)
        self.assertEqual(len(module._LEGACY_EFFECT_PLAN_BINDINGS), 0)
        self.assertEqual(len(module._LEGACY_EFFECT_OWNER_BINDINGS), 0)

    def test_forged_swapped_and_replaced_lifecycle_cannot_retire_binding(
        self,
    ) -> None:
        module = self._fresh_candidate("forgery")
        first_owner = _make_raw_owner(
            module,
            self.root,
            project="lifeforgeone",
        )
        second_owner = _make_raw_owner(
            module,
            self.root,
            project="lifeforgetwo",
        )
        first = module._legacy_effect_owner_lifecycle_from_owner(
            first_owner,
            _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
        )
        second = module._legacy_effect_owner_lifecycle_from_owner(
            second_owner,
            _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
        )

        forged = object.__new__(module._LegacyEffectOwnerLifecycle)
        for name in module._LegacyEffectOwnerLifecycle.__slots__:
            object.__setattr__(forged, name, getattr(first, name))
        with self.assertRaises(SystemExit):
            module._retire_legacy_effect_owner_lifecycle(
                forged,
                _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
            )
        self.assertIn(first_owner, module._LEGACY_EFFECT_OWNER_BINDINGS)
        self.assertIn(first_owner._plan, module._LEGACY_EFFECT_PLAN_BINDINGS)

        object.__setattr__(first, "_owner", second_owner)
        with self.assertRaises(SystemExit):
            module._retire_legacy_effect_owner_lifecycle(
                first,
                _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
            )
        object.__setattr__(first, "_owner", first_owner)
        self.assertIn(first_owner, module._LEGACY_EFFECT_OWNER_BINDINGS)
        self.assertIn(second_owner, module._LEGACY_EFFECT_OWNER_BINDINGS)

        original_lock = first._effect_lock
        object.__setattr__(first, "_effect_lock", threading.Lock())
        with self.assertRaises(SystemExit):
            module._retire_legacy_effect_owner_lifecycle(
                first,
                _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
            )
        object.__setattr__(first, "_effect_lock", original_lock)
        self.assertIn(first_owner, module._LEGACY_EFFECT_OWNER_BINDINGS)
        self.assertIn(second_owner, module._LEGACY_EFFECT_OWNER_BINDINGS)

        for lifecycle in (first, second):
            module._retire_legacy_effect_owner_lifecycle(
                lifecycle,
                _lifecycle_token=module._LEGACY_EFFECT_LIFECYCLE_TOKEN,
            )
        self.assertEqual(len(module._LEGACY_EFFECT_PLAN_BINDINGS), 0)
        self.assertEqual(len(module._LEGACY_EFFECT_OWNER_BINDINGS), 0)

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
