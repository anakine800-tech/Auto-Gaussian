#!/usr/bin/env python3
"""Safely operate Gaussian jobs through RTwin on the configured PBS server."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from gaussian_log import analyze_log_file, analyze_log_text, analyze_workflow_log_file


DEFAULT_MAC_SSH_CONFIG = Path(
    "<MAC_HOME>/Documents/用RTwin进行计算/config/ssh_config"
)
DEFAULT_RTWIN_ALIAS = "rtwin"
DEFAULT_WINDOWS_ROOT = r"<WINDOWS_HOME>\Desktop\GaussianProjects"
DEFAULT_WINDOWS_SERVER_CONFIG = r"<WINDOWS_HOME>\.ssh\gaussian_server_config"
DEFAULT_SERVER_ALIAS = "gaussian-server"
DEFAULT_REMOTE_ROOT = "/home/user100/SDL"
MAX_CORES = 44
MAX_MEMORY_BYTES = 120 * 1024**3
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
JOB_ID_RE = re.compile(r"^[0-9]+(?:\.[A-Za-z0-9_.-]+)?$")


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


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


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


def parse_gaussian(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"input does not exist: {path}")
    if path.suffix.lower() not in {".gjf", ".com"}:
        fail("Gaussian input must end in .gjf or .com")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
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
    while i < len(lines) and not lines[i].strip():
        i += 1
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

    elements: Counter[str] = Counter()
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
        "mem": link0["mem"],
        "memory_bytes": memory_bytes,
        "nprocshared": nproc,
        "route": route,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": coordinate_count,
        "elements": dict(sorted(elements.items())),
        "trailing_blank_line": True,
    }
    manifest_path = path.with_suffix(".json")
    report["manifest"] = None
    report["manifest_warnings"] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"could not read Gaussian companion manifest: {exc}")
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
        if destination.exists() and sha256(destination) != sha256(input_path):
            fail(f"refusing to overwrite different staged input: {destination}")
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
                if target.exists() and sha256(target) != sha256(source):
                    fail(f"refusing to overwrite different companion: {target}")
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
            "before considering an explicitly confirmed scheduler-only cleanup"
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


def command_preflight(args) -> None:
    project = validate_project(args.project)
    report = parse_gaussian(Path(args.input).expanduser().resolve())
    report["project"] = project
    report["remote_workdir"] = remote_project_dir(project)
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
    job, files = stage(Path(args.input).expanduser().resolve(), project, local_dir)
    windows_dir = f"{args.windows_root}\\{project}"
    remote_dir = remote_project_dir(project)

    plan = {
        "project": project,
        "local_dir": str(local_dir),
        "windows_dir": windows_dir,
        "remote_dir": remote_dir,
        "files": [path.name for path in files],
        "input_sha256": job["input_sha256"],
    }
    if args.dry_run:
        plan["dry_run"] = True
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    mkdir_script = f"New-Item -ItemType Directory -Force -Path '{windows_dir}' | Out-Null"
    run([*ssh_base(args), "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", powershell_encoded(mkdir_script)])
    windows_dir_scp = windows_dir.replace("\\", "/")
    scp_to_windows = [
        "scp", "-F", str(Path(args.mac_ssh_config).expanduser()), *map(str, files),
        f"{args.rtwin_alias}:{windows_dir_scp}/",
    ]
    run(scp_to_windows)

    expected = {path.name: sha256(path) for path in files}
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
    print(json.dumps({"inspection": final, "transfer": transfer}, ensure_ascii=False, indent=2))


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
    diagnosis["confirmation_required_for_qdel"] = True
    diagnosis["server_data_deletion_authorized"] = False
    return diagnosis


def command_diagnose_zombie(args) -> None:
    diagnosis = diagnose_zombie(args)
    local_dir = Path(args.local_dir).expanduser().resolve()
    update_job(local_dir, last_zombie_diagnosis=diagnosis)
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))


def command_cleanup_zombie(args) -> None:
    """Issue one qdel only for a repeatedly proven zombie and verify the record."""

    if not args.confirmed:
        fail(
            "cleanup-zombie requires --confirmed after the user approves the exact project and job id"
        )
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
        print(json.dumps(cleanup, ensure_ascii=False, indent=2))
        return
    if not diagnosis.get("cleanup_eligible"):
        update_job(local_dir, last_zombie_diagnosis=diagnosis)
        print(json.dumps(diagnosis, ensure_ascii=False, indent=2))
        fail("refusing qdel because repeated observations did not prove a scheduler zombie")

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
    print(json.dumps(cleanup, ensure_ascii=False, indent=2))
    if not cleared:
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
    parser.add_argument("--mac-ssh-config", default=os.environ.get("GAUSSIAN_RTWIN_SSH_CONFIG", str(DEFAULT_MAC_SSH_CONFIG)))
    parser.add_argument("--rtwin-alias", default=DEFAULT_RTWIN_ALIAS)
    parser.add_argument("--windows-root", default=DEFAULT_WINDOWS_ROOT)
    parser.add_argument("--windows-server-config", default=DEFAULT_WINDOWS_SERVER_CONFIG)
    parser.add_argument("--server-alias", default=DEFAULT_SERVER_ALIAS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="audit a local Gaussian input without network access")
    preflight.add_argument("input")
    preflight.add_argument("--project", required=True)
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
        help="qdel one repeatedly proven scheduler zombie after exact confirmation",
    )
    cleanup_zombie_parser.add_argument("--project", required=True)
    cleanup_zombie_parser.add_argument("--job-id", required=True)
    cleanup_zombie_parser.add_argument("--input-stem", required=True)
    cleanup_zombie_parser.add_argument("--local-dir", required=True)
    cleanup_zombie_parser.add_argument("--stability-seconds", type=int, default=10)
    cleanup_zombie_parser.add_argument("--verify-seconds", type=int, default=5)
    cleanup_zombie_parser.add_argument("--confirmed", action="store_true")
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
