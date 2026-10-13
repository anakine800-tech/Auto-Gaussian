import json
import math
from pathlib import Path

import pytest
from goodvibes.thermo import ThermoOptions, calc_bbe

from ag.thermo import boltzmann, calculate_thermo, write_analysis, R_HARTREE
from test_facts import attempt


def conformers(tmp_path):
    return [attempt(tmp_path, 'anti', 'butane_anti_freq.log'),
            attempt(tmp_path, 'gauche', 'butane_gauche_freq.log')]


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
    base = calculate_thermo([anti])['rows'][0]
    row = calculate_thermo([anti], spc={str(anti): str(sp)})['rows'][0]
    assert row['spc_attempt_id'] == 'singlepoint'
    assert row['E']-base['E'] == pytest.approx(-0.1, abs=1e-8)
    for key in ('H','qh_H','qh_G'):
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
    result = calculate_thermo([attempt(tmp_path)])
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
