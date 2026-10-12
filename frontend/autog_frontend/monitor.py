"""Opt-in telemetry collector, independent of Core/Observe and scientific results.

Only the worker starts SSH. HTTP reads a cached snapshot. The remote program is
fixed here; neither browser requests nor configuration can supply shell code.
"""
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime, timezone
import fcntl
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import selectors
import sqlite3
import subprocess
import threading
import time

SCHEMA = 'autog-server-monitor/1'
MAX_BYTES = 256 * 1024
RETENTION = 2880
SECTIONS = ('hostname', 'user', 'clock', 'boot', 'cores', 'load', 'memory',
            'cpu_before', 'cpu_after', 'processes', 'queue', 'nodes', 'queue_details')
# Linux/PBS only. No remote files, shell startup scripts, full process arguments,
# execution reconciliation, scheduler mutations or chemistry programs are used.
REMOTE_SCRIPT = b'''export LC_ALL=C
set -o pipefail
part() {
    printf '__AUTOG_BEGIN_%s__\\n' "$1"
    name="$1"; shift
    "$@"
    code=$?
    printf '\\n__AUTOG_END_%s_%s__\\n' "$name" "$code"
}
part hostname hostname
part user id -un
part clock date -Is
part boot cat /proc/sys/kernel/random/boot_id
part cores nproc
part load cat /proc/loadavg
part memory cat /proc/meminfo
part cpu_before head -n 1 /proc/stat
sleep 1
part cpu_after head -n 1 /proc/stat
part processes timeout 5s ps -u "$(id -un)" -o pid=,ppid=,pcpu=,rss=,etime=,comm= --sort=-pcpu
part queue timeout 5s qstat -u "$(id -un)"
part nodes timeout 5s pbsnodes -a
queue_details() {
    timeout 5s qstat -f | awk '/^Job Id:/ {print;next} /^    (Job_Name|Job_Owner|job_state|queue|server|ctime|qtime|start_time|exec_host|init_work_dir|Output_Path|Error_Path|resources_used[.](cput|mem|vmem|walltime)|Resource_List[.](nodes|mem|walltime)) = / {print}'
}
part queue_details queue_details
'''


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SampleError(Exception):
    pass


def load_config(path: Path):
    if path.stat().st_size > 16384:
        raise ValueError('monitor config too large')
    c = json.loads(path.read_text())
    fields = {'schema', 'host', 'user', 'port', 'identity_file', 'known_hosts',
              'data_directory', 'interval_seconds', 'expected_hostname'}
    if not isinstance(c, dict) or set(c) != fields or c['schema'] != SCHEMA:
        raise ValueError('invalid monitor config')
    ipaddress.ip_address(c['host'])
    for name in ('user', 'expected_hostname'):
        if not isinstance(c[name], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', c[name]):
            raise ValueError('invalid monitor identity')
    if type(c['port']) is not int or not 1 <= c['port'] <= 65535:
        raise ValueError('invalid monitor port')
    if type(c['interval_seconds']) is not int or not 30 <= c['interval_seconds'] <= 300:
        raise ValueError('monitor interval must be 30-300 seconds')
    for name in ('identity_file', 'known_hosts', 'data_directory'):
        p = Path(c[name])
        if not p.is_absolute() or p.is_symlink() or p.resolve() != p:
            raise ValueError('monitor paths must be canonical absolute paths')
        if name != 'data_directory' and not p.is_file():
            raise ValueError('monitor authentication file missing')
    return c


def ssh_argv(c):
    return ['/usr/bin/ssh', '-T', '-F', '/dev/null', '-p', str(c['port']),
            '-i', c['identity_file'], '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + c['known_hosts'],
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
            '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1', '-o', 'ForwardAgent=no',
            '-o', 'ClearAllForwardings=yes', '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=1', c['user'] + '@' + c['host'],
            '/bin/bash --noprofile --norc -s']


def collect(c, stop: threading.Event):
    """Bound time and both output streams; never invoke a local shell."""
    with subprocess.Popen(ssh_argv(c), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}) as p:
        try:
            p.stdin.write(REMOTE_SCRIPT)
            p.stdin.close()
            output = bytearray()
            stderr = bytearray()
            deadline = time.monotonic() + 25
            with selectors.DefaultSelector() as selector:
                for stream in (p.stdout, p.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    if stop.is_set():
                        raise SampleError('stopped')
                    if time.monotonic() > deadline:
                        raise SampleError('timeout')
                    for key, _ in selector.select(.2):
                        block = os.read(key.fd, 8192)
                        if not block:
                            selector.unregister(key.fileobj)
                        else:
                            (output if key.fileobj is p.stdout else stderr).extend(block)
                            if len(output) + len(stderr) > MAX_BYTES:
                                raise SampleError('output-limit')
            if p.wait(timeout=1) != 0:
                if b'Host key verification failed' in stderr or b'HOST IDENTIFICATION HAS CHANGED' in stderr:
                    raise SampleError('host-key-verification-failed')
                if b'Permission denied' in stderr:
                    raise SampleError('authentication-failed')
                raise SampleError('ssh-failed')
            return bytes(output)
        finally:
            if p.poll() is None:
                p.kill()  # Only our local SSH child; never a remote scientific process.
                p.wait()


def parse_sections(raw):
    if len(raw) > MAX_BYTES:
        raise SampleError('output-limit')
    text = raw.decode('utf-8', 'replace')
    pattern = r'__AUTOG_BEGIN_([a-z_]+)__\n(.*?)\n__AUTOG_END_\1_([0-9]+)__\n'
    matches = list(re.finditer(pattern, text, re.S))
    if [m[1] for m in matches] != list(SECTIONS) or ''.join(m[0] for m in matches) != text:
        raise SampleError('invalid-sample')
    return {m[1]: {'exit_code': int(m[3]), 'text': m[2].strip()} for m in matches}


def parse_sample(raw, c):
    s = parse_sections(raw)
    def value(k):
        if s[k]['exit_code'] != 0:
            raise ValueError(k)
        return s[k]['text']
    if s['hostname'] != {'exit_code': 0, 'text': c['expected_hostname']} or s['user'] != {'exit_code': 0, 'text': c['user']}:
        raise SampleError('identity-mismatch')
    metrics = dict(cpu_percent=None, logical_cpus=None, load_1m=None, load_5m=None, load_15m=None,
                   memory_total_mib=None, memory_available_mib=None, memory_used_mib=None,
                   swap_total_mib=None, swap_used_mib=None)
    issues = [k for k in SECTIONS if s[k]['exit_code'] != 0]
    try:
        cores = int(value('cores'))
        if cores <= 0: raise ValueError()
        metrics['logical_cpus'] = cores
    except ValueError: issues.append('cores')
    try:
        load = [float(x) for x in value('load').split()[:3]]
        if len(load) != 3 or any(not math.isfinite(x) or x < 0 for x in load): raise ValueError()
        metrics.update(zip(('load_1m', 'load_5m', 'load_15m'), load))
    except ValueError: issues.append('load')
    try:
        before, after = [[int(x) for x in value(k).split()[1:9]] for k in ('cpu_before', 'cpu_after')]
        delta = [b-a for a,b in zip(before, after)]
        if len(delta) != 8 or min(delta) < 0 or sum(delta) <= 0: raise ValueError()
        # guest counters excluded (already contained in user/nice); iowait idle.
        metrics['cpu_percent'] = round(100 * (sum(delta)-delta[3]-delta[4])/sum(delta), 2)
    except ValueError: issues.append('cpu')
    try:
        mem = {m[1]: int(m[2])/1024 for m in re.finditer(r'^(\w+):\s+(\d+) kB$', value('memory'), re.M)}
        total, available = mem['MemTotal'], mem['MemAvailable']
        swap, free = mem['SwapTotal'], mem['SwapFree']
        if not 0 <= available <= total or total <= 0 or not 0 <= free <= swap: raise ValueError()
        metrics.update(memory_total_mib=total, memory_available_mib=available, memory_used_mib=total-available,
                       swap_total_mib=swap, swap_used_mib=swap-free)
    except (KeyError, ValueError): issues.append('memory')
    processes = []
    try:
        for line in value('processes').splitlines():
            pid, ppid, cpu, rss, elapsed, command = line.split(None, 5)
            item = dict(pid=int(pid), ppid=int(ppid), cpu_percent=float(cpu), rss_mib=int(rss)/1024,
                        elapsed=elapsed, command=command)
            if not math.isfinite(item['cpu_percent']) or min(item['pid'], item['ppid'], item['cpu_percent'], item['rss_mib']) < 0:
                raise ValueError()
            processes.append(item)
    except ValueError:
        processes = []; issues.append('processes')
    return dict(sampled_at=utc_now(), server_time=s['clock']['text'] if s['clock']['exit_code']==0 else None,
                hostname=c['expected_hostname'], user=c['user'], boot_id=s['boot']['text'], metrics=metrics,
                processes=processes[:40], process_count=len(processes), issues=sorted(set(issues)),
                raw_sha256=hashlib.sha256(raw).hexdigest(), sources=s,
                process_scope='login-user-on-sampled-host', job_attempt_binding='unavailable')


class Monitor:
    def __init__(self, config_path: Path):
        self.config = load_config(config_path)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.last_success = None
        self.last_poll_at = None
        self.error = None
        self.history = deque(maxlen=120)
        self.lease = None

    def start(self):
        if self.thread is not None: return
        directory = Path(self.config['data_directory'])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lease = (directory / 'collector.lock').open('a')
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close(); self.lease = None
            raise ValueError('a monitor collector already owns this data directory') from None
        self.thread = threading.Thread(target=self._run, name='autog-telemetry', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=5)
        if self.lease and (not self.thread or not self.thread.is_alive()):
            self.lease.close(); self.lease = None

    def _run(self):
        db = None
        try:
            db = sqlite3.connect(Path(self.config['data_directory']) / 'telemetry.sqlite3')
            db.execute('CREATE TABLE IF NOT EXISTS identity (binding TEXT NOT NULL)')
            binding = json.dumps({k:self.config[k] for k in ('host','user','port','expected_hostname')}, sort_keys=True)
            rows = db.execute('SELECT binding FROM identity').fetchall()
            if rows and rows != [(binding,)]: raise ValueError('telemetry-source-changed')
            if not rows: db.execute('INSERT INTO identity VALUES (?)', (binding,))
            db.execute('CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            db.commit()
            # This is our own telemetry cache, never Core or the result library.
            for (payload,) in reversed(db.execute('SELECT payload FROM samples ORDER BY id DESC LIMIT ?', (RETENTION,)).fetchall()):
                self._remember(json.loads(payload))
            while not self.stop.is_set():
                record = {'polled_at': utc_now(), 'sample': None, 'error': None}
                try:
                    raw = collect(self.config, self.stop)
                    record['sample'] = parse_sample(raw, self.config)
                    record['raw_base64'] = base64.b64encode(raw).decode('ascii')
                except SampleError as exc:
                    if str(exc) == 'stopped': break
                    record['error'] = str(exc)
                except (OSError, ValueError, subprocess.SubprocessError):
                    record['error'] = 'collector-failed'
                # Never present an unpersisted sample as recorded evidence.
                with db:
                    db.execute('INSERT INTO samples(payload) VALUES (?)', (json.dumps(record, allow_nan=False),))
                    db.execute('DELETE FROM samples WHERE id <= (SELECT COALESCE(MAX(id),0)-? FROM samples)', (RETENTION,))
                self._remember(record)
                if self.stop.wait(self.config['interval_seconds']): break
        except (OSError, ValueError, sqlite3.Error):
            with self.lock: self.error = 'telemetry-store-unavailable'
        finally:
            if db: db.close()

    def _remember(self, record):
        with self.lock:
            self.last_poll_at = record['polled_at']
            self.error = record['error']
            sample = record['sample']
            if sample: self.last_success = sample
            self.history.append({'at': record['polled_at'], 'metrics': sample['metrics'] if sample else None,
                                 'error': record['error']})

    def snapshot(self):
        with self.lock:
            sample = self.last_success
            age = max(0, (datetime.now(timezone.utc)-datetime.fromisoformat(sample['sampled_at'])).total_seconds()) if sample else None
            state = ('unavailable' if self.error else 'waiting') if not sample else (
                'stale' if self.error or age > self.config['interval_seconds']*3 else 'partial' if sample['issues'] else 'fresh')
            return dict(schema=SCHEMA, enabled=True, state=state, error=self.error,
                        interval_seconds=self.config['interval_seconds'], age_seconds=round(age, 1) if age is not None else None,
                        last_poll_at=self.last_poll_at, sample=sample, history=list(self.history),
                        retention_samples=RETENTION, route='Mac → SSH → ' + self.config['host'],
                        server_identity={k:self.config[k] for k in ('host','port','user','expected_hostname')},
                        authority='telemetry-only; no Core transitions or scientific acceptance')
