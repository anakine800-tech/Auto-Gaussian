#!/usr/bin/env python3
"""Run the CI-owned Draft 2020-12 inventory from an existing package overlay."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, NamedTuple, Sequence


SCRIPT_ROOT = Path(__file__).resolve().parent
EXPLICIT_ENV = "AUTO_G16_SCHEMA_VALIDATION_ENV"
TRUSTED_PYTHON = Path(sys.executable).resolve(strict=True)
TRUSTED_VERSION = ".".join(str(item) for item in sys.version_info[:3])
TRUSTED_MINOR = ".".join(str(item) for item in sys.version_info[:2])
DISTRIBUTION_IMPORTS = {
    "attrs": "attrs",
    "jsonschema": "jsonschema",
    "jsonschema-specifications": "jsonschema_specifications",
    "referencing": "referencing",
    "rpds-py": "rpds",
    "typing-extensions": "typing_extensions",
}
FIXED_TEST_ENVIRONMENT = MappingProxyType(
    {
        "AUTO_G16_REQUIRE_JSONSCHEMA": "1",
        "AUTO_G16_RUNTIME_CONFIG": "/proc/auto-g16-disabled-runtime-config",
        "HOME": "/proc/auto-g16-disabled-home",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
)
PROBE_SOURCE = r"""
import base64
import importlib
import importlib.machinery
import importlib.metadata as metadata
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import sys

env_fd = int(sys.argv[1])
site_fd = int(sys.argv[2])
site_from_env = tuple(json.loads(sys.argv[3]))
imports = json.loads(sys.argv[4])
os.fchdir(site_fd)
sys.path.insert(0, ".")
errors = []
versions = {}
origins = {}
file_counts = {}
file_manifest = {}
console_script_manifest = {}

null_device = os.lstat("/dev/null")
if not stat.S_ISCHR(null_device.st_mode):
    raise RuntimeError("trusted bytecode sink is unavailable")
sys.dont_write_bytecode = True
sys.pycache_prefix = "/dev/null/auto-g16-schema-validation-bytecode-disabled"

def safe_parts(raw):
    value = str(raw).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe distribution-relative path: " + value)
    return path.parts

def open_regular_at(root_fd, parts, require_safe=False):
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
            if require_safe:
                directory = os.fstat(current)
                if (
                    not stat.S_ISDIR(directory.st_mode)
                    or directory.st_uid != os.geteuid()
                    or directory.st_mode & 0o022
                ):
                    raise ValueError("console-script directory is not private enough")
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        try:
            details = os.fstat(leaf)
            if not stat.S_ISREG(details.st_mode):
                raise ValueError("distribution entry is not a regular file")
            if require_safe and (
                details.st_uid != os.geteuid() or details.st_mode & 0o022
            ):
                raise ValueError("console script owner or mode is unsafe")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(leaf, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return (
                details.st_dev,
                details.st_ino,
                details.st_uid,
                stat.S_IMODE(details.st_mode),
                details.st_size,
                digest.digest(),
            )
        finally:
            os.close(leaf)
    finally:
        os.close(current)

def open_site_regular(raw):
    return open_regular_at(site_fd, safe_parts(raw))

def console_script_parts(raw, declared_names):
    value = str(raw).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", "."} for part in path.parts):
        raise ValueError("unsafe distribution-relative path: " + value)
    leading = 0
    for part in path.parts:
        if part != "..":
            break
        leading += 1
    if (
        leading != len(site_from_env)
        or any(part == ".." for part in path.parts[leading:])
        or tuple(path.parts[leading:leading + 1]) != ("bin",)
        or len(path.parts) != leading + 2
    ):
        raise ValueError("unsafe distribution-relative path: " + value)
    name = path.parts[-1]
    if name not in declared_names or "/" in name or "\\" in name:
        raise ValueError("undeclared console-script RECORD escape: " + value)
    return ("bin", name)

def verify_record_digest(item, details, label):
    if item.hash is None or item.hash.mode != "sha256" or item.size is None:
        raise ValueError(label + " RECORD requires sha256 and size")
    encoded = base64.urlsafe_b64encode(details[5]).rstrip(b"=").decode("ascii")
    if item.hash.value != encoded or item.size != details[4]:
        raise ValueError(label + " RECORD hash or size mismatch")

def controlled_pyc_source(parts):
    if len(parts) < 2 or parts[-2] != "__pycache__":
        return None
    suffix = "." + sys.implementation.cache_tag + ".pyc"
    if not parts[-1].endswith(suffix):
        return None
    stem = parts[-1][:-len(suffix)]
    if not stem or "." in stem:
        return None
    return "/".join(parts[:-2] + (stem + ".py",))

def relative_origin(raw):
    if not isinstance(raw, str) or not raw or raw in {"built-in", "frozen"}:
        raise ValueError("import has no regular file origin")
    absolute = os.path.abspath(raw)
    relative = os.path.relpath(absolute, os.getcwd()).replace("\\", "/")
    safe_parts(relative)
    return relative

if "PYTHONPATH" in os.environ or "PYTHONHOME" in os.environ:
    errors.append("caller Python path configuration reached isolated probe")
if "sitecustomize" in sys.modules or "usercustomize" in sys.modules:
    errors.append("site customization executed in isolated probe")

for distribution_name, import_name in imports.items():
    try:
        distributions = list(metadata.distributions(name=distribution_name, path=["."]))
        if len(distributions) != 1:
            raise ValueError(
                f"expected one {distribution_name} distribution, found {len(distributions)}"
            )
        distribution = distributions[0]
        versions[distribution_name] = distribution.version
        files = distribution.files
        if not files:
            raise ValueError(distribution_name + " has no distribution file inventory")
        manifest = {}
        external = {}
        internal = []
        internal_paths = {}
        controlled_pyc_sources = []
        dist_info_parts = safe_parts(str(distribution._path))
        if len(dist_info_parts) != 1 or not dist_info_parts[0].endswith(".dist-info"):
            raise ValueError(distribution_name + " has an unsafe metadata directory")
        record_relative = dist_info_parts[0] + "/RECORD"
        record_entries = 0
        declared_names = {
            item.name
            for item in distribution.entry_points
            if item.group == "console_scripts"
        }
        for item in files:
            raw_item = str(item).replace("\\", "/")
            try:
                parts = safe_parts(raw_item)
            except ValueError:
                if external:
                    raise ValueError(distribution_name + " has more than one external file")
                parts = console_script_parts(raw_item, declared_names)
                details = open_regular_at(env_fd, parts, require_safe=True)
                verify_record_digest(item, details, "console-script")
                external = {
                    "env_relative": "/".join(parts),
                    "sha256": details[5].hex(),
                    "size": details[4],
                    "identity": list(details[:4]),
                }
                continue
            if raw_item in internal_paths:
                raise ValueError(distribution_name + " has a duplicate RECORD path")
            internal_paths[raw_item] = item
            internal.append((item, raw_item, parts))
        for item, raw_item, parts in internal:
            details = open_regular_at(site_fd, parts)
            if raw_item == record_relative:
                record_entries += 1
                if item.hash is not None or item.size is not None:
                    raise ValueError(distribution_name + " RECORD self-entry must be unhashed")
            elif item.hash is None or item.size is None:
                if item.hash is not None or item.size is not None:
                    raise ValueError(raw_item + " RECORD hash and size must appear together")
                source = controlled_pyc_source(parts)
                if source is None:
                    raise ValueError(raw_item + " is an unsupported unhashed RECORD entry")
                controlled_pyc_sources.append(source)
            else:
                verify_record_digest(item, details, raw_item)
            manifest[raw_item] = details[5].hex()
        if record_entries != 1:
            raise ValueError(distribution_name + " must have one unhashed RECORD self-entry")
        for source in controlled_pyc_sources:
            source_item = internal_paths.get(source)
            if (
                source_item is None
                or source_item.hash is None
                or source_item.hash.mode != "sha256"
                or source_item.size is None
            ):
                raise ValueError(
                    distribution_name
                    + " has an unhashed pyc without one hashed source entry: "
                    + source
                )
        file_counts[distribution_name] = len(files)
        file_manifest[distribution_name] = manifest
        if external:
            console_script_manifest[distribution_name] = external

        spec = importlib.machinery.PathFinder.find_spec(import_name, ["."])
        if spec is None or spec.loader is None:
            raise ValueError(import_name + " has no overlay-local import spec")
        expected_relative = relative_origin(spec.origin)
        expected_identity = open_site_regular(expected_relative)
        if expected_relative not in manifest:
            raise ValueError(import_name + " import origin is absent from distribution files")
        module = importlib.import_module(import_name)
        actual_relative = relative_origin(getattr(module, "__file__", None))
        actual_identity = open_site_regular(actual_relative)
        if actual_identity[:2] != expected_identity[:2]:
            raise ValueError(import_name + " import origin changed during load")
        origins[distribution_name] = actual_relative
    except Exception as exc:
        versions.setdefault(distribution_name, None)
        errors.append(distribution_name + ": " + type(exc).__name__ + ": " + str(exc))

print(json.dumps({
    "schema": "auto-g16-schema-validation-probe/3",
    "python_version": ".".join(str(item) for item in sys.version_info[:3]),
    "versions": versions,
    "origins": origins,
    "distribution_file_counts": file_counts,
    "file_manifest": file_manifest,
    "console_script_manifest": console_script_manifest,
    "errors": errors,
}, sort_keys=True))
"""
TEST_SOURCE = r"""
import importlib
import importlib.metadata as metadata
import json
import hashlib
import os
from pathlib import PurePosixPath
import stat
import sys
import unittest

env_fd = int(sys.argv[1])
site_fd = int(sys.argv[2])
repo_fd = int(sys.argv[3])
evidence_fd = int(sys.argv[4])
root = sys.argv[5]
manifest = json.loads(sys.argv[6])
console_scripts = json.loads(sys.argv[7])
imports = json.loads(sys.argv[8])
expected_versions = json.loads(sys.argv[9])
expected_origins = json.loads(sys.argv[10])
modules = sys.argv[11:]

null_device = os.lstat("/dev/null")
if not stat.S_ISCHR(null_device.st_mode):
    raise RuntimeError("trusted bytecode sink is unavailable")
sys.dont_write_bytecode = True
sys.pycache_prefix = "/dev/null/auto-g16-schema-validation-bytecode-disabled"

def safe_parts(raw):
    path = PurePosixPath(str(raw).replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError("unsafe manifest path")
    return path.parts

def inspect_regular(root_fd, parts, require_safe=False):
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
            if require_safe:
                directory = os.fstat(current)
                if (
                    not stat.S_ISDIR(directory.st_mode)
                    or directory.st_uid != os.geteuid()
                    or directory.st_mode & 0o022
                ):
                    raise RuntimeError("console-script directory is not private enough")
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        try:
            details = os.fstat(leaf)
            if not stat.S_ISREG(details.st_mode):
                raise RuntimeError("manifest entry is not regular")
            if require_safe and (
                details.st_uid != os.geteuid() or details.st_mode & 0o022
            ):
                raise RuntimeError("console script owner or mode is unsafe")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(leaf, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return {
                "sha256": digest.hexdigest(),
                "size": details.st_size,
                "identity": [
                    details.st_dev,
                    details.st_ino,
                    details.st_uid,
                    stat.S_IMODE(details.st_mode),
                ],
            }
        finally:
            os.close(leaf)
    finally:
        os.close(current)

def replay_overlay():
    for files in manifest.values():
        for relative, expected_digest in files.items():
            if inspect_regular(site_fd, safe_parts(relative))["sha256"] != expected_digest:
                raise RuntimeError("overlay file changed after trusted probe: " + relative)
    for item in console_scripts.values():
        parts = tuple(item["env_relative"].split("/"))
        actual = inspect_regular(env_fd, parts, require_safe=True)
        if actual != {
            "sha256": item["sha256"],
            "size": item["size"],
            "identity": item["identity"],
        }:
            raise RuntimeError("console script changed after trusted probe: " + item["env_relative"])

replay_overlay()

os.fchdir(site_fd)
sys.path.insert(0, ".")
observed_versions = {}
for distribution_name in imports:
    matches = list(metadata.distributions(name=distribution_name, path=["."]))
    if len(matches) != 1:
        raise RuntimeError("test child did not find one descriptor-bound distribution")
    observed_versions[distribution_name] = matches[0].version
if observed_versions != expected_versions:
    raise RuntimeError("test child package versions differ from trusted probe")
for distribution_name, import_name in imports.items():
    module = importlib.import_module(import_name)
    origin = os.path.relpath(module.__file__, os.getcwd()).replace("\\", "/")
    if origin != expected_origins[distribution_name] or origin not in manifest[distribution_name]:
        raise RuntimeError("test child import origin differs from trusted probe")
sys.path.remove(".")
os.fchdir(repo_fd)
repo_path = os.lstat(root)
repo_descriptor = os.fstat(repo_fd)
if (
    stat.S_ISLNK(repo_path.st_mode)
    or not stat.S_ISDIR(repo_path.st_mode)
    or (repo_path.st_dev, repo_path.st_ino) != (repo_descriptor.st_dev, repo_descriptor.st_ino)
):
    raise RuntimeError("repository path identity differs from retained descriptor")
sys.path.insert(0, root)
original_version = metadata.version
def overlay_version(name):
    normalized = name.lower().replace("_", "-")
    if normalized in expected_versions:
        return expected_versions[normalized]
    return original_version(name)
metadata.version = overlay_version
suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
result = unittest.TextTestRunner(verbosity=2).run(suite)
replay_overlay()
payload = {
    "schema": "auto-g16-schema-validation-test-completion/1",
    "tests_run": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skipped": len(result.skipped),
    "successful": result.wasSuccessful(),
}
os.write(evidence_fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
raise SystemExit(0 if result.wasSuccessful() else 1)
"""


class BlockedError(ValueError):
    """The local test-only validator gate cannot run safely."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BlockedError(f"subprocess evidence contains duplicate JSON key: {key}")
        result[key] = value
    return result


class Candidate(NamedTuple):
    environment: Path
    site_packages: Path
    source: str
    environment_identity: tuple[int, int, int, int]
    site_identity: tuple[int, int, int, int]


class ValidatedCandidate(NamedTuple):
    candidate: Candidate
    environment_fd: int
    site_fd: int
    payload: dict[str, Any]


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


def _identity(path: Path) -> tuple[int, int, int, int]:
    details = path.lstat()
    return (
        details.st_dev,
        details.st_ino,
        details.st_uid,
        stat.S_IMODE(details.st_mode),
    )


def _candidate_from_env(path: Path, source: str) -> Candidate:
    path = _absolute(path, source)
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise BlockedError("descriptor-bound Schema validation requires POSIX O_NOFOLLOW")
    if not _trusted_directory_chain(path, path):
        raise BlockedError(
            f"{source} is not a trusted user-owned, non-writable existing "
            f"environment directory: {path}"
        )
    expected = path / "lib" / f"python{TRUSTED_MINOR}" / "site-packages"
    discovered = sorted(path.glob("lib/python*/site-packages"))
    if discovered != [expected] or not _trusted_directory_chain(path, expected):
        raise BlockedError(
            f"{source} must contain exactly one non-symlink site-packages for "
            f"trusted Python {TRUSTED_MINOR}: {path}"
        )
    return Candidate(path, expected, source, _identity(path), _identity(expected))


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
    envs: Sequence[Path],
    environ: Mapping[str, str],
) -> list[Candidate]:
    candidates = [
        _candidate_from_env(path, f"--env #{index}")
        for index, path in enumerate(envs, 1)
    ]
    if not candidates:
        configured = environ.get(EXPLICIT_ENV)
        if configured:
            candidates.append(_candidate_from_env(Path(configured), EXPLICIT_ENV))
    if not candidates:
        for path in _default_envs(root):
            if path.is_dir() and not path.is_symlink():
                try:
                    candidates.append(_candidate_from_env(path, f"existing {path}"))
                except BlockedError:
                    continue
    if not candidates:
        raise BlockedError(
            "no existing trusted Schema-validation package overlay matches the current "
            f"Python {TRUSTED_MINOR}; provide --env /absolute/environment. "
            "Prepare it separately with requirements/schema-validation.txt; this runner "
            "never executes an environment-local program or installs packages."
        )
    deduplicated: list[Candidate] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        key = candidate.site_identity[:2]
        if key not in seen:
            seen.add(key)
            deduplicated.append(candidate)
    return deduplicated


def _candidate_current(candidate: Candidate) -> bool:
    try:
        return (
            _trusted_directory_chain(candidate.environment, candidate.site_packages)
            and _identity(candidate.environment) == candidate.environment_identity
            and _identity(candidate.site_packages) == candidate.site_identity
        )
    except OSError:
        return False


def _open_directory(path: Path, expected: tuple[int, int, int, int], label: str) -> int:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise BlockedError(f"candidate {label} could not be opened no-follow") from exc
    details = os.fstat(descriptor)
    actual = (
        details.st_dev,
        details.st_ino,
        details.st_uid,
        stat.S_IMODE(details.st_mode),
    )
    if actual != expected or not stat.S_ISDIR(details.st_mode):
        os.close(descriptor)
        raise BlockedError(f"candidate {label} identity drifted while opening")
    return descriptor


def _open_candidate(candidate: Candidate) -> tuple[int, int]:
    if not _candidate_current(candidate):
        raise BlockedError(
            f"candidate overlay changed after discovery ({candidate.source}): "
            f"{candidate.site_packages}"
        )
    environment_fd = _open_directory(
        candidate.environment, candidate.environment_identity, "environment root"
    )
    try:
        site_fd = _open_directory(
            candidate.site_packages, candidate.site_identity, "site-packages"
        )
    except Exception:
        os.close(environment_fd)
        raise
    return environment_fd, site_fd


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _closed_probe(value: object, expected_names: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "python_version",
        "versions",
        "origins",
        "distribution_file_counts",
        "file_manifest",
        "console_script_manifest",
        "errors",
    }:
        raise BlockedError("trusted probe returned an unsupported document")
    if value["schema"] != "auto-g16-schema-validation-probe/3":
        raise BlockedError("trusted probe returned an unsupported schema")
    if value["python_version"] != TRUSTED_VERSION:
        raise BlockedError("trusted probe Python identity changed")
    versions = value["versions"]
    origins = value["origins"]
    counts = value["distribution_file_counts"]
    manifest = value["file_manifest"]
    console_scripts = value["console_script_manifest"]
    errors = value["errors"]
    if not isinstance(versions, dict) or set(versions) != expected_names:
        raise BlockedError("trusted probe returned an incomplete package inventory")
    if not isinstance(origins, dict) or not set(origins).issubset(expected_names):
        raise BlockedError("trusted probe returned an invalid import-origin inventory")
    if not isinstance(counts, dict) or not set(counts).issubset(expected_names):
        raise BlockedError("trusted probe returned an invalid distribution-file inventory")
    if not isinstance(manifest, dict) or not set(manifest).issubset(expected_names):
        raise BlockedError("trusted probe returned an invalid file manifest")
    if (
        not isinstance(console_scripts, dict)
        or not set(console_scripts).issubset(expected_names)
        or len(console_scripts) > 1
    ):
        raise BlockedError("trusted probe returned an invalid console-script manifest")
    if not all(isinstance(item, str) and item for item in origins.values()):
        raise BlockedError("trusted probe returned an invalid import origin")
    if not all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in counts.values()):
        raise BlockedError("trusted probe returned an invalid distribution file count")
    for files in manifest.values():
        if not isinstance(files, dict) or not files:
            raise BlockedError("trusted probe returned an empty distribution manifest")
        if not all(
            isinstance(path, str)
            and path
            and isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            for path, digest in files.items()
        ):
            raise BlockedError("trusted probe returned an invalid distribution digest")
    for item in console_scripts.values():
        if not isinstance(item, dict) or set(item) != {
            "env_relative",
            "sha256",
            "size",
            "identity",
        }:
            raise BlockedError("trusted probe returned an invalid console-script entry")
        relative = item["env_relative"]
        digest = item["sha256"]
        size = item["size"]
        identity = item["identity"]
        if (
            not isinstance(relative, str)
            or len(relative.split("/")) != 2
            or relative.split("/")[0] != "bin"
            or not relative.split("/")[1]
            or "/" in relative.split("/")[1]
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(identity, list)
            or len(identity) != 4
            or not all(isinstance(part, int) and not isinstance(part, bool) for part in identity)
            or identity[2] != (os.geteuid() if hasattr(os, "geteuid") else identity[2])
            or identity[3] & 0o022
        ):
            raise BlockedError("trusted probe returned unsafe console-script evidence")
    if not isinstance(errors, list) or not all(isinstance(item, str) and item for item in errors):
        raise BlockedError("trusted probe returned invalid errors")
    if not errors and any(
        counts.get(name)
        != len(manifest.get(name, {})) + (1 if name in console_scripts else 0)
        for name in expected_names
    ):
        raise BlockedError("trusted probe distribution counts disagree with its manifest")
    return value


def validate_candidate(
    candidate: Candidate,
    pins: Mapping[str, str],
    supported_python_minors: Sequence[str],
    *,
    runner: Runner = subprocess.run,
) -> ValidatedCandidate:
    if TRUSTED_MINOR not in supported_python_minors:
        raise BlockedError(
            f"current trusted Python {TRUSTED_VERSION} is outside the reviewed minor set "
            f"{', '.join(supported_python_minors)}"
        )
    if set(pins) != set(DISTRIBUTION_IMPORTS):
        raise BlockedError("lock package names differ from the reviewed import inventory")
    environment_fd, site_fd = _open_candidate(candidate)
    command = [
        str(TRUSTED_PYTHON),
        "-I",
        "-S",
        "-B",
        "-c",
        PROBE_SOURCE,
        str(environment_fd),
        str(site_fd),
        json.dumps(
            candidate.site_packages.relative_to(candidate.environment).parts,
            separators=(",", ":"),
        ),
        json.dumps(DISTRIBUTION_IMPORTS, sort_keys=True, separators=(",", ":")),
    ]
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(environment_fd, site_fd),
            env={"PYTHONNOUSERSITE": "1"},
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "probe exited without diagnostics"
            raise BlockedError(
                f"trusted probe failed ({candidate.source}, exit {completed.returncode}): {detail}"
            )
        try:
            raw = json.loads(completed.stdout, object_pairs_hook=_object)
        except json.JSONDecodeError as exc:
            raise BlockedError("trusted probe did not return one JSON document") from exc
        payload = _closed_probe(raw, set(pins))
        if payload["errors"]:
            raise BlockedError(
                f"candidate overlay origin/import validation failed ({candidate.source}): "
                + " | ".join(payload["errors"])
            )
        mismatches = [
            f"{name}: expected {version}, found {payload['versions'].get(name) or 'missing'}"
            for name, version in sorted(pins.items())
            if payload["versions"].get(name) != version
        ]
        if mismatches:
            raise BlockedError(
                f"candidate package lock mismatch ({candidate.source}, {candidate.environment}): "
                + "; ".join(mismatches)
                + ". Provide another existing overlay with --env; this runner never repairs "
                + "or installs a candidate."
            )
        if (
            set(payload["origins"]) != set(pins)
            or set(payload["distribution_file_counts"]) != set(pins)
            or set(payload["file_manifest"]) != set(pins)
        ):
            raise BlockedError("trusted probe did not close every locked import and distribution")
        return ValidatedCandidate(candidate, environment_fd, site_fd, payload)
    except Exception:
        os.close(environment_fd)
        os.close(site_fd)
        raise


def _read_evidence(descriptor: int, limit: int = 65536) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, min(8192, limit + 1 - size))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise BlockedError("test completion evidence exceeded the bounded size")


def _closed_completion(value: object) -> dict[str, Any]:
    keys = {"schema", "tests_run", "failures", "errors", "skipped", "successful"}
    if not isinstance(value, dict) or set(value) != keys:
        raise BlockedError("trusted test process returned an unsupported completion document")
    if value["schema"] != "auto-g16-schema-validation-test-completion/1":
        raise BlockedError("trusted test process returned an unsupported completion schema")
    for key in ("tests_run", "failures", "errors", "skipped"):
        item = value[key]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise BlockedError(f"trusted test completion has invalid {key}")
    if not isinstance(value["successful"], bool) or value["tests_run"] <= 0:
        raise BlockedError("trusted test completion is missing real unittest execution")
    return value


def run_inventory(
    validated: ValidatedCandidate,
    root: Path,
    modules: Sequence[str],
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    candidate = validated.candidate
    if not _candidate_current(candidate):
        raise BlockedError(
            f"candidate overlay path changed before tests ({candidate.source}); "
            "the opened descriptor was not reused silently"
        )
    repo_fd = _open_directory(root, _identity(root), "repository root")
    read_fd, write_fd = os.pipe()
    command = [
        str(TRUSTED_PYTHON),
        "-I",
        "-S",
        "-B",
        "-c",
        TEST_SOURCE,
        str(validated.environment_fd),
        str(validated.site_fd),
        str(repo_fd),
        str(write_fd),
        str(root),
        json.dumps(validated.payload["file_manifest"], sort_keys=True, separators=(",", ":")),
        json.dumps(
            validated.payload["console_script_manifest"],
            sort_keys=True,
            separators=(",", ":"),
        ),
        json.dumps(DISTRIBUTION_IMPORTS, sort_keys=True, separators=(",", ":")),
        json.dumps(validated.payload["versions"], sort_keys=True, separators=(",", ":")),
        json.dumps(validated.payload["origins"], sort_keys=True, separators=(",", ":")),
        *modules,
    ]
    try:
        try:
            completed = runner(
                command,
                check=False,
                cwd=root,
                pass_fds=(
                    validated.environment_fd,
                    validated.site_fd,
                    repo_fd,
                    write_fd,
                ),
                env=dict(FIXED_TEST_ENVIRONMENT),
            )
        except Exception:
            os.close(read_fd)
            raise
    finally:
        os.close(write_fd)
        os.close(repo_fd)
    try:
        raw = _read_evidence(read_fd)
    finally:
        os.close(read_fd)
    if not raw:
        raise BlockedError(
            f"trusted test process produced no completion evidence (exit {completed.returncode})"
        )
    try:
        payload = _closed_completion(
            json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BlockedError("trusted test completion is not one UTF-8 JSON document") from exc
    expected_exit = 0 if payload["successful"] else 1
    if completed.returncode != expected_exit:
        raise BlockedError(
            "trusted test exit status disagrees with unittest completion evidence"
        )
    return payload


def close_validated(candidates: Sequence[ValidatedCandidate]) -> None:
    for candidate in candidates:
        for descriptor in (candidate.environment_fd, candidate.site_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--env", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    validated: list[ValidatedCandidate] = []
    try:
        root = AUDIT.find_root(args.repo)
        contract = AUDIT.load_local_schema_validation_contract(root)
        if contract["pins"] != AUDIT.SCHEMA_VALIDATION_PINS:
            raise BlockedError(
                "repository Schema-validation lock differs from the reviewed static contract"
            )
        candidates = discover_candidates(root, args.env, os.environ)
        candidate_errors: list[str] = []
        for candidate in candidates:
            try:
                validated.append(
                    validate_candidate(
                        candidate,
                        contract["pins"],
                        contract["supported_python_minors"],
                    )
                )
            except BlockedError as exc:
                candidate_errors.append(str(exc))
        if candidate_errors:
            raise BlockedError(
                "all candidates are checked before tests; " + " | ".join(candidate_errors)
            )

        print(
            f"Verified {len(validated)} package overlay(s) with trusted Python "
            f"{TRUSTED_VERSION} against {len(contract['pins'])} exact locked packages.",
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
        for item in validated:
            print(
                f"RUN: trusted {TRUSTED_PYTHON} with descriptor-bound "
                f"{item.candidate.site_packages} ({item.candidate.source})",
                flush=True,
            )
            completion = run_inventory(item, root, contract["modules"])
            if not completion["successful"]:
                print(
                    "FAIL: canonical Draft 2020-12 validation completed with "
                    f"{completion['failures']} failures and {completion['errors']} errors",
                    file=sys.stderr,
                )
                return 1
        print(
            f"PASS: trusted Python completed canonical Draft 2020-12 validation in "
            f"{len(validated)} package overlay(s)."
        )
        return 0
    except (
        BlockedError,
        AUDIT.ContractError,
        AUDIT.CI_CONTRACT.ContractError,
        OSError,
        UnicodeError,
    ) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    finally:
        close_validated(validated)


if __name__ == "__main__":
    raise SystemExit(main())
