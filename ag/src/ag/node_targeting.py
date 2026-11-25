"""Opt-in PBS targeting. Suggestions are local; admission always re-queries PBS."""
from datetime import datetime, timedelta, timezone
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
import math
import re
import sys
from string import Template

from ag import capacity, pbs, remote
from ag.config import (RESOURCE_TIERS, committed_cap, optional_resource_caps, scheduler_kind,
                       select_cluster, shared_clusters)
from ag.transport import require_ok

# Append the whole node without changing existing option order or the default.
FRACTIONS = ('1/2', '1/4', '1')
_EMPTY_QUEUE_UNKNOWN = 'Site requires an empty node; target queue waiting requests could not be excluded'

# Reviewed T145 guard: exact nodefile names/count, before ANY executable body.
# A template update must be reviewed again before it can prove old placement.
_START_GUARD_SHA256 = '1cdbba1aa1fc942d7cd8ea7537f3b758c4af8001fad507d1e66792d1e79e5a4d'


def node_name(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,62}', value)
            or '..' in value or value.endswith('.')):
        raise ValueError('Invalid PBS target node name')
    return value


def validate_policy(cfg):
    if 'node_targeting' not in cfg:
        return
    p = cfg['node_targeting']
    if (scheduler_kind(cfg) != 'pbs' or not isinstance(p, dict)
            or set(p) - {'occupied_policy'} != {'allowed_nodes', 'denied_nodes', 'priority', 'restricted_nodes'}):
        raise ValueError('node_targeting requires PBS and explicit allow/deny/priority/restriction lists')
    for key in ('allowed_nodes', 'denied_nodes', 'restricted_nodes'):
        values = p[key]
        if not isinstance(values, list) or any(node_name(v) != v for v in values) or len(set(values)) != len(values):
            raise ValueError('Invalid node_targeting list')
    groups = p['priority']
    if not isinstance(groups, list) or not groups or any(not isinstance(g, list) or not g for g in groups):
        raise ValueError('node_targeting.priority requires ordered nonempty groups')
    flat = [node_name(n) for g in groups for n in g]
    if len(set(flat)) != len(flat) or set(flat) != set(p['allowed_nodes']):
        raise ValueError('Node priorities must cover the allowlist exactly once')
    if not set(p['restricted_nodes']) <= set(p['allowed_nodes']):
        raise ValueError('Restricted nodes must be in the allowlist')
    if 'occupied_policy' in p:
        site = p['occupied_policy']
        queue = cfg.get('queue') if cfg.get('scheduler') == 'pbs' else cfg['scheduler']['queue']
        if (not isinstance(site, dict) or set(site) - {'remaining_nodes'} != {'server', 'queue', 'queue_nodes', 'empty_only'}
                or not isinstance(site['server'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*', site['server'])
                or site['queue'] != queue):
            raise ValueError('Occupied-node policy must bind a PBS server and the configured queue')
        classified = set()
        for key in ('queue_nodes', 'empty_only', 'remaining_nodes'):
            names = site.get(key, [])
            if (not isinstance(names, list) or any(node_name(n) != n for n in names)
                    or len(names) != len(set(names)) or not set(names) <= set(p['allowed_nodes'])):
                raise ValueError('Invalid occupied-node policy list')
            if classified.intersection(names):
                raise ValueError('Conflicting occupied-node policy')
            classified.update(names)


def allowed(cfg, name):
    node_name(name)
    validate_policy(cfg)
    p = cfg.get('node_targeting')
    if p is None or name not in p['allowed_nodes'] or name in p['denied_nodes']:
        raise ValueError('Target node is not allowed')
    if name in p['restricted_nodes']:
        raise ValueError('Target node has an unverified special CPU restriction')


def resource(slots, fraction='1/2'):
    if fraction not in FRACTIONS or type(slots) is not int or slots < 1:
        raise ValueError('Invalid node capacity or fraction')
    divisor = int(fraction[-1])
    if slots % divisor or slots < divisor:
        raise ValueError('Node slots do not divide exactly by the selected fraction')
    cores = slots // divisor
    return dict(cores=cores, mem_gb=cores * 2)


def options(cfg, slots):
    result = []
    for fraction in FRACTIONS:
        try:
            r = resource(slots, fraction)
        except ValueError:
            continue
        tier = next((t for t in RESOURCE_TIERS if cfg['resources']['tiers'].get(t) == r), None)
        if r['cores'] > cfg['resources']['max_cores']:
            tier = None
        result.append(dict(fraction=fraction, **r, tier=tier))
    return result


def account_servers(cfg):
    """An opted-in entry requires the same owner proof on every peer entry."""
    if (not cfg or scheduler_kind(cfg) != 'pbs' or not any(
            'occupied_policy' in entry.get('node_targeting', {})
            for entry in [cfg, *cfg.get('_cluster_entries', {}).values()])):
        return set()
    return {p['server'] for entry in shared_clusters(cfg).values()
            if (p := entry.get('node_targeting', {}).get('occupied_policy'))}


def strict_nodes(text, jobs, queue_server=None, account_user=None):
    return pbs.parse_nodes(text, jobs, targeting=True, queue_server=queue_server, account_user=account_user)


def _own_cores(response, jobs, username, server):
    from ag.status import core_breakdown
    lines = response.splitlines()
    if (not isinstance(username, str) or len(lines) < 2
            or lines[0] != f'AG_OWNER {username}' or lines[-1] != 'AG_END'
            or not re.fullmatch(r'[A-Za-z0-9_.][A-Za-z0-9_.-]*', username)):
        raise ValueError('Incomplete PBS login-account job list or mismatched login')
    ids = lines[1:-1]
    if len(set(ids)) != len(ids) or any(not pbs.ordinary_server_job(job, server) for job in ids):
        raise ValueError('PBS login-account IDs are ambiguous, truncated or include an array')
    running, queued = core_breakdown(jobs, username)  # also validates owner/state and rejects own arrays
    detail_rows = [j for j in jobs if j['Job_Owner'].partition('@')[0] == username]
    details = {j['job_id']: j for j in detail_rows}
    if (len(details) != len(detail_rows) or any(not pbs.ordinary_server_job(job, server) for job in details)
            or any(j['job_id'] in details and j['Job_Owner'].partition('@')[0] != username for j in jobs)):
        raise ValueError('PBS login-account job identity is ambiguous')
    own = {job: row for job, row in details.items() if row['job_state'] != 'C'}
    if not own.keys() <= set(ids) <= details.keys():
        raise ValueError('PBS login-account job list differs from visible owner details')
    return own, running, queued, [row.get('Job_Name') for row in detail_rows]


def _check_own_allocations(jobs, username, rows):
    from ag.status import occupied
    for row in jobs:
        if row.get('Job_Owner', '').partition('@')[0] != username or row.get('job_state') == 'C':
            continue
        hosts = row.get('exec_host', '')
        if row['job_state'] not in ('R', 'E', 'S', 'Q', 'H', 'W', 'T'):
            raise ValueError('PBS login-account job state is ambiguous')
        if not hosts and row['job_state'] not in ('R', 'E', 'S'):
            continue
        slots = {}
        for host in hosts.split('+'):
            node, sep, part = host.partition('/')
            if not sep or not node:
                raise ValueError('PBS login-account allocation lacks exact execution slots')
            slots.setdefault(node, []).append(part)
        allocated = sum(pbs.slot_count(','.join(parts)) for parts in slots.values())
        if allocated != occupied([row], username):
            raise ValueError('PBS login-account requested cores and allocated slots disagree')
    if not rows or any(row.get('own_slots_consistent') is not True for row in rows):
        raise ValueError('PBS login-account node allocation could not be reconciled')


def _unobserved_cores(cfg, own, username, claimed, live_names):
    from ag import autonomy_submission as records, config, route, status
    identity = config.ssh_identity(cfg)
    if identity is None or identity[2] != username:
        raise ValueError('Local and PBS login-account identities differ')
    # The normal submission writer already has its configuration lock.
    # This short local scan must never hold the machine mutex across PBS I/O.
    source = (dict(clusters=cfg['_cluster_entries'], local=cfg['local'], _config_dir=cfg['_config_dir'])
              if '_cluster_entries' in cfg else cfg)
    peers = shared_clusters(cfg)
    with records.machine_lock(create=False):
        local = records.read_pbs_reservations(source)['placements']
        held = 0
        mapped = []
        for item in local:
            if not item.get('unmapped_manual_account'):
                mapped.append(item)
            elif item['state'] != 'finished':
                # Historical manual manifests bind an entry label, not its SSH
                # account. Never release a hold on a same-number/name guess.
                if item['job_id'] is not None and item['job_id'] in own:
                    raise ValueError('Foreign manual reservation has an ambiguous PBS account binding')
                held += item['cores']
        placements = route._placement_records(source, mapped)
        for item in route.retain_live_unknowns(placements, peers, live_names):
            if item['cluster'] not in peers:
                continue
            job = own.get(item['job_id'])
            if job is not None:
                if (job.get('Job_Name') != item['scheduler_job_name']
                        or status.occupied([job], username) != item['cores']):
                    raise ValueError('PBS job and local reservation identities disagree')
                continue
            if item['state'] == 'finished':
                continue
            if (claimed is not None and item['attempt_id'] == claimed['attempt_id']
                    and item['cluster'] == claimed['cluster'] and item['state'] == 'reserved'
                    and item['job_id'] is None):
                path = Path(cfg['local']['studies_root']) / claimed['study_id']
                if item['study_key'] == records.study_identity(path)['study_key']:
                    raw, frozen = records._manifest_bytes(path / 'attempts' / item['attempt_id'])
                    if frozen != claimed or item['manifest_sha256'] != sha256(raw).hexdigest():
                        raise ValueError('Current PBS reservation differs from the confirmed Attempt')
                    continue  # The caller adds its own already-claimed request once.
            held += item['cores']
    return held


def observe_occupied_account(cfg, rows, jobs, username, transport, claimed=None):
    servers = account_servers(cfg)
    if not servers:
        result = {}
        if username is not None:
            try:
                _check_own_allocations(jobs, username, rows)
            except ValueError as exc:
                result['occupied_queue_error'] = str(exc)
                for row in rows:
                    row.update(result)
        return result
    response = transport.run(remote.pbs_own_jobs())
    if response.returncode == 255:
        require_ok(response, 'PBS login-account query')
    notice = False
    try:
        if not pbs.query_stderr_ok(response):
            raise ValueError('PBS login-account query unavailable')
        if len(servers) != 1:
            raise ValueError('Conflicting PBS server identities for shared login account')
        server, = servers
        own, running, queued, live_names = _own_cores(response.stdout, jobs, username, server)
        notice = bool(response.stderr)
        _check_own_allocations(jobs, username, rows)
        try:
            held = _unobserved_cores(cfg, own, username, claimed, live_names)
        except (ValueError, OSError) as exc:
            raise ValueError('Shared-account local reservations could not be verified') from exc
        result = dict(occupied_queue_account=dict(server=server, committed=running + queued + held,
                                                  queued=queued + held))
    except ValueError as exc:
        result = dict(occupied_queue_error=str(exc))
    if notice:
        result['occupied_queue_notice'] = pbs.KEX_NOTICE_DETAIL
    for row in rows:
        row.update(result)
    return result


def account_refusal(cfg, row, cores):
    if row.get('occupied_queue_error'):
        return row['occupied_queue_error']
    servers = account_servers(cfg)
    if not servers:
        return None
    proof = row.get('occupied_queue_account')
    if (not isinstance(proof, dict) or servers != {proof.get('server')}
            or any(type(proof.get(k)) is not int or proof[k] < 0 for k in ('committed', 'queued'))
            or proof['queued'] > proof['committed']):
        return 'Complete PBS login-account usage is unverified'
    if cores > cfg['resources']['max_cores'] or proof['committed'] + cores > committed_cap(cfg):
        return 'PBS shared-account core limit exceeded'
    cap = optional_resource_caps(cfg).get('max_queued_cores')
    if cap is not None and proof['queued'] + cores > cap:
        return 'PBS shared-account queued core limit exceeded'
    return None


def _evidence_reason(row):
    if row.get('targeting_issue') == 'unseen_node_jobs':
        return 'pbsnodes lists allocated jobs absent from qstat; their ownership is unknown'
    if row.get('targeting_issue') == 'ambiguous_jobs':
        return 'PBS job identity, owner or state is ambiguous'
    return 'Node and job evidence is missing or contradictory'


def idle(row):
    """Display observed occupation separately from eligibility to submit."""
    if row.get('targeting_issue') == 'unseen_node_jobs':
        return 'occupied', 'pbsnodes reports allocations whose job details are not visible'
    if (row.get('targeting_consistent') is not True or row.get('targeting_issue') is not None
            or any(type(row.get(k)) is not int or row[k] < 0 for k in ('cores_used', 'jobs'))
            or type(row.get('targeting_reserved')) is not bool):
        return 'unknown', _evidence_reason(row)
    if row.get('state') != 'free' or row.get('cores_used') != 0 or row.get('jobs') != 0 or row.get('targeting_reserved'):
        return 'occupied', 'Node has allocations, queued named requests, or is not free'
    if 'empty_only_waiters_checked' in row and row['empty_only_waiters_checked'] is None:
        return 'unknown', _EMPTY_QUEUE_UNKNOWN
    if row.get('mem_assigned_gb') not in (None, 0):
        return 'unknown', 'Assigned memory contradicts idle node evidence'
    total = row.get('mem_total_gb')
    if (type(row.get('cores_total')) is not int or row['cores_total'] < 1
            or type(total) not in (int, float) or not math.isfinite(total) or total <= 0):
        return 'unknown', 'Node capacity or memory is unknown'
    return 'available', 'Snapshot candidate only; explicit choice and fresh admission required'


def admission(row, cores, mem_gb, cfg=None):
    """Apply the configured named-node rule using the original request size."""
    reason = None
    site = cfg.get('node_targeting', {}).get('occupied_policy', {}) if cfg else {}
    remaining = row.get('name') in site.get('remaining_nodes', [])
    assessment = capacity.evaluate_node(row, cores, mem_gb, scheduler='pbs', require_reported_slots=remaining)
    unseen = row.get('targeting_issue') == 'unseen_node_jobs'
    counts_valid = all(type(row.get(k)) is int and row[k] >= 0 for k in ('cores_used', 'jobs'))
    if not counts_valid or type(row.get('targeting_reserved')) is not bool:
        reason = _evidence_reason(row)
    elif remaining and (row['jobs'] > row['cores_used'] or (row['cores_used'] and not row['jobs'])):
        reason = 'PBS job count contradicts allocated CPU slots'
    elif (row.get('name') in site.get('empty_only', [])
          and (row.get('state') != 'free' or row['jobs'] or row['cores_used'] or row['targeting_reserved'])):
        reason = 'Site policy permits submission only to an empty node'
    elif unseen:
        if (row.get('targeting_consistent') is not False or row.get('capacity_cpu_consistent') is not True
                or not row['cores_used'] or not row['jobs']):
            reason = 'PBS allocation evidence is contradictory'
    elif row.get('targeting_consistent') is not True or row.get('targeting_issue') is not None:
        reason = _evidence_reason(row)
    elif (row['jobs'] or row['cores_used']) and 'targeting_issue' not in row:
        reason = 'Older snapshot lacks exact PBS job owner and slot checks'
    if not reason and unseen and not remaining and row.get('name') not in site.get('queue_nodes', []):
        reason = _evidence_reason(row) + '; site permission to queue on this occupied node is unverified'
    if not reason:
        reason = account_refusal(cfg, row, cores)
    if (not reason and row.get('name') in site.get('empty_only', [])
            and row.get('empty_only_waiters_checked') != site['queue']):
        reason = _EMPTY_QUEUE_UNKNOWN
    if reason:
        return dict(selectable=False, selectable_reason=reason, capacity=assessment)
    # Same supported PBS states as T156. Unknown availability alone cannot
    # distinguish an offline node from missing assigned-memory information.
    if row.get('state') not in ('free', 'job-busy', 'job-exclusive'):
        reason = 'Node state is unavailable or unsupported'
    elif remaining and row.get('capacity_cpu_consistent') is not True:
        reason = 'Remaining CPU slots cannot be verified'
    elif assessment['fits_total'] is not True:
        reason = '; '.join(assessment['reasons']) if remaining else 'Target capacity is unknown, inconsistent or insufficient'
    elif row['cores_used'] > row['cores_total']:
        reason = 'Node CPU allocation contradicts its total capacity'
    elif remaining and 'cores_available' not in assessment:
        reason = '; '.join(assessment['reasons'])
    elif remaining and assessment['cores_available'] < cores:
        reason = f"Only {assessment['cores_available']} CPU slots remain on this node; request requires {cores}"
    else:
        assigned = row.get('mem_assigned_bytes')
        # Unknown assigned memory is advisory. Known contradictory allocation
        # must not become admissible merely because capacity returns unknown.
        if assigned is not None and (type(assigned) is not int or assigned < 0
                or assigned > row['mem_total_bytes']
                or (assigned > 0 and row['cores_used'] == 0 and row['jobs'] == 0)):
            reason = 'Assigned memory contradicts node allocation evidence'
        elif (row['cores_used'] == 0 and row['jobs'] == 0
              and row.get('mem_assigned_gb') not in (None, 0)):
            # Preserve the old idle-memory contradiction even when exact
            # assigned bytes are unavailable (e.g. fractional-byte requests).
            reason = 'Assigned memory contradicts node allocation evidence'
        elif remaining:
            # On an empty node no running allocation can contribute a lower
            # bound. Occupied snapshots must explicitly attest even a zero.
            known = assigned
            if known is None:
                known = row.get('mem_assigned_min_bytes', None if row['cores_used'] else 0)
            if known is None:
                reason = 'Occupied snapshot lacks the checked memory lower bound; refresh the monitor'
            elif type(known) is not int or not 0 <= known <= row['mem_total_bytes']:
                reason = 'Assigned memory contradicts node allocation evidence'
            elif row['mem_total_bytes'] - known < mem_gb * 1024**3:
                reason = (f"Insufficient remaining memory on this node for the requested {mem_gb} GiB; "
                          f"at most {row['mem_total_bytes'] - known} bytes remain")
    eligible = ('Site permits queueing; login-account usage and reservations verified'
                if unseen else 'Total specs fit a named request; PBS decides queueing and placement')
    if remaining and not reason:
        memory = 'current available memory unknown' if row.get('mem_assigned_bytes') is None else 'remaining memory fits'
        eligible = f"Local policy allows request: {assessment['cores_available']} CPU slots remain; {memory}; PBS decides placement"
    return dict(selectable=reason is None,
                selectable_reason=reason or eligible,
                capacity=assessment)


def candidates(cfg, cluster='default', *, now=None):
    from ag.route import _snapshot
    selected = select_cluster(cfg, cluster)
    if 'node_targeting' not in selected:
        raise ValueError('Node targeting is not enabled for this entry')
    validate_policy(selected)
    source_cfg = (dict(clusters=cfg['_cluster_entries'], local=cfg['local'], _config_dir=cfg['_config_dir'])
                  if '_cluster_entries' in cfg else cfg)
    snapshot = _snapshot(source_cfg, cluster, now or datetime.now(timezone.utc))
    data = snapshot['data']
    rows = data['cluster'].get('nodes', []) if snapshot['fresh'] else []
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        rows = []
    policy = selected['node_targeting']
    groups = {n: i + 1 for i, group in enumerate(policy['priority']) for n in group}
    order = [n for g in policy['priority'] for n in g]
    order += [n for n in policy['denied_nodes'] if n not in order]
    result = []
    for i, name in enumerate(order):
        matches = [r for r in rows if r.get('name') == name]
        row = matches[0] if len(matches) == 1 else {}
        opts = options(selected, row.get('cores_total'))
        if name in policy['denied_nodes']:
            status, reason = 'forbidden', 'Submission to this node is forbidden'
        elif name in policy['restricted_nodes']:
            status, reason = 'restricted', 'Special CPU mapping/allocation remains unverified'
        elif not snapshot['fresh']:
            status, reason = 'stale', 'Monitor snapshot is unavailable, failed or stale'
        else:
            status, reason = idle(row)
            site = policy.get('occupied_policy', {})
            if (status == 'available' and name in site.get('empty_only', [])
                    and row.get('empty_only_waiters_checked') != site['queue']):
                status, reason = 'unknown', _EMPTY_QUEUE_UNKNOWN
        for o in opts:
            o.update(admission(row, o['cores'], o['mem_gb'], selected))
            # Keep the legacy display mapping. Exact/unknown capacity is
            # expressed by selectable, never relabelled as a missing tier.
            if row.get('mem_total_gb') is None or row['mem_total_gb'] < o['mem_gb']:
                o['tier'] = None
            if status in ('forbidden', 'restricted', 'stale'):
                o.update(selectable=False, selectable_reason=reason)
            elif o['tier'] is None and o['selectable']:
                o.update(selectable=False, selectable_reason='No configured tier fits this node and fraction')
        if status == 'available' and not any(o['tier'] for o in opts):
            status, reason = 'insufficient', 'No configured tier fits this node and fraction'
        selectable = any(o['selectable'] for o in opts)
        selectable_reason = next((o['selectable_reason'] for o in opts if o['selectable']),
                                 opts[0]['selectable_reason'] if opts else reason)
        result.append(dict(name=name, priority_group=groups.get(name), order=i + 1,
                           priority=i + 1, status=status, reason=reason, options=opts,
                           selectable=selectable, selectable_reason=selectable_reason))
    valid_until = ((datetime.fromisoformat(snapshot['sampled_at']) +
                    timedelta(seconds=3 * data['interval_seconds'])).isoformat()
                   if snapshot['fresh'] else None)
    return dict(schema='ag-node-targets/1', cluster=cluster, fresh=snapshot['fresh'],
                sampled_at=snapshot['sampled_at'], valid_until=valid_until, nodes=result)


def prepare(cfg, cluster, template, tier, target, fraction):
    selected = select_cluster(cfg, cluster)
    if 'node_targeting' not in selected:
        if target is not None or fraction is not None:
            raise ValueError('Node selection requires an opted-in PBS entry')
        return None
    if template != 'gaussian':
        raise ValueError('Node targeting initially supports only Gaussian')
    allowed(selected, target)
    fraction = fraction or '1/2'
    rows = candidates(cfg, cluster)['nodes']
    row = next(r for r in rows if r['name'] == target)
    option = next((o for o in row['options'] if o['fraction'] == fraction), None)
    if not row['selectable']:
        raise ValueError('Target node is unavailable: ' + (option or row)['selectable_reason'])
    if option is None or option['tier'] != tier or (not option['selectable'] and option['capacity']['fits_total'] is not True):
        raise ValueError('Selected tier must match target slots, fraction and memory')
    if not option['selectable']:
        raise ValueError('Target node is unavailable: ' + option['selectable_reason'])
    return dict(name=target, fraction=fraction, slots=option['cores'] * int(fraction[-1]),
                queue=selected['scheduler']['queue'])


def validate_binding(cfg, m):
    binding = m.get('node_target')
    if binding is None:
        if 'node_targeting' in cfg:
            raise ValueError('Explicit target node is required; no generic PBS fallback')
        return
    if (not isinstance(binding, dict) or set(binding) != {'name', 'fraction', 'slots', 'queue'}
            or m.get('scheduler') != 'pbs' or m['template'] != 'gaussian'):
        raise ValueError('Invalid immutable node binding')
    allowed(cfg, binding['name'])
    if binding['queue'] != cfg['scheduler']['queue']:
        raise ValueError('Target queue changed since preparation')
    r = resource(binding['slots'], binding['fraction'])
    if any(m[k] != r[k] for k in r) or cfg['resources']['tiers'].get(m['tier']) != r:
        raise ValueError('Bound node resources differ from the configured tier')


def fresh_check(cfg, m, transport, username=None, claimed=False):
    from ag.status import parse_jobs
    validate_binding(cfg, m)
    servers = account_servers(cfg)
    if 'node_target' not in m and not servers:
        return
    jobs = parse_jobs(require_ok(transport.run(remote.jobs()), 'target qstat'))
    text = require_ok(transport.run(remote.nodes()), 'target pbsnodes')
    rows = strict_nodes(text, jobs, next(iter(servers), None), username)
    account = observe_occupied_account(cfg, rows, jobs, username, transport, m if claimed else None)
    if account.get('occupied_queue_notice'):
        print(account['occupied_queue_notice'], file=sys.stderr)
    if 'node_target' not in m:
        refusal = account_refusal(cfg, account, m['cores'])
        if refusal:
            raise ValueError(refusal)
        return
    matches = [r for r in rows if r['name'] == m['node_target']['name']]
    if len(matches) != 1:
        raise ValueError('Target node missing or ambiguous')
    row = matches[0]
    if row['cores_total'] != m['node_target']['slots']:
        raise ValueError('Target capacity changed or insufficient; stop')
    site = cfg['node_targeting'].get('occupied_policy', {})
    if row['name'] in site.get('empty_only', []):
        from ag.monitor import parse_queues
        result = transport.run(remote.queues())
        queues = parse_queues(require_ok(result, 'target qstat queues'),
                              include_total=True, include_waiting=True)
        queue_ok = pbs.query_stderr_ok(result)
        pbs.observe_empty_queue(site, [row], queues if queue_ok else [], jobs)
        if queue_ok and result.stderr and not account.get('occupied_queue_notice'):
            print(pbs.KEX_NOTICE_DETAIL, file=sys.stderr)
    decision = admission(row, m['cores'], m['mem_gb'], cfg)
    if not decision['selectable']:
        raise ValueError('Target node unavailable: ' + decision['selectable_reason'] + '; stop')


def placement(m, job):
    """Exact identities only: no hostname-prefix or short/FQDN guessing."""
    b = m['node_target']
    hosts = job.get('exec_host', '') if job else ''
    evidence = dict(target=b['name'], exec_host=hosts, state='pending')
    if job is None or job.get('job_state') in ('Q', 'H', 'W', 'T'):
        return evidence
    # An allocated exec_host on a queued job is not evidence of execution.
    if job.get('job_state') not in ('R', 'E', 'S', 'C') or not hosts:
        evidence['state'] = 'unverified'
        return evidence
    count, names, slots_by_node = 0, set(), {}
    try:
        for host in hosts.split('+'):
            n, sep, slots = host.partition('/')
            if not sep:
                raise ValueError('Missing slot identity')
            names.add(node_name(n))
            slots_by_node.setdefault(n, []).append(slots)
        count = sum(pbs.slot_count(','.join(parts)) for parts in slots_by_node.values())
        evidence['state'] = 'verified' if names == {b['name']} and count == m['cores'] else 'mismatch'
    except ValueError:
        evidence['state'] = 'mismatch'
    return evidence


def summary(m):
    if 'node_target' not in m:
        return ''
    b = m['node_target']
    return (f"\nTarget node: {b['name']} | fraction {b['fraction']} | "
            f"{m['cores']} cores / {m['mem_gb']} GB | queue {b['queue']}\n")


@contextmanager
def start_placement(cfg, path, m, current, job, start):
    """Prove the *submitted bytes* executed a known guard before their receipt.

    Full bundle/template equality alone is not an ordering proof. Require the
    pinned guard at the first executable byte of that very script as well.
    Large reads stay outside the publication lock; pinned sources are rechecked
    inside it. The receipt has already passed status.read_receipt validation.
    """
    retained = (current.get('node_placement', {}).get('state') == 'verified'
                and (job is None or (job.get('job_state') == 'C' and not job.get('exec_host'))))
    if (start is None or retained
            or (job is not None and (job.get('exec_host')
                or job.get('job_state') not in ('R', 'E', 'S', 'C')))):
        yield None, lambda: None
        return
    from ag import attempt, render, submission
    from ag.facts import _publication_pin, _publication_unchanged
    with ExitStack() as handles:
        inputs = path / 'inputs'
        proofs = [_publication_pin(p, handles) for p in
                  (path.parent.parent, path.parent, path, path / 'manifest.json',
                   path / 'submission.json', path / 'status.json')]
        proofs.append(_publication_pin(inputs, handles, contents=True))
        proofs.extend(_publication_pin(p, handles) for p in inputs.iterdir())

        def verify():
            for proof in proofs:
                _publication_unchanged(proof)

        if (attempt.read_manifest(path) != m or 'cluster' not in m
                or not (path / 'submission.json').is_file()):
            raise ValueError('Start placement requires the unchanged submitted manifest and binding')
        job_id = submission.verified_job(path, m, current)
        if start.get('PBS_JOBID') != job_id:
            raise ValueError('Start placement receipt job identity mismatch')
        files = attempt.verified_files(cfg, path, m)
        script = files['job.pbs']
        guard = (render.TEMPLATES / 'node-target.pbs').read_bytes()
        if sha256(guard).hexdigest() != _START_GUARD_SHA256:
            raise ValueError('Unknown node start guard; placement cannot be proven')
        expected = Template(guard.decode()).substitute(
            target_node=m['node_target']['name'], cores=m['cores']).encode()
        # Only the reviewed shell and whole comment lines may precede the
        # guard. A copied guard in a later command, function or here-doc fails.
        shebang, newline, body = script.partition(b'\n')
        if shebang != b'#!/bin/sh' or not newline or b'\x00' in script:
            raise ValueError('Unrecognized node start script')
        while body.startswith(b'#'):
            _, newline, body = body.partition(b'\n')
            if not newline:
                break
        if not body.startswith(expected.partition(b'\n')[2]):
            raise ValueError('Known node start guard is not first in the submitted script')
        verify()
        yield dict(state='verified', source='node-guard+ag-start.json',
                   target=m['node_target']['name'], exec_host='',
                   job_id=submission.qualified(m, job_id), start_receipt=start,
                   script_sha256=sha256(script).hexdigest(),
                   bundle_sha256=m['bundle_sha256'], guard_sha256=_START_GUARD_SHA256), verify


def retain_placement(path, m, job, *, start_evidence=None):
    from ag import state
    current = state.read(path)
    evidence = placement(m, job)
    evidence['observed_at'] = datetime.now(timezone.utc).isoformat()
    # Never erase earlier verified execution identity after scheduler cleanup.
    previous = current.get('node_placement', {})
    if previous.get('state') == 'verified' and (job is None or (job.get('job_state') == 'C' and not job.get('exec_host'))):
        return current
    if start_evidence is not None and not (job or {}).get('exec_host'):
        evidence = dict(start_evidence, observed_at=evidence['observed_at'])
    result = state.write(path, current['state'], node_placement=evidence,
                         exit_status=current.get('exit_status'), note=current.get('note'))
    if evidence['state'] in ('mismatch', 'unverified'):
        raise ValueError('Target placement is not verified; stop automatic operations; do not cancel automatically')
    return result


def observe(cfg, path, m, job_id, transport):
    from ag import status, state
    try:
        result = transport.run(remote.jobs(job_id))
        if result.returncode and status.scheduler_absent(result):
            return retain_placement(path, m, None)
        jobs = status.parse_jobs(require_ok(result, 'target placement qstat'))
        if len(jobs) != 1 or jobs[0]['job_id'] != job_id or jobs[0].get('Job_Name') != m['pbs_job_name']:
            raise ValueError('Target placement scheduler identity mismatch')
    except (OSError, ValueError):
        current = state.read(path)
        state.write(path, current['state'], node_placement=dict(state='unverified', target=m['node_target']['name']),
                    note='Job accepted; placement query failed; stop')
        raise
    return retain_placement(path, m, jobs[0])
