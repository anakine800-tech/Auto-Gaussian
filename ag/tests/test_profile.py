"""Synthetic H2O states test arithmetic, never scientific acceptance of a cycle."""
import json
import math
from pathlib import Path

import pytest

from ag.cli import main
from ag.profile import (calculate_profile, energetic_span, write_profile,
                        R_KCAL, R_L_ATM)
from ag._profile_sources import DEFAULT_SETTINGS, parse_formula, protocol
from ag.thermo import HARTREE_TO_KCAL, R_HARTREE


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def source(tmp_path, name, kcal, *, ts=False, formula=None, charge=0, settings=None,
           route='#p B3LYP/6-31G(d) empiricaldispersion=GD3BJ freq', count=2, sp=None):
    settings = dict(settings or DEFAULT_SETTINGS)
    rows = []
    elements = formula or ['O', 'H', 'H']
    for index in range(count):
        aid = f'{name}-{index}'
        directory = tmp_path / 'attempts' / aid
        facts = {'schema': 'ag-facts/1', 'program': 'gaussian', 'program_version': 'Gaussian 16 Rev A.03', 'termination': 'normal',
                 'n_atoms': len(elements), 'charge': charge, 'multiplicity': 1,
                 'n_imag': 1 if ts else 0, 'route': route, 'final_geometry': 'final.xyz',
                 'energies': {'scf': kcal / HARTREE_TO_KCAL}}
        dump(directory / 'facts.json', facts)
        (directory / 'final.xyz').write_text(f'{len(elements)}\nSynthetic test\n' + ''.join(f'{e} 0 0 {i}\n' for i, e in enumerate(elements)))
        if ts:
            (directory / 'review.md').write_text('Synthetic direction review\nprofile_review: pass\nimaginary_mode_matches: true\n')
        # Equal conformers chosen so their partition sum is exactly the input G.
        g = kcal / HARTREE_TO_KCAL + R_HARTREE * settings['temperature_K'] * math.log(count)
        rows.append({'attempt_id': aid, 'qh_G': g, 'degeneracy': 1, 'spc_attempt_id': sp})
    data = {'schema': 'ag-thermo/1', 'goodvibes_version': '4.3.0', 'units': {'energy': 'Hartree'},
            'settings': settings, 'rows': rows, 'ensemble_G': kcal / HARTREE_TO_KCAL,
            'weighted_mean_G': 12345}
    dump(tmp_path / 'analyses' / f'{name}.json', data)
    return {'thermo': f'{name}.json'}


def definition(tmp_path, energies=(0, 20, -5, 15, -10), cycle=True):
    names = ['R', 'TS1', 'I', 'TS2', 'P'][:len(energies)]
    species, states = {}, []
    for index, (name, energy) in enumerate(zip(names, energies)):
        species[name] = source(tmp_path, name, energy, ts=index % 2 == 1)
        states.append({'id': name, 'kind': 'ts' if index % 2 else 'minimum', 'species': {name: 1}})
    data = {'reference': 'R', 'species': species, 'states': states, 'catalytic_cycle': cycle}
    path = tmp_path / 'analyses' / 'reaction.json'
    dump(path, data)
    return path, data


def test_balanced_profile_ensemble_barriers_and_span(tmp_path):
    path, _ = definition(tmp_path)
    result = calculate_profile(path)
    assert [r['relative_G_kcal'] for r in result['states']] == pytest.approx([0, 20, -5, 15, -10])
    assert [s['forward_barrier_kcal'] for s in result['steps']] == pytest.approx([20, 20])
    assert [s['reverse_barrier_kcal'] for s in result['steps']] == pytest.approx([25, 25])
    assert [s['reaction_G_kcal'] for s in result['steps']] == pytest.approx([-5, -5])
    assert result['energetic_span']['delta_E_kcal'] == pytest.approx(20)
    assert result['energetic_span']['TDTS'] == ['TS1', 'TS2']
    assert result['energetic_span']['TDI'] == ['I', 'R']
    assert all('weighted_mean_G' not in s for s in result['species'].values())
    assert 'G(TS1) - G(R)' == result['steps'][0]['formulas']['forward']


@pytest.mark.parametrize('field,value,error', [
    ('charge', 1, 'charge'), ('n_imag', 1, 'TS review'),
    ('route', '#p M06/6-31G(d) freq', 'protocol'),
    ('route', '#p B3LYP/def2SVP empiricaldispersion=GD3BJ freq', 'protocol'),
    ('route', '#p B3LYP/6-31G(d) empiricaldispersion=GD3 freq', 'protocol'),
    ('route', '#p B3LYP/6-31G(d) empiricaldispersion=GD3BJ scrf=(smd,solvent=water) freq', 'protocol'),
    ('termination', 'incomplete', 'termination'), ('n_imag', 2, 'n_imag'),
    ('n_imag', None, 'n_imag'),
])
def test_reject_source_mismatch_without_output(tmp_path, capsys, field, value, error):
    path, _ = definition(tmp_path)
    for i in range(2):
        facts_path = tmp_path / 'attempts' / f'P-{i}' / 'facts.json'
        facts = json.loads(facts_path.read_text())
        facts[field] = value
        dump(facts_path, facts)
    assert main(['profile', str(path), '--json']) == 1
    output = json.loads(capsys.readouterr().out)
    # Missing review is a source error rather than an inferred rejection/pass.
    assert error.lower() in output['error'].lower() or field == 'n_imag' and 'review.md' in output['error']
    assert not list(path.parent.glob('*-profile.*'))


def test_element_imbalance(tmp_path):
    path, data = definition(tmp_path)
    data['species']['P'] = source(tmp_path, 'P', -10, formula=['H', 'H'])
    dump(path, data)
    with pytest.raises(ValueError, match='elemental'):
        calculate_profile(path)


@pytest.mark.parametrize('key,value', [('temperature_K', 310), ('concentration_mol_L', 0.1),
    ('qs', 'truhlar'), ('s_cutoff_cm1', 50), ('h_cutoff_cm1', 50), ('frequency_scale', 0.95)])
def test_thermo_settings_mismatch(tmp_path, key, value):
    path, data = definition(tmp_path)
    settings = {**DEFAULT_SETTINGS, key: value}
    data['species']['P'] = source(tmp_path, 'P', -10, settings=settings)
    dump(path, data)
    with pytest.raises(ValueError, match='inconsistent'):
        calculate_profile(path)


def test_missing_species_and_explicit_single_conformer(tmp_path):
    path, data = definition(tmp_path)
    del data['species']['P']
    dump(path, data)
    with pytest.raises(ValueError, match='missing species'):
        calculate_profile(path)
    data['species']['P'] = source(tmp_path, 'P', -10, count=1)
    dump(path, data)
    with pytest.raises(ValueError, match='single_conformer_reason'):
        calculate_profile(path)
    data['species']['P']['single_conformer_reason'] = 'Synthetic rigid representative for this arithmetic test'
    dump(path, data)
    assert calculate_profile(path)['species']['P']['ensemble_G_hartree'] == pytest.approx(-10 / HARTREE_TO_KCAL)


@pytest.mark.parametrize('mutation', ['wrong_review', 'wrong_direction', 'two_ts', 'ts_as_minimum', 'no_ts'])
def test_ts_acceptance(tmp_path, mutation):
    path, data = definition(tmp_path)
    if mutation in ('wrong_review', 'wrong_direction'):
        p = tmp_path / 'attempts' / 'TS1-0' / 'review.md'
        text = p.read_text().replace('pass', 'fail') if mutation == 'wrong_review' else p.read_text().replace('true', 'false')
        p.write_text(text)
    elif mutation == 'two_ts':
        data['states'][1]['species'] = {'TS1': 2}
    elif mutation == 'ts_as_minimum':
        data['states'][0]['species']['TS1'] = 1
    else:
        data['states'][1]['species'] = {'R': 1}
        data['species'].pop('TS1')
    dump(path, data)
    with pytest.raises(ValueError, match='TS review|requires'):
        calculate_profile(path)


def test_protocol_checks_both_composite_layers(tmp_path):
    path, data = definition(tmp_path)
    source(tmp_path, 'sp', 0, count=1)
    for spec in data['species'].values():
        p = path.parent / spec['thermo']
        table = json.loads(p.read_text())
        for row in table['rows']:
            row['spc_attempt_id'] = 'sp-0'
        dump(p, table)
    assert calculate_profile(path)['species']['R']['protocol']['single_point'] is not None
    p = path.parent / 'P.json'
    table = json.loads(p.read_text())
    for row in table['rows']:
        row['spc_attempt_id'] = None
    dump(p, table)
    with pytest.raises(ValueError, match='protocol'):
        calculate_profile(path)


def test_explicit_water_and_per_species_standard_correction(tmp_path):
    # 2 H2O -> (H2O)2 has delta_n = -1, all atomic inventories match.
    path, data = definition(tmp_path, energies=(0, 20, -5))
    data['species']['R'] = source(tmp_path, 'R', 0)
    data['species']['TS1'] = source(tmp_path, 'TS1', 20, ts=True, formula=['O', 'O', 'H', 'H', 'H', 'H'])
    data['species']['I'] = source(tmp_path, 'I', -5, formula=['O', 'O', 'H', 'H', 'H', 'H'])
    data['states'][0]['species'] = {'R': 2}
    data['explicit_solvent_concentrations_M'] = {'R': 55.5}
    dump(path, data)
    result = calculate_profile(path)
    expected = R_KCAL * 298.15 * math.log(55.5)
    assert expected == pytest.approx(2.379646492, abs=1e-6)
    assert result['species']['R']['concentration_correction_kcal'] == pytest.approx(expected)
    assert result['steps'][0]['forward_barrier_kcal'] == pytest.approx(20 - 2 * expected)
    # Converting 1 M source to 1 atm target counts each free molecule once.
    del data['explicit_solvent_concentrations_M']
    data['standard_state'] = '1atm'
    dump(path, data)
    result = calculate_profile(path)
    correction = R_KCAL * 298.15 * math.log(1 / (R_L_ATM * 298.15))
    assert correction == pytest.approx(-1.8943284, abs=1e-6)
    assert result['steps'][0]['forward_barrier_kcal'] == pytest.approx(20 - correction)
    # Source thermo at the equivalent 1 atm concentration -> target 1 M.
    for name in ('R', 'TS1', 'I'):
        table_path = path.parent / f'{name}.json'
        table = json.loads(table_path.read_text())
        table['settings']['concentration_mol_L'] = 1 / (R_L_ATM * 298.15)
        dump(table_path, table)
    data['standard_state'] = '1M'
    dump(path, data)
    assert calculate_profile(path)['steps'][0]['forward_barrier_kcal'] == pytest.approx(20 + correction)


def test_span_wraparound_ties_rotation_and_reference(tmp_path):
    path, data = definition(tmp_path, energies=(0, 10, -20, -5, -4))
    result = calculate_profile(path)
    span = result['energetic_span']
    assert span['delta_E_kcal'] == pytest.approx(26)  # 10 - (-20) - 4
    assert span['TDTS'] == ['TS1'] and span['TDI'] == ['I']
    assert span['determining_pairs'][0]['cycle_correction_kcal'] == pytest.approx(-4)
    data['reference'] = 'I'
    dump(path, data)
    assert calculate_profile(path)['energetic_span']['delta_E_kcal'] == pytest.approx(26)
    # Start at I; repeat TS1 and R in the next turnover with -4 offset.
    rotated = [{'id': n, 'kind': k, 'relative_G_kcal': e} for n, k, e in
               [('I', 'minimum', -20), ('TS2', 'ts', -5), ('R', 'minimum', -4), ('TS1', 'ts', 6), ('I_next', 'minimum', -24)]]
    assert energetic_span(rotated)['delta_E_kcal'] == pytest.approx(26)


def test_perturb_each_ts_changes_determining_pair(tmp_path):
    path, _ = definition(tmp_path, energies=(0, 20, -5, 14, -10))
    result = calculate_profile(path, perturb=2)
    sensitivity = result['sensitivity']
    assert len(sensitivity['variants']) == 4
    assert sensitivity['baseline']['pairs'] == [['TS1', 'R']]
    assert sensitivity['any_changed']
    assert not calculate_profile(path, perturb=0)['sensitivity']['any_changed']
    with pytest.raises(ValueError, match='perturb'):
        calculate_profile(path, perturb=math.nan)


def test_no_overwrite_either_file_and_cli_offline(tmp_path, monkeypatch, capsys):
    import ag.cli
    import socket
    monkeypatch.setattr(ag.cli, 'load_config', lambda: pytest.fail('profile loaded cluster config'))
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network access'))
    path, _ = definition(tmp_path)
    assert main(['profile', str(path), '--perturb', '1', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    paths = [path.parent / 'reaction-profile.json', path.parent / 'reaction-profile.md']
    before = [p.read_bytes() for p in paths]
    assert main(['profile', str(path), '--json']) == 1
    capsys.readouterr()
    assert before == [p.read_bytes() for p in paths]
    (path.parent / 'another.md').write_text('keep')
    with pytest.raises(FileExistsError):
        write_profile(result, path, 'another')
    assert not (path.parent / 'another.json').exists()
    assert (path.parent / 'another.md').read_text() == 'keep'
    assert 'TDTS/TDI' in paths[1].read_text() and 'G(TS1) - G(R)' in paths[1].read_text()


@pytest.mark.parametrize('problem', ['missing_file', 'nan', 'wrong_ensemble', 'duplicate_attempt', 'unknown_field', 'bad_stoichiometry'])
def test_malformed_source_no_curve(tmp_path, capsys, problem):
    path, data = definition(tmp_path)
    table_path = path.parent / 'R.json'
    table = json.loads(table_path.read_text())
    if problem == 'missing_file':
        table_path.unlink()
    elif problem == 'nan':
        table['rows'][0]['qh_G'] = float('nan')
        dump(table_path, table)
    elif problem == 'wrong_ensemble':
        table['ensemble_G'] = 1
        dump(table_path, table)
    elif problem == 'duplicate_attempt':
        table['rows'][1] = table['rows'][0]
        dump(table_path, table)
    elif problem == 'unknown_field':
        data['standardstate'] = '1atm'
        dump(path, data)
    else:
        data['states'][0]['species']['R'] = True
        dump(path, data)
    assert main(['profile', str(path), '--json']) == 1
    assert 'error' in json.loads(capsys.readouterr().out)
    assert not list(path.parent.glob('*-profile.*'))


def test_formula_and_route_parser():
    assert parse_formula('C4H10') == {'C': 4, 'H': 10}
    assert parse_formula('CH3COOH') == {'C': 2, 'H': 4, 'O': 2}
    for value in ('', 'C0H2', 'C(OH)2', 'H2O.xxx'):
        with pytest.raises(ValueError):
            parse_formula(value)
    assert protocol('#p B3LYP/6-31G(d) SCRF=(SMD, Solvent=Water) freq')['solvent'] == 'water'
    for route in ('#p b3lyp/gen freq', '#p b3lyp/6-31g scrf=read freq', '#p pm6 freq'):
        with pytest.raises(ValueError):
            protocol(route)


@pytest.mark.parametrize('keywords', ['Opt Freq', 'Freq'])
@pytest.mark.parametrize('route', [
    '#p B3LYP/6-31+G(d) {keywords} EmpiricalDispersion=GD3BJ SCRF=(SMD,Solvent=Water)',
    '#p B3LYP / 6-31+G( d ) {keywords} EmpiricalDispersion = GD3BJ scrf = ( smd , solvent = water )',
    '#p B3LYP/6-31+G(d) scrf = ( smd , solvent = water ) EmpiricalDispersion=GD3BJ {keywords}',
])
def test_protocol_whitespace_preserves_keyword_boundaries(route, keywords):
    assert protocol(route.format(keywords=keywords)) == {
        'method': 'b3lyp', 'basis': '6-31+g(d)', 'dispersion': 'gd3bj',
        'solvent_model': 'smd', 'solvent': 'water',
    }


def test_protocol_whitespace_does_not_erase_basis_differences():
    small = protocol('#p B3LYP/6-31+G(d) Opt Freq')
    assert small == protocol('#p B3LYP / 6-31+G( d ) Freq')
    large = protocol('#p B3LYP / 6-311++G( d , p ) Freq')
    assert large['basis'] == '6-311++g(d,p)'
    assert small != large


def test_direct_attempts_real_local_minimum_and_ts_logs(tmp_path):
    from test_facts import attempt
    from goodvibes.thermo import calc_bbe, ThermoOptions
    attempt(tmp_path, 'minimum', 'water_opt_freq.log')
    ts = attempt(tmp_path, 'ts', 'water_opt_freq.log')
    ts_log = ts / 'outputs' / 'input.log'
    ts_log.write_text(ts_log.read_text().replace('2017.6012', '-2017.6012'))
    (ts / 'review.md').write_text('Synthetic frequency sign test only\nprofile_review: pass\nimaginary_mode_matches: true\n')
    data = {'species': {
        'R': {'attempts': [{'attempt_id': 'minimum'}], 'single_conformer_reason': 'rigid water fixture'},
        'TS': {'attempts': [{'attempt_id': 'ts'}], 'single_conformer_reason': 'synthetic sign-change fixture'}},
        'states': [{'id': 'R', 'kind': 'minimum', 'species': {'R': 1}},
                   {'id': 'TS', 'kind': 'ts', 'species': {'TS': 1}},
                   {'id': 'P', 'kind': 'minimum', 'species': {'R': 1}}], 'reference': 'R'}
    path = tmp_path / 'analyses' / 'reaction.json'
    dump(path, data)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = calculate_profile(path)
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after
    options = ThermoOptions(QH=True, concentration=1.0, freq_scale_factor=1.0, zpe_scale_factor=1.0)
    expected = calc_bbe.from_options(str(ts_log), options).qh_gibbs_free_energy
    assert result['species']['TS']['ensemble_G_hartree'] == pytest.approx(expected)
    assert result['species']['TS']['n_imag'] == 1


@pytest.mark.parametrize('values,expected', [
    ([0.0, 2.8, 15.1, -9.3, 1.8, 23.9, 1.0, -10.4], 33.2),
    ([0.0, 3.0, 15.9, -8.5, 2.8, 23.7, 1.4, -10.6], 32.2),
])
def test_literature_nhc_cycle_numeric_points(values, expected):
    # Lv et al., Nat Commun 13, 36 (2022), DOI 10.1038/s41467-021-27813-4,
    # Fig. 2 (unbracketed cc-pV(DT)Z and bracketed aug-cc-pV(DT)Z values).
    # Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC8748609/#Fig2
    # All numerically labelled points are transcribed; model_TS3 is drawn but
    # has no energy label, so is NOT assigned a made-up value. This regression
    # checks the published numeric span, not completeness of their mechanism
    # or compatibility of the paper's protocol with Gaussian profile inputs.
    names = ['model_NHC', 'model_INT1', 'model_TS1', 'model_INT2',
             'model_INT3', 'model_TS2', 'model_INT4', 'product']
    states = [{'id': name, 'kind': 'ts' if '_TS' in name else 'minimum',
               'relative_G_kcal': value} for name, value in zip(names, values)]
    span = energetic_span(states)
    assert span['delta_E_kcal'] == pytest.approx(expected)
    assert span['TDTS'] == ['model_TS2']
    assert span['TDI'] == ['model_INT2']
    assert span['reaction_G_kcal'] == values[-1]


def test_existing_ag_thermo_output_with_direct_ts_and_composite(tmp_path):
    from test_facts import attempt
    from ag.thermo import calculate_thermo
    low = attempt(tmp_path, 'low')
    sp = attempt(tmp_path, 'sp')
    ts = attempt(tmp_path, 'ts')
    ts_log = ts / 'outputs' / 'input.log'
    ts_log.write_text(ts_log.read_text().replace('2017.6012', '-2017.6012'))
    (ts / 'review.md').write_text('Synthetic TS\nprofile_review: pass\nimaginary_mode_matches: true\n')
    from test_thermo import sp_input
    sp_input(sp, low)
    table = calculate_thermo([low], spc={str(low): str(sp)}, temp=310)
    dump(tmp_path / 'analyses' / 'thermo.json', table)
    data = {'reference': 'R', 'species': {
        'R': {'thermo': 'thermo.json', 'single_conformer_reason': 'water'},
        'TS': {'attempts': [{'attempt_id': 'ts', 'spc_attempt_id': 'sp'}], 'single_conformer_reason': 'synthetic TS'}},
        'states': [{'id': 'R', 'kind': 'minimum', 'species': {'R': 1}},
                   {'id': 'TS', 'kind': 'ts', 'species': {'TS': 1}},
                   {'id': 'P', 'kind': 'minimum', 'species': {'R': 1}}]}
    path = tmp_path / 'analyses' / 'reaction.json'
    dump(path, data)
    result = calculate_profile(path)
    assert result['temperature_K'] == 310
    assert result['species']['R']['ensemble_G_hartree'] == table['ensemble_G']
    assert result['species']['TS']['protocol']['single_point'] is not None
    assert not (ts / 'facts.json').exists()
    data['temperature_K'] = 298.15
    dump(path, data)
    with pytest.raises(ValueError, match='temperature'):
        calculate_profile(path)


def test_requested_settings_and_duplicate_json_fields_fail(tmp_path):
    path, data = definition(tmp_path)
    data['thermo_settings'] = {'qs': 'truhlar'}
    dump(path, data)
    with pytest.raises(ValueError, match='Requested thermo_settings'):
        calculate_profile(path)
    path.write_text('{"reference":"R", "reference":"P"}')
    with pytest.raises(ValueError, match='Duplicate JSON key'):
        calculate_profile(path)


@pytest.mark.parametrize('cached_atom', [False, True])
def test_profile_with_monatomic_species(tmp_path, capsys, cached_atom):
    from test_facts import attempt
    from ag.facts import build_facts
    from ag.thermo import calculate_thermo

    species = {}
    for name, fixture in [('water', 'water_opt_freq.log'), ('ts', 'water_opt_freq.log'),
                          ('F', 'fluoride_freq_synthetic.log'), ('F_shift', 'fluoride_freq_synthetic.log')]:
        directory = attempt(tmp_path, name, fixture)
        log = directory / 'outputs/input.log'
        # Keep molecular Opt Freq versus atomic Freq, as in the L3 inputs.
        text = log.read_text().replace('B3LYP/STO-3G', 'B3LYP/6-31+G(d)')
        if name == 'ts':
            text = text.replace('2017.6012', '-2017.6012')
            (directory / 'review.md').write_text(
                'Synthetic sign change only\nprofile_review: pass\nimaginary_mode_matches: true\n')
        if name == 'F_shift':
            # An invented +0.01 Hartree electronic shift isolates the atomic G
            # contribution; identical masses/temperatures cancel thermal terms.
            text = text.replace('-99.000000', '-98.990000').replace('-98.998584', '-98.988584')
            text = text.replace('-98.997640', '-98.987640').replace('-99.013000', '-99.003000')
        log.write_text(text)
        parsed = build_facts(directory)
        if name.startswith('F'):
            assert parsed['monatomic'] and parsed['n_imag'] == 0
        spec = {'attempts': [{'attempt_id': name}], 'single_conformer_reason': 'Synthetic rigid fixture'}
        if cached_atom and name.startswith('F'):
            dump(tmp_path / 'analyses' / f'{name}.json', calculate_thermo([directory]))
            spec = {'thermo': f'{name}.json', 'single_conformer_reason': 'Monatomic fixture'}
        species[name] = spec
    path = tmp_path / 'analyses/reaction.json'
    dump(path, {'reference': 'R', 'species': species, 'states': [
        {'id': 'R', 'kind': 'minimum', 'species': {'water': 1, 'F': 1}},
        {'id': 'TS', 'kind': 'ts', 'species': {'ts': 1, 'F': 1}},
        {'id': 'P', 'kind': 'minimum', 'species': {'water': 1, 'F_shift': 1}},
    ]})
    evidence = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in (tmp_path / 'attempts').rglob('*') if p.is_file()}
    assert main(['profile', str(path), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['species']['F']['n_imag'] == 0
    assert result['species']['F']['charge'] == -1
    assert result['steps'][0]['reaction_G_kcal'] == pytest.approx(0.01 * HARTREE_TO_KCAL)
    assert result['states'][-1]['relative_G_kcal'] == pytest.approx(0.01 * HARTREE_TO_KCAL)
    assert (path.parent / 'reaction-profile.json').is_file()
    assert evidence == {p: (p.read_bytes(), p.stat().st_mtime_ns)
                        for p in (tmp_path / 'attempts').rglob('*') if p.is_file()}


def test_direct_polyatomic_log_without_frequencies_is_rejected(tmp_path, capsys):
    from test_facts import attempt
    from ag.facts import build_facts
    path, data = definition(tmp_path, energies=(0, 20, -5))
    directory = attempt(tmp_path, 'missing_freq')
    log = directory / 'outputs/input.log'
    text = log.read_text()
    start = text.index(' Harmonic frequencies (')
    end = text.index(' - Thermochemistry -', start)
    log.write_text(text[:start] + text[end:])
    facts = build_facts(directory)
    assert facts['n_atoms'] == 3 and facts['n_imag'] is None
    assert facts['vibrational_modes_complete'] is False
    data['species']['R'] = {'attempts': [{'attempt_id': 'missing_freq'}],
                            'single_conformer_reason': 'Synthetic missing frequency block'}
    dump(path, data)
    assert main(['profile', str(path), '--json']) == 1
    assert 'n_imag must be 0 or 1' in json.loads(capsys.readouterr().out)['error']
    assert not list(path.parent.glob('*-profile.*'))


def test_pair_write_collision_rolls_back_only_own_new_file(tmp_path, monkeypatch):
    path, _ = definition(tmp_path)
    result = calculate_profile(path)
    original_open = Path.open
    destination = path.parent / 'race.md'
    def racing_open(self, mode='r', *args, **kwargs):
        if self == destination and mode == 'x':
            with original_open(self, 'w') as stream:
                stream.write('other writer')
        return original_open(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', racing_open)
    with pytest.raises(FileExistsError):
        write_profile(result, path, 'race')
    assert destination.read_text() == 'other writer'
    assert not (path.parent / 'race.json').exists()


@pytest.mark.parametrize('scope', ['species', 'conformer', 'spc', 'missing'])
def test_program_version_consistency(tmp_path, scope):
    path, data = definition(tmp_path)
    targets = ['P-0', 'P-1'] if scope == 'species' else ['P-0']
    if scope == 'spc':
        source(tmp_path, 'sp', 0, count=1)
        table_path = path.parent / 'P.json'
        table = json.loads(table_path.read_text())
        for row in table['rows']:
            row['spc_attempt_id'] = 'sp-0'
        dump(table_path, table)
        targets = ['sp-0']
    for aid in targets:
        facts_path = tmp_path / 'attempts' / aid / 'facts.json'
        facts = json.loads(facts_path.read_text())
        facts['program_version'] = None if scope == 'missing' else 'Gaussian 16 Rev C.01'
        dump(facts_path, facts)
    with pytest.raises(ValueError, match='program version'):
        calculate_profile(path)
    assert not list(path.parent.glob('*-profile.*'))
