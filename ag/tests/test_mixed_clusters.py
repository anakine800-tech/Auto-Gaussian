"""Mixed local history must not confuse same-number PBS and Slurm jobs."""
import json

import pytest

from ag import attempt, budget, config, monitor, status, submission, submit
from ag.transport import Result
from test_core import cfg, Fake
from test_slurm import multi, prepare, SlurmFake
from test_monitor import QUEUES, job


@pytest.fixture
def mixed(multi, tmp_path):
    records = {}
    for label, cluster, raw in [('legacy', 'default', '101.fixture'),
                                ('pbs', 'default', '123.fixture'),
                                ('slurm', 'batch', '123')]:
        path, m = prepare(multi, tmp_path, cluster, label)
        if label == 'legacy':
            del m['cluster'], m['scheduler']
            (path / 'manifest.json').write_text(json.dumps(m))
            identity = raw
        else:
            submission.record(path, m, raw)
            identity = submission.qualified(m, raw)
        (path / 'status.json').write_text(json.dumps(dict(state='submitted', job_id=identity)))
        records[label] = (path, m)
    selected = config.select_cluster(multi, 'batch')
    path, m = records['slurm']
    budget.reserve(selected, m, dict(cluster='batch', attempts={}))
    (path / '.submit-claim').touch()
    return multi, records


class PBSFake(Fake):
    def run(self, command):
        if command.operation in ('queues', 'nodes'):
            self.calls.append(command)
            return Result(stdout=QUEUES if command.operation == 'queues' else 'node-a\n     state = free\n     np = 44\n')
        return super().run(command)


def scheduler(multi, cluster):
    selected = config.select_cluster(multi, cluster)
    if cluster == 'default':
        fake = PBSFake(selected)
        fake.qstat = Result(stdout=job('101.fixture') + job('123.fixture') + job('199.fixture', cores='1:ppn=4'))
    else:
        fake = SlurmFake(selected)
        fake.queue = Result(stdout='123|water-003-slurm|fixture|RUNNING|8|00:00|fixture\n199|external|fixture|PENDING|4|00:00|fixture\n')
    return selected, fake


@pytest.mark.parametrize('cluster,expected,labels', [('default', 20, ('legacy', 'pbs')),
                                                   ('batch', 12, ('slurm',))])
def test_monitor_and_submit_accounting(mixed, tmp_path, monkeypatch, capsys, cluster, expected, labels):
    multi, records = mixed
    selected, fake = scheduler(multi, cluster)
    result = monitor.observation(selected, fake, 'fixture')
    assert result['own']['cores_in_use'] == expected
    assert {r['attempt'] for r in result['own']['jobs'] if r['attempt']} == {records[k][0].name for k in labels}
    assert not result['warnings']
    assert status.inventory(fake, selected)[2] == expected
    assert {r['attempt_id'] for r in attempt.all_attempts(selected)} == {records[k][0].name for k in labels}
    target, _ = prepare(multi, tmp_path, cluster, 'next')
    monkeypatch.setattr('ag.confirm.confirm', lambda _: False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(multi, [target.name], fake)
    assert f'当前占用 {expected} 核' in capsys.readouterr().err
    assert not (target / '.submit-claim').exists()
    assert 'submit' not in fake.operations()


@pytest.mark.parametrize('cluster', ['default', 'batch'])
@pytest.mark.parametrize('damage', ['manifest-json', 'missing-manifest', 'cluster', 'scheduler',
                                   'status-json', 'job-format', 'job-prefix', 'submission'])
def test_damaged_attempt_identified_before_confirmation(mixed, tmp_path, monkeypatch, cluster, damage):
    multi, _ = mixed
    damaged, m = prepare(multi, tmp_path, cluster, 'broken')
    target, _ = prepare(multi, tmp_path, cluster, 'next')
    if damage == 'manifest-json':
        (damaged / 'manifest.json').write_text('{')
    elif damage == 'missing-manifest':
        (damaged / 'manifest.json').unlink()
    elif damage in ('cluster', 'scheduler'):
        m[damage] = None
        (damaged / 'manifest.json').write_text(json.dumps(m))
    elif damage == 'status-json':
        (damaged / 'status.json').write_text('{')
    elif damage == 'submission':
        (damaged / 'submission.json').write_text('{')
    else:
        value = cluster + ':bad-id' if damage == 'job-format' else 'other:123'
        (damaged / 'status.json').write_text(json.dumps(dict(state='submitted', job_id=value)))
    selected, fake = scheduler(multi, cluster)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    snapshot = monitor.sample(selected, fake)
    assert not snapshot['ok'] and damaged.name in snapshot['error']
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('damage must fail before confirmation'))
    with pytest.raises(ValueError, match=damaged.name):
        submit.submit(multi, [target.name], fake)
    assert not (target / '.submit-claim').exists()
    assert 'submit' not in fake.operations()
    fake.calls.clear()
    with pytest.raises(ValueError, match=damaged.name):
        status.check(multi, damaged, fake)
    assert not fake.calls


@pytest.mark.parametrize('cluster,foreign', [('default', 'slurm'), ('batch', 'pbs')])
def test_foreign_status_is_not_read(mixed, cluster, foreign):
    multi, records = mixed
    path, _ = records[foreign]
    (path / 'status.json').write_text('{')
    (path / 'submission.json').write_text('{')
    selected, fake = scheduler(multi, cluster)
    assert monitor.observation(selected, fake, 'fixture')['own']['cores_in_use'] in (12, 20)
    status.inventory(fake, selected)
    if cluster == 'batch':
        assert budget.totals(selected) == (0, 12 * 3600)
        assert budget.unobserved_cores(selected, [], budget.read(selected)) == 8


def test_budget_only_counts_own_unobserved_reservation(mixed):
    multi, records = mixed
    cfg = config.select_cluster(multi, 'batch')
    ledger = budget.read(cfg)
    assert budget.unobserved_cores(cfg, [], ledger) == 8
    assert budget.unobserved_cores(cfg, [{'job_id': '123', 'name': records['slurm'][0].name}], ledger) == 0
    # A foreign entry cannot turn a same-number PBS job into held Slurm cores.
    path, m = records['pbs']
    ledger['attempts'][path.name] = dict(state='reserved', used=0, reserved=1, bundle_sha256=m['bundle_sha256'])
    with pytest.raises(ValueError, match='cluster mismatch'):
        budget.unobserved_cores(cfg, [], ledger)
    del ledger['attempts'][path.name]
    path, _ = records['slurm']
    (path / 'status.json').write_text('{')
    with pytest.raises(ValueError, match=path.name):
        budget.unobserved_cores(cfg, [], ledger)
    with pytest.raises(ValueError, match=path.name):
        budget.read(cfg)


def test_missing_ledger_reports_attempt(mixed):
    multi, records = mixed
    cfg = config.select_cluster(multi, 'batch')
    budget.ledger_path(cfg).unlink()
    with pytest.raises(ValueError, match=records['slurm'][0].name):
        budget.read(cfg)


@pytest.mark.parametrize('manifest,value,expected', [
    ({}, '123.fixture', '123.fixture'),
    ({'cluster': 'default', 'scheduler': 'pbs'}, '123.fixture', '123.fixture'),
    ({'cluster': 'pbs-two', 'scheduler': 'pbs'}, 'pbs-two:123.fixture', '123.fixture'),
    ({'cluster': 'batch', 'scheduler': 'slurm'}, 'batch:123', '123'),
])
def test_scheduler_specific_identity(manifest, value, expected):
    assert submission.raw_job(manifest, value) == expected


@pytest.mark.parametrize('manifest,value', [
    ({}, 'batch:123'),
    ({'cluster': 'batch', 'scheduler': 'slurm'}, '123'),
    ({'cluster': 'batch', 'scheduler': 'slurm'}, 'batch:123.fixture'),
    ({'cluster': 'pbs-two', 'scheduler': 'pbs'}, '123.fixture'),
])
def test_ambiguous_identity_is_not_reinterpreted(manifest, value):
    with pytest.raises(ValueError):
        submission.raw_job(manifest, value)


def test_multicluster_monitor_keeps_failure_in_own_snapshot(mixed, monkeypatch, capsys):
    multi, records = mixed
    path, _ = records['slurm']
    (path / 'status.json').write_text('{')
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    monkeypatch.setattr(monitor, 'SSHTransport',
                        lambda cfg, **_: scheduler(multi, cfg['_cluster'])[1])
    assert monitor.run_clusters(multi) == 2
    snapshots = json.loads(capsys.readouterr().out)['clusters']
    assert snapshots['default']['ok']
    assert not snapshots['batch']['ok']
    assert path.name in snapshots['batch']['error']


def test_unconfigured_cluster_reports_attempt(mixed):
    multi, records = mixed
    del multi['clusters']['batch']
    with pytest.raises(ValueError, match=records['slurm'][0].name):
        monitor.run_clusters(multi)


def test_submission_recovers_identity_for_unknown_accounting(mixed):
    multi, records = mixed
    path, _ = records['slurm']
    (path / 'status.json').write_text(json.dumps(dict(state='unknown', job_id=None)))
    cfg, fake = scheduler(multi, 'batch')
    assert monitor.observation(cfg, fake, 'fixture')['own']['jobs'][0]['attempt'] == path.name
    assert budget.unobserved_cores(cfg, [{'job_id': '123', 'name': path.name}], budget.read(cfg)) == 0
    assert budget.unobserved_cores(cfg, [], budget.read(cfg)) == 8


def test_named_pbs_cluster_does_not_inherit_legacy_jobs(mixed, tmp_path):
    from copy import deepcopy
    multi, records = mixed
    multi['clusters']['pbs-two'] = deepcopy(multi['clusters']['default'])
    path, m = prepare(multi, tmp_path, 'pbs-two', 'other-pbs')
    submission.record(path, m, '101.fixture')
    (path / 'status.json').write_text(json.dumps(dict(state='submitted', job_id='pbs-two:101.fixture')))
    cfg = config.select_cluster(multi, 'pbs-two')
    fake = PBSFake(cfg)
    fake.qstat = Result(stdout=job('101.fixture'))
    result = monitor.observation(cfg, fake, 'fixture')
    assert result['own']['cores_in_use'] == 8
    assert result['own']['jobs'][0]['attempt'] == path.name
    assert not result['warnings']
    assert status.inventory(fake, cfg)[2] == 8


def test_missing_binding_cannot_free_reserved_cores(mixed):
    multi, records = mixed
    path, _ = records['slurm']
    cfg = config.select_cluster(multi, 'batch')
    ledger = budget.read(cfg)
    (path / 'submission.json').unlink()
    with pytest.raises(ValueError, match=path.name):
        budget.unobserved_cores(cfg, [{'job_id': '123'}], ledger)


def test_unknown_cluster_record_fails_both_cluster_scans(mixed):
    multi, records = mixed
    path, m = records['pbs']
    m['cluster'] = None
    (path / 'manifest.json').write_text(json.dumps(m))
    for cluster in ('default', 'batch'):
        cfg, fake = scheduler(multi, cluster)
        with pytest.raises(ValueError, match=path.name):
            monitor.observation(cfg, fake, 'fixture')
        with pytest.raises(ValueError, match=path.name):
            status.inventory(fake, cfg)
