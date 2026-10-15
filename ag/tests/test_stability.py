"""T30: synthetic diagnostics and local prepare; no Gaussian/remote execution."""
from hashlib import sha256
import json

import pytest

from ag import attempt, study
from ag._parse_outputs import parse_gaussian
from ag.cli import main
from test_core import INPUT, cfg


STABLE = ' The wavefunction is stable under the perturbations considered.'
INTERNAL = ' The wavefunction has an internal instability.'
RHF_UHF = ' The wavefunction has an RHF -> UHF instability.'
HEADER = 'Gaussian, Inc.\n --------------------\n #p HF/STO-3G Stable\n --------------------\n'
NORMAL = '\n Normal termination of Gaussian\n'


def parse(tmp_path, body, ending=NORMAL):
    path = tmp_path / 'synthetic.log'
    path.write_text(HEADER + body + ending)
    return parse_gaussian(path)[0]


@pytest.mark.parametrize('line,expected', [
    (STABLE, 'stable'), (INTERNAL, 'internal_instability'), (RHF_UHF, 'rhf_to_uhf'),
    ('\t' + STABLE.upper() + '  ', 'stable'),
    (' The wavefunction has an RHF->UHF instability.', 'rhf_to_uhf'),
    (' The wavefunction has a real -> complex instability.', 'unknown'),
    (' The wavefunction is stable under the perturbations', 'unknown'),
])
def test_diagnostic_and_exact_evidence(tmp_path, line, expected):
    facts = parse(tmp_path, line)
    assert facts['wavefunction_stability'] == expected
    assert facts['wavefunction_stability_line'] == line
    assert facts['termination'] == 'normal'


@pytest.mark.parametrize('body', ['', ' SCF Done: E(RHF) = -1.0 A.U.',
    ' Stable=Opt', ' stable', ' The wavefunctionish is stable.',
    ' Title: The wavefunction is stable under the perturbations considered.'])
def test_no_diagnostic_is_unknown_even_when_normal(tmp_path, body):
    facts = parse(tmp_path, body)
    assert facts['wavefunction_stability'] == 'unknown'
    assert facts['wavefunction_stability_line'] is None


@pytest.mark.parametrize('lines,expected', [
    ([INTERNAL, RHF_UHF, STABLE], 'stable'),
    ([STABLE, INTERNAL], 'internal_instability'),
    ([INTERNAL, RHF_UHF], 'rhf_to_uhf'),
    ([STABLE, ' The wavefunction has an unrecognized instability.'], 'unknown'),
    ([STABLE, ' The wavefunction is stable under'], 'unknown'),
])
def test_last_diagnostic_wins(tmp_path, lines, expected):
    facts = parse(tmp_path, '\n'.join(lines))
    assert facts['wavefunction_stability'] == expected
    assert facts['wavefunction_stability_line'] == lines[-1]


@pytest.mark.parametrize('boundary', [
    ' #p HF/STO-3G Stable=Opt\n --------------------',
    ' --Link1--', ' Link1:  Proceeding to internal job step number 2.',
    ' Entering Gaussian System, Link 0=g16',
])
@pytest.mark.parametrize('last', ['', INTERNAL])
def test_new_job_does_not_inherit_old_stability(tmp_path, boundary, last):
    facts = parse(tmp_path, STABLE + NORMAL + boundary + '\n' + last)
    assert facts['wavefunction_stability'] == ('internal_instability' if last else 'unknown')
    assert facts['wavefunction_stability_line'] == (last or None)


@pytest.mark.parametrize('ending,state', [('', 'incomplete'), ('\n Error termination\n', 'error')])
@pytest.mark.parametrize('line,expected', [(STABLE, 'stable'), (INTERNAL, 'internal_instability'), ('', 'unknown')])
def test_diagnostic_does_not_override_termination(tmp_path, ending, state, line, expected):
    facts = parse(tmp_path, line, ending)
    assert facts['termination'] == state
    assert facts['wavefunction_stability'] == expected
    assert facts['wavefunction_stability_line'] == (line or None)


@pytest.mark.parametrize('failure', ['none', 'exception'])
def test_text_diagnostic_survives_cclib_failure(tmp_path, monkeypatch, failure):
    import cclib.io

    def failed_parse(*args, **kwargs):
        if failure == 'exception':
            raise ValueError('Synthetic truncated output')
        return None

    monkeypatch.setattr(cclib.io, 'ccread', failed_parse)
    facts = parse(tmp_path, RHF_UHF)
    assert facts['parser_warning']
    assert facts['wavefunction_stability'] == 'rhf_to_uhf'
    assert facts['wavefunction_stability_line'] == RHF_UHF


@pytest.mark.parametrize('keyword', ['stable', 'stable=opt', 'Stable', 'Stable=Opt'])
def test_prepare_and_facts_cli(cfg, tmp_path, capsys, keyword):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace(' SP', ' ' + keyword))
    manifest = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:05:00', label='stable')
    path = attempt.find(cfg, manifest['attempt_id'])
    persisted = attempt.read_manifest(path)
    assert persisted == manifest
    assert manifest['science']['route'] == '# B3LYP/6-31G(d) ' + keyword
    assert 'qst_mode' not in manifest['science'] and 'scan' not in manifest['science']
    assert attempt.verified_files(cfg, path, manifest)['water.gjf'] == source.read_bytes()
    assert next(row for row in manifest['inputs'] if row['name'] == 'water.gjf')['sha256'] == sha256(source.read_bytes()).hexdigest()
    assert manifest['science']['route'] in attempt.summary(cfg, manifest)
    log = path / 'outputs' / 'water.log'
    log.write_text(HEADER.replace('Stable', keyword) + INTERNAL + '\n' + STABLE + NORMAL)
    # facts may be regenerated, but input/manifest/status/output bytes stay unchanged.
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()}
    first_facts = None
    for _ in range(2):
        assert main(['facts', str(path), '--json']) == 0
        facts = json.loads(capsys.readouterr().out)
        assert facts['wavefunction_stability'] == 'stable'
        assert facts['wavefunction_stability_line'] == STABLE
        assert json.loads((path / 'facts.json').read_text()) == facts
        current_facts = ((path / 'facts.json').read_bytes(), (path / 'facts.json').stat().st_mtime_ns)
        if first_facts is not None:
            assert current_facts == first_facts
        first_facts = current_facts
    after = {p.relative_to(path): p.read_bytes() for p in path.rglob('*')
             if p.is_file() and p.name not in ('facts.json', '.facts.lock')}
    assert after == before
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('keyword', ['stable', 'stable=opt'])
@pytest.mark.parametrize('old,new,error', [
    (' SP', ' SP External=fixture', 'External programs'),
    (' SP', ' SP Geom=AllCheck', 'Geom=Check'),
    ('%chk=water.chk', '%chk=../water.chk', 'plain filename'),
    ('%chk=water.chk', '%oldchk=parent.chk\n%chk=water.chk', 'parent chk attachment'),
    ('%nprocshared=8', '%nprocshared=22', 'resource tier'),
    ('%mem=10GB', '%mem=12GB', '85%'),
    ('O 0 0 0', 'O 0 0', 'Cartesian'),
    ('0 1', '0 0', 'multiplicity'),
    ('Water smoke', '@other.gjf', 'includes'),
    ('Water smoke', '--Link1--', 'Link1'),
])
def test_stable_prepare_preserves_rejections(cfg, tmp_path, keyword, old, new, error):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace(old, new).replace(' SP', ' ' + keyword))
    with pytest.raises(ValueError, match=error):
        attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:05:00', label='stable')


# Gaussian build_facts keys from main a426ca9 (including T32), before T30. A literal baseline
# keeps this regression runnable in source archives without Git or a remote.
MAIN_GAUSSIAN_FACT_KEYS = {
    'schema', 'program', 'units', 'ag_provenance', 'final_geometry', 'final_input_geometry',
    'final_input_geometry_orientation', 'charge', 'energies', 'error_hint',
    'expected_vibrational_modes', 'final_geometry_orientation', 'freq_step_converged',
    'freq_step_convergence', 'frequencies_low', 'frequency_note', 'imag_modes',
    'monatomic', 'multiplicity', 'n_atoms', 'n_imag', 'n_vibrational_modes',
    'opt_converged', 'parser_warning', 'program_version', 'program_version_warning',
    'program_versions', 'route', 's2', 'termination', 'vibrational_modes_complete',
}


@pytest.mark.parametrize('route', ['Opt', 'Freq', 'Opt Freq', 'SP'])
@pytest.mark.parametrize('body', ['', ' Title: stable=opt\n',
    ' The wavefunctionish is stable.\n',
    ' Title: The wavefunction is stable under the perturbations considered.\n'])
def test_ordinary_facts_keys_match_main(tmp_path, route, body):
    from ag.facts import build_facts
    from test_facts import attempt as synthetic_attempt

    directory = synthetic_attempt(tmp_path, fixture=None)
    (directory / 'outputs' / 'input.log').write_text(
        HEADER.replace('Stable', route) + body + NORMAL)
    facts = build_facts(directory)
    assert set(facts) == MAIN_GAUSSIAN_FACT_KEYS
    assert set(json.loads((directory / 'facts.json').read_text())) == MAIN_GAUSSIAN_FACT_KEYS


@pytest.mark.parametrize('route', ['stable', 'stable=opt', 'sTaBlE=OpT', 'SP\n stable=opt'])
def test_stable_route_without_diagnostic_keeps_unknown_fields(tmp_path, route):
    path = tmp_path / 'synthetic.log'
    path.write_text(HEADER.replace('Stable', route) + NORMAL)
    facts = parse_gaussian(path)[0]
    assert facts['wavefunction_stability'] == 'unknown'
    assert facts['wavefunction_stability_line'] is None


@pytest.mark.parametrize('header', ['', HEADER.replace('Stable', 'SP')])
@pytest.mark.parametrize('line,expected', [(STABLE, 'stable'), (INTERNAL, 'internal_instability'),
    (RHF_UHF, 'rhf_to_uhf'), (' The wavefunction has an unrecognized instability.', 'unknown')])
def test_diagnostic_without_stable_route_keeps_fields(tmp_path, header, line, expected):
    path = tmp_path / 'synthetic.log'
    path.write_text(header + line + NORMAL)
    facts = parse_gaussian(path)[0]
    assert facts['wavefunction_stability'] == expected
    assert facts['wavefunction_stability_line'] == line
