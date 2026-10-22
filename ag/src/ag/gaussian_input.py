"""Validate Cartesian Gaussian inputs before any remote side effect.

QST block parsing adapts pure logic from
archive/skills/auto-g16-ts-irc/scripts/ts_irc.py:parse_raw_qst_input and
_qst_syntax_error. No legacy imports, audit hashes or receipts are copied.
"""
import math
import re


ELEMENTS = ('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
            'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce '
            'Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn '
            'Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split()
ATOMIC_NUMBERS = {symbol: number for number, symbol in enumerate(ELEMENTS, 1)}
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'


def cartesian(rows, *, first_line, prefix=''):
    """Reject invalid atoms/coordinates before they waste a queued calculation.

    Return canonical identities for comparison/counting, preserving input bytes.
    Gaussian and XYZ callers supply the original file's one-based line number.
    """
    symbols = []
    for line, row in enumerate(rows, first_line):
        where = f'{prefix}line {line}: '
        fields = row.split()
        if len(fields) != 4:
            raise ValueError(where + 'Expected finite Cartesian coordinates: element and three numbers')
        atom, *xyz = fields
        symbol = atom.capitalize() if re.fullmatch(r'[A-Za-z]{1,2}', atom) else None
        if re.fullmatch(r'\d+', atom) and 1 <= int(atom) <= len(ELEMENTS):
            symbol = ELEMENTS[int(atom) - 1]
        if symbol not in ATOMIC_NUMBERS:
            raise ValueError(where + f'Expected a real element or atomic number 1–118; got {atom!r}. '
                             'Dummy atoms (Bq/X) and isotope/atom-label syntax are unsupported')
        if not all(re.fullmatch(NUMBER, value) and math.isfinite(float(value)) for value in xyz):
            raise ValueError(where + 'Expected finite Cartesian coordinates')
        symbols.append(symbol)
    return symbols


def check_electrons(symbols, charge, multiplicity, *, location):
    electrons = sum(ATOMIC_NUMBERS[symbol] for symbol in symbols) - charge
    if electrons < 0:
        raise ValueError(f'{location}: electron count {electrons} is negative (multiplicity {multiplicity})')
    if electrons % 2 == multiplicity % 2:
        raise ValueError(f'{location}: electron count {electrons} and multiplicity {multiplicity} '
                         'have incompatible parity')


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


def _qst_structures(sections, mode, section_lines):
    count = int(mode[-1])
    if len(sections) != 1 + 2 * count:
        raise ValueError(f'{mode} requires exactly {count} title + charge/multiplicity + coordinate groups')
    structures = []
    for i in range(count):
        title, block = sections[1 + 2 * i:3 + 2 * i]
        rows = block.splitlines()
        match = re.fullmatch(r'\s*([+-]?\d+)\s+(\d+)\s*', rows[0])
        prefix = f'{mode} group {i + 1}: '
        line = section_lines[2 + 2 * i]
        if not title.strip() or not match or int(match[2]) < 1 or len(rows) < 2:
            raise ValueError(prefix + f'line {line}: expected title, charge/multiplicity and coordinates')
        symbols = cartesian(rows[1:], first_line=line + 1, prefix=prefix)
        check_electrons(symbols, int(match[1]), int(match[2]), location=prefix + f'line {line}')
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
    untrimmed = '\n'.join(lines[index:])
    rest = untrimmed.strip()
    first_line = index + 1 + untrimmed[:len(untrimmed) - len(untrimmed.lstrip())].count('\n')
    sections = re.split(r'\n\s*\n', rest)
    section_lines = [first_line] + [first_line + rest[:match.end()].count('\n')
                                    for match in re.finditer(r'\n\s*\n', rest)]
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
    opt_options = [word.lower() for option in re.finditer(
        r'\bopt\b\s*(?:=\s*)?(\([^()]*\)|[A-Za-z0-9]+)', route, re.I)
        for word in re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', option[1])]
    modredundant = 'modredundant' in opt_options
    if mode:
        structures = _qst_structures(sections, mode, section_lines)
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
        raise ValueError(f'line {section_lines[2]}: Invalid charge/multiplicity or missing coordinates')
    symbols = cartesian(geom[1:], first_line=section_lines[2] + 1)
    check_electrons(symbols, int(match[1]), int(match[2]), location=f'line {section_lines[2]}')
    scan_data = {}
    if len(sections) > 3:
        if not modredundant or 'ts' in opt_options or len(sections) != 4:
            raise ValueError('Additional section requires non-TS Opt=ModRedundant and exactly one block')
        # Avoid displaying an angstrom scan range for non-angstrom input.
        if re.search(r'\bunits?\b', route, re.I):
            raise ValueError('ModRedundant summaries require default angstrom units; omit Units')
        from ag._scan import modredundant as parse_modredundant
        scan_data = parse_modredundant(sections[3], '\n'.join(geom[1:]))
    return dict(charge=int(match[1]), multiplicity=int(match[2]), route=route,
                geometry='\n'.join(geom[1:]), n_atoms=len(geom) - 1, **scan_data,
                stereochemistry_warning='Review stereochemistry against the source structure.')


def counterpoise_fragments(raw, *, geometry, charge, multiplicity):
    """Validate the two explicit fragments before a CP single point is queued.

    Missing/overlapping atoms or a bond across the split would silently change
    the interaction being measured. Reuse topology's uncertain band as well.
    """
    from collections import Counter
    import csv
    from hashlib import sha256
    from io import StringIO
    from ag.topology import _frame, _pairs
    from rdkit import Chem

    symbols = cartesian(geometry.splitlines(), first_line=1)
    if not symbols:
        raise ValueError('Counterpoise requires a nonempty geometry')
    if type(charge) is not int or type(multiplicity) is not int or multiplicity != 1:
        raise ValueError('Counterpoise overall charge must be an integer and multiplicity must be 1')
    try:
        reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')), strict=True)
        columns = ['fragment', 'atoms', 'charge', 'multiplicity']
        if reader.fieldnames != columns:
            raise ValueError('Counterpoise CSV requires exactly fragment,atoms,charge,multiplicity columns')
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('Invalid counterpoise fragments CSV') from exc
    if len(rows) != 2:
        raise ValueError(f'Counterpoise requires exactly 2 fragments; got {len(rows)}')
    fragments, membership, labels = [], {}, set()
    for index, row in enumerate(rows, 1):
        if set(row) != set(columns) or any(value is None for value in row.values()):
            raise ValueError(f'Fragment {index}: invalid CSV row; quote comma-separated atom indices')
        label = row['fragment'].strip()
        if not label or not label.isprintable() or label in labels:
            raise ValueError(f'Fragment {index}: name must be nonempty, printable and unique')
        labels.add(label)
        where = f'Fragment {index} ({label})'
        atoms = []
        for token in row['atoms'].split(','):
            match = re.fullmatch(r'\s*([1-9]\d*)(?:-([1-9]\d*))?\s*', token)
            if not match:
                raise ValueError(f'{where}: invalid atom index/range {token!r}; use 1-3,5 syntax')
            first, last = int(match[1]), int(match[2] or match[1])
            if not 1 <= first <= last <= len(symbols):
                raise ValueError(f'{where}: atom range {first}-{last} outside 1-{len(symbols)} or reversed')
            for atom in range(first, last + 1):
                if atom in membership:
                    raise ValueError(f'{where}: atom {atom} already belongs to fragment {membership[atom]}')
                membership[atom] = index
                atoms.append(atom)
        values = []
        for column in ('charge', 'multiplicity'):
            value = row[column].strip()
            if not re.fullmatch(r'[+-]?\d+', value):
                raise ValueError(f'{where}: {column} must be an integer')
            values.append(int(value))
        fragment_charge, fragment_mult = values
        if fragment_mult != 1:
            raise ValueError(f'{where}: multiplicity must be 1; got {fragment_mult}')
        counts = Counter(symbols[atom - 1] for atom in atoms)
        order = (['C'] + (['H'] if 'H' in counts else []) + sorted(counts.keys() - {'C', 'H'})
                 if 'C' in counts else sorted(counts))
        formula = ''.join(symbol + (str(counts[symbol]) if counts[symbol] > 1 else '') for symbol in order)
        fragments.append(dict(index=index, fragment=label, atoms=sorted(atoms), n_atoms=len(atoms),
                              formula=formula, charge=fragment_charge, multiplicity=fragment_mult))
    missing = sorted(set(range(1, len(symbols) + 1)) - membership.keys())
    if missing:
        raise ValueError('Counterpoise atoms without a fragment: ' + ', '.join(map(str, missing)))
    if sum(fragment['charge'] for fragment in fragments) != charge:
        charges = ', '.join(f"fragment {f['index']} ({f['fragment']}) = {f['charge']}" for f in fragments)
        raise ValueError(f'Counterpoise fragment charges do not sum to overall charge {charge}: {charges}')
    # Whole-system even electron count can hide impossible singlet fragments.
    for fragment in fragments:
        check_electrons([symbols[i - 1] for i in fragment['atoms']], fragment['charge'], 1,
                        location=f"Fragment {fragment['index']} ({fragment['fragment']})")
    for (left, right), evidence in _pairs(_frame(geometry), Chem).items():
        if membership[left] != membership[right] and evidence['state'] in ('bonded', 'uncertain'):
            raise ValueError(f"Counterpoise atoms {left}-{right} cross fragments "
                             f"{membership[left]}-{membership[right]}: {evidence['state']} contact "
                             f"({evidence['distance']:.6f} angstrom); review the fragment definition")
    return dict(sha256=sha256(raw).hexdigest(), fragments=fragments)


CP_SCRF_ERROR = ('G16 A.03 不支持 Counterpoise 与 SCRF 同用（T105 第 0 节实测）；'
                 '请做气相 CP，用 ag cp-report --solvent-sp 叠加溶剂相单点')


def counterpoise_route(route):
    """Reject the observed SCRF failure and unsupported CP tasks before prepare."""
    from ag._profile_sources import protocol
    if re.search(r'scrf', route, re.I):
        raise ValueError(CP_SCRF_ERROR)
    compact = re.sub(r'\s*([=,/])\s*', r'\1', route)
    compact = re.sub(r'\(\s*', '(', compact)
    compact = re.sub(r'\s*\)', ')', compact)
    method = protocol(compact, 1)
    tokens = re.findall(r'(?:[^()\s]+|\([^()]*\))+', re.sub(r'^\s*#[pnt]?\s*', '', compact, flags=re.I))
    # The whitelist prevents a second task (e.g. Force/Polar), geometry changes,
    # checkpoint guesses or hidden route options from becoming a CP SP.
    allowed = {'sp', 'counterpoise=2', 'nosymm', '5d', '6d', '7f', '10f'}
    for token in tokens:
        if '/' in token:
            continue  # protocol() requires exactly one recognized method/basis.
        if token.lower() not in allowed and not re.fullmatch(
                r'(?:scf|int|integral|empiricaldispersion|em)=(?:[a-z0-9+-]+|\([^()]*\))', token, re.I):
            raise ValueError(f'gaussian-cp only supports a gas-phase Counterpoise=2 single point: {token}')
    if sum(token.lower() == 'counterpoise=2' for token in tokens) != 1:
        raise ValueError('gaussian-cp requires exactly one Counterpoise=2')
    return method


def counterpoise_input(text, raw_fragments, cores, mem_gb, *, prepared=False):
    """Generate labels from the CSV, or revalidate exactly the generated bytes.

    Ordinary Gaussian validate remains unchanged. Only this explicit template
    accepts the generated fragment state line and atom labels.
    """
    sections = re.split(r'\n\s*\n', text.strip())
    if len(sections) != 3:
        raise ValueError('gaussian-cp requires one route/title/Cartesian block; no extra sections')
    route = ' '.join(line for line in sections[0].splitlines() if not line.startswith('%'))
    method = counterpoise_route(route)
    if prepared:
        rows = sections[2].splitlines()
        states = rows[0].split()
        if len(states) != 6:
            raise ValueError('Counterpoise requires overall and two fragment charge/multiplicity pairs')
        plain_rows = []
        for index, row in enumerate(rows[1:], 1):
            match = re.fullmatch(r'([A-Za-z]{1,2}|\d+)\(Fragment=([12])\)(\s+.+)', row)
            if not match:
                raise ValueError(f'Counterpoise atom {index}: missing/invalid Fragment label')
            plain_rows.append(match[1] + match[3])
        plain = '\n\n'.join([*sections[:2], ' '.join(states[:2])+'\n'+'\n'.join(plain_rows)])+'\n\n'
        generated, science = counterpoise_input(plain, raw_fragments, cores, mem_gb)
        if generated != text.encode():
            raise ValueError('Prepared Counterpoise labels/states differ from fragments CSV')
        return generated, science
    science = validate(text, cores, mem_gb)
    definition = counterpoise_fragments(raw_fragments, geometry=science['geometry'],
                                      charge=science['charge'], multiplicity=science['multiplicity'])
    states = [science['charge'], science['multiplicity']]
    membership = {}
    for fragment in definition['fragments']:
        states.extend((fragment['charge'], fragment['multiplicity']))
        membership.update({atom: fragment['index'] for atom in fragment['atoms']})
    rows = []
    for index, row in enumerate(science['geometry'].splitlines(), 1):
        atom, coordinates = row.split(maxsplit=1)
        rows.append(f'{atom}(Fragment={membership[index]}) {coordinates}')
    generated = '\n\n'.join([*sections[:2], ' '.join(map(str, states))+'\n'+'\n'.join(rows)])+'\n\n'
    science['counterpoise'] = {**definition, 'file': 'fragments.csv'}
    science['protocol'] = method
    return generated.encode(), science
