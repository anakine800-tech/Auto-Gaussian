"""Read-only diagnostics of adjacent points on a one-dimensional scan."""
from copy import deepcopy
from hashlib import sha256
import json
import re

from ag import geometry as geo
from ag.irc_compare import _attempt, _pairs

NOTES = [
    '所有阈值只决定是否列出，不是科学判据；clean 仅表示未列出变化，不证明路径一致。',
    '沿程点多为受约束的非驻点；成键差异只说明几何变化，不说明极小点身份。',
    '不确定原子对既不算成键变化，也不算一致；未知部分不能作为未发生变化的证据。',
    'RMSD 保持原子编号、全原子等权且仅作刚体对齐；能差为相邻点绝对能差。',
]


def bond_argument(value):
    if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*', value):
        raise ValueError('Expected two distinct 1-based atoms: i-j')
    pair = tuple(sorted(map(int, value.split('-'))))
    if pair[0] == pair[1]:
        raise ValueError('Expected two distinct 1-based atoms: i-j')
    return pair


def add_options(parser):
    parser.add_argument('--expect-bond', type=bond_argument, action='append', default=[],
                        help='Expected bond change i-j (1-based); repeat for multiple pairs')
    parser.add_argument('--dihedral-threshold', type=float, default=60.0,
                        help='Report angular changes above this value in degrees (default 60)')
    parser.add_argument('--contact-cutoff', type=float, default=3.5,
                        help='Heavy-atom contact cutoff in angstrom (default 3.5)')
    parser.add_argument('--hbond-cutoff', type=float, default=2.5,
                        help='N/O/F-bound H to N/O/F contact cutoff in angstrom (default 2.5)')


def options(args):
    return dict(expected_bonds=args.expect_bond, dihedral_threshold=args.dihedral_threshold,
                contact_cutoff=args.contact_cutoff, hbond_cutoff=args.hbond_cutoff)


def manifest_charge(path):
    from ag.catalog_v2 import manifest_info
    try:
        values, _ = manifest_info(path.parent.parent, path.name)
        return values.get('charge')
    except (ValueError, OSError, KeyError, TypeError):
        return None


def torsions(left, right, charge, coordinate, threshold):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds
    if charge is None:
        return [], ['二面角未知：manifest 缺少可用电荷，无法推断单键。']
    try:
        mol = geo.infer_molecule(left, charge, Chem, rdDetermineBonds)
    except (ValueError, RuntimeError):
        return [], ['二面角未知：第一个点无法推断键级/成键图。']
    excluded = (set(coordinate['atoms'][1:3]) if coordinate['kind'] == 'D' else set())
    changes, reasons = [], []
    for bond in mol.GetBonds():
        b, c = sorted((bond.GetBeginAtomIdx() + 1, bond.GetEndAtomIdx() + 1))
        if (bond.GetBondType() != Chem.BondType.SINGLE or bond.IsInRing() or
                left.symbols[b - 1] == 'H' or left.symbols[c - 1] == 'H' or {b, c} == excluded):
            continue
        neighbors = [sorted(a.GetIdx() + 1 for a in mol.GetAtomWithIdx(i - 1).GetNeighbors()
                            if a.GetAtomicNum() != 1 and a.GetIdx() + 1 != other)
                     for i, other in ((b, c), (c, b))]
        if not all(neighbors):
            continue
        # One reproducible heavy-atom torsion per bond; no atom remapping.
        atoms = [neighbors[0][0], b, c, neighbors[1][0]]
        try:
            before, after = (geo.dihedral(f.coordinates, atoms) for f in (left, right))
        except ValueError:
            reasons.append(f'二面角未知：原子 {atoms} 构成退化平面。')
            continue
        delta = geo.periodic_difference(before, after)
        if delta > threshold:
            changes.append(dict(bond=[b, c], atoms=atoms, before_degrees=before,
                                after_degrees=after, change_degrees=delta))
    return changes, reasons


def contacts(frame, pairs, contact_cutoff, hbond_cutoff):
    heavy = [i for i, symbol in enumerate(frame.symbols, 1) if symbol != 'H']
    polar = {i for i, symbol in enumerate(frame.symbols, 1) if symbol in ('N', 'O', 'F')}
    donors = {i for i, symbol in enumerate(frame.symbols, 1) if symbol == 'H'
              and any(pairs[tuple(sorted((i, j)))]['state'] == 'bonded' for j in polar)}
    heavy_pairs = {tuple(pair) for pair in geo.contact_fingerprint(frame.coordinates, heavy, contact_cutoff)
                   if all(frame.symbols[i - 1] != 'H' for i in pair)}
    hbond_pairs = {tuple(pair) for pair in geo.contact_fingerprint(frame.coordinates, donors, hbond_cutoff)
                   if (pair[0] in donors and pair[1] in polar) or
                      (pair[1] in donors and pair[0] in polar)}
    return {'heavy': heavy_pairs, 'hbond': hbond_pairs}


def diagnose(scan, frames, charge, *, expected_bonds=(), dihedral_threshold=60.0,
             contact_cutoff=3.5, hbond_cutoff=2.5, metrics=None):
    """Single implementation used by scan-path and scan-peak, with no writes."""
    from ag.scan_peak import ENERGY_JUMP_KCAL, RMSD_JUMP_ANGSTROM, point_frame, step_metrics, metric_jump
    try:
        from rdkit import Chem
    except ImportError:
        Chem = None
    if scan.get('dimensions') == 2:
        raise ValueError('本单不支持二维扫描 / scan-path supports only one-dimensional scans')
    thresholds = dict(dihedral_degrees=geo.finite_number(dihedral_threshold),
                      contact_angstrom=geo.finite_number(contact_cutoff),
                      hbond_angstrom=geo.finite_number(hbond_cutoff),
                      energy_kcal_mol=ENERGY_JUMP_KCAL, rmsd_angstrom=RMSD_JUMP_ANGSTROM)
    if any(value <= 0 for value in thresholds.values()) or thresholds['dihedral_degrees'] > 180:
        raise ValueError('Reporting cutoffs must be positive; dihedral threshold must be <= 180 degrees')
    coordinate = scan['coordinate']
    automatic = [tuple(sorted(coordinate['atoms']))] if coordinate['kind'] == 'B' else []
    declared = sorted({tuple(sorted(pair)) for pair in expected_bonds})
    for pair in automatic + declared:
        if (len(pair) != 2 or any(type(i) is not int or i < 1 for i in pair) or pair[0] == pair[1]
                or (frames and pair[-1] > len(frames[0].symbols))):
            raise ValueError('Expected bond atoms must be distinct valid 1-based indices')
    expected = set(automatic + declared)
    points = [dict(point=p['point'], coordinate_value=p.get('coordinate_value'),
                   converged=p['converged'], energy_hartree=p['energy_hartree']) for p in scan['points']]
    segments = []
    for index, (a, b) in enumerate(zip(scan['points'], scan['points'][1:])):
        segment = dict(points=[a['point'], b['point']], status='unknown', bond_changes=[],
                       uncertain_pairs=[], dihedral_changes=[], contact_changes=[],
                       energy_change_kcal_mol=None, rmsd_angstrom=None, unknown_reason=[])
        segments.append(segment)
        if a['converged'] is not True or b['converged'] is not True:
            segment['unknown_reason'].append('相邻点未收敛或收敛证据缺失；不跨点比较。')
            continue
        try:
            left, right = point_frame(a, frames), point_frame(b, frames)
        except ValueError:
            segment['unknown_reason'].append('相邻点缺少几何；不跨点比较。')
            continue
        if left.symbols != right.symbols:
            segment['unknown_reason'].append('元素序列或原子数不一致，无法按编号比较。')
            continue
        segment.update(metrics[index] if metrics is not None else step_metrics(a, b, frames))
        if a['energy_hartree'] is None or b['energy_hartree'] is None:
            segment['unknown_reason'].append('相邻点能量缺失。')
        if Chem is None:
            segment['unknown_reason'].append('RDKit 不可用，成键、二面角和接触诊断未知。')
            segment['status'] = 'flagged' if metric_jump(segment) else 'unknown'
            continue
        try:
            before, after = _pairs(left, Chem), _pairs(right, Chem)
        except (ValueError, RuntimeError):
            segment['unknown_reason'].append('共价半径不可用，成键与接触比较未知。')
            segment['status'] = 'flagged' if metric_jump(segment) else 'unknown'
            continue
        for pair, first in before.items():
            second = after[pair]
            item = dict(atoms=list(pair), elements=[left.symbols[i - 1] for i in pair],
                        before_distance=first['distance'], after_distance=second['distance'],
                        before_state=first['state'], after_state=second['state'])
            if 'uncertain' in (first['state'], second['state']):
                segment['uncertain_pairs'].append(item)
            elif first['state'] != second['state'] and pair not in expected:
                segment['bond_changes'].append(item)
        segment['dihedral_changes'], reasons = torsions(
            left, right, charge, coordinate, thresholds['dihedral_degrees'])
        segment['unknown_reason'].extend(reasons)
        contacts_before, contacts_after = (contacts(f, p, thresholds['contact_angstrom'],
                                                   thresholds['hbond_angstrom'])
                                          for f, p in ((left, before), (right, after)))
        for kind in contacts_before:
            for pair in sorted(contacts_before[kind] ^ contacts_after[kind]):
                cutoff = thresholds['contact_angstrom' if kind == 'heavy' else 'hbond_angstrom']
                if (before[pair]['distance'] < cutoff) == (after[pair]['distance'] < cutoff):
                    # Donor uncertainty alone is not a distance crossing.
                    continue
                # A bonded pair at either end is a bond change, not a contact change.
                if any(p[pair]['state'] == 'bonded' for p in (before, after)):
                    continue
                segment['contact_changes'].append(dict(
                    kind=kind, atoms=list(pair), elements=[left.symbols[i - 1] for i in pair],
                    change='appeared' if pair in contacts_after[kind] else 'disappeared',
                    before_distance=before[pair]['distance'], after_distance=after[pair]['distance']))
        flagged = any(segment[key] for key in ('bond_changes', 'dihedral_changes', 'contact_changes'))
        segment['status'] = ('flagged' if flagged or metric_jump(segment) else
                             'unknown' if segment['unknown_reason'] else 'clean')
    summary = {}
    for status in ('flagged', 'unknown'):
        positions = [s['points'] for s in segments if s['status'] == status]
        summary[status + '_count'], summary[status + '_segments'] = len(positions), positions
    return dict(points=points, segments=segments, expected_bonds=dict(automatic=[list(p) for p in automatic],
                declared=[list(p) for p in declared]), thresholds=thresholds, notes=NOTES[:], summary=summary)


def near_peak(report, point):
    index = next(i for i, p in enumerate(report['points']) if p['point'] == point)
    segments = report['segments'][max(0, index - 2):index + 2]
    flagged = [s['points'] for s in segments if s['status'] == 'flagged']
    warning = ('峰可能被构象跳变或成键变化污染 / Peak may be contaminated by conformational or bonding changes: '
               + ', '.join(f'{a}→{b}' for a, b in flagged)) if flagged else None
    return dict(summary=report['summary'], segments=segments, warning=warning,
                thresholds=report['thresholds'], expected_bonds=report['expected_bonds'], notes=report['notes'])


def bounded_diagnostics(report, transform):
    """Fit the entire transform in T131's 64 KiB, retaining counts and warning."""
    result = deepcopy(report)
    def size():
        return len(json.dumps(dict(transform, path_diagnostics=result), ensure_ascii=True,
                              sort_keys=True, allow_nan=False).encode('utf-8'))
    if size() <= 65536:
        return result
    result.update(truncated=True, truncation_note='已截断 / truncated to fit the 64 KiB transform limit')
    result['expected_bond_counts'] = {key: len(value) for key, value in result['expected_bonds'].items()}
    for segment in result['segments']:
        segment['original_counts'] = {key: len(segment[key]) for key in
            ('bond_changes', 'uncertain_pairs', 'dihedral_changes', 'contact_changes', 'unknown_reason')}
    # Trim the largest detail list first; preserve segment locations/status and total counts.
    while size() > 65536:
        lists = [s[key] for s in result['segments'] for key in
                 ('bond_changes', 'uncertain_pairs', 'dihedral_changes', 'contact_changes', 'unknown_reason')]
        lists += [result['summary'][key] for key in ('flagged_segments', 'unknown_segments')]
        lists += list(result['expected_bonds'].values())
        nonempty = [items for items in lists if items]
        if not nonempty:
            break
        largest = max(nonempty, key=lambda items: len(json.dumps(items, ensure_ascii=False).encode('utf-8')))
        del largest[len(largest) // 2:]
    return result


def print_report(report):
    for note in report['notes']:
        print(note)
    for key in ('thresholds', 'expected_bonds', 'summary'):
        print(key + ': ' + json.dumps(report[key], ensure_ascii=False))
    print('point | coordinate | converged | energy (Hartree)')
    for p in report['points']:
        print(f"{p['point']} | {p['coordinate_value']} | {p['converged']} | {p['energy_hartree']}")
    print('segment | status | bonds | uncertain | dihedrals | contacts | ΔE (kcal/mol) | RMSD (Å)')
    for s in report['segments']:
        counts = ' | '.join(str(len(s[k])) for k in
                            ('bond_changes', 'uncertain_pairs', 'dihedral_changes', 'contact_changes'))
        print(f"{s['points'][0]}→{s['points'][1]} | {s['status']} | {counts} | "
              f"{s['energy_change_kcal_mol']} | {s['rmsd_angstrom']}")
        for key in ('bond_changes', 'uncertain_pairs', 'dihedral_changes', 'contact_changes', 'unknown_reason'):
            if s[key]:
                print('  ' + key + ': ' + json.dumps(s[key], ensure_ascii=False))


def run(args):
    path = _attempt(args.attempt, args.study)
    facts = json.loads((path / 'facts.json').read_text())
    scan = facts.get('scan')
    if not scan or scan.get('geometries') != 'scan_points.xyz':
        raise ValueError('No scan geometries; run ag facts first')
    if scan.get('dimensions') == 2:
        raise ValueError('本单不支持二维扫描 / scan-path supports only one-dimensional scans')
    source = path / 'scan_points.xyz'
    if source.is_symlink() or sha256(source.read_bytes()).hexdigest() != scan.get('geometries_sha256'):
        raise ValueError('scan_points.xyz differs from facts.json; review/regenerate facts')
    report = diagnose(scan, geo.read_xyz(source), manifest_charge(path), **options(args))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print_report(report)
    return 0


def register(subparsers):
    parser = subparsers.add_parser('scan-path', description=__doc__)
    parser.add_argument('attempt', help='Attempt directory or ID')
    parser.add_argument('--study', help='Study directory or configured study ID')
    parser.add_argument('--json', action='store_true')
    add_options(parser)
    parser.set_defaults(func=run)
