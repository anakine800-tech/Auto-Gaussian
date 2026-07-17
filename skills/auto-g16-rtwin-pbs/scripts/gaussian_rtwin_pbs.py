#!/usr/bin/env python3
"""Safely operate Gaussian jobs through RTwin on the configured PBS server."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from gaussian_log import analyze_log_file, analyze_log_text, analyze_workflow_log_file
import protocol_selection
from runtime_config import setting


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAC_SSH_CONFIG = Path(
    setting(
        "AUTO_G16_RTWIN_SSH_CONFIG",
        "rtwin_ssh_config",
        os.environ.get(
            "GAUSSIAN_RTWIN_SSH_CONFIG",
            str(REPOSITORY_ROOT / "config" / "ssh_config"),
        ),
    )
)
DEFAULT_RTWIN_ALIAS = "rtwin"
DEFAULT_WINDOWS_ROOT = setting(
    "AUTO_G16_WINDOWS_PROJECT_ROOT", "windows_project_root", r"C:\GaussianProjects"
)
DEFAULT_WINDOWS_SERVER_CONFIG = setting(
    "AUTO_G16_WINDOWS_SERVER_CONFIG",
    "windows_server_config",
    r".ssh\gaussian_server_config",
)
DEFAULT_SERVER_ALIAS = "gaussian-server"
DEFAULT_REMOTE_ROOT = "/home/user100/SDL"
MAX_CORES = 44
MAX_MEMORY_BYTES = 120 * 1024**3
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
JOB_ID_RE = re.compile(r"^[0-9]+(?:\.[A-Za-z0-9_.-]+)?$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
INPUT_REVIEW_SCHEMA = "gaussian-input-draft-review/2"
INPUT_APPROVAL_SCHEMA = "gaussian-input-approval-receipt/1"
INPUT_APPROVAL_WORK_KINDS = {"ordinary", "minimum", "ts_pilot", "formal_ts"}
SPECIALIST_INPUT_WORK_KINDS = {"ts_scan", "irc_forward", "irc_reverse", "endpoint_reopt"}
ALL_WORK_KINDS = INPUT_APPROVAL_WORK_KINDS | SPECIALIST_INPUT_WORK_KINDS


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def decode(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp936", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def run(command: list[str], *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, input=input_bytes, capture_output=True)
    stdout = decode(result.stdout)
    stderr = decode(result.stderr)
    result.stdout = stdout  # type: ignore[assignment]
    result.stderr = stderr  # type: ignore[assignment]
    if check and result.returncode:
        detail = (stderr or stdout).strip()
        fail(f"command failed ({result.returncode}): {detail}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_stable_bytes(path: Path, label: str) -> tuple[Path, bytes, str]:
    """Read one regular non-symlink file from one descriptor and bind its bytes."""

    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable: {exc}") from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise ValueError(f"cannot open {label} without following a symlink: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(f"{label} changed while it was being read")
    data = b"".join(chunks)
    if len(data) != before.st_size:
        raise ValueError(f"{label} size changed while it was being read")
    return resolved, data, hashlib.sha256(data).hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def publish_new_json(
    path: Path,
    value: dict[str, Any],
    validator: Any | None = None,
) -> None:
    """Atomically publish immutable JSON without any overwrite window."""

    expanded = path.expanduser()
    if expanded.name in {"", ".", ".."}:
        raise ValueError("immutable artifact output must name a file")
    path = expanded.parent.resolve() / expanded.name
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if validator is not None:
            validator(temporary)
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise ValueError(f"refusing to overwrite immutable artifact: {path}") from None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def capture_submission_snapshot(source: Path, local_dir: Path) -> tuple[Path, str]:
    """Capture one unique, durable source snapshot before any approval replay."""

    resolved, data, digest = read_stable_bytes(source, "Gaussian submission source")
    if resolved.suffix.lower() not in {".gjf", ".com"}:
        raise ValueError("Gaussian submission source must end in .gjf or .com")
    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = Path(tempfile.mkdtemp(prefix=".submit-snapshot-", dir=local_dir))
    snapshot = snapshot_dir / resolved.name
    descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        raise
    directory_fd = os.open(snapshot_dir, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    _, captured, captured_digest = read_stable_bytes(snapshot, "Gaussian submission snapshot")
    if captured != data or captured_digest != digest:
        raise ValueError("Gaussian submission snapshot differs from the captured source bytes")
    return snapshot, digest


def verify_staged_submission(
    local_dir: Path,
    job: dict[str, Any],
    expected_report: dict[str, Any],
    input_approval: dict[str, Any],
    files: list[Path],
) -> dict[str, str]:
    """Recheck staged facts and file hashes immediately before any live action."""

    staged_input = local_dir / str(job["input"])
    before_path, _, before_digest = read_stable_bytes(staged_input, "staged Gaussian input")
    staged_report = parse_gaussian(before_path)
    _, _, after_digest = read_stable_bytes(staged_input, "staged Gaussian input")
    if before_digest != after_digest:
        fail("staged Gaussian input changed during final pre-network verification")
    if (
        _input_approval_facts(staged_report) != _input_approval_facts(expected_report)
        or job.get("input_sha256") != before_digest
        or (
            input_approval.get("status") == "validated_exact_input_approval"
            and input_approval.get("input_sha256") != before_digest
        )
    ):
        fail("staged Gaussian input no longer matches the exact input and live approval chain")
    expected: dict[str, str] = {}
    for path in files:
        _, _, digest = read_stable_bytes(path, f"staged upload file {path.name}")
        expected[path.name] = digest
    return expected


def assert_file_bindings_unchanged(files: list[Path], expected: dict[str, str]) -> None:
    for path in files:
        _, _, digest = read_stable_bytes(path, f"staged upload file {path.name}")
        if digest != expected.get(path.name):
            fail(f"staged upload file changed before transfer: {path.name}")


def validate_project(project: str) -> str:
    if not PROJECT_RE.fullmatch(project):
        fail("project must be 1-15 characters: letters, digits, '_' or '-', starting alphanumeric")
    return project


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        fail("invalid PBS job id")
    return job_id


def remote_project_dir(project: str) -> str:
    """Return the only permitted server-side project directory."""

    validate_project(project)
    return f"{DEFAULT_REMOTE_ROOT}/{project}"


def validate_transfer_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        fail(
            "server-bound filenames must contain only letters, digits, '_', '-', or '.', "
            "and must start alphanumeric"
        )
    return name


def remote_empty_directory_guard(project: str) -> str:
    """Create one empty, non-symlink project directory inside the fixed root."""

    remote_dir = remote_project_dir(project)
    return f"""set -euo pipefail
root='{DEFAULT_REMOTE_ROOT}'
jobdir='{remote_dir}'
root_real=$(realpath -e -- "$root")
if [ "$root_real" != "$root" ]; then
  echo 'REFUSING_OUTSIDE_SDL: allowed root is missing, moved, or a symlink' >&2
  exit 40
fi
if [ -L "$jobdir" ]; then
  echo 'REFUSING_SYMLINK: project directory is a symbolic link' >&2
  exit 41
fi
if [ -e "$jobdir" ]; then
  job_real=$(realpath -e -- "$jobdir")
  case "$job_real" in
    "$root"/*) ;;
    *) echo 'REFUSING_OUTSIDE_SDL: project resolves outside allowed root' >&2; exit 42 ;;
  esac
  if [ -n "$(find "$jobdir" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo 'REFUSING_OVERWRITE: server project directory is not empty' >&2
    exit 43
  fi
else
  mkdir -- "$jobdir"
fi
"""


def remote_existing_directory_guard(project: str) -> str:
    """Validate an existing project directory without changing server data."""

    remote_dir = remote_project_dir(project)
    return f"""set -euo pipefail
root='{DEFAULT_REMOTE_ROOT}'
jobdir='{remote_dir}'
root_real=$(realpath -e -- "$root")
if [ "$root_real" != "$root" ] || [ -L "$jobdir" ] || [ ! -d "$jobdir" ]; then
  echo 'REFUSING_OUTSIDE_SDL: invalid project directory' >&2
  exit 44
fi
job_real=$(realpath -e -- "$jobdir")
case "$job_real" in
  "$root"/*) ;;
  *) echo 'REFUSING_OUTSIDE_SDL: project resolves outside allowed root' >&2; exit 45 ;;
esac
"""


def parse_memory(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?B)\s*", value, re.I)
    if not match:
        fail(f"unsupported %mem value: {value!r}")
    number = float(match.group(1))
    power = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}[match.group(2).upper()]
    return int(number * 1024**power)


def normalize_route(route: str) -> str:
    lowered = " ".join(route.lower().split())
    lowered = re.sub(r"\s*=\s*", "=", lowered)
    lowered = re.sub(r"\s*,\s*", ",", lowered)
    lowered = re.sub(r"\(\s*", "(", lowered)
    return re.sub(r"\s*\)", ")", lowered)


def route_has_keyword(route: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword.lower())}(?=$|[=(\s])", normalize_route(route)) is not None


def route_keyword_count(route: str, keyword: str) -> int:
    return len(re.findall(rf"\b{re.escape(keyword.lower())}(?=$|[=(\s])", normalize_route(route)))


def route_has_option(route: str, keyword: str, option: str) -> bool:
    normalized = normalize_route(route)
    keyword = re.escape(keyword.lower())
    option = re.escape(option.lower())
    for match in re.finditer(rf"\b{keyword}\s*(?:=([^\s]+)|\(([^)]*)\))", normalized):
        values = (match.group(1) or match.group(2) or "").strip("()")
        if re.search(rf"(?:^|,){option}(?:,|$)", values) is not None:
            return True
    return False


def route_has_frequency(route: str) -> bool:
    return route_has_keyword(route, "freq") or route_has_keyword(route, "frequency")


def route_has_ts_optimization(route: str) -> bool:
    return any(route_has_option(route, "opt", value) for value in ("ts", "qst2", "qst3"))


def route_has_scan(route: str) -> bool:
    return route_has_keyword(route, "modredundant") or route_has_option(route, "opt", "scan") or route_has_option(route, "opt", "modredundant")


def classify_protected_work(route: str) -> str | None:
    if route_has_keyword(route, "irc"):
        return "irc"
    if route_has_scan(route):
        return "ts_scan"
    if route_has_ts_optimization(route):
        return "ts"
    return None


def route_is_ts(route: str) -> bool:
    return classify_protected_work(route) == "ts"


def _resource_tier(mem: str, nproc: int) -> str:
    tiers = {"simple": ("12GB", 8), "general": ("50GB", 22), "complex": ("120GB", 44)}
    for name, (expected_mem, expected_nproc) in tiers.items():
        if parse_memory(mem) == parse_memory(expected_mem) and nproc == expected_nproc:
            return name
    return "custom"


def _load_scientific_maturity() -> Any:
    skills_root = Path(__file__).resolve().parents[2]
    path = skills_root / "auto-g16-reaction-workflow" / "scripts" / "scientific_maturity.py"
    if not path.is_file():
        fail("scientific-maturity owner validator is unavailable")
    spec = importlib.util.spec_from_file_location("auto_g16_pbs_scientific_maturity", path)
    if spec is None or spec.loader is None:
        fail("scientific-maturity owner validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def _parse_strict_json_bytes(data: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"could not read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return value


def load_strict_json_with_hash(path: Path, label: str = "JSON artifact") -> tuple[Path, dict[str, Any], str, int]:
    resolved, data, digest = read_stable_bytes(path, label)
    return resolved, _parse_strict_json_bytes(data, resolved), digest, len(data)


def load_strict_json(path: Path) -> dict[str, Any]:
    return load_strict_json_with_hash(path)[1]


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def contract_payload_sha256(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _exact_fields(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        actual = set(value) if isinstance(value, dict) else set()
        raise ValueError(
            f"{label} fields differ: missing={sorted(fields - actual)}, unknown={sorted(actual - fields)}"
        )
    return value


def _input_approval_facts(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_sha256": report["input_sha256"],
        "route": report["route"],
        "mem": report["mem"],
        "nprocshared": report["nprocshared"],
        "charge": report["charge"],
        "multiplicity": report["multiplicity"],
        "atom_count": report["atom_count"],
        "elements": report["elements"],
    }


def input_approval_compatibility(report: dict[str, Any], work_kind: str | None) -> dict[str, Any]:
    """Classify only the input families fully represented by generic receipt /1."""

    if work_kind is None:
        return {
            "status": "missing_work_kind",
            "required": "an explicit --work-kind bound by input and live approvals",
        }
    if work_kind in SPECIALIST_INPUT_WORK_KINDS:
        return {
            "status": "blocked_missing_specialist_input_approval",
            "work_kind": work_kind,
            "reason": "this work kind requires its specialist owner manifest and exact raw-syntax/checkpoint review",
        }
    if work_kind not in INPUT_APPROVAL_WORK_KINDS:
        return {"status": "unsupported_work_kind", "work_kind": work_kind}

    route = str(report.get("route", ""))
    specialist_syntax = (
        report.get("link1_count", 0) != 0
        or report.get("route_section_count", 1) != 1
        or any(route_keyword_count(route, keyword) > 1 for keyword in ("opt", "geom", "guess"))
        or route_has_option(route, "opt", "qst2")
        or route_has_option(route, "opt", "qst3")
        or route_has_keyword(route, "irc")
        or route_has_scan(route)
        or route_has_option(route, "geom", "allcheck")
        or route_has_option(route, "geom", "check")
        or route_has_option(route, "guess", "read")
        or report.get("geometry_source") != "explicit_cartesian"
        or report.get("oldcheckpoint") is not None
    )
    if specialist_syntax:
        return {
            "status": "blocked_missing_specialist_input_approval",
            "work_kind": work_kind,
            "reason": "generic /1 covers only one self-contained Cartesian structure and no checkpoint-derived syntax",
        }

    protected = classify_protected_work(route)
    if work_kind in {"ts_pilot", "formal_ts"}:
        if protected != "ts" or not route_has_frequency(route):
            return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    elif protected is not None:
        return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    if work_kind == "minimum" and not route_has_keyword(route, "opt"):
        return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    if work_kind == "ordinary" and (route_has_keyword(route, "opt") or route_has_frequency(route)):
        return {"status": "work_kind_route_mismatch", "work_kind": work_kind}
    return {"status": "supported_generic_v1", "work_kind": work_kind}


def _validate_protocol_binding_shape(value: Any) -> dict[str, Any]:
    binding = _exact_fields(
        value,
        {
            "options_sha256", "options_payload_sha256", "selection_sha256",
            "selection_payload_sha256", "selected_option", "used_profile_ids", "used_tasks",
        },
        "input review protocol_binding",
    )
    for key in ("options_sha256", "options_payload_sha256", "selection_sha256", "selection_payload_sha256"):
        if not isinstance(binding[key], str) or SHA256_RE.fullmatch(binding[key]) is None:
            raise ValueError(f"input review protocol_binding.{key} is invalid")
    selected = _exact_fields(
        binding["selected_option"], {"tier", "option_id", "option_payload_sha256"},
        "input review selected_option",
    )
    if not all(isinstance(selected[key], str) and selected[key] for key in ("tier", "option_id")):
        raise ValueError("input review selected option identity is invalid")
    if not isinstance(selected["option_payload_sha256"], str) or SHA256_RE.fullmatch(selected["option_payload_sha256"]) is None:
        raise ValueError("input review selected option payload SHA-256 is invalid")
    profiles = binding["used_profile_ids"]
    if not isinstance(profiles, list) or not profiles or len(profiles) != len(set(profiles)) or not all(isinstance(item, str) and item for item in profiles):
        raise ValueError("input review used_profile_ids must be unique non-empty strings")
    tasks = binding["used_tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("input review used_tasks must be non-empty")
    for task in tasks:
        item = _exact_fields(task, {"task_index", "stage_type", "profile_id"}, "input review used task")
        if not isinstance(item["task_index"], int) or isinstance(item["task_index"], bool) or item["task_index"] < 0:
            raise ValueError("input review task_index is invalid")
        if not isinstance(item["stage_type"], str) or not item["stage_type"] or item["profile_id"] not in profiles:
            raise ValueError("input review used task is invalid")
    indices = [item["task_index"] for item in tasks]
    if len(indices) != len(set(indices)):
        raise ValueError("input review used task indices must be unique")
    return binding


def _validate_route_profile_mapping_shape(value: Any, approved_route: str) -> dict[str, Any]:
    mapping = _exact_fields(
        value, {"exact_route", "method", "basis", "solvent", "scf", "tasks", "explicit_confirmation"},
        "input review route_profile_mapping",
    )
    if mapping["exact_route"] != approved_route or mapping["explicit_confirmation"] is not True:
        raise ValueError("input review route/profile mapping is not explicitly bound to the exact route")
    route_lower = " ".join(approved_route.lower().split())
    for key in ("method", "basis", "solvent", "scf"):
        item = _exact_fields(
            mapping[key], {"route_value", "profile_id", "selected_value", "human_confirmed"},
            f"input review route mapping {key}",
        )
        if not isinstance(item["route_value"], str) or not item["route_value"].strip() or not isinstance(item["profile_id"], str) or not item["profile_id"]:
            raise ValueError(f"input review {key} route/profile value is missing")
        if item["human_confirmed"] is not True:
            raise ValueError(f"input review {key} mapping lacks human confirmation")
        route_value = item["route_value"].lower()
        if key in {"method", "basis"} and route_value not in route_lower:
            raise ValueError(f"input review {key} route value is absent from the exact route")
        if key == "solvent" and route_value == "none" and ("scrf" in route_lower or "solvent" in route_lower):
            raise ValueError("input review claims no solvent but the route contains solvation syntax")
        if key == "scf" and route_value == "default" and re.search(r"\bscf\b", route_lower):
            raise ValueError("input review claims default SCF but the route contains explicit SCF syntax")
    tasks = mapping["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("input review route task mappings are missing")
    for task in tasks:
        item = _exact_fields(
            task, {"task_index", "stage_type", "profile_id", "route_evidence", "human_confirmed"},
            "input review route task mapping",
        )
        evidence = item["route_evidence"]
        if item["human_confirmed"] is not True or not isinstance(evidence, list) or not evidence or len(evidence) != len(set(evidence)):
            raise ValueError("input review route task mapping is not explicitly confirmed")
        if not all(token in {"opt_ts", "minimum_opt", "frequency", "single_point"} for token in evidence):
            raise ValueError("input review task evidence must use deterministic route predicates")
    return mapping


def validate_input_review(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("input review must not be a symlink")
    path = expanded.resolve()
    review = load_strict_json(path)
    _exact_fields(
        review,
        {
            "schema", "review_id", "work_kind", "protocol_task_types", "protocol_binding",
            "route_profile_mapping", "protocol_family_completion", "approved_input", "decision", "calculation_ready",
            "no_submission_authorization", "payload_sha256",
        },
        "input-draft review /2",
    )
    if review["schema"] != INPUT_REVIEW_SCHEMA:
        raise ValueError(f"input review schema must be {INPUT_REVIEW_SCHEMA}")
    if review["work_kind"] not in INPUT_APPROVAL_WORK_KINDS:
        raise ValueError("input review work_kind is unsupported")
    if not isinstance(review["review_id"], str) or not review["review_id"].strip():
        raise ValueError("input review review_id is missing")
    task_types = review["protocol_task_types"]
    if not isinstance(task_types, list) or not task_types or not all(isinstance(item, str) and item.strip() for item in task_types):
        raise ValueError("input review protocol_task_types must be a non-empty string array")
    if len(task_types) != len(set(task_types)):
        raise ValueError("input review protocol_task_types contains duplicates")
    _validate_protocol_binding_shape(review["protocol_binding"])
    if review["protocol_family_completion"] is not False:
        raise ValueError("one input review must not claim whole protocol-family completion")
    facts = _exact_fields(
        review["approved_input"],
        {"input_sha256", "route", "mem", "nprocshared", "charge", "multiplicity", "atom_count", "elements"},
        "input review approved_input",
    )
    if not isinstance(facts["input_sha256"], str) or SHA256_RE.fullmatch(facts["input_sha256"]) is None:
        raise ValueError("input review SHA-256 is invalid")
    if not isinstance(facts["route"], str) or not facts["route"].startswith("#"):
        raise ValueError("input review route is invalid")
    if not isinstance(facts["mem"], str) or parse_memory(facts["mem"]) <= 0:
        raise ValueError("input review memory is invalid")
    for key in ("nprocshared", "multiplicity", "atom_count"):
        if not isinstance(facts[key], int) or isinstance(facts[key], bool) or facts[key] <= 0:
            raise ValueError(f"input review {key} is invalid")
    if not isinstance(facts["charge"], int) or isinstance(facts["charge"], bool):
        raise ValueError("input review charge is invalid")
    if not isinstance(facts["elements"], dict) or not facts["elements"]:
        raise ValueError("input review elements are missing")
    if sum(facts["elements"].values()) != facts["atom_count"]:
        raise ValueError("input review element counts differ from atom_count")
    _validate_route_profile_mapping_shape(review["route_profile_mapping"], facts["route"])
    decision = _exact_fields(
        review["decision"],
        {"status", "explicit_confirmation", "reviewer", "reviewed_at", "rationale"},
        "input review decision",
    )
    if decision["status"] != "accepted_exact_input" or decision["explicit_confirmation"] is not True:
        raise ValueError("input review is not explicitly accepted")
    for key in ("reviewer", "reviewed_at", "rationale"):
        if not isinstance(decision[key], str) or not decision[key].strip():
            raise ValueError(f"input review decision.{key} is missing")
    if review["calculation_ready"] is not False or review["no_submission_authorization"] is not True:
        raise ValueError("input review authority boundary changed")
    if review["payload_sha256"] != contract_payload_sha256(review):
        raise ValueError("input review payload SHA-256 is invalid")
    return review


def finalize_input_review(draft_path: Path, output: Path) -> dict[str, Any]:
    if draft_path.expanduser().is_symlink():
        raise ValueError("input review draft must not be a symlink")
    draft = load_strict_json(draft_path)
    if draft.get("payload_sha256") is not None:
        raise ValueError("input review draft payload_sha256 must be null before finalization")
    finalized = copy.deepcopy(draft)
    finalized["payload_sha256"] = contract_payload_sha256(finalized)
    expanded_output = output.expanduser()
    output = expanded_output.parent.resolve() / expanded_output.name
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing to overwrite input review: {output}")
    publish_new_json(output, finalized, validate_input_review)
    return finalized


def _artifact_binding(path: Path, root: Path, schema: str, payload: str) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"bound {schema} artifact must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise ValueError(f"bound {schema} artifact is missing or a symlink")
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("all input-approval artifacts must share one artifact root") from None
    return {
        "path": relative.as_posix(), "sha256": sha256(resolved),
        "size_bytes": resolved.stat().st_size, "schema": schema,
        "payload_sha256": payload,
    }


def _resolve_portable_binding_path(relative_value: Any, owner: Path, label: str) -> Path:
    relative = Path(str(relative_value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"{label} path must be portable and relative")
    root = owner.parent.resolve()
    raw = root / relative
    cursor = raw
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f"{label} path must not traverse a symlink")
        cursor = cursor.parent
    try:
        resolved = raw.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise ValueError(f"{label} path resolves outside its artifact root or is missing") from None
    return resolved


def _resolve_artifact_binding(binding: Any, owner: Path, schema: str) -> tuple[Path, dict[str, Any]]:
    value = _exact_fields(binding, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, "input-approval binding")
    if value["schema"] != schema:
        raise ValueError(f"input-approval binding schema must be {schema}")
    path = _resolve_portable_binding_path(value["path"], owner, "input-approval binding")
    path, document, digest, size = load_strict_json_with_hash(path, "input-approval bound artifact")
    if digest != value["sha256"] or size != value["size_bytes"]:
        raise ValueError("input-approval bound artifact bytes changed")
    if document.get("schema") != schema:
        raise ValueError("input-approval bound artifact schema changed")
    return path, document


def _input_blob_binding(path: Path, root: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("approved Gaussian input must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise ValueError("approved Gaussian input is missing or a symlink")
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("approved Gaussian input must share the receipt artifact root") from None
    return {"path": relative.as_posix(), "sha256": sha256(resolved), "size_bytes": resolved.stat().st_size}


def _resolve_input_blob(binding: Any, owner: Path) -> Path:
    value = _exact_fields(binding, {"path", "sha256", "size_bytes"}, "input-approval input binding")
    path = _resolve_portable_binding_path(value["path"], owner, "input-approval input")
    path, data, digest = read_stable_bytes(path, "input-approval exact input")
    if digest != value["sha256"] or len(data) != value["size_bytes"]:
        raise ValueError("input-approval exact input changed")
    return path


def _assert_work_kind_matches_route(work_kind: str, report: dict[str, Any]) -> None:
    compatibility = input_approval_compatibility(report, work_kind)
    if compatibility["status"] != "supported_generic_v1":
        raise ValueError(f"{compatibility['status']}: {compatibility.get('reason', 'route/work_kind mismatch')}")


def _validate_protocol_consumption(
    binding: dict[str, Any],
    options_path: Path, selection_path: Path, selection: dict[str, Any],
    options: dict[str, Any], selected: dict[str, Any],
) -> None:
    profiles = selected.get("method_profiles")
    tasks = selected.get("task_plan")
    if not isinstance(profiles, list) or not profiles or not isinstance(tasks, list) or not tasks:
        raise ValueError("selected option has no method profiles or task plan")
    expected_identity = {
        "options_sha256": sha256(options_path),
        "options_payload_sha256": options["proposal_payload_sha256"],
        "selection_sha256": sha256(selection_path),
        "selection_payload_sha256": selection["selection_payload_sha256"],
        "selected_option": copy.deepcopy(selection["selected_option"]),
    }
    for key, value in expected_identity.items():
        if binding.get(key) != value:
            raise ValueError("input review does not bind the exact options, selection and selected option")
    available_profiles = {profile["profile_id"] for profile in profiles}
    consumed_profiles = set(binding["used_profile_ids"])
    if not consumed_profiles <= available_profiles:
        raise ValueError("input review consumes a profile outside the selected option")
    referenced_profiles: set[str] = set()
    for consumed in binding["used_tasks"]:
        index = consumed["task_index"]
        if index >= len(tasks):
            raise ValueError("input review consumes a task index outside the selected option")
        selected_task = tasks[index]
        expected_task = {
            "task_index": index,
            "stage_type": selected_task["stage_type"],
            "profile_id": selected_task["profile_id"],
        }
        if consumed != expected_task:
            raise ValueError("input review consumed task differs from the selected option task")
        referenced_profiles.add(consumed["profile_id"])
    if referenced_profiles != consumed_profiles:
        raise ValueError("input review used profiles must exactly equal profiles referenced by consumed tasks")


def _replay_route_profile_mapping(review: dict[str, Any], selected: dict[str, Any]) -> None:
    binding = review["protocol_binding"]
    mapping = review["route_profile_mapping"]
    profiles = {profile["profile_id"]: profile for profile in selected["method_profiles"]}
    field_names = {
        "method": "functional_or_method", "basis": "basis_stack",
        "solvent": "solvation", "scf": "scf",
    }
    for key, field in field_names.items():
        item = mapping[key]
        profile = profiles.get(item["profile_id"])
        if profile is None or item["profile_id"] not in binding["used_profile_ids"]:
            raise ValueError(f"input review {key} mapping names an unselected profile")
        if item["selected_value"] != profile.get(field):
            raise ValueError(f"input review {key} mapping differs from the selected profile payload")
    expected_tasks = binding["used_tasks"]
    mapped_tasks = [
        {"task_index": task["task_index"], "stage_type": task["stage_type"], "profile_id": task["profile_id"]}
        for task in mapping["tasks"]
    ]
    if mapped_tasks != expected_tasks:
        raise ValueError("input review route task mapping differs from the selected task plan")
    _assert_consumed_tasks_match_route(mapping["exact_route"], expected_tasks, mapping["tasks"])


def _assert_consumed_tasks_match_route(
    route: str,
    consumed_tasks: list[dict[str, Any]],
    route_mappings: list[dict[str, Any]],
) -> None:
    if len(consumed_tasks) != len(route_mappings):
        raise ValueError("consumed task and route-mapping counts differ")
    for consumed, mapping in zip(consumed_tasks, route_mappings):
        stage = str(consumed["stage_type"]).lower()
        if stage == "single_guess_ts_opt_freq":
            expected = {"opt_ts", "frequency"}
            valid = route_has_ts_optimization(route) and route_has_frequency(route)
        elif "transition_state" in stage:
            expected = {"opt_ts"}
            valid = route_has_ts_optimization(route)
        elif "harmonic_frequency" in stage or stage in {"frequency", "freq"}:
            expected = {"frequency"}
            valid = route_has_frequency(route)
        elif "minimum" in stage or "geometry_optimization" in stage or stage in {"optimization", "opt"}:
            expected = {"minimum_opt"}
            valid = route_has_keyword(route, "opt") and not route_has_ts_optimization(route) and not route_has_scan(route)
        elif "single_point" in stage:
            expected = {"single_point"}
            valid = not any((route_has_keyword(route, "opt"), route_has_frequency(route), route_has_keyword(route, "irc")))
        else:
            raise ValueError(f"selected task stage_type has no generic /1 route predicate: {stage}")
        if not valid or set(mapping["route_evidence"]) != expected:
            raise ValueError(f"selected task {stage} does not deterministically match the exact route")


def _formula_element_counts(formula: Any) -> dict[str, int]:
    if not isinstance(formula, str) or not formula:
        raise ValueError("protocol request formula is missing")
    tokens = re.findall(r"([A-Z][a-z]?)([0-9]*)", formula)
    if not tokens or "".join(f"{element}{count}" for element, count in tokens) != formula:
        raise ValueError("generic /1 cannot derive exact element counts from the protocol request formula")
    counts: Counter[str] = Counter()
    for element, count in tokens:
        value = int(count) if count else 1
        if value < 1:
            raise ValueError("protocol request formula contains a non-positive element count")
        counts[element] += value
    return dict(sorted(counts.items()))


def _assert_protocol_structure_scope(request_structure: Any, report: dict[str, Any]) -> None:
    if not isinstance(request_structure, dict):
        raise ValueError("protocol request structure scope is missing")
    expected_counts = _formula_element_counts(request_structure.get("formula"))
    if (
        request_structure.get("charge") != report["charge"]
        or request_structure.get("multiplicity") != report["multiplicity"]
        or request_structure.get("atom_count") != report["atom_count"]
        or set(request_structure.get("elements", [])) != set(report["elements"])
        or expected_counts != report["elements"]
        or sum(expected_counts.values()) != report["atom_count"]
    ):
        raise ValueError("protocol request charge/multiplicity/complete element counts differ from the exact input")


def _make_input_approval_receipt(
    options_path: Path,
    selection_path: Path,
    review_path: Path,
    input_path: Path,
    output: Path,
    receipt_id: str,
) -> dict[str, Any]:
    selection, options, selected = protocol_selection.load_validated_selection(selection_path, options_path)
    review = validate_input_review(review_path)
    report = parse_gaussian(input_path)
    _assert_work_kind_matches_route(review["work_kind"], report)
    if review["approved_input"] != _input_approval_facts(report):
        raise ValueError("input review facts differ from the exact Gaussian input")
    if review["protocol_task_types"] != selection["scope_binding"]["task_types"]:
        raise ValueError("input review task types differ from the exact protocol selection")
    _validate_protocol_consumption(
        review["protocol_binding"], options_path, selection_path, selection, options, selected
    )
    _replay_route_profile_mapping(review, selected)
    request_structure = options.get("request_snapshot", {}).get("structure", {})
    _assert_protocol_structure_scope(request_structure, report)
    if review["work_kind"] in {"ts_pilot", "formal_ts"} and review["protocol_task_types"] != [
        "transition_state_optimization", "harmonic_frequency"
    ]:
        raise ValueError("generic single-guess TS approval requires the exact TS optimization + frequency task family")
    if review["work_kind"] == "minimum" and "geometry_optimization" not in review["protocol_task_types"]:
        raise ValueError("minimum approval requires a selected geometry_optimization task")
    resources = selected.get("resources", {})
    if resources.get("cores") != report["nprocshared"]:
        raise ValueError("selected protocol cores differ from the exact input")
    mem_gb = resources.get("mem_gb")
    if not isinstance(mem_gb, (int, float)) or isinstance(mem_gb, bool) or parse_memory(report["mem"]) != int(float(mem_gb) * 1024**3):
        raise ValueError("selected protocol memory differs from the exact input")
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise ValueError("input approval receipt_id is missing")
    root = output.parent.resolve()
    document = {
        "schema": INPUT_APPROVAL_SCHEMA,
        "receipt_id": receipt_id,
        "work_kind": review["work_kind"],
        "protocol_task_types": review["protocol_task_types"],
        "sources": {
            "protocol_options": _artifact_binding(options_path, root, "gaussian-protocol-options/1", options["proposal_payload_sha256"]),
            "protocol_selection": _artifact_binding(selection_path, root, "gaussian-protocol-selection/1", selection["selection_payload_sha256"]),
            "input_review": _artifact_binding(review_path, root, INPUT_REVIEW_SCHEMA, review["payload_sha256"]),
        },
        "input": _input_blob_binding(input_path, root),
        "protocol_review_binding": {
            "input_review_payload_sha256": review["payload_sha256"],
            "options_payload_sha256": review["protocol_binding"]["options_payload_sha256"],
            "selection_payload_sha256": review["protocol_binding"]["selection_payload_sha256"],
            "selected_option_payload_sha256": review["protocol_binding"]["selected_option"]["option_payload_sha256"],
            "consumed_profile_ids": copy.deepcopy(review["protocol_binding"]["used_profile_ids"]),
            "consumed_task_indices": [task["task_index"] for task in review["protocol_binding"]["used_tasks"]],
            "exact_route": review["route_profile_mapping"]["exact_route"],
            "route_profile_mapping_sha256": canonical_value_sha256(review["route_profile_mapping"]),
            "explicit_confirmation": True,
        },
        "protocol_family_completion": False,
        "approved_input": _input_approval_facts(report),
        "decision": {"status": "approved_exact_input", "explicit_confirmation": True},
        "single_exact_input_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    document["payload_sha256"] = contract_payload_sha256(document)
    return document


def build_input_approval_receipt(
    options_path: Path,
    selection_path: Path,
    review_path: Path,
    input_path: Path,
    output: Path,
    receipt_id: str,
) -> dict[str, Any]:
    raw_sources = (options_path, selection_path, review_path, input_path)
    if any(path.expanduser().is_symlink() for path in raw_sources):
        raise ValueError("input-approval source artifacts must not be symlinks")
    expanded_output = output.expanduser()
    output = expanded_output.parent.resolve() / expanded_output.name
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing to overwrite input approval receipt: {output}")
    document = _make_input_approval_receipt(
        options_path.expanduser().resolve(), selection_path.expanduser().resolve(),
        review_path.expanduser().resolve(), input_path.expanduser().resolve(), output, receipt_id,
    )
    publish_new_json(output, document, validate_input_approval_receipt)
    return document


def validate_input_approval_receipt(
    receipt_path: Path,
    *,
    input_path: Path | None = None,
    report: dict[str, Any] | None = None,
    work_kind: str | None = None,
    _document: dict[str, Any] | None = None,
    _resolved_path: Path | None = None,
) -> dict[str, Any]:
    if _document is None:
        expanded_receipt = receipt_path.expanduser()
        if expanded_receipt.is_symlink():
            raise ValueError("input-approval receipt must not be a symlink")
        receipt_path, document, _, _ = load_strict_json_with_hash(
            expanded_receipt, "input-approval receipt"
        )
    else:
        if _resolved_path is None:
            raise ValueError("internal input-approval path binding is missing")
        receipt_path = _resolved_path
        document = _document
    _exact_fields(
        document,
        {
            "schema", "receipt_id", "work_kind", "protocol_task_types", "sources", "input",
            "protocol_review_binding", "protocol_family_completion", "approved_input", "decision", "single_exact_input_only",
            "calculation_ready", "no_submission_authorization", "payload_sha256",
        },
        "input-approval receipt",
    )
    if document["schema"] != INPUT_APPROVAL_SCHEMA:
        raise ValueError(f"input approval schema must be {INPUT_APPROVAL_SCHEMA}")
    if document["payload_sha256"] != contract_payload_sha256(document):
        raise ValueError("input approval receipt payload SHA-256 is invalid")
    if document["single_exact_input_only"] is not True or document["calculation_ready"] is not False or document["no_submission_authorization"] is not True:
        raise ValueError("input approval receipt authority boundary changed")
    if document["protocol_family_completion"] is not False:
        raise ValueError("one input-approval receipt must not claim whole protocol-family completion")
    if document["decision"] != {"status": "approved_exact_input", "explicit_confirmation": True}:
        raise ValueError("input approval receipt decision changed")
    sources = _exact_fields(document["sources"], {"protocol_options", "protocol_selection", "input_review"}, "input-approval sources")
    options_path, options = _resolve_artifact_binding(sources["protocol_options"], receipt_path, "gaussian-protocol-options/1")
    selection_path, selection = _resolve_artifact_binding(sources["protocol_selection"], receipt_path, "gaussian-protocol-selection/1")
    review_path, review = _resolve_artifact_binding(sources["input_review"], receipt_path, INPUT_REVIEW_SCHEMA)
    if options.get("proposal_payload_sha256") != sources["protocol_options"]["payload_sha256"]:
        raise ValueError("input approval protocol-options payload changed")
    if selection.get("selection_payload_sha256") != sources["protocol_selection"]["payload_sha256"]:
        raise ValueError("input approval protocol-selection payload changed")
    if review.get("payload_sha256") != sources["input_review"]["payload_sha256"]:
        raise ValueError("input approval review payload changed")
    bound_input = _resolve_input_blob(document["input"], receipt_path)
    expected = _make_input_approval_receipt(
        options_path, selection_path, review_path, bound_input, receipt_path, document["receipt_id"]
    )
    if expected != document:
        raise ValueError("input approval receipt differs from owner reconstruction")
    if input_path is not None:
        _, current_bytes, current_digest = read_stable_bytes(input_path, "current Gaussian input snapshot")
        if current_digest != document["input"]["sha256"] or len(current_bytes) != document["input"]["size_bytes"]:
            raise ValueError("input approval is bound to different Gaussian input bytes")
    if report is not None and document["approved_input"] != _input_approval_facts(report):
        raise ValueError("input approval is bound to different current input facts")
    if work_kind is not None and document["work_kind"] != work_kind:
        raise ValueError("input approval work_kind differs from the requested submission")
    return document


def validate_input_approval(
    approval_path: Path,
    input_path: Path,
    report: dict[str, Any],
    work_kind: str,
) -> dict[str, Any]:
    try:
        expanded_approval = approval_path.expanduser()
        if expanded_approval.is_symlink():
            raise ValueError("input-approval receipt must not be a symlink")
        resolved_approval, loaded_document, approval_digest, _ = load_strict_json_with_hash(
            expanded_approval, "input-approval receipt"
        )
        document = validate_input_approval_receipt(
            resolved_approval, input_path=input_path, report=report, work_kind=work_kind,
            _document=loaded_document, _resolved_path=resolved_approval,
        )
        return {
            "status": "validated_exact_input_approval",
            "schema": document["schema"],
            "sha256": approval_digest,
            "payload_sha256": document["payload_sha256"],
            "input_sha256": report["input_sha256"],
            "work_kind": document["work_kind"],
            "protocol_options_schema": document["sources"]["protocol_options"]["schema"],
            "protocol_selection_schema": document["sources"]["protocol_selection"]["schema"],
            "input_review_schema": document["sources"]["input_review"]["schema"],
            "no_submission_authorization": True,
        }
    except SystemExit:
        raise
    except Exception as exc:
        fail(f"exact input-approval gate blocked submission: {exc}")
    raise AssertionError("unreachable")


def live_approval_summary(
    project: str,
    report: dict[str, Any],
    maturity: dict[str, Any] | None,
    work_kind: str | None = None,
    input_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "project": project,
        "remote_workdir": remote_project_dir(project),
        "input_sha256": report["input_sha256"],
        "protocol": {
            "route": report["route"],
            "mem": report["mem"],
            "nproc": report["nprocshared"],
        },
        "charge": report["charge"],
        "multiplicity": report["multiplicity"],
    }
    if work_kind is not None:
        summary["work_kind"] = work_kind
    if input_approval is not None:
        summary["input_approval"] = input_approval
    return {"scientific_maturity": maturity, **summary} if maturity is not None else summary


def expected_live_approval_scope(summary: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    expected = {
        "project": summary["project"],
        "remote_workdir": summary["remote_workdir"],
        "input_sha256": summary["input_sha256"],
        "route": summary["protocol"]["route"],
        "mem": summary["protocol"]["mem"],
        "nprocshared": summary["protocol"]["nproc"],
        "charge": summary["charge"],
        "multiplicity": summary["multiplicity"],
    }
    has_new_binding = "work_kind" in summary or "input_approval" in summary
    if has_new_binding:
        if "work_kind" not in summary or "input_approval" not in summary:
            fail("live approval /3 requires both work_kind and exact input-approval receipt binding")
        input_approval = summary["input_approval"]
        if not isinstance(input_approval, dict) or input_approval.get("status") not in {None, "validated_exact_input_approval"}:
            fail("live approval /3 requires a validated exact input-approval receipt")
        exact_input_approval = {
            key: input_approval.get(key)
            for key in ("schema", "sha256", "payload_sha256", "input_sha256", "work_kind")
        }
        if (
            exact_input_approval["schema"] != INPUT_APPROVAL_SCHEMA
            or exact_input_approval["input_sha256"] != summary["input_sha256"]
            or exact_input_approval["work_kind"] != summary["work_kind"]
            or summary["work_kind"] not in ALL_WORK_KINDS
            or any(
                not isinstance(exact_input_approval[key], str)
                or SHA256_RE.fullmatch(exact_input_approval[key]) is None
                for key in ("sha256", "payload_sha256", "input_sha256")
            )
        ):
            fail("live approval /3 input-approval binding differs from the current exact input/work_kind")
        expected["work_kind"] = summary["work_kind"]
        expected["input_approval"] = exact_input_approval
        expected_schema = "auto-g16-live-submission-approval/3"
    else:
        expected_schema = (
            "auto-g16-live-submission-approval/2"
            if "scientific_maturity" in summary
            else "auto-g16-live-submission-approval/1"
        )
    if "scientific_maturity" in summary:
        maturity = summary["scientific_maturity"]
        exact_authorization = maturity.get("exact_action_authorization")
        if not isinstance(exact_authorization, dict):
            fail("TS live approval requires an exact scientific action authorization")
        expected["scientific_maturity"] = {
            "edge_id": maturity["edge_id"],
            "pilot": maturity["pilot"],
            "maturity_gate_sha256": maturity["maturity_gate_sha256"],
            "maturity_gate_payload_sha256": maturity["maturity_gate_payload_sha256"],
            "node_id": maturity["node_id"],
            "scientific_action_authorization_sha256": exact_authorization["sha256"],
            "scientific_action_authorization_payload_sha256": exact_authorization["payload_sha256"],
        }
    return expected_schema, expected


def _validate_live_approval_document(approval: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    expected_schema, expected = expected_live_approval_scope(summary)
    if approval.get("schema") != expected_schema:
        fail("live approval record has the wrong schema")
    if approval.get("decision") != "approved" or approval.get("explicit_confirmation") is not True:
        fail("live approval record lacks an explicit approved decision")
    if approval.get("scope") != expected:
        fail("live approval scope does not exactly match the current preflight")
    if approval.get("authorizations") != {
        "create_server_directory": True,
        "submit": True,
        "retry": False,
        "cancel": False,
        "cleanup": False,
        "delete_server_data": False,
    }:
        fail("live approval authorization boundary changed")
    return approval


def validate_live_approval_binding(path: Path, summary: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        expanded = path.expanduser()
        if expanded.is_symlink():
            raise ValueError("live approval record must not be a symlink")
        _, approval, digest, _ = load_strict_json_with_hash(expanded, "live approval record")
    except ValueError as exc:
        fail(f"cannot read live approval record: {exc}")
    return _validate_live_approval_document(approval, summary), digest


def validate_live_approval(path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    return validate_live_approval_binding(path, summary)[0]


def audit_scientific_maturity(args: Any, report: dict[str, Any], action: str) -> dict[str, Any] | None:
    protected = classify_protected_work(report["route"])
    work_kind = getattr(args, "work_kind", None)
    if protected is None:
        if work_kind not in {None, "ordinary", "minimum"}:
            fail(f"--work-kind {work_kind} does not match an ordinary/minimum route")
        return None
    expected_kinds = {
        "ts": {"ts_pilot", "formal_ts"},
        "ts_scan": {"ts_scan"},
        "irc": {"irc_forward", "irc_reverse"},
    }[protected]
    if work_kind not in expected_kinds:
        fail(f"protected {protected} route requires explicit --work-kind in {sorted(expected_kinds)}")
    pilot = work_kind in {"ts_pilot", "ts_scan"}
    if bool(getattr(args, "pilot", False)) != pilot:
        fail(f"--pilot must be {'set' if pilot else 'unset'} for --work-kind {work_kind}")
    maturity_action = "irc_input" if protected == "irc" else action
    gate_value = getattr(args, "scientific_maturity", None)
    edge_id = getattr(args, "edge_id", None)
    node_id = getattr(args, "node_id", None)
    if not gate_value or not edge_id or not node_id:
        fail("protected input/submission requires --scientific-maturity, --edge-id, and exact --node-id with two accepted Gaussian minima")
    tier = _resource_tier(report["mem"], report["nprocshared"])
    if tier == "custom":
        fail("TS maturity gate requires an exact reviewed simple/general/complex resource tier")
    maturity = _load_scientific_maturity()
    try:
        check = maturity.assert_action(
            Path(gate_value).expanduser().resolve(),
            edge_id,
            maturity_action,
            pilot=pilot,
            resource_tier=tier,
            node_id=node_id,
        )
        if action == "ts_submission":
            authorization_value = getattr(args, "scientific_action_authorization", None)
            if not authorization_value:
                fail("protected TS/scan submission requires one exact --scientific-action-authorization")
            authorization = maturity.validate_action_authorization(
                Path(authorization_value).expanduser().resolve(),
                gate_path=Path(gate_value).expanduser().resolve(),
                input_sha256=report["input_sha256"],
                edge_id=edge_id,
                node_id=node_id,
                project=args.project,
                work_kind=work_kind,
                resource_tier=tier,
            )
            check["exact_action_authorization"] = {
                "sha256": sha256(Path(authorization_value).expanduser().resolve()),
                "payload_sha256": authorization["payload_sha256"],
                "node_id": authorization["scope"]["node_id"],
                "project": authorization["scope"]["project"],
                "input_sha256": authorization["input"]["sha256"],
                "no_submission_authorization": True,
            }
        return check
    except Exception as exc:
        fail(f"scientific-maturity gate blocked {maturity_action}: {exc}")
    return None


def parse_gaussian(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"input does not exist: {path}")
    if path.suffix.lower() not in {".gjf", ".com"}:
        fail("Gaussian input must end in .gjf or .com")
    text = path.read_text(encoding="utf-8")
    segments = re.split(r"(?im)^\s*--link1--\s*$", text)
    link1_count = len(segments) - 1
    route_section_count = len(re.findall(r"(?m)^\s*#", text))
    lines = segments[0].splitlines()
    if not text.endswith("\n\n"):
        fail("Gaussian input must end with a trailing blank line")

    link0: dict[str, str] = {}
    for line in lines:
        if line.startswith("%") and "=" in line:
            key, value = line[1:].split("=", 1)
            link0[key.strip().lower()] = value.strip()
    for required in ("chk", "mem", "nprocshared"):
        if not link0.get(required):
            fail(f"missing %{required}= link-0 directive")
    checkpoint = link0["chk"]
    if Path(checkpoint).name != checkpoint or "/" in checkpoint or "\\" in checkpoint:
        fail("%chk must be a local basename inside the job directory")
    oldcheckpoint = link0.get("oldchk")
    if oldcheckpoint:
        if Path(oldcheckpoint).name != oldcheckpoint or "/" in oldcheckpoint or "\\" in oldcheckpoint:
            fail("%oldchk must be a local basename inside the job directory")
        if oldcheckpoint == checkpoint:
            fail("%oldchk and %chk must use distinct basenames")
    try:
        nproc = int(link0["nprocshared"])
    except ValueError:
        fail("%nprocshared must be an integer")
    if not 1 <= nproc <= MAX_CORES:
        fail(f"%nprocshared must be between 1 and {MAX_CORES}")
    memory_bytes = parse_memory(link0["mem"])
    if memory_bytes > MAX_MEMORY_BYTES:
        fail("%mem exceeds the server's 120 GB physical-memory ceiling")

    route_start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    if route_start is None:
        fail("missing Gaussian route section")
    route_lines: list[str] = []
    i = route_start
    while i < len(lines) and lines[i].strip():
        route_lines.append(lines[i].strip())
        i += 1
    route = " ".join(route_lines)
    geom_allcheck = bool(re.search(r"\bgeom\s*=\s*allcheck\b", route, re.I))

    manifest_path = path.with_suffix(".json")
    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"could not read Gaussian companion manifest: {exc}")

    while i < len(lines) and not lines[i].strip():
        i += 1
    elements: Counter[str] = Counter()
    atom_order: list[dict[str, Any]] | None = None
    oldcheckpoint_sha256: str | None = None
    if geom_allcheck:
        if any(line.strip() for line in lines[i:]):
            fail("Geom=AllCheck input must omit title, charge/multiplicity, and explicit coordinates")
        if not oldcheckpoint:
            fail("Geom=AllCheck input requires an explicit %oldchk reviewed checkpoint")
        if not manifest or manifest.get("schema") != "gaussian-allcheck-input-manifest/1":
            fail("Geom=AllCheck input requires a gaussian-allcheck-input-manifest/1 companion")
        if manifest.get("geometry_source") != "geom_allcheck_from_reviewed_checkpoint" or manifest.get("no_explicit_molecule_specification") is not True:
            fail("AllCheck companion manifest does not certify coordinate-free checkpoint geometry")
        if manifest.get("input_sha256") != sha256(path):
            fail("AllCheck companion manifest input hash does not match the Gaussian input")
        if manifest.get("checkpoint_file") != oldcheckpoint:
            fail("AllCheck companion checkpoint filename differs from %oldchk")
        checkpoint_path = path.parent / oldcheckpoint
        if not checkpoint_path.is_file() or checkpoint_path.is_symlink():
            fail("Geom=AllCheck %oldchk must be an existing non-symlink file beside the input")
        oldcheckpoint_sha256 = sha256(checkpoint_path)
        if manifest.get("checkpoint_sha256") != oldcheckpoint_sha256:
            fail("AllCheck companion checkpoint hash does not match %oldchk")
        try:
            charge = int(manifest["charge"])
            multiplicity = int(manifest["multiplicity"])
            coordinate_count = int(manifest["atom_count"])
        except (KeyError, TypeError, ValueError):
            fail("AllCheck companion has invalid charge, multiplicity, or atom count")
        if multiplicity < 1 or coordinate_count < 1:
            fail("AllCheck companion multiplicity and atom count must be positive")
        atom_order = manifest.get("atom_order")
        if not isinstance(atom_order, list) or len(atom_order) != coordinate_count:
            fail("AllCheck companion atom order length differs from atom count")
        expected_indices = list(range(1, coordinate_count + 1))
        if [item.get("index") for item in atom_order if isinstance(item, dict)] != expected_indices:
            fail("AllCheck companion atom order must use contiguous one-based indices")
        for item in atom_order:
            if not isinstance(item, dict) or not re.fullmatch(r"[A-Z][a-z]?", str(item.get("element", ""))):
                fail("AllCheck companion contains an invalid atom-order entry")
            if not isinstance(item.get("atomic_number"), int) or item["atomic_number"] < 1:
                fail("AllCheck companion contains an invalid atomic number")
            elements[str(item["element"])] += 1
    else:
        while i < len(lines) and lines[i].strip():
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            fail("missing charge/multiplicity line")
        charge_mult = lines[i].split()
        if len(charge_mult) != 2:
            fail("charge/multiplicity line must contain exactly two integers")
        try:
            charge, multiplicity = map(int, charge_mult)
        except ValueError:
            fail("charge/multiplicity line must contain integers")
        if multiplicity < 1:
            fail("multiplicity must be at least 1")
        i += 1
        coordinate_count = 0
        while i < len(lines) and lines[i].strip():
            fields = lines[i].split()
            if len(fields) < 4:
                fail(f"malformed Cartesian coordinate at line {i + 1}")
            element = fields[0]
            if not re.fullmatch(r"[A-Z][a-z]?", element):
                fail(f"invalid element symbol at line {i + 1}: {element}")
            try:
                xyz = [float(value) for value in fields[1:4]]
            except ValueError:
                fail(f"non-numeric Cartesian coordinate at line {i + 1}")
            if not all(math.isfinite(value) for value in xyz):
                fail(f"non-finite Cartesian coordinate at line {i + 1}")
            elements[element] += 1
            coordinate_count += 1
            i += 1
        if coordinate_count == 0:
            fail("no Cartesian coordinates found")

    report = {
        "input": str(path.resolve()),
        "input_sha256": sha256(path),
        "checkpoint": checkpoint,
        "oldcheckpoint": oldcheckpoint,
        "oldcheckpoint_sha256": oldcheckpoint_sha256,
        "mem": link0["mem"],
        "memory_bytes": memory_bytes,
        "nprocshared": nproc,
        "route": route,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": coordinate_count,
        "elements": dict(sorted(elements.items())),
        "atom_order": atom_order,
        "geometry_source": "geom_allcheck_from_reviewed_checkpoint" if geom_allcheck else "explicit_cartesian",
        "link1_count": link1_count,
        "route_section_count": route_section_count,
        "trailing_blank_line": True,
    }
    report["manifest"] = None
    report["manifest_warnings"] = []
    if manifest is not None:
        warnings = manifest.get("warnings", [])
        if not isinstance(warnings, list):
            fail("companion manifest warnings must be a list")
        if warnings:
            fail("companion manifest contains unresolved warnings: " + "; ".join(map(str, warnings)))
        if manifest.get("candidate_only") is True or manifest.get("calculation_ready") is False:
            fail("companion manifest marks this as an unselected conformer candidate; review and select it first")
        centers = manifest.get("chiral_centers", [])
        if any(isinstance(center, dict) and center.get("cip") == "?" for center in centers):
            fail("companion manifest contains unassigned tetrahedral stereochemistry")
        manifest_charge = manifest.get("charge_used")
        manifest_mult = manifest.get("multiplicity_used")
        manifest_atoms = manifest.get("atom_count_in_gaussian_input")
        if manifest_charge is not None and manifest_charge != charge:
            fail("charge differs between Gaussian input and companion manifest")
        if manifest_mult is not None and manifest_mult != multiplicity:
            fail("multiplicity differs between Gaussian input and companion manifest")
        if manifest_atoms is not None and manifest_atoms != coordinate_count:
            fail("atom count differs between Gaussian input and companion manifest")
        report["manifest"] = str(manifest_path.resolve())
    return report


def pbs_text(project: str, input_name: str, nproc: int) -> str:
    return f"""#!/bin/sh
#PBS -N {project}
#PBS -j oe
#PBS -l nodes=1:ppn={nproc}
#PBS -V
#PBS -o ./{project}.pbs.out

set -eu

allowed_root="{DEFAULT_REMOTE_ROOT}"
root_real=$(realpath -e -- "$allowed_root")
work_real=$(realpath -e -- "$PBS_O_WORKDIR")
if [ "$root_real" != "$allowed_root" ]; then
  echo "Refusing to run: allowed root is missing, moved, or a symlink" >&2
  exit 40
fi
case "$work_real" in
  "$allowed_root"/*) ;;
  *) echo "Refusing to run outside $allowed_root" >&2; exit 41 ;;
esac
if [ -L "$PBS_O_WORKDIR" ]; then
  echo "Refusing to run from a symbolic-link work directory" >&2
  exit 42
fi

cd "$work_real"
scratch="$work_real/scratch"
if [ -L "$scratch" ]; then
  echo "Refusing symbolic-link scratch directory" >&2
  exit 43
fi
mkdir -p -- "$scratch"
scratch_real=$(realpath -e -- "$scratch")
case "$scratch_real" in
  "$work_real"/*) ;;
  *) echo "Refusing scratch outside the project directory" >&2; exit 44 ;;
esac
export GAUSS_SCRDIR="$scratch_real"
g16 "{input_name}"
"""


def stage(input_path: Path, project: str, local_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    audit = parse_gaussian(input_path)
    validate_transfer_name(input_path.name)
    local_dir.mkdir(parents=True, exist_ok=True)
    existing_job_path = local_dir / "job.json"
    if existing_job_path.is_file():
        try:
            existing_job = json.loads(existing_job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"could not read existing job metadata: {exc}")
        protected_states = {
            "submitted", "queued", "running", "held", "exiting", "stale",
            "completed", "failed", "interrupted", "cancel_requested",
            "submission_uncertain",
        }
        if existing_job.get("status") in protected_states:
            fail(
                f"local bundle already records status {existing_job.get('status')!r}; "
                "use a new project/local directory instead of risking a duplicate run"
            )
    destination = local_dir / input_path.name
    if destination.resolve() != input_path.resolve():
        if destination.is_symlink():
            fail(f"refusing symlink staged input: {destination}")
        if destination.exists():
            if sha256(destination) != sha256(input_path):
                fail(f"refusing to overwrite different staged input: {destination}")
        else:
            shutil.copy2(input_path, destination)
    else:
        destination = input_path

    companions: list[Path] = []
    for suffix in (".json", ".xyz"):
        source = input_path.with_suffix(suffix)
        validate_transfer_name(source.name)
        target = local_dir / source.name
        if source.is_file():
            if target.resolve() != source.resolve():
                if target.is_symlink():
                    fail(f"refusing symlink staged companion: {target}")
                if target.exists():
                    if sha256(target) != sha256(source):
                        fail(f"refusing to overwrite different companion: {target}")
                else:
                    shutil.copy2(source, target)
            companions.append(target)

    oldcheckpoint = audit.get("oldcheckpoint")
    if oldcheckpoint:
        validate_transfer_name(oldcheckpoint)
        source = input_path.parent / oldcheckpoint
        if not source.is_file() or source.is_symlink():
            fail("%oldchk must name an existing non-symlink checkpoint beside the input")
        target = local_dir / oldcheckpoint
        if target.resolve() != source.resolve():
            if target.is_symlink():
                fail(f"refusing symlink staged checkpoint: {target}")
            if target.exists():
                if sha256(target) != sha256(source):
                    fail(f"refusing to overwrite different checkpoint companion: {target}")
            else:
                shutil.copy2(source, target)
        companions.append(target)

    pbs = local_dir / f"{project}.pbs"
    atomic_text(pbs, pbs_text(project, destination.name, audit["nprocshared"]))
    immutable = [destination, *companions, pbs]
    checksums = local_dir / "checksums.sha256"
    atomic_text(checksums, "".join(f"{sha256(item)}  {item.name}\n" for item in immutable))
    job = {
        "schema": "gaussian-rtwin-pbs/1",
        "project": project,
        "status": "staged",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "input": destination.name,
        "input_sha256": audit["input_sha256"],
        "pbs_script": pbs.name,
        "checksums": checksums.name,
        "remote_workdir": remote_project_dir(project),
        "job_id": None,
        "gaussian": audit,
    }
    atomic_json(local_dir / "job.json", job)
    # job.json is mutable local control-plane state and is never uploaded.
    return job, [*immutable, checksums]


def ssh_base(args) -> list[str]:
    config = Path(args.mac_ssh_config).expanduser()
    if not config.is_file():
        fail(f"Mac SSH config not found: {config}")
    return ["ssh", "-F", str(config), args.rtwin_alias]


def nested_ssh(args, *remote_command: str) -> list[str]:
    return [
        *ssh_base(args),
        "ssh", "-F", args.windows_server_config,
        args.server_alias, *remote_command,
    ]


def powershell_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def update_job(local_dir: Path, **updates: Any) -> dict[str, Any]:
    path = local_dir / "job.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    job.update(updates)
    atomic_json(path, job)
    return job


def classify_inspection_state(
    *,
    workflow_manifest: dict[str, Any] | None,
    full_normal_count: int,
    full_error_count: int,
    analysis: dict[str, Any],
    qstate: str | None,
    process_alive: bool | None,
) -> tuple[str, int, bool, bool]:
    expected_stages = int(workflow_manifest.get("expected_stage_count", 3)) if workflow_manifest else 1
    workflow_complete = bool(
        workflow_manifest and full_normal_count >= expected_stages and full_error_count == 0
    )
    workflow_failed = bool(workflow_manifest and full_error_count > 0)
    # A single input can contain sequential work (for example, Opt followed by
    # Freq).  An earlier "Normal termination" does not make the overall job
    # terminal while PBS still has a live Gaussian session.
    if qstate == "R" and process_alive is True:
        state = "running"
    elif qstate == "Q":
        state = "queued"
    elif qstate == "H":
        state = "held"
    elif qstate == "E":
        state = "exiting"
    elif qstate == "R" and process_alive is None:
        state = "unknown"
    elif workflow_complete:
        state = "completed"
    elif workflow_failed:
        state = "failed"
    elif not workflow_manifest and analysis["normal_termination"]:
        state = "completed"
    elif not workflow_manifest and analysis["error_termination"]:
        state = "failed"
    elif qstate == "R" and process_alive is False:
        state = "stale"
    elif qstate is None and (
        analysis.get("scf_calculations", 0) > 0
        or analysis.get("final_coordinate_count", 0) > 0
        or analysis.get("normal_termination_count", 0) + analysis.get("error_termination_count", 0) > 0
    ):
        state = "interrupted"
    else:
        state = "unknown"
    return state, expected_stages, workflow_complete, workflow_failed


def terminal_log_proven(inspection: dict[str, Any]) -> bool:
    """Return True only when the log proves Gaussian reached a terminal outcome."""

    expected = inspection.get("workflow_expected_stages")
    normal_count = int(inspection.get("full_normal_termination_count") or 0)
    error_count = int(inspection.get("full_error_termination_count") or 0)
    if error_count > 0:
        return True
    if expected is not None:
        return normal_count >= int(expected)
    analysis = inspection.get("analysis") or {}
    return bool(analysis.get("normal_termination") or analysis.get("error_termination"))


def zombie_snapshot(inspection: dict[str, Any]) -> dict[str, Any]:
    """Keep only scheduler-safety evidence needed for zombie diagnosis."""

    return {
        "pbs_job_name": inspection.get("pbs_job_name"),
        "pbs_state": inspection.get("pbs_state"),
        "pbs_record_present": inspection.get("pbs_record_present"),
        "session_id": inspection.get("session_id"),
        "process_alive": inspection.get("process_alive"),
        "log_size": inspection.get("log_size"),
        "log_mtime_epoch": inspection.get("log_mtime_epoch"),
        "workflow_expected_stages": inspection.get("workflow_expected_stages"),
        "full_normal_termination_count": inspection.get("full_normal_termination_count"),
        "full_error_termination_count": inspection.get("full_error_termination_count"),
        "terminal_log_proven": terminal_log_proven(inspection),
    }


def assess_zombie_observations(
    project: str,
    job_id: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify repeated read-only observations without contacting PBS."""

    snapshots = [zombie_snapshot(value) for value in observations]
    base = {
        "schema": "pbs-zombie-diagnosis/1",
        "project": project,
        "job_id": job_id,
        "scope": "PBS scheduler record only; server project files are untouched",
    }
    if len(snapshots) < 2:
        return {
            **base,
            "classification": "insufficient_observations",
            "cleanup_eligible": False,
            "failed_checks": ["at least two observations are required"],
            "observations": snapshots,
        }
    if not snapshots[-1]["pbs_record_present"]:
        return {
            **base,
            "classification": "self_purged",
            "cleanup_eligible": False,
            "failed_checks": [],
            "observations": snapshots,
        }

    checks = {
        "exact_job_name": all(value["pbs_job_name"] == project for value in snapshots),
        "pbs_running_record": all(value["pbs_state"] == "R" for value in snapshots),
        "session_id_present": all(bool(value["session_id"]) for value in snapshots),
        "session_process_absent": all(value["process_alive"] is False for value in snapshots),
        "terminal_log_proven": all(value["terminal_log_proven"] for value in snapshots),
        "log_metadata_present": all(
            value["log_size"] is not None and value["log_mtime_epoch"] is not None
            for value in snapshots
        ),
        "log_stable": all(
            (value["log_size"], value["log_mtime_epoch"])
            == (snapshots[0]["log_size"], snapshots[0]["log_mtime_epoch"])
            for value in snapshots[1:]
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    confirmed = not failed_checks
    return {
        **base,
        "classification": "confirmed_scheduler_zombie" if confirmed else "not_confirmed_zombie",
        "cleanup_eligible": confirmed,
        "checks": checks,
        "failed_checks": failed_checks,
        "observations": snapshots,
    }


def validate_local_job_binding(
    local_dir: Path,
    project: str,
    job_id: str,
    input_stem: str,
    *,
    require_fetched: bool,
) -> dict[str, Any]:
    """Bind a cleanup request to the immutable local job audit record."""

    job_path = local_dir.expanduser().resolve() / "job.json"
    if not job_path.is_file():
        fail(f"local job audit record does not exist: {job_path}")
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"could not read local job audit record: {exc}")
    expected = {
        "project": project,
        "job_id": job_id,
        "remote_workdir": remote_project_dir(project),
    }
    for key, value in expected.items():
        if job.get(key) != value:
            fail(f"local job audit record {key} does not match the cleanup request")
    if Path(str(job.get("input", ""))).stem != input_stem:
        fail("local job audit record input stem does not match the cleanup request")
    if require_fetched and job.get("results_fetched") is not True:
        fail("refusing scheduler cleanup before results_fetched is recorded true")
    return job


def inspect_job(args, project: str, input_stem: str, job_id: str) -> dict[str, Any]:
    """Combine PBS, process, and Gaussian-log evidence into one state."""

    project = validate_project(project)
    job_id = validate_job_id(job_id)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", input_stem):
        fail("invalid input stem")
    qstat = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
    qstat_text = str(qstat.stdout or qstat.stderr)
    qstate_match = re.search(r"(?m)^\s*job_state\s*=\s*(\S+)", qstat_text)
    qstate = qstate_match.group(1) if qstate_match else None
    job_name_match = re.search(r"(?m)^\s*Job_Name\s*=\s*(\S+)", qstat_text)
    pbs_job_name = job_name_match.group(1) if job_name_match else None
    session_match = re.search(r"(?m)^\s*session_id\s*=\s*(\d+)", qstat_text)
    session_id = session_match.group(1) if session_match else None
    process_alive: bool | None = None
    if session_id:
        process = run(nested_ssh(args, "ps", "-s", session_id, "-o", "pid="), check=False)
        process_alive = bool(str(process.stdout).strip())

    remote_dir = remote_project_dir(project)
    guard = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=remote_existing_directory_guard(project).encode("utf-8"),
        check=False,
    )
    if guard.returncode:
        fail(str(guard.stderr or guard.stdout).strip())
    log_path = f"{remote_dir}/{input_stem}.log"
    manifest_path = f"{remote_dir}/{input_stem}.json"
    manifest_result = run(nested_ssh(args, "cat", manifest_path), check=False)
    workflow_manifest = None
    if manifest_result.returncode == 0:
        try:
            manifest_value = json.loads(str(manifest_result.stdout))
        except json.JSONDecodeError:
            manifest_value = None
        if isinstance(manifest_value, dict) and manifest_value.get("schema") == "gaussian-opt-freq-sp/1":
            workflow_manifest = manifest_value
    if workflow_manifest is None and getattr(args, "local_dir", None):
        local_manifest = Path(args.local_dir).expanduser().resolve() / f"{input_stem}.json"
        if local_manifest.is_file():
            try:
                manifest_value = json.loads(local_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest_value = None
            if isinstance(manifest_value, dict) and manifest_value.get("schema") == "gaussian-opt-freq-sp/1":
                workflow_manifest = manifest_value
    tail = run(nested_ssh(args, "tail", "-n", "500", log_path), check=False)
    log_text = str(tail.stdout) if tail.returncode == 0 else ""
    stat = run(nested_ssh(args, "stat", "-c", "%s:%Y", log_path), check=False)
    size = None
    mtime = None
    stat_match = re.fullmatch(r"(\d+):(\d+)", str(stat.stdout).strip())
    if stat_match:
        size, mtime = map(int, stat_match.groups())
    analysis = analyze_log_text(log_text)
    count_script = f"""normal=$(grep -c 'Normal termination of Gaussian' '{log_path}' 2>/dev/null || true)
error=$(grep -c 'Error termination' '{log_path}' 2>/dev/null || true)
printf '%s:%s\\n' "$normal" "$error"
"""
    termination_counts = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=count_script.encode("utf-8"),
        check=False,
    )
    count_match = re.fullmatch(r"(\d+):(\d+)", str(termination_counts.stdout).strip())
    full_normal_count, full_error_count = map(int, count_match.groups()) if count_match else (0, 0)
    state, expected_stages, workflow_execution_complete, workflow_execution_failed = classify_inspection_state(
        workflow_manifest=workflow_manifest,
        full_normal_count=full_normal_count,
        full_error_count=full_error_count,
        analysis=analysis,
        qstate=qstate,
        process_alive=process_alive,
    )
    scheduler_record_lingering = bool(
        qstate is not None
        and (workflow_execution_complete or (not workflow_manifest and analysis["normal_termination"]))
    )
    terminal_proven = bool(
        workflow_execution_complete
        or workflow_execution_failed
        or (not workflow_manifest and (analysis["normal_termination"] or analysis["error_termination"]))
    )
    zombie_candidate = bool(
        pbs_job_name == project
        and qstate == "R"
        and session_id is not None
        and process_alive is False
        and terminal_proven
    )

    inspection = {
        "schema": "gaussian-job-inspection/1",
        "project": project,
        "job_id": job_id,
        "state": state,
        "pbs_job_name": pbs_job_name,
        "pbs_state": qstate,
        "pbs_record_present": qstate is not None,
        "session_id": session_id,
        "process_alive": process_alive,
        "log": log_path,
        "log_size": size,
        "log_mtime_epoch": mtime,
        "workflow_expected_stages": expected_stages if workflow_manifest else None,
        "full_normal_termination_count": full_normal_count,
        "full_error_termination_count": full_error_count,
        "scheduler_record_lingering": scheduler_record_lingering,
        "scheduler_zombie_candidate": zombie_candidate,
        "analysis": analysis,
    }
    if scheduler_record_lingering:
        inspection["note"] = (
            "Gaussian is terminal while a PBS record remains; use repeated diagnose-zombie evidence "
            "before one automatic scheduler-only cleanup"
        )
    return inspection


def fetch_results(args, project: str, output_dir: Path) -> dict[str, Any]:
    """Fetch a complete project tree without changing server data."""

    project = validate_project(project)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    windows_results = f"{args.windows_root}\\{project}\\results"
    mkdir_script = f"New-Item -ItemType Directory -Force -Path '{windows_results}' | Out-Null"
    run([*ssh_base(args), "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershell_encoded(mkdir_script)])
    guard = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=remote_existing_directory_guard(project).encode("utf-8"),
        check=False,
    )
    if guard.returncode:
        fail(str(guard.stderr or guard.stdout).strip())
    remote_glob = f"{args.server_alias}:{remote_project_dir(project)}/*"
    run([*ssh_base(args), "scp", "-r", "-F", args.windows_server_config, remote_glob, windows_results + "\\"])
    windows_results_scp = windows_results.replace("\\", "/")
    run([
        "scp", "-r", "-F", str(Path(args.mac_ssh_config).expanduser()),
        f"{args.rtwin_alias}:{windows_results_scp}/*",
        str(output_dir) + "/",
    ])
    fetched = sorted(
        str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file()
    )
    logs = sorted(output_dir.glob("*.log"))
    workflow_manifest = None
    for candidate in sorted(output_dir.glob("*.json")):
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("schema") == "gaussian-opt-freq-sp/1":
            workflow_manifest = value
            break
    if logs and workflow_manifest:
        analysis = analyze_workflow_log_file(
            logs[0], output_dir,
            temperature_k=float(workflow_manifest["temperature_k"]),
            standard_state=str(workflow_manifest["standard_state"]),
            expected_stages=int(workflow_manifest.get("expected_stage_count", 3)),
        )
        analysis["species_id"] = workflow_manifest.get("species_id")
        analysis["chemical_identity"] = workflow_manifest.get("chemical_identity")
        analysis["workflow_protocol"] = {
            "stages": workflow_manifest.get("stages"),
            "temperature_k": workflow_manifest.get("temperature_k"),
            "standard_state": workflow_manifest.get("standard_state"),
        }
        atomic_json(output_dir / "result.json", analysis)
    else:
        analysis = analyze_log_file(logs[0], output_dir) if logs else None
    transfer = {
        "project": project,
        "output_dir": str(output_dir),
        "files": fetched,
        "analysis": analysis,
    }
    atomic_json(output_dir / "transfer.json", transfer)
    return transfer


def command_finalize_input_review(args) -> None:
    try:
        document = finalize_input_review(Path(args.draft), Path(args.output))
    except (OSError, ValueError, protocol_selection.ContractError) as exc:
        fail(f"input-review finalization failed: {exc}")
    print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}, ensure_ascii=False, indent=2))


def command_build_input_approval(args) -> None:
    try:
        document = build_input_approval_receipt(
            Path(args.protocol_options), Path(args.protocol_selection), Path(args.input_review),
            Path(args.input), Path(args.output), args.receipt_id,
        )
    except (OSError, ValueError, protocol_selection.ContractError) as exc:
        fail(f"input-approval build failed: {exc}")
    print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}, ensure_ascii=False, indent=2))


def command_validate_input_approval(args) -> None:
    try:
        document = validate_input_approval_receipt(Path(args.receipt))
    except (OSError, ValueError, protocol_selection.ContractError) as exc:
        fail(f"input-approval validation failed: {exc}")
    print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}, ensure_ascii=False, indent=2))


def command_preflight(args) -> None:
    project = validate_project(args.project)
    report = parse_gaussian(Path(args.input).expanduser().resolve())
    maturity = audit_scientific_maturity(args, report, "ts_input")
    report["project"] = project
    report["remote_workdir"] = remote_project_dir(project)
    if maturity is not None:
        report = {"scientific_maturity": maturity, **report}
    print(json.dumps(report, ensure_ascii=False, indent=2))


def command_stage(args) -> None:
    project = validate_project(args.project)
    job, files = stage(
        Path(args.input).expanduser().resolve(), project,
        Path(args.local_dir).expanduser().resolve(),
    )
    print(json.dumps({"job": job, "files": [str(path) for path in files]}, ensure_ascii=False, indent=2))


def command_submit(args) -> None:
    if not args.confirmed:
        fail("submit requires --confirmed after the exact preflight is approved")
    project = validate_project(args.project)
    local_dir = Path(args.local_dir).expanduser().resolve()
    try:
        input_path, captured_input_sha256 = capture_submission_snapshot(
            Path(args.input), local_dir
        )
    except ValueError as exc:
        fail(f"could not capture immutable submission snapshot: {exc}")
    input_report = parse_gaussian(input_path)
    if input_report["input_sha256"] != captured_input_sha256:
        fail("submission snapshot hash changed before approval replay")
    requested_work_kind = args.work_kind
    if not args.dry_run and requested_work_kind is None:
        fail("live submission requires an explicit --work-kind; it must not default to ordinary")
    maturity = audit_scientific_maturity(args, input_report, "ts_submission")
    compatibility = input_approval_compatibility(input_report, requested_work_kind)
    input_approval: dict[str, Any]
    if compatibility["status"] != "supported_generic_v1":
        input_approval = {**compatibility, "no_submission_authorization": True}
    elif args.input_approval_record:
        assert requested_work_kind is not None
        input_approval = validate_input_approval(
            Path(args.input_approval_record), input_path, input_report, requested_work_kind
        )
    else:
        input_approval = {
            "status": "missing_required_for_live_submission",
            "required_schema": INPUT_APPROVAL_SCHEMA,
            "work_kind": requested_work_kind,
            "no_submission_authorization": True,
        }
    approval_summary = None
    if input_approval["status"] == "validated_exact_input_approval":
        assert requested_work_kind is not None
        approval_summary = live_approval_summary(
            project, input_report, maturity, requested_work_kind, input_approval
        )
    live_approval: dict[str, Any]
    if args.approval_record and approval_summary is not None:
        validated_live, live_approval_digest = validate_live_approval_binding(
            Path(args.approval_record), approval_summary
        )
        live_approval = {
            "status": "validated_exact_live_approval",
            "schema": validated_live["schema"],
            "sha256": live_approval_digest,
        }
    elif args.approval_record:
        live_approval = {
            "status": "not_evaluated_missing_exact_input_approval",
            "required_schema": "auto-g16-live-submission-approval/3",
        }
    else:
        live_approval = {
            "status": "omitted_for_dry_run" if args.dry_run else "missing_required_for_live_submission",
            "required_schema": "auto-g16-live-submission-approval/3",
        }
    live_submission_ready = (
        input_approval["status"] == "validated_exact_input_approval"
        and live_approval["status"] == "validated_exact_live_approval"
    )
    if not args.dry_run:
        if input_approval["status"] != "validated_exact_input_approval":
            if input_approval["status"] == "blocked_missing_specialist_input_approval":
                fail(
                    "blocked_missing_specialist_input_approval: this input family requires its "
                    "specialist owner manifest and exact raw-syntax/checkpoint approval"
                )
            fail(
                "live submission requires --input-approval-record with exact "
                "protocol selection, input-draft review, and input hash"
            )
        if live_approval["status"] != "validated_exact_live_approval":
            fail("live submission requires a hash-bound --approval-record")
    job, files = stage(input_path, project, local_dir)
    job["submission_snapshot"] = {
        "path": str(input_path),
        "sha256": captured_input_sha256,
        "immutable_capture": True,
    }
    job.update({
        "input_approval": input_approval,
        "live_approval": live_approval,
        "live_submission_ready": live_submission_ready,
    })
    atomic_json(local_dir / "job.json", job)
    expected = verify_staged_submission(local_dir, job, input_report, input_approval, files)
    windows_dir = f"{args.windows_root}\\{project}"
    remote_dir = remote_project_dir(project)

    plan = {
        "project": project,
        "local_dir": str(local_dir),
        "windows_dir": windows_dir,
        "remote_dir": remote_dir,
        "files": [path.name for path in files],
        "input_sha256": job["input_sha256"],
        "input_approval": input_approval,
        "live_approval": live_approval,
        "live_submission_ready": live_submission_ready,
    }
    if maturity is not None:
        plan = {"scientific_maturity": maturity, **plan}
    if args.dry_run:
        plan["dry_run"] = True
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    mkdir_script = f"New-Item -ItemType Directory -Force -Path '{windows_dir}' | Out-Null"
    run([*ssh_base(args), "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershell_encoded(mkdir_script)])
    assert_file_bindings_unchanged(files, expected)
    windows_dir_scp = windows_dir.replace("\\", "/")
    scp_to_windows = [
        "scp", "-F", str(Path(args.mac_ssh_config).expanduser()), *map(str, files),
        f"{args.rtwin_alias}:{windows_dir_scp}/",
    ]
    run(scp_to_windows)

    ps_paths = ",".join(f"'{windows_dir}\\{name}'" for name in expected)
    hash_script = (
        f"$files=@({ps_paths}); foreach($f in $files){{"
        "$h=(Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower();"
        "Write-Output ((Split-Path $f -Leaf)+' '+$h)}"
    )
    hash_result = run([*ssh_base(args), "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershell_encoded(hash_script)])
    observed: dict[str, str] = {}
    for line in str(hash_result.stdout).splitlines():
        match = re.fullmatch(r"(.+?)\s+([0-9a-fA-F]{64})", line.strip())
        if match:
            observed[match.group(1)] = match.group(2).lower()
    mismatches = [name for name, digest in expected.items() if observed.get(name) != digest]
    if mismatches:
        fail("RTwin SHA-256 mismatch or missing hash: " + ", ".join(mismatches))

    # This is the only server-side directory creation path.  It resolves both
    # the fixed root and project path, rejects symlinks, and refuses to upload
    # into any non-empty directory so existing server data is never overwritten.
    run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=remote_empty_directory_guard(project).encode("utf-8"),
    )
    windows_files = [f"{windows_dir}\\{path.name}" for path in files]
    run([*ssh_base(args), "scp", "-F", args.windows_server_config, *windows_files, f"{args.server_alias}:{remote_dir}/"])

    submit_script = remote_existing_directory_guard(project) + f"""
cd {remote_dir}
sha256sum -c checksums.sha256
if qstat -f 2>/dev/null | grep -Fq 'Job_Name = {project}'; then
  echo 'REFUSING_DUPLICATE: active PBS job named {project}' >&2
  exit 17
fi
qsub {project}.pbs
"""
    result = run(nested_ssh(args, "bash", "-l", "-s"), input_bytes=submit_script.encode("utf-8"), check=False)
    combined = f"{result.stdout}\n{result.stderr}"
    job_ids = re.findall(r"(?m)^([0-9]+(?:\.[A-Za-z0-9_.-]+)?)\s*$", combined)
    if result.returncode or not job_ids:
        update_job(local_dir, status="submission_uncertain", submission_output=combined.strip())
        fail(
            "qsub result is uncertain; do not retry. Run status --project " + project,
            code=3,
        )
    job_id = job_ids[-1]
    updated = update_job(
        local_dir,
        status="submitted",
        job_id=job_id,
        rtwin_sha256_verified=True,
        server_sha256_verified=True,
    )
    print(json.dumps({"submitted": True, "job_id": job_id, "job": updated}, ensure_ascii=False, indent=2))


def command_status(args) -> None:
    if not args.job_id and not args.project:
        fail("status requires --job-id or --project")
    if args.job_id:
        job_id = validate_job_id(args.job_id)
        result = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
        print(str(result.stdout or result.stderr).strip())
        raise SystemExit(result.returncode)
    project = validate_project(args.project)
    result = run(nested_ssh(args, "qstat", "-f"), check=False)
    blocks = re.split(r"(?=Job Id:)", str(result.stdout))
    matches = [block.strip() for block in blocks if re.search(rf"(?m)^\s*Job_Name\s*=\s*{re.escape(project)}\s*$", block)]
    if matches:
        print("\n\n".join(matches))
    else:
        print(json.dumps({"project": project, "active_job": False, "note": "job may be completed and purged; inspect/fetch the log"}))


def command_tail(args) -> None:
    project = validate_project(args.project)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.input_stem):
        fail("invalid input stem")
    if not 1 <= args.lines <= 500:
        fail("--lines must be between 1 and 500")
    remote_dir = remote_project_dir(project)
    guard = remote_existing_directory_guard(project)
    path = f"{remote_dir}/{args.input_stem}.log"
    guard_result = run(
        nested_ssh(args, "bash", "-s"),
        input_bytes=guard.encode("utf-8"),
        check=False,
    )
    if guard_result.returncode:
        fail(str(guard_result.stderr or guard_result.stdout).strip())
    result = run(nested_ssh(args, "tail", "-n", str(args.lines), path), check=False)
    print(str(result.stdout or result.stderr).rstrip())
    raise SystemExit(result.returncode)


def command_fetch(args) -> None:
    transfer = fetch_results(args, args.project, Path(args.output_dir))
    print(json.dumps(transfer, ensure_ascii=False, indent=2))


def command_inspect(args) -> None:
    inspection = inspect_job(args, args.project, args.input_stem, args.job_id)
    if args.local_dir:
        local_dir = Path(args.local_dir).expanduser().resolve()
        if (local_dir / "job.json").is_file():
            update_job(local_dir, status=inspection["state"], last_inspection=inspection)
    print(json.dumps(inspection, ensure_ascii=False, indent=2))


def command_watch(args) -> None:
    if not 2 <= args.poll_seconds <= 300:
        fail("--poll-seconds must be between 2 and 300")
    if not 10 <= args.timeout_seconds <= 7 * 24 * 3600:
        fail("--timeout-seconds must be between 10 seconds and 7 days")
    local_dir = Path(args.local_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    deadline = time.monotonic() + args.timeout_seconds
    previous_stale_signature = None
    stale_repeats = 0
    final: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        inspection = inspect_job(args, args.project, args.input_stem, args.job_id)
        signature = (inspection.get("log_size"), inspection.get("log_mtime_epoch"))
        if inspection["state"] == "stale":
            stale_repeats = stale_repeats + 1 if signature == previous_stale_signature else 1
            previous_stale_signature = signature
            if stale_repeats >= 2:
                inspection["state"] = "interrupted"
                inspection["note"] = "PBS record is stale; session is absent and log stopped changing"
        else:
            stale_repeats = 0
            previous_stale_signature = None
        if (local_dir / "job.json").is_file():
            update_job(local_dir, status=inspection["state"], last_inspection=inspection)
        print(
            json.dumps(
                {
                    "state": inspection["state"],
                    "pbs_state": inspection["pbs_state"],
                    "log_size": inspection["log_size"],
                }
            ),
            flush=True,
        )
        if inspection["state"] in {"completed", "failed", "interrupted"}:
            final = inspection
            break
        time.sleep(args.poll_seconds)
    if final is None:
        fail("watch timeout reached while job is still non-terminal", code=4)
    transfer = fetch_results(args, args.project, output_dir) if args.fetch else None
    if transfer and transfer.get("analysis"):
        final["analysis"] = transfer["analysis"]
    if (local_dir / "job.json").is_file():
        update_job(
            local_dir,
            status=final["state"],
            last_inspection=final,
            results_fetched=bool(transfer),
            result_file=str(output_dir / "result.json") if transfer else None,
        )
    scheduler_cleanup = None
    if (
        args.auto_cleanup_zombie
        and transfer
        and final.get("scheduler_zombie_candidate") is True
    ):
        cleanup_args = argparse.Namespace(**vars(args))
        cleanup_args.stability_seconds = args.zombie_stability_seconds
        cleanup_args.verify_seconds = args.zombie_verify_seconds
        scheduler_cleanup = cleanup_zombie_record(cleanup_args)
        if scheduler_cleanup["status"] == "cleanup_unverified":
            print(
                json.dumps(
                    {
                        "inspection": final,
                        "transfer": transfer,
                        "scheduler_cleanup": scheduler_cleanup,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            fail(
                "automatic qdel was issued once but the PBS record still exists; do not retry automatically",
                code=5,
            )
    print(
        json.dumps(
            {
                "inspection": final,
                "transfer": transfer,
                "scheduler_cleanup": scheduler_cleanup,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def command_analyze(args) -> None:
    log_path = Path(args.log).expanduser().resolve()
    if not log_path.is_file():
        fail(f"log does not exist: {log_path}")
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    result = analyze_log_file(log_path, output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def diagnose_zombie(args) -> dict[str, Any]:
    """Observe a possible stale PBS R record twice and return cleanup eligibility."""

    if not 5 <= args.stability_seconds <= 300:
        fail("--stability-seconds must be between 5 and 300")
    project = validate_project(args.project)
    job_id = validate_job_id(args.job_id)
    input_stem = args.input_stem
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", input_stem):
        fail("invalid input stem")
    local_dir = Path(args.local_dir).expanduser().resolve()
    validate_local_job_binding(
        local_dir, project, job_id, input_stem, require_fetched=True
    )
    first = inspect_job(args, project, input_stem, job_id)
    time.sleep(args.stability_seconds)
    second = inspect_job(args, project, input_stem, job_id)
    diagnosis = assess_zombie_observations(project, job_id, [first, second])
    diagnosis["stability_seconds"] = args.stability_seconds
    diagnosis["results_fetched_verified"] = True
    diagnosis["confirmation_required_for_qdel"] = False
    diagnosis["automatic_cleanup_authorized_by_policy"] = True
    diagnosis["server_data_deletion_authorized"] = False
    return diagnosis


def command_diagnose_zombie(args) -> None:
    diagnosis = diagnose_zombie(args)
    local_dir = Path(args.local_dir).expanduser().resolve()
    update_job(local_dir, last_zombie_diagnosis=diagnosis)
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))


def cleanup_zombie_record(args) -> dict[str, Any]:
    """Issue one qdel only for a repeatedly proven zombie and return its audit record."""

    if not 1 <= args.verify_seconds <= 60:
        fail("--verify-seconds must be between 1 and 60")
    diagnosis = diagnose_zombie(args)
    local_dir = Path(args.local_dir).expanduser().resolve()
    if diagnosis["classification"] == "self_purged":
        cleanup = {
            "schema": "pbs-zombie-cleanup/1",
            "project": args.project,
            "job_id": args.job_id,
            "status": "self_purged",
            "qdel_issued": False,
            "scheduler_record_present": False,
            "server_project_files_changed": False,
            "diagnosis": diagnosis,
        }
        update_job(local_dir, last_zombie_diagnosis=diagnosis, scheduler_cleanup=cleanup)
        return cleanup
    if not diagnosis.get("cleanup_eligible"):
        cleanup = {
            "schema": "pbs-zombie-cleanup/1",
            "project": args.project,
            "job_id": args.job_id,
            "status": "not_eligible",
            "qdel_issued": False,
            "scheduler_record_present": bool(
                diagnosis.get("observations")
                and diagnosis["observations"][-1].get("pbs_record_present")
            ),
            "server_project_files_changed": False,
            "diagnosis": diagnosis,
        }
        update_job(local_dir, last_zombie_diagnosis=diagnosis, scheduler_cleanup=cleanup)
        return cleanup

    # This is deliberately the only qdel in the zombie cleanup path. It changes
    # PBS-owned state only; it never removes, truncates, or rewrites server data.
    qdel = run(nested_ssh(args, "qdel", validate_job_id(args.job_id)), check=False)
    time.sleep(args.verify_seconds)
    after = run(nested_ssh(args, "qstat", "-f", validate_job_id(args.job_id)), check=False)
    after_text = str(after.stdout or after.stderr)
    record_present = bool(re.search(r"(?m)^\s*job_state\s*=\s*\S+", after_text))
    cleared = not record_present
    cleanup = {
        "schema": "pbs-zombie-cleanup/1",
        "project": args.project,
        "job_id": args.job_id,
        "status": "cleared" if cleared else "cleanup_unverified",
        "qdel_issued": True,
        "qdel_returncode": qdel.returncode,
        "scheduler_record_present": record_present,
        "server_project_files_changed": False,
        "diagnosis": diagnosis,
    }
    update_job(local_dir, last_zombie_diagnosis=diagnosis, scheduler_cleanup=cleanup)
    return cleanup


def command_cleanup_zombie(args) -> None:
    """Automatically qdel one repeatedly proven zombie and verify the record."""

    cleanup = cleanup_zombie_record(args)
    print(json.dumps(cleanup, ensure_ascii=False, indent=2))
    if cleanup["status"] == "not_eligible":
        fail("refusing qdel because repeated observations did not prove a scheduler zombie")
    if cleanup["status"] == "cleanup_unverified":
        fail("qdel was issued once but the PBS record still exists; do not retry automatically", code=5)


def command_cancel(args) -> None:
    if not args.confirmed:
        fail("cancel requires --confirmed after explicit user authorization")
    job_id = validate_job_id(args.job_id)
    before = run(nested_ssh(args, "qstat", "-f", job_id), check=False)
    if before.returncode:
        fail(f"PBS job does not appear active: {job_id}")
    result = run(nested_ssh(args, "qdel", job_id))
    if args.local_dir:
        local_dir = Path(args.local_dir).expanduser().resolve()
        if (local_dir / "job.json").is_file():
            update_job(local_dir, status="cancel_requested", cancel_requested=True)
    print(json.dumps({"cancel_requested": True, "job_id": job_id, "output": str(result.stdout).strip()}))


def add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mac-ssh-config", default=str(DEFAULT_MAC_SSH_CONFIG))
    parser.add_argument("--rtwin-alias", default=DEFAULT_RTWIN_ALIAS)
    parser.add_argument("--windows-root", default=DEFAULT_WINDOWS_ROOT)
    parser.add_argument("--windows-server-config", default=DEFAULT_WINDOWS_SERVER_CONFIG)
    parser.add_argument("--server-alias", default=DEFAULT_SERVER_ALIAS)


def add_scientific_maturity_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scientific-maturity", help="immutable gaussian-scientific-maturity-gate/1 artifact required for TS work")
    parser.add_argument("--edge-id", help="reviewed mechanism edge bound by the maturity gate")
    parser.add_argument("--node-id", help="exact reviewed calculation-DAG node for this protected action")
    parser.add_argument("--pilot", action="store_true", help="limit this TS action to the reviewed one-candidate simple-tier pilot")
    parser.add_argument("--work-kind", choices=["ordinary", "minimum", "ts_pilot", "formal_ts", "ts_scan", "irc_forward", "irc_reverse", "endpoint_reopt"], help="explicit scientific work classification; required for every live submission (dry-run may report it missing)")
    parser.add_argument("--scientific-action-authorization", help="exact offline input/project/node/budget binding required for protected submission; it is not live approval")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    finalize_review = sub.add_parser("finalize-input-review", help="finalize one generic exact input-draft review /2 without live action")
    finalize_review.add_argument("draft")
    finalize_review.add_argument("--output", required=True)
    finalize_review.set_defaults(func=command_finalize_input_review)

    build_approval = sub.add_parser("build-input-approval", help="bind protocol selection, exact input review, and exact input into one non-authorizing receipt")
    build_approval.add_argument("input")
    build_approval.add_argument("--protocol-options", required=True)
    build_approval.add_argument("--protocol-selection", required=True)
    build_approval.add_argument("--input-review", required=True)
    build_approval.add_argument("--receipt-id", required=True)
    build_approval.add_argument("--output", required=True)
    build_approval.set_defaults(func=command_build_input_approval)

    validate_approval = sub.add_parser("validate-input-approval", help="replay one generic exact input-approval receipt without live action")
    validate_approval.add_argument("receipt")
    validate_approval.set_defaults(func=command_validate_input_approval)

    preflight = sub.add_parser("preflight", help="audit a local Gaussian input without network access")
    preflight.add_argument("input")
    preflight.add_argument("--project", required=True)
    add_scientific_maturity_options(preflight)
    preflight.set_defaults(func=command_preflight)

    stage_parser = sub.add_parser("stage", help="create a local PBS bundle without network access")
    stage_parser.add_argument("input")
    stage_parser.add_argument("--project", required=True)
    stage_parser.add_argument("--local-dir", required=True)
    stage_parser.set_defaults(func=command_stage)

    submit = sub.add_parser("submit", help="stage, verify, transfer, and qsub exactly once")
    submit.add_argument("input")
    submit.add_argument("--project", required=True)
    submit.add_argument("--local-dir", required=True)
    submit.add_argument("--confirmed", action="store_true")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument(
        "--approval-record",
        help="exact live /3 receipt required for new submissions; /1-/2 are historical replay-only",
    )
    submit.add_argument("--input-approval-record", help=f"owner-validated {INPUT_APPROVAL_SCHEMA} required for every live submission")
    add_scientific_maturity_options(submit)
    add_connection_options(submit)
    submit.set_defaults(func=command_submit)

    status = sub.add_parser("status", help="query an active PBS job")
    status.add_argument("--job-id")
    status.add_argument("--project")
    add_connection_options(status)
    status.set_defaults(func=command_status)

    tail = sub.add_parser("tail", help="read the end of a Gaussian log")
    tail.add_argument("--project", required=True)
    tail.add_argument("--input-stem", required=True)
    tail.add_argument("--lines", type=int, default=80)
    add_connection_options(tail)
    tail.set_defaults(func=command_tail)

    fetch = sub.add_parser("fetch", help="copy all server job files through RTwin to the Mac")
    fetch.add_argument("--project", required=True)
    fetch.add_argument("--output-dir", required=True)
    add_connection_options(fetch)
    fetch.set_defaults(func=command_fetch)

    inspect_parser = sub.add_parser("inspect", help="combine PBS, process, and log evidence into JSON")
    inspect_parser.add_argument("--project", required=True)
    inspect_parser.add_argument("--job-id", required=True)
    inspect_parser.add_argument("--input-stem", required=True)
    inspect_parser.add_argument("--local-dir")
    add_connection_options(inspect_parser)
    inspect_parser.set_defaults(func=command_inspect)

    diagnose_zombie_parser = sub.add_parser(
        "diagnose-zombie",
        help="prove a stale PBS R record with two read-only observations",
    )
    diagnose_zombie_parser.add_argument("--project", required=True)
    diagnose_zombie_parser.add_argument("--job-id", required=True)
    diagnose_zombie_parser.add_argument("--input-stem", required=True)
    diagnose_zombie_parser.add_argument("--local-dir", required=True)
    diagnose_zombie_parser.add_argument("--stability-seconds", type=int, default=10)
    add_connection_options(diagnose_zombie_parser)
    diagnose_zombie_parser.set_defaults(func=command_diagnose_zombie)

    cleanup_zombie_parser = sub.add_parser(
        "cleanup-zombie",
        help="automatically qdel one repeatedly proven scheduler zombie",
    )
    cleanup_zombie_parser.add_argument("--project", required=True)
    cleanup_zombie_parser.add_argument("--job-id", required=True)
    cleanup_zombie_parser.add_argument("--input-stem", required=True)
    cleanup_zombie_parser.add_argument("--local-dir", required=True)
    cleanup_zombie_parser.add_argument("--stability-seconds", type=int, default=10)
    cleanup_zombie_parser.add_argument("--verify-seconds", type=int, default=5)
    cleanup_zombie_parser.add_argument(
        "--confirmed", action="store_true", help=argparse.SUPPRESS
    )
    add_connection_options(cleanup_zombie_parser)
    cleanup_zombie_parser.set_defaults(func=command_cleanup_zombie)

    watch = sub.add_parser("watch", help="monitor to a terminal state, then optionally fetch and analyze")
    watch.add_argument("--project", required=True)
    watch.add_argument("--job-id", required=True)
    watch.add_argument("--input-stem", required=True)
    watch.add_argument("--local-dir", required=True)
    watch.add_argument("--output-dir", required=True)
    watch.add_argument("--poll-seconds", type=int, default=30)
    watch.add_argument("--timeout-seconds", type=int, default=86400)
    watch.add_argument("--fetch", action="store_true")
    watch.add_argument(
        "--no-auto-cleanup-zombie",
        action="store_false",
        dest="auto_cleanup_zombie",
        help="leave a confirmed scheduler-zombie record for manual diagnostics",
    )
    watch.add_argument("--zombie-stability-seconds", type=int, default=10)
    watch.add_argument("--zombie-verify-seconds", type=int, default=5)
    watch.set_defaults(auto_cleanup_zombie=True)
    add_connection_options(watch)
    watch.set_defaults(func=command_watch)

    analyze = sub.add_parser("analyze", help="analyze a fetched Gaussian log locally")
    analyze.add_argument("log")
    analyze.add_argument("--output-dir")
    analyze.set_defaults(func=command_analyze)

    cancel = sub.add_parser("cancel", help="qdel an explicitly approved PBS job")
    cancel.add_argument("--job-id", required=True)
    cancel.add_argument("--confirmed", action="store_true")
    cancel.add_argument("--local-dir")
    add_connection_options(cancel)
    cancel.set_defaults(func=command_cancel)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted", code=130)
