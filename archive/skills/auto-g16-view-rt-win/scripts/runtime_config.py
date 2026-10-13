#!/usr/bin/env python3
"""Strict, self-contained loader for machine-local Auto-G16 runtime paths."""

from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path, PureWindowsPath
from typing import Any

ALLOWED_KEYS = {
    "core_python", "rdkit_python", "chemdraw_pipeline_scripts", "rtwin_ssh_config",
    "windows_target", "windows_control_socket", "windows_project_root",
    "windows_server_config", "gaussview_exe",
}
POSIX_KEYS = {"core_python", "rdkit_python", "chemdraw_pipeline_scripts", "rtwin_ssh_config", "windows_control_socket"}
WINDOWS_KEYS = {"windows_project_root", "gaussview_exe"}


def _constant(token: str) -> Any:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {token}")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _validate(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Auto-G16 runtime config must be a JSON object")
    unknown = sorted(set(value) - ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"Auto-G16 runtime config contains unknown keys: {unknown}")
    result: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(raw, str) or not raw or raw != raw.strip() or "\x00" in raw:
            raise ValueError(f"Auto-G16 runtime setting {key!r} must be a non-empty trimmed string")
        if key in POSIX_KEYS and not Path(raw).is_absolute():
            raise ValueError(f"Auto-G16 runtime setting {key!r} must be an absolute POSIX path")
        if key in WINDOWS_KEYS and not PureWindowsPath(raw).is_absolute():
            raise ValueError(f"Auto-G16 runtime setting {key!r} must be an absolute Windows path")
        if key == "windows_server_config":
            candidate = PureWindowsPath(raw)
            if not candidate.is_absolute() and ".." in candidate.parts:
                raise ValueError("windows_server_config must be absolute or home-relative without parent traversal")
        result[key] = raw
    return result


def _config_path() -> Path:
    raw = os.environ.get("AUTO_G16_RUNTIME_CONFIG")
    path = Path(raw).expanduser() if raw else Path.home() / ".config" / "auto-g16" / "runtime.json"
    if not path.is_absolute():
        raise ValueError("AUTO_G16_RUNTIME_CONFIG must resolve to an absolute path")
    return path


def _read_nofollow(path: Path) -> str | None:
    parts = path.parts[1:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Auto-G16 runtime config path is unsafe: {path}")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path.anchor, directory_flags)
    try:
        for part in parts[:-1]:
            try:
                next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            except FileNotFoundError:
                return None
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ValueError(f"Auto-G16 runtime config path contains a symlink or non-directory: {path}") from exc
                raise
            os.close(descriptor); descriptor = next_descriptor
        try:
            leaf = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=descriptor)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ValueError(f"Auto-G16 runtime config must not be a symlink: {path}") from exc
            raise
        try:
            if not stat.S_ISREG(os.fstat(leaf).st_mode):
                raise ValueError(f"Auto-G16 runtime config must be a regular file: {path}")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(leaf, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8")
        finally:
            os.close(leaf)
    finally:
        os.close(descriptor)


def load() -> dict[str, str]:
    raw = _read_nofollow(_config_path())
    if raw is None:
        return {}
    return _validate(json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant))


CONFIG_PATH = _config_path()
VALUES = load()


def setting(env_name: str, key: str, default: str) -> str:
    value = os.environ.get(env_name, VALUES.get(key, default))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Auto-G16 runtime setting {key!r} must be a non-empty string")
    return value
