#!/usr/bin/env python3
"""Load non-secret, machine-local Auto-G16 runtime paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(
    os.environ.get(
        "AUTO_G16_RUNTIME_CONFIG",
        str(Path.home() / ".config" / "auto-g16" / "runtime.json"),
    )
).expanduser()


def load() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Auto-G16 runtime config must be a JSON object: {CONFIG_PATH}")
    return value


VALUES = load()


def setting(env_name: str, key: str, default: str) -> str:
    value = os.environ.get(env_name, VALUES.get(key, default))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Auto-G16 runtime setting {key!r} must be a non-empty string")
    return value
