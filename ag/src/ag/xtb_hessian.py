"""Finite, local xTB v6.7.1 CLI Hessian diagnostics (T176).

No executable or command in the source declaration is ever run. This adapter
checks consistency of supplied evidence, not its authenticity or chemistry.
"""
from contextlib import ExitStack
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shlex

from ag import catalog, catalog_v2 as v2, study
from ag.gaussian_input import ATOMIC_NUMBERS

COMMIT = '26b28010e805f7d1aeeef39813feb473e69cc4be'
SCHEMA = 'ag-xtb-hessian-source/1'
ANALYSIS = 'ag-xtb-hessian/1'
BOHR_ANGSTROM = 0.52917726
FREQUENCY_FACTOR = 219474.63067 / math.sqrt(1.660539040e-27 / 9.10938356e-31)
CONVENTION = ('xTB Cartesian Hessian E_h/bohr²; K=s M^(-1/2) H M^(-1/2), masses in u; '
              'signed frequencies; q=M^(-1/2)e normalized to ||q||=1 Å; δc=Bq in source frame.')
LIMITATION = ('来源声明与记录的一致性不证明构建或化学真实性；数值诊断不是 TS、驻点或 DFT 提交验收。')
BUILD = dict(name='xtb', version='6.7.1', build='gfortran_h7141999_5', subdir='osx-64',
             sha256='2945f0ffa63ad5369ac7e32449c9e195b4204c9a2f57557a174f187d1f4ad2fa')
# Audited conda-forge recipe patches. None changes wrhess/g98fake2, trproj,
# CLI mass reset or the GFN2 Hessian weighting/conversion path. Not a claim
# about arbitrary v6.7.1 builds or the authenticity of a supplied run receipt.
PATCHES = {
    '1072.patch': '4afaece6b91cc2b1134ce092a99e483ccc168af66ced4c166832bb6ce39f7706',
    '1133.patch': 'dca101d6dcc225455e0982aeebf093333ac14e4af5e0142de28fc8e49b41f71f',
    '1278.patch': 'cd2d0d414e4e7970faf70505cd09a014471d77ed43cd14d95be11a7738aa7bc0',
    '1374.patch': '930c7c486f0b95bf1722d78e32cebc46b8006ad49b251a8e59758273472b2b7d',
    'version.patch': 'cf7b5f70bc6efd56be34ed62e35ad2091688d64f9ead0ab985c732fe69ffe763'}
# Numerical constants: fixed upstream src/mctc/param/atomic_masses.f90,
# commit COMMIT, atomic_mass_nist / amutoau. Not integer isotope masses.
MASSES = (
    1.00794075, 4.00260193, 6.94003660, 9.01218307, 10.81102805, 12.01073590, 14.00670321, 15.99940492,
    18.99840316, 20.18004638, 22.98976928, 24.30505162, 26.98153853, 28.08549871, 30.97376200, 32.06478741,
    35.45293758, 39.94779856, 39.09830091, 40.07802251, 44.95590828, 47.86674496, 50.94146504, 51.99613176,
    54.93804391, 55.84514443, 58.93319429, 58.69334711, 63.54603995, 65.37778253, 69.72306607, 72.62755016,
    74.92159457, 78.95938856, 79.90352778, 83.79800000, 85.46766360, 87.61664447, 88.90584030, 91.22364160,
    92.90637300, 95.95978854, 97.90721240, 101.06494014, 102.90549800, 106.41532751, 107.86814963, 112.41155782,
    114.81808663, 118.71011259, 121.75978367, 127.60312648, 126.90447190, 131.29276145, 132.90545196, 137.32689163,
    138.90546887, 140.11573074, 140.90765760, 144.24159603, 144.91275590, 150.36635571, 151.96437813, 157.25213065,
    158.92535470, 162.49947282, 164.93032880, 167.25908265, 168.93421790, 173.05415017, 174.96681496, 178.48497872,
    180.94787564, 183.84177755, 186.20670455, 190.22485963, 192.21605165, 195.08445686, 196.96656879, 200.59916703,
    204.38341284, 207.21690806, 208.98039910, 208.98243080, 209.98714790, 222.01757820, 223.01973600, 226.02541030,
    227.02775230, 232.03805580, 231.03588420, 238.02891046, 237.04817360, 244.06420530, 243.06138130, 247.07035410,
    247.07030730, 251.07958860, 252.08298000, 257.09510610, 258.09843150, 259.10103000, 262.10961000, 267.12179000,
    269.12791000, 271.13393000, 270.13336000, 276.14846000, 276.15159000, 280.16131000, 282.16912000, 284.17416000,
    284.17873000, 289.19042000, 288.19274000, 293.20449000, 292.20746000, 294.21392000)


def _object(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError(f'Invalid {name} fields')
    return value


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON value')))


def parse_hessian(raw, n_atoms):
    """Exactly the row-wise a5,5f15.10 writer; no guessing or symmetrizing."""
    import numpy as np

    size = 3 * n_atoms
    if type(n_atoms) is not int or n_atoms < 3:
        raise ValueError('Ordinary nonlinear Hessian requires at least three atoms')
    rows = raw.decode('ascii').splitlines()
    if not rows or not re.fullmatch(r'\$hessian *', rows[0]):
        raise ValueError('Expected ordinary xTB $hessian marker (not hessian.out)')
    chunks = (size + 4) // 5
    if len(rows) != 1 + size * chunks:
        raise ValueError('Hessian dimension/layout mismatch or extra content')
    values = []
    for i in range(size):
        row = []
        for j in range(chunks):
            line = rows[1 + i * chunks + j]
            count = min(5, size - j * 5)
            if len(line) != 5 + 15 * count or line[:5] != ' ' * 5:
                raise ValueError('Hessian requires exact a5,F15.10 row chunks')
            for k in range(count):
                token = line[5 + k * 15:5 + (k + 1) * 15]
                if not re.fullmatch(r' *-?\d+\.\d{10}', token):
                    raise ValueError('Invalid or non-finite Hessian number')
                row.append(float(token))
        values.append(row)
    matrix = np.asarray(values)
    if not np.isfinite(matrix).all() or not np.array_equal(matrix, matrix.T):
        raise ValueError('Hessian must be finite and exactly symmetric')
    return matrix


def parse_geometry(raw):
    """Only g98fake2's same-frequency-stage geometry, never its vectors."""
    import numpy as np

    rows = raw.decode('utf-8').splitlines()
    if sum('frequency output generated by the xtb code' in r for r in rows) != 1:
        raise ValueError('Missing or ambiguous xTB g98 geometry origin')
    starts = [i for i, r in enumerate(rows) if r.strip() == 'Standard orientation:']
    if len(starts) != 1:
        raise ValueError('Expected one xTB frequency-frame geometry')
    start = starts[0]
    if (start + 5 >= len(rows) or not re.fullmatch(r'\s*-{10,}', rows[start + 1]) or
            'Coordinates (Angstroms)' not in rows[start + 2] or
            'Number' not in rows[start + 3] or not re.fullmatch(r'\s*-{10,}', rows[start + 4])):
        raise ValueError('Invalid g98 geometry header/units')
    symbols_by_z = {z: s for s, z in ATOMIC_NUMBERS.items()}
    symbols, coordinates = [], []
    index = start + 5
    while index < len(rows) and not re.fullmatch(r'\s*-{10,}', rows[index]):
        line = rows[index]
        if not re.fullmatch(r'\s*\d+\s+\d+\s+0(?:\s+-?\d+\.\d{6}){3}\s*', line):
            raise ValueError('Invalid g98 atom row or coordinate precision')
        fields = line.split()
        if int(fields[0]) != len(symbols) + 1 or int(fields[1]) not in symbols_by_z:
            raise ValueError('Invalid g98 atom order or atomic number')
        symbols.append(symbols_by_z[int(fields[1])])
        coordinates.append([float(v) for v in fields[3:]])
        index += 1
    if index == len(rows) or len(symbols) < 3 or not np.isfinite(coordinates).all():
        raise ValueError('Truncated or invalid g98 geometry')
    return symbols, np.asarray(coordinates), dict(start_line=start + 1, end_line=index + 1,
                                                 coordinate_error_angstrom=0.5e-6)


def convert(matrix, coordinates, masses, scale, *, coordinate_error=0.5e-6, hessian_error=0.5e-10):
    """Keep the full signed eigensystem; identify external space by geometry.

    Weyl bounds identify the zero cluster. Wedin/Davis-Kahan bounds account
    for g98 F12.6 geometry and wrhess F15.10 rounding. Ambiguous soft internal
    modes remain unresolved; no smallest-six deletion or second projection.
    """
    import numpy as np

    xyz, mass, h = (np.asarray(a, dtype=float) for a in (coordinates, masses, matrix))
    n = len(mass)
    if (n < 3 or xyz.shape != (n, 3) or h.shape != (3*n, 3*n) or
            not all(np.isfinite(a).all() for a in (xyz, mass, h)) or np.any(mass <= 0) or
            type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0 or
            not np.array_equal(h, h.T) or not 0 <= coordinate_error <= 0.5e-6 or
            not 0 <= hessian_error <= 0.5e-10):
        raise ValueError('Invalid finite matrix, masses, scale, geometry or precision')
    weight = np.repeat(np.sqrt(mass), 3)
    with np.errstate(over='raise', invalid='raise', divide='raise'):
        try:
            k = scale * h / weight[:, None] / weight[None, :]
            eigenvalues, eigenvectors = np.linalg.eigh(k)
        except (FloatingPointError, np.linalg.LinAlgError) as exc:
            raise ValueError('Hessian numerical conversion failed') from exc
    if not np.isfinite(eigenvalues).all() or not np.isfinite(eigenvectors).all():
        raise ValueError('Non-finite eigensystem')
    frequencies = np.sign(eigenvalues) * FREQUENCY_FACTOR * np.sqrt(np.abs(eigenvalues))
    cartesian = eigenvectors / weight[:, None]
    cartesian /= np.linalg.norm(cartesian, axis=0)
    result = dict(full_eigenvalues=eigenvalues.tolist(), full_frequencies_cm1=frequencies.tolist(),
                  full_displacements=cartesian.T.reshape(3*n, n, 3).tolist(),
                  status='external_modes_unresolved', internal_indices=[], external_indices=[],
                  convention=CONVENTION)
    # Each rotation is normalized separately to avoid a unit-dependent rank test.
    centered = xyz - np.sum(xyz * (mass / mass.sum())[:, None], axis=0)
    translations = [np.tile(axis, (n, 1)) for axis in np.eye(3)]
    rotations = [np.cross(axis, centered) for axis in np.eye(3)]
    a = np.column_stack([r.reshape(-1) * weight for r in translations + rotations])
    norms = np.linalg.norm(a, axis=0)
    # COM error <= sqrt(3)*coordinate_error; each centered atom error <= twice that.
    rotation_error = 2 * math.sqrt(3 * float(mass.sum())) * coordinate_error
    errors = np.array([0.] * 3 + [rotation_error] * 3)
    if np.any(norms <= errors):
        result['external'] = dict(rank=None, reason='Geometry precision cannot resolve rotation axes')
        return result
    normalized = a / norms
    u, singular, _ = np.linalg.svd(normalized, full_matrices=False)
    perturbation = float(np.linalg.norm(2 * errors / (norms - errors)))
    roundoff = 64 * np.finfo(float).eps * (3*n)
    rank = int(np.count_nonzero(singular > perturbation + roundoff))
    evidence = dict(rank=rank, singular_values=singular.tolist(), basis_error_bound=perturbation,
                    hessian_entry_error=hessian_error, coordinate_error_angstrom=coordinate_error)
    result['external'] = evidence
    if rank != 6:
        evidence['reason'] = 'Nonlinear rigid-body rank is not resolved at supplied precision'
        return result
    basis_error = perturbation / (float(singular[-1]) - perturbation) + roundoff
    norm_k = float(np.max(np.abs(eigenvalues)))
    delta_k = (3*n) * hessian_error * scale / float(mass.min()) + roundoff * norm_k
    external = np.flatnonzero(np.abs(eigenvalues) <= delta_k)
    evidence.update(eigenvalue_error_bound=delta_k, rigid_subspace_error_bound=basis_error,
                    zero_cluster_size=len(external))
    if len(external) != 6 or basis_error >= 1:
        evidence['reason'] = 'Zero cluster cannot be separated from internal modes'
        return result
    internal = np.array([i for i in range(3*n) if i not in external])
    gap = float(np.min(np.abs(eigenvalues[internal])))
    leakage = float(np.linalg.norm(u - eigenvectors[:, external] @ (eigenvectors[:, external].T @ u), 2))
    leakage_bound = basis_error + delta_k / (gap - delta_k) + roundoff
    residual = float(np.linalg.norm(k @ u, 2))
    residual_bound = delta_k + norm_k * basis_error
    evidence.update(internal_gap=gap, subspace_residual=leakage, subspace_bound=leakage_bound,
                    rigid_residual=residual, rigid_residual_bound=residual_bound)
    if leakage_bound >= 1 or leakage > leakage_bound or residual > residual_bound:
        evidence['reason'] = 'Near-zero spectral space does not resolve the geometry rigid-body space'
        return result
    result.update(status='available', internal_indices=(internal + 1).tolist(),
                  external_indices=(external + 1).tolist())
    return result


def _relative(name):
    if (not isinstance(name, str) or not name or Path(name).is_absolute() or
            '..' in Path(name).parts or name in ('.', '..')):
        raise ValueError('Source file must be relative and inside the source directory')
    return name


def _read_source(path):
    """Read once, then retain exactly these bytes (including declaration)."""
    path = v2.source_path(path)
    raw = v2.read_bytes(path, 1024*1024)
    source = _json(raw)
    _object(source, 'schema files program generation hessian geometry masses scale method solvent termination stationarity',
            'xTB source')
    if source['schema'] != SCHEMA or not isinstance(source['files'], dict):
        raise ValueError('Unsupported xTB source schema')
    payloads, bindings = {'source.json': raw}, {}
    for i, (role, ref) in enumerate(source['files'].items()):
        study.identifier(role)
        _object(ref, 'file sha256', 'file reference')
        name = _relative(ref['file'])
        data = v2.read_bytes(study.local_path(path.parent, path.parent / name), 64*1024*1024)
        if sha256(data).hexdigest() != ref['sha256']:
            raise ValueError(f'Source SHA-256 mismatch: {role}')
        stored = f'input-{i:03d}'
        payloads[stored] = data
        bindings[role] = dict(file=stored, sha256=ref['sha256'])
    return source, payloads, bindings


def _diagnose(source, files):
    """Finite evidence reader; all actual sources are selected by the CLI JSON."""
    def content(role):
        study.identifier(role)
        if role not in files:
            raise ValueError(f'Missing required source file: {role}')
        return files[role].decode('utf-8')

    program = _object(source['program'], 'version source_commit build', 'program')
    if program['version'] != '6.7.1' or program['source_commit'] != COMMIT:
        raise ValueError('Only the audited xTB v6.7.1 source is supported')
    build = _json(content(program['build']))
    if not isinstance(build, dict) or any(build.get(k) != v for k, v in BUILD.items()):
        raise ValueError('Unknown or contradictory xTB package/build evidence')
    if build.get('channel') != 'https://conda.anaconda.org/conda-forge/osx-64':
        raise ValueError('Unknown xTB build channel')
    stdout, stderr = content('stdout'), content('stderr')
    versions = re.findall(r'\*\s*xtb version\s+(\S+)', stdout, re.I)
    if versions != ['6.7.1'] or not re.search(r'xtb version\s+6\.7\.1\s+\(edcfbbe\)', stdout):
        raise ValueError('Missing, ambiguous or contradictory stdout xTB version')
    generation = _object(source['generation'], 'command controls path', 'generation')
    if generation['path'] != 'cli-numhess' or not isinstance(generation['controls'], list):
        raise ValueError('Only ordinary CLI numhess generation is supported')
    command = content(generation['command']).strip()
    if command.startswith('{'):
        execution = _json(command)
        argv = execution.get('argv') if isinstance(execution, dict) else None
        if not isinstance(argv, list) or any(not isinstance(a, str) or not a for a in argv):
            raise ValueError('Captured execution record requires argv strings')
    else:
        if '\n' in command:
            raise ValueError('Expected a single captured command line')
        argv = shlex.split(command)
    calls = re.findall(r'(?m)^\s*program call\s*:\s*(.+?)\s*$', stdout)
    if calls != [' '.join(argv)]:
        raise ValueError('Captured command contradicts raw program call')
    if 'result' in files:
        receipt = _json(content('result'))
        if (not isinstance(receipt, dict) or receipt.get('argv') != argv or
                receipt.get('timed_out') is not False or type(receipt.get('returncode')) is not int or
                receipt['returncode'] != 0 or receipt.get('executed') is not True):
            raise ValueError('Known abnormal or contradictory execution result')
    # This finite subset can be checked without interpreting shell/script text.
    if len(argv) < 3 or Path(argv[0]).name != 'xtb' or not argv[1].endswith('.xyz'):
        raise ValueError('Unsupported captured xTB invocation')
    args, options, index = argv[2:], {}, 0
    flags = {'--hess', '--ohess', '--norestart'}
    valued = {'--gfn', '--chrg', '--uhf', '--alpb', '--gbsa', '--input', '--acc', '--parallel'}
    while index < len(args):
        key = args[index]
        if key in options or key not in flags | valued:
            raise ValueError('Unsupported or repeated xTB generation option')
        if key in flags:
            options[key] = True
            index += 1
            if key == '--ohess' and index < len(args) and not args[index].startswith('--'):
                if args[index] not in ('crude', 'sloppy', 'loose', 'lax', 'normal', 'tight', 'verytight', 'extreme'):
                    raise ValueError('Unsupported optimization level')
                options[key] = args[index]
                index += 1
        else:
            if index + 1 >= len(args) or args[index + 1].startswith('--'):
                raise ValueError('Missing xTB generation option value')
            options[key] = args[index + 1]
            index += 2
    if sum(k in options for k in ('--hess', '--ohess')) != 1:
        raise ValueError('Exactly one ordinary --hess/--ohess is required')
    if options.get('--gfn', '2') != '2':
        raise ValueError('Only the audited GFN2 ordinary Hessian path is supported')
    # Raw input is bound even though it must never replace the post-rotation geometry.
    input_raw = files.get('input', b'')
    input_count, _ = v2.xyz(input_raw)
    input_elements = [row.split()[0] for row in input_raw.decode('utf-8').splitlines()[2:2+input_count]]
    if source['files']['input']['file'] != argv[1]:
        raise ValueError('Captured command/input binding mismatch')
    controls = generation['controls']
    if any(not isinstance(c, str) for c in controls) or len(set(controls)) != len(controls):
        raise ValueError('Invalid control sources')
    if '--input' in options and not any(source['files'][c]['file'] == options['--input'] for c in controls):
        raise ValueError('Missing explicitly requested control file')
    if any(c not in source['files'] for c in controls):
        raise ValueError('Missing declared control file')
    requested = []
    for role in controls:
        block = None
        for row in content(role).splitlines():
            row = row.split('#', 1)[0].strip().lower()
            if not row:
                continue
            if row in ('$hess', '$end'):
                block = row
                continue
            # Only the audited mass requests are supported, and v6.7.1 resets them.
            match = re.fullmatch(r'(isotope|modify mass|scale mass|element mass)\s*:\s*(.+)', row)
            if block != '$hess' or match is None:
                raise ValueError('Unsupported control block, constraint or Hessian modification')
            requested.append(row)
    hessian = _object(source['hessian'], 'format unit mass_weighted projected', 'Hessian semantics')
    if (hessian != dict(format='xtb-v671-wrhess', unit='hartree/bohr^2', mass_weighted=False, projected=True) or
            hessian['mass_weighted'] is not False or hessian['projected'] is not True):
        raise ValueError('Unsupported Hessian units, weighting or projection')
    if not re.search(r'(?m)^\s*writing file <hessian>\.\s*$', stdout) or not re.search(
            r'(?m)^\s*projected vibrational frequencies', stdout):
        raise ValueError('Missing ordinary projected Hessian generation evidence')
    frozen = re.findall(r'(?m)^\s*frozen atoms in %\s*:\s*([\d.]+)\s+(\d+)\s*$', stdout)
    if len(frozen) != 1 or any(float(value) != 0 for value in frozen[0]):
        raise ValueError('Frozen or unknown Hessian atoms are unsupported')
    geom = _object(source['geometry'], 'format unit', 'geometry')
    if geom != dict(format='xtb-g98', unit='angstrom'):
        raise ValueError('Only same-stage xTB g98 geometry in angstrom is supported')
    content('geometry')
    content('hessian')
    elements, coordinates, locator = parse_geometry(files['geometry'])
    if input_elements != elements:
        raise ValueError('Input/frequency geometry atom count or order contradiction')
    matrix = parse_hessian(files['hessian'], len(elements))
    effective = [MASSES[ATOMIC_NUMBERS[s] - 1] for s in elements]
    mass = _object(source['masses'], 'effective_u basis', 'masses')
    if mass['basis'] != 'v671-cli-default-reset' or mass['effective_u'] != effective:
        raise ValueError('Unknown or contradictory final effective masses; requests/echoes are not effective masses')
    echoed = [row.strip() for row in stdout.splitlines() if re.search(r'mass of .* changed to', row)]
    if len(echoed) < len(requested):
        raise ValueError('Mass request/printed echo source contradiction')
    scale = source['scale']
    scales = re.findall(r'(?m)^\s*Hessian scale factor\s*:\s*(\d+\.\d{5})\s*$', stdout)
    if (len(scales) != 1 or type(scale) not in (int, float) or not math.isfinite(scale) or
            scale != 1 or float(scales[0]) != scale):
        raise ValueError('Missing or contradictory Hessian scaling evidence')
    termination = source['termination']
    if termination not in ('normal', 'unknown', 'error'):
        raise ValueError('Invalid termination status')
    text = stdout + '\n' + stderr
    if (termination == 'error' or re.search(r'(?im)^\s*(?:abnormal termination of xtb|\[ERROR\]|ERROR STOP|'
                                           r'forrtl: severe|segmentation fault|.*(?:TIME LIMIT|CANCELLED|killed by signal))', text)):
        raise ValueError('Known abnormal termination; no usable modes published')
    normal = bool(re.search(r'(?im)^\s*normal termination of xtb\s*$', text))
    if termination == 'normal' and not normal:
        raise ValueError('Termination declaration contradicts raw output')
    stationarity = source['stationarity']
    if stationarity not in ('unknown', 'non_stationary'):
        raise ValueError('This adapter does not establish a confirmed stationary point')
    if 'INCOMPLETELY OPTIMIZED GEOMETRY' in stdout:
        stationarity = 'non_stationary'
    warnings = [LIMITATION]
    for key in ('method', 'solvent'):
        # Values are descriptive declarations; provenance is retained, not promoted to verification.
        if source[key] is not None and not isinstance(source[key], str):
            raise ValueError(f'{key} must be descriptive text or null (unknown)')
        warnings.append(f'{key}: 未独立核实' if source[key] is not None else f'{key}: unknown')
    if source['method'] not in (None, 'GFN2-xTB'):
        raise ValueError('Method declaration contradicts the selected GFN2 path')
    solvent = (('ALPB:' + options['--alpb']) if '--alpb' in options else
               ('GBSA:' + options['--gbsa']) if '--gbsa' in options else 'gas')
    if ('--alpb' in options and '--gbsa' in options) or source['solvent'] not in (None, solvent):
        raise ValueError('Solvent declaration contradicts generation options')
    if termination == 'unknown':
        warnings.append('正常结束证据未核实；仅作有警示的数学诊断')
    converted = convert(matrix, coordinates, effective, scale)
    if converted['status'] == 'available':
        # Companion g98 frequencies are independent printed evidence; its
        # mass-weighted/two-decimal vectors are deliberately never consumed.
        printed, frequency_blocks, empty_blocks = [], 0, 0
        for line in content('geometry').splitlines():
            if 'Frequencies --' in line:
                frequency_blocks += 1
                fields = line.split('Frequencies --', 1)[1].split()
                empty_blocks += not fields
                if any(not re.fullmatch(r'-?\d+\.\d{4}', f) for f in fields):
                    raise ValueError('Invalid xTB g98 printed frequencies')
                printed.extend(float(f) for f in fields)
        delta = converted['external']['eigenvalue_error_bound']
        values = [converted['full_eigenvalues'][i-1] for i in converted['internal_indices']]
        def signed_frequency(value):
            return math.copysign(FREQUENCY_FACTOR * math.sqrt(abs(value)), value)
        intervals = [(signed_frequency(v-delta), signed_frequency(v+delta))
                     for v in values]
        # g98fake2 prints only abs(f)>0.1, before F11.4 rounding. A
        # serialization interval crossing that boundary may either be absent
        # or contribute one printed frequency. Match an ordered visible subset
        # without greedily consuming a value needed by a mandatory later mode.
        # This filters companion evidence only: every internal mode is retained.
        printed.sort()
        positions = {0}
        for low, high in intervals:
            can_hide = low <= .1 and high >= -.1
            following = set()
            for j in positions:
                if can_hide:
                    following.add(j)
                if j < len(printed):
                    left, right = max(low, printed[j]-.00005), min(high, printed[j]+.00005)
                    if left <= right and (left < -.1 or right > .1):
                        following.add(j+1)
            positions = following
        if (not frequency_blocks or (empty_blocks and (printed or frequency_blocks != 1)) or
                len(printed) not in positions):
            raise ValueError('Companion g98 spectrum contradicts Hessian/masses/scale')
    return dict(schema=ANALYSIS, program=dict(program, package=BUILD, patches=PATCHES),
                elements=elements, coordinates=coordinates.tolist(),
                geometry_locator=locator, effective_masses_u=effective,
                mass_evidence=dict(basis=mass['basis'], requested=requested, printed_echoes=echoed,
                                   outcome='default initialization after read_userdata overrides requests'),
                scale=scale, method=source['method'], solvent=source['solvent'],
                termination=termination, stationarity=stationarity, warnings=warnings, **converted)


def import_hessian(root, source_path, out):
    root = catalog.resolve_study(root)
    out = Path(out)
    out = study.local_path(root / 'analyses', out if out.is_absolute() else root / out)
    if out.parent != root / 'analyses' or out.name.startswith('.'):
        raise ValueError('--out must be a new immediate directory under study analyses/')
    study.identifier(out.name)
    source, payloads, bindings = _read_source(source_path)
    report = _diagnose(source, {role: payloads[ref['file']] for role, ref in bindings.items()})
    report.update(source_sha256=sha256(payloads['source.json']).hexdigest(), inputs=bindings)
    analysis_raw = catalog.encode(report)
    payloads['binding.json'] = catalog.encode(dict(schema=ANALYSIS, sha256=sha256(analysis_raw).hexdigest(),
                                                  source_sha256=report['source_sha256']))
    # Recheck the external input bytes before reserving/publishing any output.
    _, reread, _ = _read_source(source_path)
    if reread != {k: v for k, v in payloads.items() if k != 'binding.json'}:
        raise ValueError('Source changed during import')
    with ExitStack() as stack:
        fd = os.open(out.anchor, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, fd)
        for part in out.parent.parts[1:]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        os.mkdir(out.name, mode=0o700, dir_fd=fd)  # exclusive; existing directory refuses
        dest = os.open(out.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        stack.callback(os.close, dest)
        # analysis.json is linked last, only after all bytes have been flushed.
        for name, raw in dict(payloads, **{'.analysis.partial': analysis_raw}).items():
            handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dest)
            with os.fdopen(handle, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        os.link('.analysis.partial', 'analysis.json', src_dir_fd=dest, dst_dir_fd=dest, follow_symlinks=False)
    return report


def read_analysis(root, value):
    """Recompute from retained original bytes; never trust edited mode arrays."""
    import numpy as np

    root = catalog.resolve_study(root)
    path = Path(value)
    path = study.local_path(root / 'analyses', path if path.is_absolute() else root / path)
    if path.name != 'analysis.json' or path.parent.parent != root / 'analyses':
        raise ValueError('Expected analyses/<directory>/analysis.json')
    raw = v2.read_bytes(path, 64*1024*1024)
    record = _json(raw)
    if not isinstance(record, dict) or record.get('schema') != ANALYSIS:
        raise ValueError('Unsupported xTB analysis record')
    binding = _json(v2.read_bytes(path.parent / 'binding.json', 1024))
    if binding != dict(schema=ANALYSIS, sha256=sha256(raw).hexdigest(), source_sha256=record.get('source_sha256')):
        raise ValueError('Analysis conversion/mode binding mismatch')
    original = v2.read_bytes(path.parent / 'source.json', 1024*1024)
    if sha256(original).hexdigest() != record.get('source_sha256'):
        raise ValueError('Analysis source binding mismatch')
    source = _json(original)
    payloads, bindings = {}, {}
    for i, (role, ref) in enumerate(source['files'].items()):
        name = f'input-{i:03d}'
        data = v2.read_bytes(path.parent / name, 64*1024*1024)
        if sha256(data).hexdigest() != ref['sha256']:
            raise ValueError('Analysis original input binding mismatch')
        payloads[role] = data
        bindings[role] = dict(file=name, sha256=ref['sha256'])
    expected = _diagnose(source, payloads)
    expected.update(source_sha256=sha256(original).hexdigest(), inputs=bindings)
    # Bind exact persisted bytes; numerical revalidation allows only eigensolver
    # roundoff/sign/degenerate-basis differences when reopening on another BLAS.
    numeric = ('full_eigenvalues', 'full_frequencies_cm1', 'full_displacements', 'external')
    if any(record.get(k) != v for k, v in expected.items() if k not in numeric):
        raise ValueError('Analysis source/conversion binding mismatch')
    if not np.allclose(record['full_eigenvalues'], expected['full_eigenvalues'], rtol=1e-12, atol=1e-13):
        raise ValueError('Analysis spectrum binding mismatch')
    eigenvalues = np.asarray(record['full_eigenvalues'])
    vectors = np.asarray(record['full_displacements'])
    count = len(record['elements'])
    if vectors.shape != (3*count, count, 3) or not np.isfinite(vectors).all():
        raise ValueError('Invalid stored Cartesian modes')
    weight = np.repeat(np.sqrt(record['effective_masses_u']), 3)
    q = vectors.reshape(3*count, 3*count).T
    e = weight[:, None] * q
    e /= np.linalg.norm(e, axis=0)
    h = parse_hessian(payloads['hessian'], count)
    k = record['scale'] * h / weight[:, None] / weight[None, :]
    tolerance = 256 * np.finfo(float).eps * (3*count)
    # Within a cluster split only by serialization, bases may mix without
    # scientific distinction. Two eigenvalue uncertainty intervals can differ
    # by 2*delta_K. Exact bytes are still independently bound by binding.json.
    residual_bound = (tolerance * np.linalg.norm(k, 2) +
                      2*(3*count)*.5e-10*record['scale']/min(record['effective_masses_u']))
    if (not np.allclose(np.linalg.norm(q, axis=0), 1., rtol=0, atol=tolerance) or
            np.linalg.norm(e.T @ e - np.eye(3*count), 2) > tolerance or
            np.linalg.norm(k @ e - e * eigenvalues, 2) > residual_bound or
            not np.allclose(record['full_frequencies_cm1'],
                            np.sign(eigenvalues) * FREQUENCY_FACTOR * np.sqrt(np.abs(eigenvalues)),
                            rtol=tolerance, atol=tolerance)):
        raise ValueError('Stored modes do not represent the bound Hessian eigensystem')
    indices = np.asarray(record['internal_indices'], dtype=int) - 1
    geometry_raw = catalog.encode(dict(elements=record['elements'], coordinates=record['coordinates']))
    target = dict(kind='frequency', analysis=path.relative_to(root).as_posix(),
                  source=dict(sha256=sha256(raw).hexdigest(), source_sha256=record['source_sha256'],
                              geometry_sha256=sha256(payloads['geometry']).hexdigest(),
                              hessian_sha256=sha256(payloads['hessian']).hexdigest()))
    return dict(elements=record['elements'], coordinates=np.asarray(record['coordinates']),
                frequencies=np.asarray(record['full_frequencies_cm1'])[indices],
                displacements=np.asarray(record['full_displacements'])[indices],
                analysis=target['analysis'], target=target, status=record['status'],
                orientation='xTB same-stage g98 geometry; source frame', stationarity=record['stationarity'],
                geometry_sha256=sha256(geometry_raw).hexdigest(), source=target['source'],
                warnings=record['warnings'], convention=CONVENTION,
                spectrum_indices=record['internal_indices'])


def run(args):
    result = import_hessian(args.study, args.source, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


def register(subparsers):
    parser = subparsers.add_parser('import-xtb-hessian', description=__doc__)
    parser.add_argument('--study', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.set_defaults(func=run)
