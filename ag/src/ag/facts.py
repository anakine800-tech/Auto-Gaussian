"""Local extraction of reported facts; scientific acceptance belongs to the reviewer."""

from hashlib import sha256
import difflib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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


def parse_facts(attempt_dir):
    """Return facts and named geometry text in memory; never write evidence."""
    from ag._parse_outputs import parse_gaussian, parse_crest, parse_xtb, gaussian_orientation

    attempt_dir = Path(attempt_dir)
    manifest = json.loads((attempt_dir / 'manifest.json').read_text())
    program = manifest['template']
    outputs = attempt_dir / 'outputs'
    geometries = {}
    if program == 'gaussian':
        log = gaussian_log(attempt_dir)
        facts, geometry = parse_gaussian(log, outputs / ('job.slurm.err' if manifest.get('scheduler') == 'slurm' else 'job.pbs.out'))
        input_geometry = gaussian_orientation(log.read_text(errors='replace'), 'Input')
        facts['final_input_geometry'] = 'final_input.xyz' if input_geometry else None
        facts['final_input_geometry_orientation'] = 'input' if input_geometry else None
        if input_geometry:
            geometries['final_input.xyz'] = input_geometry
        if 'irc' in facts:
            from ag._irc import parse_irc
            _, endpoint = parse_irc(log.read_text(errors='replace'))
            if endpoint:
                geometries['irc_end.xyz'] = endpoint
                facts['irc']['end_geometry'] = 'irc_end.xyz'
    elif program == 'crest':
        if '--mdopt' in manifest.get('template_params', {}):
            from ag._parse_outputs import parse_crest_mdopt
            facts, geometry, ensemble = parse_crest_mdopt(outputs, manifest.get('science', {}).get('n_frames'))
            content = ensemble.encode('utf-8')
            geometries['mdopt.xyz'] = ensemble
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
            scan, scan_geometry = parse_gaussian_scan(log.read_text(errors='replace'), definition)
        elif program == 'xtb':
            scan_path = outputs / 'xtbscan.log'
            if not scan_path.is_file():
                raise ValueError('Missing xtbscan.log for declared scan')
            scan, scan_geometry = parse_xtb_scan(scan_path, (outputs / 'xtb.out').read_text(errors='replace'), definition)
        else:
            raise ValueError('Unsupported scan program')
        if scan_geometry:
            geometries['scan_points.xyz'] = scan_geometry
            content = scan_geometry.encode('utf-8')
            scan['geometries_sha256'] = sha256(content).hexdigest()
        facts['scan'] = scan
    facts = {'schema': 'ag-facts/1', 'program': program,
             'units': {'energy': 'Hartree', 'frequency': 'cm^-1', 'distance': 'angstrom',
                       'relative_energy': 'kcal/mol'},
             'n_atoms': None, 'charge': None, 'multiplicity': None, 'route': None,
             **facts, 'final_geometry': 'final.xyz' if geometry else None}
    if geometry:
        geometries['final.xyz'] = geometry
    return facts, geometries


def ag_provenance():
    """Identify the parser checkout, never the separately deployed Skills repo."""
    root = Path(__file__).resolve().parents[3]
    try:
        def git(*args):
            return subprocess.run(['git', '-C', str(root), *args], check=True,
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('Not an ag checkout')
        commit = git('rev-parse', 'HEAD')
        dirty = bool(git('status', '--porcelain', '--untracked-files=normal', '--',
                         'ag/src', 'ag/pyproject.toml'))
        return dict(git_commit=commit, dirty=dirty)
    except (OSError, ValueError, subprocess.SubprocessError):
        return dict(git_commit=None, dirty=None)


def _existing_bytes(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f'{path.name} 必须是普通文件，不能是符号链接')
    return path.read_bytes() if path.exists() else None


def build_facts(attempt_dir, *, refresh=False):
    """The ag facts write entry point; preserve exact old bytes before refresh."""
    directory = Path(attempt_dir)
    facts, geometries = parse_facts(directory)
    facts['ag_provenance'] = ag_provenance()
    content = (json.dumps(facts, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    target = directory / 'facts.json'
    # Serialize two CLI writers so neither can replace an unarchived version.
    fd = os.open(directory / '.facts.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = _existing_bytes(target)
        if old is not None and old != content and not refresh:
            diff = ''.join(difflib.unified_diff(
                old.decode('utf-8', errors='replace').splitlines(keepends=True),
                content.decode('utf-8').splitlines(keepends=True),
                fromfile='facts.json (existing)', tofile='facts.json (parsed)'))
            raise ValueError('facts.json 内容不同，拒绝写入；人工确认差异后使用 --refresh。\n'
                             f'旧 SHA-256: {sha256(old).hexdigest()}\n'
                             f'新 SHA-256: {sha256(content).hexdigest()}\n' + diff)
        # Validate all existing geometries before creating any new evidence.
        for name, geometry in geometries.items():
            existing = _existing_bytes(directory / name)
            if existing is not None and existing != geometry.encode('utf-8'):
                if name in {'mdopt.xyz', 'scan_points.xyz'}:
                    raise ValueError(f'{name} differs from current parsed output; manual review required')
                raise ValueError(f'{name} 与当前日志解析结果不一致，需人工核对')
        for name, geometry in geometries.items():
            _write_geometry(directory / name, geometry)
        if old == content:
            return facts  # Keep the mtime and the review fingerprint unchanged.
        if old is None:
            with target.open('xb') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            return facts
        archive = directory / f'facts.{sha256(old).hexdigest()[:12]}.json'
        archived = _existing_bytes(archive)
        if archived is None:
            with archive.open('xb') as handle:
                handle.write(old)
                handle.flush()
                os.fsync(handle.fileno())
        elif archived != old:
            raise ValueError(f'{archive.name} 内容不匹配，拒绝覆盖旧版')
        # Make the backup durable before atomically publishing the new facts.
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
            fd, temporary = tempfile.mkstemp(prefix='.facts-', dir=directory)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                if _existing_bytes(target) != old:
                    raise ValueError('facts.json 在刷新期间已变化，拒绝写入')
                os.replace(temporary, target)
                os.fsync(directory_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)  # Only an unpublished temporary, never an old version.
        finally:
            os.close(directory_fd)
    return facts


def _run(args):
    try:
        facts = build_facts(resolve_attempt(args.attempt, args.study), refresh=args.refresh)
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
    parser.add_argument('--refresh', action='store_true',
                        help='After human review, archive old facts by SHA-256 and write the new version')
    parser.set_defaults(func=_run)
