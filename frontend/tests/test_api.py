import hashlib
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

import httpx
from auto_g16 import core
from auto_g16.query import QueryError, QueryService
from autog_frontend.api import create_app

TOKEN = "test-only-token-" + "0" * 32


class TestClient:
    """Direct ASGI transport: no sockets, lifespan hooks or double URL decoding.

    Starlette 1.7's deprecated httpx TestClient path double-decodes literal
    percent IDs. ASGITransport preserves HTTPX's once-decoded ASGI path.
    """

    def __init__(self, app, *, base_url, headers=None):
        self.app, self.base_url = app, base_url
        self.headers = dict(headers or {})

    def request(self, method, url, **kwargs):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(self.app),
                                         base_url=self.base_url, headers=self.headers) as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(call())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self):
        pass  # Each call closes its own client.

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name).resolve() / "core.sqlite3"
        with core.SQLiteRuntimeStore(self.database) as store:
            store.store_project(core.Project(project_id="project"))
            store.store_project(core.Project(project_id="empty"))
            store.store_workflow_run(core.WorkflowRun(workflow_run_id="run", project_id="project", workflow_name="demo"))
            store.store_task(core.Task(task_id="task", workflow_run_id="run", task_kind="fixture"))
            store.create_attempt(core.Attempt(attempt_id="attempt", task_id="task", ordinal=1))
            store.record_submission_intent("attempt", "intent")
            store.record_submission_outcome("attempt", "intent", core.SubmissionOutcome.UNKNOWN)
            store.append_result(core.Result(result_id="unsupported", attempt_id="attempt",
                                            result_type="future-protocol/1", data={"private": "do-not-expose"}))
        self.app = create_app(self.database, token=TOKEN)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.client.headers["Authorization"] = "Bearer " + TOKEN
        self.addCleanup(self.client.close)

    def fingerprint(self):
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns,
                         p.stat().st_ctime_ns) for p in self.database.parent.iterdir() if p.is_file()}

    def test_four_routes_match_public_query_and_do_not_write(self):
        q = QueryService(self.database)
        expected = {"/api/projects": q.list_projects(), "/api/projects/project": q.get_project("project"),
                    "/api/projects/project/attempts": q.list_attempts(project_id="project"),
                    "/api/attempts/attempt": q.get_attempt("attempt")}
        before = self.fingerprint()
        with patch.object(core.SQLiteRuntimeStore, "_initialize_schema", side_effect=AssertionError("write")), \
             patch.object(core.SQLiteRuntimeStore, "append_observation", side_effect=AssertionError("write")), \
             patch("subprocess.Popen", side_effect=AssertionError("process")):
            for url, dto in expected.items():
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), dto)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertNotIn("access-control-allow-origin", response.headers)
                self.assertNotIn("do-not-expose", response.text)
                self.assertEqual(response.content, self.client.get(url).content)
        self.assertEqual(before, self.fingerprint())
        detail = expected["/api/attempts/attempt"]["data"]
        self.assertEqual(detail["execution_state"], "UNKNOWN")
        self.assertEqual(detail["input"]["availability"], "unavailable")

    def test_empty_unknown_and_invalid_id(self):
        self.assertEqual(self.client.get("/api/projects/empty/attempts").json()["data"]["items"], [])
        for url in ("/api/projects/unknown", "/api/projects/unknown/attempts", "/api/attempts/unknown"):
            self.assertEqual(self.client.get(url).status_code, 404)
        for value in (" bad ", "a/b", "a\\b", "a\x00b", "x" * 513):
            response = self.client.get("/api/attempts/" + quote(value, safe=""))
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/projects/").status_code, 404)

    def test_unicode_and_literal_percent_ids_are_not_normalized(self):
        with core.SQLiteRuntimeStore(self.database) as s:
            for value in ("中文'?#", "literal%2F"):
                s.store_project(core.Project(project_id=value))
        for value in ("中文'?#", "literal%2F"):
            response = self.client.get("/api/projects/" + quote(value, safe=""))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"]["project_id"], value)

    def test_auth_precedes_routing_and_database_access(self):
        with TestClient(self.app, base_url="http://127.0.0.1") as client, \
             patch.object(QueryService, "list_projects", side_effect=AssertionError("must not read")):
            for url in ("/api/projects", "/api/projects/%20bad%20", "/missing"):
                response = client.get(url)
                self.assertEqual(response.status_code, 401)
            self.assertEqual(client.post("/api/projects").status_code, 401)
            self.assertEqual(client.get("/api/projects", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(client.get("/api/projects", headers=[("Authorization", "Bearer " + TOKEN)] * 2).status_code, 401)

    def test_request_boundary(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            self.assertEqual(self.client.request(method, "/api/projects").status_code, 405)
        self.assertEqual(self.client.get("/api/projects", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.client.get("/api/projects", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/projects", headers={"Origin": "http://127.0.0.1"}).status_code, 200)
        for query in ("database=/tmp/secret", "token=" + TOKEN, "limit=10"):
            response = self.client.get("/api/projects?" + query)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(TOKEN, response.text)
        self.assertEqual(self.client.request("GET", "/api/projects", content=b"body").status_code, 400)
        self.assertEqual(self.client.get("/api/projects", headers={"x-large": "a" * 9000}).status_code, 413)
        self.assertEqual(self.client.get("/api/projects/" + "a" * 2100).status_code, 413)
        for route in ("/docs", "/openapi.json", "/redoc", "/api/logs", "/api/submit"):
            self.assertEqual(self.client.get(route).status_code, 404)

    def test_store_errors_are_bounded_and_no_creation(self):
        missing = self.database.parent / "missing.sqlite3"
        app = create_app(missing, token=TOKEN)
        self.assertFalse(missing.exists())
        with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer " + TOKEN}) as client:
            response = client.get("/api/projects")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(str(missing), response.text)
        self.assertFalse(missing.exists())
        sidecar = Path(str(self.database) + "-journal")
        sidecar.write_bytes(b"inert")
        before = self.fingerprint()
        self.assertEqual(self.client.get("/api/projects").status_code, 503)
        self.assertEqual(before, self.fingerprint())

    def test_invalid_evidence_is_409_and_snapshot_remains_unchanged(self):
        from auto_g16.observe import OBSERVATION_TYPE
        with core.SQLiteRuntimeStore(self.database) as store:
            store.append_observation(core.Observation(observation_id="malformed", attempt_id="attempt",
                                                      observation_type=OBSERVATION_TYPE, data={}))
        before = self.fingerprint()
        response = self.client.get("/api/attempts/attempt")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "invalid-evidence")
        self.assertEqual(before, self.fingerprint())

    def test_limits_and_unexpected_errors_do_not_leak(self):
        with TestClient(create_app(self.database, token=TOKEN, max_response_bytes=256),
                        base_url="http://127.0.0.1", headers={"Authorization": "Bearer " + TOKEN}) as client:
            response = client.get("/api/projects")
            self.assertEqual(response.status_code, 413)
            self.assertNotIn("project_id", response.text)
        for error in (RuntimeError("secret path /private/file"), QueryError("unrecognized-secret")):
            with patch.object(QueryService, "list_projects", side_effect=error):
                client = TestClient(create_app(self.database, token=TOKEN), base_url="http://127.0.0.1",
                                    headers={"Authorization": "Bearer " + TOKEN})
                with client:
                    response = client.get("/api/projects")
                    self.assertEqual(response.status_code, 500)
                    self.assertNotIn("secret", response.text)

    def test_concurrent_requests_own_their_sqlite_connections(self):
        before = self.fingerprint()
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.client.get("/api/attempts/attempt"), range(12)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual(len({r.content for r in responses}), 1)
        self.assertEqual(before, self.fingerprint())

    def test_capabilities_are_readonly_and_report_actual_disabled_services(self):
        response = self.client.get('/api/capabilities')
        self.assertEqual(response.status_code, 200)
        features = response.json()['features']
        self.assertTrue(features['local_drafts'])
        for field in ('execution', 'local_queue', 'monitor', 'library', 'mode_review', 'v31_dag'):
            self.assertFalse(features[field])
        self.assertEqual(self.client.post('/api/capabilities', json={}).status_code, 405)

    def test_configuration_validation_and_exact_routes(self):
        for token in ("", "short", "a" * 31, "a" * 257, "中" * 32):
            with self.assertRaises(ValueError):
                create_app(self.database, token=token)
        self.assertEqual({r.path for r in self.app.routes}, {
            "/api/projects", "/api/projects/{project_id}", "/api/projects/{project_id}/attempts",
            "/api/attempts/{attempt_id}", "/api/projects/{project_id}/tasks",
        "/api/attempts/{attempt_id}/result", "/api/archives", "/api/archives/{archive_id}",
        "/api/attempts/{attempt_id}/details", "/api/attempts/{attempt_id}/log",
        "/api/archives/{archive_id}/details", "/api/archives/{archive_id}/log",
        "/api/attempts/{attempt_id}/vibrations", "/api/archives/{archive_id}/vibrations",
        "/api/attempts/{attempt_id}/mode-review",
        "/api/{group}/{identity}/log-window/{start}/{count}", "/api/{group}/{identity}/log-span/{start}/{end}/{digest}",
        "/api/{group}/{identity}/log-find/{term}/{start}", "/api/archives/{archive_id}/history-links", "/api/library", "/api/project-library", "/api/project-library/{identity}", "/api/archives/{identity}/conditions", "/api/archives/{identity}/workflow", "/api/monitor", "/api/capabilities", "/api/task-center", "/api/{group}/{identity}/analysis", "/api/workflows", "/api/workflows/attempts/{identity}"})
        self.assertTrue(all(r.methods == {"GET"} for r in self.app.routes))


if __name__ == "__main__":
    unittest.main()
