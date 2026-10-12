"""Installed xTB preparation fixtures; synthetic qualification, no live target."""
import base64
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from auto_g16.execution import _program_completion as completion
from auto_g16.transport import _bridge, _driver
from tests.v3.study.test_installation import Fixture, binding, encode
from tests.v3.study.test_fresh import sample
from hashlib import sha256
from tests.v3.transport._fixtures import TransportFixture, TORQUE_RESOURCE_DESCRIPTOR_BYTES
from tests.v3.execution.test_v31_lane_a import xtb_runtime_data_manifest_bytes
from tests.v31.transport.test_publisher_pilot_orchestration import qualification_fixture, seal


class QualifiedFixture(Fixture):
    """Build Q after the source archive, never a prepared execution snapshot."""
    def __init__(self, root, *, variant='normal'):
        super().__init__(root, full=True)
        self.transport_fixture = TransportFixture()
        self.transport_fixture.setUp()
        try:
            raw = self.transport_fixture.proxyjump_profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
            manifest = json.loads(raw.runtime_contents['transport-deployment-manifest-v2.json'])
            manifest.update(schema='auto-g16-v3-transport-deployment-manifest/3',
                            bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
            manifest['trust_roots'] = {k: v for k, v in manifest['trust_roots'].items()
                                      if k in completion._ROOT_RULES}
            profile = replace(raw, platform_paths={**raw.platform_paths,
                'xtb_executable_path': '/opt/xtb/6.7.1/bin/xtb',
                'xtb_data_path': '/opt/xtb/6.7.1/share/xtb'}, runtime_contents={
                _driver._TABLE_NAME: _driver._OPERATION_TABLE_BYTES,
                _driver._RESOURCE_DESCRIPTOR_NAME: TORQUE_RESOURCE_DESCRIPTOR_BYTES,
                completion._DEPLOYMENT_NAME: completion._receipt_json(manifest),
                _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME: _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES,
                'xtb': b'offline exact image', completion._DATA_NAME: xtb_runtime_data_manifest_bytes()})
            q, self.probe_evidence = qualification_fixture(profile, queue='other' if variant == 'queue' else 'batch')
            q['implementation'].update(commit=self.manifest['source_commit'], tree=self.manifest['source_tree'])
            if variant == 'source':
                q['implementation']['commit'] = 'f' * 40
            qraw = seal(q)
            profile = replace(profile, runtime_contents={**profile.runtime_contents, completion._Q_NAME: qraw})
            value = asdict(profile)
            value['runtime_contents'] = {k: base64.b64encode(v).decode('ascii')
                                         for k, v in profile.runtime_contents.items()}
            value['config_files'] = [dict(logical_name=k, content_base64=base64.b64encode(v).decode('ascii'))
                                     for k, v in profile.config_files]
            (self.install / 'profile.json').write_bytes(encode(value))
            (self.install / 'qualification.json').write_bytes(qraw)
            self.locator['profile'] = binding(self.install / 'profile.json', True)
            self.locator['qualification'] = binding(self.install / 'qualification.json', True)
            self.refresh_locator()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.transport_fixture.doCleanups()


PREVIEW_CHILD = r'''
import json,os,sys
from pathlib import Path
from unittest.mock import patch
from auto_g16.study import _registered_runtime as registered, _runtime_initialization as initialization
from auto_g16.study import _xtb_preview
from auto_g16.study.service import operate
from auto_g16.study._model import encode,digest,StudyError,plain
from auto_g16.execution import _study_stage_session as native
from tests.v3.study.test_fresh import sample
root=Path(sys.argv[1]);variant=sys.argv[2]
source=root/'creation'/'study';source.mkdir()
request=root/'request.json';request.write_bytes(encode(sample()))
sid=operate('create',str(source),request_path=str(request),request_sha256=digest(request.read_bytes()))['study_id']
initialization.initialize_local(str(source),str(root/'runtime'))
registered.register_local(str(source))
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('no remote or compute')
sys.addaudithook(audit)
with registered.open_registered(sid) as scope:
 with native._open_study_xtb_session(scope,'review') as session:
  if variant!='normal':
   try:_xtb_preview.build(session)
   except StudyError as error:assert str(error)=='qualification-required'
   else:raise AssertionError('qualification drift accepted')
  else:
   first=_xtb_preview.build(session);p=plain(first.preview)
   assert p['schema']=='auto-g16-study-xtb-preview/1'
   assert p['study_id']==sid and p['input']['sha256']==digest(p['input']['content_utf8'].encode())
   assert p['resources']['cores']==4 and p['resources']['memory_mb']==12288
   assert p['resources']['walltime_seconds']==1800 and p['resources']['queue']=='batch'
   assert p['preparation_sequence']==['OBSERVE_PROJECT','OBSERVE_PROJECT','PROVISION_PROJECT','OBSERVE_PROJECT']
   assert first.spec.program_data['task']=='optimize'
   assert first.spec.program_data['model']=='gfn2'
   assert not Path(p['paths']['local_attempt_dir']).exists()
   assert p['identities']['attempt_id']==first.workspace.attempt_id
   assert p['installation']['source_commit']==scope._execution_context().facts.source_commit
   assert p==plain(_xtb_preview.build(session).preview)
   scope.stores['project'].assert_no_creation_history(sid)
   for name in ('operations','prepared','artifacts','reviews','public'):
    assert not list((root/'runtime'/sid/name).iterdir())
   print(json.dumps(p))
'''


PREPARE_CLI_CHILD = r'''
import json,os,runpy,sys,traceback
from pathlib import Path
from unittest.mock import patch
from auto_g16.transport import _driver
from auto_g16.study import _xtb_service
from tests.v31.transport.test_rtwin_successor_bridge import _Wire,directory_token
wire=_Wire()
source,remote,record=sys.argv[1:]
wire.project=directory_token(remote)
sys.argv=['auto_g16.study','run','--directory',source,'--stage','xtb','--action','prepare']
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('no live effect')
sys.addaudithook(audit)
original_prepare=_xtb_service.prepare
def diagnosed_prepare(*args,**kwargs):
 try:return original_prepare(*args,**kwargs)
 except BaseException:
  traceback.print_exc()
  raise
try:
 with patch.object(_driver._SubprocessRTWinDriver,'_run',side_effect=wire.run),patch.object(_xtb_service,'prepare',diagnosed_prepare):
  runpy.run_module('auto_g16.study',run_name='__main__',alter_sys=True)
finally:
 Path(record).write_text(json.dumps(dict(calls=[x[0] for x in wire.calls],mkdir_count=wire.mkdir_count)))
'''


class InstalledPreviewTests(unittest.TestCase):
    def run_case(self, variant):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = QualifiedFixture(root, variant=variant)
            try:
                result = subprocess.run([sys.executable, '-B', '-c', PREVIEW_CHILD, str(root), variant],
                    cwd=fixture.source, capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            finally:
                fixture.close()

    def test_original_installed_native_preview_without_effects(self):self.run_case('normal')
    def test_other_source_qualification_rejected(self):self.run_case('source')
    def test_other_queue_qualification_rejected(self):self.run_case('queue')


class InstalledCliPreviewTests(unittest.TestCase):
    def test_public_cli_create_initialize_register_review_and_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = QualifiedFixture(root)
            try:
                source = root / 'creation' / 'study'
                source.mkdir()
                request = root / 'request.json'
                request.write_bytes(encode(sample()))
                def cli(*args):
                    result = subprocess.run([sys.executable, '-B', '-m', 'auto_g16.study', *args],
                        cwd=fixture.source, capture_output=True, text=True, timeout=180)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    return json.loads(result.stdout)
                created = cli('create', '--directory', str(source), '--request', str(request),
                              '--sha256', sha256(request.read_bytes()).hexdigest())
                initialized = cli('run', '--initialize-local', '--directory', str(source))
                self.assertFalse(initialized['execution_performed'])
                self.assertEqual(len(list((root / 'registry').iterdir())), 1)
                runtime = root / 'runtime' / created['study_id']
                def snapshot():
                    return {str(path.relative_to(runtime)): path.read_bytes()
                            for path in runtime.rglob('*') if path.is_file()}
                before = snapshot()
                first = cli('review', '--directory', str(source), '--stage', 'xtb')
                second = cli('review', '--directory', str(source), '--stage', 'xtb')
                self.assertEqual(first, second)
                self.assertEqual(first['state'], 'local-only')
                self.assertEqual(first['data']['preview_sha256'],
                                 sha256(encode(first['data']['preview'])).hexdigest())
                self.assertIsNone(first['data']['prepared'])
                self.assertEqual(snapshot(), before)
                self.assertEqual(len(list(runtime.glob('*.sqlite3'))), 4)
                evidence = root / 'human-preparation.txt'
                evidence.write_bytes(b'Explicit synthetic preparation authority for this offline fixture only.')
                now = datetime.now(timezone.utc)
                decision = dict(schema='auto-g16-study-xtb-preparation-decision/1',
                    preview_sha256=first['data']['preview_sha256'], study_id=created['study_id'],
                    attempt_id=first['data']['preview']['identities']['attempt_id'], decision='APPROVED',
                    reviewer_id='synthetic-fixture-owner', evidence=binding(evidence, True),
                    window=dict(starts_at=(now-timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                                expires_at=(now+timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')),
                    effects=dict(observe_project=3, provision_project=1, submit_qsub=0))
                packet = root / 'decision.json'
                packet.write_bytes(encode(decision))
                args = ('authorize-preparation', '--directory', str(source), '--stage', 'xtb',
                        '--request', str(packet), '--sha256', sha256(packet.read_bytes()).hexdigest())
                authorized = cli(*args)
                after = snapshot()
                self.assertEqual(cli(*args), authorized)
                self.assertEqual(snapshot(), after)
                self.assertEqual(authorized['state'], 'preparation-authorized')
                self.assertIsNone(authorized['data']['receipt'])
                self.assertEqual(set(after) - set(before),
                    {'reviews/xtb-preparation.json', 'reviews/xtb-preparation-evidence'})
                self.assertTrue(all(after[k] == v for k, v in before.items()))
                def prepare_cli(number, expected_code=0):
                    record = root / f'wire-{number}.json'
                    result = subprocess.run([sys.executable, '-B', '-c', PREPARE_CLI_CHILD,
                        str(source), first['data']['preview']['paths']['remote_project_dir'], str(record)],
                        cwd=fixture.source, capture_output=True, text=True, timeout=240)
                    self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
                    return json.loads(result.stdout), json.loads(record.read_bytes())
                prepared, wire = prepare_cli(1)
                self.assertEqual(wire, dict(calls=['OBSERVE_PROJECT','OBSERVE_PROJECT',
                    'PROVISION_PROJECT','OBSERVE_PROJECT'], mkdir_count=1))
                self.assertEqual(prepared['state'], 'prepared')
                self.assertEqual(prepared['data']['native_state']['actual_core_state'], 'PLANNED')
                complete = snapshot()
                replay, wire = prepare_cli(2)
                self.assertEqual(replay, prepared)
                self.assertEqual(wire, dict(calls=[], mkdir_count=0))
                self.assertEqual(snapshot(), complete)
                operation = runtime/'operations'/'xtb'/'preparation'
                receipt = operation/'receipt.json'
                receipt.unlink()  # Synthetic lost local acknowledgement, native history untouched.
                missing_ack = snapshot()
                self.assertEqual(cli('review', '--directory', str(source), '--stage', 'xtb')['state'], 'prepared')
                self.assertEqual(snapshot(), missing_ack)
                adopted, wire = prepare_cli(3)
                self.assertEqual(adopted, prepared)
                self.assertEqual(wire, dict(calls=[], mkdir_count=0))
                receipt.unlink()
                capture_path = operation/'step-03-capture.json'
                original_capture = capture_path.read_bytes()
                captures = []
                for field, malformed in (('transport_evidence', None), ('transport_evidence', {}),
                                         ('process_evidence', {'process': {}})):
                    value = json.loads(original_capture)
                    value[field] = malformed
                    captures.append(value)
                value = json.loads(original_capture)
                value['transport_evidence']['request_sha256'] = 'f' * 64
                captures.append(value)
                for number, value in enumerate(captures, 4):
                    capture_path.write_bytes(encode(value))
                    before_rejected = snapshot()
                    _, wire = prepare_cli(number, expected_code=2)
                    self.assertEqual(wire, dict(calls=[], mkdir_count=0))
                    self.assertEqual(snapshot(), before_rejected)
                    self.assertFalse(receipt.exists())
                capture_path.write_bytes(original_capture)
                adopted, wire = prepare_cli(8)
                self.assertEqual(adopted, prepared)
                self.assertEqual(wire, dict(calls=[], mkdir_count=0))
                reviewed = cli('review', '--directory', str(source), '--stage', 'xtb')
                self.assertEqual(reviewed['state'], 'prepared')
                self.assertIsNotNone(reviewed['data']['prepared'])
                self.assertFalse(Path(first['data']['preview']['paths']['local_attempt_dir']).exists())
                self.assertEqual(snapshot(), complete)
            finally:
                fixture.close()

    def test_unsupported_stage_rejects_before_directory_open(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'auto_g16.study', 'review',
            '--directory', '/nonexistent', '--stage', 'crest'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error'], 'stage-not-supported')
