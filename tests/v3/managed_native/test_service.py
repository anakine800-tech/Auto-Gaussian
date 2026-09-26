"""Real Core/Approval/Transport composition; inert native adapter, no live effects."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from auto_g16 import approval, core, execution
from auto_g16.execution import _program_completion as completion
from auto_g16.execution.program import _ProgramExecutionSnapshotService
from auto_g16.execution.project_provisioning import (
    _ProjectProvisioningService, _ProjectAttestor, _ProductionProvisioningJournal,
)
from auto_g16._managed_native import service
from auto_g16._managed_native.installation import parse_description
from auto_g16._managed_native.lifecycle import Lifecycle
from auto_g16._managed_native.supervisor import Observation
from auto_g16._managed_offline.common import Rejected, RequestRejected, json_bytes
from auto_g16._managed_offline.intake import Intake
from auto_g16._managed_offline.registry import Registry
from auto_g16._managed_offline.review import Review, _timestamp
from auto_g16.transport import _bridge, _driver, _program_rtwin as bridge, program
from auto_g16.transport._canonical import TransportBoundaryError, canonical_json_bytes
from tests.v3.managed_offline._fixtures import Fixture, Clock
from tests.v3.transport import _fixtures as v30
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport.test_publisher_pilot_orchestration import qualification_fixture, seal, file_binding, PILOT
from tests.v31.transport.test_rtwin_successor_bridge import directory_token
from .test_supervisor import Veto


def direct_profile(raw):
    files = dict(raw.config_files)
    old = files["mac-proxyjump-ssh-config"].decode()
    comments = "\n".join(old.splitlines()[:2]).replace("AutoG16Final", "AutoG16Direct")
    final = ("Host " + old.rsplit("\nHost ", 1)[1]).replace("auto-g16-option1-final-server-v1", "direct-server")
    final = final.replace("    ProxyJump auto-g16-option1-rtwin-v1\n", "")
    config = (comments + "\n" + final + "    CanonicalizeHostname no\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    ConnectionAttempts 1\n").encode()
    path = Path(raw.platform_paths["mac_proxyjump_ssh_config_path"]).with_name("direct-config")
    path.write_bytes(config)
    return replace(raw, server_profile_id="synthetic-direct", jump_topology=[],
        platform_paths={"mac_direct_ssh_config_path": str(path), "mac_direct_known_hosts_path": raw.platform_paths["mac_final_known_hosts_path"], "mac_direct_public_key_path": raw.platform_paths["mac_final_public_key_path"]},
        config_files=[("mac-direct-ssh-config", config), ("mac-direct-known-hosts", files["mac-final-known-hosts"]), ("mac-direct-public-key", files["mac-final-public-key"])])


class _InertProjectPeer(_ProjectAttestor):
    """Remote-mechanics substitute at the original Project semantic interface.

    The real production-generation journal, provisioning and snapshot owners
    remain unchanged. No target observation or deployment qualification occurs.
    """
    def __init__(self, profile, target, directory):
        self.profile, self.target, self.directory = profile, target, directory
        self.parent = directory_token(directory.rsplit("/", 1)[0])
        self.project = directory_token(directory)
        self.state, self.provisions = "ABSENT", 0

    def _assert_current_authority(self, target):
        if target != self.target or execution.resolve_server_profile(self.profile) != target:
            raise AssertionError("inert Project profile drift")
        authority = _driver._resolve_closed_profile_authority(target, self.profile, target.resolved_server_profile_id, successor=True)
        if type(authority.ssh_effect) is not _driver._MacDirectEffectAuthority:
            raise AssertionError("inert Project requires exact Direct profile")
        return program._identity("inert-project-runtime", {"profile":target.resolved_server_profile_id, "manifest":authority.manifest.sha256})

    def _observe_current(self, target, remote_project_dir):
        self._assert_current_authority(target)
        if remote_project_dir != self.directory:
            raise AssertionError("inert Project path differs")
        return self.state, self.parent, self.project if self.state == "EXISTING" else None

    def _provision_absent(self, target, remote_project_dir, *, parent_identity, intent_id):
        self._observe_current(target, remote_project_dir)
        if self.state != "ABSENT" or parent_identity != self.parent or not intent_id or self.provisions:
            raise AssertionError("inert Project intent differs or repeats")
        self.provisions += 1
        self.state = "EXISTING"
        return self.parent, self.project


class _Adapter:
    def __init__(self, fixture, installation, snapshot, authority, source):
        self.fixture, self.snapshot = fixture, snapshot
        self.command = bridge._prepare_program_invocation(snapshot, fixture.current_invocation)[0]
        fixture.assertEqual(self.command[:2], ("/usr/bin/ssh", "-F"))
        fixture.assertEqual(self.command[3:5], ("--", "direct-server"))
        fixture.assertEqual(source, _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES)
        self.handle, self.raw, self.output = object(), bytearray(), None
        self.closed = False
        self.steps = []
        fixture.adapters.append(self)
        if fixture.stop_at_adapter:
            fixture.life.manage("STOP", peer_uid=0)
    def check_reaper(self): self.steps.append("check")
    def spawn_suspended(self):
        self.fixture.transport._require_current_completion_owner()
        self.fixture.assertTrue(self.fixture.life.m.locked())
        self.steps.append("spawn")
        return self.handle
    def register(self, handle): self.steps.append("register")
    def resume(self, handle): self.steps.append("resume")
    def record_owner(self, handle): self.steps.append("owner")
    def pid(self, handle): return 37
    def observe(self, handle): return Observation(37, True, exit_status=0) if self.closed else None
    def write(self, handle, data): self.raw.extend(data); return len(data)
    def close_input(self, handle):
        if self.closed: return
        self.closed = True
        request = _bridge._decode_frame(bytes(self.raw), cap=self.fixture.current_invocation.operation.stdin_cap, field="inert wire")
        op, payload = request["operation"], request["payload"]["request_payload"]
        self.fixture.wires.append(op)
        if op == "ALLOCATE_WORKSPACE":
            result = {"remote_workspace": request["binding"]["remote_workspace"], "workspace_physical_token": directory_token(request["binding"]["remote_workspace"])}
        elif op == "STAGE_EXACT_FILE":
            result = {k:v for k,v in payload.items() if k != "content_base64"}
            result["artifact_physical_token"] = "staged-" + payload["portable_name"]
        elif op == "SUBMIT_QSUB_ONCE":
            if self.fixture.uncertain: raise OSError("inert response lost after submit")
            result = {"job_id": "123.server"}
        else: raise AssertionError("unexpected wire")
        self.output = _bridge._encode_frame({"protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, "operation": op, "status": "ok", "result": result})
    def read(self, handle, name, cap):
        if name == "stderr": return b""
        if self.output is None: return None
        chunk, self.output = self.output[:cap], self.output[cap:]
        return chunk
    def peek_exit(self, handle): self.steps.append("peek"); return 0
    def reap_once(self, handle): self.steps.append("reap"); return 0
    def release(self, handle): self.steps.append("release")
    def pause(self, seconds): pass


class ServiceTests(Fixture):
    def setUp(self):
        self.root = Path(os.environ.get("AUTO_G16_MANAGED_TEST_SCRATCH", tempfile.gettempdir())).resolve() / str(uuid4())
        self.root.mkdir(parents=True)
        for name in ("intake", "local", "transport", "publisher"): (self.root/name).mkdir()
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.stack.enter_context(patch("socket.socket", side_effect=AssertionError("socket forbidden")))
        f = v30.TransportFixture(); f.setUp(); self.addCleanup(f.doCleanups)
        raw = direct_profile(f.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES))
        manifest = json.loads(raw.runtime_contents[_driver._MANIFEST_NAME])
        manifest.update(schema="auto-g16-v3-transport-deployment-manifest/3", bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
        manifest["trust_roots"] = {k:v for k,v in manifest["trust_roots"].items() if k in completion._ROOT_RULES}
        profile = replace(raw, platform_paths={**raw.platform_paths, "xtb_executable_path": "/opt/xtb/6.7.1/bin/xtb", "xtb_data_path": "/opt/xtb/6.7.1/share/xtb"}, runtime_contents={_driver._TABLE_NAME:_driver._OPERATION_TABLE_BYTES, _driver._RESOURCE_DESCRIPTOR_NAME:v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES, completion._DEPLOYMENT_NAME:canonical_json_bytes(manifest), _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME:_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES, "xtb":b"inert executable", completion._DATA_NAME:lane.xtb_runtime_data_manifest_bytes()})
        self.q, self.evidence = qualification_fixture(profile, queue="batch")
        self.profile = replace(profile, runtime_contents={**profile.runtime_contents, completion._Q_NAME:seal(self.q)})
        self.resolved = execution.resolve_server_profile(self.profile)
        self.core = core.SQLiteRuntimeStore(self.root/"core.sqlite3"); self.addCleanup(self.core.close)
        self.approvals = approval.SQLiteApprovalStore(self.root/"approval.sqlite3"); self.addCleanup(self.approvals.close)
        self.core.store_project(core.Project(project_id="project-1"))
        self.core.store_workflow_run(core.WorkflowRun(workflow_run_id="run-1", project_id="project-1", workflow_name="inert"))
        self.installation = parse_description(json_bytes({"schema":"auto-g16-managed-installation-description/1", "installation_id":"inert-v1", "executor_uid":701, "desktop_uid":501}))
        self.life = Lifecycle(self.installation, Veto())
        self.registry = Registry(self.life, self.installation.description_sha256)
        self.intake = Intake(store=self.core, registry=self.registry, scratch=self.root/"intake", project_id="project-1", workflow_run_id="run-1", namespace="403f2c33-8d00-4e5e-b3bd-1b9cbbda41b6", profile=self.resolved, resources={"tier":"simple", "cores":8, "memory_mb":12288, "walltime_seconds":3600, "queue":"batch"}, completion_material=completion._prepare_publisher_pilot_rendering_material(self.profile, self.resolved), requester_uid=501)
        self.addCleanup(self.intake.files.close)
        self.clock = Clock()
        self.review = Review(intake=self.intake, approval_store=self.approvals, reviewer_uid=501, installation_hash=self.installation.description_sha256, requester_uids=(501,), not_before=_timestamp(self.clock.wall+timedelta(seconds=1200)), not_after=_timestamp(self.clock.wall+timedelta(seconds=3600)), clock=self.clock)
        self.transport = program._ProgramTransportStore._create_completion_store(self.root/"transport"/"program.sqlite3", approved_root=self.root/"transport"); self.addCleanup(self.transport.close)
        self.composition = service._Composition(installation=self.installation, life=self.life, review=self.review, profile=self.profile, program_transport_store=self.transport)
        self.adapters, self.wires, self.handoffs = [], [], []
        self.uncertain = self.stop_at_adapter = False
        self.stack.enter_context(patch("auto_g16._managed_native.darwin.DarwinOwner", side_effect=lambda *args:_Adapter(self, *args)))
        # Production entry is unchanged. Replace only its lowest process dispatch
        # in this test; the real driver, frames, stores and supervision all run.
        def inert(scope, invocation):
            self.current_invocation = invocation
            driver = service._DRIVER.get()
            self.assertIsNone(driver._active)
            self.handoffs.append((driver, scope, invocation, bridge._DIRECT_WIRE_HANDOFF.get()))
            return service._run_owned(scope, invocation)
        self.stack.enter_context(patch.object(service, "run_direct", side_effect=inert))

    def bind_snapshot(self, slot):
        remote = "/home/user100/SDL/project-1"
        journal = _ProductionProvisioningJournal.create_new(self.root/"projects.sqlite3", approved_root=self.root)
        self.addCleanup(journal.close)
        attestor = _InertProjectPeer(self.profile, self.resolved, remote)
        provisioning = _ProjectProvisioningService._from_project_attestor(attestor=attestor, target=self.resolved, journal=journal)
        binding = provisioning.provision_remote_project(project=self.intake.project, target=self.resolved, remote_project_dir=remote)
        owner = _ProgramExecutionSnapshotService._for_production(project_provisioning=provisioning, target=self.resolved)
        attempt = slot.records[3].attempt_id
        (self.root/"local"/"project-1").mkdir(exist_ok=True)
        workspace = execution.WorkspaceBinding(project=self.intake.project, attempt_id=attempt, local_approved_root=str(self.root/"local"), local_attempt_dir=str(self.root/"local"/"project-1"/attempt), rtwin_approved_root=r"C:\RTWIN", rtwin_attempt_dir=rf"C:\RTWIN\project-1\{attempt}", remote_approved_root="/home/user100/SDL", remote_attempt_dir=remote+"/"+attempt)
        resources = execution.ResolvedResourceRequest(resource_spec=slot.records[2], cores=8, memory_mb=12288, walltime_seconds=3600, queue="batch")
        snapshot = owner.prepare(self.core, attempt_id=attempt, calculation_plan_id=slot.records[1].calculation_plan_id, resource_spec_id=slot.records[2].resource_spec_id, program_execution_spec=slot.spec, project_physical_binding=binding, resolved_resource_request=resources, resolved_server_profile=self.resolved, workspace_binding=workspace, completion_rendering_material=self.intake.completion_material)
        self.review.bind_offline_snapshot(slot.key[2], snapshot)
        self._publisher(snapshot)
        return snapshot

    def _publisher(self, snapshot):
        def write(name, raw):
            path = self.root/"publisher"/name
            with path.open("xb") as stream: stream.write(raw)
            return file_binding(path)
        qpin = write(completion._Q_NAME, self.profile.runtime_contents[completion._Q_NAME])
        evidence = dict(self.evidence)
        owner, gate = b"INERT owner evidence", b"INERT gate evidence"
        for raw in (owner, gate): evidence[sha256(raw).hexdigest()] = raw
        pins = tuple(write(str(i)+".txt", raw) for i,raw in enumerate(evidence.values()))
        basis = {"schema":"auto-g16-v31-publisher-pilot-deployment/1", "source_commit":"a"*40, "source_tree":"b"*40,
            "resolved_server_profile_id":self.resolved.resolved_server_profile_id, "effective_config_sha256":self.resolved.effective_config_sha256, "program_execution_snapshot_id":snapshot.program_execution_snapshot_id,
            "qualification_payload_sha256":json.loads(self.profile.runtime_contents[completion._Q_NAME])["payload_sha256"], "qualification_file_sha256":qpin.sha256, "qualification_size_bytes":qpin.size_bytes, "qualification_path":qpin.path, "qualification_parent_chain":[{"device":d,"inode":i} for d,i in qpin.parent_chain], "qualification_file_identity":{"device":qpin.file_identity[0],"inode":qpin.file_identity[1]}, "probe_evidence_manifest_sha256":self.q["evidence_manifest_sha256"], "owner_q_acceptance_evidence_sha256":sha256(owner).hexdigest(), "pilot_live_gate_evidence_sha256":sha256(gate).hexdigest(), "pilot_window":PILOT}
        bpin = write("v31-publisher-pilot-deployment.json", canonical_json_bytes(basis))
        self.stack.enter_context(patch.object(bridge, "_FIXED_PUBLISHER_INSTALLATION", bridge._FixedPublisherInstallation(bpin,qpin,pins,"a"*40,"b"*40)))

    def ready(self):
        slot, ids = self.chain()
        self.clock.advance(1200)
        self.life.manage("OPEN", peer_uid=0)
        request = {"protocol":service._PROTOCOL, "operation":"EXECUTE_APPROVED_ATTEMPT", "scope":dict(attempt_id=slot.records[3].attempt_id, snapshot_id=slot.snapshot.program_execution_snapshot_id, **dict(zip(("scientific_approval_id","batch_submit_approval_id","operational_confirmation_id"), ids)))}
        return slot, request

    def test_01_complete_original_chain_and_repeat_has_no_second_submit(self):
        slot, request = self.ready()
        result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual((result["disposition"], result["core_state"]), ("COMPLETED", "SUBMITTED"), result)
        self.assertTrue(result["submission_consumed"])
        self.assertEqual(self.wires.count("SUBMIT_QSUB_ONCE"), 1)
        count = len(self.adapters)
        repeated = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(repeated["reason"], "STATE_NOT_ELIGIBLE")
        self.assertEqual(len(self.adapters), count)
        self.assertTrue(all(a.steps.count("reap") == 1 and a.steps[-1] == "release" for a in self.adapters))
        self.assertEqual(self.registry.allocated_count, 1)
        self.assertIsNone(service._ACTIVE.get()); self.assertIsNone(service._DRIVER.get())
        self.assertIsNone(bridge._DIRECT_WIRE_HANDOFF.get())
        self.assertEqual(len(self.handoffs), len(self.adapters))
        for driver, snapshot, invocation, handoff in self.handoffs:
            self.assertTrue(handoff._used)
            with self.assertRaises(TransportBoundaryError): handoff.assert_consumed(driver, snapshot, invocation)
            with self.assertRaises(TransportBoundaryError): handoff.consume(driver, snapshot, invocation)

    def test_02_unknown_preserves_consumption_and_retained_child(self):
        slot, request = self.ready(); self.uncertain = True
        result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual((result["disposition"], result["core_state"]), ("UNRESOLVED", "UNKNOWN"), result)
        self.assertTrue(result["submission_consumed"])
        self.assertEqual(self.life.state, "BLOCKED")
        count = len(self.adapters)
        self.composition._dispatch("consumer", request, 501)
        self.assertEqual(len(self.adapters), count)
        self.assertEqual(self.wires.count("SUBMIT_QSUB_ONCE"), 1)
        self.assertNotIn("release", self.adapters[-1].steps)
        self.assertIsNotNone(self.life.children[-1].handle)

    def test_03_stop_after_claim_before_spawn_preserves_intent(self):
        slot, request = self.ready(); self.stop_at_adapter = True
        self.composition._dispatch("consumer", request, 501)
        self.assertNotEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)
        self.assertEqual(self.wires, [])
        self.assertTrue(all("spawn" not in a.steps for a in self.adapters))

    def test_04_spliced_approval_rejected_before_claim(self):
        slot, request = self.ready()
        request["scope"]["scientific_approval_id"] = request["scope"]["batch_submit_approval_id"]
        result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["disposition"], "REJECTED")
        self.assertIsNone(result["core_state"])
        self.assertEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)
        self.assertEqual(self.adapters, [])

    def _assert_preliminary_rejection_burns_handoff(self, *, wrong_scope):
        slot, request = self.ready()
        def rejected(scope, invocation):
            handoff = bridge._DIRECT_WIRE_HANDOFF.get()
            bad_scope, bad_invocation = (object(), invocation) if wrong_scope else (scope, object())
            with self.assertRaises(TransportBoundaryError):
                service._run_owned(bad_scope, bad_invocation)
            self.assertTrue(handoff._used)
            with self.assertRaisesRegex(TransportBoundaryError, "already consumed"):
                service._run_owned(scope, invocation)
            self.assertEqual(self.adapters, [])
            self.assertEqual(self.wires, [])
            raise program._ProgramEffectUnknown("inert preliminary rejection")
        with patch.object(service, "run_direct", side_effect=rejected):
            result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["core_state"], "UNKNOWN", result)
        self.assertTrue(result["submission_consumed"])
        self.assertEqual(self.adapters, [])
        self.assertEqual(self.wires, [])
        self.assertIsNone(bridge._DIRECT_WIRE_HANDOFF.get())

    def test_17_wrong_scope_burns_handoff_before_reentry(self):
        self._assert_preliminary_rejection_burns_handoff(wrong_scope=True)

    def test_18_wrong_invocation_type_burns_handoff_before_reentry(self):
        self._assert_preliminary_rejection_burns_handoff(wrong_scope=False)

    def test_05_unbound_driver_and_low_level_call_rejected(self):
        slot, request = self.ready()
        with self.assertRaises(TransportBoundaryError):
            bridge._RTWinProgramEffectDriver(snapshot=slot.snapshot, current_profile=self.profile, program_transport_store=self.transport)
        with self.assertRaises(TransportBoundaryError): service._run_owned(slot.snapshot, None)
        self.assertEqual(self.adapters, [])

    def test_06_query_reads_original_intent_and_bad_peer_discloses_nothing(self):
        slot, request = self.ready()
        query = {"protocol":service._PROTOCOL, "operation":"QUERY_LOCAL_STATUS", "scope":{"attempt_id":slot.records[3].attempt_id}}
        before = self.composition._dispatch("consumer", query, 501)
        self.assertEqual((before["core_state"], before["submission_consumed"]), ("PLANNED", False))
        self.core.record_submission_intent(slot.records[3].attempt_id, slot.snapshot.effect_intent_id)
        after = self.composition._dispatch("consumer", query, 501)
        self.assertEqual((after["core_state"], after["submission_consumed"]), ("SUBMISSION_INTENT_RECORDED", True))
        denied = self.composition._dispatch("consumer", query, 502)
        self.assertEqual(denied["reason"], "ACCESS_DENIED")
        self.assertTrue(all(denied[k] is None for k in ("attempt_id", "core_state", "submission_consumed")))
        self.assertEqual(self.adapters, [])

    def test_07_absent_owner_guard_rejects_before_adapter(self):
        slot, request = self.ready()
        ids = tuple(request["scope"][k] for k in ("scientific_approval_id", "batch_submit_approval_id", "operational_confirmation_id"))
        with self.life.composition():
            token = service._ACTIVE.set(service._Call(self.composition, slot, slot.snapshot, ids, 501))
            driver = bridge._RTWinProgramEffectDriver(snapshot=slot.snapshot, current_profile=self.profile, program_transport_store=self.transport)
            owned = service._DRIVER.set(driver)
            try:
                authority = driver._authority()
                invocation = bridge._ProgramRTWinInvocation(_driver._operation("ALLOCATE_WORKSPACE"), authority, self.profile, {}, slot.snapshot.program_execution_snapshot_id)
                with self.transport._completion_guard():
                    handoff = bridge._DirectWireHandoff(driver, invocation)
                wire_token = bridge._DIRECT_WIRE_HANDOFF.set(handoff)
                try:
                    with self.assertRaises(TransportBoundaryError): service._run_owned(slot.snapshot, invocation)
                    self.assertTrue(handoff._used)
                    self.assertEqual(self.adapters, [])
                finally:
                    handoff.close(); bridge._DIRECT_WIRE_HANDOFF.reset(wire_token)
            finally:
                driver.close(); service._DRIVER.reset(owned); service._ACTIVE.reset(token)

    def test_08_material_and_review_dispatch_reuse_owners(self):
        from tests.v3.managed_offline._fixtures import payload
        value = payload()
        result = self.composition._dispatch("material", {"protocol":"auto-g16-material-prepare/1", "operation":"PREPARE_LOCAL", "payload":value}, 501)
        self.assertEqual(result["status"], "PREPARED_LOCAL_ONLY")
        slot = self.registry.index[value["intake_id"]]
        review = self.composition._dispatch("review", {"protocol":"auto-g16-review-bridge/1", "operation":"PREPARE_REVIEW", "payload":{"gate":"scientific", "subject_id":slot.cells["scientific"].subject}}, 501)
        self.assertEqual(review["status"], "VIEW_READY")
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.adapters, [])

    def test_09_reply_loss_keeps_original_state_without_reexecution(self):
        slot, request = self.ready()
        class Connection:
            def __init__(self): self.closed = False
            def settimeout(self, seconds): pass
            def sendall(self, raw): raise BrokenPipeError("client disconnected")
            def close(self): self.closed = True
        connection = Connection()
        with patch.object(service.ipc, "receive", return_value=(request,501)), self.assertRaises(BrokenPipeError):
            self.composition.handle("consumer", connection)
        self.assertTrue(connection.closed)
        self.assertEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.SUBMITTED)
        self.assertEqual(self.wires.count("SUBMIT_QSUB_ONCE"), 1)
        count = len(self.adapters)
        self.composition._dispatch("consumer", request, 501)
        self.assertEqual(len(self.adapters), count)

    def test_10_window_expiry_before_claim_and_after_claim(self):
        slot, request = self.ready()
        self.clock.advance(2401)
        result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["disposition"], "REJECTED")
        self.assertEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)
        self.assertEqual(self.adapters, [])

    def test_11_recovery_requests_cannot_create_continuation(self):
        slot, request = self.ready()
        for operation in ("RECONCILE_EXACT_JOB", "COLLECT_APPROVED_EPOCH"):
            altered = {**request, "operation":operation}
            result = self.composition._dispatch("consumer", altered, 501)
            self.assertEqual(result["disposition"], "REJECTED")
        self.assertEqual(self.adapters, [])
        self.assertEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)

    def test_12_record_failure_preserves_consumed_intent_and_stops_wire(self):
        slot, request = self.ready()
        with patch.object(self.transport, "record_effect", side_effect=OSError("inert disk failure")):
            result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["disposition"], "UNRESOLVED")
        self.assertNotEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)
        self.assertEqual(self.life.state, "BLOCKED")
        count = len(self.adapters)
        self.composition._dispatch("consumer", request, 501)
        self.assertEqual(len(self.adapters), count)
        self.assertNotIn("SUBMIT_QSUB_ONCE", self.wires)

    def test_19_expired_decision_allows_explicit_new_generation(self):
        slot = self.make()
        old = self.prepare(slot, "scientific")["payload"]
        self.clock.advance(600)
        expired = self.decide(old)
        self.assertEqual((expired["status"], expired["reason"]), ("REJECTED", "EXPIRED"))
        self.assertEqual(slot.cells["scientific"].state, "EXPIRED_UNDECIDED")
        self.assertEqual(self.life.state, "READY_CLOSED")
        self.assertEqual(self.approvals.evidence_count(), 0)
        fresh = self.prepare(slot, "scientific")
        self.assertEqual(fresh["status"], "VIEW_READY")
        new = fresh["payload"]
        self.assertNotEqual(old["approved_id"], new["approved_id"])
        self.assertNotEqual(old["review_view_id"], new["review_view_id"])
        self.assertEqual(slot.cells["scientific"].generation, 2)
        self.assertEqual(self.decide(old)["reason"], "UNKNOWN_VIEW")
        self.assertEqual(self.life.state, "READY_CLOSED")
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.decide(new)["status"], "RECORDED")
        self.assertEqual(self.approvals.evidence_count(), 1)
        self.assertEqual(self.life.state, "READY_CLOSED")
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_20_unknown_read_local_preserves_normal_preparation(self):
        from tests.v3.managed_offline._fixtures import payload
        value = payload()
        request = {"protocol": "auto-g16-material-prepare/1", "operation": "READ_LOCAL",
                   "payload": {"intake_id": value["intake_id"]}}
        result = self.composition._dispatch("material", request, 501)
        self.assertEqual((result["status"], result["reason"], result["payload"]),
                         ("REJECTED", "MISSING_DEPENDENCY", None))
        self.assertEqual(self.life.state, "READY_CLOSED")
        self.assertEqual(self.registry.allocated_count, 0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(list((self.root / "intake").iterdir()), [])
        prepared = self.composition._dispatch("material", {**request,
            "operation": "PREPARE_LOCAL", "payload": value}, 501)
        self.assertEqual(prepared["status"], "PREPARED_LOCAL_ONLY")
        found = self.composition._dispatch("material", request, 501)
        self.assertEqual(found["status"], "FOUND_LOCAL")
        self.assertEqual(found["payload"], prepared["payload"])
        self.assertEqual(self.registry.allocated_count, 1)
        self.assertEqual(self.life.state, "READY_CLOSED")
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_21_association_corruption_remains_permanently_blocked(self):
        slot = self.make()
        self.registry.index.clear()
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "LIFECYCLE_BLOCKED")
        self.registry.index[slot.key[2]] = slot
        self.registry.check()
        self.assertEqual(self.life.state, "BLOCKED")
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_22_identity_drift_remains_blocked_after_restoration(self):
        slot = self.make()
        original = self.life.installation
        self.life.installation = object()
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "LIFECYCLE_BLOCKED")
        self.life.installation = original
        self.life._integrity()
        self.assertEqual(self.life.state, "BLOCKED")
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_23_approval_persistence_failure_keeps_uncertain_cell_blocked(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        with patch.object(self.approvals, "store_scientific_approval", side_effect=OSError("inert persistence failure")):
            result = self.decide(view)
        self.assertEqual((result["status"], result["reason"]), ("UNCERTAIN", "STORE_UNAVAILABLE"))
        self.assertEqual(slot.cells["scientific"].state, "UNCERTAIN")
        self.assertEqual(self.life.state, "BLOCKED")
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_24_request_marker_never_clears_existing_poison(self):
        slot = self.make()
        old = self.prepare(slot, "scientific")["payload"]
        self.clock.advance(600)
        self.assertEqual(self.decide(old)["reason"], "EXPIRED")
        self.life.poison()
        self.assertEqual(self.decide(old)["reason"], "UNKNOWN_VIEW")
        self.assertEqual(self.life.state, "BLOCKED")
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_25_unclassified_or_mutating_rejections_still_poison(self):
        class ForeignRequestRejected(RequestRejected):
            pass
        cases = [(Rejected("SCOPE"), True), (Rejected("EXPIRED"), True),
                 (RequestRejected("STORE_UNAVAILABLE"), True),
                 (RequestRejected([]), True), (ForeignRequestRejected("EXPIRED"), True),
                 (RequestRejected("EXPIRED"), False), (OSError("inert failure"), True)]
        for error, readonly in cases:
            with self.subTest(error=repr(error), readonly=readonly):
                life = Lifecycle(self.installation, Veto())
                with self.assertRaises(type(error)):
                    with life.composition(readonly=readonly):
                        raise error
                self.assertEqual(life.state, "BLOCKED")
                self.assertIsNone(life.owner)
                self.assertFalse(life.c.locked())
                with self.assertRaises(Rejected):
                    life.manage("OPEN", peer_uid=0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_26_request_rejection_rechecks_veto_before_leaving(self):
        with self.assertRaisesRegex(Rejected, "LIFECYCLE_BLOCKED"):
            with self.life.composition(readonly=True):
                self.life.veto.valid = False
                raise RequestRejected("EXPIRED")
        self.life.veto.valid = True
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertIsNone(self.life.owner)
        self.assertFalse(self.life.c.locked())
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_27_request_marker_cannot_soften_launch_failure(self):
        self.life.manage("OPEN", peer_uid=0)
        def rejected():
            raise RequestRejected("EXPIRED")
        with self.assertRaisesRegex(RequestRejected, "EXPIRED"):
            with self.life.composition(readonly=True):
                self.life.launch(object(), b"", object(), rejected)
        self.assertEqual(self.life.state, "BLOCKED")
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual(self.life.children, [])
        self.assertEqual((self.adapters, self.wires), ([], []))

    def test_13_same_wire_cannot_be_dispatched_twice(self):
        slot, request = self.ready()
        original = service.run_direct
        def twice(scope, invocation):
            result = original(scope, invocation)
            before = len(self.adapters)
            with self.assertRaisesRegex(TransportBoundaryError, "already consumed"):
                service._run_owned(scope, invocation)
            self.assertEqual(len(self.adapters), before)
            self.assertIsNone(service._DRIVER.get()._active)
            return result
        with patch.object(service, "run_direct", side_effect=twice):
            result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["core_state"], "SUBMITTED", result)
        self.assertEqual(self.wires.count("SUBMIT_QSUB_ONCE"), 1)

    def test_14_foreign_invocation_burns_handoff_before_any_adapter(self):
        slot, request = self.ready()
        def foreign(scope, invocation):
            handoff = bridge._DIRECT_WIRE_HANDOFF.get()
            with self.assertRaisesRegex(TransportBoundaryError, "foreign"):
                service._run_owned(scope, replace(invocation))
            self.assertTrue(handoff._used)
            with self.assertRaisesRegex(TransportBoundaryError, "already consumed"):
                service._run_owned(scope, invocation)
            self.assertEqual(self.adapters, [])
            raise program._ProgramEffectUnknown("inert rejected handoff")
        with patch.object(service, "run_direct", side_effect=foreign):
            result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["core_state"], "UNKNOWN", result)
        self.assertTrue(result["submission_consumed"])
        self.assertEqual(self.adapters, [])
        self.assertIsNone(bridge._DIRECT_WIRE_HANDOFF.get())

    def test_15_changed_wire_is_not_accepted_by_same_object_identity(self):
        slot, request = self.ready()
        def changed(scope, invocation):
            invocation.request["operation"] = "SUBMIT_QSUB_ONCE"
            with self.assertRaisesRegex(TransportBoundaryError, "changed"):
                service._run_owned(scope, invocation)
            self.assertEqual(self.adapters, [])
            raise program._ProgramEffectUnknown("inert wire drift")
        with patch.object(service, "run_direct", side_effect=changed):
            result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["core_state"], "UNKNOWN", result)
        self.assertEqual(self.adapters, [])

    def test_16_foreign_thread_and_expired_context_reject(self):
        slot, request = self.ready()
        captured = []
        def foreign_thread(scope, invocation):
            handoff = bridge._DIRECT_WIRE_HANDOFF.get()
            captured.append((service._DRIVER.get(), scope, invocation, handoff))
            with patch.object(bridge, "get_ident", return_value=-1):
                with self.assertRaisesRegex(TransportBoundaryError, "foreign"):
                    service._run_owned(scope, invocation)
            raise program._ProgramEffectUnknown("inert wrong thread")
        with patch.object(service, "run_direct", side_effect=foreign_thread):
            result = self.composition._dispatch("consumer", request, 501)
        self.assertEqual(result["core_state"], "UNKNOWN", result)
        driver, scope, invocation, handoff = captured[0]
        token = bridge._DIRECT_WIRE_HANDOFF.set(handoff)
        try:
            with self.assertRaisesRegex(TransportBoundaryError, "expired"):
                handoff.assert_consumed(driver, scope, invocation)
        finally:
            bridge._DIRECT_WIRE_HANDOFF.reset(token)
        self.assertEqual(self.adapters, [])
