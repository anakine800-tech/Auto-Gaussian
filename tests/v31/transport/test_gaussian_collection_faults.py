"""Actual local faults through native Gaussian recovery, inert final wire only."""
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest

from tests.v31.transport import _gaussian_recovery_fixture as fixture

MODULE = 'tests.v31.transport._gaussian_recovery_fixture'


class GaussianCollectionFaultTests(unittest.TestCase):
    def case(self, stage, phase):
        retained = os.environ.get('AUTO_G16_FAULT_EVIDENCE_ROOT')
        if retained:
            folder = Path(retained).resolve() / (stage + '-' + phase)
            folder.mkdir()
        else:
            tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
            folder = Path(tmp.name).resolve()
        path = folder / 'state.json'
        self.child('build-' + stage, path, scratch=folder)
        before = fixture.persisted(fixture.load(path))
        (folder / 'baseline.json').write_text(json.dumps(before))
        return path, before

    def child(self, mode, path, *, scratch=None, expected=0):
        env = dict(os.environ)
        if scratch: env['TMPDIR'] = str(scratch)
        completed = subprocess.run([sys.executable, '-m', MODULE, mode, str(path)],
            env=env, capture_output=True, text=True, timeout=120)
        ordinal = len(list(path.parent.glob('process-*.json')))
        (path.parent / f'process-{ordinal:02d}.json').write_text(json.dumps({
            'mode': mode, 'returncode': completed.returncode,
            'stdout': completed.stdout, 'stderr': completed.stderr}, indent=2))
        self.assertEqual(completed.returncode, expected, completed.stderr[-8000:])
        return json.loads(completed.stdout) if completed.stdout else None

    def wire(self, path):
        return [json.loads(line) for line in Path(str(path) + '.wire.jsonl').read_text().splitlines()]

    def unchanged_history(self, before, after):
        self.assertEqual(set(before), {'core','approval','transport','project-journal'})
        for role, tables in before.items():
            for name, rows in tables.items():
                if name in {'attempts', 'sqlite_sequence'}: continue
                with self.subTest(role=role, table=name):
                    counts = Counter(json.dumps(r, sort_keys=True) for r in after[role][name])
                    self.assertFalse(Counter(json.dumps(r, sort_keys=True) for r in rows) - counts)
        for role in ('approval', 'project-journal'):
            self.assertEqual(json.loads(json.dumps(before[role])), after[role])
        self.assertEqual([row[:-1] for row in before['core']['attempts']],
                         [row[:-1] for row in after['core']['attempts']])
        self.assertEqual(len(after['core']['attempts']), 1)
        self.assertEqual(len(after['core']['submission_intents']), 1)
        self.assertEqual(before['core']['submission_outcomes'], after['core']['submission_outcomes'])

    def finish(self, path, before, response):
        self.assertEqual(response['verdict'], 'SUCCEEDED', response.get('rejected'))
        self.assertTrue(response['result_id'])
        self.unchanged_history(before, response['persisted'])
        wire_before = self.wire(path)
        replay = self.child('resume', path)
        self.assertEqual(self.wire(path), wire_before)
        self.assertEqual(replay['result_id'], response['result_id'])
        self.assertEqual(replay['persisted'], response['persisted'])
        self.assertEqual(sum(r['operation']=='SUBMIT_QSUB_ONCE' for r in wire_before), 1)
        self.assertTrue(all(r['operation'] in fixture.READS for r in wire_before if r['phase'] != 'setup'))
        data = fixture.load(path)
        pins = {b.role: {'sha256': sha256(Path(b.path).read_bytes()).hexdigest(), 'path': b.path} for b in data['run'].databases}
        (path.parent / 'verified.json').write_text(json.dumps({'result_id': response['result_id'],
            'qsub_count': 1, 'wire_log': str(path)+'.wire.jsonl', 'stores':pins}, indent=2))

    def test_opt_and_freq_real_exit_matrix(self):
        phases = ('before-audit','audit','wire','physical','before-result','result','assessment','before-transition','transition')
        for stage in ('opt','freq'):
            for phase in phases:
                with self.subTest(stage=stage, phase=phase):
                    path, before = self.case(stage, phase)
                    self.child('crash-' + phase, path, expected=17)
                    crash_prefix = fixture.persisted(fixture.load(path))
                    (path.parent/'crash-prefix.json').write_text(json.dumps(crash_prefix))
                    self.unchanged_history(before, crash_prefix)
                    at_crash = self.wire(path)
                    resumed = self.child('resume', path)
                    self.unchanged_history(crash_prefix, resumed['persisted'])
                    if phase in {'audit','wire','physical','before-result'}:
                        self.assertIn('already consumed', resumed.get('rejected',''))
                        self.assertEqual(self.wire(path), at_crash)
                        self.assertEqual(resumed['persisted'], crash_prefix)
                        repeat = self.child('resume', path)
                        self.assertEqual(repeat['persisted'], resumed['persisted'])
                        self.assertEqual(self.wire(path), at_crash)
                        resumed = self.child('resume-next', path)
                    elif phase != 'before-audit':
                        self.assertEqual(self.wire(path), at_crash)
                    self.finish(path, crash_prefix, resumed)

    def test_opt_and_freq_real_transport_timeout(self):
        for stage in ('opt','freq'):
            with self.subTest(stage=stage):
                path, before = self.case(stage, 'timeout')
                failed = self.child('timeout', path)
                self.assertEqual(failed.get('verdict'), 'UNKNOWN')
                self.assertEqual(failed.get('diagnostic'), 'acquisition-unknown')
                self.assertEqual(failed['persisted']['core']['attempts'][0][-1], 'SUBMITTED')
                self.unchanged_history(before, failed['persisted'])
                (path.parent/'timeout-prefix.json').write_text(json.dumps(failed['persisted']))
                peers = [json.loads(line) for line in Path(str(path)+'.peer.jsonl').read_text().splitlines()]
                self.assertEqual(len(peers), 2)
                self.assertEqual(peers[0]['pid'], peers[1]['pid'])
                self.assertEqual(peers[1]['event'], 'reaped')
                self.assertEqual(peers[1]['completion_status'], 'timeout')
                self.assertLess(peers[1]['returncode'], 0)
                with self.assertRaises(ProcessLookupError): os.kill(peers[1]['pid'], 0)
                count = len(self.wire(path))
                replay = self.child('resume', path)
                self.assertEqual(len(self.wire(path)), count)
                self.assertIn('already consumed', replay.get('rejected',''))
                self.assertEqual(replay['persisted'], failed['persisted'])
                self.finish(path, failed['persisted'], self.child('resume-next', path))

    def test_opt_and_freq_real_process_guard_contention(self):
        for stage in ('opt','freq'):
            with self.subTest(stage=stage):
                path, before = self.case(stage, 'guard')
                with subprocess.Popen([sys.executable, '-m', MODULE, 'hold-guard', str(path)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as holder:
                    held, handshake, cleanup_timeout = None, '', False
                    try:
                        with selectors.DefaultSelector() as selector:
                            selector.register(holder.stdout, selectors.EVENT_READ)
                            self.assertTrue(selector.select(30), 'guard handshake missing')
                        handshake = holder.stdout.readline()
                        self.assertTrue(handshake, 'guard holder exited before handshake')
                        held = json.loads(handshake)
                        self.assertTrue(held['held'])
                        self.assertEqual(held['pid'], holder.pid)
                        guard_prefix = fixture.persisted(fixture.load(path))
                        (path.parent/'guard-prefix.json').write_text(json.dumps(guard_prefix))
                        count = len(self.wire(path))
                        contender = self.child('resume', path)
                        self.assertIn('busy', contender.get('rejected',''))
                        self.assertEqual(contender['persisted'], guard_prefix)
                        self.assertEqual(len(self.wire(path)), count)
                    finally:
                        try:
                            out, err = holder.communicate(
                                input='release\n' if holder.poll() is None else None, timeout=30)
                        except subprocess.TimeoutExpired:
                            cleanup_timeout = True
                            holder.kill()
                            out, err = holder.communicate(timeout=30)
                        (path.parent/'guard.json').write_text(json.dumps({
                            'pid':holder.pid, 'holder':held, 'handshake':handshake,
                            'returncode':holder.returncode, 'stdout':out, 'stderr':err,
                            'cleanup_timeout':cleanup_timeout}))
                    self.assertFalse(cleanup_timeout, 'guard fixture cleanup timed out')
                    self.assertEqual(holder.returncode, 0, err)
                self.unchanged_history(before, guard_prefix)
                self.finish(path, guard_prefix, self.child('resume', path))


if __name__ == '__main__': unittest.main()
