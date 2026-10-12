import base64
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from auto_g16.query import QueryError
from autog_frontend.local_import import parse_log,import_folder
from autog_frontend.archive_outcome import ArchiveParseOutcome
from autog_frontend.archive import ArchiveQuery,LOCAL_SCHEMA
from autog_frontend.details import DetailQuery,full_result
from autog_frontend.vibrations import build_modes
from autog_frontend.library import LibraryManager,LiveArchives,capture_completed
from autog_frontend.history_links import build_links,project_links
from autog_frontend.log_window import read_window
from autog_frontend.api import create_app
from .test_api import TestClient,TOKEN
from .result_fixture import PREFIX,FREQUENCY
from .test_vibrations import GEOMETRY,VECTORS

EXIT=b' Leave Link  101 at Fri Sep 25 10:00:00 2026, MaxMem=  536870912 cpu:  0.1 elap:  0.2\n (Enter /opt/g16/l202.exe)\n'
NORMAL=b' Normal termination of Gaussian 16\n'
def parse(raw):return parse_log(raw,'sample.log','Test archive','2026-09-25T00:00:00Z')

class ParserCompatibilityTests(unittest.TestCase):
    def test_attributed_variants_and_exact_offsets(self):
        for link in (b'202',b'103',b'123'):
            for newline in (b'\n',b'\r\n'):
                raw=(PREFIX.replace(b' GradGradGrad\n',EXIT.replace(b'l202',b'l'+link))+GEOMETRY+FREQUENCY+VECTORS+NORMAL).replace(b'\n',newline)
                r,p,o=parse(raw);self.assertEqual(r['parser']['status'],'parsed');self.assertEqual(r['summary']['energy_hartree'],-75)
                self.assertEqual(ArchiveParseOutcome.from_payload(p).result_id,o.result_id)
                self.assertEqual(p['facts']['source_artifact']['sha256'],sha256(raw).hexdigest())
                span=p['facts']['termination_evidence'][0]['source_span'];self.assertIn(b'Normal termination',raw[span['start']:span['end']])
    def test_checkpoint_requires_link101_and_charge(self):
        good=PREFIX.replace(b' Symbolic Z-matrix:',b' (Enter /opt/g16/l101.exe)\n Structure from the checkpoint file:  "previous.chk"').replace(b' GradGradGrad\n',EXIT)+NORMAL
        self.assertEqual(parse(good)[0]['parser']['status'],'parsed')
        for bad in (good.replace(b' (Enter /opt/g16/l101.exe)\n',b''),good.replace(b' Charge = 0 Multiplicity = 1\n',b''),good.replace(b' H 0.0 0.0 0.0\n',b'')):
            self.assertNotEqual(parse(bad)[0]['parser']['status'],'parsed')
    def test_exit_pair_and_downstream_failures_remain_required(self):
        good=PREFIX.replace(b' GradGradGrad\n',EXIT)+NORMAL
        for bad in (good.replace(b' (Enter /opt/g16/l202.exe)\n',b''),good.replace(b'l202',b'l999'),good.replace(b'SCF Done: E(RHF) = -75.000000',b'SCF Done: E(RHF) = NaN'),good+b' SCF Done: E(RHF) = -1.0 A.U.\n',good.replace(b' Normal termination of Gaussian 16\n',b'')):
            self.assertNotEqual(parse(bad)[0]['parser']['status'],'parsed')
    def test_adjacent_mode_headers_and_large_logs(self):
        nextgroup=FREQUENCY.split(b' 1 2 3\n',1)[1]
        raw=PREFIX+GEOMETRY+FREQUENCY+VECTORS.rstrip(b'\n')+b'\n 4 5 6\n'+nextgroup+VECTORS+NORMAL+b' '* (2*1024*1024)
        r,p,o=parse(raw);self.assertEqual(r['parser']['status'],'parsed')
        m=build_modes(dict(kind='archive',id=r['archive_id'],result=full_result(o)),raw)
        self.assertEqual(len(m['modes']),6)
        extra=VECTORS.rstrip(b'\n')+b'\n 4 1 0 0 0 0 0 0 0 0 0\n'
        raw=PREFIX+GEOMETRY+FREQUENCY+extra+NORMAL;r,p,o=parse(raw)
        with self.assertRaisesRegex(ValueError,'extra-vector-atoms'):build_modes(dict(kind='archive',id=r['archive_id'],result=full_result(o)),raw)
    def test_archive_schema_cannot_impersonate_core(self):
        r,p,o=parse(PREFIX+NORMAL);p['parser_name']='auto-g16-v3-gaussian-job'
        with self.assertRaises(ValueError):ArchiveParseOutcome.from_payload(p)

class LibraryUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.index=self.write('seed-index.json',dict(schema=LOCAL_SCHEMA,records=[]));self.catalog=self.write('seed-catalog.json',dict(schema='auto-g16-local-evidence-catalog/1',entries=[]))
        self.profile=self.write('seed-profile.json',dict(database=str(self.root/'nonexistent-Core.sqlite'),archive_index=str(self.index),archive_sha256=self.ref(self.index)['sha256'],evidence_catalog=str(self.catalog),evidence_sha256=self.ref(self.catalog)['sha256']))
        self.manager=LibraryManager(self.root/'settings.json',self.profile);self.manager.configure(dict(root=str(self.root/'library'),auto_archive=True));self.addCleanup(self.manager.close)
        self.source=self.root/'recovered';self.source.mkdir();(self.source/'result.log').write_bytes(PREFIX+NORMAL)
    def write(self,name,data):
        p=self.root/name;p.write_text(json.dumps(data));return p
    def ref(self,p):
        raw=p.read_bytes();return dict(path=str(p),sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    def test_completed_receipt_auto_archive_dedupe_and_live_refresh(self):
        before=(self.source/'result.log').read_bytes();identity=capture_completed(self.source,self.manager.config)
        with patch('subprocess.Popen',side_effect=AssertionError('No execution')):self.manager.run_once()
        self.assertEqual(self.manager.status()['jobs'][0]['state'],'archived')
        self.assertEqual(len(LiveArchives(self.manager).list_archives()['items']),1)
        current=self.manager.current_profile();self.assertEqual(capture_completed(self.source,self.manager.config),identity);self.manager.run_once();self.assertEqual(current,self.manager.current_profile())
        self.assertEqual((self.source/'result.log').read_bytes(),before);self.assertFalse((self.root/'nonexistent-Core.sqlite').exists())
        self.manager.configure(dict(root=str(self.root/'newlibrary'),auto_archive=False));self.assertEqual(self.manager.current_profile(),current)
    def test_partial_tampered_failed_then_local_only_retry(self):
        self.manager.run_once();self.assertEqual(self.manager.status()['jobs'],[])
        identity=capture_completed(self.source,self.manager.config);file=self.root/'library'/'incoming'/'captures'/identity/'result.log';original=file.read_bytes();file.write_bytes(b'partial')
        self.manager.run_once();self.assertEqual(self.manager.status()['jobs'][0]['state'],'failed');self.assertEqual(self.manager.current_profile(),self.profile)
        file.write_bytes(original);self.manager.run_once();self.assertEqual(self.manager.status()['jobs'][0]['state'],'failed')
        self.manager.retry(identity);self.manager.run_once();self.assertEqual(self.manager.status()['jobs'][0]['state'],'archived')
    def test_partial_batch_cannot_be_published_by_retry(self):
        identity=capture_completed(self.source,self.manager.config);dest=self.root/'library'/'imports'/('receipt-'+identity)
        source=self.root/'library'/'incoming'/'captures'/identity
        import_folder(source,dest,self.profile);report=json.loads((dest/'import-report.json').read_bytes());report['failures']=['result.log'];(dest/'import-report.json').write_text(json.dumps(report))
        self.manager.run_once();self.manager.retry(identity);self.manager.run_once();self.assertEqual(self.manager.status()['jobs'][0]['state'],'failed');self.assertEqual(self.manager.current_profile(),self.profile)
    def test_overlap_and_symlink_rejected(self):
        for source in (self.root,self.root/'library',self.root/'library'/'incoming'):
            with self.assertRaises(ValueError):capture_completed(source,self.manager.config)
        alias=self.root/'linked';alias.symlink_to(self.source)
        with self.assertRaises(ValueError):capture_completed(alias,self.manager.config)
    def test_api_writes_opt_in_exact_origin_and_no_calculation_routes(self):
        app=create_app(self.root/'nonexistent-Core.sqlite',token=TOKEN,library_manager=self.manager)
        c=TestClient(app,base_url='http://localhost',headers={'Authorization':'Bearer '+TOKEN})
        body=dict(root=str(self.root/'library'),auto_archive=False)
        self.assertEqual(c.post('/api/library/settings',json=body).status_code,403)
        headers={'Origin':'http://localhost','X-Autog-Library':'library/1'}
        self.assertEqual(c.post('/api/library/settings',json=body,headers=headers).status_code,200)
        self.assertEqual(c.post('/api/library/settings',json=body,headers={**headers,'Origin':'https://other.test'}).status_code,403)
        self.assertEqual(c.post('/api/submit',json={},headers=headers).status_code,405)
        self.assertEqual(c.post('/api/library/capture',json={'source':str(self.source)},headers=headers).status_code,200)
        plain=TestClient(create_app(self.root/'nonexistent-Core.sqlite',token=TOKEN),base_url='http://localhost',headers={'Authorization':'Bearer '+TOKEN})
        self.assertEqual(plain.post('/api/library/settings',json=body,headers=headers).status_code,405)
    def test_large_log_windows_offsets_search_hash_and_readonly(self):
        raw=PREFIX+NORMAL+b' filler line\r\n'*180000+' 非 ASCII\n'.encode();(self.source/'result.log').write_bytes(raw)
        identity=capture_completed(self.source,self.manager.config);self.manager.run_once();a,q=self.manager.queries();archive='archive-'+sha256(raw).hexdigest()
        before=self.manager.current_profile().read_bytes();w=read_window(q,'archive',archive,'page','120','120');self.assertEqual(w['first_line'],120);self.assertLess(len(w['text']),3000)
        lo=raw.index(b'SCF Done');hi=raw.index(b'\n',lo)+1;w=read_window(q,'archive',archive,'span',str(lo),str(hi),sha256(raw).hexdigest());self.assertEqual(w['text'].encode(),raw[lo:hi])
        needle=base64.urlsafe_b64encode('非 ASCII'.encode()).decode().rstrip('=');w=read_window(q,'archive',archive,'find','last','120',term=needle);self.assertEqual(w['match_count'],1);self.assertIn('非 ASCII',w['text'])
        with self.assertRaises(QueryError):read_window(q,'archive',archive,'span',str(lo),str(hi),'0'*64)
        with self.assertRaises(QueryError):read_window(q,'archive',archive,'page','9999999','120')
        self.assertEqual(before,self.manager.current_profile().read_bytes())
        entry=q._entry('archive',archive);Path(entry['log']['path']).write_bytes(b'changed')
        with self.assertRaises(QueryError):read_window(q,'archive',archive,'page')
    def test_history_input_hash_does_not_fabricate_log_task_binding(self):
        inp=self.source/'input.gjf';inp.write_text('#p hf/sto-3g\n\ninput\n\n0 1\nH 0 0 0\n\n')
        self.write('unused.json',{})
        intent=self.source/'submission-intent.json';intent.write_text(json.dumps(dict(schema='gaussian-submission-intent/1',input_sha256=self.ref(inp)['sha256'],attempt_id='historical-attempt',scientific_task_id='historical-task')))
        identity=capture_completed(self.source,self.manager.config);self.manager.run_once();a,q=self.manager.queries();archive=a.list_archives()['items'][0]['archive_id'];view=q.get_history_links(archive)
        c=view['candidates'][0];self.assertEqual(c['input_binding'],'sha256-verified');self.assertEqual(c['log_binding'],'unknown');self.assertEqual(c['native_core_binding'],'unknown');self.assertEqual(c['inputs'][0]['text'],inp.read_text())
        self.assertIsNone(a.get_archive(archive)['data']['input'])
        packet=json.loads(Path(q._entry('archive',archive)['history_links']['path']).read_bytes());packet['candidates'][0]['claims']['attempt_id']='fabricated'
        with self.assertRaises(ValueError):project_links(packet,archive)

class ReparseTests(unittest.TestCase):
    setUp=LibraryUpgradeTests.setUp
    write=LibraryUpgradeTests.write
    ref=LibraryUpgradeTests.ref
    def test_new_version_keeps_previous_bytes_and_profile(self):
        from autog_frontend.reparse import reparse
        capture_completed(self.source,self.manager.config);self.manager.run_once()
        previous=self.manager.current_profile();data=json.loads(previous.read_bytes())
        preserved={str(p):p.read_bytes() for p in previous.parent.rglob('*') if p.is_file()}
        dest=self.root/'reparsed';report=reparse(previous,dest,previous.parent/'import-report.json')
        self.assertEqual(report['statuses'],{'parsed':1});self.assertTrue(report['old_results_preserved'])
        self.assertEqual(preserved,{name:Path(name).read_bytes() for name in preserved})
        self.assertEqual(self.manager.current_profile(),previous)
        with self.assertRaises(ValueError):reparse(previous,dest)
