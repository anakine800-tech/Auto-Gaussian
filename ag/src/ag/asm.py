"""Local distortion/interaction bookkeeping for explicitly assigned fragments."""

from collections import Counter
import json
import math
from pathlib import Path
import re

from ag import __version__, geometry as geo
from ag._parse_outputs import _route_has
from ag._profile_sources import finite, integer, nonempty, protocol, read_json, require
from ag.ensemble import _Evidence, _geometry
from ag.fragments import _write_outputs
from ag.study import identifier, local_path


NOTICE = '电子能，不含零点能和热校正；未做基组重叠误差校正；溶剂模型与复合物一致；只描述能量分解，不判断选择性来源。'
TOLERANCE = 1e-4  # Angstrom, per-atom Euclidean displacement without alignment.


def atoms(value, count):
    """Parse explicit 1-based indices; do not silently collapse duplicates."""
    nonempty(value, 'atoms')
    selected = set()
    for part in value.split(','):
        match = re.fullmatch(r'\s*([1-9][0-9]*)(?:\s*-\s*([1-9][0-9]*))?\s*', part)
        require(match is not None, 'atoms: expected comma-separated indices or ranges')
        first, last = int(match[1]), int(match[2] or match[1])
        require(1 <= first <= last <= count, 'atoms: range out of bounds or reversed')
        group = set(range(first, last + 1))
        require(not selected.intersection(group), 'atoms: duplicate index')
        selected.update(group)
    return sorted(selected)


def _path(root, value):
    path = Path(value).expanduser()
    return local_path(root, path if path.is_absolute() else root / path)


def _root(study, attempt=None):
    root = Path(study).expanduser().absolute() if study else Path.cwd()
    if not study and attempt and Path(attempt).is_absolute():
        root = Path(attempt).parent.parent
    return local_path(root, root)


def _attempt(root, value):
    nonempty(value, 'Attempt')
    if Path(value).is_absolute():
        path = local_path(root, value)
        require(path.parent == root / 'attempts', 'Attempt must belong to this study')
        identifier(path.name)
        return path
    return local_path(root, root / 'attempts' / identifier(value))


def _json(evidence, path):
    evidence.read(path)
    result = read_json(path)
    evidence.read(path)
    return result


def _xyz(evidence, path):
    evidence.read(path)
    frames = geo.read_xyz(path)
    evidence.read(path)
    require(len(frames) == 1, 'Expected exactly one geometry frame')
    return frames[0]


def _file(directory, value):
    nonempty(value, 'geometry filename')
    require(Path(value).name == value and value not in {'.', '..'}, 'Expected a plain geometry filename')
    return directory / value


def _output(root, value, suffix):
    path = local_path(root / 'analyses', _path(root, value))
    require(path.suffix == suffix, f'--out must be a new {suffix} file under analyses/')
    for target in (path, path.with_suffix('.md')) if suffix == '.json' else (path,):
        local_path(root, target)
        if target.exists():
            raise FileExistsError(f'Output already exists: {target.name}')
    return path


def split(attempt, *, geometry, atom_list, name, out, study=None):
    root = _root(study, attempt)
    directory = _attempt(root, attempt)
    target = _output(root, out, '.xyz')
    nonempty(name, 'fragment name')
    require(geometry in {'input', 'final'}, 'geometry must be input or final')
    evidence = _Evidence(root)
    if geometry == 'input':
        manifest = _json(evidence, directory / 'manifest.json')
        frame, _ = _geometry(evidence, directory, manifest)
    else:
        frame = _xyz(evidence, directory / 'final_input.xyz')
    selected = atoms(atom_list, len(frame.symbols))
    comment = (f'source={directory.name}; geometry={geometry}; '
               f'fragment={json.dumps(name, ensure_ascii=False)}; '
               f'original_atoms={",".join(map(str, selected))}')
    fragment = geo.Frame(tuple(frame.symbols[i - 1] for i in selected),
                         tuple(frame.coordinates[i - 1] for i in selected), comment)
    evidence.verify()
    _write_outputs(target.parent, {target.name: geo.xyz_text([fragment]).encode('utf-8')})
    return target.relative_to(root).as_posix()


def _energy_source(facts, geometry):
    """Bind the SCF field to its route/geometry, not merely the first route.

    This prevents mixing a later Link1 energy with an earlier optimized frame.
    Gaussian's internal Opt+Freq step is the known same-geometry continuation.
    """
    sections, sources = facts.get('job_sections'), facts.get('fact_sources')
    require(isinstance(sections, list) and sections and isinstance(sources, dict),
            'Missing energy/geometry section evidence; regenerate ag facts')
    energy_index = integer(sources.get('energies.scf'), 'energy source', positive=True)
    require(energy_index <= len(sections), 'Invalid energy source section')
    require(all(isinstance(s, dict) and s.get('index') == i and s.get('termination') == 'normal'
                for i, s in enumerate(sections, 1)), 'Invalid or non-normal job sections')
    section = sections[energy_index - 1]
    route = section.get('route')
    internal_freq = (energy_index == 2 and len(sections) == 2
                     and section.get('start_kind') == 'internal' and section.get('internal_step') == 2
                     and _route_has(sections[0].get('route'), 'opt')
                     and _route_has(sections[0].get('route'), 'freq')
                     and _route_has(route, 'freq')
                     and not any(_route_has(route, word) for word in ('opt', 'irc', 'scan')))
    parent_method = protocol(facts.get('route'), facts.get('multiplicity'))
    if internal_freq:
        # Gaussian-generated internal Freq uses SCRF=Check even for gas phase.
        # Inherit solvent only within this same-job continuation, never Link1.
        solvent = ('' if parent_method['solvent_model'] == 'none' else
                   f"SCRF=({parent_method['solvent_model']},Solvent={parent_method['solvent']})")
        route = re.sub(r'\bscrf\s*=\s*(?:check\b|\(\s*check\s*\))', solvent, route, flags=re.I)
    method = protocol(route, facts.get('multiplicity'))
    require(method == parent_method, 'Energy section protocol differs from facts route')
    if geometry == 'input':
        # An optimization's last SCF is not the energy of its submitted frame.
        require(len(sections) == 1 and not any(_route_has(route, word) for word in ('opt', 'irc', 'scan')),
                'Input geometry energy requires a single-point Attempt, not Opt/IRC/Scan')
    else:
        key = 'final_input_geometry' if geometry == 'final' else 'final_geometry'
        geometry_index = integer(sources.get(key), 'geometry source', positive=True)
        require(geometry_index <= len(sections), 'Invalid geometry source section')
        require(geometry_index == energy_index or (geometry_index == 1 and internal_freq),
                'Electronic energy does not belong to the final geometry section')
        require(not any(_route_has(route, word) for word in ('irc', 'scan')) and not facts.get('scan'),
                'IRC/scan energy is not a single final-geometry energy')
    return method


def _load_energy(evidence, value, geometry, context):
    try:
        directory = _attempt(evidence.root, value)
        facts_path = directory / 'facts.json'
        facts = _json(evidence, facts_path)
        require(facts.get('program') == 'gaussian' and facts.get('termination') == 'normal',
                'Expected normally terminated Gaussian facts')
        require(facts.get('units', {}).get('energy') == 'Hartree', 'Expected energy unit Hartree')
        energy = finite(facts.get('energies', {}).get('scf'), 'energies.scf')
        charge = integer(facts.get('charge'), 'charge')
        require(integer(facts.get('multiplicity'), 'multiplicity', positive=True) == 1,
                'Only singlets are supported; open-shell systems are unsupported')
        method = _energy_source(facts, geometry)
        version = nonempty(facts.get('program_version'), 'program version')
        if geometry == 'input':
            manifest = _json(evidence, directory / 'manifest.json')
            frame, science = _geometry(evidence, directory, manifest)
            require((science['charge'], science['multiplicity']) == (charge, 1),
                    'Input charge/multiplicity differs from facts')
            require(protocol(science['route'], science['multiplicity']) == method,
                    'Input protocol differs from energy protocol')
        else:
            key = 'final_input_geometry' if geometry == 'final' else 'final_geometry'
            name = facts.get(key)
            if geometry == 'final':
                require(name == 'final_input.xyz', 'Missing final_input.xyz in facts')
            frame = _xyz(evidence, _file(directory, name))
        require(integer(facts.get('n_atoms'), 'n_atoms', positive=True) == len(frame.symbols),
                'Geometry atom count differs from facts')
        return dict(attempt=directory.name, geometry=geometry, facts=evidence.reference(facts_path),
                    energy=_value(energy), elements=dict(Counter(frame.symbols)), charge=charge,
                    multiplicity=1, protocol=method, program_version=version), frame
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        raise ValueError(f'{context}: {detail}') from exc


def _value(energy):
    finite(energy, 'computed energy')
    return dict(hartree=energy, kcal_mol=energy * geo.HARTREE_TO_KCAL)


def _same_protocol(reference, other, context):
    require(reference['protocol'] == other['protocol'], f'{context}: method protocol mismatch')
    require(reference['program_version'] == other['program_version'], f'{context}: program version mismatch')


def _identity(row):
    return row['elements'], row['charge'], row['multiplicity']


def _system(spec, evidence):
    require(isinstance(spec, dict), 'system: expected an object')
    label = nonempty(spec.get('label'), 'system label')
    context = f'system {label}'
    geometry = spec.get('complex_geometry')
    require(isinstance(geometry, str) and geometry in {'input', 'final'},
            f'{context}: complex_geometry must be input or final')
    complex_row, frame = _load_energy(evidence, spec.get('complex_attempt'), geometry, context)
    fragments = spec.get('fragments')
    require(isinstance(fragments, list) and fragments, f'{context}: expected fragments')
    rows, covered, names = [], set(), set()
    for spec in fragments:
        require(isinstance(spec, dict), f'{context}: expected fragment object')
        name = nonempty(spec.get('name'), f'{context} fragment name')
        where = f'{context} / fragment {name}'
        require(name not in names, f'{where}: duplicate fragment name')
        names.add(name)
        try:
            selected = atoms(spec.get('atoms'), len(frame.symbols))
        except ValueError as exc:
            raise ValueError(f'{where}: {exc}') from exc
        require(not covered.intersection(selected), f'{where}: overlapping fragment atoms')
        covered.update(selected)
        row, fragment = _load_energy(evidence, spec.get('attempt'), 'input', where)
        _same_protocol(complex_row, row, where)
        require((integer(spec.get('charge'), f'{where} charge'),
                 integer(spec.get('multiplicity'), f'{where} multiplicity')) == (row['charge'], 1),
                f'{where}: declared charge/multiplicity differs from singlet facts')
        require(fragment.symbols == tuple(frame.symbols[i - 1] for i in selected)
                and all(math.dist(xyz, frame.coordinates[i - 1]) <= TOLERANCE
                        for xyz, i in zip(fragment.coordinates, selected)),
                f'{where}: fragment input geometry mismatch (tolerance 1e-4 angstrom)')
        reference = None
        distortion = None
        if 'reference_attempt' in spec:
            reference, _ = _load_energy(evidence, spec['reference_attempt'], 'reference', where + ' reference')
            _same_protocol(complex_row, reference, where + ' reference')
            require(_identity(row) == _identity(reference), f'{where}: reference identity mismatch')
            distortion = _value(row['energy']['hartree'] - reference['energy']['hartree'])
        rows.append(dict(name=name, original_atoms=selected, **row, reference=reference, E_dist=distortion))
    require(covered == set(range(1, len(frame.symbols) + 1)), f'{context}: fragments do not cover all atoms')
    require(sum(row['charge'] for row in rows) == complex_row['charge'], f'{context}: fragment charge sum mismatch')
    interaction = complex_row['energy']['hartree'] - math.fsum(row['energy']['hartree'] for row in rows)
    complete = all(row['E_dist'] is not None for row in rows)
    total = math.fsum(row['E_dist']['hartree'] for row in rows) if complete else None
    return dict(label=label, complex=complex_row, fragments=rows, E_int=_value(interaction),
                E_dist_total=_value(total) if complete else None,
                delta_E=_value(total + interaction) if complete else None)


def _comparison(spec, systems):
    require(isinstance(spec, dict), 'comparison: expected an object')
    a, b = spec.get('a'), spec.get('b')
    nonempty(a, 'comparison a')
    nonempty(b, 'comparison b')
    where = f'comparison {b} - {a}'
    require(a in systems and b in systems, f'{where}: unknown system')
    left, right = systems[a], systems[b]
    lf = {r['name']: r for r in left['fragments']}
    rf = {r['name']: r for r in right['fragments']}
    require(lf.keys() == rf.keys(), f'{where}: fragment names differ')
    rows = []
    for name, row in lf.items():
        require(_identity(row) == _identity(rf[name]), f'{where} / fragment {name}: identity mismatch')
        rows.append(dict(name=name, ddE_dist=_value(rf[name]['energy']['hartree'] - row['energy']['hartree'])))
    delta = right['complex']['energy']['hartree'] - left['complex']['energy']['hartree']
    interaction = right['E_int']['hartree'] - left['E_int']['hartree']
    residual = delta - math.fsum([interaction, *(row['ddE_dist']['hartree'] for row in rows)])
    require(abs(residual) < 1e-8, f'{where}: decomposition sum mismatch')
    return dict(a=a, b=b, direction='b - a', ddE_complex=_value(delta), ddE_int=_value(interaction),
                fragments=rows, sum_residual_hartree=residual)


def summary(definition, out, *, study=None):
    root = _root(study)
    definition = local_path(root / 'analyses', _path(root, definition))
    require(definition.suffix == '.json', 'Definition must be JSON under analyses/')
    target = _output(root, out, '.json')
    evidence = _Evidence(root)
    data = _json(evidence, definition)
    require(data.get('schema') == 'ag-asm-definition/1', 'Expected schema ag-asm-definition/1')
    require(isinstance(data.get('systems'), list) and data['systems'], 'Expected nonempty systems list')
    systems = {}
    for spec in data['systems']:
        row = _system(spec, evidence)
        require(row['label'] not in systems, f"system {row['label']}: duplicate label")
        if systems:
            _same_protocol(next(iter(systems.values()))['complex'], row['complex'], f"system {row['label']}")
        systems[row['label']] = row
    comparisons = data.get('comparisons', [])
    require(isinstance(comparisons, list), 'comparisons must be a list')
    result = dict(schema='ag-asm/1', ag_version=__version__, definition=evidence.reference(definition),
                  units=dict(energy='Hartree', converted_energy='kcal/mol', distance='angstrom'),
                  hartree_to_kcal_mol=geo.HARTREE_TO_KCAL, geometry_tolerance_angstrom=TOLERANCE,
                  systems=list(systems.values()), comparisons=[_comparison(c, systems) for c in comparisons],
                  sources=[evidence.reference(p) for p in sorted(evidence.saved)], notice=NOTICE)
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    evidence.verify()
    _write_outputs(target.parent, {target.name: content.encode('utf-8'),
                                   target.with_suffix('.md').name: markdown(result).encode('utf-8')})
    return result


def markdown(result):
    def cell(value):
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace(
            '|', '&#124;').replace('`', '&#96;').replace('\n', ' ').replace('\r', ' ')

    def table(rows):
        lines = ['| 项目 | Hartree | kcal/mol |', '| --- | ---: | ---: |']
        for name, value in rows:
            numbers = f"{value['hartree']:.12f} | {value['kcal_mol']:.8f}" if value is not None else '— | —'
            lines.append(f'| {cell(name)} | {numbers} |')
        return lines

    lines = ['# 畸变–相互作用分析', '', NOTICE, '',
             f"换算：1 Hartree = {result['hartree_to_kcal_mol']} kcal/mol。", '']
    for system in result['systems']:
        rows = [('E_complex', system['complex']['energy']), ('E_int', system['E_int'])]
        for fragment in system['fragments']:
            rows += [(fragment['name'] + ' E_frag@complex', fragment['energy']),
                     (fragment['name'] + ' E_frag,ref', (fragment['reference'] or {}).get('energy')),
                     (fragment['name'] + ' E_dist', fragment['E_dist'])]
        rows += [('E_dist_total', system['E_dist_total']), ('ΔE', system['delta_E'])]
        lines += [f"## {cell(system['label'])}", '', *table(rows), '']
    for comparison in result['comparisons']:
        rows = [('ΔΔE_complex', comparison['ddE_complex']), ('ΔΔE_int', comparison['ddE_int'])]
        rows += [(f"{r['name']} ΔΔE_dist", r['ddE_dist']) for r in comparison['fragments']]
        lines += [f"## {cell(comparison['b'])} − {cell(comparison['a'])}", '', *table(rows), '',
                  'ΔΔE_dist 直接比较片段在两个复合物几何下的电子能，不依赖弛豫参照。',
                  f"加和残差：{comparison['sum_residual_hartree']:.12g} Hartree。", '']
    lines += ['## 来源', '']
    lines += [f"- {cell(s['path'])}；SHA-256 {s['sha256']}" for s in result['sources']]
    return '\n'.join(lines) + '\n'


def run(args):
    if args.asm_command == 'split':
        print(split(args.attempt, geometry=args.geometry, atom_list=args.atoms,
                    name=args.name, out=args.out, study=args.study))
    else:
        print(markdown(summary(args.definition, args.out, study=args.study)), end='')
    return 0


def register(subparsers):
    parser = subparsers.add_parser('asm', description=__doc__)
    commands = parser.add_subparsers(dest='asm_command', required=True)
    splitting = commands.add_parser('split', help='Export explicitly selected atoms as XYZ')
    splitting.add_argument('attempt')
    splitting.add_argument('--geometry', choices=('input', 'final'), required=True)
    splitting.add_argument('--atoms', required=True)
    splitting.add_argument('--name', required=True)
    reporting = commands.add_parser('summary', help='Summarize existing electronic energies')
    reporting.add_argument('--definition', type=Path, required=True)
    for command in (splitting, reporting):
        command.add_argument('--out', type=Path, required=True)
        command.add_argument('--study', help='Study directory; defaults to current directory')
        command.set_defaults(func=run)
