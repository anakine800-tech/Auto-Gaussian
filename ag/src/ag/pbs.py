"""PBS node parsing for monitoring displays."""
import re

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


def parse_nodes(text, jobs):
    records, current, key = [], None, None
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[:1].isspace():
            current, key = {'name': line.strip()}, None
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
    allocated = {}
    for job in jobs:
        if job.get('job_state') == 'C':
            continue
        for host in filter(None, job.get('exec_host', '').split('+')):
            name, sep, slot = host.partition('/')
            if not sep:
                raise ValueError('Unrecognized exec_host allocation')
            allocated[name] = allocated.get(name, 0) + slot_count(slot)
    nodes = []
    for record in records:
        cores = record.get('np', record.get('resources_available.ncpus', ''))
        if not cores.isdigit() or not record.get('state'):
            raise ValueError('Node lacks CPU capacity or state')
        used = allocated.get(record['name'], 0)
        if 'jobs' in record:
            used = 0
            slots = []
            for fragment in record['jobs'].split(','):
                slot, sep, job_id = fragment.strip().partition('/')
                slots.append(slot)
                if sep:
                    # Node slots can belong to array children; this is display
                    # parsing only and must not widen remote command arguments.
                    if not re.fullmatch(r'\d+\[\d+\](?:\.[A-Za-z0-9][A-Za-z0-9_.-]*)?', job_id):
                        validate_job_id(job_id)
                    used += slot_count(','.join(slots))
                    slots = []
            if slots:
                raise ValueError('Unrecognized node allocation')
        nodes.append(dict(name=record['name'], state=record['state'],
                          cores_total=int(cores), cores_used=used))
    return nodes
