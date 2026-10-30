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
    if not isinstance(spec, dict) or set(spec) != {
            'goal', 'comparison_groups', 'method_policy', 'mechanism_scope',
            'system_rules', 'estimated_hours', 'attempt_limit', 'valid_until'}:
        raise ValueError('Plan requires goal, groups, method, mechanism, system rules, time and limits')
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


def bound_plan(state, plan_id, current_versions, at):
    plan = state['plans'][plan_id]
    if not plan['confirmation']:
        raise ValueError('Plan needs explicit human confirmation')
    if plan['body']['versions'] != current_versions:
        raise ValueError('Plan versions differ from the actual runtime; create and confirm a new plan')
    if at >= plan['body']['spec']['valid_until']:
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
    owner(state, run_id, token_hash, at)
    plan = bound_plan(state, state['current_plan'], current_versions, at)
    if expected_sha is not None and expected_sha != plan['sha256']:
        raise ValueError('Plan hash mismatch')
    if state['phase'] == 'ended' or (state['paused'] and action not in READ_ACTIONS):
        raise ValueError('Autonomy is paused or ended; new actions are blocked')
    if action not in READ_ACTIONS and _pending_cancellations(state):
        raise ValueError('Unresolved cancellation consumption blocks new actions; observe or record its result')
    if (action == 'prepare'
            and state['rounds'][state['current_round']]['totals']['attempt'] >= plan['body']['spec']['attempt_limit']):
        raise ValueError('Local Attempt intent limit reached; actual submissions still require reconciliation')
    return plan


def _pending_cancellations(state):
    """An in-flight or crashed cancellation never becomes available capacity."""
    results = state.get('cancellation_results', {})
    return [key for key in state.get('cancellations', {}) if key not in results]


def _cancellation_hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Cancellation evidence requires SHA-256')
    return value


def _cancellation_binding(value):
    from ag import remote
    from ag.config import cluster_name
    if not isinstance(value, dict) or set(value) != {
            'study_id', 'attempt_id', 'cluster', 'scheduler', 'job_id',
            'manifest_sha256', 'submission_sha256'}:
        raise ValueError('Invalid cancellation Attempt binding')
    for key in ('study_id', 'attempt_id'):
        study.identifier(value[key])
    cluster_name(value['cluster'])
    if value['scheduler'] not in ('pbs', 'slurm'):
        raise ValueError('Invalid cancellation scheduler')
    (remote.slurm_job_id if value['scheduler'] == 'slurm' else remote.job_id)(value['job_id'])
    for key in ('manifest_sha256', 'submission_sha256'):
        _cancellation_hash(value[key])


def _cancellation_result_origin(state, data):
    if set(data) != {'attempt_id', 'run_id', 'token_sha256', 'consumption_sha256',
                     'outcome', 'reason', 'evidence_sha256'}:
        raise ValueError('Invalid cancellation result fields')
    record = state.get('cancellations', {}).get(study.identifier(data['attempt_id']))
    if (record is None or data['run_id'] != record['run_id']
            or data['token_sha256'] != record['token_sha256']
            or data['consumption_sha256'] != record['consumption_sha256']):
        raise ValueError('Cancellation result does not match the original consumption')
    if data['outcome'] not in ('accepted', 'unknown'):
        raise ValueError('Cancellation result must be accepted or unknown; neither proves termination')
    text(data['reason'], 'Cancellation result reason')
    _cancellation_hash(data['evidence_sha256'])


def _cancellation_receipt(record, *, duplicate=False):
    record = deepcopy(record)
    record.pop('token_sha256', None)
    return dict(record=record, duplicate=duplicate, cancellation_authorized=False)


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
            if _pending_cancellations(state):
                state['paused'] = True
            state['phase'] = 'paused' if state['paused'] else 'running'
        elif op == 'start':
            bound_plan(state, data['plan_id'], data['versions'], at)
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
            plans = state['rounds'][state['current_round']]['plan_ids']
            if data['plan_id'] not in plans:
                plans.append(data['plan_id'])
            state['current_plan'] = data['plan_id']
            # A new wake cannot assume a previous process stopped before its
            # scheduler call. Keep the original consumption unresolved and
            # admit observations only; a late result never resumes the round.
            if _pending_cancellations(state):
                state['paused'] = True
            state['phase'] = 'paused' if state['paused'] else 'running'
        elif op == 'pause':
            text(data['reason'], 'Pause reason')
            state['paused'] = True
            if state['phase'] != 'ended':
                state['phase'] = 'paused'
        elif op == 'cancel_consume':
            if set(data) != {'run_id', 'token_sha256', 'versions', 'plan_sha256', 'round_id',
                             'binding', 'ownership_sha256', 'kind', 'reason', 'evidence_sha256',
                             'lineage_sha256'}:
                raise ValueError('Invalid cancellation consumption fields')
            _cancellation_binding(data['binding'])
            for key in ('plan_sha256', 'ownership_sha256', 'evidence_sha256'):
                _cancellation_hash(data[key])
            text(data['reason'], 'Cancellation reason')
            if data['kind'] not in ('no_progress', 'reroute'):
                raise ValueError('Invalid cancellation kind')
            if data['kind'] == 'reroute':
                _cancellation_hash(data['lineage_sha256'])
            elif data['lineage_sha256'] is not None:
                raise ValueError('Only reroute consumption has a lineage')
            eligible(state, data['run_id'], data['token_sha256'], data['versions'],
                     at, 'cancel', data['plan_sha256'])
            if data['round_id'] != state['current_round']:
                raise ValueError('Cancellation authorization round mismatch')
            records = state.setdefault('cancellations', {})
            attempt_id = data['binding']['attempt_id']
            if attempt_id in records:
                raise ValueError('Cancellation already consumed for this Attempt; never retry')
            if sum(row['run_id'] == data['run_id'] for row in records.values()) >= 2:
                raise ValueError('Cancellation limit of two per run reached')
            if data['kind'] == 'reroute':
                lineages = state.setdefault('reroute_lineages', {})
                if data['lineage_sha256'] in lineages:
                    raise ValueError('Reroute already consumed for this original lineage')
                lineages[data['lineage_sha256']] = attempt_id
            record = dict(deepcopy(data), at=at, seq=event['seq'])
            record['consumption_sha256'] = sha256(disk.encode(record)).hexdigest()
            records[attempt_id] = record
        elif op == 'cancel_result':
            _cancellation_result_origin(state, data)
            results = state.setdefault('cancellation_results', {})
            if data['attempt_id'] in results:
                raise ValueError('Cancellation result already recorded')
            results[data['attempt_id']] = dict(
                {k: v for k, v in data.items() if k != 'token_sha256'}, at=at, seq=event['seq'])
            if data['outcome'] == 'unknown':
                state['paused'] = True
                if state['phase'] != 'ended':
                    state['phase'] = 'paused'
        elif op == 'snapshot':
            # Only capture_for_run registers freshly captured formal snapshots.
            # This is observation provenance, never submission ownership.
            eligible(state, data['run_id'], data['token_sha256'], data['versions'],
                     at, 'observe', data['plan_sha256'])
            if data['round_id'] != state['current_round']:
                raise ValueError('Snapshot authorization round mismatch')
            from ag.autonomy_cancel import validate_observation
            validate_observation(data, state['runs'][data['run_id']], at)
            if not 0 < data['capture_started_seq'] < event['seq']:
                raise ValueError('Invalid snapshot capture-start journal position')
            observations = state.setdefault('snapshots', {})
            key = data['binding']['attempt_id'] + '/' + data['snapshot']
            if key in observations:
                raise ValueError('Snapshot already registered; cannot reuse it in another wake')
            observations[key] = {k: v for k, v in data.items() if k not in ('token_sha256', 'versions')}
            observations[key]['seq'] = event['seq']
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
            if op == 'recover':
                text(data['reason'], 'Recovery reason')
                if _pending_cancellations(state):
                    state['paused'] = True
                    if state['phase'] != 'ended':
                        state['phase'] = 'paused'
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
                if _pending_cancellations(state):
                    raise ValueError('Unresolved cancellation consumption prevents resume')
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
    for record in state.get('cancellations', {}).values():
        record.pop('token_sha256')
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


def start(cfg, name, plan_id, owner_name, *, takeover_reason=None, recover=False):
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


class _CancellationGuard:
    """One local cancellation transaction, not an ownership verifier or permit."""
    def __init__(self, store, name, run_id, token, plan_sha256):
        self._store, self._name = store, name
        self._run_id = study.identifier(run_id)
        self._token_hash = sha256(text(token, 'Run token').encode()).hexdigest()
        self._plan_sha256 = _cancellation_hash(plan_sha256)
        self._snapshot, self._active = None, True

    def _require_active(self):
        if not self._active:
            raise ValueError('Cancellation guard is closed; re-enter at the action boundary')

    @property
    def current(self):
        self._require_active()
        return public(self._snapshot)

    @property
    def snapshot(self):
        self._require_active()
        return deepcopy(self._snapshot['state'])

    def recheck(self):
        self._require_active()
        self._snapshot, _ = load(self._store)
        current_versions = versions()
        at = number(now())
        if at < self._snapshot['state']['updated_at']:
            raise ValueError('Autonomy clock moved backwards')
        self._store.verify_lock()
        eligible(self._snapshot['state'], self._run_id, self._token_hash,
                 current_versions, at, 'cancel', self._plan_sha256)
        return at, current_versions

    def consume(self, *, binding, ownership_sha256, kind, reason, evidence_sha256,
                lineage_sha256=None):
        self._require_active()
        binding = deepcopy(binding)
        _cancellation_binding(binding)
        if binding['study_id'] != self._name:
            raise ValueError('Cancellation binding belongs to a different study')
        at, current_versions = self.recheck()
        data = dict(run_id=self._run_id, token_sha256=self._token_hash,
                    versions=current_versions, plan_sha256=self._plan_sha256,
                    round_id=self._snapshot['state']['current_round'], binding=binding,
                    ownership_sha256=ownership_sha256, kind=kind, reason=reason,
                    evidence_sha256=evidence_sha256, lineage_sha256=lineage_sha256)
        self._snapshot = self._store.commit(self._snapshot, 'cancel_consume', at, data, apply)
        return _cancellation_receipt(self._snapshot['state']['cancellations'][binding['attempt_id']])


@contextmanager
def _cancellation_guard(cfg, name, run_id, token, *, plan_sha256):
    """Hold one short study lock across verification, consumption and claim.

    The executor holds config/machine locks before entering and verifies real
    T186 ownership and evidence itself. Never nest another locking autonomy
    API or perform remote IO here. This guard grants no cancellation permit.
    """
    name = study.locate(cfg, name).name
    with disk.locked(cfg, name, write=True) as store:
        guard = _CancellationGuard(store, name, run_id, token, plan_sha256)
        try:
            guard.recheck()
            yield guard
        finally:
            guard._active = False


def _consume_cancellation(cfg, name, run_id, token, *, plan_sha256, binding,
                          ownership_sha256, kind, reason, evidence_sha256, lineage_sha256=None):
    """Internal bookkeeping only; caller assertions never verify ownership."""
    with _cancellation_guard(cfg, name, run_id, token, plan_sha256=plan_sha256) as guard:
        return guard.consume(binding=binding, ownership_sha256=ownership_sha256,
                             kind=kind, reason=reason, evidence_sha256=evidence_sha256,
                             lineage_sha256=lineage_sha256)


def _record_cancellation_result(cfg, name, run_id, token, *, attempt_id, consumption_sha256,
                                outcome, reason, evidence_sha256):
    """Record only the original consumer's late outcome, without new actions.

    Like a future T186 boundary-failure record, an in-flight outcome must remain
    recordable after pause, expiry or takeover. Original run/token and exact
    consumption bind it; it cannot replace a new lease, reopen a round, unpause
    or authorize execution. 'accepted' is not proof of termination.
    """
    with disk.locked(cfg, name, write=True) as store:
        snapshot, _ = load(store)
        at = now()
        if at < snapshot['state']['updated_at']:
            raise ValueError('Autonomy clock moved backwards')
        data = dict(attempt_id=attempt_id, run_id=run_id,
                    token_sha256=sha256(text(token, 'Original run token').encode()).hexdigest(),
                    consumption_sha256=consumption_sha256, outcome=outcome,
                    reason=reason, evidence_sha256=evidence_sha256)
        _cancellation_result_origin(snapshot['state'], data)
        saved = snapshot['state'].get('cancellation_results', {}).get(attempt_id)
        if saved is not None:
            if {k: v for k, v in saved.items() if k not in ('at', 'seq')} != {
                    k: v for k, v in data.items() if k != 'token_sha256'}:
                raise ValueError('Cancellation result reused with different content')
            return _cancellation_receipt(saved, duplicate=True)
        result = store.commit(snapshot, 'cancel_result', at, data, apply)
        return _cancellation_receipt(result['state']['cancellation_results'][attempt_id])


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
        result = start(cfg, name, args.plan, args.owner, takeover_reason=args.takeover_reason, recover=args.recover)
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
