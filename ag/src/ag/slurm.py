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


RUNNING = frozenset({'RUNNING', 'COMPLETING'})


def parse_partition_jobs(text):
    """Anonymous per-partition job counts, including array children."""
    summary = dict(running_jobs=0, running_cores=0, queued_jobs=0, queued_cores=0)
    for line in text.splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) != 2 or fields[0] not in ACTIVE | TERMINAL or not fields[1].isdigit() or int(fields[1]) < 1:
            raise ValueError('Invalid anonymous partition job record')
        state, cpus = fields
        if state in TERMINAL:
            continue
        prefix = 'running' if state in RUNNING else 'queued'
        summary[prefix + '_jobs'] += 1
        summary[prefix + '_cores'] += int(cpus)
    return summary


def parse_partition_hardware(text):
    """sinfo A/I/O/T are row totals; memory is MB per node, never per CPU."""
    totals = dict(cores_allocated=0, cores_idle=0, cores_other=0, cores_total=0, mem_total_gb=0)
    if not text.strip():
        raise ValueError('No partition hardware returned')
    for line in text.splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) != 3:
            raise ValueError('Invalid sinfo hardware record')
        cpus = fields[0].split('/')
        if (len(cpus) != 4 or any(not v.isdigit() for v in cpus + fields[2:])
                or not re.fullmatch(r'\d+\+?', fields[1])):
            raise ValueError('Unknown or heterogeneous sinfo hardware values')
        allocated, idle, other, total = map(int, cpus)
        if allocated + idle + other != total or int(fields[2]) < 1:
            raise ValueError('Inconsistent sinfo CPU totals')
        for key, value in zip(('cores_allocated', 'cores_idle', 'cores_other', 'cores_total'),
                              (allocated, idle, other, total)):
            totals[key] += value
        # Live sinfo can print a minimum followed by '+' for unequal nodes.
        # Multiplying that minimum would misreport the partition's capacity.
        if fields[1].endswith('+'):
            totals['mem_total_gb'] = None
        elif totals['mem_total_gb'] is not None:
            totals['mem_total_gb'] += int(fields[1]) * int(fields[2]) / 1024
    if totals['mem_total_gb'] is not None:
        totals['mem_total_gb'] = round(totals['mem_total_gb'], 1)
    return totals


def parse_allocmem(text):
    """Verified sinfo -N -O AllocMem:20: one MB value per node, no names."""
    values = text.splitlines()
    if not values or any(not value.strip().isdigit() for value in values):
        raise ValueError('Unknown sinfo AllocMem values')
    return round(sum(int(value.strip()) for value in values) / 1024, 1)


def parse_nodes(text, partition):
    """Fixed sinfo -N -e -O rows. Unknown values stay unknown, never zero."""
    remote.slurm_token(partition)
    rows = {}
    if not text.strip():
        raise ValueError('No partition nodes returned')
    for line in text.splitlines():
        fields = [v.strip() for v in line.split('|')]
        if (len(fields) != 7 or any(len(v) >= width for v, width in
                zip(fields, (256, 256, 64, 64, 64, 64, 32)))):
            raise ValueError('Invalid or truncated sinfo node record')
        name, entry, cpus, memory, allocated, state, available = fields
        remote.slurm_token(name)
        remote.slurm_token(entry)
        if entry != partition:
            raise ValueError('sinfo returned a different partition')
        total = used = idle = other = None
        counts = cpus.split('/')
        if len(counts) == 4 and all(v.isdigit() for v in counts):
            a, i, o, t = map(int, counts)
            if a + i + o == t and t > 0:
                used, idle, other, total = a, i, o, t
        # Keep exact binary GB fractions: rounding up could manufacture room.
        mem_total = int(memory) / 1024 if memory.isdigit() else None
        mem_assigned = int(allocated) / 1024 if allocated.isdigit() else None
        if mem_total is not None and mem_total <= 0:
            mem_total = None
        if mem_total is not None and mem_assigned is not None and mem_assigned > mem_total:
            mem_assigned = None
        row = dict(name=name, partition=entry, partition_state=available,
                   state=state, cores_total=total, cores_used=used,
                   cores_idle=idle, cores_other=other, mem_total_gb=mem_total,
                   mem_assigned_gb=mem_assigned, cpu_source='sinfo CPUsState',
                   memory_source='sinfo Memory/AllocMem')
        # -N may repeat a node. Identical rows count once; disagreement cannot
        # select whichever allocation happens to make a request look feasible.
        if name in rows and rows[name] != row:
            rows[name]['capacity_error'] = 'Conflicting duplicate node records'
        else:
            rows[name] = row
    return list(rows.values())
