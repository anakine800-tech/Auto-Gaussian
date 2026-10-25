"""T135 synthetic H2O arithmetic; no stationary-point or scientific claims."""
import copy
import json
import math

import pytest

from ag.profile import calculate_profile, markdown, selectivity_results, R_KCAL, R_L_ATM
from ag.thermo import HARTREE_TO_KCAL, R_HARTREE
from test_profile import DEFAULT_SETTINGS, definition, dump, source


def three_numbers_fixture(tmp_path, *, groups=None, products=None, temperature=298.15,
                          standard_state='1M', concentration=1.0):
    """groups contains explicit (single-conformer G in kcal/mol, degeneracy)."""
    groups = groups or {'TS1': [(20, 1)], 'other_ts': [(21.13, 1)]}
    products = products or {'Z': [{'species': 'TS1'}], 'A': [{'species': 'other_ts'}]}
    path, data = definition(tmp_path, energies=(0, 20, -5), cycle=False)
    settings = {**DEFAULT_SETTINGS, 'temperature_K': temperature,
                'concentration_mol_L': concentration}
    for name, energy in (('R', 0), ('I', -5)):
        data['species'][name] = source(tmp_path, name, energy, settings=settings)
    for name, conformers in groups.items():
        spec = source(tmp_path, name, 0, ts=True, count=len(conformers), settings=settings)
        if len(conformers) == 1:
            spec['single_conformer_reason'] = 'Synthetic arithmetic example'
        data['species'][name] = spec
        table_path = path.parent / spec['thermo']
        table = json.loads(table_path.read_text())
        for row, (energy, degeneracy) in zip(table['rows'], conformers):
            g = energy / HARTREE_TO_KCAL
            row.update(qh_G=g, qh_H=g + 0.01, qh_S=0.01 / temperature,
                       degeneracy=degeneracy)
        minimum = min(g for g, _ in conformers)
        partition = sum(d * math.exp(-(g - minimum) / (R_KCAL * temperature))
                        for g, d in conformers)
        table['ensemble_G'] = minimum / HARTREE_TO_KCAL - R_HARTREE * temperature * math.log(partition)
        dump(table_path, table)
    data['standard_state'] = standard_state
    data['selectivity'] = [{'id': 'synthetic', 'products': products}]
    dump(path, data)
    return path, data


def assert_pair(selection, expected_lowest, expected_ensemble, index=0, temperature=298.15):
    pair = selection['lowest_ts']['pairwise'][index]
    old = selection['pairwise'][index]
    assert (pair['a'], pair['b']) == (old['a'], old['b'])
    assert pair['lowest_ts_ddG_kcal'] == pytest.approx(expected_lowest, rel=0, abs=1e-9)
    assert pair['ensemble_ddG_kcal'] == old['ddG_barrier_kcal']
    assert pair['ensemble_ddG_kcal'] == pytest.approx(expected_ensemble, rel=0, abs=1e-9)
    assert pair['difference_kcal'] == pytest.approx(expected_ensemble - expected_lowest, rel=0, abs=1e-9)
    assert pair['ratio_a_over_b'] == pytest.approx(math.exp(expected_lowest / (R_KCAL * temperature)))


def test_single_structure_per_product_three_numbers_and_signed_ee(tmp_path):
    path, data = three_numbers_fixture(tmp_path)
    result = calculate_profile(path)
    selection = result['selectivity'][0]
    assert_pair(selection, 1.13, 1.13)
    lowest = selection['lowest_ts']
    assert lowest['branches']['Z']['ties'] == []
    assert lowest['branches']['Z']['attempt_id'] == 'TS1-0'
    assert lowest['ee_percent'] == selection['ee_percent']
    assert lowest['ee_sign_convention'] == selection['ee_sign_convention']
    assert lowest['ee_percent'] == pytest.approx(100 * math.tanh(1.13 / (2 * R_KCAL * 298.15)))
    data['selectivity'][0]['products'] = dict(reversed(list(data['selectivity'][0]['products'].items())))
    dump(path, data)
    reversed_selection = calculate_profile(path)['selectivity'][0]
    assert_pair(reversed_selection, -1.13, -1.13)
    assert reversed_selection['lowest_ts']['ee_percent'] == -lowest['ee_percent']


@pytest.mark.parametrize('temperature', [298.15, 350.0])
def test_multiple_conformers_match_independent_partition_sum(tmp_path, temperature):
    path, _ = three_numbers_fixture(tmp_path, temperature=temperature, groups={
        'TS1': [(21.5, 1), (20, 1)], 'other_ts': [(21.13, 1), (21.4, 1), (22, 1)]})
    selection = calculate_profile(path)['selectivity'][0]
    rt = R_KCAL * temperature
    z = 1 + math.exp(-1.5 / rt)
    a = math.exp(-1.13 / rt) + math.exp(-1.4 / rt) + math.exp(-2 / rt)
    assert_pair(selection, 1.13, rt * math.log(z / a), temperature=temperature)
    assert selection['lowest_ts']['branches']['Z']['attempt_id'] == 'TS1-1'
    assert selection['lowest_ts']['branches']['A']['attempt_id'] == 'other_ts-0'


def test_branch_minimum_can_be_in_second_channel_and_keeps_its_paths(tmp_path):
    path, _ = three_numbers_fixture(tmp_path, groups={
        'TS1': [(20, 1)], 'z_extra': [(19.5, 1), (19, 1)], 'other_ts': [(21.13, 1)]},
        products={'Z': [{'species': 'TS1', 'paths': 10000}, {'species': 'z_extra', 'paths': 2}],
                  'A': [{'species': 'other_ts'}]})
    selection = calculate_profile(path)['selectivity'][0]
    branch = selection['lowest_ts']['branches']['Z']
    assert branch == {'species': 'z_extra', 'attempt_id': 'z_extra-1',
                      'corrected_G_kcal': pytest.approx(19), 'paths': 2,
                      'conformer_degeneracy': 1, 'ties': []}
    rt = R_KCAL * 298.15
    z = 10000 * math.exp(-1 / rt) + 2 * (1 + math.exp(-0.5 / rt))
    a = math.exp(-2.13 / rt)
    assert_pair(selection, 2.13 + rt * math.log(2), rt * math.log(z / a))
    assert selection['lowest_conformer']['pairwise'][0]['ddG_barrier_kcal'] != selection['lowest_ts']['pairwise'][0]['lowest_ts_ddG_kcal']


@pytest.mark.parametrize('paths', [1, 2])
def test_paths_weight_is_retained(tmp_path, paths):
    path, _ = three_numbers_fixture(tmp_path, products={
        'Z': [{'species': 'TS1'}], 'A': [{'species': 'other_ts', 'paths': paths}]})
    selection = calculate_profile(path)['selectivity'][0]
    expected = 1.13 - R_KCAL * 298.15 * math.log(paths)
    assert_pair(selection, expected, expected)
    assert selection['lowest_ts']['branches']['A']['paths'] == paths


def test_conformer_degeneracy_is_reported_but_excluded_from_single_weight(tmp_path):
    path, _ = three_numbers_fixture(tmp_path, groups={
        'TS1': [(20, 2)], 'other_ts': [(21.13, 1)]})
    selection = calculate_profile(path)['selectivity'][0]
    assert_pair(selection, 1.13, 1.13 + R_KCAL * 298.15 * math.log(2))
    assert selection['lowest_ts']['branches']['Z']['conformer_degeneracy'] == 2


@pytest.mark.parametrize('delta', [0, 0.5e-9, 1e-9, 1.5e-9])
def test_ties_use_channel_order_then_attempt_id_not_input_row_order(tmp_path, delta):
    path, _ = three_numbers_fixture(tmp_path, groups={
        'TS1': [(delta, 1), (delta, 3)], 'aaa': [(0, 1)], 'other_ts': [(1.13, 1)]},
        products={'Z': [{'species': 'TS1', 'paths': 2}, {'species': 'aaa', 'paths': 7}],
                  'A': [{'species': 'other_ts'}]})
    table_path = path.parent / 'TS1.json'
    table = json.loads(table_path.read_text())
    table['rows'].reverse()
    dump(table_path, table)
    branch = calculate_profile(path)['selectivity'][0]['lowest_ts']['branches']['Z']
    if delta <= 1e-9:
        assert (branch['species'], branch['attempt_id'], branch['paths']) == ('TS1', 'TS1-0', 2)
        assert branch['ties'] == [
            {'species': 'TS1', 'attempt_id': 'TS1-0'},
            {'species': 'TS1', 'attempt_id': 'TS1-1'},
            {'species': 'aaa', 'attempt_id': 'aaa-0'}]
    else:
        assert (branch['species'], branch['attempt_id'], branch['paths']) == ('aaa', 'aaa-0', 7)
        assert branch['ties'] == []


def test_three_products_have_all_pairs_in_definition_order_and_no_ee(tmp_path):
    path, _ = three_numbers_fixture(tmp_path, groups={
        'TS1': [(20, 1)], 'other_ts': [(21.13, 1)], 'third': [(19.7, 1)]},
        products={'Z': [{'species': 'TS1'}], 'A': [{'species': 'other_ts'}],
                  'M': [{'species': 'third'}]})
    result = calculate_profile(path)
    selection = result['selectivity'][0]
    lowest = selection['lowest_ts']
    assert [(p['a'], p['b']) for p in lowest['pairwise']] == [('Z', 'A'), ('Z', 'M'), ('A', 'M')]
    for index, expected in enumerate((1.13, -0.3, -1.43)):
        assert_pair(selection, expected, expected, index)
    assert 'ee_percent' not in lowest and 'ee_sign_convention' not in lowest
    table = markdown(result).split('#### 最低 TS / 系综 / 差值')[1].split('## 对称数')[0]
    assert len([line for line in table.splitlines() if line.startswith('| ')]) == 4


@pytest.mark.parametrize('standard_state', ['1M', '1atm'])
def test_species_corrections_are_reused_with_explicit_solvent_profile(tmp_path, standard_state):
    path, data = three_numbers_fixture(tmp_path, standard_state=standard_state, concentration=0.1)
    # Public input applies explicit solvent concentration only to minimum species.
    data['explicit_solvent_concentrations_M'] = {'R': 2.0}
    dump(path, data)
    result = calculate_profile(path)
    rt = R_KCAL * 298.15
    target = 1 if standard_state == '1M' else 1 / (R_L_ATM * 298.15)
    correction = rt * math.log(target / 0.1)
    branch = result['selectivity'][0]['lowest_ts']['branches']['Z']
    assert branch['corrected_G_kcal'] == pytest.approx(20 + correction, rel=0, abs=1e-9)
    assert branch['corrected_G_kcal'] == result['species']['TS1']['corrected_lowest_conformer_G_kcal']
    solvent = result['species']['R']
    assert solvent['standard_state_correction_kcal'] == correction
    assert solvent['concentration_correction_kcal'] == rt * math.log(2 / target)
    assert solvent['corrected_G_kcal'] == pytest.approx(rt * math.log(2 / 0.1), rel=0, abs=1e-9)
    assert_pair(result['selectivity'][0], 1.13, 1.13)


def test_selection_uses_supplied_corrected_energies_without_mutating_species(tmp_path):
    path, data = three_numbers_fixture(tmp_path, groups={
        'TS1': [(20, 1)], 'second': [(21, 1)], 'other_ts': [(22, 1)]},
        products={'Z': [{'species': 'TS1'}, {'species': 'second'}],
                  'A': [{'species': 'other_ts'}]})
    species = calculate_profile(path)['species']
    # Exercise the evaluator with synthetic precomputed per-species corrections;
    # this does not permit concentration corrections on TS in the public input.
    item = species['second']
    item['standard_state_correction_kcal'] = -0.5
    item['concentration_correction_kcal'] = -1.5
    item['corrected_G_kcal'] -= 2
    item['corrected_lowest_conformer_G_kcal'] -= 2
    before = copy.deepcopy(species)
    branch = selectivity_results(data['selectivity'], species, 298.15)[0]['lowest_ts']['branches']['Z']
    assert branch['species'] == 'second'
    assert branch['corrected_G_kcal'] == pytest.approx(19, rel=0, abs=1e-9)
    assert species == before


@pytest.mark.parametrize('gap', [-1000, 1000])
def test_extreme_single_ts_ratio_keeps_json_finite(tmp_path, gap):
    path, _ = three_numbers_fixture(tmp_path, groups={
        'TS1': [(0, 1)], 'other_ts': [(gap, 1)]})
    result = calculate_profile(path)
    lowest = result['selectivity'][0]['lowest_ts']
    assert lowest['pairwise'][0]['ratio_a_over_b'] is None
    assert lowest['pairwise'][0]['lowest_ts_ddG_kcal'] == pytest.approx(gap)
    assert lowest['ee_percent'] == (100 if gap > 0 else -100)
    json.dumps(result, allow_nan=False)


def test_markdown_new_table_keeps_legacy_tables_and_escapes_labels(tmp_path):
    path, _ = three_numbers_fixture(tmp_path, products={
        'Z|first\nlabel': [{'species': 'TS1'}], 'A': [{'species': 'other_ts'}]})
    result = calculate_profile(path)
    old = copy.deepcopy(result)
    del old['selectivity'][0]['lowest_ts']
    rendered = markdown(result)
    beginning, addition = rendered.split('\n#### 最低 TS / 系综 / 差值', 1)
    _, ending = addition.split('\n## 对称数', 1)
    assert beginning.rstrip() + '\n\n## 对称数' + ending == markdown(old)
    assert '| Z\\|first label / A | 1.130000 | 1.130000 | 0.000000 | TS1 / TS1-0 | other_ts / other_ts-0 |' in rendered
    assert '不乘构象简并度' in rendered
    assert '单结构结果和系综结果不是同一个物理量' in rendered
    assert '不代表哪个更正确' in rendered
