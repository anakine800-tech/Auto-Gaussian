#!/usr/bin/env python3
"""Build and validate offline Gaussian protocol-rigor options and selections."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


TIERS = ("loose", "standard", "strict")
RANKS = {"loose": 1, "standard": 2, "strict": 3}
DISPLAY_NAMES = {"loose": "宽松", "standard": "标准", "strict": "严格"}
RESOURCE_TIERS = {"simple", "general", "complex", "custom_reviewed", "unresolved"}
FORBIDDEN_KEYS = {
    "route", "route_preview", "input", "input_text", "gaussian_input", "checkpoint",
    "server", "server_path", "remote_root", "project", "job", "job_id", "qsub",
    "recommended", "selected", "default_tier", "submission_authorized",
}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ContractError(ValueError):
    """Raised when a protocol artifact violates a fail-closed rule."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _reject_constant(token: str) -> None:
    raise ContractError(f"non-standard JSON constant is forbidden: {token}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_pairs,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(value: Any) -> str:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def _without(document: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in document.items() if name != key}


def _finite_positive(value: Any, field: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{field} must be numeric")
    number = float(value)
    require(math.isfinite(number) and number > 0, f"{field} must be finite and positive")
    return number


def _nonempty_string(value: Any, field: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    require(isinstance(value, list), f"{field} must be an array")
    require(allow_empty or bool(value), f"{field} must not be empty")
    for item in value:
        _nonempty_string(item, field)
    return value


def _reject_forbidden_keys(value: Any, path: str = "$", *, parent: str | None = None) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            require(lowered not in FORBIDDEN_KEYS, f"{path}.{key}: forbidden pre-input field")
            require(not lowered.startswith("%"), f"{path}.{key}: Gaussian Link 0 fields are forbidden")
            _reject_forbidden_keys(child, f"{path}.{key}", parent=key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]", parent=parent)
    elif isinstance(value, float):
        require(math.isfinite(value), f"{path}: non-finite number is forbidden")


def validate_request(request: dict[str, Any]) -> None:
    require(request.get("schema") == "gaussian-calculation-request/1", "request: wrong schema")
    require(ID_PATTERN.fullmatch(str(request.get("request_id", ""))) is not None, "request: invalid request_id")
    _nonempty_string(request.get("goal"), "request.goal")
    _nonempty_string(request.get("claim_scope"), "request.claim_scope")
    _string_list(request.get("task_types"), "request.task_types", allow_empty=False)
    require(request.get("calculation_ready") is False, "request: calculation_ready must be false")
    require(request.get("no_submission_authorization") is True, "request: no_submission_authorization must be true")
    structure = request.get("structure")
    require(isinstance(structure, dict), "request.structure must be an object")
    require(SHA_PATTERN.fullmatch(str(structure.get("sha256", ""))) is not None, "request: invalid structure sha256")
    _nonempty_string(structure.get("formula"), "request.structure.formula")
    require(isinstance(structure.get("atom_count"), int) and structure["atom_count"] > 0, "request: atom_count must be positive")
    elements = _string_list(structure.get("elements"), "request.structure.elements", allow_empty=False)
    require(len(elements) == len(set(elements)), "request: elements must be unique")
    require(isinstance(structure.get("charge"), int) and not isinstance(structure["charge"], bool), "request: charge must be integer")
    require(isinstance(structure.get("multiplicity"), int) and structure["multiplicity"] > 0, "request: multiplicity must be positive")
    require(request.get("support_status") in {"supported", "unsupported", "unresolved"}, "request: invalid support_status")
    _reject_forbidden_keys(request)


def _validate_basis_stack(profile: dict[str, Any], elements: set[str], context: str) -> None:
    stack = profile.get("basis_stack")
    require(isinstance(stack, list) and stack, f"{context}.basis_stack must not be empty")
    covered: set[str] = set()
    for index, record in enumerate(stack):
        require(isinstance(record, dict), f"{context}.basis_stack[{index}] must be an object")
        basis_elements = set(_string_list(record.get("elements"), f"{context}.basis_stack[{index}].elements", allow_empty=False))
        require(not covered.intersection(basis_elements), f"{context}: basis element coverage overlaps")
        covered.update(basis_elements)
        _nonempty_string(record.get("orbital_basis"), f"{context}.basis_stack[{index}].orbital_basis")
        ecp = record.get("ecp")
        core = record.get("ecp_core_electrons")
        if ecp is None:
            require(core is None, f"{context}: ECP core electron count requires an ECP")
        else:
            _nonempty_string(ecp, f"{context}.basis_stack[{index}].ecp")
            require(isinstance(core, int) and core >= 0, f"{context}: ECP core electron count is required")
    require(covered == elements, f"{context}: basis/ECP coverage must exactly match request elements")


def _validate_method_profile(profile: Any, elements: set[str], context: str) -> None:
    require(isinstance(profile, dict), f"{context} must be an object")
    _nonempty_string(profile.get("profile_id"), f"{context}.profile_id")
    _string_list(profile.get("stages"), f"{context}.stages", allow_empty=False)
    _nonempty_string(profile.get("functional_or_method"), f"{context}.functional_or_method")
    _validate_basis_stack(profile, elements, context)
    for field in ("dispersion", "solvation", "scf"):
        require(isinstance(profile.get(field), dict), f"{context}.{field} must be an object")
    solvation = profile["solvation"]
    require(solvation.get("mode") in {"gas_phase", "continuum", "explicit", "hybrid"}, f"{context}: invalid solvation mode")
    if solvation["mode"] in {"continuum", "hybrid"}:
        _nonempty_string(solvation.get("model"), f"{context}.solvation.model")
        _nonempty_string(solvation.get("solvent_identity"), f"{context}.solvation.solvent_identity")
    _nonempty_string(profile.get("grid"), f"{context}.grid")
    _nonempty_string(profile.get("relativistic_treatment"), f"{context}.relativistic_treatment")
    _nonempty_string(profile.get("software_compatibility"), f"{context}.software_compatibility")


def _validate_resources(resources: Any, context: str) -> None:
    require(isinstance(resources, dict), f"{context}.resources must be an object")
    require(resources.get("resource_tier") in RESOURCE_TIERS, f"{context}: invalid resource tier")
    _finite_positive(resources.get("mem_gb"), f"{context}.resources.mem_gb")
    cores = resources.get("cores")
    require(isinstance(cores, int) and not isinstance(cores, bool) and 1 <= cores <= 44, f"{context}: cores must be 1..44")
    jobs = resources.get("job_count")
    require(isinstance(jobs, int) and not isinstance(jobs, bool) and jobs >= 1, f"{context}: job_count must be positive")
    _finite_positive(resources.get("relative_cost_units"), f"{context}.resources.relative_cost_units")
    _string_list(resources.get("assumptions"), f"{context}.resources.assumptions", allow_empty=False)


def _validate_option(option: Any, request: dict[str, Any]) -> None:
    require(isinstance(option, dict), "option must be an object")
    tier = option.get("tier")
    require(tier in TIERS, "option: invalid tier")
    context = f"option[{tier}]"
    require(option.get("rigor_rank") == RANKS[tier], f"{context}: wrong rigor_rank")
    require(option.get("display_name") == DISPLAY_NAMES[tier], f"{context}: wrong display_name")
    require(ID_PATTERN.fullmatch(str(option.get("option_id", ""))) is not None, f"{context}: invalid option_id")
    status = option.get("option_status")
    require(status in {"selectable", "blocked"}, f"{context}: invalid option_status")
    _nonempty_string(option.get("purpose"), f"{context}.purpose")
    require(isinstance(option.get("applicability"), dict), f"{context}.applicability must be an object")
    _string_list(option.get("limitations"), f"{context}.limitations", allow_empty=False)
    _string_list(option.get("provenance"), f"{context}.provenance", allow_empty=False)
    unresolved = _string_list(option.get("unresolved"), f"{context}.unresolved")
    _validate_resources(option.get("resources"), context)
    require(isinstance(option.get("expected_cost"), dict), f"{context}.expected_cost must be an object")
    _nonempty_string(option["expected_cost"].get("band"), f"{context}.expected_cost.band")
    _string_list(option["expected_cost"].get("drivers"), f"{context}.expected_cost.drivers", allow_empty=False)
    profiles = option.get("method_profiles")
    tasks = option.get("task_plan")
    require(isinstance(profiles, list), f"{context}.method_profiles must be an array")
    require(isinstance(tasks, list), f"{context}.task_plan must be an array")
    for field in ("validation_plan", "coverage_plan"):
        require(isinstance(option.get(field), dict) and option[field], f"{context}.{field} must be a non-empty object")
    if status == "selectable":
        require(request.get("support_status") == "supported", f"{context}: unsupported request cannot have selectable options")
        require(not unresolved, f"{context}: selectable option has unresolved fields")
        require(profiles and tasks, f"{context}: selectable option requires method profiles and task plan")
        elements = set(request["structure"]["elements"])
        profile_ids: set[str] = set()
        for index, profile in enumerate(profiles):
            _validate_method_profile(profile, elements, f"{context}.method_profiles[{index}]")
            profile_id = profile["profile_id"]
            require(profile_id not in profile_ids, f"{context}: duplicate method profile")
            profile_ids.add(profile_id)
        for index, task in enumerate(tasks):
            require(isinstance(task, dict), f"{context}.task_plan[{index}] must be an object")
            _nonempty_string(task.get("stage_type"), f"{context}.task_plan[{index}].stage_type")
            require(task.get("profile_id") in profile_ids, f"{context}: task references unknown profile")
            _string_list(task.get("acceptance_checks"), f"{context}.task_plan[{index}].acceptance_checks", allow_empty=False)
    else:
        require(bool(unresolved), f"{context}: blocked option requires unresolved reasons")
        require(not profiles and not tasks, f"{context}: blocked option must not carry runnable method/task profiles")


def _scientific_signature(option: dict[str, Any]) -> str:
    fields = ("purpose", "applicability", "method_profiles", "task_plan", "validation_plan", "coverage_plan")
    value = json.loads(json.dumps({field: option.get(field) for field in fields}))
    for profile in value.get("method_profiles", []):
        profile["profile_id"] = "bound_profile"
    for task in value.get("task_plan", []):
        task["profile_id"] = "bound_profile"
    return payload_sha256(value)


def validate_options(document: dict[str, Any]) -> None:
    require(document.get("schema") == "gaussian-protocol-options/1", "options: wrong schema")
    require(document.get("status") in {"ready_for_selection", "blocked"}, "options: invalid status")
    require(document.get("calculation_ready") is False, "options: calculation_ready must be false")
    require(document.get("no_input_render_authorization") is True, "options: must not authorize input before selection")
    require(document.get("no_submission_authorization") is True, "options: must not authorize submission")
    request = document.get("request_snapshot")
    require(isinstance(request, dict), "options: missing request snapshot")
    validate_request(request)
    source = document.get("request_source")
    require(isinstance(source, dict) and SHA_PATTERN.fullmatch(str(source.get("sha256", ""))) is not None, "options: invalid request source")
    request_path = Path(str(source.get("path", ""))).expanduser().resolve()
    require(request_path.is_file(), "options: bound request artifact is unavailable")
    require(sha256_file(request_path) == source["sha256"], "options: request file hash mismatch")
    require(load_json(request_path) == request, "options: request snapshot differs from bound request artifact")
    options = document.get("options")
    require(isinstance(options, list) and len(options) == 3, "options: exactly three candidates are required")
    tiers = [option.get("tier") for option in options if isinstance(option, dict)]
    require(set(tiers) == set(TIERS) and len(tiers) == len(set(tiers)), "options: require unique loose/standard/strict candidates")
    option_ids: set[str] = set()
    for option in options:
        _validate_option(option, request)
        require(option["option_id"] not in option_ids, "options: duplicate option_id")
        option_ids.add(option["option_id"])
        expected = payload_sha256(_without(option, "option_payload_sha256"))
        require(option.get("option_payload_sha256") == expected, f"option[{option['tier']}]: payload hash mismatch")
    require(len({_scientific_signature(option) for option in options}) > 1, "options: all three candidates are scientifically identical")
    selectable = any(option["option_status"] == "selectable" for option in options)
    require(document["status"] == ("ready_for_selection" if selectable else "blocked"), "options: status does not match candidates")
    _string_list(document.get("comparison_notes"), "options.comparison_notes", allow_empty=False)
    non_claims = _string_list(document.get("non_claims"), "options.non_claims", allow_empty=False)
    require(any("accuracy" in item.lower() and "guarantee" in item.lower() for item in non_claims), "options: must state that strict is not an accuracy guarantee")
    _reject_forbidden_keys(document)
    expected_payload = payload_sha256(_without(document, "proposal_payload_sha256"))
    require(document.get("proposal_payload_sha256") == expected_payload, "options: proposal payload hash mismatch")


def build_options(request_path: Path, profiles_path: Path) -> dict[str, Any]:
    request_path = request_path.expanduser().resolve()
    profiles_path = profiles_path.expanduser().resolve()
    request = load_json(request_path)
    validate_request(request)
    profiles = load_json(profiles_path)
    require(profiles.get("schema") == "gaussian-protocol-profile-source/1", "profiles: wrong schema")
    raw_options = profiles.get("options")
    require(isinstance(raw_options, list), "profiles.options must be an array")
    options = json.loads(json.dumps(raw_options))
    for option in options:
        require(isinstance(option, dict), "profiles option must be an object")
        require("option_payload_sha256" not in option, "profiles must not supply payload hashes")
        tier = option.get("tier")
        require(tier in TIERS, "profiles option has invalid tier")
        option["display_name"] = DISPLAY_NAMES[tier]
        option["option_payload_sha256"] = payload_sha256(option)
    document = {
        "schema": "gaussian-protocol-options/1",
        "proposal_id": profiles.get("proposal_id"),
        "status": "ready_for_selection" if any(item.get("option_status") == "selectable" for item in options) else "blocked",
        "calculation_ready": False,
        "no_input_render_authorization": True,
        "no_submission_authorization": True,
        "request_source": {"path": str(request_path), "sha256": sha256_file(request_path)},
        "request_snapshot": request,
        "difficulty_assessment": profiles.get("difficulty_assessment"),
        "common_constraints": profiles.get("common_constraints"),
        "options": options,
        "comparison_notes": profiles.get("comparison_notes"),
        "non_claims": profiles.get("non_claims"),
    }
    require(ID_PATTERN.fullmatch(str(document.get("proposal_id", ""))) is not None, "profiles: invalid proposal_id")
    require(isinstance(document["difficulty_assessment"], dict), "profiles: missing difficulty_assessment")
    require(isinstance(document["common_constraints"], dict), "profiles: missing common_constraints")
    document["proposal_payload_sha256"] = payload_sha256(document)
    validate_options(document)
    return document


def get_selected_option(options: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    selected = selection.get("selected_option", {})
    matches = [item for item in options.get("options", []) if item.get("tier") == selected.get("tier")]
    require(len(matches) == 1, "selection: selected tier is absent from options")
    option = matches[0]
    require(option.get("option_id") == selected.get("option_id"), "selection: option_id mismatch")
    require(option.get("option_payload_sha256") == selected.get("option_payload_sha256"), "selection: selected option hash mismatch")
    return option


def validate_selection(selection: dict[str, Any], options: dict[str, Any]) -> None:
    validate_options(options)
    require(selection.get("schema") == "gaussian-protocol-selection/1", "selection: wrong schema")
    require(selection.get("status") == "selected_for_input_draft", "selection: invalid status")
    require(selection.get("calculation_ready") is False, "selection: calculation_ready must be false")
    require(selection.get("no_submission_authorization") is True, "selection: submission must remain unauthorized")
    require(selection.get("request_sha256") == options["request_source"]["sha256"], "selection: request hash mismatch")
    require(selection.get("proposal_payload_sha256") == options["proposal_payload_sha256"], "selection: proposal payload hash mismatch")
    option = get_selected_option(options, selection)
    require(option.get("option_status") == "selectable", "selection: blocked option cannot be selected")
    require(selection.get("alternatives_reviewed") == list(TIERS), "selection: all three alternatives must be reviewed")
    approval = selection.get("approval_evidence")
    require(isinstance(approval, dict), "selection: missing approval evidence")
    require(approval.get("kind") == "explicit_user_selection" and approval.get("explicit_confirmation") is True, "selection: explicit user confirmation is required")
    require(SHA_PATTERN.fullmatch(str(approval.get("sha256", ""))) is not None, "selection: invalid approval hash")
    authorizations = selection.get("authorizations")
    require(
        authorizations == {
            "render_input_draft": True,
            "submit": False,
            "create_server_directory": False,
            "retry": False,
            "irc": False,
            "cancel": False,
            "cleanup": False,
        },
        "selection: authorization boundary changed",
    )
    scope = selection.get("scope_binding")
    request = options["request_snapshot"]
    expected_scope = {
        "structure_sha256": request["structure"]["sha256"],
        "charge": request["structure"]["charge"],
        "multiplicity": request["structure"]["multiplicity"],
        "task_types": request["task_types"],
    }
    require(scope == expected_scope, "selection: calculation scope mismatch")
    _reject_forbidden_keys(selection)
    expected = payload_sha256(_without(selection, "selection_payload_sha256"))
    require(selection.get("selection_payload_sha256") == expected, "selection: payload hash mismatch")


def build_selection(
    options_path: Path,
    tier: str,
    approval_record_path: Path,
    selection_id: str | None = None,
) -> dict[str, Any]:
    options_path = options_path.expanduser().resolve()
    approval_record_path = approval_record_path.expanduser().resolve()
    options = load_json(options_path)
    validate_options(options)
    require(tier in TIERS, "selection: invalid tier")
    approval = load_json(approval_record_path)
    require(approval.get("decision") == "selected" and approval.get("tier") == tier, "approval record does not select the requested tier")
    require(approval.get("explicit_confirmation") is True, "approval record lacks explicit confirmation")
    selected = next(item for item in options["options"] if item["tier"] == tier)
    require(selected["option_status"] == "selectable", "selection: blocked option cannot be selected")
    request = options["request_snapshot"]
    document = {
        "schema": "gaussian-protocol-selection/1",
        "selection_id": selection_id or f"{options['proposal_id']}_{tier}_selection",
        "status": "selected_for_input_draft",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "options_source": {"path": str(options_path), "sha256": sha256_file(options_path)},
        "request_sha256": options["request_source"]["sha256"],
        "proposal_payload_sha256": options["proposal_payload_sha256"],
        "selected_option": {
            "tier": tier,
            "option_id": selected["option_id"],
            "option_payload_sha256": selected["option_payload_sha256"],
        },
        "scope_binding": {
            "structure_sha256": request["structure"]["sha256"],
            "charge": request["structure"]["charge"],
            "multiplicity": request["structure"]["multiplicity"],
            "task_types": request["task_types"],
        },
        "approval_evidence": {
            "kind": "explicit_user_selection",
            "path": str(approval_record_path),
            "sha256": sha256_file(approval_record_path),
            "explicit_confirmation": True,
        },
        "decision_reason": _nonempty_string(approval.get("decision_reason"), "approval.decision_reason"),
        "alternatives_reviewed": list(TIERS),
        "authorizations": {
            "render_input_draft": True,
            "submit": False,
            "create_server_directory": False,
            "retry": False,
            "irc": False,
            "cancel": False,
            "cleanup": False,
        },
    }
    require(ID_PATTERN.fullmatch(document["selection_id"]) is not None, "selection: invalid selection_id")
    document["selection_payload_sha256"] = payload_sha256(document)
    validate_selection(document, options)
    return document


def load_validated_selection(
    selection_path: Path,
    options_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    selection_path = selection_path.expanduser().resolve()
    selection = load_json(selection_path)
    source = selection.get("options_source", {})
    resolved_options = options_path.expanduser().resolve() if options_path else Path(str(source.get("path", ""))).expanduser().resolve()
    require(resolved_options.is_file(), "selection: bound options artifact is unavailable")
    require(sha256_file(resolved_options) == source.get("sha256"), "selection: options file hash mismatch")
    options = load_json(resolved_options)
    validate_selection(selection, options)
    approval_path = Path(str(selection["approval_evidence"]["path"])).expanduser().resolve()
    require(approval_path.is_file(), "selection: approval record is unavailable")
    require(sha256_file(approval_path) == selection["approval_evidence"]["sha256"], "selection: approval record hash mismatch")
    return selection, options, get_selected_option(options, selection)


def write_new_json(path: Path, document: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    require(not path.exists(), f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("request")
    propose.add_argument("--profiles", required=True)
    propose.add_argument("--output", required=True)
    select = sub.add_parser("select")
    select.add_argument("options")
    select.add_argument("--tier", choices=TIERS, required=True)
    select.add_argument("--approval-record", required=True)
    select.add_argument("--selection-id")
    select.add_argument("--confirmed", action="store_true")
    select.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("artifact")
    validate.add_argument("--options")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "propose":
            document = build_options(Path(args.request), Path(args.profiles))
            write_new_json(Path(args.output), document)
            summary = {"valid": True, "schema": document["schema"], "status": document["status"], "live_actions": False}
        elif args.command == "select":
            require(args.confirmed, "select requires --confirmed after the user explicitly chooses one displayed tier")
            document = build_selection(Path(args.options), args.tier, Path(args.approval_record), args.selection_id)
            write_new_json(Path(args.output), document)
            summary = {"valid": True, "schema": document["schema"], "tier": args.tier, "live_actions": False}
        else:
            artifact_path = Path(args.artifact).expanduser().resolve()
            document = load_json(artifact_path)
            if document.get("schema") == "gaussian-protocol-options/1":
                validate_options(document)
                summary = {"valid": True, "schema": document["schema"], "live_actions": False}
            elif document.get("schema") == "gaussian-protocol-selection/1":
                load_validated_selection(artifact_path, Path(args.options) if args.options else None)
                summary = {"valid": True, "schema": document["schema"], "live_actions": False}
            else:
                raise ContractError("validate: unknown protocol artifact schema")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
