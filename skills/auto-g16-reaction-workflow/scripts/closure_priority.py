#!/usr/bin/env python3
"""Build and validate offline closure-priority plans.

The builder ranks only routes that have already passed every scientific hard
gate and that contain a complete or conditionally complete TS/Freq -> reviewed
mode -> separately approved bidirectional IRC -> identified endpoints ->
conditional endpoint Opt/Freq decision DAG.  It never renders an input,
submits work, retries work, or expands a search.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import reaction_workflow as rw  # noqa: E402


REQUEST_SCHEMA = "gaussian-closure-priority-request/1"
PLAN_SCHEMA = "gaussian-closure-priority-plan/1"
GOAL = (
    "use as few PBS jobs as practical while answering the most important "
    "scientific questions and pursuing a reliable closure."
)
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

HARD_GATES = (
    "reviewed_mechanism_and_active_state",
    "exact_atom_mapping_and_state",
    "accepted_endpoint_minima_where_required",
    "method_evidence_and_explicit_method_decision",
    "user_confirmation",
    "budget",
    "duplicate_and_state_collapse_checks",
)
DIMENSIONS = (
    "scientific_value_information_gain",
    "evidence_strength",
    "mapping_clarity",
    "initial_guess_quality",
    "convergence_likelihood",
    "expected_closure_likelihood",
    "dependency_reuse",
)
BANDS = {"high", "medium", "low", "unknown"}
BAND_ORDER = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
CALIBRATION_BASES = {
    "direct_evidence",
    "analogous_evidence",
    "reviewed_judgment",
    "historical_outcomes",
    "unavailable",
}
STAGE_KINDS = {
    "ts_freq",
    "imaginary_mode_review",
    "irc_forward",
    "irc_reverse",
    "endpoint_identification",
    "endpoint_opt_freq",
}
STAGE_ORDER = {
    "ts_freq": 0,
    "imaginary_mode_review": 1,
    "irc_forward": 2,
    "irc_reverse": 2,
    "endpoint_identification": 3,
    "endpoint_opt_freq": 4,
}
CONDITIONS = {
    "always_after_separate_approval",
    "after_accepted_ts_freq",
    "after_reviewed_intended_imaginary_mode",
    "after_both_irc_directions_terminate",
    "when_scientifically_necessary",
}
DISPOSITIONS = {"candidate", "deferred", "rejected"}
PATH_CLASSES = {"primary", "low_probability_exploration"}


class ClosurePriorityError(rw.OfflineError):
    """One closure-priority contract rule was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ClosurePriorityError(message)


def require_keys(value: Any, required: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    actual = set(value)
    require(actual == required, f"{label} fields must be exactly {sorted(required)}; got {sorted(actual)}")
    return value


def text(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    return value


def identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} is not a valid id")
    return value


def string_list(value: Any, label: str, *, minimum: int = 1) -> list[str]:
    require(isinstance(value, list) and len(value) >= minimum, f"{label} must contain at least {minimum} item(s)")
    result = [text(item, f"{label} item") for item in value]
    require(len(set(result)) == len(result), f"{label} must not contain duplicates")
    return result


def finite_nonnegative(value: Any, label: str) -> float | int:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    require(math.isfinite(value) and value >= 0, f"{label} must be finite and non-negative")
    return value


def reject_probability_fields(value: Any, label: str = "request") -> None:
    """Refuse numeric-probability fields while allowing named likelihood bands."""

    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            forbidden = (
                lowered in {"probability", "probabilities", "percentage", "percent", "numeric_score", "likelihood_score"}
                or lowered.endswith("_probability")
                or lowered.endswith("_percentage")
            )
            require(not forbidden, f"{label}.{key}: numeric or asserted probability fields are forbidden")
            reject_probability_fields(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_probability_fields(child, f"{label}[{index}]")


def normalize_band(value: Any, label: str) -> dict[str, str]:
    item = require_keys(value, {"band", "calibration"}, label)
    band = item["band"]
    require(band in BANDS, f"{label}.band must be high, medium, low, or unknown")
    calibration = require_keys(item["calibration"], {"basis", "provenance"}, f"{label}.calibration")
    basis = calibration["basis"]
    require(basis in CALIBRATION_BASES, f"{label}.calibration.basis is invalid")
    provenance = text(calibration["provenance"], f"{label}.calibration.provenance")
    if band == "unknown":
        require(basis == "unavailable", f"{label}: unknown must record unavailable calibration provenance")
    else:
        require(basis != "unavailable", f"{label}: a non-unknown band requires actual calibration provenance")
    return {"band": band, "calibration": {"basis": basis, "provenance": provenance}}


def normalize_gate(value: Any, label: str) -> dict[str, Any]:
    item = require_keys(value, {"status", "reason", "evidence_refs"}, label)
    require(item["status"] in {"pass", "block"}, f"{label}.status must be pass or block")
    return {
        "status": item["status"],
        "reason": text(item["reason"], f"{label}.reason"),
        "evidence_refs": string_list(item["evidence_refs"], f"{label}.evidence_refs"),
    }


def normalize_cost(value: Any, label: str) -> dict[str, Any]:
    item = require_keys(value, {"pbs_jobs", "core_hours", "estimate_confidence"}, label)
    ranges: dict[str, dict[str, float | int]] = {}
    for name in ("pbs_jobs", "core_hours"):
        interval = require_keys(item[name], {"minimum", "maximum"}, f"{label}.{name}")
        minimum = finite_nonnegative(interval["minimum"], f"{label}.{name}.minimum")
        maximum = finite_nonnegative(interval["maximum"], f"{label}.{name}.maximum")
        require(minimum <= maximum, f"{label}.{name} minimum exceeds maximum")
        if name == "pbs_jobs":
            require(isinstance(minimum, int) and isinstance(maximum, int), f"{label}.pbs_jobs must use integers")
        ranges[name] = {"minimum": minimum, "maximum": maximum}
    ranges["estimate_confidence"] = normalize_band(item["estimate_confidence"], f"{label}.estimate_confidence")
    return ranges


def normalize_stage(value: Any, label: str) -> dict[str, Any]:
    item = require_keys(
        value,
        {
            "node_id",
            "stage_kind",
            "depends_on",
            "condition",
            "separate_approval_required",
            "evidence_requirement",
            "continue_conditions",
            "stop_conditions",
        },
        label,
    )
    node_id = identifier(item["node_id"], f"{label}.node_id")
    kind = item["stage_kind"]
    require(kind in STAGE_KINDS, f"{label}.stage_kind is invalid")
    depends_on = string_list(item["depends_on"], f"{label}.depends_on", minimum=0)
    for dependency in depends_on:
        identifier(dependency, f"{label}.depends_on")
    require(item["condition"] in CONDITIONS, f"{label}.condition is invalid")
    require(isinstance(item["separate_approval_required"], bool), f"{label}.separate_approval_required must be boolean")
    return {
        "node_id": node_id,
        "stage_kind": kind,
        "depends_on": depends_on,
        "condition": item["condition"],
        "separate_approval_required": item["separate_approval_required"],
        "evidence_requirement": text(item["evidence_requirement"], f"{label}.evidence_requirement"),
        "continue_conditions": string_list(item["continue_conditions"], f"{label}.continue_conditions"),
        "stop_conditions": string_list(item["stop_conditions"], f"{label}.stop_conditions"),
        "executable": False,
    }


def normalize_bundle(value: Any, label: str) -> tuple[dict[str, Any], list[str]]:
    item = require_keys(value, {"bundle_id", "completeness", "stages"}, label)
    bundle_id = identifier(item["bundle_id"], f"{label}.bundle_id")
    require(item["completeness"] in {"complete", "conditionally_complete", "partial"}, f"{label}.completeness is invalid")
    require(isinstance(item["stages"], list) and item["stages"], f"{label}.stages must be non-empty")
    stages = [normalize_stage(stage, f"{label}.stages[{index}]") for index, stage in enumerate(item["stages"])]
    by_id = {stage["node_id"]: stage for stage in stages}
    require(len(by_id) == len(stages), f"{label}.stages contains duplicate node ids")
    kinds: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        kinds.setdefault(stage["stage_kind"], []).append(stage)
        for dependency in stage["depends_on"]:
            require(dependency in by_id, f"{label}: unknown dependency {dependency}")
            require(
                STAGE_ORDER[by_id[dependency]["stage_kind"]] < STAGE_ORDER[stage["stage_kind"]],
                f"{label}: dependency {dependency} does not precede {stage['node_id']}",
            )

    reasons: list[str] = []
    missing = sorted(STAGE_KINDS - set(kinds))
    if missing:
        reasons.append("closure bundle omits required stage kinds: " + ", ".join(missing))
    for singleton in ("ts_freq", "imaginary_mode_review", "irc_forward", "irc_reverse", "endpoint_identification"):
        if len(kinds.get(singleton, [])) != 1:
            reasons.append(f"closure bundle requires exactly one {singleton} stage")
    if not kinds.get("endpoint_opt_freq"):
        reasons.append("closure bundle requires a conditional endpoint_opt_freq stage")

    if not reasons:
        ts = kinds["ts_freq"][0]
        mode = kinds["imaginary_mode_review"][0]
        forward = kinds["irc_forward"][0]
        reverse = kinds["irc_reverse"][0]
        endpoints = kinds["endpoint_identification"][0]
        require(not ts["depends_on"], f"{label}: TS/Freq must be the first closure stage")
        require(
            ts["condition"] == "always_after_separate_approval",
            f"{label}: TS/Freq must remain behind separate approval",
        )
        require(mode["depends_on"] == [ts["node_id"]], f"{label}: imaginary-mode review must depend on TS/Freq")
        require(
            mode["condition"] == "after_accepted_ts_freq",
            f"{label}: imaginary-mode review must follow accepted TS/Freq evidence",
        )
        require(
            "intended reaction coordinate" in mode["evidence_requirement"].lower(),
            f"{label}: imaginary-mode review must explicitly require the intended reaction coordinate",
        )
        for irc, direction in ((forward, "forward"), (reverse, "reverse")):
            require(irc["depends_on"] == [mode["node_id"]], f"{label}: {direction} IRC must depend on mode review")
            require(
                irc["condition"] == "after_reviewed_intended_imaginary_mode",
                f"{label}: {direction} IRC must follow reviewed intended-mode evidence",
            )
            require(irc["separate_approval_required"] is True, f"{label}: {direction} IRC requires separate approval")
        require(
            set(endpoints["depends_on"]) == {forward["node_id"], reverse["node_id"]},
            f"{label}: endpoint identification must depend on both IRC directions",
        )
        require(
            endpoints["condition"] == "after_both_irc_directions_terminate",
            f"{label}: endpoint identification must wait for both IRC directions",
        )
        require(
            "structur" in endpoints["evidence_requirement"].lower(),
            f"{label}: endpoints must be structurally identified",
        )
        for endpoint_opt in kinds["endpoint_opt_freq"]:
            require(
                endpoint_opt["depends_on"] == [endpoints["node_id"]],
                f"{label}: endpoint Opt/Freq must depend on endpoint identification",
            )
            require(
                endpoint_opt["condition"] == "when_scientifically_necessary",
                f"{label}: endpoint Opt/Freq must remain conditional on scientific necessity",
            )
            require(
                endpoint_opt["separate_approval_required"] is True,
                f"{label}: endpoint Opt/Freq requires a separate future approval",
            )

    if item["completeness"] == "partial":
        reasons.append("bundle is explicitly partial and cannot enter closure ranking")
    if reasons and item["completeness"] != "partial":
        reasons.append("declared complete bundle does not supply a practical closure")
    return {
        "bundle_id": bundle_id,
        "completeness": item["completeness"],
        "stages": stages,
    }, reasons


def normalize_route(value: Any, index: int, budget: dict[str, Any]) -> dict[str, Any]:
    label = f"routes[{index}]"
    item = require_keys(
        value,
        {
            "route_id",
            "label",
            "scientific_question",
            "path_class",
            "review_disposition",
            "disposition_reason",
            "explicit_low_probability_review",
            "hard_gates",
            "dimensions",
            "estimated_cost",
            "bundle",
        },
        label,
    )
    route_id = identifier(item["route_id"], f"{label}.route_id")
    require(item["path_class"] in PATH_CLASSES, f"{label}.path_class is invalid")
    require(item["review_disposition"] in DISPOSITIONS, f"{label}.review_disposition is invalid")
    reason = item["disposition_reason"]
    require(reason is None or isinstance(reason, str), f"{label}.disposition_reason must be string or null")
    if item["review_disposition"] != "candidate":
        text(reason, f"{label}.disposition_reason")
    require(isinstance(item["explicit_low_probability_review"], bool), f"{label}.explicit_low_probability_review must be boolean")
    if item["path_class"] == "low_probability_exploration":
        require(item["explicit_low_probability_review"] is True, f"{label}: low-probability exploration requires explicit review")

    gates_raw = require_keys(item["hard_gates"], set(HARD_GATES), f"{label}.hard_gates")
    gates = {name: normalize_gate(gates_raw[name], f"{label}.hard_gates.{name}") for name in HARD_GATES}
    dimensions_raw = require_keys(item["dimensions"], set(DIMENSIONS), f"{label}.dimensions")
    dimensions = {name: normalize_band(dimensions_raw[name], f"{label}.dimensions.{name}") for name in DIMENSIONS}
    if dimensions["expected_closure_likelihood"]["band"] == "low":
        require(
            item["path_class"] == "low_probability_exploration",
            f"{label}: low expected closure likelihood must be classified as low-probability exploration",
        )
    if item["path_class"] == "low_probability_exploration":
        require(
            dimensions["expected_closure_likelihood"]["band"] == "low",
            f"{label}: low-probability exploration must retain a low expected-closure band",
        )
    cost = normalize_cost(item["estimated_cost"], f"{label}.estimated_cost")
    bundle, bundle_reasons = normalize_bundle(item["bundle"], f"{label}.bundle")

    if cost["pbs_jobs"]["maximum"] > budget["pbs_jobs"] or cost["core_hours"]["maximum"] > budget["core_hours"]:
        gates["budget"] = {
            "status": "block",
            "reason": "estimated maximum cost exceeds the reviewed plan budget",
            "evidence_refs": ["selection_policy:budget"],
        }
    eligibility_reasons = [gates[name]["reason"] for name in HARD_GATES if gates[name]["status"] == "block"]
    eligibility_reasons.extend(bundle_reasons)
    if item["review_disposition"] != "candidate":
        eligibility_reasons.append(reason.strip())

    return {
        "route_id": route_id,
        "label": text(item["label"], f"{label}.label"),
        "scientific_question": text(item["scientific_question"], f"{label}.scientific_question"),
        "path_class": item["path_class"],
        "review_disposition": item["review_disposition"],
        "disposition_reason": reason,
        "explicit_low_probability_review": item["explicit_low_probability_review"],
        "hard_gates": gates,
        "dimensions": dimensions,
        "estimated_cost": cost,
        "bundle": bundle,
        "eligible_for_ranking": not eligibility_reasons,
        "eligibility_reasons": eligibility_reasons,
        "rank": None,
        "selected": False,
        "selection_reason": "not ranked because one or more eligibility conditions failed" if eligibility_reasons else "eligible; awaiting auditable ranking",
    }


def ranking_key(route: dict[str, Any]) -> tuple[Any, ...]:
    # Cost is deliberately last: necessary evidence and scientific value are
    # never traded away merely to obtain the absolute mathematical minimum.
    return tuple(-BAND_ORDER[route["dimensions"][name]["band"]] for name in DIMENSIONS) + (
        route["estimated_cost"]["pbs_jobs"]["maximum"],
        route["estimated_cost"]["core_hours"]["maximum"],
        route["route_id"],
    )


def normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    reject_probability_fields(request)
    top = require_keys(
        request,
        {"schema", "study_id", "plan_id", "goal", "selection_policy", "routes"},
        "request",
    )
    require(top["schema"] == REQUEST_SCHEMA, f"request.schema must be {REQUEST_SCHEMA}")
    require(top["goal"] == GOAL, "request.goal must use the exact practical-closure wording")
    policy = require_keys(
        top["selection_policy"],
        {"budget", "include_low_probability_exploration", "reviewed_by", "reviewed_at", "review_rationale"},
        "selection_policy",
    )
    budget = require_keys(policy["budget"], {"pbs_jobs", "core_hours"}, "selection_policy.budget")
    normalized_budget = {
        "pbs_jobs": finite_nonnegative(budget["pbs_jobs"], "selection_policy.budget.pbs_jobs"),
        "core_hours": finite_nonnegative(budget["core_hours"], "selection_policy.budget.core_hours"),
    }
    require(isinstance(normalized_budget["pbs_jobs"], int), "selection_policy.budget.pbs_jobs must be an integer")
    require(isinstance(policy["include_low_probability_exploration"], bool), "include_low_probability_exploration must be boolean")
    require(isinstance(top["routes"], list) and top["routes"], "request.routes must be non-empty")
    routes = [normalize_route(route, index, normalized_budget) for index, route in enumerate(top["routes"])]
    route_ids = [route["route_id"] for route in routes]
    require(len(set(route_ids)) == len(route_ids), "route ids must be unique")
    node_ids = [stage["node_id"] for route in routes for stage in route["bundle"]["stages"]]
    require(len(set(node_ids)) == len(node_ids), "decision-DAG node ids must be globally unique")
    return {
        "schema": REQUEST_SCHEMA,
        "study_id": identifier(top["study_id"], "request.study_id"),
        "plan_id": identifier(top["plan_id"], "request.plan_id"),
        "goal": GOAL,
        "selection_policy": {
            "budget": normalized_budget,
            "include_low_probability_exploration": policy["include_low_probability_exploration"],
            "reviewed_by": text(policy["reviewed_by"], "selection_policy.reviewed_by"),
            "reviewed_at": text(policy["reviewed_at"], "selection_policy.reviewed_at"),
            "review_rationale": text(policy["review_rationale"], "selection_policy.review_rationale"),
        },
        "routes": routes,
    }


def derive_plan(request: dict[str, Any], request_sha256: str) -> dict[str, Any]:
    normalized = normalize_request(copy.deepcopy(request))
    routes = normalized["routes"]
    ranked = sorted((route for route in routes if route["eligible_for_ranking"]), key=ranking_key)
    for rank, route in enumerate(ranked, start=1):
        route["rank"] = rank
        route["selection_reason"] = "eligible after all hard gates and closure-completeness checks"

    selected: list[dict[str, Any]] = []
    primary = [route for route in ranked if route["path_class"] == "primary"]
    if primary:
        primary[0]["selected"] = True
        primary[0]["selection_reason"] = "highest-ranked practical complete or conditionally complete primary closure bundle"
        selected.append(primary[0])

    if normalized["selection_policy"]["include_low_probability_exploration"] and selected:
        used_jobs = sum(route["estimated_cost"]["pbs_jobs"]["maximum"] for route in selected)
        used_hours = sum(route["estimated_cost"]["core_hours"]["maximum"] for route in selected)
        for route in ranked:
            if route["path_class"] != "low_probability_exploration":
                continue
            fits = (
                used_jobs + route["estimated_cost"]["pbs_jobs"]["maximum"] <= normalized["selection_policy"]["budget"]["pbs_jobs"]
                and used_hours + route["estimated_cost"]["core_hours"]["maximum"] <= normalized["selection_policy"]["budget"]["core_hours"]
            )
            if fits:
                route["selected"] = True
                route["selection_reason"] = "explicitly reviewed low-probability exploration selected only from remaining budget"
                selected.append(route)
                break
            route["selection_reason"] = "deferred: no reviewed remaining budget after the primary closure bundle"

    for route in ranked:
        if not route["selected"] and route["selection_reason"].startswith("eligible"):
            route["selection_reason"] = "deferred to keep the plan to as few practical closure bundles as possible"

    dag_nodes = [copy.deepcopy(stage) for route in selected for stage in route["bundle"]["stages"]]
    topological = sorted(dag_nodes, key=lambda node: (STAGE_ORDER[node["stage_kind"]], node["node_id"]))
    deferred = []
    for route in routes:
        if not route["selected"]:
            reasons = route["eligibility_reasons"] or [route["selection_reason"]]
            disposition = "rejected" if route["review_disposition"] == "rejected" else "deferred"
            deferred.append({"route_id": route["route_id"], "disposition": disposition, "reasons": reasons})

    plan = {
        "schema": PLAN_SCHEMA,
        "study_id": normalized["study_id"],
        "plan_id": normalized["plan_id"],
        "goal": GOAL,
        "request_binding": {"schema": REQUEST_SCHEMA, "sha256": request_sha256},
        "planning_policy": {
            "selection_rule": "smallest_practical_complete_or_conditionally_complete_bundle",
            "absolute_mathematical_job_minimum": False,
            "necessary_evidence_may_be_omitted": False,
            "hard_gates_precede_ranking": True,
            "simple_cartesian_combination_enumeration": False,
            "automatic_search_expansion_after_failure": False,
            "automatic_retry": False,
            "low_probability_exploration_requires_remaining_budget_and_explicit_review": True,
        },
        "selection_policy": normalized["selection_policy"],
        "ranking_dimensions": list(DIMENSIONS) + ["estimated_pbs_and_core_hour_cost"],
        "routes": routes,
        "ranked_route_ids": [route["route_id"] for route in ranked],
        "selected_bundle_ids": [route["bundle"]["bundle_id"] for route in selected],
        "decision_dag": {
            "nodes": dag_nodes,
            "topological_order": [node["node_id"] for node in topological],
        },
        "deferred_or_rejected_paths": deferred,
        "executable": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "no_automatic_retry": True,
        "no_automatic_search_expansion": True,
    }
    return rw.finalize_artifact(plan)


def validate_plan_document(plan: dict[str, Any]) -> dict[str, Any]:
    require(plan.get("schema") == PLAN_SCHEMA, f"artifact.schema must be {PLAN_SCHEMA}")
    rw.validate_payload_hash(plan)
    require(plan.get("goal") == GOAL, "artifact goal wording changed")
    require(plan.get("executable") is False and plan.get("calculation_ready") is False, "plan must remain non-executable")
    require(plan.get("no_submission_authorization") is True, "plan must not authorize submission")
    require(plan.get("no_automatic_retry") is True, "plan must forbid automatic retry")
    require(plan.get("no_automatic_search_expansion") is True, "plan must forbid automatic search expansion")
    policy = plan.get("planning_policy", {})
    require(policy.get("hard_gates_precede_ranking") is True, "hard gates must precede ranking")
    require(policy.get("absolute_mathematical_job_minimum") is False, "absolute mathematical minimum must not be the objective")
    require(policy.get("necessary_evidence_may_be_omitted") is False, "necessary evidence may not be omitted")
    reject_probability_fields(plan, "artifact")
    request_binding = require_keys(plan.get("request_binding"), {"schema", "sha256"}, "artifact.request_binding")
    require(request_binding["schema"] == REQUEST_SCHEMA, "artifact request schema changed")
    require(
        isinstance(request_binding["sha256"], str) and rw.SHA256_RE.fullmatch(request_binding["sha256"]) is not None,
        "artifact request SHA-256 is invalid",
    )
    routes = plan.get("routes")
    require(isinstance(routes, list) and routes, "artifact.routes must be non-empty")
    input_route_fields = {
        "route_id",
        "label",
        "scientific_question",
        "path_class",
        "review_disposition",
        "disposition_reason",
        "explicit_low_probability_review",
        "hard_gates",
        "dimensions",
        "estimated_cost",
        "bundle",
    }
    reconstructed_routes = []
    for route in routes:
        require(isinstance(route, dict), "artifact route must be an object")
        reconstructed = {key: copy.deepcopy(route[key]) for key in input_route_fields if key != "bundle" and key in route}
        require(set(reconstructed) == input_route_fields - {"bundle"}, "artifact route input fields are incomplete")
        bundle = route.get("bundle")
        require(isinstance(bundle, dict), "artifact route bundle must be an object")
        stages = bundle.get("stages")
        require(isinstance(stages, list), "artifact route bundle stages must be an array")
        reconstructed["bundle"] = {
            "bundle_id": bundle.get("bundle_id"),
            "completeness": bundle.get("completeness"),
            "stages": [
                {key: copy.deepcopy(value) for key, value in stage.items() if key != "executable"}
                for stage in stages
            ],
        }
        reconstructed_routes.append(reconstructed)
    reconstructed_request = {
        "schema": REQUEST_SCHEMA,
        "study_id": plan.get("study_id"),
        "plan_id": plan.get("plan_id"),
        "goal": plan.get("goal"),
        "selection_policy": copy.deepcopy(plan.get("selection_policy")),
        "routes": reconstructed_routes,
    }
    rebuilt = derive_plan(reconstructed_request, request_binding["sha256"])
    require(plan == rebuilt, "artifact does not match deterministic gate, ranking, selection, or decision-DAG replay")
    ranked_ids = plan["ranked_route_ids"]
    selected_routes = [route for route in routes if route["selected"] is True]
    return {
        "schema": PLAN_SCHEMA,
        "valid": True,
        "payload_sha256": plan["payload_sha256"],
        "ranked_route_count": len(ranked_ids),
        "selected_bundle_count": len(selected_routes),
        "live_actions": False,
        "no_submission_authorization": True,
    }


def build(request_path: Path, output_path: Path) -> dict[str, Any]:
    require(not request_path.is_symlink(), "request symlinks are forbidden")
    require(not output_path.exists(), f"refusing to overwrite existing artifact: {output_path}")
    request = rw.load_json(request_path)
    plan = derive_plan(request, rw.sha256_file(request_path))
    validate_plan_document(plan)
    rw.write_json(output_path, plan)
    return validate_plan_document(plan)


def validate(path: Path) -> dict[str, Any]:
    require(not path.is_symlink(), "artifact symlinks are forbidden")
    return validate_plan_document(rw.load_json(path))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="build one immutable offline closure-priority plan")
    builder.add_argument("request", type=Path)
    builder.add_argument("--output", type=Path, required=True)
    checker = commands.add_parser("validate", help="validate one closure-priority plan")
    checker.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build(args.request, args.output) if args.command == "build" else validate(args.artifact)
    except (ClosurePriorityError, rw.OfflineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
