"""Shared PBS node parsing for monitoring and submission capacity checks."""
import re


def slot_count(value):
    if re.fullmatch(r'\d+', value):
        return 1
    if re.fullmatch(r'\d+-\d+', value):
        start, end = map(int, value.split('-'))
        if end >= start:
            return end - start + 1
    if re.fullmatch(r'\d+\*[1-9]\d*', value):
        return int(value.split('*')[1])
    raise ValueError('Unrecognized scheduler CPU slot')


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
            for assignment in filter(None, (s.strip() for s in record['jobs'].split(','))):
                slot, sep, job_id = assignment.partition('/')
                if not sep or not job_id:
                    raise ValueError('Unrecognized node allocation')
                used += slot_count(slot)
        nodes.append(dict(name=record['name'], state=record['state'],
                          cores_total=int(cores), cores_used=used))
    return nodes
