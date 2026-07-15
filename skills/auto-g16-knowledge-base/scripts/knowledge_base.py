#!/usr/bin/env python3
"""Strict offline validation for immutable Auto-G16 W2 knowledge records.

This module uses only the Python standard library. It performs no network,
Gaussian, SSH, PBS, deployment, or method-selection action. Local store writes
and exports require an exact plan-review-apply chain.
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
    "auto-g16-structure-record/1": "structure",
    "auto-g16-method-record/1": "method",
    "auto-g16-source-record/1": "source",
    "auto-g16-knowledge-link/1": "link",
    "auto-g16-knowledge-snapshot/1": "snapshot",
}

ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

REVIEW_STATUSES = {
    "draft",
    "reviewed",
    "reviewed_with_limits",
    "deprecated",
    "retracted",
    "blocked",
}
SNAPSHOT_REVIEW_STATUSES = {"reviewed", "reviewed_with_limits"}
ACCESS_CLASSES = {
    "public",
    "group_internal",
    "project_restricted",
    "confidential_unpublished",
}
EXPORT_POLICIES = {"full", "metadata_redacted", "no_export"}
REGISTRY_TYPES = {"structure", "method", "source", "link"}
REFERENCE_TYPES = REGISTRY_TYPES | {
    "reaction",
    "result",
    "calculation",
    "mechanism_hypothesis",
}

COMMON_KEYS = {
    "schema",
    "record_id",
    "revision_id",
    "created_at",
    "created_by",
    "review",
    "access",
    "provenance",
    "aliases",
    "external_identifiers",
    "uncertainties",
    "contradictions",
    "blockers",
    "calculation_ready",
    "no_submission_authorization",
    "payload_sha256",
}

PROTOCOL_FIELDS = (
    "program",
    "program_revision",
    "calculation_family",
    "functional",
    "basis_by_element",
    "ecp_by_element",
    "dispersion",
    "relativistic_treatment",
    "solvent_model",
    "explicit_components",
    "integration_grid",
    "scf_policy",
    "optimization_policy",
    "frequency_policy",
    "ts_policy",
    "irc_policy",
    "single_point_relationship",
    "charge_spin_requirements",
    "wavefunction_policy",
    "stability_checks",
    "temperature_pressure",
    "standard_state_concentration",
    "low_frequency_entropy",
)

RELATION_TYPES = {
    "structure_reported_in_source",
    "structure_coordinates_from_source",
    "structure_used_in_reaction",
    "method_reported_in_source",
    "method_used_by_calculation",
    "method_benchmarked_by_result",
    "method_failed_for_case",
    "source_supports_mechanism_hypothesis",
    "source_contradicts_mechanism_hypothesis",
    "ts_precedent_uses_structure_and_method",
    "record_supersedes_record",
}


class OfflineError(ValueError):
    """A record violated the offline W2 knowledge contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OfflineError(message)


def reject_json_constant(value: str) -> None:
    raise OfflineError(f"non-standard JSON numeric constant is forbidden: {value}")


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
            parse_constant=reject_json_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OfflineError(f"could not read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level JSON must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_data(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def payload_sha256(record: dict[str, Any]) -> str:
    payload = copy.deepcopy(record)
    payload.pop("payload_sha256", None)
    return sha256_data(payload)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value))
    except FileExistsError:
        raise OfflineError(f"refusing to overwrite existing artifact: {path}") from None


def exact_keys(
    value: Any,
    allowed: set[str],
    required: set[str],
    label: str,
) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def string(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    return value


def nullable_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return string(value, label)


def identifier(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and ID_RE.fullmatch(value) is not None,
        f"{label} must match {ID_RE.pattern}",
    )
    return value


def sha256(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        f"{label} must be a lowercase SHA-256",
    )
    return value


def timestamp(value: Any, label: str) -> str:
    text = string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfflineError(f"{label} must be an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return text


def string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    require(
        all(isinstance(item, str) and item.strip() for item in value),
        f"{label} must contain non-empty strings",
    )
    require(len(value) == len(set(value)), f"{label} must not contain duplicates")
    if nonempty:
        require(bool(value), f"{label} must not be empty")
    return value


def finite_number(value: Any, label: str, *, positive: bool = False) -> float:
    require(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value)),
        f"{label} must be a finite number",
    )
    if positive:
        require(float(value) > 0, f"{label} must be positive")
    return float(value)


def validate_record_ref(value: Any, label: str, *, registry_only: bool = False) -> dict[str, Any]:
    ref = exact_keys(
        value,
        {"record_type", "record_id", "revision_id", "payload_sha256"},
        {"record_type", "record_id", "revision_id", "payload_sha256"},
        label,
    )
    allowed = REGISTRY_TYPES if registry_only else REFERENCE_TYPES
    require(ref["record_type"] in allowed, f"{label}.record_type is unsupported")
    identifier(ref["record_id"], f"{label}.record_id")
    identifier(ref["revision_id"], f"{label}.revision_id")
    sha256(ref["payload_sha256"], f"{label}.payload_sha256")
    return ref


def validate_artifact_binding(value: Any, label: str) -> dict[str, Any]:
    binding = exact_keys(
        value,
        {"path", "sha256", "size_bytes", "schema", "payload_sha256"},
        {"path", "sha256", "size_bytes", "schema", "payload_sha256"},
        label,
    )
    string(binding["path"], f"{label}.path")
    sha256(binding["sha256"], f"{label}.sha256")
    require(
        isinstance(binding["size_bytes"], int)
        and not isinstance(binding["size_bytes"], bool)
        and binding["size_bytes"] >= 0,
        f"{label}.size_bytes must be a non-negative integer",
    )
    string(binding["schema"], f"{label}.schema")
    sha256(binding["payload_sha256"], f"{label}.payload_sha256")
    return binding


def validate_anchor_ref(value: Any, label: str) -> dict[str, Any]:
    ref = exact_keys(
        value,
        {"source_record", "anchor_id"},
        {"source_record", "anchor_id"},
        label,
    )
    source = validate_record_ref(ref["source_record"], f"{label}.source_record")
    require(source["record_type"] == "source", f"{label} must reference a source record")
    identifier(ref["anchor_id"], f"{label}.anchor_id")
    return ref


def validate_object_ref(value: Any, label: str) -> dict[str, Any]:
    ref = exact_keys(
        value,
        {"sha256", "size_bytes", "media_type", "storage_status", "original_name"},
        {"sha256", "size_bytes", "media_type", "storage_status", "original_name"},
        label,
    )
    sha256(ref["sha256"], f"{label}.sha256")
    require(
        isinstance(ref["size_bytes"], int)
        and not isinstance(ref["size_bytes"], bool)
        and ref["size_bytes"] >= 0,
        f"{label}.size_bytes must be a non-negative integer",
    )
    string(ref["media_type"], f"{label}.media_type")
    require(
        ref["storage_status"]
        in {"lawful_local_object", "metadata_only", "external_reference_only"},
        f"{label}.storage_status is invalid",
    )
    nullable_string(ref["original_name"], f"{label}.original_name")
    return ref


def validate_review(value: Any, label: str) -> dict[str, Any]:
    review = exact_keys(
        value,
        {"status", "reviewer", "reviewed_at", "notes"},
        {"status", "reviewer", "reviewed_at", "notes"},
        label,
    )
    require(review["status"] in REVIEW_STATUSES, f"{label}.status is invalid")
    reviewer = nullable_string(review["reviewer"], f"{label}.reviewer")
    reviewed_at = review["reviewed_at"]
    if review["status"] == "draft":
        require(reviewer is None and reviewed_at is None, f"{label}: draft cannot claim review")
    else:
        require(reviewer is not None, f"{label}: non-draft status requires a reviewer")
        timestamp(reviewed_at, f"{label}.reviewed_at")
    string_list(review["notes"], f"{label}.notes")
    return review


def validate_access(value: Any, label: str) -> dict[str, Any]:
    access = exact_keys(
        value,
        {"class", "owner_project", "permitted_principals", "export_policy"},
        {"class", "owner_project", "permitted_principals", "export_policy"},
        label,
    )
    require(access["class"] in ACCESS_CLASSES, f"{label}.class is invalid")
    owner = nullable_string(access["owner_project"], f"{label}.owner_project")
    principals = string_list(access["permitted_principals"], f"{label}.permitted_principals")
    require(access["export_policy"] in EXPORT_POLICIES, f"{label}.export_policy is invalid")
    if access["class"] == "project_restricted":
        require(owner is not None, f"{label}: project_restricted requires owner_project")
    if access["class"] == "confidential_unpublished":
        require(bool(principals), f"{label}: confidential records require permitted_principals")
        require(
            access["export_policy"] in {"metadata_redacted", "no_export"},
            f"{label}: confidential records cannot allow full export",
        )
    return access


def validate_provenance(value: Any, label: str) -> dict[str, Any]:
    provenance = exact_keys(
        value,
        {"source_kind", "importer", "source_artifacts"},
        {"source_kind", "importer", "source_artifacts"},
        label,
    )
    require(
        provenance["source_kind"]
        in {"manual_review", "imported", "reviewed_artifact", "study_result"},
        f"{label}.source_kind is invalid",
    )
    importer = nullable_string(provenance["importer"], f"{label}.importer")
    require(isinstance(provenance["source_artifacts"], list), f"{label}.source_artifacts must be an array")
    for index, artifact in enumerate(provenance["source_artifacts"]):
        validate_artifact_binding(artifact, f"{label}.source_artifacts[{index}]")
    if provenance["source_kind"] == "imported":
        require(importer is not None, f"{label}: imported provenance requires importer")
        require(bool(provenance["source_artifacts"]), f"{label}: imported provenance requires a source artifact")
    return provenance


def validate_aliases(value: Any, label: str) -> None:
    require(isinstance(value, list), f"{label} must be an array")
    seen: set[tuple[str, str]] = set()
    allowed_types = {
        "preferred_name",
        "synonym",
        "internal_code",
        "literature_code",
        "registry_identifier",
        "other",
    }
    for index, item in enumerate(value):
        alias = exact_keys(item, {"type", "value"}, {"type", "value"}, f"{label}[{index}]")
        require(alias["type"] in allowed_types, f"{label}[{index}].type is invalid")
        text = string(alias["value"], f"{label}[{index}].value")
        key = (alias["type"], text.casefold())
        require(key not in seen, f"{label} contains a duplicate alias")
        seen.add(key)


def validate_external_identifiers(value: Any, label: str) -> None:
    require(isinstance(value, list), f"{label} must be an array")
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        external = exact_keys(
            item,
            {"scheme", "value"},
            {"scheme", "value"},
            f"{label}[{index}]",
        )
        scheme = string(external["scheme"], f"{label}[{index}].scheme")
        external_value = string(external["value"], f"{label}[{index}].value")
        key = (scheme.casefold(), external_value.casefold())
        require(key not in seen, f"{label} contains a duplicate external identifier")
        seen.add(key)


def validate_issues(value: Any, label: str) -> None:
    require(isinstance(value, list), f"{label} must be an array")
    for index, item in enumerate(value):
        issue = exact_keys(
            item,
            {"code", "message", "source_refs"},
            {"code", "message", "source_refs"},
            f"{label}[{index}]",
        )
        identifier(issue["code"], f"{label}[{index}].code")
        string(issue["message"], f"{label}[{index}].message")
        string_list(issue["source_refs"], f"{label}[{index}].source_refs")


def validate_common(record: dict[str, Any], domain_keys: set[str]) -> None:
    exact_keys(record, COMMON_KEYS | domain_keys, COMMON_KEYS | domain_keys, "record")
    schema = record["schema"]
    require(schema in SCHEMAS, f"unsupported schema: {schema!r}")
    identifier(record["record_id"], "record.record_id")
    identifier(record["revision_id"], "record.revision_id")
    timestamp(record["created_at"], "record.created_at")
    string(record["created_by"], "record.created_by")
    validate_review(record["review"], "record.review")
    validate_access(record["access"], "record.access")
    validate_provenance(record["provenance"], "record.provenance")
    validate_aliases(record["aliases"], "record.aliases")
    validate_external_identifiers(record["external_identifiers"], "record.external_identifiers")
    validate_issues(record["uncertainties"], "record.uncertainties")
    validate_issues(record["contradictions"], "record.contradictions")
    validate_issues(record["blockers"], "record.blockers")
    require(record["calculation_ready"] is False, "record.calculation_ready must be false")
    require(
        record["no_submission_authorization"] is True,
        "record.no_submission_authorization must be true",
    )
    sha256(record["payload_sha256"], "record.payload_sha256")
    require(
        record["payload_sha256"] == payload_sha256(record),
        "record payload SHA-256 mismatch",
    )


def validate_identity(value: Any, label: str) -> None:
    identity = exact_keys(
        value,
        {
            "preferred_name",
            "formula",
            "exact_mass",
            "canonical_smiles",
            "inchi",
            "inchikey",
            "isotopes",
            "component_count",
            "stereochemistry",
            "roles",
            "composition_notes",
        },
        {
            "preferred_name",
            "formula",
            "exact_mass",
            "canonical_smiles",
            "inchi",
            "inchikey",
            "isotopes",
            "component_count",
            "stereochemistry",
            "roles",
            "composition_notes",
        },
        label,
    )
    string(identity["preferred_name"], f"{label}.preferred_name")
    nullable_string(identity["formula"], f"{label}.formula")
    if identity["exact_mass"] is not None:
        finite_number(identity["exact_mass"], f"{label}.exact_mass", positive=True)
    nullable_string(identity["canonical_smiles"], f"{label}.canonical_smiles")
    nullable_string(identity["inchi"], f"{label}.inchi")
    nullable_string(identity["inchikey"], f"{label}.inchikey")
    string_list(identity["isotopes"], f"{label}.isotopes")
    require(
        isinstance(identity["component_count"], int)
        and not isinstance(identity["component_count"], bool)
        and identity["component_count"] >= 1,
        f"{label}.component_count must be a positive integer",
    )
    stereo = exact_keys(
        identity["stereochemistry"],
        {"status", "description"},
        {"status", "description"},
        f"{label}.stereochemistry",
    )
    require(
        stereo["status"] in {"reviewed", "not_applicable", "unresolved"},
        f"{label}.stereochemistry.status is invalid",
    )
    nullable_string(stereo["description"], f"{label}.stereochemistry.description")
    string_list(identity["roles"], f"{label}.roles", nonempty=True)
    string_list(identity["composition_notes"], f"{label}.composition_notes")


def validate_state(value: Any, label: str) -> None:
    state = exact_keys(
        value,
        {
            "formal_charge",
            "multiplicity",
            "protonation",
            "salt_solvate_form",
            "oxidation_state_hypothesis",
            "ligand_count",
            "coordination_number",
            "hapticity",
            "aggregation",
            "ion_pairing",
            "bound_components",
        },
        {
            "formal_charge",
            "multiplicity",
            "protonation",
            "salt_solvate_form",
            "oxidation_state_hypothesis",
            "ligand_count",
            "coordination_number",
            "hapticity",
            "aggregation",
            "ion_pairing",
            "bound_components",
        },
        label,
    )
    require(isinstance(state["formal_charge"], int) and not isinstance(state["formal_charge"], bool), f"{label}.formal_charge must be an integer")
    require(isinstance(state["multiplicity"], int) and not isinstance(state["multiplicity"], bool) and state["multiplicity"] >= 1, f"{label}.multiplicity must be a positive integer")
    for field in (
        "protonation",
        "salt_solvate_form",
        "oxidation_state_hypothesis",
        "hapticity",
        "aggregation",
        "ion_pairing",
    ):
        nullable_string(state[field], f"{label}.{field}")
    for field in ("ligand_count", "coordination_number"):
        if state[field] is not None:
            require(isinstance(state[field], int) and not isinstance(state[field], bool) and state[field] >= 0, f"{label}.{field} must be a non-negative integer or null")
    string_list(state["bound_components"], f"{label}.bound_components")


def validate_representation(value: Any, label: str) -> None:
    representation = exact_keys(
        value,
        {
            "representation_id",
            "format",
            "object",
            "source_exact",
            "atom_order",
            "review_scope",
            "geometry_provenance",
            "supporting_record_refs",
            "limitations",
        },
        {
            "representation_id",
            "format",
            "object",
            "source_exact",
            "atom_order",
            "review_scope",
            "geometry_provenance",
            "supporting_record_refs",
            "limitations",
        },
        label,
    )
    identifier(representation["representation_id"], f"{label}.representation_id")
    require(
        representation["format"]
        in {"cdx", "cdxml", "mol", "sdf", "smiles", "inchi", "xyz", "gaussian_input", "png", "svg", "other"},
        f"{label}.format is invalid",
    )
    validate_object_ref(representation["object"], f"{label}.object")
    require(type(representation["source_exact"]) is bool, f"{label}.source_exact must be boolean")
    require(
        representation["atom_order"] in {"exact", "reviewed", "unknown", "not_applicable"},
        f"{label}.atom_order is invalid",
    )
    string(representation["review_scope"], f"{label}.review_scope")
    require(
        representation["geometry_provenance"]
        in {
            "source_exact_2d",
            "normalized_2d",
            "experimental_coordinates",
            "literature_coordinates",
            "generated_conformer",
            "optimized_minimum",
            "ts_candidate",
            "visualization_only",
            "not_applicable",
        },
        f"{label}.geometry_provenance is invalid",
    )
    require(isinstance(representation["supporting_record_refs"], list), f"{label}.supporting_record_refs must be an array")
    for index, ref in enumerate(representation["supporting_record_refs"]):
        validate_record_ref(ref, f"{label}.supporting_record_refs[{index}]")
    string_list(representation["limitations"], f"{label}.limitations")


def validate_structure(record: dict[str, Any]) -> None:
    domain = {"record_scope", "identity", "parent_identity", "state", "parent_state", "representations"}
    validate_common(record, domain)
    require(record["schema"] == "auto-g16-structure-record/1", "structure record schema mismatch")
    scope = record["record_scope"]
    require(scope in {"identity", "state", "geometry"}, "record.record_scope is invalid")
    require(isinstance(record["representations"], list), "record.representations must be an array")
    representation_ids: set[str] = set()
    for index, representation in enumerate(record["representations"]):
        validate_representation(representation, f"record.representations[{index}]")
        rep_id = representation["representation_id"]
        require(rep_id not in representation_ids, "record.representations contains duplicate IDs")
        representation_ids.add(rep_id)
    if scope == "identity":
        validate_identity(record["identity"], "record.identity")
        require(record["parent_identity"] is None and record["state"] is None and record["parent_state"] is None, "identity scope cannot contain state or parent references")
    elif scope == "state":
        require(record["identity"] is None and record["parent_state"] is None, "state scope cannot contain identity payload or parent_state")
        parent = validate_record_ref(record["parent_identity"], "record.parent_identity", registry_only=True)
        require(parent["record_type"] == "structure", "record.parent_identity must reference a structure record")
        validate_state(record["state"], "record.state")
    else:
        require(record["identity"] is None and record["state"] is None and record["parent_identity"] is None, "geometry scope cannot contain identity/state payload or parent_identity")
        parent = validate_record_ref(record["parent_state"], "record.parent_state", registry_only=True)
        require(parent["record_type"] == "structure", "record.parent_state must reference a structure state record")
        require(bool(record["representations"]), "geometry scope requires at least one representation")
        require(
            any(item["geometry_provenance"] not in {"source_exact_2d", "normalized_2d", "not_applicable"} for item in record["representations"]),
            "geometry scope requires a three-dimensional geometry provenance",
        )


def validate_fact(value: Any, label: str) -> dict[str, Any]:
    fact = exact_keys(
        value,
        {"status", "value", "source_anchor_refs", "notes"},
        {"status", "value", "source_anchor_refs", "notes"},
        label,
    )
    require(
        fact["status"]
        in {"reported", "internal_decision", "derived", "ambiguous", "not_reported", "not_applicable"},
        f"{label}.status is invalid",
    )
    fact_value = fact["value"]
    scalar = (str, int, float, bool)
    if isinstance(fact_value, str):
        require(bool(fact_value.strip()), f"{label}.value strings must not be empty")
    elif isinstance(fact_value, (int, float)) and not isinstance(fact_value, bool):
        finite_number(fact_value, f"{label}.value")
    elif isinstance(fact_value, list):
        require(
            all(item is None or isinstance(item, scalar) for item in fact_value),
            f"{label}.value arrays may contain only scalar values",
        )
        for index, item in enumerate(fact_value):
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                finite_number(item, f"{label}.value[{index}]")
    elif isinstance(fact_value, dict):
        require(
            all(isinstance(key, str) and key.strip() for key in fact_value),
            f"{label}.value maps require non-empty string keys",
        )
        require(
            all(item is None or isinstance(item, scalar) for item in fact_value.values()),
            f"{label}.value maps may contain only scalar values",
        )
        for key, item in fact_value.items():
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                finite_number(item, f"{label}.value[{key!r}]")
    else:
        require(fact_value is None or isinstance(fact_value, bool), f"{label}.value has an unsupported type")
    require(isinstance(fact["source_anchor_refs"], list), f"{label}.source_anchor_refs must be an array")
    for index, anchor in enumerate(fact["source_anchor_refs"]):
        validate_anchor_ref(anchor, f"{label}.source_anchor_refs[{index}]")
    string_list(fact["notes"], f"{label}.notes")
    if fact["status"] == "reported":
        require(bool(fact["source_anchor_refs"]), f"{label}: reported facts require a source anchor")
        require(fact["value"] is not None, f"{label}: reported facts require a value")
    if fact["status"] in {"not_reported", "not_applicable"}:
        require(fact["value"] is None, f"{label}: {fact['status']} facts must have null value")
    return fact


def validate_method(record: dict[str, Any]) -> None:
    domain = {"source_class", "protocol", "applicability", "evidence"}
    validate_common(record, domain)
    require(record["schema"] == "auto-g16-method-record/1", "method record schema mismatch")
    require(
        record["source_class"]
        in {
            "literature_reported",
            "group_custom",
            "group_recommended",
            "benchmark_candidate",
            "group_validated_within_scope",
            "blocked",
            "deprecated",
            "superseded",
        },
        "record.source_class is invalid",
    )
    protocol = exact_keys(
        record["protocol"],
        set(PROTOCOL_FIELDS),
        set(PROTOCOL_FIELDS),
        "record.protocol",
    )
    incomplete_reported: list[str] = []
    for field in PROTOCOL_FIELDS:
        fact = validate_fact(protocol[field], f"record.protocol.{field}")
        if fact["status"] in {"not_reported", "ambiguous"}:
            incomplete_reported.append(field)
    applicability = exact_keys(
        record["applicability"],
        {"included_elements", "catalyst_classes", "reaction_classes", "state_types", "job_stages", "exclusions", "limitations"},
        {"included_elements", "catalyst_classes", "reaction_classes", "state_types", "job_stages", "exclusions", "limitations"},
        "record.applicability",
    )
    elements = string_list(applicability["included_elements"], "record.applicability.included_elements")
    require(all(ELEMENT_RE.fullmatch(item) for item in elements), "record.applicability.included_elements contains an invalid element")
    for field in ("catalyst_classes", "reaction_classes", "state_types", "job_stages", "exclusions", "limitations"):
        string_list(applicability[field], f"record.applicability.{field}")
    evidence = exact_keys(
        record["evidence"],
        {"supporting_source_refs", "benchmark_record_refs", "failure_record_refs", "resource_observations", "notes"},
        {"supporting_source_refs", "benchmark_record_refs", "failure_record_refs", "resource_observations", "notes"},
        "record.evidence",
    )
    for field in ("supporting_source_refs", "benchmark_record_refs", "failure_record_refs"):
        require(isinstance(evidence[field], list), f"record.evidence.{field} must be an array")
        for index, ref in enumerate(evidence[field]):
            validate_record_ref(ref, f"record.evidence.{field}[{index}]")
    string_list(evidence["resource_observations"], "record.evidence.resource_observations")
    string_list(evidence["notes"], "record.evidence.notes")
    review_status = record["review"]["status"]
    if record["source_class"] == "literature_reported" and incomplete_reported:
        require(
            review_status != "reviewed",
            "incomplete literature-reported methods must be reviewed_with_limits, blocked, or draft",
        )
    if record["source_class"] == "group_validated_within_scope":
        require(bool(evidence["benchmark_record_refs"]), "group_validated_within_scope requires benchmark evidence")
    if record["source_class"] in {"blocked", "deprecated", "superseded"}:
        require(review_status in {"blocked", "deprecated", "reviewed_with_limits"}, "method source_class and review status are inconsistent")


def validate_bibliography(value: Any, label: str) -> dict[str, Any]:
    fields = {
        "doi",
        "isbn",
        "issn",
        "publisher",
        "authors",
        "editors",
        "title",
        "year",
        "journal",
        "volume",
        "issue",
        "page_range",
        "article_number",
        "stable_url",
    }
    bibliography = exact_keys(value, fields, fields, label)
    doi = nullable_string(bibliography["doi"], f"{label}.doi")
    if doi is not None:
        require(DOI_RE.fullmatch(doi) is not None, f"{label}.doi is invalid")
    for field in ("isbn", "issn", "publisher", "journal", "volume", "issue", "page_range", "article_number", "stable_url"):
        nullable_string(bibliography[field], f"{label}.{field}")
    string_list(bibliography["authors"], f"{label}.authors")
    string_list(bibliography["editors"], f"{label}.editors")
    string(bibliography["title"], f"{label}.title")
    if bibliography["year"] is not None:
        require(isinstance(bibliography["year"], int) and not isinstance(bibliography["year"], bool) and 1000 <= bibliography["year"] <= 3000, f"{label}.year is invalid")
    require(
        any(bibliography[field] is not None for field in ("doi", "isbn", "stable_url")),
        f"{label} requires DOI, ISBN, or stable_url",
    )
    return bibliography


def validate_source(record: dict[str, Any]) -> None:
    domain = {"source_type", "bibliography", "version", "access_details", "objects", "anchors", "claims"}
    validate_common(record, domain)
    require(record["schema"] == "auto-g16-source-record/1", "source record schema mismatch")
    require(
        record["source_type"]
        in {"journal_article", "supporting_information", "book", "book_chapter", "handbook", "thesis", "preprint", "patent", "correction", "retraction", "dataset", "repository"},
        "record.source_type is invalid",
    )
    validate_bibliography(record["bibliography"], "record.bibliography")
    version = exact_keys(
        record["version"],
        {"edition", "chapter", "version_label", "language"},
        {"edition", "chapter", "version_label", "language"},
        "record.version",
    )
    for field in ("edition", "chapter", "version_label"):
        nullable_string(version[field], f"record.version.{field}")
    string(version["language"], "record.version.language")
    access_details = exact_keys(
        record["access_details"],
        {"accessed_at", "license", "storage_status", "access_limitations"},
        {"accessed_at", "license", "storage_status", "access_limitations"},
        "record.access_details",
    )
    timestamp(access_details["accessed_at"], "record.access_details.accessed_at")
    nullable_string(access_details["license"], "record.access_details.license")
    require(access_details["storage_status"] in {"lawful_local_object", "metadata_only", "external_reference_only"}, "record.access_details.storage_status is invalid")
    string_list(access_details["access_limitations"], "record.access_details.access_limitations")
    require(isinstance(record["objects"], list), "record.objects must be an array")
    object_hashes: set[str] = set()
    for index, obj in enumerate(record["objects"]):
        validate_object_ref(obj, f"record.objects[{index}]")
        require(obj["sha256"] not in object_hashes, "record.objects contains duplicate hashes")
        object_hashes.add(obj["sha256"])
    if access_details["storage_status"] == "lawful_local_object":
        require(bool(record["objects"]), "lawful_local_object source requires at least one object hash")
    require(isinstance(record["anchors"], list), "record.anchors must be an array")
    anchor_ids: set[str] = set()
    for index, item in enumerate(record["anchors"]):
        anchor = exact_keys(
            item,
            {"anchor_id", "locator_type", "locator", "object_sha256", "notes"},
            {"anchor_id", "locator_type", "locator", "object_sha256", "notes"},
            f"record.anchors[{index}]",
        )
        anchor_id = identifier(anchor["anchor_id"], f"record.anchors[{index}].anchor_id")
        require(anchor_id not in anchor_ids, "record.anchors contains duplicate IDs")
        anchor_ids.add(anchor_id)
        require(anchor["locator_type"] in {"page", "section", "scheme", "figure", "table", "equation", "paragraph", "si_section", "coordinate_block", "chapter", "repository_item"}, f"record.anchors[{index}].locator_type is invalid")
        string(anchor["locator"], f"record.anchors[{index}].locator")
        if anchor["object_sha256"] is not None:
            sha256(anchor["object_sha256"], f"record.anchors[{index}].object_sha256")
            require(anchor["object_sha256"] in object_hashes, f"record.anchors[{index}] references an absent object")
        string_list(anchor["notes"], f"record.anchors[{index}].notes")
    require(isinstance(record["claims"], list), "record.claims must be an array")
    claim_ids: set[str] = set()
    for index, item in enumerate(record["claims"]):
        claim = exact_keys(
            item,
            {"claim_id", "category", "statement_type", "text", "anchor_ids", "review_status"},
            {"claim_id", "category", "statement_type", "text", "anchor_ids", "review_status"},
            f"record.claims[{index}]",
        )
        claim_id = identifier(claim["claim_id"], f"record.claims[{index}].claim_id")
        require(claim_id not in claim_ids, "record.claims contains duplicate IDs")
        claim_ids.add(claim_id)
        string(claim["category"], f"record.claims[{index}].category")
        require(claim["statement_type"] in {"paraphrase", "short_quote", "reviewer_interpretation"}, f"record.claims[{index}].statement_type is invalid")
        text = string(claim["text"], f"record.claims[{index}].text")
        claim_anchors = string_list(claim["anchor_ids"], f"record.claims[{index}].anchor_ids")
        require(claim["review_status"] in {"reviewed", "reviewed_with_limits", "unverified", "contradicted"}, f"record.claims[{index}].review_status is invalid")
        if claim["review_status"] in {"reviewed", "reviewed_with_limits", "contradicted"}:
            require(bool(claim_anchors), f"record.claims[{index}] requires a source anchor")
        require(all(anchor_id in anchor_ids for anchor_id in claim_anchors), f"record.claims[{index}] references an unknown anchor")
        if claim["statement_type"] == "short_quote":
            require(len(text.split()) <= 25, f"record.claims[{index}] short quote exceeds 25 words")
    if record["source_type"] in {"book", "book_chapter", "handbook"} and record["review"]["status"] in SNAPSHOT_REVIEW_STATUSES:
        require(version["edition"] is not None, "reviewed book sources require an edition")
        require(bool(record["anchors"]), "reviewed book sources require page or chapter anchors")


def validate_link(record: dict[str, Any]) -> None:
    domain = {"relation_type", "source", "target", "evidence_directness", "source_anchors", "evidence_record_refs", "scope", "mismatches"}
    validate_common(record, domain)
    require(record["schema"] == "auto-g16-knowledge-link/1", "knowledge-link schema mismatch")
    require(record["relation_type"] in RELATION_TYPES, "record.relation_type is invalid")
    source = validate_record_ref(record["source"], "record.source")
    target = validate_record_ref(record["target"], "record.target")
    require(record["evidence_directness"] in {"direct", "analogous"}, "record.evidence_directness is invalid")
    require(isinstance(record["source_anchors"], list), "record.source_anchors must be an array")
    for index, anchor in enumerate(record["source_anchors"]):
        validate_anchor_ref(anchor, f"record.source_anchors[{index}]")
    require(isinstance(record["evidence_record_refs"], list), "record.evidence_record_refs must be an array")
    for index, evidence_ref in enumerate(record["evidence_record_refs"]):
        validate_record_ref(evidence_ref, f"record.evidence_record_refs[{index}]")
    string(record["scope"], "record.scope")
    string_list(record["mismatches"], "record.mismatches")
    if record["relation_type"] == "record_supersedes_record":
        require(source["record_type"] == target["record_type"] and source["record_id"] == target["record_id"], "supersession must connect revisions of the same logical record")
        require(source["revision_id"] != target["revision_id"], "supersession must connect different revisions")
        require(record["evidence_directness"] == "direct", "supersession cannot be analogous")
    elif record["review"]["status"] in SNAPSHOT_REVIEW_STATUSES:
        require(bool(record["source_anchors"] or record["evidence_record_refs"]), "reviewed scientific links require evidence")


def snapshot_dependency_digest(record: dict[str, Any]) -> str:
    dependencies = [
        {
            "record_type": item["record_type"],
            "record_id": item["record_id"],
            "revision_id": item["revision_id"],
            "payload_sha256": item["payload_sha256"],
            "review_status": item["review_status"],
            "access_class": item["access_class"],
        }
        for item in record.get("included_records", [])
        if isinstance(item, dict)
    ]
    dependencies.sort(key=lambda item: (item["record_type"], item["record_id"], item["revision_id"]))
    return sha256_data(dependencies)


def validate_snapshot_ref(value: Any, label: str) -> dict[str, Any]:
    ref = exact_keys(
        value,
        {"record_type", "record_id", "revision_id", "payload_sha256", "review_status", "access_class"},
        {"record_type", "record_id", "revision_id", "payload_sha256", "review_status", "access_class"},
        label,
    )
    validate_record_ref(
        {key: ref[key] for key in ("record_type", "record_id", "revision_id", "payload_sha256")},
        label,
        registry_only=True,
    )
    require(ref["review_status"] in SNAPSHOT_REVIEW_STATUSES, f"{label} contains an unreviewed revision")
    require(ref["access_class"] in ACCESS_CLASSES, f"{label}.access_class is invalid")
    return ref


def validate_snapshot(record: dict[str, Any]) -> None:
    domain = {"study_id", "parent_reaction_intake", "queries", "selection_decisions", "included_records", "redactions", "unresolved_gaps", "dependency_digest"}
    validate_common(record, domain)
    require(record["schema"] == "auto-g16-knowledge-snapshot/1", "knowledge-snapshot schema mismatch")
    identifier(record["study_id"], "record.study_id")
    parent = validate_artifact_binding(record["parent_reaction_intake"], "record.parent_reaction_intake")
    require(parent["schema"] == "gaussian-reaction-intake/1", "snapshot parent must be a reaction-intake artifact")
    require(isinstance(record["queries"], list), "record.queries must be an array")
    query_ids: set[str] = set()
    for index, item in enumerate(record["queries"]):
        query = exact_keys(
            item,
            {"query_id", "registry", "query", "filters", "executed_at"},
            {"query_id", "registry", "query", "filters", "executed_at"},
            f"record.queries[{index}]",
        )
        query_id = identifier(query["query_id"], f"record.queries[{index}].query_id")
        require(query_id not in query_ids, "record.queries contains duplicate IDs")
        query_ids.add(query_id)
        require(query["registry"] in {"structure", "method", "source", "link", "all"}, f"record.queries[{index}].registry is invalid")
        string(query["query"], f"record.queries[{index}].query")
        string_list(query["filters"], f"record.queries[{index}].filters")
        timestamp(query["executed_at"], f"record.queries[{index}].executed_at")
    require(isinstance(record["included_records"], list), "record.included_records must be an array")
    included_keys: set[tuple[str, str, str]] = set()
    for index, item in enumerate(record["included_records"]):
        ref = validate_snapshot_ref(item, f"record.included_records[{index}]")
        key = (ref["record_type"], ref["record_id"], ref["revision_id"])
        require(key not in included_keys, "record.included_records contains duplicates")
        included_keys.add(key)
    require(isinstance(record["selection_decisions"], list), "record.selection_decisions must be an array")
    decision_ids: set[str] = set()
    included_decisions: set[tuple[str, str, str]] = set()
    for index, item in enumerate(record["selection_decisions"]):
        decision = exact_keys(
            item,
            {"decision_id", "record_ref", "decision", "rationale"},
            {"decision_id", "record_ref", "decision", "rationale"},
            f"record.selection_decisions[{index}]",
        )
        decision_id = identifier(decision["decision_id"], f"record.selection_decisions[{index}].decision_id")
        require(decision_id not in decision_ids, "record.selection_decisions contains duplicate IDs")
        decision_ids.add(decision_id)
        ref = validate_record_ref(decision["record_ref"], f"record.selection_decisions[{index}].record_ref", registry_only=True)
        require(decision["decision"] in {"included", "excluded"}, f"record.selection_decisions[{index}].decision is invalid")
        string(decision["rationale"], f"record.selection_decisions[{index}].rationale")
        if decision["decision"] == "included":
            included_decisions.add((ref["record_type"], ref["record_id"], ref["revision_id"]))
    require(included_decisions == included_keys, "snapshot included records must exactly match included selection decisions")
    string_list(record["redactions"], "record.redactions")
    string_list(record["unresolved_gaps"], "record.unresolved_gaps")
    require(bool(record["included_records"] or record["unresolved_gaps"]), "snapshot must contain a reviewed record or an explicit unresolved gap")
    sha256(record["dependency_digest"], "record.dependency_digest")
    require(record["dependency_digest"] == snapshot_dependency_digest(record), "snapshot dependency digest mismatch")
    require(record["review"]["status"] in SNAPSHOT_REVIEW_STATUSES, "knowledge snapshots must be reviewed or reviewed_with_limits")


VALIDATORS = {
    "auto-g16-structure-record/1": validate_structure,
    "auto-g16-method-record/1": validate_method,
    "auto-g16-source-record/1": validate_source,
    "auto-g16-knowledge-link/1": validate_link,
    "auto-g16-knowledge-snapshot/1": validate_snapshot,
}


def validate_record(record: dict[str, Any]) -> None:
    schema = record.get("schema")
    require(isinstance(schema, str) and schema in VALIDATORS, f"unsupported schema: {schema!r}")
    VALIDATORS[schema](record)


def audit_record_set(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Report duplicates and conflicts without merging or mutating records."""

    revision_keys: dict[tuple[str, str, str], dict[str, Any]] = {}
    identity_keys: dict[tuple[str, str], dict[str, Any]] = {}
    external_keys: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for record in records:
        validate_record(record)
        record_type = SCHEMAS[record["schema"]]
        revision_key = (record_type, record["record_id"], record["revision_id"])
        previous = revision_keys.get(revision_key)
        if previous is not None:
            item = {
                "kind": "duplicate_revision" if previous["payload_sha256"] == record["payload_sha256"] else "conflicting_revision_payload",
                "record_type": record_type,
                "record_id": record["record_id"],
                "revision_id": record["revision_id"],
                "payload_sha256_values": sorted({previous["payload_sha256"], record["payload_sha256"]}),
            }
            (duplicates if item["kind"] == "duplicate_revision" else conflicts).append(item)
        else:
            revision_keys[revision_key] = record

        if record_type == "structure" and record.get("record_scope") == "identity":
            identity = record.get("identity") or {}
            for scheme, raw_value in (
                ("inchikey", identity.get("inchikey")),
                ("canonical_smiles", identity.get("canonical_smiles")),
            ):
                if isinstance(raw_value, str) and raw_value.strip():
                    key = (scheme, raw_value.strip().casefold())
                    prior = identity_keys.get(key)
                    if prior is not None and prior["record_id"] != record["record_id"]:
                        duplicates.append(
                            {
                                "kind": "duplicate_structure_identity_candidate",
                                "identity_scheme": scheme,
                                "identity_value": raw_value,
                                "record_ids": sorted({prior["record_id"], record["record_id"]}),
                            }
                        )
                    else:
                        identity_keys[key] = record

        if record_type == "source":
            bibliography = record.get("bibliography") or {}
            for scheme in ("doi", "isbn"):
                raw_value = bibliography.get(scheme)
                if isinstance(raw_value, str) and raw_value.strip():
                    key = (scheme, raw_value.strip().casefold())
                    prior = external_keys.get(key)
                    if prior is not None and prior["record_id"] != record["record_id"]:
                        duplicates.append(
                            {
                                "kind": "duplicate_source_identity_candidate",
                                "identity_scheme": scheme,
                                "identity_value": raw_value,
                                "record_ids": sorted({prior["record_id"], record["record_id"]}),
                            }
                        )
                    else:
                        external_keys[key] = record

    def unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        values = {canonical_bytes(item): item for item in items}
        return [values[key] for key in sorted(values)]

    duplicates = unique(duplicates)
    conflicts = unique(conflicts)
    return {
        "record_count": len(records),
        "duplicate_candidates": duplicates,
        "conflicts": conflicts,
        "automatic_merge_performed": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }


def finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    require(record.get("schema") in VALIDATORS, f"unsupported schema: {record.get('schema')!r}")
    require(record.get("payload_sha256") is None, "finalize accepts only a draft with null payload_sha256")
    finalized = copy.deepcopy(record)
    if finalized["schema"] == "auto-g16-knowledge-snapshot/1":
        digest = snapshot_dependency_digest(finalized)
        if finalized.get("dependency_digest") is None:
            finalized["dependency_digest"] = digest
        else:
            require(finalized["dependency_digest"] == digest, "snapshot dependency digest mismatch")
    finalized["payload_sha256"] = payload_sha256(finalized)
    validate_record(finalized)
    return finalized


def command_validate(args: argparse.Namespace) -> None:
    path = Path(args.record)
    record = load_json(path)
    validate_record(record)
    print(
        json.dumps(
            {
                "valid": True,
                "path": str(path),
                "schema": record["schema"],
                "record_id": record["record_id"],
                "revision_id": record["revision_id"],
                "payload_sha256": record["payload_sha256"],
                "calculation_ready": False,
                "no_submission_authorization": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def command_finalize(args: argparse.Namespace) -> None:
    draft_path = Path(args.draft)
    output = Path(args.output)
    record = finalize_record(load_json(draft_path))
    write_json(output, record)
    print(
        json.dumps(
            {
                "output": str(output),
                "schema": record["schema"],
                "record_id": record["record_id"],
                "revision_id": record["revision_id"],
                "payload_sha256": record["payload_sha256"],
                "calculation_ready": False,
                "no_submission_authorization": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def command_audit_set(args: argparse.Namespace) -> None:
    paths = [Path(value) for value in args.records]
    report = audit_record_set([load_json(path) for path in paths])
    report["paths"] = [str(path) for path in paths]
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate one finalized knowledge record")
    validate.add_argument("record")
    validate.set_defaults(func=command_validate)

    finalize = subparsers.add_parser("finalize", help="Hash and validate a reviewed draft into a new path")
    finalize.add_argument("draft")
    finalize.add_argument("--output", required=True)
    finalize.set_defaults(func=command_finalize)

    audit_set = subparsers.add_parser(
        "audit-set",
        help="Report duplicate and conflicting records without merging them",
    )
    audit_set.add_argument("records", nargs="+")
    audit_set.set_defaults(func=command_audit_set)

    # Keep persistence code isolated while exposing one stable Skill CLI.
    import knowledge_store

    knowledge_store.add_subparsers(subparsers)
    import knowledge_transfer

    knowledge_transfer.add_subparsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
