"""Single-node advice uses synthetic scheduler records and local files only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from ag import capacity, cli, config, monitor, remote, slurm
from ag.transport import SSHTransport, Result
from test_core import cfg
from test_slurm import multi, SlurmFake


NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def node(name='node-a', **values):
    return dict(dict(name=name, state='free', cores_total=44, cores_used=0,
                     mem_total_gb=120, mem_assigned_gb=0), **values)


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
