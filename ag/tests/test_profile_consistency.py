import json
import re

import numpy as np
import pytest

from ag._profile_sources import DEFAULT_SETTINGS, integration_grid, load_species, protocol
from ag.profile import calculate_profile, markdown
from test_facts import attempt
from test_profile import definition, dump, source
from test_thermo import conformers, sp_input


@pytest.mark.parametrize('method', [
    'MP2', 'RMP2', 'UMP3', 'ROMP4(SDQ)', 'MP5', 'CCSD', 'CCSD(T)', 'QCISD',
    'QCISD(T)', 'CBS-QB3', 'G3', 'G4', 'B2PLYP', 'RB2PLYPD', 'mPW2PLYP',
    'DSD-PBEP86', 'revDSD-PBEP86', 'PBE0DH', 'PBEQIDH', 'PWPB95', 'XYG3',
    'wB97X-2', 'PM6', 'AM1', 'PM3', 'PM7', 'MNDO', 'DFTB', 'CASSCF(2,2)',
    'SomethingUnknown',
])
def test_only_scf_energy_methods_are_accepted(method):
    with pytest.raises(ValueError, match='当前只支持 SCF 能量的方法'):
        protocol(f'#p {method}/6-31G(d) SP')


@pytest.mark.parametrize('route', ['# G4', '# PM6 Opt Freq', '# CBS-QB3',
                                  '# ONIOM(B3LYP/6-31G(d):AM1) Opt',
                                  '# B3LYP/6-31G(d) TD', '# HF/6-31G MP2'])
def test_unsupported_routes_without_simple_method_basis(route):
    with pytest.raises(ValueError, match='当前只支持 SCF 能量的方法'):
        protocol(route)


@pytest.mark.parametrize('method', ['HF', 'RHF', 'UHF', 'ROHF', 'B3LYP', 'RB3LYP',
                                   'PBE1PBE', 'B97D3', 'wB97XD', 'CAM-B3LYP', 'M06-2X'])
def test_scf_methods_keep_dispersion_support(method):
    value = protocol(f'#p {method}/6-31G(d) EmpiricalDispersion=GD3BJ 5D 7F')
    assert value['method'] == method.lower() and value['dispersion'] == 'gd3bj'
    assert value['basis_function_type'] == '5D 7F'


@pytest.mark.parametrize('keyword', ['Int=UltraFine', 'Integral = UltraFine', 'Int=( UltraFine )',
                                    'Integral(UltraFine)'])
def test_grid_aliases_and_default_are_recorded_separately(keyword):
    assert integration_grid('# HF/3-21G') == 'program_default'
    assert integration_grid('# HF/3-21G Int Freq') == 'program_default'
    assert integration_grid(f'# HF/3-21G {keyword}') == 'ultrafine'
    assert protocol(f'# HF/3-21G {keyword}') == protocol('# HF/3-21G')


@pytest.mark.parametrize('ts', [False, True])
def test_profile_rejects_anti_frequency_with_gauche_sp_input(tmp_path, ts):
    anti, gauche = conformers(tmp_path)
    if ts:
        log = anti / 'outputs/input.log'
        log.write_text(re.sub(r'(Frequencies --\s+)([\d.]+)', r'\1-\2', log.read_text(), count=1))
        (anti / 'review.md').write_text('profile_review: pass\nimaginary_mode_matches: true\n')
    sp = attempt(tmp_path, 'sp', 'butane_anti_freq.log')
    sp_input(sp, gauche)
    spec = {'attempts': [{'attempt_id': 'anti', 'spc_attempt_id': 'sp'}],
            'single_conformer_reason': 'synthetic pairing regression'}
    with pytest.raises(ValueError, match='SPC pairing RMSD'):
        load_species('state', spec, tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)


def test_profile_reports_rotated_sp_pairing_and_hashes(tmp_path):
    from test_thermo_sections import explicit_water
    water = explicit_water(attempt(tmp_path))
    sp = explicit_water(attempt(tmp_path, 'sp'))
    frame = sp_input(sp, water)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    sp_input(sp, water, coordinates=np.array(frame.coordinates) @ rotation + [1, 2, 3])
    spec = {'attempts': [{'attempt_id': 'water', 'spc_attempt_id': 'sp'}],
            'single_conformer_reason': 'synthetic rotated water'}
    row = load_species('state', spec, tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)['conformers'][0]
    assert row['pairing_evidence']['rmsd_angstrom'] < 1e-10
    assert len(row['pairing_evidence']['sp_input_geometry_sha256']) == 64
    assert len(row['pairing_evidence']['frequency_final_geometry_sha256']) == 64


@pytest.mark.parametrize('route', ['# B3LYP/6-31G(d) 6D EmpiricalDispersion=GD3BJ Freq',
                                  '# MP2/6-31G(d) Freq', '# B2PLYP/6-31G(d) Freq'])
def test_profile_rejects_basis_type_or_unsupported_method(tmp_path, route):
    path, data = definition(tmp_path)
    data['species']['P'] = source(tmp_path, 'P', -10, route=route)
    dump(path, data)
    with pytest.raises(ValueError, match='protocol|当前只支持 SCF 能量的方法'):
        calculate_profile(path)


def test_grid_warnings_include_all_conformers_and_layers(tmp_path):
    path, _ = definition(tmp_path)
    baseline = calculate_profile(path)
    fact_path = tmp_path / 'attempts/R-1/facts.json'
    facts = json.loads(fact_path.read_text())
    facts['route'] += ' Integral=UltraFine'
    dump(fact_path, facts)
    result = calculate_profile(path)
    assert result['states'] == baseline['states']
    assert result['steps'] == baseline['steps']
    assert 'R/R-1/frequency=ultrafine' in result['warnings'][0]
    assert result['species']['R']['warnings']
    assert 'program_default' in markdown(result) and 'ultrafine' in markdown(result)


def test_cached_thermo_pairing_evidence_is_preserved(tmp_path):
    spec = source(tmp_path, 'water', 0)
    path = tmp_path / 'analyses/water.json'
    table = json.loads(path.read_text())
    evidence = {'rmsd_angstrom': 0.0001, 'sp_input_geometry_sha256': 'a' * 64,
                'frequency_final_geometry_sha256': 'b' * 64}
    table['rows'][0]['pairing_evidence'] = evidence
    dump(path, table)
    result = load_species('water', spec, tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)
    assert result['conformers'][0]['pairing_evidence'] == evidence
