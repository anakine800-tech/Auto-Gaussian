from __future__ import annotations

import ast
from dataclasses import fields
from hashlib import sha256
import inspect
from pathlib import Path
from typing import Mapping
import unittest
from unittest.mock import patch

import auto_g16.core as core
import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.execution import program_runtime
from auto_g16.execution.program_runtime import (
    _assert_effect_intent_replay,
    _capture_program_outputs,
    _execute_program_once,
    _job_authority,
    _load_receipts,
    _query_program_scheduler,
    _reconstruct_ambiguous_submit,
    _reconcile_program_submission,
)
from auto_g16.execution.program import _prepare_program_execution_spec
from auto_g16.transport import _bridge, _driver
from auto_g16.transport.program import (
    _PROGRAM_STORE_SCHEMA,
    _PROGRAM_STORE_TABLES,
    _PROTOCOL,
    _RECEIPT_TYPE,
    _ProgramTransportStore,
    _ProgramConfirmedFailure,
    _ProgramEffectUnknown,
    _identity,
    _prepare_program_effect_requests,
)
from tests.v3.execution.test_v31_lane_a import (
    CREST_EXECUTABLE_BYTES,
    CREST_EXECUTABLE_PATH,
    GAUSSIAN_INPUT,
    PBS_TEMPLATE,
    XYZ,
    LaneAFixture,
)


class _Driver:
    def __init__(self, outputs: Mapping[str, bytes] | None = None) -> None:
        bootstrap = b"synthetic-v31-program-driver\n"
        self.runtime_qualification: Mapping[str, object] = {
            "deployment_id": "synthetic-v31-program-driver",
            "bootstrap_protocol": "synthetic-v31-program-effect/1",
            "bootstrap_source_sha256": sha256(bootstrap).hexdigest(),
            "bootstrap_source_size_bytes": len(bootstrap),
        }
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.outputs = dict(outputs or {"xtb.out": b"normal xtb\n", "xtbopt.xyz": XYZ})
        self.raise_operation: tuple[str, BaseException] | None = None
        self.submit_response: Mapping[str, object] = {"job_id": "123.server"}
        self.query_response: Mapping[str, object] | None = None
        self.reconcile_response: Mapping[str, object] = {"outcome": "UNKNOWN"}
        self.stat_override: Mapping[str, object] | None = None
        self.fetch_override: Mapping[str, object] | None = None

    def _record(self, operation: str, request: Mapping[str, object]) -> None:
        self.calls.append((operation, request))
        if self.raise_operation is not None and self.raise_operation[0] == operation:
            raise self.raise_operation[1]

    def allocate_workspace(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._record("ALLOCATE_WORKSPACE", request)
        binding = request["binding"]
        assert isinstance(binding, Mapping)
        return {
            "remote_workspace": binding["remote_workspace"],
            "workspace_physical_token": "workspace-token-v31",
        }

    def stage_exact_file(
        self, request: Mapping[str, object], content: bytes
    ) -> Mapping[str, object]:
        self._record("STAGE_EXACT_FILE", request)
        payload = request["payload"]
        assert isinstance(payload, Mapping)
        assert len(content) == payload["size_bytes"]
        return {**dict(payload), "artifact_physical_token": f"token-{payload['portable_name']}"}

    def submit_qsub_once(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._record("SUBMIT_QSUB_ONCE", request)
        return self.submit_response

    def query_scheduler(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._record("QUERY_SCHEDULER", request)
        payload = request["payload"]
        assert isinstance(payload, Mapping)
        return self.query_response or {"job_id": payload["job_id"], "state": "running"}

    def stat_exact_file(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._record("STAT_EXACT_FILE", request)
        if self.stat_override is not None:
            return self.stat_override
        payload = request["payload"]
        assert isinstance(payload, Mapping)
        name = str(payload["portable_name"])
        if name not in self.outputs:
            return {"portable_name": name, "presence": "absent"}
        return {
            "portable_name": name,
            "presence": "present",
            "size_bytes": len(self.outputs[name]),
            "file_physical_token": f"output-token-{name}",
        }

    def fetch_exact_file(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._record("FETCH_EXACT_FILE", request)
        if self.fetch_override is not None:
            return self.fetch_override
        payload = request["payload"]
        assert isinstance(payload, Mapping)
        name = str(payload["portable_name"])
        content = self.outputs[name]
        return {
            "portable_name": name,
            "content": content,
            "sha256": sha256(content).hexdigest(),
            "size_bytes": len(content),
            "file_physical_token": payload["expected_file_physical_token"],
        }

    def reconcile_submission(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._record("RECONCILE_SUBMISSION", request)
        return self.reconcile_response


class _V30Port:
    contract_version = "synthetic-v30"

    def __init__(self) -> None:
        self.calls = 0

    def allocate_attempt_workspace(self, snapshot: execution.ExecutionSnapshot) -> str:
        self.calls += 1
        return snapshot.workspace_binding.remote_attempt_dir

    def transfer_exact_bytes(
        self,
        snapshot: execution.ExecutionSnapshot,
        prepared_input_bytes: bytes,
        pbs_template_bytes: bytes,
    ) -> None:
        self.calls += 1

    def submit_once(self, snapshot: execution.ExecutionSnapshot) -> str:
        self.calls += 1
        return "123.server"

    def reconcile_submission(
        self, snapshot: execution.ExecutionSnapshot, *, effect_sequence: int
    ) -> execution.RemoteEffectReceipt:
        self.calls += 1
        raise AssertionError("not reached")


def _mutable_copy(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _mutable_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_mutable_copy(item) for item in value)
    if isinstance(value, list):
        return [_mutable_copy(item) for item in value]
    return value


class ProgramCompositionTests(LaneAFixture):
    def setUp(self) -> None:
        super().setUp()
        transport_root = self.root / "transport"
        transport_root.mkdir()
        self.program_transport_store = _ProgramTransportStore.create_new(
            transport_root / "program-transport.sqlite3",
            approved_root=transport_root,
        )
        self.addCleanup(self.program_transport_store.close)
        self.snapshot = self.successor_snapshot()
        scheduler = self.snapshot.scheduler_artifacts[0]
        self.input_bytes = {"input.xyz": XYZ}
        self.scheduler_bytes = {
            str(scheduler["portable_name"]): str(scheduler["content_utf8"]).encode("utf-8")
        }
        self.driver = _Driver()

    def execute(self, driver: _Driver | None = None):
        return _execute_program_once(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
            driver=self.driver if driver is None else driver,
        )

    def fresh_core_store(self, name: str) -> core.SQLiteRuntimeStore:
        store = core.SQLiteRuntimeStore(self.root / f"{name}.sqlite3")
        self.addCleanup(store.close)
        store.store_project(core.Project(project_id="project-1"))
        store.store_workflow_run(
            core.WorkflowRun(
                workflow_run_id="run-1",
                project_id="project-1",
                workflow_name="x3",
            )
        )
        store.store_task(
            core.Task(
                task_id="task-1",
                workflow_run_id="run-1",
                task_kind="successor-program",
            )
        )
        store.create_attempt(
            core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1)
        )
        return store

    def fresh_program_store(self, name: str) -> _ProgramTransportStore:
        root = self.root / name
        root.mkdir()
        store = _ProgramTransportStore.create_new(
            root / "program-transport.sqlite3", approved_root=root
        )
        self.addCleanup(store.close)
        return store

    def begin_unknown_submission(self) -> None:
        self.driver.raise_operation = (
            "SUBMIT_QSUB_ONCE",
            _ProgramEffectUnknown("ambiguous"),
        )
        result = self.execute()
        self.assertEqual(result.outcome, "UNKNOWN")
        self.driver.raise_operation = None

    def append_dual_source_receipt(
        self,
        store: core.SQLiteRuntimeStore,
        program_store: _ProgramTransportStore,
        *,
        snapshot,
        request: Mapping[str, object],
        outcome: str,
        response: Mapping[str, object],
        job_id: str | None = None,
        physical: bool = True,
    ) -> core.Observation:
        if physical:
            program_store.record_effect(
                binding=request["binding"],
                request=request,
                classification=outcome,
                response=response,
                job_id=job_id,
            )
        sequence = len(store.observations_for_attempt(snapshot.attempt_id)) + 1
        payload = program_runtime._receipt_payload(
            snapshot,
            sequence=sequence,
            operation=str(request["operation"]),
            request=request,
            outcome=outcome,
            response=response,
        )
        receipt = core.Observation(
            observation_id=_identity("effect-receipt", payload),
            attempt_id=snapshot.attempt_id,
            observation_type=_RECEIPT_TYPE,
            data=payload,
        )
        store.append_observation(receipt)
        return receipt

    def manual_context(self, name: str):
        store = self.fresh_core_store(f"{name}-core")
        program_store = self.fresh_program_store(f"{name}-physical")
        driver = _Driver()
        base = program_runtime._snapshot_binding(
            self.snapshot, program_store, driver
        )
        return store, program_store, driver, base

    def append_allocate(self, store, program_store, base):
        request = program_runtime._transport._request(
            "ALLOCATE_WORKSPACE", base, {}
        )
        response = {
            "remote_workspace": self.snapshot.workspace_binding.remote_attempt_dir,
            "workspace_physical_token": "manual-workspace-token",
        }
        receipt = self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response=response,
        )
        return program_runtime._workspace_authority(
            self.snapshot, receipt, program_store
        )

    def append_stage(
        self, store, program_store, base, workspace, declaration
    ):
        request = program_runtime._transport._stage_request(
            base, workspace, declaration
        )
        response = {
            **dict(declaration),
            "artifact_physical_token": f"manual-{declaration['portable_name']}",
        }
        receipt = self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response=response,
        )
        return program_runtime._artifact_authority(
            self.snapshot, receipt, program_store
        )

    def append_valid_direct_submit(
        self, store, program_store, driver, base, *, submit_physical=True
    ):
        store.record_submission_intent(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )
        workspace = self.append_allocate(store, program_store, base)
        material = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )
        authorities = tuple(
            self.append_stage(
                store, program_store, base, workspace, declaration
            )
            for declaration, _content in material
        )
        scheduler = next(
            item for item in authorities
            if item["artifact_kind"] == "scheduler-script"
        )
        inputs = tuple(
            item for item in authorities
            if item["artifact_kind"] == "program-input"
        )
        request = program_runtime._transport._submit_request(
            base,
            workspace,
            scheduler_portable_name="xtb.pbs",
            scheduler_artifact_authority_id=str(
                scheduler["artifact_authority_id"]
            ),
            program_input_artifact_authority_ids=tuple(
                str(item["artifact_authority_id"]) for item in inputs
            ),
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={"job_id": "manual.server"},
            job_id="manual.server",
            physical=submit_physical,
        )
        store.record_submission_outcome(
            self.snapshot.attempt_id,
            self.snapshot.effect_intent_id,
            core.SubmissionOutcome.SUBMITTED,
        )
        if submit_physical:
            return _job_authority(
                store, self.snapshot, program_store, driver
            )
        return None

    def append_unknown_submit(self, store, program_store, base):
        store.record_submission_intent(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )
        workspace = self.append_allocate(store, program_store, base)
        material = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )
        authorities = tuple(
            self.append_stage(
                store, program_store, base, workspace, declaration
            )
            for declaration, _content in material
        )
        scheduler = next(
            item
            for item in authorities
            if item["artifact_kind"] == "scheduler-script"
        )
        inputs = tuple(
            item
            for item in authorities
            if item["artifact_kind"] == "program-input"
        )
        request = program_runtime._transport._submit_request(
            base,
            workspace,
            scheduler_portable_name="xtb.pbs",
            scheduler_artifact_authority_id=str(
                scheduler["artifact_authority_id"]
            ),
            program_input_artifact_authority_ids=tuple(
                str(item["artifact_authority_id"]) for item in inputs
            ),
        )
        return self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="UNKNOWN",
            response={"reason": "ambiguous-operation-outcome"},
        )

    def append_successful_reconciliation(
        self, store, program_store, base, submit_receipt, *, job_id="999.server"
    ):
        request = program_runtime._transport._reconciliation_request(
            base, submit_receipt_id=submit_receipt.observation_id
        )
        return self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={"outcome": "SUCCEEDED", "job_id": job_id},
            job_id=job_id,
        )

    def clone_receipts_with_mutation(
        self,
        name: str,
        receipt_index: int,
        mutate: object,
    ) -> tuple[core.SQLiteRuntimeStore, Mapping[str, object]]:
        receipts = self.execute().receipts
        other = self.fresh_core_store(name)
        changed_payload: Mapping[str, object] | None = None
        for index, receipt in enumerate(receipts):
            payload = _mutable_copy(receipt.data)
            assert isinstance(payload, dict)
            if index == receipt_index:
                assert callable(mutate)
                mutate(payload)
                changed_payload = payload
            replacement = core.Observation(
                observation_id=_identity("effect-receipt", payload),
                attempt_id=receipt.attempt_id,
                observation_type=receipt.observation_type,
                data=payload,
            )
            other.append_observation(replacement)
        assert changed_payload is not None
        return other, changed_payload

    def test_01_snapshot_closes_before_composition(self) -> None:
        result = self.execute()
        self.assertEqual(result.outcome, "SUCCEEDED")
        self.assertEqual(self.driver.calls[0][0], "ALLOCATE_WORKSPACE")

    def test_02_forged_snapshot_id_rejects_before_claim(self) -> None:
        object.__setattr__(self.snapshot, "program_execution_snapshot_id", "forged")
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)

    def test_03_forged_effect_intent_rejects_before_claim(self) -> None:
        object.__setattr__(self.snapshot, "effect_intent_id", "forged")
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_04_wrong_workspace_rejects_before_claim(self) -> None:
        object.__setattr__(self.snapshot.workspace_binding, "remote_attempt_dir", "/wrong")
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_05_wrong_cwd_rejects_before_claim(self) -> None:
        object.__setattr__(
            self.snapshot, "cwd_binding", {"location_kind": "server", "path": "/wrong"}
        )
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_06_input_sha_mismatch_rejects_before_claim(self) -> None:
        self.input_bytes["input.xyz"] = b"wrong"
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)

    def test_07_scheduler_bytes_mismatch_rejects_before_claim(self) -> None:
        self.scheduler_bytes["xtb.pbs"] = b"wrong"
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_08_arbitrary_extra_stage_file_rejects(self) -> None:
        self.input_bytes["extra.xyz"] = b"extra"
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_09_prepared_input_cannot_masquerade(self) -> None:
        self.input_bytes = {"prepared-input": XYZ}
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_10_pbs_template_cannot_masquerade(self) -> None:
        self.scheduler_bytes = {"pbs-template": next(iter(self.scheduler_bytes.values()))}
        with self.assertRaises(transport.TransportBoundaryError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_11_submit_binds_exact_scheduler_script(self) -> None:
        self.execute()
        submit = next(request for operation, request in self.driver.calls if operation == "SUBMIT_QSUB_ONCE")
        payload = submit["payload"]
        self.assertIsInstance(payload, Mapping)
        assert isinstance(payload, Mapping)
        self.assertEqual(payload["scheduler_portable_name"], "xtb.pbs")
        stage_kinds = [
            request["payload"]["artifact_kind"]
            for operation, request in self.driver.calls
            if operation == "STAGE_EXACT_FILE"
        ]
        self.assertEqual(stage_kinds, ["program-input", "scheduler-script"])

    def test_12_submit_rejects_caller_job_shape(self) -> None:
        self.driver.submit_response = {"job_id": "123.server", "caller_job_id": "forged"}
        result = self.execute()
        self.assertEqual(result.outcome, "UNKNOWN")
        self.assertIsNone(result.job_authority)

    def test_13_core_winner_permits_first_effect(self) -> None:
        result = self.execute()
        self.assertIs(result.claim, core.SubmissionIntentClaim.WINNER)
        self.assertGreater(len(self.driver.calls), 0)
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_14_core_replay_makes_zero_driver_calls(self) -> None:
        first = self.execute()
        count = len(self.driver.calls)
        replay_driver = _Driver()
        replay = self.execute(replay_driver)
        self.assertIs(first.claim, core.SubmissionIntentClaim.WINNER)
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(replay_driver.calls, [])
        self.assertEqual(len(self.driver.calls), count)

    def test_15_prior_v30_claim_blocks_successor(self) -> None:
        self.store.record_submission_intent("attempt-1", "v30-intent")
        with self.assertRaises(core.RecordConflictError):
            self.execute()
        self.assertEqual(self.driver.calls, [])

    def test_16_prior_successor_claim_blocks_v30(self) -> None:
        self.store.record_submission_intent("attempt-1", self.snapshot.effect_intent_id)
        v30 = self.v30_snapshot()
        port = _V30Port()
        with self.assertRaises(core.RecordConflictError):
            execution.execute_once(
                self.store,
                snapshot=v30,
                current_profile=self.resolved(),
                prepared_input_bytes=GAUSSIAN_INPUT,
                pbs_template_bytes=PBS_TEMPLATE,
                confirmed_execution_snapshot_id=v30.execution_snapshot_id,
                port=port,
            )
        self.assertEqual(port.calls, 0)

    def test_17_ambiguous_qsub_sets_unknown_and_never_retries(self) -> None:
        self.driver.raise_operation = (
            "SUBMIT_QSUB_ONCE",
            _ProgramEffectUnknown("ambiguous"),
        )
        first = self.execute()
        self.assertEqual(first.outcome, "UNKNOWN")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)
        count = len(self.driver.calls)
        replay = self.execute()
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(self.driver.calls), count)
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.driver.calls), 1)

    def test_18_reconciliation_performs_zero_qsub(self) -> None:
        self.driver.raise_operation = (
            "SUBMIT_QSUB_ONCE",
            _ProgramEffectUnknown("ambiguous"),
        )
        self.execute()
        self.driver.raise_operation = None
        before = sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.driver.calls)
        result = _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        after = sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.driver.calls)
        self.assertEqual(result, {"outcome": "UNKNOWN"})
        self.assertEqual(before, after)

    def test_19_job_authority_requires_persisted_submit_receipt(self) -> None:
        with self.assertRaises(transport.TransportBoundaryError):
            _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )
        job = self.execute().job_authority
        self.assertIsNotNone(job)
        self.assertEqual(job["job_id"], "123.server")

    def test_20_stale_receipt_rejects(self) -> None:
        request = {
            "protocol": _PROTOCOL,
            "operation": "ALLOCATE_WORKSPACE",
            "binding": {},
            "payload": {},
        }
        payload = {
            "schema": _RECEIPT_TYPE,
            "protocol": _PROTOCOL,
            "attempt_id": "attempt-1",
            "program_execution_snapshot_id": "wrong",
            "effect_intent_id": self.snapshot.effect_intent_id,
            "effect_sequence": 1,
            "operation": "ALLOCATE_WORKSPACE",
            "request_sha256": sha256(transport._canonical.canonical_bytes(request)).hexdigest(),
            "request": request,
            "outcome": "SUCCEEDED",
            "response": {
                "remote_workspace": self.snapshot.workspace_binding.remote_attempt_dir,
                "workspace_physical_token": "token",
            },
        }
        self.store.append_observation(
            core.Observation(
                observation_id=_identity("effect-receipt", payload),
                attempt_id="attempt-1",
                observation_type=_RECEIPT_TYPE,
                data=payload,
            )
        )
        with self.assertRaises(transport.TransportBoundaryError):
            _load_receipts(self.store, self.snapshot)

    def test_21_query_wrong_job_authority_fails_closed(self) -> None:
        self.execute()
        self.driver.query_response = {"job_id": "other.server", "state": "running"}
        result = _query_program_scheduler(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertEqual(result, {"job_id": "123.server", "state": "unknown"})

    def test_22_required_output_missing_rejects_capture(self) -> None:
        self.driver.outputs.pop("xtbopt.xyz")
        self.execute()
        with self.assertRaisesRegex(transport.TransportBoundaryError, "required"):
            _capture_program_outputs(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )

    def test_23_optional_output_absence_follows_spec(self) -> None:
        spec = self.xtb_spec(task="single-point")
        self.snapshot = self.successor_snapshot(spec=spec)
        scheduler = self.snapshot.scheduler_artifacts[0]
        self.scheduler_bytes = {
            "xtb.pbs": str(scheduler["content_utf8"]).encode("utf-8")
        }
        self.driver.outputs = {"xtb.out": b"energy\n"}
        self.execute()
        capture = _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertEqual(tuple(item.presence for item in capture.artifacts), ("present", "absent"))
        self.assertEqual(capture.artifacts[-1].portable_name, "xtbopt.xyz")

    def test_24_undeclared_output_fetch_rejects(self) -> None:
        self.execute()
        self.driver.stat_override = {"portable_name": "undeclared.xyz", "presence": "absent"}
        with self.assertRaises(transport.TransportBoundaryError):
            _capture_program_outputs(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )

    def test_25_no_gaussian_filename_assumption(self) -> None:
        self.execute()
        self.driver.calls.clear()
        _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        names = [
            request["payload"]["portable_name"]
            for operation, request in self.driver.calls
            if operation == "STAT_EXACT_FILE"
        ]
        self.assertEqual(names, ["xtb.out", "xtbopt.xyz"])
        self.assertTrue(all(not name.endswith(".log") for name in names))

    def test_26_xtb_outputs_follow_spec(self) -> None:
        self.execute()
        capture = _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertEqual(
            tuple((item.logical_role, item.portable_name) for item in capture.artifacts),
            (("program-log", "xtb.out"), ("optimized-geometry", "xtbopt.xyz")),
        )

    def test_27_crest_outputs_follow_spec(self) -> None:
        spec = self.crest_spec()
        self.snapshot = self.successor_snapshot(spec=spec)
        scheduler = self.snapshot.scheduler_artifacts[0]
        self.input_bytes = {"seed.xyz": XYZ}
        self.scheduler_bytes = {"crest.pbs": str(scheduler["content_utf8"]).encode("utf-8")}
        self.driver.outputs = {
            "crest.out": b"crest complete\n",
            "crest_conformers.xyz": XYZ,
        }
        self.execute()
        capture = _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertEqual(
            tuple(item.portable_name for item in capture.artifacts),
            ("crest.out", "crest_conformers.xyz", "crest.energies"),
        )
        self.assertEqual(capture.artifacts[-1].presence, "absent")

    def test_28_output_sha_or_size_mismatch_rejects(self) -> None:
        self.execute()
        content = self.driver.outputs["xtb.out"]
        self.driver.fetch_override = {
            "portable_name": "xtb.out",
            "content": content,
            "sha256": "0" * 64,
            "size_bytes": len(content),
            "file_physical_token": "output-token-xtb.out",
        }
        with self.assertRaises(transport.TransportBoundaryError):
            _capture_program_outputs(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )

    def test_29_capture_identity_is_deterministic_and_bytes_are_retained(self) -> None:
        self.execute()
        capture = _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        payload = {
            "program_execution_snapshot_id": capture.program_execution_snapshot_id,
            "effect_intent_id": capture.effect_intent_id,
            "job_authority_id": capture.job_authority_id,
            "artifacts": tuple(item.identity_payload() for item in capture.artifacts),
        }
        self.assertEqual(capture.capture_authority_id, _identity("output-capture", payload))
        self.assertEqual(capture.artifacts[0].content, b"normal xtb\n")

    def test_30_public_and_v30_surfaces_are_unchanged(self) -> None:
        self.assertEqual(
            set(transport.__all__),
            {
                "TransportBoundaryError",
                "TransportStore",
                "ExactRemoteJobBinding",
                "SchedulerReadEvidence",
                "ExactArtifactRequest",
                "FetchedArtifact",
                "FetchedOutputCapture",
                "RTWinExecutionAdapter",
                "RTWinReadAdapter",
            },
        )
        self.assertEqual(_driver._BOOTSTRAP_PROTOCOL, "auto-g16-v3-rtwin-bootstrap/2")
        self.assertEqual(
            sha256(_bridge._BOOTSTRAP_SOURCE_BYTES).hexdigest(),
            "a90edecf87916c149e865256d69e6f57820cb29336380bd45d2107c7c00c64f0",
        )
        self.assertEqual(
            tuple(inspect.signature(execution.ExecutionPort.transfer_exact_bytes).parameters),
            ("self", "snapshot", "prepared_input_bytes", "pbs_template_bytes"),
        )
        self.assertEqual(
            tuple(field.name for field in fields(execution.RemoteEffectReceipt)),
            (
                "attempt_id",
                "execution_snapshot_id",
                "submission_intent_id",
                "effect_sequence",
                "effect_kind",
                "effect_state",
                "remote_workspace",
                "job_id",
                "details",
                "remote_effect_receipt_id",
            ),
        )

    def test_31_transport_tree_has_zero_forbidden_layer_imports(self) -> None:
        forbidden = {
            "auto_g16.core", "auto_g16.approval", "auto_g16.result",
            "auto_g16.review", "auto_g16.scientific_validation", "auto_g16.workflow",
        }
        transport_root = Path(transport.__file__).resolve().parent
        for path in transport_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            } | {
                str(node.module)
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module is not None
            }
            with self.subTest(path=path.name):
                self.assertTrue(forbidden.isdisjoint(imported))

    def test_32_program_runtime_is_private_and_not_exported(self) -> None:
        self.assertEqual(program_runtime.__all__, ())
        self.assertNotIn("program_runtime", execution.__all__)
        self.assertNotIn("_execute_program_once", execution.__all__)

    def test_33_transport_pure_preparation_makes_zero_driver_calls(self) -> None:
        binding = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        material = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )
        prepared = _prepare_program_effect_requests(binding, material)
        prepared.assert_closed()
        self.assertEqual(self.driver.calls, [])

    def test_34_malformed_transport_preparation_fails_before_claim(self) -> None:
        with patch.object(
            program_runtime._transport,
            "_prepare_program_effect_requests",
            side_effect=transport.TransportBoundaryError("malformed request"),
        ):
            with self.assertRaisesRegex(transport.TransportBoundaryError, "malformed"):
                self.execute()
        self.assertEqual(self.driver.calls, [])
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)

    def test_35_extra_transport_binding_field_rejects_purely(self) -> None:
        binding = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        material = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )
        with self.assertRaises(transport.TransportBoundaryError):
            _prepare_program_effect_requests({**binding, "extra": "forbidden"}, material)
        self.assertEqual(self.driver.calls, [])
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)

    def test_36_core_winner_precedes_first_driver_call(self) -> None:
        store = self.store

        class OrderingDriver(_Driver):
            def allocate_workspace(inner_self, request):
                self.assertIs(
                    store.attempt_state("attempt-1"),
                    core.AttemptState.SUBMISSION_INTENT_RECORDED,
                )
                return super().allocate_workspace(request)

        driver = OrderingDriver()
        result = self.execute(driver)
        self.assertIs(result.claim, core.SubmissionIntentClaim.WINNER)

    def test_37_execution_not_transport_owns_core_claim_text(self) -> None:
        execution_source = Path(program_runtime.__file__).read_text(encoding="utf-8")
        transport_source = (
            Path(transport.__file__).resolve().parent / "program.py"
        ).read_text(encoding="utf-8")
        self.assertIn("record_submission_intent", execution_source)
        self.assertNotIn("record_submission_intent", transport_source)

    def test_38_execution_not_transport_writes_observations(self) -> None:
        execution_source = Path(program_runtime.__file__).read_text(encoding="utf-8")
        transport_source = (
            Path(transport.__file__).resolve().parent / "program.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Observation(", execution_source)
        self.assertNotIn("Observation(", transport_source)

    def test_39_forged_receipt_identity_rejects(self) -> None:
        result = self.execute()
        original = result.receipts[0]
        forged = core.Observation(
            observation_id="forged-receipt",
            attempt_id=original.attempt_id,
            observation_type=original.observation_type,
            data=original.data,
        )
        other = self.root / "forged-receipt.sqlite3"
        store = core.SQLiteRuntimeStore(other)
        self.addCleanup(store.close)
        store.store_project(core.Project(project_id="project-1"))
        store.store_workflow_run(core.WorkflowRun(workflow_run_id="run-1", project_id="project-1", workflow_name="x3"))
        store.store_task(core.Task(task_id="task-1", workflow_run_id="run-1", task_kind="successor-program"))
        store.create_attempt(core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1))
        store.append_observation(forged)
        with self.assertRaises(transport.TransportBoundaryError):
            _load_receipts(store, self.snapshot)

    def test_40_forged_receipt_request_hash_rejects(self) -> None:
        result = self.execute()
        original = result.receipts[0]
        payload = dict(original.data)
        payload["request_sha256"] = "0" * 64
        store_path = self.root / "forged-hash.sqlite3"
        store = core.SQLiteRuntimeStore(store_path)
        self.addCleanup(store.close)
        store.store_project(core.Project(project_id="project-1"))
        store.store_workflow_run(core.WorkflowRun(workflow_run_id="run-1", project_id="project-1", workflow_name="x3"))
        store.store_task(core.Task(task_id="task-1", workflow_run_id="run-1", task_kind="successor-program"))
        store.create_attempt(core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1))
        store.append_observation(core.Observation(
            observation_id=_identity("effect-receipt", payload),
            attempt_id="attempt-1", observation_type=_RECEIPT_TYPE, data=payload,
        ))
        with self.assertRaises(transport.TransportBoundaryError):
            _load_receipts(store, self.snapshot)

    def test_41_claim_uses_exact_successor_effect_intent(self) -> None:
        self.execute()
        self.assertIs(
            self.store.record_submission_intent(
                self.snapshot.attempt_id, self.snapshot.effect_intent_id
            ),
            core.SubmissionIntentClaim.REPLAY,
        )
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent(self.snapshot.attempt_id, "other-intent")

    def test_42_replay_with_persisted_success_has_zero_new_receipts(self) -> None:
        first = self.execute()
        replay_driver = _Driver()
        replay = self.execute(replay_driver)
        self.assertEqual(replay.receipts, first.receipts)
        self.assertEqual(replay_driver.calls, [])

    def test_43_unknown_replay_cannot_reach_any_driver_operation(self) -> None:
        self.driver.raise_operation = (
            "SUBMIT_QSUB_ONCE", _ProgramEffectUnknown("ambiguous")
        )
        self.execute()
        replay_driver = _Driver()
        replay = self.execute(replay_driver)
        self.assertEqual(replay.outcome, "UNKNOWN")
        self.assertEqual(replay_driver.calls, [])

    def test_44_reconcile_requires_unknown_before_driver_call(self) -> None:
        self.execute()
        self.driver.calls.clear()
        with self.assertRaisesRegex(transport.TransportBoundaryError, "requires UNKNOWN"):
            _reconcile_program_submission(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )
        self.assertEqual(self.driver.calls, [])

    def test_45_transport_operation_vocabulary_is_exact_and_finite(self) -> None:
        self.assertEqual(
            program_runtime._transport._OPERATIONS,
            (
                "ALLOCATE_WORKSPACE", "STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE",
                "QUERY_SCHEDULER", "STAT_EXACT_FILE", "FETCH_EXACT_FILE",
                "RECONCILE_SUBMISSION",
            ),
        )
        with self.assertRaises(transport.TransportBoundaryError):
            program_runtime._transport._request("ARBITRARY_EFFECT", {}, {})
        binding = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        with self.assertRaises(transport.TransportBoundaryError):
            program_runtime._transport._request(
                "ALLOCATE_WORKSPACE", binding, {"extra": "forbidden"}
            )

    def test_46_reconciled_job_closes_core_to_submitted(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {
            "outcome": "SUCCEEDED",
            "job_id": "999.server",
        }
        response = _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertEqual(response, self.driver.reconcile_response)
        self.assertIs(
            self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED
        )
        self.assertIsNot(
            self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED
        )

    def test_47_reconciled_job_produces_dual_source_job_authority(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {
            "outcome": "SUCCEEDED",
            "job_id": "999.server",
        }
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        authority = _job_authority(
            self.store,
            self.snapshot,
            self.program_transport_store,
            self.driver,
        )
        self.assertEqual(authority["job_id"], "999.server")
        self.assertEqual(
            authority["establishing_operation"], "RECONCILE_SUBMISSION"
        )
        self.assertIn("physical_effect_authority_id", authority)

    def test_48_confirmed_no_submission_is_not_submitted(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {"outcome": "FAILED"}
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertIs(
            self.store.attempt_state("attempt-1"),
            core.AttemptState.NOT_SUBMITTED,
        )
        with self.assertRaises(transport.TransportBoundaryError):
            _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_49_unresolved_reconciliation_remains_unknown(self) -> None:
        self.begin_unknown_submission()
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertIs(
            self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN
        )
        with self.assertRaises(transport.TransportBoundaryError):
            _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_50_reconciliation_receipt_precedes_core_transition(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {
            "outcome": "SUCCEEDED",
            "job_id": "999.server",
        }
        original = self.store.reconcile_unknown

        def observed(
            attempt_id: str,
            observation_id: str,
            resolution: core.ReconciliationResolution,
        ) -> core.AttemptState:
            ids = {
                item.observation_id
                for item in self.store.observations_for_attempt(attempt_id)
            }
            self.assertIn(observation_id, ids)
            return original(attempt_id, observation_id, resolution)

        with patch.object(self.store, "reconcile_unknown", side_effect=observed):
            _reconcile_program_submission(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )

    def test_51_terminal_conflicting_reconciliation_rejects(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {"outcome": "FAILED"}
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        calls = len(self.driver.calls)
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "requires UNKNOWN"
        ):
            _reconcile_program_submission(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )
        self.assertEqual(len(self.driver.calls), calls)

    def test_52_fake_core_submit_without_physical_row_rejects(self) -> None:
        other = self.fresh_core_store("fake-submit")
        other.record_submission_intent("attempt-1", self.snapshot.effect_intent_id)
        other.record_submission_outcome(
            "attempt-1", self.snapshot.effect_intent_id,
            core.SubmissionOutcome.SUBMITTED,
        )
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        workspace = {
            "workspace_authority_id": "forged-workspace",
            "workspace_receipt_id": "forged-receipt",
            "workspace_physical_token": "forged-token",
        }
        request = program_runtime._transport._submit_request(
            base,
            workspace,
            scheduler_portable_name="xtb.pbs",
            scheduler_artifact_authority_id="forged-scheduler",
            program_input_artifact_authority_ids=("forged-input",),
        )
        payload = program_runtime._receipt_payload(
            self.snapshot,
            sequence=1,
            operation="SUBMIT_QSUB_ONCE",
            request=request,
            outcome="SUCCEEDED",
            response={"job_id": "forged.server"},
        )
        other.append_observation(
            core.Observation(
                observation_id=_identity("effect-receipt", payload),
                attempt_id="attempt-1",
                observation_type=_RECEIPT_TYPE,
                data=payload,
            )
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "predecessor|physical-effect"
        ):
            _job_authority(
                other,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_53_fake_reconciliation_without_physical_row_rejects(self) -> None:
        self.begin_unknown_submission()
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        receipts = _load_receipts(
            self.store, self.snapshot, self.program_transport_store, base
        )
        submit = next(
            item for item in receipts
            if item.data["operation"] == "SUBMIT_QSUB_ONCE"
        )
        request = program_runtime._transport._reconciliation_request(
            base, submit_receipt_id=submit.observation_id
        )
        payload = program_runtime._receipt_payload(
            self.snapshot,
            sequence=len(receipts) + 1,
            operation="RECONCILE_SUBMISSION",
            request=request,
            outcome="SUCCEEDED",
            response={"outcome": "SUCCEEDED", "job_id": "forged.server"},
        )
        observation = core.Observation(
            observation_id=_identity("effect-receipt", payload),
            attempt_id="attempt-1",
            observation_type=_RECEIPT_TYPE,
            data=payload,
        )
        self.store.append_observation(observation)
        self.store.reconcile_unknown(
            "attempt-1",
            observation.observation_id,
            core.ReconciliationResolution.SUBMITTED,
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "physical-effect"
        ):
            _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_54_persisted_request_mutations_reject(self) -> None:
        mutations = {
            "protocol": lambda payload: payload["request"].__setitem__(
                "protocol", "forged-protocol"
            ),
            "binding": lambda payload: payload["request"]["binding"].__setitem__(
                "remote_workspace", "/forged"
            ),
            "operation-payload": lambda payload: payload["request"].__setitem__(
                "operation", "QUERY_SCHEDULER"
            ),
            "scheduler-script": lambda payload: payload["request"][
                "payload"
            ].__setitem__("scheduler_portable_name", "other.pbs"),
        }
        for offset, (name, mutate) in enumerate(mutations.items()):
            with self.subTest(name=name):
                def closed_mutation(payload: dict[str, object]) -> None:
                    mutate(payload)
                    request = payload["request"]
                    assert isinstance(request, Mapping)
                    payload["request_sha256"] = sha256(
                        transport._canonical.canonical_bytes(request)
                    ).hexdigest()

                other, _payload = self.clone_receipts_with_mutation(
                    f"mutated-{offset}", 3, closed_mutation
                )
                base = program_runtime._snapshot_binding(
                    self.snapshot, self.program_transport_store, self.driver
                )
                with self.assertRaises(transport.TransportBoundaryError):
                    _load_receipts(
                        other,
                        self.snapshot,
                        self.program_transport_store,
                        base,
                    )

    def test_55_core_and_physical_job_ids_must_match(self) -> None:
        def mutate(payload: dict[str, object]) -> None:
            response = payload["response"]
            assert isinstance(response, dict)
            response["job_id"] = "other.server"

        other, _payload = self.clone_receipts_with_mutation(
            "job-id-mismatch", 3, mutate
        )
        other.record_submission_intent("attempt-1", self.snapshot.effect_intent_id)
        other.record_submission_outcome(
            "attempt-1", self.snapshot.effect_intent_id,
            core.SubmissionOutcome.SUBMITTED,
        )
        with self.assertRaises(transport.TransportBoundaryError):
            _job_authority(
                other,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_56_store_swap_rejects_query_and_capture(self) -> None:
        self.execute()
        other = self.fresh_program_store("other-program-store")
        with self.assertRaises(transport.TransportBoundaryError):
            _query_program_scheduler(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=other,
                driver=self.driver,
            )
        with self.assertRaises(transport.TransportBoundaryError):
            _capture_program_outputs(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=other,
                driver=self.driver,
            )

    def test_57_runtime_attestation_drift_rejects(self) -> None:
        self.execute()
        changed = dict(self.driver.runtime_qualification)
        changed["deployment_id"] = "drifted-deployment"
        self.driver.runtime_qualification = changed
        with self.assertRaises(transport.TransportBoundaryError):
            _query_program_scheduler(
                self.store,
                snapshot=self.snapshot,
                program_transport_store=self.program_transport_store,
                driver=self.driver,
            )

    def test_58_direct_submit_is_dual_source_closed(self) -> None:
        result = self.execute()
        authority = result.job_authority
        assert authority is not None
        self.assertEqual(
            authority["program_transport_store_id"],
            self.program_transport_store.program_transport_store_id,
        )
        self.assertEqual(
            authority["store_instance_id"],
            self.program_transport_store.store_instance_id,
        )
        self.assertEqual(authority["establishing_operation"], "SUBMIT_QSUB_ONCE")
        self.assertIn("physical_effect_authority_id", authority)

    def test_59_query_stat_and_fetch_use_dual_source_job_authority(self) -> None:
        self.execute()
        _query_program_scheduler(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        capture = _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        self.assertTrue(capture.artifacts)
        requests = [request for _operation, request in self.driver.calls]
        for request in requests:
            if request["operation"] in {
                "QUERY_SCHEDULER", "STAT_EXACT_FILE", "FETCH_EXACT_FILE"
            }:
                self.assertEqual(
                    request["binding"]["job_authority_id"],
                    capture.job_authority_id,
                )

    def test_60_successor_store_is_private_and_v30_inventory_is_unchanged(self) -> None:
        self.assertEqual(
            _PROGRAM_STORE_SCHEMA, "auto-g16-v31-program-transport-store/1"
        )
        self.assertEqual(
            _PROGRAM_STORE_TABLES,
            (
                "program_transport_meta",
                "program_runtime_attestation",
                "program_effect_physical_authority",
            ),
        )
        self.assertEqual(
            transport.models._TABLES,
            (
                "transport_meta", "transport_runtime_attestation",
                "transport_workspace_authority", "transport_artifact_authority",
                "transport_job_authority", "transport_receipt_binding",
            ),
        )
        self.assertNotIn("_ProgramTransportStore", transport.__all__)

    def test_61_successor_physical_authority_reopens_exactly(self) -> None:
        expected = self.execute().job_authority
        path = self.program_transport_store._path
        root = self.program_transport_store._root
        store_id = self.program_transport_store.program_transport_store_id
        instance_id = self.program_transport_store.store_instance_id
        self.program_transport_store.close()
        reopened = _ProgramTransportStore.open_existing(
            path, approved_root=root
        )
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.program_transport_store_id, store_id)
        self.assertEqual(reopened.store_instance_id, instance_id)
        self.assertEqual(
            _job_authority(self.store, self.snapshot, reopened, self.driver),
            expected,
        )

    def test_62_ambiguous_submit_physical_row_cannot_be_rewritten_successful(self) -> None:
        self.begin_unknown_submission()
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        submit = next(
            item
            for item in _load_receipts(
                self.store, self.snapshot, self.program_transport_store, base
            )
            if item.data["operation"] == "SUBMIT_QSUB_ONCE"
        )
        request = submit.data["request"]
        assert isinstance(request, Mapping)
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "conflicting"
        ):
            self.program_transport_store.record_effect(
                binding=request["binding"],
                request=request,
                classification="SUCCEEDED",
                response={"job_id": "forged.server"},
                job_id="forged.server",
            )

    def test_63_stage_without_allocate_predecessor_rejects(self) -> None:
        store, program_store, driver, base = self.manual_context("stage-no-allocate")
        declaration = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )[0][0]
        forged_workspace = {
            "workspace_authority_id": "forged-workspace",
            "workspace_receipt_id": "forged-receipt",
            "workspace_physical_token": "forged-token",
        }
        request = program_runtime._transport._stage_request(
            base, forged_workspace, declaration
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={**dict(declaration), "artifact_physical_token": "forged"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "ALLOCATE predecessor"
        ):
            _load_receipts(store, self.snapshot, program_store, base)
        self.assertEqual(driver.calls, [])

    def test_64_stage_forged_or_foreign_workspace_authority_rejects(self) -> None:
        for case in ("forged", "foreign-snapshot"):
            with self.subTest(case=case):
                store, program_store, driver, base = self.manual_context(
                    f"stage-{case}"
                )
                workspace = self.append_allocate(store, program_store, base)
                if case == "forged":
                    supplied = {**workspace, "workspace_authority_id": "forged"}
                else:
                    other_snapshot = self.successor_snapshot(
                        spec=self.xtb_spec(task="single-point")
                    )
                    other_store = self.fresh_core_store("foreign-snapshot-core")
                    other_program = self.fresh_program_store(
                        "foreign-snapshot-physical"
                    )
                    other_base = program_runtime._snapshot_binding(
                        other_snapshot, other_program, driver
                    )
                    other_request = program_runtime._transport._request(
                        "ALLOCATE_WORKSPACE", other_base, {}
                    )
                    other_response = {
                        "remote_workspace": (
                            other_snapshot.workspace_binding.remote_attempt_dir
                        ),
                        "workspace_physical_token": "foreign-token",
                    }
                    other_receipt = self.append_dual_source_receipt(
                        other_store,
                        other_program,
                        snapshot=other_snapshot,
                        request=other_request,
                        outcome="SUCCEEDED",
                        response=other_response,
                    )
                    supplied = program_runtime._workspace_authority(
                        other_snapshot, other_receipt, other_program
                    )
                declaration = program_runtime._stage_material(
                    self.snapshot,
                    input_bytes=self.input_bytes,
                    scheduler_artifact_bytes=self.scheduler_bytes,
                )[0][0]
                request = program_runtime._transport._stage_request(
                    base, supplied, declaration
                )
                self.append_dual_source_receipt(
                    store,
                    program_store,
                    snapshot=self.snapshot,
                    request=request,
                    outcome="SUCCEEDED",
                    response={
                        **dict(declaration),
                        "artifact_physical_token": "forged-stage-token",
                    },
                )
                with self.assertRaisesRegex(
                    transport.TransportBoundaryError, "predecessor authority"
                ):
                    _load_receipts(store, self.snapshot, program_store, base)

    def test_65_submit_requires_both_stage_kinds_and_exact_authorities(self) -> None:
        cases = ("missing-input", "missing-scheduler", "forged-authority")
        for case in cases:
            with self.subTest(case=case):
                store, program_store, _driver, base = self.manual_context(
                    f"submit-{case}"
                )
                workspace = self.append_allocate(store, program_store, base)
                material = program_runtime._stage_material(
                    self.snapshot,
                    input_bytes=self.input_bytes,
                    scheduler_artifact_bytes=self.scheduler_bytes,
                )
                declarations = {
                    item[0]["artifact_kind"]: item[0] for item in material
                }
                authorities = {}
                for kind, declaration in declarations.items():
                    if (
                        (case == "missing-input" and kind == "program-input")
                        or (
                            case == "missing-scheduler"
                            and kind == "scheduler-script"
                        )
                    ):
                        continue
                    authorities[kind] = self.append_stage(
                        store, program_store, base, workspace, declaration
                    )
                scheduler_id = str(
                    authorities.get("scheduler-script", {}).get(
                        "artifact_authority_id", "missing-scheduler"
                    )
                )
                input_id = str(
                    authorities.get("program-input", {}).get(
                        "artifact_authority_id", "missing-input"
                    )
                )
                if case == "forged-authority":
                    input_id = "forged-input-authority"
                request = program_runtime._transport._submit_request(
                    base,
                    workspace,
                    scheduler_portable_name="xtb.pbs",
                    scheduler_artifact_authority_id=scheduler_id,
                    program_input_artifact_authority_ids=(input_id,),
                )
                self.append_dual_source_receipt(
                    store,
                    program_store,
                    snapshot=self.snapshot,
                    request=request,
                    outcome="SUCCEEDED",
                    response={"job_id": "forged.server"},
                    job_id="forged.server",
                )
                with self.assertRaises(transport.TransportBoundaryError):
                    _load_receipts(store, self.snapshot, program_store, base)

    def test_66_planned_attempt_query_rejects_self_consistent_fake_job(self) -> None:
        store, program_store, _driver, base = self.manual_context("planned-query")
        request = program_runtime._transport._scheduler_request(
            base, job_authority_id="fake-job-authority", job_id="fake.server"
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={"job_id": "fake.server", "state": "running"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "submitted-compatible"
        ):
            _load_receipts(store, self.snapshot, program_store, base)

    def test_67_query_rejects_job_authority_from_another_store(self) -> None:
        own = self.execute().job_authority
        assert own is not None
        other_store, other_program, other_driver, other_base = self.manual_context(
            "foreign-job"
        )
        foreign = self.append_valid_direct_submit(
            other_store, other_program, other_driver, other_base
        )
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        request = program_runtime._transport._scheduler_request(
            base,
            job_authority_id=str(foreign["job_authority_id"]),
            job_id=str(foreign["job_id"]),
        )
        self.append_dual_source_receipt(
            self.store,
            self.program_transport_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={"job_id": foreign["job_id"], "state": "running"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "predecessor authority"
        ):
            _load_receipts(
                self.store,
                self.snapshot,
                self.program_transport_store,
                base,
            )

    def test_68_query_rejects_core_only_job_receipt(self) -> None:
        store, program_store, driver, base = self.manual_context("core-only-job")
        self.append_valid_direct_submit(
            store, program_store, driver, base, submit_physical=False
        )
        request = program_runtime._transport._scheduler_request(
            base, job_authority_id="fake-job-authority", job_id="manual.server"
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={"job_id": "manual.server", "state": "running"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "physical-effect"
        ):
            _load_receipts(store, self.snapshot, program_store, base)

    def test_69_query_rejects_physical_only_job_row(self) -> None:
        store, program_store, _driver, base = self.manual_context("physical-only-job")
        store.record_submission_intent(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )
        workspace = self.append_allocate(store, program_store, base)
        material = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )
        authorities = tuple(
            self.append_stage(store, program_store, base, workspace, item[0])
            for item in material
        )
        scheduler = next(
            item for item in authorities
            if item["artifact_kind"] == "scheduler-script"
        )
        inputs = tuple(
            item for item in authorities if item["artifact_kind"] == "program-input"
        )
        submit_request = program_runtime._transport._submit_request(
            base,
            workspace,
            scheduler_portable_name="xtb.pbs",
            scheduler_artifact_authority_id=str(
                scheduler["artifact_authority_id"]
            ),
            program_input_artifact_authority_ids=tuple(
                str(item["artifact_authority_id"]) for item in inputs
            ),
        )
        program_store.record_effect(
            binding=submit_request["binding"],
            request=submit_request,
            classification="SUCCEEDED",
            response={"job_id": "physical.server"},
            job_id="physical.server",
        )
        store.record_submission_outcome(
            self.snapshot.attempt_id,
            self.snapshot.effect_intent_id,
            core.SubmissionOutcome.SUBMITTED,
        )
        query = program_runtime._transport._scheduler_request(
            base,
            job_authority_id="physical-only-job-authority",
            job_id="physical.server",
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=query,
            outcome="SUCCEEDED",
            response={"job_id": "physical.server", "state": "running"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "job-establishing receipt"
        ):
            _load_receipts(store, self.snapshot, program_store, base)

    def test_70_stat_rejects_undeclared_output_or_forged_job(self) -> None:
        for case in ("undeclared", "forged-job"):
            with self.subTest(case=case):
                store, program_store, driver, base = self.manual_context(
                    f"stat-{case}"
                )
                job = self.append_valid_direct_submit(
                    store, program_store, driver, base
                )
                declaration = (
                    {
                        "logical_role": "other",
                        "portable_name": "other.out",
                        "format": "other",
                    }
                    if case == "undeclared"
                    else self.snapshot.program_execution_spec.required_outputs[0]
                )
                request = program_runtime._transport._stat_request(
                    base,
                    job_authority_id=(
                        "forged-job" if case == "forged-job"
                        else str(job["job_authority_id"])
                    ),
                    declaration=declaration,
                )
                self.append_dual_source_receipt(
                    store,
                    program_store,
                    snapshot=self.snapshot,
                    request=request,
                    outcome="SUCCEEDED",
                    response={
                        "portable_name": declaration["portable_name"],
                        "presence": "absent",
                    },
                )
                with self.assertRaises(transport.TransportBoundaryError):
                    _load_receipts(
                        store,
                        self.snapshot,
                        program_store,
                        base,
                    )

    def test_71_fetch_without_stat_rejects(self) -> None:
        job = self.execute().job_authority
        assert job is not None
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        declaration = self.snapshot.program_execution_spec.required_outputs[0]
        request = program_runtime._transport._fetch_request(
            base,
            job_authority_id=str(job["job_authority_id"]),
            declaration=declaration,
            announced_size=7,
            file_physical_token="forged-token",
            stat_receipt_id="missing-stat",
        )
        self.append_dual_source_receipt(
            self.store,
            self.program_transport_store,
            snapshot=self.snapshot,
            request=request,
            outcome="SUCCEEDED",
            response={
                "portable_name": declaration["portable_name"],
                "sha256": "0" * 64,
                "size_bytes": 7,
                "file_physical_token": "forged-token",
            },
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "STAT predecessor"
        ):
            _load_receipts(
                self.store, self.snapshot, self.program_transport_store, base
            )

    def test_72_fetch_rejects_other_output_stat_or_forged_stat_values(self) -> None:
        for case in ("other-output", "wrong-size", "wrong-token"):
            with self.subTest(case=case):
                store, program_store, driver, base = self.manual_context(
                    f"fetch-{case}"
                )
                job = self.append_valid_direct_submit(
                    store, program_store, driver, base
                )
                first, second = self.snapshot.program_execution_spec.required_outputs
                stat_declaration = first
                fetch_declaration = second if case == "other-output" else first
                stat_request = program_runtime._transport._stat_request(
                    base,
                    job_authority_id=str(job["job_authority_id"]),
                    declaration=stat_declaration,
                )
                stat = self.append_dual_source_receipt(
                    store,
                    program_store,
                    snapshot=self.snapshot,
                    request=stat_request,
                    outcome="SUCCEEDED",
                    response={
                        "portable_name": stat_declaration["portable_name"],
                        "presence": "present",
                        "size_bytes": 7,
                        "file_physical_token": "stat-token",
                    },
                )
                request = program_runtime._transport._fetch_request(
                    base,
                    job_authority_id=str(job["job_authority_id"]),
                    declaration=fetch_declaration,
                    announced_size=8 if case == "wrong-size" else 7,
                    file_physical_token=(
                        "wrong-token" if case == "wrong-token" else "stat-token"
                    ),
                    stat_receipt_id=stat.observation_id,
                )
                self.append_dual_source_receipt(
                    store,
                    program_store,
                    snapshot=self.snapshot,
                    request=request,
                    outcome="SUCCEEDED",
                    response={
                        "portable_name": fetch_declaration["portable_name"],
                        "sha256": "0" * 64,
                        "size_bytes": request["payload"]["expected_size_bytes"],
                        "file_physical_token": request["payload"][
                            "expected_file_physical_token"
                        ],
                    },
                )
                with self.assertRaises(transport.TransportBoundaryError):
                    _load_receipts(
                        store,
                        self.snapshot,
                        program_store,
                        base,
                    )

    def test_73_reconcile_rejects_allocate_receipt_as_submit_source(self) -> None:
        self.begin_unknown_submission()
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        allocate = _load_receipts(
            self.store, self.snapshot, self.program_transport_store, base
        )[0]
        request = program_runtime._transport._reconciliation_request(
            base, submit_receipt_id=allocate.observation_id
        )
        self.append_dual_source_receipt(
            self.store,
            self.program_transport_store,
            snapshot=self.snapshot,
            request=request,
            outcome="UNKNOWN",
            response={"outcome": "UNKNOWN"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "predecessor authority"
        ):
            _load_receipts(
                self.store, self.snapshot, self.program_transport_store, base
            )

    def test_74_reconcile_rejects_stage_receipt_as_submit_source(self) -> None:
        self.begin_unknown_submission()
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        stage = next(
            item
            for item in _load_receipts(
                self.store, self.snapshot, self.program_transport_store, base
            )
            if item.data["operation"] == "STAGE_EXACT_FILE"
        )
        request = program_runtime._transport._reconciliation_request(
            base, submit_receipt_id=stage.observation_id
        )
        self.append_dual_source_receipt(
            self.store,
            self.program_transport_store,
            snapshot=self.snapshot,
            request=request,
            outcome="UNKNOWN",
            response={"outcome": "UNKNOWN"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "predecessor authority"
        ):
            _load_receipts(
                self.store, self.snapshot, self.program_transport_store, base
            )

    def test_75_reconcile_without_ambiguous_submit_rejects(self) -> None:
        store, program_store, _driver, base = self.manual_context("no-ambiguous")
        allocate = self.append_allocate(store, program_store, base)
        store.record_submission_intent(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )
        store.record_submission_outcome(
            self.snapshot.attempt_id,
            self.snapshot.effect_intent_id,
            core.SubmissionOutcome.UNKNOWN,
        )
        request = program_runtime._transport._reconciliation_request(
            base, submit_receipt_id=str(allocate["workspace_receipt_id"])
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=request,
            outcome="UNKNOWN",
            response={"outcome": "UNKNOWN"},
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "UNKNOWN submit predecessor"
        ):
            _load_receipts(store, self.snapshot, program_store, base)

    def test_76_all_seven_operations_reclose_from_persisted_authority(self) -> None:
        self.execute()
        _query_program_scheduler(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        _capture_program_outputs(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        direct_operations = {
            item.data["operation"]
            for item in _load_receipts(
                self.store, self.snapshot, self.program_transport_store, base
            )
        }
        self.assertEqual(
            direct_operations,
            {
                "ALLOCATE_WORKSPACE",
                "STAGE_EXACT_FILE",
                "SUBMIT_QSUB_ONCE",
                "QUERY_SCHEDULER",
                "STAT_EXACT_FILE",
                "FETCH_EXACT_FILE",
            },
        )

        store, program_store, driver, base = self.manual_context(
            "all-operations-reconcile"
        )
        store.record_submission_intent(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )
        workspace = self.append_allocate(store, program_store, base)
        material = program_runtime._stage_material(
            self.snapshot,
            input_bytes=self.input_bytes,
            scheduler_artifact_bytes=self.scheduler_bytes,
        )
        authorities = tuple(
            self.append_stage(store, program_store, base, workspace, item[0])
            for item in material
        )
        scheduler = next(
            item for item in authorities
            if item["artifact_kind"] == "scheduler-script"
        )
        inputs = tuple(
            item for item in authorities if item["artifact_kind"] == "program-input"
        )
        submit_request = program_runtime._transport._submit_request(
            base,
            workspace,
            scheduler_portable_name="xtb.pbs",
            scheduler_artifact_authority_id=str(
                scheduler["artifact_authority_id"]
            ),
            program_input_artifact_authority_ids=tuple(
                str(item["artifact_authority_id"]) for item in inputs
            ),
        )
        self.append_dual_source_receipt(
            store,
            program_store,
            snapshot=self.snapshot,
            request=submit_request,
            outcome="UNKNOWN",
            response={"reason": "ambiguous-operation-outcome"},
        )
        store.record_submission_outcome(
            self.snapshot.attempt_id,
            self.snapshot.effect_intent_id,
            core.SubmissionOutcome.UNKNOWN,
        )
        _reconcile_program_submission(
            store,
            snapshot=self.snapshot,
            program_transport_store=program_store,
            driver=driver,
        )
        operations = {
            item.data["operation"]
            for item in _load_receipts(
                store, self.snapshot, program_store, base
            )
        }
        self.assertIn("RECONCILE_SUBMISSION", operations)


    def test_77_product_uses_zero_private_core_schema_access(self) -> None:
        source = Path(program_runtime.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "._db(",
            "auto_g16.core.store",
            "submission_outcomes",
            "reconciliations",
            "SELECT",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_78_planned_replay_proof_cannot_claim_intent(self) -> None:
        with patch.object(
            self.store,
            "record_submission_intent",
            wraps=self.store.record_submission_intent,
        ) as claim:
            with self.assertRaisesRegex(
                transport.TransportBoundaryError, "PLANNED effect intent"
            ):
                _assert_effect_intent_replay(self.store, self.snapshot)
        claim.assert_not_called()
        self.assertIs(
            self.store.attempt_state(self.snapshot.attempt_id),
            core.AttemptState.PLANNED,
        )

    def test_79_nonplanned_exact_effect_intent_replays_publicly(self) -> None:
        self.assertIs(
            self.store.record_submission_intent(
                self.snapshot.attempt_id, self.snapshot.effect_intent_id
            ),
            core.SubmissionIntentClaim.WINNER,
        )
        before = self.store.attempt_state(self.snapshot.attempt_id)
        with patch.object(
            self.store,
            "record_submission_intent",
            wraps=self.store.record_submission_intent,
        ) as claim:
            _assert_effect_intent_replay(self.store, self.snapshot)
        claim.assert_called_once_with(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )
        self.assertIs(self.store.attempt_state(self.snapshot.attempt_id), before)

    def test_80_different_existing_effect_intent_replay_rejects(self) -> None:
        self.store.record_submission_intent(
            self.snapshot.attempt_id, "different-effect-intent"
        )
        before = self.store.attempt_state(self.snapshot.attempt_id)
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "does not replay"
        ):
            _assert_effect_intent_replay(self.store, self.snapshot)
        self.assertIs(self.store.attempt_state(self.snapshot.attempt_id), before)

    def test_81_reconciled_submit_retains_historical_unknown_predecessor(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {
            "outcome": "SUCCEEDED",
            "job_id": "999.server",
        }
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        receipts = _load_receipts(
            self.store,
            self.snapshot,
            self.program_transport_store,
            base,
        )
        predecessor = _reconstruct_ambiguous_submit(
            self.store,
            self.snapshot,
            self.program_transport_store,
            base,
            receipts,
        )
        self.assertEqual(predecessor.data["operation"], "SUBMIT_QSUB_ONCE")
        self.assertEqual(predecessor.data["outcome"], "UNKNOWN")
        self.assertIs(
            self.store.attempt_state(self.snapshot.attempt_id),
            core.AttemptState.SUBMITTED,
        )

    def test_82_direct_job_authority_uses_public_effect_intent_replay(self) -> None:
        self.execute()
        with patch.object(
            self.store,
            "record_submission_intent",
            wraps=self.store.record_submission_intent,
        ) as claim:
            authority = _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )
        self.assertEqual(authority["job_id"], "123.server")
        claim.assert_called_once_with(
            self.snapshot.attempt_id, self.snapshot.effect_intent_id
        )

    def test_83_reconciled_job_replays_terminal_core_reconciliation(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {
            "outcome": "SUCCEEDED",
            "job_id": "999.server",
        }
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        receipt = next(
            item
            for item in self.store.observations_for_attempt(
                self.snapshot.attempt_id
            )
            if item.observation_type == _RECEIPT_TYPE
            and item.data["operation"] == "RECONCILE_SUBMISSION"
        )
        with patch.object(
            self.store,
            "reconcile_unknown",
            wraps=self.store.reconcile_unknown,
        ) as reconcile:
            authority = _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )
        self.assertEqual(authority["job_id"], "999.server")
        reconcile.assert_called_once_with(
            self.snapshot.attempt_id,
            receipt.observation_id,
            core.ReconciliationResolution.SUBMITTED,
        )

    def test_84_reconciled_job_authority_read_is_nonmutating(self) -> None:
        self.begin_unknown_submission()
        self.driver.reconcile_response = {
            "outcome": "SUCCEEDED",
            "job_id": "999.server",
        }
        _reconcile_program_submission(
            self.store,
            snapshot=self.snapshot,
            program_transport_store=self.program_transport_store,
            driver=self.driver,
        )
        state_before = self.store.attempt_state(self.snapshot.attempt_id)
        reconciliation_before = tuple(
            tuple(row)
            for row in self.store._db().execute(
                "SELECT observation_id,resolution FROM reconciliations "
                "WHERE attempt_id=? ORDER BY observation_id",
                (self.snapshot.attempt_id,),
            ).fetchall()
        )
        _job_authority(
            self.store,
            self.snapshot,
            self.program_transport_store,
            self.driver,
        )
        reconciliation_after = tuple(
            tuple(row)
            for row in self.store._db().execute(
                "SELECT observation_id,resolution FROM reconciliations "
                "WHERE attempt_id=? ORDER BY observation_id",
                (self.snapshot.attempt_id,),
            ).fetchall()
        )
        self.assertIs(
            self.store.attempt_state(self.snapshot.attempt_id), state_before
        )
        self.assertEqual(reconciliation_after, reconciliation_before)

    def test_85_reconciled_receipt_without_terminal_core_record_rejects(self) -> None:
        store, program_store, driver, base = self.manual_context(
            "missing-terminal-reconciliation"
        )
        submit = self.append_unknown_submit(store, program_store, base)
        store.record_submission_outcome(
            self.snapshot.attempt_id,
            self.snapshot.effect_intent_id,
            core.SubmissionOutcome.SUBMITTED,
        )
        self.append_successful_reconciliation(
            store, program_store, base, submit
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "does not replay"
        ):
            _job_authority(store, self.snapshot, program_store, driver)

    def test_86_reconciled_receipt_with_wrong_observation_rejects(self) -> None:
        self.begin_unknown_submission()
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        submit = next(
            item
            for item in _load_receipts(
                self.store,
                self.snapshot,
                self.program_transport_store,
                base,
            )
            if item.data["operation"] == "SUBMIT_QSUB_ONCE"
        )
        self.append_successful_reconciliation(
            self.store, self.program_transport_store, base, submit
        )
        alternate = core.Observation(
            observation_id="alternate-reconciliation-observation",
            attempt_id=self.snapshot.attempt_id,
            observation_type="synthetic-reconciliation-proof",
            data={"resolution": "SUBMITTED"},
        )
        self.store.append_observation(alternate)
        self.store.reconcile_unknown(
            self.snapshot.attempt_id,
            alternate.observation_id,
            core.ReconciliationResolution.SUBMITTED,
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "does not replay"
        ):
            _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_87_reconciled_receipt_with_wrong_resolution_rejects(self) -> None:
        self.begin_unknown_submission()
        base = program_runtime._snapshot_binding(
            self.snapshot, self.program_transport_store, self.driver
        )
        submit = next(
            item
            for item in _load_receipts(
                self.store,
                self.snapshot,
                self.program_transport_store,
                base,
            )
            if item.data["operation"] == "SUBMIT_QSUB_ONCE"
        )
        receipt = self.append_successful_reconciliation(
            self.store, self.program_transport_store, base, submit
        )
        self.store.reconcile_unknown(
            self.snapshot.attempt_id,
            receipt.observation_id,
            core.ReconciliationResolution.NOT_SUBMITTED,
        )
        with self.assertRaisesRegex(
            transport.TransportBoundaryError, "submitted-compatible"
        ):
            _job_authority(
                self.store,
                self.snapshot,
                self.program_transport_store,
                self.driver,
            )

    def test_88_unknown_job_read_cannot_create_terminal_reconciliation(self) -> None:
        self.begin_unknown_submission()
        state_before = self.store.attempt_state(self.snapshot.attempt_id)
        reconciliation_before = tuple(
            tuple(row)
            for row in self.store._db().execute(
                "SELECT observation_id,resolution FROM reconciliations "
                "WHERE attempt_id=? ORDER BY observation_id",
                (self.snapshot.attempt_id,),
            ).fetchall()
        )
        with patch.object(
            self.store,
            "reconcile_unknown",
            wraps=self.store.reconcile_unknown,
        ) as reconcile:
            with self.assertRaisesRegex(
                transport.TransportBoundaryError, "submitted-compatible"
            ):
                _job_authority(
                    self.store,
                    self.snapshot,
                    self.program_transport_store,
                    self.driver,
                )
        reconcile.assert_not_called()
        reconciliation_after = tuple(
            tuple(row)
            for row in self.store._db().execute(
                "SELECT observation_id,resolution FROM reconciliations "
                "WHERE attempt_id=? ORDER BY observation_id",
                (self.snapshot.attempt_id,),
            ).fetchall()
        )
        self.assertIs(
            self.store.attempt_state(self.snapshot.attempt_id), state_before
        )
        self.assertEqual(reconciliation_after, reconciliation_before)


if __name__ == "__main__":
    unittest.main()
