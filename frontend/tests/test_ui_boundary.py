"""Integration boundary: public UI bytes never grant private Query access."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.query import QueryService
from autog_frontend.api import create_app
from autog_frontend.static_ui import load_ui
from tests.test_api import TOKEN, TestClient


class UIBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ui = self.root / "dist"
        (self.ui / "assets").mkdir(parents=True)
        (self.ui / "index.html").write_text('<div id="root"></div>')
        (self.ui / "assets/index-abc.js").write_text('document.title="readonly"')
        (self.ui / "assets/index-abc.css").write_text('body{color:green}')
        self.database = self.root / "core.sqlite3"
        with core.SQLiteRuntimeStore(self.database) as store:
            store.store_project(core.Project(project_id="p"))
            store.store_workflow_run(core.WorkflowRun(workflow_run_id="r", project_id="p", workflow_name="test"))
            store.store_task(core.Task(task_id="no-attempt", workflow_run_id="r", task_kind="pending"))
        self.app = create_app(self.database, token=TOKEN, ui_directory=self.ui)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")

    def test_public_ui_is_not_public_data(self):
        with patch.object(QueryService, "list_projects", side_effect=AssertionError("must not read")):
            for path in ("/", "/assets/index-abc.js", "/assets/index-abc.css"):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers['cache-control'], 'no-store')
                self.assertIn("script-src 'self'", r.headers['content-security-policy'])
                self.assertNotIn(TOKEN, r.text)
            for path in ("/api/projects", "/api/projects/p/tasks", "/assets/unknown.js", "/assets/../api/projects", "/index.html", "/.env", "/core.sqlite3"):
                self.assertEqual(self.client.get(path).status_code, 401)
        for method in ('POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'):
            self.assertEqual(self.client.request(method, '/').status_code, 405)
        self.assertEqual(self.client.get('/', headers={'Origin': 'http://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host': 'evil.example'}).status_code, 400)
        self.assertEqual(self.client.get('/?token=secret').status_code, 400)

    def test_tasks_include_zero_attempt_tasks_and_match_owner(self):
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN
        r = self.client.get('/api/projects/p/tasks')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), QueryService(self.database).list_tasks('p'))
        self.assertEqual(r.json()['data']['items'][0]['attempt_ids'], [])
        self.assertEqual(self.client.get('/api/projects/unknown/tasks').status_code, 404)
        self.assertEqual(self.client.post('/api/projects/p/tasks').status_code, 405)

    def test_bundle_is_frozen_in_memory_and_no_request_filesystem_lookup(self):
        original = self.client.get('/').content
        (self.ui / 'index.html').write_text('changed after startup')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('no request disk reads')):
            self.assertEqual(self.client.get('/').content, original)
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN
        self.assertEqual(self.client.get('/assets/missing.js').status_code, 404)
        self.assertEqual(self.client.get('/assets/%2e%2e%2fcore.sqlite3').status_code, 400)

    def test_untrusted_bundle_shapes_fail_startup(self):
        asset = self.ui / 'assets/index-abc.js'
        asset.unlink()
        asset.symlink_to(self.database)
        with self.assertRaises(ValueError):
            load_ui(self.ui)
        asset.unlink()
        (self.ui / 'assets/source.map').write_text('{}')
        with self.assertRaises(ValueError):
            load_ui(self.ui)
        with self.assertRaises(ValueError):
            load_ui(Path('relative'))
