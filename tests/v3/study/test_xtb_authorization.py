"""Actual installed authorization CLI with synthetic original qualification."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.v3.study.test_fresh import sample
from tests.v3.study.test_installation import binding, encode
from tests.v3.study.test_xtb_preparation import QualifiedFixture, PREPARE_CLI_CHILD


class AuthorizationPacketTests(unittest.TestCase):
    def test_native_approval_canonical_preserves_numeric_types(self):
        from auto_g16.approval.models import canonical_bytes, ApprovalValueError
        from auto_g16.execution._identity import canonical_bytes as execution_bytes
        value = {'nested': [None, True, 1, 'original', {'int': 298}]}
        self.assertEqual(canonical_bytes(value), execution_bytes(value))
        self.assertEqual(canonical_bytes({'temperature': 298.15}),
                         b'["mapping",[["temperature",["float",298.15]]]]')
        self.assertNotEqual(canonical_bytes({'scale': 1}), canonical_bytes({'scale': 1.0}))
        for invalid in (float('nan'), float('inf'), float('-inf')):
            with self.assertRaises(ApprovalValueError):canonical_bytes({'value': invalid})

    def test_valid_packet_between_one_and_two_mib_and_oversize_rejection(self):
        from auto_g16.study import _xtb_authorization as subject
        from auto_g16.study._model import StudyError
        # Pure parser coverage: no files, stores or native authority are minted.
        path = '/' + '/'.join(['a' * 30] * 128)
        def reference(sha):
            return dict(path=path, parent_chain=[[0, 1]] * 128,
                        file_identity=[0, 2], sha256=sha, size_bytes=1)
        evidence = [reference(f'{i:064x}') for i in range(256)]
        decision = dict(decision='APPROVED', reviewer_id='explicit-owner', evidence=evidence[0])
        value = dict(schema='auto-g16-study-xtb-authorization/1', study_id='parser-only',
                     prepared_sha256=sha256(encode({})).hexdigest(), scientific=decision,
                     batch=decision, operational=decision,
                     publisher=dict(window={}, qualification=evidence[0], evidence=evidence,
                                    owner_q_acceptance_sha256=evidence[0]['sha256'],
                                    pilot_live_gate_sha256=evidence[1]['sha256']))
        raw = encode(value)
        self.assertGreater(len(raw), 1 << 20)
        self.assertLessEqual(len(raw), 2 << 20)
        session = SimpleNamespace(context=SimpleNamespace(
            facts=SimpleNamespace(qualification_binding=evidence[0])))
        inputs = SimpleNamespace(preview={'study_id': 'parser-only'})
        self.assertEqual(subject.packet(raw, session, inputs, {'record': {}}), value)
        large = json.loads(raw)
        for item in large['publisher']['evidence']:
            item['parent_chain'] = [[2**63 - 1, 2**63 - 1]] * 128
        oversized = encode(large)
        self.assertGreater(len(oversized), 2 << 20)
        with patch('auto_g16.study._model.json.loads', side_effect=AssertionError('oversize decoded')):
            with self.assertRaisesRegex(StudyError, 'invalid-request'):
                subject.packet(oversized, session, inputs, {'record': {}})

AUTH_CHILD = r'''
import fcntl,json,os,runpy,sys,traceback
from hashlib import sha256
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
from auto_g16 import approval,execution
from auto_g16.approval.models import canonical_bytes as native_approval_bytes
from auto_g16.transport import _driver,_program_rtwin,_canonical
from auto_g16.execution import _study_stage_session as native
from auto_g16.study import _xtb_service
from auto_g16.study import _registered_runtime as registered
from auto_g16.execution import _study_authorization as authorization
from scripts import run_v31_publisher_pilot as controller
original_authorize=_xtb_service.authorize
loaded={}
def diagnose(*args,**kwargs):
 try:
  result=original_authorize(*args,**kwargs)
  for ref in result['data']['receipt']['native_references']:
   record=loaded[ref['id']]
   assert ref['sha256']==sha256(native_approval_bytes(record.persisted_payload())).hexdigest()
  return result
 except BaseException:
  traceback.print_exc()
  raise
source,packet,sha,variant=sys.argv[1:]
original=approval.SQLiteApprovalStore.store_batch_submit_approval
original_scientific=approval.SQLiteApprovalStore.store_scientific_approval
original_operational=approval.SQLiteApprovalStore.store_operational_confirmation
def reader(original):
 def read(self,identity):
  record=original(self,identity);loaded[identity]=record
  return record
 return read
writes=[]
def scientific(self,record):
 writes.append('scientific')
 if variant=='prefix':raise RuntimeError('synthetic stopped before first approval')
 return original_scientific(self,record)
def store(self,record):
 writes.append('batch')
 if variant=='before':raise RuntimeError('synthetic stopped before batch')
 value=original(self,record)
 if variant=='after':raise RuntimeError('synthetic stopped after batch')
 return value
def operational(self,record):
 writes.append('operational')
 return original_operational(self,record)
original_validator=controller._validate_pilot_qualification_evidence
local_reviews=[]
def validate(run,deployment,confirmation):
 session=native._CURRENT.get()
 assert session.action=='authorize' and session.run is None and session.publisher is None
 assert _program_rtwin._publisher_identity_installation() is deployment.installation
 resources=tuple(session._resources)
 for name in ('run','publisher','collection_run','collection'):
  try:session.select(name,None)
  except native.ExecutionValueError:pass
  else:raise AssertionError('local review token selected effects')
 try:controller._prepare_first_publisher_pilot_port(run,session.scope.stores)
 except native.ExecutionValueError:pass
 else:raise AssertionError('local review token constructed an effect port')
 assert tuple(session._resources)==resources
 original_validator(run,deployment,confirmation)
 local_reviews.append('effects-refused')
def forbid(*args,**kwargs):raise AssertionError('authorization attempted native execution')
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('no live effect')
sys.addaudithook(audit)
sys.argv=['auto_g16.study','authorize','--directory',source,'--stage','xtb','--request',packet,'--sha256',sha]
interrupted=KeyboardInterrupt('synthetic original body')
target=[];closed=[];held=[]
real_close=os.close
parser_module=_canonical if variant=='basis-close' else controller
real_parser=parser_module.strict_canonical_json
def interrupted_parse(raw,label):
 selected='publisher deployment basis' if variant=='basis-close' else 'reviewed publisher semantics'
 if label==selected:
  session=native._CURRENT.get()
  basename='v31-publisher-pilot-deployment.json' if variant=='basis-close' else 'reviewed-scope.json'
  pins=[row['resource'] for row in session._resources if row['kind']=='publisher-pin'
        and not row['attempted'] and row['resource'].binding.path.endswith('/'+basename)]
  assert len(pins)==1
  target.append(pins[0].fds[-1]);held.append((session,session.scope.registration_ref['registration']['study_id']))
  raise interrupted
 return real_parser(raw,label)
def interrupted_close(fd):
 if target and fd==target[0] and not closed:
  closed.append(fd)
  if variant=='scope-close':real_close(fd)
  raise OSError('private cleanup detail')
 return real_close(fd)
def retained_fault(error):
 assert error is interrupted and held and closed==target and not writes
 assert 'private cleanup' not in str(getattr(error,'__notes__',()))
 session,sid=held[0];scope=session.scope
 assert scope._session_unresolved and session._unknown and native._PROCESS_LOCK.locked()
 assert all(not owner._closed for owner in session._stores.values())
 assert registered.installed._FACTS is not None and registered._RETAINED
 assert authorization._REVIEW.get() is None and native._CURRENT.get() is None
 assert _program_rtwin._STUDY_SESSION.get() is None and registered._ACTIVE_SCOPE.get() is None
 assert any(target[0] in row['descriptors'] for row in session._unknown)
 token=native._CURRENT.set(session)
 try:
  with patch.object(os,'close',side_effect=AssertionError('second close')):
   for row in session._resources:
    if row['attempted']:session.close_resource(row['resource'])
    else:
     try:session.close_resource(row['resource'])
     except native.ExecutionValueError:pass
     else:raise AssertionError('closed unresolved session reopened a resource')
 finally:native._CURRENT.reset(token)
 root=Path(source).parent.parent
 runtime=root/'runtime'/sid
 child=os.fork()
 if child==0:
  fd=os.open(runtime/'initialization',os.O_RDONLY|os.O_DIRECTORY)
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:pass
  else:os._exit(7)
  fd=os.open(root/'registry',os.O_RDONLY|os.O_DIRECTORY)
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);os._exit(0)
 assert os.waitpid(child,0)[1]==0
 try:
  with registered.open_registered(sid):pass
 except Exception:pass
 else:raise AssertionError('unknown resource lifetime reopened')
 print(json.dumps({'fault':'original-and-retention-confirmed'}))
with ExitStack() as faults,patch.object(_xtb_service,'authorize',side_effect=diagnose),\
 patch.object(controller,'_validate_pilot_qualification_evidence',side_effect=validate),\
 patch.object(approval.SQLiteApprovalStore,'store_scientific_approval',side_effect=scientific,autospec=True),\
 patch.object(approval.SQLiteApprovalStore,'store_batch_submit_approval',side_effect=store,autospec=True),\
 patch.object(approval.SQLiteApprovalStore,'store_operational_confirmation',side_effect=operational,autospec=True),\
 patch.object(execution,'execute_once',side_effect=forbid),\
 patch.object(_driver._SubprocessRTWinDriver,'_run',side_effect=forbid):
 for name in ('load_scientific_approval','load_batch_submit_approval','load_operational_confirmation'):
  faults.enter_context(patch.object(approval.SQLiteApprovalStore,name,
      side_effect=reader(getattr(approval.SQLiteApprovalStore,name)),autospec=True))
 if variant in ('basis-close','scope-close'):
  faults.enter_context(patch.object(parser_module,'strict_canonical_json',side_effect=interrupted_parse))
  faults.enter_context(patch.object(os,'close',side_effect=interrupted_close))
 try:runpy.run_module('auto_g16.study',run_name='__main__',alter_sys=True)
 except KeyboardInterrupt as error:retained_fault(error)
 finally:
  print('TEST_WRITES='+json.dumps(writes),file=sys.stderr)
  print('TEST_LOCAL_REVIEWS='+json.dumps(local_reviews),file=sys.stderr)
'''


class InstalledAuthorizationTests(unittest.TestCase):
    def run_case(self, variant):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = QualifiedFixture(root)
            try:
                source = root/'creation'/'study'
                source.mkdir()
                request = root/'request.json'
                request.write_bytes(encode(sample()))
                def cli(*args):
                    result = subprocess.run([sys.executable, '-B', '-m', 'auto_g16.study', *args],
                        cwd=fixture.source, capture_output=True, text=True, timeout=240)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    return json.loads(result.stdout)
                created = cli('create', '--directory', str(source), '--request', str(request),
                              '--sha256', sha256(request.read_bytes()).hexdigest())
                cli('run', '--directory', str(source), '--initialize-local')
                reviewed = cli('review', '--directory', str(source), '--stage', 'xtb')
                preview = reviewed['data']['preview']
                evidence = root/'preparation-evidence'
                evidence.write_bytes(b'explicit synthetic preparation review only')
                now = datetime.now(timezone.utc)
                start = (now-timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                finish = (now+timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                decision = dict(schema='auto-g16-study-xtb-preparation-decision/1',
                    preview_sha256=reviewed['data']['preview_sha256'], study_id=created['study_id'],
                    attempt_id=preview['identities']['attempt_id'], decision='APPROVED',
                    reviewer_id='synthetic-preparation-owner', evidence=binding(evidence, True),
                    window=dict(starts_at=start, expires_at=finish),
                    effects=dict(observe_project=3, provision_project=1, submit_qsub=0))
                preparation = root/'preparation.json'
                preparation.write_bytes(encode(decision))
                cli('authorize-preparation', '--directory', str(source), '--stage', 'xtb',
                    '--request', str(preparation), '--sha256', sha256(preparation.read_bytes()).hexdigest())
                result = subprocess.run([sys.executable, '-B', '-c', PREPARE_CLI_CHILD, str(source),
                    preview['paths']['remote_project_dir'], str(root/'prepare-wire.json')],
                    cwd=fixture.source, capture_output=True, text=True, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                prepared = cli('review', '--directory', str(source), '--stage', 'xtb')['data']['prepared']
                raw_evidence = dict(fixture.probe_evidence)
                for raw in (b'explicit synthetic owner Q acceptance', b'explicit synthetic live gate'):
                    raw_evidence[sha256(raw).hexdigest()] = raw
                evidence_refs = []
                for sha, raw in sorted(raw_evidence.items()):
                    path = root/sha
                    path.write_bytes(raw)
                    evidence_refs.append(binding(path, True))
                human = root/'human-approval'
                human.write_bytes(b'explicit synthetic scientific, finite batch and operational decisions')
                approved = dict(decision='APPROVED', reviewer_id='synthetic-owner', evidence=binding(human, True))
                value = dict(schema='auto-g16-study-xtb-authorization/1', study_id=created['study_id'],
                    prepared_sha256=sha256(encode(prepared)).hexdigest(), scientific=approved,
                    batch=approved, operational=approved,
                    publisher=dict(window=dict(started_at=start, finished_at=finish),
                        qualification=fixture.locator['qualification'], evidence=evidence_refs,
                        owner_q_acceptance_sha256=sha256(b'explicit synthetic owner Q acceptance').hexdigest(),
                        pilot_live_gate_sha256=sha256(b'explicit synthetic live gate').hexdigest()))
                packet = root/'authorization.json'
                packet.write_bytes(encode(value))
                runtime = root/'runtime'/created['study_id']
                def snapshot():
                    return {str(p.relative_to(runtime)):p.read_bytes() for p in runtime.rglob('*') if p.is_file()}
                def invoke(mode, code, expected_writes):
                    result = subprocess.run([sys.executable, '-B', '-c', AUTH_CHILD, str(source),
                        str(packet), sha256(packet.read_bytes()).hexdigest(), mode], cwd=fixture.source,
                        capture_output=True, text=True, timeout=240)
                    self.assertEqual(result.returncode, code, result.stdout+result.stderr)
                    observed = [line for line in result.stderr.splitlines() if line.startswith('TEST_WRITES=')]
                    self.assertEqual(len(observed), 1, result.stderr)
                    self.assertEqual(json.loads(observed[0].split('=', 1)[1]), expected_writes)
                    local_checks = [line for line in result.stderr.splitlines() if line.startswith('TEST_LOCAL_REVIEWS=')]
                    self.assertEqual(len(local_checks), 1, result.stderr)
                    self.assertEqual(json.loads(local_checks[0].split('=', 1)[1]),
                                     ['effects-refused'] if expected_writes or code == 0
                                         and mode not in ('basis-close', 'scope-close') else [])
                    return json.loads(result.stdout)
                if variant in ('basis-close', 'scope-close'):
                    result = invoke(variant, 0, [])
                    self.assertEqual(result, {'fault': 'original-and-retention-confirmed'})
                    self.assertFalse((runtime/'operations'/'xtb'/'authorization'/'receipt.json').exists())
                    return
                if variant in ('missing-expected', 'wrong-expected'):
                    invoke('prefix', 2, ['scientific'])
                    expected_path = runtime/'operations'/'xtb'/'authorization'/'expected-native-approvals.json'
                    if variant == 'missing-expected':
                        expected_path.rename(root/'retained-expected.json')
                    else:
                        expected = json.loads(expected_path.read_bytes())
                        expected['scientific_approval_id'] = '11111111-1111-4111-8111-111111111111'
                        expected_path.write_bytes(encode(expected))
                    saved = snapshot()
                    refused = invoke('normal', 2, [])
                    self.assertEqual(refused['error'], 'runtime-unresolved')
                    self.assertEqual(snapshot(), saved)
                    return
                if variant != 'normal':
                    invoke(variant, 2, ['scientific', 'batch'])
                    self.assertFalse((runtime/'operations'/'xtb'/'authorization'/'receipt.json').exists())
                    self.assertTrue((runtime/'operations'/'xtb'/'authorization'/'expected-native-approvals.json').is_file())
                pending = {'normal': ['scientific', 'batch', 'operational'],
                           'before': ['batch', 'operational'], 'after': ['operational']}[variant]
                result = invoke('normal', 0, pending)
                self.assertEqual(result['state'], 'authorized')
                refs = result['data']['receipt']['native_references']
                self.assertEqual([r['role'] for r in refs], ['scientific', 'batch', 'operational'])
                saved = snapshot()
                self.assertEqual(invoke('normal', 0, []), result)
                self.assertEqual(snapshot(), saved)
                self.assertFalse(Path(preview['paths']['local_attempt_dir']).exists())
            finally:
                fixture.close()

    def test_actual_cli_import_and_exact_restart_without_effects(self):self.run_case('normal')
    def test_native_partial_before_batch_recovers_same_records(self):self.run_case('before')
    def test_native_partial_after_batch_recovers_same_records(self):self.run_case('after')
    def test_missing_expected_rejects_before_any_approval_write(self):self.run_case('missing-expected')
    def test_wrong_expected_rejects_before_any_approval_write(self):self.run_case('wrong-expected')
    def test_native_basis_reader_preserves_body_and_unknown_close(self):self.run_case('basis-close')
    def test_native_scope_reader_preserves_body_and_unknown_close(self):self.run_case('scope-close')
