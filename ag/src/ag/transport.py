"""Bounded SSH/scp transport, replaceable with an inert test implementation."""
from dataclasses import dataclass
import os
import re
import shlex
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
        raise TransportError(f'{operation} failed (exit {result.returncode}); stop and inspect locally'
                             + (': ' + result.stderr.strip() if result.stderr.strip() else ''))
    return result.stdout


def redact_stderr(value, cfg):
    """Remove SSH endpoint/user identifiers before errors reach disk or CLI."""
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    value = str(value)
    secrets = {cfg['ssh']['host'], str(Path.home()), Path.home().name}
    for section in ('remote', 'local', 'ssh'):
        secrets.update(v for v in cfg.get(section, {}).values() if isinstance(v, str) and v.startswith('/'))
    try:
        for line in Path(cfg['ssh']['config_file']).read_text().splitlines():
            parts = shlex.split(re.sub(r'^([ \t]*[A-Za-z]+)[ \t]*=[ \t]*', r'\1 ', line), comments=True)
            if parts and parts[0].lower() in ('host', 'hostname', 'user', 'identityfile', 'hostkeyalias'):
                secrets.update(p for p in parts[1:] if p not in ('*', '?'))
    except (OSError, ValueError):
        pass
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            value = value.replace(secret, '[redacted]')
    value = re.sub(r'(?i)\b[\w.-]+@[\w.:-]+', '[redacted]', value)
    value = re.sub(r'(?i)(hostname |connecting to |authenticating to |connection to |connection (?:closed|reset) by |host [\'"]?)([^\s\'"]+)',
                   r'\1[redacted]', value)
    value = re.sub(r'(?i)(?:[a-z0-9_-]+\.)+[a-z0-9_-]+', '[redacted]', value)
    value = re.sub(r'(?i)(?<![\w])(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]*(?:%[a-z0-9]+)?', '[redacted]', value)
    value = re.sub(r"(?i)(as )['\"][^'\"]+['\"]", r'\1[redacted]', value)
    value = re.sub(r'(?i)(?:user(?:name)?[ =:]+)[^\s,;]+', 'user [redacted]', value)
    value = re.sub(r'/[^\s\'"]+', '[path]', value)
    return value[:4096]


# The live T1 SSH-255 incident motivated one bounded retry for observations.
# Submit/cancel retain the original single-attempt transport, including reads.
READ_OPERATIONS = frozenset({'identity', 'queues', 'nodes', 'jobs', 'root_check', 'executable',
                            'metadata', 'output_exists', 'listing', 'receipt',
                            'output_observation', 'completion_marker', 'session_processes',
                            'slurm_jobs', 'slurm_accounting', 'slurm_find', 'slurm_history',
                            'slurm_partitions', 'slurm_tools', 'storage_usage'})


class SSHTransport:
    def __init__(self, cfg, *, read_only=False):
        self.cfg = cfg
        self.read_only = read_only
        self.error_paths = []
        self.options = ['-F', cfg['ssh']['config_file'], '-o', 'BatchMode=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15']

    def _execute(self, argv, timeout):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            detail = redact_stderr(exc.stderr or '', self.cfg)
            raise SSHConnectionError('Remote operation timed out; 密钥可能已过期，请到网页重新下载' + (': ' + detail if detail else '')) from exc
        except OSError as exc:
            raise TransportError('Could not start SSH/scp locally') from exc
        return Result(p.returncode, p.stdout, redact_stderr(p.stderr, self.cfg))

    def record_to(self, paths):
        self.error_paths = list(paths)

    def _record_failure(self, detail):
        # Preserve even a recovered first SSH failure; never infer a new job
        # state or reissue a side effect because observation failed.
        from ag import journal, state
        safe = redact_stderr(detail, self.cfg)
        for path in self.error_paths:
            current = state.read(path)
            error = {'at': journal.now(), 'stderr': safe}
            state.write(path, current['state'], exit_status=current.get('exit_status'),
                        note=current.get('note'), ssh_error=error)
            journal.append(path.parent.parent, 'ssh_error', path.name, 'error', error)

    def _perform(self, operation):
        for index in range(2 if self.read_only else 1):
            try:
                result = operation()
            except SSHConnectionError as exc:
                self._record_failure(str(exc))
                if not self.read_only or index == 1:
                    raise
            else:
                if result.returncode == 255:
                    result.stderr = redact_stderr(result.stderr, self.cfg) + '; 密钥可能已过期，请到网页重新下载'
                    self._record_failure(result.stderr or 'SSH failed (exit 255; no stderr)')
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
        require_ok(self._perform(lambda: self._execute(
            ['scp', *self.options, str(local), self.cfg['ssh']['host'] + ':' + dest], 60)), 'upload')

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


_SSH_TRANSPORT_TYPE = SSHTransport


def bound_transport(transport, cfg):
    """Select the endpoint before any operation; injectable fakes stay inert."""
    if isinstance(transport, _SSH_TRANSPORT_TYPE):
        from ag.config import select_cluster
        if select_cluster(transport.cfg, cfg['_cluster']) == cfg:
            return transport
        return SSHTransport(cfg, read_only=transport.read_only)
    if hasattr(transport, 'for_cluster'):
        return transport.for_cluster(cfg)
    if hasattr(transport, 'cfg'):
        from ag.config import select_cluster
        original = select_cluster(transport.cfg, cfg['_cluster'])
        if original['ssh'] != cfg['ssh'] or original['remote'] != cfg['remote']:
            raise ValueError('Injected transport belongs to a different cluster')
    return transport
