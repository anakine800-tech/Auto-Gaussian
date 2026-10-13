"""Read-only scheduler observations and conservative unknown reconciliation."""
import re
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


def inventory(transport):
    username = require_ok(transport.run(remote.identity()), 'identity').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
        raise ValueError('Cannot identify remote user')
    jobs = parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat'))
    return username, jobs, occupied(jobs, username)


def check(cfg, path, transport):
    m, current = attempt.read_manifest(path), state.read(path)
    journal.append(path.parent.parent, 'status', path.name, 'query', current['state'])
    if current['state'] == 'submitting':
        # A process interrupted after its claim cannot establish whether qsub ran.
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
    if current['state'] != 'submitted':
        return current
    result = transport.run(remote.jobs(current['job_id']))
    if not result.returncode:
        jobs = parse_jobs(result.stdout)
        if len(jobs) != 1 or jobs[0]['job_id'] != current['job_id'] or jobs[0].get('Job_Name') != m['pbs_job_name']:
            raise ValueError('Scheduler identity mismatch; stop')
        job = jobs[0]
        if job.get('job_state') == 'C':
            raw = job.get('exit_status', job.get('Exit_status'))
            return state.write(path, 'finished', exit_status=int(raw) if raw is not None else None)
        return {**current, 'scheduler_state': job.get('job_state')}
    if result.returncode == 255 or 'Unknown Job Id' not in result.stderr:
        raise TransportError('qstat failed; stop without inferring job completion')
    output = transport.run(remote.output_exists(cfg, m, 'job.pbs.out'))
    if output.returncode == 0:
        return state.write(path, 'finished', note='Job absent with PBS output; exit status unavailable')
    if output.returncode != 1:
        require_ok(output, 'output inspection')
    return {**current, 'note': 'Job absent but no PBS output; state retained'}
