"""Local per-cluster core-hour reservations; ambiguity never frees budget.

Persist the reservation before remote writes, so a lost sbatch reply cannot
make the same credit available for another job. Callers serialize with the
existing submission lock; reconciliation takes that same lock.
"""
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import tempfile
from ag.config import cluster_name


def seconds(value):
    match = re.fullmatch(r'(?:(\d+)-)?(\d+):([0-5]\d):([0-5]\d)', value)
    if not match:
        raise ValueError('Invalid elapsed/walltime; budget remains reserved')
    days, hours, minutes, sec = (int(v or 0) for v in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + sec


def requested(m):
    return m['cores'] * seconds(m['walltime'])


def ledger_path(cfg):
    return Path(cfg['_config_dir']) / ('budget-' + cluster_name(cfg['_cluster']) + '.json')


def read(cfg):
    path = ledger_path(cfg)
    if path.is_symlink():
        raise ValueError('Budget ledger must not be a symbolic link')
    value = json.loads(path.read_text()) if path.exists() else dict(cluster=cfg['_cluster'], attempts={})
    if value.get('cluster') != cfg['_cluster'] or not isinstance(value.get('attempts'), dict):
        raise ValueError('Invalid cluster budget ledger')
    for row in value['attempts'].values():
        if (not isinstance(row, dict) or row.get('state') not in ('reserved', 'settled', 'rejected')
                or any(type(row.get(k)) is not int or row[k] < 0 for k in ('used', 'reserved'))):
            raise ValueError('Invalid budget ledger entry; cannot infer available credit')
    # A missing/partial ledger after a crash or manual deletion must not reset
    # already committed spend to zero. No reconstruction from guessed timings.
    root = Path(cfg['local']['studies_root'])
    for manifest in root.glob('*/attempts/*/manifest.json'):
        m = json.loads(manifest.read_text())
        if m.get('cluster') != cfg['_cluster'] or m.get('scheduler') != 'slurm':
            continue
        if (manifest.parent / '.submit-claim').exists() and m['attempt_id'] not in value['attempts']:
            raise ValueError('Claimed Attempt missing from budget ledger; human reconciliation required')
    return value


def totals(cfg, *, ledger=None):
    ledger = read(cfg) if ledger is None else ledger
    return (sum(v['used'] for v in ledger['attempts'].values()),
            sum(v['reserved'] for v in ledger['attempts'].values()))


def check(cfg, amount, *, ledger=None):
    used, reserved = totals(cfg, ledger=ledger)
    maximum = cfg['resources'].get('budget_core_hours')
    if maximum is not None and Decimal(used + reserved + amount) > Decimal(str(maximum)) * 3600:
        raise ValueError('Core-hour budget exceeded: used + reserved + requested exceeds budget')
    return used, reserved, maximum


def summary(cfg, amount):
    used, reserved = totals(cfg)
    maximum = cfg['resources'].get('budget_core_hours')
    bound = f'{maximum:g}' if maximum is not None else '未设置'
    return (f'本次最多 {amount / 3600:g} 核时；累计已用 {used / 3600:g}、'
            f'预留 {reserved / 3600:g}、预算 {bound} 核时（实际费用以平台计费为准）')


def write(cfg, ledger):
    path = ledger_path(cfg)
    fd, temporary = tempfile.mkstemp(prefix='.budget-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(ledger, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reserve(cfg, m, ledger):
    if m['attempt_id'] in ledger['attempts']:
        raise ValueError('Attempt budget reservation already exists; do not resubmit')
    check(cfg, requested(m), ledger=ledger)
    ledger['attempts'][m['attempt_id']] = dict(state='reserved', used=0, reserved=requested(m),
                                             bundle_sha256=m['bundle_sha256'])
    write(cfg, ledger)


def settle(cfg, m, elapsed=None, *, rejected=False, job_id=None):
    from ag.locks import submission_lock
    with submission_lock(cfg):
        ledger = read(cfg)
        row = ledger['attempts'].get(m['attempt_id'])
        if row is None or row['bundle_sha256'] != m['bundle_sha256']:
            raise ValueError('Budget reservation missing or mismatched')
        final = dict(state='rejected' if rejected else 'settled', reserved=0,
                     used=0 if rejected else m['cores'] * seconds(elapsed),
                     bundle_sha256=m['bundle_sha256'], job_id=job_id)
        if row['state'] != 'reserved' and row != final:
            raise ValueError('Conflicting budget settlement; human reconciliation required')
        ledger['attempts'][m['attempt_id']] = final
        write(cfg, ledger)


def expiry_warning(cfg, today=None):
    if not cfg.get('expires'):
        return None
    remaining = (date.fromisoformat(cfg['expires']) - (today or date.today())).days
    if remaining <= 14:
        return '资源即将到期，请先 fetch 全部结果' if remaining >= 0 else '资源已到期，请先 fetch 全部结果'
    return None


def reject(cfg, m, ledger):
    """Caller already holds submission_lock; only certain presubmit failure."""
    row = ledger['attempts'][m['attempt_id']]
    if row['state'] != 'reserved':
        raise ValueError('Cannot release an unreserved Attempt')
    ledger['attempts'][m['attempt_id']] = dict(state='rejected', reserved=0, used=0,
                                             bundle_sha256=m['bundle_sha256'], job_id=None)
    write(cfg, ledger)


def unobserved_cores(cfg, jobs, ledger, *, exclude=None):
    """squeue readback may lag across separate submit invocations, not just a batch.

    Reserve still-unsettled local jobs absent from the queue. An UNKNOWN job
    without a bound ID is conservatively counted until read-only reconciliation.
    """
    from ag import attempt, submission
    visible = {job['job_id'] for job in jobs}
    cores = 0
    for aid, row in ledger['attempts'].items():
        if row['state'] != 'reserved' or aid == exclude:
            continue
        path = attempt.find(cfg, aid)
        m = attempt.read_manifest(path)
        if m.get('cluster') != cfg['_cluster'] or m['bundle_sha256'] != row['bundle_sha256']:
            raise ValueError('Budget/core reservation identity mismatch')
        record = path / 'submission.json'
        if record.is_symlink():
            raise ValueError('Submission manifest must not be a symbolic link')
        job = submission.raw_job(m, json.loads(record.read_text())['job_id']) if record.exists() else None
        if job not in visible:
            cores += m['cores']
    return cores
