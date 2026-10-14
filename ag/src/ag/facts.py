"""Local extraction of reported facts; scientific acceptance belongs to the reviewer."""

from hashlib import sha256
import json
from pathlib import Path
import sys
import tomllib


def resolve_attempt(value, study=None):
    path = Path(value).expanduser()
    if (path / 'manifest.json').is_file():
        return path.resolve()
    root = Path(study or '.').expanduser()
    if study and not root.is_dir():
        config = Path.home() / '.config' / 'ag' / 'config.toml'
        with config.open('rb') as stream:
            root = Path(tomllib.load(stream)['local']['studies_root']).expanduser() / study
    candidate = root / 'attempts' / value
    if not (candidate / 'manifest.json').is_file():
        raise ValueError(f'Attempt not found: {value}; supply its directory or --study')
    return candidate.resolve()


def gaussian_log(attempt_dir):
    """Select the input-matched log, never silently choose among unrelated logs."""
    attempt_dir = Path(attempt_dir)
    manifest = json.loads((attempt_dir / 'manifest.json').read_text())
    matched = [attempt_dir / 'outputs' / (Path(item['name']).stem + '.log')
               for item in manifest.get('inputs', [])
               if Path(item['name']).suffix.lower() in {'.gjf', '.com'}]
    matched = [p for p in matched if p.is_file()]
    logs = matched or list((attempt_dir / 'outputs').glob('*.log'))
    if len(logs) != 1:
        raise ValueError(f'{attempt_dir.name}: expected one Gaussian output log, found {len(logs)}')
    return logs[0]


def _write_geometry(path, geometry):
    """Reuse identical bytes, never replace a previously reviewed geometry."""
    content = geometry.encode('utf-8')
    try:
        with path.open('xb') as handle:
            handle.write(content)
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'{path.name} 必须是普通文件，不能是符号链接') from None
        if path.read_bytes() != content:
            raise ValueError(f'{path.name} 与当前日志解析结果不一致，需人工核对') from None


def build_facts(attempt_dir):
    """Regenerate facts, exporting available geometries without overwriting."""
    from ag._parse_outputs import parse_gaussian, parse_crest, parse_xtb, gaussian_orientation

    attempt_dir = Path(attempt_dir)
    manifest = json.loads((attempt_dir / 'manifest.json').read_text())
    program = manifest['template']
    outputs = attempt_dir / 'outputs'
    if program == 'gaussian':
        log = gaussian_log(attempt_dir)
        facts, geometry = parse_gaussian(log, outputs / ('job.slurm.err' if manifest.get('scheduler') == 'slurm' else 'job.pbs.out'))
        input_geometry = gaussian_orientation(log.read_text(errors='replace'), 'Input')
        facts['final_input_geometry'] = 'final_input.xyz' if input_geometry else None
        facts['final_input_geometry_orientation'] = 'input' if input_geometry else None
        if input_geometry:
            _write_geometry(attempt_dir / 'final_input.xyz', input_geometry)
        if 'irc' in facts:
            from ag._irc import parse_irc
            _, endpoint = parse_irc(log.read_text(errors='replace'))
            if endpoint:
                _write_geometry(attempt_dir / 'irc_end.xyz', endpoint)
                facts['irc']['end_geometry'] = 'irc_end.xyz'
    elif program == 'crest':
        if '--mdopt' in manifest.get('template_params', {}):
            from ag._parse_outputs import parse_crest_mdopt
            facts, geometry, ensemble = parse_crest_mdopt(outputs, manifest.get('science', {}).get('n_frames'))
            target = attempt_dir / 'mdopt.xyz'
            content = ensemble.encode('utf-8')
            # Never silently replace an ensemble already used for downstream selection.
            try:
                with target.open('xb') as handle:
                    handle.write(content)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes() != content:
                    raise ValueError('mdopt.xyz differs from current parsed output; manual review required') from None
            facts.update(ensemble_geometry='mdopt.xyz', ensemble_sha256=sha256(content).hexdigest())
        else:
            facts, geometry = parse_crest(outputs)
    elif program == 'xtb':
        facts, geometry = parse_xtb(outputs)
    else:
        raise ValueError(f'Unsupported template: {program}')
    definition = manifest.get('science', {}).get('scan')
    if definition:
        from ag._scan import parse_gaussian_scan, parse_xtb_scan
        if program == 'gaussian':
            scan, geometries = parse_gaussian_scan(log.read_text(errors='replace'), definition)
        elif program == 'xtb':
            scan_path = outputs / 'xtbscan.log'
            if not scan_path.is_file():
                raise ValueError('Missing xtbscan.log for declared scan')
            scan, geometries = parse_xtb_scan(scan_path, (outputs / 'xtb.out').read_text(errors='replace'), definition)
        else:
            raise ValueError('Unsupported scan program')
        if geometries:
            target = attempt_dir / 'scan_points.xyz'
            content = geometries.encode('utf-8')
            try:
                with target.open('xb') as handle:
                    handle.write(content)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes() != content:
                    raise ValueError('scan_points.xyz differs from current parsed output; manual review required') from None
            scan['geometries_sha256'] = sha256(content).hexdigest()
        facts['scan'] = scan
    facts = {'schema': 'ag-facts/1', 'program': program,
             'units': {'energy': 'Hartree', 'frequency': 'cm^-1', 'distance': 'angstrom',
                       'relative_energy': 'kcal/mol'},
             'n_atoms': None, 'charge': None, 'multiplicity': None, 'route': None,
             **facts, 'final_geometry': 'final.xyz' if geometry else None}
    if geometry:
        _write_geometry(attempt_dir / 'final.xyz', geometry)
    (attempt_dir / 'facts.json').write_text(json.dumps(facts, indent=2, ensure_ascii=False,
                                                     allow_nan=False) + '\n')
    return facts


def _run(args):
    try:
        facts = build_facts(resolve_attempt(args.attempt, args.study))
        print(json.dumps(facts, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except ImportError as exc:
        print(f'Chemistry dependency unavailable: {exc}', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser('facts', help='Extract local calculation facts')
    parser.add_argument('attempt', help='Attempt directory or attempt ID')
    parser.add_argument('--study', help='Study directory or configured study ID')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=_run)
