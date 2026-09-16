"""Synthetic ELF and loader-mapping checks; never execute an ELF here."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import copy
import os
import struct
import sys
import errno
import base64
from hashlib import sha256
import unittest
from unittest.mock import patch

from auto_g16.execution import _crest_loader as loader

LOADER_REVIEW = b'SYNTHETIC ONLY: bounded CPU internal tblite review; no real binary qualified.\n'
LOADER_EVIDENCE = b'SYNTHETIC ONLY: loader closure evidence; no target observed.\n'


def elf_bytes(*, interpreter='', needed=(), soname=''):
    table=bytearray(b'\0');entries=[]
    for name in needed:
        entries.append((1,len(table)));table.extend(name.encode()+b'\0')
    if soname:
        entries.append((14,len(table)));table.extend(soname.encode()+b'\0')
    entries.extend(((5,1024),(10,len(table)),(0,0)))
    dynamic=b''.join(struct.pack('<qQ',*v) for v in entries)
    phnum=3 if interpreter else 2
    raw=bytearray(2048);raw[:16]=b'\x7fELF\x02\x01\x01'+bytes(9)
    raw[16:64]=struct.pack('<HHIQQQIHHHHHH',3,62,1,0,64,0,0,64,56,phnum,0,0,0)
    segments=[(1,4,0,0,0,len(raw),len(raw),4096),(2,4,512,512,0,len(dynamic),len(dynamic),8)]
    if interpreter:
        content=interpreter.encode()+b'\0';raw[256:256+len(content)]=content
        segments.append((3,4,256,256,0,len(content),len(content),1))
    for i,segment in enumerate(segments):raw[64+i*56:120+i*56]=struct.pack('<IIQQQQQQ',*segment)
    raw[512:512+len(dynamic)]=dynamic;raw[1024:1024+len(table)]=table
    return bytes(raw)


def qualification_closure(root_entry,host_key):
    """Explicit inert qualification data; cannot pass a real target guard."""
    ns=loader._namespace();identity=ns['cl_id']
    interpreter='/opt/auto-g16-fixtures/lib/ld.so'
    metadata={'class':64,'endian':'little','machine':62,'type':3,'interpreter':'','needed':[],'soname':'','rpath':'','runpath':''}
    data=[{**root_entry,'device':1,'inode':2,'elf':{**metadata,'interpreter':interpreter}},
          {'path':interpreter,'sha256':'d'*64,'size_bytes':13,'device':1,'inode':3,'elf':metadata}]
    objects=[{'object_id':identity(o),**o} for o in data]
    def alias(path,absent=False):
        parts=path[1:].split('/');nodes=[{'path':'/','kind':'directory','device':1,'inode':1,'link_target':''}]
        for i in range(len(parts)-(1 if absent else 0)):
            nodes.append({'path':'/'+('/'.join(parts[:i+1])),'kind':'regular' if i==len(parts)-1 else 'directory','device':1,'inode':i+2,'link_target':''})
        value={'requested_path':path,'canonical_path':'' if absent else path,'state':'absent' if absent else 'present','nodes':nodes}
        return {'alias_id':identity(value),**value}
    aliases=[alias(o['path']) for o in objects]
    result={'schema':'v31-crest-loader-closure/1','host_key':host_key,'root_object_id':objects[0]['object_id'],'interpreter_alias_id':aliases[1]['alias_id'],
            'objects':sorted(objects,key=lambda o:o['path']),'aliases':sorted(aliases,key=lambda a:(a['requested_path'],a['alias_id'])),'needed_edges':[],
            'selectors':[{'path':p,'state':'absent','alias':alias(p,True),'file':{}} for p in ('/etc/ld.so.cache','/etc/ld.so.preload')],
            'trace':{'objects':[{'name':'','path':interpreter}],'kernel_objects':['linux-vdso.so.1'],'searches':[]},
            'loading_policy':{'route':'cpu-internal-tblite','plugin_policy':'none','environment_policy':'no-ld-overrides','trace_policy':'direct-ld-trace-before-child-and-publication','dynamic_loading_review_sha256':sha256(LOADER_REVIEW).hexdigest()},'evidence_manifest_sha256':sha256(LOADER_EVIDENCE).hexdigest()}
    return ns['cl_validate'](result)


class CrestLoaderTests(unittest.TestCase):
    def setUp(self):
        folder=TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.interpreter=self.root/'ld.so';self.interpreter.write_bytes(elf_bytes())
        self.library=self.root/'libfixture.so.1';self.library.write_bytes(elf_bytes(soname='libfixture.so'))
        self.alias=self.root/'libfixture.so';self.alias.symlink_to(self.library.name)
        self.executable=self.root/'crest';self.executable.write_bytes(elf_bytes(interpreter=str(self.interpreter),needed=('libfixture.so',)))
        self.ns=loader._namespace()
        self.trace={'objects':[{'name':'libfixture.so','path':str(self.alias)},{'name':'','path':str(self.interpreter)}],'kernel_objects':['linux-vdso.so.1'],'searches':[]}
        self.ns['cl_trace']=lambda path,expected,interpreter:copy.deepcopy(self.trace)

    def observe(self):
        return self.ns['cl_observe'](str(self.executable),'a'*64,'b'*64,'c'*64)

    def test_complete_recursive_closure_aliases_and_guard(self):
        value=self.observe()
        self.assertEqual(len(value['objects']),3)
        self.assertEqual(len(value['needed_edges']),1)
        alias=next(a for a in value['aliases'] if a['requested_path']==str(self.alias))
        self.assertTrue(any(n['link_target']==self.library.name for n in alias['nodes']))
        self.ns['cl_guard'](str(self.executable),value)

    def test_missing_edge_extra_object_wrong_policy_reject(self):
        value=self.observe()
        bad=copy.deepcopy(value);bad['needed_edges']=[]
        with self.assertRaises(ValueError):self.ns['cl_validate'](bad)
        bad=copy.deepcopy(value);bad['loading_policy']['plugin_policy']='ambient'
        with self.assertRaises(ValueError):self.ns['cl_validate'](bad)
        bad=copy.deepcopy(value);bad['objects'][0]['inode']+=1
        with self.assertRaises(ValueError):self.ns['cl_validate'](bad)
        self.trace['objects'].insert(0,{'name':'unrelated.so','path':str(self.executable)})
        with self.assertRaises(ValueError):self.observe()

    def test_alias_same_bytes_replacement_and_trace_shadow_reject(self):
        value=self.observe()
        other=self.root/'other.so';other.write_bytes(self.library.read_bytes())
        self.trace['objects'][0]['path']=str(other)
        with self.assertRaises(ValueError):self.ns['cl_guard'](str(self.executable),value)
        self.trace['objects'][0]['path']=str(self.alias)
        previous=self.root/'old-lib.so';self.library.rename(previous);self.library.write_bytes(previous.read_bytes())
        with self.assertRaises(ValueError):self.ns['cl_guard'](str(self.executable),value)

    def test_elf_bounds_architecture_and_missing_needed_reject(self):
        self.executable.write_bytes(b'not ELF')
        with self.assertRaises(ValueError):self.observe()
        raw=bytearray(elf_bytes(interpreter=str(self.interpreter)));raw[18:20]=struct.pack('<H',183)
        self.executable.write_bytes(raw)
        with self.assertRaises(ValueError):self.observe()
        self.executable.write_bytes(elf_bytes(interpreter=str(self.interpreter),needed=('unresolved.so',)))
        with self.assertRaises(ValueError):self.observe()

    def test_exact_direct_trace_env_fd_and_output_grammar(self):
        ns=loader._namespace();expected=ns['cl_file'](str(self.executable),True)
        interpreter=ns['cl_file'](str(self.interpreter),True)
        ns['cl_no_secure']=lambda fd:None
        raw=f' linux-vdso.so.1 (0x123)\n libfixture.so => {self.alias} (0x234)\n {self.interpreter} (0x345)\n'.encode()
        debug=f' 99: find library=libfixture.so [0]; searching\n 99: search path={self.root} (RPATH from file {self.executable})\n 99: trying file={self.alias}\n 99:\n'.encode()
        self.trace['searches']=ns['cl_searches'](debug)
        calls=[]
        def run(argv,**kwargs):
            calls.append(kwargs)
            self.assertEqual(kwargs['env'],{'LD_TRACE_LOADED_OBJECTS':'1','LD_DEBUG':'libs'})
            self.assertEqual(kwargs['executable'],'/proc/self/fd/'+str(kwargs['pass_fds'][0]))
            self.assertEqual(os.fstat(kwargs['pass_fds'][0]).st_ino,expected['inode'])
            return 0,raw,debug
        ns['cl_bounded_process']=run
        self.assertEqual(ns['cl_trace'](str(self.executable),expected,interpreter),self.trace)
        for bad in (b'libfixture.so => not found\n',raw+raw,b'warning\n'):
            ns['cl_bounded_process']=lambda *args,**kwargs:(0,bad,b'')
            with self.assertRaises(ValueError):ns['cl_trace'](str(self.executable),expected,interpreter)
        self.assertEqual(len(calls),1)

    def test_origin_spelling_and_different_soname_aliases(self):
        folder=self.root/'bin';folder.mkdir()
        self.library.write_bytes(elf_bytes(soname='libopenblas.so.0'))
        second=self.root/'libblas.so';second.symlink_to(self.library.name)
        self.executable.write_bytes(elf_bytes(interpreter=str(self.interpreter),needed=('libfixture.so','libblas.so')))
        self.trace['objects'][0]['path']=str(folder)+'/.././libfixture.so'
        self.trace['objects'].insert(1,{'name':'libblas.so','path':str(second)})
        value=self.observe();self.assertEqual(len(value['objects']),3)
        self.assertEqual(len(value['needed_edges']),2)
        self.assertIn('/.././',value['trace']['objects'][0]['path'])

    def test_symlink_then_dotdot_preserves_physical_walk(self):
        (self.root/'a').mkdir();(self.root/'b').mkdir();(self.root/'b'/'inner').mkdir()
        (self.root/'a'/'link').symlink_to('../b/inner')
        (self.root/'b'/'object').write_bytes(b'physical')
        alias=self.ns['cl_alias'](str(self.root/'a'/'link')+'/../object')
        self.assertEqual(alias['canonical_path'],str(self.root/'b'/'object'))

    def test_interpreter_needed_edge_uses_observed_unnamed_object(self):
        self.interpreter.write_bytes(elf_bytes(soname='ld.so'))
        self.library.write_bytes(elf_bytes(soname='libfixture.so',needed=('ld.so',)))
        value=self.observe();self.assertEqual(len(value['needed_edges']),2)

    def test_fixed_drift_rejects_before_any_trace(self):
        value=self.observe();calls=[]
        self.ns['cl_trace']=lambda *args:calls.append(True)
        original=self.executable.read_bytes();self.executable.write_bytes(original+b'changed')
        with self.assertRaises(ValueError):self.ns['cl_guard'](str(self.executable),value)
        self.assertEqual(calls,[])

    def test_bounded_pipe_and_secure_execution_reject(self):
        ns=loader._namespace()
        with self.assertRaisesRegex(ValueError,'output cap'):
            ns['cl_bounded_process']([sys.executable,'-c','import os; os.write(1,b"x"*300000)'],stdin=ns['_cl_subprocess'].DEVNULL,env={})
        fd=os.open(self.executable,os.O_RDONLY)
        try:
            os.chmod(self.executable,0o4755)
            with self.assertRaisesRegex(ValueError,'secure execution'):ns['cl_no_secure'](fd)
            os.chmod(self.executable,0o755)
            with patch.object(ns['_cl_os'],'getxattr',create=True,return_value=b'capability'),self.assertRaisesRegex(ValueError,'capabilities'):
                ns['cl_no_secure'](fd)
        finally:os.close(fd)

    def test_symlink_cycle_rejects(self):
        a=self.root/'cycle-a';b=self.root/'cycle-b';a.symlink_to(b.name);b.symlink_to(a.name)
        with self.assertRaises(ValueError):self.ns['cl_alias'](str(a))

    def test_dedup_alias_same_mapped_object_and_narrow_rejections(self):
        second=self.root/'libblas.so';second.symlink_to(self.library.name)
        self.executable.write_bytes(elf_bytes(interpreter=str(self.interpreter),needed=('libfixture.so','libblas.so')))
        search={'name':'libblas.so','events':[{'kind':'RPATH','paths':[str(self.root)],'source':str(self.executable)},{'kind':'try','path':str(second)}]}
        self.trace['searches']=[search]
        value=self.observe();self.assertEqual(len(value['objects']),3);self.assertEqual(len(value['needed_edges']),2)
        self.ns['cl_guard'](str(self.executable),value)
        for events in ([{'kind':'cache'},{'kind':'try','path':str(second)}],
                       [{'kind':'system','paths':[str(self.root)]},{'kind':'try','path':str(second)}],
                       [{'kind':'RPATH','paths':['/outside-bundle'],'source':str(self.executable)},{'kind':'try','path':str(second)}]):
            search['events']=events
            with self.assertRaises(ValueError) as caught:self.observe()
            self.assertEqual(caught.exception.loader_diagnostics['needed']['name'],'libblas.so')
        search['events']=[{'kind':'RPATH','paths':[str(self.root)],'source':str(self.executable)},{'kind':'try','path':str(second)}]
        second.unlink();second.write_bytes(self.library.read_bytes())
        with self.assertRaisesRegex(ValueError,'unique actual mapped'):self.observe()

    def test_debug_rejects_ambiguous_truncated_and_unknown_blocks(self):
        raw=f'2: find library=libfixture.so [0]; searching\n2: search path={self.root} (RPATH from file {self.executable})\n2: trying file={self.alias}\n2:\n'.encode()
        parse=self.ns['cl_searches'];self.assertEqual(len(parse(raw)),1)
        for bad in (raw+raw,raw.rstrip(),raw.replace(b'2: trying',b'3: trying'),raw.replace(b' [0];',b' [1];'),raw+b'2: warning: version missing\n',raw.replace(b'2:\n',b'')):
            with self.assertRaises(ValueError):parse(bad)

    def test_failed_trace_retains_complete_and_bounded_partial_raw(self):
        ns=loader._namespace();ns['cl_no_secure']=lambda fd:None
        ns['cl_bounded_process']=lambda *args,**kwargs:(0,b'libfixture.so => not found\n',b'2: warning\n')
        with self.assertRaises(ValueError) as caught:ns['cl_observe'](str(self.executable),'a'*64,'b'*64,'c'*64)
        diagnostic=caught.exception.loader_diagnostics
        self.assertEqual(diagnostic['phase'],'direct-trace');self.assertTrue(diagnostic['raw_trace']['complete'])
        self.assertIn('not found',diagnostic['raw_trace']['stdout'])
        with self.assertRaisesRegex(ValueError,'output cap') as caught:
            ns['cl_bounded_process']=loader._namespace()['cl_bounded_process']
            ns['cl_bounded_process']([sys.executable,'-c','import os; os.write(1,b"x"*300000)'],stdin=ns['_cl_subprocess'].DEVNULL,env={})
        self.assertFalse(caught.exception.loader_raw['complete']);self.assertLessEqual(len(caught.exception.loader_raw['stdout']),262144)
        raw=ns['cl_raw'](b'\xff\xfe',b'\x00\xff',True,0)
        self.assertEqual(base64.b64decode(raw['stdout_base64']),b'\xff\xfe')
        self.assertEqual(raw['stderr_sha256'],sha256(b'\x00\xff').hexdigest())

    def test_guard_comparison_failure_retains_diagnostics(self):
        value=self.observe();original=self.ns['cl_observe']
        def changed(*args):
            result=original(*args);self.ns['_cl_diagnostics']['raw_trace']=self.ns['cl_raw'](b'raw',b'debug',True,0)
            result['evidence_manifest_sha256']='d'*64;return result
        self.ns['cl_observe']=changed
        with self.assertRaisesRegex(ValueError,'closure drift') as caught:self.ns['cl_guard'](str(self.executable),value)
        self.assertEqual(caught.exception.loader_diagnostics['phase'],'guard-compare')
        self.assertEqual(base64.b64decode(caught.exception.loader_diagnostics['raw_trace']['stdout_base64']),b'raw')
