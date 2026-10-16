import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from ag.facts import build_facts, resolve_attempt
from ag._parse_outputs import imaginary_modes, parse_gaussian, parse_crest, parse_xtb

FIXTURES = Path(__file__).parent / 'fixtures'


def attempt(tmp_path, name='water', fixture='water_opt_freq.log', template='gaussian'):
    directory = tmp_path / 'attempts' / name
    (directory / 'outputs').mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({
        'template': template, 'inputs': [{'name': 'input.gjf'}]}))
    if fixture:
        shutil.copyfile(FIXTURES / fixture, directory / 'outputs' / 'input.log')
    return directory


@pytest.mark.parametrize('fixture,n_atoms', [('water_opt_freq.log', 3),
    ('butane_anti_freq.log', 14), ('butane_gauche_freq.log', 14)])
def test_real_small_molecule_facts(tmp_path, fixture, n_atoms):
    directory = attempt(tmp_path, fixture=fixture)
    facts = build_facts(directory)
    text = (FIXTURES / fixture).read_text()
    expected_scf = float(re.findall(r'SCF Done:.*?=\s*([-\d.]+)', text)[-1])
    assert abs(facts['energies']['scf'] - expected_scf) < 1e-6
    for key, label in [('e_thermal', 'Energies'), ('h', 'Enthalpies'), ('g', 'Free Energies')]:
        expected = float(re.findall(r'Sum of electronic and thermal ' + label + r'=\s*([-\d.]+)', text)[-1])
        assert abs(facts['energies'][key]-expected) < 1e-6
    assert facts['n_atoms'] == n_atoms
    assert facts['n_imag'] == 0 and facts['imag_modes'] == []
    assert facts['monatomic'] is False
    assert facts['n_vibrational_modes'] == facts['expected_vibrational_modes'] == 3 * n_atoms - 6
    assert facts['vibrational_modes_complete'] is True
    assert facts['termination'] == 'normal'
    assert facts['charge'] == 0 and facts['multiplicity'] == 1
    assert facts['route'].startswith('#')
    assert json.loads((directory / 'facts.json').read_text()) == facts
    assert int((directory / 'final.xyz').read_text().splitlines()[0]) == n_atoms
    assert facts['opt_converged'] is True
    assert facts['freq_step_converged'] is True
    assert len(facts['freq_step_convergence']['criteria']) == 4


@pytest.mark.parametrize('filename,state,hint', [
    ('error_l9999.log', 'error', 'L9999'), ('error_l502.log', 'error', 'L502'),
    ('incomplete.log', 'incomplete', None)])
def test_fragments(filename, state, hint):
    facts, _ = parse_gaussian(FIXTURES / filename)
    assert facts['termination'] == state
    assert hint in facts['error_hint'] if hint else facts['error_hint'] is None


def test_walltime_and_error_precedence(tmp_path):
    log = tmp_path / 'partial.log'
    pbs = tmp_path / 'job.pbs.out'
    log.write_text('Partial calculation\n')
    pbs.write_text('PBS: job killed: walltime exceeded limit\n')
    assert parse_gaussian(log, pbs)[0]['error_hint'] == 'walltime'
    log.write_text('Normal termination of Gaussian\nError termination via Lnk1e in PATH/l123.exe\n')
    facts, _ = parse_gaussian(log)
    assert facts['termination'] == 'error' and facts['error_hint'] == 'L123（line 2）'


def test_imaginary_mode_distance_derivative():
    result = imaginary_modes([-100, 20], [[[1,0,0],[-1,0,0],[0,0,0]], [[0,0,0]]*3],
                             [[0,0,0],[1,0,0],[5,0,0]], ['C','H','H'])
    assert len(result) == 1
    pair = result[0]['pairs'][0]
    assert pair == {'atoms': [1,2], 'elements': ['C','H'], 'distance': 1.0,
                    'distance_change_rate': -2.0}
    # A rigid translation does not change pair distances.
    result = imaginary_modes([-1], [[[1,2,3]]*3], [[0,0,0],[1,0,0],[0,1,0]], ['H']*3)
    assert all(p['distance_change_rate'] == 0 for p in result[0]['pairs'])


def test_synthetic_crest_relative_units(tmp_path):
    (tmp_path/'crest.out').write_text('CREST terminated normally.\n')
    (tmp_path/'crest.energies').write_text('1 0.000\n2 0.628\n')
    (tmp_path/'crest_conformers.xyz').write_text('1\n-1.000\nH 0 0 0\n1\n-0.999\nH 1 0 0\n')
    facts, xyz = parse_crest(tmp_path)
    assert facts['relative_energies_kcal'] == [0, 0.628]
    assert facts['best_energy'] == -1 and facts['n_conformers'] == 2
    assert facts['termination'] == 'normal' and xyz.startswith('1\n')
    (tmp_path/'crest.energies').write_text('1 0.000\n')
    with pytest.raises(ValueError, match='counts differ'):
        parse_crest(tmp_path)


def test_xtb(tmp_path):
    (tmp_path/'xtb.out').write_text('| TOTAL ENERGY -5.123D+00 Eh |\nGEOMETRY OPTIMIZATION CONVERGED\nnormal termination of xtb\n')
    (tmp_path/'xtbopt.xyz').write_text('1\nenergy\nH 0 0 0\n')
    facts, xyz = parse_xtb(tmp_path)
    assert facts['total_energy'] == -5.123 and facts['converged']
    assert facts['termination'] == 'normal' and xyz.startswith('1\n')


def test_cli_and_resolution(tmp_path, capsys):
    from ag.cli import main
    directory = attempt(tmp_path)
    assert resolve_attempt('water', str(tmp_path)) == directory.resolve()
    assert main(['facts', 'water', '--study', str(tmp_path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['n_imag'] == 0


def test_cli_registration_does_not_import_chemistry():
    script = '''
import sys
class BlockChem:
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in {'cclib','goodvibes','numpy','rdkit'}:
   raise AssertionError('eager chemistry import: ' + fullname)
sys.meta_path.insert(0, BlockChem())
from ag.cli import main
try:
 main(['--help'])
except SystemExit as exc:
 assert exc.code == 0
'''
    subprocess.run([sys.executable, '-c', script], check=True, capture_output=True)


@pytest.mark.skipif(not os.getenv('AG_LOCAL_FIXTURES'), reason='Private local logs are opt-in')
def test_private_ts_and_optional_irc():
    root = Path(os.environ['AG_LOCAL_FIXTURES'])
    logs = sorted(root.glob('ts*.log'))
    assert len(logs) == 3, 'Provide exactly three ts*.log files in AG_LOCAL_FIXTURES'
    for path in logs:
        facts, geometry = parse_gaussian(path)
        assert facts['termination'] == 'normal'
        assert facts['n_imag'] == 1 and len(facts['imag_modes']) == 1
        assert geometry and facts['imag_modes'][0]['pairs']
        assert isinstance(facts['imag_modes'][0]['pairs'][0]['distance_change_rate'], float)
        review_path = path.with_suffix('.review.json')
        if review_path.exists():
            review = json.loads(review_path.read_text())
            assert review['confirmed'] is True
            assert hashlib.sha256(path.read_bytes()).hexdigest() == review['source_sha256']
            expected = {tuple(sorted(pair)) for pair in review['expected_pairs']}
            observed = {tuple(pair['atoms']) for pair in facts['imag_modes'][0]['pairs'][:len(expected)]}
            assert expected and observed == expected
    for path in root.glob('irc*.log'):
        facts, geometry = parse_gaussian(path)
        assert facts['termination'] in {'normal', 'error', 'incomplete'}
        assert isinstance(facts['energies'], dict) and geometry


@pytest.mark.parametrize('text,expected', [('<S**2> = 0.7501', 0.7501),
    ('S**2 before annihilation     0.7510, after     0.7500', 0.751)])
def test_spin_expectation(tmp_path, text, expected):
    path = tmp_path/'spin.log'
    path.write_text(text)
    assert parse_gaussian(path)[0]['s2'] == expected


def test_monatomic_freq_and_regeneration(tmp_path, capsys):
    from ag.cli import main
    directory = attempt(tmp_path, fixture='fluoride_freq_synthetic.log')
    # Explicit refresh preserves an older derived record and the original log.
    (directory / 'facts.json').write_text('{"n_imag": null}')
    original = (directory / 'outputs/input.log').read_bytes()
    assert main(['facts', str(directory), '--json', '--refresh']) == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts['parser_warning'] is None
    assert (facts['n_atoms'], facts['charge'], facts['multiplicity']) == (1, -1, 1)
    assert facts['monatomic'] is True and facts['n_imag'] == 0
    assert facts['n_vibrational_modes'] == facts['expected_vibrational_modes'] == 0
    assert facts['vibrational_modes_complete'] is True
    assert facts['frequencies_low'] == facts['imag_modes'] == []
    assert facts['frequency_note'] == '单原子无振动模式'
    assert facts['energies']['g'] == -99.013
    assert build_facts(directory) == facts
    assert (directory / 'outputs/input.log').read_bytes() == original


@pytest.mark.parametrize('problem', ['sp', 'incomplete', 'error', 'no_thermo', 'partial_thermo', 'parse_failure'])
def test_monatomic_zero_requires_completed_frequency_thermochemistry(tmp_path, monkeypatch, problem):
    text = (FIXTURES / 'fluoride_freq_synthetic.log').read_text()
    if problem == 'sp':
        text = text.replace(' Freq', ' SP')
    elif problem == 'incomplete':
        text = text.replace('Normal termination of Gaussian', '')
    elif problem == 'error':
        text += '\n Error termination\n'
    elif problem == 'no_thermo':
        text = text.split(' - Thermochemistry -')[0] + '\n Normal termination of Gaussian\n'
    elif problem == 'partial_thermo':
        text = '\n'.join(line for line in text.splitlines() if 'Free Energies=' not in line)
    else:
        import cclib.io
        monkeypatch.setattr(cclib.io, 'ccread', lambda *a, **kw: None)
    path = tmp_path / 'atom.log'
    path.write_text(text)
    facts, _ = parse_gaussian(path)
    assert facts['n_imag'] is None
    assert facts['n_vibrational_modes'] is None
    assert facts['vibrational_modes_complete'] is not True
    assert facts['frequency_note'] is None


@pytest.mark.parametrize('coordinates,mode_count,expected', [
    ([(0, 0, -1), (0, 0, 1)], 1, 1),
    ([(2, 3, 4), (3, 4, 5), (4, 5, 6)], 4, 4),
    ([(2, 3, 4), (3, 4, 5), (4, 5, 6)], 3, 4),
    ([(0, 0, 0), (1, 0, 0), (2, 0.001, 0)], 3, 3),
    ([(0, 0, 0), (1, 0.000001, 0), (2, 0, 0)], 4, 4),
    ([(0, 0, -1), (0, 0, 1)], 0, 1),
])
def test_geometry_based_mode_completeness(tmp_path, coordinates, mode_count, expected):
    # Minimal synthetic H2 / three-atom parser output, including a rotated line.
    atoms = '\n'.join(f' {i} 1 0 {x:.6f} {y:.6f} {z:.6f}'
                      for i, (x, y, z) in enumerate(coordinates, 1))
    text = ('Gaussian, Inc.\n --------------------\n #p HF/STO-3G Freq\n --------------------\n'
            ' Input orientation:\n --------------------\n'
            ' Center Atomic Atomic Coordinates (Angstroms)\n Number Number Type X Y Z\n'
            f' --------------------\n{atoms}\n --------------------\n')
    if mode_count:
        text += ' Harmonic frequencies (cm**-1)\n'
        for start in range(0, mode_count, 3):
            text += ' Frequencies -- ' + ' '.join(['100.0'] * min(3, mode_count - start)) + '\n'
        text += '\n'
    text += ' Normal termination of Gaussian\n'
    path = tmp_path / 'molecule.log'
    path.write_text(text)
    facts, _ = parse_gaussian(path)
    assert facts['parser_warning'] is None
    assert facts['expected_vibrational_modes'] == expected
    assert facts['n_vibrational_modes'] == (mode_count or None)
    assert facts['vibrational_modes_complete'] is (mode_count == expected)
    assert facts['n_imag'] == (0 if mode_count else None)
    assert facts['monatomic'] is False


def test_missing_geometry_does_not_guess_mode_count():
    from ag._parse_outputs import expected_vibrational_modes
    assert expected_vibrational_modes(3, None) is None
    assert expected_vibrational_modes(3, [[0, 0, 0]] * 3) is None


@pytest.mark.parametrize('scheduler,filename', [('pbs', 'job.pbs.out'), ('slurm', 'job.slurm.err')])
@pytest.mark.parametrize('marker_location', ['program', 'scheduler', 'both', 'neither', 'missing'])
def test_xtb_termination_sources(tmp_path, scheduler, filename, marker_location):
    directory = attempt(tmp_path, fixture=None, template='xtb')
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['scheduler'] = scheduler
    manifest_path.write_text(json.dumps(manifest))
    outputs = directory / 'outputs'
    marker = 'normal termination of xtb\n'
    (outputs / 'xtb.out').write_text('finished run\n' +
                                   (marker if marker_location in ('program', 'both') else ''))
    if marker_location != 'missing':
        (outputs / filename).write_text(marker if marker_location in ('scheduler', 'both') else '')
    # An unrelated scheduler's file must not supply evidence for this attempt.
    other = 'job.slurm.err' if scheduler == 'pbs' else 'job.pbs.out'
    (outputs / other).write_text(marker + 'killed\n')
    facts = build_facts(directory)
    sources = (['xtb.out'] if marker_location in ('program', 'both') else [])
    sources += [filename] if marker_location in ('scheduler', 'both') else []
    assert facts['termination'] == ('normal' if sources else 'incomplete')
    assert facts['termination_marker_sources'] == sources
    assert facts['scheduler_output'] == {'file': filename, 'available': marker_location != 'missing'}
    assert bool(facts['termination_warning']) == (marker_location == 'missing')
    assert json.loads((directory / 'facts.json').read_text()) == facts


@pytest.mark.parametrize('filename', ['job.pbs.out', 'job.slurm.err'])
@pytest.mark.parametrize('error', [
    'PBS: job killed: walltime exceeded limit',
    'JOB CANCELLED DUE TO TIME LIMIT',
    'Killed', 'signal SIGTERM', 'oom_kill event', 'fatal error', '[ERROR] stopped',
])
def test_xtb_scheduler_error_overrides_normal(tmp_path, filename, error):
    (tmp_path / 'xtb.out').write_text('normal termination of xtb\n')
    (tmp_path / filename).write_text('normal termination of xtb\n' + error)
    facts, _ = parse_xtb(tmp_path, filename)
    assert facts['termination'] == 'error'
    assert facts['termination_marker_sources'] == ['xtb.out', filename]
    if 'walltime' in error:
        assert facts['error_hint'] == 'walltime'


def test_xtb_program_error_overrides_scheduler_marker(tmp_path):
    (tmp_path / 'xtb.out').write_text('[ERROR] optimization failed\n')
    (tmp_path / 'job.pbs.out').write_text('normal termination of xtb\n')
    assert parse_xtb(tmp_path)[0]['termination'] == 'error'


@pytest.mark.parametrize('body,link,hint,line', [
    (' Number of steps exceeded', '9999', 'L9999: 优化步数用完', 2),
    (' Optimization stopped.\n Maximum number of optimization steps reached',
     '9999', 'L9999: 优化步数用完', 3),
    (' Wrong number of Negative eigenvalues: Desired=1 Actual=0',
     '9999', 'L9999: TS 曲率不符：负本征值数与期望不符', 2),
    (' Convergence failure -- run terminated.', '502', 'L502: SCF 不收敛', 2),
    (' SCF has not converged', '9999', 'L9999: SCF 不收敛', 2),
    (' Optimization stopped.', '9999', 'L9999: 优化未完成（原因见日志）', 3),
    (' Maximum number of corrector steps exceeded', '123', 'L123: IRC 校正失败', 2),
    (' Maximum number of corrector steps exceeded', None, 'IRC 校正失败', 2),
    (' No recognized cause', '123', 'L123', 3),
    (' No recognized cause', '502', 'L502', 3),
    (' SCF has not converged', None, 'SCF 不收敛', 2),
])
def test_error_hint_uses_cause_and_original_line(tmp_path, body, link, hint, line):
    # Prevent a link-only diagnosis from recommending the wrong recovery action.
    text = 'Synthetic termination fragment.\n' + body + '\n'
    text += f' Error termination via Lnk1e in PATH/l{link}.exe\n' if link else ''
    log = tmp_path / 'synthetic.log'
    log.write_text(text)
    facts, _ = parse_gaussian(log)
    assert facts['termination'] == ('error' if link else 'incomplete')
    assert facts['error_hint'] == f'{hint}（line {line}）'
    assert text.splitlines()[line - 1].strip()


def test_walltime_hint_and_state_remain_unchanged():
    # Scheduler walltime remains its existing keyword, not a Gaussian log line.
    from ag._parse_outputs import termination
    text = ' Number of steps exceeded\n Error termination via Lnk1e in PATH/l9999.exe\n'
    assert termination(text, 'Normal termination', '\nwalltime exceeded limit\n') == {
        'termination': 'error', 'error_hint': 'walltime'}
    assert termination('partial', 'Normal termination', 'walltime exceeded limit') == {
        'termination': 'incomplete', 'error_hint': 'walltime'}


def test_last_explicit_cause_wins_within_section(tmp_path):
    # An earlier SCF diagnostic must not hide the terminal curvature failure.
    log = tmp_path / 'synthetic.log'
    log.write_text(' SCF has not converged\n'
                   ' Wrong number of Negative eigenvalues: Desired=1 Actual=0\n'
                   ' Error termination via Lnk1e in PATH/l9999.exe\n')
    facts, _ = parse_gaussian(log)
    assert facts['termination'] == 'error'
    assert facts['error_hint'] == 'L9999: TS 曲率不符：负本征值数与期望不符（line 2）'
