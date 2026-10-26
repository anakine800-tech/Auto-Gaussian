"""T141: synthetic configuration, fake transport and baseline rendering bytes."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from ag import attempt, cli, clusters, config, doctor, render, route, study
from ag.transport import Result, SSHTransport, TransportError
from test_core import cfg, Fake, INPUT, write_config
from test_route import routed
from test_slurm import SlurmFake


def load(raw):
    # The existing test writer handles table-valued roots only.
    raw = deepcopy(raw)
    allowed = raw.pop('allowed_templates', None)
    path = write_config(raw)
    if allowed is not None:
        path.write_text('allowed_templates = ' + json.dumps(allowed) + '\n' + path.read_text())
    return config.load_config(path)


def gaussian_only(raw, mode='legacy', allowed=('gaussian',)):
    raw = deepcopy(raw)
    del raw['programs']['xtb']
    raw['allowed_templates'] = list(allowed)
    if mode == 'legacy':
        return raw, 'default'
    entry = {k: v for k, v in raw.items() if k not in ('local', '_config_dir')}
    if mode == 'slurm':
        entry.update(scheduler='slurm', partition='fixture')
    else:
        entry.update(scheduler='pbs', queue='batch')
    return dict(local=raw['local'], _config_dir=raw['_config_dir'],
                clusters={'gaussian-only': entry}), 'gaussian-only'


@pytest.mark.parametrize('mode', ['legacy', 'pbs', 'slurm'])
@pytest.mark.parametrize('allowed', [('gaussian',), ('gaussian-cp',), ('gaussian', 'gaussian-cp')])
def test_config_discovery_and_doctor(cfg, mode, allowed):
    raw, name = gaussian_only(cfg, mode, allowed)
    loaded = load(raw)
    selected = config.select_cluster(loaded, name)
    assert set(selected['programs']) == {'gaussian'}
    assert 'xtb' not in selected['programs']
    row = clusters.describe(loaded)['clusters'][0]
    assert row['programs_enabled'] == dict(gaussian=True, xtb=False, crest=False)
    fake = SlurmFake(selected) if mode == 'slurm' else Fake(selected)
    result = doctor.doctor(selected, fake)
    assert result['ok'] and result['programs'] == ['gaussian']
    executables = [c.text for c in fake.calls if c.operation == 'executable']
    assert len(executables) == 1 and '/g16' in executables[0]
    assert not {'submit', 'upload', 'create_attempt', 'cancel'} & set(fake.operations())


def test_clusters_cli_remains_local(cfg, monkeypatch, capsys):
    raw, _ = gaussian_only(cfg, 'pbs')
    loaded = load(raw)
    monkeypatch.setattr(cli, 'load_config', lambda: loaded)
    def forbidden(*args, **kwargs):
        pytest.fail('static discovery must not connect')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert cli.main(['clusters', '--json']) == 0
    captured = capsys.readouterr()
    assert not captured.err
    row = json.loads(captured.out)['clusters'][0]
    assert row['programs_enabled'] == dict(gaussian=True, xtb=False, crest=False)
    assert str(Path(cfg['_config_dir']).parent) not in captured.out


@pytest.mark.parametrize('allowed', [None, [], ['xtb'], ['crest'], ['gaussian', 'xtb'],
                                     ['gaussian', 'crest'], ['multiwfn']])
def test_missing_xtb_requires_explicit_gaussian_family(cfg, allowed):
    del cfg['programs']['xtb']
    if allowed is not None:
        cfg['allowed_templates'] = allowed
    with pytest.raises(config.ConfigError, match='programs.xtb.root'):
        load(cfg)


@pytest.mark.parametrize('field', ['g16root', 'xtb', 'crest'])
def test_no_placeholder_or_standalone_crest_escape(cfg, field):
    raw, _ = gaussian_only(cfg)
    if field == 'g16root':
        raw['programs']['gaussian']['g16root'] = '.'
    elif field == 'xtb':
        raw['programs']['xtb'] = {'root': ''}
    else:
        raw['programs']['crest'] = {'executable': '/synthetic/crest'}
    with pytest.raises(config.ConfigError):
        load(raw)


def test_missing_remote_gaussian_fails_without_writes(cfg):
    raw, name = gaussian_only(cfg)
    selected = config.select_cluster(load(raw), name)
    class MissingGaussian(Fake):
        def run(self, command):
            if command.operation == 'executable':
                self.calls.append(command)
                return Result(1)
            return super().run(command)
    fake = MissingGaussian(selected)
    with pytest.raises(TransportError, match='gaussian executable') as exc:
        doctor.doctor(selected, fake)
    assert selected['programs']['gaussian']['g16root'] not in str(exc.value)
    assert sum(c.operation == 'executable' for c in fake.calls) == 1
    assert not {'submit', 'upload', 'create_attempt'} & set(fake.operations())


@pytest.mark.parametrize('mode', ['legacy', 'pbs', 'slurm'])
def test_gaussian_prepare_and_template_refusal(cfg, tmp_path, mode):
    raw, name = gaussian_only(cfg, mode)
    loaded = load(raw)
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    study.init(loaded, 'water')
    root = Path(loaded['local']['studies_root'])
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    for template in ('xtb', 'crest', 'multiwfn', 'gaussian-cp'):
        with pytest.raises(ValueError, match='not allowed'):
            attempt.prepare(loaded, study_name='water', template=template, input_path=source,
                            tier='simple', walltime='00:30:00', label='sp',
                            cluster=name, method_basis='synthetic water fixture')
        assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    m = attempt.prepare(loaded, study_name='water', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='sp',
                        cluster=name, method_basis='synthetic water fixture')
    path = attempt.find(loaded, m['attempt_id'])
    script_name = 'job.slurm' if mode == 'slurm' else 'job.pbs'
    script = attempt.verified_files(loaded, path, m)[script_name].decode()
    assert 'ag_run g16' in script and 'GAUSS_SCRDIR="$scratch"' in script
    assert 'xtb' not in script and 'crest' not in script
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('template', ['gaussian', 'gaussian-cp', 'xtb', 'crest'])
def test_route_does_not_offer_disabled_programs(cfg, template):
    raw, name = gaussian_only(cfg, 'pbs', ('gaussian', 'gaussian-cp'))
    loaded = load(raw)
    loaded['routing'] = {'gaussian': [name], 'crest': [name]}
    result = route.suggest(loaded, template, 'simple')
    row = result['clusters'][0]
    assert row['name'] == name
    if template.startswith('gaussian'):
        assert row['conclusion'] != route.DENIED
    else:
        assert row['conclusion'] == route.DENIED
        assert result['recommendation'] is None


@pytest.mark.parametrize('independent', [False, True])
@pytest.mark.parametrize('explicit_gaussian', [False, True])
@pytest.mark.parametrize('mode', ['legacy', 'pbs', 'slurm'])
def test_full_config_keeps_all_doctor_checks(cfg, mode, independent, explicit_gaussian):
    if independent:
        cfg['programs']['crest'] = {'executable': '/synthetic/crest'}
    if explicit_gaussian:
        cfg['allowed_templates'] = ['gaussian']
    if mode != 'legacy':
        entry = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
        if mode == 'slurm':
            entry.update(scheduler='slurm', partition='fixture')
        cfg = dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters={'default': entry})
    selected = config.select_cluster(load(cfg))
    fake = SlurmFake(selected) if mode == 'slurm' else Fake(selected)
    result = doctor.doctor(selected, fake)
    assert result['programs'] == ['gaussian', 'xtb', 'crest']
    assert sum(c.operation == 'executable' for c in fake.calls) == 3
    if independent:
        assert any('/synthetic/crest' in c.text for c in fake.calls)


def test_add_entry_preserves_existing_four_and_routing(routed):
    before = load(routed)
    entry = deepcopy(routed['clusters']['default'])
    entry['ssh']['host'] = 'synthetic-gaussian-only'
    entry['allowed_templates'] = ['gaussian']
    del entry['programs']['xtb']
    routed['clusters']['gaussian-only'] = entry
    after = load(routed)
    assert len(after['clusters']) == 5
    assert after['routing'] == before['routing']
    for name, original in before['clusters'].items():
        assert after['clusters'][name] == original
    old_rows = clusters.describe(before)['clusters']
    new_rows = [r for r in clusters.describe(after)['clusters'] if r['name'] != 'gaussian-only']
    assert new_rows == old_rows


def render_case(scheduler, template, independent=False, platform=False):
    raw = dict(remote={'allowed_root': '/synthetic/work', 'ag_root': '/synthetic/work/ag'},
               scheduler={'queue': 'batch'},
               programs={'gaussian': {'g16root': '/synthetic/g16'},
                         'xtb': {'root': '/synthetic/chem'},
                         'multiwfn': '/synthetic/Multiwfn'})
    if scheduler == 'slurm':
        raw.update(scheduler='slurm', partition='fixture')
    if independent:
        raw['programs']['crest'] = {'executable': '/synthetic/crest'}
    if platform:
        raw['programs']['gaussian']['environment'] = 'scnet-a03'
    manifest = dict(cluster='default', scheduler=scheduler, study_id='water', attempt_id='water-001-sp',
                    remote_dir='water/water-001-sp', pbs_job_name='agsynthetic001',
                    template=template, template_params={}, cores=8, mem_gb=12, walltime='00:30:00')
    if template == 'xtb':
        manifest['template_params'] = {'--gfn': '2'}
    if template == 'crest':
        manifest['template_params'] = {'--gfn2': '', '--mdopt': ''}
    if template == 'multiwfn':
        manifest.update(template_params={'--analysis': 'igm', '--grid': 'low'},
                        science={'n_frames': 1, 'nci': {'analysis': 'igm', 'grid': 'low',
                                 'fragments': [{'atoms': [1]}, {'atoms': [2, 3]}]}})
    return raw, manifest


# SHA-256 generated from the exact v4.6.0 renderer at
# f7a27af01a66a195a42b3c4752369a7d18254975 using render_case above.
LEGACY_RENDER_HASHES = {('pbs', 'gaussian', False, False): '1ed6bb843452df72b775ec6d30e4c7657be26ee2042f3a4f323dacd1411ba675',
 ('pbs', 'gaussian-cp', False, False): '1ed6bb843452df72b775ec6d30e4c7657be26ee2042f3a4f323dacd1411ba675',
 ('pbs', 'xtb', False, False): '92b07f8fb92787cdaa467f58a057b9cf082754f3b6ff0ba3320f773fd1ef02f8',
 ('pbs', 'crest', False, False): '7eca6df110fbc5d5f94f34a0e910ab9509580ac5fb39b87d820af3db18299c48',
 ('slurm', 'gaussian', False, False): '763d2af2e0ad5e69b3eb7c53e72c588ad3c7669a6119fb540db4708dacad6633',
 ('slurm', 'gaussian-cp', False, False): '763d2af2e0ad5e69b3eb7c53e72c588ad3c7669a6119fb540db4708dacad6633',
 ('slurm', 'xtb', False, False): '28cf16014b4d03995dde2b98b86544a71235c9cb5f6e424f7191087fd1702b6f',
 ('slurm', 'crest', False, False): 'dae0b191d6da2af83c996cb8a7f2787b302cc2a165b3b3571cc64a47d4271dda',
 ('pbs', 'crest', True, False): '090798cecca45d80f4743e76a3e862db06fe391e0e0aaa88b93c055e07fcb3ab',
 ('slurm', 'crest', True, False): '26ac6c3357ecc699441ec5d9d6961e59a225a2817db6f49667c08d00ec841090',
 ('slurm', 'gaussian', False, True): 'ffbb218be41ba9eea0330aedfd8d1c03e0cc4bc04e34fee05a1d5f4521b50a16',
 ('slurm', 'gaussian-cp', False, True): 'ffbb218be41ba9eea0330aedfd8d1c03e0cc4bc04e34fee05a1d5f4521b50a16',
 ('pbs', 'multiwfn', False, False): 'e65a312d12f0f79281377a88291ffb44b398f95c9bddd3bea83c822a6003320a'}


@pytest.mark.parametrize('case,expected', LEGACY_RENDER_HASHES.items())
def test_full_config_render_bytes_match_v460(case, expected):
    raw, manifest = render_case(*case)
    text = render.render(raw, manifest, 'water.gjf')
    assert sha256(text.encode()).hexdigest() == expected


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('template', ['gaussian', 'gaussian-cp'])
def test_gaussian_only_render_matches_full_config(scheduler, template):
    raw, manifest = render_case(scheduler, template)
    expected = render.render(raw, manifest, 'water.gjf')
    raw['allowed_templates'] = [template]
    del raw['programs']['xtb']
    assert render.render(raw, manifest, 'water.gjf') == expected
