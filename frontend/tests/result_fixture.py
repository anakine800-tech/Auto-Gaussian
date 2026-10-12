"""Synthetic archival facts, built only for disposable test stores.

The grammar text follows the Result owner's attributed-job fixture. No real
Gaussian output, jobs or execution is involved; parsers run at fixture setup.
"""
from hashlib import sha256
from auto_g16 import core
from auto_g16.result import (
    GaussianJobParser, GaussianLogParser, InputBinding, OutputArtifact,
    OutputEnvelope, ResultProvenanceService,
)

PREFIX = b''' Entering Gaussian System, Link 0=g16
 Symbolic Z-matrix:
 Charge = 0 Multiplicity = 1
 H 0.0 0.0 0.0
 GradGradGrad
 SCF Done: E(RHF) = -75.000000 A.U. after 10 cycles
 Item Value Threshold Converged?
 Maximum Force 0.000001 0.000450 YES
 RMS Force 0.000001 0.000300 YES
 Maximum Displacement 0.000001 0.001800 YES
 RMS Displacement 0.000001 0.001200 YES
 Optimization completed.
 -- Stationary point found.
'''
FREQUENCY = b''' Harmonic frequencies (cm**-1), IR intensities (KM/Mole), Raman scattering
 activities (A**4/AMU), depolarization ratios for plane and unpolarized
 incident light, reduced masses (AMU), force constants (mDyne/A),
 and normal coordinates:
 1 2 3
 A1 A1 A1
 Frequencies -- -123.4 200.0 300.0
 Red. masses -- 1.0 2.0 3.0
 Frc consts -- 0.1 0.2 0.3
 IR Inten -- 10.0 20.0 30.0
'''
INPUT = b'#p hf/sto-3g opt freq\n\nSynthetic fixture\n\n0 1\nH 0 0 0\n\n'


def add_result_fixtures(store):
    store.store_project(core.Project(project_id='gaussian-demo'))
    store.store_workflow_run(core.WorkflowRun(workflow_run_id='gaussian-run', project_id='gaussian-demo', workflow_name='Synthetic Gaussian archive'))
    for case in ('normal', 'no-frequency', 'error', 'missing', 'partial', 'unknown', 'v31', 'legacy'):
        identity = 'gaussian-' + case
        task_id, plan_id = 'task-' + case, 'plan-' + case
        store.store_task(core.Task(task_id=task_id, workflow_run_id='gaussian-run', task_kind='synthetic-gaussian'))
        store.store_calculation_plan(core.CalculationPlan(calculation_plan_id=plan_id, task_id=task_id, revision=1,
            intent={'program': 'gaussian', 'method': 'HF', 'basis': 'STO-3G', 'charge': 0, 'multiplicity': 1}))
        store.create_attempt(core.Attempt(attempt_id=identity, task_id=task_id, ordinal=1))
        if case == 'missing':
            continue
        if case == 'v31':
            store.append_result(core.Result(result_id='v31-record', attempt_id=identity, result_type='program-completion-evidence/1', data={'fixture': True}))
            continue
        binding = InputBinding(attempt_id=identity, calculation_plan_id=plan_id, calculation_plan_revision=1,
            prepared_input_binding_id='prepared-' + case, execution_snapshot_id='snapshot-' + case,
            input_format='gaussian-gjf', logical_name='synthetic.gjf', sha256=sha256(INPUT).hexdigest(), size_bytes=len(INPUT))
        data = PREFIX + (b'' if case == 'no-frequency' else FREQUENCY) + (
            b' Error termination request processed by link 9999.\n' if case == 'error' else b' Normal termination of Gaussian 16\n')
        owner = ResultProvenanceService(store)
        owner.record_input_binding(binding)
        for sequence in range(1, 3 if case == 'normal' else 2):
            capture = OutputEnvelope(attempt_id=identity, input_binding_observation_id=binding.observation_id,
                execution_snapshot_id=binding.execution_snapshot_id, capture_source_id=f'{case}-capture-{sequence}', capture_sequence=sequence,
                capture_status='captured', capture_completeness='partial' if case == 'partial' else 'complete',
                artifacts=(OutputArtifact(artifact_kind='gaussian-log', logical_name='synthetic.log', sha256=sha256(data).hexdigest(), size_bytes=len(data)),),
                capture_manifest_sha256='b' * 64, captured_at_utc=f'2026-09-24T00:00:0{sequence}Z')
            owner.record_output_envelope(capture)
            parser = GaussianLogParser() if case == 'legacy' else GaussianJobParser()
            owner.record_parse_outcome(parser.parse(capture, {'synthetic.log': data}))
        if case == 'unknown':
            store.append_result(core.Result(result_id='unknown-record', attempt_id=identity, result_type='future-result/1', data={'private': 'must-not-expose'}))
