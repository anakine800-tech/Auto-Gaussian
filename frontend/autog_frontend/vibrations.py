"""Offline Gaussian Cartesian-mode sidecar, plus pure read-only validation.

The builder reads only explicit bytes and a public detail DTO. GET validates a
pinned sidecar; it never invokes this builder, a chemistry parser or a process.
"""
import hashlib
import math
import re
from .parser_contract import qualified_parser

SCHEMA = 'auto-g16-vibration-modes/1'
DECODER = {'name': 'autog-gaussian-cartesian-display-modes', 'version': '1.1.0'}
DECODERS = (DECODER, {'name': DECODER['name'], 'version': '1.0.0'})
CONVENTION = 'gaussian-printed-normalized-cartesian-displacements'
MAX_ATOMS = 2000
MAX_MODES = 6000


def require(condition, reason='invalid-vibration-evidence'):
    if not condition:
        raise ValueError(reason)


def finite(v):
    return type(v) in (int, float) and math.isfinite(v)


def number(value):
    require(bool(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][+-]?\d+)?', value)), 'unsupported-number')
    n = float(value.replace('D', 'E').replace('d', 'e'))
    require(math.isfinite(n))
    return n


def bound(span, source):
    return (isinstance(span, dict) and isinstance(source, dict)
            and all(span.get(k) == v for k, v in source.items())
            and type(span.get('start')) is int and type(span.get('end')) is int
            and 0 <= span['start'] < span['end'] <= source['size_bytes'])


def validate_modes(packet, detail):
    """Validate pinned operator artifact against the current public Result DTO."""
    require(isinstance(packet, dict))
    result = detail['result']
    require(result['availability'] == 'available')
    source, data = result['source'], result['data']
    require(packet.get('schema') == SCHEMA and packet.get('decoder') in DECODERS)
    require(packet.get('kind') == detail['kind'] and packet.get('id') == detail['id'])
    require(packet.get('result_source') == source and packet.get('vector_convention') == CONVENTION)
    g = packet.get('reference_geometry')
    require(isinstance(g, dict) and g == data['last_geometry'])
    require(g.get('units') == 'angstrom' and g.get('orientation_kind') == 'standard-orientation')
    artifact = source['artifact']
    require(bound(g.get('source_span'), artifact))
    atoms = g['atoms']
    require(isinstance(atoms, list) and 1 <= len(atoms) <= MAX_ATOMS)
    require([a['center'] for a in atoms] == list(range(1, len(atoms)+1)))
    require(all(type(a['atomic_number']) is int and 1 <= a['atomic_number'] <= 118
                and all(finite(a[k]) and abs(a[k]) < 1e8 for k in ('x','y','z')) for a in atoms))
    blocks, frequencies = data['frequency_blocks'], data['frequencies_cm1']
    require([v for b in blocks for v in b['frequencies_cm-1']] == frequencies)
    modes = packet.get('modes')
    require(isinstance(modes, list) and 1 <= len(modes) == len(frequencies) <= min(MAX_MODES, 3*len(atoms)))
    ordinal = 0
    for bi, block in enumerate(blocks):
        require(bound(block['source_span'], artifact))
        for slot, frequency in enumerate(block['frequencies_cm-1']):
            m = modes[ordinal]
            require(isinstance(m, dict) and all(type(m.get(k)) is int for k in ('frequency_index','mode_number','block_index','column_index')))
            require(m.get('frequency_index') == ordinal and m.get('mode_number') == ordinal+1
                    and m.get('block_index') == bi and m.get('column_index') == slot
                    and finite(m.get('frequency_cm1')) and m['frequency_cm1'] == frequency)
            require(m.get('frequency_source_span') == block['source_span'])
            span = m.get('source_span')
            require(bound(span, artifact) and span['start'] == block['source_span']['start']
                    and span['end'] > block['source_span']['end'] and g['source_span']['end'] <= span['start'])
            rows = m.get('displacements')
            require(isinstance(rows, list) and len(rows) == len(atoms))
            for a, row in zip(atoms, rows):
                require(isinstance(row, dict) and type(row.get('center')) is int and type(row.get('atomic_number')) is int)
                require(row.get('center') == a['center'] and row.get('atomic_number') == a['atomic_number']
                        and all(finite(row.get(k)) and abs(row[k]) <= 1.05 for k in ('dx','dy','dz')))
            norm = math.sqrt(sum(row[k]**2 for row in rows for k in ('dx','dy','dz')))
            require(abs(norm-1) <= .03 + .005*math.sqrt(3*len(atoms)), 'invalid-vector-normalization')
            ordinal += 1
    return packet


def build_modes(detail, raw):
    """Offline only: qualify standard low-precision Atom/AN XYZ output.

    One harmonic analysis after the exact last Standard orientation is supported.
    New orientations, Link1/job boundaries or a second harmonic analysis are
    refused. Higher precision/internal-coordinate formats need separate adapters.
    """
    require(detail.get('result', {}).get('availability') == 'available', 'qualified-result-required')
    source, data = detail['result']['source'], detail['result']['data']
    require(qualified_parser(source['parser'], source['parser_version']))
    artifact, g = source['artifact'], data['last_geometry']
    require(len(raw) <= 32*1024*1024 and len(raw) == artifact['size_bytes'] and hashlib.sha256(raw).hexdigest() == artifact['sha256'], 'log-hash-mismatch')
    require(g is not None and g.get('orientation_kind') == 'standard-orientation' and bound(g['source_span'], artifact), 'reference-geometry-unavailable')
    atoms = g['atoms']; require(1 <= len(atoms) <= MAX_ATOMS)
    gs = g['source_span']; geometry_text = raw[gs['start']:gs['end']].decode('ascii')
    require('Standard orientation:' in geometry_text and 'Coordinates (Angstroms)' in geometry_text)
    parsed = []
    for line in geometry_text.splitlines():
        parts = line.split()
        if len(parts) == 6 and all(re.fullmatch(r'\d+', p) for p in parts[:3]):
            parsed.append(dict(center=int(parts[0]), atomic_number=int(parts[1]), x=number(parts[3]), y=number(parts[4]), z=number(parts[5])))
    require(parsed == atoms, 'reference-geometry-bytes-mismatch')
    blocks = data['frequency_blocks']; require(bool(blocks), 'no-frequency-blocks')
    require(all(bound(b['source_span'], artifact) for b in blocks))
    tail = raw[gs['end']:blocks[-1]['source_span']['start']]
    require(tail.count(b'Harmonic frequencies (cm**-1)') == 1, 'ambiguous-harmonic-analysis')
    require(not any(marker in tail for marker in (b'Standard orientation:', b'Input orientation:', b'Z-Matrix orientation:', b'Normal termination', b'Error termination', b'--Link1--', b'Entering Link 1')), 'cross-geometry-or-job-boundary')
    modes, previous_end = [], gs['end']
    for bi, block in enumerate(blocks):
        span = block['source_span']; require(span['start'] >= previous_end)
        lines = raw[span['start']:span['end']].decode('ascii').splitlines()
        indices = [int(x) for x in lines[0].split()]
        count = len(block['frequencies_cm-1'])
        require(1 <= count <= 3 and indices == list(range(len(modes)+1, len(modes)+count+1)), 'mode-indices-mismatch')
        freq_lines = [line.split('--',1)[1] for line in lines if re.match(r'\s*Frequencies\s+--',line)]
        require(len(freq_lines) == 1 and [number(v) for v in freq_lines[0].split()] == block['frequencies_cm-1'], 'frequency-bytes-mismatch')
        # Bound the extra read to the immediate displacement table only.
        extra = raw[span['end']:span['end']+256*(len(atoms)+2)].splitlines(keepends=True)
        require(bool(extra) and extra[0].split() == [b'Atom',b'AN']+[v for _ in range(count) for v in (b'X',b'Y',b'Z')], 'cartesian-vectors-not-present')
        require(len(extra) >= len(atoms)+2, 'truncated-vectors')
        vectors = [[] for _ in range(count)]
        offset = span['end'] + len(extra[0])
        for atom, line in zip(atoms, extra[1:len(atoms)+1]):
            parts = line.decode('ascii').split()
            require(len(parts) == 2+3*count and int(parts[0]) == atom['center'] and int(parts[1]) == atom['atomic_number'], 'atom-order-mismatch')
            values = [number(v) for v in parts[2:]]
            for slot in range(count):
                vectors[slot].append(dict(center=atom['center'],atomic_number=atom['atomic_number'],**dict(zip(('dx','dy','dz'), values[3*slot:3*slot+3]))))
            offset += len(line)
        next_row = extra[len(atoms)+1].split()
        require(not (len(next_row) == 2 + 3*count and all(re.fullmatch(rb'[0-9]+', v) for v in next_row[:2])), 'extra-vector-atoms')
        for slot, frequency in enumerate(block['frequencies_cm-1']):
            modes.append(dict(mode_number=indices[slot],frequency_index=len(modes),block_index=bi,column_index=slot,
                              frequency_cm1=frequency,frequency_source_span=span,source_span={**artifact,'start':span['start'],'end':offset},displacements=vectors[slot]))
        previous_end = offset
    packet = dict(schema=SCHEMA,kind=detail['kind'],id=detail['id'],decoder=DECODER,result_source=source,
                  vector_convention=CONVENTION,reference_geometry=g,modes=modes)
    return validate_modes(packet,detail)
