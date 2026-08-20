from __future__ import annotations

from dataclasses import fields, replace
import ast
from hashlib import sha256
import inspect
from pathlib import Path
import unittest

import auto_g16.execution as execution
from auto_g16.execution._rtwin_minimal import (
    _SubmissionInvocation,
    _build_rtwin_minimal_plan,
    _defer_offline_fetch,
)

from .test_execution import ExecutionFixture, INPUT_BYTES, TEMPLATE_BYTES


class MinimalRTWinPlanTests(ExecutionFixture):
    def test_exact_replay_is_one_deterministic_pure_data_plan(self) -> None:
        snapshot, _profile = self.snapshot()

        first = _build_rtwin_minimal_plan(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        second = _build_rtwin_minimal_plan(snapshot, INPUT_BYTES, TEMPLATE_BYTES)

        self.assertEqual(first, second)
        self.assertEqual(first.execution_snapshot_id, snapshot.execution_snapshot_id)
        self.assertEqual(first.attempt_id, snapshot.attempt_id)
        self.assertEqual(first.submission_intent_id, snapshot.submission_intent_id)
        self.assertEqual(
            first.workspace_binding_id,
            snapshot.workspace_binding.workspace_binding_id,
        )
        self.assertEqual(first.local_attempt_dir, snapshot.workspace_binding.local_attempt_dir)
        self.assertEqual(first.rtwin_attempt_dir, snapshot.workspace_binding.rtwin_attempt_dir)
        self.assertEqual(
            first.remote_attempt_dir, snapshot.workspace_binding.remote_attempt_dir
        )
        self.assertEqual(
            tuple(artifact.role for artifact in first.artifacts),
            ("prepared-input", "pbs-template"),
        )
        self.assertEqual(
            tuple(artifact.logical_name for artifact in first.artifacts),
            ("input.gjf", "job.pbs"),
        )
        self.assertEqual(first.artifacts[0].content, INPUT_BYTES)
        self.assertEqual(first.artifacts[1].content, TEMPLATE_BYTES)
        self.assertEqual(first.artifacts[0].size_bytes, len(INPUT_BYTES))
        self.assertEqual(first.artifacts[1].size_bytes, len(TEMPLATE_BYTES))
        self.assertEqual(first.artifacts[0].sha256, sha256(INPUT_BYTES).hexdigest())
        self.assertEqual(first.artifacts[1].sha256, sha256(TEMPLATE_BYTES).hexdigest())
        self.assertEqual(first.submission.executable, "qsub")
        self.assertEqual(first.submission.argv, ("job.pbs",))
        self.assertEqual(first.submission.cwd, first.remote_attempt_dir)

    def test_plan_rejects_executable_argv_and_cwd_injection(self) -> None:
        snapshot, _profile = self.snapshot()
        plan = _build_rtwin_minimal_plan(snapshot, INPUT_BYTES, TEMPLATE_BYTES)

        with self.assertRaises(execution.ExecutionValueError):
            _SubmissionInvocation(executable="sh", argv=("job.pbs",), cwd=plan.remote_attempt_dir)
        for argv in (("job.pbs", "extra"), ("job.pbs;touch-x",), ("job.pbs\nother",)):
            with self.subTest(argv=argv), self.assertRaises(execution.ExecutionValueError):
                _SubmissionInvocation(
                    executable="qsub", argv=argv, cwd=plan.remote_attempt_dir
                )
        alternate = _SubmissionInvocation(
            executable="qsub",
            argv=("job.pbs",),
            cwd="/home/user100/SDL/other/attempt-1",
        )
        with self.assertRaises(execution.ExecutionValueError):
            replace(plan, submission=alternate)

    def test_plan_has_no_ambient_or_caller_command_inputs(self) -> None:
        snapshot, _profile = self.snapshot()
        plan = _build_rtwin_minimal_plan(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        self.assertEqual(
            tuple(item.name for item in fields(plan)),
            (
                "execution_snapshot_id",
                "attempt_id",
                "submission_intent_id",
                "project_id",
                "workspace_binding_id",
                "local_attempt_dir",
                "rtwin_attempt_dir",
                "remote_attempt_dir",
                "artifacts",
                "submission",
            ),
        )
        module_path = Path(execution.__file__).resolve().with_name("_rtwin_minimal.py")
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0
        )
        self.assertTrue(
            imported_roots.isdisjoint(
                {"os", "time", "tempfile", "subprocess", "socket", "paramiko"}
            )
        )

    def test_synthetic_adapter_consumes_plan_and_valid_fresh_flow_submits(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter()

        result = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )

        self.assertEqual(adapter.calls, ("allocate:attempt-1", "transfer:attempt-1", "submit:attempt-1"))
        self.assertEqual(adapter.submission_calls, 1)
        self.assertEqual(result.receipts[-1].job_id, "12345.synthetic")

    def test_confirmed_job_binding_stops_fetch_as_deferred(self) -> None:
        snapshot, profile = self.snapshot()
        result = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=execution.SyntheticRTWinAdapter(),
        )

        boundary = _defer_offline_fetch(snapshot, result.receipts[-1])

        self.assertEqual(boundary.disposition, "DEFERRED")
        self.assertEqual(boundary.execution_snapshot_id, snapshot.execution_snapshot_id)
        self.assertEqual(boundary.job_id, "12345.synthetic")
        self.assertEqual(
            boundary.remote_workspace,
            snapshot.workspace_binding.remote_attempt_dir,
        )

    def test_fetch_boundary_rejects_unconfirmed_or_spliced_evidence(self) -> None:
        snapshot, _profile = self.snapshot()
        invalid = (
            execution.RemoteEffectReceipt(
                attempt_id=snapshot.attempt_id,
                execution_snapshot_id=snapshot.execution_snapshot_id,
                submission_intent_id=snapshot.submission_intent_id,
                effect_sequence=1,
                effect_kind=execution.EffectKind.SUBMISSION,
                effect_state=execution.EffectState.POSSIBLY_EFFECTFUL,
                remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
                details={"code": "ambiguous"},
            ),
            execution.RemoteEffectReceipt(
                attempt_id=snapshot.attempt_id,
                execution_snapshot_id="spliced-snapshot",
                submission_intent_id=snapshot.submission_intent_id,
                effect_sequence=1,
                effect_kind=execution.EffectKind.SUBMISSION,
                effect_state=execution.EffectState.CONFIRMED_EFFECT,
                remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
                job_id="12345.synthetic",
            ),
            execution.RemoteEffectReceipt(
                attempt_id=snapshot.attempt_id,
                execution_snapshot_id=snapshot.execution_snapshot_id,
                submission_intent_id=snapshot.submission_intent_id,
                effect_sequence=1,
                effect_kind=execution.EffectKind.SUBMISSION,
                effect_state=execution.EffectState.CONFIRMED_EFFECT,
                remote_workspace="/home/user100/SDL/other/attempt-1",
                job_id="12345.synthetic",
            ),
        )
        for receipt in invalid:
            with self.subTest(receipt=receipt), self.assertRaises(
                execution.ExecutionValueError
            ):
                _defer_offline_fetch(snapshot, receipt)


class PublicCompatibilityTests(unittest.TestCase):
    def test_public_inventory_enums_and_signatures_are_frozen(self) -> None:
        self.assertEqual(
            tuple(execution.__all__),
            (
                "ConfirmedNoEffectError",
                "EffectKind",
                "EffectState",
                "ExecutionAttemptResult",
                "ExecutionConflictError",
                "ExecutionPort",
                "ExecutionRuntimeError",
                "ExecutionSnapshot",
                "ExecutionValueError",
                "LEGACY_REMOTE_ROOT",
                "PbsTemplateBinding",
                "PossiblyEffectfulError",
                "PreparedInputBinding",
                "ReceiptJournal",
                "RemoteEffectReceipt",
                "ResolvedResourceRequest",
                "ResolvedServerProfile",
                "ServerProfile",
                "SyntheticRTWinAdapter",
                "WorkspaceBinding",
                "assert_execution_snapshot_identity",
                "execute_once",
                "prepare_execution_snapshot",
                "reconcile_unknown",
                "reconcile_unknown_from_receipt",
                "resolve_server_profile",
            ),
        )
        self.assertEqual(
            tuple(item.value for item in execution.EffectKind),
            (
                "local-workspace",
                "remote-workspace",
                "input-transfer",
                "submission",
                "submission-reconciliation",
            ),
        )
        self.assertEqual(
            tuple(item.value for item in execution.EffectState),
            ("confirmed_no_effect", "confirmed_effect", "possibly_effectful"),
        )
        expected_parameters = {
            execution.execute_once: (
                "store",
                "snapshot",
                "current_profile",
                "prepared_input_bytes",
                "pbs_template_bytes",
                "confirmed_execution_snapshot_id",
                "port",
            ),
            execution.reconcile_unknown: ("store", "snapshot", "port"),
            execution.reconcile_unknown_from_receipt: ("store", "snapshot", "receipt"),
            execution.ExecutionPort.allocate_attempt_workspace: ("self", "snapshot"),
            execution.ExecutionPort.transfer_exact_bytes: (
                "self",
                "snapshot",
                "prepared_input_bytes",
                "pbs_template_bytes",
            ),
            execution.ExecutionPort.submit_once: ("self", "snapshot"),
            execution.ExecutionPort.reconcile_submission: (
                "self",
                "snapshot",
                "effect_sequence",
            ),
        }
        for callable_value, names in expected_parameters.items():
            with self.subTest(callable=callable_value):
                self.assertEqual(tuple(inspect.signature(callable_value).parameters), names)

    def test_execution_has_no_approval_legacy_or_live_transport_import(self) -> None:
        package = Path(execution.__file__).resolve().parent
        forbidden_modules = {
            "auto_g16.approval",
            "legacy_rtwin_pbs",
            "subprocess",
            "socket",
            "paramiko",
        }
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            with self.subTest(path=path.name):
                self.assertTrue(imports.isdisjoint(forbidden_modules))


if __name__ == "__main__":
    unittest.main()
