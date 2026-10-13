"""Bounded SSH/scp transport, replaceable with an inert test implementation."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
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


def require_ok(result, operation):
    if result.returncode:
        raise TransportError(f'{operation} failed (exit {result.returncode}); stop and inspect locally')
    return result.stdout


class SSHTransport:
    def __init__(self, cfg):
        self.cfg = cfg
        self.options = ['-F', cfg['ssh']['config_file'], '-o', 'BatchMode=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15']

    def _execute(self, argv, timeout):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise TransportError('Remote operation interrupted or timed out; do not retry automatically') from exc
        return Result(p.returncode, p.stdout, p.stderr)

    def run(self, command):
        if not isinstance(command, remote.Command):
            raise ValueError('Transport requires a fixed remote command')
        return self._execute(['ssh', *self.options, self.cfg['ssh']['host'], '--', command.text], command.timeout)

    def upload(self, local, manifest, name):
        require_ok(self.run(remote.upload_check(self.cfg, manifest, name)), 'upload precheck')
        dest = remote.attempt_dir(self.cfg, manifest) + '/' + remote.filename(name)
        require_ok(self._execute(['scp', *self.options, str(local), self.cfg['ssh']['host'] + ':' + dest], 60), 'upload')

    def download(self, manifest, name, local):
        if local.exists() or local.is_symlink():
            raise ValueError('Download destination already exists')
        src = remote.attempt_dir(self.cfg, manifest) + '/' + remote.filename(name)
        require_ok(self._execute(['scp', *self.options, self.cfg['ssh']['host'] + ':' + src, str(local)], 60), 'download')
