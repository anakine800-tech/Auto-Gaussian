import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from auto_g16.query import QueryError
from autog_frontend.calculation_analysis import extract, query_analysis
from autog_frontend.task_queue import TaskQueue, digest
from autog_frontend.api import create_app
from tests.test_api import TestClient, TOKEN
from tests.test_vibrations import GEOMETRY

TABLE = b''' Item Value Threshold Converged?
 Maximum Force 0.0005 0.000450 NO
 RMS Force 0.0001 0.000300 YES
 Maximum Displacement 0.002 0.001800 NO
 RMS Displacement 0.0001 0.001200 YES
'''
CYCLE = GEOMETRY + b' SCF Done: E(RHF) = -75.00D+00 A.U. after 10 cycles\n' + TABLE
LOG = b' Entering Gaussian System, Link 0=g16\n Step number 1 out of a maximum of 20\n' + CYCLE + b' Step number 2 out of a maximum of 20\n' + CYCLE.replace(b'-75.00', b'-75.01') + b' Optimization stopped.\n Error termination request processed by link 9999.\n'


class AnalysisTests(unittest.TestCase):
    def test_steps_geometry_metrics_and_exact_bytes(self):
        packet = extract(LOG, 'synthetic.log')
        points = packet['segments'][0]['points']
        self.assertEqual([p['energy']['energy_hartree'] for p in points], [-75, -75.01])
        self.assertEqual([p['printed_step'] for p in points], [1, 2])
        self.assertEqual(len(points[0]['geometry']['atoms']), 3)
        self.assertEqual([m['converged'] for m in points[0]['metrics']], [False, True, False, True])
        for p in points:
            span = p['energy']['source_span']
            self.assertIn(b'SCF Done:', LOG[span['start']:span['end']])
        self.assertEqual([e['code'] for e in packet['errors']], ['optimization-limit','termination'])

    def test_link1_restart_and_unpaired_scf_never_join(self):
        raw = CYCLE + b'--Link1--\n SCF Done: E(RHF) = -10 A.U.\n' + TABLE
        p = extract(raw, 's.log')
        self.assertEqual([len(s['points']) for s in p['segments']], [1, 0])
        raw = b'Step number 1 out of 20\n' + CYCLE + b'Step number 1 out of 20\n' + CYCLE
        self.assertEqual([len(s['points']) for s in extract(raw,'s.log')['segments']], [1,1])

    def test_truncated_geometry_and_missing_cycles_do_not_reuse(self):
        for tail in (b' SCF Done: E(RHF) = -80 A.U.\n'+TABLE, GEOMETRY[:100]+b' SCF Done: E(RHF) = -80 A.U.\n'+TABLE):
            self.assertEqual(len(extract(CYCLE+tail,'s.log')['segments'][0]['points']),1)

    def test_missing_cycle_and_changed_energy_method_break_curves(self):
        p=extract(CYCLE+TABLE+CYCLE,'s.log')
        self.assertEqual([len(s['points']) for s in p['segments']],[1,1])
        p=extract(CYCLE+CYCLE.replace(b'E(RHF)',b'E(RB3LYP)'),'s.log')
        self.assertEqual([len(s['points']) for s in p['segments']],[1,1])
        p=extract(GEOMETRY+b' SCF Done: E(RHF) = -75 A.U.\n SCF Done: E(RHF) = NaN A.U.\n'+TABLE,'s.log')
        self.assertEqual(sum(len(s['points']) for s in p['segments']),0)

    def test_crlf_unicode_offsets_and_nonfinite_rejected(self):
        raw = b'\xe4\xb8\xad\xe6\x96\x87\r\n' + LOG.replace(b'\n',b'\r\n')
        p = extract(raw,'s.log');s=p['errors'][-1]['source_span']
        self.assertTrue(raw[s['start']:s['end']].startswith(b' Error termination'))
        with self.assertRaises(ValueError):extract(CYCLE.replace(b'-75.00D+00',b'1E999'),'s.log')

    def test_query_hash_binding_and_no_parser_or_process(self):
        from hashlib import sha256
        class Archives:
            def get_archive(self, identity):
                return {'data':{'artifacts':[dict(role='log',logical_name='s.log',sha256=sha256(LOG).hexdigest(),size_bytes=len(LOG))]}}
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'packet.json';f.write_text(json.dumps(extract(LOG,'s.log')))
            ref=dict(path=str(f.resolve()),sha256=sha256(f.read_bytes()).hexdigest(),size_bytes=f.stat().st_size)
            class Query:
                archives=Archives()
                def _entry(self,*args):return {'analysis':ref}
            with patch('subprocess.Popen',side_effect=AssertionError('process')),patch('autog_frontend.calculation_analysis.extract',side_effect=AssertionError('parser')):
                self.assertEqual(query_analysis(Query(),'archive','a')['availability'],'available')
            f.write_text('{}')
            with self.assertRaises(QueryError):query_analysis(Query(),'archive','a')


class Gateway:
    def __init__(self):self.calls=0;self.state='SUBMITTED';self.changed=False;self.fail=False
    def review(self, identity):
        return dict(id=identity,title='Synthetic only',attempt_id=identity,snapshot_id='snapshot',input_sha256='a'*64,
                    input_text='#p hf/sto-3g opt\n\nSynthetic\n\n0 1\nH 0 0 0\n',template_sha256='b'*64,
                    structure_review='synthetic fixture',resources={'cores':1},remote_directory='/synthetic/no-effects',profile_sha256=('c' if not self.changed else 'd')*64)
    def list_prepared(self):return [dict(available=True,review=self.review('test'),review_sha256=digest(self.review('test')))]
    def submit(self, identity, expected):
        self.calls+=1
        if self.fail:raise OSError('reply lost')
        return dict(state=self.state,attempt_id=identity)
    def status(self,identity):return self.state


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.gateway=Gateway()
        self.queue=TaskQueue(self.root,self.gateway);self.addCleanup(self.queue.close)
    def body(self,identity='test',request='request-0001'):
        return dict(request_id=request,prepared_id=identity,review_sha256=digest(self.gateway.review(identity)))
    def test_duplicate_and_concurrent_request_exactly_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.queue.action('enqueue',self.body()),range(4)))
        self.assertTrue(all(len(r['items'])==1 for r in results))
        self.queue.tick();self.queue.tick()
        self.assertEqual(self.gateway.calls,1)
        with self.assertRaises(QueryError):self.queue.action('enqueue',self.body(request='another-request'))
    def test_unknown_persists_and_stops_next_submission(self):
        self.gateway.fail=True
        self.queue.action('enqueue',self.body());self.queue.action('enqueue',self.body('second','request-0002'))
        self.queue.tick();self.queue.tick()
        self.assertEqual(self.gateway.calls,1)
        self.assertEqual([r['state'] for r in self.queue.snapshot()['items']],['UNKNOWN','QUEUED'])
        self.queue.close();self.queue=TaskQueue(self.root,self.gateway);self.addCleanup(self.queue.close)
        self.queue.tick();self.assertEqual(self.gateway.calls,1)
    def test_restart_submitting_is_unknown_without_replay(self):
        self.queue.action('enqueue',self.body())
        with self.queue.db() as db:db.execute("UPDATE commands SET state='SUBMITTING'")
        self.queue.close();self.queue=TaskQueue(self.root,self.gateway);self.addCleanup(self.queue.close)
        self.queue.tick();self.assertEqual(self.gateway.calls,0)
        self.assertEqual(self.queue.snapshot()['items'][0]['state'],'UNKNOWN')
    def test_drift_blocks_before_effect_and_withdraw_is_local(self):
        self.queue.action('enqueue',self.body());self.gateway.changed=True;self.queue.tick()
        self.assertEqual(self.gateway.calls,0)
        item=self.queue.snapshot()['items'][0];self.assertEqual(item['state'],'BLOCKED')
        self.queue.action('withdraw',{'id':item['id']});self.assertEqual(self.gateway.calls,0)
    def test_capacity_releases_only_after_terminal_state(self):
        self.queue.action('enqueue',self.body());self.queue.action('enqueue',self.body('second','request-0002'))
        self.queue.tick();self.queue.tick();self.assertEqual(self.gateway.calls,1)
        self.gateway.state='SUCCEEDED';self.queue.tick();self.assertEqual(self.gateway.calls,2)
    def test_get_does_not_dispatch_and_cannot_withdraw_submitted(self):
        self.queue.action('enqueue',self.body());self.queue.snapshot();self.assertEqual(self.gateway.calls,0)
        self.queue.tick()
        with self.assertRaises(QueryError):self.queue.action('withdraw',{'id':self.queue.snapshot()['items'][0]['id']})
    def test_only_one_process_owner(self):
        with self.assertRaises(ValueError):TaskQueue(self.root,self.gateway)
    def test_explicit_reconcile_only_reads_existing_core_outcome(self):
        self.gateway.fail=True;self.queue.action('enqueue',self.body());self.queue.tick()
        item=self.queue.snapshot()['items'][0]
        result=self.queue.action('reconcile',{'id':item['id']})
        self.assertEqual(result['items'][0]['state'],'SUBMITTED')
        self.assertEqual(self.gateway.calls,1)
    def test_conflicting_request_and_changed_review(self):
        self.queue.action('enqueue',self.body())
        with self.assertRaises(QueryError):self.queue.action('enqueue',self.body('other'))
        with self.assertRaises(QueryError):self.queue.action('enqueue',dict(self.body('other','request-0002'),review_sha256='0'*64))
    def test_http_write_origin_header_and_disabled_boundary(self):
        db=self.root/'missing-core.db'
        client=TestClient(create_app(db,token=TOKEN,task_queue=self.queue),base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+TOKEN})
        self.assertEqual(client.get('/api/task-center').status_code,200)
        self.assertEqual(client.post('/api/task-center/enqueue',json=self.body()).status_code,403)
        headers={'Origin':'http://127.0.0.1','X-Autog-Task':'task-command/1'}
        self.assertEqual(client.post('/api/task-center/enqueue',headers=dict(headers,Origin='http://evil.test'),json=self.body()).status_code,403)
        self.assertEqual(client.post('/api/task-center/enqueue',headers=headers,json=self.body()).status_code,200)
        self.assertEqual(self.gateway.calls,0)
        disabled=TestClient(create_app(db,token=TOKEN),base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+TOKEN})
        self.assertEqual(disabled.post('/api/task-center/enqueue',headers=headers,json=self.body()).status_code,405)
        self.assertFalse(db.exists())


if __name__=='__main__':unittest.main()
