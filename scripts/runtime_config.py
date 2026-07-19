#!/usr/bin/env python3
"""Strictly validate the machine-local Auto-G16 runtime configuration offline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PureWindowsPath
from typing import Any


SCHEMA = "auto-g16-runtime-config/1"
ALLOWED_KEYS = {
    "core_python",
    "rdkit_python",
    "chemdraw_pipeline_scripts",
    "rtwin_ssh_config",
    "windows_target",
    "windows_control_socket",
    "windows_project_root",
    "windows_server_config",
    "gaussview_exe",
}
POSIX_ABSOLUTE_KEYS = {
    "core_python",
    "rdkit_python",
    "chemdraw_pipeline_scripts",
    "rtwin_ssh_config",
    "windows_control_socket",
}
WINDOWS_ABSOLUTE_KEYS = {"windows_project_root", "gaussview_exe"}
WINDOWS_HOME_OR_ABSOLUTE_KEYS = {"windows_server_config"}


class RuntimeConfigError(ValueError):
    """The local runtime configuration is malformed or outside its schema."""


def _reject_constant(value: str) -> None:
    raise RuntimeConfigError(f"non-standard JSON numeric constant is forbidden: {value}")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeConfigError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def validate(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RuntimeConfigError("runtime config must be a JSON object")
    unknown = sorted(set(value) - ALLOWED_KEYS)
    if unknown:
        raise RuntimeConfigError(f"runtime config contains unknown keys: {unknown}")
    normalized: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
            raise RuntimeConfigError(f"runtime config {key!r} must be a non-empty trimmed string")
        if "\x00" in raw:
            raise RuntimeConfigError(f"runtime config {key!r} contains a NUL byte")
        if key in POSIX_ABSOLUTE_KEYS and not Path(raw).is_absolute():
            raise RuntimeConfigError(f"runtime config {key!r} must be an absolute POSIX path")
        if key in WINDOWS_ABSOLUTE_KEYS and not PureWindowsPath(raw).is_absolute():
            raise RuntimeConfigError(f"runtime config {key!r} must be an absolute Windows path")
        if key in WINDOWS_HOME_OR_ABSOLUTE_KEYS:
            candidate = PureWindowsPath(raw)
            if not candidate.is_absolute() and ".." in candidate.parts:
                raise RuntimeConfigError(
                    f"runtime config {key!r} must be an absolute Windows path or a home-relative path without parent traversal"
                )
        normalized[key] = raw
    return normalized


def parse(raw: str, *, label: str = "runtime config") -> dict[str, str]:
    try:
        value = json.loads(
            raw,
            parse_constant=_reject_constant,
            object_pairs_hook=_closed_object,
        )
    except json.JSONDecodeError as exc:
        raise RuntimeConfigError(f"invalid JSON in {label}: {exc}") from exc
    return validate(value)


def default_path(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    raw = environ.get("AUTO_G16_RUNTIME_CONFIG")
    path = Path(raw).expanduser() if raw else home / ".config" / "auto-g16" / "runtime.json"
    if not path.is_absolute():
        raise RuntimeConfigError("AUTO_G16_RUNTIME_CONFIG must resolve to an absolute path")
    return path


def load(path: Path, *, missing_ok: bool = False) -> dict[str, str]:
    path = path.expanduser()
    if not path.is_absolute():
        raise RuntimeConfigError("runtime config path must be absolute")
    if path.is_symlink():
        raise RuntimeConfigError(f"runtime config must not be a symlink: {path}")
    if not path.exists():
        if missing_ok:
            return {}
        raise RuntimeConfigError(f"runtime config is missing: {path}")
    if not path.is_file():
        raise RuntimeConfigError(f"runtime config must be a regular file: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeConfigError(f"could not read runtime config {path}: {exc}") from exc
    return parse(raw, label=str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--json", action="store_true", help="emit a non-secret validation summary")
    args = parser.parse_args(argv)
    try:
        path = args.path or default_path()
        value = load(path)
        summary = {
            "schema": SCHEMA,
            "path": str(path),
            "valid": True,
            "configured_keys": sorted(value),
            "live_actions": False,
        }
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(f"OK: {path} matches {SCHEMA} ({len(value)} configured keys; offline only)")
        return 0
    except (RuntimeConfigError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
