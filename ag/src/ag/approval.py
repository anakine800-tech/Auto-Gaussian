"""Local, bounded submission authorization; never authorizes cancellation.

Explicit records fail closed so an expired, changed or partly mismatched batch
cannot silently fall back to a dialog. O_EXCL consumption survives interruption.
The human origin of a quote is the caller's responsibility, not inferred here.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
import re
from uuid import uuid4

from ag import attempt, journal, state, study
from ag.config import cluster_name
from ag.locks import submission_lock


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Authorization time must be an ISO timestamp with timezone')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Invalid authorization timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Authorization timestamp requires a timezone')
    return parsed


def walltime_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2,4}:[0-5]\d:[0-5]\d', value):
        raise ValueError('Authorization walltime must be positive HH:MM:SS')
    hours, minutes, seconds = map(int, value.split(':'))
    total = hours * 3600 + minutes * 60 + seconds
    if not total:
        raise ValueError('Authorization walltime must be positive HH:MM:SS')
    return total


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def exclusive_write(root, path, data):
    target = study.local_path(root, path)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def entry(manifest):
    return dict(attempt_id=manifest['attempt_id'], bundle_sha256=manifest['bundle_sha256'],
                cluster=manifest.get('cluster', 'default'), cores=manifest['cores'])


def validate_record(value, approval_id, *, now=None):
    now = now or datetime.now(timezone.utc)
    keys = {'schema', 'id', 'created_at', 'expires_at', 'quote', 'study_id',
            'attempts', 'total_cores', 'used'}
    if not isinstance(value, dict) or set(value) != keys or value['schema'] != 'ag-approval/1':
        raise ValueError('Invalid approval record format')
    if value['id'] != study.identifier(approval_id) or value['used'] is not None:
        raise ValueError('Approval identity mismatch or already used')
    study.identifier(value['study_id'])
    if not isinstance(value['quote'], str) or not value['quote'].strip():
        raise ValueError('Approval quote must not be empty')
    created, expires = timestamp(value['created_at']), timestamp(value['expires_at'])
    if not created <= now < expires or not timedelta(0) < expires - created <= timedelta(hours=24):
        raise ValueError('Approval expired or invalid validity period (maximum 24 hours)')
    entries = value['attempts']
    if not isinstance(entries, list) or not entries:
        raise ValueError('Approval requires Attempts')
    ids = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {'attempt_id', 'bundle_sha256', 'cluster', 'cores'}:
            raise ValueError('Invalid approval Attempt format')
        study.identifier(item['attempt_id'])
        cluster_name(item['cluster'])
        if (item['attempt_id'] in ids or type(item['cores']) is not int or item['cores'] < 1
                or not isinstance(item['bundle_sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', item['bundle_sha256'])):
            raise ValueError('Invalid approval Attempt identity, cores or hash')
        ids.add(item['attempt_id'])
    if type(value['total_cores']) is not int or value['total_cores'] != sum(i['cores'] for i in entries):
        raise ValueError('Invalid approval total_cores')
    return value


def create(cfg, study_name, ids, quote, hours=24):
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError('Approval quote must not be empty; preserve the human words verbatim')
    if type(hours) not in (int, float) or not math.isfinite(hours) or not 0 < hours <= 24:
        raise ValueError('Approval hours must be positive and at most 24')
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Expected unique Attempt IDs')
    root = study.locate(cfg, study_name)
    with submission_lock(cfg):
        entries = []
        for id_ in ids:
            path = attempt.find(cfg, id_)
            if path.parent.parent != root:
                raise ValueError('All approved Attempts must belong to the requested study')
            if state.read(path)['state'] != 'prepared' or (path / '.submit-claim').exists():
                raise ValueError('Only unconsumed prepared Attempts can be approved')
            entries.append(entry(attempt.read_manifest(path)))
        now = datetime.now(timezone.utc)
        value = dict(schema='ag-approval/1', id='approval-' + uuid4().hex,
                     created_at=now.isoformat(), expires_at=(now + timedelta(hours=hours)).isoformat(),
                     quote=quote, study_id=root.name, attempts=entries,
                     total_cores=sum(e['cores'] for e in entries), used=None)
        validate_record(value, value['id'], now=now)
        directory = study.local_path(root, root / 'approvals')
        directory.mkdir(exist_ok=True)
        exclusive_write(root, directory / (value['id'] + '.json'), json_bytes(value))
        journal.append(root, 'approve', detail={'approval_id': value['id'], 'quote': quote,
                                              'attempts': ids, 'record_sha256': digest(value)})
    return value


def read_record(root, approval_id):
    study.identifier(approval_id)
    path = study.local_path(root, root / 'approvals' / (approval_id + '.json'))
    marker = study.local_path(root, path.with_suffix('.used'))
    if marker.exists():
        raise ValueError('Approval already used')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Approval record missing or unreadable') from exc
    return validate_record(value, approval_id)


def check_record(root, value, prepared):
    if value['study_id'] != root.name:
        raise ValueError('Approval study mismatch')
    entries = {i['attempt_id']: i for i in value['attempts']}
    for path, manifest, _ in prepared:
        if (path.parent.parent != root or manifest['study_id'] != value['study_id']
                or entries.get(manifest['attempt_id']) != entry(manifest)):
            raise ValueError('Approval Attempt, bundle SHA-256, cluster, cores or study mismatch')


def authorize(cfg, prepared, *, approval_id=None, policy_name=None):
    if approval_id is not None and policy_name is not None:
        raise ValueError('Choose either --approval or --policy')
    authorization = dict(method='dialog', approval_id=None, policy_name=None,
                         quote=None, rule_sha256=None)
    if approval_id is not None:
        root = prepared[0][0].parent.parent
        value = read_record(root, approval_id)
        check_record(root, value, prepared)
        authorization.update(method='approval', approval_id=approval_id, quote=value['quote'],
                             record_sha256=digest(value))
    elif policy_name is not None:
        # Legacy policies do not bind an immutable plan or its method exception.
        # A matching template/core allowance must never grant relaxed autonomy.
        if any('input_validation' in m for _, m, _ in prepared):
            raise ValueError('Relaxed inputs cannot use legacy standing policies; plan-bound integration is required')
        from ag.config import validate_approval
        validate_approval(cfg)
        policy = cfg.get('approval', {}).get('policies', {}).get(policy_name)
        if policy is None:
            raise ValueError('Approval policy does not exist')
        for _, m, _ in prepared:
            if (m['study_id'] not in policy['studies'] or m['template'] not in policy['templates']
                    or m.get('cluster', 'default') not in policy['clusters']
                    or m['cores'] > policy['max_cores_per_job']
                    or walltime_seconds(m['walltime']) > walltime_seconds(policy['max_walltime'])):
                raise ValueError('Approval policy study, template, cluster, cores or walltime mismatch')
        authorization.update(method='policy', policy_name=policy_name,
                             quote=policy['quote'], rule_sha256=digest(policy))
    return authorization


def consume(cfg, prepared, authorization):
    # Recheck expiry and the complete batch after inventory/summary generation;
    # no Attempt in a changed batch may reach remote writes.
    current = authorize(cfg, prepared, approval_id=authorization['approval_id'],
                        policy_name=authorization['policy_name'])
    if current != authorization:
        raise ValueError('Authorization changed before submission')
    if authorization['method'] == 'approval':
        root = prepared[0][0].parent.parent
        approval_id = authorization['approval_id']
        value = dict(schema='ag-approval-used/1', id=approval_id, used_at=journal.now(),
                     attempts=[m['attempt_id'] for _, m, _ in prepared],
                     record_sha256=authorization['record_sha256'])
        exclusive_write(root, root / 'approvals' / (approval_id + '.used'), json_bytes(value))


def archive(path, authorization, summary):
    value = dict(schema='ag-submission-summary/1', attempt_id=path.name,
                 manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest(),
                 authorization=authorization, summary=summary)
    exclusive_write(path.parent.parent, path / 'submission-summary.json', json_bytes(value))
    journal.append(path.parent.parent, 'submit_authorization', path.name,
                   detail=dict(authorization, summary_file='submission-summary.json'))
