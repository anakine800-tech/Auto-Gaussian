"""Atomic local status updates; unknown never returns to prepared."""
import json
import os
import tempfile
from ag import journal

TRANSITIONS = {
    'prepared': {'submitting'},
    'submitting': {'submitted', 'failed_presubmit', 'unknown'},
    'unknown': {'submitted', 'running', 'finished'},
    'awaiting_second_observation': {'submitted', 'running', 'stalled', 'interrupted', 'finished'},
    'submitted': {'unknown', 'awaiting_second_observation', 'running', 'stalled', 'interrupted', 'finished', 'cancelled'},
    'running': {'unknown', 'awaiting_second_observation', 'submitted', 'stalled', 'interrupted', 'finished', 'cancelled'},
    'stalled': {'awaiting_second_observation', 'submitted', 'running', 'interrupted', 'finished', 'cancelled'},
    'interrupted': {'unknown', 'awaiting_second_observation', 'submitted', 'running', 'stalled', 'finished'},
    'finished': {'fetched'},
    'fetched': set(), 'cancelled': {'finished', 'unknown'}, 'failed_presubmit': set(),
}


def read(attempt):
    return json.loads((attempt / 'status.json').read_text())


def write(attempt, state, *, job_id=None, exit_status=None, note=None, initial=False, **details):
    old = {} if initial else read(attempt)
    if initial:
        if state != 'prepared' or (attempt / 'status.json').exists():
            raise ValueError('Invalid initial state')
    elif state != old['state'] and state not in TRANSITIONS[old['state']]:
        raise ValueError(f"Invalid transition: {old['state']} -> {state}")
    if set(details) & {'state', 'job_id', 'exit_status', 'updated_at', 'note'}:
        raise ValueError('Status details cannot replace lifecycle fields')
    value = dict(old)
    value.update(state=state, job_id=job_id if job_id is not None else old.get('job_id'),
                 exit_status=exit_status, updated_at=journal.now(), note=note)
    value.update(details)
    fd, temp = tempfile.mkstemp(prefix='.status-', dir=attempt)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, attempt / 'status.json')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    journal.append(attempt.parent.parent, 'state', attempt.name, state, note)
    return value
