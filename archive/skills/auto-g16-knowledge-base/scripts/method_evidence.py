#!/usr/bin/env python3
"""Build immutable, permission-aware method-evidence briefs offline.

The tool only validates and summarizes supplied evidence artifacts.  It never
selects a method, estimates a success probability, creates an input, or grants
calculation/submission approval.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMAS = {
    "auto-g16-method-selection-context/1": "context",
    "auto-g16-method-benchmark-case/1": "benchmark",
    "auto-g16-method-run-observation/1": "run_observation",
    "auto-g16-method-evidence-brief/1": "brief",
}
EVIDENCE_SCHEMAS = {
    "auto-g16-method-benchmark-case/1",
    "auto-g16-method-run-observation/1",
}
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")
ACCESS_CLASSES = (
    "public",
    "group_internal",
    "project_restricted",
    "confidential_unpublished",
)
EXPORT_POLICIES = ("full", "metadata_redacted", "no_export")
COMMON_FIELDS = {
    "schema",
    "artifact_id",
    "revision_id",
    "created_at",
    "created_by",
    "review",
    "access",
    "provenance",
    "source_revision_refs",
    "supersedes",
    "exclusions",
    "calculation_ready",
    "no_submission_authorization",
    "no_method_selection_authorization",
    "no_approval_authorization",
    "payload_sha256",
}


class EvidenceError(ValueError):
    """An offline method-evidence artifact violated its contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def reject_constant(value: str) -> None:
    raise EvidenceError(f"non-standard JSON numeric constant is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"could not read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level JSON must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def payload_sha256(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value))
    except FileExistsError:
        raise EvidenceError(f"refusing to overwrite existing artifact: {path}") from None


def exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    return value


def nullable_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return text(value, label)


def identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} is invalid")
    return value


def sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be a lowercase SHA-256")
    return value


def timestamp(value: Any, label: str) -> str:
    item = text(value, label)
    try:
        parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{label} must be an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return item


def strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    require(all(isinstance(item, str) and item.strip() for item in value), f"{label} must contain non-empty strings")
    require(len(value) == len(set(value)), f"{label} must not contain duplicates")
    if nonempty:
        require(bool(value), f"{label} must not be empty")
    return value


def optional_number(value: Any, label: str) -> None:
    if value is None:
        return
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and value >= 0,
        f"{label} must be a non-negative finite number or null",
    )


def validate_record_ref(value: Any, label: str) -> dict[str, Any]:
    ref = exact(value, {"record_type", "record_id", "revision_id", "payload_sha256"}, label)
    require(ref["record_type"] in {"structure", "method", "source", "link", "reaction", "result", "calculation", "mechanism_hypothesis"}, f"{label}.record_type is unsupported")
    identifier(ref["record_id"], f"{label}.record_id")
    identifier(ref["revision_id"], f"{label}.revision_id")
    sha(ref["payload_sha256"], f"{label}.payload_sha256")
    return ref


def validate_artifact_ref(value: Any, label: str) -> dict[str, Any]:
    ref = exact(value, {"schema", "artifact_id", "revision_id", "payload_sha256"}, label)
    require(ref["schema"] in SCHEMAS, f"{label}.schema is unsupported")
    identifier(ref["artifact_id"], f"{label}.artifact_id")
    identifier(ref["revision_id"], f"{label}.revision_id")
    sha(ref["payload_sha256"], f"{label}.payload_sha256")
    return ref


def artifact_ref(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("schema", "artifact_id", "revision_id", "payload_sha256")}


def validate_review(value: Any, label: str) -> None:
    review = exact(value, {"status", "reviewer", "reviewed_at", "notes"}, label)
    require(review["status"] in {"draft", "reviewed", "reviewed_with_limits", "blocked"}, f"{label}.status is invalid")
    strings(review["notes"], f"{label}.notes")
    if review["status"] == "draft":
        require(review["reviewer"] is None and review["reviewed_at"] is None, f"{label}: draft cannot claim review")
    else:
        text(review["reviewer"], f"{label}.reviewer")
        timestamp(review["reviewed_at"], f"{label}.reviewed_at")


def validate_access(value: Any, label: str) -> dict[str, Any]:
    access = exact(value, {"class", "owner_project", "permitted_principals", "export_policy"}, label)
    require(access["class"] in ACCESS_CLASSES, f"{label}.class is invalid")
    nullable_text(access["owner_project"], f"{label}.owner_project")
    strings(access["permitted_principals"], f"{label}.permitted_principals")
    require(access["export_policy"] in EXPORT_POLICIES, f"{label}.export_policy is invalid")
    if access["class"] == "project_restricted":
        require(access["owner_project"] is not None, f"{label}: project_restricted requires owner_project")
    if access["class"] == "confidential_unpublished":
        require(bool(access["permitted_principals"]), f"{label}: confidential access requires permitted principals")
        require(access["export_policy"] != "full", f"{label}: confidential access cannot permit full export")
    return access


def validate_provenance(value: Any, label: str) -> None:
    item = exact(value, {"source_kind", "importer", "source_artifacts"}, label)
    require(item["source_kind"] in {"manual_review", "imported", "reviewed_artifact", "study_result"}, f"{label}.source_kind is invalid")
    nullable_text(item["importer"], f"{label}.importer")
    require(isinstance(item["source_artifacts"], list), f"{label}.source_artifacts must be an array")
    for index, binding in enumerate(item["source_artifacts"]):
        exact(binding, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, f"{label}.source_artifacts[{index}]")
        text(binding["path"], f"{label}.source_artifacts[{index}].path")
        sha(binding["sha256"], f"{label}.source_artifacts[{index}].sha256")
        require(isinstance(binding["size_bytes"], int) and binding["size_bytes"] >= 0, f"{label}.source_artifacts[{index}].size_bytes is invalid")
        text(binding["schema"], f"{label}.source_artifacts[{index}].schema")
        sha(binding["payload_sha256"], f"{label}.source_artifacts[{index}].payload_sha256")


def validate_context_profile(value: Any, label: str, *, reviewed: bool) -> dict[str, Any]:
    profile = exact(
        value,
        {
            "calculation_family", "elements", "ecp_elements", "charge", "multiplicity",
            "electronic_state_constraints", "reference_constraints", "phase", "solvent",
            "target_properties", "resource_constraints",
        },
        label,
    )
    text(profile["calculation_family"], f"{label}.calculation_family")
    elements = strings(profile["elements"], f"{label}.elements", nonempty=True)
    require(all(ELEMENT_RE.fullmatch(item) for item in elements), f"{label}.elements contains an invalid symbol")
    ecp = strings(profile["ecp_elements"], f"{label}.ecp_elements")
    require(set(ecp) <= set(elements), f"{label}.ecp_elements must be a subset of elements")
    if reviewed:
        require(isinstance(profile["charge"], int) and not isinstance(profile["charge"], bool), f"{label}.charge must be an integer")
        require(isinstance(profile["multiplicity"], int) and not isinstance(profile["multiplicity"], bool) and profile["multiplicity"] >= 1, f"{label}.multiplicity must be positive")
    else:
        require(profile["charge"] is None or isinstance(profile["charge"], int) and not isinstance(profile["charge"], bool), f"{label}.charge is invalid")
        require(profile["multiplicity"] is None or isinstance(profile["multiplicity"], int) and not isinstance(profile["multiplicity"], bool) and profile["multiplicity"] >= 1, f"{label}.multiplicity is invalid")
    strings(profile["electronic_state_constraints"], f"{label}.electronic_state_constraints")
    strings(profile["reference_constraints"], f"{label}.reference_constraints")
    require(profile["phase"] in {"gas", "solution", "solid", "interface", "unknown"}, f"{label}.phase is invalid")
    solvent = exact(profile["solvent"], {"status", "identity", "model_constraints"}, f"{label}.solvent")
    require(solvent["status"] in {"specified", "not_applicable", "unknown"}, f"{label}.solvent.status is invalid")
    nullable_text(solvent["identity"], f"{label}.solvent.identity")
    strings(solvent["model_constraints"], f"{label}.solvent.model_constraints")
    if solvent["status"] == "specified":
        require(solvent["identity"] is not None, f"{label}.solvent specified requires identity")
    strings(profile["target_properties"], f"{label}.target_properties", nonempty=True)
    resources = exact(profile["resource_constraints"], {"max_cores", "max_memory_gb", "max_walltime_hours", "notes"}, f"{label}.resource_constraints")
    for field in ("max_cores", "max_memory_gb", "max_walltime_hours"):
        optional_number(resources[field], f"{label}.resource_constraints.{field}")
    if resources["max_cores"] is not None:
        require(isinstance(resources["max_cores"], int) and not isinstance(resources["max_cores"], bool), f"{label}.resource_constraints.max_cores must be an integer")
    strings(resources["notes"], f"{label}.resource_constraints.notes")
    return profile


def validate_resource_observation(value: Any, label: str) -> None:
    item = exact(value, {"status", "walltime_hours", "core_hours", "peak_memory_gb", "resource_tier", "notes"}, label)
    require(item["status"] in {"observed", "reported", "estimated", "unknown"}, f"{label}.status is invalid")
    for field in ("walltime_hours", "core_hours", "peak_memory_gb"):
        optional_number(item[field], f"{label}.{field}")
    nullable_text(item["resource_tier"], f"{label}.resource_tier")
    strings(item["notes"], f"{label}.notes")
    if item["status"] == "unknown":
        require(all(item[field] is None for field in ("walltime_hours", "core_hours", "peak_memory_gb", "resource_tier")), f"{label}: unknown cannot contain fabricated measurements")


def validate_common(value: dict[str, Any], domain_fields: set[str]) -> None:
    exact(value, COMMON_FIELDS | domain_fields, "artifact")
    require(value["schema"] in SCHEMAS, "artifact.schema is unsupported")
    identifier(value["artifact_id"], "artifact.artifact_id")
    identifier(value["revision_id"], "artifact.revision_id")
    timestamp(value["created_at"], "artifact.created_at")
    text(value["created_by"], "artifact.created_by")
    validate_review(value["review"], "artifact.review")
    validate_access(value["access"], "artifact.access")
    validate_provenance(value["provenance"], "artifact.provenance")
    require(isinstance(value["source_revision_refs"], list) and value["source_revision_refs"], "artifact.source_revision_refs must not be empty")
    for index, ref in enumerate(value["source_revision_refs"]):
        validate_record_ref(ref, f"artifact.source_revision_refs[{index}]")
    require(isinstance(value["supersedes"], list), "artifact.supersedes must be an array")
    for index, ref in enumerate(value["supersedes"]):
        validate_artifact_ref(ref, f"artifact.supersedes[{index}]")
    strings(value["exclusions"], "artifact.exclusions")
    require(value["calculation_ready"] is False, "artifact.calculation_ready must be false")
    require(value["no_submission_authorization"] is True, "artifact.no_submission_authorization must be true")
    require(value["no_method_selection_authorization"] is True, "artifact.no_method_selection_authorization must be true")
    require(value["no_approval_authorization"] is True, "artifact.no_approval_authorization must be true")
    sha(value["payload_sha256"], "artifact.payload_sha256")
    require(value["payload_sha256"] == payload_sha256(value), "artifact payload SHA-256 mismatch")


def validate_context(value: dict[str, Any]) -> None:
    validate_common(value, {"context_profile", "reviewed_calculation_refs", "question"})
    require(value["schema"] == "auto-g16-method-selection-context/1", "context schema mismatch")
    validate_context_profile(value["context_profile"], "artifact.context_profile", reviewed=True)
    text(value["question"], "artifact.question")
    require(isinstance(value["reviewed_calculation_refs"], list), "artifact.reviewed_calculation_refs must be an array")
    for index, ref in enumerate(value["reviewed_calculation_refs"]):
        validate_record_ref(ref, f"artifact.reviewed_calculation_refs[{index}]")
    require(value["review"]["status"] in {"reviewed", "reviewed_with_limits"}, "selection context must be reviewed")


def validate_method_ref(value: Any, label: str) -> dict[str, Any]:
    ref = validate_record_ref(value, label)
    require(ref["record_type"] == "method", f"{label} must reference a method record")
    return ref


def validate_status_notes(value: Any, label: str, statuses: set[str], *, attempts: bool = False) -> None:
    fields = {"status", "notes"} | ({"attempt_count"} if attempts else set())
    item = exact(value, fields, label)
    require(item["status"] in statuses, f"{label}.status is invalid")
    strings(item["notes"], f"{label}.notes")
    if attempts:
        require(isinstance(item["attempt_count"], int) and not isinstance(item["attempt_count"], bool) and item["attempt_count"] >= 0, f"{label}.attempt_count is invalid")


def validate_benchmark(value: dict[str, Any]) -> None:
    fields = {
        "context_profile", "method_record_ref", "source_anchor_refs", "benchmark_quality",
        "technical_feasibility", "convergence_history", "cost_observation", "observed_outcomes",
    }
    validate_common(value, fields)
    require(value["schema"] == "auto-g16-method-benchmark-case/1", "benchmark schema mismatch")
    validate_context_profile(value["context_profile"], "artifact.context_profile", reviewed=False)
    validate_method_ref(value["method_record_ref"], "artifact.method_record_ref")
    require(isinstance(value["source_anchor_refs"], list), "artifact.source_anchor_refs must be an array")
    for index, ref in enumerate(value["source_anchor_refs"]):
        anchor = exact(ref, {"source_record", "anchor_id"}, f"artifact.source_anchor_refs[{index}]")
        require(validate_record_ref(anchor["source_record"], f"artifact.source_anchor_refs[{index}].source_record")["record_type"] == "source", "source anchor must reference a source")
        identifier(anchor["anchor_id"], f"artifact.source_anchor_refs[{index}].anchor_id")
    quality = exact(value["benchmark_quality"], {"status", "comparison_scope", "reference_data_quality", "notes"}, "artifact.benchmark_quality")
    require(quality["status"] in {"strong", "moderate", "weak", "unknown"}, "artifact.benchmark_quality.status is invalid")
    nullable_text(quality["comparison_scope"], "artifact.benchmark_quality.comparison_scope")
    nullable_text(quality["reference_data_quality"], "artifact.benchmark_quality.reference_data_quality")
    strings(quality["notes"], "artifact.benchmark_quality.notes")
    if quality["status"] == "unknown":
        require(quality["comparison_scope"] is None and quality["reference_data_quality"] is None, "unknown benchmark quality cannot claim comparison data")
    validate_status_notes(value["technical_feasibility"], "artifact.technical_feasibility", {"demonstrated", "mixed", "failed", "unknown"})
    validate_status_notes(value["convergence_history"], "artifact.convergence_history", {"consistent", "mixed", "failed", "unknown"}, attempts=True)
    validate_resource_observation(value["cost_observation"], "artifact.cost_observation")
    strings(value["observed_outcomes"], "artifact.observed_outcomes")


def validate_run_observation(value: dict[str, Any]) -> None:
    fields = {
        "context_profile", "method_record_ref", "result_record_refs", "observation_status",
        "technical_feasibility", "convergence_history", "cost_observation", "observed_outcomes",
    }
    validate_common(value, fields)
    require(value["schema"] == "auto-g16-method-run-observation/1", "run-observation schema mismatch")
    validate_context_profile(value["context_profile"], "artifact.context_profile", reviewed=False)
    validate_method_ref(value["method_record_ref"], "artifact.method_record_ref")
    require(isinstance(value["result_record_refs"], list), "artifact.result_record_refs must be an array")
    for index, ref in enumerate(value["result_record_refs"]):
        require(validate_record_ref(ref, f"artifact.result_record_refs[{index}]")["record_type"] in {"result", "calculation"}, "result_record_refs must reference result or calculation records")
    require(value["observation_status"] in {"completed", "failed", "incomplete", "unknown"}, "artifact.observation_status is invalid")
    validate_status_notes(value["technical_feasibility"], "artifact.technical_feasibility", {"demonstrated", "mixed", "failed", "unknown"})
    validate_status_notes(value["convergence_history"], "artifact.convergence_history", {"consistent", "mixed", "failed", "unknown"}, attempts=True)
    validate_resource_observation(value["cost_observation"], "artifact.cost_observation")
    strings(value["observed_outcomes"], "artifact.observed_outcomes")


DIMENSION_STATUSES = {
    "chemical_directness": {"direct", "near", "indirect", "mixed", "unknown"},
    "benchmark_quality": {"strong", "moderate", "weak", "mixed", "unknown"},
    "technical_feasibility": {"demonstrated", "mixed", "failed", "unknown"},
    "convergence_history": {"consistent", "mixed", "failed", "unknown"},
    "cost": {"observed", "partial", "unknown"},
}


def validate_dimension(value: Any, label: str, name: str) -> None:
    item = exact(value, {"status", "evidence_refs", "notes", "observations"}, label)
    require(item["status"] in DIMENSION_STATUSES[name], f"{label}.status is invalid")
    require(isinstance(item["evidence_refs"], list), f"{label}.evidence_refs must be an array")
    for index, ref in enumerate(item["evidence_refs"]):
        validate_artifact_ref(ref, f"{label}.evidence_refs[{index}]")
    strings(item["notes"], f"{label}.notes")
    strings(item["observations"], f"{label}.observations")


def validate_brief(value: dict[str, Any]) -> None:
    fields = {
        "context_ref", "included_evidence_refs", "excluded_evidence", "candidate_evidence",
        "query_summary", "evidence_status", "status_rationale", "method_selection", "approval",
    }
    validate_common(value, fields)
    require(value["schema"] == "auto-g16-method-evidence-brief/1", "brief schema mismatch")
    context = validate_artifact_ref(value["context_ref"], "artifact.context_ref")
    require(context["schema"] == "auto-g16-method-selection-context/1", "brief context_ref must reference a selection context")
    require(isinstance(value["included_evidence_refs"], list), "artifact.included_evidence_refs must be an array")
    for index, ref in enumerate(value["included_evidence_refs"]):
        require(validate_artifact_ref(ref, f"artifact.included_evidence_refs[{index}]")["schema"] in EVIDENCE_SCHEMAS, "included evidence ref has wrong schema")
    require(isinstance(value["excluded_evidence"], list), "artifact.excluded_evidence must be an array")
    for index, excluded in enumerate(value["excluded_evidence"]):
        item = exact(excluded, {"evidence_ref", "reasons"}, f"artifact.excluded_evidence[{index}]")
        validate_artifact_ref(item["evidence_ref"], f"artifact.excluded_evidence[{index}].evidence_ref")
        strings(item["reasons"], f"artifact.excluded_evidence[{index}].reasons", nonempty=True)
    require(isinstance(value["candidate_evidence"], list), "artifact.candidate_evidence must be an array")
    for index, candidate in enumerate(value["candidate_evidence"]):
        item = exact(candidate, {"method_record_ref", *DIMENSION_STATUSES}, f"artifact.candidate_evidence[{index}]")
        validate_method_ref(item["method_record_ref"], f"artifact.candidate_evidence[{index}].method_record_ref")
        for name in DIMENSION_STATUSES:
            validate_dimension(item[name], f"artifact.candidate_evidence[{index}].{name}", name)
    summary = exact(value["query_summary"], {"supplied", "included", "excluded_permission", "excluded_context"}, "artifact.query_summary")
    require(all(isinstance(summary[key], int) and summary[key] >= 0 for key in summary), "artifact.query_summary counts must be non-negative integers")
    require(summary["supplied"] == summary["included"] + summary["excluded_permission"] + summary["excluded_context"], "artifact.query_summary counts do not reconcile")
    require(value["evidence_status"] in {"reviewable", "insufficient", "unknown"}, "artifact.evidence_status is invalid")
    text(value["status_rationale"], "artifact.status_rationale")
    require(value["method_selection"] == {"status": "not_performed", "selected_method_record_ref": None}, "brief must not select a method")
    require(value["approval"] == {"status": "not_granted", "approved_protocol_ref": None}, "brief must not grant approval")
    if not value["included_evidence_refs"]:
        require(value["evidence_status"] in {"insufficient", "unknown"}, "empty evidence cannot be reviewable")
    dimension_values = [
        candidate[name]["status"]
        for candidate in value["candidate_evidence"]
        for name in DIMENSION_STATUSES
    ]
    if not dimension_values or "unknown" in dimension_values:
        require(value["evidence_status"] in {"insufficient", "unknown"}, "unknown evidence dimensions cannot be reviewable")


VALIDATORS = {
    "auto-g16-method-selection-context/1": validate_context,
    "auto-g16-method-benchmark-case/1": validate_benchmark,
    "auto-g16-method-run-observation/1": validate_run_observation,
    "auto-g16-method-evidence-brief/1": validate_brief,
}


def validate_artifact(value: dict[str, Any]) -> None:
    schema = value.get("schema")
    require(schema in VALIDATORS, f"unsupported schema: {schema!r}")
    VALIDATORS[schema](value)


def finalize_artifact(value: dict[str, Any]) -> dict[str, Any]:
    require(value.get("payload_sha256") is None, "finalize requires null payload_sha256")
    result = copy.deepcopy(value)
    result["payload_sha256"] = payload_sha256(result)
    validate_artifact(result)
    return result


def load_principal(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = load_json(path)
    exact(value, {"schema", "principal_id", "group_member", "projects", "confidential_record_ids"}, "principal")
    require(value["schema"] == "auto-g16-knowledge-principal/1", "principal schema is invalid")
    text(value["principal_id"], "principal.principal_id")
    require(type(value["group_member"]) is bool, "principal.group_member must be boolean")
    strings(value["projects"], "principal.projects")
    strings(value["confidential_record_ids"], "principal.confidential_record_ids")
    return value


def access_allowed(artifact: dict[str, Any], principal: dict[str, Any] | None) -> bool:
    access = artifact["access"]
    if access["class"] == "public":
        return True
    if principal is None:
        return False
    principal_id = principal["principal_id"]
    permitted = set(access["permitted_principals"])
    if access["class"] == "group_internal":
        return principal["group_member"] is True
    if access["class"] == "project_restricted":
        return principal_id in permitted or principal["group_member"] is True and access["owner_project"] in principal["projects"]
    return principal_id in permitted and artifact["artifact_id"] in principal["confidential_record_ids"]


def relevance(context: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str, list[str]]:
    target = context["context_profile"]
    observed = evidence["context_profile"]
    reasons: list[str] = []
    if observed["calculation_family"] not in {target["calculation_family"], "any"}:
        reasons.append("calculation_family_mismatch")
    if not set(target["target_properties"]) & set(observed["target_properties"]):
        reasons.append("target_property_mismatch")
    if reasons:
        return False, "unknown", reasons

    exact_fields = 0
    compared_fields = 0
    for field in ("charge", "multiplicity", "phase"):
        if observed[field] is not None and observed[field] != "unknown":
            compared_fields += 1
            exact_fields += observed[field] == target[field]
    compared_fields += 1
    exact_fields += set(observed["elements"]) == set(target["elements"])
    compared_fields += 1
    exact_fields += set(observed["ecp_elements"]) == set(target["ecp_elements"])
    compared_fields += 1
    exact_fields += set(observed["reference_constraints"]) == set(target["reference_constraints"])
    compared_fields += 1
    exact_fields += set(observed["electronic_state_constraints"]) == set(target["electronic_state_constraints"])
    target_solvent = target["solvent"]
    observed_solvent = observed["solvent"]
    if observed_solvent["status"] != "unknown":
        compared_fields += 1
        exact_fields += observed_solvent["status"] == target_solvent["status"] and observed_solvent["identity"] == target_solvent["identity"]
    if compared_fields and exact_fields == compared_fields:
        return True, "direct", []
    if exact_fields >= max(2, compared_fields - 2):
        return True, "near", []
    return True, "indirect", []


def summarize_status(items: list[str], order: list[str], unknown: str = "unknown") -> str:
    known = [item for item in items if item != unknown]
    if not known:
        return unknown
    if len(set(known)) > 1:
        return "mixed" if "mixed" in order else known[0]
    return known[0]


def make_dimension(status: str, evidence: list[dict[str, Any]], notes: list[str], observations: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "evidence_refs": [artifact_ref(item) for item in evidence],
        "notes": sorted(set(notes)),
        "observations": sorted(set(observations or [])),
    }


def candidate_summary(method_ref: dict[str, Any], entries: list[tuple[dict[str, Any], str]]) -> dict[str, Any]:
    evidence = [item for item, _ in entries]
    directness_values = [directness for _, directness in entries]
    known_directness = set(directness_values) - {"unknown"}
    directness = next(iter(known_directness)) if len(known_directness) == 1 else "mixed" if known_directness else "unknown"
    benchmarks = [item for item in evidence if item["schema"] == "auto-g16-method-benchmark-case/1"]
    quality_values = [item["benchmark_quality"]["status"] for item in benchmarks]
    known_quality = set(quality_values) - {"unknown"}
    quality = next(iter(known_quality)) if len(known_quality) == 1 else "mixed" if known_quality else "unknown"
    technical_values = [item["technical_feasibility"]["status"] for item in evidence]
    technical = summarize_status(technical_values, ["demonstrated", "mixed", "failed", "unknown"])
    convergence_values = [item["convergence_history"]["status"] for item in evidence]
    convergence = summarize_status(convergence_values, ["consistent", "mixed", "failed", "unknown"])
    cost_known = [item for item in evidence if item["cost_observation"]["status"] != "unknown"]
    cost_status = "observed" if cost_known and all(item["cost_observation"]["status"] in {"observed", "reported"} for item in cost_known) else "partial" if cost_known else "unknown"
    cost_observations = []
    for item in cost_known:
        cost = item["cost_observation"]
        for field in ("walltime_hours", "core_hours", "peak_memory_gb", "resource_tier"):
            if cost[field] is not None:
                cost_observations.append(f"{field}={cost[field]}")
    return {
        "method_record_ref": method_ref,
        "chemical_directness": make_dimension(directness, evidence, ["Context comparison is field-by-field; no composite score is used."]),
        "benchmark_quality": make_dimension(quality, benchmarks, ["Benchmark quality is retained independently from applicability and runtime behavior."]),
        "technical_feasibility": make_dimension(technical, evidence, ["Feasibility summarizes only supplied observations."]),
        "convergence_history": make_dimension(convergence, evidence, ["Convergence history is not converted into a success probability."]),
        "cost": make_dimension(cost_status, cost_known, ["Cost observations are preserved with their reported or observed status."], cost_observations),
    }


def derived_access(context: dict[str, Any], included: list[dict[str, Any]], principal: dict[str, Any] | None) -> dict[str, Any]:
    accesses = [context["access"], *[item["access"] for item in included]]
    class_rank = max(ACCESS_CLASSES.index(item["class"]) for item in accesses)
    policy_rank = max(EXPORT_POLICIES.index(item["export_policy"]) for item in accesses)
    access_class = ACCESS_CLASSES[class_rank]
    policy = EXPORT_POLICIES[policy_rank]
    if access_class == "public":
        return {"class": "public", "owner_project": None, "permitted_principals": [], "export_policy": policy}
    require(principal is not None, "restricted derived brief requires a declared principal")
    owners = {item["owner_project"] for item in accesses if item["owner_project"] is not None}
    if access_class == "project_restricted" and len(owners) == 1:
        return {"class": access_class, "owner_project": next(iter(owners)), "permitted_principals": [principal["principal_id"]], "export_policy": policy}
    if access_class == "group_internal":
        return {"class": access_class, "owner_project": None, "permitted_principals": [], "export_policy": policy}
    return {"class": "confidential_unpublished", "owner_project": next(iter(owners), None), "permitted_principals": [principal["principal_id"]], "export_policy": "no_export"}


def query_evidence(context: dict[str, Any], evidence: list[dict[str, Any]], principal: dict[str, Any] | None) -> dict[str, Any]:
    validate_artifact(context)
    require(context["schema"] == "auto-g16-method-selection-context/1", "query context has wrong schema")
    require(access_allowed(context, principal), "principal cannot access the selection context")
    included: list[tuple[dict[str, Any], str]] = []
    excluded: list[dict[str, Any]] = []
    denied = 0
    context_excluded = 0
    ordered: list[dict[str, Any]] = []
    revision_keys: set[tuple[str, str, str]] = set()
    for item in evidence:
        validate_artifact(item)
        require(item["schema"] in EVIDENCE_SCHEMAS, "query accepts only benchmark cases and run observations")
        revision_key = (item["schema"], item["artifact_id"], item["revision_id"])
        require(revision_key not in revision_keys, "query contains a duplicate evidence revision")
        revision_keys.add(revision_key)
        ordered.append(item)
    for item in sorted(ordered, key=lambda value: canonical_bytes(artifact_ref(value))):
        if not access_allowed(item, principal):
            denied += 1
            continue
        relevant, directness, reasons = relevance(context, item)
        if not relevant:
            context_excluded += 1
            excluded.append({"evidence_ref": artifact_ref(item), "reasons": reasons})
            continue
        included.append((item, directness))

    grouped: dict[bytes, tuple[dict[str, Any], list[tuple[dict[str, Any], str]]]] = {}
    for item, directness in included:
        method_ref = item["method_record_ref"]
        key = canonical_bytes(method_ref)
        grouped.setdefault(key, (method_ref, []))[1].append((item, directness))
    candidates = [candidate_summary(method_ref, entries) for _, (method_ref, entries) in sorted(grouped.items())]
    return {
        "included": [item for item, _ in included],
        "excluded": excluded,
        "candidate_evidence": candidates,
        "summary": {
            "supplied": len(evidence),
            "included": len(included),
            "excluded_permission": denied,
            "excluded_context": context_excluded,
        },
    }


def build_brief(context: dict[str, Any], evidence: list[dict[str, Any]], principal: dict[str, Any] | None, metadata: dict[str, str]) -> dict[str, Any]:
    result = query_evidence(context, evidence, principal)
    included = result["included"]
    dimensions = [candidate[name]["status"] for candidate in result["candidate_evidence"] for name in DIMENSION_STATUSES]
    if not included:
        evidence_status = "insufficient"
        rationale = "No accessible supplied evidence matched the reviewed calculation family and target property."
    elif any(status == "unknown" for status in dimensions):
        evidence_status = "insufficient"
        rationale = "Relevant evidence exists, but one or more independent evidence dimensions remain unknown."
    else:
        evidence_status = "reviewable"
        rationale = "All five evidence dimensions contain supplied observations for human review; no method selection or approval was performed."
    source_refs = {canonical_bytes(ref): ref for ref in context["source_revision_refs"]}
    for item in included:
        for ref in item["source_revision_refs"]:
            source_refs.setdefault(canonical_bytes(ref), ref)
    brief = {
        "schema": "auto-g16-method-evidence-brief/1",
        "artifact_id": metadata["artifact_id"],
        "revision_id": metadata["revision_id"],
        "created_at": metadata["created_at"],
        "created_by": metadata["created_by"],
        "review": {"status": "reviewed_with_limits", "reviewer": metadata["created_by"], "reviewed_at": metadata["created_at"], "notes": ["Deterministic offline evidence aggregation; scientific interpretation remains human-reviewed."]},
        "access": derived_access(context, included, principal),
        "provenance": {"source_kind": "reviewed_artifact", "importer": None, "source_artifacts": []},
        "source_revision_refs": [source_refs[key] for key in sorted(source_refs)],
        "supersedes": [],
        "exclusions": ["Method selection, protocol approval, success probability, input generation, and submission authority are outside this brief."],
        "context_ref": artifact_ref(context),
        "included_evidence_refs": [artifact_ref(item) for item in included],
        "excluded_evidence": result["excluded"],
        "candidate_evidence": result["candidate_evidence"],
        "query_summary": result["summary"],
        "evidence_status": evidence_status,
        "status_rationale": rationale,
        "method_selection": {"status": "not_performed", "selected_method_record_ref": None},
        "approval": {"status": "not_granted", "approved_protocol_ref": None},
        "calculation_ready": False,
        "no_submission_authorization": True,
        "no_method_selection_authorization": True,
        "no_approval_authorization": True,
        "payload_sha256": None,
    }
    return finalize_artifact(brief)


def command_validate(args: argparse.Namespace) -> None:
    artifact = load_json(Path(args.artifact))
    validate_artifact(artifact)
    print(json.dumps({"valid": True, "schema": artifact["schema"], "artifact_id": artifact["artifact_id"], "revision_id": artifact["revision_id"], "payload_sha256": artifact["payload_sha256"], "calculation_ready": False, "no_submission_authorization": True, "no_method_selection_authorization": True, "no_approval_authorization": True}, sort_keys=True))


def command_finalize(args: argparse.Namespace) -> None:
    artifact = finalize_artifact(load_json(Path(args.draft)))
    write_json(Path(args.output), artifact)
    print(json.dumps({"output": args.output, "schema": artifact["schema"], "payload_sha256": artifact["payload_sha256"]}, sort_keys=True))


def command_query(args: argparse.Namespace) -> None:
    context = load_json(Path(args.context))
    evidence = [load_json(Path(path)) for path in args.evidence]
    principal = load_principal(Path(args.principal) if args.principal else None)
    result = query_evidence(context, evidence, principal)
    report = {
        "context_ref": artifact_ref(context),
        "included_evidence_refs": [artifact_ref(item) for item in result["included"]],
        "excluded_evidence": result["excluded"],
        "candidate_evidence": result["candidate_evidence"],
        "query_summary": result["summary"],
        "method_selection": {"status": "not_performed", "selected_method_record_ref": None},
        "approval": {"status": "not_granted", "approved_protocol_ref": None},
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def command_build_brief(args: argparse.Namespace) -> None:
    context = load_json(Path(args.context))
    evidence = [load_json(Path(path)) for path in args.evidence]
    principal = load_principal(Path(args.principal) if args.principal else None)
    brief = build_brief(context, evidence, principal, {"artifact_id": args.brief_id, "revision_id": args.revision_id, "created_at": args.created_at, "created_by": args.created_by})
    write_json(Path(args.output), brief)
    print(json.dumps({"output": args.output, "payload_sha256": brief["payload_sha256"], "evidence_status": brief["evidence_status"], "query_summary": brief["query_summary"], "method_selection": brief["method_selection"], "approval": brief["approval"]}, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("artifact")
    validate.set_defaults(func=command_validate)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("draft")
    finalize.add_argument("--output", required=True)
    finalize.set_defaults(func=command_finalize)
    for name, handler in (("query", command_query), ("build-brief", command_build_brief)):
        command = subparsers.add_parser(name)
        command.add_argument("--context", required=True)
        command.add_argument("--evidence", nargs="+", required=True)
        command.add_argument("--principal")
        if name == "build-brief":
            command.add_argument("--brief-id", required=True)
            command.add_argument("--revision-id", required=True)
            command.add_argument("--created-at", required=True)
            command.add_argument("--created-by", required=True)
            command.add_argument("--output", required=True)
        command.set_defaults(func=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
