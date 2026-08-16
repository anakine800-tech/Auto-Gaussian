from __future__ import annotations

from pathlib import Path
import os
import shutil
import tempfile
import threading
import unittest

import auto_g16.core as core
import auto_g16.execution as execution


INPUT_BYTES = b"%mem=12GB\n%nprocshared=8\n#p b3lyp/6-31g(d) opt\n\njob\n\n0 1\nH 0 0 0\n\n"
TEMPLATE_BYTES = b"#!/bin/bash\n#PBS -N synthetic\nexec g16 input.gjf\n"


def restore_permissions(path: Path) -> None:
    if not path.exists():
        return
    for root, directories, files in os.walk(path):
        os.chmod(root, 0o700)
        for directory in directories:
            os.chmod(Path(root) / directory, 0o700)
        for filename in files:
            os.chmod(Path(root) / filename, 0o600)


class ExecutionFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(self._cleanup)
        self.database = self.temporary / "runtime.sqlite3"
        self.local_root = self.temporary / "local"
        self.local_project = self.local_root / "project-1"
        self.local_project.mkdir(parents=True)
        self.store = core.SQLiteRuntimeStore(self.database)
        self.addCleanup(self.store.close)
        self._store_core_chain(self.store)

    def _cleanup(self) -> None:
        restore_permissions(self.temporary)
        shutil.rmtree(self.temporary, ignore_errors=False)

    @staticmethod
    def _store_core_chain(store: core.SQLiteRuntimeStore) -> None:
        store.store_project(core.Project(project_id="project-1"))
        store.store_workflow_run(
            core.WorkflowRun(
                workflow_run_id="run-1",
                project_id="project-1",
                workflow_name="minimum",
            )
        )
        store.store_task(
            core.Task(
                task_id="task-1",
                workflow_run_id="run-1",
                task_kind="gaussian-minimum",
            )
        )
        store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id="plan-1",
                task_id="task-1",
                revision=3,
                intent={"route": "#p b3lyp/6-31g(d) opt", "charge": 0},
            )
        )
        store.store_resource_spec(
            core.ResourceSpec(
                resource_spec_id="resources-1",
                task_id="task-1",
                resources={"tier": "simple"},
            )
        )
        store.create_attempt(
            core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1)
        )

    def profile(self, *, config: bytes = b"Host RTwin\n  HostName 100.64.0.1\n") -> execution.ServerProfile:
        return execution.ServerProfile(
            server_profile_id="profile-1",
            profile_revision=7,
            transport_kind="legacy_rtwin_pbs",
            target_host="10.0.0.50",
            target_port=22,
            remote_user="user100",
            jump_topology=[("100.64.0.1", 22, "rtwin-user")],
            host_key_policy="strict",
            batch_mode=True,
            identities_only=True,
            remote_root=execution.LEGACY_REMOTE_ROOT,
            platform_paths={
                "rtwin_root": r"C:\RTWIN",
                "known_hosts": "/etc/ssh/ssh_known_hosts",
            },
            config_files=[("ssh_config", config)],
            runtime_contents={
                "pbs-wrapper": b"qsub -- synthetic",
                "known-hosts": b"10.0.0.50 ssh-ed25519 synthetic",
            },
        )

    def snapshot(
        self,
        *,
        profile: execution.ServerProfile | None = None,
        cores: int = 8,
        input_bytes: bytes = INPUT_BYTES,
        attempt_dir: Path | None = None,
    ) -> tuple[execution.ExecutionSnapshot, execution.ServerProfile]:
        actual_profile = profile or self.profile()
        prepared = execution.PreparedInputBinding(
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            calculation_plan_revision=3,
            input_format="gaussian-gjf",
            logical_name="input.gjf",
            prepared_bytes=input_bytes,
        )
        resource = execution.ResolvedResourceRequest(
            resource_spec=self.store.load_resource_spec("resources-1"),
            cores=cores,
            memory_mb=12_288,
            walltime_seconds=3_600,
            queue="simple",
        )
        resolved = execution.resolve_server_profile(actual_profile)
        directory = attempt_dir or self.local_project / "attempt-1"
        workspace = execution.WorkspaceBinding(
            project=self.store.load_project("project-1"),
            attempt_id="attempt-1",
            local_approved_root=str(self.local_root),
            local_attempt_dir=str(directory),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir="/home/user100/SDL/project-1/attempt-1",
        )
        template = execution.PbsTemplateBinding(
            logical_name="job.pbs",
            template_bytes=TEMPLATE_BYTES,
            template_contract_version="pbs-template-v1",
            prepared_input_logical_name="input.gjf",
        )
        snapshot = execution.prepare_execution_snapshot(
            self.store,
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            resource_spec_id="resources-1",
            prepared_input_binding=prepared,
            resolved_resource_request=resource,
            resolved_server_profile=resolved,
            workspace_binding=workspace,
            pbs_template_binding=template,
            adapter_contract_version="synthetic-rtwin-v1",
        )
        return snapshot, actual_profile


class IdentityAndPreparationTests(ExecutionFixture):
    def test_exact_semantic_replay_keeps_snapshot_identity(self) -> None:
        first, _profile = self.snapshot()
        reordered = self.profile()
        reordered.platform_paths = {
            "known_hosts": "/etc/ssh/ssh_known_hosts",
            "rtwin_root": r"C:\RTWIN",
        }
        second, _profile = self.snapshot(profile=reordered)
        self.assertEqual(first.execution_snapshot_id, second.execution_snapshot_id)
        self.assertEqual(first.submission_intent_id, second.submission_intent_id)

    def test_each_effect_relevant_change_changes_snapshot_identity(self) -> None:
        baseline, _profile = self.snapshot()
        changed_resources, _profile = self.snapshot(cores=9)
        changed_input, _profile = self.snapshot(input_bytes=INPUT_BYTES + b"\n")
        changed_profile, _profile = self.snapshot(
            profile=self.profile(config=b"Host RTwin\n  HostName 100.64.0.2\n")
        )
        self.assertEqual(
            len(
                {
                    baseline.execution_snapshot_id,
                    changed_resources.execution_snapshot_id,
                    changed_input.execution_snapshot_id,
                    changed_profile.execution_snapshot_id,
                }
            ),
            4,
        )

    def test_preparation_rejects_cross_task_plan(self) -> None:
        self.store.store_task(
            core.Task(task_id="task-2", workflow_run_id="run-1", task_kind="other")
        )
        self.store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id="plan-2",
                task_id="task-2",
                revision=1,
                intent={},
            )
        )
        snapshot, _profile = self.snapshot()
        with self.assertRaises(execution.ExecutionValueError):
            execution.prepare_execution_snapshot(
                self.store,
                attempt_id="attempt-1",
                calculation_plan_id="plan-2",
                resource_spec_id="resources-1",
                prepared_input_binding=snapshot.prepared_input_binding,
                resolved_resource_request=snapshot.resolved_resource_request,
                resolved_server_profile=snapshot.resolved_server_profile,
                workspace_binding=snapshot.workspace_binding,
                pbs_template_binding=snapshot.pbs_template_binding,
                adapter_contract_version="synthetic-rtwin-v1",
            )

    def test_profile_resolution_binds_exact_config_and_runtime_bytes(self) -> None:
        profile = self.profile()
        first = execution.resolve_server_profile(profile)
        profile.runtime_contents["pbs-wrapper"] = b"changed"
        second = execution.resolve_server_profile(profile)
        self.assertNotEqual(first.effective_config_sha256, second.effective_config_sha256)
        self.assertNotEqual(first.resolved_server_profile_id, second.resolved_server_profile_id)

    def test_template_identity_comes_from_exact_bytes(self) -> None:
        first = execution.PbsTemplateBinding(
            logical_name="job.pbs",
            template_bytes=TEMPLATE_BYTES,
            template_contract_version="pbs-template-v1",
            prepared_input_logical_name="input.gjf",
        )
        second = execution.PbsTemplateBinding(
            logical_name="job.pbs",
            template_bytes=TEMPLATE_BYTES + b"# exact change\n",
            template_contract_version="pbs-template-v1",
            prepared_input_logical_name="input.gjf",
        )
        self.assertNotEqual(first.pbs_template_binding_id, second.pbs_template_binding_id)
        with self.assertRaises(TypeError):
            execution.PbsTemplateBinding(  # type: ignore[call-arg]
                logical_name="job.pbs",
                sha256="0" * 64,
                size_bytes=1,
                template_contract_version="pbs-template-v1",
                prepared_input_logical_name="input.gjf",
            )


class ExecutionFlowTests(ExecutionFixture):
    def test_confirmed_submission_persists_ordered_minimal_receipts(self) -> None:
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
        self.assertIs(result.claim, core.SubmissionIntentClaim.WINNER)
        self.assertIs(result.attempt_state, core.AttemptState.SUBMITTED)
        self.assertEqual(adapter.submission_calls, 1)
        self.assertEqual(
            [receipt.effect_sequence for receipt in result.receipts], [1, 2, 3, 4]
        )
        self.assertEqual(result.receipts[-1].job_id, "12345.synthetic")
        local = Path(snapshot.workspace_binding.local_attempt_dir)
        self.assertEqual((local / "input.gjf").read_bytes(), INPUT_BYTES)
        self.assertEqual((local / "job.pbs").read_bytes(), TEMPLATE_BYTES)
        self.assertEqual(stat_mode(local), 0o500)

    def test_replay_makes_zero_additional_adapter_calls(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter()
        execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        before = adapter.calls
        replay = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(adapter.calls, before)

    def test_completed_replay_does_not_reread_mutated_profile(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter()
        execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        before = adapter.calls
        profile.config_files[0] = ("ssh_config", b"mutated after execution")
        replay = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=b"not reread on replay",
            pbs_template_bytes=b"not reread on replay",
            confirmed_execution_snapshot_id="not re-confirmed on replay",
            port=adapter,
        )
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(adapter.calls, before)

    def test_existing_workspace_is_confirmed_no_effect_not_unknown(self) -> None:
        snapshot, profile = self.snapshot()
        Path(snapshot.workspace_binding.local_attempt_dir).mkdir()
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
        self.assertIs(result.attempt_state, core.AttemptState.SUBMISSION_INTENT_RECORDED)
        self.assertIs(result.receipts[-1].effect_state, execution.EffectState.CONFIRMED_NO_EFFECT)
        self.assertEqual(adapter.calls, ())

    def test_possibly_effectful_submit_becomes_unknown_and_never_retries(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter(
            fail_stage=execution.EffectKind.SUBMISSION,
            ambiguous=True,
        )
        first = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        self.assertIs(first.attempt_state, core.AttemptState.UNKNOWN)
        self.assertIs(first.receipts[-1].effect_state, execution.EffectState.POSSIBLY_EFFECTFUL)
        before = adapter.calls
        replay = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(adapter.calls, before)
        self.assertEqual(adapter.submission_calls, 1)

    def test_unknown_reconciliation_is_same_attempt_read_only_evidence(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter(
            fail_stage=execution.EffectKind.SUBMISSION,
            ambiguous=True,
        )
        execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        reconciler = execution.SyntheticRTWinAdapter(
            reconciliation_state=execution.EffectState.CONFIRMED_EFFECT,
            reconciliation_job_id="12345.synthetic",
        )
        state = execution.reconcile_unknown(
            self.store, snapshot=snapshot, port=reconciler
        )
        self.assertIs(state, core.AttemptState.SUBMITTED)
        self.assertEqual(adapter.submission_calls, 1)
        self.assertEqual(reconciler.calls, ("reconcile:attempt-1",))

    def test_unresolved_then_confirmed_absent_reconciliation_never_retries(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter(
            fail_stage=execution.EffectKind.SUBMISSION,
            ambiguous=True,
        )
        execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        unresolved = execution.RemoteEffectReceipt(
            attempt_id="attempt-1",
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=5,
            effect_kind=execution.EffectKind.SUBMISSION_RECONCILIATION,
            effect_state=execution.EffectState.POSSIBLY_EFFECTFUL,
            details={"source": "synthetic-read-only"},
        )
        self.assertIs(
            execution.reconcile_unknown_from_receipt(
                self.store, snapshot=snapshot, receipt=unresolved
            ),
            core.AttemptState.UNKNOWN,
        )
        absent = execution.RemoteEffectReceipt(
            attempt_id="attempt-1",
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=6,
            effect_kind=execution.EffectKind.SUBMISSION_RECONCILIATION,
            effect_state=execution.EffectState.CONFIRMED_NO_EFFECT,
            details={"source": "synthetic-read-only"},
        )
        self.assertIs(
            execution.reconcile_unknown_from_receipt(
                self.store, snapshot=snapshot, receipt=absent
            ),
            core.AttemptState.NOT_SUBMITTED,
        )
        self.assertEqual(adapter.submission_calls, 1)

    def test_profile_or_input_drift_stops_before_claim_and_effect(self) -> None:
        snapshot, profile = self.snapshot()
        profile.config_files[0] = ("ssh_config", b"changed")
        adapter = execution.SyntheticRTWinAdapter()
        with self.assertRaises(execution.ExecutionValueError):
            execution.execute_once(
                self.store,
                snapshot=snapshot,
                current_profile=profile,
                prepared_input_bytes=INPUT_BYTES,
                pbs_template_bytes=TEMPLATE_BYTES,
                confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                port=adapter,
            )
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
        self.assertEqual(adapter.calls, ())

    def test_concurrent_claims_have_one_winner_and_one_submit(self) -> None:
        snapshot, profile = self.snapshot()
        self.store.close()
        adapter = execution.SyntheticRTWinAdapter()
        barrier = threading.Barrier(2)
        claims: list[core.SubmissionIntentClaim] = []
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                with core.SQLiteRuntimeStore(self.database) as store:
                    barrier.wait()
                    result = execution.execute_once(
                        store,
                        snapshot=snapshot,
                        current_profile=profile,
                        prepared_input_bytes=INPUT_BYTES,
                        pbs_template_bytes=TEMPLATE_BYTES,
                        confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                        port=adapter,
                    )
                    claims.append(result.claim)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _item in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertCountEqual(
            claims,
            [core.SubmissionIntentClaim.WINNER, core.SubmissionIntentClaim.REPLAY],
        )
        self.assertEqual(adapter.submission_calls, 1)


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
