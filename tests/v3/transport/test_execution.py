from __future__ import annotations

import unittest

import auto_g16.core as core
import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.transport._driver import _TextResult

from tests.v3.execution.test_execution import INPUT_BYTES, TEMPLATE_BYTES

from ._fixtures import FakeDriver, TransportFixture, success


class RTWinExecutionTests(TransportFixture):
    def test_exact_operation_order_bytes_and_qsub_result(self) -> None:
        snapshot, _profile = self.transport_snapshot()
        driver = FakeDriver(
            text_results=(
                success(),
                success(),
                success(),
                success(b"123.server\n"),
            )
        )
        adapter = self.execution_adapter(driver)

        self.assertEqual(
            adapter.allocate_attempt_workspace(snapshot),
            snapshot.workspace_binding.remote_attempt_dir,
        )
        adapter.transfer_exact_bytes(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        self.assertEqual(adapter.submit_once(snapshot), "123.server")

        operations = tuple(call[1].operation.name for call in driver.text_calls)
        self.assertEqual(operations, ("allocate", "stage", "stage", "qsub"))
        invocations = tuple(call[1] for call in driver.text_calls)
        self.assertTrue(all(item.cwd == snapshot.workspace_binding.remote_attempt_dir for item in invocations))
        self.assertEqual(invocations[0].argv, ())
        self.assertEqual(
            invocations[1].argv,
            (
                "input.gjf",
                snapshot.prepared_input_binding.sha256,
                str(len(INPUT_BYTES)),
            ),
        )
        self.assertEqual(invocations[1].input_bytes, INPUT_BYTES)
        self.assertEqual(invocations[2].input_bytes, TEMPLATE_BYTES)
        self.assertEqual(invocations[3].argv, ("job.pbs",))

    def test_execute_once_winner_then_replay_makes_no_second_driver_call(self) -> None:
        snapshot, profile = self.transport_snapshot()
        driver = FakeDriver(
            text_results=(success(), success(), success(), success(b"123.server\n"))
        )
        adapter = self.execution_adapter(driver)
        first = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        calls = len(driver.text_calls)
        replay = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=b"not reread",
            pbs_template_bytes=b"not reread",
            confirmed_execution_snapshot_id="not-reread",
            port=adapter,
        )
        self.assertIs(first.claim, core.SubmissionIntentClaim.WINNER)
        self.assertIs(first.attempt_state, core.AttemptState.SUBMITTED)
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(driver.text_calls), calls)
        self.assertEqual(tuple(item[1].operation.name for item in driver.text_calls).count("qsub"), 1)

    def test_ambiguous_qsub_becomes_unknown_and_is_never_retried(self) -> None:
        snapshot, profile = self.transport_snapshot()
        malformed = _TextResult(
            stdout=b"123.server\n",
            stderr=b"warning\n",
            returncode=0,
            eof_stdout=True,
            eof_stderr=True,
            completion_status="completed",
        )
        driver = FakeDriver(text_results=(success(), success(), success(), malformed))
        adapter = self.execution_adapter(driver)
        first = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        before = len(driver.text_calls)
        second = execution.execute_once(
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
        self.assertIs(second.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(driver.text_calls), before)
        self.assertEqual(tuple(item[1].operation.name for item in driver.text_calls).count("qsub"), 1)

    def test_second_direct_submit_is_refused_without_driver_call(self) -> None:
        snapshot, _profile = self.transport_snapshot()
        driver = FakeDriver(
            text_results=(success(), success(), success(), success(b"123.server\n"))
        )
        adapter = self.execution_adapter(driver)
        adapter.allocate_attempt_workspace(snapshot)
        adapter.transfer_exact_bytes(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        adapter.submit_once(snapshot)
        before = len(driver.text_calls)
        with self.assertRaises(execution.PossiblyEffectfulError):
            adapter.submit_once(snapshot)
        self.assertEqual(len(driver.text_calls), before)

    def test_existing_workspace_is_confirmed_no_effect(self) -> None:
        snapshot, _profile = self.transport_snapshot()
        exists = _TextResult(
            stdout=b"",
            stderr=b"attempt-workspace-exists\n",
            returncode=17,
            eof_stdout=True,
            eof_stderr=True,
            completion_status="completed",
        )
        driver = FakeDriver(text_results=(exists,))
        with self.assertRaises(execution.ConfirmedNoEffectError):
            self.execution_adapter(driver).allocate_attempt_workspace(snapshot)
        self.assertEqual(len(driver.text_calls), 1)

    def test_runtime_table_and_snapshot_drift_reject_before_driver(self) -> None:
        profile = self.profile()
        profile.runtime_contents["auto-g16-rtwin-operation-table/1"] = b"drift"
        snapshot, _profile = self.transport_snapshot(profile=profile)
        driver = FakeDriver(text_results=(success(),))
        with self.assertRaises(transport.TransportBoundaryError):
            self.execution_adapter(driver).allocate_attempt_workspace(snapshot)
        self.assertEqual(driver.text_calls, [])
        clean_snapshot, _profile = self.transport_snapshot()
        object.__setattr__(clean_snapshot.resolved_resource_request, "cores", 99)
        with self.assertRaises(transport.TransportBoundaryError):
            self.execution_adapter(driver).allocate_attempt_workspace(clean_snapshot)
        self.assertEqual(driver.text_calls, [])

    def test_exact_qstat_reconciliation_never_resubmits(self) -> None:
        snapshot, _profile = self.transport_snapshot()
        ambiguous = _TextResult(
            stdout=b"123.server\n",
            stderr=b"warning\n",
            returncode=0,
            eof_stdout=True,
            eof_stderr=True,
            completion_status="completed",
        )
        present = success(b"Job Id: 123.server\n    job_state = R\n")
        driver = FakeDriver(
            text_results=(success(), success(), success(), ambiguous, present)
        )
        adapter = self.execution_adapter(driver)
        adapter.allocate_attempt_workspace(snapshot)
        adapter.transfer_exact_bytes(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        with self.assertRaises(execution.PossiblyEffectfulError):
            adapter.submit_once(snapshot)
        receipt = adapter.reconcile_submission(snapshot, effect_sequence=1)
        self.assertIs(receipt.effect_state, execution.EffectState.CONFIRMED_EFFECT)
        self.assertEqual(receipt.job_id, "123.server")
        self.assertEqual(
            tuple(item[1].operation.name for item in driver.text_calls),
            ("allocate", "stage", "stage", "qsub", "qstat"),
        )


if __name__ == "__main__":
    unittest.main()
