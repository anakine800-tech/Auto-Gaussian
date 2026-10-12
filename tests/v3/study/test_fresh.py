"""Fresh native intake and real local restart evidence; zero remote science."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.study._files import Directory
from auto_g16.study._model import StudyError, digest, encode, identities as old_identities
from auto_g16.study._fresh_model import request, identities, PROTOCOL, THERMOCHEMISTRY, STAGES
from auto_g16.study.service import operate
from tests.v3.study.test_direct import inventory


def sample():
    # Deliberately only an intake fixture, not a scientifically accepted geometry.
    xyz = '14\nSYNTHETIC intake only\n' + ''.join(
        f'{element} {i}.0 0.0 0.0\n' for i, element in enumerate(['C'] * 4 + ['H'] * 10))
    return dict(schema='auto-g16-direct-study-request/2',
        creation_key='898630eb-c630-4477-a7b2-310e5ac9a5aa', title='fresh intake fixture',
        structure=dict(xyz_utf8=xyz, sha256=digest(xyz.encode()), charge=0, multiplicity=1),
        protocol=copy.deepcopy(PROTOCOL), thermochemistry=copy.deepcopy(THERMOCHEMISTRY),
        resources={stage: dict(cores=4, memory_mb=12288, queue='batch',
                    walltime_seconds=1800 if stage == 'xtb' else 3600) for stage in STAGES[:6]})


CHILD = '''
import os,sys
from unittest.mock import patch
from auto_g16.study._files import Directory
from auto_g16.study._model import encode
from auto_g16.study.__main__ import main
original=Directory.publish
count=0
def publish(self,name,raw):
 global count
 count+=1
 if sys.argv[4]=='before' and count==int(sys.argv[3]):
  os.write(2,encode({'pid':os.getpid(),'phase':'before','publication':name}));os._exit(74)
 original(self,name,raw)
 if sys.argv[4]=='after' and count==int(sys.argv[3]):
  os.write(2,encode({'pid':os.getpid(),'phase':'after','publication':name}));os._exit(74)
args=[sys.argv[5],'--directory',sys.argv[1]]
if sys.argv[5]=='create': args+=['--request',sys.argv[2],'--sha256',sys.argv[6]]
with patch.object(Directory,'publish',publish), patch('auto_g16.study._catalog.verify',side_effect=AssertionError('historical reader forbidden')):
 sys.exit(main(args))
'''


class FreshStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / 'study'; self.directory.mkdir()
        self.path = self.root / 'request.json'
        self.value = sample(); self.path.write_bytes(encode(self.value))
        self.sha = digest(self.path.read_bytes())

    def call(self, command='create'):
        with patch('auto_g16.study._catalog.verify', side_effect=AssertionError('historical reuse')), \
                patch('auto_g16.execution.execute_once', side_effect=AssertionError('submission')), \
                patch('socket.socket', side_effect=AssertionError('network')), \
                patch('subprocess.Popen', side_effect=AssertionError('subprocess')):
            return operate(command, str(self.directory), **(
                dict(request_path=str(self.path), request_sha256=self.sha) if command == 'create' else {}))

    def child(self, command, point=0, phase='none'):
        return subprocess.run([sys.executable, '-B', '-c', CHILD, str(self.directory),
            str(self.path), str(point), phase, command, self.sha], capture_output=True, text=True, timeout=20)

    def test_package_cli_and_native_creation_is_fresh_but_not_executed(self):
        first = subprocess.run([sys.executable, '-B', '-m', 'auto_g16.study', 'create',
            '--directory', str(self.directory), '--request', str(self.path), '--sha256', self.sha],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        result = json.loads(first.stdout)
        before = inventory(self.directory)
        self.assertEqual(result['status'], 'local-created')
        ids = identities(self.value)
        self.assertNotEqual(ids['project_id'], old_identities(self.value)['project_id'])
        data = result['data']
        self.assertEqual(data['mode'], 'fresh-execution')
        self.assertFalse(data['execution_performed'])
        self.assertFalse(data['fresh_execution_e2e'])
        self.assertEqual([s['stage'] for s in data['stages']], list(STAGES))
        self.assertEqual([s['materialized'] for s in data['stages']], [True] + [False] * 7)
        self.assertEqual(data['stages'][0]['core_state'], 'PLANNED')
        self.assertTrue(all(s['scientific_result'] is None for s in data['stages']))
        self.assertEqual(len(data['creation_snapshot']['records']), 6)
        self.assertIsNone(data['next_local_step'])
        with SQLiteRuntimeStore.read_snapshot(self.directory / 'core.sqlite3') as store:
            tables = [row[0] for row in store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            counts = {table: store._connection.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
                      for table in tables}
            self.assertEqual({table: n for table, n in counts.items() if n},
                {table: 1 for table in ('projects', 'workflow_runs', 'tasks',
                                       'calculation_plans', 'resource_specs', 'attempts')})
            stage = ids['stages']['xtb']
            self.assertEqual(store.load_project(ids['project_id']).project_id, ids['project_id'])
            self.assertEqual(store.load_calculation_plan(stage['plan_id']).intent['mode'], 'fresh-execution')
            self.assertIsNone(store.load_submission_intent(stage['attempt_id']))
            self.assertFalse(store.observations_for_attempt(stage['attempt_id']))
            self.assertFalse(store.results_for_attempt(stage['attempt_id']))
        for command in ('create', 'review', 'status', 'query', 'audit', 'recover'):
            read = self.call(command)
            self.assertEqual(read['data'], data)
            self.assertEqual(before, inventory(self.directory))

    def test_eight_real_child_interruptions_and_fresh_process_recovery(self):
        for point in range(1, 5):
            for phase in ('before', 'after'):
                with self.subTest(point=point, phase=phase):
                    self.directory = self.root / f'fault-{point}-{phase}'; self.directory.mkdir()
                    stopped = self.child('create', point, phase)
                    self.assertEqual(stopped.returncode, 74, stopped.stderr + stopped.stdout)
                    before = inventory(self.directory)
                    read = self.child('recover')
                    self.assertEqual(read.returncode, 2 if point == 1 and phase == 'before' else 0,
                                     read.stderr + read.stdout)
                    self.assertEqual(before, inventory(self.directory))
                    resumed = self.child('create')
                    self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
                    result = json.loads(resumed.stdout)
                    self.assertEqual(result['data']['identities'], identities(self.value))
                    self.assertFalse(result['data']['execution_performed'])
                    after = inventory(self.directory)
                    self.assertEqual(self.child('create').returncode, 0)
                    self.assertEqual(after, inventory(self.directory))
                    for name, evidence in before.items():
                        self.assertEqual(after[name], evidence)
                    print('FRESH_STUDY_PROCESS_FAULT ' + json.dumps(dict(point=point, phase=phase,
                        process=json.loads(stopped.stderr), exit_code=stopped.returncode,
                        recovery_exit=read.returncode, suffix_resume_exit=resumed.returncode,
                        before=before, after=after, identity=identities(self.value),
                        submission_intents=0, scope='local-creation-only-no-computational-E2E'),
                        sort_keys=True), flush=True)

    def test_real_concurrent_lock_no_publication(self):
        with Directory(str(self.directory), write=True):
            result = self.child('create')
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)['error'], 'busy')
        self.assertEqual(inventory(self.directory), {})

    def test_run_does_not_open_paths_or_initialize(self):
        with patch('auto_g16.study.service.Directory', side_effect=AssertionError('open')):
            with self.assertRaisesRegex(StudyError, 'execution-contract-not-frozen'):
                operate('run', '/nonexistent')
        self.assertEqual(inventory(self.directory), {})

    def test_bad_requests_reject_before_any_publication(self):
        cases = []
        for field, bad in [('charge', True), ('charge', 1), ('multiplicity', 2), ('sha256', '0' * 64)]:
            value = sample(); value['structure'][field] = bad; cases.append(value)
        for field, bad in [('temperature_k', True), ('frequency_scale_factor', 0.98),
                           ('entropy_model', 'unknown'), ('degeneracy_policy', 'double_twice'),
                           ('zpe_scale_factor', 0.98), ('interpolation_alpha', True), ('bav_kg_m2', 1e-43)]:
            value = sample(); value['thermochemistry'][field] = bad; cases.append(value)
        for bad in (8, True, 0):
            value = sample(); value['resources']['xtb']['cores'] = bad; cases.append(value)
        value = sample(); value['protocol']['gaussian']['method'] = 'B3LYP'; cases.append(value)
        value = sample(); value['protocol']['xtb']['optimization'] = 'tight'; cases.append(value)
        value = sample(); value['protocol']['crest']['normal_md_temperature_k'] = 298.15; cases.append(value)
        for extra in ('catalog', 'handler', 'driver', 'shell'):
            value = sample(); value[extra] = {}; cases.append(value)
        for xyz in ('0\nempty\n', sample()['structure']['xyz_utf8'] + 'H 0 0 0\n',
                    sample()['structure']['xyz_utf8'].replace('C 0.0', 'C nan'),
                    sample()['structure']['xyz_utf8'].replace('C 0.0', 'C 1e999'),
                    sample()['structure']['xyz_utf8'].replace('\nC ', '\nN ', 1)):
            value = sample(); value['structure'].update(xyz_utf8=xyz, sha256=digest(xyz.encode())); cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                self.path.write_bytes(encode(value)); self.sha = digest(self.path.read_bytes())
                with self.assertRaises(StudyError): self.call()
                self.assertEqual(inventory(self.directory), {})

    def test_changed_request_and_cross_version_directory_rejected(self):
        self.call(); before = inventory(self.directory)
        value = sample(); value['title'] = 'different'
        self.path.write_bytes(encode(value)); self.sha = digest(self.path.read_bytes())
        with self.assertRaises(StudyError): self.call()
        from tests.v3.study.test_direct import sample as old_sample
        self.path.write_bytes(encode(old_sample())); self.sha = digest(self.path.read_bytes())
        with self.assertRaises(StudyError): self.call()
        self.assertEqual(before, inventory(self.directory))

    def test_partial_unknown_and_missing_core_retained(self):
        for mode in ('partial-intent', 'partial-core', 'extra', 'missing-core', 'foreign-unacknowledged-core'):
            with self.subTest(mode=mode):
                self.directory = self.root / mode; self.directory.mkdir()
                if mode == 'partial-intent':
                    (self.directory / '0001-intent.json').write_bytes(b'{partial')
                elif mode in ('partial-core', 'foreign-unacknowledged-core'):
                    self.assertEqual(self.child('create', 3, 'before').returncode, 74)
                    with (self.directory / 'core.sqlite3').open('ab') as out: out.write(b'partial')
                else:
                    self.call()
                    if mode == 'extra': (self.directory / 'unexpected').write_bytes(b'evidence')
                    else: (self.directory / 'core.sqlite3').unlink()
                before = inventory(self.directory)
                for command in ('recover', 'create'):
                    with self.assertRaises(StudyError): self.call(command)
                    self.assertEqual(before, inventory(self.directory))

    def test_replaced_inode_symlink_hardlink_and_mixed_event_reject(self):
        for mode in ('inode', 'symlink', 'hardlink', 'schema'):
            with self.subTest(mode=mode):
                self.directory = self.root / mode; self.directory.mkdir(); self.call()
                path = self.directory / 'core.sqlite3'
                if mode == 'schema':
                    path = self.directory / '0002-core.json'
                    event = json.loads(path.read_bytes()); event['schema'] = 'auto-g16-direct-study-event/1'
                    path.write_bytes(encode(event))
                else:
                    saved = self.root / f'{mode}-saved'; path.rename(saved)
                    if mode == 'inode': path.write_bytes(saved.read_bytes())
                    elif mode == 'symlink': path.symlink_to(saved)
                    else: os.link(saved, path)
                for command in ('create', 'recover'):
                    with self.assertRaises((StudyError, OSError)): self.call(command)

    def test_source_inventory_checked_on_exit(self):
        self.call()
        original = Directory.read
        injected = []
        def read(directory, name, cap=64 * 1024 * 1024):
            result = original(directory, name, cap)
            if directory.expected_names is not None and not injected:
                injected.append(True); (self.directory / 'late-unknown').write_bytes(b'retained')
            return result
        with patch.object(Directory, 'read', read), self.assertRaises(StudyError): self.call('query')


if __name__ == '__main__':
    unittest.main()
