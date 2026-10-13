"""Bounded SSH/scp transport, replaceable with an inert test implementation."""
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Protocol
from ag import remote


@dataclass
class Result:
    returncode: int = 0
    stdout: str = ''
    stderr: str = ''


class Transport(Protocol):
    def run(self, command: remote.Command) -> Result: ...
    def upload(self, local: Path, manifest: dict, name: str) -> None: ...
    def download(self, manifest: dict, name: str, local: Path) -> None: ...


class TransportError(OSError):
    pass


class SSHConnectionError(TransportError):
    """A connection interruption eligible for one retry in read-only commands."""


def require_ok(result, operation):
    if result.returncode:
        raise TransportError(f'{operation} failed (exit {result.returncode}); stop and inspect locally')
    return result.stdout


# The live T1 SSH-255 incident motivated one bounded retry for observations.
# Submit/cancel retain the original single-attempt transport, including reads.
READ_OPERATIONS = frozenset({'identity', 'queues', 'jobs', 'root_check', 'executable',
                            'metadata', 'output_exists', 'listing'})


class SSHTransport:
    def __init__(self, cfg, *, read_only=False):
        self.cfg = cfg
        self.read_only = read_only
        self.options = ['-F', cfg['ssh']['config_file'], '-o', 'BatchMode=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15']

    def _execute(self, argv, timeout):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise SSHConnectionError('Remote operation timed out') from exc
        except OSError as exc:
            raise TransportError('Could not start SSH/scp locally') from exc
        return Result(p.returncode, p.stdout, p.stderr)

    def _perform(self, operation):
        for index in range(2 if self.read_only else 1):
            try:
                result = operation()
            except SSHConnectionError:
                if not self.read_only or index == 1:
                    raise
            else:
                if result.returncode != 255 or not self.read_only or index == 1:
                    return result
            print('Read-only SSH connection failed; retrying once in 15 seconds.', file=sys.stderr)
            time.sleep(15)
        raise AssertionError('Unreachable retry state')

    def run(self, command):
        if not isinstance(command, remote.Command):
            raise ValueError('Transport requires a fixed remote command')
        if self.read_only and command.operation not in READ_OPERATIONS:
            raise ValueError('Read-only transport refuses remote writes')
        return self._perform(lambda: self._execute(
            ['ssh', *self.options, self.cfg['ssh']['host'], '--', command.text], command.timeout))

    def upload(self, local, manifest, name):
        if self.read_only:
            raise ValueError('Read-only transport refuses uploads')
        require_ok(self.run(remote.upload_check(self.cfg, manifest, name)), 'upload precheck')
        dest = remote.attempt_dir(self.cfg, manifest) + '/' + remote.filename(name)
        require_ok(self._execute(['scp', *self.options, str(local), self.cfg['ssh']['host'] + ':' + dest], 60), 'upload')

    def download(self, manifest, name, local):
        local = Path(local)
        if local.exists() or local.is_symlink():
            raise ValueError('Download destination already exists')
        src = remote.attempt_dir(self.cfg, manifest) + '/' + remote.filename(name)
        candidate = None

        def download_once():
            nonlocal candidate
            # A failed scp may leave bytes behind. Each try uses a fresh local
            # destination so neither a partial nor a published file is replaced.
            candidate = Path(tempfile.mkdtemp(prefix='.download-', dir=local.parent)) / name
            return self._execute(['scp', *self.options, self.cfg['ssh']['host'] + ':' + src, str(candidate)], 60)

        require_ok(self._perform(download_once), 'download')
        os.link(candidate, local)
