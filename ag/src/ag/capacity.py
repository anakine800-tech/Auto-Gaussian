"""Advisory single-node capacity from local snapshots; no transport or writes."""
from datetime import datetime, timedelta, timezone
import json
import math

from ag.config import RESOURCE_TIERS, load_config, scheduler_kind, select_cluster
from ag.remote import slurm_token


def _count(value):
    return type(value) is int and value >= 0


def _memory(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def evaluate_node(node, cores, mem_gb, *, scheduler, partition=None):
    """Assess one identified node, using scheduler allocation, never RSS."""
    result = dict(name=node.get('name'), fits_total=None, availability='unknown', reasons=[],
                  cpu_source=node.get('cpu_source') or ('pbsnodes/exec_host' if scheduler == 'pbs' else None),
                  memory_source=node.get('memory_source') or
                  ('PBS available/assigned memory or Torque job requests' if scheduler == 'pbs' else None))
    reasons = result['reasons']
    if (node.get('capacity_error') or node.get('targeting_consistent') is False
            or (scheduler == 'slurm' and node.get('partition') != partition)):
        reasons.append('节点身份或观测相互矛盾')
        return result
    total, used = node.get('cores_total'), node.get('cores_used')
    memory, assigned = node.get('mem_total_gb'), node.get('mem_assigned_gb')
    if not (_count(total) and total > 0 and _memory(memory) and memory > 0):
        reasons.append('节点总核数或总内存未知')
        return result
    result['fits_total'] = cores <= total and mem_gb <= memory
    if not result['fits_total']:
        result.update(availability='not_applicable')
        reasons.append('请求超过单节点总核数或总内存')
        return result
    state = node.get('state')
    states = ('free', 'job-busy', 'job-exclusive') if scheduler == 'pbs' else (
        'idle', 'mixed', 'allocated', 'completing')
    if state not in states or (scheduler == 'slurm' and node.get('partition_state') != 'up'):
        reasons.append('节点或分区状态不允许确认当前容量')
        return result
    if not (_count(used) and used <= total and _memory(assigned) and assigned <= memory):
        reasons.append('节点已分配核数或内存未知或无效')
        return result
    if scheduler == 'slurm' and state == 'idle' and used:
        reasons.append('空闲节点状态与CPU分配矛盾')
        return result
    idle = total - used
    if scheduler == 'slurm':
        idle, other = node.get('cores_idle'), node.get('cores_other')
        if not (_count(idle) and _count(other) and used + idle + other == total):
            reasons.append('节点CPU分配明细未知或矛盾')
            return result
        if other:
            reasons.append('节点存在不可用CPU，当前容量未知')
            return result
    result.update(cores_available=idle, mem_available_gb=memory - assigned)
    if idle >= cores and memory - assigned >= mem_gb and state in ('free', 'idle', 'mixed'):
        result['availability'] = 'enough'
        reasons.append('同一节点的可用核数和已分配口径剩余内存足够')
    else:
        result['availability'] = 'queue'
        reasons.append('节点总规格满足，当前分配或占用不足以立即容纳请求')
    return result


def assess(cfg, cluster, tier, target_node=None, *, now=None):
    """Read existing configuration/snapshot only; does not authorize submission."""
    # Lazy import lets route reuse this module without a module import cycle.
    from ag.route import _snapshot
    selected = select_cluster(cfg, cluster)
    scheduler = scheduler_kind(selected)
    if tier not in RESOURCE_TIERS:
        raise ValueError('Unknown resource tier')
    if target_node is not None:
        slurm_token(target_node)  # Exact local lookup only; never a remote selector.
    request = selected['resources']['tiers'].get(tier)
    result = dict(cluster=cluster, tier=tier, target_node=target_node,
                  cores=request['cores'] if request else None,
                  mem_gb=request['mem_gb'] if request else None,
                  sampled_at=None, valid_until=None, snapshot_fresh=False,
                  fits_total=None, availability='unknown', reasons=[],
                  cpu_source=None, memory_source=None, nodes=[])
    if request is None:
        result['reasons'] = ['入口未配置该档位']
        return result
    snapshot = _snapshot(cfg, cluster, now or datetime.now(timezone.utc))
    result.update(sampled_at=snapshot['sampled_at'], snapshot_fresh=snapshot['fresh'])
    if not snapshot['fresh']:
        result['reasons'] = ['快照缺失、失败、过期或身份无效']
        return result
    data = snapshot['data']
    result['valid_until'] = (datetime.fromisoformat(snapshot['sampled_at']) +
                             timedelta(seconds=3 * data['interval_seconds'])).isoformat()
    observed = data['cluster']
    nodes = observed.get('nodes')
    if observed.get('nodes_error') or not isinstance(nodes, list) or not nodes:
        result['reasons'] = ['无可用节点观测；分区汇总不能代替单节点容量']
        return result
    unique, invalid = {}, False
    for node in nodes:
        try:
            name = slurm_token(node['name'])
        except (KeyError, TypeError, ValueError):
            invalid = True
            continue
        if name in unique and unique[name] != node:
            unique[name] = dict(unique[name], capacity_error='Conflicting duplicate node records')
        else:
            unique[name] = node
    policy = selected.get('node_targeting')
    for name, node in unique.items():
        if target_node is not None and name != target_node:
            continue
        if policy and (name not in policy['allowed_nodes'] or name in policy['denied_nodes']
                       or name in policy['restricted_nodes']):
            continue
        result['nodes'].append(evaluate_node(node, **request, scheduler=scheduler,
                                             partition=selected.get('partition')))
    rows = result['nodes']
    if not rows:
        result['reasons'] = ['目标节点没有精确观测或没有符合入口配置的节点']
        return result
    fits = [row['fits_total'] for row in rows]
    result['fits_total'] = True if True in fits else False if not invalid and all(v is False for v in fits) else None
    states = [row['availability'] for row in rows]
    if 'enough' in states:
        result['availability'] = 'enough'
    elif 'unknown' in states or invalid:
        result['availability'] = 'unknown'
    elif 'queue' in states:
        result['availability'] = 'queue'
    else:
        result['availability'] = 'not_applicable'
    chosen = next((row for row in rows if row['availability'] == result['availability']), None)
    result['reasons'] = (chosen['reasons'][:] if chosen else ['节点观测缺少精确身份'])
    if chosen:
        result.update(cpu_source=chosen['cpu_source'], memory_source=chosen['memory_source'])
    return result


def run(args):
    result = assess(load_config(), args.cluster, args.tier, args.target_node)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          f"{result['cluster']} | {result['availability']} | {'；'.join(result['reasons'])}")
    return 0


def register(subparsers):
    parser = subparsers.add_parser('capacity', help='Read local snapshots for single-node capacity advice')
    parser.add_argument('--cluster', required=True)
    parser.add_argument('--tier', choices=RESOURCE_TIERS, required=True)
    parser.add_argument('--target-node')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
