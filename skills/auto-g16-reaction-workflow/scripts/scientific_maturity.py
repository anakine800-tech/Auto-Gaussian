#!/usr/bin/env python3
"""Build and enforce the offline scientific-maturity overlay for TS work.

The overlay is an immutable, hash-bound review of an existing calculation
plan.  It does not edit that plan, render Gaussian input, or authorize live
work.  Other Skills call :func:`assert_action` so the same owner validator
guards TS-family promotion and PBS submission.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


REVIEW_SCHEMA = "gaussian-scientific-maturity-review/1"
GATE_SCHEMA = "gaussian-scientific-maturity-gate/1"
ACTION_AUTHORIZATION_SCHEMA = "gaussian-scientific-action-authorization/1"
PLAN_SCHEMA = "gaussian-reaction-calculation-plan/1"
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")

EVIDENCE_CLASSES = {
    "direct_literature",
    "analogous_literature",
    "user_hypothesis",
    "internal_exploratory_hypothesis",
    "missing_precedent",
}
SEED_KINDS = {"paper", "author", "research_group", "doi", "title", "screenshot", "supporting_information"}
SEED_AUTHORITIES = {"user_hypothesis", "verifiable_seed"}
COVERAGE_LANES = {
    "exact_system",
    "same_catalyst_reaction",
    "same_substrate_class",
    "bph3_hbpin_activation",
    "pyridine_regioselectivity",
    "active_state_ion_pair_lewis_adduct",
    "computational_mechanism_ts_irc_selectivity",
    "backward_citation_chain",
    "forward_citation_chain",
    "fulltext_si_coordinates",
}
STOP_CONDITIONS = {
    "key_literature_unverified",
    "active_state_unresolved",
    "endpoint_not_minimum",
    "low_cost_scan_unsupported",
    "pilot_wrong_imaginary_mode",
    "xtb_or_dft_state_collapse",
    "composition_or_mapping_mismatch",
    "budget_exceeded_without_new_information",
}
TS_KINDS = {"ts_candidate", "ts_freq"}
IRC_KINDS = {"irc_forward", "irc_reverse"}


class MaturityError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaturityError(message)


def _reject_constant(value: str) -> None:
    raise MaturityError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for depth, part in enumerate(absolute.parts[1:], start=1):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) and depth == 1:
            current = current.resolve(strict=True)
            continue
        require(not stat.S_ISLNK(mode), f"artifact path contains a symlink: {current}")
    require(absolute.is_file(), f"JSON artifact is missing: {absolute}")
    try:
        value = json.loads(
            absolute.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaturityError(f"could not read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level JSON must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(value: dict[str, Any]) -> str:
    unhashed = copy.deepcopy(value)
    unhashed.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(unhashed)).hexdigest()


def finalize(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["payload_sha256"] = payload_sha256(result)
    return result


def write_json(path: Path, value: dict[str, Any]) -> None:
    require(path.parent.exists() and path.parent.is_dir(), "output parent must already exist")
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite output: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == keys, f"{label} fields differ: missing={sorted(keys - set(value))}, unknown={sorted(set(value) - keys)}")
    return value


def _identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} must be a stable lowercase ID")
    return value


def _string(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip() == value and bool(value), f"{label} must be a non-empty trimmed string")
    return value


def _string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    result = [_string(item, f"{label}[{index}]") for index, item in enumerate(value)]
    require(len(result) == len(set(result)), f"{label} contains duplicates")
    if nonempty:
        require(bool(result), f"{label} must not be empty")
    return result


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be a lowercase SHA-256")
    return value


def _binding(path: Path, root: Path, schema: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    document = load_json(path)
    resolved = path.absolute().resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        raise MaturityError(f"bound artifact escapes the overlay root: {path}") from None
    require(".." not in relative.parts and not relative.is_absolute(), "bound artifact path must be portable and relative")
    if schema is not None:
        require(document.get("schema") == schema, f"bound artifact schema must be {schema}")
    digest = document.get("payload_sha256")
    _sha(digest, f"{path} payload_sha256")
    return document, {
        "path": relative.as_posix(),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
        "schema": document["schema"],
        "payload_sha256": digest,
    }


def _resolve(binding: Any, owner: Path, expected_schema: str | None = None) -> tuple[dict[str, Any], Path]:
    data = _exact(binding, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, "artifact binding")
    relative = Path(_string(data["path"], "artifact binding.path"))
    require(not relative.is_absolute() and ".." not in relative.parts, "artifact binding path must be portable and relative")
    path = owner.parent / relative
    document = load_json(path)
    require(sha256_file(path) == _sha(data["sha256"], "artifact binding.sha256"), "artifact file SHA-256 changed")
    require(path.stat().st_size == data["size_bytes"], "artifact byte size changed")
    require(document.get("schema") == data["schema"], "artifact schema changed")
    if expected_schema is not None:
        require(data["schema"] == expected_schema, f"artifact binding must use {expected_schema}")
    require(document.get("payload_sha256") == data["payload_sha256"], "artifact payload SHA-256 changed")
    require(payload_sha256(document) == document.get("payload_sha256"), "artifact payload hash is invalid")
    return document, path


def _resolve_blob(binding: Any, owner: Path, label: str) -> Path:
    data = _exact(binding, {"path", "sha256", "size_bytes"}, f"{label} binding")
    relative = Path(_string(data["path"], f"{label} binding.path"))
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label} binding path must be portable and relative")
    path = owner.parent / relative
    require(path.is_file() and not path.is_symlink(), f"{label} source must be an existing non-symlink file")
    require(sha256_file(path) == _sha(data["sha256"], f"{label} binding.sha256"), f"{label} file SHA-256 changed")
    require(path.stat().st_size == data["size_bytes"], f"{label} byte size changed")
    return path


def _resolve_json_observation(binding: Any, owner: Path, label: str) -> tuple[dict[str, Any], Path]:
    data = _exact(binding, {"path", "sha256", "size_bytes", "schema"}, f"{label} binding")
    relative = Path(_string(data["path"], f"{label} binding.path"))
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label} binding path must be portable and relative")
    path = owner.parent / relative
    document = load_json(path)
    require(sha256_file(path) == _sha(data["sha256"], f"{label} binding.sha256"), f"{label} file SHA-256 changed")
    require(path.stat().st_size == data["size_bytes"], f"{label} byte size changed")
    require(document.get("schema") == data["schema"], f"{label} schema changed")
    return document, path


def _load_calculation_dag() -> Any:
    path = Path(__file__).with_name("calculation_dag.py")
    spec = importlib.util.spec_from_file_location("auto_g16_scientific_maturity_calculation_dag", path)
    require(spec is not None and spec.loader is not None, "calculation-DAG owner validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _load_gaussian_log_owner() -> Any:
    path = Path(__file__).resolve().parents[2] / "auto-g16-rtwin-pbs" / "scripts" / "gaussian_log.py"
    spec = importlib.util.spec_from_file_location("auto_g16_scientific_maturity_gaussian_log", path)
    require(spec is not None and spec.loader is not None, "Gaussian log owner parser is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_calculation_artifact_owner() -> Any:
    path = Path(__file__).with_name("calculation_artifacts.py")
    spec = importlib.util.spec_from_file_location("auto_g16_scientific_maturity_calculation_artifacts", path)
    require(spec is not None and spec.loader is not None, "calculation-artifact owner validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _load_ts_irc_owner() -> Any:
    path = Path(__file__).resolve().parents[2] / "auto-g16-ts-irc" / "scripts" / "ts_irc.py"
    spec = importlib.util.spec_from_file_location("auto_g16_scientific_maturity_ts_irc", path)
    require(spec is not None and spec.loader is not None, "TS/IRC owner validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_xyz(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(lines and lines[0].strip().isdigit(), "optimized XYZ lacks an atom count")
    count = int(lines[0].strip())
    require(len(lines) == count + 2, "optimized XYZ atom count differs from its coordinate rows")
    atoms: list[dict[str, Any]] = []
    for index, line in enumerate(lines[2:], start=1):
        fields = line.split()
        require(len(fields) == 4, "optimized XYZ rows must contain element and three coordinates")
        try:
            x, y, z = map(float, fields[1:])
        except ValueError as exc:
            raise MaturityError("optimized XYZ contains a non-numeric coordinate") from exc
        require(all(math.isfinite(value) for value in (x, y, z)), "optimized XYZ contains a non-finite coordinate")
        atoms.append({"index": index, "element": fields[0], "x": x, "y": y, "z": z})
    return atoms


def _normalize_pair(value: Any, label: str) -> list[str]:
    require(isinstance(value, list) and len(value) == 2, f"{label} must contain exactly two atom IDs")
    pair = [_identifier(item, f"{label}[{index}]") for index, item in enumerate(value)]
    require(pair[0] != pair[1], f"{label} cannot repeat one atom")
    return sorted(pair)


def _normalize_review(value: dict[str, Any], *, require_hash: bool) -> dict[str, Any]:
    keys = {
        "schema", "review_id", "study_id", "calculation_plan_payload_sha256",
        "literature_and_user_intake", "edge_reviews", "minimum_records",
        "pilot_and_budget", "path_validation", "reference_thermochemistry",
        "stop_conditions", "review_decision", "reviewer", "reviewed_at",
        "review_notes", "payload_sha256",
    }
    data = _exact(value, keys, "scientific-maturity review")
    require(data["schema"] == REVIEW_SCHEMA, f"review schema must be {REVIEW_SCHEMA}")
    if require_hash:
        require(data["payload_sha256"] == payload_sha256(data), "scientific-maturity review payload hash is invalid")
    else:
        require(data["payload_sha256"] is None, "review draft payload_sha256 must be null")

    intake = _exact(data["literature_and_user_intake"], {
        "user_seeds", "active_species_hypotheses", "elementary_step_hypotheses",
        "experimental_intermediate_evidence", "coverage_lanes", "search_saturation",
        "key_literature_no_obvious_omissions_confirmed",
    }, "literature_and_user_intake")
    seeds = []
    for index, raw in enumerate(intake["user_seeds"]):
        seed = _exact(raw, {"seed_id", "kind", "value", "authority", "verification_status"}, f"user_seeds[{index}]")
        require(seed["kind"] in SEED_KINDS, f"user seed {index} has unsupported kind")
        require(seed["authority"] in SEED_AUTHORITIES, f"user seed {index} cannot be promoted to fact")
        require(seed["verification_status"] in {"unverified", "verified", "not_verifiable"}, f"user seed {index} has invalid verification status")
        seeds.append({**seed, "seed_id": _identifier(seed["seed_id"], f"user_seeds[{index}].seed_id"), "value": _string(seed["value"], f"user_seeds[{index}].value")})
    require(len({item["seed_id"] for item in seeds}) == len(seeds), "duplicate user seed IDs")

    active_hypotheses = []
    for index, raw in enumerate(intake["active_species_hypotheses"]):
        item = _exact(raw, {"hypothesis_id", "description", "authority", "status"}, f"active_species_hypotheses[{index}]")
        require(item["authority"] in SEED_AUTHORITIES, "active-species intake may contain only a user hypothesis or verifiable seed")
        require(item["status"] in {"unresolved", "reviewed_hypothesis", "rejected"}, "active-species hypothesis status is invalid")
        active_hypotheses.append({**item, "hypothesis_id": _identifier(item["hypothesis_id"], "active-species hypothesis ID"), "description": _string(item["description"], "active-species hypothesis description")})
    require(active_hypotheses, "at least one explicit active-species hypothesis is required")

    step_hypotheses = []
    for index, raw in enumerate(intake["elementary_step_hypotheses"]):
        item = _exact(raw, {"hypothesis_id", "edge_id", "step_type", "forming_bonds", "breaking_bonds", "transferred_atom_ids", "selectivity_determining", "authority"}, f"elementary_step_hypotheses[{index}]")
        require(item["authority"] in SEED_AUTHORITIES, "elementary-step intake may contain only a user hypothesis or verifiable seed")
        step_hypotheses.append({
            **item,
            "hypothesis_id": _identifier(item["hypothesis_id"], "step hypothesis ID"),
            "edge_id": _identifier(item["edge_id"], "step hypothesis edge_id"),
            "step_type": _string(item["step_type"], "step type"),
            "forming_bonds": [_normalize_pair(pair, "forming bond") for pair in item["forming_bonds"]],
            "breaking_bonds": [_normalize_pair(pair, "breaking bond") for pair in item["breaking_bonds"]],
            "transferred_atom_ids": _string_list(item["transferred_atom_ids"], "transferred atom IDs"),
        })
        require(isinstance(item["selectivity_determining"], bool), "selectivity_determining must be boolean")
    require(step_hypotheses, "at least one explicit elementary-step hypothesis is required")

    intermediate_evidence = []
    for index, raw in enumerate(intake["experimental_intermediate_evidence"]):
        item = _exact(raw, {"evidence_id", "description", "authority", "verification_status"}, f"experimental_intermediate_evidence[{index}]")
        require(item["authority"] in SEED_AUTHORITIES, "experimental intermediate intake may contain only a user hypothesis or verifiable seed")
        require(item["verification_status"] in {"unverified", "verified", "not_verifiable"}, "intermediate evidence verification status is invalid")
        intermediate_evidence.append({**item, "evidence_id": _identifier(item["evidence_id"], "intermediate evidence ID"), "description": _string(item["description"], "intermediate evidence description")})

    lanes = []
    for index, raw in enumerate(intake["coverage_lanes"]):
        lane = _exact(raw, {"lane_id", "status", "scope_or_queries", "evidence_refs", "limitations"}, f"coverage_lanes[{index}]")
        require(lane["lane_id"] in COVERAGE_LANES, f"unsupported coverage lane: {lane['lane_id']}")
        require(lane["status"] in {"searched", "not_applicable", "blocked"}, f"coverage lane {lane['lane_id']} status is invalid")
        scopes = _string_list(lane["scope_or_queries"], f"coverage lane {lane['lane_id']} scope_or_queries")
        if lane["status"] == "searched":
            require(scopes, f"searched coverage lane {lane['lane_id']} needs an auditable scope/query")
        lanes.append({**lane, "scope_or_queries": scopes, "evidence_refs": _string_list(lane["evidence_refs"], "coverage evidence refs"), "limitations": _string_list(lane["limitations"], "coverage limitations")})
    require({item["lane_id"] for item in lanes} == COVERAGE_LANES, "coverage_lanes must cover the complete closed search overlay")

    saturation = _exact(intake["search_saturation"], {"direct", "analogous", "fulltext_or_si_missing", "user_provided_unverified", "unresolved_questions", "decision", "rationale"}, "search_saturation")
    require(saturation["decision"] in {"saturated_for_current_scope", "gaps_remain", "blocked"}, "search saturation decision is invalid")
    normalized_intake = {
        "user_seeds": sorted(seeds, key=lambda item: item["seed_id"]),
        "active_species_hypotheses": sorted(active_hypotheses, key=lambda item: item["hypothesis_id"]),
        "elementary_step_hypotheses": sorted(step_hypotheses, key=lambda item: item["hypothesis_id"]),
        "experimental_intermediate_evidence": sorted(intermediate_evidence, key=lambda item: item["evidence_id"]),
        "coverage_lanes": sorted(lanes, key=lambda item: item["lane_id"]),
        "search_saturation": {
            "direct": _string_list(saturation["direct"], "search_saturation.direct"),
            "analogous": _string_list(saturation["analogous"], "search_saturation.analogous"),
            "fulltext_or_si_missing": _string_list(saturation["fulltext_or_si_missing"], "search_saturation.fulltext_or_si_missing"),
            "user_provided_unverified": _string_list(saturation["user_provided_unverified"], "search_saturation.user_provided_unverified"),
            "unresolved_questions": _string_list(saturation["unresolved_questions"], "search_saturation.unresolved_questions"),
            "decision": saturation["decision"],
            "rationale": _string(saturation["rationale"], "search saturation rationale"),
        },
        "key_literature_no_obvious_omissions_confirmed": intake["key_literature_no_obvious_omissions_confirmed"],
    }
    require(isinstance(normalized_intake["key_literature_no_obvious_omissions_confirmed"], bool), "key-literature confirmation must be boolean")

    edges = []
    for index, raw in enumerate(data["edge_reviews"]):
        item = _exact(raw, {"edge_id", "stereochemical_channel", "path_role", "path_confirmed_by_user", "evidence_class", "evidence_refs", "start_minimum_id", "end_minimum_id", "active_species_hypothesis_id", "active_species", "step_type", "forming_bonds", "breaking_bonds", "transferred_atom_ids", "expected_reaction_coordinate", "ts_strategy", "pilot_node_ids", "formal_ts_node_ids", "low_cost_scan_support", "blockers"}, f"edge_reviews[{index}]")
        require(item["path_role"] in {"primary", "competing"}, "edge path_role must be primary or competing")
        require(isinstance(item["path_confirmed_by_user"], bool), "path confirmation must be boolean")
        require(item["evidence_class"] in EVIDENCE_CLASSES, "edge evidence_class is invalid")
        strategy = _exact(item["ts_strategy"], {"kind", "basis", "approved", "reviewer", "rationale"}, "TS strategy")
        require(strategy["kind"] in {"qst2", "qst3", "relaxed_scan", "single_guess"}, "unsupported TS strategy")
        require(strategy["basis"] in {"literature_precedent", "human_approved"}, "TS strategy requires literature precedent or human approval")
        require(isinstance(strategy["approved"], bool), "TS strategy approved must be boolean")
        require(item["low_cost_scan_support"] in {"supported", "not_run", "unsupported"}, "low_cost_scan_support is invalid")
        edges.append({
            **item,
            "edge_id": _identifier(item["edge_id"], "edge ID"),
            "evidence_refs": _string_list(item["evidence_refs"], "edge evidence refs"),
            "start_minimum_id": _identifier(item["start_minimum_id"], "start minimum ID"),
            "end_minimum_id": _identifier(item["end_minimum_id"], "end minimum ID"),
            "active_species_hypothesis_id": _identifier(item["active_species_hypothesis_id"], "active-species hypothesis ID"),
            "active_species": _string(item["active_species"], "active species"),
            "step_type": _string(item["step_type"], "edge step type"),
            "forming_bonds": [_normalize_pair(pair, "edge forming bond") for pair in item["forming_bonds"]],
            "breaking_bonds": [_normalize_pair(pair, "edge breaking bond") for pair in item["breaking_bonds"]],
            "transferred_atom_ids": _string_list(item["transferred_atom_ids"], "edge transferred atoms"),
            "expected_reaction_coordinate": _string(item["expected_reaction_coordinate"], "expected reaction coordinate"),
            "ts_strategy": {**strategy, "reviewer": _string(strategy["reviewer"], "TS strategy reviewer"), "rationale": _string(strategy["rationale"], "TS strategy rationale")},
            "pilot_node_ids": _string_list(item["pilot_node_ids"], "pilot node IDs"),
            "formal_ts_node_ids": _string_list(item["formal_ts_node_ids"], "formal TS node IDs"),
            "blockers": _string_list(item["blockers"], "edge blockers"),
        })
        require(len(edges[-1]["pilot_node_ids"]) <= 1, "each edge may declare at most one low-cost TS pilot node")
        require(set(edges[-1]["pilot_node_ids"]).isdisjoint(edges[-1]["formal_ts_node_ids"]), "pilot and formal TS node IDs must be disjoint")
        require(item["stereochemical_channel"] is None or isinstance(item["stereochemical_channel"], str), "stereochemical_channel must be a reviewed string or null")
    require(edges and len({item["edge_id"] for item in edges}) == len(edges), "edge reviews must be non-empty and unique")

    minima = []
    fact_keys = {"normal_termination", "optimization_converged", "frequency_complete", "imaginary_frequency_count", "connectivity_identity_reviewed", "composition_reviewed", "charge_multiplicity_reviewed", "atom_order_mapping_reviewed", "duplicate_reviewed", "weak_binding_intact_or_not_applicable", "low_frequency_flagged", "checkpoint_retained", "optimized_coordinates_retained"}
    for index, raw in enumerate(data["minimum_records"]):
        item = _exact(raw, {"minimum_id", "state_id", "composition_signature", "formal_charge", "multiplicity", "atom_order", "conformer_origin", "source_log", "workflow_settings", "result", "checkpoint", "optimized_coordinates", "acceptance_facts", "decision", "reviewer", "notes"}, f"minimum_records[{index}]")
        origin = _exact(item["conformer_origin"], {"scope", "source_id", "ts_derivation_allowed"}, "minimum conformer origin")
        require(origin["scope"] == "minimum_search", "conformer search must serve minima before TS derivation")
        require(isinstance(origin["ts_derivation_allowed"], bool), "ts_derivation_allowed must be boolean")
        facts = _exact(item["acceptance_facts"], fact_keys, "minimum acceptance_facts")
        require(isinstance(facts["imaginary_frequency_count"], int) and facts["imaginary_frequency_count"] >= 0, "minimum imaginary-frequency count must be non-negative")
        for key in fact_keys - {"imaginary_frequency_count"}:
            require(isinstance(facts[key], bool), f"minimum acceptance fact {key} must be boolean")
        require(item["decision"] in {"accepted", "rejected", "pending"}, "minimum decision is invalid")
        require(isinstance(item["formal_charge"], int) and isinstance(item["multiplicity"], int) and item["multiplicity"] > 0, "minimum charge/multiplicity is invalid")
        atom_order = _string_list(item["atom_order"], "minimum atom_order", nonempty=True)
        settings = _exact(item["workflow_settings"], {"temperature_k", "standard_state", "expected_stages"}, "minimum workflow_settings")
        require(isinstance(settings["temperature_k"], (int, float)) and math.isfinite(float(settings["temperature_k"])) and settings["temperature_k"] > 0, "minimum workflow temperature must be positive")
        require(settings["standard_state"] in {"1atm", "1M"}, "minimum workflow standard state must be 1atm or 1M")
        require(isinstance(settings["expected_stages"], int) and settings["expected_stages"] >= 2, "minimum workflow must expect at least Opt and Freq stages")
        minima.append({
            **item,
            "minimum_id": _identifier(item["minimum_id"], "minimum ID"),
            "state_id": _identifier(item["state_id"], "minimum state ID"),
            "composition_signature": _string(item["composition_signature"], "minimum composition signature"),
            "atom_order": atom_order,
            "conformer_origin": {**origin, "source_id": _identifier(origin["source_id"], "conformer source ID")},
            "source_log": item["source_log"], "workflow_settings": settings,
            "result": item["result"], "checkpoint": item["checkpoint"], "optimized_coordinates": item["optimized_coordinates"],
            "acceptance_facts": facts,
            "reviewer": _string(item["reviewer"], "minimum reviewer"),
            "notes": _string_list(item["notes"], "minimum notes"),
        })
    require(len({item["minimum_id"] for item in minima}) == len(minima), "duplicate minimum IDs")

    pilot = _exact(data["pilot_and_budget"], {"default_resource_tier", "primary_candidates_per_edge", "competing_candidates_per_edge", "no_automatic_expansion", "no_automatic_retry_or_chemistry_change", "task_budget", "resource_upgrades"}, "pilot_and_budget")
    require(pilot["default_resource_tier"] == "simple", "default pilot resource tier must be simple")
    require(pilot["primary_candidates_per_edge"] == 1 and pilot["competing_candidates_per_edge"] in {0, 1}, "pilot candidate limits must be one primary and at most one competing")
    require(pilot["no_automatic_expansion"] is True and pilot["no_automatic_retry_or_chemistry_change"] is True, "pilot failures must not trigger automatic expansion, retry, or chemistry changes")
    budget = _exact(pilot["task_budget"], {"max_tasks", "max_core_hours", "max_concurrent", "status"}, "task_budget")
    require(all(isinstance(budget[key], int) and budget[key] > 0 for key in ("max_tasks", "max_core_hours", "max_concurrent")), "task budget values must be positive integers")
    require(budget["status"] in {"within_budget", "exceeded", "not_assessed"}, "task budget status is invalid")
    upgrades = []
    for index, raw in enumerate(pilot["resource_upgrades"]):
        upgrade = _exact(raw, {"edge_id", "tier", "successful_pilot_evidence", "scale_memory_cost_rationale", "approved"}, f"resource_upgrades[{index}]")
        require(upgrade["tier"] in {"general", "complex"}, "resource upgrade must target general or complex")
        require(isinstance(upgrade["approved"], bool), "resource upgrade approved must be boolean")
        if upgrade["approved"]:
            binding = _exact(upgrade["successful_pilot_evidence"], {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, "successful pilot evidence")
            require(binding["schema"] in {"gaussian-ts-irc-path-acceptance/1", "gaussian-ts-irc-path-acceptance/2"}, "resource upgrade requires owner-validated successful same-edge TS/IRC evidence")
            _string(upgrade["scale_memory_cost_rationale"], "resource upgrade rationale")
        else:
            require(upgrade["successful_pilot_evidence"] is None, "unapproved resource upgrade must not claim successful-pilot evidence")
        upgrades.append({**upgrade, "edge_id": _identifier(upgrade["edge_id"], "resource-upgrade edge ID")})
    normalized_pilot = {**pilot, "task_budget": budget, "resource_upgrades": sorted(upgrades, key=lambda item: (item["edge_id"], item["tier"]))}

    paths = []
    for index, raw in enumerate(data["path_validation"]):
        item = _exact(raw, {"edge_id", "ts_exactly_one_imaginary", "mode_confirmed_along_coordinate", "irc_forward_terminated", "irc_reverse_terminated", "irc_endpoints_identified", "endpoint_reopt_freq_zero_imaginary", "endpoint_matches_expected_minima", "evidence_refs", "ts_mode_evidence", "irc_path_evidence", "energy_lineage", "endpoint_reopt_minimum_ids", "status", "blockers"}, f"path_validation[{index}]")
        for key in ("ts_exactly_one_imaginary", "mode_confirmed_along_coordinate", "irc_forward_terminated", "irc_reverse_terminated", "irc_endpoints_identified", "endpoint_reopt_freq_zero_imaginary", "endpoint_matches_expected_minima"):
            require(isinstance(item[key], bool), f"path validation {key} must be boolean")
        require(item["status"] in {"not_started", "incomplete", "accepted", "rejected"}, "path validation status is invalid")
        evidence_refs = _string_list(item["evidence_refs"], "path-validation evidence refs")
        blockers = _string_list(item["blockers"], "path-validation blockers")
        complete = all(item[key] for key in ("ts_exactly_one_imaginary", "mode_confirmed_along_coordinate", "irc_forward_terminated", "irc_reverse_terminated", "irc_endpoints_identified", "endpoint_reopt_freq_zero_imaginary", "endpoint_matches_expected_minima"))
        if item["status"] == "accepted":
            require(complete and evidence_refs and not blockers, "accepted path validation requires complete TS/mode/IRC/endpoint evidence refs without blockers")
        if any(item[key] for key in ("ts_exactly_one_imaginary", "mode_confirmed_along_coordinate", "irc_forward_terminated", "irc_reverse_terminated", "irc_endpoints_identified", "endpoint_reopt_freq_zero_imaginary", "endpoint_matches_expected_minima")):
            require(evidence_refs, "recorded TS/IRC/endpoint facts require auditable evidence refs")
        for field, schema in (("ts_mode_evidence", "gaussian-calculation-attempt-link/1"), ("irc_path_evidence", {"gaussian-ts-irc-path-acceptance/1", "gaussian-ts-irc-path-acceptance/2"}), ("energy_lineage", "gaussian-energy-lineage/1")):
            if item[field] is not None:
                _exact(item[field], {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, f"path-validation {field}")
                allowed = schema if isinstance(schema, set) else {schema}
                require(item[field]["schema"] in allowed, f"path {field} must use one of {sorted(allowed)}")
        reopt_ids = _string_list(item["endpoint_reopt_minimum_ids"], "endpoint re-Opt/Freq minimum IDs")
        require(len(reopt_ids) in {0, 2}, "endpoint re-Opt/Freq evidence must bind exactly two minima or remain empty")
        paths.append({**item, "edge_id": _identifier(item["edge_id"], "path-validation edge ID"), "evidence_refs": evidence_refs, "endpoint_reopt_minimum_ids": reopt_ids, "blockers": blockers})
    require(len({item["edge_id"] for item in paths}) == len(paths), "duplicate path-validation edge IDs")

    thermo = _exact(data["reference_thermochemistry"], {"common_reference_inventory", "same_composition", "standard_state", "temperature_k", "solvent_model_identity", "catalyst_regeneration_relation", "local_and_apparent_barriers_distinguished", "minima_and_ts_conformer_coverage", "weak_complex_low_frequency_flags", "low_frequency_policy_status", "energies_retained", "sensitivity_scope"}, "reference_thermochemistry")
    require(_string_list(thermo["common_reference_inventory"], "common reference inventory", nonempty=True), "common reference inventory is required")
    require(thermo["same_composition"] is True and thermo["standard_state"] == "1M", "common references require identical composition and 1 M standard state")
    require(isinstance(thermo["temperature_k"], (int, float)) and math.isfinite(float(thermo["temperature_k"])) and thermo["temperature_k"] > 0, "temperature must be finite and positive")
    for key in ("solvent_model_identity", "catalyst_regeneration_relation"):
        _string(thermo[key], f"reference thermochemistry {key}")
    for key in ("local_and_apparent_barriers_distinguished", "minima_and_ts_conformer_coverage", "weak_complex_low_frequency_flags"):
        require(thermo[key] is True, f"reference thermochemistry requires {key}")
    require(thermo["low_frequency_policy_status"] == "approved_before_thermochemistry", "low-frequency policy must be approved before thermochemistry")
    energies = _exact(thermo["energies_retained"], {"electronic", "enthalpy", "raw_gibbs", "treated_gibbs"}, "energies_retained")
    require(all(energies.values()), "electronic energy, enthalpy, raw Gibbs, and treated Gibbs must all be retained")
    require(thermo["sensitivity_scope"] == "few_optimized_representatives_only", "method sensitivity is limited to a few optimized representatives")

    stop_conditions = _string_list(data["stop_conditions"], "stop_conditions", nonempty=True)
    require(set(stop_conditions) == STOP_CONDITIONS, "the complete closed stop-condition set is required")
    require(data["review_decision"] in {"accepted", "accepted_with_blockers", "blocked"}, "scientific-maturity review decision is invalid")
    normalized = {
        "schema": REVIEW_SCHEMA,
        "review_id": _identifier(data["review_id"], "review_id"),
        "study_id": _identifier(data["study_id"], "study_id"),
        "calculation_plan_payload_sha256": _sha(data["calculation_plan_payload_sha256"], "calculation plan payload SHA-256"),
        "literature_and_user_intake": normalized_intake,
        "edge_reviews": sorted(edges, key=lambda item: item["edge_id"]),
        "minimum_records": sorted(minima, key=lambda item: item["minimum_id"]),
        "pilot_and_budget": normalized_pilot,
        "path_validation": sorted(paths, key=lambda item: item["edge_id"]),
        "reference_thermochemistry": thermo,
        "stop_conditions": sorted(stop_conditions),
        "review_decision": data["review_decision"],
        "reviewer": _string(data["reviewer"], "reviewer"),
        "reviewed_at": _string(data["reviewed_at"], "reviewed_at"),
        "review_notes": _string_list(data["review_notes"], "review_notes"),
        "payload_sha256": data["payload_sha256"],
    }
    if require_hash:
        require(normalized == data, "scientific-maturity review is not in deterministic normalized form")
    return normalized


def finalize_review(draft: Path, output: Path) -> dict[str, Any]:
    normalized = _normalize_review(load_json(draft), require_hash=False)
    artifact = finalize({key: value for key, value in normalized.items() if key != "payload_sha256"})
    write_json(output, artifact)
    return artifact


def _minimum_status(record: dict[str, Any], owner_path: Path) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    try:
        source_log = _resolve_blob(record["source_log"], owner_path, "minimum Gaussian log")
        result, _ = _resolve_json_observation(record["result"], owner_path, "minimum Gaussian result")
        checkpoint_path = _resolve_blob(record["checkpoint"], owner_path, "minimum checkpoint")
        optimized_path = _resolve_blob(record["optimized_coordinates"], owner_path, "minimum optimized coordinates")
    except MaturityError as exc:
        return False, [f"minimum_source_binding_invalid:{exc}"]
    facts = record["acceptance_facts"]
    if checkpoint_path.stat().st_size == 0:
        blockers.append("minimum_checkpoint_is_empty")
    if result.get("schema") != "gaussian-opt-freq-sp-result/1":
        blockers.append("minimum_result_schema_is_not_opt_freq_sp")
    try:
        owner = _load_gaussian_log_owner()
        settings = record["workflow_settings"]
        replay = owner.analyze_workflow_log_text(
            source_log.read_text(encoding="utf-8", errors="replace"),
            temperature_k=float(settings["temperature_k"]),
            standard_state=settings["standard_state"],
            expected_stages=settings["expected_stages"],
        )
    except Exception as exc:
        return False, [f"minimum_owner_parser_replay_failed:{exc}"]
    replay_fields = {
        "status", "normal_termination", "normal_termination_count", "error_termination",
        "error_termination_count", "optimization_completed", "stationary_point_found",
        "optimization_success", "frequency_count", "imaginary_frequency_count",
        "frequencies_cm-1", "final_coordinate_count", "final_coordinates",
        "expected_stage_count", "execution_complete", "frequency_complete",
        "minimum_validated", "single_point_complete", "workflow_success",
        "low_frequency_count_below_100_cm-1", "low_frequencies_cm-1", "thermochemistry",
    }
    for key in replay_fields:
        if result.get(key) != replay.get(key):
            blockers.append(f"minimum_result_differs_from_owner_log_replay:{key}")
    source_checks = {
        "normal_termination": result.get("normal_termination") is True and result.get("execution_complete") is True,
        "optimization_converged": result.get("optimization_success") is True,
        "frequency_complete": result.get("frequency_complete") is True,
        "imaginary_frequency_count": result.get("imaginary_frequency_count") == 0,
    }
    for key, passed in source_checks.items():
        if not passed or facts[key] != (0 if key == "imaginary_frequency_count" else True):
            blockers.append(f"minimum_{key}_not_proven")
    for key, value in facts.items():
        if key != "imaginary_frequency_count" and value is not True:
            blockers.append(f"minimum_{key}_not_accepted")
    identity = result.get("chemical_identity", {})
    if not isinstance(identity, dict):
        identity = {}
    source_charge = identity.get("charge", result.get("charge"))
    source_multiplicity = identity.get("multiplicity", result.get("multiplicity"))
    source_formula = identity.get("formula")
    if source_charge != record["formal_charge"] or source_multiplicity != record["multiplicity"]:
        blockers.append("minimum_source_charge_or_multiplicity_mismatch")
    if source_formula is not None and source_formula != record["composition_signature"]:
        blockers.append("minimum_source_composition_mismatch")
    coordinates = result.get("final_coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != len(record["atom_order"]):
        blockers.append("minimum_source_atom_count_or_order_missing")
    else:
        try:
            xyz = _parse_xyz(optimized_path)
            result_projection = [
                {"index": item.get("center", item.get("index")), "element": item.get("element"), "x": item.get("x"), "y": item.get("y"), "z": item.get("z")}
                for item in coordinates
            ]
            if xyz != result_projection:
                blockers.append("minimum_optimized_coordinates_differ_from_owner_result")
        except MaturityError as exc:
            blockers.append(f"minimum_optimized_coordinates_invalid:{exc}")
    if record["decision"] != "accepted":
        blockers.append("minimum_review_not_accepted")
    return not blockers, sorted(set(blockers))


def _build_gate(plan: dict[str, Any], plan_binding: dict[str, Any], review: dict[str, Any], review_binding: dict[str, Any], review_path: Path) -> dict[str, Any]:
    require(plan["study_id"] == review["study_id"], "review and calculation plan study_id differ")
    require(plan["payload_sha256"] == review["calculation_plan_payload_sha256"], "review is not bound to the exact calculation plan")
    mechanism, _ = _resolve(plan["mechanism_network"], Path(plan["__path"] if "__path" in plan else review_path))
    edge_sources = {item["edge_id"]: item for item in mechanism["edges"]}
    state_sources = {item["state_id"]: item for item in mechanism["states"]}
    edge_reviews = {item["edge_id"]: item for item in review["edge_reviews"]}
    active_edges = {edge_id for node in plan["nodes"] if node["disposition"] in {"planned", "retained"} for edge_id in node["target"]["edge_ids"]}
    require(active_edges.issubset(edge_reviews), "every active calculation-plan edge needs a scientific-maturity review")
    minima = {item["minimum_id"]: item for item in review["minimum_records"]}
    minimum_gates: dict[str, dict[str, Any]] = {}
    for minimum_id, record in minima.items():
        accepted, blockers = _minimum_status(record, review_path)
        state = state_sources.get(record["state_id"])
        if state is None:
            blockers.append("minimum_state_missing_from_mechanism_owner")
        else:
            expected_atom_order = [atom["atom_id"] for atom in state["atoms"]]
            if record["atom_order"] != expected_atom_order:
                blockers.append("minimum_atom_order_differs_from_mechanism_owner")
            try:
                result, _ = _resolve_json_observation(record["result"], review_path, "minimum Gaussian result")
                observed_elements = [atom.get("element") for atom in result.get("final_coordinates", [])]
                expected_elements = [atom["element"] for atom in state["atoms"]]
                if observed_elements != expected_elements:
                    blockers.append("minimum_element_order_differs_from_mechanism_owner")
            except MaturityError as exc:
                blockers.append(f"minimum_source_binding_invalid:{exc}")
        accepted = not blockers
        minimum_gates[minimum_id] = {"minimum_id": minimum_id, "state_id": record["state_id"], "accepted": accepted, "blockers": blockers}

    path_map = {item["edge_id"]: item for item in review["path_validation"]}
    upgrades = {(item["edge_id"], item["tier"]): item for item in review["pilot_and_budget"]["resource_upgrades"]}
    valid_upgrades: set[tuple[str, str]] = set()
    for key, upgrade in upgrades.items():
        if not upgrade["approved"]:
            continue
        try:
            evidence, evidence_path = _resolve(upgrade["successful_pilot_evidence"], review_path)
            require(evidence.get("schema") in {"gaussian-ts-irc-path-acceptance/1", "gaussian-ts-irc-path-acceptance/2"}, "successful pilot evidence schema is unsupported")
            _load_ts_irc_owner().validate_path_acceptance_artifact(evidence_path)
            if evidence.get("edge_id") == upgrade["edge_id"]:
                valid_upgrades.add(key)
        except Exception:
            continue
    literature = review["literature_and_user_intake"]
    active_hypotheses = {item["hypothesis_id"]: item for item in literature["active_species_hypotheses"]}
    critical_literature_gaps = any(
        literature["search_saturation"][key]
        for key in ("fulltext_or_si_missing", "user_provided_unverified", "unresolved_questions")
    )
    literature_confirmed = (
        literature["key_literature_no_obvious_omissions_confirmed"] is True
        and literature["search_saturation"]["decision"] == "saturated_for_current_scope"
        and all(item["status"] != "blocked" for item in literature["coverage_lanes"])
        and not critical_literature_gaps
    )
    owner_support_present = plan.get("mechanism_support") is not None
    owner_precedent_present = plan.get("ts_precedent_map") is not None
    plan_nodes = {item["node_id"]: item for item in plan["nodes"]}
    edge_gates = []
    blocker_records: list[dict[str, Any]] = []
    for edge_id in sorted(edge_reviews):
        item = edge_reviews[edge_id]
        require(edge_id in edge_sources, f"reviewed edge is absent from mechanism network: {edge_id}")
        source = edge_sources[edge_id]
        active_hypothesis = active_hypotheses.get(item["active_species_hypothesis_id"])
        require(active_hypothesis is not None, f"edge {edge_id} references an absent active-species hypothesis")
        require(active_hypothesis["description"] == item["active_species"], f"edge {edge_id} active-species description differs from its bound hypothesis")
        for node_id in item["pilot_node_ids"] + item["formal_ts_node_ids"]:
            require(node_id in plan_nodes, f"edge {edge_id} references an absent TS DAG node: {node_id}")
            node = plan_nodes[node_id]
            require(node["node_kind"] in TS_KINDS, f"edge {edge_id} references a non-TS DAG node: {node_id}")
            require(node["target"]["edge_ids"] == [edge_id], f"TS DAG node {node_id} is not bound exactly to edge {edge_id}")
        if edge_id in active_edges:
            require(len(item["pilot_node_ids"]) == 1, f"active edge {edge_id} requires exactly one low-cost TS pilot node")
            require(bool(item["formal_ts_node_ids"]), f"active edge {edge_id} requires an explicit formal TS-node set")
        require(item["stereochemical_channel"] == source["stereochemical_channel"], f"edge {edge_id} stereochemical channel differs from mechanism network")
        source_forming = sorted(change["atom_ids"] for change in source["connection_changes"] if change["before_order"] is None and change["after_order"] is not None)
        source_breaking = sorted(change["atom_ids"] for change in source["connection_changes"] if change["before_order"] is not None and change["after_order"] is None)
        require(sorted(item["forming_bonds"]) == source_forming, f"edge {edge_id} forming bonds differ from mechanism network")
        require(sorted(item["breaking_bonds"]) == source_breaking, f"edge {edge_id} breaking bonds differ from mechanism network")
        require(sorted(item["transferred_atom_ids"]) == sorted(transfer["atom_id"] for transfer in source["transfers"]), f"edge {edge_id} transferred atoms differ from mechanism network")
        start = minima.get(item["start_minimum_id"])
        end = minima.get(item["end_minimum_id"])
        blockers: list[str] = []
        if not item["path_confirmed_by_user"]:
            blockers.append("primary_or_competing_path_not_confirmed")
        if item["blockers"]:
            blockers.append("edge_review_has_blockers")
        if active_hypothesis["status"] != "reviewed_hypothesis":
            blockers.append("active_state_unresolved")
        if not item["ts_strategy"]["approved"]:
            blockers.append("ts_strategy_not_approved")
        if item["low_cost_scan_support"] == "unsupported":
            blockers.append("low_cost_scan_unsupported")
        for role, record, expected_state in (("start", start, source["from_state_id"]), ("end", end, source["to_state_id"])):
            if record is None:
                blockers.append(f"{role}_minimum_missing")
            elif record["state_id"] != expected_state:
                blockers.append(f"{role}_minimum_state_mismatch")
            elif not minimum_gates[record["minimum_id"]]["accepted"]:
                blockers.append(f"{role}_minimum_not_accepted")
            elif record["conformer_origin"]["ts_derivation_allowed"] is not True:
                blockers.append(f"{role}_minimum_ts_derivation_not_allowed")
        endpoints_consistent = False
        if start is not None and end is not None:
            endpoints_consistent = (
                start["composition_signature"] == end["composition_signature"]
                and start["formal_charge"] == end["formal_charge"]
                and start["multiplicity"] == end["multiplicity"]
                and len(start["atom_order"]) == len(end["atom_order"])
            )
            if not endpoints_consistent:
                blockers.append("endpoint_composition_charge_multiplicity_or_mapping_mismatch")
            mapping = {entry["from_atom_id"]: entry["to_atom_id"] for entry in source["atom_mapping"]}
            mapped_end_order = [mapping.get(atom_id) for atom_id in start["atom_order"]]
            if mapped_end_order != end["atom_order"]:
                endpoints_consistent = False
                blockers.append("endpoint_atom_mapping_mismatch")
        if review["pilot_and_budget"]["task_budget"]["status"] != "within_budget":
            blockers.append("task_budget_not_within_limit")
        hypothesis_only = item["evidence_class"] in {"user_hypothesis", "internal_exploratory_hypothesis", "missing_precedent"}
        formal_blockers = list(blockers)
        if not literature_confirmed:
            formal_blockers.append("key_literature_not_confirmed_saturated")
        if critical_literature_gaps:
            formal_blockers.append("critical_literature_evidence_gaps_unresolved")
        if not owner_support_present:
            formal_blockers.append("mechanism_support_owner_gate_missing")
        if not owner_precedent_present:
            formal_blockers.append("ts_precedent_owner_gate_missing")
        if hypothesis_only:
            formal_blockers.append("formal_mechanism_support_absent")
        if review["review_decision"] != "accepted":
            blockers.append("scientific_maturity_review_not_accepted")
            formal_blockers.append("scientific_maturity_review_not_accepted")
        pilot_ready = not blockers and endpoints_consistent
        formal_ready = not formal_blockers and endpoints_consistent
        path = path_map.get(edge_id)
        owner_ts_mode_evidence_valid = False
        owner_irc_path_evidence_valid = False
        owner_energy_lineage_valid = False
        if path and path.get("ts_mode_evidence") is not None:
            try:
                _, evidence_path = _resolve(path["ts_mode_evidence"], review_path, "gaussian-calculation-attempt-link/1")
                _load_calculation_artifact_owner().validate_artifact(evidence_path)
                owner_ts_mode_evidence_valid = True
            except Exception:
                owner_ts_mode_evidence_valid = False
        if path and path.get("irc_path_evidence") is not None:
            try:
                irc_evidence, irc_evidence_path = _resolve(path["irc_path_evidence"], review_path)
                require(irc_evidence.get("schema") in {"gaussian-ts-irc-path-acceptance/1", "gaussian-ts-irc-path-acceptance/2"}, "IRC path evidence schema is unsupported")
                _load_ts_irc_owner().validate_path_acceptance_artifact(irc_evidence_path)
                owner_irc_path_evidence_valid = irc_evidence.get("accepted") is True and irc_evidence.get("edge_id") == edge_id
            except Exception:
                owner_irc_path_evidence_valid = False
        if path and path.get("energy_lineage") is not None:
            try:
                lineage, lineage_path = _resolve(path["energy_lineage"], review_path, "gaussian-energy-lineage/1")
                _load_calculation_artifact_owner().validate_artifact(lineage_path)
                owner_energy_lineage_valid = lineage.get("comparison_eligible") is True
            except Exception:
                owner_energy_lineage_valid = False
        ts_accepted = bool(owner_ts_mode_evidence_valid and path and path["ts_exactly_one_imaginary"] and path["mode_confirmed_along_coordinate"])
        irc_accepted = bool(ts_accepted and owner_irc_path_evidence_valid and path and path["irc_forward_terminated"] and path["irc_reverse_terminated"] and path["irc_endpoints_identified"])
        reopt_ids = path["endpoint_reopt_minimum_ids"] if path else []
        reopt_source_hashes = {minima[minimum_id]["source_log"]["sha256"] for minimum_id in reopt_ids if minimum_id in minima}
        original_source_hashes = {item["start_minimum_id"], item["end_minimum_id"]}
        original_log_hashes = {minima[minimum_id]["source_log"]["sha256"] for minimum_id in original_source_hashes if minimum_id in minima}
        reopt_minima_valid = bool(
            len(reopt_ids) == 2
            and all(minimum_id in minimum_gates and minimum_gates[minimum_id]["accepted"] for minimum_id in reopt_ids)
            and {minima[minimum_id]["state_id"] for minimum_id in reopt_ids} == {source["from_state_id"], source["to_state_id"]}
            and set(reopt_ids).isdisjoint({item["start_minimum_id"], item["end_minimum_id"]})
            and len(reopt_source_hashes) == 2
            and reopt_source_hashes.isdisjoint(original_log_hashes)
        )
        endpoints_revalidated = bool(irc_accepted and reopt_minima_valid and path and path["endpoint_reopt_freq_zero_imaginary"] and path["endpoint_matches_expected_minima"])
        edge_gate = {
            "edge_id": edge_id,
            "path_role": item["path_role"],
            "evidence_class": item["evidence_class"],
            "start_minimum_id": item["start_minimum_id"],
            "end_minimum_id": item["end_minimum_id"],
            "endpoint_pair_accepted_and_consistent": endpoints_consistent and not any(value.endswith("minimum_not_accepted") for value in blockers),
            "pilot_ts_input_scientifically_ready": pilot_ready,
            "formal_ts_input_scientifically_ready": formal_ready,
            "ts_mode_accepted": ts_accepted,
            "owner_ts_mode_evidence_valid": owner_ts_mode_evidence_valid,
            "owner_irc_path_evidence_valid": owner_irc_path_evidence_valid,
            "owner_energy_lineage_valid": owner_energy_lineage_valid,
            "bidirectional_irc_accepted": irc_accepted,
            "irc_endpoints_reoptimized_as_expected_minima": endpoints_revalidated,
            "allowed_resource_tiers": ["simple"] + sorted({tier for (candidate_edge, tier) in valid_upgrades if candidate_edge == edge_id}),
            "pilot_candidate_limit": 1,
            "pilot_node_ids": item["pilot_node_ids"],
            "formal_ts_node_ids": item["formal_ts_node_ids"],
            "formal_blockers": sorted(set(formal_blockers)),
            "pilot_blockers": sorted(set(blockers)),
            "failure_return_stage": "mechanism_or_endpoint_review",
        }
        edge_gates.append(edge_gate)
        for code in sorted(set(formal_blockers)):
            blocker_records.append({"blocker_id": f"{edge_id}_{code}", "scope": edge_id, "description": code.replace("_", " "), "required_for": ["scientific_readiness", "ts_input", "ts_submission"]})

    edge_gate_map = {item["edge_id"]: item for item in edge_gates}
    pilot_nodes = {node_id: item["edge_id"] for item in review["edge_reviews"] for node_id in item["pilot_node_ids"]}
    formal_nodes = {node_id: item["edge_id"] for item in review["edge_reviews"] for node_id in item["formal_ts_node_ids"]}
    node_gates = []
    for node in sorted(plan["nodes"], key=lambda item: item["node_id"]):
        if node["disposition"] not in {"planned", "retained"}:
            node_gates.append({"node_id": node["node_id"], "node_kind": node["node_kind"], "status": "not_applicable", "blockers": []})
            continue
        kind = node["node_kind"]
        edge_ids = node["target"]["edge_ids"]
        blockers: list[str] = []
        if kind == "minimum":
            state_id = node["target"]["state_ids"][0]
            if not any(gate["accepted"] and gate["state_id"] == state_id for gate in minimum_gates.values()):
                blockers.append("accepted_gaussian_minimum_missing")
        elif edge_ids:
            gate = edge_gate_map[edge_ids[0]]
            if kind in TS_KINDS:
                if node["node_id"] in pilot_nodes:
                    if not gate["pilot_ts_input_scientifically_ready"]:
                        blockers.extend(gate["pilot_blockers"])
                elif node["node_id"] in formal_nodes:
                    if not gate["formal_ts_input_scientifically_ready"]:
                        blockers.extend(gate["formal_blockers"])
                else:
                    blockers.append("ts_node_not_classified_as_pilot_or_formal")
            elif kind in IRC_KINDS:
                if not gate["formal_ts_input_scientifically_ready"]:
                    blockers.extend(gate["formal_blockers"])
                if not gate["ts_mode_accepted"]:
                    blockers.append("accepted_ts_mode_missing")
            elif kind == "endpoint":
                if not gate["formal_ts_input_scientifically_ready"]:
                    blockers.extend(gate["formal_blockers"])
                if not gate["bidirectional_irc_accepted"]:
                    blockers.append("bidirectional_irc_endpoint_identification_missing")
            elif kind in {"single_point", "thermochemistry", "sensitivity"}:
                if not gate["formal_ts_input_scientifically_ready"]:
                    blockers.extend(gate["formal_blockers"])
                if not gate["irc_endpoints_reoptimized_as_expected_minima"]:
                    blockers.append("irc_endpoint_reopt_freq_acceptance_missing")
        ready_status = "ready_for_separate_pilot_gate" if node["node_id"] in pilot_nodes else "ready_for_separate_next_gate"
        node_gates.append({"node_id": node["node_id"], "node_kind": kind, "status": "blocked" if blockers else ready_status, "blockers": sorted(set(blockers))})

    summary_blockers = sorted({record["blocker_id"] for record in blocker_records})
    if review["review_decision"] != "accepted":
        summary_blockers.append("scientific_maturity_review_not_accepted")
    return finalize({
        "schema": GATE_SCHEMA,
        "study_id": review["study_id"],
        "review_id": review["review_id"],
        "calculation_plan": plan_binding,
        "review_source": review_binding,
        "scientific_approval_summary": {
            "maturity": "blocked" if summary_blockers else "reviewed",
            "evidence": {"literature_saturated": literature_confirmed, "edge_classes": {item["edge_id"]: item["evidence_class"] for item in edge_gates}},
            "endpoints": {item["edge_id"]: item["endpoint_pair_accepted_and_consistent"] for item in edge_gates},
            "blockers": summary_blockers,
            "route": "owned_by_protocol_selection_not_this_artifact",
            "resources": review["pilot_and_budget"],
            "input_hash": "not_present_in_scientific_maturity_overlay",
        },
        "minimum_gates": [minimum_gates[key] for key in sorted(minimum_gates)],
        "edge_gates": edge_gates,
        "dag_node_gates": node_gates,
        "stop_conditions": review["stop_conditions"],
        "offline_screening_energy_policy": "ff_xtb_offline_results_are_screening_only_not_formal_barriers",
        "failure_policy": "return_to_previous_scientific_stage_without_automatic_candidate_expansion_retry_or_chemistry_change",
        "blockers": blocker_records,
        "calculation_ready": False,
        "no_submission_authorization": True,
    })


def build_gate(plan_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    root = output.parent.absolute()
    dag = _load_calculation_dag()
    try:
        dag.validate_plan(plan_path)
    except Exception as exc:
        raise MaturityError(f"calculation plan owner validation failed: {exc}") from exc
    plan, plan_binding = _binding(plan_path, root, PLAN_SCHEMA)
    review, review_binding = _binding(review_path, root, REVIEW_SCHEMA)
    review = _normalize_review(review, require_hash=True)
    plan["__path"] = str(plan_path)
    artifact = _build_gate(plan, plan_binding, review, review_binding, review_path)
    plan.pop("__path", None)
    write_json(output, artifact)
    return artifact


def validate_gate(path: Path) -> dict[str, Any]:
    artifact = load_json(path)
    require(artifact.get("schema") == GATE_SCHEMA, f"gate schema must be {GATE_SCHEMA}")
    require(artifact.get("payload_sha256") == payload_sha256(artifact), "scientific-maturity gate payload hash is invalid")
    require(artifact.get("calculation_ready") is False and artifact.get("no_submission_authorization") is True, "scientific-maturity gate violates non-authorizing safety constants")
    plan, plan_path = _resolve(artifact["calculation_plan"], path, PLAN_SCHEMA)
    dag = _load_calculation_dag()
    try:
        dag.validate_plan(plan_path)
    except Exception as exc:
        raise MaturityError(f"calculation plan owner validation failed: {exc}") from exc
    review, review_path = _resolve(artifact["review_source"], path, REVIEW_SCHEMA)
    review = _normalize_review(review, require_hash=True)
    plan["__path"] = str(plan_path)
    expected = _build_gate(plan, artifact["calculation_plan"], review, artifact["review_source"], review_path)
    require(artifact == expected, "scientific-maturity gate differs from deterministic reviewed-source reconstruction")
    return artifact


def assert_action(gate_path: Path, edge_id: str, action: str, *, pilot: bool = False, resource_tier: str = "simple", node_id: str | None = None) -> dict[str, Any]:
    artifact = validate_gate(gate_path)
    edge = next((item for item in artifact["edge_gates"] if item["edge_id"] == edge_id), None)
    require(edge is not None, f"scientific-maturity gate has no reviewed edge: {edge_id}")
    require(resource_tier in edge["allowed_resource_tiers"], f"resource tier {resource_tier} lacks reviewed successful-pilot/scale/memory/cost justification")
    if node_id is not None:
        allowed_nodes = edge["pilot_node_ids"] if pilot else edge["formal_ts_node_ids"]
        require(node_id in allowed_nodes, f"node {node_id} is not in the exact {'pilot' if pilot else 'formal'} TS node set for {edge_id}")
    if pilot:
        require(resource_tier == "simple", "low-cost TS pilot must use the simple resource tier")
        ready = edge["pilot_ts_input_scientifically_ready"]
        blockers = edge["pilot_blockers"]
    else:
        ready = edge["formal_ts_input_scientifically_ready"]
        blockers = edge["formal_blockers"]
    if action in {"ts_input", "ts_submission"}:
        require(ready, f"{action} is scientifically blocked for {edge_id}: {', '.join(blockers)}")
    elif action == "irc_input":
        require(not pilot, "IRC input cannot be authorized by the one-candidate TS pilot exception")
        require(edge["formal_ts_input_scientifically_ready"], f"IRC input is scientifically blocked for {edge_id}: {', '.join(edge['formal_blockers'])}")
        require(edge["owner_ts_mode_evidence_valid"], f"IRC input is blocked for {edge_id}: owner-validated TS mode evidence is missing")
        require(edge["ts_mode_accepted"], f"IRC input is blocked for {edge_id}: accepted exactly-one-imaginary mode evidence is missing")
    elif action == "formal_barrier_report":
        require(not pilot, "formal barrier reporting cannot use the TS pilot exception")
        require(edge["formal_ts_input_scientifically_ready"], f"formal barrier reporting is scientifically blocked for {edge_id}: {', '.join(edge['formal_blockers'])}")
        require(edge["owner_ts_mode_evidence_valid"] and edge["owner_irc_path_evidence_valid"], f"formal barrier reporting is blocked for {edge_id}: owner-validated TS and bidirectional IRC evidence are missing")
        require(edge["ts_mode_accepted"] and edge["bidirectional_irc_accepted"], f"formal barrier reporting is blocked for {edge_id}: accepted TS mode and bidirectional IRC evidence are incomplete")
        require(edge["irc_endpoints_reoptimized_as_expected_minima"], f"formal barrier reporting is blocked for {edge_id}: complete IRC endpoint minimum evidence is missing")
        require(edge["owner_energy_lineage_valid"], f"formal barrier reporting is blocked for {edge_id}: owner-validated comparison-eligible energy lineage is missing")
    else:
        raise MaturityError(f"unsupported maturity action: {action}")
    return {
        "schema": "gaussian-scientific-maturity-action-check/1",
        "study_id": artifact["study_id"],
        "edge_id": edge_id,
        "action": action,
        "pilot": pilot,
        "resource_tier": resource_tier,
        "node_id": node_id,
        "scientific_gate_passed": True,
        "separate_input_review_still_required": action == "ts_input",
        "separate_live_approval_still_required": action == "ts_submission",
        "no_submission_authorization": True,
        "maturity_gate_sha256": sha256_file(gate_path),
        "maturity_gate_payload_sha256": artifact["payload_sha256"],
    }


def _make_action_authorization(
    gate_path: Path,
    input_path: Path,
    edge_id: str,
    action: str,
    pilot: bool,
    resource_tier: str,
    node_id: str,
    project: str,
    work_kind: str,
    task_count: int,
    estimated_core_hours: int,
    planned_concurrency: int,
    output: Path,
) -> dict[str, Any]:
    require(action == "ts_submission", "exact action authorization currently supports only the TS submission precheck")
    require(PROJECT_RE.fullmatch(project) is not None, "project must be a 1-15 character PBS-safe name")
    require(work_kind in {"ts_pilot", "formal_ts", "ts_scan"}, "action authorization work_kind must be ts_pilot, formal_ts, or ts_scan")
    require(pilot == (work_kind in {"ts_pilot", "ts_scan"}), "pilot flag and work_kind disagree")
    require(input_path.is_file() and not input_path.is_symlink(), "authorized Gaussian input must be an existing non-symlink file")
    gate = validate_gate(gate_path)
    edge = next((item for item in gate["edge_gates"] if item["edge_id"] == edge_id), None)
    require(edge is not None, f"scientific-maturity gate has no reviewed edge: {edge_id}")
    allowed_nodes = edge["pilot_node_ids"] if pilot else edge["formal_ts_node_ids"]
    require(node_id in allowed_nodes, f"node {node_id} is not in the exact {'pilot' if pilot else 'formal'} TS node set for {edge_id}")
    budget = gate["scientific_approval_summary"]["resources"]["task_budget"]
    require(isinstance(task_count, int) and 1 <= task_count <= budget["max_tasks"], "requested task count exceeds the reviewed budget")
    require(isinstance(estimated_core_hours, int) and 1 <= estimated_core_hours <= budget["max_core_hours"], "estimated core-hours exceed the reviewed budget")
    require(isinstance(planned_concurrency, int) and 1 <= planned_concurrency <= budget["max_concurrent"], "planned concurrency exceeds the reviewed budget")
    action_check = assert_action(gate_path, edge_id, action, pilot=pilot, resource_tier=resource_tier, node_id=node_id)
    root = output.parent.absolute().resolve()
    for label, path in (("maturity gate", gate_path), ("Gaussian input", input_path)):
        try:
            path.absolute().resolve().relative_to(root)
        except ValueError:
            raise MaturityError(f"{label} must share the action-authorization artifact root") from None
    gate_relative = gate_path.absolute().resolve().relative_to(root).as_posix()
    input_relative = input_path.absolute().resolve().relative_to(root).as_posix()
    return finalize({
        "schema": ACTION_AUTHORIZATION_SCHEMA,
        "study_id": gate["study_id"],
        "scientific_maturity": {
            "path": gate_relative, "sha256": sha256_file(gate_path), "size_bytes": gate_path.stat().st_size,
            "schema": gate["schema"], "payload_sha256": gate["payload_sha256"],
        },
        "input": {"path": input_relative, "sha256": sha256_file(input_path), "size_bytes": input_path.stat().st_size},
        "scope": {
            "edge_id": edge_id, "node_id": node_id, "action": action, "pilot": pilot,
            "project": project, "work_kind": work_kind, "resource_tier": resource_tier,
            "task_count": task_count, "estimated_core_hours": estimated_core_hours,
            "planned_concurrency": planned_concurrency,
        },
        "scientific_action_check": action_check,
        "single_exact_scope_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    })


def build_action_authorization(gate_path: Path, input_path: Path, output: Path, **scope: Any) -> dict[str, Any]:
    artifact = _make_action_authorization(gate_path, input_path, output=output, **scope)
    write_json(output, artifact)
    return artifact


def validate_action_authorization(
    path: Path,
    *,
    gate_path: Path | None = None,
    input_sha256: str | None = None,
    edge_id: str | None = None,
    node_id: str | None = None,
    project: str | None = None,
    work_kind: str | None = None,
    resource_tier: str | None = None,
) -> dict[str, Any]:
    artifact = load_json(path)
    require(artifact.get("schema") == ACTION_AUTHORIZATION_SCHEMA, f"action authorization schema must be {ACTION_AUTHORIZATION_SCHEMA}")
    require(artifact.get("payload_sha256") == payload_sha256(artifact), "action authorization payload hash is invalid")
    require(artifact.get("single_exact_scope_only") is True and artifact.get("calculation_ready") is False and artifact.get("no_submission_authorization") is True, "action authorization safety constants are invalid")
    gate, resolved_gate = _resolve(artifact["scientific_maturity"], path, GATE_SCHEMA)
    validate_gate(resolved_gate)
    resolved_input = _resolve_blob(artifact["input"], path, "authorized Gaussian input")
    scope = artifact["scope"]
    expected = _make_action_authorization(
        resolved_gate, resolved_input, scope["edge_id"], scope["action"], scope["pilot"], scope["resource_tier"],
        scope["node_id"], scope["project"], scope["work_kind"], scope["task_count"], scope["estimated_core_hours"],
        scope["planned_concurrency"], path,
    )
    require(artifact == expected, "action authorization differs from deterministic source reconstruction")
    if gate_path is not None:
        require(resolved_gate.resolve() == gate_path.resolve(), "action authorization is bound to a different maturity gate")
    if input_sha256 is not None:
        require(artifact["input"]["sha256"] == input_sha256, "action authorization is bound to a different Gaussian input")
    for label, actual, requested in (("edge", scope["edge_id"], edge_id), ("node", scope["node_id"], node_id), ("project", scope["project"], project), ("work kind", scope["work_kind"], work_kind), ("resource tier", scope["resource_tier"], resource_tier)):
        if requested is not None:
            require(actual == requested, f"action authorization {label} scope differs")
    return artifact


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    finalize_parser = commands.add_parser("finalize-review", help="normalize and hash one maturity-review draft")
    finalize_parser.add_argument("draft", type=Path)
    finalize_parser.add_argument("--output", type=Path, required=True)
    build_parser = commands.add_parser("build", help="build the immutable maturity overlay over one validated calculation plan")
    build_parser.add_argument("calculation_plan", type=Path)
    build_parser.add_argument("--review", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate", help="validate and independently reconstruct one maturity overlay")
    validate_parser.add_argument("artifact", type=Path)
    check_parser = commands.add_parser("check-action", help="fail closed unless one edge is scientifically ready for the requested next gate")
    check_parser.add_argument("artifact", type=Path)
    check_parser.add_argument("--edge-id", required=True)
    check_parser.add_argument("--node-id")
    check_parser.add_argument("--action", choices=["ts_input", "ts_submission", "irc_input", "formal_barrier_report"], required=True)
    check_parser.add_argument("--pilot", action="store_true")
    check_parser.add_argument("--resource-tier", choices=["simple", "general", "complex"], default="simple")
    authorize_parser = commands.add_parser("authorize-action", help="bind a passed science gate to one exact input/project/node/budget scope without granting live authority")
    authorize_parser.add_argument("artifact", type=Path)
    authorize_parser.add_argument("--input", type=Path, required=True)
    authorize_parser.add_argument("--edge-id", required=True)
    authorize_parser.add_argument("--node-id", required=True)
    authorize_parser.add_argument("--action", choices=["ts_submission"], required=True)
    authorize_parser.add_argument("--pilot", action="store_true")
    authorize_parser.add_argument("--resource-tier", choices=["simple", "general", "complex"], required=True)
    authorize_parser.add_argument("--project", required=True)
    authorize_parser.add_argument("--work-kind", choices=["ts_pilot", "formal_ts", "ts_scan"], required=True)
    authorize_parser.add_argument("--task-count", type=int, required=True)
    authorize_parser.add_argument("--estimated-core-hours", type=int, required=True)
    authorize_parser.add_argument("--planned-concurrency", type=int, required=True)
    authorize_parser.add_argument("--output", type=Path, required=True)
    validate_authorization_parser = commands.add_parser("validate-action-authorization", help="reconstruct one exact offline action authorization")
    validate_authorization_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "finalize-review":
            artifact = finalize_review(args.draft, args.output)
            result = {"schema": "gaussian-scientific-maturity-review-finalization/1", "payload_sha256": artifact["payload_sha256"], "live_actions": False}
        elif args.command == "build":
            artifact = build_gate(args.calculation_plan, args.review, args.output)
            result = {"schema": "gaussian-scientific-maturity-gate-build/1", "study_id": artifact["study_id"], "maturity": artifact["scientific_approval_summary"]["maturity"], "payload_sha256": artifact["payload_sha256"], "live_actions": False}
        elif args.command == "validate":
            artifact = validate_gate(args.artifact)
            result = {"schema": "gaussian-scientific-maturity-gate-validation/1", "study_id": artifact["study_id"], "maturity": artifact["scientific_approval_summary"]["maturity"], "payload_sha256": artifact["payload_sha256"], "live_actions": False}
        elif args.command == "check-action":
            result = assert_action(args.artifact, args.edge_id, args.action, pilot=args.pilot, resource_tier=args.resource_tier, node_id=args.node_id)
        elif args.command == "authorize-action":
            artifact = build_action_authorization(
                args.artifact, args.input, args.output, edge_id=args.edge_id, action=args.action, pilot=args.pilot,
                resource_tier=args.resource_tier, node_id=args.node_id, project=args.project, work_kind=args.work_kind,
                task_count=args.task_count, estimated_core_hours=args.estimated_core_hours, planned_concurrency=args.planned_concurrency,
            )
            result = {"schema": "gaussian-scientific-action-authorization-build/1", "payload_sha256": artifact["payload_sha256"], "live_actions": False, "no_submission_authorization": True}
        else:
            artifact = validate_action_authorization(args.artifact)
            result = {"schema": "gaussian-scientific-action-authorization-validation/1", "payload_sha256": artifact["payload_sha256"], "live_actions": False, "no_submission_authorization": True}
    except (MaturityError, OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
