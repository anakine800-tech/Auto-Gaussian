"""T142: entry-local PBS memory authorization, with synthetic data only."""
from copy import deepcopy
from pathlib import Path

import pytest

from ag import attempt, clusters, config, route, study
from ag.transport import SSHTransport
from test_core import cfg, INPUT
from test_gaussian_only import gaussian_only, load
from test_route import NOW, routed, save


@pytest.mark.parametrize('mode', ['legacy', 'pbs'])
def test_omitted_cap_preserves_120_and_does_not_add_default(cfg, mode):
    raw, name = gaussian_only(cfg, mode)
    loaded = load(raw)
    selected = config.select_cluster(loaded, name)
    assert 'pbs_max_mem_gb' not in selected['resources']
    assert selected['resources']['tiers']['complex']['mem_gb'] == 120
    resources = raw['resources'] if mode == 'legacy' else raw['clusters'][name]['resources']
    resources['tiers']['complex']['mem_gb'] = 121
    with pytest.raises(config.ConfigError, match='Invalid resource tier'):
        load(raw)


@pytest.mark.parametrize('mode', ['legacy', 'pbs'])
@pytest.mark.parametrize('ceiling', [120, 121, 180, 200])
def test_explicit_cap_allows_boundary_but_not_more(cfg, mode, ceiling):
    raw, name = gaussian_only(cfg, mode)
    resources = raw['resources'] if mode == 'legacy' else raw['clusters'][name]['resources']
    resources.update(pbs_max_mem_gb=ceiling)
    resources['tiers']['complex']['mem_gb'] = ceiling
    loaded = load(raw)
    assert config.select_cluster(loaded, name)['resources']['tiers']['complex']['mem_gb'] == ceiling
    resources['tiers']['complex']['mem_gb'] += 1
    with pytest.raises(config.ConfigError, match='Invalid resource tier'):
        load(raw)


@pytest.mark.parametrize('value', [True, False, 200.0, 120.5, '200', None, [], {},
                                 -1, 0, 119, 201, float('nan'), float('inf')])
def test_bad_explicit_cap_is_rejected(cfg, value):
    cfg['resources']['pbs_max_mem_gb'] = value
    with pytest.raises(config.ConfigError, match='pbs_max_mem_gb must be an integer from 120 to 200'):
        config.validate_cluster(cfg)


@pytest.mark.parametrize('tier', ['mini', 'simple', 'general', 'complex'])
@pytest.mark.parametrize('value', [True, 180.5, '180', 0, 201])
def test_existing_tier_validation_applies_with_authorization(cfg, tier, value):
    cfg['resources']['pbs_max_mem_gb'] = 200
    cfg['resources']['tiers'][tier]['mem_gb'] = value
    with pytest.raises(config.ConfigError, match='Invalid resource tier'):
        config.validate_cluster(cfg)


def test_slurm_keeps_existing_memory_behavior_and_rejects_pbs_field(cfg):
    raw, name = gaussian_only(cfg, 'slurm')
    resources = raw['clusters'][name]['resources']
    resources['tiers']['complex']['mem_gb'] = 512
    loaded = load(raw)
    assert config.select_cluster(loaded, name)['resources']['tiers']['complex']['mem_gb'] == 512
    resources['pbs_max_mem_gb'] = 200
    with pytest.raises(config.ConfigError, match='only supported for PBS'):
        load(raw)


def test_new_authorized_entry_leaves_other_entries_and_routing_unchanged(routed):
    before = load(routed)
    entry = deepcopy(routed['clusters']['default'])
    entry['ssh']['host'] = 'synthetic-high-memory'
    entry['resources']['pbs_max_mem_gb'] = 200
    entry['resources']['tiers']['complex']['mem_gb'] = 200
    routed['clusters']['high-memory'] = entry
    after = load(routed)
    assert after['routing'] == before['routing']
    for name, original in before['clusters'].items():
        assert after['clusters'][name] == original
        assert 'pbs_max_mem_gb' not in after['clusters'][name]['resources']
    assert [r for r in clusters.describe(after)['clusters'] if r['name'] != 'high-memory'] == (
        clusters.describe(before)['clusters'])
    routed['clusters']['default']['resources']['tiers']['complex']['mem_gb'] = 121
    with pytest.raises(config.ConfigError, match='Invalid resource tier'):
        load(routed)


@pytest.mark.parametrize('mode', ['legacy', 'pbs'])
def test_gaussian_only_200gb_prepare_render_discovery_and_route(cfg, tmp_path, monkeypatch, mode):
    raw, name = gaussian_only(cfg, mode)
    resources = raw['resources'] if mode == 'legacy' else raw['clusters'][name]['resources']
    resources['pbs_max_mem_gb'] = 200
    resources['tiers']['complex'] = {'cores': 8, 'mem_gb': 200}
    raw['routing'] = {'gaussian': [name]}
    loaded = load(raw)

    def no_connection(*args, **kwargs):
        pytest.fail('configuration, prepare, discovery and route must stay local')
    monkeypatch.setattr(SSHTransport, '__init__', no_connection)
    study.init(loaded, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace('%mem=10GB', '%mem=170GB'))
    manifest = attempt.prepare(
        loaded, study_name='water', template='gaussian', input_path=source,
        tier='complex', walltime='00:30:00', label='sp', cluster=name,
        method_basis='synthetic water fixture')
    path = attempt.find(loaded, manifest['attempt_id'])
    files = attempt.verified_files(loaded, path, manifest)
    assert manifest['mem_gb'] == 200 and manifest['cores'] == 8
    assert '#PBS -l mem=200gb\n' in files['job.pbs'].decode()
    assert '#PBS -l nodes=1:ppn=8\n' in files['job.pbs'].decode()
    assert files['water.gjf'] == source.read_bytes()
    assert 'GAUSS_SCRDIR="$scratch"' in files['job.pbs'].decode()
    assert not (path / '.submit-claim').exists()
    assert clusters.describe(loaded)['clusters'][0]['resources']['tiers']['complex'] == (
        {'cores': 8, 'mem_gb': 200})

    save(loaded, name, memory=256)
    advice = route.suggest(loaded, 'gaussian', 'complex', now=NOW)
    assert advice['clusters'][0]['mem_gb'] == 200
    assert advice['clusters'][0]['conclusion'] == route.READY
    save(loaded, name, memory=199)
    assert route.suggest(loaded, 'gaussian', 'complex', now=NOW)['clusters'][0]['conclusion'] == route.FULL
    assert route.suggest(loaded, 'xtb', 'complex', now=NOW)['clusters'][0]['conclusion'] == route.DENIED

    preserved = {p.name: p.read_bytes() for p in (path / 'inputs').iterdir()}
    original_manifest = (path / 'manifest.json').read_bytes()
    resources.pop('pbs_max_mem_gb')
    resources['tiers']['complex']['mem_gb'] = 120
    reverted = load(raw)
    with pytest.raises(ValueError, match='Resource configuration changed'):
        attempt.verified_files(reverted, path, manifest)
    assert {p.name: p.read_bytes() for p in (path / 'inputs').iterdir()} == preserved
    assert (path / 'manifest.json').read_bytes() == original_manifest


@pytest.mark.parametrize('memory', ['171GB', '170001MB'])
def test_gaussian_over_85_percent_rejected_before_attempt(cfg, tmp_path, memory):
    raw, name = gaussian_only(cfg)
    raw['resources']['pbs_max_mem_gb'] = 200
    raw['resources']['tiers']['complex'] = {'cores': 8, 'mem_gb': 200}
    loaded = load(raw)
    study.init(loaded, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace('10GB', memory))
    with pytest.raises(ValueError, match='exceeds 85%'):
        attempt.prepare(
            loaded, study_name='water', template='gaussian', input_path=source,
            tier='complex', walltime='00:30:00', label='sp', cluster=name,
            method_basis='synthetic water fixture')
    assert not list((Path(loaded['local']['studies_root']) / 'water/attempts').iterdir())


def test_high_memory_preserves_automatic_gaussian_memory_rule(cfg, tmp_path):
    raw, name = gaussian_only(cfg)
    raw['resources']['pbs_max_mem_gb'] = 200
    raw['resources']['tiers']['complex'] = {'cores': 8, 'mem_gb': 200}
    loaded = load(raw)
    study.init(loaded, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace('%mem=10GB\n', ''))
    manifest = attempt.prepare(
        loaded, study_name='water', template='gaussian', input_path=source,
        tier='complex', walltime='00:30:00', label='sp', cluster=name,
        method_basis='synthetic water fixture')
    path = attempt.find(loaded, manifest['attempt_id'])
    assert manifest['auto_mem_gb'] == 16
    assert b'%mem=16GB\n' in attempt.verified_files(loaded, path, manifest)['water.gjf']
