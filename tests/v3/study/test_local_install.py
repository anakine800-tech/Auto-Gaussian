"""Exclusive installation publication, retained failures and actual installed CLI."""
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.study import _local_install as subject
from auto_g16.study import _installation as facts
from auto_g16.study.__main__ import main
from auto_g16.study._model import StudyError
from tests.v3.study.test_installation import Fixture, binding, encode
from tests.v3.study.test_fresh import sample


PUBLISH = r'''
import json,os,sys
from unittest.mock import patch
from auto_g16.study import _local_install as s
request,digest,point,kind=sys.argv[1:]
original_mkdir=s._Writer.mkdir;original_publish=s._Writer.publish
original_check=s.facts.inspect_bundle
def mkdir(self,path):
 original_mkdir(self,path)
 if kind=='mkdir' and path.endswith(point):os._exit(78)
def publish(self,path,raw,mode=0o600):
 value=original_publish(self,path,raw,mode)
 if kind=='file' and path.endswith(point):os._exit(78)
 return value
def inspect(path):
 if kind=='complete':os._exit(78)
 return original_check(path)
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('remote effect')
sys.addaudithook(audit)
with patch.object(s._Writer,'mkdir',mkdir),patch.object(s._Writer,'publish',publish),patch.object(s.facts,'inspect_bundle',inspect):
 try:print(json.dumps(s.publish_local(request,digest)))
 except Exception as e:print(json.dumps({'error':str(e)}));sys.exit(2)
'''

CLI = r'''
import json,os,sys
from unittest.mock import patch
from auto_g16.study.__main__ import main
from auto_g16.study._files import Directory
from auto_g16.execution import execute_once
point=sys.argv[1]
old=Directory.publish
def publish(self,name,raw):
 old(self,name,raw)
 if name==point:os._exit(78)
def audit(event,args):
 if event.startswith('socket.') or event=='subprocess.Popen':raise AssertionError('remote effect')
sys.addaudithook(audit)
with patch.object(Directory,'publish',publish),patch('auto_g16.execution.execute_once',side_effect=AssertionError('submit')):
 sys.exit(main(sys.argv[2:]))
'''


class LocalInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.fixture=Fixture(self.root)
        self.target=self.root/'published'
        self.request=self.root/'request.json'
        self.value=dict(schema='auto-g16-study-local-install-request/1',
            destination=dict(path=str(self.target),parent_chain=binding(self.root)['parent_chain']),
            source_directory=binding(self.fixture.source),roots=self.fixture.locator['roots'],
            **{key:self.fixture.locator[key] for key in ('source_manifest','commit_object','profile','qualification')})
        self.refresh()

    def refresh(self):
        raw=encode(self.value);self.request.write_bytes(raw);self.digest=sha256(raw).hexdigest()

    def call(self):
        return subject.publish_local(str(self.request),self.digest)

    def child(self,point='',kind=''):
        return subprocess.run([sys.executable,'-B','-c',PUBLISH,str(self.request),self.digest,point,kind],
            capture_output=True,text=True)

    def test_exact_copy_existing_refusal_and_no_execution(self):
        with patch('socket.socket',side_effect=AssertionError('remote')),patch('subprocess.Popen',side_effect=AssertionError('child')):
            result=self.call()
        self.assertFalse(result['execution_performed']);self.assertEqual(result['qualification_state'],'not-assessed')
        for entry in self.fixture.manifest['entries']:
            self.assertEqual((self.target/'source'/entry['path']).read_bytes(),(self.fixture.source/entry['path']).read_bytes())
        with facts.inspect_bundle(str(self.target)) as saved:
            self.assertEqual(result['installation']['source_commit'],saved.source_commit)
        before={str(p):p.stat().st_ino for p in self.target.rglob('*')}
        with self.assertRaisesRegex(StudyError,'destination-exists'):self.call()
        self.assertEqual(before,{str(p):p.stat().st_ino for p in self.target.rglob('*')})

    def test_invalid_request_and_source_have_zero_target(self):
        baseline=json.loads(encode(self.value))
        mutations=[lambda v:v.update(extra=True),lambda v:v['destination']['parent_chain'][-1].__setitem__(1,1),
            lambda v:v['roots'].__setitem__('runtime',v['roots']['creation']),
            lambda v:v['source_manifest'].__setitem__('sha256','0'*64),
            lambda v:v['destination'].__setitem__('path',str(self.fixture.source/'nested'))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.value=json.loads(encode(baseline));mutate(self.value);self.refresh()
                with self.assertRaises(StudyError):self.call()
                self.assertFalse(self.target.exists())
        self.value=baseline;self.refresh()
        (self.fixture.source/'foo/bar').write_bytes(b'changed')
        with self.assertRaises(StudyError):self.call()
        self.assertFalse(self.target.exists())

    def test_existing_empty_partial_file_and_symlink(self):
        for kind in ('empty','partial','file','symlink'):
            target=self.root/kind;self.value['destination']['path']=str(target);self.refresh()
            if kind=='file':target.write_bytes(b'sentinel')
            elif kind=='symlink':target.symlink_to(self.fixture.source,target_is_directory=True)
            else:
                target.mkdir()
                if kind=='partial':(target/'sentinel').write_bytes(b'keep')
            with self.assertRaisesRegex(StudyError,'destination-exists'):self.call()

    def test_positive_short_writes(self):
        write=os.write
        with patch.object(subject.os,'write',side_effect=lambda fd,raw:write(fd,raw[:17])):
            self.call()
        with facts.inspect_bundle(str(self.target)):pass

    def test_zero_write_failure_retains_partial(self):
        with patch.object(subject.os,'write',return_value=0):
            with self.assertRaisesRegex(StudyError,'installation-publication-failed'):self.call()
        self.assertTrue(self.target.is_dir())
        with self.assertRaisesRegex(StudyError,'destination-exists'):self.call()
        with self.assertRaises(facts.InstallationFactsError):
            with facts.inspect_bundle(str(self.target)):pass

    def test_fsync_failure_retains_reservation(self):
        with patch.object(subject.os,'fsync',side_effect=OSError('sensitive')):
            with self.assertRaisesRegex(StudyError,'installation-publication-failed'):self.call()
        self.assertTrue(self.target.is_dir())
        with self.assertRaisesRegex(StudyError,'destination-exists'):self.call()

    def test_readback_drift_and_target_replacement(self):
        original=subject._Writer.read
        sentinel=self.root/'sentinel';sentinel.write_bytes(b'unchanged')
        triggered=[]
        def read(writer,path,*args,**kwargs):
            if path.startswith(str(self.target)) and not triggered:
                triggered.append(path)
                target=Path(path);target.rename(target.with_name(target.name+'.retained'))
                target.symlink_to(sentinel)
            return original(writer,path,*args,**kwargs)
        with patch.object(subject._Writer,'read',read):
            with self.assertRaises(StudyError):self.call()
        self.assertEqual(sentinel.read_bytes(),b'unchanged')

    def test_same_inode_readback_drift(self):
        original=subject._Writer.read
        def read(writer,path,*args,**kwargs):
            with open(path,'ab') as f:f.write(b'changed')
            return original(writer,path,*args,**kwargs)
        with patch.object(subject._Writer,'read',read):
            with self.assertRaisesRegex(StudyError,'identity-drift'):self.call()

    def test_cleanup_attempts_all_and_releases_lock(self):
        close=os.close;seen=[];failed=[]
        def fail_once(fd):
            seen.append(fd);close(fd)
            if not failed:failed.append(fd);raise OSError('sensitive close')
        with patch.object(subject.os,'close',fail_once):
            with self.assertRaises(StudyError):self.call()
        self.assertGreater(len(seen),10)
        # Complete bytes may exist, but failure never produced a publication response.
        with self.assertRaisesRegex(StudyError,'destination-exists'):self.call()

    def test_process_crashes_preserve_and_never_republish(self):
        points=[('/published','mkdir'),('/source','mkdir'),('/installation','mkdir'),
                ('foo/bar','file'),*((name,'file') for name in facts._FILES),('','complete')]
        for n,(point,kind) in enumerate(points):
            with self.subTest(point=point,kind=kind):
                parent=self.root/('case-'+str(n));parent.mkdir();self.target=parent/'published'
                self.value['destination']=dict(path=str(self.target),parent_chain=binding(parent)['parent_chain']);self.refresh()
                result=self.child(point,kind);self.assertEqual(result.returncode,78,result.stderr+result.stdout)
                self.assertEqual(result.stdout,'')
                with self.assertRaisesRegex(StudyError,'destination-exists'):self.call()
                complete=kind=='complete' or point=='study-runtime-readback.json'
                if complete:
                    with facts.inspect_bundle(str(self.target)):pass
                else:
                    with self.assertRaises(facts.InstallationFactsError):
                        with facts.inspect_bundle(str(self.target)):pass

    def test_competing_real_publishers(self):
        args=[sys.executable,'-B','-c',PUBLISH,str(self.request),self.digest,'','']
        processes=[subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        responses=[]
        for process in processes:
            out,err=process.communicate(timeout=30);self.assertEqual(err,'');responses.append((process.returncode,json.loads(out)))
        self.assertEqual(sorted(code for code,_ in responses),[0,2])
        self.assertIn(next(value['error'] for code,value in responses if code),('busy','destination-exists'))

    def test_plain_run_and_noninstalled_initialize_refuse(self):
        for args,expected in [(['run','--directory','/nonexistent'],'execution-contract-not-frozen'),
            (['run','--initialize-local','--directory','/nonexistent'],'installation-unavailable')]:
            out=io.StringIO()
            with redirect_stdout(out):code=main(args)
            self.assertEqual(code,2);self.assertEqual(json.loads(out.getvalue())['error'],expected)

    def test_actual_installed_cli_initialization_and_restart(self):
        fullroot=self.root/'full';fullroot.mkdir();fixture=Fixture(fullroot,full=True)
        self.value.update(source_directory=binding(fixture.source),roots=fixture.locator['roots'],
            **{key:fixture.locator[key] for key in ('source_manifest','commit_object','profile','qualification')})
        self.refresh();self.call()
        creation=fullroot/'creation'/'study';creation.mkdir()
        request=fullroot/'fresh.json';request.write_bytes(encode(sample()))
        def cli(*args,point=''):
            return subprocess.run([sys.executable,'-B','-c',CLI,point,*args],cwd=self.target/'source',
                capture_output=True,text=True)
        result=cli('create','--directory',str(creation),'--request',str(request),'--sha256',sha256(request.read_bytes()).hexdigest())
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        original={str(p):p.read_bytes() for p in creation.rglob('*') if p.is_file()}
        # A durable store receipt is followed by an actual abrupt process exit.
        result=cli('run','--initialize-local','--directory',str(creation),point='0003-core-receipt.json')
        self.assertEqual(result.returncode,78,result.stderr+result.stdout)
        responses=[]
        for _ in range(2):
            result=cli('run','--initialize-local','--directory',str(creation))
            self.assertEqual(result.returncode,0,result.stderr+result.stdout);responses.append(json.loads(result.stdout))
        self.assertEqual(responses[0],responses[1]);self.assertFalse(responses[0]['execution_performed'])
        self.assertEqual(original,{str(p):p.read_bytes() for p in creation.rglob('*') if p.is_file()})
        self.assertEqual(len(list((fullroot/'runtime').glob('*/core.sqlite3'))),1)
        self.assertEqual(len(list((fullroot/'runtime').glob('*/*.sqlite3'))),4)
        outside=cli('run','--initialize-local','--directory',str(fullroot))
        self.assertEqual(outside.returncode,2);self.assertEqual(json.loads(outside.stdout)['error'],'invalid-request')
        plain=cli('run','--directory',str(creation));self.assertEqual(plain.returncode,2)
        # Valid /1 persistence with explicitly synthetic catalog evidence is rejected by /2 initializer.
        from tests.v3.study.test_direct import sample as reuse_sample, SYNTHETIC
        from auto_g16.study.service import operate
        reused=fullroot/'creation'/'historical';reused.mkdir()
        request.write_bytes(encode(reuse_sample()))
        with patch('auto_g16.study._catalog.verify',return_value=SYNTHETIC):
            operate('create',str(reused),request_path=str(request),request_sha256=sha256(request.read_bytes()).hexdigest())
        before={str(p):p.read_bytes() for p in (fullroot/'runtime').rglob('*') if p.is_file()}
        rejected=cli('run','--initialize-local','--directory',str(reused))
        self.assertEqual(rejected.returncode,2);self.assertNotIn('installation-unavailable',rejected.stdout)
        self.assertEqual(before,{str(p):p.read_bytes() for p in (fullroot/'runtime').rglob('*') if p.is_file()})

    def test_late_target_inventory_addition_refuses_success(self):
        original=facts._SourceTree.check
        added=[]
        def check(tree):
            original(tree)
            if tree.source==str(self.fixture.source) and not added:
                added.append(True);(self.target/'installation'/'unexpected').write_bytes(b'retained')
        with patch.object(facts._SourceTree,'check',check):
            with self.assertRaises(StudyError):self.call()
        self.assertTrue((self.target/'installation'/'unexpected').exists())

    def test_bound_initialization_rejects_replacement_before_writes(self):
        from auto_g16.study._runtime_initialization import _initialize_bound
        from auto_g16.study.service import operate
        creation=self.root/'creation'/'study';creation.mkdir()
        request=self.root/'fresh.json';request.write_bytes(encode(sample()))
        operate('create',str(creation),request_path=str(request),request_sha256=sha256(request.read_bytes()).hexdigest())
        root=self.root/'runtime';runtime_chain=binding(root)['parent_chain'];creation_chain=binding(creation)['parent_chain']
        root.rename(self.root/'runtime-retained');root.mkdir()
        with self.assertRaises(StudyError):
            _initialize_bound(str(creation),str(root),creation_chain=creation_chain,runtime_chain=runtime_chain)
        self.assertEqual(list(root.iterdir()),[])
        self.assertEqual(list((self.root/'runtime-retained').iterdir()),[])
        with self.assertRaises(StudyError):
            _initialize_bound(str(creation),str(root),creation_chain=[[0,1]],runtime_chain=binding(root)['parent_chain'])
        self.assertEqual(list(root.iterdir()),[])

    def test_bad_manifest_classification(self):
        manifest=self.fixture.install/'source-manifest.json';manifest.write_bytes(b'{')
        self.value['source_manifest']=binding(manifest,True);self.refresh()
        with self.assertRaisesRegex(StudyError,'^invalid-installation$'):self.call()
        self.assertFalse(self.target.exists())

    def test_parent_replacement_stops_before_target_write(self):
        parent=self.root/'parent';parent.mkdir();self.target=parent/'published'
        self.value['destination']=dict(path=str(self.target),parent_chain=binding(parent)['parent_chain']);self.refresh()
        original=subject.fcntl.flock
        def lock(fd,op):
            result=original(fd,op)
            parent.rename(self.root/'parent-retained');parent.mkdir();(parent/'sentinel').write_bytes(b'keep')
            return result
        with patch.object(subject.fcntl,'flock',lock):
            with self.assertRaises(StudyError):self.call()
        self.assertEqual([p.name for p in parent.iterdir()],['sentinel'])
        self.assertEqual(list((self.root/'parent-retained').iterdir()),[])

    def test_creation_root_replacement_before_pin_has_zero_runtime_write(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from auto_g16.study.service import operate
        root=self.root/'creation';creation=root/'study';creation.mkdir()
        request=self.root/'fresh.json';request.write_bytes(encode(sample()))
        operate('create',str(creation),request_path=str(request),request_sha256=sha256(request.read_bytes()).hexdigest())
        fixed=SimpleNamespace(roots=dict(creation=binding(root),runtime=binding(self.root/'runtime')))
        # Loader facts refer to original root. Replace it before CLI opens the selected child.
        @contextmanager
        def loaded():
            root.rename(self.root/'creation-retained');root.mkdir()
            import shutil
            shutil.copytree(self.root/'creation-retained'/'study',creation)
            yield fixed
        with patch.object(facts,'load_installed_runtime',loaded):
            with self.assertRaisesRegex(StudyError,'identity-drift'):subject.initialize_installed(str(creation))
        self.assertEqual(list((self.root/'runtime').iterdir()),[])

    def test_cleanup_preserves_original_and_does_not_stick_lock(self):
        close=os.close;failed=[]
        def close_failure(fd):
            close(fd)
            if not failed:failed.append(fd);raise OSError('sensitive')
        with patch.object(subject.os,'write',return_value=0),patch.object(subject.os,'close',close_failure):
            with self.assertRaisesRegex(StudyError,'installation-publication-failed') as caught:self.call()
        self.assertIn('invalid-installation',caught.exception.__notes__)
        self.value['destination']['path']=str(self.root/'another');self.refresh()
        self.call()
