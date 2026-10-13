"""Read-only scheduler observations and conservative unknown reconciliation."""
import re
import json
import time
from datetime import datetime, timezone
from ag import attempt, journal, remote, state
from ag.transport import require_ok, TransportError


def parse_jobs(text):
    jobs = []
    current = None
    last_key = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith('Job Id:'):
            current = {'job_id': remote.job_id(line.split(':', 1)[1].strip())}
            jobs.append(current)
            last_key = None
        elif current is not None and re.match(r'^\s+[^\s=]+\s+=\s*', line):
            key, value = line.strip().split(' = ', 1)
            if key in current:
                raise ValueError('Duplicate scheduler attribute')
            current[key] = value
            last_key = key
        elif current is not None and line[:1].isspace() and last_key:
            current[last_key] += line.strip()
        else:
            raise ValueError('Unrecognized qstat output; cannot determine scheduler state')
    return jobs


def occupied(jobs, username):
    total = 0
    for job in jobs:
        if not job.get('Job_Owner') or not job.get('job_state'):
            raise ValueError('Scheduler record lacks owner/state; cannot count cores')
        if job['Job_Owner'].split('@')[0] != username or job['job_state'] == 'C':
            continue
        # Include E/T/W/S as well: these may still occupy or reserve resources.
        nodes = job.get('Resource_List.nodes')
        if not nodes:
            raise ValueError('Missing node/ppn resource request; cannot count cores')
        for chunk in nodes.split('+'):
            fields = chunk.split(':')
            count = int(fields[0]) if fields[0].isdigit() else 1
            ppn = [field[4:] for field in fields[1:] if field.startswith('ppn=')]
            if len(ppn) != 1 or not ppn[0].isdigit() or int(ppn[0]) < 1 or count < 1:
                raise ValueError('Unrecognized ppn resource request; cannot count cores')
            total += count * int(ppn[0])
    return total


def core_breakdown(jobs, username):
    """Use occupied's accounting; every non-C state outside R/E is queued."""
    total = occupied(jobs, username)
    running = occupied([job for job in jobs if job.get('job_state') in ('R', 'E')], username)
    return running, total - running


def inventory(transport):
    username = require_ok(transport.run(remote.identity()), 'identity').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
        raise ValueError('Cannot identify remote user')
    jobs = parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat'))
    return username, jobs, occupied(jobs, username)


def read_receipt(cfg, manifest, transport, name, job_id):
    raw = require_ok(transport.run(remote.receipt(cfg, manifest, name)), 'completion receipt')
    if raw == 'absent\n':
        return None
    if len(raw.encode()) > 4096:
        raise ValueError('Completion receipt exceeds 4 KB')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate receipt field')
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        key = 'started_at' if name == 'ag-start.json' else 'finished_at'
        stamp = datetime.fromisoformat(value[key].replace('Z', '+00:00'))
        if stamp.tzinfo is None or value['PBS_JOBID'] != job_id:
            raise ValueError('Receipt time/job identity mismatch')
        if name == 'ag-exit.json' and (type(value['returncode']) is not int or not 0 <= value['returncode'] <= 255):
            raise ValueError('Invalid program return code')
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError('Invalid or incomplete completion receipt; do not infer completion') from exc
    return value


def outputs(cfg, manifest, transport):
    text = require_ok(transport.run(remote.output_observation(cfg, manifest)), 'output observation')
    result = {}
    names = remote.output_names(manifest)
    for line in text.splitlines():
        name, sep, rest = line.partition(' ')
        if not sep or name not in names or name in result:
            raise ValueError('Invalid output observation')
        if rest == 'absent':
            result[name] = None
        else:
            size, sep, mtime = rest.partition(' ')
            if not sep or not size.isdigit() or not re.fullmatch(
                    r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [+-]\d{4}', mtime):
                raise ValueError('Invalid output size/mtime')
            result[name] = {'size': int(size), 'mtime': mtime}
    if set(result) != set(names):
        raise ValueError('Missing declared output observations')
    return result


def processes(transport, session):
    result = transport.run(remote.session_processes(session))
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return {'session_id': session, 'absent': True, 'rows': []}
    text = require_ok(result, 'PBS session processes')
    rows = []
    for line in text.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) != 4 or not parts[0].isdigit() or parts[1] != session or not re.fullmatch(r'[A-Za-z<+]+', parts[2]):
            raise ValueError('Invalid ps session output; do not infer process absence')
        rows.append(dict(pid=int(parts[0]), session_id=parts[1], state=parts[2], command=parts[3]))
    if not rows:
        raise ValueError('Empty successful ps output; process absence unverified')
    return {'session_id': session, 'absent': False, 'rows': rows}


def scheduler_absent(result):
    """Normalize Torque's missing-job status without treating SSH failure as absence.

    The live Torque response included ``Unknown Job Id Error`` and exit 153;
    the old one-token suffix matcher rejected that valid missing-job result.
    """
    if result.returncode <= 0 or result.returncode == 255:
        return False
    return result.returncode == 153 or bool(re.fullmatch(
        r'(?:qstat:\s*)?Unknown Job Id(?:\s+Error)?(?:\s+\S+)?',
        result.stderr.strip() or result.stdout.strip(), flags=re.IGNORECASE))


def check(cfg, path, transport):
    if hasattr(transport, 'record_to'):
        transport.record_to([path])
    m, current = attempt.read_manifest(path), state.read(path)
    journal.append(path.parent.parent, 'status', path.name, 'query', current['state'])
    if current['state'] == 'submitting':
        current = state.write(path, 'unknown', note='Interrupted submission; read-only reconciliation required')
    if current['state'] == 'unknown':
        username, jobs, _ = inventory(transport)
        matches = [j for j in jobs if j.get('Job_Name') == m['pbs_job_name']
                   and j.get('Job_Owner', '').split('@')[0] == username]
        if len(matches) == 1:
            return state.write(path, 'submitted', job_id=matches[0]['job_id'], note='Read-only scheduler reconciliation')
        require_ok(transport.run(remote.listing(cfg, m)), 'unknown directory inspection')
        journal.append(path.parent.parent, 'status', path.name, 'unknown', 'No unique scheduler evidence; human review required')
        return {**current, 'note': 'No unique scheduler evidence; remains unknown. Human review required.'}
    if current['state'] not in ('submitted', 'running', 'stalled', 'interrupted', 'awaiting_second_observation', 'finished', 'fetched'):
        return current
    job_id = remote.job_id(current['job_id'])
    start = read_receipt(cfg, m, transport, 'ag-start.json', job_id)
    end = read_receipt(cfg, m, transport, 'ag-exit.json', job_id)
    result = transport.run(remote.jobs(job_id))
    job = None
    if not result.returncode:
        jobs = parse_jobs(result.stdout)
        if len(jobs) != 1 or jobs[0]['job_id'] != job_id or jobs[0].get('Job_Name') != m['pbs_job_name']:
            raise ValueError('Scheduler identity mismatch; stop')
        job = jobs[0]
        if not job.get('job_state'):
            raise ValueError('Scheduler state missing')
    elif not scheduler_absent(result):
        require_ok(result, 'qstat')
    scheduler = job.get('job_state') if job else None
    details = {'scheduler_state': scheduler, 'scheduler_residue': False,
               'receipts': {'start': start, 'exit': end}, 'cput': job.get('resources_used.cput') if job else None}
    observed = outputs(cfg, m, transport)
    now = time.time()
    previous = current.get('observation') or {}
    session = job.get('session_id') if job else previous.get('session_id')
    if session is not None:
        remote.session_processes(session)  # validate before retaining or executing
    details.update(scheduler_observed_at=now,
                   observation={'at': now, 'outputs': observed, 'session_id': session, 'job_id': job_id},
                   wait_seconds=None, next_observation_at=None)
    if end is not None or current['state'] in ('finished', 'fetched'):
        # These fields describe the latest observation, not historical completion evidence.
        details.update(unchanged_since=None, outputs_unchanged_60s=None, session_processes=None)
    if end is not None:
        details['scheduler_residue'] = scheduler == 'R'
        note = 'Program exited; 调度器残留 (PBS R)' if scheduler == 'R' else 'Program exit receipt verified'
        target = 'fetched' if current['state'] == 'fetched' else 'finished'
        return state.write(path, target, exit_status=end['returncode'], note=note,
                           completion_source='ag-exit.json', **details)
    # Do not rewind a previously evidenced/fetched result after scheduler cleanup.
    if current['state'] in ('finished', 'fetched'):
        details['scheduler_residue'] = scheduler == 'R'
        return state.write(path, current['state'], exit_status=current.get('exit_status'),
                           note=('调度器残留 (PBS R); previous completion evidence retained'
                                 if scheduler == 'R' else 'Previous completion evidence retained; no PBS R residue'),
                           **details)
    same = (previous.get('outputs') == observed and previous.get('session_id') == session
            and previous.get('job_id') == job_id and previous.get('at', now + 1) <= now)
    since = current.get('unchanged_since', previous.get('at', now)) if same else now
    stable = same and now - since >= 60
    details.update(observation={'at': now, 'outputs': observed, 'session_id': session, 'job_id': job_id},
                   unchanged_since=since, outputs_unchanged_60s=stable, session_processes=None)
    target = 'running' if scheduler == 'R' else ('interrupted' if scheduler in (None, 'C') else 'submitted')
    note = 'No exit receipt; awaiting program evidence'
    scheduler_failed = (scheduler == 'C' and
                        job.get('Exit_status', job.get('exit_status')) not in (None, '0'))
    if scheduler in (None, 'C'):
        note = 'No exit receipt; job absent from active scheduler (interrupted)'
        if not stable and not scheduler_failed:
            target = 'awaiting_second_observation'
            details.update(wait_seconds=max(0, now - since), next_observation_at=since + 60)
            note = '等待第二次观察；需相隔至少 60 秒的稳定输出及完整完成证据'
        elif scheduler_failed:
            note = 'Scheduler reports nonzero exit status; program exit receipt unavailable (interrupted)'

    if stable and scheduler == 'R':
        target, note = 'stalled', 'Declared outputs unchanged for at least 60 seconds; human review required'
    # When Torque no longer has the job, its session ID may be unavailable.
    # T1d permits legacy completion from a marker plus two stable observations
    # in that case. A remaining PBS R/C record still uses T1c's process check.
    legacy_candidate = stable and scheduler is None
    if stable and session is not None and scheduler in ('R', 'C'):
        ps = processes(transport, session)
        details['session_processes'] = ps
        legacy_candidate = ps['absent']
    elif stable and scheduler == 'R':
        note += '; PBS session ID unavailable, process absence cannot be checked'
    if legacy_candidate and not scheduler_failed and not m.get('completion_receipts') and start is None:
        marker = require_ok(transport.run(remote.completion_marker(cfg, m)), 'program completion marker')
        if marker not in ('present\n', 'absent\n'):
            raise ValueError('Invalid completion-marker observation')
        if marker == 'present\n':
            # Recheck after reading the marker: a resumed writer must not pass
            # using a stale size/mtime observation.
            after = outputs(cfg, m, transport)
            if after == observed:
                details['scheduler_residue'] = scheduler == 'R'
                source = ('legacy-marker-stable-scheduler-absent' if scheduler is None
                          else 'legacy-marker-stable-session-absent')
                return state.write(path, 'finished', note='Legacy completion evidence verified' +
                                   ('; 调度器残留 (PBS R)' if scheduler == 'R' else ''),
                                   completion_source=source, **details)
            details.update(observation={'at': time.time(), 'outputs': after,
                                        'session_id': session, 'job_id': job_id},
                           unchanged_since=time.time(), outputs_unchanged_60s=False)
            target = 'running' if scheduler == 'R' else 'awaiting_second_observation'
            if target == 'awaiting_second_observation':
                details.update(wait_seconds=0, next_observation_at=details['unchanged_since'] + 60)
            note = 'Outputs changed during legacy completion check; 等待第二次观察，completion unverified'
    return state.write(path, target, note=note, **details)


def format_status(results):
    """Human report with observation times; missing CPU time is never zero."""
    def stamp(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else '未知'

    lines = []
    for result in results:
        lines.append(f"{result['attempt_id']}: {result['state']}")
        if result.get('note'):
            lines.append(f"  {result['note']}")
        lines.append(f"  PBS: {result.get('scheduler_state') or '未知/无记录'}; "
                     f"resources_used.cput: {result.get('cput') or '未知'} "
                     f"(查询时间 {stamp(result.get('scheduler_observed_at'))})")
        observation = result.get('observation') or {}
        at = observation.get('at')
        age = f"{max(0, time.time() - at):.0f} 秒前" if at is not None else '未知'
        lines.append(f"  输出观察时间: {stamp(at)} ({age})")
        for name, info in observation.get('outputs', {}).items():
            lines.append(f"    {name}: size={info['size']} bytes; mtime={info['mtime']}"
                         if info is not None else f"    {name}: 未发现；size/mtime 未知")
        if result.get('next_observation_at') is not None:
            lines.append(f"  已等待 {result['wait_seconds']:.0f} 秒；最早再次观察: "
                         f"{stamp(result['next_observation_at'])}")
    return '\n'.join(lines)
