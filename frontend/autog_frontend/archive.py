"""Read an explicitly pinned offline archive index; never parse or fetch on GET.

Archives are not Core Projects/Tasks/Attempts. This module has no Store writer,
network client, scheduler or scientific acceptance operation.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat

from auto_g16.query import QueryError
from .parser_contract import qualified_parser

SCHEMA = "auto-g16-legacy-archive/1"
LOCAL_SCHEMA = "auto-g16-legacy-archive/2"
LOG_LIMIT = 32 * 1024 * 1024
PARSE_LIMIT = 64 * 1024 * 1024
LIMIT = 4 * 1024 * 1024
AUTHORITY = {"core_attempt": "unavailable", "live_state": "unavailable",
             "scientific_acceptance": "unavailable", "review": "unavailable"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _fingerprint(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def read_pinned(path: Path, digest: str, *, limit: int = LIMIT) -> bytes:
    """No links, special files, oversized files or changing snapshots."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("canonical absolute index required")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("invalid index file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if _fingerprint(before) != _fingerprint(opened):
            raise ValueError("index changed")
        raw = handle.read(limit + 1)
        if (_fingerprint(opened) != _fingerprint(os.fstat(handle.fileno()))
                or _fingerprint(opened) != _fingerprint(path.lstat())):
            raise ValueError("index changed")
    if len(raw) > limit or sha256(raw).hexdigest() != digest:
        raise ValueError("index digest mismatch")
    return raw


def validate_index(data):
    if not isinstance(data, dict) or set(data) != {"schema", "records"} or data["schema"] not in (SCHEMA, LOCAL_SCHEMA):
        raise ValueError("unsupported index")
    records = data["records"]
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("invalid record list")
    seen = set()
    for r in records:
        if not isinstance(r, dict) or set(r) != {
            "archive_id", "title", "source_kind", "source_location", "captured_at",
            "artifacts", "input", "legacy_metadata", "parser", "summary", "authority",
        }:
            raise ValueError("invalid archive record")
        identity = r["archive_id"]
        if not isinstance(identity, str) or not re.fullmatch(r"archive-[0-9a-f]{64}", identity) or identity in seen:
            raise ValueError("invalid archive identity")
        seen.add(identity)
        local = data["schema"] == LOCAL_SCHEMA and r["source_kind"] == "local_log_archive"
        if (r["source_kind"] != "legacy_archive" and not local) or r["authority"] != AUTHORITY:
            raise ValueError("invalid authority")
        if any(not isinstance(r[k], str) or not r[k] or len(r[k]) > 512 for k in ("title", "source_location", "captured_at")):
            raise ValueError("invalid text field")
        artifacts = r["artifacts"]
        if not isinstance(artifacts, list) or len(artifacts) != (1 if local else 3):
            raise ValueError("expected log, input and legacy metadata")
        roles = set()
        for a in artifacts:
            if not isinstance(a, dict) or set(a) != {"role", "logical_name", "sha256", "size_bytes"}:
                raise ValueError("invalid artifact")
            if a["role"] not in ({"log"} if local else {"log", "input", "legacy_metadata"}) or a["role"] in roles:
                raise ValueError("invalid artifact roles")
            roles.add(a["role"])
            if not isinstance(a["logical_name"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", a["logical_name"]) or a["logical_name"] in {".", ".."}:
                raise ValueError("invalid logical name")
            if not isinstance(a["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", a["sha256"]):
                raise ValueError("invalid artifact hash")
            if type(a["size_bytes"]) is not int or not 0 <= a["size_bytes"] <= (LOG_LIMIT if local else 1024 * 1024):
                raise ValueError("invalid artifact size")
        log = next(a for a in artifacts if a["role"] == "log")
        if identity != "archive-" + log["sha256"]:
            raise ValueError("identity does not match log")
        if local:
            if r["input"] is not None or r["legacy_metadata"] is not None:
                raise ValueError("local logs must not claim input or historical binding")
        else:
            inp = r["input"]
            if (not isinstance(inp, dict) or set(inp) != {"text", "binding"}
                    or inp["binding"] != "legacy-job-input-hash-matched"
                    or not isinstance(inp["text"], str) or len(inp["text"]) > 65536):
                raise ValueError("invalid input")
            input_artifact = next(a for a in artifacts if a["role"] == "input")
            if sha256(inp["text"].encode("utf-8")).hexdigest() != input_artifact["sha256"]:
                raise ValueError("input hash mismatch")
            legacy = r["legacy_metadata"]
            if (not isinstance(legacy, dict) or set(legacy) != {"schema", "recorded_status", "scope"}
                    or legacy["schema"] != "codex-gaussian-pbs/1"
                    or legacy["scope"] != "historical-sidecar-claim"
                    or not isinstance(legacy["recorded_status"], str)):
                raise ValueError("invalid historical claim")
        parser = r["parser"]
        if (not isinstance(parser, dict) or set(parser) != {"name", "version", "status", "diagnostics"}
                or not qualified_parser(parser["name"], parser["version"])
                or parser["status"] not in {"parsed", "partial", "unparseable", "unsupported"}
                or not isinstance(parser["diagnostics"], list)
                or not all(isinstance(s, str) for s in parser["diagnostics"])):
            raise ValueError("unsupported parser")
        s = r["summary"]
        if parser["status"] != "parsed":
            if s is not None:
                raise ValueError("unparsed summary")
            continue
        if not isinstance(s, dict) or set(s) != {"termination", "normal_count", "error_count", "energy_hartree", "optimization", "stationary_point", "frequency_count", "imaginary_count"}:
            raise ValueError("invalid summary")
        if s["termination"] not in {"normal-termination", "error-termination", "no-terminal-marker"}:
            raise ValueError("invalid termination")
        if any(type(s[k]) is not bool for k in ("optimization", "stationary_point")):
            raise ValueError("invalid marker")
        if any(type(s[k]) is not int or s[k] < 0 for k in ("normal_count", "error_count")):
            raise ValueError("invalid count")
        e = s["energy_hartree"]
        if e is not None and (type(e) not in (float, int) or not math.isfinite(e)):
            raise ValueError("invalid energy")
        n, im = s["frequency_count"], s["imaginary_count"]
        if not (n is None and im is None) and not (type(n) is int and n > 0 and type(im) is int and 0 <= im <= n):
            raise ValueError("invalid frequency coverage")
    return data


class ArchiveQuery:
    def __init__(self, index: Path | None, digest: str | None):
        if (index is None) != (digest is None):
            raise ValueError("archive index and SHA-256 must be supplied together")
        if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid archive SHA-256")
        self.index, self.digest = index, digest

    def _read(self):
        if self.index is None:
            return {"schema": SCHEMA, "records": []}
        try:
            return validate_index(json.loads(read_pinned(self.index, self.digest), object_pairs_hook=_object,
                                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON"))))
        except OSError:
            raise QueryError("store-unavailable") from None
        except (ValueError, TypeError, KeyError, StopIteration, RecursionError):
            raise QueryError("invalid-evidence") from None

    def list_archives(self):
        data = self._read()
        return {"schema": data["schema"], "kind": "archives", "configured": self.index is not None,
                "items": [{k: r[k] for k in ("archive_id", "title", "source_kind", "source_location", "captured_at", "parser", "summary", "authority")} for r in data["records"]]}

    def get_archive(self, archive_id):
        data = self._read()
        for record in data["records"]:
            if record["archive_id"] == archive_id:
                return {"schema": data["schema"], "kind": "archive", "data": record}
        raise QueryError("not-found")
