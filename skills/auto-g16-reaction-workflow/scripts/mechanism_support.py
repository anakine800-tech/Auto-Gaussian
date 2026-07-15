#!/usr/bin/env python3
"""Build and validate immutable offline mechanism-support matrix sidecars.

The sidecar binds one exact finalized mechanism network, finalized literature
evidence, the W1 chain, and a reviewed knowledge snapshot.  It never rewrites
the network, infers chemistry, constructs a TS seed, selects a protocol, or
invokes a network, subprocess, Gaussian, SSH, PBS, or deployment action.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import mechanism_network as mn
import reaction_workflow as rw


SKILLS_DIR = Path(__file__).resolve().parents[2]
KB_SCRIPTS = SKILLS_DIR / "auto-g16-knowledge-base" / "scripts"
if str(KB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(KB_SCRIPTS))
import knowledge_base as kb  # noqa: E402  (repository-local offline validator)


REVIEW_SCHEMA = "gaussian-reaction-mechanism-support-review/1"
OUTPUT_SCHEMA = "gaussian-reaction-mechanism-support/1"
EVIDENCE_SCHEMA = "gaussian-reaction-literature-evidence/1"
LEDGER_SCHEMA = "gaussian-reaction-literature-candidate-ledger/1"
SNAPSHOT_SCHEMA = "auto-g16-knowledge-snapshot/1"

EVIDENCE_HASH_FIELD = "evidence_review_payload_sha256"
LEDGER_HASH_FIELD = "candidate_ledger_payload_sha256"
LITERATURE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

EVIDENCE_STATUSES = {
    "positive", "negative", "contradictory", "inaccessible", "incomplete",
    "rejected", "no_evidence",
}
CLAIM_RELATIONSHIPS = {"supports", "contradicts", "does_not_address", "unknown"}
DIRECTNESS_VALUES = {"direct", "analogous", "unknown", "not_applicable"}
EVIDENCE_BASES = {"experimental", "computational", "mixed", "unknown", "not_applicable"}
APPLICABILITY_VALUES = {"exact", "close", "remote", "contradictory", "unknown", "not_applicable"}
APPLICABILITY_DIMENSIONS = (
    "net_transformation",
    "elementary_step_and_atom_correspondence",
    "substrate_electronics_sterics_and_groups",
    "catalyst_and_active_state",
    "atom_inventory_charge_multiplicity_and_spin",
    "coordination_ion_pair_additives_and_solvent",
    "stereochemical_channel",
    "experimental_conditions",
    "computational_protocol_and_validation",
)
BOUNDED_USES = {
    "discovery_only", "mechanism_support", "ts_topology_support",
    "geometry_seed_support", "protocol_candidate_support",
    "not_applicable_to_target",
}
SUPPORT_BOUNDED_USES = {
    "discovery_only", "mechanism_support", "not_applicable_to_target",
}
PROMOTION_DECISIONS = {
    "accepted_for_mechanism_support", "retained_without_promotion", "rejected", "blocked",
}
CELL_DECISIONS = {
    "include_support", "include_contradiction", "retain_negative",
    "retain_inaccessible", "retain_incomplete", "reject", "record_no_evidence",
}
ROW_DISPOSITIONS = {"mandatory", "optional", "contradicted", "unresolved"}
CONFIDENCE_VALUES = {"high", "moderate", "low", "unknown", "not_applicable"}
BLOCKER_CODES = {
    "no_exact_precedent_found",
    "search_access_incomplete",
    "primary_source_unavailable",
    "supporting_information_missing",
    "computational_details_incomplete",
    "coordinates_unavailable",
    "atom_mapping_ambiguous",
    "analogy_too_remote",
    "contradictory_evidence",
    "reported_ts_not_path_validated",
    "reported_method_not_transferable",
    "candidate_construction_blocked",
}
ACCESS_BLOCKERS = {
    "search_access_incomplete", "primary_source_unavailable", "supporting_information_missing",
}
INCOMPLETE_BLOCKERS = {
    "computational_details_incomplete", "coordinates_unavailable",
    "atom_mapping_ambiguous", "reported_ts_not_path_validated",
}
PRIMARY_SOURCE_TYPES = {
    "primary_article",
    "supporting_information",
    "correction_or_retraction_notice",
    "repository_author_manuscript",
    "dissertation_or_thesis",
}
LEDGER_TOP_KEYS = {
    "schema", "request_id", "created_at", "search_plan_artifact",
    "retrieval_artifact", "target_evidence", "upstream_artifacts",
    "w2_binding_status", "promotion_blockers", "counts", "ranking_policy",
    "candidates", "limitations", "calculation_ready",
    "promotable_to_mechanism_support", "promotable_to_ts_precedent_map",
    "no_submission_authorization", "candidate_ledger_payload_sha256",
}
LEDGER_CANDIDATE_KEYS = {
    "candidate_id", "deduplication_key", "doi", "title", "authors", "year",
    "venue", "url", "publication_type", "cited_by_count",
    "record_status_signals", "metadata_abstract_available",
    "discovery_observations", "lexical_score", "score_breakdown",
    "screening_tier", "screening_status", "directness",
}
SCORE_KEYS = {
    "exact_phrases", "catalyst_terms", "substrate_terms",
    "transformation_terms", "mechanism_terms", "exclusions",
    "evidence_title", "evidence_abstract",
}

REVIEW_KEYS = {
    "schema", "support_id", "study_id", "mechanism_network_payload_sha256",
    "intake_payload_sha256", "species_registry_payload_sha256",
    "condition_model_payload_sha256", "knowledge_snapshot_payload_sha256",
    "literature_evidence_payload_sha256", "evidence_gate_acknowledgement",
    "supersedes", "evidence_columns", "rows", "cells", "coverage",
    "row_promotion_reviews", "review_decision", "reviewed_by", "reviewed_at",
    "review_notes",
}
EVIDENCE_TOP_KEYS = {
    "schema", "request_id", "created_at", "record_status",
    "candidate_ledger_artifact", "upstream_artifacts", "w2_binding_status",
    "promotion_blockers", "allowed_evidence_statuses", "allowed_decisions",
    "allowed_applicability_values", "allowed_bounded_uses", "reviews",
    "calculation_ready", "promotable_to_mechanism_support",
    "promotable_to_ts_precedent_map", "no_submission_authorization",
    "evidence_review_payload_sha256", "validated_at",
}


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw._require_exact_keys(value, keys, keys, label)
    return value


def _string(value: Any, label: str) -> str:
    return rw._require_string(value, label)


def _unique_strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    items = rw._string_list(value, label, nonempty=nonempty)
    rw.require(len(items) == len(set(items)), f"{label} must not contain duplicates")
    return sorted(items)


def _timestamp(value: Any, label: str) -> str:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise rw.OfflineError(f"{label} must be an ISO-8601 timestamp") from exc
    rw.require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return text


def _literature_id(value: Any, label: str) -> str:
    rw.require(isinstance(value, str) and LITERATURE_ID_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _normalize_doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi if re.fullmatch(r"10\.\d{4,9}/\S+", doi) else None


def _normalize_search_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", value)
    for symbol, name in (
        ("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"),
        ("Α", "alpha"), ("Β", "beta"), ("Γ", "gamma"), ("Δ", "delta"),
    ):
        normalized = normalized.replace(symbol, name)
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    return " ".join(normalized.casefold().split())


def _validate_legacy_reference_shape(value: Any, label: str) -> dict[str, Any]:
    ref = _exact(value, {"path", "sha256"}, label)
    _string(ref["path"], f"{label}.path")
    rw.require(isinstance(ref["sha256"], str) and rw.SHA256_RE.fullmatch(ref["sha256"]) is not None, f"{label}.sha256 is invalid")
    return ref


def _resolve_path(raw: Any, owner: Path, label: str) -> Path:
    text = _string(raw, f"{label}.path")
    rw.require("://" not in text, f"{label}.path must be a local file")
    direct = Path(text)
    candidates = (direct, owner.parent / direct)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    rw.require(path is not None, f"{label} file is missing: {text}")
    assert path is not None
    rw.require(not path.is_symlink(), f"{label} file must not be a symlink: {path}")
    return path


def _literature_payload_hash(data: dict[str, Any], field: str) -> str:
    payload = copy.deepcopy(data)
    payload.pop(field, None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_literature_payload(data: dict[str, Any], field: str, label: str) -> None:
    expected = data.get(field)
    rw.require(isinstance(expected, str) and rw.SHA256_RE.fullmatch(expected) is not None, f"{label} payload SHA-256 is invalid")
    rw.require(expected == _literature_payload_hash(data, field), f"{label} payload SHA-256 mismatch")


def _structured_ref(
    path: Path,
    data: dict[str, Any],
    payload_hash: str,
    *,
    display_path: str | None = None,
) -> dict[str, Any]:
    rw.require(path.is_file() and not path.is_symlink(), f"structured artifact is missing or a symlink: {path}")
    schema = _string(data.get("schema"), f"{path} schema")
    rw.require(rw.SHA256_RE.fullmatch(payload_hash) is not None, f"{path} payload hash is invalid")
    return {
        "path": str(path) if display_path is None else display_path,
        "sha256": rw.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "schema": schema,
        "payload_sha256": payload_hash,
    }


def _verify_structured_ref(
    reference: Any,
    owner: Path,
    expected_schema: str,
    label: str,
    *,
    payload_field: str = "payload_sha256",
    literature_hash: bool = False,
    validate_payload: bool = True,
) -> tuple[Path, dict[str, Any]]:
    ref = _exact(reference, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    path = _resolve_path(ref["path"], owner, label)
    rw.require(ref["schema"] == expected_schema, f"{label} schema binding mismatch")
    rw.require(ref["sha256"] == rw.sha256_file(path), f"{label} file SHA-256 mismatch")
    rw.require(isinstance(ref["size_bytes"], int) and not isinstance(ref["size_bytes"], bool) and ref["size_bytes"] >= 0, f"{label}.size_bytes must be a non-negative integer")
    rw.require(ref["size_bytes"] == path.stat().st_size, f"{label} file size mismatch")
    data = rw.load_json(path)
    rw.require(data.get("schema") == expected_schema, f"{label} artifact schema mismatch")
    if validate_payload:
        if literature_hash:
            _verify_literature_payload(data, payload_field, label)
        else:
            rw.validate_payload_hash(data)
        rw.require(data.get(payload_field) == ref["payload_sha256"], f"{label} payload SHA-256 binding mismatch")
    else:
        computed = rw.sha256_data(data)
        rw.require(computed == ref["payload_sha256"], f"{label} payload SHA-256 binding mismatch")
    return path, data


def _verify_legacy_binding(
    binding: Any,
    owner: Path,
    expected_path: Path,
    expected_data: dict[str, Any],
    label: str,
) -> None:
    ref = _exact(binding, {"path", "sha256", "schema", "payload_sha256"}, label)
    bound_path = _resolve_path(ref["path"], owner, label)
    rw.require(ref["schema"] == expected_data["schema"], f"{label} schema mismatch")
    rw.require(ref["sha256"] == rw.sha256_file(bound_path), f"{label} file hash mismatch")
    bound_data = rw.load_json(bound_path)
    if expected_data["schema"] == SNAPSHOT_SCHEMA:
        kb.validate_record(bound_data)
    else:
        rw.validate_artifact(bound_path)
    rw.require(ref["payload_sha256"] == bound_data["payload_sha256"], f"{label} payload hash mismatch")
    rw.require(bound_data["payload_sha256"] == expected_data["payload_sha256"], f"{label} differs from the supplied exact artifact")
    rw.require(rw.sha256_file(bound_path) == rw.sha256_file(expected_path), f"{label} differs from the supplied exact file")


def _validate_candidate_ledger(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    ledger = rw.load_json(path)
    _exact(ledger, LEDGER_TOP_KEYS, "candidate ledger")
    rw.require(ledger["schema"] == LEDGER_SCHEMA, "candidate ledger schema mismatch")
    _verify_literature_payload(ledger, LEDGER_HASH_FIELD, "candidate ledger")
    rw.require(
        ledger["calculation_ready"] is False
        and ledger["promotable_to_mechanism_support"] is False
        and ledger["promotable_to_ts_precedent_map"] is False
        and ledger["no_submission_authorization"] is True,
        "candidate ledger violates offline safety flags",
    )
    _literature_id(ledger["request_id"], "candidate ledger request_id")
    _timestamp(ledger["created_at"], "candidate ledger created_at")
    _validate_legacy_reference_shape(ledger["search_plan_artifact"], "candidate ledger search_plan_artifact")
    _validate_legacy_reference_shape(ledger["retrieval_artifact"], "candidate ledger retrieval_artifact")
    targets = _unique_strings(ledger["target_evidence"], "candidate ledger target_evidence", nonempty=True)
    rw.require(all(LITERATURE_ID_RE.fullmatch(value) is not None for value in targets), "candidate ledger target_evidence contains an invalid category")
    upstream = _exact(
        ledger["upstream_artifacts"],
        {"reaction_intake", "species_registry", "condition_model", "knowledge_snapshot"},
        "candidate ledger upstream_artifacts",
    )
    for key, raw_binding in upstream.items():
        binding = _exact(raw_binding, {"path", "sha256", "schema", "payload_sha256"}, f"candidate ledger upstream_artifacts.{key}")
        _string(binding["path"], f"candidate ledger upstream_artifacts.{key}.path")
        _string(binding["schema"], f"candidate ledger upstream_artifacts.{key}.schema")
        for field in ("sha256", "payload_sha256"):
            rw.require(isinstance(binding[field], str) and rw.SHA256_RE.fullmatch(binding[field]) is not None, f"candidate ledger upstream_artifacts.{key}.{field} is invalid")
    rw.require(ledger["w2_binding_status"] == "complete_for_search_scope_review", "candidate ledger lacks complete W1/knowledge bindings")
    rw.require(ledger["promotion_blockers"] == [], "candidate ledger retains upstream promotion blockers")
    counts = _exact(ledger["counts"], {"normalized_raw_records", "unique_candidates", "candidates_retained"}, "candidate ledger counts")
    for field, value in counts.items():
        rw.require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"candidate ledger counts.{field} must be a non-negative integer")
    ranking = _exact(ledger["ranking_policy"], {"type", "citation_count_used_in_score", "scientific_acceptance_performed"}, "candidate ledger ranking_policy")
    rw.require(
        ranking == {
            "type": "transparent_lexical_screening_only",
            "citation_count_used_in_score": False,
            "scientific_acceptance_performed": False,
        },
        "candidate ledger ranking policy was altered",
    )
    _unique_strings(ledger["limitations"], "candidate ledger limitations", nonempty=True)
    raw_candidates = ledger["candidates"]
    rw.require(isinstance(raw_candidates, list) and raw_candidates, "candidate ledger candidates must be a non-empty array")
    candidates: dict[str, dict[str, Any]] = {}
    candidate_order: list[str] = []
    for index, item in enumerate(raw_candidates):
        item = _exact(item, LEDGER_CANDIDATE_KEYS, f"candidate ledger candidates[{index}]")
        candidate_id = _literature_id(item["candidate_id"], f"candidate ledger candidates[{index}].candidate_id")
        rw.require(candidate_id not in candidates, f"duplicate candidate ledger candidate_id: {candidate_id}")
        candidate_order.append(candidate_id)
        _string(item["deduplication_key"], f"candidate {candidate_id}.deduplication_key")
        rw.require(item["doi"] is None or isinstance(item["doi"], str), f"candidate {candidate_id}.doi must be a string or null")
        _string(item["title"], f"candidate {candidate_id}.title")
        rw._string_list(item["authors"], f"candidate {candidate_id}.authors")
        rw.require(item["year"] is None or (isinstance(item["year"], int) and not isinstance(item["year"], bool)), f"candidate {candidate_id}.year must be an integer or null")
        for field in ("venue", "url", "publication_type"):
            rw.require(item[field] is None or (isinstance(item[field], str) and item[field].strip()), f"candidate {candidate_id}.{field} must be a non-empty string or null")
        rw.require(item["cited_by_count"] is None or (isinstance(item["cited_by_count"], int) and not isinstance(item["cited_by_count"], bool) and item["cited_by_count"] >= 0), f"candidate {candidate_id}.cited_by_count must be a non-negative integer or null")
        signals = _exact(item["record_status_signals"], {"crossref_update_to_present", "crossref_relation_present", "openalex_is_retracted"}, f"candidate {candidate_id}.record_status_signals")
        rw.require(all(value is None or type(value) is bool for value in signals.values()), f"candidate {candidate_id}.record_status_signals values must be boolean or null")
        rw.require(type(item["metadata_abstract_available"]) is bool, f"candidate {candidate_id}.metadata_abstract_available must be boolean")
        observations = item["discovery_observations"]
        rw.require(isinstance(observations, list) and observations, f"candidate {candidate_id}.discovery_observations must be a non-empty array")
        for observation_index, raw_observation in enumerate(observations):
            observation = _exact(raw_observation, {"source", "query_id", "lane", "raw_sha256"}, f"candidate {candidate_id}.discovery_observations[{observation_index}]")
            rw.require(observation["source"] in {"crossref", "openalex"}, f"candidate {candidate_id} discovery source is invalid")
            _literature_id(observation["query_id"], f"candidate {candidate_id} query_id")
            _string(observation["lane"], f"candidate {candidate_id} lane")
            rw.require(isinstance(observation["raw_sha256"], str) and rw.SHA256_RE.fullmatch(observation["raw_sha256"]) is not None, f"candidate {candidate_id} raw_sha256 is invalid")
        rw.require(isinstance(item["lexical_score"], int) and not isinstance(item["lexical_score"], bool) and item["lexical_score"] >= 0, f"candidate {candidate_id}.lexical_score must be a non-negative integer")
        breakdown = _exact(item["score_breakdown"], {"matched_terms", "points"}, f"candidate {candidate_id}.score_breakdown")
        hits = _exact(breakdown["matched_terms"], SCORE_KEYS, f"candidate {candidate_id}.score_breakdown.matched_terms")
        points = _exact(breakdown["points"], SCORE_KEYS, f"candidate {candidate_id}.score_breakdown.points")
        for key in SCORE_KEYS:
            rw._string_list(hits[key], f"candidate {candidate_id}.score_breakdown.matched_terms.{key}")
            rw.require(isinstance(points[key], int) and not isinstance(points[key], bool), f"candidate {candidate_id}.score_breakdown.points.{key} must be an integer")
        rw.require(item["lexical_score"] == max(0, sum(points.values())), f"candidate {candidate_id}.lexical_score differs from its transparent score breakdown")
        rw.require(item["screening_tier"] in {"high_priority_screen", "system_relevant_requires_full_text", "analogy_or_background_screen", "low_lexical_match"}, f"candidate {candidate_id}.screening_tier is invalid")
        rw.require(item["screening_status"] == "metadata_only_unverified" and item["directness"] == "not_reviewed", f"candidate {candidate_id} exceeds metadata-screening authority")
        candidates[candidate_id] = item
    rw.require(candidate_order == sorted(candidate_order), "candidate ledger candidates use unstable ordering")
    rw.require(counts["candidates_retained"] == len(raw_candidates), "candidate ledger retained count differs from candidates")
    rw.require(counts["unique_candidates"] >= len(raw_candidates) and counts["normalized_raw_records"] >= counts["unique_candidates"], "candidate ledger counts are inconsistent")
    return ledger, candidates


def _validate_evidence(path: Path) -> tuple[dict[str, Any], Path, dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    evidence = rw.load_json(path)
    _exact(evidence, EVIDENCE_TOP_KEYS, "finalized literature evidence")
    rw.require(evidence["schema"] == EVIDENCE_SCHEMA, "literature evidence schema mismatch")
    _verify_literature_payload(evidence, EVIDENCE_HASH_FIELD, "literature evidence")
    _literature_id(evidence["request_id"], "literature evidence request_id")
    _timestamp(evidence["created_at"], "literature evidence created_at")
    _timestamp(evidence["validated_at"], "literature evidence validated_at")
    rw.require(evidence["record_status"] == "validated_review_record", "literature evidence must be finalized")
    rw.require(evidence["w2_binding_status"] == "complete_for_search_scope_review", "literature evidence lacks complete W1/knowledge bindings")
    rw.require(evidence["promotion_blockers"] == [], "literature evidence retains upstream promotion blockers")
    rw.require(evidence["calculation_ready"] is False and evidence["no_submission_authorization"] is True, "literature evidence violates offline safety flags")
    rw.require(evidence["promotable_to_mechanism_support"] is False, "literature evidence promotion flag must remain false")
    rw.require(evidence["promotable_to_ts_precedent_map"] is False, "literature evidence TS-promotion flag must remain false")
    rw.require(evidence["allowed_evidence_statuses"] == ["not_reviewed", "not_found", "source_ambiguous", "source_reports"], "literature evidence status vocabulary drifted")
    rw.require(evidence["allowed_decisions"] == ["pending", "source_checked_background", "source_reports_analogy", "source_reports_direct_precedent", "exclude"], "literature evidence decision vocabulary drifted")
    rw.require(evidence["allowed_applicability_values"] == ["exact", "close", "remote", "contradictory", "unknown", "not_applicable"], "literature evidence applicability vocabulary drifted")
    rw.require(evidence["allowed_bounded_uses"] == ["discovery_only", "mechanism_support", "ts_topology_support", "geometry_seed_support", "protocol_candidate_support", "not_applicable_to_target"], "literature evidence bounded-use vocabulary drifted")

    ledger_ref = _exact(evidence["candidate_ledger_artifact"], {"path", "sha256"}, "candidate_ledger_artifact")
    ledger_path = _resolve_path(ledger_ref["path"], path, "candidate_ledger_artifact")
    rw.require(ledger_ref["sha256"] == rw.sha256_file(ledger_path), "candidate ledger file hash mismatch")
    ledger, candidates = _validate_candidate_ledger(ledger_path)
    rw.require(ledger.get("request_id") == evidence["request_id"], "literature evidence request differs from candidate ledger")
    rw.require(ledger["upstream_artifacts"] == evidence["upstream_artifacts"], "candidate ledger and literature evidence bind different W1/knowledge artifacts")
    rw.require(ledger["w2_binding_status"] == evidence["w2_binding_status"], "candidate ledger and literature evidence W2 binding status differs")
    rw.require(ledger["promotion_blockers"] == evidence["promotion_blockers"], "candidate ledger and literature evidence promotion blockers differ")

    claims: dict[tuple[str, str], dict[str, Any]] = {}
    raw_reviews = evidence["reviews"]
    rw.require(isinstance(raw_reviews, list) and raw_reviews, "literature evidence reviews must be a non-empty array")
    seen_candidates: set[str] = set()
    for index, raw in enumerate(raw_reviews):
        item = _exact(
            raw,
            {"candidate_id", "bibliography", "discovery", "source_checks", "directness_dimensions", "evidence", "reported_protocol", "reported_ts_path", "exact_quotes", "reviewer_decision"},
            f"literature reviews[{index}]",
        )
        candidate_id = _literature_id(item["candidate_id"], f"literature reviews[{index}].candidate_id")
        rw.require(candidate_id in candidates, f"literature review references unknown candidate: {candidate_id}")
        rw.require(candidate_id not in seen_candidates, f"duplicate literature review candidate: {candidate_id}")
        seen_candidates.add(candidate_id)
        bibliography = _exact(item["bibliography"], {"doi", "title", "authors", "year", "venue", "url", "publication_type"}, f"{candidate_id}.bibliography")
        candidate = candidates[candidate_id]
        rw.require(_normalize_doi(bibliography["doi"]) == _normalize_doi(candidate["doi"]), f"{candidate_id} bibliography DOI differs from candidate ledger")
        rw.require(_normalize_search_text(bibliography["title"]) == _normalize_search_text(candidate["title"]), f"{candidate_id} bibliography title differs from candidate ledger")
        discovery = _exact(item["discovery"], {"lexical_score", "screening_tier", "metadata_only"}, f"{candidate_id}.discovery")
        rw.require(discovery == {"lexical_score": candidate["lexical_score"], "screening_tier": candidate["screening_tier"], "metadata_only": True}, f"{candidate_id} discovery metadata differs from candidate ledger")
        checks = _exact(item["source_checks"], {"doi_or_publisher_record_checked", "primary_article_checked", "supporting_information_checked", "correction_or_retraction_checked", "access_notes"}, f"{candidate_id}.source_checks")
        for field in ("doi_or_publisher_record_checked", "primary_article_checked", "supporting_information_checked", "correction_or_retraction_checked"):
            rw.require(type(checks[field]) is bool, f"{candidate_id}.source_checks.{field} must be boolean")
        _unique_strings(checks["access_notes"], f"{candidate_id}.source_checks.access_notes")
        dimensions = _exact(item["directness_dimensions"], set(APPLICABILITY_DIMENSIONS), f"{candidate_id}.directness_dimensions")
        rw.require(all(value in APPLICABILITY_VALUES for value in dimensions.values()), f"{candidate_id} has an invalid directness dimension")
        evidence_map = item["evidence"]
        rw.require(isinstance(evidence_map, dict) and evidence_map, f"{candidate_id}.evidence must be a non-empty object")
        rw.require(set(evidence_map) == set(ledger.get("target_evidence", [])), f"{candidate_id}.evidence does not exactly cover the candidate-ledger target evidence")
        for category, raw_claim in evidence_map.items():
            claim = _exact(raw_claim, {"status", "source_locations", "paraphrase"}, f"{candidate_id}/{category}")
            rw.require(claim["status"] in {"not_reviewed", "not_found", "source_ambiguous", "source_reports"}, f"{candidate_id}/{category} has invalid claim status")
            locations = claim["source_locations"]
            rw.require(isinstance(locations, list), f"{candidate_id}/{category}.source_locations must be an array")
            normalized_locations: list[dict[str, str]] = []
            for location_index, raw_location in enumerate(locations):
                location = _exact(raw_location, {"source_type", "locator", "url_or_doi", "checked_at"}, f"{candidate_id}/{category}.source_locations[{location_index}]")
                normalized_location = {key: _string(location[key], f"{candidate_id}/{category}.source_locations[{location_index}].{key}") for key in ("source_type", "locator", "url_or_doi", "checked_at")}
                rw.require(normalized_location["source_type"] in PRIMARY_SOURCE_TYPES, f"{candidate_id}/{category} source type is not primary evidence")
                _timestamp(normalized_location["checked_at"], f"{candidate_id}/{category}.source_locations[{location_index}].checked_at")
                normalized_locations.append(normalized_location)
            if claim["status"] == "source_reports":
                rw.require(normalized_locations and isinstance(claim["paraphrase"], str) and claim["paraphrase"].strip(), f"{candidate_id}/{category} source_reports requires locations and paraphrase")
            else:
                rw.require(not normalized_locations and claim["paraphrase"] is None, f"{candidate_id}/{category} non-reported claim must not manufacture source anchors or paraphrase")
            claims[(candidate_id, category)] = {
                "candidate_id": candidate_id,
                "evidence_category": category,
                "status": claim["status"],
                "source_locations": normalized_locations,
                "paraphrase": claim["paraphrase"],
                "candidate_review": item,
            }
        protocol = _exact(item["reported_protocol"], {"status", "optimization_frequency", "single_point", "solvation", "dispersion", "temperature_k", "standard_state", "low_frequency_treatment", "program_version"}, f"{candidate_id}.reported_protocol")
        rw.require(protocol["status"] in {"not_reviewed_not_approved_protocol", "source_reported_not_approved_protocol", "source_ambiguous_not_approved_protocol", "source_incomplete_not_approved_protocol"}, f"{candidate_id} reported protocol status is invalid")
        protocol_has_values = any(value is not None for field, value in protocol.items() if field != "status")
        protocol_claim = evidence_map.get("computational_protocol", {})
        if protocol_has_values or protocol["status"] != "not_reviewed_not_approved_protocol":
            rw.require(protocol_claim.get("status") == "source_reports", f"{candidate_id} reported protocol details lack source-located computational_protocol evidence")
        ts_path = _exact(item["reported_ts_path"], {"ts_labels", "charge_multiplicity", "model_truncations", "imaginary_frequencies_cm1", "normal_mode_interpretation", "irc_directions_reported", "identified_endpoints", "coordinates_available"}, f"{candidate_id}.reported_ts_path")
        ts_path_has_values = any(value not in (None, [], {}) for value in ts_path.values())
        if ts_path_has_values:
            statuses = {evidence_map.get(target, {}).get("status") for target in ("transition_state_model", "normal_mode", "irc", "coordinates") if target in evidence_map}
            rw.require("source_reports" in statuses, f"{candidate_id} reported TS/path details lack source-located TS/path evidence")
        quotes = item["exact_quotes"]
        rw.require(isinstance(quotes, list), f"{candidate_id}.exact_quotes must be an array")
        for quote_index, quote in enumerate(quotes):
            _exact(quote, {"text", "locator"}, f"{candidate_id}.exact_quotes[{quote_index}]")
            rw.require(len(_string(quote["text"], f"{candidate_id}.exact_quotes[{quote_index}].text").split()) <= 25, f"{candidate_id} exact quote exceeds 25 words")
            _string(quote["locator"], f"{candidate_id}.exact_quotes[{quote_index}].locator")
        decision = _exact(item["reviewer_decision"], {"status", "bounded_use", "rationale", "reviewed_at"}, f"{candidate_id}.reviewer_decision")
        rw.require(decision["status"] in {"pending", "source_checked_background", "source_reports_analogy", "source_reports_direct_precedent", "exclude"}, f"{candidate_id} reviewer decision is invalid")
        if decision["status"] != "pending":
            rw.require(decision["bounded_use"] in BOUNDED_USES and isinstance(decision["rationale"], str) and decision["rationale"].strip(), f"{candidate_id} non-pending decision is incomplete")
            _timestamp(decision["reviewed_at"], f"{candidate_id}.reviewer_decision.reviewed_at")
            rw.require(checks["doi_or_publisher_record_checked"] is True, f"{candidate_id} finalized decision requires DOI/publisher verification")
        if decision["status"] in {"source_reports_analogy", "source_reports_direct_precedent"}:
            rw.require(checks["primary_article_checked"] is True and any(claim["status"] == "source_reports" for claim in evidence_map.values()), f"{candidate_id} precedent decision requires checked source-located primary evidence")
        if decision["status"] == "source_reports_direct_precedent":
            rw.require(all(value in {"exact", "not_applicable"} for value in dimensions.values()), f"{candidate_id} direct precedent has non-exact applicability dimensions")
    return evidence, ledger_path, ledger, claims


def _load_network_chain(network_path: Path) -> tuple[dict[str, Any], Path, dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]]:
    mn.validate(network_path)
    network = rw.load_json(network_path)
    intake_path = mn._referenced_path(network["intake"], network_path)
    registry_path = mn._referenced_path(network["species_registry"], network_path)
    condition_path = mn._referenced_path(network["condition_model"], network_path)
    for path in (intake_path, registry_path, condition_path):
        rw.require(path.is_file() and not path.is_symlink(), f"network W1 artifact is missing or a symlink: {path}")
    intake = rw.load_json(intake_path)
    registry = rw.load_json(registry_path)
    condition = rw.load_json(condition_path)
    return network, intake_path, intake, registry_path, registry, condition_path, condition


def _validate_snapshot(snapshot_path: Path, intake_path: Path, intake: dict[str, Any], study_id: str) -> dict[str, Any]:
    snapshot = rw.load_json(snapshot_path)
    kb.validate_record(snapshot)
    rw.require(snapshot["schema"] == SNAPSHOT_SCHEMA, "knowledge snapshot schema mismatch")
    rw.require(snapshot["study_id"] == study_id, "knowledge snapshot study_id differs from mechanism network")
    rw.require(snapshot["review"]["status"] in {"reviewed", "reviewed_with_limits"}, "knowledge snapshot is not finalized for study use")
    parent = _exact(snapshot["parent_reaction_intake"], {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, "knowledge snapshot parent reaction intake")
    parent_path = _resolve_path(parent["path"], snapshot_path, "knowledge snapshot parent reaction intake")
    rw.require(parent["schema"] == rw.INTAKE_SCHEMA and parent["sha256"] == rw.sha256_file(parent_path) and parent["size_bytes"] == parent_path.stat().st_size, "knowledge snapshot parent reaction-intake file binding drifted")
    parent_data = rw.load_json(parent_path)
    rw.validate_artifact(parent_path)
    rw.require(parent["payload_sha256"] == parent_data["payload_sha256"] == intake["payload_sha256"], "knowledge snapshot parent reaction-intake payload differs")
    rw.require(rw.sha256_file(parent_path) == rw.sha256_file(intake_path), "knowledge snapshot binds a different reaction-intake file")
    return snapshot


def _normalize_columns(
    raw_columns: Any,
    claims: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
    rw.require(isinstance(raw_columns, list) and raw_columns, "evidence_columns must be a non-empty array")
    columns: dict[str, dict[str, Any]] = {}
    claim_ids: set[str] = set()
    anchor_ids: set[str] = set()
    covered_claims: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_columns):
        item = _exact(raw, {"column_id", "candidate_id", "evidence_category", "claim_id", "source_anchors", "promotion_decision", "bounded_use", "rationale"}, f"evidence_columns[{index}]")
        column_id = rw._require_id(item["column_id"], f"evidence_columns[{index}].column_id")
        rw.require(column_id not in columns, f"duplicate column_id: {column_id}")
        candidate_id = _literature_id(item["candidate_id"], f"column {column_id}.candidate_id")
        category = _string(item["evidence_category"], f"column {column_id}.evidence_category")
        key = (candidate_id, category)
        rw.require(key in claims, f"column {column_id} references an unknown finalized literature claim")
        rw.require(key not in covered_claims, f"finalized literature claim is mapped more than once: {candidate_id}/{category}")
        covered_claims.add(key)
        claim_id = rw._require_id(item["claim_id"], f"column {column_id}.claim_id")
        rw.require(claim_id not in claim_ids, f"duplicate claim_id: {claim_id}")
        claim_ids.add(claim_id)
        claim = claims[key]
        anchors_raw = item["source_anchors"]
        rw.require(isinstance(anchors_raw, list), f"column {column_id}.source_anchors must be an array")
        anchors: list[dict[str, Any]] = []
        location_indices: set[int] = set()
        for anchor_index, raw_anchor in enumerate(anchors_raw):
            anchor = _exact(raw_anchor, {"anchor_id", "source_location_index"}, f"column {column_id}.source_anchors[{anchor_index}]")
            anchor_id = rw._require_id(anchor["anchor_id"], f"column {column_id} anchor_id")
            rw.require(anchor_id not in anchor_ids, f"duplicate anchor_id: {anchor_id}")
            anchor_ids.add(anchor_id)
            location_index = anchor["source_location_index"]
            rw.require(isinstance(location_index, int) and not isinstance(location_index, bool) and 0 <= location_index < len(claim["source_locations"]), f"column {column_id} source_location_index is invalid")
            rw.require(location_index not in location_indices, f"column {column_id} maps one source location more than once")
            location_indices.add(location_index)
            anchors.append({"anchor_id": anchor_id, "source_location_index": location_index, **copy.deepcopy(claim["source_locations"][location_index])})
        rw.require(location_indices == set(range(len(claim["source_locations"]))), f"column {column_id} must map every finalized source location exactly once")
        promotion = _string(item["promotion_decision"], f"column {column_id}.promotion_decision")
        rw.require(promotion in PROMOTION_DECISIONS, f"column {column_id} promotion_decision is invalid")
        bounded_use = item["bounded_use"]
        rw.require(bounded_use is None or bounded_use in SUPPORT_BOUNDED_USES, f"column {column_id}.bounded_use is invalid for a mechanism-support artifact")
        candidate_review = claim["candidate_review"]
        if promotion == "accepted_for_mechanism_support":
            decision = candidate_review["reviewer_decision"]
            rw.require(claim["status"] == "source_reports", f"column {column_id} cannot promote a claim without source_reports evidence")
            rw.require(candidate_review["source_checks"]["doi_or_publisher_record_checked"] is True, f"column {column_id} promotion requires DOI/publisher verification")
            rw.require(candidate_review["source_checks"]["primary_article_checked"] is True, f"column {column_id} promotion requires primary-article review")
            rw.require(decision["status"] in {"source_reports_analogy", "source_reports_direct_precedent"} and decision["bounded_use"] == "mechanism_support", f"column {column_id} promotion exceeds the finalized literature decision")
            rw.require(bounded_use == "mechanism_support", f"column {column_id} accepted promotion must use mechanism_support")
            rw.require(bool(anchors), f"column {column_id} accepted promotion requires a source anchor")
        else:
            rw.require(bounded_use in {None, "discovery_only", "not_applicable_to_target"}, f"column {column_id} cannot expose downstream TS, geometry, protocol, or mechanism authority without accepted promotion")
        columns[column_id] = {
            "column_id": column_id,
            "candidate_id": candidate_id,
            "evidence_category": category,
            "claim_id": claim_id,
            "source_claim_status": claim["status"],
            "source_claim_paraphrase": claim["paraphrase"],
            "source_anchors": sorted(anchors, key=lambda value: value["anchor_id"]),
            "promotion_decision": promotion,
            "bounded_use": bounded_use,
            "rationale": _string(item["rationale"], f"column {column_id}.rationale"),
        }
    rw.require(covered_claims == set(claims), "every finalized literature candidate/claim must be mapped exactly once")
    return [columns[key] for key in sorted(columns)], columns, anchor_ids


def _normalize_rows(raw_rows: Any, network: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], set[str], set[str]]:
    rw.require(isinstance(raw_rows, list) and raw_rows, "rows must be a non-empty array")
    valid_states = {item["state_id"] for item in network["states"]}
    valid_edges = {item["edge_id"] for item in network["edges"]}
    rows: dict[str, dict[str, Any]] = {}
    covered_states: set[str] = set()
    covered_edges: set[str] = set()
    for index, raw in enumerate(raw_rows):
        item = _exact(raw, {"row_id", "label", "state_ids", "edge_ids", "bounded_hypothesis"}, f"rows[{index}]")
        row_id = rw._require_id(item["row_id"], f"rows[{index}].row_id")
        rw.require(row_id not in rows, f"duplicate row_id: {row_id}")
        state_ids = _unique_strings(item["state_ids"], f"row {row_id}.state_ids")
        edge_ids = _unique_strings(item["edge_ids"], f"row {row_id}.edge_ids")
        rw.require(state_ids or edge_ids, f"row {row_id} must reference a state and/or edge")
        rw.require(set(state_ids) <= valid_states, f"row {row_id} references an unknown mechanism-network state")
        rw.require(set(edge_ids) <= valid_edges, f"row {row_id} references an unknown mechanism-network edge")
        rw.require(not (set(state_ids) & covered_states), f"a mechanism-network state is assigned to more than one row")
        rw.require(not (set(edge_ids) & covered_edges), f"a mechanism-network edge is assigned to more than one row")
        covered_states.update(state_ids)
        covered_edges.update(edge_ids)
        rows[row_id] = {
            "row_id": row_id,
            "label": _string(item["label"], f"row {row_id}.label"),
            "state_ids": state_ids,
            "edge_ids": edge_ids,
            "bounded_hypothesis": _string(item["bounded_hypothesis"], f"row {row_id}.bounded_hypothesis"),
        }
    return [rows[key] for key in sorted(rows)], rows, covered_states, covered_edges


def _normalize_blockers(raw: Any, cell_id: str, global_ids: set[str]) -> list[dict[str, str]]:
    rw.require(isinstance(raw, list), f"cell {cell_id}.blockers must be an array")
    blockers: list[dict[str, str]] = []
    for index, value in enumerate(raw):
        item = _exact(value, {"blocker_id", "code", "rationale"}, f"cell {cell_id}.blockers[{index}]")
        blocker_id = rw._require_id(item["blocker_id"], f"cell {cell_id} blocker_id")
        rw.require(blocker_id not in global_ids, f"duplicate blocker_id: {blocker_id}")
        global_ids.add(blocker_id)
        code = _string(item["code"], f"cell {cell_id} blocker {blocker_id}.code")
        rw.require(code in BLOCKER_CODES, f"cell {cell_id} blocker code is unsupported")
        blockers.append({"blocker_id": blocker_id, "code": code, "rationale": _string(item["rationale"], f"cell {cell_id} blocker {blocker_id}.rationale")})
    return sorted(blockers, key=lambda value: value["blocker_id"])


def _normalize_cells(
    raw_cells: Any,
    rows: dict[str, dict[str, Any]],
    columns: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    rw.require(isinstance(raw_cells, list), "cells must be an array")
    expected_pairs = {(row_id, column_id) for row_id in rows for column_id in columns}
    seen_pairs: set[tuple[str, str]] = set()
    cell_ids: set[str] = set()
    blocker_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    by_row: dict[str, list[dict[str, Any]]] = {row_id: [] for row_id in rows}
    flattened_blockers: list[dict[str, str]] = []
    for index, raw in enumerate(raw_cells):
        item = _exact(raw, {"cell_id", "row_id", "column_id", "evidence_status", "bounded_claim", "directness", "evidence_basis", "applicability", "mismatches", "alternative_explanations", "confidence", "reviewer_decision", "bounded_use", "blockers", "notes"}, f"cells[{index}]")
        cell_id = rw._require_id(item["cell_id"], f"cells[{index}].cell_id")
        rw.require(cell_id not in cell_ids, f"duplicate cell_id: {cell_id}")
        cell_ids.add(cell_id)
        row_id = rw._require_id(item["row_id"], f"cell {cell_id}.row_id")
        column_id = rw._require_id(item["column_id"], f"cell {cell_id}.column_id")
        pair = (row_id, column_id)
        rw.require(pair in expected_pairs, f"cell {cell_id} references an unknown row/column intersection")
        rw.require(pair not in seen_pairs, f"row/column intersection appears more than once: {row_id}/{column_id}")
        seen_pairs.add(pair)
        status = _string(item["evidence_status"], f"cell {cell_id}.evidence_status")
        rw.require(status in EVIDENCE_STATUSES, f"cell {cell_id}.evidence_status is invalid")
        bounded_claim = _exact(item["bounded_claim"], {"relationship", "text"}, f"cell {cell_id}.bounded_claim")
        relationship = _string(bounded_claim["relationship"], f"cell {cell_id}.bounded_claim.relationship")
        rw.require(relationship in CLAIM_RELATIONSHIPS, f"cell {cell_id} bounded-claim relationship is invalid")
        directness = _string(item["directness"], f"cell {cell_id}.directness")
        basis = _string(item["evidence_basis"], f"cell {cell_id}.evidence_basis")
        rw.require(directness in DIRECTNESS_VALUES, f"cell {cell_id}.directness is invalid")
        rw.require(basis in EVIDENCE_BASES, f"cell {cell_id}.evidence_basis is invalid")
        column_anchor_ids = {anchor["anchor_id"] for anchor in columns[column_id]["source_anchors"]}
        applicability_raw = _exact(item["applicability"], set(APPLICABILITY_DIMENSIONS), f"cell {cell_id}.applicability")
        applicability: dict[str, dict[str, Any]] = {}
        used_anchor_ids: set[str] = set()
        for dimension in APPLICABILITY_DIMENSIONS:
            decision = _exact(applicability_raw[dimension], {"value", "rationale", "source_anchor_ids"}, f"cell {cell_id}.applicability.{dimension}")
            value = _string(decision["value"], f"cell {cell_id}.applicability.{dimension}.value")
            rw.require(value in APPLICABILITY_VALUES, f"cell {cell_id}.applicability.{dimension}.value is invalid")
            anchors = _unique_strings(decision["source_anchor_ids"], f"cell {cell_id}.applicability.{dimension}.source_anchor_ids")
            rw.require(set(anchors) <= column_anchor_ids, f"cell {cell_id}.applicability.{dimension} references an anchor outside its evidence column")
            if value in {"exact", "close", "remote", "contradictory"}:
                rw.require(bool(anchors), f"cell {cell_id}.applicability.{dimension} requires a source anchor")
            used_anchor_ids.update(anchors)
            applicability[dimension] = {"value": value, "rationale": _string(decision["rationale"], f"cell {cell_id}.applicability.{dimension}.rationale"), "source_anchor_ids": anchors}
        confidence = _string(item["confidence"], f"cell {cell_id}.confidence")
        decision = _string(item["reviewer_decision"], f"cell {cell_id}.reviewer_decision")
        bounded_use = _string(item["bounded_use"], f"cell {cell_id}.bounded_use")
        rw.require(confidence in CONFIDENCE_VALUES, f"cell {cell_id}.confidence is invalid")
        rw.require(decision in CELL_DECISIONS, f"cell {cell_id}.reviewer_decision is invalid")
        rw.require(bounded_use in SUPPORT_BOUNDED_USES, f"cell {cell_id}.bounded_use is invalid for a mechanism-support artifact")
        blockers = _normalize_blockers(item["blockers"], cell_id, blocker_ids)
        blocker_codes = {blocker["code"] for blocker in blockers}
        promotion = columns[column_id]["promotion_decision"]
        claim_status = columns[column_id]["source_claim_status"]
        if status == "positive":
            rw.require(relationship == "supports" and decision == "include_support", f"cell {cell_id} positive status conflicts with its reviewed claim/decision")
            rw.require(promotion == "accepted_for_mechanism_support" and claim_status == "source_reports", f"cell {cell_id} positive support lacks an accepted source-reported promotion")
            rw.require(directness in {"direct", "analogous"} and basis in {"experimental", "computational", "mixed"}, f"cell {cell_id} positive support requires reviewed directness and evidence basis")
            rw.require(bounded_use == "mechanism_support" and bool(used_anchor_ids), f"cell {cell_id} positive support exceeds its bounded use or lacks anchors")
        elif status == "contradictory":
            rw.require(relationship == "contradicts" and decision == "include_contradiction", f"cell {cell_id} contradictory status conflicts with its reviewed claim/decision")
            rw.require(promotion == "accepted_for_mechanism_support" and claim_status == "source_reports", f"cell {cell_id} contradiction lacks an accepted source-reported promotion")
            rw.require(directness in {"direct", "analogous"} and basis in {"experimental", "computational", "mixed"}, f"cell {cell_id} contradiction requires reviewed directness and evidence basis")
            rw.require(bounded_use == "mechanism_support" and bool(used_anchor_ids) and "contradictory_evidence" in blocker_codes, f"cell {cell_id} contradiction requires anchors and the contradictory_evidence blocker")
        elif status == "negative":
            rw.require(relationship == "does_not_address" and decision == "retain_negative", f"cell {cell_id} negative status conflicts with its reviewed claim/decision")
            rw.require(bounded_use != "mechanism_support", f"cell {cell_id} negative evidence cannot be promoted as support")
        elif status == "inaccessible":
            rw.require(decision == "retain_inaccessible" and bool(blocker_codes & ACCESS_BLOCKERS), f"cell {cell_id} inaccessible status requires an access blocker")
            rw.require(bounded_use != "mechanism_support", f"cell {cell_id} inaccessible evidence cannot be promoted as support")
        elif status == "incomplete":
            rw.require(decision == "retain_incomplete" and bool(blocker_codes & INCOMPLETE_BLOCKERS), f"cell {cell_id} incomplete status requires an incompleteness blocker")
            rw.require(bounded_use != "mechanism_support", f"cell {cell_id} incomplete evidence cannot be promoted as support")
        elif status == "rejected":
            rw.require(decision == "reject" and bounded_use != "mechanism_support", f"cell {cell_id} rejected status conflicts with its reviewed decision")
        else:
            rw.require(decision == "record_no_evidence" and relationship in {"does_not_address", "unknown"}, f"cell {cell_id} no_evidence status conflicts with its reviewed claim/decision")
            rw.require(not used_anchor_ids and directness in {"unknown", "not_applicable"} and basis in {"unknown", "not_applicable"}, f"cell {cell_id} no_evidence must not imply anchored applicability")
            rw.require(bounded_use in {"discovery_only", "not_applicable_to_target"}, f"cell {cell_id} no_evidence has an invalid bounded use")
        if status not in {"positive", "contradictory"}:
            rw.require(bounded_use in {"discovery_only", "not_applicable_to_target"}, f"cell {cell_id} non-promoted evidence cannot expose TS, geometry, protocol, or mechanism authority")
        normalized_cell = {
            "cell_id": cell_id,
            "row_id": row_id,
            "column_id": column_id,
            "evidence_status": status,
            "bounded_claim": {"relationship": relationship, "text": _string(bounded_claim["text"], f"cell {cell_id}.bounded_claim.text")},
            "directness": directness,
            "evidence_basis": basis,
            "applicability": applicability,
            "mismatches": _unique_strings(item["mismatches"], f"cell {cell_id}.mismatches"),
            "alternative_explanations": _unique_strings(item["alternative_explanations"], f"cell {cell_id}.alternative_explanations"),
            "confidence": confidence,
            "reviewer_decision": decision,
            "bounded_use": bounded_use,
            "blockers": blockers,
            "notes": _unique_strings(item["notes"], f"cell {cell_id}.notes"),
        }
        normalized.append(normalized_cell)
        by_row[row_id].append(normalized_cell)
        flattened_blockers.extend({"blocker_id": blocker["blocker_id"], "code": blocker["code"], "scope": cell_id, "rationale": blocker["rationale"]} for blocker in blockers)
    rw.require(seen_pairs == expected_pairs, "matrix must contain exactly one reviewed cell for every row/evidence-column intersection")
    return sorted(normalized, key=lambda value: (value["row_id"], value["column_id"])), by_row, sorted(flattened_blockers, key=lambda value: value["blocker_id"])


def _normalize_coverage(
    raw: Any,
    network: dict[str, Any],
    covered_states: set[str],
    covered_edges: set[str],
    row_count: int,
    column_count: int,
    cell_count: int,
) -> dict[str, Any]:
    coverage = _exact(raw, {"excluded_state_targets", "excluded_edge_targets", "matrix_complete", "absent_evidence_explicit", "eligible_evidence_complete", "rationale"}, "coverage")
    rw.require(coverage["matrix_complete"] is True and coverage["absent_evidence_explicit"] is True and coverage["eligible_evidence_complete"] is True, "coverage declarations must explicitly be complete")
    valid_states = {item["state_id"] for item in network["states"]}
    valid_edges = {item["edge_id"] for item in network["edges"]}
    excluded_states: list[dict[str, str]] = []
    excluded_state_ids: set[str] = set()
    for index, raw_item in enumerate(coverage["excluded_state_targets"]):
        item = _exact(raw_item, {"state_id", "rationale"}, f"coverage.excluded_state_targets[{index}]")
        state_id = rw._require_id(item["state_id"], "excluded state_id")
        rw.require(state_id in valid_states and state_id not in covered_states and state_id not in excluded_state_ids, "excluded state target is unknown, covered, or duplicated")
        excluded_state_ids.add(state_id)
        excluded_states.append({"state_id": state_id, "rationale": _string(item["rationale"], f"excluded state {state_id}.rationale")})
    excluded_edges: list[dict[str, str]] = []
    excluded_edge_ids: set[str] = set()
    for index, raw_item in enumerate(coverage["excluded_edge_targets"]):
        item = _exact(raw_item, {"edge_id", "rationale"}, f"coverage.excluded_edge_targets[{index}]")
        edge_id = rw._require_id(item["edge_id"], "excluded edge_id")
        rw.require(edge_id in valid_edges and edge_id not in covered_edges and edge_id not in excluded_edge_ids, "excluded edge target is unknown, covered, or duplicated")
        excluded_edge_ids.add(edge_id)
        excluded_edges.append({"edge_id": edge_id, "rationale": _string(item["rationale"], f"excluded edge {edge_id}.rationale")})
    rw.require(covered_states | excluded_state_ids == valid_states, "every mechanism-network state must be row-mapped or explicitly excluded")
    rw.require(covered_edges | excluded_edge_ids == valid_edges, "every mechanism-network edge must be row-mapped or explicitly excluded")
    rw.require(cell_count == row_count * column_count, "matrix cell count is incomplete")
    return {
        "matrix_complete": True,
        "absent_evidence_explicit": True,
        "eligible_evidence_complete": True,
        "row_count": row_count,
        "column_count": column_count,
        "expected_cell_count": row_count * column_count,
        "actual_cell_count": cell_count,
        "covered_state_ids": sorted(covered_states),
        "covered_edge_ids": sorted(covered_edges),
        "excluded_state_targets": sorted(excluded_states, key=lambda value: value["state_id"]),
        "excluded_edge_targets": sorted(excluded_edges, key=lambda value: value["edge_id"]),
        "rationale": _string(coverage["rationale"], "coverage.rationale"),
    }


def _normalize_row_dispositions(raw: Any, rows: dict[str, dict[str, Any]], cells_by_row: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[str]]:
    rw.require(isinstance(raw, list), "row_promotion_reviews must be an array")
    decisions: dict[str, dict[str, Any]] = {}
    downstream_edges: set[str] = set()
    for index, raw_item in enumerate(raw):
        item = _exact(raw_item, {"row_id", "disposition", "rationale", "reviewed_by", "reviewed_at"}, f"row_promotion_reviews[{index}]")
        row_id = rw._require_id(item["row_id"], f"row_promotion_reviews[{index}].row_id")
        rw.require(row_id in rows and row_id not in decisions, f"row promotion references an unknown or duplicate row: {row_id}")
        disposition = _string(item["disposition"], f"row {row_id}.disposition")
        rw.require(disposition in ROW_DISPOSITIONS, f"row {row_id}.disposition is invalid")
        statuses = {cell["evidence_status"] for cell in cells_by_row[row_id]}
        has_positive = "positive" in statuses
        has_contradiction = "contradictory" in statuses
        if disposition in {"mandatory", "optional"}:
            rw.require(has_positive and not has_contradiction, f"row {row_id} cannot be {disposition} without uncontradicted reviewed positive support")
            downstream_edges.update(rows[row_id]["edge_ids"])
        elif disposition == "contradicted":
            rw.require(has_contradiction and not has_positive, f"row {row_id} contradicted disposition requires contradiction without retained positive support")
        else:
            rw.require((has_positive and has_contradiction) or not has_positive, f"row {row_id} unresolved disposition is inconsistent with reviewed cells")
        decisions[row_id] = {
            "row_id": row_id,
            "disposition": disposition,
            "rationale": _string(item["rationale"], f"row {row_id}.disposition rationale"),
            "reviewed_by": _string(item["reviewed_by"], f"row {row_id}.reviewed_by"),
            "reviewed_at": _timestamp(item["reviewed_at"], f"row {row_id}.reviewed_at"),
        }
    rw.require(set(decisions) == set(rows), "every matrix row requires exactly one explicit promotion review")
    return [decisions[key] for key in sorted(decisions)], sorted(downstream_edges)


def _normalize_supersedes(raw: Any, review_path: Path, study_id: str, seen: set[Path]) -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    if raw is None:
        return None, None, None
    item = _exact(raw, {"path", "payload_sha256"}, "supersedes")
    prior_path = _resolve_path(item["path"], review_path, "supersedes")
    prior = _validate(prior_path, seen)
    rw.require(prior["study_id"] == study_id, "superseded support belongs to a different study")
    rw.require(item["payload_sha256"] == prior["payload_sha256"], "supersedes payload hash mismatch")
    return _structured_ref(prior_path, prior, prior["payload_sha256"], display_path=item["path"]), prior_path, prior


def _compose(
    network_path: Path,
    evidence_path: Path,
    snapshot_path: Path,
    review_path: Path,
    *,
    display_paths: dict[str, str] | None = None,
    seen: set[Path] | None = None,
) -> dict[str, Any]:
    seen = set() if seen is None else seen
    network, intake_path, intake, registry_path, registry, condition_path, condition = _load_network_chain(network_path)
    evidence, ledger_path, ledger, claims = _validate_evidence(evidence_path)
    snapshot = _validate_snapshot(snapshot_path, intake_path, intake, network["study_id"])
    upstream = _exact(evidence["upstream_artifacts"], {"reaction_intake", "species_registry", "condition_model", "knowledge_snapshot"}, "literature evidence upstream_artifacts")
    _verify_legacy_binding(upstream["reaction_intake"], evidence_path, intake_path, intake, "literature evidence reaction_intake")
    _verify_legacy_binding(upstream["species_registry"], evidence_path, registry_path, registry, "literature evidence species_registry")
    _verify_legacy_binding(upstream["condition_model"], evidence_path, condition_path, condition, "literature evidence condition_model")
    _verify_legacy_binding(upstream["knowledge_snapshot"], evidence_path, snapshot_path, snapshot, "literature evidence knowledge_snapshot")

    review = rw.load_json(review_path)
    _exact(review, REVIEW_KEYS, "mechanism-support review")
    rw.require(review["schema"] == REVIEW_SCHEMA, "mechanism-support review schema mismatch")
    support_id = rw._require_id(review["support_id"], "support_id")
    rw.require(review["study_id"] == network["study_id"], "mechanism-support review study_id differs from mechanism network")
    expected_hashes = {
        "mechanism_network_payload_sha256": network["payload_sha256"],
        "intake_payload_sha256": intake["payload_sha256"],
        "species_registry_payload_sha256": registry["payload_sha256"],
        "condition_model_payload_sha256": condition["payload_sha256"],
        "knowledge_snapshot_payload_sha256": snapshot["payload_sha256"],
        "literature_evidence_payload_sha256": evidence[EVIDENCE_HASH_FIELD],
    }
    for field, expected in expected_hashes.items():
        rw.require(review[field] == expected, f"mechanism-support review {field} mismatch")
    rw.require(review["evidence_gate_acknowledgement"] == "separate_review_required_because_upstream_promotion_is_false", "mechanism-support review must explicitly acknowledge the fixed literature promotion gate")
    decision = _string(review["review_decision"], "mechanism-support review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "invalid mechanism-support review_decision")
    reviewed_by = _string(review["reviewed_by"], "mechanism-support reviewed_by")
    reviewed_at = _timestamp(review["reviewed_at"], "mechanism-support reviewed_at")
    notes = _unique_strings(review["review_notes"], "mechanism-support review_notes")

    columns, column_map, _ = _normalize_columns(review["evidence_columns"], claims)
    rows, row_map, covered_states, covered_edges = _normalize_rows(review["rows"], network)
    cells, cells_by_row, blockers = _normalize_cells(review["cells"], row_map, column_map)
    coverage = _normalize_coverage(review["coverage"], network, covered_states, covered_edges, len(rows), len(columns), len(cells))
    dispositions, downstream_edges = _normalize_row_dispositions(review["row_promotion_reviews"], row_map, cells_by_row)
    if decision == "blocked":
        downstream_edges = []
    supersedes_ref, _, prior = _normalize_supersedes(review["supersedes"], review_path, network["study_id"], seen)
    if prior is not None:
        rw.require(prior["support_id"] != support_id, "a support artifact cannot supersede itself")

    paths = display_paths or {}
    artifact = {
        "schema": OUTPUT_SCHEMA,
        "support_id": support_id,
        "study_id": network["study_id"],
        "mechanism_network": _structured_ref(network_path, network, network["payload_sha256"], display_path=paths.get("mechanism_network")),
        "reaction_intake": _structured_ref(intake_path, intake, intake["payload_sha256"], display_path=paths.get("reaction_intake")),
        "species_registry": _structured_ref(registry_path, registry, registry["payload_sha256"], display_path=paths.get("species_registry")),
        "condition_model": _structured_ref(condition_path, condition, condition["payload_sha256"], display_path=paths.get("condition_model")),
        "knowledge_snapshot": _structured_ref(snapshot_path, snapshot, snapshot["payload_sha256"], display_path=paths.get("knowledge_snapshot")),
        "literature_evidence": _structured_ref(evidence_path, evidence, evidence[EVIDENCE_HASH_FIELD], display_path=paths.get("literature_evidence")),
        "candidate_ledger": _structured_ref(ledger_path, ledger, ledger[LEDGER_HASH_FIELD], display_path=paths.get("candidate_ledger")),
        "review_source": _structured_ref(review_path, review, rw.sha256_data(review), display_path=paths.get("review_source")),
        "supersedes": supersedes_ref,
        "matrix": {"rows": rows, "evidence_columns": columns, "cells": cells},
        "coverage": coverage,
        "row_dispositions": dispositions,
        "downstream_reviewable_edge_ids": downstream_edges,
        "blockers": blockers,
        "review": {"decision": decision, "reviewed_by": reviewed_by, "reviewed_at": reviewed_at, "notes": notes},
        "gate_status": rw._gate_status(decision, blockers),
        "claim_ceiling": "bounded_hypothesis_space_not_mechanism_proof",
        "mechanism_proven": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    return artifact


def _write_new_json(path: Path, data: dict[str, Any]) -> None:
    rw.require(not path.is_symlink(), f"refusing to write through output symlink: {path}")
    rw.require(not path.exists(), f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(rw.canonical_bytes(data))
    except FileExistsError as exc:
        raise rw.OfflineError(f"refusing to overwrite existing artifact: {path}") from exc


def build(network_path: Path, evidence_path: Path, snapshot_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    artifact = _compose(network_path, evidence_path, snapshot_path, review_path)
    _write_new_json(output, artifact)
    return artifact


def _validate(path: Path, seen: set[Path] | None = None) -> dict[str, Any]:
    seen = set() if seen is None else seen
    rw.require(path.is_file() and not path.is_symlink(), f"mechanism-support artifact is missing or a symlink: {path}")
    resolved = path.resolve()
    rw.require(resolved not in seen, "mechanism-support supersession cycle detected")
    seen.add(resolved)
    artifact = rw.load_json(path)
    keys = {
        "schema", "support_id", "study_id", "mechanism_network", "reaction_intake",
        "species_registry", "condition_model", "knowledge_snapshot",
        "literature_evidence", "candidate_ledger", "review_source", "supersedes",
        "matrix", "coverage", "row_dispositions", "downstream_reviewable_edge_ids",
        "blockers", "review", "gate_status", "claim_ceiling", "mechanism_proven",
        "calculation_ready", "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "mechanism-support artifact")
    rw.require(artifact["schema"] == OUTPUT_SCHEMA, "mechanism-support artifact schema mismatch")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["claim_ceiling"] == "bounded_hypothesis_space_not_mechanism_proof" and artifact["mechanism_proven"] is False, "mechanism-support artifact exceeds its claim ceiling")
    rw.require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "mechanism-support artifact violates offline safety flags")

    network_path, _ = _verify_structured_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA, "mechanism_network")
    intake_path, _ = _verify_structured_ref(artifact["reaction_intake"], path, rw.INTAKE_SCHEMA, "reaction_intake")
    registry_path, _ = _verify_structured_ref(artifact["species_registry"], path, rw.REGISTRY_SCHEMA, "species_registry")
    condition_path, _ = _verify_structured_ref(artifact["condition_model"], path, rw.CONDITION_SCHEMA, "condition_model")
    snapshot_path, _ = _verify_structured_ref(artifact["knowledge_snapshot"], path, SNAPSHOT_SCHEMA, "knowledge_snapshot")
    evidence_path, _ = _verify_structured_ref(artifact["literature_evidence"], path, EVIDENCE_SCHEMA, "literature_evidence", payload_field=EVIDENCE_HASH_FIELD, literature_hash=True)
    ledger_path, _ = _verify_structured_ref(artifact["candidate_ledger"], path, LEDGER_SCHEMA, "candidate_ledger", payload_field=LEDGER_HASH_FIELD, literature_hash=True)
    review_path, _ = _verify_structured_ref(artifact["review_source"], path, REVIEW_SCHEMA, "review_source", validate_payload=False)
    rw.require(rw.sha256_file(ledger_path) == artifact["candidate_ledger"]["sha256"], "candidate ledger drifted")

    if artifact["supersedes"] is not None:
        prior_path, prior_data = _verify_structured_ref(artifact["supersedes"], path, OUTPUT_SCHEMA, "supersedes")
        _validate(prior_path, seen)
        rw.require(prior_data["study_id"] == artifact["study_id"], "superseded support belongs to another study")

    display_paths = {
        "mechanism_network": artifact["mechanism_network"]["path"],
        "reaction_intake": artifact["reaction_intake"]["path"],
        "species_registry": artifact["species_registry"]["path"],
        "condition_model": artifact["condition_model"]["path"],
        "knowledge_snapshot": artifact["knowledge_snapshot"]["path"],
        "literature_evidence": artifact["literature_evidence"]["path"],
        "candidate_ledger": artifact["candidate_ledger"]["path"],
        "review_source": artifact["review_source"]["path"],
    }
    rebuilt = _compose(network_path, evidence_path, snapshot_path, review_path, display_paths=display_paths, seen=seen)
    rw.require(artifact == rebuilt, "mechanism-support artifact differs from independent reconstruction of its immutable sources")
    rw.require(rebuilt["reaction_intake"]["sha256"] == rw.sha256_file(intake_path), "rebuilt reaction-intake binding mismatch")
    rw.require(rebuilt["species_registry"]["sha256"] == rw.sha256_file(registry_path), "rebuilt species-registry binding mismatch")
    rw.require(rebuilt["condition_model"]["sha256"] == rw.sha256_file(condition_path), "rebuilt condition-model binding mismatch")
    seen.remove(resolved)
    return artifact


def validate(path: Path) -> dict[str, Any]:
    artifact = _validate(path)
    return {
        "schema": "gaussian-reaction-mechanism-support-validation/1",
        "artifact_schema": OUTPUT_SCHEMA,
        "support_id": artifact["support_id"],
        "study_id": artifact["study_id"],
        "gate_status": artifact["gate_status"],
        "row_count": len(artifact["matrix"]["rows"]),
        "column_count": len(artifact["matrix"]["evidence_columns"]),
        "cell_count": len(artifact["matrix"]["cells"]),
        "downstream_reviewable_edge_ids": artifact["downstream_reviewable_edge_ids"],
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="build one immutable offline mechanism-support sidecar")
    builder.add_argument("mechanism_network", type=Path)
    builder.add_argument("literature_evidence", type=Path)
    builder.add_argument("knowledge_snapshot", type=Path)
    builder.add_argument("--review", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    checker = commands.add_parser("validate", help="validate and independently rebuild a mechanism-support sidecar")
    checker.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.mechanism_network, args.literature_evidence, args.knowledge_snapshot, args.review, args.output)
        else:
            result = validate(args.artifact)
    except (rw.OfflineError, kb.OfflineError, OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
