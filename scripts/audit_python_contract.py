#!/usr/bin/env python3
"""Audit the static Auto-G16 Python version contract offline."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parent
RESULT_SCHEMA = "auto-g16-python-contract-audit-result/1"
TOOL_KEYS = {
    "default-profile",
    "environment-registry",
    "core-environment",
    "chemistry-environment",
    "chemistry-lock",
}
EXACT_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+(?:[A-Za-z0-9._+-]*)")
REQUIRES_PYTHON = re.compile(
    r">=(3)\.(0|[1-9][0-9]*)\s*,\s*<(3)\.(0|[1-9][0-9]*)"
)
CONDA_PIN = re.compile(r"([A-Za-z0-9_.-]+)=([^=<>!~;\s]+)")
LOCK_PIN = re.compile(r"([A-Za-z0-9_.-]+)==([^=<>!~;\s]+)")


class ContractError(ValueError):
    """A contract input is malformed or uses unsupported syntax."""


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise ContractError(f"could not load required local helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PYTHON_ENVIRONMENT = _load_module(
    "auto_g16_python_contract_environment",
    SCRIPT_ROOT / "python_environment.py",
)
CI_CONTRACT = _load_module(
    "auto_g16_python_contract_ci",
    SCRIPT_ROOT / "audit_ci_contract.py",
)


def find_root(start: Path) -> Path:
    try:
        return CI_CONTRACT.find_root(start)
    except CI_CONTRACT.ContractError as exc:
        raise ContractError(str(exc)) from exc


def _repo_file(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ContractError(f"repository path is unsafe: {relative}")
    current = root
    for part in candidate.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ContractError(f"required repository path is unavailable: {candidate}") from exc
        if stat.S_ISLNK(mode):
            raise ContractError(f"repository contract path must not contain a symlink: {candidate}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ContractError(f"repository contract path must be a regular file: {candidate}")
    return current


def _repo_directory(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ContractError(f"repository path is unsafe: {relative}")
    current = root
    for part in candidate.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ContractError(f"required repository path is unavailable: {candidate}") from exc
        if stat.S_ISLNK(mode):
            raise ContractError(f"repository contract path must not contain a symlink: {candidate}")
    if not stat.S_ISDIR(current.lstat().st_mode):
        raise ContractError(f"repository contract path must be a directory: {candidate}")
    return current


def _read(root: Path, relative: str | Path) -> str:
    path = _repo_file(root, relative)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"could not read repository contract path: {relative}") from exc


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ContractError(f"{label} must be a non-empty trimmed repository path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise ContractError(f"{label} must be a safe repository-relative path")
    return path.as_posix()


def load_pyproject(root: Path) -> tuple[list[str], dict[str, str]]:
    try:
        value = tomllib.loads(_read(root, "pyproject.toml"))
    except tomllib.TOMLDecodeError as exc:
        raise ContractError(f"invalid pyproject.toml: {exc}") from exc
    project = value.get("project")
    if not isinstance(project, dict):
        raise ContractError("pyproject.toml must define a project table")
    raw = project.get("requires-python")
    if not isinstance(raw, str):
        raise ContractError("project.requires-python must be a string")
    match = REQUIRES_PYTHON.fullmatch(raw)
    if not match:
        raise ContractError(
            "project.requires-python must use the supported >=3.MINOR,<3.MINOR syntax"
        )
    lower = int(match.group(2))
    upper = int(match.group(4))
    if upper <= lower or upper - lower > 20:
        raise ContractError("project.requires-python does not prove a bounded non-empty minor range")
    supported = [f"3.{minor}" for minor in range(lower, upper)]

    tool = value.get("tool")
    auto_g16 = tool.get("auto-g16") if isinstance(tool, dict) else None
    python = auto_g16.get("python") if isinstance(auto_g16, dict) else None
    if not isinstance(python, dict) or set(python) != TOOL_KEYS:
        raise ContractError("tool.auto-g16.python must be a closed mapping")
    if python["default-profile"] != "core":
        raise ContractError("tool.auto-g16.python default-profile must remain core")
    paths = {
        key: _relative_path(python[key], f"tool.auto-g16.python.{key}")
        for key in TOOL_KEYS - {"default-profile"}
    }
    if len(set(paths.values())) != len(paths):
        raise ContractError("tool.auto-g16.python paths must be unique")
    return supported, paths


def _exact_pin(version: str, label: str) -> str:
    if not EXACT_VERSION.fullmatch(version):
        raise ContractError(f"{label} must use an exact version pin")
    return version


def parse_conda_environment(root: Path, relative: str) -> dict[str, Any]:
    text = _read(root, relative)
    if "\t" in text or re.search(r"(?m)^\s*(?:<<:|[^#\n]*[&*][A-Za-z0-9_-]+)", text):
        raise ContractError(f"{relative}: tabs, anchors, aliases, and merge keys are unsupported")
    scalar: dict[str, str] = {}
    arrays: dict[str, list[str]] = {}
    section: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):(?:\s*(\S.*))?", line)
        if header:
            key, raw = header.groups()
            if key in scalar or key in arrays:
                raise ContractError(f"{relative}:{number}: duplicate top-level key {key!r}")
            if raw is None:
                arrays[key] = []
                section = key
            else:
                if " #" in raw or raw[0] in "[{'\"|>&*!~":
                    raise ContractError(f"{relative}:{number}: unsupported YAML scalar syntax")
                scalar[key] = raw
                section = None
            continue
        item = re.fullmatch(r"  -\s+(\S.*)", line)
        if not item or section is None:
            raise ContractError(f"{relative}:{number}: unsupported YAML syntax")
        raw = item.group(1)
        if " #" in raw or raw[0] in "[{'\"|>&*!~":
            raise ContractError(f"{relative}:{number}: unsupported YAML list syntax")
        arrays[section].append(raw)
    if set(scalar) != {"name"} or set(arrays) != {"channels", "dependencies"}:
        raise ContractError(f"{relative}: environment must contain exactly name, channels, dependencies")
    if not scalar["name"] or arrays["channels"] != ["conda-forge"]:
        raise ContractError(f"{relative}: environment name and conda-forge channel must be explicit")
    dependencies: dict[str, str] = {}
    for raw in arrays["dependencies"]:
        match = CONDA_PIN.fullmatch(raw)
        if not match:
            raise ContractError(f"{relative}: dependency must be an exact name=version pin: {raw}")
        name = match.group(1).lower()
        if name in dependencies:
            raise ContractError(f"{relative}: duplicate dependency is forbidden: {name}")
        dependencies[name] = _exact_pin(match.group(2), f"{relative}:{name}")
    return {"name": scalar["name"], "dependencies": dependencies}


def parse_lock(root: Path, relative: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, line in enumerate(_read(root, relative).splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        match = LOCK_PIN.fullmatch(line)
        if not match:
            raise ContractError(f"{relative}:{number}: requirement must be an exact name==version pin")
        name = match.group(1).lower()
        if name in pins:
            raise ContractError(f"{relative}:{number}: duplicate requirement is forbidden: {name}")
        pins[name] = _exact_pin(match.group(2), f"{relative}:{name}")
    if not pins:
        raise ContractError(f"{relative}: chemistry lock must not be empty")
    return pins


def validate_requirement_entrypoint(
    root: Path,
    relative: str,
    expected_include: str,
) -> None:
    active_lines = [
        (number, line)
        for number, line in enumerate(_read(root, relative).splitlines(), 1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    expected = f"-r {expected_include}"
    if len(active_lines) != 1 or active_lines[0][1] != expected:
        raise ContractError(
            f"{relative}: must contain exactly one active line: {expected!r}"
        )


def _minor(version: str) -> str:
    parts = version.split(".")
    return ".".join(parts[:2])


def _compare(errors: list[str], actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, found {actual!r}")


def audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    supported, paths = load_pyproject(root)
    registry_path = _repo_file(root, paths["environment-registry"])
    registry = PYTHON_ENVIRONMENT.load_registry(registry_path)
    core = registry["profiles"]["core"]
    chem = registry["profiles"]["chem"]
    core_minor = _minor(core["python_version"])
    chem_minor = _minor(chem["python_version"])
    if core_minor not in supported:
        errors.append(f"registry core Python minor is unsupported: {core_minor}")
    if chem_minor not in supported:
        errors.append(f"registry chem Python minor is unsupported: {chem_minor}")
    _compare(
        errors,
        _read(root, ".python-version").splitlines(),
        [core["python_version"]],
        ".python-version",
    )

    core_environment = parse_conda_environment(root, paths["core-environment"])
    chem_environment = parse_conda_environment(root, paths["chemistry-environment"])
    core_dependencies = core_environment["dependencies"]
    chem_dependencies = chem_environment["dependencies"]
    expected_core_dependencies = {"python", "pip"}
    expected_chem_dependencies = expected_core_dependencies | {
        package.lower() for package in chem["packages"]
    }
    _compare(errors, set(core_dependencies), expected_core_dependencies, "core Conda dependencies")
    _compare(errors, set(chem_dependencies), expected_chem_dependencies, "chem Conda dependencies")
    _compare(errors, core_dependencies.get("python"), core["python_version"], "core Conda Python")
    _compare(errors, chem_dependencies.get("python"), chem["python_version"], "chem Conda Python")
    _compare(errors, chem_dependencies.get("pip"), core_dependencies.get("pip"), "Conda pip pin")
    for package, version in chem["packages"].items():
        _compare(
            errors,
            chem_dependencies.get(package.lower()),
            version,
            f"chem Conda {package}",
        )

    if chem["requirements"] != paths["chemistry-lock"]:
        errors.append("registry chem requirements path differs from pyproject chemistry-lock")
    lock = parse_lock(root, paths["chemistry-lock"])
    expected_lock = {package.lower(): version for package, version in chem["packages"].items()}
    _compare(errors, lock, expected_lock, "chemistry lock")
    chemistry_entrypoint = "requirements/chemistry.txt"
    chemistry_lock = Path(paths["chemistry-lock"])
    if chemistry_lock.parent != Path(chemistry_entrypoint).parent:
        raise ContractError(
            "chemistry lock and requirements entrypoint must share one directory"
        )
    validate_requirement_entrypoint(
        root,
        chemistry_entrypoint,
        chemistry_lock.name,
    )

    required_path = _repo_file(root, "config/required-checks.json")
    required = CI_CONTRACT.load_contract(required_path)
    workflow_directory = _repo_directory(root, ".github/workflows")
    for path in workflow_directory.glob("*.y*ml"):
        _repo_file(root, path.relative_to(root))
    ci_report = CI_CONTRACT.audit(root, required)
    errors.extend(f"CI contract: {item}" for item in ci_report["errors"])
    compatibility = [
        item for item in required["required_checks"] if item["job_id"] == "python-compatibility"
    ]
    expected_contexts = [f"python-compatibility ({minor})" for minor in supported]
    actual_contexts = [item["context"] for item in compatibility]
    _compare(errors, actual_contexts, expected_contexts, "required Python compatibility contexts")
    for item in compatibility:
        context_match = re.fullmatch(r"python-compatibility \((3\.[0-9]+)\)", item["context"])
        version = context_match.group(1) if context_match else None
        if version not in supported or item["matrix"] != {"python-version": version}:
            errors.append(f"required Python context has unsupported or ambiguous mapping: {item['context']}")

    workflow_paths = {
        item["workflow_file"]
        for item in required["required_checks"]
        if item["job_id"] in {
            "python-compatibility",
            "source-archive-release",
            "chemistry-dependencies",
        }
    }
    if len(workflow_paths) != 1:
        raise ContractError("Python CI jobs must be declared in exactly one workflow file")
    workflow_relative = next(iter(workflow_paths))
    workflow = _repo_file(root, workflow_relative)
    _workflow_name, expanded = CI_CONTRACT.parse_workflow(workflow)
    matrix_versions: list[str] = []
    for context, mappings in expanded.items():
        job_id, binding = next(iter(mappings))
        if job_id != "python-compatibility":
            continue
        binding_map = dict(binding)
        version = binding_map.get("python-version")
        if set(binding_map) != {"python-version"} or version is None:
            errors.append(f"CI compatibility matrix binding is ambiguous: {context}")
        else:
            matrix_versions.append(version)
    _compare(errors, matrix_versions, supported, "CI Python compatibility matrix")

    selectors = CI_CONTRACT.parse_setup_python_versions(workflow)
    expected_selectors = {
        "python-compatibility": ["${{ matrix.python-version }}"],
        "source-archive-release": [core_minor],
        "chemistry-dependencies": [chem_minor],
    }
    for job_id, expected in expected_selectors.items():
        _compare(errors, selectors.get(job_id), expected, f"CI {job_id} setup-python selector")

    run_commands = CI_CONTRACT.parse_run_commands(workflow)
    chemistry_installs = [
        (job_id, command)
        for job_id, commands in run_commands.items()
        for command in commands
        if re.search(r"\bpip\s+install\b", command)
    ]
    _compare(
        errors,
        chemistry_installs,
        [
            (
                "chemistry-dependencies",
                "python -m pip install --requirement requirements/chemistry.txt",
            )
        ],
        "CI chemistry requirements install invocation",
    )
    audit_invocations = [
        (job_id, command)
        for job_id, commands in run_commands.items()
        for command in commands
        if "scripts/audit_python_contract.py" in command
    ]
    _compare(
        errors,
        audit_invocations,
        [("source-archive-release", "python scripts/audit_python_contract.py")],
        "CI Python contract audit invocation",
    )

    status = "fail" if errors else "pass"
    return {
        "schema": RESULT_SCHEMA,
        "status": status,
        "claim": (
            "static repository declarations satisfy the Python version contract"
            if not errors
            else "static repository declarations do not satisfy the Python version contract"
        ),
        "supported_python_minors": supported,
        "profiles": {
            "core": {"python_version": core["python_version"], "minor": core_minor},
            "chem": {
                "python_version": chem["python_version"],
                "minor": chem_minor,
                "packages": chem["packages"],
            },
        },
        "summary": {"errors": len(errors), "surfaces": 9},
        "errors": errors,
        "interpreter_availability_verified": False,
        "remote_branch_protection_verified": False,
        "actual_ci_success_verified": False,
        "limitations": [
            "This offline audit checks static declarations only; it does not execute or discover interpreters.",
            "It does not verify current GitHub branch protection, required-check settings, permissions, or CI success.",
            "TOML, Conda YAML, requirements, workflow YAML, and version syntax outside the documented restricted forms fail closed.",
        ],
    }


def _print_text(report: dict[str, Any]) -> None:
    print(f"Auto-G16 Python contract audit: {report['status']}")
    print(report["claim"])
    print(f"Supported minors: {', '.join(report['supported_python_minors'])}")
    for item in report["errors"]:
        print(f"ERROR: {item}", file=sys.stderr)
    print("Interpreter availability, remote branch protection, and actual CI success: not verified")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path or path inside it")
    parser.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    args = parser.parse_args(argv)
    try:
        report = audit(find_root(args.repo))
    except (
        ContractError,
        CI_CONTRACT.ContractError,
        PYTHON_ENVIRONMENT.EnvironmentError,
        OSError,
        UnicodeError,
    ) as exc:
        error = {"schema": RESULT_SCHEMA, "status": "error", "error": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(report)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
