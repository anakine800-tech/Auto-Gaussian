"""Synthetic scheduler observations only; no cluster connections or study writes."""
import json
from pathlib import Path
import re
import subprocess

import pytest

from ag import cli, monitor, remote, status
from ag.transport import Result, SSHConnectionError, SSHTransport


QUEUES = '''Queue Max Tot Ena Str Que Run Hld Wat Trn Ext T
----- --- --- --- --- --- --- --- --- --- --- -
batch 0 4 yes yes 1 3 0 0 0 0 E
empty 0 0 yes yes 0 0 0 0 0 0 E
'''
NODES = '''node-a
     state = free
     np = 44
     jobs = 0/101.fixture, 1/101.fixture,
         2-3/101.fixture
     status = opsys=linux,loadave=0.00

node-b
     state = job-exclusive
     np = 16

node-c
     state = down,offline
     np = 8
'''


def job(job_id='101.fixture', owner='fixture', state='R', cores='1:ppn=8', extra=''):
    return (f'Job Id: {job_id}\n    Job_Name = water\n    Job_Owner = {owner}@fixture\n'
            f'    job_state = {state}\n    queue = batch\n    Resource_List.nodes = {cores}\n'
            '    Resource_List.mem = 12gb\n    Resource_List.walltime = 01:00:00\n'
            '    resources_used.walltime = 00:10:00\n    start_time = synthetic-time\n' + extra)


JOBS = (job(extra='    exec_host = node-a/0+node-a/1+\n        node-a/2+node-a/3\n')
        + job('102.fixture', cores='2:ppn=4', extra='    exec_host = node-b/0*4\n')
        + job('103.fixture', owner='other', extra='    exec_host = node-b/4+node-b/5\n'))


@pytest.fixture
def cfg(tmp_path):
    ssh = tmp_path / 'ssh_config'
    ssh.write_text('Host fixture\n  User fixture\n')
    root = tmp_path / 'studies'
    root.mkdir()
    return {'_config_dir': str(tmp_path), 'ssh': {'host': 'fixture', 'config_file': str(ssh)},
            'local': {'studies_root': str(root)}, 'resources': {'max_cores': 44}}


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setattr(monitor, 'ssh_identity', lambda cfg: ('fixture', 22, 'fixture'))


class Fake:
    def __init__(self, jobs=JOBS, queues=QUEUES, nodes=NODES):
        self.replies = dict(jobs=Result(stdout=jobs), queues=Result(stdout=queues), nodes=Result(stdout=nodes))
        self.calls = []

    def run(self, command):
        assert command in (remote.jobs(), remote.queues(), remote.nodes())
        self.calls.append(command.text)
        reply = self.replies[command.operation]
        if isinstance(reply, Exception):
            raise reply
        return reply


def attempt(cfg, name, job_id, state):
    path = Path(cfg['local']['studies_root']) / 'water' / 'attempts' / name / 'status.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(job_id=job_id, state=state)))
    path.with_name('manifest.json').write_text(json.dumps(dict(attempt_id=name, study_id='water')))
    return path


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_parsers_and_shared_accounting():
    jobs = status.parse_jobs(JOBS)
    assert jobs[0]['exec_host'] == 'node-a/0+node-a/1+node-a/2+node-a/3'
    assert status.occupied(jobs, 'fixture') == 16
    assert monitor.parse_nodes(NODES, jobs) == [
        dict(name='node-a', state='free', cores_total=44, cores_used=4, mem_total_gb=None, mem_assigned_gb=12.0, jobs=1,
             capacity_cpu_consistent=True, mem_total_bytes=None, mem_assigned_bytes=12 * 1024**3),
        dict(name='node-b', state='job-exclusive', cores_total=16, cores_used=6, mem_total_gb=None, mem_assigned_gb=None, jobs=None,
             capacity_cpu_consistent=True, mem_total_bytes=None, mem_assigned_bytes=None),
        dict(name='node-c', state='down,offline', cores_total=8, cores_used=0, mem_total_gb=None, mem_assigned_gb=None, jobs=None,
             capacity_cpu_consistent=True, mem_total_bytes=None, mem_assigned_bytes=None)]
    assert monitor.parse_queues(QUEUES) == [dict(name='batch', running=3, queued=1),
                                          dict(name='empty', running=0, queued=0)]
    assert monitor.parse_queues('') == []
    assert monitor.parse_queues('\n'.join(QUEUES.splitlines()[:2])) == []
    assert monitor.parse_nodes('', []) == []
    assert status.parse_jobs('') == []


@pytest.mark.parametrize('state', ['Q', 'R', 'H', 'E', 'T', 'W', 'S', 'C'])
def test_own_cores_match_submit_for_every_state(cfg, state):
    raw = job(state=state, cores='2:ppn=8+node-b:ppn=4') + job('105.fixture', owner='other')
    result = monitor.observation(cfg, Fake(jobs=raw), 'fixture')
    expected = status.occupied(status.parse_jobs(raw), 'fixture')
    assert result['own']['cores_in_use'] == expected == (0 if state == 'C' else 20)
    assert len(result['own']['jobs']) == (0 if state == 'C' else 1)
    if state != 'C':
        assert result['own']['jobs'][0]['cores'] == (None if state in ('R', 'E') else expected)


def test_snapshot_exact_association_and_no_study_mutation(cfg, identity):
    path = attempt(cfg, 'water-001-sp', '101.fixture', 'submitted')
    attempt(cfg, 'water-002-sp', '102.other', 'prepared')
    before = tree(path.parents[2])
    fake = Fake()
    result = monitor.sample(cfg, fake, 120)
    assert fake.calls == ['qstat -f', 'qstat -Q', 'pbsnodes -a']
    assert result['schema'] == 'ag-monitor/1'
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', result['sampled_at'])
    assert result['sampled_at'] == result['last_ok_at']
    assert result['ok'] is True and result['error'] is None
    assert result['interval_seconds'] == 120
    assert result['own']['jobs'][0] == dict(job_id='101.fixture', name='water', state='R', queue='batch',
        user='fixture', mine=True, cores_kind='allocated', mem_gb=12.0, mem_source='scheduler',
        elapsed_seconds=600, elapsed_source='walltime_used', walltime_limit_seconds=3600, qtime=None,
        cores=4, mem='12gb', walltime_used='00:10:00', walltime_limit='01:00:00',
        start_time=None, study='water', attempt='water-001-sp')
    assert result['own']['jobs'][1]['study'] is None
    assert result['own']['jobs'][1]['attempt'] is None
    assert result['cluster']['cores_total'] == 68
    assert result['cluster']['cores_used'] == 10
    assert result['warnings'] == []
    root = monitor.cache_dir(cfg)
    assert json.loads((root / 'latest.json').read_text()) == result
    summary = json.loads((root / 'history.jsonl').read_text())
    assert summary['ok'] and summary['cores_in_use'] == 16
    assert summary['jobs'] == 2
    assert tree(path.parents[2]) == before


@pytest.mark.parametrize('local', ['finished', 'fetched', 'cancelled', 'interrupted'])
@pytest.mark.parametrize('scheduler', ['R', 'Q', 'E'])
def test_residue_warning(cfg, local, scheduler):
    attempt(cfg, 'water-001-sp', '101.fixture', local)
    result = monitor.observation(cfg, Fake(jobs=job(state=scheduler)), 'fixture')
    assert result['warnings'] == [dict(kind='scheduler-residue', job_id='101.fixture',
        study='water', attempt='water-001-sp', detail='需人工确认后 ag cancel')]


@pytest.mark.parametrize('local', ['submitted', 'running'])
def test_absence_is_exact_id_not_numeric_prefix(cfg, local):
    attempt(cfg, 'water-001-sp', '101.other', local)
    warnings = monitor.observation(cfg, Fake(), 'fixture')['warnings']
    assert warnings == [dict(kind='absent-from-scheduler', job_id='101.other', study='water',
                             attempt='water-001-sp', detail='运行 ag status 核对')]


def test_over_cap_and_non_ag_jobs(cfg):
    result = monitor.observation(cfg, Fake(jobs=job(cores='2:ppn=24')), 'fixture')
    assert result['own']['cores_in_use'] == 48
    assert result['own']['core_cap'] == 44
    assert result['warnings'][0]['kind'] == 'over-cap'
    assert result['own']['jobs'][0]['study'] is None
    cfg['resources']['max_cores'] = 8
    assert monitor.observation(cfg, Fake(), 'fixture')['warnings'][0]['kind'] == 'over-cap'


def test_no_false_residue_or_absence(cfg):
    attempt(cfg, 'water-001-sp', '101.fixture', 'finished')
    attempt(cfg, 'water-002-sp', '102.fixture', 'running')
    attempt(cfg, 'water-003-sp', '104.fixture', 'unknown')
    assert monitor.observation(cfg, Fake(jobs=job(state='C') + job('102.fixture')), 'fixture')['warnings'] == []


@pytest.mark.parametrize('operation', ['jobs', 'queues'])
@pytest.mark.parametrize('failure', [Result(255, stderr='Connection to fixture failed'),
                                   SSHConnectionError('Remote operation timed out')])
def test_failure_preserves_last_success_without_additional_retry(cfg, identity, operation, failure):
    before = monitor.sample(cfg, Fake())
    fake = Fake(jobs=job(cores='1:ppn=44'))
    fake.replies[operation] = failure
    for _ in range(2):
        failed = monitor.sample(cfg, fake, 60)
        assert failed['ok'] is False
        assert failed['error'] and 'fixture' not in failed['error']
        assert failed['last_ok_at'] == before['last_ok_at']
        for key in ('own', 'cluster', 'warnings'):
            assert failed[key] == before[key]
    assert len(fake.calls) == 2 * (['jobs', 'queues', 'nodes'].index(operation) + 1)
    recovered = monitor.sample(cfg, Fake())
    assert recovered['ok'] and recovered['error'] is None
    assert recovered['last_ok_at'] == recovered['sampled_at']


def test_first_failure_is_not_reported_as_success(cfg, identity):
    cfg['resources']['max_committed_cores'] = 132
    fake = Fake()
    fake.replies['jobs'] = Result(255, stderr='user fixture: failed')
    result = monitor.sample(cfg, fake)
    assert result['ok'] is False and result['last_ok_at'] is None
    assert result['own']['jobs'] == []
    assert result['own']['core_cap'] == 44
    assert result['own']['committed_cap'] == 132


def test_atomic_latest_and_append_only_rotation(cfg, identity, monkeypatch):
    root = monitor.cache_dir(cfg)
    first = monitor.sample(cfg, Fake())
    previous = (root / 'latest.json').read_bytes()
    history = (root / 'history.jsonl').read_bytes()
    original = monitor.os.replace
    replacements = []
    def replace(src, dst):
        assert Path(src).parent == Path(dst).parent == root
        if Path(dst).name == 'latest.json':
            assert (root / 'latest.json').read_bytes() == previous
            assert json.loads(Path(src).read_text())['schema'] == 'ag-monitor/1'
        replacements.append(Path(dst).name)
        original(src, dst)
    monkeypatch.setattr(monitor.os, 'replace', replace)
    monitor.sample(cfg, Fake())
    assert (root / 'history.jsonl').read_bytes().startswith(history)
    assert len((root / 'history.jsonl').read_text().splitlines()) == 2
    assert replacements == ['previous.json', 'latest.json']
    assert (root / 'previous.json').read_bytes() == previous
    monkeypatch.setattr(monitor.os, 'replace', original)
    monkeypatch.setattr(monitor, 'HISTORY_BYTES', 1)
    (root / 'history.1.jsonl').write_text('old rotation\n')
    monitor.publish(root, first)
    assert len((root / 'history.1.jsonl').read_text().splitlines()) == 3
    assert (root / 'history.jsonl').read_bytes() == b''
    monitor.publish(root, first)
    assert len((root / 'history.1.jsonl').read_text().splitlines()) == 1
    assert sorted(p.name for p in root.iterdir()) == ['history.1.jsonl', 'history.jsonl', 'latest.json', 'previous.json']


def test_interrupted_replace_keeps_valid_latest(cfg, identity, monkeypatch):
    monitor.sample(cfg, Fake())
    root = monitor.cache_dir(cfg)
    before = tree(root)
    def fail(*args):
        raise OSError('synthetic write failure')
    monkeypatch.setattr(monitor.os, 'replace', fail)
    with pytest.raises(OSError):
        monitor.sample(cfg, Fake())
    assert tree(root) == before


@pytest.mark.parametrize('name', ['.ag-monitor', 'latest.json', 'previous.json', 'history.jsonl', 'history.1.jsonl'])
def test_cache_symlink_cannot_redirect_writes_into_study(cfg, name):
    target = attempt(cfg, 'water-001-sp', '101.fixture', 'submitted')
    before = target.read_bytes()
    root = Path(cfg['local']['studies_root'])
    if name == '.ag-monitor':
        (root / name).symlink_to(target.parent, target_is_directory=True)
    else:
        monitor.cache_dir(cfg).joinpath(name).symlink_to(target)
    with pytest.raises(ValueError, match='symbolic links'):
        monitor.sample(cfg, Fake())
    assert target.read_bytes() == before


def pair_snapshot(cfg, minute, *, ok=True):
    value = monitor.empty_snapshot(cfg, 300)
    value.update(sampled_at=f'2026-10-30T00:{minute:02d}:00Z', ok=ok,
                 error=None if ok else 'Synthetic sampling failure')
    value['last_ok_at'] = value['sampled_at'] if ok else None
    value['own']['jobs'] = [dict(job_id='101.fixture', name='water', mine=True)]
    return value


def test_previous_keeps_full_failed_sample_instead_of_last_success(cfg):
    root = monitor.cache_dir(cfg)
    first, failed, recovered = pair_snapshot(cfg, 0), pair_snapshot(cfg, 5, ok=False), pair_snapshot(cfg, 10)
    monitor.publish(root, first)
    monitor.publish(root, failed)
    failed_bytes = (root / 'latest.json').read_bytes()
    monitor.publish(root, recovered)
    assert (root / 'previous.json').read_bytes() == failed_bytes
    assert json.loads(failed_bytes)['own']['jobs'] == failed['own']['jobs']
    assert json.loads((root / 'previous.json').read_text())['ok'] is False
    assert [json.loads(line)['ok'] for line in (root / 'history.jsonl').read_text().splitlines()] == [True, False, True]


def test_control_tombstone_breaks_observation_pair(cfg):
    root = monitor.cache_dir(cfg)
    first = pair_snapshot(cfg, 0)
    monitor.publish(root, first)
    first_bytes = (root / 'latest.json').read_bytes()
    monitor.mark_removed(cfg)
    assert (root / 'previous.json').read_bytes() == first_bytes
    assert json.loads((root / 'latest.json').read_text())['config_removed'] is True
    assert len((root / 'history.jsonl').read_text().splitlines()) == 1
    monitor.publish(root, pair_snapshot(cfg, 5))
    assert json.loads((root / 'previous.json').read_text())['ok'] is False
    monitor.publish(root, pair_snapshot(cfg, 10))
    assert json.loads((root / 'previous.json').read_text())['sampled_at'] == '2026-10-30T00:05:00Z'


@pytest.mark.parametrize('second_minute', [0, 5])
def test_duplicate_or_backwards_time_breaks_next_pair(cfg, second_minute):
    root = monitor.cache_dir(cfg)
    monitor.publish(root, pair_snapshot(cfg, 5))
    monitor.publish(root, pair_snapshot(cfg, second_minute))
    monitor.publish(root, pair_snapshot(cfg, 10))
    assert json.loads((root / 'previous.json').read_text())['ok'] is False
    monitor.publish(root, pair_snapshot(cfg, 15))
    assert json.loads((root / 'previous.json').read_text())['sampled_at'] == '2026-10-30T00:10:00Z'


def test_orphan_previous_cannot_pair_with_first_new_sample(cfg):
    root = monitor.cache_dir(cfg)
    (root / 'previous.json').write_text(json.dumps(pair_snapshot(cfg, 0)))
    monitor.publish(root, pair_snapshot(cfg, 5))
    assert not (root / 'previous.json').exists()
    monitor.publish(root, pair_snapshot(cfg, 10))
    assert json.loads((root / 'previous.json').read_text())['sampled_at'] == '2026-10-30T00:05:00Z'


@pytest.mark.parametrize('interrupt_recovery', [False, True])
def test_interrupted_pair_rotation_requires_two_later_samples(cfg, monkeypatch, interrupt_recovery):
    root = monitor.cache_dir(cfg)
    monitor.publish(root, pair_snapshot(cfg, 0))
    monitor.publish(root, pair_snapshot(cfg, 5))
    latest = (root / 'latest.json').read_bytes()
    replace = monitor.os.replace
    def fail_latest(src, dst):
        if Path(dst).name == 'latest.json':
            raise OSError('Synthetic crash after previous publication')
        replace(src, dst)
    monkeypatch.setattr(monitor.os, 'replace', fail_latest)
    with pytest.raises(OSError, match='Synthetic crash'):
        monitor.publish(root, pair_snapshot(cfg, 10))
    assert (root / 'previous.json').read_bytes() == (root / 'latest.json').read_bytes() == latest
    assert not list(root.glob('*.tmp'))
    if interrupt_recovery:
        with pytest.raises(OSError, match='Synthetic crash'):
            monitor.publish(root, pair_snapshot(cfg, 10))
        assert json.loads((root / 'previous.json').read_text())['ok'] is False
        assert (root / 'latest.json').read_bytes() == latest
    monkeypatch.setattr(monitor.os, 'replace', replace)
    monitor.publish(root, pair_snapshot(cfg, 15))
    invalid = json.loads((root / 'previous.json').read_text())
    assert invalid['ok'] is False and invalid['sampled_at'] == '2026-10-30T00:05:00Z'
    monitor.publish(root, pair_snapshot(cfg, 20))
    assert json.loads((root / 'previous.json').read_text())['sampled_at'] == '2026-10-30T00:15:00Z'


def test_concurrent_publishers_cannot_interleave_snapshot_generations(cfg, monkeypatch):
    import threading
    root = monitor.cache_dir(cfg)
    monitor.publish(root, pair_snapshot(cfg, 0))
    previous_written, second_waiting, second_acquired, release = (threading.Event() for _ in range(4))
    replace, flock = monitor.os.replace, monitor.fcntl.flock
    def held_replace(src, dst):
        replace(src, dst)
        if threading.current_thread().name == 'first-publisher' and Path(dst).name == 'previous.json':
            previous_written.set()
            assert release.wait(5)
    def tracked_flock(fd, operation):
        if threading.current_thread().name == 'second-publisher':
            second_waiting.set()
        flock(fd, operation)
        if threading.current_thread().name == 'second-publisher':
            second_acquired.set()
    monkeypatch.setattr(monitor.os, 'replace', held_replace)
    monkeypatch.setattr(monitor.fcntl, 'flock', tracked_flock)
    errors = []
    def writer(minute):
        try:
            monitor.publish(root, pair_snapshot(cfg, minute))
        except BaseException as exc:
            errors.append(exc)
    first = threading.Thread(target=writer, args=(5,), name='first-publisher')
    second = threading.Thread(target=writer, args=(10,), name='second-publisher')
    first.start()
    assert previous_written.wait(5)
    second.start()
    try:
        assert second_waiting.wait(5)
        assert not second_acquired.is_set()
    finally:
        release.set()
        first.join(5)
        second.join(5)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert json.loads((root / 'previous.json').read_text())['sampled_at'] == '2026-10-30T00:05:00Z'
    assert json.loads((root / 'latest.json').read_text())['sampled_at'] == '2026-10-30T00:10:00Z'


@pytest.mark.parametrize('value', ['29', '601', '0', '-1', '1.5', 'bad'])
def test_watch_range_rejected_before_configuration(monkeypatch, value):
    monkeypatch.setattr(cli, 'load_config', lambda: pytest.fail('Must validate before loading config'))
    with pytest.raises(SystemExit) as exc:
        cli.main(['monitor', '--watch', value])
    assert exc.value.code == 2


@pytest.mark.parametrize('interval', [30, 60, 600])
def test_watch_foreground_and_ctrl_c(cfg, identity, monkeypatch, capsys, interval):
    fake = Fake()
    constructors, sleeps = [], []
    tick = [0.0]
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    def transport(config, *, read_only):
        assert config is cfg
        constructors.append(read_only)
        return fake
    def sleep(seconds):
        tick[0] += interval
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor, 'MonitorTransport', transport)
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    assert cli.main(['monitor', '--watch', str(interval), '--json']) == 0
    assert constructors == [True]
    assert len(fake.calls) == 6 and len(sleeps) == 2
    assert all(0 <= delay <= interval for delay in sleeps)
    assert all(json.loads(line)['interval_seconds'] == interval for line in capsys.readouterr().out.splitlines())


@pytest.mark.parametrize('failed,expected', [(False, 0), (True, 2)])
def test_one_shot_exit_code(cfg, identity, monkeypatch, capsys, failed, expected):
    fake = Fake()
    if failed:
        fake.replies['jobs'] = Result(255)
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda cfg, *, read_only: fake if read_only else pytest.fail())
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(monitor.time, 'sleep', lambda _: pytest.fail('One-shot must exit'))
    assert cli.main(['monitor', '--json']) == expected
    assert json.loads(capsys.readouterr().out)['interval_seconds'] is None


def test_sample_binds_account_from_one_local_identity_lookup(cfg, monkeypatch):
    from ag import approval
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv == ['ssh', '-G', '-F', cfg['ssh']['config_file'], 'fixture']
        assert kwargs['timeout'] == 15
        return Result(stdout='hostname FIXTURE-ACCOUNT\nport 2201\nuser fixture\n')

    monkeypatch.setattr(subprocess, 'run', run)
    fake = Fake()
    result = monitor.sample(cfg, fake, 300)
    assert result['ok']
    assert result['account_sha256'] == approval.digest(
        {'scheduler': 'pbs', 'ssh': ['fixture-account', 2201, 'fixture']})
    assert len(calls) == 1 and len(fake.calls) == 3
    assert result['own']['cores_in_use'] == 16
    assert not {'hostname', 'port', 'user', 'ssh'} & result.keys()


@pytest.mark.parametrize('changed', [
    ('fixture-b', 22, 'fixture'), ('fixture-a', 2202, 'fixture'),
    ('fixture-a', 22, 'other'),
])
def test_same_alias_account_change_is_bound_to_each_snapshot(cfg, monkeypatch, changed):
    replies = iter([('fixture-a', 22, 'fixture'), changed])

    def run(*args, **kwargs):
        host, port, user = next(replies)
        return Result(stdout=f'hostname {host}\nport {port}\nuser {user}\n')

    monkeypatch.setattr(subprocess, 'run', run)
    first = monitor.sample(cfg, Fake(jobs=''), 300)
    second = monitor.sample(cfg, Fake(jobs=''), 300)
    assert first['ok'] and second['ok']
    assert first['own']['jobs'] == second['own']['jobs'] == []
    assert first['account_sha256'] != second['account_sha256']
    root = monitor.cache_dir(cfg)
    assert json.loads((root / 'previous.json').read_text())['account_sha256'] == first['account_sha256']
    assert json.loads((root / 'latest.json').read_text())['account_sha256'] == second['account_sha256']


def test_failed_sample_never_relabels_retained_jobs_with_new_account(cfg, monkeypatch):
    replies = iter(['fixture-a', 'fixture-b'])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(
        stdout=f'hostname {next(replies)}\nport 22\nuser fixture\n'))
    first = monitor.sample(cfg, Fake(), 300)
    assert first['ok'] and first['account_sha256']
    fake = Fake()
    fake.replies['jobs'] = Result(255)
    failed = monitor.sample(cfg, fake, 300)
    assert failed['ok'] is False
    assert failed['own']['jobs'] == first['own']['jobs']
    assert 'account_sha256' not in failed


@pytest.mark.parametrize('text', [
    'user fixture\n', 'hostname fixture\nuser fixture\n',
    'hostname fixture\nport 22\nuser invalid@name\n',
])
def test_account_identity_requires_complete_expansion_before_remote_reads(cfg, monkeypatch, text):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(stdout=text))
    fake = Fake()
    result = monitor.sample(cfg, fake, 300)
    assert result['ok'] is False and 'account_sha256' not in result
    assert fake.calls == []


@pytest.mark.parametrize('reply', [Result(stdout=''), Result(stdout='user invalid name\n'),
                                 Result(1, stderr='fixture failed')])
def test_identity_failure_publishes_redacted_failure_without_remote_calls(cfg, monkeypatch, reply):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: reply)
    fake = Fake()
    result = monitor.sample(cfg, fake)
    assert not result['ok'] and 'fixture' not in result['error']
    assert fake.calls == []


def test_transport_retry_is_only_retry_and_never_records_to_studies(cfg, identity, monkeypatch):
    path = attempt(cfg, 'water-001-sp', '101.fixture', 'submitted')
    before = tree(path.parents[2])
    calls = []
    def execute(argv, timeout):
        calls.append(argv[-1])
        return Result(255, stderr='Connection to fixture failed')
    monkeypatch.setattr(SSHTransport, '_execute', lambda self, *a: execute(*a))
    monkeypatch.setattr('ag.transport.time.sleep', lambda seconds: None)
    result = monitor.sample(cfg, SSHTransport(cfg, read_only=True))
    assert not result['ok']
    assert calls == ['qstat -f', 'qstat -f']
    assert tree(path.parents[2]) == before


@pytest.mark.parametrize('operation,text', [('jobs', 'unexpected'), ('queues', 'Queue Que Run\nbatch bad 1')])
def test_malformed_output_keeps_success(cfg, identity, operation, text):
    previous = monitor.sample(cfg, Fake())
    fake = Fake()
    fake.replies[operation] = Result(stdout=text)
    result = monitor.sample(cfg, fake)
    assert not result['ok']
    assert result['last_ok_at'] == previous['last_ok_at']
    assert result['cluster'] == previous['cluster']


def test_legacy_timestamp_normalized_even_when_sampling_fails(cfg, identity):
    root = monitor.cache_dir(cfg)
    previous = monitor.sample(cfg, Fake())
    previous['last_ok_at'] = '2026-10-14T02:05:00.123456+00:00'
    (root / 'latest.json').write_text(json.dumps(previous))
    fake = Fake()
    fake.replies['jobs'] = Result(255)
    result = monitor.sample(cfg, fake)
    assert not result['ok']
    assert result['last_ok_at'] == '2026-10-14T02:05:00Z'
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', result['sampled_at'])
    history = [json.loads(line) for line in (root / 'history.jsonl').read_text().splitlines()]
    assert history[-1]['last_ok_at'] == result['last_ok_at']
    assert history[-1]['sampled_at'] == result['sampled_at']


@pytest.mark.parametrize('damage', [b'{', b'\xff', b'null', b'[]', b'42', b'{}',
                                  'own', 'cluster', 'warnings', 'last_ok_at', 'jobs'])
def test_corrupt_snapshot_records_one_failure_then_watch_recovers(cfg, identity, monkeypatch, capsys, damage):
    root = monitor.cache_dir(cfg)
    previous = monitor.sample(cfg, Fake())
    if isinstance(damage, bytes):
        (root / 'latest.json').write_bytes(damage)
    else:
        if damage == 'jobs':
            previous['own']['jobs'] = None
        else:
            previous[damage] = 'invalid'
        (root / 'latest.json').write_text(json.dumps(previous))
    fake = Fake()
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda cfg, *, read_only: fake)
    sleeps = []
    tick = [0.0]
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    def sleep(seconds):
        tick[0] += 60
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(cfg, 60, json_output=True) == 0
    failed, recovered = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert not failed['ok'] and failed['last_ok_at'] is None
    assert 'Read previous monitor snapshot' in failed['error']
    assert failed['own']['jobs'] == []
    assert failed['cluster']['nodes'] == []
    assert recovered['ok'] and recovered['error'] is None
    assert recovered['last_ok_at'] == recovered['sampled_at']
    assert fake.calls == ['qstat -f', 'qstat -Q', 'pbsnodes -a']
    history = [json.loads(line) for line in (root / 'history.jsonl').read_text().splitlines()]
    assert [row['ok'] for row in history] == [True, False, True]


@pytest.mark.parametrize('damage', [b'{', b'\xff', b'null', b'[]', b'42', b'"text"',
                                  b'{"job_id":"101.fixture"}'])
def test_malformed_status_keeps_data_and_watch_running(cfg, identity, monkeypatch, capsys, damage):
    path = attempt(cfg, 'water-001-sp', '101.fixture', 'submitted')
    valid = path.read_bytes()
    previous = monitor.sample(cfg, Fake())
    path.write_bytes(damage)
    fake = Fake()
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda cfg, *, read_only: fake)
    sleeps = []
    tick = [0.0]
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    def sleep(seconds):
        tick[0] += 60
        sleeps.append(seconds)
        assert path.read_bytes() == (damage if len(sleeps) <= 2 else valid)
        if len(sleeps) == 2:
            path.write_bytes(valid)  # Simulate a human repairing the fixture.
        elif len(sleeps) == 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(cfg, 60, json_output=True) == 0
    first, second, recovered = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    for failed in (first, second):
        assert not failed['ok'] and failed['error']
        assert failed['last_ok_at'] == previous['last_ok_at']
        for key in ('own', 'cluster', 'warnings'):
            assert failed[key] == previous[key]
    assert recovered['ok'] and recovered['error'] is None
    assert len(fake.calls) == 9
    history = [json.loads(line) for line in (monitor.cache_dir(cfg) / 'history.jsonl').read_text().splitlines()]
    assert [row['ok'] for row in history] == [True, False, False, True]
