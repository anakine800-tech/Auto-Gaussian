"""Supplemental fetch: synthetic files and a strictly read-only fake transport."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shlex
import signal
import subprocess

import pytest

from ag import attempt, cli, fetch, remote, state
from ag.transport import Result, TransportError
from test_core import cfg, prepared, finish  # noqa: F401 — shared synthetic fixtures


def fake_scp(monkeypatch, plans):
    """Advance a fake clock and write synthetic chunks at scheduled times."""
    from ag import transport

    class Clock:
        now = 0
        processes = []
        sleeps = []

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    clock = Clock()

    class Process:
        def __init__(self, argv, **kwargs):
            assert argv[0] == 'scp'
            assert kwargs == dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True)
            self.argv, self.target = argv, Path(argv[-1])
            self.plan = plans[len(clock.processes)]
            self.started = clock.now
            self.returncode = None
            self.terminated = self.killed = False
            self.waits = []
            self.pid = 10000 + len(clock.processes)
            clock.processes.append(self)

        def communicate(self, timeout=None):
            if self.returncode is not None:
                return '', self.plan.get('stderr', '')
            assert timeout is not None
            self.waits.append(timeout)
            end = self.plan.get('duration', float('inf'))
            elapsed = clock.now - self.started
            next_elapsed = min(elapsed + timeout, end)
            for at, data in self.plan.get('writes', []):
                if at <= next_elapsed:
                    self.target.write_bytes(data)
            clock.now = self.started + next_elapsed
            if next_elapsed >= end:
                self.returncode = self.plan.get('returncode', 0)
                return '', self.plan.get('stderr', '')
            raise subprocess.TimeoutExpired(self.argv, timeout)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            if not self.plan.get('ignore_terminate'):
                self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setattr(transport.subprocess, 'Popen', Process)
    def killpg(pid, sig):
        process = next(p for p in clock.processes if p.pid == pid)
        assert sig in (signal.SIGTERM, signal.SIGKILL)
        process.terminate() if sig == signal.SIGTERM else process.kill()
    monkeypatch.setattr(transport.os, 'killpg', killpg)
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(transport.time, 'sleep', clock.sleep)
    return clock


def download_log(cfg):
    files = list((Path(cfg['_config_dir']) / 'ssh-log').glob('*.jsonl'))
    return [json.loads(line) for file in files for line in file.read_text().splitlines()]


class ReadOnlyFake:
    def __init__(self, files):
        self.files = files
        self.calls = []
        self.downloaded = []
        self.after_download = lambda: None
        self.corrupt = False
        self.error = False
        self.record_paths = None

    def record_to(self, paths):
        self.record_paths = paths

    def run(self, command):
        assert command.operation == 'metadata'
        path = shlex.split(command.text)[-1]
        name = Path(path).name
        self.calls.append(('metadata', name))
        if self.error:
            raise TransportError('Synthetic SSH failure')
        if name not in self.files:
            # Same empty failure as test -f for an absent remote file.
            return Result(returncode=1)
        data = self.files[name]
        return Result(stdout=f'{len(data)}\n{sha256(data).hexdigest()}  {path}\n')

    def download(self, manifest, name, local):
        self.calls.append(('download', name))
        self.downloaded.append(name)
        with local.open('xb') as handle:
            handle.write(self.files[name] + (b'corrupt' if self.corrupt else b''))
        self.after_download()


@pytest.fixture
def fetched(cfg, prepared):
    path, manifest = prepared
    finish(path)
    state.write(path, 'fetched', exit_status=0)
    fake = ReadOnlyFake({'water.log': b'Normal termination', 'job.pbs.out': b'scheduler output'})
    (path / 'outputs/water.log').write_bytes(fake.files['water.log'])
    return path, fake


def snapshot(path):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.rglob('*') if p.is_file()}


def unchanged(before):
    for p, (content, mtime) in before.items():
        assert p.read_bytes() == content
        assert p.stat().st_mtime_ns == mtime


def test_add_missing_only_downloads_missing_and_keeps_original_records(cfg, fetched):
    path, fake = fetched
    before = snapshot(path.parent.parent)
    result = fetch.fetch(cfg, path, fake, add_missing=True)
    assert result['state'] == 'fetched'
    assert result['files'] == ['job.pbs.out']
    assert fake.record_paths == []
    assert fake.downloaded == ['job.pbs.out']
    assert fake.calls[:2] == [('metadata', 'water.log'), ('metadata', 'job.pbs.out')]
    unchanged(before)
    assert (path / 'outputs/job.pbs.out').read_bytes() == fake.files['job.pbs.out']
    record = json.loads((path / result['record']).read_text())
    assert record['files'] == ['job.pbs.out']
    assert record['outputs'] == {
        name: {'size': len(data), 'sha256': sha256(data).hexdigest()}
        for name, data in fake.files.items()}
    assert record['created_at'].endswith('+00:00')
    before = snapshot(path.parent.parent)
    result = fetch.fetch(cfg, path, fake, add_missing=True)
    assert result['files'] == []
    assert result['message'] == '没有可补取的文件'
    assert fake.downloaded == ['job.pbs.out']
    assert snapshot(path.parent.parent) == before


def test_add_missing_mismatch_in_later_file_refuses_entire_download(cfg, fetched):
    path, fake = fetched
    # First declared file is missing, the later existing file is wrong.
    (path / 'outputs/water.log').unlink()
    (path / 'outputs/job.pbs.out').write_bytes(b'old')
    before = snapshot(path.parent.parent)
    with pytest.raises(ValueError) as error:
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert 'job.pbs.out' in str(error.value)
    assert sha256(b'old').hexdigest() in str(error.value)
    assert sha256(fake.files['job.pbs.out']).hexdigest() in str(error.value)
    assert fake.downloaded == []
    assert snapshot(path.parent.parent) == before


@pytest.mark.parametrize('absent', ['water.log', 'job.pbs.out'])
def test_add_missing_remote_missing_even_for_existing_local_file(cfg, fetched, absent):
    path, fake = fetched
    del fake.files[absent]
    before = snapshot(path.parent.parent)
    with pytest.raises(TransportError, match=absent + '.*missing'):
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert fake.downloaded == []
    assert snapshot(path.parent.parent) == before


@pytest.mark.parametrize('value', sorted(set(state.TRANSITIONS) - {'fetched'}))
def test_add_missing_rejects_every_other_state_without_remote_calls(cfg, prepared, value):
    path, _ = prepared
    # A synthetic state snapshot avoids running any lifecycle operations.
    (path / 'status.json').write_text(json.dumps({'state': value}))
    before = snapshot(path.parent.parent)
    fake = ReadOnlyFake({})
    with pytest.raises(ValueError, match='requires a fetched'):
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert fake.calls == []
    assert snapshot(path.parent.parent) == before


@pytest.mark.parametrize('failure', ['corrupt', 'remote_changed', 'local_changed', 'ssh'])
def test_add_missing_does_not_publish_unverified_download(cfg, fetched, failure):
    path, fake = fetched
    original_status = (path / 'status.json').read_bytes()
    if failure == 'corrupt':
        fake.corrupt = True
    elif failure == 'remote_changed':
        fake.after_download = lambda: fake.files.update({'water.log': b'changed remotely'})
    elif failure == 'local_changed':
        fake.after_download = lambda: (path / 'outputs/water.log').write_bytes(b'changed locally')
    else:
        fake.error = True
    with pytest.raises((ValueError, TransportError)):
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert not (path / 'outputs/job.pbs.out').exists()
    assert not list(path.glob('fetch-add-missing-*.json'))
    assert (path / 'status.json').read_bytes() == original_status


def test_add_missing_exclusive_output_keeps_racing_file(cfg, fetched):
    path, fake = fetched
    target = path / 'outputs/job.pbs.out'
    fake.after_download = lambda: target.write_bytes(b'concurrent file')
    with pytest.raises(FileExistsError):
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert target.read_bytes() == b'concurrent file'
    assert state.read(path)['state'] == 'fetched'
    assert all(p.read_bytes() == b'' for p in path.glob('fetch-add-missing-*.json'))


def test_add_missing_record_collision_preserves_old_record(cfg, fetched, monkeypatch):
    path, fake = fetched
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(fetch, 'datetime', Clock)
    record = path / 'fetch-add-missing-20260101T000000000000Z.json'
    record.write_bytes(b'original fetch record')
    before = snapshot(path.parent.parent)
    with pytest.raises(FileExistsError):
        fetch.fetch(cfg, path, fake, add_missing=True)
    unchanged(before)
    assert not (path / 'outputs/job.pbs.out').exists()


@pytest.mark.parametrize('name', ['water.log', 'job.pbs.out'])
def test_add_missing_rejects_local_symlinks(cfg, fetched, tmp_path, name):
    path, fake = fetched
    target = path / 'outputs' / name
    if target.exists():
        target.unlink()
    outside = tmp_path / 'external'
    outside.write_bytes(b'preserve outside file')
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='Symbolic links'):
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert fake.downloaded == []
    assert outside.read_bytes() == b'preserve outside file'


def test_add_missing_cli_and_normal_fetch_still_refuses_fetched(cfg, fetched, monkeypatch, capsys):
    from ag import transport
    path, fake = fetched
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(transport, 'SSHTransport', lambda cfg, **kw: fake)
    assert cli.main(['fetch', path.name, '--add-missing', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['files'] == ['job.pbs.out']
    fake.calls.clear()
    assert cli.main(['fetch', path.name, '--json']) == 1
    assert 'Only a finished' in json.loads(capsys.readouterr().out)['error']
    assert fake.calls == []


def test_add_missing_xtb_current_declaration_includes_scheduler_output(cfg, prepared, tmp_path):
    # Prepared study is reused, but xTB files and all remote bytes are synthetic.
    xyz = tmp_path / 'water.xyz'
    xyz.write_text('3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    manifest = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='xtb', input_path=xyz,
                               tier='simple', walltime='00:10:00', label='xtb')
    path = attempt.find(cfg, manifest['attempt_id'])
    finish(path)
    state.write(path, 'fetched')
    files = {name: b'synthetic ' + name.encode() for name in remote.output_names(manifest)}
    assert 'job.pbs.out' in files
    for name, data in files.items():
        if name != 'job.pbs.out':
            (path / 'outputs' / name).write_bytes(data)
    fake = ReadOnlyFake(files)
    assert fetch.fetch(cfg, path, fake, add_missing=True)['files'] == ['job.pbs.out']
    assert fake.downloaded == ['job.pbs.out']


def test_add_missing_verifies_all_downloads_before_publishing_any(cfg, fetched):
    path, fake = fetched
    (path / 'outputs/water.log').unlink()
    # The first download verifies; the second is corrupt.
    fake.after_download = lambda: setattr(fake, 'corrupt', True)
    with pytest.raises(ValueError, match='job.pbs.out'):
        fetch.fetch(cfg, path, fake, add_missing=True)
    assert fake.downloaded == ['water.log', 'job.pbs.out']
    assert not (path / 'outputs/water.log').exists()
    assert not (path / 'outputs/job.pbs.out').exists()
    assert state.read(path)['state'] == 'fetched'
    assert not list(path.glob('fetch-add-missing-*.json'))


def test_slow_download_beyond_minute_is_verified_before_publication(cfg, prepared, monkeypatch):
    from ag.transport import SSHTransport
    path, manifest = prepared
    finish(path)
    data = b'synthetic water output' * 100
    fake = ReadOnlyFake({'water.log': data, 'job.pbs.out': b'done'})
    clock = fake_scp(monkeypatch, [
        dict(duration=130, writes=[(t, data[:len(data) * t // 120]) for t in range(10, 121, 10)]),
        dict(duration=1, writes=[(1, b'done')]),
    ])
    transport = SSHTransport(cfg, read_only=True)
    monkeypatch.setattr(transport, 'run', fake.run)
    result = fetch.fetch(cfg, path, transport)
    assert result['state'] == 'fetched' and clock.now == 131
    assert sha256((path / 'outputs/water.log').read_bytes()).digest() == sha256(data).digest()
    assert all(row['outcome'] == 'ok' for row in download_log(cfg))
    assert all(wait <= 5 for p in clock.processes for wait in p.waits)


@pytest.mark.parametrize('case,expected_bytes,expected_time', [
    ('midway', 7, 70), ('connection', 0, 60), ('empty', 0, 60), ('hard_limit', 70, 70),
])
@pytest.mark.parametrize('ignore_terminate', [False, True])
def test_download_timeout_stops_without_retry_or_publication(
        cfg, prepared, monkeypatch, tmp_path, case, expected_bytes, expected_time, ignore_terminate):
    from ag import transport
    _, manifest = prepared
    assert transport.DOWNLOAD_STALL_SECONDS == 60
    assert transport.DOWNLOAD_HARD_LIMIT_SECONDS == 86400
    plan = dict(ignore_terminate=ignore_terminate)
    if case == 'midway':
        plan['writes'] = [(10, b'partial')]
    elif case == 'empty':
        plan['writes'] = [(5, b'')]
    elif case == 'hard_limit':
        monkeypatch.setattr(transport, 'DOWNLOAD_HARD_LIMIT_SECONDS', 70)
        plan['writes'] = [(t, b'x' * t) for t in range(5, 81, 5)]
    clock = fake_scp(monkeypatch, [plan])
    target = tmp_path / 'output.log'
    reason = 'hard_limit' if case == 'hard_limit' else 'stalled'
    with pytest.raises(transport.SSHConnectionError, match=reason):
        transport.SSHTransport(cfg, read_only=True).download(manifest, 'water.log', target)
    assert not target.exists() and len(clock.processes) == 1 and clock.sleeps == []
    process, = clock.processes
    assert process.terminated and process.killed == ignore_terminate
    assert process.poll() is not None
    assert clock.now == expected_time + (5 if ignore_terminate else 0)
    row, = download_log(cfg)
    assert row['outcome'] == 'timeout' and row['timeout_reason'] == reason
    assert row['transferred_bytes'] == expected_bytes
    assert row['error_class'] == 'other'  # same category as the old fixed timeout
    assert not any(value in json.dumps(row) for value in (str(target), cfg['ssh']['host']))


def test_manual_download_after_stall_uses_fresh_destination(cfg, prepared, monkeypatch, tmp_path):
    from ag.transport import SSHConnectionError, SSHTransport
    _, manifest = prepared
    clock = fake_scp(monkeypatch, [dict(writes=[(5, b'partial')]),
                                   dict(duration=1, writes=[(1, b'complete')])])
    t = SSHTransport(cfg, read_only=True)
    target = tmp_path / 'output.log'
    with pytest.raises(SSHConnectionError, match='stalled'):
        t.download(manifest, 'water.log', target)
    t.download(manifest, 'water.log', target)
    first, second = clock.processes
    assert first.target != second.target
    assert first.target.read_bytes() == b'partial' and target.read_bytes() == b'complete'
    assert clock.sleeps == []


def test_download_start_failure_is_logged(cfg, prepared, monkeypatch, tmp_path):
    from ag.transport import SSHTransport
    _, manifest = prepared
    def fail(*args, **kwargs):
        raise OSError('synthetic local failure')
    monkeypatch.setattr(subprocess, 'Popen', fail)
    target = tmp_path / 'output.log'
    with pytest.raises(TransportError, match='Could not start'):
        SSHTransport(cfg).download(manifest, 'water.log', target)
    assert not target.exists()
    assert download_log(cfg)[0]['outcome'] == 'start_failed'
