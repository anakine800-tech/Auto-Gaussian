"""Entry defaults affect new preparations only; all inputs and transports are synthetic."""
from copy import deepcopy
from pathlib import Path

import pytest

from ag import attempt, cli, config, study
from ag.transport import SSHTransport
from test_core import cfg, write_config
from test_counterpoise import CSV, WATER
from test_node_targeting import targeted


TEMPLATES = ('gaussian', 'gaussian-cp', 'xtb', 'crest', 'multiwfn')


@pytest.fixture(autouse=True)
def no_transport(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Default-tier preparation must not connect to a real scheduler')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)


@pytest.fixture
def default_cfg(cfg, tmp_path):
    cfg['resources'].update(
        max_cores=48, max_committed_cores=96, max_queued_cores=48, default_tier='max',
        tiers={name: dict(cores=cores, mem_gb=memory) for name, cores, memory in (
            ('mini', 8, 16), ('simple', 12, 24), ('general', 24, 48),
            ('complex', 32, 72), ('max', 48, 96))})
    cfg['programs']['multiwfn'] = str(tmp_path / 'program' / 'Multiwfn')
    cfg['allowed_templates'] = list(TEMPLATES)
    config.validate_cluster(cfg)
    return cfg


def arguments(tmp_path, template='gaussian'):
    source = tmp_path / ('water.gjf' if template.startswith('gaussian') else 'water.xyz')
    route = '# B3LYP/6-31G(d) SP' + (' Counterpoise=2' if template == 'gaussian-cp' else '')
    source.write_text((route + '\n\nSynthetic water dimer\n\n0 1\n' + WATER + '\n\n')
                      if template.startswith('gaussian') else '6\nSynthetic water dimer\n' + WATER + '\n')
    args = dict(study_name='defaults', template=template, input_path=source,
                walltime='00:05:00', label='sp', method_basis='兜底方法：合成水二聚体验证')
    if template in ('gaussian-cp', 'multiwfn'):
        fragments = tmp_path / 'fragments.csv'
        fragments.write_text(CSV if template == 'gaussian-cp' else
                             'fragment,atoms\nwater-a,1-3\nwater-b,4-6\n')
        args['fragments'] = fragments
    if template == 'multiwfn':
        args.update(analysis='igm', grid='low')
    return args


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('template', TEMPLATES)
def test_default_matches_explicit_resources_and_bundle(default_cfg, tmp_path, template):
    args = arguments(tmp_path, template)
    original = args['input_path'].read_bytes()
    study.init(default_cfg, 'defaults')
    explicit_cfg = deepcopy(default_cfg)
    explicit_cfg['local']['studies_root'] = str(tmp_path / 'explicit-studies')
    study.init(explicit_cfg, 'defaults')

    implicit = attempt.prepare(default_cfg, **args)
    explicit = attempt.prepare(explicit_cfg, **args, tier='max')
    path = attempt.find(default_cfg, implicit['attempt_id'])
    files = attempt.verified_files(default_cfg, path, implicit)
    explicit_files = attempt.verified_files(explicit_cfg, attempt.find(explicit_cfg, explicit['attempt_id']), explicit)
    assert files == explicit_files
    assert {k: v for k, v in implicit.items() if k != 'created_at'} == {
        k: v for k, v in explicit.items() if k != 'created_at'}
    assert (implicit['tier'], implicit['cores'], implicit['mem_gb']) == ('max', 48, 96)
    assert 'default_tier' not in implicit
    assert args['input_path'].read_bytes() == original
    if template.startswith('gaussian'):
        assert implicit['auto_nprocshared'] == 48 and implicit['auto_mem_gb'] == 81
        assert b'%nprocshared=48\n%mem=81GB\n' in files['water.gjf']


@pytest.mark.parametrize('with_default', [True, False])
def test_explicit_tier_preserves_complete_input_and_old_binding(default_cfg, tmp_path, with_default):
    if not with_default:
        del default_cfg['resources']['default_tier']
    study.init(default_cfg, 'defaults')
    args = arguments(tmp_path)
    source = args['input_path']
    source.write_bytes(b'%nprocshared=12\n%mem=18GB\n' + source.read_bytes())
    original = source.read_bytes()
    m = attempt.prepare(default_cfg, **args, tier='simple')
    path = attempt.find(default_cfg, m['attempt_id'])
    before = tree(path)
    original_files = attempt.verified_files(default_cfg, path, m)
    assert original_files['water.gjf'] == original
    assert (m['tier'], m['cores'], m['mem_gb']) == ('simple', 12, 24)
    assert not {'auto_nprocshared', 'auto_mem_gb', 'default_tier'} & m.keys()
    default_cfg['resources']['default_tier'] = 'mini'
    assert attempt.verified_files(default_cfg, path, m) == original_files
    assert tree(path) == before and source.read_bytes() == original


def test_changed_default_does_not_rebind_implicit_attempt(default_cfg, tmp_path):
    study.init(default_cfg, 'defaults')
    args = arguments(tmp_path)
    m = attempt.prepare(default_cfg, **args)
    path = attempt.find(default_cfg, m['attempt_id'])
    before = tree(path)
    files = attempt.verified_files(default_cfg, path, m)
    default_cfg['resources']['default_tier'] = 'mini'
    assert attempt.verified_files(default_cfg, path, m) == files
    assert tree(path) == before
    next_attempt = attempt.prepare(default_cfg, **args)
    assert (next_attempt['tier'], next_attempt['cores'], next_attempt['mem_gb']) == ('mini', 8, 16)


@pytest.mark.parametrize('value', ['', 'unknown', 'ultra', None, True, 3, [], {}])
def test_invalid_default_rejected(default_cfg, value):
    default_cfg['resources']['default_tier'] = value
    with pytest.raises(config.ConfigError, match='resources.default_tier'):
        config.validate_cluster(default_cfg)


@pytest.mark.parametrize('resource,value', [('cores', 49), ('cores', 0), ('mem_gb', 121), ('mem_gb', 0)])
def test_default_resource_limits_remain_enforced(default_cfg, resource, value):
    default_cfg['resources']['tiers']['max'][resource] = value
    with pytest.raises(config.ConfigError, match='Invalid resource tier: max'):
        config.validate_cluster(default_cfg)


@pytest.mark.parametrize('template', TEMPLATES)
def test_missing_tier_fails_before_node_lookup_or_allocation(cfg, tmp_path, monkeypatch, template):
    from ag import node_targeting
    args = arguments(tmp_path, template)
    study.init(cfg, 'defaults')
    before = tree(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('Missing tier must fail before node mapping')
    monkeypatch.setattr(node_targeting, 'prepare', forbidden)
    with pytest.raises(config.ConfigError, match='Select --tier'):
        attempt.prepare(cfg, **args)
    assert tree(tmp_path) == before


def test_selected_entry_does_not_borrow_another_default(default_cfg, tmp_path):
    peer = deepcopy(default_cfg)
    peer['resources'].pop('default_tier')
    peer['scheduler'] = 'slurm'
    for key in ('local', '_config_dir'):
        peer.pop(key)
    entries = dict(clusters={'default': default_cfg, 'batch': peer},
                   local=default_cfg['local'], _config_dir=default_cfg['_config_dir'])
    entries = config.load_config(write_config(entries))
    study.init(entries, 'defaults')
    args = arguments(tmp_path)
    before = tree(tmp_path)
    with pytest.raises(config.ConfigError, match='Select --tier'):
        attempt.prepare(entries, **args, cluster='batch')
    assert tree(tmp_path) == before
    entries['clusters']['batch']['resources']['default_tier'] = 'mini'
    m = attempt.prepare(entries, **args, cluster='batch')
    assert (m['cluster'], m['scheduler'], m['tier'], m['cores']) == ('batch', 'slurm', 'mini', 8)
    attempt.verified_files(entries, attempt.find(entries, m['attempt_id']), m)


def test_node_mapping_uses_effective_default(targeted):
    cfg, args = targeted
    args.pop('tier')
    cfg['resources']['default_tier'] = 'general'
    m = attempt.prepare(cfg, **args)
    assert m['tier'] == 'general' and m['cores'] == 24
    assert m['node_target']['fraction'] == '1/2'
    root = Path(cfg['local']['studies_root'])
    before = tree(root)
    cfg['resources']['default_tier'] = 'max'
    with pytest.raises(ValueError, match='Selected tier must match'):
        attempt.prepare(cfg, **args)
    assert tree(root) == before


def test_cli_omission_uses_entry_default(default_cfg, tmp_path, monkeypatch, capsys):
    study.init(default_cfg, 'defaults')
    args = arguments(tmp_path)
    monkeypatch.setattr(cli, 'load_config', lambda: default_cfg)
    command = ['prepare', '--study', 'defaults', '--template', 'gaussian', '--input', str(args['input_path']),
               '--walltime', '00:05:00', '--label', 'cli', '--method-basis', args['method_basis']]
    assert cli.main(command) == 0
    capsys.readouterr()
    path = Path(default_cfg['local']['studies_root']) / 'defaults/attempts/defaults-001-cli'
    assert attempt.read_manifest(path)['tier'] == 'max'
    before = tree(tmp_path)
    del default_cfg['resources']['default_tier']
    assert cli.main(command) != 0
    assert 'Select --tier' in capsys.readouterr().err
    assert tree(tmp_path) == before


def test_route_still_requires_explicit_tier(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(['route', '--template', 'gaussian'])
    assert error.value.code == 2
    assert '--tier' in capsys.readouterr().err
