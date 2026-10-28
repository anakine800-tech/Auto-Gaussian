"""PBS node parsing for monitoring displays."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ag.remote import job_id as validate_job_id


def slot_count(value):
    """Count comma-separated slots, rejecting overlapping slot identifiers."""
    intervals = []
    total = 0
    for part in value.split(','):
        if re.fullmatch(r'\d+', part):
            start = end = int(part)
            count = 1
        elif re.fullmatch(r'\d+-\d+', part):
            start, end = map(int, part.split('-'))
            if end < start:
                raise ValueError('Unrecognized scheduler CPU slot')
            count = end - start + 1
        elif re.fullmatch(r'\d+\*[1-9]\d*', part):
            start, count = map(int, part.split('*'))
            end = start  # Multiplicity applies to this slot, not a range.
        else:
            raise ValueError('Unrecognized scheduler CPU slot')
        intervals.append((start, end))
        total += count
    intervals.sort()
    if any(right[0] <= left[1] for left, right in zip(intervals, intervals[1:])):
        raise ValueError('Overlapping scheduler CPU slots')
    return total


def parse_nodes(text, jobs, *, notes=None):
    records, current, key = [], None, None
    record_names = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[:1].isspace():
            current, key = {'name': line.strip()}, None
            if current['name'] in record_names:
                raise ValueError('Ambiguous duplicate PBS node identity')
            record_names.add(current['name'])
            records.append(current)
        elif current is not None and ' = ' in line:
            key, value = line.strip().split(' = ', 1)
            if key in current:
                raise ValueError('Duplicate node attribute')
            current[key] = value
        elif current is not None and key:
            current[key] += line.strip()
        else:
            raise ValueError('Unrecognized pbsnodes output')
    allocated, node_jobs, job_nodes = {}, {}, {}
    exec_names = set()
    by_job = {job['job_id']: job for job in jobs if 'job_id' in job}
    for job in jobs:
        # Even completed rows can reveal a competing domain name; they still
        # contribute no CPU allocation or node job membership.
        exec_names.update(host.partition('/')[0] for host in
                          filter(None, job.get('exec_host', '').split('+')))
        if job.get('job_state') == 'C':
            continue
        for host in filter(None, job.get('exec_host', '').split('+')):
            name, sep, slot = host.partition('/')
            if not sep:
                raise ValueError('Unrecognized exec_host allocation')
            allocated[name] = allocated.get(name, 0) + slot_count(slot)
            node_jobs.setdefault(name, set()).add(job.get('job_id'))
            job_nodes.setdefault(job.get('job_id'), set()).add(name)
    # Only the Torque memory cross-node check may equate a short name and an
    # FQDN. Keep CPU allocations, job sets and targeting identities exact.
    name_groups = {}
    for name in record_names | exec_names:
        name_groups.setdefault(name.split('.', 1)[0], set()).add(name)
    memory_names, ambiguous_names = {}, set()
    for short, names in name_groups.items():
        if len(names & record_names) <= 1 and sum('.' in name for name in names) <= 1:
            memory_names.update((name, short) for name in names)
        else:
            ambiguous_names.update(names)
    nodes = []
    for record in records:
        cores = record.get('np', record.get('resources_available.ncpus', ''))
        if not cores.isdigit() or not record.get('state'):
            raise ValueError('Node lacks CPU capacity or state')
        used = allocated.get(record['name'], 0)
        job_ids = set(node_jobs.get(record['name'], ()))
        if 'jobs' in record:
            used = 0
            slots = []
            job_ids = set()
            for fragment in record['jobs'].split(','):
                slot, sep, job_id = fragment.strip().partition('/')
                slots.append(slot)
                if sep:
                    # Node slots can belong to array children; this is display
                    # parsing only and must not widen remote command arguments.
                    if not re.fullmatch(r'\d+\[\d+\](?:\.[A-Za-z0-9][A-Za-z0-9_.-]*)?', job_id):
                        validate_job_id(job_id)
                    job_ids.add(job_id)
                    used += slot_count(','.join(slots))
                    slots = []
            if slots:
                raise ValueError('Unrecognized node allocation')
        record['_job_ids'] = job_ids
        for job_id in job_ids:
            job_nodes.setdefault(job_id, set()).add(record['name'])
        record['_cores_used'] = used
        # Preserve display precedence, but do not advertise room when the
        # exact-name node/jobs/assigned-CPU observations disagree.
        cpu_consistent = (0 <= used <= int(cores)
                          and used == allocated.get(record['name'], 0)
                          and job_ids == set(node_jobs.get(record['name'], ())))
        for field, expected in (('resources_available.ncpus', int(cores)),
                                ('resources_assigned.ncpus', used)):
            if field in record:
                value = record[field]
                cpu_consistent &= value.isdigit() and int(value) == expected
        record['_capacity_cpu_consistent'] = cpu_consistent
    for record in records:
        status = dict(part.strip().split('=', 1) for part in record.get('status', '').split(',')
                      if '=' in part)
        total_raw = record.get('resources_available.mem', status.get('physmem'))
        total = memory_gb(total_raw)
        assigned = memory_gb(record.get('resources_assigned.mem'))
        total_bytes = memory_bytes(total_raw)
        assigned_bytes = memory_bytes(record.get('resources_assigned.mem'))
        # Only Torque's status fallback uses job requests. PBS Pro keeps its
        # explicit assigned-memory field, including unknown/missing values.
        if 'status' in record and 'resources_assigned.mem' not in record:
            values, byte_values, reasons = [], [], set()
            for job_id in record['_job_ids']:
                job = by_job.get(job_id)
                if job is None:
                    reasons.add('已分配内存未知：节点作业号无法与作业记录精确对应')
                elif len({memory_names.get(name, name) for name in job_nodes[job_id]}) > 1:
                    if job_nodes[job_id] & ambiguous_names:
                        reasons.add('已分配内存未知：节点短名与完整名称的对应有歧义')
                    else:
                        reasons.add('已分配内存未知：节点上有跨多个节点的作业')
                else:
                    value = memory_gb(job.get('Resource_List.mem'))
                    if value is None:
                        reasons.add('已分配内存未知：节点上有作业未申请内存或申请值无法解析')
                    else:
                        values.append(value)
                        byte_values.append(memory_bytes(job.get('Resource_List.mem')))
            assigned = None if reasons else round(sum(values), 1)
            assigned_bytes = (None if reasons or None in byte_values else sum(byte_values))
            if notes is not None:
                notes.extend(reason for reason in sorted(reasons) if reason not in notes)
        nodes.append(dict(name=record['name'], state=record['state'],
                          cores_total=int(record.get('np', record.get('resources_available.ncpus', ''))),
                          cores_used=record['_cores_used'], mem_total_gb=total,
                          mem_assigned_gb=assigned,
                          capacity_cpu_consistent=record['_capacity_cpu_consistent'],
                          mem_total_bytes=total_bytes, mem_assigned_bytes=assigned_bytes,
                          jobs=len(record['_job_ids']) if 'jobs' in record else None))
    return nodes


def memory_bytes(value):
    """Exact whole bytes for capacity; retain unknown/fractional bytes as None."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)', value.strip(), re.I)
    if match is None:
        return None
    with localcontext() as context:
        # Enough precision for the original decimal coefficient times 1024**4.
        context.prec = len(match[1]) + 16
        amount = Decimal(match[1]) * 1024 ** ('b', 'kb', 'mb', 'gb', 'tb').index(match[2].lower())
        if amount < Decimal('1e100') * 1024**3 and amount == amount.to_integral_value():
            return int(amount)
    return None


def memory_gb(value):
    """Scheduler memory uses binary units; unknown units are not zero."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)', value.strip(), re.I)
    if match is None:
        return None
    try:
        amount = Decimal(match[1]) * Decimal(1024) ** (('b', 'kb', 'mb', 'gb', 'tb').index(match[2].lower()) - 3)
        return float(round(amount, 1)) if amount.is_finite() and amount < Decimal('1e100') else None
    except InvalidOperation:
        return None


def duration_seconds(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(?:(\d+)-)?(\d+):([0-5]\d):([0-5]\d)', value)
    if not match:
        return None
    days, hours, minutes, seconds = (int(v or 0) for v in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def timestamp(value, tz=None):
    """Return UTC text only when the scheduler timestamp is unambiguous."""
    return _timestamp(value, tz)[0]


def _timestamp(value, tz=None):
    """Never apply the local machine timezone to an unzoned scheduler date.

    PBS text dates require a configured scheduler timezone. Reject ambiguous or
    nonexistent local times rather than choosing a DST fold or shifting a gap.
    """
    if not isinstance(value, str):
        return None, None
    try:
        source = 'absolute'
        if re.fullmatch(r'\d{1,12}', value):
            stamp = datetime.fromtimestamp(int(value), timezone.utc)
        elif tz is not None and (match := re.fullmatch(
                r'([A-Za-z]{3}) ([A-Za-z]{3}) +([0-9]{1,2}) '
                r'([0-9]{2}):([0-9]{2}):([0-9]{2}) ([0-9]{4})', value)):
            # Fixed English tables: strptime's %a/%b depend on process locale.
            weekdays = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
            months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
            weekday, month, day, hour, minute, second, year = match.groups()
            local = datetime(int(year), months.index(month) + 1, int(day),
                             int(hour), int(minute), int(second))
            if local.weekday() != weekdays.index(weekday):
                return None, None
            zone = ZoneInfo(tz) if isinstance(tz, str) else tz
            candidates = set()
            for fold in (0, 1):
                utc = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                if utc.astimezone(zone).replace(tzinfo=None) == local:
                    candidates.add(utc)
            if len(candidates) != 1:
                return None, None
            stamp = candidates.pop()
            source = 'configured_timezone'
        else:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                return None, None
        return stamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), source
    except (ValueError, OverflowError, OSError, ZoneInfoNotFoundError):
        return None, None


def job_fields(job, sampled_at, tz=None, *, time_sources=None):
    """Display facts; optional time_sources stays internal to this observation."""
    running = job['job_state'] in ('R', 'E')
    cores = None
    if running:
        hosts = job.get('exec_host', '').split('+')
        if all('/' in host for host in hosts):
            cores = sum(slot_count(host.split('/', 1)[1]) for host in hosts)
    elif job.get('Resource_List.nodes'):
        # Same node/ppn arithmetic as status.occupied; other users' arrays must
        # not change that function's stricter admission policy for our account.
        cores = 0
        for chunk in job['Resource_List.nodes'].split('+'):
            fields = chunk.split(':')
            count = int(fields[0]) if fields[0].isdigit() else 1
            ppn = [field[4:] for field in fields[1:] if field.startswith('ppn=')]
            if len(ppn) != 1 or not ppn[0].isdigit() or int(ppn[0]) < 1 or count < 1:
                raise ValueError('Unrecognized ppn resource request; cannot count cores')
            cores += count * int(ppn[0])
    start, start_source = next((value for key in ('start_time_epoch', 'start_time', 'stime')
                               if (value := _timestamp(job.get(key), tz))[0] is not None),
                              (None, None))
    queued, queue_source = _timestamp(job.get('qtime'), tz)
    if time_sources is not None:
        time_sources.update(start_time=start_source, qtime=queue_source)
    elapsed, source = None, None
    if start is not None:
        seconds = int((sampled_at - datetime.fromisoformat(start)).total_seconds())
        if seconds >= 0:
            elapsed, source = seconds, 'start_time'
    if elapsed is None:
        elapsed = duration_seconds(job.get('resources_used.walltime'))
        if elapsed is not None:
            source = 'walltime_used'
    return dict(cores=cores, cores_kind='allocated' if running else 'requested',
                mem_gb=memory_gb(job.get('Resource_List.mem')), start_time=start,
                qtime=queued, elapsed_seconds=elapsed, elapsed_source=source,
                walltime_limit_seconds=duration_seconds(job.get('Resource_List.walltime')))
