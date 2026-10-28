"""Single-node advice uses synthetic scheduler records and local files only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from ag import capacity, cli, config, monitor, pbs, remote, slurm
from ag.transport import SSHTransport, Result
from test_core import cfg
from test_slurm import multi, SlurmFake
from test_monitor import Fake as PBSFake


NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def node(name='node-a', **values):
    row = dict(dict(name=name, state='free', cores_total=44, cores_used=0,
                    mem_total_gb=120, mem_assigned_gb=0, capacity_cpu_consistent=True), **values)
    for key in ('mem_total', 'mem_assigned'):
        value = row[key + '_gb']
        row[key + '_bytes'] = value * 1024**3 if type(value) is int and value >= 0 else None
    return row


def save(cfg, nodes, name='default', **values):
    data = monitor.empty_snapshot(config.select_cluster(cfg, name), 60)
    data.update(dict(sampled_at=NOW.isoformat(), ok=True) | values)
    data['cluster'].update(nodes=nodes)
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    if 'clusters' in cfg:
        root /= name
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'latest.json'
    path.write_text(json.dumps(data))
    return path, data


def assess(cfg, **kwargs):
    return capacity.assess(cfg, 'default', 'general', now=NOW, **kwargs)


@pytest.mark.parametrize('nodes,fit,availability', [
    ([node()], True, 'enough'),
    ([node(cores_used=30)], True, 'queue'),
    ([node(mem_assigned_gb=90)], True, 'queue'),
    ([node(cores_total=16), node('node-b', mem_total_gb=32)], False, 'not_applicable'),
    ([node(cores_used=30), node('node-b', mem_assigned_gb=90)], True, 'queue'),
    ([node(mem_total_gb=32), node('node-b', cores_total=64)], True, 'enough'),
    ([node(mem_total_gb=None)], None, 'unknown'),
    ([node(mem_assigned_gb=None)], True, 'unknown'),
    ([node(cores_used=None)], True, 'unknown'),
    ([node(mem_assigned_gb=121)], True, 'unknown'),
    ([node(cores_used=45)], True, 'unknown'),
    ([node(state='down,offline')], True, 'unknown'),
    ([node(state='job-exclusive', cores_used=2)], True, 'queue'),
    ([node(targeting_consistent=False)], None, 'unknown'),
    ([], None, 'unknown'),
])
def test_single_node_conclusions(cfg, nodes, fit, availability):
    save(cfg, nodes)
    result = assess(cfg)
    assert (result['fits_total'], result['availability']) == (fit, availability)
    assert result['reasons']
    assert result['cores'] == 22 and result['mem_gb'] == 50


def test_duplicates_and_exact_target(cfg):
    n = node()
    save(cfg, [n, deepcopy(n)])
    assert len(assess(cfg)['nodes']) == 1
    save(cfg, [n, node(cores_used=40)])
    assert assess(cfg)['availability'] == 'unknown'
    save(cfg, [node('node-a.synthetic'), node('node-b', cores_used=40)])
    assert assess(cfg, target_node='node-a')['availability'] == 'unknown'
    assert assess(cfg, target_node='node-b')['availability'] == 'queue'
    assert assess(cfg, target_node='node-a.synthetic')['availability'] == 'enough'


def test_policy_filters_and_no_alias_targeting(cfg):
    cfg['node_targeting'] = dict(allowed_nodes=['node-a', 'node-b'], denied_nodes=[],
                                restricted_nodes=['node-a'], priority=[['node-a', 'node-b']])
    save(cfg, [node(), node('node-b', cores_used=40)])
    assert assess(cfg)['availability'] == 'queue'
    assert assess(cfg, target_node='node-a')['availability'] == 'unknown'


@pytest.mark.parametrize('kind', ['old', 'empty', 'failed', 'invalid', 'future', 'stale', 'node-error'])
def test_missing_invalid_and_stale_snapshots(cfg, kind):
    path, data = save(cfg, [node()])
    if kind == 'old':
        del data['cluster']['nodes']
        data['cluster']['hardware'] = dict(cores_idle=10000, mem_total_gb=10000, mem_allocated_gb=0)
    elif kind == 'empty':
        data['cluster']['nodes'] = []
    elif kind == 'failed':
        data['ok'] = False
    elif kind == 'invalid':
        data['cluster']['nodes'] = [dict(name='invalid node')]
    elif kind == 'node-error':
        data['cluster']['nodes_error'] = 'synthetic query failed'
    else:
        data['sampled_at'] = (NOW + timedelta(seconds=1 if kind == 'future' else -181)).isoformat()
    path.write_text(json.dumps(data))
    assert assess(cfg)['availability'] == 'unknown'


def test_expiry_boundary(cfg):
    save(cfg, [node()], sampled_at=(NOW - timedelta(seconds=180)).isoformat())
    result = assess(cfg)
    assert result['availability'] == 'enough' and result['valid_until'] == NOW.isoformat()


def test_tier_metadata_does_not_become_evaluator_arguments(cfg):
    # Existing configuration validation permits additional tier metadata.
    cfg['resources']['tiers']['general']['description'] = 'Synthetic tier'
    config.validate_cluster(cfg)
    save(cfg, [node()])
    result = assess(cfg)
    assert result['availability'] == 'enough'
    assert result['cores'] == 22 and result['mem_gb'] == 50


@pytest.mark.parametrize('field,value', [('cores_total', True), ('cores_used', -1),
    ('mem_total_gb', float('nan')), ('mem_assigned_gb', float('inf')), ('mem_assigned_gb', False)])
def test_numeric_unknowns(cfg, field, value):
    save(cfg, [node(**{field: value})])
    assert assess(cfg)['availability'] == 'unknown'


def test_slurm_units_zero_unknown_and_partition(multi):
    raw = 'node-a|fixture|0/32/0/32|65536|0|idle|up\n'
    nodes = slurm.parse_nodes(raw, 'fixture')
    assert nodes[0]['mem_total_gb'] == 64 and nodes[0]['mem_assigned_gb'] == 0
    save(multi, nodes, 'batch')
    result = capacity.assess(multi, 'batch', 'general', now=NOW)
    assert result['availability'] == 'enough'
    assert result['memory_source'] == 'sinfo Memory/AllocMem'
    nodes[0]['mem_assigned_gb'] = None
    save(multi, nodes, 'batch')
    assert capacity.assess(multi, 'batch', 'general', now=NOW)['availability'] == 'unknown'
    nodes[0]['partition'] = 'different'
    save(multi, nodes, 'batch')
    assert capacity.assess(multi, 'batch', 'general', now=NOW)['fits_total'] is None


@pytest.mark.parametrize('state', ['down', 'drained', 'draining', 'idle*', 'idle~', 'reserved', 'future', 'idle+'])
def test_slurm_unschedulable_states(state):
    row = slurm.parse_nodes(f'node-a|fixture|0/32/0/32|65536|0|{state}|up', 'fixture')[0]
    assert capacity.evaluate_node(row, 8, 12, scheduler='slurm', partition='fixture')['availability'] == 'unknown'


def test_slurm_allocation_other_and_partition_state():
    for raw, expected in [
        ('8/24/0/32|65536|8192|mixed|up', 'enough'),
        ('32/0/0/32|65536|8192|allocated|up', 'queue'),
        ('0/24/8/32|65536|0|mixed|up', 'unknown'),
        ('0/32/0/32|65536|0|idle|down', 'unknown'),
        ('8/24/0/32|65536|0|idle|up', 'unknown'),
    ]:
        row = slurm.parse_nodes('node-a|fixture|' + raw, 'fixture')[0]
        assert capacity.evaluate_node(row, 22, 50, scheduler='slurm', partition='fixture')['availability'] == expected


def test_command_is_local_read_only(cfg, monkeypatch, capsys):
    save(cfg, [node()], sampled_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(capacity, 'load_config', lambda: cfg)
    def forbidden(*args, **kwargs):
        raise AssertionError('Read-only command attempted a side effect')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(Path, 'write_text', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    monkeypatch.setattr(Path, 'mkdir', forbidden)
    assert cli.main(['capacity', '--cluster', 'default', '--tier', 'general', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['availability'] == 'enough'
    # A missing cache must not create its directory either.
    cfg['local']['studies_root'] += '-missing'
    assert cli.main(['capacity', '--cluster', 'default', '--tier', 'simple', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['availability'] == 'unknown'


def test_node_query_failure_keeps_existing_observations(multi):
    selected = config.select_cluster(multi, 'batch')
    class FailedNodeQuery(SlurmFake):
        def run(self, command):
            if command == remote.slurm_partition_nodes('fixture'):
                return Result(1, '', 'synthetic unsupported field')
            return super().run(command)
    fake = FailedNodeQuery(selected)
    fake.queue = Result(stdout='123|synthetic|fixture|RUNNING|8|00:10|fixture\n')
    result = monitor.observation(selected, fake, 'fixture')
    assert result['own']['cores_running'] == 8
    assert result['cluster']['hardware']['cores_total'] == 32
    assert result['cluster']['hardware']['mem_allocated_gb'] == 8
    assert result['cluster']['nodes'] == [] and result['cluster']['nodes_error']


def test_monitor_publishes_identified_node_rows(multi):
    selected = config.select_cluster(multi, 'batch')
    result = monitor.observation(selected, SlurmFake(selected), 'fixture')
    assert result['cluster']['nodes_error'] is None
    row = result['cluster']['nodes'][0]
    assert row['name'] == 'node-a' and row['partition'] == 'fixture'
    assert row['cores_used'] == 8 and row['mem_assigned_gb'] == 8


def test_shared_account_entries_keep_separate_node_capacity(multi):
    multi['clusters']['second'] = deepcopy(multi['clusters']['batch'])
    save(multi, slurm.parse_nodes('node-a|fixture|0/32/0/32|65536|0|idle|up', 'fixture'), 'batch')
    save(multi, slurm.parse_nodes('node-b|fixture|0/16/0/16|32768|0|idle|up', 'fixture'), 'second')
    assert capacity.assess(multi, 'batch', 'general', now=NOW)['availability'] == 'enough'
    assert capacity.assess(multi, 'second', 'general', now=NOW)['availability'] == 'not_applicable'


@pytest.mark.parametrize('assigned,expected', [('28', 'unknown'), ('4', 'enough'), ('invalid', 'unknown')])
def test_pbs_cpu_conflicts_without_targeting_preserve_display(cfg, assigned, expected):
    assert 'node_targeting' not in cfg
    raw = ('node-a\n    state = free\n    resources_available.ncpus = 32\n'
           f'    resources_assigned.ncpus = {assigned}\n'
           '    resources_available.mem = 64gb\n    resources_assigned.mem = 0gb\n')
    jobs = [dict(job_id='101.fixture', job_state='R', exec_host='node-a/0-3')]
    rows, hardware = monitor.pbs_hardware(cfg, PBSFake(nodes=raw), jobs)
    assert rows[0]['cores_used'] == hardware['cores_allocated'] == 4
    assert rows[0]['capacity_cpu_consistent'] is (assigned == '4')
    save(cfg, rows)
    assert capacity.assess(cfg, 'default', 'simple', now=NOW)['availability'] == expected


@pytest.mark.parametrize('state', ['R', 'E', 'S'])
@pytest.mark.parametrize('hosts', [None, '', '+', 'missing-node/0-3', 'node-a.synthetic/0-3'])
def test_unlocated_active_pbs_jobs_make_capacity_unknown_only(cfg, state, hosts):
    raw = ''.join(f'{name}\n    state = free\n    np = 32\n    status = physmem=64gb\n'
                  for name in ('node-a', 'node-b'))
    job = dict(job_id='101.fixture', job_state=state, **{'Resource_List.mem': '12gb'})
    if hosts is not None:
        job['exec_host'] = hosts
    rows, hardware = monitor.pbs_hardware(cfg, PBSFake(nodes=raw), [job])
    # Keep the established display, but do not infer an idle node from absent
    # active-job placement. A second node cannot rescue this unknown mapping.
    assert hardware['cores_allocated'] == 0 and hardware['mem_allocated_gb'] == 0
    assert all(r['cores_used'] == 0 and r['mem_assigned_gb'] == 0 for r in rows)
    assert all(r['capacity_cpu_consistent'] is False for r in rows)
    save(cfg, rows)
    result = capacity.assess(cfg, 'default', 'simple', now=NOW)
    assert result['availability'] == 'unknown'


@pytest.mark.parametrize('state', [None, 'Q', 'H', 'W', 'T', 'C', 'R', 'E', 'S'])
def test_empty_or_located_pbs_jobs_can_still_fit_exactly(cfg, state):
    raw = 'node-a\n    state = free\n    np = 32\n    status = physmem=64gb\n'
    jobs = [] if state is None else [dict(job_id='101.fixture', job_state=state)]
    active = state in ('R', 'E', 'S')
    if active:
        jobs[0].update(exec_host='node-a/0-3', **{'Resource_List.mem': '12gb'})
    rows, _ = monitor.pbs_hardware(cfg, PBSFake(nodes=raw), jobs)
    assert rows[0]['capacity_cpu_consistent'] is True
    cfg['resources']['tiers']['general'] = dict(cores=28 if active else 32, mem_gb=52 if active else 64)
    save(cfg, rows)
    assert assess(cfg)['availability'] == 'enough'


@pytest.mark.parametrize('extra', ['    np = 16\n', '    jobs = 0-7/101.fixture\n',
                                  '    jobs = 0-3/102.fixture\n'])
def test_pbs_other_cpu_source_conflicts(extra):
    raw = ('node-a\n    state = free\n    resources_available.ncpus = 32\n'
           '    resources_assigned.ncpus = 4\n    resources_available.mem = 64gb\n'
           '    resources_assigned.mem = 0gb\n' + extra)
    jobs = [dict(job_id='101.fixture', job_state='R', exec_host='node-a/0-3')]
    row = pbs.parse_nodes(raw, jobs)[0]
    assert row['capacity_cpu_consistent'] is False
    assert capacity.evaluate_node(row, 8, 12, scheduler='pbs')['availability'] == 'unknown'


@pytest.mark.parametrize('total,assigned,requested_gb,fit,expected', [
    ('65535mb', '0gb', 64, False, 'not_applicable'),
    ('64gb', '40961mb', 24, True, 'queue'),
    ('65536mb', '40960mb', 24, True, 'enough'),
    ('64gb', '0gb', 64, True, 'enough'),
])
def test_pbs_capacity_uses_bytes_not_rounded_display(cfg, total, assigned, requested_gb, fit, expected):
    raw = ('node-a\n    state = free\n    resources_available.ncpus = 32\n'
           '    resources_assigned.ncpus = 0\n'
           f'    resources_available.mem = {total}\n    resources_assigned.mem = {assigned}\n')
    rows, hardware = monitor.pbs_hardware(cfg, PBSFake(nodes=raw), [])
    assert rows[0]['mem_total_gb'] == hardware['mem_total_gb'] == 64
    assert rows[0]['mem_assigned_gb'] == hardware['mem_allocated_gb'] == (40 if requested_gb == 24 else 0)
    cfg['resources']['tiers']['simple']['mem_gb'] = requested_gb
    save(cfg, rows)
    result = capacity.assess(cfg, 'default', 'simple', now=NOW)
    assert (result['fits_total'], result['availability']) == (fit, expected)


@pytest.mark.parametrize('missing', ['capacity_cpu_consistent', 'mem_total_bytes', 'mem_assigned_bytes', 'all'])
@pytest.mark.parametrize('assigned,requested_gb', [(0, 64), (40, 24)])
def test_old_pbs_cache_cannot_prove_boundary_capacity(cfg, missing, assigned, requested_gb):
    row = node(mem_total_gb=64, mem_assigned_gb=assigned)
    for key in ('capacity_cpu_consistent', 'mem_total_bytes', 'mem_assigned_bytes'):
        if missing in (key, 'all'):
            del row[key]
    save(cfg, [row])
    cfg['resources']['tiers']['simple']['mem_gb'] = requested_gb
    assert capacity.assess(cfg, 'default', 'simple', now=NOW)['availability'] == 'unknown'


def test_torque_request_sum_preserves_capacity_precision_and_precedence():
    raw = ('node-a\n    state = free\n    np = 32\n    status = physmem=65536mb\n'
           '    jobs = 0-1/101.fixture, 2-3/102.fixture\n')
    jobs = [dict(job_id=f'{101 + i}.fixture', job_state='R', exec_host=f'node-a/{2*i}-{2*i+1}',
                 **{'Resource_List.mem': f'{20481 - i}mb'}) for i in range(2)]
    row = pbs.parse_nodes(raw, jobs)[0]
    assert row['mem_total_gb'] == 64 and row['mem_assigned_gb'] == 40
    assert row['mem_assigned_bytes'] == 40961 * 1024**2
    assert capacity.evaluate_node(row, 8, 24, scheduler='pbs')['availability'] == 'queue'
    raw += '    resources_available.mem = 65gb\n    resources_assigned.mem = 7gb\n'
    row = pbs.parse_nodes(raw, jobs)[0]
    assert row['mem_total_bytes'] == 65 * 1024**3 and row['mem_assigned_bytes'] == 7 * 1024**3
    row = pbs.parse_nodes(raw.replace('7gb', 'invalid'), jobs)[0]
    assert row['mem_assigned_gb'] is None and row['mem_assigned_bytes'] is None
    jobs[0]['Resource_List.mem'] = 'invalid'
    row = pbs.parse_nodes(raw.split('    resources_available.mem')[0], jobs)[0]
    assert row['mem_assigned_gb'] is None and row['mem_assigned_bytes'] is None


@pytest.mark.parametrize('value,expected', [('0gb', 0), ('1b', 1), ('1KB', 1024),
    ('65535mb', 65535 * 1024**2), ('1.5gb', 3 * 1024**3 // 2), ('0.0625tb', 64 * 1024**3),
    ('0.5b', None), ('63.999999999999999999999999999999999gb', None),
    ('invalid', None), ('-1gb', None), ('nangb', None), (None, None)])
def test_pbs_capacity_memory_units(value, expected):
    assert pbs.memory_bytes(value) == expected
