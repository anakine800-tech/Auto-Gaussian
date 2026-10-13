#!/usr/bin/env python3
"""Offline cross-Skill replay tests for the Auto-G16 v2.5 integration overlay."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests import test_closure_priority as closure_fixture
from tests import test_method_evidence as method_fixture
from tests import test_ts_seed as seed_fixture


ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INTEGRATION = load_module(
    "auto_g16_v25_integration_test",
    ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "v25_integration.py",
)
DECISION = load_module(
    "auto_g16_v25_decision_fixture",
    ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "human_scientific_decision.py",
)
BATCH = load_module(
    "auto_g16_v25_batch_fixture",
    ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "execution_batch.py",
)
SCHEMA_VALIDATOR = load_module(
    "auto_g16_v25_schema_validator",
    ROOT / "scripts" / "validate_asymmetric_contract.py",
)


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


class V25IntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.root = Path(self.temporary.name).resolve()
        self.finalized = self.build_package()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def generic_source(self, name: str, schema: str) -> Path:
        path = self.root / name
        value = {"schema": schema, "summary": f"Synthetic {name} for offline integration."}
        DECISION.rw.finalize_artifact(value)
        write(path, value)
        return path

    def build_package(self) -> dict:
        method = method_fixture.METHOD_EVIDENCE.build_brief(
            method_fixture.context(),
            [method_fixture.benchmark(), method_fixture.run_observation()],
            None,
            method_fixture.metadata(),
        )
        method_path = self.root / "method-brief.json"
        write(method_path, method)

        mechanism_path = self.generic_source("mechanism.json", "gaussian-mechanism-proposal/1")
        network_path = self.generic_source("network.json", "gaussian-reaction-mechanism-network/1")
        discussion_draft = {
            "schema": DECISION.DISCUSSION_DRAFT,
            "discussion_id": "discussion_integration",
            "study_id": "study_integration",
            "source_hashes": {
                "mechanism": DECISION.rw.sha256_file(mechanism_path),
                "network": DECISION.rw.sha256_file(network_path),
                "evidence": [DECISION.rw.sha256_file(method_path)],
            },
            "scientific_question": "Which reviewed mechanism and explicit method may enter closure planning?",
            "established_facts": ["The method brief and proposal bytes are exact and hash-bound."],
            "uncertainties": ["No artifact in this package grants execution authority."],
            "alternatives": [
                {"alternative_id": "path_alpha", "summary": "Reviewed bounded path alpha.", "origin": "human_submitted", "proposal_only": True},
                {"alternative_id": "path_beta", "summary": "Competing bounded path beta.", "origin": "ai_generated", "proposal_only": True},
            ],
            "ai_assessment": {
                "recommendation": "Keep path alpha as the bounded integration fixture.",
                "rationale": "It exercises every owner contract without live work.",
                "risks": ["Synthetic integration evidence is not scientific validation."],
                "origin": "ai_generated",
                "proposal_only": True,
                "may_confirm": False,
            },
            "user_decision": {
                "decision": "confirm_selected",
                "exact_text": "I explicitly confirm path alpha and its exact method protocol only for later independent gates.",
                "confirmed_claims": [
                    {"claim_type": "elementary_step", "claim_id": "edge_alpha", "alternative_id": "path_alpha", "decision": "confirmed_by_user"},
                    {"claim_type": "method", "claim_id": "method_protocol", "alternative_id": "path_alpha", "decision": "confirmed_by_user"},
                ],
                "origin": "explicit_user_input",
                "assistant_generated": False,
                "automated_command_generated": False,
                "approver": "fixture_operator",
                "decided_at": "2026-07-19T14:00:00+08:00",
            },
        }
        draft_path = self.root / "discussion.draft.json"
        write(draft_path, discussion_draft)
        discussion = DECISION.build_discussion(
            self.root,
            Path(draft_path.name),
            Path(mechanism_path.name),
            Path(network_path.name),
            [Path(method_path.name)],
            Path("discussion.json"),
        )
        discussion_path = self.root / "discussion.json"

        seed_helper = seed_fixture.TSSeedTests()
        seed_source = seed_helper.source(self.root)
        seed_source["target_id"] = "connected"
        candidate, candidate_path = seed_helper.build(self.root, seed_source, "primary")
        portfolio_source = {
            "portfolio_id": "portfolio_connected",
            "target_id": "connected",
            "selections": [{
                "path": candidate_path.name,
                "role": "primary",
                "scientific_rationale": "Exact reviewed primary initial guess.",
                "user_reviewed": True,
            }],
            "exception_review": {"approved": False, "new_scientific_rationale": None, "user_reviewed": False},
            "review": {"status": "reviewed", "reviewer": "fixture_operator", "review_notes": ["One bounded primary seed."]},
        }
        portfolio_source_path = self.root / "portfolio-source.json"
        write(portfolio_source_path, portfolio_source)
        portfolio = seed_fixture.CORE.build_portfolio(portfolio_source, portfolio_source_path)
        portfolio_path = self.root / "portfolio.json"
        write(portfolio_path, portfolio)

        route = closure_fixture.route("connected")
        discussion_token = f"{INTEGRATION.DISCUSSION}:{discussion['payload_sha256']}"
        method_token = f"{INTEGRATION.METHOD_BRIEF}:{method['payload_sha256']}"
        portfolio_token = f"{INTEGRATION.TS_PORTFOLIO}:{portfolio['payload_sha256']}"
        route["hard_gates"]["reviewed_mechanism_and_active_state"]["evidence_refs"] = [discussion_token]
        route["hard_gates"]["user_confirmation"]["evidence_refs"] = [discussion_token]
        route["hard_gates"]["method_evidence_and_explicit_method_decision"]["evidence_refs"] = [method_token, discussion_token]
        route["dimensions"]["initial_guess_quality"]["calibration"]["provenance"] = portfolio_token
        closure_request = closure_fixture.request(route)
        closure_request["study_id"] = "study_integration"
        plan = closure_fixture.CLOSURE.derive_plan(closure_request, "1" * 64)
        plan_path = self.root / "closure-plan.json"
        write(plan_path, plan)

        method_protocol_sha = candidate["method_protocol_reference"]["sha256"]
        primary_geometry_sha = next(entry for entry in portfolio["entries"] if entry["role"] == "primary")["geometry_sha256"]
        tasks = []
        node_mappings = []
        selected_route = next(item for item in plan["routes"] if item["selected"])
        for index, stage in enumerate(selected_route["bundle"]["stages"], start=1):
            if stage["stage_kind"] not in INTEGRATION.CALCULATION_STAGE_KINDS:
                continue
            identity = {
                "structure_sha256": primary_geometry_sha if stage["stage_kind"] == "ts_freq" else f"{100 + index:064x}",
                "chemical_hypothesis_sha256": discussion["confirmation_scope_sha256"],
                "method_protocol_sha256": method_protocol_sha,
                "calculation_objective_sha256": INTEGRATION.objective_sha(plan["payload_sha256"], stage["node_id"], stage["stage_kind"]),
                "relevant_input_sha256": f"{200 + index:064x}",
            }
            task_id = BATCH.scientific_task_id(identity)
            tasks.append({"scientific_task_id": task_id, "identity": identity, "estimated_core_hours": 8.0, "reason": f"Selected closure node {stage['node_id']}."})
            node_mappings.append({"node_id": stage["node_id"], "scientific_task_id": task_id})
        execution_review = BATCH.finalize_review({
            "schema": BATCH.REVIEW_SCHEMA,
            "batch_id": "batch_integration",
            "review_id": "review_integration",
            "reviewed_at": "2026-07-19T14:30:00+08:00",
            "reviewer": "fixture_operator",
            "max_distinct_scientific_tasks": 10,
            "tasks": tasks,
            "governance": {
                "automatic_qsub": False,
                "automatic_retry": False,
                "automatic_scientific_change": False,
                "monitoring_is_read_only": True,
                "fresh_approval_required_per_attempt": True,
            },
            "payload_sha256": "",
        })
        execution_review_path = self.root / "execution-review.json"
        write(execution_review_path, execution_review)
        ledger_path = self.root / "execution-ledger.json"
        BATCH.initialize(execution_review_path, ledger_path, timestamp="2026-07-19T06:30:00Z")

        integration_draft = {
            "schema": INTEGRATION.SCHEMA,
            "integration_id": "v25_integration_fixture",
            "study_id": "study_integration",
            "artifacts": {
                "method_evidence_brief": INTEGRATION.make_binding(method_path, self.root),
                "mechanism_discussion": INTEGRATION.make_binding(discussion_path, self.root),
                "closure_priority_plan": INTEGRATION.make_binding(plan_path, self.root),
                "ts_seed_portfolios": [INTEGRATION.make_binding(portfolio_path, self.root)],
                "execution_batch_review": INTEGRATION.make_binding(execution_review_path, self.root),
                "execution_batch_ledger": INTEGRATION.make_binding(ledger_path, self.root),
            },
            "method_decision": {
                "claim_id": "method_protocol",
                "alternative_id": "path_alpha",
                "method_protocol_sha256": method_protocol_sha,
            },
            "route_bindings": [{
                "route_id": "connected",
                "mechanism_discussion_payload_sha256": discussion["payload_sha256"],
                "method_evidence_brief_payload_sha256": method["payload_sha256"],
                "ts_seed_portfolio_payload_sha256": portfolio["payload_sha256"],
                "node_task_bindings": node_mappings,
            }],
            "review": {
                "status": "reviewed_non_authorizing",
                "reviewer": "fixture_operator",
                "reviewed_at": "2026-07-19T15:00:00+08:00",
                "notes": ["Synthetic owner-chain integration review; no live authority."],
            },
            "authority": copy.deepcopy(INTEGRATION.AUTHORITY),
            "payload_sha256": None,
        }
        draft_path = self.root / "integration.draft.json"
        write(draft_path, integration_draft)
        return INTEGRATION.finalize(self.root, Path(draft_path.name), Path("integration.json"))

    def rehash(self, value: dict) -> dict:
        value["payload_sha256"] = INTEGRATION.payload_sha(value)
        return value

    def test_owner_chain_is_exact_non_authorizing_and_schema_valid(self) -> None:
        summary = INTEGRATION.validate_document(self.root, self.finalized)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["selected_route_count"], 1)
        self.assertEqual(summary["selected_task_count"], 4)
        self.assertEqual(summary["max_distinct_scientific_tasks"], 10)
        self.assertFalse(summary["live_actions"])
        self.assertTrue(summary["no_submission_authorization"])
        schema = SCHEMA_VALIDATOR.load_json(ROOT / "contracts" / "reaction-workflow" / "v25-integration-review.schema.json")
        SCHEMA_VALIDATOR.validate_schema_document(schema)
        SCHEMA_VALIDATOR._validate_schema_instance(self.finalized, schema, schema)

    def test_method_brief_requires_the_declared_explicit_human_method_decision(self) -> None:
        forged = copy.deepcopy(self.finalized)
        forged["method_decision"]["claim_id"] = "different_method"
        self.rehash(forged)
        with self.assertRaisesRegex(INTEGRATION.IntegrationError, "explicit human method decision"):
            INTEGRATION.validate_document(self.root, forged)

    def test_selected_closure_nodes_must_exactly_match_the_execution_ledger(self) -> None:
        forged = copy.deepcopy(self.finalized)
        forged["route_bindings"][0]["node_task_bindings"].pop()
        self.rehash(forged)
        with self.assertRaisesRegex(INTEGRATION.IntegrationError, "every selected calculation node"):
            INTEGRATION.validate_document(self.root, forged)

    def test_artifact_cannot_gain_execution_or_submission_authority(self) -> None:
        forged = copy.deepcopy(self.finalized)
        forged["authority"]["calculation_ready"] = True
        self.rehash(forged)
        with self.assertRaisesRegex(INTEGRATION.IntegrationError, "authority boundary"):
            INTEGRATION.validate_document(self.root, forged)

    def test_ts_seed_binding_is_exact_initial_guess_evidence(self) -> None:
        forged = copy.deepcopy(self.finalized)
        forged["route_bindings"][0]["ts_seed_portfolio_payload_sha256"] = "f" * 64
        self.rehash(forged)
        with self.assertRaisesRegex(INTEGRATION.IntegrationError, "TS-seed portfolio"):
            INTEGRATION.validate_document(self.root, forged)

    def test_duplicate_json_and_timezone_free_review_are_rejected(self) -> None:
        duplicate = self.root / "duplicate.json"
        duplicate.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
        with self.assertRaisesRegex(INTEGRATION.IntegrationError, "duplicate JSON key"):
            INTEGRATION.load_json(duplicate)
        forged = copy.deepcopy(self.finalized)
        forged["review"]["reviewed_at"] = "2026-07-19T15:00:00"
        self.rehash(forged)
        with self.assertRaisesRegex(INTEGRATION.IntegrationError, "timezone"):
            INTEGRATION.validate_document(self.root, forged)


if __name__ == "__main__":
    unittest.main()
