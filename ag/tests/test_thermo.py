import json
from hashlib import sha256
import math
from pathlib import Path

import pytest
from goodvibes.thermo import ThermoOptions, calc_bbe

from ag.thermo import boltzmann, calculate_thermo, write_analysis, R_HARTREE
from test_facts import attempt


def conformers(tmp_path):
    return [attempt(tmp_path, 'anti', 'butane_anti_freq.log'),
            attempt(tmp_path, 'gauche', 'butane_gauche_freq.log')]



def sp_input(sp, frequency, *, coordinates=None, symbols=None, route='# HF/3-21G SP'):
    from ag.facts import build_facts
    from ag.geometry import read_xyz
    build_facts(frequency)
    frame = read_xyz(frequency / 'final.xyz')[0]
    if coordinates is None:
        coordinates = frame.coordinates
    if symbols is None:
        symbols = frame.symbols
    text = '%nprocshared=8\n%mem=8GB\n' + route + '\n\nSP\n\n0 1\n'
    text += ''.join(f'{symbol} {x:.12f} {y:.12f} {z:.12f}\n'
                    for symbol, (x, y, z) in zip(symbols, coordinates)) + '\n'
    (sp / 'inputs').mkdir(exist_ok=True)
    (sp / 'inputs' / 'input.gjf').write_text(text)
    (sp / 'manifest.json').write_text(json.dumps({
        'template': 'gaussian', 'cores': 8, 'mem_gb': 12,
        'inputs': [{'name': 'input.gjf', 'sha256': sha256(text.encode()).hexdigest()}]}))
    return frame

def test_butane_table_against_goodvibes(tmp_path):
    anti, gauche = conformers(tmp_path)
    result = calculate_thermo([anti, gauche], degeneracy={str(gauche): 2})
    assert result['settings']['frequency_scale'] == 1
    for directory, row in zip([anti, gauche], result['rows']):
        oracle = calc_bbe.from_options(str(directory/'outputs'/'input.log'), ThermoOptions(
            QH=True, concentration=1.0, freq_scale_factor=1.0, zpe_scale_factor=1.0))
        assert row['E'] == oracle.scf_energy
        assert row['ZPE'] == oracle.zpe
        assert row['H'] == oracle.enthalpy
        assert row['qh_G'] == oracle.qh_gibbs_free_energy
    a, g = result['rows']
    ratio = 2*math.exp(-(g['qh_G']-a['qh_G'])/(R_HARTREE*298.15))
    assert g['population']/a['population'] == pytest.approx(ratio)
    assert sum(r['population'] for r in result['rows']) == pytest.approx(1)
    assert result['weighted_mean_G'] == pytest.approx(sum(r['population']*r['qh_G'] for r in result['rows']))
    rt = R_HARTREE*298.15
    expected = a['qh_G'] - rt*math.log1p(2*math.exp(-(g['qh_G']-a['qh_G'])/rt))
    assert result['ensemble_G'] == pytest.approx(expected, rel=0, abs=1e-12)
    paths = write_analysis(result, tmp_path)
    assert json.loads(paths[0].read_text()) == result
    assert 'Population' in paths[1].read_text() and 'gauche' in paths[1].read_text()
    assert f"ensemble_G): {result['ensemble_G']:.10f} Hartree" in paths[1].read_text()
    assert 'weighted_mean_G' in paths[1].read_text()
    assert write_analysis(result, tmp_path)[0] != paths[0]


def test_boltzmann_stability_and_degeneracy():
    population, mean, _ = boltzmann([-100, -100], [1, 2], 298.15)
    assert population == pytest.approx([1/3, 2/3]) and mean == pytest.approx(-100)
    population, _, ensemble = boltzmann([-1000, 0], [1, 2], 1)
    assert population == [1, 0]
    assert ensemble == -1000


def test_single_conformer_ensemble_equals_its_g():
    energy = -158.1887510934
    _, mean, ensemble = boltzmann([energy], [1], 298.15)
    assert ensemble == mean == energy


def test_two_conformer_ensemble_matches_analytic_formula():
    temperature = 310.0
    rt = R_HARTREE*temperature
    # Moderate energies allow the unshifted analytical expression as an oracle.
    energies = [-0.01, -0.008]
    expected = -rt*math.log(math.exp(-energies[0]/rt) + math.exp(-energies[1]/rt))
    _, _, ensemble = boltzmann(energies, [1, 1], temperature)
    assert ensemble == pytest.approx(expected, rel=0, abs=1e-14)
    _, _, shifted = boltzmann([g-1000 for g in energies], [1, 1], temperature)
    assert shifted == pytest.approx(expected-1000, rel=0, abs=1e-12)


def test_degeneracy_two_equals_two_identical_conformers():
    energy, temperature = -158.1887510934, 298.15
    _, _, degenerate = boltzmann([energy], [2], temperature)
    _, _, repeated = boltzmann([energy, energy], [1, 1], temperature)
    assert degenerate == pytest.approx(repeated, rel=0, abs=1e-12)
    assert degenerate == pytest.approx(
        energy - R_HARTREE*temperature*math.log(2), rel=0, abs=1e-12)


@pytest.mark.parametrize('energies,deg,temp', [([],[],298), ([0],[0],298),
    ([math.nan],[1],298), ([0],[1],0), ([0],[math.inf],298)])
def test_invalid_weighting(energies, deg, temp):
    with pytest.raises(ValueError):
        boltzmann(energies, deg, temp)


def test_spc_is_an_additive_electronic_correction(tmp_path):
    anti, gauche = conformers(tmp_path)
    sp = attempt(tmp_path, 'singlepoint', fixture=None)
    # Small synthetic SP output, with the same molecule/state metadata supplied
    # by the frequency fixture and no frequency/thermochemical section.
    text = (anti/'outputs'/'input.log').read_text()
    cutoff = text.index(' Harmonic frequencies')
    text = text[:cutoff].replace('-158.296186729', '-158.396186729')
    (sp/'outputs'/'input.log').write_text(text+'\n Normal termination of Gaussian 16\n')
    sp_input(sp, anti)
    base = calculate_thermo([anti])['rows'][0]
    row = calculate_thermo([anti], spc={str(anti): str(sp)})['rows'][0]
    assert row['spc_attempt_id'] == 'singlepoint'
    assert row['E']-base['E'] == pytest.approx(-0.1, abs=1e-8)
    for key in ('H','G','qh_H','qh_G'):
        assert row[key]-base[key] == pytest.approx(-0.1, abs=1e-8)
    assert row['ZPE'] == base['ZPE']


@pytest.mark.parametrize('kind', ['error', 'incomplete', 'imaginary', 'no_frequency'])
def test_refuses_unsuitable_input(tmp_path, kind):
    directory = attempt(tmp_path)
    path = directory/'outputs'/'input.log'
    text = path.read_text()
    if kind == 'error':
        text += '\nError termination via Lnk1e in PATH/l9999.exe\n'
    elif kind == 'incomplete':
        text = text.replace('Normal termination of Gaussian', 'Missing termination')
    elif kind == 'imaginary':
        text = text.replace('2017.6012', '-2017.6012')
    else:
        text = text[:text.index(' Harmonic frequencies')]+'\n Normal termination of Gaussian 16\n'
    path.write_text(text)
    with pytest.raises(ValueError, match='water'):
        calculate_thermo([directory])


def test_cli_and_options(tmp_path, capsys):
    from ag.cli import main
    conformers(tmp_path)
    assert main(['thermo','anti','gauche','--study',str(tmp_path),
                 '--degeneracy','gauche=2','--json']) == 0
    assert json.loads(capsys.readouterr().out)['rows'][1]['degeneracy'] == 2
    assert len(list((tmp_path/'analyses').glob('*.json'))) == 1
    assert main(['thermo','anti','--study',str(tmp_path),'--temp','nan']) == 1


def test_duplicate_and_bad_mappings(tmp_path):
    anti, gauche = conformers(tmp_path)
    with pytest.raises(ValueError, match='duplicates'):
        calculate_thermo([anti, anti])
    with pytest.raises(ValueError, match='does not match'):
        calculate_thermo([anti], degeneracy={str(gauche): 2})
    with pytest.raises(ValueError, match='positive integer'):
        calculate_thermo([anti], degeneracy={str(anti): -1})


def test_analysis_collision_does_not_overwrite(tmp_path, monkeypatch):
    import ag.thermo as thermo
    from test_thermo_sections import explicit_water
    result = calculate_thermo([explicit_water(attempt(tmp_path))])
    class FrozenClock:
        @staticmethod
        def now(tz):
            from datetime import datetime
            return datetime(2026,1,1,tzinfo=tz)
    monkeypatch.setattr(thermo, 'datetime', FrozenClock)
    paths = write_analysis(result, tmp_path)
    original = paths[0].read_bytes()
    with pytest.raises(FileExistsError):
        write_analysis(result, tmp_path)
    assert paths[0].read_bytes() == original


@pytest.mark.parametrize('reverse', [False, True])
def test_rejects_cross_paired_conformers(tmp_path, reverse):
    anti, gauche = conformers(tmp_path)
    frequency, wrong = (gauche, anti) if reverse else (anti, gauche)
    sp = attempt(tmp_path, 'sp', 'butane_anti_freq.log')
    # The output can even match the requested conformer; input must be checked.
    sp_input(sp, wrong)
    with pytest.raises(ValueError, match='SPC pairing RMSD'):
        calculate_thermo([frequency], spc={str(frequency): str(sp)})


def test_accepts_rotated_translated_input_and_reports_hashes(tmp_path):
    import numpy as np
    anti, _ = conformers(tmp_path)
    sp = attempt(tmp_path, 'sp', 'butane_anti_freq.log')
    frame = sp_input(sp, anti)
    original = calculate_thermo([anti], spc={str(anti): str(sp)})['rows'][0]
    angle = 0.731
    rotation = np.array([[math.cos(angle), -math.sin(angle), 0],
                         [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    coordinates = np.array(frame.coordinates) @ rotation + [3.2, -1.7, 0.8]
    sp_input(sp, anti, coordinates=coordinates)
    result = calculate_thermo([anti], spc={str(anti): str(sp)})
    row = result['rows'][0]
    evidence = row['pairing_evidence']
    assert evidence['rmsd_angstrom'] < 1e-10
    assert evidence['frequency_final_geometry_sha256'] == original['pairing_evidence']['frequency_final_geometry_sha256']
    assert evidence['sp_input_geometry_sha256'] != original['pairing_evidence']['sp_input_geometry_sha256']
    for name in ('sp_input_geometry_sha256', 'frequency_final_geometry_sha256'):
        assert len(evidence[name]) == 64
    payload = {'elements': list(frame.symbols), 'coordinates_angstrom': coordinates.round(12).tolist()}
    expected = sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    assert evidence['sp_input_geometry_sha256'] == expected
    assert row['qh_G'] == original['qh_G']
    markdown = write_analysis(result, tmp_path)[1].read_text()
    assert evidence['sp_input_geometry_sha256'] in markdown
    assert 'qh_H' in markdown and '1 atm → 1 M' in markdown and 'Low frequency' in markdown


@pytest.mark.parametrize('kind', ['element_order', 'same_element_swap', 'reflection',
                                  'missing_input', 'tampered_input', 'bohr', 'optimization'])
def test_pairing_rejects_missing_or_incompatible_evidence(tmp_path, kind):
    import numpy as np
    anti, gauche = conformers(tmp_path)
    sp = attempt(tmp_path, 'sp', 'butane_gauche_freq.log')
    frame = sp_input(sp, gauche)
    coordinates, symbols = list(frame.coordinates), list(frame.symbols)
    message = None
    if kind == 'element_order':
        symbols[0], symbols[4] = symbols[4], symbols[0]
        sp_input(sp, gauche, symbols=symbols)
        message = 'element sequence'
    elif kind == 'same_element_swap':
        coordinates[0], coordinates[1] = coordinates[1], coordinates[0]
        sp_input(sp, gauche, coordinates=coordinates)
        message = 'RMSD'
    elif kind == 'reflection':
        sp_input(sp, gauche, coordinates=np.array(coordinates) * [-1, 1, 1])
        message = 'RMSD'
    elif kind == 'missing_input':
        (sp / 'inputs' / 'input.gjf').unlink()
    elif kind == 'tampered_input':
        with (sp / 'inputs' / 'input.gjf').open('a') as stream:
            stream.write('\n')
        message = 'hash differs'
    else:
        route = '# HF/3-21G Units=Bohr' if kind == 'bohr' else '# HF/3-21G Opt'
        sp_input(sp, gauche, route=route)
        message = 'angstrom' if kind == 'bohr' else 'single-point'
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        calculate_thermo([gauche], spc={str(gauche): str(sp)})


@pytest.mark.parametrize('stretch,accepted', [(1.001, True), (1.01, False)])
def test_pairing_rmsd_threshold(tmp_path, stretch, accepted):
    import numpy as np
    from test_thermo_sections import explicit_water
    water = explicit_water(attempt(tmp_path))
    sp = explicit_water(attempt(tmp_path, 'sp'))
    frame = sp_input(sp, water)
    sp_input(sp, water, coordinates=np.array(frame.coordinates) * stretch)
    if accepted:
        row = calculate_thermo([water], spc={str(water): str(sp)})['rows'][0]
        assert 0 < row['pairing_evidence']['rmsd_angstrom'] <= 1e-3
    else:
        with pytest.raises(ValueError, match='RMSD'):
            calculate_thermo([water], spc={str(water): str(sp)})


@pytest.mark.parametrize('temp,conc', [(298.15, 1.0), (340.0, 0.2)])
def test_rrho_qrrho_and_correction_decomposition(tmp_path, temp, conc):
    anti, _ = conformers(tmp_path)
    sp = attempt(tmp_path, 'sp', 'butane_anti_freq.log')
    sp_input(sp, anti)
    log = sp / 'outputs' / 'input.log'
    log.write_text(log.read_text().replace('-158.296186729', '-158.396186729'))
    row = calculate_thermo([anti], temp=temp, conc=conc, spc={str(anti): str(sp)})['rows'][0]
    gas = calc_bbe.from_options(str(anti / 'outputs' / 'input.log'), ThermoOptions(
        QH=True, temperature=temp, concentration=None, freq_scale_factor=1.0, zpe_scale_factor=1.0))
    assert row['G'] == pytest.approx(row['H'] - temp * row['S'], abs=1e-12, rel=0)
    assert row['qh_G'] == pytest.approx(row['qh_H'] - temp * row['qh_S'], abs=1e-12, rel=0)
    assert row['frequency_rrho_G_1atm'] == pytest.approx(gas.gibbs_free_energy, abs=1e-12, rel=0)
    expected_ss = R_HARTREE * temp * math.log(8.3144621 * temp / 101.325)
    assert row['standard_state_correction'] == pytest.approx(expected_ss, abs=1e-14)
    assert row['low_frequency_correction'] == pytest.approx(row['qh_G'] - row['G'], abs=1e-12)
    reconstructed = row['frequency_rrho_G_1atm'] + sum(row[k] for k in (
        'spc_correction', 'low_frequency_correction', 'standard_state_correction', 'concentration_correction'))
    assert row['qh_G'] == pytest.approx(reconstructed, abs=1e-12, rel=0)
    assert row['G'] == row['frequency_rrho']['G'] + row['spc_correction']
    assert row['S'] == row['frequency_rrho']['S']


def test_symmetry_and_degeneracy_sources(tmp_path):
    from test_thermo_sections import explicit_water
    water = explicit_water(attempt(tmp_path))
    row = calculate_thermo([water], degeneracy={str(water): 2})['rows'][0]
    assert row['degeneracy'] == 2 and row['degeneracy_source'].startswith('explicit')
    assert row['rotational_symmetry_number'] == 2
    source = row['rotational_symmetry_source']
    assert source['kind'] == 'gaussian_output'
    log = water / 'outputs' / 'input.log'
    assert log.read_text().splitlines()[source['line'] - 1].strip() == source['reported_text']
    log.write_text('\n'.join(line for line in log.read_text().splitlines()
                             if not line.strip().startswith('Rotational symmetry number')))
    default = calculate_thermo([water])['rows'][0]
    assert default['rotational_symmetry_number'] == 1
    assert default['rotational_symmetry_source']['kind'] == 'goodvibes_default'
    assert default['degeneracy_source'] == 'default 1'
    assert default['qh_G'] - row['qh_G'] == pytest.approx(-R_HARTREE * 298.15 * math.log(2), abs=1e-12)


def test_existing_butane_numerical_regression(tmp_path):
    anti, gauche = conformers(tmp_path)
    result = calculate_thermo([anti, gauche], degeneracy={str(gauche): 2})
    assert [r['qh_G'] for r in result['rows']] == pytest.approx(
        [-158.18875109341352, -158.18783436288754], abs=1e-12, rel=0)
    assert [r['population'] for r in result['rows']] == pytest.approx(
        [0.5690008202674615, 0.43099917973253854], abs=1e-12, rel=0)
    assert result['ensemble_G'] == pytest.approx(-158.18928349405817, abs=1e-12, rel=0)
