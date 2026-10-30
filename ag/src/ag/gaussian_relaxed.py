"""Bounded Gaussian syntax acceptance, without scientific method verification.

The relaxed path is deliberately separate from the strict validator. Its closed
file/command grammar prevents an additional reader or a later Link1 segment
from escaping the fresh Attempt or replacing an uploaded file. No input bytes
are repaired, inferred from Gaussian defaults, or written by this module.
"""
import math
import re

from ag import gaussian_input

MAX_ATTACHMENTS = 32
MAX_BYTES = 1024 * 1024
MAX_INCLUDE_DEPTH = 8
MAX_SECTIONS = 32
_RESERVED = {'job.pbs', 'job.slurm', 'input-validation.json', 'manifest.json',
             'submission.json', 'status.json', 'parent.chk', 'ag-start.json',
             'ag-exit.json', 'job.pbs.out', 'job.slurm.out', 'job.slurm.err', 'scratch'}
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
_NUMBER = gaussian_input.NUMBER
_ROUTE_KEYS = {'opt', 'freq', 'sp', 'force', 'irc', 'scf', 'int', 'integral',
               'scrf', 'pop', 'population', 'geom', 'geometry', 'guess', 'units',
               'unit', 'empiricaldispersion', 'em', 'nosymm', 'nosymmetry',
               'symmetry', '5d', '6d', '7f', '10f', 'pseudo', 'stable', 'polar',
               'density'}
_FORBIDDEN_WORDS = {'external', 'include', 'file', 'filename', 'output', 'punch',
                    'save', 'load', 'rwf', 'restart', 'extrabasis', 'extraoverlay',
                    'iop', 'massage', 'nbo6', 'nbo7', 'nbo6read',
                    'nbo7read', 'rcfc', 'readfc', 'readcartesianfc'}
_NBO_FLAGS = {'nbo', 'npa', 'nlmo', 'bndidx', 'steric', 'dipole', 'natural',
              'detail', 'print', 'nbosum', 'nobond', 'nomo', 'aonbo', 'aonlmo'}
_FEATURE_CHECKS = {
    'gen': 'general_basis_semantics', 'genecp': 'ecp_semantics',
    'scrf_read': 'scrf_read_semantics', 'nbo': 'nbo_section_semantics',
    'modredundant': 'modredundant_semantics', 'units': 'coordinate_unit_semantics',
    'checkpoint_geometry': 'checkpoint_geometry_science',
    'additional_sections': 'additional_section_semantics',
}


def filename(value):
    """Only unambiguous basenames, including on case-insensitive source disks."""
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError('Relaxed input files require a plain basename without aliases')
    return value


def _text(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise ValueError('Relaxed Gaussian input requires nonempty bounded bytes')
    try:
        text = data.decode('utf-8')
    except UnicodeError as exc:
        raise ValueError('Relaxed Gaussian input must be UTF-8 text') from exc
    if any(not c.isprintable() and c not in '\r\n\t' for c in text):
        raise ValueError('Control characters are unsupported in relaxed input')
    if re.search(r'external', re.sub(r'\s+', '', text), re.I):
        raise ValueError('External commands are forbidden in every input and attachment')
    return text


def _expand(data, attachments, input_name):
    if not isinstance(attachments, dict) or len(attachments) > MAX_ATTACHMENTS:
        raise ValueError('Too many or invalid relaxed input attachments')
    names = [input_name, *attachments]
    for name in names:
        filename(name)
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Input package aliases or duplicate basenames are forbidden')
    protected = _RESERVED | {input_name.casefold(), input_name.rsplit('.', 1)[0].casefold() + '.log'}
    for name in attachments:
        if name.casefold() in protected or name.casefold().endswith(('.chk', '.rwf', '.int', '.d2e')):
            raise ValueError('Attachment collides with a reserved or checkpoint file')
    if sum(len(value) for value in [data, *attachments.values()] if isinstance(value, bytes)) > MAX_BYTES:
        raise ValueError('Relaxed input package exceeds its byte bound')
    texts = {name: _text(value) for name, value in attachments.items()}
    used = set()
    expanded_size = 0

    def expand(text, stack):
        nonlocal expanded_size
        if len(stack) > MAX_INCLUDE_DEPTH:
            raise ValueError('Include recursion exceeds the depth bound')
        rows = []
        for row in text.splitlines(keepends=True):
            stripped = row.strip()
            if '@' in row:
                match = re.fullmatch(r'@([A-Za-z0-9][A-Za-z0-9_.-]{0,127})', stripped)
                if not match:
                    raise ValueError('Include must be exactly @basename; paths and aliases are forbidden')
                name = filename(match[1])
                if name not in texts:
                    raise ValueError('Include requires an explicitly packaged attachment: ' + name)
                if name in stack:
                    raise ValueError('Include cycle is forbidden')
                used.add(name)
                value = expand(texts[name], (*stack, name))
                rows.append(value + ('' if value.endswith('\n') else '\n'))
                continue
            if stack and (stripped.startswith(('%', '#')) or '--link1--' in stripped.lower()):
                raise ValueError('Attachments may contain data fragments only, not Link0, route or Link1')
            expanded_size += len(row.encode())
            if expanded_size > MAX_BYTES:
                raise ValueError('Expanded includes exceed the byte bound')
            rows.append(row)
        return ''.join(rows)

    expanded = expand(_text(data), ())
    if used != set(attachments):
        raise ValueError('Every packaged attachment must be explicitly referenced')
    return expanded, protected | {name.casefold() for name in attachments}


def _route(text):
    route = ' '.join(text.split())
    if not re.fullmatch(r'#[pnt]?\s+.+', route, re.I):
        raise ValueError('Each Link1 section requires a route')
    body = re.sub(r'^#[pnt]?\s+', '', route, flags=re.I)
    if not re.fullmatch(r'[A-Za-z0-9_+*,().= /-]+', body):
        raise ValueError('Unsupported command or file syntax in route')
    # Gaussian accepts whitespace around keyword punctuation and line wraps.
    body = re.sub(r'\s*([=,/])\s*', r'\1', body)
    body = re.sub(r'\(\s*', '(', body)
    body = re.sub(r'\s*\)', ')', body)
    tokens, start, level = [], 0, 0
    for index, char in enumerate(body):
        if char == '(':
            level += 1
        elif char == ')':
            level -= 1
        if level < 0 or level > 1:
            raise ValueError('Unbalanced or nested route syntax is unsupported')
        if char == ' ' and level == 0:
            if body[start:index]:
                tokens.append(body[start:index])
            start = index + 1
    if level:
        raise ValueError('Unbalanced route parentheses')
    if body[start:]:
        tokens.append(body[start:])
    options = {}
    for token in tokens:
        words = set(re.findall(r'[a-z][a-z0-9]*', token.lower()))
        if words & _FORBIDDEN_WORDS:
            raise ValueError('Unverified command/file route option is forbidden')
        if '/' in token:
            if '..' in token or token.startswith(('/', '.')) or token.count('/') != 1 or not re.fullmatch(r'[A-Za-z0-9+*(),.-]+/[A-Za-z0-9+*(),.-]+', token):
                raise ValueError('Method/basis must not contain a file path')
            if 'method' in options:
                raise ValueError('Multiple method/basis expressions are unsupported')
            options['method'] = token.lower()
            continue
        match = re.fullmatch(r'([A-Za-z0-9]+)(?:=?\(([^()]*)\)|=([A-Za-z0-9+_.-]+))?', token)
        if not match or match[1].lower() not in _ROUTE_KEYS:
            raise ValueError('Unreviewed route keyword in relaxed input: ' + token)
        key = match[1].lower()
        key = {'geometry': 'geom', 'population': 'pop', 'unit': 'units'}.get(key, key)
        if key in options:
            raise ValueError('Duplicate route keyword is unsupported: ' + key)
        options[key] = (match[2] or match[3] or '').lower()
    if 'method' not in options:
        raise ValueError('Relaxed route requires an explicit method/basis expression')
    # These keywords have readers/writers beyond the contained syntax below.
    for key in ('geom', 'guess', 'density', 'pop', 'pseudo', 'scrf'):
        words = set(re.findall(r'[a-z][a-z0-9]*', options.get(key, '')))
        allowed = {
            'geom': {'check', 'checkpoint', 'allcheck', 'connectivity', 'modredundant'},
            'guess': {'read', 'mix', 'huckel', 'core', 'always', 'only'},
            'density': {'current', 'scf', 'checkpoint', 'check'},
            'pop': {'nbo', 'nboread', 'npa', 'full', 'regular', 'minimal', 'none', 'hirshfeld', 'chelpg', 'mk'},
            'pseudo': {'read'},
        }.get(key)
        if allowed is not None and not words <= allowed:
            raise ValueError('Unsupported reader/writer option in ' + key)
    scalar_options = {
        'scrf': r'(?:pcm|cpcm|iefpcm|smd|read|solvent=[a-z0-9-]+)',
        'opt': r'(?:ts|calcfc|calcall|modredundant|tight|verytight|loose|cartesian|noeigentest|rfo|ef|gdiis|(?:maxcycles|maxstep|recalcfc)=\d+)',
        'freq': r'(?:noraman|raman|anharmonic|vcd|roa|numer|numerical)',
        'irc': r'(?:calcfc|forward|reverse|lqa|hpc|tight|(?:maxpoints|stepsize|recalc)=\d+)',
        'scf': r'(?:tight|verytight|xqc|qc|yqc|novaracc|direct|fermi|damp|(?:maxcycle|maxcycles|conver|vshift)=\d+)',
        'int': r'(?:ultrafine|superfinegrid|finegrid|ultrafinegrid|grid=[a-z0-9]+|acc2e=\d+)',
        'integral': r'(?:ultrafine|superfinegrid|finegrid|ultrafinegrid|grid=[a-z0-9]+|acc2e=\d+)',
    }
    for key, grammar in scalar_options.items():
        if options.get(key) and any(not re.fullmatch(grammar, item) for item in options[key].split(',')):
            raise ValueError('Unreviewed reader or option in ' + key)
    # These documented options read checkpoint/frequency data or select Linda
    # workers. Reject their prefixes too; scientific option values stay unverified.
    for key, readers in (
            ('stable', ('restart',)),
            ('polar', ('restart', 'raman', 'roa', 'dcshg', 'gamma', 'workerperturbations'))):
        for option in re.split(r'[\s,]+', options.get(key, '')):
            name = option.split('=', 1)[0]
            if name and any(reader.startswith(name) for reader in readers):
                raise ValueError('Unverified checkpoint/frequency reader or worker option in ' + key)
    return route, options


def _resources(lines, cores, mem_gb):
    link = {}
    while lines and lines[0].lstrip().startswith('%'):
        match = re.fullmatch(r'\s*%([A-Za-z]+)\s*=\s*(\S+)\s*', lines.pop(0))
        if not match:
            raise ValueError('Invalid Link0 directive')
        key, value = match[1].lower(), match[2]
        if key not in {'nprocshared', 'mem', 'chk', 'oldchk'} or key in link:
            raise ValueError('Unsupported or duplicate Link0 directive')
        link[key] = value
    if link.get('nprocshared') != str(cores):
        raise ValueError('Every Link1 section requires explicit %nprocshared matching the resource tier; inheritance is unsupported')
    match = re.fullmatch(r'(\d+)(GB|MB|GW|MW)', link.get('mem', ''), re.I)
    if not match:
        raise ValueError('Every Link1 section requires explicit integer %mem; inheritance is unsupported')
    factor = {'GB': 1000, 'MB': 1, 'GW': 8000, 'MW': 8}[match[2].upper()]
    memory_mb = int(match[1]) * factor
    if not 0 < memory_mb <= mem_gb * 850:
        raise ValueError('%mem exceeds 85% of the resource tier')
    return link, dict(cores=cores, mem_gb=memory_mb / 1000, source='explicit')


def _tail(text, options):
    if not text.strip():
        return
    if any(c in text for c in '\\;`|<>\"\'') or re.search(r'\b(?:' + '|'.join(_FORBIDDEN_WORDS) + r')\b', text, re.I):
        raise ValueError('File, command or unverified reader syntax in additional section')
    if re.search(r'[A-Za-z][A-Za-z0-9_-]*\.[A-Za-z]', text) or '/' in text or '%' in text or '#' in text:
        raise ValueError('Additional section filenames and directives are forbidden; use explicit @basename data includes')
    remainder = text
    if '$' in remainder:
        def nbo(match):
            if 'nboread' not in options.get('pop', ''):
                raise ValueError('$NBO section requires Pop=NBORead')
            if any(token.lower() not in _NBO_FLAGS for token in match[1].split()):
                raise ValueError('Unsupported NBO directive; file and execution options are forbidden')
            return ''
        remainder = re.sub(r'\$nbo\b(.*?)\$end\b', nbo, remainder, flags=re.I | re.S)
        if '$' in remainder:
            raise ValueError('Only bounded $NBO ... $END data sections are supported')
    basis = options['method'].split('/')[1] in {'gen', 'genecp'} or options.get('pseudo') == 'read'
    modred = 'modredundant' in options.get('opt', '') or 'modredundant' in options.get('geom', '')
    scrf = 'read' in re.findall(r'[a-z]+', options.get('scrf', ''))
    for row in remainder.splitlines():
        row = row.strip()
        if not row:
            continue
        if scrf and re.fullmatch(r'(?:eps|epsinf)\s*=\s*' + _NUMBER, row, re.I):
            if not math.isfinite(float(row.split('=')[1])):
                raise ValueError('SCRF parameters must be finite')
            continue
        fields = row.split()
        if modred and fields and all(re.fullmatch(_NUMBER, token) or token.upper() in {'*', 'B', 'A', 'D', 'L', 'X', 'S', 'F', 'R', 'K', 'H'} for token in fields):
            continue
        if basis and re.fullmatch(r'[A-Za-z0-9_+*,(). \t-]+', row):
            continue
        raise ValueError('Unverified additional-section syntax: ' + row)


def validate(data, *, cores, mem_gb, attachments=None, parent_chk=None, input_name='input.gjf'):
    """Return (science, immutable marker) for the exact main and attachment bytes.

    Attachments are data fragments explicitly named by @basename. The caller
    must read regular, non-aliased local files and bind every byte in its bundle;
    this pure validator never follows a path. Parent provenance is the existing
    parent_chk.declare result, rechecked by the existing submission mechanism.
    """
    expanded, protected = _expand(data, {} if attachments is None else attachments, input_name)
    pieces = re.split(r'(?im)^\s*--link1--\s*$', expanded)
    if len(pieces) > MAX_SECTIONS or any(not part.strip() for part in pieces):
        raise ValueError('Empty Link1 section or too many sections')
    if parent_chk is not None and (not isinstance(parent_chk, dict) or parent_chk.get('target_name') != 'parent.chk'
                                   or not isinstance(parent_chk.get('attempt_id'), str) or not parent_chk['attempt_id']):
        raise ValueError('Invalid declared parent checkpoint')
    known = {'parent.chk': dict(kind='parent_chk', attempt_id=parent_chk['attempt_id'], filename='parent.chk')} if parent_chk else {}
    used_parent = False
    sections = []
    for index, part in enumerate(pieces, 1):
        lines = part.strip().splitlines()
        link, resource = _resources(lines, cores, mem_gb)
        blocks = re.split(r'\n\s*\n', '\n'.join(lines).strip())
        route, options = _route(blocks[0])
        # A directive below Link0 can be consumed as data by an unexpected reader.
        if any(line.lstrip().startswith(('%', '#')) for block in blocks[1:] for line in block.splitlines()):
            raise ValueError('Link0 and route directives must appear only in their header')
        for key in ('chk', 'oldchk'):
            if key in link:
                name = filename(link[key])
                if not name.endswith('.chk'):
                    raise ValueError('Checkpoint requires a plain .chk basename')
                if key == 'chk' and name.casefold() in protected:
                    raise ValueError('Checkpoint target collides with a reserved uploaded or parent file')
        source = None
        if 'oldchk' in link:
            if link['oldchk'] not in known:
                raise ValueError('%oldchk requires a proven earlier section or declared parent checkpoint')
            if not link.get('chk') or link['chk'] == link['oldchk']:
                raise ValueError('%oldchk requires a distinct explicit %chk target')
            source = known[link['oldchk']]
            used_parent |= link['oldchk'] == 'parent.chk'
        elif link.get('chk') in known:
            source = known[link['chk']]
        geometry_options = set(re.findall(r'[a-z]+', options.get('geom', '')))
        from_checkpoint = bool(geometry_options & {'check', 'checkpoint', 'allcheck'})
        allcheck = 'allcheck' in geometry_options
        checkpoint_reader = ('read' in re.findall(r'[a-z]+', options.get('guess', ''))
                             or bool({'check', 'checkpoint'} & set(re.findall(r'[a-z]+', options.get('density', '')))))
        if (from_checkpoint or checkpoint_reader) and source is None:
            raise ValueError('Checkpoint reader requires a proven same-Attempt or declared parent source')
        features = set()
        basis = options['method'].split('/')[1]
        if basis in {'gen', 'genecp'}:
            features.add('gen')
        if basis == 'genecp' or options.get('pseudo') == 'read':
            features.add('genecp')
        for condition, feature in [('read' in re.findall(r'[a-z]+', options.get('scrf', '')), 'scrf_read'),
                                   ('nboread' in re.findall(r'[a-z]+', options.get('pop', '')), 'nbo'),
                                   ('modredundant' in options.get('opt', '') or 'modredundant' in geometry_options, 'modredundant'),
                                   ('units' in options, 'units'), (from_checkpoint, 'checkpoint_geometry')]:
            if condition:
                features.add(feature)
        charge = multiplicity = geometry = n_atoms = None
        if allcheck:
            tail = '\n\n'.join(blocks[1:])
        else:
            if len(blocks) < 3 or not blocks[1].strip():
                raise ValueError('Expected title and charge/multiplicity section')
            rows = blocks[2].splitlines()
            match = re.fullmatch(r'([+-]?\d+)\s+(\d+)', rows[0].strip())
            if not match or int(match[2]) < 1:
                raise ValueError('Invalid charge or multiplicity')
            charge, multiplicity = int(match[1]), int(match[2])
            if from_checkpoint:
                if len(rows) != 1:
                    raise ValueError('Geom=Check must omit explicit coordinates')
            else:
                if len(rows) < 2:
                    raise ValueError('Explicit geometry is required without Geom=Check/AllCheck')
                symbols = gaussian_input.cartesian(rows[1:], first_line=1)
                gaussian_input.check_electrons(symbols, charge, multiplicity, location=f'Link1 section {index}')
                geometry, n_atoms = '\n'.join(rows[1:]), len(symbols)
            tail = '\n\n'.join(blocks[3:])
        _tail(tail, options)
        if tail.strip():
            features.add('additional_sections')
        geometry_source = source if from_checkpoint else dict(kind='explicit', section=index)
        sections.append(dict(index=index, route=route, resources=resource, charge=charge,
                             multiplicity=multiplicity, geometry=geometry, n_atoms=n_atoms,
                             geometry_source=geometry_source, features=sorted(features)))
        if 'chk' in link:
            known[link['chk']] = dict(kind='earlier_section', section=index, filename=link['chk'])
    if parent_chk and not used_parent:
        raise ValueError('Declared parent checkpoint must be consumed through %oldchk=parent.chk')
    first = sections[0]
    science = {key: first[key] for key in ('charge', 'multiplicity', 'geometry', 'n_atoms', 'geometry_source')}
    science.update(route='\n--Link1--\n'.join(item['route'] for item in sections), sections=sections,
                   stereochemistry_warning='Review stereochemistry and each Link1 section; checkpoint geometry may be unknown. Scientific method and additional-section semantics are unverified.')
    checks = {'scientific_method'}
    for section in sections:
        checks.update(_FEATURE_CHECKS[feature] for feature in section['features'])
    if len(sections) > 1:
        checks.add('link1_scientific_consistency')
    marker = dict(mode='relaxed', skipped_checks=sorted(checks), method_verified=False)
    return science, marker
