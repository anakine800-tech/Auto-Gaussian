#!/usr/bin/env python3
"""Offline V1 input handoff and result-continuity gate for open-shell minima."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_ROOT = SCRIPT_DIR.parents[1]
ROOT = SKILLS_ROOT.parent
PROTOCOL_PATH = SKILLS_ROOT / "auto-g16-rtwin-pbs" / "scripts" / "protocol_selection.py"
STATE_PATH = SCRIPT_DIR / "open_shell_state.py"


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load specialist module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = _module("open_shell_minimum_state", STATE_PATH)
protocol = _module("open_shell_minimum_protocol", PROTOCOL_PATH)

WORKFLOW = "main_group_open_shell_minimum_opt_freq_v1"
SCHEMA_STRUCTURE = "auto-g16-main-group-open-shell-cartesian-candidate/1"
SCHEMA_SPEC = "auto-g16-main-group-open-shell-input-specification/1"
SCHEMA_HANDOFF = "auto-g16-main-group-open-shell-minimum-opt-freq-input-handoff/1"
SCHEMA_AUDIT = "auto-g16-main-group-open-shell-minimum-opt-freq-input-audit/1"
SCHEMA_RESULT_BINDING = "auto-g16-main-group-open-shell-result-source-binding/1"
SCHEMA_RESULT_OBSERVATION = "auto-g16-main-group-open-shell-minimum-opt-freq-result-observation/1"
SCHEMA_CONTINUITY = "auto-g16-main-group-open-shell-minimum-opt-freq-result-continuity/1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
COORD_RE = re.compile(r"^\s*([A-Z][a-z]?)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$")


class ContractError(ValueError):
    """A V1 artifact failed closed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == keys, f"{label} fields mismatch; missing={sorted(keys-set(value))} unknown={sorted(set(value)-keys)}")
    return value


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _text(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    return value


def canonical_bytes(value: Any) -> bytes:
    return state.canonical_bytes(value)


def payload_sha256(value: dict[str, Any]) -> str:
    return state.payload_sha256(value)


def file_sha256(path: Path) -> str:
    return state.file_sha256(path)


def portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def load(path: str | Path, label: str, *, canonical: bool = False) -> tuple[Path, dict[str, Any]]:
    return state.load_json(path, label=label, canonical=canonical)


def binding(path: Path, document: dict[str, Any], payload_field: str = "payload_sha256") -> dict[str, Any]:
    return {
        "path": portable(path),
        "sha256": file_sha256(path),
        "schema": document["schema"],
        "payload_sha256": _sha(document[payload_field], f"{document['schema']} payload hash"),
    }


def validate_binding(value: Any, label: str) -> None:
    item = _exact(value, {"path", "sha256", "schema", "payload_sha256"}, label)
    _text(item["path"], f"{label}.path")
    _sha(item["sha256"], f"{label}.sha256")
    _text(item["schema"], f"{label}.schema")
    _sha(item["payload_sha256"], f"{label}.payload_sha256")


def coordinate_payload(atoms: list[dict[str, Any]], charge: int, multiplicity: int) -> str:
    return hashlib.sha256(canonical_bytes({"atoms": atoms, "charge": charge, "multiplicity": multiplicity})).hexdigest()


def validate_structure(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "candidate_id", "structure_sha256", "atoms", "charge", "multiplicity", "provenance", "human_review_confirmed", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "Cartesian candidate")
    require(document["schema"] == SCHEMA_STRUCTURE, "Cartesian candidate schema mismatch")
    _id(document["candidate_id"], "candidate_id")
    atoms = document["atoms"]
    require(isinstance(atoms, list) and atoms, "Cartesian candidate atoms must be non-empty")
    for expected, atom in enumerate(atoms, 1):
        _exact(atom, {"index", "element", "x_angstrom", "y_angstrom", "z_angstrom"}, f"atom[{expected}]")
        require(atom["index"] == expected, "Cartesian candidate atom order must be contiguous and one-based")
        require(atom["element"] in state.ATOMIC_NUMBERS, f"unknown element: {atom['element']}")
        for axis in ("x_angstrom", "y_angstrom", "z_angstrom"):
            state._number(atom[axis], f"atom[{expected}].{axis}")
    require(isinstance(document["charge"], int) and not isinstance(document["charge"], bool), "candidate charge must be integer")
    require(isinstance(document["multiplicity"], int) and document["multiplicity"] >= 1, "candidate multiplicity invalid")
    _exact(document["provenance"], {"converter", "source_sha256", "review_note"}, "candidate provenance")
    _text(document["provenance"]["converter"], "candidate converter")
    _sha(document["provenance"]["source_sha256"], "candidate provenance source hash")
    _text(document["provenance"]["review_note"], "candidate review note")
    require(document["human_review_confirmed"] is True, "Cartesian candidate requires explicit human review")
    require(document["structure_sha256"] == coordinate_payload(atoms, document["charge"], document["multiplicity"]), "Cartesian candidate coordinate hash mismatch")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "Cartesian candidate authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "Cartesian candidate payload hash mismatch")


def validate_spec(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "specification_id", "workflow", "route", "title", "checkpoint", "charge", "multiplicity", "reference_family", "stability_required", "expected_frequency_count", "resources", "server_directory", "server_directory_status", "selection_payload_sha256", "selected_option_payload_sha256", "explicit_review", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "input specification")
    require(document["schema"] == SCHEMA_SPEC and document["workflow"] == WORKFLOW, "input specification schema/workflow mismatch")
    _id(document["specification_id"], "specification_id")
    route = _text(document["route"], "route")
    require(route.lstrip().startswith("#"), "route must be an explicit Gaussian route card")
    _text(document["title"], "title")
    checkpoint = _text(document["checkpoint"], "checkpoint")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.chk", checkpoint) is not None, "invalid checkpoint basename")
    require(isinstance(document["charge"], int) and isinstance(document["multiplicity"], int), "input state must be explicit integers")
    require(document["reference_family"] in {"U", "RO"}, "input reference must be U or RO")
    require(document["stability_required"] is True, "input specification must require stability")
    require(isinstance(document["expected_frequency_count"], int) and document["expected_frequency_count"] > 0, "expected frequency count invalid")
    resources = _exact(document["resources"], {"resource_tier", "mem_gb", "cores"}, "resources")
    _text(resources["resource_tier"], "resource tier")
    require(isinstance(resources["mem_gb"], int) and resources["mem_gb"] > 0, "mem_gb invalid")
    require(isinstance(resources["cores"], int) and resources["cores"] > 0, "cores invalid")
    require(document["server_directory"] is None and document["server_directory_status"] == "not_created_not_authorized", "offline V1 must not bind or create a server directory")
    _sha(document["selection_payload_sha256"], "selection payload hash")
    _sha(document["selected_option_payload_sha256"], "selected option payload hash")
    review = _exact(document["explicit_review"], {"route", "resources", "state", "reference", "stability", "frequency_count", "confirmed"}, "explicit input review")
    require(all(review[key] is True for key in ("route", "resources", "state", "reference", "stability", "frequency_count", "confirmed")), "all input specification fields require explicit review")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "input specification authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "input specification payload hash mismatch")


def _load_protocol(selection_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    selection, selection_raw = load(selection_path, "protocol selection", canonical=True)
    options_ref = selection_raw.get("options_source", {})
    options_path = Path(str(options_ref.get("path", ""))).expanduser()
    if not options_path.is_absolute():
        candidates = [ROOT / options_path, selection.parent / options_path]
        options_path = next((path for path in candidates if path.is_file()), candidates[0])
    require(options_path.is_file(), "bound protocol options are unavailable")
    options = protocol.load_json(options_path)
    protocol.validate_selection(selection_raw, options)
    require(file_sha256(options_path) == options_ref["sha256"], "protocol options file hash mismatch")
    selected = protocol.get_selected_option(options, selection_raw)
    return selection_raw, options, selected, options_path.resolve()


def _normalize_route(route: str) -> str:
    normalized = " ".join(route.lower().split())
    normalized = re.sub(r"\s*=\s*", "=", normalized)
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    normalized = re.sub(r"\(\s*", "(", normalized)
    normalized = re.sub(r"\s*\)", ")", normalized)
    return re.sub(r"\s+\(", "(", normalized)


def _route_tokens(route: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    for character in route:
        if character.isspace() and depth == 0:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(character)
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
    if current:
        tokens.append("".join(current))
    return tokens


def _route_has_keyword(route: str, keyword: str) -> bool:
    return any(re.match(rf"^{re.escape(keyword)}(?=$|[=(])", token) is not None for token in _route_tokens(route))


def _route_keyword_count(route: str, keyword: str) -> int:
    return sum(re.match(rf"^{re.escape(keyword)}(?=$|[=(])", token) is not None for token in _route_tokens(route))


def _route_option_values(route: str, keyword: str) -> list[str]:
    result: list[str] = []
    for token in _route_tokens(route):
        match = re.fullmatch(rf"{re.escape(keyword)}(?:=([^\s]+)|\(([^)]*)\))", token)
        if match is None:
            continue
        raw = (match.group(1) or match.group(2) or "").strip("()")
        result.extend(value for value in raw.split(",") if value)
    return result


def _route_audit(route: str, reference: str) -> dict[str, Any]:
    normalized = _normalize_route(route)
    has_opt = _route_has_keyword(normalized, "opt")
    has_freq = _route_has_keyword(normalized, "freq") or _route_has_keyword(normalized, "frequency")
    has_stable = _route_has_keyword(normalized, "stable")
    forbidden: list[str] = []

    depth = 0
    for character in normalized:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        forbidden.append("malformed:parentheses")

    for keyword in ("irc", "ircmax", "td", "tda", "qst2", "qst3", "scan", "mecp"):
        if _route_has_keyword(normalized, keyword):
            forbidden.append(f"keyword:{keyword}")
    for keyword in ("fopt", "popt"):
        if _route_has_keyword(normalized, keyword):
            forbidden.append(f"optimization_family:{keyword}")
    if _route_keyword_count(normalized, "opt") != 1:
        forbidden.append("opt:missing_or_duplicate")

    forbidden_opt_options = {
        "ts", "qst2", "qst3", "conical", "avoided", "scan",
        "modredundant", "addredundant", "gic", "addgic", "readallgic",
    }
    for option in _route_option_values(normalized, "opt"):
        if option in forbidden_opt_options:
            forbidden.append(f"opt:{option}")
            continue
        saddle = re.fullmatch(r"saddle=([0-9]+)", option)
        if saddle is not None and int(saddle.group(1)) >= 1:
            forbidden.append(f"opt:{option}")
    if "mix" in _route_option_values(normalized, "guess"):
        forbidden.append("guess:mix")

    method_token = next((token for token in _route_tokens(normalized) if "/" in token), "")
    method = method_token.split("/", 1)[0]
    reference_ok = method.startswith("ro") if reference == "RO" else method.startswith("u") and not method.startswith("ro")
    return {"opt": has_opt, "freq": has_freq, "stable": has_stable, "reference": reference_ok, "forbidden_tokens": forbidden}


def _render_input(spec: dict[str, Any], structure: dict[str, Any]) -> str:
    lines = [
        f"%chk={spec['checkpoint']}",
        f"%mem={spec['resources']['mem_gb']}GB",
        f"%nprocshared={spec['resources']['cores']}",
        spec["route"], "", spec["title"], "", f"{spec['charge']} {spec['multiplicity']}",
    ]
    for atom in structure["atoms"]:
        lines.append(f"{atom['element']:<3} {float(atom['x_angstrom']): .8f} {float(atom['y_angstrom']): .8f} {float(atom['z_angstrom']): .8f}")
    return "\n".join(lines) + "\n\n"


def build_handoff(review_path: str | Path, structure_path: str | Path, selection_path: str | Path, spec_path: str | Path, handoff_id: str) -> dict[str, Any]:
    _id(handoff_id, "handoff_id")
    review_file, review = state.load_validated_review(review_path)
    require(review["status"] == "accepted", "handoff requires an accepted electronic-state review")
    structure_file, structure = load(structure_path, "exact Cartesian candidate", canonical=True)
    validate_structure(structure)
    selection_file = Path(selection_path).expanduser().resolve()
    selection, options, selected, options_file = _load_protocol(selection_file)
    spec_file, spec = load(spec_path, "input specification", canonical=True)
    validate_spec(spec)
    candidate = review["candidate_snapshot"]
    require(structure["candidate_id"] == candidate["candidate_id"], "structure candidate identity drift")
    require(structure["structure_sha256"] == candidate["structure_sha256"] == selection["scope_binding"]["structure_sha256"], "structure hash drift across candidate/review/protocol")
    require(structure["charge"] == candidate["charge"] == selection["scope_binding"]["charge"] == spec["charge"], "charge drift")
    require(structure["multiplicity"] == candidate["multiplicity"] == selection["scope_binding"]["multiplicity"] == spec["multiplicity"], "multiplicity drift")
    atom_pairs = [{"index": atom["index"], "element": atom["element"]} for atom in structure["atoms"]]
    require(atom_pairs == candidate["atoms"], "atom order or element inventory drift")
    require(selection["scope_binding"].get("electronic_state_review_payload_sha256") == review["payload_sha256"], "protocol selection state-review binding drift")
    require(spec["selection_payload_sha256"] == selection["selection_payload_sha256"], "input specification selection hash drift")
    require(spec["selected_option_payload_sha256"] == selected["option_payload_sha256"], "input specification selected-option hash drift")
    wavefunction = review["wavefunction_policy"]
    require(spec["reference_family"] == wavefunction["reference"], "reference-family drift")
    require(spec["stability_required"] == wavefunction["stability_required"], "stability requirement drift")
    require(spec["expected_frequency_count"] == review["state_assessment"]["expected_frequency_count"], "expected frequency-count drift")
    selected_resources = selected["resources"]
    require(spec["resources"] == {key: selected_resources[key] for key in ("resource_tier", "mem_gb", "cores")}, "resource drift from selected protocol option")
    route_checks = _route_audit(spec["route"], spec["reference_family"])
    require(all(route_checks[key] for key in ("opt", "freq", "stable", "reference")) and not route_checks["forbidden_tokens"], "route is outside reviewed minimum Opt/Freq U/RO stability scope")
    input_text = _render_input(spec, structure)
    document = {
        "schema": SCHEMA_HANDOFF, "handoff_id": handoff_id, "workflow": WORKFLOW, "status": "offline_input_handoff",
        "electronic_state_review": binding(review_file, review),
        "structure_candidate": binding(structure_file, structure),
        "protocol_options": binding(options_file, options, "proposal_payload_sha256"),
        "protocol_selection": binding(selection_file, selection, "selection_payload_sha256"),
        "input_specification": binding(spec_file, spec),
        "state": {"candidate_id": candidate["candidate_id"], "structure_sha256": structure["structure_sha256"], "charge": spec["charge"], "multiplicity": spec["multiplicity"], "reference_family": spec["reference_family"], "state_family": candidate["state_family"]},
        "coordinates": copy.deepcopy(structure["atoms"]), "route": spec["route"], "route_audit": route_checks,
        "resources": copy.deepcopy(spec["resources"]), "server_directory": None, "server_directory_status": "not_created_not_authorized",
        "expected_result": {"normal_termination": True, "stationary_minimum": True, "expected_frequency_count": spec["expected_frequency_count"], "imaginary_frequency_count": 0, "stability": "stable", "reference_family": spec["reference_family"], "s2_policy": copy.deepcopy(wavefunction["spin_contamination_policy"])},
        "input_text": input_text, "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        "calculation_ready": False, "no_submission_authorization": True,
        "authorizations": {"rendered_offline_input_handoff": True, "create_server_directory": False, "gaussian": False, "ssh": False, "pbs": False, "submit": False, "retry": False, "cancel": False, "cleanup": False, "deploy": False},
    }
    document["payload_sha256"] = payload_sha256(document)
    validate_handoff(document, check_sources=False)
    return document


def validate_handoff(document: dict[str, Any], *, check_sources: bool) -> None:
    keys = {"schema", "handoff_id", "workflow", "status", "electronic_state_review", "structure_candidate", "protocol_options", "protocol_selection", "input_specification", "state", "coordinates", "route", "route_audit", "resources", "server_directory", "server_directory_status", "expected_result", "input_text", "input_sha256", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}
    _exact(document, keys, "input handoff")
    require(document["schema"] == SCHEMA_HANDOFF and document["workflow"] == WORKFLOW and document["status"] == "offline_input_handoff", "input handoff schema/workflow/status mismatch")
    _id(document["handoff_id"], "handoff_id")
    for name in ("electronic_state_review", "structure_candidate", "protocol_options", "protocol_selection", "input_specification"):
        validate_binding(document[name], name)
    require(document["server_directory"] is None and document["server_directory_status"] == "not_created_not_authorized", "handoff must not create/bind a server directory")
    require(document["input_sha256"] == hashlib.sha256(document["input_text"].encode("utf-8")).hexdigest(), "handoff input hash mismatch")
    checks = _route_audit(document["route"], document["state"]["reference_family"])
    require(document["route_audit"] == checks and all(checks[key] for key in ("opt", "freq", "stable", "reference")) and not checks["forbidden_tokens"], "handoff route audit drift")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "handoff authority boundary changed")
    require(document["authorizations"] == {"rendered_offline_input_handoff": True, "create_server_directory": False, "gaussian": False, "ssh": False, "pbs": False, "submit": False, "retry": False, "cancel": False, "cleanup": False, "deploy": False}, "handoff authorization boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "handoff payload hash mismatch")
    if check_sources:
        review_path = document["electronic_state_review"]["path"]
        structure_path = document["structure_candidate"]["path"]
        selection_path = document["protocol_selection"]["path"]
        spec_path = document["input_specification"]["path"]
        rebuilt = build_handoff(review_path, structure_path, selection_path, spec_path, document["handoff_id"])
        require(rebuilt == document, "handoff differs from deterministic bound-source reconstruction")


def load_handoff(path: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved, document = load(path, "input handoff", canonical=True)
    validate_handoff(document, check_sources=True)
    return resolved, document


def _parse_input(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    route_lines = [line.strip() for line in lines if line.lstrip().startswith("#")]
    require(len(route_lines) == 1, "input must contain exactly one route card")
    state_indices = [index for index, line in enumerate(lines) if re.fullmatch(r"\s*-?\d+\s+\d+\s*", line)]
    require(len(state_indices) == 1, "input must contain exactly one charge/multiplicity line")
    state_index = state_indices[0]
    charge, multiplicity = (int(value) for value in lines[state_index].split())
    coordinates = []
    for line in lines[state_index + 1:]:
        if not line.strip():
            break
        match = COORD_RE.fullmatch(line)
        require(match is not None, f"invalid Cartesian line in handoff: {line!r}")
        coordinates.append({"index": len(coordinates) + 1, "element": match.group(1), "x_angstrom": float(match.group(2)), "y_angstrom": float(match.group(3)), "z_angstrom": float(match.group(4))})
    require(coordinates, "input contains no Cartesian coordinates")
    mem = [line for line in lines if line.lower().startswith("%mem=")]
    cores = [line for line in lines if line.lower().startswith("%nprocshared=")]
    checkpoints = [line for line in lines if line.lower().startswith("%chk=")]
    require(len(mem) == len(cores) == len(checkpoints) == 1, "input Link 0 directives are incomplete or duplicated")
    return {"route": route_lines[0], "charge": charge, "multiplicity": multiplicity, "coordinates": coordinates, "mem": mem[0].split("=", 1)[1], "cores": int(cores[0].split("=", 1)[1]), "checkpoint": checkpoints[0].split("=", 1)[1], "trailing_blank_line": text.endswith("\n\n")}


def build_input_audit(handoff_path: str | Path, audit_id: str) -> dict[str, Any]:
    _id(audit_id, "audit_id")
    handoff_file, handoff = load_handoff(handoff_path)
    parsed = _parse_input(handoff["input_text"])
    checks = {
        "input_hash": handoff["input_sha256"] == hashlib.sha256(handoff["input_text"].encode()).hexdigest(),
        "charge": parsed["charge"] == handoff["state"]["charge"], "multiplicity": parsed["multiplicity"] == handoff["state"]["multiplicity"],
        "reference": _route_audit(parsed["route"], handoff["state"]["reference_family"])["reference"],
        "stability": _route_audit(parsed["route"], handoff["state"]["reference_family"])["stable"],
        "minimum_opt_freq": _route_audit(parsed["route"], handoff["state"]["reference_family"])["opt"] and _route_audit(parsed["route"], handoff["state"]["reference_family"])["freq"] and not _route_audit(parsed["route"], handoff["state"]["reference_family"])["forbidden_tokens"],
        "atom_order_coordinates": parsed["coordinates"] == handoff["coordinates"], "resources": parsed["mem"] == f"{handoff['resources']['mem_gb']}GB" and parsed["cores"] == handoff["resources"]["cores"],
        "server_directory_absent": handoff["server_directory"] is None, "trailing_blank_line": parsed["trailing_blank_line"],
    }
    document = {"schema": SCHEMA_AUDIT, "audit_id": audit_id, "workflow": WORKFLOW, "status": "passed" if all(checks.values()) else "blocked", "handoff": binding(handoff_file, handoff), "input_sha256": handoff["input_sha256"], "parsed": parsed, "checks": checks, "calculation_ready": False, "no_submission_authorization": True}
    document["payload_sha256"] = payload_sha256(document)
    validate_input_audit(document, check_sources=False)
    require(document["status"] == "passed", "input audit blocked")
    return document


def validate_input_audit(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "audit_id", "workflow", "status", "handoff", "input_sha256", "parsed", "checks", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "input audit")
    require(document["schema"] == SCHEMA_AUDIT and document["workflow"] == WORKFLOW and document["status"] in {"passed", "blocked"}, "input audit identity invalid")
    validate_binding(document["handoff"], "input audit handoff")
    require(isinstance(document["checks"], dict) and document["checks"] and all(isinstance(value, bool) for value in document["checks"].values()), "input audit checks invalid")
    require(document["status"] == ("passed" if all(document["checks"].values()) else "blocked"), "input audit status/check mismatch")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "input audit authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "input audit payload hash mismatch")
    if check_sources:
        rebuilt = build_input_audit(document["handoff"]["path"], document["audit_id"])
        require(rebuilt == document, "input audit differs from deterministic reconstruction")


def validate_result_binding(document: dict[str, Any]) -> None:
    _exact(document, {"schema", "result_id", "handoff", "input_sha256", "result_source", "transport_claim", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "result source binding")
    require(document["schema"] == SCHEMA_RESULT_BINDING, "result binding schema mismatch")
    _id(document["result_id"], "result_id")
    validate_binding(document["handoff"], "result binding handoff")
    _sha(document["input_sha256"], "bound input hash")
    result = _exact(document["result_source"], {"path", "sha256"}, "result source")
    _text(result["path"], "result source path"); _sha(result["sha256"], "result source hash")
    require(document["transport_claim"] == "supplied_offline_source_binding_only", "result binding must not claim execution provenance")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "result binding authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "result binding payload hash mismatch")


def build_result_observation(binding_path: str | Path, observation_id: str) -> dict[str, Any]:
    _id(observation_id, "observation_id")
    binding_file, source_binding = load(binding_path, "result source binding", canonical=True)
    validate_result_binding(source_binding)
    handoff_file, handoff = load_handoff(source_binding["handoff"]["path"])
    require(binding(handoff_file, handoff) == source_binding["handoff"], "result binding handoff drift")
    require(source_binding["input_sha256"] == handoff["input_sha256"], "result-to-input hash lineage mismatch")
    result_path = Path(source_binding["result_source"]["path"]).expanduser()
    if not result_path.is_absolute():
        result_path = binding_file.parent / result_path
    result_path = result_path.resolve()
    require(result_path.is_file() and file_sha256(result_path) == source_binding["result_source"]["sha256"], "result source hash mismatch")
    parsed = state.build_observation(result_path, observation_id)
    document = {"schema": SCHEMA_RESULT_OBSERVATION, "observation_id": observation_id, "workflow": WORKFLOW, "observation_status": parsed["observation_status"], "result_source_binding": binding(binding_file, source_binding), "handoff": binding(handoff_file, handoff), "input_sha256": handoff["input_sha256"], "result_source": {"path": portable(result_path), "sha256": file_sha256(result_path)}, "parser": "auto-g16-main-group-open-shell-minimum-result-observer/1", "facts": parsed["facts"], "scientific_acceptance": False, "calculation_ready": False, "no_submission_authorization": True}
    document["payload_sha256"] = payload_sha256(document)
    validate_result_observation(document, check_sources=False)
    return document


def validate_result_observation(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "observation_id", "workflow", "observation_status", "result_source_binding", "handoff", "input_sha256", "result_source", "parser", "facts", "scientific_acceptance", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "result observation")
    require(document["schema"] == SCHEMA_RESULT_OBSERVATION and document["workflow"] == WORKFLOW, "result observation identity mismatch")
    validate_binding(document["result_source_binding"], "result source binding"); validate_binding(document["handoff"], "result observation handoff")
    require(document["parser"] == "auto-g16-main-group-open-shell-minimum-result-observer/1", "result parser version mismatch")
    require(document["scientific_acceptance"] is False and document["calculation_ready"] is False and document["no_submission_authorization"] is True, "result observation authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "result observation payload hash mismatch")
    if check_sources:
        rebuilt = build_result_observation(document["result_source_binding"]["path"], document["observation_id"])
        require(rebuilt == document, "result observation differs from deterministic reconstruction")


def build_continuity(audit_path: str | Path, observation_path: str | Path, continuity_id: str) -> dict[str, Any]:
    _id(continuity_id, "continuity_id")
    audit_file, audit = load(audit_path, "input audit", canonical=True); validate_input_audit(audit, check_sources=True)
    observation_file, observation = load(observation_path, "result observation", canonical=True); validate_result_observation(observation, check_sources=True)
    handoff_file, handoff = load_handoff(audit["handoff"]["path"])
    facts = observation["facts"]; expected = handoff["expected_result"]; spin = facts["spin"]
    after = spin["s2_after_annihilation"]; s2_policy = expected["s2_policy"]
    checks = {
        "input_audit_passed": audit["status"] == "passed", "same_handoff": observation["handoff"] == binding(handoff_file, handoff),
        "input_hash_lineage": observation["input_sha256"] == audit["input_sha256"] == handoff["input_sha256"],
        "normal_termination": facts["termination"]["normal"], "optimization_stationary": facts["optimization"]["stationary_point_found"], "scf_converged": facts["scf"]["converged"],
        "state": facts["state"] == {"charge": handoff["state"]["charge"], "multiplicity": handoff["state"]["multiplicity"]},
        "reference": facts["scf"]["reference_family"] == expected["reference_family"], "stability": facts["stability"] == {"performed": True, "status": "stable"},
        "s2_present": spin["s2_before_annihilation"] is not None and after is not None,
        "s2_within_policy": after is not None and abs(after - float(s2_policy["target_s2"])) <= float(s2_policy["max_abs_deviation"]),
        "frequency_count": facts["frequencies"]["count"] == expected["expected_frequency_count"], "minimum_frequencies": facts["frequencies"]["imaginary_count"] == 0,
        "v1_state_scope": handoff["state"]["multiplicity"] in {2, 3} and handoff["state"]["state_family"] in state.SUPPORTED_STATE_FAMILIES,
    }
    accepted = all(checks.values())
    document = {"schema": SCHEMA_CONTINUITY, "continuity_id": continuity_id, "workflow": WORKFLOW, "status": "accepted" if accepted else "blocked", "decision": "accepted_for_v1_minimum_evidence" if accepted else "blocked", "input_audit": binding(audit_file, audit), "result_observation": binding(observation_file, observation), "handoff": binding(handoff_file, handoff), "lineage": {"candidate_id": handoff["state"]["candidate_id"], "state_review_payload_sha256": handoff["electronic_state_review"]["payload_sha256"], "protocol_selection_payload_sha256": handoff["protocol_selection"]["payload_sha256"], "input_handoff_payload_sha256": handoff["payload_sha256"], "input_sha256": handoff["input_sha256"], "result_sha256": observation["result_source"]["sha256"]}, "checks": checks, "calculation_ready": False, "no_submission_authorization": True, "authorizations": {"promote_evidence": False, "render_new_input": False, "gaussian": False, "ssh": False, "pbs": False, "submit": False, "retry": False, "cancel": False, "cleanup": False, "deploy": False}}
    document["payload_sha256"] = payload_sha256(document)
    validate_continuity(document, check_sources=False)
    return document


def validate_continuity(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "continuity_id", "workflow", "status", "decision", "input_audit", "result_observation", "handoff", "lineage", "checks", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "result continuity")
    require(document["schema"] == SCHEMA_CONTINUITY and document["workflow"] == WORKFLOW, "result continuity identity mismatch")
    for name in ("input_audit", "result_observation", "handoff"): validate_binding(document[name], name)
    accepted = all(document["checks"].values())
    require((document["status"], document["decision"]) == (("accepted", "accepted_for_v1_minimum_evidence") if accepted else ("blocked", "blocked")), "result continuity status/check mismatch")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "result continuity authority boundary changed")
    require(all(value is False for value in document["authorizations"].values()), "result continuity must not authorize downstream/live actions")
    require(document["payload_sha256"] == payload_sha256(document), "result continuity payload hash mismatch")
    if check_sources:
        rebuilt = build_continuity(document["input_audit"]["path"], document["result_observation"]["path"], document["continuity_id"])
        require(rebuilt == document, "result continuity differs from deterministic reconstruction")


def validate_artifact(path: str | Path) -> dict[str, Any]:
    _, document = load(path, "minimum Opt/Freq artifact", canonical=True)
    validators = {SCHEMA_STRUCTURE: lambda value: validate_structure(value), SCHEMA_SPEC: lambda value: validate_spec(value), SCHEMA_HANDOFF: lambda value: validate_handoff(value, check_sources=True), SCHEMA_AUDIT: lambda value: validate_input_audit(value, check_sources=True), SCHEMA_RESULT_BINDING: lambda value: validate_result_binding(value), SCHEMA_RESULT_OBSERVATION: lambda value: validate_result_observation(value, check_sources=True), SCHEMA_CONTINUITY: lambda value: validate_continuity(value, check_sources=True)}
    require(document.get("schema") in validators, "unknown minimum Opt/Freq artifact schema")
    validators[document["schema"]](document)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    handoff = sub.add_parser("handoff"); handoff.add_argument("review"); handoff.add_argument("structure"); handoff.add_argument("selection"); handoff.add_argument("--specification", required=True); handoff.add_argument("--handoff-id", required=True); handoff.add_argument("--output", required=True)
    audit = sub.add_parser("audit-input"); audit.add_argument("handoff"); audit.add_argument("--audit-id", required=True); audit.add_argument("--output", required=True)
    observe = sub.add_parser("observe-result"); observe.add_argument("binding"); observe.add_argument("--observation-id", required=True); observe.add_argument("--output", required=True)
    accept = sub.add_parser("accept-result"); accept.add_argument("audit"); accept.add_argument("observation"); accept.add_argument("--continuity-id", required=True); accept.add_argument("--output", required=True)
    validate = sub.add_parser("validate"); validate.add_argument("artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "handoff": document = build_handoff(args.review, args.structure, args.selection, args.specification, args.handoff_id)
        elif args.command == "audit-input": document = build_input_audit(args.handoff, args.audit_id)
        elif args.command == "observe-result": document = build_result_observation(args.binding, args.observation_id)
        elif args.command == "accept-result": document = build_continuity(args.audit, args.observation, args.continuity_id)
        else:
            document = validate_artifact(args.artifact)
            print(json.dumps({"valid": True, "schema": document["schema"], "status": document.get("status"), "live_actions": False}, ensure_ascii=False)); return 0
        state.write_new_json(args.output, document)
        print(json.dumps({"valid": True, "schema": document["schema"], "status": document.get("status", document.get("observation_status")), "live_actions": False}, ensure_ascii=False)); return 0
    except (ContractError, state.ContractError, protocol.ContractError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
