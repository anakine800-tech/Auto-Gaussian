"""Real installed local registration; all computation and network effects forbidden."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.v3.study.test_installation import Fixture

CHILD = r'''
import errno,json,os,sys,threading
from pathlib import Path
from unittest.mock import patch
from auto_g16.study import _registered_runtime as r
from auto_g16.study import _runtime_initialization as init
from auto_g16.study.service import operate
from auto_g16.study._model import encode,digest,plain,StudyError
from auto_g16.core import Project
from tests.v3.study.test_fresh import sample
root=Path(sys.argv[1]); mode=sys.argv[2]
source=root/'creation'/'study';source.mkdir()
request=root/'request.json';request.write_bytes(encode(sample()))
created=operate('create',str(source),request_path=str(request),request_sha256=digest(request.read_bytes()))
sid=created['study_id'];runtime=root/'runtime'/sid
init.initialize_local(str(source),str(root/'runtime'))
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('calculation or network effect')
sys.addaudithook(audit)
def inventory():
 return {str(p.relative_to(root)): (p.stat().st_ino,digest(p.read_bytes())) for p in root.rglob('*')
         if p.is_file() and 'objects' not in p.relative_to(root).parts and '__pycache__' not in p.parts}
if mode=='prepare':print('prepared local only');sys.exit(0)
if mode=='missing':
 (runtime/'core.sqlite3').rename(runtime/'core-retained.sqlite3')
 before=inventory()
 try:r.register_local(str(source))
 except Exception:pass
 else:raise AssertionError('missing accepted')
 assert inventory()==before and not list((root/'registry').iterdir())
 print('missing rejected without writes');sys.exit(0)
if mode in ('origin','model-origin'):
 (r.core if mode=='origin' else sys.modules[r.StudyError.__module__]).__spec__.origin='/foreign/module.py'
 try:r.register_local(str(source))
 except StudyError:pass
 else:raise AssertionError('foreign origin accepted')
 assert not list((root/'registry').iterdir())
 print('origin rejected');sys.exit(0)
if mode.startswith('crash-'):
 publish=r._Directory.publish
 def stopped(self,name,raw):
  if name.endswith('-runtime.json'):
   if mode=='crash-before':os._exit(78)
   if mode=='crash-partial':
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=self.fd)
    os.write(fd,raw[:31]);os.fsync(fd);os._exit(78)
  result=publish(self,name,raw)
  if name.endswith('-runtime.json'):os._exit(78)
  return result
 with patch.object(r._Directory,'publish',stopped):r.register_local(str(source))
 raise AssertionError('crash not reached')
if mode=='registry-close':
 real_open,real_close,real_write=os.open,os.close,os.write
 affected=[];closes=[]
 def opened(name,flags,*args,**kwargs):
  fd=real_open(name,flags,*args,**kwargs)
  if str(name).endswith('-runtime.json') and flags & os.O_WRONLY:affected.append(fd)
  return fd
 def written(fd,raw):
  if affected and fd==affected[0]:raise KeyboardInterrupt('original publication')
  return real_write(fd,raw)
 def closed(fd):
  if affected and fd==affected[0] and not closes:
   closes.append(fd);real_close(fd);raise OSError('private close detail')
  return real_close(fd)
 with patch.object(r.os,'open',opened),patch.object(r.os,'write',written),patch.object(r.os,'close',closed):
  try:r.register_local(str(source))
  except KeyboardInterrupt as error:
   assert str(error)=='original publication' and 'private' not in str(error.__notes__)
  else:raise AssertionError('original interruption lost')
 assert len(closes)==1 and r._FILE_UNRESOLVED
 def forbidden(name,*args,**kwargs):
  if str(name)=='0001-runtime.json':raise AssertionError('registry file reopened')
  return real_open(name,*args,**kwargs)
 with patch.object(r.os,'open',forbidden):
  try:r.register_local(str(source))
  except StudyError as error:assert str(error)=='registry-unresolved'
  else:raise AssertionError('registry resumed after unknown close')
 print('original preserved; registry unresolved');sys.exit(0)
if mode=='historical-generator':
 saved=json.loads((runtime/'initialization'/'0001-intent.json').read_bytes())['data']['core_image_generator']
 changed=dict(saved,python='3.99.1',sqlite='99.1.0',source_sha256={k:'0'*64 for k in saved['source_sha256']})
 assert changed!=saved
 before={str(p.relative_to(runtime)):p.read_bytes() for p in runtime.rglob('*') if p.is_file()}
 with patch.object(r.model,'generator',return_value=changed),patch.object(r.model,'core_image',side_effect=AssertionError('historical image regenerated')):
  entry=r.register_local(str(source))
  with r.open_registered(sid) as scope:assert scope.request['creation_key']==sample()['creation_key']
 assert before=={str(p.relative_to(runtime)):p.read_bytes() for p in runtime.rglob('*') if p.is_file()}
 print('historical generator retained; no regeneration');sys.exit(0)
registered=r.register_local(str(source))
assert set(registered)=={'registration','file_binding'}
assert registered['file_binding']['sha256']==digest(encode(registered['registration']))
before=inventory()
assert r.register_local(str(source))==registered and inventory()==before
if mode=='schema-facts':
 owners=(r.core.SQLiteRuntimeStore,r.approval.SQLiteApprovalStore,r.project._ProductionProvisioningJournal,r.transport._ProgramTransportStore)
 for cls in owners:
  unguarded=object.__new__(cls)
  try:unguarded.registration_schema_facts()
  except (r.core.RuntimeStoreError,r.approval.ApprovalStoreError,r.project.ExecutionValueError,r.transport.TransportBoundaryError):pass
  else:raise AssertionError('unguarded schema facts accepted')
 with r.open_registered(sid) as scope:
  stores=dict(scope.stores)
  receipts={receipt['data']['role']:receipt['data']['state'] for receipt in scope.initialization_receipts}
  for role,store in stores.items():
   facts=store.registration_schema_facts()
   assert set(facts)=={'schema_sha256','table_names'} and facts['schema_sha256']==receipts[role]['schema_sha256']
   assert type(facts['table_names']) is tuple and facts['table_names']==tuple(sorted(facts['table_names']))
   try:facts['schema_sha256']='0'*64
   except TypeError:pass
   else:raise AssertionError('mutable native schema facts')
   try:store.registration_schema_facts('caller SQL')
   except TypeError:pass
   else:raise AssertionError('schema arguments accepted')
   store._connection.execute('BEGIN')
   try:
    try:store.registration_schema_facts()
    except (r.core.RuntimeStoreError,r.approval.ApprovalStoreError,r.project.ExecutionValueError,r.transport.TransportBoundaryError):pass
    else:raise AssertionError('active transaction accepted')
    assert store._connection.in_transaction
   finally:store._connection.execute('ROLLBACK')
 for store in stores.values():
  try:store.registration_schema_facts()
  except (r.core.RuntimeStoreError,r.approval.ApprovalStoreError,r.project.ExecutionValueError,r.transport.TransportBoundaryError):pass
  else:raise AssertionError('closed schema handle accepted')
 print('native schema facts: bound immutable idle guarded only');sys.exit(0)
if mode=='prepare-two':
 second=root/'creation'/'second';second.mkdir()
 value=sample();value['creation_key']='31ef731c-87f2-40fd-bf3e-4a9b3b8df181';value['title']='second local fixture'
 raw=encode(value);path=root/'second-request.json';path.write_bytes(raw)
 operate('create',str(second),request_path=str(path),request_sha256=digest(raw))
 init.initialize_local(str(second),str(root/'runtime'))
 print('two initialized; first registered');sys.exit(0)
if mode.startswith('registry-bad-'):
 entry=root/'registry'/'0001-runtime.json';raw=entry.read_bytes();value=json.loads(raw)
 kind=mode.removeprefix('registry-bad-')
 if kind=='gap':entry.rename(entry.with_name('0002-runtime.json'))
 elif kind=='duplicate':
  value.update(sequence=2,previous_sha256=digest(raw));entry.with_name('0002-runtime.json').write_bytes(encode(value))
 elif kind=='hash':
  value['request_sha256']='0'*64;entry.write_bytes(encode(value))
 elif kind=='field':
  value['extra']='not allowed';entry.write_bytes(encode(value))
 elif kind=='sequence':
  value['sequence']=True;entry.write_bytes(encode(value))
 else:raise AssertionError(kind)
 before=inventory()
 try:
  with r.open_registered(sid):pass
 except (StudyError,r.installed.InstallationFactsError):pass
 else:raise AssertionError('bad registry accepted: '+kind)
 assert inventory()==before
 print('malformed registry rejected; no writes');sys.exit(0)
if mode.startswith('path-bad-'):
 kind=mode.removeprefix('path-bad-')
 if kind=='ancestor':
  (root/'creation').rename(root/'creation-retained');(root/'creation').mkdir()
 elif kind=='symlink':
  source.rename(root/'retained-study');source.symlink_to(root/'retained-study',target_is_directory=True)
 elif kind=='runtime-root':
  (root/'runtime').rename(root/'runtime-retained');(root/'runtime').mkdir()
 elif kind=='outside':
  outside=root/'outside';outside.mkdir()
 else:raise AssertionError(kind)
 before=inventory()
 try:
  if kind=='outside':r.register_local(str(outside))
  else:
   with r.open_registered(sid):pass
 except (StudyError,r.installed.InstallationFactsError,FileNotFoundError):pass
 except OSError as error:
  assert kind=='symlink' and error.errno in (errno.ENOTDIR,errno.ELOOP)
 else:raise AssertionError('bad path accepted: '+kind)
 assert inventory()==before
 print('path binding rejected; no writes');sys.exit(0)
if mode=='fork-scope':
 original_pid=os.getpid();touched=root/'inherited-sqlite-touched'
 class Forbidden:
  def __getattribute__(self,name):
   touched.write_text(name);raise AssertionError('inherited SQLite access')
 try:
  with r.open_registered(sid) as scope:
   child=os.fork()
   if child==0:
    stores=scope._values['stores']
    inherited_connections=[store._connection for store in stores.values()]
    for store in stores.values():store._connection=Forbidden()
    try:scope.stores
    except StudyError:pass
    else:os._exit(4)
    raise KeyboardInterrupt('child runtime unwind')
   _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0
   assert not touched.exists()
   scope.stores['core'].store_project(Project(project_id='parent-after-fork'))
 except KeyboardInterrupt:
  if os.getpid()!=original_pid:
   assert r._RETAINED and not touched.exists()
   os._exit(0)
  raise
 with r.open_registered(sid) as scope:
  assert scope.stores['core'].load_project('parent-after-fork').project_id=='parent-after-fork'
 print('fork scope rejected; parent reopened');sys.exit(0)
if mode=='registry-directory-close':
 real_close=os.close;target=[];calls=[];native=r._Directory.close
 def directory_close(directory):
  if directory.path==root/'registry' and not target:target.append(directory.fd)
  return native(directory)
 def close(fd):
  if target and fd==target[0] and not calls:
   calls.append(fd);real_close(fd);raise OSError('private directory close detail')
  return real_close(fd)
 with patch.object(r._Directory,'close',directory_close),patch.object(r.os,'close',close):
  try:
   with r.open_registered(sid):raise KeyboardInterrupt('original directory body')
  except KeyboardInterrupt as error:
   assert str(error)=='original directory body' and 'private' not in str(error.__notes__)
  else:raise AssertionError('original body lost')
 assert len(calls)==1
 physical=(root/'registry').stat();assert (os.getpid(),(physical.st_dev,physical.st_ino)) in r._FILE_UNRESOLVED
 try:r.register_local(str(source))
 except StudyError as error:assert str(error)=='registry-unresolved'
 else:raise AssertionError('unknown directory close reused')
 print('directory close unresolved; original retained');sys.exit(0)
if mode=='registry-extra':
 (root/'registry'/'unexpected').write_text('retained')
 before=inventory()
 try:
  with r.open_registered(sid):pass
 except StudyError:pass
 else:raise AssertionError('extra registry accepted')
 assert inventory()==before;print('registry rejected');sys.exit(0)
if mode in ('source-body','source-owner-exit'):
 def drift():
  target=Path(r.__file__).parent/'_model.py'
  target.write_bytes(target.read_bytes()+b'\n# synthetic exit drift\n')
 if mode=='source-body':
  try:
   with r.open_registered(sid):
    drift();raise KeyboardInterrupt('original consumer')
  except KeyboardInterrupt as error:
   assert str(error)=='original consumer' and error.__notes__
  else:raise AssertionError('body error lost')
 else:
  close=r.core.SQLiteRuntimeStore.close
  def changed(store):
   result=close(store)
   if 'runtime' in getattr(getattr(store,'_existing_mutable_guard',None),'path',''):
    drift()
   return result
  # Trigger after yielded use, not startup reader close.
  try:
   with r.open_registered(sid) as scope:
    guard=scope.stores['core']._existing_mutable_guard
    native=guard.close_sqlite
    def after(store):
     result=native(store);drift();return result
    guard.close_sqlite=after
  except (r.installed.InstallationFactsError,StudyError):pass
  else:raise AssertionError('owner-exit source drift accepted')
 print('source drift rejected');sys.exit(0)
if mode=='close-unknown':
 real=r.core.sqlite3.connect
 class Fault(r.core.sqlite3.Connection):
  def close(self):raise OSError('synthetic unknown close')
 def connect(*args,**kwargs):
  if 'core.sqlite3?mode=rw' in str(args[0]):kwargs['factory']=Fault
  return real(*args,**kwargs)
 with patch.object(r.core.sqlite3,'connect',connect):
  try:
   with r.open_registered(sid):pass
  except OSError:pass
  else:raise AssertionError('unknown close accepted')
 assert r._RETAINED
 # The Study lock remains held; registry lock is independently available.
 import fcntl
 pid=os.fork()
 if pid==0:
  fd=os.open(runtime/'initialization',os.O_RDONLY|os.O_DIRECTORY)
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:pass
  else:os._exit(3)
  fd=os.open(root/'registry',os.O_RDONLY|os.O_DIRECTORY)
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);os._exit(0)
 assert os.waitpid(pid,0)[1]==0
 print('Study retained, registry free');sys.exit(0)
with r.open_registered(sid) as scope:
 assert set(scope.stores)=={'core','approval','transport','project'}
 scope.stores['core'].store_project(Project(project_id='later-native-record'))
 if mode=='scope':
  failures=[]
  def other():
   try:scope.stores
   except StudyError:failures.append(True)
  thread=threading.Thread(target=other);thread.start();thread.join();assert failures==[True]
assert r.register_local(str(source))==registered
with r.open_registered(sid) as reopened:
 assert reopened.stores['core'].load_project('later-native-record').project_id=='later-native-record'
try:scope.stores
except StudyError:pass
else:raise AssertionError('escaped scope accepted')
assert len(list((root/'registry').iterdir()))==1
print('registered, evolved, reopened; zero execution')
'''


class RegisteredRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.fixture=Fixture(self.root,full=True)

    def child(self,mode):
        return subprocess.run([sys.executable,'-B','-c',CHILD,str(self.root),mode],
            cwd=self.fixture.source,capture_output=True,text=True,timeout=90)

    def test_registration_reopens_evolved_native_state(self):
        result=self.child('scope')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('zero execution',result.stdout)

    def test_missing_store_has_zero_publication(self):
        result=self.child('missing')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_foreign_owner_origin_rejects(self):
        result=self.child('origin')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_registry_extra_rejects_without_write(self):
        result=self.child('registry-extra')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unknown_owner_close_retains_study_lock(self):
        result=self.child('close-unknown')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_crash_before_partial_and_complete_append(self):
        for mode in ('crash-before','crash-partial','crash-after'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();fixture=Fixture(root,full=True)
                stopped=subprocess.run([sys.executable,'-B','-c',CHILD,str(root),mode],
                    cwd=fixture.source,capture_output=True,text=True,timeout=90)
                self.assertEqual(stopped.returncode,78,stopped.stdout+stopped.stderr)
                registry=root/'registry'
                before={p.name:p.read_bytes() for p in registry.iterdir()}
                replay="""import sys
from auto_g16.study import _registered_runtime as r
try:r.register_local(sys.argv[1])
except Exception as e:print(type(e).__name__);sys.exit(2)
print('registered')
"""
                result=subprocess.run([sys.executable,'-B','-c',replay,str(root/'creation'/'study')],
                    cwd=fixture.source,capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,2 if mode=='crash-partial' else 0,result.stderr)
                after={p.name:p.read_bytes() for p in registry.iterdir()}
                if mode!='crash-before':self.assertEqual(after,before)
                else:self.assertEqual(set(after),{'0001-runtime.json'})

    def test_concurrent_publishers_serialize_without_second_record(self):
        import time
        result=self.child('prepare')
        self.assertEqual(result.returncode,0,result.stderr)
        script=r"""
import sys,time
from pathlib import Path
from unittest.mock import patch
from auto_g16.study import _registered_runtime as r
root=Path(sys.argv[1]);first=sys.argv[2]=='first';native=r._registry;fired=False
def pause(directory):
 global fired
 if first and not fired:
  fired=True;(root/'entered').write_text('locked')
  deadline=time.monotonic()+60
  while not (root/'release').exists():
   assert time.monotonic()<deadline;time.sleep(.02)
 return native(directory)
try:
 with patch.object(r,'_registry',pause):r.register_local(str(root/'creation'/'study'))
except Exception as e:print(str(e));sys.exit(2)
print('registered')
"""
        first=subprocess.Popen([sys.executable,'-B','-c',script,str(self.root),'first'],
            cwd=self.fixture.source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+60
            while not (self.root/'entered').exists() and first.poll() is None and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue((self.root/'entered').exists())
            loser=subprocess.run([sys.executable,'-B','-c',script,str(self.root),'second'],
                cwd=self.fixture.source,capture_output=True,text=True,timeout=30)
            self.assertEqual(loser.returncode,2,loser.stderr)
            self.assertEqual(loser.stdout.strip(),'busy')
        finally:
            (self.root/'release').write_text('continue')
            out,error=first.communicate(timeout=90)
        self.assertEqual(first.returncode,0,out+error)
        self.assertEqual([p.name for p in (self.root/'registry').iterdir()],['0001-runtime.json'])

    def test_direct_model_origin_rejects(self):
        result=self.child('model-origin')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_registry_close_unknown_preserves_interrupt_and_blocks_reopen(self):
        result=self.child('registry-close')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_body_source_drift_preserves_original(self):
        result=self.child('source-body')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_owner_exit_source_drift_is_detected(self):
        result=self.child('source-owner-exit')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


    def isolated_case(self, mode):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();fixture=Fixture(root,full=True)
            result=subprocess.run([sys.executable,'-B','-c',CHILD,str(root),mode],
                cwd=fixture.source,capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_registry_closed_shape_chain_and_binding_fail_closed(self):
        for variant in ('gap','duplicate','hash','field','sequence'):
            with self.subTest(variant=variant):self.isolated_case('registry-bad-'+variant)

    def test_ancestor_nofollow_and_installed_roots_fail_closed(self):
        for variant in ('ancestor','symlink','runtime-root','outside'):
            with self.subTest(variant=variant):self.isolated_case('path-bad-'+variant)

    def test_historical_generator_is_not_current_regeneration_requirement(self):
        result=self.child('historical-generator')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_real_scope_fork_unwind_preserves_parent(self):
        result=self.child('fork-scope')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_registry_directory_close_failure_is_unresolved(self):
        result=self.child('registry-directory-close')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_reader_releases_registry_for_another_study_append(self):
        import time
        result=self.child('prepare-two')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        script=r"""
import json,sys,time
from pathlib import Path
from auto_g16.study import _registered_runtime as r
root=Path(sys.argv[1]);mode=sys.argv[2]
if mode=='publish':
 r.register_local(str(root/'creation'/'second'));print('second appended');sys.exit(0)
sid=json.loads((root/'registry'/'0001-runtime.json').read_bytes())['study_id']
with r.open_registered(sid) as scope:
 (root/'reader-held').write_text('Study held, registry released')
 deadline=time.monotonic()+90
 while not (root/'reader-release').exists():
  assert time.monotonic()<deadline;time.sleep(.02)
 assert len(list((root/'registry').iterdir()))==2
 assert scope.registration_ref['registration']['study_id']==sid
print('reader exited after append')
"""
        reader=subprocess.Popen([sys.executable,'-B','-c',script,str(self.root),'reader'],
            cwd=self.fixture.source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+60
            while not (self.root/'reader-held').exists() and reader.poll() is None and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue((self.root/'reader-held').exists())
            result=subprocess.run([sys.executable,'-B','-c',script,str(self.root),'publish'],
                cwd=self.fixture.source,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.strip(),'second appended')
        finally:
            (self.root/'reader-release').write_text('continue')
            out,error=reader.communicate(timeout=90)
        self.assertEqual(reader.returncode,0,out+error)
        self.assertEqual(out.strip(),'reader exited after append')
        self.assertEqual([p.name for p in sorted((self.root/'registry').iterdir())],
                         ['0001-runtime.json','0002-runtime.json'])


    def test_native_schema_facts_match_receipts_and_reject_unsafe_handles(self):
        result=self.child('schema-facts')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_study_does_not_call_native_raw_sql(self):
        import ast
        source=Path(__file__).resolve().parents[3]/'auto_g16/study/_registered_runtime.py'
        tree=ast.parse(source.read_text())
        calls=[node.func.attr for node in ast.walk(tree)
               if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
               and node.func.attr in {'_db','execute','_sql'}]
        self.assertEqual(calls,[])

    def test_constructor_cleanup_preserves_original_and_closes_once(self):
        code = r"""
import errno,os,sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from auto_g16.study import _registered_runtime as r
root=Path(sys.argv[1]);mode=sys.argv[2]
link=root/('constructor-link-'+mode);link.symlink_to(root,target_is_directory=True)
real_open,real_close=os.open,os.close
opened=[];attempts=[];original=[];injected=[]
def opening(name,*args,**kwargs):
 try:fd=real_open(name,*args,**kwargs)
 except OSError as error:
  assert name==link.name and error.errno in (errno.ENOTDIR,errno.ELOOP)
  original.append(error);raise
 opened.append(fd);return fd
def closing(fd):
 attempts.append(fd)
 if not injected:
  injected.append(fd)
  if mode=='after':real_close(fd)
  raise OSError('private close details')
 real_close(fd)
before=len(r._RETAINED)
with patch.object(r.os,'open',opening),patch.object(r.os,'close',closing):
 try:r._Directory(str(link))
 except OSError as error:
  assert len(original)==1 and error is original[0]
  assert 'private close' not in str(getattr(error,'__notes__',[]))
  assert any('OSError' in note for note in error.__notes__)
 else:raise AssertionError('constructor unexpectedly accepted')
assert opened and Counter(attempts)==Counter(opened)
assert all(count==1 for count in Counter(attempts).values())
assert len(r._RETAINED)==before+1
retained,fds=r._RETAINED[-1]
assert not retained.fds and set(fds)==set(opened)
print('original nofollow failure retained; every FD close attempted once')
"""
        for variant in ('before','after'):
            with self.subTest(variant=variant):
                result=subprocess.run([sys.executable,'-B','-c',code,str(self.root),variant],
                    cwd=self.fixture.source,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
