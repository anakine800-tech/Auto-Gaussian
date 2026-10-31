"""Classify current local monitor evidence without probing or rerouting jobs."""
from datetime import datetime, timezone
import math
import os
from pathlib import Path

from ag import _autonomy_store as disk
from ag.config import cluster_name, scheduler_kind


def _entries(cfg):
    return cfg.get('clusters', cfg.get('_cluster_entries', {cfg.get('_cluster', 'default'): cfg}))


def _time(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError('Link health time requires a timezone')
        value = value.timestamp()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Link health time must be finite')
    return value


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing monitor timestamp')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Monitor timestamp requires a timezone')
    return stamp.astimezone(timezone.utc)


def _entry(name, cfg, snapshot, at):
    row = dict(name=name, relay_group=cfg.get('relay_group'), sampled_at=None,
               age_seconds=None, interval_seconds=None, status='unknown', reason='missing')
    if snapshot is None:
        return row
    row['reason'] = 'invalid'
    try:
        stamp = _stamp(snapshot['sampled_at'])
        row.update(sampled_at=stamp.isoformat(), age_seconds=at - stamp.timestamp())
        interval = snapshot['interval_seconds']
        if type(interval) is not int or not 30 <= interval <= 600:
            return row
        row['interval_seconds'] = interval
        if (snapshot['schema'] != 'ag-monitor/1' or type(snapshot['ok']) is not bool
                or not isinstance(snapshot['own'], dict) or not isinstance(snapshot['cluster'], dict)
                or snapshot['cluster'].get('name', name) != name
                or snapshot['cluster'].get('scheduler', scheduler_kind(cfg)) != scheduler_kind(cfg)
                or snapshot['error'] is not None and not isinstance(snapshot['error'], str)
                or not isinstance(snapshot['warnings'], list)):
            return row
        for section, counters, lists in (
            ('own', ('cores_in_use', 'core_cap'), ('jobs',)),
            ('cluster', ('cores_total', 'cores_used'), ('nodes', 'queues')),
        ):
            data = snapshot[section]
            if (any(data[key] is not None and type(data[key]) is not int for key in counters)
                    or any(not isinstance(data[key], list) for key in lists)):
                return row
        last_ok = snapshot['last_ok_at']
        if last_ok is not None:
            last_ok = _stamp(last_ok)
        if snapshot['ok'] and last_ok != stamp:
            return row
        if snapshot.get('config_removed') or snapshot.get('config_warning'):
            row['reason'] = 'configuration'
        elif row['age_seconds'] < 0:
            row['reason'] = 'future'
        elif row['age_seconds'] > 3 * interval:
            row['reason'] = 'stale'
        elif snapshot['ok'] and not snapshot.get('error'):
            row.update(status='success', reason=None)
        elif not snapshot['ok'] and snapshot.get('error'):
            # Retained last_ok_at / scheduler values never override this sample.
            row.update(status='failed', reason='sample_failed')
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        pass
    return row


def _status(rows):
    if not rows:
        return 'unknown'
    if all(row['status'] == 'failed' for row in rows):
        return 'local_outage'
    relay = [row for row in rows if row['relay_group'] is not None]
    if (relay and all(row['status'] == 'failed' for row in relay)
            and any(row['relay_group'] is None and row['status'] == 'success' for row in rows)):
        return 'relay_outage'
    if any(row['status'] == 'unknown' for row in rows):
        return 'unknown'
    if any(row['status'] == 'failed' for row in rows):
        return 'cluster_failure'
    return 'healthy'


def classify(cfg, snapshots, *, now):
    """Pure summary of supplied samples; never an action authorization."""
    at = _time(now)
    rows = [_entry(name, entry, snapshots.get(name), at)
            for name, entry in sorted(_entries(cfg).items())]
    result = dict(schema='ag-link-health/1', observed_at=at, status=_status(rows), entries=rows)
    validate(result)
    return result


def validate(report):
    """Check the small persisted summary when replaying an autonomy event."""
    fields = {'name', 'relay_group', 'sampled_at', 'age_seconds', 'interval_seconds', 'status', 'reason'}
    try:
        if (set(report) != {'schema', 'observed_at', 'status', 'entries'}
                or report['schema'] != 'ag-link-health/1' or not isinstance(report['entries'], list)):
            raise ValueError('Invalid link health summary')
        at = _time(report['observed_at'])
        names = []
        for row in report['entries']:
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError('Invalid link health entry')
            names.append(cluster_name(row['name']))
            if row['relay_group'] is not None:
                cluster_name(row['relay_group'])
            stamp, age, interval = row['sampled_at'], row['age_seconds'], row['interval_seconds']
            if stamp is None:
                if age is not None:
                    raise ValueError('Missing link health timestamp')
            elif (_time(age) != at - _stamp(stamp).timestamp()):
                raise ValueError('Inconsistent link health age')
            if interval is not None and (type(interval) is not int or not 30 <= interval <= 600):
                raise ValueError('Invalid link health interval')
            if row['status'] in ('success', 'failed'):
                if (age is None or interval is None or not 0 <= age <= 3 * interval
                        or row['reason'] != (None if row['status'] == 'success' else 'sample_failed')):
                    raise ValueError('Invalid current link health evidence')
            elif row['status'] != 'unknown' or row['reason'] not in (
                    'missing', 'invalid', 'configuration', 'future', 'stale'):
                raise ValueError('Invalid unknown link health evidence')
        if names != sorted(set(names)) or report['status'] != _status(report['entries']):
            raise ValueError('Inconsistent link health classification')
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError('Invalid link health summary') from exc
    return report


def read(cfg, *, now=None):
    """Read bounded cache files without creating directories or contacting SSH."""
    at = datetime.now(timezone.utc) if now is None else now
    snapshots = {}
    for name in _entries(cfg):
        snapshots[name] = None
        try:
            root = Path(cfg['local']['studies_root']) / '.ag-monitor'
            named, legacy = root / name / 'latest.json', root / 'latest.json'
            path = named if ('clusters' in cfg or '_cluster_entries' in cfg
                             or cfg.get('_cluster') or name != 'default') else legacy
            if name == 'default' and named.exists() and legacy.exists():
                raise ValueError('Ambiguous default monitor cache')
            fd = disk.directory(path.parent)
            try:
                with os.fdopen(disk.Store(fd).open(path.name, os.O_RDONLY), 'rb') as handle:
                    raw = handle.read(2 * 1024 * 1024 + 1)
            finally:
                os.close(fd)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Oversize monitor cache')
            snapshots[name] = disk.decode(raw)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            # Report only a fixed unknown reason: no raw errors, paths or jobs.
            snapshots[name] = {}
    return classify(cfg, snapshots, now=at)
