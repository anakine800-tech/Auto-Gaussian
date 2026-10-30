"""Synthetic water IRC logs and public small-molecule endpoint geometries."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from ag._irc import parse_irc
from ag.cli import main
from ag.facts import build_facts
from ag.geometry import Frame, write_xyz
from ag.irc_compare import MATCH, MISMATCH, UNKNOWN, compare, compare_endpoint, load_source


def orientation(x):
    return f''' Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        {x:.6f}    0.000000    0.000000
      2          1           0        0.960000    0.000000    0.000000
      3          1           0       -0.240000    0.930000    0.000000
 ---------------------------------------------------------------------
'''


def irc_log(ending='normal', direction='Forward'):
    limit = 2 if ending == 'maxpoints' else 20
    text = f''' #p HF/STO-3G IRC=({direction},MaxPoints={limit},CalcFC)
 ---------------------------------------------------------------------
 Charge = 0 Multiplicity = 1
 INPUT DATA FOR L123
 Maximum points per path = {limit}
'''
    for i in (1, 2):
        # Intermediate corrector SCFs must not inflate the point count.
        text += f' SCF Done: E(RHF) = -74.0 A.U.\n{orientation(i / 100)}'
        text += f' SCF Done: E(RHF) = -75.{i}D+00 A.U.\n'
        text += f' Delta-x Convergence Met\n Point Number: {i} Path Number: 1\n'
    if ending == 'failure':
        text += orientation(9) + ' SCF Done: E(RHF) = -74.5 A.U.\n'
        text += ' Maximum number of corrector steps exceded.\n Error termination\n'
    elif ending == 'truncated':
        text += orientation(9)
    else:
        text += f' Calculation of {direction.upper()} path complete.\n Normal termination of Gaussian\n'
    return text


@pytest.mark.parametrize('ending,reached,failed,complete', [
    ('normal', False, False, True), ('maxpoints', True, False, True),
    ('failure', False, True, False), ('truncated', False, False, False)])
def test_irc_reported_points(ending, reached, failed, complete):
    facts, geometry = parse_irc(irc_log(ending))
    assert facts['direction'] == 'forward'
    assert facts['point_count'] == 2
    assert facts['reached_max_points'] is reached
    assert facts['corrector_failed'] is failed
    assert facts['path_complete_reported'] is complete
    assert [point['energy_hartree'] for point in facts['energies']] == [-75.1, -75.2]
    assert '0.0200000000' in geometry and '9.0000000000' not in geometry


def test_reverse_maxpoints_unknown_and_transient_corrector():
    text = irc_log(direction='Reverse').replace('MaxPoints=20,', '').replace(' Maximum points per path = 20\n', '')
    text += ' Delta-x Convergence NOT Met\n Error in corrector energy = -0.0001\n'
    facts, _ = parse_irc(text)
    assert facts['direction'] == 'reverse'
    assert facts['reached_max_points'] is None
    assert facts['corrector_failed'] is False
    assert parse_irc(' Normal termination of Gaussian\n') == (None, None)


def test_two_paths_and_missing_point_geometry():
    text = irc_log().replace('Forward,', '')
    text += orientation(.03) + ' SCF Done: E(RHF) = -75.3 A.U.\n Point Number: 1 Path Number: 2\n'
    text += ' Calculation of REVERSE path complete.\n'
    facts, xyz = parse_irc(text)
    assert facts['direction'] == 'both' and facts['point_count'] == 3
    assert facts['end_geometry_warning'] and '0.0300000000' in xyz
    text += ' Point Number: 2 Path Number: 2\n'
    facts, xyz = parse_irc(text)
    assert xyz is None and facts['energies'][-1]['energy_hartree'] is None


def test_lqa_current_structure_and_wrapped_direction():
    text = irc_log().replace('Forward', 'Forwar\n d')
    text = text.replace(' INPUT DATA FOR L123', ' Rxn path following direction = Forward\n INPUT DATA FOR L123')
    current = orientation(.07).replace(' Standard orientation:', ' CURRENT STRUCTURE\n Cartesian Coordinates (Ang):')
    current = current.replace('           0       ', '                   ')
    text = text.replace(' Point Number: 2 Path Number: 1\n', ' Point Number: 2 Path Number: 1\n' + current)
    facts, xyz = parse_irc(text)
    assert facts['direction'] == 'forward' and '0.0700000000' in xyz


def test_link1_does_not_contaminate_irc_end():
    text = irc_log() + ' #p HF/STO-3G Opt\n --------------------------\n' + orientation(5)
    facts, xyz = parse_irc(text)
    assert facts['point_count'] == 2 and '0.0200000000' in xyz
    assert '5.0000000000' not in xyz


def irc_attempt(tmp_path):
    directory = tmp_path / 'water-irc'
    (directory / 'outputs').mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({'template': 'gaussian', 'inputs': [{'name': 'water.gjf'}]}))
    (directory / 'outputs/water.log').write_text(irc_log('failure'))
    return directory


def test_facts_reuses_identical_endpoint_and_regenerates_facts(tmp_path):
    directory = irc_attempt(tmp_path)
    facts = build_facts(directory)
    assert facts['termination'] == 'error'
    assert facts['irc']['corrector_failed'] is True
    assert facts['irc']['end_geometry'] == 'irc_end.xyz'
    assert facts['charge'] == 0 and facts['n_atoms'] == 3
    before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    endpoint = directory / 'irc_end.xyz'
    stat = endpoint.stat()
    (directory / 'facts.json').write_text('{"stale": true}')
    assert build_facts(directory, refresh=True) == facts
    assert (endpoint.stat().st_ino, endpoint.stat().st_mtime_ns) == (stat.st_ino, stat.st_mtime_ns)
    archive, = directory.glob('facts.*.json')
    assert archive.read_bytes() == b'{"stale": true}'
    assert before == {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file() and p != archive}


@pytest.mark.parametrize('change', ['endpoint', 'line_endings', 'log'])
def test_facts_rejects_endpoint_mismatch_without_updating_files(tmp_path, capsys, change):
    directory = irc_attempt(tmp_path)
    build_facts(directory)
    endpoint = directory / 'irc_end.xyz'
    if change == 'endpoint':
        endpoint.write_bytes(b'Existing reviewed geometry\n')
    elif change == 'line_endings':
        endpoint.write_bytes(endpoint.read_bytes().replace(b'\n', b'\r\n'))
    else:
        log = directory / 'outputs/water.log'
        log.write_text(log.read_text().replace('0.020000', '0.030000'))
    (directory / 'final.xyz').write_text('Existing final geometry\n')
    before = snapshot(directory)
    assert main(['facts', str(directory), '--json']) == 1
    assert 'irc_end.xyz 与当前日志解析结果不一致，需人工核对' in capsys.readouterr().err
    assert snapshot(directory) == before


@pytest.mark.parametrize('kind', ['symlink', 'dangling_symlink', 'directory'])
def test_facts_does_not_reuse_nonregular_endpoint(tmp_path, kind):
    directory = irc_attempt(tmp_path)
    endpoint = directory / 'irc_end.xyz'
    if kind == 'directory':
        endpoint.mkdir()
    else:
        target = tmp_path / 'target.xyz'
        if kind == 'symlink':
            target.write_text(parse_irc(irc_log('failure'))[1])
        endpoint.symlink_to(target)
    with pytest.raises(ValueError, match='必须是普通文件'):
        build_facts(directory)
    assert not (directory / 'facts.json').exists()
    assert not (directory / 'final.xyz').exists()
    if kind == 'symlink':
        assert target.read_text() == parse_irc(irc_log('failure'))[1]
    elif kind == 'dangling_symlink':
        assert not target.exists()


def test_generic_final_geometry_is_preserved(tmp_path, monkeypatch):
    from types import SimpleNamespace
    directory = tmp_path / 'attempt'
    (directory / 'outputs').mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({'template': 'gaussian', 'inputs': [{'name': 'water.gjf'}]}))
    (directory / 'outputs/water.log').write_text(irc_log() + ' --------------------------\n #p HF/STO-3G Opt\n --------------------------\n' + orientation(5))
    monkeypatch.setattr('cclib.io.ccread', lambda *args, **kwargs: SimpleNamespace(
        natom=3, atomnos=[8, 1, 1], atomcoords=[[[5, 0, 0], [.96, 0, 0], [-.24, .93, 0]]]))
    facts = build_facts(directory)
    assert '5.0000000000' in (directory / 'final.xyz').read_text()
    assert '0.0200000000' in (directory / 'irc_end.xyz').read_text()
    assert facts['irc']['point_count'] == 2
    assert build_facts(directory) == facts
    (directory / 'final.xyz').write_text('Stale final geometry\n')
    with pytest.raises(ValueError, match='final.xyz 与当前日志解析结果不一致'):
        build_facts(directory)
    assert (directory / 'final.xyz').read_text() == 'Stale final geometry\n'


def source(frame, *, kind='optimized', charge=0):
    return {'frame': frame, 'facts': {'charge': charge, 'multiplicity': 1},
            'source': 'synthetic', 'geometry_kind': kind, 'optimization_note': '未再优化' if kind == 'irc_endpoint' else '优化端点'}


def sn2():
    # Atom mapping: C, leaving Cl, incoming F, three methyl H atoms.
    symbols = ('C', 'Cl', 'F', 'H', 'H', 'H')
    r = Frame(symbols, ((0, 0, 0), (1.8, 0, 0), (-3.1, 0, 0),
                        (-.35, 1.03, 0), (-.35, -.51, .89), (-.35, -.51, -.89)))
    p = Frame(symbols, ((0, 0, 0), (3.3, 0, 0), (-1.4, 0, 0),
                        (.35, 1.03, 0), (.35, -.51, .89), (.35, -.51, -.89)))
    return source(r, charge=-1), source(p, charge=-1)


@pytest.mark.parametrize('swapped', [False, True])
def test_matching_endpoints_and_swapped_directions(swapped):
    r, p = sn2()
    f, rev = (p, r) if swapped else (r, p)
    result = compare(r, f, rev, r, p)
    assert result['status'] == MATCH
    assert result['assignment'] == {'forward': 'product' if swapped else 'reactant',
                                    'reverse': 'reactant' if swapped else 'product'}
    mismatch = result['comparisons']['forward']['reactant' if swapped else 'product']
    assert mismatch['status'] == MISMATCH
    assert {tuple(item['atoms']) for item in mismatch['bond_differences']} == {(1, 2), (1, 3)}
    assert all(item['endpoint_distance'] > 0 for item in mismatch['bond_differences'])
    changes = result['reaction_changes']['reference_reactant_to_product']['bond_differences']
    assert {(tuple(item['atoms']), item['change']) for item in changes} == {((1, 2), 'broken'), ((1, 3), 'formed')}


def test_both_ends_same_cannot_match_two_different_targets():
    r, p = sn2()
    result = compare(r, r, r, r, p)
    assert result['status'] == MISMATCH
    assert result['assignment'] is None


def test_stretched_bond_uncertain():
    r, p = sn2()
    coords = list(r['frame'].coordinates)
    coords[1] = (2.45, 0, 0)
    stretched = source(replace(r['frame'], coordinates=tuple(coords)), charge=-1)
    result = compare_endpoint(stretched, r, -1)
    assert result['status'] == UNKNOWN
    assert result['ambiguous_bonds'][0]['atoms'] == [1, 2]
    assert result['ambiguous_bonds'][0]['endpoint_distance'] == 2.45


def test_proton_ownership_is_mapped():
    # O-H ... O -> O ... H-O; one hydrogen keeps the same atom index.
    symbols = ('O', 'O', 'H')
    a = source(Frame(symbols, ((0, 0, 0), (4, 0, 0), (1, 0, 0))))
    b = source(Frame(symbols, ((0, 0, 0), (4, 0, 0), (3, 0, 0))))
    result = compare_endpoint(a, b, 0)
    assert result['status'] == MISMATCH
    assert result['proton_differences'] == [{'hydrogen': 3, 'endpoint_owners': [1], 'reference_owners': [2]}]


def test_stereo_flip_and_rotation():
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.AddHs(Chem.MolFromSmiles('F[C@](Cl)(Br)I'))
    assert AllChem.EmbedMolecule(mol, randomSeed=42) == 0
    frame = Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                  tuple(tuple(p) for p in mol.GetConformer().GetPositions()))
    rotated = replace(frame, coordinates=tuple((y + 3, -x, z + 7) for x, y, z in frame.coordinates))
    mirrored = replace(frame, coordinates=tuple((-x, y, z) for x, y, z in frame.coordinates))
    assert compare_endpoint(source(rotated), source(frame), 0)['status'] == MATCH
    result = compare_endpoint(source(mirrored), source(frame), 0)
    assert result['status'] == MISMATCH and result['stereo_differences'][0]['atom'] == 2


def test_element_electronic_state_and_fragment_translation():
    r, p = sn2()
    moved = replace(r['frame'], coordinates=tuple((x - 10 if i == 2 else x, y, z)
                                                  for i, (x, y, z) in enumerate(r['frame'].coordinates)))
    assert compare_endpoint(source(moved, charge=-1), r, -1)['status'] == MATCH
    wrong = source(replace(r['frame'], symbols=('N', *r['frame'].symbols[1:])), charge=-1)
    assert compare(wrong, r, p, r, p)['input_issues']
    wrong = source(r['frame'], charge=1)
    assert compare(wrong, r, p, r, p)['status'] == MISMATCH


def write_attempt(root, name, src, irc=False):
    directory = root / 'attempts' / name
    directory.mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({'template': 'gaussian'}))
    geometry = 'irc_end.xyz' if irc else 'final.xyz'
    facts = {**src['facts'], 'final_geometry': 'final.xyz', 'opt_converged': not irc}
    if irc:
        facts['irc'] = {'direction': 'forward' if name == 'forward' else 'reverse', 'end_geometry': geometry}
    (directory / 'facts.json').write_text(json.dumps(facts))
    write_xyz(directory / geometry, [src['frame']])
    return directory


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.usefixtures("synthetic_cwd")
def test_cli_only_creates_out_and_marks_unoptimized(tmp_path, capsys, monkeypatch):
    r, p = sn2()
    for name, src in [('ts', r), ('forward', r), ('reverse', p)]:
        write_attempt(tmp_path, name, src, irc=name != 'ts')
    write_xyz(tmp_path / 'r.xyz', [r['frame']])
    product = write_attempt(tmp_path, 'product', p)
    monkeypatch.setattr('ag.cli.load_config', lambda: pytest.fail('remote config loaded'))
    before = snapshot(tmp_path)
    out = tmp_path / 'report.json'
    args = ['irc-compare', '--ts', 'ts', '--forward', 'forward', '--reverse', 'reverse',
            '--reactant', str(tmp_path / 'r.xyz'), '--product', str(product),
            '--study', str(tmp_path), '--out', str(out), '--json']
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == MATCH
    assert report['sources']['forward']['optimization_note'] == '未再优化'
    after = snapshot(tmp_path)
    assert after.pop('report.json') == out.read_bytes()
    assert before == after
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)['exit_code'] == 1
    assert snapshot(tmp_path) == {**before, 'report.json': out.read_bytes()}


def test_cli_requires_out_and_rejects_symlink(tmp_path, capsys):
    args = ['irc-compare', '--ts', 'ts', '--forward', 'forward', '--reverse', 'reverse',
            '--reactant', 'r.xyz', '--product', 'p.xyz']
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    out = tmp_path / 'out.json'
    out.symlink_to(tmp_path / 'absent.json')
    assert main([*args, '--out', str(out)]) == 1
    assert not (tmp_path / 'absent.json').exists()


@pytest.mark.usefixtures("synthetic_cwd")
def test_configured_ids_use_only_local_studies_root(tmp_path, monkeypatch):
    r, _ = sn2()
    root = tmp_path / 'studies'
    directory = write_attempt(root / 'demo', 'demo-001-opt', r)
    config = tmp_path / '.config/ag'
    config.mkdir(parents=True)
    (config / 'config.toml').write_text('[local]\nstudies_root = ' + json.dumps(str(root)) + '\n')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    assert load_source('demo-001-opt')['frame'].symbols == r['frame'].symbols
    assert load_source(str(directory))['optimization_note'].startswith('已报告优化收敛')


def test_missing_facts_not_generated_and_multiframe_rejected(tmp_path):
    path = tmp_path / 'attempt'
    path.mkdir()
    (path / 'manifest.json').write_text('{}')
    before = snapshot(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_source(str(path))
    assert snapshot(tmp_path) == before
    r, p = sn2()
    write_xyz(tmp_path / 'multi.xyz', [r['frame'], p['frame']])
    with pytest.raises(ValueError, match='exactly one'):
        load_source(str(tmp_path / 'multi.xyz'), allow_xyz=True)


def test_missing_charge_does_not_invent_a_graph():
    r, _ = sn2()
    assert compare_endpoint(r, r, None)['status'] == UNKNOWN


def test_point_data_keeps_accepted_current_geometry_and_absolute_lines():
    from ag._irc import parse_irc_points
    current = orientation(.07).replace(' Standard orientation:', ' CURRENT STRUCTURE\n Cartesian Coordinates (Ang):')
    current = current.replace('           0       ', '                   ')
    text = 'preamble\n' + irc_log('failure').replace(' Point Number: 2 Path Number: 1\n',
                                                   ' Point Number: 2 Path Number: 1\n' + current)
    parsed = parse_irc_points(text)
    assert [p['point'] for p in parsed['points']] == [1, 2]
    last = parsed['points'][-1]
    assert last['energy_hartree'] == -75.2
    assert '0.0700000000' in last['geometry'] and '9.0000000000' not in last['geometry']
    assert 'CURRENT STRUCTURE' in text.splitlines()[last['geometry_line'] - 1]
    assert 'SCF Done:' in text.splitlines()[last['energy_line'] - 1]


def test_point_zero_checkpoint_and_no_borrowing():
    from ag._irc import parse_irc_points
    text = irc_log().replace(' Charge =', ' Energy From Chk = -75.0\n Point Number: 0 Path Number: 1\n Charge =')
    text += ' Point Number: 3 Path Number: 1\n'
    data = parse_irc_points(text)
    assert data['points'][0]['energy_hartree'] == -75
    assert data['points'][0]['energy_kind'] == 'scf_from_checkpoint'
    assert data['points'][-1]['energy_hartree'] is None and data['points'][-1]['geometry'] is None
    assert parse_irc_points('not an IRC') is None


def test_point_parser_link1_isolation_and_duplicates():
    from ag._irc import parse_irc_points
    text = irc_log() + ' #p HF/STO-3G Opt\n --------------------------\n' + orientation(5)
    data = parse_irc_points(text)
    assert len(data['points']) == 2 and '0.0200000000' in data['points'][-1]['geometry']
    with pytest.raises(ValueError, match='Duplicate accepted'):
        parse_irc_points(irc_log() + ' Point Number: 2 Path Number: 1\n')


def test_truncated_accepted_table_cannot_consume_next_accepted_geometry():
    from ag._irc import parse_irc_points
    current = orientation(.07).replace(' Standard orientation:', ' CURRENT STRUCTURE\n Cartesian Coordinates (Ang):')
    current = current.replace('           0       ', '                   ')
    text = (' #p HF/STO-3G IRC=(Forward,CalcFC)\n --------------------\n'
            ' SCF Done: E(RHF) = -75.0 A.U.\n Point Number: 1 Path Number: 1\n'
            ' CURRENT STRUCTURE\n Cartesian Coordinates (Ang):\n --------------------\n header cut\n'
            ' SCF Done: E(RHF) = -75.1 A.U.\n Point Number: 2 Path Number: 1\n' + current)
    points = parse_irc_points(text)['points']
    assert points[0]['geometry'] is None
    assert '0.0700000000' in points[1]['geometry']
