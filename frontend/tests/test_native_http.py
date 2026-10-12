import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from auto_g16.core import SQLiteRuntimeStore, Project, WorkflowRun, Task, Attempt
from auto_g16.query import NativeSource, NativeQueryService, QueryError
from unittest.mock import patch
from autog_frontend.api import create_app

class NativeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name).resolve()/'core.sqlite3'
        with SQLiteRuntimeStore(self.path) as s:
            s.store_project(Project(project_id='project'))
            s.store_workflow_run(WorkflowRun(workflow_run_id='run',project_id='project',workflow_name='offline'))
            s.store_task(Task(task_id='task',workflow_run_id='run',task_kind='opt'))
            s.create_attempt(Attempt(attempt_id='attempt',task_id='task',ordinal=1))
        self.client=TestClient(create_app(self.path,token='a'*32,native_sources=(NativeSource(source_id='one',database=self.path),)),base_url='http://127.0.0.1:18871',headers={'authorization':'Bearer '+'a'*32})
        self.addCleanup(self.client.close)

    def test_versioned_list_detail_and_legacy(self):
        p=self.client.get('/api/v1/native/projects');self.assertEqual(p.status_code,200)
        rows=self.client.get('/api/v1/native/sources/one/projects/project/attempts').json()['data']['items']
        detail=self.client.get('/api/v1/native/sources/one/attempts/attempt').json()['data']
        self.assertEqual(rows,[detail]);self.assertEqual(self.client.get('/api/projects').json()['schema'],'auto-g16-query/1')
        self.assertNotIn(str(self.path),p.text)
        self.assertEqual(detail['facts']['thermochemistry'],dict(availability='unavailable',reason='thermochemistry-unavailable',source=None,value=None,unit='hartree'))
        self.assertNotIn(str(self.path),str(rows))

    def test_denied_methods_paths_query_origin_and_missing(self):
        cases=[('post','/api/v1/native/projects',405,{}),('get','/api/v1/native/projects?path=private',400,{}),('get','/api/v1/native/sources/no/attempts/attempt',404,{}),('get','/api/v1/native/projects',403,{'origin':'https://evil.invalid'})]
        before=self.path.read_bytes()
        for method,path,status,headers in cases:
            self.assertEqual(getattr(self.client,method)(path,headers=headers).status_code,status)
        self.assertEqual(before,self.path.read_bytes())

    def test_unreadable_source_status_and_error_sanitized(self):
        self.path.rename(self.path.with_suffix('.retained'))
        value=self.client.get('/api/v1/native/projects').json()
        self.assertEqual(value['data']['sources'][0]['reason'],'store-unavailable')
        response=self.client.get('/api/v1/native/sources/one/attempts/attempt')
        self.assertEqual(response.status_code,503);self.assertNotIn(str(self.path),response.text)

    def test_thermodynamics_unregistered_is_source_scoped_and_readonly(self):
        before = self.path.read_bytes()
        url = '/api/v1/native/sources/one/attempts/attempt/thermodynamics'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'schema': 'auto-g16-native-thermodynamics-query/1', 'kind': 'thermodynamics',
            'data': {'availability': 'unavailable', 'reason': 'not-registered', 'source_id': 'one',
                     'attempt_id': 'attempt', 'selected_member_id': None, 'result': None}})
        for path in (url.replace('/one/', '/unknown/'), url.replace('/attempt/', '/unknown/')):
            self.assertEqual(self.client.get(path).status_code, 404)
        for method in ('post', 'put', 'delete', 'patch'):
            self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertEqual(self.client.get(url+'?path=private').status_code, 400)
        self.assertEqual(self.client.get(url, headers={'authorization': 'Bearer wrong'}).status_code, 401)
        self.assertEqual(self.client.get(url, headers={'origin': 'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.get(url.replace('/attempt/', '/bad%5Cid/')).status_code, 400)
        self.assertEqual(before, self.path.read_bytes())

    def test_thermodynamics_error_mapping_caps_and_no_list_reads(self):
        url = '/api/v1/native/sources/one/attempts/attempt/thermodynamics'
        with patch.object(NativeQueryService, 'get_thermodynamics') as query:
            for path in ('/api/v1/native/sources', '/api/v1/native/projects',
                         '/api/v1/native/sources/one/projects/project/attempts',
                         '/api/v1/native/sources/one/attempts/attempt'):
                self.assertEqual(self.client.get(path).status_code, 200)
            query.assert_not_called()
            for code, status in (('invalid-id', 400), ('not-found', 404), ('store-unavailable', 503),
                                 ('invalid-evidence', 409), ('unclassified', 500)):
                query.side_effect = QueryError(code)
                response = self.client.get(url)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), {'schema': 'auto-g16-http-error/1',
                    'error': {'code': 'internal-error' if status == 500 else code}})
            query.side_effect = RuntimeError('/private/local/source')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 500)
            self.assertNotIn('/private', response.text)
            query.side_effect = None
            query.return_value = {'synthetic': 'x' * (4 * 1024 * 1024)}
            self.assertEqual(self.client.get(url).status_code, 413)
            query.reset_mock()
            query.return_value = {'synthetic': 'passthrough'}
            response = self.client.get(url)
            query.assert_called_once_with('one', 'attempt')
            self.assertEqual(response.json(), query.return_value)
            self.assertEqual(response.headers['cache-control'], 'no-store')


class NativeThermodynamicsIntegrationTests(unittest.TestCase):
    """Real registry/query integration over the pinned backend's synthetic fixture.

    Tests may explicitly select AUTOG_TEST_BACKEND_CHECKOUT (the joint repository
    root after migration). Otherwise retain .ci/backend and source-run fallback.
    No fixture is read from an installed application or a user database.
    """

    @classmethod
    def setUpClass(cls):
        import auto_g16
        import tests
        from tests.backend_fixture_source import backend_fixture_checkout
        backend_package = Path(auto_g16.__file__).resolve().parent
        checkout = backend_fixture_checkout(Path(__file__).resolve().parents[1], backend_package)
        fixture_root = str(checkout / 'tests')
        if fixture_root not in tests.__path__:
            tests.__path__.append(fixture_root)
            cls.addClassCleanup(tests.__path__.remove, fixture_root)
        # Fixtures also import backend script helpers. Extend only that namespace;
        # never add the backend root to sys.path and shadow the installed owner.
        import scripts
        backend_scripts = str(checkout / 'scripts')
        original_scripts_path = scripts.__path__
        if backend_scripts not in original_scripts_path:
            scripts.__path__ = [*original_scripts_path, backend_scripts]
            cls.addClassCleanup(setattr, scripts, '__path__', original_scripts_path)
        from tests.v31.conformer.test_thermochemistry_readonly import PairReadbackTests, no_computation
        from tests.v31.conformer.test_successor_freq import inert_thermo_owners
        cls.no_computation = staticmethod(no_computation)
        cls.inert_owners = staticmethod(inert_thermo_owners)
        cls.addClassCleanup(PairReadbackTests.doClassCleanups)
        PairReadbackTests.setUpClass()  # Builds a disposable pair with fake kernels only.
        cls.fixture = PairReadbackTests()
        cls.addClassCleanup(cls.fixture.doCleanups)
        cls.fixture.setUp()
        cls.binding = cls.fixture.save()
        cls.registry, cls.registry_digest = cls.fixture.registry(cls.binding)

    def test_real_registration_http_projection_and_legacy_isolation(self):
        import hashlib
        import json
        from auto_g16.conformer.thermochemistry_readonly import NativeThermodynamicReadout
        from auto_g16.conformer.frequency_readonly import FreqReadout
        from autog_frontend.native_sources import load_native_sources
        fixture = self.fixture
        frequency_registry = fixture.root / 'frequency-registration.json'
        rows = []
        for index, source in enumerate(fixture.readout.frequency_sources):
            snapshot = fixture.root / f'freq{index}.json'
            rows.append({'source_id': f'synthetic-{index}', 'database': source.revision.path,
                'snapshots': [{'path': str(snapshot), 'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()}],
                'opt_readout': None,
                'freq_readout': {'path': str(frequency_registry), 'sha256': hashlib.sha256(frequency_registry.read_bytes()).hexdigest()},
                'thermodynamic_readout': {'path': str(self.registry), 'sha256': self.registry_digest}})
        registry = fixture.root / 'frontend-sources.json'
        raw = json.dumps({'schema': 'autog-native-source-registration/4', 'sources': rows}).encode()
        registry.write_bytes(raw)
        with self.no_computation(), patch.object(NativeThermodynamicReadout, 'read', side_effect=AssertionError('startup result read')):
            sources = load_native_sources(registry, hashlib.sha256(raw).hexdigest())
            app = create_app(Path(rows[0]['database']), token='a'*32, native_sources=sources)
            for changed in ('database', 'snapshot'):
                wrong = json.loads(raw)
                if changed == 'database': wrong['sources'][0]['database'] = rows[1]['database']
                else: wrong['sources'][0]['snapshots'] = rows[1]['snapshots']
                encoded = json.dumps(wrong).encode()
                registry.write_bytes(encoded)
                with self.subTest(registration=changed), self.assertRaises((ValueError, QueryError)):
                    load_native_sources(registry, hashlib.sha256(encoded).hexdigest())
        attempts = [source.snapshots[0].attempt_id for source in sources]
        paths = [f'/api/v1/native/sources/synthetic-{index}/attempts/{attempt}' for index, attempt in enumerate(attempts)]
        with TestClient(app, base_url='http://127.0.0.1:18872', headers={'authorization': 'Bearer '+'a'*32}) as client, self.inert_owners(), self.no_computation():
            old = []
            with patch.object(NativeThermodynamicReadout, 'read', side_effect=AssertionError('legacy thermo read')):
                self.assertEqual(client.get('/api/v1/native/sources').status_code, 200)
                projects = client.get('/api/v1/native/projects')
                self.assertEqual(projects.status_code, 200)
                for project in projects.json()['data']['items']:
                    self.assertEqual(client.get(f"/api/v1/native/sources/{project['source_id']}/projects/{project['project_id']}/attempts").status_code, 200)
                for path in paths:
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200, response.text)
                    old.append(response.json())
            original = NativeThermodynamicReadout.read
            calls = []
            def read_once(reader):
                calls.append(reader.artifact.sha256)
                return original(reader)
            with patch.object(NativeThermodynamicReadout, 'read', read_once), patch.object(FreqReadout, 'read', side_effect=AssertionError('nested frequency read')):
                for index, path in enumerate(paths):
                    response = client.get(path+'/thermodynamics')
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(len(calls), index+1)
                    dto = response.json()
                    self.assertEqual(set(dto), {'schema', 'kind', 'data'})
                    self.assertEqual(dto['schema'], 'auto-g16-native-thermodynamics-query/1')
                    self.assertEqual(dto['kind'], 'thermodynamics')
                    data = dto['data']
                    self.assertEqual(data['source_id'], f'synthetic-{index}')
                    self.assertEqual(data['attempt_id'], attempts[index])
                    self.assertEqual(data['selected_member_id'], fixture.readout.frequency_sources[index].member_id)
                    result = data['result']
                    self.assertEqual(result['artifact_sha256'], self.binding.sha256)
                    self.assertEqual(result['scientific_acceptance'], 'unavailable')
                    saved = fixture.pair[1]
                    self.assertEqual(result['ensemble_treated_free_energy_hartree'], saved.ensemble_treated_free_energy_hartree)
                    self.assertEqual([m['member_id'] for m in result['members']], list(saved.source_member_ids))
                    for projected, observation in zip(result['members'], saved.member_observations):
                        for key in ('raw_rrho', 'treated_qrrho', 'normalized_population', 'degeneracy'):
                            self.assertEqual(projected[key], observation[key])
                    self.assertNotIn(str(fixture.root), response.text)
                    wrong = f'/api/v1/native/sources/synthetic-{index}/attempts/{attempts[1-index]}/thermodynamics'
                    self.assertEqual(client.get(wrong).status_code, 404)
                    self.assertEqual(len(calls), index+1)
                self.assertEqual(client.get(f'/api/v1/native/sources/unknown/attempts/{attempts[0]}/thermodynamics').status_code, 404)
                self.assertEqual(len(calls), 2)
            for path, previous in zip(paths, old):
                self.assertEqual(client.get(path).json(), previous)
