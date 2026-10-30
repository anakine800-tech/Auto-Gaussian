"""T111 authorization tests: synthetic local studies and recording transports only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from ag import approval, attempt, cancel, cli, config, confirm, state, status, study, submit
from ag.transport import Result
from test_core import cfg, prepared, Fake, job_text, write_config
from test_slurm import multi, prepare, SlurmFake
from test_autonomy_submission import t186_driver_factory as autonomous_driver_factory
from test_autonomy_submission import t186_observation_owner as supplemental_observation_owner
from test_autonomy_submission import selector as core_selector
from test_fetch import fetched as supplemental_fetched


QUOTE = '  批准本批水分子验证 Attempt。\n保持上述输入与资源。  '


@pytest.mark.parametrize('first,late', [('fixture-a', 'fixture-b'), (None, 'fixture-a'), ('fixture-a', None)])
def test_late_scheduler_cluster_preserves_original_binding(multi, tmp_path, first, late):
    from ag import submission
    path, manifest = prepare(multi, tmp_path)
    original = submission.record(path, manifest, '123', scheduler_cluster=first)
    raw = (path / 'submission.json').read_bytes()
    if first is not None and late is not None:
        with pytest.raises(ValueError, match='scheduler cluster mismatch'):
            submission.record(path, manifest, '123', scheduler_cluster=late)
    else:
        assert submission.record(path, manifest, '123', scheduler_cluster=late) == original
    assert (path / 'submission.json').read_bytes() == raw


@pytest.fixture(autouse=True)
def no_dialog(monkeypatch):
    monkeypatch.setattr(confirm, 'confirm', lambda *a: pytest.fail('must not open a dialog'))


def record(cfg, path, **kwargs):
    return approval.create(cfg, path.parent.parent.name, [path.name], QUOTE, **kwargs)


def record_path(path, value):
    return path.parent.parent / 'approvals' / (value['id'] + '.json')


def second(cfg, tmp_path):
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian',
                        input_path=tmp_path / 'water.gjf', tier='simple', walltime='00:30:00', label='second')
    return attempt.find(cfg, m['attempt_id'])


def policy(cfg, **changes):
    value = dict(studies=['smoke'], templates=['gaussian', 'crest'], clusters=['default'],
                 max_cores_per_job=8, max_walltime='00:30:00', quote=QUOTE,
                 set_at='2026-10-23T00:00:00+00:00')
    value.update(changes)
    cfg['approval'] = {'policies': {'validation': value}}
    return value


@pytest.mark.parametrize('batch', [False, True])
def test_approval_submission_and_audit(cfg, prepared, tmp_path, capsys, batch):
    p, m = prepared
    paths = [p, second(cfg, tmp_path)] if batch else [p]
    value = approval.create(cfg, 'smoke', [p.name for p in paths], QUOTE)
    source = record_path(p, value)
    original = source.read_bytes()
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'create_attempt':
            assert source.with_suffix('.used').exists()
        if command.operation == 'submit':
            fake.qsub = Result(stdout=f'{123 + fake.operations().count("submit")}\n')
        return original_run(command)

    fake.run = run
    results = submit.submit(cfg, [p.name for p in paths], fake, approval_id=value['id'])
    assert all(r['state'] == 'submitted' for r in results)
    assert source.read_bytes() == original and value['quote'] == QUOTE and value['used'] is None
    marker = json.loads(source.with_suffix('.used').read_text())
    assert marker['attempts'] == [p.name for p in paths]
    assert value['total_cores'] == 8 * len(paths)
    stderr = capsys.readouterr().err
    for path in paths:
        saved = json.loads((path / 'submission.json').read_text())['authorization']
        assert saved['method'] == 'approval' and saved['quote'] == QUOTE
        assert saved['approval_id'] == value['id'] and saved['record_sha256'] == approval.digest(value)
        archive = json.loads((path / 'submission-summary.json').read_text())
        assert archive['summary'].strip() == stderr.strip()
        assert archive['authorization'] == saved
        assert path.name in stderr
        assert (path / '.submit-claim').exists()
    events = [json.loads(line) for line in (p.parent.parent / 'journal.jsonl').read_text().splitlines()]
    assert len([e for e in events if e['action'] == 'submit_authorization']) == len(paths)


def test_unused_members_cannot_reuse_consumed_batch(cfg, prepared, tmp_path):
    p, _ = prepared
    other = second(cfg, tmp_path)
    value = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)
    submit.submit(cfg, [p.name], Fake(cfg), approval_id=value['id'])
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='already used'):
        submit.submit(cfg, [other.name], fake, approval_id=value['id'])
    assert not fake.calls and state.read(other)['state'] == 'prepared'


@pytest.mark.parametrize('mode', ['approval', 'dialog'])
def test_unclaimed_member_can_submit_after_batch_stops(cfg, prepared, tmp_path, monkeypatch, mode):
    first, _ = prepared
    stopped, remaining = second(cfg, tmp_path), second(cfg, tmp_path)
    paths = [first, stopped, remaining]
    original = approval.create(cfg, 'smoke', [p.name for p in paths], QUOTE)
    source = record_path(first, original)
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'jobs' and fake.operations().count('jobs') == 2:
            fake.qstat = Result(stdout=job_text(cores=44))
        return original_run(command)

    fake.run = run
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(cfg, [p.name for p in paths], fake, approval_id=original['id'])
    assert fake.operations().count('submit') == 1
    assert state.read(first)['state'] == 'submitted'
    assert state.read(stopped)['state'] == 'failed_presubmit'
    assert (stopped / '.submit-claim').exists()
    assert state.read(remaining)['state'] == 'prepared'
    assert not (remaining / '.submit-claim').exists()
    assert not (remaining / 'submission-summary.json').exists()
    used = source.with_suffix('.used').read_bytes()
    summaries = {p: (p / 'submission-summary.json').read_bytes() for p in paths[:2]}

    fake = Fake(cfg)
    fake.qsub = Result(stdout='124.fixture\n')
    with pytest.raises(ValueError, match='already used'):
        submit.submit(cfg, [remaining.name], fake, approval_id=original['id'])
    assert not fake.calls
    kwargs = {}
    dialogs = []
    if mode == 'approval':
        kwargs['approval_id'] = record(cfg, remaining)['id']
    else:
        def accept(summary):
            dialogs.append(summary)
            return True
        monkeypatch.setattr(confirm, 'confirm', accept)
    result = submit.submit(cfg, [remaining.name], fake, **kwargs)
    assert result[0]['state'] == 'submitted' and fake.operations().count('submit') == 1
    saved = json.loads((remaining / 'submission.json').read_text())['authorization']
    archive = json.loads((remaining / 'submission-summary.json').read_text())
    assert saved['method'] == mode and saved['approval_id'] == kwargs.get('approval_id')
    assert archive['authorization'] == saved
    assert len(dialogs) == (1 if mode == 'dialog' else 0)
    assert source.with_suffix('.used').read_bytes() == used
    assert all((p / 'submission-summary.json').read_bytes() == data for p, data in summaries.items())


def test_summary_failure_stops_before_remote_write(cfg, prepared, tmp_path, monkeypatch):
    first, _ = prepared
    remaining = second(cfg, tmp_path)
    value = approval.create(cfg, 'smoke', [first.name, remaining.name], QUOTE)
    fake = Fake(cfg)

    def fail(path, authorization, summary):
        assert path == first and (path / '.submit-claim').exists()
        raise OSError('Synthetic summary write failure')

    monkeypatch.setattr(approval, 'archive', fail)
    with pytest.raises(OSError, match='Synthetic summary write failure'):
        submit.submit(cfg, [first.name, remaining.name], fake, approval_id=value['id'])
    assert 'create_attempt' not in fake.operations() and 'submit' not in fake.operations()
    assert state.read(first)['state'] == 'failed_presubmit'
    assert record_path(first, value).with_suffix('.used').exists()
    assert state.read(remaining)['state'] == 'prepared'
    assert not (remaining / '.submit-claim').exists()
    assert not (remaining / 'submission-summary.json').exists()


@pytest.mark.parametrize('field,value', [
    ('schema', 'bad'), ('id', 'other'), ('quote', ' '), ('study_id', 'another-study'),
    ('used', {}), ('total_cores', 9), ('total_cores', True), ('attempts', []),
    ('created_at', 'not-time'), ('created_at', '2020-01-01T00:00:00'),
    ('expires_at', '2000-01-01T00:00:00+00:00'),
    ('expires_at', '2100-01-01T00:00:00+00:00'),
])
def test_bad_approval_never_falls_back(cfg, prepared, field, value):
    p, _ = prepared
    doc = record(cfg, p)
    target = record_path(p, doc)
    doc[field] = value
    target.write_text(json.dumps(doc))
    fake = Fake(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name], fake, approval_id=target.stem)
    assert not fake.calls and not target.with_suffix('.used').exists()
    assert not (p / '.submit-claim').exists()


@pytest.mark.parametrize('field,value', [('attempt_id', 'another-001-sp'), ('bundle_sha256', '0' * 64),
    ('cluster', 'another'), ('cores', 4), ('cores', True)])
def test_mismatched_member_rejects_whole_batch(cfg, prepared, tmp_path, field, value):
    p, _ = prepared
    other = second(cfg, tmp_path)
    doc = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)
    doc['attempts'][1][field] = value
    doc['total_cores'] = sum(i['cores'] for i in doc['attempts'])
    target = record_path(p, doc)
    target.write_text(json.dumps(doc))
    fake = Fake(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name, other.name], fake, approval_id=doc['id'])
    assert not fake.calls and not target.with_suffix('.used').exists()
    assert all(not (item / '.submit-claim').exists() for item in (p, other))


@pytest.mark.parametrize('quote,hours', [('', 24), (' \n ', 24), (None, 24),
    (QUOTE, 25), (QUOTE, 0), (QUOTE, -1), (QUOTE, float('nan')), (QUOTE, float('inf')), (QUOTE, True)])
def test_invalid_create(cfg, prepared, quote, hours):
    p, _ = prepared
    with pytest.raises(ValueError):
        approval.create(cfg, 'smoke', [p.name], quote, hours)
    assert not (p.parent.parent / 'approvals').exists()


def test_create_refuses_consumed_and_other_study(cfg, prepared):
    p, _ = prepared
    study.init(cfg, 'other')
    with pytest.raises(ValueError, match='study'):
        approval.create(cfg, 'other', [p.name], QUOTE)
    state.write(p, 'submitting')
    with pytest.raises(ValueError, match='prepared'):
        record(cfg, p)


def test_exclusive_record_and_marker(cfg, prepared, monkeypatch):
    p, _ = prepared
    monkeypatch.setattr(approval, 'uuid4', lambda: SimpleNamespace(hex='a' * 32))
    doc = record(cfg, p, hours=1)
    target = record_path(p, doc)
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        record(cfg, p)
    assert target.read_bytes() == original
    real_open = os.open

    def open_file(path, flags, *args, **kwargs):
        if str(path).endswith('.used'):
            assert flags & os.O_EXCL
            raise PermissionError('Synthetic marker failure')
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(approval.os, 'open', open_file)
    fake = Fake(cfg)
    with pytest.raises(PermissionError):
        submit.submit(cfg, [p.name], fake, approval_id=doc['id'])
    assert 'create_attempt' not in fake.operations() and 'submit' not in fake.operations()
    assert not (p / '.submit-claim').exists()


def test_concurrent_use_has_one_winner(cfg, prepared, tmp_path):
    p, m = prepared
    other = second(cfg, tmp_path)
    doc = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)

    def use(path):
        batch = [(path, attempt.read_manifest(path), {})]
        auth = approval.authorize(cfg, batch, approval_id=doc['id'])
        return batch, auth

    candidates = [use(path) for path in (p, other)]

    def consume(candidate):
        try:
            approval.consume(cfg, *candidate)
            return True
        except (ValueError, FileExistsError):
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(consume, candidates)) == 1


@pytest.mark.parametrize('change', ['inputs', 'approval', 'expiry'])
def test_batch_rechecked_after_inventory(cfg, prepared, tmp_path, change):
    p, _ = prepared
    other = second(cfg, tmp_path)
    doc = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)
    target = record_path(p, doc)
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'identity':
            if change == 'inputs':
                (other / 'inputs/water.gjf').write_text('changed')
            else:
                modified = deepcopy(doc)
                if change == 'approval':
                    modified['quote'] = 'different approval'
                else:
                    now = datetime.now(timezone.utc)
                    modified.update(created_at=(now - timedelta(hours=2)).isoformat(),
                                    expires_at=(now - timedelta(hours=1)).isoformat())
                target.write_text(json.dumps(modified))
        return original_run(command)

    fake.run = run
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name, other.name], fake, approval_id=doc['id'])
    assert 'create_attempt' not in fake.operations()
    assert not target.with_suffix('.used').exists()
    assert not (p / '.submit-claim').exists()


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'linked-file', 'linked-directory', 'linked-marker'])
def test_unsafe_record_paths_fail_closed(cfg, prepared, tmp_path, kind):
    p, _ = prepared
    doc = record(cfg, p)
    target = record_path(p, doc)
    if kind == 'missing':
        target.unlink()
    elif kind == 'malformed':
        target.write_text('[]')
    elif kind == 'linked-marker':
        target.with_suffix('.used').symlink_to(tmp_path / 'missing')
    else:
        moved = tmp_path / 'moved'
        source = target if kind == 'linked-file' else target.parent
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=kind == 'linked-directory')
    fake = Fake(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name], fake, approval_id=doc['id'])
    assert not fake.calls


@pytest.mark.parametrize('mode', ['approval', 'policy'])
def test_second_core_check_without_dialog(cfg, prepared, mode):
    p, _ = prepared
    kwargs = {'approval_id': record(cfg, p)['id']} if mode == 'approval' else {'policy_name': 'validation'}
    if mode == 'policy':
        policy(cfg)
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'jobs' and fake.operations().count('jobs') == 1:
            fake.qstat = Result(stdout=job_text(cores=44))
        return original_run(command)

    fake.run = run
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(cfg, [p.name], fake, **kwargs)
    assert fake.operations().count('jobs') == 2 and 'create_attempt' not in fake.operations()
    assert state.read(p)['state'] == 'failed_presubmit' and (p / '.submit-claim').exists()


@pytest.mark.parametrize('mode', ['approval', 'policy'])
def test_cancel_still_needs_dialog(cfg, prepared, monkeypatch, mode):
    p, _ = prepared
    rule = policy(cfg)
    fake = Fake(cfg)
    kwargs = (dict(approval_id=record(cfg, p)['id']) if mode == 'approval'
              else dict(policy_name='validation'))
    submit.submit(cfg, [p.name], fake, **kwargs)
    auth = json.loads((p / 'submission.json').read_text())['authorization']
    assert auth['method'] == mode and auth['quote'] == QUOTE
    if mode == 'policy':
        assert auth['policy_name'] == 'validation' and auth['rule_sha256'] == approval.digest(rule)
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda *args: seen.append(args) or False)
    with pytest.raises(submit.UserCancelled):
        cancel.cancel(cfg, p, fake)
    assert len(seen) == 1 and seen[0][1] == '取消作业'
    assert 'cancel' not in fake.operations()


@pytest.mark.parametrize('changes', [dict(studies=['other']), dict(templates=['crest']), dict(clusters=['other']),
    dict(max_cores_per_job=4), dict(max_walltime='00:29:59')])
def test_policy_mismatch_has_no_remote_calls(cfg, prepared, changes):
    p, _ = prepared
    policy(cfg, **changes)
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='policy'):
        submit.submit(cfg, [p.name], fake, policy_name='validation')
    assert not fake.calls


@pytest.mark.parametrize('changes', [dict(studies=['sm*']), dict(studies=[]), dict(studies=['smoke', 'smoke']),
    dict(templates=['*']), dict(clusters=['def?ult']), dict(max_cores_per_job=True),
    dict(max_cores_per_job=0), dict(max_walltime='00:00:00'), dict(max_walltime='00:61:00'),
    dict(quote=' '), dict(set_at='2026-10-23'), dict(unrecognized=True)])
def test_invalid_policy_config(cfg, changes):
    policy(cfg, **changes)
    with pytest.raises(config.ConfigError):
        config.load_config(write_config(cfg))


@pytest.mark.parametrize('mode', ['approval', 'policy'])
def test_named_slurm_authorization(multi, tmp_path, mode):
    p, _ = prepare(multi, tmp_path)
    if mode == 'approval':
        kwargs = dict(approval_id=record(multi, p)['id'])
    else:
        policy(multi, studies=['water'], clusters=['batch'], max_walltime='01:30:00')
        kwargs = dict(policy_name='validation')
    selected = config.select_cluster(multi, 'batch')
    fake = SlurmFake(selected)
    assert submit.submit(selected, [p.name], fake, **kwargs)[0]['state'] == 'submitted'
    assert fake.operations().count('slurm_jobs') == 2
    assert json.loads((p / 'submission.json').read_text())['authorization']['method'] == mode


def test_dialog_default_even_with_matching_policy(cfg, prepared, monkeypatch):
    p, _ = prepared
    policy(cfg)
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or True)
    submit.submit(cfg, [p.name], Fake(cfg))
    assert len(seen) == 1
    assert json.loads((p / 'submission.json').read_text())['authorization']['method'] == 'dialog'


def test_cli_approve_is_local_and_doctor_lists_scope(cfg, prepared, monkeypatch, capsys):
    p, _ = prepared
    monkeypatch.setattr(cli, 'load_config', lambda **kwargs: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('approve is local'))
    assert cli.main(['approve', '--study', 'smoke', '--attempt', p.name, '--quote', QUOTE, '--hours', '2']) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc['quote'] == QUOTE and doc['attempts'][0]['attempt_id'] == p.name
    rules = policy(cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: Fake(cfg))
    assert cli.main(['doctor', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['approval_policies'] == {'validation': rules}


def test_cli_mutual_exclusion_and_cancel_rejects_authorization():
    for args in (['submit', 'smoke-001-sp', '--approval', 'a', '--policy', 'b'],
                 ['cancel', 'smoke-001-sp', '--approval', 'a'],
                 ['cancel', 'smoke-001-sp', '--policy', 'b']):
        with pytest.raises(SystemExit):
            cli.main(args)


@pytest.mark.parametrize('mode', ['approval', 'policy', 'dialog'])
def test_unknown_recovery_preserves_authorization(cfg, prepared, monkeypatch, mode):
    p, m = prepared
    if mode == 'approval':
        kwargs = dict(approval_id=record(cfg, p)['id'])
    elif mode == 'policy':
        policy(cfg)
        kwargs = dict(policy_name='validation')
    else:
        monkeypatch.setattr(confirm, 'confirm', lambda *a: True)
        kwargs = {}
    fake = Fake(cfg)
    fake.qsub = Result(255, '', 'synthetic lost response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [p.name], fake, **kwargs)
    archived = json.loads((p / 'submission-summary.json').read_text())['authorization']
    assert not (p / 'submission.json').exists()
    fake.calls.clear()
    fake.qstat = Result(stdout=job_text(m))
    assert status.check(cfg, p, fake)['state'] == 'submitted'
    assert json.loads((p / 'submission.json').read_text())['authorization'] == archived
    assert 'submit' not in fake.operations() and 'create_attempt' not in fake.operations()


def test_unknown_recovery_rejects_mismatched_summary(cfg, prepared):
    p, m = prepared
    doc = record(cfg, p)
    fake = Fake(cfg)
    fake.qsub = Result(255, '', 'synthetic lost response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [p.name], fake, approval_id=doc['id'])
    summary_path = p / 'submission-summary.json'
    summary = json.loads(summary_path.read_text())
    summary['manifest_sha256'] = '0' * 64
    summary_path.write_text(json.dumps(summary))
    fake.qstat = Result(stdout=job_text(m))
    with pytest.raises(ValueError, match='archived submission authorization'):
        status.check(cfg, p, fake)
    assert not (p / 'submission.json').exists()


@pytest.fixture
def late_reply_driver(autonomous_driver_factory, tmp_path, monkeypatch):
    home = tmp_path / 'late-reply-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    return autonomous_driver_factory('late-reply')


@pytest.mark.parametrize('observed_state', ['running', 'finished'])
def test_autonomous_late_reply_preserves_newer_observed_state(late_reply_driver, observed_state):
    from ag import autonomy
    cfg, path, manifest, context, at, _ = late_reply_driver
    retained = {}

    def publication():
        return autonomy.observation_publication_guard(cfg, 'smoke', context['run_id'], context['token'],
            action='observe', plan_sha256=context['plan_sha256'])

    class Observer(Fake):
        def run(self, command):
            if (observed_state == 'finished' and command.operation == 'receipt'
                    and 'ag-exit.json' in command.text):
                self.calls.append(command)
                return Result(stdout=json.dumps(dict(PBS_JOBID='123.fixture', returncode=0,
                    finished_at=datetime.fromtimestamp(at[0], timezone.utc).isoformat())))
            return super().run(command)

    class LateReply(Fake):
        def run(self, command):
            if command.operation == 'submit':
                # The scheduler accepted the job before the submitting client
                # received its reply. Real status recovery binds the same job
                # and publishes a later observation through its current guard.
                observer = Observer(cfg)
                observer.qstat = observer.job = Result(stdout=job_text(manifest))
                assert status.check(cfg, path, observer, publication=publication)['state'] == 'submitted'
                assert status.check(cfg, path, observer, publication=publication)['state'] == observed_state
                retained.update({name: (path / name).read_bytes()
                                 for name in ('status.json', 'submission.json')})
                retained['journal'] = (path.parent.parent / 'journal.jsonl').read_bytes()
            return super().run(command)

    fake = LateReply(cfg)
    result = submit.submit(cfg, [path.name], fake, autonomous=context)
    assert result[0]['state'] == observed_state
    assert fake.operations().count('submit') == 1
    assert {name: (path / name).read_bytes() for name in ('status.json', 'submission.json')} == {
        name: retained[name] for name in ('status.json', 'submission.json')}
    assert (path.parent.parent / 'journal.jsonl').read_bytes() == retained['journal']


@pytest.mark.parametrize('reply', [Result(1, '', 'qsub: invalid queue'),
                                  Result(1, '123.fixture', 'qsub: transport lost')])
def test_autonomous_nonzero_qsub_reply_retains_unknown_ownership(late_reply_driver, reply):
    from ag import autonomy, autonomy_submission
    cfg, path, _, context, _, _ = late_reply_driver
    fake = Fake(cfg)
    fake.qsub = reply
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert state.read(path)['state'] == 'unknown'
    assert (path / '.submit-claim').exists()
    assert not (path / 'submission.json').exists()
    consumed = autonomy.status(cfg, 'smoke')['state']['submissions'][path.name]
    assert consumed['dispatch_started'] is not None
    assert consumed['aborted_before_dispatch'] is None
    with autonomy_submission.machine_lock(create=False):
        evidence = autonomy_submission.read_reservations(cfg)
    assert len(evidence['records']) == len(evidence['placements']) == 1
    assert evidence['placements'][0]['state'] == 'unknown'
    assert evidence['placements'][0]['record_sha256'] == consumed['ownership_sha256']
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('submit') == 1


def test_supplement_large_file_io_finishes_before_publication(
        cfg, supplemental_fetched, supplemental_observation_owner, monkeypatch):
    from contextlib import contextmanager
    from ag import fetch
    path, fake = supplemental_fetched
    payload = b'synthetic-checkpoint-block\n' * 100000
    fake.files = {name: payload for name in fake.files}
    (path / 'outputs/water.log').write_bytes(payload)
    _, owner_path, _, _, locked, factory, _ = supplemental_observation_owner
    assert owner_path == path
    reads, synced, links = [], [], []
    original_fdopen, original_open = os.fdopen, Path.open
    original_fsync, original_link = os.fsync, os.link

    class WatchedReader:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, size=-1):
            assert not locked[0], 'Large output hashing must finish outside publication'
            reads.append(size)
            return self.handle.read(size)

    def fdopen(fd, *args, **kwargs):
        handle = original_fdopen(fd, *args, **kwargs)
        return WatchedReader(handle) if os.fstat(fd).st_size >= len(payload) else handle

    def open_path(target, *args, **kwargs):
        if target.is_relative_to(path / 'outputs'):
            assert not locked[0], 'Output reads/copies must finish outside publication'
        return original_open(target, *args, **kwargs)

    def fsync(fd):
        if os.fstat(fd).st_size >= len(payload):
            assert not locked[0], 'Large staged file sync must finish outside publication'
            synced.append(fd)
        return original_fsync(fd)

    def link(source, target, **kwargs):
        assert locked[0]
        links.append((source, target))
        return original_link(source, target, **kwargs)

    @contextmanager
    def publication():
        assert reads and synced
        with factory()():
            yield

    monkeypatch.setattr(os, 'fdopen', fdopen)
    monkeypatch.setattr(Path, 'open', open_path)
    monkeypatch.setattr(os, 'fsync', fsync)
    monkeypatch.setattr(os, 'link', link)
    result = fetch.fetch(cfg, path, fake, add_missing=True, publication=publication)
    assert result['files'] == ['job.pbs.out']
    assert len(links) == 1 and all(0 < size <= 1024 * 1024 for size in reads)
    source, target = links[0]
    assert source.stat().st_ino == target.stat().st_ino
    assert target.read_bytes() == payload
    assert json.loads((path / result['record']).read_text())['files'] == ['job.pbs.out']


@pytest.mark.parametrize('which', ['existing', 'staged'])
@pytest.mark.parametrize('change', ['replace', 'same_size_write', 'metadata'])
def test_supplement_rejects_file_changed_after_hash(cfg, supplemental_fetched, which, change):
    from contextlib import contextmanager
    from ag import fetch
    path, fake = supplemental_fetched
    before_status = (path / 'status.json').read_bytes()
    evidence = {}

    @contextmanager
    def publication():
        target = (path / 'outputs/water.log' if which == 'existing' else
                  next((path / 'outputs/.partial').glob('fetch-add-missing-*/job.pbs.out')))
        info, data = target.stat(), target.read_bytes()
        if change == 'replace':
            # Same bytes/size/mtime in a different inode are not the verified file.
            replaced = target.with_name(target.name + '.replacement')
            replaced.write_bytes(data)
            os.utime(replaced, ns=(info.st_atime_ns, info.st_mtime_ns))
            os.replace(replaced, target)
        elif change == 'same_size_write':
            target.write_bytes(b'X' * len(data))
            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
            assert target.stat().st_mtime_ns == info.st_mtime_ns
        else:
            target.chmod(info.st_mode ^ 0o100)
        evidence['target'] = target
        evidence['data'] = target.read_bytes()
        yield

    with pytest.raises(ValueError, match='Local output changed before publication'):
        fetch.fetch(cfg, path, fake, add_missing=True, publication=publication)
    assert not (path / 'outputs/job.pbs.out').exists()
    assert not list(path.glob('fetch-add-missing-*.json'))
    assert (path / 'status.json').read_bytes() == before_status
    assert evidence['target'].read_bytes() == evidence['data']
    assert list((path / 'outputs/.partial').glob('fetch-add-missing-*/job.pbs.out'))


def test_actual_remedy_driver_reads_and_parses_history_outside_short_locks(late_reply_driver, monkeypatch):
    from contextlib import contextmanager
    from ag import autonomy, autonomy_submission, _autonomy_store, _parse_outputs
    from test_autonomy_submission import finish_owned
    cfg, parent, manifest, context, clock, _ = late_reply_driver
    submit.submit(cfg, [parent.name], Fake(cfg), autonomous=context)
    finish_owned(parent, manifest, '-----\n# B3LYP/6-31G(d) Opt\n-----\n' +
                 'Synthetic Gaussian iteration\n' * 100000 + 'Convergence failure\nError termination\n')
    plan_id = autonomy.status(cfg, 'smoke')['state']['current_plan']
    autonomy.change(cfg, 'smoke', 'finish', context['run_id'], context['token'], reason='Synthetic next wake')
    clock[0] += 1
    wake = autonomy.start(cfg, 'smoke', plan_id, 'remedy-session')
    context = dict(context, run_id=wake['run_id'], token=wake['token'])
    source = Path(cfg['local']['studies_root']).parent / 'water.gjf'
    child = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='remedy', method_basis='Synthetic fixture', autonomous=context)
    path = attempt.find(cfg, child['attempt_id'])
    held, reads, parses = {'machine': 0, 'study': 0}, [], []
    for module, attribute, kind in ((autonomy_submission, 'machine_lock', 'machine'),
                                    (_autonomy_store, 'locked', 'study')):
        original = getattr(module, attribute)
        @contextmanager
        def watched_lock(*args, _original=original, _kind=kind, **kwargs):
            with _original(*args, **kwargs) as value:
                held[_kind] += 1
                try:
                    yield value
                finally:
                    held[_kind] -= 1
        monkeypatch.setattr(module, attribute, watched_lock)
    identities = {(p.stat().st_dev, p.stat().st_ino): p.name for p in (parent / 'outputs').iterdir()}
    original_fdopen, original_parse = os.fdopen, _parse_outputs.gaussian_job_sections
    class WatchedOutput:
        def __init__(self, stream, name):
            self.stream, self.name = stream, name
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, *args):
            assert not any(held.values()), 'Remedy output read must stay outside machine/study locks'
            reads.append(self.name)
            return self.stream.read(*args)
    def fdopen(fd, *args, **kwargs):
        info, stream = os.fstat(fd), original_fdopen(fd, *args, **kwargs)
        name = identities.get((info.st_dev, info.st_ino))
        return WatchedOutput(stream, name) if name else stream
    def parse(text):
        assert not any(held.values()), 'Remedy Gaussian parsing must stay outside machine/study locks'
        parses.append(len(text))
        return original_parse(text)
    monkeypatch.setattr(os, 'fdopen', fdopen)
    monkeypatch.setattr(_parse_outputs, 'gaussian_job_sections', parse)
    fake = Fake(cfg)
    fake.qsub = Result(stdout='124.fixture\n')
    assert submit.submit(cfg, [path.name], fake, autonomous=context)[0]['state'] == 'submitted'
    assert reads == ['water.log', 'job.pbs.out'] and len(parses) == 1
    assert fake.operations().count('create_attempt') == fake.operations().count('submit') == 1
    owned = autonomy.status(cfg, 'smoke')['state']['submissions'][path.name]
    assert owned['failure_class'] == 'gaussian-scf' and owned['dispatch_started'] is not None


@pytest.fixture
def ordinary_slurm_driver(cfg, autonomous_driver_factory, tmp_path, monkeypatch):
    home = tmp_path / 'ordinary-slurm-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    cfg.update(scheduler='slurm', partition='fixture')
    local, path, manifest, context, clock, _ = autonomous_driver_factory('ordinary-slurm')
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    target = Path(local['local']['studies_root']) / '.ag-monitor/latest.json'
    snapshot = json.loads(target.read_text())
    snapshot['cluster']['scheduler'] = 'slurm'
    snapshot['cluster']['nodes'][0].update(state='idle', partition='fixture', partition_state='up',
        mem_total_gb=120, mem_assigned_gb=0)
    target.write_text(json.dumps(snapshot))
    return local, path, manifest, context, SlurmFake(local)


@pytest.mark.parametrize('reported', [False, True])
def test_autonomous_slurm_submission_needs_no_version_or_origin_api(ordinary_slurm_driver, monkeypatch, reported):
    from ag import autonomy, autonomy_submission, remote
    cfg, path, manifest, context, fake = ordinary_slurm_driver
    counts = []
    count = submit._autonomous_unobserved_cores
    def checked_count(root, selected, jobs, *, exclude=None):
        counts.append(exclude)
        return count(root, selected, jobs, exclude=exclude)
    monkeypatch.setattr(submit, '_autonomous_unobserved_cores', checked_count)
    for module, names in ((status, ('slurm_submission_probe', 'capture_slurm_origin')),
                          (remote, ('slurm_submit_bound', 'slurm_evidence_config', 'slurm_evidence_version'))):
        for name in names:
            monkeypatch.delattr(module, name, raising=False)
    fake.qsub = Result(stdout='123;fixture\n' if reported else '123\n')
    result = submit.submit(cfg, [path.name], fake, autonomous=context)[0]
    assert result['state'] == 'submitted'
    assert counts == [None, path.name]
    assert [c for c in fake.calls if c.operation == 'submit'] == [remote.slurm_submit(cfg, manifest)]
    assert not any(c.operation.startswith('slurm_evidence_') for c in fake.calls)
    assert not list(path.glob('slurm-origin*'))
    binding = json.loads((path / 'submission.json').read_text())
    assert binding['scheduler_cluster'] == ('fixture' if reported else None)
    assert 'scheduler_probe_sha256' not in binding
    current = autonomy.status(cfg, 'smoke')['state']
    assert len(current['submissions']) == 1
    with autonomy_submission.machine_lock(create=False):
        evidence = autonomy_submission.read_reservations(cfg)
    assert len(evidence['records']) == 1 and 'slurm_probe' not in evidence['records'][0]['record']
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('submit') == 1


@pytest.mark.parametrize('reply', [Result(255, '', 'Synthetic lost response'),
                                  Result(1, '123;fixture\n', 'Synthetic nonzero response')])
def test_autonomous_slurm_unknown_keeps_actual_consumption(ordinary_slurm_driver, reply):
    from ag import autonomy, autonomy_submission
    cfg, path, _, context, fake = ordinary_slurm_driver
    fake.qsub = reply
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert state.read(path)['state'] == 'unknown'
    assert not (path / 'submission.json').exists()
    current = autonomy.status(cfg, 'smoke')['state']
    assert current['submissions'][path.name]['dispatch_started'] is not None
    with autonomy_submission.machine_lock(create=False):
        evidence = autonomy_submission.read_reservations(cfg)
    assert evidence['placements'][0]['state'] == 'unknown'
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('submit') == 1


@pytest.mark.parametrize('source', ['queue', 'accounting', 'absent'])
def test_autonomous_slurm_unknown_recovery_uses_existing_read_commands(ordinary_slurm_driver, source):
    from ag import autonomy, remote
    cfg, path, manifest, context, fake = ordinary_slurm_driver
    fake.qsub = Result(255, '', 'Synthetic lost submission response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    fake.calls.clear()
    own = f'123|{path.name}|fixture|PENDING|8|00:00:00|fixture\n'
    completed = f'123|{path.name}|fixture|COMPLETED|0:0|00:01:00|8\n'
    fake.queue = Result(stdout=own if source == 'queue' else '')
    fake.find = Result(stdout=completed if source == 'accounting' else '')
    fake.exact = Result(stdout=own if source == 'queue' else '')
    fake.accounting = Result(stdout=completed)
    def publication():
        return autonomy.observation_publication_guard(cfg, 'smoke', context['run_id'], context['token'],
            action='observe', plan_sha256=context['plan_sha256'])
    result = status.check(cfg, path, fake, publication=publication)
    queries = [c for c in fake.calls if c.operation in ('slurm_jobs', 'slurm_find', 'slurm_accounting')]
    assert queries[:2] == [remote.slurm_jobs(user='fixture'),
                           remote.slurm_find('fixture', path.name, manifest['created_at'][:10])]
    if source == 'absent':
        assert result['state'] == 'unknown' and not (path / 'submission.json').exists()
    else:
        assert result['job_id'] == 'default:123'
        assert result['state'] == ('submitted' if source == 'queue' else 'finished')
    assert not any(c.operation in ('submit', 'cancel') or c.operation.startswith('slurm_evidence_') for c in fake.calls)


@pytest.fixture
def local_autonomy_context(cfg, prepared, tmp_path, monkeypatch):
    from ag import autonomy
    from test_autonomy import spec, VERSIONS
    home = tmp_path.resolve() / 'presubmit-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(autonomy, 'now', lambda: 1000.)
    monkeypatch.setattr(autonomy, 'versions', lambda: dict(VERSIONS))
    autonomy.initialize(cfg, 'smoke')
    plan = autonomy.create_plan(cfg, 'smoke', spec())
    autonomy.confirm(cfg, 'smoke', plan['plan_id'], plan['sha256'], 'Synthetic confirmation')
    autonomy.begin(cfg, 'smoke', plan['plan_id'], 'Synthetic round')
    run = autonomy.start(cfg, 'smoke', plan['plan_id'], 'synthetic-owner')
    return dict(run_id=run['run_id'], token=run['token'], plan_sha256=plan['sha256'],
                policy_name='synthetic', object_id='water', job_class='main')


@pytest.mark.parametrize('operation', ['submit', 'prepare'])
def test_object_refusal_marks_only_one_branch(cfg, prepared, local_autonomy_context, monkeypatch, operation):
    from ag import autonomy
    context = local_autonomy_context
    path, _ = prepared

    def refuse(*args, **kwargs):
        raise autonomy.ObjectRefused('Synthetic facts conflict')

    monkeypatch.setattr(submit, '_submit' if operation == 'submit' else 'prepare_autonomous', refuse)
    with pytest.raises(autonomy.ObjectRefused):
        if operation == 'submit':
            submit.submit(cfg, [path.name], Fake(cfg), autonomous=context)
        else:
            attempt.prepare(cfg, study_name='smoke', autonomous=context)
    current = autonomy.status(cfg, 'smoke')['state']
    assert not current['paused']
    assert current['objects']['water']['status'] == '需要你看'
    assert 'Synthetic facts conflict' in current['objects']['water']['reason']
    assert not (path / '.submit-claim').exists()


def test_first_preconsume_transport_error_stays_local_and_duplicate_is_deferred(
        cfg, prepared, local_autonomy_context, monkeypatch):
    from ag import autonomy
    from ag.transport import TransportError
    context = local_autonomy_context
    path, _ = prepared
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise TransportError('Synthetic SSH failure before consumption')

    monkeypatch.setattr(submit, '_submit', fail)
    with pytest.raises(TransportError):
        submit.submit(cfg, [path.name], Fake(cfg), autonomous=context)
    current = autonomy.status(cfg, 'smoke')['state']
    assert not current['paused']
    assert len(current['presubmit_failures']) == 1
    assert state.read(path)['state'] == 'prepared' and not (path / '.submit-claim').exists()
    with pytest.raises(autonomy.PresubmitDeferred):
        submit.submit(cfg, [path.name], Fake(cfg), autonomous=context)
    assert len(calls) == 1


@pytest.mark.parametrize('stage', ['identity', 'create_attempt', 'upload', 'submit'])
def test_actual_transport_failure_respects_the_dispatch_boundary(late_reply_driver, stage):
    from ag import autonomy
    from ag.transport import TransportError
    cfg, path, _, context, _, _ = late_reply_driver

    class Failing(Fake):
        def upload(self, *args):
            if stage == 'upload':
                raise TransportError('Synthetic failed upload')
            return super().upload(*args)

    fake = Failing(cfg)
    fake.fail = stage
    with pytest.raises(submit.UnknownSubmission if stage == 'submit' else TransportError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    current = autonomy.status(cfg, 'smoke')['state']
    assert current['paused'] == (stage == 'submit')
    if stage == 'identity':
        assert state.read(path)['state'] == 'prepared'
        assert not (path / '.submit-claim').exists()
        assert len(current['presubmit_failures']) == 1 and not current.get('submissions')
    else:
        saved = current['submissions'][path.name]
        assert (saved['dispatch_started'] is not None) == (stage == 'submit')
        assert (saved['aborted_before_dispatch'] is None) == (stage == 'submit')
        assert state.read(path)['state'] == ('unknown' if stage == 'submit' else 'failed_presubmit')
        assert (path / '.submit-claim').exists()
    before = list(fake.calls)
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.calls == before


@pytest.mark.parametrize('reason', ['Input hash mismatch', 'Configuration changed', 'Rule expired'])
def test_global_submission_refusal_still_pauses(cfg, prepared, local_autonomy_context, monkeypatch, reason):
    from ag import autonomy

    def refuse(*args, **kwargs):
        raise ValueError(reason)

    monkeypatch.setattr(submit, '_submit', refuse)
    with pytest.raises(ValueError, match=reason):
        submit.submit(cfg, [prepared[0].name], Fake(cfg), autonomous=local_autonomy_context)
    assert autonomy.status(cfg, 'smoke')['state']['paused']


@pytest.mark.parametrize('change', ['placement', 'configuration'])
def test_actual_postclaim_route_change_keeps_object_and_global_stops_separate(late_reply_driver, change):
    from ag import autonomy
    cfg, path, _, context, _, _ = late_reply_driver

    class Changed(Fake):
        def run(self, command):
            result = super().run(command)
            if command.operation == 'create_attempt':
                if change == 'configuration':
                    cfg['routing']['ladder'][0]['id'] = 'changed-config-cell'
                else:
                    cache = Path(cfg['local']['studies_root']) / '.ag-monitor/latest.json'
                    snapshot = json.loads(cache.read_text())
                    node = snapshot['cluster']['nodes'][0]
                    node.update(cores_used=44, cores_idle=0, jobs=1)
                    cache.write_text(json.dumps(snapshot))
            return result

    fake = Changed(cfg)
    with pytest.raises(autonomy.ObjectRefused if change == 'placement' else ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    current = autonomy.status(cfg, 'smoke')['state']
    assert current['paused'] == (change == 'configuration')
    assert state.read(path)['state'] == 'failed_presubmit'
    assert current['submissions'][path.name]['aborted_before_dispatch'] is not None
    assert 'upload' not in fake.operations() and 'submit' not in fake.operations()
    if change == 'placement':
        assert current['objects']['water']['status'] == '需要你看'


@pytest.fixture
def core_projection_case(cfg, core_selector, tmp_path, monkeypatch):
    """Actual ownership/claim/ledger; only clock and routing selection are fixed."""
    from ag import autonomy, autonomy_submission, budget, journal, submission
    from ag.locks import claim
    from test_core import INPUT
    from test_autonomy import VERSIONS, spec
    from test_autonomy_submission import reservation_context, selection_for, publish_owned_absences
    home = tmp_path.resolve() / 'core-projection-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    clock = [1000.0]
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    monkeypatch.setattr(autonomy, 'versions', lambda: deepcopy(VERSIONS))
    monkeypatch.setattr(journal, 'now', lambda: datetime.fromtimestamp(clock[0], timezone.utc).isoformat())
    cfg.update(scheduler='slurm', partition='fixture')

    def create(kind):
        study.init(cfg, 'smoke')
        source = tmp_path / 'water.gjf'
        source.write_text(INPUT)
        manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='sp', method_basis='Synthetic core accounting')
        path = attempt.find(cfg, manifest['attempt_id'])
        selected = config.select_cluster(cfg, 'default')
        budget.reserve(selected, manifest, budget.read(selected))
        saved = None
        if kind.startswith('manual'):
            archive = approval.authorize(selected, [(path, manifest, attempt.verified_files(selected, path, manifest))],
                                         approval_id=record(cfg, path)['id'])
            claim(path / '.submit-claim')
            approval.archive(path, archive, 'Synthetic historical manual submission')
        else:
            autonomy.initialize(cfg, 'smoke')
            plan = autonomy.create_plan(cfg, 'smoke', spec())
            autonomy.confirm(cfg, 'smoke', plan['plan_id'], plan['sha256'], 'Synthetic confirmed plan')
            begun = autonomy.begin(cfg, 'smoke', plan['plan_id'], 'Synthetic confirmed round')
            run = autonomy.start(cfg, 'smoke', plan['plan_id'], 'fixture-owner')
            context = reservation_context(cfg, path, core_selector[0], round_id=begun['state']['current_round'],
                run_id=run['run_id'], plan_sha256=plan['sha256'],
                selection=selection_for(cfg, path, core_selector[0], round_id=begun['state']['current_round'],
                                        run_id=run['run_id']))
            with submit.autonomous_transaction(cfg), autonomy.submission_guard(cfg, 'smoke', run['run_id'], run['token'],
                                                                               plan_sha256=plan['sha256']) as guard:
                saved = autonomy_submission.write_reservation(cfg, path, context, verified_state=guard.snapshot)
                claim(path / '.submit-claim')
                approval.archive(path, saved['authorization'], saved['record']['summary'])
                guard.consume(saved['consume'])
                guard.dispatch_started(path.name)
        state.write(path, 'submitting')
        clock[0] += 1
        if kind == 'unknown':
            negative = dict(schema='ag-unknown-observation/1', observed_at=clock[0], scheduler='slurm',
                job_name=manifest['attempt_id'], matches=[], start_absent=True,
                account_sha256=saved['record']['account_sha256'])
            state.write(path, 'unknown', unknown_reconciliation=negative)
            autonomy.pause(cfg, 'smoke', 'Synthetic unknown submission')
            autonomy.resolve_attempt(cfg, 'smoke', path.name, 'Synthetic explicit human resolution')
        else:
            options = (dict(authorization=saved['authorization'], autonomy_state=autonomy.status(cfg, 'smoke')['state'])
                       if saved is not None else {})
            submission.record(path, manifest, '123', **options)
            state.write(path, 'submitted', job_id='default:123')
            if kind != 'manual_active':
                state.write(path, 'interrupted' if kind == 'interrupted' else 'finished', scheduler_observed_at=clock[0])
            if kind == 'interrupted':
                _, sample_clock = publish_owned_absences(cfg, saved, monkeypatch)
                clock[0] = sample_clock[0]
                monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
        return cfg, selected, path, manifest, saved, clock
    return create


@pytest.mark.parametrize('kind', ['unknown', 'interrupted', 'manual_terminal'])
def test_autonomous_core_projection_releases_proved_terminal_without_changing_ledger(core_projection_case, kind):
    from ag import autonomy, autonomy_submission, budget
    cfg, selected, path, manifest, saved, _ = core_projection_case(kind)
    original = budget.shared_ledgers(selected)
    raw = budget.ledger_path(selected).read_bytes()
    total = budget.totals(selected)
    with submit.autonomous_transaction(cfg):
        usage = autonomy_submission.read_reservations(cfg)
    if saved is not None:
        assert usage['placements'][0]['state'] == 'finished'
        consumed = deepcopy(autonomy.status(cfg, 'smoke')['state']['submissions'])
        assert consumed[path.name]['dispatch_started'] is not None
        assert consumed[path.name]['aborted_before_dispatch'] is None
    else:
        assert usage['warnings'][0]['kind'] == 'manual_terminal_excluded'
    # The durable estimate deliberately stays reserved; it is not a core lease.
    assert budget.shared_unobserved_cores(selected, [], original) == manifest['cores']
    assert submit._autonomous_unobserved_cores(cfg, selected, []) == 0
    assert budget.shared_ledgers(selected) == original
    assert budget.ledger_path(selected).read_bytes() == raw
    assert budget.totals(selected) == total == (0, budget.requested(manifest))
    assert (path / '.submit-claim').exists()
    if saved is not None:
        assert autonomy.status(cfg, 'smoke')['state']['submissions'] == consumed


@pytest.mark.parametrize('damage', ['stale', 'wrong_account'])
def test_autonomous_core_projection_rechecks_absence_before_each_count(core_projection_case, damage):
    from ag import budget, monitor
    cfg, selected, _, manifest, _, clock = core_projection_case('interrupted')
    raw = budget.ledger_path(selected).read_bytes()
    assert submit._autonomous_unobserved_cores(cfg, selected, []) == 0
    if damage == 'stale':
        clock[0] += 181
    else:
        target = monitor.cache_dir(cfg) / 'previous.json'
        sample = json.loads(target.read_text())
        sample['account_sha256'] = 'd' * 64
        target.write_text(json.dumps(sample))
    assert submit._autonomous_unobserved_cores(cfg, selected, []) == manifest['cores']
    assert budget.ledger_path(selected).read_bytes() == raw


def test_autonomous_core_projection_manual_warning_cannot_match_another_root(core_projection_case, tmp_path):
    import shutil
    from ag import autonomy_submission, budget
    cfg, selected, path, manifest, _, _ = core_projection_case('manual_active')
    other = tmp_path / 'other-studies' / path.parent.parent.name
    shutil.copytree(path.parent.parent, other)
    other_path = other / 'attempts' / path.name
    state.write(other_path, 'finished')
    autonomy_submission._register_study(other)
    with submit.autonomous_transaction(cfg):
        usage = autonomy_submission.read_reservations(cfg)
    assert usage['warnings'][0]['attempt_id'] == path.name
    assert usage['warnings'][0]['study_key'] != autonomy_submission.study_identity(path.parent.parent)['study_key']
    before = budget.ledger_path(selected).read_bytes()
    assert submit._autonomous_unobserved_cores(cfg, selected, []) == manifest['cores']
    assert budget.ledger_path(selected).read_bytes() == before


@pytest.mark.parametrize('kind', ['unknown', 'manual_terminal'])
def test_autonomous_core_projection_does_not_hide_mismatched_ledger_bundle(core_projection_case, kind):
    from ag import budget
    cfg, selected, path, _, _, _ = core_projection_case(kind)
    ledger = budget.read(selected)
    ledger['attempts'][path.name]['bundle_sha256'] = 'd' * 64
    budget.write(selected, ledger)
    before = budget.ledger_path(selected).read_bytes()
    with pytest.raises(ValueError, match='identity differ'):
        submit._autonomous_unobserved_cores(cfg, selected, [])
    assert budget.ledger_path(selected).read_bytes() == before


def test_autonomous_core_projection_never_uses_a_remapped_account(core_projection_case, monkeypatch):
    from ag import budget
    cfg, selected, _, _, _, _ = core_projection_case('interrupted')
    before = budget.ledger_path(selected).read_bytes()
    monkeypatch.setattr(config, 'ssh_identity', lambda entry: ('synthetic-other-host', 22, 'synthetic-other-user'))
    with pytest.raises(ValueError, match='account is not mapped'):
        submit._autonomous_unobserved_cores(cfg, selected, [])
    assert budget.ledger_path(selected).read_bytes() == before
