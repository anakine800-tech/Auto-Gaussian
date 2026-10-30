"""Local normal-mode displacements and pair distances, with human interpretation.

Arithmetic adapted from create_mode_review in
archive/skills/auto-g16-ts-irc/scripts/ts_irc.py; no archive imports.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import re
import sys

from ag import __version__
from ag import _parse_outputs as outputs
from ag.facts import ag_provenance, gaussian_log
from ag.facts import (_publication_recheck, _local_review_write, _attempt_publication_sources,
                      _publication_pin, _publication_unchanged, _publication_stage)
from ag.study import identifier, local_path


NOTICE = '方向判断由人完成，本输出不判定反应坐标是否正确。'


def pair_argument(value):
    match = re.fullmatch(r'([1-9][0-9]*)-([1-9][0-9]*)', value)
    if match is None or match[1] == match[2]:
        raise ValueError('Atom pairs must be distinct 1-based indices, e.g. 1-2')
    return tuple(map(int, match.groups()))


def displace(elements, coordinates, frequencies, displacements, pairs, mode=1, amplitude=0.3):
    """Use raw Cartesian vectors for the derivative, scaled vectors for XYZ.

    d|r_i-r_j|/dq = (v_i-v_j).(r_i-r_j)/|r_i-r_j|, as in imag_modes.
    Ranking uses absolute derivatives over every pair, with competition ties.
    """
    import numpy as np

    xyz = np.asarray(coordinates, dtype=float)
    freq = np.asarray(frequencies, dtype=float)
    vectors = np.asarray(displacements, dtype=float)
    n = len(elements)
    if (n < 2 or xyz.shape != (n, 3) or freq.ndim != 1 or not len(freq)
            or vectors.shape != (len(freq), n, 3)
            or not all(np.isfinite(a).all() for a in (xyz, freq, vectors))):
        raise ValueError('Incomplete or non-finite geometry/frequency/displacement data')
    if not isinstance(mode, int) or isinstance(mode, bool) or not 1 <= mode <= len(freq):
        raise ValueError('Mode index is outside the frequency list (1-based)')
    if not math.isfinite(amplitude) or amplitude <= 0:
        raise ValueError('Amplitude must be finite and positive, in angstrom')
    if not pairs or any(len(pair) != 2 or pair[0] == pair[1] or any(
            not isinstance(i, int) or isinstance(i, bool) or not 1 <= i <= n for i in pair)
            for pair in pairs):
        raise ValueError('Atom pair indices are outside the geometry or not distinct')
    selected = int(np.argsort(freq, kind='stable')[mode - 1])
    vector = vectors[selected]
    maximum = float(np.max(np.linalg.norm(vector, axis=1)))
    if maximum == 0 or not math.isfinite(maximum):
        raise ValueError('Selected mode has no finite nonzero displacement')
    step = vector / maximum * amplitude
    plus, minus = xyz + step, xyz - step
    if not np.isfinite(plus).all() or not np.isfinite(minus).all():
        raise ValueError('Displaced coordinates are not finite')
    rates = {}
    for i in range(n):
        for j in range(i + 1, n):
            delta = xyz[i] - xyz[j]
            distance = float(np.linalg.norm(delta))
            if distance == 0 or not math.isfinite(distance):
                raise ValueError('Coincident atoms or non-finite pair distance')
            rates[i + 1, j + 1] = float(np.dot(vector[i] - vector[j], delta) / distance)
    magnitudes = sorted((abs(rate) for rate in rates.values()), reverse=True)
    ranks = {}
    for rank, value in enumerate(magnitudes, 1):
        ranks.setdefault(value, rank)
    rows = []
    for i, j in pairs:
        rate = rates[tuple(sorted((i, j)))]
        original = float(np.linalg.norm(xyz[i - 1] - xyz[j - 1]))
        pos = float(np.linalg.norm(plus[i - 1] - plus[j - 1]))
        neg = float(np.linalg.norm(minus[i - 1] - minus[j - 1]))
        def sign(value):
            return 0 if abs(value) <= 1e-12 else (1 if value > 0 else -1)
        ps, ms = sign(pos - original), sign(neg - original)
        rows.append(dict(atoms=[i, j], elements=[elements[i - 1], elements[j - 1]],
                         distance=original, plus_distance=pos, minus_distance=neg,
                         plus_change=pos - original, minus_change=neg - original,
                         plus_change_sign=ps, minus_change_sign=ms,
                         shortened_sides=[side for side, value in (('plus', ps), ('minus', ms)) if value < 0],
                         distance_change_rate=rate, absolute_rate_rank=ranks[abs(rate)]))
    report = dict(mode=mode, source_mode_index=selected + 1, frequency=float(freq[selected]),
                  amplitude=amplitude, raw_max_atom_displacement=maximum,
                  displacement_scale=amplitude / maximum, pairs=rows,
                  total_pairs=len(rates),
                  ranking='Absolute raw distance_change_rate, all atom pairs; equal values share rank',
                  rate_definition='(v_i-v_j) dot (r_i-r_j) / |r_i-r_j|; raw cclib Cartesian vectors',
                  units=dict(frequency='cm^-1', distance='angstrom', amplitude='angstrom',
                             distance_change_rate='angstrom per unit raw mode parameter'),
                  note=NOTICE + ' 模式整体正负号任意；有限振幅距离变化可能不同于线性导数。')
    return report, plus.tolist(), minus.tolist()


class FrequencySectionAmbiguity(ValueError):
    """Gaussian job boundaries cannot identify a unique frequency source."""


def frequency_section(raw):
    """Use T42 boundaries; never fall back to a whole-log cclib parse."""
    splitter = getattr(outputs, 'gaussian_job_sections', None)
    if splitter is None:
        raise ValueError('mode-review requires T42 Gaussian job-section parsing; update ag first')
    text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    sections, warnings = splitter(text)
    if warnings:
        raise FrequencySectionAmbiguity('Ambiguous Gaussian job sections: ' + '; '.join(warnings))
    candidates = [section for section in sections if re.search(
        r'(?:^|[\s#])freq\b', section.get('route') or '', re.I)]
    if not candidates:
        raise ValueError('No identifiable frequency job section')
    section = candidates[-1]
    if section['termination'] != 'normal':
        raise ValueError('Frequency job section did not terminate normally')
    # Hash original bytes, including original line endings, not reconstructed text.
    block = b''.join(raw.splitlines(keepends=True)[section['start_line'] - 1:section['end_line']])
    return section, block


def read_modes(block):
    """Confirm cclib's coordinates against the frequency section's own frame.

    Gaussian/cclib prints vibdisps in Standard orientation, or Input when
    symmetry is explicitly disabled (cclib gaussianparser.after_parsing).
    No alignment/rotation is used: RMSD alone cannot establish a vector frame.
    """
    import numpy as np
    from cclib.io import ccread
    from cclib.parser.utils import PeriodicTable

    text = block.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    harmonics = list(re.finditer(r'(?m)^[ \t]*Harmonic frequencies\b', text))
    if not harmonics:
        raise ValueError('No printed harmonic frequency block')
    # A later geometry or multiple different frequency geometries could pair
    # the final coordinates with an earlier mode. Reject that ambiguity.
    prefix = text[:harmonics[0].start()]
    orientation = 'Standard'
    if not re.search(r'(?m)^[ \t]*Standard orientation:', prefix):
        if not re.search(r'\bnosymm\b|\bsymmetry\s*=\s*(?:none|\(none\))|'
                         r'Symmetry turned off', prefix, re.I):
            raise ValueError('Cannot confirm mode orientation: no Standard frame or disabled-symmetry evidence')
        orientation = 'Input'
    expected = outputs.gaussian_orientation(prefix, orientation)
    if expected is None:
        raise ValueError('Missing or incomplete frequency geometry orientation')
    frames = re.findall(r'(?m)^[ \t]*(Standard|Input|Z-Matrix) orientation:', prefix)
    if frames[-1] != orientation:
        raise ValueError('Last printed geometry is not the confirmed mode orientation')
    if re.search(r'(?m)^[ \t]*(?:Standard|Input|Z-Matrix) orientation:', text[harmonics[0].end():]):
        raise ValueError('Geometry changes after frequency block; mode orientation is uncertain')
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            data = ccread(io.StringIO('Gaussian, Inc.\n' + text), loglevel=50)
    except (ValueError, IndexError, AssertionError, AttributeError, StopIteration) as exc:
        raise ValueError('Cannot parse frequency section with cclib') from exc
    if data is None or any(not hasattr(data, name) for name in
                           ('atomcoords', 'atomnos', 'vibfreqs', 'vibdisps')):
        raise ValueError('Incomplete cclib frequency geometry or mode vectors')
    table = PeriodicTable().element
    if any(not 0 < int(number) < len(table) for number in data.atomnos):
        raise ValueError('Unsupported atom numbers in frequency section')
    elements = [table[int(number)] for number in data.atomnos]
    coords = np.asarray(data.atomcoords[-1])
    if coords.shape != (len(elements), 3) or outputs.xyz_text(elements, coords) != expected:
        raise ValueError('cclib geometry does not match the frequency mode orientation')
    # cclib consumes displacement row order without checking the Atom/AN
    # columns. Confirm those identities before reusing user atom indices.
    lines = text.splitlines()
    printed_vectors, printed_frequencies = [], []
    for line_index, line in enumerate(lines):
        if re.match(r'^\s*Frequencies\s+--\s', line):
            printed_frequencies.extend(outputs.number(v) for v in line.split('--', 1)[1].split())
        if line.split()[:3] != ['Atom', 'AN', 'X']:
            continue
        rows = [row.split() for row in lines[line_index + 1:line_index + 1 + len(elements)]]
        try:
            if len(rows) != len(elements) or any(
                    len(row) < 5 or (len(row) - 2) % 3
                    or int(row[0]) != i + 1 or int(row[1]) != int(data.atomnos[i])
                    for i, row in enumerate(rows)):
                raise ValueError('Mode atom numbering/elements do not match the geometry')
            printed_vectors.extend(np.asarray([[outputs.number(v) for v in row[2:]] for row in rows])
                                   .reshape(len(elements), -1, 3).transpose(1, 0, 2))
        except (ValueError, IndexError) as exc:
            raise ValueError('Mode atom numbering/elements or vectors do not match the geometry') from exc
    printed = np.asarray(printed_vectors)
    parsed = np.asarray(data.vibdisps)
    if (printed.shape != parsed.shape or list(data.vibfreqs) != printed_frequencies
            or not np.allclose(printed, parsed, rtol=0, atol=0.00501)):
        # hpmodes can replace two-decimal vectors with higher precision;
        # differences larger than their rounding cannot establish correspondence.
        raise ValueError('Printed frequency modes and cclib vectors cannot be matched')
    return elements, coords, data.vibfreqs, data.vibdisps, orientation.lower()


def create(attempt, study, pairs, out, mode=1, amplitude=0.3, *,
           run_id=None, token=None, plan_sha256=None):
    root = Path(study).expanduser().absolute()
    root = local_path(root, root)
    directory = local_path(root, root / 'attempts' / identifier(attempt))
    with _local_review_write(root, run_id=run_id, token=token,
                             plan_sha256=plan_sha256) as publication, ExitStack() as sources:
        verify = _attempt_publication_sources(directory, sources)
        target = Path(out).expanduser()
        if not target.is_absolute():
            target = root / target
        target = local_path(root / 'analyses', target)
        parents = [_publication_pin(p, sources) for p in
                   (target.parent, *target.parent.parents) if p.is_relative_to(root)]
        return _create(attempt, root, directory, pairs, target, mode, amplitude,
                       publication, verify, parents)


def _create(attempt, root, directory, pairs, out, mode, amplitude, publication, verify, parents):
    manifest = json.loads(local_path(root, directory / 'manifest.json').read_text())
    if manifest.get('template') != 'gaussian':
        raise ValueError('mode-review requires a Gaussian Attempt')
    target = Path(out).expanduser()
    if not target.is_absolute():
        target = root / target
    target = local_path(root / 'analyses', target)
    if target.suffix != '.json':
        raise ValueError('--out must be a new .json file under the study analyses directory')
    paths = [target, target.with_suffix('.plus.xyz'), target.with_suffix('.minus.xyz')]
    for path in paths:
        local_path(root / 'analyses', path)
        if path.exists():
            raise FileExistsError(f'Output already exists: {path.name}')
    log = local_path(directory / 'outputs', gaussian_log(directory))
    raw = log.read_bytes()
    section, block = frequency_section(raw)
    elements, coords, frequencies, vectors, orientation = read_modes(block)
    report, plus, minus = displace(elements, coords, frequencies, vectors, pairs, mode, amplitude)
    report.update(ag_version=__version__, ag_provenance=ag_provenance(),
                  attempt=attempt, orientation=orientation,
                  source=dict(log=log.relative_to(root).as_posix(), log_sha256=sha256(raw).hexdigest(),
                              section=section, section_sha256=sha256(block).hexdigest()),
                  geometries=dict(plus=paths[1].name, minus=paths[2].name))
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    def xyz(coordinates, side):
        comment = f'Attempt {attempt}; mode {mode}; {side}; max displacement {amplitude:g} angstrom'
        return (f'{len(elements)}\n{comment}\n' + ''.join(
            f'{element:2s} {x: .10f} {y: .10f} {z: .10f}\n'
            for element, (x, y, z) in zip(elements, coordinates)))
    # Payload IO and fsync precede the shared guard. Exclusive links never
    # replace bytes; a partial set and its stages remain inspectable on failure.
    payloads = (content, xyz(plus, '+'), xyz(minus, '-'))
    staged = []
    with ExitStack() as stack:
        prepared = [_publication_stage(target.parent, payload.encode('utf-8'), stack, staged,
                                       prefix='.mode-review-stage-') for payload in payloads]
        with publication() as recheck:
            verify()
            for proof in parents + [proof for _, proof in prepared]:
                _publication_unchanged(proof)
            for path in paths:
                local_path(root / 'analyses', path)
            _publication_recheck(recheck)
            for (temporary, _), path in zip(prepared, paths):
                os.link(temporary, path, follow_symlinks=False)
    for temporary in staged:
        temporary.unlink()
    return report


def run(args):
    try:
        result = create(args.attempt, args.study, [pair_argument(pair) for pair in args.pair],
                        args.out, args.mode, args.amplitude, run_id=args.run,
                        token=args.token, plan_sha256=args.plan_sha256)
    except ImportError as exc:
        print(f'mode-review chemistry dependency unavailable: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(f'Mode {result["mode"]}: {result["frequency"]:g} cm^-1; amplitude {result["amplitude"]:g} Å')
        for row in result['pairs']:
            print(f'{row["atoms"]}: {row["distance"]:.6f} Å; + {row["plus_distance"]:.6f}; '
                  f'- {row["minus_distance"]:.6f}; rate {row["distance_change_rate"]:+.6f}; '
                  f'rank {row["absolute_rate_rank"]}/{result["total_pairs"]}; '
                  f'shorter: {row["shortened_sides"]}')
        print(f'报告：{args.out}\n{NOTICE}')
    return 0


def register(subparsers):
    parser = subparsers.add_parser('mode-review', help='Export local mode displacements and selected pair distances')
    parser.add_argument('attempt', help='Attempt ID')
    parser.add_argument('--study', required=True, help='Local study directory')
    parser.add_argument('--pair', action='append', required=True, help='1-based atom indices, e.g. 1-2; repeatable')
    parser.add_argument('--mode', type=int, default=1, help='1-based mode in ascending frequency order')
    parser.add_argument('--amplitude', type=float, default=0.3, help='Maximum atomic Cartesian displacement in angstrom')
    parser.add_argument('--out', type=Path, required=True, help='New JSON under analyses/; relative to study')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--run', help='Current autonomous review wake')
    parser.add_argument('--token', help='Current owner lease token')
    parser.add_argument('--plan-sha256', help='Confirmed plan hash')
    parser.set_defaults(func=run)
