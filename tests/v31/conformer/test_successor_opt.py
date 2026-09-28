"""Native inert receipt-to-Opt lineage; no production driver or network."""
import unittest
from unittest.mock import patch
from pathlib import Path

from auto_g16 import core, execution
from auto_g16.execution import program_runtime as runtime
from auto_g16.execution._gaussian_result_source import gaussian_result_source
from auto_g16.result._successor import parse_source, append_pair
from auto_g16.conformer._successor_opt import read_opt_authority, refine_opt_ensemble, ROUTE
from auto_g16.conformer.refinement_authority import RefinementAuthorityError
from auto_g16.conformer.service import build_conformer_ensemble
from auto_g16.transport.program import _ProgramTransportStore
from tests.v31.transport import test_gaussian_successor as gaussian_fixture
from tests.v31.transport.test_program_composition import _Driver
from tests.v31.transport import test_program_completion as completion_fixture
from tests.v31.conformer import test_core as conformer_fixture
from tests.v3.result.test_gaussian_job import LINES


class SuccessorOptTests(unittest.TestCase):
    def setUp(self):
        f = gaussian_fixture.GaussianSuccessorTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.fixture = f
        c = conformer_fixture.ConformerCoreTests()
        species = c.species_binding()
        species['elements'] = ['C'] * 4
        species['explicit_hydrogens'] = [False] * 4
        self.profile = c.profile(species=species)
        coords = c.coordinates()
        observations = [c.observation(self.profile, 'anti', coordinates=coords),
                        c.observation(self.profile, 'gauche', member_index=1,
                                      coordinates=[[0., 0., 0.], [1.5, 0., 0.], [2.5, 1.7, 0.], [3.5, 1., 0.]])]
        self.prior = build_conformer_ensemble(project_id=getattr(self, 'sampling_project', 'project-1'), calculation_plan_id='ensemble-plan',
                                             calculation_plan_revision=1, profile=self.profile, observations=observations)
        member_id = getattr(self, 'selected_member', 'anti')
        coords = self.prior.members[0 if member_id == 'anti' else 1]['coordinates_angstrom']
        output_coords = getattr(self, 'output_coordinates', coords)
        version = getattr(self, 'parser_version', '1.1.0')
        attempt_id = getattr(self, 'attempt_id', 'attempt-1')
        if attempt_id != 'attempt-1':
            f.store.store_task(core.Task(task_id='task-2', workflow_run_id='run-1', task_kind='successor-program'))
            f.store.store_calculation_plan(core.CalculationPlan(calculation_plan_id='plan-2', task_id='task-2',
                revision=1, intent={'program':'gaussian', 'charge':0}))
            spec = core.ResourceSpec(resource_spec_id='resource-2',task_id='task-2',resources={'tier':'simple'})
            f.store.store_resource_spec(spec)
            f.store.create_attempt(core.Attempt(attempt_id=attempt_id, task_id='task-2', ordinal=1))
            f.resources = lambda: execution.ResolvedResourceRequest(resource_spec=spec,cores=8,
                memory_mb=12288,walltime_seconds=3600,queue='simple')
            f.workspace = lambda: execution.WorkspaceBinding(
                project=f.store.load_project('project-1'), attempt_id=attempt_id,
                local_approved_root=str(f.local_root), local_attempt_dir=str(f.local_project/attempt_id),
                rtwin_approved_root=r'C:\RTWIN', rtwin_attempt_dir='C:\\RTWIN\\project-1\\'+attempt_id,
                remote_approved_root=execution.LEGACY_REMOTE_ROOT,
                remote_attempt_dir=f.remote_project_dir+'/'+attempt_id)
        raw = (ROUTE+'\n\nsynthetic workflow only\n\n0 1\n'+
               '\n'.join('C '+' '.join(str(v) for v in point) for point in coords)+'\n\n').encode()
        atom_lines = tuple((' %d 6 0 %s' % (i, ' '.join(str(v) for v in point))).encode()
                           for i, point in enumerate(output_coords, 1))
        log = b'\n'.join(((b' Entering Gaussian System, Link 0=/opt/gaussian/g16' if version == '1.2.0' else LINES[0]), *LINES[5:9],
                           b' SCF Done: E(RwB97XD) = -75.000000 A.U. after 10 cycles',
                           *LINES[27:32], *atom_lines, LINES[34], *LINES[10:17], LINES[36]))+b'\n'
        qualified, _, _, _, _, _, _, _, snapshot = f.qualified_case(input_raw=raw, attempt_id=attempt_id,
            calculation_plan_id='plan-1' if attempt_id=='attempt-1' else 'plan-2',
            resource_spec_id='resource-1' if attempt_id=='attempt-1' else 'resource-2')
        root = f.root/'result-transport'
        root.mkdir()
        transport = _ProgramTransportStore._create_completion_store(root/'program.sqlite3', approved_root=root)
        self.addCleanup(transport.close)
        driver = _Driver({'gaussian.log': log})
        scheduler = {'gaussian.pbs': snapshot.scheduler_artifacts[0]['content_utf8'].encode()}
        runtime._prepare_program_execution(f.store, snapshot=snapshot, program_transport_store=transport,
                                           input_bytes={'flow.gjf': raw}, scheduler_artifact_bytes=scheduler, driver=driver)
        execution.execute_once(f.store, snapshot=snapshot, current_profile=qualified,
                               confirmed_execution_snapshot_id=snapshot.program_execution_snapshot_id,
                               prepared_input_bytes=raw, pbs_template_bytes=scheduler['gaussian.pbs'],
                               port=runtime._ProgramExecutionPort(snapshot=snapshot, program_transport_store=transport, driver=driver))
        f.snapshot, f.program_transport_store, f.driver = snapshot, transport, driver
        f.input_bytes = {'flow.gjf': raw}
        completion_fixture.CompletionTests.publish(f)
        self.assertEqual(completion_fixture.CompletionTests.collect(f).data['diagnostic'], 'completed')
        destination = core.SQLiteRuntimeStore()
        self.addCleanup(destination.close)
        destination._connection.deserialize(f.store._connection.serialize())
        self.args = dict(source_store=f.store, snapshot=snapshot, transport_store=transport,
                         destination=destination, validation_driver=driver, parser_version=version)
        with gaussian_result_source(f.store, snapshot=snapshot, transport_store=transport,
                                    validation_driver=driver) as (_, payload, _, captured):
            source, result, _, _ = parse_source(payload, captured, parser_version=version)
        append_pair(destination, source, result)
        self.source, self.result = source, result
        self.original = Path(f.database).read_bytes()
        self.original_transport = Path(transport._path).read_bytes()
        self.calls = len(driver.calls)

    def test_complete_replayed_authority_and_partial_ensemble(self):
        with patch.object(core.SQLiteRuntimeStore, 'append_result', side_effect=AssertionError('read wrote result')), \
             patch.object(core.SQLiteRuntimeStore, 'append_observation', side_effect=AssertionError('read wrote observation')):
            authority = read_opt_authority(self.prior, 'anti', **self.args)
            self.assertEqual(authority['assessment']['geometry_disposition'], 'accepted_opt_geometry')
            refined = refine_opt_ensemble(self.prior, self.profile, inputs=[{'member_id': 'anti', **self.args}])
        self.assertEqual(refined.members[0]['post_dft_status'], 'optimized_frequency_pending')
        self.assertEqual(refined.members[1]['post_dft_status'], 'optimization_pending')
        self.assertEqual(refined.thermodynamic_eligible_members, ())
        self.assertEqual(refined.ts_seed_members, ())
        self.assertEqual(refined.coverage, self.prior.coverage)
        self.assertEqual(self.original, Path(self.fixture.database).read_bytes())
        self.assertEqual(self.calls, len(self.fixture.driver.calls))

    def test_same_id_changed_plan_is_rejected(self):
        self.args['destination']._connection.execute("UPDATE calculation_plans SET intent=? WHERE calculation_plan_id='plan-1'",
                                                    ('["record",[]]',))
        with self.assertRaises((RefinementAuthorityError, core.CoreValidationError)):
            read_opt_authority(self.prior, 'anti', **self.args)

    def test_wrong_member_input_geometry_rejects(self):
        with self.assertRaisesRegex(RefinementAuthorityError, 'geometry differs'):
            read_opt_authority(self.prior, 'gauche', **self.args)

    def test_destination_execution_project_mismatch_rejects(self):
        destination = self.args['destination']
        destination.store_project(core.Project(project_id='different-execution-project'))
        destination._connection.execute("UPDATE workflow_runs SET project_id='different-execution-project' WHERE workflow_run_id='run-1'")
        with self.assertRaisesRegex(execution.ExecutionValueError, 'differs from current Core'):
            read_opt_authority(self.prior, 'anti', **self.args)

    def test_disk_revision_and_fresh_process_source_replay(self):
        import json
        import subprocess
        import sys
        from auto_g16.conformer._successor_opt import import_opt_result_revision
        from auto_g16.result._successor import _plain
        f = self.fixture
        initial = f.root/'initial-destination.sqlite3'
        initial.write_bytes(f.store._connection.serialize())
        output = f.root/'result-revision.sqlite3'
        args = {key: value for key, value in self.args.items() if key != 'destination'}
        receipt = import_opt_result_revision(**args, destination_path=initial,
                                             output_path=output, approved_root=f.root)
        self.assertEqual(receipt, import_opt_result_revision(**args, destination_path=initial,
                                                              output_path=output, approved_root=f.root))
        with core.SQLiteRuntimeStore.read_snapshot(output) as destination:
            reopened = read_opt_authority(self.prior, 'anti', **{**self.args, 'destination': destination})
        self.assertEqual(reopened, read_opt_authority(self.prior, 'anti', **self.args))
        snapshot_path = f.root/'snapshot.json'
        snapshot_path.write_text(json.dumps(_plain(f.snapshot._approval_semantics())))
        ensemble_path = f.root/'ensemble.json'
        ensemble_path.write_text(json.dumps(_plain({'profile': self.profile._identity_payload(),
                                                   'ensemble': self.prior._identity_payload(), 'parser_version': self.args['parser_version']})))
        script = r"""
import json, sys
from auto_g16.core import SQLiteRuntimeStore
from auto_g16.execution.program import _decode_program_review_semantics
from auto_g16.execution._gaussian_result_source import gaussian_result_source
from auto_g16.result._successor import parse_source, require_pair
from auto_g16.transport.program import _ProgramTransportStore
from tests.v31.transport.test_program_composition import _Driver
snapshot = _decode_program_review_semantics(json.loads(open(sys.argv[1]).read()))
version = json.loads(open(sys.argv[6]).read())['parser_version']
source = SQLiteRuntimeStore._open_readonly_existing(sys.argv[2])
transport = _ProgramTransportStore._open_readonly_existing(sys.argv[3], approved_root=sys.argv[4])
try:
    with gaussian_result_source(source, snapshot=snapshot, transport_store=transport,
                                validation_driver=_Driver({})) as (_, payload, _, raw):
        observation, result, _, _ = parse_source(payload, raw, parser_version=version)
    with SQLiteRuntimeStore.read_snapshot(sys.argv[5]) as destination:
        require_pair(destination, observation, result)
    from auto_g16.conformer.models import SamplingProfile, ConformerEnsemble
    from auto_g16.conformer._successor_opt import read_opt_authority, refine_opt_ensemble
    from inspect import signature
    data = json.loads(open(sys.argv[6]).read())
    def arguments(factory, payload):
        return {key: payload[key] for key in signature(factory).parameters if key in payload}
    profile = SamplingProfile._create(**arguments(SamplingProfile._create, data['profile']))
    prior = ConformerEnsemble._create(profile=profile, **arguments(ConformerEnsemble._create, data['ensemble']))
    driver = _Driver({})
    from unittest.mock import patch
    with SQLiteRuntimeStore.read_snapshot(sys.argv[5]) as destination, \
         patch.object(SQLiteRuntimeStore, 'append_result', side_effect=AssertionError('unexpected write')), \
         patch.object(SQLiteRuntimeStore, 'append_observation', side_effect=AssertionError('unexpected write')):
        args = dict(source_store=source, snapshot=snapshot, transport_store=transport,
                    destination=destination, validation_driver=driver, parser_version=version)
        authority = read_opt_authority(prior, 'anti', **args)
        refined = refine_opt_ensemble(prior, profile, inputs=[{'member_id': 'anti', **args}])
        assert not driver.calls
    print(json.dumps([observation.observation_id, result.result_id,
                      authority['optimization_geometry_authority_id'], refined.conformer_ensemble_id]))
finally:
    transport.close()
    source.close()
"""
        answer = subprocess.run([sys.executable, '-c', script, str(snapshot_path), str(f.database),
                                 str(f.program_transport_store._path), str(Path(f.program_transport_store._path).parent),
                                 str(output), str(ensemble_path)], text=True, capture_output=True, timeout=60, check=True)
        refined = refine_opt_ensemble(self.prior, self.profile, inputs=[{'member_id': 'anti', **self.args}])
        self.assertEqual(json.loads(answer.stdout), [self.source.observation_id, self.result.result_id,
                                                    reopened['optimization_geometry_authority_id'], refined.conformer_ensemble_id])
        self.assertEqual(self.original, Path(f.database).read_bytes())
        self.assertEqual(self.calls, len(f.driver.calls))

    def test_destination_alias_and_same_path_rejected_before_write(self):
        from auto_g16.conformer._successor_opt import import_opt_result_revision
        f = self.fixture
        args = {key: value for key, value in self.args.items() if key != 'destination'}
        output = f.root/'forbidden.sqlite3'
        with self.assertRaises(RefinementAuthorityError):
            import_opt_result_revision(**args, destination_path=f.database,
                                       output_path=output, approved_root=f.root)
        self.assertFalse(output.exists())

    def test_source_mixed_execution_generation_rejects(self):
        from auto_g16.transport._canonical import TransportBoundaryError
        self.fixture.store.append_observation(core.Observation(observation_id='legacy-execution',
            attempt_id='attempt-1', observation_type='v3.remote-effect-receipt', data={}))
        with self.assertRaisesRegex(TransportBoundaryError, 'mixed V30'):
            read_opt_authority(self.prior, 'anti', **self.args)

    def test_serial_revision_preserves_unselected_member_provenance(self):
        first = refine_opt_ensemble(self.prior, self.profile, inputs=[{'member_id': 'anti', **self.args}])
        # Geometry is unchanged in the synthetic Opt, so replaying anti against
        # the first revision is valid. The other retained member must stay exact.
        second = refine_opt_ensemble(first, self.profile, inputs=[{'member_id': 'anti', **self.args}])
        self.assertEqual(second.members[1], first.members[1])
        self.assertNotEqual(second.clusters[-1]['cluster_id'], first.clusters[-1]['cluster_id'])
        # Exercise the serial branch without using a retained claim as current
        # authority: read is replaced only for the opposite-member projection.
        from auto_g16.result._successor import payload_hash
        prior_authority = read_opt_authority(self.prior, 'anti', **self.args)
        opposite = {**prior_authority, 'selected_geometry': {**prior_authority['selected_geometry'],
                    'atoms': tuple({**atom, **dict(zip(('x','y','z'), point))} for atom,point in zip(
                        prior_authority['selected_geometry']['atoms'], first.members[1]['coordinates_angstrom']))}}
        with patch('auto_g16.conformer._successor_opt.read_opt_authority', return_value=opposite):
            projected = refine_opt_ensemble(first, self.profile, inputs=[{'member_id': 'gauche', **self.args}])
        self.assertEqual(projected.members[0], first.members[0])
        self.assertEqual(projected.members[1]['post_dft_status'], 'optimized_frequency_pending')


class NativeSerialOptTests(unittest.TestCase):
    def case(self, member, attempt, output):
        case = SuccessorOptTests()
        case.parser_version = '1.2.0'
        case.sampling_project = 'original-sampling-project'
        case.selected_member = member
        case.attempt_id = attempt
        case.output_coordinates = output
        self.addCleanup(case.doCleanups)
        case.setUp()
        return case

    def test_native_version_disk_and_fresh_process(self):
        case = SuccessorOptTests()
        case.parser_version = '1.2.0'
        self.addCleanup(case.doCleanups)
        case.setUp()
        case.test_disk_revision_and_fresh_process_source_replay()

    def test_changed_geometries_serial_then_joint_replay_and_dedup(self):
        import json
        import subprocess
        import sys
        from auto_g16.result._successor import _plain
        from auto_g16.conformer._successor_opt import import_opt_result_revision
        original = conformer_fixture.ConformerCoreTests().coordinates()
        optimized = [[x+0.02, y+0.03, z+0.04] for x,y,z in original]
        anti = self.case('anti', 'attempt-1', optimized)
        e0 = anti.prior
        self.assertNotEqual(e0.project_id, anti.args['snapshot'].project_physical_binding.project_id)
        ea = refine_opt_ensemble(e0, anti.profile, inputs=[{'member_id':'anti', **anti.args}])
        self.assertEqual(ea.project_id, e0.project_id)
        self.assertNotEqual(ea.members[0]['coordinates_angstrom'], e0.members[0]['coordinates_angstrom'])
        self.assertEqual(ea.members[1]['post_dft_status'], 'optimization_pending')
        ea_payload = _plain(ea._identity_payload())
        with self.assertRaisesRegex(RefinementAuthorityError, 'geometry differs'):
            read_opt_authority(ea, 'anti', **anti.args)
        # The second full inert Attempt starts only after the anti disposition.
        gauche = self.case('gauche', 'attempt-2', optimized)
        self.assertEqual(e0, gauche.prior)
        inputs = [{'member_id':'anti', **anti.args}, {'member_id':'gauche', **gauche.args}]
        eab = refine_opt_ensemble(e0, anti.profile, inputs=inputs)
        self.assertEqual(eab.project_id, e0.project_id)
        self.assertEqual(eab.supersedes_conformer_ensemble_id, e0.conformer_ensemble_id)
        self.assertEqual(ea_payload, _plain(ea._identity_payload()))
        self.assertEqual(eab.members[0]['post_dft_status'], 'optimized_frequency_pending')
        self.assertEqual(eab.members[1]['post_dft_status'], 'deduplicated_after_optimization')
        self.assertEqual(eab.dedup_decisions[-1]['member_ids'], ('anti', 'gauche'))
        self.assertEqual(eab.dedup_decisions[-1]['decision'], 'duplicate')
        self.assertFalse(eab.thermodynamic_eligible_members or eab.ts_seed_members)
        with self.assertRaises(RefinementAuthorityError):
            refine_opt_ensemble(e0, anti.profile, inputs=[{'member_id':'gauche', **anti.args}])
        with self.assertRaisesRegex(RefinementAuthorityError, 'duplicate Opt member'):
            refine_opt_ensemble(e0, anti.profile, inputs=[inputs[0], inputs[0]])
        with self.assertRaisesRegex(RefinementAuthorityError, 'one Attempt'):
            refine_opt_ensemble(e0, anti.profile, inputs=[inputs[0], {'member_id':'gauche', **anti.args}])
        bundles=[]
        for member, case in (('anti',anti),('gauche',gauche)):
            f=case.fixture
            initial=f.root/'serial-base.sqlite3'
            initial.write_bytes(f.store._connection.serialize())
            output=f.root/'serial-result.sqlite3'
            import_opt_result_revision(**{k:v for k,v in case.args.items() if k!='destination'},
                destination_path=initial,output_path=output,approved_root=f.root)
            bundles.append({'member_id':member,'core':str(f.database),'transport':str(f.program_transport_store._path),
                'transport_root':str(Path(f.program_transport_store._path).parent),'destination':str(output),
                'snapshot':_plain(f.snapshot._approval_semantics())})
        manifest=anti.fixture.root/'serial-replay.json'
        manifest.write_text(json.dumps({'profile':_plain(anti.profile._identity_payload()),
            'ensemble':_plain(e0._identity_payload()),'bundles':bundles}))
        script = "from tests.v31.conformer.test_successor_opt import replay_serial_bundle; import sys; replay_serial_bundle(sys.argv[1])"
        proc=subprocess.run([sys.executable,'-c',script,str(manifest)],text=True,capture_output=True,check=True,timeout=60)
        self.assertEqual(json.loads(proc.stdout), eab.conformer_ensemble_id)
        for case in (anti,gauche):
            self.assertEqual(case.original,Path(case.fixture.database).read_bytes())
            self.assertEqual(case.calls,len(case.fixture.driver.calls))
            self.assertEqual(case.original_transport,Path(case.fixture.program_transport_store._path).read_bytes())


def replay_serial_bundle(path):
    """Fresh-process test reader; opens retained files only and forbids effects."""
    import json
    from contextlib import ExitStack
    from inspect import signature
    from auto_g16.conformer.models import SamplingProfile, ConformerEnsemble
    from auto_g16.execution.program import _decode_program_review_semantics
    data=json.loads(Path(path).read_text())
    def args(factory,payload):
        return {k:payload[k] for k in signature(factory).parameters if k in payload}
    profile=SamplingProfile._create(**args(SamplingProfile._create,data['profile']))
    prior=ConformerEnsemble._create(profile=profile,**args(ConformerEnsemble._create,data['ensemble']))
    with ExitStack() as stack:
        inputs=[];drivers=[]
        for item in data['bundles']:
            source=core.SQLiteRuntimeStore._open_readonly_existing(item['core']);stack.callback(source.close)
            transport=_ProgramTransportStore._open_readonly_existing(item['transport'],approved_root=item['transport_root'])
            stack.callback(transport.close)
            destination=stack.enter_context(core.SQLiteRuntimeStore.read_snapshot(item['destination']))
            driver=_Driver({});drivers.append(driver)
            inputs.append(dict(member_id=item['member_id'],source_store=source,transport_store=transport,
                destination=destination,snapshot=_decode_program_review_semantics(item['snapshot']),
                validation_driver=driver,parser_version='1.2.0'))
        stack.enter_context(patch.object(core.SQLiteRuntimeStore,'append_observation',side_effect=AssertionError('write')))
        stack.enter_context(patch.object(core.SQLiteRuntimeStore,'append_result',side_effect=AssertionError('write')))
        result=refine_opt_ensemble(prior,profile,inputs=inputs)
        assert all(not driver.calls for driver in drivers)
        print(json.dumps(result.conformer_ensemble_id))
