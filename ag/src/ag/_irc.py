"""Reported Gaussian IRC facts, without assigning endpoint identity.

The directional completion/point checks adapt pure logic from
archive/skills/auto-g16-ts-irc/scripts/ts_irc.py (audit_irc_endpoint_provenance).
No legacy execution or acceptance machinery is imported.
"""

import re

from ag._parse_outputs import NUMBER, number, xyz_text


def parse_irc(text):
    """Return IRC facts and the last *reported path point* geometry.

    Point Number is printed after corrector convergence, unlike SCF/geometry
    records from trial corrector iterations. Do not export a failed trial as
    the endpoint. Counts exclude the TS (point zero); energies are Hartree.
    """
    from cclib.parser.utils import PeriodicTable

    routes = list(re.finditer(
        r'(?m)^[ \t]*(#(?!\s+OF\b)[^\n]*(?:\n(?!\s*-{5,})[^\n]+)*)\n\s*-{5,}', text))
    irc_routes = [i for i, match in enumerate(routes) if re.search(r'\birc\b', match[1], re.I)]
    if irc_routes:
        index = irc_routes[-1]
        section = text[routes[index].start():routes[index + 1].start() if index + 1 < len(routes) else len(text)]
        route = ' '.join(routes[index][1].split())
    elif re.search(r'INPUT DATA FOR L123|Point Number:\s*\d+\s+Path Number:', text, re.I):
        section, route = text, ''
    else:
        return None, None
    directions = {d.lower() for d in re.findall(r'\b(forward|reverse)\b', route, re.I)}
    if not directions:
        directions = {value.lower() for groups in re.findall(
            r'Rxn path following direction\s*=\s*(Forward|Reverse)|'
            r'Point Number\s*\d+ in (FORWARD|REVERSE) path direction', section, re.I)
            for value in groups if value}
    if not directions:
        directions = {d.lower() for d in re.findall(r'Calculation of\s+(FORWARD|REVERSE)\s+path', section, re.I)}
    if re.search(r'Follow reaction path in both directions', section, re.I):
        directions = {'forward', 'reverse'}
    direction = next(iter(directions)) if len(directions) == 1 else 'both' if len(directions) == 2 else 'unknown'
    limit = re.search(r'Maximum points per path\s*=\s*(\d+)', section, re.I)
    if limit is None:
        limit = re.search(r'\bMaxPoints\s*=\s*(\d+)', route, re.I)
    max_points = int(limit[1]) if limit else None
    orientation = re.compile(
        r'(?:Standard|Input|Z-Matrix) orientation:\s*\n\s*-+\n.*?\n\s*-+\n'
        r'(?P<atoms>(?:[ \t]*\d+[ \t]+\d+[ \t]+-?\d+[ \t]+[^\n]+\n)+)\s*-+', re.S)
    events = []
    for match in orientation.finditer(section):
        rows = [row.split() for row in match['atoms'].splitlines()]
        if any(len(row) != 6 or int(row[0]) != i + 1 for i, row in enumerate(rows)):
            continue
        table = PeriodicTable().element
        if any(not 0 < int(row[1]) < len(table) for row in rows):
            continue
        geometry = xyz_text([table[int(row[1])] for row in rows],
                            [[number(x) for x in row[3:]] for row in rows])
        events.append((match.end(), 'geometry', geometry))
    for match in re.finditer(r'SCF Done:.*?=\s*(' + NUMBER + ')', section):
        events.append((match.end(), 'energy', number(match[1])))
    for match in re.finditer(r'Point Number:\s*(\d+)\s+Path Number:\s*(\d+)', section, re.I):
        events.append((match.end(), 'point', (int(match[1]), int(match[2]))))
        # LQA (and verbose IRC output) prints the accepted CURRENT STRUCTURE
        # after the point label. Prefer that over the preceding SCF orientation.
        structure = re.match(
            r'\s*CURRENT STRUCTURE\s*\n\s*Cartesian Coordinates \(Ang\):\s*\n'
            r'\s*-+\n.*?\n\s*-+\n(?P<atoms>(?:[ \t]*\d+[ \t]+\d+[ \t]+[^\n]+\n)+)\s*-+',
            section[match.end():], re.S)
        if structure and int(match[1]) > 0:
            rows = [row.split() for row in structure['atoms'].splitlines()]
            table = PeriodicTable().element
            if all(len(row) == 5 and int(row[0]) == i + 1 and 0 < int(row[1]) < len(table)
                   for i, row in enumerate(rows)):
                geometry = xyz_text([table[int(row[1])] for row in rows],
                                    [[number(x) for x in row[2:]] for row in rows])
                events.append((match.end() + structure.end(), 'endpoint', geometry))
    points, current, endpoint = {}, {}, None
    for offset, kind, value in sorted(events):
        if kind == 'endpoint':
            if points:
                endpoint = value
            continue
        if kind != 'point':
            current[kind] = value
            continue
        point, path = value
        if point == 0:
            continue
        points[path, point] = {'path': path, 'point': point,
                              'energy_hartree': current.get('energy')}
        endpoint = current.get('geometry')
        # Missing data in the next point must not borrow this point's values.
        current = {}
    failed = bool(re.search(
        r'Maximum number of corrector steps exce(?:e)?ded|'
        r'corrector[^\n]*(?:failed|failure)|(?:failed|failure)[^\n]*corrector', section, re.I))
    reached = bool(re.search(r'(?:maximum number of (?:IRC )?points|MaxPoints)[^\n]*(?:reached|exce(?:e)?ded)', section, re.I))
    if max_points is not None:
        reached = reached or any(point >= max_points for path, point in points)
    else:
        reached = True if reached else None
    complete = {d.lower() for d in re.findall(r'Calculation of\s+(FORWARD|REVERSE)\s+path complete', section, re.I)}
    reported_complete = bool(complete) if direction == 'unknown' else directions <= complete
    return {'direction': direction, 'point_count': len(points),
            'max_points': max_points, 'reached_max_points': reached,
            'corrector_failed': failed, 'path_complete_reported': reported_complete,
            'energies': list(points.values()), 'energy_kind': 'scf', 'end_geometry': None,
            'end_geometry_source': 'last_reported_path_point' if endpoint else None,
            'end_geometry_warning': 'Both directions in one log; last reported point only' if direction == 'both' else None}, endpoint


def parse_irc_points(text):
    """Return accepted points (including an explicitly printed zero) with lines.

    Separate from parse_irc to preserve historical facts byte for byte. LQA's
    CURRENT STRUCTURE is the accepted geometry, not the last trial orientation.
    Missing data is never borrowed across point markers; later Link1 jobs and
    unaccepted corrector trials cannot replace an accepted point.
    """
    from cclib.parser.utils import PeriodicTable

    routes = list(re.finditer(
        r'(?m)^[ \t]*(#(?!\s+OF\b)[^\n]*(?:\n(?!\s*-{5,})[^\n]+)*)\n\s*-{5,}', text))
    indices = [i for i, match in enumerate(routes) if re.search(r'\birc\b', match[1], re.I)]
    start, end = 0, len(text)
    if indices:
        index = indices[-1]
        start = routes[index].start()
        end = routes[index + 1].start() if index + 1 < len(routes) else len(text)
    section = text[start:end]
    facts, _ = parse_irc(section)
    if facts is None:
        return None
    base = text.count('\n', 0, start)

    def line(offset):
        return base + section.count('\n', 0, offset) + 1

    def geometry(match, columns):
        rows = [row.split() for row in match['atoms'].splitlines()]
        table = PeriodicTable().element
        if not rows or any(len(row) != columns or int(row[0]) != i + 1
                           or not 0 < int(row[1]) < len(table) for i, row in enumerate(rows)):
            return None
        return xyz_text([table[int(row[1])] for row in rows],
                        [[number(x) for x in row[-3:]] for row in rows])

    orientation = re.compile(
        r'(?:Standard|Input|Z-Matrix) orientation:\s*\n\s*-+\n[^\n]*\n[^\n]*\n\s*-+\n'
        r'(?P<atoms>(?:[ \t]*\d+[ \t]+\d+[ \t]+-?\d+[ \t]+[^\n]+\n)+)\s*-+', re.S)
    current_structure = re.compile(
        r'\s*CURRENT STRUCTURE\s*\n\s*Cartesian Coordinates \(Ang\):\s*\n'
        r'\s*-+\n[^\n]*\n[^\n]*\n\s*-+\n(?P<atoms>(?:[ \t]*\d+[ \t]+\d+[ \t]+[^\n]+\n)+)\s*-+', re.S)
    markers = list(re.finditer(r'Point Number:\s*(\d+)\s+Path Number:\s*(\d+)', section, re.I))
    points, previous, seen = [], 0, set()
    for index, marker in enumerate(markers):
        point, path = int(marker[1]), int(marker[2])
        if (path, point) in seen:
            raise ValueError('Duplicate accepted IRC point; geometry association is ambiguous')
        seen.add((path, point))
        block = section[previous:marker.start()]
        energies = list(re.finditer(r'SCF Done:.*?=\s*(' + NUMBER + ')', block))
        energy_kind = 'scf'
        if not energies and point == 0:
            energies = list(re.finditer(r'Energy From Chk\s*=\s*(' + NUMBER + ')', block, re.I))
            energy_kind = 'scf_from_checkpoint'
        orientations = list(orientation.finditer(block))
        xyz = geometry(orientations[-1], 6) if orientations else None
        geometry_line = line(previous + orientations[-1].start()) if orientations else None
        geometry_kind = 'preceding_orientation' if xyz else None
        # A present but malformed accepted table must not fall back to a trial.
        next_marker = markers[index + 1].start() if index + 1 < len(markers) else len(section)
        tail = section[marker.end():next_marker]
        if re.match(r'\s*CURRENT STRUCTURE', tail):
            structure = current_structure.match(tail)
            xyz = geometry(structure, 5) if structure else None
            geometry_line = line(marker.end() + len(tail) - len(tail.lstrip()))
            geometry_kind = 'current_structure'
        points.append(dict(point=point, path=path, point_line=line(marker.start()),
                           energy_hartree=number(energies[-1][1]) if energies else None,
                           energy_line=line(previous + energies[-1].start()) if energies else None,
                           energy_kind=energy_kind if energies else None,
                           geometry=xyz, geometry_line=geometry_line, geometry_kind=geometry_kind))
        previous = marker.end()
    patterns = {
        'corrector_failed': r'Maximum number of corrector steps exce(?:e)?ded|corrector[^\n]*(?:failed|failure)|(?:failed|failure)[^\n]*corrector',
        'path_complete_reported': r'Calculation of\s+(?:FORWARD|REVERSE)\s+path complete',
        'max_points': r'Maximum points per path\s*=\s*\d+|MaxPoints\s*=\s*\d+',
        'reached_max_points': r'(?:maximum number of (?:IRC )?points|MaxPoints)[^\n]*(?:reached|exce(?:e)?ded)',
        'normal_termination': r'Normal termination of Gaussian',
        'error_termination': r'Error termination',
    }
    return dict(points=points, facts=facts, section_start_line=base + 1,
                section_end_line=base + len(section.splitlines()),
                evidence_lines={key: [line(m.start()) for m in re.finditer(pattern, section, re.I)]
                                for key, pattern in patterns.items()})
