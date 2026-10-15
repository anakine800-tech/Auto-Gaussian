"""T42: only existing sanitized water/butane fixtures and their derivatives.

Baseline records are pre-T42 parse_gaussian values and geometries. No private
logs, remote calls, scientific acceptance, or imported legacy parser code.
"""
import json
from pathlib import Path
import re

import pytest

from ag._parse_outputs import gaussian_job_sections, parse_gaussian, gaussian_orientation
from ag.facts import build_facts, parse_facts
from test_facts import attempt

FIXTURES = Path(__file__).parent / 'fixtures'
WATER = (FIXTURES / 'water_opt_freq.log').read_text()
OPT, REST = WATER.split(' (Enter PATH/l1.exe)\n Link1:', 1)
FREQ = ' (Enter PATH/l1.exe)\n Link1:' + REST
OPT_ONLY = OPT.replace(' Opt Freq', ' Opt')
INPUT_STARTS = list(re.finditer(r'(?m)^.*Input orientation:.*\n', OPT))
SP = OPT[:INPUT_STARTS[1].start()].replace(' Opt Freq', ' SP')
SP += next(row + '\n' for row in OPT.splitlines() if 'Normal termination of Gaussian' in row)
BASELINE = json.loads((FIXTURES / 'gaussian_section_baseline.json').read_text())
NEW_KEYS = {'job_sections', 'fact_sources', 'frequency_unavailable_reason'}
FREQUENCY_KEYS = ('n_imag', 'frequencies_low', 'imag_modes', 'freq_step_converged',
                  'freq_step_convergence', 'n_vibrational_modes', 'expected_vibrational_modes',
                  'vibrational_modes_complete', 'frequency_note')


def parse(tmp_path, text):
    log = tmp_path / 'water.log'
    log.write_text(text)
    return parse_gaussian(log)


def assert_no_frequencies(facts):
    assert all(facts[key] is None for key in FREQUENCY_KEYS)
    assert all(facts['energies'][key] is None for key in ('zpe', 'e_thermal', 'h', 'g'))
    assert facts['frequency_unavailable_reason']


@pytest.mark.parametrize('name', sorted(BASELINE))
def test_existing_values_and_geometry_unchanged(tmp_path, name):
    text = (OPT_ONLY if name == 'water_opt_only.log' else SP
            if name == 'water_sp.log' else (FIXTURES / name).read_text())
    facts, geometry = parse(tmp_path, text)
    before, before_geometry = BASELINE[name]
    assert {key: value for key, value in facts.items() if key not in NEW_KEYS} == before
    assert geometry == before_geometry
    if name == 'water_sp.log':
        assert facts['opt_converged'] is None and facts['n_imag'] is None
        assert facts['energies']['scf'] == pytest.approx(-75.3124658999)


def test_opt_freq_sections_and_absolute_sources(tmp_path):
    facts, _ = parse(tmp_path, WATER)
    sections = facts['job_sections']
    assert [(s['index'], s['start_line'], s['end_line'], s['termination']) for s in sections] == [
        (1, 1, 1378, 'normal'), (2, 1379, 1971, 'normal')]
    assert sections[0]['route'] == '#p B3LYP/STO-3G Opt Freq SCF=Tight Integral=UltraFine'
    assert sections[1]['route'].endswith(' Freq')
    sources = facts['fact_sources']
    assert sources['opt_converged'] == sources['final_geometry'] == 1
    assert sources['energies.scf'] == 2
    assert all(sources[key] == 2 for key in FREQUENCY_KEYS)
    assert facts['freq_step_convergence']['frequency_line'] == 1715
    for row in facts['freq_step_convergence']['criteria'].values():
        assert WATER.splitlines()[row['line'] - 1].strip().endswith('YES')
    assert facts['parser_warning'] is None


@pytest.mark.parametrize('cut', ['before_route', 'before_modes', 'after_modes', 'before_terminal'])
def test_frequency_truncated_never_uses_partial_results(tmp_path, cut):
    freq = {'before_route': FREQ.split(' #P')[0],
            'before_modes': FREQ.split(' Harmonic frequencies')[0],
            'after_modes': FREQ.split(' - Thermochemistry -')[0],
            'before_terminal': FREQ.split(' Normal termination')[0]}[cut]
    facts, geometry = parse(tmp_path, OPT + freq)
    assert facts['termination'] == 'incomplete'
    assert facts['opt_converged'] is True
    assert facts['fact_sources']['opt_converged'] == facts['fact_sources']['final_geometry'] == 1
    assert facts['fact_sources']['energies.scf'] == 1
    assert geometry == BASELINE['water_opt_only.log'][1]
    assert_no_frequencies(facts)


def test_frequency_error_owns_hint_and_energy(tmp_path):
    # An earlier SCF diagnostic and the scheduler hint must not hide the error link.
    text = OPT.replace(' Optimization completed.', ' SCF not converged earlier\n Optimization completed.')
    text += FREQ.split(' Normal termination')[0]
    text += ' Error termination via Lnk1e in PATH/l502.exe\n'
    log = tmp_path / 'water.log'
    log.write_text(text)
    pbs = tmp_path / 'job.pbs.out'
    pbs.write_text('job killed: walltime exceeded limit\n')
    facts, _ = parse_gaussian(log, pbs)
    assert facts['termination'] == 'error'
    assert facts['error_hint'] == 'L502: SCF 不收敛'
    assert facts['fact_sources']['error_hint'] == 2
    assert facts['opt_converged'] is True
    assert facts['fact_sources']['energies.scf'] == 1
    assert_no_frequencies(facts)


@pytest.mark.parametrize('tail', [
    ' Entering Gaussian System\n Initial command:\n',
    ' Initial command:\n',
    ' (Enter PATH/l1.exe)\n',
    ' --Link1--\n',
    ' unrecognized nonblank tail\n',
    ' Normal termination of Gaussian\n',
])
def test_extra_or_unrecognized_tail_is_not_ignored(tmp_path, tail):
    facts, _ = parse(tmp_path, WATER + tail)
    assert len(facts['job_sections']) == 3
    assert facts['termination'] == 'incomplete'
    assert facts['parser_warning']
    assert_no_frequencies(facts)


def test_extra_frequency_job_does_not_reuse_completed_frequency(tmp_path):
    # New launch plus the already sanitized frequency body, truncated at end.
    tail = ' Entering Gaussian System\n Initial command:\n' + FREQ.split(' Link1:')[1].split('\n', 1)[1]
    facts, _ = parse(tmp_path, WATER + tail.split(' Normal termination')[0])
    assert len(facts['job_sections']) == 3
    assert facts['termination'] == 'incomplete' and facts['parser_warning']
    assert facts['fact_sources']['n_imag'] == 3
    assert_no_frequencies(facts)


@pytest.mark.parametrize('step', [1, 3, 4])
def test_invalid_internal_sequence_warns_even_if_normal(tmp_path, step):
    text = WATER.replace('internal job step number  2.', f'internal job step number  {step}.')
    facts, _ = parse(tmp_path, text)
    assert all(s['termination'] == 'normal' for s in facts['job_sections'])
    assert facts['termination'] == 'incomplete' and facts['parser_warning']


def test_error_precedes_unrecognized_tail_and_prior_normal(tmp_path):
    text = OPT + FREQ.split(' Normal termination')[0] + ' Error termination via Lnk1e in PATH/l502.exe\n'
    facts, _ = parse(tmp_path, text + ' Entering Gaussian System\n')
    assert facts['termination'] == 'error'
    assert facts['error_hint'] == 'L502: SCF 不收敛'
    assert facts['fact_sources']['error_hint'] == 2


@pytest.mark.parametrize('ending', ['\n', '\r\n'])
@pytest.mark.parametrize('prefix', [' Link1:  ', ' '])
def test_internal_steps_and_trailing_blank_lines(tmp_path, ending, prefix):
    text = WATER.replace(' Link1:  Proceeding', prefix + 'Proceeding').replace('\n', ending)
    sections, warnings = gaussian_job_sections(text + ending + ' \t' + ending)
    assert len(sections) == 2 and warnings == []
    assert sections[-1]['end_line'] == 1971
    assert sections[-1]['termination'] == 'normal'
    # Ordinary Enter l1/l101 etc. lines inside the body never start jobs.
    assert sections[0]['end_line'] == 1378


def test_initial_command_is_not_an_extra_section():
    sections, warnings = gaussian_job_sections(WATER)
    assert len(sections) == 2 and warnings == []
    text = WATER.replace(' Entering Gaussian System, Link 0=g16\n', '')
    sections, warnings = gaussian_job_sections(text)
    assert len(sections) == 2 and warnings == []


def test_last_normal_section_does_not_fall_back_when_energy_missing(tmp_path):
    text = WATER.replace(FREQ, '\n'.join(row for row in FREQ.splitlines() if 'SCF Done:' not in row) + '\n')
    facts, _ = parse(tmp_path, text)
    assert facts['termination'] == 'normal'
    assert facts['energies']['scf'] is None
    assert facts['fact_sources']['energies.scf'] == 2


def test_cclib_only_receives_one_section(tmp_path, monkeypatch):
    import cclib.io
    original = cclib.io.ccread
    calls = []

    def read(source, **kwargs):
        block = source.getvalue()
        calls.append(block)
        assert block.count('Normal termination of Gaussian') == 1
        assert block.count(' #') == 1
        return original(source, **kwargs)

    monkeypatch.setattr(cclib.io, 'ccread', read)
    facts, _ = parse(tmp_path, WATER)
    assert facts['termination'] == 'normal' and len(calls) == 2
    assert 'Harmonic frequencies' not in calls[0]
    assert 'Entering Gaussian System' not in calls[1]


def test_final_input_geometry_uses_same_opt_section(tmp_path):
    directory = attempt(tmp_path)
    # Distinct trailing frequency geometry must not replace the optimization geometry.
    text = OPT + FREQ.replace('0.770245', '0.870245')
    (directory / 'outputs/input.log').write_text(text)
    facts, geometries = parse_facts(directory)
    assert facts['fact_sources']['final_input_geometry'] == facts['fact_sources']['final_geometry'] == 1
    assert geometries['final_input.xyz'] == gaussian_orientation(OPT, 'Input')
    assert geometries['final.xyz'] == BASELINE['water_opt_only.log'][1]
    assert not (directory / 'facts.json').exists()


def test_existing_facts_are_only_compared_not_refreshed(tmp_path):
    directory = attempt(tmp_path)
    facts = build_facts(directory)
    for key in NEW_KEYS:
        facts.pop(key)
    target = directory / 'facts.json'
    target.write_text(json.dumps(facts) + '\n')
    before = target.read_bytes(), target.stat().st_mtime_ns
    with pytest.raises(ValueError, match='--refresh'):
        build_facts(directory)
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert not list(directory.glob('facts.*.json'))


def test_unrecognized_truncated_geometry_has_no_final_source(tmp_path):
    facts, geometry = parse(tmp_path, WATER + ' Input orientation:\n --------\n truncated\n')
    assert facts['termination'] == 'incomplete'
    assert facts['opt_converged'] is True and facts['fact_sources']['opt_converged'] == 1
    assert geometry is None and facts['fact_sources']['final_geometry'] is None


def test_quoted_normal_marker_is_not_a_terminal(tmp_path):
    facts, _ = parse(tmp_path, WATER.replace(' Normal termination of Gaussian',
                                            ' Title: Normal termination of Gaussian'))
    assert facts['termination'] == 'incomplete'
    assert_no_frequencies(facts)


def test_scf_energy_is_from_last_normal_section(tmp_path):
    text = OPT + FREQ.replace('-75.3227750502', '-74.3227750502')
    facts, _ = parse(tmp_path, text)
    assert facts['energies']['scf'] == pytest.approx(-74.3227750502)
    assert facts['fact_sources']['energies.scf'] == 2
    facts, _ = parse(tmp_path, text.split(' Normal termination')[0])
    assert facts['energies']['scf'] is None
    assert facts['fact_sources']['energies.scf'] is None
