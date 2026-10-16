#!/usr/bin/env python3
"""Local, rigid, single-contact complex construction from human-supplied coordinates."""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import re

import numpy as np
from rdkit import Chem, rdBase

from ag import crest_input, geometry as geo
from check_species import input_bytes, safe_path, study_root

PARAMETERS = ('r', 'theta1', 'theta2', 'phi1', 'phi2', 'phi3')
# Reject near-collinearity before an ill-conditioned plane can assign an arbitrary
# torsion/face. This is a sine, not a distance; it is invariant under rigid motion.
PLANE_SINE_MIN = 1e-6
FACE_PLANAR_TOL = 0.1  # Å: a pyramidal/tetrahedral center has no trigonal Re/Si face.
MAIN_GROUP = set(range(1, 21)) | set(range(31, 39)) | set(range(49, 57)) | set(range(81, 89)) | set(range(113, 119))
DONORS = {'N', 'O', 'F', 'P', 'S', 'Cl', 'As', 'Se', 'Br', 'Sb', 'Te', 'I', 'Bi', 'Po', 'At', 'Ts'}
TABLE = Chem.GetPeriodicTable()
MAIN_GROUP_SYMBOLS = {TABLE.GetElementSymbol(n) for n in MAIN_GROUP}


def vector_unit(vector, label):
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        raise ValueError(f'{label}: coincident reference atoms')
    return vector / norm


def basis(a, b, c, label):
    axis = vector_unit(b - a, label)
    arm = vector_unit(c - a, label)
    perpendicular = arm - np.dot(arm, axis) * axis
    if np.linalg.norm(perpendicular) < PLANE_SINE_MIN:
        raise ValueError(f'{label}: collinear or nearly collinear reference atoms')
    perpendicular = vector_unit(perpendicular, label)
    return np.column_stack((axis, perpendicular, np.cross(axis, perpendicular)))


def angle(a, b, c):
    left, right = vector_unit(a - b, 'angle'), vector_unit(c - b, 'angle')
    return math.degrees(math.atan2(float(np.linalg.norm(np.cross(left, right))), float(np.dot(left, right))))


def torsion(points, label):
    a, b, c, d = points
    basis(b, c, a, label)
    basis(c, b, d, label)
    return geo.dihedral(points, (1, 2, 3, 4))


def place(a, b, c, distance, theta, phi, label):
    """Place d with angle(b,c,d)=theta and ag.geometry dihedral(a,b,c,d)=phi."""
    frame = basis(b, c, a, label)
    t, p = math.radians(theta), math.radians(phi)
    return c + distance * (frame @ np.array([-math.cos(t), math.sin(t) * math.cos(p), math.sin(t) * math.sin(p)]))


def refs(text, count, label):
    if not re.fullmatch(r'[1-9]\d*(?:,[1-9]\d*){2}', text):
        raise ValueError(f'{label}: supply three distinct 1-based indices separated by commas')
    values = tuple(map(int, text.split(',')))
    if len(set(values)) != 3 or max(values) > count:
        raise ValueError(f'{label}: indices must be distinct and within 1..{count}')
    return values


def adjacency(frame):
    """T86 radius rule: <1.2 times the covalent radii sum; no bond-order inference.

    Unlike topology's definite-edge classification, even ratios <0.6 count here:
    that uncertainty band must never hide a clash in a constructed complex.
    """
    neighbors = {i: set() for i in range(1, len(frame.symbols) + 1)}
    for i, symbol in enumerate(frame.symbols):
        for j in range(i):
            distance = math.dist(frame.coordinates[i], frame.coordinates[j])
            if distance < 1.2 * (TABLE.GetRcovalent(symbol) + TABLE.GetRcovalent(frame.symbols[j])):
                neighbors[i + 1].add(j + 1)
                neighbors[j + 1].add(i + 1)
    return neighbors


def check_component(frame, label):
    for i, symbol in enumerate(frame.symbols, 1):
        if symbol not in MAIN_GROUP_SYMBOLS:
            raise ValueError(f'{label}: atom {i} ({symbol}) is outside main-group scope (transition/f-block elements refused)')
    neighbors = adjacency(frame)
    reached, pending = set(), [1]
    while pending:
        atom = pending.pop()
        if atom not in reached:
            reached.add(atom)
            pending.extend(neighbors[atom] - reached)
    if len(reached) != len(frame.symbols):
        raise ValueError(f'{label}: expected a single connected molecule under the <1.2 radius rule')
    return neighbors


def check_references(host, guest, host_atoms, guest_atoms):
    check_component(host, 'host')
    neighbors = check_component(guest, 'guest')
    p2, p1, a = refs(host_atoms, len(host.symbols), 'host-atoms P2,P1,A')
    d, x, y = refs(guest_atoms, len(guest.symbols), 'guest-atoms D,X,Y')
    if x not in neighbors[d] or y not in neighbors[x]:
        raise ValueError('guest-atoms: D-X and X-Y must be connected by the radius rule')
    h, g = np.asarray(host.coordinates), np.asarray(guest.coordinates)
    basis(h[p2 - 1], h[p1 - 1], h[a - 1], 'host P2,P1,A')
    basis(g[d - 1], g[x - 1], g[y - 1], 'guest D,X,Y')
    return (p2, p1, a), (d, x, y)


def measure(host, guest, host_atoms, guest_atoms):
    hi, gi = check_references(host, guest, host_atoms, guest_atoms)
    p2, p1, a = (np.asarray(host.coordinates[i - 1]) for i in hi)
    d, x, y = (np.asarray(guest.coordinates[i - 1]) for i in gi)
    return dict(r=float(np.linalg.norm(a - d)), theta1=angle(p1, a, d), theta2=angle(a, d, x),
                phi1=torsion([p2, p1, a, d], 'phi1 P2,P1,A,D'),
                phi2=torsion([p1, a, d, x], 'phi2 P1,A,D,X'),
                phi3=torsion([a, d, x, y], 'phi3 A,D,X,Y'))


def build_geometry(host, guest, host_atoms, guest_atoms, parameters):
    hi, gi = check_references(host, guest, host_atoms, guest_atoms)
    values = {key: geo.finite_number(parameters[key]) for key in PARAMETERS}
    if values['r'] <= 0:
        raise ValueError('r must be positive')
    for key in ('theta1', 'theta2'):
        if not 0 < values[key] < 180 or math.sin(math.radians(values[key])) < PLANE_SINE_MIN:
            raise ValueError(f'{key}: angle near 0 or 180 degrees makes its dihedral undefined')
    p2, p1, a = (np.asarray(host.coordinates[i - 1]) for i in hi)
    old = np.asarray(guest.coordinates)
    d, x, y = (old[i - 1] for i in gi)
    nd = place(p2, p1, a, values['r'], values['theta1'], values['phi1'], 'phi1 P2,P1,A,D')
    nx = place(p1, a, nd, float(np.linalg.norm(x - d)), values['theta2'], values['phi2'], 'phi2 P1,A,D,X')
    ny = place(a, nd, nx, float(np.linalg.norm(y - x)), angle(d, x, y), values['phi3'], 'phi3 A,D,X,Y')
    rotation = basis(d, x, y, 'guest D,X,Y') @ basis(nd, nx, ny, 'placed D,X,Y').T
    coordinates = (old - d) @ rotation + nd
    if not np.isfinite(coordinates).all():
        raise ValueError('constructed coordinates must be finite')
    placed = replace(guest, coordinates=tuple(map(tuple, coordinates)), energy=None)
    measured = measure(host, placed, host_atoms, guest_atoms)
    deviations = {key: geo.periodic_difference(measured[key], values[key]) if key.startswith('phi')
                  else abs(measured[key] - values[key]) for key in PARAMETERS}
    if any(not math.isfinite(value) or value >= 1e-6 for value in deviations.values()):
        raise ValueError(f'six-coordinate reconstruction tolerance exceeded: {deviations}')
    distance_error = max((abs(math.dist(old[i], old[j]) - math.dist(coordinates[i], coordinates[j]))
                          for i in range(len(old)) for j in range(i)), default=0.0)
    if distance_error >= 1e-8:
        raise ValueError(f'guest rigid-distance tolerance exceeded: {distance_error}')
    return placed, measured, deviations, distance_error


def contact_report(host, guest, a, d, vdw_factor=None):
    if vdw_factor is not None and (not math.isfinite(vdw_factor) or vdw_factor <= 0):
        raise ValueError('vdw-factor must be finite and positive')
    contacts = []
    for i, (hs, hc) in enumerate(zip(host.symbols, host.coordinates), 1):
        for j, (gs, gc) in enumerate(zip(guest.symbols, guest.coordinates), 1):
            distance = math.dist(hc, gc)
            cr = distance / (TABLE.GetRcovalent(hs) + TABLE.GetRcovalent(gs))
            vr = distance / (TABLE.GetRvdw(hs) + TABLE.GetRvdw(gs))
            exempt = (i, j) == (a, d)
            violations = [] if exempt else (['unexpected_bond'] if cr < 1.2 else [])
            if not exempt and vdw_factor is not None and vr < vdw_factor:
                violations.append('vdw_overlap')
            contacts.append(dict(host_atom=i, guest_atom=j, complex_atoms=[i, len(host.symbols) + j],
                                 elements=[hs, gs], distance=distance, covalent_radius_ratio=cr,
                                 vdw_radius_ratio=vr, declared_contact=exempt, violations=violations))
    return dict(covalent_factor=1.2, vdw_factor=vdw_factor,
                violations=[c for c in contacts if c['violations']],
                nearest_10=sorted(contacts, key=lambda c: (c['distance'], c['host_atom'], c['guest_atom']))[:10])


def face_label(guest, attacker, center, priority):
    if not 1 <= center <= len(guest.symbols):
        raise ValueError('face-center is outside the guest atom range')
    indices = refs(priority, len(guest.symbols), 'face-priority')
    neighbors = adjacency(guest)
    if set(indices) != neighbors[center] or center in indices:
        raise ValueError('face-priority must be the three connected atoms surrounding a trigonal face-center')
    points = np.asarray(guest.coordinates)
    a, b, c = (points[i - 1] for i in indices)
    normal = basis(a, b, c, 'face-priority plane')[:, 2]
    origin = points[center - 1]
    if abs(float(np.dot(origin - a, normal))) > FACE_PLANAR_TOL:
        raise ValueError('face-center is not in the trigonal plane (tolerance 0.1 Å)')
    # A center outside the triangle cannot define this three-substituent face.
    barycentric = np.linalg.lstsq(np.column_stack((b - a, c - a)), origin - a, rcond=None)[0]
    if min(*barycentric, 1 - sum(barycentric)) <= 0:
        raise ValueError('face-priority atoms do not surround face-center')
    signed_distance = float(np.dot(np.asarray(attacker) - a, normal))
    if abs(signed_distance) < 0.3:
        raise ValueError('A is nearly in the face plane: distance < 0.3 Å')
    # Positive normal sees a→b→c counterclockwise; clockwise from A is Re.
    return dict(label='Re' if signed_distance < 0 else 'Si', center=center,
                priority=list(indices), priority_source='human-supplied; CIP not inferred',
                signed_plane_distance=signed_distance)


def site_labels(host, guest, a, d, x, face=None, face_center=None, face_priority=None, syn_anti_ref=None):
    result = dict(donor={'guest_atom': d, 'element': guest.symbols[d - 1]}, face=None, syn_anti=None)
    label = f'{guest.symbols[d - 1]}{d}'
    if syn_anti_ref is not None:
        if syn_anti_ref == d or syn_anti_ref not in adjacency(guest)[x]:
            raise ValueError('syn-anti-ref must be connected to X and distinct from D and X')
        points = [np.asarray(host.coordinates[a - 1]), *(np.asarray(guest.coordinates[i - 1]) for i in (d, x, syn_anti_ref))]
        value = torsion(points, 'syn/anti A,D,X,ref')
        tag = 'syn' if abs(value) < 90 else 'anti'
        result['syn_anti'] = dict(label=tag, dihedral=value, guest_atoms=[d, x, syn_anti_ref], host_atom=a)
        label += f'-{tag}({guest.symbols[syn_anti_ref - 1]}{syn_anti_ref})'
    if face is not None:
        result['face'] = face_label(guest, host.coordinates[a - 1], face_center, face_priority)
        result['face'].update(expected=face, host_atom=a)
        label += '-' + result['face']['label']
    result['label'] = label
    return result


def sites(frame):
    neighbors = check_component(frame, 'guest')
    points = np.asarray(frame.coordinates)
    result = []
    for i, symbol in enumerate(frame.symbols, 1):
        if symbol not in DONORS:
            continue
        linked = sorted(neighbors[i])
        hint = 'undetermined from geometry'
        if len(linked) == 1:
            hint = 'terminal sp2-like O possible' if symbol == 'O' else 'terminal; hybridization undetermined'
        elif len(linked) == 2:
            value = angle(points[linked[0] - 1], points[i - 1], points[linked[1] - 1])
            hint = 'linear sp-like' if value > 165 else 'bent sp3-like O' if symbol == 'O' else 'bent; sp2/sp3 ambiguous'
        elif len(linked) == 3:
            a, b, c = (points[j - 1] for j in linked)
            try:
                height = abs(float(np.dot(points[i - 1] - a, basis(a, b, c, 'site plane')[:, 2])))
                hint = 'planar sp2-like' if height <= FACE_PLANAR_TOL else 'pyramidal sp3-like'
            except ValueError:
                pass
        references = []
        for x in linked:
            candidates = []
            for y in sorted(neighbors[x] - {i}):
                try:
                    basis(points[i - 1], points[x - 1], points[y - 1], 'site reference')
                    candidates.append(y)
                except ValueError:
                    continue
            references.append(dict(D=i, X=x, Y_candidates=candidates, syn_anti_candidates=candidates))
        result.append(dict(atom=i, element=symbol, connected_atoms=linked, geometry_hint=hint,
                           direction_references=references))
    return dict(sites=result, notice='Candidates and geometric hints only; no site selection, bond order, charge, lone-pair vector or CIP inference.')


def read_frame(root, relative, inputs):
    input_bytes(root, relative, inputs)
    frames = geo.read_xyz(safe_path(root, relative))
    input_bytes(root, relative, inputs)
    if len(frames) != 1:
        raise ValueError('expected exactly one XYZ frame with three Cartesian coordinates per atom')
    return frames[0]


def split_complex(frame, host_range):
    match = re.fullmatch(r'([1-9]\d*)-([1-9]\d*)', host_range)
    if not match or not 1 <= int(match[1]) <= int(match[2]) <= len(frame.symbols):
        raise ValueError('host-range must be a continuous, ascending 1-based range within the complex')
    start, end = map(int, match.groups())
    host_indices = list(range(start - 1, end))
    guest_indices = [i for i in range(len(frame.symbols)) if i not in host_indices]
    if not guest_indices:
        raise ValueError('host-range must leave a nonempty guest')
    return tuple(geo.Frame(tuple(frame.symbols[i] for i in indices), tuple(frame.coordinates[i] for i in indices))
                 for indices in (host_indices, guest_indices))


def xyz_text(host, guest, name, charge, multiplicity):
    # 17 significant digits retain input host coordinates and precision on disk.
    return f'{len(host.symbols) + len(guest.symbols)}\n{name} charge={charge} multiplicity={multiplicity}\n' + ''.join(
        f'{s} {x:.17g} {y:.17g} {z:.17g}\n' for frame in (host, guest)
        for s, (x, y, z) in zip(frame.symbols, frame.coordinates))


def markdown(report):
    lines = [f"# {report['name']}: {report['status']}", '',
             f"总电荷 {report['charge']}；多重度 {report['multiplicity']}（人提供）。", '',
             '参数：Å / 度；组分内编号从 1 开始；主体在前、客体在后。', '']
    for entry in report['inputs']:
        lines.append(f"- 输入 `{entry['path']}`；SHA-256 `{entry['sha256']}`")
    lines += ['', f"参照原子：`{json.dumps(report['references'])}`", '',
              '| 参数 | 指定 | 实测 | 偏差 |', '|---|---:|---:|---:|']
    for key in PARAMETERS:
        lines.append(f"| {key} | {report['parameters'][key]:.12g} | {report['measured'][key]:.12g} | {report['deviations'][key]:.3g} |")
    lines += ['', f"客体内部距离最大偏差：{report['guest_distance_max_error']:.3g} Å。",
              f"位点标签及依据：`{json.dumps(report['site'], ensure_ascii=False)}`",
              f"约束草稿：`{json.dumps(report['constraints'], ensure_ascii=False)}`", '',
              '重叠规则：除 A–D 外，距离/共价半径和 < 1.2 拒绝；可选 vdW 因子：' + str(report['contacts']['vdw_factor'])]
    for title, contacts in [('全部违规接触', report['contacts']['violations']), ('最近 10 个接触（含声明 A–D）', report['contacts']['nearest_10'])]:
        lines += ['', f'## {title}', '', '| 主体 | 客体 | 元素 | 距离 Å | 共价半径比 | vdW 半径比 | 原因 |', '|---|---|---|---:|---:|---:|---|']
        for c in contacts:
            lines.append(f"| {c['host_atom']} | {c['guest_atom']} | {'–'.join(c['elements'])} | {c['distance']:.10g} | {c['covalent_radius_ratio']:.8g} | {c['vdw_radius_ratio']:.8g} | {', '.join(c['violations']) or ('A–D' if c['declared_contact'] else '—')} |")
    lines += ['', *['- ' + error for error in report['errors']], '',
              '这是定向初猜与约束草稿，默认交给人工审阅后的约束 CREST；不是结构签字、稳定复合物或 TS 验证。', '']
    return '\n'.join(lines)


def run_build(args):
    root = study_root(args.study)
    if not re.fullmatch(r'[\w-]{1,80}', args.name):
        raise ValueError('name must contain 1–80 letters, digits, underscores or hyphens')
    output_relative = f'analyses/complex-build/{args.name}'
    output = safe_path(root, output_relative)
    if output.exists():
        raise ValueError('output directory already exists; choose a new name')
    if args.multiplicity < 1:
        raise ValueError('multiplicity must be a positive integer supplied by the researcher')
    if not math.isfinite(args.force_constant) or args.force_constant <= 0:
        raise ValueError('force-constant must be finite and positive; no default is provided')
    if any(value is not None for value in (args.face, args.face_center, args.face_priority)) and not all(
            value is not None for value in (args.face, args.face_center, args.face_priority)):
        raise ValueError('face, face-center and face-priority must be supplied together')
    inputs = {}
    host = read_frame(root, args.host, inputs)
    guest = read_frame(root, args.guest, inputs)
    parameters = {key: getattr(args, key) for key in PARAMETERS}
    placed, measured, deviations, error = build_geometry(host, guest, args.host_atoms, args.guest_atoms, parameters)
    hi, gi = refs(args.host_atoms, len(host.symbols), 'host-atoms'), refs(args.guest_atoms, len(guest.symbols), 'guest-atoms')
    a, (d, x, _) = hi[-1], gi
    contacts = contact_report(host, placed, a, d, args.vdw_factor)
    errors = ['Atomic overlaps detected; no automatic rotation attempted.'] if contacts['violations'] else []
    labels = None
    try:
        labels = site_labels(host, placed, a, d, x, args.face, args.face_center, args.face_priority, args.syn_anti_ref)
        if args.face and labels['face']['label'] != args.face:
            errors.append(f"face mismatch: requested {args.face}, measured {labels['face']['label']}")
    except ValueError as exc:
        errors.append(str(exc))
    n_host = len(host.symbols)
    constraint = f'$constrain\n  force constant={args.force_constant:.17g}\n  distance: {a}, {n_host + d}, {parameters["r"]:.17g}\n'
    if args.constrain_angle:
        constraint += f'  angle: {a}, {n_host + d}, {n_host + x}, {parameters["theta2"]:.17g}\n'
    constraint += '$end\n'
    crest_input.validate(constraint, n_host + len(guest.symbols))
    report = dict(name=args.name, status='rejected' if errors else 'built',
                  charge=args.host_charge + args.guest_charge, multiplicity=args.multiplicity,
                  component_charges={'host': args.host_charge, 'guest': args.guest_charge},
                  inputs=list(inputs.values()), references={'host_P2_P1_A': list(hi), 'guest_D_X_Y': list(gi)},
                  parameters=parameters, measured=measured, deviations=deviations, guest_distance_max_error=error,
                  site=labels, label_requests={'face': args.face, 'face_center': args.face_center,
                                              'face_priority': args.face_priority, 'syn_anti_ref': args.syn_anti_ref},
                  contacts=contacts, errors=errors, rdkit_version=rdBase.rdkitVersion,
                  constraints={'force_constant': args.force_constant, 'constrain_angle': args.constrain_angle,
                               'text': constraint, 'validated': False, 'written': False})
    for entry in report['inputs']:
        input_bytes(root, entry['path'], inputs)
    safe_path(root, 'analyses/complex-build').mkdir(parents=True, exist_ok=True)
    safe_path(root, output_relative).mkdir()  # Exclusive, including concurrent/rejected runs.
    if not errors:
        with safe_path(root, output_relative + '/complex.xyz').open('x') as stream:
            stream.write(xyz_text(host, placed, args.name, report['charge'], args.multiplicity))
        # Confirm precision of the delivered bytes, not just the in-memory result.
        written = geo.read_xyz(safe_path(root, output_relative + '/complex.xyz'))[0]
        wh, wg = split_complex(written, f'1-{n_host}')
        if wh.coordinates != host.coordinates or wg.coordinates != placed.coordinates:
            raise ValueError('serialized coordinates changed; partial output retained')
        with safe_path(root, output_relative + '/constraints.inp').open('x') as stream:
            stream.write(constraint)
        crest_input.validate(safe_path(root, output_relative + '/constraints.inp').read_text(), len(written.symbols))
        report['constraints'].update(validated=True, written=True)
        with safe_path(root, output_relative + '/atoms.csv').open('x', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['complex_index', 'component', 'source_file', 'source_index', 'element'])
            offset = 0
            for component, frame, source in [('host', host, args.host), ('guest', guest, args.guest)]:
                for i, symbol in enumerate(frame.symbols, 1):
                    writer.writerow([offset + i, component, source, i, symbol])
                offset += len(frame.symbols)
    for name, data in [('build.json', json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'), ('build.md', markdown(report))]:
        with safe_path(root, output_relative + '/' + name).open('x') as stream:
            stream.write(data)
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    site = commands.add_parser('sites', help='List possible donor sites; never select one')
    site.add_argument('--study', default='.')
    site.add_argument('--guest', required=True, help='XYZ path relative to study (default: current directory)')
    query = commands.add_parser('measure', help='Measure six relative coordinates; indices are component-local')
    query.add_argument('--study', default='.')
    query.add_argument('--complex', required=True, help='XYZ path relative to study (default: current directory)')
    query.add_argument('--host-range', required=True)
    query.add_argument('--host-atoms', required=True)
    query.add_argument('--guest-atoms', required=True)
    build = commands.add_parser('build', help='Rigid placement, checks and CREST constraint draft')
    for name in ('study', 'name', 'host', 'guest', 'host-atoms', 'guest-atoms'):
        build.add_argument('--' + name, required=True)
    for name in ('host-charge', 'guest-charge', 'multiplicity'):
        build.add_argument('--' + name, required=True, type=int)
    for name in (*PARAMETERS, 'force-constant'):
        build.add_argument('--' + name, required=True, type=geo.finite_number)
    build.add_argument('--face', choices=['Re', 'Si'])
    build.add_argument('--face-center', type=int)
    build.add_argument('--face-priority')
    build.add_argument('--syn-anti-ref', type=int)
    build.add_argument('--vdw-factor', type=geo.finite_number)
    build.add_argument('--constrain-angle', action='store_true')
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if args.command == 'build':
            report = run_build(args)
            print(json.dumps(report, ensure_ascii=False, allow_nan=False))
            return 2 if report['status'] == 'rejected' else 0
        root, inputs = study_root(args.study), {}
        if args.command == 'sites':
            report = sites(read_frame(root, args.guest, inputs))
        else:
            host, guest = split_complex(read_frame(root, args.complex, inputs), args.host_range)
            values = measure(host, guest, args.host_atoms, args.guest_atoms)
            report = dict(parameters=values, host_atoms=args.host_atoms, guest_atoms=args.guest_atoms,
                          build_parameters=' '.join(f'--{key}={value:.17g}' for key, value in values.items()))
        report['inputs'] = list(inputs.values())
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        cli.exit(2, f'ERROR: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
