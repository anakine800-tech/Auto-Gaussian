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
from test_core import cfg, prepared, seed_submission, autonomous_cancel_case  # noqa: F401
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


def prepare_evidence_fixture(cfg, **options):
    """Create synthetic bytes only, outside the production writer being tested.

    T186 wraps public prepare with the manual/autonomous writer fence. These
    unit fixtures intentionally add counterexamples inside an already-created
    T184 evidence context; they do not exercise preparation authorization.
    """
    return getattr(attempt, '_prepare', attempt.prepare)(cfg, **options)


def related_attempt(context, cfg, tmp_path, cluster, label):
    manifest = prepare_evidence_fixture(cfg, study_name=context[1].parent.parent.name,
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
    m = prepare_evidence_fixture(cfg, study_name=existing.parent.parent.name, template=template,
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


def test_checkpoint_proof_accepts_main_input_first_manifest_without_changing_bytes(context):
    path = context[1]
    original = disk.decode((path / 'manifest.json').read_bytes())
    rebind_synthetic_manifest(path, lambda manifest: manifest['inputs'].reverse())
    before = {p: p.read_bytes() for p in path.rglob('*') if p.is_file()}
    result = evidence.checkpoint_free_input(path)
    assert result['inputs'] == original['inputs']
    assert result['bundle_sha256'] == original['bundle_sha256']
    assert result['checkpoint_dependency'] is False and result['reroute_authorized'] is False
    assert {p: p.read_bytes() for p in path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('damage', ['missing-list', 'null-list', 'mapping', 'duplicate-name',
                                  'missing-field', 'extra-field', 'boolean-size', 'float-size',
                                  'negative-size', 'wrong-size', 'invalid-hash', 'wrong-hash',
                                  'invalid-name', 'wrong-bundle'])
def test_checkpoint_proof_rejects_invalid_or_inconsistent_input_records(context, damage):
    path = context[1]

    def change(manifest):
        if damage == 'missing-list':
            del manifest['inputs']
        elif damage == 'null-list':
            manifest['inputs'] = None
        elif damage == 'mapping':
            manifest['inputs'] = {item['name']: item for item in manifest['inputs']}
        elif damage == 'duplicate-name':
            manifest['inputs'].append(dict(manifest['inputs'][0]))
        elif damage == 'missing-field':
            del manifest['inputs'][0]['size']
        elif damage == 'extra-field':
            manifest['inputs'][0]['extra'] = 'Synthetic unrecognized metadata'
        elif damage == 'wrong-bundle':
            manifest['bundle_sha256'] = '0' * 64
        else:
            item = manifest['inputs'][0]
            field, value = {
                'boolean-size': ('size', True), 'float-size': ('size', float(item['size'])),
                'negative-size': ('size', -1), 'wrong-size': ('size', item['size'] + 1),
                'invalid-hash': ('sha256', True), 'wrong-hash': ('sha256', '0' * 64),
                'invalid-name': ('name', '../input'),
            }[damage]
            item[field] = value

    rebind_synthetic_manifest(path, change)
    with pytest.raises(ValueError):
        evidence.checkpoint_free_input(path)


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
    m = prepare_evidence_fixture(cfg, study_name=existing.parent.parent.name, template='gaussian-cp',
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
    def __init__(self, manifest, *, include_cancel_version=False):
        from test_slurm import EVIDENCE_CONFIG, EVIDENCE_HISTORY, EVIDENCE_JOB
        self.commands = [remote.slurm_evidence_config(), remote.slurm_evidence_version('scontrol'),
                         remote.slurm_evidence_version('sacct'),
                         remote.slurm_evidence_history('123', 'fixture'),
                         remote.slurm_evidence_job('123', 'fixture')]
        self.responses = [Result(stdout=text) for text in (
            EVIDENCE_CONFIG, 'slurm 26.05.5\n', 'slurm 26.05.5\n',
            EVIDENCE_HISTORY.replace('water-001-sp', manifest['attempt_id']),
            EVIDENCE_JOB.replace('water-001-sp', manifest['attempt_id']))]
        if include_cancel_version:
            self.commands.insert(3, remote.slurm_evidence_version('scancel'))
            self.responses.insert(3, Result(stdout='slurm 26.05.5\n'))
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
def origin_context(multi, tmp_path, monkeypatch, request):
    from test_slurm import prepare, SubmissionProbeFake
    clock = [1800000000.0]
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    monkeypatch.setattr(a, 'now', lambda: clock[0])
    path, manifest = prepare(multi, tmp_path)
    # Construct a valid main-input-first manifest before probe/dispatch; the
    # bundle itself is name-bound, not dependent on this list's display order.
    manifest['inputs'].reverse()
    (path / 'manifest.json').write_text(json.dumps(manifest))
    probe_transport = SubmissionProbeFake(config.select_cluster(multi, 'batch'))
    execution_gap = getattr(request, 'param', None)
    if execution_gap is not None:
        probe_transport.responses[{'sbatch': 3, 'scancel': 4}[execution_gap]].stdout = 'Unknown vendor version\n'
    probe = status.slurm_submission_probe(multi, path, probe_transport)
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


@pytest.mark.parametrize('origin_context', ['sbatch', 'scancel'], indirect=True)
def test_origin_recording_does_not_treat_execution_version_gap_as_observation_failure(origin_context):
    c = origin_context
    probe = disk.decode((c['path'] / 'slurm-origin-probe.json').read_bytes())
    assert set(probe['versions']) == {'controller', 'scontrol', 'sacct'}
    assert probe['format_candidate'] is True and len(probe['queries']) == 5
    assert not (probe['bound_submit_format_candidate'] and probe['instance_cancel_format_candidate'])
    result = capture_origin(c)
    assert result['initial_instance_recorded'] is True
    assert result['reroute_authorized'] is result['live_validated'] is False
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


def test_locked_no_progress_review_does_not_reenter_action_guard(context, monkeypatch):
    run, reviews = pair(context)
    cfg, path, _, plan = context
    with a.action_guard(cfg, path.parent.parent.name, run['run_id'], run['token'],
                        action='cancel', plan_sha256=plan['sha256']) as current:
        monkeypatch.setattr(a, 'action_guard', lambda *args, **kwargs: pytest.fail('Nested action guard'))
        result = evidence._review_no_progress_locked(path, current=current, run_id=run['run_id'],
                                                    plan_sha256=plan['sha256'], reviews=reviews)
    assert result['no_progress_review_verified'] is True and result['cancellation_authorized'] is False


@pytest.mark.parametrize('invalid', [None, 0, 1, 'true', [], {}])
def test_cancel_version_capture_option_requires_exact_boolean(scheduler_attempt, invalid):
    cfg, path, _ = scheduler_attempt
    with pytest.raises(ValueError, match='exact boolean'):
        status.capture_slurm_evidence(cfg, path, NoSchedulerCalls(), include_cancel_version=invalid)
    assert not (path / 'scheduler-observations').exists()


def test_cancel_capture_saves_six_fixed_queries_with_current_scancel_version(scheduler_attempt):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest, include_cancel_version=True)
    result = status.capture_slurm_evidence(cfg, path, fake, include_cancel_version=True)
    assert fake.calls == fake.commands and len(fake.calls) == 6
    assert result['execution_versions'] == {'scancel': '26.05.5'}
    assert result['queries'][3]['label'] == 'scancel-version'
    assert result['complete'] is True and result['reroute_authorized'] is False


@pytest.mark.parametrize('response', [Result(stdout='slurm 26.05.4\n'), Result(stdout='Unknown vendor version\n'),
                                      Result(255, stderr='Synthetic SSH failure')])
def test_cancel_capture_stops_at_unsupported_or_failed_scancel_version(scheduler_attempt, response):
    cfg, path, manifest = scheduler_attempt
    fake = SchedulerEvidenceFake(manifest, include_cancel_version=True)
    fake.responses[3] = response
    with pytest.raises(ValueError, match='inspect preserved'):
        status.capture_slurm_evidence(cfg, path, fake, include_cancel_version=True)
    _, saved = scheduler_observation(path)
    assert len(fake.calls) == 4 and saved['complete'] is False


@pytest.fixture
def instance_context(origin_context):
    c = origin_context
    c['origin'] = capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake,
                                                   include_cancel_version=True, publication=c['publication'])
    return c


def verify_instance(c, observation=None):
    return evidence.verify_slurm_instance(c['path'], ownership_sha256=c['ownership_sha256'],
                                          observation=c['observation'] if observation is None else observation)


def rewrite_observation(c, change):
    target = c['path'] / c['observation']['observation'] / 'observation.json'
    saved = disk.decode(target.read_bytes())
    change(saved)
    raw = disk.encode(saved)
    target.write_bytes(raw)
    c['observation'] = dict(saved, observation_sha256=evidence.digest(raw))


def test_instance_verification_reparses_original_and_current_evidence_without_permission(instance_context):
    c = instance_context
    before = lifecycle_bytes(c['path'])
    caller = dict(c['observation'], controller={'job_id': 'caller-forged'}, complete=False,
                  reroute_authorized=True, instance_cancel_format_candidate=True)
    result = verify_instance(c, caller)
    assert result['initial_instance'] == c['origin']['instance']
    assert result['current_instance']['job_id'] == '123'
    assert result['initial_history'] == result['current_history']
    assert len(result['initial_observation']['queries']) == 5
    assert len(result['current_observation']['queries']) == 6
    assert result['initial_observation']['capture_finished_at'] < result['current_observation']['capture_started_at']
    assert result['probe_execution_versions']['scancel']['parsed'] == '26.05.5'
    assert result['origin_dispatch'] == c['runtime']['submissions'][c['path'].name]
    assert result['cancellation_authorized'] is result['reroute_authorized'] is result['live_validated'] is False
    assert lifecycle_bytes(c['path']) == before


@pytest.mark.parametrize('target', ['slurm-origin-probe.json', 'slurm-origin-claim.json', 'slurm-origin.json'])
def test_instance_verification_rejects_missing_or_noncanonical_original_record(instance_context, target):
    c = instance_context
    source = c['path'] / target
    source.write_bytes(source.read_bytes() + b' ')
    with pytest.raises(ValueError, match='canonical'):
        verify_instance(c)
    source.unlink()
    with pytest.raises(FileNotFoundError):
        verify_instance(c)


def test_instance_verification_requires_verified_reservation_owner_hash(instance_context):
    c = instance_context
    with pytest.raises(ValueError, match='ownership binding'):
        evidence.verify_slurm_instance(c['path'], ownership_sha256='e' * 64, observation=c['observation'])


def test_instance_verification_rejects_handwritten_origin_instance(instance_context):
    c = instance_context
    target = c['path'] / 'slurm-origin.json'
    value = disk.decode(target.read_bytes())
    value['instance']['uid'] += 1
    target.write_bytes(disk.encode(value))
    with pytest.raises(ValueError, match='recorded raw evidence'):
        verify_instance(c)


@pytest.mark.parametrize('which', ['initial', 'current'])
def test_instance_verification_rejects_modified_raw_response(instance_context, which):
    c = instance_context
    reference = c['origin']['observation'] if which == 'initial' else c['observation']['observation']
    raw = c['path'] / reference / 'job.stdout.txt'
    raw.write_bytes(raw.read_bytes() + b' ')
    with pytest.raises(ValueError, match='hash or size'):
        verify_instance(c)


@pytest.mark.parametrize('damage', ['parsed-controller', 'parsed-history', 'query-command', 'query-order',
                                  'query-count', 'failed', 'future-time', 'before-initial', 'version'])
def test_instance_verification_rejects_rehashed_but_false_observation_metadata(instance_context, damage):
    c = instance_context
    def change(saved):
        if damage == 'parsed-controller':
            saved['controller']['uid'] += 1
        elif damage == 'parsed-history':
            saved['history'][0]['uid'] += 1
        elif damage == 'query-command':
            saved['queries'][3]['command'] += ' --other'
        elif damage == 'query-order':
            saved['queries'][1:3] = reversed(saved['queries'][1:3])
        elif damage == 'query-count':
            del saved['queries'][3]
        elif damage == 'failed':
            saved['complete'] = False
        elif damage == 'version':
            saved['execution_versions']['scancel'] = '26.05.4'
        else:
            delta = 100 if damage == 'future-time' else -60
            saved['capture_started_at'] += delta
            saved['capture_finished_at'] += delta
            for entry in saved['queries']:
                entry['started_at'] += delta
                entry['finished_at'] += delta
    rewrite_observation(c, change)
    with pytest.raises(ValueError):
        verify_instance(c)


@pytest.mark.parametrize('changed', ['restarts', 'uid', 'submit', 'sluid'])
def test_instance_verification_rejects_self_consistent_requeued_or_reused_current_instance(origin_context, changed):
    c = origin_context
    capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    if changed == 'restarts':
        fake.responses[4].stdout = fake.responses[4].stdout.replace('|PENDING|0|', '|PENDING|1|')
        fake.responses[5].stdout = fake.responses[5].stdout.replace('Restarts=0 ', 'Restarts=1 ')
    elif changed == 'uid':
        fake.responses[4].stdout = fake.responses[4].stdout.replace('|1001|', '|1002|')
        fake.responses[5].stdout = fake.responses[5].stdout.replace('UserId=fixture(1001)', 'UserId=fixture(1002)')
    elif changed == 'submit':
        for index in (4, 5):
            fake.responses[index].stdout = fake.responses[index].stdout.replace('2026-01-01', '2026-01-02')
    else:
        from test_slurm import EVIDENCE_DB_INDEX
        fake.responses[4].stdout = fake.responses[4].stdout.replace(str(EVIDENCE_DB_INDEX), str(EVIDENCE_DB_INDEX + 1))
        for index in (4, 5):
            fake.responses[index].stdout = fake.responses[index].stdout.replace('s0123456789ABC', 's0123456789ABD')
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    with pytest.raises(ValueError, match='restarted, replaced or reused'):
        verify_instance(c)


def test_instance_verification_allows_normal_state_and_time_progression(origin_context):
    c = origin_context
    capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    fake.responses[4].stdout = fake.responses[4].stdout.replace('|Unknown|Unknown|PENDING|',
                                                            '|2026-01-01T00:01:00|2026-01-01T00:02:00|CANCELLED|')
    fake.responses[5].stdout = fake.responses[5].stdout.replace('JobState=PENDING', 'JobState=CANCELLED').replace(
        'StartTime=Unknown EndTime=Unknown', 'StartTime=2026-01-01T00:01:00 EndTime=2026-01-01T00:02:00')
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    result = verify_instance(c)
    assert result['current_instance']['state'] == 'CANCELLED'
    assert result['current_instance']['start'] is not None and result['current_instance']['end'] is not None
    assert result['initial_instance']['state'] == 'PENDING' and result['cancellation_authorized'] is False


@pytest.mark.parametrize('origin_context', ['scancel'], indirect=True)
def test_instance_verification_requires_supported_scancel_in_original_probe(origin_context):
    c = origin_context
    capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    with pytest.raises(ValueError):
        verify_instance(c)


@pytest.mark.parametrize('origin_context', ['sbatch'], indirect=True)
def test_instance_verification_does_not_require_bound_submit_format_for_cancellation(origin_context):
    c = origin_context
    capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    result = verify_instance(c)
    assert result['probe_execution_versions']['sbatch']['parsed'] is None
    assert result['probe_execution_versions']['scancel']['parsed'] == '26.05.5'
    assert result['cancellation_authorized'] is False


def review_queue(c, **kwargs):
    return evidence.review_reroute_queue(c['path'], ownership_sha256=c['ownership_sha256'],
                                         observation=c['observation'], **kwargs)


def capture_changed_instance(c, *, state_name='PENDING', start='Unknown', end='Unknown', runtime='00:00:00'):
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    fake.responses[4].stdout = fake.responses[4].stdout.replace('|Unknown|Unknown|PENDING|',
                                                               f'|{start}|{end}|{state_name}|')
    fake.responses[5].stdout = fake.responses[5].stdout.replace('JobState=PENDING', 'JobState=' + state_name).replace(
        'StartTime=Unknown EndTime=Unknown', f'StartTime={start} EndTime={end}').replace(
        'RunTime=00:00:00', 'RunTime=' + runtime)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    return c['observation']


def test_reroute_queue_rechecks_frozen_input_and_has_no_route_permission(instance_context):
    c = instance_context
    before = lifecycle_bytes(c['path'])
    result = review_queue(c)
    assert result['never_started_observed'] is True
    assert result['queued_seconds'] >= 21600
    assert result['evaluated_at'] == c['observation']['capture_finished_at']
    assert result['checkpoint_free_input']['bundle_sha256'] == c['manifest']['bundle_sha256']
    assert result['slurm_instance'] == verify_instance(c)
    assert result['reroute_authorized'] is result['live_validated'] is False
    assert lifecycle_bytes(c['path']) == before
    target = c['path'] / 'inputs' / result['checkpoint_free_input']['input_name']
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        review_queue(c)


@pytest.mark.parametrize('age', [21599, 21600])
def test_reroute_queue_six_hour_boundary_uses_raw_submit(origin_context, age):
    c = origin_context
    submitted = datetime.fromtimestamp(c['clock'][0] + 60 - age, status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    for response in c['fake'].responses[3:]:
        response.stdout = response.stdout.replace('2026-01-01T00:00:00', submitted)
    capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    for response in fake.responses[4:]:
        response.stdout = response.stdout.replace('2026-01-01T00:00:00', submitted)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    if age < 21600:
        with pytest.raises(ValueError, match='six hours'):
            review_queue(c)
    else:
        assert review_queue(c)['queued_seconds'] == age


@pytest.mark.parametrize('now', [True, -1, float('nan'), 0, 1800001000])
def test_reroute_queue_rejects_untrusted_clock_value(instance_context, now):
    with pytest.raises(ValueError):
        review_queue(instance_context, now=now)


def test_reroute_queue_retains_future_controller_prediction_without_inventing_history_start(origin_context):
    c = origin_context
    predicted = datetime.fromtimestamp(c['clock'][0] + 3600, status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    c['fake'].responses[4].stdout = c['fake'].responses[4].stdout.replace('StartTime=Unknown', 'StartTime=' + predicted)
    capture_origin(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    fake.responses[5].stdout = fake.responses[5].stdout.replace('StartTime=Unknown', 'StartTime=' + predicted)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    result = review_queue(c)
    assert set(result['predicted_start_times'].values()) == {predicted + '+00:00'}
    assert result['slurm_instance']['current_history'][0]['start'] is None
    assert result['never_started_observed'] is True and result['reroute_authorized'] is False


def test_reroute_queue_rejects_past_controller_start_even_with_missing_accounting_start(instance_context):
    c = instance_context
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    fake.responses[5].stdout = fake.responses[5].stdout.replace('StartTime=Unknown', 'StartTime=2026-01-01T00:00:01')
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    with pytest.raises(ValueError, match='past start time'):
        review_queue(c)


@pytest.mark.parametrize('offset', [0, 3600, -1])
def test_reroute_queue_controller_prediction_uses_query_second_precision(origin_context, offset):
    c = origin_context
    expected = {}
    for phase in ('initial', 'current'):
        if phase == 'current':
            c['clock'][0] += 60
        fake = c['fake'] if phase == 'initial' else SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
        start = datetime.fromtimestamp(c['clock'][0] + offset, status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        end = datetime.fromtimestamp(c['clock'][0] + offset + 3600, status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        fake.responses[-1].stdout = fake.responses[-1].stdout.replace('StartTime=Unknown EndTime=Unknown',
                                                                     f'StartTime={start} EndTime={end}')
        expected[phase] = start + '+00:00', end + '+00:00'
        if phase == 'initial':
            capture_origin(c)
        else:
            c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    if offset < 0:
        with pytest.raises(ValueError, match='past start time'):
            review_queue(c)
    else:
        result = review_queue(c)
        for phase, (start, end) in expected.items():
            assert result['predicted_start_times'][phase] == start
            assert result['predicted_end_times'][phase] == end
        assert result['slurm_instance']['current_history'][0]['start'] is None
        assert result['slurm_instance']['current_history'][0]['end'] is None


def test_reroute_queue_does_not_treat_accounting_start_as_controller_prediction(instance_context):
    c = instance_context
    future = datetime.fromtimestamp(c['clock'][0] + 3600, status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    capture_changed_instance(c, start=future)
    with pytest.raises(ValueError, match='history contains a start/end'):
        review_queue(c)


@pytest.mark.parametrize('phase', ['initial', 'current'])
@pytest.mark.parametrize('damage', ['state', 'start', 'end', 'runtime', 'different-history'])
def test_reroute_queue_rejects_running_or_contradictory_history(origin_context, phase, damage):
    c = origin_context
    fake = c['fake'] if phase == 'initial' else SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    history_index, job_index = (3, 4) if phase == 'initial' else (4, 5)
    history, job = fake.responses[history_index], fake.responses[job_index]
    if damage == 'state':
        history.stdout = history.stdout.replace('|PENDING|', '|RUNNING|')
        job.stdout = job.stdout.replace('JobState=PENDING', 'JobState=RUNNING')
    elif damage in ('start', 'end'):
        index = 6 if damage == 'start' else 7
        fields = history.stdout.rstrip('\n').split('|')
        fields[index] = '2026-01-01T00:00:01'
        history.stdout = '|'.join(fields) + '\n'
        job.stdout = job.stdout.replace(damage.title() + 'Time=Unknown', damage.title() + 'Time=2026-01-01T00:00:01')
    elif damage == 'runtime':
        job.stdout = job.stdout.replace('RunTime=00:00:00', 'RunTime=00:00:01')
    else:
        from test_slurm import EVIDENCE_DB_INDEX
        history.stdout += history.stdout.replace(str(EVIDENCE_DB_INDEX), str(EVIDENCE_DB_INDEX + 1)).replace(
            's0123456789ABC', 's0123456789ABD')
    capture_origin(c)
    c['clock'][0] += 60
    if phase == 'initial':
        fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    with pytest.raises(ValueError, match='never-started|running time'):
        review_queue(c)


def prepare_cancel_response(c, *, kind='reroute'):
    if kind == 'no_progress':
        capture_changed_instance(c, state_name='RUNNING', start='2026-01-01T00:01:00', runtime='00:01:00')
    instance = verify_instance(c)
    job = instance['current_instance']
    target = dict(scheduler_cluster=job['cluster'], uid=job['uid'], job_name=job['name'], sluid=job['sluid'], purpose=kind)
    command = remote.slurm_cancel_instance(**target)
    request = dict(schema='ag-autonomy-cancel-request/1', binding=instance['binding'],
        ownership_sha256=c['ownership_sha256'], rule_sha256='d' * 64, round_id='round-fixture',
        slurm_instance=instance, target=target, run_id='cancel-wake', plan_sha256='c' * 64,
        policy_name='fixture', kind=kind, reason='Synthetic cancellation', command=command.text,
        operation=command.operation, timeout=command.timeout, recorded_at=c['clock'][0])
    if kind == 'reroute':
        request['reroute_queue'] = review_queue(c)
    else:
        request['no_progress'] = {}  # The executor/ledger owns the two-wake review; this fixture tests stop evidence.
    c['clock'][0] += 1
    response = dict(schema='ag-autonomy-cancel-response/1', request_sha256=evidence.digest(disk.encode(request)),
        consumption_sha256='e' * 64, started_at=c['clock'][0], finished_at=c['clock'][0] + 1,
        dispatched=True, returncode=0, stdout='', stderr='', exception=None, outcome='accepted', stopped=False,
        stdout_sha256=evidence.digest(b''), stderr_sha256=evidence.digest(b''))
    c['clock'][0] += 1
    (c['path'] / 'autonomy-cancel-request.json').write_bytes(disk.encode(request))
    (c['path'] / '.cancel-claim').write_bytes(b'Claimed permanently; never retry this exact cancellation.\n')
    (c['path'] / 'autonomy-cancel-response.json').write_bytes(disk.encode(response))
    c['cancel_response'] = dict(response='autonomy-cancel-response.json', response_sha256=evidence.digest(disk.encode(response)))
    c['request'], c['response'] = request, response
    return datetime.fromtimestamp(c['clock'][0], status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def stopped(c, **kwargs):
    return evidence.verify_slurm_stopped(c['path'], ownership_sha256=c['ownership_sha256'],
        observation=c['observation'], cancel_response=c['cancel_response'], **kwargs)


@pytest.mark.parametrize('kind,start_kind', [('no_progress', 'running'), ('reroute', 'unknown'), ('reroute', 'equal')])
def test_stopped_accepts_bound_terminal_instance_and_records_race_boundary(instance_context, kind, start_kind):
    c = instance_context
    end = prepare_cancel_response(c, kind=kind)
    start = {'running': '2026-01-01T00:01:00', 'unknown': 'Unknown', 'equal': end}[start_kind]
    capture_changed_instance(c, state_name='CANCELLED', start=start, end=end,
                             runtime='00:01:00' if kind == 'no_progress' else '00:00:00')
    before = lifecycle_bytes(c['path'])
    proof = stopped(c)
    assert proof['stopped'] is True and proof['kind'] == kind
    assert proof['request_sha256'] == c['response']['request_sha256']
    assert proof['response_sha256'] == c['cancel_response']['response_sha256']
    assert proof['consumption_sha256'] == c['response']['consumption_sha256']
    assert proof['input_binding']['bundle_sha256'] == c['manifest']['bundle_sha256']
    assert proof['query_cancel_window_not_excluded'] is (kind == 'reroute')
    assert bool(proof['precision_limitation']) is (kind == 'reroute')
    assert proof['reroute_authorized'] is proof['live_validated'] is False
    assert lifecycle_bytes(c['path']) == before


@pytest.fixture
def stopped_context(instance_context):
    c = instance_context
    end = prepare_cancel_response(c)
    capture_changed_instance(c, state_name='CANCELLED', start=end, end=end)
    return c


def rewrite_cancel(c, *, request_change=None, response_change=None):
    request = disk.decode((c['path'] / 'autonomy-cancel-request.json').read_bytes())
    response = disk.decode((c['path'] / 'autonomy-cancel-response.json').read_bytes())
    if request_change:
        request_change(request)
        (c['path'] / 'autonomy-cancel-request.json').write_bytes(disk.encode(request))
        response['request_sha256'] = evidence.digest(disk.encode(request))
    if response_change:
        response_change(response)
    raw = disk.encode(response)
    (c['path'] / 'autonomy-cancel-response.json').write_bytes(raw)
    c['cancel_response']['response_sha256'] = evidence.digest(raw)


@pytest.mark.parametrize('damage', ['unknown', 'not-dispatched', 'returncode-bool', 'exception', 'stream',
    'consumption', 'early-observation', 'inverted-time', 'already-stopped', 'schema'])
def test_stopped_rejects_rehashed_invalid_response(stopped_context, damage):
    c = stopped_context
    updates = {'unknown': {'outcome': 'unknown'}, 'not-dispatched': {'dispatched': False},
        'returncode-bool': {'returncode': False}, 'exception': {'exception': {'type': 'Error', 'message': 'failure'}},
        'stream': {'stdout': 'changed'}, 'consumption': {'consumption_sha256': 'bad'},
        'early-observation': {'finished_at': c['observation']['capture_started_at']},
        'inverted-time': {'started_at': c['observation']['capture_started_at']},
        'already-stopped': {'stopped': True}, 'schema': {'schema': 'other'}}
    rewrite_cancel(c, response_change=lambda response: response.update(updates[damage]))
    with pytest.raises(ValueError):
        stopped(c)


@pytest.mark.parametrize('damage', ['binding', 'owner', 'target', 'command', 'before', 'queue', 'missing-queue',
                                  'queue-clock', 'plan', 'round'])
def test_stopped_rejects_rehashed_invalid_request(stopped_context, damage):
    c = stopped_context
    def change(request):
        if damage == 'binding':
            request['binding']['job_id'] = '124'
        elif damage == 'owner':
            request['ownership_sha256'] = 'a' * 64
        elif damage == 'target':
            request['target']['sluid'] = 's0123456789ABD'
        elif damage == 'command':
            request['command'] += ' 124'
        elif damage == 'before':
            request['slurm_instance']['current_instance']['state'] = 'CANCELLED'
        elif damage == 'queue':
            request['reroute_queue']['queued_seconds'] += 1
        elif damage == 'missing-queue':
            del request['reroute_queue']
        elif damage == 'queue-clock':
            request['reroute_queue']['evaluated_at'] += 1
            request['reroute_queue']['queued_seconds'] += 1
        elif damage == 'plan':
            request['plan_sha256'] = 'a' * 64
        else:
            request['round_id'] = 'different-round'
    rewrite_cancel(c, request_change=change)
    with pytest.raises(ValueError):
        stopped(c)


@pytest.mark.parametrize('state_name,start,end,runtime', [
    ('COMPLETING', 'Unknown', '2026-01-01T00:00:01', '00:00:00'),
    ('RUNNING', '2026-01-01T00:00:01', 'Unknown', '00:00:00'),
    ('CANCELLED', 'Unknown', 'Unknown', '00:00:00'),
    ('CANCELLED', '2026-01-01T00:00:01', '2026-01-01T00:00:02', '00:00:00'),
    ('CANCELLED', '2026-01-01T00:00:02', '2026-01-01T00:00:01', '00:00:00'),
    ('CANCELLED', '2026-01-01T00:00:01', '2026-01-01T00:00:01', '00:00:01'),
    ('CANCELLED', '2026-01-01T00:00:01', '2026-01-01T00:00:01', '1-00:00:00'),
    ('CANCELLED', 'Unknown', '2026-01-01T00:00:01', 'INVALID'),
    ('CANCELLED', 'Unknown', '2026-01-01T00:00:01', 'UNLIMITED'),
])
def test_stopped_rejects_active_or_explicit_running_evidence(instance_context, state_name, start, end, runtime):
    c = instance_context
    prepare_cancel_response(c)
    capture_changed_instance(c, state_name=state_name, start=start, end=end, runtime=runtime)
    with pytest.raises(ValueError):
        stopped(c)


@pytest.mark.parametrize('target', ['autonomy-cancel-request.json', 'autonomy-cancel-response.json', '.cancel-claim'])
def test_stopped_requires_original_response_request_and_claim_bytes(stopped_context, target):
    c = stopped_context
    source = c['path'] / target
    source.write_bytes(source.read_bytes() + b' ')
    with pytest.raises(ValueError):
        stopped(c)


def test_stopped_rejects_changed_terminal_raw_bytes(stopped_context):
    c = stopped_context
    (c['path'] / c['observation']['observation'] / 'history.stdout.txt').write_text('')
    with pytest.raises(ValueError, match='hash or size'):
        stopped(c)


@pytest.mark.parametrize('runtime', ['00:00:01', '1-00:00:00'])
def test_stopped_reroute_rejects_positive_runtime_even_with_equal_start_and_end(instance_context, runtime):
    c = instance_context
    end = prepare_cancel_response(c)
    capture_changed_instance(c, state_name='CANCELLED', start=end, end=end, runtime=runtime)
    with pytest.raises(ValueError, match='records execution'):
        stopped(c)


def test_stopped_rejects_terminal_end_before_the_pending_observation(instance_context):
    c = instance_context
    prepare_cancel_response(c)
    capture_changed_instance(c, state_name='CANCELLED', end='2026-01-01T00:00:01')
    with pytest.raises(ValueError, match='pre-cancel active observation'):
        stopped(c)


def test_stopped_reroute_rejects_positive_execution_interval_after_cancel_request(instance_context):
    c = instance_context
    start = prepare_cancel_response(c)
    end = datetime.fromtimestamp(c['clock'][0] + 1, status.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    capture_changed_instance(c, state_name='CANCELLED', start=start, end=end)
    with pytest.raises(ValueError, match='records execution'):
        stopped(c)


@pytest.mark.parametrize('other_state', ['RUNNING', 'COMPLETING', 'CANCELLED'])
def test_stopped_rejects_activity_or_another_instance_anywhere_in_history(instance_context, other_state):
    from test_slurm import EVIDENCE_DB_INDEX
    c = instance_context
    end = prepare_cancel_response(c)
    c['clock'][0] += 60
    fake = SchedulerEvidenceFake(c['manifest'], include_cancel_version=True)
    original = fake.responses[4].stdout
    fake.responses[4].stdout = original.replace('|Unknown|Unknown|PENDING|', f'|{end}|{end}|CANCELLED|')
    fake.responses[4].stdout += original.replace('|PENDING|', '|' + other_state + '|').replace(
        str(EVIDENCE_DB_INDEX), str(EVIDENCE_DB_INDEX + 1)).replace('s0123456789ABC', 's0123456789ABD')
    fake.responses[5].stdout = fake.responses[5].stdout.replace('JobState=PENDING', 'JobState=CANCELLED').replace(
        'StartTime=Unknown EndTime=Unknown', f'StartTime={end} EndTime={end}')
    c['observation'] = status.capture_slurm_evidence(c['cfg'], c['path'], fake, include_cancel_version=True)
    with pytest.raises(ValueError, match='active or reused history'):
        stopped(c)


@pytest.mark.parametrize('change', ['restore-file-mtime', 'add-input', 'replace-parent-directory'])
def test_stopping_read_receipt_detects_changes_before_publication(stopped_context, monkeypatch, change):
    # Run against the actual T186 receipt in the integrated tree. Standalone
    # T187 keeps its local proof API without copying that implementation.
    ownership = pytest.importorskip('ag.autonomy_submission')
    c = stopped_context
    with ownership._capture_reads() as reads:
        result = stopped(c)
    assert result['stopped'] is True

    def forbidden_read(*args, **kwargs):
        raise AssertionError('Short publication verification must not re-read or reparse evidence bytes')

    monkeypatch.setattr(ownership, '_read_file', forbidden_read)
    monkeypatch.setattr(evidence, 'read_bytes', forbidden_read)
    reads.verify()
    if change == 'restore-file-mtime':
        target = c['path'] / c['observation']['observation'] / 'job.stdout.txt'
        original, data = target.stat(), target.read_bytes()
        target.write_bytes(b'X' + data[1:])  # Same size; restoring mtime must not hide a write.
        os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
        assert target.stat().st_size == original.st_size
        assert target.stat().st_mtime_ns == original.st_mtime_ns
        message = 'Evidence file changed'
    elif change == 'add-input':
        (c['path'] / 'inputs' / 'unexpected.chk').write_bytes(b'synthetic extra dependency')
        message = 'Evidence directory changed'
    else:
        directory = c['path'] / c['observation']['observation']
        original = directory.stat()
        retained = directory.with_name(directory.name + '-retained')
        directory.rename(retained)
        directory.mkdir()
        for child in retained.iterdir():
            child.rename(directory / child.name)
        os.utime(directory, ns=(original.st_atime_ns, original.st_mtime_ns))
        message = 'Evidence directory changed'
    with pytest.raises(ValueError, match=message):
        reads.verify()


@pytest.fixture
def reroute_cancel_case(autonomous_cancel_case, monkeypatch):
    """Executor boundaries only; T185's real ordering runs in combination tests."""
    import sys
    from types import SimpleNamespace
    import ag
    from ag import route, submit
    c = autonomous_cancel_case
    c.context.update(kind='reroute', reviews=None, reason='Verified queue and higher current capacity')
    c.state_label = 'PENDING'
    c.record.update(study_key='f' * 64, object_id='water', selection=dict(
        input=dict(request=dict(job_class='small')),
        result=dict(schema='ag-routing-ladder/1', recommendation=dict(cell_id='original'))))
    c.routing_calls, c.queue_calls = [], []
    c.route_damage, c.queue_error = None, None
    c.choice_changes, c.budget_calls, c.stopped_receipts = {}, [], []
    c.budget_error = None
    c.account_job_cap = None
    c.pause_after_consumption = False
    c.policy = dict(templates=['gaussian'], clusters={'default': dict(nodes=[], max_committed_cores=128,
        max_queued_cores=128, max_jobs=10)}, max_cores_per_job=64, max_walltime='01:00:00', max_attempts=20)
    c.runtime.update(current_plan='plan', plans={'plan': {'body': {'spec': {'submission_policy': deepcopy(c.policy)}}}})
    c.usage = dict(committed=c.manifest['cores'], queued=c.manifest['cores'], active=[dict(run_id='older-wake')])

    def budget(policy, **values):
        assert c.locks == ['config', 'machine', 'guard']
        assert policy == c.policy
        c.budget_calls.append(deepcopy(values))
        if c.budget_error:
            raise ValueError(c.budget_error)
        return dict(pause_after_consumption=c.pause_after_consumption)

    def stopped_reservations(cfg, *, states=None):
        assert not c.locks
        assert states == {str(c.path.parent.parent): c.runtime}
        receipt = object()
        c.stopped_receipts.append(receipt)
        return receipt

    def selector(*args, evaluate_from=None, **kwargs):
        raise AssertionError('Executor must use the trusted adapter, never a parallel selector call')

    def adapter(cfg, current, context, *, evaluate_from=None, prepared_stops=None, **kwargs):
        assert c.locks == ['config', 'machine', 'guard']
        assert current == c.runtime
        assert prepared_stops is c.stopped_receipts[-1]
        c.routing_calls.append(deepcopy(dict(context=context, evaluate_from=evaluate_from, options=kwargs)))
        request = dict(context, **kwargs, evaluate_from=deepcopy(evaluate_from))
        result = dict(schema='ag-routing-ladder/1', evaluation_only=True, evaluate_from=deepcopy(evaluate_from),
            recommendation=dict(cell_id='higher', cluster='default', cores=c.manifest['cores'], target_node=None,
                                eligible=True, needs_queue=False,
                                capacity=dict(availability='enough')))
        result['recommendation'].update(c.choice_changes)
        if c.route_damage == 'no-choice':
            result['recommendation'] = None
        elif c.route_damage == 'queued':
            result['recommendation']['needs_queue'] = True
        elif c.route_damage == 'capacity':
            result['recommendation']['capacity']['availability'] = 'unknown'
        elif c.route_damage == 'ineligible':
            result['recommendation']['eligible'] = False
        elif c.route_damage == 'same-cell':
            result['recommendation']['cell_id'] = 'original'
        elif c.route_damage == 'not-evaluation':
            result['evaluation_only'] = False
        elif c.route_damage == 'source':
            result['evaluate_from']['record_sha256'] = '0' * 64
        return dict(input=dict(request=request, snapshots={}, placements=[dict(evaluate_from)],
                               wakeups=[], selected_at='2026-01-01T00:00:00+00:00', config_sha256='1' * 64),
                    result=result)

    def queue(path, *, ownership_sha256, observation):
        assert not c.locks
        c.queue_calls.append(deepcopy(observation))
        if c.queue_error:
            raise ValueError(c.queue_error)
        instance = evidence.verify_slurm_instance(path, ownership_sha256=ownership_sha256, observation=observation)
        return dict(binding=instance['binding'], ownership_sha256=ownership_sha256, slurm_instance=instance,
                    queued_seconds=21600, checkpoint_free_input={'checkpoint_dependency': False},
                    reroute_authorized=False)

    monkeypatch.setattr(route, 'select_ladder', selector, raising=False)
    monkeypatch.setattr(route, 'autonomous_selection', adapter, raising=False)
    monkeypatch.setattr(route, '_ladder_usage', lambda *args: deepcopy(c.usage), raising=False)
    monkeypatch.setattr(route, 'autonomous_account_job_cap', lambda *args: c.account_job_cap, raising=False)
    monkeypatch.setattr(submit, 'bound_policy', lambda *args: (deepcopy(c.policy), c.rule_hash), raising=False)
    monkeypatch.setattr(ag.autonomy_submission, 'prepare_stopped_reservations', stopped_reservations, raising=False)
    policy_module = SimpleNamespace(check_budget=budget)
    monkeypatch.setitem(sys.modules, 'ag.autonomy_policy', policy_module)
    monkeypatch.setattr(ag, 'autonomy_policy', policy_module, raising=False)
    monkeypatch.setattr(evidence, 'review_reroute_queue', queue)
    monkeypatch.setattr(evidence, '_review_no_progress_locked', lambda *args, **kwargs:
        pytest.fail('Reroute must use formal queue evidence, never a no-progress review'))
    return c


def run_reroute_cancel(c):
    from ag import cancel
    return cancel.autonomous_cancel(c.cfg, c.path, c.transport, **c.context)


def test_reroute_cancel_uses_adapter_twice_and_preserves_complete_route_and_queue_records(reroute_cancel_case):
    c = reroute_cancel_case
    result = run_reroute_cancel(c)
    assert result['outcome'] == 'accepted' and result['stopped'] is False
    assert len(c.routing_calls) == 2 and len(c.queue_calls) == len(c.calls) == len(c.consumed) == 1
    assert len(c.stopped_receipts) == len(c.budget_calls) == 2
    for checked in c.budget_calls:
        assert checked['round_attempts'] == checked['requested_attempts'] == 1
        occupancy = checked['occupancy'][0]
        assert occupancy['committed_cores'] == occupancy['queued_cores'] == c.manifest['cores']
        assert occupancy['requested_cores'] == c.manifest['cores'] and occupancy['jobs'] == 1
    source = dict(study_key=c.record['study_key'], attempt_id=c.path.name, record_sha256=c.owner_hash)
    for call in c.routing_calls:
        assert call['evaluate_from'] == source
        assert call['context']['object_id'] == c.record['object_id']
        assert call['context']['job_class'] == 'small'
        assert 'exclude_ownership' not in call['options']
    request = disk.decode((c.path / result['request']).read_bytes())
    assert set(request['routing_selection']) == {'input', 'result'}
    assert request['routing_selection']['input']['placements'] == [source]
    assert request['reroute_queue']['slurm_instance'] == request['slurm_instance']
    assert request['lineage_sha256'] == c.consumed[0]['lineage_sha256'] == c.owner_hash
    assert 'no_progress' not in request
    assert c.calls[0].text == remote.slurm_cancel_instance(scheduler_cluster='actual', uid=1001,
        job_name=c.path.name, sluid='s0123456789ABC', purpose='reroute').text


@pytest.mark.parametrize('damage', ['no-choice', 'queued', 'capacity', 'ineligible', 'same-cell', 'not-evaluation', 'source'])
def test_reroute_cancel_refuses_incomplete_or_nonimmediate_adapter_results_before_query(reroute_cancel_case, damage):
    c = reroute_cancel_case
    c.route_damage = damage
    with pytest.raises(ValueError, match='strictly higher'):
        run_reroute_cancel(c)
    assert c.captured == c.calls == c.consumed == []
    assert not (c.path / 'autonomy-cancel-request.json').exists()


@pytest.mark.parametrize('damage', ['prior-source', 'consumed-lineage', 'missing-original-class'])
def test_reroute_cancel_refuses_reused_lineage_or_unbound_original_position(reroute_cancel_case, damage):
    c = reroute_cancel_case
    if damage == 'prior-source':
        c.record['reroute_source'] = dict(attempt_id='original-attempt')
    elif damage == 'consumed-lineage':
        c.runtime['reroute_lineages'] = {c.owner_hash: 'another-attempt'}
    else:
        del c.record['selection']['input']['request']['job_class']
    with pytest.raises(ValueError, match='lineage|original verified'):
        run_reroute_cancel(c)
    assert c.routing_calls == c.captured == c.calls == c.consumed == []


def test_reroute_cancel_rechecks_candidate_after_scheduler_observation(reroute_cancel_case):
    c = reroute_cancel_case
    c.after_capture = lambda: setattr(c, 'route_damage', 'no-choice')
    with pytest.raises(ValueError, match='strictly higher'):
        run_reroute_cancel(c)
    assert len(c.captured) == 1 and len(c.routing_calls) == 2
    assert c.calls == c.consumed == []


def test_reroute_cancel_rechecks_actual_original_ownership_after_observation(reroute_cancel_case):
    c = reroute_cancel_case
    c.after_capture = lambda: c.record.update(plan_sha256='0' * 64)
    with pytest.raises(ValueError, match='intact dispatched ownership'):
        run_reroute_cancel(c)
    assert len(c.captured) == 1 and c.calls == c.consumed == []


def test_reroute_cancel_requires_complete_local_queue_proof_before_consumption(reroute_cancel_case):
    c = reroute_cancel_case
    c.queue_error = 'Synthetic checkpoint or never-started evidence failure'
    with pytest.raises(ValueError, match='never-started'):
        run_reroute_cancel(c)
    assert len(c.captured) == 1 and c.calls == c.consumed == []


def test_reroute_cancel_refuses_reviews_and_old_adapter_before_any_query(reroute_cancel_case, monkeypatch):
    from ag import route
    c = reroute_cancel_case
    c.context['reviews'] = []
    with pytest.raises(ValueError, match='formal queue evidence'):
        run_reroute_cancel(c)
    c.context['reviews'] = None
    monkeypatch.setattr(route, 'autonomous_selection', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='T185 exact-source'):
        run_reroute_cancel(c)
    assert c.captured == c.calls == c.consumed == []


@pytest.mark.parametrize('damage', ['cluster', 'template', 'cores', 'walltime', 'node', 'untargeted'])
def test_reroute_cancel_rejects_candidate_outside_effective_policy_before_query(reroute_cancel_case, damage):
    c = reroute_cancel_case
    if damage == 'cluster':
        c.choice_changes['cluster'] = 'unapproved'
    elif damage == 'template':
        c.policy['templates'] = ['xtb']
    elif damage == 'cores':
        c.policy['max_cores_per_job'] = c.manifest['cores'] - 1
    elif damage == 'walltime':
        c.policy['max_walltime'] = '00:00:01'
    elif damage == 'node':
        c.policy['clusters']['default']['nodes'] = ['allowed']
        c.choice_changes['target_node'] = 'not-allowed'
    else:
        c.policy['clusters']['default']['nodes'] = ['must-target']
    with pytest.raises(ValueError, match='policy'):
        run_reroute_cancel(c)
    assert c.captured == c.calls == c.consumed == c.budget_calls == []


@pytest.mark.parametrize('stage', ['before-query', 'after-query'])
@pytest.mark.parametrize('limit', ['policy', 'routing-account', 'pause-after-consumption'])
def test_reroute_cancel_requires_actual_policy_budget_at_both_boundaries(reroute_cancel_case, stage, limit):
    c = reroute_cancel_case
    def exhausted():
        if limit == 'policy':
            c.budget_error = 'Shared-account autonomous limit exceeded: max_jobs'
        elif limit == 'routing-account':
            c.account_job_cap = 1  # Immediate empty/free cells still share the existing routing cap.
        else:
            c.pause_after_consumption = True
    if stage == 'before-query':
        exhausted()
    else:
        c.after_capture = exhausted
    with pytest.raises(ValueError, match='limit exceeded|would pause'):
        run_reroute_cancel(c)
    assert len(c.captured) == int(stage == 'after-query') and c.calls == c.consumed == []
    if limit == 'policy':
        assert c.budget_calls[-1]['occupancy'][0]['jobs'] == 1  # The original remains charged.


def test_executor_rechecks_expiry_after_unlocked_initial_review_before_query(autonomous_cancel_case, monkeypatch):
    from ag import cancel, submit
    c = autonomous_cancel_case
    def bound_policy(*args):
        if c.now >= c.run_until:
            raise ValueError('Effective rule expired during unlocked review')
        return {}, c.rule_hash
    def receipt_hook():
        if not c.locks:
            c.now = c.run_until
    c.receipt_hook = receipt_hook
    monkeypatch.setattr(submit, 'bound_policy', bound_policy)
    with pytest.raises(ValueError, match='expired during unlocked'):
        cancel.autonomous_cancel(c.cfg, c.path, c.transport, **c.context)
    assert c.captured == c.calls == c.consumed == []


def test_executor_rechecks_snapshot_journal_position_after_unlocked_review(autonomous_cancel_case, monkeypatch):
    from ag import cancel
    c = autonomous_cancel_case
    original_guard, review = a._cancellation_guard, evidence._review_no_progress_locked
    changed = [False]
    @contextmanager
    def guard(*args, **kwargs):
        with original_guard(*args, **kwargs) as held:
            class CurrentGuard:
                def __getattr__(self, name):
                    return getattr(held, name)
                @property
                def current(self):
                    return dict(held.current, seq=held.current['seq'] + int(changed[0]))
            yield CurrentGuard()
    def reviewed(*args, **kwargs):
        result = review(*args, **kwargs)
        changed[0] = True
        return result
    monkeypatch.setattr(a, '_cancellation_guard', guard)
    monkeypatch.setattr(evidence, '_review_no_progress_locked', reviewed)
    with pytest.raises(ValueError, match='journal changed during unlocked'):
        cancel.autonomous_cancel(c.cfg, c.path, c.transport, **c.context)
    assert c.captured == c.calls == c.consumed == []


def test_executor_rejects_new_input_after_final_unlocked_proof(autonomous_cancel_case):
    from ag import cancel
    c = autonomous_cancel_case
    def receipt_hook():
        if not c.locks and c.captured:
            (c.path / 'inputs' / 'late.chk').write_bytes(b'synthetic late dependency')
    c.receipt_hook = receipt_hook
    with pytest.raises(ValueError, match='Directory changed'):
        cancel.autonomous_cancel(c.cfg, c.path, c.transport, **c.context)
    assert len(c.captured) == 1 and c.calls == c.consumed == []
    assert not (c.path / 'autonomy-cancel-request.json').exists()


def test_executor_uses_new_receipt_after_its_own_observation_publication(autonomous_cancel_case):
    from ag import cancel
    c = autonomous_cancel_case
    def publish_observation():
        assert not c.locks
        directory = c.path / 'scheduler-observations' / 'new-formal-observation'
        directory.mkdir(parents=True)
        (directory / 'observation.json').write_bytes(b'{}\n')
    c.after_capture = publish_observation
    result = cancel.autonomous_cancel(c.cfg, c.path, c.transport, **c.context)
    assert result['outcome'] == 'accepted' and len(c.calls) == len(c.consumed) == 1


@pytest.fixture
def real_autonomous_cancel_pipeline(cfg, tmp_path, monkeypatch):
    """Real T185/T186/T187 APIs; only external IO, time and identity are fake.

    Standalone T187 deliberately skips this combination test. It never imports
    copied upstream implementation or touches the developer's machine registry.
    """
    import base64
    import inspect
    from datetime import timezone
    from hashlib import sha256
    from pathlib import Path
    from types import SimpleNamespace
    from ag import cancel, route, submit
    from test_core import Fake as BaseFake, INPUT
    from test_slurm import EVIDENCE_CONFIG, EVIDENCE_JOB, EVIDENCE_HISTORY

    home = tmp_path / 'isolated-integration-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setattr(SSHTransport, '_execute', lambda *args, **kwargs: pytest.fail('Real SSH is forbidden'))
    try:
        from ag import autonomy_submission as ownership, autonomy_policy
    except ImportError:
        pytest.skip('Requires the actual integrated T185 selector and T186 ownership/submission APIs')
    required = [(route, 'select_ladder'), (route, 'autonomous_selection'),
                (submit, 'prepare_autonomous'), (ownership, 'prepare_reroute_evidence'),
                (ownership, 'prepare_stopped_reservations'), (a, 'submission_guard')]
    if (any(not callable(getattr(module, name, None)) for module, name in required)
            or 'evaluate_from' not in inspect.signature(route.select_ladder).parameters):
        pytest.skip('Requires the final actual T185 evaluate_from and T186 stopped-successor APIs')
    from ag import confirm
    monkeypatch.setattr(confirm, 'confirm', lambda *args: pytest.fail('Autonomy must not fall back to manual approval'))
    monkeypatch.setattr(config, 'ssh_identity', lambda selected: ('synthetic-controller', 22, 'fixture'))
    clock = [datetime(2026, 10, 29, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(a, 'now', lambda: clock[0])
    monkeypatch.setattr(a, 'versions', lambda: deepcopy(VERSIONS))
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock[0], tz=tz)
    monkeypatch.setattr(snapshot, 'datetime', Clock)

    def scalar(value):
        if isinstance(value, dict):
            return '{' + ', '.join(json.dumps(k) + ' = ' + scalar(v) for k, v in value.items()) + '}'
        if isinstance(value, list):
            return '[' + ', '.join(scalar(v) for v in value) + ']'
        return json.dumps(value)

    entry = {k: deepcopy(v) for k, v in cfg.items() if k != 'local' and not k.startswith('_')}
    entry.update(scheduler='slurm', account='fixture', qos='fixture')
    entry['resources'].update(max_committed_cores=128, max_queued_cores=128, max_walltime='12:00:00')
    entries = {name: dict(deepcopy(entry), partition=name) for name in ('default', 'batch')}
    local = dict(local=deepcopy(cfg['local']), _config_dir=cfg['_config_dir'], clusters=entries,
                 routing=dict(gaussian=['default', 'batch'], ladder=[dict(
                     id='higher' if name == 'default' else 'source', cluster=name, tier='simple',
                     classes=['small'], condition='free', min_free_cores=8, max_placements=1)
                     for name in ('default', 'batch')]), approval={'autonomous_policies': {}})
    env = SimpleNamespace(cfg=local, clock=clock, owners=[], ownership=ownership, cancel=cancel, submit=submit)

    def persist():
        target = Path(env.cfg['_config_dir']) / 'config.toml'
        target.write_text('\n'.join(json.dumps(k) + ' = ' + scalar(v) for k, v in env.cfg.items()
                                   if not k.startswith('_')) + '\n')
        env.cfg = config.load_config(target)

    def monitors(*, higher_ready):
        for name in ('default', 'batch'):
            idle = 128 if name == 'batch' or higher_ready else 0
            data = dict(schema='ag-monitor/1', ok=True, sampled_at=Clock.now(timezone.utc).isoformat(),
                interval_seconds=60, own=dict(cores_in_use=0, cores_running=0, cores_queued=0, jobs=[]),
                cluster=dict(name=name, scheduler='slurm', job_summary=dict(others_queued_jobs=0), nodes=[
                    dict(name='node-' + name, state='idle' if idle else 'allocated', partition=name,
                         partition_state='up', cores_total=128, cores_used=128-idle, cores_idle=idle,
                         cores_other=0, mem_total_gb=120, mem_assigned_gb=0, capacity_cpu_consistent=True)]))
            root = Path(env.cfg['local']['studies_root']) / '.ag-monitor' / name
            root.mkdir(parents=True, exist_ok=True)
            (root / 'latest.json').write_text(json.dumps(data))

    def stamp(at):
        return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    class Scheduler(BaseFake):
        def __init__(self, owner):
            super().__init__(config.select_cluster(env.cfg, owner.manifest['cluster']))
            self.owner, self.phase, self.was_running = owner, 'PENDING', False
            self.qsub = Result(stdout=owner.job + ';fixture\n')
            self.cancel_result, self.cancel_calls = Result(), 0
            self.record_paths, self.submitted_at, self.ended_at = [], None, None

        def for_cluster(self, selected):
            assert selected['_cluster'] == self.owner.manifest['cluster']
            assert selected['ssh'] == self.cfg['ssh'] and selected['remote'] == self.cfg['remote']
            self.cfg = selected
            return self

        def record_to(self, paths):
            self.record_paths = list(paths)

        def run(self, command):
            import fcntl
            for lock in [Path(self.cfg['_config_dir']) / 'submit.lock',
                         home / '.config/ag/autonomy-submit.lock',
                         self.owner.path.parent.parent / 'autonomy/store.lock']:
                if lock.exists():
                    with lock.open('rb') as stream:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(stream, fcntl.LOCK_UN)
            clock[0] += .25
            op = command.operation
            if op == 'submit':
                self.submitted_at = int(clock[0])
            if op in ('slurm_jobs', 'slurm_accounting', 'slurm_history', 'slurm_find'):
                self.calls.append(command)
                return Result()
            if not (op.startswith('slurm_evidence_') or op in ('cancel', 'output_observation')):
                return super().run(command)
            self.calls.append(command)
            if op == 'cancel':
                self.cancel_calls += 1
                self.ended_at = int(clock[0])
                return self.cancel_result
            if op == 'output_observation':
                data = b' SCF Done: E(RB3LYP) = -76.000000 A.U.\n Step number 2 out of 20\n'
                return Result(stdout=f'{len(data)}\n{int(clock[0])}\n' + base64.b64encode(data).decode() + '\n')
            if op == 'slurm_evidence_config':
                return Result(stdout=EVIDENCE_CONFIG)
            if op == 'slurm_evidence_version':
                return Result(stdout='slurm 26.05.5\n')
            assert self.submitted_at is not None
            value = EVIDENCE_JOB if op == 'slurm_evidence_job' else EVIDENCE_HISTORY
            value = (value.replace('water-001-sp', self.owner.path.name)
                     .replace('JobId=123 ', 'JobId=' + self.owner.job + ' ')
                     .replace('|123|', '|' + self.owner.job + '|')
                     .replace('s0123456789ABC', self.owner.sluid)
                     .replace('38390726480144748', str(self.owner.db_index))
                     .replace('2026-01-01T00:00:00', stamp(self.submitted_at))
                     .replace('PENDING', self.phase))
            if self.phase == 'RUNNING':
                self.was_running = True
            if self.phase != 'PENDING':
                start = stamp(self.submitted_at + 1) if self.was_running else stamp(self.ended_at)
                end = stamp(self.ended_at) if self.phase == 'CANCELLED' else 'Unknown'
                value = (value.replace('StartTime=Unknown', 'StartTime=' + start)
                         .replace('EndTime=Unknown', 'EndTime=' + end)
                         .replace('|Unknown|Unknown|', '|' + start + '|' + end + '|'))
                if self.was_running:
                    value = value.replace('RunTime=00:00:00', 'RunTime=01:00:00')
            return Result(stdout=value)

    def owner(name='smoke', *, allowed=('default', 'batch'), committed=128, account_job_cap=None, max_jobs=4):
        from ag import study, slurm
        if account_job_cap is not None:
            env.cfg['routing']['ladder'].append(dict(id='account-job-cap', cluster='default', tier='simple',
                classes=['small'], condition='jobs', max_jobs=account_job_cap, max_placements=1))
        persist()
        study.init(env.cfg, name)
        source = tmp_path / ('water-' + name + '.gjf')
        route_text = '# B3LYP/6-31G(d) Opt=Tight Freq Int=UltraFine SCF=(XQC,Conver=8)'
        source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', route_text))
        manifest = attempt.prepare(env.cfg, study_name=name, template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='optfreq', cluster='batch',
            method_basis='Synthetic strict water fixture')
        path = attempt.find(env.cfg, manifest['attempt_id'])
        policy_name = 'bounded-' + name
        policy = dict(schema=autonomy_policy.SCHEMA, study_id=name,
            study_key=ownership.study_identity(path.parent.parent)['study_key'], round_id='pending-round',
            plan_sha256='a'*64, routing_sha256=route.ladder_config_identity(env.cfg),
            templates=['gaussian'], max_cores_per_job=8, max_walltime='01:00:00', max_attempts=10,
            expires_at=Clock.fromtimestamp(clock[0]+86400, timezone.utc).isoformat(),
            quote='Synthetic explicit plan-bound authorization',
            set_at=Clock.fromtimestamp(clock[0]-1, timezone.utc).isoformat(), allow_relaxed=False,
            clusters={n: dict(nodes=[], max_committed_cores=committed, max_queued_cores=committed, max_jobs=max_jobs)
                      for n in allowed}, methods={'gaussian': [dict(method='rb3lyp', basis='6-31g(d)',
                basis_function_type='basis_default', dispersion='method_default', solvent_model='none',
                solvent='none', integration_grid='ultrafine', opt_convergence='tight', scf_convergence=8)]})
        a.initialize(env.cfg, name)
        plan = a.create_plan(env.cfg, name, spec(valid_until=clock[0]+86400,
            submission_policy={k: deepcopy(policy[k]) for k in autonomy_policy.PLAN_BOUND_KEYS}))
        a.confirm(env.cfg, name, plan['plan_id'], plan['sha256'], 'Synthetic immutable plan confirmation')
        begun = a.begin(env.cfg, name, plan['plan_id'], 'Synthetic explicit round confirmation')
        run = a.start(env.cfg, name, plan['plan_id'], name + '-submit-wake')
        policy.update(round_id=begun['state']['current_round'], plan_sha256=plan['sha256'])
        env.cfg['approval']['autonomous_policies'][policy_name] = policy
        persist()
        index = len(env.owners)
        sluid = 's0123456789AB' + 'CDEFGHJKMNPQRSTVWXYZ'[index]
        value = SimpleNamespace(path=path, manifest=manifest, input_name=source.name, plan=plan, run=run, policy_name=policy_name,
            job=str(123+index), sluid=sluid, db_index=slurm._evidence_sluid_number(sluid), reviews=None)
        value.context = dict(run_id=run['run_id'], token=run['token'], plan_sha256=plan['sha256'],
                             policy_name=policy_name, object_id='water', job_class='small')
        value.fake = Scheduler(value)
        env.owners.append(value)
        monitors(higher_ready=False)
        result = submit.submit(env.cfg, [path.name], value.fake, autonomous=value.context)
        assert result[0]['state'] == 'submitted'
        assert disk.decode((path / 'slurm-origin.json').read_bytes())['initial_instance_recorded'] is True
        assert len(disk.decode((path / 'slurm-origin-probe.json').read_bytes())['queries']) == 5
        return value

    def next_wake(value, *, wait=21601):
        a.change(env.cfg, value.path.parent.parent.name, 'finish', value.run['run_id'], value.run['token'],
                 reason='Synthetic wake complete')
        clock[0] += wait
        value.run = a.start(env.cfg, value.path.parent.parent.name, value.plan['plan_id'], 'next-wake')
        value.context.update(run_id=value.run['run_id'], token=value.run['token'])
        monitors(higher_ready=True)

    def cancel_owned(value, kind='reroute'):
        return cancel.autonomous_cancel(env.cfg, value.path, value.fake,
            run_id=value.run['run_id'], token=value.run['token'], plan_sha256=value.plan['sha256'],
            policy_name=value.policy_name, kind=kind, reason='Synthetic independently reviewed reason',
            reviews=value.reviews)

    def stopped(value):
        value.fake.phase = 'CANCELLED'
        clock[0] += 1
        return cancel.verify_stopped(env.cfg, value.path, value.fake,
            run_id=value.run['run_id'], token=value.run['token'], plan_sha256=value.plan['sha256'])

    def other_stopped():
        value = owner('other')
        state.write(value.path, 'running')
        value.fake.phase = 'RUNNING'
        value.reviews = []
        for _ in range(2):
            next_wake(value, wait=10800)
            captured = snapshot.capture_for_run(env.cfg, value.path, value.fake,
                run_id=value.run['run_id'], token=value.run['token'], plan_sha256=value.plan['sha256'])
            value.reviews.append(review(captured))
        assert cancel_owned(value, 'no_progress')['outcome'] == 'accepted'
        assert stopped(value)['stopped'] is True
        a.change(env.cfg, 'other', 'finish', value.run['run_id'], value.run['token'], reason='Synthetic other study observed')
        return value

    def placements():
        prepared = ownership.prepare_stopped_reservations(env.cfg)
        with ownership.machine_lock(create=False):
            return ownership.read_reservations(env.cfg, prepared_stops=prepared)['placements']

    def successor(value):
        monitors(higher_ready=True)
        context = dict(value.context, reroute_source=value.path.name)
        input_name = value.input_name
        options = dict(template='gaussian', input_path=value.path / 'inputs' / input_name,
            walltime=value.manifest['walltime'], label='reroute',
            method_basis=value.manifest['science']['method_basis'])
        manifest = submit.prepare_autonomous(env.cfg, study_name=value.path.parent.parent.name,
                                             context=context, options=options)
        new_path = attempt.find(env.cfg, manifest['attempt_id'])
        index = len(env.owners)
        sluid = 's0123456789AB' + 'CDEFGHJKMNPQRSTVWXYZ'[index]
        from ag import slurm
        result = SimpleNamespace(path=new_path, manifest=manifest, input_name=input_name, plan=value.plan, run=value.run,
            policy_name=value.policy_name, context=context, job=str(123+index), sluid=sluid,
            db_index=slurm._evidence_sluid_number(sluid), reviews=None)
        result.fake = Scheduler(result)
        env.owners.append(result)
        monitors(higher_ready=True)
        submit.submit(env.cfg, [new_path.name], result.fake, autonomous=context)
        return result

    def additional_submissions(value, count):
        from ag import slurm
        for index in range(count):
            next_wake(value, wait=1)
            context = dict(value.context, object_id='background-' + str(index))
            options = dict(template='gaussian', input_path=value.path / 'inputs' / value.input_name,
                walltime=value.manifest['walltime'], label='background-' + str(index),
                method_basis=value.manifest['science']['method_basis'])
            manifest = submit.prepare_autonomous(env.cfg, study_name=value.path.parent.parent.name,
                                                 context=context, options=options)
            path = attempt.find(env.cfg, manifest['attempt_id'])
            number = len(env.owners)
            sluid = 's0123456789AB' + 'CDEFGHJKMNPQRSTVWXYZ'[number]
            current = SimpleNamespace(path=path, manifest=manifest, input_name=value.input_name,
                plan=value.plan, run=value.run, policy_name=value.policy_name, context=context,
                job=str(123+number), sluid=sluid, db_index=slurm._evidence_sluid_number(sluid), reviews=None)
            current.fake = Scheduler(current)
            env.owners.append(current)
            submit.submit(env.cfg, [path.name], current.fake, autonomous=context)

    env.additional_submissions = additional_submissions
    env.owner, env.next_wake, env.cancel_owned = owner, next_wake, cancel_owned
    env.stopped, env.other_stopped, env.placements, env.successor = stopped, other_stopped, placements, successor
    return env


def test_real_reroute_stop_successor_with_other_stopped_study(real_autonomous_cancel_pipeline):
    env = real_autonomous_cancel_pipeline
    other = env.other_stopped()
    source = env.owner()
    env.next_wake(source)
    assert env.cancel_owned(source)['outcome'] == 'accepted'
    assert env.stopped(source)['stopped'] is True
    successor = env.successor(source)
    assert successor.manifest['cluster'] == 'default' and source.manifest['cluster'] == 'batch'
    assert successor.manifest['reroute_source']['attempt_id'] == source.path.name
    current = a.status(env.cfg, 'smoke')['state']
    ownership_sha = current['submissions'][source.path.name]['ownership_sha256']
    assert current['reroute_lineages'][ownership_sha] == source.path.name
    assert current['cancellations'][source.path.name]['lineage_sha256'] == ownership_sha
    assert len(current['submissions']) == 2 and source.fake.cancel_calls == 1
    assert sum(c.operation == 'submit' for c in successor.fake.calls) == 1
    assert any(p['attempt_id'] == other.path.name and p['state'] == 'finished' for p in env.placements())
    with pytest.raises((ValueError, FileNotFoundError)):
        env.successor(source)
    env.next_wake(successor)
    with pytest.raises(ValueError):
        env.cancel_owned(successor)
    assert successor.fake.cancel_calls == 0


@pytest.mark.parametrize('case', ['candidate-outside-policy', 'old-occupation-counts', 'candidate-account-job-limit'])
def test_real_reroute_candidate_policy_is_checked_before_cancel(real_autonomous_cancel_pipeline, case):
    env = real_autonomous_cancel_pipeline
    source = env.owner(allowed=('batch',) if case == 'candidate-outside-policy' else ('default', 'batch'),
                       committed=8 if case == 'old-occupation-counts' else 128,
                       account_job_cap=1 if case == 'candidate-account-job-limit' else None)
    env.next_wake(source)
    with pytest.raises(ValueError):
        env.cancel_owned(source)
    assert source.fake.cancel_calls == 0 and not (source.path / '.cancel-claim').exists()
    assert not a.status(env.cfg, 'smoke')['state'].get('cancellations')


@pytest.mark.parametrize('outcome', ['accepted-without-stop', 'unknown'])
def test_real_reroute_unstopped_source_keeps_occupation(real_autonomous_cancel_pipeline, outcome):
    env = real_autonomous_cancel_pipeline
    source = env.owner()
    env.next_wake(source)
    if outcome == 'unknown':
        source.fake.cancel_result = Result(255, 'Synthetic lost response', 'Synthetic connection lost')
        with pytest.raises(env.cancel.AutonomousCancellationUnknown):
            env.cancel_owned(source)
    else:
        assert env.cancel_owned(source)['outcome'] == 'accepted'
    assert not (source.path / 'autonomy-cancel-stopped.json').exists()
    rows = env.placements()
    assert any(p['attempt_id'] == source.path.name and p['state'] != 'finished' for p in rows)
    before = set(source.path.parent.iterdir())
    with pytest.raises((ValueError, FileNotFoundError)):
        env.successor(source)
    assert set(source.path.parent.iterdir()) == before and source.fake.cancel_calls == 1


def test_real_reroute_ninety_percent_consumption_pause_refuses_cancel(real_autonomous_cancel_pipeline):
    env = real_autonomous_cancel_pipeline
    source = env.owner(max_jobs=20)
    env.additional_submissions(source, 7)
    current = a.status(env.cfg, 'smoke')['state']
    assert len(current['submissions']) == 8
    assert all(item['dispatch_started'] is not None for item in current['submissions'].values())
    env.next_wake(source)
    with pytest.raises(ValueError, match='would pause at its submission consumption'):
        env.cancel_owned(source)
    assert source.fake.cancel_calls == 0 and not (source.path / '.cancel-claim').exists()
    assert not a.status(env.cfg, 'smoke')['state'].get('cancellations')
