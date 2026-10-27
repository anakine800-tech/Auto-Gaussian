"""Opt-in PBS targeting. Suggestions are local; admission always re-queries PBS."""
from datetime import datetime, timedelta, timezone
import math
import re

from ag import pbs, remote
from ag.config import RESOURCE_TIERS, scheduler_kind, select_cluster
from ag.transport import require_ok

FRACTIONS = ('1/2', '1/4')


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
            or set(p) != {'allowed_nodes', 'denied_nodes', 'priority', 'restricted_nodes'}):
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


def strict_nodes(text, jobs):
    """Cross-check both scheduler views; contradictory/missing facts fail closed.

    This is deliberately stricter than display parsing. It is not an atomic
    reservation: another scheduler client may change state after these reads.
    """
    rows = pbs.parse_nodes(text, jobs)
    names = [r['name'] for r in rows]
    if len(names) != len(set(names)):
        raise ValueError('Ambiguous duplicate PBS node identity')
    derived = pbs.parse_nodes(text, [])
    blocks = {}
    name, key = None, None
    for line in text.splitlines():
        if line and not line[0].isspace():
            name, key = line.strip(), None
            blocks[name] = {}
        elif name and ' = ' in line:
            k, v = line.strip().split(' = ', 1)
            blocks[name][k] = v
            key = k
        elif name and key and line.strip():
            blocks[name][key] += line.strip()
    allocations = {n: 0 for n in names}
    jobsets = {n: set() for n in names}
    ambiguous = len({j['job_id'] for j in jobs}) != len(jobs)
    reserved = set()
    for j in jobs:
        if j.get('job_state') == 'C':
            continue
        if j.get('job_state') not in ('Q', 'H', 'W', 'T', 'R', 'E', 'S'):
            ambiguous = True
        hosts = j.get('exec_host', '')
        if j.get('job_state') in ('R', 'E', 'S') and not hosts:
            ambiguous = True
        for host in filter(None, hosts.split('+')):
            n, sep, slot = host.partition('/')
            if not sep or n not in allocations:
                ambiguous = True
                continue
            allocations[n] += pbs.slot_count(slot)
            jobsets[n].add(j['job_id'])
        # A queued named request from another computer is already competition.
        for chunk in j.get('Resource_List.nodes', '').split('+'):
            n = chunk.split(':')[0]
            if n in allocations:
                reserved.add(n)
    for row, raw in zip(rows, derived):
        n, attrs = row['name'], blocks[row['name']]
        count = allocations[n]
        consistent = not ambiguous
        if 'np' in attrs and 'resources_available.ncpus' in attrs:
            consistent &= attrs['np'] == attrs['resources_available.ncpus']
        if 'jobs' in attrs:
            reported_ids = set(re.findall(r'/([^,\s]+)', attrs['jobs']))
            consistent &= (raw['cores_used'] == count and raw['jobs'] == len(jobsets[n])
                           and reported_ids == jobsets[n])
        if 'resources_assigned.ncpus' in attrs:
            consistent &= attrs['resources_assigned.ncpus'] == str(count)
        consistent &= 0 <= count <= row['cores_total']
        row.update(targeting_consistent=consistent, cores_used=max(row['cores_used'], count),
                   jobs=max(row['jobs'] or 0, len(jobsets[n])), targeting_reserved=n in reserved)
    return rows


def idle(row):
    if (row.get('targeting_consistent') is not True
            or any(type(row.get(k)) is not int or row[k] < 0 for k in ('cores_used', 'jobs'))
            or type(row.get('targeting_reserved')) is not bool):
        return 'unknown', 'Node and job evidence is missing or contradictory'
    if row.get('state') != 'free' or row.get('cores_used') != 0 or row.get('jobs') != 0 or row.get('targeting_reserved'):
        return 'occupied', 'Node has allocations, queued named requests, or is not free'
    if row.get('mem_assigned_gb') not in (None, 0):
        return 'unknown', 'Assigned memory contradicts idle node evidence'
    total = row.get('mem_total_gb')
    if (type(row.get('cores_total')) is not int or row['cores_total'] < 1
            or type(total) not in (int, float) or not math.isfinite(total) or total <= 0):
        return 'unknown', 'Node capacity or memory is unknown'
    return 'available', 'Snapshot candidate only; explicit choice and fresh admission required'


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
        for o in opts:
            if row.get('mem_total_gb') is None or row['mem_total_gb'] < o['mem_gb']:
                o['tier'] = None
        if status == 'available' and not any(o['tier'] for o in opts):
            status, reason = 'insufficient', 'No configured tier fits this node and fraction'
        result.append(dict(name=name, priority=i + 1, status=status, reason=reason, options=opts))
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
    if row['status'] != 'available':
        raise ValueError('Target node is unavailable: ' + row['reason'])
    option = next((o for o in row['options'] if o['fraction'] == fraction and o['tier'] == tier), None)
    if option is None:
        raise ValueError('Selected tier must match target slots, fraction and memory')
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


def fresh_check(cfg, m, transport):
    from ag.status import parse_jobs
    validate_binding(cfg, m)
    if 'node_target' not in m:
        return
    jobs = parse_jobs(require_ok(transport.run(remote.jobs()), 'target qstat'))
    text = require_ok(transport.run(remote.nodes()), 'target pbsnodes')
    rows = strict_nodes(text, jobs)
    matches = [r for r in rows if r['name'] == m['node_target']['name']]
    if len(matches) != 1:
        raise ValueError('Target node missing or ambiguous')
    row = matches[0]
    if idle(row)[0] != 'available':
        raise ValueError('Target node no longer idle or evidence inconsistent; stop')
    if row['cores_total'] != m['node_target']['slots'] or row['mem_total_gb'] < m['mem_gb']:
        raise ValueError('Target capacity changed or insufficient; stop')


def placement(m, job):
    """Exact identities only: no hostname-prefix or short/FQDN guessing."""
    b = m['node_target']
    hosts = job.get('exec_host', '') if job else ''
    evidence = dict(target=b['name'], exec_host=hosts, state='pending')
    if not hosts:
        if job and job.get('job_state') in ('R', 'E', 'C', 'S'):
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


def retain_placement(path, m, job):
    from ag import state
    current = state.read(path)
    evidence = placement(m, job)
    evidence['observed_at'] = datetime.now(timezone.utc).isoformat()
    # Never erase earlier verified execution identity after scheduler cleanup.
    previous = current.get('node_placement', {})
    if previous.get('state') == 'verified' and (not job or (job.get('job_state') == 'C' and not job.get('exec_host'))):
        return current
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
