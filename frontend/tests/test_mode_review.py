import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from auto_g16 import core
from auto_g16.query import QueryError
from autog_frontend.api import create_app
from autog_frontend.archive import ArchiveQuery
from autog_frontend.details import DetailQuery
from autog_frontend.mode_review import ModeReviewService,ModeReviewStore,SCHEMA,DECISION,digest
from .result_fixture import add_result_fixtures
from .mode_review_fixture import ID,reference,add_mode_review_fixture
from .test_api import TestClient


class ModeReviewTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.db=self.root/'core.sqlite3';self.directory=self.root/'reviews';self.directory.mkdir()
        with core.SQLiteRuntimeStore(self.db) as store:
            add_result_fixtures(store);entry=add_mode_review_fixture(store,self.root)
        self.catalog=self.root/'catalog.json';self.catalog.write_text(json.dumps({'schema':'auto-g16-local-evidence-catalog/1','entries':[entry]}))
        self.options=dict(evidence_catalog=self.catalog,evidence_sha256=reference(self.catalog)['sha256'])
        self.details=DetailQuery(self.db,ArchiveQuery(None,None),self.catalog,self.options['evidence_sha256'])
        self.service=ModeReviewService(self.details,self.directory)
        self.app=create_app(self.db,local_no_token=True,mode_review_directory=self.directory,**self.options)
        self.client=TestClient(self.app,base_url='http://127.0.0.1')
        self.uri='/api/attempts/'+ID+'/mode-review'
        self.headers={'Origin':'http://127.0.0.1','X-AutoG-Review':'intended-mode/1'}
        self.originals={p:p.read_bytes() for p in self.root.iterdir() if p.is_file()}

    def value(self):
        return dict(schema=SCHEMA,request_id=str(uuid.uuid4()),target_sha256=self.service.get(ID)['target_sha256'],reviewer='Synthetic reviewer',note='Test only, not scientific acceptance',decision=DECISION)

    def post(self,value,headers=None):
        return self.client.post(self.uri,json=value,headers=self.headers if headers is None else headers)

    def test_get_is_side_effect_free_and_default_cannot_write(self):
        self.assertEqual(self.client.get(self.uri).status_code,200);self.assertEqual(list(self.directory.iterdir()),[])
        default=TestClient(create_app(self.db,local_no_token=True,**self.options),base_url='http://127.0.0.1')
        self.assertFalse(default.get(self.uri).json()['enabled']);self.assertEqual(default.post(self.uri,json=self.value(),headers=self.headers).status_code,405)
        self.assertEqual({p:p.read_bytes() for p in self.originals},self.originals)

    def test_exact_record_replay_and_no_source_or_authority_mutation(self):
        value=self.value();response=self.post(value);self.assertEqual(response.status_code,200,response.text);record=response.json()['record']
        self.assertEqual(record['command'],value);self.assertEqual(record['reviewer_identity'],'self-declared-local-user')
        self.assertEqual(record['target']['scope'],'human-intended-mode-only-not-ts-acceptance')
        self.assertEqual(record,self.post(value).json()['record']);self.assertEqual(len(list(self.directory.glob('*.json'))),1)
        self.assertEqual(ModeReviewService(self.details,self.directory).get(ID)['records'],[record])
        self.assertEqual(self.post({**value,'note':'different'}).status_code,409)
        self.assertEqual({p:p.read_bytes() for p in self.originals},self.originals)

    def test_same_request_concurrency_is_atomic_and_timestamp_stable(self):
        value=self.value()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.service.confirm(ID,value)['record'],range(16)))
        self.assertTrue(all(r==results[0] for r in results));self.assertEqual(len(list(self.directory.iterdir())),1)

    def test_source_change_refuses_stale_confirmation_and_does_not_apply_old_record(self):
        value=self.value();record=self.service.confirm(ID,value)['record'];target=copy.deepcopy(record['target']);target['displacements_sha256']='c'*64
        with patch.object(self.service,'target',return_value=(target,None)):
            with self.assertRaises(QueryError) as raised:self.service.confirm(ID,value)
            self.assertEqual(raised.exception.code,'review-target-changed')
            view=self.service.get(ID);self.assertEqual(view['records'],[]);self.assertEqual(view['other_target_count'],1)
        self.assertEqual(self.service.get(ID)['records'],[record])

    def test_ineligible_result_and_missing_modes_cannot_be_confirmed(self):
        for identity in ('gaussian-no-frequency','gaussian-error','gaussian-normal'):
            self.assertIsNone(self.service.get(identity)['target'])
            with self.assertRaises(QueryError):self.service.confirm(identity,self.value())
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_origin_action_type_query_and_method_boundaries(self):
        value=self.value()
        for headers in ({}, {'Origin':'http://127.0.0.1'}, {**self.headers,'Origin':'https://unrelated.example'}, {**self.headers,'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.post(value,headers).status_code,403)
        self.assertEqual(self.client.post(self.uri,content=json.dumps(value),headers={**self.headers,'Content-Type':'text/plain'}).status_code,400)
        self.assertEqual(self.client.post(self.uri+'?path=x',json=value,headers=self.headers).status_code,400)
        for method in ('PUT','PATCH','DELETE','OPTIONS'):
            self.assertEqual(self.client.request(method,self.uri,json=value,headers=self.headers).status_code,405)
        self.assertEqual(self.client.post('/api/projects',json=value,headers=self.headers).status_code,405)
        self.assertEqual(self.client.post('/api/archives/archive-x/mode-review',json=value,headers=self.headers).status_code,405)
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_invalid_body_oversize_reviewer_and_extra_authority_are_rejected(self):
        value=self.value()
        for bad in ({**value,'reviewer':''},{**value,'reviewer':'a\nB'},{**value,'request_id':'../../escape'},{**value,'decision':'validated-ts'},{**value,'acceptance':True}):
            self.assertEqual(self.post(bad).status_code,400)
        self.assertEqual(self.post({**value,'note':'a'*17000}).status_code,413)
        self.assertEqual(self.client.post(self.uri,content='{"schema":1,"schema":2}',headers={**self.headers,'Content-Type':'application/json'}).status_code,400)
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_corrupt_records_and_directory_replacement_fail_closed(self):
        value=self.value();self.post(value);file=next(self.directory.glob('*.json'));record=json.loads(file.read_text());record['command']['reviewer']='tampered';file.write_text(json.dumps(record))
        self.assertEqual(self.client.get(self.uri).status_code,409)
        self.directory.rename(self.root/'original-reviews');self.directory.mkdir()
        self.assertEqual(self.client.get(self.uri).status_code,503)
        link=self.root/'symlink';link.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(ValueError):ModeReviewStore(link)

    def test_write_requires_loopback_even_with_valid_bearer_and_bounds_actual_body(self):
        import asyncio
        import httpx
        from .test_api import TOKEN
        app=create_app(self.db,token=TOKEN,mode_review_directory=self.directory,**self.options)
        async def remote():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app,client=('192.0.2.1',123)),base_url='http://127.0.0.1') as client:
                return await client.post(self.uri,json=self.value(),headers={**self.headers,'Authorization':'Bearer '+TOKEN})
        self.assertEqual(asyncio.run(remote()).status_code,403)
        for body,length,expected in ((b'x'*16385,'1',413),(b'{}','1',400),(b'{','1',400)):
            response=self.client.post(self.uri,content=body,headers={**self.headers,'Content-Type':'application/json','Content-Length':length})
            self.assertEqual(response.status_code,expected)
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_distinct_requests_at_capacity_never_make_committed_records_unreadable(self):
        values=[self.value() for _ in range(8)]
        def submit(value):
            try:return self.service.confirm(ID,value)
            except QueryError as error:return error.code
        with patch('autog_frontend.mode_review.MAX_RECORDS',1), ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(submit,values))
            committed=[v for v in results if isinstance(v,dict)]
            self.assertEqual(len(committed),1)
            self.assertEqual(results.count('review-store-limit'),7)
            self.assertEqual(self.service.get(ID)['records'],[committed[0]['record']])
            self.assertEqual(self.service.confirm(ID,committed[0]['record']['command']),committed[0])
        self.assertEqual(len(list(self.directory.iterdir())),1)
