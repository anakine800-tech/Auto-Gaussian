"""T27 slot syntax uses only fictional nodes and scheduler job IDs."""
import pytest

from ag.pbs import parse_nodes, slot_count


INVALID_SLOTS = [
    '', ',', ',0', '0,', '0,,2', '7-0', '0-7,25-12', 'x', '0,x',
    '-1', '1.5', '1-', '1-2-3', '0*0', '0*-2', '0*x', '0*2*3',
    '0,0', '0-7,7-12', '0-7,2', '2,0-7', '12-25,0-13',
    '0*2,0', '0,0*2', '0-7,3*2', '3*2,0-7', '0*2,0*3',
]


def node(name='n1', jobs=None):
    text = f'{name}\n    state = free\n    np = 44\n'
    return text if jobs is None else text + f'    jobs = {jobs}\n'


@pytest.mark.parametrize('slots,count', [
    ('0', 1), ('7-7', 1), ('0-7', 8), ('0*4', 4),
    ('0-7,12-25', 22), ('0,2,4-7,12*3', 9), ('12-25,0-7', 22),
    ('0-7,8-12', 13), ('0*4,1', 5),
])
def test_slot_count(slots, count):
    assert slot_count(slots) == count


@pytest.mark.parametrize('slots', INVALID_SLOTS)
def test_invalid_slots_rejected_in_both_scheduler_fields(slots):
    with pytest.raises(ValueError):
        slot_count(slots)
    with pytest.raises(ValueError):
        parse_nodes(node(), [{'job_state': 'R', 'exec_host': f'n1/{slots}'}])
    with pytest.raises(ValueError):
        parse_nodes(node(jobs=f'{slots}/101.srv'), [])


@pytest.mark.parametrize('host,counts', [
    ('n1/0-7,12-25', [22, 0]),
    ('n1/0-7,12-25+n2/0-3', [22, 4]),
])
def test_exec_host_combined_ranges(host, counts):
    nodes = parse_nodes(node() + node('n2'), [{'job_state': 'R', 'exec_host': host}])
    assert [n['cores_used'] for n in nodes] == counts


@pytest.mark.parametrize('assignments,count', [
    ('0-7,12-25/101.srv,26/102.srv', 23),
    ('0-7,12-25/101.srv,26,28-31/102.srv', 27),
    ('0-7,\n        12-25/101.srv, 26/102.srv', 23),
    ('0,2*3,4-7/101.srv', 8),
    ('0/101.srv,1/101.srv', 2),
])
def test_jobs_assignment_boundaries(assignments, count):
    # The node jobs field remains authoritative over exec_host.
    nodes = parse_nodes(node(jobs=assignments), [{'exec_host': 'n1/0*40'}])
    assert nodes[0]['cores_used'] == count


@pytest.mark.parametrize('assignments', [
    '', ',', ',0/101.srv', '0/101.srv,', '0/101.srv,,1/102.srv',
    '0-7,12-25', '0/101.srv,26', '0-7,12-25/',
    '0/101.srv/102.srv', '0/invalid', '0/101.srv,26/102.srv,27',
])
def test_malformed_jobs_rejected(assignments):
    with pytest.raises(ValueError):
        parse_nodes(node(jobs=assignments), [])
