"""Strict parsing of Slurm observations; no remote shell construction here."""
import re
from datetime import datetime, timezone
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


# T187 observations only. The candidate grammar is SchedMD slurm-26-05-5-1:
# src/scontrol/info_job.c, src/sacct/sacct.c and src/common/sluid.c.
# Successful parsing is neither never-started proof nor execution permission.
_EVIDENCE_VERSION = r'[0-9]+\.[0-9]+\.[0-9]+'
_EVIDENCE_SLUID = r's[0-9A-F][0-9A-HJKMNP-TV-Z]{12}'
_EVIDENCE_TIME = r'(?:[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}|Unknown)'


def _evidence_text(text):
    if not isinstance(text, str) or any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in text):
        raise ValueError('Invalid Slurm evidence text')
    return text


def _evidence_cluster(value):
    if not isinstance(value, str) or value.casefold() == 'all':
        raise ValueError('Slurm evidence requires one actual cluster')
    return remote.slurm_token(value)


def _evidence_identity(job_id, cluster, name):
    if not isinstance(job_id, str) or not isinstance(name, str):
        raise ValueError('Invalid Slurm evidence job/name identity')
    remote.slurm_job_id(job_id)
    _evidence_cluster(cluster)
    # ag Attempt names are tokens. Accepting arbitrary whitespace here makes
    # scontrol's unescaped JobName output indistinguishable from forged keys.
    remote.slurm_token(name)


def _evidence_uint(value, bits, *, positive=False):
    if not re.fullmatch(r'0|[1-9][0-9]*', value):
        raise ValueError('Invalid Slurm evidence integer')
    result = int(value)
    if result >= 2 ** bits or positive and result == 0:
        raise ValueError('Slurm evidence integer outside its field range')
    return result


def _evidence_sluid(value):
    if not re.fullmatch(_EVIDENCE_SLUID, value) or value == 's0000000000000':
        raise ValueError('Invalid or missing Slurm evidence SLUID')
    return value


def _evidence_sluid_number(value):
    number = 0
    for character in _evidence_sluid(value)[1:]:
        number = number * 32 + '0123456789ABCDEFGHJKMNPQRSTVWXYZ'.index(character)
    return number


def _evidence_time(value, *, required=False):
    # Only the fixed commands using TZ=UTC and SLURM_TIME_FORMAT=standard feed
    # this parser. No local-time inference and no substitution for missing data.
    if value == 'Unknown' and not required:
        return None
    if not re.fullmatch(_EVIDENCE_TIME, value) or value == 'Unknown':
        raise ValueError('Invalid or missing Slurm evidence timestamp')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).isoformat()
    except ValueError as exc:
        raise ValueError('Invalid Slurm evidence calendar timestamp') from exc


def parse_evidence_config(text):
    """Extract the responding controller's identity, not the client version."""
    fields = {}
    for line in _evidence_text(text).splitlines():
        match = re.match(r'^\s*(ClusterName|SLURM_VERSION)\s*=(.*)$', line)
        if not match:
            continue
        key, value = match.groups()
        if key in fields:
            raise ValueError('Duplicate Slurm controller evidence field')
        fields[key] = value.strip()
    if set(fields) != {'ClusterName', 'SLURM_VERSION'}:
        raise ValueError('Missing Slurm controller identity/version')
    _evidence_cluster(fields['ClusterName'])
    if not re.fullmatch(_EVIDENCE_VERSION, fields['SLURM_VERSION']):
        raise ValueError('Invalid Slurm controller version')
    return dict(cluster=fields['ClusterName'], server_version=fields['SLURM_VERSION'])


def parse_evidence_version(text):
    """Parse a client --version response; this says nothing about slurmctld."""
    match = re.fullmatch(r'slurm (' + _EVIDENCE_VERSION + r')\n?', _evidence_text(text))
    if not match:
        raise ValueError('Invalid Slurm client version')
    return match[1]


def parse_evidence_job(text, *, job_id, cluster, name):
    """Parse one ordinary batch scontrol --details --oneliner observation.

    Cluster comes from the separately checked controller probe; scontrol's job
    text has no ordinary-job Cluster field. Missing jobs are errors, not absence.
    """
    _evidence_identity(job_id, cluster, name)
    text = _evidence_text(text)
    if not text.endswith('\n') or len(text.splitlines()) != 1:
        raise ValueError('Expected one complete scontrol evidence record')
    line = text[:-1]
    # Match the fixed prefix, not arbitrary key-looking text from job names,
    # commands, paths or comments. Its fields precede all of those free texts.
    token = r'[^\s=]+'
    prefix = (
        r'JobId=(?P<job_id>[1-9][0-9]*) JobName=(?P<name>' + token + r') '
        r'SLUID=(?P<sluid>' + _EVIDENCE_SLUID + r') '
        r'UserId=(?P<owner>[A-Za-z0-9_.-]+)\((?P<uid>[0-9]+)\) '
        r'GroupId=' + token + r' MCS_label=' + token + r' '
        r'Priority=[0-9]+ Nice=-?[0-9]+ Account=' + token + r' QOS=' + token + r' '
        r'(?:WCKey=' + token + r' )?'
        r'JobState=(?P<state>[A-Z_]+) Reason=' + token + r' '
        r'(?:FailedNode=' + token + r' )?Dependency=' + token + r' '
        r'Requeue=[0-9]+ Restarts=(?P<restarts>[0-9]+) BatchFlag=(?P<batch_flag>[0-9]+) Reboot=[0-9]+ '
        r'ExitCode=[0-9]+:[0-9]+ DerivedExitCode=[0-9]+:[0-9]+ '
        r'RunTime=' + token + r' TimeLimit=' + token + r' TimeMin=' + token + r' '
        r'SubmitTime=(?P<submit>' + _EVIDENCE_TIME + r') '
        r'EligibleTime=' + _EVIDENCE_TIME + r' AccrueTime=' + _EVIDENCE_TIME + r' '
        r'(?:ResizeTime=' + _EVIDENCE_TIME + r' )?'
        r'StartTime=(?P<start>' + _EVIDENCE_TIME + r') '
        r'EndTime=(?P<end>' + _EVIDENCE_TIME + r') Deadline=(?:' + _EVIDENCE_TIME + r'|N/A) '
    )
    # Formatting may pad adjacent fields; permit horizontal separators without
    # allowing a free-text value or a second output line to supply these keys.
    match = re.match(prefix.replace(' ', r'[ \t]+'), line)
    if not match or match['job_id'] != job_id or match['name'] != name:
        raise ValueError('Invalid scontrol evidence prefix or job/name identity')
    key_matches = list(re.finditer(r'(?:^|[ \t])([A-Za-z][A-Za-z0-9_:/]*)=', line))
    keys = [item[1] for item in key_matches]
    if any(key.startswith(('Array', 'HetJob', 'Fed')) for key in keys):
        raise ValueError('Array, heterogeneous or federated evidence is unsupported')
    # Requiring the later batch-output fields establishes that the record was
    # read past the federation section. Never recover missing prefix fields
    # from this suffix; a key in a path is ambiguous and must reject the record.
    required = ('JobId', 'JobName', 'SLUID', 'UserId', 'JobState', 'Restarts',
                'SubmitTime', 'StartTime', 'EndTime', 'Command', 'SubmitLine',
                'WorkDir', 'StdErr', 'StdIn', 'StdOut')
    if any(keys.count(key) != 1 for key in required):
        raise ValueError('Missing, duplicate or ambiguous scontrol evidence field')
    tail_keys = [key for key in keys if key in required[9:]]
    command_at = next(item.start() for item in key_matches if item[1] == 'Command')
    if tail_keys != list(required[9:]) or command_at < match.end():
        raise ValueError('Invalid scontrol evidence suffix')
    if match['state'] not in (ACTIVE | TERMINAL) - {'REQUEUE_FED', 'REVOKED'}:
        raise ValueError('Unknown scontrol evidence state')
    _evidence_uint(match['batch_flag'], 16, positive=True)
    return dict(cluster=cluster, job_id=job_id, name=name, owner=match['owner'],
                uid=_evidence_uint(match['uid'], 32), state=match['state'],
                submit=_evidence_time(match['submit'], required=True),
                start=_evidence_time(match['start']), end=_evidence_time(match['end']),
                restarts=_evidence_uint(match['restarts'], 16), sluid=_evidence_sluid(match['sluid']))


def parse_evidence_history(text, *, job_id, cluster, name):
    """Keep distinct sacct --duplicates instances; never infer missing history."""
    _evidence_identity(job_id, cluster, name)
    widths = (256, 64, 200, 20, 32, 32, 32, 32, 64, 20, 64, 64)
    rows, by_index, by_sluid = [], {}, {}
    for line in _evidence_text(text).splitlines():
        fields = [value.strip() for value in line.split('|')]
        if (len(fields) != len(widths) or any(not value or len(value) >= width
                for value, width in zip(fields, widths))):
            raise ValueError('Missing or truncated sacct evidence field')
        (actual_cluster, job, actual_name, uid, index, submitted, start, end,
         state_raw, restarts, sluid, original_sluid) = fields
        if (actual_cluster, job, actual_name) != (cluster, job_id, name):
            raise ValueError('sacct evidence cluster/job/name identity mismatch')
        state = 'CANCELLED' if re.fullmatch(r'CANCELLED by [0-9]+', state_raw) else state_raw
        if state not in (ACTIVE | TERMINAL) - {'REQUEUE_FED', 'REVOKED'}:
            raise ValueError('Unknown or truncated sacct evidence state')
        row = dict(cluster=cluster, job_id=job_id, name=name,
                   uid=_evidence_uint(uid, 32), db_index=_evidence_uint(index, 64, positive=True),
                   submit=_evidence_time(submitted, required=True), start=_evidence_time(start),
                   end=_evidence_time(end), state=state, state_raw=state_raw,
                   restarts=_evidence_uint(restarts, 16), sluid=_evidence_sluid(sluid),
                   # Older protocol records can carry zero for the original
                   # SLUID. print_fields_sluid prints that as s0000000000000;
                   # retain its absence rather than inventing a lineage root.
                   original_sluid=None if original_sluid == 's0000000000000' else _evidence_sluid(original_sluid),
                   original_sluid_raw=original_sluid)
        # In 26.05.5 sacct PRINT_DB_INX and PRINT_SLUID both print db_index,
        # respectively as decimal and Crockford base32 (src/sacct/print.c).
        if row['db_index'] != _evidence_sluid_number(row['sluid']):
            raise ValueError('sacct DBIndex/SLUID identity mismatch')
        for seen, key in ((by_index, row['db_index']), (by_sluid, row['sluid'])):
            if key in seen and seen[key] != row:
                raise ValueError('Conflicting duplicate sacct evidence instance')
        if row['db_index'] not in by_index:
            rows.append(row)
        by_index[row['db_index']] = by_sluid[row['sluid']] = row
    if not rows:
        raise ValueError('No sacct evidence history returned')
    return rows
