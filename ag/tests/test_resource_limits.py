"""T142 resource limits use synthetic configurations and recording transports only."""
import json
from pathlib import Path

import pytest

from ag import approval, attempt, cli, clusters, config, confirm, monitor, route, state, study, submit
from ag.transport import SSHTransport
from test_approval import policy, record, record_path
from test_core import cfg, prepared, Fake, INPUT
from test_gaussian_only import gaussian_only, load
from test_monitor import Fake as MonitorFake
from test_route import NOW, routed, save
from test_slurm import SlurmFake


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob('*')}


def immutable(path):
    return {str(p.relative_to(path)): p.read_bytes()
            for p in [path / 'manifest.json', *(path / 'inputs').iterdir()]}


def forbidden(*args, **kwargs):
    pytest.fail('rejected resource request must not reach this side effect')


def resource_config(cfg, mode='legacy', optional=('max', 'ultra')):
    raw, name = gaussian_only(cfg, mode)
    entry = raw if mode == 'legacy' else raw['clusters'][name]
    # Deliberately insert in reverse order: output order is defined by known names.
    for tier in reversed(optional):
        entry['resources']['tiers'][tier] = dict(cores=8, mem_gb=12)
    return raw, name, entry


@pytest.mark.parametrize('mode', ['legacy', 'pbs', 'slurm'])
@pytest.mark.parametrize('optional', [(), ('max',), ('ultra',), ('max', 'ultra')])
def test_optional_tiers_are_only_exposed_when_configured(cfg, mode, optional):
    raw, name, entry = resource_config(cfg, mode, optional)
    entry['resources']['tiers']['unknown-metadata'] = {'secret-marker': True}
    loaded = load(raw)
    selected = config.select_cluster(loaded, name)
    assert 'max_walltime' not in selected['resources']
    assert 'pbs_max_mem_gb' not in selected['resources']
    resources = clusters.describe(loaded)['clusters'][0]['resources']
    assert list(resources['tiers']) == list(config.RESOURCE_TIERS[:4]) + list(optional)
    assert 'max_walltime' not in resources
    assert 'secret-marker' not in json.dumps(resources)


@pytest.mark.parametrize('tier', config.RESOURCE_TIERS[:4])
def test_original_four_tiers_remain_required(cfg, tier):
    del cfg['resources']['tiers'][tier]
    with pytest.raises(config.ConfigError, match='require mini, simple, general and complex'):
        load(cfg)


@pytest.mark.parametrize('tier', ['max', 'ultra'])
@pytest.mark.parametrize('value', [None, True, {}, {'cores': True, 'mem_gb': 12},
                                 {'cores': 8, 'mem_gb': 0}, {'cores': 45, 'mem_gb': 12}])
def test_invalid_optional_tier_is_not_ignored(cfg, tier, value):
    cfg['resources']['tiers'][tier] = value
    with pytest.raises((config.ConfigError, KeyError)):
        config.validate_cluster(cfg)


@pytest.mark.parametrize('tier', ['max', 'ultra'])
def test_optional_tier_obeys_pbs_memory_authorization(cfg, tier):
    cfg['resources']['tiers'][tier] = dict(cores=8, mem_gb=200)
    with pytest.raises(config.ConfigError, match='Invalid resource tier'):
        load(cfg)
    cfg['resources']['pbs_max_mem_gb'] = 200
    assert load(cfg)['resources']['tiers'][tier]['mem_gb'] == 200
    cfg['resources']['pbs_max_mem_gb'] = 199
    with pytest.raises(config.ConfigError, match='Invalid resource tier'):
        load(cfg)


def test_slurm_optional_tier_retains_existing_memory_behavior(cfg):
    raw, name, entry = resource_config(cfg, 'slurm', ('ultra',))
    entry['resources']['tiers']['ultra']['mem_gb'] = 256
    loaded = load(raw)
    assert config.select_cluster(loaded, name)['resources']['tiers']['ultra']['mem_gb'] == 256


@pytest.mark.parametrize('mode', ['legacy', 'pbs', 'slurm'])
@pytest.mark.parametrize('value', ['00:00:01', '24:00:00', '36:00:00', '1234:00:00', '9999:59:59'])
def test_positive_walltime_cap_round_trips_without_normalizing(cfg, mode, value):
    raw, name, entry = resource_config(cfg, mode)
    entry['resources']['max_walltime'] = value
    loaded = load(raw)
    assert config.select_cluster(loaded, name)['resources']['max_walltime'] == value
    assert clusters.describe(loaded)['clusters'][0]['resources']['max_walltime'] == value


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('value', [None, True, False, 24, 24.0, [], {}, '', '00:00:00',
                                 '0:30:00', '10000:00:00', '24:60:00', '24:00:60',
                                 '-1:00:00', '24:00', '24:00:00\n', ' 24:00:00',
                                 '２４:００:００', '٢٤:٠٠:٠٠'])
def test_invalid_walltime_caps_reject_non_ascii_and_non_strings(cfg, scheduler, value):
    if scheduler == 'slurm':
        cfg['scheduler'] = 'slurm'
    cfg['resources']['max_walltime'] = value
    with pytest.raises(config.ConfigError, match='resources.max_walltime'):
        config.validate_cluster(cfg)


@pytest.mark.parametrize('mode', ['pbs', 'slurm'])
@pytest.mark.parametrize('tier', ['max', 'ultra'])
def test_gaussian_only_optional_tiers_prepare_render_and_cli(cfg, tmp_path, monkeypatch, capsys, mode, tier):
    raw, name, entry = resource_config(cfg, mode)
    entry['resources']['max_walltime'] = '1234:00:00'
    loaded = load(raw)
    study.init(loaded, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    monkeypatch.setattr(cli, 'load_config', lambda: loaded)
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    assert cli.main(['prepare', '--study', 'water', '--template', 'gaussian', '--input', str(source),
                     '--tier', tier, '--walltime', '1234:00:00', '--label', 'sp', '--cluster', name,
                     '--method-basis', 'synthetic water fixture', '--json']) == 0
    manifest = json.loads(capsys.readouterr().out)
    path = attempt.find(loaded, manifest['attempt_id'])
    assert manifest['tier'] == tier and manifest['walltime'] == '1234:00:00'
    files = attempt.verified_files(loaded, path, manifest)
    script = files['job.slurm' if mode == 'slurm' else 'job.pbs'].decode()
    assert ('#SBATCH --time=1234:00:00' if mode == 'slurm' else '#PBS -l walltime=1234:00:00') in script
    assert files['water.gjf'] == source.read_bytes()
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('tier', ['max', 'ultra'])
def test_high_memory_optional_tier_uses_same_gaussian_85_percent_limit(cfg, tmp_path, tier):
    raw, name, entry = resource_config(cfg, 'pbs', (tier,))
    entry['resources']['pbs_max_mem_gb'] = 200
    entry['resources']['tiers'][tier]['mem_gb'] = 200
    entry['resources']['max_walltime'] = '36:00:00'
    loaded = load(raw)
    study.init(loaded, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace('10GB', '170GB'))
    manifest = attempt.prepare(loaded, study_name='water', template='gaussian', input_path=source,
                               tier=tier, walltime='36:00:00', label='sp', cluster=name,
                               method_basis='synthetic water fixture')
    path = attempt.find(loaded, manifest['attempt_id'])
    files = attempt.verified_files(loaded, path, manifest)
    assert b'#PBS -l mem=200gb\n' in files['job.pbs']
    assert b'%mem=170GB\n' in files['water.gjf']
    source.write_text(INPUT.replace('10GB', '171GB'))
    before = tree(tmp_path)
    with pytest.raises(ValueError, match='exceeds 85%'):
        attempt.prepare(loaded, study_name='water', template='gaussian', input_path=source,
                        tier=tier, walltime='36:00:00', label='over', cluster=name,
                        method_basis='synthetic water fixture')
    assert tree(tmp_path) == before


@pytest.mark.parametrize('template', ['gaussian', 'crest'])
@pytest.mark.parametrize('tier,walltime,message', [
    ('max', '00:30:00', 'not configured'), ('simple', '00:30:01', 'max_walltime'),
    ('simple', '00:00:00', 'positive HH:MM:SS'), ('simple', 'bad', 'positive HH:MM:SS')])
def test_prepare_rejects_before_files_claims_or_crest_checks(cfg, tmp_path, monkeypatch, template, tier, walltime, message):
    cfg['resources']['max_walltime'] = '00:30:00'
    cfg['programs']['crest'] = {'executable': str(tmp_path / 'synthetic-crest')}
    study.init(cfg, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    before = tree(tmp_path)
    monkeypatch.setattr(attempt, 'claim', forbidden)
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    fake = Fake(cfg)
    fake.run = forbidden
    with pytest.raises(ValueError, match=message):
        attempt.prepare(cfg, study_name='water', template=template, input_path=source,
                        tier=tier, walltime=walltime, label='sp', method_basis='synthetic fixture',
                        transport=fake)
    assert tree(tmp_path) == before


@pytest.mark.parametrize('tier', ['max', 'ultra'])
def test_missing_route_tier_is_denied_without_inventing_resources(routed, monkeypatch, capsys, tier):
    result = route.suggest(routed, 'gaussian', tier, now=NOW)
    assert result['recommendation'] is None
    for row in result['clusters']:
        assert row['conclusion'] == route.DENIED and row['reasons'] == ['不支持该档位']
        assert row['cores'] is None and row['mem_gb'] is None
        assert row['personal_allowed'] is False
    assert 'None' not in route.format_result(result)
    monkeypatch.setattr(route, 'load_config', lambda: routed)
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    assert cli.main(['route', '--template', 'gaussian', '--tier', tier, '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['clusters'][0]['cores'] is None
    assert result['recommendation'] is None
    assert cli.main(['route', '--template', 'gaussian', '--tier', tier]) == 0
    text = capsys.readouterr().out
    assert '不支持该档位' in text and 'None' not in text


def test_route_skips_missing_tier_and_recommends_configured_entry(routed):
    selected = routed['clusters']['newhpc']
    selected['resources']['tiers']['ultra'] = dict(cores=8, mem_gb=12)
    save(routed, 'newhpc')
    result = route.suggest(routed, 'gaussian', 'ultra', now=NOW)
    assert result['recommendation']['name'] == 'newhpc'
    assert next(r for r in result['clusters'] if r['name'] == 'default')['conclusion'] == route.DENIED


def test_monitor_refreshes_config_fields_in_success_and_retained_failure(cfg, monkeypatch):
    cfg['resources']['tiers']['ultra'] = dict(cores=8, mem_gb=12)
    cfg['resources']['tiers']['max'] = dict(cores=8, mem_gb=12)
    cfg['resources']['tiers']['unknown-metadata'] = {'secret-marker': True}
    cfg['resources']['max_walltime'] = '36:00:00'
    monkeypatch.setattr(monitor, 'ssh_identity', lambda cfg: ('fixture', 22, 'fixture'))
    first = monitor.sample(cfg, MonitorFake(), 60)
    assert first['ok'] and first['schema'] == 'ag-monitor/1'
    assert first['own']['max_walltime'] == '36:00:00'
    assert list(first['own']['tiers']) == list(config.RESOURCE_TIERS)
    assert 'secret-marker' not in json.dumps(first)
    fake = MonitorFake()
    fake.replies['jobs'] = ValueError('synthetic failed sample')
    cfg['resources']['max_walltime'] = '24:00:00'
    del cfg['resources']['tiers']['ultra']
    failed = monitor.sample(cfg, fake, 60)
    assert not failed['ok'] and failed['last_ok_at'] == first['last_ok_at']
    assert failed['own']['max_walltime'] == '24:00:00'
    assert list(failed['own']['tiers']) == list(config.RESOURCE_TIERS[:5])
    assert failed['cluster'] == first['cluster']
    del cfg['resources']['max_walltime']
    del cfg['resources']['tiers']['max']
    removed = monitor.sample(cfg, fake, 60)
    assert not removed['ok'] and 'max_walltime' not in removed['own']
    assert list(removed['own']['tiers']) == list(config.RESOURCE_TIERS[:4])
    recovered = monitor.sample(cfg, MonitorFake(), 60)
    assert recovered['ok'] and 'max_walltime' not in recovered['own']
    assert list(recovered['own']['tiers']) == list(config.RESOURCE_TIERS[:4])


def authorization(cfg, path, mode):
    if mode == 'approval':
        value = record(cfg, path)
        return {'approval_id': value['id']}, record_path(path, value)
    if mode == 'policy':
        policy(cfg)
        return {'policy_name': 'validation'}, None
    return {}, None


@pytest.mark.parametrize('mode', ['dialog', 'approval', 'policy'])
@pytest.mark.parametrize('entrypoint', ['api', 'cli'])
def test_old_prepared_obeys_new_cap_before_any_submit_side_effect(cfg, prepared, tmp_path, monkeypatch, capsys, mode, entrypoint):
    path, manifest = prepared
    options, approval_file = authorization(cfg, path, mode)
    # A later call loads a stricter configuration; the prepared bundle is immutable.
    cfg['resources']['max_walltime'] = '00:29:59'
    loaded = load(cfg)
    before = tree(tmp_path)
    monkeypatch.setattr(submit, 'bound_transport', forbidden)
    monkeypatch.setattr(submit, 'submission_lock', forbidden)
    monkeypatch.setattr(submit, 'claim', forbidden)
    monkeypatch.setattr(approval, 'consume', forbidden)
    monkeypatch.setattr(confirm, 'confirm', forbidden)
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    fake = Fake(loaded)
    fake.record_to = forbidden
    if entrypoint == 'api':
        with pytest.raises(config.ConfigError, match='max_walltime'):
            submit.submit(loaded, [path.name], fake, **options)
    else:
        monkeypatch.setattr(cli, 'load_config', lambda: loaded)
        argv = ['submit', path.name, '--json']
        for key, value in options.items():
            argv.extend(['--approval' if key == 'approval_id' else '--policy', value])
        assert cli.main(argv) != 0
        assert 'max_walltime' in json.loads(capsys.readouterr().out)['error']
    assert fake.operations() == []
    assert tree(tmp_path) == before
    assert state.read(path)['state'] == 'prepared'
    assert not (path / '.submit-claim').exists()
    if approval_file:
        assert not approval_file.with_suffix('.used').exists()


@pytest.mark.parametrize('mode', ['dialog', 'approval', 'policy'])
def test_confirmed_requests_recheck_cap_before_authorization_consumption(cfg, prepared, monkeypatch, mode):
    path, _ = prepared
    options, approval_file = authorization(cfg, path, mode)
    cfg['resources']['max_walltime'] = '00:30:00'
    before = immutable(path)
    real_authorize = approval.authorize

    def authorize(*args, **kwargs):
        result = real_authorize(*args, **kwargs)
        if mode != 'dialog':
            cfg['resources']['max_walltime'] = '00:29:59'
        return result

    def accept(text):
        cfg['resources']['max_walltime'] = '00:29:59'
        return True

    monkeypatch.setattr(approval, 'authorize', authorize)
    monkeypatch.setattr(confirm, 'confirm', accept if mode == 'dialog' else forbidden)
    monkeypatch.setattr(approval, 'consume', forbidden)
    fake = Fake(cfg)
    with pytest.raises(config.ConfigError, match='max_walltime'):
        submit.submit(cfg, [path.name], fake, **options)
    assert set(fake.operations()) <= {'identity', 'jobs'}
    assert not (path / '.submit-claim').exists()
    assert immutable(path) == before and state.read(path)['state'] == 'prepared'
    if approval_file:
        assert not approval_file.with_suffix('.used').exists()


def test_submit_rechecks_immediately_before_claim_without_rewriting_bundle(cfg, prepared, monkeypatch):
    path, _ = prepared
    options, approval_file = authorization(cfg, path, 'approval')
    cfg['resources']['max_walltime'] = '00:30:00'
    before = immutable(path)
    real_consume = approval.consume

    def consume(*args, **kwargs):
        real_consume(*args, **kwargs)
        cfg['resources']['max_walltime'] = '00:29:59'

    monkeypatch.setattr(approval, 'consume', consume)
    monkeypatch.setattr(submit, 'claim', forbidden)
    monkeypatch.setattr(confirm, 'confirm', forbidden)
    fake = Fake(cfg)
    with pytest.raises(config.ConfigError, match='max_walltime'):
        submit.submit(cfg, [path.name], fake, **options)
    assert set(fake.operations()) <= {'identity', 'jobs'}
    assert approval_file.with_suffix('.used').exists()
    assert not (path / '.submit-claim').exists()
    assert immutable(path) == before and state.read(path)['state'] == 'prepared'


@pytest.mark.parametrize('mode', ['pbs', 'slurm'])
def test_optional_tier_and_equal_cap_submit_with_existing_confirmation(cfg, tmp_path, monkeypatch, mode):
    raw, name, entry = resource_config(cfg, mode)
    entry['resources']['max_walltime'] = '00:30:00'
    loaded = load(raw)
    selected = config.select_cluster(loaded, name)
    study.init(loaded, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    manifest = attempt.prepare(loaded, study_name='water', template='gaussian', input_path=source,
                               tier='ultra', walltime='00:30:00', label='sp', cluster=name,
                               method_basis='synthetic water fixture')
    path = attempt.find(loaded, manifest['attempt_id'])
    before = immutable(path)
    confirmations = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: confirmations.append(text) or True)
    fake = SlurmFake(selected) if mode == 'slurm' else Fake(selected)
    result = submit.submit(loaded, [path.name], fake)
    assert result[0]['state'] == 'submitted' and len(confirmations) == 1
    assert 'ultra 8 cores' in confirmations[0] and '00:30:00' in confirmations[0]
    assert fake.operations().count('submit') == 1
    assert immutable(path) == before
