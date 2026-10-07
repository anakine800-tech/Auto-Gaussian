from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.core import CalculationPlan, Observation, Project, Result, SQLiteRuntimeStore
from auto_g16.query import NativeSource, NativeQueryService, QueryService, QueryError
from auto_g16.result import GaussianJobParser, GaussianResultQuery, ResultProvenanceService, INPUT_BINDING_OBSERVATION
from tests.v3.result.test_service import initialized_store, binding, output_envelope
from tests.v3.result.test_gaussian_job import transcript


def populate(path, *, gaussian=False):
    with initialized_store(path) as store:
        if gaussian:
            service = ResultProvenanceService(store)
            bound = binding()
            service.record_input_binding(bound)
            raw = transcript()
            envelope = output_envelope(bound, data=raw)
            service.record_output_envelope(envelope)
            outcome = GaussianJobParser().parse(envelope, {"job.log": raw})
            service.record_parse_outcome(outcome)
        return store.list_projects()


class NativeQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / 'core.sqlite3'
        populate(self.db, gaussian=True)
        self.query = NativeQueryService((NativeSource(source_id='one', database=self.db),))

    def test_attributed_facts_units_and_axes(self):
        data = self.query.get_attempt('one', 'attempt-1')['data']
        self.assertEqual(data['facts']['energy']['value'], -75.0)
        self.assertEqual(data['facts']['energy']['unit'], 'hartree')
        self.assertEqual(data['facts']['geometry']['unit'], 'angstrom')
        self.assertEqual(data['facts']['frequencies']['unit'], 'cm^-1')
        self.assertEqual(data['program']['value'], 'gaussian')
        self.assertEqual(data['axes']['execution']['value'], 'PLANNED')
        self.assertEqual(data['axes']['validation']['availability'], 'unavailable')
        self.assertTrue(data['history'])
        self.assertEqual(data['facts']['thermochemistry'],dict(availability='unavailable',reason='thermochemistry-unavailable',source=None,value=None,unit='hartree'))

    def test_list_detail_identical(self):
        for row in self.query.list_attempts('one', 'project-1')['data']['items']:
            self.assertEqual(row, self.query.get_attempt('one', row['attempt_id'])['data'])

    def test_exact_bound_old_plan(self):
        with SQLiteRuntimeStore(self.db) as store:
            store.store_calculation_plan(CalculationPlan(calculation_plan_id='new', task_id='task-1', revision=2, intent={'program':'xtb'}))
        self.assertEqual(self.query.get_attempt('one','attempt-1')['data']['bound_plan']['value'], {'id':'plan-1','revision':1})

    def test_source_collision_retains_both(self):
        second = self.root / 'second.sqlite3'; populate(second)
        query = NativeQueryService((NativeSource(source_id='two',database=second), NativeSource(source_id='one',database=self.db)))
        rows = query.list_projects()['data']['items']
        self.assertEqual([r['source_id'] for r in rows], ['one','two'])
        self.assertTrue(all(r['identity_collision'] for r in rows))

    def test_unavailable_source_is_not_successful_empty(self):
        query = NativeQueryService((NativeSource(source_id='absent',database=self.root/'absent'), NativeSource(source_id='one',database=self.db)))
        value = query.list_projects()['data']
        self.assertEqual(len(value['items']),1)
        self.assertEqual(value['sources'][0]['reason'],'store-unavailable')
        self.assertFalse((self.root/'absent').exists())

    def test_registration_duplicates(self):
        source = NativeSource(source_id='one',database=self.db)
        with self.assertRaises(QueryError): NativeQueryService((source,source))
        with self.assertRaises(QueryError): NativeQueryService((source,NativeSource(source_id='two',database=self.db)))
        with self.assertRaises(QueryError): NativeSource(source_id='bad/path',database=self.db)
        with self.assertRaises(QueryError): NativeSource(source_id='one',database=Path('relative'))

    def test_native_private_payload_never_decoded_or_exposed(self):
        with SQLiteRuntimeStore(self.db) as store:
            store.append_result(Result(result_id='native',attempt_id='attempt-2',result_type='program-completion-evidence/1',data={'secret':'/private/host', 'content_base64':'not-base64'}))
        data = self.query.get_attempt('one','attempt-2')['data']
        self.assertEqual(data['generation']['value'],'V31')
        self.assertEqual(data['reason'],'native-snapshot-not-registered')
        self.assertEqual(data['program']['availability'],'unavailable')
        self.assertEqual(data['facts']['energy']['availability'],'unavailable')
        self.assertNotIn('/private/host',json.dumps(data))
        self.assertNotIn('content_base64',json.dumps(data))
        self.assertEqual(data['facts']['thermochemistry']['reason'],'thermochemistry-unavailable')

    def test_mixed_generation_conflict(self):
        with SQLiteRuntimeStore(self.db) as store:
            store.append_result(Result(result_id='native',attempt_id='attempt-1',result_type='program-completion-evidence/1',data={}))
        data=self.query.get_attempt('one','attempt-1')['data']
        self.assertEqual(data['reason'],'mixed-execution-generations')
        self.assertIsNone(data['facts']['energy']['value'])
        self.assertIsNone(data['generation']['value'])
        self.assertEqual(data['facts']['thermochemistry']['reason'],'thermochemistry-unavailable')

    def test_unknown_contract_not_leaked(self):
        with SQLiteRuntimeStore(self.db) as store:
            store.append_observation(Observation(observation_id='odd',attempt_id='attempt-2',observation_type='/sensitive/host/token',data={}))
        data=self.query.get_attempt('one','attempt-2')['data']
        self.assertNotIn('/sensitive',json.dumps(data))
        self.assertEqual(data['record_inventory'][0]['contract'],'unavailable')

    def test_no_effects_no_parser_no_constructor_on_get(self):
        before=(self.db.read_bytes(),self.db.stat(),sorted(self.root.iterdir()))
        with patch.object(SQLiteRuntimeStore,'__init__',side_effect=AssertionError('constructor')), patch.object(GaussianJobParser,'parse',side_effect=AssertionError('parse')):
            self.query.list_projects(); self.query.list_attempts('one','project-1'); self.query.get_attempt('one','attempt-1')
        after=(self.db.read_bytes(),self.db.stat(),sorted(self.root.iterdir()))
        self.assertEqual(before[0],after[0]);self.assertEqual(before[2],after[2])
        for key in ('st_ino','st_size','st_mtime_ns','st_ctime_ns'): self.assertEqual(getattr(before[1],key),getattr(after[1],key))

    def test_missing_attempt_and_source(self):
        for source,attempt in [('one','missing'),('absent','attempt-1')]:
            with self.assertRaisesRegex(QueryError,'not-found'): self.query.get_attempt(source,attempt)

    def test_old_query_and_result_shapes(self):
        self.assertEqual(QueryService(self.db).get_attempt('attempt-1')['schema'],'auto-g16-query/1')
        with SQLiteRuntimeStore.read_snapshot(self.db) as store:
            self.assertEqual(GaussianResultQuery(store).get_summary('attempt-1')['schema'],'gaussian-result-summary/1')

    def test_bad_binding_fails_closed(self):
        with SQLiteRuntimeStore(self.db) as store:
            store.append_observation(Observation(observation_id='bad',attempt_id='attempt-2',observation_type=INPUT_BINDING_OBSERVATION,data={}))
        self.assertEqual(self.query.get_attempt('one','attempt-2')['data']['reason'],'provenance-conflict')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(); self.db=self.root/'core.sqlite3';populate(self.db)

    def rejected(self,path):
        with self.assertRaisesRegex(QueryError,'store-unavailable'): QueryService(path).list_projects()

    def test_reject_sidecars(self):
        for suffix in ('-journal','-wal','-shm'):
            side=Path(str(self.db)+suffix);side.write_bytes(b'')
            self.rejected(self.db);side.unlink()

    def test_reject_symlink_and_hardlink(self):
        alias=self.root/'alias';alias.symlink_to(self.db);self.rejected(alias)
        alias.unlink();alias.hardlink_to(self.db);self.rejected(alias)

    def test_missing_does_not_create(self):
        target=self.root/'absent'; self.rejected(target);self.assertFalse(target.exists())

    def test_invalid_schema_not_initialized(self):
        path=self.root/'empty';path.write_bytes(b'')
        self.rejected(path);self.assertEqual(path.read_bytes(),b'')

    def test_counterfeit_schema_rejected(self):
        with sqlite3.connect(self.db) as db: db.execute('CREATE TABLE counterfeit (x TEXT)')
        self.rejected(self.db)

    def test_foreign_key_corruption_rejected(self):
        with sqlite3.connect(self.db) as db: db.execute("UPDATE tasks SET workflow_run_id='missing'")
        self.rejected(self.db)

    def test_readonly_write_attempt_fails(self):
        before=self.db.read_bytes()
        with SQLiteRuntimeStore.read_snapshot(self.db) as store:
            with self.assertRaises(sqlite3.OperationalError):store.store_project(Project(project_id='illegal'))
        self.assertEqual(before,self.db.read_bytes())

    def test_replacement_rejected_before_publication(self):
        with self.assertRaises(Exception):
            with SQLiteRuntimeStore.read_snapshot(self.db):
                self.db.rename(self.root/'old');populate(self.db)
