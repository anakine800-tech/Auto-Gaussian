#!/usr/bin/env python3
"""Fail-closed package-4 resource policy, gate, monitoring, and accounting helpers."""

from __future__ import annotations

import copy
import argparse
import json
import math
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import execution_batch


POLICY_SCHEMA = "gaussian-execution-resource-policy/1"
GATE_SCHEMA = "gaussian-execution-resource-gate/2"
LEDGER_SCHEMA = "gaussian-execution-batch/3"
SCHEDULER_SNAPSHOT_SCHEMA = "gaussian-scheduler-resource-snapshot/1"
ACCOUNTING_SCHEMA = "gaussian-pbs-resource-accounting/1"
BATCH_QSTAT_SCHEMA = "gaussian-batch-qstat-snapshot/1"
ACTIVE_STATES = {"queued", "running"}
UNRESOLVED_STATES = {"submission_uncertain", "submitted", "queued", "running"}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
RESOURCE_TIERS = {"simple": (8, 12), "general": (22, 50), "complex": (44, 120)}
MAX_SCHEDULER_CLOCK_SKEW_SECONDS = 5.0


class ResourceError(ValueError):
    """Raised when a package-4 contract cannot be proved exactly."""


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ResourceError(f"{label} must contain exactly {sorted(fields)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResourceError(f"{label} must be a non-empty string")
    return value


def _sha(value: Any, label: str) -> str:
    value = _text(value, label)
    if SHA_RE.fullmatch(value) is None:
        raise ResourceError(f"{label} must be a lowercase SHA-256")
    return value


def _number(value: Any, label: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResourceError(f"{label} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (integer and not number.is_integer()):
        raise ResourceError(f"{label} must be a finite non-negative {'integer' if integer else 'number'}")
    return int(number) if integer else number


def validate_resource_tuple(resource_tier: Any, cores: Any, memory_gb: Any) -> None:
    tier = _text(resource_tier, "resource_tier")
    core_count = int(_number(cores, "cores", integer=True))
    memory = int(_number(memory_gb, "memory_gb", integer=True))
    if tier not in {*RESOURCE_TIERS, "custom_reviewed"}:
        raise ResourceError("resource_tier is not a closed reviewed tier")
    if tier in RESOURCE_TIERS and (core_count, memory) != RESOURCE_TIERS[tier]:
        raise ResourceError("named resource tier conflicts with exact cores/memory")


def _time(value: Any, label: str) -> datetime:
    try:
        return execution_batch.parse_time(value)
    except execution_batch.BatchError as exc:
        raise ResourceError(f"{label} is invalid: {exc}") from exc


def _payload(document: dict[str, Any], field: str = "payload_sha256") -> str:
    return execution_batch.digest_value({key: value for key, value in document.items() if key != field})


def load(path: Path) -> dict[str, Any]:
    try:
        return execution_batch.load_json(path)
    except execution_batch.BatchError as exc:
        raise ResourceError(str(exc)) from exc


def load_artifact(path: Path) -> tuple[dict[str, Any], str, int]:
    if path.is_symlink() or not path.is_file():
        raise ResourceError("resource artifact must be a regular non-symlink file")
    data = path.read_bytes()
    document = load(path)
    return document, __import__("hashlib").sha256(data).hexdigest(), len(data)


def validate_policy(document: dict[str, Any]) -> dict[str, Any]:
    _exact(document, {
        "schema", "policy_id", "reviewed_at", "reviewer", "limits", "governance",
        "payload_sha256",
    }, "resource policy")
    if document["schema"] != POLICY_SCHEMA:
        raise ResourceError(f"resource policy schema must be {POLICY_SCHEMA}")
    _text(document["policy_id"], "policy_id")
    _text(document["reviewer"], "reviewer")
    _time(document["reviewed_at"], "reviewed_at")
    limits = _exact(document["limits"], {
        "max_estimated_core_hours", "max_remaining_core_hours",
        "max_concurrent_unresolved_attempts", "max_concurrent_active_attempts",
        "max_total_cores", "max_total_memory_gb", "max_job_cores",
        "max_job_memory_gb", "max_job_walltime_seconds",
    }, "resource policy limits")
    for key in ("max_estimated_core_hours", "max_remaining_core_hours"):
        _number(limits[key], f"limits.{key}")
    for key in set(limits) - {"max_estimated_core_hours", "max_remaining_core_hours"}:
        if _number(limits[key], f"limits.{key}", integer=True) < 1:
            raise ResourceError(f"limits.{key} must be positive")
    governance = {
        "unknown_scheduler_or_ledger_state_fails_closed": True,
        "resources_must_be_exact_reviewed_bindings": True,
        "walltime_must_be_explicitly_reviewed": True,
        "automatic_resource_change": False,
        "automatic_retry": False,
        "monitoring_changes_scientific_conclusion": False,
    }
    if document["governance"] != governance:
        raise ResourceError("resource policy governance boundary changed")
    if _sha(document["payload_sha256"], "payload_sha256") != _payload(document):
        raise ResourceError("resource policy payload_sha256 mismatch")
    return document


def finalize_policy(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["payload_sha256"] = _payload(result)
    return validate_policy(result)


def validate_scheduler_snapshot(document: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    _exact(document, {
        "schema", "snapshot_id", "collected_at", "source", "transport",
        "scope", "freshness", "attempts", "payload_sha256",
    }, "scheduler resource snapshot")
    if document["schema"] != SCHEDULER_SNAPSHOT_SCHEMA:
        raise ResourceError("scheduler resource snapshot schema is unsupported")
    _text(document["snapshot_id"], "snapshot_id")
    collected = _time(document["collected_at"], "collected_at")
    _text(document["source"], "source")
    scope = _exact(document["scope"], {"kind", "owner", "completeness", "batch_evidence_sha256"}, "scheduler resource scope")
    if scope["kind"] != "complete_user_active_jobs" or scope["completeness"] != "complete":
        raise ResourceError("scheduler resource scope is not complete")
    _text(scope["owner"], "scheduler scope owner"); _sha(scope["batch_evidence_sha256"], "batch evidence sha256")
    if document["transport"] != {"classification": "success", "status": "known"}:
        raise ResourceError("scheduler transport state is unknown")
    freshness = _exact(document["freshness"], {
        "classification", "age_seconds", "max_age_seconds",
    }, "scheduler freshness")
    age = _number(freshness["age_seconds"], "freshness.age_seconds")
    maximum = _number(freshness["max_age_seconds"], "freshness.max_age_seconds")
    if freshness["classification"] != "fresh" or age > maximum:
        raise ResourceError("scheduler resource snapshot is stale or freshness is unknown")
    if now is not None:
        gate_time = _time(now, "gate evaluated_at")
        future_seconds = (collected - gate_time).total_seconds()
        if future_seconds > MAX_SCHEDULER_CLOCK_SKEW_SECONDS:
            raise ResourceError("scheduler resource snapshot collected_at is in the future")
        observed_age = max(0.0, (gate_time - collected).total_seconds())
        if age - observed_age > MAX_SCHEDULER_CLOCK_SKEW_SECONDS:
            raise ResourceError("scheduler resource snapshot declared age is inconsistent with collected_at")
        # Never let a smaller declared age understate freshness at a later
        # gate/reservation/pre-qsub replay. The immutable declaration may be
        # older than this replay, so freshness is decided by the larger age.
        effective_age = max(age, observed_age)
        if effective_age > maximum:
            raise ResourceError("scheduler resource snapshot expired before gate evaluation")
    if not isinstance(document["attempts"], list):
        raise ResourceError("scheduler attempts must be an array")
    seen: set[str] = set()
    for attempt in document["attempts"]:
        _exact(attempt, {"attempt_id", "state", "cores", "memory_gb"}, "scheduler attempt")
        attempt_id = _text(attempt["attempt_id"], "scheduler attempt_id")
        if attempt_id in seen:
            raise ResourceError("scheduler snapshot repeats an attempt")
        seen.add(attempt_id)
        if attempt["state"] not in {"submitted", *ACTIVE_STATES}:
            raise ResourceError("scheduler active attempt state is unknown or non-active")
        if _number(attempt["cores"], "scheduler cores", integer=True) < 1:
            raise ResourceError("scheduler cores must be positive")
        if _number(attempt["memory_gb"], "scheduler memory_gb", integer=True) < 1:
            raise ResourceError("scheduler memory_gb must be positive")
    if _sha(document["payload_sha256"], "payload_sha256") != _payload(document):
        raise ResourceError("scheduler snapshot payload_sha256 mismatch")
    return document


def finalize_scheduler_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["payload_sha256"] = _payload(result)
    return validate_scheduler_snapshot(result)


def validate_batch_qstat_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    _exact(document, {
        "schema", "collected_at", "source", "scope", "freshness", "age_seconds",
        "transport_classification", "job_ids", "records", "read_only", "error",
        "evidence_sha256",
    }, "batch qstat snapshot")
    if document["schema"] != BATCH_QSTAT_SCHEMA or document["source"] != "single_complete_user_qstat":
        raise ResourceError("batch qstat snapshot schema/source mismatch")
    _time(document["collected_at"], "batch collected_at")
    _number(document["age_seconds"], "batch age_seconds")
    if document["read_only"] is not True:
        raise ResourceError("batch qstat snapshot is not read-only")
    scope = _exact(document["scope"], {
        "kind", "owner", "completeness", "requested_job_ids",
    }, "batch qstat scope")
    if scope["kind"] != "complete_user_active_jobs":
        raise ResourceError("batch qstat scope is not complete user active jobs")
    requested = scope["requested_job_ids"]
    if not isinstance(requested, list) or any(not isinstance(item, str) or not item for item in requested) or len(set(requested)) != len(requested):
        raise ResourceError("batch requested job IDs are not a unique exact list")
    job_ids = document["job_ids"]
    records = document["records"]
    if not isinstance(job_ids, list) or any(not isinstance(item, str) or not item for item in job_ids) or len(set(job_ids)) != len(job_ids):
        raise ResourceError("batch observed job IDs are not a unique exact list")
    if not isinstance(records, dict) or set(records) != set(job_ids):
        raise ResourceError("batch qstat record keys differ from the exact job set")
    if document["transport_classification"] == "success":
        if document["freshness"] != "fresh" or scope["completeness"] != "complete" or document["error"] is not None:
            raise ResourceError("successful batch qstat lacks fresh complete evidence")
        _text(scope["owner"], "batch qstat owner")
    elif document["transport_classification"] in {"timeout", "transport_error", "parse_failed"}:
        if document["freshness"] != "unknown" or scope["completeness"] != "unknown" or scope["owner"] is not None or not isinstance(document["error"], str) or not document["error"]:
            raise ResourceError("failed batch qstat must be closed unknown evidence")
        if job_ids or records:
            raise ResourceError("failed batch qstat cannot claim partial job totals")
    else:
        raise ResourceError("batch qstat transport classification is not closed")
    for job_id, record in records.items():
        _exact(record, {"status", "pbs_state", "job_name", "cores", "memory_gb", "error"}, f"batch qstat record {job_id}")
        if record["status"] == "present":
            if record["pbs_state"] not in {"Q", "R"} or not isinstance(record["job_name"], str) or not record["job_name"] or record["error"] is not None:
                raise ResourceError("present batch record has unknown identity/state")
            for key in ("cores", "memory_gb"):
                if record[key] is not None and _number(record[key], f"batch {key}", integer=True) < 1:
                    raise ResourceError(f"batch {key} must be positive or unknown")
        elif record["status"] == "unknown":
            if any(record[key] is not None for key in ("pbs_state", "job_name", "cores", "memory_gb")) or not isinstance(record["error"], str) or not record["error"]:
                raise ResourceError("unknown batch record must not claim partial evidence")
        else:
            raise ResourceError("batch record status is not closed")
    if document["evidence_sha256"] != execution_batch.digest_value({key: value for key, value in document.items() if key != "evidence_sha256"}):
        raise ResourceError("batch qstat snapshot hash mismatch")
    return document


def build_scheduler_snapshot(
    ledger: dict[str, Any], batch_observation: dict[str, Any], *,
    snapshot_id: str, max_age_seconds: int,
) -> dict[str, Any]:
    """Build the gate snapshot only from one exact batch poll and /3 gate resources."""
    validate_ledger(ledger)
    _text(snapshot_id, "snapshot_id")
    if _number(max_age_seconds, "max_age_seconds", integer=True) < 1:
        raise ResourceError("max_age_seconds must be positive")
    validate_batch_qstat_snapshot(batch_observation)
    if (
        batch_observation["scope"]["completeness"] != "complete"
        or batch_observation["transport_classification"] != "success"
        or batch_observation["freshness"] != "fresh"
    ):
        raise ResourceError("batch scheduler observation transport/freshness is unknown")
    _time(batch_observation["collected_at"], "batch collected_at")
    age = _number(batch_observation["age_seconds"], "batch age_seconds")
    if age > max_age_seconds:
        raise ResourceError("batch scheduler observation is stale")
    job_ids = batch_observation["job_ids"]
    records = batch_observation["records"]
    if not isinstance(job_ids, list) or len(set(job_ids)) != len(job_ids) or not isinstance(records, dict) or set(records) != set(job_ids):
        raise ResourceError("batch scheduler observation job set is malformed")
    scheduler_state = {"Q": "queued", "R": "running"}
    attempts: list[dict[str, Any]] = []
    by_job = {
        item["scheduler_reference"]: item for item in ledger["attempts"]
        if item["state"] in UNRESOLVED_STATES and item["scheduler_reference"] is not None
    }
    unresolved = [item for item in ledger["attempts"] if item["state"] in UNRESOLVED_STATES]
    if any(item["state"] == "submission_uncertain" or item["scheduler_reference"] is None for item in unresolved):
        raise ResourceError("ledger has an unresolved attempt with unknown scheduler occupancy")
    if set(by_job) - set(job_ids):
        raise ResourceError("batch scheduler observation omitted an unresolved ledger job")
    for job_id in job_ids:
        record = records[job_id]
        if record["status"] != "present" or record["pbs_state"] not in scheduler_state:
            raise ResourceError("batch scheduler record is absent, unknown, or unsupported")
        state = scheduler_state[record["pbs_state"]]
        cores = record["cores"]; memory_gb = record["memory_gb"]
        if isinstance(cores, bool) or not isinstance(cores, int) or cores < 1 or isinstance(memory_gb, bool) or not isinstance(memory_gb, int) or memory_gb < 1:
            raise ResourceError("batch scheduler record lacks exact cores/memory")
        ledger_attempt = by_job.get(job_id)
        if ledger_attempt is not None:
            if ledger_attempt["state"] != state:
                raise ResourceError("batch scheduler state conflicts with ledger attempt state")
            gate = ledger_attempt["resource_gate"]
            if gate["status"] != "passed" or gate["requested_resources"]["cores"] != cores or gate["requested_resources"]["memory_gb"] != memory_gb:
                raise ResourceError("batch scheduler resources conflict with the exact attempt gate")
            attempt_id = ledger_attempt["attempt_id"]
        else:
            attempt_id = "external-scheduler-job-" + execution_batch.digest_value({"job_id": job_id})
        attempts.append({"attempt_id": attempt_id, "state": state, "cores": cores, "memory_gb": memory_gb})
    return finalize_scheduler_snapshot({
        "schema": SCHEDULER_SNAPSHOT_SCHEMA, "snapshot_id": snapshot_id,
        "collected_at": batch_observation["collected_at"],
        "source": "package4_builder_from_single_complete_user_qstat_and_v3_ledger",
        "scope": {"kind": "complete_user_active_jobs", "owner": batch_observation["scope"]["owner"], "completeness": "complete", "batch_evidence_sha256": batch_observation["evidence_sha256"]},
        "transport": {"classification": "success", "status": "known"},
        "freshness": {"classification": "fresh", "age_seconds": age, "max_age_seconds": max_age_seconds},
        "attempts": attempts, "payload_sha256": "",
    })


def _historical_gate() -> dict[str, Any]:
    return {
        "schema": GATE_SCHEMA,
        "owner": "auto-g16-package-4",
        "status": "historical_unbound_v2_replay_only",
        "policy_id": None,
        "policy_sha256": None,
        "gate_id": None,
        "gate_sha256": None,
        "resource_state_sha256": None,
        "resource_state_revision": None,
        "evaluated_at": None,
        "execution_scope": None,
        "requested_resources": None,
        "aggregate_before": None,
        "scheduler_snapshot": None,
    }


def _validate_gate_binding(gate: Any, *, allow_historical: bool) -> dict[str, Any]:
    gate = _exact(gate, {
        "schema", "owner", "status", "policy_id", "policy_sha256", "gate_id",
        "gate_sha256", "resource_state_sha256", "resource_state_revision", "evaluated_at",
        "execution_scope", "requested_resources", "aggregate_before", "scheduler_snapshot",
    }, "resource gate binding")
    if gate["schema"] != GATE_SCHEMA or gate["owner"] != "auto-g16-package-4":
        raise ResourceError("resource gate owner/schema mismatch")
    if gate["status"] == "historical_unbound_v2_replay_only" and allow_historical:
        if gate != _historical_gate():
            raise ResourceError("historical resource gate marker is malformed")
        return gate
    if gate["status"] != "passed":
        raise ResourceError("resource gate did not pass")
    for key in ("policy_sha256", "gate_sha256", "resource_state_sha256"):
        _sha(gate[key], key)
    for key in ("policy_id", "gate_id"):
        _text(gate[key], key)
    _number(gate["resource_state_revision"], "resource_state_revision", integer=True)
    _time(gate["evaluated_at"], "evaluated_at")
    scope = _exact(gate["execution_scope"], {"scientific_task_id", "attempt_id", "project", "input_sha256"}, "gate execution scope")
    _text(scope["scientific_task_id"], "scientific_task_id"); _text(scope["attempt_id"], "attempt_id")
    if PROJECT_RE.fullmatch(_text(scope["project"], "project")) is None: raise ResourceError("gate project is unsafe")
    _sha(scope["input_sha256"], "input_sha256")
    requested = _exact(gate["requested_resources"], {
        "resource_tier", "cores", "memory_gb", "walltime_seconds", "estimated_core_hours",
    }, "requested resources")
    _text(requested["resource_tier"], "resource_tier")
    validate_resource_tuple(requested["resource_tier"], requested["cores"], requested["memory_gb"])
    for key in ("cores", "memory_gb", "walltime_seconds"):
        if _number(requested[key], key, integer=True) < 1:
            raise ResourceError(f"{key} must be positive")
    if _number(requested["estimated_core_hours"], "estimated_core_hours") <= 0:
        raise ResourceError("new resource gate estimated_core_hours must be positive")
    aggregate = _exact(gate["aggregate_before"], {
        "estimated_core_hours", "remaining_core_hours", "unresolved_attempts",
        "active_attempts", "total_cores", "total_memory_gb",
    }, "resource aggregate")
    for key in aggregate:
        _number(aggregate[key], f"aggregate_before.{key}", integer=key not in {"estimated_core_hours", "remaining_core_hours"})
    snapshot = _exact(gate["scheduler_snapshot"], {
        "snapshot_id", "payload_sha256", "artifact_sha256", "artifact_size", "collected_at",
        "source", "freshness", "transport_classification",
    }, "gate scheduler binding")
    _text(snapshot["snapshot_id"], "snapshot_id")
    _sha(snapshot["payload_sha256"], "scheduler snapshot hash")
    _sha(snapshot["artifact_sha256"], "scheduler artifact hash")
    _number(snapshot["artifact_size"], "scheduler artifact size", integer=True)
    _time(snapshot["collected_at"], "scheduler collected_at")
    _text(snapshot["source"], "scheduler source")
    if snapshot["freshness"] != "fresh" or snapshot["transport_classification"] != "success":
        raise ResourceError("gate scheduler binding is not fresh and successful")
    expected = execution_batch.digest_value({key: value for key, value in gate.items() if key != "gate_sha256"})
    if gate["gate_sha256"] != expected:
        raise ResourceError("resource gate hash mismatch")
    return gate


def _v2_projection(ledger: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(ledger)
    projected.pop("resource_state_revision", None)
    projected.pop("resource_state_sha256", None)
    projected["schema"] = execution_batch.BATCH_V2_SCHEMA
    projected["resource_policy_interface"] = {
        "schema": "gaussian-execution-resource-policy-hook/1",
        "owner": "auto-g16-package-4",
        "status": "interface_reserved_not_enforced_by_package_2",
        "hard_budget_gate_implemented": False,
        "concurrency_resource_gate_implemented": False,
    }
    for attempt in projected["attempts"]:
        attempt.pop("resource_accounting", None)
        attempt["resource_gate"] = {
            "schema": "gaussian-execution-resource-gate/1",
            "owner": "auto-g16-package-4",
            "status": "not_evaluated_by_package_2",
        }
    projected["ledger_sha256"] = execution_batch.digest_value(
        {key: value for key, value in projected.items() if key != "ledger_sha256"}
    )
    return projected


def validate_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    if set(ledger) != {
        "schema", "batch", "revision", "created_at", "tasks", "attempts", "events",
        "counters", "resource_policy_interface", "calculation_ready",
        "no_submission_authorization", "resource_state_revision", "resource_state_sha256",
        "ledger_sha256",
    } or ledger.get("schema") != LEDGER_SCHEMA:
        raise ResourceError(f"protected package-4 submission requires a closed {LEDGER_SCHEMA} ledger")
    if ledger["resource_policy_interface"] != {
        "schema": "gaussian-execution-resource-policy-hook/2",
        "owner": "auto-g16-package-4",
        "status": "enforced_for_every_new_live_submit",
        "hard_budget_gate_implemented": True,
        "concurrency_resource_gate_implemented": True,
    }:
        raise ResourceError("active package-4 resource interface changed")
    try:
        execution_batch.validate_submission_ledger(_v2_projection(ledger))
    except execution_batch.BatchError as exc:
        raise ResourceError(str(exc)) from exc
    for attempt in ledger["attempts"]:
        _validate_gate_binding(attempt["resource_gate"], allow_historical=True)
        accounting = attempt["resource_accounting"]
        if accounting is not None:
            validate_accounting(accounting)
            if accounting["attempt_id"] != attempt["attempt_id"] or accounting["job_id"] != attempt["scheduler_reference"]:
                raise ResourceError("resource accounting is not bound to the exact attempt/job")
            if attempt["consumed_core_hours"] != accounting["actual_core_hours"]:
                raise ResourceError("consumed core-hours differ from resource accounting")
    if ledger["ledger_sha256"] != execution_batch.digest_value({key: value for key, value in ledger.items() if key != "ledger_sha256"}):
        raise ResourceError("package-4 ledger hash mismatch")
    _number(ledger["resource_state_revision"], "resource_state_revision", integer=True)
    if ledger["resource_state_sha256"] != execution_batch.digest_value(_resource_state_projection(ledger)):
        raise ResourceError("package-4 resource-state projection hash mismatch")
    return ledger


def _resource_state_projection(ledger: dict[str, Any]) -> dict[str, Any]:
    """Only occupancy, budget, task, attempt, and accounting changes invalidate a gate."""
    return {
        "schema": LEDGER_SCHEMA,
        "batch_id": ledger["batch"]["batch_id"],
        "tasks": copy.deepcopy(ledger["tasks"]),
        "attempts": copy.deepcopy(ledger["attempts"]),
        "counters": copy.deepcopy(ledger["counters"]),
        "resource_state_revision": ledger["resource_state_revision"],
    }


def _seal(ledger: dict[str, Any], *, resource_changed: bool = False) -> dict[str, Any]:
    ledger["counters"] = execution_batch._calculate_v2_counters(ledger)
    if "resource_state_revision" not in ledger:
        ledger["resource_state_revision"] = 0
    elif resource_changed:
        ledger["resource_state_revision"] += 1
    ledger["resource_state_sha256"] = execution_batch.digest_value(_resource_state_projection(ledger))
    ledger["ledger_sha256"] = execution_batch.digest_value({key: value for key, value in ledger.items() if key != "ledger_sha256"})
    return ledger


def migrate_v2_to_v3(path: Path, *, migrated_at: str, migration_source: str) -> dict[str, Any]:
    _time(migrated_at, "migrated_at")
    _text(migration_source, "migration_source")
    with execution_batch._locked(path):
        raw = execution_batch.load_json(path)
        if raw.get("schema") == LEDGER_SCHEMA:
            return validate_ledger(raw)
        try:
            ledger = execution_batch.validate_submission_ledger(raw)
        except execution_batch.BatchError as exc:
            raise ResourceError(f"only a valid /2 ledger can migrate to /3: {exc}") from exc
        upgraded = copy.deepcopy(ledger)
        upgraded["schema"] = LEDGER_SCHEMA
        upgraded["resource_policy_interface"] = {
            "schema": "gaussian-execution-resource-policy-hook/2",
            "owner": "auto-g16-package-4",
            "status": "enforced_for_every_new_live_submit",
            "hard_budget_gate_implemented": True,
            "concurrency_resource_gate_implemented": True,
        }
        for attempt in upgraded["attempts"]:
            attempt["resource_gate"] = _historical_gate()
            attempt["resource_accounting"] = None
        upgraded["revision"] += 1
        execution_batch._append_event(upgraded, "ledger_migrated_to_v3", {
            "from_schema": execution_batch.BATCH_V2_SCHEMA,
            "source": migration_source,
            "historical_attempts_remain_resource_unbound_replay_only": True,
        }, timestamp=migrated_at, important=True)
        _seal(upgraded)
        validate_ledger(upgraded)
        execution_batch._atomic_write(path, upgraded)
        return upgraded


def evaluate_gate(
    ledger: dict[str, Any], policy: dict[str, Any], scheduler: dict[str, Any], *,
    gate_id: str, evaluated_at: str, resource_tier: str, cores: int, memory_gb: int,
    walltime_seconds: int, estimated_core_hours: float,
    scheduler_artifact_sha256: str, scheduler_artifact_size: int,
    scientific_task_id: str, attempt_id: str, project: str, input_sha256: str,
) -> dict[str, Any]:
    validate_ledger(ledger)
    validate_policy(policy)
    validate_scheduler_snapshot(scheduler, now=evaluated_at)
    _text(gate_id, "gate_id")
    task = next((item for item in ledger["tasks"] if item["scientific_task_id"] == scientific_task_id), None)
    if task is None or task["identity"]["relevant_input_sha256"] != _sha(input_sha256, "input_sha256"):
        raise ResourceError("resource gate execution scope is not an exact admitted task/input")
    if PROJECT_RE.fullmatch(project) is None: raise ResourceError("resource gate project is unsafe")
    _text(attempt_id, "attempt_id")
    validate_resource_tuple(resource_tier, cores, memory_gb)
    request = {
        "resource_tier": resource_tier,
        "cores": int(_number(cores, "cores", integer=True)),
        "memory_gb": int(_number(memory_gb, "memory_gb", integer=True)),
        "walltime_seconds": int(_number(walltime_seconds, "walltime_seconds", integer=True)),
        "estimated_core_hours": float(_number(estimated_core_hours, "estimated_core_hours")),
    }
    if any(request[key] < 1 for key in ("cores", "memory_gb", "walltime_seconds")):
        raise ResourceError("per-job cores, memory, and walltime must be positive")
    if request["estimated_core_hours"] <= 0:
        raise ResourceError("new resource gate estimated_core_hours must be positive")
    limits = policy["limits"]
    scheduler_attempts = scheduler["attempts"]
    ledger_unresolved = [item for item in ledger["attempts"] if item["state"] in UNRESOLVED_STATES]
    if any(item["state"] == "submission_uncertain" for item in ledger_unresolved):
        raise ResourceError("submission_uncertain attempt makes resource occupancy unknown")
    scheduler_by_id = {item["attempt_id"]: item for item in scheduler_attempts}
    for item in ledger_unresolved:
        if item["resource_gate"]["status"] != "passed":
            raise ResourceError("unresolved historical attempt has unknown resources")
        observed = scheduler_by_id.get(item["attempt_id"])
        expected_resources = item["resource_gate"]["requested_resources"]
        if observed is None:
            raise ResourceError("scheduler snapshot omitted an unresolved ledger attempt")
        if (
            observed["state"] != item["state"]
            or observed["cores"] != expected_resources["cores"]
            or observed["memory_gb"] != expected_resources["memory_gb"]
        ):
            raise ResourceError("scheduler and ledger state/resources conflict")
    aggregate = {
        "estimated_core_hours": float(ledger["counters"]["estimated_core_hours"]),
        "remaining_core_hours": float(limits["max_remaining_core_hours"]) - float(ledger["counters"]["estimated_core_hours"]),
        "unresolved_attempts": len(ledger_unresolved),
        "active_attempts": len(scheduler_attempts),
        "total_cores": sum(int(item["cores"]) for item in scheduler_attempts),
        "total_memory_gb": sum(int(item["memory_gb"]) for item in scheduler_attempts),
    }
    checks = {
        "max_estimated_core_hours": aggregate["estimated_core_hours"] + request["estimated_core_hours"] <= limits["max_estimated_core_hours"],
        "max_remaining_core_hours": request["estimated_core_hours"] <= aggregate["remaining_core_hours"],
        "max_concurrent_unresolved_attempts": aggregate["unresolved_attempts"] + 1 <= limits["max_concurrent_unresolved_attempts"],
        "max_concurrent_active_attempts": aggregate["active_attempts"] + 1 <= limits["max_concurrent_active_attempts"],
        "max_total_cores": aggregate["total_cores"] + request["cores"] <= limits["max_total_cores"],
        "max_total_memory_gb": aggregate["total_memory_gb"] + request["memory_gb"] <= limits["max_total_memory_gb"],
        "max_job_cores": request["cores"] <= limits["max_job_cores"],
        "max_job_memory_gb": request["memory_gb"] <= limits["max_job_memory_gb"],
        "max_job_walltime_seconds": request["walltime_seconds"] <= limits["max_job_walltime_seconds"],
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    if failed:
        raise ResourceError("resource hard gate failed: " + ", ".join(failed))
    gate = {
        "schema": GATE_SCHEMA,
        "owner": "auto-g16-package-4",
        "status": "passed",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["payload_sha256"],
        "gate_id": gate_id,
        "gate_sha256": "",
        "resource_state_sha256": ledger["resource_state_sha256"],
        "resource_state_revision": ledger["resource_state_revision"],
        "evaluated_at": evaluated_at,
        "execution_scope": {"scientific_task_id": scientific_task_id, "attempt_id": attempt_id, "project": project, "input_sha256": input_sha256},
        "requested_resources": request,
        "aggregate_before": aggregate,
        "scheduler_snapshot": {
            "snapshot_id": scheduler["snapshot_id"],
            "payload_sha256": scheduler["payload_sha256"],
            "artifact_sha256": _sha(scheduler_artifact_sha256, "scheduler artifact sha256"),
            "artifact_size": int(_number(scheduler_artifact_size, "scheduler artifact size", integer=True)),
            "collected_at": scheduler["collected_at"],
            "source": scheduler["source"],
            "freshness": scheduler["freshness"]["classification"],
            "transport_classification": scheduler["transport"]["classification"],
        },
    }
    gate["gate_sha256"] = execution_batch.digest_value({key: value for key, value in gate.items() if key != "gate_sha256"})
    return _validate_gate_binding(gate, allow_historical=False)


def reserve_attempt(
    path: Path, task_id: str, *, identity: dict[str, str], idempotency_key: str,
    project: str, remote_workdir: str, input_sha256: str, live_approval_id: str,
    live_approval_sha256: str, estimated_core_hours_evidence: dict[str, str],
    reserved_at: str, audit_reason: str, policy: dict[str, Any], gate: dict[str, Any],
    scheduler_snapshot: dict[str, Any], scheduler_artifact_sha256: str,
    scheduler_artifact_size: int,
) -> dict[str, Any]:
    validate_policy(policy)
    _validate_gate_binding(gate, allow_historical=False)
    if gate["policy_id"] != policy["policy_id"] or gate["policy_sha256"] != policy["payload_sha256"]:
        raise ResourceError("resource gate is not bound to the exact policy")
    validate_scheduler_snapshot(scheduler_snapshot, now=reserved_at)
    snapshot_binding = gate["scheduler_snapshot"]
    if (
        snapshot_binding["snapshot_id"] != scheduler_snapshot["snapshot_id"]
        or snapshot_binding["payload_sha256"] != scheduler_snapshot["payload_sha256"]
        or snapshot_binding["artifact_sha256"] != _sha(scheduler_artifact_sha256, "scheduler artifact sha256")
        or snapshot_binding["artifact_size"] != _number(scheduler_artifact_size, "scheduler artifact size", integer=True)
    ):
        raise ResourceError("reservation scheduler artifact differs from the exact gate binding")
    if PROJECT_RE.fullmatch(project) is None:
        raise ResourceError("project must be a safe 1-15 character server job name")
    if remote_workdir != f"/home/user100/SDL/{project}":
        raise ResourceError("reservation remote_workdir must equal the fixed exact project path")
    with execution_batch._locked(path):
        ledger = validate_ledger(execution_batch.load_json(path))
        if ledger["resource_state_sha256"] != gate["resource_state_sha256"] or ledger["resource_state_revision"] != gate["resource_state_revision"]:
            raise ResourceError("resource gate is stale relative to the locked resource state")
        # Reuse the package-2 reservation rules in memory, without publishing a second ledger.
        task = next((item for item in ledger["tasks"] if item["scientific_task_id"] == task_id), None)
        if task is None or execution_batch.classify_retry(task["identity"], identity)["classification"] != "exact_resubmission":
            raise ResourceError("resource-bound attempt requires the exact admitted scientific task")
        if input_sha256 != task["identity"]["relevant_input_sha256"]:
            raise ResourceError("resource-bound attempt input hash mismatch")
        key = _text(idempotency_key, "idempotency_key")
        attempt_id = execution_batch.attempt_id_for(ledger["batch"]["batch_id"], key)
        if gate["execution_scope"] != {"scientific_task_id": task_id, "attempt_id": attempt_id, "project": project, "input_sha256": input_sha256}:
            raise ResourceError("resource gate execution scope differs from the reservation")
        if any(item["idempotency_key"] == key for item in ledger["attempts"]):
            raise ResourceError("idempotency key is already reserved")
        if any(item["live_approval_id"] == live_approval_id or item["live_approval_sha256"] == live_approval_sha256 for item in ledger["attempts"]):
            raise ResourceError("one-time live approval was already consumed")
        if any(item["scientific_task_id"] == task_id and item["state"] in UNRESOLVED_STATES for item in ledger["attempts"]):
            raise ResourceError("task already has an unresolved physical attempt")
        request = gate["requested_resources"]
        attempt = {
            "attempt_id": attempt_id, "scientific_task_id": task_id,
            "idempotency_key": key, "state": "submission_uncertain", "project": project,
            "job_name": project, "remote_workdir": remote_workdir,
            "input_sha256": _sha(input_sha256, "input_sha256"),
            "live_approval_id": _text(live_approval_id, "live_approval_id"),
            "live_approval_sha256": _sha(live_approval_sha256, "live_approval_sha256"),
            "estimated_core_hours": request["estimated_core_hours"],
            "estimated_core_hours_evidence": execution_batch.validate_evidence(estimated_core_hours_evidence, "estimated_core_hours_evidence"),
            "consumed_core_hours": None, "consumed_core_hours_evidence": None,
            "reserved_at": reserved_at, "updated_at": reserved_at,
            "scheduler_reference": None, "reconciliation_evidence": None,
            "audit_reason": _text(audit_reason, "audit_reason"),
            "resource_gate": copy.deepcopy(gate), "resource_accounting": None,
        }
        _time(reserved_at, "reserved_at")
        ledger["attempts"].append(attempt)
        task["state"] = "submission_uncertain"
        execution_batch._append_event(ledger, "resource_bound_submission_attempt_reserved", {
            "attempt_id": attempt_id, "scientific_task_id": task_id,
            "policy_sha256": gate["policy_sha256"], "gate_sha256": gate["gate_sha256"],
            "scheduler_snapshot_sha256": gate["scheduler_snapshot"]["payload_sha256"],
            "reason": "resource policy and fresh gate consumed before any network",
        }, timestamp=reserved_at, important=True)
        ledger["revision"] += 1
        _seal(ledger, resource_changed=True)
        validate_ledger(ledger)
        execution_batch._atomic_write(path, ledger)
        return copy.deepcopy(attempt)


def reconcile_attempt(path: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply package-2 transition rules to a /3 ledger while preserving package-4 bindings."""
    with execution_batch._locked(path):
        ledger = validate_ledger(execution_batch.load_json(path))
        attempt_id = args[0] if args else kwargs.pop("attempt_id")
        state = kwargs["state"]
        attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == attempt_id), None)
        if attempt is None:
            raise ResourceError("unknown attempt_id")
        if state not in execution_batch.ATTEMPT_STATES:
            raise ResourceError(f"invalid attempt state {state}")
        evidence = execution_batch.validate_evidence(kwargs["reconciliation_evidence"], "reconciliation_evidence")
        reference = kwargs.get("scheduler_reference")
        if state == attempt["state"]:
            if attempt["scheduler_reference"] != reference or attempt["reconciliation_evidence"] != evidence:
                raise ResourceError("idempotent reconciliation differs from recorded evidence")
            return copy.deepcopy(attempt)
        if state not in execution_batch.TRANSITIONS[attempt["state"]]:
            raise ResourceError(f"invalid attempt transition {attempt['state']} -> {state}")
        observed_at = kwargs["observed_at"]
        _time(observed_at, "observed_at")
        if state in {"submitted", "queued", "running", "completed", "failed"}:
            _text(reference, "scheduler_reference")
        attempt.update({"state": state, "updated_at": observed_at, "scheduler_reference": reference, "reconciliation_evidence": evidence})
        task = next(item for item in ledger["tasks"] if item["scientific_task_id"] == attempt["scientific_task_id"])
        task["state"] = "reviewed" if state == "reconciled_not_submitted" else state
        execution_batch._append_event(ledger, "submission_attempt_reconciled", {
            "attempt_id": attempt_id, "state": state, "scheduler_reference": reference,
            "evidence_sha256": evidence["sha256"], "reason": _text(kwargs["reason"], "reason"),
        }, timestamp=observed_at, important=True)
        ledger["revision"] += 1
        _seal(ledger, resource_changed=True)
        validate_ledger(ledger)
        execution_batch._atomic_write(path, ledger)
        return copy.deepcopy(attempt)


def parse_accounting(text: str, *, job_id: str, attempt_id: str, input_sha256: str,
                     evidence_source: str, collected_at: str) -> dict[str, Any]:
    """Parse common PBS resources_used dialects; absent/ambiguous fields stay unknown."""
    _text(job_id, "job_id"); _text(attempt_id, "attempt_id"); _sha(input_sha256, "input_sha256")
    _text(evidence_source, "evidence_source"); _time(collected_at, "collected_at")
    fields: dict[str, str] = {}
    duplicate_fields: set[str] = set()
    for key, value in re.findall(r"(?im)^\s*resources_used\.([A-Za-z_]+)\s*=\s*(\S+)\s*$", text):
        normalized = key.lower()
        if normalized in fields:
            duplicate_fields.add(normalized)
        else:
            fields[normalized] = value

    def seconds(value: str | None) -> int | None:
        if value is None or re.fullmatch(r"\d+(?::\d+){0,2}", value) is None:
            return None
        parts = [int(item) for item in value.split(":")]
        if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2: return parts[0] * 60 + parts[1]
        return parts[0]

    def memory_mb(value: str | None) -> float | None:
        match = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)(kb|mb|gb|tb|b)?", value or "")
        if not match: return None
        number = float(match.group(1)); unit = (match.group(2) or "b").lower()
        return number * {"b": 1 / 1024**2, "kb": 1 / 1024, "mb": 1, "gb": 1024, "tb": 1024**2}[unit]

    cpu = seconds(fields.get("cput")); wall = seconds(fields.get("walltime"))
    parsed_job_ids = re.findall(r"(?im)^\s*Job Id:\s*([^\s]+)\s*$", text)
    parsed_job_id = parsed_job_ids[0] if len(parsed_job_ids) == 1 else None
    identity_known = parsed_job_id == job_id
    core_matches = re.findall(r"(?im)^\s*(?:Resource_List\.)?(?:ncpus|procs|ppn)\s*=\s*(\d+)\s*$", text)
    cores = int(core_matches[0]) if len(core_matches) == 1 else None
    ambiguous = bool(duplicate_fields or len(core_matches) > 1 or len(parsed_job_ids) > 1)
    actual = None if ambiguous or not identity_known else ((cpu / 3600.0) if cpu is not None else ((wall * cores / 3600.0) if wall is not None and cores is not None else None))
    raw_bytes = text.encode("utf-8")
    record = {
        "schema": ACCOUNTING_SCHEMA, "job_id": job_id, "parsed_job_id": parsed_job_id,
        "attempt_id": attempt_id,
        "input_sha256": input_sha256, "collected_at": collected_at,
        "source": evidence_source, "evidence_sha256": __import__("hashlib").sha256(raw_bytes).hexdigest(),
        "evidence_size": len(raw_bytes),
        "parser": {"schema": "gaussian-pbs-accounting-parser/1", "version": 1},
        "transport_classification": "success", "fields": {
            "cpu_seconds": cpu, "walltime_seconds": wall, "memory_mb": memory_mb(fields.get("mem")),
            "vmemory_mb": memory_mb(fields.get("vmem")), "cores": cores,
        }, "actual_core_hours": actual,
        "classification": (
            "unknown_ambiguous_duplicate" if ambiguous else
            "unknown_job_identity" if not identity_known else
            "known" if actual is not None else "unknown_missing_or_dialect"
        ),
        "payload_sha256": "",
    }
    record["payload_sha256"] = _payload(record)
    return validate_accounting(record)


def validate_accounting(record: dict[str, Any]) -> dict[str, Any]:
    _exact(record, {"schema", "job_id", "parsed_job_id", "attempt_id", "input_sha256", "collected_at", "source", "evidence_sha256", "evidence_size", "parser", "transport_classification", "fields", "actual_core_hours", "classification", "payload_sha256"}, "resource accounting")
    if record["schema"] != ACCOUNTING_SCHEMA: raise ResourceError("resource accounting schema mismatch")
    _text(record["job_id"], "job_id")
    if record["parsed_job_id"] is not None: _text(record["parsed_job_id"], "parsed_job_id")
    _text(record["attempt_id"], "attempt_id"); _sha(record["input_sha256"], "input_sha256")
    _time(record["collected_at"], "collected_at"); _text(record["source"], "source"); _sha(record["evidence_sha256"], "evidence_sha256")
    _number(record["evidence_size"], "evidence_size", integer=True)
    if record["parser"] != {"schema": "gaussian-pbs-accounting-parser/1", "version": 1}:
        raise ResourceError("resource accounting parser identity changed")
    if record["transport_classification"] != "success": raise ResourceError("accounting transport is unknown")
    fields = _exact(record["fields"], {"cpu_seconds", "walltime_seconds", "memory_mb", "vmemory_mb", "cores"}, "accounting fields")
    for key, value in fields.items():
        if value is not None: _number(value, f"fields.{key}", integer=key in {"cpu_seconds", "walltime_seconds", "cores"})
    if record["classification"] == "known":
        if record["parsed_job_id"] != record["job_id"]:
            raise ResourceError("known accounting lacks exact parsed PBS job identity")
        actual = float(_number(record["actual_core_hours"], "actual_core_hours"))
        expected = fields["cpu_seconds"] / 3600.0 if fields["cpu_seconds"] is not None else (
            fields["walltime_seconds"] * fields["cores"] / 3600.0
            if fields["walltime_seconds"] is not None and fields["cores"] is not None else None
        )
        if expected is None or not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12):
            raise ResourceError("actual core-hours differ from deterministic accounting fields")
    elif record["classification"] in {"unknown_missing_or_dialect", "unknown_ambiguous_duplicate", "unknown_job_identity"}:
        if record["actual_core_hours"] is not None: raise ResourceError("unknown accounting cannot claim actual core-hours")
    else: raise ResourceError("accounting classification is unsupported")
    if _sha(record["payload_sha256"], "accounting payload_sha256") != _payload(record):
        raise ResourceError("resource accounting payload hash mismatch")
    return record


def reconcile_accounting(path: Path, accounting: dict[str, Any], *, raw_evidence: bytes) -> dict[str, Any]:
    validate_accounting(accounting)
    if not isinstance(raw_evidence, bytes):
        raise ResourceError("accounting reconciliation requires immutable raw evidence bytes")
    replayed = parse_accounting(
        raw_evidence.decode("utf-8"), job_id=accounting["job_id"],
        attempt_id=accounting["attempt_id"], input_sha256=accounting["input_sha256"],
        evidence_source=accounting["source"], collected_at=accounting["collected_at"],
    )
    if replayed != accounting:
        raise ResourceError("accounting record differs from deterministic raw evidence replay")
    if accounting["classification"] != "known":
        raise ResourceError("unknown accounting cannot reconcile consumed core-hours")
    with execution_batch._locked(path):
        ledger = validate_ledger(execution_batch.load_json(path))
        attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == accounting["attempt_id"]), None)
        if attempt is None or attempt["scheduler_reference"] != accounting["job_id"] or attempt["input_sha256"] != accounting["input_sha256"]:
            raise ResourceError("accounting does not bind exact job/attempt/input")
        if attempt["state"] not in {"completed", "failed"}:
            raise ResourceError("resource accounting reconciliation requires a terminal attempt")
        if attempt["resource_accounting"] is not None:
            if attempt["resource_accounting"] != accounting: raise ResourceError("accounting was already reconciled differently")
            return copy.deepcopy(attempt)
        attempt["resource_accounting"] = copy.deepcopy(accounting)
        attempt["consumed_core_hours"] = accounting["actual_core_hours"]
        attempt["consumed_core_hours_evidence"] = {"source": accounting["source"], "sha256": accounting["evidence_sha256"]}
        execution_batch._append_event(ledger, "terminal_resource_accounting_reconciled", {
            "attempt_id": attempt["attempt_id"], "job_id": accounting["job_id"],
            "estimated_core_hours": attempt["estimated_core_hours"], "actual_core_hours": accounting["actual_core_hours"],
            "source": accounting["source"], "collected_at": accounting["collected_at"],
            "automatic_method_or_resource_change": False, "automatic_retry": False,
        }, timestamp=accounting["collected_at"], important=True)
        ledger["revision"] += 1; _seal(ledger, resource_changed=True); validate_ledger(ledger); execution_batch._atomic_write(path, ledger)
        return copy.deepcopy(attempt)


def validate_monitor_observation(observation: dict[str, Any]) -> dict[str, Any]:
    required = {"collected_at", "source", "freshness", "age_seconds", "transport_classification", "state", "interruption_proof", "evidence_sha256"}
    _exact(observation, required, "monitor observation")
    _time(observation["collected_at"], "collected_at"); _text(observation["source"], "source")
    if observation["freshness"] not in {"fresh", "stale", "unknown"}: raise ResourceError("invalid observation freshness")
    _number(observation["age_seconds"], "age_seconds"); _text(observation["transport_classification"], "transport_classification")
    if observation["transport_classification"] not in {"success", "timeout", "transport_error", "parse_failed"}:
        raise ResourceError("monitor transport classification is not closed")
    if observation["state"] not in {"unknown", "queued", "running", "stale", "completed", "failed", "interrupted"}:
        raise ResourceError("monitor state is not closed")
    if observation["transport_classification"] != "success" and (observation["freshness"] != "unknown" or observation["state"] != "unknown"):
        raise ResourceError("failed monitor transport requires unknown freshness and state")
    if observation["freshness"] == "stale" and observation["state"] != "unknown":
        raise ResourceError("stale monitor evidence cannot claim a state")
    if observation["freshness"] == "unknown" and observation["transport_classification"] == "success":
        raise ResourceError("successful monitor transport must classify freshness")
    if observation["state"] == "interrupted":
        proof = _exact(observation["interruption_proof"], {
            "stable_repeats", "scheduler_record_absent", "log_signature_stable", "normal_termination_absent",
            "termination_counts_known", "stable_duration_seconds", "log_age_seconds",
            "full_normal_termination_count", "full_error_termination_count",
        }, "interruption proof")
        if (
            _number(proof["stable_repeats"], "stable_repeats", integer=True) < 2
            or _number(proof["stable_duration_seconds"], "stable_duration_seconds") < 60
            or _number(proof["log_age_seconds"], "log_age_seconds") < 60
            or proof["full_normal_termination_count"] != 0 or proof["full_error_termination_count"] != 0
            or proof["scheduler_record_absent"] is not True or proof["log_signature_stable"] is not True
            or proof["normal_termination_absent"] is not True or proof["termination_counts_known"] is not True
        ):
            raise ResourceError("interrupted state requires repeated stable exact absence evidence")
    elif observation["interruption_proof"] is not None:
        raise ResourceError("interruption proof is only valid for interrupted evidence")
    _sha(observation["evidence_sha256"], "evidence_sha256")
    return observation


def record_monitor_observation(
    path: Path, *, attempt_id: str, project: str, job_id: str,
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Append evidence and safely reconcile exact fresh states, never scientific acceptance."""
    validate_monitor_observation(observation)
    with execution_batch._locked(path):
        ledger = validate_ledger(execution_batch.load_json(path))
        attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == attempt_id), None)
        if attempt is None:
            raise ResourceError("monitor observation attempt is absent from ledger")
        _text(project, "monitor project"); _text(job_id, "monitor job_id")
        monitor_binding = {
            "attempt_id": attempt_id, "project": project, "job_id": job_id,
            "input_sha256": attempt["input_sha256"],
            "observation_evidence_sha256": observation["evidence_sha256"],
        }
        binding_sha256 = execution_batch.digest_value(monitor_binding)
        classification = "append_only_unknown"
        observed_state = observation["state"]
        desired = "failed" if observed_state == "interrupted" else observed_state
        can_reconcile = (
            observation["transport_classification"] == "success"
            and observation["freshness"] == "fresh"
            and observed_state in {"queued", "running", "completed", "failed", "interrupted"}
        )
        if can_reconcile:
            if (
                attempt["state"] == "submission_uncertain"
                or attempt["scheduler_reference"] is None
                or attempt["scheduler_reference"] != job_id
                or attempt["project"] != project
            ):
                classification = "conflict_unknown"
            elif desired == attempt["state"]:
                classification = "same_state"
            elif desired not in execution_batch.TRANSITIONS[attempt["state"]]:
                classification = "conflict_unknown"
            else:
                attempt["state"] = desired
                attempt["updated_at"] = observation["collected_at"]
                attempt["scheduler_reference"] = job_id
                attempt["reconciliation_evidence"] = {
                    "source": observation["source"], "sha256": observation["evidence_sha256"],
                }
                task = next(item for item in ledger["tasks"] if item["scientific_task_id"] == attempt["scientific_task_id"])
                task["state"] = desired
                classification = "state_reconciled"
        execution_batch._append_event(ledger, "read_only_monitor_observation", {
            "attempt_id": attempt_id, **copy.deepcopy(observation),
            "project": project, "job_id": job_id,
            "input_sha256": attempt["input_sha256"],
            "monitor_binding_sha256": binding_sha256,
            "reconciliation_classification": classification,
            "scientific_conclusion_changed": False,
        }, timestamp=observation["collected_at"], important=observation["state"] in {"unknown", "failed", "completed", "interrupted"})
        if classification == "state_reconciled":
            execution_batch._append_event(ledger, "submission_attempt_reconciled", {
                "attempt_id": attempt_id, "state": desired, "scheduler_reference": job_id,
                "evidence_sha256": observation["evidence_sha256"],
                "reason": (
                    "repeated stable fresh exact interruption evidence mapped to failed execution state without scientific acceptance"
                    if observed_state == "interrupted" else
                    "fresh successful exact one-call monitor evidence reconciled scheduler state"
                ),
            }, timestamp=observation["collected_at"], important=True)
        ledger["revision"] += 1
        _seal(ledger, resource_changed=classification == "state_reconciled")
        validate_ledger(ledger); execution_batch._atomic_write(path, ledger)
        return copy.deepcopy(ledger["events"][-1])


def _reject_symlinked_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        if not current.exists() and not current.is_symlink():
            continue
        if current.is_symlink():
            raise ResourceError(f"immutable artifact path contains a symlink: {current}")
        if current != absolute and not current.is_dir():
            raise ResourceError(f"immutable artifact ancestor is not a directory: {current}")


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.absolute()
    _reject_symlinked_ancestors(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlinked_ancestors(path.parent)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_name = f".{path.name}.{secrets.token_hex(8)}.partial"
    descriptor: int | None = None
    directory: int | None = None
    try:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory = os.open(path.parent, directory_flags)
        leaf_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary_name, leaf_flags, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        except FileExistsError as exc:
            raise ResourceError(f"refusing to overwrite immutable artifact: {path}") from exc
        os.fsync(directory)
    finally:
        if descriptor is not None: os.close(descriptor)
        if directory is not None:
            try: os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError: pass
            os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    finalize = sub.add_parser("finalize-policy"); finalize.add_argument("draft"); finalize.add_argument("--output", required=True)
    migrate = sub.add_parser("migrate-ledger"); migrate.add_argument("ledger"); migrate.add_argument("--migrated-at", required=True); migrate.add_argument("--source", required=True)
    build_snapshot = sub.add_parser("build-scheduler-snapshot"); build_snapshot.add_argument("ledger"); build_snapshot.add_argument("batch_observation"); build_snapshot.add_argument("--snapshot-id", required=True); build_snapshot.add_argument("--max-age-seconds", type=int, required=True); build_snapshot.add_argument("--output", required=True)
    gate = sub.add_parser("evaluate-gate"); gate.add_argument("ledger"); gate.add_argument("--policy", required=True); gate.add_argument("--scheduler-snapshot", required=True); gate.add_argument("--gate-id", required=True); gate.add_argument("--evaluated-at", required=True); gate.add_argument("--scientific-task-id", required=True); gate.add_argument("--attempt-id", required=True); gate.add_argument("--project", required=True); gate.add_argument("--input-sha256", required=True); gate.add_argument("--resource-tier", required=True); gate.add_argument("--cores", type=int, required=True); gate.add_argument("--memory-gb", type=int, required=True); gate.add_argument("--walltime-seconds", type=int, required=True); gate.add_argument("--estimated-core-hours", type=float, required=True); gate.add_argument("--output", required=True)
    accounting = sub.add_parser("parse-accounting"); accounting.add_argument("input"); accounting.add_argument("--job-id", required=True); accounting.add_argument("--attempt-id", required=True); accounting.add_argument("--input-sha256", required=True); accounting.add_argument("--source", required=True); accounting.add_argument("--collected-at", required=True); accounting.add_argument("--output", required=True)
    reconcile = sub.add_parser("reconcile-accounting"); reconcile.add_argument("ledger"); reconcile.add_argument("accounting"); reconcile.add_argument("--raw-evidence", required=True)
    args = parser.parse_args(argv)
    if args.command == "finalize-policy": result = finalize_policy(load(Path(args.draft))); _write_new(Path(args.output), result)
    elif args.command == "migrate-ledger": result = migrate_v2_to_v3(Path(args.ledger), migrated_at=args.migrated_at, migration_source=args.source)
    elif args.command == "build-scheduler-snapshot": result = build_scheduler_snapshot(validate_ledger(load(Path(args.ledger))), load(Path(args.batch_observation)), snapshot_id=args.snapshot_id, max_age_seconds=args.max_age_seconds); _write_new(Path(args.output), result)
    elif args.command == "evaluate-gate":
        scheduler_document, scheduler_sha, scheduler_size = load_artifact(Path(args.scheduler_snapshot))
        result = evaluate_gate(validate_ledger(load(Path(args.ledger))), validate_policy(load(Path(args.policy))), validate_scheduler_snapshot(scheduler_document), gate_id=args.gate_id, evaluated_at=args.evaluated_at, scientific_task_id=args.scientific_task_id, attempt_id=args.attempt_id, project=args.project, input_sha256=args.input_sha256, resource_tier=args.resource_tier, cores=args.cores, memory_gb=args.memory_gb, walltime_seconds=args.walltime_seconds, estimated_core_hours=args.estimated_core_hours, scheduler_artifact_sha256=scheduler_sha, scheduler_artifact_size=scheduler_size); _write_new(Path(args.output), result)
    elif args.command == "parse-accounting":
        input_path = Path(args.input)
        if input_path.is_symlink() or not input_path.is_file(): raise ResourceError("accounting input must be a regular non-symlink file")
        result = parse_accounting(input_path.read_text(encoding="utf-8"), job_id=args.job_id, attempt_id=args.attempt_id, input_sha256=args.input_sha256, evidence_source=args.source, collected_at=args.collected_at); _write_new(Path(args.output), result)
    else:
        raw_path = Path(args.raw_evidence)
        if raw_path.is_symlink() or not raw_path.is_file(): raise ResourceError("raw accounting evidence must be a regular non-symlink file")
        result = reconcile_accounting(Path(args.ledger), validate_accounting(load(Path(args.accounting))), raw_evidence=raw_path.read_bytes())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except ResourceError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr); raise SystemExit(2)
