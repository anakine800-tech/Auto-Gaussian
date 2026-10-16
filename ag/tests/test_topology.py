"""Hand-built small molecule geometry; no research logs or remote operations."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ag import geometry as geo, topology
from ag.cli import main


WATER = geo.Frame(('O', 'H', 'H'), ((0., 0., 0.), (0.96, 0., 0.), (-0.24, 0.93, 0.)))


def rows(frame):
    return '\n'.join(f'{symbol} {x} {y} {z}' for symbol, (x, y, z) in zip(frame.symbols, frame.coordinates))


def attempt(tmp_path, before=WATER, after=WATER, *, route='# opt freq hf/sto-3g', n_imag=0, charge=0):
    root = tmp_path / 'study'
    path = root / 'attempts' / 'water-001-opt'
    path.mkdir(parents=True)
    (root / 'analyses').mkdir()
    (path / 'manifest.json').write_text(json.dumps({'attempt_id': path.name, 'template': 'gaussian',
        'science': {'geometry': rows(before), 'route': route, 'charge': charge, 'multiplicity': 1}}))
    (path / 'facts.json').write_text(json.dumps({'n_imag': n_imag, 'route': route,
        'final_input_geometry': 'final_input.xyz', 'final_geometry': 'final.xyz'}))
    (path / 'final_input.xyz').write_text(geo.xyz_text([after]))
    return path


@pytest.fixture
def chemistry():
    pytest.importorskip('rdkit')
    pytest.importorskip('cclib')


def test_unchanged_perturbation(chemistry):
    final = replace(WATER, coordinates=((0., 0., 0.), (0.965, 0., 0.), (-0.24, 0.935, 0.)))
    report = topology.compare_minimum(WATER, final, 0)
    assert report['status'] == 'unchanged'
    assert all(not report[key] for key in topology.DIFFERENCES)
    assert report['bond_order_and_stereo_assessment']['status'] == 'evaluated'


def test_proton_transfer(chemistry):
    before = geo.Frame(('O', 'O', 'H'), ((0., 0., 0.), (4., 0., 0.), (1., 0., 0.)))
    after = replace(before, coordinates=((0., 0., 0.), (4., 0., 0.), (3., 0., 0.)))
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'changed'
    assert report['proton_differences'] == [{'hydrogen': 3, 'reference_owners': [1], 'endpoint_owners': [2]}]


@pytest.mark.parametrize('reverse', [False, True])
def test_bond_change(chemistry, reverse):
    before = geo.Frame(('C', 'C'), ((0., 0., 0.), (1.5, 0., 0.)))
    after = replace(before, coordinates=((0., 0., 0.), (4., 0., 0.)))
    if reverse:
        before, after = after, before
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'changed'
    assert report['bond_differences'][0]['atoms'] == [1, 2]
    assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'


@pytest.mark.parametrize('element', ['B', 'N', 'O'])
def test_uncertain_contacts_by_element(chemistry, element):
    from rdkit import Chem
    table = Chem.GetPeriodicTable()
    near = 1.35 * (table.GetRcovalent(element) + table.GetRcovalent('O'))
    before = geo.Frame((element, 'O'), ((0., 0., 0.), (4., 0., 0.)))
    after = replace(before, coordinates=((0., 0., 0.), (near, 0., 0.)))
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'unknown'
    assert report['uncertain_contacts']['submitted'][element] == []
    assert report['uncertain_contacts']['final'][element][0]['atoms'] == [1, 2]
    assert report['ambiguous_bonds']


def test_handbuilt_tetrahedral_flip_and_rotation(chemistry):
    # Distinct substituents on tetrahedral carbon; manually chosen bond lengths.
    s = 3 ** -0.5
    before = geo.Frame(('C', 'F', 'Cl', 'Br', 'I'), ((0., 0., 0.),
        (1.35*s, 1.35*s, 1.35*s), (1.77*s, -1.77*s, -1.77*s),
        (-1.94*s, 1.94*s, -1.94*s), (-2.14*s, -2.14*s, 2.14*s)))
    rotated = replace(before, coordinates=tuple((y+3, -x, z+2) for x, y, z in before.coordinates))
    mirrored = replace(before, coordinates=tuple((-x, y, z) for x, y, z in before.coordinates))
    assert topology.compare_minimum(before, rotated, 0)['status'] == 'unchanged'
    report = topology.compare_minimum(before, mirrored, 0)
    assert report['status'] == 'changed'
    assert report['stereo_differences'][0]['atom'] == 1


@pytest.mark.parametrize('after', [geo.Frame(('O',), ((0., 0., 0.),)),
    replace(WATER, symbols=('H', 'O', 'H'))])
def test_mismatch_is_unknown_without_comparing(tmp_path, chemistry, monkeypatch, after):
    path = attempt(tmp_path, after=after)
    def forbidden(*args):
        pytest.fail('must not compare mismatched atoms')
    monkeypatch.setattr(topology, 'compare_endpoint', forbidden)
    report = topology.analyze(path)
    assert report['status'] == 'unknown'
    assert report['bond_differences'] == []
    assert '不做重排' in report['reasons'][0]


@pytest.mark.parametrize('route', ['# opt=ts freq', '# Opt=(TS,CalcFC) freq', '# opt=qst2 freq', '# opt=(qst3,calcfc)'])
def test_ts_distances_only(tmp_path, chemistry, monkeypatch, route):
    after = replace(WATER, coordinates=((0., 0., 0.), (1.2, 0., 0.), (-0.24, 0.93, 0.)))
    path = attempt(tmp_path, after=after, route=route, n_imag=1)
    def forbidden(*args):
        pytest.fail('TS must not infer bonds')
    monkeypatch.setattr(topology, 'compare_endpoint', forbidden)
    report = topology.analyze(path, ['1-2'])
    assert report['mode'] == 'ts_distances'
    assert report['status'] == 'unknown'  # no topology verdict
    assert report['distance_report_status'] == 'reported'
    assert report['pair_distances'][0]['change'] == pytest.approx(0.24)
    assert report['distance_rule']['applied'] is False
    assert not report['bond_differences']
    report = topology.analyze(path)
    assert report['status'] == 'unknown'
    assert any('--pair' in reason for reason in report['reasons'])


@pytest.mark.parametrize(('route', 'n_imag'), [('# opt freq', 1), ('# opt=ts freq', 0), ('# opt=ts freq', 2)])
def test_ts_requires_both_conditions(tmp_path, chemistry, route, n_imag):
    report = topology.analyze(attempt(tmp_path, route=route, n_imag=n_imag))
    assert report['mode'] == 'minimum'


def test_qst_groups_are_named(tmp_path, chemistry):
    path = attempt(tmp_path, route='# opt=qst3 freq', n_imag=1)
    manifest = json.loads((path / 'manifest.json').read_text())
    manifest['science']['structures'] = [dict(geometry=rows(WATER)) for _ in range(3)]
    (path / 'manifest.json').write_text(json.dumps(manifest))
    report = topology.analyze(path, ['1-2'])
    assert [row['submitted_role'] for row in report['pair_distances']] == ['reactant', 'product', 'ts_guess']
    assert report['sources']['submitted']['geometries'][2]['geometry_pointer'] == '/science/structures/2/geometry'


def test_cli_sources_fallback_readonly_and_summary(tmp_path, chemistry, capsys, monkeypatch):
    path = attempt(tmp_path)
    (path / 'final_input.xyz').rename(path / 'final.xyz')
    (path / 'review.md').write_text('review remains unchanged')
    baseline = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()}
    out = path.parents[1] / 'analyses' / 'topology.json'
    monkeypatch.setattr('ag.cli.load_config', lambda *a, **k: pytest.fail('must not load remote config'))
    assert main(['topology', path.name, '--study', str(path.parents[1]), '--out', str(out), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(out.read_text())
    assert report['status'] == 'unchanged'
    assert '取向可能不同' in report['orientation_note']
    for role in ('submitted', 'final', 'facts'):
        src = report['sources'][role]
        assert src['sha256'] == sha256((path / src['file']).read_bytes()).hexdigest()
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == evidence for p, evidence in baseline.items())
    md = out.with_suffix('.md').read_text()
    assert topology.NOTICE in md and report['sources']['final']['sha256'] in md
    assert report['ag_version'] in md and '[1.2, 1.5]' in md
    assert main(['topology', str(path), '--out', str(out)]) == 1


@pytest.mark.parametrize('existing', ['json', 'md', 'symlink'])
def test_output_exclusive(tmp_path, chemistry, existing):
    path = attempt(tmp_path)
    out = tmp_path / 'report.json'
    target = out.with_suffix('.md') if existing == 'md' else out
    if existing == 'symlink':
        target.symlink_to(tmp_path / 'absent')
    else:
        target.write_text('keep')
    assert main(['topology', str(path), '--out', str(out)]) == 1
    if existing != 'symlink':
        assert target.read_text() == 'keep'
    else:
        assert target.is_symlink() and not (tmp_path / 'absent').exists()
    other = out if existing == 'md' else out.with_suffix('.md')
    assert not other.exists()


@pytest.mark.parametrize('pair', ['0-1', '1-1', '1-x', '1-4'])
def test_invalid_pairs(tmp_path, chemistry, pair):
    path = attempt(tmp_path, route='# opt=ts', n_imag=1)
    with pytest.raises(ValueError, match='pair'):
        topology.analyze(path, [pair])


def test_missing_charge_and_rdkit_failure(chemistry, monkeypatch):
    assert topology.compare_minimum(WATER, WATER, None)['status'] == 'unknown'
    def fail(*args):
        raise ValueError('cannot assign valence')
    monkeypatch.setattr(geo, 'infer_molecule', fail)
    report = topology.compare_minimum(WATER, WATER, 0)
    assert report['status'] == 'unknown'
    assert any('RDKit' in reason for reason in report['reasons'])
    assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'


def test_missing_rdkit_stays_unknown(monkeypatch):
    def fail(*args):
        raise ImportError('RDKit')
    monkeypatch.setattr(topology, 'compare_endpoint', fail)
    report = topology.compare_minimum(WATER, WATER, 0)
    assert report['status'] == 'unknown' and 'RDKit 不可用' in report['reasons'][0]


def test_final_input_preferred_and_atomic_numbers(tmp_path, chemistry):
    path = attempt(tmp_path)
    manifest = json.loads((path / 'manifest.json').read_text())
    manifest['science']['geometry'] = manifest['science']['geometry'].replace('O ', '8 ').replace('H ', '1 ')
    (path / 'manifest.json').write_text(json.dumps(manifest))
    (path / 'final.xyz').write_text('invalid unused fallback')
    report = topology.analyze(path)
    assert report['status'] == 'unchanged'
    assert report['sources']['final']['file'] == 'final_input.xyz'


def test_cli_multiple_pairs(tmp_path, chemistry, capsys):
    path = attempt(tmp_path, route='# opt=ts', n_imag=1)
    assert main(['topology', str(path), '--out', str(tmp_path / 'report.json'),
                 '--pair', '1-2', '2-3', '--pair', '1-3', '2-1', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result['pair_distances']) == 3


def test_unassigned_stereo_is_explicit_unknown(chemistry, monkeypatch):
    from ag import irc_compare
    monkeypatch.setattr(irc_compare, '_stereo', lambda *args: {1: '?'})
    report = topology.compare_minimum(WATER, WATER, 0)
    assert report['status'] == 'unknown'
    assert report['stereo_differences']
    assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'


def test_charge_comes_from_manifest(tmp_path, chemistry, monkeypatch):
    path = attempt(tmp_path, charge=-1)
    (path / 'facts.json').write_text(json.dumps({'n_imag': 0, 'charge': 7}))
    seen = []
    compare = topology.compare_endpoint
    def record(final, submitted, charge):
        seen.append(charge)
        return compare(final, submitted, charge)
    monkeypatch.setattr(topology, 'compare_endpoint', record)
    assert topology.analyze(path)['charge'] == -1
    assert seen == [-1]


@pytest.mark.parametrize('suffix', ['.json', '.md'])
def test_racing_report_creation_does_not_overwrite(tmp_path, chemistry, monkeypatch, suffix):
    path = attempt(tmp_path)
    out = tmp_path / 'report.json'
    analyze = topology.analyze
    def race(*args):
        result = analyze(*args)
        out.with_suffix(suffix).write_text('concurrent report')
        return result
    monkeypatch.setattr(topology, 'analyze', race)
    assert main(['topology', str(path), '--out', str(out)]) == 1
    assert out.with_suffix(suffix).read_text() == 'concurrent report'


def test_source_changed_while_reading(tmp_path, chemistry, monkeypatch):
    path = attempt(tmp_path)
    read_xyz = geo.read_xyz
    def race(source):
        frames = read_xyz(source)
        source.write_text(geo.xyz_text([replace(WATER, coordinates=((1., 0., 0.), *WATER.coordinates[1:]))]))
        return frames
    monkeypatch.setattr(geo, 'read_xyz', race)
    with pytest.raises(ValueError, match='changed during reading'):
        topology.analyze(path)


def test_nondefault_units_are_not_assumed_angstrom(tmp_path, chemistry):
    path = attempt(tmp_path, route='# opt freq units=bohr')
    report = topology.analyze(path)
    assert report['status'] == 'unknown'
    assert 'Units' in report['reasons'][0]


@pytest.mark.parametrize('before,after,formulas', [
    (WATER, replace(WATER, coordinates=(WATER.coordinates[0], (4., 0., 0.), WATER.coordinates[2])), ['HO', 'H']),
    (geo.Frame(('B', 'O'), ((0., 0., 0.), (1.5, 0., 0.))),
     geo.Frame(('B', 'O'), ((0., 0., 0.), (4., 0., 0.))), ['B', 'O']),
])
def test_fragment_split_and_formulas(tmp_path, chemistry, before, after, formulas):
    path = attempt(tmp_path, before, after)
    report = topology.analyze(path)
    assert report['status'] == 'changed'
    assert report['fragments']['submitted']['count'] == 1
    assert report['fragments']['final']['count'] == 2
    assert [item['formula'] for item in report['fragments']['final']['components']] == formulas
    assert any('片段数变化：1 → 2' in reason for reason in report['reasons'])
    summary = topology.markdown(report)
    assert 'fragments' in summary and all(formula in summary for formula in formulas)


def two_waters():
    return geo.Frame(WATER.symbols * 2, WATER.coordinates + tuple((x + 5., y, z) for x, y, z in WATER.coordinates))


def test_unchanged_disconnected_molecules(chemistry):
    before = two_waters()
    report = topology.compare_minimum(before, before, 0)
    assert report['status'] == 'unchanged'
    for name in ('submitted', 'final'):
        fragments = report['fragments'][name]
        assert fragments['count'] == 2
        assert fragments['components'] == [dict(atoms=[1, 2, 3], formula='H2O'), dict(atoms=[4, 5, 6], formula='H2O')]


@pytest.mark.parametrize('indices', [(1, 4), (0, 3)])
def test_same_element_exchange_is_unknown(tmp_path, chemistry, indices):
    before = two_waters()
    coordinates = list(before.coordinates)
    i, j = indices
    coordinates[i], coordinates[j] = coordinates[j], coordinates[i]
    after = replace(before, coordinates=tuple(coordinates))
    report = topology.analyze(attempt(tmp_path, before, after))
    assert report['status'] == 'unknown'
    assert report['bond_differences'] and report['proton_differences']
    assert report['same_connectivity_graph'] is True
    assert report['graph_keys']['endpoint'] == report['graph_keys']['reference']
    assert report['fragments']['submitted']['count'] == report['fragments']['final']['count'] == 2
    assert any('可能是同元素原子位置互换或编号映射问题，需人工核对' in reason for reason in report['reasons'])
    assert 'same_connectivity_graph' in topology.markdown(report)
    assert '无法由元素序列检测' not in ' '.join(report['limitations'])


def test_fragment_uncertainty_is_not_a_bond(chemistry):
    frame = geo.Frame(('B', 'O'), ((0., 0., 0.), (2., 0., 0.)))
    report = topology.compare_minimum(frame, frame, 0)
    assert report['status'] == 'unknown'
    assert report['fragments']['submitted']['count'] == 2
    assert report['ambiguous_bonds']
    assert report['fragments']['fragments_if_uncertain_bonded'] == {'submitted': 1, 'final': 1}
    assert report['fragments']['fragment_change_depends_on_uncertain_contacts'] is False


@pytest.mark.parametrize('element', ['B', 'C'])
@pytest.mark.parametrize('distance,definite_count', [(1.5, 1), (3.5, 2)])
@pytest.mark.parametrize('reverse', [False, True])
def test_fragment_change_dependent_on_uncertain_contact(tmp_path, chemistry, element, distance, definite_count, reverse):
    before = geo.Frame((element, 'O'), ((0., 0., 0.), (distance, 0., 0.)))
    after = replace(before, coordinates=((0., 0., 0.), (2., 0., 0.)))
    expected = [definite_count, 2]
    bonded = [definite_count, 1]
    if reverse:
        before, after = after, before
        expected.reverse()
        bonded.reverse()
    report = topology.analyze(attempt(tmp_path, before, after))
    fragments = report['fragments']
    assert report['status'] == 'unknown'
    assert [fragments[side]['count'] for side in ('submitted', 'final')] == expected
    assert fragments['fragments_if_uncertain_bonded'] == dict(zip(('submitted', 'final'), bonded))
    assert fragments['fragment_change_depends_on_uncertain_contacts'] is True
    from rdkit import Chem
    table = Chem.GetPeriodicTable()
    ratio = 2. / (table.GetRcovalent(element) + table.GetRcovalent('O'))
    reason = report['reasons'][-1]
    assert f"{'submitted' if reverse else 'final'} 原子 1–2 ({element}–O)" in reason
    assert f'距离 2.000000 Å，半径比 {ratio:.6f}' in reason
    assert '片段数是否变化取决于这些接触是否算作成键' in reason
    assert '变化是否依赖不确定接触：是' in topology.markdown(report)


@pytest.mark.parametrize('reverse', [False, True])
def test_definite_boron_oxygen_break_stays_changed(chemistry, reverse):
    before = geo.Frame(('B', 'O'), ((0., 0., 0.), (1.5, 0., 0.)))
    after = replace(before, coordinates=((0., 0., 0.), (3.5, 0., 0.)))
    if reverse:
        before, after = after, before
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'changed'
    assert set(report['fragments']) == {'submitted', 'final'}


@pytest.mark.parametrize('reverse', [False, True])
def test_both_fragment_treatments_change_in_same_direction(tmp_path, chemistry, reverse):
    # Independent B-O pairs: one stays uncertain; the other definitely splits.
    before = geo.Frame(('B', 'O', 'B', 'O'), ((0., 0., 0.), (2.2, 0., 0.), (0., 10., 0.), (1.5, 10., 0.)))
    after = replace(before, coordinates=before.coordinates[:-1] + ((3.5, 10., 0.),))
    if reverse:
        before, after = after, before
    report = topology.analyze(attempt(tmp_path, before, after))
    assert report['status'] == 'changed'
    assert report['fragments']['fragment_change_depends_on_uncertain_contacts'] is False
    assert report['fragments']['fragments_if_uncertain_bonded'] == (
        {'submitted': 3, 'final': 2} if reverse else {'submitted': 2, 'final': 3})
    assert '两种处理下连通片段数均同向变化' in report['reasons'][-1]
    assert '变化是否依赖不确定接触：否' in topology.markdown(report)


@pytest.mark.parametrize('reverse', [False, True])
def test_opposite_fragment_change_directions_stay_unknown(chemistry, reverse):
    before = geo.Frame(('B', 'O', 'B', 'O'), ((0., 0., 0.), (1.5, 0., 0.), (0., 10., 0.), (3.5, 10., 0.)))
    after = replace(before, coordinates=((0., 0., 0.), (2.2, 0., 0.), (0., 10., 0.), (2.2, 10., 0.)))
    if reverse:
        before, after = after, before
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'unknown'
    fragments = report['fragments']
    assert fragments['fragment_change_depends_on_uncertain_contacts'] is True
    delta = fragments['final']['count'] - fragments['submitted']['count']
    bonded = fragments['fragments_if_uncertain_bonded']
    assert delta * (bonded['final'] - bonded['submitted']) < 0
    assert all(pair in report['reasons'][-1] for pair in ('1–2 (B–O)', '3–4 (B–O)'))


def test_intrafragment_uncertain_contact_is_not_listed_as_cause(chemistry):
    before = geo.Frame(('B', 'O', 'C', 'C', 'C'),
                       ((0., 0., 0.), (1.5, 0., 0.), (0., 10., 0.), (1.52, 10., 0.), (1.52, 11.1, 0.)))
    after = replace(before, coordinates=(before.coordinates[0], (2.2, 0., 0.), *before.coordinates[2:]))
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'unknown'
    assert '1–2 (B–O)' in report['reasons'][-1]
    assert '3–5 (C–C)' not in report['reasons'][-1]


@pytest.mark.parametrize('ratio,definite_count,bonded_count', [
    (0.5, 2, 1), (0.6, 1, 1), (1.19, 1, 1), (1.2, 2, 1),
    (1.35, 2, 1), (1.5, 2, 1), (1.51, 2, 2)])
def test_fragment_treatments_preserve_radius_boundaries(chemistry, ratio, definite_count, bonded_count):
    from rdkit import Chem
    distance = 2 * Chem.GetPeriodicTable().GetRcovalent('H') * ratio
    frame = geo.Frame(('H', 'H'), ((0., 0., 0.), (distance, 0., 0.)))
    assert topology.fragments(frame)['count'] == definite_count
    assert topology.fragments(frame, _include_uncertain=True)['count'] == bonded_count
    if ratio < 0.6:
        reference = replace(frame, coordinates=((0., 0., 0.), (0.62, 0., 0.)))
        report = topology.compare_minimum(reference, frame, 0)
        assert report['status'] == 'unknown'
        assert '半径比 0.500000' in report['reasons'][-1]


@pytest.mark.parametrize('name,expected_sha256', [
    ('water', 'c9fd8fa3099cdabe32d09aca07538928b161e25905b89b85616cd960f4e3002e'),
    ('two_waters', '5f827c59ff7d2899a98dbd1a14a5f948f20bf291679a96fc9e50c59c240aa837'),
    ('water_exchange', '0f0569e57841361930cb0013b83491590c11d31183b1250b0c8f5166cc628656'),
    ('acetone_bf3_split', 'b07fc8dfe68022743adce5c42f016a74b9ffe3687fed16cd3eba1c114e71075d'),
    ('proton_transfer', '3f9c7a6efd42d026a7bf6db50cd095f3763516e8779748050b7dda4d01e40624'),
    ('boron_mirror', '84da7149aa529d0cd48b0a795c685de9a37c0bcc07aedda5e7bdab1c3d1d7e0c'),
])
def test_no_uncertain_contacts_preserve_main_json_bytes(tmp_path, chemistry, name, expected_sha256):
    # Baseline: main/v4.2.1 at 3ee74fc; exact CLI serialization, version fields excluded.
    charge = 0
    if name == 'water':
        before = after = WATER
    elif name in ('two_waters', 'water_exchange'):
        before = after = two_waters()
        if name == 'water_exchange':
            coordinates = list(before.coordinates)
            coordinates[1], coordinates[4] = coordinates[4], coordinates[1]
            after = replace(before, coordinates=tuple(coordinates))
    else:
        fixture_names = {'acetone_bf3_split': ('acetone_bf3', 'acetone_bf3_separated'),
                         'proton_transfer': ('enolate_hf', 'enolate_protonated_f'),
                         'boron_mirror': ('boron_adjacent', 'boron_adjacent_mirror')}
        before, after = (geo.read_xyz(Path(__file__).parent / 'fixtures' / 'inference' / (stem + '.xyz'))[0]
                         for stem in fixture_names[name])
        charge = -1 if name == 'proton_transfer' else 0
    report = topology.analyze(attempt(tmp_path, before, after, charge=charge))
    assert set(report['fragments']) == {'submitted', 'final'}
    for key in ('ag_version', 'ag_provenance'):
        report.pop(key)
    data = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    assert sha256(data).hexdigest() == expected_sha256


def test_ts_does_not_report_connectivity_fragments(tmp_path, chemistry, monkeypatch):
    def forbidden(*args):
        pytest.fail('TS must not infer connected components')
    monkeypatch.setattr(topology, '_fragments', forbidden)
    path = attempt(tmp_path, route='# opt=ts', n_imag=1)
    report = topology.analyze(path, ['1-2'])
    assert 'fragments' not in report
    assert report['distance_report_status'] == 'reported'


def test_proton_transfer_with_different_graph_stays_changed(chemistry):
    # Hand-built HF + water -> fluoride + hydronium; two fragments on both sides.
    before = geo.Frame(WATER.symbols + ('F', 'H'), WATER.coordinates + ((5., 0., 0.), (5.92, 0., 0.)))
    after = replace(before, coordinates=before.coordinates[:-1] + ((-0.24, -0.93, 0.),))
    report = topology.compare_minimum(before, after, 0)
    assert report['status'] == 'changed'
    assert report['same_connectivity_graph'] is False
    assert report['proton_differences'] == [{'hydrogen': 5, 'endpoint_owners': [1], 'reference_owners': [4]}]
    assert report['fragments']['submitted']['count'] == report['fragments']['final']['count'] == 2
