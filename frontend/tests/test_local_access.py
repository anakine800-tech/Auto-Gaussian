import asyncio
from pathlib import Path
import tempfile
import unittest
import httpx
from auto_g16 import core
from autog_frontend.api import create_app
from .test_api import TestClient, TOKEN

class LocalAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.database=self.root/'core.db'
        with core.SQLiteRuntimeStore(self.database) as store:store.store_project(core.Project(project_id='local-project'))
        self.ui=self.root/'ui';(self.ui/'assets').mkdir(parents=True);(self.ui/'index.html').write_text('<html><head></head><body>UI</body></html>')
        self.app=create_app(self.database,local_no_token=True,ui_directory=self.ui)
        self.client=TestClient(self.app,base_url='http://127.0.0.1')

    def test_local_auto_access_without_credentials_preserves_readonly_and_source(self):
        before=self.database.read_bytes()
        self.assertEqual(self.client.get('/api/projects').status_code,200)
        self.assertIn('local-project',self.client.get('/api/projects').text)
        self.assertIn('<meta name="autog-access" content="local-no-token">',self.client.get('/').text)
        self.assertNotIn('autog-access',(self.ui/'index.html').read_text())
        for method in ('POST','PUT','PATCH','DELETE','HEAD','OPTIONS'):self.assertEqual(self.client.request(method,'/api/projects').status_code,405)
        self.assertEqual(self.client.get('/api/projects?file=x').status_code,400)
        self.assertEqual(self.client.get('/api/projects',headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/projects',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        self.assertEqual(self.client.get('/api/projects',headers={'Host':'other.example'}).status_code,400)
        self.assertEqual(self.database.read_bytes(),before)

    def test_nonlocal_client_is_rejected_even_with_loopback_host_and_default_stays_authenticated(self):
        async def remote():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(self.app,client=('192.0.2.1',1234)),base_url='http://127.0.0.1') as c:return await c.get('/api/projects')
        self.assertEqual(asyncio.run(remote()).status_code,403)
        app=create_app(self.database,token=TOKEN,ui_directory=self.ui);c=TestClient(app,base_url='http://127.0.0.1');self.assertEqual(c.get('/api/projects').status_code,401);self.assertNotIn('autog-access',c.get('/').text)
        with self.assertRaises(ValueError):create_app(self.database,local_no_token=True,token=TOKEN)
        with self.assertRaises(ValueError):create_app(self.database)
