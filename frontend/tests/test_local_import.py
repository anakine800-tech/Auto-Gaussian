import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autog_frontend.archive import ArchiveQuery, SCHEMA, LOCAL_SCHEMA, validate_index, read_pinned, LIMIT
from autog_frontend.local_import import parse_log, import_folder
from autog_frontend.archive_import import build_archive_evidence
from autog_frontend.details import DetailQuery
from .archive_fixture import archive_capture


class LocalImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.source = self.root/'source'; self.source.mkdir()
        capture = archive_capture(self.source, frequency=True)
        self.raw = (self.source/'synthetic.log').read_bytes()
        self.old, parsed = build_archive_evidence(capture)
        self.index = self.root/'old-index.json'; self.index.write_text(json.dumps(dict(schema=SCHEMA,records=[self.old])))
        self.catalog = self.root/'old-catalog.json'; self.catalog.write_text(json.dumps(dict(schema='auto-g16-local-evidence-catalog/1',entries=[])))
        self.profile = self.root/'profile.json';self.profile.write_text(json.dumps(dict(database=str(self.root/'absent.sqlite'),archive_index=str(self.index),archive_sha256=self.hash(self.index),evidence_catalog=str(self.catalog),evidence_sha256=self.hash(self.catalog),port=8767)))
    def hash(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def make(self,raw=None):return parse_log(self.raw if raw is None else raw,'local.log','Local fixture','2026-09-25T00:00:00Z')
    def test_log_only_contract_preserves_unknown_bindings_and_v1_rejects(self):
        r,p,o=self.make();validate_index(dict(schema=LOCAL_SCHEMA,records=[r]));self.assertIsNone(r['input']);self.assertIsNone(r['legacy_metadata']);self.assertTrue(all(v=='unavailable' for v in r['authority'].values()))
        self.assertEqual(r['summary']['imaginary_count'],1)
        with self.assertRaises(ValueError):validate_index(dict(schema=SCHEMA,records=[r]))
        for key,value in [('input',dict(text='',binding='legacy-job-input-hash-matched')),('legacy_metadata',{}),('authority',{})]:
            changed=copy.deepcopy(r);changed[key]=value
            with self.assertRaises(ValueError):validate_index(dict(schema=LOCAL_SCHEMA,records=[changed]))
    def test_unparsed_log_is_archived_without_fabricated_summary(self):
        r,_,_=self.make(b'not a valid Gaussian output');self.assertIsNone(r['summary']);self.assertNotEqual(r['parser']['status'],'parsed')
    def test_import_deduplicates_preserves_previous_and_does_not_follow_links(self):
        (self.source/'duplicate.log').write_bytes(self.raw)
        (self.source/'new.log').write_bytes(b'Gaussian incomplete output')
        (self.source/'empty.out').write_bytes(b'')
        (self.source/'keep.chk').write_bytes(b'checkpoint')
        (self.source/'alias.log').symlink_to(self.source/'new.log')
        before={p.name:self.hash(p) for p in self.source.iterdir() if p.is_file() and not p.is_symlink()}
        dest=self.root/'data'/'batch';report=import_folder(self.source,dest,self.profile)
        self.assertEqual(report['unique_nonempty_logs'],2);self.assertEqual(report['indexed_archives'],2);self.assertEqual(report['failures'],[])
        self.assertEqual(before,{p.name:self.hash(p) for p in self.source.iterdir() if p.is_file() and not p.is_symlink()})
        index=json.loads((dest/'archive-index.json').read_bytes());self.assertIn(self.old,index['records'])
        entries=json.loads((dest/'import-report.json').read_bytes())['files'];self.assertIn('retained-at-source-not-copied',[e['status'] for e in entries]);self.assertIn('excluded-nonregular',[e['status'] for e in entries])
        with self.assertRaises(ValueError):import_folder(self.source,dest,self.profile)
        self.assertFalse((self.root/'absent.sqlite').exists())
    def test_large_log_details_and_explicit_inline_limit_without_parse_on_get(self):
        raw=self.raw+b' '* (2*1024*1024);r,p,o=self.make(raw)
        index=self.root/'index.json';index.write_text(json.dumps(dict(schema=LOCAL_SCHEMA,records=[r])))
        log=self.root/'large.log';log.write_bytes(raw);parsed=self.root/'parsed.json';parsed.write_text(json.dumps(p))
        def ref(p):return dict(path=str(p),sha256=self.hash(p),size_bytes=p.stat().st_size)
        catalog=self.root/'catalog.json';catalog.write_text(json.dumps(dict(schema='auto-g16-local-evidence-catalog/1',entries=[dict(kind='archive',id=r['archive_id'],log=ref(log),parse_outcome=ref(parsed))])))
        q=DetailQuery(self.root/'absent.sqlite',ArchiveQuery(index,self.hash(index)),catalog,self.hash(catalog))
        with patch('autog_frontend.local_import.GaussianJobParser.parse',side_effect=AssertionError('GET parsed')):
            detail=q.get_details('archive',r['archive_id']);self.assertIsNone(detail['context']['input']);self.assertIsNone(detail['context']['lineage']['attempt_id'])
            self.assertEqual(q.get_log('archive',r['archive_id'])['log']['reason'],'log-exceeds-inline-limit')
        parsed.write_text('{}')
        with self.assertRaises(Exception):q.get_details('archive',r['archive_id'])
    def test_oversized_pin_default_limit_and_symlink_are_rejected(self):
        p=self.root/'big';p.write_bytes(b'a'*(LIMIT+1))
        with self.assertRaises(ValueError):read_pinned(p,self.hash(p))
        self.assertEqual(len(read_pinned(p,self.hash(p),limit=LIMIT+1)),LIMIT+1)
        link=self.root/'link';link.symlink_to(p)
        with self.assertRaises(ValueError):read_pinned(link,self.hash(p),limit=LIMIT+1)
