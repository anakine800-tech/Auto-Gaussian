"""Synthetic section binding; invented water numbers, no research data."""
import json
from pathlib import Path

import pytest
from goodvibes.thermo import ThermoOptions, calc_bbe

from ag._parse_outputs import parse_gaussian
from ag._profile_sources import DEFAULT_SETTINGS, load_species, section_source
from ag.facts import build_facts
from ag.thermo import calculate_thermo
from test_facts import attempt
from test_route_wrap import section, TABLE, FREQUENCIES

GEOMETRY = ''' Charge = 0 Multiplicity = 1
 Input orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.800000    0.600000
      3          1           0        0.000000   -0.800000    0.600000
 ---------------------------------------------------------------------
'''
THERMAL = ''' Molecular mass:    18.01056 amu.
 Rotational symmetry number  2.0000
 Rotational temperatures (Kelvin)     20.00000    10.00000     5.00000
 Zero-point correction=                           0.010000 (Hartree/Particle)
 Sum of electronic and thermal Energies=          -74.980000
 Sum of electronic and thermal Enthalpies=        -74.970000
 Sum of electronic and thermal Free Energies=     -75.020000
'''
ROUTE = 'HF/STO-3G EmpiricalDispersion=GD3BJ SCRF=(SMD,Solvent=Water)'


def synthetic(tmp_path, *, opt=ROUTE, freq=ROUTE, tail=False, standalone=False,
              opt_print='', freq_print=''):
    directory = attempt(tmp_path, fixture=None)
    body = (' Gaussian 16, Revision A.03,\n' + GEOMETRY + freq_print
            + ' SCF Done:  E(RHF) =  -75.000000000 A.U. after 1 cycles\n'
            + FREQUENCIES + TABLE + THERMAL)
    text = '' if standalone else section(' #p ' + opt + ' Opt',
        body=GEOMETRY + opt_print + ' SCF Done:  E(RHF) =  -77.000000 A.U. after 1 cycles\n'
        + ' Step number 1\n' + TABLE + ' Optimization completed.\n')
    text += section(' #p ' + freq + ' Fr\n eq Integral=UltraFine',
                    body=body, explicit=not standalone)
    if tail:
        text += section(' #p HF/6-31G SP', explicit=True, body=GEOMETRY
                        + ' SCF Done:  E(RHF) =  -99.000000 A.U. after 1 cycles\n'
                        + ' Rotational symmetry number  9.0000\n')
    (directory / 'outputs/input.log').write_text(text)
    return directory


@pytest.mark.parametrize('tail', [False, True])
def test_matching_sections_bind_thermo_and_profile_to_actual_freq(tmp_path, tail):
    directory = synthetic(tmp_path, tail=tail)
    before = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    row = calculate_thermo([directory])['rows'][0]
    assert row['frequency_source']['section_index'] == 2
    assert row['electronic_energy_source'] == row['frequency_source']
    assert row['E'] == row['frequency_E'] == -75
    assert row['rotational_symmetry_number'] == 2
    assert row['frequency_source']['start_line'] <= row['rotational_symmetry_source']['line'] <= row['frequency_source']['end_line']
    assert row['comparability']['frequency_protocol'] == section_source(
        parse_gaussian(directory / 'outputs/input.log')[0], 'water')['protocol']
    assert row['integration_grid']['frequency'] == 'ultrafine'
    profile = load_species('water', {'attempts': [{'attempt_id': 'water'}],
        'single_conformer_reason': 'synthetic water'}, tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)
    assert profile['conformers'][0]['frequency_source'] == row['frequency_source']
    assert profile['ensemble_G_hartree'] == row['qh_G']
    assert before == {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}


@pytest.mark.parametrize('freq,fields', [
    (ROUTE.replace('HF/', 'B3LYP/'), ['method']),
    (ROUTE.replace('STO-3G', '6-31G'), ['basis']),
    (ROUTE.replace('GD3BJ', 'GD3'), ['dispersion']),
    (ROUTE.replace('SMD', 'PCM'), ['solvent_model']),
    (ROUTE.replace('Water', 'Toluene'), ['solvent']),
    (ROUTE + ' 6D', ['basis_function_type']),
    ('B3LYP/6-31G', ['method', 'basis', 'dispersion', 'solvent_model', 'solvent']),
    (ROUTE.replace('HF/', 'RHF/'), ['method']),
])
@pytest.mark.parametrize('consumer', ['thermo', 'profile'])
def test_opt_freq_differences_are_listed_and_rejected(tmp_path, freq, fields, consumer):
    directory = synthetic(tmp_path, freq=freq)
    with pytest.raises(ValueError, match='inconsistent Opt/Freq') as error:
        if consumer == 'thermo':
            calculate_thermo([directory])
        else:
            load_species('water', {'attempts': [{'attempt_id': 'water'}],
                'single_conformer_reason': 'synthetic'}, tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)
    for field in fields:
        assert f'{field}: Opt section 1=' in str(error.value)
    assert 'Freq section 2=' in str(error.value)


def test_single_freq_preserves_goodvibes_numbers_and_settings(tmp_path):
    directory = synthetic(tmp_path, standalone=True)
    row = calculate_thermo([directory], temp=310, conc=0.2, qs='truhlar',
                           s_cutoff=80, h_cutoff=90)['rows'][0]
    oracle = calc_bbe.from_options(str(directory / 'outputs/input.log'), ThermoOptions(
        temperature=310, concentration=0.2, QS='truhlar', QH=True,
        s_freq_cutoff=80, h_freq_cutoff=90, freq_scale_factor=1.0, zpe_scale_factor=1.0))
    for field, attr in {'E': 'scf_energy', 'ZPE': 'zpe', 'H': 'enthalpy', 'S': 'entropy',
                        'G': 'gibbs_free_energy', 'qh_H': 'qh_enthalpy', 'qh_S': 'qh_entropy',
                        'qh_G': 'qh_gibbs_free_energy'}.items():
        assert row[field] == getattr(oracle, attr)
    assert row['frequency_source']['section_index'] == 1


def test_checkpoint_only_solvent_never_borrows_opt_protocol(tmp_path):
    directory = synthetic(tmp_path, freq='HF/STO-3G SCRF=Check')
    with pytest.raises(ValueError, match='SCRF=Check requires a complete printed solvent'):
        calculate_thermo([directory])


def test_monatomic_freq_does_not_take_trailing_sp_energy(tmp_path):
    directory = attempt(tmp_path, fixture='fluoride_freq_converged_synthetic.log')
    log = directory / 'outputs/input.log'
    baseline = calculate_thermo([directory])['rows'][0]
    original = log.read_text()
    tail = original.split(' Harmonic frequencies')[0].replace(' Freq', ' SP')
    log.write_text(original + ' --Link1--\n' + tail.replace('-99.0000000000', '-101.0000000000')
                   + ' Rotational symmetry number  9.0000\n Normal termination of Gaussian\n')
    row = calculate_thermo([directory])['rows'][0]
    for field in ('E', 'frequency_E', 'ZPE', 'H', 'S', 'G', 'qh_H', 'qh_S', 'qh_G'):
        assert row[field] == baseline[field]
    assert row['electronic_energy_source']['section_index'] == 1


@pytest.mark.parametrize('field', ['freq_step_converged', 'energies.zpe'])
def test_mixed_field_sources_are_rejected(tmp_path, field):
    directory = synthetic(tmp_path)
    facts = parse_gaussian(directory / 'outputs/input.log')[0]
    facts['fact_sources'][field] = 1
    with pytest.raises(ValueError, match='inconsistent section sources'):
        section_source(facts, 'water')


def test_explicit_spc_reports_its_actual_energy_section(tmp_path):
    from test_thermo import sp_input
    frequency = synthetic(tmp_path, standalone=True)
    sp = attempt(tmp_path, 'sp', fixture=None)
    log = sp / 'outputs/input.log'
    log.write_text(section(' # HF/STO-3G SP', body=GEOMETRY
                          + ' SCF Done:  E(RHF) =  -74.0 A.U. after 1 cycles\n')
                   + section(' # HF/6-31G SP', explicit=True, body=GEOMETRY
                             + ' Gaussian 16, Revision A.03,\n'
                             + ' SCF Done:  E(RHF) =  -76.0 A.U. after 1 cycles\n'))
    sp_input(sp, frequency)
    row = calculate_thermo([frequency], spc={str(frequency): str(sp)})['rows'][0]
    assert row['frequency_source']['section_index'] == 1
    assert row['electronic_energy_source']['attempt_id'] == 'sp'
    assert row['electronic_energy_source']['section_index'] == 2
    assert row['comparability']['single_point_protocol']['basis'] == '6-31g'
    assert row['E'] == pytest.approx(-76) and row['spc_correction'] == pytest.approx(-1)


def test_cached_multisection_thermo_requires_matching_sources(tmp_path):
    directory = synthetic(tmp_path)
    build_facts(directory)
    table = calculate_thermo([directory])
    analyses = tmp_path / 'analyses'
    analyses.mkdir()
    path = analyses / 'thermo.json'
    spec = {'thermo': 'thermo.json', 'single_conformer_reason': 'synthetic'}
    path.write_text(json.dumps(table))
    assert load_species('water', spec, tmp_path, analyses, DEFAULT_SETTINGS)['ensemble_G_hartree'] == table['ensemble_G']
    del table['rows'][0]['frequency_source']
    path.write_text(json.dumps(table))
    with pytest.raises(ValueError, match='cached thermo section sources'):
        load_species('water', spec, tmp_path, analyses, DEFAULT_SETTINGS)


def explicit_water(directory):
    """Synthetic explicit Freq echo for existing numerical/identity tests.

    The original fixture's SCRF=Check lacks a printed solvent block. Change
    only the echo for these unrelated checks, preserving all numeric data.
    """
    path = directory / 'outputs/input.log'
    path.write_text(path.read_text().replace(
        '#P Geom=AllCheck Guess=TCheck SCRF=Check GenChk RB3LYP/STO-3G Freq',
        '#P B3LYP/STO-3G Freq'))
    return directory


def solvent_block(model='SMD', *, solvent='Water', epsilon='78.355300',
                  epsilon_infinite='1.777849'):
    radii = 'SMD-Coulomb' if model == 'SMD' else 'UFF (Universal Force Field)'
    return (f' Polarizable Continuum Model (PCM)\n'
            f' =================================\n'
            f' Model                : PCM.\n'
            f' Atomic radii         : {radii}.\n'
            f' Polarization charges : Total charges.\n'
            f' Charge compensation  : None.\n'
            f' Solution method      : On-the-fly selection.\n'
            f' Cavity type          : Scaled VdW (van der Waals Surface) (Alpha=1.100).\n'
            f' Cavity algorithm     : GePol (No added spheres)\n'
            f'                        Default sphere list used, NSphG=    3.\n'
            f'                        Lebedev-Laikov grids with approx.  5.0 points / Ang**2.\n'
            f'                        Smoothing algorithm: York/Karplus (Gamma=1.0000).\n'
            f'                        Polarization charges: spherical gaussians, with\n'
            f'                                              point-specific exponents (IZeta= 3).\n'
            f'                        Self-potential: point-specific (ISelfS= 7).\n'
            f'                        Self-field    : sphere-specific E.n sum rule (ISelfD= 2).\n'
            f' Solvent              : {solvent}, Eps= {epsilon} Eps(inf)= {epsilon_infinite}\n'
            f' ---------------------------------------------------------------------\n')


def inherited_solvent(tmp_path, model, *, opt_print=None, freq_print=None, freq_route=None):
    route = ROUTE.replace('SMD', model)
    return synthetic(tmp_path, opt=route,
        freq=freq_route or route.replace(f'SCRF=({model},Solvent=Water)', 'SCRF=Check'),
        opt_print=solvent_block(model) if opt_print is None else opt_print,
        freq_print=solvent_block(model) if freq_print is None else freq_print)


@pytest.mark.parametrize('model', ['SMD', 'PCM'])
@pytest.mark.parametrize('check', ['SCRF=Check', 'SCRF=(Check)', 'SCRF(Check)', ''])
def test_own_matching_printed_solvent_binds_freq_and_cached_profile(tmp_path, model, check):
    directory = inherited_solvent(tmp_path, model,
        freq_route='HF/STO-3G EmpiricalDispersion=GD3BJ ' + check)
    build_facts(directory)
    before = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    table = calculate_thermo([directory])
    source = table['rows'][0]['frequency_source']
    assert source['section_index'] == 2
    assert source['protocol']['solvent_model'] == model.lower()
    assert source['protocol']['solvent'] == 'water'
    assert source['protocol']['solvent_parameters']['epsilon'] == 78.3553
    assert source['protocol']['solvent_parameters']['epsilon_infinite'] == 1.777849
    assert source['printed_conditions']['solvent']['values'] == source['compared_opt_sections'][0]['printed_conditions']['solvent']['values']
    location = source['printed_conditions']['solvent']['blocks'][0]
    assert source['start_line'] < location['start_line'] < location['end_line'] < source['end_line']
    assert source['compared_opt_sections'][0]['printed_conditions']['solvent']['blocks'][0]['end_line'] < source['start_line']
    assert table['rows'][0]['electronic_energy_source'] == source
    analyses = tmp_path / 'analyses'
    analyses.mkdir()
    (analyses / 'thermo.json').write_text(json.dumps(table))
    result = load_species('water', {'thermo': 'thermo.json', 'single_conformer_reason': 'synthetic'},
                          tmp_path, analyses, DEFAULT_SETTINGS)
    assert result['conformers'][0]['frequency_source'] == source
    assert result['ensemble_G_hartree'] == table['ensemble_G']
    assert before == {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}


@pytest.mark.parametrize('model', ['SMD', 'PCM'])
@pytest.mark.parametrize('change', ['solvent', 'epsilon', 'epsilon_infinite', 'radii',
                                   'other_parameter', 'missing_freq', 'missing_opt',
                                   'malformed', 'missing_field', 'unterminated', 'conflicting_repeat'])
def test_inherited_solvent_requires_complete_identical_own_blocks(tmp_path, model, change):
    opt, freq = solvent_block(model), solvent_block(model)
    if change == 'solvent':
        freq = freq.replace('Water', 'Toluene')
    elif change == 'epsilon':
        freq = freq.replace('78.355300', '78.355301')
    elif change == 'epsilon_infinite':
        freq = freq.replace('1.777849', '1.777850')
    elif change == 'radii':
        freq = freq.replace('SMD-Coulomb' if model == 'SMD' else 'UFF', 'Bondi')
    elif change == 'other_parameter':
        freq = freq.replace('Total charges', 'Apparent charges')
    elif change == 'missing_freq':
        freq = ''
    elif change == 'missing_opt':
        opt = ''
    elif change == 'malformed':
        freq = freq.replace('78.355300', '*********')
    elif change == 'missing_field':
        freq = '\n'.join(line for line in freq.splitlines() if 'Atomic radii' not in line) + '\n'
    elif change == 'unterminated':
        freq = freq.rsplit(' -----', 1)[0]
    elif change == 'conflicting_repeat':
        freq += freq.replace('78.355300', '2.374100')
    directory = inherited_solvent(tmp_path, model, opt_print=opt, freq_print=freq)
    # cclib may reject malformed/truncated blocks before extracting modes.
    # Also exercise the scoped parser directly to verify its own rejection.
    if change in {'malformed', 'unterminated'}:
        from ag._profile_sources import _printed_solvent
        with pytest.raises(ValueError, match='printed|parameter'):
            _printed_solvent(freq, 0, 'synthetic')
    diagnostic = 'solvent|parameter|inconsistent Opt/Freq|n_imag'
    with pytest.raises(ValueError, match=diagnostic):
        calculate_thermo([directory])
    with pytest.raises(ValueError, match=diagnostic):
        load_species('water', {'attempts': [{'attempt_id': 'water'}], 'single_conformer_reason': 'synthetic'},
                     tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)


def test_repeated_identical_solvent_blocks_and_numeric_format_are_accepted(tmp_path):
    directory = inherited_solvent(tmp_path, 'SMD', opt_print=solvent_block() * 2,
        freq_print=solvent_block(epsilon='7.83553E+01'))
    source = calculate_thermo([directory])['rows'][0]['frequency_source']
    assert len(source['compared_opt_sections'][0]['printed_conditions']['solvent']['blocks']) == 2


@pytest.mark.parametrize('model', ['SMD', 'PCM'])
def test_solver_and_derivative_diagnostics_do_not_change_solvent_conditions(tmp_path, model):
    original = solvent_block(model)
    first = (' 1st derivatives      : Analytical E(r).r(x)/FMM algorithm (CHGder, D1EAlg=3).\n'
             '                        Cavity 1st derivative terms included.\n')
    second = (' 2nd derivatives      : Analytical E(r).r(xy)/FMM algorithm (CHGder, D2EAlg=3).\n'
              '                        Cavity 2nd derivative terms included.\n')
    opt = original.replace(' Solvent ', first + ' Solvent ')
    freq = original.replace(' Solvent ', first + second + ' Solvent ').replace(
        'On-the-fly selection.', 'Matrix inversion.')
    directory = inherited_solvent(tmp_path, model, opt_print=opt + freq, freq_print=freq)
    source = calculate_thermo([directory])['rows'][0]['frequency_source']
    printed = source['printed_conditions']['solvent']
    diagnostics = printed['blocks'][0]['evaluation_diagnostics']
    assert '2nd derivatives' in diagnostics
    assert diagnostics['solution method'] == 'matrix inversion.'
    assert '2nd derivatives' not in printed['values']['other_parameters']
    assert 'solution method' not in printed['values']['other_parameters']
    assert printed['values'] == source['compared_opt_sections'][0]['printed_conditions']['solvent']['values']


@pytest.mark.parametrize('setting,diagnostic,field,expected', [
    ('EmpiricalDispersion=GD2', ' R6Disp:  Grimme-D2 Dispersion energy= -0.001 Hartrees.\n', 'dispersion', 'gd2'),
    ('5D 7F', ' Standard basis: STO-3G (5D, 7F)\n', 'basis_function_type', '5D 7F'),
])
@pytest.mark.parametrize('missing', [False, True])
def test_other_omitted_conditions_require_same_section_print(tmp_path, setting, diagnostic, field, expected, missing):
    directory = synthetic(tmp_path, opt='HF/STO-3G ' + setting, freq='HF/STO-3G',
                          opt_print=diagnostic, freq_print='' if missing else diagnostic)
    if missing:
        with pytest.raises(ValueError, match='missing or conflicting same-section printed ' + field):
            calculate_thermo([directory])
    else:
        source = calculate_thermo([directory])['rows'][0]['frequency_source']
        assert source['protocol'][field] == expected
        assert source['printed_conditions'][field]['lines'][0] > source['start_line']


@pytest.mark.parametrize('route', ['Freq SCRF=Check', 'HF/ChkBasis SCRF=Check',
                                  'HF/STO-3G EmpiricalDispersion=Check SCRF=Check'])
def test_unsupported_checkpoint_conditions_are_not_guessed(tmp_path, route):
    directory = inherited_solvent(tmp_path, 'SMD', freq_route=route)
    with pytest.raises(ValueError, match='explicit method/basis|Custom basis|unsupported inherited dispersion'):
        calculate_thermo([directory])


def test_gas_phase_single_and_two_section_numeric_behavior_unchanged(tmp_path):
    rows = []
    for name, standalone in [('single', True), ('two', False)]:
        directory = synthetic(tmp_path / name, opt='HF/STO-3G', freq='HF/STO-3G', standalone=standalone)
        rows.append(calculate_thermo([directory])['rows'][0])
    for field in ('E', 'ZPE', 'H', 'S', 'G', 'qh_H', 'qh_S', 'qh_G'):
        assert rows[0][field] == rows[1][field]
    for row in rows:
        assert row['comparability']['frequency_protocol']['solvent_model'] == 'none'
        assert 'printed_conditions' not in row['frequency_source']


def test_multiple_opt_sections_cannot_hide_inherited_dispersion_difference(tmp_path):
    printed = ' R6Disp:  Grimme-D2 Dispersion energy= -0.001 Hartrees.\n'
    directory = synthetic(tmp_path, opt='HF/STO-3G', freq='HF/STO-3G',
                          opt_print=printed, freq_print=printed)
    log = directory / 'outputs/input.log'
    text = log.read_text()
    boundary = text.index(' --Link1--')
    log.write_text(text[:boundary] + section(' #p HF/STO-3G EmpiricalDispersion=GD3 Opt',
        explicit=True, body=GEOMETRY + printed.replace('Grimme-D2', 'Grimme-D3')) + text[boundary:])
    with pytest.raises(ValueError, match='dispersion: Opt section 2=.*gd3.*Freq section 3=.*gd2'):
        calculate_thermo([directory])


def test_printed_conditions_cannot_bind_to_stale_section_ranges(tmp_path):
    directory = inherited_solvent(tmp_path, 'SMD')
    facts = build_facts(directory)
    log = directory / 'outputs/input.log'
    log.write_text('\n' + log.read_text())
    with pytest.raises(ValueError, match='job sections differ from facts'):
        section_source(facts, 'water', directory=directory)


def test_checkpoint_solvent_does_not_hide_ambiguous_route(tmp_path):
    directory = inherited_solvent(tmp_path, 'SMD', freq_route=ROUTE + ' SCRF=Check')
    with pytest.raises(ValueError, match='Ambiguous solvent settings'):
        calculate_thermo([directory])


def test_matching_checkpoint_solvent_does_not_relax_freq_convergence(tmp_path):
    directory = inherited_solvent(tmp_path, 'SMD')
    log = directory / 'outputs/input.log'
    before, after = log.read_text().rsplit(TABLE, 1)
    log.write_text(before + TABLE.replace('YES', 'NO', 1) + after)
    with pytest.raises(ValueError, match='freq_step_converged'):
        calculate_thermo([directory])
