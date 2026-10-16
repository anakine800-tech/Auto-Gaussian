"""Synthetic regression cases for incompatible conformer ensembles."""
import pytest

import ag.thermo as thermo
from test_facts import attempt
from test_thermo import conformers, sp_input


def alter_facts(monkeypatch, directory, **changes):
    original = thermo.parse_facts

    def parse(path):
        facts, geometries = original(path)
        if path == directory:
            facts.update(changes)
        return facts, geometries

    monkeypatch.setattr(thermo, 'parse_facts', parse)


def test_water_and_butane_cannot_form_one_ensemble(tmp_path):
    water = attempt(tmp_path)
    anti, _ = conformers(tmp_path)
    with pytest.raises(ValueError, match='Incomparable thermo ensemble:.*\n.*elements'):
        thermo.calculate_thermo([water, anti])


@pytest.mark.parametrize('field,value', [('charge', 1), ('multiplicity', 3),
                                       ('program_version', 'Gaussian 09 Revision D.01')])
def test_frequency_state_and_version_must_match(tmp_path, monkeypatch, field, value):
    anti, gauche = conformers(tmp_path)
    alter_facts(monkeypatch, gauche, **{field: value})
    with pytest.raises(ValueError, match=field):
        thermo.calculate_thermo([anti, gauche])


@pytest.mark.parametrize('route', ['# B3LYP/Def2SVP Freq', '# wB97XD/6-31G Freq',
                                  '# wB97XD/Def2SVP SCRF=(SMD,Solvent=Water) Freq',
                                  '# wB97XD/Def2SVP EmpiricalDispersion=GD3BJ Freq'])
def test_frequency_protocol_must_match(tmp_path, monkeypatch, route):
    anti, gauche = conformers(tmp_path)
    alter_facts(monkeypatch, gauche, route=route)
    with pytest.raises(ValueError, match='frequency_protocol'):
        thermo.calculate_thermo([anti, gauche])


def test_all_or_no_spc_lists_both_groups(tmp_path):
    anti, gauche = conformers(tmp_path)
    sp = attempt(tmp_path, 'sp', 'butane_anti_freq.log')
    sp_input(sp, anti)
    with pytest.raises(ValueError, match='with SPC: anti; without SPC: gauche'):
        thermo.calculate_thermo([anti, gauche], spc={str(anti): str(sp)})


@pytest.mark.parametrize('layer', ['frequency', 'single_point'])
@pytest.mark.parametrize('field,value', [('route', '# B3LYP/3-21G SP'),
                                       ('program_version', 'Gaussian 09 Revision D.01')])
def test_each_composite_layer_is_compared(tmp_path, monkeypatch, layer, field, value):
    anti, gauche = conformers(tmp_path)
    sp_a = attempt(tmp_path, 'sp-a', 'butane_anti_freq.log')
    sp_g = attempt(tmp_path, 'sp-g', 'butane_gauche_freq.log')
    sp_input(sp_a, anti)
    sp_input(sp_g, gauche)
    alter_facts(monkeypatch, gauche if layer == 'frequency' else sp_g, **{field: value})
    with pytest.raises(ValueError, match=layer + ('_protocol' if field == 'route' else '_program_version')):
        thermo.calculate_thermo([anti, gauche], spc={str(anti): str(sp_a), str(gauche): str(sp_g)})


@pytest.mark.parametrize('layer', ['frequency', 'single_point'])
@pytest.mark.parametrize('method', ['MP2', 'B2PLYP'])
def test_post_scf_methods_cannot_supply_either_layer(tmp_path, monkeypatch, layer, method):
    anti, _ = conformers(tmp_path)
    sp = attempt(tmp_path, 'sp', 'butane_anti_freq.log')
    sp_input(sp, anti)
    alter_facts(monkeypatch, anti if layer == 'frequency' else sp, route=f'# {method}/3-21G SP')
    with pytest.raises(ValueError, match='当前只支持 SCF 能量的方法'):
        thermo.calculate_thermo([anti], spc={str(anti): str(sp)})


@pytest.mark.parametrize('types', [('5D', '6D'), ('7F', '10F')])
def test_basis_function_types_must_match(tmp_path, monkeypatch, types):
    anti, gauche = conformers(tmp_path)
    for directory, basis_type in zip((anti, gauche), types):
        alter_facts(monkeypatch, directory, route=f'# HF/3-21G {basis_type} Freq')
    with pytest.raises(ValueError, match='basis_function_type'):
        thermo.calculate_thermo([anti, gauche])


def test_grid_difference_warns_without_changing_numbers(tmp_path, monkeypatch):
    anti, gauche = conformers(tmp_path)
    for directory in (anti, gauche):
        alter_facts(monkeypatch, directory, route='# wB97XD/Def2SVP Freq')
    baseline = thermo.calculate_thermo([anti, gauche])
    alter_facts(monkeypatch, gauche, route='# wB97XD/Def2SVP Freq Integral=(UltraFine)')
    result = thermo.calculate_thermo([anti, gauche])
    assert result['ensemble_G'] == baseline['ensemble_G']
    assert [r['population'] for r in result['rows']] == [r['population'] for r in baseline['rows']]
    assert result['rows'][1]['integration_grid']['frequency'] == 'ultrafine'
    assert 'program_default' in result['warnings'][0] and 'gauche/frequency=ultrafine' in result['warnings'][0]
    report = thermo.write_analysis(result, tmp_path)[1].read_text()
    assert '分子式相同不等于同一物种' in report and 'ultrafine' in report and '警告' in report


def test_monatomic_report_explains_no_vibrational_modes(tmp_path):
    atom = attempt(tmp_path, 'F', 'fluoride_freq_converged_synthetic.log')
    result = thermo.calculate_thermo([atom])
    assert '单原子无振动模式' in result['rows'][0]['frequency_evidence']['note']
    assert '单原子无振动模式' in thermo.write_analysis(result, tmp_path)[1].read_text()


def test_thermo_rejects_incomplete_modes_with_zero_imaginary_count(tmp_path, monkeypatch):
    anti, _ = conformers(tmp_path)
    alter_facts(monkeypatch, anti, n_imag=0, vibrational_modes_complete=False,
                n_vibrational_modes=35, expected_vibrational_modes=36)
    with pytest.raises(ValueError, match='n_vibrational_modes=35, expected_vibrational_modes=36'):
        thermo.calculate_thermo([anti])


@pytest.mark.parametrize('field', ['freq_step_converged', 'vibrational_modes_complete'])
def test_legacy_frequency_evidence_requires_refresh(tmp_path, monkeypatch, field):
    anti, _ = conformers(tmp_path)
    original = thermo.parse_facts

    def parse(path):
        facts, geometries = original(path)
        facts.pop(field)
        return facts, geometries

    monkeypatch.setattr(thermo, 'parse_facts', parse)
    with pytest.raises(ValueError, match='ag facts.*--refresh'):
        thermo.calculate_thermo([anti])
