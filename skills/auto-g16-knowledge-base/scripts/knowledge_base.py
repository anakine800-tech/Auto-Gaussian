#!/usr/bin/env python3
"""Deterministic offline Auto-G16 knowledge registry.

Canonical JSON records and content-addressed objects are the source of truth.
SQLite files are disposable indexes.  This module uses only the Python standard
library and never invokes Gaussian, SSH, PBS, deployment, or a network service.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMAS = {
    "structure": "auto-g16-structure-record/1",
    "method": "auto-g16-method-record/1",
    "source": "auto-g16-source-record/1",
    "link": "auto-g16-knowledge-link/1",
    "snapshot": "auto-g16-knowledge-snapshot/1",
}
SCHEMA_TO_TYPE = {value: key for key, value in SCHEMAS.items()}
RECORD_TYPES = set(SCHEMAS)
REVIEW_STATUSES = {
    "draft",
    "reviewed",
    "reviewed_with_limits",
    "deprecated",
    "retracted",
    "blocked",
}
SNAPSHOT_REVIEW_STATUSES = {"reviewed", "reviewed_with_limits"}
ACCESS_CLASSES = (
    "public",
    "group_internal",
    "project_restricted",
    "confidential_unpublished",
)
ACCESS_RANK = {value: index for index, value in enumerate(ACCESS_CLASSES)}
METHOD_CLASSES = {
    "literature_reported",
    "group_internal",
    "group_recommended",
    "benchmark_candidate",
    "validated_within_scope",
    "blocked",
    "deprecated",
    "superseded",
}
SOURCE_TYPES = {
    "journal_article",
    "supporting_information",
    "book",
    "book_chapter",
    "thesis",
    "preprint",
    "patent",
    "correction",
    "retraction",
    "dataset",
    "repository",
}
LINK_TYPES = {
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
EVIDENCE_MODES = {"direct", "analogous"}
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")
REVISION_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}_r[0-9]{3,}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DOI_RE = re.compile(r"^10\.[0-9]{4,9}/\S+$", re.IGNORECASE)

COMMON_KEYS = {
    "schema",
    "record_type",
    "logical_id",
    "revision_id",
    "revision",
    "created_at",
    "created_by",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "review_notes",
    "access",
    "provenance",
    "aliases",
    "external_identifiers",
    "uncertainties",
    "blockers",
    "supersedes",
    "link_ids",
    "data",
    "payload_sha256",
    "calculation_ready",
    "no_submission_authorization",
}


class KnowledgeError(ValueError):
    """A knowledge-base input violated the offline contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise KnowledgeError(message)


def reject_constant(value: str) -> None:
    raise KnowledgeError(f"non-standard JSON numeric constant is forbidden: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeError(f"could not read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level JSON must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(record: dict[str, Any]) -> str:
    value = copy.deepcopy(record)
    value.pop("payload_sha256", None)
    return sha256_bytes(canonical_bytes(value))


def finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(record)
    value["calculation_ready"] = False
    value["no_submission_authorization"] = True
    value["payload_sha256"] = payload_sha256(value)
    return value


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing fields: {', '.join(missing)}")


def text(value: Any, label: str, *, empty: bool = False) -> str:
    require(isinstance(value, str), f"{label} must be a string")
    if not empty:
        require(bool(value.strip()), f"{label} must not be empty")
    return value


def optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return text(value, label)


def string_list(value: Any, label: str) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    require(
        all(isinstance(item, str) and item.strip() for item in value),
        f"{label} must contain non-empty strings",
    )
    require(len(value) == len(set(value)), f"{label} must not contain duplicates")
    return list(value)


def identifier(value: Any, label: str, *, revision: bool = False) -> str:
    pattern = REVISION_RE if revision else ID_RE
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, f"invalid {label}")
    return value


def sha256(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def timestamp(value: Any, label: str) -> str:
    raw = text(value, label)
    require(raw.endswith("Z"), f"{label} must be UTC and end in Z")
    try:
        datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise KnowledgeError(f"invalid {label}") from exc
    return raw


def validate_object_ref(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    exact_keys(value, {"sha256", "size_bytes", "media_type", "original_name"}, label)
    sha256(value["sha256"], f"{label}.sha256")
    require(isinstance(value["size_bytes"], int) and value["size_bytes"] >= 0, f"{label}.size_bytes must be non-negative")
    text(value["media_type"], f"{label}.media_type")
    text(value["original_name"], f"{label}.original_name")
    require(Path(value["original_name"]).name == value["original_name"], f"{label}.original_name must be a basename")


def validate_ref(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    exact_keys(value, {"record_type", "logical_id", "revision_id", "payload_sha256"}, label)
    require(value["record_type"] in RECORD_TYPES, f"{label}.record_type is invalid")
    identifier(value["logical_id"], f"{label}.logical_id")
    identifier(value["revision_id"], f"{label}.revision_id", revision=True)
    sha256(value["payload_sha256"], f"{label}.payload_sha256")


def validate_artifact_ref(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    exact_keys(value, {"path", "sha256", "payload_sha256"}, label)
    text(value["path"], f"{label}.path")
    sha256(value["sha256"], f"{label}.sha256")
    sha256(value["payload_sha256"], f"{label}.payload_sha256")


def validate_access(value: Any, label: str) -> None:
    require(isinstance(value, dict), f"{label} must be an object")
    exact_keys(value, {"class", "project_ids", "license", "storage_status"}, label)
    require(value["class"] in ACCESS_CLASSES, f"{label}.class is invalid")
    projects = string_list(value["project_ids"], f"{label}.project_ids")
    if value["class"] == "project_restricted":
        require(bool(projects), f"{label}.project_ids is required for project_restricted")
    else:
        require(not projects, f"{label}.project_ids is only valid for project_restricted")
    text(value["license"], f"{label}.license")
    require(value["storage_status"] in {"metadata_only", "lawful_local_object", "public_redistributable"}, f"{label}.storage_status is invalid")


def validate_provenance(value: Any, label: str) -> None:
    require(isinstance(value, list) and value, f"{label} must be a non-empty array")
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        require(isinstance(item, dict), f"{item_label} must be an object")
        exact_keys(item, {"kind", "source", "locator", "sha256"}, item_label)
        text(item["kind"], f"{item_label}.kind")
        text(item["source"], f"{item_label}.source")
        text(item["locator"], f"{item_label}.locator")
        if item["sha256"] is not None:
            sha256(item["sha256"], f"{item_label}.sha256")


def validate_common(record: dict[str, Any]) -> str:
    exact_keys(record, COMMON_KEYS, "record")
    schema = text(record["schema"], "schema")
    require(schema in SCHEMA_TO_TYPE, "unknown record schema")
    record_type = text(record["record_type"], "record_type")
    require(record_type == SCHEMA_TO_TYPE[schema], "record_type does not match schema")
    logical_id = identifier(record["logical_id"], "logical_id")
    revision_id = identifier(record["revision_id"], "revision_id", revision=True)
    require(revision_id.startswith(logical_id + "_r"), "revision_id must be derived from logical_id")
    require(isinstance(record["revision"], int) and record["revision"] > 0, "revision must be a positive integer")
    require(revision_id.endswith(f"_r{record['revision']:03d}"), "revision_id and revision disagree")
    timestamp(record["created_at"], "created_at")
    text(record["created_by"], "created_by")
    require(record["review_status"] in REVIEW_STATUSES, "review_status is invalid")
    if record["review_status"] in SNAPSHOT_REVIEW_STATUSES:
        text(record["reviewed_by"], "reviewed_by")
        timestamp(record["reviewed_at"], "reviewed_at")
    else:
        optional_text(record["reviewed_by"], "reviewed_by")
        if record["reviewed_at"] is not None:
            timestamp(record["reviewed_at"], "reviewed_at")
    string_list(record["review_notes"], "review_notes")
    validate_access(record["access"], "access")
    validate_provenance(record["provenance"], "provenance")
    string_list(record["aliases"], "aliases")
    external = record["external_identifiers"]
    require(isinstance(external, list), "external_identifiers must be an array")
    for index, item in enumerate(external):
        label = f"external_identifiers[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"scheme", "value"}, label)
        text(item["scheme"], f"{label}.scheme")
        text(item["value"], f"{label}.value")
    string_list(record["uncertainties"], "uncertainties")
    string_list(record["blockers"], "blockers")
    if record["supersedes"] is not None:
        identifier(record["supersedes"], "supersedes", revision=True)
        require(record["revision"] > 1, "a first revision cannot supersede another revision")
    if record["revision"] > 1:
        require(record["supersedes"] is not None, "a later revision must explicitly supersede an older revision")
    string_list(record["link_ids"], "link_ids")
    require(isinstance(record["data"], dict), "data must be an object")
    require(record["calculation_ready"] is False, "knowledge records must set calculation_ready to false")
    require(record["no_submission_authorization"] is True, "knowledge records must deny submission authorization")
    sha256(record["payload_sha256"], "payload_sha256")
    require(record["payload_sha256"] == payload_sha256(record), "payload_sha256 mismatch")
    return record_type


def validate_structure(data: dict[str, Any], reviewed: bool) -> None:
    expected = {
        "preferred_name", "identity_id", "state_id", "roles", "formula",
        "formal_charge", "multiplicity", "component_count", "protonation",
        "salt_or_solvate", "stereochemistry", "coordination_state",
        "representations", "ownership",
    }
    exact_keys(data, expected, "structure.data")
    text(data["preferred_name"], "structure.data.preferred_name")
    identifier(data["identity_id"], "structure.data.identity_id")
    identifier(data["state_id"], "structure.data.state_id")
    require(data["state_id"] != data["identity_id"], "structure state_id must remain distinct from identity_id")
    roles = string_list(data["roles"], "structure.data.roles")
    require(bool(roles), "structure.data.roles must not be empty")
    text(data["formula"], "structure.data.formula")
    require(isinstance(data["formal_charge"], int) and not isinstance(data["formal_charge"], bool), "formal_charge must be an integer")
    require(isinstance(data["multiplicity"], int) and data["multiplicity"] > 0, "multiplicity must be positive")
    require(isinstance(data["component_count"], int) and data["component_count"] > 0, "component_count must be positive")
    for key in ("protonation", "salt_or_solvate", "stereochemistry"):
        text(data[key], f"structure.data.{key}")
    optional_text(data["coordination_state"], "structure.data.coordination_state")
    reps = data["representations"]
    require(isinstance(reps, list), "structure.data.representations must be an array")
    if reviewed:
        require(bool(reps), "reviewed structure requires a hashed representation")
    for index, item in enumerate(reps):
        label = f"structure.data.representations[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"format", "object", "atom_order_sha256", "review_scope", "geometry_provenance", "limitations"}, label)
        require(item["format"] in {"cdx", "cdxml", "mol", "sdf", "smiles", "inchi", "xyz", "gjf_geometry", "png", "svg"}, f"{label}.format is invalid")
        validate_object_ref(item["object"], f"{label}.object")
        if item["atom_order_sha256"] is not None:
            sha256(item["atom_order_sha256"], f"{label}.atom_order_sha256")
        text(item["review_scope"], f"{label}.review_scope")
        text(item["geometry_provenance"], f"{label}.geometry_provenance")
        string_list(item["limitations"], f"{label}.limitations")
    require(isinstance(data["ownership"], dict), "structure.data.ownership must be an object")
    exact_keys(data["ownership"], {"owner", "project", "sample_reference"}, "structure.data.ownership")
    text(data["ownership"]["owner"], "structure.data.ownership.owner")
    optional_text(data["ownership"]["project"], "structure.data.ownership.project")
    optional_text(data["ownership"]["sample_reference"], "structure.data.ownership.sample_reference")


def validate_method(data: dict[str, Any], reviewed: bool) -> None:
    expected = {
        "name", "classification", "program", "program_version",
        "calculation_family", "protocol", "basis_by_element", "scope",
        "benchmarks", "failure_modes",
    }
    exact_keys(data, expected, "method.data")
    text(data["name"], "method.data.name")
    require(data["classification"] in METHOD_CLASSES, "method.data.classification is invalid")
    text(data["program"], "method.data.program")
    text(data["program_version"], "method.data.program_version")
    text(data["calculation_family"], "method.data.calculation_family")
    protocol_keys = {
        "functional", "dispersion", "solvent_model", "relativistic_treatment",
        "grid", "scf", "optimization", "frequency", "ts", "irc",
        "single_point_relationship", "thermochemistry",
    }
    protocol = data["protocol"]
    require(isinstance(protocol, dict), "method.data.protocol must be an object")
    exact_keys(protocol, protocol_keys, "method.data.protocol")
    for key in sorted(protocol_keys):
        optional_text(protocol[key], f"method.data.protocol.{key}")
    basis = data["basis_by_element"]
    require(isinstance(basis, dict), "method.data.basis_by_element must be an object")
    for element, definition in basis.items():
        require(re.fullmatch(r"[A-Z][a-z]?", element) is not None, f"invalid basis element: {element}")
        text(definition, f"method.data.basis_by_element.{element}")
    scope = data["scope"]
    require(isinstance(scope, dict), "method.data.scope must be an object")
    exact_keys(scope, {"elements", "catalyst_classes", "reaction_classes", "state_types", "job_stages", "exclusions"}, "method.data.scope")
    elements = string_list(scope["elements"], "method.data.scope.elements")
    for key in ("catalyst_classes", "reaction_classes", "state_types", "job_stages", "exclusions"):
        string_list(scope[key], f"method.data.scope.{key}")
    if reviewed:
        require(bool(elements), "reviewed method requires explicit element scope")
        require(set(elements) <= set(basis), "reviewed method lacks complete per-element basis/ECP coverage")
        required_protocol = {"functional", "grid", "scf", "optimization", "frequency", "thermochemistry"}
        require(all(protocol[key] is not None for key in required_protocol), "reviewed method has an incomplete protocol")
    require(isinstance(data["benchmarks"], list), "method.data.benchmarks must be an array")
    for index, item in enumerate(data["benchmarks"]):
        require(isinstance(item, dict), f"method.data.benchmarks[{index}] must be an object")
        exact_keys(item, {"case", "result", "evidence_revision_id"}, f"method.data.benchmarks[{index}]")
        text(item["case"], f"method.data.benchmarks[{index}].case")
        text(item["result"], f"method.data.benchmarks[{index}].result")
        identifier(item["evidence_revision_id"], f"method.data.benchmarks[{index}].evidence_revision_id", revision=True)
    string_list(data["failure_modes"], "method.data.failure_modes")


def validate_source(data: dict[str, Any], reviewed: bool) -> None:
    expected = {
        "source_type", "title", "authors_or_editors", "year", "publisher",
        "journal_or_book", "volume", "issue", "edition", "chapter",
        "pages_or_article", "identifiers", "stable_url", "accessed_at",
        "anchors", "relationships", "local_objects", "extracted_claims",
    }
    exact_keys(data, expected, "source.data")
    require(data["source_type"] in SOURCE_TYPES, "source.data.source_type is invalid")
    text(data["title"], "source.data.title")
    require(bool(string_list(data["authors_or_editors"], "source.data.authors_or_editors")), "source requires authors or editors")
    require(isinstance(data["year"], int) and 1400 <= data["year"] <= 2200, "source.data.year is invalid")
    for key in ("publisher", "journal_or_book", "volume", "issue", "edition", "chapter", "pages_or_article", "stable_url"):
        optional_text(data[key], f"source.data.{key}")
    identifiers_value = data["identifiers"]
    require(isinstance(identifiers_value, list), "source.data.identifiers must be an array")
    for index, item in enumerate(identifiers_value):
        label = f"source.data.identifiers[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"scheme", "value"}, label)
        scheme = text(item["scheme"], f"{label}.scheme").lower()
        identifier_value = text(item["value"], f"{label}.value")
        if scheme == "doi":
            require(DOI_RE.fullmatch(identifier_value) is not None, f"{label}.value is not a DOI")
    timestamp(data["accessed_at"], "source.data.accessed_at")
    anchors = data["anchors"]
    require(isinstance(anchors, list), "source.data.anchors must be an array")
    for index, item in enumerate(anchors):
        label = f"source.data.anchors[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"kind", "locator"}, label)
        text(item["kind"], f"{label}.kind")
        text(item["locator"], f"{label}.locator")
    if reviewed and data["source_type"] in {"book", "book_chapter"}:
        require(data["edition"] is not None, "reviewed book source requires an edition")
        require(any(item["kind"] in {"page", "chapter"} for item in anchors), "reviewed book source requires a page or chapter anchor")
    relationships = data["relationships"]
    require(isinstance(relationships, list), "source.data.relationships must be an array")
    for index, item in enumerate(relationships):
        label = f"source.data.relationships[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"relation", "target_revision_id"}, label)
        text(item["relation"], f"{label}.relation")
        identifier(item["target_revision_id"], f"{label}.target_revision_id", revision=True)
    if reviewed and data["source_type"] == "supporting_information":
        require(any(item["relation"] == "supplement_to" for item in relationships), "reviewed SI requires a supplement_to relationship")
    require(isinstance(data["local_objects"], list), "source.data.local_objects must be an array")
    for index, item in enumerate(data["local_objects"]):
        validate_object_ref(item, f"source.data.local_objects[{index}]")
    claims = data["extracted_claims"]
    require(isinstance(claims, list), "source.data.extracted_claims must be an array")
    for index, item in enumerate(claims):
        label = f"source.data.extracted_claims[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"claim_type", "paraphrase", "anchor", "reviewer_interpretation", "status"}, label)
        text(item["claim_type"], f"{label}.claim_type")
        text(item["paraphrase"], f"{label}.paraphrase")
        text(item["anchor"], f"{label}.anchor")
        text(item["reviewer_interpretation"], f"{label}.reviewer_interpretation")
        require(item["status"] in {"source_reports", "not_found", "source_ambiguous"}, f"{label}.status is invalid")


def validate_link(data: dict[str, Any]) -> None:
    exact_keys(data, {"link_type", "source", "target", "evidence_mode", "anchors", "scope", "uncertainty", "mismatches"}, "link.data")
    require(data["link_type"] in LINK_TYPES, "link.data.link_type is invalid")
    validate_ref(data["source"], "link.data.source")
    validate_ref(data["target"], "link.data.target")
    require(data["source"] != data["target"], "knowledge link cannot be self-referential")
    require(data["evidence_mode"] in EVIDENCE_MODES, "link.data.evidence_mode is invalid")
    require(bool(string_list(data["anchors"], "link.data.anchors")), "link requires an exact evidence anchor")
    text(data["scope"], "link.data.scope")
    text(data["uncertainty"], "link.data.uncertainty")
    string_list(data["mismatches"], "link.data.mismatches")


def validate_snapshot(data: dict[str, Any]) -> None:
    exact_keys(data, {"study_id", "parent_reaction_intake", "database_fingerprint", "queries", "records", "redactions", "unresolved_gaps", "contradictions"}, "snapshot.data")
    identifier(data["study_id"], "snapshot.data.study_id")
    validate_artifact_ref(data["parent_reaction_intake"], "snapshot.data.parent_reaction_intake")
    sha256(data["database_fingerprint"], "snapshot.data.database_fingerprint")
    queries = data["queries"]
    require(isinstance(queries, list) and queries, "snapshot.data.queries must be a non-empty array")
    for index, item in enumerate(queries):
        label = f"snapshot.data.queries[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"registry", "query", "selected_revision_ids", "excluded_decisions"}, label)
        require(item["registry"] in RECORD_TYPES - {"snapshot"}, f"{label}.registry is invalid")
        text(item["query"], f"{label}.query")
        string_list(item["selected_revision_ids"], f"{label}.selected_revision_ids")
        require(isinstance(item["excluded_decisions"], list), f"{label}.excluded_decisions must be an array")
        for decision_index, decision in enumerate(item["excluded_decisions"]):
            dlabel = f"{label}.excluded_decisions[{decision_index}]"
            require(isinstance(decision, dict), f"{dlabel} must be an object")
            exact_keys(decision, {"revision_id", "reason"}, dlabel)
            identifier(decision["revision_id"], f"{dlabel}.revision_id", revision=True)
            text(decision["reason"], f"{dlabel}.reason")
    records = data["records"]
    require(isinstance(records, list) and records, "snapshot.data.records must be a non-empty array")
    for index, item in enumerate(records):
        validate_ref(item, f"snapshot.data.records[{index}]")
        require(item["record_type"] != "snapshot", "a snapshot cannot include another snapshot")
    require(len({item["revision_id"] for item in records}) == len(records), "snapshot records must be unique")
    string_list(data["redactions"], "snapshot.data.redactions")
    string_list(data["unresolved_gaps"], "snapshot.data.unresolved_gaps")
    string_list(data["contradictions"], "snapshot.data.contradictions")


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    record_type = validate_common(record)
    reviewed = record["review_status"] in SNAPSHOT_REVIEW_STATUSES
    if record_type == "structure":
        validate_structure(record["data"], reviewed)
    elif record_type == "method":
        validate_method(record["data"], reviewed)
    elif record_type == "source":
        validate_source(record["data"], reviewed)
    elif record_type == "link":
        validate_link(record["data"])
    elif record_type == "snapshot":
        validate_snapshot(record["data"])
    return record


def finalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Finalize an authored record draft without weakening any semantic gate."""
    value = copy.deepcopy(draft)
    value["calculation_ready"] = False
    value["no_submission_authorization"] = True
    value["payload_sha256"] = ""
    final = finalize_record(value)
    return validate_record(final)


def record_ref(record: dict[str, Any]) -> dict[str, str]:
    return {
        "record_type": record["record_type"],
        "logical_id": record["logical_id"],
        "revision_id": record["revision_id"],
        "payload_sha256": record["payload_sha256"],
    }


def ensure_store(store: Path, *, create: bool = False) -> Path:
    if create:
        require(not store.exists(), f"refusing to overwrite existing store: {store}")
        store.mkdir(parents=True, mode=0o700)
        (store / "records").mkdir(mode=0o700)
        (store / "objects" / "sha256").mkdir(parents=True, mode=0o700)
        (store / "objects" / "metadata").mkdir(parents=True, mode=0o700)
        write_new(
            store / "store.json",
            {
                "schema": "auto-g16-knowledge-store/1",
                "canonical_source": "immutable_json_and_content_addressed_objects",
                "sqlite_is_rebuildable_cache": True,
                "no_submission_authorization": True,
            },
        )
        (store / "store.json").chmod(0o600)
    require(store.is_dir() and not store.is_symlink(), f"knowledge store is missing or unsafe: {store}")
    resolved = store.resolve()
    require((resolved / "store.json").is_file(), f"knowledge store metadata is missing: {store}")
    return resolved


def record_path(store: Path, record: dict[str, Any]) -> Path:
    return store / "records" / record["record_type"] / record["logical_id"] / f"{record['revision_id']}.json"


def iter_record_paths(store: Path) -> Iterable[Path]:
    records = store / "records"
    if not records.exists():
        return []
    return sorted(path for path in records.rglob("*.json") if path.is_file() and not path.is_symlink())


def load_store_records(store: Path) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in iter_record_paths(store):
        value = validate_record(load_json(path))
        expected = record_path(store, value)
        require(path.resolve() == expected.resolve(), f"record is stored at a non-canonical path: {path}")
        result.append((path, value))
    revision_ids = [value["revision_id"] for _, value in result]
    require(len(revision_ids) == len(set(revision_ids)), "duplicate revision IDs in store")
    return result


def fingerprint(records: Iterable[dict[str, Any]]) -> str:
    bindings = sorted((item["revision_id"], item["payload_sha256"]) for item in records)
    return sha256_bytes(canonical_bytes(bindings))


def compatible_access(record: dict[str, Any], grants: set[str], project_ids: set[str]) -> bool:
    access = record["access"]
    if access["class"] not in grants:
        return False
    if access["class"] == "project_restricted":
        return bool(project_ids & set(access["project_ids"]))
    return True


def conflict_reasons(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for item in existing:
        if item["revision_id"] == candidate["revision_id"]:
            reasons.append("exact_duplicate" if item["payload_sha256"] == candidate["payload_sha256"] else "revision_id_conflict")
        if item["logical_id"] == candidate["logical_id"] and item["revision"] == candidate["revision"] and item["revision_id"] != candidate["revision_id"]:
            reasons.append("logical_revision_conflict")
        if item["record_type"] == candidate["record_type"] == "structure":
            left, right = item["data"], candidate["data"]
            if (left["identity_id"], left["state_id"]) == (right["identity_id"], right["state_id"]) and item["logical_id"] != candidate["logical_id"]:
                reasons.append("structure_identity_state_duplicate")
        if item["record_type"] == candidate["record_type"] == "source":
            def dois(record: dict[str, Any]) -> set[str]:
                return {entry["value"].lower() for entry in record["data"]["identifiers"] if entry["scheme"].lower() == "doi"}
            if dois(item) & dois(candidate) and item["logical_id"] != candidate["logical_id"]:
                reasons.append("source_doi_duplicate")
    return sorted(set(reasons))


def commit_record(store: Path, record: dict[str, Any]) -> Path:
    path = record_path(store, record)
    require(not path.exists(), f"refusing to overwrite existing record: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(record))
    path.chmod(0o600)
    return path


def validate_manifest_hash(value: dict[str, Any], label: str) -> None:
    sha256(value.get("payload_sha256"), f"{label}.payload_sha256")
    require(value["payload_sha256"] == payload_sha256(value), f"{label} payload SHA-256 mismatch")


def import_records(
    store: Path,
    inputs: list[Path],
    report: Path,
    *,
    commit: bool,
    approved_dry_run: Path | None = None,
) -> dict[str, Any]:
    store = ensure_store(store)
    require(not report.exists(), f"refusing to overwrite existing artifact: {report}")
    existing = [value for _, value in load_store_records(store)]
    candidates = [validate_record(load_json(path)) for path in inputs]
    require(len({item["revision_id"] for item in candidates}) == len(candidates), "import batch contains duplicate revision IDs")
    store_fingerprint_before = fingerprint(existing)
    candidate_fingerprint = fingerprint(candidates)
    results: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for input_path, candidate in zip(inputs, candidates):
        reasons = conflict_reasons(candidate, existing + accepted)
        blocking = [reason for reason in reasons if reason != "exact_duplicate"]
        action = "refuse_conflict" if blocking else ("skip_exact_duplicate" if reasons else ("commit_new_revision" if commit else "would_add_new_revision"))
        results.append({
            "input": str(input_path),
            "revision_id": candidate["revision_id"],
            "payload_sha256": candidate["payload_sha256"],
            "action": action,
            "conflicts": reasons,
        })
        if not reasons:
            accepted.append(candidate)
    has_conflicts = any(item["action"] == "refuse_conflict" for item in results)
    if commit:
        require(approved_dry_run is not None, "commit requires --approved-dry-run from a reviewed dry run")
        approved = load_json(approved_dry_run)
        require(approved.get("schema") == "auto-g16-knowledge-import-manifest/1", "approved dry run has the wrong schema")
        require(approved.get("mode") == "dry_run", "approved import manifest is not a dry run")
        validate_manifest_hash(approved, "approved dry run")
        require(approved.get("store") == str(store), "approved dry run targets a different store")
        require(approved.get("store_fingerprint_before") == store_fingerprint_before, "canonical store changed after dry run")
        require(approved.get("candidate_fingerprint") == candidate_fingerprint, "import candidates changed after dry run")
        approved_results = approved.get("results")
        require(isinstance(approved_results, list) and all(isinstance(item, dict) for item in approved_results), "approved dry run results are invalid")
        require(not any(item.get("action") == "refuse_conflict" for item in approved_results), "approved dry run contains unresolved conflicts")
    committed_paths: list[str] = []
    if commit and not has_conflicts:
        for candidate in accepted:
            committed_paths.append(str(commit_record(store, candidate).relative_to(store)))
    result = {
        "schema": "auto-g16-knowledge-import-manifest/1",
        "mode": "commit" if commit else "dry_run",
        "store": str(store),
        "store_fingerprint_before": store_fingerprint_before,
        "candidate_fingerprint": candidate_fingerprint,
        "results": results,
        "committed_paths": committed_paths,
        "requires_scientific_review": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "payload_sha256": "",
    }
    result["payload_sha256"] = payload_sha256(result)
    write_new(report, result)
    require(not has_conflicts, f"import refused because conflicts require review; see {report}")
    return result


def object_path(store: Path, digest: str) -> Path:
    return store / "objects" / "sha256" / digest[:2] / digest


def object_metadata_path(store: Path, digest: str) -> Path:
    return store / "objects" / "metadata" / digest[:2] / f"{digest}.json"


def import_object(
    store: Path,
    source: Path,
    report: Path,
    *,
    media_type: str,
    license_name: str,
    access_class: str,
    storage_status: str,
    project_ids: list[str],
    commit: bool,
    approved_dry_run: Path | None = None,
) -> dict[str, Any]:
    store = ensure_store(store)
    require(not report.exists(), f"refusing to overwrite existing artifact: {report}")
    require(source.is_file() and not source.is_symlink(), f"object source is missing or a symlink: {source}")
    access = {
        "class": access_class,
        "project_ids": project_ids,
        "license": license_name,
        "storage_status": storage_status,
    }
    validate_access(access, "object import access")
    require(storage_status in {"lawful_local_object", "public_redistributable"}, "object import requires an affirmative lawful storage status")
    digest = sha256_file(source)
    target = object_path(store, digest)
    metadata_target = object_metadata_path(store, digest)
    target_present_before = target.exists()
    metadata_present_before = metadata_target.exists()
    require(target_present_before == metadata_present_before, "object and immutable metadata presence disagree")
    reference = {
        "sha256": digest,
        "size_bytes": source.stat().st_size,
        "media_type": text(media_type, "media_type"),
        "original_name": source.name,
    }
    object_metadata = {
        "schema": "auto-g16-content-object-metadata/1",
        "object": reference,
        "access": access,
        "no_submission_authorization": True,
        "payload_sha256": "",
    }
    object_metadata["payload_sha256"] = payload_sha256(object_metadata)
    if commit:
        require(approved_dry_run is not None, "object commit requires --approved-dry-run from a reviewed dry run")
        approved = load_json(approved_dry_run)
        require(approved.get("schema") == "auto-g16-content-object-import/1", "approved object dry run has the wrong schema")
        require(approved.get("mode") == "dry_run", "approved object manifest is not a dry run")
        validate_manifest_hash(approved, "approved object dry run")
        require(approved.get("store") == str(store), "approved object dry run targets a different store")
        require(approved.get("object") == reference, "object changed after dry run")
        require(approved.get("access") == access, "object access policy changed after dry run")
        require(approved.get("target_present_before") == target_present_before, "object store changed after dry run")
        require(approved.get("metadata_present_before") == metadata_present_before, "object metadata store changed after dry run")
    status = "already_present" if target.exists() else ("committed" if commit else "would_commit")
    if target.exists():
        require(target.is_file() and not target.is_symlink(), "content-addressed object path is unsafe")
        require(sha256_file(target) == digest, "content-addressed object hash mismatch")
        require(metadata_target.is_file() and not metadata_target.is_symlink(), "content-addressed object metadata is missing or unsafe")
        require(load_json(metadata_target) == object_metadata, "content-addressed object metadata conflict requires review")
    elif commit:
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.exists(), f"refusing to overwrite object: {target}")
        shutil.copyfile(source, target)
        target.chmod(0o600)
        require(sha256_file(target) == digest, "copied object hash mismatch")
        write_new(metadata_target, object_metadata)
        metadata_target.chmod(0o600)
    result = {
        "schema": "auto-g16-content-object-import/1",
        "mode": "commit" if commit else "dry_run",
        "status": status,
        "store": str(store),
        "object": reference,
        "access": access,
        "target_present_before": target_present_before,
        "metadata_present_before": metadata_present_before,
        "store_path": str(target.relative_to(store)),
        "metadata_path": str(metadata_target.relative_to(store)),
        "no_submission_authorization": True,
        "payload_sha256": "",
    }
    result["payload_sha256"] = payload_sha256(result)
    write_new(report, result)
    return result


MIGRATIONS = (
    """
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE records (
      revision_id TEXT PRIMARY KEY,
      logical_id TEXT NOT NULL,
      revision INTEGER NOT NULL,
      record_type TEXT NOT NULL,
      schema_name TEXT NOT NULL,
      payload_sha256 TEXT NOT NULL,
      review_status TEXT NOT NULL,
      access_class TEXT NOT NULL,
      project_ids_json TEXT NOT NULL,
      preferred_label TEXT NOT NULL,
      searchable_text TEXT NOT NULL,
      canonical_json TEXT NOT NULL
    );
    CREATE INDEX records_logical_revision ON records(logical_id, revision);
    CREATE INDEX records_type_review_access ON records(record_type, review_status, access_class);
    CREATE TABLE aliases (revision_id TEXT NOT NULL, alias TEXT NOT NULL, PRIMARY KEY(revision_id, alias));
    CREATE TABLE external_identifiers (revision_id TEXT NOT NULL, scheme TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(revision_id, scheme, value));
    CREATE TABLE links (revision_id TEXT PRIMARY KEY, link_type TEXT NOT NULL, source_revision_id TEXT NOT NULL, target_revision_id TEXT NOT NULL, evidence_mode TEXT NOT NULL);
    CREATE TABLE object_references (revision_id TEXT NOT NULL, sha256 TEXT NOT NULL, original_name TEXT NOT NULL, PRIMARY KEY(revision_id, sha256, original_name));
    """,
)


def preferred_label(record: dict[str, Any]) -> str:
    data = record["data"]
    if record["record_type"] == "structure":
        return data["preferred_name"]
    if record["record_type"] == "method":
        return data["name"]
    if record["record_type"] == "source":
        return data["title"]
    if record["record_type"] == "link":
        return data["link_type"]
    return data["study_id"]


def collect_objects(record: dict[str, Any]) -> list[dict[str, Any]]:
    if record["record_type"] == "structure":
        return [item["object"] for item in record["data"]["representations"]]
    if record["record_type"] == "source":
        return list(record["data"]["local_objects"])
    return []


def verify_store_relationships(store: Path, records: list[dict[str, Any]]) -> None:
    by_revision = {item["revision_id"]: item for item in records}
    for record in records:
        for link_id in record["link_ids"]:
            require(link_id in by_revision, f"declared link revision is missing: {link_id}")
            link = by_revision[link_id]
            require(link["record_type"] == "link", f"declared link ID is not a link record: {link_id}")
            endpoints = {link["data"]["source"]["revision_id"], link["data"]["target"]["revision_id"]}
            require(record["revision_id"] in endpoints, f"declared link does not bind its declaring record: {link_id}")
        if record["supersedes"] is not None:
            require(record["supersedes"] in by_revision, f"missing superseded revision: {record['supersedes']}")
            previous = by_revision[record["supersedes"]]
            require(previous["logical_id"] == record["logical_id"], "supersedes must preserve logical_id")
            require(previous["revision"] < record["revision"], "supersedes must point to an older revision")
        for obj in collect_objects(record):
            path = object_path(store, obj["sha256"])
            require(path.is_file() and not path.is_symlink(), f"referenced object is missing: {obj['sha256']}")
            require(path.stat().st_size == obj["size_bytes"] and sha256_file(path) == obj["sha256"], f"referenced object does not match: {obj['sha256']}")
            metadata_path = object_metadata_path(store, obj["sha256"])
            require(metadata_path.is_file() and not metadata_path.is_symlink(), f"referenced object metadata is missing: {obj['sha256']}")
            metadata = load_json(metadata_path)
            exact_keys(metadata, {"schema", "object", "access", "no_submission_authorization", "payload_sha256"}, "object metadata")
            require(metadata["schema"] == "auto-g16-content-object-metadata/1", "unsupported object metadata schema")
            validate_object_ref(metadata["object"], "object metadata.object")
            require(metadata["object"] == obj, f"referenced object metadata does not match record: {obj['sha256']}")
            validate_access(metadata["access"], "object metadata.access")
            require(metadata["no_submission_authorization"] is True, "object metadata must deny submission authorization")
            validate_manifest_hash(metadata, "object metadata")
            require(ACCESS_RANK[record["access"]["class"]] >= ACCESS_RANK[metadata["access"]["class"]], "record access is less restrictive than a referenced object")
            if record["access"]["class"] == metadata["access"]["class"] == "project_restricted":
                require(set(record["access"]["project_ids"]) <= set(metadata["access"]["project_ids"]), "record project access is broader than a referenced object")
        if record["record_type"] == "link":
            for side in ("source", "target"):
                ref = record["data"][side]
                require(ref["revision_id"] in by_revision, f"link {side} revision is missing")
                target = by_revision[ref["revision_id"]]
                require(record_ref(target) == ref, f"link {side} binding does not match canonical record")
                require(ACCESS_RANK[record["access"]["class"]] >= ACCESS_RANK[target["access"]["class"]], "link access is less restrictive than a bound record")
                if record["access"]["class"] == target["access"]["class"] == "project_restricted":
                    require(
                        set(record["access"]["project_ids"]) <= set(target["access"]["project_ids"]),
                        "link project access is broader than a bound record",
                    )


def rebuild_index(store: Path, index_path: Path) -> dict[str, Any]:
    store = ensure_store(store)
    require(not index_path.exists(), f"refusing to overwrite existing index: {index_path}")
    pairs = load_store_records(store)
    records = [item for _, item in pairs]
    verify_store_relationships(store, records)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA page_size=4096")
        for migration in MIGRATIONS:
            connection.executescript(migration)
        db_fingerprint = fingerprint(records)
        metadata = {
            "schema": "auto-g16-knowledge-sqlite-index/1",
            "migration_version": str(len(MIGRATIONS)),
            "database_fingerprint": db_fingerprint,
            "record_count": str(len(records)),
            "no_submission_authorization": "true",
        }
        connection.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", sorted(metadata.items()))
        for record in sorted(records, key=lambda item: item["revision_id"]):
            canonical = canonical_bytes(record).decode("utf-8").rstrip("\n")
            searchable = " ".join(
                [preferred_label(record), record["logical_id"], *record["aliases"], *(item["value"] for item in record["external_identifiers"])]
            ).casefold()
            connection.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["revision_id"], record["logical_id"], record["revision"], record["record_type"],
                    record["schema"], record["payload_sha256"], record["review_status"],
                    record["access"]["class"], json.dumps(record["access"]["project_ids"], separators=(",", ":")),
                    preferred_label(record), searchable, canonical,
                ),
            )
            connection.executemany("INSERT INTO aliases VALUES (?,?)", [(record["revision_id"], item) for item in sorted(record["aliases"])])
            connection.executemany(
                "INSERT INTO external_identifiers VALUES (?,?,?)",
                [(record["revision_id"], item["scheme"], item["value"]) for item in sorted(record["external_identifiers"], key=lambda item: (item["scheme"], item["value"]))],
            )
            if record["record_type"] == "link":
                connection.execute(
                    "INSERT INTO links VALUES (?,?,?,?,?)",
                    (record["revision_id"], record["data"]["link_type"], record["data"]["source"]["revision_id"], record["data"]["target"]["revision_id"], record["data"]["evidence_mode"]),
                )
            connection.executemany(
                "INSERT INTO object_references VALUES (?,?,?)",
                [(record["revision_id"], item["sha256"], item["original_name"]) for item in sorted(collect_objects(record), key=lambda item: (item["sha256"], item["original_name"]))],
            )
        connection.execute(f"PRAGMA user_version={len(MIGRATIONS)}")
        connection.commit()
        connection.execute("VACUUM")
        index_path.chmod(0o600)
    except Exception:
        connection.close()
        if index_path.exists():
            index_path.unlink()
        raise
    finally:
        if connection:
            connection.close()
    return {"record_count": len(records), "database_fingerprint": fingerprint(records), "index": str(index_path)}


def index_metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        values = dict(connection.execute("SELECT key,value FROM metadata"))
    except sqlite3.Error as exc:
        raise KnowledgeError(f"invalid knowledge index: {exc}") from exc
    require(values.get("schema") == "auto-g16-knowledge-sqlite-index/1", "unsupported knowledge index schema")
    required = {"migration_version", "database_fingerprint", "record_count", "no_submission_authorization"}
    require(required <= set(values), "knowledge index metadata is incomplete")
    sha256(values["database_fingerprint"], "index database_fingerprint")
    require(values["migration_version"].isdigit() and int(values["migration_version"]) > 0, "index migration_version is invalid")
    require(values["record_count"].isdigit(), "index record_count is invalid")
    require(values["no_submission_authorization"] == "true", "index must deny submission authorization")
    return values


def verify_index(store: Path, index_path: Path) -> dict[str, Any]:
    store = ensure_store(store)
    require(index_path.is_file() and not index_path.is_symlink(), f"index is missing or unsafe: {index_path}")
    records = [value for _, value in load_store_records(store)]
    verify_store_relationships(store, records)
    current = fingerprint(records)
    connection = sqlite3.connect(f"file:{index_path.resolve()}?mode=ro", uri=True)
    try:
        metadata = index_metadata(connection)
        indexed_count = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    finally:
        connection.close()
    require(metadata["database_fingerprint"] == current, "stale derived index: database fingerprint differs from canonical store")
    require(int(metadata["record_count"]) == len(records) == indexed_count, "stale derived index: record count differs from canonical store")
    return {
        "status": "current",
        "database_fingerprint": current,
        "record_count": len(records),
        "migration_version": metadata["migration_version"],
        "no_submission_authorization": True,
    }


def query_index(
    index_path: Path,
    output: Path,
    *,
    registry: str | None,
    query: str | None,
    statuses: set[str],
    grants: set[str],
    project_ids: set[str],
) -> dict[str, Any]:
    require(index_path.is_file() and not index_path.is_symlink(), f"index is missing or unsafe: {index_path}")
    require(grants <= set(ACCESS_CLASSES), "unknown access grant")
    require("public" in grants, "public grant must always be present")
    require(statuses <= REVIEW_STATUSES, "unknown review status")
    if registry is not None:
        require(registry in RECORD_TYPES, "unknown registry")
    connection = sqlite3.connect(f"file:{index_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata = index_metadata(connection)
        rows = connection.execute("SELECT * FROM records ORDER BY record_type, logical_id, revision").fetchall()
    finally:
        connection.close()
    results: list[dict[str, Any]] = []
    needle = query.casefold() if query else None
    for row in rows:
        if registry is not None and row["record_type"] != registry:
            continue
        if row["review_status"] not in statuses:
            continue
        access = row["access_class"]
        if access not in grants:
            continue
        projects = set(json.loads(row["project_ids_json"]))
        if access == "project_restricted" and not projects & project_ids:
            continue
        if needle is not None and needle not in row["searchable_text"]:
            continue
        results.append({
            "record_type": row["record_type"],
            "logical_id": row["logical_id"],
            "revision_id": row["revision_id"],
            "payload_sha256": row["payload_sha256"],
            "review_status": row["review_status"],
            "access_class": access,
            "preferred_label": row["preferred_label"],
        })
    result = {
        "schema": "auto-g16-knowledge-query-result/1",
        "database_fingerprint": metadata["database_fingerprint"],
        "query": query,
        "registry": registry,
        "review_statuses": sorted(statuses),
        "grants": sorted(grants),
        "project_ids": sorted(project_ids),
        "result_count": len(results),
        "results": results,
        "redaction_policy": "records outside explicit grants are omitted without revealing identifiers",
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    write_new(output, result)
    return result


def export_index(
    index_path: Path,
    output_dir: Path,
    *,
    registry: str | None,
    statuses: set[str],
    grants: set[str],
    project_ids: set[str],
) -> dict[str, Any]:
    """Export permission-filtered canonical JSON without exporting file objects."""
    require(index_path.is_file() and not index_path.is_symlink(), f"index is missing or unsafe: {index_path}")
    require(not output_dir.exists(), f"refusing to overwrite existing export directory: {output_dir}")
    require(grants <= set(ACCESS_CLASSES), "unknown access grant")
    require("public" in grants, "public grant must always be present")
    require(statuses <= REVIEW_STATUSES, "unknown review status")
    if registry is not None:
        require(registry in RECORD_TYPES, "unknown registry")
    connection = sqlite3.connect(f"file:{index_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata = index_metadata(connection)
        rows = connection.execute("SELECT * FROM records ORDER BY record_type, logical_id, revision").fetchall()
    finally:
        connection.close()
    selected: list[sqlite3.Row] = []
    for row in rows:
        if registry is not None and row["record_type"] != registry:
            continue
        if row["review_status"] not in statuses or row["access_class"] not in grants:
            continue
        projects = set(json.loads(row["project_ids_json"]))
        if row["access_class"] == "project_restricted" and not projects & project_ids:
            continue
        selected.append(row)
    output_dir.mkdir(parents=True)
    records_dir = output_dir / "records"
    records_dir.mkdir()
    exported: list[dict[str, Any]] = []
    for row in selected:
        record = json.loads(row["canonical_json"])
        validate_record(record)
        require(record["payload_sha256"] == row["payload_sha256"], "index canonical record hash mismatch")
        relative = Path("records") / row["record_type"] / f"{row['revision_id']}.json"
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_bytes(record))
        exported.append({
            "path": str(relative),
            "revision_id": row["revision_id"],
            "payload_sha256": row["payload_sha256"],
            "file_sha256": sha256_file(target),
        })
    manifest = {
        "schema": "auto-g16-knowledge-export-manifest/1",
        "database_fingerprint": metadata["database_fingerprint"],
        "registry": registry,
        "review_statuses": sorted(statuses),
        "grants": sorted(grants),
        "project_ids": sorted(project_ids),
        "record_count": len(exported),
        "records": exported,
        "content_objects_exported": False,
        "redaction_policy": "records outside explicit grants and all binary objects are omitted",
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    write_new(output_dir / "manifest.json", manifest)
    return manifest


def load_selection(path: Path) -> dict[str, Any]:
    value = load_json(path)
    expected = {"schema", "study_id", "parent_reaction_intake", "queries", "selected_revision_ids", "redactions", "unresolved_gaps", "contradictions", "author", "reviewer", "created_at", "review_status", "access"}
    exact_keys(value, expected, "snapshot selection")
    require(value["schema"] == "auto-g16-knowledge-snapshot-request/1", "unsupported snapshot request schema")
    identifier(value["study_id"], "snapshot request study_id")
    validate_artifact_ref(value["parent_reaction_intake"], "snapshot request parent_reaction_intake")
    require(isinstance(value["queries"], list) and value["queries"], "snapshot request queries must be non-empty")
    for index, item in enumerate(value["queries"]):
        label = f"snapshot request queries[{index}]"
        require(isinstance(item, dict), f"{label} must be an object")
        exact_keys(item, {"registry", "query", "selected_revision_ids", "excluded_decisions"}, label)
        require(item["registry"] in RECORD_TYPES - {"snapshot"}, f"{label}.registry is invalid")
        text(item["query"], f"{label}.query")
        string_list(item["selected_revision_ids"], f"{label}.selected_revision_ids")
        require(isinstance(item["excluded_decisions"], list), f"{label}.excluded_decisions must be an array")
        for decision in item["excluded_decisions"]:
            require(isinstance(decision, dict), f"{label} exclusion must be an object")
            exact_keys(decision, {"revision_id", "reason"}, f"{label} exclusion")
            identifier(decision["revision_id"], f"{label} exclusion revision_id", revision=True)
            text(decision["reason"], f"{label} exclusion reason")
    selected = string_list(value["selected_revision_ids"], "snapshot request selected_revision_ids")
    require(bool(selected), "snapshot request must select at least one revision")
    selected_from_queries = {item for query_item in value["queries"] for item in query_item["selected_revision_ids"]}
    require(set(selected) == selected_from_queries, "snapshot request selected revisions must exactly match query selections")
    for key in ("redactions", "unresolved_gaps", "contradictions"):
        string_list(value[key], f"snapshot request {key}")
    text(value["author"], "snapshot request author")
    text(value["reviewer"], "snapshot request reviewer")
    timestamp(value["created_at"], "snapshot request created_at")
    require(value["review_status"] in SNAPSHOT_REVIEW_STATUSES, "snapshot request must be reviewed")
    validate_access(value["access"], "snapshot request access")
    return value


def build_snapshot(store: Path, selection_path: Path, output: Path) -> dict[str, Any]:
    store = ensure_store(store)
    selection = load_selection(selection_path)
    parent_ref = selection["parent_reaction_intake"]
    parent_path = Path(parent_ref["path"])
    if not parent_path.is_absolute():
        parent_path = selection_path.parent / parent_path
    require(parent_path.is_file() and not parent_path.is_symlink(), f"parent reaction intake is missing or unsafe: {parent_path}")
    require(sha256_file(parent_path) == parent_ref["sha256"], "parent reaction intake file SHA-256 mismatch")
    parent_data = load_json(parent_path)
    require(parent_data.get("schema") == "gaussian-reaction-intake/1", "parent artifact is not a W1 reaction intake")
    require(parent_data.get("calculation_ready") is False, "parent reaction intake must not be calculation-ready")
    require(parent_data.get("no_submission_authorization") is True, "parent reaction intake must deny submission authorization")
    require(parent_data.get("payload_sha256") == parent_ref["payload_sha256"], "parent reaction intake payload SHA-256 mismatch")
    require(parent_data.get("payload_sha256") == payload_sha256(parent_data), "parent reaction intake canonical payload hash mismatch")
    all_records = [value for _, value in load_store_records(store)]
    verify_store_relationships(store, all_records)
    by_revision = {item["revision_id"]: item for item in all_records}
    selected: list[dict[str, Any]] = []
    for revision_id in selection["selected_revision_ids"]:
        require(revision_id in by_revision, f"selected revision does not exist: {revision_id}")
        record = by_revision[revision_id]
        require(record["review_status"] in SNAPSHOT_REVIEW_STATUSES, f"snapshot refuses unreviewed revision: {revision_id}")
        require(record["record_type"] != "snapshot", "snapshot cannot select another snapshot")
        selected.append(record)
    most_restrictive = max((ACCESS_RANK[item["access"]["class"]] for item in selected), default=0)
    require(ACCESS_RANK[selection["access"]["class"]] >= most_restrictive, "snapshot access is less restrictive than a selected record")
    if selection["access"]["class"] == "project_restricted":
        snapshot_projects = set(selection["access"]["project_ids"])
        for item in selected:
            if item["access"]["class"] == "project_restricted":
                require(snapshot_projects <= set(item["access"]["project_ids"]), "snapshot project access is broader than a selected record")
    logical_ids = [item["logical_id"] for item in selected]
    require(len(logical_ids) == len(set(logical_ids)), "snapshot must not select multiple revisions of one logical record")
    for query_item in selection["queries"]:
        for revision_id in query_item["selected_revision_ids"]:
            require(by_revision[revision_id]["record_type"] == query_item["registry"], f"query registry does not match selected revision: {revision_id}")
        selected_in_query = set(query_item["selected_revision_ids"])
        for decision in query_item["excluded_decisions"]:
            revision_id = decision["revision_id"]
            require(revision_id in by_revision, f"excluded revision does not exist: {revision_id}")
            require(by_revision[revision_id]["record_type"] == query_item["registry"], f"query registry does not match excluded revision: {revision_id}")
            require(revision_id not in selected_in_query, f"revision cannot be both selected and excluded: {revision_id}")
    logical_id = f"snapshot_{selection['study_id']}"
    record = {
        "schema": SCHEMAS["snapshot"],
        "record_type": "snapshot",
        "logical_id": logical_id,
        "revision_id": f"{logical_id}_r001",
        "revision": 1,
        "created_at": selection["created_at"],
        "created_by": selection["author"],
        "review_status": selection["review_status"],
        "reviewed_by": selection["reviewer"],
        "reviewed_at": selection["created_at"],
        "review_notes": ["Exact reviewed revisions selected; retrieval does not grant calculation authority."],
        "access": selection["access"],
        "provenance": [{"kind": "snapshot_request", "source": str(selection_path), "locator": "whole artifact", "sha256": sha256_file(selection_path)}],
        "aliases": [],
        "external_identifiers": [],
        "uncertainties": selection["unresolved_gaps"],
        "blockers": ["A knowledge snapshot is evidence only and cannot authorize protocol selection or calculation."],
        "supersedes": None,
        "link_ids": [item["revision_id"] for item in selected if item["record_type"] == "link"],
        "data": {
            "study_id": selection["study_id"],
            "parent_reaction_intake": selection["parent_reaction_intake"],
            "database_fingerprint": fingerprint(selected),
            "queries": selection["queries"],
            "records": [record_ref(item) for item in sorted(selected, key=lambda item: item["revision_id"])],
            "redactions": selection["redactions"],
            "unresolved_gaps": selection["unresolved_gaps"],
            "contradictions": selection["contradictions"],
        },
        "calculation_ready": False,
        "no_submission_authorization": True,
        "payload_sha256": "",
    }
    final = finalize_record(record)
    validate_record(final)
    write_new(output, final)
    return final


def verify_snapshot(store: Path, snapshot_path: Path) -> dict[str, Any]:
    store = ensure_store(store)
    snapshot = validate_record(load_json(snapshot_path))
    require(snapshot["record_type"] == "snapshot", "artifact is not a knowledge snapshot")
    by_revision = {item["revision_id"]: item for _, item in load_store_records(store)}
    selected: list[dict[str, Any]] = []
    for ref in snapshot["data"]["records"]:
        require(ref["revision_id"] in by_revision, f"snapshot dependency is missing: {ref['revision_id']}")
        record = by_revision[ref["revision_id"]]
        require(record_ref(record) == ref, f"snapshot dependency drift: {ref['revision_id']}")
        require(record["review_status"] in SNAPSHOT_REVIEW_STATUSES, f"snapshot dependency is no longer review-eligible: {ref['revision_id']}")
        selected.append(record)
    require(fingerprint(selected) == snapshot["data"]["database_fingerprint"], "snapshot database fingerprint mismatch")
    return {
        "status": "verified_immutable_snapshot",
        "snapshot_payload_sha256": snapshot["payload_sha256"],
        "selected_record_count": len(selected),
        "database_fingerprint": snapshot["data"]["database_fingerprint"],
        "calculation_ready": False,
        "no_submission_authorization": True,
    }


def command_validate(args: argparse.Namespace) -> None:
    record = validate_record(load_json(args.record))
    print(json.dumps({"status": "valid", "record": record_ref(record), "calculation_ready": False, "no_submission_authorization": True}, sort_keys=True))


def command_finalize(args: argparse.Namespace) -> None:
    record = finalize_draft(load_json(args.draft))
    write_new(args.output, record)
    print(json.dumps({"status": "finalized", "record": record_ref(record), "output": str(args.output)}, sort_keys=True))


def command_init(args: argparse.Namespace) -> None:
    store = ensure_store(args.store, create=True)
    print(json.dumps({"status": "created", "store": str(store)}))


def command_import(args: argparse.Namespace) -> None:
    result = import_records(
        args.store,
        args.records,
        args.report,
        commit=args.commit,
        approved_dry_run=args.approved_dry_run,
    )
    print(json.dumps({"mode": result["mode"], "result_count": len(result["results"]), "report": str(args.report)}))


def command_import_object(args: argparse.Namespace) -> None:
    result = import_object(
        args.store,
        args.source,
        args.report,
        media_type=args.media_type,
        license_name=args.license,
        access_class=args.access_class,
        storage_status=args.storage_status,
        project_ids=args.project_id,
        commit=args.commit,
        approved_dry_run=args.approved_dry_run,
    )
    print(json.dumps({"mode": result["mode"], "status": result["status"], "object": result["object"]}, sort_keys=True))


def command_rebuild(args: argparse.Namespace) -> None:
    print(json.dumps(rebuild_index(args.store, args.index), sort_keys=True))


def command_verify_index(args: argparse.Namespace) -> None:
    print(json.dumps(verify_index(args.store, args.index), sort_keys=True))


def command_query(args: argparse.Namespace) -> None:
    result = query_index(
        args.index,
        args.output,
        registry=args.registry,
        query=args.query,
        statuses=set(args.review_status or ["reviewed", "reviewed_with_limits"]),
        grants=set(args.grant or ["public"]),
        project_ids=set(args.project_id),
    )
    print(json.dumps({"result_count": result["result_count"], "output": str(args.output)}))


def command_export(args: argparse.Namespace) -> None:
    result = export_index(
        args.index,
        args.output_dir,
        registry=args.registry,
        statuses=set(args.review_status or ["reviewed", "reviewed_with_limits"]),
        grants=set(args.grant or ["public"]),
        project_ids=set(args.project_id),
    )
    print(json.dumps({"record_count": result["record_count"], "output_dir": str(args.output_dir)}))


def command_snapshot(args: argparse.Namespace) -> None:
    result = build_snapshot(args.store, args.selection, args.output)
    print(json.dumps({"snapshot": record_ref(result), "output": str(args.output)}, sort_keys=True))


def command_verify_snapshot(args: argparse.Namespace) -> None:
    print(json.dumps(verify_snapshot(args.store, args.snapshot), sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate one closed canonical record")
    validate.add_argument("record", type=Path)
    validate.set_defaults(func=command_validate)
    finalize = sub.add_parser("finalize", help="hash and validate one closed authored record draft")
    finalize.add_argument("draft", type=Path)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.set_defaults(func=command_finalize)
    init = sub.add_parser("init-store", help="create a new empty canonical store")
    init.add_argument("store", type=Path)
    init.set_defaults(func=command_init)
    importer = sub.add_parser("import", help="dry-run or commit canonical records")
    importer.add_argument("store", type=Path)
    importer.add_argument("records", type=Path, nargs="+")
    importer.add_argument("--report", type=Path, required=True)
    importer.add_argument("--commit", action="store_true", help="commit only after reviewing a prior dry-run report")
    importer.add_argument("--approved-dry-run", type=Path)
    importer.set_defaults(func=command_import)
    obj = sub.add_parser("import-object", help="dry-run or commit one lawful content-addressed object")
    obj.add_argument("store", type=Path)
    obj.add_argument("source", type=Path)
    obj.add_argument("--media-type", required=True)
    obj.add_argument("--license", required=True)
    obj.add_argument("--access-class", required=True, choices=ACCESS_CLASSES)
    obj.add_argument("--storage-status", required=True, choices=("lawful_local_object", "public_redistributable"))
    obj.add_argument("--project-id", action="append", default=[])
    obj.add_argument("--report", type=Path, required=True)
    obj.add_argument("--commit", action="store_true")
    obj.add_argument("--approved-dry-run", type=Path)
    obj.set_defaults(func=command_import_object)
    rebuild = sub.add_parser("rebuild", help="build a fresh deterministic SQLite index")
    rebuild.add_argument("store", type=Path)
    rebuild.add_argument("--index", type=Path, required=True)
    rebuild.set_defaults(func=command_rebuild)
    verify_index_parser = sub.add_parser("verify-index", help="detect drift between a canonical store and derived index")
    verify_index_parser.add_argument("store", type=Path)
    verify_index_parser.add_argument("index", type=Path)
    verify_index_parser.set_defaults(func=command_verify_index)
    query = sub.add_parser("query", help="query an index with fail-closed access grants")
    query.add_argument("index", type=Path)
    query.add_argument("--output", type=Path, required=True)
    query.add_argument("--registry", choices=sorted(RECORD_TYPES))
    query.add_argument("--query")
    query.add_argument("--review-status", action="append", choices=sorted(REVIEW_STATUSES))
    query.add_argument("--grant", action="append", choices=ACCESS_CLASSES)
    query.add_argument("--project-id", action="append", default=[])
    query.set_defaults(func=command_query)
    export = sub.add_parser("export", help="export permission-filtered canonical JSON records")
    export.add_argument("index", type=Path)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--registry", choices=sorted(RECORD_TYPES))
    export.add_argument("--review-status", action="append", choices=sorted(REVIEW_STATUSES))
    export.add_argument("--grant", action="append", choices=ACCESS_CLASSES)
    export.add_argument("--project-id", action="append", default=[])
    export.set_defaults(func=command_export)
    snapshot = sub.add_parser("snapshot", help="build an immutable reviewed study snapshot")
    snapshot.add_argument("store", type=Path)
    snapshot.add_argument("selection", type=Path)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.set_defaults(func=command_snapshot)
    verify = sub.add_parser("verify-snapshot", help="verify exact snapshot dependencies against a store")
    verify.add_argument("store", type=Path)
    verify.add_argument("snapshot", type=Path)
    verify.set_defaults(func=command_verify_snapshot)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except (KnowledgeError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
