"""Strict parsing of Slurm observations; no remote shell construction here."""
import re
from ag import remote

TERMINAL = frozenset({'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY',
                      'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'DEADLINE', 'REVOKED'})
ACTIVE = frozenset({'PENDING', 'RUNNING', 'CONFIGURING', 'COMPLETING', 'SUSPENDED',
                   'RESIZING', 'REQUEUED', 'REQUEUE_FED', 'REQUEUE_HOLD', 'SIGNALING',
                   'SPECIAL_EXIT', 'STAGE_OUT', 'STOPPED'})


def parse_submission(text):
    parts = text.strip().split(';')
    if len(parts) > 2 or (len(parts) == 2 and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', parts[1])):
        raise ValueError('Invalid sbatch response')
    return remote.slurm_job_id(parts[0]), parts[1] if len(parts) == 2 else None


def parse_queue(text):
    jobs = []
    seen = set()
    for line in text.splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) != 7:
            raise ValueError('Invalid squeue record; cannot count cores')
        job, name, owner, state, cpus, elapsed, partition = fields
        # -r expands arrays. Heterogeneous components each reserve their own CPUs.
        if not re.fullmatch(r'[1-9][0-9]*(?:_[0-9]+|\+[0-9]+)?', job) or job in seen:
            raise ValueError('Invalid or duplicate squeue job identity')
        if not name or not re.fullmatch(r'[A-Za-z0-9_.-]+', owner) or state not in ACTIVE | TERMINAL:
            raise ValueError('Invalid squeue owner/state/name')
        if not cpus.isdigit() or int(cpus) < 1:
            raise ValueError('Invalid squeue requested/allocated CPUs')
        seen.add(job)
        jobs.append(dict(job_id=job, name=name, owner=owner, state=state,
                         cores=int(cpus), elapsed=elapsed, partition=partition))
    return jobs


def core_breakdown(jobs, username):
    if any(j['owner'] != username for j in jobs):
        raise ValueError('squeue user filter returned a different owner')
    running = sum(j['cores'] for j in jobs if j['state'] in {'RUNNING', 'COMPLETING'})
    queued = sum(j['cores'] for j in jobs if j['state'] in ACTIVE - {'RUNNING', 'COMPLETING'})
    return running, queued


def parse_accounting(text, job_id=None, *, name=None, username=None, allow_arrays=False):
    jobs = []
    seen = set()
    for line in text.splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) != 7:
            raise ValueError('Invalid sacct record')
        job, job_name, owner, state, exitcode, elapsed, cpus = fields
        if (not job_name or not re.fullmatch(r'[A-Za-z0-9_.-]+', owner)
                or (name is not None and job_name != name)
                or (username is not None and owner != username)):
            raise ValueError('sacct name/owner identity mismatch')
        if allow_arrays:
            if not re.fullmatch(r'[1-9][0-9]*(?:_[0-9]+|\+[0-9]+)?', job):
                raise ValueError('Invalid sacct allocation identity')
        else:
            remote.slurm_job_id(job)
        if job in seen or (job_id is not None and job != job_id):
            raise ValueError('sacct exact-job identity mismatch')
        seen.add(job)
        # CANCELLED may carry "by <uid>". Truncated state names fail closed.
        if re.fullmatch(r'CANCELLED by [0-9]+', state):
            state = 'CANCELLED'
        if state not in ACTIVE | TERMINAL or not re.fullmatch(r'[0-9]+:[0-9]+', exitcode):
            raise ValueError('Invalid sacct state/ExitCode')
        if not cpus.isdigit():
            raise ValueError('Invalid sacct AllocCPUS')
        code, signal = map(int, exitcode.split(':'))
        jobs.append(dict(job_id=job, state=state, exit_code=code, exit_signal=signal,
                         elapsed=elapsed, allocated_cpus=int(cpus)))
    return jobs
