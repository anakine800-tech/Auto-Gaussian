"""Gaussian/cclib and text output readers. Optional libraries load only on use."""

from contextlib import redirect_stderr, redirect_stdout
import io
import math
import re

NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'
HARTREE_TO_KCAL = 627.509541


def number(value):
    result = float(value.replace('D', 'E').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError('Non-finite number in calculation output')
    return result


def last_number(pattern, text):
    matches = re.findall('(?:' + pattern + r')\s*(' + NUMBER + ')', text, re.I)
    return number(matches[-1]) if matches else None


def termination(text, marker, pbs_text='', *, line_offset=0):
    error = re.search(r'Error termination|abnormal termination|fatal error|\[ERROR\]', text, re.I)
    links = list(re.finditer(r'Error termination via Lnk1e in .*?[/\\]l(\d+)\.exe', text, re.I))
    hint = None
    # A link identifies the exit point, not the cause (L9999 also reports a
    # wrong TS curvature at the first step). Prefer the last explicit cause
    # in this job section; never copy raw log text, which can contain paths.
    causes = []
    for pattern, label in (
        (r'Number of steps exceeded', '优化步数用完'),
        (r'Wrong number of Negative eigenvalues', 'TS 曲率不符：负本征值数与期望不符'),
        (r'Convergence failure|SCF(?: has)? not converged', 'SCF 不收敛'),
    ):
        causes.extend((match.start(), label) for match in re.finditer(pattern, text, re.I))
    # "Optimization stopped" alone is not evidence of a step limit.
    for stopped in re.finditer(r'Optimization stopped[^\n]*(?:\n[^\n]*){0,2}', text, re.I):
        limit = re.search(r'(?:maximum number of (?:optimization )?steps|'
                          r'(?:optimization )?step limit)\s+(?:has been\s+)?(?:reached|exceeded)',
                          stopped[0], re.I)
        if limit:
            causes.append((stopped.start() + limit.start(), '优化步数用完'))
    if causes:
        position, label = max(causes, key=lambda item: item[0])
        prefix = 'L' + links[-1][1] + ': ' if links else ''
        hint = prefix + label
    elif links:
        position = links[-1].start()
        hint = ('L9999: 优化未完成（原因见日志）' if links[-1][1] == '9999'
                else 'L' + links[-1][1])
    if hint:
        line = line_offset + text.count('\n', 0, position) + 1
        hint += f'（line {line}）'
    walltime = re.search(r'walltime.*(?:exceed|limit|kill)|(?:exceed|kill).*walltime', pbs_text, re.I)
    if walltime:
        hint = 'walltime'
    state = 'error' if error else ('normal' if marker.lower() in text.lower() else 'incomplete')
    return {'termination': state, 'error_hint': hint}


def imaginary_modes(frequencies, displacements, coordinates, elements):
    modes = []
    for frequency, vectors in zip(frequencies, displacements):
        if frequency >= 0:
            continue
        pairs = []
        for i, ri in enumerate(coordinates):
            for j in range(i + 1, len(coordinates)):
                dr = [a - b for a, b in zip(ri, coordinates[j])]
                distance = math.sqrt(sum(x*x for x in dr))
                if 0 < distance < 3.5:
                    rate = sum((a - b)*r for a, b, r in zip(vectors[i], vectors[j], dr)) / distance
                    pairs.append({'atoms': [i+1, j+1], 'elements': [elements[i], elements[j]],
                                  'distance': distance, 'distance_change_rate': float(rate)})
        pairs.sort(key=lambda pair: -abs(pair['distance_change_rate']))
        modes.append({'frequency': float(frequency), 'pairs': pairs[:5]})
    return modes


def xyz_text(elements, coordinates):
    return (f'{len(elements)}\nFinal parsed geometry\n' + ''.join(
        f'{element:2s} {x: .10f} {y: .10f} {z: .10f}\n'
        for element, (x, y, z) in zip(elements, coordinates)))


def gaussian_orientation(text, orientation):
    """Last printed orientation only; never fall back past a truncated table."""
    from cclib.parser.utils import PeriodicTable

    headers = list(re.finditer(r'(?m)^[ \t]*' + re.escape(orientation)
                               + r' orientation:[ \t]*$', text))
    if not headers:
        return None
    block = re.match(
        r'\s*\n[ \t]*-+\n[^\n]*Coordinates \(Angstroms\)[^\n]*\n'
        r'[^\n]*\n[ \t]*-+\n(?P<atoms>(?:[^\n]+\n)+?)[ \t]*-+(?:\n|$)',
        text[headers[-1].end():])
    if block is None:
        return None
    rows = [row.split() for row in block['atoms'].splitlines()]
    table = PeriodicTable().element
    try:
        if not rows or any(len(row) != 6 or int(row[0]) != i + 1
                           or not 0 < int(row[1]) < len(table)
                           for i, row in enumerate(rows)):
            return None
        return xyz_text([table[int(row[1])] for row in rows],
                        [[number(x) for x in row[3:]] for row in rows])
    except ValueError:
        return None



def _gaussian_routes(text):
    """Map opening separator lines (zero-based) to complete route echoes.

    IRC's '# OF POINTS' and '# OF STEPS' are body statistics, not routes.
    Keep the opening separator in the new section so extraction and boundary
    detection apply exactly the same rule, including wrapped route lines.
    """
    lines = text.splitlines()
    routes = {}
    separator = re.compile(r'[ \t]*-{5,}[ \t]*')
    i = 0
    while i < len(lines):
        if not separator.fullmatch(lines[i]):
            i += 1
            continue
        first = i + 1
        while first < len(lines) and not lines[first].strip():
            first += 1
        if first == len(lines) or not lines[first].lstrip().startswith('#'):
            i += 1
            continue
        end = first + 1
        while end < len(lines) and lines[end].strip() and not separator.fullmatch(lines[end]):
            end += 1
        if end < len(lines) and separator.fullmatch(lines[end]):
            routes[i] = ' '.join(' '.join(lines[first:end]).split())
            i = end + 1
        else:
            i = end
    return routes


def frequency_convergence(text):
    """Last post-frequency convergence check, scoped to its Gaussian job step.

    L1 showed that Opt convergence and positive frequencies can coexist with
    a failed displacement check. Never reuse an earlier Opt table or a table
    from another Link1 step when the frequency check is absent/truncated.
    """
    lines = text.splitlines()
    row_pattern = re.compile(
        r'^\s*(Maximum|RMS)\s+(Force|Displacement)\s+(' + NUMBER +
        r')\s+(' + NUMBER + r')\s+(YES|NO)\s*$', re.I)
    # Line numbers are local log evidence, never copies of paths or raw headers.
    route_lines = {start + 1: route for start, route in _gaussian_routes(text).items()}
    check = None
    active = False
    after_terminal = False
    for index, line in enumerate(lines, 1):
        if after_terminal and line.strip():
            # A new/truncated job after termination cannot inherit the old
            # check, even when its route echo is not complete enough to parse.
            check = None
            after_terminal = False
        if index in route_lines:
            active = False
            if re.search(r'\bfreq\b', route_lines[index], re.I):
                check = None
        if re.search(r'Normal termination of Gaussian|Error termination|'
                     r'Link1:.*Proceeding|Entering Gaussian System|^\s*--Link1--', line, re.I):
            active = False
        if re.match(r'[ \t]*(?:Normal termination of Gaussian|Error termination)\b', line, re.I):
            after_terminal = True
        if re.search(r'^\s*Harmonic frequencies\s*\(', line, re.I):
            active = True
            check = {'frequency_line': index, 'table_line': None,
                     'criteria': {}, 'non_optimized_parameters_line': None}
        if not active:
            continue
        if re.search(r'Item\s+Value\s+Threshold\s+Converged\?', line, re.I):
            check.update(table_line=index, criteria={}, non_optimized_parameters_line=None)
            for row_index in range(index, min(index + 4, len(lines))):
                match = row_pattern.fullmatch(lines[row_index])
                if match is None:
                    break
                kind, quantity, value, threshold, passed = match.groups()
                check['criteria'][f'{kind}_{quantity}'.lower()] = {
                    'value': number(value), 'threshold': number(threshold),
                    'converged': passed.upper() == 'YES', 'line': row_index + 1}
        if 'Non-Optimized Parameters' in line:
            check['non_optimized_parameters_line'] = index
    converged = None
    if check is not None:
        criteria = check['criteria']
        if check['non_optimized_parameters_line'] is not None or any(
                not row['converged'] for row in criteria.values()):
            converged = False
        elif len(criteria) == 4:
            converged = True
    return {'freq_step_converged': converged, 'freq_step_convergence': check}


def wavefunction_stability(text):
    """Last printed diagnostic in the current job, not acceptance of a new state.

    Stable=Opt may print several results. Do not infer stability from termination,
    or reuse a prior job's result after a new route/Link1 starts.
    """
    result, evidence = 'unknown', None
    patterns = (
        ('stable', r'The wavefunction is stable under the perturbations considered\.'),
        ('internal_instability', r'The wavefunction has an internal instability\.'),
        ('rhf_to_uhf', r'The wavefunction has an RHF\s*->\s*UHF instability\.'),
    )
    for line in text.splitlines():
        if re.match(r'\s*(?:#|--Link1--|Link1:.*Proceeding|Entering Gaussian System)', line, re.I):
            result, evidence = 'unknown', None
        if re.match(r'\s*The wavefunction\b', line, re.I):
            # An unsupported or truncated diagnostic must not retain an older
            # positive result. Preserve its exact line so it can be reviewed.
            evidence = line
            result = next((value for value, pattern in patterns
                           if re.fullmatch(r'\s*' + pattern + r'\s*', line, re.I)), 'unknown')
    return {'wavefunction_stability': result, 'wavefunction_stability_line': evidence}


def expected_vibrational_modes(n_atoms, coordinates):
    """Classify geometry; missing/degenerate coordinates do not imply nonlinear.

    A 1e-5 angstrom perpendicular tolerance allows Gaussian's printed-coordinate
    rounding without treating a visibly bent molecule as linear.
    """
    if n_atoms == 1:
        return 0
    if n_atoms is None or n_atoms < 2 or coordinates is None or len(coordinates) != n_atoms:
        return None
    import numpy as np

    centered = np.asarray(coordinates, dtype=float) - np.mean(coordinates, axis=0)
    if centered.shape != (n_atoms, 3) or not np.isfinite(centered).all():
        return None
    _, singular, axes = np.linalg.svd(centered, full_matrices=False)
    if singular[0] <= 1e-5:
        return None
    perpendicular = centered - np.outer(centered @ axes[0], axes[0])
    linear = np.max(np.linalg.norm(perpendicular, axis=1)) <= 1e-5
    return 3 * n_atoms - (5 if linear else 6)


def gaussian_job_sections(text):
    """Return inclusive, 1-based source spans; blanks after a terminal are not evidence.

    Entering/Initial command are one launch header. Opt Freq's second step
    instead has an optional l1 entry followed by Proceeding to internal job
    step. A bare l1 entry is not itself proof of a valid continuation.
    """
    lines = text.splitlines(keepends=True)
    routes = _gaussian_routes(text)
    sections, warnings = [], []
    start = None
    kind, step = None, None
    seen_route = seen_initial = seen_launch = False

    def finish(end):
        nonlocal start
        while end > start and not lines[end - 1].strip():
            end -= 1
        block = ''.join(lines[start:end])
        section_routes = [route for line, route in routes.items() if start <= line < end]
        state = termination(block, 'Normal termination of Gaussian')['termination']
        if state == 'normal' and not re.match(
                r'\s*Normal termination of Gaussian\b', lines[end - 1], re.I):
            state = 'incomplete'
        sections.append(dict(index=len(sections) + 1, start_line=start + 1, end_line=end,
                             route=section_routes[0] if section_routes else None,
                             termination=state,
                             start_kind=kind, internal_step=step))
        start = None

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        launch = bool(re.match(r'\s*Entering Gaussian System\b', line, re.I))
        initial = bool(re.match(r'\s*Initial command:', line, re.I))
        internal = re.match(r'\s*(?:Link1:\s*)?Proceeding to internal job step number\s+(\d+)\.',
                            line, re.I)
        explicit = bool(re.match(r'\s*--Link1--\s*$', line, re.I))
        route = i in routes
        if start is not None:
            # The initial header has both launch markers; neither is an
            # additional job. The optional l1 line belongs to its next step.
            prelude = bool(internal or explicit) and all(
                not row.strip() or re.fullmatch(r'\s*\(Enter .*[/\\]l1\.exe\)\s*', row)
                for row in lines[start:i])
            boundary = ((launch and (seen_launch or seen_initial or seen_route))
                        or (initial and (seen_initial or seen_route))
                        or ((internal or explicit) and not prelude)
                        or (route and seen_route))
            if boundary:
                finish(i)
        if start is None:
            start, kind, step = i, 'unmarked', None
            seen_route = seen_initial = seen_launch = False
        if launch or initial:
            kind = 'launch'
        elif internal:
            kind, step = 'internal', int(internal[1])
        elif explicit:
            kind = 'link1'
        seen_launch |= launch
        seen_initial |= initial
        seen_route |= route
        if re.match(r'\s*Normal termination of Gaussian\b', line, re.I):
            finish(i + 1)
    if start is not None:
        finish(len(lines))
    if not sections:
        sections = [dict(index=1, start_line=1, end_line=len(lines), route=None,
                         termination='incomplete', start_kind='unmarked', internal_step=None)]
    first_route = sections[0]['route'] or ''
    opt_freq = _route_has(first_route, 'opt') and _route_has(first_route, 'freq')
    expected = 2 if opt_freq else 1
    if len(sections) > expected:
        warnings.append(f'Unexpected job section count: {len(sections)} (route allows at most {expected})')
    for section in sections[1:]:
        if not (opt_freq and section['index'] == 2 and section['start_kind'] == 'internal'
                and section['internal_step'] == 2 and _route_has(section['route'], 'freq')
                and not _route_has(section['route'], 'opt')):
            warnings.append(f"Unexpected or unrecognized job section {section['index']} "
                            f"at line {section['start_line']}")
    return sections, warnings


def _route_has(route, keyword):
    # Stable=Opt is not a geometry optimization job.
    return bool(re.search(r'(?:^|[\s#])' + keyword + r'\b', route or '', re.I))


def gaussian_section_text(text, section):
    return ''.join(text.splitlines(keepends=True)[section['start_line'] - 1:section['end_line']])


_FREQUENCY_FACTS = ('freq_step_converged', 'freq_step_convergence', 'n_imag',
                    'frequencies_low', 'imag_modes', 'n_vibrational_modes',
                    'expected_vibrational_modes', 'vibrational_modes_complete', 'frequency_note')
_THERMAL_FACTS = ('zpe', 'e_thermal', 'h', 'g')


def parse_gaussian(path, pbs_path=None):
    text = path.read_text(errors='replace')
    pbs = pbs_path.read_text(errors='replace') if pbs_path and pbs_path.exists() else ''
    sections, warnings = gaussian_job_sections(text)
    boundary_warning = bool(warnings)
    blocks = [gaussian_section_text(text, section) for section in sections]
    parsed = [_parse_gaussian_section(block, internal=section['start_kind'] == 'internal')
              for section, block in zip(sections, blocks)]
    for section, (values, _) in zip(sections, parsed):
        check = values['freq_step_convergence']
        if check:
            offset = section['start_line'] - 1
            for key in ('frequency_line', 'table_line', 'non_optimized_parameters_line'):
                if check[key] is not None:
                    check[key] += offset
            for row in check['criteria'].values():
                row['line'] += offset
        if values['parser_warning']:
            warnings.append(values['parser_warning'] if len(sections) == 1 else
                            f"Section {section['index']}: {values['parser_warning']}")

    # Identity and spin belong to the last section, even if it is incomplete.
    facts = dict(parsed[-1][0])
    sources = {key: sections[-1]['index'] for key in
               ('n_atoms', 'charge', 'multiplicity', 'monatomic', 's2')}
    facts.update(gaussian_version(text))
    facts['route'] = sections[0]['route']
    sources['route'] = 1
    errors = [i for i, section in enumerate(sections) if section['termination'] == 'error']
    facts['termination'] = ('error' if errors else 'normal' if not boundary_warning and all(
        section['termination'] == 'normal' for section in sections) else 'incomplete')
    if errors:
        facts['error_hint'] = termination(
            blocks[errors[-1]], 'Normal termination of Gaussian',
            line_offset=sections[errors[-1]]['start_line'] - 1)['error_hint']
        sources['error_hint'] = errors[-1] + 1
    else:
        facts['error_hint'] = termination(
            blocks[-1], 'Normal termination of Gaussian', pbs,
            line_offset=sections[-1]['start_line'] - 1)['error_hint']
        sources['error_hint'] = None if facts['error_hint'] == 'walltime' else len(sections)

    opts = [i for i, section in enumerate(sections) if _route_has(section['route'], 'opt')]
    if not opts:
        opts = [i for i, (values, _) in enumerate(parsed) if values['opt_converged'] is not None]
    opt = opts[-1] if opts else len(sections) - 1
    facts['opt_converged'] = parsed[opt][0]['opt_converged']
    sources['opt_converged'] = opt + 1
    geometry = parsed[opt][1]
    facts['final_geometry_orientation'] = parsed[opt][0]['final_geometry_orientation']
    sources['final_geometry'] = sources['final_geometry_orientation'] = opt + 1

    normal = [i for i, section in enumerate(sections) if section['termination'] == 'normal']
    # A single failed/truncated job still owns its reported SCF energy.
    # Multiple jobs may only borrow from the last normally terminated section.
    scf = 0 if len(sections) == 1 else normal[-1] if normal else None
    facts['energies'] = dict(facts['energies'])
    facts['energies']['scf'] = parsed[scf][0]['energies']['scf'] if scf is not None else None
    sources['energies.scf'] = scf + 1 if scf is not None else None
    freqs = [i for i, section in enumerate(sections) if _route_has(section['route'], 'freq')
             or re.search(r'Harmonic frequencies|Frequencies\s+--|Zero-point correction=', blocks[i])]
    freq = freqs[-1] if freqs else None
    # Unknown trailing output may be a new, truncated Freq. Do not lend it the
    # prior frequency result. An explicitly identified SP keeps its own source.
    unknown_tail = len(sections) > 1 and sections[-1]['route'] is None
    invalid_freq = (freq is not None and sections[freq]['termination'] != 'normal') or unknown_tail
    frequency_source = None if unknown_tail else freq + 1 if freq is not None else len(sections)
    pending_internal_freq = (len(sections) == 2 and _route_has(sections[0]['route'], 'opt')
                             and _route_has(sections[0]['route'], 'freq')
                             and sections[-1]['start_kind'] == 'internal'
                             and sections[-1]['internal_step'] == 2)
    if unknown_tail and not pending_internal_freq:
        geometry = None
        facts['final_geometry_orientation'] = None
        sources['final_geometry'] = sources['final_geometry_orientation'] = None
    facts['frequency_unavailable_reason'] = (
        'Unrecognized trailing job section; frequency source is uncertain' if unknown_tail else
        f"Frequency section {freq + 1} ended {sections[freq]['termination']}" if invalid_freq else None)
    for key in _FREQUENCY_FACTS:
        facts[key] = None if invalid_freq else parsed[freq][0][key] if freq is not None else facts[key]
        sources[key] = frequency_source
    for key in _THERMAL_FACTS:
        facts['energies'][key] = (None if invalid_freq else parsed[freq][0]['energies'][key]
                                 if freq is not None else facts['energies'][key])
        sources['energies.' + key] = frequency_source
    if any('wavefunction_stability' in values for values, _ in parsed):
        facts.update(wavefunction_stability(blocks[-1]))
        sources['wavefunction_stability'] = sources['wavefunction_stability_line'] = len(sections)
    ircs = [i for i, (values, _) in enumerate(parsed) if 'irc' in values]
    if ircs:
        facts['irc'] = parsed[ircs[-1]][0]['irc']
        sources['irc'] = ircs[-1] + 1
    facts.update(job_sections=sections, fact_sources=sources,
                 parser_warning='; '.join(warnings) or None)
    return facts, geometry


def _parse_gaussian_section(text, *, internal=False):
    from cclib.io import ccread
    from cclib.parser.utils import PeriodicTable, convertor

    facts = termination(text, 'Normal termination of Gaussian')
    facts.update(gaussian_version(text))
    # Truncated/error logs can make cclib raise. Keep termination evidence,
    # but never turn a failed parse into invented numerical facts.
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            # Internal steps omit the banner used by cclib's format detector.
            # This detector hint contains no facts from another section.
            data = ccread(io.StringIO(('Gaussian, Inc.\n' if internal else '') + text),
                          loglevel=50)
    except (ValueError, IndexError, AssertionError, AttributeError, StopIteration):
        data = None
    facts['parser_warning'] = None if data is not None else 'cclib could not parse this output'
    routes = list(_gaussian_routes(text).values())
    facts['route'] = routes[0] if routes else None
    facts['n_atoms'] = int(data.natom) if data is not None and hasattr(data, 'natom') else None
    facts['charge'] = int(data.charge) if data is not None and hasattr(data, 'charge') else None
    facts['multiplicity'] = int(data.mult) if data is not None and hasattr(data, 'mult') else None
    facts.update(frequency_convergence(text))
    # Ordinary jobs must keep their facts keys (and signed evidence) unchanged.
    if (any(re.search(r'\bstable\b', route, re.I) for route in routes)
            or re.search(r'(?m)^[ \t]*The wavefunction\b', text, re.I)):
        facts.update(wavefunction_stability(text))
    # Gaussian prints one leading space; deeper indentation/quoted prose is
    # not a status line. Match variants such as '... negligible forces.'.
    facts['opt_converged'] = (True if re.search(r'(?m)^ ?Optimization completed\b', text) else
                              False if re.search(r'(?m)^ ?Optimization stopped\b', text) else None)
    scf = float(convertor(data.scfenergies[-1], 'eV', 'hartree')) if data is not None and hasattr(data, 'scfenergies') else None
    facts['energies'] = {
        'scf': scf,
        'zpe': last_number(r'Zero-point correction=', text),
        'e_thermal': last_number(r'Sum of electronic and thermal Energies=', text),
        'h': last_number(r'Sum of electronic and thermal Enthalpies=', text),
        'g': last_number(r'Sum of electronic and thermal Free Energies=', text),
    }
    facts['s2'] = last_number(r'<S\*\*2>\s*=|S\*\*2 before annihilation', text)
    frequencies = list(getattr(data, 'vibfreqs', []))
    facts['n_imag'] = sum(f < 0 for f in frequencies) if frequencies else None
    if facts['n_imag'] is not None:
        facts['n_imag'] = int(facts['n_imag'])
    facts['frequencies_low'] = sorted(float(f) for f in frequencies)[:10]
    facts['imag_modes'] = []
    geometry = None
    coords = None
    facts['final_geometry_orientation'] = None
    if data is not None and hasattr(data, 'atomcoords') and hasattr(data, 'atomnos'):
        coords = data.atomcoords[-1]
        elements = [PeriodicTable().element[int(n)] for n in data.atomnos]
        geometry = xyz_text(elements, coords)
        # cclib prefers Standard; without it, it uses Input/Z-Matrix coordinates.
        # Label only a frame whose printed coordinates actually match the export.
        for orientation in ('Standard', 'Input', 'Z-Matrix'):
            if gaussian_orientation(text, orientation) == geometry:
                facts['final_geometry_orientation'] = orientation.lower()
                break
        if hasattr(data, 'vibdisps'):
            facts['imag_modes'] = imaginary_modes(frequencies, data.vibdisps, coords, elements)
    facts['monatomic'] = facts['n_atoms'] == 1
    expected_modes = expected_vibrational_modes(facts['n_atoms'], coords)
    frequency_job = bool(re.search(r'\bfreq\b', facts['route'] or '', re.I))
    # L3: a completed atomic Freq has thermochemistry but no Frequencies lines.
    # Do not extend this inference to SP, failed jobs, or missing polyatomic data.
    atomic_frequency = (facts['monatomic'] and frequency_job
                        and facts['termination'] == 'normal'
                        and all(facts['energies'][key] is not None
                                for key in ('zpe', 'e_thermal', 'h', 'g'))
                        and not frequencies)
    if atomic_frequency:
        facts['n_imag'] = 0
    facts['n_vibrational_modes'] = len(frequencies) if frequencies or atomic_frequency else None
    facts['expected_vibrational_modes'] = expected_modes
    facts['vibrational_modes_complete'] = (
        facts['n_vibrational_modes'] == expected_modes
        if expected_modes is not None and (frequency_job or frequencies) else None)
    facts['frequency_note'] = '单原子无振动模式' if atomic_frequency else None
    from ag._irc import parse_irc
    irc, endpoint = parse_irc(text)
    if irc is not None:
        facts['irc'] = irc
        if endpoint and facts['n_atoms'] is None:
            facts['n_atoms'] = int(endpoint.splitlines()[0])
        state = re.findall(r'Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)', text)
        if state and facts['charge'] is None:
            facts['charge'], facts['multiplicity'] = map(int, state[-1])
    return facts, geometry


def read_xyz_frames(path):
    lines = path.read_text().splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        n = int(lines[i])
        if n <= 0 or i + n + 2 > len(lines):
            raise ValueError(f'{path.name}: incomplete XYZ frame')
        comment = lines[i+1]
        atoms = [line.split() for line in lines[i+2:i+n+2]]
        if any(len(row) < 4 for row in atoms):
            raise ValueError(f'{path.name}: invalid XYZ coordinates')
        elements = [row[0] for row in atoms]
        coordinates = [[number(x) for x in row[1:4]] for row in atoms]
        frames.append((comment, elements, coordinates))
        i += n + 2
    return frames


def parse_xtb(outputs, scheduler_output='job.pbs.out'):
    text = (outputs / 'xtb.out').read_text(errors='replace')
    scheduler_path = outputs / scheduler_output
    available = scheduler_path.is_file()
    scheduler_text = scheduler_path.read_text(errors='replace') if available else ''
    marker = 'normal termination of xtb'
    facts = termination(text + '\n' + scheduler_text, marker, scheduler_text)
    # stderr contains xTB's normal marker, but a scheduler kill overrides it.
    killed = re.search(r'\b(?:kill(?:ed|ing)?|sigkill|sigterm|oom(?:_kill)?|out of memory)\b'
                       r'|time\s*limit|walltime.*(?:exceed|limit)', scheduler_text, re.I)
    if killed or facts['error_hint'] == 'walltime':
        facts['termination'] = 'error'
        facts['error_hint'] = facts['error_hint'] or 'scheduler termination error'
    facts.update(termination_marker_sources=[name for name, content in
                 [('xtb.out', text), (scheduler_output, scheduler_text)] if marker in content.lower()],
                 scheduler_output={'file': scheduler_output, 'available': available},
                 termination_warning=None if available else
                 f'{scheduler_output} 未取回；无法核对调度器输出，不据退出回执推断正常结束')
    facts.update(total_energy=last_number(r'TOTAL ENERGY\s*', text),
                 converged='GEOMETRY OPTIMIZATION CONVERGED' in text)
    geometry = None
    if (outputs / 'xtbopt.xyz').exists():
        _, elements, coords = read_xyz_frames(outputs / 'xtbopt.xyz')[-1]
        facts['n_atoms'] = len(elements)
        geometry = xyz_text(elements, coords)
    return facts, geometry


def parse_crest(outputs):
    text = (outputs / 'crest.out').read_text(errors='replace')
    pbs = outputs / 'job.pbs.out'
    facts = termination(text, 'CREST terminated normally.', pbs.read_text() if pbs.exists() else '')
    facts.update(n_conformers=None, relative_energies_kcal=[], best_energy=None)
    if not (outputs / 'crest_conformers.xyz').exists():
        return facts, None
    frames = read_xyz_frames(outputs / 'crest_conformers.xyz')
    if not frames:
        return facts, None
    energies = []
    for line in (outputs / 'crest.energies').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            columns = line.split()
            energies.append(number(columns[1]))
    if len(energies) != len(frames):
        raise ValueError('CREST energy/geometry counts differ')
    # CREST 3.0.2 cregen_econf_list writes relative kcal/mol, not Hartree.
    best = min(range(len(energies)), key=energies.__getitem__)
    comment, elements, coords = frames[best]
    match = re.match(r'\s*(' + NUMBER + r')(?:\s|$)', comment)
    facts.update(n_atoms=len(elements), n_conformers=len(frames),
                 best_energy=number(match[1]) if match else None,
                 relative_energies_kcal=energies)
    return facts, xyz_text(elements, coords)


def gaussian_version(text):
    """Extract only product/revision tokens; never retain identifying headers."""
    versions = set(re.findall(r'Gaussian\s+(\d{2}),\s+Revision\s+([A-Z]\.\d{2})\b', text, re.I))
    versions.update(re.findall(r'Gaussian\s+(\d{2}):[^\n]*?G\d{2}Rev([A-Z]\.\d{2})\b', text, re.I))
    normalized = sorted({f'Gaussian {major} Rev {revision.upper()}' for major, revision in versions})
    return dict(program_version=normalized[0] if len(normalized) == 1 else None,
                program_versions=normalized,
                program_version_warning=('Conflicting Gaussian versions in log' if len(normalized) > 1 else
                                         'Gaussian version not found in log' if not normalized else None))


def parse_crest_mdopt(outputs, expected_frames=None):
    """CREST 3.0.2 optimization.f90 writes ordered Hartree XYZ, not crest.energies."""
    from ag import geometry as geo
    frames = geo.read_xyz(outputs / 'crest_ensemble.xyz')
    if expected_frames is not None and len(frames) != expected_frames:
        raise ValueError('CREST mdopt input/output frame counts differ')
    failed = [index for index, frame in enumerate(frames, 1) if '!failed' in frame.comment.lower()]
    if failed:
        indices = ', '.join(map(str, failed))
        raise ValueError(f'CREST mdopt contains failed optimizations in frames (1-based): {indices}; review before dedup')
    for frame in frames:
        if frame.symbols != frames[0].symbols:
            raise ValueError('CREST mdopt atom counts or element sequences differ')
        if frame.energy is None or frame.energy_unit != 'hartree':
            raise ValueError('CREST mdopt requires a finite Hartree energy in every XYZ comment')
    text = (outputs / 'crest.out').read_text(errors='replace')
    facts = termination(text, 'CREST terminated normally.')
    best = min(frames, key=lambda frame: frame.energy)
    facts.update(mode='mdopt', n_atoms=len(best.symbols), n_conformers=len(frames),
                 conformer_energies_hartree=[frame.energy for frame in frames],
                 relative_energies_kcal=geo.relative_energies(frames, best.energy),
                 best_energy=best.energy)
    return facts, geo.xyz_text([best]), geo.xyz_text(frames)
