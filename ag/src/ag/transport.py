"""Bounded SSH/scp transport, replaceable with an inert test implementation."""
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import json
import stat
import os
import re
import shlex
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Protocol
from ag import remote


# Slow relays must be allowed to make progress beyond a fixed minute, while
# dead connections and a child that never exits still have bounded lifetimes.
DOWNLOAD_STALL_SECONDS = 60
DOWNLOAD_HARD_LIMIT_SECONDS = 24 * 60 * 60


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


def error_class(detail, outcome):
    """Classify redacted stderr only; never include arbitrary error text."""
    if outcome == 'ok':
        return 'none'
    value = detail.lower()
    for category, patterns in (
        ('connection_refused', ('connection refused',)),
        ('connection_timeout', ('connection timed out', 'connection timeout', 'operation timed out')),
        ('connection_reset', ('connection reset', 'connection closed', 'broken pipe')),
        ('host_key', ('host key', 'host identification has changed', 'host [redacted] verification failed', 'host [redacted] has changed')),
        ('permission_denied', ('permission denied',)),
        ('operation_not_permitted', ('operation not permitted',)),
        ('name_resolution', ('could not resolve', 'name or service not known', 'name resolution', 'nodename nor servname')),
        ('network_unreachable', ('network is unreachable', 'network unreachable', 'no route to host')),
    ):
        if any(pattern in value for pattern in patterns):
            return category
    return 'other'


# The live T1 SSH-255 incident motivated one bounded retry for observations.
# Submit/cancel retain the original single-attempt transport, including reads.
READ_OPERATIONS = frozenset({'identity', 'queues', 'nodes', 'jobs', 'root_check', 'executable',
                            'metadata', 'parent_chk_metadata', 'parent_chk_environment', 'output_exists', 'listing', 'receipt',
                            'output_observation', 'completion_marker', 'session_processes',
                            'slurm_jobs', 'slurm_accounting', 'slurm_find', 'slurm_history',
                            'slurm_evidence_config', 'slurm_evidence_version',
                            'slurm_evidence_job', 'slurm_evidence_history',
                            'slurm_partitions', 'slurm_tools', 'storage_usage'})


class SSHTransport:
    def __init__(self, cfg, *, read_only=False):
        self.cfg = cfg
        self.read_only = read_only
        self.error_paths = []
        self._connect_timeout_seconds = cfg['ssh'].get('connect_timeout_seconds', 15)
        self.options = ['-F', cfg['ssh']['config_file'], '-o', 'BatchMode=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o',
                        f'ConnectTimeout={self._connect_timeout_seconds}']

    @property
    def extra_connect_seconds(self):
        """Keep the existing command/transfer allowance on slow connections."""
        return self._connect_timeout_seconds - 15

    def _log_call(self, tool, operation, attempt, outcome, returncode, duration, detail,
                  *, timeout_reason=None, transferred_bytes=None):
        # Diagnose refused connections without persisting endpoint/command data.
        at = datetime.now(timezone.utc)
        cluster = self.cfg.get('_cluster', 'default')
        row = dict(at=at.isoformat(), cluster=cluster, tool=tool, operation=operation,
                   attempt=attempt, outcome=outcome, returncode=returncode,
                   duration_s=round(duration, 3), error_class=error_class(detail, outcome))
        if timeout_reason is not None:
            row.update(timeout_reason=timeout_reason, transferred_bytes=transferred_bytes)
        directory_fd = file_fd = None
        failure = None
        try:
            # The configured location may legitimately traverse a symlink. Keep
            # the log directory/file themselves protected against redirection.
            directory = Path(self.cfg['_config_dir']).resolve() / 'ssh-log'
            if directory.is_symlink():
                raise OSError(errno.ELOOP, 'Symbolic link')
            directory.mkdir(mode=0o700, exist_ok=True)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            file_fd = os.open(f'{cluster}-{at:%Y-%m}.jsonl',
                              os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                              0o600, dir_fd=directory_fd)
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise OSError(errno.EINVAL, 'Not a regular log file')
            os.fchmod(file_fd, 0o600)
            data = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
            if os.write(file_fd, data) != len(data):
                raise OSError(errno.EIO, 'Incomplete log write')
        except RuntimeError:
            # pathlib.resolve reports symlink loops this way on older Python.
            failure = 'symlink'
        except OSError as exc:
            failure = {errno.ELOOP: 'symlink', errno.EACCES: 'permission',
                       errno.EPERM: 'permission', errno.EROFS: 'permission',
                       errno.EINVAL: 'not_regular', errno.EISDIR: 'not_regular',
                       errno.ENXIO: 'not_regular', errno.ENOTDIR: 'not_regular'}.get(exc.errno, 'io')
        finally:
            for fd in (file_fd, directory_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        failure = failure or 'io'
        # A monitor process can create several transports; warn once across all
        # of them, including when the warning stream itself is unavailable.
        if failure and not getattr(SSHTransport._log_call, '_warning_emitted', False):
            SSHTransport._log_call._warning_emitted = True
            try:
                print(f'Warning: could not write local SSH log ({failure}); operation continues.', file=sys.stderr)
            except OSError:
                pass  # Even an unavailable warning stream cannot alter the operation.

    def _execute(self, argv, timeout, *, observe_stderr=None):
        # Monitor classification needs raw stderr before redaction. Keep that
        # in-memory observation here so subprocess/error handling cannot drift.
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if observe_stderr is not None:
                observe_stderr(exc.stderr or '')
            detail = redact_stderr(exc.stderr or '', self.cfg)
            raise SSHConnectionError('Remote operation timed out; 密钥可能已过期，请到网页重新下载' + (': ' + detail if detail else '')) from exc
        except OSError as exc:
            raise TransportError('Could not start SSH/scp locally') from exc
        if observe_stderr is not None:
            observe_stderr(p.stderr if p.returncode else '')
        return Result(p.returncode, p.stdout, redact_stderr(p.stderr, self.cfg))

    def _logged_execute(self, argv, timeout, operation, attempt):
        # Keep both existing hooks intact: incomplete fetch overrides _perform
        # to stop at the first failure, and transport fakes replace _execute.
        started = time.monotonic()
        outcome, returncode, detail = 'start_failed', None, ''
        try:
            try:
                result = self._execute(argv, timeout)
            except SSHConnectionError as exc:
                outcome = 'timeout'
                detail = redact_stderr(getattr(exc.__cause__, 'stderr', '') or '', self.cfg)
                raise
            except TransportError as exc:
                detail = redact_stderr(str(exc.__cause__ or exc), self.cfg)
                raise
            returncode = result.returncode
            outcome = 'ok' if returncode == 0 else 'exit'
            detail = result.stderr  # _execute already redacts subprocess stderr.
            return result
        finally:
            self._log_call(argv[0], operation, attempt, outcome, returncode,
                           time.monotonic() - started, detail)

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

    def _perform(self, operation, *, allow_retry=True):
        retry = self.read_only and allow_retry
        for index in range(2 if retry else 1):
            try:
                result = operation()
            except SSHConnectionError as exc:
                self._record_failure(str(exc))
                if not retry or index == 1:
                    raise
            else:
                if result.returncode == 255:
                    result.stderr = redact_stderr(result.stderr, self.cfg) + '; 密钥可能已过期，请到网页重新下载'
                    self._record_failure(result.stderr or 'SSH failed (exit 255; no stderr)')
                if result.returncode != 255 or not retry or index == 1:
                    return result
            print('Read-only SSH connection failed; retrying once in 15 seconds.', file=sys.stderr)
            time.sleep(15)
        raise AssertionError('Unreachable retry state')

    def run(self, command):
        if not isinstance(command, remote.Command):
            raise ValueError('Transport requires a fixed remote command')
        if self.read_only and command.operation not in READ_OPERATIONS:
            raise ValueError('Read-only transport refuses remote writes')
        index = 0

        def run_once():
            nonlocal index
            index += 1
            return self._logged_execute(
                ['ssh', *self.options, self.cfg['ssh']['host'], '--', command.text],
                command.timeout + self.extra_connect_seconds, command.operation, index)

        # Formal autonomy evidence must retain and stop at the first SSH error;
        # a successful retry cannot erase the uncertainty of that observation.
        if command.operation in ('slurm_evidence_config', 'slurm_evidence_version',
                                 'slurm_evidence_job', 'slurm_evidence_history'):
            return self._perform(run_once, allow_retry=False)
        return self._perform(run_once)

    def upload(self, local, manifest, name):
        if self.read_only:
            raise ValueError('Read-only transport refuses uploads')
        require_ok(self.run(remote.upload_check(self.cfg, manifest, name)), 'upload precheck')
        dest = remote.attempt_dir(self.cfg, manifest) + '/' + remote.filename(name)
        require_ok(self._perform(lambda: self._logged_execute(
            ['scp', *self.options, str(local), self.cfg['ssh']['host'] + ':' + dest],
            60 + self.extra_connect_seconds, 'upload', 1)), 'upload')

    def download(self, manifest, name, local):
        local = Path(local)
        if local.exists() or local.is_symlink():
            raise ValueError('Download destination already exists')
        src = remote.attempt_dir(self.cfg, manifest) + '/' + remote.filename(name)
        candidate = None
        index = 0
        timeout_reason = None
        stall_seconds = DOWNLOAD_STALL_SECONDS + self.extra_connect_seconds

        def download_once():
            nonlocal candidate, index, timeout_reason
            index += 1
            # A failed scp may leave bytes behind. Each try uses a fresh local
            # destination so neither a partial nor a published file is replaced.
            candidate = Path(tempfile.mkdtemp(prefix='.download-', dir=local.parent)) / name
            argv = ['scp', *self.options, self.cfg['ssh']['host'] + ':' + src, str(candidate)]
            started = last_progress = time.monotonic()
            transferred = 0
            outcome, returncode, detail = 'start_failed', None, ''
            try:
                try:
                    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               text=True, start_new_session=True)
                except OSError as exc:
                    detail = redact_stderr(str(exc), self.cfg)
                    raise TransportError('Could not start SSH/scp locally') from exc
                try:
                    while True:
                        now = time.monotonic()
                        interval = max(0, min(5, stall_seconds - (now - last_progress),
                                              DOWNLOAD_HARD_LIMIT_SECONDS - (now - started)))
                        try:
                            stdout, stderr = process.communicate(timeout=interval)
                            returncode = process.returncode
                            outcome = 'ok' if returncode == 0 else 'exit'
                            detail = redact_stderr(stderr, self.cfg)
                            return Result(returncode, stdout, detail)
                        except subprocess.TimeoutExpired:
                            now = time.monotonic()
                            size = candidate.stat().st_size if candidate.exists() else 0
                            if size != transferred:
                                transferred, last_progress = size, now
                            if now - started >= DOWNLOAD_HARD_LIMIT_SECONDS:
                                timeout_reason = 'hard_limit'
                            elif now - last_progress >= stall_seconds:
                                timeout_reason = 'stalled'
                            else:
                                continue
                            outcome = 'timeout'
                            raise subprocess.TimeoutExpired(argv, now - started) from None
                finally:
                    # Include scp's SSH child: it can otherwise keep the pipes
                    # open after scp exits and defeat the timeout while reaping.
                    if timeout_reason is not None or process.poll() is None:
                        def stop_group(sig):
                            try:
                                os.killpg(process.pid, sig)
                            except ProcessLookupError:
                                pass  # The process group already exited.

                        stop_group(signal.SIGTERM)
                        try:
                            process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            stop_group(signal.SIGKILL)
                            process.communicate()
            finally:
                self._log_call('scp', 'download', index, outcome, returncode,
                               time.monotonic() - started, detail,
                               timeout_reason=timeout_reason, transferred_bytes=transferred)

        try:
            result = self._perform(download_once)
        except subprocess.TimeoutExpired as exc:
            # Preserve the connection-error category, but a stalled download
            # needs human inspection, not the ordinary read-only SSH retry.
            message = f'Download timed out ({timeout_reason}); stop and inspect locally'
            self._record_failure(message)
            raise SSHConnectionError(message) from exc
        require_ok(result, 'download')
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
