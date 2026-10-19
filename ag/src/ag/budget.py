"""Local per-entry accounting; ambiguity never frees reserved cores.

Persist the reservation before remote writes, so a lost sbatch reply cannot
make the same credit available for another job. Callers serialize with the
existing submission lock; reconciliation takes that same lock.
"""
from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile
from ag.config import cluster_name, scheduler_kind, shared_clusters
from ag.transport import redact_stderr


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
    try:
        contents = path.read_text()
    except FileNotFoundError:
        missing = True
        value = dict(cluster=cfg['_cluster'], attempts={})
    else:
        missing = False
        value = json.loads(contents)
    if value.get('cluster') != cfg['_cluster'] or not isinstance(value.get('attempts'), dict):
        raise ValueError('Invalid cluster budget ledger')
    for aid, row in value['attempts'].items():
        if (not isinstance(row, dict) or row.get('state') not in ('reserved', 'settled', 'rejected')
                or any(type(row.get(k)) is not int or row[k] < 0 for k in ('used', 'reserved'))):
            raise ValueError(f'Attempt {aid}: invalid budget ledger entry; cannot infer available credit')
    # A missing ledger is empty only for a never-submitted entry. Scan every
    # local study so deletion cannot silently release another study's cores.
    # Existing partial-ledger claim checks remain in force; never reconstruct.
    from ag import attempt
    try:
        for path, m, current, job in attempt.local_records(
                cfg['local']['studies_root'], cfg['_cluster'], scheduler_kind(cfg)):
            claim = path / '.submit-claim'
            if (claim.exists() or claim.is_symlink()) and m['attempt_id'] not in value['attempts']:
                raise ValueError(f'Attempt {path.name} (study {m["study_id"]}): claimed Attempt missing from budget ledger; human reconciliation required')
            if missing and ((path / 'submission.json').exists() or job is not None or current['state'] != 'prepared'):
                raise ValueError(f'Attempt {path.name} (study {m["study_id"]}): submission trace missing from budget ledger; human reconciliation required')
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        if not missing:
            raise
        raise ValueError(f'Cluster {cfg["_cluster"]}: budget ledger missing; {redact_stderr(exc, cfg)}；'
                         '从备份或原配置目录找回该入口的台账；找不到则停止并交给负责人核对') from None
    return value


def totals(cfg, *, ledger=None):
    ledger = read(cfg) if ledger is None else ledger
    return (sum(v['used'] for v in ledger['attempts'].values()),
            sum(v['reserved'] for v in ledger['attempts'].values()))


def public_summary(cfg):
    """The local estimate is not a platform balance; stop publishing a budget."""
    return None


def check(cfg, amount, *, ledger=None):
    """Retained for callers; budget_core_hours no longer gates submission."""
    return None


def summary(cfg, amount):
    return f'本次最多消耗 {amount / 3600:g} 核时（核数 × walltime；实际以平台计费为准）'


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
    from ag import attempt
    visible = {job['job_id']: job for job in jobs}
    cores = 0
    for aid, row in ledger['attempts'].items():
        if row['state'] != 'reserved' or aid == exclude:
            continue
        path = attempt.find(cfg, aid)
        record = attempt.local_record(path, cfg['_cluster'], scheduler_kind(cfg))
        if record is None:
            raise ValueError(f'Attempt {aid}: budget/core reservation cluster mismatch')
        m, _, job = record
        if m['bundle_sha256'] != row['bundle_sha256']:
            raise ValueError(f'Attempt {path.name} (study {m["study_id"]}): budget/core reservation identity mismatch')
        observed = visible.get(job)
        if observed is not None and observed.get('name') != m['attempt_id']:
            raise ValueError(f'Attempt {aid}: scheduler/core reservation identity mismatch')
        if observed is None:
            cores += m['cores']
    return cores


def shared_ledgers(cfg):
    """Read peers only, under submit's existing config-directory lock.

    A missing ledger may start empty only without any local submission trace.
    Reading never creates peer ledgers; reserve() writes only the target entry.
    """
    ledgers = {}
    for name, entry in shared_clusters(cfg).items():
        try:
            ledgers[name] = read(entry)
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
            raise ValueError(f'Cluster {name}: cannot read budget-{name}.json ({redact_stderr(exc, entry)})') from None
    return ledgers


def shared_unobserved_cores(cfg, jobs, ledgers, *, exclude=None):
    cores = 0
    for name, entry in shared_clusters(cfg).items():
        try:
            cores += unobserved_cores(entry, jobs, ledgers[name],
                                     exclude=exclude if name == cfg['_cluster'] else None)
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
            raise ValueError(f'Cluster {name}: cannot account for budget-{name}.json ({redact_stderr(exc, entry)})') from None
    return cores
