"""Routing uses synthetic snapshots only and never creates a transport."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import io
import os
from pathlib import Path
import subprocess

import pytest

from ag import attempt, capacity, cli, config, monitor, route, study
from ag.transport import SSHTransport
from test_core import cfg, INPUT, write_config


NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


@pytest.fixture
def routed(cfg):
    entry = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
    entries = {n: deepcopy(entry) for n in ('default', 'newhpc', 'scnet', 'scnet-test')}
    for name, selected in entries.items():
        selected['ssh']['host'] = 'synthetic-' + name
        selected['resources']['max_committed_cores'] = 88
    for name in ('scnet', 'scnet-test'):
        entries[name].update(scheduler='slurm', partition='synthetic')
        entries[name]['ssh']['host'] = 'synthetic-shared'
    entries['scnet-test']['allowed_templates'] = ['crest', 'xtb']
    raw = dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters=entries,
               routing=dict(gaussian=['default', 'newhpc', 'scnet'],
                            crest=['scnet-test', 'default', 'newhpc']))
    for name in entries:
        save(raw, name)
    return raw


def snapshot(raw, name, *, running=0, queued=0, others=0, idle=88, memory=240):
    selected = config.select_cluster(raw, name)
    result = monitor.empty_snapshot(selected, 60)
    result.update(sampled_at=NOW.isoformat(), last_ok_at=NOW.isoformat(), ok=True)
    result['own'].update(cores_running=running, cores_queued=queued, cores_in_use=running + queued)
    result['cluster'].update(
        job_summary=dict(monitor.empty_summary(), others_queued_jobs=others),
        hardware=dict(monitor.empty_hardware('sinfo' if name.startswith('scnet') else 'pbsnodes'),
                      cores_total=88, cores_allocated=88-idle, cores_idle=idle,
                      mem_total_gb=memory, mem_allocated_gb=0),
        nodes=[dict(name='node-a', state=('idle' if idle == 88 else 'mixed')
                    if config.scheduler_kind(selected) == 'slurm' else 'free',
                    partition=selected.get('partition'), partition_state='up',
                    cores_total=88, cores_used=88-idle, cores_idle=idle, cores_other=0,
                    mem_total_gb=memory, mem_assigned_gb=0, capacity_cpu_consistent=True,
                    mem_total_bytes=memory * 1024**3 if type(memory) is int else None,
                    mem_assigned_bytes=0)])
    return result


def save(raw, name, data=None, **kwargs):
    root = Path(raw['local']['studies_root']) / '.ag-monitor'
    if 'clusters' in raw:
        root /= name
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'latest.json'
    path.write_text(json.dumps(data if data is not None else snapshot(raw, name, **kwargs)))
    return path


def suggest(raw, template='gaussian', tier='general', **kwargs):
    return route.suggest(raw, template, tier, now=NOW, **kwargs)


def row(result, name='default'):
    return next(r for r in result['clusters'] if r['name'] == name)


def test_default_then_newhpc(routed):
    assert suggest(routed)['recommendation']['name'] == 'default'
    save(routed, 'default', idle=0)
    result = suggest(routed)
    assert result['recommendation']['name'] == 'newhpc'
    assert row(result)['conclusion'] == route.FULL
    assert '当前分配或占用不足' in ' '.join(row(result)['reasons'])


@pytest.mark.parametrize('status_,selectable,option_selectable,expected', [
    ('occupied', True, True, True), ('available', False, True, False),
    ('occupied', None, None, False), ('available', None, None, True),
    ('occupied', True, False, False)])
def test_target_candidate_optional_selectability(routed, monkeypatch, status_, selectable,
                                                option_selectable, expected):
    from ag import node_targeting
    routed['clusters']['default']['node_targeting'] = dict(
        allowed_nodes=['compute-a'], denied_nodes=[], restricted_nodes=[], priority=[['compute-a']])
    data = snapshot(routed, 'default')
    data['cluster']['nodes'][0]['name'] = 'compute-a'
    save(routed, 'default', data)
    option = dict(tier='general')
    candidate = dict(name='compute-a', status=status_, options=[option])
    if selectable is not None:
        candidate['selectable'] = selectable
    if option_selectable is not None:
        option['selectable'] = option_selectable
    monkeypatch.setattr(node_targeting, 'candidates', lambda *a, **kw: dict(nodes=[candidate]))
    result = suggest(routed)
    reasons = row(result)['reasons']
    assert ('没有满足此档位的具名节点候选' not in reasons) is expected
    assert row(result)['specification_allowed'] is expected
    assert row(result)['node_candidates']['nodes'][0]['status'] == status_
    assert (result['recommendation']['name'] == 'default') is expected


@pytest.mark.parametrize('kind', ['others', 'total', 'queue', 'running', 'single', 'memory', 'not-free'])
def test_capacity_reasons(routed, kind):
    data = snapshot(routed, 'default')
    resources = routed['clusters']['default']['resources']
    if kind == 'others':
        data['cluster']['job_summary']['others_queued_jobs'] = 1
    elif kind == 'total':
        data['own'].update(cores_running=70, cores_in_use=70)
    elif kind == 'queue':
        resources['max_queued_cores'] = 20
    elif kind == 'running':
        resources['scheduler_max_running_cores'] = 20
    elif kind == 'single':
        resources['max_cores'] = 20
    elif kind == 'memory':
        data['cluster']['nodes'][0]['mem_total_gb'] = 40
        data['cluster']['nodes'][0]['mem_total_bytes'] = 40 * 1024**3
    else:
        data['cluster']['nodes'][0]['state'] = 'offline'
    save(routed, 'default', data)
    result = suggest(routed)
    assert result['recommendation']['name'] == 'newhpc'
    assert row(result)['conclusion'] == route.FULL
    expected = '本人上限' if kind in ('total', 'queue', 'running', 'single') else {
        'others': '他人排队', 'memory': '单节点总核数或总内存', 'not-free': '状态'}[kind]
    assert expected in ' '.join(row(result)['reasons'])


@pytest.mark.parametrize('kind', ['expired', 'failed', 'future', 'interval', 'missing-nodes',
    'missing-summary', 'unknown-cores', 'missing-memory', 'missing-own', 'invalid-own',
    'bad-schema', 'removed', 'identity', 'bad-json', 'list', 'missing', 'symlink'])
def test_unknown_snapshots(routed, kind, tmp_path):
    data = snapshot(routed, 'default')
    if kind == 'expired':
        data['sampled_at'] = (NOW - timedelta(seconds=181)).isoformat()
    elif kind == 'future':
        data['sampled_at'] = (NOW + timedelta(seconds=1)).isoformat()
    elif kind == 'failed':
        data.update(ok=False, error='private-error-marker')
    elif kind == 'interval':
        data['interval_seconds'] = None
    elif kind == 'missing-nodes':
        del data['cluster']['nodes']
    elif kind == 'missing-summary':
        del data['cluster']['job_summary']
    elif kind == 'unknown-cores':
        data['cluster']['nodes'][0]['cores_total'] = None
        data['cluster']['hardware']['cores_idle'] = None
    elif kind == 'missing-memory':
        del data['cluster']['nodes'][0]['mem_total_gb']
        del data['cluster']['nodes'][0]['mem_total_bytes']
    elif kind == 'missing-own':
        del data['own']['cores_queued']
    elif kind == 'invalid-own':
        data['own']['cores_in_use'] = 1
    elif kind == 'bad-schema':
        data['schema'] = 'old'
    elif kind == 'removed':
        data['config_removed'] = True
    elif kind == 'identity':
        data['cluster']['name'] = 'newhpc'
    path = save(routed, 'default', data)
    if kind == 'bad-json':
        path.write_text('{private-error-marker')
    elif kind == 'list':
        path.write_text('[]')
    elif kind == 'missing':
        path.unlink()
    elif kind == 'symlink':
        target = tmp_path / 'private-target'
        path.rename(target)
        path.symlink_to(target)
    result = suggest(routed)
    assert row(result)['conclusion'] == route.FULL
    assert route.UNKNOWN in ' '.join(row(result)['reasons'])
    assert 'private-' not in json.dumps(result)


def test_freshness_boundary(routed):
    data = snapshot(routed, 'default')
    data['sampled_at'] = (NOW - timedelta(seconds=180)).isoformat()
    save(routed, 'default', data)
    assert row(suggest(routed))['conclusion'] == route.READY


@pytest.mark.parametrize('name', ['default', 'scnet'])
def test_unknown_memory_is_advisory(routed, name):
    save(routed, name, memory=None)
    result = suggest(routed)
    assert row(result, name)['conclusion'] == route.FULL
    assert row(result, name)['capacity']['availability'] == 'unknown'
    assert row(result, name)['personal_allowed'] and row(result, name)['specification_allowed']


def test_pbs_requires_one_node_not_sum(routed):
    data = snapshot(routed, 'default')
    node = data['cluster']['nodes'][0]
    node.update(cores_total=16, cores_used=0)
    data['cluster']['nodes'] = [dict(node, name=f'node-{i}') for i in range(4)]
    save(routed, 'default', data)
    assert row(suggest(routed))['conclusion'] == route.FULL


def test_slurm_memory_and_unknown_cpu(routed):
    save(routed, 'scnet', memory=40)
    assert '请求超过单节点总核数或总内存' in row(suggest(routed), 'scnet')['reasons']
    data = snapshot(routed, 'scnet')
    data['cluster']['hardware'].update(cores_idle=None, error='private-error-marker')
    data['cluster']['nodes'][0]['cores_idle'] = None
    save(routed, 'scnet', data)
    assert row(suggest(routed), 'scnet')['conclusion'] == route.FULL


@pytest.mark.parametrize('template', ['crest', 'xtb', 'gaussian', 'gaussian-cp', 'multiwfn'])
def test_template_families_and_programs(routed, template):
    result = suggest(routed, template)
    if template in ('crest', 'xtb'):
        assert result['recommendation']['name'] == 'scnet-test'
    elif template == 'multiwfn':
        assert result['recommendation'] is None
        for entry in routed['clusters'].values():
            entry['programs']['multiwfn'] = '/synthetic/Multiwfn'
        result = suggest(routed, template)
        assert result['recommendation']['name'] == 'default'
        assert row(result, 'newhpc')['conclusion'] == route.DENIED
        assert row(result, 'scnet')['conclusion'] == route.DENIED
    else:
        assert result['recommendation']['name'] == 'default'
        assert row(result, 'scnet-test')['conclusion'] == route.DENIED
    del routed['clusters']['default']['programs']['gaussian']
    assert row(suggest(routed))['conclusion'] == route.DENIED


def test_shared_usage_once_and_minimum_caps(routed):
    save(routed, 'scnet', running=30)
    save(routed, 'scnet-test', running=30)
    routed['clusters']['scnet']['resources']['max_committed_cores'] = 60
    result = suggest(routed, 'crest')
    assert result['recommendation']['name'] == 'scnet-test'  # 30 + 22, not 60 + 22
    routed['clusters']['scnet']['resources']['max_committed_cores'] = 44
    assert not row(suggest(routed, 'crest'), 'scnet-test')['personal_allowed']
    routed['clusters']['scnet']['resources']['max_committed_cores'] = 88
    routed['clusters']['scnet']['resources']['max_queued_cores'] = 20
    assert not row(suggest(routed, 'crest'), 'scnet-test')['personal_allowed']


def test_shared_newest_valid_own_and_stale_hardware(routed):
    old = snapshot(routed, 'scnet', running=80)
    old['sampled_at'] = (NOW - timedelta(seconds=1)).isoformat()
    save(routed, 'scnet', old)
    assert row(suggest(routed), 'scnet')['personal_allowed']
    failed = snapshot(routed, 'scnet-test', running=80)
    failed['ok'] = False
    save(routed, 'scnet-test', failed)
    assert not row(suggest(routed), 'scnet')['personal_allowed']
    save(routed, 'scnet', running=0)
    result = suggest(routed, 'crest')
    assert row(result, 'scnet-test')['personal_allowed']
    assert row(result, 'scnet-test')['conclusion'] == route.FULL
    assert result['recommendation']['name'] == 'default'


def test_queue_fallback_and_no_eligible_entry(routed):
    for name in routed['clusters']:
        save(routed, name, idle=0)
    result = suggest(routed)
    assert result['recommendation']['name'] == 'default'
    assert result['recommendation']['needs_queue']
    assert result['message'] == '快照下建议排队：default'
    save(routed, 'default', idle=0, running=88)
    assert suggest(routed)['recommendation']['name'] == 'newhpc'
    for name in routed['clusters']:
        save(routed, name, idle=0, running=88)
    assert suggest(routed)['recommendation'] is None


def test_study_override_no_routing_and_empty_order(routed):
    routed['routing']['studies'] = {'water': {'gaussian': ['scnet', 'default']}}
    assert suggest(routed, study='water')['recommendation']['name'] == 'scnet'
    assert suggest(routed, 'crest', study='water')['recommendation']['name'] == 'scnet-test'
    routed['routing']['gaussian'] = []
    assert suggest(routed)['recommendation'] is None
    del routed['routing']
    result = suggest(routed)
    assert result['message'] == '未配置路由顺序'
    assert result['recommendation'] is None and len(result['clusters']) == 4


@pytest.mark.parametrize('routing', [None, [], {'typo': []}, {'gaussian': 'default'},
    {'gaussian': ['missing']}, {'gaussian': ['default', 'default']}, {'crest': [True]},
    {'studies': []}, {'studies': {'water': {'crest': ['missing']}}},
    {'studies': {'../bad': {'crest': ['default']}}}])
def test_config_rejects_invalid_routing(cfg, routing):
    cfg['routing'] = routing
    with pytest.raises(config.ConfigError):
        config.validate_routing(cfg)
    if not isinstance(routing, dict):
        return  # TOML has no null; the shared writer only serializes tables.
    path = write_config(cfg)
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_config_accepts_legacy_and_named_study_orders(routed, cfg, tmp_path):
    routed['routing']['studies'] = {'water': {'gaussian': ['default']}}
    assert config.load_config(write_config(routed))['routing'] == routed['routing']
    cfg['routing'] = {'gaussian': ['default']}
    cfg['local'] = {'studies_root': str(tmp_path / 'legacy-studies')}
    assert config.load_config(write_config(cfg))['routing'] == cfg['routing']
    save(cfg, 'default')
    assert suggest(cfg)['recommendation']['name'] == 'default'
    named = Path(cfg['local']['studies_root']) / '.ag-monitor/default/latest.json'
    named.parent.mkdir()
    named.write_text('{}')
    assert row(suggest(cfg))['conclusion'] == route.FULL


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '100'])
def test_invalid_memory_is_not_the_g7_exception(routed, value):
    data = snapshot(routed, 'scnet', memory=None)
    data['cluster']['nodes'][0]['mem_assigned_gb'] = value
    save(routed, 'scnet', data)
    assert row(suggest(routed), 'scnet')['conclusion'] == route.FULL


def test_entry_specific_tier_and_study_only_order(routed):
    routed['clusters']['default']['resources']['tiers']['general']['cores'] = 44
    save(routed, 'default', idle=30)
    save(routed, 'newhpc', idle=30)
    assert suggest(routed)['recommendation']['name'] == 'newhpc'
    routed['routing'] = {'studies': {'water': {'gaussian': ['newhpc']}}}
    assert suggest(routed)['message'] == '未配置路由顺序'
    assert suggest(routed, study='water')['recommendation']['name'] == 'newhpc'


def test_missing_cache_does_not_create_directory(cfg, tmp_path, monkeypatch, capsys):
    cfg['routing'] = {'gaussian': ['default']}
    monkeypatch.setattr(route, 'load_config', lambda: cfg)
    before = tree(tmp_path)
    assert cli.main(['route', '--template', 'gaussian', '--tier', 'mini', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['recommendation'] is None
    assert not Path(cfg['local']['studies_root']).exists()
    assert tree(tmp_path) == before


@pytest.mark.parametrize('walltime', [None, '00:30:00'])
@pytest.mark.parametrize('targeted', [False, True])
def test_cli_read_only_and_allowlisted_output(routed, tmp_path, monkeypatch, capsys, walltime, targeted):
    routed['clusters']['default']['display_name'] = '合成入口'
    data = snapshot(routed, 'default')
    data['cluster']['jobs'] = [{'user': 'private-marker', 'queue': 'private-marker'}]
    if targeted:
        from ag import node_targeting  # Load before forbidding filesystem operations.
        entry = routed['clusters']['default']
        entry['node_targeting'] = dict(allowed_nodes=['node-a'], denied_nodes=[],
                                       restricted_nodes=[], priority=[['node-a']])
        entry['resources']['tiers']['general'] = dict(cores=24, mem_gb=48)
        data['cluster']['nodes'][0].update(cores_total=48, jobs=0,
                                          targeting_consistent=True, targeting_reserved=True)
    else:
        data['cluster']['nodes'][0].update(cpu_source='private-marker', memory_source='private-marker')
    save(routed, 'default', data)
    monkeypatch.setattr(route, 'load_config', lambda: routed)
    original = route.suggest
    monkeypatch.setattr(route, 'suggest', lambda *a, **kw: original(*a, **kw, now=NOW))
    def forbidden(*args, **kwargs):
        pytest.fail('route must not construct transports or run subprocesses')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    original_open = io.open
    def read_only(file, mode='r', *args, **kwargs):
        if any(flag in mode for flag in ('w', 'a', 'x', '+')):
            forbidden()
        return original_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(io, 'open', read_only)
    for operation in ('mkdir', 'rename', 'replace', 'unlink', 'open'):
        monkeypatch.setattr(os, operation, forbidden)
    before = tree(tmp_path)
    options = ['route', '--template', 'gaussian', '--tier', 'general', '--study', 'water']
    if walltime is not None:
        options += ['--walltime', walltime]
    assert cli.main([*options, '--json']) == 0
    captured = capsys.readouterr()
    assert not captured.err and 'private-marker' not in captured.out
    result = json.loads(captured.out)
    assert result['recommendation']['name'] == 'default'
    assert cli.main(options) == 0
    text = capsys.readouterr().out
    assert '合成入口（default）' in text and text.endswith('建议：default\n')
    assert tree(tmp_path) == before


def test_prepare_hint_preserves_manifest_and_json(routed, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'load_config', lambda: routed)
    original = route.suggest
    monkeypatch.setattr(route, 'suggest', lambda *a, **kw: original(*a, **kw, now=NOW))
    study.init(routed, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    args = ['prepare', '--study', 'water', '--template', 'gaussian', '--input', str(source),
            '--tier', 'simple', '--walltime', '00:30:00', '--label', 'sp',
            '--method-basis', '兜底方法：合成测试', '--cluster', 'newhpc']
    assert cli.main(args) == 0
    text = capsys.readouterr().out
    assert '路由建议为 default（快照下容量足够' in text
    assert text.endswith(f'本次按 --cluster newhpc 准备。{route.DISCLAIMER}\n')
    path = attempt.find(routed, 'water-001-sp')
    before = tree(path)
    manifest = attempt.read_manifest(path)
    assert manifest['cluster'] == 'newhpc'
    assert not any('rout' in key for key in manifest)
    assert route.prepare_hint(routed, dict(manifest, cluster='default')) == ''
    attempt.summary(routed, manifest)
    assert tree(path) == before
    assert cli.main([*args, '--json']) == 0
    manifest_json = json.loads(capsys.readouterr().out)
    assert manifest_json == attempt.read_manifest(attempt.find(routed, 'water-002-sp'))
    for name in routed['clusters']:
        save(routed, name, dict(snapshot(routed, name), ok=False))
    assert route.prepare_hint(routed, manifest) == ''
    del routed['routing']
    assert route.prepare_hint(routed, manifest) == ''


@pytest.mark.parametrize('requested,maximum,status', [
    ('00:00:01', '00:00:01', 'within_limit'),
    ('00:29:59', '00:30:00', 'within_limit'),
    ('00:30:00', '00:30:00', 'within_limit'),
    ('00:30:01', '00:30:00', 'exceeded'),
    ('9999:59:59', '9999:59:59', 'within_limit'),
    ('9999:59:59', None, 'unknown_limit'),
    (None, '00:30:00', 'not_checked'),
    (None, None, 'not_checked'),
])
def test_walltime_boundaries_and_optional_limits(routed, requested, maximum, status):
    resources = routed['clusters']['default']['resources']
    if maximum is not None:
        resources['max_walltime'] = maximum
    result = suggest(routed, walltime=requested)
    entry = row(result)
    assert entry['walltime'] == dict(requested=requested, maximum=maximum, status=status)
    assert entry['specification_allowed'] is (status != 'exceeded')
    assert result['walltime'] == requested and route.DISCLAIMER in route.format_result(result)
    if requested is None:
        assert '未核对任务时限' in ' '.join(entry['notes'])
    elif maximum is None:
        assert '不代表无限制' in ' '.join(entry['notes'])


@pytest.mark.parametrize('requested', ['', True, 1, [], '00:00:00', '0:30:00',
    '10000:00:00', '00:60:00', '00:00:60', '-1:00:00', '00:30', '00:30:00\n', ' 00:30:00'])
def test_invalid_walltime_rejected_before_snapshot_reads(routed, monkeypatch, requested):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid walltime must fail before reading snapshots')
    monkeypatch.setattr(route, '_snapshot', forbidden)
    with pytest.raises(ValueError, match='positive HH:MM:SS'):
        suggest(routed, walltime=requested)


@pytest.mark.parametrize('busy', [False, True])
def test_walltime_excluded_from_ready_and_queue_fallback(routed, busy):
    for name in routed['clusters']:
        routed['clusters'][name]['resources']['max_walltime'] = '00:30:00'
        save(routed, name, idle=0 if busy else 88)
    routed['clusters']['newhpc']['resources']['max_walltime'] = '01:00:00'
    result = suggest(routed, walltime='00:45:00')
    assert result['recommendation']['name'] == 'newhpc'
    assert result['recommendation']['needs_queue'] is busy
    assert row(result)['conclusion'] == route.DENIED
    routed['clusters']['newhpc']['resources']['max_walltime'] = '00:30:00'
    result = suggest(routed, walltime='00:45:00')
    assert result['recommendation'] is None
    assert all(not r['specification_allowed'] for r in result['clusters'])


def test_time_limits_come_from_current_configuration_and_are_entry_specific(routed):
    # Shared-account minimums apply to account quotas, not each partition's walltime.
    routed['routing']['crest'] = ['scnet-test', 'scnet']
    for name in ('scnet', 'scnet-test'):
        data = snapshot(routed, name)
        data['own']['max_walltime'] = '00:01:00'
        save(routed, name, data)
    routed['clusters']['scnet-test']['resources']['max_walltime'] = '00:30:00'
    routed['clusters']['scnet']['resources']['max_walltime'] = '02:00:00'
    result = suggest(routed, 'crest', walltime='01:00:00')
    assert result['recommendation']['name'] == 'scnet'
    del routed['clusters']['scnet-test']['resources']['max_walltime']
    assert suggest(routed, 'crest', walltime='01:00:00')['recommendation']['name'] == 'scnet-test'
    routed['routing']['studies'] = {'water': {'crest': ['scnet']}}
    assert suggest(routed, 'crest', study='water', walltime='01:00:00')['recommendation']['name'] == 'scnet'


@pytest.mark.parametrize('name', ['default', 'scnet'])
def test_capacity_reuses_single_node_result_not_hardware_sum(routed, name):
    routed['routing']['gaussian'] = [name]
    data = snapshot(routed, name)
    original = data['cluster']['nodes'][0]
    small_cpu = dict(original, name='node-cpu', cores_total=16, cores_idle=16, cores_used=0)
    small_memory = dict(original, name='node-memory', mem_total_gb=32, mem_total_bytes=32 * 1024**3)
    data['cluster']['nodes'] = [small_cpu, small_memory]
    save(routed, name, data)
    expected = capacity.assess(routed, name, 'general', now=NOW)
    result = suggest(routed)
    assert row(result, name)['capacity']['availability'] == expected['availability'] == 'not_applicable'
    assert result['recommendation'] is None
    data['cluster']['nodes'].append(dict(original, name='node-large'))
    save(routed, name, data)
    assert suggest(routed)['recommendation']['needs_queue'] is False


@pytest.mark.parametrize('kind', ['busy', 'unknown-memory', 'old-pbs', 'old-slurm', 'stale'])
def test_legal_requests_keep_queue_or_unknown_advice(routed, kind):
    name = 'scnet' if kind == 'old-slurm' else 'default'
    routed['routing']['gaussian'] = [name]
    data = snapshot(routed, name, idle=0 if kind == 'busy' else 88)
    if kind == 'unknown-memory':
        data['cluster']['nodes'][0]['mem_assigned_bytes'] = None
    elif kind == 'old-pbs':
        del data['cluster']['nodes'][0]['capacity_cpu_consistent']
    elif kind == 'old-slurm':
        del data['cluster']['nodes']
    elif kind == 'stale':
        data['sampled_at'] = (NOW - timedelta(seconds=181)).isoformat()
    save(routed, name, data)
    result = suggest(routed, walltime='01:00:00')
    entry = row(result, name)
    assert entry['specification_allowed']
    assert entry['capacity']['availability'] == ('queue' if kind == 'busy' else 'unknown')
    if kind == 'stale':
        assert result['recommendation'] is None  # Unknown own usage still cannot pass.
    else:
        assert result['recommendation']['needs_queue']
        assert ('容量未知' in result['recommendation']['reason']) is (kind != 'busy')


def test_prepare_hint_uses_saved_tier_and_walltime(routed, tmp_path, monkeypatch):
    study.init(routed, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    routed['clusters']['newhpc']['resources']['default_tier'] = 'simple'
    manifest = attempt.prepare(routed, study_name='water', template='gaussian', input_path=source,
                               walltime='01:00:00', label='sp', cluster='newhpc', method_basis='synthetic')
    routed['clusters']['newhpc']['resources']['default_tier'] = 'general'
    routed['clusters']['default']['resources']['max_walltime'] = '00:30:00'
    original, observed = route.suggest, []
    def capture(cfg, template, tier, study, **kwargs):
        observed.append((tier, kwargs['walltime']))
        return original(cfg, template, tier, study, now=NOW, **kwargs)
    monkeypatch.setattr(route, 'suggest', capture)
    before = tree(tmp_path)
    saved = deepcopy(manifest)
    assert route.prepare_hint(routed, manifest) == ''  # Actual walltime excludes default.
    assert observed == [('simple', '01:00:00')]
    assert manifest == saved and tree(tmp_path) == before


@pytest.mark.parametrize('error', [OSError, ValueError, KeyError, TypeError, AttributeError,
                                 RecursionError, RuntimeError, OverflowError])
def test_hint_failure_cannot_fail_successful_prepare(routed, tmp_path, monkeypatch, capsys, error):
    study.init(routed, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    monkeypatch.setattr(cli, 'load_config', lambda: routed)
    def failed(*args, **kwargs):
        raise error('private-hint-error')
    monkeypatch.setattr(route, 'suggest', failed)
    assert cli.main(['prepare', '--study', 'water', '--template', 'gaussian', '--input', str(source),
                     '--tier', 'simple', '--walltime', '00:30:00', '--label', 'sp',
                     '--method-basis', 'synthetic water fixture', '--cluster', 'newhpc']) == 0
    assert 'private-hint-error' not in capsys.readouterr().out
    path = attempt.find(routed, 'water-001-sp')
    manifest = attempt.read_manifest(path)
    before = tree(path)
    assert route.prepare_hint(routed, manifest) == ''
    assert tree(path) == before
    assert json.loads((path / 'status.json').read_text())['state'] == 'prepared'
    assert attempt.bundle(attempt.verified_files(routed, path, manifest))[1] == manifest['bundle_sha256']


def test_route_cli_walltime_and_explicit_tier(routed, monkeypatch, capsys):
    monkeypatch.setattr(route, 'load_config', lambda: routed)
    routed['clusters']['default']['resources']['default_tier'] = 'simple'
    with pytest.raises(SystemExit) as error:
        cli.main(['route', '--template', 'gaussian', '--walltime', '01:00:00'])
    assert error.value.code == 2
    capsys.readouterr()
    original = route.suggest
    monkeypatch.setattr(route, 'suggest', lambda *a, **kw: original(*a, **kw, now=NOW))
    assert cli.main(['route', '--template', 'gaussian', '--tier', 'general',
                     '--walltime', '01:00:00', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['walltime'] == '01:00:00'
    assert result['clusters'][0]['walltime']['status'] == 'unknown_limit'


@pytest.fixture
def targeted_routed(routed):
    entry = routed['clusters']['default']
    entry['resources']['tiers'].update(mini=dict(cores=12, mem_gb=24),
                                       general=dict(cores=24, mem_gb=48))
    entry['resources']['max_walltime'] = '04:00:00'
    entry['node_targeting'] = dict(allowed_nodes=['node-a', 'node-b'], denied_nodes=[],
                                    restricted_nodes=[], priority=[['node-a'], ['node-b']])
    data = snapshot(routed, 'default')
    node = data['cluster']['nodes'][0]
    node.update(cores_total=48, cores_used=4, mem_total_gb=128, mem_total_bytes=128 * 1024**3,
                mem_assigned_gb=8, mem_assigned_bytes=8 * 1024**3, jobs=1,
                targeting_consistent=True, targeting_reserved=False)
    data['cluster']['nodes'].append(dict(node, name='node-b', cores_used=0, jobs=0,
                                       mem_assigned_gb=0, mem_assigned_bytes=0))
    routed['routing']['gaussian'] = ['default']
    save(routed, 'default', data)
    return routed, data


@pytest.mark.parametrize('state,used,memory,reserved,availability', [
    ('free', 4, 8, False, 'enough'),
    ('free', 32, 64, False, 'queue'),
    ('job-busy', 48, 96, False, 'queue'),
    ('job-exclusive', 4, 8, False, 'queue'),
    ('free', 4, None, False, 'unknown'),
    ('free', 0, 0, True, 'enough'),
])
def test_shared_named_candidate_uses_option_capacity(targeted_routed, state, used, memory,
                                                    reserved, availability):
    routed, data = targeted_routed
    # A second node has abundant idle resources but no fraction mapped to this tier.
    data['cluster']['nodes'][1]['cores_total'] = 64
    node = data['cluster']['nodes'][0]
    node.update(state=state, cores_used=used, jobs=int(used > 0), targeting_reserved=reserved,
                mem_assigned_gb=memory, mem_assigned_bytes=None if memory is None else memory * 1024**3)
    save(routed, 'default', data)
    before = deepcopy(routed)
    result = suggest(routed, walltime='01:00:00')
    entry = row(result)
    candidate = entry['node_candidates']['nodes'][0]
    assert candidate['status'] == 'occupied' and candidate['selectable'] is True
    assert entry['specification_allowed']
    assert entry['capacity']['availability'] == availability
    matching = next(o for o in candidate['options'] if o['tier'] == 'general')
    assert matching['capacity']['availability'] == availability
    assert result['recommendation']['needs_queue'] is (availability != 'enough')
    assert routed == before


@pytest.mark.parametrize('kind', ['tier-mismatch', 'forbidden', 'restricted', 'offline',
                                  'inconsistent', 'unknown-total', 'stale', 'walltime'])
def test_no_named_candidate_cannot_enter_queue_fallback(targeted_routed, kind):
    routed, data = targeted_routed
    policy = routed['clusters']['default']['node_targeting']
    for node in data['cluster']['nodes']:
        if kind == 'tier-mismatch':
            node['cores_total'] = 64
        elif kind == 'offline':
            node['state'] = 'offline'
        elif kind == 'inconsistent':
            node['targeting_consistent'] = False
        elif kind == 'unknown-total':
            del node['mem_total_bytes']
    if kind in ('forbidden', 'restricted'):
        policy['denied_nodes' if kind == 'forbidden' else 'restricted_nodes'] = ['node-a', 'node-b']
    elif kind == 'stale':
        data['sampled_at'] = (NOW - timedelta(seconds=181)).isoformat()
    elif kind == 'walltime':
        routed['clusters']['default']['resources']['max_walltime'] = '00:30:00'
    save(routed, 'default', data)
    result = suggest(routed, walltime='01:00:00')
    assert result['recommendation'] is None
    assert not row(result)['specification_allowed']


def test_mapped_named_candidate_capacity_and_priority_preserved(targeted_routed):
    routed, data = targeted_routed
    data['cluster']['nodes'][0].update(cores_used=40, mem_assigned_gb=100,
                                      mem_assigned_bytes=100 * 1024**3)
    save(routed, 'default', data)
    result = suggest(routed, walltime='01:00:00')
    entry = row(result)
    assert entry['capacity']['availability'] == 'enough'  # The second mapped option fits.
    assert not result['recommendation']['needs_queue']
    assert [n['name'] for n in entry['node_candidates']['nodes']] == ['node-a', 'node-b']
    assert 'target_node' not in result['recommendation']  # Advice does not select a node.


@pytest.fixture
def ladder_config(cfg):
    cfg['routing'] = {'gaussian': ['default'], 'ladder': [dict(
        id='available-default', cluster='default', classes=['main'], tier='general',
        condition='free', min_free_cores=22, max_placements=1)]}
    return cfg


@pytest.mark.parametrize('condition,extra', [
    ('empty', {'max_placements': 2}), ('free', {'min_free_cores': 22}),
    ('jobs', {'max_jobs': 4}), ('queue', {}),
])
def test_ladder_config_valid_conditions_are_readonly(ladder_config, condition, extra, monkeypatch):
    cell = ladder_config['routing']['ladder'][0]
    del cell['min_free_cores']
    cell.update(condition=condition, **extra)
    before = deepcopy(ladder_config)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('configuration contacted a process'))
    config.validate_routing(ladder_config)
    assert ladder_config == before


@pytest.mark.parametrize('value', [None, {}, [], 'empty', [None], [[]], [{}]])
def test_ladder_config_requires_nonempty_cell_list(ladder_config, value):
    ladder_config['routing']['ladder'] = value
    with pytest.raises(config.ConfigError):
        config.validate_routing(ladder_config)


@pytest.mark.parametrize('key', ['id', 'cluster', 'classes', 'tier', 'condition', 'max_placements'])
def test_ladder_config_requires_declared_fields(ladder_config, key):
    del ladder_config['routing']['ladder'][0][key]
    with pytest.raises(config.ConfigError):
        config.validate_routing(ladder_config)


@pytest.mark.parametrize('patch', [
    {'typo': True}, {'id': '../unsafe'}, {'id': []}, {'cluster': 'missing'},
    {'classes': []}, {'classes': 'main'}, {'classes': ['main', 'main']},
    {'classes': ['unknown']}, {'classes': [True]}, {'classes': [[]]},
    {'tier': 'unconfigured'}, {'tier': 'ultra'}, {'tier': []},
    {'condition': 'typo'}, {'max_placements': 0}, {'max_placements': 3},
    {'max_placements': True}, {'max_placements': 1.0},
    {'min_free_cores': 21}, {'min_free_cores': True}, {'min_free_cores': None},
    {'max_jobs': 4}, {'nodes': ['compute-a']}, {'node_fraction': '1/2'},
])
def test_ladder_config_rejects_unsafe_cell_values(ladder_config, patch):
    ladder_config['routing']['ladder'][0].update(patch)
    with pytest.raises(config.ConfigError):
        config.validate_routing(ladder_config)


def test_ladder_config_rejects_duplicate_cell_identity(ladder_config):
    cells = ladder_config['routing']['ladder']
    cells.append(deepcopy(cells[0]))
    with pytest.raises(config.ConfigError):
        config.validate_routing(ladder_config)


@pytest.mark.parametrize('condition,extra', [
    ('empty', {'min_free_cores': 22}), ('queue', {'min_free_cores': 22}),
    ('jobs', {}), ('jobs', {'max_jobs': 0}), ('jobs', {'max_jobs': True}),
    ('jobs', {'max_jobs': 4, 'max_placements': 2}),
    ('jobs', {'max_jobs': 4, 'nodes': ['compute-a']}),
    ('jobs', {'max_jobs': 4, 'node_fraction': '1/2'}),
    ('queue', {'max_placements': 2}), ('queue', {'max_jobs': 4}),
])
def test_ladder_config_condition_fields_cannot_weaken_caps(ladder_config, condition, extra):
    cell = ladder_config['routing']['ladder'][0]
    del cell['min_free_cores']
    cell.update(condition=condition, **extra)
    with pytest.raises(config.ConfigError):
        config.validate_routing(ladder_config)


@pytest.mark.parametrize('field,value', [
    ('cores', 45), ('cores', 0), ('cores', True), ('cores', 22.0),
    ('mem_gb', 0), ('mem_gb', True), ('mem_gb', None),
])
def test_ladder_config_rejects_invalid_tier_resources(ladder_config, field, value):
    ladder_config['resources']['tiers']['general'][field] = value
    with pytest.raises(config.ConfigError):
        config.validate_routing(ladder_config)


@pytest.fixture
def targeting_ladder_config(ladder_config):
    ladder_config['node_targeting'] = dict(
        allowed_nodes=['compute-a', 'compute-b'], denied_nodes=[], restricted_nodes=[],
        priority=[['compute-a', 'compute-b']])
    cell = ladder_config['routing']['ladder'][0]
    cell.update(nodes=['compute-b', 'compute-a'], node_fraction='1/2')
    return ladder_config


@pytest.mark.parametrize('fraction', ['1/2', '1/4', '1'])
def test_ladder_config_accepts_target_fraction_and_preserves_order(targeting_ladder_config, fraction):
    cell = targeting_ladder_config['routing']['ladder'][0]
    cell['node_fraction'] = fraction
    before = deepcopy(targeting_ladder_config)
    config.validate_routing(targeting_ladder_config)
    assert targeting_ladder_config == before


@pytest.mark.parametrize('kind', ['missing-nodes', 'empty-nodes', 'duplicate-nodes',
    'unknown-node', 'invalid-node', 'missing-fraction', 'invalid-fraction', 'denied', 'restricted'])
def test_ladder_config_does_not_bypass_target_policy(targeting_ladder_config, kind):
    cell = targeting_ladder_config['routing']['ladder'][0]
    policy = targeting_ladder_config['node_targeting']
    if kind == 'missing-nodes':
        del cell['nodes']
    elif kind == 'empty-nodes':
        cell['nodes'] = []
    elif kind == 'duplicate-nodes':
        cell['nodes'] = ['compute-a', 'compute-a']
    elif kind == 'unknown-node':
        cell['nodes'] = ['compute-c']
    elif kind == 'invalid-node':
        cell['nodes'] = [True]
    elif kind == 'missing-fraction':
        del cell['node_fraction']
    elif kind == 'invalid-fraction':
        cell['node_fraction'] = '1/3'
    else:
        policy['denied_nodes' if kind == 'denied' else 'restricted_nodes'] = ['compute-a']
    with pytest.raises(config.ConfigError):
        config.validate_routing(targeting_ladder_config)


@pytest.mark.parametrize('layout', ['legacy', 'named', 'mixed'])
def test_ladder_load_config_before_cluster_normalization(cfg, layout):
    if layout == 'named':
        selected = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
        cfg = dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters={'default': selected})
    elif layout == 'mixed':
        selected = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
        cfg['clusters'] = {'secondary': selected}
    # The existing writer has no TOML array-of-tables support. Append the actual
    # syntax a user would configure, so this exercises the loader as well.
    path = write_config(cfg)
    with path.open('a') as handle:
        handle.write('\n[[routing.ladder]]\nid="single-node-fit"\ncluster="default"\n'
                     'classes=["main", "small"]\ntier="general"\ncondition="free"\n'
                     'min_free_cores=22\nmax_placements=1\n')
    loaded = config.load_config(path)
    assert loaded['routing']['ladder'][0]['cluster'] == 'default'
    assert config.select_cluster(loaded, 'default')['resources']['tiers']['general']['cores'] == 22


def test_optional_ladder_does_not_change_legacy_route_or_study_orders(routed):
    routed['routing']['studies'] = {'water': {'gaussian': ['newhpc', 'default']}}
    before = suggest(routed, study='water')
    routed['routing']['ladder'] = [dict(id='synthetic-cell', cluster='default',
        classes=['main'], tier='simple', condition='empty', max_placements=2)]
    config.validate_routing(routed)
    assert suggest(routed, study='water') == before
