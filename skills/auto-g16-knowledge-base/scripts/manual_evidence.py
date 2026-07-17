#!/usr/bin/env python3
"""Build immutable offline receipts from a private manual-retrieval SQLite view.

The adapter opens SQLite in immutable read-only mode, permits only SELECT
operations, and never stores source text or machine paths in a receipt.  It
does not select a method, render Gaussian input, authorize a calculation, or
modify any Auto-G16 knowledge or scientific-maturity record.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


RECEIPT_SCHEMA = "auto-g16-manual-evidence-receipt/1"
ADAPTER_SCHEMA = "auto-g16-manual-retrieval-adapter/1"
REVIEW_SCHEMA = "auto-g16-manual-evidence-review/1"
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")
PARAM_RE = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
MACHINE_PATH_RE = re.compile(
    rf"(?:^|[\s'\"])(?:/{'Users'}/|/home/|[A-Za-z]:[\\/])"
)
TEXT_QUALITIES = {
    "embedded_text",
    "embedded_ocr_unreviewed",
    "legacy_word_text_pagination_unstable",
    "image_only",
}
DEGRADED_TEXT_QUALITIES = TEXT_QUALITIES - {"embedded_text"}
SOURCE_KINDS = {
    "gaussian_program_manual",
    "gaussian_associated_text",
    "general_electronic_structure",
}
CLAIM_SCOPES = {
    "gaussian_syntax_or_version",
    "gaussian_nonversion_concept",
    "general_electronic_structure",
}
LOCATOR_KINDS = {"physical_page", "logical_chunk", "metadata"}
MAJOR_VERSIONS = {"G98", "G03", "G09", "G16", "other"}
VISUAL_STATUSES = {
    "reviewed",
    "not_reviewed",
    "unavailable",
    "not_applicable_logical_chunk_only",
}
CHUNK_REVIEW_STATUSES = {"reviewed", "not_reviewed", "not_applicable_no_logical_chunk"}
APPLICABILITY_DECISIONS = {
    "applicable",
    "applicable_with_limits",
    "not_applicable",
    "blocked_pending_installed_revision_review",
    "blocked_insufficient_evidence",
}
DOWNSTREAM_ROLES = {
    "manual_lookup_evidence",
    "installed_revision_applicability_evidence",
    "scientific_maturity_supporting_evidence",
    "protocol_candidate_support",
    "troubleshooting_support",
}
REQUIRED_RESULT_COLUMNS = (
    "result_id",
    "canonical_store_digest",
    "source_record_id",
    "source_revision",
    "source_payload_sha256",
    "source_object_sha256",
    "source_kind",
    "locator_kind",
    "page",
    "logical_chunk",
    "text_quality",
    "text_quality_notes",
    "source_program",
    "source_major_version",
    "source_version",
    "evidence_text",
)
MAX_QUERY_CHARS = 1000
MAX_PARAPHRASE_CHARS = 600
MAX_SHORT_QUOTE_CHARS = 120
MAX_EVIDENCE_TEXT_CHARS = 250_000
SQLITE_PROGRESS_INTERVAL = 1000
SQLITE_VM_STEP_BUDGET = 1_000_000
ALLOWED_SQL_FUNCTIONS = {"instr", "lower"}
CLAIM_CEILING = (
    "manual_evidence_only_no_method_selection_input_generation_"
    "calculation_readiness_or_submission_authority"
)


class ManualEvidenceError(ValueError):
    """The requested operation violates the manual-evidence contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManualEvidenceError(message)


def _reject_constant(value: str) -> None:
    raise ManualEvidenceError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManualEvidenceError(f"could not read JSON: {exc}") from exc
    require(isinstance(value, dict), "top-level JSON must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ManualEvidenceError(f"could not hash file: {exc}") from exc
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value))
    except FileExistsError:
        raise ManualEvidenceError("refusing to overwrite an existing artifact") from None


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def text(value: Any, label: str, *, maximum: int = 2000) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    require(len(value) <= maximum, f"{label} exceeds {maximum} characters")
    require(MACHINE_PATH_RE.search(value) is None, f"{label} must not contain a machine absolute path")
    return value


def nullable_text(value: Any, label: str, *, maximum: int = 2000) -> str | None:
    if value is None:
        return None
    return text(value, label, maximum=maximum)


def identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} is invalid")
    return value


def sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be a lowercase SHA-256")
    return value


def timestamp(value: Any, label: str) -> str:
    candidate = text(value, label, maximum=80)
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManualEvidenceError(f"{label} must be an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return candidate


def string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    result = [text(item, f"{label} item", maximum=1000) for item in value]
    require(len(result) == len(set(result)), f"{label} must not contain duplicates")
    if nonempty:
        require(bool(result), f"{label} must not be empty")
    return result


def payload_sha(receipt: dict[str, Any]) -> str:
    payload = copy.deepcopy(receipt)
    payload.pop("payload_sha256", None)
    return canonical_sha(payload)


def _audit_no_machine_paths(value: Any, label: str = "artifact") -> None:
    if isinstance(value, str):
        require(MACHINE_PATH_RE.search(value) is None, f"{label} contains a machine absolute path")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _audit_no_machine_paths(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _audit_no_machine_paths(item, f"{label}.{key}")


def validate_sql(sql: Any, label: str, parameters: set[str]) -> str:
    statement = text(sql, label, maximum=20_000).strip()
    lowered = statement.casefold()
    require(re.match(r"^(?:select|with)\b", lowered) is not None, f"{label} must be one SELECT/WITH statement")
    require(";" not in statement, f"{label} must not contain a statement separator")
    require("--" not in statement and "/*" not in statement and "*/" not in statement, f"{label} must not contain SQL comments")
    actual = set(PARAM_RE.findall(statement))
    require(actual == parameters, f"{label} parameters must be exactly: {', '.join(sorted(parameters))}")
    return statement


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    data = exact(
        config,
        {"schema", "adapter_id", "query_sql", "selection_sql", "preview_char_limit"},
        "adapter config",
    )
    require(data["schema"] == ADAPTER_SCHEMA, "adapter config schema is unsupported")
    identifier(data["adapter_id"], "adapter_id")
    validate_sql(data["query_sql"], "query_sql", {"limit", "query"})
    validate_sql(data["selection_sql"], "selection_sql", {"query", "result_id"})
    require(
        isinstance(data["preview_char_limit"], int)
        and not isinstance(data["preview_char_limit"], bool)
        and 40 <= data["preview_char_limit"] <= 500,
        "preview_char_limit must be an integer from 40 through 500",
    )
    _audit_no_machine_paths(data, "adapter config")
    return data


def _database_snapshot(path: Path, expected_sha256: str) -> tuple[tuple[int, int, int, int], str]:
    sha(expected_sha256, "expected database SHA-256")
    require(path.exists() and path.is_file(), "retrieval database must be a regular file")
    require(not path.is_symlink(), "retrieval database must not be a symlink")
    for suffix in ("-journal", "-wal", "-shm"):
        require(not Path(str(path) + suffix).exists(), f"retrieval database has an unstable SQLite sidecar: {suffix}")
    stat = path.stat()
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    digest = file_sha(path)
    require(digest == expected_sha256, "retrieval database SHA-256 mismatch")
    return signature, digest


def _authorizer(
    action: int,
    _arg1: str | None,
    arg2: str | None,
    _db: str | None,
    _trigger: str | None,
) -> int:
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if (arg2 or "").casefold() in ALLOWED_SQL_FUNCTIONS else sqlite3.SQLITE_DENY
    allowed = {
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_RECURSIVE,
        sqlite3.SQLITE_SELECT,
    }
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def _normalize_row(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    require(set(raw) == set(REQUIRED_RESULT_COLUMNS), "adapter result columns differ from the required closed interface")
    result_id = text(raw["result_id"], "result_id", maximum=300)
    store_digest = sha(raw["canonical_store_digest"], "canonical_store_digest")
    source_record_id = identifier(raw["source_record_id"], "source_record_id")
    source_revision = text(raw["source_revision"], "source_revision", maximum=300)
    source_payload = sha(raw["source_payload_sha256"], "source_payload_sha256")
    source_object = sha(raw["source_object_sha256"], "source_object_sha256")
    source_kind = raw["source_kind"]
    require(source_kind in SOURCE_KINDS, "source_kind is unsupported")
    locator_kind = raw["locator_kind"]
    require(locator_kind in LOCATOR_KINDS, "locator_kind is unsupported")
    page = raw["page"]
    if page is not None:
        require(isinstance(page, int) and not isinstance(page, bool) and page >= 1, "page must be null or a positive integer")
    logical_chunk = nullable_text(raw["logical_chunk"], "logical_chunk", maximum=300)
    require(page is not None or logical_chunk is not None, "source locator requires page or logical_chunk")
    if locator_kind == "physical_page":
        require(page is not None, "physical_page locator requires a positive page")
    else:
        require(page is None and logical_chunk is not None, f"{locator_kind} locator requires page=null and a stable logical_chunk")
    quality = raw["text_quality"]
    require(quality in TEXT_QUALITIES, "text_quality is unsupported")
    quality_note = nullable_text(raw["text_quality_notes"], "text_quality_notes", maximum=1000)
    if quality in DEGRADED_TEXT_QUALITIES:
        require(quality_note is not None, "unreviewed OCR, legacy Word, or image-only text requires text_quality_notes")
    program = nullable_text(raw["source_program"], "source_program", maximum=80)
    major = raw["source_major_version"]
    require(major is None or major in MAJOR_VERSIONS, "source_major_version is unsupported")
    version = nullable_text(raw["source_version"], "source_version", maximum=200)
    version_fields = (program, major, version)
    require(all(item is None for item in version_fields) or all(item is not None for item in version_fields), "source program/version fields must be all present or all null")
    if program is not None:
        require(program == "Gaussian", "populated source_program must be exactly Gaussian")
    if source_kind == "gaussian_program_manual":
        require(all(item is not None for item in version_fields), "Gaussian program-manual evidence requires source program/version")
    if source_kind == "general_electronic_structure":
        require(all(item is None for item in version_fields), "general electronic-structure sources must not fabricate Gaussian program/version")
    evidence_text = raw["evidence_text"]
    require(isinstance(evidence_text, str), "evidence_text must be a string")
    require(len(evidence_text) <= MAX_EVIDENCE_TEXT_CHARS, "evidence_text exceeds the bounded adapter limit")
    require(evidence_text.strip() or quality == "image_only", "empty evidence_text is allowed only for image_only sources")
    text_digest = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
    normalized = {
        "result_id": result_id,
        "canonical_store_digest": store_digest,
        "source_record_id": source_record_id,
        "source_revision": source_revision,
        "source_payload_sha256": source_payload,
        "source_object_sha256": source_object,
        "source_kind": source_kind,
        "locator_kind": locator_kind,
        "page": page,
        "logical_chunk": logical_chunk,
        "text_quality": quality,
        "text_quality_notes": quality_note,
        "source_program": program,
        "source_major_version": major,
        "source_version": version,
        "retrieved_text_sha256": text_digest,
    }
    return normalized, evidence_text


def execute_readonly(
    database: Path,
    expected_sha256: str,
    sql: str,
    parameters: dict[str, Any],
    *,
    max_rows: int,
) -> list[tuple[dict[str, Any], str]]:
    require(isinstance(max_rows, int) and not isinstance(max_rows, bool) and max_rows >= 1, "read-only query max_rows must be positive")
    before, digest = _database_snapshot(database, expected_sha256)
    resolved = database.absolute()
    uri = f"file:{quote(str(resolved), safe='/')}?mode=ro&immutable=1"
    connection: sqlite3.Connection | None = None
    progress_steps = 0
    progress_exceeded = False

    def progress() -> int:
        nonlocal progress_steps, progress_exceeded
        progress_steps += SQLITE_PROGRESS_INTERVAL
        if progress_steps > SQLITE_VM_STEP_BUDGET:
            progress_exceeded = True
            return 1
        return 0

    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_authorizer(_authorizer)
        connection.set_progress_handler(progress, SQLITE_PROGRESS_INTERVAL)
        cursor = connection.execute(sql, parameters)
        names = tuple(item[0] for item in (cursor.description or ()))
        require(len(names) == len(set(names)), "adapter result contains duplicate column aliases")
        require(set(names) == set(REQUIRED_RESULT_COLUMNS), "adapter SQL must return the exact required column aliases")
        raw_rows = [dict(row) for row in cursor.fetchmany(max_rows + 1)]
        require(len(raw_rows) <= max_rows, f"read-only adapter returned more than the allowed {max_rows} rows")
    except sqlite3.Error as exc:
        if progress_exceeded:
            raise ManualEvidenceError(f"read-only adapter exceeded the deterministic {SQLITE_VM_STEP_BUDGET}-step budget") from exc
        raise ManualEvidenceError(f"read-only adapter query failed: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    after, after_digest = _database_snapshot(database, expected_sha256)
    require(before == after and digest == after_digest, "retrieval database changed during the read-only query")
    normalized = [_normalize_row(row) for row in raw_rows]
    ids = [row[0]["result_id"] for row in normalized]
    require(len(ids) == len(set(ids)), "adapter results contain duplicate result_id values")
    return normalized


def validate_visual_review(value: Any, *, page: int | None) -> dict[str, Any]:
    review = exact(value, {"status", "reviewer", "reviewed_at", "notes"}, "whole_page_visual_review")
    require(review["status"] in VISUAL_STATUSES, "whole_page_visual_review.status is unsupported")
    reviewer = nullable_text(review["reviewer"], "whole_page_visual_review.reviewer", maximum=200)
    reviewed_at = review["reviewed_at"]
    notes = string_list(review["notes"], "whole_page_visual_review.notes")
    if review["status"] == "reviewed":
        require(reviewer is not None and reviewed_at is not None, "reviewed whole-page evidence requires reviewer and reviewed_at")
        timestamp(reviewed_at, "whole_page_visual_review.reviewed_at")
    else:
        require(reviewer is None and reviewed_at is None, "unreviewed whole-page evidence cannot claim reviewer or reviewed_at")
        require(bool(notes), "non-reviewed whole-page status requires notes")
    if review["status"] == "not_applicable_logical_chunk_only":
        require(page is None, "page-located evidence cannot claim logical-chunk-only visual status")
    return review


def validate_chunk_review(value: Any, *, logical_chunk: str | None) -> dict[str, Any]:
    review = exact(value, {"status", "reviewer", "reviewed_at", "notes"}, "logical_chunk_review")
    require(review["status"] in CHUNK_REVIEW_STATUSES, "logical_chunk_review.status is unsupported")
    reviewer = nullable_text(review["reviewer"], "logical_chunk_review.reviewer", maximum=200)
    reviewed_at = review["reviewed_at"]
    notes = string_list(review["notes"], "logical_chunk_review.notes")
    if review["status"] == "reviewed":
        require(reviewer is not None and reviewed_at is not None, "reviewed logical chunk requires reviewer and reviewed_at")
        timestamp(reviewed_at, "logical_chunk_review.reviewed_at")
    else:
        require(reviewer is None and reviewed_at is None, "unreviewed logical chunk cannot claim reviewer or reviewed_at")
        require(bool(notes), "non-reviewed logical-chunk status requires notes")
    if logical_chunk is None:
        require(review["status"] == "not_applicable_no_logical_chunk", "evidence without logical_chunk requires an explicit not-applicable chunk review")
    else:
        require(review["status"] != "not_applicable_no_logical_chunk", "logical-chunk evidence cannot claim chunk review is not applicable")
    return review


def validate_installed_review(value: Any) -> dict[str, Any]:
    review = exact(value, {"status", "reviewer", "reviewed_at", "evidence_sha256", "notes"}, "installed_revision_review")
    require(review["status"] in {"reviewed", "not_reviewed", "not_applicable_non_version_claim"}, "installed_revision_review.status is unsupported")
    reviewer = nullable_text(review["reviewer"], "installed_revision_review.reviewer", maximum=200)
    evidence = review["evidence_sha256"]
    require(isinstance(evidence, list), "installed_revision_review.evidence_sha256 must be an array")
    for index, digest in enumerate(evidence):
        sha(digest, f"installed_revision_review.evidence_sha256[{index}]")
    require(len(evidence) == len(set(evidence)), "installed_revision_review evidence hashes must be unique")
    notes = string_list(review["notes"], "installed_revision_review.notes")
    if review["status"] == "reviewed":
        require(reviewer is not None and review["reviewed_at"] is not None, "installed-revision review requires reviewer and reviewed_at")
        timestamp(review["reviewed_at"], "installed_revision_review.reviewed_at")
        require(bool(evidence) and bool(notes), "installed-revision review requires hash-bound evidence and notes")
    elif review["status"] == "not_reviewed":
        require(reviewer is None and review["reviewed_at"] is None, "not_reviewed cannot claim reviewer or reviewed_at")
        require(not evidence, "not_reviewed cannot claim installed-revision evidence")
        require(bool(notes), "not_reviewed requires a fail-closed note")
    else:
        require(reviewer is None and review["reviewed_at"] is None, "not-applicable installed-revision status cannot claim reviewer or reviewed_at")
        require(not evidence, "not-applicable installed-revision status cannot claim version evidence")
        require(bool(notes), "not-applicable installed-revision status requires notes")
    return review


def validate_statement(statement_type: Any, value: Any, label: str) -> str:
    require(statement_type in {"paraphrase", "short_quote"}, "statement_type is unsupported")
    result = text(value, label, maximum=MAX_PARAPHRASE_CHARS)
    if statement_type == "short_quote":
        require(len(result.split()) <= 25, "short_quote exceeds the 25-word limit")
        require(len(result) <= MAX_SHORT_QUOTE_CHARS, f"short_quote exceeds the {MAX_SHORT_QUOTE_CHARS}-character limit")
    return result


def validate_review(value: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    data = exact(
        value,
        {
            "schema",
            "receipt_id",
            "query",
            "selected_result_id",
            "claim_scope",
            "statement_type",
            "short_paraphrase",
            "whole_page_visual_review",
            "logical_chunk_review",
            "target_installation",
            "installed_revision_review",
            "applicability_decision",
            "applicability_rationale",
            "uncertainties",
            "reviewer",
            "reviewed_at",
            "downstream_role",
        },
        "manual evidence review",
    )
    require(data["schema"] == REVIEW_SCHEMA, "manual evidence review schema is unsupported")
    identifier(data["receipt_id"], "receipt_id")
    query = text(data["query"], "query", maximum=MAX_QUERY_CHARS)
    require(query.strip() == query, "query must not have leading or trailing whitespace")
    require(text(data["selected_result_id"], "selected_result_id", maximum=300) == row["result_id"], "selected_result_id does not match the retrieval row")
    require(data["claim_scope"] in CLAIM_SCOPES, "claim_scope is unsupported")
    if data["claim_scope"] == "general_electronic_structure":
        require(row["source_kind"] == "general_electronic_structure", "general claim_scope requires a general electronic-structure source")
    if data["claim_scope"] == "gaussian_syntax_or_version":
        require(row["source_kind"] != "general_electronic_structure", "general theory sources cannot support a Gaussian version-specific claim")
        require(row["source_program"] == "Gaussian" and row["source_major_version"] is not None and row["source_version"] is not None, "version-specific claim requires Gaussian source version metadata")
    if data["claim_scope"] == "gaussian_nonversion_concept":
        require(row["source_kind"] != "general_electronic_structure", "Gaussian non-version claim requires a Gaussian manual or associated text")
    validate_statement(data["statement_type"], data["short_paraphrase"], "short_paraphrase")
    visual_review = validate_visual_review(data["whole_page_visual_review"], page=row["page"])
    chunk_review = validate_chunk_review(data["logical_chunk_review"], logical_chunk=row["logical_chunk"])
    target = exact(data["target_installation"], {"program", "major_version", "installed_revision"}, "target_installation")
    require(text(target["program"], "target_installation.program", maximum=80) == "Gaussian", "target program must be exactly Gaussian")
    require(target["major_version"] in MAJOR_VERSIONS, "target major_version is unsupported")
    text(target["installed_revision"], "target_installation.installed_revision", maximum=200)
    installed = validate_installed_review(data["installed_revision_review"])
    decision = data["applicability_decision"]
    require(decision in APPLICABILITY_DECISIONS, "applicability_decision is unsupported")
    text(data["applicability_rationale"], "applicability_rationale", maximum=1000)
    uncertainties = string_list(data["uncertainties"], "uncertainties")
    reviewer = text(data["reviewer"], "reviewer", maximum=200)
    timestamp(data["reviewed_at"], "reviewed_at")
    require(data["downstream_role"] in DOWNSTREAM_ROLES, "downstream_role is unsupported")

    version_claim = data["claim_scope"] == "gaussian_syntax_or_version"
    cross_version = version_claim and row["source_major_version"] != target["major_version"]
    g09_to_g16 = version_claim and row["source_major_version"] == "G09" and target["major_version"] == "G16"
    if version_claim:
        require(installed["status"] != "not_applicable_non_version_claim", "version-specific evidence cannot skip installed-revision review as non-version evidence")
        if g09_to_g16 and installed["status"] != "reviewed":
            require(
                decision == "blocked_pending_installed_revision_review",
                "G09-to-G16 evidence must fail closed until the target installed revision is reviewed",
            )
        if decision in {"applicable", "applicable_with_limits"}:
            require(installed["status"] == "reviewed", "positive version-specific applicability requires installed-revision review")
        if cross_version and installed["status"] != "reviewed":
            require(decision.startswith("blocked_"), "unreviewed cross-version evidence must remain blocked")
    else:
        require(decision != "blocked_pending_installed_revision_review", "non-version claims must not fabricate a pending Gaussian version gate")
        require(installed["status"] != "not_reviewed", "non-version claims must mark installed-revision review not applicable or provide an actual review")
    if decision == "blocked_pending_installed_revision_review":
        require(installed["status"] == "not_reviewed", "pending-installed-revision decision requires not_reviewed status")
    if decision in {"applicable", "applicable_with_limits"}:
        if row["page"] is not None:
            require(visual_review["status"] == "reviewed", "positive page-located applicability requires whole-page visual review")
        if row["logical_chunk"] is not None:
            require(chunk_review["status"] == "reviewed", "positive logical-chunk applicability requires logical-chunk review")
    if row["text_quality"] in DEGRADED_TEXT_QUALITIES:
        require(bool(uncertainties), "degraded text quality requires explicit uncertainty propagation")
        require(decision != "applicable", "degraded text quality cannot produce unqualified applicability")
    if row["text_quality"] == "legacy_word_text_pagination_unstable":
        require(row["locator_kind"] == "logical_chunk" and row["page"] is None and row["logical_chunk"] is not None, "legacy Word pagination-unstable evidence must use a logical_chunk locator instead of a page")
    if decision == "applicable_with_limits":
        require(bool(uncertainties), "applicable_with_limits requires explicit uncertainties")
    _audit_no_machine_paths(data, "manual evidence review")
    require(reviewer.strip() == reviewer, "reviewer must not have surrounding whitespace")
    return data


def build_receipt(
    config_path: Path,
    database: Path,
    expected_db_sha256: str,
    review_path: Path,
    output: Path,
) -> dict[str, Any]:
    config = validate_config(load_json(config_path))
    review = load_json(review_path)
    query = review.get("query")
    result_id = review.get("selected_result_id")
    text(query, "query", maximum=MAX_QUERY_CHARS)
    text(result_id, "selected_result_id", maximum=300)
    rows = execute_readonly(
        database,
        expected_db_sha256,
        config["selection_sql"],
        {"query": query, "result_id": result_id},
        max_rows=1,
    )
    require(len(rows) == 1, "selection_sql must return exactly one row")
    row, _source_text = rows[0]
    validate_review(review, row)
    review_file_sha = file_sha(review_path)
    config_file_sha = file_sha(config_path)
    row_sha = canonical_sha(row)
    limitations = [] if row["text_quality_notes"] is None else [row["text_quality_notes"]]
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "receipt_id": review["receipt_id"],
        "retrieval": {
            "adapter_id": config["adapter_id"],
            "adapter_config_sha256": config_file_sha,
            "retrieval_database_sha256": expected_db_sha256,
            "canonical_store_digest": row["canonical_store_digest"],
            "result_id": row["result_id"],
            "retrieval_row_sha256": row_sha,
            "retrieved_text_sha256": row["retrieved_text_sha256"],
            "query": review["query"],
        },
        "source": {
            "record_id": row["source_record_id"],
            "revision": row["source_revision"],
            "payload_sha256": row["source_payload_sha256"],
            "object_sha256": row["source_object_sha256"],
            "source_kind": row["source_kind"],
            "claim_scope": review["claim_scope"],
            "locator": {"kind": row["locator_kind"], "page": row["page"], "logical_chunk": row["logical_chunk"]},
            "text_quality": {"classification": row["text_quality"], "limitations": limitations},
            "program": {
                "name": row["source_program"],
                "major_version": row["source_major_version"],
                "version": row["source_version"],
            },
        },
        "evidence": {
            "statement_type": review["statement_type"],
            "short_paraphrase": review["short_paraphrase"],
            "whole_page_visual_review": copy.deepcopy(review["whole_page_visual_review"]),
            "logical_chunk_review": copy.deepcopy(review["logical_chunk_review"]),
        },
        "target_installation": copy.deepcopy(review["target_installation"]),
        "applicability": {
            "decision": review["applicability_decision"],
            "rationale": review["applicability_rationale"],
            "installed_revision_review": copy.deepcopy(review["installed_revision_review"]),
        },
        "uncertainties": copy.deepcopy(review["uncertainties"]),
        "review": {
            "reviewer": review["reviewer"],
            "reviewed_at": review["reviewed_at"],
            "review_input_sha256": review_file_sha,
        },
        "downstream_role": review["downstream_role"],
        "claim_ceiling": CLAIM_CEILING,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "no_method_selection_authorization": True,
        "no_input_generation_authorization": True,
        "payload_sha256": None,
    }
    receipt["payload_sha256"] = payload_sha(receipt)
    validate_receipt(receipt)
    write_json(output, receipt)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    data = exact(
        receipt,
        {
            "schema",
            "receipt_id",
            "retrieval",
            "source",
            "evidence",
            "target_installation",
            "applicability",
            "uncertainties",
            "review",
            "downstream_role",
            "claim_ceiling",
            "calculation_ready",
            "no_submission_authorization",
            "no_method_selection_authorization",
            "no_input_generation_authorization",
            "payload_sha256",
        },
        "manual evidence receipt",
    )
    require(data["schema"] == RECEIPT_SCHEMA, "manual evidence receipt schema is unsupported")
    identifier(data["receipt_id"], "receipt_id")
    retrieval = exact(
        data["retrieval"],
        {
            "adapter_id",
            "adapter_config_sha256",
            "retrieval_database_sha256",
            "canonical_store_digest",
            "result_id",
            "retrieval_row_sha256",
            "retrieved_text_sha256",
            "query",
        },
        "retrieval",
    )
    identifier(retrieval["adapter_id"], "retrieval.adapter_id")
    for field in (
        "adapter_config_sha256",
        "retrieval_database_sha256",
        "canonical_store_digest",
        "retrieval_row_sha256",
        "retrieved_text_sha256",
    ):
        sha(retrieval[field], f"retrieval.{field}")
    text(retrieval["result_id"], "retrieval.result_id", maximum=300)
    text(retrieval["query"], "retrieval.query", maximum=MAX_QUERY_CHARS)

    source = exact(data["source"], {"record_id", "revision", "payload_sha256", "object_sha256", "source_kind", "claim_scope", "locator", "text_quality", "program"}, "source")
    identifier(source["record_id"], "source.record_id")
    text(source["revision"], "source.revision", maximum=300)
    sha(source["payload_sha256"], "source.payload_sha256")
    sha(source["object_sha256"], "source.object_sha256")
    require(source["source_kind"] in SOURCE_KINDS, "source.source_kind is unsupported")
    require(source["claim_scope"] in CLAIM_SCOPES, "source.claim_scope is unsupported")
    locator = exact(source["locator"], {"kind", "page", "logical_chunk"}, "source.locator")
    require(locator["kind"] in LOCATOR_KINDS, "source.locator.kind is unsupported")
    page = locator["page"]
    if page is not None:
        require(isinstance(page, int) and not isinstance(page, bool) and page >= 1, "source.locator.page must be null or positive")
    logical_chunk = nullable_text(locator["logical_chunk"], "source.locator.logical_chunk", maximum=300)
    require(page is not None or logical_chunk is not None, "source locator requires page or logical_chunk")
    if locator["kind"] == "physical_page":
        require(page is not None, "physical_page receipt locator requires a positive page")
    else:
        require(page is None and logical_chunk is not None, f"{locator['kind']} receipt locator requires page=null and logical_chunk")
    quality = exact(source["text_quality"], {"classification", "limitations"}, "source.text_quality")
    require(quality["classification"] in TEXT_QUALITIES, "source.text_quality.classification is unsupported")
    limitations = string_list(quality["limitations"], "source.text_quality.limitations")
    require(len(limitations) <= 1, "source.text_quality.limitations must preserve the adapter's single lossless quality note")
    if quality["classification"] in DEGRADED_TEXT_QUALITIES:
        require(bool(limitations), "degraded text quality requires limitations")
    program = exact(source["program"], {"name", "major_version", "version"}, "source.program")
    program_name = nullable_text(program["name"], "source.program.name", maximum=80)
    major_version = program["major_version"]
    require(major_version is None or major_version in MAJOR_VERSIONS, "source.program.major_version is unsupported")
    source_version = nullable_text(program["version"], "source.program.version", maximum=200)
    version_fields = (program_name, major_version, source_version)
    require(all(item is None for item in version_fields) or all(item is not None for item in version_fields), "source program/version fields must be all present or all null")
    if program_name is not None:
        require(program_name == "Gaussian", "populated source program must be exactly Gaussian")
    if source["source_kind"] == "gaussian_program_manual" or source["claim_scope"] == "gaussian_syntax_or_version":
        require(all(item is not None for item in version_fields), "Gaussian program-manual or version-specific receipt requires source program/version")
    if source["source_kind"] == "general_electronic_structure":
        require(source["claim_scope"] == "general_electronic_structure", "general source requires general claim_scope")
        require(all(item is None for item in version_fields), "general theory receipt must not fabricate Gaussian source version")
    if source["claim_scope"] == "general_electronic_structure":
        require(source["source_kind"] == "general_electronic_structure", "general claim_scope requires general source_kind")

    evidence = exact(data["evidence"], {"statement_type", "short_paraphrase", "whole_page_visual_review", "logical_chunk_review"}, "evidence")
    validate_statement(evidence["statement_type"], evidence["short_paraphrase"], "evidence.short_paraphrase")
    visual_review = validate_visual_review(evidence["whole_page_visual_review"], page=page)
    chunk_review = validate_chunk_review(evidence["logical_chunk_review"], logical_chunk=logical_chunk)
    target = exact(data["target_installation"], {"program", "major_version", "installed_revision"}, "target_installation")
    require(text(target["program"], "target_installation.program", maximum=80) == "Gaussian", "target program must be exactly Gaussian")
    require(target["major_version"] in MAJOR_VERSIONS, "target major_version is unsupported")
    text(target["installed_revision"], "target_installation.installed_revision", maximum=200)
    applicability = exact(data["applicability"], {"decision", "rationale", "installed_revision_review"}, "applicability")
    require(applicability["decision"] in APPLICABILITY_DECISIONS, "applicability decision is unsupported")
    text(applicability["rationale"], "applicability.rationale", maximum=1000)
    installed = validate_installed_review(applicability["installed_revision_review"])
    uncertainties = string_list(data["uncertainties"], "uncertainties")
    review = exact(data["review"], {"reviewer", "reviewed_at", "review_input_sha256"}, "review")
    text(review["reviewer"], "review.reviewer", maximum=200)
    timestamp(review["reviewed_at"], "review.reviewed_at")
    sha(review["review_input_sha256"], "review.review_input_sha256")
    require(data["downstream_role"] in DOWNSTREAM_ROLES, "downstream_role is unsupported")
    require(data["claim_ceiling"] == CLAIM_CEILING, "claim_ceiling is invalid")
    require(data["calculation_ready"] is False, "calculation_ready must be false")
    require(data["no_submission_authorization"] is True, "no_submission_authorization must be true")
    require(data["no_method_selection_authorization"] is True, "no_method_selection_authorization must be true")
    require(data["no_input_generation_authorization"] is True, "no_input_generation_authorization must be true")
    sha(data["payload_sha256"], "payload_sha256")

    version_claim = source["claim_scope"] == "gaussian_syntax_or_version"
    cross_version = version_claim and major_version != target["major_version"]
    g09_to_g16 = version_claim and major_version == "G09" and target["major_version"] == "G16"
    if version_claim:
        require(installed["status"] != "not_applicable_non_version_claim", "version-specific receipt cannot skip installed-revision review")
        if g09_to_g16 and installed["status"] != "reviewed":
            require(applicability["decision"] == "blocked_pending_installed_revision_review", "G09-to-G16 receipt is not fail closed")
        if applicability["decision"] in {"applicable", "applicable_with_limits"}:
            require(installed["status"] == "reviewed", "positive version-specific applicability requires installed-revision review")
        if cross_version and installed["status"] != "reviewed":
            require(applicability["decision"].startswith("blocked_"), "unreviewed cross-version receipt must remain blocked")
    else:
        require(applicability["decision"] != "blocked_pending_installed_revision_review", "non-version receipt must not fabricate a pending Gaussian version gate")
        require(installed["status"] != "not_reviewed", "non-version receipt must mark installed-revision review not applicable or reviewed")
    if applicability["decision"] == "blocked_pending_installed_revision_review":
        require(installed["status"] == "not_reviewed", "pending-installed-revision receipt requires not_reviewed")
    if applicability["decision"] in {"applicable", "applicable_with_limits"}:
        if page is not None:
            require(visual_review["status"] == "reviewed", "positive page-located receipt requires whole-page visual review")
        if logical_chunk is not None:
            require(chunk_review["status"] == "reviewed", "positive logical-chunk receipt requires logical-chunk review")
    if quality["classification"] in DEGRADED_TEXT_QUALITIES:
        require(bool(uncertainties), "degraded text quality requires uncertainty propagation")
        require(applicability["decision"] != "applicable", "degraded text quality cannot be unqualified applicable")
    if quality["classification"] == "legacy_word_text_pagination_unstable":
        require(locator["kind"] == "logical_chunk" and page is None and logical_chunk is not None, "legacy Word pagination-unstable receipt must use a logical_chunk locator")
    if applicability["decision"] == "applicable_with_limits":
        require(bool(uncertainties), "applicable_with_limits requires uncertainties")
    reconstructed_row = {
        "result_id": retrieval["result_id"],
        "canonical_store_digest": retrieval["canonical_store_digest"],
        "source_record_id": source["record_id"],
        "source_revision": source["revision"],
        "source_payload_sha256": source["payload_sha256"],
        "source_object_sha256": source["object_sha256"],
        "source_kind": source["source_kind"],
        "locator_kind": locator["kind"],
        "page": page,
        "logical_chunk": logical_chunk,
        "text_quality": quality["classification"],
        "text_quality_notes": limitations[0] if limitations else None,
        "source_program": program_name,
        "source_major_version": major_version,
        "source_version": source_version,
        "retrieved_text_sha256": retrieval["retrieved_text_sha256"],
    }
    require(retrieval["retrieval_row_sha256"] == canonical_sha(reconstructed_row), "retrieval row SHA-256 mismatch")
    _audit_no_machine_paths(data, "manual evidence receipt")
    require(data["payload_sha256"] == payload_sha(data), "manual evidence receipt payload SHA-256 mismatch")
    return data


def command_validate_config(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    config = validate_config(load_json(config_path))
    print(json.dumps({"valid": True, "schema": ADAPTER_SCHEMA, "adapter_id": config["adapter_id"], "config_sha256": file_sha(config_path), "offline": True}, sort_keys=True))


def command_query(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    config = validate_config(load_json(config_path))
    query = text(args.query, "query", maximum=MAX_QUERY_CHARS)
    require(query.strip() == query, "query must not have leading or trailing whitespace")
    require(1 <= args.limit <= 50, "limit must be from 1 through 50")
    rows = execute_readonly(
        Path(args.database),
        args.expected_db_sha256,
        config["query_sql"],
        {"query": query, "limit": args.limit},
        max_rows=args.limit,
    )
    candidates = []
    for row, source_text in rows:
        preview = " ".join(source_text.split())[: config["preview_char_limit"]]
        candidates.append(
            {
                "result_id": row["result_id"],
                "source_record_id": row["source_record_id"],
                "source_revision": row["source_revision"],
                "source_kind": row["source_kind"],
                "locator_kind": row["locator_kind"],
                "page": row["page"],
                "logical_chunk": row["logical_chunk"],
                "text_quality": row["text_quality"],
                "source_program": row["source_program"],
                "source_major_version": row["source_major_version"],
                "source_version": row["source_version"],
                "retrieved_text_sha256": row["retrieved_text_sha256"],
                "preview": preview,
            }
        )
    print(
        json.dumps(
            {
                "schema": "auto-g16-manual-retrieval-candidates/1",
                "adapter_id": config["adapter_id"],
                "adapter_config_sha256": file_sha(config_path),
                "retrieval_database_sha256": args.expected_db_sha256,
                "query": query,
                "candidates": candidates,
                "private_operational_output_do_not_commit": True,
                "calculation_ready": False,
                "no_submission_authorization": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def command_build(args: argparse.Namespace) -> None:
    receipt = build_receipt(
        Path(args.config),
        Path(args.database),
        args.expected_db_sha256,
        Path(args.review),
        Path(args.output),
    )
    print(json.dumps({"schema": RECEIPT_SCHEMA, "receipt_id": receipt["receipt_id"], "payload_sha256": receipt["payload_sha256"], "calculation_ready": False, "no_submission_authorization": True}, sort_keys=True))


def command_validate(args: argparse.Namespace) -> None:
    receipt = validate_receipt(load_json(Path(args.receipt)))
    print(json.dumps({"valid": True, "schema": RECEIPT_SCHEMA, "receipt_id": receipt["receipt_id"], "payload_sha256": receipt["payload_sha256"], "calculation_ready": False, "no_submission_authorization": True}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    config = commands.add_parser("validate-config", help="validate one path-free read-only adapter configuration")
    config.add_argument("config")
    config.set_defaults(func=command_validate_config)
    query = commands.add_parser("query", help="run a bounded private read-only lookup and print short candidates")
    query.add_argument("--config", required=True)
    query.add_argument("--database", required=True)
    query.add_argument("--expected-db-sha256", required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=10)
    query.set_defaults(func=command_query)
    build = commands.add_parser("build-receipt", help="reselect one exact row and build an immutable evidence-only receipt")
    build.add_argument("--config", required=True)
    build.add_argument("--database", required=True)
    build.add_argument("--expected-db-sha256", required=True)
    build.add_argument("--review", required=True)
    build.add_argument("--output", required=True)
    build.set_defaults(func=command_build)
    validate = commands.add_parser("validate", help="validate one finalized manual-evidence receipt")
    validate.add_argument("receipt")
    validate.set_defaults(func=command_validate)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.func(args)
    except (ManualEvidenceError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
