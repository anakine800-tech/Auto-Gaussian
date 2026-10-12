"""Installation facts tested against independent Git objects and real imports."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.study import _installation as subject

ROOT = Path(__file__).resolve().parents[3]


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def binding(path, file=False):
    ancestors = list(reversed(path.parents)) + ([] if file else [path])
    value = dict(path=str(path), parent_chain=[[p.stat().st_dev,p.stat().st_ino] for p in ancestors],
                 file_identity=[path.stat().st_dev,path.stat().st_ino])
    if file:
        raw=path.read_bytes();value.update(sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    return value


class Fixture:
    def __init__(self, root, *, full=False):
        self.root=root; self.bundle=root/'bundle';self.source=self.bundle/'source';self.install=self.bundle/'installation'
        self.source.mkdir(parents=True);self.install.mkdir()
        if full:
            if (ROOT/'.git').exists():
                names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().strip('\0').split('\0')
            else:
                # Complete-full CI uses a Git source archive without repository metadata.
                names=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
                       if p.is_file() and '__pycache__' not in p.relative_to(ROOT).parts]
            names += [name for name in ('auto_g16/study/_installation.py', 'auto_g16/study/_local_install.py')
                      if (ROOT/name).is_file()]
            for name in sorted(set(names)):
                source=ROOT/name;target=self.source/name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        else:
            for name in subject._REQUIRED:
                target=self.source/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/name).read_bytes() if name.startswith('auto_g16/') else b'fixture\n')
            for name,data in [('foo/bar',b'\0\xff\x01'),('foo.bar',b''),('中文.txt','测试'.encode()),('executable',b'#!/bin/sh\nexit 0\n')]:
                target=self.source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            (self.source/'executable').chmod(0o755)
        self.gitdir=root/'objects'
        subprocess.run(['git','init','-q','--bare',str(self.gitdir)],check=True)
        self.git('add','-f','--','.')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','synthetic installation fixture')
        commit=self.git('rev-parse','HEAD').decode().strip();tree=self.git('rev-parse','HEAD^{tree}').decode().strip()
        entries=[]
        for item in self.git('ls-files','-s','-z').split(b'\0'):
            if not item:continue
            meta,name=item.split(b'\t');name=name.decode();raw=(self.source/name).read_bytes()
            entries.append(dict(path=name,mode=meta.split()[0].decode(),size_bytes=len(raw),sha256=sha256(raw).hexdigest()))
        self.manifest=dict(schema='auto-g16-study-source-manifest/1',source_commit=commit,source_tree=tree,
                           entries=sorted(entries,key=lambda e:e['path'].encode()))
        (self.install/'source-manifest.json').write_bytes(encode(self.manifest))
        (self.install/'git-commit.bin').write_bytes(self.git('cat-file','commit',commit))
        (self.install/'profile.json').write_bytes(b'{"opaque":"not-approved-profile"}')
        (self.install/'qualification.json').write_bytes(b'{"opaque":"not-approved-Q"}')
        roots={}
        for name in ('creation','runtime','registry'):
            path=root/name;path.mkdir();roots[name]=binding(path)
        self.locator=dict(schema='auto-g16-study-installation-locator/1',source_commit=commit,source_tree=tree,roots=roots,
            **{key:binding(self.install/name,True) for key,name in [('source_manifest','source-manifest.json'),('commit_object','git-commit.bin'),('profile','profile.json'),('qualification','qualification.json')]})
        self.refresh_locator()

    def git(self,*args):
        return subprocess.check_output(['git','--git-dir='+str(self.gitdir),'--work-tree='+str(self.source),*args],cwd=self.source)

    def refresh_locator(self):
        path=self.install/'study-runtime.json';path.write_bytes(encode(self.locator))
        self.readback=dict(schema='auto-g16-study-installation-readback/1',bundle=binding(self.bundle),
            source=binding(self.source),installation=binding(self.install),locator=binding(path,True),
            source_commit=self.manifest['source_commit'],source_tree=self.manifest['source_tree'])
        (self.install/'study-runtime-readback.json').write_bytes(encode(self.readback))

    def refresh_manifest(self):
        path=self.install/'source-manifest.json';path.write_bytes(encode(self.manifest))
        self.locator['source_manifest']=binding(path,True);self.refresh_locator()


CHILD = r'''
import json,os,sys,threading
from auto_g16.study import _installation as s
mode=sys.argv[1]
original_cwd=os.getcwd()
if mode=='cwd':os.chdir('/')
if mode=='offline':
 with s.inspect_bundle(os.path.dirname(original_cwd)) as offline:assert offline.loaded_path_consistency=='not-assessed'
 assert s._FACTS is None
if mode=='body':
 try:
  with s.load_installed_runtime():raise RuntimeError('body')
 except RuntimeError:pass
 assert s._FACTS is None
def code(call):
 try:
  with call():pass
 except s.InstallationFactsError as error:return error.code
 return 'accepted'
with s.load_installed_runtime() as first:
 assert first.loaded_path_consistency=='matched' and not first.execution_enabled
 if mode=='nested':assert code(s.load_installed_runtime)=='busy'
 if mode=='thread':
  result=[];thread=threading.Thread(target=lambda:result.append(code(s.load_installed_runtime)))
  thread.start();thread.join();assert result==['busy']
 if mode=='fork':
  pid=os.fork()
  if pid==0:os._exit(0 if code(s.load_installed_runtime)=='forked-process' else 3)
  assert os.waitpid(pid,0)[1]==0
with s.load_installed_runtime() as second:assert first is second
if mode=='exit-error':
 error=RuntimeError('original')
 try:
  with s.load_installed_runtime():
   open('foo.bar','ab').write(b'x');raise error
 except RuntimeError as caught:
  assert caught is error and caught.__notes__==['identity-drift']
 assert code(s.load_installed_runtime)=='installation-invalidated'
if mode=='close-except':
 from unittest.mock import patch
 original_close=s.os.close;calls=[]
 def closed(fd):
  original_close(fd);calls.append(fd)
  if len(calls)==1:raise OSError('close failure inside outer except')
 try:raise RuntimeError('handled outer error')
 except RuntimeError as outer:
  with patch.object(s.os,'close',closed):assert code(s.load_installed_runtime)=='invalid-installation'
  assert not hasattr(outer,'__notes__')
 assert code(s.load_installed_runtime)=='installation-invalidated'
if mode in ('close','close-body'):
 from unittest.mock import patch
 original_close=s.os.close;calls=[];error=RuntimeError('close body')
 def closed(fd):
  original_close(fd);calls.append(fd)
  if len(calls)==1:raise OSError('injected close failure')
 try:
  with patch.object(s.os,'close',closed):
   with s.load_installed_runtime():
    if mode=='close-body':raise error
 except RuntimeError as caught:
  assert mode=='close-body' and caught is error and caught.__notes__==['invalid-installation']
 except s.InstallationFactsError as caught:
  assert mode=='close' and caught.code=='invalid-installation'
 else:raise AssertionError('missing failure')
 assert len(calls)>5 and len(calls)==len(set(calls))
 assert code(s.load_installed_runtime)=='installation-invalidated'
if mode=='replace':
 p='foo.bar';raw=open(p,'rb').read();os.rename(p,p+'.old');open(p,'wb').write(raw);os.unlink(p+'.old')
 assert code(s.load_installed_runtime)=='identity-drift'
 assert code(s.load_installed_runtime)=='installation-invalidated'
if mode=='source-drift':
 p='foo.bar';open(p,'ab').write(b'x')
 assert code(s.load_installed_runtime)=='source-mismatch'
 assert code(s.load_installed_runtime)=='installation-invalidated'
if mode=='origin':
 import auto_g16;auto_g16.__spec__.origin='/foreign/__init__.py'
 assert code(s.load_installed_runtime)=='identity-drift'
 assert code(s.load_installed_runtime)=='installation-invalidated'
print(json.dumps({'ok':True,'mode':mode,'state':first.state,'enabled':first.execution_enabled}))
'''


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.fixture=Fixture(self.root)

    @contextmanager
    def inspect(self):
        with patch('socket.socket',side_effect=AssertionError('network')), \
             patch('subprocess.Popen',side_effect=AssertionError('subprocess')), \
             patch('sqlite3.connect',side_effect=AssertionError('database')), \
             patch('os.mkdir',side_effect=AssertionError('mkdir')), \
             patch('os.write',side_effect=AssertionError('write')):
            with subject.inspect_bundle(str(self.fixture.bundle)) as value:yield value

    def test_independent_git_objects_and_immutable_zero_authority_facts(self):
        before={p:p.read_bytes() for p in self.fixture.bundle.rglob('*') if p.is_file()}
        with self.inspect() as facts:
            self.assertEqual(facts.source_tree,self.fixture.manifest['source_tree'])
            self.assertEqual(facts.source_commit,self.fixture.manifest['source_commit'])
            self.assertEqual(facts.qualification_state,'not-assessed')
            self.assertFalse(facts.execution_enabled);self.assertFalse(facts.executed_code_attested)
            with self.assertRaises(TypeError):facts.roots['runtime']['path']='bad'
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertIsNone(subject._FACTS)

    def test_full_local_source_archive_against_git(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture=Fixture(Path(temp).resolve(),full=True)
            with subject.inspect_bundle(str(fixture.bundle)) as facts:
                self.assertEqual(facts.source_tree,fixture.manifest['source_tree'])
                self.assertFalse(facts.execution_enabled)

    def test_source_identity_inventory_and_mode_failures(self):
        mutations={
            'blob':lambda f:(f.source/'foo.bar').write_bytes(b'wrong'),
            'missing':lambda f:(f.source/'foo.bar').unlink(),
            'extra':lambda f:(f.source/'extra').write_bytes(b'x'),
            'directory':lambda f:(f.source/'extra').mkdir(),
            'mode':lambda f:(f.source/'foo.bar').chmod(0o755),
            'symlink':lambda f:(f.source/'foo.bar').unlink() or (f.source/'foo.bar').symlink_to('中文.txt'),
            'hardlink':lambda f:(f.source/'foo.bar').unlink() or os.link(f.source/'中文.txt',f.source/'foo.bar'),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name),tempfile.TemporaryDirectory(dir=self.root) as temp:
                fixture=Fixture(Path(temp));mutate(fixture)
                with self.assertRaises(subject.InstallationFactsError):
                    with subject.inspect_bundle(str(fixture.bundle)):pass

    def test_canonical_manifest_and_independent_tree_commit_validation(self):
        for field in ('source_tree','source_commit','duplicate','size-bool','unknown','gitlink'):
            with self.subTest(field=field),tempfile.TemporaryDirectory(dir=self.root) as temp:
                f=Fixture(Path(temp))
                if field in ('source_tree','source_commit'):f.manifest[field]='0'*40
                elif field=='duplicate':f.manifest['entries'].append(f.manifest['entries'][0])
                elif field=='size-bool':f.manifest['entries'][0]['size_bytes']=True
                elif field=='unknown':f.manifest['extra']=1
                else:f.manifest['entries'][0]['mode']='160000'
                f.refresh_manifest()
                with self.assertRaises(subject.InstallationFactsError):
                    with subject.inspect_bundle(str(f.bundle)):pass

    def test_readback_root_overlap_and_missing_do_not_repair(self):
        f=self.fixture
        f.locator['roots']['runtime']=f.locator['roots']['creation'];f.refresh_locator()
        with self.assertRaises(subject.InstallationFactsError):
            with self.inspect():pass
        (f.install/'study-runtime-readback.json').unlink()
        with self.assertRaisesRegex(subject.InstallationFactsError,'installation-unavailable'):
            with self.inspect():pass
        self.assertFalse((f.install/'study-runtime-readback.json').exists())

    def test_cache_grammar_and_no_bytecode_attestation(self):
        source=self.fixture.source/'auto_g16/study';cache=source/'__pycache__';cache.mkdir()
        tag=sys.implementation.cache_tag;p=cache/('_installation.'+tag+'.pyc');p.write_bytes(b'not-authenticated')
        with self.inspect() as facts:self.assertFalse(facts.executed_code_attested)
        for name in ('foreign.'+tag+'.pyc','_installation.foreign.pyc','_installation.'+tag+'.so','subdir'):
            with self.subTest(name=name):
                invalid=cache/name;invalid.write_bytes(b'x')
                with self.assertRaises(subject.InstallationFactsError):
                    with self.inspect():pass
                invalid.unlink()
        with self.inspect():
            p.unlink();(cache/('_installation.'+tag+'.opt-1.pyc')).write_bytes(b'new cache')

    def test_exit_drift_retains_evidence_and_original_exception(self):
        path=self.fixture.source/'foo.bar'
        with self.assertRaisesRegex(subject.InstallationFactsError,'identity-drift'):
            with self.inspect():path.write_bytes(b'external change')
        self.assertEqual(path.read_bytes(),b'external change')
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            f=Fixture(Path(temp));error=RuntimeError('body error')
            with self.assertRaises(RuntimeError) as caught:
                with subject.inspect_bundle(str(f.bundle)):
                    (f.source/'foo.bar').write_bytes(b'external change');raise error
            self.assertIs(caught.exception,error)
            self.assertEqual(error.__notes__,['identity-drift'])

    def test_final_read_returning_original_bytes_cannot_adopt_late_change(self):
        original=os.read;changed=[];path=self.fixture.install/'git-commit.bin'
        def read(fd,count):
            raw=original(fd,count)
            if os.fstat(fd).st_ino==path.stat().st_ino and raw and not changed:
                with path.open('ab') as stream:stream.write(b'x')
                changed.append(True)
            return raw
        with patch.object(subject.os,'read',read),self.assertRaises(subject.InstallationFactsError):
            with subject.inspect_bundle(str(self.fixture.bundle)):pass
        self.assertTrue(changed);self.assertTrue(path.read_bytes().endswith(b'x'))

    def test_fixed_loader_actual_child_origins_restart_drift_and_locks(self):
        for mode in ('normal','nested','thread','fork','replace','source-drift','origin','cwd','offline','body','exit-error','close','close-body','close-except'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as temp:
                f=Fixture(Path(temp));env=dict(os.environ)
                env.pop('PYTHONPATH',None);env['AUTO_G16_STUDY_INSTALLATION']='/ignored'
                result=subprocess.run([sys.executable,'-B','-c',CHILD,mode],cwd=f.source,env=env,
                                      text=True,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertFalse(json.loads(result.stdout)['enabled'])
        with self.assertRaisesRegex(subject.InstallationFactsError,'installation-unavailable'):
            with subject.load_installed_runtime():pass

    def test_parent_replacement_and_descriptor_release(self):
        collected=[];original=subject._Pins.close
        def close(pins,error=None):
            collected.extend(fd for fd,_kind,_version in pins.nodes.values());return original(pins,error)
        f=self.fixture
        with patch.object(subject._Pins,'close',close),self.assertRaisesRegex(subject.InstallationFactsError,'identity-drift'):
            with subject.inspect_bundle(str(f.bundle)):
                f.bundle.rename(self.root/'retained-bundle');f.bundle.mkdir()
                (f.bundle/'sentinel').write_bytes(b'unchanged')
        self.assertEqual({p.name for p in f.bundle.iterdir()},{'sentinel'})
        self.assertEqual((f.bundle/'sentinel').read_bytes(),b'unchanged')
        self.assertTrue(collected)
        for fd in collected:
            with self.assertRaises(OSError):os.fstat(fd)

    def test_control_canonical_caps_types_and_physical_substitution(self):
        for kind in ('duplicate','unknown','bool-identity','cap','noncanonical','replaced-profile','bad-readback','bad-commit'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory(dir=self.root) as temp:
                f=Fixture(Path(temp));path=f.install/'study-runtime.json'
                if kind=='duplicate':path.write_bytes(b'{"schema":"a","schema":"b"}')
                elif kind=='unknown':f.locator['extra']=1;f.refresh_locator()
                elif kind=='bool-identity':f.locator['profile']['file_identity'][0]=True;f.refresh_locator()
                elif kind=='cap':path.write_bytes(b' '*(2*1024*1024+1))
                elif kind=='noncanonical':path.write_bytes(json.dumps(f.locator,indent=2).encode())
                elif kind=='replaced-profile':
                    target=f.install/'profile.json';raw=target.read_bytes();target.rename(self.root/'retained-profile');target.write_bytes(raw)
                elif kind=='bad-readback':
                    f.readback['source_tree']='0'*40;(f.install/'study-runtime-readback.json').write_bytes(encode(f.readback))
                else:
                    (f.install/'git-commit.bin').write_bytes(b'not a commit')
                    f.locator['commit_object']=binding(f.install/'git-commit.bin',True);f.refresh_locator()
                with self.assertRaises(subject.InstallationFactsError):
                    with subject.inspect_bundle(str(f.bundle)):pass

    def test_cache_symlinks_subdirectories_and_hardlinks_rejected(self):
        parent=self.fixture.source/'auto_g16/study';cache=parent/'__pycache__';cache.mkdir()
        path=cache/('_installation.'+sys.implementation.cache_tag+'.pyc')
        for kind in ('directory','symlink','hardlink'):
            with self.subTest(kind=kind):
                if kind=='directory':path.mkdir()
                elif kind=='symlink':path.symlink_to(parent/'_installation.py')
                else:os.link(parent/'_installation.py',path)
                with self.assertRaises(subject.InstallationFactsError):
                    with self.inspect():pass
                if kind=='directory':path.rmdir()
                else:path.unlink()

    def test_root_fstat_failure_closes_unregistered_descriptor(self):
        opened=[];original_open=os.open
        def tracked(path,*args,**kwargs):
            fd=original_open(path,*args,**kwargs);opened.append(fd);return fd
        with patch.object(subject.os,'open',tracked), \
             patch.object(subject.os,'fstat',side_effect=OSError('root metadata failure')), \
             self.assertRaisesRegex(subject.InstallationFactsError,'invalid-installation'):
            with subject.inspect_bundle(str(self.fixture.bundle)):pass
        self.assertEqual(len(opened),1)
        with self.assertRaises(OSError):os.fstat(opened[0])

    def test_normal_inspection_inside_except_does_not_swallow_close_failure(self):
        original_close=os.close;calls=[]
        def closed(fd):
            original_close(fd);calls.append(fd)
            if len(calls)==1:raise OSError('close failure')
        try:raise RuntimeError('already handled outer exception')
        except RuntimeError as outer:
            with patch.object(subject.os,'close',closed),self.assertRaisesRegex(subject.InstallationFactsError,'invalid-installation'):
                with subject.inspect_bundle(str(self.fixture.bundle)):pass
            self.assertFalse(hasattr(outer,'__notes__'))
        self.assertGreater(len(calls),5)

    def test_first_loader_close_failure_does_not_publish_binding(self):
        script = r"""
import os
from unittest.mock import patch
from auto_g16.study import _installation as s
original=s.os.close;calls=[]
def closed(fd):
 original(fd);calls.append(fd)
 if len(calls)==1:raise OSError('injected')
try:
 with patch.object(s.os,'close',closed):
  with s.load_installed_runtime():assert s._FACTS is None
except s.InstallationFactsError as error:assert error.code=='invalid-installation'
else:raise AssertionError('failure swallowed')
assert s._FACTS is None and s._PIN_STATE is None and not s._LOCK.locked()
"""
        env=dict(os.environ);env.pop('PYTHONPATH',None)
        result=subprocess.run([sys.executable,'-B','-c',script],cwd=self.fixture.source,env=env,
                              text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_complete_archive_fixture_also_runs_without_git_metadata(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp, patch(__name__+'.ROOT',self.fixture.source):
            fixture=Fixture(Path(temp),full=True)
            with subject.inspect_bundle(str(fixture.bundle)) as facts:
                self.assertEqual(facts.source_tree,fixture.manifest['source_tree'])
