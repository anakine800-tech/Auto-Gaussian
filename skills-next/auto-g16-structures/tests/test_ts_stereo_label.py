"""Synthetic tetrahedral geometries only; no research data or remote operations."""
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytest.importorskip('rdkit')
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import ts_stereo_label as label


def molecule(smiles):
    params = Chem.SmilesParserParams()
    params.removeHs = False
    return Chem.MolFromSmiles(smiles, params)


def write_csv(path, rows, fields=('reference_atom', 'ts_atom')):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def reference(root, smiles='F[C@H](Cl)Br', name='product', suffix='.mol'):
    mol = molecule(smiles)
    AllChem.Compute2DCoords(mol)
    if suffix == '.sdf':
        with Chem.SDWriter(str(root / (name + suffix))) as writer:
            writer.write(mol)
    else:
        Chem.MolToMolFile(mol, str(root / (name + suffix)))
    full = Chem.AddHs(mol)
    rows = [dict(reference_atom=str(i + 1), ts_atom=str(i + 1)) for i in range(mol.GetNumAtoms())]
    for atom in mol.GetAtoms():
        if atom.GetChiralTag() in label.TETRAHEDRAL and atom.GetTotalNumHs() == 1:
            hydrogen = next(a.GetIdx() for a in full.GetAtomWithIdx(atom.GetIdx()).GetNeighbors()
                            if a.GetIdx() >= mol.GetNumAtoms())
            rows.append(dict(reference_atom=f'H@{atom.GetIdx() + 1}', ts_atom=str(hydrogen + 1)))
    write_csv(root / (name + '-map.csv'), rows)
    return mol, rows


def geometry(smiles='F[C@H](Cl)Br'):
    mol = Chem.AddHs(molecule(smiles))
    assert AllChem.EmbedMolecule(mol, randomSeed=42) == 0
    return [a.GetSymbol() for a in mol.GetAtoms()], mol.GetConformer().GetPositions()


def body(symbols, points):
    return '\n'.join(f'{s} {x:.10f} {y:.10f} {z:.10f}' for s, (x, y, z) in zip(symbols, points)) + '\n'


def attempt(root, name='ts-same', smiles='F[C@H](Cl)Br', frame=None):
    symbols, points = geometry(smiles) if frame is None else frame
    path = root / 'attempts' / name
    path.mkdir(parents=True)
    (path / 'final_input.xyz').write_text(f'{len(symbols)}\nsynthetic local geometry\n' + body(symbols, points))
    (path / 'manifest.json').write_text(json.dumps({'science': {'geometry': body(symbols, points)}}))
    return symbols, points


def run(root, ts='ts-same', name='labels', **kwargs):
    return label.run(root, name, ts, kwargs.pop('product', 'product.mol'),
                     kwargs.pop('product_map', 'product-map.csv'), **kwargs)


def setup(root):
    reference(root)
    return attempt(root)


def test_retention_sn2_inversion_and_evidence(tmp_path):
    reference(tmp_path)
    symbols, points = geometry()
    # Stretch the three heavy-atom arms to mimic a distorted partial-bond TS.
    points[[0, 2, 3]] = points[1] + 1.6 * (points[[0, 2, 3]] - points[1])
    attempt(tmp_path, frame=(symbols, points))
    inverted = points.copy(); inverted[:, 2] *= -1
    attempt(tmp_path, 'ts-invert', frame=(symbols, inverted))
    report = run(tmp_path, 'ts-same,ts-invert')
    same, inverse = [a['product_centers'][0] for a in report['attempts']]
    assert (same['relation'], same['label']) == ('same', 'R')
    assert (inverse['relation'], inverse['label']) == ('opposite', 'S')
    assert inverse['signed_volume'] == pytest.approx(-same['signed_volume'])
    assert abs(same['signed_volume']) > 0.9
    assert same['neighbors'][-1] == 'H@2'
    assert report['attempts'][0]['product_configuration'] == 'C2:R'
    assert report['attempts'][0]['catalyst_check']['status'] == 'not_requested'
    assert report['channel_suggestions'] is None
    for source in report['inputs']:
        assert source['sha256'] == hashlib.sha256((tmp_path / source['path']).read_bytes()).hexdigest()
        assert not Path(source['path']).is_absolute()
    output = tmp_path / 'analyses/ts-labels/labels'
    assert json.loads((output / 'labels.json').read_text()) == report
    assert 'C2:R' in (output / 'labels.md').read_text()
    assert str(tmp_path) not in (output / 'labels.json').read_text()
    assert not (output / 'channel-suggestions.csv').exists()


@pytest.mark.parametrize('first,second,expected', [('@', '@', 'C2:S;C4:R'), ('@', '@@', 'C2:S;C4:S'),
                                                 ('@@', '@', 'C2:R;C4:R'), ('@@', '@@', 'C2:R;C4:S')])
def test_two_adjacent_centers_four_combinations(tmp_path, first, second, expected):
    reference(tmp_path, 'C[C@H](O)[C@H](O)C')
    attempt(tmp_path, smiles=f'C[C{first}H](O)[C{second}H](O)C')
    item = run(tmp_path)['attempts'][0]
    assert item['product_configuration'] == expected
    assert all(not c['review_reasons'] for c in item['product_centers'])


@pytest.mark.parametrize('smiles,expected', [('F[C@](Cl)(Br)I', 'C2:S'), ('[H][C@](F)(Cl)Br', 'C2:S')])
@pytest.mark.parametrize('suffix', ['.mol', '.sdf'])
def test_explicit_four_neighbors_and_reference_formats(tmp_path, smiles, expected, suffix):
    reference(tmp_path, smiles, suffix=suffix)
    attempt(tmp_path, smiles=smiles)
    item = run(tmp_path, product='product' + suffix)['attempts'][0]
    assert item['product_configuration'] == expected
    assert not any(n.startswith('H@') for n in item['product_centers'][0]['neighbors'])


def test_source_and_ts_order_permutations(tmp_path):
    mol, rows = reference(tmp_path)
    symbols, points = geometry()
    source_order = [2, 0, 3, 1]
    reordered = Chem.RenumberAtoms(mol, source_order)
    Chem.MolToMolFile(reordered, str(tmp_path / 'product.mol'))
    ts_order = [4, 3, 1, 0, 2]
    indices = {old + 1: new + 1 for new, old in enumerate(ts_order)}
    mapping = [dict(reference_atom=str(i + 1), ts_atom=str(indices[old + 1])) for i, old in enumerate(source_order)]
    mapping.append(dict(reference_atom='H@4', ts_atom=str(indices[int(rows[-1]['ts_atom'])])))
    write_csv(tmp_path / 'product-map.csv', mapping)
    attempt(tmp_path, frame=([symbols[i] for i in ts_order], points[ts_order]))
    assert run(tmp_path)['attempts'][0]['product_configuration'] == 'C4:R'


def test_volume_rotation_translation_scale_invariant():
    _, points = geometry()
    center, neighbors = points[1], points[[0, 2, 3, 4]]
    initial = label.signed_volume(center, neighbors)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    offset = np.array([4.0, -6.0, 2.0])
    moved = (neighbors - center) * np.array([2, 0.5, 8, 1])[:, None] + center
    assert label.signed_volume(center @ rotation + offset, moved @ rotation + offset) == pytest.approx(initial)
    with pytest.raises(ValueError, match='coincides'):
        label.signed_volume(center, np.array([center, *neighbors[1:]]))


@pytest.mark.parametrize('epsilon', [0, 1e-4, -1e-4])
def test_nearly_planar_is_unknown(tmp_path, epsilon):
    reference(tmp_path)
    symbols = ['F', 'C', 'Cl', 'Br', 'H']
    points = np.array([[1, 0, epsilon], [0, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]])
    attempt(tmp_path, frame=(symbols, points))
    center = run(tmp_path)['attempts'][0]['product_centers'][0]
    assert center['label'] == center['relation'] == 'unknown'
    assert abs(center['signed_volume']) < 0.05


@pytest.mark.parametrize('smiles,atom,cip,reason', [
    ('C[C@H](O)[C@H](Cl)[C@H](O)C', 4, 's', 'pseudoasymmetric'),
    ('F[C@]([C@H](Cl)[C@H](Br)I)([C@H](Cl)[C@@H](Br)I)N', 2, 'R', 'depends')])
def test_pseudoasymmetric_and_stereo_dependent_cip_need_review(tmp_path, smiles, atom, cip, reason):
    reference(tmp_path, smiles)
    attempt(tmp_path, smiles=smiles)
    centers = run(tmp_path)['attempts'][0]['product_centers']
    center = next(c for c in centers if c['reference_atom'] == atom)
    assert center['reference_cip'] == cip
    assert center['label'] == 'needs_review'
    assert any(reason in r for r in center['reasons'])
    assert all(c['label'] in {'R', 'S'} for c in centers if c != center)


def test_unassigned_reference_rejected(tmp_path):
    reference(tmp_path, 'FC(Cl)Br')
    attempt(tmp_path)
    with pytest.raises(ValueError, match='Unassigned'):
        run(tmp_path)
    assert not (tmp_path / 'analyses').exists()


def test_relative_stereo_group_needs_review():
    mol = Chem.MolFromSmiles('F[C@H](Cl)Br |o1:1|')
    assert label.reference_centers(mol)[0]['review_reasons'] == [
        'relative/mixture stereo group does not specify an absolute reference']


@pytest.mark.parametrize('flip,expected', [(False, 'unchanged'), (True, 'changed')])
def test_catalyst_check_and_suggestion_warning(tmp_path, flip, expected):
    symbols, points = setup(tmp_path)
    _, mapping = reference(tmp_path, name='catalyst')
    for row in mapping:
        row['ts_atom'] = str(int(row['ts_atom']) + len(symbols))
    write_csv(tmp_path / 'catalyst-map.csv', mapping)
    extra = points.copy()
    if flip:
        extra[:, 2] *= -1
    target = tmp_path / 'attempts/ts-same/final_input.xyz'
    target.write_text(f'{2 * len(symbols)}\nsynthetic catalyst complex\n' + body(symbols + symbols, np.vstack([points, extra + 10])))
    write_csv(tmp_path / 'channels.csv', [{'channel_id': 'r', 'product_branch': 'C2:R'}], ['channel_id', 'product_branch'])
    report = run(tmp_path, catalyst='catalyst.mol', catalyst_map='catalyst-map.csv', channels='channels.csv')
    item = report['attempts'][0]
    assert item['catalyst_check']['status'] == expected
    assert bool(item['warnings']) == flip
    assert report['channel_suggestions'][0]['suggested_channel_id'] == ('' if flip else 'r')
    if flip:
        assert '**警告：催化剂' in (tmp_path / 'analyses/ts-labels/labels/labels.md').read_text()


@pytest.mark.parametrize('branches,expected,note', [(['C2:R'], 'ch-0', 'unique match'),
    (['C2:S'], '', 'no exact'), (['C2:R', 'C2:R'], '', 'multiple')])
def test_channel_suggestions_are_only_drafts(tmp_path, branches, expected, note):
    setup(tmp_path)
    path = tmp_path / 'channels.csv'
    write_csv(path, [dict(channel_id=f'ch-{i}', product_branch=b) for i, b in enumerate(branches)],
              ['channel_id', 'product_branch'])
    original = path.read_bytes()
    report = run(tmp_path, channels=path.name)
    row = report['channel_suggestions'][0]
    assert row['suggested_channel_id'] == expected
    assert row['status'] == 'pending_confirmation' and note in row['note']
    out = tmp_path / 'analyses/ts-labels/labels/channel-suggestions.csv'
    assert list(csv.DictReader(io.StringIO(out.read_text()))) == [row]
    assert path.read_bytes() == original
    assert 'ensemble_manifests' not in out.read_text()
    assert not (tmp_path / 'study.md').exists()


@pytest.mark.parametrize('label_value', ['unknown', 'needs_review'])
def test_unresolved_center_never_suggests_channel(label_value):
    item = dict(attempt='ts', product_configuration=f'C2:{label_value}',
                product_centers=[{'label': label_value}], catalyst_check={'status': 'not_requested'})
    row = label.suggestion(item, [{'channel_id': 'bad', 'product_branch': item['product_configuration']}])
    assert row['suggested_channel_id'] == ''
    assert row['status'] == 'pending_confirmation'
    assert 'unknown/needs_review' in row['note']


@pytest.mark.parametrize('bad,match', [('missing', 'missing'), ('element', 'element mismatch'),
    ('duplicate_ref', 'one-to-one'), ('duplicate_ts', 'one-to-one'), ('out_of_range', 'exceeds'),
    ('bad_h', 'invalid reference_atom'), ('zero', 'positive'), ('bad_ref', 'invalid reference_atom')])
def test_bad_mapping_refused(tmp_path, bad, match):
    _, rows = reference(tmp_path)
    attempt(tmp_path)
    if bad == 'missing': rows.pop()
    elif bad == 'element': rows[0]['ts_atom'], rows[1]['ts_atom'] = rows[1]['ts_atom'], rows[0]['ts_atom']
    elif bad == 'duplicate_ref': rows.append(dict(reference_atom='1', ts_atom='6'))
    elif bad == 'duplicate_ts': rows[-1]['ts_atom'] = rows[0]['ts_atom']
    elif bad == 'out_of_range': rows[0]['ts_atom'] = '999'
    elif bad == 'bad_h': rows[-1]['reference_atom'] = 'H@1'
    elif bad == 'zero': rows[0]['ts_atom'] = '0'
    elif bad == 'bad_ref': rows[0]['reference_atom'] = '999'
    write_csv(tmp_path / 'product-map.csv', rows)
    with pytest.raises(ValueError, match=match): run(tmp_path)
    assert not (tmp_path / 'analyses').exists()


def test_partial_mapping_needs_only_centers_and_neighbors(tmp_path):
    _, rows = reference(tmp_path, 'F[C@H](Cl)CCC')
    attempt(tmp_path, smiles='F[C@H](Cl)CCC')
    write_csv(tmp_path / 'product-map.csv', [r for r in rows if r['reference_atom'] not in {'5', '6'}])
    assert run(tmp_path)['attempts'][0]['product_centers'][0]['relation'] == 'same'


def test_input_geometry_and_qst_selection(tmp_path):
    symbols, points = setup(tmp_path)
    path = tmp_path / 'attempts/ts-same/manifest.json'
    inverted = points.copy(); inverted[:, 2] *= -1
    path.write_text(json.dumps({'science': {'geometry': body(symbols, inverted)}}))
    report = run(tmp_path, geometry='input')
    assert report['attempts'][0]['product_configuration'] == 'C2:S'
    assert report['attempts'][0]['geometry_source']['json_pointer'] == '/science/geometry'
    groups = [{'geometry': body(symbols, points)}] * 2 + [{'geometry': body(symbols, inverted)}]
    path.write_text(json.dumps({'science': {'structures': groups}}))
    report = run(tmp_path, name='qst3', geometry='input')
    assert report['attempts'][0]['product_configuration'] == 'C2:S'
    assert report['attempts'][0]['geometry_source']['json_pointer'] == '/science/structures/2/geometry'
    path.write_text(json.dumps({'science': {'structures': groups[:2]}}))
    with pytest.raises(ValueError, match='QST2'): run(tmp_path, name='qst2', geometry='input')


@pytest.mark.parametrize('bad', ['multiple', 'nan', 'short', 'count', 'element', 'missing_final'])
def test_invalid_final_geometry_refused_without_fallback(tmp_path, bad):
    setup(tmp_path)
    path = tmp_path / 'attempts/ts-same/final_input.xyz'
    text = path.read_text()
    if bad == 'multiple': path.write_text(text + text)
    elif bad == 'nan': path.write_text('1\nsynthetic\nC nan 0 0\n')
    elif bad == 'short': path.write_text('5\nsynthetic\nC 0 0 0\n')
    elif bad == 'count': path.write_text('0\nsynthetic\n')
    elif bad == 'element': path.write_text('1\nsynthetic\nXx 0 0 0\n')
    elif bad == 'missing_final': path.rename(path.with_name('final.xyz'))
    with pytest.raises((ValueError, OSError)): run(tmp_path)


@pytest.mark.parametrize('value', [0, -0.1, 1.1, float('nan'), float('inf')])
def test_threshold_validation(tmp_path, value):
    with pytest.raises(ValueError, match='min_chirality'): run(tmp_path, min_chirality=value)


@pytest.mark.parametrize('target', ['reference', 'map', 'geometry', 'attempts', 'analyses', 'output', 'root'])
def test_symlink_refusal(tmp_path, target):
    root = tmp_path / 'study'; root.mkdir()
    setup(root)
    if target == 'root':
        alias = tmp_path / 'alias'; alias.symlink_to(root); root = alias
    else:
        relative = {'reference': 'product.mol', 'map': 'product-map.csv',
                    'geometry': 'attempts/ts-same/final_input.xyz', 'attempts': 'attempts',
                    'analyses': 'analyses', 'output': 'analyses/ts-labels/labels'}[target]
        path = root / relative
        if path.exists(): path.rename(tmp_path / 'held')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(tmp_path / 'held')
    with pytest.raises(ValueError, match='symlink'): run(root)


@pytest.mark.parametrize('kwargs', [{'product': '../outside.mol'}, {'product_map': '/outside.csv'},
    {'name': '../outside'}, {'ts': '../outside'}, {'ts': 'ts-same,ts-same'}, {'catalyst': 'product.mol'}])
def test_paths_and_paired_options_refused(tmp_path, kwargs):
    setup(tmp_path)
    with pytest.raises(ValueError): run(tmp_path, **kwargs)


def test_no_overwrite_or_mixed_input_revisions(tmp_path, monkeypatch):
    setup(tmp_path)
    run(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='already exists'): run(tmp_path)
    assert all(p.read_bytes() == data for p, data in before.items())
    original = label.markdown
    def change_input(report):
        (tmp_path / 'product-map.csv').write_text('reference_atom,ts_atom\n1,1\n')
        return original(report)
    monkeypatch.setattr(label, 'markdown', change_input)
    with pytest.raises(ValueError, match='input changed'): run(tmp_path, name='edited')
    assert not (tmp_path / 'analyses/ts-labels/edited').exists()


@pytest.mark.skipif(not getattr(Chem, 'HasChemDrawCDXSupport', lambda: False)(), reason='RDKit lacks ChemDraw CDX support')
def test_cdxml_explicit_h(tmp_path):
    shutil.copyfile(Path(__file__).parent / 'fixtures/chiral_explicit_h.cdxml', tmp_path / 'product.cdxml')
    mol, _, _ = label.read_molecule(str(tmp_path / 'product.cdxml'), Chem, preserve_explicit_h=True)
    full = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(full, randomSeed=42) == 0
    write_csv(tmp_path / 'product-map.csv', [dict(reference_atom=str(i + 1), ts_atom=str(i + 1)) for i in range(mol.GetNumAtoms())])
    attempt(tmp_path, frame=([a.GetSymbol() for a in full.GetAtoms()], full.GetConformer().GetPositions()))
    assert run(tmp_path, product='product.cdxml')['attempts'][0]['product_configuration'] == 'C1:S'


def test_cli_end_to_end_synthetic(tmp_path):
    setup(tmp_path)
    write_csv(tmp_path / 'channels.csv', [{'channel_id': 'channel-r', 'product_branch': 'C2:R'}], ['channel_id', 'product_branch'])
    process = subprocess.run([sys.executable, str(SCRIPTS / 'ts_stereo_label.py'), '--study', str(tmp_path),
        '--name', 'cli', '--ts', 'ts-same', '--product', 'product.mol', '--product-map', 'product-map.csv',
        '--channels', 'channels.csv'], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)['configurations'] == {'ts-same': 'C2:R'}
    assert json.loads(process.stdout)['status'] == 'pending_confirmation'
    assert (tmp_path / 'analyses/ts-labels/cli/channel-suggestions.csv').is_file()
