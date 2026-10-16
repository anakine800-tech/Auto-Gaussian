"""T51 local diagnostic logs; all subprocesses are synthetic."""
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest
from ag import remote
from ag.transport import Result, SSHTransport, SSHConnectionError, TransportError
from test_core import cfg, prepared


def rows(cfg):
    files = list((Path(cfg['_config_dir']) / 'ssh-log').glob('*.jsonl'))
    assert len(files) == 1
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    data = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert files[0].name == f"{data[0]['cluster']}-{data[0]['at'][:7]}.jsonl"
    return data


@pytest.mark.parametrize('outcome', ['ok', 'exit', 'timeout', 'start_failed'])
def test_outcomes_and_redaction(cfg, monkeypatch, outcome):
    secret = 'host-private.invalid private-user ' + str(Path(cfg['_config_dir']) / 'private-key')
    def execute(*args, **kwargs):
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired('ssh', 15, stderr=secret.encode())
        if outcome == 'start_failed':
            raise OSError(errno.EACCES, secret)
        return Result(0 if outcome == 'ok' else 1, stderr=secret)
    monkeypatch.setattr(subprocess, 'run', execute)
    clock = iter([10.0, 10.123456])
    monkeypatch.setattr('ag.transport.time.monotonic', lambda: next(clock))
    t = SSHTransport(cfg)
    if outcome in ('timeout', 'start_failed'):
        with pytest.raises(SSHConnectionError if outcome == 'timeout' else TransportError):
            t.run(remote.jobs())
    else:
        assert t.run(remote.jobs()).returncode == (0 if outcome == 'ok' else 1)
    row, = rows(cfg)
    assert set(row) == {'at', 'cluster', 'tool', 'operation', 'attempt', 'outcome', 'returncode', 'duration_s', 'error_class'}
    assert datetime.fromisoformat(row['at']).utcoffset().total_seconds() == 0
    assert row == dict(at=row['at'], cluster='default', tool='ssh', operation='jobs', attempt=1,
                       outcome=outcome, returncode={'ok': 0, 'exit': 1}.get(outcome), duration_s=0.123,
                       error_class='none' if outcome == 'ok' else 'other')
    raw = json.dumps(row)
    for value in ('host-private', 'private-user', 'private-key', cfg['_config_dir'], cfg['ssh']['host']):
        assert value not in raw


@pytest.mark.parametrize('message,category', [
    ('connect to host private.invalid: Connection refused', 'connection_refused'),
    ('Operation not permitted', 'operation_not_permitted'),
    ('Connection timed out', 'connection_timeout'),
    ('Connection reset by peer', 'connection_reset'),
    ('Permission denied (publickey)', 'permission_denied'),
    ('Host key verification failed.', 'host_key'),
    ('REMOTE HOST IDENTIFICATION HAS CHANGED!', 'host_key'),
    ('Could not resolve hostname private.invalid', 'name_resolution'),
    ('Network is unreachable', 'network_unreachable'),
    ('unexpected synthetic diagnostic', 'other'),
])
def test_error_classes(cfg, monkeypatch, message, category):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(255, stderr=message))
    SSHTransport(cfg).run(remote.identity())
    assert rows(cfg)[0]['error_class'] == category


@pytest.mark.parametrize('first', ['exit', 'timeout'])
def test_read_retry_logs_each_call(cfg, monkeypatch, first):
    calls = []
    def execute(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            if first == 'timeout':
                raise subprocess.TimeoutExpired('ssh', 15, stderr='Connection timed out')
            return Result(255, stderr='Connection refused')
        return Result()
    monkeypatch.setattr(subprocess, 'run', execute)
    monkeypatch.setattr('ag.transport.time.sleep', lambda seconds: None)
    assert SSHTransport(cfg, read_only=True).run(remote.jobs()).returncode == 0
    data = rows(cfg)
    assert [r['attempt'] for r in data] == [1, 2]
    assert [r['outcome'] for r in data] == [first, 'ok']


@pytest.mark.parametrize('failure', ['directory_link', 'file_link', 'unwritable', 'write', 'close'])
def test_logging_failure_never_changes_operation(cfg, tmp_path, monkeypatch, capsys, failure):
    directory = Path(cfg['_config_dir']) / 'ssh-log'
    target = tmp_path / 'untouched'
    if failure == 'directory_link':
        target.mkdir()
        directory.symlink_to(target, target_is_directory=True)
    elif failure == 'file_link':
        directory.mkdir()
        target.write_text('untouched')
        (directory / f'default-{datetime.now(timezone.utc).strftime("%Y-%m")}.jsonl').symlink_to(target)
    elif failure == 'unwritable':
        original = os.open
        def denied(path, *a, **k):
            if Path(path) == directory:
                raise PermissionError(errno.EACCES, 'synthetic private detail')
            return original(path, *a, **k)
        monkeypatch.setattr(os, 'open', denied)
    elif failure == 'write':
        def failed(*a):
            raise OSError('synthetic private detail')
        monkeypatch.setattr(os, 'write', failed)
    else:
        original = os.close
        def failed(fd):
            original(fd)
            raise OSError('synthetic private detail')
        monkeypatch.setattr(os, 'close', failed)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(stdout='success'))
    assert SSHTransport(cfg).run(remote.jobs()).stdout == 'success'
    warning = capsys.readouterr().err
    assert warning.count('Warning:') == 1 and 'private detail' not in warning
    if failure == 'directory_link':
        assert not list(target.iterdir())
    if failure == 'file_link':
        assert target.read_text() == 'untouched'


def test_upload_and_download_operations(cfg, prepared, tmp_path, monkeypatch):
    path, manifest = prepared
    def execute(argv, **kwargs):
        if argv[0] == 'scp' and ':' in argv[-2]:
            Path(argv[-1]).write_bytes(b'synthetic')
        return Result()
    monkeypatch.setattr(subprocess, 'run', execute)
    t = SSHTransport(cfg)
    t.upload(path / 'inputs/water.gjf', manifest, 'water.gjf')
    t.download(manifest, 'water.log', tmp_path / 'download.log')
    data = rows(cfg)
    assert [(r['tool'], r['operation']) for r in data] == [('ssh', 'upload_check'), ('scp', 'upload'), ('scp', 'download')]
    assert all(r['attempt'] == 1 for r in data)


def test_scp_retry_records_each_attempt(cfg, prepared, tmp_path, monkeypatch):
    _, manifest = prepared
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b'partial' if len(calls) == 1 else b'complete')
        return Result(255 if len(calls) == 1 else 0, stderr='Connection refused' if len(calls) == 1 else '')
    monkeypatch.setattr(subprocess, 'run', execute)
    monkeypatch.setattr('ag.transport.time.sleep', lambda seconds: None)
    destination = tmp_path / 'result.log'
    SSHTransport(cfg, read_only=True).download(manifest, 'water.log', destination)
    data = rows(cfg)
    assert [(r['tool'], r['operation'], r['attempt'], r['outcome']) for r in data] == [
        ('scp', 'download', 1, 'exit'), ('scp', 'download', 2, 'ok')]
    assert destination.read_bytes() == b'complete'
    assert Path(calls[0][-1]).read_bytes() == b'partial'


def test_append_preserves_history_and_restricts_existing_permissions(cfg, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result())
    t = SSHTransport(cfg)
    t.run(remote.jobs())
    directory = Path(cfg['_config_dir']) / 'ssh-log'
    file, = directory.glob('*.jsonl')
    before = file.read_bytes()
    file.chmod(0o644)
    older = directory / 'default-2000-01.jsonl'
    older.write_text('historical marker')
    t.run(remote.identity())
    assert file.read_bytes().startswith(before)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert [json.loads(line)['operation'] for line in file.read_text().splitlines()] == ['jobs', 'identity']
    assert older.read_text() == 'historical marker'
