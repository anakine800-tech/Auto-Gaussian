"""Formal cancellation evidence, using synthetic studies and fake transport."""
from copy import deepcopy
from datetime import datetime
import json
import os

import pytest

from ag import attempt, autonomy as a, autonomy_cancel as evidence, cli, snapshot, state, submission
from ag import _autonomy_store as disk
from ag.transport import TransportError
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
    assert len(list((path / 'snapshots').iterdir())) == 1
    assert not a.status(cfg, path.parent.parent.name)['state'].get('snapshots')


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
