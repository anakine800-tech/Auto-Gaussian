"""Read-only scheduler sampling; all writes stay in the local monitor cache."""
import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
import time
import threading

from ag import remote, status, slurm, attempt, budget, pbs, approval
from ag.config import (load_config, select_cluster, scheduler_kind, committed_cap,
                       shared_clusters, optional_resource_caps, RESOURCE_TIERS, cluster_name,
                       ssh_identity)
from ag.pbs import parse_nodes
from ag.transport import SSHTransport, SSHConnectionError, TransportError, Result, redact_stderr, require_ok


HISTORY_BYTES = 5 * 1024 * 1024
STORAGE_INTERVAL = 3600
STORAGE_TIMEOUT = 30


class MonitorTransport(SSHTransport):
    """Keep the read-only allowlist, but report timeouts in this round immediately."""

    def _perform(self, operation):
        return operation()

    def _execute(self, argv, timeout):
        def classify(stderr):
            self.failure_category = failure_category(stderr)

        return super()._execute(argv, timeout, observe_stderr=classify)


def watch_seconds(value):
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('--watch must be an integer from 30 to 600') from exc
    if not 30 <= seconds <= 600:
        raise argparse.ArgumentTypeError('--watch must be from 30 to 600 seconds')
    return seconds


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
    return [dict(job_id=job, state=current['state'], study=m['study_id'], attempt=path.name,
                 mem_gb=m.get('mem_gb'))
            for path, m, current, job in attempt.local_records(root, cluster, scheduler)
            if job is not None]


def observation(cfg, transport, username, *, storage_state=None, sampled_at=None):
    sampled_at = sampled_at or datetime.now(timezone.utc)
    if scheduler_kind(cfg) == 'slurm':
        return slurm_observation(cfg, transport, username, storage_state=storage_state)
    jobs = status.parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat jobs'))
    # Use submit's exact all-user validation and non-C reservation accounting.
    used = status.occupied(jobs, username)
    queues = parse_queues(require_ok(transport.run(remote.queues()), 'qstat queues'))
    nodes, hardware = pbs_hardware(cfg, transport, jobs)
    attempts = local_attempts(Path(cfg['local']['studies_root']), cfg.get('_cluster', 'default'), 'pbs')
    by_job = {}
    for item in attempts:
        # Do not silently attach a scheduler job to the wrong copied Attempt.
        if item['job_id'] in by_job:
            raise ValueError(f'Multiple local Attempts record the same exact job ID: {by_job[item["job_id"]]["attempt"]}, {item["attempt"]}')
        by_job[item['job_id']] = item
    all_jobs = []
    scheduler_timezone = cfg.get('scheduler_timezone')
    timezone_mismatch = False
    time_observations = []
    for job in jobs:
        if job['job_state'] == 'C':
            continue
        user = job['Job_Owner'].split('@')[0]
        mine = user == username
        link = by_job.get(job['job_id'], {}) if mine else {}
        time_sources = {}
        fields = pbs.job_fields(job, sampled_at, scheduler_timezone, time_sources=time_sources)
        walltime = pbs.duration_seconds(job.get('resources_used.walltime'))
        start_mismatch = False
        if scheduler_timezone is not None and fields['start_time'] is not None:
            # A wrong timezone can put a start in the future or add hours to
            # elapsed time. The strict thresholds are unchanged from T124.
            seconds = (sampled_at - datetime.fromisoformat(fields['start_time'])).total_seconds()
            if seconds < -120 or (walltime is not None
                                  and (seconds < walltime - 120 or seconds > walltime + 3600)):
                start_mismatch = timezone_mismatch = True
        row = dict(job_id=job['job_id'], user=user, mine=mine,
                   name=job.get('Job_Name'), state=job['job_state'], queue=job.get('queue'),
                   mem=job.get('Resource_List.mem'), mem_source='scheduler',
                   walltime_used=job.get('resources_used.walltime'),
                   walltime_limit=job.get('Resource_List.walltime'),
                   study=link.get('study'), attempt=link.get('attempt'),
                   **fields)
        all_jobs.append(row)
        time_observations.append((row, time_sources, walltime, start_mismatch))
    if timezone_mismatch:
        # Invalidate this entry's timezone-dependent values before sorting or
        # truncation. Absolute times survive unless that start itself failed.
        for row, sources, walltime, start_mismatch in time_observations:
            if start_mismatch or sources['start_time'] == 'configured_timezone':
                row.update(start_time=None, elapsed_seconds=walltime,
                           elapsed_source='walltime_used' if walltime is not None else None)
            if sources['qtime'] == 'configured_timezone':
                row['qtime'] = None
    all_jobs.sort(key=job_sort_key)
    own = [row for row in all_jobs if row['mine']]
    scheduler = {job['job_id']: job for job in jobs}
    warnings = []
    if timezone_mismatch:
        warnings.append(dict(kind='timezone-mismatch', job_id=None, study=None, attempt=None,
                             detail='开始时间与采样时间或已用 walltime 不一致，可能配置了错误的调度器时区；本轮依赖该时区的开始/提交时间及直接异常的开始时间已置为未知，清空开始时间的耗时退回 walltime，缺失时为未知'))
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
        for row in all_jobs + warnings:
            if row.get('job_id'):
                row['job_id'] = cfg['_cluster'] + ':' + row['job_id']
    return dict(own=dict(cores_in_use=used, core_cap=cap, jobs=own,
                         cores_running=running, cores_queued=queued, committed_cap=total_cap,
                         **memory_totals(own), **shared_fields(cfg)),
                cluster=dict(nodes=nodes, queues=queues, hardware=hardware, scheduler='pbs',
                             cores_total=hardware['cores_total'], cores_used=hardware['cores_allocated'],
                             jobs=all_jobs[:500], jobs_omitted=max(0, len(all_jobs) - 500),
                             job_summary=job_summary(all_jobs), job_summary_error=None, display_order=cfg.get('display_order'),
                             scheduler_timezone=scheduler_timezone),
                warnings=warnings)


def cache_dir(cfg, *, create=True):
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    if cfg.get('_cluster'):
        root = root / cfg['_cluster']
    # A redirected cache/history could otherwise overwrite study files.
    for path in (root.parent, root, *(root / name for name in
                                    ('latest.json', 'previous.json', 'history.jsonl', 'history.1.jsonl'))):
        if path.is_symlink():
            raise ValueError('Monitor cache must not contain symbolic links')
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _replace_snapshot(root, name, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=root,
                                         prefix='.' + name + '-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / name)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _snapshot_bytes(fd, name):
    try:
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    with os.fdopen(handle, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Invalid monitor snapshot file')
        return stream.read()


def publish(root, snapshot, *, record_history=True):
    # Once and watch may finish together. Serialize only local publication so
    # their previous/latest generations cannot interleave; never hold over sampling.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        for name in ('latest.json', 'previous.json', 'history.jsonl', 'history.1.jsonl'):
            if (root / name).is_symlink():
                raise ValueError('Monitor cache must not contain symbolic links')
        latest = _snapshot_bytes(fd, 'latest.json')
        previous = _snapshot_bytes(fd, 'previous.json')
        continuous = True
        if latest is not None and previous is not None:
            try:
                continuous = (datetime.fromisoformat(json.loads(previous)['sampled_at'])
                              < datetime.fromisoformat(json.loads(latest)['sampled_at']))
            except (ValueError, KeyError, TypeError):
                continuous = False
        if latest is None:
            # An orphaned previous cannot be paired with a new cache.
            (root / 'previous.json').unlink(missing_ok=True)
        elif not continuous:
            # Keep a durable break even if this recovery itself is interrupted.
            # Deleting previous here would make the old latest look like a
            # normal first sample after a crash. This is not a new observation.
            try:
                interrupted = json.loads(latest)
                if not isinstance(interrupted, dict):
                    raise ValueError('Invalid cached snapshot')
            except (ValueError, TypeError):
                interrupted = dict(snapshot, sampled_at=None)
            interrupted.update(ok=False, error='Monitor snapshot continuity interrupted')
            _replace_snapshot(root, 'previous.json',
                              (json.dumps(interrupted, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        else:
            _replace_snapshot(root, 'previous.json', latest)
        # Persist the predecessor before publishing a newer latest. A crash
        # between these replaces leaves equal generations, which readers reject.
        # Failed samples and control tombstones also rotate; never skip them.
        os.fsync(fd)
        data = (json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        _replace_snapshot(root, 'latest.json', data)
        os.fsync(fd)
        if not record_history:
            return
        summary = {key: snapshot[key] for key in ('sampled_at', 'interval_seconds', 'ok', 'error', 'last_ok_at')}
        summary.update(sampling_state=snapshot.get('sampling', once_sampling())['state'],
                       consecutive_failures=snapshot.get('sampling', once_sampling())['consecutive_failures'],
                       trigger=snapshot.get('sampling', once_sampling())['trigger'],
                       cores_in_use=snapshot['own']['cores_in_use'],
                       jobs=len(snapshot['own']['jobs']), warnings=len(snapshot['warnings']),
                       job_summary=snapshot['cluster'].get('job_summary'),
                       sample_duration_ms=snapshot.get('sample_duration_ms'))
        history = root / 'history.jsonl'
        with history.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + '\n')
        if history.stat().st_size > HISTORY_BYTES:
            os.replace(history, root / 'history.1.jsonl')
            history.touch(exist_ok=False)
    finally:
        os.close(fd)


def empty_snapshot(cfg, interval=None):
    return dict(schema='ag-monitor/1', sampled_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                interval_seconds=interval, sampling=once_sampling(), sample_duration_ms=0, ok=False, error=None, last_ok_at=None,
                own=dict(cores_in_use=0, core_cap=cfg['resources']['max_cores'],
                         committed_cap=committed_cap(cfg), jobs=[], mem_running_gb=None, mem_queued_gb=None,
                         **shared_fields(cfg)),
                cluster=dict(nodes=[], queues=[], cores_total=0, cores_used=0, scheduler=scheduler_kind(cfg),
                             jobs=[], jobs_omitted=0, job_summary=empty_summary(), job_summary_error=None,
                             hardware=empty_hardware('sinfo' if scheduler_kind(cfg) == 'slurm' else 'pbsnodes'),
                             display_order=cfg.get('display_order'),
                             scheduler_timezone=cfg.get('scheduler_timezone')), warnings=[])


def retained_snapshot(previous):
    retained = {key: previous[key] for key in ('last_ok_at', 'own', 'cluster', 'warnings')}
    for section, counters, lists in (
        ('own', ('cores_in_use', 'core_cap'), ('jobs',)),
        ('cluster', ('cores_total', 'cores_used'), ('nodes', 'queues')),
    ):
        value = retained[section]
        if (not isinstance(value, dict)
                or any(value[key] is not None and type(value[key]) is not int for key in counters)
                or any(not isinstance(value[key], list) for key in lists)):
            raise ValueError('Invalid cached monitor data')
    if not isinstance(retained['warnings'], list):
        raise ValueError('Invalid cached monitor warnings')
    if retained['last_ok_at'] is not None:
        stamp = datetime.fromisoformat(retained['last_ok_at'])
        if stamp.tzinfo is None:
            raise ValueError('Cached last_ok_at lacks a timezone')
        retained['last_ok_at'] = stamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return retained


def sample(cfg, transport, interval=None, *, config_warning=None, schedule=None, trigger='scheduled'):
    started = time.monotonic()
    at = utc_now()
    category = None
    if hasattr(transport, 'failure_category'):
        transport.failure_category = None
    root = cache_dir(cfg)
    previous_path = root / 'latest.json'
    snapshot = empty_snapshot(cfg, interval)
    now = snapshot['sampled_at']
    operation = 'Read previous monitor snapshot'
    storage_state = {}
    try:
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding='utf-8'))
            retained = retained_snapshot(previous)
            snapshot.update(retained)
        storage_state = {key: snapshot['cluster'][key] for key in
                         ('storage_kib', 'storage_checked_at', 'storage_sampled_at', 'storage_error')
                         if key in snapshot['cluster']}
        operation = 'Collect monitor sample'
        # One local ssh -G supplies both job ownership and the account binding;
        # an alias name alone cannot bind an empty queue after its target changes.
        identity = ssh_identity(cfg)
        if identity is None or not re.fullmatch(r'[A-Za-z0-9_.-]+', identity[2]):
            raise ValueError('Cannot identify local SSH scheduler account')
        snapshot.update(observation(cfg, transport, identity[2], storage_state=storage_state,
                                    sampled_at=datetime.fromisoformat(now)))
    except (OSError, ValueError, KeyError, AttributeError, TypeError, subprocess.TimeoutExpired) as exc:
        category = getattr(transport, 'failure_category', None) or failure_category(exc)
        snapshot['error'] = redact_stderr(f'{operation}: {exc}', cfg)
    else:
        snapshot.update(ok=True, last_ok_at=now,
                        account_sha256=approval.digest({'scheduler': scheduler_kind(cfg), 'ssh': list(identity)}))
    # Even a failed sample or old cache must use today's configured caps.
    # Historical usage stays historical; never invent a running/queued split.
    snapshot['own'].update(core_cap=cfg['resources']['max_cores'], committed_cap=committed_cap(cfg))
    for key in ('shared_with', 'max_queued_cores', 'scheduler_max_running_cores'):
        snapshot['own'].pop(key, None)
    snapshot['own'].update(shared_fields(cfg))
    snapshot['own'].update(max_cores=cfg['resources']['max_cores'],
                           tiers={name: {key: cfg['resources']['tiers'][name][key]
                                         for key in ('cores', 'mem_gb')}
                                  for name in RESOURCE_TIERS
                                  if name in cfg['resources'].get('tiers', {})})
    snapshot['own'].pop('max_walltime', None)
    if 'max_walltime' in cfg['resources']:
        snapshot['own']['max_walltime'] = cfg['resources']['max_walltime']
    # Configuration labels stay current even when retained scheduler data is old.
    snapshot['cluster'].pop('display_name', None)
    if 'display_name' in cfg:
        snapshot['cluster']['display_name'] = cfg['display_name']
    snapshot['cluster']['display_order'] = cfg.get('display_order')
    snapshot['cluster']['scheduler_timezone'] = cfg.get('scheduler_timezone')
    snapshot['cluster']['scheduler'] = scheduler_kind(cfg)
    # Older caches gain the additive fields without fabricating observations.
    defaults = empty_snapshot(cfg, interval)
    for section in ('own', 'cluster'):
        for key, value in defaults[section].items():
            snapshot[section].setdefault(key, value)
    snapshot['cluster']['hardware'].setdefault('notes', [])
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
    snapshot['sample_duration_ms'] = max(0, round((time.monotonic() - started) * 1000))
    if schedule is not None:
        schedule.record(snapshot['ok'], category, trigger, started, at)
        pending = read_control(root / REQUEST_FILE) is not None
        snapshot['sampling'] = schedule.snapshot(trigger, pending)
    publish(root, snapshot)
    return snapshot


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
        if job['state'] not in slurm.ACTIVE:
            continue
        link = by_job.get(job['job_id'], {})
        own.append(dict(user=username, mine=True, cores_kind='allocated' if job['state'] in slurm.RUNNING else 'requested',
                        mem_gb=link.get('mem_gb'),
                        mem_source='manifest' if link.get('mem_gb') is not None else None,
                        start_time=None, qtime=None, walltime_limit_seconds=None,
                        elapsed_seconds=slurm_elapsed(job['elapsed']),
                        elapsed_source='walltime_used' if slurm_elapsed(job['elapsed']) is not None else None,
                        job_id=cfg['_cluster'] + ':' + job['job_id'], name=job['name'],
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
    summary, hardware, summary_error = slurm_partition(cfg, transport, own)
    nodes, nodes_error = slurm_nodes(cfg, transport)
    storage_sample(cfg, transport, storage_state)
    return dict(own=dict(cores_in_use=running + queued, cores_running=running, cores_queued=queued,
                         core_cap=cap, committed_cap=total_cap, jobs=own, **memory_totals(own), **shared_fields(cfg)),
                cluster=dict(nodes=nodes, nodes_error=nodes_error, queues=[], cores_total=0, cores_used=0,
                             hardware_capacity_known=hardware['cores_total'] is not None,
                             hardware=hardware, jobs=own, jobs_omitted=0, job_summary=summary,
                             job_summary_error=summary_error, scheduler_timezone=None,
                             display_order=cfg.get('display_order'), name=cfg['_cluster'], scheduler='slurm',
                             **storage_state, expiry_warning=expiry,
                             budget=budget_summary, expires=cfg.get('expires')), warnings=warnings)


def shared_fields(cfg):
    peers = [name for name in shared_clusters(cfg) if name != cfg.get('_cluster', 'default')]
    return dict(optional_resource_caps(cfg), **(dict(shared_with=peers) if peers else {}))



def utc_now():
    return datetime.now(timezone.utc)


def iso_at(value):
    return value.isoformat(timespec='seconds').replace('+00:00', 'Z')


def failure_category(value):
    """Classify in memory, before redaction can remove authentication tokens."""
    value = str(value)
    if re.search(r'Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED', value, re.I):
        return 'host_key'
    methods = r'(?:publickey|password|keyboard-interactive|hostbased|gssapi(?:-with-mic|-keyex)?)'
    if re.search(r'Permission denied \(' + methods + r'(?:,\s*' + methods + r')*\)', value, re.I):
        return 'auth'
    return None


@dataclass
class Sampling:
    base: int
    failures: int = 0
    state: str = 'normal'
    pause_reason: str | None = None
    due: float = float('-inf')
    next_at: str | None = None
    current: int = field(init=False)

    def __post_init__(self):
        self.current = self.base

    def record(self, ok, category, trigger, started, at):
        if ok:
            self.failures, self.state, self.pause_reason = 0, 'normal', None
            self.current = self.base
        elif trigger == 'scheduled':
            self.failures += 1
            self.current = min(600, self.base * 2 ** min(5, max(0, self.failures - 2)))
            self.state = 'backoff' if self.failures >= 3 else 'normal'
        if not ok and category:
            self.state, self.pause_reason, self.due, self.next_at = 'paused', category, float('inf'), None
        elif ok or trigger == 'scheduled':
            self.due = started + self.current
            self.next_at = iso_at(at + timedelta(seconds=self.current))
        # An ordinary failed manual attempt preserves every scheduling value,
        # including an authentication pause being retried with confirmation.

    def snapshot(self, trigger, pending=False):
        return dict(state=self.state, consecutive_failures=self.failures,
                    current_interval_seconds=self.current, next_sample_at=self.next_at,
                    pause_reason=self.pause_reason, trigger=trigger, retry_pending=pending)


def once_sampling():
    return dict(state='normal', consecutive_failures=0, current_interval_seconds=None,
                next_sample_at=None, pause_reason=None, trigger='scheduled', retry_pending=False)


REQUEST_FILE = 'retry-request.json'
STATUS_FILE = 'retry-status.json'
CONTROL_BYTES = 2 * 1024 * 1024
DISCARD_REASONS = ('auth_confirmation_required', 'entry_removed', 'config_changed', 'monitor_restarted')
WATCH_FILE = 'watch.json'


def control_root(cfg, *, create=True):
    return cache_dir(dict(cfg, _cluster=None), create=create)


@contextmanager
def control_lock(cfg, *, create=True):
    # Serialize request creation with claiming it / marking an entry in progress.
    # This prevents a click at the claim boundary from causing a second sample.
    root = control_root(cfg, create=create)
    path = root / 'watch.lock'
    if path.is_symlink():
        raise ValueError('Monitor cache must not contain symbolic links')
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    except FileNotFoundError:
        if create:
            raise
        yield None
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield root
    finally:
        os.close(fd)


def read_control(path):
    if path.is_symlink():
        raise ValueError('Monitor cache must not contain symbolic links')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('Invalid monitor control file')
        raw = handle.read(CONTROL_BYTES + 1)
        if len(raw) > CONTROL_BYTES:
            raise ValueError('Monitor control file exceeds size limit')
        return json.loads(raw)


def write_control(root, value, filename=WATCH_FILE):
    target = root / filename
    if target.is_symlink():
        raise ValueError('Monitor cache must not contain symbolic links')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root,
                                         prefix='.watch-', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def watch_alive(value):
    try:
        if not isinstance(value, dict) or type(value['pid']) is not int or value['pid'] <= 0:
            return False
        age = (utc_now() - datetime.fromisoformat(value['heartbeat_at'])).total_seconds()
        if not 0 <= age <= 90:
            return False
        os.kill(value['pid'], 0)
        return True
    except (OSError, KeyError, TypeError, ValueError):
        return False


def entries(cfg):
    if 'clusters' in cfg:
        return {name: select_cluster(cfg, name) for name in sorted(cfg['clusters'])}
    return {cfg.get('_cluster', 'default'): cfg}


def control_source(entry):
    return 'named' if entry.get('_cluster') else 'legacy'


def utc_stamp(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() == timedelta(0)
    except ValueError:
        return False


def request_identity(value):
    return (isinstance(value, dict) and isinstance(value.get('request_id'), str)
            and re.fullmatch(r'[0-9a-f]{32}', value['request_id']) is not None
            and utc_stamp(value.get('requested_at')))


def retry_status(root, name):
    value = read_control(root / STATUS_FILE)
    if value is None and not (root / STATUS_FILE).exists():
        return None
    valid = (request_identity(value) and type(value.get('version')) is int and value['version'] == 1
             and value.get('entry') == name
             and all(key in value for key in ('state', 'reason', 'finished_at', 'sampled_at', 'ok')))
    if valid:
        state = value['state']
        if state in ('queued', 'running'):
            valid = all(value[key] is None for key in ('reason', 'finished_at', 'sampled_at', 'ok'))
        elif state == 'finished':
            valid = (value['reason'] is None and utc_stamp(value['finished_at'])
                     and utc_stamp(value['sampled_at']) and type(value['ok']) is bool)
        elif state == 'discarded':
            valid = (value['reason'] in DISCARD_REASONS and utc_stamp(value['finished_at'])
                     and value['sampled_at'] is None and value['ok'] is None)
        else:
            valid = False
    if not valid:
        raise ValueError('Invalid monitor retry status; inspect local control files')
    return {key: value[key] for key in ('version', 'entry', 'request_id', 'requested_at',
            'state', 'reason', 'finished_at', 'sampled_at', 'ok')}


def new_retry_status(name, request, state):
    return dict(version=1, entry=name, request_id=request['request_id'],
                requested_at=request['requested_at'], state=state, reason=None,
                finished_at=None, sampled_at=None, ok=None)


def queued_status(root, name, request):
    value = retry_status(root, name)
    if (not request_identity(request) or type(request.get('auth_fixed')) is not bool
            or value is None or value['state'] != 'queued'
            or any(value[key] != request[key] for key in ('request_id', 'requested_at'))):
        raise ValueError('Inconsistent monitor retry request; inspect local control files')
    return value


def retry(cfg, name, *, auth_fixed=False, json_output=False, track=False):
    if track and not json_output:
        raise ValueError('--track requires --retry and --json')
    result = dict(entry=name, result='refused', reason=None, requested_at=None)
    if track:
        result['request_id'] = None
    selected = entries(cfg)
    if name not in selected:
        result['reason'] = 'unknown_entry'
    else:
        # Only the daemon creates its cache/lock; a refused click leaves no files.
        with control_lock(cfg, create=False) as root:
            watching = read_control(root / WATCH_FILE) if root is not None else None
            rows = watching.get('entries') if isinstance(watching, dict) else None
            row = rows.get(name) if isinstance(rows, dict) else None
            if not watch_alive(watching) or not isinstance(row, dict):
                result['reason'] = 'monitor_not_running'
            elif row.get('pause_reason') in ('auth', 'host_key') and not auth_fixed:
                result['reason'] = 'auth_confirmation_required'
            else:
                version = watching.get('retry_tracking_version')
                supported = type(version) is int and version == 1
                if (version is not None or track) and not supported:
                    raise ValueError('Monitor retry tracking is unavailable')
                if supported and row.get('source') != control_source(selected[name]):
                    result['reason'] = 'monitor_not_running'
                else:
                    entry_root = cache_dir(selected[name], create=False)
                    path = entry_root / REQUEST_FILE
                    if watching.get('sampling') == name:
                        request = dict(requested_at=watching['sample_started_at'],
                                       request_id=watching.get('sample_request_id'))
                        if supported:
                            if not request_identity(request):
                                raise ValueError('Invalid monitor sampling identity')
                            value = retry_status(entry_root, name)
                            if value is None or value['request_id'] != request['request_id']:
                                value = new_retry_status(name, request, 'running')
                                write_control(entry_root, value, STATUS_FILE)
                            elif value['state'] != 'running':
                                raise ValueError('Inconsistent monitor sampling status')
                        outcome = 'in_progress'
                    else:
                        request = read_control(path)
                        if request is not None:
                            if supported:
                                queued_status(entry_root, name, request)
                            outcome = 'already_queued'
                        else:
                            request = dict(requested_at=iso_at(utc_now()), auth_fixed=auth_fixed)
                            if supported:
                                # Validate the previous record before replacing it; never hide corruption.
                                previous = retry_status(entry_root, name)
                                if previous is not None and previous['state'] in ('queued', 'running'):
                                    raise ValueError('Inconsistent monitor retry request; inspect local control files')
                                request['request_id'] = secrets.token_hex(16)
                            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                                json.dump(request, handle)
                                handle.flush()
                                os.fsync(handle.fileno())
                            if supported:
                                write_control(entry_root, new_retry_status(name, request, 'queued'), STATUS_FILE)
                            outcome = 'queued'
                    result.update(result=outcome, requested_at=request['requested_at'])
                    if track:
                        result['request_id'] = request['request_id']
    if json_output:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        messages = dict(queued='重试请求已登记', already_queued='已有待处理请求，已合并',
                        in_progress='入口正在采样，已合并；结果见下一份快照',
                        monitor_not_running='监控未运行，未登记请求',
                        auth_confirmation_required='入口因认证或主机指纹失败暂停；修复后请带 --auth-fixed',
                        unknown_entry='入口名不在当前配置中')
        print(f"{name}：{messages[result['reason'] or result['result']]}", flush=True)
    return int(result['result'] == 'refused')


class WatchControl:
    """Local-only heartbeat; the foreground thread alone performs SSH samples."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.stopped = threading.Event()
        self.failure = None
        self.discarded = []

    def __enter__(self):
        with control_lock(self.cfg) as root:
            previous = read_control(root / WATCH_FILE)
            if watch_alive(previous):
                raise ValueError('A monitor is already running for this cache')
            selected = entries(self.cfg)
            # A removed entry can still have an acknowledged request after a crash.
            # Use only validated names/layouts under the same configured root.
            leftovers = {(name, control_source(entry)): entry for name, entry in selected.items()}
            if (isinstance(previous, dict) and type(previous.get('retry_tracking_version')) is int
                    and previous['retry_tracking_version'] == 1):
                if not isinstance(previous.get('entries'), dict):
                    raise ValueError('Invalid monitor control entries')
                for name, row in previous['entries'].items():
                    cluster_name(name)
                    if not isinstance(row, dict) or row.get('source') not in ('legacy', 'named'):
                        raise ValueError('Invalid monitor control source')
                    if row['source'] == 'legacy' and name != 'default':
                        raise ValueError('Invalid legacy monitor entry')
                    leftovers[(name, row['source'])] = dict(self.cfg, _cluster=name if row['source'] == 'named' else None)
            for (name, _), entry in leftovers.items():
                self.discard(name, entry, 'monitor_restarted', startup=True)
            for entry in selected.values():
                cache_dir(entry)
            self.selected = selected
            self.value = dict(pid=os.getpid(), heartbeat_at=iso_at(utc_now()), sampling=None,
                              sample_started_at=None, sample_request_id=None, retry_tracking_version=1,
                              entries={name: dict(source=control_source(entry), pause_reason=None)
                                       for name, entry in selected.items()})
            write_control(root, self.value)
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.thread.start()
        return self

    def discard(self, name, entry, reason, *, startup=False):
        # Caller holds watch.lock. Publish a reason before unlinking any request.
        root = cache_dir(entry, create=False)
        path = root / REQUEST_FILE
        value = retry_status(root, name)
        try:
            request = read_control(path)
        except (ValueError, UnicodeError):
            if not startup or path.is_symlink():
                raise
            request = {}  # T127's pre-tracking startup cleanup, with no invented ID.
        present = path.exists()
        if isinstance(request, dict) and 'request_id' in request:
            if (not request_identity(request) or value is None
                    or any(request[key] != value[key] for key in ('request_id', 'requested_at'))):
                raise ValueError('Inconsistent monitor retry request; inspect local control files')
        elif present and not startup:
            raise ValueError('Untracked monitor retry request; restart required')
        if value is not None and value['state'] in ('queued', 'running'):
            write_control(root, dict(value, state='discarded', reason=reason,
                                     finished_at=iso_at(utc_now()), sampled_at=None, ok=None), STATUS_FILE)
            self.discarded.append(name)
        if present:
            path.unlink()
            if name not in self.discarded:
                self.discarded.append(name)

    def reconfigure(self, selected, changed):
        with control_lock(self.cfg) as root:
            if self.failure is not None:
                raise self.failure
            for name, entry in self.selected.items():
                if name not in selected or name in changed:
                    self.discard(name, entry, 'entry_removed' if name not in selected else 'config_changed')
            for entry in selected.values():
                cache_dir(entry)
            self.value['entries'] = {
                name: dict(source=control_source(entry), pause_reason=(
                    None if name in changed else self.value['entries'].get(name, {}).get('pause_reason')))
                for name, entry in selected.items()}
            self.selected = selected
            self.value['heartbeat_at'] = iso_at(utc_now())
            write_control(root, self.value)

    def heartbeat(self):
        while not self.stopped.wait(30):
            try:
                with control_lock(self.cfg) as root:
                    self.value['heartbeat_at'] = iso_at(utc_now())
                    write_control(root, self.value)
            except (OSError, ValueError) as exc:
                self.failure = exc
                return

    def begin(self, name, entry, schedule):
        with control_lock(self.cfg) as root:
            if self.failure is not None:
                raise self.failure
            entry_root = cache_dir(entry)
            request_path = entry_root / REQUEST_FILE
            request = read_control(request_path)
            if request is not None:
                value = queued_status(entry_root, name, request)
                if schedule.state == 'paused' and not request['auth_fixed']:
                    self.discard(name, entry, 'auth_confirmation_required')
                    return None
                trigger = 'manual_auth_fixed' if request['auth_fixed'] else 'manual'
                # Claim first. If either write/unlink fails, stop without sampling;
                # another claim cannot execute a running request a second time.
                write_control(entry_root, dict(value, state='running'), STATUS_FILE)
                request_path.unlink()
            elif request_path.exists():
                raise ValueError('Invalid monitor retry request')
            elif time.monotonic() >= schedule.due:
                trigger = 'scheduled'
                request = dict(request_id=secrets.token_hex(16), requested_at=iso_at(utc_now()))
            else:
                return None
            self.value.update(sampling=name, sample_started_at=request['requested_at'],
                              sample_request_id=request['request_id'], heartbeat_at=iso_at(utc_now()))
            write_control(root, self.value)
            return trigger

    def finish(self, name, schedule, snapshot):
        # sample() has returned only after both snapshot and history publication.
        with control_lock(self.cfg) as root:
            if self.failure is not None:
                raise self.failure
            entry_root = cache_dir(self.selected[name])
            value = retry_status(entry_root, name)
            if value is not None and value['request_id'] == self.value['sample_request_id']:
                if value['state'] != 'running':
                    raise ValueError('Inconsistent monitor sampling status')
                write_control(entry_root, dict(value, state='finished', finished_at=iso_at(utc_now()),
                                                sampled_at=snapshot['sampled_at'], ok=snapshot['ok']), STATUS_FILE)
            self.value['entries'][name]['pause_reason'] = schedule.pause_reason
            self.value.update(sampling=None, sample_started_at=None, sample_request_id=None,
                              heartbeat_at=iso_at(utc_now()))
            write_control(root, self.value)

    def configure(self, selected, schedules):
        values = {name: dict(pause_reason=schedules[name].pause_reason, source=control_source(entry))
                  for name, entry in selected.items()}
        if values != self.value['entries']:
            with control_lock(self.cfg) as root:
                self.value['entries'] = values
                self.value['heartbeat_at'] = iso_at(utc_now())
                write_control(root, self.value)

    def pending(self, selected):
        with control_lock(self.cfg):
            return {name for name, entry in selected.items()
                    if read_control(cache_dir(entry) / REQUEST_FILE) is not None}

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join()
        with control_lock(self.cfg) as root:
            self.value.update(pid=None, sampling=None, heartbeat_at=iso_at(utc_now()))
            write_control(root, self.value)


def print_round(snapshots, sampled, *, json_output, multi, discarded=()):
    if json_output:
        value = dict(clusters=snapshots) if multi else next(iter(snapshots.values()), {})
    else:
        rows = {}
        for name, snapshot in snapshots.items():
            sampling = snapshot['sampling']
            rows[name] = dict(sampled=name in sampled,
                              trigger=sampling['trigger'] if name in sampled else None,
                              ok=snapshot['ok'], state=sampling['state'],
                              consecutive_failures=sampling['consecutive_failures'],
                              jobs=len(snapshot['own']['jobs']), warnings=len(snapshot['warnings']),
                              next_sample_at=sampling['next_sample_at'],
                              error=snapshot['error'][:200] if snapshot['error'] else None)
        value = dict(schema='ag-monitor-line/1', at=iso_at(utc_now()), entries=rows)
    if discarded:
        value = dict(value, discarded_retry_requests=list(discarded))
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run(cfg, interval=None, *, json_output=False):
    return run_clusters(cfg, interval, json_output=json_output)


def run_clusters(cfg, interval=None, *, json_output=True):
    # Preserve the existing Python entry point's full-snapshot default. The
    # CLI goes through run(), which explicitly selects compact stdout by default.
    # WatchControl advertises these entries before the first reload. Requests
    # accepted in that window must be compared against this actual baseline.
    selected = entries(cfg)
    transports, schedules, snapshots = {}, {}, {}
    reload = ConfigReload()
    original_root = cfg['local']['studies_root']
    try:
        with WatchControl(cfg) if interval is not None else nullcontext() as control:
            while True:
                cfg, warning = reload.read(cfg)
                if cfg['local']['studies_root'] != original_root:
                    raise ValueError('Monitor control root changed; stop and review before restarting')
                current = entries(cfg)
                comparable = lambda value: {k: v for k, v in value.items() if k != '_cluster_entries'}
                changed = {name for name in current.keys() & selected.keys()
                           if comparable(current[name]) != comparable(selected[name])}
                if control is not None and (changed or selected.keys() != current.keys()):
                    control.reconfigure(current, changed)
                for name in selected.keys() - current.keys():
                    mark_removed(selected[name])
                for name, entry in current.items():
                    # Peer metadata changes are not changes to this entry's SSH
                    # configuration. Current peer caps still reach each sample.
                    if name not in transports or name in changed:
                        transports[name] = MonitorTransport(entry, read_only=True)
                        schedules[name] = Sampling(entry_interval(entry, interval)) if interval is not None else None
                selected = current
                transports = {name: transports[name] for name in selected}
                schedules = {name: schedules[name] for name in selected}
                snapshots = {name: value for name, value in snapshots.items() if name in selected}
                if control is not None:
                    control.configure(selected, schedules)
                sampled = set()
                # Automatic samples run once per round, in deadline order.
                # After every sample, retries from any entry take the next
                # free slot, including entries already sampled this round.
                remaining = dict(selected)
                while True:
                    pending = control.pending(selected) if control else set()
                    candidates = remaining.keys() | pending
                    if not candidates:
                        break
                    name = min(candidates, key=lambda n: (n not in pending,
                               schedules[n].due if schedules[n] else 0, n))
                    remaining.pop(name, None)
                    entry, schedule = selected[name], schedules[name]
                    trigger = control.begin(name, entry, schedule) if control else 'scheduled'
                    if trigger is None:
                        continue
                    snapshots[name] = sample(entry, transports[name], entry_interval(entry, interval),
                                             config_warning=warning, schedule=schedule, trigger=trigger)
                    sampled.add(name)
                    if control is not None:
                        control.finish(name, schedule, snapshots[name])
                if sampled or (control is not None and control.discarded):
                    print_round(snapshots, sampled, json_output=json_output,
                                multi='clusters' in cfg, discarded=control.discarded if control else ())
                    if control is not None:
                        control.discarded.clear()
                if interval is None:
                    return 0 if all(s['ok'] for s in snapshots.values()) else 2
                delay = min((schedule.due - time.monotonic() for schedule in schedules.values()), default=2)
                time.sleep(min(2, max(0, delay)))
    except KeyboardInterrupt:
        return 0


def config_signature(path):
    value = Path(path).stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


class ConfigReload:
    """A single run's successful stable read; errors are never cached."""

    def __init__(self):
        self.signature = None
        self.checked = float('-inf')

    def read(self, cfg):
        path = cfg.get('_config_path')
        if path is None:
            return reload_config(cfg)
        try:
            before = (path, config_signature(path))
            if before == self.signature and time.monotonic() - self.checked < 30:
                return cfg, None
            fresh, warning = reload_config(cfg)
            if warning or before != (path, config_signature(path)):
                raise ValueError('Unstable monitor configuration')
        except (OSError, ValueError, KeyError, TypeError):
            self.signature = None
            return cfg, '配置重读失败，沿用上一轮配置'
        self.signature, self.checked = before, time.monotonic()
        return fresh, None


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
    try:
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        retained_snapshot(snapshot)
        if (snapshot['schema'] != 'ag-monitor/1' or type(snapshot['ok']) is not bool
                or not isinstance(snapshot['sampled_at'], str)
                or snapshot['interval_seconds'] is not None and type(snapshot['interval_seconds']) is not int
                or snapshot['error'] is not None and not isinstance(snapshot['error'], str)):
            raise ValueError('Invalid cached monitor envelope')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        snapshot = empty_snapshot(cfg)
        snapshot['sampled_at'] = None  # no observation exists for this control-only tombstone
        snapshot['error'] = '缓存不可读，已按配置移除处理'
    snapshot.update(config_removed=True, config_note='配置已移除')
    publish(root, snapshot, record_history=False)


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
        return
    values.update(storage_kib=value, storage_sampled_at=values['storage_checked_at'], storage_error=None)


def entry_interval(cfg, interval):
    if interval is None:
        return None
    return cfg.get('monitor_interval_seconds', max(interval, 60) if scheduler_kind(cfg) == 'slurm' else interval)


def empty_hardware(source, error=None):
    return dict(cores_total=None, cores_allocated=None, cores_idle=None, cores_other=None,
                mem_total_gb=None, mem_allocated_gb=None, source=source, error=error, notes=[])


def known_sum(values):
    values = list(values)
    return None if any(value is None for value in values) else round(sum(values), 1)


def pbs_hardware(cfg, transport, jobs):
    try:
        hardware = empty_hardware('pbsnodes')
        raw = require_ok(transport.run(remote.nodes()), 'pbsnodes')
        nodes = parse_nodes(raw, jobs, notes=hardware['notes'])
        if 'node_targeting' in cfg:
            from ag.node_targeting import strict_nodes
            try:
                nodes = strict_nodes(raw, jobs)
            except ValueError:
                # Ambiguous targeting evidence must not erase the read-only view.
                for node in nodes:
                    node['targeting_consistent'] = False
                hardware['notes'].append('Node targeting evidence is inconsistent; read-only display retained, targeting unavailable')
        if nodes:
            hardware.update(cores_total=sum(n['cores_total'] for n in nodes),
                            cores_allocated=sum(n['cores_used'] for n in nodes),
                            cores_idle=sum(max(0, n['cores_total'] - n['cores_used']) for n in nodes
                                           if n['state'] == 'free'),
                            mem_total_gb=known_sum(n['mem_total_gb'] for n in nodes),
                            mem_allocated_gb=known_sum(n['mem_assigned_gb'] for n in nodes))
            hardware['cores_other'] = max(0, hardware['cores_total'] - hardware['cores_allocated'] - hardware['cores_idle'])
        else:
            hardware['error'] = '未返回节点硬件'
        return nodes, hardware
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return [], empty_hardware('pbsnodes', redact_stderr(f'Hardware query failed: {exc}', cfg))


def job_sort_key(row):
    running = row['state'] in ('R', 'E')
    stamp = row['start_time'] if running else row['qtime']
    # Validated PBS IDs arrive here before the cluster prefix is added. Compare
    # the sequence numerically so unknown/equal times do not put 1000 before 999.
    sequence = int(re.match(r'\d+', row['job_id'])[0])
    return (not row['mine'], not running, stamp is None, stamp or '', sequence, row['job_id'])


def empty_summary():
    return {prefix + key: None for prefix in ('', 'others_')
            for key in ('running_jobs', 'running_cores', 'queued_jobs', 'queued_cores')}


def job_summary(rows):
    summary = empty_summary()
    for prefix, subset in (('', rows), ('others_', [r for r in rows if not r['mine']])):
        for kind, running in (('running', True), ('queued', False)):
            jobs = [r for r in subset if (r['state'] in ('R', 'E', *slurm.RUNNING)) == running]
            summary[prefix + kind + '_jobs'] = len(jobs)
            summary[prefix + kind + '_cores'] = known_sum(r['cores'] for r in jobs)
    return summary


def memory_totals(rows):
    return {f'mem_{kind}_gb': known_sum(r['mem_gb'] for r in rows
                                       if (r['state'] in ('R', 'E', *slurm.RUNNING)) == running)
            for kind, running in (('running', True), ('queued', False))}


def slurm_elapsed(value):
    # squeue %M emits MM:SS for jobs less than one hour old.
    if re.fullmatch(r'\d+:[0-5]\d', value):
        minutes, seconds = map(int, value.split(':'))
        return minutes * 60 + seconds
    return pbs.duration_seconds(value)


def slurm_partition(cfg, transport, own):
    partition = cfg.get('partition')
    if not partition:
        return empty_summary(), empty_hardware('sinfo', '未配置分区'), None
    summary_error = None
    inconsistent = False
    try:
        summary = slurm.parse_partition_jobs(require_ok(
            transport.run(remote.slurm_partition_jobs(partition)), 'squeue partition jobs'))
        mine = job_summary([row for row in own if row['queue'] == partition])
        for key, value in list(summary.items()):
            difference = value - mine[key]
            summary['others_' + key] = difference if difference >= 0 else None
            inconsistent |= difference < 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        summary = empty_summary()
        summary_error = redact_stderr(f'Partition job query failed: {exc}', cfg)
    hardware = empty_hardware('sinfo')
    try:
        hardware.update(slurm.parse_partition_hardware(require_ok(
            transport.run(remote.slurm_partition_hardware(partition)), 'sinfo partition hardware')))
        if hardware['mem_total_gb'] is None:
            hardware['notes'].append('sinfo 内存为异构节点最小值，总内存未知')
        hardware['mem_allocated_gb'] = slurm.parse_allocmem(require_ok(
            transport.run(remote.slurm_partition_allocmem(partition)), 'sinfo AllocMem'))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # An AllocMem failure must not erase a successful CPU/total-memory sample.
        hardware['error'] = '; '.join(filter(None, [hardware['error'],
            redact_stderr(f'Hardware query failed: {exc}', cfg)]))
    if inconsistent:
        for key in summary:
            if key.startswith('others_'):
                summary[key] = None
        hardware['notes'].append('两次作业查询不一致，他人汇总出现负数')
    return summary, hardware, summary_error


def slurm_nodes(cfg, transport):
    partition = cfg.get('partition')
    if not partition:
        return [], '未配置分区'
    try:
        raw = require_ok(transport.run(remote.slurm_partition_nodes(partition)), 'sinfo nodes')
        return slurm.parse_nodes(raw, partition), None
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # Independent from successful own-job and legacy hardware observations.
        return [], redact_stderr(f'Node capacity query failed: {exc}', cfg)
