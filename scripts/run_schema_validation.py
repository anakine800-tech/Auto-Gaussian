#!/usr/bin/env python3
"""Run the CI-owned Draft 2020-12 inventory in an existing test-only venv."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Sequence


SCRIPT_ROOT = Path(__file__).resolve().parent
EXPLICIT_PYTHON_ENV = "AUTO_G16_SCHEMA_VALIDATION_PYTHON"
PROBE_SOURCE = """\
import json
import sys
site_packages = sys.argv[1]
names = json.loads(sys.argv[2])
sys.path.insert(0, site_packages)
import importlib.metadata as metadata
versions = {}
for name in names:
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        versions[name] = None
print(json.dumps({
    "schema": "auto-g16-schema-validation-probe/1",
    "python_version": ".".join(str(item) for item in sys.version_info[:3]),
    "versions": versions,
}, sort_keys=True))
"""
TEST_SOURCE = """\
import runpy
import sys
root = sys.argv[1]
site_packages = sys.argv[2]
modules = sys.argv[3:]
sys.path[:0] = [site_packages, root]
sys.argv = ["unittest", *modules, "-v"]
runpy.run_module("unittest", run_name="__main__")
"""


class BlockedError(ValueError):
    """The local test-only validator gate cannot run safely."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BlockedError(f"candidate probe returned duplicate JSON key: {key}")
        result[key] = value
    return result


class Candidate(NamedTuple):
    python: Path
    environment: Path
    site_packages: Path
    source: str


def _load_audit() -> Any:
    path = SCRIPT_ROOT / "audit_python_contract.py"
    spec = importlib.util.spec_from_file_location(
        "auto_g16_local_schema_validation_contract", path
    )
    if not spec or not spec.loader:
        raise BlockedError("could not load the local Python contract audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit()


def _absolute(value: Path, label: str) -> Path:
    if not value.is_absolute():
        raise BlockedError(f"{label} must be an absolute path: {value}")
    return value


def _candidate_from_python(path: Path, source: str) -> Candidate:
    path = _absolute(path, source)
    parent = path.parent
    if parent.name not in {"bin", "Scripts"}:
        raise BlockedError(
            f"{source} must name a Python inside an isolated env bin/ or Scripts/: {path}"
        )
    return _candidate_from_env(parent.parent, source, python=path)


def _candidate_from_env(
    path: Path,
    source: str,
    *,
    python: Path | None = None,
) -> Candidate:
    path = _absolute(path, source)
    if not _trusted_directory_chain(path, path):
        raise BlockedError(
            f"{source} is not a trusted user-owned, non-writable existing "
            f"environment directory: {path}"
        )
    choices = (path / "bin" / "python", path / "Scripts" / "python.exe")
    existing_pythons = [candidate for candidate in choices if candidate.exists()]
    if python is None and len(existing_pythons) != 1:
        raise BlockedError(
            f"{source} must contain exactly one conventional Python executable: {path}"
        )
    if python is not None and python not in choices:
        raise BlockedError(f"{source} does not belong to the declared environment: {python}")
    package_choices = sorted(path.glob("lib/python*/site-packages"))
    windows_packages = path / "Lib" / "site-packages"
    if windows_packages.is_dir():
        package_choices.append(windows_packages)
    package_choices = [
        candidate
        for candidate in package_choices
        if _trusted_directory_chain(path, candidate)
    ]
    if len(package_choices) != 1:
        raise BlockedError(
            f"{source} must contain exactly one non-symlink environment-local "
            f"site-packages directory: {path}"
        )
    return Candidate(
        python=python or existing_pythons[0],
        environment=path,
        site_packages=package_choices[0],
        source=source,
    )


def _trusted_directory_chain(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
    current = root
    paths = [current]
    for part in relative.parts:
        current = current / part
        paths.append(current)
    for current in paths:
        try:
            details = current.lstat()
        except OSError:
            return False
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or (expected_uid is not None and details.st_uid != expected_uid)
            or (os.name == "posix" and details.st_mode & 0o022)
        ):
            return False
    return True


def _default_envs(root: Path) -> tuple[Path, ...]:
    review_root = Path("/private/tmp/auto-g16-jsonschema-review")
    return (
        root / ".venv-schema-validation",
        review_root / "venv311",
        review_root / "venv312",
        review_root / "venv313",
    )


def discover_candidates(
    root: Path,
    pythons: Sequence[Path],
    envs: Sequence[Path],
    environ: Mapping[str, str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, path in enumerate(pythons, 1):
        candidates.append(_candidate_from_python(path, f"--python #{index}"))
    for index, path in enumerate(envs, 1):
        candidates.append(_candidate_from_env(path, f"--env #{index}"))
    if not candidates:
        configured = environ.get(EXPLICIT_PYTHON_ENV)
        if configured:
            candidates.append(
                _candidate_from_python(Path(configured), EXPLICIT_PYTHON_ENV)
            )
    if not candidates:
        for path in _default_envs(root):
            if path.is_dir() and not path.is_symlink():
                candidates.append(_candidate_from_env(path, f"existing {path}"))
    if not candidates:
        raise BlockedError(
            "no existing isolated Schema-validation environment was found; "
            "provide --env /absolute/venv or --python /absolute/venv/bin/python. "
            "Create/install it separately from this command using "
            "requirements/schema-validation.txt; this runner never installs packages."
        )
    deduplicated: list[Candidate] = []
    seen: set[tuple[Path, Path]] = set()
    for candidate in candidates:
        key = (
            candidate.python.absolute(),
            candidate.site_packages.absolute(),
        )
        if key not in seen:
            seen.add(key)
            deduplicated.append(candidate)
    return deduplicated


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _closed_probe(value: object, expected_names: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "python_version",
        "versions",
    }:
        raise BlockedError("candidate probe returned an unsupported document")
    if value["schema"] != "auto-g16-schema-validation-probe/1":
        raise BlockedError("candidate probe returned an unsupported schema")
    versions = value["versions"]
    if not isinstance(versions, dict) or set(versions) != expected_names:
        raise BlockedError("candidate probe returned an incomplete package inventory")
    if not all(item is None or isinstance(item, str) for item in versions.values()):
        raise BlockedError("candidate probe returned a non-string package version")
    if not isinstance(value["python_version"], str) or not value["python_version"]:
        raise BlockedError("candidate probe returned an invalid python_version")
    return value


def validate_candidate(
    candidate: Candidate,
    pins: Mapping[str, str],
    supported_python_minors: Sequence[str],
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    try:
        details = candidate.python.stat()
    except OSError as exc:
        raise BlockedError(
            f"candidate Python is unavailable ({candidate.source}): {candidate.python}"
        ) from exc
    expected_uid = os.geteuid() if hasattr(os, "geteuid") else None
    if (
        not stat.S_ISREG(details.st_mode)
        or not os.access(candidate.python, os.X_OK)
        or (expected_uid is not None and details.st_uid != expected_uid)
    ):
        raise BlockedError(
            f"candidate Python is not a trusted user-owned executable "
            f"({candidate.source}): {candidate.python}"
        )
    if not _trusted_directory_chain(
        candidate.environment, candidate.python.parent
    ) or not _trusted_directory_chain(
        candidate.environment, candidate.site_packages
    ):
        raise BlockedError(
            f"candidate environment directories are unavailable, replaced, or writable "
            f"by another local user ({candidate.source}): {candidate.environment}"
        )
    command = [
        str(candidate.python),
        "-I",
        "-S",
        "-c",
        PROBE_SOURCE,
        str(candidate.site_packages),
        json.dumps(sorted(pins), separators=(",", ":")),
    ]
    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONNOUSERSITE": "1"},
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "probe exited without diagnostics"
        raise BlockedError(
            f"candidate probe failed ({candidate.source}, exit {completed.returncode}): {detail}"
        )
    try:
        raw = json.loads(completed.stdout, object_pairs_hook=_object)
    except json.JSONDecodeError as exc:
        raise BlockedError("candidate probe did not return one JSON document") from exc
    payload = _closed_probe(raw, set(pins))
    version_parts = payload["python_version"].split(".")
    python_minor = ".".join(version_parts[:2])
    if len(version_parts) != 3 or python_minor not in supported_python_minors:
        raise BlockedError(
            f"candidate Python {payload['python_version']} is outside the reviewed "
            f"minor set {', '.join(supported_python_minors)} ({candidate.source})"
        )
    mismatches = [
        f"{name}: expected {version}, found {payload['versions'][name] or 'missing'}"
        for name, version in sorted(pins.items())
        if payload["versions"][name] != version
    ]
    if mismatches:
        raise BlockedError(
            "candidate package lock mismatch ("
            + candidate.source
            + f", {candidate.environment}"
            + "): "
            + "; ".join(mismatches)
            + ". Provide another existing isolated environment with --env or --python; "
            + "this runner never repairs or installs a candidate."
        )
    return payload


def run_inventory(
    candidate: Candidate,
    root: Path,
    modules: Sequence[str],
    *,
    runner: Runner = subprocess.run,
) -> int:
    command = [
        str(candidate.python),
        "-I",
        "-S",
        "-c",
        TEST_SOURCE,
        str(root),
        str(candidate.site_packages),
        *modules,
    ]
    completed = runner(
        command,
        check=False,
        cwd=root,
        env={
            "AUTO_G16_REQUIRE_JSONSCHEMA": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
    )
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--python", type=Path, action="append", default=[])
    parser.add_argument("--env", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        root = AUDIT.find_root(args.repo)
        contract = AUDIT.load_local_schema_validation_contract(root)
        if contract["pins"] != AUDIT.SCHEMA_VALIDATION_PINS:
            raise BlockedError(
                "repository Schema-validation lock differs from the reviewed static contract"
            )
        candidates = discover_candidates(
            root, args.python, args.env, os.environ
        )
        validated: list[tuple[Candidate, dict[str, Any]]] = []
        candidate_errors: list[str] = []
        for candidate in candidates:
            try:
                validated.append(
                    (
                        candidate,
                        validate_candidate(
                            candidate,
                            contract["pins"],
                            contract["supported_python_minors"],
                        ),
                    )
                )
            except BlockedError as exc:
                candidate_errors.append(str(exc))
        if candidate_errors:
            raise BlockedError(
                "all candidates are checked before tests; "
                + " | ".join(candidate_errors)
            )
    except (
        BlockedError,
        AUDIT.ContractError,
        AUDIT.CI_CONTRACT.ContractError,
        OSError,
        UnicodeError,
    ) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    print(
        f"Verified {len(validated)} isolated environment(s) against "
        f"{len(contract['pins'])} exact locked package versions.",
        flush=True,
    )
    print(
        "LOCK: "
        + "; ".join(
            f"{name}=={version}" for name, version in sorted(contract["pins"].items())
        ),
        flush=True,
    )
    print(
        f"CI owner {contract['workflow']} supplies the canonical ordered "
        f"{len(contract['modules'])}-module inventory.",
        flush=True,
    )
    for candidate, payload in validated:
        print(
            f"RUN: Python {payload['python_version']} with "
            f"{candidate.site_packages} ({candidate.source})",
            flush=True,
        )
        result = run_inventory(candidate, root, contract["modules"])
        if result != 0:
            print(
                f"FAIL: canonical Draft 2020-12 validation exited {result}: "
                f"{candidate.python}",
                file=sys.stderr,
            )
            return 1
    print(
        f"PASS: canonical Draft 2020-12 validation completed in "
        f"{len(validated)} isolated environment(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
