"""T127 offline acceptance: synthetic clocks, schedulers, and local IPC only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ag import cli, config, monitor, pbs, remote, status
from ag.transport import Result
from test_monitor import identity, Fake, job
from test_core import cfg, write_config
from test_slurm import multi
from test_monitor_all_jobs import PartitionFake


class Clock:
    def __init__(self, monkeypatch):
        self.tick = 0.0
        monkeypatch.setattr(monitor.time, 'monotonic', lambda: self.tick)
        monkeypatch.setattr(monitor, 'utc_now', lambda: self.now)

    @property
    def now(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.tick)

    def advance(self, seconds):
        self.tick += seconds


@pytest.mark.parametrize('base', [30, 60, 90, 600])
def test_backoff_and_success(base, monkeypatch):
    clock = Clock(monkeypatch)
    schedule = monitor.Sampling(base)
    for count in range(1, 40):
        schedule.record(False, None, 'scheduled', clock.tick, clock.now)
        expected = min(600, base * 2 ** max(0, count - 2))
        assert schedule.current == expected
        assert schedule.failures == count
        assert schedule.state == ('normal' if count < 3 else 'backoff')
        assert schedule.due == clock.tick + expected
        clock.advance(expected)
    schedule.record(True, None, 'scheduled', clock.tick, clock.now)
    assert (schedule.state, schedule.failures, schedule.current) == ('normal', 0, base)


@pytest.mark.parametrize('detail,category', [
    ('Permission denied (publickey,password).', 'auth'),
    ('Permission denied (keyboard-interactive,hostbased,gssapi-with-mic).', 'auth'),
    ('Permission denied (gssapi-keyex).', 'auth'),
    ('Permission denied (publickey).', 'auth'),
    ('Host key verification failed.', 'host_key'),
    ('WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!', 'host_key'),
    ('cat: x: Permission denied', None),
    ('Permission denied', None),
    ('Permission denied (unknown)', None),
])
def test_authentication_categories_before_redaction(cfg, monkeypatch, detail, category):
    monkeypatch.setattr(monitor.subprocess, 'run', lambda *a, **k: Result(255, stderr=detail))
    transport = monitor.MonitorTransport(cfg, read_only=True)
    transport.run(remote.jobs())
    assert transport.failure_category == category
    assert monitor.failure_category(detail) == category


@pytest.mark.parametrize('category', ['auth', 'host_key'])
def test_manual_success_failure_and_auth_pause(monkeypatch, category):
    clock = Clock(monkeypatch)
    schedule = monitor.Sampling(60)
    for _ in range(4):
        schedule.record(False, None, 'scheduled', clock.tick, clock.now)
    saved = deepcopy(schedule)
    schedule.record(False, None, 'manual', clock.tick, clock.now)
    assert schedule == saved
    schedule.record(False, category, 'manual', clock.tick, clock.now)
    assert schedule.state == 'paused' and schedule.failures == 4
    assert schedule.pause_reason == category and schedule.next_at is None
    saved = deepcopy(schedule)
    schedule.record(False, None, 'manual_auth_fixed', clock.tick, clock.now)
    assert schedule == saved
    schedule.record(True, None, 'manual_auth_fixed', clock.tick, clock.now)
    assert schedule.snapshot('manual_auth_fixed') == dict(state='normal', consecutive_failures=0,
        current_interval_seconds=60, next_sample_at='2026-01-01T00:01:00Z', pause_reason=None,
        trigger='manual_auth_fixed', retry_pending=False)


def requested(cfg, capsys, **kwargs):
    code = monitor.retry(cfg, 'default', json_output=True, **kwargs)
    return code, json.loads(capsys.readouterr().out.splitlines()[-1])


def test_retry_lifecycle_and_request_merging(cfg, capsys, monkeypatch):
    clock = Clock(monkeypatch)
    schedule = monitor.Sampling(60)
    with monitor.WatchControl(cfg) as control:
        control.configure({'default': cfg}, {'default': schedule})
        code, value = requested(cfg, capsys)
        assert code == 0 and value == dict(entry='default', result='queued', reason=None,
                                          requested_at='2026-01-01T00:00:00Z')
        original = (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).read_bytes()
        code, value = requested(cfg, capsys)
        assert code == 0 and value['result'] == 'already_queued'
        assert (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).read_bytes() == original
        assert control.begin('default', cfg, schedule) == 'manual'
        assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
        code, value = requested(cfg, capsys)
        assert code == 0 and value['result'] == 'in_progress'
        schedule.record(True, None, 'manual', clock.tick, clock.now)
        control.finish('default', schedule)
        assert control.begin('default', cfg, schedule) is None
    code, value = requested(cfg, capsys)
    assert code == 1 and value['reason'] == 'monitor_not_running'
    assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
    assert not any(p.is_dir() for p in monitor.control_root(cfg).iterdir())


@pytest.mark.parametrize('category', ['auth', 'host_key'])
def test_paused_retry_requires_confirmation_and_only_attempts_once(cfg, capsys, monkeypatch, category):
    clock = Clock(monkeypatch)
    schedule = monitor.Sampling(60)
    schedule.record(False, category, 'scheduled', clock.tick, clock.now)
    with monitor.WatchControl(cfg) as control:
        control.configure({'default': cfg}, {'default': schedule})
        assert control.begin('default', cfg, schedule) is None
        code, value = requested(cfg, capsys)
        assert code == 1 and value['reason'] == 'auth_confirmation_required'
        assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
        assert requested(cfg, capsys, auth_fixed=True)[1]['result'] == 'queued'
        assert control.begin('default', cfg, schedule) == 'manual_auth_fixed'
        schedule.record(False, category, 'manual_auth_fixed', clock.tick, clock.now)
        control.finish('default', schedule)
        assert control.begin('default', cfg, schedule) is None


@pytest.mark.parametrize('mode', ['absent-cache', 'absent-heartbeat', 'stale', 'dead', 'missing-lock'])
def test_retry_without_live_monitor_leaves_files_unchanged(cfg, capsys, mode, monkeypatch):
    clock = Clock(monkeypatch)
    studies = Path(cfg['local']['studies_root'])
    root = studies / '.ag-monitor'
    if mode != 'absent-cache':
        root.mkdir(parents=True)
    if mode in ('stale', 'dead', 'missing-lock'):
        monitor.write_control(root, dict(pid=os.getpid(), heartbeat_at=monitor.iso_at(clock.now),
                                         entries={'default': {}}))
        if mode != 'missing-lock':
            with monitor.control_lock(cfg):
                pass
        if mode == 'stale':
            clock.advance(91)
        elif mode == 'dead':
            monkeypatch.setattr(monitor.os, 'kill', lambda *a: (_ for _ in ()).throw(ProcessLookupError()))
    def inventory():
        return {str(p.relative_to(studies)): p.read_bytes() if p.is_file() else None
                for p in studies.rglob('*')}
    before = inventory()
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: pytest.fail('Retry must remain local'))
    code, value = requested(cfg, capsys)
    assert code == 1 and value['reason'] == 'monitor_not_running'
    assert value['requested_at'] is None
    assert not (root / monitor.REQUEST_FILE).exists()
    assert inventory() == before


@pytest.mark.parametrize('name', ['unknown', '../escape', '/absolute', 'x/y', ''])
def test_unknown_retry_entry_never_creates_cache(cfg, capsys, name):
    assert monitor.retry(cfg, name, json_output=True) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'unknown_entry'
    assert not (Path(cfg['local']['studies_root']) / '.ag-monitor').exists()


@pytest.mark.parametrize('filename', [monitor.REQUEST_FILE, monitor.WATCH_FILE, 'watch.lock'])
def test_control_files_refuse_symlinks(cfg, capsys, filename):
    target = Path(cfg['local']['studies_root']) / 'untouched.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{}')
    with monitor.WatchControl(cfg):
        path = monitor.control_root(cfg) / filename
        if path.exists():
            path.unlink()
        path.symlink_to(target)
        try:
            with pytest.raises(ValueError, match='symbolic links'):
                requested(cfg, capsys)
        finally:
            path.unlink()
    assert target.read_text() == '{}'


def test_startup_discards_requests_and_does_not_restore_pause(cfg, identity, monkeypatch, capsys):
    clock = Clock(monkeypatch)
    root = monitor.cache_dir(cfg)
    (root / monitor.REQUEST_FILE).write_text('leftover invalid request')
    saved = monitor.empty_snapshot(cfg)
    saved['sampling'].update(state='paused', pause_reason='auth')
    monitor.publish(root, saved)
    fake = Fake()
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    def sleep(delay):
        assert 0 < delay <= 2
        clock.advance(delay)
        if clock.tick >= 10:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(cfg, 60) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1  # five idle wakeups neither print nor append history
    value = json.loads(lines[0])
    assert value['discarded_retry_requests'] == ['default']
    assert value['entries']['default']['state'] == 'normal'
    assert value['entries']['default']['trigger'] == 'scheduled'
    assert len(fake.calls) == 3
    assert len((root / 'history.jsonl').read_text().splitlines()) == 2


def test_heartbeat_during_slow_sampling_is_local_only(cfg, monkeypatch):
    clock = Clock(monkeypatch)
    control = monitor.WatchControl(cfg)
    control.value = dict(pid=os.getpid(), heartbeat_at=monitor.iso_at(clock.now), sampling='default',
                         sample_started_at=monitor.iso_at(clock.now), entries={'default': {}})
    class Stop:
        def wait(self, seconds):
            assert seconds == 30
            clock.advance(seconds)
            return clock.tick > 120
    control.stopped = Stop()
    monkeypatch.setattr(monitor.subprocess, 'run', lambda *a, **k: pytest.fail('Heartbeat must be local'))
    control.heartbeat()
    value = monitor.read_control(monitor.control_root(cfg) / monitor.WATCH_FILE)
    assert monitor.watch_alive(value) and value['sampling'] == 'default'
    assert value['heartbeat_at'] == '2026-01-01T00:02:00Z'


@pytest.mark.parametrize('legacy', [True, False])
def test_scheduler_pauses_only_failed_entry_and_resets_config(multi, cfg, monkeypatch, capsys, legacy):
    clock = Clock(monkeypatch)
    active = cfg if legacy else multi
    calls = []
    changed = [False]
    def build(entry, **kwargs):
        fake = Fake()
        name = entry.get('_cluster', 'default')
        original = fake.run
        def run(command):
            if command.operation == 'jobs':
                calls.append((name, clock.tick))
                if name == 'default' and not changed[0]:
                    return Result(255, stderr='Permission denied (publickey).')
            return original(command)
        fake.run = run
        return fake
    # Keep both test entries PBS so no irrelevant fake Slurm commands occur.
    if not legacy:
        multi['clusters']['batch'] = deepcopy(multi['clusters']['default'])
    monkeypatch.setattr(monitor, 'MonitorTransport', build)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    current = [active]
    monkeypatch.setattr(monitor, 'reload_config', lambda _: (current[0], None))
    def sleep(seconds):
        clock.advance(seconds)
        if clock.tick >= 92:
            raise KeyboardInterrupt
        if clock.tick >= 65 and not changed[0]:
            changed[0] = True
            current[0] = deepcopy(active)
            entry = current[0] if legacy else current[0]['clusters']['default']
            entry['monitor_interval_seconds'] = 90
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(active, 30) == 0
    assert [at for name, at in calls if name == 'default'] == [0, 66]
    if not legacy:
        assert [at for name, at in calls if name == 'batch'] == [0, 30, 60, 90]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]['entries']['default']['state'] == 'paused'
    assert lines[-1]['entries']['default']['state'] == 'normal'


@pytest.mark.parametrize('value', [20, 601, '60', True, 30.0])
def test_interval_invalid(multi, value):
    for entry in multi['clusters'].values():
        entry['monitor_interval_seconds'] = value
        with pytest.raises(config.ConfigError, match='monitor_interval_seconds'):
            config.validate_cluster(entry)


def test_interval_defaults_and_legacy_merge(multi):
    pbs_entry = multi['clusters']['default']
    slurm_entry = multi['clusters']['batch']
    assert monitor.entry_interval(pbs_entry, 30) == 30
    assert monitor.entry_interval(slurm_entry, 30) == 60
    for entry in (pbs_entry, slurm_entry):
        entry['monitor_interval_seconds'] = 90
        config.validate_cluster(entry)
        assert monitor.entry_interval(entry, 30) == 90
        assert monitor.entry_interval(entry, None) is None
    legacy = deepcopy(pbs_entry)
    legacy.update(local=multi['local'], _config_dir=multi['_config_dir'],
                  clusters={'batch': slurm_entry})
    legacy.pop('monitor_interval_seconds')
    file = write_config(legacy)
    file.write_text('monitor_interval_seconds = 90\n' + file.read_text())
    loaded = config.load_config(file)
    assert loaded['clusters']['default']['monitor_interval_seconds'] == 90


def torque(name='node-a', assignments=None, extra=''):
    text = (f'{name}\n    state = free\n    np = 64\n'
            '    status = opsys=linux,physmem=67108864kb,availmem=999999999kb,\n'
            '        totmem=888888888kb\n')
    return text + (f'    jobs = {assignments}\n' if assignments is not None else '') + extra


@pytest.mark.parametrize('problem,expected', [(None, 24.0), ('missing', None), ('invalid', None),
                                             ('cross_node', None), ('id_mismatch', None)])
def test_torque_memory_exact_job_mapping(problem, expected):
    jobs = status.parse_jobs(job('901.fixture', extra='    exec_host = node-a/0-3\n') +
                             job('902.fixture', extra='    exec_host = node-a/4-7\n'))
    nodes = torque(assignments='0-3/901.fixture,4-7/902.fixture')
    if problem == 'missing':
        del jobs[0]['Resource_List.mem']
    if problem == 'invalid':
        jobs[0]['Resource_List.mem'] = 'unknown'
    if problem == 'cross_node':
        jobs[0]['exec_host'] += '+node-b/0-3'
        nodes += torque('node-b', '0-3/901.fixture')
    if problem == 'id_mismatch':
        jobs[0]['job_id'] = '901.different'
    notes = []
    values = pbs.parse_nodes(nodes, jobs, notes=notes)
    assert all(n['mem_total_gb'] == 64.0 and n['mem_assigned_gb'] == expected for n in values)
    assert bool(notes) == bool(problem)
    assert all('未知' in n for n in notes)
    assert all('node-' not in n and '901' not in n for n in notes)


def test_torque_idle_and_pbs_pro_priority():
    node = pbs.parse_nodes(torque(), [])[0]
    assert node['mem_total_gb'] == 64.0 and node['mem_assigned_gb'] == 0.0
    node = pbs.parse_nodes(torque(extra='    resources_available.mem = 128gb\n'
                                      '    resources_assigned.mem = 7gb\n'), [])[0]
    assert node['mem_total_gb'] == 128.0 and node['mem_assigned_gb'] == 7.0


def test_notes_scheduler_old_cache_and_history(cfg, identity, multi):
    root = monitor.cache_dir(cfg)
    old = monitor.sample(cfg, Fake())
    old.pop('sampling')
    old['cluster']['hardware'].pop('notes')
    (root / 'latest.json').write_text(json.dumps(old))
    fake = Fake()
    fake.replies['jobs'] = Result(1, stderr='synthetic failure')
    result = monitor.sample(cfg, fake)
    assert result['sampling'] == monitor.once_sampling()
    assert result['cluster']['scheduler'] == 'pbs'
    assert result['cluster']['hardware']['notes'] == []
    history = json.loads((root / 'history.jsonl').read_text().splitlines()[-1])
    assert history['sampling_state'] == 'normal' and history['consecutive_failures'] == 0
    assert history['trigger'] == 'scheduled'
    entry = config.select_cluster(multi, 'batch')
    fake = PartitionFake(entry)
    fake.hardware = Result(stdout='24/36/4/64|65536+|2\n')
    hardware = monitor.observation(entry, fake, 'userA')['cluster']['hardware']
    assert hardware['error'] is None and hardware['cores_total'] == 64
    assert any('异构' in n for n in hardware['notes'])


def test_cli_retry_and_watch_contract(cfg, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: pytest.fail('Retry must not SSH'))
    assert cli.main(['monitor', '--retry', 'default', '--json']) == 1
    value = json.loads(capsys.readouterr().out)
    assert value['reason'] == 'monitor_not_running'
    with pytest.raises(SystemExit) as exc:
        cli.main(['monitor', '--retry', 'default', '--watch', '30'])
    assert exc.value.code == 2
    assert cli.main(['monitor', '--auth-fixed']) == 1


def test_summary_has_no_job_details_and_idle_triggers_are_null(cfg, identity, capsys):
    snapshot = monitor.sample(cfg, Fake())
    monitor.print_round({'first': snapshot, 'second': snapshot}, {'first'}, json_output=False, multi=True)
    text = capsys.readouterr().out
    value = json.loads(text)
    assert value['schema'] == 'ag-monitor-line/1'
    assert value['entries']['first']['jobs'] == 2
    assert value['entries']['first']['sampled'] and value['entries']['first']['trigger'] == 'scheduled'
    assert not value['entries']['second']['sampled'] and value['entries']['second']['trigger'] is None
    assert all(secret not in text for secret in ('fixture', 'other', '101', 'water'))


@pytest.mark.parametrize('manual_ok', [True, False])
def test_retry_in_backoff_runs_once_and_preserves_or_resets_deadline(cfg, identity, monkeypatch, capsys, manual_ok):
    clock = Clock(monkeypatch)
    fake, calls = Fake(), []
    original = fake.run
    def run(command):
        if command.operation == 'jobs':
            calls.append(clock.tick)
            if len(calls) < 4 or not manual_ok:
                return Result(1, stderr='synthetic ordinary failure')
            # Clicking during the claimed retry cannot enqueue another sample.
            assert requested(cfg, capsys)[1]['result'] == 'in_progress'
        return original(command)
    fake.run = run
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    def sleep(delay):
        clock.advance(delay)
        if clock.tick == 100:
            assert requested(cfg, capsys)[1]['result'] == 'queued'
            assert requested(cfg, capsys)[1]['result'] == 'already_queued'
        if clock.tick >= 110:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(cfg, 30) == 0
    assert calls == [0, 30, 60, 100]
    snapshot = json.loads((monitor.cache_dir(cfg) / 'latest.json').read_text())
    sampling = snapshot['sampling']
    assert sampling['trigger'] == 'manual' and not sampling['retry_pending']
    assert sampling['consecutive_failures'] == (0 if manual_ok else 3)
    assert sampling['current_interval_seconds'] == (30 if manual_ok else 60)
    assert sampling['next_sample_at'] == ('2026-01-01T00:02:10Z' if manual_ok else '2026-01-01T00:02:00Z')


def test_pending_request_gets_next_free_sampling_slot(multi, monkeypatch, capsys):
    clock = Clock(monkeypatch)
    for name in ('batch', 'third'):
        multi['clusters'][name] = deepcopy(multi['clusters']['default'])
    calls = []
    def build(entry, **kwargs):
        fake = Fake()
        original = fake.run
        def run(command):
            if command.operation == 'jobs':
                calls.append(entry['_cluster'])
                if len(calls) == 1:
                    assert monitor.retry(multi, 'third', json_output=True) == 0
                    assert json.loads(capsys.readouterr().out)['result'] == 'queued'
            return original(command)
        fake.run = run
        return fake
    monkeypatch.setattr(monitor, 'MonitorTransport', build)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    monkeypatch.setattr(monitor.time, 'sleep', lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert monitor.run(multi, 30) == 0
    assert calls == ['batch', 'third', 'default']


@pytest.mark.parametrize('request_during', ['default', 'third'])
def test_retry_of_sampled_entry_gets_next_free_slot(multi, monkeypatch, capsys, request_during):
    clock = Clock(monkeypatch)
    for name in ('batch', 'third'):
        multi['clusters'][name] = deepcopy(multi['clusters']['default'])
    calls = []
    def build(entry, **kwargs):
        fake = Fake()
        original = fake.run
        def run(command):
            if command.operation == 'jobs':
                name = entry['_cluster']
                calls.append((name, clock.tick))
                clock.advance(7)
                if name == request_during:
                    # batch already finished this round; another entry is busy.
                    assert monitor.retry(multi, 'batch', json_output=True) == 0
                    assert json.loads(capsys.readouterr().out)['result'] == 'queued'
                clock.advance(13)
            return original(command)
        fake.run = run
        return fake
    monkeypatch.setattr(monitor, 'MonitorTransport', build)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    monkeypatch.setattr(monitor.time, 'sleep', lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert monitor.run(multi, 30) == 0
    expected = (['batch', 'default', 'batch', 'third'] if request_during == 'default'
                else ['batch', 'default', 'third', 'batch'])
    assert calls == list(zip(expected, [0, 20, 40, 60]))
    root = monitor.cache_dir(config.select_cluster(multi, 'batch'))
    history = [json.loads(line) for line in (root / 'history.jsonl').read_text().splitlines()]
    assert [row['trigger'] for row in history] == ['scheduled', 'manual']
    assert not (root / monitor.REQUEST_FILE).exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary['entries']['batch']['trigger'] == 'manual'
    assert all(row['sampled'] for row in summary['entries'].values())


@pytest.mark.skipif(sys.platform != 'darwin', reason='plutil is a macOS-only validation tool')
def test_launchagent_example_lint(tmp_path):
    source = Path(__file__).parents[2] / 'docs/ops/launchd/local.autogaussian.monitor.plist.example'
    text = source.read_text().replace('&lt;AG_EXECUTABLE&gt;', '/tmp/ag').replace('&lt;LOG_DIR&gt;', '/tmp/log')
    text = text.replace('&lt;SYSTEM_BIN_DIR&gt;', '/usr/bin').replace('&lt;SYSTEM_SBIN_DIR&gt;', '/bin')
    target = tmp_path / 'monitor.plist'
    target.write_text(text)
    result = subprocess.run(['plutil', '-lint', str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# Frozen frontend v4.5.0 validator (6267b08), copied for additive compatibility.
def validate_monitor(data):
    def require(condition):
        if not condition:
            raise ValueError('快照格式不正确')

    def string(value, nullable=False):
        require(isinstance(value, str) or nullable and value is None)

    def integer(value, nullable=False):
        require(type(value) is int and value >= 0 or nullable and value is None)

    def timestamp(value, nullable=False):
        if nullable and value is None:
            return
        string(value)
        require('T' in value)
        require(datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() == timedelta(0))

    def rows(value):
        require(isinstance(value, list))
        for row in value:
            require(isinstance(row, dict))
        return value

    def number(value, nullable=False):
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0
                or nullable and value is None)

    def job_fields(job, new=False):
        for key in ('job_id', 'name', 'state', 'queue'):
            string(job[key])
        integer(job['cores'], True)
        for key in ('mem', 'walltime_used', 'walltime_limit', 'study', 'attempt'):
            string(job.get(key), True)
        if new or 'user' in job:
            string(job['user'])
        if new or 'mine' in job:
            require(type(job['mine']) is bool)
        if new or 'cores_kind' in job:
            require(job['cores_kind'] in ('allocated', 'requested'))
        if 'mem_source' in job:
            require(job['mem_source'] in ('scheduler', 'manifest', None))
        if 'mem_gb' in job:
            number(job['mem_gb'], True)
        for key in ('elapsed_seconds', 'walltime_limit_seconds'):
            if key in job:
                integer(job[key], True)
        if 'elapsed_source' in job:
            require(job['elapsed_source'] in ('start_time', 'walltime_used', None))
        for key in ('qtime', 'start_time'):
            if key in job:
                # Legacy own.jobs start_time was an unparsed scheduler string.
                if key == 'start_time' and not new and 'cores_kind' not in job:
                    string(job[key], True)
                else:
                    timestamp(job[key], True)

    try:
        require(isinstance(data, dict) and data['schema'] == 'ag-monitor/1')
        timestamp(data['sampled_at'])
        interval = data['interval_seconds']
        require(interval is None or type(interval) is int and 30 <= interval <= 600)
        require(type(data['ok']) is bool)
        string(data['error'], True)
        timestamp(data['last_ok_at'], True)
        if 'sample_duration_ms' in data:
            integer(data['sample_duration_ms'], True)
        own, cluster = data['own'], data['cluster']
        require(isinstance(own, dict) or not data['ok'] and own is None)
        require(isinstance(cluster, dict) or not data['ok'] and cluster is None)
        if own is not None:
            integer(own['cores_in_use'])
            for key in ('cores_running', 'cores_queued', 'committed_cap'):
                if key in own:
                    integer(own[key])
            require(type(own['core_cap']) is int and own['core_cap'] > 0)
            for key in ('max_queued_cores', 'scheduler_max_running_cores', 'max_cores'):
                if key in own:
                    integer(own[key])
                    if key != 'max_queued_cores':
                        require(own[key] > 0)
            if 'tiers' in own:
                require(isinstance(own['tiers'], dict))
                for name, tier in own['tiers'].items():
                    string(name)
                    require(isinstance(tier, dict))
                    integer(tier['cores'])
                    require(tier['cores'] > 0)
                    memory = tier['mem_gb']
                    require(type(memory) in (int, float) and math.isfinite(memory) and memory > 0)
            if 'shared_with' in own:
                require(isinstance(own['shared_with'], list))
                for name in own['shared_with']:
                    string(name)
            for key in ('mem_running_gb', 'mem_queued_gb'):
                if key in own:
                    number(own[key], True)
            for job in rows(own['jobs']):
                job_fields(job)
        if cluster is not None:
            if 'display_name' in cluster:
                name = cluster['display_name']
                string(name)
                require(1 <= len(name) <= 32 and name.isprintable())
            for key in ('name', 'scheduler', 'expires', 'expiry_warning'):
                if key in cluster:
                    string(cluster[key], True)
            if 'display_order' in cluster:
                require(cluster['display_order'] is None or type(cluster['display_order']) is int)
            for key in ('storage_checked_at', 'storage_sampled_at'):
                if key in cluster:
                    timestamp(cluster[key], True)
            if 'storage_error' in cluster:
                string(cluster['storage_error'], True)
            if 'job_summary_error' in cluster:
                string(cluster['job_summary_error'], True)
            if 'jobs_omitted' in cluster:
                integer(cluster['jobs_omitted'], True)
            if 'jobs' in cluster:
                for job in rows(cluster['jobs']):
                    job_fields(job, new=True)
            summary = cluster.get('job_summary')
            if summary is not None:
                require(isinstance(summary, dict))
                for key in ('running_jobs', 'running_cores', 'queued_jobs', 'queued_cores',
                            'others_running_jobs', 'others_running_cores',
                            'others_queued_jobs', 'others_queued_cores'):
                    if key in summary:
                        integer(summary[key], True)
            hardware = cluster.get('hardware')
            if hardware is not None:
                require(isinstance(hardware, dict))
                for key in ('cores_total', 'cores_allocated', 'cores_idle', 'cores_other'):
                    if key in hardware:
                        integer(hardware[key], True)
                for key in ('mem_total_gb', 'mem_allocated_gb'):
                    if key in hardware:
                        number(hardware[key], True)
                if 'source' in hardware:
                    require(hardware['source'] in ('pbsnodes', 'sinfo'))
                if 'error' in hardware:
                    string(hardware['error'], True)
            if 'storage_kib' in cluster:
                integer(cluster['storage_kib'], True)
            if 'hardware_capacity_known' in cluster:
                require(type(cluster['hardware_capacity_known']) is bool)
            budget = cluster.get('budget')
            if budget is not None:
                require(isinstance(budget, dict))
                for key in ('core_hours', 'used', 'reserved'):
                    value = budget[key]
                    require(type(value) in (int, float) and math.isfinite(value) and value >= 0)
            integer(cluster['cores_total'], True)
            integer(cluster['cores_used'], True)
            for node in rows(cluster['nodes']):
                string(node['name']); string(node['state'])
                integer(node['cores_total'], True); integer(node['cores_used'], True)
                for key in ('mem_total_gb', 'mem_assigned_gb'):
                    if key in node:
                        number(node[key], True)
                if 'jobs' in node:
                    integer(node['jobs'], True)
            for queue in rows(cluster['queues']):
                string(queue['name']); integer(queue['running']); integer(queue['queued'])
        for warning in rows(data['warnings']):
            string(warning['kind']); string(warning['detail'])
            for key in ('job_id', 'study', 'attempt'):
                string(warning[key], True)
        return data
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('快照格式不正确') from None


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
def test_v450_frontend_accepts_new_snapshots(cfg, identity, multi, scheduler):
    if scheduler == 'pbs':
        entry, fake = cfg, Fake()
    else:
        entry = config.select_cluster(multi, 'batch')
        fake = PartitionFake(entry)
    snapshot = monitor.sample(entry, fake, 60, schedule=monitor.Sampling(60))
    assert validate_monitor(snapshot) is snapshot
    assert 'sampling' in snapshot and 'notes' in snapshot['cluster']['hardware']
