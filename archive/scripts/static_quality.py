#!/usr/bin/env python3
"""Run the dependency-free progressive static-quality policy."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "static-quality.json"
SCHEMA = "auto-g16-static-quality/1"
SUPPORTED_RULES = {
    "no-bare-except",
    "no-builtin-eval-exec",
    "no-shell-true",
    "no-star-import",
}


class StaticQualityError(ValueError):
    """The progressive static-quality policy or selected source failed."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StaticQualityError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise StaticQualityError(f"invalid static-quality config: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"schema", "paths", "rules"}:
        raise StaticQualityError("static-quality config must be a closed object")
    if value["schema"] != SCHEMA:
        raise StaticQualityError("unsupported static-quality schema")
    paths = value["paths"]
    rules = value["rules"]
    if not isinstance(paths, list) or not paths or not all(isinstance(item, str) for item in paths):
        raise StaticQualityError("static-quality paths must be a non-empty string array")
    if len(paths) != len(set(paths)):
        raise StaticQualityError("static-quality paths contain duplicates")
    if not isinstance(rules, list) or set(rules) != SUPPORTED_RULES:
        raise StaticQualityError("static-quality rules must list the supported progressive rule set")
    return value


def inspect_source(source: str, label: str, rules: set[str]) -> list[str]:
    try:
        tree = ast.parse(source, filename=label)
    except SyntaxError as exc:
        return [f"{label}:{exc.lineno}: syntax error: {exc.msg}"]
    violations: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        if "no-bare-except" in rules and isinstance(node, ast.ExceptHandler) and node.type is None:
            violations.append(f"{label}:{line}: bare except is forbidden")
        if "no-star-import" in rules and isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                violations.append(f"{label}:{line}: star import is forbidden")
        if "no-builtin-eval-exec" in rules and isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                violations.append(f"{label}:{line}: builtin {node.func.id} is forbidden")
        if "no-shell-true" in rules and isinstance(node, ast.Call):
            if any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                violations.append(f"{label}:{line}: shell=True is forbidden")
    return violations


def run(config: dict[str, Any]) -> list[str]:
    rules = set(config["rules"])
    violations: list[str] = []
    for raw in config["paths"]:
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            violations.append(f"{raw}: configured path must be repository-relative")
            continue
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            violations.append(f"{raw}: selected source is missing, non-regular, or a symlink")
            continue
        violations.extend(inspect_source(path.read_text(encoding="utf-8"), raw, rules))
    return violations


def main() -> int:
    try:
        config = load_config()
        violations = run(config)
        if violations:
            for item in violations:
                print(f"ERROR: {item}", file=sys.stderr)
            return 1
        print(f"OK: {len(config['paths'])} progressively selected Python files passed {len(config['rules'])} static rules")
        return 0
    except (StaticQualityError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
