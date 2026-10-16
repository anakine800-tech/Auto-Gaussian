"""Synthetic geometry regressions: no research files, network or quantum programs."""
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

import numpy as np
import pytest

pytest.importorskip('rdkit')
from ag import crest_input, geometry as geo

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import build_complex as build

REPO = Path(__file__).resolve().parents[3]
T68 = REPO / 'ag/tests/fixtures/inference/acetone_bf3.xyz'
HOST_ATOMS, GUEST_ATOMS = '3,2,1', '3,2,1'


def sample():
    return build.split_complex(geo.read_xyz(T68)[0], '4-7')


def write_frame(path, frame):
    empty = geo.Frame((), ())
    path.write_text(build.xyz_text(frame, empty, 'synthetic', 0, 1))


def transformed(frame, rng):
    matrix, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    matrix[:, 0] *= np.linalg.det(matrix)
    xyz = np.asarray(frame.coordinates) @ matrix + rng.uniform(-10, 10, 3)
    return replace(frame, coordinates=tuple(map(tuple, xyz)))


def aligned_rmsd(first, second):
    """Independent all-atom, fixed-order proper Kabsch alignment; no reflection."""
    a, b = np.asarray(first), np.asarray(second)
    a, b = a - a.mean(0), b - b.mean(0)
    u, _, vt = np.linalg.svd(a.T @ b)
    rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    return float(np.sqrt(np.mean(np.sum((a @ rotation - b) ** 2, axis=1))))


def arguments(root, name='roundtrip', **changes):
    host, guest = sample()
    values = build.measure(host, guest, HOST_ATOMS, GUEST_ATOMS)
    options = dict(study=str(root), name=name, host='host.xyz', guest='guest.xyz',
                   host_charge=0, guest_charge=0, multiplicity=1,
                   host_atoms=HOST_ATOMS, guest_atoms=GUEST_ATOMS, **values, force_constant=0.5)
    options.update(changes)
    argv = ['build']
    for key, value in options.items():
        if value is True:
            argv.append('--' + key.replace('_', '-'))
        elif value is not None and value is not False:
            argv.append('--' + key.replace('_', '-') + '=' + str(value))
    return build.parser().parse_args(argv)


def prepare(root, seed=86):
    host, guest = sample()
    rng = np.random.default_rng(seed)
    for name, frame in [('host', host), ('guest', guest)]:
        write_frame(root / f'{name}.xyz', transformed(frame, rng))
    return host, guest


def output(root, name='roundtrip'):
    return root / 'analyses/complex-build' / name


@pytest.mark.parametrize('seed', range(10))
def test_roundtrip_t68_saved_bytes_random_component_rotations(tmp_path, seed):
    host, guest = prepare(tmp_path, seed)
    report = build.run_build(arguments(tmp_path, constrain_angle=True))
    assert report['status'] == 'built'
    combined = geo.read_xyz(output(tmp_path) / 'complex.xyz')[0]
    rmsd = aligned_rmsd(combined.coordinates, host.coordinates + guest.coordinates)
    assert rmsd < 1e-6
    measured = build.measure(*build.split_complex(combined, '1-4'), HOST_ATOMS, GUEST_ATOMS)
    for key in build.PARAMETERS:
        difference = geo.periodic_difference(measured[key], report['parameters'][key]) if key.startswith('phi') else abs(measured[key] - report['parameters'][key])
        assert difference < 1e-6
    assert combined.coordinates[:4] == geo.read_xyz(tmp_path / 'host.xyz')[0].coordinates
    before = np.asarray(geo.read_xyz(tmp_path / 'guest.xyz')[0].coordinates)
    after = np.asarray(combined.coordinates[4:])
    assert np.max(np.abs(np.linalg.norm(before[:, None] - before, axis=2) - np.linalg.norm(after[:, None] - after, axis=2))) < 1e-8
    assert report['guest_distance_max_error'] < 1e-8
    assert combined.comment == 'roundtrip charge=0 multiplicity=1'
    assert json.loads((output(tmp_path) / 'build.json').read_text()) == report
    assert len(report['contacts']['nearest_10']) == 10
    print(f'T68 acetone–BF3 seed={seed}: RMSD={rmsd:.12e} Å')


def test_mapping_hashes_constraints_and_human_electronic_state(tmp_path, monkeypatch):
    prepare(tmp_path)
    original = crest_input.validate
    calls = []
    def tracked(text, n_atoms):
        calls.append((text, n_atoms))
        return original(text, n_atoms)
    monkeypatch.setattr(crest_input, 'validate', tracked)
    report = build.run_build(arguments(tmp_path, host_charge=-1, guest_charge=1, multiplicity=3, constrain_angle=True))
    assert report['charge'] == 0 and report['multiplicity'] == 3
    assert report['component_charges'] == {'host': -1, 'guest': 1}
    constraint = (output(tmp_path) / 'constraints.inp').read_text()
    assert len(calls) == 2 and calls[-1] == (constraint, 14)
    assert 'distance: 1, 7,' in constraint and 'angle: 1, 7, 6,' in constraint
    assert report['constraints']['validated'] and report['constraints']['written']
    with (output(tmp_path) / 'atoms.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 14 and rows[4] == dict(complex_index='5', component='guest', source_file='guest.xyz', source_index='1', element='C')
    assert [int(row['complex_index']) for row in rows] == list(range(1, 15))
    for entry in report['inputs']:
        assert entry['sha256'] == hashlib.sha256((tmp_path / entry['path']).read_bytes()).hexdigest()
    assert str(tmp_path) not in (output(tmp_path) / 'build.json').read_text()


def trigonal():
    return geo.Frame(('C', 'O', 'H', 'H'), ((0., 0., 0.), (1.2, 0., 0.), (-.55, .9526, 0.), (-.55, -.9526, 0.)))


@pytest.mark.parametrize('z,priority,expected', [(2., '2,3,4', 'Si'), (-2., '2,3,4', 'Re'), (2., '2,4,3', 'Re'), (-2., '2,4,3', 'Si')])
def test_face_both_sides_and_human_priority(z, priority, expected):
    result = build.face_label(trigonal(), [0, 0, z], 1, priority)
    assert result['label'] == expected
    assert result['priority_source'] == 'human-supplied; CIP not inferred'


@pytest.mark.parametrize('z', [0., .299, -.299])
def test_face_near_plane_refused(z):
    with pytest.raises(ValueError, match='0.3 Å'):
        build.face_label(trigonal(), [0, 0, z], 1, '2,3,4')


def test_face_bad_surroundings_and_pyramidal_center():
    with pytest.raises(ValueError, match='three connected'):
        build.face_label(trigonal(), [0, 0, 2], 1, '1,2,3')
    shifted = replace(trigonal(), coordinates=((0, 0, .2), *trigonal().coordinates[1:]))
    with pytest.raises(ValueError, match='not in the trigonal plane'):
        build.face_label(shifted, [0, 0, 2], 1, '2,3,4')


@pytest.mark.parametrize('phi,expected', [(0, 'syn'), (89, 'syn'), (-89, 'syn'), (91, 'anti'), (-91, 'anti'), (180, 'anti')])
def test_syn_anti_and_label_basis(phi, expected):
    guest = trigonal()
    d, x, ref = (np.asarray(guest.coordinates[i - 1]) for i in (2, 1, 3))
    # The reversed torsion ref-X-D-A equals A-D-X-ref.
    attacker = build.place(ref, x, d, 3, 120, phi, 'test')
    host = geo.Frame(('B',), (tuple(attacker),))
    result = build.site_labels(host, guest, 1, 2, 1, syn_anti_ref=3)
    assert result['label'] == f'O2-{expected}(H3)'
    assert result['syn_anti']['host_atom'] == 1
    assert result['syn_anti']['guest_atoms'] == [2, 1, 3]
    with pytest.raises(ValueError, match='syn-anti-ref'):
        build.site_labels(host, guest, 1, 2, 1, syn_anti_ref=2)


def test_face_mismatch_rejects_without_moving_to_requested_side(tmp_path):
    host, guest = sample()
    # This synthetic fixture is almost planar at its carbonyl C; move the whole
    # BF3 away from the plane to test the requested-face validation at CLI level.
    shift = np.array([0., 0., 3.])
    host = replace(host, coordinates=tuple(map(tuple, np.asarray(host.coordinates) + shift)))
    write_frame(tmp_path / 'host.xyz', host)
    write_frame(tmp_path / 'guest.xyz', guest)
    measured = build.measure(host, guest, HOST_ATOMS, GUEST_ATOMS)
    actual = build.face_label(guest, host.coordinates[0], 2, '3,1,4')['label']
    report = build.run_build(arguments(tmp_path, face='Re' if actual == 'Si' else 'Si', face_center=2, face_priority='3,1,4', **measured))
    assert report['status'] == 'rejected'
    assert report['site']['face']['label'] == actual
    assert any('face mismatch' in error for error in report['errors'])
    assert not (output(tmp_path) / 'complex.xyz').exists()
    assert (output(tmp_path) / 'build.md').exists()


@pytest.mark.parametrize('changes,reason', [({'r': .2}, 'unexpected_bond'), ({'phi1': 0}, 'unexpected_bond'), ({'vdw_factor': 2}, 'vdw_overlap')])
def test_clashes_all_pairs_reported_no_candidate_published(tmp_path, changes, reason):
    prepare(tmp_path)
    report = build.run_build(arguments(tmp_path, **changes))
    assert report['status'] == 'rejected'
    assert any(reason in c['violations'] for c in report['contacts']['violations'])
    assert all(not c['declared_contact'] for c in report['contacts']['violations'])
    assert len(report['contacts']['nearest_10']) == 10
    assert {p.name for p in output(tmp_path).iterdir()} == {'build.json', 'build.md'}
    text = (output(tmp_path) / 'build.md').read_text()
    for c in report['contacts']['violations']:
        assert f"| {c['host_atom']} | {c['guest_atom']} |" in text
    assert not report['constraints']['written']


def test_contact_very_short_distances_cannot_hide_in_topology_uncertainty_band():
    host = geo.Frame(('B', 'F'), ((0, 0, 0), (1, 0, 0)))
    guest = geo.Frame(('O', 'C'), ((0, 0, 1.5), (1, 0, .01)))
    result = build.contact_report(host, guest, 1, 1)
    pair = next(c for c in result['violations'] if c['host_atom'] == 2 and c['guest_atom'] == 2)
    assert pair['covalent_radius_ratio'] < .6
    assert 'unexpected_bond' in pair['violations']


@pytest.mark.parametrize('which', ['host', 'guest'])
def test_collinear_references_refused(which):
    host, guest = sample()
    frame = host if which == 'host' else guest
    points = list(frame.coordinates)
    points[2] = tuple(np.asarray(points[0]) + .5 * (np.asarray(points[1]) - points[0]))
    bad = replace(frame, coordinates=tuple(points))
    with pytest.raises(ValueError, match='collinear'):
        build.measure(bad if which == 'host' else host, bad if which == 'guest' else guest, HOST_ATOMS, GUEST_ATOMS)


@pytest.mark.parametrize('key,value', [('theta1', 0), ('theta2', 180), ('theta1', .000001), ('theta2', 179.999999), ('r', 0), ('phi1', float('nan'))])
def test_degenerate_or_nonfinite_parameters(key, value):
    host, guest = sample()
    values = build.measure(host, guest, HOST_ATOMS, GUEST_ATOMS)
    values[key] = value
    with pytest.raises(ValueError):
        build.build_geometry(host, guest, HOST_ATOMS, GUEST_ATOMS, values)


@pytest.mark.parametrize('symbol', ['Fe', 'Zn', 'La', 'U', 'Xx'])
def test_non_main_group_refused(symbol):
    host, guest = sample()
    host = replace(host, symbols=(symbol, *host.symbols[1:]))
    with pytest.raises(ValueError, match='outside main-group'):
        build.measure(host, guest, HOST_ATOMS, GUEST_ATOMS)


def test_disconnected_and_invalid_guest_reference_refused():
    host, guest = sample()
    disconnected = replace(guest, coordinates=(*guest.coordinates[:-1], (100, 100, 100)))
    with pytest.raises(ValueError, match='single connected'):
        build.sites(disconnected)
    with pytest.raises(ValueError, match='D-X and X-Y'):
        build.measure(host, guest, HOST_ATOMS, '3,1,2')
    with pytest.raises(ValueError, match='distinct'):
        build.measure(host, guest, '1,1,2', GUEST_ATOMS)


def test_sites_list_candidates_with_no_choice():
    _, guest = sample()
    report = build.sites(guest)
    assert len(report['sites']) == 1
    oxygen = report['sites'][0]
    assert oxygen['atom'] == 3 and oxygen['element'] == 'O'
    assert oxygen['connected_atoms'] == [2]
    assert oxygen['direction_references'][0] == dict(D=3, X=2, Y_candidates=[1, 4], syn_anti_candidates=[1, 4])
    assert 'no site selection' in report['notice']


@pytest.mark.parametrize('changes', [{'host': '../host.xyz'}, {'host': '/outside.xyz'}, {'name': '../escape'}, {'guest': 'link.xyz'}, {'host': 'linked/host.xyz'}])
def test_path_escape_and_input_links_refused(tmp_path, changes):
    prepare(tmp_path)
    (tmp_path / 'link.xyz').symlink_to(tmp_path / 'guest.xyz')
    (tmp_path / 'linked').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='relative|symlink|name must'):
        build.run_build(arguments(tmp_path, **changes))
    assert not (tmp_path / 'analyses').exists()


def test_existing_output_and_output_symlinks_refused(tmp_path):
    prepare(tmp_path)
    build.run_build(arguments(tmp_path))
    before = {p.name: p.read_bytes() for p in output(tmp_path).iterdir()}
    with pytest.raises(ValueError, match='already exists'):
        build.run_build(arguments(tmp_path))
    assert before == {p.name: p.read_bytes() for p in output(tmp_path).iterdir()}
    (tmp_path / 'analyses/complex-build/link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        build.run_build(arguments(tmp_path, name='link'))


def test_parent_and_study_symlink_refused(tmp_path):
    prepare(tmp_path)
    (tmp_path / 'analyses').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        build.run_build(arguments(tmp_path))
    (tmp_path / 'study-link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        build.run_build(arguments(tmp_path / 'study-link'))


def test_constraints_validator_failure_is_not_success(tmp_path, monkeypatch):
    prepare(tmp_path)
    def fail(*args):
        raise ValueError('validator rejected draft')
    monkeypatch.setattr(crest_input, 'validate', fail)
    with pytest.raises(ValueError, match='validator rejected'):
        build.run_build(arguments(tmp_path))
    assert not output(tmp_path).exists()


@pytest.mark.parametrize('changes', [{'force_constant': 0}, {'force_constant': -1}, {'multiplicity': 0}, {'face': 'Re'}, {'face_center': 2}, {'vdw_factor': -1}])
def test_required_human_input_and_invalid_options(tmp_path, changes):
    prepare(tmp_path)
    with pytest.raises(ValueError):
        build.run_build(arguments(tmp_path, **changes))


def test_cli_measure_split_build_and_sites(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', str(REPO / 'ag/src'))
    write_frame(tmp_path / 'complex.xyz', geo.read_xyz(T68)[0])
    common = [sys.executable, str(SCRIPTS / 'build_complex.py')]
    measured = subprocess.run(common + ['measure', '--complex', 'complex.xyz', '--host-range', '4-7', '--host-atoms', HOST_ATOMS, '--guest-atoms', GUEST_ATOMS], cwd=tmp_path, text=True, capture_output=True)
    assert measured.returncode == 0, measured.stderr
    parameters = json.loads(measured.stdout)
    host, guest = prepare(tmp_path)
    command = common + ['build', '--study', str(tmp_path), '--name', 'cli', '--host', 'host.xyz', '--guest', 'guest.xyz', '--host-charge', '0', '--guest-charge', '0', '--multiplicity', '1', '--force-constant', '.5', '--host-atoms', HOST_ATOMS, '--guest-atoms', GUEST_ATOMS, *shlex.split(parameters['build_parameters'])]
    built = subprocess.run(command, text=True, capture_output=True)
    assert built.returncode == 0, built.stderr
    coordinates = geo.read_xyz(output(tmp_path, 'cli') / 'complex.xyz')[0].coordinates
    assert aligned_rmsd(coordinates, host.coordinates + guest.coordinates) < 1e-6
    candidates = subprocess.run(common + ['sites', '--guest', 'guest.xyz', '--study', str(tmp_path)], text=True, capture_output=True)
    assert candidates.returncode == 0 and json.loads(candidates.stdout)['sites'][0]['element'] == 'O'
    no_force = command.copy()
    index = no_force.index('--force-constant')
    del no_force[index:index + 2]
    missing = subprocess.run(no_force, text=True, capture_output=True)
    assert missing.returncode == 2 and '--force-constant' in missing.stderr


def test_multiple_xyz_frames_rejected(tmp_path):
    prepare(tmp_path)
    path = tmp_path / 'guest.xyz'
    path.write_text(path.read_text() * 2)
    with pytest.raises(ValueError, match='exactly one'):
        build.run_build(arguments(tmp_path))


def test_second_synthetic_water_formaldehyde_roundtrip(tmp_path):
    host = geo.Frame(('O', 'H', 'H'), ((0., 0., 0.), (-.76, .58, 0.), (-.76, -.58, 0.)))
    guest = geo.Frame(('C', 'O', 'H', 'H'), ((4.2, .2, .6), (3., .3, .4), (4.8, 1.1, .7), (4.7, -.7, .6)))
    values = build.measure(host, guest, '3,2,1', '2,1,3')
    rng = np.random.default_rng(8602)
    write_frame(tmp_path / 'host.xyz', transformed(host, rng))
    write_frame(tmp_path / 'guest.xyz', transformed(guest, rng))
    report = build.run_build(arguments(tmp_path, guest_atoms='2,1,3', **values))
    assert report['status'] == 'built'
    saved = geo.read_xyz(output(tmp_path) / 'complex.xyz')[0]
    rmsd = aligned_rmsd(saved.coordinates, host.coordinates + guest.coordinates)
    assert rmsd < 1e-6
    print(f'synthetic water–formaldehyde: RMSD={rmsd:.12e} Å')


def test_constraints_validation_after_write_is_required(tmp_path, monkeypatch):
    prepare(tmp_path)
    original, calls = crest_input.validate, []
    def validate(text, n_atoms):
        calls.append(text)
        if len(calls) == 2:
            assert (output(tmp_path) / 'constraints.inp').read_text() == text
            raise ValueError('written constraints rejected')
        return original(text, n_atoms)
    monkeypatch.setattr(crest_input, 'validate', validate)
    with pytest.raises(ValueError, match='written constraints rejected'):
        build.run_build(arguments(tmp_path))
    assert not (output(tmp_path) / 'build.json').exists()
    with pytest.raises(ValueError, match='already exists'):
        build.run_build(arguments(tmp_path))


def test_measure_rejects_collinear_cross_component_plane():
    host, guest = sample()
    d, x = np.asarray(guest.coordinates[2]), np.asarray(guest.coordinates[1])
    # Make A-D-X collinear while keeping both components internally intact.
    translation = d + (d - x) - np.asarray(host.coordinates[0])
    host = replace(host, coordinates=tuple(map(tuple, np.asarray(host.coordinates) + translation)))
    with pytest.raises(ValueError, match='phi2.*collinear'):
        build.measure(host, guest, HOST_ATOMS, GUEST_ATOMS)


def test_face_and_syn_label_combined():
    guest = trigonal()
    host = geo.Frame(('B',), ((2., 0., 2.),))
    result = build.site_labels(host, guest, 1, 2, 1, face='Si', face_center=1, face_priority='2,3,4', syn_anti_ref=3)
    assert result['label'] == 'O2-anti(H3)-Si'
    assert result['face']['priority'] == [2, 3, 4]
