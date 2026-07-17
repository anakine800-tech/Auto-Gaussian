#!/usr/bin/env python3
"""Focused offline tests for main-group open-shell TS/Freq/IRC V1."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills" / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_ts_irc.py"
STATE_SCRIPT = ROOT / "skills" / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_state.py"
FIXTURES = ROOT / "tests" / "fixtures" / "main_group_open_shell_ts_irc"
STATE_FIXTURES = ROOT / "tests" / "fixtures" / "main_group_open_shell"
SCHEMA = ROOT / "contracts" / "main-group-open-shell" / "ts-irc-contracts.schema.json"
SCHEMA_VALIDATOR = ROOT / "scripts" / "validate_asymmetric_contract.py"


def module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path); assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


TS = module_from(SCRIPT, "open_shell_ts_irc")
STATE = module_from(STATE_SCRIPT, "open_shell_state_for_tests")
VALIDATOR = module_from(SCHEMA_VALIDATOR, "open_shell_ts_irc_schema_validator")


def dump(path: Path, value: dict, *, canonical: bool = False) -> Path:
    path.write_bytes(TS.canonical_bytes(value) if canonical else (json.dumps(value, indent=2) + "\n").encode())
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_closed(test: unittest.TestCase, value: object, location: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object": test.assertIs(value.get("additionalProperties"), False, location)
        for key, child in value.items(): assert_closed(test, child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): assert_closed(test, child, f"{location}[{index}]")


class OpenShellTsIrcTests(unittest.TestCase):
    def build_chain(self, root: Path) -> dict[str, tuple[Path, dict]]:
        root = root.resolve()
        review = STATE.build_review(STATE_FIXTURES / "ch3_candidate.json", STATE_FIXTURES / "ch3_review_source.json")
        review_path = STATE.write_new_json(root / "state_review.json", review)
        workflow = TS.build_workflow(review_path, FIXTURES / "ch3_doublet_ts_candidate.json", FIXTURES / "ch3_doublet_protocol.json", "ch3_doublet_ts_irc")
        workflow_path = TS.write_new_json(root / "workflow.json", workflow)

        protocol = json.loads((FIXTURES / "ch3_doublet_protocol.json").read_text())
        audits: dict[str, tuple[Path, dict]] = {}
        for stage in ("ts_freq", "irc_forward", "irc_reverse"):
            input_path = root / f"{stage}.gjf"
            input_path.write_text(protocol["stages"][stage]["route"] + "\n\nSynthetic non-runnable fixture\n", encoding="utf-8")
            source = {
                "schema": "auto-g16-main-group-open-shell-ts-irc-input-audit-source/1", "audit_id": f"ch3_{stage}_audit", "stage": stage,
                "workflow_payload_sha256": workflow["payload_sha256"], "state_review_payload_sha256": workflow["state_review"]["payload_sha256"],
                "candidate_sha256": workflow["candidate"]["sha256"], "protocol_file_sha256": workflow["protocol"]["sha256"],
                "protocol_selection_payload_sha256": protocol["stages"][stage]["protocol_selection_payload_sha256"],
                "input": {"path": str(input_path), "sha256": digest(input_path), "route": protocol["stages"][stage]["route"], "atom_elements": ["C", "H", "H", "H"]},
                "charge": 0, "multiplicity": 2, "state_family": "doublet_ground_state", "wavefunction_reference": "U", "same_spin_surface": True,
                "settings_reviewed": True, "review": {"decision": "accepted_for_offline_audit", "reviewer": "synthetic_fixture_reviewer", "confirmed": True},
                "calculation_ready": False, "no_submission_authorization": True,
            }
            source_path = dump(root / f"{stage}.source.json", source)
            audit = TS.build_input_audit(workflow_path, source_path); audit_path = TS.write_new_json(root / f"{stage}.audit.json", audit)
            audits[stage] = (audit_path, audit)

        observation = STATE.build_observation(FIXTURES / "ch3_doublet_ts_success.synthetic.txt", "ch3_doublet_ts_observation")
        observation_path = STATE.write_new_json(root / "ts.observation.json", observation)
        mode = {"schema": "auto-g16-main-group-open-shell-ts-mode-decision/1", "decision_id": "ch3_doublet_mode", "workflow_payload_sha256": workflow["payload_sha256"], "input_audit_payload_sha256": audits["ts_freq"][1]["payload_sha256"], "observation_payload_sha256": observation["payload_sha256"], "imaginary_mode_index": 0, "intended_reaction_coordinate_confirmed": True, "reviewer": "synthetic_fixture_reviewer", "rationale": "Synthetic manual mode confirmation.", "decision": "accepted", "confirmed": True, "calculation_ready": False, "no_submission_authorization": True}
        mode_path = dump(root / "mode.json", mode)
        ts_acceptance = TS.build_ts_acceptance(workflow_path, audits["ts_freq"][0], observation_path, mode_path, "ch3_doublet_ts_acceptance")
        ts_path = TS.write_new_json(root / "ts.acceptance.json", ts_acceptance)
        plan = TS.build_irc_plan(workflow_path, ts_path, audits["irc_forward"][0], audits["irc_reverse"][0], "ch3_doublet_irc_plan")
        plan_path = TS.write_new_json(root / "irc.plan.json", plan)
        endpoints = {}
        for direction, identity, structure in (("forward", "product", "5" * 64), ("reverse", "reactant", "6" * 64)):
            source = {"schema": "auto-g16-main-group-open-shell-irc-endpoint-source/1", "endpoint_id": f"ch3_{direction}_endpoint", "direction": direction, "plan_payload_sha256": plan["payload_sha256"], "input_audit_payload_sha256": plan["direction_input_audits"][direction]["payload_sha256"], "normal_termination": True, "path_complete": True, "endpoint_identity": identity, "structure_sha256": structure, "charge": 0, "multiplicity": 2, "state_family": "doublet_ground_state", "wavefunction_reference": "U", "s2_before_annihilation": 0.76, "s2_after_annihilation": 0.751, "stability": "stable", "state_lineage_payload_sha256": workflow["payload_sha256"], "review": {"decision": "accepted_endpoint_identity", "reviewer": "synthetic_fixture_reviewer", "rationale": f"Synthetic {direction} endpoint identity review.", "confirmed": True}, "calculation_ready": False, "no_submission_authorization": True}
            endpoints[direction] = (dump(root / f"{direction}.endpoint.json", source), source)
        acceptance = TS.build_irc_acceptance(plan_path, endpoints["forward"][0], endpoints["reverse"][0], "ch3_doublet_irc_acceptance")
        acceptance_path = TS.write_new_json(root / "irc.acceptance.json", acceptance)
        return {"workflow": (workflow_path, workflow), "ts_audit": audits["ts_freq"], "forward_audit": audits["irc_forward"], "reverse_audit": audits["irc_reverse"], "observation": (observation_path, observation), "mode": (mode_path, mode), "ts": (ts_path, ts_acceptance), "plan": (plan_path, plan), "forward": endpoints["forward"], "reverse": endpoints["reverse"], "irc": (acceptance_path, acceptance)}

    def test_schema_is_closed_versioned_and_static_json_is_valid(self) -> None:
        schema = json.loads(SCHEMA.read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(schema["$id"].endswith("/1")); self.assertTrue(schema["title"].startswith("Auto-G16")); assert_closed(self, schema)
        with tempfile.TemporaryDirectory() as tmp:
            chain = self.build_chain(Path(tmp))
            VALIDATOR.validate_schema_document(schema)
            for name in ("workflow", "ts_audit", "ts", "plan", "irc"):
                VALIDATOR._validate_schema_instance(chain[name][1], schema, schema)
            for value in (json.loads((FIXTURES / "ch3_doublet_ts_candidate.json").read_text()), json.loads((FIXTURES / "ch3_doublet_protocol.json").read_text()), chain["mode"][1], chain["forward"][1], chain["reverse"][1]):
                VALIDATOR._validate_schema_instance(value, schema, schema)

    def test_positive_doublet_ts_and_bidirectional_irc_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chain = self.build_chain(Path(tmp))
            self.assertEqual(chain["workflow"][1]["workflow_kind"], TS.WORKFLOW_KIND)
            self.assertEqual(chain["ts"][1]["status"], "accepted")
            self.assertEqual(chain["plan"][1]["status"], "planned_offline_only")
            self.assertFalse(chain["plan"][1]["irc_validated"])
            self.assertEqual(chain["irc"][1]["status"], "irc_validated")
            self.assertTrue(chain["irc"][1]["irc_validated"])
            for name in ("workflow", "ts_audit", "forward_audit", "reverse_audit", "ts", "plan", "irc"):
                self.assertEqual(TS.validate_artifact(chain[name][0])["payload_sha256"], chain[name][1]["payload_sha256"])
                self.assertFalse(chain[name][1]["calculation_ready"]); self.assertTrue(chain[name][1]["no_submission_authorization"])

    def test_ts_blocks_frequency_mode_s2_stability_reference_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); chain = self.build_chain(root)
            base = (FIXTURES / "ch3_doublet_ts_success.synthetic.txt").read_text()
            cases = {
                "frequency": base.replace("-450.0", "450.0"),
                "incomplete_frequencies": base.replace("Frequencies -- 700.0 1100.0 3000.0\n", ""),
                "s2": base.replace("after 0.7505", "after 1.2000"),
                "stability": base.replace("The wavefunction is stable under the perturbations considered.", "The wavefunction has an internal instability."),
                "reference": base.replace("E(UFixture)", "E(ROFixture)"),
            }
            for name, text in cases.items():
                with self.subTest(name=name):
                    log_path = root / f"{name}.synthetic.txt"; log_path.write_text(text)
                    observation = STATE.build_observation(log_path, f"{name}_observation")
                    obs_path = STATE.write_new_json(root / f"{name}.observation.json", observation)
                    mode = copy.deepcopy(chain["mode"][1]); mode["observation_payload_sha256"] = observation["payload_sha256"]
                    mode_path = dump(root / f"{name}.mode.json", mode)
                    if name == "frequency":
                        with self.assertRaisesRegex(TS.ContractError, "reaction-coordinate mode"):
                            TS.build_ts_acceptance(chain["workflow"][0], chain["ts_audit"][0], obs_path, mode_path, f"{name}_acceptance")
                    else:
                        result = TS.build_ts_acceptance(chain["workflow"][0], chain["ts_audit"][0], obs_path, mode_path, f"{name}_acceptance")
                        self.assertEqual(result["status"], "blocked")
            mode = copy.deepcopy(chain["mode"][1]); mode["intended_reaction_coordinate_confirmed"] = False
            with self.assertRaisesRegex(TS.ContractError, "reaction-coordinate mode"):
                TS.build_ts_acceptance(chain["workflow"][0], chain["ts_audit"][0], chain["observation"][0], dump(root / "mode_rejected.json", mode), "mode_rejected")
            mode = copy.deepcopy(chain["mode"][1]); mode["workflow_payload_sha256"] = "9" * 64
            with self.assertRaisesRegex(TS.ContractError, "hash drift"):
                TS.build_ts_acceptance(chain["workflow"][0], chain["ts_audit"][0], chain["observation"][0], dump(root / "mode_drift.json", mode), "mode_drift")

    def test_irc_blocks_endpoint_state_and_hash_drift(self) -> None:
        mutations = {
            "incomplete": lambda x: x.update(path_complete=False),
            "multiplicity": lambda x: x.update(multiplicity=3),
            "reference": lambda x: x.update(wavefunction_reference="RO"),
            "stability": lambda x: x.update(stability="unstable"),
            "s2": lambda x: x.update(s2_after_annihilation=1.2),
            "lineage": lambda x: x.update(state_lineage_payload_sha256="9" * 64),
            "plan_hash": lambda x: x.update(plan_payload_sha256="8" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); chain = self.build_chain(root); source = copy.deepcopy(chain["forward"][1]); mutate(source)
                path = dump(root / f"{name}.endpoint.json", source)
                if name == "s2":
                    result = TS.build_irc_acceptance(chain["plan"][0], path, chain["reverse"][0], f"{name}_irc")
                    self.assertEqual(result["status"], "blocked"); self.assertFalse(result["irc_validated"])
                else:
                    with self.assertRaises(TS.ContractError):
                        TS.build_irc_acceptance(chain["plan"][0], path, chain["reverse"][0], f"{name}_irc")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); chain = self.build_chain(root); same_side = copy.deepcopy(chain["forward"][1]); same_side["endpoint_identity"] = "reactant"
            result = TS.build_irc_acceptance(chain["plan"][0], dump(root / "same_side.json", same_side), chain["reverse"][0], "same_side_irc")
            self.assertEqual(result["status"], "blocked"); self.assertFalse(result["irc_validated"])

    def test_explicit_scope_blocks_and_closed_shell_adapter_is_unchanged(self) -> None:
        candidate = json.loads((FIXTURES / "ch3_doublet_ts_candidate.json").read_text())
        cases = [("spin_crossing", ("workflow_scope", "spin_crossing")), ("open_shell_singlet", ("electronic_scope", "broken_symmetry")), ("multireference", ("electronic_scope", "multireference")), ("transition_metal", None)]
        for name, mutation in cases:
            with self.subTest(name=name):
                changed = copy.deepcopy(candidate)
                if mutation: changed[mutation[0]] = mutation[1]
                else: changed["atoms"][0]["element"] = "Fe"
                with self.assertRaises(TS.ContractError): TS._validate_ts_candidate(changed)
        closed_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "input-draft-review.schema.json").read_text())
        self.assertEqual(closed_schema["properties"]["workflow_kind"]["const"], "closed_shell_main_group_single_guess_ts_freq")

    def test_no_live_execution_surface(self) -> None:
        tree = ast.parse(SCRIPT.read_text())
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertTrue(imported.isdisjoint({"subprocess", "socket", "requests", "paramiko", "asyncssh"}))
        choices = next(action.choices for action in TS.build_parser()._actions if getattr(action, "choices", None))
        self.assertEqual(set(choices), {"build-workflow", "audit-input", "accept-ts", "plan-irc", "accept-irc", "validate"})


if __name__ == "__main__": unittest.main()
