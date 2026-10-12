"""Real local initialization crashes and restart, with no computational peer."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.study import _runtime_initialization as runtime
from auto_g16.study._model import StudyError, encode, digest
from auto_g16.study._files import Directory
from auto_g16.transport._canonical import TransportBoundaryError
from auto_g16.study.service import operate
from tests.v3.study.test_fresh import sample


def inventory(root):
    """Retain file identity/content and directory identity across appended suffixes."""
    values = {}
    for p in root.rglob('*'):
        info = p.lstat()
        payload = os.readlink(p) if p.is_symlink() else (
            None if p.is_dir() else (info.st_mtime_ns, digest(p.read_bytes())))
        values[str(p.relative_to(root))] = (info.st_ino, payload)
    return values

CHILD = r'''
import json,os,sys
from unittest.mock import patch
from auto_g16.study import _runtime_initialization as r
from auto_g16.study._files import Directory
source,root,action,point,phase,log=sys.argv[1:]
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen': raise AssertionError('effect forbidden')
sys.addaudithook(audit)
def stop(name,when):
 if point==name and phase==when:
  os.write(2,json.dumps(dict(pid=os.getpid(),point=name,phase=when)).encode());os._exit(78)
original_publish=Directory.publish
original_create=r._create_store
def publish(self,name,raw):
 stop(name,'before');original_publish(self,name,raw);stop(name,'after')
def create(directory,index,value):
 name='store-'+r.ROLES[index];stop(name,'before')
 with open(log,'a') as f: f.write(name+'\n');f.flush();os.fsync(f.fileno())
 original_create(directory,index,value);stop(name,'after')
with patch.object(Directory,'publish',publish),patch.object(r,'_create_store',create):
 try:
  result=(r.initialize_local if action=='initialize' else r.inspect_local)(source,root)
 except Exception as e:
  print(json.dumps({'error':str(e),'type':type(e).__name__}));sys.exit(2)
 print(json.dumps(result))
'''


class RuntimeInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.destination = self.root / 'runtimes'; self.destination.mkdir()
        self.request = self.root / 'request.json'; self.request.write_bytes(encode(sample()))
        self.created = operate('create', str(self.source), request_path=str(self.request),
                               request_sha256=digest(self.request.read_bytes()))
        self.target = self.destination / self.created['study_id']
        self.log = self.root / 'creators.log'

    def call(self, write=True):
        with patch('socket.socket', side_effect=AssertionError('socket')), \
                patch('subprocess.Popen', side_effect=AssertionError('child')), \
                patch('auto_g16.execution.execute_once', side_effect=AssertionError('submit')):
            return (runtime.initialize_local if write else runtime.inspect_local)(
                str(self.source), str(self.destination))

    def child(self, action='initialize', point='', phase='', *, source=None, root=None, log=None):
        return subprocess.run([sys.executable, '-B', '-c', CHILD, str(source or self.source),
            str(root or self.destination), action, point, phase, str(log or self.log)],
            capture_output=True, text=True, timeout=30)

    def test_real_four_owner_roundtrip_and_repeat_do_not_write(self):
        first = self.child()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result['state'], 'local-initialized')
        self.assertEqual(len(result['journal']), 10)
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['installation_state'], 'uninstalled')
        before = inventory(self.root)
        for write in (False, True):
            self.assertEqual(self.call(write), result)
            self.assertEqual(inventory(self.root), before)
        self.assertEqual(self.log.read_text().splitlines(), ['store-' + role for role in runtime.ROLES])
        self.assertEqual(operate('recover', str(self.source))['data']['execution_readiness']['state'], 'blocked')
        with self.assertRaisesRegex(StudyError, 'execution-contract-not-frozen'):
            operate('run', str(self.source))
        self.assertEqual(inventory(self.root), before)

    def test_actual_child_exit_at_each_event_store_and_binding(self):
        points = [*runtime.FILES, *('store-' + role for role in runtime.ROLES), 'binding.json']
        for point in points:
            for phase in ('before', 'after'):
                with self.subTest(point=point, phase=phase), tempfile.TemporaryDirectory(dir=self.root) as t:
                    case = Path(t); source=case/'source';source.mkdir();root=case/'root';root.mkdir();log=case/'calls'
                    operate('create', str(source), request_path=str(self.request),
                            request_sha256=digest(self.request.read_bytes()))
                    crashed = self.child(point=point, phase=phase, source=source, root=root, log=log)
                    self.assertEqual(crashed.returncode, 78, crashed.stdout + crashed.stderr)
                    observed = inventory(root)
                    inspection = self.child('inspect', source=source, root=root, log=log)
                    self.assertEqual(inventory(root), observed)
                    if point == runtime.FILES[0] and phase == 'before':
                        self.assertEqual(inspection.returncode, 2)
                        stopped = self.child(source=source, root=root, log=log)
                        self.assertEqual(stopped.returncode, 2)
                        self.assertEqual(inventory(root), observed)
                        continue
                    self.assertEqual(inspection.returncode, 0, inspection.stdout + inspection.stderr)
                    resumed = self.child(source=source, root=root, log=log)
                    self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                    self.assertEqual(log.read_text().splitlines(), ['store-' + role for role in runtime.ROLES])
                    after = inventory(root)
                    for name, content in observed.items():
                        self.assertEqual(after[name], content, name)
                    replay = self.child(source=source, root=root, log=log)
                    self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
                    self.assertEqual(inventory(root), after)

    def test_partial_files_and_unexpected_prefix_are_retained(self):
        for role, content in [('core', b''), ('approval', b'partial'), ('transport', b''), ('project', b'bad')]:
            with self.subTest(role=role), tempfile.TemporaryDirectory(dir=self.root) as t:
                case = Path(t); root=case/'root';root.mkdir();log=case/'calls'
                stopped = self.child(point='store-'+role, phase='before', root=root, log=log)
                self.assertEqual(stopped.returncode, 78)
                target = root / self.created['study_id']
                filename = runtime.DATABASES[runtime.ROLES.index(role)]
                (target/filename).write_bytes(content)
                before = inventory(root)
                for action in ('inspect','initialize'):
                    result = self.child(action, root=root, log=log)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(inventory(root), before)
        self.call()
        (self.target/'unexpected').write_bytes(b'preserve')
        before=inventory(self.root)
        with self.assertRaisesRegex(StudyError, 'initialization-unresolved'):
            self.call()
        self.assertEqual(inventory(self.root),before)

    def test_owner_inspectors_reject_sidecars_missing_alias_and_wrong_identity_without_changes(self):
        self.call()
        for index, name in enumerate(runtime.DATABASES):
            owner=runtime.OWNERS[index];path=self.target/name
            kwargs=dict(approved_root=str(self.target),expected_file_identity=(path.stat().st_dev,path.stat().st_ino))
            if index==0: kwargs['expected_records']=runtime.model.records(sample())
            for suffix in ('-journal','-wal','-shm'):
                sidecar=path.with_name(name+suffix);sidecar.write_bytes(b'')
                before=inventory(self.root)
                with self.subTest(owner=name,sidecar=suffix), self.assertRaises(Exception):
                    owner.inspect_initialization(str(path),**kwargs)
                self.assertEqual(inventory(self.root),before)
                sidecar.unlink()  # Disposable synthetic fixture only.
            wrong=dict(kwargs,expected_file_identity=(True,1))
            with self.assertRaises(Exception):owner.inspect_initialization(str(path),**wrong)
            alias=self.target/(name+'.alias');alias.symlink_to(path)
            with self.assertRaises(Exception):owner.inspect_initialization(str(alias),**kwargs)
            alias.unlink()
            missing=self.target/(name+'.missing')
            with self.assertRaises(Exception):owner.inspect_initialization(str(missing),**kwargs)
            self.assertFalse(missing.exists())

    def test_nonempty_native_tables_cannot_be_adopted_or_reinitialized(self):
        self.call()
        # An extra valid Core row is not a pristine six-record database.
        from auto_g16.core import SQLiteRuntimeStore
        from auto_g16.core.models import Project
        with SQLiteRuntimeStore(self.target/'core.sqlite3') as store:
            store.store_project(Project(project_id='05e36128-652a-4e77-a0d3-81a95bb47119'))
        before=inventory(self.root)
        with self.assertRaisesRegex(StudyError,'initialization-unresolved'):self.call()
        self.assertEqual(inventory(self.root),before)

    def test_native_transport_guard_and_real_process_study_lock(self):
        self.call()
        with Directory(str(self.target/'initialization'),write=True):
            blocked=self.child('inspect')
            self.assertEqual(blocked.returncode,2)
            self.assertEqual(json.loads(blocked.stdout)['error'],'busy')
            from auto_g16.transport.program import _directory_guard
            # Distinct directory inode: the native guard can actually acquire its lock.
            with _directory_guard(str(self.target/'transport.sqlite3'),str(self.target)):
                pass
        self.assertEqual(self.call(False)['state'],'local-initialized')

    def test_missing_inspection_and_invalid_roots_have_no_effect(self):
        before=inventory(self.root)
        with self.assertRaisesRegex(StudyError,'not-found'):self.call(False)
        self.assertEqual(before,inventory(self.root))
        for root in (str(self.source),str(self.source/'inside'),str(self.root),'.'):
            with self.subTest(root=root),self.assertRaises(StudyError):
                runtime.initialize_local(str(self.source),root)
        self.assertEqual(before,inventory(self.root))

    def test_exit_drift_is_not_a_success(self):
        self.call()
        original=runtime._response
        def drift(*args,**kwargs):
            response=original(*args,**kwargs)
            (self.target/'operations'/'unexpected').write_bytes(b'preserve')
            return response
        with patch.object(runtime,'_response',drift),self.assertRaises(StudyError):self.call(False)
        self.assertEqual((self.target/'operations'/'unexpected').read_bytes(),b'preserve')

    def test_later_owner_and_response_cannot_change_prior_database_unnoticed(self):
        for when in ('later-owner', 'response'):
            with self.subTest(when=when), tempfile.TemporaryDirectory(dir=self.root) as t:
                root=Path(t)/'runtimes';root.mkdir();log=Path(t)/'calls'
                self.assertEqual(self.child(root=root,log=log).returncode,0)
                target=root/self.created['study_id']/'approval.sqlite3'
                original=runtime._inspect if when=='later-owner' else runtime._response
                def changed(*args,**kwargs):
                    result=original(*args,**kwargs)
                    if when=='response' or args[1]==3:
                        with target.open('ab') as f:f.write(b'changed')
                    return result
                with patch.object(runtime,'_inspect' if when=='later-owner' else '_response',changed), \
                        self.assertRaisesRegex(StudyError,'initialization-unresolved'):
                    runtime.inspect_local(str(self.source),str(root))

    def test_owner_close_time_content_drift_rejects(self):
        self.call()
        for index in (0,3):
            with self.subTest(role=runtime.ROLES[index]):
                owner=runtime.OWNERS[index];path=self.target/runtime.DATABASES[index]
                original=owner.close;changed=[]
                def close(store):
                    original(store)
                    if not changed:
                        changed.append(True)
                        with path.open('ab') as f:f.write(b'close-drift')
                kwargs=dict(approved_root=str(self.target),expected_file_identity=(path.stat().st_dev,path.stat().st_ino))
                if index==0:kwargs['expected_records']=runtime.model.records(sample())
                with patch.object(owner,'close',close),self.assertRaises(Exception):
                    owner.inspect_initialization(str(path),**kwargs)
                self.assertTrue(changed)

    def test_generator_version_format_rejects_without_repair(self):
        stopped=self.child(point=runtime.FILES[0],phase='after')
        self.assertEqual(stopped.returncode,78)
        path=self.target/'initialization'/runtime.FILES[0]
        original=json.loads(path.read_bytes())
        for version in ('', 'not-a-version'):
            with self.subTest(version=version):
                original['data']['core_image_generator']['python']=version
                path.write_bytes(encode(original))
                before=inventory(self.root)
                with self.assertRaisesRegex(StudyError,'initialization-unresolved'):self.call(False)
                self.assertEqual(inventory(self.root),before)

    def test_descriptor_creators_never_write_replacement_paths(self):
        from auto_g16 import _initialization_file as files
        for index in (1,2,3):
            for fault in ('parent-at-reserve', 'parent-before-write', 'target-before-write', 'parent-during-write', 'exit-content'):
                with self.subTest(role=runtime.ROLES[index],fault=fault), tempfile.TemporaryDirectory(dir=self.root) as t:
                    base=Path(t);root=base/'runtime';root.mkdir();old=base/'retained'
                    name=runtime.DATABASES[index];path=root/name
                    with Directory(str(root),lock=False) as directory: chain=directory.chain
                    original_open=files.os.open;original_write=files.os.write;original_publish=files._ReservedFile.publish
                    mutated=[]
                    def replace_parent():
                        root.rename(old);root.mkdir();(root/'sentinel').write_bytes(b'unchanged')
                        mutated.append(True)
                    def opened(file,flags,*args,**kwargs):
                        if fault=='parent-at-reserve' and flags & os.O_CREAT and not mutated:replace_parent()
                        return original_open(file,flags,*args,**kwargs)
                    def written(fd,raw):
                        if fault=='parent-during-write' and not mutated:
                            n=original_write(fd,raw[:512]);replace_parent();return n
                        return original_write(fd,raw)
                    def published(target,raw):
                        if fault=='parent-before-write':replace_parent()
                        elif fault=='target-before-write':
                            path.rename(base/'original.sqlite3');path.write_bytes(b'replacement');mutated.append(True)
                        result=original_publish(target,raw)
                        if fault=='exit-content':
                            with path.open('ab') as f:f.write(b'exit-drift')
                            mutated.append(True)
                        return result
                    with patch.object(files.os,'open',opened),patch.object(files.os,'write',written), \
                            patch.object(files._ReservedFile,'publish',published),self.assertRaises(Exception):
                        runtime.OWNERS[index].create_initialization_at(str(path),approved_root=str(root),parent_chain=chain)
                    self.assertTrue(mutated)
                    if fault.startswith('parent-'):
                        self.assertEqual({p.name for p in root.iterdir()},{'sentinel'})
                        self.assertEqual((root/'sentinel').read_bytes(),b'unchanged')
                        self.assertTrue((old/name).exists())
                        self.assertEqual((old/name).stat().st_size,512 if fault=='parent-during-write' else 0)
                    elif fault=='target-before-write':
                        self.assertEqual(path.read_bytes(),b'replacement')
                        self.assertEqual((base/'original.sqlite3').stat().st_size,0)
                    else:self.assertTrue(path.read_bytes().endswith(b'exit-drift'))

    def test_descriptor_creators_short_write_and_failures_preserve_reserved_file(self):
        from auto_g16 import _initialization_file as files
        for index in (1,2,3):
            for fault in ('short-write','serialize','interrupted-write','fsync'):
                with self.subTest(role=runtime.ROLES[index],fault=fault), tempfile.TemporaryDirectory(dir=self.root) as t:
                    root=Path(t);path=root/runtime.DATABASES[index]
                    with Directory(str(root),lock=False) as directory:chain=directory.chain
                    original_write=files.os.write;count=[]
                    def written(fd,raw):
                        if fault=='interrupted-write' and count:raise KeyboardInterrupt('injected')
                        count.append(True);return original_write(fd,raw[:512])
                    from contextlib import ExitStack
                    with ExitStack() as stack:
                        if fault in ('short-write','interrupted-write'):stack.enter_context(patch.object(files.os,'write',written))
                        if fault=='serialize':stack.enter_context(patch.object(files,'serialize_initial',side_effect=RuntimeError('serialize failed')))
                        if fault=='fsync':stack.enter_context(patch.object(files.os,'fsync',side_effect=OSError('fsync failed')))
                        if fault=='short-write':
                            result=runtime.OWNERS[index].create_initialization_at(str(path),approved_root=str(root),parent_chain=chain)
                            self.assertEqual(result['sha256'],digest(path.read_bytes()))
                            self.assertGreater(len(count),1)
                        else:
                            expected = TransportBoundaryError if index == 2 and fault == 'fsync' else (RuntimeError,OSError,KeyboardInterrupt)
                            with self.assertRaises(expected) as caught:
                                runtime.OWNERS[index].create_initialization_at(str(path),approved_root=str(root),parent_chain=chain)
                            if index == 2 and fault == 'fsync':self.assertIsInstance(caught.exception.__cause__,OSError)
                    self.assertTrue(path.exists())
                    if fault=='serialize':self.assertEqual(path.stat().st_size,0)
                    if fault=='interrupted-write':self.assertEqual(path.stat().st_size,512)
                    before=inventory(root)
                    with self.assertRaises(TransportBoundaryError if index == 2 else FileExistsError) as caught:
                        runtime.OWNERS[index].create_initialization_at(str(path),approved_root=str(root),parent_chain=chain)
                    if index == 2:self.assertIsInstance(caught.exception.__cause__,FileExistsError)
                    self.assertEqual(inventory(root),before)
                    if fault=='short-write':
                        state=runtime.OWNERS[index].inspect_initialization(str(path),approved_root=str(root),
                            expected_file_identity=(path.stat().st_dev,path.stat().st_ino))
                        self.assertEqual(state['role'],runtime.ROLES[index])

    def test_descriptor_creators_reject_content_drift_during_final_readback(self):
        from auto_g16 import _initialization_file as files
        for index in (1,2,3):
            with self.subTest(role=runtime.ROLES[index]), tempfile.TemporaryDirectory(dir=self.root) as t:
                root=Path(t);path=root/runtime.DATABASES[index]
                with Directory(str(root),lock=False) as directory:chain=directory.chain
                original_read=files.os.pread;changed=[]
                def read_then_replace(fd,count,offset):
                    raw=original_read(fd,count,offset)
                    if offset+len(raw)==os.fstat(fd).st_size and not changed:
                        os.pwrite(fd,b'changed!',0);os.fsync(fd);changed.append(True)
                    return raw
                with patch.object(files.os,'pread',read_then_replace),self.assertRaises(files.InitialFileError):
                    runtime.OWNERS[index].create_initialization_at(str(path),approved_root=str(root),parent_chain=chain)
                self.assertTrue(changed)
                self.assertEqual(path.read_bytes()[:8],b'changed!')
