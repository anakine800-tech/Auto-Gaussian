"""Synthetic small molecules only; diagnostics never submit or modify evidence."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolTransforms

from ag import cli, geometry as geo, scan_path, scan_peak
from test_catalog import files, make_attempt, write_json
from test_scan_peak_ts_input import make_scan, object_entry, candidate_options


def butane(angles):
    mol = Chem.AddHs(Chem.MolFromSmiles('CCCC'))
    assert AllChem.EmbedMolecule(mol, randomSeed=136) == 0
    AllChem.MMFFOptimizeMolecule(mol)
    frames = []
    for angle in angles:
        rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, 3, angle)
        frames.append(geo.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                                tuple(tuple(p) for p in mol.GetConformer().GetPositions())))
    return frames


def scan_for(frames, *, kind='B', atoms=(1, 2), energies=None):
    energies = energies if energies is not None else [-10 + .001 * i for i in range(len(frames))]
    return dict(coordinate=dict(kind=kind, atoms=list(atoms), unit='degree' if kind == 'D' else 'angstrom'),
                geometries='scan_points.xyz', points=[dict(point=i + 1, coordinate_value=float(i),
                    converged=True, energy_hartree=energies[i], geometry_frame=i + 1)
                    for i in range(len(frames))])


def save_scan(tmp_path, frames, scan, charge=0):
    root = tmp_path / 'synthetic-scan'
    (root / 'attempts').mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic local scan\n')
    identity = make_attempt(root, '001-scan', template='xtb', charge=charge, multiplicity=1)
    path = root / 'attempts' / identity
    data = geo.xyz_text(frames).encode()
    (path / 'scan_points.xyz').write_bytes(data)
    scan = dict(scan, geometries_sha256=sha256(data).hexdigest())
    write_json(path / 'facts.json', dict(scan=scan))
    return path


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    from ag import attempt, catalog
    from ag.transport import SSHTransport
    def forbidden(*args, **kwargs):
        pytest.fail('Path diagnostics must not load credentials, prepare or contact remote systems')
    monkeypatch.setattr(cli, 'load_config', forbidden)
    monkeypatch.setattr(catalog, 'load_config', forbidden)
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(attempt, 'prepare', forbidden)


def test_clean_dihedral_scan_and_central_bond_exemption():
    frames = butane([170, 180, -170])
    report = scan_path.diagnose(scan_for(frames, kind='D', atoms=(1, 2, 3, 4)), frames, 0)
    assert [s['status'] for s in report['segments']] == ['clean', 'clean']
    assert all(not s['dihedral_changes'] for s in report['segments'])
    # A large torsion is still excluded even if another warning (RMSD/contact) occurs.
    frames = butane([60, 180])
    report = scan_path.diagnose(scan_for(frames, kind='D', atoms=(4, 3, 2, 1)), frames, 0)
    assert not report['segments'][0]['dihedral_changes']


def test_sidechain_jump_and_peak_warning_first_line(tmp_path, capsys):
    frames = butane([60, 60, 180, 180, 180])
    scan = scan_for(frames, energies=[-10, -9.999, -9.998, -9.999, -10])
    report = scan_path.diagnose(scan, frames, 0)
    jump = report['segments'][1]
    assert jump['status'] == 'flagged'
    assert jump['dihedral_changes'][0]['bond'] == [2, 3]
    assert jump['dihedral_changes'][0]['atoms'] == [1, 2, 3, 4]
    assert jump['dihedral_changes'][0]['change_degrees'] == pytest.approx(120)
    path = save_scan(tmp_path, frames, scan)
    before = files(path)
    out = tmp_path / 'peak.xyz'
    assert cli.main(['scan-peak', str(path), '--out', str(out)]) == 0
    output = capsys.readouterr().out
    assert output.startswith('!!! 峰可能被构象跳变或成键变化污染 / Peak may be contaminated')
    assert '2→3' in output.splitlines()[0]
    assert geo.read_xyz(out)[0].coordinates == geo.read_xyz(path / 'scan_points.xyz')[2].coordinates
    assert files(path) == before


def test_periodic_difference_and_thresholds():
    frames = butane([170, -170])
    scan = scan_for(frames)
    assert not scan_path.diagnose(scan, frames, 0)['segments'][0]['dihedral_changes']
    report = scan_path.diagnose(scan, frames, 0, dihedral_threshold=15, contact_cutoff=4, hbond_cutoff=3)
    assert report['segments'][0]['dihedral_changes'][0]['change_degrees'] == pytest.approx(20)
    assert report['thresholds'] == dict(dihedral_degrees=15, contact_angstrom=4, hbond_angstrom=3,
                                      energy_kcal_mol=20, rmsd_angstrom=.5)
    frames = butane([60, 100])
    assert scan_path.diagnose(scan, frames, 0, dihedral_threshold=30)['segments'][0]['dihedral_changes']
    assert not scan_path.diagnose(scan, frames, 0)['segments'][0]['dihedral_changes']


def proton_transfer():
    # Two waters plus a shared proton, with an independent C-C scan coordinate.
    ethane = Chem.AddHs(Chem.MolFromSmiles('CC'))
    assert AllChem.EmbedMolecule(ethane, randomSeed=136) == 0
    AllChem.MMFFOptimizeMolecule(ethane)
    fragment = tuple((x + 12, y, z) for x, y, z in ethane.GetConformer().GetPositions())
    symbols = ('O', 'O', 'H', 'H', 'H', 'H', 'H') + tuple(a.GetSymbol() for a in ethane.GetAtoms())
    coords = ((0, 0, 0), (3.2, 0, 0), (.98, 0, 0), (-.4, .8, 0), (-.4, -.8, 0),
              (3.6, .8, 0), (3.6, -.8, 0)) + fragment
    left = geo.Frame(symbols, coords)
    right = replace(left, coordinates=coords[:2] + ((2.22, 0, 0),) + coords[3:])
    return [left, right]


def test_proton_transfer_expected_and_uncertain():
    frames = proton_transfer()
    scan = scan_for(frames, atoms=(8, 9))
    report = scan_path.diagnose(scan, frames, None)
    segment = report['segments'][0]
    assert segment['status'] == 'flagged'
    assert [row['atoms'] for row in segment['bond_changes']] == [[1, 3], [2, 3]]
    assert [(row['before_state'], row['after_state']) for row in segment['bond_changes']] == [
        ('bonded', 'separated'), ('separated', 'bonded')]
    report = scan_path.diagnose(scan, frames, None, expected_bonds=[(3, 1), (2, 3)])
    assert not report['segments'][0]['bond_changes']
    assert report['segments'][0]['status'] == 'unknown'  # missing charge is not clean
    assert report['expected_bonds'] == dict(automatic=[[8, 9]], declared=[[1, 3], [2, 3]])
    # At the covalent-radius uncertainty band, do not turn it into a change/agreement.
    middle = replace(frames[0], coordinates=frames[0].coordinates[:2] + ((1.3, 0, 0),) +
                     frames[0].coordinates[3:])
    segment = scan_path.diagnose(scan, [frames[0], middle], None)['segments'][0]
    assert any(row['atoms'] == [1, 3] for row in segment['uncertain_pairs'])
    assert not segment['bond_changes'] and segment['status'] == 'unknown'
    assert not segment['contact_changes']  # donor uncertainty is not a cutoff crossing


def test_uncertainty_alone_does_not_flag():
    # Explicit synthetic H-H pair in the uncertainty band; H2 inference succeeds.
    hydrogen = geo.Frame(('H', 'H'), ((0, 0, 0), (.8, 0, 0)))
    report = scan_path.diagnose(scan_for([hydrogen, hydrogen]), [hydrogen, hydrogen], 0)
    assert report['segments'][0]['uncertain_pairs']
    assert report['segments'][0]['status'] == 'clean'


def test_automatic_bond_exemption_and_bonded_contact_exclusion():
    frames = [geo.Frame(('C', 'C'), ((0, 0, 0), (distance, 0, 0))) for distance in (1.5, 2.4)]
    segment = scan_path.diagnose(scan_for(frames), frames, None)['segments'][0]
    assert not segment['bond_changes'] and not segment['contact_changes']
    assert segment['rmsd_angstrom'] < .5


def waters(distance):
    return geo.Frame(('O', 'H', 'H', 'O', 'H', 'H'),
        ((0, 0, 0), (.96, 0, 0), (-.3, .9, 0), (distance, 0, 0),
         (distance + .3, .9, 0), (distance + .3, -.9, 0)))


@pytest.mark.parametrize('reverse', [False, True])
def test_heavy_and_hbond_contacts_and_cutoffs(reverse):
    frames = [waters(3.8), waters(3.3)][::(-1 if reverse else 1)]
    scan = scan_for(frames, atoms=(1, 2))
    changes = scan_path.diagnose(scan, frames, 0)['segments'][0]['contact_changes']
    assert [(c['kind'], c['atoms']) for c in changes] == [('heavy', [1, 4]), ('hbond', [2, 4])]
    assert all(c['change'] == ('disappeared' if reverse else 'appeared') for c in changes)
    assert all(c['before_distance'] != c['after_distance'] for c in changes)
    changes = scan_path.diagnose(scan, frames, 0, contact_cutoff=4, hbond_cutoff=3)['segments'][0]['contact_changes']
    assert changes == []


@pytest.mark.parametrize('damage', ['unconverged', 'no_geometry', 'bad_frame'])
def test_gaps_never_bridge(damage):
    frames = butane([60, 120, 180])
    scan = scan_for(frames)
    if damage == 'unconverged':
        scan['points'][1]['converged'] = False
    else:
        scan['points'][1]['geometry_frame'] = None if damage == 'no_geometry' else 99
    report = scan_path.diagnose(scan, frames, 0)
    assert report['summary'] == dict(flagged_count=0, flagged_segments=[], unknown_count=2,
                                   unknown_segments=[[1, 2], [2, 3]])
    assert all(s['unknown_reason'] and s['rmsd_angstrom'] is None and
               not s['dihedral_changes'] for s in report['segments'])


def test_metrics_shared_and_not_recomputed(monkeypatch):
    frames = butane([60, 60, 180, 180, 180])
    scan = scan_for(frames, energies=[-10, -9.96, -9.95, -9.96, -10])
    values = []
    peak, _ = scan_peak.select_peak(scan, frames, path_metrics=values)
    def forbidden(*args, **kwargs):
        pytest.fail('scan-path must reuse the metrics already computed by select_peak')
    monkeypatch.setattr(scan_peak, 'step_metrics', forbidden)
    report = scan_path.diagnose(scan, frames, 0, metrics=values)
    for jump in peak['jumps']:
        segment = report['segments'][jump['points'][0] - 1]
        assert segment['energy_change_kcal_mol'] == jump['energy_change_kcal_mol']
        assert segment['rmsd_angstrom'] == jump['rmsd_angstrom']
        assert segment['status'] == 'flagged'


@pytest.mark.parametrize('charge', [None, 0])
def test_failed_inference_is_unknown_not_export_failure(tmp_path, capsys, monkeypatch, charge):
    frames = butane([60, 60, 60])
    scan = scan_for(frames, energies=[-10, -9.999, -10])
    def fail(*args):
        raise ValueError('synthetic ambiguous valence')
    monkeypatch.setattr(geo, 'infer_molecule', fail)
    report = scan_path.diagnose(scan, frames, charge)
    assert all(s['status'] == 'unknown' and s['unknown_reason'] for s in report['segments'])
    path = save_scan(tmp_path, frames, scan)
    assert cli.main(['scan-peak', str(path), '--out', str(tmp_path / 'guess.xyz'), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['path_diagnostics']['summary']['unknown_count'] == 2


def test_ring_double_terminal_bonds_not_rotatable(monkeypatch):
    def forbidden(*args):
        pytest.fail('Ring, double and terminal bonds must not be measured as rotatable torsions')
    monkeypatch.setattr(geo, 'dihedral', forbidden)
    for smiles in ('C1CCCCC1', 'CC=CC', 'CC'):
        mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
        assert AllChem.EmbedMolecule(mol, randomSeed=136) == 0
        frame = geo.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                          tuple(tuple(p) for p in mol.GetConformer().GetPositions()))
        changes, unknown = scan_path.torsions(frame, frame, 0, dict(kind='B', atoms=[1, 2]), .01)
        assert changes == [] and unknown == []


def test_cli_readonly_options_and_hash(tmp_path, capsys):
    frames = proton_transfer()
    path = save_scan(tmp_path, frames, scan_for(frames, atoms=(8, 9)))
    before = files(path)
    assert cli.main(['scan-path', str(path), '--expect-bond', '1-3', '--expect-bond', '3-2',
                     '--dihedral-threshold', '30', '--contact-cutoff', '4', '--hbond-cutoff', '3', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['expected_bonds']['declared'] == [[1, 3], [2, 3]]
    assert report['thresholds']['dihedral_degrees'] == 30
    assert not report['segments'][0]['bond_changes']
    assert files(path) == before
    assert cli.main(['scan-path', str(path)]) == 0
    output = capsys.readouterr().out
    assert 'segment | status' in output and '非驻点' in output and '不是科学判据' in output
    (path / 'scan_points.xyz').write_bytes(b'changed')
    assert cli.main(['scan-path', str(path), '--json']) == 1
    assert 'differs from facts.json' in json.loads(capsys.readouterr().out)['error']


def test_peak_expect_bond_uses_same_report(tmp_path, capsys):
    frames = proton_transfer()
    frames.append(frames[-1])
    scan = scan_for(frames, atoms=(8, 9), energies=[-10, -9.999, -10])
    path = save_scan(tmp_path, frames, scan, charge=1)
    options = ['--expect-bond', '1-3', '--expect-bond', '2-3', '--dihedral-threshold', '30']
    assert cli.main(['scan-path', str(path), '--json', *options]) == 0
    full = json.loads(capsys.readouterr().out)
    assert cli.main(['scan-peak', str(path), '--json', '--out', str(tmp_path / 'peak.xyz'), *options]) == 0
    near = json.loads(capsys.readouterr().out)['path_diagnostics']
    assert near == scan_path.near_peak(full, 2)
    assert not any(s['bond_changes'] for s in near['segments'])


def test_missing_rdkit_preserves_export(tmp_path, capsys, monkeypatch):
    import builtins
    frames = butane([60, 60, 60])
    path = save_scan(tmp_path, frames, scan_for(frames, energies=[-10, -9.999, -10]))
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == 'rdkit':
            raise ImportError('synthetic unavailable dependency')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', unavailable)
    assert cli.main(['scan-peak', str(path), '--out', str(tmp_path / 'peak.xyz'), '--json']) == 0
    report = json.loads(capsys.readouterr().out)['path_diagnostics']
    assert report['summary']['unknown_count'] == 2
    assert 'RDKit' in report['segments'][0]['unknown_reason'][0]


@pytest.mark.parametrize('option,value', [('dihedral-threshold', 'nan'), ('dihedral-threshold', '181'),
    ('contact-cutoff', '0'), ('hbond-cutoff', '-1'), ('hbond-cutoff', 'inf'), ('expect-bond', '1-99')])
def test_bad_reporting_options(tmp_path, capsys, option, value):
    frames = butane([60, 60, 60])
    path = save_scan(tmp_path, frames, scan_for(frames, energies=[-10, -9.999, -10]))
    for command in ('scan-path', 'scan-peak'):
        extra = ['--out', str(tmp_path / 'guess.xyz')] if command == 'scan-peak' else []
        assert cli.main([command, str(path), '--' + option, value, '--json', *extra]) == 1
        capsys.readouterr()
    assert not (tmp_path / 'guess.xyz').exists()


def test_two_dimensional_behavior_unchanged(tmp_path, capsys):
    root, path = make_scan(tmp_path, 'gaussian', grid=True)
    assert cli.main(['scan-path', str(path), '--json']) == 1
    assert '不支持二维' in json.loads(capsys.readouterr().out)['error']
    assert cli.main(['scan-peak', str(path), '--point', '2,2', '--out', str(root / 'peak.xyz'), '--json']) == 0
    assert 'path_diagnostics' not in json.loads(capsys.readouterr().out)


def test_near_peak_only_and_far_warning_absent():
    frames = butane([60, 60, 60, 60, 60, 60, 180, 180])
    report = scan_path.diagnose(scan_for(frames), frames, 0)
    near = scan_path.near_peak(report, 2)
    assert near['summary']['flagged_count'] > 0 and near['warning'] is None
    assert [s['points'] for s in near['segments']] == [[1, 2], [2, 3], [3, 4]]
    near = scan_path.near_peak(report, 6)
    assert '6→7' in near['warning']
    assert len(near['segments']) == 4


def test_candidate_registration_bounded_and_summary_preserved(tmp_path, capsys, monkeypatch):
    root, path = make_scan(tmp_path)
    object_entry(root)
    original = scan_path.near_peak
    def large(*args):
        report = original(*args)
        # Simulate a large molecule's pair list without storing research coordinates.
        report['segments'][0]['uncertain_pairs'] = [dict(atoms=[1, 2], note='合成不确定对' * 20)] * 1200
        return report
    monkeypatch.setattr(scan_path, 'near_peak', large)
    assert cli.main(['scan-peak', str(path), '--out', str(root / 'guess.xyz'), '--json',
                     *candidate_options('--upgrade-catalog')]) == 0
    report = json.loads(capsys.readouterr().out)
    events = [json.loads(line) for line in (root / 'catalog/journal.jsonl').read_text().splitlines()]
    transform = next(e['transform'] for e in events if e['op'] == 'candidate')
    saved = transform['path_diagnostics']
    assert saved['truncated'] and '已截断' in saved['truncation_note']
    assert saved['summary'] == report['path_diagnostics']['summary']
    assert saved['segments'][0]['original_counts']['uncertain_pairs'] == 1200
    assert len(json.dumps(transform, ensure_ascii=False).encode()) <= 65536
    assert len(report['path_diagnostics']['segments'][0]['uncertain_pairs']) == 1200
    assert 'points' not in saved


def test_unknown_pair_symbol_order():
    frames = [waters(3.8), replace(waters(3.8), symbols=('N', 'H', 'H', 'O', 'H', 'H'))]
    segment = scan_path.diagnose(scan_for(frames), frames, 0)['segments'][0]
    assert segment['status'] == 'unknown' and segment['unknown_reason']
