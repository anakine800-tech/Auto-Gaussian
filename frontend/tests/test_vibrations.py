import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autog_frontend.vibrations import build_modes, validate_modes
from autog_frontend.archive_import import build_archive_evidence
from autog_frontend.archive import ArchiveQuery, SCHEMA
from autog_frontend.details import DetailQuery
from autog_frontend.api import create_app
from auto_g16 import core
from auto_g16.query import QueryError
from .archive_fixture import archive_capture
from .result_fixture import PREFIX, FREQUENCY, add_result_fixtures
from .test_api import TestClient, TOKEN

GEOMETRY = b''' Standard orientation:
 ---------------------------------------------------------------------
 Center Atomic Atomic Coordinates (Angstroms)
 Number Number Type X Y Z
 ---------------------------------------------------------------------
 1 8 0 0.000000 0.000000 0.135955
 2 1 0 0.000000 0.770245 -0.543819
 3 1 0 0.000000 -0.770245 -0.543819
 ---------------------------------------------------------------------
'''
VECTORS = b''' Atom AN X Y Z X Y Z X Y Z
 1 8 0.00 0.00 -0.07 0.00 0.00 0.05 0.00 -0.07 0.00
 2 1 0.00 0.45 0.54 0.00 0.57 -0.42 0.00 0.53 -0.47
 3 1 0.00 -0.45 0.54 0.00 -0.57 -0.42 0.00 0.53 0.47

'''

class VibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.database=self.root/'core.db'
        with core.SQLiteRuntimeStore(self.database) as store:add_result_fixtures(store)
        self.make()

    def ref(self,p):
        b=p.read_bytes();return dict(path=str(p),sha256=hashlib.sha256(b).hexdigest(),size_bytes=len(b))

    def write(self,name,data):
        p=self.root/name;p.write_text(json.dumps(data));return p

    def make(self,vectors=VECTORS,gap=b''):
        capture=archive_capture(self.root,frequency=True)
        raw=PREFIX+GEOMETRY+gap+FREQUENCY+vectors+b' Normal termination of Gaussian 16\n'
        log=self.root/'synthetic.log';log.write_bytes(raw)
        entry=next(e for e in capture['files'] if e['path'].endswith('synthetic.log'))
        entry.update(size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),sha256_after=hashlib.sha256(raw).hexdigest())
        self.record,parsed=build_archive_evidence(capture)
        self.index=self.write('index.json',{'schema':SCHEMA,'records':[self.record]})
        self.entries=[dict(kind='archive',id=self.record['archive_id'],log=self.ref(log),parse_outcome=self.ref(self.write('parse.json',parsed)))]
        self.catalog=self.write('catalog.json',{'schema':'auto-g16-local-evidence-catalog/1','entries':self.entries})
        self.raw=raw;self.detail=self.query().get_details('archive',self.record['archive_id'])

    def query(self):return DetailQuery(self.database,ArchiveQuery(self.index,self.ref(self.index)['sha256']),self.catalog,self.ref(self.catalog)['sha256'])
    def bind(self,packet):
        self.entries[0]['vibrations']=self.ref(self.write('modes.json',packet))
        self.write('catalog.json',{'schema':'auto-g16-local-evidence-catalog/1','entries':self.entries})

    def test_exact_printed_vectors_frequency_order_and_immutable_sources(self):
        before=copy.deepcopy(self.detail);p=build_modes(self.detail,self.raw)
        self.assertEqual([m['frequency_cm1'] for m in p['modes']],[-123.4,200,300])
        self.assertEqual(p['modes'][0]['displacements'][1]['dy'],.45)
        self.assertEqual(p['modes'][2]['displacements'][2]['dz'],.47)
        span=p['modes'][0]['source_span'];self.assertIn(b'Atom AN',self.raw[span['start']:span['end']]);self.assertEqual(self.detail,before)

    def test_hash_missing_truncated_and_wrong_atom_vectors_fail_closed(self):
        with self.assertRaises(ValueError):build_modes(self.detail,self.raw+b'changed')
        for vectors in (b'',VECTORS.replace(b' 2 1',b' 4 1'),VECTORS.replace(b' 3 1',b' 3 8'),VECTORS.split(b' 3 1')[0],VECTORS.replace(b'0.45',b'NaN'),VECTORS.replace(b'0.45',b'9.99')):
            with self.subTest(vectors=vectors):
                self.make(vectors=vectors)
                with self.assertRaises((ValueError,IndexError)):build_modes(self.detail,self.raw)

    def test_cross_job_ambiguous_family_and_unknown_geometry_refused(self):
        for gap in (b'--Link1--\n',b'Normal termination\n',b'Harmonic frequencies (cm**-1)\n'):
            self.make(gap=gap)
            with self.assertRaises(ValueError):build_modes(self.detail,self.raw)
        self.make();self.detail['result']['data']['last_geometry']['orientation_kind']='input-orientation'
        with self.assertRaises(ValueError):build_modes(self.detail,self.raw)

    def test_sidecar_rebinding_and_numeric_mutations_rejected(self):
        packet=build_modes(self.detail,self.raw)
        for mutation in (lambda p:p.update(id='other'),lambda p:p['result_source'].update(result_id='other'),lambda p:p['modes'][0].update(frequency_cm1=42),lambda p:p['modes'][0]['displacements'][0].update(dx=float('nan')),lambda p:p['modes'][0]['displacements'][0].update(center=4),lambda p:p['reference_geometry']['atoms'][0].update(x=1),lambda p:p['modes'][0]['source_span'].update(end=999999),lambda p:p['modes'].pop()):
            candidate=copy.deepcopy(packet);mutation(candidate)
            with self.assertRaises(ValueError):validate_modes(candidate,self.detail)

    def test_get_reads_pinned_modes_without_parsing_process_or_store_mutation(self):
        p=build_modes(self.detail,self.raw);self.bind(p);before=self.database.read_bytes()
        with patch('autog_frontend.vibrations.build_modes',side_effect=AssertionError('GET parser')),patch('subprocess.Popen',side_effect=AssertionError('process')):
            result=self.query().get_vibrations('archive',self.record['archive_id'])
        self.assertEqual(result['vibrations']['data'],p);self.assertEqual(self.database.read_bytes(),before)
        (self.root/'modes.json').write_text('{}')
        with self.assertRaises(QueryError):self.query().get_vibrations('archive',self.record['archive_id'])

    def test_get_auth_readonly_and_missing_modes(self):
        self.assertEqual(self.query().get_vibrations('archive',self.record['archive_id'])['vibrations']['availability'],'unavailable')
        self.bind(build_modes(self.detail,self.raw))
        app=create_app(self.database,token=TOKEN,archive_index=self.index,archive_sha256=self.ref(self.index)['sha256'],evidence_catalog=self.catalog,evidence_sha256=self.ref(self.catalog)['sha256'])
        uri='/api/archives/'+self.record['archive_id']+'/vibrations'
        c=TestClient(app,base_url='http://localhost',headers={'Authorization':'Bearer '+TOKEN})
        self.assertEqual(c.get(uri).status_code,200);self.assertEqual(c.post(uri).status_code,405);self.assertEqual(c.get(uri+'?path=x').status_code,400)
        self.assertEqual(TestClient(app,base_url='http://localhost').get(uri).status_code,401)
        self.assertNotIn(str(self.root),c.get(uri).text)
        self.assertEqual(c.get('/api/attempts/gaussian-normal/vibrations').json()['vibrations']['availability'],'unavailable')
