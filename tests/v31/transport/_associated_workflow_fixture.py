"""Production owners with an inert wire peer; never launches SSH/PBS/Gaussian."""
from contextlib import ExitStack
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json

from auto_g16 import approval, core, execution
from auto_g16.execution import program, program_runtime as runtime, _program_completion as completion
from auto_g16.execution import _project_association_source as owner
from auto_g16.execution._receipt_source import _FixedReceiptSource, _gaussian_receipt_sources
from auto_g16.execution.project_provisioning import _ProjectProvisioningService
from auto_g16.transport import _program_rtwin as rtwin, _driver, _bridge, program as transport
from tests.v31.transport.test_project_profile_association import pin
from tests.v31.transport import test_rtwin_successor_bridge as wire_fixture
from tests.v31.conformer import test_successor_freq as science


def prepare(test, stage, binding, opt=None):
    from auto_g16.conformer._successor_freq import optimization_link
    f = test.o if stage == 'opt' else test.f
    current = test.old if stage == 'opt' else test.current
    target = execution.resolve_server_profile(current)
    attempt = 'attempt-1' if stage == 'opt' else 'a708332d-2e3b-4e5d-8749-bc67e1da0002'
    plan, resource = 'plan-1', 'resource-1'
    if stage == 'freq':
        f.store.store_task(core.Task(task_id='freq-task', workflow_run_id='run-1', task_kind='successor-program'))
        plan, resource = 'freq-plan', 'freq-resource'
        f.store.store_calculation_plan(core.CalculationPlan(calculation_plan_id=plan, task_id='freq-task', revision=1,
            intent={'program':'gaussian', 'optimization_source':optimization_link(opt),
                    'method_binding':{k:v for k,v in opt['method_binding'].items() if k != 'route_contract_version'}}))
        f.store.store_resource_spec(core.ResourceSpec(resource_spec_id=resource, task_id='freq-task', resources={'tier':'simple'}))
        f.store.create_attempt(core.Attempt(attempt_id=attempt, task_id='freq-task', ordinal=1))
    route = science.OPT_ROUTE if stage == 'opt' else science.ROUTE
    raw = ('%chk=gaussian.chk\n%mem=12GB\n%nprocshared=8\n' + route + '\n\nsynthetic\n\n0 1\n' +
        '\n'.join(('C' if i < 4 else 'H') + ' ' + ' '.join(map(str,p)) for i,p in enumerate(science.COORDS)) + '\n\n').encode()
    executable = (test.rows[4]).invocation['executable_identity']
    spec = program._prepare_program_execution_spec(program_kind='gaussian', executable_path=executable['absolute_path'],
        executable_size_bytes=executable['size_bytes'], executable_sha256=executable['sha256'], input_name='flow.gjf', input_bytes=raw,
        program_data={'stage':stage}, resolved_profile=target, completion_mode=completion._MODE, gaussian_headroom_mib=4096,
        startup_mode='short-entry-opt-resources-v3' if stage == 'opt' else 'short-entry-freq-resources-v4')
    provision = _ProjectProvisioningService._from_project_attestor(
        attestor=rtwin._RTWinProjectAttestor(current_profile=current,target=target), target=target, journal=test.journal)
    service = program._ProgramExecutionSnapshotService._for_production(project_provisioning=provision,target=target)
    workspace = execution.WorkspaceBinding(project=f.store.load_project('project-1'), attempt_id=attempt,
        local_approved_root=str(f.local_root), local_attempt_dir=str(f.local_project/attempt), rtwin_approved_root=r'C:\RTWIN',
        rtwin_attempt_dir='C:\\RTWIN\\project-1\\'+attempt, remote_approved_root=execution.LEGACY_REMOTE_ROOT,
        remote_attempt_dir=f.remote_project_dir+'/'+attempt)
    snapshot = service.prepare(f.store,attempt_id=attempt,calculation_plan_id=plan,resource_spec_id=resource,
        program_execution_spec=spec,project_physical_binding=binding,
        resolved_resource_request=execution.ResolvedResourceRequest(resource_spec=f.store.load_resource_spec(resource),cores=8,memory_mb=16384,walltime_seconds=3600,queue='batch'),
        resolved_server_profile=target,workspace_binding=workspace,
        completion_rendering_material=completion._prepare_publisher_pilot_rendering_material(current,target))
    return f,current,target,snapshot,raw


def execute_collect(test, prepared, stage, association):
    from scripts import run_v31_publisher_pilot as controller
    f,current,target,snapshot,raw = prepared
    qname = 'v31-gaussian-publisher-qualification-v7.json' if stage == 'opt' else 'v31-gaussian-publisher-qualification-v8.json'
    # Regenerate only the fixture evidence catalogue used by installed_case.
    from tests.v31.transport.test_publisher_pilot_orchestration import qualification_fixture
    # The exact Q's catalogue was retained by the original qualified fixture.
    rows = test.old_rows if stage == 'opt' else test.rows
    installation,_ = f.installed_case(current,target,rows[2],rows[3],snapshot)
    root=f.root/'associated-results';root.mkdir()
    native=transport._ProgramTransportStore._create_completion_store(root/'transport.sqlite3',approved_root=root)
    test.addCleanup(native.close)
    peer=wire_fixture._Wire();peer.outputs={'gaussian.log':science.log_bytes(freq=stage=='freq')}
    peer.scheduler=(153,b'',b'qstat: Unknown Job Id 123.server\n')
    calls=[]
    def wire(scope, invocation):
        _,frame=rtwin._prepare_program_invocation(scope,invocation)
        request=_bridge._decode_frame(frame,cap=invocation.operation.stdin_cap,field='associated inert wire')
        calls.append(request['operation'])
        if request['operation']=='SUBMIT_QSUB_ONCE':
            test.assertEqual(len(request['payload']['staged']),5)
            test.assertEqual(request['payload']['launch_context']['project_physical_binding_id'],snapshot.project_physical_binding_id)
            return _bridge._encode_frame({'protocol':_bridge._PROGRAM_BOOTSTRAP_PROTOCOL,'operation':'SUBMIT_QSUB_ONCE','status':'ok','result':{'job_id':'123.server'}}),b'',0,'completed',True,True
        return peer.run(scope,invocation)
    meaning={'fixture':'associated Opt/Freq offline'}
    scientific=approval.ScientificApproval.for_plan(f.store,f.store.load_calculation_plan(snapshot.calculation_plan_id),displayed_semantic_meaning=meaning,reviewer_id='fixture',reviewer_evidence={})
    batch=approval.BatchSubmitApproval.for_existing_attempts(f.store,[(snapshot.attempt_id,scientific)],reviewer_id='fixture',reviewer_evidence={})
    confirmation=approval.ExactOperationalConfirmation.for_snapshot(f.store,snapshot,confirmer_id='fixture',confirmer_evidence={})
    run=SimpleNamespace(snapshot=snapshot,displayed_semantic_meaning=meaning,scientific_approval_id=scientific.scientific_approval_id,
        batch_submit_approval_id=batch.batch_submit_approval_id,operational_confirmation_id=confirmation.operational_confirmation_id)
    deployment=SimpleNamespace(basis={'pilot_live_gate_evidence_sha256':'2'*64})
    def approvals():
        with patch.object(controller,'_load_current_authorities',return_value=({'core':f.store},scientific,batch,confirmation)):
            return controller._current_gaussian_handoff_approvals(run,deployment)
    with patch.object(rtwin,'_FIXED_PUBLISHER_INSTALLATION',installation),patch.object(rtwin,'_publisher_window',return_value=None),patch.object(_driver._SubprocessRTWinDriver,'_run',side_effect=wire):
        driver=rtwin._RTWinProgramEffectDriver(snapshot=snapshot,current_profile=current,program_transport_store=native)
        try:
            scheduler={a['portable_name']:a['content_utf8'].encode() for a in snapshot.scheduler_artifacts}
            token=rtwin._GAUSSIAN_LAUNCH_OWNER.set((snapshot,approvals))
            try:
                runtime._prepare_program_execution(f.store,snapshot=snapshot,program_transport_store=native,input_bytes={'flow.gjf':raw},scheduler_artifact_bytes=scheduler,driver=driver)
                result=execution.execute_once(f.store,snapshot=snapshot,current_profile=current,confirmed_execution_snapshot_id=snapshot.program_execution_snapshot_id,
                    prepared_input_bytes=raw,pbs_template_bytes=next(iter(scheduler.values())),port=runtime._ProgramExecutionPort(snapshot=snapshot,program_transport_store=native,driver=driver))
                test.assertEqual(result.attempt_state,core.AttemptState.SUBMITTED)
            finally:rtwin._GAUSSIAN_LAUNCH_OWNER.reset(token)
            receipt=dict(completion._receipt_binding(snapshot,'123.server',wire_fixture.directory_token(snapshot.workspace_binding.remote_attempt_dir)))
            receipt.update(termination={'kind':'exited','returncode':0,'signal':None},finished_at='2026-09-30T00:00:00.000000Z',outputs=[])
            for item in (*snapshot.program_execution_spec.required_outputs,*snapshot.program_execution_spec.optional_outputs):
                data=peer.outputs.get(item['portable_name'])
                receipt['outputs'].append({**{k:item[k] for k in ('logical_role','portable_name','format')},'presence':'absent' if data is None else 'present',
                    'sha256':None if data is None else sha256(data).hexdigest(),'size_bytes':None if data is None else len(data)})
            peer.outputs['v31-completion.json']=completion._receipt_json(receipt)
            assessment=runtime._collect_program_completion(f.store,snapshot=snapshot,program_transport_store=native,driver=driver,input_bytes={'flow.gjf':raw})
            test.assertEqual(assessment.data['diagnostic'],'completed')
            test.assertEqual(calls.count('SUBMIT_QSUB_ONCE'),1)
        finally:driver.close()
    from auto_g16.transport import _gaussian_resource_submit, _gaussian_freq_submit
    bootstrap=(_gaussian_resource_submit if stage=='opt' else _gaussian_freq_submit).source_bytes()
    fixed=_FixedReceiptSource(snapshot.program_execution_snapshot_id,pin(f.store._connection.execute('PRAGMA database_list').fetchone()[2]),
        pin(native._path),sha256(bootstrap).hexdigest(),len(bootstrap),project_association=association)
    return dict(source_store=f.store,snapshot=snapshot,transport_store=native,parser_version='1.2.0'),fixed,root


def run(test):
    from auto_g16.conformer._successor_opt import read_opt_authority,refine_opt_ensemble,import_opt_result_revision
    from auto_g16.conformer._successor_freq import refine_freq_ensemble,import_freq_result_revision,read_two_stage_authority
    from auto_g16.conformer.service import create_sampling_profile,build_conformer_ensemble
    from auto_g16.result._successor import _plain
    from inspect import signature
    c=science.conformercoretests_fixture.ConformerCoreTests();species=c.species_binding();order=species['atom_order']+['h%d'%i for i in range(10)]
    species.update(atom_order=order,atom_mapping={a:'source-'+a for a in order},elements=['C']*4+['H']*10,explicit_hydrogens=[False]*4+[True]*10,
        fragment_ids=['fragment_1']*14,bonds=[[order[a],order[b],1.] for a,b in ((0,1),(1,2),(2,3),*((p,4+i) for i,p in enumerate((0,0,0,1,1,2,2,3,3,3))))])
    values=c.profile()._identity_payload();args={k:_plain(values[k]) for k in signature(create_sampling_profile).parameters if k in values};args['species_binding']=species
    args['geometry_legality_policy']['reference_bond_maximum_distances']=[{'atom_ids':b[:2],'maximum':2.,'unit':'angstrom'} for b in species['bonds']]
    args['rmsd_policy']['symmetry_mapping']=list(range(14));profile=create_sampling_profile(**args)
    ensemble=build_conformer_ensemble(project_id='sampling-project',calculation_plan_id='sampling-plan',calculation_plan_revision=1,profile=profile,
        observations=[c.observation(profile,'anti',coordinates=[list(p) for p in science.COORDS])])
    binding,association=test.issue()
    opt,ofixed,oroot=execute_collect(test,prepare(test,'opt',test.original),'opt',None)
    def import_revision(data,fixed,root,importer):
        initial=root/'initial.sqlite3';initial.write_bytes(data['source_store']._connection.serialize())
        output=root/'parsed.sqlite3'
        importer(**data,destination_path=initial,output_path=output,approved_root=root)
        test.assertEqual(initial.read_bytes(),data['source_store']._connection.serialize())
        destination=core.SQLiteRuntimeStore._open_readonly_existing(output);test.addCleanup(destination.close)
        data['destination']=destination
        snap=root/'snapshot.json';snap.write_bytes(owner._raw(data['snapshot']._approval_semantics()))
        original=asdict(fixed)
        if fixed.project_association is None:original.pop('project_association')
        return dict(member_id='anti',original=original,snapshot=asdict(pin(snap)),transport_root=str(root),revision=asdict(pin(output)),parser_version='1.2.0')
    with _gaussian_receipt_sources((ofixed,)):
        orow=import_revision(opt,ofixed,oroot,import_opt_result_revision)
        authority=read_opt_authority(ensemble,'anti',**opt)
        refined=refine_opt_ensemble(ensemble,profile,inputs=[dict(member_id='anti',**opt)])
    freq,ffixed,froot=execute_collect(test,prepare(test,'freq',binding,authority),'freq',association)
    with _gaussian_receipt_sources((ofixed,ffixed)):
        frow=import_revision(freq,ffixed,froot,import_freq_result_revision)
        test.assertEqual(read_two_stage_authority(ensemble,'anti',optimization=opt,frequency=freq)['assessment']['classification'],'VALIDATED_TWO_STAGE_MINIMUM')
        final=refine_freq_ensemble(refined,profile,optimization_ensemble=ensemble,inputs=[dict(member_id='anti',optimization=opt,frequency=freq)])
    material=froot/'material.json';material.write_bytes(owner._raw(dict(profile=profile._identity_payload(),original=ensemble._identity_payload(),opt_refined=refined._identity_payload(),history=[],prior=refined._identity_payload(),refined=final._identity_payload())))
    registry={'schema':'auto-g16-freq-readout-registration/2','material':asdict(pin(material)),'optimization_sources':[orow],'frequency_sources':[frow]}
    path=froot/'registry.json';path.write_bytes(owner._raw(registry))
    from auto_g16.conformer.frequency_readonly import load_freq_readout
    with patch.object(_driver,'_resolve_closed_profile_authority',side_effect=AssertionError('detached current driver')):
        reader=load_freq_readout(path.read_bytes(),sha256(path.read_bytes()).hexdigest())
        dto=reader.read(freq['destination'],freq['snapshot'].attempt_id)
        test.assertEqual(dto['assessment']['classification'],'VALIDATED_TWO_STAGE_MINIMUM')
        broken=json.loads(path.read_bytes());broken['frequency_sources'][0]['original']['project_association']['proof']['sha256']='0'*64
        raw=owner._raw(broken)
        bad=load_freq_readout(raw,sha256(raw).hexdigest())
        with test.assertRaises(Exception):bad.read(freq['destination'],freq['snapshot'].attempt_id)
    return freq['snapshot'],path


def read_registry(path):
    """Fresh-process product query; current execution authority must be unavailable."""
    from auto_g16.conformer.frequency_readonly import load_freq_readout
    from auto_g16.query import NativeSource,NativeQueryService
    raw=Path(path).read_bytes();reader=load_freq_readout(raw,sha256(raw).hexdigest());selected=reader.frequency_sources[0]
    with patch.object(_driver,'_resolve_closed_profile_authority',side_effect=AssertionError('historical query consulted current driver')):
        return NativeQueryService((NativeSource(source_id='freq',database=Path(selected.revision.path),snapshots=(selected.snapshot,),freq_readout=reader),)).get_attempt('freq',selected.snapshot.attempt_id)
