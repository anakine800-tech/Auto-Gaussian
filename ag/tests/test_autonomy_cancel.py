"""Formal cancellation evidence, using synthetic studies and fake transport."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import os

import pytest

from ag import attempt, autonomy as a, autonomy_cancel as evidence, cli, config, remote, snapshot, state, status, submission
from ag import _autonomy_store as disk
from ag.transport import Result, SSHConnectionError, SSHTransport, TransportError
from test_core import cfg, prepared, seed_submission  # noqa: F401
from test_autonomy import spec, VERSIONS
from test_snapshot import Fake
from test_slurm import multi  # noqa: F401


@pytest.fixture
def context(cfg, prepared, monkeypatch):
    path, _ = prepared
    clock = [1790000000.0]
    monkeypatch.setattr(a, 'now', lambda: clock[0])
    monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock[0], tz=tz)

    monkeypatch.setattr(snapshot, 'datetime', Clock)
    name = path.parent.parent.name
    a.initialize(cfg, name)
    plan = a.create_plan(cfg, name, spec(valid_until=clock[0] + 100000))
    a.confirm(cfg, name, plan['plan_id'], plan['sha256'], 'Synthetic human plan confirmation')
    a.begin(cfg, name, plan['plan_id'], 'Synthetic human round confirmation')
    state.write(path, 'submitting')
    seed_submission(path)
    state.write(path, 'running')
    return cfg, path, clock, plan


def start(context):
    cfg, path, _, plan = context
    return a.start(cfg, path.parent.parent.name, plan['plan_id'], 'synthetic-session')


def capture(context, run, fake=None):
    cfg, path, _, plan = context
    return snapshot.capture_for_run(cfg, path, fake or Fake(), run_id=run['run_id'],
                                    token=run['token'], plan_sha256=plan['sha256'])


def finish(context, run):
    cfg, path, _, _ = context
    a.change(cfg, path.parent.parent.name, 'finish', run['run_id'], run['token'],
             reason='Synthetic wake complete')


def review(value):
    return dict(snapshot=value['snapshot'], snapshot_sha256=value['autonomy']['snapshot_sha256'],
                log_sha256=value['sha256'], no_progress=True,
                reason='Synthetic reviewer inspected the complete fragment and found no progress')


def pair(context):
    first = start(context)
    one = capture(context, first)
    finish(context, first)
    context[2][0] += 1800
    second = start(context)
    two = capture(context, second)
    return second, [review(one), review(two)]


def check(context, run, reviews):
    cfg, path, _, plan = context
    return evidence.review_no_progress(cfg, path, run_id=run['run_id'], token=run['token'],
                                      plan_sha256=plan['sha256'], reviews=reviews)


def related_attempt(context, cfg, tmp_path, cluster, label):
    manifest = attempt.prepare(cfg, study_name=context[1].parent.parent.name,
                               template='gaussian', input_path=tmp_path / 'water.gjf',
                               tier='simple', walltime='00:30:00', label=label,
                               cluster=cluster, method_basis='Synthetic fallback method')
    return attempt.find(cfg, manifest['attempt_id']), manifest


def test_two_wakes_verify_bytes_but_never_grant_cancellation(context):
    run, reviews = pair(context)
    cfg, path, _, _ = context
    before = {p: p.read_bytes() for p in path.parent.parent.rglob('*') if p.is_file()}
    result = check(context, run, reviews)
    assert result['no_progress_review_verified'] is True
    assert result['cancellation_authorized'] is False
    assert result['scientific_judgment'] == 'pending_human_confirmation'
    assert result['binding']['job_id'] == '123.fixture'
    assert len({item['run_id'] for item in result['evidence']}) == 2
    assert {p: p.read_bytes() for p in path.parent.parent.rglob('*') if p.is_file()} == before
    assert not (path / '.cancel-claim').exists()
    assert a.status(cfg, path.parent.parent.name)['state']['totals']['cancel'] == 0


@pytest.mark.parametrize('field,value', [
    ('snapshot', 'snapshots/20000101T000000000000Z'),
    ('snapshot_sha256', '0' * 64), ('log_sha256', '0' * 64),
    ('no_progress', False), ('no_progress', 1), ('reason', ''),
])
def test_model_flags_cannot_replace_registered_evidence(context, field, value):
    run, reviews = pair(context)
    reviews[1][field] = value
    with pytest.raises(ValueError):
        check(context, run, reviews)


def test_same_snapshot_twice_reversed_and_missing_reviews(context):
    run, reviews = pair(context)
    for wrong in ([reviews[0], reviews[0]], list(reversed(reviews)), reviews[:1], []):
        with pytest.raises(ValueError):
            check(context, run, wrong)


def test_unregistered_manual_capture_cannot_be_adopted(context):
    run, reviews = pair(context)
    cfg, path, clock, _ = context
    clock[0] += 1
    result = snapshot.capture(cfg, path, Fake())
    reviews[1]['snapshot'] = result['snapshot']
    reviews[1]['snapshot_sha256'] = evidence.digest((path / result['snapshot'] / 'snapshot.json').read_bytes())
    with pytest.raises(ValueError, match='latest formal'):
        check(context, run, reviews)


def test_latest_capture_in_each_wake_is_required(context):
    run, reviews = pair(context)
    context[2][0] += 1
    newer = capture(context, run)
    with pytest.raises(ValueError, match='latest formal'):
        check(context, run, reviews)
    reviews[1] = review(newer)
    assert check(context, run, reviews)['no_progress_review_verified']


def test_intervening_wake_cannot_be_skipped(context):
    first = start(context)
    one = capture(context, first)
    finish(context, first)
    context[2][0] += 100
    middle = start(context)
    finish(context, middle)
    context[2][0] += 100
    last = start(context)
    two = capture(context, last)
    with pytest.raises(ValueError, match='expected wake'):
        check(context, last, [review(one), review(two)])


@pytest.mark.parametrize('target', ['water.log', 'snapshot.json'])
def test_changed_or_missing_snapshot_bytes_rejected(context, target):
    run, reviews = pair(context)
    file = context[1] / reviews[0]['snapshot'] / target
    file.write_bytes(file.read_bytes() + b' ')
    with pytest.raises(ValueError):
        check(context, run, reviews)
    file.unlink()
    with pytest.raises(OSError):
        check(context, run, reviews)


@pytest.mark.parametrize('field,value', [('job_id', '999.fixture'), ('cluster', 'different'),
                                       ('attempt_id', 'other-001-water')])
def test_metadata_identity_is_not_trusted(context, field, value):
    run, reviews = pair(context)
    file = context[1] / reviews[0]['snapshot'] / 'snapshot.json'
    metadata = json.loads(file.read_text())
    metadata[field] = value
    file.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        check(context, run, reviews)


@pytest.mark.parametrize('target', ['manifest.json', 'submission.json'])
def test_binding_bytes_must_remain_identical(context, target):
    run, reviews = pair(context)
    file = context[1] / target
    file.write_bytes(file.read_bytes() + b' ')
    with pytest.raises(ValueError):
        check(context, run, reviews)


@pytest.mark.parametrize('new_state', ['unknown', 'submitted', 'cancelled'])
def test_uncertain_queued_or_cancel_accepted_not_abnormal_evidence(context, new_state):
    run, reviews = pair(context)
    file = context[1] / 'status.json'
    current = json.loads(file.read_text())
    current['state'] = new_state
    file.write_text(json.dumps(current))
    with pytest.raises(ValueError):
        check(context, run, reviews)


def test_status_only_legacy_job_is_not_accepted(context):
    run = start(context)
    (context[1] / 'submission.json').unlink()
    fake = Fake()
    with pytest.raises(OSError):
        capture(context, run, fake)
    assert not fake.calls


@pytest.mark.parametrize('interval_hours', [3, 5])
def test_normal_three_or_five_hour_wake_interval_preserves_consecutive_evidence(context, interval_hours):
    first = start(context)
    previous = capture(context, first)
    finish(context, first)
    context[2][0] += interval_hours * 3600
    second = start(context)
    current = capture(context, second)
    result = check(context, second, [review(previous), review(current)])
    assert result['no_progress_review_verified'] is True
    assert result['cancellation_authorized'] is False
    assert [item['run_id'] for item in result['evidence']] == [first['run_id'], second['run_id']]


def test_expired_current_wake_cannot_review_its_registered_pair(context):
    run, reviews = pair(context)
    context[2][0] += a.RUN_SECONDS
    with pytest.raises(ValueError, match='60 minute'):
        check(context, run, reviews)


@pytest.mark.parametrize('pause_at', ['before_first_capture', 'during_first_capture', 'between_captures'])
def test_pause_breaks_pair_until_two_consecutive_captures_after_resume(context, pause_at):
    cfg, path, clock, _ = context
    name = path.parent.parent.name
    first = start(context)
    if pause_at == 'before_first_capture':
        a.pause(cfg, name, 'Synthetic human pause before the first capture')

    class Pausing(Fake):
        def run(self, command):
            a.pause(cfg, name, 'Synthetic human pause during the first capture')
            return super().run(command)

    previous = capture(context, first, Pausing() if pause_at == 'during_first_capture' else Fake())
    finish(context, first)
    if pause_at == 'between_captures':
        a.pause(cfg, name, 'Synthetic human pause between consecutive captures')
    clock[0] += 3 * 3600
    second = start(context)
    a.change(cfg, name, 'resume', second['run_id'], second['token'],
             reason='Synthetic human explicitly resumes observation')
    resumed = capture(context, second)
    with pytest.raises(ValueError, match='pause|resume'):
        check(context, second, [review(previous), review(resumed)])

    finish(context, second)
    clock[0] += 3 * 3600
    third = start(context)
    current = capture(context, third)
    result = check(context, third, [review(resumed), review(current)])
    assert result['no_progress_review_verified'] is True
    assert result['cancellation_authorized'] is False


def test_pause_and_takeover_fence_old_reviewer(context):
    run, reviews = pair(context)
    cfg, path, clock, plan = context
    a.pause(cfg, path.parent.parent.name, 'Synthetic human pause')
    with pytest.raises(ValueError, match='paused'):
        check(context, run, reviews)
    # Observation during pause is still supported, but gives no action permit.
    clock[0] += 1
    capture(context, run)
    clock[0] += a.LEASE_SECONDS
    a.start(cfg, path.parent.parent.name, plan['plan_id'], 'new-session', takeover_reason='Expired synthetic wake')
    with pytest.raises(ValueError, match='owner'):
        check(context, run, reviews)


def test_network_failure_leaves_no_registered_evidence(context):
    run = start(context)
    fake = Fake()
    fake.reply = TransportError('Synthetic lost connection')
    with pytest.raises(TransportError):
        capture(context, run, fake)
    cfg, path, _, _ = context
    assert not a.status(cfg, path.parent.parent.name)['state'].get('snapshots')


def test_owner_expires_during_network_io_without_holding_local_lock(context):
    run = start(context)
    cfg, path, clock, _ = context

    class Slow(Fake):
        def run(self, command):
            # A separate lock can be acquired during the network operation.
            a.pause(cfg, path.parent.parent.name, 'Pause during read')
            clock[0] += a.RUN_SECONDS
            return super().run(command)

    with pytest.raises(ValueError, match='60 minute'):
        capture(context, run, Slow())
    assert not (path / 'snapshots').exists()
    assert not a.status(cfg, path.parent.parent.name)['state'].get('snapshots')


def test_unknown_cancel_pause_breaks_snapshot_pair_after_resume(context):
    run, reviews = pair(context)
    cfg, path, _, plan = context
    name = path.parent.parent.name
    receipt = a._consume_cancellation(cfg, name, run['run_id'], run['token'],
        plan_sha256=plan['sha256'], binding=evidence.bound_attempt(path),
        ownership_sha256='a' * 64, kind='no_progress', reason='Synthetic consumed review',
        evidence_sha256='b' * 64)
    a._record_cancellation_result(cfg, name, run['run_id'], run['token'], attempt_id=path.name,
        consumption_sha256=receipt['record']['consumption_sha256'], outcome='unknown',
        reason='Synthetic lost response', evidence_sha256='c' * 64)
    a.change(cfg, name, 'resume', run['run_id'], run['token'], reason='Explicit synthetic resume')
    with pytest.raises(ValueError, match='Pause interrupted'):
        check(context, run, reviews)
    assert not (path / '.cancel-claim').exists()


@pytest.mark.parametrize('link', ['symbolic', 'hard'])
def test_snapshot_links_cannot_supply_evidence(context, link):
    run, reviews = pair(context)
    file = context[1] / reviews[0]['snapshot'] / 'water.log'
    copied = file.with_name('copy.log')
    file.rename(copied)
    if link == 'symbolic':
        file.symlink_to(copied)
    else:
        os.link(copied, file)
    with pytest.raises((OSError, ValueError)):
        check(context, run, reviews)


def test_cli_partial_wake_context_rejected_before_transport(context, monkeypatch, capsys):
    cfg, path, _, _ = context
    monkeypatch.setattr(cli, 'load_config', lambda **kw: cfg)
    from ag import transport
    monkeypatch.setattr(transport, 'SSHTransport', lambda *a, **k: pytest.fail('No transport expected'))
    assert cli.main(['snapshot', path.name, '--run', 'missing-token']) == 1
    assert 'requires --run' in capsys.readouterr().err


def test_capture_event_survives_publish_failure_and_cannot_be_registered_twice(context, monkeypatch):
    run = start(context)
    cfg, path, clock, _ = context
    name = path.parent.parent.name
    publish = disk.Store.publish

    def fail_publish(self, value):
        raise OSError('Synthetic failure after durable capture event')

    monkeypatch.setattr(disk.Store, 'publish', fail_publish)
    with pytest.raises(OSError, match='durable capture'):
        capture(context, run)
    monkeypatch.setattr(disk.Store, 'publish', publish)
    with pytest.raises(ValueError, match='stale'):
        a.status(cfg, name)
    journal = (path.parent.parent / 'autonomy' / 'journal.jsonl').read_bytes()
    event = disk.decode(journal.splitlines()[-1])
    assert event['op'] == 'snapshot'
    reference = event['data']['snapshot']
    original = json.loads((path / reference / 'snapshot.json').read_text())

    recovered = a.change(cfg, name, 'recover', run['run_id'], run['token'],
                         reason='Explicit recovery of durable synthetic capture')
    registered = recovered['state']['snapshots'][path.name + '/' + reference]
    assert registered['snapshot_sha256'] == evidence.digest((path / reference / 'snapshot.json').read_bytes())
    assert (path.parent.parent / 'autonomy' / 'journal.jsonl').read_bytes().startswith(journal)

    # Simulate an accidental attempt to register the already captured bytes;
    # recovery must not turn the same observation into another source event.
    with monkeypatch.context() as patch:
        patch.setattr(snapshot, 'capture', lambda *args, **kwargs: original)
        with pytest.raises(ValueError, match='already registered'):
            capture(context, run)
    assert len(a.status(cfg, name)['state']['snapshots']) == 1

    finish(context, run)
    clock[0] += 1800
    second = start(context)
    current = capture(context, second)
    old_review = dict(snapshot=reference, snapshot_sha256=registered['snapshot_sha256'],
                      log_sha256=registered['log_sha256'], no_progress=True,
                      reason='Synthetic reviewer inspected the recovered formal capture')
    assert check(context, second, [old_review, review(current)])['no_progress_review_verified']


def test_previous_round_snapshots_cannot_be_reviewed_in_new_round(context):
    run, old_reviews = pair(context)
    cfg, path, clock, plan = context
    name = path.parent.parent.name
    finish(context, run)
    a.change(cfg, name, 'end', None, None, round_id=run['state']['current_round'],
             reason='Synthetic human ends the first round')
    a.begin(cfg, name, plan['plan_id'], 'Synthetic human explicitly confirms another round')
    clock[0] += 1
    first_new = start(context)
    capture(context, first_new)
    finish(context, first_new)
    clock[0] += 1
    second_new = start(context)
    current = capture(context, second_new)
    with pytest.raises(ValueError, match='latest formal'):
        check(context, second_new, [old_reviews[1], review(current)])


def test_previous_plan_snapshot_cannot_supply_current_plan_review(context):
    first = start(context)
    previous = capture(context, first)
    finish(context, first)
    cfg, path, clock, _ = context
    name = path.parent.parent.name
    changed = a.create_plan(cfg, name, spec(goal='Revised synthetic comparison',
                                         valid_until=clock[0] + 100000))
    a.confirm(cfg, name, changed['plan_id'], changed['sha256'], 'Synthetic human confirms revised plan')
    clock[0] += 1
    revised_context = cfg, path, clock, changed
    current_run = start(revised_context)
    current = capture(revised_context, current_run)
    with pytest.raises(ValueError, match='expected wake and job'):
        check(revised_context, current_run, [review(previous), review(current)])


def test_another_attempts_registered_snapshots_do_not_substitute(context, tmp_path):
    cfg, path, clock, plan = context
    other, _ = related_attempt(context, cfg, tmp_path, cluster='default', label='other')
    state.write(other, 'submitting')
    seed_submission(other)
    state.write(other, 'running')
    other_context = cfg, other, clock, plan
    first = start(context)
    foreign_one = capture(context, first)
    capture(other_context, first)
    finish(context, first)
    clock[0] += 1
    second = start(context)
    foreign_two = capture(context, second)
    capture(other_context, second)
    assert path.name != other.name
    with pytest.raises(ValueError, match='latest formal'):
        check(other_context, second, [review(foreign_one), review(foreign_two)])


@pytest.mark.parametrize('retarget', ['status', 'submission'])
def test_slurm_same_job_number_cannot_be_retargeted_to_another_cluster(context, multi, tmp_path, retarget):
    _, _, clock, plan = context
    path, manifest = related_attempt(context, multi, tmp_path, cluster='batch', label='slurm')
    state.write(path, 'submitting')
    submission.record(path, manifest, '123')
    state.write(path, 'submitted', job_id='batch:123')
    state.write(path, 'running')
    slurm_context = multi, path, clock, plan
    run, reviews = pair(slurm_context)
    assert check(slurm_context, run, reviews)['binding']['job_id'] == '123'
    target = path / (retarget + '.json')
    value = json.loads(target.read_text())
    value['job_id'] = 'default:123'
    if retarget == 'submission':
        value['cluster'] = 'default'
    target.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='different cluster|binding'):
        check(slurm_context, run, reviews)


def test_pause_during_network_read_registers_observation_but_blocks_review(context):
    first = start(context)
    one = capture(context, first)
    finish(context, first)
    cfg, path, clock, _ = context
    name = path.parent.parent.name
    clock[0] += 1
    second = start(context)

    class Pausing(Fake):
        def run(self, command):
            a.pause(cfg, name, 'Synthetic human pause during network read')
            return super().run(command)

    two = capture(context, second, Pausing())
    current = a.status(cfg, name)['state']
    assert current['paused'] is True
    assert len(current['snapshots']) == 2
    assert current['snapshots'][path.name + '/' + two['snapshot']]['run_id'] == second['run_id']
    with pytest.raises(ValueError, match='paused'):
        check(context, second, [review(one), review(two)])
    assert current['totals']['cancel'] == 0
    assert not (path / '.cancel-claim').exists()


def test_owner_expiry_while_reading_captured_bytes_blocks_registration(context, monkeypatch):
    run = start(context)
    cfg, path, clock, _ = context
    original = evidence.snapshot_evidence

    def expires_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += a.RUN_SECONDS
        return result

    monkeypatch.setattr(evidence, 'snapshot_evidence', expires_after_read)
    with pytest.raises(ValueError, match='60 minute'):
        capture(context, run)
    assert len(list((path / 'snapshots').iterdir())) == 1
    assert not a.status(cfg, path.parent.parent.name)['state'].get('snapshots')


def test_formal_capture_accepts_configured_cluster_case_and_underscore(context, multi, tmp_path):
    _, _, clock, plan = context
    cluster = 'Synthetic_Cluster'
    multi['clusters'][cluster] = deepcopy(multi['clusters']['batch'])
    path, manifest = related_attempt(context, multi, tmp_path, cluster=cluster, label='named-cluster')
    state.write(path, 'submitting')
    submission.record(path, manifest, '123')
    state.write(path, 'submitted', job_id=cluster + ':123')
    state.write(path, 'running')
    slurm_context = multi, path, clock, plan
    run = start(slurm_context)
    fake = Fake()
    result = capture(slurm_context, run, fake)
    assert result['cluster'] == fake.selected == cluster
    registered = a.status(multi, path.parent.parent.name)['state']['snapshots']
    assert registered[path.name + '/' + result['snapshot']]['binding']['cluster'] == cluster


def checkpoint_attempt(context, tmp_path, route, *, template='gaussian', params=None, constraints=None):
    from test_core import INPUT
    cfg, existing, _, _ = context
    source = tmp_path / ('checkpoint.gjf' if template.startswith('gaussian') else 'checkpoint.xyz')
    if template.startswith('gaussian'):
        source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', route))
    else:
        source.write_text('3\nSynthetic water\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    m = attempt.prepare(cfg, study_name=existing.parent.parent.name, template=template,
                        input_path=source, tier='simple', walltime='00:30:00', label='checkpoint',
                        method_basis='Synthetic fallback', params=params, constraints=constraints)
    path = attempt.find(cfg, m['attempt_id'])
    state.write(path, 'submitting')
    seed_submission(path)
    return path, m


@pytest.mark.parametrize('route', [
    '# B3LYP/6-31G(d) SP',
    '#p B3LYP/def2TZVP Opt=(TS,CalcFC,Tight,NoEigenTest,MaxCycles=100) Freq=NoRaman '
    'SCF=(XQC,Tight) Integral=UltraFine SCRF=(SMD,Solvent=Dichloromethane) EmpiricalDispersion=GD3BJ',
    '# HF/STO-3G Opt Freq',
    '# PBE0/aug-cc-pVTZ SP 5D 7F NoSymm',
])
def test_checkpoint_free_strict_input_binds_original_bytes(context, tmp_path, route):
    path, m = checkpoint_attempt(context, tmp_path, route)
    before = {p: p.read_bytes() for p in path.rglob('*') if p.is_file()}
    context[0]['resources']['tiers']['simple']['cores'] = 12  # Historical proof is not current resource authorization.
    result = evidence.checkpoint_free_input(path)
    assert result['checkpoint_dependency'] is False and result['reroute_authorized'] is False
    assert result['bundle_sha256'] == m['bundle_sha256']
    assert result['input_sha256'] == evidence.digest(before[path / 'inputs' / 'checkpoint.gjf'])
    assert {p: p.read_bytes() for p in path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('option', [
    'Guess=Read', 'Guess=(Read,Only)', 'Guess=Chk', 'Guess=Only', 'Opt=Restart',
    'Opt=ReadFC', 'Opt=RCFC', 'Freq=ReadFC', 'Freq=Restart', 'IRC', 'IRC=RCFC',
    'IOp(5/13=1)', 'Stable=Restart', 'SCRF=(SMD,Solvent=Water,Read)',
    'UnknownKeyword', 'SCF=(Tight,UnknownOption)', 'SCF=(Tight,Restart)',
    'Opt=(CalcFC,(Restart))', 'Int=UltraFine Int=FineGrid',
    'SCRF=(SMD,Solvent=Water UnknownOption)', 'SCRF=(SMD,Solvent=Water Read)',
    'SCRF=(SMD,Solvent=Water Check)', 'SCRF=(SMD,Solvent=Water Guess=Read)',
    'SCRF=(SMD,Solvent=UnknownSolvent)',
])
def test_checkpoint_readers_abbreviations_and_unknown_syntax_are_not_proof(context, tmp_path, option):
    path, _ = checkpoint_attempt(context, tmp_path, '# B3LYP/6-31G(d) ' + option)
    with pytest.raises(ValueError):
        evidence.checkpoint_free_input(path)


@pytest.mark.parametrize('basis', ['ChkBasis', 'Gen', 'UnknownBasis'])
def test_opaque_basis_cannot_prove_no_checkpoint_dependency(context, tmp_path, basis):
    path, _ = checkpoint_attempt(context, tmp_path, '# HF/' + basis + ' SP')
    with pytest.raises(ValueError):
        evidence.checkpoint_free_input(path)


def rebind_synthetic_manifest(path, change):
    # Test construction only; production submission manifests are immutable.
    m = json.loads((path / 'manifest.json').read_text())
    change(m)
    (path / 'manifest.json').write_text(json.dumps(m))
    record = json.loads((path / 'submission.json').read_text())
    record['manifest_sha256'] = evidence.digest((path / 'manifest.json').read_bytes())
    (path / 'submission.json').write_text(json.dumps(record))


@pytest.mark.parametrize('field,value', [('parent_chk', None), ('input_validation', {'mode': 'relaxed'}),
                                       ('input_validation', {'mode': 'strict'}), ('input_validation', None)])
def test_parent_relaxed_or_unknown_validation_marker_is_rejected(context, field, value):
    path = context[1]
    rebind_synthetic_manifest(path, lambda m: m.update({field: value}))
    with pytest.raises(ValueError, match='Parent checkpoint or relaxed/unknown'):
        evidence.checkpoint_free_input(path)


@pytest.mark.parametrize('damage', ['changed', 'extra-chk', 'relaxed-sidecar', 'link'])
def test_checkpoint_proof_rejects_changed_bundle_or_hidden_attachment(context, damage):
    path = context[1]
    source = path / 'inputs' / 'water.gjf'
    if damage == 'changed':
        source.write_bytes(source.read_bytes() + b' ')
    elif damage == 'extra-chk':
        (path / 'inputs' / 'hidden.chk').write_bytes(b'Synthetic fixture')
    elif damage == 'relaxed-sidecar':
        (path / 'inputs' / 'input-validation.json').write_text('{}')
    else:
        original = path / 'original.gjf'
        source.rename(original)
        source.symlink_to(original)
    with pytest.raises((ValueError, OSError)):
        evidence.checkpoint_free_input(path)


@pytest.mark.parametrize('template', ['xtb', 'crest'])
def test_xyz_and_declared_constraints_have_no_checkpoint_reader(context, tmp_path, template):
    constraints = tmp_path / 'constraints.inp'
    constraints.write_text('$constrain\ndistance: 1,2,auto\n$end\n')
    path, _ = checkpoint_attempt(context, tmp_path, '', template=template, constraints=constraints)
    assert evidence.checkpoint_free_input(path)['checkpoint_dependency'] is False


def test_checkpoint_proof_does_not_accept_manual_no_dependency_label(context, tmp_path):
    path, _ = checkpoint_attempt(context, tmp_path, '# HF/STO-3G Guess=Read')
    rebind_synthetic_manifest(path, lambda m: m.update(no_chk_dependency=True))
    with pytest.raises(ValueError, match='checkpoint-reading'):
        evidence.checkpoint_free_input(path)


def test_counterpoise_frozen_fragment_input_is_verified(context, tmp_path):
    from test_counterpoise import WATER, CSV
    cfg, existing, _, _ = context
    source, fragments = tmp_path / 'pair.gjf', tmp_path / 'fragments.csv'
    source.write_text('%nprocshared=8\n%mem=10GB\n%chk=pair.chk\n'
                      '# B3LYP/6-31G(d) Counterpoise=2 SP\n\nSynthetic water dimer\n\n0 1\n' + WATER + '\n\n')
    fragments.write_text(CSV)
    m = attempt.prepare(cfg, study_name=existing.parent.parent.name, template='gaussian-cp',
                        input_path=source, fragments=fragments, tier='simple', walltime='00:30:00',
                        label='cp-checkpoint', method_basis='Synthetic fallback')
    path = attempt.find(cfg, m['attempt_id'])
    state.write(path, 'submitting')
    seed_submission(path)
    result = evidence.checkpoint_free_input(path)
    assert result['checkpoint_dependency'] is False
    assert result['inputs'] == m['inputs']


def test_removed_parent_tag_does_not_hide_oldchk_bytes(context):
    path = context[1]
    source = path / 'inputs' / 'water.gjf'
    source.write_bytes(b'%oldchk=parent.chk\n' + source.read_bytes())
    files = {p.name: p.read_bytes() for p in (path / 'inputs').iterdir()}
    records, sha = attempt.bundle(files)
    rebind_synthetic_manifest(path, lambda m: m.update(inputs=records, bundle_sha256=sha))
    with pytest.raises(ValueError, match='oldchk requires'):
        evidence.checkpoint_free_input(path)


@pytest.fixture
def scheduler_attempt(multi, tmp_path):
    from test_slurm import prepare
    path, manifest = prepare(multi, tmp_path)
    state.write(path, 'submitting')
    submission.record(path, manifest, '123', scheduler_cluster='fixture')
    state.write(path, 'submitted', job_id='batch:123')
    return multi, path, manifest


class NoSchedulerCalls:
    def run(self, command):
        pytest.fail('Invalid local evidence must be rejected before a scheduler query')


@pytest.mark.parametrize('cluster', [None, '', 'all', 'ALL', 'fixture,other'])
def test_scheduler_capture_cannot_retrofit_missing_or_broad_original_cluster(scheduler_attempt, cluster):
    cfg, path, _ = scheduler_attempt
    target = path / 'submission.json'
    record = json.loads(target.read_text())
    record['scheduler_cluster'] = cluster
    target.write_text(json.dumps(record))
    before = target.read_bytes()
    with pytest.raises(ValueError):
        status.capture_slurm_evidence(cfg, path, NoSchedulerCalls())
    assert target.read_bytes() == before
    assert not (path / 'scheduler-observations').exists()


@pytest.mark.parametrize('damage', ['unknown', 'wrong-job', 'wrong-cluster', 'missing-submission'])
def test_scheduler_capture_rejects_uncertain_or_mismatched_binding_before_query(scheduler_attempt, damage):
    cfg, path, _ = scheduler_attempt
    target = path / ('submission.json' if damage in ('wrong-cluster', 'missing-submission') else 'status.json')
    if damage == 'missing-submission':
        target.unlink()
    else:
        value = json.loads(target.read_text())
        value.update({'state': 'unknown'} if damage == 'unknown' else
                     {'job_id': 'batch:456'} if damage == 'wrong-job' else {'cluster': 'default'})
        target.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        status.capture_slurm_evidence(cfg, path, NoSchedulerCalls())
    assert not (path / 'scheduler-observations').exists()


def test_scheduler_capture_refuses_pbs_without_changing_lifecycle(context):
    cfg, path, _, _ = context
    before = {p: p.read_bytes() for p in path.parent.parent.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='Slurm observations only'):
        status.capture_slurm_evidence(cfg, path, NoSchedulerCalls())
    assert {p: p.read_bytes() for p in path.parent.parent.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('redirect', ['parent-symlink', 'timestamp-collision'])
def test_scheduler_capture_does_not_follow_or_overwrite_observation_directories(
        scheduler_attempt, tmp_path, monkeypatch, redirect):
    cfg, path, _ = scheduler_attempt
    directory = path / 'scheduler-observations'
    if redirect == 'parent-symlink':
        destination = tmp_path / 'unrelated'
        destination.mkdir()
        directory.symlink_to(destination, target_is_directory=True)
    else:
        instant = 1790000000.0
        monkeypatch.setattr(status.time, 'time', lambda: instant)
        name = datetime.fromtimestamp(instant, status.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        destination = directory / name
        destination.mkdir(parents=True)
    marker = destination / 'preserved.txt'
    marker.write_bytes(b'Original local evidence')
    with pytest.raises((ValueError, OSError)):
        status.capture_slurm_evidence(cfg, path, NoSchedulerCalls())
    assert list(destination.iterdir()) == [marker]
    assert marker.read_bytes() == b'Original local evidence'


class SchedulerEvidenceFake:
    def __init__(self, manifest):
        from test_slurm import EVIDENCE_CONFIG, EVIDENCE_HISTORY, EVIDENCE_JOB
        self.commands = [remote.slurm_evidence_config(), remote.slurm_evidence_version('scontrol'),
                         remote.slurm_evidence_version('sacct'),
                         remote.slurm_evidence_history('123', 'fixture'),
                         remote.slurm_evidence_job('123', 'fixture')]
        self.responses = [Result(stdout=text) for text in (
            EVIDENCE_CONFIG, 'slurm 26.05.5\n', 'slurm 26.05.5\n',
            EVIDENCE_HISTORY.replace('water-001-sp', manifest['attempt_id']),
            EVIDENCE_JOB.replace('water-001-sp', manifest['attempt_id']))]
        self.calls = []

    def run(self, command):
        assert command == self.commands[len(self.calls)]
        self.calls.append(command)
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def scheduler_observation(path):
    records = list((path / 'scheduler-observations').glob('*/observation.json'))
    assert len(records) == 1
    return records[0].parent, disk.decode(records[0].read_bytes())


def lifecycle_bytes(path):
    return {p: p.read_bytes() for p in path.parent.parent.rglob('*')
            if p.is_file() and 'scheduler-observations' not in p.parts}


@pytest.mark.parametrize('restarts', [0, 1])
def test_scheduler_capture_saves_fixed_queries_and_bytes_without_granting_eligibility(
        scheduler_attempt, restarts):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    fake.responses[3].stdout = fake.responses[3].stdout.replace('|PENDING|0|', f'|PENDING|{restarts}|')
    fake.responses[4].stdout = fake.responses[4].stdout.replace('Restarts=0 ', f'Restarts={restarts} ')
    before = lifecycle_bytes(path)
    result = status.capture_slurm_evidence(cfg, path, fake)
    directory, saved = scheduler_observation(path)
    assert result == dict(saved, observation_sha256=evidence.digest((directory / 'observation.json').read_bytes()))
    assert saved['complete'] is True and saved['reroute_authorized'] is False
    assert saved['binding'] == evidence.bound_attempt(path)
    assert saved['scheduler_cluster'] == 'fixture' and saved['binding']['cluster'] == 'batch'
    assert saved['controller']['state'] == 'PENDING'
    assert saved['controller']['restarts'] == saved['history'][0]['restarts'] == restarts
    assert saved['matched_db_index'] == saved['history'][0]['db_index'] == int(fake.responses[3].stdout.split('|')[4])
    assert fake.calls == fake.commands
    assert [entry['label'] for entry in saved['queries']] == [
        'config', 'scontrol-version', 'sacct-version', 'history', 'job']
    previous = saved['capture_started_at']
    for entry, command, response in zip(saved['queries'], fake.commands, fake.responses):
        assert entry['operation'] == command.operation and entry['command'] == command.text
        assert previous <= entry['started_at'] <= entry['finished_at'] <= saved['capture_finished_at']
        previous = entry['finished_at']
        assert entry['returncode'] == 0
        for stream in ('stdout', 'stderr'):
            expected = getattr(response, stream).encode('utf-8')
            output = directory / entry[stream]['file']
            assert output.read_bytes() == expected
            assert entry[stream]['sha256'] == evidence.digest(expected)
            assert entry[stream]['size'] == len(expected)
            assert output.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    assert lifecycle_bytes(path) == before
    assert not (path / '.cancel-claim').exists()


@pytest.mark.parametrize('stage', range(5))
@pytest.mark.parametrize('failure', ['nonzero', 'diagnostics'])
def test_scheduler_capture_preserves_failed_response_and_stops_queries(scheduler_attempt, stage, failure):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    fake.responses[stage] = Result(17 if failure == 'nonzero' else 0,
                                   stdout='Synthetic partial response\n', stderr='Synthetic diagnostic\n')
    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake)
    directory, saved = scheduler_observation(path)
    assert len(fake.calls) == len(saved['queries']) == stage + 1
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    failed = saved['queries'][-1]
    assert failed['returncode'] == fake.responses[stage].returncode
    for stream in ('stdout', 'stderr'):
        data = getattr(fake.responses[stage], stream).encode('utf-8')
        assert (directory / failed[stream]['file']).read_bytes() == data
        assert failed[stream]['sha256'] == evidence.digest(data)
    assert lifecycle_bytes(path) == before


@pytest.mark.parametrize('stage', [0, 1, 2])
def test_scheduler_capture_requires_exact_controller_and_client_version_combination(scheduler_attempt, stage):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    fake.responses[stage].stdout = fake.responses[stage].stdout.replace('26.05.5', '26.05.4')
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake)
    _, saved = scheduler_observation(path)
    assert len(fake.calls) == 3
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    assert '26.05.4' in saved['versions'].values()


@pytest.mark.parametrize('damage,expected_queries', [
    ('different-controller', 1), ('missing-history', 4), ('wrong-history-job', 4),
    ('wrong-controller-job', 5), ('conflicting-owner', 5),
])
def test_scheduler_capture_stops_on_missing_or_conflicting_identity(scheduler_attempt, damage, expected_queries):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    if damage == 'different-controller':
        fake.responses[0].stdout = fake.responses[0].stdout.replace('fixture', 'other')
    elif damage == 'missing-history':
        fake.responses[3].stdout = ''
    elif damage == 'wrong-history-job':
        fake.responses[3].stdout = fake.responses[3].stdout.replace('|123|', '|456|')
    elif damage == 'wrong-controller-job':
        fake.responses[4].stdout = fake.responses[4].stdout.replace('JobId=123 ', 'JobId=456 ')
    else:
        fake.responses[4].stdout = fake.responses[4].stdout.replace('UserId=fixture(1001)', 'UserId=fixture(1002)')
    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake)
    _, saved = scheduler_observation(path)
    assert len(fake.calls) == expected_queries
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    assert lifecycle_bytes(path) == before


@pytest.mark.parametrize('conflict', ['missing-current-sluid', 'restarts', 'submit', 'completing-after-cancel'])
def test_scheduler_capture_rejects_cross_source_instance_and_state_conflicts(scheduler_attempt, conflict):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    if conflict == 'missing-current-sluid':
        fake.responses[4].stdout = fake.responses[4].stdout.replace('SLUID=s0123456789ABC ', 'SLUID=s0123456789ABD ')
    elif conflict == 'restarts':
        fake.responses[3].stdout = fake.responses[3].stdout.replace('|PENDING|0|', '|PENDING|1|')
    elif conflict == 'submit':
        fake.responses[3].stdout = fake.responses[3].stdout.replace('2026-01-01T00:00:00', '2026-01-02T00:00:00')
    else:
        fake.responses[3].stdout = fake.responses[3].stdout.replace('|PENDING|', '|CANCELLED|')
        fake.responses[4].stdout = fake.responses[4].stdout.replace('JobState=PENDING ', 'JobState=COMPLETING ')
    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='inspect preserved') as failure:
        status.capture_slurm_evidence(cfg, path, fake)
    directory, saved = scheduler_observation(path)
    assert len(fake.calls) == len(saved['queries']) == 5
    assert 'instance or state conflict' in str(failure.value.__cause__)
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    for index in (3, 4):
        assert (directory / saved['queries'][index]['stdout']['file']).read_text() == fake.responses[index].stdout
    assert lifecycle_bytes(path) == before


def test_scheduler_capture_rechecks_binding_after_last_query(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt

    class ChangedBinding(SchedulerEvidenceFake):
        def run(self, command):
            response = super().run(command)
            if command.operation == 'slurm_evidence_job':
                target = path / 'submission.json'
                record = json.loads(target.read_text())
                record['scheduler_cluster'] = 'other'
                target.write_text(json.dumps(record))
            return response

    fake = ChangedBinding(manifest)
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake)
    _, saved = scheduler_observation(path)
    assert len(fake.calls) == 5
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    assert not (path / '.cancel-claim').exists()


@pytest.mark.parametrize('failure', ['ssh-255', 'connection-error'])
def test_scheduler_capture_real_transport_stops_first_error_without_lifecycle_annotation(
        scheduler_attempt, monkeypatch, failure):
    cfg, path, _ = scheduler_attempt
    transport = SSHTransport(config.select_cluster(cfg, 'batch'), read_only=True)
    transport.record_to([path])  # Simulate a transport reused after status().
    calls = []

    def execute(argv, timeout):
        calls.append(argv)
        if failure == 'connection-error':
            raise SSHConnectionError('Synthetic connection error')
        return Result(255, stdout='Synthetic partial response\n', stderr='Synthetic connection error')

    monkeypatch.setattr(transport, '_execute', execute)
    monkeypatch.setattr(status.time, 'sleep', lambda seconds: pytest.fail('Formal evidence must not retry'))
    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, transport)
    directory, saved = scheduler_observation(path)
    assert len(calls) == len(saved['queries']) == 1
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    if failure == 'ssh-255':
        assert saved['queries'][0]['returncode'] == 255
        assert (directory / saved['queries'][0]['stdout']['file']).read_bytes() == b'Synthetic partial response\n'
    else:
        assert saved['queries'][0]['error_type'] == 'SSHConnectionError'
    assert lifecycle_bytes(path) == before


def test_scheduler_capture_rejects_future_submit_time_but_preserves_reason(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    for index in (3, 4):
        fake.responses[index].stdout = fake.responses[index].stdout.replace('2026-01-01', '2099-01-01')
    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake)
    _, saved = scheduler_observation(path)
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    assert 'submit time is in the future' in saved['error']
    assert len(saved['queries']) == 5 and lifecycle_bytes(path) == before


def test_pending_future_start_is_not_interpreted_as_execution(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest)
    fake.responses[4].stdout = fake.responses[4].stdout.replace(
        'StartTime=Unknown', 'StartTime=2099-01-01T00:00:00')
    result = status.capture_slurm_evidence(cfg, path, fake)
    assert result['complete'] is True and result['reroute_authorized'] is False
    assert result['controller']['start'] == '2099-01-01T00:00:00+00:00'
    assert result['history'][0]['start'] is None


def test_final_clock_regression_keeps_failure_reason(scheduler_attempt, monkeypatch):
    cfg, path, manifest = scheduler_attempt
    ticks = iter([1800000000] * 11 + [1799999999, 1800000000])
    monkeypatch.setattr(status.time, 'time', lambda: next(ticks))
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, SchedulerEvidenceFake(manifest))
    _, saved = scheduler_observation(path)
    assert saved['complete'] is False and saved['error_type'] == 'ValueError'
    assert saved['error'] == 'Clock moved backwards after scheduler observation'


def test_scheduler_publication_guard_covers_only_final_local_writes(scheduler_attempt, monkeypatch):
    cfg, path, manifest = scheduler_attempt
    inside, events = [False], []

    class GuardAwareTransport(SchedulerEvidenceFake):
        def run(self, command):
            assert not inside[0], 'Network query ran inside publication guard'
            return super().run(command)

    fake = GuardAwareTransport(manifest)
    parser = status.slurm.parse_evidence_job

    def parse_job(*args, **kwargs):
        assert not inside[0], 'Scheduler parsing ran inside publication guard'
        return parser(*args, **kwargs)

    monkeypatch.setattr(status.slurm, 'parse_evidence_job', parse_job)

    @contextmanager
    def publication():
        assert fake.calls == fake.commands
        assert not (path / 'scheduler-observations').exists()
        events.append('enter')
        inside[0] = True
        try:
            yield
            scheduler_observation(path)
            events.append('published')
        finally:
            inside[0] = False
            events.append('exit')

    before = lifecycle_bytes(path)
    result = status.capture_slurm_evidence(cfg, path, fake, publication=publication)
    assert events == ['enter', 'published', 'exit']
    assert result['complete'] is True and result['reroute_authorized'] is False
    assert lifecycle_bytes(path) == before


def test_scheduler_publication_refusal_leaves_no_observation_or_lifecycle_change(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt
    fake, entered = SchedulerEvidenceFake(manifest), []

    @contextmanager
    def publication():
        entered.append(len(fake.calls))
        raise ValueError('Synthetic owner expired before publication')
        yield

    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='Synthetic owner expired'):
        status.capture_slurm_evidence(cfg, path, fake, publication=publication)
    assert entered == [5]
    assert not (path / 'scheduler-observations').exists()
    assert lifecycle_bytes(path) == before


def test_scheduler_failed_query_is_published_only_with_guard(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt
    fake, entered = SchedulerEvidenceFake(manifest), []
    fake.responses[3] = Result(17, stdout='Synthetic incomplete history\n', stderr='Synthetic failure\n')

    @contextmanager
    def publication():
        entered.append(len(fake.calls))
        assert not (path / 'scheduler-observations').exists()
        yield
        assert len(fake.calls) == 4  # No query may follow the failed history call.

    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake, publication=publication)
    directory, saved = scheduler_observation(path)
    assert entered == [4]
    assert saved['complete'] is False and saved['reroute_authorized'] is False
    assert (directory / saved['queries'][-1]['stdout']['file']).read_bytes() == b'Synthetic incomplete history\n'
    assert saved['queries'][-1]['returncode'] == 17
    assert lifecycle_bytes(path) == before


def test_scheduler_failed_query_cannot_publish_after_guard_refusal(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt
    fake, entered = SchedulerEvidenceFake(manifest), []
    fake.responses[3] = SSHConnectionError('Synthetic connection error')

    @contextmanager
    def publication():
        entered.append(len(fake.calls))
        raise ValueError('Synthetic owner expired before failure publication')
        yield

    before = lifecycle_bytes(path)
    with pytest.raises(ValueError, match='Synthetic owner expired'):
        status.capture_slurm_evidence(cfg, path, fake, publication=publication)
    assert entered == [4] and len(fake.calls) == 4
    assert not (path / 'scheduler-observations').exists()
    assert lifecycle_bytes(path) == before


class OriginPublication:
    def __init__(self, runtime):
        self.runtime, self.entries, self.active = runtime, 0, False
        self.reject = set()
        self.before = lambda count: None

    @contextmanager
    def __call__(self):
        self.entries += 1
        self.before(self.entries)
        if self.entries in self.reject:
            raise ValueError('Synthetic origin owner expired')
        assert not self.active
        self.active = True
        try:
            yield self.runtime
        finally:
            self.active = False


@pytest.fixture
def origin_context(multi, tmp_path, monkeypatch):
    from test_slurm import prepare, SubmissionProbeFake
    clock = [1800000000.0]
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    monkeypatch.setattr(a, 'now', lambda: clock[0])
    path, manifest = prepare(multi, tmp_path)
    # Construct a valid main-input-first manifest before probe/dispatch; the
    # bundle itself is name-bound, not dependent on this list's display order.
    manifest['inputs'].reverse()
    (path / 'manifest.json').write_text(json.dumps(manifest))
    probe = status.slurm_submission_probe(multi, path, SubmissionProbeFake(config.select_cluster(multi, 'batch')))
    (path / 'slurm-origin-probe.json').write_bytes(disk.encode(probe['record']))
    ownership = 'b' * 64
    state.write(path, 'submitting')
    submission.record(path, manifest, '123', scheduler_cluster='fixture',
                      authorization=dict(method='autonomy', ownership_sha256=ownership))
    record = json.loads((path / 'submission.json').read_text())
    record['scheduler_probe_sha256'] = probe['sha256']  # Synthetic T186 dispatch construction only.
    (path / 'submission.json').write_bytes(disk.encode(record))
    state.write(path, 'submitted', job_id='batch:123')
    runtime = dict(submissions={path.name: dict(ownership_sha256=ownership, round_id='round-fixture',
                   run_id='run-fixture', plan_sha256='c' * 64, dispatch_started={'at': clock[0] + 1})},
                   current_round='round-fixture', lease=dict(run_id='run-fixture'),
                   current_plan='plan-fixture', plans={'plan-fixture': dict(sha256='c' * 64)})
    publication = OriginPublication(runtime)
    clock[0] += 2

    class OriginTransport(SchedulerEvidenceFake):
        after_query = lambda self, command: None

        def run(self, command):
            assert not publication.active, 'Origin network IO must remain outside the owner lock'
            assert (path / 'slurm-origin-claim.json').exists()
            response = super().run(command)
            self.after_query(command)
            return response

    return dict(cfg=multi, path=path, manifest=manifest, probe_sha256=probe['sha256'],
                ownership_sha256=ownership, runtime=runtime, publication=publication,
                fake=OriginTransport(manifest), clock=clock)


def capture_origin(context):
    return evidence.capture_slurm_origin(context['cfg'], context['path'], context['fake'],
                                        probe_sha256=context['probe_sha256'],
                                        ownership_sha256=context['ownership_sha256'],
                                        publication=context['publication'])


def replace_origin_probe(context, change):
    # Fixture-only rewrite models what T186 froze before dispatch, never a
    # production path that upgrades a previously submitted Attempt.
    path = context['path']
    probe = disk.decode((path / 'slurm-origin-probe.json').read_bytes())
    change(probe)
    raw = disk.encode(probe)
    (path / 'slurm-origin-probe.json').write_bytes(raw)
    context['probe_sha256'] = evidence.digest(raw)
    record = disk.decode((path / 'submission.json').read_bytes())
    record['scheduler_probe_sha256'] = context['probe_sha256']
    (path / 'submission.json').write_bytes(disk.encode(record))


def test_origin_records_first_instance_with_three_short_publications(origin_context):
    c, path = origin_context, origin_context['path']
    before = lifecycle_bytes(path)
    result = capture_origin(c)
    saved = disk.decode((path / 'slurm-origin.json').read_bytes())
    claim = disk.decode((path / 'slurm-origin-claim.json').read_bytes())
    assert result == dict(saved, origin_sha256=evidence.digest(disk.encode(saved)))
    assert saved['status'] == 'recorded' and saved['initial_instance_recorded'] is True
    assert saved['live_validated'] is saved['reroute_authorized'] is False
    assert saved['binding'] == evidence.bound_attempt(path)
    assert saved['claim_sha256'] == evidence.digest(disk.encode(claim))
    assert saved['probe_sha256'] == claim['probe_sha256'] == c['probe_sha256']
    assert saved['ownership_sha256'] == claim['ownership_sha256'] == c['ownership_sha256']
    assert saved['dispatch_started'] == claim['dispatch_started'] == {'at': c['clock'][0] - 1}
    assert saved['instance']['sluid'] == saved['instance']['original_sluid']
    assert saved['observation_sha256'] == evidence.digest((path / saved['observation'] / 'observation.json').read_bytes())
    assert c['publication'].entries == 3 and len(c['fake'].calls) == 5
    assert all(p.read_bytes() == raw for p, raw in before.items())
    with pytest.raises(ValueError, match='already claimed'):
        capture_origin(c)
    assert len(c['fake'].calls) == 5


@pytest.mark.parametrize('unsupported', ['version', 'unknown-cluster'])
def test_origin_unsupported_probe_records_unavailable_without_remote_queries(origin_context, unsupported):
    c, path = origin_context, origin_context['path']
    def change(probe):
        probe['format_candidate'] = False
        if unsupported == 'version':
            probe['versions']['controller']['parsed'] = '25.11.0'
        else:
            probe['scheduler_cluster'] = None
    replace_origin_probe(c, change)
    before = (path / 'submission.json').read_bytes(), (path / 'status.json').read_bytes()
    result = capture_origin(c)
    assert result['status'] == 'unavailable' and result['initial_instance_recorded'] is False
    assert result['live_validated'] is result['reroute_authorized'] is False
    assert not c['fake'].calls and c['publication'].entries == 2
    assert not (path / 'scheduler-observations').exists()
    assert ((path / 'submission.json').read_bytes(), (path / 'status.json').read_bytes()) == before
    if unsupported == 'unknown-cluster':
        assert result['scheduler_cluster'] is None  # Do not adopt the sbatch name as a probe.
        assert disk.decode(before[0])['scheduler_cluster'] == 'fixture'


@pytest.mark.parametrize('damage', ['missing-probe-ref', 'wrong-owner', 'noncanonical-probe',
                                  'wrong-probe-bundle', 'changed-input', 'wrong-cluster'])
def test_origin_rejects_missing_or_changed_predispatch_sources_without_claim(origin_context, damage):
    c, path = origin_context, origin_context['path']
    record = disk.decode((path / 'submission.json').read_bytes())
    if damage == 'missing-probe-ref':
        del record['scheduler_probe_sha256']
    elif damage == 'wrong-owner':
        record['authorization']['ownership_sha256'] = 'd' * 64
    elif damage == 'wrong-cluster':
        record['scheduler_cluster'] = 'other'
    elif damage == 'noncanonical-probe':
        probe_path = path / 'slurm-origin-probe.json'
        raw = json.dumps(disk.decode(probe_path.read_bytes()), indent=2).encode()
        probe_path.write_bytes(raw)
        c['probe_sha256'] = record['scheduler_probe_sha256'] = evidence.digest(raw)
    elif damage == 'wrong-probe-bundle':
        replace_origin_probe(c, lambda probe: probe['binding'].update(bundle_sha256='d' * 64))
        record = disk.decode((path / 'submission.json').read_bytes())
    else:
        source = path / 'inputs' / 'water.gjf'
        source.write_bytes(source.read_bytes() + b' ')
    (path / 'submission.json').write_bytes(disk.encode(record))
    with pytest.raises(ValueError):
        capture_origin(c)
    assert not c['fake'].calls and not (path / 'slurm-origin-claim.json').exists()
    assert not (path / 'slurm-origin.json').exists()


@pytest.mark.parametrize('damage', ['owner', 'round', 'lease', 'plan', 'before-probe', 'future-dispatch',
                                  'missing-dispatch', 'numeric-dispatch', 'extra-dispatch-field'])
def test_origin_requires_same_consumed_dispatch_and_current_run(origin_context, damage):
    c = origin_context
    runtime = c['runtime']
    consumed = runtime['submissions'][c['path'].name]
    if damage == 'owner':
        consumed['ownership_sha256'] = 'e' * 64
    elif damage == 'round':
        runtime['current_round'] = 'another-round'
    elif damage == 'lease':
        runtime['lease']['run_id'] = 'another-run'
    elif damage == 'plan':
        runtime['plans'][runtime['current_plan']]['sha256'] = 'e' * 64
    elif damage == 'before-probe':
        consumed['dispatch_started']['at'] = c['clock'][0] - 3
    elif damage == 'future-dispatch':
        consumed['dispatch_started']['at'] = c['clock'][0] + 1
    elif damage == 'numeric-dispatch':
        consumed['dispatch_started'] = c['clock'][0] - 1
    elif damage == 'extra-dispatch-field':
        consumed['dispatch_started']['extra'] = True
    else:
        del consumed['dispatch_started']
    with pytest.raises(ValueError):
        capture_origin(c)
    assert not c['fake'].calls and not (c['path'] / 'slurm-origin-claim.json').exists()


@pytest.mark.parametrize('stage', [1, 2, 3])
def test_origin_publication_refusal_never_publishes_final_origin(origin_context, stage):
    c, path = origin_context, origin_context['path']
    c['publication'].reject.add(stage)
    before = (path / 'submission.json').read_bytes(), (path / 'status.json').read_bytes()
    with pytest.raises(ValueError, match='owner expired'):
        capture_origin(c)
    assert not (path / 'slurm-origin.json').exists()
    assert (path / 'slurm-origin-claim.json').exists() is (stage > 1)
    assert (path / 'scheduler-observations').exists() is (stage == 3)
    assert len(c['fake'].calls) == (0 if stage == 1 else 5)
    assert ((path / 'submission.json').read_bytes(), (path / 'status.json').read_bytes()) == before


@pytest.mark.parametrize('damage', ['claim', 'lease', 'probe', 'dispatch-at'])
def test_origin_rechecks_sources_after_network_before_any_observation_publication(origin_context, damage):
    c, path = origin_context, origin_context['path']
    def changed(command):
        if command.operation != 'slurm_evidence_job':
            return
        if damage == 'claim':
            (path / 'slurm-origin-claim.json').write_bytes(b'Changed claim')
        elif damage == 'lease':
            c['runtime']['lease']['run_id'] = 'another-run'
        elif damage == 'dispatch-at':
            c['runtime']['submissions'][path.name]['dispatch_started']['at'] += 0.5
        else:
            target = path / 'slurm-origin-probe.json'
            target.write_bytes(target.read_bytes() + b' ')
    c['fake'].after_query = changed
    with pytest.raises(ValueError):
        capture_origin(c)
    assert len(c['fake'].calls) == 5 and (path / 'slurm-origin-claim.json').exists()
    assert not (path / 'scheduler-observations').exists()
    assert not (path / 'slurm-origin.json').exists()


@pytest.mark.parametrize('failure', ['query', 'version-changed'])
def test_origin_real_observation_failure_is_persisted_then_raised_without_retry(origin_context, failure):
    c, path = origin_context, origin_context['path']
    if failure == 'query':
        c['fake'].responses[3] = Result(17, stdout='Synthetic partial history', stderr='Synthetic failure')
    else:
        c['fake'].responses[1].stdout = 'slurm 26.05.4\n'
    before = (path / 'submission.json').read_bytes(), (path / 'status.json').read_bytes()
    with pytest.raises(ValueError, match='inspect preserved') as caught:
        capture_origin(c)
    saved = disk.decode((path / 'slurm-origin.json').read_bytes())
    assert saved['status'] == 'unavailable' and saved['initial_instance_recorded'] is False
    assert caught.value.origin_evidence['record'] == saved
    assert caught.value.origin_evidence['origin_sha256'] == evidence.digest(disk.encode(saved))
    assert saved['observation_sha256'] == caught.value.evidence['observation_sha256']
    assert ((path / 'submission.json').read_bytes(), (path / 'status.json').read_bytes()) == before
    count = len(c['fake'].calls)
    with pytest.raises(ValueError, match='already claimed'):
        capture_origin(c)
    assert len(c['fake'].calls) == count


@pytest.mark.parametrize('unavailable', ['restarted', 'missing-original', 'different-original'])
def test_origin_valid_observation_without_original_instance_is_not_positive(origin_context, unavailable):
    c = origin_context
    if unavailable == 'restarted':
        c['fake'].responses[3].stdout = c['fake'].responses[3].stdout.replace('|PENDING|0|', '|PENDING|1|')
        c['fake'].responses[4].stdout = c['fake'].responses[4].stdout.replace('Restarts=0 ', 'Restarts=1 ')
    else:
        fields = c['fake'].responses[3].stdout.rstrip('\n').split('|')
        fields[-1] = 's0000000000000' if unavailable == 'missing-original' else 's0123456789ABD'
        c['fake'].responses[3].stdout = '|'.join(fields) + '\n'
    result = capture_origin(c)
    assert result['status'] == 'unavailable' and result['initial_instance_recorded'] is False
    assert result['live_validated'] is result['reroute_authorized'] is False
    assert len(c['fake'].calls) == 5


def test_origin_rejects_clock_regression_between_claim_and_capture(origin_context):
    c, path = origin_context, origin_context['path']
    clock = c['clock']
    # Move backwards after the first publication while remaining after dispatch.
    original = c['publication']

    @contextmanager
    def publication():
        with original() as runtime:
            yield runtime
        if original.entries == 1:
            clock[0] -= 0.5

    c['publication'] = publication
    with pytest.raises(ValueError, match='between origin claim and observation'):
        capture_origin(c)
    assert (path / 'slurm-origin-claim.json').exists() and not (path / 'slurm-origin.json').exists()
    assert len(c['fake'].calls) == 5
