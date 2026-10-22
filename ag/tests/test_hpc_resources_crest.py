"""T106: synthetic admission boundaries and independent executable selection."""
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import shlex
import subprocess

import pytest
from ag import attempt, clusters, config, confirm, doctor, monitor, remote, render, state, study, submit
from ag.transport import Result, TransportError, SSHConnectionError, SSHTransport
from test_core import cfg, prepared, write_config, job_text
from test_queue import QueueFake, prepare_batch
from test_slurm import multi, prepare, SlurmFake
from test_shared_cluster_caps import shared, reserve, row
from test_monitor import Fake as MonitorFake


def limits(resources):
    resources.update(max_cores=48, max_committed_cores=288,
                     max_queued_cores=216, scheduler_max_running_cores=72)


def test_new_limits_and_tier_mapping(cfg):
    limits(cfg['resources'])
    for tier, cores, mem in zip(cfg['resources']['tiers'].values(), (8, 16, 24, 36), (8, 16, 64, 120)):
        tier.update(cores=cores, mem_gb=mem)
    loaded = config.load_config(write_config(cfg))
    assert loaded['resources'] == cfg['resources']
    loaded['resources']['tiers']['complex']['cores'] = 49
    with pytest.raises(ValueError, match='Invalid resource tier'):
        config.validate_cluster(loaded)


@pytest.mark.parametrize('key', ['max_cores', 'max_queued_cores', 'scheduler_max_running_cores'])
@pytest.mark.parametrize('value', [True, 0, -1, 48.0, '48'])
def test_invalid_caps(cfg, key, value):
    limits(cfg['resources'])
    cfg['resources'][key] = value
    with pytest.raises(ValueError, match=key):
        config.load_config(write_config(cfg))


@pytest.mark.parametrize('value', ['', 'relative/crest', '/fixture/../crest', '/fixture/crest;bad',
                                   '/fixture/$(bad)', '/fixture/crest\n', '/', None])
def test_independent_crest_rejects_unsafe_path(cfg, value):
    cfg['programs']['crest'] = {'executable': value}
    with pytest.raises(ValueError):
        config.load_config(write_config(cfg))


@pytest.mark.parametrize('value', [None, '/fixture/crest', {}, {'root': '/fixture'},
                                   {'executable': '/fixture/crest', 'args': '--evil'}])
def test_independent_crest_requires_exact_table(cfg, value):
    cfg['programs']['crest'] = value
    with pytest.raises(ValueError, match='programs.crest'):
        config.validate_cluster(cfg)


def queue_text(scheduler, running, queued):
    if scheduler == 'pbs':
        # Include another user's large request; it must not consume this user's cap.
        return (job_text(cores=running) if running else '') + (
            job_text(cores=queued - 8, state_='Q').replace('123.fixture', '124.fixture')
            + job_text(cores=8, state_='H').replace('123.fixture', '125.fixture')
            + job_text(cores=999, owner='other').replace('123.fixture', '126.fixture'))
    return (f'900|external|fixture|RUNNING|{running}|00:00|fixture\n' if running else '') + (
        f'901|manual|fixture|PENDING|{queued - 8}|00:00|fixture\n'
        '902|held|fixture|SUSPENDED|8|00:00|fixture\n')


def set_queue(fake, scheduler, running, queued):
    setattr(fake, 'qstat' if scheduler == 'pbs' else 'queue', Result(stdout=queue_text(scheduler, running, queued)))


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('running,queued,error', [
    (72, 208, None), (71, 209, 'Queued core limit exceeded'),
    (73, 208, 'Core limit exceeded'), (0, 216, 'Queued core limit exceeded'),
    # Scheduler runtime metadata does not pretend to enforce a running limit.
    (73, 207, None),
])
def test_queue_and_total_boundaries(multi, tmp_path, monkeypatch, scheduler, running, queued, error):
    name = 'default' if scheduler == 'pbs' else 'batch'
    limits(multi['clusters'][name]['resources'])
    path, _ = prepare(multi, tmp_path, cluster=name)
    selected = config.select_cluster(multi, name)
    fake = QueueFake(selected, occupied=0) if scheduler == 'pbs' else SlurmFake(selected)
    set_queue(fake, scheduler, running, queued)
    dialogs = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: dialogs.append(text) or True)
    if error:
        with pytest.raises(ValueError, match=error):
            submit.submit(multi, [path.name], fake)
        assert not dialogs and not (path / '.submit-claim').exists()
        assert not set(fake.operations()) & {'create_attempt', 'upload', 'submit'}
    else:
        assert submit.submit(multi, [path.name], fake)[0]['state'] == 'submitted'
        assert '排队上限 216' in dialogs[0] and '上限 288' in dialogs[0]
        assert '单作业上限 48' in dialogs[0]
        assert f'当前排队 {queued} / 排队上限 216' in dialogs[0]
        assert '由调度器执行，ag 未核实' in dialogs[0]
        assert '调度器运行上限 72' in dialogs[0] and 'ag 未设置或验证' in dialogs[0]


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
def test_queue_rechecked_after_confirmation(multi, tmp_path, monkeypatch, scheduler):
    name = 'default' if scheduler == 'pbs' else 'batch'
    limits(multi['clusters'][name]['resources'])
    path, _ = prepare(multi, tmp_path, cluster=name)
    selected = config.select_cluster(multi, name)
    fake = QueueFake(selected, occupied=0) if scheduler == 'pbs' else SlurmFake(selected)
    set_queue(fake, scheduler, 0, 208)
    def accept(_):
        set_queue(fake, scheduler, 0, 209)
        return True
    monkeypatch.setattr(confirm, 'confirm', accept)
    with pytest.raises(ValueError, match='Queued core limit changed'):
        submit.submit(multi, [path.name], fake)
    assert state.read(path)['state'] == 'failed_presubmit'
    assert not set(fake.operations()) & {'create_attempt', 'upload', 'submit'}


def test_pbs_batch_lag_counts_prior_submission_as_queued(cfg, tmp_path, monkeypatch):
    limits(cfg['resources'])
    ids = prepare_batch(cfg, tmp_path, 8, count=2)
    class Lag(QueueFake):
        def run(self, command):
            if command.operation == 'submit':
                set_queue(self, 'pbs', 0, 201)
            return super().run(command)
    fake = Lag(cfg, occupied=0)
    set_queue(fake, 'pbs', 0, 200)
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    with pytest.raises(ValueError, match='Queued core limit changed'):
        submit.submit(cfg, ids, fake)
    assert fake.operations().count('submit') == 1
    assert fake.operations().count('create_attempt') == 1
    assert state.read(attempt.find(cfg, ids[0]))['state'] == 'submitted'
    assert state.read(attempt.find(cfg, ids[1]))['state'] == 'failed_presubmit'


@pytest.mark.parametrize('visible', [False, True])
def test_peer_queue_cap_cannot_be_bypassed_or_double_counted(shared, tmp_path, monkeypatch, visible):
    shared['clusters']['batch']['resources']['max_queued_cores'] = 16
    # The target omits the optional cap; its peer's configured cap still applies.
    _, m = reserve(shared, tmp_path, cores=8, job='123')
    path, _ = prepare(shared, tmp_path, 'trial', 'next')
    selected = config.select_cluster(shared, 'trial')
    fake = SlurmFake(selected)
    fake.queue = Result(stdout=('999|external|fixture|PENDING|1|00:00|fixture\n'
                               + (row(m) if visible else '')))
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    if visible:
        assert submit.submit(shared, [path.name], fake)[0]['state'] == 'submitted'
    else:
        with pytest.raises(ValueError, match='Queued core limit exceeded: 9 queued'):
            submit.submit(shared, [path.name], fake)
        assert not (path / '.submit-claim').exists()
    shared['clusters']['trial']['resources']['max_queued_cores'] = 12
    assert config.optional_resource_caps(selected)['max_queued_cores'] == 12
    distinct = deepcopy(selected)
    distinct['ssh']['host'] = 'distinct-fixture'
    distinct['resources']['max_queued_cores'] = 24
    assert config.optional_resource_caps(distinct)['max_queued_cores'] == 24


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
def test_doctor_and_template_use_independent_crest(multi, tmp_path, scheduler):
    name = 'default' if scheduler == 'pbs' else 'batch'
    selected = config.select_cluster(multi, name)
    selected['programs']['crest'] = {'executable': str(tmp_path / 'independent' / 'crest')}
    limits(selected['resources'])
    selected['resources']['max_committed_cores'] = 288
    fake = QueueFake(selected, occupied=0) if scheduler == 'pbs' else SlurmFake(selected)
    result = doctor.doctor(selected, fake)
    exact = config.crest_executable(selected['programs'])
    assert remote.executable(exact) in fake.calls
    assert remote.executable(selected['programs']['xtb']['root'] + '/bin/crest') not in fake.calls
    assert result['max_queued_cores'] == 216 and result['scheduler_max_running_cores'] == 72
    assert '由调度器执行，ag 未核实' in result['scheduler_running_note']
    manifest = dict(study_id='water', attempt_id='water-001-crest', remote_dir='water/water-001-crest',
                    pbs_job_name='water-crest', cluster=name, scheduler=scheduler, template='crest',
                    template_params={}, cores=8, mem_gb=8, walltime='00:01:00')
    script = render.render(selected, manifest, 'water.xyz')
    assert f'ag_run {shlex.quote(exact)} water.xyz' in script
    assert subprocess.run(['sh', '-n'], input=script, text=True, capture_output=True).returncode == 0
    # Run only the rendered program body against a local inert executable.
    binary = Path(exact); binary.parent.mkdir(); binary.write_text('#!/bin/sh\nprintf "independent:%s\\n" "$*"\n')
    binary.chmod(0o700)
    xtb_bin = Path(selected['programs']['xtb']['root']) / 'bin'
    xtb_bin.mkdir(parents=True)
    decoy = xtb_bin / 'crest'; decoy.write_text('#!/bin/sh\nprintf "wrong executable\\n"\n'); decoy.chmod(0o700)
    body = 'ag_run() { "$@"; }\nexport XTBPATH=' + script.split('export XTBPATH=', 1)[1]
    result = subprocess.run(['sh'], input=body, text=True, cwd=tmp_path, capture_output=True, env=os.environ.copy())
    assert result.returncode == 0
    assert (tmp_path / 'crest.out').read_text() == 'independent:water.xyz -T 8\n'


def test_public_caps_and_failed_monitor_snapshot(cfg, monkeypatch):
    limits(cfg['resources'])
    cfg['programs']['crest'] = {'executable': str(Path(cfg['_config_dir']) / 'private-crest-marker')}
    rows = clusters.describe(config.load_config(write_config(cfg)))['clusters']
    assert rows[0]['resources']['max_queued_cores'] == 216
    assert rows[0]['resources']['scheduler_max_running_cores'] == 72
    assert rows[0]['programs_enabled']['crest']
    assert 'private-crest-marker' not in str(rows)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    assert monitor.sample(cfg, MonitorFake())['own']['max_queued_cores'] == 216
    cfg['resources'].pop('max_queued_cores')
    cfg['resources'].pop('scheduler_max_running_cores')
    failed = MonitorFake(); failed.replies['jobs'] = TransportError('synthetic failure')
    snapshot = monitor.sample(cfg, failed)
    assert not snapshot['ok']
    assert 'max_queued_cores' not in snapshot['own']
    assert 'scheduler_max_running_cores' not in snapshot['own']


@pytest.mark.parametrize('cap', [48, 47])
def test_pbs_48_core_job_is_single_node_and_enforced(cfg, tmp_path, monkeypatch, cap):
    limits(cfg['resources'])
    ids = prepare_batch(cfg, tmp_path, 48)
    path = attempt.find(cfg, ids[0])
    assert '#PBS -l nodes=1:ppn=48' in (path / 'inputs' / 'job.pbs').read_text()
    cfg['resources']['max_cores'] = cap
    fake = QueueFake(cfg, occupied=0)
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    if cap == 48:
        assert submit.submit(cfg, ids, fake)[0]['state'] == 'submitted'
    else:
        with pytest.raises(ValueError, match='Single job exceeds'):
            submit.submit(cfg, ids, fake)
        assert not fake.calls


def test_missing_independent_crest_does_not_fall_back(cfg):
    cfg['programs']['crest'] = {'executable': '/fixture/independent/crest'}
    class Missing(QueueFake):
        def run(self, command):
            if command == remote.executable('/fixture/independent/crest'):
                self.calls.append(command)
                return Result(1)
            return super().run(command)
    fake = Missing(cfg, occupied=0)
    with pytest.raises(TransportError, match='crest executable failed'):
        doctor.doctor(cfg, fake)
    assert remote.executable(cfg['programs']['xtb']['root'] + '/bin/crest') not in fake.calls


@pytest.mark.parametrize('scheduler,params,expected', [
    ('pbs', {}, 'b0d538289e7c26250273fc525a78239f79fbfcef7ce0771625944eac125fb69e'),
    ('pbs', {'--quick': ''}, 'a158f3656722a21e174082b5693d45e5b856f07de96c4d96cb39f4c83f0ba493'),
    ('pbs', {'--mdopt': ''}, 'ea7654fc04397dca4a99cfbe550cded2cb21b29cc0386feb91cd656660c6f3f3'),
    ('slurm', {}, '3f7d86598825527d7643c165551fa43fd4a6c758b88a95a62ec02ed2db69c2c4'),
    ('slurm', {'--quick': ''}, '5eb9dfc505664f82e9dc49b4b0e4da11cf189a6602259c60d7453f4d379cbd2e'),
    ('slurm', {'--mdopt': ''}, '6032b0eb453895abd3fca0d34342466715c1d0e3225a813cf2f2173354539786'),
])
def test_legacy_crest_full_script_bytes(scheduler, params, expected):
    # Full-script SHA-256 values from the unchanged T102 baseline b318639.
    cfg = dict(scheduler={'queue': 'fixture'} if scheduler == 'pbs' else 'slurm',
               remote={'ag_root': '/fixture/ag'},
               programs={'gaussian': {'g16root': '/fixture/g16'}, 'xtb': {'root': '/fixture/xtb'}})
    m = dict(study_id='water', attempt_id='water-001-crest', remote_dir='water/water-001-crest',
             pbs_job_name='water-crest', cluster='default', scheduler=scheduler, template='crest',
             template_params=params, cores=8, mem_gb=8, walltime='00:01:00')
    assert sha256(render.render(cfg, m, 'water.xyz').encode()).hexdigest() == expected


def crest_preparation(cfg, tmp_path):
    study.init(cfg, 'water')
    source = tmp_path / 'water.xyz'
    source.write_text('3\nwater fixture\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    return dict(study_name='water', template='crest', input_path=source, tier='simple',
                walltime='00:01:00', label='crest', method_basis='兜底方法：合成测试')


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('installation', ['missing', 'not-executable', 'executable'])
def test_prepare_checks_exact_installation_before_claim(multi, tmp_path, scheduler, installation):
    name = 'default' if scheduler == 'pbs' else 'batch'
    binary = tmp_path / 'independent-crest'
    if installation != 'missing':
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o700 if installation == 'executable' else 0o600)
    multi['clusters'][name]['programs']['crest'] = {'executable': str(binary)}
    raw = config.load_config(write_config(multi))
    selected = config.select_cluster(raw, name)
    calls = []
    class LocalExecutableCheck:
        def run(self, command):
            assert command == remote.executable(config.crest_executable(selected['programs']))
            calls.append(command)
            # Only test -x/-f on a synthetic local path; never run the program.
            result = subprocess.run(['sh', '-c', command.text], capture_output=True, text=True)
            return Result(result.returncode, result.stdout, result.stderr)
    args = crest_preparation(raw, tmp_path)
    if installation == 'executable':
        m = attempt.prepare(raw, **args, cluster=name, transport=LocalExecutableCheck())
        path = attempt.find(raw, m['attempt_id'])
        script = path / 'inputs' / ('job.pbs' if scheduler == 'pbs' else 'job.slurm')
        assert f'ag_run {shlex.quote(str(binary))} water.xyz' in script.read_text()
        assert state.read(path)['state'] == 'prepared'
    else:
        with pytest.raises(TransportError, match='crest executable failed'):
            attempt.prepare(raw, **args, cluster=name, transport=LocalExecutableCheck())
        assert list((Path(raw['local']['studies_root']) / 'water/attempts').iterdir()) == []
    assert len(calls) == 1


@pytest.mark.parametrize('failure', [Result(255), SSHConnectionError('synthetic SSH interruption')])
def test_prepare_ssh_failure_never_retries_or_claims(cfg, tmp_path, monkeypatch, failure):
    cfg['programs']['crest'] = {'executable': str(tmp_path / 'crest')}
    args = crest_preparation(cfg, tmp_path)
    calls = []
    def execute(self, argv, timeout, operation, index):
        calls.append((operation, index))
        assert not self.read_only  # Existing transport's automatic retry is off.
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(SSHTransport, '_logged_execute', execute)
    with pytest.raises(TransportError):
        attempt.prepare(cfg, **args)
    assert calls == [('executable', 1)]
    assert list((Path(cfg['local']['studies_root']) / 'water/attempts').iterdir()) == []


def test_legacy_prepare_stays_offline(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(SSHTransport, '__init__', lambda *a, **k: pytest.fail('legacy prepare must stay offline'))
    args = crest_preparation(cfg, tmp_path)
    m = attempt.prepare(cfg, **args)
    assert state.read(attempt.find(cfg, m['attempt_id']))['state'] == 'prepared'


def test_gaussian_does_not_probe_crest(multi, tmp_path, monkeypatch):
    multi['clusters']['default']['programs']['crest'] = {'executable': '/fixture/missing-crest'}
    monkeypatch.setattr(SSHTransport, '__init__', lambda *a, **k: pytest.fail('Gaussian must not probe CREST'))
    path, _ = prepare(multi, tmp_path, cluster='default')
    assert state.read(path)['state'] == 'prepared'


@pytest.mark.parametrize('tier_cores', [44, 45])
def test_default_explicit_44_tier_boundary(cfg, tier_cores):
    cfg['resources']['max_cores'] = 44
    cfg['resources']['tiers']['complex']['cores'] = tier_cores
    if tier_cores == 44:
        assert config.load_config(write_config(cfg))['resources']['max_cores'] == 44
    else:
        with pytest.raises(ValueError, match='Invalid resource tier'):
            config.load_config(write_config(cfg))


@pytest.mark.parametrize('peer_cap,target_cap', [(16, 24), (24, 16)])
@pytest.mark.parametrize('job', [None, '123'])
def test_shared_queue_min_includes_unknown(shared, tmp_path, monkeypatch, peer_cap, target_cap, job):
    shared['clusters']['batch']['resources']['max_queued_cores'] = peer_cap
    shared['clusters']['trial']['resources']['max_queued_cores'] = target_cap
    reserve(shared, tmp_path, cores=8, job=job)
    path, _ = prepare(shared, tmp_path, 'trial', 'next')
    fake = SlurmFake(config.select_cluster(shared, 'trial'))
    fake.queue = Result(stdout='999|external|fixture|PENDING|1|00:00|fixture\n')
    monkeypatch.setattr(confirm, 'confirm', lambda _: pytest.fail('queue cap must reject before confirmation'))
    with pytest.raises(ValueError, match='Queued core limit exceeded: 9 queued.*16 cap'):
        submit.submit(shared, [path.name], fake)
    assert not (path / '.submit-claim').exists()
    assert not set(fake.operations()) & {'create_attempt', 'upload', 'submit'}
