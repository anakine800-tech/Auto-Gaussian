"""T19 discovery and snapshot checks, using only synthetic local configuration."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from ag import budget, cli, clusters, config, monitor
from ag.transport import Result, SSHTransport
from test_core import cfg, write_config
from test_slurm import multi, SlurmFake


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def query(raw, tmp_path, monkeypatch, capsys, *options):
    path = write_config(raw)
    monkeypatch.setattr(cli, 'load_config', lambda: config.load_config(path))
    def forbidden(*args, **kwargs):
        pytest.fail('Cluster discovery must not construct a transport or run a subprocess')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    before = tree(tmp_path)
    code = cli.main(['clusters', '--json', *options])
    captured = capsys.readouterr()
    assert captured.err == ''
    assert tree(tmp_path) == before
    return code, json.loads(captured.out)


def seed_budget(raw, *, used=5400):
    selected = config.select_cluster(raw, 'batch')
    path = budget.ledger_path(selected)
    path.write_text(json.dumps(dict(cluster='batch', attempts={
        'synthetic-settled': dict(state='settled', used=used, reserved=0,
                                  job_id='private-job-marker', bundle_sha256='private-hash-marker'),
        'synthetic-unknown': dict(state='rejected', used=0, reserved=0),
        'synthetic-rejected': dict(state='rejected', used=0, reserved=0)})))
    return path


def test_legacy_single_cluster(cfg, tmp_path, monkeypatch, capsys):
    code, result = query(cfg, tmp_path, monkeypatch, capsys)
    assert code == 0
    assert result == {'clusters': [dict(
        name='default', scheduler='pbs', is_default=True,
        resources=dict(max_cores=44, max_committed_cores=44, tiers=cfg['resources']['tiers']),
        expires=None, programs_enabled=dict(gaussian=True, xtb=True, crest=True))]}


@pytest.mark.parametrize('mode,expected', [
    ('same', True), ('different', False), ('supplied_symlink', True), ('configured_symlink', True)])
def test_verify_studies_root(cfg, tmp_path, monkeypatch, capsys, mode, expected):
    root = Path(cfg['local']['studies_root'])
    root.mkdir()
    supplied = root
    if mode == 'different':
        supplied = tmp_path / 'other-studies'
        supplied.mkdir()
    elif mode.endswith('symlink'):
        alias = tmp_path / 'studies-alias'
        alias.symlink_to(root, target_is_directory=True)
        if mode == 'supplied_symlink':
            supplied = alias
        else:
            cfg['local']['studies_root'] = str(alias)
    code, baseline = query(cfg, tmp_path, monkeypatch, capsys)
    assert code == 0 and set(baseline) == {'clusters'}
    code, result = query(cfg, tmp_path, monkeypatch, capsys, '--verify-studies-root', str(supplied))
    assert code == 0
    assert result == dict(baseline, studies_root_matches=expected)
    assert result['studies_root_matches'] is expected
    for path in (str(tmp_path), str(supplied), cfg['local']['studies_root']):
        assert path not in json.dumps(result)


def test_verify_studies_root_symlink_loop_does_not_echo_path(cfg, tmp_path, monkeypatch, capsys):
    alias = tmp_path / 'private-loop-marker'
    alias.symlink_to(alias)
    code, result = query(cfg, tmp_path, monkeypatch, capsys, '--verify-studies-root', str(alias))
    assert code != 0 and set(result) == {'error', 'exit_code'}
    assert str(tmp_path) not in json.dumps(result) and alias.name not in json.dumps(result)


def test_dual_clusters_allowlist_and_budget(multi, tmp_path, monkeypatch, capsys):
    private = ['private-host-marker', 'private-user-marker', 'private-account-marker',
               'private-partition-marker', 'private-module-marker', 'private-metadata-marker',
               'private-job-marker', 'private-hash-marker']
    pbs, batch = multi['clusters']['default'], multi['clusters']['batch']
    pbs['resources']['max_committed_cores'] = 88
    pbs['resources']['budget_core_hours'] = 1000  # PBS must not expose a budget.
    pbs['resources']['tiers']['private-tier-marker'] = {'cores': 1, 'mem_gb': 1}
    batch.update(account=private[2], partition=private[3], expires='2027-01-31')
    batch['ssh'].update(host=private[0], user=private[1])
    batch['resources']['budget_core_hours'] = 100.5
    batch['resources']['tiers']['mini']['metadata'] = private[5]
    batch['programs']['gaussian'].update(modules=[private[4]], module_init=str(tmp_path / private[4]))
    seed_budget(multi)
    code, result = query(multi, tmp_path, monkeypatch, capsys)
    assert code == 0 and set(result) == {'clusters'}
    assert [r['name'] for r in result['clusters']] == ['batch', 'default']
    for row in result['clusters']:
        expected = {'name', 'scheduler', 'is_default', 'resources', 'expires', 'programs_enabled'}
        if row['name'] == 'batch':
            assert row['scheduler'] == 'slurm' and row['is_default'] is False
            assert row['expires'] == '2027-01-31'
            assert 'budget' not in row
        else:
            assert row['scheduler'] == 'pbs' and row['is_default'] is True
            assert row['resources']['max_committed_cores'] == 88
        assert set(row) == expected
        assert set(row['resources']) == {'max_cores', 'max_committed_cores', 'tiers'}
        assert set(row['resources']['tiers']) == {'mini', 'simple', 'general', 'complex'}
        assert all(set(t) == {'cores', 'mem_gb'} for t in row['resources']['tiers'].values())
        assert set(row['programs_enabled']) == {'gaussian', 'xtb', 'crest'}
        assert all(type(v) is bool for v in row['programs_enabled'].values())
    serialized = json.dumps(result)
    for value in private + [str(tmp_path), 'private-tier-marker']:
        assert value not in serialized
    for key in ('host', 'hostname', 'username', 'user', 'account', 'partition', 'qos', 'queue',
                'ssh', 'remote', 'local', 'config_file', 'studies_root', 'g16root', 'root',
                'allowed_root', 'ag_root', 'modules', 'module_init', '_config_dir', 'job_id'):
        assert f'"{key}"' not in serialized


def test_mixed_config_uses_implicit_default(cfg, multi, tmp_path, monkeypatch, capsys):
    cfg['clusters'] = {'batch': multi['clusters']['batch']}
    code, result = query(cfg, tmp_path, monkeypatch, capsys)
    assert code == 0
    assert [(r['name'], r['scheduler'], r['is_default']) for r in result['clusters']] == [
        ('batch', 'slurm', False), ('default', 'pbs', True)]


def test_no_default_is_not_inferred(multi, tmp_path, monkeypatch, capsys):
    del multi['clusters']['default']
    code, result = query(multi, tmp_path, monkeypatch, capsys)
    assert code == 0 and result['clusters'][0]['is_default'] is False
    assert len(result['clusters']) == 1


@pytest.mark.parametrize('configured', [False, True])
def test_optional_budget_and_fresh_ledger(multi, tmp_path, monkeypatch, capsys, configured):
    if configured:
        multi['clusters']['batch']['resources']['budget_core_hours'] = 100
    code, result = query(multi, tmp_path, monkeypatch, capsys)
    assert code == 0
    row = result['clusters'][0]
    assert 'budget' not in row
    assert not budget.ledger_path(config.select_cluster(multi, 'batch')).exists()


@pytest.mark.parametrize('damage', ['{', 'null', '[]', '{"cluster":"batch","attempts":{}}'])
def test_discovery_no_longer_reads_core_hour_budget(multi, tmp_path, monkeypatch, capsys, damage):
    multi['clusters']['batch']['resources']['budget_core_hours'] = 100
    path = seed_budget(multi)
    path.write_text(damage)
    claim = Path(multi['local']['studies_root']) / 'water/attempts/water-001-sp'
    claim.mkdir(parents=True)
    (claim / 'manifest.json').write_text(json.dumps(dict(
        cluster='batch', scheduler='slurm', attempt_id='water-001-sp')))
    (claim / '.submit-claim').touch()
    code, result = query(multi, tmp_path, monkeypatch, capsys)
    assert code == 0 and all('budget' not in row for row in result['clusters'])


def test_error_text_does_not_leak_filesystem_values(monkeypatch, capsys, tmp_path):
    def fail():
        raise PermissionError(f'private-user-marker: {tmp_path}')
    monkeypatch.setattr(cli, 'load_config', fail)
    assert cli.main(['clusters', '--json']) == 2
    captured = capsys.readouterr()
    assert 'private-user-marker' not in captured.out and str(tmp_path) not in captured.out
    assert captured.err == '' and set(json.loads(captured.out)) == {'error', 'exit_code'}


def test_program_projection_uses_shared_xtb_crest_configuration(cfg):
    loaded = config.load_config(write_config(cfg))
    # Current validation requires both roots; projection also handles absent
    # program settings without claiming executable availability.
    loaded['programs'] = {}
    assert clusters.describe(loaded)['clusters'][0]['programs_enabled'] == dict(
        gaussian=False, xtb=False, crest=False)
    loaded['programs'] = {'xtb': {'root': 'synthetic-root'}}
    assert clusters.describe(loaded)['clusters'][0]['programs_enabled'] == dict(
        gaussian=False, xtb=True, crest=True)


@pytest.fixture
def monitored(multi, monkeypatch):
    batch = multi['clusters']['batch']
    batch['resources']['budget_core_hours'] = 100
    batch['expires'] = '2027-01-31'
    seed_budget(multi)
    monkeypatch.setattr(monitor, 'login_user', lambda cfg: 'fixture')
    selected = config.select_cluster(multi, 'batch')
    return selected, SlurmFake(selected)


def test_slurm_snapshot_fields_and_local_only_budget(monitored):
    selected, fake = monitored
    path = budget.ledger_path(selected)
    before = path.read_bytes()
    result = monitor.sample(selected, fake)
    assert result['ok']
    assert result['cluster']['budget'] is None
    assert result['cluster']['expires'] == '2027-01-31'
    assert result['cluster']['storage_kib'] == 1024
    assert fake.operations() == ['slurm_jobs', 'slurm_jobs', 'slurm_partitions', 'slurm_partitions', 'storage_usage']
    assert path.read_bytes() == before
    cache = Path(selected['local']['studies_root']) / '.ag-monitor/batch/latest.json'
    assert json.loads(cache.read_text()) == result


@pytest.mark.parametrize('failure', ['scheduler', 'budget'])
def test_failed_slurm_sample_keeps_last_storage_with_null_budget(monitored, failure):
    selected, fake = monitored
    previous = monitor.sample(selected, fake)
    fake.calls.clear()
    if failure == 'scheduler':
        fake.queue = Result(255, stderr='synthetic failure')
    else:
        budget.ledger_path(selected).write_text('null')
    result = monitor.sample(selected, fake)
    assert not result['ok'] and result['error']
    assert result['last_ok_at'] == previous['last_ok_at']
    assert result['cluster'] == previous['cluster']
    assert fake.operations() == (['slurm_jobs'] if failure == 'scheduler' else [])


@pytest.mark.parametrize('old_cache', [False, True])
def test_first_failure_and_pre_t19_cache_do_not_invent_zeros(monitored, old_cache):
    selected, fake = monitored
    if old_cache:
        previous = monitor.sample(selected, fake)
        for key in ('budget', 'expires', 'storage_kib'):
            previous['cluster'].pop(key)
        (monitor.cache_dir(selected) / 'latest.json').write_text(json.dumps(previous))
    fake.queue = Result(255)
    result = monitor.sample(selected, fake)
    assert not result['ok']
    assert result['cluster']['budget'] is None and result['cluster']['storage_kib'] is None
    assert result['cluster']['expires'] == '2027-01-31'


def test_unconfigured_slurm_budget_and_expiry_are_null(monitored):
    selected, fake = monitored
    selected = deepcopy(selected)
    del selected['resources']['budget_core_hours']
    del selected['expires']
    result = monitor.sample(selected, fake)
    assert result['ok']
    assert result['cluster']['budget'] is None and result['cluster']['expires'] is None


def test_monitor_cache_paths_legacy_named_default_and_batch(multi, cfg):
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    assert monitor.cache_dir(cfg) == root
    assert monitor.cache_dir(config.select_cluster(multi, 'default')) == root / 'default'
    assert monitor.cache_dir(config.select_cluster(multi, 'batch')) == root / 'batch'
