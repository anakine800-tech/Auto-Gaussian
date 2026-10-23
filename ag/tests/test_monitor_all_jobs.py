"""T114 synthetic queues and clocks; no live configuration or network access."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import subprocess

import pytest

from ag import config, monitor, pbs, remote, slurm, status
from ag.transport import Result, SSHConnectionError, READ_OPERATIONS
from test_core import cfg, write_config
from test_monitor import Fake as PBSFake, job, attempt
from test_slurm import multi, SlurmFake


NOW = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)


def row(number, user='userA', state='R', extra=''):
    return job(f'{number}.fixture', owner=user, state=state,
               extra='    exec_host = node-a/0-3+node-b/0*2\n' + extra)


@pytest.mark.parametrize('value', ['50gb', '51200mb', '52428800kb', '53687091200b', '0.048828125TB', '50GB'])
def test_memory_units(value):
    assert pbs.memory_gb(value) == 50.0


@pytest.mark.parametrize('value', [None, '', '50', '50GiB', '-2gb', 'nangb', 'infgb'])
def test_unknown_memory(value):
    assert pbs.memory_gb(value) is None


def test_all_jobs_association_allocated_requested_and_completed(cfg):
    attempt(cfg, 'water-001-sp', '901.fixture', 'submitted')
    raw = row(901) + ''.join(row(i, 'userB') for i in range(902, 905))
    raw += row(905, 'userC', 'Q') + row(906, 'userD', 'H') + row(907, 'userA', 'C')
    result = monitor.observation(cfg, PBSFake(jobs=raw), 'userA', sampled_at=NOW)
    rows = result['cluster']['jobs']
    assert len(rows) == 6 and result['cluster']['jobs_omitted'] == 0
    assert rows[0]['mine'] and rows[0]['attempt'] == 'water-001-sp'
    assert all(r['study'] is None and r['attempt'] is None for r in rows[1:])
    assert [(r['cores'], r['cores_kind']) for r in rows] == [(6, 'allocated')] * 4 + [(8, 'requested')] * 2
    assert result['own']['cores_in_use'] == 8  # Admission accounting is unchanged.
    assert result['own']['jobs'] == [rows[0]]
    assert result['own']['mem_running_gb'] == 12.0
    assert result['own']['mem_queued_gb'] == 0
    assert result['cluster']['job_summary'] == dict(running_jobs=4, running_cores=24,
        queued_jobs=2, queued_cores=16, others_running_jobs=3, others_running_cores=18,
        others_queued_jobs=2, others_queued_cores=16)


def test_unknown_mem_is_not_partial_sum(cfg):
    raw = row(901) + row(902, state='Q').replace('Resource_List.mem = 12gb', 'Resource_List.mem = unknown')
    raw += row(903).replace('    Resource_List.mem = 12gb\n', '')
    result = monitor.observation(cfg, PBSFake(jobs=raw), 'userA')
    assert result['own']['mem_running_gb'] is None
    assert result['own']['mem_queued_gb'] is None


@pytest.mark.parametrize('start', ['1767225600', '2026-01-01T08:00:00+08:00', '2026-01-01T00:00:00Z'])
def test_start_and_queue_time_normalized(start):
    parsed = status.parse_jobs(row(901))[0]
    parsed.update(start_time=start, qtime='1767222000')
    fields = pbs.job_fields(parsed, NOW)
    assert fields['elapsed_seconds'] == 3600 and fields['elapsed_source'] == 'start_time'
    assert fields['start_time'] == '2026-01-01T00:00:00Z'
    assert fields['qtime'] == '2025-12-31T23:00:00Z'
    assert fields['walltime_limit_seconds'] == 3600


def test_timezone_unknown_and_missing_elapsed():
    parsed = status.parse_jobs(row(901))[0]
    parsed.update(start_time='Thu Jan  1 00:00:00 2026', qtime='Thu Jan  1 00:00:00 2026')
    fields = pbs.job_fields(parsed, NOW)
    assert fields['start_time'] is None and fields['qtime'] is None
    assert fields['elapsed_seconds'] == 600 and fields['elapsed_source'] == 'walltime_used'
    parsed.pop('resources_used.walltime')
    fields = pbs.job_fields(parsed, NOW)
    assert fields['elapsed_seconds'] is None and fields['elapsed_source'] is None
    parsed['start_time_epoch'] = '1767225600'
    assert pbs.job_fields(parsed, NOW)['elapsed_source'] == 'start_time'


def test_limit_and_sort_before_truncation(cfg):
    raw = ''.join(row(i, 'userB', 'Q', f'    qtime = {1767222000 + i}\n') for i in range(1500, 900, -1))
    raw += row(3000, extra='    start_time_epoch = 1767225600\n')
    raw += row(3001, 'userB', extra='    start_time_epoch = 1767225601\n')
    raw += row(3002, 'userB', extra='    start_time_epoch = 1767225600\n')
    result = monitor.observation(cfg, PBSFake(jobs=raw), 'userA', sampled_at=NOW)
    rows = result['cluster']['jobs']
    assert len(rows) == 500 and result['cluster']['jobs_omitted'] == 103
    assert [r['job_id'] for r in rows[:4]] == ['3000.fixture', '3002.fixture', '3001.fixture', '901.fixture']
    assert result['cluster']['job_summary']['queued_jobs'] == 600


def test_pbs_node_memory_and_distinct_job_count(cfg):
    nodes = ('node-a\n    state = free\n    resources_available.ncpus = 32\n'
             '    resources_available.mem = 65536mb\n    resources_assigned.mem = 12gb\n'
             '    jobs = 0/901.fixture, 1/901.fixture, 2-3/902.fixture\n')
    result = monitor.observation(cfg, PBSFake(jobs='', nodes=nodes), 'userA')
    node = result['cluster']['nodes'][0]
    assert node['jobs'] == 2 and node['mem_total_gb'] == 64 and node['mem_assigned_gb'] == 12
    hardware = result['cluster']['hardware']
    assert hardware['mem_total_gb'] == 64 and hardware['mem_allocated_gb'] == 12
    assert (hardware['cores_total'], hardware['cores_allocated'], hardware['cores_idle'], hardware['cores_other']) == (32, 4, 28, 0)
    nodes += 'node-b\n    state = down\n    np = 8\n'
    result = monitor.observation(cfg, PBSFake(jobs='', nodes=nodes), 'userA')
    assert result['cluster']['hardware']['mem_total_gb'] is None
    assert result['cluster']['hardware']['mem_allocated_gb'] is None
    assert result['cluster']['hardware']['cores_other'] == 8


@pytest.mark.parametrize('failure', [Result(255, stderr='fixture failure'), SSHConnectionError('fixture timeout'),
                                   Result(stdout='node-a\n    state = free\n')])
def test_pbs_hardware_failure_is_partial(cfg, monkeypatch, failure):
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'userA')
    fake = PBSFake(jobs=row(901))
    fake.replies['nodes'] = failure
    result = monitor.sample(cfg, fake)
    assert result['ok'] and result['own']['jobs']
    hardware = result['cluster']['hardware']
    assert hardware['error'] and 'fixture' not in hardware['error']
    assert all(v is None for k, v in hardware.items() if k not in ('source', 'error'))


class PartitionFake(SlurmFake):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.partition_jobs = Result(stdout='RUNNING|8\nRUNNING|16\nPENDING|4\nPENDING|8\n')
        self.hardware = Result(stdout='24/36/4/64|65536|2\n')
        self.allocmem = Result(stdout='8192                \n16384               \n')
        self.queue = Result(stdout='901|water|userA|RUNNING|8|10:00|fixture\n'
                            '902|water|userA|PENDING|4|0:00|fixture\n'
                            '903|water|userA|RUNNING|2|1-00:00:00|second\n')

    def run(self, command):
        for factory, value in ((remote.slurm_partition_jobs, self.partition_jobs),
                               (remote.slurm_partition_hardware, self.hardware),
                               (remote.slurm_partition_allocmem, self.allocmem)):
            if command == factory(self.cfg.get('partition', 'fixture')):
                self.calls.append(command)
                if isinstance(value, Exception):
                    raise value
                return value
        return super().run(command)


def test_slurm_partition_totals_own_account_and_no_node_rows(multi):
    entry = config.select_cluster(multi, 'batch')
    result = monitor.observation(entry, PartitionFake(entry), 'userA')
    assert result['own']['cores_in_use'] == 14
    assert result['cluster']['job_summary'] == dict(running_jobs=2, running_cores=24,
        queued_jobs=2, queued_cores=12, others_running_jobs=1, others_running_cores=16,
        others_queued_jobs=1, others_queued_cores=8)
    assert result['cluster']['hardware'] == dict(cores_total=64, cores_allocated=24, cores_idle=36,
        cores_other=4, mem_total_gb=128.0, mem_allocated_gb=24.0, source='sinfo', error=None)
    assert result['cluster']['nodes'] == [] and result['cluster']['hardware_capacity_known']
    assert result['cluster']['jobs'] == result['own']['jobs']
    assert all(r['mine'] and r['user'] == 'userA' for r in result['cluster']['jobs'])
    assert result['own']['mem_running_gb'] is None
    assert result['own']['jobs'][0]['elapsed_seconds'] == 600
    assert result['own']['jobs'][2]['elapsed_seconds'] == 86400


def test_partition_race_does_not_invent_negative_others(multi):
    entry = config.select_cluster(multi, 'batch')
    fake = PartitionFake(entry)
    fake.partition_jobs = Result(stdout='RUNNING|4\n')
    result = monitor.observation(entry, fake, 'userA')
    assert all(v is None for k, v in result['cluster']['job_summary'].items() if k.startswith('others_'))
    assert '不一致' in result['cluster']['hardware']['error']


def test_no_partition_never_queries_cluster(multi):
    del multi['clusters']['batch']['partition']
    entry = config.select_cluster(multi, 'batch')
    fake = PartitionFake(entry)
    result = monitor.observation(entry, fake, 'userA')
    assert all('sinfo' not in c.text and ' -p ' not in c.text for c in fake.calls)
    assert result['cluster']['hardware']['error'] == '未配置分区'
    assert all(v is None for v in result['cluster']['job_summary'].values())


@pytest.mark.parametrize('part', ['hardware', 'allocmem'])
def test_slurm_hardware_failure_does_not_hide_jobs(multi, monkeypatch, part):
    entry = config.select_cluster(multi, 'batch')
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'userA')
    fake = PartitionFake(entry)
    setattr(fake, part, Result(1, stderr=entry['ssh']['host'] + ' unavailable'))
    result = monitor.sample(entry, fake)
    assert result['ok'] and len(result['own']['jobs']) == 3
    assert not result['cluster']['hardware_capacity_known']
    assert result['cluster']['hardware']['cores_total'] is None
    assert 'fixture' not in result['cluster']['hardware']['error']


def test_partition_job_failure_retains_last_success(multi, monkeypatch):
    entry = config.select_cluster(multi, 'batch')
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'userA')
    fake = PartitionFake(entry)
    before = monitor.sample(entry, fake)
    fake.partition_jobs = Result(1, stderr='fixture unavailable')
    after = monitor.sample(entry, fake)
    assert not after['ok'] and after['cluster'] == before['cluster']


def test_heterogeneous_sinfo_memory_is_unknown():
    result = slurm.parse_partition_hardware('12/48/4/64|65536+|2\n')
    assert result['mem_total_gb'] is None and result['cores_total'] == 64
    assert slurm.parse_allocmem(' 1024 \n 2048 \n') == 3


@pytest.mark.parametrize('raw', ['', 'a|1|2', '0/0/1/4|1|1', '0/1/0/1|bad|1'])
def test_bad_hardware_is_not_zero(raw):
    with pytest.raises(ValueError):
        slurm.parse_partition_hardware(raw)


def test_partition_commands_use_validated_selector_and_existing_read_operations():
    assert remote.slurm_partition_jobs('part-a').text == "squeue -h -p part-a -r --local -o '%T|%C'"
    assert remote.slurm_partition_hardware('part-a').text == "sinfo -h -p part-a -o '%C|%m|%D'"
    assert remote.slurm_partition_allocmem('part-a').text == 'sinfo -h -p part-a -N -O AllocMem:20'
    for factory in (remote.slurm_partition_jobs, remote.slurm_partition_hardware, remote.slurm_partition_allocmem):
        assert factory('part-a').operation in READ_OPERATIONS
        for bad in (None, '', '-a', 'a,b', 'a;id', 'a\nb', '$(id)', 'a b', '../a'):
            with pytest.raises(ValueError):
                factory(bad)


@pytest.mark.parametrize('damage', [None, b'{', b'\xff', b'null', b'[]', b'{}', b'{"own":null}'])
def test_removed_corrupt_or_missing_cache(cfg, damage):
    root = monitor.cache_dir(cfg)
    if damage is not None:
        (root / 'latest.json').write_bytes(damage)
    monitor.mark_removed(cfg)
    snapshot = json.loads((root / 'latest.json').read_text())
    assert snapshot['schema'] == 'ag-monitor/1' and not snapshot['ok']
    assert snapshot['config_removed'] and snapshot['last_ok_at'] is None
    assert snapshot['error'] == '缓存不可读，已按配置移除处理'


@pytest.mark.parametrize('order', [0, -10, 4])
def test_display_order_success_failure_config_and_legacy(cfg, monkeypatch, order):
    path = write_config(cfg)
    path.write_text(f'display_order = {order}\n' + path.read_text())
    loaded = config.load_config(path)
    assert loaded['display_order'] == order
    cfg['display_order'] = order
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'userA')
    fake = PBSFake(jobs=row(901))
    assert monitor.sample(cfg, fake)['cluster']['display_order'] == order
    fake.replies['jobs'] = Result(1)
    cfg['display_order'] = order + 1
    assert monitor.sample(cfg, fake)['cluster']['display_order'] == order + 1
    cfg.pop('display_order')
    assert monitor.sample(cfg, fake)['cluster']['display_order'] is None


@pytest.mark.parametrize('value', [True, 1.5, '1', None])
def test_bad_display_order(cfg, value):
    cfg['display_order'] = value
    with pytest.raises(ValueError, match='display_order'):
        config.validate_cluster(cfg)


def test_history_contains_counts_only(cfg, monkeypatch):
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'userA')
    monitor.sample(cfg, PBSFake(jobs=row(901) + row(902, 'userB')))
    text = (monitor.cache_dir(cfg) / 'history.jsonl').read_text()
    assert all(private not in text for private in ('userA', 'userB', '902.fixture', 'node-a', 'water'))
    summary = json.loads(text)
    assert summary['job_summary']['others_running_jobs'] == 1
    assert type(summary['warnings']) is int and type(summary['sample_duration_ms']) is int


@pytest.mark.parametrize('slow', [False, True])
def test_entry_cadence_and_no_overlapping_rounds(multi, monkeypatch, capsys, slow):
    tick = [0.0]
    calls, sleeps = [], []
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: None)
    def sample(entry, transport, interval, **kwargs):
        calls.append((entry['_cluster'], tick[0], interval))
        if slow:
            tick[0] += 40
        return {'ok': True}
    def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 3:
            raise KeyboardInterrupt
        tick[0] += delay
    monkeypatch.setattr(monitor, 'sample', sample)
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run_clusters(multi, 30) == 0
    if slow:
        assert sleeps == [0, 0, 0]
        assert [c[1] for c in calls] == [0, 40, 80, 120, 160, 200]
    else:
        assert [(name, at) for name, at, _ in calls] == [('batch', 0), ('default', 0),
            ('default', 30), ('batch', 60), ('default', 60)]
    assert all(interval == (60 if name == 'batch' else 30) for name, _, interval in calls)


def test_sample_duration_measures_collection(cfg, monkeypatch):
    tick = [0.0]
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'userA')
    fake = PBSFake(jobs=row(901))
    original = fake.run
    def run(command):
        tick[0] += 0.25
        return original(command)
    fake.run = run
    result = monitor.sample(cfg, fake, 30)
    assert result['sample_duration_ms'] == 750
