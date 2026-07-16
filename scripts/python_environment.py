#!/usr/bin/env python3
"""Resolve, validate, and enter the reviewed Auto-G16 Python profiles."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "python-environments.json"
PACKAGE_IMPORTS = {"numpy": "numpy", "Pillow": "PIL", "rdkit": "rdkit"}


class EnvironmentError(ValueError):
    """The configured Python environment is missing, ambiguous, or drifted."""


def _reject_constant(value: str) -> None:
    raise EnvironmentError(f"non-standard JSON numeric constant is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EnvironmentError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EnvironmentError(f"invalid JSON configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EnvironmentError(f"JSON configuration must be an object: {path}")
    return value


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "auto-g16-python-environments/1":
        raise EnvironmentError("unsupported Python environment registry schema")
    profiles = value.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"core", "chem"}:
        raise EnvironmentError("Python environment registry must define exactly core and chem")
    if value.get("default_profile") != "core":
        raise EnvironmentError("core must remain the default Python profile")
    for name, profile in profiles.items():
        required = {
            "python_version", "environment_variable", "runtime_config_key",
            "fallback", "requirements", "packages",
        }
        if not isinstance(profile, dict) or set(profile) != required:
            raise EnvironmentError(f"Python profile {name!r} is not a closed object")
        if not isinstance(profile["packages"], dict):
            raise EnvironmentError(f"Python profile {name!r} packages must be an object")
    return value


def runtime_config_path(
    environ: Optional[dict[str, str]] = None, home: Optional[Path] = None
) -> Path:
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    raw = environ.get("AUTO_G16_RUNTIME_CONFIG")
    return Path(raw).expanduser() if raw else home / ".config" / "auto-g16" / "runtime.json"


def load_runtime_config(
    environ: Optional[dict[str, str]] = None, home: Optional[Path] = None
) -> tuple[dict[str, Any], Path]:
    path = runtime_config_path(environ, home)
    if not path.is_file():
        return {}, path
    return load_json(path), path


def resolve_profile(
    name: str,
    *,
    registry: Optional[dict[str, Any]] = None,
    environ: Optional[dict[str, str]] = None,
    home: Optional[Path] = None,
) -> tuple[Path, str]:
    registry = load_registry() if registry is None else registry
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    profiles = registry["profiles"]
    if name not in profiles:
        raise EnvironmentError(f"unknown Python profile: {name}")
    profile = profiles[name]
    runtime, config_path = load_runtime_config(environ, home)
    env_name = profile["environment_variable"]
    config_key = profile["runtime_config_key"]
    if environ.get(env_name):
        raw = environ[env_name]
        source = env_name
    elif runtime.get(config_key):
        raw = runtime[config_key]
        source = f"{config_path}:{config_key}"
    else:
        raw = profile["fallback"]
        source = "version-controlled fallback"
    if not isinstance(raw, str) or not raw.strip():
        raise EnvironmentError(f"Python profile {name!r} path must be a non-empty string")
    if raw.startswith("~/"):
        path = home / raw[2:]
    else:
        path = Path(raw).expanduser()
    if not path.is_absolute():
        raise EnvironmentError(f"Python profile {name!r} must use an absolute interpreter path")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise EnvironmentError(f"Python profile {name!r} is not executable: {path} ({source})")
    return path, source


PROBE = r'''import importlib, json, pathlib, sys
result = {
    "executable": str(pathlib.Path(sys.executable).resolve()),
    "python_version": sys.version.split()[0],
    "pip": {"version": None, "path": None, "error": None},
    "packages": {},
}
try:
    pip = importlib.import_module("pip")
    result["pip"] = {
        "version": getattr(pip, "__version__", None),
        "path": str(pathlib.Path(pip.__file__).resolve()),
        "error": None,
    }
except Exception as exc:
    result["pip"]["error"] = f"{type(exc).__name__}: {exc}"
for distribution, module_name in {"numpy": "numpy", "Pillow": "PIL", "rdkit": "rdkit"}.items():
    try:
        module = importlib.import_module(module_name)
        result["packages"][distribution] = {
            "version": getattr(module, "__version__", None),
            "path": str(pathlib.Path(module.__file__).resolve()),
            "error": None,
        }
    except Exception as exc:
        result["packages"][distribution] = {
            "version": None,
            "path": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
print(json.dumps(result, sort_keys=True))'''


def probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(path), "-c", PROBE],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
        raise EnvironmentError(f"Python probe failed for {path}: {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EnvironmentError(f"Python probe returned invalid JSON for {path}") from exc
    if not isinstance(value, dict):
        raise EnvironmentError(f"Python probe returned an invalid object for {path}")
    return value


def inspect_profile(
    name: str, registry: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    registry = load_registry() if registry is None else registry
    profile = registry["profiles"][name]
    result: dict[str, Any] = {
        "profile": name,
        "expected_python": profile["python_version"],
        "expected_packages": profile["packages"],
        "ok": False,
        "errors": [],
    }
    try:
        path, source = resolve_profile(name, registry=registry)
        result["configured_executable"] = str(path)
        result["source"] = source
        result["runtime"] = probe(path)
    except (EnvironmentError, OSError, subprocess.SubprocessError) as exc:
        result["errors"].append(str(exc))
        return result
    runtime = result["runtime"]
    if runtime.get("python_version") != profile["python_version"]:
        result["errors"].append(
            f"Python version drift: expected {profile['python_version']}, "
            f"found {runtime.get('python_version')}"
        )
    if runtime.get("pip", {}).get("error"):
        result["errors"].append(f"pip unavailable: {runtime['pip']['error']}")
    for package, expected in profile["packages"].items():
        actual = runtime.get("packages", {}).get(package, {})
        if actual.get("error"):
            result["errors"].append(f"{package} unavailable: {actual['error']}")
        elif actual.get("version") != expected:
            result["errors"].append(
                f"{package} version drift: expected {expected}, found {actual.get('version')}"
            )
    result["ok"] = not result["errors"]
    return result


def print_human(result: dict[str, Any]) -> None:
    status = "OK" if result["ok"] else "FAIL"
    print(f"[{status}] {result['profile']} profile")
    print(f"  source: {result.get('source', 'unresolved')}")
    print(f"  configured executable: {result.get('configured_executable', 'unresolved')}")
    runtime = result.get("runtime", {})
    print(f"  executable: {runtime.get('executable', 'unavailable')}")
    print(
        f"  Python: {runtime.get('python_version', 'unavailable')} "
        f"(expected {result['expected_python']})"
    )
    pip = runtime.get("pip", {})
    print(f"  pip: {pip.get('version') or 'unavailable'} @ {pip.get('path') or 'unavailable'}")
    for package in ("numpy", "Pillow", "rdkit"):
        details = runtime.get("packages", {}).get(package, {})
        expected = result["expected_packages"].get(package)
        suffix = f" (expected {expected})" if expected else " (optional in core)"
        print(f"  {package}: {details.get('version') or 'not installed'}{suffix}")
    for error in result["errors"]:
        print(f"  ERROR: {error}")


def run_skill_sync(core_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(core_path), str(ROOT / "scripts" / "check_skill_sync.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    resolve_parser = subparsers.add_parser("resolve", help="print one selected interpreter")
    resolve_parser.add_argument("profile", choices=("core", "chem"))
    check_parser = subparsers.add_parser("check", help="report and validate both environments")
    check_parser.add_argument("--profile", action="append", choices=("core", "chem"))
    check_parser.add_argument("--skill-sync", action="store_true")
    check_parser.add_argument("--json", action="store_true")
    run_parser = subparsers.add_parser("run", help="execute with a reviewed profile")
    run_parser.add_argument("profile", choices=("core", "chem"))
    run_parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    try:
        registry = load_registry()
        if args.command == "resolve":
            path, _source = resolve_profile(args.profile, registry=registry)
            print(path)
            return 0
        if args.command == "run":
            command = list(args.args)
            if command and command[0] == "--":
                command.pop(0)
            if not command:
                raise EnvironmentError("run requires Python arguments or a script path")
            result = inspect_profile(args.profile, registry)
            errors = list(result["errors"])
            is_pip_command = command[:2] == ["-m", "pip"]
            if is_pip_command and args.profile == "chem":
                package_prefixes = tuple(
                    f"{package} " for package in registry["profiles"]["chem"]["packages"]
                )
                errors = [item for item in errors if not item.startswith(package_prefixes)]
            if errors:
                raise EnvironmentError("; ".join(errors))
            executable = Path(result["configured_executable"])
            os.execv(str(executable), [str(executable), *command])
            return 0

        profiles = args.profile or ["core", "chem"]
        results = [inspect_profile(name, registry) for name in profiles]
        sync_result: Optional[dict[str, Any]] = None
        if args.skill_sync:
            core_path, _source = resolve_profile("core", registry=registry)
            completed = run_skill_sync(core_path)
            sync_result = {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        if args.json:
            print(json.dumps({"profiles": results, "skill_sync": sync_result}, indent=2, sort_keys=True))
        else:
            for index, result in enumerate(results):
                if index:
                    print()
                print_human(result)
            if sync_result is not None:
                print()
                print(f"[{'OK' if sync_result['ok'] else 'FAIL'}] repository/deployed Skill sync")
                output = (sync_result["stdout"] + sync_result["stderr"]).rstrip()
                if output:
                    print(output)
        return 0 if all(item["ok"] for item in results) and (sync_result is None or sync_result["ok"]) else 1
    except (EnvironmentError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
