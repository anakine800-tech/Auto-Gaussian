"""T217B: real local submission/recovery with synthetic PBS transport only."""
from copy import deepcopy
from contextlib import contextmanager
import json
import os

import pytest

from ag import autonomy, config, confirm, remote, state, status, submission, submit
from ag.transport import Result, TransportError
from test_approval import autonomous_driver_factory, policy, record
from test_core import cfg, prepared, Fake, job_text


class StartFake(Fake):
    def __init__(self, cfg, manifest):
        super().__init__(cfg)
        self.start = dict(PBS_JOBID='123.fixture', started_at=manifest['created_at'])
        self.end = None
        self.after_start = None

    def run(self, command):
        if command.operation == 'receipt':
            self.calls.append(command)
            value = self.start if 'ag-start.json' in command.text else self.end
            if 'ag-start.json' in command.text and self.after_start is not None:
                callback, self.after_start = self.after_start, None
                callback()
            return Result(stdout='absent\n' if value is None else json.dumps(value))
        return super().run(command)


@pytest.fixture
def lost_manual(cfg, prepared, monkeypatch):
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    monkeypatch.setattr(confirm, 'confirm', lambda *args: pytest.fail('Unexpected dialog'))
    path, manifest = prepared

    def dispatch(mode='approval'):
        if mode == 'approval':
            options = dict(approval_id=record(cfg, path)['id'])
        elif mode == 'policy':
            policy(cfg)
            options = dict(policy_name='validation')
        else:
            monkeypatch.setattr(confirm, 'confirm', lambda *args: True)
            options = {}
        fake = StartFake(cfg, manifest)
        fake.qsub = Result(255, '', 'Synthetic lost qsub response')
        with pytest.raises(submit.UnknownSubmission):
            submit.submit(cfg, [path.name], fake, **options)
        assert state.read(path)['state'] == 'unknown'
        assert fake.operations().count('submit') == 1
        assert not (path / 'submission.json').exists()
        return cfg, path, manifest, fake

    return dispatch


def frozen(path):
    members = [path / 'manifest.json', path / '.submit-claim',
               path / 'submission-summary.json', *(path / 'inputs').iterdir()]
    return {member: member.read_bytes() for member in members}


def assert_read_only_since(fake, first):
    assert not {'submit', 'create_attempt', 'upload', 'cancel'} & set(fake.operations()[first:])
    assert fake.operations().count('submit') == 1


def assert_frozen_metadata_since(fake, first, cfg, manifest):
    observed = [command for command in fake.calls[first:] if command.operation == 'metadata']
    expected = {remote.metadata(cfg, manifest, item['name']) for item in manifest['inputs']}
    assert len(observed) == len(expected) and set(observed) == expected


@pytest.mark.parametrize('mode', ['approval', 'policy', 'dialog'])
@pytest.mark.parametrize('finished', [False, True])
def test_manual_lost_reply_binds_start_once_and_continues_status(lost_manual, mode, finished):
    cfg, path, manifest, fake = lost_manual(mode)
    if finished:
        fake.end = dict(PBS_JOBID='123.fixture', returncode=0, finished_at=manifest['created_at'])
    original = frozen(path)
    authorization = json.loads((path / 'submission-summary.json').read_text())['authorization']
    first = len(fake.calls)

    result = status.check(cfg, path, fake)

    assert result['state'] == ('finished' if finished else 'awaiting_second_observation')
    assert result['job_id'] == 'default:123.fixture'
    assert result['start_reconciliation']['source'] == 'frozen-submission+ag-start.json'
    assert result['start_reconciliation']['remote_input_verification'] == 'size+sha256'
    assert_frozen_metadata_since(fake, first, cfg, manifest)
    binding = (path / 'submission.json').read_bytes()
    assert json.loads(binding)['authorization'] == authorization
    assert set(fake.files) == {member['name'] for member in manifest['inputs']}
    assert frozen(path) == original
    assert_read_only_since(fake, first)
    again = status.check(cfg, path, fake)
    assert again['job_id'] == result['job_id']
    assert (path / 'submission.json').read_bytes() == binding
    assert frozen(path) == original
    assert_read_only_since(fake, first)


def test_manual_empty_queue_and_no_start_remain_unknown_without_retry(lost_manual):
    cfg, path, _, fake = lost_manual()
    fake.start = None
    original = frozen(path)
    first = len(fake.calls)

    result = status.check(cfg, path, fake)

    assert result['state'] == 'unknown' and result['job_id'] is None
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake)
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('damage', ['no-claim', 'bad-claim', 'bad-summary', 'authorization',
                                  'local-script', 'conflicting-binding'])
def test_start_recovery_refuses_broken_original_submission(lost_manual, damage):
    cfg, path, manifest, fake = lost_manual()
    if damage == 'no-claim':
        (path / '.submit-claim').unlink()
    elif damage == 'bad-claim':
        (path / '.submit-claim').write_text('Incomplete synthetic claim')
    elif damage in ('bad-summary', 'authorization'):
        target = path / 'submission-summary.json'
        summary = json.loads(target.read_text())
        if damage == 'bad-summary':
            summary['manifest_sha256'] = '0' * 64
        else:
            summary['authorization']['quote'] = 'Changed synthetic authorization'
        target.write_text(json.dumps(summary))
    elif damage == 'local-script':
        script = path / 'inputs/job.pbs'
        script.write_bytes(script.read_bytes() + b'\nChanged local script\n')
    else:
        submission.record(path, manifest, '999.fixture')
    binding = (path / 'submission.json').read_bytes() if (path / 'submission.json').exists() else None
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    if binding is None:
        assert not (path / 'submission.json').exists()
    else:
        assert (path / 'submission.json').read_bytes() == binding
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('job', ['', '123_1', '123[1].fixture', 'batch:123', '../123',
                                 '123.fixture\n', 123, True, None])
def test_start_recovery_requires_exact_pbs_job_id(lost_manual, job):
    cfg, path, _, fake = lost_manual()
    fake.start['PBS_JOBID'] = job
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('mixed', [False, True])
def test_pbs_recovery_refuses_slurm_or_mixed_receipt_dialect(lost_manual, mixed):
    cfg, path, _, fake = lost_manual()
    fake.start['job_id'] = '123'
    if not mixed:
        fake.start.pop('PBS_JOBID')
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('loss', ['expired-run', 'takeover'])
def test_autonomous_start_recovery_refuses_lost_publication_owner(autonomous_driver_factory, loss):
    cfg, path, manifest, context, clock, _ = autonomous_driver_factory('start-recovery-owner')
    fake = StartFake(cfg, manifest)
    fake.qsub = Result(255, '', 'Synthetic lost qsub response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    original = frozen(path)
    consumed = deepcopy(autonomy.status(cfg, 'smoke')['state']['submissions'])
    first = len(fake.calls)

    def lose_owner():
        # The real store read also verifies no publication mutex is held during IO.
        current = autonomy.status(cfg, 'smoke')['state']
        clock[0] += 3600 if loss == 'expired-run' else 5400
        if loss == 'takeover':
            autonomy.start(cfg, 'smoke', current['current_plan'], 'Synthetic replacement observer',
                           takeover_reason='Synthetic expired lease', observe_only=True)

    fake.after_start = lose_owner

    def publication():
        return autonomy.observation_publication_guard(cfg, 'smoke', context['run_id'], context['token'],
            action='observe', plan_sha256=context['plan_sha256'])

    with pytest.raises(autonomy.PublicationRefused):
        status.check(cfg, path, fake, publication=publication)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert autonomy.status(cfg, 'smoke')['state']['submissions'] == consumed
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('member', ['.submit-claim', 'manifest.json', 'inputs/water.gjf',
                                  'inputs/job.pbs', 'submission-summary.json',
                                  'submission.json', 'journal.jsonl'])
def test_start_recovery_rechecks_sources_inside_manual_publication(lost_manual, member):
    cfg, path, _, fake = lost_manual()
    original = frozen(path)
    before_status = (path / 'status.json').read_bytes()
    journal = path.parent.parent / 'journal.jsonl'
    before_journal = journal.read_bytes()
    changed = []
    first = len(fake.calls)

    @contextmanager
    def publication():
        with autonomy.manual_publication_guard(cfg, path.parent.parent.name) as current:
            target = journal if member == 'journal.jsonl' else path / member
            if member == 'submission.json':
                # Simulate a different local writer appearing after the absence pin.
                target.write_bytes(b'{"synthetic_racing_binding":true}\n')
            else:
                previous = target.stat()
                target.write_bytes(target.read_bytes())
                os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            changed.append(target.read_bytes())
            yield current

    with pytest.raises(ValueError):
        status.check(cfg, path, fake, publication=publication)

    assert len(changed) == 1
    assert (path / 'status.json').read_bytes() == before_status
    assert journal.read_bytes() == before_journal
    assert frozen(path) == original
    if member == 'submission.json':
        assert (path / member).read_bytes() == changed[0]
    else:
        assert not (path / 'submission.json').exists()
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('change', ['absent', 'other-id', 'other-time'])
def test_start_recovery_refuses_receipt_changed_before_final_read(lost_manual, change):
    cfg, path, _, fake = lost_manual()
    original = frozen(path)
    first = len(fake.calls)

    def replace_receipt():
        if change == 'absent':
            fake.start = None
        elif change == 'other-id':
            fake.start = dict(fake.start, PBS_JOBID='999.fixture')
        else:
            fake.start = dict(fake.start, started_at='2026-01-01T00:00:00Z')

    fake.after_start = replace_receipt
    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert fake.operations()[first:].count('receipt') == 2
    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('change', ['current-user', 'configured-queue'])
def test_start_recovery_refuses_changed_entry_configuration(lost_manual, monkeypatch, change):
    cfg, path, _, fake = lost_manual()
    if change == 'current-user':
        monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'other-fixture'))
    else:
        cfg['scheduler']['queue'] = 'other-fixture'
    original = frozen(path)
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('field', ['name', 'owner', 'id', 'queue'])
def test_start_cannot_override_contradictory_exact_qstat(lost_manual, field):
    cfg, path, manifest, fake = lost_manual()
    text = job_text(manifest) + '    queue = batch\n'
    before, after = {
        'name': (manifest['pbs_job_name'], 'unrelated-name'),
        'owner': ('fixture@fixture', 'other-fixture@fixture'),
        'id': ('123.fixture', '999.fixture'),
        'queue': ('queue = batch', 'queue = other-fixture'),
    }[field]
    fake.job = Result(stdout=text.replace(before, after))
    original = frozen(path)
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('raw', [
    '{"PBS_JOBID":"123.fixture","PBS_JOBID":"123.fixture","started_at":"2026-01-01T00:00:00Z"}',
    '{"PBS_JOBID":NaN,"started_at":"2026-01-01T00:00:00Z"}',
    '{"PBS_JOBID":"123.fixture","started_at":NaN}',
    '[]',
    '{"PBS_JOBID":"123.fixture","started_at":"2026-01-01\ufffd00:00:00Z"}',
    '{"PBS_JOBID":"\uff11\uff12\uff13.fixture","started_at":"2026-01-01T00:00:00Z"}',
    '{"PBS_JOBID":"\\ud800","started_at":"2026-01-01T00:00:00Z"}',
])
def test_start_recovery_refuses_ambiguous_or_invalid_receipt_bytes(lost_manual, raw):
    cfg, path, _, fake = lost_manual()
    run = fake.run
    original = frozen(path)
    first = len(fake.calls)

    def malformed_receipt(command):
        if command.operation == 'receipt':
            fake.calls.append(command)
            return Result(stdout=raw)
        return run(command)

    fake.run = malformed_receipt
    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('finished', [False, True])
def test_autonomous_start_recovery_preserves_actual_consumption(autonomous_driver_factory, finished):
    cfg, path, manifest, context, _, _ = autonomous_driver_factory('start-recovery-success')
    fake = StartFake(cfg, manifest)
    fake.qsub = Result(255, '', 'Synthetic lost qsub response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    if finished:
        fake.end = dict(PBS_JOBID='123.fixture', returncode=0, finished_at=manifest['created_at'])
    original = frozen(path)
    before = autonomy.status(cfg, 'smoke')['state']
    consumed = deepcopy(before['submissions'])
    assert len(consumed) == 1 and before['phase'] == 'paused'
    authorization = json.loads((path / 'submission-summary.json').read_text())['authorization']
    first = len(fake.calls)

    def publication():
        return autonomy.observation_publication_guard(cfg, 'smoke', context['run_id'], context['token'],
            action='observe', plan_sha256=context['plan_sha256'])

    result = status.check(cfg, path, fake, publication=publication)

    assert result['state'] == ('finished' if finished else 'awaiting_second_observation')
    assert result['job_id'] == 'default:123.fixture'
    assert result['start_reconciliation']['source'] == 'frozen-submission+ag-start.json'
    assert result['start_reconciliation']['account_source'] == 'immutable-reservation'
    assert result['start_reconciliation']['remote_input_verification'] == 'size+sha256'
    assert_frozen_metadata_since(fake, first, cfg, manifest)
    assert json.loads((path / 'submission.json').read_text())['authorization'] == authorization
    after = autonomy.status(cfg, 'smoke')['state']
    assert after['submissions'] == consumed and after['phase'] == before['phase']
    assert frozen(path) == original
    assert_read_only_since(fake, first)


def test_autonomous_start_recovery_requires_original_reserved_account(autonomous_driver_factory, monkeypatch):
    cfg, path, manifest, context, _, _ = autonomous_driver_factory('start-recovery-account')
    fake = StartFake(cfg, manifest)
    fake.qsub = Result(255, '', 'Synthetic lost qsub response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    # Same remote username is insufficient when the original account host changed.
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('other-fixture', 22, 'fixture'))
    original = frozen(path)
    first = len(fake.calls)

    def publication():
        return autonomy.observation_publication_guard(cfg, 'smoke', context['run_id'], context['token'],
            action='observe', plan_sha256=context['plan_sha256'])

    with pytest.raises(ValueError):
        status.check(cfg, path, fake, publication=publication)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('name', ['water.gjf', 'job.pbs'])
@pytest.mark.parametrize('change', ['hash', 'size'])
def test_start_recovery_refuses_changed_remote_frozen_input(lost_manual, name, change):
    cfg, path, _, fake = lost_manual()
    original = frozen(path)
    data = fake.files[name]
    fake.files[name] = (b'!' + data[1:]) if change == 'hash' else data + b'\n'
    assert fake.files[name] != data
    if change == 'hash':
        assert len(fake.files[name]) == len(data)
    first = len(fake.calls)

    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


@pytest.mark.parametrize('name', ['water.gjf', 'job.pbs'])
@pytest.mark.parametrize('failure', ['query-error', 'missing-line', 'invalid-size', 'invalid-hash', 'wrong-name'])
def test_start_recovery_refuses_unverified_remote_metadata(lost_manual, name, failure):
    cfg, path, manifest, fake = lost_manual()
    original = frozen(path)
    command_to_corrupt = remote.metadata(cfg, manifest, name)
    run = fake.run
    first = len(fake.calls)

    def corrupted_metadata(command):
        result = run(command)
        if command != command_to_corrupt:
            return result
        if failure == 'query-error':
            return Result(255, '', 'Synthetic metadata connection failure')
        size, digest_line = result.stdout.splitlines()
        if failure == 'missing-line':
            return Result(stdout=size + '\n')
        if failure == 'invalid-size':
            return Result(stdout='unknown\n' + digest_line + '\n')
        digest, reported_name = digest_line.split('  ', 1)
        if failure == 'invalid-hash':
            digest = 'not-a-sha256'
        else:
            reported_name += '.different'
        return Result(stdout=size + '\n' + digest + '  ' + reported_name + '\n')

    fake.run = corrupted_metadata
    with pytest.raises((ValueError, TransportError)):
        status.check(cfg, path, fake)

    assert command_to_corrupt in fake.calls[first:]
    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)


def test_start_recovery_refuses_local_source_change_during_remote_metadata(lost_manual):
    cfg, path, _, fake = lost_manual()
    original = frozen(path)
    run = fake.run
    first = len(fake.calls)
    changed = []

    def late_metadata(command):
        result = run(command)
        if command.operation == 'metadata' and not changed:
            source = path / 'inputs/job.pbs'
            previous = source.stat()
            source.write_bytes(source.read_bytes())
            os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            changed.append(True)
        return result

    fake.run = late_metadata
    with pytest.raises(ValueError):
        status.check(cfg, path, fake)

    assert changed == [True]
    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    assert frozen(path) == original
    assert_read_only_since(fake, first)
