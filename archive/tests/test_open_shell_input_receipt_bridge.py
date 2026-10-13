#!/usr/bin/env python3
"""Offline bridge tests for open-shell minimum input approval."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_gaussian_auto_gate import AUTO
from tests.test_open_shell_minimum_handoff import OpenShellMinimumHandoffTests


ROOT = Path(__file__).parents[1]


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


TRANSPORT = AUTO.transport
SCHEMA_VALIDATOR = module("open_shell_receipt_schema", ROOT / "scripts" / "validate_asymmetric_contract.py")


class OpenShellInputReceiptBridgeTests(unittest.TestCase):
    def build_receipt(self, root: Path) -> dict:
        chain = OpenShellMinimumHandoffTests().build_chain(root)
        input_path = root / "exact.gjf"
        input_path.write_bytes(chain["handoff"]["input_text"].encode("utf-8"))
        report = TRANSPORT.parse_gaussian(input_path)
        options = chain["options"]
        selection = chain["selection"]
        selected = chain["selected"]
        stage_type = selected["task_plan"][0]["stage_type"]
        options_path = chain["options_path"]
        selection_path = chain["selection_path"]
        profile = selected["method_profiles"][0]
        used_task = {"task_index": 0, "stage_type": stage_type, "profile_id": profile["profile_id"]}
        mapping = {
            "exact_route": report["route"],
            "method": {"route_value": "ub3lyp", "profile_id": profile["profile_id"], "selected_value": profile["functional_or_method"], "human_confirmed": True},
            "basis": {"route_value": "6-31g(d)", "profile_id": profile["profile_id"], "selected_value": profile["basis_stack"], "human_confirmed": True},
            "solvent": {"route_value": "none", "profile_id": profile["profile_id"], "selected_value": profile["solvation"], "human_confirmed": True},
            "scf": {"route_value": "default", "profile_id": profile["profile_id"], "selected_value": profile["scf"], "human_confirmed": True},
            "tasks": [{**used_task, "route_evidence": ["minimum_opt", "frequency"], "human_confirmed": True}],
            "explicit_confirmation": True,
        }
        draft = {
            "schema": TRANSPORT.INPUT_REVIEW_SCHEMA, "review_id": "open_shell_minimum_exact_input",
            "work_kind": "minimum", "protocol_task_types": ["optimization", "frequency"],
            "protocol_binding": {
                "options_sha256": TRANSPORT.sha256(options_path), "options_payload_sha256": options["proposal_payload_sha256"],
                "selection_sha256": TRANSPORT.sha256(selection_path), "selection_payload_sha256": selection["selection_payload_sha256"],
                "selected_option": copy.deepcopy(selection["selected_option"]), "used_profile_ids": [profile["profile_id"]], "used_tasks": [used_task],
            },
            "route_profile_mapping": mapping, "protocol_family_completion": False,
            "approved_input": TRANSPORT._input_approval_facts(report),
            "decision": {"status": "accepted_exact_input", "explicit_confirmation": True, "reviewer": "offline fixture reviewer", "reviewed_at": "2026-07-17", "rationale": "Exact open-shell owner chain and input bytes reviewed."},
            "calculation_ready": False, "no_submission_authorization": True, "payload_sha256": None,
        }
        draft_path = root / "input-review-draft.json"
        review_path = root / "input-review.json"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        TRANSPORT.finalize_input_review(draft_path, review_path)
        receipt_path = root / "input-approval-v2.json"
        receipt = TRANSPORT.build_input_approval_receipt(
            options_path, selection_path, review_path, input_path, receipt_path, "open-shell-minimum-receipt",
            chain["review_path"], chain["handoff_path"], chain["audit_path"],
        )
        return {**chain, "input_path": input_path, "review_path": review_path, "receipt_path": receipt_path, "receipt": receipt, "report": report}

    def test_stable_opt_is_not_a_second_top_level_opt_but_duplicate_opt_is(self) -> None:
        positive = "#p ub3lyp/6-31g(d) opt freq stable=opt"
        duplicate = "#p ub3lyp/6-31g(d) opt=loose opt freq stable=opt"
        self.assertEqual(TRANSPORT.route_keyword_count(positive, "opt"), 1)
        self.assertEqual(TRANSPORT.route_optimization_keyword_count(positive), 1)
        self.assertEqual(TRANSPORT.route_keyword_count(duplicate, "opt"), 2)
        report = {"route": duplicate, "geometry_source": "explicit_cartesian", "oldcheckpoint": None, "link1_count": 0, "route_section_count": 1}
        self.assertEqual(TRANSPORT.input_approval_compatibility(report, "minimum")["status"], "blocked_missing_specialist_input_approval")

    def test_owner_opt_freq_stage_vocabulary_maps_to_top_level_opt_and_freq(self) -> None:
        consumed = [{"task_index": 0, "stage_type": "opt_freq", "profile_id": "p"}]
        mappings = [{**consumed[0], "route_evidence": ["minimum_opt", "frequency"], "human_confirmed": True}]
        for stage in ("opt_freq", "opt_freq_with_stability"):
            consumed[0]["stage_type"] = mappings[0]["stage_type"] = stage
            TRANSPORT._assert_consumed_tasks_match_route("#p ufixture/basis opt freq stable=opt", consumed, mappings)

    def test_open_shell_minimum_receipt_replays_all_owners_and_closed_schema(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            chain = self.build_receipt(Path(temp).resolve())
            receipt = TRANSPORT.validate_input_approval_receipt(chain["receipt_path"], input_path=chain["input_path"], report=chain["report"], work_kind="minimum")
            self.assertEqual(receipt["schema"], TRANSPORT.OPEN_SHELL_INPUT_APPROVAL_SCHEMA)
            self.assertEqual(receipt["specialist_owner_binding"]["reference_family"], "U")
            self.assertEqual(receipt["specialist_owner_binding"]["input_sha256"], chain["report"]["input_sha256"])
            self.assertFalse(receipt["calculation_ready"])
            self.assertTrue(receipt["no_submission_authorization"])
            schema = json.loads((ROOT / "contracts" / "rtwin-pbs" / "input-approval-receipt-v2.schema.json").read_text())
            SCHEMA_VALIDATOR.validate_schema_document(schema)
            SCHEMA_VALIDATOR._validate_schema_instance(receipt, schema, schema)

    def test_open_shell_v1_without_owner_chain_and_all_owner_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve()
            chain = self.build_receipt(root)
            with self.assertRaisesRegex(ValueError, "requires electronic-state review"):
                TRANSPORT._make_input_approval_receipt(chain["options_path"], chain["selection_path"], chain["review_path"], chain["input_path"], root / "unsafe.json", "unsafe")
            for source in ("electronic_state_review", "open_shell_input_handoff", "open_shell_input_audit"):
                with self.subTest(source=source):
                    forged = copy.deepcopy(chain["receipt"])
                    forged["sources"][source]["payload_sha256"] = "0" * 64
                    forged["payload_sha256"] = TRANSPORT.contract_payload_sha256(forged)
                    path = root / f"forged-{source}.json"
                    path.write_text(json.dumps(forged), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        TRANSPORT.validate_input_approval_receipt(path)

    def test_specialist_routes_remain_blocked(self) -> None:
        routes = (
            "#p u/b opt=(qst2,calcfc) freq stable=opt", "#p u/b fopt freq stable=opt",
            "#p u/b opt freq irc=(forward) stable=opt", "#p u/b opt=modredundant freq stable=opt",
            "#p u/b opt freq geom=check guess=read stable=opt",
        )
        for route in routes:
            with self.subTest(route=route):
                report = {"route": route, "geometry_source": "explicit_cartesian", "oldcheckpoint": None, "link1_count": 0, "route_section_count": 1}
                self.assertNotEqual(TRANSPORT.input_approval_compatibility(report, "minimum")["status"], "supported_generic_v1")


if __name__ == "__main__":
    unittest.main()
