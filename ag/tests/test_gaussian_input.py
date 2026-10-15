"""T13-1 Cartesian QST validation; synthetic geometries, no Gaussian execution."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from ag import attempt, gaussian_input, study
from test_core import INPUT, cfg


WATER = 'O 0 0 0\nH 0 0 1\nH 0 1 0'


def qst(mode=2, *, route=None, blocks=None):
    if blocks is None:
        blocks = [(f'Water group {i + 1}', '0 1', WATER) for i in range(mode)]
    route = route or f'# HF/STO-3G Opt=(QST{mode},CalcFC)'
    return ('%nprocshared=8\n%mem=10GB\n%chk=water.chk\n' + route + '\n\n' +
            '\n\n'.join(f'{title}\n\n{state}\n{geometry}' for title, state, geometry in blocks) + '\n\n')


def validate(text):
    return gaussian_input.validate(text, 8, 12)


@pytest.mark.parametrize('mode', [2, 3])
@pytest.mark.parametrize('option', ['Opt=QST{n}', 'oPt = (CalcFC, qSt{n}, MaxCycle=50)',
                                    'Opt(QST{n},CalcFC)', 'Opt=(\n CalcFC, QST{n})'])
def test_valid_qst(mode, option):
    result = validate(qst(mode, route='# HF/STO-3G ' + option.format(n=mode)))
    assert result['qst_mode'] == f'QST{mode}'
    assert [s['title'] for s in result['structures']] == [f'Water group {i + 1}' for i in range(mode)]
    assert all(s['n_atoms'] == 3 and s['charge'] == 0 and s['multiplicity'] == 1
               for s in result['structures'])
    assert result['largest_displacements'] == [
        dict(atom_index=i + 1, element=element, displacement=0) for i, element in enumerate(['O', 'H', 'H'])]


@pytest.mark.parametrize('mode,count', [(2, 1), (2, 3), (3, 1), (3, 2), (3, 4)])
def test_wrong_group_count(mode, count):
    with pytest.raises(ValueError, match=f'exactly {mode}'):
        validate(qst(mode, blocks=[('Water', '0 1', WATER)] * count))


@pytest.mark.parametrize('position', [1, 2])
@pytest.mark.parametrize('state,geometry,error', [
    ('0 1', WATER + '\nH 1 0 0', 'n_atoms'),
    ('0 1', 'H 0 0 0\nO 0 0 1\nH 0 1 0', 'elements'),
    ('-1 1', WATER, 'charge'), ('0 3', WATER, 'multiplicity'),
    ('0 0', WATER, 'charge/multiplicity'),
    ('0 1', '', 'coordinates'),
    ('0 1', WATER.replace('O 0', 'O nan'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O inf'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O 1e999'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O 0 0'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O(Fragment=1) 0'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'X 0'), 'real element'),
])
def test_malformed_or_mismatched_group(position, state, geometry, error):
    blocks = [('Water', '0 1', WATER)] * 3
    blocks[position] = ('Changed', state, geometry)
    with pytest.raises(ValueError, match=error):
        validate(qst(3, blocks=blocks))


@pytest.mark.parametrize('route,error', [
    ('Opt=(TS,QST2)', 'Opt=TS'), ('Opt=TS Opt=QST3', 'Opt=TS'),
    ('Opt=(QST3,CalcFC,TS)', 'Opt=TS'),
    ('Opt=(QST2,QST3)', 'QST2 and QST3'), ('Opt=QST2 Opt=QST3', 'QST2 and QST3'),
    ('QST2 Opt=CalcFC', 'option in Opt'), ('Opt=(QST2,QST2)', 'option in Opt'),
    ('Opt=(QST2', 'option in Opt'),
])
def test_conflicting_or_malformed_options(route, error):
    with pytest.raises(ValueError, match=error):
        validate(qst(route='# HF/STO-3G ' + route))


@pytest.mark.parametrize('mode', [2, 3])
@pytest.mark.parametrize('tail', ['--Link1--\n', '@parent.gjf\n', 'include foo\n', 'External=foo\n',
                                '1 2 1.0\n', 'C 0\nSTO-3G\n****\n'])
def test_qst_rejects_unsafe_or_additional_sections(mode, tail):
    with pytest.raises(ValueError):
        validate(qst(mode) + tail)


@pytest.mark.parametrize('oldchk,error', [('parent.chk', 'parent chk attachment'),
    ('water.chk', 'different filenames'), ('../parent.chk', 'plain filename'),
    ('dir/parent.chk', 'plain filename'), ('bad name.chk', 'plain filename')])
@pytest.mark.parametrize('text', [INPUT, qst(2), qst(3)])
def test_oldchk_not_available_without_attachment(text, oldchk, error):
    with pytest.raises(ValueError, match=error):
        validate(f'%oldchk={oldchk}\n' + text)


def test_qst_numeric_elements_and_multiline_titles():
    text = qst(blocks=[('Reactant\nsecond title line', '+0 1', WATER),
                       ('Product', '0 1', WATER.replace('O ', '8 ').replace('H ', '1 '))])
    result = validate(text.replace('\n', '\r\n'))
    assert result['structures'][0]['title'] == 'Reactant\nsecond title line'
    assert result['structures'][1]['elements'] == ['O', 'H', 'H']


def test_kabsch_removes_translation_and_proper_rotation():
    # A 90-degree rotation about z followed by a translation.
    moved = 'O 3 4 5\nH 3 4 6\nH 2 4 5'
    result = validate(qst(blocks=[('Reactant', '0 1', WATER), ('Product', '0 1', moved)]))
    assert all(row['displacement'] == 0 for row in result['largest_displacements'])


def test_kabsch_top_five_have_known_displacements_and_input_indices():
    # Symmetric numerical fixture; scaling doubles each distance from the centroid.
    points = [(1, 0, 0), (-1, 0, 0), (0, 2, 0), (0, -2, 0), (0, 0, 3), (0, 0, -3)]
    geometries = ['\n'.join(f'H {scale*x} {scale*y} {scale*z}' for x, y, z in points) for scale in (1, 2)]
    result = validate(qst(blocks=[('Reactant', '0 1', geometries[0]), ('Product', '0 1', geometries[1])]))
    assert [(r['atom_index'], r['displacement']) for r in result['largest_displacements']] == [
        (5, 3), (6, 3), (3, 2), (4, 2), (1, 1)]
    assert result['displacement_unit'] == 'input coordinate units'


def test_alignment_neither_reflects_nor_remaps_atoms():
    geometry = 'C 0 0 0\nH 1 0 0\nH 0 2 0\nH 0 0 3'
    for changed in ('C 0 0 0\nH -1 0 0\nH 0 2 0\nH 0 0 3',
                    'C 0 0 0\nH 0 2 0\nH 1 0 0\nH 0 0 3'):
        result = validate(qst(blocks=[('Reactant', '0 1', geometry), ('Product', '0 1', changed)]))
        assert result['largest_displacements'][0]['displacement'] > 0.1
        assert 'do not verify same-element' in result['stereochemistry_warning']


def prepare_qst(cfg, tmp_path, mode):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(qst(mode))
    manifest = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:05:00', label='qst')
    return source, attempt.find(cfg, manifest['attempt_id']), manifest


@pytest.mark.parametrize('mode', [2, 3])
def test_prepare_summary_and_revalidation(cfg, tmp_path, mode):
    source, path, manifest = prepare_qst(cfg, tmp_path, mode)
    persisted = attempt.read_manifest(path)
    assert persisted == manifest
    assert json.loads(json.dumps(manifest))['science']['qst_mode'] == f'QST{mode}'
    files = attempt.verified_files(cfg, path, persisted)
    assert files['water.gjf'] == source.read_bytes()
    assert next(r for r in manifest['inputs'] if r['name'] == 'water.gjf')['sha256'] == sha256(source.read_bytes()).hexdigest()
    summary = attempt.summary(cfg, manifest)
    for i in range(mode):
        assert f'Title: Water group {i + 1} | Atoms: 3' in summary
    assert summary.count(WATER) == mode
    assert 'Kabsch alignment' in summary
    assert 'Atom 1 (O): 0.00000000' in summary
    if mode == 3:
        assert 'Group 3 (TS guess)' in summary
    forged = deepcopy(manifest)
    forged['science']['structures'][-1]['title'] = 'Different title'
    with pytest.raises(ValueError, match='Scientific summary differs'):
        attempt.verified_files(cfg, path, forged)
    (path / 'inputs' / 'water.gjf').write_text(source.read_text().replace('Water group 2', 'Changed product'))
    with pytest.raises(ValueError, match='Input bundle differs'):
        attempt.verified_files(cfg, path, manifest)


def test_parent_relation_does_not_authorize_oldchk(cfg, tmp_path):
    source, path, parent = prepare_qst(cfg, tmp_path, 2)
    source.write_text('%oldchk=parent.chk\n' + INPUT)
    with pytest.raises(ValueError, match='parent chk attachment'):
        attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:05:00', label='child',
                        parents=[dict(attempt_id=parent['attempt_id'], relation='irc_of')])
    assert [p.name for p in path.parent.iterdir() if p.is_dir()] == [parent['attempt_id']]


@pytest.mark.parametrize('route', ['SP', 'Opt Freq', 'Opt=(TS,CalcFC,NoEigenTest)'])
def test_single_structure_return_format_unchanged(route):
    text = INPUT.replace(' SP', ' ' + route)
    assert validate(text) == dict(charge=0, multiplicity=1, route='# B3LYP/6-31G(d) ' + route,
                                 geometry=WATER, n_atoms=3,
                                 stereochemistry_warning='Review stereochemistry against the source structure.')


@pytest.mark.parametrize('text', [INPUT + 'Extra section\n', INPUT.replace('0 1', '+0 1'),
    INPUT.replace('O 0 0 0', 'O 0 0'), INPUT.replace('0 1', '0 0')])
def test_single_structure_rejections_unchanged(text):
    with pytest.raises(ValueError):
        validate(text)
