"""T117 routing uses synthetic snapshots only and never creates a transport."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from ag import attempt, cli, config, monitor, route, study
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
        nodes=[dict(state='free', cores_total=88, cores_used=88-idle,
                    mem_total_gb=memory, mem_assigned_gb=0)])
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
    assert '空闲核数不足' in ' '.join(row(result)['reasons'])


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
    else:
        data['cluster']['nodes'][0]['state'] = 'offline'
    save(routed, 'default', data)
    result = suggest(routed)
    assert result['recommendation']['name'] == 'newhpc'
    assert row(result)['conclusion'] == route.FULL
    expected = '本人上限' if kind in ('total', 'queue', 'running', 'single') else {
        'others': '他人排队', 'memory': '内存不足', 'not-free': 'free 节点'}[kind]
    assert expected in ' '.join(row(result)['reasons'])


@pytest.mark.parametrize('kind', ['expired', 'failed', 'future', 'interval', 'missing-hardware',
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
    elif kind == 'missing-hardware':
        del data['cluster']['hardware']
    elif kind == 'missing-summary':
        del data['cluster']['job_summary']
    elif kind == 'unknown-cores':
        data['cluster']['nodes'][0]['cores_total'] = None
        data['cluster']['hardware']['cores_idle'] = None
    elif kind == 'missing-memory':
        del data['cluster']['nodes'][0]['mem_total_gb']
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
    assert row(result, name)['conclusion'] == route.READY
    assert row(result, name)['notes'] == ['内存未知']


def test_pbs_requires_one_node_not_sum(routed):
    data = snapshot(routed, 'default')
    node = data['cluster']['nodes'][0]
    node.update(cores_total=16, cores_used=0)
    data['cluster']['nodes'] = [deepcopy(node) for _ in range(4)]
    save(routed, 'default', data)
    assert row(suggest(routed))['conclusion'] == route.FULL


def test_slurm_memory_and_unknown_cpu(routed):
    save(routed, 'scnet', memory=40)
    assert '空闲内存不足' in row(suggest(routed), 'scnet')['reasons']
    data = snapshot(routed, 'scnet')
    data['cluster']['hardware'].update(cores_idle=None, error='private-error-marker')
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
    assert result['message'] == '都需要排队：建议排在 default'
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
    data['cluster']['hardware']['mem_allocated_gb'] = value
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


def test_cli_read_only_and_allowlisted_output(routed, tmp_path, monkeypatch, capsys):
    routed['clusters']['default']['display_name'] = '合成入口'
    data = snapshot(routed, 'default')
    data['cluster']['jobs'] = [{'user': 'private-marker', 'queue': 'private-marker'}]
    save(routed, 'default', data)
    monkeypatch.setattr(route, 'load_config', lambda: routed)
    original = route.suggest
    monkeypatch.setattr(route, 'suggest', lambda *a, **kw: original(*a, **kw, now=NOW))
    def forbidden(*args, **kwargs):
        pytest.fail('route must not construct transports or run subprocesses')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    before = tree(tmp_path)
    options = ['route', '--template', 'gaussian', '--tier', 'general', '--study', 'water']
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
    assert text.endswith('路由建议为 default（可以马上运行）；本次按 --cluster newhpc 准备。\n')
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
