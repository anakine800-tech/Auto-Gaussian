"""Installed session lifetime with real local owners; never permits remote work."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.v3.study.test_installation import Fixture

CHILD = r'''
import contextvars,fcntl,json,os,sys,threading
from pathlib import Path
from unittest.mock import patch
from auto_g16.study import _registered_runtime as r, _runtime_initialization as init
from auto_g16.study import _xtb_files as files
from auto_g16.study.service import operate
from auto_g16.study._model import encode,digest,StudyError
from auto_g16.execution import _study_stage_session as native
from auto_g16.transport import _program_rtwin as rtwin
from scripts import run_v31_publisher_pilot as controller
from tests.v3.study.test_fresh import sample
root=Path(sys.argv[1]);mode=sys.argv[2]
source=root/'creation'/'study';source.mkdir()
request=root/'request.json';request.write_bytes(encode(sample()))
sid=operate('create',str(source),request_path=str(request),request_sha256=digest(request.read_bytes()))['study_id']
init.initialize_local(str(source),str(root/'runtime'))
r.register_local(str(source))
runtime=root/'runtime'/sid
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('remote or calculation effect')
sys.addaudithook(audit)
def reject(call,expected=(StudyError,native.ExecutionValueError,r.installed.InstallationFactsError)):
 try:call()
 except expected:return
 raise AssertionError('expected rejection')
def enter(scope,action='review',**kwargs):
 with native._open_study_xtb_session(scope,action,**kwargs):pass
def locks_retained():
 child=os.fork()
 if child==0:
  fd=os.open(runtime/'initialization',os.O_RDONLY|os.O_DIRECTORY)
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:pass
  else:os._exit(7)
  fd=os.open(root/'registry',os.O_RDONLY|os.O_DIRECTORY)
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);os._exit(0)
 assert os.waitpid(child,0)[1]==0
def reopen():
 with r.open_registered(sid):pass
if mode.startswith('close-') or mode=='body-close':
 real_open,real_close=os.open,os.close
 targets=[];closed=[];stores=None;session=None
 def opened(name,flags,*args,**kwargs):
  fd=real_open(name,flags,*args,**kwargs)
  if str(name)=='xtb-preparation.json' and flags & os.O_WRONLY:targets.append(fd)
  return fd
 def close(fd):
  if targets and fd==targets[0] and not closed:
   closed.append(fd)
   if mode!='close-before':real_close(fd)
   raise OSError('private resource close detail')
  return real_close(fd)
 original=KeyboardInterrupt('body interrupted')
 try:
  with r.open_registered(sid) as scope:
   stores=dict(scope.stores)
   with native._open_study_xtb_session(scope,'authorize-preparation') as session:
    directory=files.root(session,'reviews')
    with patch.object(os,'open',opened),patch.object(os,'close',close):
     if mode=='body-close':
      with directory._file('xtb-preparation.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL):raise original
     else:directory.publish('xtb-preparation.json',b'{}')
 except BaseException as error:
  assert error is original if mode=='body-close' else isinstance(error,OSError)
  assert 'private resource' not in str(getattr(error,'__notes__',()))
 else:raise AssertionError('close failure lost')
 assert len(closed)==1 and scope._session_unresolved and r._RETAINED
 assert all(not store._closed for store in stores.values())
 assert session._unknown and native._PROCESS_LOCK.locked()
 assert native._CURRENT.get() is None and rtwin._STUDY_SESSION.get() is None and r._ACTIVE_SCOPE.get() is None
 assert session._unknown[0]['descriptors']==(targets[0],)
 # Repeated close cannot touch the uncertain numeric FD.
 token=native._CURRENT.set(session)
 try:
  with patch.object(os,'close',side_effect=AssertionError('second close')):
   session.close_resource(session._unknown[0]['resource'])
 finally:native._CURRENT.reset(token)
 reject(reopen);locks_retained()
 print('unknown close retains stores, Study, loader, process lock; registry independent');sys.exit(0)
if mode.startswith('driver-') or mode.startswith('pin-constructor-'):
 from dataclasses import replace
 from tests.v31.transport.test_publisher_pilot_orchestration import _PilotFixture,file_binding
 path=root/'pin-evidence';path.write_bytes(b'local synthetic evidence')
 binding=file_binding(path)
 original=KeyboardInterrupt('original native cleanup body')
 driver=None;target=[];closed=[];owners=[]
 fixture=None
 if mode.startswith('driver-'):
  # Native lifetime unit only: create the real private driver via its initializer.
  # It never opens qualified effect authority and is not a runtime/E2E fixture.
  fixture=_PilotFixture();fixture.setUp()
 real_close=os.close
 def closing(fd):
  if target and fd==target[0] and not closed:
   closed.append(fd)
   if mode.endswith('after'):real_close(fd)
   raise OSError('private nested close')
  return real_close(fd)
 try:
  with r.open_registered(sid) as scope:
   owners=list(scope.stores.values())
   with native._open_study_xtb_session(scope,'submit') as session:
    if fixture is not None:
     driver=rtwin._RTWinProgramEffectDriver.__new__(rtwin._RTWinProgramEffectDriver)
     driver._initialize(fixture.snapshot,fixture.current_profile,scope.stores['transport'])
     pin=rtwin._PinnedPublisherFile(binding,1024)
     driver._publisher=rtwin._PublisherDeploymentRead(None,{}, {}, {}, (pin,))
     target.append(pin.fds[-1])
     with patch.object(os,'close',closing):
      try:raise original
      finally:session.close_resource(driver,original=original)
    else:
     check=rtwin._PinnedPublisherFile._read_and_check
     def interrupted(pin):
      target.append(pin.fds[-1]);raise original
     with patch.object(rtwin._PinnedPublisherFile,'_read_and_check',interrupted),patch.object(os,'close',closing):
      rtwin._PinnedPublisherFile(binding,1024)
 except KeyboardInterrupt as error:
  assert error is original and 'private nested' not in str(error.__notes__)
 else:raise AssertionError('native cleanup masked original')
 assert scope._session_unresolved and session._unknown and native._PROCESS_LOCK.locked()
 assert all(not owner._closed for owner in owners)
 assert r.installed._FACTS is not None and len(closed)==1
 assert any(target[0] in row['descriptors'] for row in session._unknown)
 token=native._CURRENT.set(session)
 try:
  with patch.object(os,'close',side_effect=AssertionError('second uncertain close')):
   for row in session._resources:session.close_resource(row['resource'])
 finally:native._CURRENT.reset(token)
 locks_retained();print('native lifetime only: full inventory retained and original exception preserved');sys.exit(0)
if mode=='fork':
 parent=os.getpid();touched=[]
 try:
  with r.open_registered(sid) as scope:
   stores=dict(scope.stores)
   with native._open_study_xtb_session(scope,'review') as session:
    child=os.fork()
    if child==0:
     class Forbidden:
      def __getattribute__(self,name):touched.append(name);raise AssertionError('inherited SQLite')
     kept=[store._connection for store in stores.values()]
     for store in stores.values():store._connection=Forbidden()
     reject(session.assert_current)
     raise KeyboardInterrupt('fork unwind')
    assert os.waitpid(child,0)[1]==0
    session.assert_current()
 except KeyboardInterrupt:
  if os.getpid()!=parent:
   assert native._QUARANTINE and r._RETAINED and not touched
   os._exit(0)
  raise
 reopen();print('fork rejected without inherited SQLite access');sys.exit(0)
with r.open_registered(sid) as scope:
 if mode=='fixed':
  for module,name in ((controller,'_FIXED_PILOT_RUN'),(controller,'_FIXED_COLLECTION_RUN'),
       (rtwin,'_FIXED_PUBLISHER_INSTALLATION'),(rtwin,'_FIXED_COLLECTION_INSTALLATION')):
   with patch.object(module,name,object()):reject(lambda:enter(scope))
  enter(scope)
 elif mode=='actions':
  for action,kwargs in [('other',{}),('collect',{}),('collect',{'continuation_sha256':'A'*64}),
      ('review',{'continuation_sha256':'a'*64})]:reject(lambda:enter(scope,action,**kwargs))
  with native._open_study_xtb_session(scope,'review') as session:
   reject(session.require_writer)
   reject(lambda:session.select('publisher',None))
   reject(lambda:enter(scope))
   fake=native._Session(scope,'review',None)
   transport_token=rtwin._STUDY_SESSION.set(fake)
   try:reject(rtwin._active_study_session,(rtwin.TransportBoundaryError,))
   finally:rtwin._STUDY_SESSION.reset(transport_token)
   reject(fake.assert_current)
   reject(lambda:scope._retain_unresolved_session(fake))
   reject(lambda:scope._retain_unresolved_session(session))
   def other_context():
    token=r._ACTIVE_SCOPE.set(scope)
    try:reject(lambda:enter(scope))
    finally:r._ACTIVE_SCOPE.reset(token)
   contextvars.Context().run(other_context)
   errors=[]
   def other_thread():
    try:session.assert_current()
    except native.ExecutionValueError:errors.append(True)
   thread=threading.Thread(target=other_thread);thread.start();thread.join();assert errors==[True]
  reject(session.assert_current)
 elif mode=='origin':
  with native._open_study_xtb_session(scope,'review') as session:
   for field in ('__file__',):
    with patch.object(rtwin,field,'/foreign/module.py'):reject(session.assert_current)
   with patch.object(rtwin.__spec__,'origin','/foreign/module.py'):reject(session.assert_current)
 elif mode=='primitive':
  with native._open_study_xtb_session(scope,'review') as session:
   directory=files.root(session,'reviews')
   def access(flags):
    with directory._file('xtb-preparation.json',flags):pass
   for flags in (os.O_WRONLY|os.O_CREAT|os.O_EXCL,os.O_WRONLY|os.O_TRUNC,os.O_RDWR):
    reject(lambda:access(flags))
   assert not directory.names()
  with native._open_study_xtb_session(scope,'authorize') as session:
   session.publisher=object()
   reject(lambda:session.select('publisher',None))
 elif mode.startswith('drift-'):
  original=KeyboardInterrupt('body with evidence drift')
  try:
   with native._open_study_xtb_session(scope,'prepare') as session:
    target=files.directory(session,'prepared-root',create=True)
    target.publish('prepared.json',b'{}')
    path=Path(target.path)
    if mode=='drift-directory':
     path.rename(path.with_name('retained-original'));path.mkdir()
    elif mode=='drift-extra':(path/'unexpected').write_bytes(b'extra')
    else:(path/'prepared.json').write_bytes(b'[]')
    if mode=='drift-body':raise original
  except KeyboardInterrupt as error:
   assert error is original and error.__notes__
  except StudyError:
   assert mode!='drift-body'
  else:raise AssertionError('business evidence drift accepted')
  assert not scope._session_unresolved
  print('business evidence drift detected; no lifetime-unknown claim');sys.exit(0)
 elif mode=='replacement':
  with native._open_study_xtb_session(scope,'prepare') as session:
   target=files.directory(session,'prepared-root',create=True)
   native_close=session.close_resource;fired=[]
   def replaced(resource,**kwargs):
    native_close(resource,**kwargs)
    if resource.name=='prepared.json' and not fired:
     fired.append(True);p=Path(target.path)/'prepared.json'
     p.rename(root/'retained-original-file')
     p.write_bytes(b'{}')
   with patch.object(session,'close_resource',replaced):reject(lambda:target.publish('prepared.json',b'{}'))
   assert fired
   print('same-content replacement rejected');sys.exit(0)
 elif mode in ('directory','directory-partial'):
  with native._open_study_xtb_session(scope,'prepare') as session:
   if mode=='directory-partial':
    real_mkdir=os.mkdir
    def interrupted(name,*args,**kwargs):
     real_mkdir(name,*args,**kwargs);raise KeyboardInterrupt('after mkdir')
    with patch.object(os,'mkdir',interrupted):
     reject(lambda:files.directory(session,'prepared-root',create=True),(KeyboardInterrupt,))
    reject(lambda:files.directory(session,'prepared-root',create=True))
   else:
    target=files.directory(session,'prepared-root',create=True)
    saved=target.publish('prepared.json',b'{}')
    assert target.read('prepared.json')[1]==saved
    reject(lambda:target.publish('prepared.json',b'changed'))
  with native._open_study_xtb_session(scope,'review') as session:
   if mode=='directory-partial':reject(lambda:files.directory(session,'prepared-root'))
   else:
    target=files.directory(session,'prepared-root')
    assert target.read('prepared.json')[1]==saved
    reject(lambda:target.publish('new.json',b'{}'))
 else:
  original=KeyboardInterrupt('ordinary body')
  try:
   with native._open_study_xtb_session(scope,'review'):raise original
  except KeyboardInterrupt as error:assert error is original
  assert not scope._session_unresolved and not native._PROCESS_LOCK.locked()
  enter(scope)
 assert not scope._session_unresolved
reopen()
assert not native._PROCESS_LOCK.locked() and not native._QUARANTINE
print('session validation and cleanup passed; zero remote effect')
'''


class StageSessionTests(unittest.TestCase):
    def run_case(self, mode):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root, full=True)
            result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(root), mode],
                cwd=fixture.source, capture_output=True, text=True, timeout=180)
            if result.returncode:
                print(result.stdout + result.stderr, flush=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ordinary_failure_closes_and_reopens(self):self.run_case('ordinary')
    def test_closed_actions_context_thread_and_fake_tokens(self):self.run_case('actions')
    def test_dual_fixed_selections_reject(self):self.run_case('fixed')
    def test_module_file_and_spec_origin(self):self.run_case('origin')
    def test_fork_rejects_inherited_resource_access(self):self.run_case('fork')
    def test_file_close_before_actual_retains_original_owners(self):self.run_case('close-before')
    def test_file_close_after_actual_retains_original_owners(self):self.run_case('close-after')
    def test_body_interrupt_survives_close_failure(self):self.run_case('body-close')
    def test_directory_exact_reopen_and_no_overwrite(self):self.run_case('directory')
    def test_interrupted_mkdir_never_repeats(self):self.run_case('directory-partial')

    def test_readonly_primitive_and_local_authorize_forbid_effects(self):self.run_case('primitive')
    def test_same_content_replacement_is_not_adopted(self):self.run_case('replacement')
    def test_business_file_drift_detected_at_exit(self):self.run_case('drift-file')
    def test_business_directory_drift_detected_at_exit(self):self.run_case('drift-directory')
    def test_unexpected_directory_entry_rejected(self):self.run_case('drift-extra')
    def test_body_error_preserved_with_business_drift(self):self.run_case('drift-body')
    def test_driver_nested_close_before_preserves_body(self):self.run_case('driver-before')
    def test_driver_nested_close_after_preserves_body(self):self.run_case('driver-after')
    def test_publisher_partial_constructor_close_before(self):self.run_case('pin-constructor-before')
    def test_publisher_partial_constructor_close_after(self):self.run_case('pin-constructor-after')


class FixedPathDependencyTests(unittest.TestCase):
    def test_default_driver_and_pin_never_import_or_call_stage_session(self):
        import builtins
        from unittest.mock import patch
        from auto_g16.execution import _study_stage_session as native
        from auto_g16.transport import _program_rtwin as rtwin
        from tests.v31.transport.test_publisher_pilot_orchestration import _PilotFixture, file_binding
        fixture = _PilotFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        path = fixture.root / 'pin-evidence'
        path.write_bytes(b'local synthetic evidence')
        binding = file_binding(path)
        original_import = builtins.__import__
        def guarded(name, globals=None, locals=None, fromlist=(), level=0):
            if '_study_stage_session' in name or '_study_stage_session' in (fromlist or ()):
                raise AssertionError('fixed path imported new Execution dependency')
            return original_import(name, globals, locals, fromlist, level)
        with patch.object(builtins, '__import__', guarded), \
                patch.object(native, '_current', side_effect=AssertionError('new session call')), \
                patch.object(rtwin, '_wire_call', side_effect=AssertionError('remote wire')):
            pin = rtwin._PinnedPublisherFile(binding, 1024)
            pin._read_and_check()
            pin.close()
            driver = rtwin._RTWinProgramEffectDriver.__new__(rtwin._RTWinProgramEffectDriver)
            driver._initialize(fixture.snapshot, fixture.current_profile, fixture.program_transport_store)
            self.assertIsNone(driver._study_session)
            driver.close()
            with self.assertRaises(rtwin.TransportBoundaryError):
                rtwin._RTWinProgramEffectDriver(snapshot=fixture.snapshot,
                    current_profile=fixture.current_profile, program_transport_store=fixture.program_transport_store)
