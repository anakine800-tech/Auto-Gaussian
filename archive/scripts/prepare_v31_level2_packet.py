#!/usr/bin/env python3
"""Prepare an offline, non-authoritative V31 Level-2 review packet."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, fields
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from uuid import UUID, uuid5

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_g16 import core, execution
from auto_g16.execution import program
from auto_g16.execution._paths import require_contained, validate_portable_name, validate_posix_path
from auto_g16.transport import _driver

SCHEMA = "auto-g16-v31-level2-review-request/1"
PACKET_SCHEMA = "auto-g16-v31-level2-review-packet/1"
MAX_BYTES = 256 * 1024 * 1024
_NAMESPACE = UUID("bbeb5851-e351-53d2-8c7c-d3280a727975")
_REQUEST_KEYS = {
    "schema", "main_sha", "request_id", "project", "workflow", "batch_purpose",
    "program_kind", "program_data", "plan_intent", "displayed_scientific_meaning",
    "resources", "input", "server_profile", "program_identities",
}


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def encode(value) -> bytes:
    return (json.dumps(_plain(value), sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def _closed(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip() or any(c in value for c in "\r\n\0"):
        raise ValueError(f"{label} must be a non-empty single-line string")
    return value


def _digest(value, length, label):
    if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value) is None:
        raise ValueError(f"{label} must be an exact lowercase digest")
    return value


def _b64(value):
    if not isinstance(value, str):
        raise ValueError("content_base64 must be a string")
    data = base64.b64decode(value, validate=True)
    if base64.b64encode(data).decode("ascii") != value:
        raise ValueError("content_base64 must use canonical encoding")
    return data


def decode(raw: bytes):
    if len(raw) > MAX_BYTES:
        raise ValueError("request exceeds the offline packet size bound")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("nonfinite JSON number")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _profile(value):
    _closed(value, {field.name for field in fields(execution.ServerProfile)}, "server_profile")
    data = dict(value)
    if not isinstance(data["config_files"], list) or not isinstance(data["runtime_contents"], dict):
        raise ValueError("profile content containers are malformed")
    if not isinstance(data["platform_paths"], dict):
        raise ValueError("profile platform_paths must be an object")
    configs = []
    for entry in data["config_files"]:
        _closed(entry, {"logical_name", "content_base64"}, "profile config")
        configs.append((entry["logical_name"], _b64(entry["content_base64"])))
    data["config_files"] = configs
    data["runtime_contents"] = {key: _b64(content) for key, content in data["runtime_contents"].items()}
    if not isinstance(data["jump_topology"], list) or any(not isinstance(hop, list) or len(hop) != 3 for hop in data["jump_topology"]):
        raise ValueError("profile jump_topology is malformed")
    data["jump_topology"] = [tuple(hop) for hop in data["jump_topology"]]
    return execution.ServerProfile(**data)


def _input(value):
    _closed(value, {"portable_name", "content_base64", "sha256", "size_bytes"}, "input")
    validate_portable_name(value["portable_name"], "input portable_name")
    raw = _b64(value["content_base64"])
    _digest(value["sha256"], 64, "input sha256")
    if type(value["size_bytes"]) is not int or len(raw) != value["size_bytes"] or sha256(raw).hexdigest() != value["sha256"]:
        raise ValueError("input bytes differ from the declared exact identity")
    lines = raw.decode("utf-8").splitlines()
    if not lines or re.fullmatch(r"[1-9][0-9]*", lines[0]) is None or len(lines) != int(lines[0]) + 2:
        raise ValueError("input must contain exactly one XYZ frame")
    for line in lines[2:]:
        parts = line.split()
        if len(parts) != 4 or re.fullmatch(r"[A-Z][a-z]?", parts[0]) is None or any(not math.isfinite(float(item)) for item in parts[1:]):
            raise ValueError("XYZ atom record is malformed")
    return raw


def build_packet(request: dict, *, expected_main_sha: str) -> dict:
    """Pure preparation. SHA agreement is caller binding, not a live Git attestation."""
    # Detach caller-owned containers before binding the candidate bytes.
    request = decode(encode(request))
    _closed(request, _REQUEST_KEYS, "request")
    if request["schema"] != SCHEMA:
        raise ValueError("unknown request schema")
    _digest(expected_main_sha, 40, "expected main SHA")
    if _digest(request["main_sha"], 40, "main SHA") != expected_main_sha:
        raise ValueError("main SHA differs from the explicit expected binding")
    request_id = _text(request["request_id"], "request_id")
    if str(UUID(request_id)) != request_id:
        raise ValueError("request_id must be a canonical UUID")
    kind = request["program_kind"]
    if kind not in {"xtb", "crest"}:
        raise ValueError("only xTB and CREST successor candidates are supported")
    if not isinstance(request["program_data"], dict):
        raise ValueError("program_data must be an explicit object")
    validator = program._validate_xtb_data if kind == "xtb" else program._validate_crest_imtd_gc_v2_data
    data = validator(request["program_data"])
    for name in ("plan_intent", "displayed_scientific_meaning"):
        if not isinstance(request[name], dict) or not request[name]:
            raise ValueError(f"{name} must explicitly contain reviewed candidate semantics")
    # Freeze the program meaning inside the plan; no choice is inferred from XYZ.
    if request["plan_intent"].get("program_kind") != kind or request["plan_intent"].get("program_data") != _plain(data):
        raise ValueError("CalculationPlan program semantics differ from program_data")
    raw = _input(request["input"])
    if request["plan_intent"].get("input_sha256") != sha256(raw).hexdigest():
        raise ValueError("CalculationPlan input binding differs from exact XYZ")
    project_data = _closed(request["project"], {"project_id", "remote_project_dir"}, "project")
    project = core.Project(project_id=project_data["project_id"])
    remote_project = validate_posix_path(project_data["remote_project_dir"], "remote_project_dir")
    require_contained(remote_project, execution.LEGACY_REMOTE_ROOT, "remote_project_dir")
    if remote_project == execution.LEGACY_REMOTE_ROOT:
        raise ValueError("a distinct Project directory is required")
    workflow_data = _closed(request["workflow"], {"workflow_run_id", "workflow_name", "project_id"}, "workflow")
    workflow = core.WorkflowRun(**workflow_data)
    if workflow.project_id != project.project_id:
        raise ValueError("Workflow belongs to a different Project")
    # Request bytes bind every generated candidate ID; these are not durable Core records.
    request_bytes = encode(request)
    if len(request_bytes) > MAX_BYTES:
        raise ValueError("request exceeds the offline packet size bound")
    request_sha = sha256(request_bytes).hexdigest()
    def identifier(role):
        return str(uuid5(_NAMESPACE, f"{request_id}:{request_sha}:{role}"))
    batch = core.Batch(batch_id=identifier("batch"), workflow_run_id=workflow.workflow_run_id,
                       purpose=_text(request["batch_purpose"], "batch purpose"))
    task = core.Task(task_id=identifier("task"), workflow_run_id=workflow.workflow_run_id,
                     task_kind="successor-program", batch_id=batch.batch_id)
    attempt = core.Attempt(attempt_id=identifier("attempt"), task_id=task.task_id, ordinal=1)
    plan = core.CalculationPlan(calculation_plan_id=identifier("plan"), task_id=task.task_id,
                                revision=1, intent=request["plan_intent"])
    resource_data = _closed(request["resources"], {"cores", "memory_mb", "walltime_seconds", "queue"}, "resources")
    resource = core.ResourceSpec(resource_spec_id=identifier("resources"), task_id=task.task_id, resources=resource_data)
    resources = execution.ResolvedResourceRequest(resource_spec=resource, **resource_data)
    if resources.queue != "batch":
        raise ValueError("the frozen Torque renderer requires exact batch queue")
    workspace = f"{remote_project}/{attempt.attempt_id}"
    identities = _closed(request["program_identities"], {"xtb", "crest"}, "program_identities")
    for program_kind, identity in identities.items():
        if identity is None:
            continue
        _closed(identity, {"absolute_path", "size_bytes", "sha256", "version"}, f"{program_kind} identity")
        validate_posix_path(identity["absolute_path"], "program executable path")
        _digest(identity["sha256"], 64, "program SHA")
        if type(identity["size_bytes"]) is not int or identity["size_bytes"] < 1:
            raise ValueError("program size must be positive")
        _text(identity["version"], "program version")
        if program_kind == "crest" and identity["version"] != "3.0.2":
            raise ValueError("CREST qualification candidate requires exactly 3.0.2")
    blockers = ["FRESH_PROJECT_ATTESTATION_REQUIRES_SEPARATE_OWNER_GATE",
                "PRODUCTION_QUALIFICATION_AND_CORE_FRESHNESS_NOT_OBSERVED",
                "HUMAN_SCIENTIFIC_BATCH_AND_OPERATIONAL_DECISIONS_REQUIRED"]
    for program_kind, identity in identities.items():
        if identity is None:
            blockers.append(f"MISSING_{program_kind.upper()}_IDENTITY")
    spec = None
    scheduler = []
    profile_semantics = None
    qsub = None
    if request["server_profile"] is None:
        blockers.append("MISSING_PRODUCTION_SERVER_PROFILE")
    else:
        supplied_profile = _profile(request["server_profile"])
        resolved = execution.resolve_server_profile(supplied_profile)
        profile_semantics = _plain(resolved.semantic_payload())
        for program_kind, identity in identities.items():
            if identity is not None and (
                resolved.platform_paths.get(f"{program_kind}_executable_path") != identity["absolute_path"]
                or _plain(resolved.runtime_identities.get(program_kind)) != {key: identity[key] for key in ("size_bytes", "sha256")}
            ):
                raise ValueError("supplied program identity differs from resolved profile")
        # Validate every supplied fact, even when another prerequisite is absent.
        manifest_raw = supplied_profile.runtime_contents.get("transport-deployment-manifest-v3.json")
        dialect_raw = supplied_profile.runtime_contents.get(_driver._RESOURCE_DESCRIPTOR_NAME)
        manifest = None
        dialect = None
        if manifest_raw is None:
            blockers.append("MISSING_SUCCESSOR_DEPLOYMENT_MANIFEST")
        else:
            manifest = _driver._parse_deployment_manifest(manifest_raw, successor=True)
        if dialect_raw is None:
            blockers.append("MISSING_RESOURCE_DESCRIPTOR")
        else:
            dialect = _driver._parse_resource_descriptor(dialect_raw)
            if dialect.dialect_id != _driver._TORQUE_RESOURCE_DIALECT:
                raise ValueError("Level-2 preview requires the frozen production Torque dialect")
        if manifest is not None and dialect is not None:
            _driver._validate_resource_deployment(manifest, dialect)
        # Candidate bytes establish internal consistency only, never production facts.
        if identities[kind] is not None:
            identity = identities[kind]
            spec = program._prepare_program_execution_spec(
                program_kind=kind, executable_path=identity["absolute_path"],
                executable_size_bytes=identity["size_bytes"], executable_sha256=identity["sha256"],
                input_name=request["input"]["portable_name"], input_bytes=raw,
                program_data=data, resolved_profile=resolved)
            scheduler = _plain(program._render_scheduler_artifact(spec, resources, resolved))
            occupied_names = {item["portable_name"] for item in (*spec.required_outputs, *spec.optional_outputs, *scheduler)}
            if request["input"]["portable_name"] in occupied_names:
                raise ValueError("input name conflicts with a scheduler or program output artifact")
            # Renderer-only preview has no snapshot identity or executable authority.
            enactment = _driver._ResourceEnactment(
                "non-authoritative-preview", resources.resolved_resource_request_id,
                resources.cores, resources.memory_mb, resources.walltime_seconds,
                resources.queue, _driver._TORQUE_RESOURCE_DIALECT)
            qsub = {"argv_tail": list(_driver._render_qsub_argv(enactment, scheduler[0]["portable_name"], workspace)),
                    "executable": None, "cwd": workspace,
                    "executable_state": "DEFERRED_UNTIL_DEPLOYMENT_AUTHORITY_REVIEW"}
            if manifest is not None and dialect is not None:
                qsub_root = manifest.trust_roots["server_qsub"]
                qsub.update(executable={"absolute_path": qsub_root.path, "sha256": qsub_root.expected_sha256,
                                        "size_bytes": qsub_root.expected_size_bytes},
                            argv=[qsub_root.path, *qsub["argv_tail"]],
                            executable_state="SUPPLIED_MANIFEST_CONSISTENT_NOT_PRODUCTION_OBSERVED")
    deferred = "DEFERRED_UNTIL_AUTHORIZED_CURRENT_ATTESTATION"
    packet = {
        "schema": PACKET_SCHEMA, "request_sha256": request_sha,
        "source_main": {"sha": expected_main_sha, "verification": "CALLER_BOUND_NOT_GIT_ATTESTED"},
        "status": "BLOCKED_ON_LIVE_PREREQUISITES", "blockers": blockers,
        "live_authorized": False, "execution_ready": False,
        "candidate_records": {"project": asdict(project), "workflow": asdict(workflow),
                              "batch": asdict(batch), "task": asdict(task), "attempt": asdict(attempt),
                              "plan": {"calculation_plan_id": plan.calculation_plan_id, "task_id": task.task_id,
                                       "revision": 1, "intent": _plain(plan.intent)},
                              "resource_spec": {"resource_spec_id": resource.resource_spec_id, "task_id": task.task_id,
                                                "resources": resource_data}},
        "core_records_persisted": False, "input": request["input"],
        "supplied_program_identities": identities, "resolved_profile_candidate": profile_semantics,
        "program_execution_spec_candidate": None if spec is None else _plain(spec.semantic_payload()),
        "program_execution_snapshot": {"state": deferred, "value": None},
        "approval_candidates": {
            "scientific": {"decision": None, "calculation_plan_id": plan.calculation_plan_id,
                           "displayed_semantic_meaning": request["displayed_scientific_meaning"]},
            "batch_submit": {"decision": None, "attempt_ids": [attempt.attempt_id],
                             "calculation_plan_id": plan.calculation_plan_id},
            "operational": {"decision": None, "snapshot_id": None, "state": deferred}},
        "scheduler_artifact_candidates": scheduler, "qsub_preview": qsub,
        "effect_budget": {"authorized_now": {"ssh": 0, "remote_mutations": 0, "program_launches": 0,
                                             "qsub": 0, "qdel": 0},
                          "proposed_after_separate_gates": {"attempt_ids": [attempt.attempt_id],
                              "allocate_workspace_max": 1, "stage_exact_file_max": 2, "qsub_max": 1,
                              "automatic_retry": 0, "qdel": 0, "deletion": 0}},
        "expected_evidence_inventory": ["fresh production program and runtime-data qualification", "current ProjectPhysicalBinding",
            "durable new Core Task and Attempt plus exact CalculationPlan", "three human approval decisions",
            "exact ProgramExecutionSnapshot and deployment manifest", "WINNER and immutable effect receipts",
            "exact qsub response and job identity", "pre-normalization scheduler stdout/stderr/returncode and acquisition binding",
            "terminal scheduler evidence", "exact required outputs, hashes and lineage", "separate scientific review and acceptance"],
        "required_owner_decisions": ["review source, program facts, structure/stereochemistry/charge/spin and all scientific parameters",
            "authorize current Project observation and separately any provisioning", "reconcile candidate IDs and freeze durable new records",
            "approve exact plan and finite Attempt set", "prepare real snapshot under current physical authority",
            "confirm exact snapshot, deployment, resources, input/PBS bytes and effect budget", "issue explicit Live Owner Gate"],
        "stop_conditions": ["any missing, stale, conflicting or malformed authority/evidence", "existing Attempt or target workspace",
            "symlink, physical identity drift or root escape", "UNKNOWN or ambiguous submission: never retry",
            "missing terminal evidence or required output: never accept science", "any unapproved effect or scope expansion"],
        "reconciliation": ["stop effects and preserve exact raw bytes, receipts and Attempt/snapshot/job lineage",
            "request a separate Owner gate for bounded read-only reconciliation", "UNKNOWN remains UNKNOWN without proof; no new Attempt or qsub retry",
            "scheduler completion alone is not scientific acceptance; require a separate scientific review"],
        "historical_level2": {"job_id": "682.master", "status": "LEVEL2_TERMINAL_EVIDENCE_INCOMPLETE",
                              "retroactively_repaired": False, "fresh_scientific_qualification_required": True},
    }
    packet["packet_sha256"] = sha256(encode(packet)).hexdigest()
    return packet


@contextmanager
def _parent(path: Path):
    """Traverse absolute local parents descriptor-relatively without following links."""
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts) or len(path.parts) < 2:
        raise ValueError("packet paths must be absolute and normalized")
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def read_request(path: Path):
    with _parent(path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                raise ValueError("request must be a bounded regular file")
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("request changed while being read")
    return decode(raw)


def write_new(path: Path, packet: dict):
    raw = encode(packet)
    with _parent(path) as (parent, name):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        packet = build_packet(read_request(args.request), expected_main_sha=args.expected_main_sha)
        write_new(args.output, packet)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"packet preparation rejected: {exc}", file=sys.stderr)
        return 2
    print(f"{packet['status']}: offline review packet written; no live authority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
