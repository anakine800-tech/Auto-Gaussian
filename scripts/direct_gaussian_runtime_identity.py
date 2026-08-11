#!/usr/bin/env python3
"""Closed absolute Gaussian executable identity and PBS handoff owner.

Portable documents produced here are splice evidence only.  They never grant
apply, effect, live, or execution authority, and an open descriptor is never
claimed to survive the qsub/PBS boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
import types
from pathlib import Path
from typing import Any


SCHEMA = "auto-g16-direct-gaussian-runtime-binding/1"
OWNER = "auto-g16-direct-gaussian-runtime-identity-owner"
OWNER_VERSION = "direct-gaussian-runtime-identity/1"
INPUT_BASENAME = "approved-input.gjf"
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")


class DirectGaussianRuntimeIdentityError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectGaussianRuntimeIdentityError(message)


def _owner_source_snapshot() -> tuple[Path, tuple[int, ...], str]:
    path = Path(os.path.abspath(__file__))
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_uid, before.st_gid,
                before.st_mode, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    _require(
        stat.S_ISREG(before.st_mode)
        and identity == (after.st_dev, after.st_ino, after.st_uid, after.st_gid,
                         after.st_mode, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        "Gaussian owner source identity differs",
    )
    raw = b"".join(chunks)
    _require(len(raw) == before.st_size, "Gaussian owner source size differs")
    return path, identity, hashlib.sha256(raw).hexdigest()


def assert_reviewed_module_binding() -> None:
    _assert_owner_module_binding()


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DirectGaussianRuntimeIdentityError("Gaussian binding is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and SHA_RE.fullmatch(value) is not None and value != ZERO_SHA,
             f"{label} differs")
    return value


def _absolute(value: Any) -> str:
    _require(type(value) is str and value.startswith("/") and "//" not in value
             and not value.endswith("/")
             and re.fullmatch(r"/[A-Za-z0-9._+@%/-]+", value) is not None
             and all(part not in {"", ".", ".."} for part in value.split("/")[1:]),
             "Gaussian executable must be one canonical absolute path")
    return value


def _component_paths(path: str) -> tuple[Path, ...]:
    current = Path("/")
    result = []
    for part in Path(path).parts[1:]:
        current /= part
        result.append(current)
    return tuple(result)


def _open_component_chain(path: str) -> tuple[tuple[int, Path, os.stat_result], ...]:
    """Open every component relative to its already-open parent, never by full path."""
    opened: list[tuple[int, Path, os.stat_result]] = []
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        current = Path("/")
        parts = Path(path).parts[1:]
        for ordinal, part in enumerate(parts):
            current /= part
            final = ordinal == len(parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            if not final:
                flags |= os.O_DIRECTORY
            descriptor = os.open(part, flags, dir_fd=parent)
            info = os.fstat(descriptor)
            _require(stat.S_ISREG(info.st_mode) if final else stat.S_ISDIR(info.st_mode),
                     "Gaussian path component type differs")
            opened.append((descriptor, current, info))
            if not final:
                os.close(parent)
                parent = os.dup(descriptor)
        return tuple(opened)
    except BaseException:
        for descriptor, _path, _info in opened:
            os.close(descriptor)
        raise
    finally:
        os.close(parent)


def _read_descriptor(descriptor: int) -> tuple[os.stat_result, bytes]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    before = os.fstat(descriptor)
    chunks = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(descriptor)
    _require((before.st_dev, before.st_ino, before.st_uid, before.st_gid, before.st_mode,
              before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
             == (after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_mode,
                 after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
             "Gaussian executable identity changed while observed")
    return before, b"".join(chunks)


def observe_reviewed_gaussian_executable(path: str, *, expected_uid: int,
                                         expected_gid: int, expected_mode: int) -> dict[str, Any]:
    """Read-only owner observation for one already reviewed absolute candidate."""
    _assert_owner_module_binding()
    canonical = _absolute(path)
    _require(type(expected_uid) is int and expected_uid >= 0 and type(expected_gid) is int
             and expected_gid >= 0 and type(expected_mode) is int
             and 0 < expected_mode <= 0o7777 and expected_mode & 0o111 != 0,
             "reviewed Gaussian owner or executable mode differs")
    components = []
    opened = _open_component_chain(canonical)
    try:
        for ordinal, (_descriptor, component, info) in enumerate(opened):
            components.append({
            "ordinal": ordinal,
            "path": str(component),
            "device": str(info.st_dev),
            "inode": str(info.st_ino),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": format(stat.S_IMODE(info.st_mode), "04o"),
            "type": "directory" if ordinal < len(opened) - 1 else "regular_executable",
            })
        final, raw = _read_descriptor(opened[-1][0])
    finally:
        for descriptor, _path, _info in opened:
            os.close(descriptor)
    _require(final.st_uid == expected_uid and final.st_gid == expected_gid
             and stat.S_IMODE(final.st_mode) == expected_mode
             and final.st_nlink == 1 and final.st_mode & 0o111 != 0,
             "Gaussian final owner, mode, link count, or executability differs")
    document = {
        "schema": SCHEMA,
        "owner": {"owner_id": OWNER, "owner_version": OWNER_VERSION},
        "executable": {
            "canonical_absolute_path": canonical,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "uid": expected_uid,
            "gid": expected_gid,
            "mode": format(expected_mode, "04o"),
            "link_count": 1,
        },
        "component_identity_chain": components,
        "invocation": {"argv": [canonical, INPUT_BASENAME], "shell": False,
                       "path_lookup": False, "caller_override": False},
        "pbs_boundary": {
            "descriptor_survives_qsub": False,
            "absolute_path_contract_required": True,
            "administrator_execution_time_reobservation_required": True,
            "post_install_reobservation_required": True,
        },
        "authority": {"authorizes_apply": False, "authorizes_effect": False,
                      "authorizes_live": False, "portable_projection_is_authority": False},
        "binding_payload_sha256": "",
    }
    document["binding_payload_sha256"] = digest(document)
    return validate_gaussian_runtime_binding(document)


def validate_gaussian_runtime_binding(value: Any) -> dict[str, Any]:
    _assert_owner_module_binding()
    _require(type(value) is dict, "Gaussian runtime binding must be an object")
    required = {"schema", "owner", "executable", "component_identity_chain", "invocation",
                "pbs_boundary", "authority", "binding_payload_sha256"}
    _require(set(value) == required, "Gaussian runtime binding fields differ")
    document = copy.deepcopy(value)
    _require(document["schema"] == SCHEMA and document["owner"] == {
        "owner_id": OWNER, "owner_version": OWNER_VERSION}, "Gaussian runtime owner differs")
    executable = document["executable"]
    _require(type(executable) is dict and set(executable) == {
        "canonical_absolute_path", "sha256", "uid", "gid", "mode", "link_count"},
        "Gaussian executable fields differ")
    path = _absolute(executable["canonical_absolute_path"])
    _sha(executable["sha256"], "Gaussian executable SHA-256")
    _require(type(executable["uid"]) is int and executable["uid"] >= 0
             and type(executable["gid"]) is int and executable["gid"] >= 0
             and type(executable["mode"]) is str and re.fullmatch(r"0[0-7]{3}", executable["mode"])
             and int(executable["mode"], 8) & 0o111 != 0 and executable["link_count"] == 1,
             "Gaussian executable owner or mode differs")
    chain = document["component_identity_chain"]
    paths = _component_paths(path)
    _require(type(chain) is list and len(chain) == len(paths), "Gaussian component chain differs")
    for ordinal, (component, expected_path) in enumerate(zip(chain, paths, strict=True)):
        _require(type(component) is dict and set(component) == {
            "ordinal", "path", "device", "inode", "uid", "gid", "mode", "type"}
            and component["ordinal"] == ordinal and component["path"] == str(expected_path)
            and component["type"] == ("regular_executable" if ordinal == len(paths) - 1 else "directory"),
            "Gaussian component identity chain is not canonical")
        _require(type(component["device"]) is str and re.fullmatch(r"(?:0|[1-9][0-9]*)", component["device"])
                 and type(component["inode"]) is str and re.fullmatch(r"[1-9][0-9]*", component["inode"])
                 and type(component["uid"]) is int and component["uid"] >= 0
                 and type(component["gid"]) is int and component["gid"] >= 0
                 and type(component["mode"]) is str and re.fullmatch(r"0[0-7]{3}", component["mode"]),
                 "Gaussian component identity field differs")
    _require(chain[-1]["uid"] == executable["uid"] and chain[-1]["gid"] == executable["gid"]
             and chain[-1]["mode"] == executable["mode"],
             "Gaussian final chain/executable identity differs")
    _require(document["invocation"] == {"argv": [path, INPUT_BASENAME], "shell": False,
             "path_lookup": False, "caller_override": False}, "Gaussian invocation differs")
    _require(document["pbs_boundary"] == {"descriptor_survives_qsub": False,
             "absolute_path_contract_required": True,
             "administrator_execution_time_reobservation_required": True,
             "post_install_reobservation_required": True}, "Gaussian PBS boundary differs")
    _require(document["authority"] == {"authorizes_apply": False, "authorizes_effect": False,
             "authorizes_live": False, "portable_projection_is_authority": False},
             "Gaussian portable authority differs")
    supplied = _sha(document["binding_payload_sha256"], "Gaussian runtime binding")
    _require(supplied == digest({**document, "binding_payload_sha256": ""}),
             "Gaussian runtime binding hash differs")
    return document


def replay_gaussian_executable_identity(value: Any) -> int:
    """Replay current no-follow identity; return an open FD that the caller must close."""
    _assert_owner_module_binding()
    document = validate_gaussian_runtime_binding(value)
    executable = document["executable"]
    opened = _open_component_chain(executable["canonical_absolute_path"])
    try:
        for (_descriptor, component, info), expected in zip(
                opened, document["component_identity_chain"], strict=True):
            _require(str(component) == expected["path"]
                     and str(info.st_dev) == expected["device"] and str(info.st_ino) == expected["inode"]
                     and info.st_uid == expected["uid"] and info.st_gid == expected["gid"]
                     and format(stat.S_IMODE(info.st_mode), "04o") == expected["mode"],
                     "Gaussian component current identity differs")
        descriptor = opened[-1][0]
        info, raw = _read_descriptor(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == executable["uid"]
                 and info.st_gid == executable["gid"]
                 and format(stat.S_IMODE(info.st_mode), "04o") == executable["mode"]
                 and info.st_nlink == 1 and info.st_mode & 0o111 != 0
                 and hashlib.sha256(raw).hexdigest() == executable["sha256"],
                 "Gaussian final executable currentness differs")
        retained = os.dup(descriptor)
        for opened_descriptor, _path, _info in opened:
            os.close(opened_descriptor)
        opened = ()
        return retained
    except BaseException:
        for descriptor, _path, _info in opened:
            os.close(descriptor)
        raise


_CANONICAL_MODULE = sys.modules.get(__name__)
_EXECUTED_SOURCE_PATH, _EXECUTED_SOURCE_IDENTITY, _EXECUTED_SOURCE_SHA256 = (
    _owner_source_snapshot()
)
_FROZEN_BINDING_ASSERT = assert_reviewed_module_binding
_FROZEN_OBSERVER = observe_reviewed_gaussian_executable
_FROZEN_VALIDATOR = validate_gaussian_runtime_binding
_FROZEN_REPLAY = replay_gaussian_executable_identity


def _assert_owner_module_binding() -> None:
    current_path, current_identity, current_sha256 = _owner_source_snapshot()
    reviewed_sha256 = getattr(_CANONICAL_MODULE, "__reviewed_source_sha256__", None)
    _require(
        type(_CANONICAL_MODULE) is types.ModuleType
        and sys.modules.get(__name__) is _CANONICAL_MODULE
        and current_path == _EXECUTED_SOURCE_PATH
        and current_identity == _EXECUTED_SOURCE_IDENTITY
        and current_sha256 == _EXECUTED_SOURCE_SHA256
        and reviewed_sha256 in {None, _EXECUTED_SOURCE_SHA256}
        and assert_reviewed_module_binding is _FROZEN_BINDING_ASSERT
        and observe_reviewed_gaussian_executable is _FROZEN_OBSERVER
        and validate_gaussian_runtime_binding is _FROZEN_VALIDATOR
        and replay_gaussian_executable_identity is _FROZEN_REPLAY
        and _FROZEN_BINDING_ASSERT.__globals__ is _CANONICAL_MODULE.__dict__
        and _FROZEN_VALIDATOR.__globals__ is _CANONICAL_MODULE.__dict__
        and _FROZEN_REPLAY.__globals__ is _CANONICAL_MODULE.__dict__,
        "Gaussian owner module, source, or function binding differs",
    )
