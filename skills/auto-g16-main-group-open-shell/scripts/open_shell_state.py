#!/usr/bin/env python3
"""Offline main-group open-shell electronic-state review and result acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SCHEMA_REVIEW = "auto-g16-main-group-open-shell-review/1"
SCHEMA_OBSERVATION = "auto-g16-main-group-open-shell-observation/1"
SCHEMA_ACCEPTANCE = "auto-g16-main-group-open-shell-result-acceptance/1"
SUPPORTED_STATE_FAMILIES = {
    "doublet_ground_state",
    "high_spin_triplet_ground_state",
    "triplet_carbene",
}
ALL_STATE_FAMILIES = SUPPORTED_STATE_FAMILIES | {
    "closed_shell_singlet",
    "open_shell_singlet",
    "broken_symmetry_singlet",
    "excited_state",
    "multireference_state",
    "spin_crossing_state",
}
MAIN_GROUP_SYMBOLS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "Tl", "Pb", "Bi", "Po",
    "At", "Rn", "Fr", "Ra", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
}
ELEMENTS = (
    "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)
ATOMIC_NUMBERS = {symbol: number for number, symbol in enumerate(ELEMENTS) if symbol}
REQUIRED_ACCEPTANCE_CHECKS = [
    "review_accepted",
    "normal_termination",
    "scf_converged",
    "state_identity",
    "reference_family",
    "stability",
    "s2_present",
    "s2_within_policy",
    "stationary_minimum",
    "frequencies_complete",
    "no_imaginary_frequencies",
    "single_reference_scope",
]


class ContractError(ValueError):
    """Fail-closed contract error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _reject_constant(token: str) -> None:
    raise ContractError(f"non-finite/non-standard JSON constant is forbidden: {token}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def payload_sha256(value: dict[str, Any], field: str = "payload_sha256") -> str:
    return hashlib.sha256(canonical_bytes({key: item for key, item in value.items() if key != field})).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_symlink_path(path: Path, label: str) -> Path:
    """Reject the leaf or any existing ancestor symlink before resolving."""
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        require(not component.is_symlink(), f"{label} path contains a symlink: {component}")
    return absolute


def _input_path(path: str | Path, label: str) -> Path:
    raw = _reject_symlink_path(Path(path).expanduser(), label)
    resolved = raw.resolve()
    require(resolved.is_file(), f"{label} must be an existing regular file")
    return resolved


def portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def load_json(path: str | Path, *, canonical: bool = False, label: str = "JSON artifact") -> tuple[Path, dict[str, Any]]:
    resolved = _input_path(path, label)
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot parse {label}: {exc}") from exc
    require(isinstance(value, dict), f"{label} root must be an object")
    _finite_tree(value)
    if canonical:
        require(raw == canonical_bytes(value), f"{label} must use canonical JSON encoding")
    return resolved, value


def write_new_json(path: str | Path, value: dict[str, Any]) -> Path:
    raw = _reject_symlink_path(Path(path).expanduser(), "output")
    require(not raw.exists(), f"refusing to overwrite existing output: {raw}")
    raw.parent.mkdir(parents=True, exist_ok=True)
    try:
        with raw.open("xb") as handle:
            handle.write(canonical_bytes(value))
    except FileExistsError as exc:
        raise ContractError(f"refusing to overwrite existing output: {raw}") from exc
    return raw.resolve()


def _finite_tree(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        require(math.isfinite(value), f"{path}: non-finite number is forbidden")
    elif isinstance(value, dict):
        for key, child in value.items():
            _finite_tree(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _finite_tree(child, f"{path}[{index}]")


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    actual = set(value)
    require(actual == keys, f"{label} fields mismatch; missing={sorted(keys-actual)} unknown={sorted(actual-keys)}")
    return value


def _text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    return value.strip()


def _integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    if minimum is not None:
        require(value >= minimum, f"{label} must be at least {minimum}")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    number = float(value)
    require(math.isfinite(number), f"{label} must be finite")
    if minimum is not None:
        require(number >= minimum, f"{label} must be at least {minimum}")
    return number


def _string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list) and (not nonempty or value), f"{label} must be an array")
    for index, item in enumerate(value):
        _text(item, f"{label}[{index}]")
    return value


def validate_candidate(candidate: dict[str, Any]) -> None:
    _exact(candidate, {"schema", "candidate_id", "structure_sha256", "atoms", "charge", "multiplicity", "state_family", "electronic_scope", "structure_role", "task_types", "calculation_ready", "no_submission_authorization"}, "candidate")
    require(candidate["schema"] == "auto-g16-main-group-open-shell-candidate/1", "candidate schema mismatch")
    require(ID_RE.fullmatch(str(candidate["candidate_id"])) is not None, "invalid candidate_id")
    require(SHA_RE.fullmatch(str(candidate["structure_sha256"])) is not None, "invalid structure_sha256")
    atoms = candidate["atoms"]
    require(isinstance(atoms, list) and atoms, "candidate.atoms must be non-empty")
    for expected, atom in enumerate(atoms, 1):
        _exact(atom, {"index", "element"}, f"candidate.atoms[{expected-1}]")
        require(atom["index"] == expected, "candidate atom indices must be contiguous and one-based")
        require(atom["element"] in ATOMIC_NUMBERS, f"unknown element: {atom['element']}")
    _integer(candidate["charge"], "candidate.charge")
    _integer(candidate["multiplicity"], "candidate.multiplicity", minimum=1)
    require(candidate["state_family"] in ALL_STATE_FAMILIES, "candidate state_family is unknown")
    require(candidate["electronic_scope"] in {"single_reference_ground_state", "broken_symmetry", "multireference", "excited_state", "spin_crossing"}, "candidate electronic_scope is unknown")
    require(candidate["structure_role"] in {"minimum", "transition_state", "irc_endpoint", "mecp"}, "candidate structure_role is unknown")
    _string_list(candidate["task_types"], "candidate.task_types", nonempty=True)
    require(candidate["calculation_ready"] is False, "candidate calculation_ready must be false")
    require(candidate["no_submission_authorization"] is True, "candidate must not authorize submission")


def validate_review_source(source: dict[str, Any]) -> None:
    _exact(source, {"schema", "review_id", "credible_multiplicities", "wavefunction_reference", "stability_required", "expected_frequency_count", "spin_contamination_policy", "alternative_solutions", "multireference_risk", "reviewer_decision", "calculation_ready", "no_submission_authorization"}, "review source")
    require(source["schema"] == "auto-g16-main-group-open-shell-review-source/1", "review source schema mismatch")
    require(ID_RE.fullmatch(str(source["review_id"])) is not None, "invalid review_id")
    multiplicities = source["credible_multiplicities"]
    require(isinstance(multiplicities, list) and multiplicities, "credible_multiplicities must be non-empty")
    require(len(multiplicities) == len(set(multiplicities)), "credible_multiplicities must be unique")
    for item in multiplicities:
        _integer(item, "credible multiplicity", minimum=1)
    require(source["wavefunction_reference"] in {"U", "RO"}, "wavefunction reference must be U or RO")
    require(isinstance(source["stability_required"], bool), "stability_required must be boolean")
    _integer(source["expected_frequency_count"], "expected_frequency_count", minimum=1)
    policy = _exact(source["spin_contamination_policy"], {"metric", "target_s2", "max_abs_deviation", "missing_diagnostic"}, "spin contamination policy")
    require(policy["metric"] == "post_annihilation_absolute_s2_deviation", "unsupported S2 metric")
    _number(policy["target_s2"], "target_s2", minimum=0)
    _number(policy["max_abs_deviation"], "max_abs_deviation", minimum=0)
    require(policy["missing_diagnostic"] == "block", "missing S2 diagnostic must block")
    alternatives = source["alternative_solutions"]
    require(isinstance(alternatives, list) and alternatives, "alternative_solutions must be non-empty")
    for index, alternative in enumerate(alternatives):
        _exact(alternative, {"multiplicity", "state_family", "disposition", "evidence"}, f"alternative_solutions[{index}]")
        _integer(alternative["multiplicity"], "alternative multiplicity", minimum=1)
        require(alternative["state_family"] in ALL_STATE_FAMILIES, "alternative state family is unknown")
        require(alternative["disposition"] in {"lower_priority", "excluded_by_evidence", "requires_escalation"}, "alternative disposition is unknown")
        _text(alternative["evidence"], "alternative evidence")
    risk = _exact(source["multireference_risk"], {"level", "evidence", "action"}, "multireference_risk")
    require(risk["level"] in {"low", "moderate", "high", "unresolved"}, "multireference risk level is unknown")
    _string_list(risk["evidence"], "multireference evidence", nonempty=True)
    require(risk["action"] in {"accept_single_reference", "escalate", "reject"}, "multireference action is unknown")
    decision = _exact(source["reviewer_decision"], {"decision", "rationale", "confirmed"}, "reviewer_decision")
    require(decision["decision"] in {"accepted_for_v1_protocol_gate", "blocked", "rejected"}, "review decision is unknown")
    _text(decision["rationale"], "review rationale")
    require(decision["confirmed"] is True, "reviewer decision must be explicitly confirmed")
    require(source["calculation_ready"] is False and source["no_submission_authorization"] is True, "review source authority boundary changed")


def _state_blockers(candidate: dict[str, Any], source: dict[str, Any], electron_count: int, target_s2: float) -> list[str]:
    reasons: list[str] = []
    multiplicity = candidate["multiplicity"]
    if any(atom["element"] not in MAIN_GROUP_SYMBOLS for atom in candidate["atoms"]):
        reasons.append("metal_or_non_main_group_element")
    if electron_count <= 0:
        reasons.append("nonpositive_electron_count")
    if (electron_count % 2) == (multiplicity % 2):
        reasons.append("electron_parity_multiplicity_mismatch")
    if multiplicity not in source["credible_multiplicities"]:
        reasons.append("multiplicity_not_in_credible_set")
    if candidate["state_family"] not in SUPPORTED_STATE_FAMILIES:
        reasons.append("state_family_outside_v1")
    if multiplicity not in {2, 3}:
        reasons.append("multiplicity_outside_doublet_triplet_v1")
    if candidate["state_family"] == "doublet_ground_state" and multiplicity != 2:
        reasons.append("doublet_state_multiplicity_mismatch")
    if candidate["state_family"] in {"high_spin_triplet_ground_state", "triplet_carbene"} and multiplicity != 3:
        reasons.append("triplet_state_multiplicity_mismatch")
    if candidate["electronic_scope"] != "single_reference_ground_state":
        reasons.append("electronic_scope_outside_single_reference_ground_state")
    if candidate["structure_role"] != "minimum":
        reasons.append("structure_role_outside_minimum")
    if candidate["task_types"] != ["optimization", "frequency"]:
        reasons.append("task_scope_outside_minimum_opt_freq")
    if source["stability_required"] is not True:
        reasons.append("stability_test_not_required")
    expected_s2 = ((multiplicity - 1) / 2) * (((multiplicity - 1) / 2) + 1)
    if not math.isclose(target_s2, expected_s2, rel_tol=0, abs_tol=1e-12):
        reasons.append("target_s2_mismatch")
    risk = source["multireference_risk"]
    if risk["level"] != "low" or risk["action"] != "accept_single_reference":
        reasons.append("multireference_risk_unresolved_or_material")
    return reasons


def build_review(candidate_path: str | Path, source_path: str | Path) -> dict[str, Any]:
    candidate_file, candidate = load_json(candidate_path, label="candidate")
    source_file, source = load_json(source_path, label="review source")
    validate_candidate(candidate)
    validate_review_source(source)
    atomic_sum = sum(ATOMIC_NUMBERS[atom["element"]] for atom in candidate["atoms"])
    electron_count = atomic_sum - candidate["charge"]
    multiplicity = candidate["multiplicity"]
    spin = (multiplicity - 1) / 2
    expected_s2 = spin * (spin + 1)
    target_s2 = float(source["spin_contamination_policy"]["target_s2"])
    blockers = _state_blockers(candidate, source, electron_count, target_s2)
    decision = source["reviewer_decision"]["decision"]
    if decision == "accepted_for_v1_protocol_gate":
        require(not blockers, f"review cannot accept blocked state: {', '.join(blockers)}")
    elif not blockers:
        blockers.append("reviewer_explicitly_withheld_acceptance")
    elements = sorted({atom["element"] for atom in candidate["atoms"]}, key=lambda item: ATOMIC_NUMBERS[item])
    document = {
        "schema": SCHEMA_REVIEW,
        "review_id": source["review_id"],
        "status": "accepted" if decision == "accepted_for_v1_protocol_gate" else "blocked",
        "candidate_source": {"path": portable_path(candidate_file), "sha256": file_sha256(candidate_file)},
        "review_source": {"path": portable_path(source_file), "sha256": file_sha256(source_file)},
        "candidate_snapshot": candidate,
        "atom_inventory": {"atoms": candidate["atoms"], "elements": elements, "atomic_number_sum": atomic_sum},
        "electron_accounting": {
            "charge": candidate["charge"],
            "electron_count": electron_count,
            "electron_parity": "even" if electron_count % 2 == 0 else "odd",
            "multiplicity": multiplicity,
            "multiplicity_parity_consistent": (electron_count % 2) != (multiplicity % 2),
        },
        "credible_multiplicities": source["credible_multiplicities"],
        "state_assessment": {
            "state_family": candidate["state_family"],
            "electronic_scope": candidate["electronic_scope"],
            "structure_role": candidate["structure_role"],
            "task_types": candidate["task_types"],
            "expected_frequency_count": source["expected_frequency_count"],
            "v1_classification": "supported_single_reference_minimum" if not blockers else "outside_or_blocked_v1",
        },
        "wavefunction_policy": {
            "reference": source["wavefunction_reference"],
            "stability_required": source["stability_required"],
            "target_spin": spin,
            "target_s2": expected_s2,
            "spin_contamination_policy": source["spin_contamination_policy"],
        },
        "alternative_solutions": source["alternative_solutions"],
        "multireference_risk": source["multireference_risk"],
        "conclusion": {"decision": decision, "reasons": blockers or ["all_v1_electronic_state_checks_satisfied"], "confirmed": True},
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    document["payload_sha256"] = payload_sha256(document)
    validate_review(document, check_sources=False)
    return document


def validate_review(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "review_id", "status", "candidate_source", "review_source", "candidate_snapshot", "atom_inventory", "electron_accounting", "credible_multiplicities", "state_assessment", "wavefunction_policy", "alternative_solutions", "multireference_risk", "conclusion", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "electronic-state review")
    require(document["schema"] == SCHEMA_REVIEW, "review schema mismatch")
    require(document["status"] in {"accepted", "blocked"}, "review status invalid")
    require(SHA_RE.fullmatch(str(document["payload_sha256"])) is not None and document["payload_sha256"] == payload_sha256(document), "review payload hash mismatch")
    validate_candidate(document["candidate_snapshot"])
    candidate = document["candidate_snapshot"]
    candidate_source = _exact(document["candidate_source"], {"path", "sha256"}, "candidate_source")
    review_source = _exact(document["review_source"], {"path", "sha256"}, "review_source")
    for binding, label in ((candidate_source, "candidate source"), (review_source, "review source")):
        _text(binding["path"], f"{label} path")
        require(SHA_RE.fullmatch(str(binding["sha256"])) is not None, f"{label} hash invalid")
    if check_sources:
        candidate_path, bound_candidate = load_json(candidate_source["path"], label="bound candidate")
        source_path, source = load_json(review_source["path"], label="bound review source")
        require(file_sha256(candidate_path) == candidate_source["sha256"] and bound_candidate == candidate, "review candidate binding mismatch")
        require(file_sha256(source_path) == review_source["sha256"], "review source hash mismatch")
        validate_review_source(source)
        rebuilt = build_review(candidate_path, source_path)
        require(rebuilt == document, "review differs from deterministic bound-source reconstruction")
    inventory = _exact(document["atom_inventory"], {"atoms", "elements", "atomic_number_sum"}, "atom_inventory")
    require(inventory["atoms"] == candidate["atoms"], "review atom inventory drift")
    expected_elements = sorted({atom["element"] for atom in candidate["atoms"]}, key=lambda item: ATOMIC_NUMBERS[item])
    expected_sum = sum(ATOMIC_NUMBERS[atom["element"]] for atom in candidate["atoms"])
    require(inventory["elements"] == expected_elements and inventory["atomic_number_sum"] == expected_sum, "review element/electron inventory drift")
    accounting = _exact(document["electron_accounting"], {"charge", "electron_count", "electron_parity", "multiplicity", "multiplicity_parity_consistent"}, "electron_accounting")
    electrons = expected_sum - candidate["charge"]
    require(accounting == {"charge": candidate["charge"], "electron_count": electrons, "electron_parity": "even" if electrons % 2 == 0 else "odd", "multiplicity": candidate["multiplicity"], "multiplicity_parity_consistent": (electrons % 2) != (candidate["multiplicity"] % 2)}, "electron accounting mismatch")
    assessment = _exact(document["state_assessment"], {"state_family", "electronic_scope", "structure_role", "task_types", "expected_frequency_count", "v1_classification"}, "state_assessment")
    _integer(assessment["expected_frequency_count"], "review expected_frequency_count", minimum=1)
    wf = _exact(document["wavefunction_policy"], {"reference", "stability_required", "target_spin", "target_s2", "spin_contamination_policy"}, "wavefunction_policy")
    require(wf["reference"] in {"U", "RO"} and wf["stability_required"] is True, "review wavefunction policy is not V1-safe")
    _number(wf["target_spin"], "target_spin", minimum=0)
    _number(wf["target_s2"], "target_s2", minimum=0)
    policy = _exact(wf["spin_contamination_policy"], {"metric", "target_s2", "max_abs_deviation", "missing_diagnostic"}, "review S2 policy")
    require(policy["metric"] == "post_annihilation_absolute_s2_deviation" and policy["missing_diagnostic"] == "block", "review S2 policy changed")
    _number(policy["max_abs_deviation"], "max_abs_deviation", minimum=0)
    risk = _exact(document["multireference_risk"], {"level", "evidence", "action"}, "review multireference risk")
    _string_list(risk["evidence"], "multireference evidence", nonempty=True)
    conclusion = _exact(document["conclusion"], {"decision", "reasons", "confirmed"}, "review conclusion")
    _string_list(conclusion["reasons"], "review reasons", nonempty=True)
    require(conclusion["confirmed"] is True, "review conclusion must be confirmed")
    accepted = conclusion["decision"] == "accepted_for_v1_protocol_gate"
    require(document["status"] == ("accepted" if accepted else "blocked"), "review status/decision mismatch")
    if accepted:
        require(document["state_assessment"]["v1_classification"] == "supported_single_reference_minimum", "accepted review is outside V1 classification")
        require(risk["level"] == "low" and risk["action"] == "accept_single_reference", "accepted review has unresolved multireference risk")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "review authority boundary changed")


def load_validated_review(path: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved, document = load_json(path, canonical=True, label="electronic-state review")
    validate_review(document, check_sources=True)
    return resolved, document


def _last_float(matches: list[str]) -> float | None:
    return float(matches[-1].replace("D", "E")) if matches else None


def build_observation(log_path: str | Path, observation_id: str) -> dict[str, Any]:
    require(ID_RE.fullmatch(observation_id) is not None, "invalid observation_id")
    log_file = _input_path(log_path, "Gaussian result text")
    text = log_file.read_text(encoding="utf-8", errors="replace")
    state_matches = re.findall(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text, flags=re.I)
    scf_matches = re.findall(r"SCF Done:\s+E\(([^)]+)\)\s*=\s*([-+0-9.DEe]+)", text, flags=re.I)
    s2_matches = re.findall(r"S\*\*2\s+before annihilation\s*([-+0-9.DEe]+),\s*after\s*([-+0-9.DEe]+)", text, flags=re.I)
    harmonic_frequency_lines = re.findall(
        r"(?im)^\s*Frequencies\s+--(?!-)\s*([^\r\n]+)$",
        text,
    )
    frequency_values = [
        float(token.replace("D", "E"))
        for line in harmonic_frequency_lines
        for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEe][-+]?\d+)?", line)
    ]
    method = scf_matches[-1][0].strip() if scf_matches else None
    reference = None
    if method:
        upper = method.upper()
        reference = "RO" if upper.startswith("RO") else "U" if upper.startswith("U") else "R" if upper.startswith("R") else "unknown"
    stable = bool(re.search(r"wavefunction is stable under the perturbations considered", text, flags=re.I))
    unstable = bool(re.search(r"wavefunction (?:has|is).*instabil|internal instability", text, flags=re.I))
    stability_status = "unstable" if unstable else "stable" if stable else "missing"
    charge = int(state_matches[-1][0]) if state_matches else None
    multiplicity = int(state_matches[-1][1]) if state_matches else None
    s2_before = _last_float([item[0] for item in s2_matches])
    s2_after = _last_float([item[1] for item in s2_matches])
    normal_count = len(re.findall(r"Normal termination of Gaussian", text, flags=re.I))
    error_count = len(re.findall(r"Error termination", text, flags=re.I))
    facts = {
        "state": {"charge": charge, "multiplicity": multiplicity},
        "scf": {"converged": bool(scf_matches), "method": method, "reference_family": reference, "energy_hartree": float(scf_matches[-1][1].replace("D", "E")) if scf_matches else None},
        "termination": {"normal_count": normal_count, "error_count": error_count, "normal": normal_count > 0 and error_count == 0},
        "optimization": {"stationary_point_found": bool(re.search(r"Stationary point found", text, flags=re.I))},
        "spin": {"s2_before_annihilation": s2_before, "s2_after_annihilation": s2_after},
        "stability": {"performed": stable or unstable, "status": stability_status},
        "frequencies": {"performed": bool(frequency_values), "values_cm_minus_1": frequency_values, "count": len(frequency_values), "imaginary_count": sum(value < 0 for value in frequency_values)},
    }
    complete = all((charge is not None, multiplicity is not None, facts["scf"]["converged"], facts["termination"]["normal"], facts["optimization"]["stationary_point_found"], s2_before is not None, s2_after is not None, facts["stability"]["performed"], facts["frequencies"]["performed"]))
    document = {
        "schema": SCHEMA_OBSERVATION,
        "observation_id": observation_id,
        "observation_status": "complete" if complete else "incomplete",
        "source": {"path": portable_path(log_file), "sha256": file_sha256(log_file)},
        "parser": "auto-g16-main-group-open-shell-observer/1",
        "facts": facts,
        "scientific_acceptance": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    document["payload_sha256"] = payload_sha256(document)
    validate_observation(document, check_source=True)
    return document


def validate_observation(document: dict[str, Any], *, check_source: bool) -> None:
    _exact(document, {"schema", "observation_id", "observation_status", "source", "parser", "facts", "scientific_acceptance", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "observation")
    require(document["schema"] == SCHEMA_OBSERVATION, "observation schema mismatch")
    require(ID_RE.fullmatch(str(document["observation_id"])) is not None, "invalid observation_id")
    require(document["observation_status"] in {"complete", "incomplete"}, "invalid observation status")
    source = _exact(document["source"], {"path", "sha256"}, "observation source")
    require(SHA_RE.fullmatch(str(source["sha256"])) is not None, "observation source hash invalid")
    if check_source:
        source_path = _input_path(source["path"], "bound Gaussian result text")
        require(file_sha256(source_path) == source["sha256"], "observation source hash mismatch")
    require(document["parser"] == "auto-g16-main-group-open-shell-observer/1", "observation parser version mismatch")
    facts = _exact(document["facts"], {"state", "scf", "termination", "optimization", "spin", "stability", "frequencies"}, "observation facts")
    state = _exact(facts["state"], {"charge", "multiplicity"}, "observed state")
    require(state["charge"] is None or isinstance(state["charge"], int), "observed charge must be integer or null")
    require(state["multiplicity"] is None or (isinstance(state["multiplicity"], int) and state["multiplicity"] >= 1), "observed multiplicity invalid")
    scf = _exact(facts["scf"], {"converged", "method", "reference_family", "energy_hartree"}, "observed SCF")
    require(isinstance(scf["converged"], bool), "SCF convergence flag invalid")
    require(scf["reference_family"] in {None, "U", "RO", "R", "unknown"}, "observed reference family invalid")
    if scf["energy_hartree"] is not None:
        _number(scf["energy_hartree"], "SCF energy")
    termination = _exact(facts["termination"], {"normal_count", "error_count", "normal"}, "termination facts")
    _integer(termination["normal_count"], "normal_count", minimum=0)
    _integer(termination["error_count"], "error_count", minimum=0)
    require(termination["normal"] is (termination["normal_count"] > 0 and termination["error_count"] == 0), "termination summary inconsistent")
    optimization = _exact(facts["optimization"], {"stationary_point_found"}, "optimization facts")
    require(isinstance(optimization["stationary_point_found"], bool), "stationary point flag invalid")
    spin = _exact(facts["spin"], {"s2_before_annihilation", "s2_after_annihilation"}, "spin facts")
    for key in spin:
        if spin[key] is not None:
            _number(spin[key], key, minimum=0)
    stability = _exact(facts["stability"], {"performed", "status"}, "stability facts")
    require(isinstance(stability["performed"], bool) and stability["status"] in {"stable", "unstable", "missing"}, "stability facts invalid")
    require(stability["performed"] is (stability["status"] != "missing"), "stability performed/status mismatch")
    frequencies = _exact(facts["frequencies"], {"performed", "values_cm_minus_1", "count", "imaginary_count"}, "frequency facts")
    require(isinstance(frequencies["performed"], bool) and isinstance(frequencies["values_cm_minus_1"], list), "frequency facts invalid")
    for value in frequencies["values_cm_minus_1"]:
        _number(value, "frequency")
    require(frequencies["count"] == len(frequencies["values_cm_minus_1"]) and frequencies["imaginary_count"] == sum(value < 0 for value in frequencies["values_cm_minus_1"]), "frequency summary inconsistent")
    require(frequencies["performed"] is bool(frequencies["values_cm_minus_1"]), "frequency performed flag inconsistent")
    require(document["scientific_acceptance"] is False and document["calculation_ready"] is False and document["no_submission_authorization"] is True, "observation authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "observation payload hash mismatch")


def load_validated_observation(path: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved, document = load_json(path, canonical=True, label="Gaussian result observation")
    validate_observation(document, check_source=True)
    rebuilt = build_observation(document["source"]["path"], document["observation_id"])
    require(rebuilt == document, "observation differs from deterministic source parse")
    return resolved, document


def validate_acceptance_policy(policy: dict[str, Any]) -> None:
    _exact(policy, {"schema", "policy_id", "decision_rule", "required_checks", "confirmed", "calculation_ready", "no_submission_authorization"}, "acceptance policy")
    require(policy["schema"] == "auto-g16-main-group-open-shell-acceptance-policy/1", "acceptance policy schema mismatch")
    require(ID_RE.fullmatch(str(policy["policy_id"])) is not None, "invalid policy_id")
    require(policy["decision_rule"] in {"accept_if_all_required_checks_pass", "block"}, "acceptance decision rule invalid")
    require(policy["required_checks"] == REQUIRED_ACCEPTANCE_CHECKS, "acceptance policy required checks must match V1")
    require(policy["confirmed"] is True, "acceptance policy must be pre-confirmed")
    require(policy["calculation_ready"] is False and policy["no_submission_authorization"] is True, "acceptance policy authority boundary changed")


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {"check": name, "status": "pass" if passed else "block", "detail": detail}


def build_acceptance(review_path: str | Path, observation_path: str | Path, policy_path: str | Path, acceptance_id: str) -> dict[str, Any]:
    require(ID_RE.fullmatch(acceptance_id) is not None, "invalid acceptance_id")
    review_file, review = load_validated_review(review_path)
    observation_file, observation = load_validated_observation(observation_path)
    policy_file, policy = load_json(policy_path, label="acceptance policy")
    validate_acceptance_policy(policy)
    candidate = review["candidate_snapshot"]
    facts = observation["facts"]
    wf = review["wavefunction_policy"]
    s2_after = facts["spin"]["s2_after_annihilation"]
    s2_present = facts["spin"]["s2_before_annihilation"] is not None and s2_after is not None
    within_s2 = s2_present and abs(float(s2_after) - float(wf["target_s2"])) <= float(wf["spin_contamination_policy"]["max_abs_deviation"])
    checks = [
        _check("review_accepted", review["status"] == "accepted" and review["conclusion"]["decision"] == "accepted_for_v1_protocol_gate", "exact electronic-state review must be accepted"),
        _check("normal_termination", facts["termination"]["normal"], "normal termination with no error termination is required"),
        _check("scf_converged", facts["scf"]["converged"] and facts["scf"]["energy_hartree"] is not None, "SCF Done energy is required"),
        _check("state_identity", facts["state"] == {"charge": candidate["charge"], "multiplicity": candidate["multiplicity"]}, "observed charge/multiplicity must equal reviewed state"),
        _check("reference_family", facts["scf"]["reference_family"] == wf["reference"], "observed U/RO reference must match review"),
        _check("stability", facts["stability"] == {"performed": True, "status": "stable"}, "explicit stable-wavefunction text is required"),
        _check("s2_present", s2_present, "S2 before and after annihilation are both required"),
        _check("s2_within_policy", bool(within_s2), "post-annihilation S2 must be within the reviewed absolute threshold"),
        _check("stationary_minimum", facts["optimization"]["stationary_point_found"], "stationary-point evidence is required"),
        _check("frequencies_complete", facts["frequencies"]["performed"] and facts["frequencies"]["count"] == review["state_assessment"]["expected_frequency_count"], "observed frequency count must exactly match the human-reviewed expectation"),
        _check("no_imaginary_frequencies", facts["frequencies"]["imaginary_count"] == 0, "a V1 minimum must have no imaginary frequencies"),
        _check("single_reference_scope", review["state_assessment"]["v1_classification"] == "supported_single_reference_minimum" and review["multireference_risk"]["level"] == "low", "single-reference V1 scope must remain resolved"),
    ]
    accepted = policy["decision_rule"] == "accept_if_all_required_checks_pass" and all(item["status"] == "pass" for item in checks)
    document = {
        "schema": SCHEMA_ACCEPTANCE,
        "acceptance_id": acceptance_id,
        "status": "accepted" if accepted else "blocked",
        "review_source": {"path": portable_path(review_file), "sha256": file_sha256(review_file), "payload_sha256": review["payload_sha256"]},
        "observation_source": {"path": portable_path(observation_file), "sha256": file_sha256(observation_file), "payload_sha256": observation["payload_sha256"]},
        "policy_source": {"path": portable_path(policy_file), "sha256": file_sha256(policy_file), "policy_id": policy["policy_id"]},
        "checks": checks,
        "decision": "accepted_for_v1_minimum_evidence" if accepted else "blocked",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "authorizations": {"render_input": False, "gaussian": False, "ssh": False, "pbs": False, "submit": False, "retry": False, "cancel": False, "cleanup": False, "deploy": False},
    }
    document["payload_sha256"] = payload_sha256(document)
    validate_acceptance(document, check_sources=False)
    return document


def validate_acceptance(document: dict[str, Any], *, check_sources: bool) -> None:
    _exact(document, {"schema", "acceptance_id", "status", "review_source", "observation_source", "policy_source", "checks", "decision", "calculation_ready", "no_submission_authorization", "authorizations", "payload_sha256"}, "result acceptance")
    require(document["schema"] == SCHEMA_ACCEPTANCE, "acceptance schema mismatch")
    require(document["status"] in {"accepted", "blocked"} and document["decision"] in {"accepted_for_v1_minimum_evidence", "blocked"}, "acceptance status invalid")
    review_binding = _exact(document["review_source"], {"path", "sha256", "payload_sha256"}, "acceptance review source")
    observation_binding = _exact(document["observation_source"], {"path", "sha256", "payload_sha256"}, "acceptance observation source")
    policy_binding = _exact(document["policy_source"], {"path", "sha256", "policy_id"}, "acceptance policy source")
    for binding, label in ((review_binding, "review"), (observation_binding, "observation"), (policy_binding, "policy")):
        require(SHA_RE.fullmatch(str(binding["sha256"])) is not None, f"acceptance {label} file hash invalid")
    require(isinstance(document["checks"], list) and [item.get("check") for item in document["checks"]] == REQUIRED_ACCEPTANCE_CHECKS, "acceptance checks are incomplete or reordered")
    for index, item in enumerate(document["checks"]):
        _exact(item, {"check", "status", "detail"}, f"acceptance checks[{index}]")
        require(item["status"] in {"pass", "block"}, "acceptance check status invalid")
        _text(item["detail"], "acceptance check detail")
    accepted = all(item["status"] == "pass" for item in document["checks"])
    if document["status"] == "accepted":
        require(accepted and document["decision"] == "accepted_for_v1_minimum_evidence", "accepted result has blocked checks")
    else:
        require(document["decision"] == "blocked", "blocked result decision mismatch")
    expected_authorizations = {"render_input": False, "gaussian": False, "ssh": False, "pbs": False, "submit": False, "retry": False, "cancel": False, "cleanup": False, "deploy": False}
    require(document["authorizations"] == expected_authorizations, "acceptance authorization boundary changed")
    require(document["calculation_ready"] is False and document["no_submission_authorization"] is True, "acceptance authority boundary changed")
    require(document["payload_sha256"] == payload_sha256(document), "acceptance payload hash mismatch")
    if check_sources:
        review_path, review = load_validated_review(review_binding["path"])
        observation_path, observation = load_validated_observation(observation_binding["path"])
        policy_path, policy = load_json(policy_binding["path"], label="bound acceptance policy")
        validate_acceptance_policy(policy)
        require(file_sha256(review_path) == review_binding["sha256"] and review["payload_sha256"] == review_binding["payload_sha256"], "acceptance review binding mismatch")
        require(file_sha256(observation_path) == observation_binding["sha256"] and observation["payload_sha256"] == observation_binding["payload_sha256"], "acceptance observation binding mismatch")
        require(file_sha256(policy_path) == policy_binding["sha256"] and policy["policy_id"] == policy_binding["policy_id"], "acceptance policy binding mismatch")
        rebuilt = build_acceptance(review_path, observation_path, policy_path, document["acceptance_id"])
        require(rebuilt == document, "acceptance differs from deterministic bound-source reconstruction")


def validate_artifact(path: str | Path) -> dict[str, Any]:
    _, document = load_json(path, canonical=True, label="open-shell artifact")
    schema = document.get("schema")
    if schema == SCHEMA_REVIEW:
        validate_review(document, check_sources=True)
    elif schema == SCHEMA_OBSERVATION:
        validate_observation(document, check_source=True)
        rebuilt = build_observation(document["source"]["path"], document["observation_id"])
        require(rebuilt == document, "observation differs from deterministic source parse")
    elif schema == SCHEMA_ACCEPTANCE:
        validate_acceptance(document, check_sources=True)
    else:
        raise ContractError("unknown open-shell artifact schema")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review")
    review.add_argument("candidate")
    review.add_argument("--review-source", required=True)
    review.add_argument("--output", required=True)
    observe = sub.add_parser("observe")
    observe.add_argument("log")
    observe.add_argument("--observation-id", required=True)
    observe.add_argument("--output", required=True)
    accept = sub.add_parser("accept")
    accept.add_argument("review")
    accept.add_argument("observation")
    accept.add_argument("--policy", required=True)
    accept.add_argument("--acceptance-id", required=True)
    accept.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "review":
            document = build_review(args.candidate, args.review_source)
            write_new_json(args.output, document)
        elif args.command == "observe":
            document = build_observation(args.log, args.observation_id)
            write_new_json(args.output, document)
        elif args.command == "accept":
            document = build_acceptance(args.review, args.observation, args.policy, args.acceptance_id)
            write_new_json(args.output, document)
        else:
            document = validate_artifact(args.artifact)
        print(json.dumps({"valid": True, "schema": document["schema"], "status": document.get("status", document.get("observation_status")), "live_actions": False}, ensure_ascii=False))
        return 0
    except (ContractError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
