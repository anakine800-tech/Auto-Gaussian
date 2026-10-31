"""T217B Slurm receipt recovery: one dispatch, strict existing identities."""
import json

import pytest

from ag import config, state, status, submit
from ag.transport import Result, TransportError
from test_core import cfg, allow
from test_slurm import multi, prepare, SlurmFake


class StartSlurmFake(SlurmFake):
    def __init__(self, cfg, manifest):
        super().__init__(cfg)
        self.start = {'job_id': '123', 'started_at': manifest['created_at']}
        self.accounting = Result()

    def run(self, command):
        if command.operation == 'receipt':
            self.calls.append(command)
            value = self.start if 'ag-start.json' in command.text else None
            return Result(stdout='absent\n' if value is None else json.dumps(value))
        return super().run(command)


@pytest.fixture
def lost_slurm(multi, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    path, manifest = prepare(multi, tmp_path)
    fake = StartSlurmFake(config.select_cluster(multi, 'batch'), manifest)
    fake.qsub = Result(255, stderr='Synthetic lost sbatch response')
    allow(monkeypatch)
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(multi, [path.name], fake)
    assert state.read(path)['state'] == 'unknown'
    assert fake.operations().count('submit') == 1
    assert not (path / 'submission.json').exists()
    return multi, path, manifest, fake


def no_second_dispatch(fake, first):
    assert fake.operations().count('submit') == 1
    assert not {'submit', 'upload', 'create_attempt', 'cancel'} & set(fake.operations()[first:])


@pytest.mark.parametrize('purged', [False, True])
def test_start_only_lost_reply_binds_once_and_later_finishes(lost_slurm, purged):
    cfg, path, manifest, fake = lost_slurm
    if purged:
        fake.exact = Result(1, stderr='squeue: error: Invalid job id specified\n')
    first = len(fake.calls)
    claim = (path / '.submit-claim').read_bytes()
    original_manifest = (path / 'manifest.json').read_bytes()
    original_summary = (path / 'submission-summary.json').read_bytes()

    result = status.check(cfg, path, fake)

    assert result['state'] == 'submitted'
    assert result['job_id'] == 'batch:123'
    assert result['start_reconciliation']['account_source'] == 'current-ssh-identity'
    binding = (path / 'submission.json').read_bytes()
    assert json.loads(binding)['authorization'] == json.loads(original_summary)['authorization']
    assert status.check(cfg, path, fake)['state'] == 'submitted'
    fake.accounting = Result(stdout=f"123|{manifest['attempt_id']}|fixture|COMPLETED|0:0|00:01:00|8\n")
    assert status.check(cfg, path, fake)['state'] == 'finished'
    assert (path / 'submission.json').read_bytes() == binding
    assert (path / '.submit-claim').read_bytes() == claim
    assert (path / 'manifest.json').read_bytes() == original_manifest
    assert (path / 'submission-summary.json').read_bytes() == original_summary
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake)
    no_second_dispatch(fake, first)


def test_no_name_match_and_no_start_stay_unknown(lost_slurm):
    cfg, path, _, fake = lost_slurm
    fake.start = None
    first = len(fake.calls)

    result = status.check(cfg, path, fake)

    assert result['state'] == 'unknown' and result['job_id'] is None
    assert not (path / 'submission.json').exists()
    no_second_dispatch(fake, first)


@pytest.mark.parametrize('job', ['0', '123_1', '123+1', '123.fixture', 'batch:123', '', 123])
def test_start_requires_exact_slurm_job_number(lost_slurm, job):
    cfg, path, _, fake = lost_slurm
    fake.start['job_id'] = job
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    no_second_dispatch(fake, first)


@pytest.mark.parametrize('field,value', [('job', '124'), ('name', 'different'),
                                       ('owner', 'other'), ('partition', 'other')])
def test_exact_queue_contradiction_refuses_before_binding(lost_slurm, field, value):
    cfg, path, manifest, fake = lost_slurm
    row = dict(job='123', name=manifest['attempt_id'], owner='fixture', partition='fixture')
    row[field] = value
    fake.exact = Result(stdout='{job}|{name}|{owner}|RUNNING|8|00:00|{partition}\n'.format(**row))
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    no_second_dispatch(fake, first)


@pytest.mark.parametrize('field,value', [('job', '124'), ('name', 'different'), ('owner', 'other')])
def test_exact_accounting_contradiction_refuses_before_binding(lost_slurm, field, value):
    cfg, path, manifest, fake = lost_slurm
    row = dict(job='123', name=manifest['attempt_id'], owner='fixture')
    row[field] = value
    fake.accounting = Result(stdout='{job}|{name}|{owner}|COMPLETED|0:0|00:01:00|8\n'.format(**row))
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    no_second_dispatch(fake, first)


@pytest.mark.parametrize('result', [Result(255, stderr='Invalid job id specified'),
                                  Result(1, stderr='squeue: controller unavailable'),
                                  Result(stdout='invalid queue output')])
def test_exact_queue_error_is_not_missing_job(lost_slurm, result):
    cfg, path, _, fake = lost_slurm
    fake.exact = result
    first = len(fake.calls)

    with pytest.raises((ValueError, TransportError)):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    no_second_dispatch(fake, first)
