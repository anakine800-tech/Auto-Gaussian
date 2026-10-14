"""Export an interior converged scan geometry as a TS guess, never a TS verdict."""
from hashlib import sha256
import json
from pathlib import Path

from ag import geometry as geo
from ag.irc_compare import _attempt

# Warning heuristics only: large steps or steep chemistry can trigger them too.
ENERGY_JUMP_KCAL = 20.0
RMSD_JUMP_ANGSTROM = 0.5


def aligned_rmsd(left, right):
    import numpy as np
    if left.symbols != right.symbols:
        raise ValueError('Scan frames have different atom order/count')
    a, b = (np.array(f.coordinates, dtype=float) for f in (left, right))
    a, b = a - a.mean(axis=0), b - b.mean(axis=0)
    u, _, vt = np.linalg.svd(a.T @ b)
    correction = np.eye(3)
    correction[-1, -1] = 1 if np.linalg.det(u @ vt) >= 0 else -1
    return float(np.sqrt(np.mean(np.sum((a @ (u @ correction @ vt) - b) ** 2, axis=1))))


def select_peak(scan, frames):
    points = scan['points']
    if len(points) < 3:
        raise ValueError('At least three scan points are needed; endpoints cannot be exported')
    def energy(point):
        return geo.finite_number(point['energy_hartree'])
    def usable(point):
        return point['converged'] is True and point['energy_hartree'] is not None
    candidates = [i for i in range(1, len(points) - 1) if usable(points[i])]
    if not candidates:
        raise ValueError('No converged interior scan point')
    selected = max(candidates, key=lambda i: energy(points[i]))
    peak = points[selected]
    def frame(point):
        index = point.get('geometry_frame')
        if type(index) is not int or not 1 <= index <= len(frames):
            raise ValueError('Missing scan point geometry; regenerate/review ag facts')
        return frames[index - 1]
    chosen = frame(peak)
    warnings, jumps = [], []
    if any(usable(points[i]) and energy(points[i]) >= energy(peak) for i in (0, len(points) - 1)):
        warnings.append('范围不够，峰可能在范围外：端点能量不低于所选内部点；端点未参与初猜选择。')
    if any(p['converged'] is not True for p in points):
        warnings.append('有未收敛的点或收敛证据缺失的点；这些点未参与初猜选择。')
    for i, (left, right) in enumerate(zip(points, points[1:]), 1):
        delta = (abs(energy(right) - energy(left)) * geo.HARTREE_TO_KCAL
                 if left['energy_hartree'] is not None and right['energy_hartree'] is not None else None)
        rmsd = (aligned_rmsd(frame(left), frame(right))
                if left.get('geometry_frame') and right.get('geometry_frame') else None)
        if (delta is not None and delta > ENERGY_JUMP_KCAL) or (rmsd is not None and rmsd > RMSD_JUMP_ANGSTROM):
            jumps.append(dict(points=[i, i + 1], energy_change_kcal_mol=delta, rmsd_angstrom=rmsd))
    if jumps:
        warnings.append('可能跳到了另一条路径或另一个构象：相邻点能量或几何 RMSD 跳变，需人工审阅。')
    report = dict(peak=peak, coordinate=scan['coordinate'],
                  neighbors_before=points[max(0, selected - 2):selected],
                  neighbors_after=points[selected + 1:selected + 3], warnings=warnings, jumps=jumps,
                  warning_thresholds=dict(energy_kcal_mol=ENERGY_JUMP_KCAL, rmsd_angstrom=RMSD_JUMP_ANGSTROM),
                  note='仅为 TS 初猜，不判定 TS；邻点不足两点时仅列已有点。RMSD 保持原子编号、全原子等权且仅作刚体对齐。')
    return report, chosen


def run(args):
    if args.out.exists() or args.out.is_symlink():
        raise FileExistsError(f'Output already exists: {args.out}')
    path = _attempt(args.attempt, args.study)
    facts = json.loads((path / 'facts.json').read_text())
    scan = facts.get('scan')
    if not scan or scan.get('geometries') != 'scan_points.xyz':
        raise ValueError('No scan geometries; run ag facts first')
    source = path / 'scan_points.xyz'
    # Prevent exporting a different frame after somebody edits the multi-XYZ.
    if source.is_symlink() or sha256(source.read_bytes()).hexdigest() != scan.get('geometries_sha256'):
        raise ValueError('scan_points.xyz differs from facts.json; review/regenerate facts')
    report, frame = select_peak(scan, geo.read_xyz(source))
    geo.write_xyz(args.out, [frame])
    report['out'] = str(args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(report['note'])
        print(f"TS 初猜：point {report['peak']['point']} → {args.out}")
        for point in report['neighbors_before'] + [report['peak']] + report['neighbors_after']:
            print(f"point {point['point']}: coordinate={point['coordinate_value']} "
                  f"{scan['coordinate']['unit']}, energy={point['energy_hartree']} Hartree, "
                  f"converged={point['converged']}")
        for warning in report['warnings']:
            print('警告：' + warning)
    return 0


def register(subparsers):
    parser = subparsers.add_parser('scan-peak', description=__doc__)
    parser.add_argument('attempt', help='Attempt directory or ID')
    parser.add_argument('--study', help='Study directory or configured study ID')
    parser.add_argument('--out', type=Path, required=True, help='New XYZ file; existing files are refused')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
