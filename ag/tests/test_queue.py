"""T11 queue admission uses only inert transport replies and synthetic water."""
import json

import pytest

from ag import attempt, config, confirm, monitor, remote, state, status, study, submit
from ag.transport import Result, TransportError
from test_core import Fake, INPUT, cfg, job_text, prepared, write_config
from test_monitor import Fake as MonitorFake, job


class QueueFake(Fake):
    def __init__(self, cfg, *, occupied=40, nodes=44):
        super().__init__(cfg)
        self.qstat = Result(stdout=job_text(cores=occupied)) if occupied else Result()
        self.nodes = Result(stdout=f'node-fixture\n    state = free\n    np = {nodes}\n')
        self.submitted_count = 0
        self.job_snapshots = []
        self.node_snapshots = []

    def run(self, command):
        if command.operation == 'nodes':
            self.calls.append(command)
            reply = self.node_snapshots.pop(0) if self.node_snapshots else self.nodes
            if isinstance(reply, Exception):
                raise reply
            return reply
        if command.operation == 'jobs' and self.job_snapshots:
            self.qstat = Result(stdout=self.job_snapshots.pop(0))
        if command.operation == 'submit':
            self.submitted_count += 1
            self.qsub = Result(stdout=f'{200 + self.submitted_count}.fixture\n')
        return super().run(command)


def prepare_batch(cfg, tmp_path, cores, count=1):
    study.init(cfg, 'water')
    cfg['resources']['tiers']['simple']['cores'] = cores
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace('nprocshared=8', f'nprocshared={cores}'))
    return [attempt.prepare(cfg, study_name='water', template='gaussian', input_path=source,
                            tier='simple', walltime='00:01:00', label=f'sp{i}')['attempt_id']
            for i in range(count)]


@pytest.mark.parametrize('value', [44, 88, 176])
def test_committed_config_valid(cfg, value):
    cfg['resources']['max_committed_cores'] = value
    assert config.load_config(write_config(cfg))['resources']['max_committed_cores'] == value


@pytest.mark.parametrize('value', [43, 177, 0, -1, True, False, 88.0, '88'])
def test_committed_config_invalid(cfg, value):
    cfg['resources']['max_committed_cores'] = value
    with pytest.raises(config.ConfigError, match='max_committed_cores'):
        config.load_config(write_config(cfg))


def test_committed_bounds_follow_max_cores(cfg):
    cfg['resources'].update(max_cores=8, max_committed_cores=32)
    assert config.load_config(write_config(cfg))['resources']['max_committed_cores'] == 32
    cfg['resources']['max_committed_cores'] = 33
    with pytest.raises(config.ConfigError):
        config.load_config(write_config(cfg))


def test_queue_admits_40_plus_32_and_shows_summary(cfg, tmp_path, monkeypatch, capsys):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, 32)
    fake = QueueFake(cfg)
    dialogs = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: dialogs.append(text) or True)
    assert submit.submit(cfg, ids, fake)[0]['state'] == 'submitted'
    line = '当前占用 40 核（运行 40、排队 0），提交后合计 72 / 上限 88 核；集群空闲不足时作业将在 PBS 中排队'
    assert line in dialogs[0]
    output = capsys.readouterr()
    assert line in output.err and output.out == ''
    assert fake.operations().count('nodes') == 1
    # The submission adds only T10's already-whitelisted read.
    assert {c.operation for c in fake.calls} == {
        'identity', 'jobs', 'nodes', 'create_attempt', 'upload', 'metadata', 'submit'}
    assert all(c == remote.nodes() for c in fake.calls if c.operation == 'nodes')


@pytest.mark.parametrize('cores,count', [(28, 2), (8, 7)])
def test_queue_rejects_40_plus_56_before_confirmation(cfg, tmp_path, monkeypatch, cores, count):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, cores, count)
    fake = QueueFake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('over cap'))
    with pytest.raises(ValueError, match='40 occupied.*56 requested / 88'):
        submit.submit(cfg, ids, fake)
    assert 'create_attempt' not in fake.operations()
    assert all(not (attempt.find(cfg, id_) / '.submit-claim').exists() for id_ in ids)


@pytest.mark.parametrize('nodes', [
    Result(stdout='node-a\n    state = free\n    np = 88\n'),
    Result(stdout='node-a\n    state = free\n    np = 44\nnode-b\n    state = down\n    np = 44\n'),
    Result(1, '', 'synthetic error'), TransportError('synthetic timeout'),
    Result(stdout='bad output'), Result(),
    Result(stdout='node-a\n    state = free\n    np = 0\n'),
])
def test_strict_fallback_rejects_40_plus_8(cfg, prepared, monkeypatch, capsys, nodes):
    cfg['resources']['max_committed_cores'] = 88
    fake = QueueFake(cfg)
    fake.nodes = nodes
    monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('over strict cap'))
    with pytest.raises(ValueError, match='40 occupied.*8 requested / 44'):
        submit.submit(cfg, [prepared[0].name], fake)
    assert '严格模式' in capsys.readouterr().err
    assert 'create_attempt' not in fake.operations()


def test_strict_fallback_can_submit_within_cap(cfg, prepared, monkeypatch, capsys):
    cfg['resources']['max_committed_cores'] = 88
    fake = QueueFake(cfg, occupied=32)
    fake.nodes = Result(1)
    dialogs = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: dialogs.append(text) or True)
    submit.submit(cfg, [prepared[0].name], fake)
    assert '严格模式：pbsnodes' in dialogs[0]
    assert '提交后合计 40 / 上限 44 核' in dialogs[0]


@pytest.mark.parametrize('occupied,allowed', [(36, True), (40, False)])
def test_omitted_config_preserves_old_limit(cfg, prepared, monkeypatch, occupied, allowed):
    cfg = config.load_config(write_config(cfg))
    assert cfg['resources']['max_committed_cores'] == 44
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    fake = QueueFake(cfg, occupied=occupied)
    if allowed:
        assert submit.submit(cfg, [prepared[0].name], fake)[0]['state'] == 'submitted'
    else:
        with pytest.raises(ValueError, match='Core limit exceeded'):
            submit.submit(cfg, [prepared[0].name], fake)


@pytest.mark.parametrize('reply', [Result(1), Result(stdout='broken qstat'),
                                  Result(stdout=job_text().replace('1:ppn=8', 'bad'))])
def test_unreadable_qstat_always_refuses(cfg, prepared, monkeypatch, reply):
    cfg['resources']['max_committed_cores'] = 88
    fake = QueueFake(cfg)
    fake.qstat = reply
    monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('qstat invalid'))
    with pytest.raises((ValueError, TransportError)):
        submit.submit(cfg, [prepared[0].name], fake)
    assert 'nodes' not in fake.operations()
    assert 'create_attempt' not in fake.operations()


def test_single_job_cannot_exceed_running_cap(cfg, prepared, monkeypatch):
    cfg['resources'].update(max_cores=4, max_committed_cores=16)
    fake = QueueFake(cfg, occupied=0, nodes=4)
    monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('single job too large'))
    with pytest.raises(ValueError, match='Single job'):
        submit.submit(cfg, [prepared[0].name], fake)
    assert fake.calls == []


@pytest.mark.parametrize('visible', [False, True])
def test_batch_cumulative_without_double_count(cfg, tmp_path, monkeypatch, visible):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, 16, 3)
    fake = QueueFake(cfg)
    snapshots = [job_text(cores=40), job_text(cores=40)]
    for n in (1, 2):
        snapshots.append(job_text(cores=40) + (''.join(
            job_text(cores=16, state_='Q').replace('123.fixture', f'{201+i}.fixture')
            for i in range(n)) if visible else ''))
    fake.job_snapshots = snapshots
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    assert len(submit.submit(cfg, ids, fake)) == 3
    assert fake.submitted_count == 3


def test_batch_counts_missing_qsub_and_new_external_jobs(cfg, tmp_path, monkeypatch):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, 16, 3)
    fake = QueueFake(cfg)
    # A new external job appears, while our first qsub is still invisible.
    fake.job_snapshots = [job_text(cores=n) for n in (40, 40, 60)]
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(cfg, ids, fake)
    assert fake.submitted_count == 1
    assert [state.read(attempt.find(cfg, id_))['state'] for id_ in ids] == [
        'submitted', 'failed_presubmit', 'prepared']


def test_batch_reuses_confirmed_hardware_result(cfg, tmp_path, monkeypatch, capsys):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, 16, 3)
    fake = QueueFake(cfg)
    fake.node_snapshots = [fake.nodes, TransportError('must not query nodes again')]
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    assert len(submit.submit(cfg, ids, fake)) == 3
    assert fake.operations().count('nodes') == 1
    assert fake.operations().count('identity') == 1
    assert fake.operations().count('jobs') == 4
    assert '严格模式' not in capsys.readouterr().err


@pytest.mark.parametrize('nodes', [Result(1), Result(stdout='node-a\n    state = free\n    np = 88\n')])
def test_batch_retains_confirmed_strict_cap(cfg, tmp_path, monkeypatch, nodes):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, 8, 2)
    fake = QueueFake(cfg, occupied=24)
    fake.node_snapshots = [nodes, fake.nodes]
    # First job is still invisible, and another client adds 8 cores.
    fake.job_snapshots = [job_text(cores=n) for n in (24, 24, 32)]
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(cfg, ids, fake)
    assert fake.operations().count('nodes') == 1
    assert fake.submitted_count == 1
    assert [state.read(attempt.find(cfg, id_))['state'] for id_ in ids] == [
        'submitted', 'failed_presubmit']


@pytest.mark.parametrize('reply', [Result(1), Result(stdout='broken qstat'),
                                  Result(stdout=job_text().replace('1:ppn=8', 'bad'))])
def test_unreadable_qstat_after_confirmation_stops(cfg, prepared, monkeypatch, reply):
    cfg['resources']['max_committed_cores'] = 88
    fake = QueueFake(cfg)

    def accept(text):
        fake.qstat = reply
        return True

    monkeypatch.setattr(confirm, 'confirm', accept)
    with pytest.raises((ValueError, TransportError)):
        submit.submit(cfg, [prepared[0].name], fake)
    assert 'create_attempt' not in fake.operations()
    assert state.read(prepared[0])['state'] == 'failed_presubmit'
    assert fake.operations().count('nodes') == 1


@pytest.mark.parametrize('scheduler_state', ['R', 'E', 'Q', 'H', 'W', 'T', 'S', 'C'])
def test_breakdown_monitor_and_submit_match(cfg, scheduler_state):
    cfg['resources']['max_committed_cores'] = 88
    raw = job(state=scheduler_state, cores='2:ppn=8+node-b:ppn=4') + job('105.fixture', owner='other')
    own = monitor.observation(cfg, MonitorFake(jobs=raw), 'fixture')['own']
    total = 0 if scheduler_state == 'C' else 20
    running = 20 if scheduler_state in ('R', 'E') else 0
    assert status.core_breakdown(status.parse_jobs(raw), 'fixture') == (running, total - running)
    assert own['cores_running'] == running
    assert own['cores_queued'] == total - running
    assert own['cores_in_use'] == total
    assert own['core_cap'] == 44 and own['committed_cap'] == 88


@pytest.mark.parametrize('nodes,cap', [
    ('node-a\n    state = free\n    np = 44\n', 88),
    ('node-a\n    state = free\n    np = 88\n', 44),
    ('node-a\n    state = free\n    np = 44\nnode-b\n    state = down\n    np = 8\n', 44),
])
@pytest.mark.parametrize('cores', [44, 45, 72, 88, 96])
def test_monitor_warns_at_effective_cap(cfg, cores, nodes, cap):
    cfg['resources']['max_committed_cores'] = 88
    raw = job(cores='1:ppn=40') + job('102.fixture', state='Q', cores=f'1:ppn={cores - 40}')
    result = monitor.observation(cfg, MonitorFake(jobs=raw, nodes=nodes), 'fixture')
    assert result['own']['committed_cap'] == 88  # Configured allowance remains visible.
    assert bool(result['warnings']) == (cores > cap)
    if cores > cap:
        assert result['warnings'][0]['kind'] == 'over-cap'
        assert f'超过上限 {cap} 核' in result['warnings'][0]['detail']


def test_old_monitor_cache_allows_incremental_fields(cfg, monkeypatch):
    monkeypatch.setattr(monitor, 'login_user', lambda cfg: 'fixture')
    cfg['resources']['max_committed_cores'] = 88
    initial = monitor.sample(cfg, MonitorFake())
    for key in ('cores_running', 'cores_queued', 'committed_cap'):
        initial['own'].pop(key)
    (monitor.cache_dir(cfg) / 'latest.json').write_text(json.dumps(initial))
    current = monitor.sample(cfg, MonitorFake())
    assert current['ok'] and current['schema'] == 'ag-monitor/1'
    assert current['own']['committed_cap'] == 88


def test_confirmation_splits_running_and_queued_for_all_own_jobs(cfg, prepared, monkeypatch):
    cfg['resources']['max_committed_cores'] = 88
    fake = QueueFake(cfg)
    fake.qstat = Result(stdout=(job_text(cores=16, state_='E')
        + job_text(cores=24, state_='H').replace('123.fixture', '124.fixture')
        + job_text(cores=44, owner='other').replace('123.fixture', '125.fixture')
        + job_text(cores=44, state_='C').replace('123.fixture', '126.fixture')))
    dialogs = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: dialogs.append(text) or False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(cfg, [prepared[0].name], fake)
    assert '当前占用 40 核（运行 16、排队 24），提交后合计 48 / 上限 88 核' in dialogs[0]
    assert not (prepared[0] / '.submit-claim').exists()


def test_batch_completed_job_does_not_reserve_cores(cfg, tmp_path, monkeypatch):
    cfg['resources']['max_committed_cores'] = 88
    ids = prepare_batch(cfg, tmp_path, 16, 2)
    fake = QueueFake(cfg)
    fake.job_snapshots = [job_text(cores=40), job_text(cores=40), job_text(cores=60)
        + job_text(cores=16, state_='C').replace('123.fixture', '201.fixture')]
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    assert len(submit.submit(cfg, ids, fake)) == 2
