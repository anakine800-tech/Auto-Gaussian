"""Validate Cartesian Gaussian inputs before any remote side effect.

QST block parsing adapts pure logic from
archive/skills/auto-g16-ts-irc/scripts/ts_irc.py:parse_raw_qst_input and
_qst_syntax_error. No legacy imports, audit hashes or receipts are copied.
"""
import math
import re


def _qst_mode(route):
    modes = set(re.findall(r'\bqst[23]\b', route.lower()))
    if not modes:
        return None
    if len(modes) != 1:
        raise ValueError('QST2 and QST3 cannot be combined')
    options = []
    for match in re.finditer(r'\bopt\b\s*(?:=\s*)?(\([^()]*\)|[A-Za-z0-9]+)', route, re.I):
        options.extend(re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', match[1].lower()))
    mode = next(iter(modes))
    if 'ts' in options:
        raise ValueError('Opt=TS cannot be combined with QST2 or QST3')
    if options.count(mode) != 1 or len(re.findall(r'\bqst[23]\b', route, re.I)) != 1:
        raise ValueError('QST requires exactly one QST2 or QST3 option in Opt')
    return mode.upper()


def _qst_structures(sections, mode):
    count = int(mode[-1])
    if len(sections) != 1 + 2 * count:
        raise ValueError(f'{mode} requires exactly {count} title + charge/multiplicity + coordinate groups')
    # Canonical element identities also allow Gaussian atomic-number rows.
    elements = ('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
                'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce '
                'Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn '
                'Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split()
    structures = []
    number = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    for i in range(count):
        title, block = sections[1 + 2 * i:3 + 2 * i]
        rows = block.splitlines()
        match = re.fullmatch(r'\s*([+-]?\d+)\s+(\d+)\s*', rows[0])
        prefix = f'{mode} group {i + 1}: '
        if not title.strip() or not match or int(match[2]) < 1 or len(rows) < 2:
            raise ValueError(prefix + 'expected title, charge/multiplicity and coordinates')
        symbols = []
        for row in rows[1:]:
            if not re.fullmatch(rf'\s*(?:[A-Z][a-z]?|\d+)\s+{number}\s+{number}\s+{number}\s*', row):
                raise ValueError(prefix + 'expected finite Cartesian coordinates')
            atom, *xyz = row.split()
            if atom.isdigit() and 1 <= int(atom) <= len(elements):
                atom = elements[int(atom) - 1]
            if atom not in elements:
                raise ValueError(prefix + 'expected a real element or atomic number')
            if not all(math.isfinite(float(value)) for value in xyz):
                raise ValueError(prefix + 'expected finite Cartesian coordinates')
            symbols.append(atom)
        structure = dict(title=title.strip(), charge=int(match[1]), multiplicity=int(match[2]),
                         geometry='\n'.join(rows[1:]), n_atoms=len(symbols), elements=symbols)
        if structures:
            for key in ('n_atoms', 'elements', 'charge', 'multiplicity'):
                if structure[key] != structures[0][key]:
                    raise ValueError(prefix + f'{key} differs from reactant')
        structures.append(structure)
    return structures


def _qst_displacements(structures):
    """Proper Kabsch rotation, all atoms equally weighted, fixed input row mapping."""
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError('QST alignment requires NumPy; install ag[chem]') from exc
    arrays = [np.array([row.split()[1:] for row in s['geometry'].splitlines()], dtype=float)
              for s in structures[:2]]
    # Fail clearly if finite but extreme coordinates overflow the alignment.
    try:
        with np.errstate(over='raise', invalid='raise'):
            reference, moving = [a - a.mean(axis=0) for a in arrays]
            u, _, vt = np.linalg.svd(moving.T @ reference)
            correction = np.eye(3)
            correction[-1, -1] = 1 if np.linalg.det(u @ vt) >= 0 else -1
            displacement = np.linalg.norm(moving @ (u @ correction @ vt) - reference, axis=1)
    except (FloatingPointError, np.linalg.LinAlgError) as exc:
        raise ValueError('QST coordinates cannot be aligned numerically') from exc
    # Rounded values make confirmation revalidation independent of insignificant SVD noise.
    values = [round(float(value), 8) for value in displacement]
    indices = sorted(range(len(values)), key=lambda i: (-values[i], i))[:5]
    return [dict(atom_index=i + 1, element=structures[0]['elements'][i], displacement=values[i])
            for i in indices]


def validate(text, cores, mem_gb, *, parent_chk=False):
    lines = text.splitlines()
    link = {}
    index = 0
    while index < len(lines) and lines[index].startswith('%'):
        match = re.fullmatch(r'%([A-Za-z]+)\s*=\s*(.+)', lines[index])
        if not match:
            raise ValueError('Invalid Link0 directive')
        key, value = match.group(1).lower(), match.group(2).strip()
        # Other Link0 file directives can escape the fresh Attempt directory.
        if key not in {'nprocshared', 'mem', 'chk', 'oldchk'} or key in link:
            raise ValueError('Unsupported or duplicate Link0 directive')
        link[key] = value
        index += 1
    if link.get('nprocshared') != str(cores):
        raise ValueError('%nprocshared must match resource tier')
    memory = re.fullmatch(r'(\d+)(GB|MB|MW|GW)', link.get('mem', ''), re.I)
    if not memory:
        raise ValueError('%mem must use integer GB, MB, GW or MW')
    factor = {'GB': 1, 'MB': 0.001, 'GW': 8, 'MW': 0.008}[memory[2].upper()]
    if not 0 < int(memory[1]) * factor <= mem_gb * 0.85:
        raise ValueError('%mem exceeds 85% of the resource tier')
    if 'chk' in link and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.chk', link['chk']):
        raise ValueError('%chk must be a plain filename')
    if 'oldchk' in link:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.chk', link['oldchk']):
            raise ValueError('%oldchk must be a plain filename')
        if link.get('chk') == link['oldchk']:
            raise ValueError('%chk and %oldchk must use different filenames')
        if not parent_chk or link['oldchk'] != 'parent.chk':
            raise ValueError('%oldchk requires a declared parent chk attachment named parent.chk')
        if 'chk' not in link:
            raise ValueError('%oldchk requires a distinct explicit %chk')
    if parent_chk and link.get('oldchk') != 'parent.chk':
        raise ValueError('Parent chk attachment requires %oldchk=parent.chk')
    rest = '\n'.join(lines[index:]).strip()
    sections = re.split(r'\n\s*\n', rest)
    if len(sections) < 3 or not sections[0].lstrip().startswith('#') or not sections[1].strip():
        raise ValueError('Expected route, title, charge/multiplicity and Cartesian coordinates')
    route = ' '.join(sections[0].split())
    # External launches and file inclusion can bypass reviewed program templates.
    if re.search(r'\bexternal\b|\binclude\b|@', text, re.I) or '--link1--' in text.lower():
        raise ValueError('External programs, includes and Link1 are unsupported')
    for option in re.finditer(r'\bgeom(?:etry)?\s*(?:=\s*)?(\([^()]*\)|[A-Za-z]+)', route, re.I):
        if re.search(r'\b(?:check|checkpoint|allcheck)\b', option[1], re.I):
            raise ValueError('Geom=Check/AllCheck is unsupported; provide explicit coordinates')
    mode = _qst_mode(route)
    if mode:
        structures = _qst_structures(sections, mode)
        first = structures[0]
        return dict(charge=first['charge'], multiplicity=first['multiplicity'], route=route,
                    geometry=first['geometry'], n_atoms=first['n_atoms'], qst_mode=mode,
                    structures=structures, largest_displacements=_qst_displacements(structures),
                    displacement_unit='input coordinate units',
                    stereochemistry_warning='Review stereochemistry and atom row mapping against the source structures. '
                    'Matching element order and aligned displacements do not verify same-element atom identities.')
    geom = sections[2].splitlines()
    match = re.fullmatch(r'\s*(-?\d+)\s+(\d+)\s*', geom[0])
    if not match or int(match[2]) < 1 or len(geom) < 2:
        raise ValueError('Invalid charge/multiplicity or missing coordinates')
    number = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    for row in geom[1:]:
        if not re.fullmatch(rf'\s*(?:[A-Z][a-z]?|\d+)\s+{number}\s+{number}\s+{number}\s*', row):
            raise ValueError('Expected finite Cartesian coordinates')
    if len(sections) > 3:
        raise ValueError('Additional Gaussian input sections are not supported in this release')
    return dict(charge=int(match[1]), multiplicity=int(match[2]), route=route,
                geometry='\n'.join(geom[1:]), n_atoms=len(geom) - 1,
                stereochemistry_warning='Review stereochemistry against the source structure.')
