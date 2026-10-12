import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from autog_frontend.monitor import (Monitor, REMOTE_SCRIPT, SECTIONS, SampleError,
                                    collect, load_config, parse_sample, ssh_argv)
from autog_frontend.api import create_app
from tests.test_api import TestClient, TOKEN


def raw_sample(overrides=None):
    data = dict(hostname='test-node', user='testuser', clock='2026-09-25T01:00:00+0000', boot='fixture-boot',
                cores='4', load='1.00 2.00 3.00 1/200 123',
                memory='MemTotal: 8192000 kB\nMemAvailable: 6144000 kB\nSwapTotal: 1024000 kB\nSwapFree: 512000 kB',
                cpu_before='cpu 100 0 100 800 0 0 0 0 20 0',
                cpu_after='cpu 150 0 150 900 0 0 0 0 40 0',
                processes='12 1 200.0 1048576 01:01:01 l502.exe\n13 1 0.0 1024 00:01 bash',
                queue_details='', queue='fixture PBS job R', nodes='test-node\n     state = free\n     jobs = 0-3/fixture')
    if overrides: data.update(overrides)
    return ''.join(f'__AUTOG_BEGIN_{k}__\n{data[k][0] if isinstance(data[k],tuple) else data[k]}\n__AUTOG_END_{k}_{data[k][1] if isinstance(data[k],tuple) else 0}__\n' for k in SECTIONS).encode()


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        for name in ('key','hosts'): (self.root/name).write_text('inert test metadata; never SSH')
        self.config=dict(schema='autog-server-monitor/1',host='192.0.2.1',user='testuser',port=22,
                         identity_file=str(self.root/'key'),known_hosts=str(self.root/'hosts'),
                         data_directory=str(self.root/'telemetry'),interval_seconds=30,expected_hostname='test-node')
        self.path=self.root/'config.json';self.path.write_text(json.dumps(self.config))

    def test_real_format_units_cpu_and_missingness(self):
        sample=parse_sample(raw_sample(),self.config)
        self.assertEqual(sample['metrics']['cpu_percent'],50)
        self.assertEqual(sample['metrics']['memory_used_mib'],2000)
        self.assertEqual(sample['metrics']['swap_used_mib'],500)
        self.assertEqual(sample['processes'][0]['rss_mib'],1024)
        self.assertEqual(sample['processes'][0]['cpu_percent'],200)
        self.assertEqual(sample['issues'],[])
        sample=parse_sample(raw_sample({'memory':('permission denied',1),'queue':('failed',1),'processes':('failed',1)}),self.config)
        self.assertIsNone(sample['metrics']['memory_used_mib'])
        self.assertIn('processes',sample['issues'])
        self.assertEqual(sample['sources']['queue']['exit_code'],1)

    def test_malformed_or_mismatched_never_success(self):
        for raw in (raw_sample()+b'junk', raw_sample({'hostname':'other-node'}),raw_sample({'user':'other'}),b'not a sample'):
            with self.assertRaises(SampleError):parse_sample(raw,self.config)
        for override,key in (({'cpu_after':'cpu 0 0 0 0 0 0 0 0'},'cpu_percent'),({'load':'nan 2 3'},'load_1m')):
            sample=parse_sample(raw_sample(override),self.config)
            self.assertIsNone(sample['metrics'][key])

    def test_config_fixed_command_and_trust(self):
        for k,v in (('host','evil;touch /tmp/x'),('user','x; id'),('interval_seconds',1),('command','qsub'),('identity_file','relative')):
            c={**self.config,k:v};self.path.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load_config(self.path)
        args=ssh_argv(self.config)
        self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertIn('BatchMode=yes',args)
        self.assertIn('ForwardAgent=no',args)
        self.assertEqual(args[-1],'/bin/bash --noprofile --norc -s')
        for word in (b'qsub',b'qdel',b'kill ',b'rm ',b'> /',b'sudo'):
            self.assertNotIn(word,REMOTE_SCRIPT)

    def test_stale_retains_success_and_gaps(self):
        m=Monitor(self.path);sample=parse_sample(raw_sample(),self.config)
        m._remember(dict(polled_at=sample['sampled_at'],sample=sample,error=None))
        self.assertEqual(m.snapshot()['state'],'fresh')
        m._remember(dict(polled_at=sample['sampled_at'],sample=None,error='timeout'))
        dto=m.snapshot()
        self.assertEqual(dto['state'],'stale');self.assertEqual(dto['sample'],sample)
        self.assertIsNone(dto['history'][-1]['metrics'])
        self.assertNotIn(self.config['identity_file'],json.dumps(dto))
        m.error=None;m.last_success={**sample,'sampled_at':'2020-01-01T00:00:00+00:00'}
        self.assertEqual(m.snapshot()['state'],'stale')

    def test_http_get_does_not_spawn_or_write(self):
        monitor=Monitor(self.path)
        client=TestClient(create_app(self.root/'absent-core.sqlite3',token=TOKEN,monitor=monitor),base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+TOKEN})
        with patch('subprocess.Popen',side_effect=AssertionError('no SSH from GET')):
            self.assertEqual(client.get('/api/monitor').status_code,200)
            self.assertEqual(client.post('/api/monitor').status_code,405)
            self.assertEqual(client.get('/api/monitor?host=evil').status_code,400)
        self.assertFalse((self.root/'absent-core.sqlite3').exists())
        self.assertFalse((self.root/'telemetry').exists())

    def test_worker_persistence_recovery_and_exclusive_lease(self):
        m=Monitor(self.path)
        saved=threading.Event()
        original=m._remember
        def remember(r):original(r); saved.set()
        with patch('autog_frontend.monitor.collect',return_value=raw_sample()),patch.object(m,'_remember',side_effect=remember):
            m.start()
            try:
                self.assertTrue(saved.wait(3))
                with self.assertRaises(ValueError):Monitor(self.path).start()
            finally:m.close()
        dbpath=self.root/'telemetry/telemetry.sqlite3'
        with closing(sqlite3.connect(dbpath)) as db:
            row=json.loads(db.execute('SELECT payload FROM samples').fetchone()[0])
        self.assertEqual(hashlib.sha256(base64.b64decode(row['raw_base64'])).hexdigest(),row['sample']['raw_sha256'])
        m2=Monitor(self.path);m2.stop.set();m2._run()
        self.assertEqual(m2.snapshot()['sample']['hostname'],'test-node')
        self.assertEqual(m2.snapshot()['state'],'fresh')
        self.config['host']='192.0.2.2';self.path.write_text(json.dumps(self.config))
        wrong=Monitor(self.path);wrong.stop.set();wrong._run()
        self.assertEqual(wrong.snapshot()['error'],'telemetry-store-unavailable')
        self.assertIsNone(wrong.snapshot()['sample'])

    def test_output_cap_and_stop_kill_only_our_local_child(self):
        # Real local subprocesses, no network. Both streams bounded.
        with patch('autog_frontend.monitor.ssh_argv',return_value=[sys.executable,'-c','import sys;sys.stdin.read();sys.stdout.write("x"*400000);sys.stdout.flush()']):
            with self.assertRaisesRegex(SampleError,'output-limit'):collect(self.config,threading.Event())
        stop=threading.Event();stop.set()
        with patch('autog_frontend.monitor.ssh_argv',return_value=[sys.executable,'-c','import sys,time;sys.stdin.read();time.sleep(30)']):
            with self.assertRaisesRegex(SampleError,'stopped'):collect(self.config,stop)
