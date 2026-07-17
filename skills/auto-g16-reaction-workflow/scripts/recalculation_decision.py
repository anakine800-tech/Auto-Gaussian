#!/usr/bin/env python3
"""Finalize and validate immutable, non-authorizing recalculation decisions.

This standard-library-only CLI records a human decision about one failed
Gaussian attempt.  It never edits an input, proposes extra candidates, retries
a calculation, contacts SSH/PBS/Gaussian, submits work, cancels work, or cleans
up data.  Even an approved proposal only identifies one exact delta that must
pass new independent protocol, maturity, input, and live-approval gates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
SKILLS_ROOT = SKILL_ROOT.parent
ROOT = SKILLS_ROOT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import reaction_workflow as rw  # noqa: E402


ARTIFACT_SCHEMA = "gaussian-recalculation-decision/1"
DRAFT_SCHEMA = "gaussian-recalculation-decision-draft/1"
EVIDENCE_ROLES = ("attempt", "input", "protocol", "result", "terminal_evidence")
DECISIONS = {
    "no_retry",
    "defer",
    "approve_one_exact_recalculation_proposal",
    "reject_proposal",
}
FAILURE_CATEGORIES = {
    "input_or_configuration",
    "electronic_structure_convergence",
    "geometry_optimization",
    "frequency_or_hessian",
    "resource_or_scheduler",
    "runtime_or_environment",
    "scientific_validation",
    "incomplete_or_ambiguous",
    "other_reviewed",
}
PROPOSAL_STATUSES = {"selected_for_separate_gate", "deferred", "rejected"}
DELTA_TARGETS = {
    "structure",
    "method",
    "route",
    "resources",
    "input",
    "numerical_controls",
    "protocol",
    "other_reviewed",
}
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")

DECISION_POLICY = {
    "human_review_required": True,
    "normal_termination_alone_sufficient": False,
    "single_error_code_alone_sufficient": False,
    "automatic_inference_performed": False,
    "approval_requires_independent_future_gates": True,
}
IMMUTABILITY = {
    "upstream_failure_records_rewritten": False,
    "job_or_result_backwrite": False,
    "decision_link_only": True,
    "automatic_candidate_expansion": False,
    "automatic_input_change": False,
    "automatic_chemistry_method_resource_change": False,
    "automatic_cleanup": False,
    "automatic_cancellation": False,
}
REQUIRED_NEW_REVIEWS = {
    "protocol": True,
    "scientific_maturity": True,
    "input": True,
    "live_approval": True,
}
_OWNED_PAYLOAD_FIELDS = {
    ARTIFACT_SCHEMA: "payload_sha256",
    "gaussian-protocol-options/1": "proposal_payload_sha256",
    "gaussian-protocol-selection/1": "selection_payload_sha256",
    "gaussian-candidate-input-handoff/1": "payload_sha256",
    "gaussian-input-draft-review/1": "payload_sha256",
    "gaussian-calculation-attempt-link/1": "payload_sha256",
    "gaussian-sanitized-job-observation/1": "payload_sha256",
}
ROLE_SCHEMAS = {
    "attempt": {
        "gaussian-rtwin-pbs/1",
        "gaussian-job-inspection/1",
        "gaussian-sanitized-job-observation/1",
        "gaussian-calculation-attempt-link/1",
    },
    "input": {
        "gaussian-candidate-input-handoff/1",
        "gaussian-input-draft-review/1",
        "gaussian-opt-freq-sp/1",
        "gaussian-allcheck-input-manifest/1",
        "gaussian-asymmetric-metal-input-observation/1",
    },
    "protocol": {
        "gaussian-protocol-options/1",
        "gaussian-protocol-selection/1",
        "gaussian-protocol-profile-source/1",
    },
    "result": {
        "gaussian-result/1",
        "gaussian-opt-freq-sp-result/1",
        "gaussian-ts-freq-result/1",
        "gaussian-asymmetric-ts-result/1",
        "gaussian-asymmetric-metal-result-observation/1",
    },
    "terminal_evidence": {
        "gaussian-terminal-intake/1",
        "gaussian-job-inspection/1",
    },
}
RAW_MEDIA_TYPES = {
    "attempt": {"application/json", "text/plain", "application/octet-stream"},
    "input": {"application/json", "chemical/x-gaussian-input", "text/plain", "application/octet-stream"},
    "protocol": {"application/json", "text/plain", "application/octet-stream"},
    "result": {"application/json", "text/plain", "application/octet-stream"},
    "terminal_evidence": {"application/json", "text/plain", "application/octet-stream"},
}


class DecisionError(rw.OfflineError):
    """The recalculation-decision contract was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DecisionError(message)


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def _nonempty(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    return value


def _id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _nonempty_strings(value: Any, label: str) -> list[str]:
    require(isinstance(value, list) and value, f"{label} must be a non-empty array")
    return [_nonempty(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _reject_json_constant(value: str) -> None:
    raise DecisionError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def _parse_json_value(text: str, label: str) -> Any:
    _nonempty(text, label)
    try:
        return json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise DecisionError(f"{label} is not valid JSON: {exc}") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _value_sha256(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _canonical_assertion(source: str, pointer: str, value: Any) -> dict[str, Any]:
    canonical = _canonical_json(value)
    return {
        "source": source,
        "json_pointer": pointer,
        "canonical_json": canonical,
        "value_sha256": _value_sha256(canonical),
    }


def _no_symlink_components(path: Path, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        require(not current.is_symlink(), f"{label} path component must not be a symlink: {current}")


def _package_root(path: Path) -> Path:
    expanded = path.expanduser()
    require(expanded.exists() and expanded.is_dir(), f"package root must be an existing directory: {expanded}")
    _no_symlink_components(expanded, "package root")
    return expanded.resolve()


def _relative_name(path: Path, label: str) -> Path:
    lexical = path.expanduser()
    require(not lexical.is_absolute(), f"{label} must be package-root relative; absolute paths are forbidden")
    require(".." not in lexical.parts, f"{label} must not contain lexical parent traversal")
    require(bool(lexical.parts), f"{label} must not be empty")
    return lexical


def _package_file(root: Path, path: Path, label: str) -> Path:
    lexical = _relative_name(path, label)
    candidate = root / lexical
    require(candidate.exists(), f"{label} does not exist below package root: {lexical}")
    _no_symlink_components(candidate, label)
    require(candidate.is_file(), f"{label} must be a regular file: {lexical}")
    resolved = candidate.resolve()
    require(resolved.is_relative_to(root), f"{label} escaped package root")
    return resolved


def _safe_output(root: Path, path: Path) -> Path:
    lexical = _relative_name(path, "output path")
    candidate = root / lexical
    require(not candidate.exists() and not candidate.is_symlink(), f"refusing to overwrite existing output: {lexical}")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    _no_symlink_components(candidate.parent, "output parent")
    resolved_parent = candidate.parent.resolve()
    require(resolved_parent.is_relative_to(root), "output path escaped package root")
    return resolved_parent / candidate.name


def _write_new(path: Path, document: dict[str, Any]) -> None:
    """Publish complete bytes atomically without ever clobbering a target."""
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite existing output: {path.name}")
    temp_path = path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    temp_fd: int | None = None
    try:
        temp_fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        payload = rw.canonical_bytes(document)
        with os.fdopen(temp_fd, "wb", closefd=True) as handle:
            temp_fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # A same-directory hard link is an atomic no-clobber publication: if an
        # external writer creates the target after our checks, link fails with
        # FileExistsError and its bytes remain untouched.
        os.link(temp_path, path)
        temp_path.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise DecisionError(f"refusing concurrent or overwrite publication: {path.name}") from exc
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temp_path.exists() or temp_path.is_symlink():
            temp_path.unlink()


def _payload_sha256(document: dict[str, Any], field: str) -> str:
    payload = copy.deepcopy(document)
    payload.pop(field, None)
    return rw.sha256_data(payload)


def _declared_payload(document: dict[str, Any]) -> str | None:
    field = _OWNED_PAYLOAD_FIELDS.get(document.get("schema"))
    if field is None or field not in document:
        return None
    value = _sha(document.get(field), f"{document.get('schema')} owned payload SHA-256")
    require(value == _payload_sha256(document, field), f"{document.get('schema')} owned payload SHA-256 mismatch")
    return value


def _load_source(root: Path, path: Path, label: str) -> tuple[Path, dict[str, Any] | None]:
    resolved = _package_file(root, path, label)
    if resolved.suffix.lower() == ".json":
        return resolved, rw.load_json(resolved)
    return resolved, None


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix in {".gjf", ".com"}:
        return "chemical/x-gaussian-input"
    if suffix in {".log", ".out", ".txt"}:
        return "text/plain"
    return "application/octet-stream"


def _artifact_ref(root: Path, role: str, path: Path, document: dict[str, Any] | None) -> dict[str, Any]:
    schema = document.get("schema") if document is not None else None
    require(schema is None or isinstance(schema, str), "source artifact schema must be a string or null")
    media_type = _media_type(path)
    if schema is None:
        require(media_type in RAW_MEDIA_TYPES[role], f"{role} raw evidence media type is not allowed: {media_type}")
    else:
        require(schema in ROLE_SCHEMAS[role], f"{role} evidence schema is not allowlisted for this role: {schema}")
        require(media_type == "application/json", f"schema-bearing {role} evidence must use application/json")
    payload = _declared_payload(document) if document is not None else None
    return {
        "path": str(path.relative_to(root)),
        "sha256": rw.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "media_type": media_type,
        "schema": schema,
        "payload_sha256": payload,
        "integrity_validation": "bytes_and_declared_payload_replayed" if payload is not None else "bytes_only",
        "owner_validation": "not_performed_no_semantic_acceptance",
    }


def _resolve_binding(root: Path, role: str, reference: Any, label: str) -> tuple[Path, dict[str, Any] | None]:
    _exact_keys(reference, {"path", "sha256", "size_bytes", "media_type", "schema", "payload_sha256", "integrity_validation", "owner_validation"}, label)
    raw = _nonempty(reference["path"], f"{label}.path")
    require("://" not in raw, f"{label}.path must be local")
    lexical = _relative_name(Path(raw), f"{label}.path")
    resolved, document = _load_source(root, lexical, label)
    expected = _artifact_ref(root, role, resolved, document)
    require(reference == expected, f"{label} artifact reference drift")
    return resolved, document


def _pointer(document: dict[str, Any] | None, pointer: str, label: str) -> Any:
    require(document is not None, f"{label} requires a JSON evidence source")
    require(isinstance(pointer, str) and pointer.startswith("/"), f"{label} must be an RFC 6901 JSON Pointer")
    current: Any = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            require(token in current, f"{label} does not resolve: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            require(token.isdigit(), f"{label} array token is not an index: {token}")
            index = int(token)
            require(0 <= index < len(current), f"{label} array index is out of range: {index}")
            current = current[index]
        else:
            raise DecisionError(f"{label} traverses a scalar before the pointer ends: {pointer}")
    return current


def _source_selector(value: Any, label: str, keys: set[str]) -> tuple[str, str]:
    selector = _exact_keys(value, keys, label)
    source = selector.get("source")
    require(source in EVIDENCE_ROLES, f"{label}.source is invalid")
    pointer = selector.get("json_pointer")
    require(isinstance(pointer, str) and pointer.startswith("/"), f"{label}.json_pointer is invalid")
    return source, pointer


def _reviewed_at(value: Any) -> str:
    text = _nonempty(value, "review.reviewed_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionError("review.reviewed_at must be an ISO 8601 timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "review.reviewed_at must include a timezone")
    return text


def _reject_machine_paths(value: Any, label: str = "artifact", field: str | None = None) -> None:
    """Reject machine-local locators while allowing contract JSON Pointers."""
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_machine_paths(child, f"{label}.{key}", key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_machine_paths(child, f"{label}[{index}]", field)
    elif isinstance(value, str) and field != "json_pointer":
        machine_markers = (
            "/" + "Users" + "/",
            "/" + "home" + "/",
            "/" + "private" + "/",
            "file" + "://",
        )
        require(not value.startswith(("/", "\\\\")), f"{label} contains an absolute machine path")
        require(re.match(r"^[A-Za-z]:[\\\\/]", value) is None, f"{label} contains a Windows absolute machine path")
        require(not any(marker in value for marker in machine_markers), f"{label} contains a machine-local path")


def _validate_review(review: Any) -> dict[str, Any]:
    review = _exact_keys(review, {"decision", "reviewer", "reviewed_at", "notes", "uncertainties"}, "review")
    require(review["decision"] in DECISIONS, "review.decision is invalid")
    _nonempty(review["reviewer"], "review.reviewer")
    _reviewed_at(review["reviewed_at"])
    _nonempty_strings(review["notes"], "review.notes")
    _nonempty_strings(review["uncertainties"], "review.uncertainties")
    return review


def _validate_decision_semantics(review: dict[str, Any], actions: list[dict[str, Any]]) -> None:
    decision = review["decision"]
    statuses = [action["status"] for action in actions]
    if decision == "no_retry":
        require(not actions, "no_retry requires candidate_actions to be empty")
    elif decision == "defer":
        require(bool(actions) and set(statuses) == {"deferred"}, "defer requires one or more deferred proposals")
    elif decision == "approve_one_exact_recalculation_proposal":
        require(len(actions) == 1 and statuses == ["selected_for_separate_gate"], "approval requires exactly one proposal selected only for separate future gates")
    else:
        require(bool(actions) and set(statuses) == {"rejected"}, "reject_proposal requires one or more rejected proposals")


def _build_failure_classification(
    value: Any,
    sources: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    value = _exact_keys(value, {"category", "summary", "evidence", "human_classified"}, "failure_classification")
    require(value["category"] in FAILURE_CATEGORIES, "failure_classification.category is invalid")
    _nonempty(value["summary"], "failure_classification.summary")
    require(value["human_classified"] is True, "failure classification must be explicitly human-classified")
    evidence = value["evidence"]
    require(isinstance(evidence, list) and len(evidence) >= 2, "failure classification requires at least two exact evidence observations")
    built: list[dict[str, Any]] = []
    distinct_sources: set[str] = set()
    for index, item in enumerate(evidence):
        label = f"failure_classification.evidence[{index}]"
        source, pointer = _source_selector(item, label, {"source", "json_pointer", "interpretation"})
        interpretation = _nonempty(item["interpretation"], f"{label}.interpretation")
        observed = _pointer(sources[source], pointer, f"{label}.json_pointer")
        assertion = _canonical_assertion(source, pointer, observed)
        assertion["interpretation"] = interpretation
        built.append(assertion)
        distinct_sources.add(source)
    require(len(distinct_sources) >= 2, "failure classification evidence must span at least two bound sources")
    return {
        "category": value["category"],
        "summary": value["summary"],
        "evidence": built,
        "human_classified": True,
    }


def _build_original(
    value: Any,
    refs: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    value = _exact_keys(value, {"method", "route", "resources", "structure_hashes"}, "preserved_original_calculation")
    result: dict[str, Any] = {
        "input_sha256": refs["input"]["sha256"],
        "protocol_sha256": refs["protocol"]["sha256"],
    }
    for name in ("method", "route"):
        source, pointer = _source_selector(value[name], f"preserved_original_calculation.{name}", {"source", "json_pointer"})
        observed = _pointer(sources[source], pointer, f"preserved_original_calculation.{name}.json_pointer")
        require(isinstance(observed, str) and bool(observed.strip()), f"original {name} evidence must resolve to a non-empty string")
        result[name] = {"source": source, "json_pointer": pointer, "value": observed}
    source, pointer = _source_selector(value["resources"], "preserved_original_calculation.resources", {"source", "json_pointer"})
    observed_resources = _pointer(sources[source], pointer, "preserved_original_calculation.resources.json_pointer")
    result["resources"] = _canonical_assertion(source, pointer, observed_resources)
    structure_hashes = value["structure_hashes"]
    require(isinstance(structure_hashes, list) and structure_hashes, "at least one original structure hash is required")
    built_hashes: list[dict[str, Any]] = []
    roles: set[str] = set()
    for index, item in enumerate(structure_hashes):
        label = f"preserved_original_calculation.structure_hashes[{index}]"
        source, pointer = _source_selector(item, label, {"role", "source", "json_pointer"})
        role = _id(item["role"], f"{label}.role")
        require(role not in roles, f"duplicate structure-hash role: {role}")
        observed = _pointer(sources[source], pointer, f"{label}.json_pointer")
        built_hashes.append({"role": role, "source": source, "json_pointer": pointer, "sha256": _sha(observed, f"{label} observed SHA-256")})
        roles.add(role)
    result["structure_hashes"] = built_hashes
    return result


def _build_candidate_actions(
    values: Any,
    sources: dict[str, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    require(isinstance(values, list), "candidate_actions must be an array")
    built: list[dict[str, Any]] = []
    proposal_ids: set[str] = set()
    for index, value in enumerate(values):
        label = f"candidate_actions[{index}]"
        value = _exact_keys(
            value,
            {"proposal_id", "status", "proposed_exact_delta", "rationale", "impact_scope", "risks", "required_new_reviews"},
            label,
        )
        proposal_id = _id(value["proposal_id"], f"{label}.proposal_id")
        require(proposal_id not in proposal_ids, f"duplicate proposal_id: {proposal_id}")
        require(value["status"] in PROPOSAL_STATUSES, f"{label}.status is invalid")
        rationale = _exact_keys(value["rationale"], {"scientific", "numerical"}, f"{label}.rationale")
        _nonempty(rationale["scientific"], f"{label}.rationale.scientific")
        _nonempty(rationale["numerical"], f"{label}.rationale.numerical")
        _nonempty_strings(value["impact_scope"], f"{label}.impact_scope")
        _nonempty_strings(value["risks"], f"{label}.risks")
        require(value["required_new_reviews"] == REQUIRED_NEW_REVIEWS, f"{label}.required_new_reviews must require fresh protocol, maturity, input, and live approvals")
        deltas = value["proposed_exact_delta"]
        require(isinstance(deltas, list) and deltas, f"{label}.proposed_exact_delta must not be empty")
        built_deltas: list[dict[str, Any]] = []
        locators: set[str] = set()
        for delta_index, delta in enumerate(deltas):
            delta_label = f"{label}.proposed_exact_delta[{delta_index}]"
            delta = _exact_keys(
                delta,
                {"target", "target_locator", "source", "json_pointer", "to_canonical_json", "change_origin"},
                delta_label,
            )
            require(delta["target"] in DELTA_TARGETS, f"{delta_label}.target is invalid")
            locator = _nonempty(delta["target_locator"], f"{delta_label}.target_locator")
            require(locator not in locators, f"duplicate proposed delta target locator: {locator}")
            source, pointer = _source_selector(
                delta,
                delta_label,
                {"target", "target_locator", "source", "json_pointer", "to_canonical_json", "change_origin"},
            )
            require(delta["change_origin"] == "human_authored", f"{delta_label}.change_origin must be human_authored")
            observed = _pointer(sources[source], pointer, f"{delta_label}.json_pointer")
            from_canonical = _canonical_json(observed)
            to_value = _parse_json_value(delta["to_canonical_json"], f"{delta_label}.to_canonical_json")
            to_canonical = _canonical_json(to_value)
            require(delta["to_canonical_json"] == to_canonical, f"{delta_label}.to_canonical_json must already be canonical JSON")
            require(from_canonical != to_canonical, f"{delta_label} does not change the bound value")
            built_deltas.append(
                {
                    "target": delta["target"],
                    "target_locator": locator,
                    "source": source,
                    "json_pointer": pointer,
                    "from_canonical_json": from_canonical,
                    "from_sha256": _value_sha256(from_canonical),
                    "to_canonical_json": to_canonical,
                    "to_sha256": _value_sha256(to_canonical),
                    "change_origin": "human_authored",
                }
            )
            locators.add(locator)
        built.append(
            {
                "proposal_id": proposal_id,
                "status": value["status"],
                "proposed_exact_delta": built_deltas,
                "rationale": copy.deepcopy(rationale),
                "impact_scope": copy.deepcopy(value["impact_scope"]),
                "risks": copy.deepcopy(value["risks"]),
                "required_new_reviews": copy.deepcopy(REQUIRED_NEW_REVIEWS),
            }
        )
        proposal_ids.add(proposal_id)
    return built


def finalize_decision(
    package_root: Path,
    draft_path: Path,
    source_paths: dict[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    root = _package_root(package_root)
    draft_resolved = _package_file(root, draft_path, "decision draft")
    draft = rw.load_json(draft_resolved)
    _exact_keys(
        draft,
        {"schema", "decision_id", "failure_classification", "preserved_original_calculation", "candidate_actions", "review"},
        "decision draft",
    )
    require(draft["schema"] == DRAFT_SCHEMA, "decision draft schema is invalid")
    decision_id = _id(draft["decision_id"], "decision_id")
    require(set(source_paths) == set(EVIDENCE_ROLES), "exactly five evidence source paths are required")
    resolved_sources: dict[str, Path] = {}
    source_documents: dict[str, dict[str, Any] | None] = {}
    refs: dict[str, dict[str, Any]] = {}
    for role in EVIDENCE_ROLES:
        resolved, document = _load_source(root, source_paths[role], f"{role} evidence")
        resolved_sources[role] = resolved
        source_documents[role] = document
        refs[role] = _artifact_ref(root, role, resolved, document)
    review = copy.deepcopy(_validate_review(draft["review"]))
    failure = _build_failure_classification(draft["failure_classification"], source_documents)
    original = _build_original(draft["preserved_original_calculation"], refs, source_documents)
    actions = _build_candidate_actions(draft["candidate_actions"], source_documents)
    _validate_decision_semantics(review, actions)
    bindings = {
        role: {
            "artifact": refs[role],
            "retention_status": "preserved_immutable",
            "use": "evidence_only",
        }
        for role in EVIDENCE_ROLES
    }
    document = {
        "schema": ARTIFACT_SCHEMA,
        "decision_id": decision_id,
        "evidence_bindings": bindings,
        "failure_classification": failure,
        "preserved_original_calculation": original,
        "candidate_actions": actions,
        "review": review,
        "decision_policy": copy.deepcopy(DECISION_POLICY),
        "immutability": copy.deepcopy(IMMUTABILITY),
        "calculation_ready": False,
        "no_submission_authorization": True,
        "no_automatic_retry": True,
    }
    _reject_machine_paths(document)
    rw.finalize_artifact(document)
    output = _safe_output(root, output_path)
    _validate_document(document, root, source_override=(resolved_sources, source_documents))
    _write_new(output, document)
    return document


def _validate_canonical_assertion(
    assertion: Any,
    source_documents: dict[str, dict[str, Any] | None],
    label: str,
) -> None:
    source, pointer = _source_selector(assertion, label, {"source", "json_pointer", "canonical_json", "value_sha256"})
    observed = _pointer(source_documents[source], pointer, f"{label}.json_pointer")
    expected = _canonical_json(observed)
    require(assertion["canonical_json"] == expected, f"{label}.canonical_json differs from bound evidence")
    require(_sha(assertion["value_sha256"], f"{label}.value_sha256") == _value_sha256(expected), f"{label}.value_sha256 mismatch")


def _validate_output_failure(value: Any, sources: dict[str, dict[str, Any] | None]) -> None:
    value = _exact_keys(value, {"category", "summary", "evidence", "human_classified"}, "failure_classification")
    require(value["category"] in FAILURE_CATEGORIES, "failure_classification.category is invalid")
    _nonempty(value["summary"], "failure_classification.summary")
    require(value["human_classified"] is True, "failure classification must be human-classified")
    evidence = value["evidence"]
    require(isinstance(evidence, list) and len(evidence) >= 2, "failure classification needs at least two evidence observations")
    distinct_sources: set[str] = set()
    for index, item in enumerate(evidence):
        label = f"failure_classification.evidence[{index}]"
        _exact_keys(item, {"source", "json_pointer", "canonical_json", "value_sha256", "interpretation"}, label)
        _nonempty(item["interpretation"], f"{label}.interpretation")
        _validate_canonical_assertion(
            {key: item[key] for key in ("source", "json_pointer", "canonical_json", "value_sha256")},
            sources,
            label,
        )
        distinct_sources.add(item["source"])
    require(len(distinct_sources) >= 2, "failure classification evidence must span at least two bound sources")


def _validate_output_original(
    value: Any,
    refs: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any] | None],
) -> None:
    value = _exact_keys(value, {"input_sha256", "protocol_sha256", "method", "route", "resources", "structure_hashes"}, "preserved_original_calculation")
    require(value["input_sha256"] == refs["input"]["sha256"], "preserved original input SHA-256 drift")
    require(value["protocol_sha256"] == refs["protocol"]["sha256"], "preserved original protocol SHA-256 drift")
    for name in ("method", "route"):
        assertion = value[name]
        source, pointer = _source_selector(assertion, f"preserved_original_calculation.{name}", {"source", "json_pointer", "value"})
        observed = _pointer(sources[source], pointer, f"preserved_original_calculation.{name}.json_pointer")
        require(isinstance(observed, str) and assertion["value"] == observed and bool(observed.strip()), f"preserved original {name} differs from bound evidence")
    _validate_canonical_assertion(value["resources"], sources, "preserved_original_calculation.resources")
    hashes = value["structure_hashes"]
    require(isinstance(hashes, list) and hashes, "preserved original structure hashes must not be empty")
    roles: set[str] = set()
    for index, item in enumerate(hashes):
        label = f"preserved_original_calculation.structure_hashes[{index}]"
        source, pointer = _source_selector(item, label, {"role", "source", "json_pointer", "sha256"})
        role = _id(item["role"], f"{label}.role")
        require(role not in roles, f"duplicate structure-hash role: {role}")
        observed = _pointer(sources[source], pointer, f"{label}.json_pointer")
        require(_sha(item["sha256"], f"{label}.sha256") == observed, f"{label}.sha256 differs from bound evidence")
        roles.add(role)


def _validate_output_actions(values: Any, sources: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    require(isinstance(values, list), "candidate_actions must be an array")
    proposal_ids: set[str] = set()
    for index, action in enumerate(values):
        label = f"candidate_actions[{index}]"
        action = _exact_keys(action, {"proposal_id", "status", "proposed_exact_delta", "rationale", "impact_scope", "risks", "required_new_reviews"}, label)
        proposal_id = _id(action["proposal_id"], f"{label}.proposal_id")
        require(proposal_id not in proposal_ids, f"duplicate proposal_id: {proposal_id}")
        require(action["status"] in PROPOSAL_STATUSES, f"{label}.status is invalid")
        rationale = _exact_keys(action["rationale"], {"scientific", "numerical"}, f"{label}.rationale")
        _nonempty(rationale["scientific"], f"{label}.rationale.scientific")
        _nonempty(rationale["numerical"], f"{label}.rationale.numerical")
        _nonempty_strings(action["impact_scope"], f"{label}.impact_scope")
        _nonempty_strings(action["risks"], f"{label}.risks")
        require(action["required_new_reviews"] == REQUIRED_NEW_REVIEWS, f"{label} does not require every fresh downstream review")
        deltas = action["proposed_exact_delta"]
        require(isinstance(deltas, list) and deltas, f"{label}.proposed_exact_delta must not be empty")
        locators: set[str] = set()
        for delta_index, delta in enumerate(deltas):
            delta_label = f"{label}.proposed_exact_delta[{delta_index}]"
            delta = _exact_keys(
                delta,
                {"target", "target_locator", "source", "json_pointer", "from_canonical_json", "from_sha256", "to_canonical_json", "to_sha256", "change_origin"},
                delta_label,
            )
            require(delta["target"] in DELTA_TARGETS, f"{delta_label}.target is invalid")
            locator = _nonempty(delta["target_locator"], f"{delta_label}.target_locator")
            require(locator not in locators, f"duplicate proposed delta target locator: {locator}")
            source, pointer = _source_selector(
                delta,
                delta_label,
                {"target", "target_locator", "source", "json_pointer", "from_canonical_json", "from_sha256", "to_canonical_json", "to_sha256", "change_origin"},
            )
            require(delta["change_origin"] == "human_authored", f"{delta_label}.change_origin must be human_authored")
            observed = _pointer(sources[source], pointer, f"{delta_label}.json_pointer")
            from_expected = _canonical_json(observed)
            require(delta["from_canonical_json"] == from_expected, f"{delta_label}.from_canonical_json differs from bound evidence")
            require(_sha(delta["from_sha256"], f"{delta_label}.from_sha256") == _value_sha256(from_expected), f"{delta_label}.from_sha256 mismatch")
            to_value = _parse_json_value(delta["to_canonical_json"], f"{delta_label}.to_canonical_json")
            to_expected = _canonical_json(to_value)
            require(delta["to_canonical_json"] == to_expected, f"{delta_label}.to_canonical_json is not canonical")
            require(_sha(delta["to_sha256"], f"{delta_label}.to_sha256") == _value_sha256(to_expected), f"{delta_label}.to_sha256 mismatch")
            require(from_expected != to_expected, f"{delta_label} does not change the bound value")
            locators.add(locator)
        proposal_ids.add(proposal_id)
    return values


def _validate_document(
    document: dict[str, Any],
    package_root: Path,
    *,
    source_override: tuple[dict[str, Path], dict[str, dict[str, Any] | None]] | None = None,
) -> dict[str, Any]:
    _exact_keys(
        document,
        {
            "schema", "decision_id", "evidence_bindings", "failure_classification",
            "preserved_original_calculation", "candidate_actions", "review", "decision_policy",
            "immutability", "calculation_ready", "no_submission_authorization",
            "no_automatic_retry", "payload_sha256",
        },
        "recalculation decision",
    )
    require(document["schema"] == ARTIFACT_SCHEMA, "recalculation decision schema is invalid")
    _id(document["decision_id"], "decision_id")
    require(document["decision_policy"] == DECISION_POLICY, "decision inference policy changed")
    require(document["immutability"] == IMMUTABILITY, "immutability or automatic-action boundary changed")
    require(document["calculation_ready"] is False, "calculation_ready must remain false")
    require(document["no_submission_authorization"] is True, "submission must remain unauthorized")
    require(document["no_automatic_retry"] is True, "automatic retry must remain disabled")
    _reject_machine_paths(document)
    try:
        rw.validate_payload_hash(document)
    except rw.OfflineError as exc:
        raise DecisionError(f"decision payload validation failed: {exc}") from exc
    bindings = _exact_keys(document["evidence_bindings"], set(EVIDENCE_ROLES), "evidence_bindings")
    refs: dict[str, dict[str, Any]] = {}
    resolved_paths: dict[str, Path] = {}
    source_documents: dict[str, dict[str, Any] | None] = {}
    for role in EVIDENCE_ROLES:
        binding = _exact_keys(bindings[role], {"artifact", "retention_status", "use"}, f"evidence_bindings.{role}")
        require(binding["retention_status"] == "preserved_immutable", f"{role} evidence must remain immutable")
        require(binding["use"] == "evidence_only", f"{role} binding must remain evidence-only")
        refs[role] = binding["artifact"]
        if source_override is None:
            path, source_document = _resolve_binding(package_root, role, refs[role], f"evidence_bindings.{role}.artifact")
        else:
            path = source_override[0][role]
            source_document = source_override[1][role]
            expected = _artifact_ref(package_root, role, path, source_document)
            require(refs[role] == expected, f"evidence_bindings.{role}.artifact drift")
        resolved_paths[role] = path
        source_documents[role] = source_document
    _validate_output_failure(document["failure_classification"], source_documents)
    _validate_output_original(document["preserved_original_calculation"], refs, source_documents)
    actions = _validate_output_actions(document["candidate_actions"], source_documents)
    review = _validate_review(document["review"])
    _validate_decision_semantics(review, actions)
    return document


def validate_decision(package_root: Path, path: Path) -> dict[str, Any]:
    root = _package_root(package_root)
    resolved = _package_file(root, path, "recalculation decision")
    document = rw.load_json(resolved)
    _validate_document(document, root)
    return {
        "valid": True,
        "schema": ARTIFACT_SCHEMA,
        "decision_id": document["decision_id"],
        "decision": document["review"]["decision"],
        "payload_sha256": document["payload_sha256"],
        "calculation_ready": False,
        "no_submission_authorization": True,
        "no_automatic_retry": True,
        "live_actions": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    finalize = sub.add_parser("finalize", help="finalize one immutable human-reviewed decision")
    finalize.add_argument("--root", required=True, help="decision package root; all other paths are relative to it")
    finalize.add_argument("draft")
    finalize.add_argument("--attempt", required=True)
    finalize.add_argument("--input", required=True)
    finalize.add_argument("--protocol", required=True)
    finalize.add_argument("--result", required=True)
    finalize.add_argument("--terminal-evidence", required=True)
    finalize.add_argument("--output", required=True)
    validate = sub.add_parser("validate", help="replay all bindings and validate one finalized decision")
    validate.add_argument("--root", required=True, help="decision package root; artifact bindings resolve only below it")
    validate.add_argument("artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "finalize":
            source_paths = {
                "attempt": Path(args.attempt),
                "input": Path(args.input),
                "protocol": Path(args.protocol),
                "result": Path(args.result),
                "terminal_evidence": Path(args.terminal_evidence),
            }
            document = finalize_decision(Path(args.root), Path(args.draft), source_paths, Path(args.output))
            summary = {
                "schema": ARTIFACT_SCHEMA,
                "decision_id": document["decision_id"],
                "decision": document["review"]["decision"],
                "payload_sha256": document["payload_sha256"],
                "calculation_ready": False,
                "no_submission_authorization": True,
                "no_automatic_retry": True,
                "live_actions": False,
            }
        else:
            summary = validate_decision(Path(args.root), Path(args.artifact))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (DecisionError, rw.OfflineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
