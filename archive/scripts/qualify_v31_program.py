#!/usr/bin/env python3
"""Inventory supplied local V31 program bytes; never execute or qualify production."""

from __future__ import annotations

import argparse
import base64
from contextlib import AbstractContextManager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_g16.execution._identity import ExecutionValueError, require_positive_integer, require_sha256
from auto_g16.execution._paths import validate_posix_path
from auto_g16.execution.models import _canonical_xtb_runtime_data_manifest


MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * MAX_FILE_BYTES
MAX_ENTRIES = 256
MAX_DEPTH = 32
MAX_VERSION_EVIDENCE_BYTES = 65536


class QualificationError(ValueError):
    """Local evidence is incomplete, inconsistent, or unsafe to inspect."""


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    # Ancestor directory content may change independently of this inventory.
    return (info.st_dev, info.st_ino, info.st_mode)


class _LocalReader(AbstractContextManager):
    """Retain descriptors until all supplied evidence has been rechecked."""

    def __init__(self) -> None:
        if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
            raise QualificationError("descriptor no-follow inspection is unavailable")
        self.flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        self.fds: list[int] = []
        self.bindings: list[tuple[int, str, int, tuple[int, ...], bool]] = []
        self.directories: list[tuple[int, tuple[int, ...], tuple[str, ...]]] = []
        self.total_bytes = 0
        self.entry_count = 0

    def __exit__(self, *_args: object) -> None:
        for fd in reversed(self.fds):
            os.close(fd)

    def _open(self, parent: int, name: str, *, directory: bool) -> int:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        predicate = stat.S_ISDIR if directory else stat.S_ISREG
        if not predicate(before.st_mode):
            raise QualificationError("input must be a regular file or real directory")
        fd = os.open(name, self.flags | (os.O_DIRECTORY if directory else 0), dir_fd=parent)
        self.fds.append(fd)
        opened = os.fstat(fd)
        identity = _directory_identity if directory else _identity
        if identity(before) != identity(opened):
            raise QualificationError("input identity changed while opening")
        self.bindings.append((parent, name, fd, identity(opened), directory))
        return fd

    def open_path(self, path: str, *, directory: bool = False) -> int:
        validate_posix_path(path, "local input path")
        parts = path.split("/")[1:]
        if len(parts) > MAX_DEPTH or path == "/":
            raise QualificationError("local input path is outside the bounded depth")
        parent = os.open("/", self.flags | os.O_DIRECTORY)
        self.fds.append(parent)
        for index, name in enumerate(parts):
            parent = self._open(parent, name, directory=directory or index < len(parts) - 1)
        return parent

    def read_file(self, fd: int, *, limit: int = MAX_FILE_BYTES, retain: bool = False) -> tuple[dict[str, object], bytes]:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise QualificationError("input file is empty, irregular, or exceeds its byte cap")
        self.entry_count += 1
        self.total_bytes += before.st_size
        if self.entry_count > MAX_ENTRIES or self.total_bytes > MAX_TOTAL_BYTES:
            raise QualificationError("local inventory exceeds its bounded budget")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise QualificationError("input file was truncated during inspection")
            remaining -= len(chunk)
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
        if os.read(fd, 1) or _identity(before) != _identity(os.fstat(fd)):
            raise QualificationError("input file changed during inspection")
        return {"size_bytes": before.st_size, "sha256": digest.hexdigest()}, b"".join(chunks)

    def inventory(self, fd: int, prefix: str = "", depth: int = 0) -> dict[str, object]:
        if depth > MAX_DEPTH:
            raise QualificationError("runtime-data tree exceeds its bounded depth")
        before = _identity(os.fstat(fd))
        names = tuple(sorted(os.listdir(fd)))
        self.directories.append((fd, before, names))
        files: dict[str, object] = {}
        for name in names:
            if name in {".", ".."} or "/" in name or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
                raise QualificationError("runtime-data entry name is not canonical")
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            relative = prefix + name
            if stat.S_ISDIR(info.st_mode):
                self.entry_count += 1
                if self.entry_count > MAX_ENTRIES:
                    raise QualificationError("runtime-data inventory exceeds its entry cap")
                child = self._open(fd, name, directory=True)
                files.update(self.inventory(child, relative + "/", depth + 1))
            elif stat.S_ISREG(info.st_mode):
                child = self._open(fd, name, directory=False)
                files[relative], _ = self.read_file(child)
            else:
                raise QualificationError("runtime-data entries must not be symlinks or special files")
        return files

    def verify(self) -> None:
        for parent, name, fd, expected, directory in self.bindings:
            identity = _directory_identity if directory else _identity
            if identity(os.fstat(fd)) != expected or identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected:
                raise QualificationError("input path or content changed before inventory completion")
        for fd, expected, names in self.directories:
            if _identity(os.fstat(fd)) != expected or tuple(sorted(os.listdir(fd))) != names:
                raise QualificationError("runtime-data directory inventory changed during inspection")


def _closed_json(raw: bytes) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise QualificationError("version evidence contains duplicate keys")
            value[key] = item
        return value

    def nonfinite(_value: str) -> None:
        raise QualificationError("version evidence contains non-finite values")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    fields = {"schema", "kind", "binary_identity", "reported_version", "captured_at", "stdout_base64", "stderr_base64"}
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != "auto-g16-v31-captured-version-claim/1":
        raise QualificationError("version evidence must use the exact captured-claim schema")
    return value


def _version_claim(raw: bytes, kind: str, binary: dict[str, object]) -> dict[str, object]:
    value = _closed_json(raw)
    identity = value["binary_identity"]
    if not isinstance(identity, dict) or set(identity) != {"canonical_path", "size_bytes", "sha256"}:
        raise QualificationError("captured binary identity is not closed")
    validate_posix_path(identity["canonical_path"], "captured binary path")
    require_positive_integer(identity["size_bytes"], "captured binary size")
    require_sha256(identity["sha256"], "captured binary SHA-256")
    if value["kind"] != kind or identity != binary:
        raise QualificationError("captured claim is not bound to this local binary identity")
    version = value["reported_version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise QualificationError("captured reported_version is not an exact version token")
    if kind == "crest" and version != "3.0.2":
        raise QualificationError("CREST requires exactly reported version 3.0.2; claim rejected")
    captured_at = value["captured_at"]
    if not isinstance(captured_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", captured_at):
        raise QualificationError("captured_at must be an exact UTC timestamp")
    datetime.strptime(captured_at, "%Y-%m-%dT%H:%M:%SZ")
    streams: dict[str, object] = {}
    texts: list[str] = []
    for name in ("stdout", "stderr"):
        encoded = value[name + "_base64"]
        if not isinstance(encoded, str):
            raise QualificationError("captured streams must be canonical base64")
        content = base64.b64decode(encoded, validate=True)
        if base64.b64encode(content).decode("ascii") != encoded or len(content) > 32768:
            raise QualificationError("captured stream is non-canonical or oversized")
        texts.append(content.decode("utf-8"))
        streams[name] = {"size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    if not any(re.search(r"(?<![A-Za-z0-9.+-])" + re.escape(version) + r"(?![A-Za-z0-9.+-])", text) for text in texts):
        raise QualificationError("reported version token is absent from captured output")
    return {
        "version": version,
        "version_verification": "UNVERIFIED_CAPTURED_CLAIM",
        "version_evidence": {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                             "claimed_captured_at": captured_at, "streams": streams,
                             "capture_authenticity_verified": False},
    }


def qualify_program(*, kind: str, path: str, runtime_data: str | None = None, version_evidence: str | None = None) -> dict[str, object]:
    if kind not in {"xtb", "crest"} or (kind == "xtb") != (runtime_data is not None):
        raise QualificationError("xTB requires runtime-data; CREST must not supply it")
    with _LocalReader() as reader:
        binary_fd = reader.open_path(path)
        binary, _ = reader.read_file(binary_fd)
        binary = {"canonical_path": path, **binary}
        data_report = None
        if runtime_data is not None:
            data_fd = reader.open_path(runtime_data, directory=True)
            files = reader.inventory(data_fd)
            manifest = _canonical_xtb_runtime_data_manifest(json.dumps({
                "schema": "auto-g16-v31-xtb-runtime-data-manifest/1", "files": files,
            }).encode("utf-8"))
            data_report = {"canonical_path": runtime_data, "manifest": json.loads(manifest),
                           "manifest_canonical_utf8": manifest.decode("utf-8"),
                           "manifest_size_bytes": len(manifest), "manifest_sha256": hashlib.sha256(manifest).hexdigest()}
        version: dict[str, object] = {"version": None, "version_verification": "UNVERIFIED_PROBE_DEFERRED", "version_evidence": None}
        if version_evidence is not None:
            evidence_fd = reader.open_path(version_evidence)
            _, raw = reader.read_file(evidence_fd, limit=MAX_VERSION_EVIDENCE_BYTES, retain=True)
            version = _version_claim(raw, kind, binary)
        reader.verify()
        return {
            "schema": "auto-g16-v31-local-program-inventory/1",
            "status": "LOCAL_CONTENT_INVENTORY_COMPLETE", "kind": kind,
            **binary, **version, "runtime_data": data_report,
            "production_qualification": "UNVERIFIED", "live_authority": False,
            "program_executed": False, "executable_format_verified": False,
            "scope": "supplied local bytes only; no production readiness or ServerProfile authority",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("xtb", "crest"), required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--runtime-data")
    parser.add_argument("--version-evidence")
    args = parser.parse_args(argv)
    try:
        report = qualify_program(kind=args.kind, path=args.path, runtime_data=args.runtime_data, version_evidence=args.version_evidence)
    except (QualificationError, ExecutionValueError, OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"local program inventory rejected: {exc}\n")
    print(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
