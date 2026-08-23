"""Package-private fixed RTwin operation table and controlled driver seam."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from typing import BinaryIO, Final, Protocol

from auto_g16.execution import ExecutionSnapshot

from ._bridge import _BRIDGE_LAUNCHER_BYTES, _SERVER_AGENT_BYTES
from ._canonical import TransportBoundaryError, canonical_bytes


_FIXED_ENV: Final = {
    "LANG": "C",
    "LC_ALL": "C",
    "PYTHONNOUSERSITE": "1",
    "PYTHONUTF8": "1",
}

_TABLE_OBJECT: Final = {
    "version": "auto-g16-rtwin-operation-table/1",
    "cwd_policy": "exact-remote-attempt-workspace",
    "shell": False,
    "env": _FIXED_ENV,
    "limits": {
        "max_artifact_requests": 4,
        "max_artifact_bytes": 134217728,
        "max_capture_bytes": 268435456,
    },
    "operations": [
        {
            "name": "allocate",
            "token": "mkdir-attempt",
            "argv_template": [],
            "timeout_seconds": 30,
            "stdout_cap": 65536,
            "stderr_cap": 65536,
        },
        {
            "name": "stage",
            "token": "stage-exact-bytes",
            "argv_template": ["{logical_name}", "{sha256}", "{size_bytes}"],
            "timeout_seconds": 900,
            "stdout_cap": 65536,
            "stderr_cap": 65536,
        },
        {
            "name": "qsub",
            "token": "qsub",
            "argv_template": ["{pbs_basename}"],
            "timeout_seconds": 30,
            "stdout_cap": 65536,
            "stderr_cap": 65536,
        },
        {
            "name": "qstat",
            "token": "qstat",
            "argv_template": ["-f", "{job_id}"],
            "timeout_seconds": 30,
            "stdout_cap": 262144,
            "stderr_cap": 65536,
        },
        {
            "name": "fetch",
            "token": "fetch-exact-bytes",
            "argv_template": ["{remote_relative_name}"],
            "timeout_seconds": 900,
            "stdout_cap": 0,
            "stderr_cap": 65536,
        },
    ],
}
_OPERATION_TABLE_BYTES: Final = canonical_bytes(_TABLE_OBJECT)
_OPERATION_TABLE_SHA256: Final = (
    "3502638017454526cdbfee01de47a543a9870c9c57697e4373732cb7909a71d1"
)
if len(_OPERATION_TABLE_BYTES) != 1040:
    raise RuntimeError("source-controlled RTwin operation table size drifted")
from hashlib import sha256 as _sha256  # noqa: E402

if _sha256(_OPERATION_TABLE_BYTES).hexdigest() != _OPERATION_TABLE_SHA256:
    raise RuntimeError("source-controlled RTwin operation table digest drifted")


@dataclass(frozen=True, slots=True)
class _Operation:
    name: str
    token: str
    timeout_seconds: int
    stdout_cap: int
    stderr_cap: int


_OPERATIONS: Final = {
    item["name"]: _Operation(
        name=item["name"],
        token=item["token"],
        timeout_seconds=item["timeout_seconds"],
        stdout_cap=item["stdout_cap"],
        stderr_cap=item["stderr_cap"],
    )
    for item in _TABLE_OBJECT["operations"]
}


@dataclass(frozen=True, slots=True, kw_only=True)
class _Invocation:
    operation: _Operation
    argv: tuple[str, ...]
    cwd: str
    input_bytes: bytes | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class _TextResult:
    stdout: bytes
    stderr: bytes
    returncode: int | None
    eof_stdout: bool
    eof_stderr: bool
    completion_status: str

    def __post_init__(self) -> None:
        if type(self.stdout) is not bytes or type(self.stderr) is not bytes:
            raise TransportBoundaryError("driver text streams must be exact bytes")
        if self.returncode is not None and (
            isinstance(self.returncode, bool) or not isinstance(self.returncode, int)
        ):
            raise TransportBoundaryError("driver returncode must be an integer or null")
        if type(self.eof_stdout) is not bool or type(self.eof_stderr) is not bool:
            raise TransportBoundaryError("driver EOF fields must be exact booleans")
        if self.completion_status not in {"completed", "timeout", "transport-error"}:
            raise TransportBoundaryError("driver completion status is outside the closed set")
        if self.completion_status == "completed" and (
            self.returncode is None or not self.eof_stdout or not self.eof_stderr
        ):
            raise TransportBoundaryError("completed driver result lacks completion/EOF")


@dataclass(frozen=True, slots=True, kw_only=True)
class _FetchResult:
    status: str
    content: bytes = b""
    before_identity: str | None = None
    after_identity: str | None = None
    before_size: int | None = None
    after_size: int | None = None
    before_sha256: str | None = None
    after_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"found", "missing", "unstable", "transport-error"}:
            raise TransportBoundaryError("fetch driver status is outside the closed set")
        if type(self.content) is not bytes:
            raise TransportBoundaryError("fetch content must be exact immutable bytes")
        metadata = (
            self.before_identity,
            self.after_identity,
            self.before_size,
            self.after_size,
            self.before_sha256,
            self.after_sha256,
        )
        if self.status != "found":
            if self.content or any(item is not None for item in metadata):
                raise TransportBoundaryError("non-found fetch result carries artifact evidence")
            return
        if (
            not isinstance(self.before_identity, str)
            or not self.before_identity
            or not isinstance(self.after_identity, str)
            or not self.after_identity
            or isinstance(self.before_size, bool)
            or not isinstance(self.before_size, int)
            or self.before_size < 0
            or isinstance(self.after_size, bool)
            or not isinstance(self.after_size, int)
            or self.after_size < 0
            or not isinstance(self.before_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.before_sha256) is None
            or not isinstance(self.after_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.after_sha256) is None
        ):
            raise TransportBoundaryError("found fetch result metadata is not type-closed")


def _is_text_result_closed(value: object) -> bool:
    return (
        isinstance(value, _TextResult)
        and type(value.stdout) is bytes
        and type(value.stderr) is bytes
        and (
            value.returncode is None
            or (not isinstance(value.returncode, bool) and isinstance(value.returncode, int))
        )
        and type(value.eof_stdout) is bool
        and type(value.eof_stderr) is bool
        and value.completion_status in {"completed", "timeout", "transport-error"}
        and (
            value.completion_status != "completed"
            or (
                value.returncode is not None
                and value.eof_stdout
                and value.eof_stderr
            )
        )
    )


def _is_fetch_result_closed(value: object) -> bool:
    if not isinstance(value, _FetchResult) or type(value.content) is not bytes:
        return False
    metadata = (
        value.before_identity,
        value.after_identity,
        value.before_size,
        value.after_size,
        value.before_sha256,
        value.after_sha256,
    )
    if value.status in {"missing", "unstable", "transport-error"}:
        return not value.content and all(item is None for item in metadata)
    return (
        value.status == "found"
        and isinstance(value.before_identity, str)
        and bool(value.before_identity)
        and isinstance(value.after_identity, str)
        and bool(value.after_identity)
        and not isinstance(value.before_size, bool)
        and isinstance(value.before_size, int)
        and value.before_size >= 0
        and not isinstance(value.after_size, bool)
        and isinstance(value.after_size, int)
        and value.after_size >= 0
        and isinstance(value.before_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", value.before_sha256) is not None
        and isinstance(value.after_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", value.after_sha256) is not None
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _BoundedProcessResult:
    stdout: bytes
    stderr: bytes
    binary_result: bytes
    returncode: int | None
    eof_stdout: bool
    eof_stderr: bool
    eof_binary_result: bool
    completion_status: str


class _RTWinDriver(Protocol):
    def invoke_text(
        self, snapshot: ExecutionSnapshot, invocation: _Invocation
    ) -> _TextResult: ...

    def invoke_fetch(
        self, snapshot: ExecutionSnapshot, invocation: _Invocation
    ) -> _FetchResult: ...


_FETCH_HEADER = re.compile(
    rb"\AAUTO-G16-FETCH/1\nidentity=([^\n]+)\nsize=([0-9]+)\nsha256=([0-9a-f]{64})\n\n",
)


class _SubprocessRTWinDriver:
    """Live-capable bridge driver; construction performs no operation."""

    def _open_bridge(self, snapshot: ExecutionSnapshot) -> BinaryIO:
        paths = snapshot.resolved_server_profile.platform_paths
        bridge = paths["rtwin_bridge_executable"]
        assert isinstance(bridge, str)
        identity = snapshot.resolved_server_profile.runtime_identities["rtwin-bridge"]
        expected_digest = identity["sha256"]
        expected_size = identity["size_bytes"]
        assert isinstance(expected_digest, str) and isinstance(expected_size, int)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(bridge, flags)
        except OSError as exc:
            raise TransportBoundaryError("RTwin bridge executable is unavailable") from exc
        try:
            opened = os.fstat(descriptor)
            named = os.stat(bridge, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or opened.st_mode & 0o111 == 0
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or opened.st_size != expected_size
            ):
                raise TransportBoundaryError("RTwin bridge executable identity drifted")
            chunks: list[bytes] = []
            remaining = expected_size
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    raise TransportBoundaryError("RTwin bridge executable read was short")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise TransportBoundaryError("RTwin bridge executable grew during attestation")
            exact_bytes = b"".join(chunks)
            if _sha256(exact_bytes).hexdigest() != expected_digest:
                raise TransportBoundaryError("RTwin bridge executable bytes drifted")
            if exact_bytes != _BRIDGE_LAUNCHER_BYTES:
                raise TransportBoundaryError("RTwin bridge is not the source-controlled launcher")
            agent = snapshot.resolved_server_profile.runtime_identities["rtwin-pbs-v1"]
            if agent != {
                "sha256": _sha256(_SERVER_AGENT_BYTES).hexdigest(),
                "size_bytes": len(_SERVER_AGENT_BYTES),
            }:
                raise TransportBoundaryError("RTwin server agent bytes drifted")
            named_after = os.stat(bridge, follow_symlinks=False)
            if (
                not stat.S_ISREG(named_after.st_mode)
                or (named_after.st_dev, named_after.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise TransportBoundaryError("RTwin bridge executable was replaced")
            # Execute only a private unlinked copy of the already-hashed bytes.
            # The caller-supplied inode may remain writable and therefore is not
            # itself an execution source after attestation.
            sealed = tempfile.TemporaryFile(mode="w+b")
            try:
                sealed.write(exact_bytes)
                sealed.flush()
                os.fsync(sealed.fileno())
                os.fchmod(sealed.fileno(), 0o500)
                sealed.seek(0)
            except Exception:
                sealed.close()
                raise
            os.close(descriptor)
            return sealed
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise

    def _command(
        self, snapshot: ExecutionSnapshot, invocation: _Invocation
    ) -> tuple[str, ...]:
        paths = snapshot.resolved_server_profile.platform_paths
        bridge = paths["rtwin_bridge_executable"]
        assert isinstance(bridge, str)
        target = snapshot.resolved_server_profile.target_identity
        packet = {
            "schema": "auto-g16-rtwin-bridge-request/1",
            "operation": invocation.operation.token,
            "argv": list(invocation.argv),
            "cwd": invocation.cwd,
            "remote_root": snapshot.resolved_server_profile.remote_root,
            "attempt_id": snapshot.attempt_id,
            "execution_snapshot_id": snapshot.execution_snapshot_id,
            "submission_intent_id": snapshot.submission_intent_id,
            "target_identity": {
                "destination_host": target["destination_host"],
                "destination_port": target["destination_port"],
                "jump_topology": [dict(item) for item in target["jump_topology"]],
            },
            "remote_user": snapshot.resolved_server_profile.remote_user,
            "platform_paths": {
                key: paths[key]
                for key in (
                    "rtwin_root",
                    "known_hosts",
                    "mac_ssh_executable",
                    "mac_scp_executable",
                    "rtwin_ssh_executable",
                    "rtwin_scp_executable",
                    "server_python_executable",
                    "server_qsub_executable",
                    "server_qstat_executable",
                )
            },
            "runtime_identities": {
                key: dict(snapshot.resolved_server_profile.runtime_identities[key])
                for key in (
                    "auto-g16-rtwin-operation-table/1",
                    "rtwin-pbs-v1",
                    "mac-ssh",
                    "mac-scp",
                    "rtwin-ssh",
                    "rtwin-scp",
                    "rtwin-bridge",
                    "server-python",
                    "server-qsub",
                    "server-qstat",
                )
            },
        }
        encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"))
        return (bridge, "--request-json", encoded)

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            try:
                process.kill()
            except OSError:
                pass

    def _run_bounded(
        self,
        snapshot: ExecutionSnapshot,
        invocation: _Invocation,
        *,
        binary_result_cap: int | None,
    ) -> _BoundedProcessResult:
        sealed: BinaryIO | None = None
        result_read = -1
        result_write = -1
        process: subprocess.Popen[bytes] | None = None
        try:
            sealed = self._open_bridge(snapshot)
            command = self._command(snapshot, invocation)
            pass_fds = [sealed.fileno()]
            if binary_result_cap is not None:
                result_read, result_write = os.pipe()
                command = (*command, "--result-fd", str(result_write))
                pass_fds.append(result_write)
            process = subprocess.Popen(
                command,
                executable=f"/dev/fd/{sealed.fileno()}",
                pass_fds=tuple(pass_fds),
                stdin=subprocess.PIPE if invocation.input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(_FIXED_ENV),
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
            if result_write >= 0:
                os.close(result_write)
                result_write = -1
            if process.stdout is None or process.stderr is None:
                raise OSError("bounded bridge pipes are unavailable")

            selector = selectors.DefaultSelector()
            buffers = {
                "stdout": bytearray(),
                "stderr": bytearray(),
                "binary": bytearray(),
            }
            caps = {
                "stdout": invocation.operation.stdout_cap,
                "stderr": invocation.operation.stderr_cap,
                "binary": binary_result_cap or 0,
            }
            eof = {"stdout": False, "stderr": False, "binary": binary_result_cap is None}
            streams: dict[str, object] = {
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
            for name in ("stdout", "stderr"):
                stream = streams[name]
                assert hasattr(stream, "fileno")
                os.set_blocking(stream.fileno(), False)  # type: ignore[union-attr]
                selector.register(stream, selectors.EVENT_READ, ("read", name))
            if result_read >= 0:
                os.set_blocking(result_read, False)
                streams["binary"] = result_read
                selector.register(result_read, selectors.EVENT_READ, ("read", "binary"))

            input_bytes = invocation.input_bytes
            input_position = 0
            if input_bytes is not None:
                if process.stdin is None:
                    raise OSError("bounded bridge stdin is unavailable")
                if not input_bytes:
                    process.stdin.close()
                else:
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE, ("write", "stdin"))

            deadline = time.monotonic() + invocation.operation.timeout_seconds
            status = "completed"
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timeout"
                    break
                events = selector.select(min(remaining, 0.1))
                for key, _mask in events:
                    direction, name = key.data
                    if direction == "write":
                        assert input_bytes is not None and process.stdin is not None
                        try:
                            count = os.write(
                                process.stdin.fileno(),
                                input_bytes[input_position : input_position + 65_536],
                            )
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                            continue
                        input_position += count
                        if input_position == len(input_bytes):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    cap = caps[name]
                    descriptor = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                    chunk = os.read(descriptor, min(65_536, cap - len(buffers[name]) + 1))
                    if not chunk:
                        eof[name] = True
                        selector.unregister(key.fileobj)
                        continue
                    buffers[name].extend(chunk)
                    if len(buffers[name]) > cap:
                        status = "transport-error"
                        break
                if status != "completed":
                    break

            if status != "completed":
                self._kill(process)
            try:
                returncode = process.wait(timeout=1)
            except (subprocess.TimeoutExpired, OSError):
                self._kill(process)
                returncode = None
                status = "transport-error" if status == "completed" else status
            if status == "completed" and not all(eof.values()):
                status = "transport-error"
                returncode = None
            return _BoundedProcessResult(
                stdout=bytes(buffers["stdout"]) if status != "transport-error" else b"",
                stderr=bytes(buffers["stderr"]) if status != "transport-error" else b"",
                binary_result=bytes(buffers["binary"]) if status == "completed" else b"",
                returncode=returncode,
                eof_stdout=eof["stdout"],
                eof_stderr=eof["stderr"],
                eof_binary_result=eof["binary"],
                completion_status=status,
            )
        except OSError:
            if process is not None:
                self._kill(process)
                try:
                    process.wait(timeout=1)
                except Exception:
                    pass
            return _BoundedProcessResult(
                stdout=b"",
                stderr=b"",
                binary_result=b"",
                returncode=None,
                eof_stdout=False,
                eof_stderr=False,
                eof_binary_result=False,
                completion_status="transport-error",
            )
        finally:
            if result_read >= 0:
                try:
                    os.close(result_read)
                except OSError:
                    pass
            if result_write >= 0:
                try:
                    os.close(result_write)
                except OSError:
                    pass
            if sealed is not None:
                sealed.close()

    def invoke_text(
        self, snapshot: ExecutionSnapshot, invocation: _Invocation
    ) -> _TextResult:
        completed = self._run_bounded(
            snapshot, invocation, binary_result_cap=None
        )
        return _TextResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            eof_stdout=completed.eof_stdout,
            eof_stderr=completed.eof_stderr,
            completion_status=completed.completion_status,
        )

    def invoke_fetch(
        self, snapshot: ExecutionSnapshot, invocation: _Invocation
    ) -> _FetchResult:
        completed = self._run_bounded(
            snapshot, invocation, binary_result_cap=134_218_240
        )
        if (
            completed.completion_status == "completed"
            and completed.returncode == 44
            and completed.stdout == b""
            and completed.stderr == b"artifact-not-found\n"
            and completed.binary_result == b""
            and completed.eof_binary_result
        ):
            return _FetchResult(status="missing")
        if (
            completed.completion_status != "completed"
            or completed.returncode != 0
            or completed.stdout
            or completed.stderr
            or not completed.eof_stdout
            or not completed.eof_stderr
            or not completed.eof_binary_result
        ):
            return _FetchResult(status="transport-error")
        match = _FETCH_HEADER.match(completed.binary_result)
        if match is None:
            return _FetchResult(status="unstable")
        identity_raw, size_raw, digest_raw = match.groups()
        content = completed.binary_result[match.end() :]
        try:
            identity = identity_raw.decode("ascii")
            size = int(size_raw.decode("ascii"))
            digest = digest_raw.decode("ascii")
        except (UnicodeDecodeError, ValueError):
            return _FetchResult(status="unstable")
        return _FetchResult(
            status="found",
            content=content,
            before_identity=identity,
            after_identity=identity,
            before_size=size,
            after_size=size,
            before_sha256=digest,
            after_sha256=digest,
        )


def _operation(name: str) -> _Operation:
    try:
        return _OPERATIONS[name]
    except KeyError as exc:
        raise TransportBoundaryError("operation is not in the frozen table") from exc


__all__ = [
    "_FIXED_ENV",
    "_FetchResult",
    "_Invocation",
    "_OPERATION_TABLE_BYTES",
    "_OPERATION_TABLE_SHA256",
    "_RTWinDriver",
    "_SubprocessRTWinDriver",
    "_TextResult",
    "_is_fetch_result_closed",
    "_is_text_result_closed",
    "_operation",
]
