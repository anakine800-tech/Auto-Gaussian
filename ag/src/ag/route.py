"""Advisory routing from local monitor snapshots; no transport or file writes."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from ag.config import (load_config, select_cluster, scheduler_kind, shared_clusters,
                       committed_cap, optional_resource_caps, validate_routing)
from ag.study import identifier


TEMPLATES = ('gaussian', 'gaussian-cp', 'multiwfn', 'crest', 'xtb')
TIERS = ('mini', 'simple', 'general', 'complex')
UNKNOWN = '快照非最新或缺字段'
READY, FULL, DENIED = '可以马上运行', '没地方', '不允许'


def _count(value):
    return type(value) is int and value >= 0


def _memory(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


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
        if name == 'default' and named.exists() and legacy.exists():
            raise ValueError('Ambiguous default snapshots')
        if any(p.is_symlink() for p in (root.parent, root, path.parent, path)):
            raise ValueError('Redirected snapshot')
        with path.open('rb') as handle:
            raw = handle.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Oversize snapshot')
        data = json.loads(raw)
        stamp = _timestamp(data['sampled_at'])
        interval = data['interval_seconds']
        if type(interval) is not int or not 30 <= interval <= 600:
            raise ValueError('Unknown sampling interval')
        if (data['schema'] != 'ag-monitor/1' or data['ok'] is not True
                or data.get('error') or data.get('config_removed')
                or not 0 <= (now - stamp).total_seconds() <= 3 * interval):
            raise ValueError('Failed or stale snapshot')
        if (not isinstance(data['own'], dict) or not isinstance(data['cluster'], dict)
                or data['cluster'].get('name', name) != name
                or data['cluster'].get('scheduler', scheduler_kind(select_cluster(cfg, name)))
                != scheduler_kind(select_cluster(cfg, name))):
            raise ValueError('Invalid snapshot identity')
        return dict(data=data, sampled_at=stamp.isoformat(), fresh=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        # Never echo raw JSON, errors, node names, account names or paths.
        return dict(data=None, sampled_at=stamp.isoformat() if stamp else None, fresh=False)


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


def _available_memory(row, total, used, required):
    # Missing T114 fields differ from explicitly unknown memory (G7).
    if total not in row or used not in row:
        return False, f'{UNKNOWN}：内存字段缺失'
    a, b = row[total], row[used]
    if any(value is not None and not _memory(value) for value in (a, b)):
        return False, f'{UNKNOWN}：内存数据无效'
    if a is None or b is None:
        return True, '内存未知'
    if b > a:
        return False, f'{UNKNOWN}：内存数据无效'
    if a - b < required:
        return False, '空闲内存不足'
    return True, None


def _hardware(data, scheduler, cores, memory):
    cluster = data['cluster']
    hardware = cluster.get('hardware')
    if not isinstance(hardware, dict) or 'cores_idle' not in hardware:
        return [f'{UNKNOWN}：硬件字段缺失'], []
    if scheduler == 'slurm':
        idle = hardware['cores_idle']
        if not _count(idle):
            return [f'{UNKNOWN}：空闲核数未知'], []
        reasons = [] if idle >= cores else ['空闲核数不足']
        fits, note = _available_memory(hardware, 'mem_total_gb', 'mem_allocated_gb', memory)
        return reasons + ([note] if not fits else []), [note] if fits and note else []
    nodes = cluster.get('nodes')
    if not isinstance(nodes, list):
        return [f'{UNKNOWN}：节点字段缺失'], []
    reasons, unknown_fit = [], False
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('state'), str):
            reasons.append(f'{UNKNOWN}：节点状态未知')
            continue
        if node['state'] != 'free':
            continue
        total, used = node.get('cores_total'), node.get('cores_used')
        if not _count(total) or not _count(used) or used > total:
            reasons.append(f'{UNKNOWN}：空闲核数未知')
            continue
        if total - used < cores:
            reasons.append('free 节点空闲核数不足')
            continue
        fits, note = _available_memory(node, 'mem_total_gb', 'mem_assigned_gb', memory)
        if fits and note is None:
            return [], []
        if fits:
            unknown_fit = True
        else:
            reasons.append(note)
    if unknown_fit:
        return [], ['内存未知']
    if not _count(hardware['cores_idle']):
        reasons.append(f'{UNKNOWN}：空闲核数未知')
    return list(dict.fromkeys(reasons)) or ['没有符合要求的 free 节点'], []


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


def suggest(cfg, template, tier, study=None, *, now=None):
    if template not in TEMPLATES or tier not in TIERS:
        raise ValueError('Unknown template or tier')
    if study is not None:
        identifier(study)
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
        resource = selected['resources']['tiers'][tier]
        cores, memory = resource['cores'], resource['mem_gb']
        snapshot = snapshots[name]
        row = dict(name=name, display_name=selected.get('display_name', name),
                   cores=cores, mem_gb=memory, conclusion=DENIED, reasons=[], notes=[],
                   sampled_at=snapshot['sampled_at'], snapshot_fresh=snapshot['fresh'],
                   personal_allowed=False, usage_source=None, in_order=name in (order or []))
        if not _enabled(selected, template):
            row['reasons'] = ['不允许该模板（入口限制或程序未配置）']
        else:
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
                hardware_reasons, notes = _hardware(data, scheduler_kind(selected), cores, memory)
                reasons.extend(hardware_reasons)
                row['notes'] = notes
            row.update(conclusion=FULL if reasons else READY, reasons=list(dict.fromkeys(reasons)))
        rows.append(row)
    eligible = [r for r in rows if r['in_order'] and r['personal_allowed']]
    chosen = next((r for r in eligible if r['conclusion'] == READY), None)
    queued = chosen is None
    chosen = chosen or next(iter(eligible), None)
    recommendation = None
    if chosen:
        recommendation = dict(name=chosen['name'], needs_queue=queued,
                              reason='需要排队' if queued else '可以马上运行',
                              reasons=chosen['reasons'] + chosen['notes'])
    message = ('未配置路由顺序' if order is None else
               f"都需要排队：建议排在 {chosen['name']}" if chosen and queued else
               f"建议：{chosen['name']}" if chosen else
               '无建议：顺序中没有本人上限允许的入口')
    return dict(template=template, tier=tier, study=study, order=order, clusters=rows,
                recommendation=recommendation, message=message)


def format_result(result):
    lines = ['入口（显示名） | 结论 | 原因 | 快照时间']
    for row in result['clusters']:
        name = row['name']
        if row['display_name'] != name:
            name = f"{row['display_name']}（{name}）"
        reasons = row['reasons'] + row['notes'] or ['本人上限及硬件满足，未见他人排队']
        lines.append(f"{name} | {row['conclusion']} | {'；'.join(reasons)} | {row['sampled_at'] or '未知'}")
    return '\n'.join([*lines, result['message']])


def prepare_hint(cfg, manifest):
    # Advice must never turn a successful preparation into a failed operation.
    if 'routing' not in cfg:
        return ''
    try:
        result = suggest(cfg, manifest['template'], manifest['tier'], manifest['study_id'])
        chosen = result['recommendation']
        if not chosen or chosen['name'] == manifest.get('cluster', 'default'):
            return ''
        row = next(r for r in result['clusters'] if r['name'] == chosen['name'])
        if not row['snapshot_fresh']:
            return ''
        reason = '；'.join([chosen['reason'], *chosen['reasons']])
        return (f"\n路由建议为 {chosen['name']}（{reason}）；"
                f"本次按 --cluster {manifest.get('cluster', 'default')} 准备。")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return ''


def run(args):
    result = suggest(load_config(), args.template, args.tier, args.study)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_result(result))
    return 0


def register(subparsers):
    parser = subparsers.add_parser('route', help='Read local monitor snapshots for routing advice')
    parser.add_argument('--template', choices=TEMPLATES, required=True)
    parser.add_argument('--tier', choices=TIERS, required=True)
    parser.add_argument('--study')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
