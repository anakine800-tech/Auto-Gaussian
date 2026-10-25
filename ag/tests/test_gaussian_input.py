"""T13-1 Cartesian QST validation; synthetic geometries, no Gaussian execution."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

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
    ('0 1', WATER + '\nH 1 0 0\nH -1 0 0', 'n_atoms'),
    ('0 1', 'H 0 0 0\nO 0 0 1\nH 0 1 0', 'elements'),
    ('-2 1', WATER, 'charge'), ('0 3', WATER, 'multiplicity'),
    ('0 0', WATER, 'charge/multiplicity'),
    ('0 1', '', 'coordinates'),
    ('0 1', WATER.replace('O 0', 'O nan'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O inf'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O 1e999'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O 0 0'), 'finite Cartesian'),
    ('0 1', WATER.replace('O 0', 'O(Fragment=1) 0'), 'atom-label syntax'),
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
        result = validate(qst(blocks=[('Reactant', '0 2', geometry), ('Product', '0 2', changed)]))
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


# T83: invalid preparation must fail before allocating an Attempt or sequence.
BAD_ATOMS = [
    ('O 1e999 0 0', 'finite Cartesian'),
    ('O inf 0 0', 'finite Cartesian'),
    ('O nan 0 0', 'finite Cartesian'),
    ('O -inf 0 0', 'finite Cartesian'),
    ('Qq 0 0 0', 'real element'),
    ('0 0 0 0', 'atomic number 1–118'),
    ('119 0 0 0', 'atomic number 1–118'),
    ('Bq 0 0 0', 'Dummy atoms'),
    ('X 0 0 0', 'Dummy atoms'),
    ('O(Iso=18) 0 0 0', 'isotope'),
    ('18O 0 0 0', 'isotope'),
    ('D 0 0 0', 'isotope'),
    ('T 0 0 0', 'isotope'),
]


@pytest.mark.parametrize('atom,error', BAD_ATOMS)
@pytest.mark.parametrize('ending', ['\n', '\r\n'])
def test_invalid_single_atoms_report_original_line(atom, error, ending):
    text = INPUT.replace('O 0 0 0', atom).replace('\n', ending)
    with pytest.raises(ValueError, match=f'line 9: .*{error}'):
        validate(text)


@pytest.mark.parametrize('state,geometry,electrons,multiplicity', [
    ('0 2', WATER, 10, 2),
    ('0 1', 'H 0 0 0', 1, 1),
    ('-1 1', WATER, 11, 1),
    ('1 1', WATER, 9, 1),
    ('11 2', WATER, -1, 2),
])
def test_electron_errors_report_charge_line_and_values(state, geometry, electrons, multiplicity):
    text = INPUT.replace('0 1\n' + WATER, state + '\n' + geometry)
    with pytest.raises(ValueError) as caught:
        validate(text)
    message = str(caught.value)
    assert 'line 8:' in message
    assert f'electron count {electrons}' in message
    assert f'multiplicity {multiplicity}' in message
    assert ('negative' if electrons < 0 else 'parity') in message


@pytest.mark.parametrize('state', ['-1 2', '1 2', '2 1', '10 1', '0 99'])
def test_charge_is_subtracted_and_only_spin_parity_is_checked(state):
    result = validate(INPUT.replace('0 1\n' + WATER, state + '\n' + WATER))
    assert (result['charge'], result['multiplicity']) == tuple(map(int, state.split()))


@pytest.mark.parametrize('number,symbol', [
    (1, 'H'), (8, 'O'), (17, 'Cl'), (26, 'Fe'), (54, 'Xe'),
    (79, 'Au'), (92, 'U'), (117, 'Ts'), (118, 'Og'),
])
def test_real_elements_and_atomic_numbers_across_periodic_table(number, symbol):
    multiplicity = 1 if number % 2 == 0 else 2
    for atom in (str(number), symbol, symbol.lower(), symbol.upper()):
        geometry = f'{atom} 0 0 0'
        result = validate(INPUT.replace('0 1\n' + WATER, f'0 {multiplicity}\n' + geometry))
        assert result['geometry'] == geometry
        assert result['n_atoms'] == 1


@pytest.mark.parametrize('mode,position', [(2, 0), (2, 1), (3, 0), (3, 1), (3, 2)])
@pytest.mark.parametrize('atom,error', BAD_ATOMS)
def test_every_qst_structure_checks_atoms_with_absolute_lines(mode, position, atom, error):
    blocks = [(f'Water {i}\nmultiline title', '0 1', WATER) for i in range(mode)]
    blocks[position] = (f'Water {position}\nmultiline title', '0 1', WATER.replace('O 0 0 0', atom))
    text = qst(mode, blocks=blocks).replace('\n\n', '\n \n\n').replace('\n', '\r\n')
    line = text.splitlines().index(atom) + 1
    with pytest.raises(ValueError, match=f'QST{mode} group {position + 1}: line {line}: .*{error}'):
        validate(text)


@pytest.mark.parametrize('position', [0, 1, 2])
@pytest.mark.parametrize('state,electrons,multiplicity', [('0 2', 10, 2), ('-1 1', 11, 1), ('11 1', -1, 1)])
def test_every_qst_structure_checks_electrons_before_cross_group_comparison(position, state, electrons, multiplicity):
    blocks = [(f'Water {i}', '0 1', WATER) for i in range(3)]
    blocks[position] = (f'Water {position}', state, WATER)
    text = qst(3, blocks=blocks)
    line = text.splitlines().index(state) + 1
    with pytest.raises(ValueError) as caught:
        validate(text)
    assert f'QST3 group {position + 1}: line {line}:' in str(caught.value)
    assert f'electron count {electrons}' in str(caught.value)
    assert f'multiplicity {multiplicity}' in str(caught.value)


@pytest.mark.parametrize('template', ['gaussian', 'xtb', 'crest', 'mdopt'])
@pytest.mark.parametrize('atom,error', BAD_ATOMS)
def test_prepare_invalid_geometry_allocates_nothing(cfg, tmp_path, template, atom, error):
    # Use the real local prepare path and a synthetic configuration, never SSH.
    study.init(cfg, 'smoke')
    attempts = Path(cfg['local']['studies_root']) / 'smoke' / 'attempts'
    params = {'--mdopt': ''} if template == 'mdopt' else {}
    program = 'crest' if template == 'mdopt' else template
    geometry = WATER.replace('O 0 0 0', atom)
    source = tmp_path / ('water.gjf' if template == 'gaussian' else 'water.xyz')
    contents = (INPUT.replace(WATER, geometry) if template == 'gaussian'
                else '3\nSynthetic water\n' + geometry + '\n')
    if template == 'mdopt':
        contents = '3\nSynthetic water\n' + WATER + '\n\n' + contents
    source.write_text(contents)
    line = contents.splitlines().index(atom) + 1
    with pytest.raises(ValueError, match=f'line {line}: .*{error}'):
        attempt.prepare(cfg, study_name='smoke', template=program, input_path=source,
                        tier='simple', walltime='00:05:00', label='invalid', params=params,
                        method_basis='兜底方法：合成测试')
    assert list(attempts.iterdir()) == []


@pytest.mark.parametrize('template', ['xtb', 'crest'])
def test_valid_xyz_summary_and_input_bytes_unchanged(cfg, tmp_path, template):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.xyz'
    data = ('3\r\nSynthetic water\r\n' + WATER.replace('\n', '\r\n') + '\r\n').encode()
    source.write_bytes(data)
    manifest = attempt.prepare(cfg, study_name='smoke', template=template, input_path=source,
                               tier='simple', walltime='00:05:00', label='valid',
                               method_basis='兜底方法：合成测试')
    assert manifest['science'] == dict(charge=0, multiplicity=1, route='', geometry=WATER, n_atoms=3,
        stereochemistry_warning='Review stereochemistry against the source structure.',
        method_basis='兜底方法：合成测试')
    path = attempt.find(cfg, manifest['attempt_id'])
    assert attempt.verified_files(cfg, path, manifest)['water.xyz'] == data


@pytest.mark.parametrize('template', ['gaussian', 'xtb', 'crest'])
def test_prepare_spin_mismatch_allocates_nothing(cfg, tmp_path, template):
    study.init(cfg, 'smoke')
    source = tmp_path / ('water.gjf' if template == 'gaussian' else 'water.xyz')
    source.write_text(INPUT.replace('0 1\n' + WATER, '0 2\n' + WATER)
                      if template == 'gaussian' else '3\nWater\n' + WATER + '\n')
    with pytest.raises(ValueError, match='electron count 10 and multiplicity 2'):
        attempt.prepare(cfg, study_name='smoke', template=template, input_path=source,
                        tier='simple', walltime='00:05:00', label='invalid',
                        params={} if template == 'gaussian' else {'--uhf': '1'},
                        method_basis='兜底方法：合成测试')
    assert list((Path(cfg['local']['studies_root']) / 'smoke' / 'attempts').iterdir()) == []


def test_legacy_invalid_prepared_input_is_only_rechecked_when_verifying(cfg, tmp_path, monkeypatch):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace('O 0 0 0', 'O 1e999 0 0'))
    previous_science = validate(INPUT)
    previous_science['geometry'] = WATER.replace('O 0 0 0', 'O 1e999 0 0')
    # Emulate the old permissive parser only while creating a legacy fixture.
    with monkeypatch.context() as patch:
        patch.setattr(gaussian_input, 'validate', lambda *args, **kwargs: previous_science)
        manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                                   tier='simple', walltime='00:05:00', label='legacy',
                                   method_basis='兜底方法：合成测试')
    path = attempt.find(cfg, manifest['attempt_id'])
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()}
    assert attempt.read_manifest(path) == manifest
    with pytest.raises(ValueError, match='line 9: .*finite Cartesian'):
        attempt.verified_files(cfg, path, manifest)
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()} == before


# T133: render bodies for both scan TS guesses and future QST callers.
WATER_SECTION = (0, 1, ['O', 'H', 'H'], [(0, 0, 0), (0, 0, 1), (0, 1, 0)])


@pytest.mark.parametrize('count', [1, 2, 3])
def test_render_input_body_and_qst(count):
    route = '# HF/STO-3G Opt=' + ('TS' if count == 1 else f'(QST{count},CalcFC)')
    body = gaussian_input.render_input(route, 'Synthetic water', [WATER_SECTION] * count)
    assert body.startswith(route + '\n\n') and body.endswith('\n\n')
    assert '%' not in body and body.count('Synthetic water') == count
    result = validate('%nprocshared=8\n%mem=10GB\n' + body)
    assert result['charge'] == 0 and result['multiplicity'] == 1 and result['n_atoms'] == 3
    if count > 1:
        assert len(result['structures']) == count and result['qst_mode'] == f'QST{count}'
        assert result['structures'][0]['elements'] == WATER_SECTION[2]
        assert [s['title'] for s in result['structures']] == ['Synthetic water'] * count


@pytest.mark.parametrize('titles', [['Reactant', 'Product'], ('Reactant', 'Product', 'TS guess')])
def test_render_input_individual_titles(titles):
    route = f'# HF/STO-3G Opt=QST{len(titles)}'
    body = gaussian_input.render_input(route, titles, iter([WATER_SECTION] * len(titles)))
    result = validate('%nprocshared=8\n%mem=10GB\n' + body)
    assert [s['title'] for s in result['structures']] == list(titles)
    assert body.endswith('\n\n') and '%' not in body


@pytest.mark.parametrize('titles', [[], ['Only reactant'], ['Reactant', 'Product', 'Extra']])
def test_render_input_title_count_must_match(titles):
    with pytest.raises(ValueError, match='title sequence length'):
        gaussian_input.render_input('# HF/STO-3G Opt=QST2', titles, [WATER_SECTION] * 2)


@pytest.mark.parametrize('bad', ['', '  ', 'First\nSecond', 'Title\n', '\nTitle',
                                 'First\rSecond', 'Title\r\n', 'First\u2028Second'])
@pytest.mark.parametrize('sequence', [False, True])
def test_render_input_titles_reject_empty_or_line_breaks(bad, sequence):
    with pytest.raises(ValueError, match='title must be nonempty and contain no line breaks'):
        gaussian_input.render_input('# HF/STO-3G Opt=QST2', ['Reactant', bad] if sequence else bad,
                                    [WATER_SECTION] * 2)


@pytest.mark.parametrize('route,title,sections,error', [
    ('# HF/STO-3G', '', [WATER_SECTION], 'title'),
    ('# HF/STO-3G', 'title\n\n0 1', [WATER_SECTION], 'title'),
    ('# HF/STO-3G\n\nextra', 'title', [WATER_SECTION], 'route'),
    ('%chk=extra.chk\n# HF/STO-3G', 'title', [WATER_SECTION], 'Link0'),
    ('# HF/STO-3G\n%chk=extra.chk', 'title', [WATER_SECTION], 'Link0'),
    ('# HF/STO-3G', 'title', [], 'Expected route'),
    ('# HF/STO-3G', 'title', [(0, 1, ['H'], [])], 'matching'),
    ('# HF/STO-3G', 'title', [(0, 2, ['H'], [(0, 1)])], 'three Cartesian'),
    ('# HF/STO-3G', 'title', [(0, 2, ['H'], [(float('nan'), 0, 0)])], 'finite Cartesian'),
    ('# HF/STO-3G', 'title', [(0, 1, ['Bq'], [(0, 0, 0)])], 'real element'),
    ('# HF/STO-3G', 'title', [(0, 1, ['H'], [(0, 0, 0)])], 'parity'),
    ('# HF/STO-3G', 'title', [(False, 1, ['He'], [(0, 0, 0)])], 'integer'),
    ('# HF/STO-3G', 'title', [(0, 0, ['He'], [(0, 0, 0)])], 'positive'),
    ('# HF/STO-3G Geom=AllCheck', 'title', [WATER_SECTION], 'Geom=Check'),
    ('# HF/STO-3G External=program', 'title', [WATER_SECTION], 'External'),
    ('# HF/STO-3G', 'title --Link1--', [WATER_SECTION], 'Link1'),
    ('# HF/STO-3G Opt=QST2', 'title', [WATER_SECTION], 'exactly 2'),
])
def test_render_input_validates_sections(route, title, sections, error):
    with pytest.raises(ValueError, match=error):
        gaussian_input.render_input(route, title, sections)


@pytest.mark.parametrize('option', ['opt=ts', 'OPT=(TS, CALCFC)', 'Opt ( CalcFC, tS )',
                                  'opt = ts', 'Opt=(TS,\nNoEigenTest,MaxCycles=100)'])
def test_ts_route_forms_and_scientific_choices(option):
    # No method/basis whitelist, and no requirement to choose CalcFC/NoEigenTest.
    assert gaussian_input.ts_route_check('# ArbitraryMethod/ArbitraryBasis ' + option) is None


@pytest.mark.parametrize('option', ['SP', 'TS Opt=CalcFC', 'Opt=NotTS', 'Opt=(TSBad)',
                                  'Opt=(MaxCycle=TS)', 'Opt=(MaxCycle = TS)', 'Opt=(TS=No)',
                                  'Opt=(TS', 'Opt=QST2'])
def test_ts_route_requires_an_actual_ts_option(option):
    with pytest.raises(ValueError, match='requires Opt=TS'):
        gaussian_input.ts_route_check('# HF/STO-3G ' + option)


@pytest.mark.parametrize('keyword', [
    'ModRedundant', 'ModRedun', 'ModRed', 'AddRedundant', 'AddRedun', 'AddRed', 'Scan',
    'ReadOptimize', 'ReadOpt', 'RdOpt', 'ReadFreeze', 'RdFreeze', 'Freeze', 'FreezeAll',
    'AddGIC', 'ReadGIC', 'ReadAllGIC',
])
@pytest.mark.parametrize('form', ['Opt=(TS,{k})', 'Opt=TS Geom={k}', 'Opt=TS {k}'])
def test_ts_route_rejects_scan_freeze_keywords(keyword, form):
    with pytest.raises(ValueError, match='scan/freeze'):
        gaussian_input.ts_route_check('# HF/STO-3G ' + form.format(k=keyword.swapcase()))


@pytest.mark.parametrize('keyword', ['RCFC', 'ReadFC', 'ReadCartesianFC'])
def test_ts_route_requires_parent_chk_for_read_force_constants(keyword):
    with pytest.raises(ValueError, match='prepare --parent-chk'):
        gaussian_input.ts_route_check(f'# HF/STO-3G Opt=(TS,{keyword.lower()})')
