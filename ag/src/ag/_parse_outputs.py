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


def termination(text, marker, pbs_text=''):
    error = re.search(r'Error termination|abnormal termination|fatal error|\[ERROR\]', text, re.I)
    link = re.findall(r'Error termination via Lnk1e in .*?[/\\]l(\d+)\.exe', text, re.I)
    hint = None
    if link:
        hint = {'9999': 'L9999: 优化步数用完', '502': 'L502: SCF 不收敛'}.get(link[-1], 'L' + link[-1])
    elif re.search(r'convergence failure|SCF.*not converg', text, re.I):
        hint = 'SCF 不收敛'
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


def parse_gaussian(path, pbs_path=None):
    from cclib.io import ccread
    from cclib.parser.utils import PeriodicTable, convertor

    text = path.read_text(errors='replace')
    pbs = pbs_path.read_text(errors='replace') if pbs_path and pbs_path.exists() else ''
    facts = termination(text, 'Normal termination of Gaussian', pbs)
    # Truncated/error logs can make cclib raise. Keep termination evidence,
    # but never turn a failed parse into invented numerical facts.
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            data = ccread(str(path), loglevel=50)
    except (ValueError, IndexError, AssertionError, AttributeError, StopIteration):
        data = None
    facts['parser_warning'] = None if data is not None else 'cclib could not parse this output'
    routes = re.findall(r'(?m)^\s*(#[^\n]*(?:\n(?!\s*-{5,})[^\n]+)*)\n\s*-{5,}', text)
    facts['route'] = ' '.join(routes[0].split()) if routes else None
    facts['n_atoms'] = int(data.natom) if data is not None and hasattr(data, 'natom') else None
    facts['charge'] = int(data.charge) if data is not None and hasattr(data, 'charge') else None
    facts['multiplicity'] = int(data.mult) if data is not None and hasattr(data, 'mult') else None
    facts['opt_converged'] = (True if 'Optimization completed.' in text else
                              False if 'Optimization stopped.' in text else None)
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
    if data is not None and hasattr(data, 'atomcoords') and hasattr(data, 'atomnos'):
        coords = data.atomcoords[-1]
        elements = [PeriodicTable().element[int(n)] for n in data.atomnos]
        geometry = xyz_text(elements, coords)
        if hasattr(data, 'vibdisps'):
            facts['imag_modes'] = imaginary_modes(frequencies, data.vibdisps, coords, elements)
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


def parse_xtb(outputs):
    text = (outputs / 'xtb.out').read_text(errors='replace')
    pbs = outputs / 'job.pbs.out'
    facts = termination(text, 'normal termination of xtb', pbs.read_text() if pbs.exists() else '')
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
