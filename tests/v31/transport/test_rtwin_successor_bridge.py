"""Production bridge composition with deterministic responses and zero processes."""

from __future__ import annotations

import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from dataclasses import fields
from hashlib import sha256
import io
import inspect
import json
from pathlib import Path
import sqlite3
from threading import Barrier
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import Mock, patch

import auto_g16.approval as approval
import auto_g16.core as core
import auto_g16.execution as execution
from auto_g16.execution import program as preparation, program_runtime as runtime
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal, _ProjectProvisioningService, _ProjectAttestor
from auto_g16.transport import _bridge, _driver, _program_rtwin as bridge, program
from auto_g16.transport._canonical import TransportBoundaryError, canonical_json_bytes
from tests.v3.execution import test_v31_lane_a as lane
from tests.v3.transport import _fixtures as v30
from tests.v31.transport import test_program_composition as composition


def directory_token(path: str, inode: int = 50) -> str:
    return base64.b64encode(canonical_json_bytes(["v31-directory/1", path, [[1, inode + i] for i in range(len(path.split("/")))]] )).decode("ascii")


class _Wire:
    """Offline wire peer; validates commands/frames, never creates a process."""

    def __init__(self) -> None:
        self.calls = []
        self.project_state = "ABSENT"
        self.parent = directory_token("/home/user100/SDL")
        self.project = directory_token("/home/user100/SDL/project-1")
        self.mkdir_count = 0
        self.raise_after_mkdir = False
        self.replace_parent = False
        self.fail_operation = None
        self.scheduler = (0, b"Job Id: 123.server\n    job_state = C\n    resources_used.cput = 00:00:01\n    Resource_List.nodes = 1:ppn=8\n    exit_status = 0\n", b"")
        self.outputs = {"xtb.out": b"exact xtb output\n", "xtbopt.xyz": lane.XYZ}

    def run(self, scope, invocation):
        command, frame = bridge._prepare_program_invocation(scope, invocation)
        assert command[0] == "/usr/bin/ssh"
        assert command[1] == "-F"
        assert command[3:5] == ("--", "auto-g16-option1-final-server-v1")
        assert "powershell" not in command[-1].lower()
        request = _bridge._decode_frame(frame, cap=invocation.operation.stdin_cap, field="test request")
        op = request["operation"]
        self.calls.append((op, request))
        if op == self.fail_operation:
            return b"", b"", None, "timeout", False, False
        b = request["binding"]
        if op == "OBSERVE_PROJECT":
            result = {"state": self.project_state, "parent_physical_identity": self.parent, "project_physical_identity": self.project if self.project_state == "EXISTING" else None}
        elif op == "PROVISION_PROJECT":
            if self.replace_parent or b["parent_physical_identity"] != self.parent or self.project_state != "ABSENT":
                return b"", b"parent-drift", 2, "completed", True, True
            self.mkdir_count += 1
            self.project_state = "EXISTING"
            if self.raise_after_mkdir:
                return b"", b"", None, "timeout", False, False
            result = {"state": "EXISTING", "parent_physical_identity": self.parent, "project_physical_identity": self.project}
        else:
            p = request["payload"]["request_payload"]
            if op == "ALLOCATE_WORKSPACE":
                result = {"remote_workspace": b["remote_workspace"], "workspace_physical_token": directory_token(b["remote_workspace"])}
            elif op == "STAGE_EXACT_FILE":
                result = {key: value for key, value in p.items() if key != "content_base64"}
                result["artifact_physical_token"] = "staged-" + p["portable_name"]
            elif op == "SUBMIT_QSUB_ONCE":
                assert len(request["payload"]["staged"]) == 2
                assert request["payload"]["resources"]["queue"] == "batch"
                result = {"job_id": "123.server"}
            elif op == "RECONCILE_SUBMISSION":
                result = {"outcome": "UNKNOWN"}
            elif op == "QUERY_SCHEDULER":
                code, out, err = self.scheduler
                result = {"stdout_base64": base64.b64encode(out).decode("ascii"), "stderr_base64": base64.b64encode(err).decode("ascii"), "returncode": code, "eof_stdout": True, "eof_stderr": True, "completion_status": "completed"}
            else:
                name = p["portable_name"]
                data = self.outputs.get(name)
                if op == "STAT_EXACT_FILE":
                    result = {"portable_name": name, "presence": "absent"} if data is None else {"portable_name": name, "presence": "present", "size_bytes": len(data), "file_physical_token": "output-" + name}
                else:
                    result = {"portable_name": name, "size_bytes": len(data), "sha256": sha256(data).hexdigest(), "content_base64": base64.b64encode(data).decode("ascii"), "file_physical_token": "output-" + name}
        response = _bridge._encode_frame({"protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, "operation": op, "status": "ok", "result": result})
        return response, b"", 0, "completed", True, True


class ProductionBridgeTests(lane.LaneAFixture):
    def setUp(self) -> None:
        super().setUp()
        fixture = v30.TransportFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = fixture.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        manifest = json.loads(raw.runtime_contents["transport-deployment-manifest-v2.json"])
        manifest.update(schema="auto-g16-v3-transport-deployment-manifest/3", bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
        manifest["trust_roots"] = {key: value for key, value in manifest["trust_roots"].items() if key in {"mac_ssh", "server_remote_shell", "server_python", "server_qsub", "server_qstat"}}
        self.current_profile = replace(raw, platform_paths={**raw.platform_paths, "xtb_executable_path": "/opt/xtb/6.7.1/bin/xtb", "crest_executable_path": "/opt/crest/3.0.2/bin/crest", "xtb_data_path": "/opt/xtb/6.7.1/share/xtb"}, runtime_contents={_driver._TABLE_NAME: _driver._OPERATION_TABLE_BYTES, _driver._RESOURCE_DESCRIPTOR_NAME: v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES, "transport-deployment-manifest-v3.json": canonical_json_bytes(manifest), _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME: _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES, "xtb": b"offline exact binary image A", "crest": b"offline exact binary image B", lane.XTB_RUNTIME_DATA_MANIFEST_NAME: lane.xtb_runtime_data_manifest_bytes()})
        self.target = execution.resolve_server_profile(self.current_profile)
        root = self.root / "bridge"
        root.mkdir()
        self.journal_path = root / "projects.sqlite3"
        self.journal = _ProductionProvisioningJournal.create_new(self.journal_path, approved_root=root)
        self.addCleanup(self.journal.close)
        self.program_store = program._ProgramTransportStore.create_new(root / "program.sqlite3", approved_root=root)
        self.addCleanup(self.program_store.close)
        self.wire = _Wire()
        self.process_spy = patch.object(_driver.subprocess, "Popen", side_effect=AssertionError("offline tests prohibit processes")).start()
        self.addCleanup(patch.stopall)
        self.run_patch = patch.object(_driver._SubprocessRTWinDriver, "_run", side_effect=self.wire.run)
        self.run_spy = self.run_patch.start()
        self.service = _ProjectProvisioningService._from_project_attestor(attestor=bridge._RTWinProjectAttestor(current_profile=self.current_profile, target=self.target), target=self.target, journal=self.journal)

    def tearDown(self) -> None:
        self.process_spy.assert_not_called()
        super().tearDown()

    def provision(self):
        return self.service.provision_remote_project(project=self.store.load_project("project-1"), target=self.target, remote_project_dir=self.remote_project_dir)

    def prepare(self):
        binding = self.provision()
        spec = preparation._prepare_program_execution_spec(program_kind="xtb", executable_path=self.current_profile.platform_paths["xtb_executable_path"], executable_size_bytes=len(self.current_profile.runtime_contents["xtb"]), executable_sha256=sha256(self.current_profile.runtime_contents["xtb"]).hexdigest(), input_name="input.xyz", input_bytes=lane.XYZ, program_data=self.xtb_data(), resolved_profile=self.target)
        service = preparation._ProgramExecutionSnapshotService._for_production(project_provisioning=self.service, target=self.target)
        resources = execution.ResolvedResourceRequest(resource_spec=self.store.load_resource_spec("resource-1"), cores=8, memory_mb=12288, walltime_seconds=3600, queue="batch")
        self.snapshot = service.prepare(self.store, attempt_id="attempt-1", calculation_plan_id="plan-1", resource_spec_id="resource-1", program_execution_spec=spec, project_physical_binding=binding, resolved_resource_request=resources, resolved_server_profile=self.target, workspace_binding=self.workspace())
        self.driver = bridge._RTWinProgramEffectDriver(snapshot=self.snapshot, current_profile=self.current_profile, program_transport_store=self.program_store)
        self.wire.calls.clear()
        return self.snapshot

    def execute(self, store=None):
        scheduler = self.snapshot.scheduler_artifacts[0]
        selected_store = self.store if store is None else store
        result = execution.execute_once(selected_store, snapshot=self.snapshot, current_profile=self.current_profile, confirmed_execution_snapshot_id=self.snapshot.program_execution_snapshot_id, prepared_input_bytes=lane.XYZ, pbs_template_bytes=scheduler["content_utf8"].encode("utf-8"), port=runtime._ProgramExecutionPort(snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver))
        self.assertIs(type(result), execution.ExecutionAttemptResult)
        self.assertEqual(result.receipts, ())
        return runtime._read_program_execution_result(selected_store, snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver, claim=result.claim)

    def query(self):
        return runtime._query_program_scheduler(self.store, snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver)

    def capture(self):
        return runtime._capture_program_outputs(self.store, snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver)

    def approvals(self):
        plan = self.store.load_calculation_plan("plan-1")
        science = approval.ScientificApproval.for_plan(self.store, plan, displayed_semantic_meaning={"program": "xtb"}, reviewer_id="offline-reviewer", reviewer_evidence={})
        batch = approval.BatchSubmitApproval.for_existing_attempts(self.store, [("attempt-1", science)], reviewer_id="offline-reviewer", reviewer_evidence={})
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(self.store, self.snapshot, confirmer_id="offline-reviewer", confirmer_evidence={})
        return dict(runtime_store=self.store, attempt=self.store.load_attempt("attempt-1"), plan=plan, displayed_semantic_meaning={"program": "xtb"}, scientific_approval=science, batch_submit_approval=batch, execution_snapshot=self.snapshot, operational_confirmation=confirmation)

    def test_project_absent_observation_is_read_only(self):
        result = self.service.classify_remote_project(project=self.store.load_project("project-1"), target=self.target, remote_project_dir=self.remote_project_dir, stored_binding=None)
        self.assertEqual(result, ("ABSENT", None))
        self.assertEqual([op for op, _ in self.wire.calls], ["OBSERVE_PROJECT"])
        self.assertEqual(self.wire.mkdir_count, 0)

    def test_common_signature_requiredness_and_result_inventory_remain_frozen(self):
        signature = inspect.signature(execution.execute_once)
        self.assertEqual(tuple(signature.parameters), ("store", "snapshot", "current_profile", "prepared_input_bytes", "pbs_template_bytes", "confirmed_execution_snapshot_id", "port"))
        self.assertTrue(all(p.default is inspect.Parameter.empty for p in signature.parameters.values()))
        self.assertEqual(signature.return_annotation, "ExecutionAttemptResult")
        self.assertIs(get_type_hints(execution.execute_once)["return"], execution.ExecutionAttemptResult)
        self.assertIs(get_type_hints(execution.execute_once)["port"], execution.ExecutionPort)
        self.assertEqual(tuple(f.name for f in fields(execution.ExecutionAttemptResult)), ("claim", "attempt_state", "receipts"))
        self.assertFalse(hasattr(execution, "_ProgramExecutionPort"))

    def test_generation_splices_and_nonbytes_are_rejected_before_claim(self):
        self.prepare()
        port = runtime._ProgramExecutionPort(snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver)
        arguments = dict(snapshot=self.snapshot, current_profile=self.current_profile, confirmed_execution_snapshot_id=self.snapshot.program_execution_snapshot_id, prepared_input_bytes=lane.XYZ, pbs_template_bytes=self.snapshot.scheduler_artifacts[0]["content_utf8"].encode("utf-8"), port=port)
        v30 = self.v30_snapshot()
        cases = (
            {**arguments, "snapshot": v30, "confirmed_execution_snapshot_id": v30.execution_snapshot_id},
            {**arguments, "port": composition._V30Port()},
            {**arguments, "prepared_input_bytes": {"input.xyz": lane.XYZ}},
            {**arguments, "pbs_template_bytes": {"scheduler": arguments["pbs_template_bytes"]}},
            {**arguments, "confirmed_execution_snapshot_id": v30.execution_snapshot_id},
        )
        with patch.object(self.store, "record_submission_intent", wraps=self.store.record_submission_intent) as claim:
            for case in cases:
                with self.subTest(case=tuple(case)), self.assertRaises((execution.ExecutionValueError, TransportBoundaryError)):
                    execution.execute_once(self.store, **case)
            claim.assert_not_called()
        self.assertFalse(self.wire.calls)

    def test_production_project_implements_semantic_seam_and_rejects_synthetic_injection(self):
        self.assertIsInstance(self.service._attestor, _ProjectAttestor)
        with self.assertRaises(execution.ExecutionValueError):
            _ProjectProvisioningService._from_project_attestor(attestor=self.remote_attestor, target=self.target, journal=self.journal)
        with self.assertRaises(execution.ExecutionValueError):
            _ProjectProvisioningService._from_project_attestor(attestor=object(), target=self.target, journal=self.journal)
        self.assertFalse(self.wire.calls)

    def test_v30_core_type_gate_precedes_the_single_claim(self):
        # Preserve the original V30 ReceiptJournal type gate before Core claim.
        current = self.v30_snapshot()
        v30_port = composition._V30Port()
        v30_port.contract_version = current.adapter_contract_version
        foreign = SimpleNamespace(attempt_state=Mock(return_value=core.AttemptState.PLANNED), record_submission_intent=Mock())
        with self.assertRaisesRegex(execution.ExecutionValueError, "public Core"):
            execution.execute_once(foreign, snapshot=current, current_profile=lane.LaneAFixture.profile(self), prepared_input_bytes=lane.GAUSSIAN_INPUT, pbs_template_bytes=lane.PBS_TEMPLATE, confirmed_execution_snapshot_id=current.execution_snapshot_id, port=v30_port)
        foreign.record_submission_intent.assert_not_called()
        self.assertEqual(v30_port.calls, 0)

    def test_project_provision_intent_precedes_one_mkdir_and_reopen_replays(self):
        committed = []

        def observe_committed_intent(scope, invocation):
            if invocation.operation.name == "PROVISION_PROJECT":
                self.assertFalse(self.journal._connection.in_transaction)
                with closing(sqlite3.connect(f"{self.journal_path.as_uri()}?mode=ro&cache=private", uri=True)) as reader:
                    rows = reader.execute("SELECT intent_id,project_id,target_id,project_path,payload_json FROM main.provisioning_intents").fetchall()
                expected = {"project_id": "project-1", "target_id": self.target.resolved_server_profile_id, "path": self.remote_project_dir, "parent_identity": self.wire.parent, "authority_id": self.service._authority_id}
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][1:4], ("project-1", self.target.resolved_server_profile_id, self.remote_project_dir))
                self.assertEqual(json.loads(rows[0][4]), expected)
                self.assertEqual(rows[0][4], json.dumps(expected, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")))
                _command, frame = bridge._prepare_program_invocation(scope, invocation)
                request = _bridge._decode_frame(frame, cap=invocation.operation.stdin_cap, field="committed intent test")
                self.assertEqual(rows[0][0], request["payload"]["provision_intent_id"])
                committed.append(rows[0])
            return self.wire.run(scope, invocation)

        self.run_spy.side_effect = observe_committed_intent
        binding = self.provision()
        self.assertEqual(len(committed), 1)
        self.assertEqual(self.wire.mkdir_count, 1)
        self.assertEqual([op for op, _ in self.wire.calls], ["OBSERVE_PROJECT", "OBSERVE_PROJECT", "PROVISION_PROJECT"])
        reopened = _ProductionProvisioningJournal.open_existing(self.journal_path, approved_root=self.journal_path.parent)
        self.addCleanup(reopened.close)
        service = _ProjectProvisioningService._from_project_attestor(attestor=bridge._RTWinProjectAttestor(current_profile=self.current_profile, target=self.target), target=self.target, journal=reopened)
        replay = service.provision_remote_project(project=self.store.load_project("project-1"), target=self.target, remote_project_dir=self.remote_project_dir)
        self.assertEqual(replay, binding)
        self.assertEqual(self.wire.mkdir_count, 1)

    def test_project_temp_trigger_suppression_has_zero_provision(self):
        self.journal._connection.execute("CREATE TEMP TRIGGER suppress_intent BEFORE INSERT ON main.provisioning_intents BEGIN SELECT RAISE(IGNORE); END")
        with self.assertRaisesRegex(execution.ExecutionValueError, "TEMP schema"):
            self.provision()
        self.assertNotIn("PROVISION_PROJECT", [op for op, _ in self.wire.calls])
        self.assertEqual(self.wire.mkdir_count, 0)
        self.assertEqual(self.journal._connection.execute("SELECT COUNT(*) FROM main.provisioning_intents").fetchone()[0], 0)

    def test_project_ambient_transaction_is_rejected_without_commit_or_rollback(self):
        connection = self.journal._connection
        connection.execute("BEGIN")
        trace = []
        connection.set_trace_callback(trace.append)
        try:
            with self.assertRaisesRegex(execution.ExecutionValueError, "pre-existing transaction"):
                self.provision()
            self.assertTrue(connection.in_transaction)
            self.assertFalse(any(sql.upper().startswith(("COMMIT", "ROLLBACK")) for sql in trace))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM main.provisioning_intents").fetchone()[0], 0)
            self.assertNotIn("PROVISION_PROJECT", [op for op, _ in self.wire.calls])
            self.assertEqual(self.wire.mkdir_count, 0)
        finally:
            connection.set_trace_callback(None)
            connection.execute("ROLLBACK")

    def test_project_silently_ignored_insert_has_zero_provision(self):
        def ignore_insert(action, name, _column, _database, _source):
            return sqlite3.SQLITE_IGNORE if action == sqlite3.SQLITE_INSERT and name == "provisioning_intents" else sqlite3.SQLITE_OK

        self.journal._connection.set_authorizer(ignore_insert)
        try:
            with self.assertRaisesRegex(execution.ExecutionValueError, "INSERT did not create"):
                self.provision()
            self.assertFalse(self.journal._connection.in_transaction)
            self.assertNotIn("PROVISION_PROJECT", [op for op, _ in self.wire.calls])
            self.assertEqual(self.wire.mkdir_count, 0)
            self.assertEqual(self.journal._connection.execute("SELECT COUNT(*) FROM main.provisioning_intents").fetchone()[0], 0)
        finally:
            self.journal._connection.set_authorizer(None)

    def test_project_connection_policy_drift_has_zero_provision(self):
        connection = self.journal._connection
        cases = (
            ("PRAGMA synchronous=OFF", "PRAGMA synchronous=FULL"),
            ("PRAGMA trusted_schema=ON", "PRAGMA trusted_schema=OFF"),
            ("PRAGMA read_uncommitted=ON", "PRAGMA read_uncommitted=OFF"),
            ("PRAGMA foreign_keys=OFF", "PRAGMA foreign_keys=ON"),
            ("PRAGMA journal_mode=MEMORY", "PRAGMA journal_mode=DELETE"),
            ("ATTACH ':memory:' AS foreign_db", "DETACH foreign_db"),
            ("CREATE TEMP TABLE provisioning_intents(value TEXT)", "DROP TABLE temp.provisioning_intents"),
        )
        for inject, restore in cases:
            with self.subTest(inject=inject):
                connection.execute(inject)
                try:
                    with self.assertRaises(execution.ExecutionValueError):
                        self.provision()
                    self.assertNotIn("PROVISION_PROJECT", [op for op, _ in self.wire.calls])
                    self.assertEqual(self.wire.mkdir_count, 0)
                finally:
                    connection.execute(restore)

    def test_project_failed_commit_has_zero_provision(self):
        def deny_commit(action, name, _column, _database, _source):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT" else sqlite3.SQLITE_OK

        self.journal._connection.set_authorizer(deny_commit)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                self.provision()
            self.assertFalse(self.journal._connection.in_transaction)
            self.assertEqual(self.journal._connection.execute("SELECT COUNT(*) FROM main.provisioning_intents").fetchone()[0], 0)
            self.assertNotIn("PROVISION_PROJECT", [op for op, _ in self.wire.calls])
            self.assertEqual(self.wire.mkdir_count, 0)
        finally:
            self.journal._connection.set_authorizer(None)

    def test_project_failed_committed_readback_has_zero_provision_and_no_retry(self):
        reader = sqlite3.connect(f"{self.journal_path.as_uri()}?mode=ro&cache=private", uri=True)
        reader.set_authorizer(lambda *_args: sqlite3.SQLITE_DENY)
        with patch("auto_g16.execution.project_provisioning.sqlite3.connect", return_value=reader):
            with self.assertRaises(sqlite3.DatabaseError):
                self.provision()
        self.assertFalse(self.journal._connection.in_transaction)
        self.assertEqual(self.journal._connection.execute("SELECT COUNT(*) FROM main.provisioning_intents").fetchone()[0], 1)
        with self.assertRaisesRegex(execution.ExecutionValueError, "no automatic retry"):
            self.provision()
        self.assertNotIn("PROVISION_PROJECT", [op for op, _ in self.wire.calls])
        self.assertEqual(self.wire.mkdir_count, 0)

    def test_project_parent_replacement_stops_and_durable_intent_cannot_retry(self):
        self.wire.replace_parent = True
        with self.assertRaises(program._ProgramEffectUnknown):
            self.provision()
        self.wire.replace_parent = False
        with self.assertRaisesRegex(execution.ExecutionValueError, "no automatic retry"):
            self.provision()
        self.assertEqual(self.wire.mkdir_count, 0)

    def test_parent_change_between_classification_and_recheck_has_zero_intent_or_mkdir(self):
        with patch.object(self.service._attestor, "_observe_current", side_effect=[("ABSENT", self.wire.parent, None), ("ABSENT", directory_token("/home/user100/SDL", 999), None)]):
            with self.assertRaisesRegex(execution.ExecutionValueError, "parent identity changed"):
                self.provision()
        self.assertEqual(self.wire.mkdir_count, 0)
        self.assertEqual(self.journal._connection.execute("SELECT COUNT(*) FROM provisioning_intents").fetchone()[0], 0)

    def test_project_ambiguous_mkdir_cannot_adopt_or_retry(self):
        self.wire.raise_after_mkdir = True
        with self.assertRaises(program._ProgramEffectUnknown):
            self.provision()
        with self.assertRaisesRegex(execution.ExecutionValueError, "UNBOUND_EXISTING"):
            self.provision()
        self.assertIsNone(self.journal.load_binding("project-1"))
        self.assertEqual(self.wire.mkdir_count, 1)

    def test_unbound_existing_has_zero_mutation(self):
        self.wire.project_state = "EXISTING"
        with self.assertRaisesRegex(execution.ExecutionValueError, "UNBOUND_EXISTING"):
            self.provision()
        self.assertEqual(self.wire.mkdir_count, 0)

    def test_bound_project_identity_drift_rejects(self):
        self.provision()
        self.wire.project = directory_token(self.remote_project_dir, 999)
        with self.assertRaisesRegex(execution.ExecutionValueError, "physical identity drifted"):
            self.provision()
        self.assertEqual(self.wire.mkdir_count, 1)

    def test_real_executable_path_size_hash_are_profile_owned(self):
        self.prepare()
        spec = self.snapshot.program_execution_spec
        for key, bad in (("executable_path", "/different/xtb"), ("executable_size_bytes", 99), ("executable_sha256", "0" * 64)):
            args = dict(program_kind="xtb", executable_path=self.current_profile.platform_paths["xtb_executable_path"], executable_size_bytes=len(self.current_profile.runtime_contents["xtb"]), executable_sha256=sha256(self.current_profile.runtime_contents["xtb"]).hexdigest(), input_name="input.xyz", input_bytes=lane.XYZ, program_data=self.xtb_data(), resolved_profile=self.target)
            args[key] = bad
            with self.subTest(field=key), self.assertRaises(execution.ExecutionValueError):
                preparation._prepare_program_execution_spec(**args)
        self.assertEqual(spec.invocation["executable_identity"]["absolute_path"], self.current_profile.platform_paths["xtb_executable_path"])
        self.assertFalse(self.wire.calls)

    def test_synthetic_driver_cannot_authorize_real_executable(self):
        self.prepare()
        self.driver = composition._Driver()
        with self.assertRaisesRegex(TransportBoundaryError, "production RTwin driver"):
            self.execute()
        self.assertFalse(self.driver.calls)
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)

    def test_production_driver_cannot_accept_fixture_executable(self):
        snapshot = self.successor_snapshot()
        with self.assertRaisesRegex(TransportBoundaryError, "synthetic executables"):
            bridge._RTWinProgramEffectDriver(snapshot=snapshot, current_profile=lane.LaneAFixture.profile(self), program_transport_store=self.program_store)

    def test_runtime_qualification_drift_rejects_before_claim_or_process(self):
        self.prepare()
        self.current_profile.runtime_contents["xtb"] += b"changed"
        with patch.object(self.store, "record_submission_intent", wraps=self.store.record_submission_intent) as claim:
            with self.assertRaises((execution.ExecutionValueError, TransportBoundaryError)):
                self.execute()
            claim.assert_not_called()
        self.assertFalse(self.wire.calls)

    def test_xtb_runtime_data_manifest_drift_rejects_before_claim_or_process(self):
        self.prepare()
        manifest = json.loads(
            self.current_profile.runtime_contents[lane.XTB_RUNTIME_DATA_MANIFEST_NAME]
        )
        manifest["files"]["param_gfn2-xtb.txt"]["sha256"] = "0" * 64
        self.current_profile.runtime_contents[
            lane.XTB_RUNTIME_DATA_MANIFEST_NAME
        ] = lane.xtb_runtime_data_manifest_bytes(manifest)
        with patch.object(
            self.store,
            "record_submission_intent",
            wraps=self.store.record_submission_intent,
        ) as claim:
            with self.assertRaises((execution.ExecutionValueError, TransportBoundaryError)):
                self.execute()
            claim.assert_not_called()
        self.assertFalse(self.wire.calls)

    def test_seven_operations_use_the_reviewed_rtwin_runner(self):
        self.prepare()
        self.assertEqual(self.driver.runtime_qualification["bootstrap_protocol"], _bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
        self.assertEqual(self.execute().outcome, "SUCCEEDED")
        self.query()
        capture = self.capture()
        authority = runtime._assert_program_terminal_success_authority(self.store, snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver, capture=capture)
        self.assertEqual(authority["job_id"], "123.server")
        self.assertEqual({op for op, _ in self.wire.calls}, set(program._OPERATIONS) - {"RECONCILE_SUBMISSION"})
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.wire.calls), 1)

    def test_unknown_submission_reconciliation_has_no_second_qsub(self):
        self.prepare()
        self.wire.fail_operation = "SUBMIT_QSUB_ONCE"
        self.assertEqual(self.execute().outcome, "UNKNOWN")
        self.wire.fail_operation = None
        runtime._reconcile_program_submission(self.store, snapshot=self.snapshot, program_transport_store=self.program_store, driver=self.driver)
        before = len(self.wire.calls)
        self.assertIs(self.execute().claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(self.wire.calls), before)
        self.assertIn("RECONCILE_SUBMISSION", [op for op, _ in self.wire.calls])
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.wire.calls), 1)

    def test_approval_chain_is_pure_and_rejected_stale_or_missing_scope_calls_no_driver(self):
        self.prepare()
        packet = self.approvals()
        with patch.object(self.store, "record_submission_intent", wraps=self.store.record_submission_intent) as claim:
            approval.validate_effect_authority(**packet)
            for field, value in (
                ("displayed_semantic_meaning", {"program": "crest"}),
                ("scientific_approval", approval.ScientificApproval.for_plan(self.store, packet["plan"], displayed_semantic_meaning={"program": "xtb"}, reviewer_id="r", reviewer_evidence={}, decision=approval.ApprovalDecision.REJECTED)),
                ("operational_confirmation", approval.ExactOperationalConfirmation.for_snapshot(self.store, self.snapshot, confirmer_id="r", confirmer_evidence={}, decision=approval.ApprovalDecision.REJECTED)),
            ):
                with self.subTest(field=field), self.assertRaises(approval.ApprovalError):
                    approval.validate_effect_authority(**{**packet, field: value})
            self.store.store_task(core.Task(task_id="task-2", workflow_run_id="run-1", task_kind="successor-program"))
            other_plan = core.CalculationPlan(calculation_plan_id="plan-2", task_id="task-2", revision=1, intent={"program": "xtb"})
            self.store.store_calculation_plan(other_plan)
            self.store.create_attempt(core.Attempt(attempt_id="attempt-2", task_id="task-2", ordinal=1))
            other_science = approval.ScientificApproval.for_plan(self.store, other_plan, displayed_semantic_meaning={"program": "xtb"}, reviewer_id="r", reviewer_evidence={})
            missing = approval.BatchSubmitApproval.for_existing_attempts(self.store, [("attempt-2", other_science)], reviewer_id="r", reviewer_evidence={})
            with self.assertRaises(approval.ApprovalError):
                approval.validate_effect_authority(**{**packet, "batch_submit_approval": missing})
            claim.assert_not_called()
        self.assertFalse(self.wire.calls)

    def test_snapshot_mutation_stales_confirmation_before_claim(self):
        self.prepare()
        packet = self.approvals()
        object.__setattr__(self.snapshot, "program_execution_snapshot_id", "forged")
        with patch.object(self.store, "record_submission_intent", wraps=self.store.record_submission_intent) as claim:
            with self.assertRaises(approval.ApprovalError):
                approval.validate_effect_authority(**packet)
            claim.assert_not_called()
        self.assertFalse(self.wire.calls)

    def test_reopened_three_layer_approval_authorizes_one_production_bridge_claim(self):
        self.prepare()
        packet = self.approvals()
        database = self.root / "production-approvals.sqlite3"
        with closing(approval.SQLiteApprovalStore(database)) as stored:
            stored.store_scientific_approval(packet["scientific_approval"])
            stored.store_batch_submit_approval(packet["batch_submit_approval"])
            stored.store_operational_confirmation(packet["operational_confirmation"])
        with closing(approval.SQLiteApprovalStore(database)) as reopened:
            packet["scientific_approval"] = reopened.load_scientific_approval(packet["scientific_approval"].scientific_approval_id)
            packet["batch_submit_approval"] = reopened.load_batch_submit_approval(packet["batch_submit_approval"].batch_submit_approval_id)
            packet["operational_confirmation"] = reopened.load_current_operational_confirmation(packet["operational_confirmation"].operational_confirmation_id, self.snapshot)
        with patch.object(self.store, "record_submission_intent", wraps=self.store.record_submission_intent) as claim:
            approval.validate_effect_authority(**packet)
            claim.assert_not_called()
            self.assertFalse(self.wire.calls)
            self.assertIs(self.execute().claim, core.SubmissionIntentClaim.WINNER)
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.wire.calls), 1)
        before = len(self.wire.calls)
        self.assertIs(self.execute().claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(self.wire.calls), before)

    def test_two_validated_controllers_have_one_winner_and_replay_is_effect_free(self):
        self.prepare()
        packet = self.approvals()
        barrier = Barrier(2)
        def controller():
            other = core.SQLiteRuntimeStore(self.database)
            try:
                approval.validate_effect_authority(**{**packet, "runtime_store": other})
                barrier.wait(timeout=10)
                return self.execute(other)
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda _: controller(), range(2)))
        self.assertCountEqual([result.claim for result in results], [core.SubmissionIntentClaim.WINNER, core.SubmissionIntentClaim.REPLAY])
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.wire.calls), 1)
        before = len(self.wire.calls)
        with self.assertRaises(approval.ApprovalScopeError):
            approval.validate_effect_authority(**packet)
        self.assertEqual(len(self.wire.calls), before)

    def test_queued_held_exiting_absent_unknown_and_missing_exit_cannot_succeed(self):
        self.prepare()
        self.execute()
        cases = [(0, f"Job Id: 123.server\n    job_state = {state}\n".encode(), b"") for state in ("Q", "H", "E", "C")]
        cases += [(153, b"", b"qstat: Unknown Job Id 123.server\n"), (0, b"ambiguous\n", b"")]
        for value in cases:
            with self.subTest(response=value):
                self.wire.scheduler = value
                self.query()
                self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)
                before = len(self.wire.calls)
                with self.assertRaisesRegex(TransportBoundaryError, "capture requires"):
                    self.capture()
                self.assertEqual(len(self.wire.calls), before)

    def test_running_then_exact_exit_zero_owns_success_and_capture(self):
        self.prepare()
        self.execute()
        self.wire.scheduler = (0, b"Job Id: 123.server\n    job_state = R\n", b"")
        self.query()
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.RUNNING)
        self.wire.scheduler = (0, b"Job Id: 123.server\n    job_state = C\n    exit_status = 0\n", b"")
        self.query()
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertEqual(self.capture().artifacts[1].content, lane.XYZ)

    def test_terminal_nonzero_owns_failure_and_blocks_capture(self):
        self.prepare()
        self.execute()
        self.wire.scheduler = (0, b"Job Id: 123.server\n    job_state = C\n    exit_status = 7\n", b"")
        self.query()
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.FAILED)
        with self.assertRaises(TransportBoundaryError):
            self.capture()

    def test_exact_torque_terminal_exit_status_propagates(self):
        for state in ("C", "F", "X"):
            for code in (0, 1, -1):
                with self.subTest(state=state, code=code):
                    out = f"Job Id: 123.server\n    job_state = {state}\n    exit_status = {code}\n".encode()
                    result = bridge._parse_scheduler({
                        "stdout_base64": base64.b64encode(out).decode(),
                        "stderr_base64": "", "returncode": 0,
                        "eof_stdout": True, "eof_stderr": True,
                        "completion_status": "completed",
                    }, "123.server")
                    self.assertEqual(result, {"job_id": "123.server", "state": "terminal", "exit_status": code})

    def test_scheduler_state_mapping_is_unchanged(self):
        expected = {"Q": "queued", "W": "queued", "R": "running", "B": "running", "H": "held", "S": "held", "E": "exiting", "T": "exiting", "Z": "unknown"}
        for state, disposition in expected.items():
            with self.subTest(state=state):
                out = f"Job Id: 123.server\n    job_state = {state}\n".encode()
                result = bridge._parse_scheduler({
                    "stdout_base64": base64.b64encode(out).decode(),
                    "stderr_base64": "", "returncode": 0,
                    "eof_stdout": True, "eof_stderr": True,
                    "completion_status": "completed",
                }, "123.server")
                self.assertEqual(result, {"job_id": "123.server", "state": disposition})

    def test_other_job_duplicate_exit_or_invalid_exit_never_promotes(self):
        self.prepare()
        self.execute()
        cases = (
            b"Job Id: other.server\n    job_state = C\n    exit_status = 0\n",
            b"Job Id: 123.server\n    job_state = C\n    exit_status = 0\n    exit_status = 7\n",
            b"Job Id: 123.server\n    job_state = C\n    exit_status = +0\n",
            b"Job Id: 123.server\n    job_state = C\n",
            b"Job Id: 123.server\n    job_state = C\n    exit_status = garbage\n",
            b"Job Id: 123.server\n    job_state = C\n   exit_status = 0\n",
            b"Job Id: 123.server\n    job_state = C\n    Exit_status = 0\n",
        )
        for out in cases:
            self.wire.scheduler = (0, out, b"")
            self.assertEqual(self.query()["state"], "unknown")
            self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)
            before = len(self.wire.calls)
            with self.assertRaises(TransportBoundaryError):
                self.capture()
            self.assertEqual(len(self.wire.calls), before)

    def test_concrete_methods_require_one_use_execution_context(self):
        self.prepare()
        base = runtime._snapshot_binding(self.snapshot, self.program_store, self.driver)
        request = program._request("ALLOCATE_WORKSPACE", base, {})
        with self.assertRaisesRegex(TransportBoundaryError, "execution-owned"):
            self.driver.allocate_workspace(request)
        self.assertFalse(self.wire.calls)

    def test_winner_enum_cannot_reenter_a_failed_continuation(self):
        fixture = composition.ProgramCompositionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.driver.raise_operation = ("ALLOCATE_WORKSPACE", program._ProgramConfirmedFailure("no effect"))
        self.assertEqual(fixture.execute().outcome, "FAILED")
        self.assertIs(fixture.store.attempt_state("attempt-1"), core.AttemptState.SUBMISSION_INTENT_RECORDED)
        prepared = runtime._prepare_program_execution(fixture.store, snapshot=fixture.snapshot, program_transport_store=fixture.program_transport_store, input_bytes=fixture.input_bytes, scheduler_artifact_bytes=fixture.scheduler_bytes, driver=fixture.driver)
        before = len(fixture.driver.calls)
        with self.assertRaisesRegex(TransportBoundaryError, "one-use Execution WINNER"):
            runtime._execute_claimed_program(fixture.store, snapshot=fixture.snapshot, program_transport_store=fixture.program_transport_store, prepared=prepared, driver=fixture.driver, claim=core.SubmissionIntentClaim.WINNER)
        self.assertEqual(len(fixture.driver.calls), before)
        self.assertIs(fixture.execute().claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(fixture.driver.calls), before)

    def test_executable_attestation_rejects_symlink_ancestors_and_leaf(self):
        tree = ast.parse(_bridge._PROGRAM_BOOTSTRAP_SOURCE)
        namespace = {}
        exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "<offline-successor-bootstrap>", "exec"), namespace)
        parent = self.root / "exact-binary"
        parent.mkdir()
        binary = parent / "xtb"
        content = b"offline image, never executed"
        binary.write_bytes(content)
        binary.chmod(0o700)
        alias = self.root / "ancestor-link"
        alias.symlink_to(parent, target_is_directory=True)
        leaf = parent / "leaf-link"
        leaf.symlink_to(binary)
        args = {"path": str(binary), "size_bytes": len(content), "sha256": sha256(content).hexdigest()}
        namespace["executable"](args)
        for path in (alias / "xtb", leaf):
            with self.subTest(path=path.name), self.assertRaises(OSError):
                namespace["executable"]({**args, "path": str(path)})

    def test_bootstrap_project_mkdir_is_fd_relative_once_and_parent_rechecked(self):
        self.provision()
        request = next(request for op, request in self.wire.calls if op == "PROVISION_PROJECT")
        tree = ast.parse(_bridge._PROGRAM_BOOTSTRAP_SOURCE, feature_version=(3, 6))
        namespace = {}
        exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "<offline-successor-bootstrap>", "exec"), namespace)
        manifest = json.loads(self.current_profile.runtime_contents["transport-deployment-manifest-v3.json"])
        fake_os = Mock()
        fake_os.path.abspath.return_value = "/usr/bin/python3"
        output = io.BytesIO()
        fake_sys = SimpleNamespace(argv=["bootstrap", base64.b64encode(canonical_json_bytes(manifest)).decode()], executable="/usr/bin/python3", stdin=SimpleNamespace(buffer=io.BytesIO(_bridge._encode_frame(request))), stdout=SimpleNamespace(buffer=output))
        namespace.update(os=fake_os, sys=fake_sys, executable=Mock(), parent=Mock(return_value=(10, self.wire.parent, "/home/user100/SDL", "project-1")), named_directory=Mock(return_value=11), project_observe=Mock(return_value={"state": "EXISTING", "parent_physical_identity": self.wire.parent, "project_physical_identity": self.wire.project}))
        namespace["main"]()
        fake_os.mkdir.assert_called_once_with("project-1", 0o700, dir_fd=10)
        namespace["named_directory"].assert_called_once_with("/home/user100/SDL", self.wire.parent)
        fake_os.makedirs.assert_not_called()
        fake_os.unlink.assert_not_called()
        fake_os.mkdir.reset_mock()
        fake_sys.stdin.buffer = io.BytesIO(_bridge._encode_frame(request))
        namespace["named_directory"].side_effect = ValueError("parent replacement")
        with self.assertRaisesRegex(ValueError, "parent replacement"):
            namespace["main"]()
        fake_os.mkdir.assert_not_called()

    def test_bootstrap_directory_open_never_follows_symlinks(self):
        tree = ast.parse(_bridge._PROGRAM_BOOTSTRAP_SOURCE)
        namespace = {}
        exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "<offline-successor-bootstrap>", "exec"), namespace)
        fake_os = Mock()
        fake_os.path.normpath.return_value = "/home/user100/SDL"
        fake_os.open.side_effect = [10, 11, OSError("symlink/reparse-like component")]
        fake_os.fstat.return_value = SimpleNamespace(st_dev=1, st_ino=2)
        namespace["os"] = fake_os
        with self.assertRaises(OSError):
            namespace["directory"]("/home/user100/SDL")
        import os
        for call in fake_os.open.call_args_list:
            self.assertTrue(call.args[1] & os.O_NOFOLLOW)
            self.assertTrue(call.args[1] & os.O_DIRECTORY)
        fake_os.mkdir.assert_not_called()
