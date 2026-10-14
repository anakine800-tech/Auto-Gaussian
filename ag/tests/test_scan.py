"""Synthetic small-molecule scan input/output and local export regressions."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from ag import attempt, cli, crest_input, gaussian_input, render, remote, study
from ag._scan import (coordinate, input_geometry, modredundant, parse_gaussian_scan,
                      parse_xtb_scan, value)
from ag.facts import build_facts
from ag.geometry import Frame, HARTREE_TO_KCAL, read_xyz, xyz_text
from ag.scan_peak import select_peak
from test_core import cfg, INPUT

GEOMETRY = 'O 0 0 0\nO 1.45 0 0\nH -0.4 0.8 0\nH 1.85 0 0.8'
GJF = '%nprocshared=8\n%mem=10GB\n# HF/STO-3G opt=modredundant\n\nperoxide\n\n0 1\n' + GEOMETRY + '\n\n'
XCONTROL = '$constrain\ndistance: 1, 2, auto\nangle: 3, 1, 2, auto\n$end\n$scan\n1: 1.45,2.05,7\n$end\n'


def definition():
    return modredundant('B 1 2 S 6 0.1', GEOMETRY)['scan']


@pytest.mark.parametrize('line', ['B 1 2 S 6 0.1', 'A 3 1 2 S 50 -1', 'D 3 1 2 4 S 1 2e0',
                                 'B 1 2 F', 'B 1 2 S 5 .1\nA 3 1 2 F\nD 3 1 2 4 F'])
def test_modredundant_valid(line):
    data = gaussian_input.validate(GJF + line + '\n\n', 8, 12)
    assert 'scan' in data
    assert data['n_atoms'] == 4


@pytest.mark.parametrize('line', [
    'B 0 2 S 5 .1', 'B 1 5 S 5 .1', 'B 1 * S 5 .1', 'B 1 1 F',
    *[f'B 1 2 {action}' for action in ('K', 'R', 'H', 'A', 'D', 'B')],
    'B 1 2 S 5 .1\nA 3 1 2 S 5 1', 'B 1 2 S', 'B 1 2 S 5',
    'B 1 2 S 0 .1', 'B 1 2 S 51 .1', 'B 1 2 S 1.5 .1', 'B 1 2 S 5 0',
    'B 1 2 S 5 nan', 'B 1 2 S 5 inf', 'B 1 2 S 5 1e999', 'X 1 F',
    'B 1 2 F garbage', 'B 1 2 S 5 .1\n\nB 1 2 F', 'B 1 2 F\n@input',
])
def test_modredundant_invalid(line):
    with pytest.raises(ValueError):
        gaussian_input.validate(GJF + line + '\n\n', 8, 12)


@pytest.mark.parametrize('route', ['opt', 'sp', 'opt=(ts,modredundant)', 'opt=(qst2,modredundant)',
                                 'opt=(qst3,modredundant)', 'opt=modredundant external=test', 'opt=modredundant units=bohr'])
def test_extra_section_requires_plain_modredundant(route):
    with pytest.raises(ValueError):
        gaussian_input.validate(GJF.replace('opt=modredundant', route) + 'B 1 2 S 5 .1\n', 8, 12)


def test_scan_input_summary(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'peroxide.gjf'
    source.write_text(GJF + 'B 1 2 S 6 0.1\nA 3 1 2 F\n')
    m = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='scan')
    summary = attempt.summary(cfg, m)
    assert 'B 1(O) 2(O)' in summary
    assert 'Start: 1.45' in summary and 'End: 2.05' in summary
    assert 'Steps: 6' in summary and 'Step size: 0.1' in summary
    assert 'Frozen coordinates: A 3(H) 1(O) 2(O)' in summary
    attempt.verified_files(cfg, attempt.find(cfg, m['attempt_id']), m)
    assert gaussian_input.validate(INPUT, 8, 12)['n_atoms'] == 3


@pytest.mark.parametrize('bad', ['1: 1,2,0', '1: 1,2,101', '2: 1,2,5', '0: 1,2,5',
                                  '1: nan,2,5', '1: 1,inf,5', '1: 1,2,1.5', '1: -1e308,1e308,2',
                                  '1: 1,2,5\n1: 2,3,5', '$write', 'mode=concerted'])
def test_xtb_scan_rejects(bad):
    text = '$constrain\ndistance: 1,2,auto\n$end\n$scan\n' + bad + '\n$end\n'
    with pytest.raises(ValueError):
        crest_input.validate(text, 4, allow_scan=True)


@pytest.mark.parametrize('separator', ['$end\n', ''])
@pytest.mark.parametrize('steps', [1, 7, 100])
def test_xtb_scan_valid_and_crest_unchanged(separator, steps):
    text = XCONTROL.replace('$end\n$scan', separator + '$scan').replace(',7', f',{steps}')
    scan = crest_input.validate(text, 4, allow_scan=True)
    assert scan['steps'] == steps and scan['coordinate']['atoms'] == [1, 2]
    with pytest.raises(ValueError):
        crest_input.validate(text, 4)


def test_xtb_constraints_bundle(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source, constraint = tmp_path / 'peroxide.xyz', tmp_path / 'scan.inp'
    source.write_text('4\nperoxide\n' + GEOMETRY + '\n')
    constraint.write_text(XCONTROL)
    kwargs = dict(study_name='smoke', template='xtb', input_path=source,
                  tier='simple', walltime='00:30:00', label='scan', params={'--gfn': '2', '--opt': ''})
    plain = attempt.prepare(cfg, **kwargs)
    m = attempt.prepare(cfg, constraints=constraint, **kwargs)
    path = attempt.find(cfg, m['attempt_id'])
    files = attempt.verified_files(cfg, path, m)
    assert files['constraints.inp'] == constraint.read_bytes()
    assert files['job.pbs'].endswith(b'--input constraints.inp > xtb.out\n')
    assert m['science']['scan']['coordinate']['elements'] == ['O', 'O']
    assert 'xtbscan.log' in render.declaration('xtb')['scan_outputs']
    assert remote.output_names(plain) == ['xtb.out', 'xtbopt.xyz', 'xtbopt.log', 'job.pbs.out']
    assert remote.output_names(m) == ['xtb.out', 'xtbscan.log', 'job.pbs.out']
    assert '--input' not in plain['template_params']
    assert 'scan' not in plain['science']
    bad = deepcopy(m)
    bad['science']['scan']['start'] = 100
    with pytest.raises(ValueError, match='summary'):
        attempt.verified_files(cfg, path, bad)
    with pytest.raises(ValueError, match='Use --constraints'):
        attempt.prepare(cfg, **{**kwargs, 'params': {'--input': 'constraints.inp'}})
    (path / 'inputs/constraints.inp').write_text(XCONTROL.replace('2.05', '2.15'))
    with pytest.raises(ValueError, match='bundle'):
        attempt.verified_files(cfg, path, m)


def frame_at(i, energy=None):
    symbols, coordinates = input_geometry(GEOMETRY)
    coordinates[1][0] += i * .1
    return Frame(tuple(symbols), tuple(tuple(p) for p in coordinates), energy=energy)


def orientation(frame):
    numbers = {'O': 8, 'H': 1}
    return (' Standard orientation:\n -----------\n Center Atomic Atomic Coordinates\n Number Number Type X Y Z\n -----------\n' +
            ''.join(f' {i} {numbers[s]} 0 {x} {y} {z}\n' for i, (s, (x, y, z)) in enumerate(zip(frame.symbols, frame.coordinates), 1)) +
            ' -----------\n')


def gaussian_log(energies, states):
    text = '# HF/STO-3G opt=modredundant\n -----\n'
    for i, (energy, state) in enumerate(zip(energies, states)):
        # A trial SCF must never create another point.
        text += orientation(frame_at(i)) + f' SCF Done: E(RHF) = {energy - .01} A.U.\n'
        text += orientation(frame_at(i)) + f' SCF Done: E(RHF) = {energy} A.U.\n'
        if state is not None:
            text += ' Optimization ' + ('completed' if state else 'stopped') + '.\n'
            if state:
                text += ' -- Stationary point found.\n'
    return text


ENERGIES = [-150.0, -149.999, -149.997, -149.995, -149.997, -149.999, -150.0]


def test_gaussian_points_converged_failed_and_truncated():
    scan, xyz = parse_gaussian_scan(gaussian_log(ENERGIES, [True, False, True, True, True, True, None]), definition())
    assert len(scan['points']) == 7 and xyz.count('energy=') == 7
    assert [p['energy_hartree'] for p in scan['points']] == ENERGIES
    assert [p['converged'] for p in scan['points']] == [True, False, True, True, True, True, None]
    assert scan['points'][3]['coordinate_value'] == pytest.approx(1.75)
    partial, _ = parse_gaussian_scan(gaussian_log(ENERGIES[:2], [True, True]), definition())
    assert partial['points'][2]['energy_hartree'] is None
    assert partial['points'][2]['geometry_frame'] is None
    assert partial['points'][2]['converged'] is None


def test_gaussian_missing_energy_not_borrowed():
    log = gaussian_log(ENERGIES[:1], [True]) + orientation(frame_at(1)) + ' Optimization stopped.\n'
    scan, _ = parse_gaussian_scan(log, definition())
    assert scan['points'][1]['energy_hartree'] is None


def xtb_stdout(states):
    return 'RELAXED SCAN\n' + ''.join(
        f'... step {i} ...\n' + ('GEOMETRY OPTIMIZATION CONVERGED\n' if state is True else
        'FAILED TO CONVERGE\n' if state is False else '') for i, state in enumerate(states, 1))


def test_xtb_scan_parser(tmp_path):
    path = tmp_path / 'xtbscan.log'
    path.write_text(xyz_text([frame_at(i, e) for i, e in enumerate(ENERGIES)]))
    scan, xyz = parse_xtb_scan(path, xtb_stdout([True, True, False, True, True, True, True]), definition())
    assert scan['energy_kind'] == 'xtb_unbiased'
    assert [p['energy_hartree'] for p in scan['points']] == ENERGIES
    assert scan['points'][2]['converged'] is False
    assert xyz.count('energy=') == 7
    unknown, _ = parse_xtb_scan(path, 'normal termination of xtb', definition())
    assert all(p['converged'] is None for p in unknown['points'])


@pytest.mark.parametrize('program', ['gaussian', 'xtb'])
def test_facts_and_peak_cli(tmp_path, capsys, program):
    root = tmp_path / 'attempt'
    root.mkdir()
    outputs = root / 'outputs'
    outputs.mkdir()
    (root / 'manifest.json').write_text(json.dumps({'template': program, 'science': {'scan': definition()}}))
    if program == 'gaussian':
        (outputs / 'peroxide.log').write_text(gaussian_log(ENERGIES, [True] * 7))
    else:
        (outputs / 'xtbscan.log').write_text(xyz_text([frame_at(i, e) for i, e in enumerate(ENERGIES)]))
        (outputs / 'xtb.out').write_text(xtb_stdout([True] * 7))
    facts = build_facts(root)
    before = (root / 'scan_points.xyz').read_bytes()
    assert build_facts(root) == facts
    assert (root / 'scan_points.xyz').read_bytes() == before
    destination = tmp_path / 'seed.xyz'
    assert cli.main(['scan-peak', str(root), '--out', str(destination), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['peak']['point'] == 4 and result['warnings'] == []
    assert len(result['neighbors_before']) == len(result['neighbors_after']) == 2
    assert read_xyz(destination)[0].coordinates[1][0] == pytest.approx(1.75)
    assert cli.main(['scan-peak', str(root), '--out', str(destination)]) == 1
    capsys.readouterr()
    assert read_xyz(destination)[0].coordinates[1][0] == pytest.approx(1.75)
    (root / 'scan_points.xyz').write_text('changed')
    with pytest.raises(ValueError, match='differs'):
        build_facts(root)
    assert cli.main(['scan-peak', str(root), '--out', str(tmp_path / 'other.xyz')]) == 1
    assert not (tmp_path / 'other.xyz').exists()


@pytest.mark.parametrize('case', ['normal', 'boundary', 'jump', 'unconverged', 'rmsd'])
def test_peak_warnings(case, tmp_path):
    energies, states = ENERGIES[:], [True] * 7
    if case == 'boundary':
        energies[-1] = -149.99
    if case == 'jump':
        energies[3] += .1
    if case == 'unconverged':
        states[0] = False
    scan, xyz = parse_gaussian_scan(gaussian_log(energies, states), definition())
    path = tmp_path / 'points.xyz'
    path.write_text(xyz)
    frames = read_xyz(path)
    if case == 'rmsd':
        coords = list(frames[3].coordinates)
        coords[2] = (10, 10, 10)
        frames[3] = Frame(frames[3].symbols, tuple(coords))
    report, chosen = select_peak(scan, frames)
    warnings = ' '.join(report['warnings'])
    if case == 'normal':
        assert warnings == ''
    elif case == 'boundary':
        assert '范围不够' in warnings and report['peak']['point'] != 7
    elif case in ('jump', 'rmsd'):
        assert '另一条路径' in warnings and report['jumps']
    else:
        assert '未收敛' in warnings and report['peak']['point'] == 4


def test_no_converged_interior_and_required_out():
    scan, _ = parse_gaussian_scan(gaussian_log(ENERGIES, [True] + [False] * 5 + [True]), definition())
    with pytest.raises(ValueError, match='No strict local maximum'):
        select_peak(scan, [])
    with pytest.raises(SystemExit):
        cli.main(['scan-peak', 'attempt'])


def synthetic_scan(energies, states=None):
    spec = {**definition(), 'expected_points': len(energies)}
    scan, _ = parse_gaussian_scan(gaussian_log(energies, states or [True] * len(energies)), spec)
    return scan, [frame_at(i, e) for i, e in enumerate(energies)]


def test_lower_local_peak_below_separation_boundary():
    # Toward the left/separated boundary energy rises; point 2 is the highest
    # interior point, but the buried local peak is point 9.
    energies = [-150 + e * .001 for e in (20, 18, 14, 8, 2, 0, 1, 3, 5, 3, 1)]
    scan, frames = synthetic_scan(energies)
    report, chosen = select_peak(scan, frames)
    assert report['peak']['point'] == 9
    assert chosen == frames[8]
    assert [p['point'] for p in report['local_maxima']] == [9]
    assert '范围不够' in ' '.join(report['warnings'])


@pytest.mark.parametrize('energies', [
    [-3, -2, -1], [-1, -2, -3], [-1, -1, -1], [-3, -2, -2, -3],
    [-1, -3, -2], [-3, -2],
])
def test_no_strict_peak_refuses(energies):
    scan, frames = synthetic_scan(energies)
    with pytest.raises(ValueError, match='扫描范围或扫描坐标不合适'):
        select_peak(scan, frames)


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('missing', [False, None, 'energy'])
def test_peak_requires_center_and_immediate_neighbors(index, missing):
    scan, frames = synthetic_scan([-150, -149.99, -150])
    if missing == 'energy':
        scan['points'][index]['energy_hartree'] = None
    else:
        scan['points'][index]['converged'] = missing
    with pytest.raises(ValueError, match='No strict local maximum'):
        select_peak(scan, frames)


@pytest.mark.parametrize('json_output', [False, True])
@pytest.mark.parametrize('point, selected', [(None, 5), (2, 2), (5, 5)])
def test_two_peaks_cli_lists_all_and_exports_requested(tmp_path, capsys, json_output, point, selected):
    scan, frames = synthetic_scan([-150, -149.998, -149.999, -149.999, -149.996, -149.999, -150])
    (tmp_path / 'manifest.json').write_text('{}')
    source = tmp_path / 'scan_points.xyz'
    source.write_text(xyz_text(frames))
    scan['geometries_sha256'] = sha256(source.read_bytes()).hexdigest()
    (tmp_path / 'facts.json').write_text(json.dumps({'scan': scan}))
    destination = tmp_path / 'peak.xyz'
    args = ['scan-peak', str(tmp_path), '--out', str(destination)]
    if json_output:
        args += ['--json']
    if point is not None:
        args += ['--point', str(point)]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    if json_output:
        report = json.loads(output)
        assert report['peak']['point'] == selected
        assert [p['point'] for p in report['local_maxima']] == [2, 5]
        assert [p['coordinate_value'] for p in report['local_maxima']] == pytest.approx([1.55, 1.85])
        assert [p['energy_hartree'] for p in report['local_maxima']] == [-149.998, -149.996]
        assert [p['relative_energy_kcal_mol'] for p in report['local_maxima']] == pytest.approx(
            [.002 * HARTREE_TO_KCAL, .004 * HARTREE_TO_KCAL])
        assert report['relative_energy_reference']['energy_hartree'] == -150
    else:
        assert 'point 2: coordinate=1.55 angstrom, energy=-149.998 Hartree, relative_energy=' in output
        assert 'point 5: coordinate=1.85 angstrom, energy=-149.996 Hartree, relative_energy=' in output
        assert f'TS 初猜：point {selected}' in output
    for actual, expected in zip(read_xyz(destination)[0].coordinates, frames[selected - 1].coordinates):
        assert actual == pytest.approx(expected)


@pytest.mark.parametrize('point', [0, 1, 3, 7, 8, -1])
def test_invalid_requested_peak_does_not_export(tmp_path, capsys, point):
    scan, frames = synthetic_scan(ENERGIES)
    (tmp_path / 'manifest.json').write_text('{}')
    source = tmp_path / 'scan_points.xyz'
    source.write_text(xyz_text(frames))
    scan['geometries_sha256'] = sha256(source.read_bytes()).hexdigest()
    (tmp_path / 'facts.json').write_text(json.dumps({'scan': scan}))
    destination = tmp_path / 'peak.xyz'
    assert cli.main(['scan-peak', str(tmp_path), '--point', str(point), '--out', str(destination)]) == 1
    assert 'not a strict local maximum' in capsys.readouterr().err
    assert not destination.exists()


def test_monotonic_cli_does_not_export(tmp_path, capsys):
    scan, frames = synthetic_scan([-150, -149.999, -149.998])
    (tmp_path / 'manifest.json').write_text('{}')
    source = tmp_path / 'scan_points.xyz'
    source.write_text(xyz_text(frames))
    scan['geometries_sha256'] = sha256(source.read_bytes()).hexdigest()
    (tmp_path / 'facts.json').write_text(json.dumps({'scan': scan}))
    destination = tmp_path / 'peak.xyz'
    assert cli.main(['scan-peak', str(tmp_path), '--out', str(destination)]) == 1
    assert '扫描范围或扫描坐标不合适' in capsys.readouterr().err
    assert not destination.exists()


def test_angle_dihedral_values():
    coordinates = [(1, 0, 0), (0, 0, 0), (0, 1, 0), (0, 1, 1)]
    symbols = ['C'] * 4
    assert value(coordinate('A', [1, 2, 3], symbols), coordinates) == pytest.approx(90)
    assert abs(value(coordinate('D', [1, 2, 3, 4], symbols), coordinates)) == pytest.approx(90)


def test_xtb_verbose_point_convergence(tmp_path):
    path = tmp_path / 'xtbscan.log'
    path.write_text(xyz_text([frame_at(i, e) for i, e in enumerate(ENERGIES)]))
    text = 'GEOMETRY OPTIMIZATION CONVERGED AFTER 5 ITERATIONS\nRELAXED SCAN\n'
    outcomes = ['GEOMETRY OPTIMIZATION CONVERGED AFTER 10 ITERATIONS'] * 7
    outcomes[2] = 'FAILED TO CONVERGE GEOMETRY OPTIMIZATION IN 250 ITERATIONS'
    scan, _ = parse_xtb_scan(path, text + '\n'.join(outcomes), definition())
    assert [p['converged'] for p in scan['points']] == [True, True, False, True, True, True, True]
    missing, _ = parse_xtb_scan(path, text + '\n'.join(outcomes[1:]), definition())
    assert all(p['converged'] is None for p in missing['points'])


def test_scan_files_refuse_symlinks(tmp_path):
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    (outputs / 'peroxide.log').write_text(gaussian_log(ENERGIES, [True] * 7))
    (tmp_path / 'manifest.json').write_text(json.dumps({'template': 'gaussian', 'science': {'scan': definition()}}))
    external = tmp_path / 'preserve.xyz'
    external.write_text('untouched')
    (tmp_path / 'scan_points.xyz').symlink_to(external)
    with pytest.raises(ValueError):
        build_facts(tmp_path)
    assert external.read_text() == 'untouched'


@pytest.mark.parametrize('route', ['opt=modredundant', 'opt=(ts,modredundant)', 'opt=(ts,calcfc)', 'sp'])
def test_no_extra_section_keeps_single_structure_behavior(route):
    science = gaussian_input.validate(GJF.replace('opt=modredundant', route), 8, 12)
    assert science['n_atoms'] == 4
    assert 'scan' not in science


@pytest.mark.parametrize('scan', [False, True])
@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
def test_xtb_fetch_declares_termination_evidence(scan, scheduler):
    manifest = {'template': 'xtb', 'scheduler': scheduler,
                'inputs': [{'name': 'water.xyz'}], 'science': {'scan': {'steps': 3}} if scan else {}}
    expected = ['xtb.out', 'xtbscan.log'] if scan else ['xtb.out', 'xtbopt.xyz', 'xtbopt.log']
    expected += ['job.pbs.out'] if scheduler == 'pbs' else ['job.slurm.out', 'job.slurm.err']
    assert remote.output_names(manifest) == expected
