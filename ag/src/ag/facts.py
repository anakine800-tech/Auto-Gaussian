"""Local extraction of reported facts; scientific acceptance belongs to the reviewer."""

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


def build_facts(attempt_dir):
    """Read local outputs and regenerate facts.json and, when available, final.xyz."""
    from ag._parse_outputs import parse_gaussian, parse_crest, parse_xtb

    attempt_dir = Path(attempt_dir)
    manifest = json.loads((attempt_dir / 'manifest.json').read_text())
    program = manifest['template']
    outputs = attempt_dir / 'outputs'
    if program == 'gaussian':
        log = gaussian_log(attempt_dir)
        facts, geometry = parse_gaussian(log, outputs / 'job.pbs.out')
        if 'irc' in facts:
            from ag._irc import parse_irc
            _, endpoint = parse_irc(log.read_text(errors='replace'))
            if endpoint:
                # Exclusive creation prevents a later parse from replacing a
                # geometry that may already have been reviewed or optimized.
                with (attempt_dir / 'irc_end.xyz').open('x') as handle:
                    handle.write(endpoint)
                facts['irc']['end_geometry'] = 'irc_end.xyz'
    elif program == 'crest':
        facts, geometry = parse_crest(outputs)
    elif program == 'xtb':
        facts, geometry = parse_xtb(outputs)
    else:
        raise ValueError(f'Unsupported template: {program}')
    facts = {'schema': 'ag-facts/1', 'program': program,
             'units': {'energy': 'Hartree', 'frequency': 'cm^-1', 'distance': 'angstrom',
                       'relative_energy': 'kcal/mol'},
             'n_atoms': None, 'charge': None, 'multiplicity': None, 'route': None,
             **facts, 'final_geometry': 'final.xyz' if geometry else None}
    if geometry:
        (attempt_dir / 'final.xyz').write_text(geometry)
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
