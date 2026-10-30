"""Manual cancellation fences, with synthetic files and recording transports."""
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread

import pytest

from ag import autonomy, cancel, confirm, journal, state, submission
from ag import _autonomy_store as disk
from ag.autonomy_submission import machine_lock
from ag.submit import UserCancelled
from ag.transport import TransportError
from test_autonomy import VERSIONS, spec
from test_core import cfg, Fake  # noqa: F401
from test_slurm import multi, prepare  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path.resolve() / 'synthetic-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))


@pytest.fixture(params=['default', 'batch'], ids=['pbs', 'slurm'])
def case(multi, tmp_path, monkeypatch, request):
    path, manifest = prepare(multi, tmp_path, cluster=request.param)
    job = '123.fixture' if request.param == 'default' else '123'
    state.write(path, 'submitting')
    submission.record(path, manifest, job)
    state.write(path, 'submitted', job_id=submission.qualified(manifest, job))
    monkeypatch.setattr(autonomy, 'now', lambda: 1000.0)
    monkeypatch.setattr(autonomy, 'versions', lambda: dict(VERSIONS))
    root = path.parent.parent
    autonomy.initialize(multi, root.name)
    plan = autonomy.create_plan(multi, root.name, spec())
    autonomy.confirm(multi, root.name, plan['plan_id'], plan['sha256'], 'Synthetic human confirmation')
    autonomy.begin(multi, root.name, plan['plan_id'], 'Synthetic round authorization')
    run = autonomy.start(multi, root.name, plan['plan_id'], 'synthetic-owner')
    return multi, path, manifest, job, run


class RecordingFake(Fake):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.recorded_paths = None
        self.before_run = lambda: None

    def record_to(self, paths):
        self.recorded_paths = list(paths)

    def run(self, command):
        self.before_run()
        return super().run(command)


def lock_probe(cfg, path):
    """Attempt the same lock order as owner/status/fetch publication."""
    entered = Event()
    errors = []

    def inspect():
        try:
            with machine_lock():
                with disk.locked(cfg, path.parent.parent.name, write=True):
                    entered.set()
        except BaseException as exc:
            errors.append(exc)
            entered.set()

    worker = Thread(target=inspect, daemon=True)
    worker.start()
    return entered, worker, errors


@pytest.mark.parametrize('outcome', ['succeeded', 'user_cancelled', 'failed_or_unknown'])
def test_cancel_local_publication_excludes_owner_observers(case, monkeypatch, outcome):
    cfg, path, _, _, _ = case
    fake = RecordingFake(cfg)
    fake.fail = 'cancel' if outcome == 'failed_or_unknown' else None
    observations = []
    probes = []

    def inspect_local(label):
        probe = lock_probe(cfg, path)
        probes.append(probe)
        observations.append((label, probe[0].wait(0.05)))

    original_append, original_claim, original_write = journal.append, cancel.claim, state.write

    def append(*args, **kwargs):
        if args[1] in ('cancel', 'state'):
            inspect_local('journal:' + args[1])
        return original_append(*args, **kwargs)

    def claim(target):
        inspect_local('claim')
        return original_claim(target)

    def write(*args, **kwargs):
        inspect_local('status')
        return original_write(*args, **kwargs)

    monkeypatch.setattr(journal, 'append', append)
    monkeypatch.setattr(cancel, 'claim', claim)
    monkeypatch.setattr(state, 'write', write)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: outcome != 'user_cancelled')
    before_owner = autonomy.status(cfg, path.parent.parent.name)['state']
    try:
        if outcome == 'user_cancelled':
            with pytest.raises(UserCancelled):
                cancel.cancel(cfg, path, fake)
        elif outcome == 'failed_or_unknown':
            with pytest.raises(TransportError):
                cancel.cancel(cfg, path, fake)
        else:
            assert cancel.cancel(cfg, path, fake)['state'] == 'cancelled'
    finally:
        for entered, worker, errors in probes:
            worker.join(2)
            assert not worker.is_alive() and not errors
    assert observations
    assert not [label for label, entered in observations if entered], observations
    assert fake.recorded_paths == []
    assert autonomy.status(cfg, path.parent.parent.name)['state'] == before_owner
    assert (path / '.cancel-claim').exists() == (outcome != 'user_cancelled')


def test_cancel_dialog_and_remote_io_do_not_hold_publication_locks(case, monkeypatch):
    cfg, path, _, _, _ = case
    fake = RecordingFake(cfg)

    def require_unlocked():
        entered, worker, errors = lock_probe(cfg, path)
        assert entered.wait(2), 'Dialog/remote IO held a machine or study publication lock'
        worker.join(2)
        assert not worker.is_alive() and not errors

    def approve(*args):
        require_unlocked()
        return True

    monkeypatch.setattr(confirm, 'confirm', approve)
    fake.before_run = require_unlocked
    assert cancel.cancel(cfg, path, fake)['state'] == 'cancelled'


def test_cancel_acquires_configuration_lock_before_each_publication(case, monkeypatch):
    cfg, path, _, _, _ = case
    fake = RecordingFake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: True)
    original_guard = autonomy.manual_publication_guard
    probes = []

    @contextmanager
    def publication(*args, **kwargs):
        # This runs before the actual factory acquires machine -> study.
        entered = Event()

        def acquire_configuration():
            with cancel.submission_lock(cfg):
                entered.set()

        worker = Thread(target=acquire_configuration, daemon=True)
        worker.start()
        probes.append((entered, worker))
        assert not entered.wait(0.05), 'Publication preceded the configuration lock'
        with original_guard(*args, **kwargs) as current:
            yield current

    monkeypatch.setattr(autonomy, 'manual_publication_guard', publication)
    try:
        assert cancel.cancel(cfg, path, fake)['state'] == 'cancelled'
    finally:
        for entered, worker in probes:
            worker.join(2)
            assert not worker.is_alive() and entered.is_set()


@pytest.mark.parametrize('finished_state', ['finished', 'fetched'])
def test_cancel_late_reply_preserves_published_completion(case, monkeypatch, finished_state):
    cfg, path, _, _, run = case
    fake = RecordingFake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: True)

    def publish_completion():
        with autonomy.observation_publication_guard(cfg, path.parent.parent.name,
                run['run_id'], run['token'], action='observe', plan_sha256=run['state']['plan_sha256']):
            state.write(path, 'finished', exit_status=7, completion_source='synthetic-observation')
            if finished_state == 'fetched':
                state.write(path, 'fetched', exit_status=7)

    fake.before_run = publish_completion
    result = cancel.cancel(cfg, path, fake)
    assert result['state'] == finished_state
    assert result['exit_status'] == 7
    assert result['completion_source'] == 'synthetic-observation'
    assert result['cleanup_status'] in ('qdel_accepted', 'scancel_accepted')
    assert (path / '.cancel-claim').exists()


def test_cancel_changed_confirmation_has_no_claim_or_remote_call(case, monkeypatch):
    cfg, path, _, _, _ = case
    fake = RecordingFake(cfg)

    def approve(*args):
        state.write(path, 'running')
        return True

    monkeypatch.setattr(confirm, 'confirm', approve)
    with pytest.raises(ValueError, match='Status changed during confirmation'):
        cancel.cancel(cfg, path, fake)
    assert not fake.calls and not (path / '.cancel-claim').exists()


def test_cancel_failed_or_unknown_keeps_claim_and_never_retries(case, monkeypatch):
    cfg, path, _, _, _ = case
    fake = RecordingFake(cfg)
    fake.fail = 'cancel'
    monkeypatch.setattr(confirm, 'confirm', lambda *args: True)
    with pytest.raises(TransportError):
        cancel.cancel(cfg, path, fake)
    assert state.read(path)['state'] == 'submitted'
    with pytest.raises(ValueError, match='no retry'):
        cancel.cancel(cfg, path, fake)
    assert len(fake.calls) == 1


def test_cancel_late_reply_cannot_publish_against_changed_binding(case, monkeypatch):
    cfg, path, manifest, _, _ = case
    fake = RecordingFake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: True)
    replacement = '456.fixture' if manifest['scheduler'] == 'pbs' else '456'

    def change_binding():
        state.write(path, 'running', job_id=submission.qualified(manifest, replacement))

    fake.before_run = change_binding
    with pytest.raises(ValueError, match='binding|Status changed'):
        cancel.cancel(cfg, path, fake)
    assert state.read(path)['state'] == 'running'
    assert (path / '.cancel-claim').exists()
    assert len(fake.calls) == 1


@pytest.mark.parametrize('cluster', ['default', 'batch'], ids=['pbs', 'slurm'])
def test_cancel_ordinary_study_retains_exact_job_and_once_only_behavior(multi, tmp_path, monkeypatch, cluster):
    path, manifest = prepare(multi, tmp_path, cluster=cluster)
    job = '123.fixture' if cluster == 'default' else '123'
    state.write(path, 'submitting')
    submission.record(path, manifest, job)
    state.write(path, 'submitted', job_id=submission.qualified(manifest, job))
    fake = RecordingFake(multi)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: True)
    assert cancel.cancel(multi, path, fake)['state'] == 'cancelled'
    assert [command.text for command in fake.calls] == [
        'qdel 123.fixture' if cluster == 'default' else 'scancel 123']
    with pytest.raises(ValueError):
        cancel.cancel(multi, path, fake)
    assert len(fake.calls) == 1
    assert not (path.parent.parent / 'autonomy').exists()
