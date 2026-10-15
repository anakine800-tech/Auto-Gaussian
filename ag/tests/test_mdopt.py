"""Offline CREST 3 mdopt and same-method source merging; only synthetic water/butane."""
from dataclasses import replace
import json
import shlex
from pathlib import Path

import pytest

from ag import attempt, facts, geometry as geo, remote, render, study
from ag.cli import main
from test_core import cfg

WATER = '3\nMMFF energy=4 kcal/mol\nO 0 0 0\nH 0 0 0.96\nH 0.93 0 -0.24\n'


def prepare(cfg, tmp_path, contents=WATER * 2, params=None, name='ensemble.xyz'):
    study.init(cfg, 'smoke')
    source = tmp_path / name
    source.write_text(contents)
    return attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='crest', input_path=source,
                           params={'--gfn2': '', '--mdopt': ''} if params is None else params,
                           tier='simple', walltime='00:30:00', label='mdopt')


def test_prepare_mdopt_and_render_bind_input(cfg, tmp_path):
    m = prepare(cfg, tmp_path)
    path = attempt.find(cfg, m['attempt_id'])
    assert m['science']['n_frames'] == 2
    assert m['science']['n_atoms'] == 3
    assert (path / 'inputs' / 'ensemble.xyz').read_text() == WATER * 2
    line = next(line for line in (path / 'inputs' / 'job.pbs').read_text().splitlines()
                if line.startswith('ag_run crest'))
    assert shlex.split(line) == ['ag_run', 'crest', '--mdopt', 'ensemble.xyz', '--gfn2', '-T', '8', '>', 'crest.out']
    assert remote.output_names(m) == ['crest.out', 'crest_ensemble.xyz', 'ensemble_energies.log']
    assert remote.output_names({**m, 'scheduler': 'slurm'}) == ['crest.out', 'crest_ensemble.xyz', 'ensemble_energies.log', 'job.slurm.err']
    assert attempt.verified_files(cfg, path, m)['ensemble.xyz'] == (WATER * 2).encode()


@pytest.mark.parametrize('content', [
    WATER + '2\nwrong count\nO 0 0 0\nH 0 0 1\n',
    WATER + WATER.replace('O 0 0 0', 'C 0 0 0'),
    WATER + WATER.replace('O 0 0 0\nH 0 0 0.96', 'H 0 0 0\nO 0 0 0.96'),
    WATER * 1001, WATER + WATER[:-6], '',
    *[WATER + WATER.replace('0.96', bad) for bad in ('nan', 'inf', '-inf', '1e999', '1_0')],
])
def test_prepare_rejects_bad_mdopt_without_attempt(cfg, tmp_path, content):
    with pytest.raises(ValueError):
        prepare(cfg, tmp_path, content)
    assert not list((Path(cfg['local']['studies_root']) / 'smoke' / 'attempts').iterdir())


def test_mdopt_limit_inclusive(cfg, tmp_path):
    assert prepare(cfg, tmp_path, WATER * 1000)['science']['n_frames'] == 1000


def test_mdopt_input_output_collision(cfg, tmp_path):
    with pytest.raises(ValueError, match='collide'):
        prepare(cfg, tmp_path, name='crest_ensemble.xyz')


@pytest.mark.parametrize('template', ['crest', 'xtb'])
def test_non_mdopt_single_frame_unchanged(cfg, tmp_path, template):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.xyz'
    source.write_text(WATER)
    kwargs = dict(study_name='smoke', template=template, input_path=source,
                  tier='simple', walltime='00:30:00', label='single')
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', **kwargs)
    assert m['science']['n_atoms'] == 3
    assert 'n_frames' not in m['science']
    if template == 'crest':
        assert remote.output_names(m) == ['crest.out', 'crest_conformers.xyz', 'crest.energies', 'crest_best.xyz']
    source.write_text(WATER * 2)
    with pytest.raises(ValueError, match='atom count'):
        attempt.prepare(cfg, method_basis='兜底方法：合成测试', **kwargs)


@pytest.mark.parametrize('template,params', [('xtb', {'--mdopt': ''}), ('crest', {'--mdopt': 'file.xyz'}),
                                           ('crest', {'--mdopt': 'true'})])
def test_mdopt_allowlist(template, params):
    with pytest.raises(ValueError):
        render.parameters(template, params)


def output_attempt(cfg, tmp_path):
    m = prepare(cfg, tmp_path)
    path = attempt.find(cfg, m['attempt_id'])
    (path / 'outputs' / 'crest.out').write_text('CREST terminated normally.\n')
    # Unsorted output, matching CREST 3.0.2 wrensemble's energy comment format.
    (path / 'outputs' / 'crest_ensemble.xyz').write_text(
        WATER.replace('MMFF energy=4 kcal/mol', '  -5.00000000  ') +
        WATER.replace('MMFF energy=4 kcal/mol', '  -5.00100000  ').replace('0.96', '0.97'))
    return path


def test_mdopt_facts_export_and_dedup(cfg, tmp_path, capsys):
    path = output_attempt(cfg, tmp_path)
    result = facts.build_facts(path)
    assert result['conformer_energies_hartree'] == [-5.0, -5.001]
    assert result['best_energy'] == -5.001
    assert result['relative_energies_kcal'] == pytest.approx([0.001 * geo.HARTREE_TO_KCAL, 0])
    frames = geo.read_xyz(path / result['ensemble_geometry'])
    assert [f.energy for f in frames] == [-5.0, -5.001]
    assert frames[1].coordinates[1][2] == 0.97
    assert facts.build_facts(path) == result
    assert main(['dedup', '--source', f'etkdg={path / "mdopt.xyz"}', '--representative', 'lowest',
                 '--window', '6', '--charge', '0', '--out', str(tmp_path / 'analysis'), '--json']) == 0
    merged = json.loads(capsys.readouterr().out)
    assert merged['kept'][0]['energy'] == -5.001
    assert merged['kept'][0]['sources'] == ['etkdg']
    assert merged['energy_basis'] == 'shared_hartree'
    (path / 'outputs' / 'crest_ensemble.xyz').write_text(
        (path / 'outputs' / 'crest_ensemble.xyz').read_text().replace('-5.00100000', '-5.00200000'))
    with pytest.raises(ValueError, match='facts.json 内容不同'):
        facts.build_facts(path)


@pytest.mark.parametrize('bad', ['  1.00000000 !failed', 'nan', '-5 kcal/mol', 'no energy', '1e999'])
def test_mdopt_bad_energy_never_exported(cfg, tmp_path, bad):
    path = output_attempt(cfg, tmp_path)
    output = path / 'outputs' / 'crest_ensemble.xyz'
    output.write_text(output.read_text().replace('  -5.00100000  ', bad))
    with pytest.raises(ValueError):
        facts.build_facts(path)
    assert not (path / 'mdopt.xyz').exists()


@pytest.mark.parametrize('change', ['missing', 'count', 'elements', 'coordinate'])
def test_mdopt_incomplete_or_malformed(cfg, tmp_path, change):
    path = output_attempt(cfg, tmp_path)
    output = path / 'outputs' / 'crest_ensemble.xyz'
    if change == 'missing':
        output.unlink()
    elif change == 'count':
        output.write_text('3\n' + output.read_text().split('3\n')[1])
    elif change == 'elements':
        output.write_text(output.read_text().replace('H 0 0 0.97', 'C 0 0 0.97'))
    else:
        output.write_text(output.read_text().replace('0.97', 'nan'))
    with pytest.raises((ValueError, FileNotFoundError)):
        facts.build_facts(path)


def test_lowest_source_merge_window_provenance_and_cluster(tmp_path, capsys):
    original = geo.read_xyz(Path(__file__).parent / 'data' / 'butane.xyz')
    crest = [replace(original[0], energy=-9.98), replace(original[1], energy=-9.98)]
    etkdg = [replace(original[0], energy=-10.001)]
    for label, frames in [('crest', crest), ('etkdg', etkdg)]:
        geo.write_xyz(tmp_path / f'{label}.xyz', frames)
    args = ['dedup', '--source', f'crest={tmp_path / "crest.xyz"}', '--source', f'etkdg={tmp_path / "etkdg.xyz"}',
            '--representative', 'lowest', '--window', '6', '--charge', '0', '--out', str(tmp_path), '--json']
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result['kept']) == 1
    assert result['kept'][0]['energy'] == -10.001
    # Same geometry cannot attach the crest provenance across a > --de gap.
    assert result['kept'][0]['sources'] == ['etkdg']
    assert len(result['kept'][0]['members']) == 1
    assert [r['reason'] for r in result['excluded']] == ['energy_window', 'energy_window']
    assert main(['cluster', result['output'], '--representative', 'lowest', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['representatives'][0]['energy'] == -10.001
    (tmp_path / 'etkdg.xyz').write_text(geo.xyz_text([replace(etkdg[0], energy_unit='kcal/mol')]))
    assert main(args) == 1
    assert 'Hartree' in capsys.readouterr().err


def test_constrained_mdopt_bundle_revalidation(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'ensemble.xyz'
    source.write_text(WATER * 2)
    constraints = tmp_path / 'water.inp'
    constraints.write_text('$constrain\n distance: 1, 2, 0.96\n$end\n')
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='crest', input_path=source,
                        params={'--mdopt': '', '--gfn2': ''}, constraints=constraints,
                        tier='simple', walltime='00:30:00', label='constrained')
    path = attempt.find(cfg, m['attempt_id'])
    assert attempt.verified_files(cfg, path, m)['constraints.inp'] == constraints.read_bytes()
    assert '2 frames' in attempt.summary(cfg, m)


def test_mdopt_fetch_collects_only_mode_outputs(cfg, tmp_path):
    from ag.fetch import fetch
    from ag import state
    from test_core import Fake
    m = prepare(cfg, tmp_path)
    path = attempt.find(cfg, m['attempt_id'])
    # Synthetic finished state: no scheduler or real configuration is consulted.
    (path / 'status.json').write_text(json.dumps({'state': 'finished', 'exit_status': 0}))
    fake = Fake(cfg)
    fake.files = {'crest.out': b'CREST terminated normally.\n', 'ensemble_energies.log': b'synthetic energy log\n',
                  'crest_ensemble.xyz': WATER.replace('MMFF energy=4 kcal/mol', '-5').encode() * 2}
    result = fetch(cfg, path, fake)
    assert result['files'] == ['crest.out', 'crest_ensemble.xyz', 'ensemble_energies.log']
    assert state.read(path)['state'] == 'fetched'
    assert facts.build_facts(path)['n_conformers'] == 2


@pytest.mark.parametrize('failed_frames', [(2,), (1, 3)])
def test_mdopt_reports_all_failed_frame_indices(cfg, tmp_path, failed_frames):
    path = output_attempt(cfg, tmp_path)
    manifest = json.loads((path / 'manifest.json').read_text())
    manifest['science']['n_frames'] = 3
    (path / 'manifest.json').write_text(json.dumps(manifest))
    contents = ''.join(WATER.replace('MMFF energy=4 kcal/mol',
                                    '1.00000000 !failed' if index in failed_frames else '-5.00000000')
                       for index in range(1, 4))
    (path / 'outputs' / 'crest_ensemble.xyz').write_text(contents)
    with pytest.raises(ValueError) as error:
        facts.build_facts(path)
    indices = ', '.join(map(str, failed_frames))
    assert str(error.value) == (f'CREST mdopt contains failed optimizations in frames (1-based): '
                                f'{indices}; review before dedup')
    assert not (path / 'mdopt.xyz').exists()
    assert not (path / 'facts.json').exists()
