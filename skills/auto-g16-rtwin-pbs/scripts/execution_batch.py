#!/usr/bin/env python3
"""Offline, fail-closed governance for reviewed Gaussian execution batches."""

from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


BATCH_SCHEMA = "gaussian-execution-batch/1"
BATCH_V2_SCHEMA = "gaussian-execution-batch/2"
REVIEW_SCHEMA = "gaussian-execution-batch-review/1"
MAX_DISTINCT_TASKS = 10
DEFAULT_SUMMARY_CADENCE_MINUTES = 60
SHA256_FIELDS = (
    "structure_sha256",
    "chemical_hypothesis_sha256",
    "method_protocol_sha256",
    "calculation_objective_sha256",
    "relevant_input_sha256",
)
TASK_STATES = {
    "reviewed",
    "submission_uncertain",
    "submitted",
    "queued",
    "running",
    "completed",
    "failed",
}
ATTEMPT_STATES = {
    "submission_uncertain",
    "submitted",
    "queued",
    "running",
    "completed",
    "failed",
    "reconciled_not_submitted",
}
UNRESOLVED_ATTEMPT_STATES = {
    "submission_uncertain",
    "submitted",
    "queued",
    "running",
}
TRANSITIONS = {
    "submission_uncertain": ATTEMPT_STATES - {"submission_uncertain"},
    "submitted": {"queued", "running", "completed", "failed"},
    "queued": {"running", "completed", "failed"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
    "reconciled_not_submitted": set(),
}


class BatchError(ValueError):
    """Raised when a batch mutation would violate reviewed governance."""


def _reject_constant(value: str) -> None:
    raise BatchError(f"non-finite JSON number is not permitted: {value}")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BatchError(f"duplicate JSON key is not permitted: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise BatchError(f"refusing symlink JSON input: {path}")
    if not path.is_file():
        raise BatchError(f"JSON input is not a regular file: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BatchError("top-level JSON value must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    copy_value = copy.deepcopy(value)
    copy_value.pop(key, None)
    return copy_value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BatchError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BatchError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchError(f"{label} must be a non-empty string")
    return value


def _require_sha(value: Any, label: str) -> str:
    text = _require_string(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise BatchError(f"{label} must be a lowercase SHA-256")
    return text


def validate_identity(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict) or set(identity) != set(SHA256_FIELDS):
        raise BatchError("scientific identity must contain exactly the five governed SHA-256 fields")
    return {field: _require_sha(identity[field], field) for field in SHA256_FIELDS}


def scientific_task_id(identity: dict[str, str]) -> str:
    validated = validate_identity(identity)
    return "scientific-task-" + digest_value(validated)


def attempt_id_for(batch_id: str, idempotency_key: str) -> str:
    """Return the stable physical-attempt identity before any reservation write."""

    _require_string(batch_id, "batch_id")
    _require_string(idempotency_key, "idempotency_key")
    return "qsub-attempt-" + hashlib.sha256(
        f"{batch_id}\0{idempotency_key}".encode("utf-8")
    ).hexdigest()


def validate_evidence(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"source", "sha256"}:
        raise BatchError(f"{label} must contain exactly source and sha256")
    return {
        "source": _require_string(value["source"], f"{label}.source"),
        "sha256": _require_sha(value["sha256"], f"{label}.sha256"),
    }


def finalize_review(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["payload_sha256"] = digest_value(_without(result, "payload_sha256"))
    validate_review(result)
    return result


def validate_review(review: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "batch_id", "review_id", "reviewed_at", "reviewer",
        "max_distinct_scientific_tasks", "tasks", "governance", "payload_sha256",
    }
    if set(review) != required:
        raise BatchError(f"review fields differ: expected {sorted(required)}")
    if review["schema"] != REVIEW_SCHEMA:
        raise BatchError(f"review schema must be {REVIEW_SCHEMA}")
    _require_string(review["batch_id"], "batch_id")
    _require_string(review["review_id"], "review_id")
    _require_string(review["reviewer"], "reviewer")
    parse_time(review["reviewed_at"])
    if review["max_distinct_scientific_tasks"] != MAX_DISTINCT_TASKS:
        raise BatchError(f"reviewed batch cap must be exactly {MAX_DISTINCT_TASKS}")
    tasks = review["tasks"]
    if not isinstance(tasks, list) or len(tasks) > MAX_DISTINCT_TASKS:
        raise BatchError(f"review may contain at most {MAX_DISTINCT_TASKS} distinct tasks")
    seen: set[str] = set()
    for task in tasks:
        expected = {"scientific_task_id", "identity", "estimated_core_hours", "reason"}
        if not isinstance(task, dict) or set(task) != expected:
            raise BatchError("reviewed task has unknown or missing fields")
        identity = validate_identity(task["identity"])
        expected_id = scientific_task_id(identity)
        if task["scientific_task_id"] != expected_id:
            raise BatchError("scientific_task_id does not match the governed scientific identity")
        if expected_id in seen:
            raise BatchError("review contains duplicate scientific identity")
        seen.add(expected_id)
        _core_hours(task["estimated_core_hours"], "estimated_core_hours")
        _require_string(task["reason"], "task reason")
    governance = review["governance"]
    expected_governance = {
        "automatic_qsub": False,
        "automatic_retry": False,
        "automatic_scientific_change": False,
        "monitoring_is_read_only": True,
        "fresh_approval_required_per_attempt": True,
    }
    if governance != expected_governance:
        raise BatchError("review governance flags must preserve every fail-closed boundary")
    payload = _require_sha(review["payload_sha256"], "payload_sha256")
    if payload != digest_value(_without(review, "payload_sha256")):
        raise BatchError("review payload_sha256 mismatch")
    return review


def _core_hours(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BatchError(f"{label} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise BatchError(f"{label} must be a finite non-negative number")
    return number


def _event(event_type: str, timestamp: str, details: dict[str, Any], previous: str | None, *, important: bool) -> dict[str, Any]:
    event = {
        "sequence": 0,
        "event_type": event_type,
        "timestamp": timestamp,
        "important": important,
        "previous_event_sha256": previous,
        "details": copy.deepcopy(details),
    }
    event["event_sha256"] = digest_value(event)
    return event


def _append_event(ledger: dict[str, Any], event_type: str, details: dict[str, Any], *, timestamp: str, important: bool = False) -> None:
    parse_time(timestamp)
    previous = ledger["events"][-1]["event_sha256"] if ledger["events"] else None
    event = _event(event_type, timestamp, details, previous, important=important)
    event["sequence"] = len(ledger["events"]) + 1
    event["event_sha256"] = digest_value(_without(event, "event_sha256"))
    ledger["events"].append(event)


def _calculate_counters(ledger: dict[str, Any]) -> dict[str, Any]:
    assumed_physical = [
        attempt for attempt in ledger["attempts"]
        if attempt["state"] != "reconciled_not_submitted"
    ]
    return {
        "distinct_scientific_tasks": len(ledger["tasks"]),
        "physical_qsub_attempts": len(assumed_physical),
        "estimated_core_hours": round(sum(float(item["estimated_core_hours"]) for item in assumed_physical), 12),
        "consumed_core_hours": round(sum(float(item["consumed_core_hours"] or 0) for item in ledger["attempts"]), 12),
    }


def _seal(ledger: dict[str, Any]) -> dict[str, Any]:
    ledger["counters"] = _calculate_counters(ledger)
    ledger["ledger_sha256"] = digest_value(_without(ledger, "ledger_sha256"))
    return ledger


def validate_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "batch", "revision", "created_at", "tasks", "attempts", "events",
        "counters", "calculation_ready", "no_submission_authorization", "ledger_sha256",
    }
    if set(ledger) != required or ledger.get("schema") != BATCH_SCHEMA:
        raise BatchError(f"ledger must be a closed {BATCH_SCHEMA} object")
    if ledger["calculation_ready"] is not False or ledger["no_submission_authorization"] is not True:
        raise BatchError("execution-batch ledger must remain non-authorizing")
    batch = ledger["batch"]
    expected_batch = {"batch_id", "review_id", "review_sha256", "max_distinct_scientific_tasks"}
    if not isinstance(batch, dict) or set(batch) != expected_batch:
        raise BatchError("ledger batch identity is malformed")
    _require_string(batch["batch_id"], "batch.batch_id")
    _require_string(batch["review_id"], "batch.review_id")
    _require_sha(batch["review_sha256"], "batch.review_sha256")
    if batch["max_distinct_scientific_tasks"] != MAX_DISTINCT_TASKS:
        raise BatchError("ledger batch cap changed")
    if not isinstance(ledger["revision"], int) or ledger["revision"] < 0:
        raise BatchError("ledger revision must be a non-negative integer")
    parse_time(ledger["created_at"])
    if not isinstance(ledger["tasks"], list) or len(ledger["tasks"]) > MAX_DISTINCT_TASKS:
        raise BatchError("ledger task cap exceeded")
    task_ids: set[str] = set()
    for task in ledger["tasks"]:
        expected = {"scientific_task_id", "identity", "state", "admitted_at", "admitted_by", "admission_reason", "initial_estimated_core_hours"}
        if not isinstance(task, dict) or set(task) != expected:
            raise BatchError("ledger task has unknown or missing fields")
        identity = validate_identity(task["identity"])
        task_id = scientific_task_id(identity)
        if task["scientific_task_id"] != task_id or task_id in task_ids:
            raise BatchError("ledger task identity is duplicated or inconsistent")
        task_ids.add(task_id)
        if task["state"] not in TASK_STATES:
            raise BatchError("invalid task state")
        parse_time(task["admitted_at"])
        _require_string(task["admitted_by"], "admitted_by")
        _require_string(task["admission_reason"], "admission_reason")
        _core_hours(task["initial_estimated_core_hours"], "initial_estimated_core_hours")
    attempt_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    approval_hashes: set[str] = set()
    for attempt in ledger["attempts"]:
        expected = {
            "attempt_id", "scientific_task_id", "idempotency_key", "state", "input_sha256",
            "live_approval_sha256", "estimated_core_hours", "consumed_core_hours", "reserved_at",
            "updated_at", "scheduler_reference", "audit_reason",
        }
        if not isinstance(attempt, dict) or set(attempt) != expected:
            raise BatchError("attempt has unknown or missing fields")
        if attempt["attempt_id"] in attempt_ids or attempt["idempotency_key"] in idempotency_keys:
            raise BatchError("attempt or idempotency key is duplicated")
        attempt_ids.add(_require_string(attempt["attempt_id"], "attempt_id"))
        idempotency_keys.add(_require_string(attempt["idempotency_key"], "idempotency_key"))
        if attempt["scientific_task_id"] not in task_ids:
            raise BatchError("attempt refers to an unreviewed task")
        if attempt["state"] not in ATTEMPT_STATES:
            raise BatchError("invalid attempt state")
        _require_sha(attempt["input_sha256"], "attempt input_sha256")
        approval_hash = _require_sha(attempt["live_approval_sha256"], "live_approval_sha256")
        if approval_hash in approval_hashes:
            raise BatchError("fresh live approval hash must be unique per attempt")
        approval_hashes.add(approval_hash)
        estimate = _core_hours(attempt["estimated_core_hours"], "estimated_core_hours")
        if isinstance(attempt.get("resource_gate"), dict) and attempt["resource_gate"].get("status") == "passed" and estimate <= 0:
            raise BatchError("new resource-bound attempt estimated_core_hours must be positive")
        if attempt["consumed_core_hours"] is not None:
            _core_hours(attempt["consumed_core_hours"], "consumed_core_hours")
        parse_time(attempt["reserved_at"])
        parse_time(attempt["updated_at"])
        if attempt["scheduler_reference"] is not None:
            _require_string(attempt["scheduler_reference"], "scheduler_reference")
        _require_string(attempt["audit_reason"], "audit_reason")
    if not isinstance(ledger["events"], list):
        raise BatchError("events must be an array")
    previous: str | None = None
    for index, event in enumerate(ledger["events"], start=1):
        expected = {"sequence", "event_type", "timestamp", "important", "previous_event_sha256", "details", "event_sha256"}
        if not isinstance(event, dict) or set(event) != expected:
            raise BatchError("event has unknown or missing fields")
        if event["sequence"] != index or event["previous_event_sha256"] != previous:
            raise BatchError("event hash chain is discontinuous")
        if event["event_sha256"] != digest_value(_without(event, "event_sha256")):
            raise BatchError("event hash mismatch")
        previous = event["event_sha256"]
        parse_time(event["timestamp"])
    if ledger["counters"] != _calculate_counters(ledger):
        raise BatchError("ledger counters do not match append-only records")
    if ledger["ledger_sha256"] != digest_value(_without(ledger, "ledger_sha256")):
        raise BatchError("ledger_sha256 mismatch")
    return ledger


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BatchError(f"refusing to replace symlink ledger: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or lock_path.is_symlink():
        raise BatchError("ledger and lock paths must not be symlinks")
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def initialize(review_path: Path, ledger_path: Path, *, timestamp: str | None = None) -> dict[str, Any]:
    review = validate_review(load_json(review_path))
    created_at = timestamp or utc_now()
    with _locked(ledger_path):
        if ledger_path.exists():
            existing = validate_ledger(load_json(ledger_path))
            if existing["batch"]["review_sha256"] != review["payload_sha256"]:
                raise BatchError("existing ledger is bound to a different immutable review")
            return existing
        ledger: dict[str, Any] = {
            "schema": BATCH_SCHEMA,
            "batch": {
                "batch_id": review["batch_id"],
                "review_id": review["review_id"],
                "review_sha256": review["payload_sha256"],
                "max_distinct_scientific_tasks": MAX_DISTINCT_TASKS,
            },
            "revision": 0,
            "created_at": created_at,
            "tasks": [],
            "attempts": [],
            "events": [],
            "counters": {},
            "calculation_ready": False,
            "no_submission_authorization": True,
            "ledger_sha256": "",
        }
        for item in review["tasks"]:
            ledger["tasks"].append({
                "scientific_task_id": item["scientific_task_id"],
                "identity": copy.deepcopy(item["identity"]),
                "state": "reviewed",
                "admitted_at": review["reviewed_at"],
                "admitted_by": review["reviewer"],
                "admission_reason": item["reason"],
                "initial_estimated_core_hours": float(item["estimated_core_hours"]),
            })
            _append_event(
                ledger, "task_admitted",
                {"decision": "admitted", "reason": item["reason"], "scientific_task_id": item["scientific_task_id"]},
                timestamp=review["reviewed_at"], important=True,
            )
        _append_event(
            ledger, "batch_initialized",
            {"batch_id": review["batch_id"], "review_sha256": review["payload_sha256"], "reason": "immutable reviewed batch accepted"},
            timestamp=created_at, important=True,
        )
        _seal(ledger)
        validate_ledger(ledger)
        _atomic_write(ledger_path, ledger)
        return ledger


def _mutate(ledger_path: Path, callback: Any) -> Any:
    with _locked(ledger_path):
        ledger = validate_ledger(load_json(ledger_path))
        original_batch = copy.deepcopy(ledger["batch"])
        result = callback(ledger)
        if ledger["batch"] != original_batch:
            raise BatchError("immutable reviewed batch identity changed")
        ledger["revision"] += 1
        _seal(ledger)
        validate_ledger(ledger)
        _atomic_write(ledger_path, ledger)
        return result, ledger


def admit_task(
    ledger_path: Path,
    identity: dict[str, str],
    *,
    estimated_core_hours: float,
    reason: str,
    reviewer: str,
    reviewed_at: str,
    requested_task_id: str | None = None,
) -> dict[str, Any]:
    validated = validate_identity(identity)
    task_id = scientific_task_id(validated)
    estimate = _core_hours(estimated_core_hours, "estimated_core_hours")
    _require_string(reason, "admission reason")
    _require_string(reviewer, "reviewer")
    parse_time(reviewed_at)

    def change(ledger: dict[str, Any]) -> dict[str, Any]:
        if requested_task_id is not None and requested_task_id != task_id:
            decision = {"decision": "rejected", "reason": "requested task id does not match governed scientific identity", "scientific_task_id": task_id}
            _append_event(ledger, "task_rejected", decision, timestamp=reviewed_at, important=True)
            return decision
        existing = next((item for item in ledger["tasks"] if item["scientific_task_id"] == task_id), None)
        if existing is not None:
            decision = {"decision": "admitted", "reason": "existing scientific identity; no new task slot consumed", "scientific_task_id": task_id, "new_slot_consumed": False}
            _append_event(ledger, "task_admission_idempotent", decision, timestamp=reviewed_at)
            return decision
        if len(ledger["tasks"]) >= MAX_DISTINCT_TASKS:
            decision = {"decision": "deferred", "reason": "reviewed batch already contains 10 distinct scientific tasks", "scientific_task_id": task_id, "new_slot_consumed": False}
            _append_event(ledger, "task_deferred", decision, timestamp=reviewed_at, important=True)
            return decision
        task = {
            "scientific_task_id": task_id,
            "identity": validated,
            "state": "reviewed",
            "admitted_at": reviewed_at,
            "admitted_by": reviewer,
            "admission_reason": reason,
            "initial_estimated_core_hours": estimate,
        }
        ledger["tasks"].append(task)
        decision = {"decision": "admitted", "reason": reason, "scientific_task_id": task_id, "new_slot_consumed": True}
        _append_event(ledger, "task_admitted", decision, timestamp=reviewed_at, important=True)
        return decision

    return _mutate(ledger_path, change)[0]


def classify_retry(existing_identity: dict[str, str], proposed_identity: dict[str, str]) -> dict[str, Any]:
    current = validate_identity(existing_identity)
    proposed = validate_identity(proposed_identity)
    changed = [field for field in SHA256_FIELDS if current[field] != proposed[field]]
    if changed:
        return {
            "classification": "new_scientific_task",
            "changed_fields": changed,
            "scientific_task_id": scientific_task_id(proposed),
            "consumes_new_task_slot": True,
            "automatic_qsub_authorized": False,
            "reason": "scientific identity changed; a new reviewed task is required",
        }
    return {
        "classification": "exact_resubmission",
        "changed_fields": [],
        "scientific_task_id": scientific_task_id(current),
        "consumes_new_task_slot": False,
        "automatic_qsub_authorized": False,
        "reason": "scientific identity is unchanged; fresh exact input and live approval gates still apply",
    }


def reserve_attempt(
    ledger_path: Path,
    scientific_task_id_value: str,
    *,
    identity: dict[str, str],
    idempotency_key: str,
    input_sha256: str,
    live_approval_sha256: str,
    estimated_core_hours: float,
    reserved_at: str,
    audit_reason: str,
) -> dict[str, Any]:
    proposed_identity = validate_identity(identity)
    _require_string(idempotency_key, "idempotency_key")
    input_digest = _require_sha(input_sha256, "input_sha256")
    approval_digest = _require_sha(live_approval_sha256, "live_approval_sha256")
    estimate = _core_hours(estimated_core_hours, "estimated_core_hours")
    parse_time(reserved_at)
    _require_string(audit_reason, "audit_reason")

    def change(ledger: dict[str, Any]) -> dict[str, Any]:
        task = next((item for item in ledger["tasks"] if item["scientific_task_id"] == scientific_task_id_value), None)
        if task is None:
            raise BatchError("physical attempt requires an admitted scientific task")
        retry = classify_retry(task["identity"], proposed_identity)
        if retry["classification"] != "exact_resubmission":
            raise BatchError(
                "scientific identity changed in " + ", ".join(retry["changed_fields"])
                + "; admit a new scientific task before any attempt"
            )
        if input_digest != task["identity"]["relevant_input_sha256"]:
            raise BatchError("input hash differs from reviewed task identity; admit a new scientific task")
        same_key = next((item for item in ledger["attempts"] if item["idempotency_key"] == idempotency_key), None)
        if same_key is not None:
            expected = (scientific_task_id_value, input_digest, approval_digest, estimate)
            observed = (same_key["scientific_task_id"], same_key["input_sha256"], same_key["live_approval_sha256"], float(same_key["estimated_core_hours"]))
            if observed != expected:
                raise BatchError("idempotency key was already used for a different attempt request")
            return copy.deepcopy(same_key)
        if any(item["live_approval_sha256"] == approval_digest for item in ledger["attempts"]):
            raise BatchError("exact resubmission requires a fresh live approval record")
        if any(item["scientific_task_id"] == scientific_task_id_value and item["state"] in UNRESOLVED_ATTEMPT_STATES for item in ledger["attempts"]):
            raise BatchError("task already has an unresolved physical attempt; reconcile it before any resubmission")
        attempt_id = "qsub-attempt-" + hashlib.sha256(
            f"{ledger['batch']['batch_id']}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()
        attempt = {
            "attempt_id": attempt_id,
            "scientific_task_id": scientific_task_id_value,
            "idempotency_key": idempotency_key,
            "state": "submission_uncertain",
            "input_sha256": input_digest,
            "live_approval_sha256": approval_digest,
            "estimated_core_hours": estimate,
            "consumed_core_hours": None,
            "reserved_at": reserved_at,
            "updated_at": reserved_at,
            "scheduler_reference": None,
            "audit_reason": audit_reason,
        }
        ledger["attempts"].append(attempt)
        task["state"] = "submission_uncertain"
        _append_event(
            ledger, "submission_uncertain",
            {"attempt_id": attempt_id, "scientific_task_id": scientific_task_id_value, "reason": "attempt reserved before qsub and remains occupied until reconciliation"},
            timestamp=reserved_at, important=True,
        )
        return copy.deepcopy(attempt)

    return _mutate(ledger_path, change)[0]


def reconcile_attempt(
    ledger_path: Path,
    attempt_id: str,
    *,
    state: str,
    observed_at: str,
    reason: str,
    scheduler_reference: str | None = None,
    consumed_core_hours: float | None = None,
) -> dict[str, Any]:
    if state not in ATTEMPT_STATES:
        raise BatchError(f"invalid attempt reconciliation state: {state}")
    parse_time(observed_at)
    _require_string(reason, "reconciliation reason")
    consumed = None if consumed_core_hours is None else _core_hours(consumed_core_hours, "consumed_core_hours")
    if scheduler_reference is not None:
        _require_string(scheduler_reference, "scheduler_reference")

    def change(ledger: dict[str, Any]) -> dict[str, Any]:
        attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == attempt_id), None)
        if attempt is None:
            raise BatchError("unknown attempt_id")
        if state == attempt["state"]:
            return copy.deepcopy(attempt)
        if state not in TRANSITIONS[attempt["state"]]:
            raise BatchError(f"invalid attempt transition {attempt['state']} -> {state}")
        attempt["state"] = state
        attempt["updated_at"] = observed_at
        if scheduler_reference is not None:
            attempt["scheduler_reference"] = scheduler_reference
        if consumed is not None:
            attempt["consumed_core_hours"] = consumed
        task = next(item for item in ledger["tasks"] if item["scientific_task_id"] == attempt["scientific_task_id"])
        if state != "reconciled_not_submitted":
            task["state"] = state
        elif not any(item is not attempt and item["scientific_task_id"] == task["scientific_task_id"] and item["state"] in UNRESOLVED_ATTEMPT_STATES for item in ledger["attempts"]):
            task["state"] = "reviewed"
        _append_event(
            ledger, "attempt_state_changed",
            {"attempt_id": attempt_id, "scientific_task_id": attempt["scientific_task_id"], "state": state, "reason": reason},
            timestamp=observed_at, important=state in {"submitted", "queued", "running", "completed", "failed", "reconciled_not_submitted"},
        )
        return copy.deepcopy(attempt)

    return _mutate(ledger_path, change)[0]


def _calculate_v2_counters(ledger: dict[str, Any]) -> dict[str, Any]:
    assumed_physical = [
        attempt for attempt in ledger["attempts"]
        if attempt["state"] != "reconciled_not_submitted"
    ]
    return {
        "distinct_scientific_tasks": len(ledger["tasks"]),
        "physical_qsub_attempts": len(assumed_physical),
        "estimated_core_hours": round(
            sum(float(item["estimated_core_hours"]) for item in assumed_physical), 12
        ),
        "consumed_core_hours": round(
            sum(float(item["consumed_core_hours"] or 0) for item in ledger["attempts"]), 12
        ),
    }


def _seal_v2(ledger: dict[str, Any]) -> dict[str, Any]:
    ledger["counters"] = _calculate_v2_counters(ledger)
    ledger["ledger_sha256"] = digest_value(_without(ledger, "ledger_sha256"))
    return ledger


def validate_submission_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    """Validate the execution ledger required by every new live submit."""

    required = {
        "schema", "batch", "revision", "created_at", "tasks", "attempts", "events",
        "counters", "resource_policy_interface", "calculation_ready",
        "no_submission_authorization", "ledger_sha256",
    }
    if set(ledger) != required or ledger.get("schema") != BATCH_V2_SCHEMA:
        raise BatchError(f"protected submission requires a closed {BATCH_V2_SCHEMA} ledger")
    if ledger["calculation_ready"] is not False or ledger["no_submission_authorization"] is not True:
        raise BatchError("execution ledger must remain non-authorizing")
    batch = ledger["batch"]
    if not isinstance(batch, dict) or set(batch) != {
        "batch_id", "review_id", "review_sha256", "max_distinct_scientific_tasks"
    }:
        raise BatchError("submission ledger batch identity is malformed")
    _require_string(batch["batch_id"], "batch.batch_id")
    _require_string(batch["review_id"], "batch.review_id")
    _require_sha(batch["review_sha256"], "batch.review_sha256")
    if batch["max_distinct_scientific_tasks"] != MAX_DISTINCT_TASKS:
        raise BatchError("submission ledger batch cap changed")
    if not isinstance(ledger["revision"], int) or ledger["revision"] < 0:
        raise BatchError("submission ledger revision must be non-negative")
    parse_time(ledger["created_at"])
    interface = ledger["resource_policy_interface"]
    if interface != {
        "schema": "gaussian-execution-resource-policy-hook/1",
        "owner": "auto-g16-package-4",
        "status": "interface_reserved_not_enforced_by_package_2",
        "hard_budget_gate_implemented": False,
        "concurrency_resource_gate_implemented": False,
    }:
        raise BatchError("package-4 resource-policy interface changed")
    if not isinstance(ledger["tasks"], list) or len(ledger["tasks"]) > MAX_DISTINCT_TASKS:
        raise BatchError("submission ledger task cap exceeded")
    task_ids: set[str] = set()
    for task in ledger["tasks"]:
        if not isinstance(task, dict) or set(task) != {
            "scientific_task_id", "identity", "state", "admitted_at", "admitted_by",
            "admission_reason", "initial_estimated_core_hours",
            "initial_estimated_core_hours_evidence",
        }:
            raise BatchError("submission ledger task has unknown or missing fields")
        identity = validate_identity(task["identity"])
        task_id = scientific_task_id(identity)
        if task["scientific_task_id"] != task_id or task_id in task_ids:
            raise BatchError("submission ledger task identity is duplicated or inconsistent")
        task_ids.add(task_id)
        if task["state"] not in TASK_STATES:
            raise BatchError("invalid submission-ledger task state")
        parse_time(task["admitted_at"])
        _require_string(task["admitted_by"], "admitted_by")
        _require_string(task["admission_reason"], "admission_reason")
        _core_hours(task["initial_estimated_core_hours"], "initial_estimated_core_hours")
        validate_evidence(
            task["initial_estimated_core_hours_evidence"],
            "initial_estimated_core_hours_evidence",
        )
    attempt_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    approval_hashes: set[str] = set()
    approval_ids: set[str] = set()
    for attempt in ledger["attempts"]:
        if not isinstance(attempt, dict) or set(attempt) != {
            "attempt_id", "scientific_task_id", "idempotency_key", "state",
            "project", "job_name", "remote_workdir", "input_sha256",
            "live_approval_id", "live_approval_sha256", "estimated_core_hours",
            "estimated_core_hours_evidence", "consumed_core_hours",
            "consumed_core_hours_evidence", "reserved_at", "updated_at",
            "scheduler_reference", "reconciliation_evidence", "audit_reason",
            "resource_gate",
        }:
            raise BatchError("submission attempt has unknown or missing fields")
        attempt_id = _require_string(attempt["attempt_id"], "attempt_id")
        key = _require_string(attempt["idempotency_key"], "idempotency_key")
        if attempt_id in attempt_ids or key in idempotency_keys:
            raise BatchError("attempt or idempotency key is duplicated")
        attempt_ids.add(attempt_id)
        idempotency_keys.add(key)
        if attempt["scientific_task_id"] not in task_ids:
            raise BatchError("attempt refers to an unreviewed task")
        if attempt["state"] not in ATTEMPT_STATES:
            raise BatchError("invalid submission attempt state")
        project = _require_string(attempt["project"], "project")
        if attempt["job_name"] != project:
            raise BatchError("job_name must exactly equal the reviewed project")
        if attempt["remote_workdir"] != f"/home/user100/SDL/{project}":
            raise BatchError("attempt remote_workdir is outside the fixed server root")
        _require_sha(attempt["input_sha256"], "attempt input_sha256")
        approval_id = _require_string(attempt["live_approval_id"], "live_approval_id")
        approval_hash = _require_sha(attempt["live_approval_sha256"], "live_approval_sha256")
        if approval_id in approval_ids or approval_hash in approval_hashes:
            raise BatchError("one-time live approval ID/hash must be unique per attempt")
        approval_ids.add(approval_id)
        approval_hashes.add(approval_hash)
        _core_hours(attempt["estimated_core_hours"], "estimated_core_hours")
        validate_evidence(attempt["estimated_core_hours_evidence"], "estimated_core_hours_evidence")
        if attempt["consumed_core_hours"] is None:
            if attempt["consumed_core_hours_evidence"] is not None:
                raise BatchError("consumed evidence requires an observed consumed_core_hours value")
        else:
            _core_hours(attempt["consumed_core_hours"], "consumed_core_hours")
            validate_evidence(attempt["consumed_core_hours_evidence"], "consumed_core_hours_evidence")
        parse_time(attempt["reserved_at"])
        parse_time(attempt["updated_at"])
        scheduler_reference = attempt["scheduler_reference"]
        if attempt["state"] in {"submitted", "queued", "running", "completed", "failed"}:
            _require_string(scheduler_reference, "scheduler_reference")
        elif scheduler_reference is not None:
            _require_string(scheduler_reference, "scheduler_reference")
        if attempt["state"] == "submission_uncertain":
            if attempt["reconciliation_evidence"] is not None:
                validate_evidence(attempt["reconciliation_evidence"], "reconciliation_evidence")
        elif attempt["reconciliation_evidence"] is None:
            raise BatchError("resolved attempt requires hash-bound reconciliation evidence")
        else:
            validate_evidence(attempt["reconciliation_evidence"], "reconciliation_evidence")
        _require_string(attempt["audit_reason"], "audit_reason")
        if attempt["resource_gate"] != {
            "schema": "gaussian-execution-resource-gate/1",
            "owner": "auto-g16-package-4",
            "status": "not_evaluated_by_package_2",
        }:
            raise BatchError("attempt resource-gate interface changed")
    if not isinstance(ledger["events"], list):
        raise BatchError("events must be an array")
    previous: str | None = None
    for index, event in enumerate(ledger["events"], start=1):
        if not isinstance(event, dict) or set(event) != {
            "sequence", "event_type", "timestamp", "important",
            "previous_event_sha256", "details", "event_sha256",
        }:
            raise BatchError("submission-ledger event is malformed")
        if event["sequence"] != index or event["previous_event_sha256"] != previous:
            raise BatchError("submission-ledger event chain is discontinuous")
        if event["event_sha256"] != digest_value(_without(event, "event_sha256")):
            raise BatchError("submission-ledger event hash mismatch")
        previous = event["event_sha256"]
        parse_time(event["timestamp"])
    if ledger["counters"] != _calculate_v2_counters(ledger):
        raise BatchError("submission-ledger counters do not match records")
    if ledger["ledger_sha256"] != digest_value(_without(ledger, "ledger_sha256")):
        raise BatchError("submission-ledger hash mismatch")
    return ledger


def migrate_to_submission_ledger(
    ledger_path: Path,
    *,
    migrated_at: str,
    migration_source: str,
) -> dict[str, Any]:
    """Upgrade a valid /1 ledger to /2 without changing its scientific identity."""

    parse_time(migrated_at)
    source = _require_string(migration_source, "migration_source")
    with _locked(ledger_path):
        raw = load_json(ledger_path)
        if raw.get("schema") == BATCH_V2_SCHEMA:
            return validate_submission_ledger(raw)
        legacy = validate_ledger(raw)
        upgraded = copy.deepcopy(legacy)
        upgraded["schema"] = BATCH_V2_SCHEMA
        upgraded["resource_policy_interface"] = {
            "schema": "gaussian-execution-resource-policy-hook/1",
            "owner": "auto-g16-package-4",
            "status": "interface_reserved_not_enforced_by_package_2",
            "hard_budget_gate_implemented": False,
            "concurrency_resource_gate_implemented": False,
        }
        for task in upgraded["tasks"]:
            task["initial_estimated_core_hours_evidence"] = {
                "source": source,
                "sha256": digest_value({
                    "legacy_schema": BATCH_SCHEMA,
                    "scientific_task_id": task["scientific_task_id"],
                    "initial_estimated_core_hours": task["initial_estimated_core_hours"],
                }),
            }
        for attempt in upgraded["attempts"]:
            if attempt["state"] != "reconciled_not_submitted":
                raise BatchError(
                    "legacy ledger with a physical or uncertain attempt cannot be auto-migrated; "
                    "preserve it for historical replay and create a reviewed /2 batch"
                )
            attempt.update({
                "project": "legacy_unbound",
                "job_name": "legacy_unbound",
                "remote_workdir": "/home/user100/SDL/legacy_unbound",
                "live_approval_id": "legacy-" + attempt["attempt_id"],
                "estimated_core_hours_evidence": {
                    "source": source,
                    "sha256": digest_value({
                        "attempt_id": attempt["attempt_id"],
                        "estimated_core_hours": attempt["estimated_core_hours"],
                    }),
                },
                "consumed_core_hours_evidence": None,
                "reconciliation_evidence": {
                    "source": source,
                    "sha256": digest_value({
                        "attempt_id": attempt["attempt_id"],
                        "state": "reconciled_not_submitted",
                    }),
                },
                "resource_gate": {
                    "schema": "gaussian-execution-resource-gate/1",
                    "owner": "auto-g16-package-4",
                    "status": "not_evaluated_by_package_2",
                },
            })
        upgraded["revision"] += 1
        _append_event(
            upgraded,
            "ledger_migrated_to_v2",
            {"from_schema": BATCH_SCHEMA, "source": source},
            timestamp=migrated_at,
            important=True,
        )
        _seal_v2(upgraded)
        validate_submission_ledger(upgraded)
        _atomic_write(ledger_path, upgraded)
        return upgraded


def _mutate_v2(ledger_path: Path, callback: Any) -> Any:
    with _locked(ledger_path):
        ledger = validate_submission_ledger(load_json(ledger_path))
        original_batch = copy.deepcopy(ledger["batch"])
        result = callback(ledger)
        if ledger["batch"] != original_batch:
            raise BatchError("immutable reviewed batch identity changed")
        ledger["revision"] += 1
        _seal_v2(ledger)
        validate_submission_ledger(ledger)
        _atomic_write(ledger_path, ledger)
        return result, ledger


def reserve_submission_attempt(
    ledger_path: Path,
    scientific_task_id_value: str,
    *,
    identity: dict[str, str],
    idempotency_key: str,
    project: str,
    remote_workdir: str,
    input_sha256: str,
    live_approval_id: str,
    live_approval_sha256: str,
    estimated_core_hours: float,
    estimated_core_hours_evidence: dict[str, str],
    reserved_at: str,
    audit_reason: str,
) -> dict[str, Any]:
    proposed_identity = validate_identity(identity)
    key = _require_string(idempotency_key, "idempotency_key")
    project_value = _require_string(project, "project")
    if remote_workdir != f"/home/user100/SDL/{project_value}":
        raise BatchError("reservation remote_workdir must use the fixed server root")
    input_digest = _require_sha(input_sha256, "input_sha256")
    approval_id = _require_string(live_approval_id, "live_approval_id")
    approval_digest = _require_sha(live_approval_sha256, "live_approval_sha256")
    estimate = _core_hours(estimated_core_hours, "estimated_core_hours")
    estimate_evidence = validate_evidence(
        estimated_core_hours_evidence, "estimated_core_hours_evidence"
    )
    parse_time(reserved_at)
    _require_string(audit_reason, "audit_reason")

    def change(ledger: dict[str, Any]) -> dict[str, Any]:
        task = next(
            (item for item in ledger["tasks"] if item["scientific_task_id"] == scientific_task_id_value),
            None,
        )
        if task is None:
            raise BatchError("physical attempt requires an admitted scientific task")
        retry = classify_retry(task["identity"], proposed_identity)
        if retry["classification"] != "exact_resubmission":
            raise BatchError("scientific identity changed; admit a new scientific task")
        if input_digest != task["identity"]["relevant_input_sha256"]:
            raise BatchError("input hash differs from reviewed task identity")
        attempt_id = attempt_id_for(ledger["batch"]["batch_id"], key)
        same_key = next((item for item in ledger["attempts"] if item["idempotency_key"] == key), None)
        if same_key is not None:
            expected = {
                "attempt_id": attempt_id,
                "scientific_task_id": scientific_task_id_value,
                "project": project_value,
                "input_sha256": input_digest,
                "live_approval_id": approval_id,
                "live_approval_sha256": approval_digest,
                "estimated_core_hours": estimate,
                "estimated_core_hours_evidence": estimate_evidence,
            }
            if any(same_key[field] != value for field, value in expected.items()):
                raise BatchError("idempotency key was already used for a different attempt request")
            return copy.deepcopy(same_key)
        if any(
            item["live_approval_id"] == approval_id
            or item["live_approval_sha256"] == approval_digest
            for item in ledger["attempts"]
        ):
            raise BatchError("one-time live approval was already consumed")
        if any(
            item["scientific_task_id"] == scientific_task_id_value
            and item["state"] in UNRESOLVED_ATTEMPT_STATES
            for item in ledger["attempts"]
        ):
            raise BatchError("task already has an unresolved physical attempt")
        attempt = {
            "attempt_id": attempt_id,
            "scientific_task_id": scientific_task_id_value,
            "idempotency_key": key,
            "state": "submission_uncertain",
            "project": project_value,
            "job_name": project_value,
            "remote_workdir": remote_workdir,
            "input_sha256": input_digest,
            "live_approval_id": approval_id,
            "live_approval_sha256": approval_digest,
            "estimated_core_hours": estimate,
            "estimated_core_hours_evidence": estimate_evidence,
            "consumed_core_hours": None,
            "consumed_core_hours_evidence": None,
            "reserved_at": reserved_at,
            "updated_at": reserved_at,
            "scheduler_reference": None,
            "reconciliation_evidence": None,
            "audit_reason": audit_reason,
            "resource_gate": {
                "schema": "gaussian-execution-resource-gate/1",
                "owner": "auto-g16-package-4",
                "status": "not_evaluated_by_package_2",
            },
        }
        ledger["attempts"].append(attempt)
        task["state"] = "submission_uncertain"
        _append_event(
            ledger,
            "submission_attempt_reserved",
            {
                "attempt_id": attempt_id,
                "scientific_task_id": scientific_task_id_value,
                "project": project_value,
                "approval_id": approval_id,
                "reason": "reserved before any network or qsub action",
            },
            timestamp=reserved_at,
            important=True,
        )
        return copy.deepcopy(attempt)

    return _mutate_v2(ledger_path, change)[0]


def reconcile_submission_attempt(
    ledger_path: Path,
    attempt_id: str,
    *,
    state: str,
    observed_at: str,
    reason: str,
    reconciliation_evidence: dict[str, str],
    scheduler_reference: str | None = None,
    consumed_core_hours: float | None = None,
    consumed_core_hours_evidence: dict[str, str] | None = None,
) -> dict[str, Any]:
    if state not in ATTEMPT_STATES:
        raise BatchError(f"invalid attempt reconciliation state: {state}")
    parse_time(observed_at)
    _require_string(reason, "reconciliation reason")
    evidence = validate_evidence(reconciliation_evidence, "reconciliation_evidence")
    if state in {"submitted", "queued", "running", "completed", "failed"}:
        reference = _require_string(scheduler_reference, "scheduler_reference")
    else:
        reference = scheduler_reference
        if reference is not None:
            _require_string(reference, "scheduler_reference")
    consumed = None if consumed_core_hours is None else _core_hours(
        consumed_core_hours, "consumed_core_hours"
    )
    if consumed is None and consumed_core_hours_evidence is not None:
        raise BatchError("consumed evidence requires consumed_core_hours")
    consumed_evidence = None if consumed is None else validate_evidence(
        consumed_core_hours_evidence, "consumed_core_hours_evidence"
    )

    def change(ledger: dict[str, Any]) -> dict[str, Any]:
        attempt = next((item for item in ledger["attempts"] if item["attempt_id"] == attempt_id), None)
        if attempt is None:
            raise BatchError("unknown attempt_id")
        if state == attempt["state"]:
            if (
                attempt["scheduler_reference"] != reference
                or attempt["reconciliation_evidence"] != evidence
            ):
                raise BatchError("idempotent reconciliation differs from recorded evidence")
            return copy.deepcopy(attempt)
        if state not in TRANSITIONS[attempt["state"]]:
            raise BatchError(f"invalid attempt transition {attempt['state']} -> {state}")
        attempt["state"] = state
        attempt["updated_at"] = observed_at
        attempt["scheduler_reference"] = reference
        attempt["reconciliation_evidence"] = evidence
        if consumed is not None:
            attempt["consumed_core_hours"] = consumed
            attempt["consumed_core_hours_evidence"] = consumed_evidence
        task = next(
            item for item in ledger["tasks"]
            if item["scientific_task_id"] == attempt["scientific_task_id"]
        )
        if state == "reconciled_not_submitted":
            task["state"] = "reviewed"
        else:
            task["state"] = state
        _append_event(
            ledger,
            "submission_attempt_reconciled",
            {
                "attempt_id": attempt_id,
                "state": state,
                "scheduler_reference": reference,
                "evidence_sha256": evidence["sha256"],
                "reason": reason,
            },
            timestamp=observed_at,
            important=True,
        )
        return copy.deepcopy(attempt)

    return _mutate_v2(ledger_path, change)[0]


def record_error(ledger_path: Path, *, code: str, message: str, observed_at: str) -> dict[str, Any]:
    _require_string(code, "error code")
    _require_string(message, "error message")
    parse_time(observed_at)

    def change(ledger: dict[str, Any]) -> dict[str, Any]:
        details = {"code": code, "message": message}
        _append_event(ledger, "important_error", details, timestamp=observed_at, important=True)
        return details

    return _mutate(ledger_path, change)[0]


def monitoring_summary(
    ledger_path: Path,
    *,
    now: str,
    last_summary_at: str | None = None,
    cadence_minutes: int = DEFAULT_SUMMARY_CADENCE_MINUTES,
) -> dict[str, Any]:
    """Return a read-only operator view; never mutate or invoke live actions."""

    ledger = validate_ledger(load_json(ledger_path))
    current = parse_time(now)
    anchor_text = last_summary_at or ledger["created_at"]
    anchor = parse_time(anchor_text)
    if not isinstance(cadence_minutes, int) or cadence_minutes <= 0:
        raise BatchError("cadence_minutes must be a positive integer")
    due = (current - anchor).total_seconds() >= cadence_minutes * 60
    immediate = [
        copy.deepcopy(event) for event in ledger["events"]
        if event["important"] and parse_time(event["timestamp"]) > anchor
    ]
    status_counts: dict[str, int] = {}
    for task in ledger["tasks"]:
        status_counts[task["state"]] = status_counts.get(task["state"], 0) + 1
    return {
        "schema": "gaussian-execution-batch-monitor-summary/1",
        "batch_id": ledger["batch"]["batch_id"],
        "generated_at": now,
        "read_only": True,
        "live_actions": {
            "submit": False,
            "retry": False,
            "cancel": False,
            "edit_chemistry": False,
            "expand_search": False,
            "scheduler_zombie_cleanup_authority_changed": False,
        },
        "cadence_minutes": cadence_minutes,
        "cumulative_summary_due": due,
        "cumulative_summary": {
            "counters": copy.deepcopy(ledger["counters"]),
            "task_states": status_counts,
            "unresolved_attempts": sum(item["state"] in UNRESOLVED_ATTEMPT_STATES for item in ledger["attempts"]),
        } if due else None,
        "immediate_events": immediate,
    }


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate one offline execution-batch ledger")
    validate.add_argument("ledger")
    migrate = sub.add_parser(
        "migrate-v2",
        help="upgrade an attempt-free or definitively-negative /1 ledger to the v2 contract",
    )
    migrate.add_argument("ledger")
    migrate.add_argument("--migrated-at", required=True)
    migrate.add_argument("--migration-source", required=True)
    summary = sub.add_parser("summary", help="emit a read-only operator summary")
    summary.add_argument("ledger")
    summary.add_argument("--now", required=True)
    summary.add_argument("--last-summary-at")
    summary.add_argument("--cadence-minutes", type=int, default=DEFAULT_SUMMARY_CADENCE_MINUTES)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "validate":
        raw = load_json(Path(args.ledger))
        ledger = (
            validate_submission_ledger(raw)
            if raw.get("schema") == BATCH_V2_SCHEMA
            else validate_ledger(raw)
        )
        _print({"valid": True, "schema": ledger["schema"], "counters": ledger["counters"], "live_actions": False})
    elif args.command == "migrate-v2":
        ledger = migrate_to_submission_ledger(
            Path(args.ledger),
            migrated_at=args.migrated_at,
            migration_source=args.migration_source,
        )
        _print({
            "migrated": True,
            "schema": ledger["schema"],
            "ledger_sha256": ledger["ledger_sha256"],
            "live_actions": False,
        })
    elif args.command == "summary":
        _print(monitoring_summary(Path(args.ledger), now=args.now, last_summary_at=args.last_summary_at, cadence_minutes=args.cadence_minutes))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BatchError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(2)
