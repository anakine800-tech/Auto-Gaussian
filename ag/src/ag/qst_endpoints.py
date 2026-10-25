"""Build a local QST2 draft from fetched minima and a human-supplied atom map."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import re

from ag import catalog, catalog_v2 as v2, gaussian_input, geometry as geo, study

# Comparison/report tolerance only, never a scientific acceptance threshold.
BETTER_RMSD_ANGSTROM = 0.01


def endpoint(root, identity):
    directory, (_, status, _) = catalog.record(root, identity)
    if status['state'] != 'fetched':
        raise ValueError(f'{identity}: endpoint must be fetched')
    facts = catalog.read_facts(root, directory)
    if facts.get('opt_converged') is not True:
        raise ValueError(f'{identity}: endpoint optimization is not converged')
    imaginary = facts.get('n_imag')
    if imaginary is not None and (type(imaginary) is not int or imaginary != 0):
        raise ValueError(f'{identity}: n_imag must be zero for an endpoint minimum')
    warnings = ([f'{identity}: n_imag unknown; minimum character requires human review']
                if imaginary is None else [])
    info, missing = v2.manifest_info(root, identity)
    for field in ('charge', 'multiplicity'):
        if field not in info:
            raise ValueError(f'{identity}: {field} unavailable: {missing.get(field, "missing")}')
    source = study.local_path(root, directory / 'final_input.xyz')
    if not source.exists():
        source = study.local_path(root, directory / 'final.xyz')
    raw = v2.read_bytes(source, 1024 * 1024)
    v2.xyz(raw)  # exactly one frame, canonical elements, finite coordinates
    rows = raw.decode('utf-8').splitlines()[2:]
    frame = geo.Frame(tuple(row.split()[0] for row in rows),
                      tuple(tuple(float(x) for x in row.split()[1:]) for row in rows))
    gaussian_input.check_electrons(frame.symbols, info['charge'], info['multiplicity'], location=identity)
    provenance = dict(attempt=identity, geometry_file=source.name, geometry_sha256=sha256(raw).hexdigest())
    return frame, info, provenance, warnings


def mapping(raw, reactant, product):
    """Validate a complete product -> reactant bijection; never infer one."""
    count = len(reactant.symbols)
    if len(product.symbols) != count:
        raise ValueError('Endpoint atom counts differ')
    value = json.loads(raw)
    pairs = value.get('product_to_reactant') if isinstance(value, dict) else None
    if not isinstance(pairs, list) or len(pairs) != count:
        raise ValueError('product_to_reactant must cover every atom exactly once')
    order, seen = [None] * count, set()
    for pair in pairs:
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(type(i) is not int or not 1 <= i <= count for i in pair)):
            raise ValueError('Mapping requires pairs of 1-based integer atom indices')
        source, target = pair
        if source in seen or order[target - 1] is not None:
            raise ValueError('Mapping contains duplicate product or reactant atoms')
        if product.symbols[source - 1] != reactant.symbols[target - 1]:
            raise ValueError(f'Mapping elements differ: product {source} -> reactant {target}')
        seen.add(source)
        order[target - 1] = source - 1
    return replace(product, symbols=tuple(product.symbols[i] for i in order),
                   coordinates=tuple(product.coordinates[i] for i in order))


def align_indices(value, count):
    if value is None:
        return list(range(count))
    selected = []
    for token in value.split(','):
        match = re.fullmatch(r'\s*([1-9]\d*)(?:-([1-9]\d*))?\s*', token)
        if not match:
            raise ValueError('--align-atoms requires 1-based indices/ranges, e.g. 1-3,5')
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise ValueError('--align-atoms outside endpoint atom range or reversed')
        for index in range(first - 1, last):
            if index in selected:
                raise ValueError('--align-atoms contains duplicate indices')
            selected.append(index)
    return selected


def equivalent_maps(frame, charge, side):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds
    from ag.irc_compare import _pairs

    # A questionable edge could invent/remove equivalence. Reuse the existing
    # connectivity uncertainty band instead of guessing a molecular graph.
    uncertain = [list(pair) for pair, row in _pairs(frame, Chem).items() if row['state'] == 'uncertain']
    if uncertain:
        raise ValueError(f'{side}: uncertain bonding at atom pairs {uncertain}; review endpoint geometry')
    try:
        mol = geo.infer_molecule(frame, charge, Chem, rdDetermineBonds)
    except Exception as exc:
        raise ValueError(f'{side}: molecular graph inference failed ({type(exc).__name__}); no graph guessed') from exc
    try:
        return geo.rms_atom_maps(mol, mol, Chem)
    except ValueError as exc:
        raise ValueError(f'{side}: equivalent mappings could not be enumerated within '
                         f'RMS_MAX_MAPPINGS={geo.RMS_MAX_MAPPINGS}; human review must narrow the '
                         'problem scope; --align-atoms does not limit graph enumeration; no truncation') from exc


def align_endpoints(reactant, product, charge, indices):
    import numpy as np

    left, right = (np.asarray(frame.coordinates, dtype=float) for frame in (reactant, product))
    rotation, rmsd = geo.kabsch(right[indices], left[indices])
    try:
        with np.errstate(over='raise', invalid='raise'):
            aligned = (right - right[indices].mean(axis=0)) @ rotation + left[indices].mean(axis=0)
            displacement = np.linalg.norm(aligned - left, axis=1)
            all_rmsd = float(np.sqrt(np.mean(displacement ** 2)))
    except FloatingPointError as exc:
        raise ValueError('Endpoint coordinates cannot be aligned numerically') from exc
    checked, better = {}, []
    for side, frame in (('reactant', reactant), ('product', product)):
        checked[side] = 0
        for atom_map in equivalent_maps(frame, charge, side):
            if all(i == j for i, j in atom_map):
                continue
            checked[side] += 1
            permutation = [j for _, j in atom_map]
            changed_left = left[permutation] if side == 'reactant' else left
            changed_right = right[permutation] if side == 'product' else right
            _, alternative = geo.kabsch(changed_right[indices], changed_left[indices])
            if rmsd - alternative > BETTER_RMSD_ANGSTROM:
                better.append(dict(endpoint=side, atom_pairs=[[i + 1, j + 1] for i, j in atom_map if i != j],
                                   rmsd_angstrom=alternative))
    largest = sorted(range(len(left)), key=lambda i: (-displacement[i], i))[:10]
    report = dict(align_rmsd=rmsd, all_atoms_rmsd=all_rmsd,
                  rotation=rotation.tolist(), rotation_determinant=float(np.linalg.det(rotation)),
                  largest_displacements=[dict(atom_index=i + 1, element=reactant.symbols[i],
                                              displacement_angstrom=float(displacement[i])) for i in largest],
                  checked_equivalent_mappings=checked, better_swaps=better,
                  comparison_tolerance_angstrom=BETTER_RMSD_ANGSTROM)
    return replace(product, coordinates=tuple(tuple(float(x) for x in row) for row in aligned)), report


def route_check(route):
    if gaussian_input._qst_mode(route) != 'QST2':
        raise ValueError('Endpoint draft route requires Opt=QST2 and forbids QST3')
    # Reuse T133 G2 exactly: its TS-specific check receives a validation-only
    # copy with the QST2 optimization option replaced. Render the original.
    gaussian_input.ts_route_check(re.sub(r'\bqst2\b', 'TS', route, flags=re.I))


def register_candidate(root, args, raw, transform):
    # T133 exposes the unchanged T131 transaction for generated byte snapshots.
    return catalog.register_candidate(root, object=args.object, id=args.candidate_id,
                                      xyz_bytes=raw, source='qst2_endpoints:aligned_product',
                                      origin='qst', parent_attempt=args.reactant, transform=transform,
                                      target_channel=args.target_channel,
                                      upgrade_catalog=args.upgrade_catalog, dry_run=args.dry_run)


def output(report, as_json):
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
        return
    if report.get('error'):
        print(report['error'])
    for side in ('reactant', 'product'):
        source = report[side]
        print(f"{side}: {source['attempt']} / {source['geometry_file']} SHA-256 {source['geometry_sha256']}")
    print('Mapping SHA-256: ' + report['mapping_sha256'])
    print(f"Alignment RMSD: {report['align_rmsd']:.8f} Å; all atoms: {report['all_atoms_rmsd']:.8f} Å")
    print('Checked nonidentity equivalent mappings: ' + str(report['checked_equivalent_mappings']))
    for row in report['largest_displacements']:
        print(f"atom {row['atom_index']} {row['element']}: {row['displacement_angstrom']:.8f} Å")
    for swap in report['better_swaps']:
        print(f"{swap['endpoint']} equivalent permutation {swap['atom_pairs']}: {swap['rmsd_angstrom']:.8f} Å")
    if report['keep_mapping_reason'] is not None:
        print('Keep mapping reason: ' + report['keep_mapping_reason'])
    for warning in report['warnings']:
        print('Warning: ' + warning)
    if 'gaussian_qst2' in report:
        print('QST2 draft: ' + report['gaussian_qst2']['path'] + ' SHA-256 ' + report['gaussian_qst2']['sha256'])
    if 'candidate' in report:
        print(json.dumps(report['candidate'], ensure_ascii=False))


def run(args):
    if args.out.exists() or args.out.is_symlink():
        raise FileExistsError(f'Output already exists: {args.out}')
    if ((args.keep_mapping and not (args.reason and args.reason.strip())) or
            (not args.keep_mapping and args.reason is not None)):
        raise ValueError('--keep-mapping and a nonempty --reason must be supplied together')
    if not args.register_candidate and any((args.object, args.candidate_id, args.target_channel, args.upgrade_catalog)):
        raise ValueError('Candidate options require --register-candidate')
    if args.register_candidate and not (args.object and args.candidate_id):
        raise ValueError('--register-candidate requires --object and --candidate-id')
    route_check(args.route)
    root = catalog.resolve_study(args.study)
    reactant, r_info, r_source, r_warnings = endpoint(root, args.reactant)
    product, p_info, p_source, p_warnings = endpoint(root, args.product)
    if any(r_info[key] != p_info[key] for key in ('charge', 'multiplicity')):
        raise ValueError('Endpoint charge or multiplicity differs')
    raw_mapping = v2.read_bytes(args.mapping, 1024 * 1024)
    product = mapping(raw_mapping, reactant, product)
    indices = align_indices(args.align_atoms, len(reactant.symbols))
    product, report = align_endpoints(reactant, product, r_info['charge'], indices)
    report.update(reactant=r_source, product=p_source, mapping_sha256=sha256(raw_mapping).hexdigest(),
                  align_atoms=[i + 1 for i in indices] if args.align_atoms is not None else 'all',
                  keep_mapping_reason=args.reason if args.keep_mapping else None,
                  skipped_better_swaps=report['better_swaps'] if args.keep_mapping else [],
                  warnings=r_warnings + p_warnings)
    if report['better_swaps'] and not args.keep_mapping:
        report['error'] = ('Equivalent permutations lower RMSD by more than 0.01 Å; review the mapping or '
                           'use --keep-mapping --reason. No draft written; this is not a scientific criterion.')
        output(report, args.json)
        return 1
    titles = [args.title_reactant if args.title_reactant is not None else f'QST2 reactant {args.reactant}',
              args.title_product if args.title_product is not None else f'QST2 product {args.product}']
    text = gaussian_input.render_input(args.route, titles,
        [(r_info['charge'], r_info['multiplicity'], f.symbols, f.coordinates) for f in (reactant, product)])
    # Link0 is validation-only; the saved draft leaves resource choice to prepare.
    gaussian_input.validate('%nprocshared=1\n%mem=1GB\n' + text, 1, 2)
    raw = text.encode('utf-8')
    with args.out.open('xb') as handle:
        handle.write(raw)
    report['gaussian_qst2'] = dict(path=str(args.out), sha256=sha256(raw).hexdigest(), route=args.route,
                                 titles=titles, charge=r_info['charge'], multiplicity=r_info['multiplicity'])
    if args.register_candidate:
        transform = dict(type='qst2_endpoints', reactant=r_source, product=p_source,
                         **{key: report[key] for key in ('mapping_sha256', 'align_atoms', 'align_rmsd',
                                                        'skipped_better_swaps', 'keep_mapping_reason')})
        try:
            report['candidate'] = register_candidate(root, args, geo.xyz_text([product]).encode('utf-8'), transform)
        except (ValueError, OSError, KeyError) as exc:
            report['error'] = f'Candidate registration failed; QST2 draft retained: {exc}'
            output(report, args.json)
            return 1
    output(report, args.json)
    return 0


def register(subparsers):
    parser = subparsers.add_parser('qst-endpoints', description=__doc__)
    parser.add_argument('study', help='Study directory or configured ID')
    for option in ('reactant', 'product', 'route'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New Gaussian draft; no Link0 or overwrite')
    parser.add_argument('--align-atoms', help='Reactant atom indices/ranges, e.g. 1-3,5; default all')
    parser.add_argument('--keep-mapping', action='store_true')
    parser.add_argument('--reason')
    parser.add_argument('--title-reactant')
    parser.add_argument('--title-product')
    parser.add_argument('--register-candidate', action='store_true')
    parser.add_argument('--object')
    parser.add_argument('--candidate-id')
    parser.add_argument('--target-channel')
    parser.add_argument('--upgrade-catalog', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Preview registration; still write the draft')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
