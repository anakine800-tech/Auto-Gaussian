"""Synthetic CREST version/semantic failures; never execute a scientific binary."""
from dataclasses import replace
from hashlib import sha256
import copy
import json
import unittest
import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from auto_g16 import execution, core
from auto_g16.execution import _crest_completion as crest
from auto_g16.execution import _program_completion as c
from auto_g16.execution import program as p, program_runtime as runtime
from auto_g16.execution import _crest_seed_handoff as handoffs
from auto_g16.transport import program as transport
from auto_g16.transport._canonical import TransportBoundaryError
from scripts import run_v31_publisher_pilot as controller
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport import test_program_completion as old
from tests.v31.transport import test_program_composition as composition
from tests.v31.transport import test_publisher_pilot_orchestration as pilot
from tests.v31.transport import test_crest_loader as loader_tests

LOG = b'CREST iMTD-GC SAMPLING\nMeta-Dynamics Iteration 1\nMTD Simulations done\nFinal Ensemble Information\nCREST terminated normally.\n'
FRAME = b'  2\n       -1.00000000\n H 0.0000000000 0.0000000000 0.0000000000\n H 0.0000000000 0.0000000000 0.7400000000\n'
OUTPUTS = {'crest.out': LOG, 'crest_best.xyz': FRAME, 'crest_conformers.xyz': FRAME, 'crest.energies': b'  1  0.000\n'}


def crest_profile(self, **kwargs):
    profile = lane.LaneAFixture.profile(self, **kwargs)
    profile = replace(profile, runtime_contents={**profile.runtime_contents, c._DEPLOYMENT_NAME: c._receipt_json(old.manifest())})
    return qualify_crest_profile(profile)


def qualify_crest_profile(profile,queue='simple'):
    q, _ = pilot.qualification_fixture(profile,queue=queue)
    resolved = execution.resolve_server_profile(profile)
    wrapper, probe = crest._wrapper_sources()
    q.update(schema=crest._Q_SCHEMA, contract_sha256=crest._CONTRACT_SHA256,
             profile_basis_sha256=c._publisher_profile_basis(resolved, crest=True))
    q['scope'].update(program_kind='crest', adapter_id='auto-g16-v31-crest', operations=['imtd-gc'])
    q['runtime']['crest'] = {'path': profile.platform_paths['crest_executable_path'], **pilot.digest(profile.runtime_contents['crest'])}
    q['runtime']['crest_loader_closure'] = loader_tests.qualification_closure(q['runtime']['crest'],q['hosts'][0]['host_key'])
    q['implementation'].update(wrapper_source=pilot.digest(wrapper.encode()), probe_source=pilot.digest(probe.encode()))
    for host in q['hosts']:
        loc = copy.deepcopy(host['locations'][2]);loc.update(role='crest', path=profile.platform_paths['crest_executable_path'])
        host['locations'].append(loc)
    q['evidence_manifest_sha256'] = sha256(c._receipt_json(controller._probe_index(q))).hexdigest()
    return replace(profile, runtime_contents={**profile.runtime_contents, crest._Q_NAME: pilot.seal(q)})


class CrestCompletionTests(lane.LaneAFixture):
    profile = crest_profile
    def resolved(self, **kwargs):
        return execution.resolve_server_profile(self.profile(**kwargs))

    def setUp(self):
        super().setUp()
        self.current_profile = self.profile()
        self.q = json.loads(self.current_profile.runtime_contents[crest._Q_NAME])['payload']
        self.spec = p._prepare_program_execution_spec(program_kind='crest', executable_path=lane.CREST_EXECUTABLE_PATH, executable_size_bytes=len(lane.CREST_EXECUTABLE_BYTES), executable_sha256=sha256(lane.CREST_EXECUTABLE_BYTES).hexdigest(), input_name='seed.xyz', input_bytes=lane.XYZ, program_data=self.crest_data(**crest._POLICY), resolved_profile=self.resolved(), completion_mode=c._MODE)
        self.material = c._prepare_publisher_pilot_rendering_material(self.current_profile, self.resolved())
        self.snapshot = self.snapshot_service.prepare(self.store, attempt_id='attempt-1', calculation_plan_id='plan-1', resource_spec_id='resource-1', program_execution_spec=self.spec, project_physical_binding=self.physical_binding(), resolved_resource_request=self.resources(), resolved_server_profile=self.resolved(), workspace_binding=self.workspace(), completion_rendering_material=self.material)
        root = self.root / 'transport';root.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(root / 'program.sqlite3', approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.driver = composition._Driver(OUTPUTS)
        self.input_bytes = {'seed.xyz': lane.XYZ}
        self.scheduler_bytes = {'crest.pbs': self.snapshot.scheduler_artifacts[0]['content_utf8'].encode()}

    execute = composition.ProgramCompositionTests.execute
    kwargs = old.CompletionTests.kwargs
    publish = old.CompletionTests.publish
    collect = old.CompletionTests.collect

    def test_native_completion_replay_and_readonly_proof(self):
        self.execute();self.publish();assessment = self.collect()
        self.assertEqual(assessment.data['diagnostic'], 'completed')
        self.assertEqual(self.store.attempt_state('attempt-1'), core.AttemptState.SUCCEEDED)
        before = self.store.observations_for_attempt('attempt-1')
        calls = len(self.driver.calls)
        with patch.object(self.store, 'append_observation', side_effect=AssertionError('read-only writes')), patch.object(self.store, 'append_result', side_effect=AssertionError('read-only writes')):
            proof, capture = runtime._read_program_receipt_success_authority(self.store, **self.kwargs())
        self.assertEqual(proof['capture_authority_id'], capture.capture_authority_id)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()), assessment)
        self.assertEqual(before, self.store.observations_for_attempt('attempt-1'))
        self.assertEqual(calls, len(self.driver.calls))
        with self.assertRaisesRegex(TransportBoundaryError, 'strict consumer'):
            runtime._assert_program_terminal_success_authority(self.store, **self.kwargs(), capture=capture)

    def test_native_crest_snapshot_restore_collect_and_zero_wire_replay(self):
        self._native_crest_snapshot_restore_collect_and_zero_wire_replay(recover=False)

    def test_native_crest_unknown_recovery_collect_and_zero_wire_replay(self):
        self._native_crest_snapshot_restore_collect_and_zero_wire_replay(recover=True)

    def _native_crest_snapshot_restore_collect_and_zero_wire_replay(self, *, recover):
        from contextlib import ExitStack
        from tests.v31.transport import test_publisher_collection_recovery as recovery
        from tests.v31.transport import test_rtwin_successor_bridge as bridge_tests
        from tests.v31.conformer import test_crest_receipt_handoff as seed_tests
        from auto_g16.conformer.models import _payload_sha256
        from auto_g16.transport import _driver, _bridge, _program_rtwin as rtwin
        from auto_g16.execution import _receipt_source as source_module
        from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal, _ProjectProvisioningService
        source=recovery._RecoveryFixture();source.xtb_data=lambda **changes:lane.LaneAFixture.xtb_data(solvent=None,**changes)
        source.setUp();self.addCleanup(source.doCleanups);source.resume()
        fixed_source=source_module._FixedReceiptSource(source.snapshot.program_execution_snapshot_id,pilot.file_binding(Path(source.database)),pilot.file_binding(Path(source.program_transport_store._path)),sha256(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(),len(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES))
        raw=source.current_profile
        profile=replace(raw,platform_paths={**raw.platform_paths,'crest_executable_path':'/opt/crest/3.0.2/bin/crest'},runtime_contents={**{k:v for k,v in raw.runtime_contents.items() if k!=c._Q_NAME},'crest':lane.CREST_EXECUTABLE_BYTES})
        profile=qualify_crest_profile(profile,queue='batch');target=execution.resolve_server_profile(profile)
        sampling=seed_tests.profile3()
        self.spec=p._prepare_program_execution_spec(program_kind='crest',executable_path=profile.platform_paths['crest_executable_path'],executable_size_bytes=len(lane.CREST_EXECUTABLE_BYTES),executable_sha256=sha256(lane.CREST_EXECUTABLE_BYTES).hexdigest(),input_name='seed.xyz',input_bytes=lane.XYZ,program_data=self.crest_data(**crest._POLICY,sampling_configuration_identity=_payload_sha256(sampling.crest_imtd_gc_profile)),resolved_profile=target,completion_mode=c._MODE)
        context=dict(core_store=source.store,xtb_program_execution_snapshot=source.snapshot,xtb_program_transport_store=source.program_transport_store,xtb_validation_driver=None,crest_program_execution_spec=self.spec,crest_exact_input_bytes=lane.XYZ,sampling_profile=sampling)
        with ExitStack() as stack:
            stack.enter_context(patch.object(source_module,'_FIXED_RECEIPT_SOURCE',fixed_source))
            handoff=handoffs._build_receipt_seed_handoff(**context)
            project=core.Project(project_id='crest-project');self.store.store_project(project)
            self.store.store_workflow_run(core.WorkflowRun(workflow_run_id='crest-run',project_id=project.project_id,workflow_name='crest'))
            self.store.store_task(core.Task(task_id='crest-task',workflow_run_id='crest-run',task_kind='successor-program'))
            plan=core.CalculationPlan(calculation_plan_id='crest-plan',task_id='crest-task',revision=1,intent={'crest_receipt_seed_handoff':{'handoff_authority_id':handoff.handoff_authority_id,'payload_sha256':handoff.payload_sha256}});self.store.store_calculation_plan(plan)
            resource=core.ResourceSpec(resource_spec_id='crest-resource',task_id='crest-task',resources={'tier':'simple'});self.store.store_resource_spec(resource)
            self.store.create_attempt(core.Attempt(attempt_id='crest-attempt',task_id='crest-task',ordinal=1))
            folder=self.root/'native-project';folder.mkdir()
            journal=_ProductionProvisioningJournal.create_new(folder/'project.sqlite3',approved_root=self.root if recover else folder);self.addCleanup(journal.close)
            if recover:
                self.program_transport_store=transport._ProgramTransportStore._create_completion_store(folder/'program.sqlite3',approved_root=self.root)
                self.addCleanup(self.program_transport_store.close)
            wire=bridge_tests._Wire();wire.outputs=dict(OUTPUTS);wire.project=bridge_tests.directory_token('/home/user100/SDL/crest-project')
            stack.enter_context(patch.object(_driver._SubprocessRTWinDriver,'_run',side_effect=wire.run))
            stack.enter_context(patch.object(_driver.subprocess,'Popen',side_effect=AssertionError('no live processes')))
            service=_ProjectProvisioningService._from_project_attestor(attestor=rtwin._RTWinProjectAttestor(current_profile=profile,target=target),target=target,journal=journal)
            binding=service.provision_remote_project(project=project,target=target,remote_project_dir='/home/user100/SDL/crest-project')
            factory=p._ProgramExecutionSnapshotService._for_production(project_provisioning=service,target=target)
            resources=execution.ResolvedResourceRequest(resource_spec=resource,cores=8,memory_mb=12288,walltime_seconds=3600,queue='batch')
            local=self.local_root/'crest-project';local.mkdir()
            workspace=execution.WorkspaceBinding(project=project,attempt_id='crest-attempt',local_approved_root=str(self.local_root),local_attempt_dir=str(local/'crest-attempt'),remote_approved_root=execution.LEGACY_REMOTE_ROOT,remote_attempt_dir='/home/user100/SDL/crest-project/crest-attempt',rtwin_approved_root=r'C:\RTWIN',rtwin_attempt_dir=r'C:\RTWIN\crest-project\crest-attempt')
            self.snapshot=factory.prepare(self.store,attempt_id='crest-attempt',calculation_plan_id='crest-plan',resource_spec_id='crest-resource',program_execution_spec=self.spec,project_physical_binding=binding,resolved_resource_request=resources,resolved_server_profile=target,workspace_binding=workspace,completion_rendering_material=c._prepare_publisher_pilot_rendering_material(profile,target))
            self.current_profile=profile;self.q=json.loads(profile.runtime_contents[crest._Q_NAME])['payload']
            self.scheduler_bytes={'crest.pbs':self.snapshot.scheduler_artifacts[0]['content_utf8'].encode()}
            installation,_,run,_=pilot._PilotFixture.install_fixture(self)
            fixed=handoffs._FixedReceiptSubmission(handoff,self.snapshot.program_execution_snapshot_id,binding.semantic_payload(),plan.calculation_plan_id,runtime.semantic_sha256(plan.intent),context)
            stack.enter_context(patch.object(rtwin,'_FIXED_PUBLISHER_INSTALLATION',installation))
            stack.enter_context(patch.object(controller,'_FIXED_PILOT_RUN',run))
            wire.calls.clear()
            closure=self.q['runtime']['crest_loader_closure']
            for missing_digest in (closure['evidence_manifest_sha256'],closure['loading_policy']['dynamic_loading_review_sha256']):
                incomplete=replace(installation,evidence=tuple(e for e in installation.evidence if e.sha256!=missing_digest))
                with patch.object(rtwin,'_FIXED_PUBLISHER_INSTALLATION',incomplete),patch.object(self.store,'record_submission_intent',side_effect=AssertionError('claim forbidden')) as claim:
                    with self.assertRaisesRegex(TransportBoundaryError,'fixed deployment ingestion rejected'):controller._run_first_publisher_pilot()
                claim.assert_not_called();self.assertEqual(wire.calls,[])
            for missing in (None,replace(fixed,plan_intent_sha256='0'*64)):
                with patch.object(handoffs,'_FIXED_RECEIPT_SUBMISSION',missing),patch.object(self.store,'record_submission_intent',side_effect=AssertionError('claim forbidden')) as claim:
                    with self.assertRaises(execution.ExecutionValueError):controller._run_first_publisher_pilot()
                claim.assert_not_called();self.assertEqual(wire.calls,[])
            stack.enter_context(patch.object(handoffs,'_FIXED_RECEIPT_SUBMISSION',fixed))
            if recover:wire.fail_operation='SUBMIT_QSUB_ONCE'
            result=controller._run_first_publisher_pilot();self.assertIs(result.claim,core.SubmissionIntentClaim.WINNER)
            if recover:
                from tests.v31.transport import test_exact_job_recovery as exact
                from auto_g16.transport._recovery_process import _RecoveryProcessOwner
                from auto_g16.transport._canonical import canonical_json_bytes
                self.assertEqual(self.store.attempt_state('crest-attempt'),core.AttemptState.UNKNOWN)
                original_outcome=tuple(self.store._connection.execute("SELECT * FROM submission_outcomes WHERE attempt_id='crest-attempt'").fetchone())
                wire.fail_operation=None
                self.original=installation;self.original_run=run;self.journal=journal
                self.resolved=lambda:target
                self.recovery_root=self.root/'exact-recovery';self.recovery_root.mkdir()
                self.write=recovery._RecoveryFixture.write.__get__(self)
                self.run,self.installation,self.document=recovery._RecoveryFixture.install_recovery(self)
                receipts=self.store.observations_for_attempt('crest-attempt')
                def change(document):
                    document['schema']=exact.proof.SCHEMA
                    document['scope'].update(action='reconcile-exact-job-and-collect',maximum_reconciliation_epochs=1)
                    document['scope']['operations']=['RECONCILE_SUBMISSION',*rtwin._COLLECTION_OPERATIONS]
                    raw=exact.proof.source_bytes()
                    document['reconciliation']={'submit_receipt_id':receipts[-1].observation_id,'job_owner':'user100@localhost','server':'server','host':exact.HOST,'probe_source':{'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)},'prior_recovery_authority':None}
                self.installation=recovery._RecoveryFixture.changed_installation(self,change)
                change(self.document)
                expected=exact.proof.expected_evidence(self.snapshot,receipts,self.document)
                def peer(scope,invocation):
                    rtwin._prepare_program_invocation(scope,invocation)
                    return exact.framed(exact.result(expected)),b'',0,'completed',True,True
                stack.enter_context(patch.object(_RecoveryProcessOwner,'_run',side_effect=peer))
                stack.enter_context(patch.object(rtwin,'_FIXED_COLLECTION_INSTALLATION',self.installation))
                stack.enter_context(patch.object(controller,'_FIXED_COLLECTION_RUN',self.run))
                self.assertEqual(controller._reconcile_fixed_publisher_submission()['outcome'],'SUCCEEDED')
            submitted=self.snapshot;calls=len(wire.calls)
            self.snapshot=factory.restore_for_collection(self.store,reviewed_semantics=submitted._approval_semantics())
            self.assertEqual(self.snapshot,submitted);self.assertEqual(calls,len(wire.calls))
            wire.scheduler=(153,b'',b'qstat: Unknown Job Id Error 123.server\n')
            receipt=dict(c._receipt_binding(self.snapshot,'123.server',bridge_tests.directory_token(self.snapshot.workspace_binding.remote_attempt_dir)))
            receipt.update(termination={'kind':'exited','returncode':0,'signal':None},finished_at='2026-09-15T00:10:00.000000Z',outputs=[{**{k:d[k] for k in ('logical_role','portable_name','format')},'presence':'present','size_bytes':len(wire.outputs[d['portable_name']]),'sha256':sha256(wire.outputs[d['portable_name']]).hexdigest()} for d in self.spec.required_outputs])
            wire.outputs['v31-completion.json']=c._receipt_json(receipt)
            collect=controller._resume_fixed_publisher_collection if recover else controller._collect_first_publisher_pilot
            assessment=collect();self.assertEqual(assessment.data['verdict'],'SUCCEEDED')
            calls=len(wire.calls);self.assertEqual(collect(),assessment);self.assertEqual(calls,len(wire.calls))
            if recover:self.assertEqual(tuple(self.store._connection.execute("SELECT * FROM submission_outcomes WHERE attempt_id='crest-attempt'").fetchone()),original_outcome)

    def test_nonzero_is_native_failed(self):
        self.execute();self.publish(code=7)
        self.assertEqual(self.collect().data['diagnostic'], 'program-nonzero')

    def test_missing_output_is_native_failed(self):
        self.execute();del self.driver.outputs['crest_best.xyz'];self.publish()
        self.assertEqual(self.collect().data['diagnostic'], 'output-incomplete')

    def test_missing_phase_is_native_failed(self):
        self.execute();self.driver.outputs['crest.out'] = b'CREST terminated normally.\n';self.publish()
        self.assertEqual(self.collect().data['diagnostic'], 'output-invalid')

    def test_tuple_and_order_are_explicit(self):
        self.assertEqual(p._PROGRAM_EFFECT_RECEIPT_TYPE, transport._RECEIPT_TYPE)
        self.assertEqual(self.spec.adapter_contract_version, 3)
        argv = self.spec.invocation['argv'];i = argv.index('-cross')
        self.assertEqual(argv[i:i+2], ('-cross', '-nozs'))
        self.assertEqual(tuple(x['portable_name'] for x in self.spec.required_outputs), crest._NAMES)
        self.assertTrue(self.snapshot.scheduler_artifacts[0]['content_utf8'].startswith('#!/bin/bash\n# auto-g16-v31-scheduler/4\n'))
        with self.assertRaises(Exception):
            c._validate_material({**self.material, 'schema': c._PILOT_MATERIAL_SCHEMA}, self.resolved())
        with self.assertRaises(Exception):
            self.publish(schema=c._SCHEMA)
            c._decode_receipt(self.driver.outputs['v31-completion.json'])

    def test_wrong_qualification_program_rejects(self):
        raw = self.current_profile.runtime_contents[crest._Q_NAME]
        q = json.loads(raw)['payload'];q['scope']['program_kind'] = 'xtb'
        with self.assertRaises(Exception): c._decode_publisher_qualification(pilot.seal(q))

    def test_loader_root_mismatch_rejects_before_trace(self):
        q=copy.deepcopy(self.q);q['runtime']['crest']['path']='/opt/wrong/crest'
        with self.assertRaisesRegex(ValueError,'loader root'):c._decode_publisher_qualification(pilot.seal(q))
        ns=self.namespace();runtime_data=copy.deepcopy(self.q['runtime']);calls=[]
        ns.update(system_bytes=lambda path,cap:b'machine' if path=='/etc/machine-id' else b'12345678-1234-1234-1234-123456789abc',host_mounts=lambda:[],host_location=lambda *args:{},file_identity=lambda *args:None,
                  sys=SimpleNamespace(platform='linux'),os=SimpleNamespace(uname=lambda:SimpleNamespace(release='kernel',machine='x86_64'),stat=lambda *args:SimpleNamespace(st_dev=1,st_ino=2)),cl_guard=lambda *args:calls.append(True))
        runtime_data['crest_loader_closure']['host_key']=ns['semantic']({'machine_id_sha256':sha256(b'machine').hexdigest()})
        runtime_data['crest']['path']='/opt/wrong/crest'
        with self.assertRaisesRegex(ValueError,'crest-loader-root'):ns['observe_publisher_host'](runtime_data,'/root','/data')
        self.assertEqual(calls,[])

    def namespace(self):
        namespace = {'__name__': 'inert_crest_fixture'}
        exec(compile(crest._wrapper_sources()[0], 'crest-source', 'exec'), namespace)
        return namespace

    def test_execute_once_requires_handoff_before_claim_after_runtime_drift(self):
        prepare = runtime._prepare_program_execution
        def drift(*args, **kwargs):
            result = prepare(*args, **kwargs)
            self.driver.runtime_qualification = {**self.driver.runtime_qualification, 'bootstrap_protocol':'not-synthetic'}
            return result
        port = runtime._ProgramExecutionPort(snapshot=self.snapshot,program_transport_store=self.program_transport_store,driver=self.driver)
        with patch.object(runtime,'_prepare_program_execution',side_effect=drift), \
             patch.object(handoffs,'_FIXED_RECEIPT_SUBMISSION',None), \
             patch.object(self.store,'record_submission_intent',side_effect=AssertionError('claim forbidden')) as claim:
            with self.assertRaisesRegex(execution.ExecutionValueError,'NOT_ACQUIRED'):
                execution.execute_once(self.store,snapshot=self.snapshot,current_profile=self.current_profile,prepared_input_bytes=lane.XYZ,pbs_template_bytes=self.scheduler_bytes['crest.pbs'],confirmed_execution_snapshot_id=self.snapshot.program_execution_snapshot_id,port=port)
        claim.assert_not_called()
        self.assertEqual(self.driver.calls,[])
        self.assertEqual(self.store.attempt_state('attempt-1'),core.AttemptState.PLANNED)

    test_crest_wrapper_all_host_identities = pilot.PublisherWrapperTests.test_host_guard_match_and_each_identity_mismatch

    def test_crest_wrapper_publication_and_lifecycle_drift(self):
        for phase in ('initial', 'before-child', 'before-link', 'success'):
            with self.subTest(phase=phase):
                workspace = self.root / ('crest-'+phase);workspace.mkdir()
                config = json.loads(c._receipt_json(old._supplement_wrapper_config(self, workspace)))
                (workspace/'input.xyz').rename(workspace/'seed.xyz')
                ns = self.namespace();calls=[];launches=[]
                def guard(config):
                    calls.append(True)
                    if len(calls) == {'initial':1,'before-child':2,'before-link':3}.get(phase):
                        raise ValueError('injected host drift')
                    return {'host':'inert'}
                def launch(*args, **kwargs):
                    launches.append(True)
                    self.assertFalse(kwargs['shell'])
                    os.write(kwargs['stdout'], LOG)
                    for name, raw in OUTPUTS.items():
                        if name != 'crest.out': (workspace/name).write_bytes(raw)
                    return SimpleNamespace(pid=123, returncode=None)
                ns.update(publisher_host_guard=guard, subreaper=lambda:None, wait_all=lambda *args:0,
                          subprocess=SimpleNamespace(Popen=launch, DEVNULL=-3))
                cwd=Path.cwd()
                try:
                    with patch.object(sys,'executable',str(Path(sys.executable).resolve())), patch.dict(os.environ,{'PBS_JOBID':'123.server'}):
                        if phase=='success': self.assertEqual(ns['run'](config),0)
                        else:
                            with self.assertRaises(ValueError): ns['run'](config)
                finally: os.chdir(cwd)
                self.assertEqual(len(launches),int(phase in {'before-link','success'}))
                self.assertEqual((workspace/'v31-completion.json').exists(),phase=='success')
                if phase=='success':
                    receipt = c._decode_receipt((workspace/'v31-completion.json').read_bytes())
                    self.assertEqual(receipt['schema'],crest._SCHEMA)
                    self.assertEqual(receipt['operation'],'imtd-gc')
                    self.assertEqual({r['portable_name'] for r in receipt['outputs']},set(crest._NAMES))


class CrestOutputTests(unittest.TestCase):
    def test_valid_single_and_multiple_cycles(self):
        self.assertIsNone(crest._output_closure(lane.XYZ, OUTPUTS))
        log = LOG.replace(b'Final Ensemble', b'Meta-Dynamics Iteration 1\nMeta-Dynamics Iteration 2\nMTD Simulations done\nFinal Ensemble')
        self.assertIsNone(crest._output_closure(lane.XYZ, {**OUTPUTS, 'crest.out': log}))

    def test_malformed_phase_order_and_duplicates(self):
        for log in [LOG+LOG, LOG.replace(b'MTD Simulations done\n', b''), LOG.replace(b'Meta-Dynamics Iteration 1', b'MTD Simulations done'), LOG.replace(b'CREST iMTD-GC SAMPLING', b'quoted CREST iMTD-GC SAMPLING')]:
            with self.subTest(log=log): self.assertEqual(crest._output_closure(lane.XYZ, {**OUTPUTS, 'crest.out': log}), 'output-invalid')

    def test_required_empty_atom_and_best_corruption(self):
        for name in crest._NAMES:
            with self.subTest(missing=name): self.assertEqual(crest._output_closure(lane.XYZ, {**OUTPUTS, name: None}), 'output-incomplete')
            with self.subTest(empty=name): self.assertEqual(crest._output_closure(lane.XYZ, {**OUTPUTS, name: b''}), 'output-invalid')
        for bad in [FRAME.replace(b' H ', b' C ', 1), FRAME+b'junk\n', FRAME.replace(b'0.7400000000', b'NaN'), FRAME.replace(b'-1.00000000', b'-1.1'), FRAME.rstrip(b'\n'), FRAME.replace(b'0.7400000000', b'7.4e-1')]:
            with self.subTest(frame=bad): self.assertEqual(crest._output_closure(lane.XYZ, {**OUTPUTS, 'crest_conformers.xyz': bad}), 'output-invalid')

    def test_relative_energies_precision_index_count(self):
        second = FRAME.replace(b'-1.00000000', b'-0.99900000')
        good = {**OUTPUTS, 'crest_conformers.xyz': FRAME+second, 'crest.energies': b' 1 0.000\n 2 0.628\n'}
        self.assertIsNone(crest._output_closure(lane.XYZ, good))
        for raw in [b'1 0.000\n2 0.626\n', b'1 0.000\n3 0.628\n', b'1 0.000\n', b'1 0.000\n2 NaN\n', b'1 0.000\n2 -0.628\n']:
            with self.subTest(raw=raw): self.assertEqual(crest._output_closure(lane.XYZ, {**good, 'crest.energies': raw}), 'output-invalid')
