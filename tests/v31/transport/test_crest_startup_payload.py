"""Inert delivery/native replay deltas for the additive CREST startup tuple."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import base64
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from auto_g16 import core, execution
from auto_g16.execution import _crest_completion as crest, _crest_startup as startup
from auto_g16.execution import _program_completion as c, program as p, program_runtime as runtime
from auto_g16.transport import program as transport, _bridge
from scripts import run_v31_publisher_pilot as controller
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport import test_crest_completion as previous
from tests.v31.transport import test_program_completion as old
from tests.v31.transport import test_program_composition as composition
from tests.v31.transport import test_publisher_pilot_orchestration as pilot
from tests.v31.transport.test_rtwin_successor_bridge import directory_token

DELIVERY_EVIDENCE = b'SYNTHETIC ONLY: native-loader delivery fixture evidence, never production qualification.\n'


def qualify_profile(profile, queue='simple'):
    old_profile = previous.qualify_crest_profile(profile, queue=queue)
    q = json.loads(old_profile.runtime_contents[crest._Q_NAME])['payload']
    clean = replace(old_profile, runtime_contents={k:v for k,v in old_profile.runtime_contents.items() if k != crest._Q_NAME})
    wrapper, probe = startup._wrapper_sources()
    q.update(schema=startup._Q_SCHEMA, contract_sha256=startup._CONTRACT_SHA256,
             profile_basis_sha256=c._publisher_profile_basis(execution.resolve_server_profile(clean), startup=True),
             delivery_probe={**copy.deepcopy(q['controller_probe']), 'case_id':'P09', 'evidence':pilot.digest(DELIVERY_EVIDENCE)})
    q['implementation'].update(wrapper_source=pilot.digest(wrapper.encode()), probe_source=pilot.digest(probe.encode()), loader_source=pilot.digest(startup._LOADER_SOURCE.encode()))
    q['evidence_manifest_sha256'] = sha256(c._receipt_json(controller._probe_index(q))).hexdigest()
    return replace(clean, runtime_contents={**clean.runtime_contents, startup._Q_NAME:pilot.seal(q)})


class StartupNativeTests(lane.LaneAFixture):
    qualification_name = startup._Q_NAME
    qualify_profile = staticmethod(qualify_profile)
    def profile(self, **kwargs):
        profile = lane.LaneAFixture.profile(self, **kwargs)
        return qualify_profile(replace(profile, runtime_contents={**profile.runtime_contents, c._DEPLOYMENT_NAME:c._receipt_json(old.manifest())}))
    def resolved(self, **kwargs):
        return execution.resolve_server_profile(self.profile(**kwargs))
    def setUp(self):
        original = lane._SyntheticRemoteProjectAttestor._from_privileged_test_fixture
        def attestor(**kw):
            kw['observed_parent_physical_identity'] = directory_token('/home/user100/SDL')
            kw['provisioned_project_physical_identity'] = directory_token(kw['observed_project_dir'])
            return original(**kw)
        with patch.object(lane._SyntheticRemoteProjectAttestor, '_from_privileged_test_fixture', side_effect=attestor):
            super().setUp()
        self.current_profile = self.profile()
        self.q = json.loads(self.current_profile.runtime_contents[startup._Q_NAME])['payload']
        self.spec = p._prepare_program_execution_spec(program_kind='crest', executable_path=lane.CREST_EXECUTABLE_PATH, executable_size_bytes=len(lane.CREST_EXECUTABLE_BYTES), executable_sha256=sha256(lane.CREST_EXECUTABLE_BYTES).hexdigest(), input_name='seed.xyz', input_bytes=lane.XYZ, program_data=self.crest_data(**crest._POLICY), resolved_profile=self.resolved(), completion_mode=c._MODE)
        self.material = c._prepare_publisher_pilot_rendering_material(self.current_profile, self.resolved())
        self.snapshot = self.snapshot_service.prepare(self.store, attempt_id='attempt-1', calculation_plan_id='plan-1', resource_spec_id='resource-1', program_execution_spec=self.spec, project_physical_binding=self.physical_binding(), resolved_resource_request=self.resources(), resolved_server_profile=self.resolved(), workspace_binding=self.workspace(), completion_rendering_material=self.material)
        root=self.root/'transport';root.mkdir()
        self.program_transport_store=transport._ProgramTransportStore._create_completion_store(root/'program.sqlite3',approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.driver=composition._Driver(previous.OUTPUTS)
        self.input_bytes={'seed.xyz':lane.XYZ}
        self.scheduler_bytes={item['portable_name']:item['content_utf8'].encode() for item in self.snapshot.scheduler_artifacts}
    execute = composition.ProgramCompositionTests.execute
    kwargs = old.CompletionTests.kwargs
    publish = old.CompletionTests.publish
    collect = old.CompletionTests.collect

    def test_two_closed_artifacts_replay_and_one_submit(self):
        self.snapshot.assert_identity_closed()
        artifacts=self.snapshot.scheduler_artifacts
        self.assertEqual([x['logical_role'] for x in artifacts],['scheduler-script','startup-payload'])
        self.assertLessEqual(artifacts[0]['size_bytes'],16384)
        self.assertGreater(artifacts[1]['size_bytes'],65536)
        self.assertEqual(p._decode_program_review_semantics(self.snapshot._approval_semantics()), self.snapshot)
        self.execute();self.publish();assessment=self.collect()
        self.assertEqual(assessment.data['verdict'],'SUCCEEDED')
        submit=[request for name,request in self.driver.calls if name=='SUBMIT_QSUB_ONCE']
        self.assertEqual(len(submit),1)
        self.assertEqual(len(submit[0]['payload']['startup_payload_artifact_authority_ids']),1)
        stages=[r['payload']['artifact_kind'] for name,r in self.driver.calls if name=='STAGE_EXACT_FILE']
        self.assertEqual(stages,['program-input','scheduler-script','startup-payload'])
        calls=len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store,**self.kwargs()),assessment)
        self.assertEqual(len(self.driver.calls),calls)

    def test_native_production_wire_restore_and_seed_handoff(self):
        previous.CrestCompletionTests._native_crest_snapshot_restore_collect_and_zero_wire_replay(
            self, recover=False
        )

    def test_missing_reordered_changed_payload_reject_before_effect(self):
        original=self.snapshot.scheduler_artifacts
        for artifacts in (original[:1],original[::-1],(original[0],{**original[1],'content_utf8':original[1]['content_utf8']+' '})):
            with self.subTest(artifacts=len(artifacts)),self.assertRaises(Exception):
                c._material_from_artifact(artifacts,self.resolved())
        with self.assertRaises(Exception):
            runtime._prepare_program_execution(self.store, snapshot=self.snapshot, program_transport_store=self.program_transport_store,input_bytes=self.input_bytes,scheduler_artifact_bytes={'crest.pbs':self.scheduler_bytes['crest.pbs']},driver=self.driver)
        self.assertEqual(self.driver.calls,[])

    def test_q3_requires_p09_loader_and_unambiguous_profile(self):
        for key in ('delivery_probe','loader_source'):
            q=copy.deepcopy(self.q)
            (q if key=='delivery_probe' else q['implementation']).pop(key)
            with self.assertRaises(Exception):c._decode_publisher_qualification(pilot.seal(q))
        q=copy.deepcopy(self.q);q['delivery_probe']['outcome']='UNKNOWN'
        with self.assertRaises(Exception):c._decode_publisher_qualification(pilot.seal(q))
        ambiguous=replace(self.current_profile,runtime_contents={**self.current_profile.runtime_contents,crest._Q_NAME:b'old'})
        with self.assertRaisesRegex(ValueError,'ambiguous'):c._prepare_publisher_pilot_rendering_material(ambiguous,execution.resolve_server_profile(ambiguous))

    def test_payload_authorities_and_fixed_transport_role_are_closed(self):
        self.execute()
        payload=next(r['payload'] for name,r in self.driver.calls if name=='SUBMIT_QSUB_ONCE')
        for ids in ((),('a','b'),(payload['scheduler_artifact_authority_id'],),payload['program_input_artifact_authority_ids']):
            with self.assertRaises(Exception):transport._validate_operation_payload('SUBMIT_QSUB_ONCE',{**payload,'startup_payload_artifact_authority_ids':ids})
        stage=next(r['payload'] for name,r in self.driver.calls if name=='STAGE_EXACT_FILE' and r['payload']['artifact_kind']=='startup-payload')
        for field,value in (('portable_name','foreign.json'),('logical_role','scheduler-script'),('format','bash'),('size_bytes',8*1024*1024+1)):
            with self.assertRaises(Exception):transport._validate_operation_payload('STAGE_EXACT_FILE',{**stage,field:value})

    def test_unknown_submit_replay_never_retries(self):
        composition.ProgramCompositionTests.test_17_ambiguous_qsub_sets_unknown_and_never_retries(self)

    def test_missing_delivery_evidence_refuses_installed_tuple(self):
        from auto_g16.transport import _program_rtwin as rtwin
        installation, authority, run, confirmation = pilot._PilotFixture.install_fixture(self)
        missing = replace(installation, evidence=tuple(x for x in installation.evidence if x.sha256 != sha256(DELIVERY_EVIDENCE).hexdigest()))
        with patch.object(rtwin, '_FIXED_PUBLISHER_INSTALLATION', missing), self.assertRaisesRegex(Exception, 'ingestion rejected'):
            rtwin._read_fixed_publisher_deployment(authority,self.snapshot)
        self.assertEqual(self.driver.calls, [])

    def test_old_wrapper_and_bridge_bytes_remain_exact(self):
        # Independent frozen predecessor digests, not computed expected values.
        self.assertEqual(sha256(_bridge._PRE_STARTUP_PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(),'b80962b8f0425f32206f228ee3e65b76749b8d447e826427dca8241d541166fb')
        for a,b in zip(crest._wrapper_sources(),startup._wrapper_sources()):
            restored=b.replace(startup._MATERIAL_SCHEMA,crest._MATERIAL_SCHEMA).replace('v31-completion-prebinding/5','v31-completion-prebinding/4').replace(startup._Q_SCHEMA,crest._Q_SCHEMA).replace('"crest.pbs","crest-startup.json"','"crest.pbs"')
            self.assertEqual(a,restored)


class LoaderExecutionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.project=Path(t.name).resolve()/'project';self.project.mkdir(mode=0o700)
        self.workspace=self.project/'attempt';self.workspace.mkdir(mode=0o700)
        nodes=[];path=Path('/')
        for part in ('/',*self.project.parts[1:]):
            path=Path('/') if part=='/' else path/part
            s=path.stat();nodes.append([s.st_dev,s.st_ino])
        source='import os,sys,json,base64\nprint(json.dumps({"pid":os.getpid(),"argv":len(sys.argv),"main":__name__,"cwd":os.getcwd(),"cfg":json.loads(base64.b64decode(sys.stdin.read()))["cores"]}))\nraise SystemExit(23)\n'
        d=pilot.digest(source.encode())
        q={'payload':{'schema':startup._Q_SCHEMA,'implementation':{'wrapper_source':d}}}
        config={'prebinding':{'binding_schema':'v31-completion-prebinding/5','wrapper_source_sha256':d['sha256'],'wrapper_source_size_bytes':d['size_bytes'],'cwd_binding':{'location_kind':'server','path':str(self.workspace)},'attempt_id':'attempt'},'prebinding_sha256':'0'*64,'spec':{},'material':{'schema':startup._MATERIAL_SCHEMA,'publisher_qualification_base64':base64.b64encode(c._receipt_json(q)).decode()},'xtb_data_path':'/inert','cores':8,'walltime_seconds':3600}
        self.payload={'schema':startup._PAYLOAD_SCHEMA,'wrapper_source':source,'config':config}
        python=str(Path(sys.executable).resolve())
        self.invocation={'schema':'auto-g16-v31-crest-startup-invocation/1','workspace':str(self.workspace),'project_token':base64.b64encode(c._receipt_json(['v31-directory/1',str(self.project),nodes])).decode(),'payload_name':startup._PAYLOAD_NAME,'server_python':{'path':python,**pilot.digest(Path(python).read_bytes())}}
        self.write_payload()
    def write_payload(self, raw=None):
        raw=c._receipt_json(self.payload) if raw is None else raw
        path=self.workspace/startup._PAYLOAD_NAME
        path.write_bytes(raw);path.chmod(0o600)
        self.invocation.update(payload_sha256=sha256(raw).hexdigest(),payload_size_bytes=len(raw))
    def run_loader(self, prefix=""):
        encoded=base64.b64encode(c._receipt_json(self.invocation)).decode()
        proc=subprocess.Popen([self.invocation['server_python']['path'],'-I','-S','-B','-c',prefix + startup._LOADER_SOURCE,encoded],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        out,err=proc.communicate(timeout=10)
        return proc.pid,proc.returncode,out,err
    def reject(self):
        pid,code,out,err=self.run_loader()
        self.assertNotEqual(code,0);self.assertNotEqual(code,23);self.assertEqual(out,b'')
    def test_same_pid_exact_stdin_and_exit_status(self):
        pid,code,out,err=self.run_loader()
        self.assertEqual(code,23,err.decode());self.assertEqual(json.loads(out),{'pid':pid,'argv':1,'main':'__main__','cwd':str(self.workspace),'cfg':8})
    def test_symlink_payload_refused_before_wrapper(self):
        path=self.workspace/startup._PAYLOAD_NAME;path.rename(self.workspace/'retained');path.symlink_to('retained');self.reject()
    def test_payload_mode_refused_before_wrapper(self):
        (self.workspace/startup._PAYLOAD_NAME).chmod(0o644);self.reject()
    def test_replaced_project_refused_before_wrapper(self):
        self.project.rename(self.project.with_name('retained'));self.project.mkdir(mode=0o700);self.workspace.mkdir(mode=0o700);self.write_payload();self.reject()
    def test_digest_mismatch_refused_before_wrapper(self):
        self.invocation['payload_sha256']='0'*64;self.reject()
    def test_duplicate_json_keys_refused_before_wrapper(self):
        self.write_payload(c._receipt_json(self.payload).replace(b'"schema":',b'"schema":"duplicate","schema":',1));self.reject()
    def test_wrapper_q_mismatch_refused_before_wrapper(self):
        self.payload['wrapper_source']+='\n';self.write_payload();self.reject()
    def set_wrapper(self, source):
        self.payload['wrapper_source'] = source
        d=pilot.digest(source.encode())
        self.payload['config']['prebinding'].update(wrapper_source_sha256=d['sha256'],wrapper_source_size_bytes=d['size_bytes'])
        self.payload['config']['material']['publisher_qualification_base64']=base64.b64encode(c._receipt_json({'payload':{'schema':startup._Q_SCHEMA,'implementation':{'wrapper_source':d}}})).decode()
        self.write_payload()
    def test_normal_zero_exit_preserved(self):
        self.set_wrapper('raise SystemExit(0)\n')
        self.assertEqual(self.run_loader()[1],0)
    def test_signal_exit_preserved(self):
        self.set_wrapper('import os,signal\nos.kill(os.getpid(), signal.SIGTERM)\n')
        self.assertEqual(self.run_loader()[1],-15)
    def test_oversized_and_truncated_payload_refused(self):
        original=self.invocation['payload_size_bytes']
        for size in (original+1,8*1024*1024+1,True):
            self.invocation['payload_size_bytes']=size;self.reject()
    def test_nonregular_payload_refused(self):
        path=self.workspace/startup._PAYLOAD_NAME;path.rename(self.workspace/'retained');os.mkfifo(path,0o600);self.reject()
    def test_mutated_during_read_refused_before_wrapper(self):
        prefix='import os\nreal_read=os.read\nchanged=[]\ndef racing_read(fd,n):\n raw=real_read(fd,n)\n if raw and os.fstat(fd).st_size==%d and not changed:\n  changed.append(1)\n  with open(%r,"ab") as f:f.write(b"x")\n return raw\nos.read=racing_read\n' % (self.invocation['payload_size_bytes'],str(self.workspace/startup._PAYLOAD_NAME))
        _,code,out,_=self.run_loader(prefix)
        self.assertNotEqual(code,23);self.assertNotEqual(code,0);self.assertEqual(out,b'')
    def test_same_bytes_replacement_during_read_refused_before_wrapper(self):
        path=str(self.workspace/startup._PAYLOAD_NAME)
        # Replace after the final real fstat has captured the old inode, so
        # fstat/read/fstat alone passes. Only the new named check can reject.
        prefix='import os\nreal_fstat=os.fstat\nseen=[]\ndef racing_fstat(fd):\n captured=real_fstat(fd)\n if captured.st_size==%d:\n  seen.append(1)\n  if len(seen)==2:\n   os.rename(%r,%r)\n   with open(%r,"xb") as f:f.write(%r)\n   os.chmod(%r,0o600)\n return captured\nos.fstat=racing_fstat\n' % (self.invocation['payload_size_bytes'],path,path+'.retained',path,c._receipt_json(self.payload),path)
        _,code,out,_=self.run_loader(prefix)
        self.assertNotEqual(code,23);self.assertNotEqual(code,0);self.assertEqual(out,b'')
    def test_parent_replaced_after_read_refused_before_wrapper(self):
        prefix='import os\nreal_read=os.read\nchanged=[]\ndef racing_read(fd,n):\n raw=real_read(fd,n)\n if raw and os.fstat(fd).st_size==%d and not changed:\n  changed.append(1)\n  os.rename(%r,%r)\n return raw\nos.read=racing_read\n' % (self.invocation['payload_size_bytes'],str(self.project),str(self.project.with_name('retained')))
        _,code,out,_=self.run_loader(prefix)
        self.assertNotEqual(code,23);self.assertNotEqual(code,0);self.assertEqual(out,b'')
    def test_attempt_mode_refused_before_wrapper(self):
        self.workspace.chmod(0o755);self.reject()


class HistoricalBootstrapTests(unittest.TestCase):
    def test_original_old_bootstrap_receipt_remains_readonly(self):
        from tests.v31.transport.test_receipt_source import ReceiptSourceTests
        fixture=ReceiptSourceTests();self.addCleanup(fixture.doCleanups)
        with patch.object(_bridge,'_PROGRAM_BOOTSTRAP_SOURCE_BYTES',_bridge._PRE_STARTUP_PROGRAM_BOOTSTRAP_SOURCE_BYTES):
            fixture.setUp()
        proof,capture=fixture.read()
        self.assertEqual(proof['capture_authority_id'],capture.capture_authority_id)
        self.assertEqual(fixture.fixed.bootstrap_source_sha256,'b80962b8f0425f32206f228ee3e65b76749b8d447e826427dca8241d541166fb')
