"""Offline end-to-end snapshot -> owner DTO -> authenticated GET tests."""
from contextlib import contextmanager, ExitStack
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.query import QueryService
from auto_g16.result import GaussianJobParser, GaussianResultQuery
from autog_frontend.api import create_app
from autog_frontend.result_query import ResultSummaryQuery
from tests.result_fixture import add_result_fixtures
from tests.test_api import TestClient, TOKEN


class ResultIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name).resolve() / 'core.sqlite3'
        with core.SQLiteRuntimeStore(self.database) as store:
            add_result_fixtures(store)
        self.client = TestClient(create_app(self.database, token=TOKEN), base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer ' + TOKEN})

    def get(self, case):
        return self.client.get('/api/attempts/gaussian-' + case + '/result')

    def fingerprint(self):
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size,
                        p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                for p in self.database.parent.iterdir()}

    def test_every_state_matches_owner_and_cannot_parse_or_write(self):
        before = self.fingerprint()
        with ExitStack() as traps:
            for method in ('_initialize_schema', 'append_result', 'append_observation', 'advance_attempt'):
                traps.enter_context(patch.object(core.SQLiteRuntimeStore, method, side_effect=AssertionError('mutation')))
            traps.enter_context(patch.object(GaussianJobParser, 'parse', side_effect=AssertionError('parse')))
            traps.enter_context(patch('subprocess.Popen', side_effect=AssertionError('process')))
            traps.enter_context(patch('socket.socket', side_effect=AssertionError('network')))
            # Direct query while socket creation is trapped; ASGI event loops may
            # need an OS socketpair even though their HTTP transport is in-process.
            direct = ResultSummaryQuery(self.database).get_summary('gaussian-normal')
        self.assertEqual(direct['summary']['final_energy_hartree'], -75)
        for case, availability in [('normal', 'available'), ('no-frequency', 'available'), ('error', 'available'),
                                  ('missing', 'missing'), ('partial', 'partial'), ('unknown', 'unsupported'),
                                  ('v31', 'unsupported'), ('legacy', 'unsupported')]:
            with self.subTest(case=case), core.SQLiteRuntimeStore.read_snapshot(self.database) as reader:
                expected = GaussianResultQuery(reader).get_summary('gaussian-' + case)
            with patch.object(GaussianJobParser, 'parse', side_effect=AssertionError('parse')):
                response = self.get(case)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), expected)
            self.assertEqual(expected['availability'], availability)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('must-not-expose', response.text)
        self.assertEqual(before, self.fingerprint())

    def test_missing_frequency_and_error_termination_are_not_success(self):
        frequency = self.get('no-frequency').json()['summary']['frequency']
        self.assertEqual(frequency, {'availability': 'missing', 'count': None, 'imaginary_count': None})
        self.assertEqual(self.get('error').json()['summary']['termination']['status'], 'error-termination')
        self.assertEqual(QueryService(self.database).get_attempt('gaussian-error')['data']['execution_state'], 'PLANNED')

    def test_history_selection_and_existing_attempt_contract_unchanged(self):
        dto = self.get('normal').json()
        self.assertEqual([h['selected'] for h in dto['history']], [False, True])
        self.assertEqual(dto['source']['capture_source_id'], 'normal-capture-2')
        self.assertEqual(self.client.get('/api/attempts/gaussian-normal').json(),
                         QueryService(self.database).get_attempt('gaussian-normal'))

    def test_conflict_stays_a_domain_dto_and_suppresses_facts(self):
        with core.SQLiteRuntimeStore(self.database) as store:
            store.append_result(core.Result(result_id='mixed', attempt_id='gaussian-normal',
                result_type='program-completion-evidence/1', data={'private': 'secret'}))
        before = self.fingerprint()
        response = self.get('normal')
        self.assertEqual(response.status_code, 200)
        dto = response.json()
        self.assertEqual(dto['availability'], 'conflict')
        self.assertEqual(dto['reasons'], ['mixed-execution-generations'])
        self.assertIsNone(dto['summary'])
        self.assertIsNone(dto['source'])
        self.assertEqual(dto['history'], [])
        self.assertEqual(before, self.fingerprint())

    def test_unsafe_identity_remains_explicit_result_conflict(self):
        with core.SQLiteRuntimeStore(self.database) as store:
            store.store_task(core.Task(task_id='unicode-task', workflow_run_id='gaussian-run', task_kind='fixture'))
            store.create_attempt(core.Attempt(attempt_id='中文', task_id='unicode-task', ordinal=1))
        response = self.client.get('/api/attempts/%E4%B8%AD%E6%96%87/result')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reasons'], ['unsafe-identifier'])
        self.assertIsNone(response.json()['attempt_id'])
        self.assertEqual(self.client.get('/api/attempts/%E4%B8%AD%E6%96%87').status_code, 200)

    def test_snapshot_exit_failure_never_publishes_computed_dto(self):
        original = core.SQLiteRuntimeStore.read_snapshot
        @contextmanager
        def drift(database):
            with original(database) as store:
                yield store
                raise core.RuntimeStoreError('private source changed')
        with patch.object(core.SQLiteRuntimeStore, 'read_snapshot', drift):
            response = self.get('normal')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('summary', response.json())
        self.assertNotIn('private', response.text)

    def test_missing_source_and_attempt_are_distinct_and_no_creation(self):
        self.assertEqual(self.get('absent').status_code, 404)
        self.assertEqual(self.get('missing').json()['availability'], 'missing')
        database = self.database.parent / 'absent.sqlite3'
        c = TestClient(create_app(database, token=TOKEN), base_url='http://127.0.0.1', headers=self.client.headers)
        self.assertEqual(c.get('/api/attempts/gaussian-normal/result').status_code, 503)
        self.assertFalse(database.exists())
        Path(str(self.database) + '-journal').write_bytes(b'inert')
        before = self.fingerprint()
        self.assertEqual(self.get('normal').status_code, 503)
        self.assertEqual(before, self.fingerprint())

    def test_auth_request_limits_and_errors_are_inherited(self):
        url = '/api/attempts/gaussian-normal/result'
        with patch.object(ResultSummaryQuery, 'get_summary', side_effect=AssertionError('must not read')):
            unauth = TestClient(create_app(self.database, token=TOKEN), base_url='http://127.0.0.1')
            self.assertEqual(unauth.get(url).status_code, 401)
            for method in ('POST', 'DELETE', 'PUT', 'PATCH', 'HEAD', 'OPTIONS'):
                self.assertEqual(self.client.request(method, url).status_code, 405)
            self.assertEqual(self.client.get(url + '?path=private').status_code, 400)
            self.assertEqual(self.client.get(url, headers={'Origin': 'https://evil.example'}).status_code, 403)
        with patch.object(ResultSummaryQuery, 'get_summary', side_effect=RuntimeError('private path')):
            self.assertEqual(self.get('normal').json()['error']['code'], 'internal-error')
            self.assertNotIn('private', self.get('normal').text)
        small = TestClient(create_app(self.database, token=TOKEN, max_response_bytes=256),
                           base_url='http://127.0.0.1', headers=self.client.headers)
        self.assertEqual(small.get(url).status_code, 413)

    def test_parallel_reads_have_independent_connections(self):
        before = self.fingerprint()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.get('normal'), range(8)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(len({r.content for r in results}), 1)
        self.assertEqual(before, self.fingerprint())
