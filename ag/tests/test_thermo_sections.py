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


def synthetic(tmp_path, *, opt=ROUTE, freq=ROUTE, tail=False, standalone=False):
    directory = attempt(tmp_path, fixture=None)
    body = (' Gaussian 16, Revision A.03,\n' + GEOMETRY
            + ' SCF Done:  E(RHF) =  -75.000000000 A.U. after 1 cycles\n'
            + FREQUENCIES + TABLE + THERMAL)
    text = '' if standalone else section(' #p ' + opt + ' Opt',
        body=GEOMETRY + ' SCF Done:  E(RHF) =  -77.000000 A.U. after 1 cycles\n'
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
    with pytest.raises(ValueError, match='section 2 protocol: SCRF needs explicit'):
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

    The original fixture's SCRF=Check is now correctly unsupported by T82's
    explicit-protocol rule. Change only the echo, preserving all numeric data.
    """
    path = directory / 'outputs/input.log'
    path.write_text(path.read_text().replace(
        '#P Geom=AllCheck Guess=TCheck SCRF=Check GenChk RB3LYP/STO-3G Freq',
        '#P B3LYP/STO-3G Freq'))
    return directory
