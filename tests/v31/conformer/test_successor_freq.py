"""Inert two-stage workflow and adversarial fact association; no live backend."""
from dataclasses import replace
import copy
import unittest
from unittest.mock import patch
from auto_g16 import core,execution
from auto_g16.conformer._successor_opt import ROUTE as OPT_ROUTE,read_opt_authority,refine_opt_ensemble
from auto_g16.conformer._successor_freq import optimization_link,read_two_stage_authority,refine_freq_ensemble
from auto_g16.execution._gaussian_freq_resources import ROUTE
from auto_g16.execution._gaussian_result_source import gaussian_result_source,gaussian_freq_result_source
from auto_g16.execution import program_runtime as runtime
from auto_g16.result._successor import parse_source,parse_freq_source,append_pair
from auto_g16.result.gaussian_job import _NativeGaussianJobParser
from auto_g16.scientific_validation._successor_freq import assess_frequency
from auto_g16.scientific_validation.models import ScientificValidationError
from auto_g16.conformer.refinement_authority import RefinementAuthorityError
from auto_g16.conformer.service import build_conformer_ensemble,create_sampling_profile
from auto_g16.transport.program import _ProgramTransportStore
import tests.v31.transport.test_gaussian_successor as gaussiansuccessortests_fixture
from tests.v31.transport.test_program_composition import _Driver
import tests.v31.transport.test_program_completion as completiontests_fixture
import tests.v31.conformer.test_core as conformercoretests_fixture
from tests.v3.result.test_gaussian_job import LINES,envelope

# Deliberately synthetic mapped n-butane, not a calculated geometry.
COORDS=((0.,0.,0.),(1.5,0.,0.),(2.2,1.3,0.),(3.7,1.3,0.),
        (-.4,.8,.6),(-.4,-.8,.6),(-.4,0.,-1.),(1.8,-.7,.8),(1.8,-.7,-.8),
        (1.9,2.,.8),(1.9,2.,-.8),(4.1,.5,.6),(4.1,2.1,.6),(4.1,1.3,-1.))


def geometry_rows(coords=COORDS):
    return (b' Input orientation:',*LINES[28:32],*((' %d %d 0 '%(i,6 if i<=4 else 1)+' '.join(map(str,p))).encode() for i,p in enumerate(coords,1)),LINES[34])


def log_bytes(*,freq=False,values=None,coords=COORDS,extra=()):
    rows=[b' Entering Gaussian System, Link 0=/opt/gaussian/g16',*LINES[5:9],
          b' Standard basis: def2SVP (5D, 7F)',b' SCF Done: E(RwB97XD) = -158.000000 A.U. after 10 cycles',*geometry_rows(coords)]
    if freq:
        values=tuple(range(100,136)) if values is None else values
        for i in range(0,len(values),3):
            group=values[i:i+3]
            if i==0:rows.extend(LINES[17:21])
            rows.extend([(' '+ ' '.join(str(n) for n in range(i+1,i+len(group)+1))).encode(),b' A1 A1 A1',
                         (' Frequencies -- '+' '.join(map(str,group))).encode(),*LINES[24:27]])
    else:rows.extend(LINES[10:17])
    rows.extend(extra);rows.append(LINES[36])
    return b'\n'.join(rows)+b'\n'


class FrequencyFactsTests(unittest.TestCase):
    def parsed(self,**kwargs):
        raw=log_bytes(freq=True,**kwargs);env,files=envelope(raw)
        parsed=_NativeGaussianJobParser().parse(env,files)
        self.assertEqual(parsed.parse_status.value,'parsed',parsed.diagnostics)
        return env,parsed
    def expected(self):
        return self.parsed()[1].facts['geometry_blocks'][0]
    def test_complete_zero_negative_and_counts(self):
        for values,kind in ((tuple(range(36)),'VALIDATED_TWO_STAGE_MINIMUM'),((-0.001,*range(1,36)),'NOT_MINIMUM'),
                            (tuple(range(33)),'INCOMPLETE'),(tuple(range(39)),'UNSUPPORTED'),((),'INCOMPLETE')):
            with self.subTest(kind=kind):
                env,p=self.parsed(values=values)
                selected,a=assess_frequency(env,p,self.expected())
                self.assertEqual(a['classification'],kind)
    def test_all_later_input_blocks_must_match(self):
        env,p=self.parsed(extra=geometry_rows())
        self.assertEqual(assess_frequency(env,p,self.expected())[1]['classification'],'VALIDATED_TWO_STAGE_MINIMUM')
        coords=list(COORDS);coords[0]=(.000001,0.,0.)
        env,p=self.parsed(extra=geometry_rows(coords))
        with self.assertRaisesRegex(ScientificValidationError,'conflicts'):assess_frequency(env,p,self.expected())
    def test_missing_input_geometry_never_uses_standard(self):
        raw=log_bytes(freq=True).replace(b'Input orientation',b'Standard orientation');env,files=envelope(raw)
        p=_NativeGaussianJobParser().parse(env,files)
        self.assertEqual(assess_frequency(env,p,self.expected())[1]['reason_code'],'missing-frequency-geometry')
    def test_source_and_span_forgery_rejected(self):
        env,p=self.parsed()
        from auto_g16.result._successor import _plain
        for which in ('source','span'):
            facts=_plain(p.facts)
            if which=='source':facts['source_artifact']['sha256']='0'*64
            else:facts['geometry_blocks'][0]['source_span']['end']=facts['frequency_blocks'][0]['source_span']['end']
            # Fact-only owner is also defensive on detached mapping input.
            from types import SimpleNamespace
            value=SimpleNamespace(**{k:getattr(p,k) for k in ('parser_name','parser_version','result_kind','parse_status')},facts=facts)
            with self.assertRaises(ScientificValidationError):assess_frequency(env,value,self.expected())


class FrequencyWorkflowTests(unittest.TestCase):
    def setUp(self):
        c=conformercoretests_fixture.ConformerCoreTests();species=c.species_binding()
        order=species['atom_order']+['h%d'%i for i in range(10)]
        species.update(atom_order=order,atom_mapping={a:'source-'+a for a in order},elements=['C']*4+['H']*10,
                       explicit_hydrogens=[False]*4+[True]*10,fragment_ids=['fragment_1']*14,
                       bonds=[[order[a],order[b],1.] for a,b in ((0,1),(1,2),(2,3),*( (parent,4+i) for i,parent in enumerate((0,0,0,1,1,2,2,3,3,3))))])
        # Construct the same closed policy with the complete atom bijection.
        base=c.profile()
        from auto_g16.result._successor import _plain
        from inspect import signature
        args={k:_plain(base._identity_payload()[k]) for k in signature(create_sampling_profile).parameters if k in base._identity_payload()}
        args['species_binding']=species
        args['geometry_legality_policy']['reference_bond_maximum_distances']=[{'atom_ids':b[:2],'maximum':2.,'unit':'angstrom'} for b in species['bonds']]
        args['rmsd_policy']['symmetry_mapping']=list(range(14))
        self.profile=create_sampling_profile(**args)
        self.ensemble=build_conformer_ensemble(project_id='sampling-project',calculation_plan_id='sampling-plan',calculation_plan_revision=1,
            profile=self.profile,observations=[c.observation(self.profile,'anti',coordinates=[list(p) for p in COORDS])]+
                ([c.observation(self.profile,'gauche',member_index=1,coordinates=[list(p) for p in GAUCHE])] if getattr(self,'two_members',False) else []))
        self.opt=self.case('opt','attempt-1')
        self.authority=read_opt_authority(self.ensemble,'anti',**self.opt)
        self.freq=self.case('freq','attempt-2',opt=self.authority)
        self.refined=refine_opt_ensemble(self.ensemble,self.profile,inputs=[dict(member_id='anti',**self.opt)])
    def case(self,stage,attempt,opt=None,values=None,coords=COORDS):
        f=gaussiansuccessortests_fixture.GaussianSuccessorTests();f.setUp();self.addCleanup(f.doCleanups)
        plan='plan-1';rs='resource-1'
        if attempt!='attempt-1':
            f.store.store_task(core.Task(task_id='task-freq',workflow_run_id='run-1',task_kind='successor-program'))
            f.store.store_calculation_plan(core.CalculationPlan(calculation_plan_id='plan-freq',task_id='task-freq',revision=1,
                intent=({'program':'gaussian','optimization_source':optimization_link(opt),'method_binding':{k:v for k,v in opt['method_binding'].items() if k!='route_contract_version'}} if stage=='freq' else {'program':'gaussian','charge':0})))
            spec=core.ResourceSpec(resource_spec_id='resource-freq',task_id='task-freq',resources={'tier':'simple'})
            f.store.store_resource_spec(spec);f.store.create_attempt(core.Attempt(attempt_id=attempt,task_id='task-freq',ordinal=1))
            plan='plan-freq';rs='resource-freq'
            f.resources=lambda:execution.ResolvedResourceRequest(resource_spec=spec,cores=8,memory_mb=16384 if stage=='freq' else 12288,walltime_seconds=3600,queue='simple')
            f.workspace=lambda:execution.WorkspaceBinding(project=f.store.load_project('project-1'),attempt_id=attempt,
                local_approved_root=str(f.local_root),local_attempt_dir=str(f.local_project/attempt),rtwin_approved_root=r'C:\RTWIN',
                rtwin_attempt_dir='C:\\RTWIN\\project-1\\'+attempt,remote_approved_root=execution.LEGACY_REMOTE_ROOT,remote_attempt_dir=f.remote_project_dir+'/'+attempt)
        raw=((('%chk=gaussian.chk\n%mem=12GB\n%nprocshared=8\n'+ROUTE) if stage=='freq' else OPT_ROUTE)+
             '\n\nsynthetic\n\n0 1\n'+'\n'.join(('C' if i<4 else 'H')+' '+' '.join(map(str,p)) for i,p in enumerate(coords))+'\n\n').encode()
        kwargs=dict(input_raw=raw,attempt_id=attempt,calculation_plan_id=plan,resource_spec_id=rs)
        if stage=='freq':kwargs.update(startup='freq-resource',headroom_mib=4096,resource_memory_mb=16384)
        qualified,*_,snapshot=f.qualified_case(**kwargs)
        root=f.root/'result-transport';root.mkdir()
        transport=_ProgramTransportStore._create_completion_store(root/'program.sqlite3',approved_root=root);self.addCleanup(transport.close)
        driver=_Driver({'gaussian.log':log_bytes(freq=stage=='freq',values=values,coords=coords)})
        scheduler={a['portable_name']:a['content_utf8'].encode() for a in snapshot.scheduler_artifacts}
        runtime._prepare_program_execution(f.store,snapshot=snapshot,program_transport_store=transport,input_bytes={'flow.gjf':raw},scheduler_artifact_bytes=scheduler,driver=driver)
        execution.execute_once(f.store,snapshot=snapshot,current_profile=qualified,confirmed_execution_snapshot_id=snapshot.program_execution_snapshot_id,
            prepared_input_bytes=raw,pbs_template_bytes=next(iter(scheduler.values())),port=runtime._ProgramExecutionPort(snapshot=snapshot,program_transport_store=transport,driver=driver))
        f.snapshot,f.program_transport_store,f.driver=snapshot,transport,driver;f.input_bytes={'flow.gjf':raw}
        completiontests_fixture.CompletionTests.publish(f);self.assertEqual(completiontests_fixture.CompletionTests.collect(f).data['diagnostic'],'completed')
        destination=core.SQLiteRuntimeStore();self.addCleanup(destination.close);destination._connection.deserialize(f.store._connection.serialize())
        reader,parser=(gaussian_freq_result_source,parse_freq_source) if stage=='freq' else (gaussian_result_source,parse_source)
        with reader(f.store,snapshot=snapshot,transport_store=transport,validation_driver=driver) as (_,payload,_,log):
            source,result,_,_=parser(payload,log,parser_version='1.2.0')
        append_pair(destination,source,result)
        return dict(source_store=f.store,snapshot=snapshot,transport_store=transport,destination=destination,validation_driver=driver,parser_version='1.2.0')
    def inputs(self):return [dict(member_id='anti',optimization=self.opt,frequency=self.freq)]
    def test_complete_native_two_stage_and_serial_replay(self):
        with patch.object(core.SQLiteRuntimeStore,'append_result',side_effect=AssertionError('read wrote')):
            a=read_two_stage_authority(self.ensemble,'anti',optimization=self.opt,frequency=self.freq)
            self.assertEqual(a['assessment']['classification'],'VALIDATED_TWO_STAGE_MINIMUM')
            first=refine_freq_ensemble(self.refined,self.profile,optimization_ensemble=self.ensemble,inputs=self.inputs())
            second=refine_freq_ensemble(first,self.profile,optimization_ensemble=self.ensemble,inputs=self.inputs())
            third=refine_freq_ensemble(second,self.profile,optimization_ensemble=self.ensemble,inputs=self.inputs(),history=[first])
        self.assertEqual(first.members[0]['post_dft_status'],'validated_minimum')
        self.assertEqual(third.supersedes_conformer_ensemble_id,second.conformer_ensemble_id)
        self.assertFalse(first.thermodynamic_eligible_members or first.ts_seed_members)
    def test_forged_self_consistent_parsed_payload_rejected(self):
        self.freq['destination']._connection.execute("UPDATE results SET result_type='v31-gaussian-parsed-result/1'")
        with self.assertRaises(ValueError):read_two_stage_authority(self.ensemble,'anti',optimization=self.opt,frequency=self.freq)
    def test_old_reader_and_same_attempt_reject(self):
        with self.assertRaises(ValueError):
            with gaussian_result_source(self.freq['source_store'],snapshot=self.freq['snapshot'],transport_store=self.freq['transport_store'],validation_driver=self.freq['validation_driver']):pass
        with self.assertRaises(RefinementAuthorityError):read_two_stage_authority(self.ensemble,'anti',optimization=self.opt,frequency=self.opt)


def inert_readout(path):
    """Exercise all real owners with the explicit existing inert driver tuple."""
    from contextlib import ExitStack
    from hashlib import sha256
    from pathlib import Path
    from auto_g16.conformer.frequency_readonly import load_freq_readout
    import auto_g16.conformer._successor_opt as opt_owner
    import auto_g16.conformer._successor_freq as freq_owner
    import auto_g16.conformer.frequency_readonly as read_owner
    raw=Path(path).read_bytes();reader=load_freq_readout(raw,sha256(raw).hexdigest())
    def opt(*args,**kwargs):return gaussian_result_source(*args,**{**kwargs,'validation_driver':_Driver({})})
    def freq(*args,**kwargs):return gaussian_freq_result_source(*args,**{**kwargs,'validation_driver':_Driver({})})
    with ExitStack() as stack:
        stack.enter_context(patch.object(opt_owner,'gaussian_result_source',opt))
        stack.enter_context(patch.object(freq_owner,'gaussian_freq_result_source',freq))
        stack.enter_context(patch.object(read_owner,'gaussian_freq_result_source',freq))
        for name in ('append_result','append_observation'):
            stack.enter_context(patch.object(core.SQLiteRuntimeStore,name,side_effect=AssertionError('read wrote')))
        selected=reader.frequency_sources[0]
        from auto_g16.query import NativeSource,NativeQueryService
        query=NativeQueryService((NativeSource(source_id='freq',database=Path(selected.revision.path),snapshots=(selected.snapshot,),freq_readout=reader),))
        return query.get_attempt('freq',selected.snapshot.attempt_id)


class FrequencyPersistenceTests(FrequencyWorkflowTests):
    # Build the synthetic calculation twice only for this complete durable proof.
    test_complete_native_two_stage_and_serial_replay=None
    test_forged_self_consistent_parsed_payload_rejected=None
    test_old_reader_and_same_attempt_reject=None
    def test_revision_idempotency_registration_query_and_fresh_process(self):
        import json,subprocess,sys
        from dataclasses import asdict
        from pathlib import Path
        from auto_g16.result._successor import _plain
        from auto_g16.conformer._successor_opt import import_opt_result_revision
        from auto_g16.conformer._successor_freq import import_freq_result_revision
        from tests.v31.transport.test_publisher_pilot_orchestration import file_binding
        source_rows=[]
        for mid,args,importer in [('anti',self.opt,import_opt_result_revision),('anti',self.freq,import_freq_result_revision)]:
            root=Path(args['transport_store']._path).parent
            initial=root/'initial.sqlite3';initial.write_bytes(args['source_store']._connection.serialize())
            output=root/'parsed.sqlite3'
            kwargs={k:v for k,v in args.items() if k!='destination'}
            receipt=importer(**kwargs,destination_path=initial,output_path=output,approved_root=root)
            self.assertEqual(receipt,importer(**kwargs,destination_path=initial,output_path=output,approved_root=root))
            self.assertEqual(initial.read_bytes(),args['source_store']._connection.serialize())
            snapshot=root/'snapshot.json';snapshot.write_text(json.dumps(_plain(args['snapshot']._approval_semantics())))
            corepath=args['source_store']._connection.execute('PRAGMA database_list').fetchone()[2]
            source_rows.append(dict(member_id=mid,original=dict(snapshot_id=args['snapshot'].program_execution_snapshot_id,
                core=asdict(file_binding(Path(corepath))),transport=asdict(file_binding(Path(args['transport_store']._path))),
                bootstrap_source_sha256='0'*64,bootstrap_source_size_bytes=1),snapshot=asdict(file_binding(snapshot)),
                transport_root=str(root),revision=asdict(file_binding(output)),parser_version='1.2.0'))
            with core.SQLiteRuntimeStore.read_snapshot(output) as dest:
                args['destination']=dest
                if importer is import_freq_result_revision:
                    a=read_two_stage_authority(self.ensemble,'anti',optimization=self.opt,frequency=args)
                    self.assertEqual(a['assessment']['classification'],'VALIDATED_TWO_STAGE_MINIMUM')
                # Keep a separate immutable-memory snapshot for later composition.
                retained=core.SQLiteRuntimeStore();self.addCleanup(retained.close)
                retained._connection.deserialize(dest._connection.serialize());args['destination']=retained
        refined=refine_freq_ensemble(self.refined,self.profile,optimization_ensemble=self.ensemble,inputs=self.inputs())
        root=Path(self.freq['transport_store']._path).parent
        material=root/'material.json';material.write_text(json.dumps(_plain(dict(profile=self.profile._identity_payload(),original=self.ensemble._identity_payload(),
            opt_refined=self.refined._identity_payload(),history=[],prior=self.refined._identity_payload(),refined=refined._identity_payload()))))
        registry=root/'registry.json';registry.write_text(json.dumps(dict(schema='auto-g16-freq-readout-registration/1',material=asdict(file_binding(material)),
            optimization_sources=[source_rows[0]],frequency_sources=[source_rows[1]])))
        before={str(p):p.read_bytes() for p in (material,registry,Path(source_rows[0]['original']['core']['path']),Path(source_rows[1]['original']['core']['path']))}
        dto=inert_readout(registry)
        data=dto['data'];self.assertEqual(data['facts']['frequencies']['unit'],'cm^-1')
        self.assertEqual(data['provenance']['parsed_result']['frequency_count'],36)
        self.assertEqual(data['provenance']['parsed_result']['optimization_attempt_id'],'attempt-1')
        self.assertEqual(data['axes']['validation']['value']['classification'],'VALIDATED_TWO_STAGE_MINIMUM')
        script='import json,sys; from tests.v31.conformer.test_successor_freq import inert_readout; print(json.dumps(inert_readout(sys.argv[1])))'
        proc=subprocess.run([sys.executable,'-B','-c',script,str(registry)],capture_output=True,text=True,timeout=60)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(json.loads(proc.stdout),dto)
        self.assertEqual({p:Path(p).read_bytes() for p in before},before)


class FrequencyProjectionTests(unittest.TestCase):
    def test_unparsed_counts_are_unknown_and_actual_zero_remains_visible(self):
        from types import SimpleNamespace
        from auto_g16.conformer.frequency_readonly import _frequency_counts
        from auto_g16.result.models import ParseStatus
        for status in (ParseStatus.UNPARSEABLE,ParseStatus.UNSUPPORTED):
            counts=_frequency_counts(SimpleNamespace(parse_status=status,facts={}))
            self.assertIsNone(counts['frequency_count']);self.assertIsNone(counts['imaginary_frequency_count'])
            self.assertEqual(counts['frequency_count_availability'],'unavailable')
        counts=_frequency_counts(SimpleNamespace(parse_status=ParseStatus.PARSED,facts={'frequencies_cm-1':(0.,-0.001,1.)}))
        self.assertEqual((counts['frequency_count'],counts['imaginary_frequency_count'],counts['zero_frequency_count']),(3,1,1))
    def test_freq_and_opt_share_bounded_slot(self):
        from auto_g16.conformer import readonly
        from auto_g16.conformer.frequency_readonly import FreqReadout
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        reader=object.__new__(FreqReadout)
        entered=Event();release=Event()
        def replay(*args):entered.set();release.wait(1);return 'done'
        with patch.object(FreqReadout,'_read_serial',replay),ThreadPoolExecutor(1) as pool:
            future=pool.submit(reader.read,None,'freq');self.assertTrue(entered.wait(1))
            try:
                with patch.object(readonly,'_OPT_READ_WAIT_SECONDS',.01):
                    with self.assertRaises(readonly.OptReadBusy):readonly.OptReadout.read(None,None,'opt')
            finally:release.set()
            self.assertEqual(future.result(2),'done')
        self.assertTrue(readonly._OPT_READ_LOCK.acquire(timeout=.01));readonly._OPT_READ_LOCK.release()


def opposite_terminal():
    import math
    origin=COORDS[2];axis=[COORDS[2][i]-COORDS[1][i] for i in range(3)]
    length=math.sqrt(sum(v*v for v in axis));axis=[v/length for v in axis]
    result=list(COORDS)
    for index in (3,11,12,13):
        delta=[COORDS[index][i]-origin[i] for i in range(3)];dot=sum(x*y for x,y in zip(delta,axis))
        result[index]=tuple(round(origin[i]+2*dot*axis[i]-delta[i],6) for i in range(3))
    return tuple(result)
GAUCHE=opposite_terminal()


class TwoMemberFrequencyTests(FrequencyWorkflowTests):
    two_members=True
    test_complete_native_two_stage_and_serial_replay=None
    test_forged_self_consistent_parsed_payload_rejected=None
    test_old_reader_and_same_attempt_reject=None
    def test_partial_then_both_members_replay_without_losing_negative_evidence(self):
        gopt=self.case('opt','attempt-3',coords=GAUCHE)
        ga=read_opt_authority(self.ensemble,'gauche',**gopt)
        self.assertEqual(ga['assessment']['geometry_disposition'],'accepted_opt_geometry')
        opt=refine_opt_ensemble(self.ensemble,self.profile,inputs=[dict(member_id='anti',**self.opt),dict(member_id='gauche',**gopt)])
        self.assertTrue(all(m['post_dft_status']=='optimized_frequency_pending' for m in opt.members))
        inputs=[dict(member_id='anti',optimization=self.opt,frequency=self.freq),dict(member_id='gauche',optimization=gopt,frequency=None)]
        first=refine_freq_ensemble(opt,self.profile,optimization_ensemble=self.ensemble,inputs=inputs)
        self.assertEqual([m['post_dft_status'] for m in first.members],['validated_minimum','optimized_frequency_pending'])
        gfreq=self.case('freq','attempt-4',coords=GAUCHE,opt=ga,values=(-.001,*range(1,36)))
        inputs[1]['frequency']=gfreq
        final=refine_freq_ensemble(first,self.profile,optimization_ensemble=self.ensemble,inputs=inputs)
        self.assertEqual([m['post_dft_status'] for m in final.members],['validated_minimum','frequency_failed'])
        self.assertEqual(final.members[1]['negative_frequency_authority']['assessment']['classification'],'NOT_MINIMUM')
        self.assertEqual(final.members[0]['two_stage_minimum_authority'],first.members[0]['two_stage_minimum_authority'])
        self.assertEqual(final.supersedes_conformer_ensemble_id,first.conformer_ensemble_id)
        self.assertFalse(final.thermodynamic_eligible_members or final.ts_seed_members)
        inputs[0]['frequency']=None
        with self.assertRaises(RefinementAuthorityError):refine_freq_ensemble(first,self.profile,optimization_ensemble=self.ensemble,inputs=inputs)
