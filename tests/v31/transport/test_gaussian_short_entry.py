"""Gaussian short-entry deltas. All effects use local fixtures or inert stubs."""
import base64
import builtins
import copy
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core, execution
from auto_g16.execution import _gaussian_file_carrier as startup
from auto_g16.execution import _program_completion as completion
from auto_g16.execution import program, program_runtime as runtime
from auto_g16.transport import _driver, _gaussian_file_submit as submit, _program_rtwin as rtwin
from auto_g16.transport import program as transport
from tests.v3.execution.test_v31_lane_a import LaneAFixture
from tests.v31.transport import test_gaussian_successor as previous
from tests.v31.transport import test_program_composition as composition
from tests.v31.transport import test_program_completion as old
from tests.v31.transport import test_publisher_pilot_orchestration as pilot


class ShortEntryCompositionTests(LaneAFixture):
    gaussian_profile = previous.GaussianSuccessorTests.gaussian_profile
    qualified_case = previous.GaussianSuccessorTests.qualified_case
    kwargs = old.CompletionTests.kwargs
    installed_case = previous.GaussianSuccessorTests.installed_case

    def setUp(self):
        super().setUp()
        self.profile_current, self.target, self.q, _, self.spec, self.service, _, self.material, self.snapshot = self.qualified_case(startup="file")
        root = self.root / "short-effects"
        root.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(root / "transport.sqlite3", approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.driver = composition._Driver({"gaussian.log": b"Normal termination of Gaussian 16\n"})
        self.input_bytes = {"flow.gjf": previous.OPT}
        self.scheduler_bytes = {a["portable_name"]: a["content_utf8"].encode() for a in self.snapshot.scheduler_artifacts}

    def execute(self):
        entry_name = self.snapshot.scheduler_artifacts[0]["portable_name"]
        runtime._prepare_program_execution(self.store, **self.kwargs(), input_bytes=self.input_bytes, scheduler_artifact_bytes=self.scheduler_bytes)
        result = execution.execute_once(self.store, snapshot=self.snapshot, current_profile=self.profile_current,
            confirmed_execution_snapshot_id=self.snapshot.program_execution_snapshot_id,
            prepared_input_bytes=previous.OPT, pbs_template_bytes=self.scheduler_bytes[entry_name],
            port=runtime._ProgramExecutionPort(**self.kwargs()))
        return runtime._read_program_execution_result(self.store, **self.kwargs(), claim=result.claim)

    def test_two_artifacts_four_control_stages_one_submit_and_receipt3(self):
        self.snapshot.assert_identity_closed()
        self.assertEqual(program._decode_program_review_semantics(self.snapshot._approval_semantics()), self.snapshot)
        self.assertEqual(self.snapshot.scheduler_artifacts[0]["portable_name"],"gaussian-entry-template.pbs")
        self.assertLessEqual(len(self.scheduler_bytes["gaussian-entry-template.pbs"]), 16384)
        self.assertNotIn(startup._wrapper_sources()[0], self.scheduler_bytes["gaussian-entry-template.pbs"].decode())
        self.assertEqual(self.spec.adapter_contract_version, 5)
        self.execute()
        stages = [r["payload"] for op, r in self.driver.calls if op == "STAGE_EXACT_FILE"]
        self.assertEqual([s["artifact_kind"] for s in stages], ["program-input", "scheduler-script", "startup-payload", "derived-config", "submit-intent-marker"])
        derived = startup._derived_artifacts(self.snapshot)
        self.assertEqual([d for d, _ in derived], rtwin._gaussian_derived_stages(self.snapshot))
        for row, (_, raw) in zip(stages[-2:], derived):
            self.assertEqual(row["sha256"], sha256(raw).hexdigest())
            self.assertEqual(row["size_bytes"], len(raw))
        requests = [r for op, r in self.driver.calls if op == "SUBMIT_QSUB_ONCE"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(requests[0]["payload"]["handoff_artifact_authority_ids"]), 2)
        old.CompletionTests.publish(self)
        assessment = old.CompletionTests.collect(self)
        self.assertEqual(assessment.data["verdict"], "SUCCEEDED")
        count = len(self.driver.calls)
        runtime._replay_program_completion(self.store, **self.kwargs())
        self.assertEqual(len(self.driver.calls), count)

    def test_extracted_helper_closes_both_gaussian_derived_artifact_tuples(self):
        from auto_g16.execution import _program_artifacts as artifacts
        from auto_g16.execution import _gaussian_startup as historical
        self.assertIs(runtime._stage_material, artifacts._stage_material)
        self.assertIs(runtime._declared_stage_payload, artifacts._declared_stage_payload)
        for variant, owner in ((True, historical), ("file", startup)):
            with self.subTest(variant=variant):
                snapshot = self.qualified_case(startup=variant)[-1]
                scheduler_bytes = {a["portable_name"]: a["content_utf8"].encode()
                                   for a in snapshot.scheduler_artifacts}
                staged = artifacts._stage_material(snapshot, input_bytes=self.input_bytes,
                                                   scheduler_artifact_bytes=scheduler_bytes)
                derived = owner._derived_artifacts(snapshot)
                self.assertEqual(len(derived), 2)
                self.assertEqual(staged[-2:], derived)
                for declaration, content in staged:
                    self.assertEqual(artifacts._declared_stage_payload(snapshot, declaration), declaration)
                    self.assertEqual(sha256(content).hexdigest(), declaration["sha256"])
                for declaration, _ in derived:
                    with self.assertRaises(transport.TransportBoundaryError):
                        artifacts._declared_stage_payload(snapshot, {**declaration, "sha256": "0" * 64})

    def test_unknown_is_no_retry_and_no_completion(self):
        composition.ProgramCompositionTests.test_17_ambiguous_qsub_sets_unknown_and_never_retries(self)

    def test_gaussian_submit_has_distinct_receipt_persistence_budget(self):
        generic = _driver._operation("SUBMIT_QSUB_ONCE")
        gaussian = rtwin._gaussian_submit_operation(file_carrier=True)
        self.assertEqual(submit.QSUB_CHILD_TIMEOUT_SECONDS, 30)
        self.assertEqual(submit.RECEIPT_PERSISTENCE_BUDGET_SECONDS, 90)
        self.assertEqual(submit.SUBMIT_EFFECT_TIMEOUT_SECONDS, 120)
        self.assertEqual(generic.timeout_seconds, 30)
        self.assertEqual(gaussian.timeout_seconds, 120)
        self.assertEqual(
            (gaussian.name, gaussian.token, gaussian.stdin_cap, gaussian.stdout_cap, gaussian.stderr_cap),
            (generic.name, generic.token, generic.stdin_cap, generic.stdout_cap, generic.stderr_cap),
        )
        source = submit.source_bytes()
        self.assertEqual(source.count(b"deadline=time.monotonic()+30"), 1)
        self.assertEqual((len(source), sha256(source).hexdigest()), (47590, "42bc47b466c4a7147de03f13b08c0e78ea0808743d54644fd04fa1c50e7be3d3"))

    def test_submit_timeout_contract_fails_closed_on_source_or_table_drift(self):
        with patch.object(submit, "source_bytes", return_value=b"no qualified child deadline"):
            with self.assertRaisesRegex(ValueError, "child deadline source drift"):
                rtwin._gaussian_submit_operation(file_carrier=True)
        with patch.object(submit, "RECEIPT_PERSISTENCE_BUDGET_SECONDS", 60), patch.object(submit, "SUBMIT_EFFECT_TIMEOUT_SECONDS", 90):
            with self.assertRaisesRegex(ValueError, "receipt persistence budget drift"):
                rtwin._gaussian_submit_operation(file_carrier=True)
        with patch.object(submit, "SUBMIT_EFFECT_TIMEOUT_SECONDS", 121):
            with self.assertRaisesRegex(ValueError, "submit timeout budget drift"):
                rtwin._gaussian_submit_operation(file_carrier=True)
        reference = _driver._operation("SUBMIT_QSUB_ONCE")
        drifted = _driver._Operation(reference.name, reference.token, 31, reference.stdin_cap, reference.stdout_cap, reference.stderr_cap)
        with patch.object(_driver, "_operation", return_value=drifted):
            with self.assertRaisesRegex(transport.TransportBoundaryError, "child timeout differs"):
                rtwin._gaussian_submit_operation(file_carrier=True)

    def test_closed_tuple_qualification_and_stage_derivation(self):
        from scripts import run_v31_publisher_pilot as controller
        contract=(Path(startup.__file__).resolve().parents[2]/"docs/v3/gaussian-qsub-file-carrier-contract.md").read_bytes()
        self.assertEqual(sha256(contract).hexdigest(),startup._CONTRACT_SHA256)
        index=controller._probe_index(self.q)
        self.assertEqual([x for x in index["entries"] if x["role"]=="delivery-probe"], [{"role":"delivery-probe","case_id":"P09","evidence":self.q["delivery_probe"]["evidence"]}])
        reviewed=json.loads(completion._receipt_json(self.snapshot._approval_semantics()))
        self.assertFalse(reviewed["gaussian_startup_review"]["stage_protocol"]["completion_authority"])
        for change in (lambda r:r.pop("gaussian_startup_review"),lambda r:r["gaussian_startup_review"]["stage_protocol"].update(completion_authority=True),lambda r:r["gaussian_startup_review"]["derived_stages"][0].update(sha256="0"*64)):
            altered=copy.deepcopy(reviewed);change(altered)
            with self.assertRaises(ValueError):program._decode_program_review_semantics(altered)
        from auto_g16.approval.store import _validate_snapshot_semantics
        self.assertEqual(_validate_snapshot_semantics(reviewed,execution_snapshot_id=self.snapshot.program_execution_snapshot_id,attempt_id=self.snapshot.attempt_id,calculation_plan_id=self.snapshot.calculation_plan_id,calculation_plan_revision=self.snapshot.calculation_plan_revision),self.snapshot._approval_semantics())
        for key in ("loader_source", "delivery_probe"):
            q = copy.deepcopy(self.q)
            (q if key == "delivery_probe" else q["implementation"]).pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                completion._decode_publisher_qualification(pilot.seal(q))
        for artifacts in (self.snapshot.scheduler_artifacts[:1], self.snapshot.scheduler_artifacts[::-1]):
            with self.assertRaises(ValueError): startup._payload(artifacts)
        with self.assertRaises(ValueError):
            runtime._stage_material(self.snapshot, input_bytes=self.input_bytes,
                scheduler_artifact_bytes={**self.scheduler_bytes, "gaussian-config.json": b"caller"})
        self.execute()
        authorities = []
        for op, r in self.driver.calls:
            if op == "STAGE_EXACT_FILE":
                authorities.append({k:v for k,v in r["payload"].items() if k != "content_base64"} | {"artifact_authority_id": str(len(authorities))})
        self.assertEqual(len(runtime._handoff_stage_ids(self.snapshot, authorities)), 2)
        for bad in (authorities[:-1], authorities[::-1], authorities + [authorities[-1]]):
            with self.assertRaises(ValueError): runtime._handoff_stage_ids(self.snapshot, bad)

    def test_native_q6_durable_authorities_context_and_wire(self):
        from auto_g16.transport import _bridge, _driver
        from tests.v3.transport import _fixtures as v30
        from tests.v31.transport import test_rtwin_successor_bridge as bridge_test
        fixture=v30.TransportFixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        raw=fixture.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        manifest=json.loads(raw.runtime_contents["transport-deployment-manifest-v2.json"])
        manifest.update(schema="auto-g16-v3-transport-deployment-manifest/3",bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
        manifest["trust_roots"]={k:v for k,v in manifest["trust_roots"].items() if k in completion._ROOT_RULES}
        from tests.v3.execution import test_v31_lane_a as lane
        profile=replace(raw,platform_paths={**raw.platform_paths,"xtb_executable_path":lane.XTB_EXECUTABLE_PATH,"xtb_data_path":lane.XTB_DATA_PATH},runtime_contents={"xtb":lane.XTB_EXECUTABLE_BYTES,completion._DATA_NAME:lane.xtb_runtime_data_manifest_bytes(),_driver._TABLE_NAME:_driver._OPERATION_TABLE_BYTES,_driver._RESOURCE_DESCRIPTOR_NAME:v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES,completion._DEPLOYMENT_NAME:completion._receipt_json(manifest)})
        current,target,q,evidence,_,_,_,_,snapshot=self.qualified_case(startup="file",production_generation=True,base_profile_override=profile,g16_path=previous.TARGET_G16_PATH,g16_size=previous.TARGET_G16_SIZE,g16_sha256=previous.TARGET_G16_SHA256)
        installation,authority=self.installed_case(current,target,q,evidence,snapshot)
        calls=[]
        def peer(scope,invocation):
            command,frame=rtwin._prepare_program_invocation(scope,invocation)
            request=_bridge._decode_frame(frame,cap=invocation.operation.stdin_cap,field="inert Q6 request")
            self.assertIn(submit.source_bytes().decode().splitlines()[0],command[-1])
            op=request["operation"];payload=request["payload"]["request_payload"];calls.append(request)
            self.assertEqual(invocation.operation.timeout_seconds, 120 if op=="SUBMIT_QSUB_ONCE" else _driver._operation(op).timeout_seconds)
            if op=="ALLOCATE_WORKSPACE":
                response={"remote_workspace":scope.workspace_binding.remote_attempt_dir,"workspace_physical_token":bridge_test.directory_token(scope.workspace_binding.remote_attempt_dir)}
            elif op=="STAGE_EXACT_FILE":
                response={k:v for k,v in payload.items() if k!="content_base64"};response["artifact_physical_token"]="inert-"+payload["portable_name"]
            elif op=="SUBMIT_QSUB_ONCE":
                self.assertEqual(len(request["payload"]["staged"]),5)
                context=request["payload"]["launch_context"]
                self.assertEqual([r["role"] for r in context["stages"]],["entry","payload","config","submit_marker"])
                self.assertEqual(payload["handoff_artifact_authority_ids"],[r["artifact_authority_id"] for r in context["stages"][2:]])
                bad=copy.deepcopy(request);bad["payload"]["launch_context"]["approvals"]["scientific"]["payload_sha256"]="0"*64
                with self.assertRaises(ValueError):rtwin._assert_wire_scope(scope,scope.program_execution_snapshot_id,bad)
                response={"job_id":"123.server"}
            else:raise AssertionError(op)
            return _bridge._encode_frame({"protocol":_bridge._PROGRAM_BOOTSTRAP_PROTOCOL,"operation":op,"status":"ok","result":response}),b"",0,"completed",True,True
        from auto_g16 import approval
        from scripts import run_v31_publisher_pilot as controller
        meaning={"fixture":"inert Q6 only"}
        scientific=approval.ScientificApproval.for_plan(self.store,self.store.load_calculation_plan(snapshot.calculation_plan_id),displayed_semantic_meaning=meaning,reviewer_id="fixture",reviewer_evidence={})
        batch=approval.BatchSubmitApproval.for_existing_attempts(self.store,[(snapshot.attempt_id,scientific)],reviewer_id="fixture",reviewer_evidence={})
        confirmation=approval.ExactOperationalConfirmation.for_snapshot(self.store,snapshot,confirmer_id="fixture",confirmer_evidence={})
        run=SimpleNamespace(snapshot=snapshot,displayed_semantic_meaning=meaning,scientific_approval_id=scientific.scientific_approval_id,batch_submit_approval_id=batch.batch_submit_approval_id,operational_confirmation_id=confirmation.operational_confirmation_id)
        deployment=SimpleNamespace(basis={"pilot_live_gate_evidence_sha256":"2"*64})
        def current_approvals():
            with patch.object(controller,"_load_current_authorities",return_value=({"core":self.store},scientific,batch,confirmation)):
                return controller._current_gaussian_handoff_approvals(run,deployment)
        with self.assertRaises(ValueError):current_approvals()
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",installation),patch.object(rtwin,"_publisher_window",return_value=None),patch.object(_driver._SubprocessRTWinDriver,"_run",side_effect=peer),patch.object(_driver.subprocess,"Popen",side_effect=AssertionError("live forbidden")):
            driver=rtwin._RTWinProgramEffectDriver(snapshot=snapshot,current_profile=current,program_transport_store=self.program_transport_store)
            self.addCleanup(driver.close)
            self.snapshot=snapshot;self.profile_current=current;self.driver=driver
            self.scheduler_bytes={a["portable_name"]:a["content_utf8"].encode() for a in snapshot.scheduler_artifacts}
            token=rtwin._GAUSSIAN_LAUNCH_OWNER.set((snapshot,current_approvals))
            try:
                result=self.execute();self.assertEqual(result.outcome,"SUCCEEDED")
                self.assertIsNone(rtwin._GAUSSIAN_WIRE_CONTEXT.get())
                count=len(calls);self.execute();self.assertEqual(len(calls),count)
            finally:rtwin._GAUSSIAN_LAUNCH_OWNER.reset(token)
        self.assertEqual([r["operation"] for r in calls],["ALLOCATE_WORKSPACE"]+["STAGE_EXACT_FILE"]*5+["SUBMIT_QSUB_ONCE"])

    def test_historical_source_bytes_and_child_status_helpers_unchanged(self):
        import ast
        from auto_g16.execution import _crest_startup, _gaussian_startup as historical_startup
        from auto_g16.transport import _bridge, _gaussian_submit as historical_submit
        wrapper=previous.gaussian._wrapper_sources()[0]
        self.assertEqual(sha256(wrapper.encode()).hexdigest(),"7bfeeb7acff1ce08f1e582a554590a6070befa348dcec6d38c9a3a0de2639af5")
        self.assertEqual(sha256(_crest_startup._LOADER_SOURCE.encode()).hexdigest(),"a550727e4c39a703a63ac1befdb3ec86ebe7bf3ef94e9252fcbf14d6ca373b37")
        self.assertEqual(sha256(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(),"dee52a198f0b5f70797329331505710564ea11916d69cb1f88ac7e6b0d1fb5dc")
        self.assertEqual((len(historical_startup._LOADER_SOURCE.encode()),sha256(historical_startup._LOADER_SOURCE.encode()).hexdigest()),(9693,"4e535f907464604b9ae0cba8b1a418ea48e2fac43c0e0d4d5773d6b7650d3002"))
        self.assertEqual((len(historical_submit.source_bytes()),sha256(historical_submit.source_bytes()).hexdigest()),(42890,"4fff8379fb67d70763f9cc6f37bfd1580c90c5efb7e41c172717124c4389ae52"))
        historical_profile,_,historical_q,_,historical_spec,_,_,historical_material,historical_snapshot=self.qualified_case(startup=True)
        self.assertEqual((historical_spec.adapter_contract_version,historical_material["schema"]),(4,historical_startup._MATERIAL_SCHEMA))
        self.assertEqual(completion._decode_publisher_qualification(historical_profile.runtime_contents[historical_startup._Q_NAME])["payload"]["schema"],historical_startup._Q_SCHEMA)
        historical_snapshot.assert_identity_closed()
        self.assertNotEqual(historical_q["contract_sha256"],self.q["contract_sha256"])
        newer=startup._wrapper_sources()[0]
        def functions(source):return {n.name:ast.get_source_segment(source,n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        oldfunc,newfunc=functions(wrapper),functions(newer)
        for name in ("subreaper","wait_all","exclusive","publish","file_identity"):
            self.assertEqual(oldfunc[name],newfunc[name])
        oldrun=oldfunc["run"];newrun=newfunc["run"].replace('        __auto_g16_publish_stage__("launch-lock-handoff")\n','')
        for before,after in ((previous.gaussian._MATERIAL_SCHEMA,startup._MATERIAL_SCHEMA),(previous.gaussian._Q_SCHEMA,startup._Q_SCHEMA),("v31-completion-prebinding/6","v31-completion-prebinding/8"),('spec["adapter_contract_version"]!=3','spec["adapter_contract_version"]!=5')):
            oldrun=oldrun.replace(before,after)
        self.assertEqual(oldrun,newrun)


INERT = b'''keys=set(globals())
__auto_g16_publish_stage__("wrapper-entered")
import base64,builtins,sys
builtins.gaussian_test_capture.append((keys,list(sys.argv),sys.stdin.read(),dict(__auto_g16_startup_context__)))
__auto_g16_publish_stage__("launch-lock-handoff")
raise SystemExit(7)
'''


class PhysicalFixture:
    """Real temp inodes, source-owned native function; qsub is never a process."""
    def __init__(self, root):
        self.ns = {"__name__": "inert_native"}
        source = submit.source_bytes().decode().split("try: main()\n", 1)[0]
        exec(compile(source, "<inert-native>", "exec"), self.ns)
        self.loader = {"__name__": "inert_loader"}
        exec(compile(startup._DECODED_LOADER_SOURCE, "<inert-loader>", "exec"), self.loader)
        self.project = Path(root).resolve()
        self.project.chmod(0o700)
        self.attempt = "11111111-1111-4111-8111-111111111111"
        self.workspace = self.project / self.attempt
        self.workspace.mkdir(mode=0o700)
        self.fd, self.token = self.ns["directory"](str(self.workspace))
        self.pfd, self.ptoken = self.ns["directory"](str(self.project))
        self.resources = {"cores":1,"memory_mb":128,"walltime_seconds":10,"queue":"batch"}
        binding = {"binding_schema":"v31-completion-prebinding/8", "attempt_id":self.attempt,
            "workspace_binding_id":"w", "project_physical_binding_id":"p", "resolved_server_profile_id":"r",
            "cwd_binding":{"location_kind":"server", "path":str(self.workspace)},
            "wrapper_source_sha256":sha256(INERT).hexdigest(), "wrapper_source_size_bytes":len(INERT)}
        spec={"program_kind":"gaussian","adapter_contract_version":5}
        material={"schema":startup._MATERIAL_SCHEMA}
        sem=self.loader["g_sem"]
        binding.update(rendering_material_sha256=sem(material),program_execution_spec_payload_sha256=sem(spec))
        self.config={"cores":1,"walltime_seconds":10,"material":material,"spec":spec,"prebinding":binding,"prebinding_sha256":sem(binding)}
        self.cfg=self.ns["g_json"](self.config,False)
        payload=self.ns["g_json"]({"schema":startup._PAYLOAD_SCHEMA,
            "wrapper_source":startup._envelope(INERT,"auto-g16-v31-gaussian-wrapper-source-bytes/1"),
            "config":startup._envelope(self.cfg,"auto-g16-v31-gaussian-wrapper-config-bytes/1")})
        entry=b"#!/bin/sh\n# inert snapshot bytes; never executed\n__AUTO_G16_CARRIER_DESCRIPTOR_BASE64__\n"
        fields={k:v for k,v in binding.items() if k not in ("binding_schema","wrapper_source_sha256","wrapper_source_size_bytes","rendering_material_sha256")}
        fields["scheduler_artifacts"]=[{"logical_role":role,"portable_name":name,"format":form,**self.ns["g_digest"](raw),"content_utf8":raw.decode()} for role,name,form,raw in (("scheduler-script","gaussian-entry-template.pbs","pbs-shell-utf8",entry),("startup-payload","gaussian-startup.json","canonical-json-utf8",payload))]
        effect=self.loader["g_id"]("program-effect-intent",fields)
        snapshot=self.loader["g_id"]("program-execution-snapshot",{"effect_intent_id":effect,**fields})
        self.b={"remote_workspace":str(self.workspace),"workspace_physical_token":self.token,"project_directory":str(self.project),"project_physical_identity":self.ptoken,"attempt_id":self.attempt,"program_execution_snapshot_id":snapshot,"effect_intent_id":effect,"resolved_server_profile_id":"r"}
        marker=self.ns["g_json"]({"program_execution_snapshot_id":snapshot,"effect_intent_id":effect})
        rows=[];staged=[]
        for index,(kind,name,raw) in enumerate((("program-input","flow.gjf",previous.OPT),("scheduler-script","gaussian-entry-template.pbs",entry),("startup-payload","gaussian-startup.json",payload),("derived-config","gaussian-config.json",self.cfg),("submit-intent-marker",".auto-g16-v31-submit-intent",marker))):
            file=self.workspace/name;file.write_bytes(raw);file.chmod(0o600)
            token=self.ns["g_b64"](self.ns["g_json"](["v31-file/1",self.token,name,self.ns["g_ident"](file.stat())]))
            staged.append({"artifact_kind":kind,"portable_name":name,**self.ns["g_digest"](raw),"artifact_physical_token":token})
            if index: rows.append({"role":self.ns["G_ROLES"][index-1],"artifact_authority_id":"a"+str(index),"stage_receipt_id":"s"+str(index),"stage_receipt_payload_sha256":"1"*64,"physical_token_base64":token})
        approvals={k:{"authority_id":k,"payload_sha256":"2"*64} for k in ("scientific","finite_batch","operational_confirmation","live_gate")}
        predecessor={k:k for k in ("transport_store_id","store_instance_id","runtime_attestation_id","workspace_authority_id","allocation_receipt_id")}
        predecessor["allocation_receipt_payload_sha256"]="3"*64
        self.p={"request_payload":{"scheduler_portable_name":"gaussian.pbs","scheduler_artifact_authority_id":"a1","program_input_artifact_authority_ids":["science"],"startup_payload_artifact_authority_ids":["a2"],"handoff_artifact_authority_ids":["a3","a4"]},"resources":self.resources,"staged":staged,
            "launch_context":{"project_id":"p","project_physical_binding_id":"p","workspace_binding_id":"w","approvals":approvals,"predecessor":predecessor,"stages":rows}}
        py=Path(sys.executable).resolve()
        self.constants={"schema":"auto-g16-v31-gaussian-startup-invocation/1","attempt_id":self.attempt,"workspace_binding_id":"w","workspace":str(self.workspace),"project_physical_binding_id":"p","resolved_server_profile_id":"r","payload":self.ns["g_digest"](payload),"wrapper_source":self.ns["g_digest"](INERT),"resources":self.resources,"server_python":{"path":str(py),**self.ns["g_digest"](py.read_bytes())}}
        self.calls=[]
        def inert_run(root,args,fd,cap):
            self.assert_qsub_start()
            self.calls.append(args)
            return 0,b"123.server\n",b""
        self.ns["run_exact"]=inert_run

    def close(self):
        os.close(self.fd);os.close(self.pfd)

    def submit(self):
        result=self.ns["g_submit"](self.b,self.p,{"server_qsub":{"path":"/inert/qsub"}},self.fd,self.pfd)
        self.carrier_pin=(self.workspace/self.ns["G_ENTRY"]).read_bytes().splitlines()[-1].decode("ascii")
        return result

    def carrier(self):
        return self.ns["g_carrier"]((self.workspace/self.ns["G_CARRIER"]).read_bytes())

    def assert_qsub_start(self):
        carrier_path=self.workspace/self.ns["G_CARRIER"]
        start_path=self.workspace/self.ns["G_QSUB_START"]
        assert carrier_path.exists() and start_path.exists()
        assert carrier_path.stat().st_ino==(self.workspace/self.ns["G_CARRIER_PENDING"]).stat().st_ino
        assert start_path.stat().st_ino==(self.workspace/self.ns["G_QSUB_START_PENDING"]).stat().st_ino

    def load(self, cwd=None, extra_env=None):
        saved=os.open(".",os.O_RDONLY)
        try:
            os.chdir(cwd or self.workspace)
            with patch.dict(os.environ,{"PBS_JOBID":"123.server",**(extra_env or {})},clear=True), patch.object(sys,"executable",self.constants["server_python"]["path"]), patch.object(sys,"argv",[]), patch.object(sys,"stdin"), patch.object(builtins,"gaussian_test_capture",[],create=True):
                try:self.loader["g_loader"](self.constants,self.carrier_pin)
                except SystemExit as exc:
                    return exc.code,list(builtins.gaussian_test_capture)
        finally:
            os.fchdir(saved);os.close(saved)


class PhysicalHandoffTests(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory(dir="/tmp");self.addCleanup(temp.cleanup)
        f=PhysicalFixture(temp.name);self.addCleanup(f.close)
        return f

    def test_native_handoff_file_carrier_direct_qsub_and_exact_retained_execution(self):
        f=self.fixture();self.assertEqual(f.submit(),{"job_id":"123.server"})
        self.assertEqual(len(f.calls),1)
        args=f.calls[0];self.assertEqual(args,["-d",str(f.workspace),"-l","nodes=1:ppn=1,mem=128mb,walltime=10","-q","batch","gaussian.pbs"])
        self.assertNotIn("-v",args);self.assertNotIn("-V",args)
        c=f.carrier()
        self.assertEqual(c["workspace"]["workspace_physical_token_base64"],f.token)
        pre=json.loads((f.workspace/"v31-launch-pre-authority.json").read_bytes())
        self.assertEqual(f.ns["g_validate_pre"](pre),c["handoff"]["launch_handoff_pre_authority_id"])
        start=json.loads((f.workspace/"v31-qsub-invocation-start.json").read_bytes())
        self.assertEqual(start["raw_argv"],["/inert/qsub",*args])
        self.assertEqual(start["carrier"]["sha256"],sha256((f.workspace/"v31-launch-carrier.json").read_bytes()).hexdigest())
        self.assertEqual(start["carrier"]["file_identity"]["inode"],(f.workspace/"v31-launch-carrier.json").stat().st_ino)
        self.assertEqual(start["entry"]["file_identity"]["inode"],(f.workspace/"gaussian.pbs").stat().st_ino)
        self.assertEqual((f.workspace/"gaussian.pbs").stat().st_ino,(f.workspace/"gaussian.pbs.pending").stat().st_ino)
        post=json.loads((f.workspace/"v31-qsub-launch-carrier-receipt.json").read_bytes())
        self.assertEqual(post["schema"],"auto-g16-v31-gaussian-qsub-launch-carrier-receipt/2")
        self.assertEqual(post["outcome"],"SUCCEEDED");self.assertEqual(post["raw_argv"][1:],args)
        self.assertEqual(post["carrier"],start["carrier"])
        code,captures=f.load();self.assertEqual(code,7)
        self.assertEqual(captures[0][0],{"__name__","__file__","__package__","__cached__","__builtins__","__auto_g16_startup_context__","__auto_g16_publish_stage__"})
        self.assertEqual(captures[0][1],["<auto-g16-v31-gaussian-wrapper>"])
        self.assertEqual(captures[0][2],base64.b64encode(f.cfg).decode()+"\n")
        prior=None
        for stage in f.ns["G_STAGES"]:
            path=f.workspace/(".auto-g16-v31-"+stage+".json");raw=path.read_bytes();value=f.ns["g_stage"](json.loads(raw))
            self.assertEqual(value["previous_stage_sha256"],prior);prior=sha256(raw).hexdigest()
            self.assertEqual(path.stat().st_ino,path.with_suffix(".pending").stat().st_ino)
        self.assertFalse((f.workspace/"v31-completion.json").exists())
        with self.assertRaises(ValueError):f.submit()
        self.assertEqual(len(f.calls),1)

    def test_pre_authority_deep_backrefs_and_wrong_id_fail(self):
        f=self.fixture();f.submit()
        pre=json.loads((f.workspace/"v31-launch-pre-authority.json").read_bytes())
        for path in ((),("scope",),("scope","attempt"),("approvals",),("approvals","scientific"),("predecessor",),("handoff",),("carrier_contract",)):
            for field in ("carrier_hash","raw_argv","post_receipt_id","job_id","outcome"):
                bad=copy.deepcopy(pre);node=bad
                for key in path:node=node[key]
                node[field]="forbidden"
                with self.subTest(path=path,field=field),self.assertRaises(ValueError):f.ns["g_validate_pre"](bad)
        carrier_path=f.workspace/f.ns["G_CARRIER"]
        raw=carrier_path.read_bytes();pid=f.carrier()["handoff"]["launch_handoff_pre_authority_id"].encode()
        carrier_path.write_bytes(raw.replace(pid,b"x"*len(pid),1))
        with self.assertRaises(ValueError):f.load()
        self.assertFalse((f.workspace/".auto-g16-v31-entry-start.json").exists())

    def test_carrier_noncanonical_duplicate_and_caps(self):
        f=self.fixture();f.submit();decoded=f.carrier();raw=f.ns["g_json"](decoded)
        invalid=[raw+b"\n",raw[:-1],b" "*65537,raw.replace(b'{',b'{"schema":"duplicate",',1)]
        doubled=copy.deepcopy(decoded);doubled["workspace"]["workspace_physical_token_base64"]=base64.b64encode(f.token.encode()).decode()
        invalid.append(f.ns["g_json"](doubled))
        for value in invalid:
            with self.assertRaises(ValueError):f.ns["g_carrier"](value)

    def test_pre_submit_replacement_missing_stage_and_resource_fail_zero(self):
        for name in ("flow.gjf","gaussian-entry-template.pbs","gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent"):
            f=self.fixture();p=f.workspace/name;p.rename(p.with_name(p.name+".original"));p.write_bytes(p.with_name(p.name+".original").read_bytes());p.chmod(0o600)
            with self.subTest(name=name),self.assertRaises(ValueError):f.submit()
            self.assertEqual(f.calls,[])
        for mutate in (lambda f:f.p["launch_context"]["stages"].pop(),lambda f:f.resources.update(cores=True),lambda f:f.p["request_payload"].update(extra="bad"),lambda f:f.p["launch_context"]["stages"].reverse()):
            f=self.fixture();mutate(f)
            with self.assertRaises((ValueError,KeyError)):f.submit()
            self.assertEqual(f.calls,[])

    def test_loader_i3_replacements_and_original_cwd_survival(self):
        for name in ("v31-launch-carrier.json","v31-qsub-invocation-start.json","v31-launch-handoff.json","gaussian.pbs","gaussian-entry-template.pbs","gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent"):
            f=self.fixture();f.submit();p=f.workspace/name;p.rename(p.with_name(p.name+".original"));p.write_bytes(p.with_name(p.name+".original").read_bytes());p.chmod(0o600)
            with self.subTest(name=name),self.assertRaises(ValueError):f.load()
        f=self.fixture();f.submit();original=f.workspace.with_name("retained");f.workspace.rename(original);f.workspace.mkdir(mode=0o700)
        with self.assertRaises(ValueError):f.load()
        self.assertEqual(list(f.workspace.iterdir()),[])
        self.assertEqual(f.load(cwd=original)[0],7)
        self.assertEqual(list(f.workspace.iterdir()),[])

    def test_i4_replacement_executes_retained_bytes_without_reopen(self):
        f=self.fixture();f.submit();publish=f.loader["g_publish"]
        def replacement(parent,pending,final,raw,check):
            value=publish(parent,pending,final,raw,check)
            if final==".auto-g16-v31-payload-verified.json":
                for name in ("v31-launch-carrier.json","v31-qsub-invocation-start.json","v31-launch-handoff.json","gaussian.pbs","gaussian-entry-template.pbs","gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent"):
                    p=f.workspace/name;p.rename(p.with_name(p.name+".original"));p.write_bytes(b"untrusted replacement");p.chmod(0o600)
            return value
        f.loader["g_publish"]=replacement
        self.assertEqual(f.load()[0],7)

    def test_same_byte_carrier_and_start_replacement_before_first_stage_refuses(self):
        f=self.fixture();f.submit();publish=f.loader["g_publish"]
        def replace_launch_evidence(parent,pending,final,raw,check):
            if final==".auto-g16-v31-entry-start.json":
                for pending_name,final_name in ((f.ns["G_CARRIER_PENDING"],f.ns["G_CARRIER"]),(f.ns["G_QSUB_START_PENDING"],f.ns["G_QSUB_START"])):
                    content=(f.workspace/final_name).read_bytes()
                    (f.workspace/pending_name).rename(f.workspace/(pending_name+".original"))
                    (f.workspace/final_name).rename(f.workspace/(final_name+".original"))
                    (f.workspace/pending_name).write_bytes(content);(f.workspace/pending_name).chmod(0o600)
                    os.link(f.workspace/pending_name,f.workspace/final_name)
            return publish(parent,pending,final,raw,check)
        f.loader["g_publish"]=replace_launch_evidence
        with self.assertRaises(ValueError):f.load()
        self.assertFalse((f.workspace/".auto-g16-v31-entry-start.json").exists())
        self.assertFalse((f.workspace/".auto-g16-v31-entry-start.pending").exists())

    def test_coordinated_pre_loader_carrier_and_start_replacement_refuses(self):
        f=self.fixture();f.submit()
        carrier_raw=(f.workspace/f.ns["G_CARRIER"]).read_bytes()
        for name in (f.ns["G_CARRIER_PENDING"],f.ns["G_CARRIER"]):
            (f.workspace/name).rename(f.workspace/(name+".original"))
        (f.workspace/f.ns["G_CARRIER_PENDING"]).write_bytes(carrier_raw)
        (f.workspace/f.ns["G_CARRIER_PENDING"]).chmod(0o600)
        os.link(f.workspace/f.ns["G_CARRIER_PENDING"],f.workspace/f.ns["G_CARRIER"])
        carrier=f.ns["g_carrier"](carrier_raw)
        stat_result=(f.workspace/f.ns["G_CARRIER"]).stat()
        replacement_desc=f.ns["g_file_desc"](str(f.workspace),carrier["handoff"]["parent_chain"],f.token,f.ns["G_CARRIER"],stat_result,carrier_raw)
        start=json.loads((f.workspace/f.ns["G_QSUB_START"]).read_bytes());start["carrier"]=replacement_desc
        start_raw=f.ns["g_json"](start)
        for name in (f.ns["G_QSUB_START_PENDING"],f.ns["G_QSUB_START"]):
            (f.workspace/name).rename(f.workspace/(name+".original"))
        (f.workspace/f.ns["G_QSUB_START_PENDING"]).write_bytes(start_raw)
        (f.workspace/f.ns["G_QSUB_START_PENDING"]).chmod(0o600)
        os.link(f.workspace/f.ns["G_QSUB_START_PENDING"],f.workspace/f.ns["G_QSUB_START"])
        with self.assertRaises(ValueError):f.load()
        self.assertFalse((f.workspace/".auto-g16-v31-entry-start.json").exists())

    def test_atomic_publication_failures_leave_evidence_without_qsub(self):
        for operation in ("write","fsync","link"):
            f=self.fixture()
            with patch.object(f.ns["os"],operation,side_effect=OSError("inert injected failure")):
                with self.assertRaises(OSError):f.submit()
            self.assertEqual(f.calls,[])
            self.assertTrue((f.workspace/"v31-launch-reattestation.pending").exists())
            with self.assertRaises(ValueError):f.submit()
            self.assertEqual(f.calls,[])

    def test_payload_envelopes_duplicate_keys_caps_and_config_types(self):
        f=self.fixture();raw=(f.workspace/"gaussian-startup.json").read_bytes();p=json.loads(raw)
        for field,value in (("encoding","BASE64"),("size_bytes",True),("sha256","0"*64),("data_base64",p["config"]["data_base64"]+"\n")):
            bad=copy.deepcopy(p);bad["config"][field]=value
            with self.assertRaises(ValueError):f.ns["g_payload"](f.ns["g_json"](bad))
        for data in (raw+b"\n",raw.replace(b'{',b'{"schema":"duplicate",',1),b"\xef\xbb\xbf"+raw):
            with self.assertRaises(ValueError):f.ns["g_payload"](data)

    def test_each_stage_closed_schema_and_publication_crash_boundary(self):
        f=self.fixture();f.submit();f.load()
        for stage in f.ns["G_STAGES"]:
            raw=(f.workspace/(".auto-g16-v31-"+stage+".json")).read_bytes();value=json.loads(raw)
            for key in value:
                bad=copy.deepcopy(value);bad.pop(key)
                with self.subTest(stage=stage,key=key),self.assertRaises(ValueError):f.ns["g_stage"](bad)
            for change in ({"extra":1},{"stage":"unknown"},{"attempt_id":"bad"},{"job_id":"-bad"},{"created_at":"yesterday"},{"payload_expected":{**value["payload_expected"],"size_bytes":True}}):
                with self.assertRaises(ValueError):f.ns["g_stage"]({**value,**change})
            broken=self.fixture();broken.submit();publish=broken.loader["g_publish"]
            def crash(parent,pending,final,raw,check):
                if final==".auto-g16-v31-"+stage+".json":raise OSError("inert stage crash")
                return publish(parent,pending,final,raw,check)
            broken.loader["g_publish"]=crash
            with self.assertRaises(OSError):broken.load()
            self.assertFalse((broken.workspace/(".auto-g16-v31-"+stage+".json")).exists())
            self.assertFalse((broken.workspace/"v31-completion.json").exists())

    def test_symlink_mode_drift_and_qsub_uncertainty_preserve_evidence(self):
        for name in ("gaussian-entry-template.pbs","gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent"):
            for symlink in (True,False):
                f=self.fixture();p=f.workspace/name
                if symlink:
                    p.rename(p.with_name(p.name+".original"));p.symlink_to(p.name+".original")
                else:p.chmod(0o644)
                with self.assertRaises((ValueError,OSError)):f.submit()
                self.assertEqual(f.calls,[])
        f=self.fixture()
        def unknown(*args):f.calls.append(args);raise OSError("inert uncertain invocation")
        f.ns["run_exact"]=unknown
        with self.assertRaises(OSError):f.submit()
        post=json.loads((f.workspace/"v31-qsub-launch-carrier-receipt.json").read_bytes())
        self.assertEqual(post["outcome"],"UNKNOWN");self.assertEqual(post["invocation_status"],"interrupted-or-timeout");self.assertIsNone(post["job_id"])
        self.assertTrue((f.workspace/"v31-qsub-invocation-start.json").exists())
        with self.assertRaises(ValueError):f.submit()
        self.assertEqual(len(f.calls),1)

        failed=self.fixture()
        def rejected(root,args,fd,cap):
            failed.assert_qsub_start();failed.calls.append(args);return 1,b"",b"rejected\n"
        failed.ns["run_exact"]=rejected
        with self.assertRaises(ValueError):failed.submit()
        receipt=json.loads((failed.workspace/"v31-qsub-launch-carrier-receipt.json").read_bytes())
        self.assertEqual((receipt["outcome"],receipt["invocation_status"],receipt["returncode"],receipt["job_id"]),("FAILED","returned",1,None))
        with self.assertRaises(ValueError):failed.submit()
        self.assertEqual(len(failed.calls),1)

    def test_timeout_persists_partial_trace_and_blocks_second_qsub(self):
        f=self.fixture()
        def timed_out(root,args,fd,cap):
            f.assert_qsub_start();f.calls.append(args)
            f.ns["G_QSUB_TRACE"].update(out=b"partial job",err=b"deadline reached\n",code=1)
            raise TimeoutError("inert qsub deadline")
        f.ns["run_exact"]=timed_out
        with self.assertRaises(TimeoutError):f.submit()
        receipt=json.loads((f.workspace/"v31-qsub-launch-carrier-receipt.json").read_bytes())
        self.assertEqual((receipt["outcome"],receipt["invocation_status"],receipt["returncode"],receipt["job_id"]),("UNKNOWN","interrupted-or-timeout",1,None))
        self.assertEqual(base64.b64decode(receipt["stdout_base64"]),b"partial job")
        self.assertEqual(base64.b64decode(receipt["stderr_base64"]),b"deadline reached\n")
        with self.assertRaises(ValueError):f.submit()
        self.assertEqual(len(f.calls),1)

    def test_short_writes_read_drift_and_post_final_crash_are_closed(self):
        f=self.fixture();write=os.write
        with patch.object(os,"write",side_effect=lambda fd,data:write(fd,data[:7])):
            self.assertEqual(f.submit(),{"job_id":"123.server"})
        for name in ("gaussian-startup.json","gaussian-config.json"):
            broken=self.fixture();broken.submit();target=broken.workspace/name
            before=target.read_bytes();target.write_bytes(before+b"x")
            with self.assertRaises(ValueError):broken.load()
            self.assertFalse((broken.workspace/".auto-g16-v31-wrapper-entered.json").exists())
        for final in ("v31-launch-handoff.json","v31-launch-pre-authority.json","v31-launch-carrier.json","v31-qsub-invocation-start.json"):
            broken=self.fixture();publish=broken.ns["g_publish"]
            def crash(parent,pending,name,raw,check):
                result=publish(parent,pending,name,raw,check)
                if name==final:raise OSError("inert post-final interruption")
                return result
            broken.ns["g_publish"]=crash
            with self.assertRaises(OSError):broken.submit()
            self.assertEqual(broken.calls,[]);self.assertTrue((broken.workspace/final).exists())
            with self.assertRaises(ValueError):broken.submit()
            self.assertEqual(broken.calls,[])

    def test_i1_i2_directory_mode_and_owner_drift_refuse_before_qsub(self):
        for phase in ("v31-launch-reattestation.json","v31-launch-pre-authority.json"):
            for target in ("project","workspace"):
                for field in ("mode","uid"):
                    f=self.fixture();publish=f.ns["g_publish"];fstat=os.fstat;drift=[]
                    folder=getattr(f,target);identity=folder.stat().st_ino
                    def injected_stat(fd):
                        s=fstat(fd)
                        if drift and field=="uid" and s.st_ino==identity:
                            values={k:getattr(s,k) for k in dir(s) if k.startswith("st_")}
                            return SimpleNamespace(**{**values,"st_uid":s.st_uid+1})
                        return s
                    def change(parent,pending,final,raw,check):
                        value=publish(parent,pending,final,raw,check)
                        if final==phase:
                            if field=="mode":folder.chmod(0o755)
                            drift.append(True)
                        return value
                    f.ns["g_publish"]=change
                    with self.subTest(phase=phase,target=target,field=field),patch.object(os,"fstat",side_effect=injected_stat):
                        with self.assertRaises(ValueError):f.submit()
                    self.assertEqual(f.calls,[])

    def test_publication_link_boundary_rechecks_regular_owner_mode_size(self):
        import stat
        for field in ("mode","uid","type","size"):
            f=self.fixture();link=os.link;fstat=os.fstat;linked=[]
            def injected_link(*args,**kwargs):
                result=link(*args,**kwargs);linked.append(True)
                if field=="mode":(f.workspace/"test-final.json").chmod(0o644)
                return result
            def injected_stat(fd):
                s=fstat(fd)
                if not linked or not stat.S_ISREG(s.st_mode) or field=="mode":return s
                change={"uid":{"st_uid":s.st_uid+1},"type":{"st_mode":stat.S_IFDIR|0o600},"size":{"st_size":s.st_size+1}}[field]
                return SimpleNamespace(**{**{k:getattr(s,k) for k in dir(s) if k.startswith("st_")},**change})
            with self.subTest(field=field),patch.object(os,"link",side_effect=injected_link),patch.object(os,"fstat",side_effect=injected_stat):
                with self.assertRaises(ValueError):f.ns["g_publish"](f.fd,"test-pending.json","test-final.json",b"{}\n",lambda:None)
            self.assertTrue((f.workspace/"test-pending.json").exists())
            self.assertTrue((f.workspace/"test-final.json").exists())

    def test_carrier_environment_and_wrong_interpreter_refuse_before_entry(self):
        f=self.fixture();f.submit()
        # The direct-qsub path accepts no launch carrier environment at all.
        saved=os.open(".",os.O_RDONLY)
        try:
            os.chdir(f.workspace)
            with patch.dict(os.environ,{"AUTO_G16_LAUNCH_HANDOFF_AUTH":"forbidden"},clear=True):
                with patch.dict(f.loader,{"g_carrier":lambda v:(_ for _ in ()).throw(AssertionError("must reject before parsing"))}):
                    with self.assertRaises(ValueError):f.loader["g_loader"](f.constants,f.carrier_pin)
        finally:os.fchdir(saved);os.close(saved)
        f.constants["server_python"]["sha256"]="0"*64
        with self.assertRaises(ValueError):f.load()
        self.assertFalse((f.workspace/".auto-g16-v31-entry-start.json").exists())


if __name__ == "__main__":
    unittest.main()
