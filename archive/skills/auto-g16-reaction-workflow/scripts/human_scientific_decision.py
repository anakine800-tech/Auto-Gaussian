#!/usr/bin/env python3
"""Build and validate offline human scientific-decision artifacts.

The CLI records explicit user decisions, operator recommendations, and
evidence-bound learning proposals.  It never infers user confirmation, changes
an approved decision, creates an executable handoff, or performs a live action.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import reaction_workflow as rw


DISCUSSION = "gaussian-mechanism-discussion/1"
DISCUSSION_DRAFT = "gaussian-mechanism-discussion-draft/1"
ACTION_CARD = "gaussian-operator-action-card/1"
ACTION_DRAFT = "gaussian-operator-action-card-draft/1"
LEARNING = "gaussian-study-learning-update/1"
LEARNING_DRAFT = "gaussian-study-learning-update-draft/1"
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
CONFIRMABLE = {"mechanism", "active_species", "elementary_step", "method", "calculation_route"}
DECISIONS = {"confirm_selected", "defer", "reject", "request_revision"}
UNAUTHORIZED = [
    "automatic_retry", "chemistry_change", "method_change", "calculation_route_change",
    "candidate_expansion", "job_cancellation", "data_cleanup", "live_submission",
]


class DecisionError(rw.OfflineError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DecisionError(message)


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def text(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    return value


def ident(value: Any, label: str) -> str:
    try:
        return rw._require_id(value, label)
    except rw.OfflineError as exc:
        raise DecisionError(str(exc)) from exc


def strings(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    require(not nonempty or bool(value), f"{label} must not be empty")
    return [text(item, f"{label}[{index}]") for index, item in enumerate(value)]


def timestamp(value: Any, label: str) -> str:
    raw = text(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionError(f"{label} must be an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{label} must include a timezone")
    return raw


def sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be a SHA-256")
    return value


def package_root(path: Path) -> Path:
    require(path.exists() and path.is_dir() and not path.is_symlink(), "package root must be an existing non-symlink directory")
    return path.resolve()


def package_file(root: Path, relative: Path, label: str) -> Path:
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label} must be package-root relative")
    candidate = root / relative
    require(candidate.exists() and candidate.is_file() and not candidate.is_symlink(), f"{label} must be an existing non-symlink file")
    resolved = candidate.resolve()
    require(resolved.is_relative_to(root), f"{label} escapes package root")
    return resolved


def output_file(root: Path, relative: Path) -> Path:
    require(not relative.is_absolute() and ".." not in relative.parts, "output must be package-root relative")
    candidate = root / relative
    require(candidate.parent.exists() and candidate.parent.is_dir() and not candidate.parent.is_symlink(), "output parent must pre-exist and not be a symlink")
    require(not candidate.exists() and not candidate.is_symlink(), "refusing to overwrite existing output")
    return candidate


def binding(root: Path, relative: Path, role: str) -> dict[str, Any]:
    path = package_file(root, relative, role)
    data = rw.load_json(path)
    declared = data.get("payload_sha256")
    if declared is not None:
        rw.validate_payload_hash(data)
    return {
        "role": role,
        "path": relative.as_posix(),
        "sha256": rw.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "schema": data.get("schema"),
        "payload_sha256": declared,
    }


def validate_binding(root: Path, value: Any, label: str) -> dict[str, Any]:
    item = exact(value, {"role", "path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    path = package_file(root, Path(text(item["path"], f"{label}.path")), label)
    require(item["sha256"] == rw.sha256_file(path) and item["size_bytes"] == path.stat().st_size, f"{label} evidence hash is stale")
    data = rw.load_json(path)
    require(item["schema"] == data.get("schema"), f"{label} schema drift")
    require(item["payload_sha256"] == data.get("payload_sha256"), f"{label} payload hash drift")
    if data.get("payload_sha256") is not None:
        rw.validate_payload_hash(data)
    return data


def validate_source_hashes(value: Any, sources: dict[str, Any]) -> None:
    hashes = exact(value, {"mechanism", "network", "evidence"}, "source_hashes")
    require(sha(hashes["mechanism"], "source_hashes.mechanism") == sources["mechanism"]["sha256"], "mechanism review hash is stale")
    require(sha(hashes["network"], "source_hashes.network") == sources["network"]["sha256"], "network review hash is stale")
    evidence_hashes = [sha(item, "source_hashes.evidence") for item in hashes["evidence"]]
    require(evidence_hashes == [item["sha256"] for item in sources["evidence"]], "evidence review hash is stale")


def normalize_alternatives(value: Any) -> list[dict[str, Any]]:
    require(isinstance(value, list) and len(value) >= 2, "alternatives must contain at least two proposals")
    result = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = exact(raw, {"alternative_id", "summary", "origin", "proposal_only"}, f"alternatives[{index}]")
        alternative_id = ident(item["alternative_id"], "alternative_id")
        require(alternative_id not in seen, "alternative IDs must be unique")
        seen.add(alternative_id)
        require(item["origin"] in {"ai_generated", "human_submitted", "evidence_derived"}, "alternative origin is invalid")
        require(item["proposal_only"] is True, "every alternative must remain proposal_only")
        result.append({**item, "summary": text(item["summary"], "alternative summary")})
    return result


def normalize_user_decision(value: Any, alternatives: set[str]) -> dict[str, Any]:
    item = exact(value, {"decision", "exact_text", "confirmed_claims", "origin", "assistant_generated", "automated_command_generated", "approver", "decided_at"}, "user_decision")
    require(item["decision"] in DECISIONS, "user_decision.decision is invalid")
    require(item["origin"] == "explicit_user_input", "AI-generated content cannot be user confirmation")
    require(item["assistant_generated"] is False, "assistant-generated content cannot be user confirmation")
    require(item["automated_command_generated"] is False, "an automated command cannot generate user confirmation")
    claims = []
    seen: set[tuple[str, str]] = set()
    require(isinstance(item["confirmed_claims"], list), "confirmed_claims must be an array")
    for index, raw in enumerate(item["confirmed_claims"]):
        claim = exact(raw, {"claim_type", "claim_id", "alternative_id", "decision"}, f"confirmed_claims[{index}]")
        require(claim["claim_type"] in CONFIRMABLE, "confirmed claim type is invalid")
        claim_id = ident(claim["claim_id"], "claim_id")
        require(claim["alternative_id"] in alternatives, "confirmed claim references an unknown alternative")
        require(claim["decision"] == "confirmed_by_user", "only explicit user decisions can confirm a claim")
        key = (claim["claim_type"], claim_id)
        require(key not in seen, "confirmed claims must be unique")
        seen.add(key)
        claims.append(dict(claim))
    if item["decision"] == "confirm_selected":
        require(bool(claims), "confirm_selected requires at least one exact confirmed claim")
    else:
        require(not claims, "non-confirming decisions cannot contain confirmed claims")
    return {**item, "exact_text": text(item["exact_text"], "user_decision.exact_text"), "confirmed_claims": claims, "approver": text(item["approver"], "approver"), "decided_at": timestamp(item["decided_at"], "decided_at")}


def build_discussion(root: Path, draft_path: Path, mechanism: Path, network: Path, evidence: list[Path], output: Path) -> dict[str, Any]:
    require(bool(evidence), "at least one evidence artifact is required")
    draft = rw.load_json(package_file(root, draft_path, "discussion draft"))
    exact(draft, {"schema", "discussion_id", "study_id", "source_hashes", "scientific_question", "established_facts", "uncertainties", "alternatives", "ai_assessment", "user_decision"}, "discussion draft")
    require(draft["schema"] == DISCUSSION_DRAFT, "discussion draft schema is invalid")
    sources = {"mechanism": binding(root, mechanism, "mechanism"), "network": binding(root, network, "network"), "evidence": [binding(root, path, "evidence") for path in evidence]}
    validate_source_hashes(draft["source_hashes"], sources)
    alternatives = normalize_alternatives(draft["alternatives"])
    ai = exact(draft["ai_assessment"], {"recommendation", "rationale", "risks", "origin", "proposal_only", "may_confirm"}, "ai_assessment")
    require(ai["origin"] == "ai_generated" and ai["proposal_only"] is True and ai["may_confirm"] is False, "AI assessment must remain a non-confirming proposal")
    ai = {**ai, "recommendation": text(ai["recommendation"], "AI recommendation"), "rationale": text(ai["rationale"], "AI rationale"), "risks": strings(ai["risks"], "AI risks")}
    decision = normalize_user_decision(draft["user_decision"], {item["alternative_id"] for item in alternatives})
    fingerprint = rw.sha256_data({"sources": sources, "user_decision": decision})
    artifact = {
        "schema": DISCUSSION, "discussion_id": ident(draft["discussion_id"], "discussion_id"), "study_id": ident(draft["study_id"], "study_id"),
        "sources": sources, "scientific_question": text(draft["scientific_question"], "scientific_question"),
        "established_facts": strings(draft["established_facts"], "established_facts"), "uncertainties": strings(draft["uncertainties"], "uncertainties"),
        "alternatives": alternatives, "ai_assessment": ai, "user_decision": decision, "confirmation_scope_sha256": fingerprint,
        "revision_policy": {"changed_source_requires_renewed_confirmation": True, "prior_confirmation_reusable": False, "learning_update_may_rewrite_decision": False},
        "calculation_ready": False, "no_submission_authorization": True, "no_automatic_promotion": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output_file(root, output), artifact)
    return artifact


def validate_discussion(root: Path, artifact: dict[str, Any]) -> None:
    exact(artifact, {"schema", "discussion_id", "study_id", "sources", "scientific_question", "established_facts", "uncertainties", "alternatives", "ai_assessment", "user_decision", "confirmation_scope_sha256", "revision_policy", "calculation_ready", "no_submission_authorization", "no_automatic_promotion", "payload_sha256"}, "mechanism discussion")
    require(artifact["schema"] == DISCUSSION, "discussion schema is invalid")
    ident(artifact["discussion_id"], "discussion_id"); ident(artifact["study_id"], "study_id")
    text(artifact["scientific_question"], "scientific_question")
    strings(artifact["established_facts"], "established_facts"); strings(artifact["uncertainties"], "uncertainties")
    sources = exact(artifact["sources"], {"mechanism", "network", "evidence"}, "sources")
    require(sources["mechanism"].get("role") == "mechanism", "mechanism source role changed")
    require(sources["network"].get("role") == "network", "network source role changed")
    validate_binding(root, sources["mechanism"], "mechanism source")
    validate_binding(root, sources["network"], "network source")
    require(isinstance(sources["evidence"], list) and sources["evidence"], "evidence sources must not be empty")
    for index, item in enumerate(sources["evidence"]):
        require(item.get("role") == "evidence", "evidence source role changed")
        validate_binding(root, item, f"evidence source {index}")
    alternatives = normalize_alternatives(artifact["alternatives"])
    ai = exact(artifact["ai_assessment"], {"recommendation", "rationale", "risks", "origin", "proposal_only", "may_confirm"}, "ai_assessment")
    text(ai["recommendation"], "AI recommendation"); text(ai["rationale"], "AI rationale"); strings(ai["risks"], "AI risks")
    require(ai["origin"] == "ai_generated" and ai["proposal_only"] is True and ai["may_confirm"] is False, "AI assessment acquired confirmation authority")
    decision = normalize_user_decision(artifact["user_decision"], {item["alternative_id"] for item in alternatives})
    require(artifact["confirmation_scope_sha256"] == rw.sha256_data({"sources": sources, "user_decision": decision}), "confirmation scope hash mismatch")
    require(artifact["revision_policy"] == {"changed_source_requires_renewed_confirmation": True, "prior_confirmation_reusable": False, "learning_update_may_rewrite_decision": False}, "revision policy changed")
    require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True and artifact["no_automatic_promotion"] is True, "discussion authority boundary changed")
    rw.validate_payload_hash(artifact)


def discussion_binding(root: Path, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = binding(root, path, "discussion")
    document = rw.load_json(package_file(root, path, "discussion"))
    validate_discussion(root, document)
    require(document["schema"] == DISCUSSION, "source is not a mechanism discussion")
    return ref, document


def confidence(value: Any, label: str) -> dict[str, Any]:
    item = exact(value, {"band", "rationale"}, label)
    require(item["band"] in {"very_low", "low", "moderate", "high", "unknown"}, f"{label}.band is invalid")
    return {"band": item["band"], "rationale": text(item["rationale"], f"{label}.rationale")}


def build_action(root: Path, draft_path: Path, discussion_path: Path, output: Path) -> dict[str, Any]:
    draft = rw.load_json(package_file(root, draft_path, "action-card draft"))
    exact(draft, {"schema", "card_id", "study_id", "discussion_payload_sha256", "disposition", "purpose", "exact_scope", "prerequisites", "scientific_value", "estimated_cost", "success_confidence", "closure_confidence", "stop_conditions", "continuation", "rollback", "unauthorized_actions"}, "action-card draft")
    require(draft["schema"] == ACTION_DRAFT and draft["disposition"] in {"run", "defer", "reject"}, "action-card draft schema or disposition is invalid")
    discussion_ref, discussion = discussion_binding(root, discussion_path)
    require(draft["study_id"] == discussion["study_id"], "action-card study differs from discussion")
    require(draft["discussion_payload_sha256"] == discussion["payload_sha256"], "action-card discussion hash is stale")
    if draft["disposition"] == "run":
        require(discussion["user_decision"]["decision"] == "confirm_selected", "run requires an explicit current user confirmation")
    scope = exact(draft["exact_scope"], {"target_kind", "target_ids", "included_actions"}, "exact_scope")
    scope = {"target_kind": text(scope["target_kind"], "target_kind"), "target_ids": strings(scope["target_ids"], "target_ids"), "included_actions": strings(scope["included_actions"], "included_actions")}
    require(isinstance(draft["prerequisites"], list) and draft["prerequisites"], "prerequisites must not be empty")
    prerequisites = []
    for index, raw in enumerate(draft["prerequisites"]):
        item = exact(raw, {"name", "status", "evidence"}, f"prerequisites[{index}]")
        require(item["status"] in {"satisfied", "blocked", "unknown"}, "prerequisite status is invalid")
        prerequisites.append({"name": text(item["name"], "prerequisite name"), "status": item["status"], "evidence": text(item["evidence"], "prerequisite evidence")})
    if draft["disposition"] == "run":
        require(all(item["status"] == "satisfied" for item in prerequisites), "run disposition requires every hard prerequisite to be satisfied")
    cost = exact(draft["estimated_cost"], {"status", "task_count", "core_hours_band", "walltime_band", "assumptions"}, "estimated_cost")
    require(cost["status"] in {"estimated", "unknown"}, "estimated_cost.status is invalid")
    if cost["status"] == "unknown":
        require(cost["task_count"] is None and cost["core_hours_band"] is None and cost["walltime_band"] is None, "unknown cost cannot contain invented estimates")
    else:
        require(isinstance(cost["task_count"], int) and cost["task_count"] >= 1, "estimated task_count is invalid")
        text(cost["core_hours_band"], "core_hours_band"); text(cost["walltime_band"], "walltime_band")
    cost["assumptions"] = strings(cost["assumptions"], "cost assumptions")
    continuation = exact(draft["continuation"], {"on_success", "on_failure"}, "continuation")
    continuation = {"on_success": strings(continuation["on_success"], "on_success"), "on_failure": strings(continuation["on_failure"], "on_failure")}
    require(draft["unauthorized_actions"] == UNAUTHORIZED, "unauthorized_actions must use the closed safety list")
    artifact = {
        "schema": ACTION_CARD, "card_id": ident(draft["card_id"], "card_id"), "study_id": ident(draft["study_id"], "study_id"), "discussion": discussion_ref,
        "disposition": draft["disposition"], "purpose": text(draft["purpose"], "purpose"), "exact_scope": scope, "prerequisites": prerequisites,
        "scientific_value": text(draft["scientific_value"], "scientific_value"), "estimated_cost": cost,
        "success_confidence": confidence(draft["success_confidence"], "success_confidence"), "closure_confidence": confidence(draft["closure_confidence"], "closure_confidence"),
        "stop_conditions": strings(draft["stop_conditions"], "stop_conditions"), "continuation": continuation, "rollback": strings(draft["rollback"], "rollback"),
        "unauthorized_actions": list(UNAUTHORIZED), "recommendation_only": True, "calculation_ready": False, "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact); rw.write_json(output_file(root, output), artifact)
    return artifact


def validate_action(root: Path, artifact: dict[str, Any]) -> None:
    exact(artifact, {"schema", "card_id", "study_id", "discussion", "disposition", "purpose", "exact_scope", "prerequisites", "scientific_value", "estimated_cost", "success_confidence", "closure_confidence", "stop_conditions", "continuation", "rollback", "unauthorized_actions", "recommendation_only", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "operator action card")
    require(artifact["schema"] == ACTION_CARD, "action-card schema is invalid")
    ident(artifact["card_id"], "card_id"); ident(artifact["study_id"], "study_id")
    require(artifact["discussion"].get("role") == "discussion" and artifact["discussion"].get("schema") == DISCUSSION, "action-card discussion binding is invalid")
    discussion = validate_binding(root, artifact["discussion"], "discussion")
    validate_discussion(root, discussion)
    require(artifact["study_id"] == discussion["study_id"], "action-card study drift")
    require(artifact["disposition"] in {"run", "defer", "reject"}, "action-card disposition is invalid")
    if artifact["disposition"] == "run": require(discussion["user_decision"]["decision"] == "confirm_selected", "run lost explicit user confirmation")
    text(artifact["purpose"], "purpose"); text(artifact["scientific_value"], "scientific_value")
    scope = exact(artifact["exact_scope"], {"target_kind", "target_ids", "included_actions"}, "exact_scope")
    text(scope["target_kind"], "target_kind"); strings(scope["target_ids"], "target_ids"); strings(scope["included_actions"], "included_actions")
    require(isinstance(artifact["prerequisites"], list) and artifact["prerequisites"], "prerequisites must not be empty")
    for index, raw in enumerate(artifact["prerequisites"]):
        item = exact(raw, {"name", "status", "evidence"}, f"prerequisites[{index}]")
        text(item["name"], "prerequisite name"); text(item["evidence"], "prerequisite evidence")
        require(item["status"] in {"satisfied", "blocked", "unknown"}, "prerequisite status is invalid")
    if artifact["disposition"] == "run":
        require(all(item["status"] == "satisfied" for item in artifact["prerequisites"]), "run disposition requires every hard prerequisite to remain satisfied")
    cost = exact(artifact["estimated_cost"], {"status", "task_count", "core_hours_band", "walltime_band", "assumptions"}, "estimated_cost")
    require(cost["status"] in {"estimated", "unknown"}, "estimated_cost.status is invalid")
    if cost["status"] == "unknown":
        require(cost["task_count"] is None and cost["core_hours_band"] is None and cost["walltime_band"] is None, "unknown cost cannot contain invented estimates")
    else:
        require(isinstance(cost["task_count"], int) and cost["task_count"] >= 1, "estimated task_count is invalid")
        text(cost["core_hours_band"], "core_hours_band"); text(cost["walltime_band"], "walltime_band")
    strings(cost["assumptions"], "cost assumptions")
    confidence(artifact["success_confidence"], "success_confidence"); confidence(artifact["closure_confidence"], "closure_confidence")
    strings(artifact["stop_conditions"], "stop_conditions"); strings(artifact["rollback"], "rollback")
    continuation = exact(artifact["continuation"], {"on_success", "on_failure"}, "continuation")
    strings(continuation["on_success"], "on_success"); strings(continuation["on_failure"], "on_failure")
    require(artifact["unauthorized_actions"] == UNAUTHORIZED and artifact["recommendation_only"] is True and artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "action-card authority boundary changed")
    rw.validate_payload_hash(artifact)


def build_learning(root: Path, draft_path: Path, discussion_path: Path, evidence_paths: list[Path], output: Path) -> dict[str, Any]:
    require(bool(evidence_paths), "learning update requires evidence")
    draft = rw.load_json(package_file(root, draft_path, "learning-update draft"))
    exact(draft, {"schema", "update_id", "study_id", "discussion_payload_sha256", "evidence_hashes", "observations", "interpretations", "affected_approved_decisions", "decision_effect", "proposed_changes", "decision_handling", "review"}, "learning-update draft")
    require(draft["schema"] == LEARNING_DRAFT, "learning-update draft schema is invalid")
    discussion_ref, discussion = discussion_binding(root, discussion_path)
    require(draft["study_id"] == discussion["study_id"] and draft["discussion_payload_sha256"] == discussion["payload_sha256"], "learning update discussion binding is stale")
    evidence = [binding(root, path, "learning_evidence") for path in evidence_paths]
    require(draft["evidence_hashes"] == [item["sha256"] for item in evidence], "learning evidence hash is stale")
    handling = exact(draft["decision_handling"], {"approved_decisions_rewritten", "new_confirmation_required", "automatic_promotion"}, "decision_handling")
    require(handling == {"approved_decisions_rewritten": False, "new_confirmation_required": True, "automatic_promotion": False}, "learning update may not rewrite an approved decision")
    affected = strings(draft["affected_approved_decisions"], "affected_approved_decisions", nonempty=False)
    require(draft["decision_effect"] in {"no_change", "invalidates_requires_new_discussion", "proposal_for_review"}, "decision_effect is invalid")
    old_hashes = {item["sha256"] for item in discussion["sources"]["evidence"]}
    changed = any(item["sha256"] not in old_hashes for item in evidence)
    if changed and affected:
        require(draft["decision_effect"] == "invalidates_requires_new_discussion", "changed evidence affecting approval requires renewed confirmation")
    interpretations = []
    for index, raw in enumerate(draft["interpretations"]):
        item = exact(raw, {"text", "origin", "proposal_only"}, f"interpretations[{index}]")
        require(item["origin"] in {"ai_generated", "human_submitted"} and item["proposal_only"] is True, "interpretations must remain proposals")
        interpretations.append({**item, "text": text(item["text"], "interpretation")})
    proposed = []
    for index, raw in enumerate(draft["proposed_changes"]):
        item = exact(raw, {"target_claim_id", "proposal", "origin", "proposal_only"}, f"proposed_changes[{index}]")
        require(item["origin"] in {"ai_generated", "human_submitted"} and item["proposal_only"] is True, "learning changes must remain proposals")
        proposed.append({**item, "target_claim_id": ident(item["target_claim_id"], "target_claim_id"), "proposal": text(item["proposal"], "proposal")})
    review = exact(draft["review"], {"reviewer", "reviewed_at", "notes"}, "review")
    review = {"reviewer": text(review["reviewer"], "reviewer"), "reviewed_at": timestamp(review["reviewed_at"], "reviewed_at"), "notes": strings(review["notes"], "review notes")}
    artifact = {
        "schema": LEARNING, "update_id": ident(draft["update_id"], "update_id"), "study_id": ident(draft["study_id"], "study_id"), "discussion": discussion_ref,
        "evidence": evidence, "observations": strings(draft["observations"], "observations"), "interpretations": interpretations,
        "affected_approved_decisions": affected, "decision_effect": draft["decision_effect"], "proposed_changes": proposed, "decision_handling": handling, "review": review,
        "calculation_ready": False, "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact); rw.write_json(output_file(root, output), artifact)
    return artifact


def validate_learning(root: Path, artifact: dict[str, Any]) -> None:
    exact(artifact, {"schema", "update_id", "study_id", "discussion", "evidence", "observations", "interpretations", "affected_approved_decisions", "decision_effect", "proposed_changes", "decision_handling", "review", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "study learning update")
    require(artifact["schema"] == LEARNING, "learning-update schema is invalid")
    ident(artifact["update_id"], "update_id"); ident(artifact["study_id"], "study_id")
    require(artifact["discussion"].get("role") == "discussion" and artifact["discussion"].get("schema") == DISCUSSION, "learning discussion binding is invalid")
    discussion = validate_binding(root, artifact["discussion"], "discussion"); validate_discussion(root, discussion)
    require(artifact["study_id"] == discussion["study_id"], "learning-update study drift")
    require(isinstance(artifact["evidence"], list) and artifact["evidence"], "learning evidence must not be empty")
    for index, item in enumerate(artifact["evidence"]): validate_binding(root, item, f"learning evidence {index}")
    strings(artifact["observations"], "observations")
    require(isinstance(artifact["interpretations"], list), "interpretations must be an array")
    for index, raw in enumerate(artifact["interpretations"]):
        item = exact(raw, {"text", "origin", "proposal_only"}, f"interpretations[{index}]")
        text(item["text"], "interpretation")
        require(item["origin"] in {"ai_generated", "human_submitted"} and item["proposal_only"] is True, "interpretations must remain proposals")
    affected = strings(artifact["affected_approved_decisions"], "affected_approved_decisions", nonempty=False)
    require(artifact["decision_effect"] in {"no_change", "invalidates_requires_new_discussion", "proposal_for_review"}, "decision_effect is invalid")
    old_hashes = {item["sha256"] for item in discussion["sources"]["evidence"]}
    changed = any(item["sha256"] not in old_hashes for item in artifact["evidence"])
    if changed and affected:
        require(artifact["decision_effect"] == "invalidates_requires_new_discussion", "changed evidence affecting approval requires renewed confirmation")
    require(isinstance(artifact["proposed_changes"], list), "proposed_changes must be an array")
    for index, raw in enumerate(artifact["proposed_changes"]):
        item = exact(raw, {"target_claim_id", "proposal", "origin", "proposal_only"}, f"proposed_changes[{index}]")
        ident(item["target_claim_id"], "target_claim_id"); text(item["proposal"], "proposal")
        require(item["origin"] in {"ai_generated", "human_submitted"} and item["proposal_only"] is True, "learning changes must remain proposals")
    require(artifact["decision_handling"] == {"approved_decisions_rewritten": False, "new_confirmation_required": True, "automatic_promotion": False}, "learning update rewrites approval")
    review = exact(artifact["review"], {"reviewer", "reviewed_at", "notes"}, "review")
    text(review["reviewer"], "reviewer"); timestamp(review["reviewed_at"], "reviewed_at"); strings(review["notes"], "review notes")
    require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "learning-update authority boundary changed")
    rw.validate_payload_hash(artifact)


def validate(root: Path, path: Path) -> dict[str, Any]:
    document = rw.load_json(package_file(root, path, "artifact"))
    schema = document.get("schema")
    if schema == DISCUSSION: validate_discussion(root, document)
    elif schema == ACTION_CARD: validate_action(root, document)
    elif schema == LEARNING: validate_learning(root, document)
    else: raise DecisionError("unsupported human scientific-decision schema")
    return {"valid": True, "schema": schema, "payload_sha256": document["payload_sha256"], "live_actions": False, "no_submission_authorization": True}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__); sub = result.add_subparsers(dest="command", required=True)
    discussion = sub.add_parser("build-discussion"); discussion.add_argument("--root", required=True); discussion.add_argument("draft"); discussion.add_argument("--mechanism", required=True); discussion.add_argument("--network", required=True); discussion.add_argument("--evidence", action="append", required=True); discussion.add_argument("--output", required=True)
    action = sub.add_parser("build-action-card"); action.add_argument("--root", required=True); action.add_argument("draft"); action.add_argument("--discussion", required=True); action.add_argument("--output", required=True)
    learning = sub.add_parser("build-learning-update"); learning.add_argument("--root", required=True); learning.add_argument("draft"); learning.add_argument("--discussion", required=True); learning.add_argument("--evidence", action="append", required=True); learning.add_argument("--output", required=True)
    check = sub.add_parser("validate"); check.add_argument("--root", required=True); check.add_argument("artifact")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = package_root(Path(args.root))
        if args.command == "build-discussion": document = build_discussion(root, Path(args.draft), Path(args.mechanism), Path(args.network), [Path(item) for item in args.evidence], Path(args.output))
        elif args.command == "build-action-card": document = build_action(root, Path(args.draft), Path(args.discussion), Path(args.output))
        elif args.command == "build-learning-update": document = build_learning(root, Path(args.draft), Path(args.discussion), [Path(item) for item in args.evidence], Path(args.output))
        else:
            print(json.dumps(validate(root, Path(args.artifact)), indent=2)); return 0
        print(json.dumps({"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False, "no_submission_authorization": True}, indent=2)); return 0
    except (DecisionError, rw.OfflineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
