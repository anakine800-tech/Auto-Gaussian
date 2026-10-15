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


def selection_fixture(tmp_path, **kwargs):
    path, data = definition(tmp_path, energies=(0, 20, -5))
    data['species']['other_ts'] = source(tmp_path, 'other_ts', 21.13, ts=True, count=1, **kwargs)
    data['species']['other_ts']['single_conformer_reason'] = 'Synthetic single TS comparison'
    data['selectivity'] = [{'id': 'selectivity', 'products': {
        'Z': [{'species': 'TS1'}], 'A': [{'species': 'other_ts'}]}}]
    dump(path, data)
    return path, data


def test_selectivity_sign_order_and_lowest_conformer(tmp_path):
    path, data = selection_fixture(tmp_path)
    result = calculate_profile(path)
    comparison = result['selectivity'][0]
    pair = comparison['pairwise'][0]
    assert comparison['product_order'] == ['Z', 'A']
    assert list(comparison['products']) == ['Z', 'A']
    assert pair['ddG_barrier_kcal'] == pytest.approx(1.13)
    assert pair['ratio_a_over_b'] == pytest.approx(math.exp(1.13 / (R_KCAL*298.15)))
    assert comparison['ee_percent'] == pytest.approx(74, abs=0.2)
    assert comparison['dominant_products'] == ['Z']
    assert '第一个标签占优为正' in comparison['ee_sign_convention']
    assert comparison['channels']['Z'][0]['paths_source'] == '默认 1'
    assert comparison['channels']['Z'][0]['paths'] == 1
    assert comparison['lowest_conformer']['pairwise'][0]['ddG_barrier_kcal'] == pytest.approx(1.13 - R_KCAL*298.15*math.log(2))
    data['selectivity'][0]['products'] = dict(reversed(list(data['selectivity'][0]['products'].items())))
    dump(path, data)
    reverse = calculate_profile(path)['selectivity'][0]
    assert reverse['pairwise'][0]['ddG_barrier_kcal'] == pytest.approx(-1.13)
    assert reverse['pairwise'][0]['ratio_a_over_b'] * pair['ratio_a_over_b'] == pytest.approx(1)
    assert reverse['ee_percent'] == -comparison['ee_percent']
    assert reverse['dominant_products'] == ['Z']
    assert 'competing_ts' not in result and 'competing_ts_note' not in result


def test_two_channels_per_product_add_flux_and_report_degeneracies(tmp_path):
    path, data = selection_fixture(tmp_path)
    data['species']['z_extra'] = source(tmp_path, 'z_extra', 20.5, ts=True)
    data['species']['a_extra'] = source(tmp_path, 'a_extra', 21.0, ts=True)
    products = data['selectivity'][0]['products']
    products['Z'].append({'species': 'z_extra', 'paths': 2})
    products['A'].append({'species': 'a_extra'})
    # The z_extra ensemble includes a physical conformer degeneracy of 3.
    table_path = path.parent / 'z_extra.json'
    table = json.loads(table_path.read_text())
    table['rows'][0]['degeneracy'] = 3
    table['ensemble_G'] -= R_HARTREE * 298.15 * math.log(2)
    dump(table_path, table)
    dump(path, data)
    result = calculate_profile(path)['selectivity'][0]
    rt = R_KCAL * 298.15
    z = 1 + 4 * math.exp(-0.5/rt)  # 2 paths × ensemble partition-sum factor 2
    a = math.exp(-1.13/rt) + math.exp(-1/rt)
    assert result['products']['Z']['fraction'] == pytest.approx(z/(z+a))
    assert result['ee_percent'] == pytest.approx(100*(z-a)/(z+a))
    channel = result['channels']['Z'][1]
    assert channel['paths'] == 2 and channel['paths_source'] == '显式指定'
    assert [c['degeneracy'] for c in channel['conformer_degeneracies']] == [3, 1]


def test_paths_two_equals_energy_lowering_rt_ln_two(tmp_path):
    path, data = selection_fixture(tmp_path)
    data['selectivity'][0]['products']['A'][0]['paths'] = 2
    dump(path, data)
    weighted = calculate_profile(path)['selectivity'][0]
    data['selectivity'][0]['products']['A'][0]['paths'] = 1
    table_path = path.parent / 'other_ts.json'
    table = json.loads(table_path.read_text())
    shift = R_HARTREE * 298.15 * math.log(2)
    for row in table['rows']:
        row['qh_G'] -= shift
        row['qh_H'] -= shift
    table['ensemble_G'] -= shift
    dump(table_path, table)
    dump(path, data)
    lowered = calculate_profile(path)['selectivity'][0]
    assert lowered['products']['A'] == pytest.approx(weighted['products']['A'])
    assert lowered['ee_percent'] == pytest.approx(weighted['ee_percent'])
    assert lowered['lowest_conformer']['ee_percent'] == pytest.approx(weighted['lowest_conformer']['ee_percent'])


def test_three_products_ratios_no_ee_and_extreme_energy_offset(tmp_path):
    path, data = selection_fixture(tmp_path)
    data['species']['third'] = source(tmp_path, 'third', 20 + R_KCAL*298.15*math.log(3), ts=True)
    data['selectivity'][0]['products']['M'] = [{'species': 'third'}]
    dump(path, data)
    result = calculate_profile(path)['selectivity'][0]
    weights = [1, math.exp(-1.13/(R_KCAL*298.15)), 1/3]
    assert result['product_order'] == ['Z', 'A', 'M']
    assert [p['fraction'] for p in result['products'].values()] == pytest.approx([w/sum(weights) for w in weights])
    assert len(result['pairwise']) == 3
    assert result['pairwise'][1]['ratio_a_over_b'] == pytest.approx(3)
    assert result['products']['M']['effective_barrier_relative_kcal'] == pytest.approx(R_KCAL*298.15*math.log(3))
    assert 'ee_percent' not in result and 'ee_percent' not in result['lowest_conformer']
    for name in ('TS1', 'other_ts', 'third'):
        table_path = path.parent / f'{name}.json'
        table = json.loads(table_path.read_text())
        for row in table['rows']:
            row['qh_G'] -= 10000
            row['qh_H'] -= 10000
        table['ensemble_G'] -= 10000
        dump(table_path, table)
    shifted = calculate_profile(path)['selectivity'][0]
    assert [p['fraction'] for p in shifted['products'].values()] == pytest.approx([p['fraction'] for p in result['products'].values()])
    json.dumps(shifted, allow_nan=False)


def test_selectivity_species_perturbation_ranges_and_flip(tmp_path):
    path, data = selection_fixture(tmp_path)
    data['selectivity'][0]['perturb_kcal'] = 2
    dump(path, data)
    result = calculate_profile(path)['selectivity'][0]
    report = result['sensitivity']
    assert report['dominant_product_flipped'] and report['dominant_changed']
    assert len(report['variants']) == 4
    assert {(v['perturbed_species'], v['shift_kcal']) for v in report['variants']} == {
        ('TS1', -2), ('TS1', 2), ('other_ts', -2), ('other_ts', 2)}
    expected = [1/(1+math.exp(-gap/(R_KCAL*298.15))) for gap in (1.13-2, 1.13+2)]
    assert report['fraction_ranges']['Z'] == pytest.approx({'min': min(expected), 'max': max(expected)})
    assert result['lowest_conformer']['sensitivity']['dominant_product_flipped']
    rendered = markdown(calculate_profile(path))
    assert '占优产物翻转：True' in rendered and 'Minimum proportion' in rendered
    data['selectivity'][0]['perturb_kcal'] = 0
    dump(path, data)
    report = calculate_profile(path)['selectivity'][0]['sensitivity']
    assert not report['dominant_changed'] and not report['dominant_product_flipped']
    assert report['fraction_ranges']['Z']['min'] == report['fraction_ranges']['Z']['max']


@pytest.mark.parametrize('kwargs,error', [({'formula': ['H', 'H']}, 'elemental'), ({'charge': 1}, 'charge')])
def test_selectivity_identity_rejected(tmp_path, kwargs, error):
    path, _ = selection_fixture(tmp_path, **kwargs)
    with pytest.raises(ValueError, match=error):
        calculate_profile(path)


@pytest.mark.parametrize('mutation,error', [
    ('minimum', 'requires TS'), ('missing', 'missing species'),
    ('duplicate', 'Duplicate selectivity'), ('not_list', 'must be a list'),
    ('old_interface', 'Unknown profile field'), ('empty', 'empty TS channels'),
    ('one_product', 'at least two products')])
def test_selectivity_invalid_definition(tmp_path, mutation, error):
    path, data = selection_fixture(tmp_path)
    if mutation == 'minimum':
        data['selectivity'][0]['products']['Z'][0]['species'] = 'R'
    elif mutation == 'missing':
        data['selectivity'][0]['products']['A'][0]['species'] = 'absent'
    elif mutation == 'duplicate':
        data['selectivity'] *= 2
    elif mutation == 'old_interface':
        data['competing_ts'] = []
    elif mutation == 'empty':
        data['selectivity'][0]['products']['A'] = []
    elif mutation == 'one_product':
        del data['selectivity'][0]['products']['A']
    else:
        data['selectivity'] = {}
    dump(path, data)
    with pytest.raises(ValueError, match=error):
        calculate_profile(path)


@pytest.mark.parametrize('product', ['Z', 'A'])
def test_duplicate_ts_rejected_before_loading_sources(tmp_path, monkeypatch, capsys, product):
    path, data = selection_fixture(tmp_path)
    data['selectivity'][0]['products'][product].append({'species': 'TS1', 'paths': 2})
    dump(path, data)
    monkeypatch.setattr('ag.profile.load_species', lambda *args: pytest.fail('loaded duplicate TS source'))
    assert main(['profile', str(path), '--json']) == 1
    error = json.loads(capsys.readouterr().out)['error']
    assert 'selectivity: duplicate TS species' in error and "'TS1'" in error
    assert f"at product {product!r} channel 2" in error
    assert "first at product 'Z' channel 1" in error
    assert 'using paths' in error
    assert not list(path.parent.glob('*-profile.*'))


def test_ts_reuse_across_independent_selectivity_definitions_allowed(tmp_path):
    path, data = selection_fixture(tmp_path)
    data['selectivity'].append({**data['selectivity'][0], 'id': 'independent-comparison'})
    dump(path, data)
    first, second = calculate_profile(path)['selectivity']
    assert first['products'] == second['products']
    assert first['ee_percent'] == second['ee_percent']


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '2'])
def test_invalid_paths(tmp_path, value):
    path, data = selection_fixture(tmp_path)
    data['selectivity'][0]['products']['A'][0]['paths'] = value
    dump(path, data)
    with pytest.raises(ValueError, match='paths'):
        calculate_profile(path)


@pytest.mark.parametrize('value', [True, -1, float('nan'), float('inf')])
def test_invalid_selectivity_perturbation(tmp_path, value):
    path, data = selection_fixture(tmp_path)
    data['selectivity'][0]['perturb_kcal'] = value
    dump(path, data)
    with pytest.raises(ValueError, match='perturb_kcal'):
        calculate_profile(path)


def test_symmetry_warning_and_four_markdown_sections(tmp_path):
    path, _ = selection_fixture(tmp_path)
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
    for heading in ('焓熵分项', '动力学换算', '产物选择性', '对称数'):
        assert f'## {heading}' in rendered
    for text in ('没有隧穿校正', '不是微观动力学模型', 'gaussian_output', 'goodvibes_default', '最低构象'):
        assert text in rendered
