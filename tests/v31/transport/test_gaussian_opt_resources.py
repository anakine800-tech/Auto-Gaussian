"""Opt resource contract: synthetic offline evidence, never target qualification."""
from hashlib import sha256
import unittest

from auto_g16.execution import ExecutionValueError
from auto_g16.execution.program import _validate_gaussian_input


BODY = b"#p RHF/STO-3G Opt=(MaxCycles=128) SCF=Tight\n\nsynthetic\n\n0 1\nH 0 0 0\nH 0 0 0.7\n\n"
PREFIX = b"%chk=gaussian.chk\n%mem=12GB\n%nprocshared=8\n"
INPUT = PREFIX + BODY


class GaussianOptResourceGrammarTests(unittest.TestCase):
    def parse(self, raw=INPUT, stage="opt"):
        return _validate_gaussian_input("synthetic.gjf", raw, {"stage": stage}, resource_link0=True)

    def test_exact_bytes_and_units_are_preserved_without_scheduler_mapping(self):
        before = sha256(INPUT).hexdigest()
        parsed = self.parse()
        self.assertEqual(dict(parsed), {"memory_value": 12, "memory_unit": "GB", "cores": 8})
        self.assertEqual(sha256(INPUT).hexdigest(), before)
        self.assertNotIn("memory_mb", parsed)
        with self.assertRaises(TypeError):
            parsed["cores"] = 1
        for token, value, unit in ((b"12288MB", 12288, "MB"), (b"12gb", 12, "GB")):
            with self.subTest(token=token):
                self.assertEqual(dict(self.parse(INPUT.replace(b"12GB", token))),
                                 {"memory_value": value, "memory_unit": unit, "cores": 8})

    def test_required_unique_fields_and_no_extra_link0(self):
        for line in PREFIX.splitlines(keepends=True):
            for raw in (INPUT.replace(line, b""), line + INPUT):
                with self.subTest(raw=raw), self.assertRaises(ExecutionValueError):
                    self.parse(raw)
        for extra in (b"%oldchk=old.chk", b"%rwf=scratch", b"%cpu=0-7", b"%nproc=8", b"%save", b"%MEM=12GB"):
            with self.subTest(extra=extra), self.assertRaises(ExecutionValueError):
                self.parse(extra + b"\n" + INPUT)

    def test_ambiguous_or_unbounded_memory_and_core_syntax_rejects(self):
        for value in (b"12", b"12G", b"12GiB", b"12GW", b"12000KB", b"12.0GB", b"+12GB",
                      b"0GB", b"012GB", b"1e1GB", b"12 GB", b"12GB #comment", b"1000000000MB"):
            with self.subTest(value=value), self.assertRaises(ExecutionValueError):
                self.parse(INPUT.replace(b"12GB", value))
        for value in (b"0", b"08", b"+8", b"8.0", b"8MB", b"8 ", b"1000000000"):
            with self.subTest(value=value), self.assertRaises(ExecutionValueError):
                self.parse(INPUT.replace(b"nprocshared=8", b"nprocshared=" + value))

    def test_checkpoint_paths_and_instruction_injection_reject(self):
        for path in (b"../gaussian.chk", b"/tmp/a.chk", b"$HOME/a.chk", b"Gaussian.chk", b"gaussian.chk;id"):
            with self.subTest(path=path), self.assertRaises(ExecutionValueError):
                self.parse(INPUT.replace(b"gaussian.chk", path))
        for raw in (INPUT.replace(b"12GB", b"12GB\x0b%mem=1GB"),
                    INPUT.replace(b"SCF=Tight", b"SCF=Tight %mem=1GB"),
                    INPUT.replace(b"SCF=Tight", b"SCF=Tight @external"),
                    INPUT.replace(b"\n", b"\r\n"), INPUT + b"--Link1--\n",
                    INPUT + b"@coordinates\n", INPUT.replace(b"synthetic", b"bad\x00title")):
            with self.subTest(raw=raw), self.assertRaises(ExecutionValueError):
                self.parse(raw)

    def test_only_self_contained_minimum_opt(self):
        for route in (b"Freq", b"Opt=(TS,CalcFC)", b"Opt=QST2", b"Opt(QST3)", b"Opt IRC",
                      b"Opt Geom=AllCheck", b"Opt Guess=Read", b"Opt=ReadFC", b"Opt=Restart", b"Opt External=program",
                      b"Opt=(Saddle=2,CalcFC)", b"Opt=RCFC", b"Opt=ReadCartesianFC",
                      b"Opt FOpt=TS", b"Opt POpt=(Saddle=1)", b"Opt IRCMax", b"Opt=UnknownOption",
                      b"Opt Density=Checkpoint", b"Opt SCF=Restart", b"Opt SCRF=Check",
                      b"Opt Guess=TCheck", b"Opt ExtraLinks=L9999"):
            raw = INPUT.replace(b"Opt=(MaxCycles=128)", route)
            with self.subTest(route=route), self.assertRaises(ExecutionValueError):
                self.parse(raw)
        with self.assertRaises(ExecutionValueError):
            self.parse(stage="freq")

    def test_historical_default_keeps_resource_rejection_and_return_value(self):
        self.assertIsNone(_validate_gaussian_input("old.gjf", BODY, {"stage": "opt"}))
        self.assertIsNone(_validate_gaussian_input("old.gjf", b"%chk=GAUSSIAN.CHK\n" + BODY, {"stage": "opt"}))
        with self.assertRaises(ExecutionValueError):
            _validate_gaussian_input("old.gjf", INPUT, {"stage": "opt"})

    def test_closed_route_options_and_exact_scientific_text(self):
        route = b"#p wB97XD/Def2SVP Opt=(MaxCycles=128) SCF=(Tight,MaxCycle=128) Integral=UltraFine NoSymm"
        raw = PREFIX + route + BODY[BODY.index(b"\n"):]
        self.assertEqual(dict(self.parse(raw)), {"memory_value": 12, "memory_unit": "GB", "cores": 8})
        for token in (b"Opt=(CalcFC,Tight,MaxStep=10)", b"Opt", b"Opt = (MaxCycles=128)"):
            with self.subTest(token=token):
                self.parse(INPUT.replace(b"Opt=(MaxCycles=128)", token))

    def test_duplicate_or_malformed_route_declarations_reject(self):
        for token in (b"Opt Opt", b"Opt=(MaxCycles=12,MaxCycles=128)", b"Opt=(Tight,Tight)",
                      b"Opt=(MaxCycles=0)", b"Opt=(MaxCycles=-1)", b"Opt=(MaxCycles=1e2)",
                      b"Opt=(MaxCycles=128,)", b"Opt=(MaxCycles=(128))", b"Opt;id"):
            with self.subTest(token=token), self.assertRaises(ExecutionValueError):
                self.parse(INPUT.replace(b"Opt=(MaxCycles=128)", token))
        for suffix in (b",Freq", b",Opt(TS)", b",ExtraLinks(L9999)", b"(d,p)"):
            with self.subTest(suffix=suffix), self.assertRaises(ExecutionValueError):
                self.parse(INPUT.replace(b"STO-3G", b"STO-3G" + suffix))




from tests.v3.execution.test_v31_lane_a import LaneAFixture
from tests.v31.transport import test_gaussian_successor as predecessor
from auto_g16.execution import _gaussian_resources as resources
from auto_g16.execution import _program_completion as completion, program
from auto_g16.execution._program_artifacts import _stage_material
from auto_g16 import execution
from unittest.mock import patch
from dataclasses import replace
import copy
import json


class GaussianOptResourceBindingTests(LaneAFixture):
    gaussian_profile = predecessor.GaussianSuccessorTests.gaussian_profile
    qualified_case = predecessor.GaussianSuccessorTests.qualified_case
    installed_case = predecessor.GaussianSuccessorTests.installed_case

    def case(self, **kwargs):
        return self.qualified_case(**{"startup":"resource", "input_raw":INPUT,
            "headroom_mib":4096, "resource_memory_mb":16384, **kwargs})

    def test_q7_snapshot_registers_with_readonly_owner_without_execution(self):
        from auto_g16.execution.readonly import ProgramReadSnapshot, _snapshot
        snapshot = self.case()[-1]
        raw = completion._receipt_json(snapshot._approval_semantics())
        with patch.object(program, "_render_scheduler_artifact", side_effect=AssertionError("render")), \
             patch.object(program.ProgramExecutionSnapshot, "_from_verified", side_effect=AssertionError("execution snapshot")), \
             patch("auto_g16.execution.program_runtime._assert_effect_intent_replay", side_effect=AssertionError("claim")), \
             patch("builtins.open", side_effect=AssertionError("open")):
            registration = ProgramReadSnapshot(content=raw, sha256=sha256(raw).hexdigest())
            detached = _snapshot(registration)
        self.assertEqual(detached.program_execution_spec.adapter_contract_version, 6)
        self.assertEqual(detached.effect_intent_id, snapshot.effect_intent_id)
        self.assertNotIsInstance(detached, program.ProgramExecutionSnapshot)

    def test_q7_readonly_rejects_self_consistent_resource_or_artifact_mismatch(self):
        from auto_g16.execution.readonly import ProgramReadSnapshot
        from auto_g16.execution._identity import semantic_id, semantic_sha256
        snapshot = self.case()[-1]
        original = json.loads(completion._receipt_json(snapshot._approval_semantics()))
        for field, replacement in (("cores", 7), ("memory_mib", 11264), ("artifact", "gaussian.pbs")):
            with self.subTest(field=field):
                value = copy.deepcopy(original)
                if field == "artifact":
                    value["scheduler_artifacts"][0]["portable_name"] = replacement
                else:
                    spec_data = value["program_execution_spec"]
                    spec_data["program_data"]["gaussian_resources"][field] = replacement
                    spec = program.ProgramExecutionSpec._from_closed(**{k:v for k,v in completion.freeze_mapping(spec_data, "test spec").items() if k != "program_execution_spec_id"})
                    value["program_execution_spec"] = json.loads(completion._receipt_json(spec.semantic_payload()))
                    value["program_execution_spec_id"] = spec.program_execution_spec_id
                    value["program_execution_spec_payload_sha256"] = semantic_sha256(spec.semantic_payload())
                payload = completion.freeze_mapping({key:value[key] for key in program._SNAPSHOT_PAYLOAD_FIELDS}, "test snapshot")
                value["effect_intent_id"] = semantic_id("program-effect-intent", payload)
                value["program_execution_snapshot_id"] = semantic_id("program-execution-snapshot", {"effect_intent_id":value["effect_intent_id"], **payload})
                raw = completion._receipt_json(value)
                expected = "historical persisted evidence differs" if field == "artifact" else ("Gaussian cores differ from resolved resources" if field == "cores" else "Gaussian working memory plus explicit headroom differs from PBS budget")
                with self.assertRaisesRegex(ExecutionValueError, expected):
                    ProgramReadSnapshot(content=raw, sha256=sha256(raw).hexdigest())

    def test_exact_spec_snapshot_review_restore_stage_and_native_protocol(self):
        rows = self.case()
        current, target, q, evidence, spec, service, binding, material, snapshot = rows
        self.assertEqual(spec.adapter_contract_version, 6)
        self.assertEqual(dict(spec.program_data["gaussian_resources"]),
                         {"memory_mib":12288,"cores":8,"headroom_mib":4096})
        self.assertEqual(spec.exact_inputs[0]["sha256"], sha256(INPUT).hexdigest())
        snapshot.assert_identity_closed()
        self.assertEqual(program._decode_program_review_semantics(snapshot._approval_semantics()), snapshot)
        with self.assertRaisesRegex(ExecutionValueError,"production Project journal"):
            service.restore_for_collection(self.store, reviewed_semantics=snapshot._approval_semantics())
        data = {a["portable_name"]:a["content_utf8"].encode() for a in snapshot.scheduler_artifacts}
        staged = _stage_material(snapshot, input_bytes={"flow.gjf":INPUT}, scheduler_artifact_bytes=data)
        self.assertEqual([d["artifact_kind"] for d,raw in staged],
                         ["program-input","scheduler-script","startup-payload","derived-config","submit-intent-marker"])
        self.assertEqual(staged[0][1], INPUT)
        cfg = resources._payload(snapshot.scheduler_artifacts)["config"]
        self.assertEqual((cfg["cores"],cfg["memory_mb"],cfg["walltime_seconds"]),(8,16384,3600))
        self.assertIn("#PBS -l mem=16384mb", snapshot.scheduler_artifacts[0]["content_utf8"])
        from auto_g16.transport import _gaussian_resource_submit as submit
        submit.assert_submit_timeout_contract()
        compile(submit.source_bytes(), "new-resource-bootstrap", "exec")
        compile(resources._DECODED_LOADER_SOURCE, "new-resource-loader", "exec")
        installation, authority = self.installed_case(current,target,q,evidence,snapshot)
        self.assertIsNotNone(installation)

    def test_budget_core_and_headroom_mismatches_fail_closed(self):
        from auto_g16.execution.program import _validate_gaussian_resource_binding
        rows = self.case(); spec=rows[4]; snapshot=rows[-1]
        for memory,cores in ((12288,8),(16383,8),(16385,8),(16384,7),(16384,16)):
            candidate=execution.ResolvedResourceRequest(resource_spec=self.store.load_resource_spec("resource-1"),
                cores=cores,memory_mb=memory,walltime_seconds=3600,queue="simple")
            with self.subTest(memory=memory,cores=cores), self.assertRaises(ExecutionValueError):
                _validate_gaussian_resource_binding(spec,candidate)
        for headroom in (None,0,-1,True,"4096"):
            with self.subTest(headroom=headroom), self.assertRaises(ExecutionValueError):
                program._prepare_program_execution_spec(program_kind="gaussian",executable_path=spec.invocation["executable_identity"]["absolute_path"],
                    executable_size_bytes=spec.invocation["executable_identity"]["size_bytes"],executable_sha256=spec.invocation["executable_identity"]["sha256"],
                    input_name="flow.gjf",input_bytes=INPUT,program_data={"stage":"opt"},resolved_profile=rows[1],
                    completion_mode=completion._MODE,startup_mode="short-entry-opt-resources-v3",gaussian_headroom_mib=headroom)

    def test_historical_owner_and_mixed_material_fail_closed(self):
        with patch.object(completion,"_resource_owner",side_effect=AssertionError("old tuple called new owner")):
            old=self.qualified_case(startup="file")[-1]
            old.assert_identity_closed()
            _stage_material(old,input_bytes={"flow.gjf":__import__("tests.v31.transport.test_gaussian_successor",fromlist=["OPT"]).OPT},
                            scheduler_artifact_bytes={a["portable_name"]:a["content_utf8"].encode() for a in old.scheduler_artifacts})
            old._approval_semantics()
        rows=self.case(); current,target,q,evidence,spec,service,binding,material,snapshot=rows
        with self.assertRaises(ExecutionValueError):
            service.prepare(self.store,attempt_id="attempt-1",calculation_plan_id="plan-1",resource_spec_id="resource-1",
                program_execution_spec=spec,project_physical_binding=binding,resolved_resource_request=snapshot.resolved_resource_request,
                resolved_server_profile=target,workspace_binding=self.workspace(),completion_rendering_material=old._completion_material())
        forged=copy.deepcopy(q);forged["implementation"]["wrapper_source"]["sha256"]="0"*64
        with self.assertRaises(ValueError):
            completion._decode_publisher_qualification(completion._receipt_json({"payload":forged,"payload_sha256":completion.semantic_sha256(forged)}))


    def test_new_tuple_same_attempt_mock_submit_receipt_restore_and_no_resubmit(self):
        from auto_g16.execution import program_runtime as runtime
        from auto_g16.transport import program as transport
        from tests.v31.transport import test_program_composition as composition, test_program_completion as old
        from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal, _ProjectProvisioningService
        current,_,_,_,_,service,_,_,snapshot=self.case()
        root=self.root/"resource-effects";root.mkdir()
        self.program_transport_store=transport._ProgramTransportStore._create_completion_store(root/"program.sqlite3",approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.snapshot=snapshot;self.driver=composition._Driver({"gaussian.log":b"Normal termination of Gaussian 16\n"})
        self.input_bytes={"flow.gjf":INPUT}
        self.scheduler_bytes={a["portable_name"]:a["content_utf8"].encode() for a in snapshot.scheduler_artifacts}
        runtime._prepare_program_execution(self.store,**self.kwargs(),input_bytes=self.input_bytes,scheduler_artifact_bytes=self.scheduler_bytes)
        execution.execute_once(self.store,snapshot=snapshot,current_profile=current,
            confirmed_execution_snapshot_id=snapshot.program_execution_snapshot_id,prepared_input_bytes=INPUT,
            pbs_template_bytes=self.scheduler_bytes["gaussian-entry-template.pbs"],port=runtime._ProgramExecutionPort(**self.kwargs()))
        self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.driver.calls),1)
        journal=_ProductionProvisioningJournal.create_new(root/"project.sqlite3",approved_root=root)
        self.addCleanup(journal.close);object.__setattr__(service._project_provisioning,"_journal",journal)
        count=len(self.driver.calls)
        with patch.object(_ProjectProvisioningService,"_assert_production_authority"),patch.object(_ProjectProvisioningService,"_assert_owned_binding"):
            self.assertEqual(service.restore_for_collection(self.store,reviewed_semantics=snapshot._approval_semantics()),snapshot)
            self.assertEqual(service.restore_for_reconciliation(self.store,reviewed_semantics=snapshot._approval_semantics()),snapshot)
        self.assertEqual(len(self.driver.calls),count)
        old.CompletionTests.publish(self)
        result=old.CompletionTests.collect(self)
        self.assertEqual(result.data["verdict"],"SUCCEEDED")
        count=len(self.driver.calls)
        runtime._replay_program_completion(self.store,**self.kwargs())
        self.assertEqual(len(self.driver.calls),count)

    kwargs = predecessor.GaussianSuccessorTests.kwargs

    def test_rendered_wrapper_real_inert_child_exact_stdin_and_zero_child_failures(self):
        self._run_native_fixture_isolated(with_parent_child=False)

    def test_rendered_wrapper_isolated_from_parent_inert_child(self):
        self._run_native_fixture_isolated(with_parent_child=True)

    def _run_native_fixture_isolated(self, *, with_parent_child):
        """The wrapper owns every child of its process, never the suite's children."""
        import subprocess, sys
        from pathlib import Path

        command = """
import unittest
from tests.v31.transport.test_gaussian_opt_resources import GaussianOptResourceBindingTests
case = GaussianOptResourceBindingTests('_check_rendered_wrapper_real_inert_child')
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([case]))
raise SystemExit(not result.wasSuccessful())
"""
        peer = None
        try:
            if with_parent_child:
                peer = subprocess.Popen(
                    [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                self.assertIsNone(peer.poll())
            completed = subprocess.run(
                [sys.executable, "-c", command],
                cwd=Path(__file__).resolve().parents[3],
                capture_output=True, text=True, timeout=45, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            if peer is not None:
                self.assertIsNone(peer.poll(), "fixture reaped or terminated the suite's child")
        finally:
            if peer is not None:
                peer.communicate(timeout=10)
                self.assertEqual(peer.returncode, 0)

    def _check_rendered_wrapper_real_inert_child(self):
        """Native local stdin/inode evidence; host observation and Linux entry adapted.

        Full rendered wrapper, qualification/source/spec/resource/file guards run.
        The source is not edited; only Linux host observation, subreaper and the
        /proc executable fd spelling are adapted on macOS. This is not Q7 target
        qualification or full file-carrier/loader qualification.
        """
        import os, sys, base64, subprocess
        from pathlib import Path
        from types import SimpleNamespace
        from tests.v31.transport.test_program_completion import manifest
        snapshot=self.case()[-1]
        payload=resources._payload(snapshot.scheduler_artifacts)
        source=payload["wrapper_source"]
        python=Path(sys.executable).resolve();python_raw=python.read_bytes()
        for scenario in ("success","budget","input","qualification","spec","source"):
            with self.subTest(scenario=scenario):
                workspace=(self.root/("native-"+scenario)).resolve();workspace.mkdir()
                child=workspace/"inert-child"
                child.write_text("#!"+str(python)+"\nimport sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n")
                child.chmod(0o700)
                raw=INPUT
                (workspace/"flow.gjf").write_bytes(raw)
                marker=completion._receipt_json({"program_execution_snapshot_id":"synthetic-snapshot","effect_intent_id":"synthetic-intent"})
                (workspace/".auto-g16-v31-submit-intent").write_bytes(marker)
                cfg=copy.deepcopy(payload["config"])
                spec=cfg["spec"];spec.pop("program_execution_spec_id")
                spec["invocation"]["executable_identity"]={"absolute_path":str(child),"sha256":sha256(child.read_bytes()).hexdigest(),"size_bytes":child.stat().st_size}
                spec["invocation"]["argv"]=[str(child)]
                cfg["spec"]=json.loads(completion._receipt_json(program.ProgramExecutionSpec._from_closed(**program.freeze_mapping(spec,"native fixture spec")).semantic_payload()))
                deploy=manifest();deploy["trust_roots"]["server_python"].update(path=str(python),expected_size_bytes=len(python_raw),expected_sha256=sha256(python_raw).hexdigest())
                cfg["material"]["deployment_manifest_base64"]=base64.b64encode(completion._receipt_json(deploy)).decode()
                q=json.loads(base64.b64decode(cfg["material"]["publisher_qualification_base64"]))["payload"]
                for name in ("g16root","GAUSS_EXEDIR","LD_LIBRARY_PATH"):q["runtime"]["gaussian_environment"][name]=str(workspace)
                q["runtime"]["gaussian"]={"path":str(child),"sha256":sha256(child.read_bytes()).hexdigest(),"size_bytes":child.stat().st_size}
                if scenario=="source":q["implementation"]["wrapper_source"]["sha256"]="0"*64
                if scenario=="qualification":q["schema"]="auto-g16-v31-publisher-qualification/6"
                cfg["material"]["publisher_qualification_base64"]=base64.b64encode(completion._receipt_json({"payload":q,"payload_sha256":completion.semantic_sha256(q)})).decode()
                fields={k:v for k,v in cfg["prebinding"].items() if k not in ("binding_schema","wrapper_source_sha256","wrapper_source_size_bytes","rendering_material_sha256")}
                fields.update(cwd_binding={"location_kind":"server","path":str(workspace)},program_execution_spec_id=cfg["spec"]["program_execution_spec_id"],program_execution_spec_payload_sha256=completion.semantic_sha256(cfg["spec"]))
                cfg["prebinding"]=json.loads(completion._receipt_json(completion._prebinding(fields,cfg["material"])))
                cfg["prebinding_sha256"]=completion.semantic_sha256(cfg["prebinding"])
                if scenario=="budget":cfg["memory_mb"]=12288
                if scenario=="spec":cfg["spec"]["program_data"]["gaussian_resources"]["cores"]=7
                if scenario=="input":(workspace/"flow.gjf").write_bytes(INPUT.replace(b"12GB",b"13GB"))
                stages=[];ns={"__name__":"native_resource_fixture","__auto_g16_publish_stage__":stages.append}
                exec(compile(source,"rendered-resource-wrapper","exec"),ns)
                ns["__auto_g16_startup_context__"]={"workspace":"unselected"}
                fd,token,chain=ns["pin_directory"](str(workspace))
                ns["__auto_g16_startup_context__"]={"cwd_fd":fd,"workspace":str(workspace),"workspace_token":token,"marker_bytes":marker,"marker_identity":ns["identity"](os.stat(workspace/".auto-g16-v31-submit-intent"))}
                observed={k:v for k,v in q["hosts"][0].items() if k not in ("locations","evidence")}
                observed["locations"]=[{k:v for k,v in loc.items() if k!="evidence"} for loc in q["hosts"][0]["locations"]]
                ns["observe_publisher_host"]=lambda *args:observed
                launches=[]
                def launch(argv,**kwargs):
                    launches.append(argv)
                    self.assertFalse(kwargs["shell"])
                    self.assertEqual(os.fstat(kwargs["stdin"]).st_ino,(workspace/"flow.gjf").stat().st_ino)
                    execfd=kwargs["pass_fds"][0]
                    self.assertEqual(kwargs["executable"],"/proc/self/fd/"+str(execfd))
                    self.assertEqual(os.fstat(execfd).st_ino,child.stat().st_ino)
                    if sys.platform!="linux":kwargs["executable"]=str(child)
                    return subprocess.Popen(argv,**kwargs)
                ns["subprocess"]=SimpleNamespace(Popen=launch)
                if sys.platform!="linux":ns["subreaper"]=lambda:None
                cwd=Path.cwd()
                try:
                    with patch.object(sys,"executable",str(python)),patch.dict(os.environ,{"PBS_JOBID":"123.server"},clear=True):
                        if scenario=="success":
                            self.assertEqual(ns["run"](cfg),0)
                            self.assertEqual((workspace/"gaussian.log").read_bytes(),INPUT)
                            receipt=completion._decode_receipt((workspace/"v31-completion.json").read_bytes())
                            self.assertEqual(receipt["inputs"][0]["sha256"],sha256(INPUT).hexdigest())
                        else:
                            with self.assertRaises(ValueError):ns["run"](cfg)
                            self.assertFalse((workspace/"v31-completion.json").exists())
                    self.assertEqual(len(launches),int(scenario=="success"))
                finally:
                    os.chdir(cwd)
                    for handle in reversed(chain):os.close(handle)


    def test_non_synthetic_q7_installed_driver_wire_and_rejection_gates(self):
        from tests.v31.transport import test_gaussian_short_entry as prior_delivery
        from auto_g16.transport import program as transport
        root=self.root/"q7-installed-effects";root.mkdir()
        self.program_transport_store=transport._ProgramTransportStore._create_completion_store(root/"transport.sqlite3",approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        prior_delivery.ShortEntryCompositionTests._check_installed_gaussian_delivery(
            self,startup_mode="resource",input_raw=INPUT,
            resource_kwargs={"headroom_mib":4096,"resource_memory_mb":16384})

    def execute(self):
        from tests.v31.transport import test_gaussian_short_entry as prior_delivery
        return prior_delivery.ShortEntryCompositionTests.execute(self)
