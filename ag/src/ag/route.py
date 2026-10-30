"""Advisory routing from local monitor snapshots; no transport or file writes."""
from datetime import datetime, timezone
from contextvars import ContextVar
from copy import deepcopy
import json
from pathlib import Path

from ag.config import (load_config, select_cluster, scheduler_kind, shared_clusters,
                       committed_cap, optional_resource_caps, validate_routing, RESOURCE_TIERS,
                       walltime_seconds)
from ag.capacity import assess
from ag.study import identifier


TEMPLATES = ('gaussian', 'gaussian-cp', 'multiwfn', 'crest', 'xtb')
TIERS = RESOURCE_TIERS
UNKNOWN = '快照非最新或缺字段'
READY, FULL, DENIED = '快照下容量足够', '需排队或容量未知', '不允许'
DISCLAIMER = '建议仅基于本机配置与已有快照，不保证实际启动时间。'
_CAPTURED_SNAPSHOTS = ContextVar('ag_route_captured_snapshots', default=None)


def _count(value):
    return type(value) is int and value >= 0


def _timestamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Missing timezone')
    return stamp.astimezone(timezone.utc)


def _snapshot(cfg, name, now):
    # Do not use monitor.cache_dir(): even a missing cache must stay read-only.
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    named, legacy = root / name / 'latest.json', root / 'latest.json'
    path = named if 'clusters' in cfg or name != 'default' else legacy
    data, stamp = None, None
    try:
        captured = _CAPTURED_SNAPSHOTS.get()
        if captured is None:
            if name == 'default' and named.exists() and legacy.exists():
                raise ValueError('Ambiguous default snapshots')
            if any(p.is_symlink() for p in (root.parent, root, path.parent, path)):
                raise ValueError('Redirected snapshot')
            with path.open('rb') as handle:
                raw = handle.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Oversize snapshot')
            data = json.loads(raw)
        else:
            # Both suggest and capacity.assess use this reader. A replay must
            # evaluate the saved original bytes, not a later latest.json file.
            data = deepcopy(captured.get(name))
        stamp = _timestamp(data['sampled_at'])
        if not _ladder_snapshot(cfg, name, data, now):
            raise ValueError('Failed, stale or invalid snapshot')
        return dict(data=data, sampled_at=stamp.isoformat(), fresh=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        # Never echo raw JSON, errors, node names, account names or paths.
        return dict(data=None, sampled_at=stamp.isoformat() if stamp else None, fresh=False)


def autonomous_selection(cfg, state, context, *, template, walltime,
                         parent_cluster=None, exclude_ownership=None, requested_tier=None):
    """Capture local evidence and invoke the reviewed ladder, under caller locks.

    There is no JSON-input escape hatch. The original monitor bytes, verified
    immutable submissions and replayed waiting events are the only inputs.
    The caller holds the machine submission lock through durable consumption.
    """
    import os
    from ag import autonomy, autonomy_submission, _autonomy_store as disk
    at = datetime.fromtimestamp(autonomy.now(), timezone.utc)
    name = context['study_id']
    scope = str(Path(cfg['local']['studies_root']) / name)
    study_key = autonomy_submission.study_identity(scope)['study_key']
    evidence = autonomy_submission.read_reservations(cfg, states={scope: state})
    placements = [p for p in evidence['placements']
                  if p['record_sha256'] != exclude_ownership]
    placements = _placement_records(cfg, placements)
    snapshots = {}
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    for cluster in cfg.get('clusters', {'default': cfg}):
        named, legacy = root / cluster / 'latest.json', root / 'latest.json'
        target = named if 'clusters' in cfg or cluster != 'default' else legacy
        try:
            if cluster == 'default' and named.exists() and legacy.exists():
                raise ValueError('Ambiguous monitor snapshot')
            fd = disk.directory(target.parent)
            try:
                with os.fdopen(disk.Store(fd).open(target.name, os.O_RDONLY), 'rb') as handle:
                    raw = handle.read(2 * 1024 * 1024 + 1)
            finally:
                os.close(fd)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Oversize monitor snapshot')
            snapshots[cluster] = disk.decode(raw)
        except FileNotFoundError:
            snapshots[cluster] = None
    # Waiting is established by a saved no-placement decision, never by a
    # model-provided timestamp or the presence of an object in an intent list.
    waiting_since, wakeups = autonomy_submission.waiting_history(cfg, state, name, context['object_id'])
    request = dict(template=template, job_class=context['job_class'], walltime=walltime, study_key=study_key,
                   study_id=name, round_id=state['current_round'], run_id=context['run_id'],
                   object_id=context['object_id'], waiting_since=waiting_since,
                   parent_cluster=parent_cluster)
    selector = select_ladder
    if template in ('crest', 'xtb'):
        selector = select_legacy
        request['tier'] = requested_tier
    result = selector(cfg, snapshots, **request, placements=placements,
                      wakeups=wakeups, batch_inputs=evidence['batch_inputs'], now=at)
    original = dict(config_sha256=ladder_config_identity(cfg), request=request,
                    snapshots=snapshots, placements=placements, wakeups=wakeups,
                    selected_at=at.isoformat())
    return dict(input=original, result=result)


def _own(snapshot):
    if not snapshot['fresh']:
        return None
    own = snapshot['data']['own']
    keys = ('cores_in_use', 'cores_running', 'cores_queued')
    if not all(_count(own.get(k)) for k in keys):
        return None
    if own['cores_in_use'] != own['cores_running'] + own['cores_queued']:
        return None
    return {k: own[k] for k in keys}


def _personal(selected, snapshots, cores):
    peers = shared_clusters(selected)
    candidates = [(snapshots[n]['sampled_at'], n, _own(snapshots[n])) for n in peers]
    candidates = [row for row in candidates if row[2] is not None]
    reasons = []
    if cores > selected['resources']['max_cores']:
        reasons.append('本人上限：超过单作业上限')
    if not candidates:
        reasons.append(f'{UNKNOWN}：本人占用未知')
        return False, reasons, None
    _, source, own = max(candidates)
    if own['cores_in_use'] + cores > committed_cap(selected):
        reasons.append('本人上限：运行加排队超过总上限')
    caps = optional_resource_caps(selected)
    for key, used, label in (
            ('max_queued_cores', own['cores_queued'], '排队上限'),
            ('scheduler_max_running_cores', own['cores_running'], '调度器运行限额')):
        if key in caps and used + cores > caps[key]:
            reasons.append(f'本人上限：超过{label}')
    return not reasons, reasons, source


def _walltime(resources, requested):
    """Compare with the configured limit; no limit means unknown, not unlimited."""
    maximum = resources.get('max_walltime')
    result = dict(requested=requested, maximum=maximum, status='not_checked')
    seconds = walltime_seconds(requested) if requested is not None else None
    if requested is None:
        note = '未核对任务时限（未提供 --walltime）'
        if maximum is None:
            note += '；入口未配置时限上限，不代表无限制'
    elif maximum is None:
        result['status'] = 'unknown_limit'
        note = '入口未配置 resources.max_walltime，调度器时限未知，不代表无限制'
    elif seconds > walltime_seconds(maximum):
        result['status'] = 'exceeded'
        note = '任务时限超过入口 resources.max_walltime'
    else:
        result['status'] = 'within_limit'
        note = '任务时限符合本机配置的入口上限'
    return result, note


def _enabled(selected, template):
    if template not in selected.get('allowed_templates', TEMPLATES):
        return False
    programs = selected.get('programs', {})
    if template in ('gaussian', 'gaussian-cp'):
        return bool(programs.get('gaussian', {}).get('g16root'))
    if template == 'multiwfn':
        # Preserve the existing renderer restriction; advice cannot enable a template.
        return (selected['_cluster'] == 'default' and scheduler_kind(selected) == 'pbs'
                and bool(programs.get('multiwfn')))
    xtb = bool(programs.get('xtb', {}).get('root'))
    return xtb or (template == 'crest' and bool(programs.get('crest', {}).get('executable')))


def suggest(cfg, template, tier, study=None, *, walltime=None, now=None, captured_snapshots=None):
    """Use the existing advice algorithm, optionally replaying captured data.

    The private context is per thread/task: it prevents a concurrent capture or
    replay from replacing another caller's snapshot source. No CLI accepts it.
    """
    if captured_snapshots is None:
        return _suggest(cfg, template, tier, study, walltime=walltime, now=now)
    token = _CAPTURED_SNAPSHOTS.set(deepcopy(captured_snapshots))
    try:
        return _suggest(cfg, template, tier, study, walltime=walltime, now=now)
    finally:
        _CAPTURED_SNAPSHOTS.reset(token)


def _suggest(cfg, template, tier, study=None, *, walltime=None, now=None):
    if template not in TEMPLATES or tier not in TIERS:
        raise ValueError('Unknown template or tier')
    if study is not None:
        identifier(study)
    if walltime is not None:
        walltime_seconds(walltime)
    validate_routing(cfg)
    now = now or datetime.now(timezone.utc)
    family = 'crest' if template in ('crest', 'xtb') else 'gaussian'
    routing = cfg.get('routing', {})
    order = routing.get('studies', {}).get(study, {}).get(family, routing.get(family))
    names = list(cfg.get('clusters', {'default': cfg}))
    snapshots = {name: _snapshot(cfg, name, now) for name in names}
    rows = []
    for name in dict.fromkeys([*(order or []), *sorted(names)]):
        selected = select_cluster(cfg, name)
        resource = selected['resources']['tiers'].get(tier)
        cores, memory = (resource['cores'], resource['mem_gb']) if resource else (None, None)
        snapshot = snapshots[name]
        time_check, time_note = _walltime(selected['resources'], walltime)
        row = dict(name=name, display_name=selected.get('display_name', name),
                   cores=cores, mem_gb=memory, conclusion=DENIED, reasons=[], notes=[],
                   sampled_at=snapshot['sampled_at'], snapshot_fresh=snapshot['fresh'],
                   personal_allowed=False, usage_source=None, in_order=name in (order or []),
                   specification_allowed=False, walltime=time_check)
        row['notes'].append(time_note)
        if resource is None:
            row['reasons'] = ['不支持该档位']
            rows.append(row)
            continue
        if not _enabled(selected, template):
            row['reasons'] = ['不允许该模板（入口限制或程序未配置）']
        elif time_check['status'] == 'exceeded':
            row['reasons'] = [time_note]
            row['notes'] = []
        else:
            row['specification_allowed'] = True
            allowed, reasons, source = _personal(selected, snapshots, cores)
            row.update(personal_allowed=allowed, usage_source=source)
            if not snapshot['fresh']:
                reasons.append(UNKNOWN)
            else:
                data = snapshot['data']
                summary = data['cluster'].get('job_summary')
                others = summary.get('others_queued_jobs') if isinstance(summary, dict) else None
                if not _count(others):
                    reasons.append(f'{UNKNOWN}：他人排队数量未知')
                elif others:
                    reasons.append('已有他人排队作业')
            capacity = assess(cfg, name, tier, now=now)
            if 'node_targeting' in selected:
                from ag.node_targeting import candidates
                targets = candidates(cfg, name, now=now)
                row['node_candidates'] = targets
                row['notes'].append('必须明确选择并确认目标节点；排序不授权自动选择')
                matches = [(n, o) for n in targets['nodes']
                           if n.get('selectable', n['status'] == 'available')
                           for o in n['options'] if o['tier'] == tier and o.get('selectable', True)]
                if template != 'gaussian' or not matches:
                    row['specification_allowed'] = False
                    capacity.update(availability='unknown', fits_total=None,
                                    reasons=['没有满足此档位的具名节点候选'])
                else:
                    # Only eligible mapped options can establish this entry's
                    # capacity. Reuse T157's T156 results, not unrelated nodes.
                    assessments = [o['capacity'] if 'capacity' in o else
                                   assess(cfg, name, tier, target_node=n['name'], now=now)
                                   for n, o in matches]
                    choice = next(a for state in ('enough', 'unknown', 'queue', 'not_applicable')
                                  for a in assessments if a['availability'] == state)
                    capacity.update({key: choice[key] for key in ('fits_total', 'availability', 'reasons')})
                capacity.update(sampled_at=targets.get('sampled_at', capacity['sampled_at']),
                                valid_until=targets.get('valid_until', capacity['valid_until']),
                                snapshot_fresh=targets.get('fresh', capacity['snapshot_fresh']))
            row['capacity'] = {key: capacity[key] for key in (
                'fits_total', 'availability', 'sampled_at', 'valid_until', 'snapshot_fresh', 'reasons')}
            if capacity['availability'] == 'enough':
                row['notes'].extend(capacity['reasons'])
            else:
                reasons.extend(capacity['reasons'])
            if capacity['availability'] == 'unknown':
                reasons.append(f'{UNKNOWN}：单节点容量未知')
            if capacity['availability'] == 'not_applicable':
                row['specification_allowed'] = False
            row.update(conclusion=FULL if reasons else READY, reasons=list(dict.fromkeys(reasons)))
        rows.append(row)
    eligible = [r for r in rows if r['in_order'] and r['personal_allowed']
                and r['specification_allowed']]
    chosen = next((r for r in eligible if r['conclusion'] == READY), None)
    queued = chosen is None
    chosen = chosen or next(iter(eligible), None)
    recommendation = None
    if chosen:
        recommendation = dict(name=chosen['name'], needs_queue=queued,
                              reason=('容量未知，建议核对后排队' if chosen['capacity']['availability'] == 'unknown'
                                      else '快照下建议排队') if queued else READY,
                              reasons=chosen['reasons'] + chosen['notes'])
    message = ('未配置路由顺序' if order is None else
               f"快照下建议排队：{chosen['name']}" if chosen and queued else
               f"建议：{chosen['name']}" if chosen else
               '无建议：顺序中没有规格适用且本人上限允许的入口')
    return dict(template=template, tier=tier, study=study, order=order, clusters=rows,
                recommendation=recommendation, message=message, walltime=walltime, notes=[DISCLAIMER])


def _digest(value):
    from hashlib import sha256
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _ladder_snapshot(cfg, name, data, now):
    """Validate in-memory evidence with the deployed monitor freshness rules."""
    try:
        interval = data['interval_seconds']
        return (data['schema'] == 'ag-monitor/1' and data['ok'] is True
                and not data.get('error') and not data.get('config_removed')
                and type(interval) is int and 30 <= interval <= 600
                and 0 <= (now - _timestamp(data['sampled_at'])).total_seconds() <= 3 * interval
                and isinstance(data['own'], dict) and isinstance(data['cluster'], dict)
                and data['cluster'].get('name', name) == name
                and data['cluster'].get('scheduler', scheduler_kind(select_cluster(cfg, name)))
                == scheduler_kind(select_cluster(cfg, name)))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def ladder_config_identity(cfg):
    """Digest routing inputs, including physical identity; never publish credentials."""
    from ag.config import cluster_identity
    entries = {}
    for name in cfg.get('clusters', {'default': cfg}):
        entry = select_cluster(cfg, name)
        entries[name] = dict(resources=entry['resources'],
                            identity=[str(v) for v in cluster_identity(entry)],
                            partition=entry.get('partition'),
                            node_targeting=entry.get('node_targeting'),
                            capabilities={t: _enabled(entry, t) for t in TEMPLATES})
    return _digest(dict(routing=cfg.get('routing'), entries=entries))


def _study_identity(key, name, names):
    """Validate an adapter-bound locator identity without accessing its path."""
    if (not isinstance(key, str) or len(key) != 64
            or any(c not in '0123456789abcdef' for c in key)):
        raise ValueError('Missing or invalid study_key')
    identifier(name)
    if names.setdefault(key, name) != name:
        raise ValueError('Conflicting study_key display names')


def _placement_records(cfg, placements):
    """Normalize adapter-verified local records; duplicate reads are not new jobs.

    The adapter must supply ALL active local reservations (including other
    studies/rounds/runs), including UNKNOWN and unobserved claims, plus this
    run's completed placements. study_key comes from the adapter's safely
    located absolute study directory; study_id and scheduler_job_name come
    from the verified manifest. Autonomous round/run ownership comes from
    replayed submission intent records. No CLI accepts these from user JSON.
    Hash strings alone do not verify a submission.
    """
    from ag.config import cluster_identity
    from ag.submission import raw_job, qualified
    records, attempts, study_names = {}, {}, {}
    for item in placements:
        entry = select_cluster(cfg, item['cluster'])
        identity = cluster_identity(entry)
        _study_identity(item['study_key'], item['study_id'], study_names)
        identifier(item['attempt_id'])
        identifier(item['scheduler_job_name'])
        if item['run_id'] is not None:
            identifier(item['run_id'])
            identifier(item['round_id'])
            identifier(item['object_id'])
        elif item['round_id'] is not None:
            raise ValueError('Round placement requires a wakeup identity')
        if item.get('target_node') is not None:
            from ag.node_targeting import allowed
            allowed(entry, item['target_node'])
        if (item['state'] not in ('reserved', 'unknown', 'queued', 'running', 'finished')
                or type(item['cores']) is not int or item['cores'] < 1
                or type(item['mem_gb']) is not int or item['mem_gb'] < 1):
            raise ValueError('Invalid or unresolved local placement evidence')
        job = item['job_id']
        if job is not None:
            manifest = dict(cluster=item['cluster'], scheduler=scheduler_kind(entry))
            job = raw_job(manifest, job if ':' in job else qualified(manifest, job))
        elif item['state'] not in ('reserved', 'unknown'):
            raise ValueError('Submitted placement needs a bound scheduler job')
        for field in ('manifest_sha256', 'record_sha256'):
            value = item[field]
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Missing placement evidence identity')
        record = dict(item, job_id=job)
        key = (identity, job if job is not None else ('reservation', item['study_key'], item['attempt_id']))
        attempt_key = (identity, item['study_key'], item['attempt_id'])
        # Aliases of one account may expose the same verified binding. Only
        # the entry name may differ; conflicting ownership is never merged.
        binding = {k: v for k, v in record.items() if k != 'cluster'}
        if ((key in records and {k: v for k, v in records[key].items() if k != 'cluster'} != binding)
                or (attempt_key in attempts and attempts[attempt_key] != key)):
            raise ValueError('Conflicting local placement identities')
        if key not in records or record['cluster'] < records[key]['cluster']:
            records[key] = record
        attempts[attempt_key] = key
    return sorted(records.values(), key=lambda p: (p['cluster'], p['study_key'], p['attempt_id']))


def _observed_jobs(cfg, name, data):
    from ag.submission import raw_job
    selected = select_cluster(cfg, name)
    peers = shared_clusters(selected)
    result = {}
    jobs = data['own']['jobs']
    if not isinstance(jobs, list):
        raise ValueError('Missing complete scheduler job list')
    for row in jobs:
        job = row['job_id']
        prefix = job.split(':')[0] if ':' in job else name
        if prefix not in peers:
            raise ValueError('Snapshot job belongs to another physical cluster')
        key = raw_job(dict(cluster=prefix, scheduler=scheduler_kind(selected)), job)
        from ag.slurm import ACTIVE, TERMINAL
        active = {'Q', 'H', 'W', 'T', 'R', 'E', 'S'} if scheduler_kind(selected) == 'pbs' else ACTIVE
        terminal = {'C'} if scheduler_kind(selected) == 'pbs' else TERMINAL
        if row.get('state') in terminal:
            continue
        if row.get('state') not in active:
            raise ValueError('Unknown scheduler job state')
        if key in result:
            raise ValueError('Duplicate scheduler job identity')
        if not isinstance(row.get('name'), str):
            raise ValueError('Missing scheduler job name')
        result[key] = row
    return result


def _is_running(job):
    return job.get('state') in ('R', 'E', 'RUNNING', 'COMPLETING')


def _ladder_usage(cfg, name, snapshots, placements, now):
    peers = shared_clusters(select_cluster(cfg, name))
    choices = []
    for peer in peers:
        data = snapshots.get(peer)
        if _ladder_snapshot(cfg, peer, data, now):
            own = _own(dict(fresh=True, data=data))
            if own is not None:
                choices.append((_timestamp(data['sampled_at']), peer, own))
    if not choices:
        raise ValueError('No fresh complete account usage')
    stamp, source, own = max(choices)
    observed = _observed_jobs(cfg, source, snapshots[source])
    # Equal timestamps cannot order contradictory same-account observations.
    # Reject rather than let an alias with an empty view release reservations.
    def signature(peer, counts):
        jobs = _observed_jobs(cfg, peer, snapshots[peer])
        return counts, {k: {f: row.get(f) for f in ('name', 'state', 'cores', 'queue')}
                        for k, row in jobs.items()}
    if any(signature(peer, counts) != signature(source, own)
           for at, peer, counts in choices if at == stamp):
        raise ValueError('Conflicting same-time shared account snapshots')
    active = [p for p in placements if p['cluster'] in peers
              and (p['state'] != 'finished' or p['job_id'] in observed)]
    for p in active:
        row = observed.get(p['job_id'])
        if row is not None and row['name'] != p['scheduler_job_name']:
            raise ValueError('Scheduler and local submission identity disagree')
    unseen = [p for p in active if p['job_id'] not in observed]
    return dict(source=source, committed=own['cores_in_use'] + sum(p['cores'] for p in unseen),
                queued=own['cores_queued'] + sum(p['cores'] for p in unseen),
                active=active, observed=observed)


def select_ladder(cfg, snapshots, *, template, job_class, walltime, study_key, study_id, round_id, run_id, object_id,
                  placements, wakeups, waiting_since=None, parent_cluster=None,
                  batch_inputs=None, now=None, evaluate_from=None):
    """Pure T185/T186 selection kernel; no IO, SSH, preparation or approval.

    Inputs are captured by a trusted local adapter, not model-authored flags:
    placements bind verified manifests/submission records (or outstanding
    claims/ledgers); wakeups bind replayed run-start events and object waiting
    history. study_key is the adapter-bound SHA-256 of the safely located
    absolute study directory; study_id is its display name, never a fallback
    identity. This kernel does not locate or hash paths. batch_inputs maps
    input digests to complete original selections.
    T184 does not yet expose those verified inputs, so the CLI fails closed.
    Counts include every autonomous study and round on this machine. A
    selected resource is advice to prepare; T186 must recapture ALL records
    and recompute while holding the shared submission lock, then reserve
    before releasing it. This function never certifies its caller's evidence
    or provides a concurrency lock. UNKNOWN retention is not permission to
    resume its owner or resubmit that Attempt. evaluate_from identifies one
    caller-verified original reservation for candidate evaluation only. It
    exempts only that record's object shortcut, never its resource usage;
    cancellation eligibility and any subsequent submission remain external.
    """
    from copy import deepcopy
    from ag.capacity import evaluate_node
    from ag.config import cluster_identity
    from ag.node_targeting import admission, resource
    validate_routing(cfg)
    if template not in TEMPLATES or job_class not in ('main', 'small'):
        raise ValueError('Invalid ladder template or job class')
    if job_class == 'main' and template != 'gaussian':
        raise ValueError('Only Gaussian main-system jobs use the main ladder')
    if template in ('crest', 'xtb'):
        raise ValueError('CREST/xTB retain the existing routing order')
    study_names = {}
    _study_identity(study_key, study_id, study_names)
    identifier(round_id)
    identifier(run_id)
    identifier(object_id)
    walltime_seconds(walltime)
    if parent_cluster is not None:
        select_cluster(cfg, parent_cluster)
    now = now or datetime.now(timezone.utc)
    config_hash = ladder_config_identity(cfg)
    records = _placement_records(cfg, placements)
    for record in records:
        _study_identity(record['study_key'], record['study_id'], study_names)
    # Validate every supplied wakeup even when no waiting qualification is
    # requested, so a missing locator never silently becomes a name match.
    seen_runs = {}
    for wake in wakeups:
        _study_identity(wake['study_key'], wake['study_id'], study_names)
        for field in ('round_id', 'run_id', 'object_id'):
            identifier(wake[field])
        start = _timestamp(wake['started_at'])
        identity = tuple(wake[k] for k in ('study_key', 'round_id', 'run_id', 'object_id'))
        if identity in seen_runs and seen_runs[identity] != start:
            raise ValueError('Conflicting wakeup identity')
        seen_runs[identity] = start
    batch_inputs = batch_inputs or {}
    cells = cfg.get('routing', {}).get('ladder')
    if not cells:
        raise ValueError('No routing.ladder configured')
    evaluation_source = None
    if evaluate_from is not None:
        if (not isinstance(evaluate_from, dict)
                or set(evaluate_from) != {'study_key', 'attempt_id', 'record_sha256'}):
            raise ValueError('Evaluation requires an exact original reservation identity')
        identifier(evaluate_from['attempt_id'])
        digest = evaluate_from['record_sha256']
        if (evaluate_from['study_key'] != study_key or not isinstance(digest, str)
                or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('Invalid evaluation source identity')
        # Equivalent reads/aliases already collapse to one physical binding;
        # multiple distinct bindings must never receive one source exemption.
        matches = [p for p in records if p['study_key'] == study_key
                   and p['attempt_id'] == evaluate_from['attempt_id']]
        if len(matches) != 1:
            raise ValueError('Evaluation source must match exactly one original placement')
        evaluation_source = matches[0]
        if (evaluation_source['record_sha256'] != digest or evaluation_source.get('round_id') != round_id
                or evaluation_source.get('object_id') != object_id or evaluation_source.get('run_id') is None
                or evaluation_source.get('config_sha256') != config_hash):
            raise ValueError('Evaluation source ownership or routing configuration differs')
        source_cells = [c for c in cells if c['id'] == evaluation_source.get('cell_id')
                        and job_class in c['classes']]
        if len(source_cells) != 1:
            raise ValueError('Evaluation source cell is missing or inapplicable')
        source_cell = source_cells[0]
        source_entry = select_cluster(cfg, source_cell['cluster'])
        expected = source_entry['resources']['tiers'][source_cell['tier']]
        if (cluster_identity(select_cluster(cfg, evaluation_source['cluster'])) != cluster_identity(source_entry)
                or evaluation_source['cores'] != expected['cores'] or evaluation_source['mem_gb'] != expected['mem_gb']
                or evaluation_source.get('target_node') != (evaluation_source.get('capacity_node')
                    if 'node_targeting' in source_entry else None)
                or not isinstance(evaluation_source.get('capacity_node'), str)
                or ('nodes' in source_cell and evaluation_source['capacity_node'] not in source_cell['nodes'])):
            raise ValueError('Evaluation source position or resources differ from its cell')

    def is_original(p):
        return evaluation_source is not None and all(p[k] == evaluation_source[k]
            for k in ('study_key', 'attempt_id', 'record_sha256'))

    evidence = dict(config_sha256=config_hash,
                    snapshots={n: _digest(d) for n, d in snapshots.items() if d is not None},
                    placements_sha256=_digest(records), wakeups_sha256=_digest(wakeups))
    request = dict(template=template, job_class=job_class, walltime=walltime, study_key=study_key,
                   study_id=study_id, round_id=round_id, run_id=run_id,
                   object_id=object_id, waiting_since=waiting_since, parent_cluster=parent_cluster)
    if evaluate_from is not None:
        # Preserve ordinary selection/batch hashes when evaluation is absent.
        request['evaluate_from'] = deepcopy(evaluate_from)
    evidence['input_sha256'] = _digest(dict(config_sha256=config_hash, request=request,
        snapshots=snapshots, placements=records, wakeups=wakeups, selected_at=now.isoformat()))
    result = dict(schema='ag-routing-ladder/1', study_key=study_key, study_id=study_id,
                  round_id=round_id, run_id=run_id, object_id=object_id,
                  template=template, job_class=job_class, walltime=walltime,
                  parent_cluster=parent_cluster, evidence=evidence, candidates=[],
                  recommendation=None, notes=[DISCLAIMER])
    if evaluate_from is not None:
        result.update(evaluation_only=True, evaluate_from=deepcopy(evaluate_from))
    if any(p['study_key'] == study_key and p.get('round_id') == round_id and p.get('run_id') == run_id
           and p.get('object_id') == object_id and not is_original(p) for p in records):
        result['reason'] = 'object_already_placed_in_run'
        return result
    waited = False
    if waiting_since is not None:
        since = _timestamp(waiting_since)
        for wake in wakeups:
            start = _timestamp(wake['started_at'])
            if (wake['study_key'] == study_key and wake['round_id'] == round_id
                    and wake['object_id'] == object_id and since < start <= now):
                waited = True
    # The scheduler may still show a locally finished job. Retain its exact
    # active/queue membership until readback disappears; do not release a slot.
    effective = []
    for p in records:
        item = dict(p)
        try:
            usage = _ladder_usage(cfg, p['cluster'], snapshots, records, now)
            observed = usage['observed'].get(p['job_id'])
            if observed is not None:
                item['state'] = 'running' if _is_running(observed) else 'queued'
            elif p['state'] != 'finished':
                # Missing readback cannot prove that a bound or UNKNOWN
                # submission has finished, nor release its possible queue slot.
                item['state'] = 'reserved'
        except (KeyError, TypeError, ValueError):
            # Account evidence is rejected at the relevant candidate below.
            item['state'] = 'reserved'
        effective.append(item)
    queued = [p for p in effective if p.get('run_id') is not None
              and p['state'] in ('reserved', 'queued')]
    if any(p['study_key'] == study_key and p.get('round_id') == round_id and p.get('object_id') == object_id
           and p['state'] != 'finished' and not is_original(p) for p in effective):
        result['reason'] = 'object_already_active_in_round'
        return result
    rows = result['candidates']
    unknown_cells = []
    for cell_index, cell in enumerate(cells):
        if job_class not in cell['classes']:
            continue
        name = cell['cluster']
        selected = select_cluster(cfg, name)
        requested = selected['resources']['tiers'][cell['tier']]
        cores, memory = requested['cores'], requested['mem_gb']
        data = snapshots.get(name)
        time_check, time_note = _walltime(selected['resources'], walltime)
        base = dict(cell_id=cell['id'], cluster=name, tier=cell['tier'], **requested,
                    condition=cell['condition'], node_fraction=cell.get('node_fraction'),
                    target_node=None, capacity_node=None, eligible=False, reasons=[],
                    cell_index=cell_index, occupied=False, walltime=time_check, notes=[time_note])
        reasons = base['reasons']
        if parent_cluster is not None and name != parent_cluster:
            reasons.append('parent_cluster_binding')
        if not _enabled(selected, template) or ('node_targeting' in selected and template != 'gaussian'):
            reasons.append('unsupported_template')
        if time_check['status'] == 'exceeded':
            reasons.append('walltime_exceeded')
        if not _ladder_snapshot(cfg, name, data, now) or data['cluster'].get('nodes_error'):
            if not reasons:
                unknown_cells.append(base)
            reasons.append('snapshot_missing_failed_or_stale')
        if reasons:
            rows.append(base)
            continue
        try:
            usage = _ladder_usage(cfg, name, snapshots, effective, now)
            local_jobs = _observed_jobs(cfg, name, data)
        except (KeyError, TypeError, ValueError):
            reasons.append('account_or_reservation_evidence_unknown')
            rows.append(base)
            continue
        base['usage_source'] = usage['source']
        if cores > selected['resources']['max_cores'] or usage['committed'] + cores > committed_cap(selected):
            reasons.append('account_core_limit')
        queue_cap = optional_resource_caps(selected).get('max_queued_cores')
        if queue_cap is not None and usage['queued'] + cores > queue_cap:
            reasons.append('account_queue_limit')
        nodes = data['cluster'].get('nodes')
        if (data['cluster'].get('nodes_error') or not isinstance(nodes, list) or not nodes
                or any(not isinstance(n, dict) for n in nodes)
                or any(not isinstance(n.get('name'), str) for n in nodes)
                or len({n['name'] for n in nodes}) != len(nodes)):
            reasons.append('node_identity_unknown')
            rows.append(base)
            continue
        ordered = cell.get('nodes', [n['name'] for n in nodes])
        for node_name in ordered:
            row = deepcopy(base)
            row['capacity_node'] = node_name
            row['target_node'] = node_name if 'node_targeting' in selected else None
            row['batch_snapshot_sha256'] = _digest(data)
            row['batch_input_sha256'] = evidence['input_sha256']
            nodes_here = [n for n in nodes if n['name'] == node_name]
            if len(nodes_here) != 1:
                row['reasons'].append('node_missing')
                rows.append(row)
                continue
            original = nodes_here[0]
            current = deepcopy(original)
            if 'node_targeting' in selected:
                try:
                    if resource(original.get('cores_total'), cell['node_fraction']) != requested:
                        raise ValueError('Tier does not match fraction')
                    if not admission(original, cores, memory)['selectable']:
                        raise ValueError('Node not admissible')
                except (KeyError, ValueError):
                    row['reasons'].append('node_fraction_or_total_specs')
            # A queued/unobserved unbound job may land on any node. Reserve on
            # each candidate until readback locates/runs it; never sum free nodes.
            pending = [p for p in usage['active']
                       if not (_is_running(local_jobs.get(p['job_id'], {}))
                               or local_jobs.get(p['job_id'], {}).get('state') in ('S', 'SUSPENDED'))
                       and p.get('target_node') in (None, node_name)]
            try:
                current['cores_used'] += sum(p['cores'] for p in pending)
                if scheduler_kind(selected) == 'pbs':
                    current['mem_assigned_bytes'] += sum(p['mem_gb'] * 1024**3 for p in pending)
                else:
                    current['mem_assigned_gb'] += sum(p['mem_gb'] for p in pending)
                    current['cores_idle'] -= sum(p['cores'] for p in pending)
                    if pending and current['state'] == 'idle':
                        current['state'] = 'mixed'
            except (KeyError, TypeError):
                row['reasons'].append('node_allocation_unknown')
            check = evaluate_node(original if cell['condition'] in ('jobs', 'queue') else current,
                                  cores, memory, scheduler=scheduler_kind(selected),
                                  partition=selected.get('partition'))
            row['capacity'] = check
            row['occupied'] = bool(original.get('cores_used') or pending)
            if check['availability'] in ('unknown', 'not_applicable'):
                row['reasons'].append('node_capacity_unknown_or_inapplicable')
            members = [p for p in records if p['study_key'] == study_key
                       and p.get('round_id') == round_id and p.get('run_id') == run_id
                       and p.get('cell_id') == cell['id'] and p.get('capacity_node') == node_name]
            if cell['condition'] in ('empty', 'free') and len(members) >= cell['max_placements']:
                row['reasons'].append('batch_placement_limit')
            condition = cell['condition']
            if condition in ('empty', 'free'):
                if check['availability'] != 'enough':
                    row['reasons'].append('insufficient_current_capacity')
                others = data['cluster'].get('job_summary', {}).get('others_queued_jobs')
                if not _count(others) or others:
                    row['reasons'].append('other_queue_unknown_or_waiting')
                if condition == 'free' and check.get('cores_available', -1) < cell['min_free_cores']:
                    row['reasons'].append('free_core_condition')
                if condition == 'empty':
                    origin = original
                    if members:
                        first = members[0]
                        digest = first.get('batch_input_sha256')
                        batch = batch_inputs.get(digest)
                        try:
                            # Replaying the same selector also verifies original
                            # quota, capability, order and local reservations.
                            # Strictly fewer records makes recursive proofs finite.
                            if (first['config_sha256'] != config_hash
                                    or len(batch['placements']) >= len(records)
                                    or batch['request']['study_key'] != study_key
                                    or batch['request']['study_id'] != study_id
                                    or batch['request']['round_id'] != round_id
                                    or batch['request']['run_id'] != run_id
                                    or batch['request']['object_id'] != first['object_id']
                                    or batch['selected_at'] != first['selected_at']
                                    or _timestamp(first['selected_at']) > now):
                                raise ValueError('Invalid batch identity')
                            initial = select_ladder(cfg, batch['snapshots'], **batch['request'],
                                placements=batch['placements'], wakeups=batch['wakeups'],
                                batch_inputs=batch_inputs, now=_timestamp(batch['selected_at']))
                            choice = initial['recommendation']
                            if (initial['evidence']['input_sha256'] != digest or choice is None
                                    or choice['cell_id'] != cell['id'] or choice['capacity_node'] != node_name
                                    or any(p.get('batch_input_sha256') != digest
                                           or cluster_identity(select_cluster(cfg, p['cluster'])) != cluster_identity(selected)
                                           or p['cores'] != cores or p['mem_gb'] != memory
                                           or p.get('target_node') != row['target_node']
                                           for p in members)):
                                raise ValueError('Initial batch did not qualify')
                            origins = [n for n in batch['snapshots'][name]['cluster']['nodes']
                                       if n['name'] == node_name]
                            origin = origins[0]
                            row['batch_input_sha256'] = digest
                            row['batch_snapshot_sha256'] = choice['batch_snapshot_sha256']
                        except (KeyError, TypeError, ValueError, IndexError):
                            row['reasons'].append('batch_origin_unverified')
                    if (origin.get('cores_used') != 0 or origin.get('jobs') != 0
                            or origin.get('targeting_reserved') is True
                            or (origin.get('mem_assigned_bytes') if scheduler_kind(selected) == 'pbs'
                                else origin.get('mem_assigned_gb')) != 0):
                        row['reasons'].append('not_initially_empty')
                    if not members and pending:
                        row['reasons'].append('existing_local_reservation')
            elif condition == 'jobs':
                if not waited:
                    row['reasons'].append('no_verified_waiting_wakeup')
                autonomous = [p for p in usage['active'] if p.get('run_id') is not None]
                if len(autonomous) >= cell['max_jobs']:
                    row['reasons'].append('autonomous_job_limit')
            elif condition == 'queue':
                identity = cluster_identity(selected)
                same = [p for p in queued if cluster_identity(select_cluster(cfg, p['cluster'])) == identity
                        and (row['target_node'] is None or p.get('target_node') in (None, row['target_node']))]
                if same:
                    row['reasons'].append('resource_queue_limit')
                if len(queued) >= 2:
                    row['reasons'].append('global_queue_limit')
            row['eligible'] = not row['reasons']
            rows.append(row)
    entry_order = list(dict.fromkeys(c['cluster'] for c in cells if job_class in c['classes']))

    def priority(row):
        # Preserve configured entry order while using occupied nodes before
        # empty nodes for small systems. One ordering serves both ordinary
        # selection and comparison against an original reservation's cell.
        if job_class == 'small':
            return (row['condition'] == 'queue', entry_order.index(row['cluster']),
                    not row['occupied'], row['cell_index'])
        return (row['cell_index'],)

    if evaluation_source is not None:
        # The source's current position is required even if a higher cell fits.
        if any(r['cell_id'] == evaluation_source['cell_id'] for r in unknown_cells):
            result['reason'] = 'snapshot_missing_failed_or_stale'
            return result
        source_rows = [r for r in rows if r['cell_id'] == evaluation_source['cell_id']
                       and r['capacity_node'] == evaluation_source['capacity_node']]
        if len(source_rows) != 1:
            raise ValueError('Evaluation source position is not present in current candidates')
        source_nodes = [n for n in snapshots[source_cell['cluster']]['cluster']['nodes']
                        if n.get('name') == evaluation_source['capacity_node']]
        if (len(source_nodes) != 1 or ('node_targeting' in source_entry
                and resource(source_nodes[0].get('cores_total'), source_cell['node_fraction']) != expected)):
            raise ValueError('Evaluation source node or fraction differs from its cell')
        source_rank = priority(source_rows[0])
        for row in rows:
            if row['cell_id'] == evaluation_source['cell_id'] or priority(row) >= source_rank:
                row['eligible'] = False
                row['reasons'].append('not_strictly_higher_than_source')
    choices = sorted((row for row in rows if row['eligible']), key=priority)
    # A lower-priority outage must not stop a known better candidate. For
    # small jobs, unknown occupancy may have the preferred occupied rank;
    # use that bound only for comparison, never as observed resource evidence.
    if unknown_cells and (not choices or any(
            priority(dict(row, occupied=True)) < priority(choices[0]) for row in unknown_cells)):
        result['reason'] = 'snapshot_missing_failed_or_stale'
        return result
    if choices:
        chosen = deepcopy(choices[0])
        chosen.update(config_sha256=config_hash, selected_at=now.isoformat(),
                      needs_queue=chosen['condition'] in ('jobs', 'queue'))
        result['recommendation'] = chosen
    result['reason'] = 'selected' if choices else 'no_eligible_cell'
    return result


def autonomous_account_job_cap(cfg, name):
    """The bound ladder's account job ceiling also covers other templates."""
    peers = shared_clusters(select_cluster(cfg, name))
    limits = [cell['max_jobs'] for cell in cfg.get('routing', {}).get('ladder', [])
              if cell['condition'] == 'jobs' and cell['cluster'] in peers]
    return min(limits) if limits else None


def select_legacy(cfg, snapshots, *, template, job_class, walltime, study_key, study_id,
                  round_id, run_id, object_id, tier, placements, wakeups,
                  waiting_since=None, parent_cluster=None, batch_inputs=None, now=None):
    """Recheck CREST/xTB's existing recommendation with trusted reservations.

    Entry order and tier selection remain suggest's existing behavior. If that
    recommendation cannot survive complete account/node evidence, stop; this
    wrapper does not introduce another fallback or Gaussian ladder ordering.
    """
    from ag import approval
    from ag.capacity import evaluate_node
    if template not in ('crest', 'xtb') or job_class != 'small':
        raise ValueError('Legacy autonomous routing requires a small CREST/xTB object')
    if tier not in TIERS:
        raise ValueError('Autonomous CREST/xTB routing requires an explicit --tier')
    walltime_seconds(walltime)
    names = {}
    _study_identity(study_key, study_id, names)
    for value in (round_id, run_id, object_id):
        identifier(value)
    if parent_cluster is not None:
        select_cluster(cfg, parent_cluster)
    if waiting_since is not None:
        _timestamp(waiting_since)
    if not isinstance(wakeups, list):
        raise ValueError('Verified wakeup list is required')
    seen = set()
    for wake in wakeups:
        _study_identity(wake['study_key'], wake['study_id'], names)
        key = tuple(wake[k] for k in ('study_key', 'round_id', 'run_id', 'object_id'))
        for value in key[1:]:
            identifier(value)
        _timestamp(wake['started_at'])
        if key in seen:
            raise ValueError('Duplicate wakeup identity')
        seen.add(key)
    now = now or datetime.now(timezone.utc)
    config_hash = ladder_config_identity(cfg)
    records = _placement_records(cfg, placements)
    for record in records:
        _study_identity(record['study_key'], record['study_id'], names)
    request = dict(template=template, job_class=job_class, walltime=walltime, study_key=study_key,
                   study_id=study_id, round_id=round_id, run_id=run_id, object_id=object_id,
                   waiting_since=waiting_since, parent_cluster=parent_cluster, tier=tier)
    original = dict(config_sha256=config_hash, request=request, snapshots=snapshots,
                    placements=records, wakeups=wakeups, selected_at=now.isoformat())
    evidence = dict(config_sha256=config_hash, input_sha256=approval.digest(original),
                    snapshots={name: approval.digest(data) for name, data in snapshots.items() if data is not None},
                    placements_sha256=approval.digest(records), wakeups_sha256=approval.digest(wakeups))
    result = dict(schema='ag-routing-legacy/1', **request, evidence=evidence,
                  recommendation=None, candidates=[], notes=[DISCLAIMER])
    if any(p['study_key'] == study_key and p.get('round_id') == round_id
           and p.get('run_id') == run_id and p.get('object_id') == object_id for p in records):
        result['reason'] = 'object_already_placed_in_run'
        return result
    advice = suggest(cfg, template, tier, study_id, walltime=walltime, now=now,
                     captured_snapshots=snapshots)
    result['candidates'] = advice['clusters']
    recommendation = advice['recommendation']
    if recommendation is None:
        result['reason'] = 'legacy_route_has_no_recommendation'
        return result
    name = recommendation['name']
    selected = select_cluster(cfg, name)
    suggested_row = next(row for row in advice['clusters'] if row['name'] == name)
    if suggested_row.get('capacity', {}).get('availability') not in ('enough', 'queue'):
        result['reason'] = 'legacy_recommendation_capacity_unknown'
        return result
    if parent_cluster is not None and name != parent_cluster:
        result['reason'] = 'parent_cluster_binding'
        return result
    # Check the recommendation and earlier entries in suggest's own order.
    # A lower-priority failure must not veto a verified recommendation; usage
    # still receives all snapshots and records for shared-account accounting.
    order = advice['order']
    relevant = [n for n in order[:order.index(name) + 1]
                if _enabled(select_cluster(cfg, n), template)
                and tier in select_cluster(cfg, n)['resources']['tiers']]
    if any(not _ladder_snapshot(cfg, n, snapshots.get(n), now) for n in relevant):
        result['reason'] = 'snapshot_missing_failed_or_stale'
        return result
    try:
        usages = {n: _ladder_usage(cfg, n, snapshots, records, now) for n in relevant}
        usage = usages[name]
        jobs = _observed_jobs(cfg, name, snapshots[name])
    except (KeyError, TypeError, ValueError):
        result['reason'] = 'account_or_reservation_evidence_unknown'
        return result
    resource = selected['resources']['tiers'][tier]
    job_cap = autonomous_account_job_cap(cfg, name)
    if job_cap is not None and sum(p.get('run_id') is not None for p in usage['active']) >= job_cap:
        result['reason'] = 'autonomous_job_limit'
        return result
    cores, memory = resource['cores'], resource['mem_gb']
    caps = optional_resource_caps(selected)
    if (cores > selected['resources']['max_cores'] or usage['committed'] + cores > committed_cap(selected)
            or ('max_queued_cores' in caps and usage['queued'] + cores > caps['max_queued_cores'])):
        result['reason'] = 'account_or_queue_core_limit'
        return result
    if any(p['study_key'] == study_key and p.get('round_id') == round_id
           and p.get('object_id') == object_id for p in usage['active']):
        result['reason'] = 'object_already_active_in_round'
        return result
    data = snapshots[name]
    nodes = data['cluster'].get('nodes')
    if ('node_targeting' in selected or data['cluster'].get('nodes_error')
            or not isinstance(nodes, list) or not nodes
            or any(not isinstance(node, dict) or not isinstance(node.get('name'), str) for node in nodes)
            or len({node['name'] for node in nodes}) != len(nodes)):
        result['reason'] = 'node_identity_unknown_or_unsupported'
        return result
    others = data['cluster'].get('job_summary', {}).get('others_queued_jobs')
    if not _count(others):
        result['reason'] = 'other_queue_unknown'
        return result
    pending = [p for p in usage['active'] if not (_is_running(jobs.get(p['job_id'], {}))
               or jobs.get(p['job_id'], {}).get('state') in ('S', 'SUSPENDED'))]
    evaluated = []
    for node in nodes:
        current = deepcopy(node)
        held = [p for p in pending if p.get('target_node') in (None, node['name'])]
        try:
            current['cores_used'] += sum(p['cores'] for p in held)
            if scheduler_kind(selected) == 'pbs':
                current['mem_assigned_bytes'] += sum(p['mem_gb'] * 1024**3 for p in held)
            else:
                current['mem_assigned_gb'] += sum(p['mem_gb'] for p in held)
                current['cores_idle'] -= sum(p['cores'] for p in held)
                if held and current['state'] == 'idle':
                    current['state'] = 'mixed'
        except (KeyError, TypeError):
            result['reason'] = 'node_allocation_unknown'
            return result
        evaluated.append(evaluate_node(current, cores, memory, scheduler=scheduler_kind(selected),
                                       partition=selected.get('partition')))
    desired = 'queue' if recommendation['needs_queue'] else 'enough'
    matching = [check for check in evaluated if check['availability'] == desired]
    # Queue advice may be caused by other queued users even while one node
    # currently fits. It still uses the same suggested entry and queue limits.
    if desired == 'queue' and not matching:
        matching = [check for check in evaluated if check['availability'] == 'enough']
    if not matching:
        result['reason'] = 'node_capacity_unknown_or_changed_by_reservation'
        return result
    if desired == 'queue':
        queued = []
        for p in records:
            if p.get('run_id') is None:
                continue
            try:
                view = _ladder_usage(cfg, p['cluster'], snapshots, records, now)
                if p not in view['active']:
                    continue
                observed = view['observed'].get(p['job_id'])
                if observed is not None and _is_running(observed):
                    continue
            except (KeyError, TypeError, ValueError):
                pass  # Missing readback never frees a possible queue slot.
            queued.append(p)
        if len(queued) >= 2:
            result['reason'] = 'global_queue_limit'
            return result
    chosen = matching[0]
    result['recommendation'] = dict(cluster=name, tier=tier, **resource,
        target_node=None, capacity_node=chosen['name'], node_fraction=None,
        cell_id='legacy-' + name, config_sha256=config_hash, selected_at=now.isoformat(),
        batch_input_sha256=evidence['input_sha256'], needs_queue=desired == 'queue')
    result['reason'] = 'selected'
    return result


def format_result(result):
    lines = ['入口（显示名） | 结论 | 原因 | 快照时间']
    for row in result['clusters']:
        name = row['name']
        if row['display_name'] != name:
            name = f"{row['display_name']}（{name}）"
        reasons = row['reasons'] + row['notes'] or ['本人上限及硬件满足，未见他人排队']
        lines.append(f"{name} | {row['conclusion']} | {'；'.join(reasons)} | {row['sampled_at'] or '未知'}")
    return '\n'.join([*lines, *result.get('notes', []), result['message']])


def prepare_hint(cfg, manifest):
    # Advice must never turn a successful preparation into a failed operation.
    if 'routing' not in cfg:
        return ''
    try:
        result = suggest(cfg, manifest['template'], manifest['tier'], manifest['study_id'],
                         walltime=manifest['walltime'])
        chosen = result['recommendation']
        if not chosen or chosen['name'] == manifest.get('cluster', 'default'):
            return ''
        row = next(r for r in result['clusters'] if r['name'] == chosen['name'])
        if not row['snapshot_fresh']:
            return ''
        reason = '；'.join([chosen['reason'], *chosen['reasons']])
        return (f"\n路由建议为 {chosen['name']}（{reason}）；"
                f"本次按 --cluster {manifest.get('cluster', 'default')} 准备。{DISCLAIMER}")
    except Exception:
        # This boundary covers optional advice only, after prepare has succeeded.
        # Even an unexpected advisor failure must not misreport that saved result.
        return ''


def run(args):
    if args.config_identity:
        routing_options = (args.template, args.tier, args.job_class, args.study, args.walltime,
                           args.round_id, args.run_id, args.object_id,
                           args.autonomous_policy, args.token, args.plan_sha256)
        if any(value is not None for value in routing_options):
            raise ValueError('--config-identity cannot be combined with routing arguments')
        try:
            result = dict(routing_sha256=ladder_config_identity(load_config()))
        except Exception as exc:
            # Discovery must not expose private configuration values in errors.
            raise ValueError('Cannot read routing configuration identity; check local configuration') from exc
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
              else 'routing_sha256: ' + result['routing_sha256'])
        return 0
    if args.template is None:
        args.route_parser.error('the following arguments are required: --template')
    context_options = (args.round_id, args.run_id, args.object_id,
                       args.autonomous_policy, args.token, args.plan_sha256)
    if args.job_class:
        if not all((*context_options, args.study, args.walltime)):
            raise ValueError('Trusted routing requires --study, --round-id, --run-id, --object-id, '
                             '--walltime, --autonomous-policy, --token and --plan-sha256')
        if (args.template in ('crest', 'xtb')) != (args.tier is not None):
            raise ValueError('Trusted CREST/xTB routing requires --tier; Gaussian ladder routing does not use --tier')
        from hashlib import sha256
        from ag import autonomy, autonomy_submission, _autonomy_store as disk
        from ag.submit import autonomy_context, bound_policy
        context = autonomy_context(dict(run_id=args.run_id, token=args.token,
            plan_sha256=args.plan_sha256, policy_name=args.autonomous_policy,
            object_id=args.object_id, job_class=args.job_class), args.study)
        identifier(args.round_id)
        # Advisory inspection must not initialize registries, emit waiting
        # events, pause a round, or create a missing lock/configuration file.
        with autonomy_submission.machine_lock(create=False):
            cfg = load_config()
            with disk.locked(cfg, args.study) as store:
                snapshot, _ = autonomy.load(store)
                state = snapshot['state']
                current_versions = autonomy.versions()
                at = autonomy.now()
                if at < state['updated_at']:
                    raise ValueError('Autonomy clock moved backwards')
                autonomy.eligible(state, args.run_id, sha256(args.token.encode()).hexdigest(),
                    current_versions, at, 'submit', args.plan_sha256)
                if state['current_round'] != args.round_id:
                    raise ValueError('Routing request belongs to another authorization round')
                bound_policy(cfg, state, context)
                selection = autonomous_selection(cfg, state, context, template=args.template,
                    walltime=args.walltime, requested_tier=args.tier)
                store.verify_lock()
        result = selection['result']
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            chosen = result['recommendation']
            print((f"建议：{chosen['cluster']} / {chosen['tier']} / {chosen['cores']} 核"
                   if chosen else '无建议：' + result['reason']) + '\n' + DISCLAIMER)
        return 0
    if any(value is not None for value in context_options):
        raise ValueError('Autonomous routing context requires --job-class')
    if args.tier is None:
        args.route_parser.error('Legacy routing advice requires --tier')
    cfg = load_config()
    result = suggest(cfg, args.template, args.tier, args.study, walltime=args.walltime)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_result(result))
    return 0


def register(subparsers):
    parser = subparsers.add_parser('route', help='Read local monitor snapshots for routing advice')
    parser.add_argument('--config-identity', action='store_true',
                        help='Read local routing configuration identity without a plan or routing request')
    parser.add_argument('--template', choices=TEMPLATES)
    parser.add_argument('--tier', choices=TIERS)
    parser.add_argument('--job-class', choices=('main', 'small'))
    parser.add_argument('--round-id')
    parser.add_argument('--run-id')
    parser.add_argument('--object-id')
    parser.add_argument('--autonomous-policy')
    parser.add_argument('--token')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--walltime', help='Requested positive HH:MM:SS; omitted means unchecked')
    parser.add_argument('--study')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run, route_parser=parser)
