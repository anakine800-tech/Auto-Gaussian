"""Validate Cartesian Gaussian inputs before any remote side effect."""
import re


def validate(text, cores, mem_gb):
    lines = text.splitlines()
    link = {}
    index = 0
    while index < len(lines) and lines[index].startswith('%'):
        match = re.fullmatch(r'%([A-Za-z]+)\s*=\s*(.+)', lines[index])
        if not match:
            raise ValueError('Invalid Link0 directive')
        key, value = match.group(1).lower(), match.group(2).strip()
        # Other Link0 file directives can escape the fresh Attempt directory.
        if key not in {'nprocshared', 'mem', 'chk'} or key in link:
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
    rest = '\n'.join(lines[index:]).strip()
    sections = re.split(r'\n\s*\n', rest)
    if len(sections) < 3 or not sections[0].lstrip().startswith('#') or not sections[1].strip():
        raise ValueError('Expected route, title, charge/multiplicity and Cartesian coordinates')
    route = ' '.join(sections[0].split())
    # External launches and file inclusion can bypass reviewed program templates.
    if re.search(r'\bexternal\b|\binclude\b|@', text, re.I) or '--link1--' in text.lower():
        raise ValueError('External programs, includes and Link1 are unsupported')
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
