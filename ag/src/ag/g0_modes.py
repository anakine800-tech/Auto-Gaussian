"""Cartesian Wilson-B projections of retrieved Gaussian modes (T138).

Diagnostics only: no Hessian, mode rotation, mass weighting or acceptance gate.
"""
from hashlib import sha256
import json
import re

from ag import attempt, catalog, geometry, mode_review, study as study_paths
from ag.facts import gaussian_log


CONVENTION = ('笛卡尔、未质量加权；Gaussian 打印位移 q 重新归一为单位长度 '
              '（‖q‖ = 1 Å）；δc = B q；距离变化用 Å，角度变化用弧度并另报度。'
              '不旋转、不对齐模式向量。')
NOTES = ['结果是诊断，不是 TS 验收；方向判断仍需人审。',
         '模式整体正负号任意；实频仅作参考，不参与标记。',
         '重叠度只用于报告和排序，不设阈值。',
         '|δc| < 1e-3 Å（距离）或 1e-3 rad（角度）记为 ≈0，符号不定；只是数值零容差，不是科学判据。']
# Numerical zero tests, not scientific cutoffs. Angles use their native radian
# unit; applying an angstrom tolerance to an angular derivative is undefined.
ZERO_TOLERANCE = {'distance': 1e-3, 'angle': 1e-3}
ROLES = {'distance': {'breaking': 1, 'forming': -1},
         'angle': {'increasing': 1, 'decreasing': -1, 'report': None}}


def coordinate_spec(value, n_atoms=None):
    """Validate one declaration before it can address a B-matrix row."""
    if not isinstance(value, dict) or set(value) - {'kind', 'atoms', 'role', 'label'}:
        raise ValueError('Invalid reaction coordinate fields')
    kind, atoms, role = (value.get(k) for k in ('kind', 'atoms', 'role'))
    if not isinstance(kind, str) or kind not in ROLES:
        raise ValueError('Reaction coordinate kind must be distance or angle')
    if (not isinstance(atoms, list) or len(atoms) != (2 if kind == 'distance' else 3)
            or any(type(i) is not int or i < 1 or (n_atoms is not None and i > n_atoms) for i in atoms)
            or len(set(atoms)) != len(atoms)):
        raise ValueError('Reaction coordinate atoms must be distinct in-range 1-based indices')
    if not isinstance(role, str) or role not in ROLES[kind]:
        raise ValueError('Invalid reaction coordinate role')
    label = value.get('label', '')
    if not isinstance(label, str):
        raise ValueError('Reaction coordinate label must be text')
    return dict(kind=kind, atoms=list(atoms), role=role, label=label)


def coordinate_argument(value):
    match = re.fullmatch(r'(distance|angle):([1-9][0-9]*(?:-[1-9][0-9]*)+):([a-z]+)', value)
    if not match:
        raise ValueError('Expected --reaction-coordinate kind:atoms:role')
    return coordinate_spec(dict(kind=match[1], atoms=list(map(int, match[2].split('-'))), role=match[3]))


def reaction_coordinates(config, target_channel, source=None, extra=()):
    """Use G0's already-read JSON and byte hash; never reopen its window file."""
    specs, sources = [], []
    if not isinstance(config, dict) or not isinstance(config.get('reaction_coordinates', {}), dict):
        raise ValueError('reaction_coordinates must be a channel-keyed object')
    for channel, values in config.get('reaction_coordinates', {}).items():
        study_paths.identifier(channel)
        if not isinstance(values, list):
            raise ValueError('Channel reaction coordinates must be a list')
        parsed = [coordinate_spec(value) for value in values]
        if channel == target_channel:
            specs = parsed
    if target_channel is not None:
        study_paths.identifier(target_channel)
    if source is not None:
        sources.append(dict(source, channel=target_channel, count=len(specs)))
    for value in extra:
        specs.append(coordinate_argument(value))
        sources.append(dict(command_line=value))
    return specs, sources


def wilson_row(coordinates, spec):
    """Return ∂c/∂x in the input frame; angle i-j-k has vertex j."""
    import numpy as np

    xyz = np.asarray(coordinates, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError('Expected finite N-by-3 coordinates')
    spec = coordinate_spec(spec, len(xyz))
    row = np.zeros_like(xyz)
    i, j, *rest = [a - 1 for a in spec['atoms']]
    u = xyz[i] - xyz[j]
    length = float(np.linalg.norm(u))
    if not 0 < length < float('inf'):
        raise ValueError('Degenerate reaction coordinate: coincident atoms or non-finite distance')
    u = u / length
    if spec['kind'] == 'distance':
        row[i], row[j] = u, -u
        return row
    k = rest[0]
    v = xyz[k] - xyz[j]
    other = float(np.linalg.norm(v))
    if not 0 < other < float('inf'):
        raise ValueError('角度坐标退化：重合原子或非有限距离')
    v = v / other
    cosine = float(np.clip(np.dot(u, v), -1, 1))
    sine = float(np.linalg.norm(np.cross(u, v)))
    if sine < 1e-6:
        raise ValueError('角度坐标退化：|sin θ| < 1e-6')
    row[i] = (cosine * u - v) / (length * sine)
    row[k] = (cosine * v - u) / (other * sine)
    row[j] = -row[i] - row[k]
    return row


def analyze_modes(elements, coordinates, frequencies, displacements, coordinates_spec):
    """Analyze all negative modes plus the lowest three nonnegative modes.

    Indices are 1-based indices in the supplied Gaussian frequency list. The
    mode's global sign maximizes nonzero sign matches, then the signed sum.
    An exact tie retains +1. A zero direction d has overlap 0 (no direction).
    """
    import numpy as np

    xyz, freq, vectors = (np.asarray(a, dtype=float) for a in (coordinates, frequencies, displacements))
    n = len(elements)
    if (n < 2 or xyz.shape != (n, 3) or freq.ndim != 1 or not len(freq)
            or vectors.shape != (len(freq), n, 3)
            or not all(np.isfinite(a).all() for a in (xyz, freq, vectors))):
        raise ValueError('Incomplete or non-finite geometry/frequency/displacement data')
    if not isinstance(coordinates_spec, (list, tuple)) or not coordinates_spec:
        raise ValueError('未声明反应坐标')
    specs = [coordinate_spec(s, n) for s in coordinates_spec]
    rows = np.asarray([wilson_row(xyz, s) for s in specs])
    signs = np.asarray([ROLES[s['kind']][s['role']] or 0 for s in specs])
    tolerances = np.asarray([ZERO_TOLERANCE[s['kind']] for s in specs])
    direction = np.einsum('k,kij->ij', signs, rows)
    norm_d = float(np.linalg.norm(direction))
    signed_count = int(np.count_nonzero(signs))
    order = sorted(range(len(freq)), key=lambda i: (freq[i], i))
    negative = [i for i in order if freq[i] < 0]
    reference = [i for i in order if freq[i] >= 0][:3]
    modes = []
    for i in negative + reference:
        # Scaling before normalization avoids overflow/underflow in the norm.
        scale = float(np.max(np.abs(vectors[i])))
        if scale == 0:
            raise ValueError(f'Mode {i + 1} has no nonzero displacement')
        q = vectors[i] / scale
        q = q / np.linalg.norm(q)
        delta = np.einsum('kij,ij->k', rows, q)
        zero = np.abs(delta) < tolerances
        signed = signs * delta
        def sign_key(sigma):
            return (int(np.count_nonzero((sigma * signed > 0) & ~zero)),
                    float(sigma * np.sum(signed)))
        sigma = max((1, -1), key=sign_key)
        details = []
        for spec, change, expected, near_zero in zip(specs, delta, signs, zero):
            corrected = sigma * float(change)
            entry = dict(spec, value=float(change), unit='angstrom' if spec['kind'] == 'distance' else 'radian',
                         expected_sign=int(expected) if expected else None,
                         corrected_value=corrected,
                         corrected_sign=None if near_zero else (1 if corrected > 0 else -1),
                         matches=None if near_zero or not expected else bool(expected * corrected > 0),
                         near_zero=bool(near_zero), zero_tolerance=ZERO_TOLERANCE[spec['kind']])
            if spec['kind'] == 'angle':
                entry.update(degrees=float(np.degrees(change)), corrected_degrees=float(np.degrees(corrected)))
            details.append(entry)
        overlap = abs(float(np.sum(q * direction))) / norm_d if norm_d else 0.0
        modes.append(dict(index=i + 1, frequency_cm1=float(freq[i]), imaginary=bool(freq[i] < 0),
                          delta=details, sigma=sigma, consistent_count=sign_key(sigma)[0],
                          signed_count=signed_count, overlap=min(1.0, overlap)))
    imaginary = [m for m in modes if m['imaginary']]
    best = max(imaginary, key=lambda m: (m['consistent_count'], m['overlap'])) if imaginary else None
    flags = []
    if not imaginary:
        flags.append('no_imaginary_mode')
    if len(imaginary) > 1:
        flags.append('multiple_imaginary_modes')
    if best and best['index'] != negative[0] + 1:
        flags.append('most_negative_not_best')
    if best and best['consistent_count'] < signed_count:
        flags.append('sign_inconsistent')
    notes = list(NOTES)
    if not norm_d:
        notes.append('有符号 B 行之和 d 为零（或未声明期望符号）；重叠度记 0，无合成方向。')
    return dict(convention=CONVENTION, modes=modes, best_mode=best['index'] if best else None,
                flags=flags, notes=notes)


def _stationarity(facts, section, block):
    """Only the facts' source-bound converged Opt establishes stationarity.

    Missing legacy source metadata is unknown. A later optimization cannot
    lend its convergence to an earlier Freq; nor can another Freq's facts.
    """
    sections, sources = facts.get('job_sections'), facts.get('fact_sources')
    if not isinstance(sections, list) or not isinstance(sources, dict):
        return 'unknown'
    freq_index, opt_index = sources.get('n_imag'), sources.get('opt_converged')
    if type(freq_index) is not int or freq_index != section['index']:
        return 'unknown'
    current = next((s for s in sections if isinstance(s, dict) and s.get('index') == freq_index), None)
    if current != section:
        return 'unknown'
    if facts.get('opt_converged') is not True:
        return 'non_stationary' if facts.get('opt_converged') in (False, None) else 'unknown'
    if type(opt_index) is not int or opt_index > freq_index:
        return 'unknown'
    opt = next((s for s in sections if isinstance(s, dict) and s.get('index') == opt_index), None)
    if not opt or opt.get('termination') != 'normal' or not re.search(
            r'(?:^|[\s#])opt\b', opt.get('route') or '', re.I):
        return 'unknown'
    if opt_index == freq_index:
        # The facts supply convergence, but not its line number. In a combined
        # section, confirm it precedes the already-validated harmonic block.
        prefix = re.split(rb'(?m)^[ \t]*Harmonic frequencies\b', block, maxsplit=1)[0]
        if not re.search(rb'(?m)^ ?Optimization completed\b', prefix):
            return 'unknown'
    return 'stationary'


class FrequencySourceAmbiguity(mode_review.FrequencySectionAmbiguity):
    """A classified parser ambiguity with the safely read source attached."""

    def __init__(self, reason, *, attempt, source):
        super().__init__(reason)
        self.attempt = attempt
        self.source = source


def read_frequency_attempt(study, attempt_id, *, allow_unavailable=False):
    """Read an exact fetched Gaussian Attempt, retaining its own mode frame."""
    root = catalog.resolve_study(study)
    path = study_paths.local_path(root, root / 'attempts' / study_paths.identifier(attempt_id))
    manifest, status, _ = attempt.local_record(path)
    if manifest.get('template') != 'gaussian':
        if allow_unavailable:
            return None
        raise ValueError('Mode projection requires a Gaussian Attempt')
    if status['state'] != 'fetched':
        if allow_unavailable:
            return None
        raise ValueError('Mode projection requires a fetched Attempt')
    facts = catalog.read_facts(root, path)
    log = study_paths.local_path(path / 'outputs', gaussian_log(path))
    raw = log.read_bytes()
    try:
        section, block = mode_review.frequency_section(raw)
    except mode_review.FrequencySectionAmbiguity as exc:
        raise FrequencySourceAmbiguity(
            str(exc), attempt=attempt_id,
            source=dict(log=log.relative_to(root).as_posix(), log_sha256=sha256(raw).hexdigest())) from exc
    except ValueError as exc:
        # Only absence is optional in a batch. Ambiguous sections, abnormal
        # termination and malformed vectors remain errors, not missing data.
        if allow_unavailable and str(exc) == 'No identifiable frequency job section':
            return None
        raise
    elements, coords, frequencies, displacements, orientation = mode_review.read_modes(block)
    geometry_bytes = json.dumps(dict(elements=elements, coordinates=coords.tolist()),
                                separators=(',', ':'), allow_nan=False).encode()
    return dict(elements=elements, coordinates=coords, frequencies=frequencies, displacements=displacements,
                attempt=attempt_id, orientation=orientation, stationarity=_stationarity(facts, section, block),
                geometry_sha256=sha256(geometry_bytes).hexdigest(),
                source=dict(log=log.relative_to(root).as_posix(), log_sha256=sha256(raw).hexdigest(),
                            section=section, section_sha256=sha256(block).hexdigest()))


def analyze_candidate(elements, coordinates, frequency, coordinates_spec):
    """Compare element order and report RMSD without transforming any mode."""
    if list(elements) != list(frequency['elements']):
        raise ValueError('Candidate and frequency element sequences differ; atom numbering cannot be matched')
    _, rmsd = geometry.kabsch(coordinates, frequency['coordinates'])
    if not coordinates_spec:
        return dict(available=False, reason='未声明反应坐标', attempt=frequency['attempt'],
                    aligned_rmsd_angstrom=float(rmsd), flags=[], coordinates_spec=[])
    report = analyze_modes(frequency['elements'], frequency['coordinates'], frequency['frequencies'],
                           frequency['displacements'], coordinates_spec)
    report.update({key: frequency[key] for key in
                   ('attempt', 'orientation', 'stationarity', 'geometry_sha256', 'source')})
    report.update(available=True, aligned_rmsd_angstrom=float(rmsd), coordinates_spec=coordinates_spec)
    if frequency['stationarity'] != 'stationary':
        report['flags'].append('non_stationary_frequencies')
        if frequency['stationarity'] == 'unknown':
            report['notes'].append('是否驻点未知，不当作驻点；频率仅作诊断参考。')
    return report
