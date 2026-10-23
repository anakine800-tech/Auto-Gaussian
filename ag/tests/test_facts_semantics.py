"""T108: public small-molecule fixtures and synthetic format regressions only.

Default thresholds/stationary markers: reviewed water/butane fixtures.
Negligible-force completion: existing T42b format, artificial numbers below.
Stability matrix layout: UCSB's H2 tutorial (task2B.html, section 4);
all matrix/spin numbers below are synthetic, not research output.
"""
from hashlib import sha256
import json

import pytest

from ag import cli, facts as facts_module
from ag._parse_outputs import frequency_convergence, wavefunction_stability
from ag._profile_sources import section_source
from ag.review import fact_row
from ag.thermo import _frequency_evidence, calculate_thermo, write_analysis
from test_facts import attempt
from test_facts_reparse import snapshot
from test_route_wrap import FREQUENCIES, TABLE, parse, section


STATIONARY = ' Optimization completed.\n    -- Stationary point found.\n'
NEGLIGIBLE = ' Optimization completed on the basis of negligible forces.\n    -- Stationary point found.\n'
TIGHT = (TABLE.replace('0.000450', '0.000015').replace('0.000300', '0.000010')
         .replace('0.001800', '0.000060').replace('0.001200', '0.000040')
         .replace('0.000100', '0.000030').replace('0.000050', '0.000020'))
FAILED = TIGHT.replace('0.000030     0.000060     YES', '0.000090     0.000060     NO')
MATRIX = (' Stability analysis using  singles matrix:\n'
          ' Eigenvectors of the stability matrix:\n'
          ' Eigenvector   1:   Triplet-SGU  Eigenvalue=-0.0200000  <S**2>=2.000\n'
          '       1 ->  2         0.70711\n'
          ' Eigenvector   2:   Singlet-SGU  Eigenvalue= 0.0300000\n')
ALREADY = ' The wavefunction is already stable.\n'
SPIN = (' SCF Done: E(UHF) = -39.0 A.U. after 10 cycles\n'
        ' S**2 before annihilation     2.0240, after     2.0008\n')
NEW_FREQ = ('freq_step_gaussian_stationary', 'freq_step_review',
            'freq_step_converged_tight', 'freq_step_threshold_set')


def line_of(text, fragment):
    return next(i for i, line in enumerate(text.splitlines(), 1) if fragment in line)


def test_tight_opt_freq_and_global_stationary_evidence(tmp_path):
    text = section(' #p HF/STO-3G Opt=Tight Freq', body=TIGHT + STATIONARY)
    text += section(' #p HF/STO-3G Freq', step=2, body=FREQUENCIES + TIGHT + STATIONARY)
    result = parse(tmp_path, text)
    assert result['freq_step_converged'] is True
    assert result['freq_step_converged_tight'] is True
    assert result['freq_step_threshold_set'] == 'tight'
    assert result['freq_step_review'] == 'pass'
    stationary = result['freq_step_gaussian_stationary']
    assert stationary['found'] is True and stationary['basis'] == 'all_criteria'
    assert len(stationary['lines']) == 2
    assert all(i >= result['job_sections'][1]['start_line'] for i in stationary['lines'])
    assert [text.splitlines()[i - 1] for i in stationary['lines']] == STATIONARY.splitlines()
    assert all(result['fact_sources'][key] == 2 for key in NEW_FREQ)


def test_negligible_forces_require_manual_review_and_still_reject_thermo(tmp_path):
    text = section(' #p HF/STO-3G Freq', body=FREQUENCIES + FAILED + NEGLIGIBLE)
    result = parse(tmp_path, text)
    assert result['freq_step_converged'] is False
    assert result['freq_step_gaussian_stationary']['basis'] == 'negligible_forces'
    assert result['freq_step_review'] == 'manual_review'
    with pytest.raises(ValueError, match='四项未全部通过，但 Gaussian 判定驻点（力可忽略）：需人工判定') as error:
        _frequency_evidence(result, 'water')
    assert 'maximum_displacement' in str(error.value) and '"line":' in str(error.value)
    row = fact_row('freq_step_converged', True, result)
    assert '需人工判定' in row[1] and row[2] == '无法判断'


def test_default_pass_tight_failure_warns_without_changing_thermo(tmp_path):
    directory = attempt(tmp_path, fixture='butane_anti_freq.log')
    original = (directory / 'outputs/input.log').read_bytes()
    result = calculate_thermo([directory])
    warning = 'Freq 步按默认阈值通过、按 Tight 阈值未通过；若父优化为 Opt=Tight，需人工判定是否接受'
    assert any(warning in item for item in result['warnings'])
    parsed, _ = facts_module.parse_facts(directory)
    assert parsed['freq_step_threshold_set'] == 'default'
    assert parsed['freq_step_converged'] is True and parsed['freq_step_converged_tight'] is False
    assert parsed['freq_step_review'] == 'pass'
    assert warning in fact_row('freq_step_converged', True, parsed)[1]
    _, markdown = write_analysis(result, tmp_path)
    assert warning in markdown.read_text()
    assert (directory / 'outputs/input.log').read_bytes() == original
    assert not (directory / 'facts.json').exists()


@pytest.mark.parametrize('table,thresholds,tight,review', [
    (TABLE, 'default', False, 'pass'),
    (TIGHT, 'tight', True, 'pass'),
    (TIGHT.replace('0.000015', '0.000016'), 'other', True, 'pass'),
    (TIGHT.replace('0.000030', '0.000060'), 'tight', False, 'pass'),
    (TIGHT + ' ! Non-Optimized Parameters !\n', 'tight', False, 'fail'),
    (TIGHT.rsplit(' RMS', 1)[0], None, None, None),
    ('', None, None, None),
])
def test_threshold_sets_and_incomplete_evidence(table, thresholds, tight, review):
    result = frequency_convergence(FREQUENCIES + table)
    assert result['freq_step_threshold_set'] == thresholds
    assert result['freq_step_converged_tight'] is tight
    assert result['freq_step_review'] == review
    assert result['freq_step_gaussian_stationary']['found'] is False


@pytest.mark.parametrize('body', [FREQUENCIES + FAILED,
    FREQUENCIES + TIGHT, FREQUENCIES + TIGHT + ' Title: -- Stationary point found.\n'])
def test_opt_stationary_not_borrowed_by_frequency(tmp_path, body):
    text = section(' #p HF/STO-3G Opt Freq', body=TIGHT + NEGLIGIBLE)
    text += section(' #p HF/STO-3G Freq', step=2, body=body)
    result = parse(tmp_path, text)
    assert result['freq_step_gaussian_stationary'] == {'found': False, 'basis': None, 'lines': []}


@pytest.mark.parametrize('tail', [
    section(' #p HF/STO-3G Freq', step=2, body=FREQUENCIES, ending=''),
    ' --Link1--\n #p HF/STO-3G Fre', ' unknown truncated tail\n',
])
def test_truncated_tail_cannot_inherit_frequency_facts(tmp_path, tail):
    result = parse(tmp_path, section(' #p HF/STO-3G Freq', body=FREQUENCIES + TIGHT + STATIONARY) + tail)
    assert result['termination'] == 'incomplete'
    assert all(result[key] is None for key in NEW_FREQ)


def test_last_table_resets_stationary_and_no_freq_is_null():
    result = frequency_convergence(FREQUENCIES + TIGHT + STATIONARY + FAILED)
    assert result['freq_step_gaussian_stationary']['found'] is False
    assert result['freq_step_review'] == 'fail'
    assert frequency_convergence(TIGHT + STATIONARY)['freq_step_gaussian_stationary']['found'] is None


def test_new_fields_follow_frequency_source_past_sp(tmp_path):
    text = section(' #p HF/STO-3G Freq', body=FREQUENCIES + TIGHT + STATIONARY)
    text += section(' #p HF/STO-3G SP', step=2)
    result = parse(tmp_path, text)
    assert result['freq_step_gaussian_stationary']['found'] is True
    assert all(result['fact_sources'][key] == 1 for key in NEW_FREQ)
    # Same section checks include new keys when present; legacy facts remain supported.
    result['fact_sources']['freq_step_review'] = 2
    result['multiplicity'] = 1  # Explicit synthetic state for protocol validation.
    with pytest.raises(ValueError, match='inconsistent section sources'):
        section_source(result, 'water')


def test_already_stable_and_lowest_eigenvalue_have_global_lines(tmp_path):
    text = section(' #p HF/STO-3G SP')
    text += section(' #p HF/STO-3G Stable=Opt', step=2, body=MATRIX + ALREADY)
    result = parse(tmp_path, text)
    assert result['wavefunction_stability'] == 'stable'
    assert result['wavefunction_stability_line'] == ALREADY.rstrip('\n')
    assert result['wavefunction_stability_line_number'] == line_of(text, 'already stable')
    assert result['wavefunction_stability_lowest_eigenvalue'] == {
        'value': -0.02, 'line': line_of(text, 'Eigenvector   1:')}
    assert result['fact_sources']['wavefunction_stability_lowest_eigenvalue'] == 2
    assert 'lowest_eigenvalue' in fact_row('multiplicity', 1, result)[1]


@pytest.mark.parametrize('body', [
    ' Eigenvalues -- -0.25 0.01\n' + ALREADY,
    MATRIX.replace('Eigenvalue=-0.0200000', 'Eigenvalue=********') + ALREADY,
    MATRIX.replace('Eigenvalue=-0.0200000', 'Eigenvalue=-0.0200000 unexpected') + ALREADY,
    MATRIX + ALREADY + ' Eigenvectors of the stability matrix:\n',
    MATRIX + ALREADY + ' --Link1--\n' + ALREADY,
    MATRIX + ALREADY + ' #p HF/STO-3G Stable\n' + ALREADY,
    MATRIX + ALREADY + ' SCF Done: E(RHF) = -75.0 A.U.\n' + ALREADY,
    MATRIX + ' The wavefunction has an unsupported diagnostic.\n',
])
def test_unsupported_or_new_stability_evidence_does_not_borrow(body):
    assert wavefunction_stability(body)['wavefunction_stability_lowest_eigenvalue'] is None


def test_last_stability_analysis_wins_not_most_negative_in_file():
    body = MATRIX + ' The wavefunction has an internal instability.\n'
    body += MATRIX.replace('-0.0200000', '0.0100000') + ALREADY
    result = wavefunction_stability(body)
    assert result['wavefunction_stability_lowest_eigenvalue']['value'] == 0.01


def test_s2_from_last_scf_not_eigenvector_labels(tmp_path):
    first = section(' #p UHF/STO-3G SP', body=SPIN.replace('2.0240', '2.0900'))
    second = section(' #p UHF/STO-3G Stable=Opt', step=2,
                     body=SPIN + ' Leave Link  502\n' + MATRIX + ALREADY)
    text = first + second
    result = parse(tmp_path, text)
    assert result['s2'] == 2.024 and result['s2_after_annihilation'] == 2.0008
    assert result['s2_line'] == line_of(text, '2.0240')
    assert result['fact_sources']['s2_line'] == 2


@pytest.mark.parametrize('body', [
    ' <S**2>=2.000\n',
    ' S**2 before annihilation 2.0240, after 2.0008\n',
    SPIN + ' SCF Done: E(RHF) = -39.1 A.U.\n',
    SPIN.splitlines()[0] + '\n' + MATRIX + ' S**2 before annihilation 2.1, after 2.0\n',
    SPIN.splitlines()[0] + '\n Excited State 1: Triplet <S**2>=2.000\n'
    ' S**2 before annihilation 2.1, after 2.0\n',
])
def test_spin_without_final_scf_annihilation_is_null(tmp_path, body):
    result = parse(tmp_path, section(' #p HF/STO-3G SP', body=body))
    assert result['s2'] is result['s2_after_annihilation'] is result['s2_line'] is None


def test_old_facts_preserved_and_explicit_dry_run_shows_semantic_diff(tmp_path, capsys):
    directory = attempt(tmp_path / 'study', fixture=None)
    (directory / 'status.json').write_text('{"state":"fetched"}')
    (directory / 'outputs/input.log').write_text(section(' #p UHF/STO-3G Freq',
        body=SPIN + FREQUENCIES + TIGHT + STATIONARY + MATRIX + ALREADY))
    old, _ = facts_module.parse_facts(directory)
    for key in (*NEW_FREQ, 's2_after_annihilation', 's2_line',
                'wavefunction_stability_line_number', 'wavefunction_stability_lowest_eigenvalue'):
        old.pop(key)
        old['fact_sources'].pop(key)
    for row in old['freq_step_convergence']['criteria'].values():
        row.pop('converged_tight')
    old['s2'] = 2.0
    old['wavefunction_stability'] = 'unknown'
    old['parser']['rules'] = 'route-join-v1'
    (directory / 'facts.json').write_text(json.dumps(old))
    study = directory.parent.parent
    (study / 'study.md').write_text('Signed: ' + sha256((directory / 'facts.json').read_bytes()).hexdigest())
    before = snapshot(study)
    facts_module.parse_facts(directory)
    assert snapshot(study) == before
    preview = tmp_path / 'preview.json'
    assert cli.main(['facts', str(directory), '--reparse', '--dry-run', '--out', str(preview)]) == 0
    report = json.loads(capsys.readouterr().out)
    changes = {row['path'] for row in report['differences']}
    assert {'/s2', '/s2_after_annihilation', '/s2_line', '/freq_step_gaussian_stationary',
            '/freq_step_review', '/freq_step_threshold_set', '/parser/rules'} <= changes
    assert report['references_to_old_sha256'] == ['study.md']
    assert snapshot(study) == before
