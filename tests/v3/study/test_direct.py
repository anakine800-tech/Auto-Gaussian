"""Real local process faults with explicitly synthetic source verification only."""
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
from auto_g16.study._model import StudyError, core_image, decode, digest, encode, request
from auto_g16.study.service import FILES, operate


SYNTHETIC = {'fixture': 'local-persistence-only-no-scientific-evidence'}


def sample():
    return dict(schema='auto-g16-direct-study-request/1',
        creation_key='71768e85-d6e7-4c5e-9cc7-a156ce57d86a', title='local fault fixture',
        initial_xtb=dict(input_sha256='a' * 64, charge=0, multiplicity=1, cores=4,
                         memory_mb=12288, walltime_seconds=1800, queue='batch'),
        catalog=dict(path='/fixture', parent_chain=[[1, 1]], file_identity=[1, 2],
                     sha256='b' * 64, size_bytes=10))


def inventory(directory):
    return {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, digest(p.read_bytes()))
            for p in directory.iterdir()}


CHILD = '''
import os,sys
from unittest.mock import patch
from auto_g16.study._files import Directory
from auto_g16.study._model import encode,StudyError
from auto_g16.study.service import operate
original=Directory.publish
count=0
def publish(self,name,raw):
 global count
 count+=1
 if sys.argv[4]=='before' and count==int(sys.argv[3]):
  os.write(2,encode({'pid':os.getpid(),'phase':'before','publication':name}));os._exit(73)
 original(self,name,raw)
 if sys.argv[4]=='after' and count==int(sys.argv[3]):
  os.write(2,encode({'pid':os.getpid(),'phase':'after','publication':name}));os._exit(73)
with patch('auto_g16.study._catalog.verify',return_value={'fixture':'local-persistence-only-no-scientific-evidence'}),patch.object(Directory,'publish',publish):
 try:
  result=operate(sys.argv[5],sys.argv[1],**({'request_path':sys.argv[2],'request_sha256':sys.argv[6]} if sys.argv[5]=='create' else {}))
 except StudyError as e:
  print(encode({'error':str(e)}).decode());sys.exit(2)
 print(encode(result).decode())
'''


class DirectStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / 'study'
        self.directory.mkdir()
        self.request_path = self.root / 'request.json'
        self.request_path.write_bytes(encode(sample()))
        self.sha = digest(self.request_path.read_bytes())

    def call(self, command='create'):
        with patch('auto_g16.study._catalog.verify', return_value=SYNTHETIC):
            return operate(command, str(self.directory), **(
                dict(request_path=str(self.request_path), request_sha256=self.sha) if command == 'create' else {}))

    def child(self, command, point=0, phase='none'):
        return subprocess.run([sys.executable, '-B', '-c', CHILD, str(self.directory),
            str(self.request_path), str(point), phase, command, self.sha], capture_output=True, text=True, timeout=20)

    def test_create_all_read_commands_and_idempotence(self):
        first = self.call()
        before = inventory(self.directory)
        for command in ('review', 'status', 'query', 'audit', 'recover', 'create'):
            result = self.call(command)
            self.assertEqual(result['study_id'], first['study_id'])
            self.assertEqual(result['data']['local']['local_attempt_state'], 'PLANNED')
            self.assertEqual(before, inventory(self.directory))
        with self.assertRaisesRegex(StudyError, 'execution-contract-not-frozen'):
            self.call('run')
        self.assertEqual(before, inventory(self.directory))

    def test_actual_child_process_interruptions_all_publications(self):
        # Five publications: intent, SQLite image, CORE event, SOURCES event, COMPLETE.
        for point in range(1, 6):
            for phase in ('before', 'after'):
                with self.subTest(point=point, phase=phase):
                    self.directory = self.root / f'fault-{point}-{phase}'
                    self.directory.mkdir()
                    stopped = self.child('create', point, phase)
                    self.assertEqual(stopped.returncode, 73, stopped.stderr + stopped.stdout)
                    before = inventory(self.directory)
                    read = self.child('recover')
                    self.assertEqual(read.returncode, 2 if point == 1 and phase == 'before' else 0,
                                     read.stderr + read.stdout)
                    self.assertEqual(before, inventory(self.directory))
                    resumed = self.child('create')
                    self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
                    result = json.loads(resumed.stdout)
                    self.assertEqual(result['status'], 'historical-reuse-complete')
                    self.assertEqual(result['data']['local']['local_attempt_state'], 'PLANNED')
                    after = inventory(self.directory)
                    self.assertEqual(self.child('create').returncode, 0)
                    self.assertEqual(after, inventory(self.directory))
                    for name, evidence in before.items():
                        self.assertEqual(after[name], evidence)
                    print('DIRECT_STUDY_PROCESS_FAULT ' + json.dumps(dict(
                        scope='synthetic-source-local-persistence-only', point=point, phase=phase,
                        process=json.loads(stopped.stderr), termination_returncode=stopped.returncode,
                        recovery_returncode=read.returncode, recovered_without_writes=True,
                        resume_returncode=resumed.returncode, identities=result['data']['local']['identities'],
                        attempt_state=result['data']['local']['local_attempt_state'],
                        before=before, after=after, repeated_create_zero_write=True), sort_keys=True), flush=True)

    def test_real_concurrent_process_lock(self):
        with Directory(str(self.directory), write=True):
            blocked = self.child('create')
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertEqual(json.loads(blocked.stdout), {'error': 'busy'})
        self.assertEqual(inventory(self.directory), {})

    def test_partial_write_retained_without_retry(self):
        for name in ('0001-intent.json', 'core.sqlite3'):
            with self.subTest(name=name):
                self.directory = self.root / name.replace('.', '-')
                self.directory.mkdir()
                if name == 'core.sqlite3':
                    self.assertEqual(self.child('create', 2, 'before').returncode, 73)
                (self.directory / name).write_bytes(b'{partial')
                before = inventory(self.directory)
                for command in ('recover', 'create'):
                    with self.assertRaises(StudyError):
                        self.call(command)
                    self.assertEqual(before, inventory(self.directory))

    def test_unacknowledged_foreign_image_rejected(self):
        self.assertEqual(self.child('create', 3, 'before').returncode, 73)
        with (self.directory / 'core.sqlite3').open('ab') as stream:
            stream.write(b'foreign')
        before = inventory(self.directory)
        with self.assertRaisesRegex(StudyError, 'initialization-unresolved'):
            self.call()
        self.assertEqual(before, inventory(self.directory))

    def test_changed_source_digest_and_request_fail_closed(self):
        self.call()
        before = inventory(self.directory)
        with patch('auto_g16.study._catalog.verify', return_value={'changed': True}):
            with self.assertRaises(StudyError):
                operate('recover', str(self.directory))
        other = sample(); other['title'] = 'changed'
        self.request_path.write_bytes(encode(other)); self.sha = digest(encode(other))
        with self.assertRaisesRegex(StudyError, 'invalid-request'):
            self.call()
        self.assertEqual(before, inventory(self.directory))

    def test_unknown_file_gaps_symlink_hardlink_and_clone_rejected(self):
        self.call()
        original = self.directory
        for mode in ('unknown', 'gap', 'symlink', 'hardlink', 'clone'):
            with self.subTest(mode=mode):
                target = self.root / mode; target.mkdir()
                for path in original.iterdir():
                    if mode == 'gap' and path.name == FILES[1]:
                        continue
                    if path.name == FILES[0] and mode == 'symlink':
                        (target / path.name).symlink_to(path)
                    elif path.name == FILES[0] and mode == 'hardlink':
                        os.link(path, target / path.name)
                    else:
                        (target / path.name).write_bytes(path.read_bytes())
                if mode == 'unknown': (target / 'unexpected').write_bytes(b'x')
                with self.assertRaises((StudyError, OSError)):
                    operate('recover', str(target))

    def test_request_rejects_nonfinite_duplicates_bool_ranges_extra(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'):
            with self.assertRaises(StudyError): decode(raw)
        for field, bad in [('cores', True), ('cores', 0), ('charge', 33), ('queue', 'x;run'),
                           ('multiplicity', 0), ('input_sha256', 'A' * 64)]:
            v = sample(); v['initial_xtb'][field] = bad
            with self.assertRaises(StudyError): request(encode(v), digest(encode(v)))
        v = sample(); v['handler'] = 'something'
        with self.assertRaises(StudyError): request(encode(v), digest(encode(v)))

    def test_directory_identity_and_file_changes_on_exit(self):
        with self.assertRaises(StudyError):
            with Directory(str(self.directory)) as directory:
                moved = self.root / 'moved'
                self.directory.rename(moved); self.directory.mkdir()
        self.directory = self.root / 'file-change'; self.directory.mkdir()
        (self.directory / 'evidence').write_bytes(b'old')
        with self.assertRaises(StudyError):
            with Directory(str(self.directory)) as directory:
                directory.read('evidence')
                (self.directory / 'evidence').write_bytes(b'new')

    def test_final_exit_inventory_rejects_late_unknown_file(self):
        self.call()
        original = Directory.read
        injected = []
        def read(directory, name, cap=64 * 1024 * 1024):
            result = original(directory, name, cap)
            if directory.expected_names is not None and not injected:
                injected.append(True)
                (self.directory / 'late-unknown').write_bytes(b'retained')
            return result
        with patch.object(Directory, 'read', read), self.assertRaises(StudyError):
            self.call('status')
        self.assertEqual((self.directory / 'late-unknown').read_bytes(), b'retained')

    def test_request_digest_cannot_be_relabelled_with_rehashed_journal(self):
        self.call()
        previous = None
        for i, name in enumerate(FILES):
            path = self.directory / name
            event = decode(path.read_bytes())
            event['previous_sha256'] = previous
            if i in (0, 3): event['data']['request_sha256'] = '0' * 64
            if i == 3: event['data']['source_event_sha256'] = previous
            path.write_bytes(encode(event)); previous = digest(encode(event))
        before = inventory(self.directory)
        with self.assertRaises(StudyError): self.call('recover')
        self.assertEqual(before, inventory(self.directory))

    def test_pretty_request_rejects_before_any_publication(self):
        self.request_path.write_bytes(json.dumps(sample(), indent=2).encode())
        self.sha = digest(self.request_path.read_bytes())
        with self.assertRaisesRegex(StudyError, 'invalid-request'): self.call()
        self.assertEqual(inventory(self.directory), {})


class MemoryExportTests(unittest.TestCase):
    def test_deterministic_native_image_and_idle_memory_export(self):
        self.assertEqual(core_image(sample()), core_image(sample()))

    def test_rejects_file_temp_attached_and_transaction(self):
        with tempfile.TemporaryDirectory() as root:
            for database in ('', str(Path(root) / 'file.db')):
                store = SQLiteRuntimeStore(database)
                try:
                    with self.assertRaises(Exception): store.export_memory_snapshot()
                finally: store.close()
        for statement in ("ATTACH DATABASE ':memory:' AS second", 'BEGIN'):
            store = SQLiteRuntimeStore(':memory:')
            try:
                store._connection.execute(statement)
                with self.assertRaises(Exception): store.export_memory_snapshot()
            finally: store.close()
