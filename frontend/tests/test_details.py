import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.result import ResultProvenanceService
from auto_g16.query import QueryError
from autog_frontend.archive import ArchiveQuery, SCHEMA
from autog_frontend.archive_import import build_archive_evidence, plain
from autog_frontend.details import DetailQuery, historical_review
from autog_frontend.api import create_app
from .archive_fixture import archive_capture
from .result_fixture import add_result_fixtures
from .test_api import TestClient, TOKEN


class DetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.database = self.root/'core.db'
        with core.SQLiteRuntimeStore(self.database) as store:
            add_result_fixtures(store)
        self.capture = archive_capture(self.root)
        self.record, self.parsed = build_archive_evidence(self.capture)
        self.index = self.write('index.json', {'schema': SCHEMA, 'records': [self.record]})
        parsed = self.write('parsed.json', self.parsed)
        self.entries = [{'kind':'archive','id':self.record['archive_id'],'log':self.ref(self.root/'synthetic.log'),
                         'job':self.ref(self.root/'job.json'),'parse_outcome':self.ref(parsed)}]
        self.catalog = self.write('catalog.json', {'schema':'auto-g16-local-evidence-catalog/1','entries':self.entries})

    def write(self, name, data):
        p=self.root/name; p.write_text(json.dumps(data)); return p

    def ref(self, path):
        raw=path.read_bytes(); return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}

    def query(self):
        return DetailQuery(self.database, ArchiveQuery(self.index,self.ref(self.index)['sha256']),self.catalog,self.ref(self.catalog)['sha256'])

    def test_native_full_facts_preserve_frequency_and_source_units(self):
        dto=self.query().get_details('attempt','gaussian-normal')
        self.assertEqual(dto['result']['data']['frequencies_cm1'],[-123.4,200,300])
        self.assertEqual(dto['result']['data']['thermochemistry_unit'],'Hartree')
        self.assertEqual(dto['result']['data']['geometry_unit'],'angstrom')
        self.assertEqual(dto['review']['availability'],'unavailable')

    def test_scientific_display_projects_exact_program_facts_without_validation(self):
        q=self.query();before=self.database.read_bytes()
        with core.SQLiteRuntimeStore.read_snapshot(self.database) as store:
            outcome=ResultProvenanceService(store).current_view('gaussian-normal').selected_results[-1]
            expected=plain(outcome.facts)
        with patch('subprocess.Popen',side_effect=AssertionError('process')), patch('autog_frontend.archive_import.GaussianJobParser.parse',side_effect=AssertionError('parse')):
            data=q.get_details('attempt','gaussian-normal')['result']['data']['scientific_facts']
        self.assertEqual(data['schema'],'auto-g16-scientific-display-facts/1')
        for key,value in data.items():
            if key!='schema':self.assertEqual(value,expected[key])
        self.assertEqual(data['imaginary_frequency_count'],1)
        self.assertNotIn('classification',data)
        self.assertEqual(self.database.read_bytes(),before)
        missing=q.get_details('attempt','gaussian-no-frequency')['result']['data']['scientific_facts']
        self.assertEqual(missing['frequency_count'],0)
        self.assertEqual(q.get_details('attempt','gaussian-error')['result']['data']['scientific_facts']['program_status'],'error-termination')

    def test_archive_log_matches_bytes_and_queries_do_not_parse_or_execute(self):
        q=self.query(); before=self.ref(self.database)
        with patch('autog_frontend.archive_import.GaussianJobParser.parse',side_effect=AssertionError('parse')), patch('subprocess.Popen',side_effect=AssertionError('process')):
            details=q.get_details('archive',self.record['archive_id'])
            log=q.get_log('archive',self.record['archive_id'])
        self.assertEqual(log['log']['data']['text'],(self.root/'synthetic.log').read_text())
        self.assertEqual(details['execution']['source']['kind'],'legacy-job-sidecar')
        self.assertEqual(details['context']['lineage']['scope'],'legacy-archive-not-core-lineage')
        self.assertIsNone(details['context']['lineage']['attempt_id'])
        self.assertEqual(details['context']['lineage']['result_source'],details['result']['source'])
        self.assertEqual(self.ref(self.database),before)

    def test_modified_log_catalog_and_cross_identity_are_rejected(self):
        q=self.query()
        (self.root/'synthetic.log').write_text('changed')
        with self.assertRaises(QueryError):q.get_log('archive',self.record['archive_id'])
        self.catalog.write_text('{}')
        with self.assertRaises(QueryError):q.get_details('archive',self.record['archive_id'])

    def test_source_index_parser_and_frequency_disagreements_are_rejected(self):
        self.record['summary']['frequency_count']=42; self.record['summary']['imaginary_count']=12
        self.write('index.json',{'schema':SCHEMA,'records':[self.record]})
        with self.assertRaises(QueryError):self.query().get_details('archive',self.record['archive_id'])
        self.record['summary']['frequency_count']=None; self.record['summary']['imaginary_count']=None
        self.record['parser']['diagnostics']=['different']
        self.write('index.json',{'schema':SCHEMA,'records':[self.record]})
        with self.assertRaises(QueryError):self.query().get_details('archive',self.record['archive_id'])

    def test_http_inherits_auth_method_and_catalog_is_not_request_selectable(self):
        app=create_app(self.database,token=TOKEN,archive_index=self.index,archive_sha256=self.ref(self.index)['sha256'],evidence_catalog=self.catalog,evidence_sha256=self.ref(self.catalog)['sha256'])
        client=TestClient(app,base_url='http://localhost',headers={'Authorization':'Bearer '+TOKEN})
        uri='/api/archives/'+self.record['archive_id']+'/log'
        self.assertEqual(client.get(uri).status_code,200)
        self.assertEqual(client.post(uri).status_code,405)
        self.assertEqual(client.get(uri+'?path=/etc/passwd').status_code,400)
        self.assertEqual(TestClient(app,base_url='http://localhost').get(uri).status_code,401)
        self.assertNotIn(str(self.root),client.get(uri).text)
        with patch('autog_frontend.details.DetailQuery.get_log', side_effect=QueryError('response-too-large')):
            self.assertEqual(client.get(uri).status_code,413)

    def test_missing_source_and_unsupported_result_remain_unavailable(self):
        q=DetailQuery(self.database,ArchiveQuery(None,None))
        self.assertEqual(q.get_log('attempt','gaussian-normal')['log']['availability'],'unavailable')
        for identity in ('gaussian-v31','gaussian-partial','gaussian-unknown'):
            self.assertEqual(q.get_details('attempt',identity)['result']['availability'],'unavailable')
        with self.assertRaises(QueryError):q.get_details('attempt','missing')

    def test_historical_review_cannot_cross_result_or_acceptance(self):
        with core.SQLiteRuntimeStore.read_snapshot(self.database) as store:
            view=ResultProvenanceService(store).current_view('gaussian-normal'); outcome=view.selected_results[-1]
            attempt=store.load_attempt('gaussian-normal');plan=store.load_calculation_plan(view.input_binding.calculation_plan_id)
            bad={'schema_version':1,'attempt':{'attempt_id':'different'}}
            with self.assertRaises(ValueError):historical_review(bad,view,attempt,plan,outcome,{'sha256':'a'*64,'size_bytes':1})
