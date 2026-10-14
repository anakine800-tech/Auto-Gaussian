"""Synthetic T39 arithmetic and additive-output regression; no research data."""
import json
import math
from pathlib import Path

import pytest

from ag.cli import main
from ag.profile import calculate_profile, eyring, markdown, R_KCAL, R_L_ATM
from ag.thermo import HARTREE_TO_KCAL, R_HARTREE
from test_profile import definition, dump, source


def test_all_legacy_fields_exactly_unchanged(tmp_path):
    # Snapshot produced by the unmodified profile at 00705b9, using the existing
    # definition() synthetic example and perturb=1. New keys are the only delta.
    legacy = json.loads((Path(__file__).parent / 'data/profile_legacy_output.json').read_text())
    path, _ = definition(tmp_path)
    current = calculate_profile(path, perturb=1)

    def project(old, new):
        if isinstance(old, dict):
            return {k: project(v, new[k]) for k, v in old.items()}
        if isinstance(old, list):
            assert len(old) == len(new)
            return [project(a, b) for a, b in zip(old, new)]
        return new

    assert project(legacy, current) == legacy


def test_ensemble_h_s_use_g_weights_and_degeneracy(tmp_path):
    path, _ = definition(tmp_path)
    table_path = path.parent / 'R.json'
    table = json.loads(table_path.read_text())
    temperature = table['settings']['temperature_K']
    rt = R_HARTREE * temperature
    energies = [-100.0, -100.0 + rt * math.log(3)]
    enthalpies = [-99.98, -99.95]
    # d=(1,2): unnormalized weights (1, 2/3), populations (3/5, 2/5).
    for row, g, h, d in zip(table['rows'], energies, enthalpies, (1, 2)):
        row.update(qh_G=g, qh_H=h, qh_S=(h-g)/temperature, degeneracy=d)
    g_ens = -100 - rt * math.log(5/3)
    table['ensemble_G'] = g_ens
    dump(table_path, table)
    result = calculate_profile(path)
    item = result['species']['R']
    h_ens = 0.6 * enthalpies[0] + 0.4 * enthalpies[1]
    assert [c['population'] for c in item['conformers']] == pytest.approx([0.6, 0.4])
    assert item['ensemble_H_hartree'] == pytest.approx(h_ens)
    assert item['ensemble_S_hartree_per_K'] == pytest.approx((h_ens-g_ens)/temperature)
    assert item['ensemble_H_hartree'] - temperature * item['ensemble_S_hartree_per_K'] == pytest.approx(g_ens)
    for step in result['steps']:
        for direction, g_key in (('forward', 'forward_barrier_kcal'),
                                 ('reverse', 'reverse_barrier_kcal'), ('reaction', 'reaction_G_kcal')):
            assert step[f'{direction}_dH_kcal'] + step[f'{direction}_minus_TdS_kcal'] == pytest.approx(step[g_key])


@pytest.mark.parametrize('error,accepted', [(5e-7, True), (2e-6, False)])
def test_qh_consistency_tolerance_and_attempt_error(tmp_path, capsys, error, accepted):
    path, _ = definition(tmp_path)
    table_path = path.parent / 'R.json'
    table = json.loads(table_path.read_text())
    table['rows'][1]['qh_H'] += error
    dump(table_path, table)
    assert main(['profile', str(path), '--json']) == (0 if accepted else 1)
    result = json.loads(capsys.readouterr().out)
    if not accepted:
        assert 'R-1: qh_H - T*qh_S' in result['error']
        assert not list(path.parent.glob('*-profile.*'))


def association(tmp_path):
    path, data = definition(tmp_path, energies=(0, 4, -2), cycle=False)
    for name, energy, ts in (('TS1', 4, True), ('I', -2, False)):
        data['species'][name] = source(tmp_path, name, energy, ts=ts,
                                       formula=['O', 'O', 'H', 'H', 'H', 'H'])
    data['states'][0]['species'] = {'R': 2}
    dump(path, data)
    return path, data


def test_association_decomposition_corrections_and_kinetics(tmp_path):
    path, data = association(tmp_path)
    baseline = calculate_profile(path)
    step = baseline['steps'][0]
    assert [s['molecule_count'] for s in baseline['states']] == [2, 1, 1]
    assert step['molecule_counts'] == {'reactant': 2, 'ts': 1, 'product': 1}
    assert step['molecularity_change'] == -1
    assert step['reaction_molecularity_change'] == -1
    assert '按标准态浓度的准一级近似，受缔合熵模型影响' in step['forward_kinetics']['notes']
    assert '接近扩散控制，不宜用 TST 速率解释' in step['forward_kinetics']['notes']
    assert not step['reverse_kinetics']['notes']
    # Both corrections change only -TΔS. Enthalpy is paired qh_H, including SPC.
    data['standard_state'] = '1atm'
    data['explicit_solvent_concentrations_M'] = {'R': 2.0}
    dump(path, data)
    result = calculate_profile(path)
    modified = result['steps'][0]
    rt = R_KCAL * result['temperature_K']
    standard = rt * math.log(1 / (R_L_ATM * result['temperature_K']))
    delta = standard - 2 * rt * math.log(2)
    assert modified['forward_dH_kcal'] == step['forward_dH_kcal']
    assert modified['forward_minus_TdS_kcal'] - step['forward_minus_TdS_kcal'] == pytest.approx(delta)
    assert '接近扩散控制' not in ' '.join(modified['forward_kinetics']['notes'])
    item = result['species']['R']
    assert (item['ensemble_H_hartree'] - result['temperature_K'] * item['corrected_S_hartree_per_K']) * HARTREE_TO_KCAL == pytest.approx(item['corrected_G_kcal'])
    # Reverse the path: the reverse direction now carries the association note.
    data['states'].reverse()
    dump(path, data)
    reversed_step = calculate_profile(path)['steps'][0]
    assert reversed_step['molecularity_change'] == 0
    assert reversed_step['reverse_molecularity_change'] == -1
    assert '准一级' in ' '.join(reversed_step['reverse_kinetics']['notes'])


def test_diffusion_warning_cancels_spectator(tmp_path):
    path, data = association(tmp_path)
    data['species']['spectator'] = source(tmp_path, 'spectator', -10)
    for state in data['states']:
        state['species']['spectator'] = 1
    dump(path, data)
    result = calculate_profile(path)
    assert result['steps'][0]['molecule_counts'] == {'reactant': 3, 'ts': 2, 'product': 2}
    assert '接近扩散控制' in ' '.join(result['steps'][0]['forward_kinetics']['notes'])


def test_eyring_24_kcal_and_profile_temperature(tmp_path):
    assert eyring(24, 298.15)['half_life_s'] / 3600 == pytest.approx(12, rel=0.02)
    path, data = definition(tmp_path, energies=(0, 24, -2))
    result = calculate_profile(path)
    step = result['steps'][0]
    assert step['forward_kinetics']['half_life_s'] / 3600 == pytest.approx(12, rel=0.02)
    # Independent exact SI constants and existing profile R for both directions.
    for name, barrier in (('forward', 24), ('reverse', 26)):
        expected = (1.380649e-23 * 298.15 / 6.62607015e-34) * math.exp(-barrier / (R_KCAL*298.15))
        assert step[f'{name}_kinetics']['k_s-1'] == pytest.approx(expected)
        assert step[f'{name}_kinetics']['half_life_s'] == pytest.approx(math.log(2)/expected)
    for spec in data['species'].values():
        table_path = path.parent / spec['thermo']
        table = json.loads(table_path.read_text())
        table['settings']['temperature_K'] = 350.0
        for row in table['rows']:
            row['qh_S'] = (row['qh_H'] - row['qh_G']) / 350.0
        # Equal-conformer partition sum at the new temperature.
        table['ensemble_G'] = table['rows'][0]['qh_G'] - R_HARTREE * 350 * math.log(2)
        dump(table_path, table)
    warm = calculate_profile(path)['steps'][0]
    expected = (1.380649e-23 * 350 / 6.62607015e-34) * math.exp(-24 / (R_KCAL*350))
    assert warm['forward_kinetics']['k_s-1'] == pytest.approx(expected)


@pytest.mark.parametrize('barrier', [-1000, 1000])
def test_extreme_kinetics_remain_json_serializable(tmp_path, barrier):
    path, _ = definition(tmp_path, energies=(0, barrier, 0))
    result = calculate_profile(path)
    kinetics = result['steps'][0]['forward_kinetics']
    assert kinetics['k_s-1'] is None
    assert kinetics['half_life_s'] is None
    assert math.isfinite(kinetics['ln_k_s-1'])
    json.dumps(result, allow_nan=False)
    assert 'null (see JSON logarithm)' in markdown(result)


def competition(tmp_path, **kwargs):
    path, data = definition(tmp_path, energies=(0, 20, -5))
    data['species']['other_ts'] = source(tmp_path, 'other_ts', 21.13, ts=True, count=1, **kwargs)
    data['species']['other_ts']['single_conformer_reason'] = 'Synthetic single TS comparison'
    data['competing_ts'] = [{'id': 'selectivity', 'a': 'TS1', 'b': 'other_ts'}]
    dump(path, data)
    return path, data


def test_competing_ts_sign_ee_and_lowest_conformer(tmp_path):
    path, data = competition(tmp_path)
    result = calculate_profile(path)
    comparison = result['competing_ts'][0]
    assert comparison['ddG_barrier_kcal'] == pytest.approx(1.13)
    assert comparison['rate_ratio_a_over_b'] == pytest.approx(math.exp(1.13 / (R_KCAL*298.15)))
    assert comparison['ee_percent'] == pytest.approx(74, abs=0.2)
    assert comparison['faster'] == 'a'
    assert comparison['lowest_conformer']['ddG_barrier_kcal'] == pytest.approx(1.13 - R_KCAL*298.15*math.log(2))
    data['competing_ts'][0].update(a='other_ts', b='TS1')
    dump(path, data)
    reverse = calculate_profile(path)['competing_ts'][0]
    assert reverse['ddG_barrier_kcal'] == pytest.approx(-1.13)
    assert reverse['rate_ratio_a_over_b'] * comparison['rate_ratio_a_over_b'] == pytest.approx(1)
    assert reverse['ee_percent'] == comparison['ee_percent']
    assert reverse['faster'] == 'b'
    data['competing_ts'][0]['b'] = 'other_ts'
    dump(path, data)
    tie = calculate_profile(path)['competing_ts'][0]
    assert (tie['rate_ratio_a_over_b'], tie['ee_percent'], tie['faster']) == (1, 0, 'equal')


@pytest.mark.parametrize('kwargs,error', [({'formula': ['H', 'H']}, 'elemental'), ({'charge': 1}, 'charge')])
def test_competing_ts_identity_rejected(tmp_path, kwargs, error):
    path, _ = competition(tmp_path, **kwargs)
    with pytest.raises(ValueError, match=error):
        calculate_profile(path)


@pytest.mark.parametrize('mutation,error', [
    ('minimum', 'requires TS'), ('missing', 'missing species'),
    ('duplicate', 'Duplicate competing_ts'), ('not_list', 'must be a list')])
def test_competing_ts_invalid_definition(tmp_path, mutation, error):
    path, data = competition(tmp_path)
    if mutation == 'minimum':
        data['competing_ts'][0].update(a='R')
    elif mutation == 'missing':
        data['competing_ts'][0].update(b='absent')
    elif mutation == 'duplicate':
        data['competing_ts'] *= 2
    else:
        data['competing_ts'] = {}
    dump(path, data)
    with pytest.raises(ValueError, match=error):
        calculate_profile(path)


def test_symmetry_warning_and_four_markdown_sections(tmp_path):
    path, _ = competition(tmp_path)
    baseline = calculate_profile(path)
    assert baseline['symmetry']['warnings'] == []
    table_path = path.parent / 'R.json'
    table = json.loads(table_path.read_text())
    table['rows'][0]['rotational_symmetry_number'] = 3
    table['rows'][0]['rotational_symmetry_source'] = {'kind': 'gaussian_output', 'file': 'input.log', 'line': 10}
    dump(table_path, table)
    facts_path = tmp_path / 'attempts/R-0/facts.json'
    facts = json.loads(facts_path.read_text())
    facts['route'] += ' NoSymm'
    dump(facts_path, facts)
    result = calculate_profile(path)
    warnings = '\n'.join(result['symmetry']['warnings'])
    assert '混用 nosymm' in warnings and 'σ 不同' in warnings and 'σ > 1' in warnings
    conformer = result['species']['R']['conformers'][0]
    assert conformer['nosymm'] is True
    assert conformer['RT_ln_sigma_kcal'] == pytest.approx(R_KCAL*298.15*math.log(3))
    assert result['steps'] == baseline['steps']  # report only; no implicit energy correction
    rendered = markdown(result)
    for heading in ('焓熵分项', '动力学换算', '竞争 TS 比较', '对称数'):
        assert f'## {heading}' in rendered
    for text in ('没有隧穿校正', '不是微观动力学模型', 'gaussian_output', 'goodvibes_default', '最低构象'):
        assert text in rendered
