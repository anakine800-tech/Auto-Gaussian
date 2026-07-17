#!/usr/bin/env python3
"""Offline contracts for candidate-bound main-group open-shell TS/Freq/IRC."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


WORKFLOW_SCHEMA = "auto-g16-main-group-open-shell-ts-irc-workflow/1"
INPUT_AUDIT_SCHEMA = "auto-g16-main-group-open-shell-ts-irc-input-audit/1"
TS_ACCEPTANCE_SCHEMA = "auto-g16-main-group-open-shell-ts-acceptance/1"
IRC_PLAN_SCHEMA = "auto-g16-main-group-open-shell-irc-plan/1"
IRC_ACCEPTANCE_SCHEMA = "auto-g16-main-group-open-shell-irc-path-acceptance/1"
WORKFLOW_KIND = "main_group_open_shell_single_surface_ts_freq_irc"
SHA_RE = re.compile(r"[0-9a-f]{64}")
ID_RE = re.compile(r"[a-z][a-z0-9_]{2,63}")
SUPPORTED_STATE_FAMILIES = {"doublet_ground_state", "high_spin_triplet", "triplet_carbene"}
SUPPORTED_MULTIPLICITIES = {2, 3}
AUTHORIZATIONS = {
    "render_input": False,
    "gaussian": False,
    "ssh": False,
    "pbs": False,
    "submit": False,
    "retry": False,
    "cancel": False,
    "cleanup": False,
    "deploy": False,
}


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def payload_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes({key: child for key, child in value.items() if key != "payload_sha256"})).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_path(value: str | Path, label: str, *, output: bool = False) -> Path:
    path = Path(value).expanduser()
    require(not path.is_symlink(), f"{label} must not be a symlink")
    parent = path.parent.resolve(strict=True)
    require(not any(part.is_symlink() for part in list(path.parents) if part.exists()), f"{label} path contains a symlink")
    resolved = parent / path.name
    if output:
        require(not resolved.exists(), f"refusing to overwrite existing {label}")
    else:
        require(resolved.is_file(), f"{label} must be an existing file")
    return resolved


def _reject_constant(_: str) -> None:
    raise ContractError("non-finite JSON value")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        require(key not in value, f"duplicate JSON key: {key}")
        value[key] = child
    return value


def load_json(value: str | Path, label: str, *, canonical: bool = False) -> tuple[Path, dict[str, Any]]:
    path = _safe_path(value, label)
    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    require(isinstance(document, dict), f"{label} must be a JSON object")
    if canonical:
        require(path.read_bytes() == canonical_bytes(document), f"{label} must use canonical JSON encoding")
    return path, document


def write_new_json(value: str | Path, document: dict[str, Any]) -> Path:
    path = _safe_path(value, "output artifact", output=True)
    path.write_bytes(canonical_bytes(document))
    return path


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    missing, extra = keys - set(value), set(value) - keys
    require(not missing and not extra, f"{label} fields invalid; missing={sorted(missing)} unknown={sorted(extra)}")
    return value


def _text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip() and "<" not in value and ">" not in value, f"{label} must be explicit non-placeholder text")
    return value


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be SHA-256")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), f"{label} must be finite")
    if minimum is not None:
        require(value >= minimum, f"{label} must be >= {minimum}")
    return float(value)


def _binding(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    binding = {"path": str(path), "sha256": file_sha256(path)}
    if "payload_sha256" in document:
        binding["payload_sha256"] = document["payload_sha256"]
    return binding


def _authority(document: dict[str, Any], label: str) -> None:
    require(document.get("calculation_ready") is False, f"{label} calculation_ready must remain false")
    require(document.get("no_submission_authorization") is True, f"{label} no_submission_authorization must remain true")
    require(document.get("authorizations") == AUTHORIZATIONS, f"{label} authorization boundary changed")


def _load_open_shell_module() -> Any:
    source = Path(__file__).with_name("open_shell_state.py")
    spec = importlib.util.spec_from_file_location("open_shell_state_for_ts_irc", source)
    require(spec is not None and spec.loader is not None, "cannot load open-shell state owner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_ts_candidate(candidate: dict[str, Any]) -> None:
    _exact(candidate, {"schema", "candidate_id", "structure_sha256", "atoms", "charge", "multiplicity", "state_family", "electronic_scope", "structure_role", "workflow_scope", "exclusions", "calculation_ready", "no_submission_authorization"}, "TS candidate")
    require(candidate["schema"] == "auto-g16-main-group-open-shell-ts-candidate/1", "TS candidate schema mismatch")
    require(ID_RE.fullmatch(str(candidate["candidate_id"])) is not None, "invalid TS candidate_id")
    _sha(candidate["structure_sha256"], "TS structure hash")
    require(isinstance(candidate["atoms"], list) and candidate["atoms"], "TS atoms missing")
    for index, atom in enumerate(candidate["atoms"], 1):
        _exact(atom, {"index", "element"}, f"TS atom {index}")
        require(atom["index"] == index and isinstance(atom["element"], str), "TS atom order invalid")
        require(atom["element"] not in {"Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg"}, "transition metal is outside open-shell TS/IRC scope")
    require(isinstance(candidate["charge"], int), "TS charge must be integer")
    require(candidate["multiplicity"] in SUPPORTED_MULTIPLICITIES, "only doublet or high-spin triplet is supported")
    require(candidate["state_family"] in SUPPORTED_STATE_FAMILIES, "state family is outside supported open-shell scope")
    require(candidate["electronic_scope"] == "single_reference_ground_state", "multireference, excited, broken-symmetry, and open-shell singlet states are blocked")
    require(candidate["structure_role"] == "transition_state_candidate", "candidate must be a TS candidate")
    require(candidate["workflow_scope"] == "same_spin_surface_ts_freq_irc", "spin crossing and MECP are blocked")
    require(candidate["exclusions"] == {"transition_metal": False, "spin_crossing_or_mecp": False, "open_shell_singlet": False, "multireference": False, "different_multiplicity_endpoints": False}, "TS exclusions must be explicit and all false")
    require(candidate["calculation_ready"] is False and candidate["no_submission_authorization"] is True, "TS candidate authority boundary changed")


def _validate_protocol(protocol: dict[str, Any]) -> None:
    _exact(protocol, {"schema", "protocol_id", "workflow_kind", "candidate_id", "structure_sha256", "charge", "multiplicity", "state_family", "wavefunction_reference", "same_spin_surface", "single_reference", "stages", "spin_policy", "endpoint_policy", "review", "calculation_ready", "no_submission_authorization"}, "protocol")
    require(protocol["schema"] == "auto-g16-main-group-open-shell-ts-irc-protocol-source/1", "protocol schema mismatch")
    require(ID_RE.fullmatch(str(protocol["protocol_id"])) is not None, "invalid protocol_id")
    require(protocol["workflow_kind"] == WORKFLOW_KIND, "protocol workflow kind mismatch")
    _sha(protocol["structure_sha256"], "protocol structure hash")
    require(protocol["multiplicity"] in SUPPORTED_MULTIPLICITIES and protocol["state_family"] in SUPPORTED_STATE_FAMILIES, "protocol state is unsupported")
    require(protocol["wavefunction_reference"] in {"U", "RO"}, "protocol reference must be U or RO")
    require(protocol["same_spin_surface"] is True and protocol["single_reference"] is True, "protocol must remain same-surface single-reference")
    stages = _exact(protocol["stages"], {"ts_freq", "irc_forward", "irc_reverse"}, "protocol stages")
    for name, stage in stages.items():
        _exact(stage, {"route", "method", "basis", "solvent", "resources", "settings", "protocol_selection_payload_sha256"}, f"protocol stage {name}")
        for key in ("route", "method", "basis", "solvent", "resources", "settings"):
            _text(stage[key], f"{name}.{key}")
        _sha(stage["protocol_selection_payload_sha256"], f"{name} selection hash")
        route = stage["route"].lower()
        require((name == "ts_freq" and "freq" in route) or (name != "ts_freq" and "irc" in route), f"{name} route lacks explicit stage keyword")
        if name == "irc_forward":
            require("forward" in route and "reverse" not in route, "forward route direction invalid")
        if name == "irc_reverse":
            require("reverse" in route and "forward" not in route, "reverse route direction invalid")
    spin = _exact(protocol["spin_policy"], {"target_s2", "max_abs_post_annihilation_s2_deviation", "stability_required", "reference_continuity_required"}, "spin policy")
    _number(spin["target_s2"], "target S2", minimum=0)
    _number(spin["max_abs_post_annihilation_s2_deviation"], "S2 threshold", minimum=0)
    require(spin["stability_required"] is True and spin["reference_continuity_required"] is True, "spin diagnostics must be mandatory")
    endpoint = _exact(protocol["endpoint_policy"], {"require_both_directions", "require_identified_reactant_and_product", "require_same_charge_multiplicity_state_lineage"}, "endpoint policy")
    require(all(value is True for value in endpoint.values()), "endpoint continuity policy cannot be relaxed")
    review = _exact(protocol["review"], {"decision", "reviewer", "rationale", "confirmed"}, "protocol review")
    require(review["decision"] == "accepted_for_offline_contract" and review["confirmed"] is True, "protocol must be explicitly accepted")
    _text(review["reviewer"], "protocol reviewer"); _text(review["rationale"], "protocol rationale")
    require(protocol["calculation_ready"] is False and protocol["no_submission_authorization"] is True, "protocol authority boundary changed")


def build_workflow(state_review_path: str | Path, candidate_path: str | Path, protocol_path: str | Path, workflow_id: str) -> dict[str, Any]:
    require(ID_RE.fullmatch(workflow_id) is not None, "invalid workflow_id")
    owner = _load_open_shell_module()
    state_path, state_review = owner.load_validated_review(state_review_path)
    candidate_file, candidate = load_json(candidate_path, "TS candidate")
    protocol_file, protocol = load_json(protocol_path, "TS/IRC protocol")
    _validate_ts_candidate(candidate); _validate_protocol(protocol)
    require(state_review["status"] == "accepted" and state_review["conclusion"]["decision"] == "accepted_for_v1_protocol_gate", "state review is not accepted")
    state = state_review["candidate_snapshot"]
    require(state["charge"] == candidate["charge"] == protocol["charge"], "charge lineage drift")
    require(state["multiplicity"] == candidate["multiplicity"] == protocol["multiplicity"], "multiplicity lineage drift")
    require(state["state_family"] == candidate["state_family"] == protocol["state_family"], "state-family lineage drift")
    require(state_review["wavefunction_policy"]["reference"] == protocol["wavefunction_reference"], "U/RO reference drift")
    require(candidate["candidate_id"] == protocol["candidate_id"] and candidate["structure_sha256"] == protocol["structure_sha256"], "candidate/protocol binding mismatch")
    require([atom["element"] for atom in state["atoms"]] == [atom["element"] for atom in candidate["atoms"]], "state-review and TS candidate atom order/composition mismatch")
    document = {
        "schema": WORKFLOW_SCHEMA, "workflow_id": workflow_id, "workflow_kind": WORKFLOW_KIND, "status": "planned_offline",
        "state_review": _binding(state_path, state_review), "candidate": _binding(candidate_file, candidate), "protocol": _binding(protocol_file, protocol),
        "state_lineage": {"candidate_id": candidate["candidate_id"], "structure_sha256": candidate["structure_sha256"], "charge": candidate["charge"], "multiplicity": candidate["multiplicity"], "state_family": candidate["state_family"], "wavefunction_reference": protocol["wavefunction_reference"], "target_s2": protocol["spin_policy"]["target_s2"], "max_abs_post_annihilation_s2_deviation": protocol["spin_policy"]["max_abs_post_annihilation_s2_deviation"], "expected_frequency_count": state_review["state_assessment"]["expected_frequency_count"], "atom_elements": [atom["element"] for atom in candidate["atoms"]]},
        "blocked_scope": ["spin_crossing_or_mecp", "open_shell_singlet", "multireference", "different_multiplicity_endpoints", "transition_metal", "execution"],
        "calculation_ready": False, "no_submission_authorization": True, "authorizations": AUTHORIZATIONS,
    }
    document["payload_sha256"] = payload_sha256(document)
    validate_workflow(document, check_sources=False)
    return document


def validate_workflow(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "workflow_id", "workflow_kind", "status", "state_review", "candidate", "protocol", "state_lineage", "blocked_scope", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "workflow")
    require(document["schema"] == WORKFLOW_SCHEMA and document["workflow_kind"] == WORKFLOW_KIND and document["status"] == "planned_offline", "workflow identity invalid")
    for label in ("state_review", "candidate", "protocol"):
        binding = document[label]; require(isinstance(binding, dict), f"{label} binding invalid"); _sha(binding["sha256"], f"{label} file hash")
    lineage = _exact(document["state_lineage"], {"candidate_id", "structure_sha256", "charge", "multiplicity", "state_family", "wavefunction_reference", "target_s2", "max_abs_post_annihilation_s2_deviation", "expected_frequency_count", "atom_elements"}, "state lineage")
    require(lineage["multiplicity"] in SUPPORTED_MULTIPLICITIES and lineage["state_family"] in SUPPORTED_STATE_FAMILIES and lineage["wavefunction_reference"] in {"U", "RO"}, "workflow state lineage unsupported")
    require(document["blocked_scope"] == ["spin_crossing_or_mecp", "open_shell_singlet", "multireference", "different_multiplicity_endpoints", "transition_metal", "execution"], "workflow exclusions changed")
    _authority(document, "workflow"); require(document["payload_sha256"] == payload_sha256(document), "workflow payload hash mismatch")
    if check_sources:
        rebuilt = build_workflow(document["state_review"]["path"], document["candidate"]["path"], document["protocol"]["path"], document["workflow_id"])
        require(rebuilt == document, "workflow differs from bound-source reconstruction")


def build_input_audit(workflow_path: str | Path, source_path: str | Path) -> dict[str, Any]:
    workflow_file, workflow = load_json(workflow_path, "workflow", canonical=True); validate_workflow(workflow, check_sources=True)
    source_file, source = load_json(source_path, "input audit source")
    _exact(source, {"schema", "audit_id", "stage", "workflow_payload_sha256", "state_review_payload_sha256", "candidate_sha256", "protocol_file_sha256", "protocol_selection_payload_sha256", "input", "charge", "multiplicity", "state_family", "wavefunction_reference", "same_spin_surface", "settings_reviewed", "review", "calculation_ready", "no_submission_authorization"}, "input audit source")
    require(source["schema"] == "auto-g16-main-group-open-shell-ts-irc-input-audit-source/1", "input audit source schema mismatch")
    require(source["stage"] in {"ts_freq", "irc_forward", "irc_reverse"}, "input stage invalid")
    protocol_path, protocol = load_json(workflow["protocol"]["path"], "bound protocol"); _validate_protocol(protocol)
    stage = protocol["stages"][source["stage"]]
    expected = {"workflow_payload_sha256": workflow["payload_sha256"], "state_review_payload_sha256": workflow["state_review"]["payload_sha256"], "candidate_sha256": workflow["candidate"]["sha256"], "protocol_file_sha256": workflow["protocol"]["sha256"], "protocol_selection_payload_sha256": stage["protocol_selection_payload_sha256"]}
    require(all(source[key] == value for key, value in expected.items()), "input source lineage or hash drift")
    lineage = workflow["state_lineage"]
    require(source["charge"] == lineage["charge"] and source["multiplicity"] == lineage["multiplicity"] and source["state_family"] == lineage["state_family"] and source["wavefunction_reference"] == lineage["wavefunction_reference"], "input state/reference drift")
    input_record = _exact(source["input"], {"path", "sha256", "route", "atom_elements"}, "input record")
    _sha(input_record["sha256"], "input SHA-256")
    input_file = _safe_path(input_record["path"], "reviewed Gaussian input")
    require(file_sha256(input_file) == input_record["sha256"], "reviewed Gaussian input hash drift")
    require(input_record["route"] == stage["route"], "input route differs from reviewed protocol")
    require(input_record["atom_elements"] == lineage["atom_elements"], "input atom order drift")
    require(source["same_spin_surface"] is True and source["settings_reviewed"] is True, "input must be reviewed on the same spin surface")
    review = _exact(source["review"], {"decision", "reviewer", "confirmed"}, "input review")
    require(review["decision"] == "accepted_for_offline_audit" and review["confirmed"] is True, "input audit source not accepted")
    require(source["calculation_ready"] is False and source["no_submission_authorization"] is True, "input source authority boundary changed")
    document = {"schema": INPUT_AUDIT_SCHEMA, "audit_id": source["audit_id"], "stage": source["stage"], "status": "accepted_offline_input_audit", "workflow": _binding(workflow_file, workflow), "source": _binding(source_file, source), "input": input_record, "state_lineage": lineage, "calculation_ready": False, "no_submission_authorization": True, "authorizations": AUTHORIZATIONS}
    document["payload_sha256"] = payload_sha256(document)
    validate_input_audit(document, check_sources=False)
    return document


def validate_input_audit(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "audit_id", "stage", "status", "workflow", "source", "input", "state_lineage", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "input audit")
    require(document["schema"] == INPUT_AUDIT_SCHEMA and document["stage"] in {"ts_freq", "irc_forward", "irc_reverse"} and document["status"] == "accepted_offline_input_audit", "input audit identity invalid")
    _sha(document["workflow"]["sha256"], "input audit workflow hash"); _sha(document["source"]["sha256"], "input audit source hash"); _sha(document["input"]["sha256"], "audited input hash")
    _authority(document, "input audit"); require(document["payload_sha256"] == payload_sha256(document), "input audit payload hash mismatch")
    if check_sources:
        rebuilt = build_input_audit(document["workflow"]["path"], document["source"]["path"]); require(rebuilt == document, "input audit differs from sources")


def build_ts_acceptance(workflow_path: str | Path, input_audit_path: str | Path, observation_path: str | Path, mode_decision_path: str | Path, acceptance_id: str) -> dict[str, Any]:
    require(ID_RE.fullmatch(acceptance_id) is not None, "invalid TS acceptance_id")
    owner = _load_open_shell_module()
    workflow_file, workflow = load_json(workflow_path, "workflow", canonical=True); validate_workflow(workflow, check_sources=True)
    audit_file, audit = load_json(input_audit_path, "TS input audit", canonical=True); validate_input_audit(audit, check_sources=True)
    observation_file, observation = owner.load_validated_observation(observation_path)
    decision_file, decision = load_json(mode_decision_path, "mode decision")
    require(audit["stage"] == "ts_freq" and audit["workflow"]["payload_sha256"] == workflow["payload_sha256"], "TS input audit does not bind workflow")
    _exact(decision, {"schema", "decision_id", "workflow_payload_sha256", "input_audit_payload_sha256", "observation_payload_sha256", "imaginary_mode_index", "intended_reaction_coordinate_confirmed", "reviewer", "rationale", "decision", "confirmed", "calculation_ready", "no_submission_authorization"}, "mode decision")
    require(decision["schema"] == "auto-g16-main-group-open-shell-ts-mode-decision/1" and decision["decision"] == "accepted" and decision["confirmed"] is True, "normal mode is not accepted")
    require(decision["workflow_payload_sha256"] == workflow["payload_sha256"] and decision["input_audit_payload_sha256"] == audit["payload_sha256"] and decision["observation_payload_sha256"] == observation["payload_sha256"], "mode decision source hash drift")
    negative_indices = [index for index, value in enumerate(observation["facts"]["frequencies"]["values_cm_minus_1"]) if value < 0]
    require(len(negative_indices) == 1 and decision["imaginary_mode_index"] == negative_indices[0] and decision["intended_reaction_coordinate_confirmed"] is True, "intended reaction-coordinate mode must be manually confirmed")
    facts, lineage = observation["facts"], workflow["state_lineage"]
    s2 = facts["spin"]["s2_after_annihilation"]
    checks = {
        "normal_termination": facts["termination"]["normal"], "scf_converged": facts["scf"]["converged"] and facts["scf"]["energy_hartree"] is not None, "stationary_point": facts["optimization"]["stationary_point_found"],
        "exactly_one_imaginary_frequency": facts["frequencies"]["performed"] and facts["frequencies"]["imaginary_count"] == 1,
        "frequencies_complete": facts["frequencies"]["count"] == lineage["expected_frequency_count"],
        "mode_review_confirmed": decision["intended_reaction_coordinate_confirmed"] is True,
        "state_identity": facts["state"] == {"charge": lineage["charge"], "multiplicity": lineage["multiplicity"]},
        "reference_continuity": facts["scf"]["reference_family"] == lineage["wavefunction_reference"],
        "stability": facts["stability"] == {"performed": True, "status": "stable"},
        "s2_present": facts["spin"]["s2_before_annihilation"] is not None and s2 is not None,
        "s2_within_reviewed_threshold": s2 is not None and abs(float(s2) - float(lineage["target_s2"])) <= float(lineage["max_abs_post_annihilation_s2_deviation"]),
    }
    document = {"schema": TS_ACCEPTANCE_SCHEMA, "acceptance_id": acceptance_id, "status": "accepted" if all(checks.values()) else "blocked", "workflow": _binding(workflow_file, workflow), "input_audit": _binding(audit_file, audit), "observation": _binding(observation_file, observation), "mode_decision": _binding(decision_file, decision), "checks": [{"check": key, "status": "pass" if value else "block"} for key, value in checks.items()], "state_lineage": lineage, "decision": "accepted_same_surface_first_order_saddle" if all(checks.values()) else "blocked", "calculation_ready": False, "no_submission_authorization": True, "authorizations": AUTHORIZATIONS}
    document["payload_sha256"] = payload_sha256(document)
    validate_ts_acceptance(document, check_sources=False)
    return document


def validate_ts_acceptance(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "acceptance_id", "status", "workflow", "input_audit", "observation", "mode_decision", "checks", "state_lineage", "decision", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "TS acceptance")
    require(document["schema"] == TS_ACCEPTANCE_SCHEMA and document["status"] in {"accepted", "blocked"}, "TS acceptance identity invalid")
    passed = all(item == {"check": item.get("check"), "status": "pass"} for item in document["checks"])
    require((document["status"] == "accepted") is passed, "TS acceptance status/check mismatch")
    require(document["decision"] == ("accepted_same_surface_first_order_saddle" if passed else "blocked"), "TS acceptance decision mismatch")
    _authority(document, "TS acceptance"); require(document["payload_sha256"] == payload_sha256(document), "TS acceptance payload hash mismatch")
    if check_sources:
        rebuilt = build_ts_acceptance(document["workflow"]["path"], document["input_audit"]["path"], document["observation"]["path"], document["mode_decision"]["path"], document["acceptance_id"]); require(rebuilt == document, "TS acceptance differs from sources")


def build_irc_plan(workflow_path: str | Path, ts_acceptance_path: str | Path, forward_audit_path: str | Path, reverse_audit_path: str | Path, plan_id: str) -> dict[str, Any]:
    require(ID_RE.fullmatch(plan_id) is not None, "invalid IRC plan_id")
    workflow_file, workflow = load_json(workflow_path, "workflow", canonical=True); validate_workflow(workflow, check_sources=True)
    ts_file, ts = load_json(ts_acceptance_path, "TS acceptance", canonical=True); validate_ts_acceptance(ts, check_sources=True)
    audits = []
    for direction, value in (("irc_forward", forward_audit_path), ("irc_reverse", reverse_audit_path)):
        path, audit = load_json(value, f"{direction} input audit", canonical=True); validate_input_audit(audit, check_sources=True)
        require(audit["stage"] == direction and audit["workflow"]["payload_sha256"] == workflow["payload_sha256"], f"{direction} audit lineage mismatch")
        audits.append((path, audit))
    require(ts["status"] == "accepted" and ts["workflow"]["payload_sha256"] == workflow["payload_sha256"], "accepted TS lineage required")
    document = {"schema": IRC_PLAN_SCHEMA, "plan_id": plan_id, "status": "planned_offline_only", "workflow": _binding(workflow_file, workflow), "ts_acceptance": _binding(ts_file, ts), "direction_input_audits": {"forward": _binding(*audits[0]), "reverse": _binding(*audits[1])}, "state_lineage": workflow["state_lineage"], "required_result_evidence": ["both_directions_complete", "normal_termination", "identified_reactant_and_product", "matching_charge_multiplicity", "matching_state_lineage", "matching_u_or_ro_reference", "stable_wavefunction", "s2_within_reviewed_threshold"], "irc_validated": False, "calculation_ready": False, "no_submission_authorization": True, "authorizations": AUTHORIZATIONS}
    document["payload_sha256"] = payload_sha256(document)
    validate_irc_plan(document, check_sources=False)
    return document


def validate_irc_plan(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "plan_id", "status", "workflow", "ts_acceptance", "direction_input_audits", "state_lineage", "required_result_evidence", "irc_validated", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "IRC plan")
    require(document["schema"] == IRC_PLAN_SCHEMA and document["status"] == "planned_offline_only" and document["irc_validated"] is False, "IRC plan identity invalid")
    require(set(document["direction_input_audits"]) == {"forward", "reverse"}, "IRC plan directions invalid")
    _authority(document, "IRC plan"); require(document["payload_sha256"] == payload_sha256(document), "IRC plan payload hash mismatch")
    if check_sources:
        rebuilt = build_irc_plan(document["workflow"]["path"], document["ts_acceptance"]["path"], document["direction_input_audits"]["forward"]["path"], document["direction_input_audits"]["reverse"]["path"], document["plan_id"]); require(rebuilt == document, "IRC plan differs from sources")


def _validate_endpoint(source: dict[str, Any], direction: str, plan: dict[str, Any]) -> None:
    _exact(source, {"schema", "endpoint_id", "direction", "plan_payload_sha256", "input_audit_payload_sha256", "normal_termination", "path_complete", "endpoint_identity", "structure_sha256", "charge", "multiplicity", "state_family", "wavefunction_reference", "s2_before_annihilation", "s2_after_annihilation", "stability", "state_lineage_payload_sha256", "review", "calculation_ready", "no_submission_authorization"}, f"{direction} endpoint")
    require(source["schema"] == "auto-g16-main-group-open-shell-irc-endpoint-source/1" and source["direction"] == direction, "endpoint direction/schema mismatch")
    require(source["plan_payload_sha256"] == plan["payload_sha256"], "endpoint plan hash drift")
    audit = plan["direction_input_audits"][direction]
    require(source["input_audit_payload_sha256"] == audit["payload_sha256"], "endpoint input-audit hash drift")
    lineage = plan["state_lineage"]
    require(source["charge"] == lineage["charge"] and source["multiplicity"] == lineage["multiplicity"] and source["state_family"] == lineage["state_family"], "endpoint state drift")
    require(source["wavefunction_reference"] == lineage["wavefunction_reference"], "endpoint U/RO reference drift")
    require(source["state_lineage_payload_sha256"] == plan["workflow"]["payload_sha256"], "endpoint state lineage hash drift")
    _sha(source["structure_sha256"], "endpoint structure hash")
    _number(source["s2_before_annihilation"], "endpoint S2 before", minimum=0); _number(source["s2_after_annihilation"], "endpoint S2 after", minimum=0)
    require(source["stability"] == "stable", "endpoint stability missing or failed")
    require(source["normal_termination"] is True and source["path_complete"] is True, "endpoint direction is incomplete")
    require(source["endpoint_identity"] in {"reactant", "product"}, "endpoint identity must be reviewed")
    review = _exact(source["review"], {"decision", "reviewer", "rationale", "confirmed"}, "endpoint review")
    require(review["decision"] == "accepted_endpoint_identity" and review["confirmed"] is True, "endpoint identity is not accepted")
    require(source["calculation_ready"] is False and source["no_submission_authorization"] is True, "endpoint authority boundary changed")


def build_irc_acceptance(plan_path: str | Path, forward_path: str | Path, reverse_path: str | Path, acceptance_id: str) -> dict[str, Any]:
    require(ID_RE.fullmatch(acceptance_id) is not None, "invalid IRC acceptance_id")
    plan_file, plan = load_json(plan_path, "IRC plan", canonical=True); validate_irc_plan(plan, check_sources=True)
    sources = {}
    for direction, value in (("forward", forward_path), ("reverse", reverse_path)):
        path, source = load_json(value, f"{direction} endpoint source"); _validate_endpoint(source, direction, plan); sources[direction] = (path, source)
    forward, reverse = sources["forward"][1], sources["reverse"][1]
    lineage = plan["state_lineage"]
    threshold, target = lineage["max_abs_post_annihilation_s2_deviation"], lineage["target_s2"]
    checks = {
        "both_directions_complete": forward["path_complete"] and reverse["path_complete"],
        "normal_termination_both": forward["normal_termination"] and reverse["normal_termination"],
        "reactant_and_product_identified": {forward["endpoint_identity"], reverse["endpoint_identity"]} == {"reactant", "product"},
        "charge_multiplicity_continuity": all(item["charge"] == lineage["charge"] and item["multiplicity"] == lineage["multiplicity"] for item in (forward, reverse)),
        "state_lineage_continuity": all(item["state_lineage_payload_sha256"] == plan["workflow"]["payload_sha256"] for item in (forward, reverse)),
        "reference_continuity": all(item["wavefunction_reference"] == lineage["wavefunction_reference"] for item in (forward, reverse)),
        "stability_both": all(item["stability"] == "stable" for item in (forward, reverse)),
        "s2_within_reviewed_threshold_both": all(abs(float(item["s2_after_annihilation"]) - float(target)) <= float(threshold) for item in (forward, reverse)),
    }
    accepted = all(checks.values())
    document = {"schema": IRC_ACCEPTANCE_SCHEMA, "acceptance_id": acceptance_id, "status": "irc_validated" if accepted else "blocked", "plan": _binding(plan_file, plan), "endpoints": {direction: _binding(*value) for direction, value in sources.items()}, "checks": [{"check": key, "status": "pass" if value else "block"} for key, value in checks.items()], "state_lineage": lineage, "irc_validated": accepted, "limitations": ["Offline evidence acceptance only; endpoint minimum and thermochemistry claims are outside this contract."], "calculation_ready": False, "no_submission_authorization": True, "authorizations": AUTHORIZATIONS}
    document["payload_sha256"] = payload_sha256(document)
    validate_irc_acceptance(document, check_sources=False)
    return document


def validate_irc_acceptance(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "acceptance_id", "status", "plan", "endpoints", "checks", "state_lineage", "irc_validated", "limitations", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "IRC acceptance")
    require(document["schema"] == IRC_ACCEPTANCE_SCHEMA and set(document["endpoints"]) == {"forward", "reverse"}, "IRC acceptance identity invalid")
    passed = all(item.get("status") == "pass" for item in document["checks"])
    require(document["irc_validated"] is passed and document["status"] == ("irc_validated" if passed else "blocked"), "IRC acceptance status/check mismatch")
    _authority(document, "IRC acceptance"); require(document["payload_sha256"] == payload_sha256(document), "IRC acceptance payload hash mismatch")
    if check_sources:
        rebuilt = build_irc_acceptance(document["plan"]["path"], document["endpoints"]["forward"]["path"], document["endpoints"]["reverse"]["path"], document["acceptance_id"]); require(rebuilt == document, "IRC acceptance differs from sources")


def validate_artifact(path: str | Path) -> dict[str, Any]:
    _, document = load_json(path, "open-shell TS/IRC artifact", canonical=True)
    validators = {WORKFLOW_SCHEMA: validate_workflow, INPUT_AUDIT_SCHEMA: validate_input_audit, TS_ACCEPTANCE_SCHEMA: validate_ts_acceptance, IRC_PLAN_SCHEMA: validate_irc_plan, IRC_ACCEPTANCE_SCHEMA: validate_irc_acceptance}
    require(document.get("schema") in validators, "unknown open-shell TS/IRC artifact schema")
    validators[document["schema"]](document, check_sources=True)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    workflow = sub.add_parser("build-workflow"); workflow.add_argument("--state-review", required=True); workflow.add_argument("--candidate", required=True); workflow.add_argument("--protocol", required=True); workflow.add_argument("--workflow-id", required=True); workflow.add_argument("--output", required=True)
    audit = sub.add_parser("audit-input"); audit.add_argument("--workflow", required=True); audit.add_argument("--source", required=True); audit.add_argument("--output", required=True)
    ts = sub.add_parser("accept-ts"); ts.add_argument("--workflow", required=True); ts.add_argument("--input-audit", required=True); ts.add_argument("--observation", required=True); ts.add_argument("--mode-decision", required=True); ts.add_argument("--acceptance-id", required=True); ts.add_argument("--output", required=True)
    plan = sub.add_parser("plan-irc"); plan.add_argument("--workflow", required=True); plan.add_argument("--ts-acceptance", required=True); plan.add_argument("--forward-audit", required=True); plan.add_argument("--reverse-audit", required=True); plan.add_argument("--plan-id", required=True); plan.add_argument("--output", required=True)
    accept = sub.add_parser("accept-irc"); accept.add_argument("--plan", required=True); accept.add_argument("--forward-endpoint", required=True); accept.add_argument("--reverse-endpoint", required=True); accept.add_argument("--acceptance-id", required=True); accept.add_argument("--output", required=True)
    validate = sub.add_parser("validate"); validate.add_argument("artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build-workflow": document = build_workflow(args.state_review, args.candidate, args.protocol, args.workflow_id)
        elif args.command == "audit-input": document = build_input_audit(args.workflow, args.source)
        elif args.command == "accept-ts": document = build_ts_acceptance(args.workflow, args.input_audit, args.observation, args.mode_decision, args.acceptance_id)
        elif args.command == "plan-irc": document = build_irc_plan(args.workflow, args.ts_acceptance, args.forward_audit, args.reverse_audit, args.plan_id)
        elif args.command == "accept-irc": document = build_irc_acceptance(args.plan, args.forward_endpoint, args.reverse_endpoint, args.acceptance_id)
        else:
            document = validate_artifact(args.artifact)
            print(json.dumps({"valid": True, "schema": document["schema"], "live_actions": False})); return 0
        write_new_json(args.output, document)
        print(json.dumps({"valid": True, "schema": document["schema"], "status": document.get("status"), "live_actions": False}))
        return 0
    except (ContractError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
