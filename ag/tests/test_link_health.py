"""Synthetic monitor evidence only; no SSH, actual settings or study data."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from ag import clusters, config, link_health, monitor
from ag.transport import SSHTransport
from test_core import cfg, write_config
from test_route import routed, snapshot, save, NOW
from test_slurm import multi


def reports(raw, failed=()):
    rows = {name: snapshot(raw, name) for name in raw['clusters']}
    for name in failed:
        rows[name].update(ok=False, error='synthetic connection failure')
    return rows


def dependencies(raw):
    raw['clusters']['default']['relay_group'] = 'relay-a'
    raw['clusters']['newhpc']['relay_group'] = 'relay-a'
    return raw


@pytest.mark.parametrize('failed,expected', [
    ((), 'healthy'),
    (('default',), 'cluster_failure'),
    (('default', 'newhpc'), 'relay_outage'),
    (('default', 'newhpc', 'scnet', 'scnet-test'), 'local_outage'),
])
def test_classification_and_retained_success(routed, failed, expected):
    dependencies(routed)
    snapshots = reports(routed, failed)
    before = deepcopy(snapshots)
    report = link_health.classify(routed, snapshots, now=NOW + timedelta(seconds=15))
    assert report['status'] == expected
    assert all(row['age_seconds'] == 15 for row in report['entries'])
    assert all(row['interval_seconds'] == 60 for row in report['entries'])
    assert snapshots == before
    for row in report['entries']:
        assert row['status'] == ('failed' if row['name'] in failed else 'success')
        assert row['relay_group'] == ('relay-a' if row['name'] in ('default', 'newhpc') else None)
    serialized = json.dumps(report)
    assert 'synthetic connection failure' not in serialized
    assert 'last_ok_at' not in serialized
    assert link_health.validate(report) is report


@pytest.mark.parametrize('mutation,reason', [
    (lambda s: s.update(sampled_at=(NOW - timedelta(seconds=181)).isoformat()), 'stale'),
    (lambda s: s.update(sampled_at=(NOW + timedelta(seconds=1)).isoformat()), 'future'),
    (lambda s: s.update(sampled_at='damaged'), 'invalid'),
    (lambda s: s.update(sampled_at=NOW.replace(tzinfo=None).isoformat()), 'invalid'),
    (lambda s: s.update(interval_seconds=None), 'invalid'),
    (lambda s: s.update(interval_seconds=True), 'invalid'),
    (lambda s: s.update(ok=1), 'invalid'),
    (lambda s: s.update(ok=False, error=None), 'invalid'),
    (lambda s: s.update(ok=True, error='conflicting success'), 'invalid'),
    (lambda s: s.update(config_removed=True), 'configuration'),
    (lambda s: s.update(config_warning='old configuration'), 'configuration'),
    (lambda s: s.pop('error'), 'invalid'),
    (lambda s: s['own'].pop('jobs'), 'invalid'),
    (lambda s: s.update(ok=True, error=None, last_ok_at=None), 'invalid'),
    (lambda s: s.update(ok=True, error=None, last_ok_at=(NOW - timedelta(seconds=60)).isoformat()), 'invalid'),
    (lambda s: s['cluster'].update(name='different'), 'invalid'),
    (lambda s: s['cluster'].update(scheduler='different'), 'invalid'),
])
def test_unknown_never_proves_current_success_or_outage(routed, mutation, reason):
    dependencies(routed)
    snapshots = reports(routed, ('default', 'newhpc'))
    mutation(snapshots['newhpc'])
    result = link_health.classify(routed, snapshots, now=NOW)
    assert result['status'] == 'unknown'
    row = next(row for row in result['entries'] if row['name'] == 'newhpc')
    assert row['status'] == 'unknown' and row['reason'] == reason


def test_freshness_boundary_and_missing_independent_evidence(routed):
    dependencies(routed)
    snapshots = reports(routed, ('default', 'newhpc'))
    assert link_health.classify(routed, snapshots, now=NOW + timedelta(seconds=180))['status'] == 'relay_outage'
    assert link_health.classify(routed, snapshots, now=NOW + timedelta(seconds=180.1))['status'] == 'unknown'
    del snapshots['scnet']
    del snapshots['scnet-test']
    result = link_health.classify(routed, snapshots, now=NOW)
    assert result['status'] == 'unknown'
    assert [row['reason'] for row in result['entries'] if row['relay_group'] is None] == ['missing', 'missing']


def test_unmarked_entries_and_partial_groups_are_not_relay_outage(routed):
    snapshots = reports(routed, ('default', 'newhpc'))
    assert link_health.classify(routed, snapshots, now=NOW)['status'] == 'cluster_failure'
    dependencies(routed)
    routed['clusters']['scnet']['relay_group'] = 'relay-b'
    assert link_health.classify(routed, snapshots, now=NOW)['status'] == 'cluster_failure'


def test_local_cache_reader_never_creates_or_probes(routed, monkeypatch):
    dependencies(routed)
    def forbidden(*args, **kwargs):
        pytest.fail('Link summary must not probe a connection')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    for name, data in reports(routed, ('default', 'newhpc')).items():
        save(routed, name, data)
    root = Path(routed['local']['studies_root'])
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    assert link_health.read(routed, now=NOW)['status'] == 'relay_outage'
    selected = config.select_cluster(routed, 'scnet-test')
    assert link_health.read(selected, now=NOW)['status'] == 'relay_outage'
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('mode', ['missing', 'invalid', 'duplicate', 'oversize', 'symlink', 'parent_symlink', 'ambiguous'])
def test_unreadable_cache_is_unknown(routed, tmp_path, mode):
    dependencies(routed)
    for name, data in reports(routed, ('default', 'newhpc')).items():
        save(routed, name, data)
    path = Path(routed['local']['studies_root']) / '.ag-monitor' / 'default' / 'latest.json'
    if mode == 'missing':
        path.unlink()
    elif mode == 'invalid':
        path.write_text('{')
    elif mode == 'duplicate':
        path.write_text('{"ok":true,"ok":false}')
    elif mode == 'oversize':
        path.write_bytes(b' ' * (2 * 1024 * 1024 + 1))
    elif mode == 'symlink':
        other = tmp_path / 'synthetic-snapshot.json'
        path.rename(other)
        path.symlink_to(other)
    elif mode == 'parent_symlink':
        other = tmp_path / 'synthetic-cache'
        path.parent.rename(other)
        path.parent.symlink_to(other, target_is_directory=True)
    else:
        (path.parent.parent / 'latest.json').write_bytes(path.read_bytes())
    result = link_health.read(routed, now=NOW)
    assert result['status'] == 'unknown'
    assert result['entries'][0]['status'] == 'unknown'
    assert str(tmp_path) not in json.dumps(result)


def test_minimal_local_config_and_legacy_cache(cfg, tmp_path):
    result = link_health.read(dict(local=cfg['local']), now=NOW)
    assert result['status'] == 'unknown'
    assert not Path(cfg['local']['studies_root']).exists()
    data = monitor.empty_snapshot(cfg, 60)
    data.update(sampled_at=NOW.isoformat(), last_ok_at=NOW.isoformat(), ok=True)
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    root.mkdir(parents=True)
    (root / 'latest.json').write_text(json.dumps(data))
    assert link_health.read(cfg, now=NOW)['status'] == 'healthy'


@pytest.mark.parametrize('change', [
    lambda r: r.update(status='healthy'),
    lambda r: r['entries'].append(deepcopy(r['entries'][0])),
    lambda r: r['entries'][0].update(age_seconds=181),
    lambda r: r['entries'][0].update(interval_seconds=True),
    lambda r: r['entries'][0].update(status='success'),
    lambda r: r.update(observed_at=float('nan')),
])
def test_damaged_persisted_report_rejected(routed, change):
    report = link_health.classify(dependencies(routed), reports(routed, ('default', 'newhpc')), now=NOW)
    change(report)
    with pytest.raises(ValueError):
        link_health.validate(report)


def test_config_defaults_and_discovery(multi):
    assert config.link_recheck_settings(multi) == dict(link_recheck_interval_minutes=30, link_recheck_max_attempts=2)
    multi['clusters']['default']['relay_group'] = 'relay-a'
    multi['clusters']['batch']['relay_group'] = 'relay-b'
    multi['autonomy'] = dict(link_recheck_interval_minutes=12, link_recheck_max_attempts=1)
    loaded = config.load_config(write_config(multi))
    assert config.link_recheck_settings(config.select_cluster(loaded, 'batch')) == multi['autonomy']
    assert {row['name']: row['relay_group'] for row in clusters.describe(loaded)['clusters']} == {
        'default': 'relay-a', 'batch': 'relay-b'}


def test_legacy_relay_field_survives_named_migration(cfg, multi):
    cfg['clusters'] = {'batch': multi['clusters']['batch']}
    path = write_config(cfg)
    path.write_text('relay_group = "relay-a"\n' + path.read_text())
    loaded = config.load_config(path)
    assert config.select_cluster(loaded, 'default')['relay_group'] == 'relay-a'
    assert 'relay_group' not in config.select_cluster(loaded, 'batch')


@pytest.mark.parametrize('value', ['', 'contains space', '../path', True, 12, None])
def test_bad_relay_group_is_rejected(multi, value):
    multi['clusters']['batch']['relay_group'] = value
    with pytest.raises(ValueError, match='relay_group'):
        config.validate_cluster(multi['clusters']['batch'])


@pytest.mark.parametrize('section', [
    None, [], {'typo': 1}, {'link_recheck_interval_minutes': 0},
    {'link_recheck_interval_minutes': True}, {'link_recheck_interval_minutes': 0.5},
    {'link_recheck_max_attempts': 3}, {'link_recheck_max_attempts': -1},
    {'link_recheck_max_attempts': True},
])
def test_bad_recheck_settings_are_rejected(section):
    with pytest.raises(ValueError):
        config.link_recheck_settings({'autonomy': section})


def test_zero_recheck_limit_and_large_interval_do_not_extend_lease():
    assert config.link_recheck_settings({'autonomy': dict(
        link_recheck_interval_minutes=120, link_recheck_max_attempts=0)}) == dict(
            link_recheck_interval_minutes=120, link_recheck_max_attempts=0)


def test_local_only_config_keeps_groups_without_remote_requirements(cfg):
    path = Path(cfg['_config_dir']) / 'local.toml'
    path.write_text('\n'.join([
        '[local]', f'studies_root = {json.dumps(cfg["local"]["studies_root"])}',
        '[autonomy]', 'link_recheck_interval_minutes = 12', 'link_recheck_max_attempts = 1',
        '[clusters.relay]', 'relay_group = "relay-a"', 'scheduler = "pbs"',
        '[clusters.relay.ssh]', 'host = "private-host-marker"',
        'config_file = "does-not-exist"',
        '[clusters.direct]', 'scheduler = "slurm"',
        '[clusters.direct.remote]', 'ag_root = "invalid-and-not-needed"',
    ]))
    loaded = config.load_config(path, local_only=True)
    assert loaded == dict(local=cfg['local'], _config_dir=cfg['_config_dir'],
        clusters={'relay': {'scheduler': 'pbs', 'relay_group': 'relay-a'},
                  'direct': {'scheduler': 'slurm'}},
        autonomy={'link_recheck_interval_minutes': 12, 'link_recheck_max_attempts': 1})
    serialized = json.dumps(loaded)
    assert 'private-host-marker' not in serialized and 'ssh' not in serialized and 'remote' not in serialized
    assert {row['name'] for row in link_health.read(loaded, now=NOW)['entries']} == {'relay', 'direct'}


def test_local_only_legacy_cache_and_minimal_config(cfg):
    path = Path(cfg['_config_dir']) / 'local.toml'
    local = '[local]\nstudies_root = ' + json.dumps(cfg['local']['studies_root'])
    path.write_text('relay_group = "relay-a"\n' + local)
    loaded = config.load_config(path, local_only=True)
    assert loaded['relay_group'] == 'relay-a' and 'clusters' not in loaded
    assert link_health.read(loaded, now=NOW)['entries'][0]['relay_group'] == 'relay-a'
    path.write_text(local)
    loaded = config.load_config(path, local_only=True)
    assert link_health.read(loaded, now=NOW)['status'] == 'unknown'


def test_local_only_unmarked_mixed_entries_are_preserved(cfg, multi):
    cfg['clusters'] = {'batch': multi['clusters']['batch']}
    loaded = config.load_config(write_config(cfg), local_only=True)
    assert loaded['clusters'] == {'default': {'scheduler': 'pbs'}, 'batch': {'scheduler': 'slurm'}}


def test_discovery_exposes_current_machine_link_health_without_study_or_writes(routed, monkeypatch):
    dependencies(routed)
    original_read = link_health.read
    monkeypatch.setattr(link_health, 'read', lambda cfg: original_read(cfg, now=NOW))
    def forbidden(*args, **kwargs):
        pytest.fail('Discovery must not probe a server')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    root = Path(routed['local']['studies_root'])
    for failed, expected in [((), 'healthy'), (('default', 'newhpc'), 'relay_outage')]:
        for name, data in reports(routed, failed).items():
            data['cluster']['private_note'] = 'private-host-marker'
            save(routed, name, data)
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob('*') if p.is_file()}
        result = clusters.describe(routed)
        assert result['link_health']['status'] == expected
        assert all(row['age_seconds'] == 0 for row in result['link_health']['entries'])
        assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob('*') if p.is_file()} == before
        text = json.dumps(result)
        assert 'private-host-marker' not in text and str(root) not in text
    save(routed, 'default', {})
    assert clusters.describe(routed)['link_health']['status'] == 'unknown'
