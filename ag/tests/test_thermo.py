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
    paths = write_analysis(result, tmp_path)
    assert json.loads(paths[0].read_text()) == result
    assert 'Population' in paths[1].read_text() and 'gauche' in paths[1].read_text()
    assert write_analysis(result, tmp_path)[0] != paths[0]


def test_boltzmann_stability_and_degeneracy():
    population, mean = boltzmann([-100, -100], [1, 2], 298.15)
    assert population == pytest.approx([1/3, 2/3]) and mean == pytest.approx(-100)
    population, _ = boltzmann([-1000, 0], [1, 2], 1)
    assert population == [1, 0]


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
