"""Read-only scheduler sampling; all writes stay in the local monitor cache."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from ag import remote, status, slurm, attempt, budget
from ag.config import load_config, select_cluster, scheduler_kind, committed_cap, shared_clusters, optional_resource_caps
from ag.pbs import parse_nodes
from ag.transport import SSHTransport, redact_stderr, require_ok


HISTORY_BYTES = 5 * 1024 * 1024
STORAGE_INTERVAL = 3600
STORAGE_TIMEOUT = 30


class MonitorTransport(SSHTransport):
    """Keep the read-only allowlist, but report timeouts in this round immediately."""

    def _perform(self, operation):
        return operation()


def watch_seconds(value):
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('--watch must be an integer from 60 to 600') from exc
    if not 60 <= seconds <= 600:
        raise argparse.ArgumentTypeError('--watch must be from 60 to 600 seconds')
    return seconds


def login_user(cfg):
    # ssh -G evaluates local configuration (including Include/Host rules) and
    # exits without connecting. This avoids a fourth remote identity command.
    try:
        result = subprocess.run(
            ['ssh', '-G', '-F', cfg['ssh']['config_file'], cfg['ssh']['host']],
            capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise OSError('Local SSH configuration lookup timed out') from exc
    if result.returncode:
        raise OSError('Local SSH configuration lookup failed: ' + result.stderr)
    users = [line.split()[1] for line in result.stdout.splitlines()
             if line.startswith('user ') and len(line.split()) == 2]
    if len(users) != 1 or not re.fullmatch(r'[A-Za-z0-9_.-]+', users[0]):
        raise ValueError('Cannot identify SSH login user')
    return users[0]


def parse_queues(text):
    rows, header = [], None
    for line in text.splitlines():
        fields = line.split()
        if not fields or set(''.join(fields)) == {'-'}:
            continue
        if fields[0] == 'Queue':
            header = fields
            if 'Run' not in header or 'Que' not in header:
                raise ValueError('Unrecognized qstat queue header')
            continue
        if header is None or len(fields) != len(header):
            raise ValueError('Unrecognized qstat queue row')
        running, queued = fields[header.index('Run')], fields[header.index('Que')]
        if not running.isdigit() or not queued.isdigit():
            raise ValueError('Invalid queue counts')
        rows.append(dict(name=fields[0], running=int(running), queued=int(queued)))
    return rows


def local_attempts(root, cluster='default', scheduler=None):
    return [dict(job_id=job, state=current['state'], study=m['study_id'], attempt=path.name)
            for path, m, current, job in attempt.local_records(root, cluster, scheduler)
            if job is not None]


def observation(cfg, transport, username, *, storage_state=None):
    if scheduler_kind(cfg) == 'slurm':
        return slurm_observation(cfg, transport, username, storage_state=storage_state)
    jobs = status.parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat jobs'))
    # Use submit's exact all-user validation and non-C reservation accounting.
    used = status.occupied(jobs, username)
    queues = parse_queues(require_ok(transport.run(remote.queues()), 'qstat queues'))
    nodes = parse_nodes(require_ok(transport.run(remote.nodes()), 'pbsnodes'), jobs)
    attempts = local_attempts(Path(cfg['local']['studies_root']), cfg.get('_cluster', 'default'), 'pbs')
    by_job = {}
    for item in attempts:
        # Do not silently attach a scheduler job to the wrong copied Attempt.
        if item['job_id'] in by_job:
            raise ValueError(f'Multiple local Attempts record the same exact job ID: {by_job[item["job_id"]]["attempt"]}, {item["attempt"]}')
        by_job[item['job_id']] = item
    own = []
    for job in jobs:
        if job['Job_Owner'].split('@')[0] != username:
            continue
        link = by_job.get(job['job_id'], {})
        own.append(dict(job_id=job['job_id'], name=job.get('Job_Name'), state=job['job_state'],
                        queue=job.get('queue'), cores=status.occupied([job], username),
                        mem=job.get('Resource_List.mem'), walltime_used=job.get('resources_used.walltime'),
                        walltime_limit=job.get('Resource_List.walltime'),
                        start_time=job.get('start_time', job.get('start_time_epoch')),
                        study=link.get('study'), attempt=link.get('attempt')))
    scheduler = {job['job_id']: job for job in jobs}
    warnings = []
    for item in attempts:
        job = scheduler.get(item['job_id'])
        kind, detail = None, None
        if item['state'] in ('finished', 'fetched', 'cancelled', 'interrupted') and job and job['job_state'] in ('R', 'Q', 'E'):
            kind, detail = 'scheduler-residue', '需人工确认后 ag cancel'
        elif item['state'] in ('submitted', 'running') and job is None:
            kind, detail = 'absent-from-scheduler', '运行 ag status 核对'
        if kind:
            warnings.append(dict(kind=kind, job_id=item['job_id'], study=item['study'],
                                 attempt=item['attempt'], detail=detail))
    cap = cfg['resources']['max_cores']
    total_cap = committed_cap(cfg)
    running, queued = status.core_breakdown(jobs, username)
    if used > total_cap:
        warnings.append(dict(kind='over-cap', job_id=None, study=None, attempt=None,
                             detail=f'本人占用 {used} 核，超过上限 {total_cap} 核'))
    if cfg.get('_cluster'):
        for row in own + warnings:
            if row.get('job_id'):
                row['job_id'] = cfg['_cluster'] + ':' + row['job_id']
    return dict(own=dict(cores_in_use=used, core_cap=cap, jobs=own,
                         cores_running=running, cores_queued=queued, committed_cap=total_cap,
                         **shared_fields(cfg)),
                cluster=dict(nodes=nodes, queues=queues,
                             cores_total=sum(n['cores_total'] for n in nodes),
                             cores_used=sum(n['cores_used'] for n in nodes)), warnings=warnings)


def cache_dir(cfg):
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    if cfg.get('_cluster'):
        root = root / cfg['_cluster']
    # A redirected cache/history could otherwise overwrite study files.
    for path in (root.parent, root, *(root / name for name in ('latest.json', 'history.jsonl', 'history.1.jsonl'))):
        if path.is_symlink():
            raise ValueError('Monitor cache must not contain symbolic links')
    root.mkdir(parents=True, exist_ok=True)
    return root


def publish(root, snapshot):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root,
                                         prefix='.latest-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / 'latest.json')
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    summary = {key: snapshot[key] for key in ('sampled_at', 'interval_seconds', 'ok', 'error', 'last_ok_at')}
    summary.update(cores_in_use=snapshot['own']['cores_in_use'],
                   jobs=len(snapshot['own']['jobs']), warnings=snapshot['warnings'])
    history = root / 'history.jsonl'
    with history.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + '\n')
    if history.stat().st_size > HISTORY_BYTES:
        os.replace(history, root / 'history.1.jsonl')
        history.touch(exist_ok=False)


def sample(cfg, transport, interval=None, *, config_warning=None):
    root = cache_dir(cfg)
    previous_path = root / 'latest.json'
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    snapshot = dict(schema='ag-monitor/1', sampled_at=now, interval_seconds=interval,
                    ok=False, error=None, last_ok_at=None,
                    own=dict(cores_in_use=0, core_cap=cfg['resources']['max_cores'],
                             committed_cap=committed_cap(cfg), jobs=[], **shared_fields(cfg)),
                    cluster=dict(nodes=[], queues=[], cores_total=0, cores_used=0), warnings=[])
    operation = 'Read previous monitor snapshot'
    storage_state = {}
    try:
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding='utf-8'))
            # A damaged cache must not escape the sampling error handler or
            # leave invalid containers for publish() to crash on afterwards.
            retained = {key: previous[key] for key in ('last_ok_at', 'own', 'cluster', 'warnings')}
            for section, counters, lists in (
                ('own', ('cores_in_use', 'core_cap'), ('jobs',)),
                ('cluster', ('cores_total', 'cores_used'), ('nodes', 'queues')),
            ):
                value = retained[section]
                if (not isinstance(value, dict)
                        or any(type(value[key]) is not int for key in counters)
                        or any(not isinstance(value[key], list) for key in lists)):
                    raise ValueError('Invalid cached monitor data')
            if not isinstance(retained['warnings'], list):
                raise ValueError('Invalid cached monitor warnings')
            if retained['last_ok_at'] is not None:
                stamp = datetime.fromisoformat(retained['last_ok_at'])
                if stamp.tzinfo is None:
                    raise ValueError('Cached last_ok_at lacks a timezone')
                retained['last_ok_at'] = stamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            snapshot.update(retained)
        storage_state = {key: snapshot['cluster'][key] for key in
                         ('storage_kib', 'storage_checked_at', 'storage_sampled_at', 'storage_error')
                         if key in snapshot['cluster']}
        operation = 'Collect monitor sample'
        snapshot.update(observation(cfg, transport, login_user(cfg), storage_state=storage_state))
    except (OSError, ValueError, KeyError, AttributeError, TypeError, subprocess.TimeoutExpired) as exc:
        snapshot['error'] = redact_stderr(f'{operation}: {exc}', cfg)
    else:
        snapshot.update(ok=True, last_ok_at=now)
    # Even a failed sample or old cache must use today's configured caps.
    # Historical usage stays historical; never invent a running/queued split.
    snapshot['own'].update(core_cap=cfg['resources']['max_cores'], committed_cap=committed_cap(cfg))
    for key in ('shared_with', 'max_queued_cores', 'scheduler_max_running_cores'):
        snapshot['own'].pop(key, None)
    snapshot['own'].update(shared_fields(cfg))
    snapshot['own'].update(max_cores=cfg['resources']['max_cores'],
                           tiers={name: {key: cfg['resources']['tiers'][name][key]
                                         for key in ('cores', 'mem_gb')}
                                  for name in ('mini', 'simple', 'general', 'complex')
                                  if name in cfg['resources'].get('tiers', {})})
    # Configuration labels stay current even when retained scheduler data is old.
    snapshot['cluster'].pop('display_name', None)
    if 'display_name' in cfg:
        snapshot['cluster']['display_name'] = cfg['display_name']
    snapshot['config_warning'] = config_warning
    snapshot['config_removed'] = False
    snapshot['warnings'] = [row for row in snapshot['warnings']
                            if not isinstance(row, dict) or row.get('kind') != 'config-reload-failed']
    if config_warning:
        snapshot['warnings'].append(dict(kind='config-reload-failed', job_id=None, study=None,
                                         attempt=None, detail=config_warning))
    if scheduler_kind(cfg) == 'slurm':
        # Missing fields in a first failure or a pre-T19 cache are unknown,
        # never zero. Preserve the last successful storage value on failure;
        # obsolete budget totals are removed even from retained old snapshots.
        snapshot['cluster']['budget'] = None
        snapshot['cluster'].setdefault('storage_kib', None)
        snapshot['cluster'].update(storage_state)
        snapshot['cluster']['expires'] = cfg.get('expires')
        snapshot['cluster']['expiry_warning'] = budget.expiry_warning(cfg)
    publish(root, snapshot)
    return snapshot


def run(cfg, interval=None):
    if 'clusters' in cfg:
        return run_clusters(cfg, interval)
    transport = None
    transport_cfg = None
    try:
        while True:
            started = time.monotonic()
            cfg, warning = reload_config(cfg)
            if 'clusters' in cfg:
                return run_clusters(cfg, interval)
            if transport_cfg != cfg:
                transport = MonitorTransport(cfg, read_only=True)
                transport_cfg = cfg
            snapshot = sample(cfg, transport, interval, config_warning=warning)
            print(json.dumps(snapshot, ensure_ascii=False), flush=True)
            if interval is None:
                return 0 if snapshot['ok'] else 2
            time.sleep(max(0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


def slurm_observation(cfg, transport, username, *, storage_state=None):
    ledgers = budget.shared_ledgers(cfg)
    budget_summary = budget.public_summary(cfg)
    storage_state = storage_state if storage_state is not None else {}
    expiry = budget.expiry_warning(cfg)
    jobs = slurm.parse_queue(require_ok(transport.run(remote.slurm_jobs(user=username)), 'squeue monitor'))
    running, queued = slurm.core_breakdown(jobs, username)
    held = budget.shared_unobserved_cores(cfg, jobs, ledgers)
    records = local_attempts(Path(cfg['local']['studies_root']), cfg['_cluster'], 'slurm')
    by_job = {}
    for record in records:
        if record['job_id'] in by_job:
            raise ValueError(f'Multiple local Attempts record the same exact job ID: {by_job[record["job_id"]]["attempt"]}, {record["attempt"]}')
        by_job[record['job_id']] = record
    own = []
    for job in jobs:
        link = by_job.get(job['job_id'], {})
        own.append(dict(job_id=cfg['_cluster'] + ':' + job['job_id'], name=job['name'],
                        state=job['state'], cores=job['cores'], queue=job['partition'],
                        walltime_used=job['elapsed'], study=link.get('study'), attempt=link.get('attempt')))
    warnings = []
    active = {j['job_id'] for j in jobs}
    for record in records:
        kind = None
        if record['state'] in ('submitted', 'running', 'unknown') and record['job_id'] not in active:
            kind = 'absent-from-scheduler'
        elif record['state'] in ('finished', 'fetched', 'cancelled') and record['job_id'] in active:
            kind = 'scheduler-residue'
        if kind:
            warnings.append(dict(kind=kind, job_id=cfg['_cluster'] + ':' + record['job_id'],
                                 study=record['study'], attempt=record['attempt'], detail='运行 ag status 核对；不会自动重提或取消'))
    cap = cfg['resources']['max_cores']
    total_cap = committed_cap(cfg)
    if running + queued + held > total_cap:
        warnings.append(dict(kind='over-cap', job_id=None, study=None, attempt=None,
                             detail=f'本人运行加排队 {running + queued} 核、同组本地未观测预留 {held} 核，超过上限 {total_cap} 核'))
    storage_sample(cfg, transport, storage_state)
    return dict(own=dict(cores_in_use=running + queued, cores_running=running, cores_queued=queued,
                         core_cap=cap, committed_cap=total_cap, jobs=own, **shared_fields(cfg)),
                cluster=dict(nodes=[], queues=[], cores_total=0, cores_used=0,
                             hardware_capacity_known=False, name=cfg['_cluster'], scheduler='slurm',
                             **storage_state, expiry_warning=expiry,
                             budget=budget_summary, expires=cfg.get('expires')), warnings=warnings)


def shared_fields(cfg):
    peers = [name for name in shared_clusters(cfg) if name != cfg.get('_cluster', 'default')]
    return dict(optional_resource_caps(cfg), **(dict(shared_with=peers) if peers else {}))


def run_clusters(cfg, interval=None):
    selected, transports = {}, {}
    try:
        while True:
            started = time.monotonic()
            cfg, warning = reload_config(cfg)
            names = sorted(cfg['clusters']) if 'clusters' in cfg else ['default']
            current = {name: select_cluster(cfg, name) for name in names}
            for name in selected.keys() - current.keys():
                mark_removed(selected[name])
            for name, entry in current.items():
                if entry != selected.get(name):
                    transports[name] = MonitorTransport(entry, read_only=True)
            selected = current
            transports = {name: transports[name] for name in selected}
            snapshots = {name: sample(c, transports[name], interval, config_warning=warning)
                         for name, c in selected.items()}
            print(json.dumps(dict(clusters=snapshots), ensure_ascii=False), flush=True)
            if interval is None:
                return 0 if all(s['ok'] for s in snapshots.values()) else 2
            time.sleep(max(0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


def reload_config(cfg):
    # In-memory callers (including offline fixtures) have no file to reload.
    path = cfg.get('_config_path')
    if path is None:
        return cfg, None
    try:
        fresh = load_config(path)
        if '_cluster' in cfg:
            fresh = select_cluster(fresh, cfg['_cluster'])
        return fresh, None
    except (OSError, ValueError, KeyError, TypeError):
        return cfg, '配置重读失败，沿用上一轮配置'


def mark_removed(cfg):
    root = cache_dir(cfg)
    path = root / 'latest.json'
    if path.exists():
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        snapshot.update(config_removed=True, config_note='配置已移除')
        publish(root, snapshot)


def storage_sample(cfg, transport, values):
    """Throttle slow du independently, including failed attempts, across restarts."""
    from ag.doctor import storage
    now = datetime.now(timezone.utc)
    values.setdefault('storage_kib', None)
    values.setdefault('storage_sampled_at', None)
    values.setdefault('storage_error', None)
    try:
        checked = datetime.fromisoformat(values['storage_checked_at'])
        due = not 0 <= (now - checked).total_seconds() < STORAGE_INTERVAL
    except (ValueError, KeyError, TypeError):
        due = True
    if not due:
        return
    values['storage_checked_at'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        value = storage(cfg, transport, timeout=STORAGE_TIMEOUT)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        values['storage_error'] = redact_stderr(f'Storage query failed: {exc}', cfg)
        raise
    values.update(storage_kib=value, storage_sampled_at=values['storage_checked_at'], storage_error=None)
