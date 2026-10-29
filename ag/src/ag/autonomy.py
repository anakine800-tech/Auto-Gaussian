"""Purely local autonomous-run bookkeeping, not submission authorization.

Journal replay prevents counter resets after crashes. A fresh lease token
fences a resumed old process; pause is serialized only with short local IO.
No remote operation, scheduler, scientific verdict or automatic retry lives
here. Consumers must recheck at their action boundary, not cache check().
"""
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from ag import __version__, study
from ag import _autonomy_store as disk

RUN_SECONDS = 60 * 60
LEASE_SECONDS = 90 * 60
COUNTERS = ('attempt', 'remedy', 'cancel', 'reroute')
ACTIONS = ('prepare', 'submit', 'remedy', 'cancel', 'reroute', 'observe', 'fetch', 'organize')
READ_ACTIONS = ('observe', 'fetch', 'organize')
SUBMISSION_FIELDS = {'attempt_id', 'object_id', 'failure_class', 'ownership_sha256',
                     'round_id', 'run_id', 'plan_sha256', 'rule_sha256', 'max_attempts'}


class _SubmissionLimit(ValueError):
    """A verified round cannot consume more submissions without human review."""


class PublicationRefused(ValueError):
    """An observation lost its verified owner before final local publication."""


def now():
    return datetime.now(timezone.utc).timestamp()


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be nonempty text')
    return value


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid autonomy time or duration')
    return value


def versions():
    # Adapt facts.ag_provenance's checkout check, with optional index writes
    # disabled: the public check command must remain read-only.
    root = Path(__file__).resolve().parents[3]
    result = dict(ag_version=__version__, git_commit=None, dirty=None)
    try:
        def git(*args):
            return subprocess.run(['git', '-C', str(root), *args], check=True,
                                  capture_output=True, text=True, timeout=10,
                                  env=dict(os.environ, GIT_OPTIONAL_LOCKS='0')).stdout.strip()
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('Not an ag checkout')
        result.update(git_commit=git('rev-parse', 'HEAD'), dirty=bool(git(
            'status', '--porcelain', '--untracked-files=normal', '--', 'ag/src', 'ag/pyproject.toml')))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    for package in ('rdkit', 'goodvibes'):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def validate_versions(value):
    if (not isinstance(value, dict)
            or set(value) != {'ag_version', 'git_commit', 'dirty', 'rdkit', 'goodvibes'}
            or not isinstance(value['git_commit'], str)
            or not re.fullmatch(r'[0-9a-f]{40,64}', value['git_commit'])
            or type(value['dirty']) is not bool):
        raise ValueError('Cannot verify actual ag checkout version')
    for key in ('ag_version', 'rdkit', 'goodvibes'):
        text(value[key], key)
    if value['dirty']:
        raise ValueError('Plan requires a clean ag source checkout so its commit identifies the code')


def validate_plan(plan):
    if set(plan) != {'id', 'created_at', 'versions', 'spec'}:
        raise ValueError('Invalid autonomy plan fields')
    study.identifier(plan['id'])
    number(plan['created_at'])
    validate_versions(plan['versions'])
    spec = plan['spec']
    required = {
            'goal', 'comparison_groups', 'method_policy', 'mechanism_scope',
            'system_rules', 'estimated_hours', 'attempt_limit', 'valid_until'}
    if (not isinstance(spec, dict) or not required <= set(spec)
            or set(spec) - required - {'submission_policy'}):
        raise ValueError('Plan requires goal, groups, method, mechanism, system rules, time and limits')
    if 'submission_policy' in spec:
        from ag.autonomy_policy import validate_plan_bounds
        validate_plan_bounds(spec['submission_policy'])
    for key in ('goal', 'method_policy', 'mechanism_scope'):
        text(spec[key], key)
    groups = spec['comparison_groups']
    if not isinstance(groups, list) or not groups:
        raise ValueError('comparison_groups must be a nonempty list')
    for group in groups:
        text(group, 'comparison group')
    if not isinstance(spec['system_rules'], dict) or set(spec['system_rules']) != {'main', 'small'}:
        raise ValueError('system_rules requires main and small criteria')
    for rule in spec['system_rules'].values():
        text(rule, 'system rule')
    if number(spec['estimated_hours']) <= 0:
        raise ValueError('estimated_hours must be positive')
    if type(spec['attempt_limit']) is not int or spec['attempt_limit'] < 1:
        raise ValueError('attempt_limit must be a positive integer')
    if number(spec['valid_until']) <= plan['created_at']:
        raise ValueError('Plan validity must end after creation')


def initial():
    return dict(schema='ag-autonomy/1', phase='ended', paused=False, plans={},
                current_plan=None, current_round=None, rounds={}, lease=None, runs={},
                summary='', pending=[], objects={},
                totals=dict.fromkeys(COUNTERS, 0), counts={}, updated_at=0)


def idle(state):
    if state['lease'] is not None:
        raise ValueError('End the current run before changing plans')


def bound_plan(state, plan_id, current_versions, at, *, observation=False):
    plan = state['plans'][plan_id]
    if not plan['confirmation']:
        raise ValueError('Plan needs explicit human confirmation')
    if plan['body']['versions'] != current_versions:
        raise ValueError('Plan versions differ from the actual runtime; create and confirm a new plan')
    # Expiry stops new calculation actions, but must not strand evidence from
    # jobs already submitted. Observation still requires the original confirmed
    # plan, toolchain and a separately current wake lease.
    if not observation and at >= plan['body']['spec']['valid_until']:
        raise ValueError('Plan expired')
    return plan


def owner(state, run_id, token_hash, at):
    lease = state['lease']
    if not lease or lease['run_id'] != run_id or lease['token_sha256'] != token_hash:
        raise ValueError('Stale or incorrect run owner')
    if at < lease['started_at'] or at >= lease['run_until'] or at >= lease['expires_at']:
        raise ValueError('Run has reached its 60 minute limit; lease takeover is available at 90 minutes')
    return lease


def eligible(state, run_id, token_hash, current_versions, at, action, expected_sha=None, *, intent_limit=True):
    if action not in ACTIONS:
        raise ValueError('Unknown autonomy action')
    lease = owner(state, run_id, token_hash, at)
    if lease.get('observe_only', False) and action not in READ_ACTIONS:
        raise ValueError('Observe-only lease cannot authorize new actions')
    plan = bound_plan(state, state['current_plan'], current_versions, at,
                      observation=action in READ_ACTIONS)
    if expected_sha is not None and expected_sha != plan['sha256']:
        raise ValueError('Plan hash mismatch')
    if state['phase'] == 'ended' or (state['paused'] and action not in READ_ACTIONS):
        raise ValueError('Autonomy is paused or ended; new actions are blocked')
    if (intent_limit and action == 'prepare'
            and state['rounds'][state['current_round']]['totals']['attempt'] >= plan['body']['spec']['attempt_limit']):
        raise ValueError('Local Attempt intent limit reached; actual submissions still require reconciliation')
    return plan


def _sha256(value, label):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError(label + ' requires SHA-256')
    return value


def _submission_record(state, data, at):
    """Validate real reservation consumption; intent counters are not evidence."""
    if set(data) != {'record', 'token_sha256', 'versions'}:
        raise ValueError('Invalid submission consumption event')
    record = data['record']
    if not isinstance(record, dict) or set(record) != SUBMISSION_FIELDS:
        raise ValueError('Invalid submission consumption fields')
    for key in ('attempt_id', 'object_id', 'round_id', 'run_id'):
        study.identifier(record[key])
    for key in ('ownership_sha256', 'plan_sha256', 'rule_sha256'):
        _sha256(record[key], key)
    failure = record['failure_class']
    if failure is not None:
        text(failure, 'failure_class')
        if failure != failure.strip():
            raise ValueError('failure_class must use its exact canonical spelling')
    plan = eligible(state, record['run_id'], data['token_sha256'], data['versions'],
                    at, 'submit', record['plan_sha256'])
    if record['round_id'] != state['current_round']:
        raise ValueError('Submission reservation belongs to another round')
    maximum = record['max_attempts']
    if type(maximum) is not int or not 1 <= maximum <= plan['body']['spec']['attempt_limit']:
        raise ValueError('Submission rule limit exceeds the confirmed plan')
    submissions = state.get('submissions', {})
    if record['attempt_id'] in submissions:
        raise ValueError('Attempt already consumed; never submit it again')
    if any(saved['ownership_sha256'] == record['ownership_sha256'] for saved in submissions.values()):
        raise ValueError('Immutable ownership record already consumed')
    consumed = [saved for saved in submissions.values() if saved['round_id'] == record['round_id']]
    if len(consumed) >= maximum:
        raise _SubmissionLimit('Actual round submission limit reached')
    if len(consumed) * 10 >= maximum * 9:
        raise _SubmissionLimit('Actual round submission count reached 90%; pause required')
    if failure is not None and sum(saved['object_id'] == record['object_id']
            and saved['failure_class'] == failure for saved in consumed) >= 2:
        raise ValueError('Object already consumed two remedies for this failure class')
    return record, len(consumed) + 1, maximum


def _submission_reference(state, data, at, *, dispatch):
    required = {'attempt_id', 'ownership_sha256', 'round_id', 'run_id',
                'plan_sha256', 'token_sha256', 'versions'}
    if not dispatch:
        required.add('reason')
    if set(data) != required:
        raise ValueError('Invalid submission outcome event')
    action = 'submit' if dispatch else 'organize'
    eligible(state, data['run_id'], data['token_sha256'], data['versions'], at,
             action, data['plan_sha256'])
    saved = state.get('submissions', {}).get(data['attempt_id'])
    if saved is None or any(saved[key] != data[key] for key in (
            'ownership_sha256', 'round_id', 'run_id', 'plan_sha256')):
        raise ValueError('Submission outcome does not match its consumed reservation')
    if saved['dispatch_started'] is not None or saved['aborted_before_dispatch'] is not None:
        raise ValueError('Submission dispatch or abort already recorded; preserve the reservation')
    if not dispatch:
        text(data['reason'], 'Exact reason submission was not dispatched')
    return saved


def apply(previous, event):
    """Validate and replay every transition, including ownership and counters."""
    op, at, data = event['op'], number(event['at']), event['data']
    if not isinstance(data, dict):
        raise ValueError('Invalid autonomy event data')
    if previous is None:
        if op != 'init' or data:
            raise ValueError('Autonomy journal must start with init')
        state = initial()
    else:
        state = deepcopy(previous)
        if at < state['updated_at']:
            raise ValueError('Autonomy clock moved backwards')
        if op == 'plan':
            idle(state)
            body = data['body']
            validate_plan(body)
            if body['created_at'] != at or body['id'] in state['plans']:
                raise ValueError('Duplicate or inconsistent plan')
            if data['sha256'] != sha256(disk.encode(body)).hexdigest():
                raise ValueError('Plan hash mismatch')
            state['plans'][body['id']] = dict(body=body, sha256=data['sha256'], confirmation=None)
        elif op == 'confirm':
            idle(state)
            plan = state['plans'][data['plan_id']]
            if plan['confirmation'] or data['sha256'] != plan['sha256']:
                raise ValueError('Plan already confirmed or hash mismatch')
            if data['versions'] != plan['body']['versions'] or at >= plan['body']['spec']['valid_until']:
                raise ValueError('Plan expired or versions changed')
            text(data['quote'], 'Human confirmation quote')
            plan['confirmation'] = dict(at=at, quote=data['quote'], sha256=data['sha256'])
        elif op == 'begin':
            idle(state)
            if state['phase'] != 'ended':
                raise ValueError('End the current authorization round before explicitly beginning another')
            plan = bound_plan(state, data['plan_id'], data['versions'], at)
            text(data['quote'], 'Explicit human confirmation of a new authorization round')
            round_id = study.identifier(data['round_id'])
            if round_id in state['rounds']:
                raise ValueError('Authorization round identity already used')
            state['rounds'][round_id] = dict(started_at=at, ended_at=None, quote=data['quote'],
                plan_ids=[data['plan_id']], initial_plan_sha256=plan['sha256'],
                totals=dict.fromkeys(COUNTERS, 0))
            state['current_round'] = round_id
            state['current_plan'] = data['plan_id']
            state['phase'] = 'paused' if state['paused'] else 'running'
        elif op == 'start':
            observe_only = data.get('observe_only', False)
            if type(observe_only) is not bool:
                raise ValueError('observe_only must be a boolean')
            if observe_only and data['plan_id'] != state['current_plan']:
                raise ValueError('Observe-only lease requires the current round and current plan')
            bound_plan(state, data['plan_id'], data['versions'], at, observation=observe_only)
            if state['phase'] == 'ended' or state['current_round'] is None:
                raise ValueError('Authorization round ended; explicit begin with human confirmation is required')
            old = state['lease']
            if old:
                if at < old['expires_at']:
                    raise ValueError('Another run holds the lease')
                text(data['takeover_reason'], 'Explicit takeover reason')
                if data['previous_lease'] != old:
                    raise ValueError('Takeover evidence mismatch')
                state['runs'][old['run_id']]['ended_at'] = at
                state['runs'][old['run_id']]['outcome'] = 'expired-takeover'
            elif data['previous_lease'] is not None or data['takeover_reason'] is not None:
                raise ValueError('No expired lease to take over')
            run_id = study.identifier(data['run_id'])
            if run_id in state['runs'] or not re.fullmatch('[0-9a-f]{64}', data['token_sha256']):
                raise ValueError('Invalid or reused run identity')
            text(data['owner'], 'owner')
            state['lease'] = dict(run_id=run_id, round_id=state['current_round'], owner=data['owner'], token_sha256=data['token_sha256'],
                                  started_at=at, run_until=at + RUN_SECONDS, expires_at=at + LEASE_SECONDS)
            state['runs'][run_id] = dict(owner=data['owner'], plan_id=data['plan_id'], round_id=state['current_round'], started_at=at,
                                         ended_at=None, outcome=None, totals=dict.fromkeys(COUNTERS, 0))
            # Omit the optional field for ordinary starts, including replay of
            # old events: changing historical state shapes breaks verification.
            if observe_only:
                state['lease']['observe_only'] = True
                state['runs'][run_id]['observe_only'] = True
            plans = state['rounds'][state['current_round']]['plan_ids']
            if data['plan_id'] not in plans:
                plans.append(data['plan_id'])
            state['current_plan'] = data['plan_id']
            state['phase'] = 'paused' if state['paused'] else 'running'
        elif op == 'pause':
            text(data['reason'], 'Pause reason')
            state['paused'] = True
            if state['phase'] != 'ended':
                state['phase'] = 'paused'
        elif op == 'manual_takeover':
            if set(data) != {'previous_lease', 'writer_id', 'study_key', 'reason'}:
                raise ValueError('Invalid manual takeover evidence')
            old = state['lease']
            if (not state['paused'] or state['phase'] != 'paused' or old is None
                    or old != data['previous_lease'] or at < old['expires_at']):
                raise ValueError('Manual takeover requires a paused round and an exactly expired lease')
            if not isinstance(data['writer_id'], str) or not re.fullmatch('[0-9a-f]{32}', data['writer_id']):
                raise ValueError('Invalid manual writer identity')
            _sha256(data['study_key'], 'Manual writer study key')
            text(data['reason'], 'Manual takeover reason')
            state['runs'][old['run_id']].update(ended_at=at, outcome='manual-takeover')
            state['lease'] = None
        elif op == 'submission_consume':
            record, consumed, maximum = _submission_record(state, data, at)
            state.setdefault('submissions', {})[record['attempt_id']] = dict(
                record, plan_id=state['current_plan'], at=at,
                owner_token_sha256=data['token_sha256'],
                dispatch_started=None, aborted_before_dispatch=None)
            if consumed * 10 >= maximum * 9:
                # This reservation remains consumed, but cannot dispatch after
                # this pause. The caller records a pre-dispatch abort and keeps
                # its historical Attempt count; there is no final-job exception.
                state['paused'] = True
                state['phase'] = 'paused'
                state['submission_pause'] = dict(at=at, attempt_id=record['attempt_id'],
                    round_id=record['round_id'], reason='Actual round submission count reached 90%')
        elif op in ('submission_dispatch', 'submission_abort'):
            dispatch = op == 'submission_dispatch'
            saved = _submission_reference(state, data, at, dispatch=dispatch)
            if dispatch:
                saved['dispatch_started'] = {'at': at}
            else:
                saved['aborted_before_dispatch'] = {'at': at, 'reason': data['reason']}
        elif op == 'submission_boundary_failure':
            if set(data) != {'attempt_id', 'ownership_sha256', 'run_id', 'token_sha256', 'dispatched', 'reason'}:
                raise ValueError('Invalid submission boundary failure event')
            saved = state.get('submissions', {}).get(data['attempt_id'])
            if (saved is None or saved['ownership_sha256'] != data['ownership_sha256']
                    or saved['run_id'] != data['run_id']
                    or saved['owner_token_sha256'] != data['token_sha256']):
                raise ValueError('Submission failure must belong to its original reservation owner')
            if (type(data['dispatched']) is not bool
                    or data['dispatched'] != (saved['dispatch_started'] is not None)):
                raise ValueError('Submission failure contradicts the durable dispatch boundary')
            text(data['reason'], 'Submission boundary failure reason')
            if 'boundary_failure' in saved:
                raise ValueError('Submission boundary failure already recorded')
            saved['boundary_failure'] = {'at': at, 'dispatched': data['dispatched'], 'reason': data['reason']}
            if not data['dispatched'] and saved['aborted_before_dispatch'] is None:
                saved['aborted_before_dispatch'] = {'at': at, 'reason': data['reason']}
            state['paused'] = True
            if state['phase'] != 'ended':
                state['phase'] = 'paused'
        elif op == 'waiting':
            if set(data) != {'object_id', 'record_sha256', 'round_id', 'run_id',
                             'plan_sha256', 'token_sha256', 'versions'}:
                raise ValueError('Invalid waiting observation event')
            study.identifier(data['object_id'])
            _sha256(data['record_sha256'], 'Waiting evidence')
            eligible(state, data['run_id'], data['token_sha256'], data['versions'],
                     at, 'submit', data['plan_sha256'])
            if data['round_id'] != state['current_round']:
                raise ValueError('Waiting observation belongs to another round')
            waiting = state.setdefault('waiting', [])
            if any(row['run_id'] == data['run_id'] and row['object_id'] == data['object_id'] for row in waiting):
                raise ValueError('Object already has a waiting observation in this wake')
            waiting.append({key: data[key] for key in (
                'object_id', 'record_sha256', 'round_id', 'run_id', 'plan_sha256')})
            waiting[-1].update(plan_id=state['current_plan'], at=at)
        elif op in ('resume', 'finish', 'end', 'update', 'count', 'recover'):
            if op == 'end' and state['lease'] is None:
                if data['run_id'] is not None or data['token_sha256'] is not None:
                    raise ValueError('No current wake lease; do not reuse a former run identity')
            elif op == 'recover' and data['run_id'] is None and data['token_sha256'] is None:
                old = state['lease']
                if data['previous_lease'] != old:
                    raise ValueError('Recovery lease evidence mismatch')
                if old:
                    if at < old['expires_at']:
                        raise ValueError('Recovery without the owner must wait for lease expiry')
                    state['runs'][old['run_id']].update(ended_at=at, outcome='expired-recovered')
                    state['lease'] = None
            else:
                owner(state, data['run_id'], data['token_sha256'], at)
            if op in ('resume', 'count') and state['lease'].get('observe_only', False):
                raise ValueError('Observe-only lease cannot resume or count new actions')
            if op == 'recover':
                text(data['reason'], 'Recovery reason')
            elif op == 'finish':
                text(data['reason'], 'Finish reason')
                run = state['runs'][data['run_id']]
                run.update(ended_at=at, outcome='finished')
                state['lease'] = None
            elif op == 'end':
                text(data['reason'], 'Explicit end of authorization round')
                if state['phase'] == 'ended' or state['current_round'] is None:
                    raise ValueError('Authorization round is already ended')
                if data['round_id'] != state['current_round']:
                    raise ValueError('Authorization round changed; stale end request rejected')
                if state['lease']:
                    state['runs'][state['lease']['run_id']].update(ended_at=at, outcome='round-ended')
                state['rounds'][state['current_round']]['ended_at'] = at
                state['lease'] = None
                state['phase'] = 'ended'
            elif op == 'resume':
                bound_plan(state, state['current_plan'], data['versions'], at)
                text(data['reason'], 'Explicit resume reason')
                if not state['paused']:
                    raise ValueError('Autonomy is not paused')
                state['paused'] = False
                state['phase'] = 'running'
            elif op == 'update':
                eligible(state, data['run_id'], data['token_sha256'], data['versions'], at, 'organize')
                if not isinstance(data['summary'], str) or not isinstance(data['pending'], list) or not isinstance(data['objects'], dict):
                    raise ValueError('Update requires summary text, pending list and objects mapping')
                for item in data['pending']:
                    text(item, 'Pending decision')
                for key in data['objects']:
                    study.identifier(key)
                state.update(summary=data['summary'], pending=data['pending'], objects=data['objects'])
            else:
                kind = data['kind']
                if kind not in COUNTERS:
                    raise ValueError('Invalid counter kind')
                eligible(state, data['run_id'], data['token_sha256'], data['versions'], at,
                         'prepare' if kind == 'attempt' else kind)
                request_id = study.identifier(data['request_id'])
                if request_id in state['counts']:
                    raise ValueError('Duplicate count event in journal')
                study.identifier(data['object_id'])
                text(data['failure_class'], 'failure_class')
                text(data['evidence'], 'Local intent reference (not submission proof)')
                state['counts'][request_id] = dict(data, plan_id=state['current_plan'], round_id=state['current_round'], at=at)
                state['totals'][kind] += 1
                state['rounds'][state['current_round']]['totals'][kind] += 1
                state['runs'][data['run_id']]['totals'][kind] += 1
        else:
            raise ValueError('Unknown autonomy event')
    state['updated_at'] = at
    return state


def load(store, *, allow_stale=False):
    snapshot, stale = store.load(apply, allow_stale=allow_stale)
    for plan in snapshot['state']['plans'].values():
        raw = store.read('plan-' + plan['body']['id'] + '.json')
        if sha256(raw).hexdigest() != plan['sha256'] or raw != disk.encode(plan['body']):
            raise ValueError('Immutable autonomy plan was changed')
    return snapshot, stale


def public(snapshot):
    result = deepcopy(snapshot)
    state = result['state']
    if state['lease']:
        state['lease'].pop('token_sha256')
    for count in state['counts'].values():
        count.pop('token_sha256')
    for record in state.get('submissions', {}).values():
        record.pop('owner_token_sha256')
    plan = state['plans'].get(state['current_plan'])
    state['plan_sha256'] = plan['sha256'] if plan else None
    state['versions'] = plan['body']['versions'] if plan else None
    result['submission_counts_verified'] = False
    result['integration'] = 'local state only; actual submission counts require immutable ownership audit'
    return result


def initialize(cfg, name):
    from ag.autonomy_submission import machine_lock
    with machine_lock():
        _require_no_manual_writer(cfg, name)
        with disk.locked(cfg, name, write=True, initialize=True) as store:
            return public(store.commit(None, 'init', now(), {}, apply))


def create_plan(cfg, name, spec):
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        at = now()
        body = dict(id=uuid4().hex, created_at=at, versions=versions(), spec=spec)
        data = dict(body=body, sha256=sha256(disk.encode(body)).hexdigest())
        # Validate before publishing any plan bytes; orphan files are never adopted.
        apply(snapshot['state'], dict(op='plan', at=at, data=data))
        store.exclusive('plan-' + body['id'] + '.json', disk.encode(body))
        store.commit(snapshot, 'plan', at, data, apply)
        return dict(plan_id=body['id'], sha256=data['sha256'], plan=body, confirmed=False)


def confirm(cfg, name, plan_id, plan_sha256, quote):
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        return public(store.commit(snapshot, 'confirm', now(), dict(plan_id=plan_id,
                      sha256=plan_sha256, quote=quote, versions=versions()), apply))


def begin(cfg, name, plan_id, quote):
    # The same machine lock surrounds manual prepare/submit. It closes the
    # gap where a new round could begin just after a manual-write guard checked.
    from ag.autonomy_submission import machine_lock
    with machine_lock():
        _require_no_manual_writer(cfg, name)
        with disk.locked(cfg, name, write=True) as store:
            snapshot, _ = load(store)
            data = dict(plan_id=plan_id, quote=quote, round_id=uuid4().hex, versions=versions())
            return public(store.commit(snapshot, 'begin', now(), data, apply))


def start(cfg, name, plan_id, owner_name, *, takeover_reason=None, recover=False, observe_only=False):
    if type(observe_only) is not bool:
        raise ValueError('observe_only must be a boolean')
    from ag.autonomy_submission import machine_lock
    with machine_lock():
        _require_no_manual_writer(cfg, name)
        return _start(cfg, name, plan_id, owner_name, takeover_reason=takeover_reason,
                      recover=recover, observe_only=observe_only)


def _start(cfg, name, plan_id, owner_name, *, takeover_reason, recover, observe_only):
    with disk.locked(cfg, name, write=True) as store:
        snapshot, stale = load(store, allow_stale=recover)
        old = snapshot['state']['lease']
        if stale and (not old or takeover_reason is None):
            raise ValueError('Stale state requires current-owner recover or expired-lease takeover')
        token, run_id = uuid4().hex, uuid4().hex
        data = dict(plan_id=plan_id, owner=owner_name, run_id=run_id,
                    token_sha256=sha256(token.encode()).hexdigest(), versions=versions(),
                    takeover_reason=takeover_reason, previous_lease=old,
                    recovered_stale_state=stale)
        if observe_only:
            data['observe_only'] = True
        result = public(store.commit(snapshot, 'start', now(), data, apply))
        result.update(run_id=run_id, token=token)
        return result


def pause(cfg, name, reason):
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        return public(store.commit(snapshot, 'pause', now(), dict(reason=reason), apply))


def pause_if_current_owner(cfg, name, run_id, token, reason):
    """An expired owner may report a stop, but cannot pause its successor."""
    if not isinstance(token, str) or not token:
        return False
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        lease = snapshot['state']['lease']
        if (lease is None or lease['run_id'] != run_id
                or lease['token_sha256'] != sha256(token.encode()).hexdigest()):
            return False
        store.commit(snapshot, 'pause', now(), dict(reason=reason), apply)
        return True


def change(cfg, name, op, run_id, token, **fields):
    if op not in ('update', 'resume', 'finish', 'end', 'count', 'recover'):
        raise ValueError('Invalid run operation')
    from ag.autonomy_submission import machine_lock
    with machine_lock() if op == 'resume' else nullcontext():
        if op == 'resume':
            _require_no_manual_writer(cfg, name)
        return _change(cfg, name, op, run_id, token, **fields)


def _change(cfg, name, op, run_id, token, **fields):
    with disk.locked(cfg, name, write=True) as store:
        snapshot, stale = load(store, allow_stale=op == 'recover')
        data = dict(fields, run_id=run_id, token_sha256=sha256(token.encode()).hexdigest() if token else None)
        if op not in ('finish', 'end', 'recover'):
            data['versions'] = versions()
        at = now()
        inactive_end = op == 'end' and snapshot['state']['lease'] is None
        if not inactive_end and (op != 'recover' or run_id is not None or token is not None):
            owner(snapshot['state'], run_id, data['token_sha256'], at)
        if op in ('resume', 'count') and snapshot['state']['lease'].get('observe_only', False):
            raise ValueError('Observe-only lease cannot resume or count new actions')
        if op == 'count' and fields.get('request_id') in snapshot['state']['counts']:
            saved = snapshot['state']['counts'][fields['request_id']]
            if {k: v for k, v in saved.items() if k not in ('plan_id', 'round_id', 'at')} != data:
                raise ValueError('Count request ID reused with different content or run')
            # An acknowledgement only; no action eligibility or counter increment.
            return dict(public(snapshot), duplicate=True)
        if op == 'recover':
            lease = snapshot['state']['lease']
            if not stale and not (lease and at >= lease['expires_at'] and run_id is None and token is None):
                raise ValueError('State is current; no recovery needed')
            data['previous_lease'] = lease
        return public(store.commit(snapshot, op, at, data, apply))


def status(cfg, name):
    with disk.locked(cfg, name) as store:
        snapshot, _ = load(store)
        return public(snapshot)


class _SubmissionGuard:
    """A short local transaction; never retain this object for remote IO."""
    def __init__(self, store, run_id, token, plan_sha256):
        if not isinstance(token, str) or not token:
            raise ValueError('Submission requires the current owner token')
        self._store = store
        self._run_id = study.identifier(run_id)
        self._token_hash = sha256(token.encode()).hexdigest()
        self._plan_sha256 = _sha256(plan_sha256, 'Expected immutable plan')
        self._active = True
        self._snapshot = None

    @property
    def snapshot(self):
        if not self._active:
            raise ValueError('Submission guard is closed; re-enter at the next action boundary')
        return deepcopy(self._snapshot['state'])

    def _recheck(self, action):
        if not self._active:
            raise ValueError('Submission guard is closed; re-enter at the next action boundary')
        self._snapshot, _ = load(self._store)
        current_versions = versions()
        at = now()
        current = self._snapshot['state']
        if at < current['updated_at']:
            raise ValueError('Autonomy clock moved backwards')
        self._store.verify_lock()
        # A returning stale process cannot use its obsolete token to pause or
        # consume against the replacement holder's current actions.
        owner(current, self._run_id, self._token_hash, at)
        try:
            # Actual preparation uses audited submission consumption at its
            # publication boundary. Preserve intent limits only for legacy
            # count/check and journal replay, never as a second live budget.
            eligible(current, self._run_id, self._token_hash, current_versions,
                     at, action, self._plan_sha256, intent_limit=action != 'prepare')
        except ValueError:
            plan = current['plans'][current['current_plan']]
            invalid = (plan['sha256'] != self._plan_sha256
                       or plan['body']['versions'] != current_versions
                       or at >= plan['body']['spec']['valid_until'])
            if action not in READ_ACTIONS and invalid and not current['paused']:
                self._snapshot = self._store.commit(self._snapshot, 'pause', at,
                    {'reason': 'Submission boundary rejected: plan hash, runtime versions or plan validity changed'}, apply)
            raise
        return at, current_versions

    def check_current(self, action='submit'):
        """Recheck after local validation, immediately before its side effect."""
        self._recheck(action)
        return self.snapshot

    def consume(self, record):
        at, current_versions = self._recheck('submit')
        data = dict(record=deepcopy(record), token_sha256=self._token_hash, versions=current_versions)
        if not isinstance(record, dict) or record.get('run_id') != self._run_id:
            raise ValueError('Reservation run differs from the current submission guard')
        try:
            self._snapshot = self._store.commit(self._snapshot, 'submission_consume', at, data, apply)
        except _SubmissionLimit as exc:
            self._snapshot = self._store.commit(self._snapshot, 'pause', at, {'reason': str(exc)}, apply)
            raise
        return deepcopy(self._snapshot)

    def validate_consume(self, record):
        """Reject known limits before publishing any immutable reservation."""
        at, current_versions = self._recheck('submit')
        if not isinstance(record, dict) or record.get('run_id') != self._run_id:
            raise ValueError('Reservation run differs from the current submission guard')
        _submission_record(self._snapshot['state'], dict(record=deepcopy(record),
            token_sha256=self._token_hash, versions=current_versions), at)

    def pause(self, reason):
        at, _ = self._recheck('organize')
        self._snapshot = self._store.commit(self._snapshot, 'pause', at, {'reason': reason}, apply)
        return deepcopy(self._snapshot)

    def _outcome(self, attempt_id, *, dispatch, reason=None):
        at, current_versions = self._recheck('submit' if dispatch else 'organize')
        saved = self._snapshot['state'].get('submissions', {}).get(study.identifier(attempt_id))
        if saved is None:
            raise ValueError('No consumed submission reservation for this Attempt')
        data = dict(attempt_id=attempt_id, ownership_sha256=saved['ownership_sha256'],
                    round_id=self._snapshot['state']['current_round'], run_id=self._run_id,
                    plan_sha256=self._plan_sha256, token_sha256=self._token_hash, versions=current_versions)
        if not dispatch:
            data['reason'] = reason
        self._snapshot = self._store.commit(self._snapshot,
            'submission_dispatch' if dispatch else 'submission_abort', at, data, apply)
        return deepcopy(self._snapshot)

    def dispatch_started(self, attempt_id):
        """Persist immediately before the one scheduler call, never afterwards."""
        return self._outcome(attempt_id, dispatch=True)

    def abort_before_dispatch(self, attempt_id, reason):
        """The live owner may close an undispatched reservation even if paused."""
        return self._outcome(attempt_id, dispatch=False, reason=reason)

    def waiting(self, object_id, record_sha256):
        """Bind one complete no-placement selection per object and wake."""
        at, current_versions = self._recheck('submit')
        data = dict(object_id=object_id, record_sha256=record_sha256,
                    round_id=self._snapshot['state']['current_round'], run_id=self._run_id,
                    plan_sha256=self._plan_sha256, token_sha256=self._token_hash, versions=current_versions)
        self._snapshot = self._store.commit(self._snapshot, 'waiting', at, data, apply)
        return deepcopy(self._snapshot)


@contextmanager
def submission_guard(cfg, name, run_id, token, *, plan_sha256):
    """Recheck and consume under a short study mutex, NEVER across remote IO.

    The caller must already hold the machine-wide submission lock, reconcile
    immutable ownership evidence and actual global usage, and re-enter for each
    remote side-effect boundary. This guard does not authenticate caller dicts.
    """
    with disk.locked(cfg, name, write=True) as store:
        guard = _SubmissionGuard(store, run_id, token, plan_sha256)
        try:
            guard._recheck('submit')
            yield guard
        finally:
            guard._active = False


def boundary_failure(cfg, name, attempt_id, ownership_sha256, *, run_id, token, dispatched, reason):
    """Record only an existing owner's outcome after pause/expiry/lost lease.

    Caller holds the machine submission lock. The original secret token binds
    this exact consumed Attempt, not the current lease. It cannot authorize any
    new work, abort a dispatched request, or alter another owner's reservation.
    A dispatched UNKNOWN always remains reserved, including after a takeover.
    """
    if not isinstance(token, str) or not token:
        raise ValueError('Submission failure requires the original owner token')
    data = dict(attempt_id=attempt_id, ownership_sha256=ownership_sha256, run_id=run_id,
                token_sha256=sha256(token.encode()).hexdigest(), dispatched=dispatched, reason=reason)
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        at = now()
        saved = snapshot['state'].get('submissions', {}).get(attempt_id)
        if saved is not None and 'boundary_failure' in saved:
            previous = saved['boundary_failure']
            if (saved['ownership_sha256'] == ownership_sha256 and saved['run_id'] == run_id
                    and saved['owner_token_sha256'] == data['token_sha256']
                    and type(dispatched) is bool and previous['dispatched'] == dispatched
                    and previous['reason'] == reason):
                return public(snapshot)  # acknowledgement, never another write or permit
        return public(store.commit(snapshot, 'submission_boundary_failure', at, data, apply))


@contextmanager
def manual_write_guard(cfg, name, *, action=None, attempt_ids=None):
    """Register a manual operation without holding a study/machine mutex over IO.

    A paused round admits manual writes only without a live 90-minute lease.
    The durable claim excludes begin/start/resume until completion or an
    explicit human release of an abandoned writer registration.
    An individual claim lock distinguishes concurrent legacy manual work from a
    crashed writer; an abandoned or damaged claim is never silently cleared.
    """
    from ag.autonomy_submission import machine_lock, study_identity
    if action is not None:
        if attempt_ids is None:
            attempt_ids = []
        elif isinstance(attempt_ids, list):
            attempt_ids = list(attempt_ids)
        _manual_action(action, attempt_ids)
    elif attempt_ids is not None:
        raise ValueError('Manual writer Attempt IDs require an action')
    writerfd = None
    try:
        with machine_lock():
            root = study.locate(cfg, name)
            identity = study_identity(root)
            directory = study.local_path(root, root / 'autonomy')
            present = os.path.lexists(directory)
            with disk.locked(cfg, name, write=True) if present else nullcontext() as store:
                snapshot = load(store)[0] if store else None
                state = snapshot['state'] if snapshot else None
                at = number(now())
                takeover = False
                if state:
                    if at < state['updated_at']:
                        raise ValueError('Autonomy clock moved backwards')
                    if state['phase'] not in ('ended', 'paused'):
                        raise ValueError('Pause the active autonomous round before manual writes')
                    lease = state['lease']
                    if lease:
                        if state['phase'] != 'paused' or at < lease['expires_at']:
                            raise ValueError('A live autonomous lease excludes manual writes until 90 minutes')
                        takeover = True
                with disk.manual_writers(identity['study_key'], create=True) as writers:
                    records = _manual_writer_records(writers, root, identity)
                    if state and state['phase'] != 'ended' and any(not row['closed'] for row in records.values()):
                        raise ValueError('An in-flight manual writer already owns the paused study')
                    writer_id = uuid4().hex
                    claim = dict(schema='ag-manual-writer/1', writer_id=writer_id,
                                 study_path=str(root), started_at=at, **identity)
                    if action is not None:
                        claim.update(schema='ag-manual-writer/2', action=action,
                                     attempt_ids=list(attempt_ids or []))
                    raw = disk.encode(claim)
                    filename = writer_id + '.claim.json'
                    writers.exclusive(filename, raw)
                    writerfd = writers.open(filename, os.O_RDONLY)
                    fcntl.flock(writerfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # A failed journal/state publish leaves the claim unfinished.
                    # Its released claim lock will require explicit inspection.
                    if takeover:
                        store.commit(snapshot, 'manual_takeover', at, dict(previous_lease=lease,
                            writer_id=writer_id, study_key=identity['study_key'],
                            reason='Manual write took over the paused study after the 90-minute lease expired'), apply)
        try:
            yield dict(writer_id=writer_id, study_key=identity['study_key'], manual_takeover=takeover)
        finally:
            with machine_lock():
                if study_identity(root) != identity:
                    raise ValueError('Manual writer study directory identity changed')
                with disk.manual_writers(identity['study_key']) as writers:
                    if writers is None:
                        raise ValueError('Manual writer registry disappeared; preserve evidence')
                    records = _manual_writer_records(writers, root, identity)
                    row = records.get(writer_id)
                    named = os.stat(filename, dir_fd=writers.fd, follow_symlinks=False)
                    held = os.fstat(writerfd)
                    if (row is None or row['closed'] or row['raw'] != raw
                            or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)):
                        raise ValueError('Manual writer claim changed; preserve evidence')
                    finished_at = number(now())
                    if finished_at < claim['started_at']:
                        raise ValueError('Manual writer clock moved backwards')
                    writers.exclusive(writer_id + '.complete.json', disk.encode(dict(
                        schema='ag-manual-writer-complete/1', writer_id=writer_id,
                        claim_sha256=sha256(raw).hexdigest(), finished_at=finished_at)))
    finally:
        if writerfd is not None:
            os.close(writerfd)


def _manual_action(action, attempt_ids):
    if action not in ('prepare', 'submit', 'fetch', 'cancel', 'status', 'snapshot', 'facts'):
        raise ValueError('Invalid manual writer action')
    if not isinstance(attempt_ids, list) or any(not isinstance(value, str) for value in attempt_ids):
        raise ValueError('Manual writer Attempt IDs must be a list')
    if len(set(attempt_ids)) != len(attempt_ids):
        raise ValueError('Manual writer Attempt IDs must be unique')
    for value in attempt_ids:
        study.identifier(value)


def _manual_writer_records(store, root, identity, *, allow_stale=False):
    """Validate immutable claims and their outcomes; caller holds the machine lock."""
    if store is None:
        return {}
    records = {}
    for filename in os.listdir(store.fd):
        match = re.fullmatch(r'([0-9a-f]{32})\.(claim|complete|release)\.json', filename)
        if not match:
            raise ValueError('Unknown manual writer evidence; preserve files for inspection')
        raw = store.read(filename)
        value = disk.decode(raw)
        if not isinstance(value, dict) or disk.encode(value) != raw:
            raise ValueError('Damaged manual writer evidence; preserve files for inspection')
        writer_id, kind = match.groups()
        if value.get('writer_id') != writer_id:
            raise ValueError('Manual writer identity mismatch')
        row = records.setdefault(writer_id, {})
        row[kind] = value
        if kind == 'claim':
            row['raw'] = raw
    for writer_id, row in records.items():
        claim = row.get('claim')
        fields = {'schema', 'writer_id', 'study_path', 'started_at', *identity}
        if claim and claim.get('schema') == 'ag-manual-writer/2':
            fields |= {'action', 'attempt_ids'}
        if (not claim or set(claim) != fields
                or claim['schema'] not in ('ag-manual-writer/1', 'ag-manual-writer/2') or claim['study_path'] != str(root)
                or any(type(claim[key]) is not type(value) or claim[key] != value for key, value in identity.items())):
            raise ValueError('Manual writer study binding changed or claim is missing')
        if claim['schema'] == 'ag-manual-writer/2':
            _manual_action(claim['action'], claim['attempt_ids'])
        number(claim['started_at'])
        completion = row.get('complete')
        release = row.get('release')
        if completion is not None and release is not None:
            raise ValueError('Manual writer has conflicting completion and release evidence')
        if completion is not None:
            if (set(completion) != {'schema', 'writer_id', 'claim_sha256', 'finished_at'}
                    or completion['schema'] != 'ag-manual-writer-complete/1'
                    or completion['claim_sha256'] != sha256(row['raw']).hexdigest()
                    or number(completion['finished_at']) < claim['started_at']):
                raise ValueError('Manual writer completion does not match its claim')
            row['state'] = 'completed'
        elif release is not None:
            if (set(release) != {'schema', 'writer_id', 'claim_sha256', 'released_at', 'quote'}
                    or release['schema'] != 'ag-manual-writer-release/1'
                    or release['claim_sha256'] != sha256(row['raw']).hexdigest()
                    or number(release['released_at']) < claim['started_at']):
                raise ValueError('Manual writer release does not match its claim')
            text(release['quote'], 'Verbatim human writer release confirmation')
            row['state'] = 'released'
        else:
            fd = store.open(writer_id + '.claim.json', os.O_RDONLY)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    row['state'] = 'active'
                else:
                    row['state'] = 'stale'
                    if not allow_stale:
                        raise ValueError('Unfinished manual writer has no live owner; inspect manual-writers and explicitly release-writer')
            finally:
                os.close(fd)
        row['complete'] = completion
        row['release'] = release
        row['closed'] = completion is not None or release is not None
    return records


def _require_no_manual_writer(cfg, name):
    """Called under machine_lock before init/begin/start/resume obtains a lease."""
    from ag.autonomy_submission import study_identity
    root = study.locate(cfg, name)
    identity = study_identity(root)
    with disk.manual_writers(identity['study_key']) as store:
        if any(not row['closed'] for row in _manual_writer_records(store, root, identity).values()):
            raise ValueError('An in-flight manual writer excludes autonomous progression')


def manual_writers(cfg, name):
    """Read exact manual writer evidence; never initialize or repair records."""
    from ag.autonomy_submission import machine_lock, study_identity
    root = study.locate(cfg, name)
    identity = study_identity(root)
    result = dict(study_key=identity['study_key'], writers=[])
    with ExitStack() as stack:
        try:
            stack.enter_context(machine_lock(create=False))
        except FileNotFoundError:
            if os.path.lexists(Path.home() / '.config' / 'ag' / 'manual-writers'):
                raise ValueError('Manual writer evidence exists but its machine mutex is missing')
            return result
        with disk.manual_writers(identity['study_key']) as store:
            records = _manual_writer_records(store, root, identity, allow_stale=True)
            for writer_id, row in sorted(records.items()):
                claim = row['claim']
                item = dict(writer_id=writer_id, state=row['state'], claim_sha256=sha256(row['raw']).hexdigest(),
                            action=claim.get('action'), attempt_ids=claim.get('attempt_ids', []),
                            started_at=claim['started_at'])
                if row['complete']:
                    item['finished_at'] = row['complete']['finished_at']
                if row['release']:
                    item.update(released_at=row['release']['released_at'], quote=row['release']['quote'])
                result['writers'].append(item)
    return result


def release_writer(cfg, name, writer_id, quote):
    """Close one abandoned manual claim, never an Attempt or job reservation."""
    from ag.autonomy_submission import machine_lock, study_identity
    if not isinstance(writer_id, str) or not re.fullmatch('[0-9a-f]{32}', writer_id):
        raise ValueError('Exact manual writer ID is required')
    text(quote, 'Verbatim human writer release confirmation')
    with machine_lock(create=False):
        root = study.locate(cfg, name)
        identity = study_identity(root)
        with disk.manual_writers(identity['study_key']) as store:
            records = _manual_writer_records(store, root, identity, allow_stale=True)
            row = records.get(writer_id)
            if row is None:
                raise ValueError('Exact manual writer claim not found')
            if row['state'] != 'stale':
                raise ValueError('Only a stale manual writer without a live claim lock can be released')
            fd = store.open(writer_id + '.claim.json', os.O_RDONLY)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError('Active manual writer cannot be released') from exc
                raw = store.read(writer_id + '.claim.json')
                named = os.stat(writer_id + '.claim.json', dir_fd=store.fd, follow_symlinks=False)
                held = os.fstat(fd)
                if raw != row['raw'] or (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino):
                    raise ValueError('Manual writer claim changed during release')
                at = number(now())
                if at < row['claim']['started_at']:
                    raise ValueError('Manual writer clock moved backwards')
                value = dict(schema='ag-manual-writer-release/1', writer_id=writer_id,
                             claim_sha256=sha256(raw).hexdigest(), released_at=at, quote=quote)
                store.exclusive(writer_id + '.release.json', disk.encode(value))
            finally:
                os.close(fd)
    return dict(writer_id=writer_id, study_key=identity['study_key'], state='released',
                claim_sha256=value['claim_sha256'], scope='Manual writer registration only',
                effect='Does not resume the round, alter Attempts or UNKNOWN, release job reservations, or permit resubmission')


@contextmanager
def action_guard(cfg, name, run_id, token, *, action, plan_sha256):
    """Hold only across a short local claim/decision, NEVER remote IO.

    A returned snapshot is not a permit. Future integrations must re-enter at
    each action boundary and reconcile immutable Attempt evidence separately.
    Pause and takeover serialize with this guard; they never wait for a run.
    Do not nest another autonomy API here (it would acquire a second flock).
    """
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        current_versions = versions()
        at = now()
        if not isinstance(plan_sha256, str) or not re.fullmatch('[0-9a-f]{64}', plan_sha256):
            raise ValueError('Expected immutable plan SHA-256 is required')
        if at < snapshot['state']['updated_at']:
            raise ValueError('Autonomy clock moved backwards')
        eligible(snapshot['state'], run_id, sha256(token.encode()).hexdigest(),
                 current_versions, at, action, plan_sha256)
        store.verify_lock()
        yield public(snapshot)


@contextmanager
def observation_publication_guard(cfg, name, run_id, token, *, action, plan_sha256):
    """Fence final local publication only; network and parsing stay outside.

    Plan expiry permits observation of existing work, but current ownership,
    confirmation, tool versions and the 60-minute wake limit still apply.
    Errors raised by the publication body retain their original type.
    """
    from ag.autonomy_submission import machine_lock
    with ExitStack() as stack:
        try:
            if action not in READ_ACTIONS:
                raise ValueError('Observation publication accepts read actions only')
            text(token, 'Observation owner token')
            _sha256(plan_sha256, 'Expected immutable plan')
            stack.enter_context(machine_lock(create=False))
            store = stack.enter_context(disk.locked(cfg, name, write=True))
            snapshot, _ = load(store)
            current_versions = versions()
            at = number(now())
            if at < snapshot['state']['updated_at']:
                raise ValueError('Autonomy clock moved backwards')
            eligible(snapshot['state'], run_id, sha256(token.encode()).hexdigest(), current_versions,
                     at, action, plan_sha256)
            store.verify_lock()
        except (ValueError, OSError) as exc:
            raise PublicationRefused(str(exc)) from exc
        yield deepcopy(snapshot['state'])


def check(cfg, name, run_id, token, *, action, plan_sha256):
    with action_guard(cfg, name, run_id, token, action=action, plan_sha256=plan_sha256) as result:
        return dict(result, eligible_now=True, action=action)


def input_json(value):
    path = Path(value).absolute()
    fd = disk.directory(path.parent)
    try:
        return disk.decode(disk.Store(fd).read(path.name))
    finally:
        os.close(fd)


def run(args):
    cfg, name, op = args.config, args.study, args.action
    if op == 'init':
        result = initialize(cfg, name)
    elif op == 'plan':
        result = create_plan(cfg, name, input_json(args.input))
    elif op == 'confirm':
        result = confirm(cfg, name, args.plan, args.sha256, args.quote)
    elif op == 'begin':
        result = begin(cfg, name, args.plan, args.quote)
    elif op == 'start':
        result = start(cfg, name, args.plan, args.owner, takeover_reason=args.takeover_reason,
                       recover=args.recover, observe_only=args.observe_only)
    elif op == 'pause':
        result = pause(cfg, name, args.reason)
    elif op == 'status':
        result = status(cfg, name)
    elif op == 'manual-writers':
        result = manual_writers(cfg, name)
    elif op == 'release-writer':
        result = release_writer(cfg, name, args.writer_id, args.quote)
    elif op == 'scientific-review':
        from ag import attempt, autonomy_submission
        path = attempt.find(cfg, args.attempt)
        if path.parent.parent.name != name:
            raise ValueError('Scientific review Attempt belongs to another study')
        result = autonomy_submission.write_scientific_review(cfg, path, run_id=args.run,
            token=args.token, plan_sha256=args.plan_sha256, object_id=args.object_id,
            outcome=args.outcome, reason=args.reason, mode_review=args.mode_review)
    elif op == 'check':
        result = check(cfg, name, args.run, args.token, action=args.for_action, plan_sha256=args.sha256)
    else:
        fields = {}
        if op in ('resume', 'finish', 'end', 'recover'):
            fields['reason'] = args.reason
            if op == 'end':
                fields['round_id'] = args.round
        elif op == 'update':
            fields = input_json(args.input)
            if not isinstance(fields, dict) or set(fields) != {'summary', 'pending', 'objects'}:
                raise ValueError('Update input must contain only summary, pending and objects')
        else:
            fields = {k: getattr(args, k) for k in ('kind', 'request_id', 'object_id', 'failure_class', 'evidence')}
        result = change(cfg, name, op, args.run, args.token, **fields)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def register(subparsers):
    p = subparsers.add_parser('autonomy', help='Purely local plan, run lease, pause and journal (no submission)')
    children = p.add_subparsers(dest='action', required=True)
    for op in ('init', 'plan', 'confirm', 'begin', 'start', 'pause', 'resume', 'finish', 'end', 'update', 'count', 'recover', 'status', 'check', 'manual-writers', 'release-writer', 'scientific-review'):
        child = children.add_parser(op)
        child.set_defaults(func=run)
        child.add_argument('--study', required=True)
        child.add_argument('--json', action='store_true', help='JSON output (also the default)')
        if op in ('plan', 'update'):
            child.add_argument('--input', required=True, help='Local JSON input file')
        if op in ('confirm', 'begin', 'start'):
            child.add_argument('--plan', required=True)
        if op in ('confirm', 'check'):
            child.add_argument('--sha256', required=True, help='Expected immutable plan SHA-256')
        if op in ('confirm', 'begin'):
            child.add_argument('--quote', required=True, help=(
                'Verbatim human confirmation of a NEW authorization round and budget; NOT submission approval'
                if op == 'begin' else 'Verbatim human plan confirmation; NOT submission approval'))
        if op == 'release-writer':
            child.add_argument('--writer-id', required=True, help='Exact stale manual writer ID from manual-writers')
            child.add_argument('--quote', required=True, help=(
                'Verbatim human confirmation to release ONLY this abandoned writer registration; '
                'does not resume autonomy or change job reservations, UNKNOWN or single-submit protection'))
        if op == 'scientific-review':
            child.add_argument('--attempt', required=True)
            child.add_argument('--run', required=True)
            child.add_argument('--token', required=True)
            child.add_argument('--plan-sha256', required=True)
            child.add_argument('--object-id', required=True)
            child.add_argument('--outcome', choices=('ts_zero_imaginary', 'ts_wrong_mode'), required=True)
            child.add_argument('--reason', required=True, help='Scientific reasoning, pending human confirmation')
            child.add_argument('--mode-review', help='Existing source-bound mode review report; required for wrong direction')
        if op == 'start':
            child.add_argument('--owner', required=True, help='Session identity')
            child.add_argument('--observe-only', action='store_true', help=(
                'Acquire a lease only for observing, fetching and organizing the current plan; '
                'plan expiry is allowed, but confirmation, versions and lease limits still apply'))
            child.add_argument('--takeover-reason', help='Explicit reason to take over an expired lease')
            child.add_argument('--recover', action='store_true', help='Replay a verified stale snapshot during expired takeover')
        if op in ('pause', 'resume', 'finish', 'end', 'recover'):
            child.add_argument('--reason', required=True)
        if op == 'end':
            child.add_argument('--round', required=True, help='Expected authorization round ID; stale end requests are rejected')
        if op in ('resume', 'finish', 'end', 'update', 'count', 'recover', 'check'):
            child.add_argument('--run', required=op not in ('recover', 'end'))
            child.add_argument('--token', required=op not in ('recover', 'end'))
        if op == 'check':
            child.add_argument('--for-action', choices=ACTIONS, required=True)
        if op == 'count':
            child.add_argument('--kind', choices=COUNTERS, required=True)
            for field in ('request-id', 'object-id', 'failure-class', 'evidence'):
                child.add_argument('--' + field, required=True)
