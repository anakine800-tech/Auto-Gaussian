from __future__ import annotations

import base64
import unittest

import auto_g16.core as core
import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.transport._canonical import canonical_json_bytes
from auto_g16.transport._driver import _TextResult
from tests.v3.execution.test_execution import INPUT_BYTES, TEMPLATE_BYTES

from ._fixtures import FakeDriver, TransportFixture, response


def execution_successes(job_id: str = "123.server", *, input_bytes: bytes = INPUT_BYTES) -> tuple[_TextResult, ...]:
    workspace = base64.b64encode(b"workspace-token-v1").decode("ascii")
    staged = []
    for kind, logical, content in (("prepared-input", "input.gjf", input_bytes), ("pbs-template", "job.pbs", TEMPLATE_BYTES)):
        staged.append(response("STAGE_EXACT_FILE", {
            "artifact_kind": kind, "logical_name": logical, "remote_relative_name": logical,
            "sha256": __import__("hashlib").sha256(content).hexdigest(), "size_bytes": len(content),
            "artifact_physical_token_base64": base64.b64encode(canonical_json_bytes(["token", kind, logical])).decode("ascii"),
        }))
    return (
        response("ALLOCATE_WORKSPACE", {"remote_workspace": "/home/user100/SDL/project-1/attempt-1", "workspace_physical_token_base64": workspace}),
        *staged,
        response("SUBMIT_QSUB_ONCE", {"job_id": job_id}),
    )


class RTWinExecutionTests(TransportFixture):
    def test_exact_operation_order_and_binding_schemas(self) -> None:
        snapshot, profile = self.transport_snapshot()
        driver = FakeDriver(text_results=execution_successes())
        adapter = self.execution_adapter(driver, profile)
        self.assertEqual(adapter.allocate_attempt_workspace(snapshot), snapshot.workspace_binding.remote_attempt_dir)
        adapter.transfer_exact_bytes(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        self.assertEqual(adapter.submit_once(snapshot), "123.server")
        self.assertEqual(tuple(call[1].operation.name for call in driver.text_calls), ("ALLOCATE_WORKSPACE", "STAGE_EXACT_FILE", "STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE"))
        self.assertEqual(set(driver.text_calls[0][1].request["binding"]), {"transport_store_id", "store_instance_id", "runtime_attestation_id", "attempt_id", "execution_snapshot_id", "submission_intent_id", "remote_workspace"})
        self.assertNotIn("prepared_input_logical_name", driver.text_calls[-1][1].request["binding"])
        submit = driver.text_calls[-1][1]
        self.assertEqual(submit.request["payload"], {
            "pbs_basename": "job.pbs",
            "resource_enactment": {
                "execution_snapshot_id": snapshot.execution_snapshot_id,
                "resolved_resource_request_id": snapshot.resolved_resource_request.resolved_resource_request_id,
                "cores": 8, "memory_mb": 12_288, "walltime_seconds": 3_600,
                "queue": "simple",
                "scheduler_dialect_id": "auto-g16-v3-pbs-resource-enactment/synthetic-test/1",
            },
        })
        self.assertEqual(submit.argv, (
            "--auto-g16-synthetic-cores", "8",
            "--auto-g16-synthetic-memory-mb", "12288",
            "--auto-g16-synthetic-walltime-seconds", "3600",
            "--auto-g16-synthetic-queue", "simple", "job.pbs",
        ))

    def test_execute_once_winner_then_replay_has_one_effect_sequence(self) -> None:
        snapshot, profile = self.transport_snapshot()
        driver = FakeDriver(text_results=execution_successes())
        adapter = self.execution_adapter(driver, profile)
        first = execution.execute_once(self.store, snapshot=snapshot, current_profile=profile, prepared_input_bytes=INPUT_BYTES, pbs_template_bytes=TEMPLATE_BYTES, confirmed_execution_snapshot_id=snapshot.execution_snapshot_id, port=adapter)
        calls = len(driver.text_calls)
        replay = execution.execute_once(self.store, snapshot=snapshot, current_profile=profile, prepared_input_bytes=b"not-reread", pbs_template_bytes=b"not-reread", confirmed_execution_snapshot_id="not-reread", port=adapter)
        self.assertIs(first.claim, core.SubmissionIntentClaim.WINNER)
        self.assertIs(first.attempt_state, core.AttemptState.SUBMITTED)
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(driver.text_calls), calls)
        self.assertEqual(tuple(call[1].operation.name for call in driver.text_calls).count("SUBMIT_QSUB_ONCE"), 1)

    def test_postlaunch_qsub_drift_or_ambiguity_becomes_unknown_and_never_retries(self) -> None:
        snapshot, profile = self.transport_snapshot()
        results = list(execution_successes())
        results[-1] = _TextResult(stdout=b"", stderr=b"", returncode=None, eof_stdout=False, eof_stderr=False, completion_status="transport-error")
        driver = FakeDriver(text_results=tuple(results))
        adapter = self.execution_adapter(driver, profile)
        first = execution.execute_once(self.store, snapshot=snapshot, current_profile=profile, prepared_input_bytes=INPUT_BYTES, pbs_template_bytes=TEMPLATE_BYTES, confirmed_execution_snapshot_id=snapshot.execution_snapshot_id, port=adapter)
        before = len(driver.text_calls)
        replay = execution.execute_once(self.store, snapshot=snapshot, current_profile=profile, prepared_input_bytes=INPUT_BYTES, pbs_template_bytes=TEMPLATE_BYTES, confirmed_execution_snapshot_id=snapshot.execution_snapshot_id, port=adapter)
        self.assertIs(first.attempt_state, core.AttemptState.UNKNOWN)
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(driver.text_calls), before)

    def test_snapshot_or_current_profile_drift_rejects_before_driver(self) -> None:
        snapshot, profile = self.transport_snapshot()
        driver = FakeDriver(text_results=execution_successes())
        object.__setattr__(snapshot.resolved_resource_request, "cores", 99)
        with self.assertRaises(transport.TransportBoundaryError):
            self.execution_adapter(driver, profile).allocate_attempt_workspace(snapshot)
        self.assertEqual(driver.text_calls, [])

    def test_each_snapshot_resource_drift_rejects_before_driver(self) -> None:
        for field, changed in (
            ("cores", 9), ("memory_mb", 12_289),
            ("walltime_seconds", 3_601), ("queue", "other"),
            ("resolved_resource_request_id", "forged-resource-request"),
        ):
            with self.subTest(field=field):
                snapshot, profile = self.transport_snapshot()
                driver = FakeDriver(text_results=execution_successes())
                object.__setattr__(snapshot.resolved_resource_request, field, changed)
                with self.assertRaises(transport.TransportBoundaryError):
                    self.execution_adapter(driver, profile).allocate_attempt_workspace(snapshot)
                self.assertEqual(driver.text_calls, [])

    def test_gaussian_directives_never_rewrite_scheduler_resources(self) -> None:
        gaussian_bytes = b"%mem=1GB\n%nprocshared=1\n#p hf/sto-3g\n\njob\n\n0 1\nH 0 0 0\n\n"
        snapshot, profile = self.transport_snapshot(prepared_bytes=gaussian_bytes)
        driver = FakeDriver(text_results=execution_successes(input_bytes=gaussian_bytes))
        adapter = self.execution_adapter(driver, profile)
        adapter.allocate_attempt_workspace(snapshot)
        adapter.transfer_exact_bytes(snapshot, gaussian_bytes, TEMPLATE_BYTES)
        adapter.submit_once(snapshot)
        resource = driver.text_calls[-1][1].request["payload"]["resource_enactment"]
        self.assertEqual((resource["cores"], resource["memory_mb"]), (8, 12_288))

    def test_null_queue_emits_no_queue_selector(self) -> None:
        snapshot, profile = self.transport_snapshot(queue=None)
        driver = FakeDriver(text_results=execution_successes())
        adapter = self.execution_adapter(driver, profile)
        adapter.allocate_attempt_workspace(snapshot)
        adapter.transfer_exact_bytes(snapshot, INPUT_BYTES, TEMPLATE_BYTES)
        adapter.submit_once(snapshot)
        submit = driver.text_calls[-1][1]
        self.assertIsNone(submit.request["payload"]["resource_enactment"]["queue"])
        self.assertNotIn("--auto-g16-synthetic-queue", submit.argv)

    def test_staging_wrong_bytes_rejects_before_stage_driver(self) -> None:
        snapshot, profile = self.transport_snapshot()
        driver = FakeDriver(text_results=execution_successes())
        adapter = self.execution_adapter(driver, profile)
        adapter.allocate_attempt_workspace(snapshot)
        with self.assertRaises(execution.ConfirmedNoEffectError):
            adapter.transfer_exact_bytes(snapshot, b"wrong", TEMPLATE_BYTES)
        self.assertEqual(tuple(call[1].operation.name for call in driver.text_calls), ("ALLOCATE_WORKSPACE",))


if __name__ == "__main__":
    unittest.main()
