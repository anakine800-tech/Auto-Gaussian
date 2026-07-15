#!/usr/bin/env python3
"""Build and validate an offline mechanism-support matrix view.

The matrix consumes, but never replaces, the owner-validated
``gaussian-reaction-mechanism-support/1`` evidence gate.  It performs no
literature search, chemistry inference, calculation planning, or live action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any

import mechanism_support as support_owner


rw = support_owner.rw
OUTPUT_SCHEMA = "gaussian-reaction-mechanism-support-matrix/1"
REVIEW_SCHEMA = "gaussian-reaction-mechanism-support-matrix-review/1"
SUPPORT_SCHEMA = support_owner.OUTPUT_SCHEMA
NETWORK_SCHEMA = support_owner.mn.OUTPUT_SCHEMA
REPO_ROOT = Path(__file__).resolve().parents[3]

REVIEW_KEYS = {
    "schema", "matrix_id", "study_id", "mechanism_support_payload_sha256",
    "mechanism_network_payload_sha256", "rows", "cells", "coverage",
    "row_promotion_reviews", "supersedes", "review_decision", "reviewer",
    "reviewed_at", "review_notes",
}
ROW_KEYS = {"row_id", "label", "edge_id", "stereochemical_channel", "bounded_hypothesis"}
CELL_KEYS = {
    "row_id", "support_record_id", "evidence_status", "bounded_claim",
    "applicability_dimensions", "mismatches", "alternative_explanations",
    "confidence", "reviewer_decision", "bounded_use", "blockers", "notes",
}
DIMENSIONS = {
    "net_transformation", "elementary_step_and_atom_correspondence",
    "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
    "atom_inventory_charge_multiplicity_and_spin",
    "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
    "experimental_conditions", "computational_protocol_and_validation",
}
EVIDENCE_STATUSES = {
    "positive", "negative", "contradictory", "inaccessible", "incomplete",
    "rejected", "no_evidence",
}
RELATIONSHIPS = {"supports", "contradicts", "does_not_address", "unknown"}
CONFIDENCE = {"high", "medium", "low", "unknown"}
CELL_DECISIONS = {"retained", "rejected", "blocked"}
BOUNDED_USES = {"matrix_comparison_only", "hypothesis_exploration_review"}
ROW_DISPOSITIONS = {"mandatory", "optional", "contradicted", "unresolved"}
NATIVE_STATUS = {
    "direct": "positive", "analogy": "positive", "contradictory": "contradictory",
    "missing": "no_evidence", "excluded": "rejected",
}


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw.require(set(value) == keys, f"{label} has unknown or missing fields: {sorted(set(value) ^ keys)}")
    return value


def _string(value: Any, label: str) -> str:
    return rw._require_string(value, label)


def _strings(value: Any, label: str) -> list[str]:
    result = rw._string_list(value, label)
    rw.require(len(result) == len(set(result)), f"{label} contains duplicates")
    return sorted(result)


def _channel(value: Any, label: str) -> str | None:
    rw.require(value is None or isinstance(value, str), f"{label} must be a string or null")
    return value


def _timestamp(value: Any, label: str) -> str:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise rw.OfflineError(f"{label} must be an ISO-8601 timestamp") from exc
    rw.require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return text


def _target_key(edge_id: str, channel: str | None) -> tuple[str, str]:
    return edge_id, "" if channel is None else channel


def _path_without_symlink(path: Path, label: str, *, must_exist: bool = True) -> Path:
    raw = os.fspath(path)
    rw.require(".." not in PurePath(raw).parts, f"{label} contains parent traversal")
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            rw.require(not current.is_symlink(), f"{label} contains a symlink: {current}")
    if must_exist:
        rw.require(absolute.is_file(), f"{label} is missing or not a regular file: {absolute}")
    return absolute


def _prepare_output(path: Path) -> Path:
    absolute = _path_without_symlink(path, "matrix output", must_exist=False)
    rw.require(not absolute.exists() and not absolute.is_symlink(), f"refusing to overwrite existing artifact: {absolute}")
    ancestor = absolute.parent
    missing: list[Path] = []
    while not ancestor.exists():
        rw.require(not ancestor.is_symlink(), f"matrix output contains a symlink ancestor: {ancestor}")
        missing.append(ancestor)
        ancestor = ancestor.parent
    _path_without_symlink(ancestor, "matrix output ancestor", must_exist=False)
    for directory in reversed(missing):
        directory.mkdir()
    return absolute


def _display_path(path: Path) -> str:
    absolute = path.expanduser().absolute()
    try:
        return absolute.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(absolute)


def _resolve_reference(reference: dict[str, Any], owner: Path, label: str) -> Path:
    path_value = _string(reference.get("path"), f"{label}.path")
    raw = Path(path_value)
    path = raw if raw.is_absolute() else REPO_ROOT / raw
    return _path_without_symlink(path, label)


def _artifact_ref(path: Path, data: dict[str, Any], schema: str, payload_sha256: str) -> dict[str, Any]:
    return {
        "path": _display_path(path), "sha256": rw.sha256_file(path),
        "size_bytes": path.stat().st_size, "schema": schema,
        "payload_sha256": payload_sha256,
    }


def _verify_ref(reference: Any, owner: Path, schema: str, label: str) -> tuple[Path, dict[str, Any]]:
    ref = _exact(reference, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    path = _resolve_reference(ref, owner, label)
    rw.require(ref["schema"] == schema, f"{label} schema mismatch")
    rw.require(ref["sha256"] == rw.sha256_file(path), f"{label} file hash drift")
    rw.require(ref["size_bytes"] == path.stat().st_size, f"{label} byte-size drift")
    data = rw.load_json(path)
    rw.require(data.get("schema") == schema, f"{label} bound document schema mismatch")
    owned_payload = rw.sha256_data(data) if schema == REVIEW_SCHEMA else data.get("payload_sha256")
    rw.require(owned_payload == ref["payload_sha256"], f"{label} payload hash drift")
    return path, data


def _column_id(record_id: str) -> str:
    return "col_" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:20]


def _columns(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id = {item["support_record_id"]: item for item in records}
    rw.require(len(by_id) == len(records), "owner support records contain duplicate IDs")
    columns = []
    for record_id in sorted(by_id):
        record = by_id[record_id]
        evidence = record["evidence"]
        classification = record["classification"]
        columns.append({
            "column_id": _column_id(record_id),
            "support_record_id": record_id,
            "edge_id": record["target"]["edge_id"],
            "stereochemical_channel": record["target"]["stereochemical_channel"],
            "candidate_id": evidence["candidate_id"],
            "claim_binding_id": evidence["claim_binding_id"],
            "location_binding_id": evidence["location_binding_id"],
            "classification_category": classification["category"],
            "claim_effect": classification["claim_effect"],
            "support_status": record["support_status"],
            "hypothesis_exploration_eligible": record["hypothesis_exploration_eligible"],
            "mechanism_claim_supported": record["mechanism_claim_supported"],
            "mechanism_claim_validated": False,
        })
    return columns, by_id


def _summaries(support: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in support["edge_channel_summary"]:
        key = _target_key(item["edge_id"], item["stereochemical_channel"])
        rw.require(key not in result, "owner support contains duplicate edge/channel summaries")
        result[key] = item
    return result


def _normalize_rows(raw: Any, summaries: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], set[tuple[str, str]]]:
    rw.require(isinstance(raw, list) and raw, "matrix rows must be a non-empty array")
    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    covered: set[tuple[str, str]] = set()
    for index, value in enumerate(raw):
        item = _exact(value, ROW_KEYS, f"rows[{index}]")
        row_id = rw._require_id(item["row_id"], f"rows[{index}].row_id")
        edge_id = rw._require_id(item["edge_id"], f"rows[{index}].edge_id")
        channel = _channel(item["stereochemical_channel"], f"rows[{index}].stereochemical_channel")
        key = _target_key(edge_id, channel)
        rw.require(row_id not in by_id, f"duplicate matrix row_id: {row_id}")
        rw.require(key in summaries and key not in covered, f"matrix row target is unknown or duplicated: {edge_id}")
        summary = summaries[key]
        row = {
            "row_id": row_id, "label": _string(item["label"], f"row {row_id}.label"),
            "edge_id": edge_id, "stereochemical_channel": channel,
            "bounded_hypothesis": _string(item["bounded_hypothesis"], f"row {row_id}.bounded_hypothesis"),
            "owner_gate": {
                "claim_support_status": summary["claim_support_status"],
                "hypothesis_exploration_eligible": summary["hypothesis_exploration_eligible"],
                "mechanism_claim_supported": summary["mechanism_claim_supported"],
                "mechanism_claim_validated": False,
            },
        }
        rows.append(row)
        by_id[row_id] = row
        covered.add(key)
    rows.sort(key=lambda item: item["row_id"])
    return rows, by_id, covered


def _normalize_dimensions(raw: Any, label: str) -> list[dict[str, str]]:
    rw.require(isinstance(raw, list) and len(raw) == len(DIMENSIONS), f"{label} must contain all nine dimensions")
    result = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        item = _exact(value, {"dimension", "value", "rationale"}, f"{label}[{index}]")
        dimension = _string(item["dimension"], f"{label}[{index}].dimension")
        rw.require(dimension in DIMENSIONS and dimension not in seen, f"{label} has an invalid or duplicate dimension")
        applicability = _string(item["value"], f"{label}[{index}].value")
        rw.require(applicability in support_owner.APPLICABILITY, f"{label}[{index}].value is invalid")
        seen.add(dimension)
        result.append({"dimension": dimension, "value": applicability, "rationale": _string(item["rationale"], f"{label}[{index}].rationale")})
    return sorted(result, key=lambda item: item["dimension"])


def _normalize_blockers(raw: Any, label: str) -> list[dict[str, str]]:
    rw.require(isinstance(raw, list), f"{label} must be an array")
    result = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        item = _exact(value, {"blocker_id", "code", "rationale"}, f"{label}[{index}]")
        blocker_id = rw._require_id(item["blocker_id"], f"{label}[{index}].blocker_id")
        rw.require(blocker_id not in seen, f"{label} contains duplicate blocker IDs")
        seen.add(blocker_id)
        result.append({"blocker_id": blocker_id, "code": rw._require_id(item["code"], f"{label}[{index}].code"), "rationale": _string(item["rationale"], f"{label}[{index}].rationale")})
    return sorted(result, key=lambda item: item["blocker_id"])


def _normalize_cells(raw: Any, rows: dict[str, dict[str, Any]], records: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    rw.require(isinstance(raw, list), "matrix cells must be an array")
    expected = {(row_id, record_id) for row_id in rows for record_id in records}
    seen: set[tuple[str, str]] = set()
    cells: list[dict[str, Any]] = []
    by_row = {row_id: [] for row_id in rows}
    flattened: list[dict[str, str]] = []
    for index, value in enumerate(raw):
        item = _exact(value, CELL_KEYS, f"cells[{index}]")
        row_id = rw._require_id(item["row_id"], f"cells[{index}].row_id")
        record_id = rw._require_id(item["support_record_id"], f"cells[{index}].support_record_id")
        pair = (row_id, record_id)
        rw.require(pair in expected and pair not in seen, "matrix cell references an unknown or duplicate row/column pair")
        seen.add(pair)
        status = _string(item["evidence_status"], f"cell {row_id}/{record_id}.evidence_status")
        rw.require(status in EVIDENCE_STATUSES, f"cell {row_id}/{record_id} evidence_status is invalid")
        claim = _exact(item["bounded_claim"], {"relationship", "text"}, f"cell {row_id}/{record_id}.bounded_claim")
        relationship = _string(claim["relationship"], f"cell {row_id}/{record_id}.relationship")
        rw.require(relationship in RELATIONSHIPS, f"cell {row_id}/{record_id} relationship is invalid")
        dimensions = _normalize_dimensions(item["applicability_dimensions"], f"cell {row_id}/{record_id}.applicability_dimensions")
        blockers = _normalize_blockers(item["blockers"], f"cell {row_id}/{record_id}.blockers")
        decision = _string(item["reviewer_decision"], f"cell {row_id}/{record_id}.reviewer_decision")
        bounded_use = _string(item["bounded_use"], f"cell {row_id}/{record_id}.bounded_use")
        confidence = _string(item["confidence"], f"cell {row_id}/{record_id}.confidence")
        rw.require(decision in CELL_DECISIONS and bounded_use in BOUNDED_USES and confidence in CONFIDENCE, f"cell {row_id}/{record_id} has an invalid review enum")
        if status in {"positive", "contradictory"}:
            rw.require(decision == "retained" and not blockers, f"cell {row_id}/{record_id} cannot retain positive/contradictory evidence while rejected or blocked")
        record = records[record_id]
        native = _target_key(rows[row_id]["edge_id"], rows[row_id]["stereochemical_channel"]) == _target_key(record["target"]["edge_id"], record["target"]["stereochemical_channel"])
        if native:
            expected_status = NATIVE_STATUS[record["classification"]["category"]]
            rw.require(status == expected_status, f"native matrix cell {row_id}/{record_id} conflicts with the owner evidence classification")
            expected_relationship = record["classification"]["claim_effect"]
            if expected_relationship == "excluded":
                expected_relationship = "does_not_address"
            rw.require(relationship == expected_relationship, f"native matrix cell {row_id}/{record_id} conflicts with the owner claim effect")
            owner_values = {entry["dimension"]: entry["value"] for entry in record["applicability_dimensions"]}
            rw.require({entry["dimension"]: entry["value"] for entry in dimensions} == owner_values, f"native matrix cell {row_id}/{record_id} conflicts with owner applicability")
        cell_id = "cell_" + hashlib.sha256(f"{row_id}\0{record_id}".encode()).hexdigest()[:20]
        cell = {
            "cell_id": cell_id, "row_id": row_id, "column_id": _column_id(record_id),
            "support_record_id": record_id, "native_owner_cell": native,
            "evidence_status": status,
            "bounded_claim": {"relationship": relationship, "text": _string(claim["text"], f"cell {row_id}/{record_id}.text")},
            "applicability_dimensions": dimensions,
            "mismatches": _strings(item["mismatches"], f"cell {row_id}/{record_id}.mismatches"),
            "alternative_explanations": _strings(item["alternative_explanations"], f"cell {row_id}/{record_id}.alternative_explanations"),
            "confidence": confidence, "reviewer_decision": decision,
            "bounded_use": bounded_use, "blockers": blockers,
            "notes": _strings(item["notes"], f"cell {row_id}/{record_id}.notes"),
        }
        cells.append(cell)
        by_row[row_id].append(cell)
        flattened.extend({"blocker_id": entry["blocker_id"], "code": entry["code"], "scope": cell_id, "rationale": entry["rationale"]} for entry in blockers)
    rw.require(seen == expected, "matrix must contain exactly one cell for every row/support-record intersection")
    return sorted(cells, key=lambda item: (item["row_id"], item["column_id"])), by_row, flattened


def _normalize_coverage(raw: Any, summaries: dict[tuple[str, str], dict[str, Any]], covered: set[tuple[str, str]], row_count: int, column_count: int, cell_count: int) -> dict[str, Any]:
    data = _exact(raw, {"excluded_edge_channels", "matrix_complete", "absent_evidence_explicit", "rationale"}, "coverage")
    rw.require(data["matrix_complete"] is True and data["absent_evidence_explicit"] is True, "matrix coverage must explicitly be complete")
    excluded: list[dict[str, Any]] = []
    excluded_keys: set[tuple[str, str]] = set()
    rw.require(isinstance(data["excluded_edge_channels"], list), "excluded_edge_channels must be an array")
    for index, value in enumerate(data["excluded_edge_channels"]):
        item = _exact(value, {"edge_id", "stereochemical_channel", "rationale"}, f"coverage.excluded_edge_channels[{index}]")
        edge_id = rw._require_id(item["edge_id"], f"excluded target {index}.edge_id")
        channel = _channel(item["stereochemical_channel"], f"excluded target {index}.stereochemical_channel")
        key = _target_key(edge_id, channel)
        rw.require(key in summaries and key not in covered and key not in excluded_keys, "excluded matrix target is unknown, covered, or duplicated")
        excluded_keys.add(key)
        excluded.append({"edge_id": edge_id, "stereochemical_channel": channel, "rationale": _string(item["rationale"], f"excluded target {index}.rationale")})
    rw.require(covered | excluded_keys == set(summaries), "every owner edge/channel summary must be matrix-covered or explicitly excluded")
    rw.require(cell_count == row_count * column_count, "matrix cell count is incomplete")
    return {
        "matrix_complete": True, "absent_evidence_explicit": True,
        "row_count": row_count, "column_count": column_count,
        "expected_cell_count": row_count * column_count, "actual_cell_count": cell_count,
        "covered_edge_channels": [{"edge_id": key[0], "stereochemical_channel": key[1] or None} for key in sorted(covered)],
        "excluded_edge_channels": sorted(excluded, key=lambda item: _target_key(item["edge_id"], item["stereochemical_channel"])),
        "rationale": _string(data["rationale"], "coverage.rationale"),
    }


def _normalize_dispositions(raw: Any, rows: dict[str, dict[str, Any]], cells: dict[str, list[dict[str, Any]]], top_decision: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    rw.require(isinstance(raw, list), "row_promotion_reviews must be an array")
    result: dict[str, dict[str, Any]] = {}
    downstream = []
    blockers = []
    for index, value in enumerate(raw):
        item = _exact(value, {"row_id", "disposition", "rationale", "reviewed_by", "reviewed_at"}, f"row_promotion_reviews[{index}]")
        row_id = rw._require_id(item["row_id"], f"row_promotion_reviews[{index}].row_id")
        rw.require(row_id in rows and row_id not in result, "row disposition references an unknown or duplicate row")
        disposition = _string(item["disposition"], f"row {row_id}.disposition")
        rw.require(disposition in ROW_DISPOSITIONS, f"row {row_id} disposition is invalid")
        statuses = {cell["evidence_status"] for cell in cells[row_id] if cell["reviewer_decision"] == "retained"}
        positive = "positive" in statuses
        contradictory = "contradictory" in statuses
        owner_eligible = rows[row_id]["owner_gate"]["hypothesis_exploration_eligible"]
        if disposition in {"mandatory", "optional"}:
            rw.require(positive and not contradictory, f"row {row_id} cannot be {disposition} without uncontradicted positive matrix evidence")
            rw.require(owner_eligible, f"row {row_id} cannot bypass the mechanism-support exploration gate")
            if top_decision != "blocked":
                downstream.append({
                    "row_id": row_id, "edge_id": rows[row_id]["edge_id"],
                    "stereochemical_channel": rows[row_id]["stereochemical_channel"],
                    "disposition": disposition, "owner_hypothesis_exploration_eligible": True,
                    "mechanism_claim_supported": rows[row_id]["owner_gate"]["mechanism_claim_supported"],
                    "mechanism_claim_validated": False,
                })
        elif disposition == "contradicted":
            rw.require(contradictory and not positive, f"row {row_id} contradicted disposition is inconsistent with its retained cells")
        else:
            rw.require((positive and contradictory) or not positive or not owner_eligible, f"row {row_id} unresolved disposition is inconsistent with its retained cells")
        if disposition in {"contradicted", "unresolved"}:
            blockers.append({
                "blocker_id": "row_" + hashlib.sha256(row_id.encode()).hexdigest()[:20],
                "code": "matrix_row_not_reviewable", "scope": row_id,
                "rationale": f"Matrix row {row_id} remains {disposition}; it is not exposed as downstream-reviewable.",
            })
        result[row_id] = {
            "row_id": row_id, "disposition": disposition,
            "rationale": _string(item["rationale"], f"row {row_id}.rationale"),
            "reviewed_by": _string(item["reviewed_by"], f"row {row_id}.reviewed_by"),
            "reviewed_at": _timestamp(item["reviewed_at"], f"row {row_id}.reviewed_at"),
        }
    rw.require(set(result) == set(rows), "every matrix row requires exactly one disposition review")
    return [result[key] for key in sorted(result)], sorted(downstream, key=lambda item: item["row_id"]), blockers


def _support_and_network(path: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    support_path = _path_without_symlink(path, "mechanism-support input")
    support_owner.validate(support_path)
    support = rw.load_json(support_path)
    network_path, network = support_owner._verify_input_ref(
        support["mechanism_network"], support_path, NETWORK_SCHEMA, "payload_sha256",
        "matrix mechanism network",
    )
    _path_without_symlink(network_path, "matrix mechanism network")
    return support, network_path, network


def _normalize_review(review: dict[str, Any], support: dict[str, Any]) -> tuple[Any, ...]:
    _exact(review, REVIEW_KEYS, "mechanism-support-matrix review")
    rw.require(review["schema"] == REVIEW_SCHEMA, "unrecognized mechanism-support-matrix review schema")
    matrix_id = rw._require_id(review["matrix_id"], "matrix_id")
    rw.require(review["study_id"] == support["study_id"], "matrix review study_id differs from owner support")
    rw.require(review["mechanism_support_payload_sha256"] == support["payload_sha256"], "matrix review mechanism-support hash mismatch")
    rw.require(review["mechanism_network_payload_sha256"] == support["mechanism_network"]["payload_sha256"], "matrix review mechanism-network hash mismatch")
    decision = _string(review["review_decision"], "matrix review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "invalid matrix review_decision")
    summaries = _summaries(support)
    rows, row_map, covered = _normalize_rows(review["rows"], summaries)
    columns, record_map = _columns(support["records"])
    cells, by_row, blockers = _normalize_cells(review["cells"], row_map, record_map)
    coverage = _normalize_coverage(review["coverage"], summaries, covered, len(rows), len(columns), len(cells))
    dispositions, downstream, row_blockers = _normalize_dispositions(review["row_promotion_reviews"], row_map, by_row, decision)
    blockers.extend(row_blockers)
    if support["gate_status"] == "blocked":
        downstream = []
        blockers.append({
            "blocker_id": "owner_support_gate_blocked", "code": "owner_support_gate_blocked",
            "scope": "mechanism_support", "rationale": "The owner mechanism-support evidence gate is blocked.",
        })
    blocker_ids = [item["blocker_id"] for item in blockers]
    rw.require(len(blocker_ids) == len(set(blocker_ids)), "matrix blockers contain duplicate IDs")
    review_meta = {
        "decision": decision, "reviewer": _string(review["reviewer"], "matrix reviewer"),
        "reviewed_at": _timestamp(review["reviewed_at"], "matrix reviewed_at"),
        "notes": _strings(review["review_notes"], "matrix review_notes"),
    }
    return matrix_id, rows, columns, cells, coverage, dispositions, downstream, sorted(blockers, key=lambda item: item["blocker_id"]), review_meta


def _normalize_supersedes(raw: Any, review_path: Path, study_id: str, seen: set[Path]) -> dict[str, Any] | None:
    if raw is None:
        return None
    item = _exact(raw, {"path", "payload_sha256"}, "supersedes")
    path_value = _string(item["path"], "supersedes.path")
    raw_path = Path(path_value)
    prior_path = raw_path if raw_path.is_absolute() else review_path.parent / raw_path
    prior = _validate(prior_path, seen)
    rw.require(prior["study_id"] == study_id, "superseded matrix belongs to a different study")
    rw.require(prior["payload_sha256"] == item["payload_sha256"], "supersedes payload hash mismatch")
    return _artifact_ref(_path_without_symlink(prior_path, "superseded matrix"), prior, OUTPUT_SCHEMA, prior["payload_sha256"])


def _compose(support_path: Path, review_path: Path, *, seen: set[Path] | None = None) -> dict[str, Any]:
    seen = set() if seen is None else seen
    support_path = _path_without_symlink(support_path, "mechanism-support input")
    review_path = _path_without_symlink(review_path, "mechanism-support-matrix review")
    support, network_path, network = _support_and_network(support_path)
    review = rw.load_json(review_path)
    matrix_id, rows, columns, cells, coverage, dispositions, downstream, blockers, review_meta = _normalize_review(review, support)
    supersedes = _normalize_supersedes(review["supersedes"], review_path, support["study_id"], seen)
    evidence_gate = {
        "gate_status": support["gate_status"],
        "exploration_eligible_edge_channels_present": support["exploration_eligible_edge_channels_present"],
        "mechanism_claim_support_present": support["mechanism_claim_support_present"],
        "mechanism_claim_validation_present": False,
        "owner_blocker_ids": sorted(item["blocker_id"] for item in support["blockers"]),
    }
    artifact = {
        "schema": OUTPUT_SCHEMA, "matrix_id": matrix_id, "study_id": support["study_id"],
        "mechanism_support": _artifact_ref(support_path, support, SUPPORT_SCHEMA, support["payload_sha256"]),
        "mechanism_network": _artifact_ref(network_path, network, NETWORK_SCHEMA, network["payload_sha256"]),
        "review_source": _artifact_ref(review_path, review, REVIEW_SCHEMA, rw.sha256_data(review)),
        "supersedes": supersedes, "evidence_gate": evidence_gate,
        "matrix": {"rows": rows, "evidence_columns": columns, "cells": cells},
        "coverage": coverage, "row_dispositions": dispositions,
        "downstream_reviewable_targets": downstream, "blockers": blockers,
        "review": review_meta, "gate_status": rw._gate_status(review_meta["decision"], blockers),
        "claim_ceiling": "bounded_hypothesis_space_not_mechanism_proof",
        "mechanism_proven": False, "mechanism_claim_validation_present": False,
        "calculation_ready": False, "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    return artifact


def build(support_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    artifact = _compose(support_path, review_path)
    destination = _prepare_output(output)
    try:
        with destination.open("xb") as handle:
            handle.write(rw.canonical_bytes(artifact))
    except FileExistsError as exc:
        raise rw.OfflineError(f"refusing to overwrite existing artifact: {destination}") from exc
    return artifact


def _validate(path: Path, seen: set[Path] | None = None) -> dict[str, Any]:
    seen = set() if seen is None else seen
    path = _path_without_symlink(path, "mechanism-support-matrix artifact")
    resolved = path.resolve()
    rw.require(resolved not in seen, "mechanism-support-matrix supersession cycle detected")
    seen.add(resolved)
    artifact = rw.load_json(path)
    keys = {
        "schema", "matrix_id", "study_id", "mechanism_support", "mechanism_network",
        "review_source", "supersedes", "evidence_gate", "matrix", "coverage",
        "row_dispositions", "downstream_reviewable_targets", "blockers", "review",
        "gate_status", "claim_ceiling", "mechanism_proven",
        "mechanism_claim_validation_present", "calculation_ready",
        "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "mechanism-support-matrix artifact")
    rw.require(artifact["schema"] == OUTPUT_SCHEMA, "unrecognized mechanism-support-matrix artifact schema")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["claim_ceiling"] == "bounded_hypothesis_space_not_mechanism_proof" and artifact["mechanism_proven"] is False, "matrix exceeds its claim ceiling")
    rw.require(artifact["mechanism_claim_validation_present"] is False, "matrix cannot validate a mechanism claim")
    rw.require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "matrix violates offline safety constants")
    support_path, support = _verify_ref(artifact["mechanism_support"], path, SUPPORT_SCHEMA, "mechanism_support")
    support_owner.validate(support_path)
    network_path, network = _verify_ref(artifact["mechanism_network"], path, NETWORK_SCHEMA, "mechanism_network")
    owner_network_path, owner_network = support_owner._verify_input_ref(support["mechanism_network"], support_path, NETWORK_SCHEMA, "payload_sha256", "matrix owner network")
    rw.require(network_path.resolve() == owner_network_path.resolve() and network == owner_network, "matrix network differs from the owner support binding")
    review_path, review = _verify_ref(artifact["review_source"], path, REVIEW_SCHEMA, "review_source")
    rw.require(artifact["review_source"]["payload_sha256"] == rw.sha256_data(review), "matrix review payload hash drift")
    if artifact["supersedes"] is not None:
        prior_path, prior = _verify_ref(artifact["supersedes"], path, OUTPUT_SCHEMA, "supersedes")
        _validate(prior_path, seen)
        rw.require(prior["study_id"] == artifact["study_id"], "superseded matrix belongs to another study")
    rebuilt = _compose(support_path, review_path, seen=seen)
    rw.require(artifact == rebuilt, "mechanism-support-matrix differs from independent reconstruction of its immutable sources")
    seen.remove(resolved)
    return artifact


def validate(path: Path) -> dict[str, Any]:
    artifact = _validate(path)
    return {
        "schema": "gaussian-reaction-mechanism-support-matrix-validation/1",
        "artifact_schema": OUTPUT_SCHEMA, "matrix_id": artifact["matrix_id"],
        "study_id": artifact["study_id"], "gate_status": artifact["gate_status"],
        "row_count": len(artifact["matrix"]["rows"]),
        "column_count": len(artifact["matrix"]["evidence_columns"]),
        "cell_count": len(artifact["matrix"]["cells"]),
        "downstream_reviewable_target_count": len(artifact["downstream_reviewable_targets"]),
        "payload_sha256": artifact["payload_sha256"], "live_actions": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="build one immutable offline mechanism-support matrix")
    builder.add_argument("mechanism_support", type=Path)
    builder.add_argument("--review", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    checker = commands.add_parser("validate", help="validate and independently rebuild one matrix")
    checker.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build(args.mechanism_support, args.review, args.output) if args.command == "build" else validate(args.artifact)
    except (rw.OfflineError, OSError, ValueError, AssertionError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
