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


def test_retry_lifecycle_and_request_merging(cfg, identity, capsys, monkeypatch):
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
        snapshot = monitor.sample(cfg, Fake(), 60, schedule=schedule, trigger='manual')
        control.finish('default', schedule, snapshot)
        assert control.begin('default', cfg, schedule) is None
    code, value = requested(cfg, capsys)
    assert code == 1 and value['reason'] == 'monitor_not_running'
    assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
    assert not any(p.is_dir() for p in monitor.control_root(cfg).iterdir())


@pytest.mark.parametrize('category', ['auth', 'host_key'])
def test_paused_retry_requires_confirmation_and_only_attempts_once(cfg, identity, capsys, monkeypatch, category):
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
        fake = Fake()
        fake.replies['jobs'] = Result(255, stderr=('Permission denied (publickey).'
            if category == 'auth' else 'Host key verification failed.'))
        snapshot = monitor.sample(cfg, fake, 60, schedule=schedule, trigger='manual_auth_fixed')
        control.finish('default', schedule, snapshot)
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
    monkeypatch.setattr(monitor, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
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


@pytest.mark.parametrize('name,host,other_nodes,other_host,expected', [
    ('node-a', 'node-a.example', '', '', 12.0),
    ('node-a.example', 'node-a', '', '', 12.0),
    ('node-a.example', 'node-a.example', torque('node-a.other'), '', 12.0),
    ('node-a', 'node-a.example', torque('node-a.other'), '', None),
    ('node-a', 'node-a.example', torque('node-a.example'), '', None),
    ('node-a.example', 'node-a', torque('node-a.other'), '', None),
    ('node-a', 'node-a.example', '', 'node-a.other', None),
    ('node-a.example', 'node-a', '', 'node-a.other', None),
    ('node-a', 'node-a.example/0-1+node-b.example', '', '', None),
])
def test_torque_memory_name_equivalence_is_unique_and_local(name, host, other_nodes, other_host, expected):
    raw = torque(name, '0-3/901.fixture') + other_nodes
    jobs = status.parse_jobs(job('901.fixture', extra=f'    exec_host = {host}/0-3\n'))
    if other_host:
        jobs += status.parse_jobs(job('902.fixture', extra=f'    exec_host = {other_host}/0-3\n'))
    before = deepcopy(jobs)
    notes = []
    values = pbs.parse_nodes(raw, jobs, notes=notes)
    assert values[0]['mem_assigned_gb'] == expected
    assert (values[0]['name'], values[0]['cores_used'], values[0]['jobs']) == (name, 4, 1)
    assert jobs == before  # No alias reaches another parser or admission caller.
    assert bool(notes) == (expected is None)
    assert all('node-' not in n and '901' not in n and '902' not in n for n in notes)


@pytest.mark.parametrize('problem', ['missing_job', 'id_mismatch', 'missing_mem', 'invalid_mem'])
def test_memory_alias_keeps_exact_job_and_request_requirements(problem):
    jobs = status.parse_jobs(job('901.fixture', extra='    exec_host = node-a.example/0-3\n'))
    if problem == 'missing_job':
        jobs = []
    elif problem == 'id_mismatch':
        jobs[0]['job_id'] = '901.other'
    elif problem == 'missing_mem':
        jobs[0].pop('Resource_List.mem')
    else:
        jobs[0]['Resource_List.mem'] = 'unknown'
    notes = []
    assert pbs.parse_nodes(torque(assignments='0-3/901.fixture'), jobs, notes=notes)[0]['mem_assigned_gb'] is None
    assert notes


def test_completed_exec_host_still_reveals_name_ambiguity_without_allocation():
    jobs = status.parse_jobs(job('901.fixture', extra='    exec_host = node-a.example/0-3\n') +
                            job('902.fixture', state='C', extra='    exec_host = node-a.other/0-3\n'))
    notes = []
    values = pbs.parse_nodes(torque(assignments='0-3/901.fixture'), jobs, notes=notes)
    assert values[0]['cores_used'] == 4 and values[0]['jobs'] == 1
    assert values[0]['mem_assigned_gb'] is None
    assert len(notes) == 1 and '歧义' in notes[0]


@pytest.mark.parametrize('assigned,expected', [('7gb', 7.0), ('invalid', None)])
def test_explicit_pbs_pro_memory_wins_over_ambiguous_alias(assigned, expected):
    jobs = status.parse_jobs(job('901.fixture', extra='    exec_host = node-a.example/0-3\n'))
    raw = torque(assignments='0-3/901.fixture', extra=f'    resources_assigned.mem = {assigned}\n')
    raw += torque('node-a.other')
    notes = []
    assert pbs.parse_nodes(raw, jobs, notes=notes)[0]['mem_assigned_gb'] == expected
    assert notes == []


@pytest.mark.parametrize('second', [torque(), torque(extra='    jobs = 0/999.fixture\n'),
                                   torque().replace('np = 64', 'np = 32')])
def test_duplicate_node_sample_keeps_jobs_queue_and_frontend_shape(cfg, identity, second):
    # load_config uses only this test's temporary files; no default config or SSH.
    entry = config.select_cluster(config.load_config(write_config(cfg)), 'default')
    raw_job = job('901.fixture', extra='    exec_host = node-a/0-3\n')
    good = monitor.sample(entry, Fake(jobs=raw_job, nodes=torque()), 60)
    root = monitor.cache_dir(entry)
    history_before = (root / 'history.jsonl').read_bytes()
    fake = Fake(jobs=raw_job, nodes=torque() + second)
    result = monitor.sample(entry, fake, 60, schedule=monitor.Sampling(60))
    assert result['ok'] and result['error'] is None
    assert result['own'] == good['own']
    assert result['cluster']['queues'] == good['cluster']['queues']
    assert result['cluster']['nodes'] == []
    assert result['cluster']['cores_total'] is None and result['cluster']['cores_used'] is None
    hardware = result['cluster']['hardware']
    assert all(hardware[k] is None for k in ('cores_total', 'cores_allocated', 'cores_idle',
                                            'cores_other', 'mem_total_gb', 'mem_allocated_gb'))
    assert 'duplicate' in hardware['error'] and 'node-a' not in hardware['error']
    assert result['sampling']['state'] == 'normal' and result['sampling']['consecutive_failures'] == 0
    assert len(fake.calls) == 3
    assert validate_monitor(result) is result
    assert json.loads((root / 'latest.json').read_text()) == result
    assert (root / 'history.jsonl').read_bytes().startswith(history_before)


def test_time_and_memory_fixes_survive_sample_publish(cfg, identity, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(monitor, 'datetime', FixedDatetime)
    cfg['scheduler_timezone'] = 'Asia/Shanghai'
    raw = job('901.fixture', extra='    exec_host = node-a.example/0-3\n'
              '    qtime = Thu Jan  1 08:00:00 2026\n').replace(
        'start_time = synthetic-time', 'start_time = Thu Jan  1 08:50:00 2026')
    fake = Fake(jobs=raw, nodes=torque(assignments='0-3/901.fixture'))
    good = monitor.sample(cfg, fake, 60)
    root = monitor.cache_dir(cfg)
    history_before = (root / 'history.jsonl').read_bytes()
    fake.replies['jobs'] = Result(stdout=raw + job('902.fixture', owner='other',
                                  extra='    start_time_epoch = 1767232800\n'))
    result = monitor.sample(cfg, fake, 60)
    assert result['ok'] and len(fake.calls) == 6
    assert result['own']['jobs'][0]['start_time'] is None
    assert result['own']['jobs'][0]['qtime'] is None
    assert result['own']['jobs'][0]['elapsed_seconds'] == 600
    assert result['own']['jobs'][0]['elapsed_source'] == 'walltime_used'
    assert result['cluster']['hardware']['mem_allocated_gb'] == 12
    assert result['own']['jobs'][0] == result['cluster']['jobs'][0]
    assert validate_monitor(result) is result
    published = (root / 'latest.json').read_text()
    assert json.loads(published) == result
    assert 'configured_timezone' not in published and 'Thu Jan' not in published
    assert (root / 'history.jsonl').read_bytes().startswith(history_before)
    assert good['own']['jobs'][0]['start_time'] == '2026-01-01T00:50:00Z'
    assert good['own']['jobs'][0]['qtime'] == '2026-01-01T00:00:00Z'


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
    monkeypatch.setattr(monitor, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
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
    monkeypatch.setattr(monitor, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
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


# T149: actual local IPC and publication, with synthetic clocks/config/transports.
def tracked_status(cfg):
    return monitor.retry_status(monitor.cache_dir(cfg), cfg.get('_cluster', 'default'))


def complete_sample(control, cfg, schedule, fake, trigger):
    snapshot = monitor.sample(cfg, fake, 60, schedule=schedule, trigger=trigger)
    control.finish(cfg.get('_cluster', 'default'), schedule, snapshot)
    return snapshot


@pytest.mark.parametrize('args', [
    ['--track'], ['--track', '--json'], ['--track', '--retry', 'default'],
    ['--track', '--watch', '30', '--json'],
])
def test_track_combinations_fail_before_config_or_io(monkeypatch, args):
    monkeypatch.setattr(cli, 'load_config', lambda: pytest.fail('Invalid combination read configuration'))
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: pytest.fail('Invalid combination used SSH'))
    assert cli.main(['monitor', *args]) == 1


@pytest.mark.parametrize('track', [False, True])
def test_cli_tracking_shape_and_refusal(cfg, monkeypatch, capsys, track):
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: pytest.fail('Retry used SSH'))
    args = ['monitor', '--retry', 'default', '--json'] + (['--track'] if track else [])
    keys = {'entry', 'result', 'reason', 'requested_at'} | ({'request_id'} if track else set())
    assert cli.main(args) == 1
    value = json.loads(capsys.readouterr().out)
    assert set(value) == keys and value['reason'] == 'monitor_not_running'
    if track:
        assert value['request_id'] is None
    with monitor.WatchControl(cfg):
        assert cli.main(args) == 0
        first = json.loads(capsys.readouterr().out)
        assert set(first) == keys and first['result'] == 'queued'
        assert cli.main(args) == 0
        second = json.loads(capsys.readouterr().out)
        assert second['result'] == 'already_queued'
        if track:
            assert first['request_id'] == second['request_id'] == tracked_status(cfg)['request_id']


@pytest.mark.parametrize('scheduled,ok', [(False, True), (False, False), (True, True), (True, False)])
def test_tracking_merges_real_sample_and_preserves_terminal(cfg, identity, capsys, monkeypatch, scheduled, ok):
    clock = Clock(monkeypatch)
    schedule, fake = monitor.Sampling(60), Fake()
    if not ok:
        fake.replies['jobs'] = Result(1, stderr='synthetic ordinary failure')
    with monitor.WatchControl(cfg) as control:
        if not scheduled:
            first = requested(cfg, capsys, track=True)[1]
            assert tracked_status(cfg)['state'] == 'queued'
            # An untracked call merges into the same request and preserves its ID.
            assert requested(cfg, capsys)[1]['result'] == 'already_queued'
        trigger = control.begin('default', cfg, schedule)
        assert trigger == ('scheduled' if scheduled else 'manual')
        if scheduled:
            assert tracked_status(cfg) is None  # no request yet
            first = requested(cfg, capsys, track=True)[1]
        for _ in range(3):
            value = requested(cfg, capsys, track=True)[1]
            assert value['result'] == 'in_progress' and value['request_id'] == first['request_id']
        assert tracked_status(cfg)['state'] == 'running'
        snapshot = complete_sample(control, cfg, schedule, fake, trigger)
        terminal = tracked_status(cfg)
        assert terminal == dict(version=1, entry='default', request_id=first['request_id'],
            requested_at=first['requested_at'], state='finished', reason=None,
            finished_at=monitor.iso_at(clock.now), sampled_at=snapshot['sampled_at'], ok=ok)
        assert len(fake.calls) == (3 if ok else 1)
        # A later scheduled round cannot replace the tracked result.
        clock.advance(60)
        assert control.begin('default', cfg, schedule) == 'scheduled'
        complete_sample(control, cfg, schedule, fake, 'scheduled')
        assert tracked_status(cfg) == terminal
        second = requested(cfg, capsys, track=True)[1]
        assert second['result'] == 'queued' and second['request_id'] != first['request_id']


def test_two_finished_requests_in_same_second_are_distinct(cfg, identity, capsys, monkeypatch):
    Clock(monkeypatch)
    schedule, ids, times = monitor.Sampling(60), [], []
    with monitor.WatchControl(cfg) as control:
        for _ in range(2):
            value = requested(cfg, capsys, track=True)[1]
            ids.append(value['request_id'])
            times.append(value['requested_at'])
            assert control.begin('default', cfg, schedule) == 'manual'
            complete_sample(control, cfg, schedule, Fake(), 'manual')
            assert tracked_status(cfg)['request_id'] == ids[-1]
    assert ids[0] != ids[1] and times[0] == times[1]


@pytest.mark.parametrize('category', ['auth', 'host_key'])
@pytest.mark.parametrize('confirmed', [False, True])
def test_queued_then_paused_has_reason_without_authorization_upgrade(cfg, capsys, monkeypatch, category, confirmed):
    clock = Clock(monkeypatch)
    schedule = monitor.Sampling(60)
    with monitor.WatchControl(cfg) as control:
        first = requested(cfg, capsys, track=True, auth_fixed=confirmed)[1]
        # A subsequent confirmation merges, but cannot elevate an earlier request.
        assert requested(cfg, capsys, track=True, auth_fixed=True)[1]['request_id'] == first['request_id']
        schedule.record(False, category, 'scheduled', clock.tick, clock.now)
        trigger = control.begin('default', cfg, schedule)
        value = tracked_status(cfg)
        assert trigger == ('manual_auth_fixed' if confirmed else None)
        assert value['state'] == ('running' if confirmed else 'discarded')
        assert value['reason'] == (None if confirmed else 'auth_confirmation_required')
        assert value['sampled_at'] is None and value['ok'] is None
        assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
        assert not (monitor.cache_dir(cfg) / 'latest.json').exists()
        assert not (monitor.cache_dir(cfg) / 'history.jsonl').exists()


@pytest.mark.parametrize('state', ['queued', 'running'])
@pytest.mark.parametrize('named', [False, True])
def test_restart_discards_tracked_state_without_replay(cfg, identity, capsys, monkeypatch, state, named):
    Clock(monkeypatch)
    if named:
        cfg = config.select_cluster(cfg)
    name, schedule = 'default', monitor.Sampling(60)
    with monitor.WatchControl(cfg) as control:
        first = requested(cfg, capsys, track=True)[1]
        if state == 'running':
            assert control.begin(name, cfg, schedule) == 'manual'
    fake = Fake()
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    monkeypatch.setattr(monitor.time, 'sleep', lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert monitor.run(cfg, 60) == 0
    value = tracked_status(cfg)
    assert value['request_id'] == first['request_id']
    assert (value['state'], value['reason'], value['sampled_at'], value['ok']) == (
        'discarded', 'monitor_restarted', None, None)
    assert value['finished_at'] is not None
    assert len(fake.calls) == 3  # T127 startup scheduled sample only; no replay
    assert json.loads((monitor.cache_dir(cfg) / 'latest.json').read_text())['sampling']['trigger'] == 'scheduled'


def test_restart_covers_removed_entry_from_previous_watch(multi, capsys, monkeypatch):
    Clock(monkeypatch)
    old = config.select_cluster(multi, 'batch')
    with monitor.WatchControl(multi):
        assert monitor.retry(multi, 'batch', track=True, json_output=True) == 0
    first = json.loads(capsys.readouterr().out)
    del multi['clusters']['batch']
    with monitor.WatchControl(multi):
        value = tracked_status(old)
        assert value['request_id'] == first['request_id'] and value['reason'] == 'monitor_restarted'
        assert not (monitor.cache_dir(old) / monitor.REQUEST_FILE).exists()


@pytest.mark.parametrize('change', ['removed', 'connection', 'interval', 'peer_cap'])
def test_reload_discard_precedes_rebuild_and_preserves_real_history(multi, monkeypatch, capsys, change):
    clock = Clock(monkeypatch)
    multi['clusters']['batch'] = deepcopy(multi['clusters']['default'])
    multi['clusters']['default']['monitor_interval_seconds'] = 600
    multi['clusters']['batch']['monitor_interval_seconds'] = 600
    loaded = config.load_config(write_config(multi))
    old = config.select_cluster(loaded, 'default')
    calls, accepted = [], []
    def build(entry, **kwargs):
        calls.append(entry['_cluster'])
        if len(calls) > 2 and entry['_cluster'] == 'default':
            assert tracked_status(old)['reason'] == 'config_changed'
        return Fake()
    monkeypatch.setattr(monitor, 'MonitorTransport', build)
    monkeypatch.setattr(monitor, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    def sleep(seconds):
        clock.advance(seconds)
        if accepted:
            raise KeyboardInterrupt
        accepted.append(requested(loaded, capsys, track=True)[1])
        if change == 'removed':
            del multi['clusters']['default']
        elif change == 'connection':
            multi['clusters']['default']['ssh']['host'] = 'changed-fixture'
        elif change == 'interval':
            multi['clusters']['default']['monitor_interval_seconds'] = 300
        else:
            multi['clusters']['batch']['resources']['max_committed_cores'] = 80
        write_config(multi)
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(loaded, 60) == 0
    value = tracked_status(old)
    assert value['request_id'] == accepted[0]['request_id']
    history = [json.loads(row) for row in (monitor.cache_dir(old) / 'history.jsonl').read_text().splitlines()]
    if change == 'peer_cap':
        assert value['state'] == 'finished'
        assert [row['trigger'] for row in history] == ['scheduled', 'manual']
        assert calls.count('default') == 1
    else:
        assert value['state'] == 'discarded'
        assert value['reason'] == ('entry_removed' if change == 'removed' else 'config_changed')
        assert value['sampled_at'] is None and value['ok'] is None
        assert [row['trigger'] for row in history] == ['scheduled'] * (1 if change == 'removed' else 2)
    assert not (monitor.cache_dir(old) / monitor.REQUEST_FILE).exists()
    lines = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    if change == 'removed':
        assert lines[-1]['discarded_retry_requests'] == ['default']
        assert all(not row['sampled'] for row in lines[-1]['entries'].values())


@pytest.mark.parametrize('stage', ['queued', 'running', 'discarded', 'finished'])
def test_status_publish_failure_never_acknowledges_or_reexecutes(cfg, identity, capsys, monkeypatch, stage):
    clock = Clock(monkeypatch)
    schedule, fake = monitor.Sampling(60), Fake()
    original = monitor.write_control
    def fail(root, value, filename=monitor.WATCH_FILE):
        if filename == monitor.STATUS_FILE and value['state'] == stage:
            raise OSError('synthetic status write failure')
        return original(root, value, filename)
    with monitor.WatchControl(cfg) as control:
        if stage == 'queued':
            monkeypatch.setattr(monitor, 'write_control', fail)
            with pytest.raises(OSError, match='synthetic'):
                requested(cfg, capsys, track=True)
            assert capsys.readouterr().out == ''
            assert tracked_status(cfg) is None
            assert (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
            with pytest.raises(ValueError, match='Inconsistent'):
                control.begin('default', cfg, schedule)
        else:
            requested(cfg, capsys, track=True)
            monkeypatch.setattr(monitor, 'write_control', fail)
            if stage == 'discarded':
                schedule.record(False, 'auth', 'scheduled', clock.tick, clock.now)
            if stage in ('running', 'discarded'):
                with pytest.raises(OSError, match='synthetic'):
                    control.begin('default', cfg, schedule)
                assert tracked_status(cfg)['state'] == 'queued'
                assert (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
            else:
                assert control.begin('default', cfg, schedule) == 'manual'
                snapshot = monitor.sample(cfg, fake, 60, schedule=schedule, trigger='manual')
                with pytest.raises(OSError, match='synthetic'):
                    control.finish('default', schedule, snapshot)
                assert tracked_status(cfg)['state'] == 'running'
                assert control.begin('default', cfg, schedule) is None
        assert len(fake.calls) == (3 if stage == 'finished' else 0)


@pytest.mark.parametrize('discard', [False, True])
def test_request_unlink_failure_preserves_claim_and_cannot_execute_twice(cfg, capsys, monkeypatch, discard):
    clock = Clock(monkeypatch)
    schedule = monitor.Sampling(60)
    original = Path.unlink
    def fail(path, *a, **k):
        if path.name == monitor.REQUEST_FILE:
            raise OSError('synthetic unlink failure')
        return original(path, *a, **k)
    with monitor.WatchControl(cfg) as control:
        requested(cfg, capsys, track=True)
        if discard:
            schedule.record(False, 'auth', 'scheduled', clock.tick, clock.now)
        monkeypatch.setattr(Path, 'unlink', fail)
        with pytest.raises(OSError, match='synthetic'):
            control.begin('default', cfg, schedule)
        assert tracked_status(cfg)['state'] == ('discarded' if discard else 'running')
        assert (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
        with pytest.raises(ValueError, match='Inconsistent'):
            control.begin('default', cfg, schedule)
        assert not (monitor.cache_dir(cfg) / 'latest.json').exists()


@pytest.mark.parametrize('failure', ['sample', 'latest', 'history'])
def test_run_failure_leaves_running_status_without_second_sample(cfg, identity, capsys, monkeypatch, failure):
    Clock(monkeypatch)
    calls = []
    fake = Fake()
    original_run = fake.run
    def run(command):
        if command.operation == 'jobs':
            calls.append(command.operation)
            assert requested(cfg, capsys, track=True)[1]['result'] == 'in_progress'
            if failure == 'sample':
                raise RuntimeError('synthetic process failure')
        return original_run(command)
    fake.run = run
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    if failure == 'latest':
        original = monitor.os.replace
        def replace(source, target):
            if Path(target).name == 'latest.json':
                raise OSError('synthetic latest failure')
            return original(source, target)
        monkeypatch.setattr(monitor.os, 'replace', replace)
    elif failure == 'history':
        original = Path.open
        def opened(path, *a, **k):
            if path.name == 'history.jsonl':
                raise OSError('synthetic history failure')
            return original(path, *a, **k)
        monkeypatch.setattr(Path, 'open', opened)
    with pytest.raises((RuntimeError, OSError), match='synthetic'):
        monitor.run(cfg, 60)
    assert calls == ['jobs'] and tracked_status(cfg)['state'] == 'running'
    assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()


@pytest.mark.parametrize('damage', [
    {'version': True}, {'version': 2}, {'state': 'unknown'}, {'entry': 'other'},
    {'request_id': 'A' * 32}, {'requested_at': '2026-01-01'}, {'ok': False},
    {'reason': 'config_changed'}, {'finished_at': '2026-01-01T00:00:00Z'},
])
def test_invalid_status_cannot_be_merged_or_claimed(cfg, capsys, monkeypatch, damage):
    Clock(monkeypatch)
    with monitor.WatchControl(cfg) as control:
        requested(cfg, capsys, track=True)
        root = monitor.cache_dir(cfg)
        value = dict(tracked_status(cfg), **damage)
        (root / monitor.STATUS_FILE).write_text(json.dumps(value))
        before = (root / monitor.REQUEST_FILE).read_bytes()
        with pytest.raises(ValueError, match='Invalid monitor retry status'):
            requested(cfg, capsys, track=True)
        with pytest.raises(ValueError, match='Invalid monitor retry status'):
            control.begin('default', cfg, monitor.Sampling(60))
        assert (root / monitor.REQUEST_FILE).read_bytes() == before


@pytest.mark.parametrize('mode', ['symlink', 'oversize', 'invalid-json'])
def test_status_read_failure_keeps_snapshot_and_request(cfg, identity, capsys, monkeypatch, mode):
    Clock(monkeypatch)
    monitor.sample(cfg, Fake())
    with monitor.WatchControl(cfg):
        requested(cfg, capsys, track=True)
        root = monitor.cache_dir(cfg)
        original = {name: (root / name).read_bytes() for name in ('latest.json', 'history.jsonl', monitor.REQUEST_FILE)}
        path = root / monitor.STATUS_FILE
        path.unlink()
        if mode == 'symlink':
            path.symlink_to(root / 'latest.json')
        else:
            path.write_bytes(b' ' * (monitor.CONTROL_BYTES + 1) if mode == 'oversize' else b'{')
        with pytest.raises(ValueError):
            requested(cfg, capsys, track=True)
        assert original == {name: (root / name).read_bytes() for name in original}


def test_source_marker_follows_actual_layout_and_mismatch_refuses(cfg, capsys, monkeypatch):
    Clock(monkeypatch)
    with monitor.WatchControl(cfg):
        value = monitor.read_control(monitor.control_root(cfg) / monitor.WATCH_FILE)
        assert value['retry_tracking_version'] == 1 and value['entries']['default']['source'] == 'legacy'
        assert requested(config.select_cluster(cfg), capsys, track=True)[1]['reason'] == 'monitor_not_running'
        assert not (monitor.control_root(cfg) / 'default').exists()
    selected = config.select_cluster(cfg)
    with monitor.WatchControl(selected):
        value = monitor.read_control(monitor.control_root(cfg) / monitor.WATCH_FILE)
        assert value['entries']['default']['source'] == 'named'
        assert requested(cfg, capsys, track=True)[1]['reason'] == 'monitor_not_running'


def test_concurrent_clients_share_one_id(cfg, monkeypatch, capsys):
    from concurrent.futures import ThreadPoolExecutor
    Clock(monkeypatch)
    with monitor.WatchControl(cfg):
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert list(pool.map(lambda _: monitor.retry(cfg, 'default', track=True, json_output=True), range(6))) == [0] * 6
        values = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
        assert len({value['request_id'] for value in values}) == 1
        assert [value['result'] for value in values].count('queued') == 1
        assert [value['result'] for value in values].count('already_queued') == 5


@pytest.mark.parametrize('track', [False, True])
def test_cli_request_through_real_watch_loop(cfg, identity, capsys, monkeypatch, track):
    clock = Clock(monkeypatch)
    fake, accepted = Fake(), []
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    def sleep(seconds):
        clock.advance(seconds)
        if accepted:
            raise KeyboardInterrupt
        args = ['monitor', '--retry', 'default', '--json'] + (['--track'] if track else [])
        assert cli.main(args) == 0
        accepted.append(json.loads(capsys.readouterr().out.splitlines()[-1]))
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert cli.main(['monitor', '--watch', '60']) == 0
    assert len(fake.calls) == 6
    value = tracked_status(cfg)
    assert value['state'] == 'finished' and value['ok'] is True
    assert value['requested_at'] == accepted[0]['requested_at']
    if track:
        assert value['request_id'] == accepted[0]['request_id']
    else:
        assert set(accepted[0]) == {'entry', 'result', 'reason', 'requested_at'}
    history = [json.loads(row) for row in (monitor.cache_dir(cfg) / 'history.jsonl').read_text().splitlines()]
    assert [row['trigger'] for row in history] == ['scheduled', 'manual']


@pytest.mark.parametrize('legacy', ['null', '[]', '3', '"legacy"', '{}', '{'])
def test_startup_cleanup_untracked_records_has_no_invented_id(cfg, capsys, monkeypatch, legacy):
    Clock(monkeypatch)
    path = monitor.cache_dir(cfg) / monitor.REQUEST_FILE
    path.write_text(legacy)
    with monitor.WatchControl(cfg) as control:
        assert control.discarded == ['default']
        assert not path.exists() and tracked_status(cfg) is None


def test_unknown_extra_status_fields_are_ignored_not_republished(cfg, identity, capsys, monkeypatch):
    Clock(monkeypatch)
    schedule = monitor.Sampling(60)
    with monitor.WatchControl(cfg) as control:
        requested(cfg, capsys, track=True)
        root = monitor.cache_dir(cfg)
        value = dict(tracked_status(cfg), future_field='synthetic future value')
        (root / monitor.STATUS_FILE).write_text(json.dumps(value))
        assert requested(cfg, capsys, track=True)[1]['result'] == 'already_queued'
        assert control.begin('default', cfg, schedule) == 'manual'
        complete_sample(control, cfg, schedule, Fake(), 'manual')
        assert 'future_field' not in monitor.read_control(root / monitor.STATUS_FILE)


@pytest.mark.parametrize('version', [None, 2, True, '1'])
def test_track_cannot_claim_unknown_or_old_capability(cfg, capsys, monkeypatch, version):
    Clock(monkeypatch)
    with monitor.WatchControl(cfg) as control:
        watching = dict(control.value)
        if version is None:
            watching.pop('retry_tracking_version')
        else:
            watching['retry_tracking_version'] = version
        monitor.write_control(monitor.control_root(cfg), watching)
        with pytest.raises(ValueError, match='tracking is unavailable'):
            requested(cfg, capsys, track=True)
        assert not (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()
        assert tracked_status(cfg) is None


def test_old_watch_accepts_default_four_key_client(cfg, capsys, monkeypatch):
    Clock(monkeypatch)
    with monitor.WatchControl(cfg) as control:
        watching = dict(control.value)
        watching.pop('retry_tracking_version')
        monitor.write_control(monitor.control_root(cfg), watching)
        value = requested(cfg, capsys)[1]
        assert set(value) == {'entry', 'result', 'reason', 'requested_at'}
        assert value['result'] == 'queued' and tracked_status(cfg) is None
        pending = monitor.read_control(monitor.cache_dir(cfg) / monitor.REQUEST_FILE)
        assert set(pending) == {'requested_at', 'auth_fixed'}


@pytest.mark.parametrize('operation', ['replace', 'fsync'])
def test_atomic_status_failure_preserves_old_bytes(cfg, capsys, monkeypatch, operation):
    Clock(monkeypatch)
    with monitor.WatchControl(cfg) as control:
        requested(cfg, capsys, track=True)
        path = monitor.cache_dir(cfg) / monitor.STATUS_FILE
        before = path.read_bytes()
        with monkeypatch.context() as fault:
            if operation == 'replace':
                original = monitor.os.replace
                def replace(source, target):
                    if Path(target).name == monitor.STATUS_FILE:
                        raise OSError('synthetic replace failure')
                    return original(source, target)
                fault.setattr(monitor.os, 'replace', replace)
            else:
                fault.setattr(monitor.os, 'fsync', lambda _: (_ for _ in ()).throw(OSError('synthetic fsync failure')))
            with pytest.raises(OSError, match='synthetic'):
                control.begin('default', cfg, monitor.Sampling(60))
        assert path.read_bytes() == before
        assert (path.parent / monitor.REQUEST_FILE).exists()
        assert not list(path.parent.glob('.watch-*'))


def test_request_persistence_failure_has_no_queued_response(cfg, capsys, monkeypatch):
    Clock(monkeypatch)
    with monitor.WatchControl(cfg):
        with monkeypatch.context() as fault:
            fault.setattr(monitor.os, 'fsync', lambda _: (_ for _ in ()).throw(OSError('synthetic fsync failure')))
            with pytest.raises(OSError, match='synthetic'):
                requested(cfg, capsys, track=True)
        assert capsys.readouterr().out == '' and tracked_status(cfg) is None
        assert (monitor.cache_dir(cfg) / monitor.REQUEST_FILE).exists()


def test_other_entry_sample_cannot_finish_queued_request(multi, identity, capsys, monkeypatch):
    Clock(monkeypatch)
    multi['clusters']['batch'] = deepcopy(multi['clusters']['default'])
    selected = monitor.entries(multi)
    with monitor.WatchControl(multi) as control:
        assert monitor.retry(multi, 'default', track=True, json_output=True) == 0
        first = json.loads(capsys.readouterr().out)
        schedule = monitor.Sampling(60)
        assert control.begin('batch', selected['batch'], schedule) == 'scheduled'
        complete_sample(control, selected['batch'], schedule, Fake(), 'scheduled')
        assert tracked_status(selected['default'])['state'] == 'queued'
        assert tracked_status(selected['default'])['request_id'] == first['request_id']
        assert tracked_status(selected['batch']) is None


@pytest.mark.parametrize('named,change', [
    (False, 'unchanged'), (True, 'unchanged'),
    (False, 'connection'), (True, 'connection'),
    (False, 'interval'), (True, 'interval'),
    (True, 'peer_cap'), (True, 'added'), (True, 'removed'),
])
def test_retry_between_watch_publication_and_first_reload(cfg, multi, identity, capsys, monkeypatch, named, change):
    clock = Clock(monkeypatch)
    source = multi if named else cfg
    if named:
        source['clusters']['batch'] = deepcopy(source['clusters']['default'])
    file = write_config(source)
    loaded = config.load_config(file)
    original_entry = monitor.entries(loaded)['default']
    root = monitor.cache_dir(original_entry, create=False)
    accepted, transports, calls = [], {}, []
    original_read = monitor.ConfigReload.read
    preserve = change in ('unchanged', 'peer_cap', 'added')

    def first_read(cache, active):
        if not accepted:
            watching = monitor.read_control(monitor.control_root(active) / monitor.WATCH_FILE)
            assert monitor.watch_alive(watching) and watching['retry_tracking_version'] == 1
            assert watching['entries']['default']['source'] == ('named' if named else 'legacy')
            assert not transports and not (root / 'latest.json').exists()
            # The request is acknowledged after the capability marker is visible,
            # before the first real stat/load_config cycle and any sampling.
            reply = requested(active, capsys, track=True)[1]
            assert reply['result'] == 'queued'
            accepted.append(reply)
            assert tracked_status(original_entry)['state'] == 'queued'
            if change != 'unchanged':
                entry = source['clusters']['default'] if named else source
                if change == 'connection':
                    entry['ssh']['host'] = 'changed-fixture'
                elif change == 'interval':
                    if named:
                        entry['monitor_interval_seconds'] = 90
                elif change == 'peer_cap':
                    source['clusters']['batch']['resources']['max_committed_cores'] = 80
                elif change == 'added':
                    source['clusters']['added'] = deepcopy(source['clusters']['batch'])
                else:
                    del source['clusters']['default']
                write_config(source)
                if change == 'interval' and not named:
                    file.write_text('monitor_interval_seconds = 90\n' + file.read_text())
        return original_read(cache, active)

    def build(entry, **kwargs):
        name = entry.get('_cluster', 'default')
        assert name not in transports
        if name == 'default':
            # A real change must discard before constructing the new transport;
            # mere initialization must leave the acknowledged request queued.
            assert tracked_status(original_entry)['state'] == ('queued' if preserve else 'discarded')
        fake = Fake()
        original_run = fake.run
        def run(command):
            if command.operation == 'jobs':
                calls.append(name)
                if name == 'default':
                    assert tracked_status(original_entry)['state'] == ('running' if preserve else 'discarded')
            return original_run(command)
        fake.run = run
        transports[name] = fake
        return fake

    def sleep(seconds):
        clock.advance(seconds)
        if clock.tick >= 6:
            raise KeyboardInterrupt

    monkeypatch.setattr(monitor.ConfigReload, 'read', first_read)
    monkeypatch.setattr(monitor, 'MonitorTransport', build)
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(loaded, 60) == 0
    assert len(accepted) == 1
    result = tracked_status(original_entry)
    assert result['request_id'] == accepted[0]['request_id']
    assert result['requested_at'] == accepted[0]['requested_at']
    assert result['state'] == ('finished' if preserve else 'discarded')
    assert result['reason'] == (None if preserve else 'entry_removed' if change == 'removed' else 'config_changed')
    assert result['finished_at'] is not None
    assert not (root / monitor.REQUEST_FILE).exists()
    if change == 'removed':
        assert 'default' not in transports and 'default' not in calls
        assert not (root / 'history.jsonl').exists()
    else:
        assert calls.count('default') == 1 and len(transports['default'].calls) == 3
        snapshot = json.loads((root / 'latest.json').read_text())
        history = [json.loads(line) for line in (root / 'history.jsonl').read_text().splitlines()]
        assert len(history) == 1
        assert snapshot['sampling']['trigger'] == history[0]['trigger'] == ('manual' if preserve else 'scheduled')
        if preserve:
            assert result['sampled_at'] == snapshot['sampled_at'] and result['ok'] is True
    if not preserve:
        assert result['sampled_at'] is None and result['ok'] is None
