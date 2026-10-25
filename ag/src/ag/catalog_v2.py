"""Catalog v2 field validation, local provenance and derived channel views.

The single event replay loop lives in catalog.py. These helpers never parse
calculation outputs, change research evidence, or perform remote operations.
"""
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import stat

from ag import attempt, study
from ag.gaussian_input import ATOMIC_NUMBERS, cartesian

OPS = ('channel', 'channel-status', 'coverage', 'candidate', 'candidate-result')
ORIGINS = ('scan', 'qst', 'template-transform', 'path-search', 'manual', 'literature')
OUTCOMES = ('diagnosed', 'accepted', 'other_channel', 'minimum', 'opt_failed', 'multiple_imag', 'other')
ASSIGNMENTS = ('none', 'tentative', 'verified', 'undetermined')
UPGRADE_WARNING = ('将升级 catalog 为 /2；旧版 ag 和 v4.5.x 前端将不能再读写这个 catalog。'
                   '旧日志行保持原字节；升级后不可通过删除事件降级。')
FIELDS = {
    'object': {'id', 'name', 'state_label', 'multiplicity', 'conformer', 'note', 'update'},
    'member': {'object', 'attempt', 'role', 'force_role'},
    'adopt': {'object', 'role', 'attempt', 'quote', 'report', 'checks'},
    'retire': {'object', 'reason'}, 'report-kind': {'report', 'kind'},
    'channel': {'object', 'id', 'name', 'definition', 'product_branch', 'discovered', 'confirmed', 'update'},
    'channel-status': {'object', 'channel', 'status', 'quote', 'reason', 'checks'},
    'coverage': {'object', 'statement', 'scope', 'budget', 'quote'},
    'candidate': {'object', 'id', 'source', 'file', 'sha256', 'n_atoms', 'formula', 'origin',
                  'parent', 'transform', 'target_channel', 'literature', 'note'},
    'candidate-result': {'object', 'candidate', 'outcome', 'attempt', 'diagnosis', 'assignment',
                         'quote', 'note', 'checks'},
}


def is_v2(event):
    return (event.get('schema') == 'ag-catalog/2' or event['op'] in OPS or
            bool({'expected_formula', 'expected_charge'} & event.keys()))


def validate_fields(event):
    op, schema = event['op'], event['schema']
    if op not in FIELDS:
        raise ValueError(f'Unknown catalog operation: {op}')
    allowed = FIELDS[op] | {'schema', 'seq', 'at', 'op', 'prev_sha256'}
    if schema == 'ag-catalog/2' and op == 'object':
        allowed |= {'expected_formula', 'expected_charge'}
    if (schema == 'ag-catalog/1' and op in OPS) or event.keys() - allowed:
        raise ValueError(f'Unsupported fields or operation for {schema}')


def text(value, field, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must not be empty')
    return value


def quote(value):
    text(value, 'quote')
    if len(value) > 2000:
        raise ValueError('quote must be at most 2000 characters')
    return value


def hill(counts):
    order = (['C'] + (['H'] if 'H' in counts else []) + sorted(set(counts) - {'C', 'H'})
             if 'C' in counts else sorted(counts))
    return ''.join(symbol + (str(counts[symbol]) if counts[symbol] != 1 else '') for symbol in order)


def formula(value):
    text(value, 'formula')
    tokens = re.findall(r'([A-Z][a-z]?)([0-9]*)', value)
    if not tokens or ''.join(a + n for a, n in tokens) != value:
        raise ValueError('formula must contain element symbols and positive integer counts')
    counts = Counter()
    for symbol, number in tokens:
        if symbol not in ATOMIC_NUMBERS or (number and (number.startswith('0') or int(number) < 1)):
            raise ValueError('formula contains an invalid element or count')
        counts[symbol] += int(number or '1')
    return hill(counts)


def expected(value, field):
    if value in ('unset', 'unknown'):
        return dict(state=value, value=None)
    if field == 'formula':
        value = formula(value)
    elif isinstance(value, bool) or not re.fullmatch(r'[+-]?[0-9]+', str(value)):
        raise ValueError('charge must be an integer, unknown or unset')
    else:
        value = int(value)
    return dict(state='set', value=value)


def validate_expected(value, field):
    if not isinstance(value, dict) or set(value) != {'state', 'value'}:
        raise ValueError('Invalid expected field')
    if value['state'] in ('unset', 'unknown') and value['value'] is None:
        return
    if value['state'] == 'set':
        actual = value['value']
        if field == 'charge' and type(actual) is int:
            return
        if field == 'formula' and isinstance(actual, str) and formula(actual) == actual:
            return
    raise ValueError('Invalid expected field state/value')


def initialize(obj):
    obj.setdefault('expected', {key: dict(state='unset', value=None) for key in ('formula', 'charge')})
    obj.setdefault('channels', [])
    obj.setdefault('candidates', [])
    obj.setdefault('coverage', None)
    obj.setdefault('member_mismatches', [])


def find(items, identity, label):
    study.identifier(identity)
    for item in items:
        if item['id'] == identity:
            return item
    raise ValueError(f'Unknown {label}: {identity}')


def nullable_string(value, field):
    if value is not None and not isinstance(value, str):
        raise ValueError(f'Invalid {field}')


def json_object(value, field):
    if value is not None:
        if not isinstance(value, dict):
            raise ValueError(f'{field} must be a JSON object')
        json.dumps(value, allow_nan=False)


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Invalid SHA-256')


def verified_results(obj, channel):
    return [dict(candidate=c['id'], seq=r['seq']) for c in obj['candidates'] for r in c['results']
            if r['assignment'] == dict(status='verified', channels=[channel])]


def apply_event(obj, e):
    """Apply one v2 event within catalog.replay, validating stored evidence."""
    op = e['op']
    if op == 'channel':
        identity = study.identifier(e['id'])
        old = next((c for c in obj['channels'] if c['id'] == identity), None)
        if type(e['update']) is not bool or e['update'] != (old is not None):
            raise ValueError('channel ID already exists (use --update), or update ID missing')
        if old is None and obj['status'] == 'retired':
            raise ValueError('Cannot add a channel to a retired object')
        for key in ('name', 'definition'):
            text(e[key], key)
        nullable_string(e['product_branch'], 'product_branch')
        if any(type(e[k]) is not bool for k in ('discovered', 'confirmed')):
            raise ValueError('Invalid channel confirmation flags')
        if not e['discovered'] and not e['confirmed']:
            raise ValueError('Only discovered channels can be pending confirmation')
        if old and (old['discovered'] != e['discovered'] or (old['confirmed'] and not e['confirmed'])):
            raise ValueError('Channel discovery provenance cannot change or confirmation be revoked')
        if old is None:
            old = dict(id=identity, declaration=None, candidate_ids=[], outcome_counts={})
            obj['channels'].append(old)
        old.update({k: e[k] for k in ('name', 'definition', 'product_branch', 'discovered', 'confirmed')})
    elif op == 'channel-status':
        channel = find(obj['channels'], e['channel'], 'channel')
        if e['status'] not in ('verified', 'excluded-low-confidence', 'cleared'):
            raise ValueError('Invalid channel declaration')
        quote(e['quote'])
        nullable_string(e['reason'], 'reason')
        if e['status'] == 'excluded-low-confidence':
            text(e['reason'], 'reason')
        if e['status'] == 'verified':
            matches = verified_results(obj, e['channel'])
            if not matches or e['checks'] != dict(verified_candidate_results=matches):
                raise ValueError('verified channel requires a verified candidate result')
        elif e['checks'] != {}:
            raise ValueError('Invalid channel declaration checks')
        channel['declaration'] = (None if e['status'] == 'cleared' else
                                  {k: e[k] for k in ('status', 'at', 'quote', 'reason')})
    elif op == 'coverage':
        if e['statement'] not in ('stable', 'withdrawn'):
            raise ValueError('Invalid coverage statement')
        for key in ('scope', 'budget'):
            text(e[key], key)
        quote(e['quote'])
        obj['coverage'] = {k: e[k] for k in ('statement', 'scope', 'budget', 'at', 'quote')}
    elif op == 'candidate':
        identity = study.identifier(e['id'])
        if any(c['id'] == identity for c in obj['candidates']):
            raise ValueError('candidate ID already exists')
        digest(e['sha256'])
        if e['file'] != f"catalog/candidates/{e['sha256']}.xyz":
            raise ValueError('Invalid candidate archive path')
        if type(e['n_atoms']) is not int or e['n_atoms'] < 1 or formula(e['formula']) != e['formula']:
            raise ValueError('Invalid candidate composition')
        counts = re.findall(r'[A-Z][a-z]?([0-9]*)', e['formula'])
        if sum(int(n or '1') for n in counts) != e['n_atoms']:
            raise ValueError('Candidate composition differs from atom count')
        text(e['source'], 'source')
        if e['origin'] not in ORIGINS:
            raise ValueError('Invalid candidate origin')
        parent = e['parent']
        if not isinstance(parent, dict) or set(parent) != {'attempt', 'file'}:
            raise ValueError('Invalid candidate parent')
        if parent['attempt'] is not None:
            study.identifier(parent['attempt'])
        if parent['file'] is not None:
            if not isinstance(parent['file'], dict) or set(parent['file']) != {'source', 'sha256'}:
                raise ValueError('Invalid parent file')
            text(parent['file']['source'], 'parent source')
            digest(parent['file']['sha256'])
        json_object(e['transform'], 'transform')
        if e['target_channel'] is not None:
            find(obj['channels'], e['target_channel'], 'channel')
        literature = e['literature']
        if e['origin'] == 'literature' and literature is None:
            raise ValueError('literature origin requires DOI')
        if literature is not None:
            if not isinstance(literature, dict) or set(literature) != {'doi', 'si_location'}:
                raise ValueError('Invalid literature reference')
            if not isinstance(literature['doi'], str) or not re.fullmatch(r'10\.[0-9]{4,9}/\S+', literature['doi']):
                raise ValueError('Invalid DOI format')
            nullable_string(literature['si_location'], 'si_location')
        nullable_string(e['note'], 'note')
        candidate = {k: e[k] for k in ('id', 'file', 'sha256', 'n_atoms', 'formula', 'origin',
                                      'parent', 'transform', 'target_channel', 'literature', 'note')}
        candidate.update(registered_at=e['at'], results=[], latest_assignment=None)
        obj['candidates'].append(candidate)
    elif op == 'candidate-result':
        candidate = find(obj['candidates'], e['candidate'], 'candidate')
        if e['outcome'] not in OUTCOMES:
            raise ValueError('Invalid candidate outcome')
        nullable_string(e['note'], 'note')
        if e['outcome'] == 'other':
            text(e['note'], 'note for other outcome')
        if e['attempt'] is not None:
            study.identifier(e['attempt'])
        json_object(e['diagnosis'], 'diagnosis')
        assignment = e['assignment']
        if not isinstance(assignment, dict) or set(assignment) != {'status', 'channels'}:
            raise ValueError('Invalid assignment')
        status, channels = assignment['status'], assignment['channels']
        if status not in ASSIGNMENTS or not isinstance(channels, list):
            raise ValueError('Invalid assignment')
        for identity in channels:
            find(obj['channels'], identity, 'channel')
        if len(channels) != len(set(channels)):
            raise ValueError('Duplicate assignment channels')
        if ((status in ('tentative', 'verified') and len(channels) != 1) or
                (status == 'none' and channels) or (status == 'undetermined' and len(channels) == 1)):
            raise ValueError('assignment requires none: 0, tentative/verified: 1, undetermined: 0 or >=2 channels')
        nullable_string(e['quote'], 'quote')
        if e['quote'] is not None:
            quote(e['quote'])
        if status == 'verified':
            quote(e['quote'])
            checks = e['checks']
            if (e['attempt'] is None or not any(m['attempt'] == e['attempt'] for m in obj['members']) or
                    not isinstance(checks, dict) or set(checks) != {'fetched', 'facts_readable', 'n_imag', 'member'} or
                    any(checks[k] is not True for k in ('fetched', 'facts_readable', 'member')) or
                    type(checks['n_imag']) is not int or checks['n_imag'] != 1):
                raise ValueError('verified assignment requires fetched, readable facts, n_imag == 1 and membership')
        elif e['checks'] != {}:
            raise ValueError('Invalid candidate result checks')
        candidate['results'].append(dict(e))
        candidate['latest_assignment'] = dict(assignment)


def finish(obj):
    """Channel counts include every result, including failed/reassigned attempts."""
    for channel in obj['channels']:
        identity = channel['id']
        candidates = [c for c in obj['candidates'] if c['target_channel'] == identity or
                      any(identity in r['assignment']['channels'] for r in c['results'])]
        channel['candidate_ids'] = [c['id'] for c in candidates]
        channel['outcome_counts'] = dict(Counter(r['outcome'] for c in candidates for r in c['results']))
        declaration = channel['declaration']
        if declaration:
            status = declaration['status'].replace('-', '_')
        elif channel['discovered'] and not channel['confirmed']:
            status = 'pending_confirmation'
        elif any(r['assignment'] == dict(status='tentative', channels=[identity])
                 for c in candidates for r in c['results']):
            status = 'tentative_found'
        else:
            status = 'attempted_not_found' if candidates else 'untried'
        channel['status'] = status


def source_path(value):
    path = Path(value).expanduser().absolute()
    return study.local_path(Path(path.anchor), path)


def read_bytes(value, limit):
    path = source_path(value)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('Only regular source files are allowed')
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'Source file exceeds {limit} bytes')
    return data


def file_hash(value):
    path = source_path(value)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('Only regular parent files are allowed')
        result = sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def xyz(data, *, ensemble=False):
    rows = data.decode('utf-8').splitlines()
    frames, index = [], 0
    while index < len(rows):
        if not re.fullmatch(r'\s*[0-9]+\s*', rows[index]):
            raise ValueError('Invalid XYZ atom count')
        count = int(rows[index])
        end = index + count + 2
        if count < 1 or end > len(rows):
            raise ValueError('Empty or truncated XYZ')
        atoms = rows[index + 2:end]
        if any(not line.split() or line.split()[0] not in ATOMIC_NUMBERS for line in atoms):
            raise ValueError('XYZ requires valid element symbols')
        symbols = cartesian(atoms, first_line=index + 3)
        frames.append((count, hill(Counter(symbols))))
        index = end
    if not frames or (not ensemble and len(frames) != 1):
        raise ValueError('Expected exactly one XYZ geometry')
    if any(frame != frames[0] for frame in frames):
        raise ValueError('XYZ ensemble compositions differ')
    return frames[0]


def read_json(value):
    if value is None:
        return None
    result = json.loads(read_bytes(value, 65536))
    if not isinstance(result, dict):
        raise ValueError('Expected a JSON object')
    json.dumps(result, allow_nan=False)
    return result


def archive(root, event, data, *, write=False):
    """Exclusive content-addressed snapshot; never rewrite even a corrupt file."""
    path = study.local_path(root, root / event['file'])
    if sha256(data).hexdigest() != event['sha256']:
        raise ValueError('Candidate source hash mismatch')
    if path.exists():
        if read_bytes(path, 1024 * 1024) != data:
            raise ValueError('Candidate archive hash mismatch; requires manual handling')
        if path.stat().st_mode & 0o222:
            raise ValueError('Existing candidate archive must be read-only; requires manual handling')
    elif write:
        path.parent.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def manifest_info(root, identity):
    """Read immutable input provenance; never substitute missing charge/spin."""
    path = study.local_path(root, root / 'attempts' / study.identifier(identity))
    study.local_path(root, path / 'manifest.json')
    manifest = attempt.read_manifest(path)
    science = manifest.get('science') or {}
    values, unavailable = {}, {}
    groups = science.get('structures') if science.get('qst_mode') or 'structures' in science else [science]
    if not isinstance(groups, list) or not groups or any(not isinstance(g, dict) for g in groups):
        return {}, {k: 'QST structures missing or invalid' for k in ('formula', 'charge', 'multiplicity')}
    for key in ('formula', 'charge', 'multiplicity'):
        try:
            parts = []
            if key == 'formula' and manifest.get('template') in ('xtb', 'crest'):
                inputs = [item for item in manifest.get('inputs', []) if Path(item['name']).suffix.lower() == '.xyz']
                if len(inputs) != 1:
                    raise ValueError('Expected one declared input XYZ')
                item = inputs[0]
                data = read_bytes(study.local_path(root, path / 'inputs' / attempt.filename(item['name'])), 1024 * 1024)
                if sha256(data).hexdigest() != item['sha256'] or len(data) != item['size']:
                    raise ValueError('Input XYZ hash/size differs from manifest')
                parts = [xyz(data, ensemble=True)[1]]
            else:
                for group in groups:
                    if key == 'formula':
                        geometry = text(group.get('geometry'), 'science.geometry')
                        symbols = cartesian(geometry.splitlines(), first_line=1)
                        if not symbols:
                            raise ValueError('Missing geometry')
                        value = hill(Counter(symbols))
                    else:
                        value = group.get(key)
                        params = manifest.get('template_params') or {}
                        option = '--chrg' if key == 'charge' else '--uhf'
                        if manifest.get('template') in ('xtb', 'crest') and option in params:
                            raw = params[option]
                            if isinstance(raw, bool) or not re.fullmatch(r'[+-]?[0-9]+', str(raw)):
                                raise ValueError(f'Invalid {option}')
                            value = int(raw) + (1 if key == 'multiplicity' else 0)
                            if group.get(key) is not None and group[key] != value:
                                raise ValueError(f'{option} differs from science.{key}')
                        if type(value) is not int or (key == 'multiplicity' and value < 1):
                            raise ValueError(f'Missing or invalid {key}')
                    parts.append(value)
            if any(value != parts[0] for value in parts):
                raise ValueError(f'QST groups disagree on {key}')
            values[key] = parts[0]
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            unavailable[key] = str(exc)
    return values, unavailable


def member_report(root, obj):
    expected_values = {k: v['value'] for k, v in obj.get('expected', {}).items() if v['state'] == 'set'}
    if obj['multiplicity'] is not None:
        expected_values['multiplicity'] = obj['multiplicity']
    messages = [f"{obj['id']}: {key}={value['state']}; skipped / 跳过核对"
                for key, value in obj.get('expected', {}).items() if value['state'] != 'set']
    if obj['multiplicity'] is None:
        messages.append(f"{obj['id']}: multiplicity=unset; skipped / 跳过核对")
    mismatches = []
    for member in obj['members']:
        try:
            actual, missing = manifest_info(root, member['attempt'])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            actual, missing = {}, {k: str(exc) for k in expected_values}
        for key, value in expected_values.items():
            if key in missing:
                messages.append(f"{obj['id']}/{member['attempt']}: {key} 未核对: {missing[key]}")
            elif actual[key] != value:
                mismatches.append(dict(attempt=member['attempt'], field=key, expected=value, actual=actual[key]))
    return mismatches, messages


def object_suggest(root, identity):
    values, unavailable = manifest_info(root, identity)
    command = ['ag', 'catalog', 'object', str(root), '--id', '<OBJECT>', '--name', '<NAME>']
    for key, value in values.items():
        command.extend(['--' + key, str(value)])
    if 'formula' in values or 'charge' in values:
        command.append('--upgrade-catalog')
    return dict(attempt=identity, suggested=values, unavailable=unavailable,
                command=shlex.join(command) if values else None)


def plan(root, objects, op, fields, checks, warnings, archives):
    from ag import catalog
    identity = study.identifier(fields['object'])
    if identity not in objects:
        raise ValueError(f'Unknown object: {identity}')
    obj = objects[identity]
    initialize(obj)
    f = fields
    if op == 'channel':
        old = next((c for c in obj['channels'] if c['id'] == f['id']), {})
        update = f.get('update', False)
        if f.get('confirm') and (not update or not old.get('discovered')):
            raise ValueError('--confirm requires --update on a discovered channel')
        discovered = old.get('discovered', f.get('discovered', False))
        if old and f.get('discovered') and not old['discovered']:
            raise ValueError('Cannot change channel discovery provenance')
        return dict(object=identity, id=f['id'], name=f.get('name') or old.get('name'),
                    definition=f.get('definition') or old.get('definition'),
                    product_branch=f.get('product_branch') if f.get('product_branch') is not None else old.get('product_branch'),
                    discovered=discovered, confirmed=bool(f.get('confirm') or old.get('confirmed') or not discovered),
                    update=update)
    if op == 'channel-status':
        status = f['status']
        proof = dict(verified_candidate_results=verified_results(obj, f['channel'])) if status == 'verified' else {}
        return dict(object=identity, channel=f['channel'], status=status, quote=f['quote'],
                    reason=f.get('reason'), checks=proof)
    if op == 'coverage':
        return dict(object=identity, **{k: f[k] for k in ('statement', 'scope', 'budget', 'quote')})
    if op == 'candidate':
        data = read_bytes(f['xyz'], 1024 * 1024)
        count, composition = xyz(data)
        hashed = sha256(data).hexdigest()
        parent = dict(attempt=f.get('parent_attempt'), file=None)
        if parent['attempt'] is not None:
            catalog.record(root, parent['attempt'])
        if f.get('parent_file') is not None:
            parent['file'] = dict(source=str(f['parent_file']), sha256=file_hash(f['parent_file']))
        if f.get('si_location') is not None and not f.get('doi'):
            raise ValueError('--si-location requires --doi')
        literature = dict(doi=f['doi'], si_location=f.get('si_location')) if f.get('doi') else None
        event = dict(object=identity, id=f['id'], source=str(f['xyz']), file=f'catalog/candidates/{hashed}.xyz',
                     sha256=hashed, n_atoms=count, formula=composition, origin=f['origin'], parent=parent,
                     transform=read_json(f.get('transform_json')), target_channel=f.get('target_channel'),
                     literature=literature, note=f.get('note'))
        archive(root, event, data)
        archives.append((event, data))
        exp = obj['expected']['formula']
        checks['expected_formula'] = dict(state=exp['state'], expected=exp['value'], actual=composition,
                                          matches=(exp['value'] == composition) if exp['state'] == 'set' else None)
        checks['expected_charge'] = dict(state=obj['expected']['charge']['state'], checked=False,
                                         reason='未核对：XYZ does not encode charge')
        if exp['state'] == 'set' and exp['value'] != composition:
            warnings.append('WARNING: candidate formula differs from object expectation; registration allowed.')
        return event
    if op == 'candidate-result':
        identity_attempt = f.get('attempt')
        status = f.get('assign', 'none')
        proof = {}
        if identity_attempt is not None:
            path, (_, current, _) = catalog.record(root, identity_attempt)
            member = any(m['attempt'] == identity_attempt for m in obj['members'])
            if not member:
                warnings.append('WARNING: Attempt is not an object member; use catalog member explicitly.')
            if status == 'verified':
                if current['state'] != 'fetched':
                    raise ValueError('verified assignment requires a fetched Attempt')
                facts = catalog.read_facts(root, path)
                proof = dict(fetched=True, facts_readable=True, n_imag=facts.get('n_imag'), member=member)
        return dict(object=identity, candidate=f['candidate'], outcome=f['outcome'], attempt=identity_attempt,
                    diagnosis=read_json(f.get('diagnosis_json')), assignment=dict(status=status, channels=f.get('channel') or []),
                    quote=f.get('quote'), note=f.get('note'), checks=proof)
    raise ValueError(f'Unknown catalog operation: {op}')


def ledger(objects, identity, channel=None):
    obj = find(list(objects.values()), identity, 'object')
    initialize(obj)
    channels = [find(obj['channels'], channel, 'channel')] if channel else obj['channels']
    rows = [dict(channel=c['id'], status=c['status'],
                 candidates=[candidate for candidate in obj['candidates'] if candidate['id'] in c['candidate_ids']])
            for c in channels]
    assigned = {identity for c in obj['channels'] for identity in c['candidate_ids']}
    return dict(object=identity, channels=rows,
                unassigned=[] if channel else [c for c in obj['candidates'] if c['id'] not in assigned])


def print_tables(objects):
    def line(*values):
        print('\t'.join(str(value).replace('\t', ' ').replace('\n', ' ') for value in values))
    line('OBJECT', 'CHANNEL', 'STATUS', 'CANDIDATES', 'OUTCOMES', 'LATEST ATTEMPT')
    for obj in objects:
        for channel in obj.get('channels', []):
            results = [r for c in obj['candidates'] if c['id'] in channel['candidate_ids'] for r in c['results']]
            latest = max(results, key=lambda r: r['seq']) if results else {}
            line(obj['id'], channel['id'], channel['status'], len(channel['candidate_ids']),
                 json.dumps(channel['outcome_counts'], ensure_ascii=False), latest.get('attempt') or '-')
    line('OBJECT', 'CANDIDATE', 'ORIGIN', 'TARGET', 'LATEST OUTCOME', 'LATEST ASSIGNMENT')
    for obj in objects:
        for candidate in obj.get('candidates', []):
            line(obj['id'], candidate['id'], candidate['origin'], candidate['target_channel'] or '-',
                 candidate['results'][-1]['outcome'] if candidate['results'] else '-',
                 json.dumps(candidate['latest_assignment'], ensure_ascii=False))
