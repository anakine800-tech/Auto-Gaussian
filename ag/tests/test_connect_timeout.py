"""T130: synthetic endpoints and subprocesses; no live SSH or configuration."""
from copy import deepcopy
from datetime import datetime, timezone
import subprocess

import pytest

from ag import config, doctor, fetch, monitor, remote, state, submit, transport
from ag.transport import Result, SSHConnectionError, SSHTransport, TransportError
from test_core import cfg, prepared, write_config, Fake, allow  # noqa: F401 — synthetic fixtures
from test_fetch import fake_scp, download_log
from test_slurm import multi  # noqa: F401 — synthetic multi-entry fixture


def options(cfg, seconds):
    return ['-F', cfg['ssh']['config_file'], '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'ConnectTimeout={seconds}']


@pytest.mark.parametrize('layout', ['legacy', 'named', 'hybrid'])
@pytest.mark.parametrize('value', [None, 15, 40, 60, 14, 61, True, False, '40', 40.0])
def test_config_loads_timeout_only_as_bounded_integer(cfg, multi, layout, value):
    if layout == 'legacy':
        source, target = cfg, cfg
    elif layout == 'named':
        source, target = multi, multi['clusters']['batch']
    else:
        source, target = cfg, cfg
        source['clusters'] = {'batch': multi['clusters']['batch']}
    if value is not None:
        target['ssh']['connect_timeout_seconds'] = value
    path = write_config(source)
    if value is not None and (type(value) is not int or value not in (15, 40, 60)):
        with pytest.raises(config.ConfigError, match='ssh.connect_timeout_seconds'):
            config.load_config(path)
    else:
        loaded = config.load_config(path)
        selected = config.select_cluster(loaded, 'batch' if layout == 'named' else 'default')
        assert SSHTransport(selected).options == options(selected, value or 15)
        assert ('connect_timeout_seconds' in selected['ssh']) == (value is not None)


def test_shared_entries_keep_independent_timeouts_and_shared_capacity(multi):
    multi['clusters']['other'] = deepcopy(multi['clusters']['default'])
    multi['clusters']['default']['ssh']['connect_timeout_seconds'] = 40
    multi['clusters']['other']['ssh']['connect_timeout_seconds'] = 60
    selected = [config.select_cluster(config.load_config(write_config(multi)), name)
                for name in ('default', 'other')]
    assert config.cluster_identity(selected[0]) == config.cluster_identity(selected[1])
    for cfg, seconds in zip(selected, (40, 60)):
        assert set(config.shared_clusters(cfg)) == {'default', 'other'}
        assert SSHTransport(cfg).options == options(cfg, seconds)
    original = SSHTransport(selected[0])
    assert transport.bound_transport(original, selected[0]) is original
    with pytest.raises(config.ConfigError, match='cluster mismatch'):
        transport.bound_transport(original, selected[1])
    assert original.options == options(selected[0], 40)


@pytest.mark.parametrize('seconds', [None, 15, 40, 60])
@pytest.mark.parametrize('kind', [SSHTransport, monitor.MonitorTransport, fetch._IncompleteSSHTransport])
@pytest.mark.parametrize('base_timeout', [30, 60, 120])
def test_ssh_argv_and_total_timeout(cfg, monkeypatch, seconds, kind, base_timeout):
    if seconds is not None:
        cfg['ssh']['connect_timeout_seconds'] = seconds
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result(stdout='synthetic result')

    monkeypatch.setattr(transport.subprocess, 'run', run)
    client = kind(cfg)
    command = remote.Command('jobs', 'qstat -f', timeout=base_timeout)
    assert client.run(command) == Result(stdout='synthetic result')
    assert command.timeout == base_timeout
    assert calls == [(['ssh', *options(cfg, seconds or 15), cfg['ssh']['host'], '--', command.text],
                     dict(capture_output=True, text=True, timeout=base_timeout + (seconds or 15) - 15))]
    with pytest.raises(AttributeError):
        client.extra_connect_seconds = 0


@pytest.mark.parametrize('seconds', [None, 15, 40, 60])
def test_upload_argv_and_allowance(cfg, prepared, monkeypatch, seconds):
    if seconds is not None:
        cfg['ssh']['connect_timeout_seconds'] = seconds
    path, manifest = prepared
    source = path / 'inputs/water.gjf'
    calls = []
    monkeypatch.setattr(transport.subprocess, 'run',
                        lambda argv, **kw: calls.append((argv, kw)) or Result())
    SSHTransport(cfg).upload(source, manifest, source.name)
    expected = dict(capture_output=True, text=True, timeout=60 + (seconds or 15) - 15)
    assert calls == [
        (['ssh', *options(cfg, seconds or 15), cfg['ssh']['host'], '--',
          remote.upload_check(cfg, manifest, source.name).text], expected),
        (['scp', *options(cfg, seconds or 15), str(source),
          cfg['ssh']['host'] + ':' + remote.attempt_dir(cfg, manifest) + '/' + source.name], expected),
    ]


@pytest.mark.parametrize('seconds,expected', [(None, 30), (15, 30), (40, 55), (60, 75)])
@pytest.mark.parametrize('kind', [SSHTransport, monitor.MonitorTransport])
def test_explicit_storage_timeout_is_extended_once(cfg, monkeypatch, seconds, expected, kind):
    if seconds is not None:
        cfg['ssh']['connect_timeout_seconds'] = seconds
    calls = []
    monkeypatch.setattr(transport.subprocess, 'run', lambda argv, **kw:
                        calls.append(kw['timeout']) or Result(stdout='1024 ' + cfg['remote']['ag_root']))
    assert doctor.storage(cfg, kind(cfg), timeout=30) == 1024
    assert calls == [expected]


@pytest.mark.parametrize('seconds,limit', [(None, 60), (15, 60), (40, 85), (60, 105)])
@pytest.mark.parametrize('progress', [False, True])
@pytest.mark.parametrize('kind', [SSHTransport, fetch._IncompleteSSHTransport])
def test_download_stall_allowance_and_no_retry(cfg, prepared, monkeypatch, tmp_path,
                                             seconds, limit, progress, kind):
    if seconds is not None:
        cfg['ssh']['connect_timeout_seconds'] = seconds
    _, manifest = prepared
    clock = fake_scp(monkeypatch, [dict(writes=[(10, b'partial')] if progress else [])])
    target = tmp_path / 'output.log'
    with pytest.raises(SSHConnectionError, match='stalled'):
        kind(cfg).download(manifest, 'water.log', target)
    assert clock.now == limit + (10 if progress else 0)
    assert len(clock.processes) == 1 and clock.sleeps == [] and not target.exists()
    process, = clock.processes
    assert process.argv == ['scp', *options(cfg, seconds or 15), cfg['ssh']['host'] + ':' +
                            remote.attempt_dir(cfg, manifest) + '/water.log', str(process.target)]
    assert all(wait <= 5 for wait in process.waits)
    assert download_log(cfg)[0]['timeout_reason'] == 'stalled'


def test_slow_connection_download_can_finish(cfg, prepared, monkeypatch, tmp_path):
    cfg['ssh']['connect_timeout_seconds'] = 40
    _, manifest = prepared
    clock = fake_scp(monkeypatch, [dict(duration=75, writes=[(70, b'complete')])])
    target = tmp_path / 'output.log'
    fetch._IncompleteSSHTransport(cfg).download(manifest, 'water.log', target)
    assert target.read_bytes() == b'complete' and clock.now == 75


def test_download_hard_limit_is_unchanged(cfg, prepared, monkeypatch, tmp_path):
    cfg['ssh']['connect_timeout_seconds'] = 40
    _, manifest = prepared
    assert transport.DOWNLOAD_HARD_LIMIT_SECONDS == 86400
    monkeypatch.setattr(transport, 'DOWNLOAD_HARD_LIMIT_SECONDS', 70)
    clock = fake_scp(monkeypatch, [dict(writes=[(t, b'x' * t) for t in range(5, 81, 5)])])
    with pytest.raises(SSHConnectionError, match='hard_limit'):
        SSHTransport(cfg).download(manifest, 'water.log', tmp_path / 'output.log')
    assert clock.now == 70 and clock.sleeps == []


@pytest.mark.parametrize('failure', ['exit', 'timeout'])
@pytest.mark.parametrize('recover', [False, True])
def test_read_only_retry_is_still_once_after_15_seconds(cfg, monkeypatch, failure, recover):
    cfg['ssh']['connect_timeout_seconds'] = 40
    calls, sleeps = [], []

    def run(argv, **kwargs):
        calls.append(kwargs['timeout'])
        if recover and len(calls) == 2:
            return Result()
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'], stderr='Connection timed out')
        return Result(255, stderr='Connection timed out')

    monkeypatch.setattr(transport.subprocess, 'run', run)
    monkeypatch.setattr(transport.time, 'sleep', sleeps.append)
    if failure == 'timeout' and not recover:
        with pytest.raises(SSHConnectionError):
            SSHTransport(cfg, read_only=True).run(remote.jobs())
    else:
        assert SSHTransport(cfg, read_only=True).run(remote.jobs()).returncode == (0 if recover else 255)
    assert calls == [85, 85] and sleeps == [15]


@pytest.mark.parametrize('operation', ['submit', 'cancel', 'upload'])
@pytest.mark.parametrize('failure', ['exit', 'timeout'])
def test_writes_do_not_retry(cfg, prepared, monkeypatch, operation, failure):
    cfg['ssh']['connect_timeout_seconds'] = 40
    path, manifest = prepared
    calls = []

    def run(argv, **kwargs):
        calls.append((argv[0], kwargs['timeout']))
        if operation == 'upload' and argv[0] == 'ssh':
            return Result()  # Existing upload precheck.
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        return Result(255, stderr='Connection timed out')

    monkeypatch.setattr(transport.subprocess, 'run', run)
    monkeypatch.setattr(transport.time, 'sleep', lambda _: pytest.fail('Writes must not retry'))
    client = SSHTransport(cfg)
    if operation == 'upload':
        with pytest.raises(TransportError):
            client.upload(path / 'inputs/water.gjf', manifest, 'water.gjf')
        assert calls == [('ssh', 85), ('scp', 85)]
    else:
        command = remote.submit(cfg, manifest) if operation == 'submit' else remote.cancel('123')
        if failure == 'timeout':
            with pytest.raises(SSHConnectionError):
                client.run(command)
        else:
            assert client.run(command).returncode == 255
        assert calls == [('ssh', command.timeout + 25)]


@pytest.mark.parametrize('failure', ['exit', 'timeout'])
def test_submission_uncertainty_preserves_claim_and_unknown(cfg, prepared, monkeypatch, failure):
    cfg['ssh']['connect_timeout_seconds'] = 40
    path, _ = prepared
    timeouts = []

    def run(argv, **kwargs):
        timeouts.append(kwargs['timeout'])
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        return Result(255, stderr='Connection timed out')

    class SubmissionFake(Fake):
        def run(self, command):
            if command.operation == 'submit':
                return SSHTransport(cfg).run(command)
            return super().run(command)

    monkeypatch.setattr(transport.subprocess, 'run', run)
    monkeypatch.setattr(transport.time, 'sleep', lambda _: pytest.fail('Submit must not retry'))
    allow(monkeypatch)
    fake = SubmissionFake(cfg)
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake)
    assert state.read(path)['state'] == 'unknown'
    assert (path / '.submit-claim').exists()
    assert not (path / 'submission.json').exists()
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake)
    assert timeouts == [145]


@pytest.mark.parametrize('detail,category', [
    ('Permission denied (publickey).', 'auth'),
    ('Host key verification failed.', 'host_key'),
    ('WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!', 'host_key'),
    ('Connection timed out', None),
])
@pytest.mark.parametrize('outcome', ['success', 'exit', 'timeout'])
def test_monitor_matches_base_results_and_errors_before_redaction(cfg, monkeypatch,
                                                                detail, category, outcome):
    cfg['ssh'].update(host='publickey', connect_timeout_seconds=40)
    calls = []

    def run(argv, **kwargs):
        calls.append(kwargs['timeout'])
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'], stderr=detail)
        return Result(0 if outcome == 'success' else 255, stdout='synthetic output', stderr=detail)

    monkeypatch.setattr(transport.subprocess, 'run', run)
    monkeypatch.setattr(transport.time, 'sleep', lambda _: pytest.fail('Monitor must not retry'))
    base, client = SSHTransport(cfg), monitor.MonitorTransport(cfg, read_only=True)
    client.failure_category = 'auth'  # A successful response must clear stale classification.
    if outcome == 'timeout':
        with pytest.raises(SSHConnectionError) as original:
            base.run(remote.jobs())
        with pytest.raises(SSHConnectionError) as monitored:
            client.run(remote.jobs())
        assert str(original.value) == str(monitored.value)
        assert type(original.value.__cause__) is type(monitored.value.__cause__)
    else:
        # _perform deliberately differs: monitor does not append a retry hint.
        assert base._execute(['ssh'], 85) == client._execute(['ssh'], 85)
    assert client.failure_category == (None if outcome == 'success' else category)
    assert calls == [85, 85]
    if outcome != 'success' and category is None:
        schedule = monitor.Sampling(30)
        for _ in range(3):
            schedule.record(False, client.failure_category, 'scheduled', 0, datetime.now(timezone.utc))
        assert schedule.state == 'backoff' and schedule.pause_reason is None


def test_monitor_local_start_failure_matches_base(cfg, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('synthetic local error')

    monkeypatch.setattr(transport.subprocess, 'run', fail)
    for kind in (SSHTransport, monitor.MonitorTransport):
        with pytest.raises(TransportError, match='^Could not start SSH/scp locally$') as error:
            kind(cfg).run(remote.jobs())
        assert isinstance(error.value.__cause__, OSError)
