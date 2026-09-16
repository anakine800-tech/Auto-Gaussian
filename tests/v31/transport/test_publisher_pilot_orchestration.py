"""R4 private product paths with inert stores/bytes, never target qualification."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import base64
import copy
import inspect
import json
import os
import shlex
import sys
import unittest
from unittest.mock import patch

from auto_g16 import approval, core, execution
from auto_g16.execution import _program_completion as c
from auto_g16.execution import _program_completion_wrapper as w
from auto_g16.execution import program as p
from auto_g16.execution import program_runtime as runtime
from auto_g16.transport import _program_rtwin as rtwin
from auto_g16.transport import program as transport
from auto_g16.transport._canonical import TransportBoundaryError
from scripts import run_v31_publisher_pilot as controller
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport import test_program_completion as old
from tests.v31.transport import test_program_composition as composition

OBS = {"started_at": "1999-01-01T00:00:00.000000Z", "finished_at": "1999-01-01T00:00:01.000000Z"}
PILOT = {"started_at": "2000-01-01T00:00:00.000000Z", "finished_at": "2999-01-01T00:00:00.000000Z"}


def digest(raw):
    return {"sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}


def seal(payload):
    return c._receipt_json({"payload": payload, "payload_sha256": c.semantic_sha256(c.freeze_mapping(payload, "test Q"))})


def qualification_fixture(profile, queue="simple"):
    """Explicit synthetic schema/identity fixture; PASS labels are not real probes."""
    resolved = execution.resolve_server_profile(profile)
    evidence = {}
    def ev(role):
        raw = ("INERT SYNTHETIC ONLY " + role + "\n").encode()
        evidence[sha256(raw).hexdigest()] = raw
        return digest(raw)
    def probe(case):
        return {"case_id": case, "outcome": "PASS", "evidence": ev(case), "observed_window": OBS}
    roots = json.loads(profile.runtime_contents[c._DEPLOYMENT_NAME])["trust_roots"]
    py = roots["server_python"]
    machine = sha256(b"synthetic-machine\n").hexdigest()
    host_key = c.semantic_sha256(c.freeze_mapping({"machine_id_sha256": machine}, "test host"))
    node = {"device": 1, "inode": 1}
    mount = {"mount_id": 1, "device_major": 0, "device_minor": 1, "root": "/", "mount_point": "/", "filesystem_type": "synthetic", "source": "synthetic", "mount_options": ["rw"], "super_options": ["rw"]}
    locations = []
    paths = (resolved.remote_root, py["path"], resolved.platform_paths["xtb_executable_path"], resolved.platform_paths["xtb_data_path"])
    for role,path in zip(c._Q_ROLES, paths):
        locations.append({"role": role, "path": path, "parent_chain": [node] * (len(path.split("/"))-1), "object": node, "mount": mount, "evidence": ev(role)})
    host = {"host_key": host_key, "machine_id_sha256": machine, "boot_id": "11111111-2222-3333-4444-555555555555", "kernel_release": "synthetic-linux", "architecture": "x86_64", "namespaces": {"mount": node, "pid": node}, "locations": locations, "observed_window": OBS, "identity_evidence": ev("identity"), "probes": [probe(f"P{i:02d}") for i in range(1,8)]}
    payload = {"schema": c._Q_SCHEMA, "contract_sha256": c._PUBLISHER_CONTRACT_SHA256,
        "scope": {"backend": "legacy_rtwin_pbs", "program_kind": "xtb", "adapter_id": "auto-g16-v31-xtb", "adapter_contract_version": 3, "completion_mode": c._MODE, "operations": ["optimize", "single-point"]},
        "implementation": {"commit": "a"*40, "tree": "b"*40, "wrapper_source": digest(w._PUBLISHER_WRAPPER_SOURCE.encode()), "probe_source": digest(w._PUBLISHER_PROBE_SOURCE.encode())},
        "profile_basis_sha256": c._publisher_profile_basis(resolved),
        "runtime": {"deployment_manifest": dict(resolved.runtime_identities[c._DEPLOYMENT_NAME]), "server_python": {"path": py["path"], "sha256": py["expected_sha256"], "size_bytes": py["expected_size_bytes"]}, "xtb": {"path": resolved.platform_paths["xtb_executable_path"], **dict(resolved.runtime_identities["xtb"])}, "xtb_runtime_data_manifest": dict(resolved.runtime_identities[c._DATA_NAME])},
        "execution_domain": {"target_identity_sha256": c.semantic_sha256(resolved.target_identity), "remote_user": resolved.remote_user, "remote_root": resolved.remote_root, "queue": queue, "eligible_host_keys": [host_key], "scheduler_scope_evidence": ev("scheduler")},
        "hosts": [host], "observation_window": OBS, "evidence_manifest_sha256": "0"*64, "controller_probe": probe("P08")}
    manifest_raw = c._receipt_json(controller._probe_index(payload))
    payload["evidence_manifest_sha256"] = sha256(manifest_raw).hexdigest()
    evidence[payload["evidence_manifest_sha256"]] = manifest_raw
    return payload, evidence


def file_binding(path):
    path = Path(path)
    parents = [Path("/")]
    for part in path.parts[1:-1]:
        parents.append(parents[-1] / part)
    nodes = tuple((p.stat().st_dev, p.stat().st_ino) for p in parents)
    st = path.stat()
    return rtwin._PublisherFileBinding(str(path), nodes, (st.st_dev,st.st_ino), sha256(path.read_bytes()).hexdigest(), st.st_size)


class _PilotFixture(lane.LaneAFixture):
    def profile(self, **kwargs):
        profile = lane.LaneAFixture.profile(self, **kwargs)
        profile = replace(profile, runtime_contents={**profile.runtime_contents, c._DEPLOYMENT_NAME: c._receipt_json(old.manifest())})
        q, _ = qualification_fixture(profile)
        return replace(profile, runtime_contents={**profile.runtime_contents, c._Q_NAME: seal(q)})

    def resolved(self, **kwargs):
        return execution.resolve_server_profile(self.profile(**kwargs))

    def setUp(self):
        super().setUp()
        self.current_profile = self.profile()
        self.q = json.loads(self.current_profile.runtime_contents[c._Q_NAME])["payload"]
        self.spec = p._prepare_program_execution_spec(program_kind="xtb", executable_path=lane.XTB_EXECUTABLE_PATH, executable_size_bytes=len(lane.XTB_EXECUTABLE_BYTES), executable_sha256=sha256(lane.XTB_EXECUTABLE_BYTES).hexdigest(), input_name="input.xyz", input_bytes=lane.XYZ, program_data=self.xtb_data(), resolved_profile=self.resolved(), completion_mode=c._MODE)
        self.material = c._prepare_publisher_pilot_rendering_material(self.current_profile, self.resolved())
        self.snapshot = self.make_snapshot(self.material)
        root = self.root / "transport"; root.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(root / "program.sqlite3", approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.driver = composition._Driver()
        self.input_bytes = {"input.xyz": lane.XYZ}
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}

    def make_snapshot(self, material):
        return self.snapshot_service.prepare(self.store, attempt_id="attempt-1", calculation_plan_id="plan-1", resource_spec_id="resource-1", program_execution_spec=self.spec, project_physical_binding=self.physical_binding(), resolved_resource_request=self.resources(), resolved_server_profile=self.resolved(), workspace_binding=self.workspace(), completion_rendering_material=material)

    execute = composition.ProgramCompositionTests.execute
    kwargs = old.CompletionTests.kwargs
    publish = old.CompletionTests.publish
    collect = old.CompletionTests.collect

    def install_fixture(self):
        is_crest = self.snapshot.program_execution_spec.program_kind == "crest"
        from auto_g16.execution import _crest_completion as crest
        qname = crest._Q_NAME if is_crest else c._Q_NAME
        target = self.snapshot.resolved_server_profile
        root = self.root / "installation"; root.mkdir()
        def write(name, raw):
            path = root / name
            with path.open("xb") as out: out.write(raw)
            return file_binding(path)
        _, evidence = qualification_fixture(replace(self.current_profile, runtime_contents={k:v for k,v in self.current_profile.runtime_contents.items() if k != qname}), queue=self.snapshot.resolved_resource_request.queue)
        if is_crest:
            from tests.v31.transport.test_crest_loader import LOADER_REVIEW, LOADER_EVIDENCE
            for raw in (LOADER_REVIEW, LOADER_EVIDENCE):
                evidence[sha256(raw).hexdigest()] = raw
            index = c._receipt_json(controller._probe_index(self.q))
            evidence[sha256(index).hexdigest()] = index
        qpin = write(qname, self.current_profile.runtime_contents[qname])
        owner_raw = b"SYNTHETIC FIXTURE: reviewed exact Q accepted only inside inert test.\n"
        live_raw = b"SYNTHETIC FIXTURE: bounded single Attempt only inside inert test.\n"
        evidence[sha256(owner_raw).hexdigest()] = owner_raw
        evidence[sha256(live_raw).hexdigest()] = live_raw
        pins = tuple(write(f"evidence-{i}.txt", raw) for i,raw in enumerate(evidence.values()))
        basis = {"schema": "auto-g16-v31-publisher-pilot-deployment/2" if is_crest else "auto-g16-v31-publisher-pilot-deployment/1", "source_commit": "a"*40, "source_tree": "b"*40, "resolved_server_profile_id": target.resolved_server_profile_id, "effective_config_sha256": target.effective_config_sha256, "program_execution_snapshot_id": self.snapshot.program_execution_snapshot_id,
            "qualification_payload_sha256": json.loads(self.current_profile.runtime_contents[qname])["payload_sha256"], "qualification_file_sha256": qpin.sha256, "qualification_size_bytes": qpin.size_bytes, "qualification_path": qpin.path, "qualification_parent_chain": [{"device":d,"inode":i} for d,i in qpin.parent_chain], "qualification_file_identity": {"device":qpin.file_identity[0],"inode":qpin.file_identity[1]},
            "probe_evidence_manifest_sha256": self.q["evidence_manifest_sha256"], "owner_q_acceptance_evidence_sha256": sha256(owner_raw).hexdigest(), "pilot_live_gate_evidence_sha256": sha256(live_raw).hexdigest(), "pilot_window": PILOT}
        bpin = write("v31-publisher-pilot-deployment.json", c._receipt_json(basis))
        installation = rtwin._FixedPublisherInstallation(bpin,qpin,pins,"a"*40,"b"*40)
        authority = rtwin._driver._DeploymentAuthority(None,None,None,self.resolved().resolved_server_profile_id,self.resolved().effective_config_sha256,self.snapshot.program_execution_snapshot_id,"c"*64,1,None,None)
        apath = self.root / "approval.sqlite3"
        astore = approval.SQLiteApprovalStore(apath); self.addCleanup(astore.close)
        scientific = approval.ScientificApproval.for_plan(self.store,self.store.load_calculation_plan(self.snapshot.calculation_plan_id),displayed_semantic_meaning={"intent":"inert"},reviewer_id="synthetic",reviewer_evidence={"fixture":"inert"})
        batch = approval.BatchSubmitApproval.for_existing_attempts(self.store,[(self.snapshot.attempt_id,scientific)],reviewer_id="synthetic",reviewer_evidence={"fixture":"inert"})
        attachment = {key: basis[key] for key in controller._PILOT_ATTACHMENT_KEYS if key != "deployment_readback_evidence_sha256"}
        attachment["deployment_readback_evidence_sha256"] = bpin.sha256
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(self.store,self.snapshot,confirmer_id="synthetic",confirmer_evidence={"publisher_pilot":attachment})
        astore.store_scientific_approval(scientific); astore.store_batch_submit_approval(batch); astore.store_operational_confirmation(confirmation)
        qscope = {key:basis[key] for key in ("qualification_payload_sha256","qualification_file_sha256")}
        live = {**qscope, **{key:basis[key] for key in ("resolved_server_profile_id","program_execution_snapshot_id","pilot_window")}, "attempt_id":self.snapshot.attempt_id}
        semantic = {"schema":"v31-publisher-reviewed-scope/1", "owner_exact_q":{"raw":digest(owner_raw),"scope":qscope}, "live_gate":{"raw":digest(live_raw),"scope":live}}
        spin = write("reviewed-scope.json",c._receipt_json(semantic))
        stores = []
        for role,store,path in (("core",self.store,self.database),("approval",astore,apath),("transport",self.program_transport_store,Path(self.program_transport_store._path))):
            pin = file_binding(path)
            stores.append(controller._PilotStoreBinding(role,store,pin.path,pin.parent_chain,pin.file_identity))
        modules = (c,w,p,runtime,rtwin,controller)
        if is_crest:
            from auto_g16.execution import _crest_loader, _crest_seed_handoff, _receipt_source, xtb_crest_handoff
            from auto_g16.conformer import service as conformer_service
            modules += (crest,_crest_loader,_crest_seed_handoff,_receipt_source,xtb_crest_handoff,conformer_service,transport)
        run = controller._FixedPilotRun(self.snapshot,self.current_profile,tuple(stores),scientific.scientific_approval_id,batch.batch_submit_approval_id,confirmation.operational_confirmation_id,{"intent":"inert"},lane.XYZ,self.scheduler_bytes["crest.pbs" if is_crest else "xtb.pbs"],spin,tuple(file_binding(Path(m.__file__).resolve()) for m in modules))
        return installation,authority,run,confirmation


class PublisherIdentityTests(_PilotFixture):
    def test_old_default_and_new_full_snapshot_receipt_roundtrip(self):
        old_material = c._prepare_completion_rendering_material(self.current_profile,self.resolved())
        self.assertEqual(old_material["schema"],c._MATERIAL_SCHEMA)
        before = self.make_snapshot(old_material)
        self.assertTrue(before.scheduler_artifacts[0]["content_utf8"].startswith("#!/bin/bash\n# auto-g16-v31-scheduler/2\n"))
        self.assertEqual(len(w._WRAPPER_SOURCE.encode()),14181)
        self.assertEqual(sha256(w._WRAPPER_SOURCE.encode()).hexdigest(),"58167de5436ec2d5ae9ef89dde458f386cdc2860f4f00a41c81c0a390f782333")
        self.snapshot.assert_identity_closed()
        self.assertEqual(p._validate_program_review_semantics(self.snapshot._approval_semantics()),self.snapshot._approval_semantics())
        # Core has no snapshot table: the existing Approval record persists the
        # complete expanded snapshot. Reopen both databases and rebuild from that
        # durable payload through the real validator, without mutable profile reads.
        review_path=self.root/"snapshot-review.sqlite3"
        review_store=approval.SQLiteApprovalStore(review_path)
        confirmation=approval.ExactOperationalConfirmation.for_snapshot(self.store,self.snapshot,confirmer_id="inert-reopen",confirmer_evidence={"fixture":"synthetic only"})
        review_store.store_operational_confirmation(confirmation)
        review_store.close();self.store.close()
        self.store=core.SQLiteRuntimeStore(self.database);self.addCleanup(self.store.close)
        review_store=approval.SQLiteApprovalStore(review_path);self.addCleanup(review_store.close)
        rebuilt=[];from_verified=p.ProgramExecutionSnapshot._from_verified
        def reconstruct(**kwargs):
            value=from_verified(**kwargs);rebuilt.append(value);return value
        with patch.object(p.ProgramExecutionSnapshot,"_from_verified",side_effect=reconstruct),patch.object(c,"resolve_server_profile",side_effect=AssertionError("no mutable profile during reopen")):
            loaded=review_store.load_operational_confirmation(confirmation.operational_confirmation_id)
        self.assertTrue(rebuilt)
        restored=rebuilt[-1]
        restored.assert_identity_closed();restored._assert_current_core(self.store)
        loaded.assert_current(self.store,restored)
        self.assertEqual(restored._approval_semantics(),self.snapshot._approval_semantics())
        self.assertEqual(restored.program_execution_snapshot_id,self.snapshot.program_execution_snapshot_id)
        self.snapshot=restored
        expected = c._receipt_binding(self.snapshot,"123.server","workspace-token-v31")
        self.assertEqual(expected["wrapper_source_sha256"],sha256(w._PUBLISHER_WRAPPER_SOURCE.encode()).hexdigest())
        self.assertNotEqual(expected["wrapper_source_sha256"],c._receipt_binding(before,"123.server","workspace-token-v31")["wrapper_source_sha256"])
        self.execute(); self.publish()
        assessment = self.collect()
        self.assertEqual(assessment.data["verdict"],"SUCCEEDED")
        self.assertIs(self.store.attempt_state("attempt-1"),core.AttemptState.SUCCEEDED)
        count = len(self.driver.calls)
        runtime._assert_program_receipt_success_authority(self.store,**self.kwargs())
        self.assertEqual(len(self.driver.calls),count)

    def test_profile_projection_preserves_all_non_q_input(self):
        resolved = self.resolved()
        expected = dict(resolved._identity_payload); expected.pop("effective_config_sha256")
        expected["runtime_identities"] = {k:v for k,v in expected["runtime_identities"].items() if k != c._Q_NAME}
        self.assertEqual(c._publisher_profile_basis(resolved),c.semantic_sha256(c.freeze_mapping(expected,"expected")))
        for profile in (replace(self.current_profile,profile_revision=2), replace(self.current_profile,config_files=[("ssh_config",b"Host changed.example\n")]), replace(self.current_profile,runtime_contents={**self.current_profile.runtime_contents,"extra":b"extra"})):
            with self.subTest(profile=profile.profile_revision):
                with self.assertRaises(execution.ExecutionValueError):
                    c._prepare_publisher_pilot_rendering_material(profile,execution.resolve_server_profile(profile))
        self.assertEqual(set(resolved._identity_payload),c._PROFILE_BASIS_FIELDS)
        self.assertIn(c._Q_NAME,resolved.runtime_identities)

    def test_q_closed_schema_nested_adversaries(self):
        mutations = [lambda q:q.update(extra=1), lambda q:q["scope"].update(adapter_contract_version=True), lambda q:q["hosts"][0]["namespaces"]["mount"].update(device=True), lambda q:q["hosts"][0]["locations"][0]["mount"].update(extra="x"), lambda q:q["hosts"].append(copy.deepcopy(q["hosts"][0])), lambda q:q["hosts"][0]["probes"].pop(), lambda q:q["controller_probe"].update(outcome="UNKNOWN"), lambda q:q["runtime"]["server_python"].update(path="/bad/../python"), lambda q:q["observation_window"].update(finished_at="1999-02-30T00:00:00.000000Z"), lambda q:q["hosts"][0].update(boot_id="NOT_ACQUIRED"), lambda q:q["implementation"]["wrapper_source"].update(sha256="0"*64), lambda q:q["hosts"][0]["locations"][0]["parent_chain"].pop()]
        for mutate in mutations:
            value=copy.deepcopy(self.q);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(execution.ExecutionValueError):c._decode_publisher_qualification(seal(value))
        raw=seal(self.q)
        for bad in (raw+b"\n", b"\xef\xbb\xbf"+raw, raw.replace(b'"payload":',b'"payload":{},"payload":',1), b" "* (c._Q_CAP+1)):
            with self.assertRaises(execution.ExecutionValueError):c._decode_publisher_qualification(bad)

    def test_mixed_tuple_and_cross_source_receipt_reject(self):
        artifact=dict(self.snapshot.scheduler_artifacts[0])
        artifact["content_utf8"]=artifact["content_utf8"].replace("# auto-g16-v31-scheduler/3","# auto-g16-v31-scheduler/2",1)
        with self.assertRaises(execution.ExecutionValueError):c._material_from_artifact((artifact,),self.resolved())
        for schema in ("v31-completion-rendering-material/9",c._MATERIAL_SCHEMA):
            with self.assertRaises(execution.ExecutionValueError):c._validate_material({**self.material,"schema":schema},self.resolved())
        receipt=self.publish(wrapper_source_sha256=sha256(w._WRAPPER_SOURCE.encode()).hexdigest(),wrapper_source_size_bytes=14181)
        with self.assertRaises(execution.ExecutionValueError):c._bound_receipt(c._receipt_json(receipt),self.snapshot,"123.server","workspace-token-v31")

    def test_script_config_uses_fixed_quoted_stdin_not_large_argv(self):
        script=self.snapshot.scheduler_artifacts[0]["content_utf8"]
        prefix, encoded, delimiter = script.rstrip("\n").rsplit("\n",2)
        self.assertEqual(delimiter,"AUTO_G16_PUBLISHER_CONFIG")
        self.assertNotIn(delimiter,encoded)
        self.assertTrue(prefix.endswith(" <<'AUTO_G16_PUBLISHER_CONFIG'"))
        self.assertEqual(c._canonical_json_object(base64.b64decode(encoded),8*1024*1024)["material"],c._plain(self.material))
        compile(w._PUBLISHER_WRAPPER_SOURCE,"publisher","exec")
        self.assertIn('stdin=subprocess.DEVNULL',w._PUBLISHER_WRAPPER_SOURCE)
        self.assertNotIn('closed(un64(sys.argv[1]))',w._PUBLISHER_WRAPPER_SOURCE)

    def test_missing_fixed_installation_and_old_production_are_rejected(self):
        with self.assertRaisesRegex(TransportBoundaryError,"NOT_ACQUIRED"):
            rtwin._read_fixed_publisher_deployment(None,self.snapshot)
        with self.assertRaisesRegex(TransportBoundaryError,"publisher-not-qualified|synthetic executables"):
            rtwin._RTWinProgramEffectDriver(snapshot=self.snapshot,current_profile=self.current_profile,program_transport_store=self.program_transport_store)
        with self.assertRaisesRegex(TransportBoundaryError,"NOT_ACQUIRED"):
            controller._run_first_publisher_pilot()


class PublisherInstallationTests(_PilotFixture):
    def test_fixed_read_pins_basis_q_and_all_originals(self):
        installation,authority,run,confirmation=self.install_fixture()
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation):
            read=rtwin._read_fixed_publisher_deployment(authority,self.snapshot)
            try:
                controller._validate_pilot_qualification_evidence(run,read,confirmation)
                path=Path(installation.qualification.path)
                path.rename(path.with_suffix(".retained"));path.write_bytes(self.current_profile.runtime_contents[c._Q_NAME])
                with self.assertRaisesRegex(TransportBoundaryError,"drift"):read.assert_current()
            finally:read.close()

    def test_symlink_missing_original_and_wrong_basis_reject(self):
        installation,authority,run,confirmation=self.install_fixture()
        cases=[replace(installation,evidence=installation.evidence[:-1]),replace(installation,source_commit="f"*40)]
        for value in cases:
            with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",value),self.assertRaisesRegex(TransportBoundaryError,"publisher-not-qualified"):
                rtwin._read_fixed_publisher_deployment(authority,self.snapshot)
        path=Path(installation.basis.path);saved=path.with_suffix(".retained");path.rename(saved);path.symlink_to(saved)
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation),self.assertRaises(TransportBoundaryError):rtwin._read_fixed_publisher_deployment(authority,self.snapshot)

    def test_self_signed_scope_or_attachment_does_not_match_installed_review(self):
        installation,authority,run,confirmation=self.install_fixture()
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation):
            read=rtwin._read_fixed_publisher_deployment(authority,self.snapshot)
            try:
                forged={**c._plain(confirmation.confirmer_evidence),"publisher_pilot":{**c._plain(confirmation.confirmer_evidence["publisher_pilot"]),"owner_q_acceptance_evidence_sha256":"f"*64}}
                bad=approval.ExactOperationalConfirmation.for_snapshot(self.store,self.snapshot,confirmer_id="synthetic",confirmer_evidence=forged)
                with self.assertRaises(TransportBoundaryError):controller._validate_pilot_qualification_evidence(run,read,bad)
                scope=Path(run.reviewed_semantics.path); raw=json.loads(scope.read_bytes());raw["owner_exact_q"]["scope"]["qualification_payload_sha256"]="f"*64
                # Even with independently pinned changed bytes, incompatible scope fails.
                alternate=scope.with_name("foreign-scope.json");alternate.write_bytes(c._receipt_json(raw))
                with self.assertRaises(TransportBoundaryError):controller._validate_pilot_qualification_evidence(replace(run,reviewed_semantics=file_binding(alternate)),read,confirmation)
            finally:read.close()

    def test_parent_replacement_during_pinned_read_is_detected(self):
        folder=self.root/"read-race";folder.mkdir();path=folder/"evidence.txt";path.write_bytes(b"retained evidence\n")
        pin=rtwin._PinnedPublisherFile(file_binding(path),65536)
        real_read=os.read;changed=[]
        def read(fd,size):
            raw=real_read(fd,size)
            if fd==pin.fds[-1] and raw and not changed:
                folder.rename(self.root/"retained-read-race");changed.append(True)
            return raw
        try:
            with patch.object(os,"read",side_effect=read),self.assertRaises((OSError,TransportBoundaryError)):
                pin._read_and_check()
        finally:pin.close()

    def test_constructor_failure_closes_retained_qualification_descriptors(self):
        closed=[]
        def reject(driver):
            driver._publisher=SimpleNamespace(close=lambda:closed.append(True))
            raise TransportBoundaryError("injected later constructor failure")
        with patch.object(rtwin._RTWinProgramEffectDriver,"_authority",reject),self.assertRaises(TransportBoundaryError):
            rtwin._RTWinProgramEffectDriver(snapshot=self.snapshot,current_profile=self.current_profile,program_transport_store=self.program_transport_store)
        self.assertEqual(closed,[True])

    def test_pinned_probe_index_rejects_float_equivalent_digest_size(self):
        # Create an internally bound installation whose canonical index uses a
        # float equal to the Q's integer; its real bytes/hashes all match pins.
        original=controller._probe_index
        def malformed(payload):
            index=copy.deepcopy(c._plain(original(payload)))
            index["entries"][0]["evidence"]["size_bytes"]=float(index["entries"][0]["evidence"]["size_bytes"])
            return index
        original_json=c._receipt_json
        def index_bytes(value):
            if isinstance(value,dict) and value.get("schema")=="v31-publisher-probe-evidence-index/1":
                return json.dumps(value,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()+b"\n"
            return original_json(value)
        fixture=_PilotFixture();self.addCleanup(fixture.doCleanups)
        with patch.object(controller,"_probe_index",side_effect=malformed),patch.object(c,"_receipt_json",side_effect=index_bytes):
            fixture.setUp()
            installation,authority,run,confirmation=fixture.install_fixture()
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation):
            read=rtwin._read_fixed_publisher_deployment(authority,fixture.snapshot)
            try:
                with self.assertRaisesRegex(TransportBoundaryError,"probe index"):
                    controller._validate_pilot_qualification_evidence(run,read,confirmation)
            finally:read.close()


class PublisherControllerTests(_PilotFixture):
    def invoke(self,installation,authority,run):
        port=runtime._ProgramExecutionPort(snapshot=self.snapshot,program_transport_store=self.program_transport_store,driver=self.driver)
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation),patch.object(controller,"_FIXED_PILOT_RUN",run),patch.object(rtwin._driver,"_resolve_closed_profile_authority",return_value=authority),patch.object(controller,"_prepare_first_publisher_pilot_port",return_value=port):
            return controller._run_first_publisher_pilot()

    def test_real_validator_twice_then_unique_execute_and_restart_reject(self):
        installation,authority,run,confirmation=self.install_fixture()
        calls=[]
        validate=approval.validate_effect_authority
        execute=execution.execute_once
        def wrapped_validate(**kw):
            calls.append("validate");return validate(**kw)
        def wrapped_execute(*args,**kw):
            calls.append("execute");self.assertEqual(kw["confirmed_execution_snapshot_id"],confirmation.execution_snapshot_id);return execute(*args,**kw)
        with patch.object(approval,"validate_effect_authority",side_effect=wrapped_validate),patch.object(execution,"execute_once",side_effect=wrapped_execute):
            result=self.invoke(installation,authority,run)
        self.assertEqual(calls,["validate","validate","execute"])
        self.assertIs(result.claim,core.SubmissionIntentClaim.WINNER)
        self.assertEqual(sum(x[0]=="SUBMIT_QSUB_ONCE" for x in self.driver.calls),1)
        with patch.object(execution,"execute_once",wraps=execute) as spy,self.assertRaises(approval.ApprovalScopeError):
            self.invoke(installation,authority,run)
        spy.assert_not_called()

    def test_wrong_scientific_meaning_and_unknown_approval_zero_claim(self):
        installation,authority,run,confirmation=self.install_fixture()
        for bad in (replace(run,displayed_semantic_meaning={"intent":"changed"}),replace(run,scientific_approval_id="missing"),replace(run,batch_submit_approval_id="missing"),replace(run,operational_confirmation_id="missing")):
            with patch.object(execution,"execute_once",wraps=execution.execute_once) as spy,self.assertRaises(Exception):self.invoke(installation,authority,bad)
            spy.assert_not_called()
            self.assertIs(self.store.attempt_state("attempt-1"),core.AttemptState.PLANNED)
            self.assertEqual(self.driver.calls,[])

    def test_final_preclaim_drift_zero_execute_and_preserves_evidence(self):
        installation,authority,run,confirmation=self.install_fixture()
        validate=approval.validate_effect_authority;count=0
        def drift(**kwargs):
            nonlocal count
            validate(**kwargs);count+=1
            if count==1:
                path=Path(installation.qualification.path);path.rename(path.with_suffix(".retained"));path.write_bytes(self.current_profile.runtime_contents[c._Q_NAME])
        with patch.object(approval,"validate_effect_authority",side_effect=drift),patch.object(execution,"execute_once",wraps=execution.execute_once) as spy,self.assertRaises(TransportBoundaryError):self.invoke(installation,authority,run)
        spy.assert_not_called();self.assertEqual(self.driver.calls,[])
        self.assertIs(self.store.attempt_state("attempt-1"),core.AttemptState.PLANNED)


class PublisherWrapperTests(_PilotFixture):
    def namespace(self):
        namespace = {"__name__": "inert_r4_fixture"}
        exec(compile(w._PUBLISHER_WRAPPER_SOURCE,"r4-source","exec"),namespace)
        return namespace

    def test_host_guard_match_and_each_identity_mismatch(self):
        ns=self.namespace()
        script=self.snapshot.scheduler_artifacts[0]["content_utf8"]
        config=json.loads(base64.b64decode(script.rstrip("\n").rsplit("\n",2)[1]))
        host=self.q["hosts"][0]
        actual={k:copy.deepcopy(host[k]) for k in ("host_key","machine_id_sha256","boot_id","kernel_release","architecture","namespaces","locations")}
        actual["locations"]=[{k:v for k,v in loc.items() if k!="evidence"} for loc in actual["locations"]]
        ns["observe_publisher_host"]=lambda *args:actual
        ns["file_identity"]=lambda path,size,digest:(path,size,digest)
        self.assertEqual(ns["publisher_host_guard"](config),actual)
        for key in ("host_key","machine_id_sha256","boot_id","kernel_release","architecture","namespaces","locations"):
            changed=copy.deepcopy(actual);changed[key]="mismatch"
            ns["observe_publisher_host"]=lambda *args:changed
            with self.subTest(field=key),self.assertRaises(ValueError):ns["publisher_host_guard"](config)

    def test_full_new_source_zero_child_and_prelink_drift_leave_no_receipt(self):
        # Fault-injected control-flow evidence only, NOT actual Linux qualification.
        for phase in ("initial","before-child","before-link","success"):
            with self.subTest(phase=phase):
                workspace=self.root/("host-"+phase);workspace.mkdir()
                config=json.loads(c._receipt_json(old._supplement_wrapper_config(self,workspace)))
                ns=self.namespace();calls=[];launches=[]
                def guard(config):
                    calls.append("guard")
                    target={"initial":1,"before-child":2,"before-link":3}.get(phase)
                    if len(calls)==target:raise ValueError("injected actual-host mismatch")
                    return {"host":"inert"}
                def launch(*args,**kwargs):
                    launches.append(True)
                    self.assertIs(kwargs["shell"],False)
                    self.assertEqual(kwargs["stdin"],-3)
                    os.write(kwargs["stdout"],b"inert log\n")
                    return SimpleNamespace(pid=123,returncode=None)
                ns.update(publisher_host_guard=guard,subreaper=lambda:None,wait_all=lambda *args:0,subprocess=SimpleNamespace(Popen=launch,DEVNULL=-3))
                cwd=Path.cwd()
                try:
                    with patch.object(sys,"executable",str(Path(sys.executable).resolve())),patch.dict(os.environ,{"PBS_JOBID":"123.server"}):
                        if phase=="success":self.assertEqual(ns["run"](config),0)
                        else:
                            with self.assertRaises(ValueError):ns["run"](config)
                finally:os.chdir(cwd)
                self.assertEqual(len(launches),int(phase in {"before-link","success"}))
                self.assertEqual((workspace/"v31-completion.json").exists(),phase=="success")
                self.assertEqual((workspace/"v31-completion.pending").exists(),phase in {"before-link","success"})
                if phase=="success":self.assertEqual(len(calls),3)

    def test_new_stdin_rejects_trailing_duplicate_oversize_and_extra_argv(self):
        import io
        # Evaluate just the exact source main block against a recording run seam.
        block=w._PUBLISHER_WRAPPER_SOURCE[w._PUBLISHER_WRAPPER_SOURCE.rindex('if __name__=="__main__":'):]
        for raw,args in ((b"e30=\n\n",["-c"]),(b"e30=e30=\n",["-c"]),(b"A"*(8*1024*1024+1)+b"\n",["-c"]),(b"e30=\n",["-c","extra"])):
            ns=self.namespace();called=[];ns["__name__"]="__main__";ns["run"]=lambda v:called.append(v) or 0
            def leave(code):raise SystemExit(code)
            ns["sys"]=SimpleNamespace(argv=args,stdin=SimpleNamespace(buffer=io.BytesIO(raw)),exit=leave)
            with self.assertRaises(SystemExit) as result:exec(block,ns)
            self.assertEqual(result.exception.code,125);self.assertEqual(called,[])

    def test_large_qualified_set_keeps_config_out_of_argv(self):
        value=copy.deepcopy(self.q)
        value["hosts"]=[]
        for i in range(32):
            host=copy.deepcopy(self.q["hosts"][0]);host["machine_id_sha256"]=sha256(str(i).encode()).hexdigest()
            host["host_key"]=c.semantic_sha256(c.freeze_mapping({"machine_id_sha256":host["machine_id_sha256"]},"host"));value["hosts"].append(host)
        value["hosts"].sort(key=lambda h:h["host_key"])
        value["execution_domain"]["eligible_host_keys"]=[h["host_key"] for h in value["hosts"]]
        raw=seal(value)
        self.assertGreater(len(raw),128*1024)
        self.assertLess(len(raw),1024*1024)
        profile=replace(self.current_profile,runtime_contents={**self.current_profile.runtime_contents,c._Q_NAME:raw})
        resolved=execution.resolve_server_profile(profile)
        material=c._prepare_publisher_pilot_rendering_material(profile,resolved)
        fields={k:v for k,v in self.snapshot._identity_payload.items() if k!="scheduler_artifacts"}
        fields["resolved_server_profile_id"]=resolved.resolved_server_profile_id
        artifact=c._render_completion_scheduler(self.spec,self.resources(),resolved,fields,material)[0]
        script=artifact["content_utf8"]
        command, encoded, delimiter=script.rstrip("\n").rsplit("\n",2)
        # No config data appears in exec argv; all quoted source tokens stay bounded.
        argv=shlex.split(command[command.index("exec ")+5:])
        self.assertLess(max(len(x.encode()) for x in argv),65536)
        self.assertGreater(len(encoded),128*1024)
        self.assertNotIn(delimiter,encoded)

    def test_new_source_rechecks_data_file_content_and_inode_before_child_and_link(self):
        # Real descriptor/file operations with inert child and model host identity.
        # Linux namespace/subreaper behavior remains the separate Linux evidence gap.
        for phase in ("before-child","before-link"):
            for change in ("content","same-bytes-inode"):
                with self.subTest(phase=phase,change=change):
                    workspace=self.root/(phase+"-"+change);workspace.mkdir()
                    config=json.loads(c._receipt_json(old._supplement_wrapper_config(self,workspace)))
                    ns=self.namespace();launches=[]
                    expected=self.q["hosts"][0]
                    observed={k:copy.deepcopy(expected[k]) for k in ("host_key","machine_id_sha256","boot_id","kernel_release","architecture","namespaces","locations")}
                    observed["locations"]=[{k:v for k,v in loc.items() if k!="evidence"} for loc in observed["locations"]]
                    ns["observe_publisher_host"]=lambda *args:copy.deepcopy(observed)
                    target=Path(config["xtb_data_path"])/lane.XTB_RUNTIME_DATA_FILES[0]
                    def drift():
                        raw=target.read_bytes();target.rename(target.with_name("retained-data"))
                        target.write_bytes(raw if change=="same-bytes-inode" else b"changed data bytes\n")
                    exclusive=ns["exclusive"]
                    def create(parent,name,raw):
                        exclusive(parent,name,raw)
                        if name=="v31-completion.pending" and phase=="before-link":drift()
                    def launch(*args,**kwargs):
                        launches.append(True);os.write(kwargs["stdout"],b"inert log\n")
                        return SimpleNamespace(pid=123,returncode=None)
                    ns.update(exclusive=create,subreaper=drift if phase=="before-child" else lambda:None,wait_all=lambda *args:0,subprocess=SimpleNamespace(Popen=launch,DEVNULL=-3))
                    cwd=Path.cwd()
                    try:
                        with patch.object(sys,"executable",str(Path(sys.executable).resolve())),patch.dict(os.environ,{"PBS_JOBID":"123.server"}),self.assertRaises(ValueError):
                            ns["run"](config)
                    finally:os.chdir(cwd)
                    self.assertEqual(len(launches),int(phase=="before-link"))
                    self.assertFalse((workspace/"v31-completion.json").exists())
                    self.assertEqual((workspace/"v31-completion.pending").exists(),phase=="before-link")
                    self.assertTrue(target.with_name("retained-data").exists())


class PublisherProductionBridgeTests(lane.LaneAFixture):
    """Real product factory/driver/wire preparation; process seam is inert."""
    install_fixture = _PilotFixture.install_fixture

    def resolved(self, **kwargs):
        return self.target if hasattr(self,"target") else lane.LaneAFixture.resolved(self,**kwargs)

    def setUp(self):
        super().setUp()
        from tests.v3.transport import _fixtures as v30
        from tests.v31.transport import test_rtwin_successor_bridge as bridge_tests
        from auto_g16.transport import _bridge
        from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal, _ProjectProvisioningService
        fixture=v30.TransportFixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        raw=fixture.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        manifest=json.loads(raw.runtime_contents["transport-deployment-manifest-v2.json"])
        manifest.update(schema="auto-g16-v3-transport-deployment-manifest/3",bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
        manifest["trust_roots"]={k:v for k,v in manifest["trust_roots"].items() if k in c._ROOT_RULES}
        driver=rtwin._driver
        profile=replace(raw,platform_paths={**raw.platform_paths,"xtb_executable_path":"/opt/xtb/6.7.1/bin/xtb","xtb_data_path":"/opt/xtb/6.7.1/share/xtb"},runtime_contents={driver._TABLE_NAME:driver._OPERATION_TABLE_BYTES,driver._RESOURCE_DESCRIPTOR_NAME:v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES,c._DEPLOYMENT_NAME:c._receipt_json(manifest),_bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME:_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES,"xtb":b"offline exact image",c._DATA_NAME:lane.xtb_runtime_data_manifest_bytes()})
        self.q,_=qualification_fixture(profile,queue="batch")
        self.current_profile=replace(profile,runtime_contents={**profile.runtime_contents,c._Q_NAME:seal(self.q)})
        self.target=execution.resolve_server_profile(self.current_profile)
        root=self.root/"production-fixture";root.mkdir()
        journal=_ProductionProvisioningJournal.create_new(root/"journal.sqlite3",approved_root=root);self.addCleanup(journal.close)
        self.program_transport_store=transport._ProgramTransportStore._create_completion_store(root/"transport.sqlite3",approved_root=root);self.addCleanup(self.program_transport_store.close)
        self.wire=bridge_tests._Wire()
        process=patch.object(driver.subprocess,"Popen",side_effect=AssertionError("no processes in bridge test"));self.process_spy=process.start();self.addCleanup(process.stop)
        wire=patch.object(driver._SubprocessRTWinDriver,"_run",side_effect=self.wire.run);wire.start();self.addCleanup(wire.stop)
        service=_ProjectProvisioningService._from_project_attestor(attestor=rtwin._RTWinProjectAttestor(current_profile=self.current_profile,target=self.target),target=self.target,journal=journal)
        binding=service.provision_remote_project(project=self.store.load_project("project-1"),target=self.target,remote_project_dir=self.remote_project_dir)
        spec=p._prepare_program_execution_spec(program_kind="xtb",executable_path=profile.platform_paths["xtb_executable_path"],executable_size_bytes=len(profile.runtime_contents["xtb"]),executable_sha256=sha256(profile.runtime_contents["xtb"]).hexdigest(),input_name="input.xyz",input_bytes=lane.XYZ,program_data=self.xtb_data(),resolved_profile=self.target,completion_mode=c._MODE)
        resources=execution.ResolvedResourceRequest(resource_spec=self.store.load_resource_spec("resource-1"),cores=8,memory_mb=12288,walltime_seconds=3600,queue="batch")
        self.snapshot=p._ProgramExecutionSnapshotService._for_production(project_provisioning=service,target=self.target).prepare(self.store,attempt_id="attempt-1",calculation_plan_id="plan-1",resource_spec_id="resource-1",program_execution_spec=spec,project_physical_binding=binding,resolved_resource_request=resources,resolved_server_profile=self.target,workspace_binding=self.workspace(),completion_rendering_material=c._prepare_publisher_pilot_rendering_material(self.current_profile,self.target))
        self.scheduler_bytes={"xtb.pbs":self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}
        self.wire.calls.clear()

    def test_real_controller_driver_submission_receipt_collection_and_guard(self):
        from tests.v31.transport import test_rtwin_successor_bridge as bridge_tests
        installation,_,run,confirmation=self.install_fixture()
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation),patch.object(controller,"_FIXED_PILOT_RUN",run):
            result=controller._run_first_publisher_pilot()
            self.assertIs(result.claim,core.SubmissionIntentClaim.WINNER)
            self.assertIs(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
            self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.wire.calls),1)
            receipt=dict(c._receipt_binding(self.snapshot,"123.server",bridge_tests.directory_token(self.snapshot.workspace_binding.remote_attempt_dir)))
            receipt.update(termination={"kind":"exited","returncode":0,"signal":None},finished_at="2026-09-15T00:00:00.000000Z",outputs=[])
            for declaration in (*self.snapshot.program_execution_spec.required_outputs,*self.snapshot.program_execution_spec.optional_outputs):
                raw=self.wire.outputs[declaration["portable_name"]]
                receipt["outputs"].append({**{k:declaration[k] for k in ("logical_role","portable_name","format")},"presence":"present",**digest(raw)})
            self.wire.outputs["v31-completion.json"]=c._receipt_json(receipt)
            self.wire.scheduler=(153,b"",b"qstat: Unknown Job Id 123.server\n")
            # Submitted collection cannot call the PLANNED-only validator.
            with patch.object(approval,"validate_effect_authority",side_effect=AssertionError("PLANNED validator after submission")):
                assessment=controller._collect_first_publisher_pilot()
            self.assertEqual(assessment.data["verdict"],"SUCCEEDED")
            before=len(self.wire.calls)
            assessment=controller._collect_first_publisher_pilot()
            self.assertEqual(assessment.data["verdict"],"SUCCEEDED");self.assertEqual(len(self.wire.calls),before)
            qpath=Path(installation.qualification.path);qpath.rename(qpath.with_suffix(".retained"));qpath.write_bytes(self.current_profile.runtime_contents[c._Q_NAME])
            with self.assertRaises(TransportBoundaryError):controller._collect_first_publisher_pilot()
            self.assertEqual(len(self.wire.calls),before)
            self.assertIs(self.store.attempt_state("attempt-1"),core.AttemptState.SUCCEEDED)
        self.process_spy.assert_not_called()

    def test_production_fixed_locator_missing_zero_claim_or_wire_effect(self):
        with patch.object(self.store,"record_submission_intent",wraps=self.store.record_submission_intent) as claim:
            with self.assertRaisesRegex(TransportBoundaryError,"NOT_ACQUIRED"):
                rtwin._RTWinProgramEffectDriver(snapshot=self.snapshot,current_profile=self.current_profile,program_transport_store=self.program_transport_store)
            claim.assert_not_called()
        self.assertEqual(self.wire.calls,[])


    def test_postclaim_q_drift_stops_following_effect_keeps_consumed_attempt(self):
        installation,_,run,confirmation=self.install_fixture()
        original=self.wire.run
        def drift(scope,invocation):
            result=original(scope,invocation)
            if invocation.operation.name=="ALLOCATE_WORKSPACE":
                path=Path(installation.qualification.path);path.rename(path.with_suffix(".retained"));path.write_bytes(self.current_profile.runtime_contents[c._Q_NAME])
            return result
        claims=[]
        original_claim=self.store.record_submission_intent
        def claim_once(*args,**kwargs):
            result=original_claim(*args,**kwargs);claims.append(result);return result
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation),patch.object(controller,"_FIXED_PILOT_RUN",run),patch.object(rtwin._driver._SubprocessRTWinDriver,"_run",side_effect=drift),patch.object(self.store,"record_submission_intent",side_effect=claim_once):
            try:controller._run_first_publisher_pilot()
            except TransportBoundaryError:pass
            self.assertEqual(claims.count(core.SubmissionIntentClaim.WINNER),1)
        self.assertIsNot(self.store.attempt_state("attempt-1"),core.AttemptState.PLANNED)
        self.assertEqual([op for op,_ in self.wire.calls],["ALLOCATE_WORKSPACE"])
        self.assertTrue(Path(installation.qualification.path).with_suffix(".retained").exists())
        self.process_spy.assert_not_called()


if __name__=="__main__":unittest.main()
