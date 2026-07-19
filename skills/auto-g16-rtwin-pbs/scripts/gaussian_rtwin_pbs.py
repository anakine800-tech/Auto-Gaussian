#!/usr/bin/env python3
"""Safely operate Gaussian jobs through RTwin on the configured PBS server."""

from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gaussian_log import analyze_log_file, analyze_log_text, analyze_workflow_log_file
import execution_batch
import protocol_selection
import resource_efficiency
from runtime_config import setting


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAC_SSH_CONFIG = Path(
    setting(
        "AUTO_G16_RTWIN_SSH_CONFIG",
        "rtwin_ssh_config",
        os.environ.get(
            "GAUSSIAN_RTWIN_SSH_CONFIG",
            str(REPOSITORY_ROOT / "config" / "ssh_config"),
        ),
    )
)
DEFAULT_RTWIN_ALIAS = "rtwin"
DEFAULT_WINDOWS_ROOT = setting(
    "AUTO_G16_WINDOWS_PROJECT_ROOT", "windows_project_root", r"C:\GaussianProjects"
)
DEFAULT_WINDOWS_SERVER_CONFIG = setting(
    "AUTO_G16_WINDOWS_SERVER_CONFIG",
    "windows_server_config",
    r".ssh\gaussian_server_config",
)
DEFAULT_SERVER_ALIAS = "gaussian-server"
DEFAULT_REMOTE_ROOT = "/home/user100/SDL"
MAX_CORES = 44
MAX_MEMORY_BYTES = 120 * 1024**3
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
JOB_ID_RE = re.compile(r"^[0-9]+(?:\.[A-Za-z0-9_.-]+)?$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
INPUT_REVIEW_SCHEMA = "gaussian-input-draft-review/2"
INPUT_APPROVAL_SCHEMA = "gaussian-input-approval-receipt/1"
OPEN_SHELL_INPUT_APPROVAL_SCHEMA = "gaussian-input-approval-receipt/2"
OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA = "gaussian-input-approval-receipt/3"
LIVE_APPROVAL_V1_SCHEMA = "auto-g16-live-submission-approval/1"
LIVE_APPROVAL_V2_SCHEMA = "auto-g16-live-submission-approval/2"
LIVE_APPROVAL_V3_SCHEMA = "auto-g16-live-submission-approval/3"
OPEN_SHELL_LIVE_APPROVAL_SCHEMA = "auto-g16-live-submission-approval/4"
OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA = "auto-g16-live-submission-approval/5"
LIVE_APPROVAL_V6_SCHEMA = "auto-g16-live-submission-approval/6"
OPEN_SHELL_LIVE_APPROVAL_V7_SCHEMA = "auto-g16-live-submission-approval/7"
OPEN_SHELL_FAMILY_LIVE_APPROVAL_V8_SCHEMA = "auto-g16-live-submission-approval/8"
LIVE_APPROVAL_V9_SCHEMA = "auto-g16-live-submission-approval/9"
OPEN_SHELL_LIVE_APPROVAL_V10_SCHEMA = "auto-g16-live-submission-approval/10"
OPEN_SHELL_FAMILY_LIVE_APPROVAL_V11_SCHEMA = "auto-g16-live-submission-approval/11"
CANCELLATION_APPROVAL_SCHEMA = "auto-g16-exact-cancellation-approval/1"
INPUT_APPROVAL_WORK_KINDS = {"ordinary", "minimum", "ts_pilot", "formal_ts"}
SPECIALIST_INPUT_WORK_KINDS = {"ts_scan", "irc_forward", "irc_reverse", "endpoint_reopt"}
ALL_WORK_KINDS = INPUT_APPROVAL_WORK_KINDS | SPECIALIST_INPUT_WORK_KINDS
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60
STREAM_COPY_CHUNK_SIZE = 1024 * 1024
MAX_IN_MEMORY_READ_BYTES = 16 * 1024 * 1024
TRANSFER_RATE_FLOOR_BYTES_PER_SECOND = 1024 * 1024
TRANSFER_FIXED_OVERHEAD_SECONDS = 30
MIN_TRANSFER_TIMEOUT_SECONDS = 60
MAX_TRANSFER_TIMEOUT_SECONDS = 3600
MAX_READ_ONLY_RETRIES = 2
MAX_REMOTE_CLOCK_SKEW_SECONDS = 5
MIN_INTERRUPTION_STABLE_SECONDS = 60
WATCH_HEARTBEAT_SECONDS = 3600
WATCH_MAX_POLL_SECONDS = 300
WATCH_JITTER_FRACTION = 0.10


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def decode(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp936", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def run(
    command: list[str], *, input_bytes: bytes | None = None, check: bool = True,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run one local/SSH/scp command with a mandatory finite timeout and no retry."""

    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        fail("command timeout must be a positive integer")
    try:
        result = subprocess.run(
            command, input=input_bytes, capture_output=True, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(
            command, 124, exc.stdout or b"", (exc.stderr or b"") + b"\nAUTO_G16_COMMAND_TIMEOUT"
        )
    stdout = decode(result.stdout)
    stderr = decode(result.stderr)
    result.stdout = stdout  # type: ignore[assignment]
    result.stderr = stderr  # type: ignore[assignment]
    if check and result.returncode:
        detail = (stderr or stdout).strip()
        fail(f"command failed ({result.returncode}): {detail}")
    return result


def transfer_timeout_seconds(total_bytes: int) -> int:
    """Return one finite transfer budget from an exact known byte count."""
    if not isinstance(total_bytes, int) or isinstance(total_bytes, bool) or total_bytes < 0:
        fail("transfer timeout requires an exact non-negative byte count")
    calculated = TRANSFER_FIXED_OVERHEAD_SECONDS + math.ceil(
        total_bytes / TRANSFER_RATE_FLOOR_BYTES_PER_SECOND
    )
    return max(MIN_TRANSFER_TIMEOUT_SECONDS, min(MAX_TRANSFER_TIMEOUT_SECONDS, calculated))


class _ReadOnlyCapability:
    __slots__ = ("kind", "command", "input_sha256")

    def __init__(self, kind: str, command: list[str], input_bytes: bytes | None):
        self.kind = kind
        self.command = tuple(command)
        self.input_sha256 = hashlib.sha256(input_bytes or b"").hexdigest()


COMPLETE_USER_QSTAT_SCRIPT = b'''set -u
owner=$(id -un) || exit 91
printf 'AUTO_G16_OWNER\t%s\n' "$owner"
qstat -f -u "$owner"
'''


def _exact_read_only_capability(kind: str, command: list[str], input_bytes: bytes | None) -> _ReadOnlyCapability:
    if kind not in {"single_job_inspection", "complete_user_qstat"}:
        raise ValueError("unknown read-only capability")
    if (
        len(command) != 10 or command[0] != "ssh" or command[1] != "-F"
        or command[4] != "ssh" or command[5] != "-F"
        or command[8:] != ["bash", "-s"] or input_bytes is None
        or any(not isinstance(command[index], str) or not command[index] for index in (2, 3, 6, 7))
        or any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", command[index]) is None for index in (3, 7))
    ):
        raise ValueError("read-only capability requires the exact internal snapshot builder")
    if kind == "complete_user_qstat" and input_bytes != COMPLETE_USER_QSTAT_SCRIPT:
        raise ValueError("complete-user capability accepts only the fixed qstat builder")
    if kind == "single_job_inspection":
        text = decode(input_bytes)
        job_match = re.search(r"qstat_out=\$\(qstat -f '([^']+)'", text)
        log_match = re.search(r"if \[ -f '(/home/user100/SDL/([^/]+)/([^/]+)\.log)' \]", text)
        if not job_match or not log_match:
            raise ValueError("inspection capability cannot recover exact builder scope")
        project, input_stem = log_match.group(2), log_match.group(3)
        if input_bytes != server_job_snapshot_script(project, input_stem, job_match.group(1)).encode("utf-8"):
            raise ValueError("inspection capability accepts only the exact generated snapshot script")
    return _ReadOnlyCapability(kind, command, input_bytes)


def run_read_only(
    command: list[str], *, input_bytes: bytes | None = None,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    retries: int = MAX_READ_ONLY_RETRIES,
    capability: _ReadOnlyCapability | None = None,
) -> subprocess.CompletedProcess:
    """Retry only commands whose complete command/script is provably read-only."""

    if (
        not isinstance(capability, _ReadOnlyCapability)
        or capability.kind not in {"single_job_inspection", "complete_user_qstat"}
        or capability.command != tuple(command)
        or capability.input_sha256 != hashlib.sha256(input_bytes or b"").hexdigest()
    ):
        raise ValueError("automatic retry requires an exact private read-only snapshot capability")
    if not isinstance(retries, int) or not 0 <= retries <= MAX_READ_ONLY_RETRIES:
        raise ValueError("read-only retries exceed the finite package-4 limit")
    result: subprocess.CompletedProcess | None = None
    for attempt in range(retries + 1):
        result = run(
            command, input_bytes=input_bytes, check=False, timeout_seconds=timeout_seconds
        )
        if result.returncode not in {124, 255}:
            return result
        if attempt < retries:
            time.sleep(0.05 * (2 ** attempt))
    assert result is not None
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_stable_bytes(path: Path, label: str) -> tuple[Path, bytes, str]:
    """Read one regular non-symlink file from one descriptor and bind its bytes."""

    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable: {exc}") from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise ValueError(f"cannot open {label} without following a symlink: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if before.st_size > MAX_IN_MEMORY_READ_BYTES:
            raise ValueError(f"{label} exceeds the bounded in-memory read limit; use streaming copy/hash")
        data = bytearray()
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, STREAM_COPY_CHUNK_SIZE)
            if not chunk:
                break
            data.extend(chunk); digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(f"{label} changed while it was being read")
    if len(data) != before.st_size:
        raise ValueError(f"{label} size changed while it was being read")
    return resolved, bytes(data), digest.hexdigest()


def stable_file_metadata(path: Path, label: str) -> tuple[Path, str, int]:
    """Hash a descriptor-bound regular file without retaining its bytes."""
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = expanded.resolve(strict=True)
    descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} must be a regular file")
        digest = hashlib.sha256(); size = 0
        while True:
            chunk = os.read(descriptor, STREAM_COPY_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk); size += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _descriptor_identity(before) != _descriptor_identity(after) or _nofollow_path_identity(resolved, label) != _descriptor_identity(before) or size != before.st_size:
        raise ValueError(f"{label} changed while it was hashed")
    return resolved, digest.hexdigest(), size


def _descriptor_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _nofollow_path_identity(path: Path, label: str) -> tuple[int, int, int, int]:
    try:
        value = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"{label} path identity is unavailable: {exc}") from exc
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"{label} must remain a regular non-symlink file")
    return _descriptor_identity(value)


def atomic_stable_file_copy(
    source: Path, destination: Path, label: str, *, expected: dict[str, Any] | None = None,
    mode: int = 0o400,
) -> dict[str, Any]:
    """Descriptor-bound chunked copy with private no-clobber publication."""
    expanded = source.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = expanded.resolve(strict=True)
    source_fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    temporary = destination.with_name(f".{destination.name}.copy-{os.getpid()}-{time.time_ns()}.tmp")
    destination_fd = -1
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or _nofollow_path_identity(resolved, label) != _descriptor_identity(before):
            raise ValueError(f"{label} descriptor/path identity differs")
        destination_fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode
        )
        os.fchmod(destination_fd, mode)
        digest = hashlib.sha256(); size = 0
        while True:
            chunk = os.read(source_fd, STREAM_COPY_CHUNK_SIZE)
            if not chunk: break
            digest.update(chunk); size += len(chunk)
            offset = 0
            while offset < len(chunk):
                written = os.write(destination_fd, chunk[offset:])
                if written <= 0: raise OSError("zero-byte stable copy write")
                offset += written
        os.fsync(destination_fd)
        after = os.fstat(source_fd)
        identity = _descriptor_identity(before)
        if identity != _descriptor_identity(after) or _nofollow_path_identity(resolved, label) != identity or size != before.st_size:
            raise ValueError(f"{label} changed while it was copied")
        observed = {"sha256": digest.hexdigest(), "size": size}
        if expected is not None and observed != {"sha256": expected.get("sha256"), "size": expected.get("size")}:
            raise ValueError(f"{label} changed after manifest validation")
        os.close(destination_fd); destination_fd = -1
        copied = os.stat(temporary, follow_symlinks=False)
        if not stat.S_ISREG(copied.st_mode) or copied.st_size != size or sha256(temporary) != observed["sha256"]:
            raise ValueError(f"{label} private copy failed pre-publication verification")
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise ValueError(f"{label} destination already exists") from exc
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
        if _nofollow_path_identity(destination, f"published {label}")[2] != size or sha256(destination) != observed["sha256"]:
            raise ValueError(f"published {label} failed verification")
        return {**observed, "source": resolved}
    finally:
        os.close(source_fd)
        if destination_fd >= 0: os.close(destination_fd)
        with contextlib.suppress(FileNotFoundError): temporary.unlink()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"refusing to replace symlink state file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextlib.contextmanager
def locked_state(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    if path.is_symlink() or lock_path.is_symlink():
        raise ValueError("job state and lock paths must not be symlinks")
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def publish_new_json(
    path: Path,
    value: dict[str, Any],
    validator: Any | None = None,
) -> None:
    """Atomically publish immutable JSON without any overwrite window."""

    expanded = path.expanduser()
    if expanded.name in {"", ".", ".."}:
        raise ValueError("immutable artifact output must name a file")
    path = expanded.parent.resolve() / expanded.name
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if validator is not None:
            validator(temporary)
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise ValueError(f"refusing to overwrite immutable artifact: {path}") from None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def capture_submission_snapshot(source: Path, local_dir: Path) -> tuple[Path, str]:
    """Capture one unique, durable source snapshot before any approval replay."""

    resolved, data, digest = read_stable_bytes(source, "Gaussian submission source")
    if resolved.suffix.lower() not in {".gjf", ".com"}:
        raise ValueError("Gaussian submission source must end in .gjf or .com")
    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = Path(tempfile.mkdtemp(prefix=".submit-snapshot-", dir=local_dir))
    snapshot = snapshot_dir / resolved.name
    descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        raise
    directory_fd = os.open(snapshot_dir, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    _, captured, captured_digest = read_stable_bytes(snapshot, "Gaussian submission snapshot")
    if captured != data or captured_digest != digest:
        raise ValueError("Gaussian submission snapshot differs from the captured source bytes")
    # A checkpoint-derived input is not self-contained. Freeze its exact companion
    # manifest and reviewed %oldchk beside the input before replaying any approval.
    companion_sources: list[Path] = []
    manifest_source = resolved.with_suffix(".json")
    if manifest_source.is_file() or manifest_source.is_symlink():
        companion_sources.append(manifest_source)
    oldchk_match = re.search(r"(?im)^\s*%oldchk\s*=\s*([^\r\n]+)\s*$", decode(data))
    if oldchk_match:
        oldchk_name = oldchk_match.group(1).strip()
        if Path(oldchk_name).name != oldchk_name or "/" in oldchk_name or "\\" in oldchk_name:
            raise ValueError("%oldchk must be a local basename inside the snapshot")
        companion_sources.append(resolved.parent / oldchk_name)
    for companion_source in companion_sources:
        companion_snapshot = snapshot_dir / companion_source.name
        atomic_stable_file_copy(
            companion_source, companion_snapshot, f"submission companion {companion_source.name}", mode=0o400
        )
    return snapshot, digest


def verify_staged_submission(
    local_dir: Path,
    job: dict[str, Any],
    expected_report: dict[str, Any],
    input_approval: dict[str, Any],
    files: list[Path],
) -> dict[str, str]:
    """Recheck staged facts and file hashes immediately before any live action."""

    staged_input = local_dir / str(job["input"])
    before_path, _, before_digest = read_stable_bytes(staged_input, "staged Gaussian input")
    staged_report = parse_gaussian(before_path)
    _, _, after_digest = read_stable_bytes(staged_input, "staged Gaussian input")
    if before_digest != after_digest:
        fail("staged Gaussian input changed during final pre-network verification")
    if (
        _input_approval_facts(staged_report) != _input_approval_facts(expected_report)
        or job.get("input_sha256") != before_digest
        or (
            input_approval.get("status") == "validated_exact_input_approval"
            and input_approval.get("input_sha256") != before_digest
        )
    ):
        fail("staged Gaussian input no longer matches the exact input and live approval chain")
    expected: dict[str, str] = {}
    for path in files:
        _, digest, _ = stable_file_metadata(path, f"staged upload file {path.name}")
        expected[path.name] = digest
    return expected


def assert_file_bindings_unchanged(files: list[Path], expected: dict[str, str]) -> None:
    for path in files:
        _, digest, _ = stable_file_metadata(path, f"staged upload file {path.name}")
        if digest != expected.get(path.name):
            fail(f"staged upload file changed before transfer: {path.name}")


def validate_project(project: str) -> str:
    if not PROJECT_RE.fullmatch(project):
        fail("project must be 1-15 characters: letters, digits, '_' or '-', starting alphanumeric")
    return project


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        fail("invalid PBS job id")
    return job_id


def remote_project_dir(project: str) -> str:
    """Return the only permitted server-side project directory."""

    validate_project(project)
    return f"{DEFAULT_REMOTE_ROOT}/{project}"


def validate_transfer_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        fail(
            "server-bound filenames must contain only letters, digits, '_', '-', or '.', "
            "and must start alphanumeric"
        )
    return name


def checked_local_path(path: Path, label: str) -> Path:
    """Return an absolute path only when every existing component is non-symlink."""

    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    absolute = Path(os.path.abspath(str(expanded)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            fail(f"cannot inspect {label} path component {current}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"{label} must not contain a symlink: {current}")
    return absolute


def command_detail(result: subprocess.CompletedProcess) -> str | None:
    """Return one bounded diagnostic without turning an error into evidence."""

    detail = " ".join(str(result.stderr or result.stdout).strip().split())
    return detail[:500] if detail else None


def is_unknown_job_id(result: subprocess.CompletedProcess) -> bool:
    """Recognize only PBS' explicit statement that one exact record is absent."""

    text = f"{result.stdout}\n{result.stderr}"
    return bool(re.search(r"\bunknown\s+job(?:\s+identifier|\s+id)?\b", text, re.I))


def classify_qstat_evidence(result: subprocess.CompletedProcess) -> dict[str, Any]:
    """Classify qstat as present/absent/unknown; command errors stay unknown."""

    text = str(result.stdout or result.stderr)
    if result.returncode == 0:
        qstate_match = re.search(r"(?m)^\s*job_state\s*=\s*(\S+)", text)
        job_name_match = re.search(r"(?m)^\s*Job_Name\s*=\s*(\S+)", text)
        session_match = re.search(r"(?m)^\s*session_id\s*=\s*(\d+)", text)
        if qstate_match and job_name_match:
            return {
                "status": "present",
                "record_present": True,
                "pbs_state": qstate_match.group(1),
                "job_name": job_name_match.group(1),
                "session_id": session_match.group(1) if session_match else None,
                "returncode": result.returncode,
                "error": None,
            }
        return {
            "status": "unknown",
            "record_present": None,
            "pbs_state": None,
            "job_name": None,
            "session_id": None,
            "returncode": result.returncode,
            "error": "qstat succeeded but its exact job record could not be parsed",
        }
    if result.returncode != 255 and is_unknown_job_id(result):
        return {
            "status": "absent",
            "record_present": False,
            "pbs_state": None,
            "job_name": None,
            "session_id": None,
            "returncode": result.returncode,
            "error": None,
        }
    return {
        "status": "unknown",
        "record_present": None,
        "pbs_state": None,
        "job_name": None,
        "session_id": None,
        "returncode": result.returncode,
        "error": command_detail(result) or "qstat failed without an explicit Unknown Job Id response",
    }


def classify_process_evidence(result: subprocess.CompletedProcess) -> dict[str, Any]:
    """Classify an exact PBS session process observation without guessing."""

    output = str(result.stdout).strip()
    if result.returncode == 0:
        present = bool(output)
        return {
            "status": "present" if present else "absent",
            "process_alive": present,
            "returncode": result.returncode,
            "error": None,
        }
    if result.returncode == 1 and not output and not str(result.stderr).strip():
        return {
            "status": "absent",
            "process_alive": False,
            "returncode": result.returncode,
            "error": None,
        }
    return {
        "status": "unknown",
        "process_alive": None,
        "returncode": result.returncode,
        "error": command_detail(result) or "ps failed, so session-process presence is unknown",
    }


def classify_qdel_outcome(result: subprocess.CompletedProcess) -> dict[str, Any]:
    """Classify the one allowed qdel without treating transport failure as success."""

    if result.returncode == 0:
        return {"status": "success", "returncode": 0, "error": None}
    if result.returncode != 255 and is_unknown_job_id(result):
        return {
            "status": "unknown_job_id",
            "returncode": result.returncode,
            "error": None,
        }
    return {
        "status": "failed",
        "returncode": result.returncode,
        "error": command_detail(result) or "qdel failed without an explicit Unknown Job Id response",
    }


def classify_qsub_outcome(result: subprocess.CompletedProcess) -> dict[str, Any]:
    combined = f"{result.stdout}\n{result.stderr}"
    job_ids = sorted(set(re.findall(
        r"(?m)^([0-9]+(?:\.[A-Za-z0-9_.-]+)?)\s*$", combined
    )))
    if result.returncode == 0 and len(job_ids) == 1:
        return {"classification": "submitted_unique", "job_id": job_ids[0], "output": combined.strip()}
    return {
        "classification": "submission_uncertain",
        "job_id": None,
        "candidate_job_ids": job_ids,
        "output": combined.strip(),
    }


def remote_empty_directory_guard(project: str) -> str:
    """Atomically claim a never-before-existing project directory."""

    remote_dir = remote_project_dir(project)
    return f"""set -euo pipefail
root='{DEFAULT_REMOTE_ROOT}'
jobdir='{remote_dir}'
root_real=$(realpath -e -- "$root")
if [ "$root_real" != "$root" ]; then
  echo 'REFUSING_OUTSIDE_SDL: allowed root is missing, moved, or a symlink' >&2
  exit 40
fi
if [ -e "$jobdir" ]; then
  echo 'REFUSING_OVERWRITE: server project directory already exists, even if empty' >&2
  exit 43
fi
mkdir -- "$jobdir"
job_real=$(realpath -e -- "$jobdir")
case "$job_real" in
  "$root"/*) ;;
  *) echo 'REFUSING_OUTSIDE_SDL: claimed project resolves outside allowed root' >&2; exit 42 ;;
esac
"""


def remote_existing_directory_guard(project: str) -> str:
    """Validate an existing project directory without changing server data."""

    remote_dir = remote_project_dir(project)
    return f"""set -euo pipefail
root='{DEFAULT_REMOTE_ROOT}'
jobdir='{remote_dir}'
root_real=$(realpath -e -- "$root")
if [ "$root_real" != "$root" ] || [ -L "$jobdir" ] || [ ! -d "$jobdir" ]; then
  echo 'REFUSING_OUTSIDE_SDL: invalid project directory' >&2
  exit 44
fi
job_real=$(realpath -e -- "$jobdir")
case "$job_real" in
  "$root"/*) ;;
  *) echo 'REFUSING_OUTSIDE_SDL: project resolves outside allowed root' >&2; exit 45 ;;
esac
"""


def parse_memory(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?B)\s*", value, re.I)
    if not match:
        fail(f"unsupported %mem value: {value!r}")
    number = float(match.group(1))
    power = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}[match.group(2).upper()]
    return int(number * 1024**power)


def normalize_route(route: str) -> str:
    lowered = " ".join(route.lower().split())
    lowered = re.sub(r"\s*=\s*", "=", lowered)
    lowered = re.sub(r"\s*,\s*", ",", lowered)
    lowered = re.sub(r"\(\s*", "(", lowered)
    return re.sub(r"\s*\)", ")", lowered)


def route_top_level_tokens(route: str) -> list[str]:
    """Return route tokens split only at top-level whitespace.

    Gaussian option values are not route keywords.  In particular, the
    ``opt`` in ``Stable=Opt`` must not be counted as a second top-level Opt.
    """
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    for character in normalize_route(route):
        if character.isspace() and depth == 0:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(character)
        if character == "(":
            depth += 1
        elif character == ")" and depth > 0:
            depth -= 1
    if current:
        tokens.append("".join(current))
    return tokens


def route_has_keyword(route: str, keyword: str) -> bool:
    pattern = re.compile(rf"^{re.escape(keyword.lower())}(?=$|[=(])")
    return any(pattern.match(token) is not None for token in route_top_level_tokens(route))


def route_keyword_count(route: str, keyword: str) -> int:
    pattern = re.compile(rf"^{re.escape(keyword.lower())}(?=$|[=(])")
    return sum(pattern.match(token) is not None for token in route_top_level_tokens(route))


def route_option_values(route: str, keyword: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(rf"^{re.escape(keyword.lower())}(?:=([^\s]+)|\(([^)]*)\))$")
    for token in route_top_level_tokens(route):
        match = pattern.fullmatch(token)
        if match is None:
            continue
        values = (match.group(1) or match.group(2) or "").strip("()")
        result.extend(value for value in values.split(",") if value)
    return result


def route_has_option(route: str, keyword: str, option: str) -> bool:
    return option.lower() in route_option_values(route, keyword)


OPTIMIZATION_KEYWORDS = ("opt", "fopt", "popt")


def optimization_option_values(route: str) -> list[str]:
    return [value for keyword in OPTIMIZATION_KEYWORDS for value in route_option_values(route, keyword)]


def route_has_optimization_keyword(route: str) -> bool:
    return any(route_has_keyword(route, keyword) for keyword in OPTIMIZATION_KEYWORDS)


def route_optimization_keyword_count(route: str) -> int:
    return sum(route_keyword_count(route, keyword) for keyword in OPTIMIZATION_KEYWORDS)


def route_has_frequency(route: str) -> bool:
    return route_has_keyword(route, "freq") or route_has_keyword(route, "frequency")


def route_has_ts_optimization(route: str) -> bool:
    for value in optimization_option_values(route):
        if value in {"ts", "qst2", "qst3"}:
            return True
        saddle = re.fullmatch(r"saddle=([0-9]+)", value)
        if saddle is not None and int(saddle.group(1)) >= 1:
            return True
    return False


def route_has_specialist_optimization(route: str) -> bool:
    """Optimization families that need a dedicated owner, not TS maturity."""
    return (
        any(value in {"conical", "avoided"} for value in optimization_option_values(route))
        or route_has_gic_optimization(route)
    )


def route_has_gic_optimization(route: str) -> bool:
    gic_values = {"gic", "addgic", "readallgic"}
    return bool(
        set(optimization_option_values(route)) & gic_values
        or set(route_option_values(route, "geom")) & gic_values
    )


def route_has_scan(route: str) -> bool:
    return (
        route_has_keyword(route, "modredundant")
        or any(value in {"scan", "modredundant", "addredundant"} for value in optimization_option_values(route))
    )


def route_has_relaxed_scan_context(route: str) -> bool:
    values = set(optimization_option_values(route))
    return route_has_keyword(route, "modredundant") or bool(
        values & {"modredundant", "addredundant"}
    )


def route_has_specialist_path(route: str) -> bool:
    return route_has_keyword(route, "ircmax") or (
        route_has_keyword(route, "scan")
        and "scan" not in optimization_option_values(route)
    )


def classify_protected_work(route: str) -> str | None:
    if route_has_keyword(route, "irc"):
        return "irc"
    if route_has_scan(route):
        return "ts_scan"
    if route_has_specialist_path(route):
        return "specialist_path"
    if route_has_specialist_optimization(route):
        return "specialist_opt"
    if route_has_ts_optimization(route):
        return "ts"
    return None


def classify_protected_input(report: dict[str, Any]) -> str | None:
    if report.get("has_relaxed_scan_directive") is True:
        return "ts_scan"
    return classify_protected_work(str(report.get("route", "")))


def route_is_ts(route: str) -> bool:
    return classify_protected_work(route) == "ts"


def _resource_tier(mem: str, nproc: int) -> str:
    tiers = {"simple": ("12GB", 8), "general": ("50GB", 22), "complex": ("120GB", 44)}
    for name, (expected_mem, expected_nproc) in tiers.items():
        if parse_memory(mem) == parse_memory(expected_mem) and nproc == expected_nproc:
            return name
    return "custom"


MATURITY_GATE_V1_SCHEMA = "gaussian-scientific-maturity-gate/1"
MATURITY_GATE_V2_SCHEMA = "gaussian-scientific-maturity-gate/2"
MATURITY_ACTION_V1_SCHEMA = "gaussian-scientific-maturity-action-check/1"
MATURITY_ACTION_V2_SCHEMA = "gaussian-scientific-maturity-action/2"


def _load_scientific_maturity(version: int = 1) -> Any:
    skills_root = Path(__file__).resolve().parents[2]
    filename = "scientific_maturity.py" if version == 1 else "scientific_maturity_v2.py"
    path = skills_root / "auto-g16-reaction-workflow" / "scripts" / filename
    if not path.is_file():
        fail("scientific-maturity owner validator is unavailable")
    spec = importlib.util.spec_from_file_location(f"auto_g16_pbs_scientific_maturity_v{version}", path)
    if spec is None or spec.loader is None:
        fail("scientific-maturity owner validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_open_shell_minimum_owner() -> Any:
    path = Path(__file__).resolve().parents[2] / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_minimum.py"
    if not path.is_file():
        raise ValueError("main-group open-shell minimum owner validator is unavailable")
    spec = importlib.util.spec_from_file_location("auto_g16_pbs_open_shell_minimum", path)
    if spec is None or spec.loader is None:
        raise ValueError("main-group open-shell minimum owner validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_open_shell_minimum_family_owner() -> Any:
    path = Path(__file__).resolve().parents[2] / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_minimum_family.py"
    if not path.is_file():
        raise ValueError("main-group open-shell minimum family owner validator is unavailable")
    spec = importlib.util.spec_from_file_location("auto_g16_pbs_open_shell_minimum_family", path)
    if spec is None or spec.loader is None:
        raise ValueError("main-group open-shell minimum family owner validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _maturity_owner_for_gate(path: Path) -> tuple[str, Any, Path]:
    """Select the owner and freeze the identity read for schema dispatch."""
    expanded = path.expanduser()
    if expanded.is_symlink():
        fail("scientific-maturity gate must not be a symlink")
    try:
        resolved, document, _, _ = load_strict_json_with_hash(expanded, "scientific-maturity gate")
    except ValueError as exc:
        fail(f"cannot read scientific-maturity gate: {exc}")
    schema = document.get("schema")
    owners = {
        MATURITY_GATE_V1_SCHEMA: lambda: _load_scientific_maturity(1),
        MATURITY_GATE_V2_SCHEMA: lambda: _load_scientific_maturity(2),
    }
    if schema not in owners:
        fail(f"unsupported scientific-maturity gate schema: {schema!r}")
    return schema, owners[schema](), resolved


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def _parse_strict_json_bytes(data: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"could not read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return value


def load_strict_json_with_hash(path: Path, label: str = "JSON artifact") -> tuple[Path, dict[str, Any], str, int]:
    resolved, data, digest = read_stable_bytes(path, label)
    return resolved, _parse_strict_json_bytes(data, resolved), digest, len(data)


def load_strict_json(path: Path) -> dict[str, Any]:
    return load_strict_json_with_hash(path)[1]


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def contract_payload_sha256(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _exact_fields(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        actual = set(value) if isinstance(value, dict) else set()
        raise ValueError(
            f"{label} fields differ: missing={sorted(fields - actual)}, unknown={sorted(actual - fields)}"
        )
    return value


def _input_approval_facts(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_sha256": report["input_sha256"],
        "route": report["route"],
        "mem": report["mem"],
        "nprocshared": report["nprocshared"],
        "charge": report["charge"],
        "multiplicity": report["multiplicity"],
        "atom_count": report["atom_count"],
        "elements": report["elements"],
    }


def input_approval_compatibility(report: dict[str, Any], work_kind: str | None) -> dict[str, Any]:
    """Classify only the input families fully represented by generic receipt /1."""

    if work_kind is None:
        return {
            "status": "missing_work_kind",
            "required": "an explicit --work-kind bound by input and live approvals",
        }
    if work_kind in SPECIALIST_INPUT_WORK_KINDS:
        return {
            "status": "blocked_missing_specialist_input_approval",
            "work_kind": work_kind,
            "reason": "this work kind requires its specialist owner manifest and exact raw-syntax/checkpoint review",
        }
    if work_kind not in INPUT_APPROVAL_WORK_KINDS:
        return {"status": "unsupported_work_kind", "work_kind": work_kind}
    if work_kind == "ordinary" and isinstance(report.get("multiplicity"), int) and report["multiplicity"] > 1:
        return {
            "status": "blocked_unsupported_open_shell_ordinary",
            "work_kind": work_kind,
            "required_owner": "unavailable_specialist_open_shell_ordinary_owner",
            "required_schema": None,
            "reason": "generic input receipt /1 and live approval /9 are singlet-only for ordinary jobs",
        }

    route = str(report.get("route", ""))
    route_tokens = set(normalize_route(route).split())
    if (
        work_kind == "minimum"
        and report.get("multiplicity") in {2, 3}
        and route_has_optimization_keyword(route)
        and route_has_frequency(route)
        and route_has_keyword(route, "stable")
        and any(token == "stable=opt" or token == "stable=(opt)" for token in route_tokens)
        and any(token == "opt=tight" or token == "opt=(tight)" for token in route_tokens)
    ):
        return {
            "status": "blocked_combined_open_shell_minimum_stability_parse_risk",
            "work_kind": work_kind,
            "required_schema": OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA,
            "failure_classification": "gaussian_link1_combined_opt_freq_stable_parse_failure",
            "reason": "Gaussian 16 A.03 must receive Opt/Freq and Stable=Opt as independently approved checkpoint-bound stages",
        }
    open_shell_family_stage = (
        work_kind == "minimum"
        and report.get("multiplicity") in {2, 3}
        and (
            (route_has_optimization_keyword(route) and route_has_frequency(route) and not route_has_keyword(route, "stable"))
            or (
                route_has_keyword(route, "stable")
                and route_has_option(route, "geom", "allcheck")
                and route_has_option(route, "guess", "read")
                and not route_has_optimization_keyword(route)
                and not route_has_frequency(route)
            )
        )
    )
    if open_shell_family_stage:
        return {
            "status": "blocked_missing_open_shell_family_stage_approval",
            "work_kind": work_kind,
            "required_schema": OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA,
            "reason": "this open-shell minimum stage requires exact two-stage family owner replay",
        }
    specialist_syntax = (
        report.get("link1_count", 0) != 0
        or report.get("route_section_count", 1) != 1
        or route_optimization_keyword_count(route) > 1
        or any(route_keyword_count(route, keyword) > 1 for keyword in ("geom", "guess"))
        or route_has_keyword(route, "fopt")
        or route_has_keyword(route, "popt")
        or any(value in {"qst2", "qst3"} for value in optimization_option_values(route))
        or route_has_keyword(route, "irc")
        or route_has_scan(route)
        or route_has_specialist_optimization(route)
        or route_has_specialist_path(route)
        or report.get("has_relaxed_scan_directive") is True
        or route_has_option(route, "geom", "allcheck")
        or route_has_option(route, "geom", "check")
        or route_has_option(route, "guess", "read")
        or report.get("geometry_source") != "explicit_cartesian"
        or report.get("oldcheckpoint") is not None
    )
    if specialist_syntax:
        return {
            "status": "blocked_missing_specialist_input_approval",
            "work_kind": work_kind,
            "reason": "generic /1 covers only one self-contained Cartesian structure and no checkpoint-derived syntax",
        }

    protected = classify_protected_input(report)
    if work_kind in {"ts_pilot", "formal_ts"}:
        if protected != "ts" or not route_has_frequency(route):
            return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    elif protected is not None:
        return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    if work_kind == "minimum" and not route_has_optimization_keyword(route):
        return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    if work_kind == "ordinary" and (route_has_optimization_keyword(route) or route_has_frequency(route)):
        return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    return {"status": "supported_generic_v1", "work_kind": work_kind}


def _validate_protocol_binding_shape(value: Any) -> dict[str, Any]:
    binding = _exact_fields(
        value,
        {
            "options_sha256", "options_payload_sha256", "selection_sha256",
            "selection_payload_sha256", "selected_option", "used_profile_ids", "used_tasks",
        },
        "input review protocol_binding",
    )
    for key in ("options_sha256", "options_payload_sha256", "selection_sha256", "selection_payload_sha256"):
        if not isinstance(binding[key], str) or SHA256_RE.fullmatch(binding[key]) is None:
            raise ValueError(f"input review protocol_binding.{key} is invalid")
    selected = _exact_fields(
        binding["selected_option"], {"tier", "option_id", "option_payload_sha256"},
        "input review selected_option",
    )
    if not all(isinstance(selected[key], str) and selected[key] for key in ("tier", "option_id")):
        raise ValueError("input review selected option identity is invalid")
    if not isinstance(selected["option_payload_sha256"], str) or SHA256_RE.fullmatch(selected["option_payload_sha256"]) is None:
        raise ValueError("input review selected option payload SHA-256 is invalid")
    profiles = binding["used_profile_ids"]
    if not isinstance(profiles, list) or not profiles or len(profiles) != len(set(profiles)) or not all(isinstance(item, str) and item for item in profiles):
        raise ValueError("input review used_profile_ids must be unique non-empty strings")
    tasks = binding["used_tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("input review used_tasks must be non-empty")
    for task in tasks:
        item = _exact_fields(task, {"task_index", "stage_type", "profile_id"}, "input review used task")
        if not isinstance(item["task_index"], int) or isinstance(item["task_index"], bool) or item["task_index"] < 0:
            raise ValueError("input review task_index is invalid")
        if not isinstance(item["stage_type"], str) or not item["stage_type"] or item["profile_id"] not in profiles:
            raise ValueError("input review used task is invalid")
    indices = [item["task_index"] for item in tasks]
    if len(indices) != len(set(indices)):
        raise ValueError("input review used task indices must be unique")
    return binding


def _validate_route_profile_mapping_shape(value: Any, approved_route: str) -> dict[str, Any]:
    mapping = _exact_fields(
        value, {"exact_route", "method", "basis", "solvent", "scf", "tasks", "explicit_confirmation"},
        "input review route_profile_mapping",
    )
    if mapping["exact_route"] != approved_route or mapping["explicit_confirmation"] is not True:
        raise ValueError("input review route/profile mapping is not explicitly bound to the exact route")
    route_lower = " ".join(approved_route.lower().split())
    for key in ("method", "basis", "solvent", "scf"):
        item = _exact_fields(
            mapping[key], {"route_value", "profile_id", "selected_value", "human_confirmed"},
            f"input review route mapping {key}",
        )
        if not isinstance(item["route_value"], str) or not item["route_value"].strip() or not isinstance(item["profile_id"], str) or not item["profile_id"]:
            raise ValueError(f"input review {key} route/profile value is missing")
        if item["human_confirmed"] is not True:
            raise ValueError(f"input review {key} mapping lacks human confirmation")
        route_value = item["route_value"].lower()
        if key in {"method", "basis"} and route_value not in route_lower:
            raise ValueError(f"input review {key} route value is absent from the exact route")
        if key == "solvent" and route_value == "none" and ("scrf" in route_lower or "solvent" in route_lower):
            raise ValueError("input review claims no solvent but the route contains solvation syntax")
        if key == "scf" and route_value == "default" and re.search(r"\bscf\b", route_lower):
            raise ValueError("input review claims default SCF but the route contains explicit SCF syntax")
    tasks = mapping["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("input review route task mappings are missing")
    for task in tasks:
        item = _exact_fields(
            task, {"task_index", "stage_type", "profile_id", "route_evidence", "human_confirmed"},
            "input review route task mapping",
        )
        evidence = item["route_evidence"]
        if item["human_confirmed"] is not True or not isinstance(evidence, list) or not evidence or len(evidence) != len(set(evidence)):
            raise ValueError("input review route task mapping is not explicitly confirmed")
        if not all(token in {"opt_ts", "minimum_opt", "frequency", "single_point"} for token in evidence):
            raise ValueError("input review task evidence must use deterministic route predicates")
    return mapping


def validate_input_review(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("input review must not be a symlink")
    path = expanded.resolve()
    review = load_strict_json(path)
    _exact_fields(
        review,
        {
            "schema", "review_id", "work_kind", "protocol_task_types", "protocol_binding",
            "route_profile_mapping", "protocol_family_completion", "approved_input", "decision", "calculation_ready",
            "no_submission_authorization", "payload_sha256",
        },
        "input-draft review /2",
    )
    if review["schema"] != INPUT_REVIEW_SCHEMA:
        raise ValueError(f"input review schema must be {INPUT_REVIEW_SCHEMA}")
    if review["work_kind"] not in INPUT_APPROVAL_WORK_KINDS:
        raise ValueError("input review work_kind is unsupported")
    if not isinstance(review["review_id"], str) or not review["review_id"].strip():
        raise ValueError("input review review_id is missing")
    task_types = review["protocol_task_types"]
    if not isinstance(task_types, list) or not task_types or not all(isinstance(item, str) and item.strip() for item in task_types):
        raise ValueError("input review protocol_task_types must be a non-empty string array")
    if len(task_types) != len(set(task_types)):
        raise ValueError("input review protocol_task_types contains duplicates")
    _validate_protocol_binding_shape(review["protocol_binding"])
    if review["protocol_family_completion"] is not False:
        raise ValueError("one input review must not claim whole protocol-family completion")
    facts = _exact_fields(
        review["approved_input"],
        {"input_sha256", "route", "mem", "nprocshared", "charge", "multiplicity", "atom_count", "elements"},
        "input review approved_input",
    )
    if not isinstance(facts["input_sha256"], str) or SHA256_RE.fullmatch(facts["input_sha256"]) is None:
        raise ValueError("input review SHA-256 is invalid")
    if not isinstance(facts["route"], str) or not facts["route"].startswith("#"):
        raise ValueError("input review route is invalid")
    if not isinstance(facts["mem"], str) or parse_memory(facts["mem"]) <= 0:
        raise ValueError("input review memory is invalid")
    for key in ("nprocshared", "multiplicity", "atom_count"):
        if not isinstance(facts[key], int) or isinstance(facts[key], bool) or facts[key] <= 0:
            raise ValueError(f"input review {key} is invalid")
    if not isinstance(facts["charge"], int) or isinstance(facts["charge"], bool):
        raise ValueError("input review charge is invalid")
    if not isinstance(facts["elements"], dict) or not facts["elements"]:
        raise ValueError("input review elements are missing")
    if sum(facts["elements"].values()) != facts["atom_count"]:
        raise ValueError("input review element counts differ from atom_count")
    _validate_route_profile_mapping_shape(review["route_profile_mapping"], facts["route"])
    decision = _exact_fields(
        review["decision"],
        {"status", "explicit_confirmation", "reviewer", "reviewed_at", "rationale"},
        "input review decision",
    )
    if decision["status"] != "accepted_exact_input" or decision["explicit_confirmation"] is not True:
        raise ValueError("input review is not explicitly accepted")
    for key in ("reviewer", "reviewed_at", "rationale"):
        if not isinstance(decision[key], str) or not decision[key].strip():
            raise ValueError(f"input review decision.{key} is missing")
    if review["calculation_ready"] is not False or review["no_submission_authorization"] is not True:
        raise ValueError("input review authority boundary changed")
    if review["payload_sha256"] != contract_payload_sha256(review):
        raise ValueError("input review payload SHA-256 is invalid")
    return review


def finalize_input_review(draft_path: Path, output: Path) -> dict[str, Any]:
    if draft_path.expanduser().is_symlink():
        raise ValueError("input review draft must not be a symlink")
    draft = load_strict_json(draft_path)
    if draft.get("payload_sha256") is not None:
        raise ValueError("input review draft payload_sha256 must be null before finalization")
    finalized = copy.deepcopy(draft)
    finalized["payload_sha256"] = contract_payload_sha256(finalized)
    expanded_output = output.expanduser()
    output = expanded_output.parent.resolve() / expanded_output.name
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing to overwrite input review: {output}")
    publish_new_json(output, finalized, validate_input_review)
    return finalized


def _artifact_binding(path: Path, root: Path, schema: str, payload: str) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"bound {schema} artifact must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise ValueError(f"bound {schema} artifact is missing or a symlink")
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("all input-approval artifacts must share one artifact root") from None
    return {
        "path": relative.as_posix(), "sha256": sha256(resolved),
        "size_bytes": resolved.stat().st_size, "schema": schema,
        "payload_sha256": payload,
    }


def _resolve_portable_binding_path(relative_value: Any, owner: Path, label: str) -> Path:
    relative = Path(str(relative_value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"{label} path must be portable and relative")
    root = owner.parent.resolve()
    raw = root / relative
    cursor = raw
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f"{label} path must not traverse a symlink")
        cursor = cursor.parent
    try:
        resolved = raw.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise ValueError(f"{label} path resolves outside its artifact root or is missing") from None
    return resolved


def _resolve_artifact_binding(binding: Any, owner: Path, schema: str) -> tuple[Path, dict[str, Any]]:
    value = _exact_fields(binding, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, "input-approval binding")
    if value["schema"] != schema:
        raise ValueError(f"input-approval binding schema must be {schema}")
    path = _resolve_portable_binding_path(value["path"], owner, "input-approval binding")
    path, document, digest, size = load_strict_json_with_hash(path, "input-approval bound artifact")
    if digest != value["sha256"] or size != value["size_bytes"]:
        raise ValueError("input-approval bound artifact bytes changed")
    if document.get("schema") != schema:
        raise ValueError("input-approval bound artifact schema changed")
    return path, document


def _input_blob_binding(path: Path, root: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("approved Gaussian input must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise ValueError("approved Gaussian input is missing or a symlink")
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("approved Gaussian input must share the receipt artifact root") from None
    return {"path": relative.as_posix(), "sha256": sha256(resolved), "size_bytes": resolved.stat().st_size}


def _resolve_input_blob(binding: Any, owner: Path) -> Path:
    value = _exact_fields(binding, {"path", "sha256", "size_bytes"}, "input-approval input binding")
    path = _resolve_portable_binding_path(value["path"], owner, "input-approval input")
    path, data, digest = read_stable_bytes(path, "input-approval exact input")
    if digest != value["sha256"] or len(data) != value["size_bytes"]:
        raise ValueError("input-approval exact input changed")
    return path


def _assert_work_kind_matches_route(work_kind: str, report: dict[str, Any]) -> None:
    compatibility = input_approval_compatibility(report, work_kind)
    if compatibility["status"] != "supported_generic_v1":
        raise ValueError(f"{compatibility['status']}: {compatibility.get('reason', 'route/work_kind mismatch')}")


def _validate_protocol_consumption(
    binding: dict[str, Any],
    options_path: Path, selection_path: Path, selection: dict[str, Any],
    options: dict[str, Any], selected: dict[str, Any],
) -> None:
    profiles = selected.get("method_profiles")
    tasks = selected.get("task_plan")
    if not isinstance(profiles, list) or not profiles or not isinstance(tasks, list) or not tasks:
        raise ValueError("selected option has no method profiles or task plan")
    expected_identity = {
        "options_sha256": sha256(options_path),
        "options_payload_sha256": options["proposal_payload_sha256"],
        "selection_sha256": sha256(selection_path),
        "selection_payload_sha256": selection["selection_payload_sha256"],
        "selected_option": copy.deepcopy(selection["selected_option"]),
    }
    for key, value in expected_identity.items():
        if binding.get(key) != value:
            raise ValueError("input review does not bind the exact options, selection and selected option")
    available_profiles = {profile["profile_id"] for profile in profiles}
    consumed_profiles = set(binding["used_profile_ids"])
    if not consumed_profiles <= available_profiles:
        raise ValueError("input review consumes a profile outside the selected option")
    referenced_profiles: set[str] = set()
    for consumed in binding["used_tasks"]:
        index = consumed["task_index"]
        if index >= len(tasks):
            raise ValueError("input review consumes a task index outside the selected option")
        selected_task = tasks[index]
        expected_task = {
            "task_index": index,
            "stage_type": selected_task["stage_type"],
            "profile_id": selected_task["profile_id"],
        }
        if consumed != expected_task:
            raise ValueError("input review consumed task differs from the selected option task")
        referenced_profiles.add(consumed["profile_id"])
    if referenced_profiles != consumed_profiles:
        raise ValueError("input review used profiles must exactly equal profiles referenced by consumed tasks")


def _replay_route_profile_mapping(review: dict[str, Any], selected: dict[str, Any]) -> None:
    binding = review["protocol_binding"]
    mapping = review["route_profile_mapping"]
    profiles = {profile["profile_id"]: profile for profile in selected["method_profiles"]}
    field_names = {
        "method": "functional_or_method", "basis": "basis_stack",
        "solvent": "solvation", "scf": "scf",
    }
    for key, field in field_names.items():
        item = mapping[key]
        profile = profiles.get(item["profile_id"])
        if profile is None or item["profile_id"] not in binding["used_profile_ids"]:
            raise ValueError(f"input review {key} mapping names an unselected profile")
        if item["selected_value"] != profile.get(field):
            raise ValueError(f"input review {key} mapping differs from the selected profile payload")
    expected_tasks = binding["used_tasks"]
    mapped_tasks = [
        {"task_index": task["task_index"], "stage_type": task["stage_type"], "profile_id": task["profile_id"]}
        for task in mapping["tasks"]
    ]
    if mapped_tasks != expected_tasks:
        raise ValueError("input review route task mapping differs from the selected task plan")
    _assert_consumed_tasks_match_route(mapping["exact_route"], expected_tasks, mapping["tasks"])


def _assert_consumed_tasks_match_route(
    route: str,
    consumed_tasks: list[dict[str, Any]],
    route_mappings: list[dict[str, Any]],
) -> None:
    if len(consumed_tasks) != len(route_mappings):
        raise ValueError("consumed task and route-mapping counts differ")
    for consumed, mapping in zip(consumed_tasks, route_mappings):
        stage = str(consumed["stage_type"]).lower()
        if stage == "single_guess_ts_opt_freq":
            expected = {"opt_ts", "frequency"}
            valid = route_has_ts_optimization(route) and route_has_frequency(route)
        elif stage in {"opt_freq", "opt_freq_with_stability"}:
            expected = {"minimum_opt", "frequency"}
            valid = (
                route_has_optimization_keyword(route) and route_has_frequency(route)
                and not route_has_ts_optimization(route) and not route_has_scan(route)
            )
        elif "transition_state" in stage:
            expected = {"opt_ts"}
            valid = route_has_ts_optimization(route)
        elif "harmonic_frequency" in stage or stage in {"frequency", "freq"}:
            expected = {"frequency"}
            valid = route_has_frequency(route)
        elif "minimum" in stage or "geometry_optimization" in stage or stage in {"optimization", "opt"}:
            expected = {"minimum_opt"}
            valid = route_has_optimization_keyword(route) and not route_has_ts_optimization(route) and not route_has_scan(route)
        elif "single_point" in stage:
            expected = {"single_point"}
            valid = not any((
                route_has_optimization_keyword(route), route_has_frequency(route),
                route_has_keyword(route, "irc"), route_has_specialist_path(route),
            ))
        else:
            raise ValueError(f"selected task stage_type has no generic /1 route predicate: {stage}")
        if not valid or set(mapping["route_evidence"]) != expected:
            raise ValueError(f"selected task {stage} does not deterministically match the exact route")


def _formula_element_counts(formula: Any) -> dict[str, int]:
    if not isinstance(formula, str) or not formula:
        raise ValueError("protocol request formula is missing")
    tokens = re.findall(r"([A-Z][a-z]?)([0-9]*)", formula)
    if not tokens or "".join(f"{element}{count}" for element, count in tokens) != formula:
        raise ValueError("generic /1 cannot derive exact element counts from the protocol request formula")
    counts: Counter[str] = Counter()
    for element, count in tokens:
        value = int(count) if count else 1
        if value < 1:
            raise ValueError("protocol request formula contains a non-positive element count")
        counts[element] += value
    return dict(sorted(counts.items()))


def _assert_protocol_structure_scope(request_structure: Any, report: dict[str, Any]) -> None:
    if not isinstance(request_structure, dict):
        raise ValueError("protocol request structure scope is missing")
    expected_counts = _formula_element_counts(request_structure.get("formula"))
    if (
        request_structure.get("charge") != report["charge"]
        or request_structure.get("multiplicity") != report["multiplicity"]
        or request_structure.get("atom_count") != report["atom_count"]
        or set(request_structure.get("elements", [])) != set(report["elements"])
        or expected_counts != report["elements"]
        or sum(expected_counts.values()) != report["atom_count"]
    ):
        raise ValueError("protocol request charge/multiplicity/complete element counts differ from the exact input")


def _is_main_group_open_shell_minimum(options: dict[str, Any], review: dict[str, Any]) -> bool:
    request = options.get("request_snapshot", {})
    return review["work_kind"] == "minimum" and request.get("system_class") == "main_group_open_shell"


def _replay_open_shell_minimum_owner(
    state_review_path: Path,
    handoff_path: Path,
    audit_path: Path,
    options_path: Path,
    selection_path: Path,
    input_path: Path,
    report: dict[str, Any],
) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    def same_bound_payload(left: dict[str, Any], right: dict[str, Any]) -> bool:
        keys = {"schema", "sha256", "payload_sha256"}
        return all(left.get(key) == right.get(key) for key in keys)

    owner = _load_open_shell_minimum_owner()
    state_review_file, state_review = owner.state.load_validated_review(state_review_path)
    handoff_file, handoff = owner.load_handoff(handoff_path)
    audit_file, audit = owner.load(audit_path, "input audit", canonical=True)
    owner.validate_input_audit(audit, check_sources=True)
    if audit["status"] != "passed":
        raise ValueError("main-group open-shell input audit is not passed")
    if not same_bound_payload(audit["handoff"], owner.binding(handoff_file, handoff)):
        raise ValueError("main-group open-shell audit/handoff binding drift")
    if not same_bound_payload(handoff["electronic_state_review"], owner.binding(state_review_file, state_review)):
        raise ValueError("main-group open-shell handoff/state-review binding drift")
    if handoff["protocol_options"]["sha256"] != sha256(options_path) or handoff["protocol_selection"]["sha256"] != sha256(selection_path):
        raise ValueError("main-group open-shell handoff protocol source binding drift")
    _, input_bytes, input_digest = read_stable_bytes(input_path, "open-shell exact Gaussian input")
    rendered = handoff["input_text"].encode("utf-8")
    if input_bytes != rendered or input_digest != handoff["input_sha256"] or audit["input_sha256"] != input_digest:
        raise ValueError("main-group open-shell owner artifacts do not bind the exact input bytes")
    if handoff["route"] != report["route"]:
        raise ValueError("main-group open-shell handoff route differs from the exact input")
    state = handoff["state"]
    if state["charge"] != report["charge"] or state["multiplicity"] != report["multiplicity"]:
        raise ValueError("main-group open-shell owner charge/multiplicity drift")
    resources = handoff["resources"]
    if resources["cores"] != report["nprocshared"] or parse_memory(report["mem"]) != int(resources["mem_gb"] * 1024**3):
        raise ValueError("main-group open-shell owner resource binding drift")
    return owner, state_review, handoff, audit


def _make_input_approval_receipt(
    options_path: Path,
    selection_path: Path,
    review_path: Path,
    input_path: Path,
    output: Path,
    receipt_id: str,
    open_shell_state_review_path: Path | None = None,
    open_shell_handoff_path: Path | None = None,
    open_shell_audit_path: Path | None = None,
) -> dict[str, Any]:
    selection, options, selected = protocol_selection.load_validated_selection(selection_path, options_path)
    review = validate_input_review(review_path)
    report = parse_gaussian(input_path)
    _assert_work_kind_matches_route(review["work_kind"], report)
    if review["approved_input"] != _input_approval_facts(report):
        raise ValueError("input review facts differ from the exact Gaussian input")
    if review["protocol_task_types"] != selection["scope_binding"]["task_types"]:
        raise ValueError("input review task types differ from the exact protocol selection")
    _validate_protocol_consumption(
        review["protocol_binding"], options_path, selection_path, selection, options, selected
    )
    _replay_route_profile_mapping(review, selected)
    request_structure = options.get("request_snapshot", {}).get("structure", {})
    _assert_protocol_structure_scope(request_structure, report)
    if review["work_kind"] in {"ts_pilot", "formal_ts"} and review["protocol_task_types"] != [
        "transition_state_optimization", "harmonic_frequency"
    ]:
        raise ValueError("generic single-guess TS approval requires the exact TS optimization + frequency task family")
    if review["work_kind"] == "minimum" and not {"geometry_optimization", "optimization"}.intersection(review["protocol_task_types"]):
        raise ValueError("minimum approval requires a selected geometry_optimization or optimization task")
    resources = selected.get("resources", {})
    if resources.get("cores") != report["nprocshared"]:
        raise ValueError("selected protocol cores differ from the exact input")
    mem_gb = resources.get("mem_gb")
    if not isinstance(mem_gb, (int, float)) or isinstance(mem_gb, bool) or parse_memory(report["mem"]) != int(float(mem_gb) * 1024**3):
        raise ValueError("selected protocol memory differs from the exact input")
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise ValueError("input approval receipt_id is missing")
    root = output.parent.resolve()
    owner_paths = (open_shell_state_review_path, open_shell_handoff_path, open_shell_audit_path)
    open_shell_required = _is_main_group_open_shell_minimum(options, review)
    if open_shell_required and any(path is None for path in owner_paths):
        raise ValueError("main-group open-shell minimum approval requires electronic-state review, input handoff, and passed input audit")
    if not open_shell_required and any(path is not None for path in owner_paths):
        raise ValueError("main-group open-shell owner artifacts are valid only for a main-group open-shell minimum")
    owner_replay = None
    if open_shell_required:
        assert all(path is not None for path in owner_paths)
        owner_replay = _replay_open_shell_minimum_owner(
            open_shell_state_review_path, open_shell_handoff_path, open_shell_audit_path,
            options_path, selection_path, input_path, report,
        )
    document = {
        "schema": OPEN_SHELL_INPUT_APPROVAL_SCHEMA if open_shell_required else INPUT_APPROVAL_SCHEMA,
        "receipt_id": receipt_id,
        "work_kind": review["work_kind"],
        "protocol_task_types": review["protocol_task_types"],
        "sources": {
            "protocol_options": _artifact_binding(options_path, root, "gaussian-protocol-options/1", options["proposal_payload_sha256"]),
            "protocol_selection": _artifact_binding(selection_path, root, "gaussian-protocol-selection/1", selection["selection_payload_sha256"]),
            "input_review": _artifact_binding(review_path, root, INPUT_REVIEW_SCHEMA, review["payload_sha256"]),
        },
        "input": _input_blob_binding(input_path, root),
        "protocol_review_binding": {
            "input_review_payload_sha256": review["payload_sha256"],
            "options_payload_sha256": review["protocol_binding"]["options_payload_sha256"],
            "selection_payload_sha256": review["protocol_binding"]["selection_payload_sha256"],
            "selected_option_payload_sha256": review["protocol_binding"]["selected_option"]["option_payload_sha256"],
            "consumed_profile_ids": copy.deepcopy(review["protocol_binding"]["used_profile_ids"]),
            "consumed_task_indices": [task["task_index"] for task in review["protocol_binding"]["used_tasks"]],
            "exact_route": review["route_profile_mapping"]["exact_route"],
            "route_profile_mapping_sha256": canonical_value_sha256(review["route_profile_mapping"]),
            "explicit_confirmation": True,
        },
        "protocol_family_completion": False,
        "approved_input": _input_approval_facts(report),
        "decision": {"status": "approved_exact_input", "explicit_confirmation": True},
        "single_exact_input_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    if owner_replay is not None:
        owner, state_review, handoff, audit = owner_replay
        document["sources"].update({
            "electronic_state_review": _artifact_binding(open_shell_state_review_path, root, owner.state.SCHEMA_REVIEW, state_review["payload_sha256"]),
            "open_shell_input_handoff": _artifact_binding(open_shell_handoff_path, root, owner.SCHEMA_HANDOFF, handoff["payload_sha256"]),
            "open_shell_input_audit": _artifact_binding(open_shell_audit_path, root, owner.SCHEMA_AUDIT, audit["payload_sha256"]),
        })
        document["specialist_owner_binding"] = {
            "owner": "auto-g16-main-group-open-shell",
            "workflow": owner.WORKFLOW,
            "electronic_state_review_payload_sha256": state_review["payload_sha256"],
            "input_handoff_payload_sha256": handoff["payload_sha256"],
            "input_audit_payload_sha256": audit["payload_sha256"],
            "selected_option_payload_sha256": review["protocol_binding"]["selected_option"]["option_payload_sha256"],
            "input_sha256": handoff["input_sha256"],
            "exact_route": handoff["route"],
            "charge": handoff["state"]["charge"],
            "multiplicity": handoff["state"]["multiplicity"],
            "reference_family": handoff["state"]["reference_family"],
            "resources": copy.deepcopy(handoff["resources"]),
            "owner_replay_passed": True,
        }
    document["payload_sha256"] = contract_payload_sha256(document)
    return document


def build_input_approval_receipt(
    options_path: Path,
    selection_path: Path,
    review_path: Path,
    input_path: Path,
    output: Path,
    receipt_id: str,
    open_shell_state_review_path: Path | None = None,
    open_shell_handoff_path: Path | None = None,
    open_shell_audit_path: Path | None = None,
) -> dict[str, Any]:
    raw_sources = tuple(path for path in (
        options_path, selection_path, review_path, input_path,
        open_shell_state_review_path, open_shell_handoff_path, open_shell_audit_path,
    ) if path is not None)
    if any(path.expanduser().is_symlink() for path in raw_sources):
        raise ValueError("input-approval source artifacts must not be symlinks")
    expanded_output = output.expanduser()
    output = expanded_output.parent.resolve() / expanded_output.name
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing to overwrite input approval receipt: {output}")
    document = _make_input_approval_receipt(
        options_path.expanduser().resolve(), selection_path.expanduser().resolve(),
        review_path.expanduser().resolve(), input_path.expanduser().resolve(), output, receipt_id,
        *(path.expanduser().resolve() if path is not None else None for path in (
            open_shell_state_review_path, open_shell_handoff_path, open_shell_audit_path,
        )),
    )
    publish_new_json(output, document, validate_input_approval_receipt)
    return document


def validate_input_approval_receipt(
    receipt_path: Path,
    *,
    input_path: Path | None = None,
    report: dict[str, Any] | None = None,
    work_kind: str | None = None,
    _document: dict[str, Any] | None = None,
    _resolved_path: Path | None = None,
) -> dict[str, Any]:
    if _document is None:
        expanded_receipt = receipt_path.expanduser()
        if expanded_receipt.is_symlink():
            raise ValueError("input-approval receipt must not be a symlink")
        receipt_path, document, _, _ = load_strict_json_with_hash(
            expanded_receipt, "input-approval receipt"
        )
    else:
        if _resolved_path is None:
            raise ValueError("internal input-approval path binding is missing")
        receipt_path = _resolved_path
        document = _document
    common_fields = {
        "schema", "receipt_id", "work_kind", "protocol_task_types", "sources", "input",
        "protocol_review_binding", "protocol_family_completion", "approved_input", "decision", "single_exact_input_only",
        "calculation_ready", "no_submission_authorization", "payload_sha256",
    }
    schema = document.get("schema")
    if schema not in {INPUT_APPROVAL_SCHEMA, OPEN_SHELL_INPUT_APPROVAL_SCHEMA}:
        raise ValueError("unsupported input approval receipt schema")
    _exact_fields(
        document,
        common_fields | ({"specialist_owner_binding"} if schema == OPEN_SHELL_INPUT_APPROVAL_SCHEMA else set()),
        "input-approval receipt",
    )
    if document["payload_sha256"] != contract_payload_sha256(document):
        raise ValueError("input approval receipt payload SHA-256 is invalid")
    if document["single_exact_input_only"] is not True or document["calculation_ready"] is not False or document["no_submission_authorization"] is not True:
        raise ValueError("input approval receipt authority boundary changed")
    if document["protocol_family_completion"] is not False:
        raise ValueError("one input-approval receipt must not claim whole protocol-family completion")
    if document["decision"] != {"status": "approved_exact_input", "explicit_confirmation": True}:
        raise ValueError("input approval receipt decision changed")
    source_fields = {"protocol_options", "protocol_selection", "input_review"}
    if schema == OPEN_SHELL_INPUT_APPROVAL_SCHEMA:
        source_fields |= {"electronic_state_review", "open_shell_input_handoff", "open_shell_input_audit"}
    sources = _exact_fields(document["sources"], source_fields, "input-approval sources")
    options_path, options = _resolve_artifact_binding(sources["protocol_options"], receipt_path, "gaussian-protocol-options/1")
    selection_path, selection = _resolve_artifact_binding(sources["protocol_selection"], receipt_path, "gaussian-protocol-selection/1")
    review_path, review = _resolve_artifact_binding(sources["input_review"], receipt_path, INPUT_REVIEW_SCHEMA)
    open_shell_paths: tuple[Path | None, Path | None, Path | None] = (None, None, None)
    if schema == OPEN_SHELL_INPUT_APPROVAL_SCHEMA:
        state_review_path, _ = _resolve_artifact_binding(
            sources["electronic_state_review"], receipt_path, "auto-g16-main-group-open-shell-review/1"
        )
        handoff_path, _ = _resolve_artifact_binding(
            sources["open_shell_input_handoff"], receipt_path,
            "auto-g16-main-group-open-shell-minimum-opt-freq-input-handoff/1",
        )
        audit_path, _ = _resolve_artifact_binding(
            sources["open_shell_input_audit"], receipt_path,
            "auto-g16-main-group-open-shell-minimum-opt-freq-input-audit/1",
        )
        open_shell_paths = (state_review_path, handoff_path, audit_path)
    if options.get("proposal_payload_sha256") != sources["protocol_options"]["payload_sha256"]:
        raise ValueError("input approval protocol-options payload changed")
    if selection.get("selection_payload_sha256") != sources["protocol_selection"]["payload_sha256"]:
        raise ValueError("input approval protocol-selection payload changed")
    if review.get("payload_sha256") != sources["input_review"]["payload_sha256"]:
        raise ValueError("input approval review payload changed")
    bound_input = _resolve_input_blob(document["input"], receipt_path)
    expected = _make_input_approval_receipt(
        options_path, selection_path, review_path, bound_input, receipt_path, document["receipt_id"],
        *open_shell_paths,
    )
    if expected != document:
        raise ValueError("input approval receipt differs from owner reconstruction")
    if input_path is not None:
        _, current_bytes, current_digest = read_stable_bytes(input_path, "current Gaussian input snapshot")
        if current_digest != document["input"]["sha256"] or len(current_bytes) != document["input"]["size_bytes"]:
            raise ValueError("input approval is bound to different Gaussian input bytes")
    if report is not None and document["approved_input"] != _input_approval_facts(report):
        raise ValueError("input approval is bound to different current input facts")
    if work_kind is not None and document["work_kind"] != work_kind:
        raise ValueError("input approval work_kind differs from the requested submission")
    return document


def validate_input_approval(
    approval_path: Path,
    input_path: Path,
    report: dict[str, Any],
    work_kind: str,
) -> dict[str, Any]:
    try:
        expanded_approval = approval_path.expanduser()
        if expanded_approval.is_symlink():
            raise ValueError("input-approval receipt must not be a symlink")
        resolved_approval, loaded_document, approval_digest, _ = load_strict_json_with_hash(
            expanded_approval, "input-approval receipt"
        )
        if loaded_document.get("schema") == OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA:
            owner = _load_open_shell_minimum_family_owner()
            document = owner.validate_stage_receipt_file(
                resolved_approval, input_path, report, work_kind,
                _document=loaded_document,
            )
        else:
            compatibility = input_approval_compatibility(report, work_kind)
            if compatibility["status"] == "blocked_combined_open_shell_minimum_stability_parse_risk":
                raise ValueError(
                    "blocked_combined_open_shell_minimum_stability_parse_risk: receipt /1 or /2 "
                    "cannot make the failed same-route Opt/Freq+Stable=Opt input live"
                )
            document = validate_input_approval_receipt(
                resolved_approval, input_path=input_path, report=report, work_kind=work_kind,
                _document=loaded_document, _resolved_path=resolved_approval,
            )
        result = {
            "status": "validated_exact_input_approval",
            "schema": document["schema"],
            "sha256": approval_digest,
            "payload_sha256": document["payload_sha256"],
            "input_sha256": report["input_sha256"],
            "work_kind": document["work_kind"],
            "no_submission_authorization": True,
        }
        if document["schema"] != OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA:
            result.update({
                "protocol_options_schema": document["sources"]["protocol_options"]["schema"],
                "protocol_selection_schema": document["sources"]["protocol_selection"]["schema"],
                "input_review_schema": document["sources"]["input_review"]["schema"],
            })
        if document["schema"] == OPEN_SHELL_INPUT_APPROVAL_SCHEMA:
            result["specialist_owner_binding"] = copy.deepcopy(
                document["specialist_owner_binding"]
            )
        elif document["schema"] == OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA:
            result["specialist_family_binding"] = copy.deepcopy(document["owner_binding"])
            result["family_stage"] = document["stage"]
        return result
    except SystemExit:
        raise
    except Exception as exc:
        fail(f"exact input-approval gate blocked submission: {exc}")
    raise AssertionError("unreachable")


def live_approval_summary(
    project: str,
    report: dict[str, Any],
    maturity: dict[str, Any] | None,
    work_kind: str | None = None,
    input_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "project": project,
        "remote_workdir": remote_project_dir(project),
        "input_sha256": report["input_sha256"],
        "protocol": {
            "route": report["route"],
            "mem": report["mem"],
            "nproc": report["nprocshared"],
        },
        "charge": report["charge"],
        "multiplicity": report["multiplicity"],
    }
    if work_kind is not None:
        summary["work_kind"] = work_kind
    if input_approval is not None:
        summary["input_approval"] = input_approval
    return {"scientific_maturity": maturity, **summary} if maturity is not None else summary


def expected_live_approval_scope(summary: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    expected = {
        "project": summary["project"],
        "remote_workdir": summary["remote_workdir"],
        "input_sha256": summary["input_sha256"],
        "route": summary["protocol"]["route"],
        "mem": summary["protocol"]["mem"],
        "nprocshared": summary["protocol"]["nproc"],
        "charge": summary["charge"],
        "multiplicity": summary["multiplicity"],
    }
    maturity = summary.get("scientific_maturity")
    maturity_schema = maturity.get("schema") if isinstance(maturity, dict) else None
    has_new_binding = "work_kind" in summary or "input_approval" in summary
    if has_new_binding:
        if "work_kind" not in summary or "input_approval" not in summary:
            fail("live approval /3 requires both work_kind and exact input-approval receipt binding")
        input_approval = summary["input_approval"]
        if not isinstance(input_approval, dict) or input_approval.get("status") not in {None, "validated_exact_input_approval"}:
            fail("prospective live approval requires a validated exact input-approval receipt")
        exact_input_approval = {
            key: input_approval.get(key)
            for key in ("schema", "sha256", "payload_sha256", "input_sha256", "work_kind")
        }
        if (
            exact_input_approval["input_sha256"] != summary["input_sha256"]
            or exact_input_approval["work_kind"] != summary["work_kind"]
            or summary["work_kind"] not in ALL_WORK_KINDS
            or any(
                not isinstance(exact_input_approval[key], str)
                or SHA256_RE.fullmatch(exact_input_approval[key]) is None
                for key in ("sha256", "payload_sha256", "input_sha256")
            )
        ):
            fail("prospective live input-approval binding differs from the current exact input/work_kind")
        expected["work_kind"] = summary["work_kind"]
        expected["input_approval"] = exact_input_approval
        if maturity is not None:
            fail(
                "mixed approval generations are forbidden: protected maturity evidence cannot be "
                "combined with a prospective input receipt + live approval"
            )
        if exact_input_approval["schema"] == INPUT_APPROVAL_SCHEMA:
            if summary["multiplicity"] != 1:
                fail("generic receipt /1 and resource-bound live /9 are singlet-only")
            expected_schema = LIVE_APPROVAL_V3_SCHEMA
        elif exact_input_approval["schema"] == OPEN_SHELL_INPUT_APPROVAL_SCHEMA:
            if input_approval.get("status") != "validated_exact_input_approval":
                fail("live approval /4 requires a fully replayed open-shell input receipt /2")
            if summary["work_kind"] != "minimum":
                fail("live approval /4 is restricted to work_kind minimum")
            owner = _exact_fields(
                input_approval.get("specialist_owner_binding"),
                {
                    "owner", "workflow", "electronic_state_review_payload_sha256",
                    "input_handoff_payload_sha256", "input_audit_payload_sha256",
                    "selected_option_payload_sha256", "input_sha256", "exact_route",
                    "charge", "multiplicity", "reference_family", "resources",
                    "owner_replay_passed",
                },
                "live approval /4 open-shell owner binding",
            )
            resources = _exact_fields(
                owner["resources"], {"resource_tier", "mem_gb", "cores"},
                "live approval /4 open-shell resources",
            )
            owner_hashes = (
                "electronic_state_review_payload_sha256", "input_handoff_payload_sha256",
                "input_audit_payload_sha256", "selected_option_payload_sha256",
            )
            if (
                owner["owner"] != "auto-g16-main-group-open-shell"
                or owner["workflow"] != "main_group_open_shell_minimum_opt_freq_v1"
                or owner["input_sha256"] != summary["input_sha256"]
                or owner["exact_route"] != summary["protocol"]["route"]
                or owner["charge"] != summary["charge"]
                or owner["multiplicity"] != summary["multiplicity"]
                or owner["multiplicity"] not in {2, 3}
                or owner["reference_family"] not in {"U", "RO"}
                or owner["owner_replay_passed"] is not True
                or resources["cores"] != summary["protocol"]["nproc"]
                or not isinstance(resources["resource_tier"], str)
                or not resources["resource_tier"]
                or not isinstance(resources["mem_gb"], int)
                or isinstance(resources["mem_gb"], bool)
                or resources["mem_gb"] < 1
                or parse_memory(summary["protocol"]["mem"]) != resources["mem_gb"] * 1024**3
                or any(
                    not isinstance(owner[key], str) or SHA256_RE.fullmatch(owner[key]) is None
                    for key in owner_hashes
                )
            ):
                fail("live approval /4 open-shell owner binding differs from the current exact preflight")
            expected["open_shell_owner"] = copy.deepcopy(owner)
            expected_schema = OPEN_SHELL_LIVE_APPROVAL_SCHEMA
        elif exact_input_approval["schema"] == OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA:
            if input_approval.get("status") != "validated_exact_input_approval":
                fail("live approval /5 requires a fully replayed open-shell family receipt /3")
            if summary["work_kind"] != "minimum":
                fail("live approval /5 is restricted to work_kind minimum")
            owner = _exact_fields(
                input_approval.get("specialist_family_binding"),
                {
                    "owner", "workflow", "family_payload_sha256", "stage", "input_sha256",
                    "route", "charge", "multiplicity", "reference_family", "method", "basis",
                    "resources", "checkpoint_sha256", "owner_replay_passed",
                },
                "live approval /5 open-shell family binding",
            )
            resources = _exact_fields(owner["resources"], {"resource_tier", "mem_gb", "cores"}, "live approval /5 resources")
            if (
                owner["owner"] != "auto-g16-main-group-open-shell"
                or owner["workflow"] != "main_group_open_shell_minimum_two_stage_v1"
                or owner["stage"] not in {"opt_freq", "stability"}
                or owner["input_sha256"] != summary["input_sha256"]
                or owner["route"] != summary["protocol"]["route"]
                or owner["charge"] != summary["charge"]
                or owner["multiplicity"] != summary["multiplicity"]
                or owner["multiplicity"] not in {2, 3}
                or owner["reference_family"] not in {"U", "RO"}
                or owner["owner_replay_passed"] is not True
                or resources["cores"] != summary["protocol"]["nproc"]
                or parse_memory(summary["protocol"]["mem"]) != resources["mem_gb"] * 1024**3
                or not isinstance(owner["method"], str) or not owner["method"]
                or not isinstance(owner["basis"], str) or not owner["basis"]
                or any(not isinstance(owner[key], str) or SHA256_RE.fullmatch(owner[key]) is None for key in ("family_payload_sha256", "input_sha256"))
                or (owner["stage"] == "opt_freq" and owner["checkpoint_sha256"] is not None)
                or (owner["stage"] == "stability" and (not isinstance(owner["checkpoint_sha256"], str) or SHA256_RE.fullmatch(owner["checkpoint_sha256"]) is None))
            ):
                fail("live approval /5 open-shell family binding differs from the current exact preflight")
            expected["open_shell_family"] = copy.deepcopy(owner)
            expected_schema = OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA
        else:
            fail("prospective live approval supports only input receipt /1, /2, or /3")
    else:
        if maturity is None:
            expected_schema = LIVE_APPROVAL_V1_SCHEMA
        elif maturity_schema == MATURITY_ACTION_V1_SCHEMA:
            expected_schema = LIVE_APPROVAL_V2_SCHEMA
        elif maturity_schema == MATURITY_ACTION_V2_SCHEMA:
            fail(
                "maturity action /2 live replay is not integrated; future protected live requires "
                "an exact maturity action /2, action authorization /2, and specialist input receipt"
            )
        else:
            fail(f"unsupported scientific-maturity action schema: {maturity_schema!r}")
    if maturity_schema == MATURITY_ACTION_V1_SCHEMA:
        exact_authorization = maturity.get("exact_action_authorization")
        if not isinstance(exact_authorization, dict):
            fail("TS live approval requires an exact scientific action authorization")
        expected["scientific_maturity"] = {
            "edge_id": maturity["edge_id"],
            "pilot": maturity["pilot"],
            "maturity_gate_sha256": maturity["maturity_gate_sha256"],
            "maturity_gate_payload_sha256": maturity["maturity_gate_payload_sha256"],
            "node_id": maturity["node_id"],
            "scientific_action_authorization_sha256": exact_authorization["sha256"],
            "scientific_action_authorization_payload_sha256": exact_authorization["payload_sha256"],
        }
    execution = summary.get("execution")
    if execution is not None:
        resource_binding = execution.get("resource_binding") if isinstance(execution, dict) else None
        execution_fields = {
            "batch_id", "review_sha256", "scientific_task_id", "attempt_id",
            "idempotency_key", "estimated_core_hours",
            "estimated_core_hours_evidence",
        }
        if resource_binding is not None:
            execution_fields.add("resource_binding")
        try:
            exact_execution = _exact_fields(
                execution,
                execution_fields,
                "protected live execution binding",
            )
            evidence = _exact_fields(
                exact_execution["estimated_core_hours_evidence"],
                {"source", "sha256"},
                "estimated core-hour evidence",
            )
        except ValueError as exc:
            fail(str(exc))
        if (
            not isinstance(exact_execution["batch_id"], str)
            or not exact_execution["batch_id"]
            or not isinstance(exact_execution["scientific_task_id"], str)
            or not exact_execution["scientific_task_id"].startswith("scientific-task-")
            or not isinstance(exact_execution["attempt_id"], str)
            or not exact_execution["attempt_id"].startswith("qsub-attempt-")
            or not isinstance(exact_execution["idempotency_key"], str)
            or not exact_execution["idempotency_key"]
            or not isinstance(exact_execution["estimated_core_hours"], (int, float))
            or isinstance(exact_execution["estimated_core_hours"], bool)
            or not math.isfinite(float(exact_execution["estimated_core_hours"]))
            or float(exact_execution["estimated_core_hours"]) <= 0
            or any(
                not isinstance(exact_execution[key], str)
                or SHA256_RE.fullmatch(exact_execution[key]) is None
                for key in ("review_sha256",)
            )
            or not isinstance(evidence["source"], str)
            or not evidence["source"]
            or not isinstance(evidence["sha256"], str)
            or SHA256_RE.fullmatch(evidence["sha256"]) is None
        ):
            fail("protected live execution binding is malformed")
        expected["operation"] = "submit"
        expected["execution"] = copy.deepcopy(exact_execution)
        if resource_binding is not None:
            try:
                exact_resource = _exact_fields(
                    resource_binding,
                    {
                        "policy_id", "policy_sha256", "gate_id", "gate_sha256",
                        "resource_tier", "cores", "memory_gb", "walltime_seconds",
                    },
                    "resource-bound live execution",
                )
            except ValueError as exc:
                fail(str(exc))
            if (
                any(not isinstance(exact_resource[key], str) or not exact_resource[key] for key in ("policy_id", "gate_id", "resource_tier"))
                or any(not isinstance(exact_resource[key], str) or SHA256_RE.fullmatch(exact_resource[key]) is None for key in ("policy_sha256", "gate_sha256"))
                or any(isinstance(exact_resource[key], bool) or not isinstance(exact_resource[key], int) or exact_resource[key] < 1 for key in ("cores", "memory_gb", "walltime_seconds"))
                or exact_resource["cores"] != summary["protocol"]["nproc"]
                or exact_resource["memory_gb"] * 1024**3 != parse_memory(summary["protocol"]["mem"])
            ):
                fail("resource-bound live execution differs from the exact Gaussian/PBS resources")
            try:
                resource_efficiency.validate_resource_tuple(
                    exact_resource["resource_tier"], exact_resource["cores"], exact_resource["memory_gb"]
                )
            except resource_efficiency.ResourceError as exc:
                fail(str(exc))
            owner_key = (
                "open_shell_owner" if expected_schema == OPEN_SHELL_LIVE_APPROVAL_SCHEMA
                else "open_shell_family" if expected_schema == OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA
                else None
            )
            if owner_key is not None:
                owner_resources = expected[owner_key]["resources"]
                if (
                    owner_resources["resource_tier"] != exact_resource["resource_tier"]
                    or owner_resources["cores"] != exact_resource["cores"]
                    or owner_resources["mem_gb"] != exact_resource["memory_gb"]
                ):
                    fail("specialist owner resources differ from the exact resource-bound live gate")
            schema_upgrade = {
                LIVE_APPROVAL_V3_SCHEMA: LIVE_APPROVAL_V9_SCHEMA,
                OPEN_SHELL_LIVE_APPROVAL_SCHEMA: OPEN_SHELL_LIVE_APPROVAL_V10_SCHEMA,
                OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA: OPEN_SHELL_FAMILY_LIVE_APPROVAL_V11_SCHEMA,
            }
        else:
            schema_upgrade = {
                LIVE_APPROVAL_V3_SCHEMA: LIVE_APPROVAL_V6_SCHEMA,
                OPEN_SHELL_LIVE_APPROVAL_SCHEMA: OPEN_SHELL_LIVE_APPROVAL_V7_SCHEMA,
                OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA: OPEN_SHELL_FAMILY_LIVE_APPROVAL_V8_SCHEMA,
            }
        if expected_schema not in schema_upgrade:
            fail("historical approval generations cannot enter a new protected submit")
        expected_schema = schema_upgrade[expected_schema]
    return expected_schema, expected


def _validate_live_approval_document(approval: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    expected_schema, expected = expected_live_approval_scope(summary)
    protected_schemas = {
        LIVE_APPROVAL_V6_SCHEMA,
        OPEN_SHELL_LIVE_APPROVAL_V7_SCHEMA,
        OPEN_SHELL_FAMILY_LIVE_APPROVAL_V8_SCHEMA,
        LIVE_APPROVAL_V9_SCHEMA,
        OPEN_SHELL_LIVE_APPROVAL_V10_SCHEMA,
        OPEN_SHELL_FAMILY_LIVE_APPROVAL_V11_SCHEMA,
    }
    if expected_schema in protected_schemas:
        try:
            _exact_fields(
                approval,
                {
                    "schema", "approval_id", "approver_identity", "approved_at",
                    "expires_at", "decision", "explicit_confirmation", "scope",
                    "revocation", "consumption", "authorizations",
                },
                "protected live approval",
            )
            revocation = _exact_fields(
                approval["revocation"], {"revoked", "revoked_at", "reason"},
                "live approval revocation",
            )
            consumption = _exact_fields(
                approval["consumption"], {"single_use", "consumed"},
                "live approval consumption",
            )
        except ValueError as exc:
            fail(str(exc))
        if not isinstance(approval["approval_id"], str) or not approval["approval_id"].strip():
            fail("protected live approval requires a one-time approval_id")
        if not isinstance(approval["approver_identity"], str) or not approval["approver_identity"].strip():
            fail("protected live approval requires approver_identity")
        try:
            approved_at = execution_batch.parse_time(approval["approved_at"])
            expires_at = execution_batch.parse_time(approval["expires_at"])
        except (execution_batch.BatchError, resource_efficiency.ResourceError) as exc:
            fail(f"protected live approval timestamp is invalid: {exc}")
        now = datetime.now(timezone.utc)
        if approved_at > now or expires_at <= approved_at or now >= expires_at:
            fail("protected live approval is not currently within its approved time window")
        if revocation != {"revoked": False, "revoked_at": None, "reason": None}:
            fail("protected live approval has been revoked or has malformed revocation state")
        if consumption != {"single_use": True, "consumed": False}:
            fail("protected live approval must be active and single-use before reservation")
    elif expected_schema in {OPEN_SHELL_LIVE_APPROVAL_SCHEMA, OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA}:
        try:
            _exact_fields(
                approval,
                {"schema", "decision", "explicit_confirmation", "scope", "authorizations"},
                "open-shell live approval",
            )
        except ValueError as exc:
            fail(str(exc))
    if approval.get("schema") != expected_schema:
        fail("live approval record has the wrong schema")
    if approval.get("decision") != "approved" or approval.get("explicit_confirmation") is not True:
        fail("live approval record lacks an explicit approved decision")
    if approval.get("scope") != expected:
        fail("live approval scope does not exactly match the current preflight")
    if approval.get("authorizations") != {
        "create_server_directory": True,
        "submit": True,
        "retry": False,
        "cancel": False,
        "cleanup": False,
        "delete_server_data": False,
    }:
        fail("live approval authorization boundary changed")
    return approval


def live_approval_scope_proposal(summary: dict[str, Any]) -> dict[str, Any]:
    """Return an offline proposal only; never manufacture an approved record."""

    required_schema, scope = expected_live_approval_scope(summary)
    return {
        "required_schema": required_schema,
        "scope_proposal": scope,
        "proposal_only": True,
        "no_submission_authorization": True,
    }


def validate_live_approval_binding(path: Path, summary: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        expanded = path.expanduser()
        if expanded.is_symlink():
            raise ValueError("live approval record must not be a symlink")
        _, approval, digest, _ = load_strict_json_with_hash(expanded, "live approval record")
    except ValueError as exc:
        fail(f"cannot read live approval record: {exc}")
    return _validate_live_approval_document(approval, summary), digest


def validate_live_approval(path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    return validate_live_approval_binding(path, summary)[0]


def audit_scientific_maturity(args: Any, report: dict[str, Any], action: str) -> dict[str, Any] | None:
    protected = classify_protected_input(report)
    work_kind = getattr(args, "work_kind", None)
    if protected is None:
        if work_kind not in {None, "ordinary", "minimum"}:
            fail(f"--work-kind {work_kind} does not match an ordinary/minimum route")
        return None
    if protected == "specialist_opt":
        fail("Conical/Avoided optimization requires a dedicated specialist input owner and cannot use ordinary TS maturity")
    if protected == "specialist_path":
        fail("IRCMax/standalone Scan requires a dedicated specialist path owner and cannot use ordinary IRC or TS authority")
    expected_kinds = {
        "ts": {"ts_pilot", "formal_ts"},
        "ts_scan": {"ts_scan"},
        "irc": {"irc_forward", "irc_reverse"},
    }[protected]
    if work_kind not in expected_kinds:
        fail(f"protected {protected} route requires explicit --work-kind in {sorted(expected_kinds)}")
    pilot = work_kind in {"ts_pilot", "ts_scan"}
    if bool(getattr(args, "pilot", False)) != pilot:
        fail(f"--pilot must be {'set' if pilot else 'unset'} for --work-kind {work_kind}")
    maturity_action = "irc_input" if protected == "irc" else action
    gate_value = getattr(args, "scientific_maturity", None)
    edge_id = getattr(args, "edge_id", None)
    node_id = getattr(args, "node_id", None)
    if not gate_value or not edge_id or not node_id:
        fail("protected input/submission requires --scientific-maturity, --edge-id, and exact --node-id with two accepted Gaussian minima")
    tier = _resource_tier(report["mem"], report["nprocshared"])
    if tier == "custom":
        fail("TS maturity gate requires an exact reviewed simple/general/complex resource tier")
    raw_gate_path = Path(gate_value).expanduser()
    gate_schema, maturity, gate_path = _maturity_owner_for_gate(raw_gate_path)
    prospective_live = bool(getattr(args, "_prospective_live", False))
    if prospective_live and gate_schema == MATURITY_GATE_V1_SCHEMA:
        fail(
            "scientific-maturity gate /1 is historical replay-only for protected work; future "
            "protected live requires an exact maturity action /2, action authorization /2, "
            "and specialist input receipt"
        )
    try:
        if gate_schema == MATURITY_GATE_V1_SCHEMA:
            check = maturity.assert_action(
                gate_path, edge_id, maturity_action, pilot=pilot,
                resource_tier=tier, node_id=node_id,
            )
        else:
            check = maturity.assert_action(
                gate_path, edge_id, node_id, maturity_action, pilot=pilot,
            )
        if prospective_live and gate_schema == MATURITY_GATE_V2_SCHEMA:
            fail(
                "protected live integration remains unavailable after maturity /2 replay; future "
                "protected live requires an exact maturity action /2, action authorization /2, "
                "and specialist input receipt"
            )
        if action == "ts_submission" and gate_schema == MATURITY_GATE_V1_SCHEMA:
            authorization_value = getattr(args, "scientific_action_authorization", None)
            if not authorization_value:
                fail("protected TS/scan submission requires one exact --scientific-action-authorization")
            authorization = maturity.validate_action_authorization(
                Path(authorization_value).expanduser().resolve(),
                gate_path=gate_path,
                input_sha256=report["input_sha256"],
                edge_id=edge_id,
                node_id=node_id,
                project=args.project,
                work_kind=work_kind,
                resource_tier=tier,
            )
            check["exact_action_authorization"] = {
                "sha256": sha256(Path(authorization_value).expanduser().resolve()),
                "payload_sha256": authorization["payload_sha256"],
                "node_id": authorization["scope"]["node_id"],
                "project": authorization["scope"]["project"],
                "input_sha256": authorization["input"]["sha256"],
                "no_submission_authorization": True,
            }
        return check
    except Exception as exc:
        future = (
            "; future protected live requires an exact maturity action /2, action authorization /2, "
            "and specialist input receipt"
            if prospective_live else ""
        )
        fail(f"scientific-maturity gate blocked {maturity_action}: {exc}{future}")
    return None


def parse_gaussian(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"input does not exist: {path}")
    if path.suffix.lower() not in {".gjf", ".com"}:
        fail("Gaussian input must end in .gjf or .com")
    text = path.read_text(encoding="utf-8")
    segments = re.split(r"(?im)^\s*--link1--\s*$", text)
    link1_count = len(segments) - 1
    route_section_count = len(re.findall(r"(?m)^\s*#", text))
    lines = segments[0].splitlines()
    if not text.endswith("\n\n"):
        fail("Gaussian input must end with a trailing blank line")

    link0: dict[str, str] = {}
    for line in lines:
        if line.startswith("%") and "=" in line:
            key, value = line[1:].split("=", 1)
            link0[key.strip().lower()] = value.strip()
    for required in ("chk", "mem", "nprocshared"):
        if not link0.get(required):
            fail(f"missing %{required}= link-0 directive")
    checkpoint = link0["chk"]
    if Path(checkpoint).name != checkpoint or "/" in checkpoint or "\\" in checkpoint:
        fail("%chk must be a local basename inside the job directory")
    oldcheckpoint = link0.get("oldchk")
    if oldcheckpoint:
        if Path(oldcheckpoint).name != oldcheckpoint or "/" in oldcheckpoint or "\\" in oldcheckpoint:
            fail("%oldchk must be a local basename inside the job directory")
        if oldcheckpoint == checkpoint:
            fail("%oldchk and %chk must use distinct basenames")
    try:
        nproc = int(link0["nprocshared"])
    except ValueError:
        fail("%nprocshared must be an integer")
    if not 1 <= nproc <= MAX_CORES:
        fail(f"%nprocshared must be between 1 and {MAX_CORES}")
    memory_bytes = parse_memory(link0["mem"])
    if memory_bytes > MAX_MEMORY_BYTES:
        fail("%mem exceeds the server's 120 GB physical-memory ceiling")

    route_start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    if route_start is None:
        fail("missing Gaussian route section")
    route_lines: list[str] = []
    i = route_start
    while i < len(lines) and lines[i].strip():
        route_lines.append(lines[i].strip())
        i += 1
    route = " ".join(route_lines)
    geom_allcheck = bool(re.search(r"\bgeom\s*=\s*allcheck\b", route, re.I))

    manifest_path = path.with_suffix(".json")
    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            manifest = load_strict_json(manifest_path)
        except (OSError, ValueError) as exc:
            fail(f"could not read Gaussian companion manifest: {exc}")

    while i < len(lines) and not lines[i].strip():
        i += 1
    elements: Counter[str] = Counter()
    atom_order: list[dict[str, Any]] | None = None
    oldcheckpoint_sha256: str | None = None
    trailing_section_lines: list[str] = []
    if geom_allcheck:
        if any(line.strip() for line in lines[i:]):
            fail("Geom=AllCheck input must omit title, charge/multiplicity, and explicit coordinates")
        if not oldcheckpoint:
            fail("Geom=AllCheck input requires an explicit %oldchk reviewed checkpoint")
        allowed_allcheck_manifests = {
            "gaussian-allcheck-input-manifest/1",
            "auto-g16-main-group-open-shell-minimum-stability-input-manifest/1",
        }
        if not manifest or manifest.get("schema") not in allowed_allcheck_manifests:
            fail("Geom=AllCheck input requires a recognized closed checkpoint companion manifest")
        if manifest.get("schema") == "auto-g16-main-group-open-shell-minimum-stability-input-manifest/1":
            try:
                _load_open_shell_minimum_family_owner().validate_stability_manifest(
                    manifest, input_path=path
                )
            except Exception as exc:
                fail(f"open-shell stability manifest owner gate failed: {exc}")
        if manifest.get("geometry_source") != "geom_allcheck_from_reviewed_checkpoint" or manifest.get("no_explicit_molecule_specification") is not True:
            fail("AllCheck companion manifest does not certify coordinate-free checkpoint geometry")
        if manifest.get("input_sha256") != sha256(path):
            fail("AllCheck companion manifest input hash does not match the Gaussian input")
        if manifest.get("checkpoint_file") != oldcheckpoint:
            fail("AllCheck companion checkpoint filename differs from %oldchk")
        checkpoint_path = path.parent / oldcheckpoint
        if not checkpoint_path.is_file() or checkpoint_path.is_symlink():
            fail("Geom=AllCheck %oldchk must be an existing non-symlink file beside the input")
        oldcheckpoint_sha256 = sha256(checkpoint_path)
        if manifest.get("checkpoint_sha256") != oldcheckpoint_sha256:
            fail("AllCheck companion checkpoint hash does not match %oldchk")
        try:
            charge = int(manifest["charge"])
            multiplicity = int(manifest["multiplicity"])
            coordinate_count = int(manifest["atom_count"])
        except (KeyError, TypeError, ValueError):
            fail("AllCheck companion has invalid charge, multiplicity, or atom count")
        if multiplicity < 1 or coordinate_count < 1:
            fail("AllCheck companion multiplicity and atom count must be positive")
        atom_order = manifest.get("atom_order")
        if not isinstance(atom_order, list) or len(atom_order) != coordinate_count:
            fail("AllCheck companion atom order length differs from atom count")
        expected_indices = list(range(1, coordinate_count + 1))
        if [item.get("index") for item in atom_order if isinstance(item, dict)] != expected_indices:
            fail("AllCheck companion atom order must use contiguous one-based indices")
        for item in atom_order:
            if not isinstance(item, dict) or not re.fullmatch(r"[A-Z][a-z]?", str(item.get("element", ""))):
                fail("AllCheck companion contains an invalid atom-order entry")
            if not isinstance(item.get("atomic_number"), int) or item["atomic_number"] < 1:
                fail("AllCheck companion contains an invalid atomic number")
            elements[str(item["element"])] += 1
    else:
        while i < len(lines) and lines[i].strip():
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            fail("missing charge/multiplicity line")
        charge_mult = lines[i].split()
        if len(charge_mult) != 2:
            fail("charge/multiplicity line must contain exactly two integers")
        try:
            charge, multiplicity = map(int, charge_mult)
        except ValueError:
            fail("charge/multiplicity line must contain integers")
        if multiplicity < 1:
            fail("multiplicity must be at least 1")
        i += 1
        coordinate_count = 0
        while i < len(lines) and lines[i].strip():
            fields = lines[i].split()
            if len(fields) < 4:
                fail(f"malformed Cartesian coordinate at line {i + 1}")
            element = fields[0]
            if not re.fullmatch(r"[A-Z][a-z]?", element):
                fail(f"invalid element symbol at line {i + 1}: {element}")
            try:
                xyz = [float(value) for value in fields[1:4]]
            except ValueError:
                fail(f"non-numeric Cartesian coordinate at line {i + 1}")
            if not all(math.isfinite(value) for value in xyz):
                fail(f"non-finite Cartesian coordinate at line {i + 1}")
            elements[element] += 1
            coordinate_count += 1
            i += 1
        if coordinate_count == 0:
            fail("no Cartesian coordinates found")
        trailing_section_lines = [line.strip() for line in lines[i:] if line.strip()]

    relaxed_scan_re = re.compile(
        r"(?:^|\s)S\s+[0-9]+\s+[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?(?:\s|$)",
        re.I,
    )
    legacy_relaxed_scan = route_has_relaxed_scan_context(route) and any(
        relaxed_scan_re.search(line) for line in trailing_section_lines
    )
    gic_tail = " ".join(trailing_section_lines)
    gic_relaxed_scan = route_has_gic_optimization(route) and bool(
        re.search(r"\bNSteps\s*=\s*[0-9]+\b", gic_tail, re.I)
        and re.search(
            r"\bStepSize\s*=\s*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\b",
            gic_tail, re.I,
        )
    )
    has_relaxed_scan_directive = legacy_relaxed_scan or gic_relaxed_scan

    report = {
        "input": str(path.resolve()),
        "input_sha256": sha256(path),
        "checkpoint": checkpoint,
        "oldcheckpoint": oldcheckpoint,
        "oldcheckpoint_sha256": oldcheckpoint_sha256,
        "mem": link0["mem"],
        "memory_bytes": memory_bytes,
        "nprocshared": nproc,
        "route": route,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": coordinate_count,
        "elements": dict(sorted(elements.items())),
        "atom_order": atom_order,
        "geometry_source": "geom_allcheck_from_reviewed_checkpoint" if geom_allcheck else "explicit_cartesian",
        "link1_count": link1_count,
        "route_section_count": route_section_count,
        "trailing_section_line_count": len(trailing_section_lines),
        "has_relaxed_scan_directive": has_relaxed_scan_directive,
        "trailing_blank_line": True,
    }
    report["manifest"] = None
    report["manifest_warnings"] = []
    if manifest is not None:
        warnings = manifest.get("warnings", [])
        if not isinstance(warnings, list):
            fail("companion manifest warnings must be a list")
        if warnings:
            fail("companion manifest contains unresolved warnings: " + "; ".join(map(str, warnings)))
        owner_nonauthorizing_manifest = manifest.get("schema") == "auto-g16-main-group-open-shell-minimum-stability-input-manifest/1"
        if not owner_nonauthorizing_manifest and (manifest.get("candidate_only") is True or manifest.get("calculation_ready") is False):
            fail("companion manifest marks this as an unselected conformer candidate; review and select it first")
        centers = manifest.get("chiral_centers", [])
        if any(isinstance(center, dict) and center.get("cip") == "?" for center in centers):
            fail("companion manifest contains unassigned tetrahedral stereochemistry")
        manifest_charge = manifest.get("charge_used")
        manifest_mult = manifest.get("multiplicity_used")
        manifest_atoms = manifest.get("atom_count_in_gaussian_input")
        if manifest_charge is not None and manifest_charge != charge:
            fail("charge differs between Gaussian input and companion manifest")
        if manifest_mult is not None and manifest_mult != multiplicity:
            fail("multiplicity differs between Gaussian input and companion manifest")
        if manifest_atoms is not None and manifest_atoms != coordinate_count:
            fail("atom count differs between Gaussian input and companion manifest")
        report["manifest"] = str(manifest_path.resolve())
    return report


def _pbs_walltime(seconds: int) -> str:
    if not isinstance(seconds, int) or seconds < 1:
        raise ValueError("PBS walltime must be a positive reviewed integer")
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds_value = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_value:02d}"


def pbs_text(
    project: str, input_name: str, nproc: int, *, mem_gb: int | None = None,
    walltime_seconds: int | None = None, resource_tier: str | None = None,
) -> str:
    resource_lines = ""
    if any(value is not None for value in (mem_gb, walltime_seconds, resource_tier)):
        if (
            not isinstance(mem_gb, int) or mem_gb < 1
            or not isinstance(walltime_seconds, int) or walltime_seconds < 1
            or not isinstance(resource_tier, str) or not resource_tier.strip()
        ):
            raise ValueError("resource-bound PBS generation requires exact tier, memory, and walltime")
        resource_efficiency.validate_resource_tuple(resource_tier, nproc, mem_gb)
        resource_lines = (
            f"#PBS -l mem={mem_gb}gb\n"
            f"#PBS -l walltime={_pbs_walltime(walltime_seconds)}\n"
            f"# AUTO_G16_RESOURCE_TIER={resource_tier}\n"
        )
    return f"""#!/bin/sh
#PBS -N {project}
#PBS -j oe
#PBS -l nodes=1:ppn={nproc}
{resource_lines}#PBS -V
#PBS -o ./{project}.pbs.out

set -eu

allowed_root="{DEFAULT_REMOTE_ROOT}"
root_real=$(realpath -e -- "$allowed_root")
work_real=$(realpath -e -- "$PBS_O_WORKDIR")
if [ "$root_real" != "$allowed_root" ]; then
  echo "Refusing to run: allowed root is missing, moved, or a symlink" >&2
  exit 40
fi
case "$work_real" in
  "$allowed_root"/*) ;;
  *) echo "Refusing to run outside $allowed_root" >&2; exit 41 ;;
esac
if [ -L "$PBS_O_WORKDIR" ]; then
  echo "Refusing to run from a symbolic-link work directory" >&2
  exit 42
fi

cd "$work_real"
scratch="$work_real/scratch"
if [ -L "$scratch" ]; then
  echo "Refusing symbolic-link scratch directory" >&2
  exit 43
fi
mkdir -p -- "$scratch"
scratch_real=$(realpath -e -- "$scratch")
case "$scratch_real" in
  "$work_real"/*) ;;
  *) echo "Refusing scratch outside the project directory" >&2; exit 44 ;;
esac
export GAUSS_SCRDIR="$scratch_real"
g16 "{input_name}"
"""


def stage(
    input_path: Path, project: str, local_dir: Path,
    resource_binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    audit = parse_gaussian(input_path)
    validate_transfer_name(input_path.name)
    local_dir.mkdir(parents=True, exist_ok=True)
    existing_job_path = local_dir / "job.json"
    if existing_job_path.is_file():
        try:
            existing_job = json.loads(existing_job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"could not read existing job metadata: {exc}")
        protected_states = {
            "submitted", "queued", "running", "held", "exiting", "stale",
            "completed", "failed", "interrupted", "cancel_requested",
            "submission_uncertain",
        }
        if existing_job.get("status") in protected_states:
            fail(
                f"local bundle already records status {existing_job.get('status')!r}; "
                "use a new project/local directory instead of risking a duplicate run"
            )
    destination = local_dir / input_path.name
    if destination.resolve() != input_path.resolve():
        if destination.is_symlink():
            fail(f"refusing symlink staged input: {destination}")
        if destination.exists():
            if sha256(destination) != sha256(input_path):
                fail(f"refusing to overwrite different staged input: {destination}")
        else:
            shutil.copy2(input_path, destination)
    else:
        destination = input_path

    companions: list[Path] = []
    for suffix in (".json", ".xyz"):
        source = input_path.with_suffix(suffix)
        validate_transfer_name(source.name)
        target = local_dir / source.name
        if source.is_file():
            if target.resolve() != source.resolve():
                if target.is_symlink():
                    fail(f"refusing symlink staged companion: {target}")
                if target.exists():
                    if sha256(target) != sha256(source):
                        fail(f"refusing to overwrite different companion: {target}")
                else:
                    shutil.copy2(source, target)
            companions.append(target)

    oldcheckpoint = audit.get("oldcheckpoint")
    if oldcheckpoint:
        validate_transfer_name(oldcheckpoint)
        source = input_path.parent / oldcheckpoint
        if not source.is_file() or source.is_symlink():
            fail("%oldchk must name an existing non-symlink checkpoint beside the input")
        target = local_dir / oldcheckpoint
        if target.resolve() != source.resolve():
            if target.is_symlink():
                fail(f"refusing symlink staged checkpoint: {target}")
            if target.exists():
                if sha256(target) != sha256(source):
                    fail(f"refusing to overwrite different checkpoint companion: {target}")
            else:
                shutil.copy2(source, target)
        companions.append(target)

    pbs = local_dir / f"{project}.pbs"
    pbs_kwargs: dict[str, Any] = {}
    if resource_binding is not None:
        if resource_binding["cores"] != audit["nprocshared"]:
            fail("resource gate cores differ from Gaussian %nprocshared")
        if resource_binding["memory_gb"] * 1024**3 != parse_memory(audit["mem"]):
            fail("resource gate memory differs from Gaussian %mem")
        pbs_kwargs = {
            "mem_gb": resource_binding["memory_gb"],
            "walltime_seconds": resource_binding["walltime_seconds"],
            "resource_tier": resource_binding["resource_tier"],
        }
    atomic_text(pbs, pbs_text(project, destination.name, audit["nprocshared"], **pbs_kwargs))
    immutable = [destination, *companions, pbs]
    checksums = local_dir / "checksums.sha256"
    atomic_text(checksums, "".join(f"{sha256(item)}  {item.name}\n" for item in immutable))
    job = {
        "schema": "gaussian-rtwin-pbs/1",
        "project": project,
        "status": "staged",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "input": destination.name,
        "input_sha256": audit["input_sha256"],
        "pbs_script": pbs.name,
        "checksums": checksums.name,
        "remote_workdir": remote_project_dir(project),
        "job_id": None,
        "gaussian": audit,
        "resource_binding": copy.deepcopy(resource_binding),
    }
    initialize_job_state(local_dir, job)
    # job.json is mutable local control-plane state and is never uploaded.
    return job, [*immutable, checksums]


def ssh_base(args) -> list[str]:
    config = Path(args.mac_ssh_config).expanduser()
    if not config.is_file():
        fail(f"Mac SSH config not found: {config}")
    return ["ssh", "-F", str(config), args.rtwin_alias]


def nested_ssh(args, *remote_command: str) -> list[str]:
    return [
        *ssh_base(args),
        "ssh", "-F", args.windows_server_config,
        args.server_alias, *remote_command,
    ]


def powershell_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def update_job(local_dir: Path, **updates: Any) -> dict[str, Any]:
    path = local_dir / "job.json"
    events_path = local_dir / "job.events.jsonl"
    with locked_state(path):
        events = _load_job_events(events_path)
        if not events:
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"local job state is unavailable: {path}")
            current = json.loads(path.read_text(encoding="utf-8"))
            _append_job_event_locked(
                events_path,
                events,
                "legacy_snapshot_imported",
                {"replace": current},
            )
            events = _load_job_events(events_path)
        current = _derive_job_state(events)
        _append_job_event_locked(
            events_path,
            events,
            "job_state_updated",
            {"updates": copy.deepcopy(updates)},
        )
        current.update(updates)
        current["state_revision"] = len(events) + 1
        current["state_event_sha256"] = _load_job_events(events_path)[-1]["event_sha256"]
        current["state_sha256"] = canonical_digest(
            {key: value for key, value in current.items() if key != "state_sha256"}
        )
        atomic_json(path, current)
        return current


def _load_job_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("job event log must be a regular non-symlink file")
    events: list[dict[str, Any]] = []
    previous: str | None = None
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"job event log line {index} is invalid: {exc}") from exc
        if not isinstance(event, dict) or set(event) != {
            "sequence", "event_type", "timestamp", "previous_event_sha256",
            "payload", "event_sha256",
        }:
            raise ValueError("job event log contains an open or malformed record")
        if event["sequence"] != index or event["previous_event_sha256"] != previous:
            raise ValueError("job event log sequence/hash chain is discontinuous")
        if event["event_sha256"] != canonical_digest(
            {key: value for key, value in event.items() if key != "event_sha256"}
        ):
            raise ValueError("job event hash mismatch")
        previous = event["event_sha256"]
        events.append(event)
    return events


def _append_job_event_locked(
    path: Path,
    events: list[dict[str, Any]],
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    event = {
        "sequence": len(events) + 1,
        "event_type": event_type,
        "timestamp": utc_now(),
        "previous_event_sha256": events[-1]["event_sha256"] if events else None,
        "payload": payload,
    }
    event["event_sha256"] = canonical_digest(event)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        pass
    return event


def _derive_job_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    current: dict[str, Any] = {}
    for event in events:
        payload = event["payload"]
        if "replace" in payload:
            current = copy.deepcopy(payload["replace"])
        elif "updates" in payload:
            current.update(copy.deepcopy(payload["updates"]))
        else:
            raise ValueError("job event payload has no recognized state operation")
    if not events:
        raise ValueError("job event log is empty")
    current["state_revision"] = len(events)
    current["state_event_sha256"] = events[-1]["event_sha256"]
    current["state_sha256"] = canonical_digest(
        {key: value for key, value in current.items() if key != "state_sha256"}
    )
    return current


def initialize_job_state(local_dir: Path, job: dict[str, Any]) -> dict[str, Any]:
    path = local_dir / "job.json"
    events_path = local_dir / "job.events.jsonl"
    with locked_state(path):
        if events_path.exists():
            raise ValueError(
                "refusing to replace existing append-only job event history; use a fresh local directory"
            )
        event = _append_job_event_locked(
            events_path, [], "job_state_initialized", {"replace": copy.deepcopy(job)}
        )
        current = copy.deepcopy(job)
        current["state_revision"] = 1
        current["state_event_sha256"] = event["event_sha256"]
        current["state_sha256"] = canonical_digest(current)
        atomic_json(path, current)
        return current


def read_job_state(local_dir: Path) -> dict[str, Any]:
    path = local_dir / "job.json"
    events_path = local_dir / "job.events.jsonl"
    with locked_state(path):
        events = _load_job_events(events_path)
        if events:
            derived = _derive_job_state(events)
            if not path.is_file() or path.is_symlink():
                raise ValueError("derived job.json is missing or unsafe")
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored != derived:
                atomic_json(path, derived)
            return derived
        if not path.is_file() or path.is_symlink():
            raise ValueError("job.json is missing or unsafe")
        return json.loads(path.read_text(encoding="utf-8"))


def classify_inspection_state(
    *,
    workflow_manifest: dict[str, Any] | None,
    full_normal_count: int,
    full_error_count: int,
    analysis: dict[str, Any],
    qstate: str | None,
    process_alive: bool | None,
    pbs_evidence_status: str | None = None,
) -> tuple[str, int, bool, bool]:
    expected_stages = int(workflow_manifest.get("expected_stage_count", 3)) if workflow_manifest else 1
    workflow_complete = bool(
        workflow_manifest and full_normal_count >= expected_stages and full_error_count == 0
    )
    workflow_failed = bool(workflow_manifest and full_error_count > 0)
    if pbs_evidence_status is None:
        pbs_evidence_status = "present" if qstate is not None else "unknown"
    if pbs_evidence_status not in {"present", "absent", "unknown"}:
        raise ValueError("pbs_evidence_status must be present, absent, or unknown")
    # A single input can contain sequential work (for example, Opt followed by
    # Freq).  An earlier "Normal termination" does not make the overall job
    # terminal while PBS still has a live Gaussian session.
    if pbs_evidence_status == "unknown":
        state = "unknown"
    elif qstate == "R" and process_alive is True:
        state = "running"
    elif qstate == "Q":
        state = "queued"
    elif qstate == "H":
        state = "held"
    elif qstate == "E":
        state = "exiting"
    elif qstate == "R" and process_alive is None:
        state = "unknown"
    elif workflow_complete:
        state = "completed"
    elif workflow_failed:
        state = "failed"
    elif not workflow_manifest and (full_error_count > 0 or analysis["error_termination"]):
        state = "failed"
    elif not workflow_manifest and (full_normal_count >= 1 or analysis["normal_termination"]):
        state = "completed"
    elif qstate == "R" and process_alive is False:
        state = "stale"
    else:
        state = "unknown"
    return state, expected_stages, workflow_complete, workflow_failed


def terminal_log_proven(inspection: dict[str, Any]) -> bool:
    """Return True only when the log proves Gaussian reached a terminal outcome."""

    if inspection.get("termination_counts_known") is not True:
        return False
    expected = inspection.get("workflow_expected_stages")
    normal_count = int(inspection.get("full_normal_termination_count") or 0)
    error_count = int(inspection.get("full_error_termination_count") or 0)
    if error_count > 0:
        return True
    if expected is not None:
        return normal_count >= int(expected)
    analysis = inspection.get("analysis") or {}
    return bool(normal_count > 0 or error_count > 0 or analysis.get("normal_termination") or analysis.get("error_termination"))


def zombie_snapshot(inspection: dict[str, Any]) -> dict[str, Any]:
    """Keep only scheduler-safety evidence needed for zombie diagnosis."""

    pbs_record_present = inspection.get("pbs_record_present")
    pbs_evidence_status = inspection.get("pbs_evidence_status")
    if pbs_evidence_status not in {"present", "absent", "unknown"}:
        pbs_evidence_status = (
            "present" if pbs_record_present is True
            else "absent" if pbs_record_present is False
            else "unknown"
        )
    process_alive = inspection.get("process_alive")
    process_evidence_status = inspection.get("process_evidence_status")
    if process_evidence_status not in {"present", "absent", "unknown"}:
        process_evidence_status = (
            "present" if process_alive is True
            else "absent" if process_alive is False
            else "unknown"
        )
    return {
        "pbs_job_name": inspection.get("pbs_job_name"),
        "pbs_state": inspection.get("pbs_state"),
        "pbs_record_present": inspection.get("pbs_record_present"),
        "pbs_evidence_status": pbs_evidence_status,
        "session_id": inspection.get("session_id"),
        "process_alive": inspection.get("process_alive"),
        "process_evidence_status": process_evidence_status,
        "log_size": inspection.get("log_size"),
        "log_mtime_epoch": inspection.get("log_mtime_epoch"),
        "workflow_expected_stages": inspection.get("workflow_expected_stages"),
        "full_normal_termination_count": inspection.get("full_normal_termination_count"),
        "full_error_termination_count": inspection.get("full_error_termination_count"),
        "terminal_log_proven": terminal_log_proven(inspection),
    }


def assess_zombie_observations(
    project: str,
    job_id: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify repeated read-only observations without contacting PBS."""

    snapshots = [zombie_snapshot(value) for value in observations]
    base = {
        "schema": "pbs-zombie-diagnosis/1",
        "project": project,
        "job_id": job_id,
        "scope": "PBS scheduler record only; server project files are untouched",
    }
    if len(snapshots) < 2:
        return {
            **base,
            "classification": "insufficient_observations",
            "cleanup_eligible": False,
            "failed_checks": ["at least two observations are required"],
            "observations": snapshots,
        }
    if snapshots[-1]["pbs_evidence_status"] == "absent":
        return {
            **base,
            "classification": "self_purged",
            "cleanup_eligible": False,
            "failed_checks": [],
            "observations": snapshots,
        }

    checks = {
        "pbs_evidence_present": all(
            value["pbs_evidence_status"] == "present" for value in snapshots
        ),
        "exact_job_name": all(value["pbs_job_name"] == project for value in snapshots),
        "pbs_running_record": all(value["pbs_state"] == "R" for value in snapshots),
        "session_id_present": all(bool(value["session_id"]) for value in snapshots),
        "session_process_absent": all(
            value["process_evidence_status"] == "absent" and value["process_alive"] is False
            for value in snapshots
        ),
        "terminal_log_proven": all(value["terminal_log_proven"] for value in snapshots),
        "log_metadata_present": all(
            value["log_size"] is not None and value["log_mtime_epoch"] is not None
            for value in snapshots
        ),
        "log_stable": all(
            (value["log_size"], value["log_mtime_epoch"])
            == (snapshots[0]["log_size"], snapshots[0]["log_mtime_epoch"])
            for value in snapshots[1:]
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    confirmed = not failed_checks
    return {
        **base,
        "classification": "confirmed_scheduler_zombie" if confirmed else "not_confirmed_zombie",
        "cleanup_eligible": confirmed,
        "checks": checks,
        "failed_checks": failed_checks,
        "observations": snapshots,
    }


def validate_local_job_binding(
    local_dir: Path,
    project: str,
    job_id: str,
    input_stem: str,
    *,
    require_fetched: bool, expected_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Bind any local status/fetch mutation to the exact staged job bytes."""

    local_dir = checked_local_path(local_dir, "local job directory")
    try:
        job = read_job_state(local_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        fail(f"could not read local job audit record: {exc}")
    expected = {
        "project": project,
        "job_id": job_id,
        "remote_workdir": remote_project_dir(project),
    }
    for key, value in expected.items():
        if job.get(key) != value:
            fail(f"local job audit record {key} does not match the exact request")
    input_name = str(job.get("input", ""))
    if Path(input_name).stem != input_stem or Path(input_name).name != input_name:
        fail("local job audit record input stem does not match the exact request")
    input_digest = job.get("input_sha256")
    staged_input = local_dir / input_name
    if not isinstance(input_digest, str) or not SHA256_RE.fullmatch(input_digest):
        fail("local job audit record lacks an exact input hash")
    if staged_input.is_symlink() or not staged_input.is_file() or sha256(staged_input) != input_digest:
        fail("local staged input bytes do not match the job audit hash")
    if expected_attempt_id is not None:
        execution = job.get("execution_batch")
        if not isinstance(execution, dict) or execution.get("attempt_id") != expected_attempt_id:
            fail("local job audit attempt does not match the exact request")
    if require_fetched and job.get("results_fetched") is not True:
        fail("refusing scheduler cleanup before results_fetched is recorded true")
    return job


def validate_terminal_inspection_receipt(
    local_dir: Path, job: dict[str, Any], project: str, job_id: str, input_stem: str,
) -> dict[str, Any]:
    path = local_dir / "terminal-inspection.json"
    if path.is_symlink() or not path.is_file():
        fail("fetch requires an immutable exact terminal inspection receipt")
    receipt = load_strict_json(path)
    required = {
        "schema", "project", "job_id", "input_stem", "input_sha256", "attempt_id",
        "terminal_state", "collected_at", "inspection_evidence_sha256", "inspection",
        "scientific_acceptance", "receipt_sha256",
    }
    if set(receipt) != required or receipt.get("schema") != "gaussian-terminal-inspection-receipt/1":
        fail("terminal inspection receipt is open or malformed")
    execution = job.get("execution_batch") if isinstance(job.get("execution_batch"), dict) else {}
    expected = {
        "project": project, "job_id": job_id, "input_stem": input_stem,
        "input_sha256": job.get("input_sha256"), "attempt_id": execution.get("attempt_id"),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        fail("terminal inspection receipt differs from the exact local job binding")
    if receipt.get("scientific_acceptance") is not False:
        fail("terminal inspection receipt must not claim scientific acceptance")
    if receipt.get("receipt_sha256") != canonical_digest({key: value for key, value in receipt.items() if key != "receipt_sha256"}):
        fail("terminal inspection receipt hash mismatch")
    inspection = receipt.get("inspection")
    if not isinstance(inspection, dict) or inspection.get("evidence_sha256") != receipt.get("inspection_evidence_sha256"):
        fail("terminal inspection evidence binding is malformed")
    if inspection["evidence_sha256"] != canonical_digest({key: value for key, value in inspection.items() if key != "evidence_sha256"}):
        fail("terminal inspection evidence hash mismatch")
    if (
        inspection.get("project") != project or inspection.get("job_id") != job_id
        or inspection.get("freshness") != "fresh"
        or inspection.get("transport_classification") != "success"
        or inspection.get("termination_counts_known") is not True
        or inspection.get("state") != receipt.get("terminal_state")
    ):
        fail("terminal inspection was not fresh, successful, and exact when captured")
    if receipt["terminal_state"] in {"completed", "failed"}:
        if not terminal_log_proven(inspection):
            fail("terminal inspection lacks exact terminal log evidence")
    elif receipt["terminal_state"] == "interrupted":
        proof = inspection.get("interruption_proof")
        if not isinstance(proof, dict) or proof.get("stable_repeats", 0) < 2 or proof.get("stable_duration_seconds", 0) < MIN_INTERRUPTION_STABLE_SECONDS or proof.get("log_age_seconds", 0) < MIN_INTERRUPTION_STABLE_SECONDS or proof.get("full_normal_termination_count") != 0 or proof.get("full_error_termination_count") != 0 or any(proof.get(key) is not True for key in ("scheduler_record_absent", "log_signature_stable", "normal_termination_absent", "termination_counts_known")):
            fail("interrupted terminal receipt lacks repeated stable absence proof")
    else:
        fail("terminal inspection receipt is not terminal")
    return receipt


def publish_terminal_inspection_receipt(
    local_dir: Path, job: dict[str, Any], inspection: dict[str, Any], input_stem: str,
) -> dict[str, Any]:
    path = local_dir / "terminal-inspection.json"
    if path.exists() or path.is_symlink():
        return validate_terminal_inspection_receipt(local_dir, job, inspection["project"], inspection["job_id"], input_stem)
    if (
        inspection.get("freshness") != "fresh"
        or inspection.get("transport_classification") != "success"
        or inspection.get("termination_counts_known") is not True
        or inspection.get("evidence_sha256") != canonical_digest({key: value for key, value in inspection.items() if key != "evidence_sha256"})
    ):
        fail("refusing to publish stale, failed, or tampered terminal inspection evidence")
    if inspection.get("state") in {"completed", "failed"}:
        if not terminal_log_proven(inspection):
            fail("refusing terminal receipt without terminal log evidence")
    elif inspection.get("state") == "interrupted":
        proof = inspection.get("interruption_proof")
        if not isinstance(proof, dict) or proof.get("stable_repeats", 0) < 2 or proof.get("stable_duration_seconds", 0) < MIN_INTERRUPTION_STABLE_SECONDS or proof.get("log_age_seconds", 0) < MIN_INTERRUPTION_STABLE_SECONDS or proof.get("full_normal_termination_count") != 0 or proof.get("full_error_termination_count") != 0 or any(proof.get(key) is not True for key in ("scheduler_record_absent", "log_signature_stable", "normal_termination_absent", "termination_counts_known")):
            fail("refusing interrupted terminal receipt without repeated stable proof")
    else:
        fail("refusing terminal receipt for a non-terminal observation")
    execution = job.get("execution_batch") if isinstance(job.get("execution_batch"), dict) else {}
    receipt = {
        "schema": "gaussian-terminal-inspection-receipt/1",
        "project": inspection["project"], "job_id": inspection["job_id"],
        "input_stem": input_stem, "input_sha256": job["input_sha256"],
        "attempt_id": execution.get("attempt_id"), "terminal_state": inspection["state"],
        "collected_at": inspection["collected_at"],
        "inspection_evidence_sha256": inspection["evidence_sha256"],
        "inspection": copy.deepcopy(inspection), "scientific_acceptance": False,
    }
    receipt["receipt_sha256"] = canonical_digest(receipt)
    publish_new_json(path, receipt)
    return validate_terminal_inspection_receipt(local_dir, job, inspection["project"], inspection["job_id"], input_stem)


def _legacy_multi_call_inspect_job(args, project: str, input_stem: str, job_id: str) -> dict[str, Any]:
    """Combine PBS, process, and Gaussian-log evidence into one state."""

    project = validate_project(project)
    job_id = validate_job_id(job_id)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", input_stem):
        fail("invalid input stem")
    qstat = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
    qstat_evidence = classify_qstat_evidence(qstat)
    qstate = qstat_evidence["pbs_state"]
    pbs_job_name = qstat_evidence["job_name"]
    session_id = qstat_evidence["session_id"]
    process_alive: bool | None = None
    process_evidence = {
        "status": "unknown",
        "process_alive": None,
        "returncode": None,
        "error": "no parsed PBS session id was available",
    }
    if session_id:
        process = run(nested_ssh(args, "ps", "-s", session_id, "-o", "pid="), check=False)
        process_evidence = classify_process_evidence(process)
        process_alive = process_evidence["process_alive"]

    remote_dir = remote_project_dir(project)
    guard = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=remote_existing_directory_guard(project).encode("utf-8"),
        check=False,
    )
    if guard.returncode:
        fail(str(guard.stderr or guard.stdout).strip())
    log_path = f"{remote_dir}/{input_stem}.log"
    manifest_path = f"{remote_dir}/{input_stem}.json"
    manifest_result = run(nested_ssh(args, "cat", manifest_path), check=False)
    workflow_manifest = None
    if manifest_result.returncode == 0:
        try:
            manifest_value = json.loads(str(manifest_result.stdout))
        except json.JSONDecodeError:
            manifest_value = None
        if isinstance(manifest_value, dict) and manifest_value.get("schema") == "gaussian-opt-freq-sp/1":
            workflow_manifest = manifest_value
    if workflow_manifest is None and getattr(args, "local_dir", None):
        local_manifest = Path(args.local_dir).expanduser().resolve() / f"{input_stem}.json"
        if local_manifest.is_file():
            try:
                manifest_value = json.loads(local_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest_value = None
            if isinstance(manifest_value, dict) and manifest_value.get("schema") == "gaussian-opt-freq-sp/1":
                workflow_manifest = manifest_value
    tail = run(nested_ssh(args, "tail", "-n", "500", log_path), check=False)
    log_text = str(tail.stdout) if tail.returncode == 0 else ""
    stat = run(nested_ssh(args, "stat", "-c", "%s:%Y", log_path), check=False)
    size = None
    mtime = None
    stat_match = re.fullmatch(r"(\d+):(\d+)", str(stat.stdout).strip())
    if stat_match:
        size, mtime = map(int, stat_match.groups())
    analysis = analyze_log_text(log_text)
    count_script = f"""normal=$(grep -c 'Normal termination of Gaussian' '{log_path}' 2>/dev/null || true)
error=$(grep -c 'Error termination' '{log_path}' 2>/dev/null || true)
printf '%s:%s\\n' "$normal" "$error"
"""
    termination_counts = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=count_script.encode("utf-8"),
        check=False,
    )
    count_match = re.fullmatch(r"(\d+):(\d+)", str(termination_counts.stdout).strip())
    full_normal_count, full_error_count = map(int, count_match.groups()) if count_match else (0, 0)
    state, expected_stages, workflow_execution_complete, workflow_execution_failed = classify_inspection_state(
        workflow_manifest=workflow_manifest,
        full_normal_count=full_normal_count,
        full_error_count=full_error_count,
        analysis=analysis,
        qstate=qstate,
        process_alive=process_alive,
        pbs_evidence_status=qstat_evidence["status"],
    )
    scheduler_record_lingering = bool(
        qstat_evidence["status"] == "present"
        and qstate is not None
        and (workflow_execution_complete or (not workflow_manifest and analysis["normal_termination"]))
    )
    terminal_proven = bool(
        workflow_execution_complete
        or workflow_execution_failed
        or (not workflow_manifest and (analysis["normal_termination"] or analysis["error_termination"]))
    )
    zombie_candidate = bool(
        pbs_job_name == project
        and qstate == "R"
        and session_id is not None
        and process_alive is False
        and terminal_proven
    )
    incomplete_log_observed = bool(
        analysis.get("scf_calculations", 0) > 0
        or analysis.get("final_coordinate_count", 0) > 0
        or analysis.get("normal_termination_count", 0) + analysis.get("error_termination_count", 0) > 0
    )
    interrupted_candidate = bool(
        qstat_evidence["status"] == "absent"
        and incomplete_log_observed
        and not terminal_proven
        and size is not None
        and mtime is not None
    )

    inspection = {
        "schema": "gaussian-job-inspection/1",
        "project": project,
        "job_id": job_id,
        "state": state,
        "pbs_job_name": pbs_job_name,
        "pbs_state": qstate,
        "pbs_record_present": qstat_evidence["record_present"],
        "pbs_evidence_status": qstat_evidence["status"],
        "pbs_returncode": qstat_evidence["returncode"],
        "pbs_evidence_error": qstat_evidence["error"],
        "session_id": session_id,
        "process_alive": process_alive,
        "process_evidence_status": process_evidence["status"],
        "process_returncode": process_evidence["returncode"],
        "process_evidence_error": process_evidence["error"],
        "log": log_path,
        "log_size": size,
        "log_mtime_epoch": mtime,
        "workflow_expected_stages": expected_stages if workflow_manifest else None,
        "full_normal_termination_count": full_normal_count,
        "full_error_termination_count": full_error_count,
        "scheduler_record_lingering": scheduler_record_lingering,
        "scheduler_zombie_candidate": zombie_candidate,
        "interrupted_candidate": interrupted_candidate,
        "analysis": analysis,
    }
    if scheduler_record_lingering:
        inspection["note"] = (
            "Gaussian is terminal while a PBS record remains; use repeated diagnose-zombie evidence "
            "before one automatic scheduler-only cleanup"
        )
    return inspection


def server_job_snapshot_script(project: str, input_stem: str, job_id: str) -> str:
    """One read-only remote script for qstat/process/log/manifest evidence."""
    remote_dir = remote_project_dir(project)
    log_path = f"{remote_dir}/{input_stem}.log"
    manifest_path = f"{remote_dir}/{input_stem}.json"
    return remote_existing_directory_guard(project) + fr"""
qstat_out=$(qstat -f '{job_id}' 2>&1); qrc=$?
session=$(printf '%s\n' "$qstat_out" | sed -n 's/^[[:space:]]*session_id[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n 1)
qstate=$(printf '%s\n' "$qstat_out" | sed -n 's/^[[:space:]]*job_state[[:space:]]*=[[:space:]]*\([A-Z]\).*/\1/p' | head -n 1)
if [ -n "$session" ]; then process_out=$(ps -s "$session" -o pid= 2>&1); prc=$?; else process_out=''; prc=125; fi
if [ -f '{manifest_path}' ] && [ ! -L '{manifest_path}' ]; then manifest_out=$(cat -- '{manifest_path}'); mrc=$?; else manifest_out=''; mrc=1; fi
if [ -f '{log_path}' ] && [ ! -L '{log_path}' ]; then
  tail_out=$(tail -n 500 -- '{log_path}' 2>&1); trc=$?
  stat_value=$(stat -c '%s:%Y' -- '{log_path}' 2>/dev/null || true)
  if [ "$qstate" = Q ] || {{ [ "$qstate" = R ] && [ "$prc" -eq 0 ] && [ -n "$process_out" ]; }}; then
    normal_count=''; error_count=''; scan_scope='bounded_tail_only'
  else
    counts=$(awk '/Normal termination of Gaussian/{{n++}} /Error termination/{{e++}} END{{printf "%d:%d", n+0, e+0}}' -- '{log_path}' 2>/dev/null || true)
    normal_count=${{counts%%:*}}; error_count=${{counts#*:}}; scan_scope='exact_whole_log_once'
  fi
else tail_out=''; trc=1; stat_value=''; normal_count=''; error_count=''; fi
printf 'COLLECTED_EPOCH\t%s\n' "$(date +%s)"
printf 'QSTAT_RC\t%s\nQSTAT_B64\t' "$qrc"; printf '%s' "$qstat_out" | base64 -w0; printf '\n'
printf 'PROCESS_RC\t%s\nPROCESS_B64\t' "$prc"; printf '%s' "$process_out" | base64 -w0; printf '\n'
printf 'MANIFEST_RC\t%s\nMANIFEST_B64\t' "$mrc"; printf '%s' "$manifest_out" | base64 -w0; printf '\n'
printf 'TAIL_RC\t%s\nTAIL_B64\t' "$trc"; printf '%s' "$tail_out" | base64 -w0; printf '\n'
printf 'LOG_STAT\t%s\nNORMAL_COUNT\t%s\nERROR_COUNT\t%s\nSCAN_SCOPE\t%s\n' "$stat_value" "$normal_count" "$error_count" "${{scan_scope:-no_log}}"
"""


def parse_job_snapshot_output(text: str) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "\t" not in line:
            if line.strip():
                raise ValueError("remote snapshot contains an unframed line")
            continue
        key, value = line.split("\t", 1)
        if key in values:
            raise ValueError("remote snapshot repeats a field")
        values[key] = value
    required = {
        "COLLECTED_EPOCH", "QSTAT_RC", "QSTAT_B64", "PROCESS_RC", "PROCESS_B64",
        "MANIFEST_RC", "MANIFEST_B64", "TAIL_RC", "TAIL_B64", "LOG_STAT",
        "NORMAL_COUNT", "ERROR_COUNT",
    }
    if set(values) not in {frozenset(required), frozenset(required | {"SCAN_SCOPE"})}:
        raise ValueError("remote snapshot fields are missing or unknown")

    def integer(key: str) -> int:
        if re.fullmatch(r"-?\d+", values[key]) is None:
            raise ValueError(f"remote snapshot {key} is not an integer")
        return int(values[key])

    def decoded(key: str) -> str:
        try:
            return base64.b64decode(values[key], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"remote snapshot {key} is invalid base64/UTF-8") from exc

    return {
        "collected_epoch": integer("COLLECTED_EPOCH"),
        "qstat": subprocess.CompletedProcess([], integer("QSTAT_RC"), decoded("QSTAT_B64"), ""),
        "process": subprocess.CompletedProcess([], integer("PROCESS_RC"), decoded("PROCESS_B64"), ""),
        "manifest_rc": integer("MANIFEST_RC"), "manifest_text": decoded("MANIFEST_B64"),
        "tail_rc": integer("TAIL_RC"), "tail_text": decoded("TAIL_B64"),
        "log_stat": values["LOG_STAT"], "normal_count": values["NORMAL_COUNT"],
        "error_count": values["ERROR_COUNT"],
        "scan_scope": values.get("SCAN_SCOPE", "exact_whole_log_once"),
    }


def inspect_job(args, project: str, input_stem: str, job_id: str) -> dict[str, Any]:
    """Collect one structured read-only remote snapshot for one exact job."""
    project = validate_project(project); job_id = validate_job_id(job_id)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", input_stem): fail("invalid input stem")
    collected_at = utc_now(); local_request_epoch = time.time()
    command = nested_ssh(args, "bash", "-s")
    snapshot_bytes = server_job_snapshot_script(project, input_stem, job_id).encode("utf-8")
    result = run_read_only(
        command, input_bytes=snapshot_bytes,
        capability=_exact_read_only_capability("single_job_inspection", command, snapshot_bytes),
    )
    local_received_epoch = time.time()
    if result.returncode != 0:
        return {
            "schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id,
            "state": "unknown", "collected_at": collected_at, "source": "single_remote_read_only_snapshot",
            "local_request_epoch": local_request_epoch, "local_received_epoch": local_received_epoch, "remote_collected_epoch": None,
            "freshness": "unknown", "age_seconds": 0, "transport_classification": "timeout" if result.returncode == 124 else "transport_error",
            "transport_returncode": result.returncode, "pbs_state": None, "log_size": None,
            "log_mtime_epoch": None, "session_id": None, "termination_counts_known": False,
            "evidence_conflict": False,
            "error": command_detail(result) or "snapshot transport failed or timed out",
        }
    try:
        snapshot = parse_job_snapshot_output(str(result.stdout))
    except ValueError as exc:
        return {
            "schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id,
            "state": "unknown", "collected_at": collected_at, "source": "single_remote_read_only_snapshot",
            "local_request_epoch": local_request_epoch, "local_received_epoch": local_received_epoch, "remote_collected_epoch": None,
            "freshness": "unknown", "age_seconds": 0, "transport_classification": "parse_failed",
            "transport_returncode": result.returncode, "pbs_state": None, "log_size": None,
            "log_mtime_epoch": None, "session_id": None, "termination_counts_known": False,
            "evidence_conflict": False, "error": str(exc),
        }
    remote_epoch = snapshot["collected_epoch"]
    if remote_epoch <= 0 or remote_epoch > local_received_epoch + MAX_REMOTE_CLOCK_SKEW_SECONDS:
        inspection = {
            "schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id,
            "state": "unknown", "collected_at": collected_at, "source": "single_remote_read_only_snapshot",
            "local_request_epoch": local_request_epoch, "local_received_epoch": local_received_epoch,
            "remote_collected_epoch": remote_epoch, "freshness": "unknown", "age_seconds": 0,
            "transport_classification": "parse_failed", "transport_returncode": result.returncode,
            "pbs_state": None, "log_size": None, "log_mtime_epoch": None, "session_id": None,
            "termination_counts_known": False, "evidence_conflict": True,
            "error": "remote collection clock is invalid or beyond allowed skew",
        }
        inspection["evidence_sha256"] = canonical_digest(inspection); return inspection
    qstat_evidence = classify_qstat_evidence(snapshot["qstat"])
    process_evidence = classify_process_evidence(snapshot["process"])
    workflow_manifest = None
    if snapshot["manifest_rc"] == 0:
        try: manifest_value = json.loads(snapshot["manifest_text"])
        except json.JSONDecodeError: manifest_value = None
        if isinstance(manifest_value, dict) and manifest_value.get("schema") == "gaussian-opt-freq-sp/1": workflow_manifest = manifest_value
    analysis = analyze_log_text(snapshot["tail_text"] if snapshot["tail_rc"] == 0 else "")
    stat_match = re.fullmatch(r"(\d+):(\d+)", snapshot["log_stat"])
    size, mtime = (map(int, stat_match.groups()) if stat_match else (None, None))
    scan_scope = snapshot["scan_scope"]
    if scan_scope not in {"bounded_tail_only", "exact_whole_log_once", "no_log"}:
        scan_scope = "invalid"
    counts_known = bool(
        scan_scope == "exact_whole_log_once"
        and
        re.fullmatch(r"\d+", snapshot["normal_count"])
        and re.fullmatch(r"\d+", snapshot["error_count"])
    )
    normal_count = int(snapshot["normal_count"]) if counts_known else None
    error_count = int(snapshot["error_count"]) if counts_known else None
    conflict = bool(qstat_evidence["status"] == "present" and qstat_evidence["job_name"] != project)
    state, expected_stages, workflow_complete, workflow_failed = classify_inspection_state(
        workflow_manifest=workflow_manifest, full_normal_count=normal_count or 0,
        full_error_count=error_count or 0, analysis=analysis, qstate=qstat_evidence["pbs_state"],
        process_alive=process_evidence["process_alive"], pbs_evidence_status=qstat_evidence["status"],
    )
    malformed_full_scan = scan_scope in {"exact_whole_log_once", "invalid"} and not counts_known
    if conflict or malformed_full_scan: state = "unknown"
    age_seconds = max(0, int(local_received_epoch - remote_epoch))
    freshness = "unknown" if malformed_full_scan else ("fresh" if age_seconds <= 120 else "stale")
    if freshness != "fresh": state = "unknown"
    inspection = {
        "schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id,
        "state": state, "collected_at": collected_at, "source": "single_remote_read_only_snapshot",
        "local_request_epoch": local_request_epoch, "local_received_epoch": local_received_epoch,
        "remote_collected_epoch": remote_epoch,
        "freshness": freshness, "age_seconds": age_seconds,
        "transport_classification": "parse_failed" if malformed_full_scan else "success",
        "transport_returncode": result.returncode, "pbs_job_name": qstat_evidence["job_name"],
        "pbs_state": qstat_evidence["pbs_state"], "pbs_record_present": qstat_evidence["record_present"],
        "pbs_evidence_status": qstat_evidence["status"], "process_alive": process_evidence["process_alive"],
        "session_id": qstat_evidence["session_id"],
        "process_evidence_status": process_evidence["status"], "log_size": size,
        "log_mtime_epoch": mtime, "workflow_expected_stages": expected_stages if workflow_manifest else None,
        "full_normal_termination_count": normal_count, "full_error_termination_count": error_count,
        "termination_counts_known": counts_known, "termination_scan_scope": scan_scope,
        "interruption_proof": None,
        "evidence_conflict": conflict or malformed_full_scan, "analysis": analysis,
    }
    if malformed_full_scan:
        inspection["error"] = "whole-log termination counts are malformed or unavailable"
    terminal_proven = terminal_log_proven(inspection)
    inspection.update({
        "scheduler_record_lingering": bool(
            qstat_evidence["status"] == "present" and terminal_proven
        ),
        "scheduler_zombie_candidate": bool(
            qstat_evidence["job_name"] == project
            and qstat_evidence["pbs_state"] == "R"
            and process_evidence["process_alive"] is False
            and terminal_proven
        ),
        "interrupted_candidate": bool(
            counts_known
            and qstat_evidence["status"] == "absent"
            and size is not None
            and not terminal_proven
        ),
    })
    inspection["evidence_sha256"] = canonical_digest(inspection)
    return inspection


def load_fetch_allowlist(
    local_dir: Path,
    job: dict[str, Any],
    input_stem: str,
) -> tuple[list[str], list[str], dict[str, str]]:
    """Build the exact server allowlist from the staged local audit bundle."""

    checksums_name = validate_transfer_name(str(job.get("checksums", "")))
    checksums_path = local_dir / checksums_name
    if not checksums_path.is_file() or checksums_path.is_symlink():
        fail("local staged checksums file is missing or is a symlink")
    expected_hashes: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})\s{2}([^/\\]+)", line)
        if not match:
            fail("local staged checksums file contains a malformed entry")
        digest, name = match.groups()
        name = validate_transfer_name(name)
        if name in expected_hashes:
            fail(f"local staged checksums file repeats {name}")
        expected_hashes[name] = digest
    expected_hashes[checksums_name] = sha256(checksums_path)
    input_name = validate_transfer_name(str(job.get("input", "")))
    if input_name not in expected_hashes:
        fail("local staged checksums do not bind the exact Gaussian input")
    if expected_hashes[input_name] != job.get("input_sha256"):
        fail("local staged input hash does not match job.json")
    local_input = local_dir / input_name
    if not local_input.is_file() or local_input.is_symlink():
        fail("local staged Gaussian input is missing or is a symlink")
    if sha256(local_input) != job.get("input_sha256"):
        fail("local staged Gaussian input bytes no longer match job.json")
    required = sorted({*expected_hashes, validate_transfer_name(f"{input_stem}.log")})
    optional = {validate_transfer_name(f"{job['project']}.pbs.out")}
    checkpoint = (job.get("gaussian") or {}).get("checkpoint")
    if checkpoint:
        optional.add(validate_transfer_name(str(checkpoint)))
    optional.difference_update(required)
    return required, sorted(optional), expected_hashes


def server_fetch_inventory_script(
    project: str,
    required: list[str],
    optional: list[str],
) -> str:
    """Return a read-only exact-file inventory; no glob or scratch traversal."""

    lines = [remote_existing_directory_guard(project), f"cd '{remote_project_dir(project)}'"]
    for status, names in (("REQUIRED", required), ("OPTIONAL", optional)):
        for name in names:
            validate_transfer_name(name)
            lines.append(
                f"if [ -L '{name}' ]; then echo 'REFUSING_SYMLINK\t{name}' >&2; exit 51; "
                f"elif [ -f '{name}' ]; then digest=$(sha256sum -- '{name}'); digest=${{digest%% *}}; "
                f"size=$(stat -c %s -- '{name}'); printf 'FILE\\t{name}\\t%s\\t%s\\n' \"$digest\" \"$size\"; "
                f"else printf 'MISSING_{status}\\t{name}\\n'; fi"
            )
    return "\n".join(lines) + "\n"


def parse_server_fetch_inventory(
    text: str,
    required: list[str],
    optional: list[str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    allowed = set(required) | set(optional)
    files: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []
    missing_optional: list[str] = []
    reported: set[str] = set()
    for line in text.splitlines():
        fields = line.split("\t")
        if fields[0] == "FILE" and len(fields) == 4:
            _, name, digest, size_text = fields
            if name not in allowed or name in reported or not SHA256_RE.fullmatch(digest):
                fail("server fetch inventory contains an unexpected or duplicate file")
            try:
                size = int(size_text)
            except ValueError:
                fail("server fetch inventory contains an invalid file size")
            if size < 0:
                fail("server fetch inventory contains a negative file size")
            files[name] = {"sha256": digest, "size": size}
            reported.add(name)
        elif fields[0] in {"MISSING_REQUIRED", "MISSING_OPTIONAL"} and len(fields) == 2:
            name = fields[1]
            if name not in allowed or name in reported:
                fail("server fetch inventory reports an unexpected missing file")
            (missing_required if fields[0] == "MISSING_REQUIRED" else missing_optional).append(name)
            reported.add(name)
        elif line.strip():
            fail("server fetch inventory could not be parsed exactly")
    unreported = allowed - set(files) - set(missing_required) - set(missing_optional)
    if unreported:
        fail("server fetch inventory omitted allowlisted entries: " + ", ".join(sorted(unreported)))
    if missing_required:
        fail("server fetch is missing required files: " + ", ".join(sorted(missing_required)))
    return files, sorted(missing_optional)


def begin_fetch_snapshot(output_dir: Path, binding: dict[str, str]) -> Path:
    """Reserve one empty local snapshot; partial snapshots remain visibly blocked."""

    output_dir = checked_local_path(output_dir, "fetch output directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir = checked_local_path(output_dir, "fetch output directory")
    if output_dir.exists():
        if not output_dir.is_dir():
            fail("fetch output path already exists and is not a directory")
        if any(output_dir.iterdir()):
            fail("refusing to mix fetch results with a non-empty or partial target")
    else:
        output_dir.mkdir()
    output_dir = checked_local_path(output_dir, "fetch output directory")
    marker = output_dir / ".fetch-in-progress"
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except FileExistsError:
        fail("another or partial fetch already owns this snapshot target")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"schema": "gaussian-fetch-in-progress/1", **binding}, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return marker


def reusable_snapshot_files(
    reuse_value: str | None, binding: dict[str, str], server_files: dict[str, dict[str, Any]],
) -> dict[str, Path]:
    """Return only old immutable files whose local bytes re-hash to the new remote manifest."""
    if not reuse_value:
        return {}
    candidate = checked_local_path(Path(reuse_value), "reuse snapshot")
    transfer_path = candidate / "transfer.json" if candidate.is_dir() else candidate
    if transfer_path.name != "transfer.json" or transfer_path.is_symlink() or not transfer_path.is_file():
        fail("--reuse-snapshot must name an immutable transfer.json or its snapshot directory")
    transfer = load_strict_json(transfer_path)
    if (
        transfer.get("schema") != "gaussian-fetch-snapshot/1"
        or transfer.get("snapshot_complete") is not True
        or transfer.get("payload_sha256") != canonical_digest({key: value for key, value in transfer.items() if key != "payload_sha256"})
        or not isinstance(transfer.get("terminal_inspection_receipt_sha256"), str)
        or not isinstance(transfer.get("artifacts"), dict)
        or any(transfer.get(key) != binding[key] for key in ("project", "job_id", "input_stem"))
        or not isinstance(transfer.get("per_hop"), dict)
    ):
        fail("reuse snapshot is incomplete or bound to a different exact job")
    reusable: dict[str, Path] = {}
    for name, remote in server_files.items():
        old = transfer["per_hop"].get(name)
        artifact = transfer["artifacts"].get(name)
        path = transfer_path.parent / name
        if not isinstance(old, dict) or not isinstance(artifact, dict) or path.is_symlink() or not path.is_file():
            continue
        if (
            old.get("server_sha256") == remote["sha256"]
            and old.get("mac_sha256") == remote["sha256"]
            and old.get("size") == remote["size"]
            and artifact == {"sha256": remote["sha256"], "size": remote["size"]}
            and path.stat().st_size == remote["size"]
            and sha256(path) == remote["sha256"]
        ):
            reusable[name] = path
    return reusable


def atomic_private_reuse_copy(source: Path, destination: Path, expected: dict[str, Any]) -> None:
    """Publish a private no-clobber copy; never share an inode with the old snapshot."""
    try:
        atomic_stable_file_copy(source, destination, "reusable immutable snapshot file", expected=expected, mode=0o400)
    except (OSError, ValueError) as exc:
        fail(str(exc))


def fetch_results(args, project: str, output_dir: Path) -> dict[str, Any]:
    """Create one exact, hash-verified, immutable fetch snapshot."""

    project = validate_project(project)
    job_id = validate_job_id(str(getattr(args, "job_id", "")))
    input_stem = str(getattr(args, "input_stem", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", input_stem):
        fail("fetch requires a valid exact --input-stem")
    local_dir_value = getattr(args, "local_dir", None)
    if not local_dir_value:
        fail("fetch requires --local-dir with the exact job.json audit bundle")
    local_dir = checked_local_path(Path(local_dir_value), "fetch local job directory")
    job = validate_local_job_binding(
        local_dir, project, job_id, input_stem, require_fetched=False
    )
    terminal_receipt = validate_terminal_inspection_receipt(local_dir, job, project, job_id, input_stem)
    required, optional, expected_hashes = load_fetch_allowlist(local_dir, job, input_stem)
    snapshot_id = hashlib.sha256(
        f"{project}\0{job_id}\0{input_stem}\0{time.time_ns()}\0{os.getpid()}".encode("utf-8")
    ).hexdigest()[:16]
    binding = {
        "project": project,
        "job_id": job_id,
        "input_stem": input_stem,
        "snapshot_id": snapshot_id,
    }
    marker = begin_fetch_snapshot(output_dir, binding)
    output_dir = marker.parent

    inventory_result = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=server_fetch_inventory_script(project, required, optional).encode("utf-8"),
    )
    server_files, missing_optional = parse_server_fetch_inventory(
        str(inventory_result.stdout), required, optional
    )
    staged_mismatches = [
        name for name, digest in expected_hashes.items()
        if server_files.get(name, {}).get("sha256") != digest
    ]
    if staged_mismatches:
        fail("server staged-file SHA-256 mismatch: " + ", ".join(staged_mismatches))

    reusable = reusable_snapshot_files(
        getattr(args, "reuse_snapshot", None), binding, server_files
    )
    changed_names = sorted(set(server_files) - set(reusable))
    changed_size_bytes = sum(server_files[name]["size"] for name in changed_names)
    fetch_transfer_timeout = transfer_timeout_seconds(changed_size_bytes)

    snapshot_tag = f"fetch-{project}-{job_id}-{input_stem}-{snapshot_id}"
    windows_results = f"{args.windows_root}\\{project}\\{snapshot_tag}"
    escaped_windows_results = windows_results.replace("'", "''")
    mkdir_script = (
        f"if (Test-Path -LiteralPath '{escaped_windows_results}') "
        "{ throw 'REFUSING_EXISTING_FETCH_SNAPSHOT' }; "
        f"New-Item -ItemType Directory -Path '{escaped_windows_results}' | Out-Null"
    )
    present_names = sorted(server_files)
    if changed_names:
        run([
            *ssh_base(args), "powershell", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", powershell_encoded(mkdir_script),
        ])
        remote_sources = [
            f"{args.server_alias}:{remote_project_dir(project)}/{name}" for name in changed_names
        ]
        run([
            *ssh_base(args), "scp", "-F", args.windows_server_config,
            *remote_sources, windows_results + "\\",
        ], timeout_seconds=fetch_transfer_timeout)
    ps_paths = ",".join(
        "'" + f"{windows_results}\\{name}".replace("'", "''") + "'"
        for name in changed_names
    )
    hash_script = (
        f"$files=@({ps_paths}); foreach($f in $files){{"
        "$h=(Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower();"
        "$s=(Get-Item -LiteralPath $f).Length;"
        "Write-Output ((Split-Path $f -Leaf)+\"`t\"+$h+\"`t\"+$s)}"
    )
    rtwin_hashes: dict[str, dict[str, Any]] = {
        name: copy.deepcopy(server_files[name]) for name in reusable
    }
    if changed_names:
        rtwin_hash_result = run([
            *ssh_base(args), "powershell", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", powershell_encoded(hash_script),
        ])
        for line in str(rtwin_hash_result.stdout).splitlines():
            fields = line.strip().split("\t")
            if len(fields) != 3 or fields[0] not in changed_names or not SHA256_RE.fullmatch(fields[1]):
                fail("RTwin fetch hash inventory could not be parsed exactly")
            if fields[0] in rtwin_hashes:
                fail("RTwin fetch hash inventory repeats a file")
            try:
                size = int(fields[2])
            except ValueError:
                fail("RTwin fetch hash inventory contains an invalid size")
            rtwin_hashes[fields[0]] = {"sha256": fields[1], "size": size}
    if rtwin_hashes != server_files:
        fail("server to RTwin fetch verification failed")

    windows_results_scp = windows_results.replace("\\", "/")
    for name, old_path in reusable.items():
        destination = output_dir / name
        atomic_private_reuse_copy(old_path, destination, server_files[name])
    if changed_names:
        local_network_stage = Path(tempfile.mkdtemp(prefix=f".fetch-network-{snapshot_id}-", dir=output_dir.parent))
        rtwin_sources = [f"{args.rtwin_alias}:{windows_results_scp}/{name}" for name in changed_names]
        run([
            "scp", "-F", str(Path(args.mac_ssh_config).expanduser()),
            *rtwin_sources, str(local_network_stage) + "/",
        ], timeout_seconds=fetch_transfer_timeout)
        for name in changed_names:
            staged = local_network_stage / name
            if staged.is_symlink() or not staged.is_file() or sha256(staged) != server_files[name]["sha256"] or staged.stat().st_size != server_files[name]["size"]:
                fail("private network staging failed exact hash/size verification")
            atomic_private_reuse_copy(staged, output_dir / name, server_files[name])
        for name in changed_names:
            with contextlib.suppress(FileNotFoundError): (local_network_stage / name).unlink()
        with contextlib.suppress(OSError): local_network_stage.rmdir()
    actual_entries = {path.name for path in output_dir.iterdir() if path.name != marker.name}
    if actual_entries != set(present_names):
        fail("Mac fetch snapshot contains missing, extra, nested, or partial transfer entries")
    mac_hashes: dict[str, dict[str, Any]] = {}
    for name in present_names:
        path = output_dir / name
        if not path.is_file() or path.is_symlink():
            fail(f"Mac fetch snapshot entry is not one regular file: {name}")
        mac_hashes[name] = {"sha256": sha256(path), "size": path.stat().st_size}
    if mac_hashes != server_files:
        fail("RTwin to Mac fetch verification failed")

    exact_log = output_dir / f"{input_stem}.log"
    workflow_manifest = None
    exact_manifest = output_dir / f"{input_stem}.json"
    if exact_manifest.name in present_names:
        try:
            manifest_value = json.loads(exact_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest_value = None
        if isinstance(manifest_value, dict) and manifest_value.get("schema") == "gaussian-opt-freq-sp/1":
            workflow_manifest = manifest_value
    if workflow_manifest:
        analysis = analyze_workflow_log_file(
            exact_log, output_dir,
            temperature_k=float(workflow_manifest["temperature_k"]),
            standard_state=str(workflow_manifest["standard_state"]),
            expected_stages=int(workflow_manifest.get("expected_stage_count", 3)),
        )
        analysis["species_id"] = workflow_manifest.get("species_id")
        analysis["chemical_identity"] = workflow_manifest.get("chemical_identity")
        analysis["workflow_protocol"] = {
            "stages": workflow_manifest.get("stages"),
            "temperature_k": workflow_manifest.get("temperature_k"),
            "standard_state": workflow_manifest.get("standard_state"),
        }
        atomic_json(output_dir / "result.json", analysis)
    else:
        analysis = analyze_log_file(exact_log, output_dir)

    per_hop = {
        name: {
            "server_sha256": server_files[name]["sha256"],
            "rtwin_sha256": rtwin_hashes[name]["sha256"],
            "mac_sha256": mac_hashes[name]["sha256"],
            "size": mac_hashes[name]["size"],
        }
        for name in present_names
    }
    allowlist_record = {
        "schema": "gaussian-server-fetch-allowlist/1",
        **binding,
        "remote_workdir": remote_project_dir(project),
        "required": required,
        "optional": optional,
        "missing_optional": missing_optional,
        "present": present_names,
        "scratch_included": False,
        "unrelated_files_included": False,
    }
    publish_new_json(output_dir / "server-allowlist.json", allowlist_record)
    atomic_text(
        output_dir / "fetch.sha256",
        "".join(f"{mac_hashes[name]['sha256']}  {name}\n" for name in present_names),
    )
    files = sorted(
        path.name for path in output_dir.iterdir()
        if path.is_file() and path.name != marker.name
    )
    transfer = {
        "schema": "gaussian-fetch-snapshot/1",
        **binding,
        "input_sha256": job["input_sha256"],
        "terminal_inspection_receipt_sha256": terminal_receipt["receipt_sha256"],
        "output_dir": str(output_dir),
        "snapshot_complete": True,
        "files": files,
        "exact_log": exact_log.name,
        "server_allowlist": "server-allowlist.json",
        "sha256_manifest": "fetch.sha256",
        "per_hop_sha256_verified": True,
        "incremental_reuse": {
            "source_snapshot": str(getattr(args, "reuse_snapshot", None)) if reusable else None,
            "reused_files": sorted(reusable), "transferred_files": changed_names,
            "complete_independent_snapshot": True,
        },
        "transfer_timeout_evidence": {
            "known_changed_size_bytes": changed_size_bytes,
            "server_to_rtwin_timeout_seconds": fetch_transfer_timeout,
            "rtwin_to_mac_timeout_seconds": fetch_transfer_timeout,
            "rate_floor_bytes_per_second": TRANSFER_RATE_FLOOR_BYTES_PER_SECOND,
            "fixed_overhead_seconds": TRANSFER_FIXED_OVERHEAD_SECONDS,
        },
        "per_hop": per_hop,
        "analysis": analysis,
        "artifacts": {
            path.name: {"sha256": sha256(path), "size": path.stat().st_size}
            for path in output_dir.iterdir()
            if path.is_file() and path.name not in {marker.name, "transfer.json"}
        },
        "payload_sha256": "",
    }
    transfer["payload_sha256"] = canonical_digest({key: value for key, value in transfer.items() if key != "payload_sha256"})
    publish_new_json(output_dir / "transfer.json", transfer)
    marker.unlink()
    return transfer


def command_finalize_input_review(args) -> None:
    try:
        document = finalize_input_review(Path(args.draft), Path(args.output))
    except (OSError, ValueError, protocol_selection.ContractError) as exc:
        fail(f"input-review finalization failed: {exc}")
    print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}, ensure_ascii=False, indent=2))


def command_build_input_approval(args) -> None:
    try:
        document = build_input_approval_receipt(
            Path(args.protocol_options), Path(args.protocol_selection), Path(args.input_review),
            Path(args.input), Path(args.output), args.receipt_id,
            Path(args.open_shell_state_review) if args.open_shell_state_review else None,
            Path(args.open_shell_input_handoff) if args.open_shell_input_handoff else None,
            Path(args.open_shell_input_audit) if args.open_shell_input_audit else None,
        )
    except (OSError, ValueError, protocol_selection.ContractError) as exc:
        fail(f"input-approval build failed: {exc}")
    print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}, ensure_ascii=False, indent=2))


def command_validate_input_approval(args) -> None:
    try:
        receipt_path = Path(args.receipt).expanduser()
        loaded = load_strict_json(receipt_path)
        if loaded.get("schema") == OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA:
            _load_open_shell_minimum_family_owner().validate_stage_receipt(loaded)
            document = loaded
        else:
            document = validate_input_approval_receipt(receipt_path)
    except (OSError, ValueError, protocol_selection.ContractError) as exc:
        fail(f"input-approval validation failed: {exc}")
    print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}, ensure_ascii=False, indent=2))


def command_preflight(args) -> None:
    project = validate_project(args.project)
    report = parse_gaussian(Path(args.input).expanduser().resolve())
    maturity = audit_scientific_maturity(args, report, "ts_input")
    report["project"] = project
    report["remote_workdir"] = remote_project_dir(project)
    if maturity is not None:
        report = {"scientific_maturity": maturity, **report}
    print(json.dumps(report, ensure_ascii=False, indent=2))


def command_stage(args) -> None:
    project = validate_project(args.project)
    job, files = stage(
        Path(args.input).expanduser().resolve(), project,
        Path(args.local_dir).expanduser().resolve(),
    )
    print(json.dumps({"job": job, "files": [str(path) for path in files]}, ensure_ascii=False, indent=2))


def validate_execution_ledger_path(path: Path) -> dict[str, Any]:
    raw = execution_batch.load_json(path)
    if raw.get("schema") == resource_efficiency.LEDGER_SCHEMA:
        return resource_efficiency.validate_ledger(raw)
    return execution_batch.validate_submission_ledger(raw)


def reconcile_execution_attempt(path: Path, attempt_id: str, **kwargs: Any) -> dict[str, Any]:
    raw = execution_batch.load_json(path)
    if raw.get("schema") == resource_efficiency.LEDGER_SCHEMA:
        return resource_efficiency.reconcile_attempt(path, attempt_id, **kwargs)
    return execution_batch.reconcile_submission_attempt(path, attempt_id, **kwargs)


def replay_resource_artifacts_before_qsub(
    *, policy_path: Path, gate_path: Path, scheduler_path: Path,
    expected_policy: dict[str, Any], expected_gate: dict[str, Any],
    expected_scheduler: dict[str, Any],
    expected_bindings: dict[str, tuple[str, int]], now: str,
) -> None:
    """Replay exact immutable resource artifacts and freshness immediately before qsub."""
    replay_policy, policy_sha, policy_size = resource_efficiency.load_artifact(policy_path)
    replay_gate, gate_sha, gate_size = resource_efficiency.load_artifact(gate_path)
    replay_scheduler, scheduler_sha, scheduler_size = resource_efficiency.load_artifact(scheduler_path)
    resource_efficiency.validate_policy(replay_policy)
    resource_efficiency._validate_gate_binding(replay_gate, allow_historical=False)
    resource_efficiency.validate_scheduler_snapshot(replay_scheduler, now=now)
    if (
        replay_policy != expected_policy or (policy_sha, policy_size) != expected_bindings["policy"]
        or replay_gate != expected_gate or (gate_sha, gate_size) != expected_bindings["gate"]
        or replay_scheduler != expected_scheduler
        or (scheduler_sha, scheduler_size) != expected_bindings["scheduler"]
    ):
        raise resource_efficiency.ResourceError("resource artifact drifted after reservation")


def command_submit(args) -> None:
    if not args.confirmed:
        fail("submit requires --confirmed after the exact preflight is approved")
    project = validate_project(args.project)
    local_dir = Path(args.local_dir).expanduser().resolve()
    try:
        input_path, captured_input_sha256 = capture_submission_snapshot(
            Path(args.input), local_dir
        )
    except ValueError as exc:
        fail(f"could not capture immutable submission snapshot: {exc}")
    input_report = parse_gaussian(input_path)
    if input_report["input_sha256"] != captured_input_sha256:
        fail("submission snapshot hash changed before approval replay")
    requested_work_kind = args.work_kind
    if not args.dry_run and requested_work_kind is None:
        fail("live submission requires an explicit --work-kind; it must not default to ordinary")
    args._prospective_live = not args.dry_run
    maturity = audit_scientific_maturity(args, input_report, "ts_submission")
    compatibility = input_approval_compatibility(input_report, requested_work_kind)
    execution_binding: dict[str, Any] | None = None
    execution_ledger_path: Path | None = None
    execution_task: dict[str, Any] | None = None
    execution_ledger: dict[str, Any] | None = None
    resource_policy: dict[str, Any] | None = None
    resource_gate: dict[str, Any] | None = None
    scheduler_resource_snapshot: dict[str, Any] | None = None
    resource_artifact_bindings: dict[str, tuple[str, int]] = {}
    execution_values = (
        args.execution_batch_ledger,
        args.scientific_task_id,
        args.idempotency_key,
        args.estimated_core_hours,
        args.estimated_core_hours_evidence_source,
        args.estimated_core_hours_evidence_sha256,
        args.resource_policy,
        args.resource_gate,
        args.scheduler_resource_snapshot,
        args.resource_tier,
        args.resource_cores,
        args.resource_memory_gb,
        args.walltime_seconds,
    )
    if not args.dry_run and any(value is None for value in execution_values):
        fail(
            "protected live submit requires --execution-batch-ledger, --scientific-task-id, "
            "--idempotency-key, --estimated-core-hours, and its evidence source/hash"
            "; package 4 also requires --resource-policy, --resource-gate, exact tier/cores/memory, "
                "an exact --scheduler-resource-snapshot, and explicitly reviewed --walltime-seconds"
        )
    if all(value is not None for value in execution_values):
        execution_ledger_path = Path(args.execution_batch_ledger).expanduser().resolve()
        try:
            execution_ledger = resource_efficiency.validate_ledger(
                resource_efficiency.load(execution_ledger_path)
            )
            policy_raw, policy_file_sha, policy_size = resource_efficiency.load_artifact(Path(args.resource_policy).expanduser().resolve())
            gate_raw, gate_file_sha, gate_size = resource_efficiency.load_artifact(Path(args.resource_gate).expanduser().resolve())
            scheduler_raw, scheduler_file_sha, scheduler_size = resource_efficiency.load_artifact(Path(args.scheduler_resource_snapshot).expanduser().resolve())
            resource_policy = resource_efficiency.validate_policy(policy_raw)
            resource_gate = resource_efficiency._validate_gate_binding(
                gate_raw,
                allow_historical=False,
            )
            scheduler_resource_snapshot = resource_efficiency.validate_scheduler_snapshot(scheduler_raw, now=utc_now())
            resource_artifact_bindings = {
                "policy": (policy_file_sha, policy_size), "gate": (gate_file_sha, gate_size),
                "scheduler": (scheduler_file_sha, scheduler_size),
            }
        except (execution_batch.BatchError, resource_efficiency.ResourceError) as exc:
            fail(f"execution-batch gate blocked submit: {exc}")
        execution_task = next(
            (
                item for item in execution_ledger["tasks"]
                if item["scientific_task_id"] == args.scientific_task_id
            ),
            None,
        )
        if execution_task is None:
            fail("execution-batch ledger does not contain the exact scientific task")
        if execution_task["identity"]["relevant_input_sha256"] != captured_input_sha256:
            fail("execution-batch scientific task is not bound to the captured input hash")
        attempt_id = execution_batch.attempt_id_for(
            execution_ledger["batch"]["batch_id"], args.idempotency_key
        )
        execution_binding = {
            "batch_id": execution_ledger["batch"]["batch_id"],
            "review_sha256": execution_ledger["batch"]["review_sha256"],
            "scientific_task_id": args.scientific_task_id,
            "attempt_id": attempt_id,
            "idempotency_key": args.idempotency_key,
            "estimated_core_hours": float(args.estimated_core_hours),
            "estimated_core_hours_evidence": {
                "source": args.estimated_core_hours_evidence_source,
                "sha256": args.estimated_core_hours_evidence_sha256,
            },
            "resource_binding": {
                "policy_id": resource_policy["policy_id"],
                "policy_sha256": resource_policy["payload_sha256"],
                "gate_id": resource_gate["gate_id"],
                "gate_sha256": resource_gate["gate_sha256"],
                "resource_tier": args.resource_tier,
                "cores": args.resource_cores,
                "memory_gb": args.resource_memory_gb,
                "walltime_seconds": args.walltime_seconds,
            },
        }
        requested = resource_gate["requested_resources"]
        if (
            resource_gate["policy_id"] != resource_policy["policy_id"]
            or resource_gate["policy_sha256"] != resource_policy["payload_sha256"]
            or requested != {
                "resource_tier": args.resource_tier,
                "cores": args.resource_cores,
                "memory_gb": args.resource_memory_gb,
                "walltime_seconds": args.walltime_seconds,
                "estimated_core_hours": float(args.estimated_core_hours),
            }
            or args.resource_cores != input_report["nprocshared"]
            or args.resource_memory_gb * 1024**3 != parse_memory(input_report["mem"])
        ):
            fail("resource policy/gate/CLI binding differs from exact input resources")
        if (
            resource_gate["scheduler_snapshot"]["payload_sha256"] != scheduler_resource_snapshot["payload_sha256"]
            or resource_gate["scheduler_snapshot"]["artifact_sha256"] != resource_artifact_bindings["scheduler"][0]
            or resource_gate["scheduler_snapshot"]["artifact_size"] != resource_artifact_bindings["scheduler"][1]
        ):
            fail("resource gate differs from the exact scheduler snapshot artifact")
    input_approval: dict[str, Any]
    if args.input_approval_record:
        assert requested_work_kind is not None
        input_approval = validate_input_approval(
            Path(args.input_approval_record), input_path, input_report, requested_work_kind
        )
    elif compatibility["status"] != "supported_generic_v1":
        input_approval = {**compatibility, "no_submission_authorization": True}
    else:
        input_approval = {
            "status": "missing_required_for_live_submission",
            "required_schema": compatibility.get("required_schema", INPUT_APPROVAL_SCHEMA),
            "work_kind": requested_work_kind,
            "no_submission_authorization": True,
        }
    approval_summary = None
    live_requirement = None
    if input_approval["status"] == "validated_exact_input_approval":
        assert requested_work_kind is not None
        approval_summary = live_approval_summary(
            project, input_report, maturity, requested_work_kind, input_approval
        )
        if execution_binding is not None:
            approval_summary["execution"] = execution_binding
        live_requirement = live_approval_scope_proposal(approval_summary)
    live_approval: dict[str, Any]
    validated_live_document: dict[str, Any] | None = None
    if args.approval_record and approval_summary is not None:
        validated_live, live_approval_digest = validate_live_approval_binding(
            Path(args.approval_record), approval_summary
        )
        validated_live_document = validated_live
        live_approval = {
            "status": "validated_exact_live_approval",
            "schema": validated_live["schema"],
            "sha256": live_approval_digest,
            "approval_id": validated_live.get("approval_id"),
            "approver_identity": validated_live.get("approver_identity"),
        }
    elif args.approval_record:
        live_approval = {
            "status": "not_evaluated_missing_exact_input_approval",
            "required_schema": LIVE_APPROVAL_V3_SCHEMA,
        }
    else:
        live_approval = {
            "status": "omitted_for_dry_run" if args.dry_run else "missing_required_for_live_submission",
            "required_schema": (
                live_requirement["required_schema"] if live_requirement is not None
                else LIVE_APPROVAL_V3_SCHEMA
            ),
        }
        if live_requirement is not None:
            live_approval.update(live_requirement)
    live_submission_ready = (
        input_approval["status"] == "validated_exact_input_approval"
        and live_approval["status"] == "validated_exact_live_approval"
    )
    if not args.dry_run:
        if input_approval["status"] != "validated_exact_input_approval":
            if input_approval["status"] in {
                "blocked_missing_specialist_input_approval",
                "blocked_combined_open_shell_minimum_stability_parse_risk",
                "blocked_unsupported_open_shell_ordinary",
            }:
                fail(
                    f"{input_approval['status']}: this input family requires its specialist "
                    "owner manifest and independently approved exact stage"
                )
            fail(
                "live submission requires --input-approval-record with exact "
                "protocol selection, input-draft review, and input hash"
            )
        if live_approval["status"] != "validated_exact_live_approval":
            fail("live submission requires a hash-bound --approval-record")
    job, files = stage(
        input_path, project, local_dir,
        execution_binding["resource_binding"] if execution_binding is not None else None,
    )
    job["submission_snapshot"] = {
        "path": str(input_path),
        "sha256": captured_input_sha256,
        "immutable_capture": True,
    }
    job.update({
        "input_approval": input_approval,
        "live_approval": live_approval,
        "live_submission_ready": live_submission_ready,
    })
    job = update_job(
        local_dir,
        submission_snapshot=job["submission_snapshot"],
        input_approval=input_approval,
        live_approval=live_approval,
        live_submission_ready=live_submission_ready,
    )
    expected = verify_staged_submission(local_dir, job, input_report, input_approval, files)
    windows_dir = f"{args.windows_root}\\{project}"
    remote_dir = remote_project_dir(project)

    plan = {
        "project": project,
        "local_dir": str(local_dir),
        "windows_dir": windows_dir,
        "remote_dir": remote_dir,
        "files": [path.name for path in files],
        "input_sha256": job["input_sha256"],
        "input_approval": input_approval,
        "live_approval": live_approval,
        "live_submission_ready": live_submission_ready,
    }
    if maturity is not None:
        plan = {"scientific_maturity": maturity, **plan}
    if args.dry_run:
        plan["dry_run"] = True
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    assert execution_binding is not None
    assert execution_ledger_path is not None
    assert execution_task is not None
    assert validated_live_document is not None
    assert approval_summary is not None
    assert resource_policy is not None
    assert resource_gate is not None
    assert scheduler_resource_snapshot is not None
    try:
        replayed_live_document, replayed_live_digest = validate_live_approval_binding(
            Path(args.approval_record), approval_summary
        )
    except SystemExit:
        fail("live approval changed, was revoked, or expired during local staging; no reservation or network action occurred")
    if (
        replayed_live_digest != live_approval["sha256"]
        or replayed_live_document != validated_live_document
    ):
        fail("live approval stable replay differs before reservation; no network action occurred")
    validated_live_document = replayed_live_document
    try:
        reservation = resource_efficiency.reserve_attempt(
            execution_ledger_path,
            execution_binding["scientific_task_id"],
            identity=execution_task["identity"],
            idempotency_key=execution_binding["idempotency_key"],
            project=project,
            remote_workdir=remote_dir,
            input_sha256=captured_input_sha256,
            live_approval_id=validated_live_document["approval_id"],
            live_approval_sha256=live_approval["sha256"],
            estimated_core_hours_evidence=execution_binding["estimated_core_hours_evidence"],
            reserved_at=utc_now(),
            audit_reason="exact input, live approval, stable task, and idempotency key replayed before network",
            policy=resource_policy,
            gate=resource_gate,
            scheduler_snapshot=scheduler_resource_snapshot,
            scheduler_artifact_sha256=resource_artifact_bindings["scheduler"][0],
            scheduler_artifact_size=resource_artifact_bindings["scheduler"][1],
        )
    except (execution_batch.BatchError, resource_efficiency.ResourceError) as exc:
        fail(f"attempt reservation blocked submit before network: {exc}")
    def prepare_reserved_local_transaction() -> tuple[dict[str, Any], list[Path], dict[str, str], dict[str, Any], int]:
        """Publish every post-reservation local artifact before the first network call."""
        intent = {
            "schema": "gaussian-submission-intent/1",
            "project": project,
            "job_name": project,
            "remote_workdir": remote_dir,
            "input_sha256": captured_input_sha256,
            "batch_id": execution_binding["batch_id"],
            "scientific_task_id": execution_binding["scientific_task_id"],
            "attempt_id": reservation["attempt_id"],
            "idempotency_key": execution_binding["idempotency_key"],
            "live_approval_id": validated_live_document["approval_id"],
            "live_approval_sha256": live_approval["sha256"],
            "reserved_at": reservation["reserved_at"],
        }
        intent["intent_sha256"] = canonical_digest(intent)
        intent_path = local_dir / "submission-intent.json"
        publish_new_json(intent_path, intent)
        consumption = {
            "schema": "auto-g16-live-approval-consumption/1",
            "approval_id": validated_live_document["approval_id"],
            "approval_sha256": live_approval["sha256"],
            "attempt_id": reservation["attempt_id"],
            "idempotency_key": reservation["idempotency_key"],
            "consumed_at": utc_now(),
        }
        consumption["consumption_sha256"] = canonical_digest(consumption)
        publish_new_json(local_dir / "live-approval-consumption.json", consumption)
        checksums_path = local_dir / str(job["checksums"])
        upload_files = [path for path in files if path != checksums_path]
        upload_files.append(intent_path)
        atomic_text(
            checksums_path,
            "".join(f"{sha256(item)}  {item.name}\n" for item in upload_files),
        )
        transaction_files = [*upload_files, checksums_path]
        transfer_size_bytes = sum(path.stat().st_size for path in transaction_files)
        upload_timeout_seconds = transfer_timeout_seconds(transfer_size_bytes)
        transaction_job = update_job(
            local_dir,
            status="submission_uncertain",
            execution_batch={
                "ledger": str(execution_ledger_path),
                "batch_id": execution_binding["batch_id"],
                "scientific_task_id": execution_binding["scientific_task_id"],
                "attempt_id": reservation["attempt_id"],
                "idempotency_key": reservation["idempotency_key"],
                "reservation_sha256": canonical_digest(reservation),
            },
            submission_intent_sha256=intent["intent_sha256"],
            transfer_timeout_evidence={
                "known_upload_size_bytes": transfer_size_bytes,
                "mac_to_rtwin_timeout_seconds": upload_timeout_seconds,
                "rtwin_to_server_timeout_seconds": upload_timeout_seconds,
                "rate_floor_bytes_per_second": TRANSFER_RATE_FLOOR_BYTES_PER_SECOND,
                "fixed_overhead_seconds": TRANSFER_FIXED_OVERHEAD_SECONDS,
            },
        )
        transaction_expected = verify_staged_submission(
            local_dir, transaction_job, input_report, input_approval, transaction_files
        )
        return intent, transaction_files, transaction_expected, transaction_job, upload_timeout_seconds

    try:
        intent, files, expected, job, upload_timeout_seconds = prepare_reserved_local_transaction()
    except (OSError, ValueError, SystemExit, KeyboardInterrupt) as exc:
        evidence = {
            "source": "proven_pre_network_local_transaction_failure",
            "sha256": canonical_digest({
                "attempt_id": reservation["attempt_id"],
                "phase": "post_reservation_before_first_network",
                "error_type": type(exc).__name__,
            }),
        }
        try:
            reconcile_execution_attempt(
                execution_ledger_path, reservation["attempt_id"],
                state="reconciled_not_submitted", observed_at=utc_now(),
                reason="post-reservation local transaction failed before any network command",
                reconciliation_evidence=evidence,
            )
        except (execution_batch.BatchError, resource_efficiency.ResourceError) as ledger_exc:
            with contextlib.suppress(OSError, ValueError, SystemExit):
                update_job(local_dir, status="submission_uncertain", pre_network_reconciliation_error=str(ledger_exc))
            fail("pre-network local transaction failed and ledger release also failed", code=5)
        with contextlib.suppress(OSError, ValueError, SystemExit):
            update_job(local_dir, status="not_submitted", qsub_invocation_started=False, submission_reconciliation=evidence)
        if isinstance(exc, KeyboardInterrupt):
            raise
        fail(f"local transaction failed before network; reservation released: {exc}")

    try:
        mkdir_script = (
            f"if(Test-Path -LiteralPath '{windows_dir}'){{exit 43}};"
            f"New-Item -ItemType Directory -Path '{windows_dir}' -ErrorAction Stop | Out-Null"
        )
        run([*ssh_base(args), "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershell_encoded(mkdir_script)])
        assert_file_bindings_unchanged(files, expected)
        windows_dir_scp = windows_dir.replace("\\", "/")
        scp_to_windows = [
            "scp", "-F", str(Path(args.mac_ssh_config).expanduser()), *map(str, files),
            f"{args.rtwin_alias}:{windows_dir_scp}/",
        ]
        run(scp_to_windows, timeout_seconds=upload_timeout_seconds)

        ps_paths = ",".join(f"'{windows_dir}\\{name}'" for name in expected)
        hash_script = (
            f"$files=@({ps_paths}); foreach($f in $files){{"
            "$h=(Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower();"
            "Write-Output ((Split-Path $f -Leaf)+' '+$h)}"
        )
        hash_result = run([*ssh_base(args), "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershell_encoded(hash_script)])
        observed: dict[str, str] = {}
        for line in str(hash_result.stdout).splitlines():
            match = re.fullmatch(r"(.+?)\s+([0-9a-fA-F]{64})", line.strip())
            if match:
                observed[match.group(1)] = match.group(2).lower()
        mismatches = [name for name, digest in expected.items() if observed.get(name) != digest]
        if mismatches:
            fail("RTwin SHA-256 mismatch or missing hash: " + ", ".join(mismatches))

        # This is the only server-side directory creation path. It is one
        # atomic claim and rejects every pre-existing path, including empty.
        run(
            nested_ssh(args, "bash", "-s"),
            input_bytes=remote_empty_directory_guard(project).encode("utf-8"),
        )
        windows_files = [f"{windows_dir}\\{path.name}" for path in files]
        run(
            [*ssh_base(args), "scp", "-F", args.windows_server_config, *windows_files, f"{args.server_alias}:{remote_dir}/"],
            timeout_seconds=upload_timeout_seconds,
        )
    except SystemExit:
        evidence = {
            "source": "local_transaction_stopped_before_qsub",
            "sha256": canonical_digest({
                "attempt_id": reservation["attempt_id"],
                "phase": "pre_qsub_transport",
                "job_state_sha256": read_job_state(local_dir)["state_sha256"],
            }),
        }
        try:
            reconcile_execution_attempt(
                execution_ledger_path,
                reservation["attempt_id"],
                state="reconciled_not_submitted",
                observed_at=utc_now(),
                reason="local control flow proved qsub was never invoked",
                reconciliation_evidence=evidence,
            )
        except (execution_batch.BatchError, resource_efficiency.ResourceError) as ledger_exc:
            update_job(local_dir, status="submission_uncertain", pre_qsub_reconciliation_error=str(ledger_exc))
            fail("pre-qsub transport failed and ledger reconciliation also failed", code=5)
        update_job(local_dir, status="not_submitted", submission_reconciliation=evidence)
        raise

    try:
        replay_resource_artifacts_before_qsub(
            policy_path=Path(args.resource_policy).expanduser().resolve(),
            gate_path=Path(args.resource_gate).expanduser().resolve(),
            scheduler_path=Path(args.scheduler_resource_snapshot).expanduser().resolve(),
            expected_policy=resource_policy, expected_gate=resource_gate,
            expected_scheduler=scheduler_resource_snapshot,
            expected_bindings=resource_artifact_bindings, now=utc_now(),
        )
    except (OSError, ValueError, resource_efficiency.ResourceError) as exc:
        evidence = {
            "source": "resource_artifact_replay_failed_before_qsub",
            "sha256": canonical_digest({"attempt_id": reservation["attempt_id"], "reason": str(exc)}),
        }
        try:
            reconcile_execution_attempt(
                execution_ledger_path, reservation["attempt_id"],
                state="reconciled_not_submitted", observed_at=utc_now(),
                reason="resource policy/gate/scheduler freshness or exact replay failed before qsub",
                reconciliation_evidence=evidence,
            )
        except (execution_batch.BatchError, resource_efficiency.ResourceError) as ledger_exc:
            update_job(local_dir, status="submission_uncertain", resource_replay_error=str(ledger_exc))
            fail("resource replay failed before qsub and ledger reconciliation also failed", code=5)
        update_job(local_dir, status="not_submitted", qsub_invocation_started=False, submission_reconciliation=evidence)
        fail("resource artifact/freshness replay failed; qsub was not invoked")

    try:
        qsub_live_document, qsub_live_digest = validate_live_approval_binding(
            Path(args.approval_record), approval_summary
        )
        if (
            qsub_live_digest != live_approval["sha256"]
            or qsub_live_document != validated_live_document
        ):
            fail("live approval changed after reservation and transfer")
    except SystemExit:
        evidence = {
            "source": "live_approval_replay_failed_before_qsub",
            "sha256": canonical_digest({
                "attempt_id": reservation["attempt_id"],
                "approval_sha256": live_approval["sha256"],
                "phase": "immediately_before_qsub",
            }),
        }
        try:
            reconcile_execution_attempt(
                execution_ledger_path,
                reservation["attempt_id"],
                state="reconciled_not_submitted",
                observed_at=utc_now(),
                reason="approval drift, revocation, or expiry was detected before qsub invocation",
                reconciliation_evidence=evidence,
            )
        except (execution_batch.BatchError, resource_efficiency.ResourceError) as exc:
            update_job(
                local_dir, status="submission_uncertain", qsub_invocation_started=False,
                approval_replay_reconciliation_error={
                    "error_type": type(exc).__name__, "message": str(exc),
                    "attempt_id": reservation["attempt_id"], "evidence_sha256": evidence["sha256"],
                },
            )
            fail("approval replay failed before qsub and ledger reconciliation also failed", code=5)
        update_job(
            local_dir,
            status="not_submitted",
            qsub_invocation_started=False,
            submission_reconciliation=evidence,
        )
        fail("approval is no longer valid; qsub was not invoked and the attempt is reconciled not submitted")

    update_job(local_dir, status="submission_uncertain", qsub_invocation_started=True)
    submit_script = remote_existing_directory_guard(project) + f"""
cd {remote_dir}
sha256sum -c checksums.sha256
if [ -e submission-receipt.json ]; then
  echo 'REFUSING_DUPLICATE: immutable submission receipt already exists' >&2
  exit 17
fi
job_id=$(qsub -v AUTO_G16_ATTEMPT_ID={reservation['attempt_id']},AUTO_G16_INPUT_SHA256={captured_input_sha256} {project}.pbs)
receipt_tmp='.submission-receipt-{reservation['attempt_id']}.tmp'
if [ -e "$receipt_tmp" ]; then
  echo 'REFUSING_DUPLICATE: transaction temp receipt already exists' >&2
  exit 18
fi
printf '{{"schema":"gaussian-remote-submission-receipt/1","project":"{project}","job_name":"{project}","input_sha256":"{captured_input_sha256}","attempt_id":"{reservation['attempt_id']}","job_id":"%s"}}\n' "$job_id" > "$receipt_tmp"
chmod 400 "$receipt_tmp"
if ! ln "$receipt_tmp" submission-receipt.json; then
  echo 'REFUSING_DUPLICATE: immutable submission receipt publish failed' >&2
  exit 19
fi
printf '%s\n' "$job_id"
"""
    result = run(nested_ssh(args, "bash", "-l", "-s"), input_bytes=submit_script.encode("utf-8"), check=False)
    outcome = classify_qsub_outcome(result)
    if outcome["classification"] != "submitted_unique":
        update_job(local_dir, status="submission_uncertain", submission_output=outcome["output"])
        fail(
            "qsub result is uncertain; do not retry. Run reconcile-submission for the exact reservation",
            code=3,
        )
    job_id = outcome["job_id"]
    assert isinstance(job_id, str)
    receipt = {
        "schema": "gaussian-submission-receipt/1",
        "project": project,
        "job_name": project,
        "input_sha256": captured_input_sha256,
        "attempt_id": reservation["attempt_id"],
        "job_id": job_id,
        "intent_sha256": intent["intent_sha256"],
        "observed_at": utc_now(),
    }
    receipt["receipt_sha256"] = canonical_digest(receipt)
    try:
        publish_new_json(local_dir / "submission-receipt.json", receipt)
    except ValueError as exc:
        update_job(local_dir, status="submission_uncertain", receipt_error=str(exc))
        fail("qsub may have succeeded but immutable local receipt could not be published; reconcile only", code=3)
    try:
        reconciled_attempt = reconcile_execution_attempt(
            execution_ledger_path,
            reservation["attempt_id"],
            state="submitted",
            observed_at=receipt["observed_at"],
            reason="unique qsub job ID captured in immutable local and remote receipts",
            scheduler_reference=job_id,
            reconciliation_evidence={
                "source": "immutable_submission_receipt",
                "sha256": receipt["receipt_sha256"],
            },
        )
    except (execution_batch.BatchError, resource_efficiency.ResourceError) as exc:
        update_job(local_dir, status="submission_uncertain", ledger_reconcile_error=str(exc))
        fail("qsub succeeded but ledger reconciliation is incomplete; reconcile only", code=3)
    updated = update_job(
        local_dir,
        status="submitted",
        job_id=job_id,
        rtwin_sha256_verified=True,
        server_sha256_verified=True,
        execution_attempt_sha256=canonical_digest(reconciled_attempt),
        submission_receipt_sha256=receipt["receipt_sha256"],
    )
    print(json.dumps({"submitted": True, "job_id": job_id, "job": updated}, ensure_ascii=False, indent=2))


def classify_submission_reconciliation(
    *,
    project: str,
    input_sha256: str,
    attempt_id: str,
    directory_present: bool | None,
    remote_intent: dict[str, Any] | None,
    remote_receipt: dict[str, Any] | None,
    qstat_text: str,
) -> dict[str, Any]:
    """Classify read-only remote evidence without ever proposing another qsub."""

    exact = {
        "project": project,
        "job_name": project,
        "input_sha256": input_sha256,
        "attempt_id": attempt_id,
    }
    intent_matches = bool(
        isinstance(remote_intent, dict)
        and all(remote_intent.get(key) == value for key, value in exact.items())
    )
    receipt_job_id: str | None = None
    if isinstance(remote_receipt, dict) and all(
        remote_receipt.get(key) == value for key, value in exact.items()
    ):
        candidate = remote_receipt.get("job_id")
        if isinstance(candidate, str) and JOB_ID_RE.fullmatch(candidate):
            receipt_job_id = candidate
    candidates: list[str] = []
    for block in re.split(r"(?=Job Id:)", qstat_text):
        identifier = re.search(r"(?m)^Job Id:\s*([^\s]+)\s*$", block)
        if not identifier:
            continue
        job_id = identifier.group(1)
        if (
            JOB_ID_RE.fullmatch(job_id)
            and re.search(rf"(?m)^\s*Job_Name\s*=\s*{re.escape(project)}\s*$", block)
            and f"AUTO_G16_ATTEMPT_ID={attempt_id}" in block
            and f"AUTO_G16_INPUT_SHA256={input_sha256}" in block
        ):
            candidates.append(job_id)
    unique_candidates = sorted(set(candidates))
    if receipt_job_id is not None:
        if unique_candidates and unique_candidates != [receipt_job_id]:
            return {
                "classification": "still_uncertain_multiple",
                "job_ids": sorted(set([receipt_job_id, *unique_candidates])),
                "intent_matches": intent_matches,
                "automatic_qsub_authorized": False,
            }
        return {
            "classification": "submitted_unique",
            "job_ids": [receipt_job_id],
            "intent_matches": intent_matches,
            "evidence_source": "immutable_remote_submission_receipt",
            "automatic_qsub_authorized": False,
        }
    if len(unique_candidates) == 1 and intent_matches:
        return {
            "classification": "submitted_unique",
            "job_ids": unique_candidates,
            "intent_matches": True,
            "evidence_source": "exact_qstat_variables_and_remote_intent",
            "automatic_qsub_authorized": False,
        }
    if len(unique_candidates) > 1:
        return {
            "classification": "still_uncertain_multiple",
            "job_ids": unique_candidates,
            "intent_matches": intent_matches,
            "automatic_qsub_authorized": False,
        }
    if len(unique_candidates) == 1:
        return {
            "classification": "still_uncertain_one_unbound",
            "job_ids": unique_candidates,
            "intent_matches": False,
            "automatic_qsub_authorized": False,
        }
    if directory_present is False and not unique_candidates:
        return {
            "classification": "definitely_not_submitted",
            "job_ids": [],
            "intent_matches": False,
            "evidence_source": "atomic_project_directory_absent_and_no_exact_scheduler_job",
            "automatic_qsub_authorized": False,
        }
    return {
        "classification": "still_uncertain_zero",
        "job_ids": [],
        "intent_matches": intent_matches,
        "automatic_qsub_authorized": False,
    }


def _decode_probe_json(markers: dict[str, str], key: str) -> dict[str, Any] | None:
    encoded = markers.get(key)
    if not encoded:
        return None
    try:
        value = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def command_reconcile_submission(args) -> None:
    project = validate_project(args.project)
    local_dir = Path(args.local_dir).expanduser().resolve()
    ledger_path = Path(args.execution_batch_ledger).expanduser().resolve()
    try:
        ledger = validate_execution_ledger_path(ledger_path)
    except execution_batch.BatchError as exc:
        fail(f"cannot reconcile invalid execution ledger: {exc}")
    attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == args.attempt_id), None)
    if attempt is None:
        fail("reconcile-submission requires an exact existing attempt reservation")
    if (
        attempt["project"] != project
        or attempt["job_name"] != project
        or attempt["remote_workdir"] != remote_project_dir(project)
    ):
        fail("reconcile-submission project/job scope differs from the reservation")
    if attempt["state"] != "submission_uncertain":
        print(json.dumps({
            "classification": "already_reconciled",
            "attempt": attempt,
            "remote_actions": False,
            "automatic_qsub_authorized": False,
        }, ensure_ascii=False, indent=2))
        return
    remote_dir = remote_project_dir(project)
    probe_script = f"""set -euo pipefail
jobdir='{remote_dir}'
if [ ! -e "$jobdir" ]; then
  echo 'DIRECTORY_PRESENT=0'
  exit 0
fi
echo 'DIRECTORY_PRESENT=1'
if [ -f "$jobdir/submission-intent.json" ] && [ ! -L "$jobdir/submission-intent.json" ]; then
  printf 'INTENT_B64='
  base64 -w0 "$jobdir/submission-intent.json"
  printf '\n'
fi
if [ -f "$jobdir/submission-receipt.json" ] && [ ! -L "$jobdir/submission-receipt.json" ]; then
  printf 'RECEIPT_B64='
  base64 -w0 "$jobdir/submission-receipt.json"
  printf '\n'
fi
"""
    probe = run(
        nested_ssh(args, "bash", "-s"), input_bytes=probe_script.encode("utf-8"), check=False
    )
    qstat = run(nested_ssh(args, "qstat", "-f"), check=False)
    if probe.returncode != 0 or qstat.returncode != 0:
        fail("submission reconciliation transport evidence is unknown; qsub remains forbidden", code=3)
    markers: dict[str, str] = {}
    for line in str(probe.stdout).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            markers[key] = value
    directory_present = (
        True if markers.get("DIRECTORY_PRESENT") == "1"
        else False if markers.get("DIRECTORY_PRESENT") == "0"
        else None
    )
    classification = classify_submission_reconciliation(
        project=project,
        input_sha256=attempt["input_sha256"],
        attempt_id=attempt["attempt_id"],
        directory_present=directory_present,
        remote_intent=_decode_probe_json(markers, "INTENT_B64"),
        remote_receipt=_decode_probe_json(markers, "RECEIPT_B64"),
        qstat_text=str(qstat.stdout),
    )
    evidence_document = {
        "schema": "gaussian-submission-reconciliation/1",
        "project": project,
        "job_name": project,
        "input_sha256": attempt["input_sha256"],
        "attempt_id": attempt["attempt_id"],
        "classification": classification["classification"],
        "job_ids": classification["job_ids"],
        "observed_at": utc_now(),
        "remote_read_only": True,
        "automatic_qsub_authorized": False,
    }
    evidence_document["evidence_sha256"] = canonical_digest(evidence_document)
    if classification["classification"] == "submitted_unique":
        job_id = classification["job_ids"][0]
        local_receipt = {
            "schema": "gaussian-submission-receipt/1",
            "project": project,
            "job_name": project,
            "input_sha256": attempt["input_sha256"],
            "attempt_id": attempt["attempt_id"],
            "job_id": job_id,
            "intent_sha256": read_job_state(local_dir).get("submission_intent_sha256"),
            "observed_at": evidence_document["observed_at"],
        }
        local_receipt["receipt_sha256"] = canonical_digest(local_receipt)
        receipt_path = local_dir / "submission-receipt.json"
        if receipt_path.exists():
            existing = load_strict_json(receipt_path)
            if any(existing.get(key) != local_receipt.get(key) for key in (
                "project", "job_name", "input_sha256", "attempt_id", "job_id"
            )):
                fail("existing immutable submission receipt conflicts with reconciliation")
            local_receipt = existing
        else:
            publish_new_json(receipt_path, local_receipt)
        resolved = reconcile_execution_attempt(
            ledger_path,
            attempt["attempt_id"],
            state="submitted",
            observed_at=evidence_document["observed_at"],
            reason="read-only reconciliation found exactly one bound scheduler submission",
            scheduler_reference=job_id,
            reconciliation_evidence={
                "source": classification["evidence_source"],
                "sha256": evidence_document["evidence_sha256"],
            },
        )
        update_job(
            local_dir,
            status="submitted",
            job_id=job_id,
            submission_reconciliation=evidence_document,
            execution_attempt_sha256=canonical_digest(resolved),
        )
    elif classification["classification"] == "definitely_not_submitted":
        resolved = reconcile_execution_attempt(
            ledger_path,
            attempt["attempt_id"],
            state="reconciled_not_submitted",
            observed_at=evidence_document["observed_at"],
            reason="read-only evidence proved the atomic project directory never existed",
            reconciliation_evidence={
                "source": classification["evidence_source"],
                "sha256": evidence_document["evidence_sha256"],
            },
        )
        update_job(
            local_dir,
            status="not_submitted",
            submission_reconciliation=evidence_document,
            execution_attempt_sha256=canonical_digest(resolved),
        )
    print(json.dumps({
        **classification,
        "reconciliation_evidence": evidence_document,
        "remote_read_only": True,
    }, ensure_ascii=False, indent=2))


def command_status(args) -> None:
    if not args.job_id and not args.project:
        fail("status requires --job-id or --project")
    if args.job_id:
        job_id = validate_job_id(args.job_id)
        result = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
        print(str(result.stdout or result.stderr).strip())
        raise SystemExit(result.returncode)
    project = validate_project(args.project)
    result = run(nested_ssh(args, "qstat", "-f"), check=False)
    blocks = re.split(r"(?=Job Id:)", str(result.stdout))
    matches = [block.strip() for block in blocks if re.search(rf"(?m)^\s*Job_Name\s*=\s*{re.escape(project)}\s*$", block)]
    if matches:
        print("\n\n".join(matches))
    else:
        print(json.dumps({"project": project, "active_job": False, "note": "job may be completed and purged; inspect/fetch the log"}))


def batch_qstat_snapshot(args, job_ids: list[str] | None = None) -> dict[str, Any]:
    exact_ids = [validate_job_id(item) for item in (job_ids or [])]
    if len(set(exact_ids)) != len(exact_ids):
        fail("batch-status job IDs must be unique")
    collected_at = utc_now()
    script = COMPLETE_USER_QSTAT_SCRIPT
    command = nested_ssh(args, "bash", "-s")
    result = run_read_only(
        command, input_bytes=script,
        capability=_exact_read_only_capability("complete_user_qstat", command, script),
    )
    records: dict[str, dict[str, Any]] = {}
    owner: str | None = None
    transport = "success"
    error: str | None = None
    if result.returncode != 0:
        transport = "timeout" if result.returncode == 124 else "transport_error"
        error = command_detail(result) or "complete user qstat did not return scheduler success; empty scope is unproven"
    elif str(result.stderr or "").strip():
        transport = "parse_failed"
        error = "complete user qstat returned nonempty warning/error text on stderr"
    else:
        output = str(result.stdout or "")
        owner_match = re.match(r"^AUTO_G16_OWNER\t([A-Za-z0-9_.-]+)\n", output)
        if owner_match is None:
            transport = "parse_failed"; error = "complete user qstat owner evidence is absent"
        else:
            owner = owner_match.group(1); qstat_output = output[owner_match.end():]
            blocks_by_job: dict[str, list[str]] = {}
            split_blocks = re.split(r"(?=^Job Id:)", qstat_output, flags=re.MULTILINE)
            prefix = split_blocks[0]
            job_blocks = split_blocks[1:]
            if prefix.strip():
                transport = "parse_failed"; error = "complete user qstat contains non-job text before the first job block"
            for block in job_blocks:
                match = re.search(r"(?m)^Job Id:\s*([^\s]+)\s*$", block)
                if match: blocks_by_job.setdefault(match.group(1), []).append(block)
            marker_count = len(re.findall(r"(?m)^Job Id:", qstat_output))
            malformed_block_text = any(
                any(line.strip() and not line[:1].isspace() for line in block.splitlines()[1:])
                for block in job_blocks
            )
            if transport != "success":
                pass
            elif marker_count != sum(len(blocks) for blocks in blocks_by_job.values()):
                transport = "parse_failed"; error = "complete user qstat contains an unparseable job block"
            elif malformed_block_text:
                transport = "parse_failed"; error = "complete user qstat contains non-field text inside or after a job block"
            elif any(len(blocks) != 1 for blocks in blocks_by_job.values()):
                transport = "parse_failed"; error = "complete user qstat repeats a job block"
            else:
                for job_id, only in blocks_by_job.items():
                    block = only[0]
                    owner_fields = re.findall(r"(?im)^\s*Job_Owner\s*=\s*([^@\s]+)@\S+\s*$", block)
                    state_fields = re.findall(r"(?im)^\s*job_state\s*=\s*(\S+)\s*$", block)
                    name_fields = re.findall(r"(?im)^\s*Job_Name\s*=\s*(\S+)\s*$", block)
                    core_fields = [int(value) for value in re.findall(r"(?im)^\s*Resource_List\.(?:ncpus|procs)\s*=\s*(\d+)\s*$", block)]
                    core_fields += [int(nodes) * int(ppn) for nodes, ppn in re.findall(r"(?im)^\s*Resource_List\.nodes\s*=\s*(\d+):ppn=(\d+)\s*$", block)]
                    memory_fields = re.findall(r"(?im)^\s*Resource_List\.mem\s*=\s*(\d+(?:\.\d+)?)(kb|mb|gb|tb)\s*$", block)
                    if len(owner_fields) != 1 or owner_fields[0] != owner or len(state_fields) != 1 or len(name_fields) != 1:
                        records[job_id] = {"status": "unknown", "pbs_state": None, "job_name": None, "cores": None, "memory_gb": None, "error": "job owner/state/name evidence is absent, duplicated, or conflicting"}
                        continue
                    if state_fields[0] not in {"Q", "R"}:
                        records[job_id] = {"status": "unknown", "pbs_state": None, "job_name": None, "cores": None, "memory_gb": None, "error": "job scheduler state is unsupported or non-active"}
                        continue
                    cores = core_fields[0] if len(core_fields) == 1 else None
                    memory_gb = None
                    if len(memory_fields) == 1:
                        number, unit = memory_fields[0]
                        converted = float(number) * {"kb": 1 / 1024**2, "mb": 1 / 1024, "gb": 1, "tb": 1024}[unit.lower()]
                        if converted.is_integer(): memory_gb = int(converted)
                    records[job_id] = {
                        "status": "present", "pbs_state": state_fields[0], "job_name": name_fields[0],
                        "cores": cores, "memory_gb": memory_gb, "error": None,
                    }
                for job_id in exact_ids:
                    if job_id not in records:
                        records[job_id] = {"status": "unknown", "pbs_state": None, "job_name": None, "cores": None, "memory_gb": None, "error": "requested exact job absent from complete user qstat"}
    if transport != "success":
        owner = None; records = {}
    snapshot = {
        "schema": "gaussian-batch-qstat-snapshot/1", "collected_at": collected_at,
        "source": "single_complete_user_qstat",
        "scope": {"kind": "complete_user_active_jobs", "owner": owner, "completeness": "complete" if transport == "success" else "unknown", "requested_job_ids": exact_ids},
        "freshness": "fresh" if transport == "success" else "unknown",
        "age_seconds": 0, "transport_classification": transport,
        "job_ids": sorted(records), "records": records, "read_only": True, "error": error,
    }
    snapshot["evidence_sha256"] = canonical_digest(snapshot)
    return resource_efficiency.validate_batch_qstat_snapshot(snapshot)


def command_batch_status(args) -> None:
    print(json.dumps(batch_qstat_snapshot(args, args.job_ids), ensure_ascii=False, indent=2))


def command_tail(args) -> None:
    project = validate_project(args.project)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.input_stem):
        fail("invalid input stem")
    if not 1 <= args.lines <= 500:
        fail("--lines must be between 1 and 500")
    remote_dir = remote_project_dir(project)
    guard = remote_existing_directory_guard(project)
    path = f"{remote_dir}/{args.input_stem}.log"
    guard_result = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=guard.encode("utf-8"),
        check=False,
    )
    if guard_result.returncode:
        fail(str(guard_result.stderr or guard_result.stdout).strip())
    result = run(nested_ssh(args, "tail", "-n", str(args.lines), path), check=False)
    print(str(result.stdout or result.stderr).rstrip())
    raise SystemExit(result.returncode)


def command_fetch(args) -> None:
    transfer = fetch_results(args, args.project, Path(args.output_dir))
    if transfer.get("snapshot_complete") is True:
        output_dir = checked_local_path(Path(args.output_dir), "fetch output directory")
        local_dir = checked_local_path(Path(args.local_dir), "fetch local job directory")
        validate_local_job_binding(local_dir, args.project, args.job_id, args.input_stem, require_fetched=False)
        transfer_path = output_dir / "transfer.json"
        update_job(
            local_dir,
            results_fetched=True,
            fetch_snapshot=str(output_dir / "transfer.json"),
            fetch_snapshot_sha256=sha256(transfer_path),
            fetch_snapshot_size=transfer_path.stat().st_size,
            result_file=str(output_dir / "result.json"),
        )
    print(json.dumps(transfer, ensure_ascii=False, indent=2))


def command_inspect(args) -> None:
    inspection = inspect_job(args, args.project, args.input_stem, args.job_id)
    if args.local_dir:
        local_dir = checked_local_path(Path(args.local_dir), "inspection local job directory")
        if (local_dir / "job.json").is_file():
            job = validate_local_job_binding(local_dir, args.project, args.job_id, args.input_stem, require_fetched=False, expected_attempt_id=args.attempt_id)
            updates: dict[str, Any] = {"status": inspection["state"], "monitor_observation": inspection}
            if inspection["state"] in {"completed", "failed"} and inspection["freshness"] == "fresh" and inspection["transport_classification"] == "success":
                receipt = publish_terminal_inspection_receipt(local_dir, job, inspection, args.input_stem)
                updates["terminal_inspection_receipt_sha256"] = receipt["receipt_sha256"]
            update_job(local_dir, **updates)
    if args.execution_batch_ledger or args.attempt_id:
        if not args.execution_batch_ledger or not args.attempt_id:
            fail("ledger monitor recording requires both --execution-batch-ledger and --attempt-id")
        observation = {
            "collected_at": inspection["collected_at"], "source": inspection["source"],
            "freshness": inspection["freshness"], "age_seconds": inspection["age_seconds"],
            "transport_classification": inspection["transport_classification"],
            "state": inspection["state"] if inspection["state"] not in {"held", "exiting"} else "unknown",
            "interruption_proof": None,
            "evidence_sha256": inspection.get("evidence_sha256", canonical_digest(inspection)),
        }
        try:
            resource_efficiency.record_monitor_observation(
                Path(args.execution_batch_ledger).expanduser().resolve(),
                attempt_id=args.attempt_id, project=args.project,
                observation=observation, job_id=args.job_id,
            )
        except resource_efficiency.ResourceError as exc:
            fail(f"monitor ledger append failed closed: {exc}")
    print(json.dumps(inspection, ensure_ascii=False, indent=2))


def command_watch(args) -> None:
    if not 2 <= args.poll_seconds <= 300:
        fail("--poll-seconds must be between 2 and 300")
    if not 10 <= args.timeout_seconds <= 7 * 24 * 3600:
        fail("--timeout-seconds must be between 10 seconds and 7 days")
    local_dir = checked_local_path(Path(args.local_dir), "watch local job directory")
    output_dir = checked_local_path(Path(args.output_dir), "watch output directory")
    clock = getattr(args, "_watch_monotonic", time.monotonic)
    sleeper = getattr(args, "_watch_sleep", time.sleep)
    random_value = getattr(args, "_watch_random", random.random)
    deadline = clock() + args.timeout_seconds
    previous_stale_signature = None
    stale_repeats = 0
    stable_since_epoch: float | None = None
    final: dict[str, Any] | None = None
    last_persist_signature: tuple[Any, ...] | None = None
    last_persisted_at: float | None = None
    poll_interval = float(args.poll_seconds)
    while True:
        loop_now = clock()
        if loop_now >= deadline:
            break
        inspection = inspect_job(args, args.project, args.input_stem, args.job_id)
        signature = (inspection.get("log_size"), inspection.get("log_mtime_epoch"))
        if (
            inspection.get("termination_counts_known") is True
            and inspection.get("interrupted_candidate") is True
            and inspection.get("pbs_record_present") is False
        ):
            same_signature = signature == previous_stale_signature
            stale_repeats = stale_repeats + 1 if same_signature else 1
            if not same_signature: stable_since_epoch = time.time()
            previous_stale_signature = signature
            now_epoch = time.time()
            stable_duration = 0 if stable_since_epoch is None else max(0, now_epoch - stable_since_epoch)
            log_age = 0 if inspection.get("log_mtime_epoch") is None else max(0, now_epoch - inspection["log_mtime_epoch"])
            if stale_repeats >= 2 and stable_duration >= MIN_INTERRUPTION_STABLE_SECONDS and log_age >= MIN_INTERRUPTION_STABLE_SECONDS and inspection.get("termination_counts_known") is True and not terminal_log_proven(inspection):
                inspection["state"] = "interrupted"
                inspection["note"] = (
                    "explicit scheduler-record absence and a stable incomplete log prove interruption"
                )
                inspection["interruption_proof"] = {
                    "stable_repeats": stale_repeats,
                    "scheduler_record_absent": inspection.get("pbs_record_present") is False,
                    "log_signature_stable": True,
                    "normal_termination_absent": not terminal_log_proven(inspection),
                    "termination_counts_known": True,
                    "stable_duration_seconds": stable_duration,
                    "log_age_seconds": log_age,
                    "full_normal_termination_count": inspection.get("full_normal_termination_count"),
                    "full_error_termination_count": inspection.get("full_error_termination_count"),
                }
                inspection["evidence_sha256"] = canonical_digest({
                    key: value for key, value in inspection.items() if key != "evidence_sha256"
                })
        else:
            stale_repeats = 0
            previous_stale_signature = None
            stable_since_epoch = None
        persistence_signature = (
            inspection.get("state"), inspection.get("pbs_state"), inspection.get("freshness"),
            inspection.get("transport_classification"), inspection.get("pbs_record_present"),
            inspection.get("process_alive"), inspection.get("log_size"), inspection.get("log_mtime_epoch"),
            inspection.get("full_normal_termination_count"), inspection.get("full_error_termination_count"),
            canonical_digest(inspection.get("interruption_proof")) if inspection.get("interruption_proof") else None,
        )
        urgent = (
            inspection.get("state") not in {"queued", "running"}
            or inspection.get("transport_classification") != "success"
            or inspection.get("freshness") != "fresh"
        )
        stable_unchanged = persistence_signature == last_persist_signature
        heartbeat_due = last_persisted_at is None or loop_now - last_persisted_at >= WATCH_HEARTBEAT_SECONDS
        persist = urgent or not stable_unchanged or heartbeat_due
        if persist and (local_dir / "job.json").is_file():
            job = validate_local_job_binding(local_dir, args.project, args.job_id, args.input_stem, require_fetched=False, expected_attempt_id=args.attempt_id)
            updates = {"status": inspection["state"], "monitor_observation": inspection}
            if inspection["state"] in {"completed", "failed", "interrupted"} and inspection["freshness"] == "fresh" and inspection["transport_classification"] == "success":
                receipt = publish_terminal_inspection_receipt(local_dir, job, inspection, args.input_stem)
                updates["terminal_inspection_receipt_sha256"] = receipt["receipt_sha256"]
            update_job(local_dir, **updates)
        if persist and (args.execution_batch_ledger or args.attempt_id):
            if not args.execution_batch_ledger or not args.attempt_id:
                fail("watch ledger recording requires both --execution-batch-ledger and --attempt-id")
            try:
                resource_efficiency.record_monitor_observation(
                    Path(args.execution_batch_ledger).expanduser().resolve(),
                    attempt_id=args.attempt_id, project=args.project,
                    observation={
                        "collected_at": inspection["collected_at"], "source": inspection["source"],
                        "freshness": inspection["freshness"], "age_seconds": inspection["age_seconds"],
                        "transport_classification": inspection["transport_classification"],
                        "state": inspection["state"] if inspection["state"] not in {"held", "exiting"} else "unknown",
                        "interruption_proof": inspection.get("interruption_proof"),
                        "evidence_sha256": inspection.get("evidence_sha256", canonical_digest(inspection)),
                    },
                    job_id=args.job_id,
                )
            except resource_efficiency.ResourceError as exc:
                fail(f"watch ledger append failed closed: {exc}")
        if persist:
            last_persist_signature = persistence_signature
            last_persisted_at = loop_now
        print(
            json.dumps(
                {
                    "state": inspection["state"],
                    "pbs_state": inspection["pbs_state"],
                    "log_size": inspection["log_size"],
                }
            ),
            flush=True,
        )
        if inspection["state"] in {"completed", "failed", "interrupted"}:
            final = inspection
            break
        if not urgent and stable_unchanged:
            poll_interval = min(float(WATCH_MAX_POLL_SECONDS), max(float(args.poll_seconds), poll_interval * 2.0))
        else:
            poll_interval = float(args.poll_seconds)
        jitter = (float(random_value()) * 2.0 - 1.0) * WATCH_JITTER_FRACTION
        sleeper(max(float(args.poll_seconds), min(float(WATCH_MAX_POLL_SECONDS), poll_interval * (1.0 + jitter))))
    if final is None:
        fail("watch timeout reached while job is still non-terminal", code=4)
    transfer = fetch_results(args, args.project, output_dir) if args.fetch else None
    if transfer and transfer.get("analysis"):
        final["analysis"] = transfer["analysis"]
    fetch_complete = bool(transfer and transfer.get("snapshot_complete") is True)
    if (local_dir / "job.json").is_file():
        validate_local_job_binding(
            local_dir, args.project, args.job_id, args.input_stem,
            require_fetched=False, expected_attempt_id=args.attempt_id,
        )
        update_job(
            local_dir,
            status=final["state"],
            last_inspection=final,
            results_fetched=fetch_complete,
            fetch_snapshot=str(output_dir / "transfer.json") if fetch_complete else None,
            fetch_snapshot_sha256=sha256(output_dir / "transfer.json") if fetch_complete else None,
            fetch_snapshot_size=(output_dir / "transfer.json").stat().st_size if fetch_complete else None,
            result_file=str(output_dir / "result.json") if fetch_complete else None,
        )
    scheduler_cleanup = None
    if (
        args.auto_cleanup_zombie
        and fetch_complete
        and final.get("scheduler_zombie_candidate") is True
    ):
        cleanup_args = argparse.Namespace(**vars(args))
        cleanup_args.stability_seconds = args.zombie_stability_seconds
        cleanup_args.verify_seconds = args.zombie_verify_seconds
        scheduler_cleanup = cleanup_zombie_record(cleanup_args)
        if scheduler_cleanup["status"] == "cleanup_unverified":
            print(
                json.dumps(
                    {
                        "inspection": final,
                        "transfer": transfer,
                        "scheduler_cleanup": scheduler_cleanup,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            fail(
                "automatic qdel was issued once but cleanup could not be verified; do not retry automatically",
                code=5,
            )
    print(
        json.dumps(
            {
                "inspection": final,
                "transfer": transfer,
                "scheduler_cleanup": scheduler_cleanup,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def command_analyze(args) -> None:
    log_path = Path(args.log).expanduser().resolve()
    if not log_path.is_file():
        fail(f"log does not exist: {log_path}")
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    result = analyze_log_file(log_path, output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def diagnose_zombie(args) -> dict[str, Any]:
    """Observe a possible stale PBS R record twice and return cleanup eligibility."""

    if not 5 <= args.stability_seconds <= 300:
        fail("--stability-seconds must be between 5 and 300")
    project = validate_project(args.project)
    job_id = validate_job_id(args.job_id)
    input_stem = args.input_stem
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", input_stem):
        fail("invalid input stem")
    local_dir = checked_local_path(Path(args.local_dir), "zombie local job directory")
    validate_local_job_binding(
        local_dir, project, job_id, input_stem, require_fetched=True
    )
    first = inspect_job(args, project, input_stem, job_id)
    time.sleep(args.stability_seconds)
    second = inspect_job(args, project, input_stem, job_id)
    diagnosis = assess_zombie_observations(project, job_id, [first, second])
    diagnosis["stability_seconds"] = args.stability_seconds
    diagnosis["results_fetched_verified"] = True
    diagnosis["confirmation_required_for_qdel"] = False
    diagnosis["automatic_cleanup_authorized_by_policy"] = True
    diagnosis["server_data_deletion_authorized"] = False
    return diagnosis


def command_diagnose_zombie(args) -> None:
    diagnosis = diagnose_zombie(args)
    local_dir = checked_local_path(Path(args.local_dir), "zombie local job directory")
    update_job(local_dir, last_zombie_diagnosis=diagnosis)
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))


def last_scheduler_record_evidence(diagnosis: dict[str, Any]) -> tuple[bool | None, str]:
    """Preserve the last diagnosis' scheduler-record three-state evidence."""

    observations = diagnosis.get("observations")
    last = observations[-1] if isinstance(observations, list) and observations else {}
    if not isinstance(last, dict):
        return None, "unknown"
    present = last.get("pbs_record_present")
    if present is not True and present is not False and present is not None:
        present = None
    evidence_status = last.get("pbs_evidence_status")
    if evidence_status not in {"present", "absent", "unknown"}:
        evidence_status = (
            "present" if present is True
            else "absent" if present is False
            else "unknown"
        )
    return present, evidence_status


def cleanup_zombie_record(args) -> dict[str, Any]:
    """Issue one qdel only for a repeatedly proven zombie and return its audit record."""

    if not 1 <= args.verify_seconds <= 60:
        fail("--verify-seconds must be between 1 and 60")
    diagnosis = diagnose_zombie(args)
    local_dir = checked_local_path(Path(args.local_dir), "zombie local job directory")
    if diagnosis["classification"] == "self_purged":
        cleanup = {
            "schema": "pbs-zombie-cleanup/1",
            "project": args.project,
            "job_id": args.job_id,
            "status": "self_purged",
            "qdel_issued": False,
            "scheduler_record_present": False,
            "scheduler_record_evidence_status": "absent",
            "server_project_files_changed": False,
            "diagnosis": diagnosis,
        }
        update_job(local_dir, last_zombie_diagnosis=diagnosis, scheduler_cleanup=cleanup)
        return cleanup
    if not diagnosis.get("cleanup_eligible"):
        record_present, evidence_status = last_scheduler_record_evidence(diagnosis)
        cleanup = {
            "schema": "pbs-zombie-cleanup/1",
            "project": args.project,
            "job_id": args.job_id,
            "status": "not_eligible",
            "qdel_issued": False,
            "scheduler_record_present": record_present,
            "scheduler_record_evidence_status": evidence_status,
            "server_project_files_changed": False,
            "diagnosis": diagnosis,
        }
        update_job(local_dir, last_zombie_diagnosis=diagnosis, scheduler_cleanup=cleanup)
        return cleanup

    # This is deliberately the only qdel in the zombie cleanup path. It changes
    # PBS-owned state only; it never removes, truncates, or rewrites server data.
    qdel = run(nested_ssh(args, "qdel", validate_job_id(args.job_id)), check=False)
    qdel_outcome = classify_qdel_outcome(qdel)
    time.sleep(args.verify_seconds)
    after = run(nested_ssh(args, "qstat", "-f", validate_job_id(args.job_id)), check=False)
    verification = classify_qstat_evidence(after)
    record_present = verification["record_present"]
    cleared = bool(
        qdel_outcome["status"] in {"success", "unknown_job_id"}
        and verification["status"] == "absent"
    )
    cleanup = {
        "schema": "pbs-zombie-cleanup/1",
        "project": args.project,
        "job_id": args.job_id,
        "status": "cleared" if cleared else "cleanup_unverified",
        "qdel_issued": True,
        "qdel_returncode": qdel.returncode,
        "qdel_outcome": qdel_outcome["status"],
        "qdel_error": qdel_outcome["error"],
        "verification_outcome": verification["status"],
        "verification_returncode": verification["returncode"],
        "verification_error": verification["error"],
        "scheduler_record_present": record_present,
        "scheduler_record_evidence_status": verification["status"],
        "server_project_files_changed": False,
        "diagnosis": diagnosis,
    }
    update_job(local_dir, last_zombie_diagnosis=diagnosis, scheduler_cleanup=cleanup)
    return cleanup


def command_cleanup_zombie(args) -> None:
    """Automatically qdel one repeatedly proven zombie and verify the record."""

    cleanup = cleanup_zombie_record(args)
    print(json.dumps(cleanup, ensure_ascii=False, indent=2))
    if cleanup["status"] == "not_eligible":
        fail("refusing qdel because repeated observations did not prove a scheduler zombie")
    if cleanup["status"] == "cleanup_unverified":
        fail("qdel was issued once but cleanup could not be verified; do not retry automatically", code=5)


def command_cancel(args) -> None:
    job_id = validate_job_id(args.job_id)
    if not args.local_dir or not args.approval_record or not args.execution_batch_ledger or not args.attempt_id:
        fail(
            "active cancellation requires --local-dir, exact --approval-record, "
            "--execution-batch-ledger, and --attempt-id; --confirmed is not authority"
        )
    local_dir = Path(args.local_dir).expanduser().resolve()
    if (local_dir / "cancellation-intent.json").exists():
        fail(
            "cancellation intent already exists; this job scope is consumed and qdel is "
            "forbidden for every later invocation"
        )
    job = read_job_state(local_dir)
    if job.get("project") is None:
        fail("local job state has no exact project binding")
    project = validate_project(job["project"])
    if job.get("job_id") != job_id or job.get("remote_workdir") != remote_project_dir(project):
        fail("local job state does not match the exact cancellation target")
    ledger_path = Path(args.execution_batch_ledger).expanduser().resolve()
    try:
        ledger = validate_execution_ledger_path(ledger_path)
    except execution_batch.BatchError as exc:
        fail(f"cancellation execution ledger is invalid: {exc}")
    attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == args.attempt_id), None)
    if (
        attempt is None
        or attempt["project"] != project
        or attempt["scheduler_reference"] != job_id
    ):
        fail("cancellation attempt scope does not match project/job ID")
    expected_scope = {
        "operation": "cancel_active_job",
        "project": project,
        "job_id": job_id,
        "local_job_sha256": job["state_sha256"],
        "attempt_id": attempt["attempt_id"],
        "attempt_sha256": canonical_digest(attempt),
    }
    try:
        _, approval, approval_sha256, _ = load_strict_json_with_hash(
            Path(args.approval_record).expanduser(), "exact cancellation approval"
        )
        _exact_fields(
            approval,
            {
                "schema", "approval_id", "approver_identity", "approved_at", "expires_at",
                "decision", "explicit_confirmation", "scope", "revocation", "consumption",
                "authorizations",
            },
            "exact cancellation approval",
        )
        revocation = _exact_fields(
            approval["revocation"], {"revoked", "revoked_at", "reason"},
            "cancellation revocation",
        )
        consumption = _exact_fields(
            approval["consumption"], {"single_use", "consumed"},
            "cancellation consumption",
        )
    except (ValueError, OSError) as exc:
        fail(f"cannot validate exact cancellation approval: {exc}")
    if (
        approval.get("schema") != CANCELLATION_APPROVAL_SCHEMA
        or approval.get("decision") != "approved"
        or approval.get("explicit_confirmation") is not True
        or not isinstance(approval.get("approval_id"), str)
        or not approval["approval_id"].strip()
        or not isinstance(approval.get("approver_identity"), str)
        or not approval["approver_identity"].strip()
        or approval.get("scope") != expected_scope
        or approval.get("authorizations") != {
            "qdel_exact_job": True,
            "retry": False,
            "cleanup": False,
            "delete_server_data": False,
        }
        or revocation != {"revoked": False, "revoked_at": None, "reason": None}
        or consumption != {"single_use": True, "consumed": False}
    ):
        fail("exact cancellation approval scope/authority is invalid")
    try:
        approved_at = execution_batch.parse_time(approval["approved_at"])
        expires_at = execution_batch.parse_time(approval["expires_at"])
    except execution_batch.BatchError as exc:
        fail(f"cancellation approval timestamp is invalid: {exc}")
    now = datetime.now(timezone.utc)
    if approved_at > now or expires_at <= approved_at or now >= expires_at:
        fail("exact cancellation approval is expired or not yet active")
    intent = {
        "schema": "auto-g16-exact-cancellation-intent/1",
        "approval_id": approval["approval_id"],
        "approval_sha256": approval_sha256,
        "approver_identity": approval["approver_identity"],
        "scope": expected_scope,
        "reserved_at": utc_now(),
        "qdel_may_be_issued_at_most_once": True,
        "automatic_retry_authorized": False,
    }
    intent["intent_sha256"] = canonical_digest(intent)
    intent_path = local_dir / "cancellation-intent.json"
    try:
        publish_new_json(intent_path, intent)
    except ValueError:
        fail(
            "cancellation intent already exists or cannot be reserved; qdel is forbidden "
            "for every later invocation of this job scope"
        )
    try:
        update_job(
            local_dir,
            status="cancellation_reserved",
            cancellation_intent_sha256=intent["intent_sha256"],
            cancellation_approval_id=approval["approval_id"],
            qdel_invocation_started=False,
        )
    except Exception as exc:
        fail(
            "cancellation intent was consumed but append-only job-state reservation failed; "
            f"do not issue or retry qdel: {exc}",
            code=5,
        )
    before = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
    before_evidence = classify_qstat_evidence(before)
    if (
        before_evidence["status"] != "present"
        or before_evidence["job_name"] != project
    ):
        classification = (
            "absent_no_qdel" if before_evidence["status"] == "absent"
            else "unknown_no_qdel"
        )
        update_job(
            local_dir,
            status="cancellation_uncertain",
            cancellation_precheck={
                "classification": classification,
                "pbs_evidence": before_evidence,
                "qdel_issued": False,
                "automatic_retry_authorized": False,
            },
        )
        fail(
            "cancellation intent is consumed but exact active-job evidence is absent or unknown; "
            "qdel was not issued and must not be retried automatically",
            code=3,
        )
    update_job(
        local_dir,
        status="cancellation_uncertain",
        qdel_invocation_started=True,
        qdel_invocation_started_at=utc_now(),
    )
    result = run(nested_ssh(args, "qdel", job_id), check=False)
    qdel_outcome = classify_qdel_outcome(result)
    receipt = {
        "schema": "auto-g16-exact-cancellation-receipt/1",
        "approval_id": approval["approval_id"],
        "approval_sha256": approval_sha256,
        "approver_identity": approval["approver_identity"],
        "scope": expected_scope,
        "consumed_at": utc_now(),
        "qdel_issued_once": True,
        "qdel_outcome": qdel_outcome["status"],
        "qdel_returncode": result.returncode,
        "automatic_retry_authorized": False,
    }
    receipt["receipt_sha256"] = canonical_digest(receipt)
    try:
        publish_new_json(local_dir / "cancellation-receipt.json", receipt)
    except ValueError as exc:
        update_job(
            local_dir,
            status="cancellation_uncertain",
            qdel_outcome=qdel_outcome,
            cancellation_receipt_publication_failed=True,
        )
        fail(
            "qdel was invoked once but immutable outcome receipt publication failed; "
            f"the prior intent forbids every resend: {exc}",
            code=5,
        )
    update_job(
        local_dir,
        status="cancel_requested" if qdel_outcome["status"] == "success" else "cancellation_uncertain",
        cancel_requested=True,
        cancellation_receipt_sha256=receipt["receipt_sha256"],
        qdel_outcome=qdel_outcome,
    )
    print(json.dumps({
        "cancel_requested": qdel_outcome["status"] == "success",
        "job_id": job_id,
        "qdel_outcome": qdel_outcome,
        "automatic_retry_authorized": False,
    }))
    if qdel_outcome["status"] != "success":
        fail("qdel outcome is uncertain; the consumed cancellation intent forbids retry", code=5)


def command_reconcile_cancellation(args) -> None:
    """Read one exact PBS record after a consumed intent; never issue qdel."""

    job_id = validate_job_id(args.job_id)
    local_dir = Path(args.local_dir).expanduser().resolve()
    job = read_job_state(local_dir)
    project = validate_project(str(job.get("project", "")))
    if job.get("job_id") != job_id or job.get("remote_workdir") != remote_project_dir(project):
        fail("cancellation reconciliation differs from the exact local job scope")
    intent_path = local_dir / "cancellation-intent.json"
    try:
        intent = load_strict_json(intent_path)
    except (OSError, ValueError) as exc:
        fail(f"cancellation reconciliation requires the immutable intent: {exc}")
    scope = intent.get("scope")
    if (
        intent.get("schema") != "auto-g16-exact-cancellation-intent/1"
        or not isinstance(scope, dict)
        or scope.get("project") != project
        or scope.get("job_id") != job_id
        or intent.get("intent_sha256") != canonical_digest(
            {key: value for key, value in intent.items() if key != "intent_sha256"}
        )
    ):
        fail("immutable cancellation intent hash/scope is invalid")
    result = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
    evidence = classify_qstat_evidence(result)
    if evidence["status"] == "present" and evidence["job_name"] == project:
        classification = "active"
    elif evidence["status"] == "absent":
        classification = "absent"
    else:
        classification = "unknown"
    report = {
        "schema": "auto-g16-exact-cancellation-reconciliation/1",
        "project": project,
        "job_id": job_id,
        "intent_sha256": intent["intent_sha256"],
        "classification": classification,
        "pbs_evidence": evidence,
        "remote_read_only": True,
        "qdel_issued": False,
        "automatic_retry_authorized": False,
        "observed_at": utc_now(),
    }
    report["evidence_sha256"] = canonical_digest(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mac-ssh-config", default=str(DEFAULT_MAC_SSH_CONFIG))
    parser.add_argument("--rtwin-alias", default=DEFAULT_RTWIN_ALIAS)
    parser.add_argument("--windows-root", default=DEFAULT_WINDOWS_ROOT)
    parser.add_argument("--windows-server-config", default=DEFAULT_WINDOWS_SERVER_CONFIG)
    parser.add_argument("--server-alias", default=DEFAULT_SERVER_ALIAS)


def add_scientific_maturity_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scientific-maturity", help="immutable maturity gate /1 or /2; /1 is historical replay-only for protected live work")
    parser.add_argument("--edge-id", help="reviewed mechanism edge bound by the maturity gate")
    parser.add_argument("--node-id", help="exact reviewed calculation-DAG node for this protected action")
    parser.add_argument("--pilot", action="store_true", help="limit this TS action to the reviewed one-candidate simple-tier pilot")
    parser.add_argument("--work-kind", choices=["ordinary", "minimum", "ts_pilot", "formal_ts", "ts_scan", "irc_forward", "irc_reverse", "endpoint_reopt"], help="explicit scientific work classification; required for every live submission (dry-run may report it missing)")
    parser.add_argument("--scientific-action-authorization", help="exact offline input/project/node/budget binding required for protected submission; it is not live approval")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    finalize_review = sub.add_parser("finalize-input-review", help="finalize one generic exact input-draft review /2 without live action")
    finalize_review.add_argument("draft")
    finalize_review.add_argument("--output", required=True)
    finalize_review.set_defaults(func=command_finalize_input_review)

    build_approval = sub.add_parser("build-input-approval", help="bind protocol selection, exact input review, and exact input into one non-authorizing receipt")
    build_approval.add_argument("input")
    build_approval.add_argument("--protocol-options", required=True)
    build_approval.add_argument("--protocol-selection", required=True)
    build_approval.add_argument("--input-review", required=True)
    build_approval.add_argument("--open-shell-state-review", help="accepted main-group open-shell electronic-state review")
    build_approval.add_argument("--open-shell-input-handoff", help="owner-validated minimum Opt/Freq input handoff")
    build_approval.add_argument("--open-shell-input-audit", help="passed owner input audit for the exact handoff bytes")
    build_approval.add_argument("--receipt-id", required=True)
    build_approval.add_argument("--output", required=True)
    build_approval.set_defaults(func=command_build_input_approval)

    validate_approval = sub.add_parser("validate-input-approval", help="replay one generic exact input-approval receipt without live action")
    validate_approval.add_argument("receipt")
    validate_approval.set_defaults(func=command_validate_input_approval)

    preflight = sub.add_parser("preflight", help="audit a local Gaussian input without network access")
    preflight.add_argument("input")
    preflight.add_argument("--project", required=True)
    add_scientific_maturity_options(preflight)
    preflight.set_defaults(func=command_preflight)

    stage_parser = sub.add_parser("stage", help="create a local PBS bundle without network access")
    stage_parser.add_argument("input")
    stage_parser.add_argument("--project", required=True)
    stage_parser.add_argument("--local-dir", required=True)
    stage_parser.set_defaults(func=command_stage)

    submit = sub.add_parser("submit", help="stage, verify, transfer, and qsub exactly once")
    submit.add_argument("input")
    submit.add_argument("--project", required=True)
    submit.add_argument("--local-dir", required=True)
    submit.add_argument("--confirmed", action="store_true")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--execution-batch-ledger", help="protected gaussian-execution-batch/3 ledger; /2 is historical replay-only")
    submit.add_argument("--scientific-task-id", help="stable reviewed scientific task identity")
    submit.add_argument("--idempotency-key", help="operator-generated stable key for this physical attempt")
    submit.add_argument("--estimated-core-hours", type=float, help="attempt estimate bound into the ledger and approval")
    submit.add_argument("--estimated-core-hours-evidence-source", help="non-empty source identifier for the estimate")
    submit.add_argument("--estimated-core-hours-evidence-sha256", help="lowercase SHA-256 of the estimate evidence")
    submit.add_argument("--resource-policy", help="exact reviewed gaussian-execution-resource-policy/1")
    submit.add_argument("--resource-gate", help="fresh exact gaussian-execution-resource-gate/2")
    submit.add_argument("--scheduler-resource-snapshot", help="exact fresh scheduler resource snapshot bound by the gate")
    submit.add_argument("--resource-tier", help="explicit reviewed tier; never inferred from chemistry")
    submit.add_argument("--resource-cores", type=int, help="explicit reviewed cores; must equal %nprocshared")
    submit.add_argument("--resource-memory-gb", type=int, help="explicit reviewed memory; must equal %mem")
    submit.add_argument("--walltime-seconds", type=int, help="explicit reviewed PBS walltime")
    submit.add_argument(
        "--approval-record",
        help=(
            "resource-bound one-time live approval /9 for receipt /1, /10 for owner-replayed "
            "open-shell receipt /2, or /11 for one family-stage receipt /3; /6-/8 are historical replay only"
        ),
    )
    submit.add_argument(
        "--input-approval-record",
        help=(
            f"owner-validated {INPUT_APPROVAL_SCHEMA} for ordinary/closed-shell minimum, "
            f"or fully replayed {OPEN_SHELL_INPUT_APPROVAL_SCHEMA} for legacy open-shell minimum, "
            f"or {OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA} for one two-stage family member"
        ),
    )
    add_scientific_maturity_options(submit)
    add_connection_options(submit)
    submit.set_defaults(func=command_submit)

    reconcile = sub.add_parser(
        "reconcile-submission",
        help="read remote intent/receipt and exact qstat bindings without qsub or retry",
    )
    reconcile.add_argument("--project", required=True)
    reconcile.add_argument("--local-dir", required=True)
    reconcile.add_argument("--execution-batch-ledger", required=True)
    reconcile.add_argument("--attempt-id", required=True)
    add_connection_options(reconcile)
    reconcile.set_defaults(func=command_reconcile_submission)

    status = sub.add_parser("status", help="query an active PBS job")
    status.add_argument("--job-id")
    status.add_argument("--project")
    add_connection_options(status)
    status.set_defaults(func=command_status)

    batch_status = sub.add_parser("batch-status", help="query the complete active user scope with one read-only qstat call")
    batch_status.add_argument("--job-id", dest="job_ids", action="append", help="optional exact ledger job expected in the complete scope")
    add_connection_options(batch_status)
    batch_status.set_defaults(func=command_batch_status)

    tail = sub.add_parser("tail", help="read the end of a Gaussian log")
    tail.add_argument("--project", required=True)
    tail.add_argument("--input-stem", required=True)
    tail.add_argument("--lines", type=int, default=80)
    add_connection_options(tail)
    tail.set_defaults(func=command_tail)

    fetch = sub.add_parser("fetch", help="create one exact immutable fetch snapshot through RTwin")
    fetch.add_argument("--project", required=True)
    fetch.add_argument("--job-id", required=True)
    fetch.add_argument("--input-stem", required=True)
    fetch.add_argument("--local-dir", required=True)
    fetch.add_argument("--output-dir", required=True)
    fetch.add_argument("--reuse-snapshot", help="prior immutable complete snapshot for hash-verified local reuse")
    add_connection_options(fetch)
    fetch.set_defaults(func=command_fetch)

    inspect_parser = sub.add_parser("inspect", help="combine PBS, process, and log evidence into JSON")
    inspect_parser.add_argument("--project", required=True)
    inspect_parser.add_argument("--job-id", required=True)
    inspect_parser.add_argument("--input-stem", required=True)
    inspect_parser.add_argument("--local-dir")
    inspect_parser.add_argument("--execution-batch-ledger")
    inspect_parser.add_argument("--attempt-id")
    add_connection_options(inspect_parser)
    inspect_parser.set_defaults(func=command_inspect)

    diagnose_zombie_parser = sub.add_parser(
        "diagnose-zombie",
        help="prove a stale PBS R record with two read-only observations",
    )
    diagnose_zombie_parser.add_argument("--project", required=True)
    diagnose_zombie_parser.add_argument("--job-id", required=True)
    diagnose_zombie_parser.add_argument("--input-stem", required=True)
    diagnose_zombie_parser.add_argument("--local-dir", required=True)
    diagnose_zombie_parser.add_argument("--stability-seconds", type=int, default=10)
    add_connection_options(diagnose_zombie_parser)
    diagnose_zombie_parser.set_defaults(func=command_diagnose_zombie)

    cleanup_zombie_parser = sub.add_parser(
        "cleanup-zombie",
        help="automatically qdel one repeatedly proven scheduler zombie",
    )
    cleanup_zombie_parser.add_argument("--project", required=True)
    cleanup_zombie_parser.add_argument("--job-id", required=True)
    cleanup_zombie_parser.add_argument("--input-stem", required=True)
    cleanup_zombie_parser.add_argument("--local-dir", required=True)
    cleanup_zombie_parser.add_argument("--stability-seconds", type=int, default=10)
    cleanup_zombie_parser.add_argument("--verify-seconds", type=int, default=5)
    cleanup_zombie_parser.add_argument(
        "--confirmed", action="store_true", help=argparse.SUPPRESS
    )
    add_connection_options(cleanup_zombie_parser)
    cleanup_zombie_parser.set_defaults(func=command_cleanup_zombie)

    watch = sub.add_parser("watch", help="monitor to a terminal state, then optionally fetch and analyze")
    watch.add_argument("--project", required=True)
    watch.add_argument("--job-id", required=True)
    watch.add_argument("--input-stem", required=True)
    watch.add_argument("--local-dir", required=True)
    watch.add_argument("--output-dir", required=True)
    watch.add_argument("--poll-seconds", type=int, default=30)
    watch.add_argument("--timeout-seconds", type=int, default=86400)
    watch.add_argument("--fetch", action="store_true")
    watch.add_argument("--reuse-snapshot", help="prior immutable complete snapshot for incremental fetch")
    watch.add_argument("--execution-batch-ledger")
    watch.add_argument("--attempt-id")
    watch.add_argument(
        "--no-auto-cleanup-zombie",
        action="store_false",
        dest="auto_cleanup_zombie",
        help="leave a confirmed scheduler-zombie record for manual diagnostics",
    )
    watch.add_argument("--zombie-stability-seconds", type=int, default=10)
    watch.add_argument("--zombie-verify-seconds", type=int, default=5)
    watch.set_defaults(auto_cleanup_zombie=True)
    add_connection_options(watch)
    watch.set_defaults(func=command_watch)

    analyze = sub.add_parser("analyze", help="analyze a fetched Gaussian log locally")
    analyze.add_argument("log")
    analyze.add_argument("--output-dir")
    analyze.set_defaults(func=command_analyze)

    cancel = sub.add_parser("cancel", help="qdel an explicitly approved PBS job")
    cancel.add_argument("--job-id", required=True)
    cancel.add_argument("--confirmed", action="store_true", help=argparse.SUPPRESS)
    cancel.add_argument("--local-dir")
    cancel.add_argument("--approval-record")
    cancel.add_argument("--execution-batch-ledger")
    cancel.add_argument("--attempt-id")
    add_connection_options(cancel)
    cancel.set_defaults(func=command_cancel)

    reconcile_cancel = sub.add_parser(
        "reconcile-cancellation",
        help="classify the exact job active/absent/unknown after a consumed cancellation intent",
    )
    reconcile_cancel.add_argument("--job-id", required=True)
    reconcile_cancel.add_argument("--local-dir", required=True)
    add_connection_options(reconcile_cancel)
    reconcile_cancel.set_defaults(func=command_reconcile_cancellation)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted", code=130)
