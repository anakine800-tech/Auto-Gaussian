#!/usr/bin/env python3
"""Build and audit offline main-group multiplicity families without live actions."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("open_shell_state_family_dependency", HERE / "open_shell_state.py")
assert _SPEC and _SPEC.loader
STATE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(STATE)

SCHEMA_SOURCE = "auto-g16-main-group-multiplicity-family-source/1"
SCHEMA_PLAN = "auto-g16-main-group-multiplicity-family-plan/1"
SCHEMA_AUDIT = "auto-g16-main-group-multiplicity-family-comparison-audit/1"
SCHEMA_COMMON = "auto-g16-main-group-multiplicity-comparison-protocol/1"
SCHEMA_MEMBER_PROTOCOL = "auto-g16-main-group-multiplicity-member-protocol/1"
SCHEMA_MEMBER_INPUT = "auto-g16-main-group-multiplicity-member-input-lineage/1"
SUPPORTED = "v1_handoff_candidate"
BLOCKED = "blocked_needs_specialist"
AUTHORITY = {"calculation_ready": False, "no_submission_authorization": True}


ContractError = STATE.ContractError
require = STATE.require


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    return STATE._exact(value, keys, label)


def _text(value: Any, label: str) -> str:
    return STATE._text(value, label)


def _id(value: Any, label: str) -> str:
    text = _text(value, label)
    require(STATE.ID_RE.fullmatch(text) is not None, f"invalid {label}")
    return text


def _hash(value: Any, label: str) -> str:
    require(isinstance(value, str) and STATE.SHA_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _authority(document: dict[str, Any], label: str) -> None:
    require(document.get("calculation_ready") is False, f"{label} calculation_ready must be false")
    require(document.get("no_submission_authorization") is True, f"{label} must not authorize submission")


def _binding(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": STATE.portable_path(path),
        "sha256": STATE.file_sha256(path),
        "schema": document.get("schema"),
        "payload_sha256": document.get("payload_sha256", STATE.payload_sha256(document)),
    }


def _validate_binding(value: Any, label: str) -> dict[str, Any]:
    binding = _exact(value, {"path", "sha256", "schema", "payload_sha256"}, label)
    _text(binding["path"], f"{label}.path")
    _hash(binding["sha256"], f"{label}.sha256")
    _text(binding["schema"], f"{label}.schema")
    _hash(binding["payload_sha256"], f"{label}.payload_sha256")
    return binding


def _load_sealed(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    resolved, document = STATE.load_json(path, canonical=True, label=label)
    _hash(document.get("payload_sha256"), f"{label} payload hash")
    require(document["payload_sha256"] == STATE.payload_sha256(document), f"{label} payload hash mismatch")
    _authority(document, label)
    return resolved, document


def validate_common_protocol(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "protocol_id", "approval", "energy_quantity", "common_reference", "comparability_statement", "thermochemistry_policy", "ground_state_policy", "settings_sha256", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "common comparison protocol")
    require(document["schema"] == SCHEMA_COMMON, "common comparison protocol schema mismatch")
    _id(document["protocol_id"], "protocol_id")
    approval = _exact(document["approval"], {"decision", "reviewer", "rationale", "confirmed"}, "comparison approval")
    require(approval["decision"] == "approved_common_comparison_protocol" and approval["confirmed"] is True, "common comparison protocol requires explicit human approval")
    _text(approval["reviewer"], "comparison reviewer")
    _text(approval["rationale"], "comparison rationale")
    require(document["energy_quantity"] == "electronic_energy_hartree", "V1 comparison permits electronic energy only")
    _text(document["common_reference"], "common_reference")
    _text(document["comparability_statement"], "comparability_statement")
    require(document["thermochemistry_policy"] == "not_compared", "V1 must not mix thermochemistry")
    require(document["ground_state_policy"] == "no_automatic_ground_state_claim", "ground-state claims are forbidden")
    _hash(document["settings_sha256"], "settings_sha256")
    _authority(document, "common comparison protocol")
    require(document["payload_sha256"] == STATE.payload_sha256(document), "common comparison protocol payload hash mismatch")


def validate_member_protocol(document: dict[str, Any], member_id: str, common: dict[str, Any], disposition: str) -> None:
    _exact(document, {"schema", "member_id", "disposition", "candidate_payload_sha256", "state_review_payload_sha256", "common_protocol_payload_sha256", "comparison_settings_sha256", "method_selection_source", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "member protocol")
    require(document["schema"] == SCHEMA_MEMBER_PROTOCOL and document["member_id"] == member_id, "member protocol identity mismatch")
    require(document["disposition"] == disposition, "member protocol disposition drift")
    for key in ("candidate_payload_sha256", "state_review_payload_sha256", "common_protocol_payload_sha256", "comparison_settings_sha256"):
        _hash(document[key], f"member protocol {key}")
    require(document["common_protocol_payload_sha256"] == common["payload_sha256"], "member protocol common-protocol binding drift")
    require(document["comparison_settings_sha256"] == common["settings_sha256"], "member comparison settings drift")
    _text(document["method_selection_source"], "method_selection_source")
    _authority(document, "member protocol")
    require(document["payload_sha256"] == STATE.payload_sha256(document), "member protocol payload hash mismatch")


def validate_member_input(document: dict[str, Any], member_id: str, disposition: str, candidate_payload: str, protocol_payload: str) -> None:
    _exact(document, {"schema", "member_id", "disposition", "candidate_payload_sha256", "member_protocol_payload_sha256", "input_artifact_sha256", "handoff_status", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "member input lineage")
    require(document["schema"] == SCHEMA_MEMBER_INPUT and document["member_id"] == member_id, "member input lineage identity mismatch")
    require(document["disposition"] == disposition, "member input lineage disposition drift")
    require(document["candidate_payload_sha256"] == candidate_payload, "member input candidate binding drift")
    require(document["member_protocol_payload_sha256"] == protocol_payload, "member input protocol binding drift")
    if disposition == SUPPORTED:
        _hash(document["input_artifact_sha256"], "input artifact hash")
        require(document["handoff_status"] == "eligible_after_separate_input_approval", "supported member input status mismatch")
    else:
        require(document["input_artifact_sha256"] is None, "blocked member must not carry an input artifact hash")
        require(document["handoff_status"] == BLOCKED, "blocked member input status mismatch")
    _authority(document, "member input lineage")
    require(document["payload_sha256"] == STATE.payload_sha256(document), "member input lineage payload hash mismatch")


def validate_source(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "family_id", "composition_signature", "structure_relationship", "common_protocol_path", "members", "comparison_claims", "review", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "family source")
    require(document["schema"] == SCHEMA_SOURCE, "family source schema mismatch")
    _id(document["family_id"], "family_id")
    _text(document["composition_signature"], "composition_signature")
    relationship = _exact(document["structure_relationship"], {"kind", "statement", "atom_mapping_reviewed", "confirmed"}, "structure relationship")
    require(relationship["kind"] in {"same_composition_reviewed_atom_mapping", "same_exact_structure_different_state"}, "unsupported structure relationship")
    _text(relationship["statement"], "structure relationship statement")
    require(relationship["atom_mapping_reviewed"] is True and relationship["confirmed"] is True, "structure relationship requires explicit review")
    _text(document["common_protocol_path"], "common_protocol_path")
    members = document["members"]
    require(isinstance(members, list) and len(members) >= 2, "family requires at least two members")
    ids: set[str] = set()
    multiplicities: set[int] = set()
    for index, member in enumerate(members):
        _exact(member, {"member_id", "state_label", "multiplicity", "disposition", "candidate_path", "state_review_path", "protocol_path", "input_lineage_path"}, f"members[{index}]")
        member_id = _id(member["member_id"], f"members[{index}].member_id")
        require(member_id not in ids, "family member ids must be unique")
        ids.add(member_id)
        require(isinstance(member["multiplicity"], int) and not isinstance(member["multiplicity"], bool) and member["multiplicity"] >= 1, "member multiplicity invalid")
        require(member["multiplicity"] not in multiplicities, "family multiplicities must be unique")
        multiplicities.add(member["multiplicity"])
        require(member["disposition"] in {SUPPORTED, BLOCKED}, "member disposition invalid")
        _text(member["state_label"], "state_label")
        for key in ("candidate_path", "state_review_path", "protocol_path", "input_lineage_path"):
            _text(member[key], f"member {key}")
    claims = _exact(document["comparison_claims"], {"energy_ordering", "ground_state", "thermochemistry"}, "comparison claims")
    require(claims == {"energy_ordering": "not_claimed", "ground_state": "not_claimed", "thermochemistry": "not_compared"}, "family source must not assert energy ordering, ground state, or thermochemistry")
    review = _exact(document["review"], {"reviewer", "rationale", "confirmed"}, "family review")
    _text(review["reviewer"], "family reviewer")
    _text(review["rationale"], "family review rationale")
    require(review["confirmed"] is True, "family review must be confirmed")
    _authority(document, "family source")
    require(document["payload_sha256"] == STATE.payload_sha256(document), "family source payload hash mismatch")


def build_plan(source_path: str | Path) -> dict[str, Any]:
    source_file, source = _load_sealed(source_path, "family source")
    validate_source(source)
    common_file, common = _load_sealed(source["common_protocol_path"], "common comparison protocol")
    validate_common_protocol(common)
    plan_members = []
    unique_lineages: dict[str, set[str]] = {key: set() for key in ("candidate", "state_review", "protocol", "input")}
    family_composition: tuple[tuple[tuple[str, int], ...], int, int] | None = None
    for member in source["members"]:
        member_id = member["member_id"]
        disposition = member["disposition"]
        candidate_file, candidate = STATE.load_json(member["candidate_path"], label=f"{member_id} candidate")
        review_file, review = _load_sealed(member["state_review_path"], f"{member_id} state review")
        protocol_file, protocol = _load_sealed(member["protocol_path"], f"{member_id} protocol")
        input_file, input_lineage = _load_sealed(member["input_lineage_path"], f"{member_id} input lineage")
        STATE.validate_candidate(candidate)
        require(all(atom["element"] in STATE.MAIN_GROUP_SYMBOLS for atom in candidate["atoms"]), "multiplicity family is main-group only")
        counts: dict[str, int] = {}
        for atom in candidate["atoms"]:
            counts[atom["element"]] = counts.get(atom["element"], 0) + 1
        composition = (tuple(sorted(counts.items())), len(candidate["atoms"]), candidate["charge"])
        if family_composition is None:
            family_composition = composition
        else:
            require(composition == family_composition, "family member composition, atom count, or charge drift")
        require(candidate["candidate_id"] == member_id and candidate["multiplicity"] == member["multiplicity"], "family member/candidate identity drift")
        STATE.validate_review(review, check_sources=True)
        require(review["candidate_snapshot"] == candidate, "family member review is not bound to its candidate")
        if disposition == SUPPORTED:
            require(review["status"] == "accepted" and review["state_assessment"]["v1_classification"] == "supported_single_reference_minimum", "handoff candidate lacks accepted V1 state review")
        else:
            require(review["status"] == "blocked", "unsupported member must retain a blocked state review")
        validate_member_protocol(protocol, member_id, common, disposition)
        candidate_payload = STATE.payload_sha256(candidate)
        require(protocol["candidate_payload_sha256"] == candidate_payload, "member protocol candidate lineage drift")
        require(protocol["state_review_payload_sha256"] == review["payload_sha256"], "member protocol review lineage drift")
        validate_member_input(input_lineage, member_id, disposition, candidate_payload, protocol["payload_sha256"])
        artifacts = {
            "candidate": _binding(candidate_file, candidate),
            "state_review": _binding(review_file, review),
            "protocol": _binding(protocol_file, protocol),
            "input_lineage": _binding(input_file, input_lineage),
        }
        for kind, binding in artifacts.items():
            bucket = "input" if kind == "input_lineage" else kind
            require(binding["sha256"] not in unique_lineages[bucket], f"{bucket} file hash reused across family members")
            unique_lineages[bucket].add(binding["sha256"])
        plan_members.append({
            "member_id": member_id,
            "state_label": member["state_label"],
            "multiplicity": member["multiplicity"],
            "disposition": disposition,
            "lineage": artifacts,
            "handoff_status": "eligible_after_separate_input_approval" if disposition == SUPPORTED else BLOCKED,
            "result_lineage_status": "awaiting_independent_result" if disposition == SUPPORTED else BLOCKED,
        })
    supported_count = sum(item["disposition"] == SUPPORTED for item in plan_members)
    document = {
        "schema": SCHEMA_PLAN,
        "family_id": source["family_id"],
        "source": _binding(source_file, source),
        "composition_signature": source["composition_signature"],
        "structure_relationship": source["structure_relationship"],
        "common_comparison_protocol": _binding(common_file, common),
        "members": plan_members,
        "planning_status": "ready_for_independent_v1_handoffs" if supported_count else "blocked_no_supported_v1_members",
        "comparison_status": "planned_not_performed",
        "exclusions": ["transition_metals", "spin_crossing", "mecp", "automatic_ground_state_claim", "automatic_multireference_inference", "thermochemistry_mixing", "cross_multiplicity_conformer_ensemble"],
        **AUTHORITY,
    }
    document["payload_sha256"] = STATE.payload_sha256(document)
    validate_plan(document, check_sources=False)
    return document


def validate_plan(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "family_id", "source", "composition_signature", "structure_relationship", "common_comparison_protocol", "members", "planning_status", "comparison_status", "exclusions", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "family plan")
    require(document["schema"] == SCHEMA_PLAN, "family plan schema mismatch")
    _id(document["family_id"], "family_id")
    _validate_binding(document["source"], "family plan source")
    _validate_binding(document["common_comparison_protocol"], "common comparison protocol")
    require(document["comparison_status"] == "planned_not_performed", "family plan cannot claim a comparison")
    require(document["planning_status"] in {"ready_for_independent_v1_handoffs", "blocked_no_supported_v1_members"}, "family planning status invalid")
    require(isinstance(document["members"], list) and len(document["members"]) >= 2, "family plan requires members")
    for member in document["members"]:
        _exact(member, {"member_id", "state_label", "multiplicity", "disposition", "lineage", "handoff_status", "result_lineage_status"}, "family plan member")
        lineage = _exact(member["lineage"], {"candidate", "state_review", "protocol", "input_lineage"}, "member lineage")
        for key, binding in lineage.items():
            _validate_binding(binding, f"member {key}")
        if member["disposition"] == SUPPORTED:
            require(member["handoff_status"] == "eligible_after_separate_input_approval" and member["result_lineage_status"] == "awaiting_independent_result", "supported member status drift")
        else:
            require(member["disposition"] == BLOCKED and member["handoff_status"] == BLOCKED and member["result_lineage_status"] == BLOCKED, "blocked member status drift")
    required_exclusions = {"transition_metals", "spin_crossing", "mecp", "automatic_ground_state_claim", "automatic_multireference_inference", "thermochemistry_mixing", "cross_multiplicity_conformer_ensemble"}
    require(set(document["exclusions"]) == required_exclusions, "family plan exclusions changed")
    _authority(document, "family plan")
    require(document["payload_sha256"] == STATE.payload_sha256(document), "family plan payload hash mismatch")
    if check_sources:
        source_path, source = _load_sealed(document["source"]["path"], "bound family source")
        require(_binding(source_path, source) == document["source"], "family plan source binding drift")
        require(build_plan(source_path) == document, "family plan differs from deterministic reconstruction")


def build_audit(plan_path: str | Path, result_manifest_path: str | Path) -> dict[str, Any]:
    plan_file, plan = _load_sealed(plan_path, "family plan")
    validate_plan(plan, check_sources=True)
    manifest_file, manifest = _load_sealed(result_manifest_path, "family result manifest")
    _exact(manifest, {"schema", "family_id", "results", "comparison_statement", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "result manifest")
    require(manifest["schema"] == "auto-g16-main-group-multiplicity-family-result-manifest/1", "result manifest schema mismatch")
    require(manifest["family_id"] == plan["family_id"], "result manifest family drift")
    require(manifest["comparison_statement"] == "no_energy_ordering_or_ground_state_claim", "result manifest contains a forbidden comparison claim")
    by_id = {item["member_id"]: item for item in plan["members"]}
    require(isinstance(manifest["results"], list) and {item.get("member_id") for item in manifest["results"]} == set(by_id), "result manifest member set drift")
    rows = []
    accepted_count = 0
    result_hashes: set[str] = set()
    for result in manifest["results"]:
        _exact(result, {"member_id", "acceptance_path"}, "result manifest member")
        member = by_id[result["member_id"]]
        if member["disposition"] == BLOCKED:
            require(result["acceptance_path"] is None, "blocked/needs-specialist member must not carry V1 result acceptance")
            rows.append({"member_id": result["member_id"], "multiplicity": member["multiplicity"], "status": BLOCKED, "result": None, "electronic_energy_hartree": None})
            continue
        acceptance_file, acceptance = _load_sealed(result["acceptance_path"], f"{result['member_id']} result acceptance")
        STATE.validate_acceptance(acceptance, check_sources=True)
        require(acceptance["status"] == "accepted", "family comparison requires accepted V1 result evidence")
        review_file, review = STATE.load_validated_review(acceptance["review_source"]["path"])
        candidate_binding = member["lineage"]["candidate"]
        require(STATE.payload_sha256(review["candidate_snapshot"]) == candidate_binding["payload_sha256"], "result acceptance candidate lineage drift")
        require(STATE.file_sha256(acceptance_file) not in result_hashes, "result acceptance hash reused across members")
        result_hashes.add(STATE.file_sha256(acceptance_file))
        _, observation = STATE.load_validated_observation(acceptance["observation_source"]["path"])
        energy = observation["facts"]["scf"]["energy_hartree"]
        require(energy is not None, "accepted result lacks electronic energy")
        accepted_count += 1
        rows.append({"member_id": result["member_id"], "multiplicity": member["multiplicity"], "status": "accepted_v1_evidence", "result": _binding(acceptance_file, acceptance), "electronic_energy_hartree": energy})
    status = "comparable_without_ordering_claim" if accepted_count >= 2 else "blocked_insufficient_supported_results"
    document = {
        "schema": SCHEMA_AUDIT,
        "family_id": plan["family_id"],
        "plan": _binding(plan_file, plan),
        "result_manifest": _binding(manifest_file, manifest),
        "common_comparison_protocol": plan["common_comparison_protocol"],
        "members": rows,
        "comparison_status": status,
        "energy_ordering": "not_evaluated",
        "ground_state_claim": "not_made",
        "thermochemistry": "not_compared",
        "multireference_inference": "not_made_from_energy_proximity",
        **AUTHORITY,
    }
    document["payload_sha256"] = STATE.payload_sha256(document)
    validate_audit(document, check_sources=False)
    return document


def validate_audit(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "family_id", "plan", "result_manifest", "common_comparison_protocol", "members", "comparison_status", "energy_ordering", "ground_state_claim", "thermochemistry", "multireference_inference", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "family comparison audit")
    require(document["schema"] == SCHEMA_AUDIT, "family comparison audit schema mismatch")
    for key in ("plan", "result_manifest", "common_comparison_protocol"):
        _validate_binding(document[key], f"audit {key}")
    require(document["comparison_status"] in {"comparable_without_ordering_claim", "blocked_insufficient_supported_results"}, "comparison audit status invalid")
    require(document["energy_ordering"] == "not_evaluated" and document["ground_state_claim"] == "not_made", "comparison audit made a forbidden energy-ordering/ground-state claim")
    require(document["thermochemistry"] == "not_compared", "comparison audit mixed thermochemistry")
    require(document["multireference_inference"] == "not_made_from_energy_proximity", "comparison audit inferred multireference character")
    _authority(document, "family comparison audit")
    require(document["payload_sha256"] == STATE.payload_sha256(document), "family comparison audit payload hash mismatch")
    if check_sources:
        plan_path, plan = _load_sealed(document["plan"]["path"], "bound family plan")
        manifest_path, manifest = _load_sealed(document["result_manifest"]["path"], "bound result manifest")
        require(_binding(plan_path, plan) == document["plan"], "comparison audit plan binding drift")
        require(_binding(manifest_path, manifest) == document["result_manifest"], "comparison audit result-manifest binding drift")
        require(build_audit(plan_path, manifest_path) == document, "comparison audit differs from deterministic reconstruction")


def validate_artifact(path: str | Path) -> dict[str, Any]:
    _, document = _load_sealed(path, "multiplicity-family artifact")
    schema = document.get("schema")
    if schema == SCHEMA_SOURCE:
        validate_source(document)
    elif schema == SCHEMA_PLAN:
        validate_plan(document, check_sources=True)
    elif schema == SCHEMA_AUDIT:
        validate_audit(document, check_sources=True)
    elif schema == SCHEMA_COMMON:
        validate_common_protocol(document)
    else:
        raise ContractError("unknown multiplicity-family artifact schema")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("source")
    plan.add_argument("--output", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("plan")
    audit.add_argument("--results", required=True)
    audit.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            document = build_plan(args.source)
            STATE.write_new_json(args.output, document)
        elif args.command == "audit":
            document = build_audit(args.plan, args.results)
            STATE.write_new_json(args.output, document)
        else:
            document = validate_artifact(args.artifact)
        print(json.dumps({"valid": True, "schema": document["schema"], "status": document.get("planning_status", document.get("comparison_status")), "live_actions": False}, ensure_ascii=False))
        return 0
    except (ContractError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
