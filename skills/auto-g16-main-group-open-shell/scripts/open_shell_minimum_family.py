#!/usr/bin/env python3
"""Offline owner for a two-stage open-shell minimum Opt/Freq + Stable=Opt family."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
STATE_PATH = SCRIPT_DIR / "open_shell_state.py"


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load owner dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = _module("open_shell_minimum_family_state", STATE_PATH)

WORKFLOW = "main_group_open_shell_minimum_two_stage_v1"
HANDOFF_SCHEMA = "auto-g16-main-group-open-shell-minimum-family-handoff/1"
PROSPECTIVE_HANDOFF_SCHEMA = "auto-g16-main-group-open-shell-minimum-family-handoff/2"
HANDOFF_SCHEMAS = {HANDOFF_SCHEMA, PROSPECTIVE_HANDOFF_SCHEMA}
CHECKPOINT_SCHEMA = "auto-g16-main-group-open-shell-minimum-checkpoint-binding/1"
MANIFEST_SCHEMA = "auto-g16-main-group-open-shell-minimum-stability-input-manifest/1"
RECEIPT_SCHEMA = "gaussian-input-approval-receipt/3"
ACCEPTANCE_SCHEMA = "auto-g16-main-group-open-shell-minimum-family-acceptance/1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
CHK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.chk$")
RESOURCE_TIERS = {"simple": (12, 8), "general": (50, 22), "complex": (120, 44)}
AUTHORITY = {"calculation_ready": False, "no_submission_authorization": True}
NO_ACTIONS = {"submit": False, "retry": False, "cancel": False, "cleanup": False, "delete_server_data": False}


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == fields, f"{label} fields mismatch; missing={sorted(fields-set(value))} unknown={sorted(set(value)-fields)}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def payload_sha256(value: dict[str, Any]) -> str:
    body = copy.deepcopy(value)
    body.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _load(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular non-symlink file")
    try:
        def reject_constant(value: str) -> None:
            raise ValueError(f"non-standard JSON number is forbidden: {value}")
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                require(key not in result, f"duplicate JSON key is forbidden: {key}")
                result[key] = value
            return result
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant, object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label}: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def _binding(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "schema": document["schema"], "payload_sha256": document["payload_sha256"]}


def _validate_binding(value: Any, label: str, schema: str | None = None) -> None:
    item = _exact(value, {"path", "sha256", "schema", "payload_sha256"}, label)
    require(isinstance(item["path"], str) and item["path"], f"{label}.path invalid")
    _sha(item["sha256"], f"{label}.sha256")
    _sha(item["payload_sha256"], f"{label}.payload_sha256")
    if schema is not None:
        require(item["schema"] == schema, f"{label} schema mismatch")


def _validate_family_binding(value: Any, label: str) -> None:
    _validate_binding(value, label)
    require(value["schema"] in HANDOFF_SCHEMAS, f"{label} schema mismatch")


def _route_tokens(route: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    for char in " ".join(route.lower().split()):
        if char.isspace() and depth == 0:
            if current:
                tokens.append("".join(current)); current = []
            continue
        current.append(char)
        depth += char == "("
        depth -= char == ")" and depth > 0
    if current:
        tokens.append("".join(current))
    return tokens


def _has(route: str, keyword: str) -> bool:
    return any(re.match(rf"^{re.escape(keyword)}(?=$|[=(])", token) for token in _route_tokens(route))


def _method_basis(route: str) -> tuple[str, str, str]:
    for token in _route_tokens(route):
        if "/" in token and not token.startswith(("scf", "scrf", "iop")):
            method, basis = token.split("/", 1)
            reference = "RO" if method.startswith("ro") else "U" if method.startswith("u") else ""
            require(reference in {"U", "RO"}, "route must use an explicit U or RO reference")
            return method, basis, reference
    raise ContractError("route must contain one explicit method/basis token")


def _validate_routes(opt_route: str, stability_route: str) -> tuple[str, str, str]:
    require(opt_route.lstrip().startswith("#") and stability_route.lstrip().startswith("#"), "both stages require route cards")
    require(_has(opt_route, "opt") and _has(opt_route, "freq"), "opt_freq stage requires Opt and Freq")
    require(not _has(opt_route, "stable"), "opt_freq stage must not contain Stable or Stable=Opt")
    require(_has(stability_route, "stable"), "stability stage requires Stable=Opt")
    require(any(token in {"stable=opt", "stable=(opt)"} for token in _route_tokens(stability_route)), "stability stage requires exact Stable=Opt")
    require(_has(stability_route, "geom") and any(token == "geom=allcheck" for token in _route_tokens(stability_route)), "stability stage requires Geom=AllCheck")
    require(_has(stability_route, "guess") and any(token == "guess=read" for token in _route_tokens(stability_route)), "stability stage requires Guess=Read")
    require(not _has(stability_route, "opt") and not _has(stability_route, "freq"), "stability stage must not contain Opt or Freq")
    opt_method, opt_basis, opt_ref = _method_basis(opt_route)
    stable_method, stable_basis, stable_ref = _method_basis(stability_route)
    require((opt_method, opt_basis, opt_ref) == (stable_method, stable_basis, stable_ref), "stage method/basis/reference continuity mismatch")
    return opt_method, opt_basis, opt_ref


def validate_handoff(document: dict[str, Any]) -> None:
    common_fields = {"schema", "family_id", "workflow", "status", "state", "structure", "method_basis", "resources", "selection_binding", "stages", "family_requirements", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}
    require(document.get("schema") in HANDOFF_SCHEMAS, "family handoff schema mismatch")
    lineage_field = "failure_lineage" if document["schema"] == HANDOFF_SCHEMA else "prospective_lineage"
    _exact(document, common_fields | {lineage_field}, "family handoff")
    require(document["workflow"] == WORKFLOW and document["status"] == "offline_candidates_ready_for_independent_approval", "family handoff identity/status mismatch")
    _id(document["family_id"], "family_id")
    state_value = _exact(document["state"], {"charge", "multiplicity", "state_family", "reference_family", "target_s2", "max_abs_s2_deviation"}, "family state")
    require(isinstance(state_value["charge"], int) and state_value["multiplicity"] in {2, 3}, "only reviewed doublet/high-spin triplet minima are supported")
    require(state_value["state_family"] in {"doublet_ground_state", "high_spin_triplet_ground_state", "triplet_carbene"} and state_value["reference_family"] in {"U", "RO"}, "unsupported open-shell state/reference")
    require(isinstance(state_value["target_s2"], (int, float)) and isinstance(state_value["max_abs_s2_deviation"], (int, float)) and state_value["max_abs_s2_deviation"] >= 0, "invalid S2 policy")
    structure = _exact(document["structure"], {"atoms", "structure_sha256"}, "family structure")
    require(isinstance(structure["atoms"], list) and bool(structure["atoms"]), "family atoms missing")
    for index, atom in enumerate(structure["atoms"], 1):
        _exact(atom, {"index", "element", "x_angstrom", "y_angstrom", "z_angstrom"}, f"atom[{index}]")
        require(atom["index"] == index and atom["element"] in state.MAIN_GROUP_SYMBOLS, "invalid/non-main-group atom inventory")
        for key in ("x_angstrom", "y_angstrom", "z_angstrom"):
            require(isinstance(atom[key], (int, float)) and not isinstance(atom[key], bool), f"atom[{index}].{key} invalid")
    _sha(structure["structure_sha256"], "structure hash")
    expected_structure_sha = hashlib.sha256(canonical_bytes({"atoms": structure["atoms"], "charge": state_value["charge"], "multiplicity": state_value["multiplicity"]})).hexdigest()
    require(structure["structure_sha256"] == expected_structure_sha, "family structure hash differs from exact atom/state payload")
    resources = _exact(document["resources"], {"resource_tier", "mem_gb", "cores"}, "family resources")
    require(resources["resource_tier"] in RESOURCE_TIERS and isinstance(resources["mem_gb"], int) and isinstance(resources["cores"], int), "invalid resource tier")
    require((resources["mem_gb"], resources["cores"]) == RESOURCE_TIERS[resources["resource_tier"]], "resource tier/memory/core mapping changed")
    selection = _exact(document["selection_binding"], {"selection_payload_sha256", "selected_option_payload_sha256"}, "selection binding")
    _sha(selection["selection_payload_sha256"], "selection payload hash"); _sha(selection["selected_option_payload_sha256"], "selected option payload hash")
    if document["schema"] == HANDOFF_SCHEMA:
        failure = _exact(document["failure_lineage"], {"superseded_input_sha256", "classification", "resubmit_same_input"}, "failure lineage")
        _sha(failure["superseded_input_sha256"], "superseded input hash")
        require(failure["classification"] == "gaussian_link1_combined_opt_freq_stable_parse_failure" and failure["resubmit_same_input"] is False, "failure lineage must block same-input retry")
    else:
        prospective = _exact(document["prospective_lineage"], {"classification", "prior_failed_input_sha256", "combined_route_forbidden"}, "prospective lineage")
        require(prospective == {"classification": "prospective_two_stage_minimum", "prior_failed_input_sha256": None, "combined_route_forbidden": True}, "prospective lineage must not claim a prior failed input")
    stages = _exact(document["stages"], {"opt_freq", "stability"}, "family stages")
    opt = _exact(stages["opt_freq"], {"stage_id", "route", "checkpoint", "input_text", "input_sha256", "expected_frequency_count"}, "opt_freq stage")
    stable = _exact(stages["stability"], {"stage_id", "route", "oldcheckpoint", "checkpoint", "input_text", "input_sha256", "requires_checkpoint_binding"}, "stability stage")
    require(opt["stage_id"] == "opt_freq" and stable["stage_id"] == "stability", "stage identities changed")
    require(CHK_RE.fullmatch(opt["checkpoint"]) is not None and CHK_RE.fullmatch(stable["oldcheckpoint"]) is not None and CHK_RE.fullmatch(stable["checkpoint"]) is not None, "invalid checkpoint basename")
    require(opt["checkpoint"] == stable["oldcheckpoint"] and stable["checkpoint"] != stable["oldcheckpoint"], "checkpoint generation binding mismatch")
    require(stable["requires_checkpoint_binding"] is True and isinstance(opt["expected_frequency_count"], int) and opt["expected_frequency_count"] > 0, "stage evidence requirements invalid")
    method, basis, reference = _validate_routes(opt["route"], stable["route"])
    require(document["method_basis"] == {"method": method, "basis": basis}, "declared method/basis differs from both routes")
    require(reference == state_value["reference_family"], "route reference differs from reviewed state")
    for stage_value in (opt, stable):
        require(stage_value["input_sha256"] == hashlib.sha256(stage_value["input_text"].encode()).hexdigest(), "stage exact input SHA mismatch")
    requirements = _exact(document["family_requirements"], {"independent_stage_receipts", "independent_live_approvals", "link1_forbidden", "mixed_checkpoint_generation_forbidden"}, "family requirements")
    require(all(requirements.values()), "all two-stage family requirements must remain enabled")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True and document["authorizations"] == NO_ACTIONS, "family handoff authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "family handoff payload hash mismatch")


def validate_checkpoint_binding(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "binding_id", "family", "stage", "result", "checkpoint", "state_method_continuity", "opt_freq_evidence", "status", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "checkpoint binding")
    require(document["schema"] == CHECKPOINT_SCHEMA and document["stage"] == "opt_freq", "checkpoint binding identity mismatch")
    _id(document["binding_id"], "binding_id"); _validate_family_binding(document["family"], "checkpoint family")
    result = _exact(document["result"], {"path", "sha256", "input_sha256"}, "checkpoint result")
    require(isinstance(result["path"], str) and result["path"], "result path missing"); _sha(result["sha256"], "result hash"); _sha(result["input_sha256"], "result input hash")
    checkpoint = _exact(document["checkpoint"], {"file", "sha256"}, "checkpoint")
    require(CHK_RE.fullmatch(checkpoint["file"]) is not None, "invalid checkpoint file"); _sha(checkpoint["sha256"], "checkpoint hash")
    continuity = _exact(document["state_method_continuity"], {"charge", "multiplicity", "reference_family", "method", "basis"}, "state/method continuity")
    require(isinstance(continuity["charge"], int) and continuity["multiplicity"] in {2, 3} and continuity["reference_family"] in {"U", "RO"}, "invalid checkpoint state continuity")
    evidence = _exact(document["opt_freq_evidence"], {"normal_termination", "stationary_point", "scf_converged", "expected_frequency_count", "actual_frequency_count", "imaginary_frequency_count", "s2_within_policy"}, "Opt/Freq evidence")
    require(all(evidence[key] is True for key in ("normal_termination", "stationary_point", "scf_converged", "s2_within_policy")) and evidence["actual_frequency_count"] == evidence["expected_frequency_count"] and evidence["imaginary_frequency_count"] == 0, "checkpoint cannot be promoted without accepted Opt/Freq evidence")
    require(document["status"] == "accepted_final_optimized_checkpoint" and document["calculation_ready"] is False and document["no_submission_authorization"] is True and document["authorizations"] == NO_ACTIONS, "checkpoint binding status/authority changed")
    require(document["payload_sha256"] == payload_sha256(document), "checkpoint binding payload hash mismatch")
    family_path = Path(document["family"]["path"])
    result_path = Path(document["result"]["path"])
    checkpoint_path = result_path.parent / document["checkpoint"]["file"]
    require(family_path.is_file() and not family_path.is_symlink() and file_sha256(family_path) == document["family"]["sha256"], "checkpoint family source changed")
    require(result_path.is_file() and not result_path.is_symlink() and file_sha256(result_path) == document["result"]["sha256"], "checkpoint result source changed")
    require(checkpoint_path.is_file() and not checkpoint_path.is_symlink() and file_sha256(checkpoint_path) == document["checkpoint"]["sha256"], "bound final checkpoint bytes changed")
    family = _load(family_path, "checkpoint family source"); validate_handoff(family)
    require(document["family"] == _binding(family_path, family), "checkpoint family binding differs from source")
    require(document["result"]["input_sha256"] == family["stages"]["opt_freq"]["input_sha256"], "checkpoint result input lineage differs")
    require(document["checkpoint"]["file"] == family["stages"]["opt_freq"]["checkpoint"], "checkpoint basename differs from Opt/Freq family stage")
    require(document["state_method_continuity"] == {"charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"], "reference_family": family["state"]["reference_family"], **family["method_basis"]}, "checkpoint state/method lineage differs")
    facts = state.build_observation(result_path, "checkpoint_replay")["facts"]
    after = facts["spin"]["s2_after_annihilation"]
    expected_count = family["stages"]["opt_freq"]["expected_frequency_count"]
    replayed_evidence = {
        "normal_termination": facts["termination"]["normal"],
        "stationary_point": facts["optimization"]["stationary_point_found"],
        "scf_converged": facts["scf"]["converged"] and facts["state"] == {"charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"]} and facts["scf"]["reference_family"] == family["state"]["reference_family"],
        "expected_frequency_count": expected_count,
        "actual_frequency_count": facts["frequencies"]["count"],
        "imaginary_frequency_count": facts["frequencies"]["imaginary_count"],
        "s2_within_policy": after is not None and abs(after - family["state"]["target_s2"]) <= family["state"]["max_abs_s2_deviation"],
    }
    require(document["opt_freq_evidence"] == replayed_evidence, "checkpoint Opt/Freq evidence differs from deterministic owner replay")


def validate_stability_manifest(document: dict[str, Any], *, input_path: Path | None = None) -> None:
    _exact(document, {"schema", "family", "checkpoint_binding", "stage", "geometry_source", "no_explicit_molecule_specification", "input_sha256", "checkpoint_file", "checkpoint_sha256", "charge", "multiplicity", "atom_count", "atom_order", "method", "basis", "reference_family", "warnings", "candidate_only", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "stability manifest")
    require(document["schema"] == MANIFEST_SCHEMA and document["stage"] == "stability", "stability manifest identity mismatch")
    _validate_family_binding(document["family"], "manifest family"); _validate_binding(document["checkpoint_binding"], "manifest checkpoint binding", CHECKPOINT_SCHEMA)
    require(document["geometry_source"] == "geom_allcheck_from_reviewed_checkpoint" and document["no_explicit_molecule_specification"] is True, "stability manifest geometry source changed")
    _sha(document["input_sha256"], "manifest input hash"); _sha(document["checkpoint_sha256"], "manifest checkpoint hash")
    require(CHK_RE.fullmatch(document["checkpoint_file"]) is not None and document["multiplicity"] in {2, 3} and document["reference_family"] in {"U", "RO"}, "manifest checkpoint/state invalid")
    require(isinstance(document["atom_order"], list) and len(document["atom_order"]) == document["atom_count"] > 0, "manifest atom order invalid")
    require(document["warnings"] == [] and document["candidate_only"] is False and document["calculation_ready"] is False and document["no_submission_authorization"] is True, "stability manifest authority/warnings changed")
    require(document["payload_sha256"] == payload_sha256(document), "stability manifest payload hash mismatch")
    if input_path is not None:
        require(file_sha256(input_path) == document["input_sha256"], "stability manifest input bytes mismatch")


def validate_stage_receipt(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "receipt_id", "work_kind", "family", "stage", "input", "checkpoint_binding", "stability_manifest", "owner_binding", "decision", "single_exact_input_only", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "family stage receipt")
    require(document["schema"] == RECEIPT_SCHEMA, "family receipt schema mismatch"); _id(document["receipt_id"], "receipt_id")
    require(document["work_kind"] == "minimum", "family receipt work_kind changed")
    _validate_family_binding(document["family"], "receipt family")
    require(document["stage"] in {"opt_freq", "stability"}, "unknown family stage")
    input_value = _exact(document["input"], {"path", "sha256", "size_bytes"}, "receipt input")
    require(isinstance(input_value["path"], str) and input_value["path"] and isinstance(input_value["size_bytes"], int) and input_value["size_bytes"] > 0, "receipt input invalid"); _sha(input_value["sha256"], "receipt input hash")
    if document["stage"] == "opt_freq":
        require(document["checkpoint_binding"] is None and document["stability_manifest"] is None, "Opt/Freq receipt must not claim a future checkpoint")
    else:
        _validate_binding(document["checkpoint_binding"], "receipt checkpoint binding", CHECKPOINT_SCHEMA); _validate_binding(document["stability_manifest"], "receipt stability manifest", MANIFEST_SCHEMA)
    owner = _exact(document["owner_binding"], {"owner", "workflow", "family_payload_sha256", "stage", "input_sha256", "route", "charge", "multiplicity", "reference_family", "method", "basis", "resources", "checkpoint_sha256", "owner_replay_passed"}, "receipt owner binding")
    require(owner["owner"] == "auto-g16-main-group-open-shell" and owner["workflow"] == WORKFLOW and owner["stage"] == document["stage"] and owner["input_sha256"] == input_value["sha256"] and owner["owner_replay_passed"] is True, "receipt owner binding mismatch")
    _sha(owner["family_payload_sha256"], "family payload hash")
    if document["stage"] == "opt_freq": require(owner["checkpoint_sha256"] is None, "Opt/Freq receipt cannot bind an output checkpoint")
    else: _sha(owner["checkpoint_sha256"], "stability source checkpoint hash")
    require(document["decision"] == {"status": "approved_exact_family_stage", "explicit_confirmation": True} and document["single_exact_input_only"] is True, "family receipt decision changed")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True and document["authorizations"] == NO_ACTIONS, "family receipt authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "family receipt payload hash mismatch")


def validate_stage_receipt_file(receipt_path: Path, input_path: Path, report: dict[str, Any], work_kind: str, *, _document: dict[str, Any] | None = None) -> dict[str, Any]:
    receipt_path = receipt_path.resolve(); document = copy.deepcopy(_document) if _document is not None else _load(receipt_path, "family stage receipt"); validate_stage_receipt(document)
    require(work_kind == "minimum", "two-stage family is restricted to minimum")
    family_path = Path(document["family"]["path"]); family = _load(family_path, "family handoff"); validate_handoff(family)
    require(file_sha256(family_path) == document["family"]["sha256"] and family["payload_sha256"] == document["family"]["payload_sha256"], "family receipt binding changed")
    stage = family["stages"][document["stage"]]
    require(file_sha256(input_path) == document["input"]["sha256"] == stage["input_sha256"] and input_path.stat().st_size == document["input"]["size_bytes"], "family receipt exact input bytes differ")
    require(report["route"] == stage["route"] and report["charge"] == family["state"]["charge"] and report["multiplicity"] == family["state"]["multiplicity"], "family receipt current route/state differs")
    owner = document["owner_binding"]
    require(owner["route"] == stage["route"] and owner["family_payload_sha256"] == family["payload_sha256"] and owner["resources"] == family["resources"], "family owner reconstruction differs")
    require(owner["method"] == family["method_basis"]["method"] and owner["basis"] == family["method_basis"]["basis"] and owner["reference_family"] == family["state"]["reference_family"], "family owner method/reference differs")
    require(report["nprocshared"] == family["resources"]["cores"], "family receipt core count differs")
    if document["stage"] == "stability":
        binding_path = Path(document["checkpoint_binding"]["path"]); checkpoint_binding = _load(binding_path, "checkpoint binding"); validate_checkpoint_binding(checkpoint_binding)
        manifest_path = Path(document["stability_manifest"]["path"]); manifest = _load(manifest_path, "stability manifest"); validate_stability_manifest(manifest, input_path=input_path)
        require(file_sha256(binding_path) == document["checkpoint_binding"]["sha256"] and file_sha256(manifest_path) == document["stability_manifest"]["sha256"], "family stage source file changed")
        require(manifest["family"] == document["family"] and manifest["checkpoint_binding"] == document["checkpoint_binding"], "stability manifest belongs to a different family/checkpoint binding")
        require(manifest["charge"] == family["state"]["charge"] and manifest["multiplicity"] == family["state"]["multiplicity"] and manifest["reference_family"] == family["state"]["reference_family"], "stability manifest state/reference differs")
        require({"method": manifest["method"], "basis": manifest["basis"]} == family["method_basis"], "stability manifest method/basis differs")
        require(report["oldcheckpoint_sha256"] == checkpoint_binding["checkpoint"]["sha256"] == manifest["checkpoint_sha256"] == owner["checkpoint_sha256"], "stability receipt final checkpoint hash differs")
        require(report["oldcheckpoint"] == checkpoint_binding["checkpoint"]["file"] == manifest["checkpoint_file"], "stability receipt checkpoint filename differs")
    return document


def build_checkpoint_binding(handoff_path: Path, result_path: Path, checkpoint_path: Path, binding_id: str) -> dict[str, Any]:
    family = _load(handoff_path, "family handoff"); validate_handoff(family); _id(binding_id, "binding_id")
    require(result_path.is_file() and not result_path.is_symlink(), "Opt/Freq result must be a regular file")
    require(checkpoint_path.is_file() and not checkpoint_path.is_symlink() and checkpoint_path.name == family["stages"]["opt_freq"]["checkpoint"], "final checkpoint file differs from family")
    facts = state.build_observation(result_path, f"{binding_id}_observation")["facts"]
    spin_after = facts["spin"]["s2_after_annihilation"]
    expected = family["stages"]["opt_freq"]["expected_frequency_count"]
    state_ok = facts["state"] == {"charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"]}
    ref_ok = facts["scf"]["reference_family"] == family["state"]["reference_family"]
    s2_ok = spin_after is not None and abs(spin_after - family["state"]["target_s2"]) <= family["state"]["max_abs_s2_deviation"]
    evidence = {"normal_termination": facts["termination"]["normal"], "stationary_point": facts["optimization"]["stationary_point_found"], "scf_converged": facts["scf"]["converged"] and state_ok and ref_ok, "expected_frequency_count": expected, "actual_frequency_count": facts["frequencies"]["count"], "imaginary_frequency_count": facts["frequencies"]["imaginary_count"], "s2_within_policy": s2_ok}
    require(all(evidence[key] is True for key in ("normal_termination", "stationary_point", "scf_converged", "s2_within_policy")) and evidence["actual_frequency_count"] == expected and evidence["imaginary_frequency_count"] == 0, "Opt/Freq result cannot promote a checkpoint")
    document = {"schema": CHECKPOINT_SCHEMA, "binding_id": binding_id, "family": _binding(handoff_path, family), "stage": "opt_freq", "result": {"path": str(result_path.resolve()), "sha256": file_sha256(result_path), "input_sha256": family["stages"]["opt_freq"]["input_sha256"]}, "checkpoint": {"file": checkpoint_path.name, "sha256": file_sha256(checkpoint_path)}, "state_method_continuity": {"charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"], "reference_family": family["state"]["reference_family"], **family["method_basis"]}, "opt_freq_evidence": evidence, "status": "accepted_final_optimized_checkpoint", **AUTHORITY, "authorizations": copy.deepcopy(NO_ACTIONS), "payload_sha256": None}
    document["payload_sha256"] = payload_sha256(document); validate_checkpoint_binding(document); return document


def build_stability_manifest(handoff_path: Path, binding_path: Path, stability_input: Path) -> dict[str, Any]:
    family = _load(handoff_path, "family handoff"); validate_handoff(family)
    checkpoint_binding = _load(binding_path, "checkpoint binding"); validate_checkpoint_binding(checkpoint_binding)
    require(checkpoint_binding["family"] == _binding(handoff_path, family), "checkpoint belongs to a different family")
    require(file_sha256(stability_input) == family["stages"]["stability"]["input_sha256"], "stability candidate input differs from family")
    atoms = family["structure"]["atoms"]
    atom_order = [{"index": atom["index"], "element": atom["element"], "atomic_number": state.ATOMIC_NUMBERS[atom["element"]]} for atom in atoms]
    document = {"schema": MANIFEST_SCHEMA, "family": _binding(handoff_path, family), "checkpoint_binding": _binding(binding_path, checkpoint_binding), "stage": "stability", "geometry_source": "geom_allcheck_from_reviewed_checkpoint", "no_explicit_molecule_specification": True, "input_sha256": file_sha256(stability_input), "checkpoint_file": checkpoint_binding["checkpoint"]["file"], "checkpoint_sha256": checkpoint_binding["checkpoint"]["sha256"], "charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"], "atom_count": len(atoms), "atom_order": atom_order, **family["method_basis"], "reference_family": family["state"]["reference_family"], "warnings": [], "candidate_only": False, **AUTHORITY, "payload_sha256": None}
    document["payload_sha256"] = payload_sha256(document); validate_stability_manifest(document, input_path=stability_input); return document


def build_stage_receipt(handoff_path: Path, input_path: Path, receipt_id: str, stage_id: str, checkpoint_binding_path: Path | None = None, manifest_path: Path | None = None) -> dict[str, Any]:
    family = _load(handoff_path, "family handoff"); validate_handoff(family); _id(receipt_id, "receipt_id")
    require(stage_id in {"opt_freq", "stability"}, "invalid family stage")
    stage_value = family["stages"][stage_id]
    require(file_sha256(input_path) == stage_value["input_sha256"], "receipt input differs from family stage")
    checkpoint_binding = None; manifest = None; checkpoint_hash = None
    if stage_id == "stability":
        require(checkpoint_binding_path is not None and manifest_path is not None, "stability receipt requires checkpoint binding and manifest")
        checkpoint_doc = _load(checkpoint_binding_path, "checkpoint binding"); validate_checkpoint_binding(checkpoint_doc)
        manifest_doc = _load(manifest_path, "stability manifest"); validate_stability_manifest(manifest_doc, input_path=input_path)
        checkpoint_binding = _binding(checkpoint_binding_path, checkpoint_doc); manifest = _binding(manifest_path, manifest_doc); checkpoint_hash = checkpoint_doc["checkpoint"]["sha256"]
    else:
        require(checkpoint_binding_path is None and manifest_path is None, "Opt/Freq receipt cannot pre-bind checkpoint evidence")
    owner = {"owner": "auto-g16-main-group-open-shell", "workflow": WORKFLOW, "family_payload_sha256": family["payload_sha256"], "stage": stage_id, "input_sha256": stage_value["input_sha256"], "route": stage_value["route"], "charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"], "reference_family": family["state"]["reference_family"], **family["method_basis"], "resources": family["resources"], "checkpoint_sha256": checkpoint_hash, "owner_replay_passed": True}
    document = {"schema": RECEIPT_SCHEMA, "receipt_id": receipt_id, "work_kind": "minimum", "family": _binding(handoff_path, family), "stage": stage_id, "input": {"path": str(input_path.resolve()), "sha256": file_sha256(input_path), "size_bytes": input_path.stat().st_size}, "checkpoint_binding": checkpoint_binding, "stability_manifest": manifest, "owner_binding": owner, "decision": {"status": "approved_exact_family_stage", "explicit_confirmation": True}, "single_exact_input_only": True, **AUTHORITY, "authorizations": copy.deepcopy(NO_ACTIONS), "payload_sha256": None}
    document["payload_sha256"] = payload_sha256(document); validate_stage_receipt(document); return document


def _acceptance_checks(family: dict[str, Any], checkpoint: dict[str, Any], opt_result: Path, stability_result: Path) -> dict[str, bool]:
    opt = state.build_observation(opt_result, "family_acceptance_opt")["facts"]
    stable = state.build_observation(stability_result, "family_acceptance_stable")["facts"]
    target, tolerance = family["state"]["target_s2"], family["state"]["max_abs_s2_deviation"]
    def continuity(facts: dict[str, Any]) -> bool:
        after = facts["spin"]["s2_after_annihilation"]
        return facts["state"] == {"charge": family["state"]["charge"], "multiplicity": family["state"]["multiplicity"]} and facts["scf"]["reference_family"] == family["state"]["reference_family"] and after is not None and abs(after-target) <= tolerance
    return {"checkpoint_binding_accepted": checkpoint["status"] == "accepted_final_optimized_checkpoint", "opt_freq_normal": opt["termination"]["normal"], "opt_freq_stationary": opt["optimization"]["stationary_point_found"], "opt_freq_scf": opt["scf"]["converged"], "opt_freq_frequency_count": opt["frequencies"]["count"] == family["stages"]["opt_freq"]["expected_frequency_count"], "opt_freq_zero_imaginary": opt["frequencies"]["imaginary_count"] == 0, "opt_freq_state_reference_s2": continuity(opt), "stability_normal": stable["termination"]["normal"], "stability_scf": stable["scf"]["converged"], "stability_text_stable": stable["stability"] == {"performed": True, "status": "stable"}, "stability_state_reference_s2": continuity(stable), "same_final_checkpoint_generation": checkpoint["checkpoint"]["file"] == family["stages"]["stability"]["oldcheckpoint"]}


def build_acceptance(handoff_path: Path, checkpoint_binding_path: Path, opt_result: Path, stability_result: Path, acceptance_id: str) -> dict[str, Any]:
    family = _load(handoff_path, "family handoff"); validate_handoff(family); _id(acceptance_id, "acceptance_id")
    checkpoint = _load(checkpoint_binding_path, "checkpoint binding"); validate_checkpoint_binding(checkpoint)
    checks = _acceptance_checks(family, checkpoint, opt_result, stability_result)
    accepted = all(checks.values())
    document = {"schema": ACCEPTANCE_SCHEMA, "acceptance_id": acceptance_id, "workflow": WORKFLOW, "status": "accepted_owner_result" if accepted else "blocked", "family": _binding(handoff_path, family), "checkpoint_binding": _binding(checkpoint_binding_path, checkpoint), "results": {"opt_freq": {"path": str(opt_result.resolve()), "sha256": file_sha256(opt_result)}, "stability": {"path": str(stability_result.resolve()), "sha256": file_sha256(stability_result)}}, "checks": checks, "decision": "accepted_two_stage_minimum_evidence" if accepted else "blocked", **AUTHORITY, "authorizations": copy.deepcopy(NO_ACTIONS), "payload_sha256": None}
    document["payload_sha256"] = payload_sha256(document); validate_acceptance(document); return document


def validate_acceptance(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "acceptance_id", "workflow", "status", "family", "checkpoint_binding", "results", "checks", "decision", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "family acceptance")
    require(document["schema"] == ACCEPTANCE_SCHEMA and document["workflow"] == WORKFLOW, "family acceptance identity mismatch"); _id(document["acceptance_id"], "acceptance_id")
    _validate_family_binding(document["family"], "acceptance family"); _validate_binding(document["checkpoint_binding"], "acceptance checkpoint", CHECKPOINT_SCHEMA)
    results = _exact(document["results"], {"opt_freq", "stability"}, "acceptance results")
    for name in results:
        _exact(results[name], {"path", "sha256"}, f"{name} result"); _sha(results[name]["sha256"], f"{name} result hash")
    require(isinstance(document["checks"], dict) and document["checks"] and all(isinstance(value, bool) for value in document["checks"].values()), "acceptance checks invalid")
    accepted = all(document["checks"].values())
    require((document["status"], document["decision"]) == (("accepted_owner_result", "accepted_two_stage_minimum_evidence") if accepted else ("blocked", "blocked")), "acceptance status/check mismatch")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True and document["authorizations"] == NO_ACTIONS, "acceptance authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "acceptance payload hash mismatch")
    family_path = Path(document["family"]["path"]); checkpoint_path = Path(document["checkpoint_binding"]["path"])
    family = _load(family_path, "acceptance family"); validate_handoff(family)
    checkpoint = _load(checkpoint_path, "acceptance checkpoint binding"); validate_checkpoint_binding(checkpoint)
    require(document["family"] == _binding(family_path, family) and document["checkpoint_binding"] == _binding(checkpoint_path, checkpoint), "acceptance lineage bindings changed")
    opt_path = Path(results["opt_freq"]["path"]); stable_path = Path(results["stability"]["path"])
    require(opt_path.is_file() and stable_path.is_file() and file_sha256(opt_path) == results["opt_freq"]["sha256"] and file_sha256(stable_path) == results["stability"]["sha256"], "acceptance result source changed")
    require(document["checks"] == _acceptance_checks(family, checkpoint, opt_path, stable_path), "acceptance checks differ from deterministic owner replay")


def _render_explicit(spec: dict[str, Any]) -> str:
    coordinates = "\n".join(f"{a['element']} {a['x_angstrom']:.10f} {a['y_angstrom']:.10f} {a['z_angstrom']:.10f}" for a in spec["atoms"])
    return f"%chk={spec['opt_checkpoint']}\n%mem={spec['resources']['mem_gb']}GB\n%nprocshared={spec['resources']['cores']}\n{spec['opt_route']}\n\n{spec['title']} Opt/Freq\n\n{spec['charge']} {spec['multiplicity']}\n{coordinates}\n\n"


def _render_stability(spec: dict[str, Any]) -> str:
    return f"%oldchk={spec['opt_checkpoint']}\n%chk={spec['stability_checkpoint']}\n%mem={spec['resources']['mem_gb']}GB\n%nprocshared={spec['resources']['cores']}\n{spec['stability_route']}\n\n"


def build_family(spec_path: Path, output: Path, opt_input: Path, stability_input: Path) -> dict[str, Any]:
    spec = _load(spec_path, "family build specification")
    common_fields = {"family_id", "title", "charge", "multiplicity", "state_family", "reference_family", "target_s2", "max_abs_s2_deviation", "atoms", "structure_sha256", "opt_route", "stability_route", "opt_checkpoint", "stability_checkpoint", "expected_frequency_count", "resources", "selection_payload_sha256", "selected_option_payload_sha256"}
    is_retry = "superseded_input_sha256" in spec
    lineage_field = "superseded_input_sha256" if is_retry else "family_origin"
    _exact(spec, common_fields | {lineage_field}, "family build specification")
    if is_retry:
        _sha(spec["superseded_input_sha256"], "superseded input hash")
        handoff_schema = HANDOFF_SCHEMA
        lineage = {"failure_lineage": {"superseded_input_sha256": spec["superseded_input_sha256"], "classification": "gaussian_link1_combined_opt_freq_stable_parse_failure", "resubmit_same_input": False}}
    else:
        require(spec["family_origin"] == "prospective_two_stage_minimum", "unsupported prospective family origin")
        handoff_schema = PROSPECTIVE_HANDOFF_SCHEMA
        lineage = {"prospective_lineage": {"classification": "prospective_two_stage_minimum", "prior_failed_input_sha256": None, "combined_route_forbidden": True}}
    opt_text, stable_text = _render_explicit(spec), _render_stability(spec)
    method, basis, reference = _validate_routes(spec["opt_route"], spec["stability_route"])
    require(reference == spec["reference_family"], "build specification reference mismatch")
    require(not output.exists() and not opt_input.exists() and not stability_input.exists(), "refusing to overwrite family outputs")
    document = {"schema": handoff_schema, "family_id": spec["family_id"], "workflow": WORKFLOW, "status": "offline_candidates_ready_for_independent_approval", "state": {key: spec[key] for key in ("charge", "multiplicity", "state_family", "reference_family", "target_s2", "max_abs_s2_deviation")}, "structure": {"atoms": spec["atoms"], "structure_sha256": spec["structure_sha256"]}, "method_basis": {"method": method, "basis": basis}, "resources": spec["resources"], "selection_binding": {"selection_payload_sha256": spec["selection_payload_sha256"], "selected_option_payload_sha256": spec["selected_option_payload_sha256"]}, **lineage, "stages": {"opt_freq": {"stage_id": "opt_freq", "route": spec["opt_route"], "checkpoint": spec["opt_checkpoint"], "input_text": opt_text, "input_sha256": hashlib.sha256(opt_text.encode()).hexdigest(), "expected_frequency_count": spec["expected_frequency_count"]}, "stability": {"stage_id": "stability", "route": spec["stability_route"], "oldcheckpoint": spec["opt_checkpoint"], "checkpoint": spec["stability_checkpoint"], "input_text": stable_text, "input_sha256": hashlib.sha256(stable_text.encode()).hexdigest(), "requires_checkpoint_binding": True}}, "family_requirements": {"independent_stage_receipts": True, "independent_live_approvals": True, "link1_forbidden": True, "mixed_checkpoint_generation_forbidden": True}, **AUTHORITY, "authorizations": copy.deepcopy(NO_ACTIONS), "payload_sha256": None}
    document["payload_sha256"] = payload_sha256(document); validate_handoff(document)
    opt_input.write_text(opt_text, encoding="utf-8"); stability_input.write_text(stable_text, encoding="utf-8")
    output.write_bytes(canonical_bytes(document)); return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-family", help="render two offline candidate inputs and a non-authorizing family handoff")
    build.add_argument("--spec", required=True); build.add_argument("--output", required=True); build.add_argument("--opt-input", required=True); build.add_argument("--stability-input", required=True)
    validate = sub.add_parser("validate", help="validate one family artifact without network access")
    validate.add_argument("kind", choices=["handoff", "checkpoint", "manifest", "receipt", "acceptance"]); validate.add_argument("path")
    bind = sub.add_parser("bind-checkpoint", help="accept exact offline Opt/Freq evidence and bind its final checkpoint")
    bind.add_argument("--handoff", required=True); bind.add_argument("--result", required=True); bind.add_argument("--checkpoint", required=True); bind.add_argument("--binding-id", required=True); bind.add_argument("--output", required=True)
    manifest = sub.add_parser("build-stability-manifest", help="bind the Stable=Opt candidate to the accepted final checkpoint")
    manifest.add_argument("--handoff", required=True); manifest.add_argument("--checkpoint-binding", required=True); manifest.add_argument("--input", required=True); manifest.add_argument("--output", required=True)
    receipt = sub.add_parser("approve-stage", help="create one non-authorizing exact family-stage receipt /3")
    receipt.add_argument("--handoff", required=True); receipt.add_argument("--input", required=True); receipt.add_argument("--stage", choices=["opt_freq", "stability"], required=True); receipt.add_argument("--receipt-id", required=True); receipt.add_argument("--checkpoint-binding"); receipt.add_argument("--manifest"); receipt.add_argument("--output", required=True)
    accept = sub.add_parser("accept-results", help="aggregate both offline stage results under the owner evidence policy")
    accept.add_argument("--handoff", required=True); accept.add_argument("--checkpoint-binding", required=True); accept.add_argument("--opt-result", required=True); accept.add_argument("--stability-result", required=True); accept.add_argument("--acceptance-id", required=True); accept.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "build-family":
        build_family(Path(args.spec), Path(args.output), Path(args.opt_input), Path(args.stability_input)); return 0
    if args.command != "validate":
        output = Path(args.output)
        require(not output.exists() and not output.is_symlink(), f"refusing to overwrite output: {output}")
        if args.command == "bind-checkpoint":
            document = build_checkpoint_binding(Path(args.handoff), Path(args.result), Path(args.checkpoint), args.binding_id)
        elif args.command == "build-stability-manifest":
            document = build_stability_manifest(Path(args.handoff), Path(args.checkpoint_binding), Path(args.input))
        elif args.command == "approve-stage":
            document = build_stage_receipt(Path(args.handoff), Path(args.input), args.receipt_id, args.stage, Path(args.checkpoint_binding) if args.checkpoint_binding else None, Path(args.manifest) if args.manifest else None)
        else:
            document = build_acceptance(Path(args.handoff), Path(args.checkpoint_binding), Path(args.opt_result), Path(args.stability_result), args.acceptance_id)
        output.write_bytes(canonical_bytes(document)); return 0
    document = _load(Path(args.path), args.kind)
    {"handoff": validate_handoff, "checkpoint": validate_checkpoint_binding, "manifest": validate_stability_manifest, "receipt": validate_stage_receipt, "acceptance": validate_acceptance}[args.kind](document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
