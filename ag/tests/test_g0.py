"""T137 synthetic local diagnostics; no calculations or real study data."""
from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

from ag import catalog, catalog_v2 as v2, cli, g0, geometry as geo
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
        report = diagnose(water, candidate=name, window=['1-2:0:4'])['candidates'][0]
        assert report['verdict'] == verdict
        assert any('受限松弛' in f['message'] for f in report['flags'])
        assert cli.main(['g0', str(water), '--object', 'water-a', '--candidate', name, '--json']) == (1 if verdict == 'rejected' else 0)
        assert 'error' not in json.loads(capsys.readouterr().out)


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
