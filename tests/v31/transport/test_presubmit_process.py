"""Real local process termination and native replay; synthetic effects only."""
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.execution import _presubmit_recovery as recovery
from auto_g16.execution.program import _decode_program_review_semantics
from auto_g16.transport import program as transport
from auto_g16.transport._program_rtwin import _plain
from tests.v31.transport import test_presubmit_recovery as fixture_module
from tests.v31.transport import test_program_composition as composition


def _write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _process(mode, path):
    if mode == 'build':
        fixture = fixture_module.PreSubmitRecoveryTests()
        fixture.setUp()
        fixture.stop()
        _write(path, dict(database=str(fixture.database),
            transport=str(fixture.root / 'transport' / 'program.sqlite3'),
            semantics=_plain(fixture.snapshot._approval_semantics()),
            receipt=fixture.stopped, decision=fixture.decision))
        # Deliberately bypass Python cleanup; all committed stores survive.
        os._exit(0)
    value = json.loads(path.read_text())
    snapshot = _decode_program_review_semantics(value['semantics'])
    store = core.SQLiteRuntimeStore(value['database'])
    native = transport._ProgramTransportStore.open_existing(value['transport'],
        approved_root=Path(value['transport']).parent)
    driver = composition._Driver()
    forbidden = path.parent / ('forbidden-' + mode + '.json')
    def no_effect(*args, **kwargs):
        _write(forbidden, {'effect_attempted': True})
        raise AssertionError('recovery must not prepare, submit, or call a driver')
    append = core.SQLiteRuntimeStore.append_observation
    disposition = core.SQLiteRuntimeStore.reconcile_unknown
    claim = core.SQLiteRuntimeStore.record_submission_intent
    def replay_only(self, attempt_id, intent_id):
        # Native intent replay is required; a new or changed claim is forbidden.
        if attempt_id != snapshot.attempt_id or self.load_submission_intent(attempt_id) != intent_id:
            no_effect()
        result = claim(self, attempt_id, intent_id)
        if result is not core.SubmissionIntentClaim.REPLAY:
            no_effect()
        return result
    def record(self, observation):
        if observation.observation_type == recovery.PROOF and mode == 'before-proof':
            os._exit(73)
        append(self, observation)
        if observation.observation_type == recovery.PROOF and mode == 'after-proof':
            os._exit(73)
    def resolve(self, *args, **kwargs):
        state = disposition(self, *args, **kwargs)
        if mode == 'after-disposition':
            os._exit(73)
        return state
    try:
        with ExitStack() as guards:
            guards.enter_context(patch.object(driver, '_record', side_effect=no_effect))
            guards.enter_context(patch.object(subprocess, 'Popen', side_effect=no_effect))
            guards.enter_context(patch.object(socket.socket, 'connect', side_effect=no_effect))
            for name in ('allocate_workspace', 'stage_exact_file', 'submit_qsub_once',
                         'query_scheduler', 'reconcile_submission', 'stat_output', 'fetch_output'):
                if hasattr(driver, name):
                    guards.enter_context(patch.object(driver, name, side_effect=no_effect))
            guards.enter_context(patch.object(core.SQLiteRuntimeStore, 'record_submission_intent', replay_only))
            guards.enter_context(patch.object(core.SQLiteRuntimeStore, 'create_child_attempt', side_effect=no_effect))
            guards.enter_context(patch.object(core.SQLiteRuntimeStore, 'append_observation', record))
            guards.enter_context(patch.object(core.SQLiteRuntimeStore, 'reconcile_unknown', resolve))
            if mode != 'inspect':
                recovery.reconcile(store, snapshot=snapshot, program_transport_store=native,
                    driver=driver, stopped_receipt_id=value['receipt'], decision=value['decision'])
            observations = store.observations_for_attempt(snapshot.attempt_id)
            rows = native._connection.execute(
                'SELECT * FROM program_effect_physical_authority ORDER BY physical_effect_authority_id').fetchall()
            result = dict(state=store.attempt_state(snapshot.attempt_id).value,
                proof_ids=[o.observation_id for o in observations if o.observation_type == recovery.PROOF],
                receipts=[_plain(o.data) for o in observations if o.observation_type == transport._RECEIPT_TYPE],
                physical_rows=[[{'bytes_hex': v.hex()} if isinstance(v, bytes) else v
                                for v in row] for row in rows], driver_calls=len(driver.calls),
                attempt_ids=[a.attempt_id for a in store.list_attempts('task-1')],
                submission_intent=store.load_submission_intent(snapshot.attempt_id),
                result_ids=[r.result_id for r in store.results_for_attempt(snapshot.attempt_id)])
    finally:
        native.close()
        store.close()
    result['store_hashes'] = {key: sha256(Path(value[key]).read_bytes()).hexdigest()
                            for key in ('database', 'transport')}
    print(json.dumps(result, sort_keys=True), flush=True)


class PreSubmitProcessTests(unittest.TestCase):
    def test_crash_prefix_restarts_without_effects_or_duplicate_proof(self):
        retained = os.environ.get('AUTO_G16_PRESUBMIT_TEST_EVIDENCE_ROOT')
        if retained:
            root = Path(tempfile.mkdtemp(prefix='presubmit-', dir=retained)).resolve()
        else:
            scratch = tempfile.TemporaryDirectory()
            self.addCleanup(scratch.cleanup)
            root = Path(scratch.name).resolve()
        for phase in ('before-proof', 'after-proof', 'after-disposition'):
            with self.subTest(phase=phase):
                folder = root / phase
                folder.mkdir()
                path = folder / 'state.json'
                count = 0
                def child(mode):
                    nonlocal count
                    count += 1
                    env = dict(os.environ, TMPDIR=str(folder))
                    run = subprocess.run([sys.executable, '-B', '-m', 'tests.v31.transport.test_presubmit_process', mode, str(path)],
                        capture_output=True, text=True, env=env, timeout=30,
                        cwd=Path(__file__).resolve().parents[3])
                    _write(folder / f'process-{count:02d}.json', dict(mode=mode,
                        returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
                    self.assertEqual(run.returncode, 73 if mode == phase else 0, run.stdout + run.stderr)
                    return json.loads(run.stdout) if run.stdout else None
                child('build')
                before = child('inspect')
                self.assertEqual(before['state'], 'UNKNOWN')
                child(phase)
                stopped = child('inspect')
                self.assertEqual(stopped['state'], 'NOT_SUBMITTED' if phase == 'after-disposition' else 'UNKNOWN')
                self.assertEqual(len(stopped['proof_ids']), 0 if phase == 'before-proof' else 1)
                recovered = child('recover')
                self.assertEqual(recovered['state'], 'NOT_SUBMITTED')
                self.assertEqual(len(recovered['proof_ids']), 1)
                for key in ('receipts', 'physical_rows', 'attempt_ids', 'submission_intent', 'result_ids'):
                    self.assertEqual(recovered[key], before[key])
                self.assertFalse(any(r['operation'] == 'SUBMIT_QSUB_ONCE' for r in recovered['receipts']))
                self.assertEqual(recovered['driver_calls'], 0)
                self.assertEqual(recovered['attempt_ids'], ['attempt-1'])
                self.assertEqual(recovered['store_hashes']['transport'], before['store_hashes']['transport'])
                self.assertEqual(child('recover'), recovered)
                self.assertFalse(list(folder.glob('forbidden-*')))
                _write(folder / 'verified.json', {'phase': phase, 'result': recovered,
                    'claim': 'synthetic staging only; real SQLite, process exit, fresh recovery and replay'})


if __name__ == '__main__':
    if len(sys.argv) == 3:
        _process(sys.argv[1], Path(sys.argv[2]))
    else:
        unittest.main()
