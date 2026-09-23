"""Read-only receipt source failures and exact successor seed binding."""
from unittest.mock import patch
from hashlib import sha256
from dataclasses import replace

from auto_g16.conformer.service import create_sampling_profile, _assert_crest_program_execution_alignment
from auto_g16.conformer.models import _payload_sha256
from auto_g16.execution import program as p, program_runtime as runtime
from auto_g16.execution import _crest_completion as crest
from auto_g16.execution import _program_completion as c
from auto_g16.execution._crest_seed_handoff import _build_receipt_seed_handoff, _assert_receipt_seed_handoff
from auto_g16.execution._identity import ExecutionValueError
from auto_g16 import core, execution
from auto_g16.execution import _crest_seed_handoff as handoffs
from auto_g16.execution.project_provisioning import _ProjectProvisioningService, _SyntheticRemoteProjectAttestor, _SYNTHETIC_TEST_HARNESS_PRIVILEGE
from auto_g16.execution.xtb_crest_handoff import _build_xtb_crest_seed_handoff
from auto_g16.transport._canonical import TransportBoundaryError
from tests.v31.conformer import test_core as conformer_tests
from tests.v31.transport import test_publisher_pilot_orchestration as pilot
from tests.v31.transport import test_program_composition as composition
from tests.v31.transport import test_crest_completion as crest_tests
from tests.v3.execution import test_v31_lane_a as lane


def profile3():
    f = conformer_tests.ConformerCoreTests()
    data = composition._mutable_copy(f.profile()._identity_payload());data.pop('schema_version')
    species = {'graph_identity':'synthetic-h2', 'atom_order':['h1','h2'], 'atom_mapping':{'h1':'s1','h2':'s2'}, 'elements':['H','H'], 'explicit_hydrogens':[True,True], 'fragment_ids':['one','one'], 'component_count':1, 'bonds':[['h1','h2',1.0]], 'formal_charge':0, 'multiplicity':1, 'electronic_state_family':'reviewed_closed_shell_singlet'}
    data['species_binding'] = species
    data['stereochemistry_binding'] = {'scope':'locked','assignments':{},'binding_modes':{}}
    data['geometry_legality_policy']['reference_bond_maximum_distances'] = [{'atom_ids':['h1','h2'],'maximum':2.0,'unit':'angstrom'}]
    data['rmsd_policy']['symmetry_mapping'] = [0,1]
    data['crest_imtd_gc_profile']['adapter']['contract_version'] = 3
    data['crest_imtd_gc_profile']['execution_policy'] = {**crest._POLICY, 'completion_mode':c._MODE}
    return create_sampling_profile(**data)


class ReceiptSeedTests(pilot._PilotFixture):
    @staticmethod
    def xtb_data(**changes):
        return lane.LaneAFixture.xtb_data(**{"solvent": None, **changes})

    def setUp(self):
        super().setUp()
        self.sampling = profile3()
        self.target = p._prepare_program_execution_spec(program_kind='crest', executable_path=lane.CREST_EXECUTABLE_PATH, executable_size_bytes=len(lane.CREST_EXECUTABLE_BYTES), executable_sha256=sha256(lane.CREST_EXECUTABLE_BYTES).hexdigest(), input_name='seed.xyz', input_bytes=lane.XYZ, program_data=self.crest_data(**crest._POLICY, sampling_configuration_identity=_payload_sha256(self.sampling.crest_imtd_gc_profile)), resolved_profile=self.resolved(), completion_mode=c._MODE)

    def handoff_args(self):
        return dict(core_store=self.store, xtb_program_execution_snapshot=self.snapshot, xtb_program_transport_store=self.program_transport_store, xtb_validation_driver=self.driver, crest_program_execution_spec=self.target, crest_exact_input_bytes=lane.XYZ, sampling_profile=self.sampling)

    def readonly_build(self, **changes):
        args = {**self.handoff_args(), **changes}
        before = self.store.observations_for_attempt('attempt-1'), self.store.results_for_attempt('attempt-1'), self.store.attempt_state('attempt-1'), len(self.driver.calls)
        try:
            with patch.object(self.store, 'append_observation', side_effect=AssertionError('source write')), patch.object(self.store, 'append_result', side_effect=AssertionError('source write')), patch.object(runtime, '_advance_completion', side_effect=AssertionError('source state write')):
                return _build_receipt_seed_handoff(**args)
        finally:
            after = self.store.observations_for_attempt('attempt-1'), self.store.results_for_attempt('attempt-1'), self.store.attempt_state('attempt-1'), len(self.driver.calls)
            self.assertEqual(before, after)

    def test_native_xtb_receipt_to_crest_and_strict_isolation(self):
        self.execute();self.publish();self.collect()
        handoff = self.readonly_build()
        self.assertEqual(handoff.payload['schema'], 'v31-xtb-crest-seed-handoff/2')
        _assert_receipt_seed_handoff(handoff, **self.handoff_args())
        _, capture = runtime._read_program_receipt_success_authority(self.store, **self.kwargs())
        with self.assertRaisesRegex(TransportBoundaryError, 'strict consumer'):
            runtime._assert_program_terminal_success_authority(self.store, **self.kwargs(), capture=capture)
        with self.assertRaises(ExecutionValueError):
            _build_xtb_crest_seed_handoff(**self.handoff_args(), xtb_output_capture=capture)

    def test_missing_source_proof_rejects_without_write(self):
        self.execute()
        with self.assertRaises(TransportBoundaryError): self.readonly_build()

    def test_source_failure_rejects_without_write(self):
        self.execute();self.publish(code=4);self.collect()
        with self.assertRaises(TransportBoundaryError): self.readonly_build()

    def test_later_unknown_invalidates_without_write(self):
        self.execute();self.publish();self.collect()
        self.driver.query_response = {'job_id':'123.server','state':'unknown'}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        with self.assertRaises(TransportBoundaryError): self.readonly_build()

    def test_input_and_profile_splices_reject_without_write(self):
        self.execute();self.publish();self.collect()
        with self.assertRaises(ExecutionValueError): self.readonly_build(crest_exact_input_bytes=lane.XYZ+b'\n')
        old = conformer_tests.ConformerCoreTests().profile()
        with self.assertRaises(ValueError): self.readonly_build(sampling_profile=old)
        _assert_crest_program_execution_alignment(self.sampling, self.target)

    def destination(self, handoff):
        target = crest_tests.CrestCompletionTests();target.setUp();self.addCleanup(target.doCleanups)
        s = target.store
        project = core.Project(project_id='crest-project');s.store_project(project)
        s.store_workflow_run(core.WorkflowRun(workflow_run_id='crest-run',project_id=project.project_id,workflow_name='crest'))
        s.store_task(core.Task(task_id='crest-task',workflow_run_id='crest-run',task_kind='successor-program'))
        intent = {'crest_receipt_seed_handoff':{'handoff_authority_id':handoff.handoff_authority_id,'payload_sha256':handoff.payload_sha256}}
        plan = core.CalculationPlan(calculation_plan_id='crest-plan',task_id='crest-task',revision=1,intent=intent);s.store_calculation_plan(plan)
        resource = core.ResourceSpec(resource_spec_id='crest-resource',task_id='crest-task',resources={'tier':'simple'});s.store_resource_spec(resource)
        s.create_attempt(core.Attempt(attempt_id='crest-attempt',task_id='crest-task',ordinal=1))
        remote = '/home/user100/SDL/crest-project'
        attestor = _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,target=target.resolved(),observed_project_dir=remote,observed_state='ABSENT',observed_parent_physical_identity='opaque-server-parent-v1',observed_project_physical_identity=None,provisioned_project_physical_identity='crest-project-identity')
        service = _ProjectProvisioningService._from_privileged_synthetic_attestor(privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,attestor=attestor)
        binding = service.provision_remote_project(project=project,target=target.resolved(),remote_project_dir=remote,evidence_identity='inert-crest-create')
        local = target.local_root/'crest-project';local.mkdir()
        workspace = execution.WorkspaceBinding(project=project,attempt_id='crest-attempt',local_approved_root=str(target.local_root),local_attempt_dir=str(local/'crest-attempt'),remote_approved_root=execution.LEGACY_REMOTE_ROOT,remote_attempt_dir=remote+'/crest-attempt',rtwin_approved_root=r'C:\RTWIN',rtwin_attempt_dir=r'C:\RTWIN\crest-project\crest-attempt')
        snapshot = p._ProgramExecutionSnapshotService._for_privileged_synthetic_tests(privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,project_provisioning=service).prepare(s,attempt_id='crest-attempt',calculation_plan_id='crest-plan',resource_spec_id='crest-resource',program_execution_spec=self.target,project_physical_binding=binding,resolved_resource_request=execution.ResolvedResourceRequest(resource_spec=resource,cores=8,memory_mb=12288,walltime_seconds=3600,queue='simple'),resolved_server_profile=target.resolved(),workspace_binding=workspace,completion_rendering_material=target.material)
        fixed = handoffs._FixedReceiptSubmission(handoff,snapshot.program_execution_snapshot_id,binding.semantic_payload(),plan.calculation_plan_id,runtime.semantic_sha256(plan.intent),self.handoff_args())
        return target,snapshot,fixed

    def test_fixed_submission_revalidates_both_projects_plan_and_source(self):
        self.execute();self.publish();self.collect()
        handoff=self.readonly_build();target,snapshot,fixed=self.destination(handoff)
        with patch.object(handoffs,'_FIXED_RECEIPT_SUBMISSION',fixed):
            handoffs._assert_fixed_receipt_submission(target.store,snapshot,lane.XYZ)
        for changed in (None,replace(fixed,plan_intent_sha256='0'*64),replace(fixed,destination_snapshot_id='other'),replace(fixed,destination_project_binding={}),replace(fixed,source_context={**fixed.source_context,'crest_exact_input_bytes':lane.XYZ+b'\n'})):
            with patch.object(handoffs,'_FIXED_RECEIPT_SUBMISSION',changed), self.assertRaises(ExecutionValueError):
                handoffs._assert_fixed_receipt_submission(target.store,snapshot,lane.XYZ)
        self.driver.query_response={'job_id':'123.server','state':'unknown'}
        runtime._query_program_scheduler(self.store,**self.kwargs())
        with patch.object(handoffs,'_FIXED_RECEIPT_SUBMISSION',fixed), self.assertRaises(TransportBoundaryError):
            handoffs._assert_fixed_receipt_submission(target.store,snapshot,lane.XYZ)
        self.assertEqual(target.store.attempt_state('crest-attempt'),core.AttemptState.PLANNED)
        self.assertEqual(target.driver.calls,[])
