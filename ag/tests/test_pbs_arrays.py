"""T77 Torque records; no live connections or real identifiers.

Initial read-only observation found no arrays. A later owner-submitted minimal
array exposed a running parent in qstat -f; LIVE_PARENT_SHAPE retains only its
relevant fields with fictional identifiers. Children and array_state_count
remain synthetic. Parent/child syntax follows
https://docs.adaptivecomputing.com/torque/4-2-7/Content/topics/2-jobs/multiJobSubmission.htm
"""
import time

import pytest

from ag import confirm, doctor, fetch, monitor, pbs, remote, state, status, submission, submit
from ag.transport import Result
from test_core import Fake, cfg, job_text, prepared
from test_monitor import Fake as MonitorFake, job
from test_pbs import node
from test_queue import QueueFake


ARRAY_IDS = ['9100[]', '9100[].fixture', '9100[0]', '9100[5].fixture',
             '9100[12].fixture-1.example']
ARRAY_ERROR = ('本人有 PBS 数组作业，无法可靠统计已占用核数，拒绝提交；'
               '已完成但仍保留在 qstat 中的本人数组记录也会导致拒绝，请等记录消失后再提交')


# Sanitized field subset from the manual 2026-10-16 sleep-array observation.
# The live parent had job_array_request but no array_state_count attribute.
LIVE_PARENT_SHAPE = '''Job Id: 9100[].fixture
    Job_Name = array-fixture
    Job_Owner = fixture@fixture
    job_state = R
    Resource_List.nodes = 1:ppn=1
    job_array_request = 1-2
'''


def test_observed_parent_shape_refuses_own_and_ignores_other_array(cfg):
    parsed = status.parse_jobs(LIVE_PARENT_SHAPE)
    assert parsed[0]['array'] is True
    assert parsed[0]['job_array_request'] == '1-2'
    assert 'array_state_count' not in parsed[0]
    fake = Fake(cfg)
    fake.qstat = Result(stdout=LIVE_PARENT_SHAPE)
    with pytest.raises(ValueError, match=ARRAY_ERROR):
        doctor.doctor(cfg, fake)
    fake.qstat = Result(stdout=job_text() + LIVE_PARENT_SHAPE.replace('fixture@fixture', 'other@fixture'))
    assert doctor.doctor(cfg, fake)['occupied_cores'] == 8


def array_job(job_id='9100[].fixture', owner='other', state_='Q', name='array-fixture'):
    return (f'Job Id: {job_id}\n    Job_Name = {name}\n'
            f'    Job_Owner = {owner}@fixture\n    job_state = {state_}\n'
            '    Resource_List.nodes = 1:ppn=1\n'
            '    job_array_request = 1-2\n'
            '    array_state_count = Queued:2 Running:0\n'
            '        Complete:0\n')


@pytest.mark.parametrize('job_id', ARRAY_IDS)
def test_array_observations_preserve_id_fields_and_mark(job_id):
    parsed = status.parse_jobs(array_job(job_id))
    assert parsed == [{'job_id': job_id, 'array': True, 'Job_Name': 'array-fixture',
                       'Job_Owner': 'other@fixture', 'job_state': 'Q',
                       'Resource_List.nodes': '1:ppn=1', 'job_array_request': '1-2',
                       'array_state_count': 'Queued:2 Running:0Complete:0'}]
    ordinary = status.parse_jobs(job_text())[0]
    assert 'array' not in ordinary


@pytest.mark.parametrize('job_id', ARRAY_IDS)
@pytest.mark.parametrize('state_', ['R', 'E', 'Q', 'H', 'W', 'T', 'S', 'C'])
def test_other_arrays_do_not_change_ordinary_accounting(job_id, state_):
    ordinary = job_text(cores=22, state_=state_)
    before = status.parse_jobs(ordinary)
    # Neither a missing nor an unusable array resource request is estimated.
    other = array_job(job_id, state_=state_).replace('    Resource_List.nodes = 1:ppn=1\n', '')
    jobs = status.parse_jobs(other + ordinary)
    assert status.occupied(jobs, 'fixture') == status.occupied(before, 'fixture')
    assert status.core_breakdown(jobs, 'fixture') == status.core_breakdown(before, 'fixture')
    assert status.occupied(jobs, 'fixture') == (0 if state_ == 'C' else 22)


@pytest.mark.parametrize('job_id', ARRAY_IDS)
@pytest.mark.parametrize('state_', ['R', 'E', 'Q', 'H', 'W', 'T', 'S', 'C'])
def test_own_array_always_refuses_accounting(job_id, state_):
    jobs = status.parse_jobs(job_text() + array_job(job_id, owner='fixture', state_=state_))
    for counter in (status.occupied, status.core_breakdown):
        with pytest.raises(ValueError, match=ARRAY_ERROR):
            counter(jobs, 'fixture')


@pytest.mark.parametrize('job_id', ['garbage', '9100[a]', '9100[-1]', '9100[1-2]',
    '9100[1,2]', '9100[1%2]', '9100[1][2]', '9100[1', '9100]1[',
    '9100[].', '9100[].-bad', '9100[].fixture;id', '9100[1].fixture/extra', '9100 [1]'])
def test_unrecognized_ids_still_fail_even_for_other_users(job_id):
    with pytest.raises(ValueError, match='Invalid exact PBS job ID'):
        status.parse_jobs(array_job(job_id))


@pytest.mark.parametrize('field', ['Job_Owner', 'job_state'])
def test_array_missing_owner_or_state_is_not_silently_skipped(field):
    text = '\n'.join(line for line in array_job().splitlines() if not line.strip().startswith(field))
    with pytest.raises(ValueError, match='lacks owner/state'):
        status.occupied(status.parse_jobs(text), 'fixture')


@pytest.mark.parametrize('job_id', ARRAY_IDS)
def test_remote_exact_command_arguments_still_reject_arrays(cfg, job_id):
    with pytest.raises(ValueError, match='Invalid exact PBS job ID'):
        remote.job_id(job_id)
    with pytest.raises(ValueError, match='Invalid exact PBS job ID'):
        remote.jobs(job_id)
    with pytest.raises(ValueError, match='Invalid exact PBS job ID'):
        remote.cancel(job_id)


@pytest.mark.parametrize('job_id', ARRAY_IDS)
def test_other_arrays_allow_inventory_doctor_and_fake_submit(cfg, prepared, monkeypatch, job_id):
    fake = QueueFake(cfg, occupied=8)
    fake.qstat = Result(stdout=job_text() + array_job(job_id))
    assert status.inventory(fake, cfg)[2] == 8
    assert doctor.doctor(cfg, fake)['occupied_cores'] == 8
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    assert submit.submit(cfg, [prepared[0].name], fake)[0]['state'] == 'submitted'
    assert fake.submitted_count == 1
    assert all('[' not in command.text for command in fake.calls if command.operation in ('jobs', 'submit'))


@pytest.mark.parametrize('after_confirmation', [False, True])
@pytest.mark.parametrize('job_id', ['9100[].fixture', '9100[1].fixture'])
def test_own_array_blocks_fake_submit_without_remote_writes(cfg, prepared, monkeypatch,
                                                          after_confirmation, job_id):
    path, _ = prepared
    fake = QueueFake(cfg, occupied=0)
    own = array_job(job_id, owner='fixture')
    if after_confirmation:
        fake.job_snapshots = ['', own]
        monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    else:
        fake.qstat = Result(stdout=own)
        monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('must reject before confirmation'))
    with pytest.raises(ValueError, match=ARRAY_ERROR):
        submit.submit(cfg, [path.name], fake)
    assert set(fake.operations()) == {'identity', 'jobs'}
    assert fake.submitted_count == 0
    assert (path / '.submit-claim').exists() == after_confirmation
    assert state.read(path)['state'] == ('failed_presubmit' if after_confirmation else 'prepared')


def test_own_array_blocks_doctor(cfg):
    fake = Fake(cfg)
    fake.qstat = Result(stdout=array_job(owner='fixture'))
    with pytest.raises(ValueError, match=ARRAY_ERROR):
        doctor.doctor(cfg, fake)
    assert fake.operations() == ['identity', 'jobs']


@pytest.mark.parametrize('owner', ['other', 'fixture'])
def test_monitor_sample_with_arrays(cfg, monkeypatch, owner):
    monkeypatch.setattr(monitor, 'ssh_identity', lambda cfg: ('fixture', 22, 'fixture'))
    raw = job() + array_job(owner=owner) + array_job('9100[1].fixture', owner=owner, state_='R')
    fake = MonitorFake(jobs=raw, nodes=node(jobs='0/101.fixture,1/9100[1].fixture'))
    result = monitor.sample(cfg, fake)
    if owner == 'other':
        assert result['ok'] is True
        assert result['own']['cores_in_use'] == 8
        assert [row['job_id'] for row in result['own']['jobs']] == ['101.fixture']
        assert result['own']['jobs'][0]['attempt'] is None
        assert result['cluster']['cores_used'] == 2
    else:
        assert result['ok'] is False
        assert ARRAY_ERROR in result['error']
        assert result['own']['jobs'] == []
        assert fake.calls == ['qstat -f']


@pytest.mark.parametrize('owner', ['fixture', 'other'])
@pytest.mark.parametrize('state_', ['R', 'C'])
def test_unknown_reconciliation_never_binds_array(cfg, prepared, owner, state_):
    path, manifest = prepared
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    fake = Fake(cfg)
    fake.qstat = Result(stdout=array_job(owner=owner, state_=state_, name=manifest['pbs_job_name']))
    if owner == 'fixture':
        with pytest.raises(ValueError, match=ARRAY_ERROR):
            status.check(cfg, path, fake)
    else:
        assert status.check(cfg, path, fake)['state'] == 'unknown'
    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert set(fake.operations()) <= {'identity', 'jobs', 'listing', 'receipt'}


def test_unknown_reconciliation_still_finds_ordinary_job_among_other_arrays(cfg, prepared):
    path, manifest = prepared
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    fake = Fake(cfg)
    fake.qstat = Result(stdout=job_text(manifest) + array_job(name=manifest['pbs_job_name']))
    result = status.check(cfg, path, fake)
    assert result['state'] == 'submitted'
    assert result['job_id'] == 'default:123.fixture'


@pytest.mark.parametrize('job_id', ['123[].fixture', '123[1].fixture'])
def test_exact_status_and_incomplete_fetch_reject_array_reply(cfg, prepared, job_id):
    path, manifest = prepared
    state.write(path, 'submitting')
    submission.record(path, manifest, '123.fixture')
    state.write(path, 'submitted', job_id='default:123.fixture')
    fake = Fake(cfg)
    fake.job = Result(stdout=array_job(job_id, owner='fixture', state_='C', name=manifest['pbs_job_name']))
    with pytest.raises(ValueError, match='Scheduler identity mismatch'):
        status.check(cfg, path, fake)
    current = state.read(path)
    now = time.time()
    current['incomplete_observations'] = [
        dict(at=now - age, job_id='123.fixture', scheduler_state='C', outputs={}, exit_receipt=None)
        for age in (400, 50)]
    with pytest.raises(ValueError, match='PBS job active or identity unverified'):
        fetch._end_evidence(cfg, path, manifest, current, fake)
    assert all(command.text == 'qstat -f 123.fixture' for command in fake.calls if command.operation == 'jobs')
    assert set(fake.operations()) <= {'jobs', 'receipt'}


@pytest.mark.parametrize('assignments,expected', [
    ('0/9100[1],1/9100[2]', 2),
    ('0-7,12-25/9100[5].fixture,26/123.fixture', 23),
    ('0-7,\n        12-25/9100[5].fixture,26/123.fixture', 23),
    ('0,2*3,4-7/9100[5].fixture', 8),
])
def test_node_array_children_count_slots_not_array_size(assignments, expected):
    assert pbs.parse_nodes(node(jobs=assignments), [])[0]['cores_used'] == expected


@pytest.mark.parametrize('job_id', ['9100[]', '9100[].fixture', '9100[bad]',
                                  '9100[1-2]', '9100[1].', '9100[1].fixture;id'])
def test_node_arrays_do_not_relax_unknown_or_parent_allocations(job_id):
    with pytest.raises(ValueError, match='Invalid exact PBS job ID'):
        pbs.parse_nodes(node(jobs=f'0/{job_id}'), [])
