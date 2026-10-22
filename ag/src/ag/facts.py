"""Local extraction of reported facts; scientific acceptance belongs to the reviewer."""

from hashlib import sha256
from datetime import datetime, timezone
import difflib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import tomllib


def resolve_attempt(value, study=None, *, strict=False):
    def resolved(path):
        if strict:
            from ag.study import local_path
            return local_path(path.parent.parent, path)
        return path.resolve()

    path = Path(value).expanduser()
    if (path / 'manifest.json').is_file():
        return resolved(path)
    root = Path(study or '.').expanduser()
    if study and not root.is_dir():
        config = Path.home() / '.config' / 'ag' / 'config.toml'
        with config.open('rb') as stream:
            root = Path(tomllib.load(stream)['local']['studies_root']).expanduser() / study
    candidate = root / 'attempts' / value
    if not (candidate / 'manifest.json').is_file():
        raise ValueError(f'Attempt not found: {value}; supply its directory or --study')
    return resolved(candidate)


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



def parse_counterpoise(log):
    """Strict two-fragment gas SP reader; never use the last fragment SCF as E_AB.

    Summary labels follow the Gaussian Counterpoise manual (CONFLEX mirror).
    DCBS/MCBS markers are independently observable in cclib-data's Gaussian03
    H2FAs--AsH2F.opt-mp2-cp.log; that correlated/Opt file is NOT supported here.
    G16 A.03 gas-SP live fixtures still have to validate this narrow reader.
    """
    from ag._parse_outputs import (NUMBER, number, gaussian_job_sections,
                                   gaussian_orientation, gaussian_version, termination,
                                   HARTREE_TO_KCAL)
    from ag.gaussian_input import counterpoise_route
    from ag._profile_sources import require, normalized_method
    raw = log.read_bytes()
    text = raw.decode('utf-8', errors='replace')
    lines = text.splitlines()
    source = dict(path='outputs/' + log.name, sha256=sha256(raw).hexdigest())
    status = termination(text, 'Normal termination of Gaussian')
    if status['termination'] != 'normal':
        refusal = [i for i, line in enumerate(lines, 1)
                   if line.strip() == 'No SCRF with counterpoise/fragments.']
        return dict(**status, **gaussian_version(text), counterpoise=None,
                    counterpoise_unavailable='SCRF incompatible with counterpoise/fragments' if refusal
                    else 'CP job did not terminate normally',
                    counterpoise_error_sources=[dict(**source, line=i) for i in refusal]), None, None
    sections, warnings = gaussian_job_sections(text)
    require(len(sections) == 1 and sections[0]['termination'] == 'normal' and not warnings,
            'Counterpoise requires one normally terminated SP section; unknown output format')
    method = counterpoise_route(sections[0]['route'] or '')
    markers = []
    for i, line in enumerate(lines):
        if re.match(r'\s*Counterpoise:\s*doing\b', line):
            match = re.fullmatch(r'\s*Counterpoise: doing (DCBS|MCBS) calculation for fragment\s+([12])(?: NewBq=T)?\s*', line)
            require(match is not None, f'Unknown Counterpoise fragment format at line {i + 1}')
            markers.append((i, match[1], int(match[2])))
    require(len(markers) == 4 and {(basis, frag) for _, basis, frag in markers}
            == {(basis, frag) for basis in ('DCBS', 'MCBS') for frag in (1, 2)},
            'Expected exactly one DCBS and MCBS calculation per fragment; unknown CP format')
    starts = [i for i, line in enumerate(lines) if re.match(r'\s*Counterpoise corrected energy\s*=', line)]
    require(len(starts) == 1 and starts[0] > markers[-1][0],
            'Expected one G16 Counterpoise summary after fragment calculations; unknown CP format')
    start = starts[0]
    specs = [('corrected_energy', r'Counterpoise corrected energy', 'Hartree', ''),
             ('bsse', r'BSSE energy', 'Hartree', ''),
             ('sum_fragments', r'sum of fragments', 'Hartree', ''),
             ('interaction_raw_printed', r'complexation energy', 'kcal/mol', r'\s+kcal/mole \(raw\)'),
             ('interaction_corrected_printed', r'complexation energy', 'kcal/mol', r'\s+kcal/mole \(corrected\)')]
    values = {}
    for offset, (key, label, unit, suffix) in enumerate(specs):
        i = start + offset
        match = re.fullmatch(r'\s*' + label + r'\s*=\s*(' + NUMBER + ')' + suffix + r'\s*',
                            lines[i] if i < len(lines) else '')
        require(match is not None, f'Unknown/truncated Counterpoise summary at line {i + 1}')
        values[key] = dict(value=number(match[1]), unit=unit, source=dict(**source, line=i + 1))

    def scf(first, last):
        matches = [(i, re.fullmatch(r'\s*SCF Done:\s+E\(([^)]+)\)\s*=\s*(' + NUMBER
                                    + r')\s+A\.U\. after\s+\d+\s+cycles\s*', lines[i]))
                   for i in range(first, last) if re.match(r'\s*SCF Done:', lines[i])]
        require(len(matches) == 1 and matches[0][1] is not None,
                f'Expected one unambiguous SCF energy between lines {first + 1} and {last}')
        i, match = matches[0]
        require(normalized_method(match[1], 1) == method['method'], 'CP SCF method differs from route')
        return dict(value=number(match[2]), unit='Hartree', source=dict(**source, line=i + 1))

    values['uncorrected_energy'] = scf(0, markers[0][0])
    fragments = {i: dict(index=i) for i in (1, 2)}
    for position, (first, basis, fragment) in enumerate(markers):
        last = markers[position + 1][0] if position + 1 < len(markers) else start
        fragments[fragment][basis.lower()] = scf(first + 1, last)
        fragments[fragment][basis.lower()]['calculation_source'] = dict(**source, line=first + 1)
    # Reject mismatched/truncated fragment groups instead of reporting plausible
    # numbers taken from different cycles. SCF print precision bounds tolerance.
    own = sum(fragment['mcbs']['value'] for fragment in fragments.values())
    ghost = sum(fragment['dcbs']['value'] for fragment in fragments.values())
    raw_energy = values['uncorrected_energy']['value']
    correction = values['bsse']['value']
    corrected = values['corrected_energy']['value']
    require(abs(corrected - raw_energy - correction) <= 1e-8
            and abs(own - values['sum_fragments']['value']) <= 1e-8
            and abs(own - ghost - correction) <= 1e-8,
            'Counterpoise summary/fragment energy sums disagree')
    require(abs((raw_energy - own) * HARTREE_TO_KCAL - values['interaction_raw_printed']['value']) <= .011
            and abs((corrected - own) * HARTREE_TO_KCAL - values['interaction_corrected_printed']['value']) <= .011,
            'Counterpoise printed interaction energies disagree with Hartree values')
    whole = '\n'.join(lines[:markers[0][0]])
    states = re.findall(r'(?m)^\s*Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)(?: in supermolecule)?[ \t]*$', whole)
    require(len(states) == 1 and int(states[0][1]) == 1, 'Missing/ambiguous whole-complex charge/multiplicity')
    fragment_states = [(i, re.fullmatch(r'\s*Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+) in fragment\s+([12])\.\s*', line))
                       for i, line in enumerate(whole.splitlines(), 1) if ' in fragment ' in line and 'Charge' in line]
    require(len(fragment_states) == 2 and all(match is not None for _, match in fragment_states)
            and {int(match[3]) for _, match in fragment_states} == {1, 2},
            'Missing/ambiguous printed CP fragment states')
    for i, match in fragment_states:
        require(int(match[2]) == 1, 'Only singlet CP fragment output is supported')
        fragments[int(match[3])].update(charge=int(match[1]), multiplicity=int(match[2]),
                                      state_source=dict(**source, line=i))
    input_geometry = gaussian_orientation(whole, 'Input')
    geometry = gaussian_orientation(whole, 'Standard') or input_geometry
    require(geometry is not None, 'Missing whole-complex orientation before CP fragments')
    geometry_kind = 'standard' if gaussian_orientation(whole, 'Standard') else 'input'
    result = dict(termination='normal', error_hint=None, **gaussian_version(text),
                  route=sections[0]['route'], n_atoms=int(geometry.splitlines()[0]),
                  charge=int(states[0][0]), multiplicity=1, energies={'scf': raw_energy},
                  counterpoise={**values, 'fragments': list(fragments.values()), 'protocol': method},
                  job_sections=sections, fact_sources={'route': 1, 'energies.scf': 1, 'final_geometry': 1,
                                                      'final_input_geometry': 1 if input_geometry else None},
                  final_geometry_orientation=geometry_kind,
                  final_input_geometry='final_input.xyz' if input_geometry else None,
                  final_input_geometry_orientation='input' if input_geometry else None,
                  parser={'rules': 'counterpoise-two-fragment-sp-v1'}, parser_warning=None)
    return result, geometry, input_geometry


def parse_facts(attempt_dir):
    """Return facts and named geometry text in memory; never write evidence."""
    from ag._parse_outputs import (parse_gaussian, parse_crest, parse_xtb,
                                   gaussian_orientation, gaussian_section_text)

    attempt_dir = Path(attempt_dir)
    manifest = json.loads((attempt_dir / 'manifest.json').read_text())
    program = manifest['template']
    outputs = attempt_dir / 'outputs'
    geometries = {}
    from ag.fetch import incomplete_record
    incomplete = incomplete_record(attempt_dir)
    if incomplete:
        from ag.remote import output_names
        primary = output_names(manifest)[0]
        if primary in incomplete[1]['missing']:
            # No program log means no geometry/energy to infer. Still expose the
            # verified collection sources and scheduler error as incomplete facts.
            from ag._parse_outputs import annotate_fetch_sources
            result = dict(schema='ag-facts/1', program=program, termination='incomplete',
                          error_hint=None, n_atoms=None, charge=None, multiplicity=None,
                          route=None, opt_converged=None, final_geometry=None,
                          final_input_geometry=None, parser_warning=f'{primary} confirmed missing')
            annotate_fetch_sources(result, attempt_dir)
            return result, geometries
    if program == 'gaussian-cp':
        facts, geometry, input_geometry = parse_counterpoise(gaussian_log(attempt_dir))
        if input_geometry:
            geometries['final_input.xyz'] = input_geometry
    elif program == 'gaussian':
        log = gaussian_log(attempt_dir)
        facts, geometry = parse_gaussian(log, outputs / ('job.slurm.err' if manifest.get('scheduler') == 'slurm' else 'job.pbs.out'))
        text = log.read_text(errors='replace')
        geometry_section = facts['fact_sources']['final_geometry']
        input_geometry = gaussian_orientation(gaussian_section_text(
            text, facts['job_sections'][geometry_section - 1]), 'Input') if geometry_section else None
        facts['fact_sources']['final_input_geometry'] = geometry_section
        facts['fact_sources']['final_input_geometry_orientation'] = geometry_section
        facts['final_input_geometry'] = 'final_input.xyz' if input_geometry else None
        facts['final_input_geometry_orientation'] = 'input' if input_geometry else None
        if input_geometry:
            geometries['final_input.xyz'] = input_geometry
        if 'irc' in facts:
            from ag._irc import parse_irc
            _, endpoint = parse_irc(gaussian_section_text(
                text, facts['job_sections'][facts['fact_sources']['irc'] - 1]))
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
        facts, geometry = parse_xtb(outputs, 'job.slurm.err' if manifest.get('scheduler') == 'slurm' else 'job.pbs.out')
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
    if program != 'gaussian':
        from ag._parse_outputs import annotate_fetch_sources
        annotate_fetch_sources(facts, attempt_dir)
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


def _difference_summary(previous, current):
    """Classify refused evidence changes without replacing the full byte diff.

    Report newly added/deleted subtrees once; recurse through shared objects so
    energy and convergence changes are visible. Arrays remain one value path.
    Use the same JSON type-sensitive comparison and root provenance exclusion
    as build_facts, rather than Python equality (where True == 1).
    """
    if not isinstance(previous, dict):
        return '差异分类：旧 facts 不是有效的 JSON 对象，无法分类；请核对完整 diff。\n'
    old = {key: value for key, value in previous.items() if key != 'ag_provenance'}
    new = {key: value for key, value in current.items() if key != 'ag_provenance'}
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    try:
        canonical(old)
    except ValueError:
        return '差异分类：旧 facts 含无效 JSON 数值，无法分类；请核对完整 diff。\n'
    added, removed, changed = [], [], []

    def compare(before, after, prefix=''):
        for key in sorted(before.keys() | after.keys()):
            path = f'{prefix}.{key}' if prefix else key
            if key not in before:
                added.append(path)
            elif key not in after:
                removed.append(path)
            elif isinstance(before[key], dict) and isinstance(after[key], dict):
                compare(before[key], after[key], path)
            elif canonical(before[key]) != canonical(after[key]):
                changed.append(path)

    compare(old, new)
    conclusion = ('只有新增字段，既有值未变' if added and not removed and not changed else
                  '既有值发生变化' if changed else '存在删除字段，既有值未变')
    return ('差异分类（不含 ag_provenance）：' + conclusion + '。\n'
            + '新增的键：' + (', '.join(added) or '无') + '\n'
            + '删除的键：' + (', '.join(removed) or '无') + '\n'
            + '既有值变化的键：' + (', '.join(changed) or '无') + '\n')


class FactsConflictError(ValueError):
    """Parsed facts differ from existing evidence and require explicit refresh."""


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
        previous = None
        same = False
        if old is not None:
            try:
                previous = json.loads(old)
                if isinstance(previous, dict):
                    # A code upgrade alone must not invalidate signed evidence.
                    # Canonical JSON preserves number/bool types while ignoring
                    # formatting, key order and parser provenance metadata.
                    canonical = lambda value: json.dumps(
                        {key: item for key, item in value.items() if key != 'ag_provenance'},
                        sort_keys=True, ensure_ascii=False, allow_nan=False)
                    same = canonical(previous) == canonical(facts)
            except (ValueError, UnicodeDecodeError):
                pass  # Invalid old bytes still require explicit, archived refresh.
        if old is not None and not same and not refresh:
            diff = ''.join(difflib.unified_diff(
                old.decode('utf-8', errors='replace').splitlines(keepends=True),
                content.decode('utf-8').splitlines(keepends=True),
                fromfile='facts.json (existing)', tofile='facts.json (parsed)'))
            raise FactsConflictError(_difference_summary(previous, facts)
                             + 'facts.json 内容不同，拒绝写入；人工确认差异后使用 --refresh。\n'
                             + f'旧 SHA-256: {sha256(old).hexdigest()}\n'
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
        if same:
            # Report the retained version, including its original/missing provenance.
            return previous  # Keep bytes, mtime and the review fingerprint unchanged.
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


def _json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _facts_object(content):
    value = json.loads(content)
    if not isinstance(value, dict) or value.get('schema') != 'ag-facts/1':
        raise ValueError('Expected an ag-facts/1 JSON object')
    _json_bytes(value)  # Reject NaN/Infinity, including in the previous version.
    return value


def _field_differences(before, after, path=''):
    """JSON Pointer paths, including individual array elements and type changes."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if key not in before:
                changes.append(dict(path=pointer, change='added', new=after[key]))
            elif key not in after:
                changes.append(dict(path=pointer, change='removed', old=before[key]))
            else:
                changes.extend(_field_differences(before[key], after[key], pointer))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            pointer = f'{path}/{index}'
            if index >= len(before):
                changes.append(dict(path=pointer, change='added', new=after[index]))
            elif index >= len(after):
                changes.append(dict(path=pointer, change='removed', old=before[index]))
            else:
                changes.extend(_field_differences(before[index], after[index], pointer))
        return changes
    return ([] if _json_bytes(before) == _json_bytes(after) else
            [dict(path=path, change='changed', old=before, new=after)])


def _reparse_references(study, digest):
    """Reject links before parsing; read only text candidates, never follow links."""
    from ag.study import local_path
    references = []
    pattern = re.compile(r'(?<![0-9A-Fa-f])' + digest + r'(?![0-9A-Fa-f])')
    def failed(error):
        raise error
    for root, dirs, files in os.walk(study, followlinks=False, onerror=failed):
        for name in dirs + files:
            path = local_path(study, Path(root) / name)
            mode = path.stat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ValueError('Study entries must be regular files or directories')
            if name in files and path.suffix.lower() in {'.md', '.json', '.csv'}:
                try:
                    content = path.read_text(encoding='utf-8')
                except UnicodeDecodeError:
                    continue  # Binary data with a text suffix is not a text reference.
                if pattern.search(content):
                    references.append(path.relative_to(study).as_posix())
    return sorted(references)


def _archive_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')


def _write_synced(handle, content):
    handle.write(content)
    handle.flush()
    os.fsync(handle.fileno())


def reparse_facts(attempt_dir, *, dry_run=False, out=None):
    """Locally reparse fetched evidence, preserving every prior facts version.

    All input/path/reference checks precede writes. Unlike build_facts this
    operation never exports geometries or edits study/review records.
    """
    from ag.study import local_path
    directory = Path(attempt_dir).expanduser().absolute()
    study = directory.parent.parent
    directory = local_path(study, directory)
    if directory.parent.name != 'attempts':
        raise ValueError('Reparse requires an Attempt in study/attempts')
    if dry_run != (out is not None):
        raise ValueError('--dry-run requires --out; --out is only valid with --dry-run')
    target = local_path(study, directory / 'facts.json')
    old = _existing_bytes(target)
    if old is None:
        raise ValueError('Reparse requires existing facts.json')
    previous = _facts_object(old)
    digest = sha256(old).hexdigest()
    references = _reparse_references(study, digest)
    status_path = local_path(study, directory / 'status.json')
    status_bytes = status_path.read_bytes()
    status = json.loads(status_bytes)
    if not isinstance(status, dict) or status.get('state') != 'fetched':
        raise ValueError('Reparse requires Attempt state fetched')
    # Every parser input lives under the checked Attempt tree. Gaussian uses
    # the same input-matched, unambiguous local log selection as ordinary facts.
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    if manifest['template'] in ('gaussian', 'gaussian-cp'):
        gaussian_log(directory)
    else:
        primary = {'xtb': 'xtb.out', 'crest': 'crest.out'}.get(manifest['template'])
        if primary is None or not (directory / 'outputs' / primary).is_file():
            raise ValueError('Missing local program log or unsupported template')
    facts, geometries = parse_facts(directory)
    facts['ag_provenance'] = ag_provenance()
    content = _json_bytes(facts)
    _facts_object(content)
    for name, geometry in geometries.items():
        path = local_path(directory, directory / name)
        existing = _existing_bytes(path)
        if existing is not None and existing != geometry.encode('utf-8'):
            raise ValueError(f'{name} differs from parsed geometry; manual review required')
    result = dict(old_sha256=digest, new_sha256=sha256(content).hexdigest(),
                  differences=_field_differences(previous, facts),
                  references_to_old_sha256=references, dry_run=dry_run)
    if dry_run:
        destination = Path(out).expanduser().absolute()
        destination = local_path(destination.parent, destination)
        if destination.is_relative_to(study) or destination.suffix.lower() != '.json':
            raise ValueError('--out must be a .json file outside the study')
        if not destination.parent.is_dir() or destination.exists():
            raise ValueError('--out parent must exist and output must not exist')
        with destination.open('xb') as handle:
            try:
                _write_synced(handle, content)
            except BaseException:
                destination.unlink()  # Only this unpublished preview, never old facts.
                raise
        result['out'] = str(destination)
        return result

    history = local_path(study, directory / 'facts-history')
    if history.exists() and not history.is_dir():
        raise ValueError('facts-history must be a directory')
    archive = history / f'{_archive_stamp()}-{digest[:12]}.json'
    if archive.exists():
        raise FileExistsError('facts-history archive already exists; refusing overwrite')
    # Share the ordinary facts writer lock. Dry-run never creates this file.
    fd = os.open(directory / '.facts.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _existing_bytes(target) != old or status_path.read_bytes() != status_bytes:
            raise ValueError('facts.json or status.json changed during reparse')
        if archive.exists():
            raise FileExistsError('facts-history archive already exists; refusing overwrite')
        fd, temporary = tempfile.mkstemp(prefix='.facts-reparse-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as handle:
                _write_synced(handle, content)
            staged = Path(temporary).read_bytes()
            _facts_object(staged)
            if staged != content:
                raise ValueError('Temporary facts validation failed')
            history.mkdir(exist_ok=True)
            with archive.open('xb') as handle:
                try:
                    _write_synced(handle, old)
                    if sha256(archive.read_bytes()).hexdigest() != digest:
                        raise ValueError('Archived facts hash mismatch')
                except BaseException:
                    archive.unlink()  # Discard only an incomplete copy; source is untouched.
                    raise
            history_fd = os.open(history, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(history_fd)
            finally:
                os.close(history_fd)
            # Persist the new history directory entry before publishing facts;
            # otherwise a crash could retain the replacement but lose its archive.
            directory_fd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            if _existing_bytes(target) != old or status_path.read_bytes() != status_bytes:
                raise ValueError('facts.json or status.json changed during reparse')
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    result['archive'] = archive.relative_to(study).as_posix()
    return result


def _run(args):
    try:
        if (args.dry_run or args.out is not None) and not args.reparse:
            raise ValueError('--dry-run and --out require --reparse')
        directory = resolve_attempt(args.attempt, args.study, strict=args.reparse)
        facts = (reparse_facts(directory, dry_run=args.dry_run, out=args.out) if args.reparse else
                 build_facts(directory, refresh=args.refresh))
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--refresh', action='store_true',
                        help='After human review, archive old facts by SHA-256 and write the new version')
    modes.add_argument('--reparse', action='store_true',
                       help='Reparse fetched local logs, archive old facts and report hashes/references')
    parser.add_argument('--dry-run', action='store_true', help='Preview --reparse outside the study')
    parser.add_argument('--out', help='New .json file outside the study, required with --dry-run')
    parser.set_defaults(func=_run)
