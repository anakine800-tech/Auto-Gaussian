"""Spin-prefix comparison only; invented numbers do not validate open-shell chemistry."""
import json

import pytest

from ag import asm, irc_review
from ag._profile_sources import DEFAULT_SETTINGS, load_species, protocol
from ag.facts import build_facts
from ag.profile import calculate_profile
from ag.thermo import calculate_thermo
from test_asm import WATER, attempt as energy_attempt, update_json
from test_profile import definition, dump
from test_thermo import sp_input
from test_thermo_sections import synthetic


CASES = [
    (1, 'M062X', 'RM062X', True, 'rm062x'),
    (1, 'M062X', 'UM062X', False, 'rm062x'),
    (2, 'B3LYP', 'UB3LYP', True, 'ub3lyp'),
    (2, 'B3LYP', 'RB3LYP', False, 'ub3lyp'),
    (2, 'ROB3LYP', 'UB3LYP', False, 'rob3lyp'),
]
PREFIX_CASES = pytest.mark.parametrize('multiplicity,left,right,equal,expected', CASES)


@PREFIX_CASES
def test_method_prefix_equivalence(multiplicity, left, right, equal, expected):
    a = protocol(f'# {left}/STO-3G Freq', multiplicity)
    b = protocol(f'# {right}/STO-3G Freq', multiplicity)
    assert a['method'] == expected
    assert (a == b) is equal


@pytest.mark.parametrize('multiplicity', [None, 0, -1, True, 1.0, '1'])
def test_no_default_spin_without_valid_multiplicity(multiplicity):
    with pytest.raises(ValueError, match='method multiplicity'):
        protocol('# M062X/STO-3G', multiplicity)


@pytest.mark.parametrize('method,multiplicity,expected', [
    ('revTPSS', 1, 'rrevtpss'), ('revTPSSH', 2, 'urevtpssh'),
    ('RrevTPSS', 2, 'rrevtpss'), ('ROHF', 1, 'rohf'), ('UHF', 1, 'uhf'),
    ('M062X', 3, 'um062x'), ('B3LYP', 4, 'ub3lyp'),
])
def test_complete_base_names_and_explicit_prefixes(method, multiplicity, expected):
    assert protocol(f'# {method}/STO-3G', multiplicity)['method'] == expected


@PREFIX_CASES
@pytest.mark.parametrize('consumer', ['thermo', 'profile'])
def test_opt_freq_binding_uses_spin_normalization(tmp_path, multiplicity, left, right,
                                                 equal, expected, consumer):
    directory = synthetic(tmp_path, opt=f'{left}/STO-3G', freq=f'{right}/STO-3G',
                          multiplicity=multiplicity, charge=multiplicity - 1)

    def run():
        if consumer == 'thermo':
            return calculate_thermo([directory])['rows'][0]
        return load_species('water', {'attempts': [{'attempt_id': 'water'}],
            'single_conformer_reason': 'synthetic prefix comparison'}, tmp_path,
            tmp_path / 'analyses', DEFAULT_SETTINGS)['conformers'][0]

    if not equal:
        with pytest.raises(ValueError, match='inconsistent Opt/Freq protocols:\nmethod:'):
            run()
        return
    row = run()
    assert row['frequency_source']['section_index'] == 2
    assert row['frequency_source']['protocol']['method'] == expected
    assert right in row['frequency_source']['route']  # retain the raw Freq evidence
    assert row['electronic_energy_source'] == row['frequency_source']


@PREFIX_CASES
@pytest.mark.parametrize('layer', ['frequency', 'single_point'])
def test_t82_compares_normalized_methods_in_each_layer(tmp_path, multiplicity, left,
                                                      right, equal, expected, layer):
    frequencies, spc = [], {}
    for name, method in [('a', left), ('b', right)]:
        freq_method = method if layer == 'frequency' else 'HF'
        freq = synthetic(tmp_path, name=name, standalone=True,
                         freq=f'{freq_method}/STO-3G', multiplicity=multiplicity,
                         charge=multiplicity - 1)
        frequencies.append(freq)
        if layer == 'single_point':
            sp = synthetic(tmp_path, name=f'sp-{name}', standalone=True,
                           freq=f'{method}/STO-3G', multiplicity=multiplicity,
                           charge=multiplicity - 1)
            log = sp / 'outputs/input.log'
            log.write_text(log.read_text().replace(' Fr\n eq', ' SP'))
            sp_input(sp, freq, route=f'# {method}/STO-3G SP', multiplicity=multiplicity,
                     charge=multiplicity - 1)
            spc[str(freq)] = str(sp)
    if not equal:
        with pytest.raises(ValueError, match=layer + '_protocol'):
            calculate_thermo(frequencies, spc=spc)
        return
    result = calculate_thermo(frequencies, spc=spc)
    assert {r['comparability'][layer + '_protocol']['method'] for r in result['rows']} == {expected}
    assert result['rows'][0]['qh_G'] == result['rows'][1]['qh_G']


@PREFIX_CASES
def test_profile_states_use_the_same_method_rule(tmp_path, multiplicity, left, right,
                                                equal, expected):
    path, _ = definition(tmp_path)
    for facts_path in (tmp_path / 'attempts').glob('*/facts.json'):
        facts = json.loads(facts_path.read_text())
        method = right if facts_path.parent.name.startswith('P-') else left
        facts.update(route=f'# {method}/6-31G(d) EmpiricalDispersion=GD3BJ Freq',
                     multiplicity=multiplicity, charge=multiplicity - 1)
        dump(facts_path, facts)
    if not equal:
        with pytest.raises(ValueError, match='protocol'):
            calculate_profile(path)
        return
    result = calculate_profile(path)
    assert [r['relative_G_kcal'] for r in result['states']] == pytest.approx([0, 20, -5, 15, -10])
    assert result['species']['P']['protocol']['frequency']['method'] == expected


@pytest.mark.parametrize('field', ['frequency_source', 'electronic_energy_source'])
def test_cached_source_normalization_keeps_provenance_strict_and_file_unchanged(tmp_path, field):
    directory = synthetic(tmp_path, opt='M062X/STO-3G', freq='M062X/STO-3G')
    build_facts(directory)
    table = json.loads(json.dumps(calculate_thermo([directory])))
    analyses = tmp_path / 'analyses'
    analyses.mkdir()
    path = analyses / 'thermo.json'
    spec = {'thermo': path.name, 'single_conformer_reason': 'synthetic cache'}
    # Simulate an older report that had no implicit prefix in its method label.
    table['rows'][0][field]['protocol']['method'] = 'm062x'
    path.write_text(json.dumps(table))
    before = path.read_bytes()
    result = load_species('water', spec, tmp_path, analyses, DEFAULT_SETTINGS)
    assert result['ensemble_G_hartree'] == table['ensemble_G']
    assert result['conformers'][0][field]['protocol']['method'] == 'rm062x'
    assert path.read_bytes() == before
    table['rows'][0][field]['protocol']['method'] = 'um062x'
    path.write_text(json.dumps(table))
    with pytest.raises(ValueError, match='cached thermo section sources'):
        load_species('water', spec, tmp_path, analyses, DEFAULT_SETTINGS)
    table['rows'][0][field]['protocol']['method'] = 'm062x'
    table['rows'][0][field]['section_index'] = 1
    path.write_text(json.dumps(table))
    with pytest.raises(ValueError, match='cached thermo section sources'):
        load_species('water', spec, tmp_path, analyses, DEFAULT_SETTINGS)


@PREFIX_CASES
def test_asm_energy_section_uses_shared_protocol(tmp_path, multiplicity, left, right,
                                               equal, expected):
    directory = energy_attempt(tmp_path, 'water', WATER, -75,
                               route=f'# {left}/STO-3G SP', multiplicity=multiplicity,
                               charge=multiplicity - 1)
    facts = json.loads((directory / 'facts.json').read_text())
    facts['job_sections'][0]['route'] = f'# {right}/STO-3G SP'
    if not equal:
        with pytest.raises(ValueError, match='Energy section protocol differs'):
            asm._energy_source(facts, 'input')
        return
    assert asm._energy_source(facts, 'input')['method'] == expected


@PREFIX_CASES
def test_irc_input_and_facts_use_shared_protocol(tmp_path, multiplicity, left, right,
                                               equal, expected):
    directory = energy_attempt(tmp_path, 'water', WATER, -75,
                               route=f'# {left}/STO-3G SP', multiplicity=multiplicity,
                               charge=multiplicity - 1)
    update_json(directory / 'facts.json', route=f'# {right}/STO-3G SP')
    evidence = irc_review._Evidence(tmp_path)
    if not equal:
        with pytest.raises(ValueError, match='facts/input method protocol differs'):
            irc_review._load(evidence, 'water')
        return
    assert irc_review._load(evidence, 'water')['protocol']['method'] == expected


@pytest.mark.parametrize('method,equal', [('RM062X', True), ('UM062X', False)])
def test_asm_input_protocol_uses_shared_normalization(tmp_path, method, equal):
    directory = energy_attempt(tmp_path, 'water', WATER, -75, route='# M062X/STO-3G SP')
    facts = json.loads((directory / 'facts.json').read_text())
    facts['route'] = facts['job_sections'][0]['route'] = f'# {method}/STO-3G SP'
    update_json(directory / 'facts.json', **facts)
    evidence = asm._Evidence(tmp_path)
    if not equal:
        with pytest.raises(ValueError, match='Input protocol differs'):
            asm._load_energy(evidence, 'water', 'input', 'test')
        return
    assert asm._load_energy(evidence, 'water', 'input', 'test')[0]['protocol']['method'] == 'rm062x'
