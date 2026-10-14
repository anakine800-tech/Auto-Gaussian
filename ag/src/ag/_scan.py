"""One-dimensional scan definitions and local point extraction.

Missing point evidence stays unknown; optimization iterations are not scan points.
xTB output semantics checked against grimme-lab/xtb v6.7.1:
src/scan_driver.f90 and src/optimizer.f90 (no source code copied).
"""
import math
import re
from dataclasses import replace

from ag.geometry import Frame, NUMBER, finite_number, read_xyz, xyz_text

COUNTS = {'B': 2, 'A': 3, 'D': 4}


def coordinate(kind, atoms, symbols):
    if len(atoms) != COUNTS[kind] or any(i < 1 or i > len(symbols) for i in atoms):
        raise ValueError('Scan coordinate atom index out of range')
    # A repeated atom makes the internal coordinate undefined, not a scan.
    if len(set(atoms)) != len(atoms):
        raise ValueError('Coordinate atom indices must be distinct')
    return dict(kind=kind, atoms=atoms, elements=[symbols[i - 1] for i in atoms],
                unit='angstrom' if kind == 'B' else 'degree')


def value(definition, coordinates):
    import numpy as np
    p = [np.array(coordinates[i - 1], dtype=float) for i in definition['atoms']]
    if definition['kind'] == 'B':
        result = float(np.linalg.norm(p[1] - p[0]))
    elif definition['kind'] == 'A':
        a, b = p[0] - p[1], p[2] - p[1]
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm == 0:
            raise ValueError('Undefined scan angle')
        result = math.degrees(math.acos(float(np.clip(a @ b / norm, -1, 1))))
    else:
        axis = p[2] - p[1]
        if np.linalg.norm(axis) == 0:
            raise ValueError('Undefined scan dihedral')
        axis /= np.linalg.norm(axis)
        a, b = p[0] - p[1], p[3] - p[2]
        a, b = a - (a @ axis) * axis, b - (b @ axis) * axis
        if min(np.linalg.norm(a), np.linalg.norm(b)) < 1e-12:
            raise ValueError('Undefined scan dihedral')
        result = math.degrees(math.atan2(float(np.cross(axis, a) @ b), float(a @ b)))
    return round(finite_number(result), 10)


def input_geometry(geometry):
    from cclib.parser.utils import PeriodicTable
    table = PeriodicTable().element
    symbols, coordinates = [], []
    for row in geometry.splitlines():
        symbol, *xyz = row.split()
        if symbol.isdigit() and 0 < int(symbol) < len(table):
            symbol = table[int(symbol)]
        if symbol not in table:
            raise ValueError('Scan requires real elements')
        symbols.append(symbol)
        coordinates.append([finite_number(x) for x in xyz])
    return symbols, coordinates


def modredundant(text, geometry):
    symbols, coordinates = input_geometry(geometry)
    scan, frozen = None, []
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in COUNTS:
            raise ValueError('ModRedundant permits only B, A or D coordinates')
        kind, n = fields[0], COUNTS[fields[0]]
        if len(fields) < n + 2 or not all(re.fullmatch(r'[0-9]+', x) for x in fields[1:n + 1]):
            raise ValueError('ModRedundant requires positive atom indices and an action')
        definition = coordinate(kind, list(map(int, fields[1:n + 1])), symbols)
        start = value(definition, coordinates)
        action = fields[n + 1]
        if action == 'F' and len(fields) == n + 2:
            frozen.append({**definition, 'value': start})
        elif action == 'S' and len(fields) == n + 4:
            if scan is not None:
                raise ValueError('Only one S line is supported')
            if not re.fullmatch(r'[0-9]+', fields[-2]) or not 1 <= int(fields[-2]) <= 50:
                raise ValueError('Scan steps must be 1–50')
            if not re.fullmatch(NUMBER, fields[-1]):
                raise ValueError('Scan step size must be finite and nonzero')
            step = finite_number(fields[-1])
            if step == 0:
                raise ValueError('Scan step size must be finite and nonzero')
            steps = int(fields[-2])
            scan = dict(coordinate=definition, start=start, steps=steps, step_size=step,
                        end=finite_number(start + steps * step), expected_points=steps + 1)
        else:
            raise ValueError('ModRedundant permits only F or S steps step_size')
    return {'scan': scan, 'frozen_coordinates': frozen}


def summary(science):
    scan = science.get('scan')
    def label(c):
        return c['kind'] + ' ' + ' '.join(f'{i}({e})' for i, e in zip(c['atoms'], c['elements']))
    text = ''
    if scan:
        text += (f"Scan: {label(scan['coordinate'])} | Start: {scan['start']:g} | "
                 f"Steps: {scan['steps']} | Step size: {scan['step_size']:g} | "
                 f"End: {scan['end']:g} {scan['coordinate']['unit']}\n\n")
        if scan['expected_points'] == 1:
            text += 'Warning: xTB 6.7.1 divides by points minus one; avoid a one-point scan.\n\n'
    if science.get('frozen_coordinates'):
        text += 'Frozen coordinates: ' + '; '.join(label(c) for c in science['frozen_coordinates']) + '\n\n'
    return text


def _result(definition, observations, energy_kind):
    points, frames = [], []
    expected = definition['expected_points']
    if len(observations) > expected:
        raise ValueError('More scan points than declared; cannot assign coordinate values')
    symbols = None
    for i in range(expected):
        frame, energy, converged = observations[i] if i < len(observations) else (None, None, None)
        point = dict(point=i + 1, target_value=definition['start'] + i * definition['step_size'],
                     coordinate_value=None, energy_hartree=energy, converged=converged,
                     geometry_frame=None)
        if frame:
            if symbols is not None and frame.symbols != symbols:
                raise ValueError('Scan atom order/count changed')
            symbols = frame.symbols
            c = definition['coordinate']
            if [symbols[j - 1] for j in c['atoms']] != c['elements']:
                raise ValueError('Scan geometry differs from coordinate definition')
            point['coordinate_value'] = value(c, frame.coordinates)
            frames.append(replace(frame, energy=energy, comment=f'scan point {i + 1}'))
            point['geometry_frame'] = len(frames)
        points.append(point)
    return {**definition, 'points': points, 'energy_kind': energy_kind,
            'geometries': 'scan_points.xyz' if frames else None}, xyz_text(frames)


def parse_gaussian_scan(text, definition):
    from cclib.parser.utils import PeriodicTable
    table = PeriodicTable().element
    orientation = re.compile(
        r'(?:Standard|Input|Z-Matrix) orientation:\s*\n\s*-+\n.*?\n\s*-+\n'
        r'(?P<atoms>(?:[ \t]*\d+[ \t]+\d+[ \t]+-?\d+[ \t]+[^\n]+\n)+)\s*-+', re.S)
    events = []
    for match in orientation.finditer(text):
        rows = [row.split() for row in match['atoms'].splitlines()]
        if any(len(r) != 6 or int(r[0]) != i + 1 or not 0 < int(r[1]) < len(table)
               for i, r in enumerate(rows)):
            raise ValueError('Invalid Gaussian scan orientation')
        frame = Frame(tuple(table[int(r[1])] for r in rows),
                      tuple(tuple(finite_number(x) for x in r[3:]) for r in rows))
        events.append((match.end(), 'geometry', frame))
    for match in re.finditer(r'SCF Done:.*?=\s*(' + NUMBER + ')', text):
        events.append((match.end(), 'energy', finite_number(match[1])))
    for match in re.finditer(r'Optimization (completed|stopped)\.', text):
        events.append((match.end(), 'point', match[1] == 'completed'))
    observations, current = [], {}
    for _, kind, item in sorted(events):
        if kind == 'point':
            observations.append((current.get('geometry'), current.get('energy'), item))
            current = {}
        else:
            current[kind] = item
    # An interrupted final optimization must not borrow the previous point.
    if current.get('energy') is not None and len(observations) < definition['expected_points']:
        observations.append((current.get('geometry'), current['energy'], None))
    return _result(definition, observations, 'scf')


def parse_xtb_scan(path, text, definition):
    frames = read_xyz(path)
    # xtb 6.7.1 scan_driver writes every frame, even when optimization fails.
    # xtbscan.log energies are unbiased Hartree. Convergence is only in xtb.out.
    text = text.split('RELAXED SCAN', 1)[-1]
    starts = list(re.finditer(r'(?m)^\s*\.\.\. step\s+(\d+)\s+\.\.\.\s*$', text))
    states = {}
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        section = text[match.end():end]
        n = int(match[1])
        if n in states:
            raise ValueError('Duplicate xTB scan step')
        failed = re.search(r'FAILED TO CONVERGE|GEOMETRY OPTIMIZATION (?:FAILED|NOT CONVERGED)', section, re.I)
        states[n] = False if failed else True if 'GEOMETRY OPTIMIZATION CONVERGED' in section else None
    if not starts:
        # Verbose scan_driver omits step labels, but prints exactly one optimizer
        # outcome per frame. A count mismatch cannot safely be aligned by position.
        outcomes = re.findall(r'GEOMETRY OPTIMIZATION CONVERGED|FAILED TO CONVERGE GEOMETRY OPTIMIZATION', text)
        if len(outcomes) == len(frames):
            states = {i: outcome == 'GEOMETRY OPTIMIZATION CONVERGED'
                      for i, outcome in enumerate(outcomes, 1)}
    observations = []
    for i, frame in enumerate(frames, 1):
        if frame.energy is None or frame.energy_unit != 'hartree':
            raise ValueError('xtbscan.log requires finite Hartree energy for each frame')
        observations.append((frame, frame.energy, states.get(i)))
    return _result(definition, observations, 'xtb_unbiased')
