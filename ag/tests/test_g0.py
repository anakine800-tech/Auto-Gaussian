"""T137/T138 synthetic local diagnostics; no calculations or real study data."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

from ag import _parse_outputs, catalog, catalog_v2 as v2, cli, g0, g0_mapping, g0_modes, geometry as geo
from test_catalog import files, make_attempt, water, write_json
from test_catalog_v2 import GEOMETRY, XYZ, tree


def object_(root, identity='water-a', formula='H2O', charge='0', multiplicity=1):
    catalog.change(root, 'object', id=identity, name=identity, formula=formula,
                   charge=charge, multiplicity=multiplicity, upgrade_catalog=True)


def candidate_(root, identity='guess-a', data=XYZ, parent=None, object='water-a', **kw):
    return catalog.register_candidate(root, object=object, id=identity, xyz_bytes=data,
                                      source='synthetic.xyz', origin=kw.pop('origin', 'manual'),
                                      parent_attempt=parent, **kw)


def diagnose(root, **kw):
    kw.setdefault('candidate', 'guess-a')
    kw.setdefault('window', ['1-2:0.9:1.1'])
    return g0.diagnose(root, object=kw.pop('object', 'water-a'), **kw)


@pytest.fixture
def normal(water):
    object_(water)
    identity = make_attempt(water, '001-input', geometry=GEOMETRY, charge=0, multiplicity=1)
    candidate_(water, parent=identity)
    return water, identity


def test_clean_and_no_file_writes(normal, capsys):
    root, identity = normal
    before, snapshot = files(root), tree(root)
    report = diagnose(root)
    c = report['candidates'][0]
    assert c['verdict'] == 'clean' and c['flags'] == c['reject_reasons'] == c['unchecked'] == []
    assert all(check['status'] == 'pass' for check in c['integrity'].values())
    assert c['reference']['attempt'] == identity
    assert cli.main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
                     '--window', '1-2:0.9:1.1', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert cli.main(['g0', str(root), '--object', 'water-a', '--all']) == 0
    output = capsys.readouterr().out
    assert g0.NOTICE in output and g0.ORDER_NOTICE in output and '未设窗口' in output
    assert files(root) == before and tree(root) == snapshot


@pytest.mark.parametrize('formula,charge,mult,field', [
    ('H2O2', '0', 1, 'atom_count_and_formula'), ('H2O', '2', 1, 'charge'),
    ('H2O', '0', 3, 'multiplicity'), ('H2O', '0', 2, 'multiplicity'),
    ('H2O', '1', 1, 'charge'), ('H2O', '12', 1, 'charge')])
def test_object_expectations_and_electron_parity(normal, formula, charge, mult, field):
    root, _ = normal
    catalog.change(root, 'object', id='water-a', name='Water', update=True,
                   formula=formula, charge=charge, multiplicity=mult)
    c = diagnose(root)['candidates'][0]
    assert c['verdict'] == 'rejected' and c['integrity'][field]['status'] == 'reject'
    assert all(r['category'] == 'input_integrity' for r in c['reject_reasons'])


def test_element_order_and_same_element_limit(normal):
    root, identity = normal
    for name, data, status in (
            ('different', b'3\nSynthetic\nH 0 0 1\nO 0 0 0\nH 0 1 0\n', 'reject'),
            ('same', b'3\nSynthetic\nO 0 0 0\nH 0 1 0\nH 0 0 1\n', 'pass')):
        candidate_(root, name, data, identity)
        check = diagnose(root, candidate=name)['candidates'][0]['integrity']['atom_order']
        assert check['status'] == status
        assert '同种元素原子互换无法检出' in check['limitation']


def test_two_objects_different_stoichiometry(normal):
    root, _ = normal
    geometry = GEOMETRY + '\nO 8 0 0\nH 8 0 1\nH 8 1 0'
    identity = make_attempt(root, '002-dimer', geometry=geometry, charge=0, multiplicity=1)
    object_(root, 'water-dimer', formula='H4O2')
    candidate_(root, data=('6\nSynthetic dimer\n' + geometry + '\n').encode(),
               parent=identity, object='water-dimer')
    assert diagnose(root)['candidates'][0]['verdict'] == 'clean'
    assert diagnose(root, object='water-dimer')['candidates'][0]['verdict'] == 'clean'


@pytest.mark.parametrize('expectation', ['unset', 'unknown'])
def test_unchecked_is_flag_not_reject(water, expectation):
    object_(water, formula=expectation, charge=expectation, multiplicity=None)
    candidate_(water)
    c = diagnose(water)['candidates'][0]
    assert c['verdict'] == 'flagged' and len(c['unchecked']) == 4
    assert not c['reject_reasons'] and len(c['flags']) == 4


def test_manual_reference_and_missing_spin(normal):
    root, identity = normal
    candidate_(root, 'manual')
    c = diagnose(root, candidate='manual')['candidates'][0]
    assert c['unchecked'] == ['atom_order', 'charge', 'multiplicity']
    assert diagnose(root, candidate='manual', reference_attempt=identity)['candidates'][0]['verdict'] == 'clean'
    absent = make_attempt(root, '002-missing', geometry=GEOMETRY)
    c = diagnose(root, candidate='manual', reference_attempt=absent)['candidates'][0]
    assert c['unchecked'] == ['charge', 'multiplicity'] and c['verdict'] == 'flagged'


@pytest.mark.parametrize('kind', ['qst', 'xtb', 'crest'])
def test_reference_sources(normal, kind):
    root, _ = normal
    science = dict(geometry=GEOMETRY, charge=0, multiplicity=1)
    if kind == 'qst':
        second = dict(science, geometry='H 0 0 1\nH 0 1 0\nO 0 0 0')
        science = dict(qst_mode='QST2', structures=[science, second])
    identity = make_attempt(root, '002-reference', template='gaussian' if kind == 'qst' else kind, **science)
    if kind != 'qst':
        path = root / 'attempts' / identity
        (path / 'inputs').mkdir()
        (path / 'inputs/input.xyz').write_bytes(XYZ)
        manifest = json.loads((path / 'manifest.json').read_text())
        manifest.update(inputs=[dict(name='input.xyz', sha256=sha256(XYZ).hexdigest(), size=len(XYZ))],
                        template_params={'--chrg': '0', '--uhf': '0'}, science={})
        write_json(path / 'manifest.json', manifest)
    assert diagnose(root, reference_attempt=identity)['candidates'][0]['verdict'] == 'clean'
    if kind != 'qst':
        (path / 'inputs/input.xyz').write_bytes(XYZ + b'\n')
        with pytest.raises(ValueError, match='hash/size'):
            diagnose(root, reference_attempt=identity)


@pytest.mark.parametrize('elements,distance,damage,clash', [
    (('H', 'H'), 0.4, True, False), (('H', 'H'), 0.5, False, False),
    (('C', 'C'), 0.7, True, True), (('C', 'C'), 0.76, False, True),
    (('C', 'C'), 1.5, False, False), (('C', 'C'), 2.4, False, True),
    (('C', 'C'), 2.55, False, False)])
def test_fixed_geometry_boundaries(elements, distance, damage, clash):
    frame = geo.Frame(elements, ((0, 0, 0), (distance, 0, 0)))
    report = g0._geometry(frame)
    assert bool(report['damage']) is damage and bool(report['clashes']) is clash
    for pair in report['damage'] + report['clashes']:
        assert pair['atoms'] == [1, 2] and pair['elements'] == list(elements)
        assert pair['distance_angstrom'] == distance


def test_damage_rejects_and_clash_only_flags(water, capsys):
    object_(water, formula='C2')
    for name, distance, verdict in [('damage', 0.7, 'rejected'), ('clash', 2.4, 'flagged')]:
        data = f'2\nSynthetic carbon pair\nC 0 0 0\nC {distance} 0 0\n'.encode()
        candidate_(water, name, data)
        report = diagnose(water, candidate=name, window=[])['candidates'][0]
        assert report['verdict'] == verdict
        assert any('受限松弛' in f['message'] for f in report['flags'])
        assert cli.main(['g0', str(water), '--object', 'water-a', '--candidate', name, '--json']) == (1 if verdict == 'rejected' else 0)
        assert 'error' not in json.loads(capsys.readouterr().out)


def carbon_pair(root, distance=2.2):
    geometry = f'C 0 0 0\nC {distance} 0 0'
    object_(root, formula='C2')
    identity = make_attempt(root, '001-carbon-pair', geometry=geometry, charge=0, multiplicity=1)
    candidate_(root, data=('2\nSynthetic carbon pair\n' + geometry + '\n').encode(), parent=identity)


def test_shared_window_file_keeps_other_channel_coordinates_unapplied(water):
    carbon_pair(water)
    path = water / 'analyses/windows.json'
    config = dict(all=[dict(atoms=[1, 2], min=2.0, max=2.4)])
    write_json(path, config)
    before = diagnose(water, windows=path, window=[])
    config['reaction_coordinates'] = {'approach-a': [
        dict(kind='distance', atoms=[1, 2], role='forming', label='Synthetic forming pair'),
        dict(kind='angle', atoms=[1, 2, 3], role='report')]}
    # A different target channel's atom count must not constrain this candidate.
    write_json(path, config)
    snapshot = files(water)
    after = diagnose(water, windows=path, window=[])
    assert after['candidates'][0]['verdict'] == 'clean'
    assert after['candidates'][0]['windows']['source']['sha256'] == sha256(path.read_bytes()).hexdigest()
    before['candidates'][0]['windows']['source'] = after['candidates'][0]['windows']['source']
    before['candidates'][0]['modes']['coordinate_sources'] = after['candidates'][0]['modes']['coordinate_sources']
    assert before == after and files(water) == snapshot


@pytest.mark.parametrize('source', ['all', 'target_channel', 'command_line'])
@pytest.mark.parametrize('distance,verdict,outside', [(2.0, 'clean', 0), (2.2, 'clean', 0),
                                                    (2.4, 'clean', 0), (1.9, 'flagged', 1),
                                                    (0.4, 'rejected', 1), (0.7, 'rejected', 1)])
def test_declared_reaction_pairs_keep_windows_and_damage(water, source, distance, verdict, outside):
    carbon_pair(water, distance)
    window = dict(atoms=[2, 1], min=2.0, max=2.4, label='Synthetic reaction pair')
    config = {'all': [], 'channels': {}}
    extra = []
    if source == 'all':
        config['all'] = [window]
    elif source == 'command_line':
        extra = ['2-1:2.0:2.4']
    else:
        catalog.change(water, 'channel', object='water-a', id='a', name='A', definition='Synthetic')
        parent = catalog.show(water)[0]['objects'][0]['candidates'][0]['parent']['attempt']
        data = f'2\nSynthetic\nC 0 0 0\nC {distance} 0 0\n'.encode()
        candidate_(water, 'target', data, parent=parent, target_channel='a')
        config['channels']['a'] = [window]
    path = water / 'analyses/windows.json'
    write_json(path, config)
    name = 'target' if source == 'target_channel' else 'guess-a'
    c = diagnose(water, candidate=name, windows=path, window=extra)['candidates'][0]
    assert c['verdict'] == verdict and c['counts']['outside_windows'] == outside
    assert not c['geometry']['clashes'] and c['counts']['ordinary_clashes'] == 0
    assert c['geometry']['reaction_center_pairs'][0]['atoms'] == [1, 2]
    assert c['geometry']['reaction_center_pairs'][0]['elements'] == ['C', 'C']
    assert c['geometry']['reaction_center_pairs'][0]['distance_angstrom'] == distance
    assert c['counts']['reaction_center_pairs'] == 1
    assert not any(f['category'] == 'ordinary_clash' or '松弛' in f['message'] for f in c['flags'])
    assert bool(c['geometry']['damage']) is (verdict == 'rejected')
    if distance == 0.4:
        assert len(c['geometry']['damage'][0]['criteria']) == 2
    if distance == 0.7:
        assert c['geometry']['damage'][0]['criteria'] == ['distance_below_half_covalent_sum']


def test_reaction_pair_exemption_is_pair_specific():
    frame = geo.Frame(('C', 'C', 'C'), ((0, 0, 0), (2.2, 0, 0), (4.4, 0, 0)))
    result = g0._geometry(frame, [(2, 1), (1, 2)])
    assert [c['atoms'] for c in result['reaction_center_pairs']] == [[1, 2]]
    assert [c['atoms'] for c in result['clashes']] == [[2, 3]]
    assert '先核对是否为未声明的反应中心' in result['clashes'][0]['recommendation']


def test_forming_carbon_pair_needs_explicit_window(water, capsys):
    carbon_pair(water, 2.2)
    before = files(water)
    c = diagnose(water, window=[])['candidates'][0]
    assert c['verdict'] == 'flagged' and c['counts']['ordinary_clashes'] == 1
    assert not c['geometry']['reaction_center_pairs']
    assert cli.main(['g0', str(water), '--object', 'water-a', '--all', '--window', '1-2:2.0:2.4']) == 0
    output = capsys.readouterr().out
    assert 'guess-a: clean' in output and 'geometry.reaction_center_pairs:' in output
    assert 'ordinary_clash' not in output and '松弛' not in output
    assert files(water) == before


def test_other_channel_windows_do_not_exempt_candidate_or_mode_only_pairs(water):
    carbon_pair(water)
    catalog.change(water, 'channel', object='water-a', id='other', name='Other', definition='Synthetic')
    catalog.change(water, 'candidate-result', object='water-a', candidate='guess-a', outcome='other_channel',
                   assign='tentative', channel=['other'])
    path = water / 'analyses/windows.json'
    write_json(path, dict(channels={'other': [dict(atoms=[1, 2], min=2.0, max=2.4)]},
                         reaction_coordinates={'other': [dict(kind='distance', atoms=[1, 2], role='forming')]}))
    c = diagnose(water, candidate=None, channel='other', windows=path, window=[])['candidates'][0]
    assert not c['geometry']['reaction_center_pairs']
    assert c['counts']['ordinary_clashes'] == 1
    assert c['verdict'] == 'flagged' and c['windows']['status'] == 'unset'


def test_recorded_and_truncated_reaction_center_pairs(water, capsys):
    carbon_pair(water)
    assert cli.main(['g0', str(water), '--object', 'water-a', '--all', '--window', '1-2:2.0:2.4',
                     '--record', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    c = result['candidates'][0]
    assert result['record']['events'][0]['diagnosis'] == c
    c['geometry']['reaction_center_pairs'] *= 2000
    c['counts']['reaction_center_pairs'] = 2000
    bounded = g0.bounded_diagnosis(c)
    assert bounded['truncated'] and len(catalog.encode(bounded)) <= 65536
    assert bounded['counts']['reaction_center_pairs'] == 2000 and bounded['verdict'] == 'clean'


@pytest.mark.parametrize('bad', [[], {'all': None}, {'channels': []},
                               {'all': [{'atoms': [1, 2], 'min': 3, 'max': 2}]}])
def test_shared_file_still_validates_owned_window_sections(normal, bad):
    root, _ = normal
    path = root / 'analyses/bad-windows.json'
    write_json(path, bad)
    with pytest.raises(ValueError):
        diagnose(root, windows=path)


@pytest.mark.parametrize('key', ['reaction_coordinate', 'channnels', 'future_extension'])
def test_shared_file_rejects_unknown_top_level_keys(normal, key, capsys):
    root, _ = normal
    path = root / 'analyses/bad-windows.json'
    write_json(path, {key: {}})
    snapshot = files(root)
    assert cli.main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(path),
                     '--record', '--json']) == 1
    error = json.loads(capsys.readouterr().out)
    assert 'Unknown windows file fields' in error['error']
    assert 'candidates' not in error and files(root) == snapshot


@pytest.mark.parametrize('distance', [1.5, 3.0])
def test_reaction_center_listing_does_not_depend_on_bond_or_clash_cutoff(distance):
    frame = geo.Frame(('C', 'C'), ((0, 0, 0), (distance, 0, 0)))
    result = g0._geometry(frame, [(1, 2)])
    assert result['reaction_center_pairs'][0]['distance_angstrom'] == distance
    assert not result['clashes']


def test_rdkit_heavy_pair_clash_thresholds():
    from rdkit import Chem
    table = Chem.GetPeriodicTable()
    for elements, expected in [(('C', 'C'), 2.55), (('C', 'O'), 2.4375), (('C', 'N'), 2.475)]:
        radii = [table.GetRvdw(element) for element in elements]
        threshold = g0.VDW_FACTOR * sum(radii)
        print(f"{'-'.join(elements)}: 0.75 * ({radii[0]} + {radii[1]}) = {threshold:.4f} Angstrom")
        assert threshold == pytest.approx(expected)
        frame = geo.Frame(elements, ((0, 0, 0), (2.2, 0, 0)))
        assert g0._geometry(frame)['clashes'][0]['threshold_angstrom'] == threshold
        assert not g0._geometry(frame, [(1, 2)])['clashes']


def test_windows_sources_and_historical_channel_selection(normal):
    root, identity = normal
    for name in ('a', 'b'):
        catalog.change(root, 'channel', object='water-a', id=name, name=name, definition='Synthetic')
    candidate_(root, 'channel-a', parent=identity, target_channel='a')
    catalog.change(root, 'candidate-result', object='water-a', candidate='channel-a', outcome='other_channel',
                   assign='tentative', channel=['b'])
    source = root / 'analyses/windows.json'
    write_json(source, dict(all=[dict(atoms=[1, 2], min=1, max=1)], channels={
        'a': [dict(atoms=[1, 3], min=2, max=3, label='Synthetic forming bond')],
        'b': [dict(atoms=[2, 3], min=10, max=11)]}))
    report = diagnose(root, candidate=None, channel='b', windows='analyses/windows.json', window=['2-3:1:2'])
    assert report['order'] == ['channel-a']
    c = report['candidates'][0]
    assert c['verdict'] == 'flagged' and c['counts']['outside_windows'] == 1
    assert c['windows']['source']['sha256'] == sha256(source.read_bytes()).hexdigest()
    assert [w['source'] for w in c['windows']['used']] == ['all', 'target_channel', 'command_line']
    assert c['windows']['used'][0]['status'] == 'pass'
    assert c['flags'][0]['atoms'] == [1, 3] and c['flags'][0]['label'] == 'Synthetic forming bond'


@pytest.mark.parametrize('kind', ['outside', 'symlink', 'parent-link', 'traversal'])
def test_window_paths_refused(normal, tmp_path, kind):
    root, _ = normal
    source = tmp_path / 'windows.json'
    source.write_text('{}')
    if kind == 'outside':
        value = source
    elif kind == 'symlink':
        value = root / 'analyses/link.json'
        value.symlink_to(source)
    elif kind == 'parent-link':
        (root / 'analyses/link').symlink_to(tmp_path, target_is_directory=True)
        value = root / 'analyses/link/windows.json'
    else:
        value = root / 'analyses/../windows.json'
    before = files(root)
    with pytest.raises(ValueError, match='path|links'):
        diagnose(root, windows=value)
    assert files(root) == before


@pytest.mark.parametrize('window', ['0-2:1:2', '1-1:1:2', '1-2:2:1', '1-2:nan:2',
                                    '1-2:1:inf', '1-2:-1:2', '1-4:1:2'])
def test_invalid_windows_are_errors(normal, window):
    root, _ = normal
    with pytest.raises(ValueError):
        diagnose(root, window=[window])


def labels(root, identity, label='R', geometry='input'):
    relative = f'attempts/{identity}/' + ('manifest.json' if geometry == 'input' else 'final_input.xyz')
    if geometry == 'final':
        (root / relative).write_bytes(XYZ)
    item = dict(attempt=identity, product_configuration='O1:' + label,
                product_centers=[dict(element='O', reference_atom=1, label=label)], catalyst_centers=[],
                geometry_source=dict(path=relative, sha256=sha256((root / relative).read_bytes()).hexdigest(),
                                     json_pointer='/science/geometry' if geometry == 'input' else None))
    # Synthetic format fixture only; water is not claimed to have a stereocenter.
    data = dict(atom_index_base=1, geometry=geometry, attempts=[item])
    path = root / 'analyses/labels.json'
    write_json(path, data)
    return path, data


@pytest.mark.parametrize('label,expected,status', [('R', 'O1:R', 'match'), ('S', 'O1:R', 'other_channel'),
                                                  ('unknown', 'O1:R', 'pending'), ('needs_review', 'O1:R', 'pending')])
def test_stereo_matching_is_flag_only(normal, label, expected, status):
    root, identity = normal
    path, _ = labels(root, identity, label)
    c = diagnose(root, stereo_json=path, stereo_attempt=identity, expected_label=expected)['candidates'][0]
    assert c['stereo']['status'] == status and not c['reject_reasons']
    assert c['verdict'] == ('clean' if status == 'match' else 'flagged')
    assert catalog.show(root)[0]['objects'][0]['candidates'][0]['results'] == []


@pytest.mark.parametrize('kind', ['missing-centers', 'bad-label', 'duplicate-attempt', 'wrong-configuration',
                                 'geometry-mismatch', 'stale-hash', 'wrong-source', 'final-mismatch'])
def test_stereo_errors_produce_no_verdict_or_record(normal, kind, capsys):
    root, identity = normal
    path, data = labels(root, identity, geometry='final' if kind == 'final-mismatch' else 'input')
    item = data['attempts'][0]
    if kind == 'missing-centers':
        del item['product_centers']
    elif kind == 'bad-label':
        item['product_centers'][0]['label'] = 'r'
    elif kind == 'duplicate-attempt':
        data['attempts'].append(item.copy())
    elif kind == 'wrong-configuration':
        item['product_configuration'] = 'O1:S'
    elif kind == 'geometry-mismatch':
        manifest = root / 'attempts' / identity / 'manifest.json'
        m = json.loads(manifest.read_text())
        m['science']['geometry'] = GEOMETRY.replace('H 0 0 1', 'H 0 0 2')
        write_json(manifest, m)
    elif kind == 'stale-hash':
        item['geometry_source']['sha256'] = '0' * 64
    elif kind == 'wrong-source':
        item['geometry_source']['json_pointer'] = '/science/other'
    else:
        final = root / item['geometry_source']['path']
        final.write_bytes(XYZ.replace(b'H 0 0 1', b'H 0 0 2'))
        item['geometry_source']['sha256'] = sha256(final.read_bytes()).hexdigest()
    write_json(path, data)
    before = files(root)
    assert cli.main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
                     '--stereo-json', str(path), '--stereo-attempt', identity, '--expected-label', 'O1:R',
                     '--record', '--json']) != 0
    report = json.loads(capsys.readouterr().out)
    assert 'error' in report and 'candidates' not in report
    assert files(root) == before


def test_stereo_final_and_tolerance(normal):
    root, identity = normal
    path, _ = labels(root, identity, geometry='final')
    assert diagnose(root, stereo_json=path, stereo_attempt=identity, expected_label='O1:R')['candidates'][0]['stereo']['status'] == 'match'
    near = geo.Frame(('O',), ((0.0001, 0, 0),))
    zero = geo.Frame(('O',), ((0, 0, 0),))
    far = geo.Frame(('O',), ((0.000101, 0, 0),))
    assert g0._same_geometry(near, zero) and not g0._same_geometry(far, zero)


@pytest.mark.parametrize('mode', ['input', 'final', 'qst3'])
def test_actual_skill_labels_are_consumed_without_relabelling(water, monkeypatch, mode):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    script = Path(__file__).parents[2] / 'skills-next/auto-g16-structures/scripts/ts_stereo_label.py'
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location('g0_label_fixture', script)
    label = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(label)
    mol = Chem.AddHs(Chem.MolFromSmiles('F[C@H](Cl)Br'))
    assert AllChem.EmbedMolecule(mol, randomSeed=42) == 0
    Chem.MolToMolFile(mol, str(water / 'product.mol'))
    (water / 'map.csv').write_text('reference_atom,ts_atom\n' + ''.join(
        f'{i},{i}\n' for i in range(1, mol.GetNumAtoms() + 1)))
    xyz = Chem.MolToXYZBlock(mol).encode()
    geometry = '\n'.join(xyz.decode().splitlines()[2:])
    science = dict(geometry=geometry, charge=0, multiplicity=1)
    if mode == 'qst3':
        # QST reference order uses first group; labels use the third TS guess.
        first = dict(science, geometry='\n'.join(
            f'{row.split()[0]} {float(row.split()[1]) + 3} {row.split()[2]} {row.split()[3]}'
            for row in geometry.splitlines()))
        science = dict(qst_mode='QST3', structures=[first, first, science])
    identity = make_attempt(water, '001-halogenated-methane', **science)
    (water / 'attempts' / identity / 'final_input.xyz').write_bytes(xyz)
    object_(water, formula=v2.xyz(xyz)[1])
    candidate_(water, data=xyz, parent=identity)
    generated = label.run(water, 'actual-labels', identity, 'product.mol', 'map.csv',
                          geometry='input' if mode == 'qst3' else mode)
    expected = generated['attempts'][0]['product_configuration']
    before = files(water)
    report = diagnose(water, window=[], stereo_json=water / 'analyses/ts-labels/actual-labels/labels.json',
                      stereo_attempt=identity, expected_label=expected)
    assert report['candidates'][0]['stereo']['status'] == 'match'
    assert files(water) == before


@pytest.mark.parametrize('kind', ['unknown-catalyst', 'empty-product', 'ambiguous-centers'])
def test_unresolved_stereo_is_pending(normal, kind):
    root, identity = normal
    path, data = labels(root, identity)
    item = data['attempts'][0]
    if kind == 'unknown-catalyst':
        item['catalyst_centers'] = [dict(element='O', reference_atom=1, label='unknown')]
    elif kind == 'empty-product':
        item['product_centers'] = []
    else:
        item['product_centers'] *= 2
    item['product_configuration'] = ';'.join(
        f"{c['element']}{c['reference_atom']}:{c['label']}" for c in item['product_centers'])
    write_json(path, data)
    c = diagnose(root, stereo_json=path, stereo_attempt=identity, expected_label='O1:R')['candidates'][0]
    assert c['stereo']['status'] == 'pending' and c['verdict'] == 'flagged'


def test_archive_corruption_is_error_not_rejection(normal, capsys):
    root, _ = normal
    candidate = catalog.show(root)[0]['objects'][0]['candidates'][0]
    path = root / candidate['file']
    path.chmod(0o600)
    path.write_bytes(XYZ + b'\n')
    before = files(root)
    assert cli.main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a', '--record', '--json']) != 0
    result = json.loads(capsys.readouterr().out)
    assert 'hash mismatch' in result['error'] and 'verdict' not in result
    assert files(root) == before


def test_batch_sorting(normal):
    root, identity = normal
    candidate_(root, 'many-flags')
    candidate_(root, 'rejected', XYZ.replace(b'H 0 0 1', b'H 0 0 0.4'), identity)
    candidate_(root, 'one-flag', XYZ.replace(b'H 0 0 1', b'H 0 0 2'), identity)
    candidate_(root, 'second-clean', parent=identity)
    result = diagnose(root, candidate=None, all_candidates=True)
    assert result['order'] == ['rejected', 'one-flag', 'many-flags', 'guess-a', 'second-clean']
    assert result['counts'] == dict(rejected=1, flagged=2, clean=2)


def test_record_single_batch_dry_run_one_lock(normal, capsys, monkeypatch):
    root, identity = normal
    candidate_(root, 'second', parent=identity)
    argv = ['g0', str(root), '--object', 'water-a', '--all', '--window', '1-2:0.9:1.1', '--record', '--json']
    before = files(root)
    assert cli.main(argv + ['--dry-run']) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report['record']['events']) == 2 and files(root) == before
    lock = catalog.catalog_lock
    writes = []

    @contextmanager
    def counted(root, *, write=False):
        if write:
            writes.append(True)
        with lock(root, write=write):
            yield

    monkeypatch.setattr(catalog, 'catalog_lock', counted)
    assert cli.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert writes == [True]
    for event in report['record']['events']:
        assert event['outcome'] == 'diagnosed' and event['attempt'] is None
        assert event['assignment'] == dict(status='none', channels=[])
        assert event['diagnosis']['verdict'] == 'clean'
    assert cli.main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a', '--record', '--json']) == 0
    capsys.readouterr()
    assert cli.main(['catalog', 'ledger', str(root), '--object', 'water-a', '--json']) == 0
    ledger = json.loads(capsys.readouterr().out)
    assert [len(c['results']) for c in ledger['unassigned']] == [2, 1]
    evidence = {k: v for k, v in before.items() if not k.startswith('catalog/')}
    assert {k: files(root)[k] for k in evidence} == evidence


def test_batch_invalid_event_and_stale_snapshot_do_not_write(normal):
    root, _ = normal
    snapshot = diagnose(root)
    diagnosis = snapshot['candidates'][0]
    rows = [dict(object='water-a', candidate='guess-a', diagnosis=diagnosis),
            dict(object='water-a', candidate='missing', diagnosis=diagnosis)]
    before = files(root)
    with pytest.raises(ValueError, match='Unknown candidate'):
        catalog.register_candidate_results(root, rows, journal_sha256=snapshot['journal_sha256'])
    assert files(root) == before
    catalog.change(root, 'object', id='water-a', name='Changed expectation', update=True, charge='2')
    before = files(root)
    with pytest.raises(ValueError, match='changed since diagnosis'):
        catalog.register_candidate_results(root, rows[:1], journal_sha256=snapshot['journal_sha256'])
    assert files(root) == before


def test_v1_empty_report_survives_record_refusal(water, capsys):
    catalog.change(water, 'object', id='water-a', name='Legacy object')
    before = files(water)
    argv = ['g0', str(water), '--object', 'water-a', '--all', '--record', '--json']
    assert cli.main(argv) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['candidates'] == [] and '--upgrade-catalog' in report['record']['error']
    assert files(water) == before
    for option in ('--dry-run', '--upgrade-catalog'):
        assert cli.main(argv + [option]) == 0
        assert json.loads(capsys.readouterr().out)['record']['events'] == []
        assert files(water) == before


def test_truncation_retains_verdict_counts_and_size(normal):
    report = diagnose(normal[0])['candidates'][0]
    report.update(verdict='flagged', flags=[dict(category='distance_window', message='长标签' * 100)] * 1000)
    report['counts']['flags'] = 1000
    bounded = g0.bounded_diagnosis(report)
    assert len(catalog.encode(bounded)) <= 65536 and bounded['truncated']
    assert bounded['verdict'] == 'flagged' and bounded['counts']['flags'] == 1000
    assert len(report['flags']) == 1000
    report['stereo']['expected_label'] = '长' * 40000
    bounded = g0.bounded_diagnosis(report)
    assert len(catalog.encode(bounded)) <= 65536 and bounded['counts'] == report['counts']


@pytest.mark.parametrize('options', [dict(candidate=None, all_candidates=True, reference_attempt='ref'),
                                    dict(stereo_json='labels.json'),
                                    dict(candidate=None, all_candidates=True, stereo_json='labels.json',
                                         stereo_attempt='ref', expected_label='C1:R')])
def test_single_candidate_options_rejected_for_batch(normal, options):
    with pytest.raises(ValueError):
        diagnose(normal[0], **options)


@pytest.mark.parametrize('option', ['--dry-run', '--upgrade-catalog'])
def test_record_options_require_record(normal, option, capsys):
    root, _ = normal
    assert cli.main(['g0', str(root), '--object', 'water-a', '--all', option, '--json']) != 0
    assert 'require --record' in json.loads(capsys.readouterr().out)['error']


MODE_XYZ = b'3\nSynthetic transfer\nO 0 0 0\nH 1 0 0\nO 2.6 0 0\n'
MODE_SPECS = [dict(kind='distance', atoms=[1, 2], role='breaking'),
              dict(kind='distance', atoms=[2, 3], role='forming')]


def frequency_attempt(root, suffix='002-freq', *, positive=False, stationary=False, weak=False):
    identity = make_attempt(root, suffix, route='# HF/3-21G Freq',
                            geometry='O 0 0 0\nH 1 0 0\nO 2.6 0 0', charge=1, multiplicity=1)
    path = root / 'attempts' / identity
    (path / 'outputs').mkdir()
    text = (Path(__file__).parent / 'fixtures/g0_modes_synthetic.log').read_text()
    if positive:
        text = text.replace('-300.0000', '300.0000').replace('-100.0000', '100.0000')
    if weak:
        text = text.replace('1.00   0.00   0.00   0.00   0.00   0.00\n',
                            '0.60   0.80   0.00   0.00   0.00   0.00\n', 1)
    if stationary:
        text = (' Entering Gaussian System\n -----\n # opt\n -----\n'
                ' Optimization completed.\n Normal termination of Gaussian\n' +
                text.replace(' Entering Gaussian System', ' --Link1--'))
    log = path / 'outputs/job.log'
    log.write_text(text)
    facts, _ = _parse_outputs.parse_gaussian(log)
    write_json(path / 'facts.json', dict(facts, schema='ag-facts/1'))
    return identity


def declare_frequency(root, *pairs):
    """Synthetic test declarations are explicit, independently source-bound entries."""
    path = root / 'analyses/atom-mapping.json'
    entries = json.loads(path.read_bytes())['mappings'] if path.exists() else []
    candidates = {c['id']: c for c in catalog.show(root)[0]['objects'][0]['candidates']}
    for name, identity in pairs:
        frequency = g0_modes.read_frequency_attempt(root, identity)
        candidate = candidates[name]
        entries = [e for e in entries if e['candidate'] != name]
        entries.append(dict(object='water-a', candidate=name, candidate_sha256=candidate['sha256'],
                            target=g0_mapping.frequency_target(frequency),
                            candidate_to_target=list(range(1, candidate['n_atoms'] + 1))))
    write_json(path, dict(mappings=entries))
    return path


def mapped_diagnose(root, **kw):
    kw.setdefault('atom_mapping', root / 'analyses/atom-mapping.json')
    return diagnose(root, **kw)


def mapped_main(argv):
    return cli.main([*argv, '--atom-mapping', str(Path(argv[1]) / 'analyses/atom-mapping.json')])


@pytest.fixture
def mode_case(water):
    object_(water, formula='HO2', charge='1')
    catalog.change(water, 'channel', object='water-a', id='transfer', name='Transfer', definition='Synthetic')
    identity = frequency_attempt(water)
    candidate_(water, data=MODE_XYZ, parent=identity, target_channel='transfer')
    path = water / 'analyses/windows.json'
    write_json(path, dict(all=[dict(atoms=[1, 2], min=0.9, max=1.1)],
                         reaction_coordinates={'transfer': MODE_SPECS}))
    declare_frequency(water, ('guess-a', identity))
    return water, identity, path


def link_result(root, candidate, identity):
    catalog.change(root, 'candidate-result', object='water-a', candidate=candidate,
                   outcome='diagnosed', attempt=identity, assign='none')


def test_modes_cli_json_text_and_read_only(mode_case, capsys):
    root, identity, path = mode_case
    argv = ['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
            '--modes-attempt', identity, '--windows', str(path)]
    before = files(root)
    assert mapped_main(argv + ['--json']) == 0
    c = json.loads(capsys.readouterr().out)['candidates'][0]
    modes = c['modes']
    assert modes['best_mode'] == 2 and modes['available'] and c['verdict'] == 'flagged'
    assert c['reject_reasons'] == [] and c['counts']['g0_flags'] == 0
    assert c['counts']['mode_flags'] == 3
    assert {f['category'] for f in c['flags']} == {
        'mode:multiple_imaginary_modes', 'mode:most_negative_not_best', 'mode:non_stationary_frequencies'}
    assert modes['coordinate_sources'][0]['sha256'] == c['windows']['source']['sha256']
    assert len(modes['geometry_sha256']) == 64 and modes['attempt'] == identity
    assert modes['aligned_rmsd_angstrom'] == pytest.approx(0)
    assert mapped_main(argv) == 0
    text = capsys.readouterr().out
    assert '*2 | -100.000000' in text and '0.816497' in text and 'δc=+1.000000' in text
    assert '≈0，符号不定' in text and '实频参考' in text and '结果是诊断，不是 TS 验收' in text
    assert files(root) == before


def test_window_file_read_and_parsed_once_even_if_changed(mode_case, monkeypatch):
    root, identity, path = mode_case
    candidate_(root, 'second', MODE_XYZ, parent=identity, target_channel='transfer')
    for name in ('guess-a', 'second'):
        link_result(root, name, identity)
    declare_frequency(root, ('second', identity))
    original = path.read_bytes()
    read, loads = v2.read_bytes, json.loads
    reads, parses = [], []
    def capture_read(value, limit):
        data = read(value, limit)
        if Path(value) == path:
            reads.append(value)
            path.write_text('{}')  # later read would lose the coordinates
        return data
    def capture_parse(value, *args, **kwargs):
        if value == original:
            parses.append(value)
        return loads(value, *args, **kwargs)
    monkeypatch.setattr(v2, 'read_bytes', capture_read)
    monkeypatch.setattr(json, 'loads', capture_parse)
    result = mapped_diagnose(root, candidate=None, all_candidates=True, windows=path)
    assert len(reads) == len(parses) == 1
    for c in result['candidates']:
        assert c['modes']['available']
        assert c['modes']['coordinate_sources'][0]['sha256'] == sha256(original).hexdigest()
        assert c['windows']['source']['sha256'] == sha256(original).hexdigest()
        assert c['modes']['coordinates_spec'][0]['role'] == 'breaking'


@pytest.mark.parametrize('distance', [2.2, 0.4, 0.7])
@pytest.mark.parametrize('source', ['channel', 'cli'])
def test_mode_distances_exempt_clashes_but_not_damage(water, distance, source):
    carbon_pair(water, distance)
    extra, path, name = ['distance:2-1:forming'], None, 'guess-a'
    if source == 'channel':
        catalog.change(water, 'channel', object='water-a', id='a', name='A', definition='Synthetic')
        parent = catalog.show(water)[0]['objects'][0]['candidates'][0]['parent']['attempt']
        candidate_(water, 'target', f'2\nSynthetic\nC 0 0 0\nC {distance} 0 0\n'.encode(),
                   parent=parent, target_channel='a')
        path = water / 'analyses/modes.json'
        write_json(path, {'reaction_coordinates': {'a': [dict(kind='distance', atoms=[2, 1], role='forming')]}})
        extra, name = [], 'target'
    c = diagnose(water, candidate=name, windows=path, window=[], reaction_coordinate=extra)['candidates'][0]
    assert c['geometry']['clashes'] == []
    assert c['geometry']['reaction_center_pairs'][0]['atoms'] == [1, 2]
    assert c['counts']['reaction_center_pairs'] == 1
    assert c['verdict'] == ('flagged' if distance == 2.2 else 'rejected')
    assert bool(c['geometry']['damage']) is (distance < 1)
    assert not any(f['category'] == 'ordinary_clash' for f in c['flags'])


def test_mode_coordinates_validate_channel_and_atom_indices(normal):
    root, _ = normal
    for key in ('../escape', 'UPPER', 'bad id'):
        path = root / 'analyses/invalid.json'
        write_json(path, {'reaction_coordinates': {key: []}})
        with pytest.raises(ValueError, match='IDs'):
            diagnose(root, windows=path)
    with pytest.raises(ValueError, match='in-range'):
        diagnose(root, reaction_coordinate=['distance:1-4:forming'])


def test_batch_uses_latest_nonempty_attempt_and_missing_is_not_flag(mode_case):
    root, identity, path = mode_case
    link_result(root, 'guess-a', identity)
    for name in ('no-result', 'only-null', 'latest-null', 'not-fetched', 'no-freq', 'non-gaussian'):
        candidate_(root, name, MODE_XYZ, parent=identity, target_channel='transfer')
    link_result(root, 'only-null', None)
    link_result(root, 'latest-null', identity)
    newer = frequency_attempt(root, '006-newer', positive=True)
    link_result(root, 'latest-null', newer)
    link_result(root, 'latest-null', None)
    link_result(root, 'latest-null', None)
    pending = make_attempt(root, '003-pending', status='prepared')
    link_result(root, 'not-fetched', identity)
    link_result(root, 'not-fetched', pending)
    link_result(root, 'not-fetched', None)
    sp = frequency_attempt(root, '004-sp')
    log = root / 'attempts' / sp / 'outputs/job.log'
    log.write_text(log.read_text().replace('HF/3-21G Freq', 'HF/3-21G SP'))
    link_result(root, 'no-freq', identity)
    link_result(root, 'no-freq', sp)
    link_result(root, 'no-freq', None)
    other = make_attempt(root, '005-xtb', template='xtb')
    link_result(root, 'non-gaussian', identity)
    link_result(root, 'non-gaussian', other)
    link_result(root, 'non-gaussian', None)
    declare_frequency(root, ('latest-null', newer))
    result = mapped_diagnose(root, candidate=None, all_candidates=True, windows=path)
    by_id = {c['candidate']: c for c in result['candidates']}
    assert by_id['guess-a']['modes']['available']
    for name in ('no-result', 'only-null', 'not-fetched', 'no-freq', 'non-gaussian'):
        assert not by_id[name]['modes']['available']
        assert by_id[name]['modes']['reason'].startswith('无模式数据')
        assert by_id[name]['verdict'] == 'clean'
    assert by_id['only-null']['modes']['attempt'] is None
    assert by_id['latest-null']['modes']['available']
    assert by_id['latest-null']['modes']['attempt'] == newer
    assert by_id['latest-null']['modes']['best_mode'] is None
    for name, expected in [('not-fetched', pending), ('no-freq', sp), ('non-gaussian', other)]:
        assert by_id[name]['modes']['attempt'] == expected
    with pytest.raises(ValueError, match='single --candidate'):
        mapped_diagnose(root, candidate=None, all_candidates=True, modes_attempt=identity)


@pytest.mark.parametrize('selection', [['--all'], ['--channel', 'transfer']])
def test_batch_modes_survive_recorded_diagnosis(mode_case, capsys, selection):
    root, identity, path = mode_case
    link_result(root, 'guess-a', identity)
    argv = ['g0', str(root), '--object', 'water-a', *selection, '--windows', str(path), '--json']
    attempt_files = files(root / 'attempts')
    assert mapped_main(argv + ['--record']) == 0
    recorded = json.loads(capsys.readouterr().out)['candidates'][0]['modes']
    _, events, _ = catalog.read_journal(root)
    assert events[-1]['outcome'] == 'diagnosed' and events[-1]['attempt'] is None
    before = files(root)
    assert mapped_main(argv) == 0
    modes = json.loads(capsys.readouterr().out)['candidates'][0]['modes']
    assert modes['available'] and modes['attempt'] == identity and modes['best_mode'] == 2
    assert modes == recorded
    assert files(root) == before and files(root / 'attempts') == attempt_files


def test_batch_bad_mode_evidence_does_not_write_partial_records(mode_case, capsys):
    root, identity, path = mode_case
    link_result(root, 'guess-a', identity)
    broken = frequency_attempt(root, '003-bad-frame')
    log = root / 'attempts' / broken / 'outputs/job.log'
    log.write_text(log.read_text().replace('Standard orientation', 'Input orientation'))
    candidate_(root, 'broken', MODE_XYZ, parent=identity, target_channel='transfer')
    link_result(root, 'broken', broken)
    before = files(root)
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(path),
                     '--record', '--json']) == 1
    assert 'orientation' in json.loads(capsys.readouterr().out)['error']
    assert files(root) == before


@pytest.fixture
def mode_batch(mode_case):
    root, identity, windows = mode_case
    identities = [identity]
    for index, name in enumerate(('middle', 'last'), 3):
        frequency = frequency_attempt(root, f'{index:03d}-freq')
        candidate_(root, name, MODE_XYZ, parent=frequency, target_channel='transfer')
        identities.append(frequency)
    names = ['guess-a', 'middle', 'last']
    for name, frequency in zip(names, identities):
        link_result(root, name, frequency)
    declare_frequency(root, *zip(names, identities))
    return root, windows, names, identities


def ambiguous_log(root, identity):
    path = root / 'attempts' / identity / 'outputs/job.log'
    path.write_bytes(path.read_bytes() + b' unexplained synthetic tail\n')
    return path


@pytest.mark.parametrize('failed', [(0,), (1,), (2,), (0, 1, 2)])
@pytest.mark.parametrize('selection', [['--all'], ['--channel', 'transfer']])
def test_batch_frequency_ambiguity_preserves_complete_successes(mode_batch, capsys, failed, selection):
    root, windows, names, identities = mode_batch
    baseline = mapped_diagnose(root, candidate=None, all_candidates=True, windows=windows)
    sources = {i: ambiguous_log(root, identities[i]) for i in failed}
    before, snapshot = files(root), tree(root)
    argv = ['g0', str(root), '--object', 'water-a', *selection, '--windows', str(windows),
            '--window', '1-2:0.9:1.1']
    assert mapped_main(argv + ['--json']) == 2
    report = json.loads(capsys.readouterr().out)
    expected = [c for c in baseline['candidates'] if c['candidate'] not in [names[i] for i in failed]]
    assert report['candidates'] == expected
    assert report['order'] == [c['candidate'] for c in expected]
    assert report['counts'] == dict(rejected=0, flagged=len(expected), clean=0,
                                    errors=len(failed), selected=len(names))
    assert report['counts']['selected'] == len(report['order']) + len(report['errors'])
    assert report['incomplete_notice'] == g0.INCOMPLETE_NOTICE
    assert report['errors'] == [dict(
        candidate=names[i], object='water-a', attempt=identities[i], stage='frequency_section',
        category='ambiguous_frequency_sections', reason=report['errors'][n]['reason'],
        source=dict(log=sources[i].relative_to(root).as_posix(),
                    log_sha256=sha256(sources[i].read_bytes()).hexdigest())) for n, i in enumerate(failed)]
    assert all('Ambiguous Gaussian job sections' in error['reason'] for error in report['errors'])
    assert mapped_main(argv) == 2
    output = capsys.readouterr().out
    assert g0.INCOMPLETE_NOTICE in output
    assert all(f"{c['candidate']}: {c['verdict']}" in output for c in expected)
    assert output.count('error: ') == len(failed)
    assert all(f'"candidate": "{names[i]}"' in output for i in failed)
    assert files(root) == before and tree(root) == snapshot


@pytest.mark.parametrize('options', [[], ['--dry-run'], ['--upgrade-catalog']])
def test_incomplete_batch_record_never_enters_catalog_writer(mode_batch, capsys, monkeypatch, options):
    root, windows, _, identities = mode_batch
    ambiguous_log(root, identities[1])
    before, snapshot = files(root), tree(root)
    monkeypatch.setattr(catalog, 'register_candidate_results',
                        lambda *a, **kw: pytest.fail('incomplete batch entered catalog writer'))
    for output in (['--json'], []):
        assert mapped_main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(windows),
                         '--record', *options, *output]) == 2
        captured = capsys.readouterr()
        if output:
            report = json.loads(captured.out)
            assert len(report['candidates']) == 2 and len(report['errors']) == 1
            assert report['record'] == dict(error=g0.UNRECORDED_NOTICE)
        else:
            assert g0.UNRECORDED_NOTICE in captured.out and g0.UNRECORDED_NOTICE in captured.err
        assert files(root) == before and tree(root) == snapshot


def test_ambiguity_without_coordinates_stays_unrequested_and_single_stays_fatal(mode_batch, capsys):
    root, windows, names, identities = mode_batch
    ambiguous_log(root, identities[1])
    before = files(root)
    argv = ['g0', str(root), '--object', 'water-a']
    assert cli.main(argv + ['--all', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report['candidates']) == 3 and 'errors' not in report
    assert all(c['modes']['reason'] == '未声明反应坐标' for c in report['candidates'])
    assert mapped_main(argv + ['--candidate', names[1], '--modes-attempt', identities[1],
                            '--windows', str(windows), '--record', '--json']) == 1
    error = json.loads(capsys.readouterr().out)
    assert 'Ambiguous Gaussian job sections' in error['error'] and 'candidates' not in error
    assert files(root) == before


def test_ambiguity_is_separate_from_missing_modes_and_rejected(mode_batch, capsys):
    root, windows, names, identities = mode_batch
    mapping = root / 'analyses/atom-mapping.json'
    config = json.loads(mapping.read_bytes())
    config['mappings'] = [e for e in config['mappings'] if e['candidate'] != names[2]]
    write_json(mapping, config)
    ambiguous_log(root, identities[1])
    log = root / 'attempts' / identities[2] / 'outputs/job.log'
    log.write_bytes(log.read_bytes().replace(b'HF/3-21G Freq', b'HF/3-21G SP'))
    candidate_(root, 'damaged', MODE_XYZ.replace(b'H 1 0 0', b'H 0.3 0 0'),
               parent=identities[0], target_channel='transfer')
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(windows), '--json']) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['counts'] == dict(rejected=1, flagged=1, clean=1, errors=1, selected=4)
    assert report['order'] == ['damaged', names[0], names[2]]
    assert report['candidates'][-1]['modes']['reason'].startswith('无模式数据')


def test_empty_batch_has_no_error_or_partial_record(mode_case, capsys):
    root, _, windows = mode_case
    catalog.change(root, 'channel', object='water-a', id='empty', name='Empty', definition='Synthetic')
    before = files(root)
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--channel', 'empty',
                     '--windows', str(windows), '--record', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['candidates'] == report['order'] == report['record']['events'] == []
    assert report['counts'] == dict(rejected=0, flagged=0, clean=0) and 'errors' not in report
    assert files(root) == before


@pytest.mark.parametrize('fault,match', [
    ('hash', 'hash mismatch'), ('journal', 'journal damaged'), ('symlink', 'Symbolic'),
    ('reference', 'invalid manifest'), ('window', 'Window atom index'), ('abnormal', 'terminate normally'),
    ('vectors', 'vectors'), ('facts', 'facts not readable')])
def test_fatal_evidence_after_ambiguity_still_aborts_entire_batch(mode_batch, capsys, fault, match):
    root, windows, _, identities = mode_batch
    ambiguous_log(root, identities[0])
    path = root / 'attempts' / identities[-1]
    log = path / 'outputs/job.log'
    if fault == 'hash':
        candidate = catalog.show(root)[0]['objects'][0]['candidates'][-1]
        archive = root / candidate['file']
        archive.chmod(0o600)
        archive.write_bytes(archive.read_bytes() + b'\n')
    elif fault == 'journal':
        journal = root / 'catalog/journal.jsonl'
        journal.write_bytes(journal.read_bytes() + b'{')
    elif fault == 'symlink':
        log.unlink()
        log.symlink_to(root / 'attempts' / identities[1] / 'outputs/job.log')
    elif fault == 'reference':
        manifest = path / 'manifest.json'
        data = json.loads(manifest.read_text())
        data['attempt_id'] = 'wrong-identity'
        write_json(manifest, data)
    elif fault == 'window':
        write_json(windows, dict(all=[dict(atoms=[1, 4], min=0, max=2)]))
    elif fault == 'abnormal':
        log.write_text(log.read_text().replace('Normal termination of Gaussian', 'Error termination of Gaussian'))
    elif fault == 'vectors':
        log.write_text(log.read_text().replace('     3   8    ', '     3   1    '))
    else:
        write_json(path / 'facts.json', [])
    before = files(root)
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(windows),
                     '--record', '--json']) == 1
    report = json.loads(capsys.readouterr().out)
    assert match in report['error'] and 'candidates' not in report and 'errors' not in report
    assert files(root) == before


def test_no_imaginary_modes_and_missing_declaration(mode_case):
    root, identity, path = mode_case
    positive = frequency_attempt(root, '003-positive', positive=True)
    declare_frequency(root, ('guess-a', positive))
    c = mapped_diagnose(root, windows=path, modes_attempt=positive)['candidates'][0]
    assert c['verdict'] == 'flagged' and not c['reject_reasons']
    assert 'mode:no_imaginary_mode' in [f['category'] for f in c['flags']]
    assert len(c['modes']['modes']) == 3
    no_spec = diagnose(root, modes_attempt=identity)['candidates'][0]['modes']
    assert not no_spec['available'] and no_spec['reason'] == '未声明反应坐标'


@pytest.mark.parametrize('batch', [False, True])
def test_modes_record_and_catalog_ledger(mode_case, capsys, batch):
    root, identity, path = mode_case
    link_result(root, 'guess-a', identity)
    if batch:
        candidate_(root, 'second', MODE_XYZ, parent=identity, target_channel='transfer')
        link_result(root, 'second', identity)
        declare_frequency(root, ('second', identity))
    selection = ['--all'] if batch else ['--candidate', 'guess-a', '--modes-attempt', identity]
    argv = ['g0', str(root), '--object', 'water-a', *selection, '--windows', str(path), '--record', '--json']
    before = files(root)
    assert mapped_main(argv + ['--dry-run']) == 0
    assert json.loads(capsys.readouterr().out)['record']['dry_run']
    assert files(root) == before
    assert mapped_main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    _, events, _ = catalog.read_journal(root)
    count = 2 if batch else 1
    for event, row in zip(events[-count:], report['candidates']):
        assert event['outcome'] == 'diagnosed' and event['attempt'] is None
        assert event['diagnosis']['modes'] == row['modes']
        assert len(catalog.encode(event['diagnosis'])) <= 65536
    assert cli.main(['catalog', 'ledger', str(root), '--object', 'water-a', '--json']) == 0
    assert 'diagnosed' in capsys.readouterr().out


def test_mode_sorting_end_to_end(mode_case):
    root, identity, path = mode_case
    weak = frequency_attempt(root, '003-weak', weak=True)
    positive = frequency_attempt(root, '004-positive', positive=True)
    stationary = frequency_attempt(root, '005-stationary', stationary=True)
    for name, frequency in [('guess-a', weak), ('strong', identity), ('real-only', positive),
                            ('missing', None), ('less-mode-flags', stationary), ('tie', identity)]:
        if name != 'guess-a':
            candidate_(root, name, MODE_XYZ, parent=identity, target_channel='transfer')
        link_result(root, name, frequency)
    declare_frequency(root, ('guess-a', weak), ('strong', identity), ('real-only', positive),
                      ('less-mode-flags', stationary), ('tie', identity))
    # Same group: a deliberately out-of-window pair flags all six candidates.
    result = mapped_diagnose(root, candidate=None, all_candidates=True, windows=path, window=['1-2:2:3'])
    assert result['order'] == ['strong', 'less-mode-flags', 'tie', 'guess-a', 'real-only', 'missing']
    assert all(c['verdict'] == 'flagged' for c in result['candidates'])
    assert result['candidates'][0]['counts']['mode_flags'] > result['candidates'][1]['counts']['mode_flags']
    # Only the original T137 flag count breaks an overlap tie, not mode flags.
    sample = deepcopy(result['candidates'][0])
    higher_flags = deepcopy(sample)
    higher_flags['counts']['g0_flags'] += 1
    assert g0._mode_order(sample) < g0._mode_order(higher_flags)


def test_bounded_modes_drop_references_before_coordinates_and_keep_all_imaginary(mode_case):
    root, identity, path = mode_case
    report = mapped_diagnose(root, windows=path, modes_attempt=identity)['candidates'][0]
    for mode in report['modes']['modes']:
        if not mode['imaginary']:
            mode['delta'][0]['label'] = '参考' * 40000
    bounded = g0.bounded_diagnosis(report)
    assert bounded['truncated'] and bounded['modes']['reference_modes_removed'] == 3
    assert all(m['imaginary'] for m in bounded['modes']['modes'])
    assert all(m['delta'] for m in bounded['modes']['modes'])  # no need to trim imaginary details yet
    for mode in report['modes']['modes']:
        mode['delta'][0]['label'] = '坐标' * 40000
    bounded = g0.bounded_diagnosis(report)
    imaginary = [m for m in report['modes']['modes'] if m['imaginary']]
    for original, saved in zip(imaginary, bounded['modes']['modes'], strict=True):
        assert saved['delta'] == [] and saved['delta_count'] == 2
        for key in ('index', 'frequency_cm1', 'consistent_count', 'signed_count', 'overlap'):
            assert saved[key] == original[key]
    assert bounded['modes']['coordinates_spec_count'] == 2
    assert len(catalog.encode(bounded)) <= 65536
    # Even the final scalar fallback must retain mode summaries.
    report['stereo']['expected_label'] = '长' * 40000
    bounded = g0.bounded_diagnosis(report)
    assert len(bounded['modes']['modes']) == len(imaginary)
    assert bounded['counts'] == report['counts'] and len(catalog.encode(bounded)) <= 65536
    assert len(report['modes']['modes']) == 5  # input/stdout report untouched


def test_modes_never_change_rejected_group_to_flagged(mode_case):
    root, identity, path = mode_case
    damaged = MODE_XYZ.replace(b'H 1 0 0', b'H 0.4 0 0')
    candidate_(root, 'damaged', damaged, parent=identity, target_channel='transfer')
    link_result(root, 'guess-a', identity)
    link_result(root, 'damaged', identity)
    declare_frequency(root, ('damaged', identity))
    result = mapped_diagnose(root, candidate=None, all_candidates=True, windows=path)
    assert result['order'][0] == 'damaged'
    assert result['candidates'][0]['verdict'] == 'rejected'
    assert result['candidates'][0]['modes']['aligned_rmsd_angstrom'] > 0


def test_cli_repeated_coordinates_without_window_file(mode_case, capsys):
    root, identity, _ = mode_case
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
                     '--modes-attempt', identity, '--reaction-coordinate', 'distance:1-2:breaking',
                     '--reaction-coordinate', 'distance:2-3:forming', '--json']) == 0
    row = json.loads(capsys.readouterr().out)['candidates'][0]
    modes = row['modes']
    assert modes['best_mode'] == 2 and len(modes['coordinates_spec']) == 2
    assert modes['coordinate_sources'] == [dict(command_line='distance:1-2:breaking'),
                                           dict(command_line='distance:2-3:forming')]
    assert row['counts']['reaction_center_pairs'] == 2


def test_oversized_mode_record_keeps_all_imaginary_and_full_stdout(mode_case, capsys):
    root, identity, path = mode_case
    config = json.loads(path.read_bytes())
    for spec in config['reaction_coordinates']['transfer']:
        spec['label'] = '合成标签' * 4000
    write_json(path, config)
    before = files(root / 'attempts')
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
                     '--modes-attempt', identity, '--windows', str(path), '--record', '--json']) == 0
    report = json.loads(capsys.readouterr().out)['candidates'][0]
    _, events, _ = catalog.read_journal(root)
    saved = events[-1]['diagnosis']
    assert len(catalog.encode(report)) > 65536 >= len(catalog.encode(saved))
    assert saved['truncated'] and saved['modes']['reference_modes_removed'] == 3
    assert len(report['modes']['modes']) == 5
    for original, compact in zip(report['modes']['modes'][:2], saved['modes']['modes'], strict=True):
        assert original['delta'] and compact['delta'] == []
        for key in ('index', 'frequency_cm1', 'sigma', 'consistent_count', 'signed_count', 'overlap'):
            assert compact[key] == original[key]
    assert files(root / 'attempts') == before


def test_unrepresentable_mode_summary_refuses_record_without_partial_write(mode_case, capsys, monkeypatch):
    root, identity, path = mode_case
    # Force the existing byte budget below even the mandatory summaries to
    # exercise the failure path without a physically huge molecule fixture.
    monkeypatch.setattr(g0, 'MAX_DIAGNOSIS_BYTES', 1024)
    before = files(root)
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
                     '--modes-attempt', identity, '--windows', str(path), '--record', '--json']) == 2
    report = json.loads(capsys.readouterr().out)
    assert 'every imaginary mode' in report['record']['error']
    assert len(report['candidates'][0]['modes']['modes']) == 5
    assert files(root) == before


def reference_declaration(root, candidate='guess-a', permutation=None):
    value = next(c for c in catalog.show(root)[0]['objects'][0]['candidates'] if c['id'] == candidate)
    _, source, _ = g0._manifest_frame(root, value['parent']['attempt'])
    return dict(object='water-a', candidate=candidate, candidate_sha256=value['sha256'],
                target=g0_mapping.reference_target(source),
                candidate_to_target=permutation or list(range(1, value['n_atoms'] + 1)))


def test_legacy_candidates_and_reference_mapping_do_not_establish_mode_identity(mode_case, capsys):
    root, identity, windows = mode_case
    argv = ['g0', str(root), '--object', 'water-a', '--candidate', 'guess-a',
            '--modes-attempt', identity, '--windows', str(windows), '--json']
    before = files(root)
    assert cli.main(argv) == 0
    row = json.loads(capsys.readouterr().out)['candidates'][0]
    assert row['integrity']['atom_order']['sequence_status'] == 'same'
    assert row['atom_correspondence']['reference']['status'] == 'unverified'
    assert row['atom_correspondence']['frequency']['status'] == 'unverified'
    assert not row['modes']['available'] and 'modes' not in row['modes']
    assert row['modes']['source']['log_sha256']
    assert row['verdict'] != 'rejected' and files(root) == before
    mapping = root / 'analyses/reference-only.json'
    write_json(mapping, dict(mappings=[reference_declaration(root)]))
    before = files(root)
    assert cli.main(argv + ['--atom-mapping', str(mapping)]) == 0
    row = json.loads(capsys.readouterr().out)['candidates'][0]
    assert row['atom_correspondence']['reference']['status'] == 'declared_verified'
    assert row['atom_correspondence']['frequency']['status'] == 'unverified'
    assert not row['modes']['available'] and files(root) == before


@pytest.mark.parametrize('origin', ['scan', 'qst', 'manual'])
def test_origin_parent_and_small_rmsd_never_prove_correspondence(mode_case, origin):
    root, identity, windows = mode_case
    swapped = b'3\nSynthetic swapped O atoms\nO 2.6 0 0\nH 1 0 0\nO 0 0 0\n'
    candidate_(root, 'swapped', swapped, parent=identity, origin=origin, target_channel='transfer')
    row = diagnose(root, candidate='swapped', modes_attempt=identity, windows=windows)['candidates'][0]
    assert row['integrity']['atom_order']['status'] == 'pass'
    assert not row['modes']['available'] and row['verdict'] != 'rejected'
    assert row['atom_correspondence']['frequency']['status'] == 'unverified'


def test_different_element_sequence_can_use_explicit_reference_bijection(normal):
    root, identity = normal
    candidate_(root, 'permuted', b'3\nSynthetic\nH 0 0 1\nO 0 0 0\nH 0 1 0\n', parent=identity)
    path = root / 'analyses/mapping.json'
    write_json(path, dict(mappings=[reference_declaration(root, 'permuted', [2, 1, 3])]))
    row = diagnose(root, candidate='permuted', atom_mapping=path)['candidates'][0]
    assert row['integrity']['atom_order']['sequence_status'] == 'different'
    assert row['integrity']['atom_order']['status'] == 'pass'
    assert row['atom_correspondence']['reference']['status'] == 'declared_verified'


@pytest.mark.parametrize('field,category', [
    ('candidate_to_target', 'invalid_atom_mapping'), ('candidate_sha256', 'atom_mapping_binding_mismatch'),
    ('attempt', 'atom_mapping_binding_mismatch'), ('sha256', 'atom_mapping_binding_mismatch'),
    ('section_sha256', 'atom_mapping_binding_mismatch'), ('start_line', 'atom_mapping_binding_mismatch'),
    ('end_line', 'atom_mapping_binding_mismatch')])
@pytest.mark.parametrize('selection', [['--all'], ['--channel', 'transfer']])
def test_mapping_errors_keep_other_candidates_and_prevent_record(mode_batch, capsys, field, category, selection):
    root, windows, names, identities = mode_batch
    path = root / 'analyses/atom-mapping.json'
    config = json.loads(path.read_bytes())
    entry = next(e for e in config['mappings'] if e['candidate'] == names[1])
    if field == 'candidate_to_target':
        entry[field] = [1, 2, 2]
    elif field == 'candidate_sha256':
        entry[field] = '0' * 64
    elif field == 'attempt':
        entry['target'][field] = identities[0]
    else:
        entry['target']['source'][field] = 999 if field.endswith('line') else '0' * 64
    write_json(path, config)
    before = files(root)
    argv = ['g0', str(root), '--object', 'water-a', *selection, '--windows', str(windows), '--record']
    assert mapped_main(argv + ['--json']) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['order'] == [names[0], names[2]]
    assert report['counts']['selected'] == 3 and report['counts']['errors'] == 1
    error = report['errors'][0]
    assert error['candidate'] == names[1] and error['category'] == category
    assert error['source']['mapping_sha256'] == sha256(path.read_bytes()).hexdigest()
    assert error['source']['target']['attempt'] == identities[1]
    assert report['record']['error'] == g0.UNRECORDED_NOTICE
    assert all(c['modes']['available'] for c in report['candidates'])
    assert mapped_main(argv + ['--dry-run']) == 2
    assert 'atom_mapping' in capsys.readouterr().out
    assert files(root) == before
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--candidate', names[1],
                        '--modes-attempt', identities[1], '--windows', str(windows), '--record', '--json']) == 1
    assert 'error' in json.loads(capsys.readouterr().out) and files(root) == before


@pytest.mark.parametrize('fault', ['candidate', 'log', 'reference', 'journal', 'symlink'])
def test_mapping_failure_cannot_mask_underlying_corruption(mode_batch, capsys, fault):
    root, windows, names, identities = mode_batch
    path = root / 'analyses/atom-mapping.json'
    config = json.loads(path.read_bytes())
    # Every declaration is bad: a broad catch or early validation would hide
    # fatal corruption in the same candidate as well as in a later one.
    for entry in config['mappings']:
        entry['candidate_to_target'] = []
    write_json(path, config)
    last = root / 'attempts' / identities[-1]
    if fault == 'candidate':
        candidate = catalog.show(root)[0]['objects'][0]['candidates'][-1]
        archive = root / candidate['file']
        archive.chmod(0o600)
        archive.write_bytes(archive.read_bytes() + b'\n')
    elif fault == 'log':
        log = last / 'outputs/job.log'
        log.write_bytes(log.read_bytes().replace(b'Normal termination of Gaussian', b'Error termination of Gaussian'))
    elif fault == 'reference':
        write_json(last / 'manifest.json', {})
    elif fault == 'journal':
        journal = root / 'catalog/journal.jsonl'
        journal.write_bytes(journal.read_bytes() + b'{')
    else:
        log = last / 'outputs/job.log'
        log.unlink()
        log.symlink_to(root / 'attempts' / identities[0] / 'outputs/job.log')
    before = files(root)
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(windows),
                        '--record', '--json']) == 1
    report = json.loads(capsys.readouterr().out)
    assert 'error' in report and 'errors' not in report and 'candidates' not in report
    assert files(root) == before


def test_mapping_file_is_read_once_and_record_preserves_runtime_hash(mode_batch, capsys, monkeypatch):
    root, windows, _, _ = mode_batch
    path = root / 'analyses/atom-mapping.json'
    raw = path.read_bytes()
    original_read = v2.read_bytes
    reads = []
    def read(value, limit):
        data = original_read(value, limit)
        if str(value) == str(path):
            reads.append(value)
            path.write_text('{"mappings":[]}')
        return data
    monkeypatch.setattr(v2, 'read_bytes', read)
    before = files(root / 'attempts')
    journal = (root / 'catalog/journal.jsonl').read_bytes()
    assert mapped_main(['g0', str(root), '--object', 'water-a', '--all', '--windows', str(windows),
                        '--record', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(reads) == 1 and all(c['modes']['available'] for c in report['candidates'])
    assert (root / 'catalog/journal.jsonl').read_bytes().startswith(journal)
    _, events, _ = catalog.read_journal(root)
    for event in events[-3:]:
        correspondence = event['diagnosis']['atom_correspondence']['frequency']
        assert correspondence['mapping_sha256'] == sha256(raw).hexdigest()
        assert correspondence['target']['source']['section_sha256']
        assert event['assignment'] == dict(status='none', channels=[])
    assert files(root / 'attempts') == before


def test_reference_and_frequency_can_use_different_source_and_permutation(mode_case):
    root, frequency, _ = mode_case
    swapped_rows = 'O 2.6 0 0\nH 1 0 0\nO 0 0 0'
    reference = make_attempt(root, '006-swapped', geometry=swapped_rows, charge=1, multiplicity=1)
    candidate_(root, 'swapped', ('3\nSynthetic\n' + swapped_rows + '\n').encode(), parent=reference)
    path = declare_frequency(root, ('swapped', frequency))
    data = json.loads(path.read_bytes())
    entry = next(e for e in data['mappings'] if e['candidate'] == 'swapped')
    entry['candidate_to_target'] = [3, 2, 1]
    data['mappings'].append(reference_declaration(root, 'swapped'))
    write_json(path, data)
    row = diagnose(root, candidate='swapped', modes_attempt=frequency, atom_mapping=path,
                   reaction_coordinate=['distance:3-2:breaking', 'distance:2-1:forming'])['candidates'][0]
    correspondence = row['atom_correspondence']
    assert correspondence['reference']['target']['attempt'] == reference
    assert correspondence['reference']['candidate_to_target'] == [1, 2, 3]
    assert correspondence['frequency']['target']['attempt'] == frequency
    assert correspondence['frequency']['candidate_to_target'] == [3, 2, 1]
    assert row['modes']['best_mode'] == 2
    best = next(m for m in row['modes']['modes'] if m['index'] == 2)
    assert [d['value'] for d in best['delta']] == pytest.approx([1, -1])
    assert [d['candidate_atoms'] for d in best['delta']] == [[3, 2], [2, 1]]
    assert [d['atoms'] for d in best['delta']] == [[1, 2], [2, 3]]


@pytest.mark.parametrize('source', ['reference', 'frequency'])
def test_valid_source_bytes_changed_since_declaration_is_local_binding_failure(mode_case, source):
    root, identity, windows = mode_case
    path = root / 'analyses/atom-mapping.json'
    data = json.loads(path.read_bytes())
    data['mappings'].append(reference_declaration(root))
    write_json(path, data)
    if source == 'reference':
        manifest = root / 'attempts' / identity / 'manifest.json'
        content = json.loads(manifest.read_bytes())
        content['science']['geometry'] += '\n'
        write_json(manifest, content)
    else:
        log = root / 'attempts' / identity / 'outputs/job.log'
        log.write_bytes(log.read_bytes() + b'\n')
    link_result(root, 'guess-a', identity)
    report = diagnose(root, candidate=None, all_candidates=True, windows=windows, atom_mapping=path)
    assert report['candidates'] == report['order'] == []
    assert report['counts']['errors'] == report['counts']['selected'] == 1
    assert report['errors'][0]['category'] == 'atom_mapping_binding_mismatch'
    assert source in report['errors'][0]['reason']


@pytest.mark.parametrize('kind', ['qst', 'xtb', 'crest'])
def test_reference_mapping_binds_actual_json_or_xyz_source(normal, kind):
    root, _ = normal
    if kind == 'qst':
        science = dict(structures=[dict(geometry=GEOMETRY, charge=0, multiplicity=1)] * 2)
        identity = make_attempt(root, '007-reference', qst_mode='QST2', **science)
    else:
        identity = make_attempt(root, '007-reference', template=kind)
        path = root / 'attempts' / identity
        (path / 'inputs').mkdir()
        (path / 'inputs/input.xyz').write_bytes(XYZ)
        manifest = json.loads((path / 'manifest.json').read_bytes())
        manifest.update(inputs=[dict(name='input.xyz', sha256=sha256(XYZ).hexdigest(), size=len(XYZ))],
                        template_params={'--chrg': '0', '--uhf': '0'}, science={})
        write_json(path / 'manifest.json', manifest)
    candidate_(root, 'new', parent=identity)
    declaration = reference_declaration(root, 'new')
    mapping = root / 'analyses/reference.json'
    write_json(mapping, dict(mappings=[declaration]))
    row = diagnose(root, candidate='new', atom_mapping=mapping)['candidates'][0]
    assert row['atom_correspondence']['reference']['status'] == 'declared_verified'
    if kind == 'qst':
        assert declaration['target']['source']['json_pointer'] == '/science/structures/0/geometry'
    else:
        assert declaration['target']['source']['frame'] == 1
        assert declaration['target']['source']['sha256'] == sha256(XYZ).hexdigest()
        (path / 'inputs/input.xyz').write_bytes(XYZ + b'\n')
        with pytest.raises(ValueError, match='hash/size') as error:
            diagnose(root, candidate=None, all_candidates=True, atom_mapping=mapping)
        assert not isinstance(error.value, g0_mapping.AtomMappingError)


def test_bounded_diagnosis_retains_mapping_bindings_after_json_roundtrip(mode_case):
    root, identity, windows = mode_case
    row = json.loads(json.dumps(mapped_diagnose(root, windows=windows, modes_attempt=identity)['candidates'][0]))
    original = deepcopy(row['atom_correspondence']['frequency'])
    row['stereo']['long_text'] = 'x' * 70000
    bounded = g0.bounded_diagnosis(row)
    for saved in (bounded['atom_correspondence']['frequency'], bounded['modes']['atom_correspondence']):
        assert saved['mapping_sha256'] == original['mapping_sha256']
        assert saved['target'] == original['target']
        assert saved['json_pointer'] == original['json_pointer']
        assert saved['atom_count'] == 3 and 'candidate_to_target' not in saved
    assert len(catalog.encode(bounded)) <= 65536


@pytest.mark.parametrize('declaration', ['missing', 'invalid'])
def test_zero_mode_cannot_be_hidden_by_mapping(mode_case, capsys, declaration):
    root, identity, windows = mode_case
    log = root / 'attempts' / identity / 'outputs/job.log'
    lines = log.read_text().splitlines(keepends=True)
    in_vectors = False
    for index, line in enumerate(lines):
        if line.split()[:3] == ['Atom', 'AN', 'X']:
            in_vectors = True
            continue
        if in_vectors:
            values = line.split()
            if len(values) == 11 and values[0] in ('1', '2', '3'):
                values[2:5] = ['0.00'] * 3
                lines[index] = '     ' + '   '.join(values) + '\n'
            else:
                break
    log.write_text(''.join(lines))
    args = ['g0', str(root), '--object', 'water-a', '--all', '--windows', str(windows), '--record', '--json']
    link_result(root, 'guess-a', identity)
    if declaration == 'invalid':
        path = root / 'analyses/atom-mapping.json'
        data = json.loads(path.read_bytes())
        data['mappings'][0]['candidate_to_target'] = []
        write_json(path, data)
        args += ['--atom-mapping', str(path)]
    before = files(root)
    assert cli.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert 'no nonzero displacement' in report['error']
    assert 'errors' not in report and files(root) == before
