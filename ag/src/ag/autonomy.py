"""Purely local autonomous-run bookkeeping, not submission authorization.

Journal replay prevents counter resets after crashes. A fresh lease token
fences a resumed old process; pause is serialized only with short local IO.
No remote operation, scheduler, scientific verdict or automatic retry lives
here. Consumers must recheck at their action boundary, not cache check().
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
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


def eligible(state, run_id, token_hash, current_versions, at, action, expected_sha=None):
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
    if (action == 'prepare'
            and state['rounds'][state['current_round']]['totals']['attempt'] >= plan['body']['spec']['attempt_limit']):
        raise ValueError('Local Attempt intent limit reached; actual submissions still require reconciliation')
    return plan


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
    plan = state['plans'].get(state['current_plan'])
    state['plan_sha256'] = plan['sha256'] if plan else None
    state['versions'] = plan['body']['versions'] if plan else None
    result['submission_counts_verified'] = False
    result['integration'] = 'local bookkeeping only; prepare/submit/cancel are not wired'
    return result


def initialize(cfg, name):
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
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        data = dict(plan_id=plan_id, quote=quote, round_id=uuid4().hex, versions=versions())
        return public(store.commit(snapshot, 'begin', now(), data, apply))


def start(cfg, name, plan_id, owner_name, *, takeover_reason=None, recover=False, observe_only=False):
    if type(observe_only) is not bool:
        raise ValueError('observe_only must be a boolean')
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


def change(cfg, name, op, run_id, token, **fields):
    if op not in ('update', 'resume', 'finish', 'end', 'count', 'recover'):
        raise ValueError('Invalid run operation')
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
    for op in ('init', 'plan', 'confirm', 'begin', 'start', 'pause', 'resume', 'finish', 'end', 'update', 'count', 'recover', 'status', 'check'):
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
