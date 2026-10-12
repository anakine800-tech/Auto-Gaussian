import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.execution import RemoteEffectReceipt,EffectKind,EffectState
from autog_frontend.api import create_app
from autog_frontend.archive_import import plain
from autog_frontend.workflow_query import WorkflowQuery,attach_live,receipt_binding,scheduler_jobs
from tests.test_api import TestClient,TOKEN


IDENTITY=dict(schema='pbs-job-incarnation/1',host='192.0.2.1',port=22,user='testuser',job_id='123.master',
              ctime='Fri Sep 25 10:00:00 2026',qtime='Fri Sep 25 10:00:00 2026',workspace='/work/exact-attempt')

def monitor(state='fresh',changes=None):
    fields=dict(Job_Name='same-name-is-not-identity',Job_Owner='testuser@submit',job_state='R',ctime=IDENTITY['ctime'],qtime=IDENTITY['qtime'],init_work_dir=IDENTITY['workspace'])
    fields.update(changes or {})
    text='Job Id: 123.master\n'+''.join(f'    {k} = {v}\n' for k,v in fields.items())
    return dict(enabled=True,state=state,server_identity={'host':'192.0.2.1','port':22,'user':'testuser'},sample=dict(user='testuser',hostname='master',sampled_at='2026-09-25T02:00:30Z',raw_sha256='a'*64,sources={'queue_details':{'text':text,'exit_code':0}}))

class Details:
    def execution_source(self,identity):return None
    def get_details(self,*args):return {'result':{'availability':'unavailable'}}
class Monitor:
    def __init__(self,dto):self.dto=dto
    def snapshot(self):return copy.deepcopy(self.dto)

def receipt(attempt='a',birth=True,sequence=1,intent='intent',job='123.master'):
    return RemoteEffectReceipt(attempt_id=attempt,execution_snapshot_id='snapshot-'+attempt,submission_intent_id=intent,
        effect_sequence=sequence,effect_kind=EffectKind.SUBMISSION,effect_state=EffectState.CONFIRMED_EFFECT,
        remote_workspace=IDENTITY['workspace'],job_id=job,details={'scheduler_identity':IDENTITY} if birth else {})

def observation(r):return core.Observation(observation_id=r.remote_effect_receipt_id,attempt_id=r.attempt_id,observation_type='v3.remote-effect-receipt',data=r.semantic_payload())

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name).resolve()/'core.sqlite3'
        with core.SQLiteRuntimeStore(self.db) as s:
            s.store_project(core.Project(project_id='p'));s.store_workflow_run(core.WorkflowRun(workflow_run_id='w',project_id='p',workflow_name='test'))
            s.store_task(core.Task(task_id='t',workflow_run_id='w',task_kind='synthetic'))
            s.store_task(core.Task(task_id='empty',workflow_run_id='w',task_kind='synthetic'))
            s.create_attempt(core.Attempt(attempt_id='a',task_id='t',ordinal=1))
            s.append_observation(observation(receipt()))
        self.q=WorkflowQuery(self.db,Details(),Monitor(monitor()))

    def test_confirmed_submission_without_result_can_bind_and_timeline_has_no_fake_time(self):
        d=self.q.overview();a=next(t for t in d['tasks'] if t['task_id']=='t')['attempts'][0]
        self.assertEqual(a['result']['availability'],'missing')
        self.assertEqual(a['binding']['status'],'historical-confirmed')
        self.assertEqual(a['live']['status'],'verified')
        self.assertEqual(a['core_state'],'PLANNED') # Telemetry never advances Core.
        self.assertIsNone(d['tasks'][0]['current_attempt_id'])
        self.assertEqual(d['layout'],dict(schema='autog-workflow-layout/1',availability='unavailable',
            reason='v31-workflow-source-not-connected',nodes=[],edges=[]))
        timeline=self.q.attempt('a')['attempt']['timeline']
        self.assertIsNone(timeline[0]['time']);self.assertEqual(timeline[-1]['kind'],'live')
        self.assertEqual(d['server_jobs'][0]['association'],'verified')

    def test_job_number_and_name_are_not_a_binding(self):
        _,b=receipt_binding([observation(receipt(birth=False))],'a')
        m=monitor();jobs,_=scheduler_jobs(m)
        self.assertEqual(attach_live(b,jobs,m)['reason'],'submission-birth-identity-not-recorded')
        b['status']='unavailable'
        self.assertEqual(attach_live(b,jobs,m)['status'],'unavailable')

    def test_reused_number_wrong_server_user_workspace_and_stale_withhold_live(self):
        _,b=receipt_binding([observation(receipt())],'a')
        for change in ({'ctime':'Sat Sep 26 10:00:00 2026'},{'qtime':'different'},{'init_work_dir':'/work/similar'},{'Job_Owner':'other@submit'}):
            m=monitor(changes=change);jobs,_=scheduler_jobs(m)
            self.assertNotEqual(attach_live(b,jobs,m)['status'],'verified')
        for change in ({'host':'192.0.2.2'},{'user':'other'},{'port':2222}):
            m=monitor();m['server_identity'].update(change);jobs,_=scheduler_jobs(m)
            self.assertEqual(attach_live(b,jobs,m)['reason'],'different-server-or-account')
        m=monitor('stale');jobs,_=scheduler_jobs(m)
        self.assertEqual(attach_live(b,jobs,m)['status'],'stale')
        self.assertEqual(attach_live(b,[],monitor())['reason'],'not-observed-does-not-imply-completion')

    def test_conflicting_receipts_fail_closed_and_duplicates_never_pick_a_winner(self):
        with self.assertRaises(ValueError):receipt_binding([observation(receipt()),observation(receipt(sequence=2,intent='other'))],'a')
        with core.SQLiteRuntimeStore(self.db) as s:
            s.store_task(core.Task(task_id='other',workflow_run_id='w',task_kind='synthetic'))
            s.create_attempt(core.Attempt(attempt_id='b',task_id='other',ordinal=1));s.append_observation(observation(receipt('b')))
        d=self.q.overview();rows=[a for t in d['tasks'] for a in t['attempts']]
        self.assertTrue(all(a['live']['reason']=='multiple-attempts-claim-job' for a in rows))
        self.assertEqual(d['server_jobs'][0]['association'],'unlinked')
        self.assertEqual(self.q.attempt('a')['attempt']['live']['status'],'conflict')

    def test_scheduler_failure_malformed_or_missing_owner_is_not_empty_success(self):
        m=monitor();m['sample']['sources']['queue_details']['exit_code']=1
        self.assertEqual(scheduler_jobs(m)[1],'unavailable')
        m=monitor();m['sample']['sources']['queue_details']['text']+='    arbitrary = injected\n'
        self.assertEqual(scheduler_jobs(m)[1],'invalid')
        m=monitor(changes={'Job_Owner':'other@host'})
        self.assertEqual(scheduler_jobs(m)[0],[])

    def test_pinned_execution_packet_mismatch_does_not_override_receipt_or_grant_live(self):
        with patch.object(self.q.details,'execution_source',side_effect=ValueError('tampered packet')):
            a=self.q.attempt('a')['attempt']
        self.assertEqual(a['binding']['status'],'conflict');self.assertNotEqual(a['live']['status'],'verified')

    def test_api_is_get_only_without_ssh_or_core_writes(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        app=create_app(self.db,token=TOKEN,monitor=Monitor(monitor()))
        client=TestClient(app,base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+TOKEN})
        with patch('subprocess.Popen',side_effect=AssertionError('GET cannot SSH')),patch.object(core.SQLiteRuntimeStore,'_initialize_schema',side_effect=AssertionError('GET cannot initialize')):
            self.assertEqual(client.get('/api/workflows').status_code,200)
            self.assertEqual(client.get('/api/workflows/attempts/a').status_code,200)
            self.assertEqual(client.get('/api/workflows/attempts/absent').status_code,404)
            self.assertEqual(client.post('/api/workflows').status_code,405)
            self.assertEqual(client.get('/api/workflows?host=evil').status_code,400)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
