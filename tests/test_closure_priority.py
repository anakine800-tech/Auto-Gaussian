#!/usr/bin/env python3
"""Focused offline tests for closure-priority planning."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "closure_priority.py"
SCHEMA = ROOT / "contracts" / "reaction-workflow" / "closure-priority-plan.schema.json"
SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLOSURE = load_module("closure_priority_test", TOOL)
SCHEMA_VALIDATOR = load_module("closure_priority_schema_test", SCHEMA_VALIDATOR_PATH)


def calibrated(band: str, basis: str = "reviewed_judgment") -> dict:
    if band == "unknown":
        basis = "unavailable"
    return {
        "band": band,
        "calibration": {
            "basis": basis,
            "provenance": "Reviewed synthetic fixture; no numeric probability asserted.",
        },
    }


def stages(prefix: str) -> list[dict]:
    ts = f"{prefix}_ts_freq"
    mode = f"{prefix}_mode_review"
    forward = f"{prefix}_irc_forward"
    reverse = f"{prefix}_irc_reverse"
    endpoints = f"{prefix}_endpoints"
    endpoint_opt = f"{prefix}_endpoint_opt"
    return [
        {
            "node_id": ts,
            "stage_kind": "ts_freq",
            "depends_on": [],
            "condition": "always_after_separate_approval",
            "separate_approval_required": True,
            "evidence_requirement": "Accepted TS optimization and complete frequency evidence.",
            "continue_conditions": ["TS/Freq terminates and is eligible for scientific mode review."],
            "stop_conditions": ["Stop on failure, state collapse, or an unreviewed result; do not expand the search."],
        },
        {
            "node_id": mode,
            "stage_kind": "imaginary_mode_review",
            "depends_on": [ts],
            "condition": "after_accepted_ts_freq",
            "separate_approval_required": False,
            "evidence_requirement": "Exactly one imaginary mode explicitly reviewed as the intended reaction coordinate.",
            "continue_conditions": ["A human review accepts the intended imaginary mode."],
            "stop_conditions": ["Stop when the mode is wrong, ambiguous, or unreviewed."],
        },
        {
            "node_id": forward,
            "stage_kind": "irc_forward",
            "depends_on": [mode],
            "condition": "after_reviewed_intended_imaginary_mode",
            "separate_approval_required": True,
            "evidence_requirement": "Separately approved forward IRC with retained terminal evidence.",
            "continue_conditions": ["Forward IRC terminates for later endpoint identification."],
            "stop_conditions": ["Stop on failure; do not retry or alter chemistry automatically."],
        },
        {
            "node_id": reverse,
            "stage_kind": "irc_reverse",
            "depends_on": [mode],
            "condition": "after_reviewed_intended_imaginary_mode",
            "separate_approval_required": True,
            "evidence_requirement": "Separately approved reverse IRC with retained terminal evidence.",
            "continue_conditions": ["Reverse IRC terminates for later endpoint identification."],
            "stop_conditions": ["Stop on failure; do not retry or alter chemistry automatically."],
        },
        {
            "node_id": endpoints,
            "stage_kind": "endpoint_identification",
            "depends_on": [forward, reverse],
            "condition": "after_both_irc_directions_terminate",
            "separate_approval_required": False,
            "evidence_requirement": "Both endpoints are structurally identified against reviewed states and atom mapping.",
            "continue_conditions": ["Both endpoint identities are accepted."],
            "stop_conditions": ["Stop if either endpoint is missing, ambiguous, or maps to an unintended state."],
        },
        {
            "node_id": endpoint_opt,
            "stage_kind": "endpoint_opt_freq",
            "depends_on": [endpoints],
            "condition": "when_scientifically_necessary",
            "separate_approval_required": True,
            "evidence_requirement": "Endpoint Opt/Freq only where a reviewed scientific reason requires minimum closure.",
            "continue_conditions": ["Required endpoint minimum evidence is accepted."],
            "stop_conditions": ["Do not run when existing accepted endpoint minima already close the question."],
        },
    ]


def route(route_id: str, *, band: str = "medium", jobs: int = 5, path_class: str = "primary") -> dict:
    pass_gate = {
        "status": "pass",
        "reason": "Reviewed evidence satisfies this hard gate for the synthetic route.",
        "evidence_refs": [f"review:{route_id}"],
    }
    dimensions = {
        name: calibrated(band)
        for name in CLOSURE.DIMENSIONS
    }
    return {
        "route_id": route_id,
        "label": f"Connected closure route {route_id}",
        "scientific_question": "Does this reviewed elementary step close to the intended mapped endpoints?",
        "path_class": path_class,
        "review_disposition": "candidate",
        "disposition_reason": None,
        "explicit_low_probability_review": path_class == "low_probability_exploration",
        "hard_gates": {name: copy.deepcopy(pass_gate) for name in CLOSURE.HARD_GATES},
        "dimensions": dimensions,
        "estimated_cost": {
            "pbs_jobs": {"minimum": jobs - 1, "maximum": jobs},
            "core_hours": {"minimum": jobs * 4, "maximum": jobs * 8},
            "estimate_confidence": calibrated("medium", "historical_outcomes"),
        },
        "bundle": {
            "bundle_id": f"{route_id}_bundle",
            "completeness": "conditionally_complete",
            "stages": stages(route_id),
        },
    }


def request(*routes: dict) -> dict:
    return {
        "schema": CLOSURE.REQUEST_SCHEMA,
        "study_id": "synthetic_closure_study",
        "plan_id": "synthetic_closure_plan",
        "goal": CLOSURE.GOAL,
        "selection_policy": {
            "budget": {"pbs_jobs": 20, "core_hours": 200},
            "include_low_probability_exploration": False,
            "reviewed_by": "synthetic human reviewer",
            "reviewed_at": "2026-07-19T10:00:00+08:00",
            "review_rationale": "Prefer one practical evidence-complete closure family.",
        },
        "routes": list(routes),
    }


class ClosurePriorityTests(unittest.TestCase):
    def test_standard_connected_closure_family_is_non_executable_and_schema_valid(self) -> None:
        plan = CLOSURE.derive_plan(request(route("connected")), "a" * 64)
        summary = CLOSURE.validate_plan_document(plan)
        self.assertTrue(summary["valid"])
        self.assertEqual(plan["selected_bundle_ids"], ["connected_bundle"])
        self.assertEqual(
            [node["stage_kind"] for node in plan["decision_dag"]["nodes"]],
            ["ts_freq", "imaginary_mode_review", "irc_forward", "irc_reverse", "endpoint_identification", "endpoint_opt_freq"],
        )
        self.assertTrue(all(node["executable"] is False for node in plan["decision_dag"]["nodes"]))
        self.assertFalse(plan["executable"])
        self.assertTrue(plan["no_submission_authorization"])
        self.assertTrue(plan["no_automatic_retry"])
        self.assertTrue(plan["no_automatic_search_expansion"])
        schema = SCHEMA_VALIDATOR.load_json(SCHEMA)
        SCHEMA_VALIDATOR.validate_schema_document(schema)
        SCHEMA_VALIDATOR._validate_schema_instance(plan, schema, schema)

    def test_hard_gates_block_before_ranking_even_when_dimensions_are_high(self) -> None:
        blocked = route("blocked", band="high", jobs=4)
        blocked["hard_gates"]["accepted_endpoint_minima_where_required"] = {
            "status": "block",
            "reason": "Required endpoint minima have not been accepted.",
            "evidence_refs": ["minimum-gate:blocked"],
        }
        eligible = route("eligible", band="medium", jobs=5)
        plan = CLOSURE.derive_plan(request(blocked, eligible), "b" * 64)
        self.assertEqual(plan["ranked_route_ids"], ["eligible"])
        blocked_out = next(item for item in plan["routes"] if item["route_id"] == "blocked")
        self.assertFalse(blocked_out["eligible_for_ranking"])
        self.assertIsNone(blocked_out["rank"])
        self.assertIn("Required endpoint minima", blocked_out["eligibility_reasons"][0])

    def test_unknown_likelihood_bands_are_preserved_without_fabricated_probabilities(self) -> None:
        unknown = route("unknowns", band="unknown")
        plan = CLOSURE.derive_plan(request(unknown), "c" * 64)
        output = plan["routes"][0]
        self.assertEqual(output["dimensions"]["convergence_likelihood"]["band"], "unknown")
        self.assertEqual(output["dimensions"]["expected_closure_likelihood"]["calibration"]["basis"], "unavailable")
        self.assertNotRegex(json.dumps(plan).lower(), r'"probability"\s*:')
        bad = request(route("numeric"))
        bad["routes"][0]["dimensions"]["convergence_likelihood"]["probability"] = 0.8
        with self.assertRaisesRegex(CLOSURE.ClosurePriorityError, "probability fields are forbidden"):
            CLOSURE.derive_plan(bad, "d" * 64)

    def test_as_few_as_practical_never_selects_a_cheaper_incomplete_bundle(self) -> None:
        cheap_partial = route("cheap_partial", band="high", jobs=1)
        cheap_partial["bundle"]["completeness"] = "partial"
        cheap_partial["bundle"]["stages"] = cheap_partial["bundle"]["stages"][:1]
        practical = route("practical", band="medium", jobs=5)
        plan = CLOSURE.derive_plan(request(cheap_partial, practical), "e" * 64)
        self.assertEqual(plan["selected_bundle_ids"], ["practical_bundle"])
        self.assertFalse(plan["planning_policy"]["absolute_mathematical_job_minimum"])
        self.assertFalse(plan["planning_policy"]["necessary_evidence_may_be_omitted"])
        rejected = next(item for item in plan["deferred_or_rejected_paths"] if item["route_id"] == "cheap_partial")
        self.assertTrue(any("partial" in reason or "omits" in reason for reason in rejected["reasons"]))

    def test_low_probability_exploration_requires_explicit_review_and_remaining_budget(self) -> None:
        unreviewed = route("unreviewed_low", band="low", path_class="low_probability_exploration")
        unreviewed["explicit_low_probability_review"] = False
        with self.assertRaisesRegex(CLOSURE.ClosurePriorityError, "requires explicit review"):
            CLOSURE.derive_plan(request(unreviewed), "f" * 64)

        primary = route("primary", jobs=5)
        exploration = route("exploration", band="low", jobs=4, path_class="low_probability_exploration")
        reviewed = request(primary, exploration)
        reviewed["selection_policy"]["include_low_probability_exploration"] = True
        reviewed["selection_policy"]["budget"] = {"pbs_jobs": 6, "core_hours": 50}
        plan = CLOSURE.derive_plan(reviewed, "1" * 64)
        self.assertEqual(plan["selected_bundle_ids"], ["primary_bundle"])
        exploration_out = next(item for item in plan["routes"] if item["route_id"] == "exploration")
        self.assertIn("remaining budget", exploration_out["selection_reason"])

    def test_cli_build_validate_and_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as raw:
            work = Path(raw)
            request_path = work / "request.json"
            output_path = work / "plan.json"
            request_path.write_text(json.dumps(request(route("cli")), indent=2) + "\n", encoding="utf-8")
            built = subprocess.run(
                [sys.executable, str(TOOL), "build", str(request_path), "--output", str(output_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            validated = subprocess.run(
                [sys.executable, str(TOOL), "validate", str(output_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validated.returncode, 0, validated.stderr)
            second = subprocess.run(
                [sys.executable, str(TOOL), "build", str(request_path), "--output", str(output_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("refusing to overwrite", second.stderr)


if __name__ == "__main__":
    unittest.main()
