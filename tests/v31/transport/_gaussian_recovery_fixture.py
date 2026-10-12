"""Persistent synthetic Gaussian cases; real native owners, never live SSH."""
from contextlib import ExitStack, closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from auto_g16 import approval, core, execution
from auto_g16.execution import program as p, program_runtime as runtime
from auto_g16.execution import _program_completion as c, _project_association_source as association_owner
from auto_g16.execution.project_provisioning import _ProjectProvisioningService
from auto_g16.transport import _driver, _bridge, _program_rtwin as rtwin, program as transport
from auto_g16.transport._canonical import TransportBoundaryError
from scripts import run_v31_publisher_pilot as controller
from tests.v31.transport import test_project_profile_association as association
from tests.v31.transport import test_publisher_collection_recovery as reuse
from tests.v31.transport import test_publisher_pilot_orchestration as pilot
from tests.v31.transport import test_gaussian_successor as gaussian
from tests.v31.transport import test_rtwin_successor_bridge as bridge
from tests.v31.transport.test_gaussian_freq_resources import INPUT

REAL_POPEN = subprocess.Popen
REAL_RUN = _driver._SubprocessRTWinDriver._run
READS = frozenset(rtwin._COLLECTION_OPERATIONS)


def append(path, value):
    with Path(path).open('a') as out:
        out.write(json.dumps(value, sort_keys=True) + '\n')
        out.flush()
        os.fsync(out.fileno())


class Fixture(reuse._RecoveryFixture):
    def setUp(self):
        a = association.AssociationTests(); a.setUp()
        self.addCleanup(a.doCleanups)
        self.a = a
        f = a.f
        self.root, self.store, self.database = f.root, f.store, f.database
        rows = a.old_rows if self.stage == 'opt' else a.rows
        self.current_profile, target, self.q, evidence, self.spec, _, _, material, prior = rows
        self.input_raw = INPUT.replace(b'Freq', b'Opt') if self.stage == 'opt' else INPUT
        self.association_source = None
        binding = a.original
        if self.stage == 'freq':
            binding, self.association_source = a.issue()
        self.journal, self.journal_root = a.journal, a.root
        service = _ProjectProvisioningService._from_project_attestor(
            attestor=rtwin._RTWinProjectAttestor(current_profile=self.current_profile, target=target),
            target=target, journal=self.journal)
        snapshot_service = p._ProgramExecutionSnapshotService._for_production(project_provisioning=service, target=target)
        self.snapshot = snapshot_service.prepare(self.store, attempt_id='attempt-1', calculation_plan_id='plan-1',
            resource_spec_id='resource-1', program_execution_spec=self.spec, project_physical_binding=binding,
            resolved_resource_request=prior.resolved_resource_request, resolved_server_profile=target,
            workspace_binding=f.workspace(), completion_rendering_material=material)
        folder = self.root / 'fault-stores'; folder.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(folder / 'transport.sqlite3', approved_root=self.root)
        self.addCleanup(self.program_transport_store.close)
        self.original, _ = gaussian.GaussianSuccessorTests.installed_case(self, self.current_profile, target, self.q, evidence, self.snapshot)
        astore = approval.SQLiteApprovalStore(folder / 'approval.sqlite3'); self.addCleanup(astore.close)
        meaning = {'intent': 'inert'}
        scientific = approval.ScientificApproval.for_plan(self.store, self.store.load_calculation_plan('plan-1'),
            displayed_semantic_meaning=meaning, reviewer_id='synthetic', reviewer_evidence=meaning)
        batch = approval.BatchSubmitApproval.for_existing_attempts(self.store, [('attempt-1', scientific)], reviewer_id='synthetic', reviewer_evidence=meaning)
        basis = json.loads(Path(self.original.basis.path).read_bytes())
        attachment = {k: basis[k] for k in controller._PILOT_ATTACHMENT_KEYS if k != 'deployment_readback_evidence_sha256'}
        attachment['deployment_readback_evidence_sha256'] = self.original.basis.sha256
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(self.store, self.snapshot,
            confirmer_id='synthetic', confirmer_evidence={'publisher_pilot': attachment})
        astore.store_scientific_approval(scientific); astore.store_batch_submit_approval(batch); astore.store_operational_confirmation(confirmation)
        # Scope bytes bind the original installed evidence, not a new permission.
        owner_raw = b'SYNTHETIC Gaussian Q/4 owner acceptance\n'
        live_raw = b'SYNTHETIC Gaussian Q/4 offline driver construction\n'
        qscope = {k: basis[k] for k in ('qualification_payload_sha256', 'qualification_file_sha256')}
        live_scope = {**qscope, **{k: basis[k] for k in ('resolved_server_profile_id', 'program_execution_snapshot_id', 'pilot_window')}, 'attempt_id': 'attempt-1'}
        scope = folder / 'original-review.json'
        scope.write_bytes(c._receipt_json({'schema': 'v31-publisher-reviewed-scope/1',
            'owner_exact_q': {'raw': pilot.digest(owner_raw), 'scope': qscope},
            'live_gate': {'raw': pilot.digest(live_raw), 'scope': live_scope}}))
        stores = []
        for role, store, path in [('core', self.store, self.database), ('approval', astore, folder / 'approval.sqlite3'), ('transport', self.program_transport_store, folder / 'transport.sqlite3')]:
            pin = pilot.file_binding(path)
            stores.append(controller._PilotStoreBinding(role, store, pin.path, pin.parent_chain, pin.file_identity))
        self.scheduler_bytes = {a['portable_name']: a['content_utf8'].encode() for a in self.snapshot.scheduler_artifacts}
        self.original_run = controller._FixedPilotRun(self.snapshot, self.current_profile, tuple(stores),
            scientific.scientific_approval_id, batch.batch_submit_approval_id, confirmation.operational_confirmation_id,
            meaning, self.input_raw, self.scheduler_bytes[self.snapshot.scheduler_artifacts[0]['portable_name']],
            pilot.file_binding(scope), ())
        self.wire = a.b.wire
        self.wire.outputs = {'gaussian.log': b'Normal termination of Gaussian 16\n'}
        self.wire.calls.clear()
        def setup_peer(scope, invocation):
            if invocation.operation.name != 'SUBMIT_QSUB_ONCE': return self.wire.run(scope, invocation)
            _, frame = rtwin._prepare_program_invocation(scope, invocation)
            request = _bridge._decode_frame(frame, cap=invocation.operation.stdin_cap, field='synthetic Gaussian submit')
            assert len(request['payload']['staged']) == 5
            self.wire.calls.append(('SUBMIT_QSUB_ONCE', request))
            return _bridge._encode_frame({'protocol': _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, 'operation':'SUBMIT_QSUB_ONCE',
                'status':'ok', 'result':{'job_id':'123.server'}}), b'', 0, 'completed', True, True
        with patch.object(rtwin, '_FIXED_PUBLISHER_INSTALLATION', self.original), \
                patch.object(controller, '_FIXED_PILOT_RUN', self.original_run), \
                patch.object(_driver._SubprocessRTWinDriver, '_run', side_effect=setup_peer):
            driver = rtwin._RTWinProgramEffectDriver(snapshot=self.snapshot, current_profile=self.current_profile, program_transport_store=self.program_transport_store)
            token = rtwin._GAUSSIAN_LAUNCH_OWNER.set((self.snapshot,
                lambda: controller._current_gaussian_handoff_approvals(self.original_run, driver._publisher)))
            try:
                controller._load_validate_current(self.original_run, driver._publisher)
                runtime._prepare_program_execution(self.store, snapshot=self.snapshot, program_transport_store=self.program_transport_store,
                    input_bytes={'flow.gjf': self.input_raw}, scheduler_artifact_bytes=self.scheduler_bytes, driver=driver)
                result = execution.execute_once(self.store, snapshot=self.snapshot, current_profile=self.current_profile,
                    confirmed_execution_snapshot_id=self.snapshot.program_execution_snapshot_id, prepared_input_bytes=self.input_raw,
                    pbs_template_bytes=self.scheduler_bytes[self.snapshot.scheduler_artifacts[0]['portable_name']],
                    port=runtime._ProgramExecutionPort(snapshot=self.snapshot, program_transport_store=self.program_transport_store, driver=driver))
                assert result.claim is core.SubmissionIntentClaim.WINNER
            finally:
                rtwin._GAUSSIAN_LAUNCH_OWNER.reset(token)
                driver.close()
        assert sum(op == 'SUBMIT_QSUB_ONCE' for op, _ in self.wire.calls) == 1
        self.setup_calls = [op for op, _ in self.wire.calls]
        receipt = dict(c._receipt_binding(self.snapshot, '123.server', bridge.directory_token(self.snapshot.workspace_binding.remote_attempt_dir)))
        receipt.update(termination={'kind': 'exited', 'returncode': 0, 'signal': None}, finished_at='2001-01-02T00:00:00.000000Z', outputs=[])
        for declaration in (*self.spec.required_outputs, *self.spec.optional_outputs):
            raw = self.wire.outputs.get(declaration['portable_name'])
            receipt['outputs'].append({**{k: declaration[k] for k in ('logical_role','portable_name','format')},
                'presence': 'present' if raw is not None else 'absent', 'size_bytes': len(raw) if raw else None, 'sha256': sha256(raw).hexdigest() if raw else None})
        self.wire.outputs['v31-completion.json'] = c._receipt_json(receipt)
        self.recovery_root = self.root / 'recovery'; self.recovery_root.mkdir()
        self.split_store_roots = True
        self.run, self.installation, self.document = self.install_recovery()

    def write(self, name, raw):
        return super().write(name, self.input_raw if name == 'input.xyz' else raw)


def build(stage, path):
    f = Fixture(); f.stage = stage; f.setUp()
    # This closed test-only codec never becomes a production installation hook.
    reuse._TEST_TYPES['_AssociationSource'] = association_owner._AssociationSource
    reuse._TEST_TYPES['_AssociationInstallation'] = association_owner._AssociationInstallation
    state = dict(run=f.run, installation=f.installation, original=f.original, outputs=f.wire.outputs,
        association_source=f.association_source, stage=stage)
    Path(path).write_text(json.dumps(reuse._pack(state)))
    for op in f.setup_calls:
        append(str(path) + '.wire.jsonl', {'pid': os.getpid(), 'phase': 'setup', 'operation': op})
    os._exit(0)  # Retain owned synthetic stores for the parent to inspect.


def persisted(state):
    result = {}
    for binding in state['run'].databases:
        with closing(sqlite3.connect(Path(binding.path).as_uri() + '?mode=ro', uri=True)) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            result[binding.role] = {name: [[{'blob_hex': value.hex()} if isinstance(value, bytes) else value for value in row]
                for row in sorted(db.execute('SELECT * FROM "' + name.replace('"','""') + '"').fetchall(), key=repr)] for name in tables}
    return result


def load(path):
    reuse._TEST_TYPES['_AssociationSource'] = association_owner._AssociationSource
    reuse._TEST_TYPES['_AssociationInstallation'] = association_owner._AssociationInstallation
    return reuse._unpack(json.loads(Path(path).read_text()))


def run(mode, path):
    state = load(path)
    if mode == 'hold-guard':
        binding = next(b for b in state['run'].databases if b.role == 'transport')
        with closing(transport._ProgramTransportStore.open_existing(binding.path, approved_root=state['run'].store_root)) as store:
            with store._completion_guard():
                print(json.dumps({'held': True, 'pid': os.getpid()}), flush=True)
                sys.stdin.readline()
        return
    wire = bridge._Wire(); wire.outputs = state['outputs']
    wire.scheduler = (153, b'', b'qstat: Unknown Job Id Error 123.server\n')
    selected = reuse._next_process_installation(state['installation']) if mode == 'resume-next' else state['installation']
    phase = mode.removeprefix('crash-') if mode.startswith('crash-') else ''
    peer_processes = []
    def peer(scope, invocation):
        op = invocation.operation.name
        append(str(path) + '.wire.jsonl', {'pid': os.getpid(), 'phase': mode, 'operation': op})
        assert op in READS, 'recovery attempted non-read operation: ' + op
        if mode == 'timeout':
            def local_process(command, **kwargs):
                assert command[0] == '/usr/bin/ssh'
                proc = REAL_POPEN([sys.executable, '-c', 'import sys,time;sys.stdin.buffer.read();time.sleep(120)'], **kwargs)
                peer_processes.append(proc)
                append(str(path) + '.peer.jsonl', {'pid': proc.pid, 'parent': os.getpid(), 'event': 'started'})
                return proc
            with patch.object(_driver.subprocess, 'Popen', side_effect=local_process):
                value = REAL_RUN(_driver._SubprocessRTWinDriver(), scope, invocation)
            for proc in peer_processes:
                assert proc.poll() is not None
                append(str(path) + '.peer.jsonl', {'pid': proc.pid, 'event': 'reaped', 'returncode': proc.returncode, 'completion_status': value[3]})
            return value
        value = wire.run(scope, invocation)
        if phase == 'wire': os._exit(17)
        return value
    with ExitStack() as stack:
        for owner, name, value in [(rtwin, '_FIXED_PUBLISHER_INSTALLATION', state['original']),
                (rtwin, '_FIXED_COLLECTION_INSTALLATION', selected), (controller, '_FIXED_COLLECTION_RUN', state['run']),
                (association_owner, '_FIXED_ASSOCIATION_SOURCE', state['association_source'])]:
            stack.enter_context(patch.object(owner, name, value))
        stack.enter_context(patch.object(_driver._SubprocessRTWinDriver, '_run', side_effect=peer))
        stack.enter_context(patch.object(_driver.subprocess, 'Popen', side_effect=AssertionError('no live process')))
        stack.enter_context(patch.object(execution, 'execute_once', side_effect=AssertionError('no submit')))
        stack.enter_context(patch.object(runtime, '_prepare_program_execution', side_effect=AssertionError('no prepare')))
        stack.enter_context(patch.object(p._ProgramExecutionSnapshotService, 'prepare', side_effect=AssertionError('no new snapshot')))
        old_obs, old_result, old_advance = core.SQLiteRuntimeStore.append_observation, core.SQLiteRuntimeStore.append_result, core.SQLiteRuntimeStore.advance_attempt
        def observation(store, record):
            if (phase == 'before-audit' and record.observation_type == runtime._COLLECTION_START) or (phase == 'physical' and record.observation_type == transport._RECEIPT_TYPE): os._exit(17)
            old_obs(store, record)
            if (phase == 'audit' and record.observation_type == runtime._COLLECTION_START) or (phase == 'assessment' and record.observation_type == runtime._COMPLETION_ASSESSMENT): os._exit(17)
        def result(store, record):
            if phase == 'before-result': os._exit(17)
            old_result(store, record)
            if phase == 'result': os._exit(17)
        def advance(store, *args):
            if phase == 'before-transition': os._exit(17)
            value = old_advance(store, *args)
            if phase == 'transition': os._exit(17)
            return value
        stack.enter_context(patch.object(core.SQLiteRuntimeStore, 'append_observation', observation))
        stack.enter_context(patch.object(core.SQLiteRuntimeStore, 'append_result', result))
        stack.enter_context(patch.object(core.SQLiteRuntimeStore, 'advance_attempt', advance))
        try:
            value = controller._resume_fixed_publisher_collection()
            answer = {'verdict': value.data['verdict'], 'diagnostic': value.data['diagnostic'], 'assessment_id': value.observation_id, 'result_id': value.data['evidence_result_id']}
        except (TransportBoundaryError, execution.ExecutionValueError) as exc:
            answer = {'rejected': str(exc)}
        answer.update(pid=os.getpid(), persisted=persisted(state))
        print(json.dumps(answer), flush=True)


if __name__ == '__main__':
    mode, path = sys.argv[1:]
    try:
        if mode in {'build-opt', 'build-freq'}: build(mode[6:], path)
        else: run(mode, path)
    except BaseException:
        import traceback
        traceback.print_exc(); sys.stderr.flush()
        os._exit(2)  # Preserve failure evidence too.
