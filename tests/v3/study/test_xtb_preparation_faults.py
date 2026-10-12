"""Native preparation faults use the actual installed owners and final wire seam."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.v3.study.test_xtb_preparation import QualifiedFixture

CHILD = r'''
import json,os,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from auto_g16.study import _registered_runtime as registered,_runtime_initialization as initialization
from auto_g16.study import _xtb_preview,_xtb_files,_xtb_service
from auto_g16.study.service import operate
from auto_g16.study._model import encode,digest,StudyError
from auto_g16.execution import _study_stage_session as native,_study_preparation as preparation
from auto_g16.execution._identity import ExecutionValueError
from auto_g16.transport import _driver,_bridge,_program_rtwin as bridge
from tests.v3.study.test_fresh import sample
from tests.v3.study.test_installation import binding
from tests.v31.transport.test_rtwin_successor_bridge import _Wire,directory_token
root=Path(sys.argv[1]);variant=sys.argv[2]
source=root/'creation'/'study';source.mkdir()
request=root/'request.json';request.write_bytes(encode(sample()))
sid=operate('create',str(source),request_path=str(request),request_sha256=digest(request.read_bytes()))['study_id']
initialization.initialize_local(str(source),str(root/'runtime'));registered.register_local(str(source))
evidence=root/'human.txt';evidence.write_bytes(b'explicit synthetic preparation fixture authorization')
with registered.open_registered(sid) as scope:
 with native._open_study_xtb_session(scope,'authorize-preparation') as session:
  inputs=_xtb_preview.build(session);p=inputs.preview
  now=datetime.now(timezone.utc)
  decision=dict(schema='auto-g16-study-xtb-preparation-decision/1',preview_sha256=digest(encode(p)),
   study_id=sid,attempt_id=p['identities']['attempt_id'],decision='APPROVED',reviewer_id='synthetic-owner',
   evidence=binding(evidence,True),effects=dict(observe_project=3,provision_project=1,submit_qsub=0),
   window=dict(starts_at=(now-timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
   expires_at=(now+timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')))
  reviews=_xtb_files.root(session,'reviews')
  reviews.publish('xtb-preparation-evidence',evidence.read_bytes())
  reviews.publish('xtb-preparation.json',encode(decision))
wire=_Wire();wire.project=directory_token(p['paths']['remote_project_dir'])
target_fd=[];mutations=[];real_read=os.read
def read(fd,cap):
 raw=real_read(fd,cap)
 if variant=='readback' and target_fd and fd==target_fd[0] and raw and not mutations:
  mutations.append(fd)
  os.pwrite(fd,b'X'*len(raw),0);os.fsync(fd)
 return raw
def run(scope,invocation):
 if variant=='readback':target_fd[:]=native._CURRENT.get()._preparation.sink.resource.fds
 result=wire.run(scope,invocation)
 if variant=='prewrite':
  sink=native._CURRENT.get()._preparation.sink
  target_fd[:]=sink.resource.fds
  os.fchmod(target_fd[0],0o400)
 if variant=='timeout':return b'',b'',None,'timeout',False,False
 if variant=='interrupt':raise KeyboardInterrupt('synthetic interrupt after entered wire')
 response=_bridge._decode_frame(result[0],cap=invocation.operation.stdout_cap,field='test')
 if variant=='state':response['result']['state']='INVALID'
 elif variant=='path':response['result']['parent_physical_identity']=directory_token('/wrong')
 elif variant=='keys':response['result']['unexpected']=True
 return (_bridge._encode_frame(response),*result[1:])
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('no live effect')
sys.addaudithook(audit)
with patch.object(_driver._SubprocessRTWinDriver,'_run',side_effect=run),patch.object(os,'read',side_effect=read):
 with registered.open_registered(sid) as scope:
  with native._open_study_xtb_session(scope,'prepare') as session:
   inputs=_xtb_preview.build(session)
   try:
    with preparation.prepare_once(session,inputs) as current:
     attestor=bridge._RTWinProjectAttestor(current_profile=inputs.current_profile,target=inputs.target)
     try:attestor._observe_current(inputs.target,p['paths']['remote_project_dir'])
     except (bridge._ProjectWireUnknown,KeyboardInterrupt):pass
     else:raise AssertionError('invalid wire result accepted')
     assert current.ordinal==0 and current.entered
     if variant in ('readback','prewrite'):
      assert (mutations if variant=='readback' else target_fd)
      assert current.sink.attempted and not current.sink.resource.fds
      assert current.sink.name not in current.directory.seen
      if variant=='prewrite':
       captured_path=Path(current.directory.path)/current.sink.name
       assert captured_path.read_bytes()==b''
       captured_path.chmod(0o600)
      with patch.object(os,'write',side_effect=AssertionError('duplicate diagnostic write')):
       try:current.capture(bridge._ProjectWireCapture())
       except ExecutionValueError:pass
       else:raise AssertionError('consumed diagnostic retried')
     try:attestor._observe_current(inputs.target,p['paths']['remote_project_dir'])
     except ExecutionValueError:pass
     else:raise AssertionError('caught UNKNOWN continued to a second wire')
     assert len(wire.calls)==1
   except ExecutionValueError:pass
   else:raise AssertionError('incomplete preparation acknowledged')
 # New original four-store/session ownership still cannot replay the entered step.
 try:_xtb_service.prepare(str(source))
 except StudyError as error:assert str(error)=='preparation-unresolved'
 else:raise AssertionError('partial preparation replayed')
 assert len(wire.calls)==1
 assert wire.mkdir_count==0
print(json.dumps(dict(variant=variant,calls=[x[0] for x in wire.calls],resubmission=False)))
'''


class PreparationFaultTests(unittest.TestCase):
    def run_case(self, variant):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = QualifiedFixture(root)
            try:
                result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(root), variant],
                    cwd=fixture.source, capture_output=True, text=True, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            finally:fixture.close()

    def test_invalid_state_cannot_continue_or_replay(self):self.run_case('state')
    def test_wrong_physical_path_cannot_continue_or_replay(self):self.run_case('path')
    def test_extra_result_key_cannot_continue_or_replay(self):self.run_case('keys')
    def test_timeout_cannot_continue_or_replay(self):self.run_case('timeout')
    def test_interruption_cannot_continue_or_replay(self):self.run_case('interrupt')
    def test_capture_readback_race_rejects_and_consumes_once(self):self.run_case('readback')
    def test_capture_prewrite_failure_consumes_once(self):self.run_case('prewrite')


POSTFLIGHT_CHILD = CHILD.split('wire=_Wire();')[0] + r'''
import runpy,base64,hashlib
wire=_Wire();wire.project=directory_token(p['paths']['remote_project_dir'])
clock_patch=None
original_datetime=datetime
class Expired(datetime):
 @classmethod
 def now(cls,tz=None):return original_datetime(2100,1,1,tzinfo=timezone.utc)
def run(scope,invocation):
 global clock_patch
 result=wire.run(scope,invocation)
 if invocation.operation.name=='PROVISION_PROJECT':
  if variant=='source':
   path=Path(_xtb_service.__file__)
   path.write_bytes(path.read_bytes()+b'\n# synthetic post-wire source drift\n')
  else:
   clock_patch=patch.object(_xtb_service,'datetime',Expired);clock_patch.start()
 return result
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('no live effect')
sys.addaudithook(audit)
sys.argv=['auto_g16.study','run','--directory',str(source),'--stage','xtb','--action','prepare']
try:
 with patch.object(_driver._SubprocessRTWinDriver,'_run',side_effect=run):
  try:runpy.run_module('auto_g16.study',run_name='__main__',alter_sys=True)
  except SystemExit as error:assert error.code==2
  else:raise AssertionError('postflight failure acknowledged')
finally:
 if clock_patch is not None:clock_patch.stop()
assert [v[0] for v in wire.calls]==['OBSERVE_PROJECT','OBSERVE_PROJECT','PROVISION_PROJECT']
assert wire.mkdir_count==1
operation=root/'runtime'/sid/'operations'/'xtb'/'preparation'
assert not (operation/'receipt.json').exists()
assert not (operation/'step-04-entered.json').exists()
raw=(operation/'step-03-capture.json').read_bytes();capture=json.loads(raw)
e=capture['transport_evidence']
out=base64.b64decode(e['stdout_base64'],validate=True)
assert hashlib.sha256(out).hexdigest()==e['stdout_sha256']
frame=_bridge._decode_frame(out,cap=65536,field='retained original Project frame')
assert frame['operation']=='PROVISION_PROJECT' and frame['result']['state']=='EXISTING'
print(json.dumps(dict(study_id=sid,capture_sha256=digest(raw),variant=variant)))
'''


class PostflightEvidenceTests(unittest.TestCase):
    def run_case(self, variant):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = QualifiedFixture(root)
            try:
                result = subprocess.run([sys.executable, '-B', '-c', POSTFLIGHT_CHILD, str(root), variant],
                    cwd=fixture.source, capture_output=True, text=True, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                import json
                from tests.v3.study.test_xtb_preparation import PREPARE_CLI_CHILD
                value = json.loads(result.stdout.splitlines()[-1])
                capture = root/'runtime'/value['study_id']/'operations'/'xtb'/'preparation'/'step-03-capture.json'
                fresh = subprocess.run([sys.executable, '-I', '-c', '''
import hashlib,json,sys
raw=open(sys.argv[1],'rb').read()
assert hashlib.sha256(raw).hexdigest()==sys.argv[2]
capture=json.loads(raw)
assert capture['transport_evidence']['operation']=='PROVISION_PROJECT'
assert capture['ordinal']==3
''', str(capture), value['capture_sha256']], capture_output=True, text=True)
                self.assertEqual(fresh.returncode, 0, fresh.stdout+fresh.stderr)
                record = root/'replay-wire.json'
                replay = subprocess.run([sys.executable, '-B', '-c', PREPARE_CLI_CHILD,
                    str(root/'creation'/'study'), '/unused-no-wire', str(record)],
                    cwd=fixture.source, capture_output=True, text=True, timeout=180)
                self.assertEqual(replay.returncode, 2, replay.stdout+replay.stderr)
                self.assertEqual(json.loads(record.read_bytes()), dict(calls=[],mkdir_count=0))
            finally:fixture.close()

    def test_post_provision_source_drift_preserves_original_capture(self):self.run_case('source')
    def test_post_provision_expiry_preserves_original_capture(self):self.run_case('expiry')
