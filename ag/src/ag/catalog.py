"""Local research-object registration and human-quoted adoption (T119).

The append-only journal is authoritative; state.json is only a derived view.
Checks prevent cross-study attribution, incompatible adoption and silent loss
of history. No parser, scientific decision or remote operation runs here.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

from ag import attempt, study
from ag.config import load_config
from ag.locks import submission_lock


ROLES = ('crest', 'scan', 'ts', 'opt', 'freq', 'stable', 'irc', 'sp', 'other')
ADOPT_ROLES = ('opt', 'freq', 'sp')
KINDS = ('formal', 'energy', 'state-check', 'ensemble', 'irc', 'thermo',
         'stage-review', 'figure', 'other')
OBJECT_FIELDS = ('name', 'state_label', 'multiplicity', 'conformer', 'note')


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must not be empty')
    return value


def resolve_study(value):
    path = Path(value).expanduser()
    if path.is_absolute() or path.is_dir() or len(path.parts) > 1:
        root = study.local_path(path.absolute(), path.absolute())
        study.identifier(root.name)
    else:
        root = study.locate(load_config(local_only=True), value)
    if not root.is_dir() or not study.local_path(root, root / 'attempts').is_dir():
        raise ValueError('Study must exist and contain an attempts directory')
    return root


def catalog_path(root, name):
    return study.local_path(root, root / 'catalog' / name)


@contextmanager
def read_lock(root):
    """Synchronize with writers without creating files for read-only commands."""
    path = catalog_path(root, 'submit.lock')
    if not path.exists():
        yield
        return
    with path.open('rb') as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_journal(root):
    path = catalog_path(root, 'journal.jsonl')
    data = path.read_bytes() if path.exists() else b''
    events, previous = [], None
    try:
        for seq, line in enumerate(data.splitlines(keepends=True), 1):
            if not line.endswith(b'\n'):
                raise ValueError('incomplete final line')
            event = json.loads(line)
            if (event['schema'] != 'ag-catalog/1' or type(event['seq']) is not int
                    or event['seq'] != seq or event['prev_sha256'] != previous):
                raise ValueError('seq or prev_sha256 mismatch')
            at = datetime.fromisoformat(event['at'])
            if at.utcoffset() is None or at.utcoffset().total_seconds() != 0:
                raise ValueError('event timestamp must be UTC')
            events.append(event)
            previous = sha256(line).hexdigest()
        replay(events)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(f'Catalog journal damaged: {exc}; requires manual handling; '
                         'ag never repairs or rewrites the journal') from exc
    return data, events, previous


def replay(events):
    objects, kinds = {}, {}
    for e in events:
        op = e['op']
        if op == 'object':
            identity = study.identifier(e['id'])
            if type(e['update']) is not bool or e['update'] != (identity in objects):
                raise ValueError('object ID already exists (use --update), or update ID missing')
            text(e['name'], 'name')
            for key in ('state_label', 'conformer', 'note'):
                if e[key] is not None and not isinstance(e[key], str):
                    raise ValueError(f'Invalid object {key}')
            if e['multiplicity'] is not None and (type(e['multiplicity']) is not int or e['multiplicity'] < 1):
                raise ValueError('multiplicity must be a positive integer')
            obj = objects.setdefault(identity, dict(id=identity, status='candidate', members=[],
                                                    adopted=dict.fromkeys(ADOPT_ROLES)))
            obj.update({key: e[key] for key in OBJECT_FIELDS})
        elif op in ('member', 'adopt', 'retire'):
            obj = objects[e['object']]
            if op == 'retire':
                text(e['reason'], 'reason')
                obj['status'] = 'retired'
                continue
            study.identifier(e['attempt'])
            if op == 'member':
                if e['role'] not in ROLES or type(e.get('force_role', False)) is not bool:
                    raise ValueError('Invalid member role')
                obj['members'] = [m for m in obj['members'] if m['attempt'] != e['attempt']]
                obj['members'].append(dict(attempt=e['attempt'], role=e['role']))
            else:
                if e['role'] not in ADOPT_ROLES:
                    raise ValueError('Invalid adoption role')
                text(e['quote'], 'quote')
                if len(e['quote']) > 2000:
                    raise ValueError('quote must be at most 2000 characters')
                if not any(m['attempt'] == e['attempt'] for m in obj['members']):
                    raise ValueError('Adoption must follow membership')
                checks = e['checks']
                if (any(checks[k] is not True for k in ('fetched', 'facts_readable', 'role_match'))
                        or (e['role'] == 'freq' and checks['freq_review'] == 'fail')):
                    raise ValueError('Invalid adoption checks')
                obj['adopted'][e['role']] = {k: e[k] for k in ('attempt', 'at', 'quote', 'report')}
                if obj['status'] != 'retired':
                    obj['status'] = 'adopted'
        elif op == 'report-kind':
            if e['kind'] not in KINDS:
                raise ValueError('Invalid report kind')
            text(e['report'], 'report')
            kinds[e['report']] = e['kind']
        else:
            raise ValueError(f'Unknown catalog operation: {op}')
    return objects, kinds


def record(root, identity):
    path = study.local_path(root, root / 'attempts' / study.identifier(identity))
    if not path.is_dir():
        raise ValueError(f'Attempt {identity} does not exist in this study (exact ID required)')
    return path, attempt.local_record(path)


def infer_roles(manifest):
    template, science = manifest.get('template'), manifest.get('science', {})
    if template == 'crest':
        return ['crest']
    if science.get('scan'):
        return ['scan']
    if template == 'xtb':
        return ['opt' if '--opt' in manifest.get('template_params', {}) else 'sp']
    if template not in ('gaussian', 'gaussian-cp'):
        return []
    route = science.get('route') or ''
    roles = set(re.findall(r'(?:^|[\s#])(opt|freq|stable|irc|scan|sp)\b', route, re.I))
    roles = {role.lower() for role in roles}
    opt = re.search(r'(?:^|[\s#])opt\b\s*(?:=\s*)?(\([^()]*\)|[\w]+)', route, re.I)
    if 'opt' in roles and opt and re.search(r'\b(ts|qst2|qst3)\b', opt[1], re.I):
        roles.remove('opt')
        roles.add('ts')
    # A Gaussian route with a method/basis and no task keyword defaults to SP.
    if not roles and re.search(r'\S+/\S+', route):
        roles.add('sp')
    # A combined task is never a standalone SP, even if SP is also spelled out.
    if roles - {'sp'}:
        roles.discard('sp')
    return [role for role in ROLES if role in roles]


def read_facts(root, path):
    target = study.local_path(root, path / 'facts.json')
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('schema') != 'ag-facts/1':
            raise ValueError('expected ag-facts/1 object')
    except (OSError, ValueError) as exc:
        raise ValueError(f'Attempt {path.name}: facts not readable ({exc})') from exc
    return value


def report_path(root, value):
    path = Path(text(value, 'report'))
    if path.is_absolute():
        raise ValueError('report must be relative to analyses/')
    # Accept both analyses/foo and foo; persist the analyses-relative spelling.
    if path.parts and path.parts[0] == 'analyses':
        path = Path(*path.parts[1:])
    base = study.local_path(root, root / 'analyses')
    # Check before normalization so a symlink followed by /.. cannot be hidden.
    candidate = base / path
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise ValueError('Symbolic links are not allowed in report paths')
    target = study.local_path(base, Path(os.path.abspath(candidate)))
    if not target.is_file():
        raise ValueError('report must be an existing file inside analyses/')
    return target.relative_to(base).as_posix()


def plan(root, events, op, **fields):
    objects, _ = replay(events)
    checks, warnings, pending = dict(study_exists=True), [], []
    if op == 'object':
        identity = study.identifier(fields['id'])
        old = objects.get(identity, {})
        fields = dict(id=identity, update=fields.get('update', False),
                      **{k: fields.get(k) if fields.get(k) is not None else old.get(k)
                         for k in OBJECT_FIELDS})
    elif op in ('member', 'adopt', 'retire'):
        identity = study.identifier(fields['object'])
        if identity not in objects:
            raise ValueError(f'Unknown object: {identity}')
        if op in ('member', 'adopt'):
            path, (manifest, current, _) = record(root, fields['attempt'])
            roles = infer_roles(manifest)
            checks.update(attempt_exists=True, same_study=True, inferred_roles=roles)
            role = fields['role']
            if op == 'member':
                if role == 'auto':
                    if not roles:
                        raise ValueError('Cannot infer role; specify --role explicitly')
                    role = roles[0]
                force = fields.get('force_role', False)
                if roles and role not in roles and not force:
                    raise ValueError('Role differs from inferred calculation type; use --force-role')
                fields = dict(object=identity, attempt=path.name, role=role, force_role=force)
                checks['role_match'] = role in roles
            else:
                quote = text(fields['quote'], 'quote')
                if len(quote) > 2000:
                    raise ValueError('quote must be at most 2000 characters')
                if current['state'] != 'fetched':
                    raise ValueError('Adoption requires a fetched Attempt')
                facts = read_facts(root, path)
                matches = bool(set(roles) & ({'opt', 'ts'} if role == 'opt' else {role}))
                if role not in ADOPT_ROLES or not matches:
                    raise ValueError('Adoption role does not match calculation type')
                review = facts.get('freq_step_review') if role == 'freq' else None
                if role == 'freq' and review == 'fail':
                    raise ValueError('Cannot adopt Freq with freq_step_review=fail')
                if review == 'manual_review':
                    warnings.append('WARNING: freq_step_review=manual_review; requires human review; '
                                    'registration is not scientific acceptance.')
                report = report_path(root, fields['report']) if fields.get('report') is not None else None
                adoption_checks = dict(fetched=True, facts_readable=True, role_match=True, freq_review=review)
                checks.update(adoption_checks)
                if not any(m['attempt'] == path.name for m in objects[identity]['members']):
                    pending.append(dict(op='member', object=identity, attempt=path.name,
                                        role=role if role in roles else roles[0], force_role=False))
                fields = dict(object=identity, attempt=path.name, role=role, quote=quote,
                              report=report, checks=adoption_checks)
    elif op == 'report-kind':
        fields = dict(report=report_path(root, fields['report']), kind=fields['kind'])
        checks['report_exists_in_analyses'] = True
    pending.append(dict(op=op, **fields))
    # Validate the whole proposal before appending even its automatic member.
    replay(events + [dict(at=now(), **e) for e in pending])
    return pending, checks, warnings


def derived_state(root, events, data):
    objects, kinds = replay(events)
    for obj in objects.values():
        obj.pop('note')  # Notes remain in the authoritative object events.
        values = dict(scf_h=None, freq_scf_h=None, zpe_h=None, g_h=None,
                      source=dict(scf_h=None, freq_scf_h=None, zpe_h=None, g_h=None))
        for role, mapping in (('sp', {'scf_h': 'scf'}),
                              ('freq', {'freq_scf_h': 'scf', 'zpe_h': 'zpe', 'g_h': 'g'})):
            adopted = obj['adopted'][role]
            if adopted is None:
                continue
            try:
                path, _ = record(root, adopted['attempt'])
                facts = read_facts(root, path)
                energies = facts.get('energies') or {}
                if facts.get('units', {}).get('energy') != 'Hartree':
                    continue
                for key, source in mapping.items():
                    value = energies.get(source)
                    if type(value) in (int, float) and math.isfinite(value):
                        values[key] = value
                        values['source'][key] = adopted['attempt']
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                pass  # Missing copied values are null, never invented or recomputed.
        obj['values'] = values
    return dict(schema='ag-catalog-state/1', journal_sha256=sha256(data).hexdigest(),
                generated_at=now(), objects=list(objects.values()), report_kinds=kinds)


def write_state(root, value):
    target = catalog_path(root, 'state.json')
    fd, name = tempfile.mkstemp(prefix='.state-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(encode(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def change(root, op, *, dry_run=False, **fields):
    root = resolve_study(root)

    def prepare():
        data, events, previous = read_journal(root)
        pending, checks, warnings = plan(root, events, op, **fields)
        lines, added = [], []
        for seq, event in enumerate(pending, len(events) + 1):
            event = dict(schema='ag-catalog/1', seq=seq, at=now(), prev_sha256=previous, **event)
            line = encode(event)
            previous = sha256(line).hexdigest()
            lines.append(line)
            added.append(event)
        return data, events, b''.join(lines), added, checks, warnings

    if dry_run:
        with read_lock(root):
            _, _, _, added, checks, warnings = prepare()
    else:
        directory = catalog_path(root, 'journal.jsonl').parent
        directory.mkdir(exist_ok=True)
        catalog_path(root, 'submit.lock')
        # Reuse locks.py with a study-local directory, never the global submit lock.
        with submission_lock({'_config_dir': str(directory)}):
            data, events, new, added, checks, warnings = prepare()
            target = catalog_path(root, 'state.json')
            if target.exists() and not target.is_file():
                raise ValueError('Catalog state.json must be a regular file')
            value = derived_state(root, events + added, data + new)
            path = catalog_path(root, 'journal.jsonl')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            try:
                if os.write(fd, new) != len(new):
                    raise OSError('Short catalog append; stop and inspect journal manually')
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                write_state(root, value)
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError as exc:
                raise OSError('Catalog journal appended but derived state was not fully published; '
                              'stop and inspect locally; do not repeat adoption blindly') from exc
    return dict(dry_run=dry_run, events=added, checks=checks, warnings=warnings)


def show(root):
    root = resolve_study(root)
    with read_lock(root):
        data, events, _ = read_journal(root)
        path = catalog_path(root, 'state.json')
        if not path.exists():
            if events:
                raise ValueError('Catalog state missing; journal retained; requires manual handling')
            return derived_state(root, [], b''), []
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('schema') != 'ag-catalog-state/1':
            raise ValueError('Invalid catalog state; requires manual handling')
        warnings = []
        if value.get('journal_sha256') != sha256(data).hexdigest():
            warnings.append('WARNING: state.json journal_sha256 differs from journal; state is stale.')
        return value, warnings


def suggest(root):
    root = resolve_study(root)
    with read_lock(root):
        _, events, _ = read_journal(root)
        objects, _ = replay(events)
        assigned = {m['attempt'] for obj in objects.values() for m in obj['members']}
        manifests = {}
        for path in sorted((root / 'attempts').iterdir()):
            if path.name.startswith('.'):
                continue
            study.local_path(root, path)
            if path.is_dir():
                _, (manifest, _, _) = record(root, path.name)
                manifests[path.name] = manifest
        remaining = set(manifests) - assigned
        edges, missing = [], []
        adjacency = {identity: set() for identity in remaining}
        for child, manifest in manifests.items():
            for parent in manifest.get('parents', []):
                identity = parent['attempt_id']
                if identity not in manifests:
                    missing.append(dict(parent=identity, child=child))
                if child in remaining and identity in remaining:
                    adjacency[child].add(identity)
                    adjacency[identity].add(child)
                    edges.append(dict(parent=identity, child=child, relation=parent.get('relation', '')))
        suggestions, used = [], set(objects)
        while remaining:
            first = min(remaining)
            component, todo = set(), [first]
            while todo:
                identity = todo.pop()
                if identity in component:
                    continue
                component.add(identity)
                todo.extend(adjacency[identity] - component)
            remaining -= component
            number = len(suggestions) + 1
            proposed = f'object-{number}'
            while proposed in used:
                number += 1
                proposed = f'object-{number}'
            used.add(proposed)
            commands = [shlex.join(['ag', 'catalog', 'object', str(root), '--id', proposed,
                                    '--name', proposed])]
            for identity in sorted(component):
                # Unknown types need a deliberate manual choice before execution.
                role = 'auto' if infer_roles(manifests[identity]) else '<CHOOSE_ROLE>'
                commands.append(shlex.join(['ag', 'catalog', 'member', str(root), '--object', proposed,
                                            '--attempt', identity, '--role', role]))
            suggestions.append(dict(id=proposed, members=sorted(component),
                                    parents=[e for e in edges if e['child'] in component], commands=commands))
        return dict(suggestions=suggestions, missing_parents=missing)


def run(args):
    if args.action == 'show':
        value, warnings = show(args.study)
        for warning in warnings:
            print(warning, file=sys.stderr)
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print('ID\tNAME\tSTATUS\tMEMBERS (ROLE)\tOPT\tFREQ\tSP')
            for obj in value['objects']:
                cells = [obj['id'], obj['name'], obj['status'],
                         ', '.join(f"{m['attempt']} ({m['role']})" for m in obj['members'])]
                cells.extend((obj['adopted'][role] or {}).get('attempt', '-') for role in ADOPT_ROLES)
                print('\t'.join(str(cell).replace('\t', ' ').replace('\n', ' ') for cell in cells))
    elif args.action == 'suggest':
        value = suggest(args.study)
        print('Suggestions only: parent links do not establish conformer or electronic-state identity.')
        for group in value['suggestions']:
            print(f"\n{group['id']}: {', '.join(group['members'])}")
            for edge in group['parents']:
                print(f"  {edge['parent']} -> {edge['child']} ({edge['relation']})")
            print('\n'.join(group['commands']))
        for edge in value['missing_parents']:
            print(f"Missing parent: {edge['parent']} -> {edge['child']}")
        if not value['suggestions']:
            print('No unassigned Attempts.')
    else:
        fields = {key: val for key, val in vars(args).items()
                  if key not in ('command', 'action', 'study', 'dry_run', 'func')}
        value = change(args.study, args.action, dry_run=args.dry_run, **fields)
        for warning in value['warnings']:
            print(warning, file=sys.stderr)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def register(subparsers):
    parser = subparsers.add_parser('catalog', description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    for op in ('object', 'member', 'adopt', 'retire', 'report-kind', 'show', 'suggest'):
        child = actions.add_parser(op)
        child.add_argument('study')
        child.set_defaults(func=run)
        if op == 'object':
            child.add_argument('--id', required=True)
            child.add_argument('--name', required=True)
            child.add_argument('--update', action='store_true')
            child.add_argument('--state-label')
            child.add_argument('--multiplicity', type=int)
            child.add_argument('--conformer')
            child.add_argument('--note')
        if op in ('member', 'adopt', 'retire'):
            child.add_argument('--object', required=True)
        if op in ('member', 'adopt'):
            child.add_argument('--attempt', required=True)
            child.add_argument('--role', choices=('auto', *ROLES) if op == 'member' else ADOPT_ROLES,
                               default='auto' if op == 'member' else None, required=op == 'adopt')
        if op == 'member':
            child.add_argument('--force-role', action='store_true')
        if op == 'adopt':
            child.add_argument('--quote', required=True,
                               help='Verbatim human words from this study in the current conversation')
            child.add_argument('--report')
        if op == 'retire':
            child.add_argument('--reason', required=True)
        if op == 'report-kind':
            child.add_argument('--report', required=True)
            child.add_argument('--kind', required=True, choices=KINDS)
        if op == 'show':
            child.add_argument('--json', action='store_true')
        elif op != 'suggest':
            child.add_argument('--dry-run', action='store_true')
