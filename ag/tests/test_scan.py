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


@pytest.mark.parametrize('line', ['B 1 2 S 6 0.1', 'A 3 1 2 S 50 -1.0', 'D 3 1 2 4 S 1 2.0e0',
                                 'B 1 2 F', 'B 1 2 S 5 .1\nA 3 1 2 F\nD 3 1 2 4 F'])
def test_modredundant_valid(line):
    data = gaussian_input.validate(GJF + line + '\n\n', 8, 12)
    assert 'scan' in data
    assert data['n_atoms'] == 4


@pytest.mark.parametrize('line', [
    'B 0 2 S 5 .1', 'B 1 5 S 5 .1', 'B 1 * S 5 .1', 'B 1 1 F',
    *[f'B 1 2 {action}' for action in ('K', 'R', 'H', 'A', 'D', 'B')],
    'B 1 2 S', 'B 1 2 S 5',
    'B 1 2 S 0 .1', 'B 1 2 S 51 .1', 'B 1 2 S 1.5 .1', 'B 1 2 S 5 0',
    'B 1 2 S 5 nan', 'B 1 2 S 5 inf', 'B 1 2 S 5 1e999', 'X 1 F',
    'B 1 2 F garbage', 'B 1 2 S 5 .1\n\nB 1 2 F', 'B 1 2 F\n@input',
])
def test_modredundant_invalid(line):
    with pytest.raises(ValueError):
        gaussian_input.validate(GJF + line + '\n\n', 8, 12)


@pytest.mark.parametrize('prefix', ['', 'B 1 2 S 2 0.04\n'])
@pytest.mark.parametrize('step', ['5', '-5', '5e0'])
def test_scan_step_requires_decimal_point(cfg, tmp_path, prefix, step):
    study.init(cfg, 'smoke')
    source = tmp_path / 'peroxide.gjf'
    source.write_text(GJF + prefix + f'A 3 1 2 S 2 {step}\n\n')
    with pytest.raises(ValueError, match=r'decimal point; write 5\.0 instead of 5'):
        attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke',
                        template='gaussian', input_path=source, tier='simple',
                        walltime='00:30:00', label='scan')


@pytest.mark.parametrize('prefix', ['', 'B 1 2 S 2 0.04\n'])
@pytest.mark.parametrize('step', ['5.0', '-5.0', '.5', '0.04'])
def test_scan_decimal_steps_accepted(prefix, step):
    science = gaussian_input.validate(GJF + prefix + f'A 3 1 2 S 2 {step}\n\n', 8, 12)
    scan = science['scan']
    axis = scan['coordinates'][1] if prefix else scan
    assert axis['step_size'] == float(step)


@pytest.mark.parametrize('route', ['opt', 'sp', 'opt=(ts,modredundant)', 'opt=(qst2,modredundant)',
                                 'opt=(qst3,modredundant)', 'opt=modredundant external=test', 'opt=modredundant units=bohr'])
def test_extra_section_requires_plain_modredundant(route):
    with pytest.raises(ValueError):
        gaussian_input.validate(GJF.replace('opt=modredundant', route) + 'B 1 2 S 5 .1\n', 8, 12)


def test_scan_input_summary(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'peroxide.gjf'
    source.write_text(GJF + 'B 1 2 S 6 0.1\nA 3 1 2 F\n')
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
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
    plain = attempt.prepare(cfg, method_basis='兜底方法：合成测试', **kwargs)
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', constraints=constraint, **kwargs)
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
        attempt.prepare(cfg, method_basis='兜底方法：合成测试', **{**kwargs, 'params': {'--input': 'constraints.inp'}})
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


@pytest.mark.parametrize('energies', [ENERGIES, [-150, -149.999, -149.998]])
def test_1d_grid_point_argument_has_explicit_error(tmp_path, capsys, energies):
    scan, frames = synthetic_scan(energies)
    (tmp_path / 'manifest.json').write_text('{}')
    source = tmp_path / 'scan_points.xyz'
    source.write_text(xyz_text(frames))
    scan['geometries_sha256'] = sha256(source.read_bytes()).hexdigest()
    (tmp_path / 'facts.json').write_text(json.dumps({'scan': scan}))
    destination = tmp_path / 'peak.xyz'
    assert cli.main(['scan-peak', str(tmp_path), '--point', '2,2', '--out', str(destination)]) == 1
    assert '一维扫描只接受单个整数 --point' in capsys.readouterr().err
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

# T75: deterministic 2D grid mapping; energies are a synthetic saddle, not chemistry.
GRID_GEOMETRY = 'O 0 0 0\nO 1.4 0 0\nH 0 1 0\nH 1.4 0 1'
GRID_LINES = 'B 1 2 S 2 .2\nB 1 3 S 2 .2'


def grid_definition():
    return modredundant(GRID_LINES, GRID_GEOMETRY)['scan']


def grid_frame(i, j):
    symbols, coords = input_geometry(GRID_GEOMETRY)
    coords[1][0] += i * .2
    coords[2][1] += j * .2
    return Frame(tuple(symbols), tuple(tuple(p) for p in coords))


def grid_log(order, *, states=None):
    text = '# HF/STO-3G opt=modredundant\n -----\n'
    for i, j in order:
        energy = -150 + ((i - 1) ** 2 - (j - 1) ** 2) * .001
        text += orientation(grid_frame(i, j)) + f' SCF Done: E(RHF) = {energy - .1} A.U.\n'
        text += orientation(grid_frame(i, j)) + f' SCF Done: E(RHF) = {energy} A.U.\n'
        state = (states or {}).get((i, j), True)
        if state is not None:
            text += ' Optimization ' + ('completed' if state else 'stopped') + '.\n'
    return text


GRID_ORDERS = [
    [(i, j) for i in range(3) for j in range(3)],
    [(i, j) for j in range(3) for i in range(3)],
    [(i, j) for i in range(3) for j in (range(3) if i % 2 == 0 else reversed(range(3)))],
]


@pytest.mark.parametrize('order', GRID_ORDERS)
def test_2d_grid_maps_measured_coordinates_not_traversal(tmp_path, order):
    scan, xyz = parse_gaussian_scan(grid_log(order), grid_definition())
    source = tmp_path / 'grid.xyz'
    source.write_text(xyz)
    frames = read_xyz(source)
    assert len(frames) == 9 and scan['saddle_candidates'] == [[2, 2]]
    for i in range(3):
        for j in range(3):
            p = scan['points'][i][j]
            assert p['point'] == [i + 1, j + 1]
            assert p['target_values'] == pytest.approx([1.4 + i * .2, 1 + j * .2])
            assert p['coordinate_values'] == pytest.approx(p['target_values'])
            assert p['energy_hartree'] == pytest.approx(-150 + ((i - 1) ** 2 - (j - 1) ** 2) * .001)
            assert p['geometry_frame'] == order.index((i, j)) + 1
            for actual, expected in zip(frames[p['geometry_frame'] - 1].coordinates, grid_frame(i, j).coordinates):
                assert actual == pytest.approx(expected)


def test_2d_missing_and_unfinished_points_stay_null():
    order = [p for p in GRID_ORDERS[0] if p != (1, 1)]
    scan, _ = parse_gaussian_scan(grid_log(order), grid_definition())
    assert scan['points'][1][1] is None and scan['saddle_candidates'] == []
    assert sum(p is not None for row in scan['points'] for p in row) == 8
    scan, _ = parse_gaussian_scan(grid_log(order) + grid_log([(1, 1)], states={(1, 1): None}), grid_definition())
    assert scan['points'][1][1] is None
    scan, xyz = parse_gaussian_scan('', grid_definition())
    assert scan['points'] == [[None] * 3 for _ in range(3)] and not xyz


@pytest.mark.parametrize('which', ['far', 'half', 'duplicate', 'extra', 'no_geometry', 'wrong_atoms'])
def test_2d_bad_grid_refuses_entire_scan(tmp_path, which):
    order = GRID_ORDERS[0]
    text = grid_log(order)
    if which == 'far':
        text = text.replace(' 1.4 0.0 0.0', ' 1.0 0.0 0.0')
    elif which == 'half':
        text = text.replace(' 1.4 0.0 0.0', ' 1.3 0.0 0.0')
    elif which == 'duplicate':
        text = grid_log(order[:-1] + [order[0]])
    elif which == 'extra':
        text += grid_log([order[0]])
    elif which == 'no_geometry':
        text = ' SCF Done: E(RHF) = -150 A.U.\n Optimization completed.\n'
    else:
        text = text.replace(' 2 8 0 ', ' 2 1 0 ')
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'outputs/peroxide.log').write_text(text)
    (tmp_path / 'manifest.json').write_text(json.dumps({'template': 'gaussian', 'science': {'scan': grid_definition()}}))
    with pytest.raises(ValueError):
        build_facts(tmp_path)
    assert not (tmp_path / 'facts.json').exists()
    assert not (tmp_path / 'scan_points.xyz').exists()


@pytest.mark.parametrize('position', [(1, 1), (0, 1), (2, 1), (1, 0), (1, 2)])
@pytest.mark.parametrize('missing', [False, None, 'energy', 'point'])
def test_2d_saddle_requires_five_converged_points(position, missing):
    from ag._scan import saddle_candidates
    scan, _ = parse_gaussian_scan(grid_log(GRID_ORDERS[0]), grid_definition())
    i, j = position
    if missing == 'point':
        scan['points'][i][j] = None
    elif missing == 'energy':
        scan['points'][i][j]['energy_hartree'] = None
    else:
        scan['points'][i][j]['converged'] = missing
    assert saddle_candidates(scan['points']) == []


def test_2d_saddle_is_strict_in_both_axes():
    from ag._scan import saddle_candidates
    scan, _ = parse_gaussian_scan(grid_log(GRID_ORDERS[0]), grid_definition())
    for row in scan['points']:
        for point in row:
            point['energy_hartree'] *= -1
    assert [p['point'] for p in saddle_candidates(scan['points'])] == [[2, 2]]
    scan['points'][0][1]['energy_hartree'] = scan['points'][1][1]['energy_hartree']
    assert saddle_candidates(scan['points']) == []


@pytest.mark.parametrize('lines, message', [
    (GRID_LINES + '\nA 3 1 2 S 2 1.0', 'At most two'),
    ('B 1 2 S 2 .1\nB 1 2 S 2 .1', 'same atoms'),
    ('B 1 2 S 2 .1\nB 2 1 S 2 .1', 'same atoms'),
    ('A 3 1 2 S 2 1.0\nA 1 2 3 S 2 1.0', 'same atoms'),
    ('D 3 1 2 4 S 2 1.0\nD 4 2 1 3 S 2 1.0', 'same atoms'),
    ('B 1 2 S 20 .1\nB 1 3 S 20 .1', '441'),
    ('B 1 2 S 21 .1\nB 1 3 S 1 .1', '1–20'),
])
def test_2d_validation_limits(lines, message):
    with pytest.raises(ValueError, match=message):
        gaussian_input.validate(GJF.replace(GEOMETRY, GRID_GEOMETRY) + lines + '\n', 8, 12)


def test_2d_prepare_summary_and_limits(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'peroxide.gjf'
    source.write_text(GJF.replace(GEOMETRY, GRID_GEOMETRY) + GRID_LINES + '\nA 3 1 2 F\n')
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='scan2d')
    scan = m['science']['scan']
    assert scan['dimensions'] == 2 and scan['expected_points'] == 9
    text = attempt.summary(cfg, m)
    assert 'Scan dimension 1: B 1(O) 2(O) | Start: 1.4 | Steps: 2 | Step size: 0.2 | End: 1.8 angstrom' in text
    assert 'Scan dimension 2: B 1(O) 3(H) | Start: 1 | Steps: 2 | Step size: 0.2 | End: 1.4 angstrom' in text
    assert 'Total scan points: 9' in text and '每个点都是一次约束优化' in text
    assert 'Frozen coordinates: A 3(H) 1(O) 2(O)' in text
    attempt.verified_files(cfg, attempt.find(cfg, m['attempt_id']), m)
    assert modredundant('B 1 2 S 11 .1\nB 1 3 S 11 .1', GRID_GEOMETRY)['scan']['expected_points'] == 144
    assert modredundant('B 1 2 S 50 .1', GRID_GEOMETRY)['scan']['steps'] == 50


@pytest.mark.parametrize('json_output', [False, True])
def test_2d_facts_and_peak_cli(tmp_path, capsys, json_output):
    order = GRID_ORDERS[2]
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'outputs/peroxide.log').write_text(grid_log(order))
    (tmp_path / 'manifest.json').write_text(json.dumps({'template': 'gaussian', 'science': {'scan': grid_definition()}}))
    facts = build_facts(tmp_path)
    assert facts['scan']['saddle_candidates'] == [[2, 2]]
    assert build_facts(tmp_path) == facts
    dest = tmp_path / 'seed.xyz'
    args = ['scan-peak', str(tmp_path), '--out', str(dest)]
    for point in [[], ['--point', '1,1'], ['--point', '2'], ['--point', '0,2'], ['--point', '4,4']]:
        assert cli.main(args + point) == 1
        assert '全部候选: 2,2' in capsys.readouterr().err
        assert not dest.exists()
    assert cli.main(args + ['--point', '2,2'] + (['--json'] if json_output else [])) == 0
    output = capsys.readouterr().out
    if json_output:
        report = json.loads(output)
        assert report['dimensions'] == 2 and report['peak']['point'] == [2, 2]
        assert [p['point'] for p in report['saddle_candidates']] == [[2, 2]]
        assert report['saddle_candidates'][0]['relative_energy_kcal_mol'] == pytest.approx(.001 * HARTREE_TO_KCAL)
        assert len(report['neighbors_before']) == len(report['neighbors_after']) == 2
    else:
        assert 'TS 初猜：二维网格点 2,2' in output and '全部鞍点候选' in output
    for actual, expected in zip(read_xyz(dest)[0].coordinates, grid_frame(1, 1).coordinates):
        assert actual == pytest.approx(expected)
    assert cli.main(args + ['--point', '2,2']) == 1
    capsys.readouterr()
    (tmp_path / 'scan_points.xyz').write_text('changed')
    assert cli.main(['scan-peak', str(tmp_path), '--point', '2,2', '--out', str(tmp_path / 'other.xyz')]) == 1
    assert 'differs' in capsys.readouterr().err


def test_2d_negative_steps_and_periodic_dihedral():
    import math
    geom = 'H 0 1 0\nO 0 0 0\nO 1.4 0 0\nH 1.4 -0.984807753 0.173648178'
    spec = modredundant('D 1 2 3 4 S 2 10.0\nB 2 3 S 2 -.1', geom)['scan']
    log = ''
    for i, j in reversed(GRID_ORDERS[0]):
        theta = math.radians(spec['coordinates'][0]['start'] + i * 10)
        distance = 1.4 - j * .1
        f = Frame(('H', 'O', 'O', 'H'), ((0, 1, 0), (0, 0, 0), (distance, 0, 0),
                                         (distance, math.cos(theta), math.sin(theta))))
        log += orientation(f) + ' SCF Done: E(RHF) = -150 A.U.\n Optimization completed.\n'
    scan, _ = parse_gaussian_scan(log, spec)
    assert all(p is not None for row in scan['points'] for p in row)
    assert scan['points'][2][2]['coordinate_values'][0] < -160
    assert scan['points'][2][2]['target_values'][0] > 180
    assert scan['points'][2][2]['coordinate_values'][1] == pytest.approx(1.2)


def test_2d_periodic_alias_is_ambiguous():
    spec = modredundant('D 3 1 2 4 S 1 360.0\nB 1 2 S 1 .1', GEOMETRY)['scan']
    with pytest.raises(ValueError, match='uniquely'):
        parse_gaussian_scan(gaussian_log(ENERGIES[:1], [True]), spec)


def one_dimensional_snapshot(root, program):
    import contextlib
    import io
    from ag._scan import summary
    from ag.facts import parse_facts
    root.mkdir(parents=True)
    outputs = root / 'outputs'
    outputs.mkdir()
    (root / 'manifest.json').write_text(json.dumps({'template': program, 'science': {'scan': definition()}}))
    log = outputs / ('peroxide.log' if program == 'gaussian' else 'xtb.out')
    if program == 'xtb':
        (outputs / 'xtbscan.log').write_text(xyz_text([frame_at(i, e) for i, e in enumerate(ENERGIES)]))
    cases = {}
    for name, states in [('complete', [True] * 7), ('partial', [True, False, True, True, True, True, None])]:
        log.write_text(gaussian_log(ENERGIES, states) if program == 'gaussian' else xtb_stdout(states))
        facts, geometries = parse_facts(root)
        scan = facts['scan']
        (root / 'facts.json').write_text(json.dumps({'scan': scan}))
        (root / 'scan_points.xyz').write_text(geometries['scan_points.xyz'])
        case = {'scan': scan, 'xyz': geometries['scan_points.xyz']}
        for fmt in ['text', 'json']:
            dest = root / f'{name}-{fmt}.xyz'
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                assert cli.main(['scan-peak', str(root), '--point', '4', '--out', str(dest)] + (['--json'] if fmt == 'json' else [])) == 0
            case[fmt] = stream.getvalue().replace(str(dest), '<out>')
            case[fmt + '_xyz'] = dest.read_text()
        cases[name] = case
    cases['summary'] = summary({'scan': definition()})
    return {name: sha256(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()).hexdigest() for name,value in cases.items()}


# Byte baselines captured on main at 3ee74fc before T75 changes.
ONE_DIMENSIONAL_BASELINE = {
  "gaussian": {
    "complete": "dee9c0177aebed757b9bc646e892f8f46f8c3cade65cd1963c80a53d4a73164a",
    "partial": "3443feb945b2534377cf446dbfa05413bcee9c85d81cdee75ff762d317cfa543",
    "summary": "632b4a516bba77d9e6d4ae84e1303f7b6d6cc9d58b5c004c29f39eb47853ab3e"
  },
  "xtb": {
    "complete": "e58676d9af75a65c0b0cb89a8d5b24848225ca2ff851f5ce2bdb117c7dd67794",
    "partial": "7e25103152c02d9305d2dc66a1b3eb9983b4f94477a96f512f01dab32f08b9b5",
    "summary": "632b4a516bba77d9e6d4ae84e1303f7b6d6cc9d58b5c004c29f39eb47853ab3e"
  }
}


@pytest.mark.parametrize('program', ['gaussian', 'xtb'])
def test_1d_bytes_match_pre_t75_main(tmp_path, program):
    assert one_dimensional_snapshot(tmp_path / program, program) == ONE_DIMENSIONAL_BASELINE[program]


def test_2d_angle_and_small_coordinate_deviations():
    import math
    geom = 'O 0 0 0\nH 1 0 0\nH 0 1 0'
    spec = modredundant('B 1 2 S 2 .1\nA 2 1 3 S 2 10.0', geom)['scan']
    text = ''
    for i, j in reversed(GRID_ORDERS[0]):
        # Simulate the finite precision of real Cartesian orientations.
        distance = 1 + i * .1 + .000001
        angle = math.radians(90 + j * 10 + .000001)
        frame = Frame(('O', 'H', 'H'), ((0, 0, 0), (distance, 0, 0), (math.cos(angle), math.sin(angle), 0)))
        text += orientation(frame) + ' SCF Done: E(RHF) = -75 A.U.\n Optimization completed.\n'
    scan, _ = parse_gaussian_scan(text, spec)
    assert scan['saddle_candidates'] == []
    for i in range(3):
        for j in range(3):
            assert scan['points'][i][j]['target_values'] == pytest.approx([1 + i * .1, 90 + j * 10])
            assert scan['points'][i][j]['coordinate_values'] == pytest.approx([1 + i * .1 + .000001, 90 + j * 10 + .000001])
    with pytest.raises(ValueError, match=r'全部候选: \(none\)'):
        select_peak(scan, [], point=[2, 2])


def test_2d_stopped_point_and_missing_energy_never_borrowed():
    text = grid_log([(0, 0)]) + orientation(grid_frame(1, 0)) + ' Optimization stopped.\n'
    scan, _ = parse_gaussian_scan(text, grid_definition())
    assert scan['points'][1][0]['converged'] is False
    assert scan['points'][1][0]['energy_hartree'] is None
    assert scan['points'][2][0] is None


def test_2d_peak_lists_all_candidates_and_checks_grid_edges(tmp_path):
    spec = modredundant('B 1 2 S 4 .2\nB 1 3 S 2 .2', GRID_GEOMETRY)['scan']
    # Swap whole rows in output order. Frame-neighbor comparisons would create
    # spurious jumps; grid neighbors are always within the warning thresholds.
    order = [(i, j) for i in [4, 0, 3, 1, 2] for j in range(3)]
    text = ''
    x = [1, 0, 2, 0, 1]
    for i, j in order:
        energy = -150 + (x[i] - (j - 1) ** 2) * .001
        text += orientation(grid_frame(i, j)) + f' SCF Done: E(RHF) = {energy} A.U.\n Optimization completed.\n'
    scan, xyz = parse_gaussian_scan(text, spec)
    assert scan['saddle_candidates'] == [[2, 2], [4, 2]]
    with pytest.raises(ValueError, match='全部候选: 2,2; 4,2'):
        select_peak(scan, [])
    path = tmp_path / 'frames.xyz'
    path.write_text(xyz)
    report, chosen = select_peak(scan, read_xyz(path), point=[4, 2])
    assert report['peak']['point'] == [4, 2]
    assert report['jumps'] == []
    assert chosen.coordinates[1][0] == pytest.approx(2)
    # Saved hints alone cannot make a newly invalid point eligible.
    scan['points'][3][0]['converged'] = False
    with pytest.raises(ValueError, match='全部候选: 2,2$'):
        select_peak(scan, read_xyz(path), point=[4, 2])
