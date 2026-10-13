#!/usr/bin/env python3
"""Offline tests for the versioned open-shell minimum two-stage family."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from types import SimpleNamespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.test_gaussian_auto_gate import AUTO


ROOT = Path(__file__).parents[1]
TRANSPORT = AUTO.transport


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


FAMILY = module("open_shell_two_stage_family", ROOT / "skills" / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_minimum_family.py")
SCHEMA = module("open_shell_two_stage_schema", ROOT / "scripts" / "validate_asymmetric_contract.py")
AUTHORIZATIONS = {"create_server_directory": True, "submit": True, "retry": False, "cancel": False, "cleanup": False, "delete_server_data": False}


class OpenShellMinimumTwoStageFamilyTests(unittest.TestCase):
    def build_chain(self, root: Path, *, expected_frequency_count: int = 3, opt_log_text: str | None = None, prospective: bool = False) -> dict:
        spec = {
            "family_id": "oh_retry_family", "title": "offline OH retry candidate", "charge": 0, "multiplicity": 2,
            "state_family": "doublet_ground_state", "reference_family": "U", "target_s2": 0.75, "max_abs_s2_deviation": 0.1,
            "atoms": [
                {"index": 1, "element": "O", "x_angstrom": 0.0, "y_angstrom": 0.0, "z_angstrom": 0.0},
                {"index": 2, "element": "H", "x_angstrom": 0.0, "y_angstrom": 0.0, "z_angstrom": 0.97},
                {"index": 3, "element": "H", "x_angstrom": 0.9, "y_angstrom": 0.0, "z_angstrom": -0.2},
            ],
            "structure_sha256": "pending",
            "opt_route": "#p UB3LYP/cc-pVTZ Opt=Tight Freq SCF=(Tight,XQC) Int=UltraFine NoSymm",
            "stability_route": "#p UB3LYP/cc-pVTZ Stable=Opt Geom=AllCheck Guess=Read SCF=(Tight,XQC) Int=UltraFine NoSymm",
            "opt_checkpoint": "oh_opt.chk", "stability_checkpoint": "oh_stable.chk", "expected_frequency_count": expected_frequency_count,
            "resources": {"resource_tier": "simple", "mem_gb": 12, "cores": 8},
            "selection_payload_sha256": "2" * 64, "selected_option_payload_sha256": "3" * 64,
        }
        if prospective:
            spec["family_origin"] = "prospective_two_stage_minimum"
        else:
            spec["superseded_input_sha256"] = "43ad5e2e" + "0" * 56
        spec["structure_sha256"] = FAMILY.hashlib.sha256(FAMILY.canonical_bytes({"atoms": spec["atoms"], "charge": spec["charge"], "multiplicity": spec["multiplicity"]})).hexdigest()
        spec_path = root / "spec.json"; spec_path.write_text(json.dumps(spec), encoding="utf-8")
        handoff_path, opt_input, stable_input = root / "family.json", root / "oh_opt.gjf", root / "oh_stable.gjf"
        handoff = FAMILY.build_family(spec_path, handoff_path, opt_input, stable_input)
        opt_receipt = FAMILY.build_stage_receipt(handoff_path, opt_input, "oh_opt_receipt", "opt_freq")
        opt_receipt_path = root / "opt-receipt.json"; opt_receipt_path.write_bytes(FAMILY.canonical_bytes(opt_receipt))
        opt_log = root / "oh_opt.log"; opt_log.write_text(opt_log_text if opt_log_text is not None else self.good_log(stable=False), encoding="utf-8")
        checkpoint_path = root / "oh_opt.chk"; checkpoint_path.write_bytes(b"synthetic offline checkpoint bytes")
        checkpoint = FAMILY.build_checkpoint_binding(handoff_path, opt_log, checkpoint_path, "oh_checkpoint_binding")
        checkpoint_path_json = root / "checkpoint-binding.json"; checkpoint_path_json.write_bytes(FAMILY.canonical_bytes(checkpoint))
        manifest = FAMILY.build_stability_manifest(handoff_path, checkpoint_path_json, stable_input)
        manifest_path = stable_input.with_suffix(".json"); manifest_path.write_bytes(FAMILY.canonical_bytes(manifest))
        stable_receipt = FAMILY.build_stage_receipt(handoff_path, stable_input, "oh_stability_receipt", "stability", checkpoint_path_json, manifest_path)
        stable_receipt_path = root / "stable-receipt.json"; stable_receipt_path.write_bytes(FAMILY.canonical_bytes(stable_receipt))
        return locals()

    @staticmethod
    def good_log(*, stable: bool) -> str:
        stability = " The wavefunction is stable under the perturbations considered.\n" if stable else ""
        frequencies = " Frequencies -- 100.0 200.0 300.0\n" if not stable else ""
        stationary = " Stationary point found.\n" if not stable else ""
        return (
            " Charge = 0 Multiplicity = 2\n"
            " SCF Done:  E(UB3LYP) =  -75.000000 A.U.\n"
            " S**2 before annihilation 0.7600, after 0.7510\n"
            + stationary + frequencies + stability + " Normal termination of Gaussian 16\n"
        )

    def test_A_closed_schemas_and_static_routes(self) -> None:
        for path in (
            ROOT / "contracts/main-group-open-shell/minimum-two-stage-family-contracts.schema.json",
            ROOT / "contracts/rtwin-pbs/live-submission-approval-v5.schema.json",
        ):
            schema = json.loads(path.read_text(encoding="utf-8")); SCHEMA.validate_schema_document(schema)
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            chain = self.build_chain(Path(temp).resolve())
            schema = json.loads((ROOT / "contracts/main-group-open-shell/minimum-two-stage-family-contracts.schema.json").read_text())
            for artifact in (chain["handoff"], chain["checkpoint"], chain["manifest"], chain["opt_receipt"], chain["stable_receipt"]):
                SCHEMA._validate_schema_instance(artifact, schema, schema)
            self.assertNotIn("stable", chain["handoff"]["stages"]["opt_freq"]["route"].lower())
            self.assertNotIn(" freq", chain["handoff"]["stages"]["stability"]["route"].lower())

    def test_B_owner_tamper_and_aggregate_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve(); chain = self.build_chain(root)
            stable_log = root / "oh_stable.log"; stable_log.write_text(self.good_log(stable=True), encoding="utf-8")
            acceptance = FAMILY.build_acceptance(chain["handoff_path"], chain["checkpoint_path_json"], chain["opt_log"], stable_log, "oh_family_acceptance")
            self.assertEqual(acceptance["status"], "accepted_owner_result")
            self.assertFalse(acceptance["calculation_ready"]); self.assertTrue(acceptance["no_submission_authorization"])
            family_schema = json.loads((ROOT / "contracts/main-group-open-shell/minimum-two-stage-family-contracts.schema.json").read_text())
            SCHEMA._validate_schema_instance(acceptance, family_schema, family_schema)
            for label, mutate, validator in (
                ("Opt adds Stable", lambda x: x["stages"]["opt_freq"].__setitem__("route", x["stages"]["opt_freq"]["route"] + " Stable=Opt"), FAMILY.validate_handoff),
                ("checkpoint hash", lambda x: x["checkpoint"].__setitem__("sha256", "0" * 64), FAMILY.validate_checkpoint_binding),
                ("receipt retry", lambda x: x["authorizations"].__setitem__("retry", True), FAMILY.validate_stage_receipt),
            ):
                with self.subTest(label=label):
                    source = chain["handoff"] if label.startswith("Opt") else chain["checkpoint"] if label.startswith("checkpoint") else chain["stable_receipt"]
                    forged = copy.deepcopy(source); mutate(forged); forged["payload_sha256"] = FAMILY.payload_sha256(forged)
                    with self.assertRaises(FAMILY.ContractError): validator(forged)
            unstable_log = root / "unstable.log"; unstable_log.write_text(self.good_log(stable=False), encoding="utf-8")
            blocked = FAMILY.build_acceptance(chain["handoff_path"], chain["checkpoint_path_json"], chain["opt_log"], unstable_log, "oh_family_blocked")
            self.assertEqual(blocked["status"], "blocked")

    def test_B_owner_checkpoint_replay_ignores_low_frequency_diagnostics(self) -> None:
        fixture = (ROOT / "tests/fixtures/main_group_open_shell/oh_low_frequency_diagnostics.synthetic.txt").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            chain = self.build_chain(Path(temp).resolve(), expected_frequency_count=1, opt_log_text=fixture)
        evidence = chain["checkpoint"]["opt_freq_evidence"]
        self.assertEqual(evidence["actual_frequency_count"], 1)
        self.assertEqual(evidence["imaginary_frequency_count"], 0)
        self.assertEqual(chain["checkpoint"]["status"], "accepted_final_optimized_checkpoint")

    def test_B_prospective_family_has_no_fabricated_failure_lineage(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve(); chain = self.build_chain(root, prospective=True)
            handoff = chain["handoff"]
            self.assertEqual(handoff["schema"], FAMILY.PROSPECTIVE_HANDOFF_SCHEMA)
            self.assertNotIn("failure_lineage", handoff)
            self.assertEqual(handoff["prospective_lineage"], {
                "classification": "prospective_two_stage_minimum",
                "prior_failed_input_sha256": None,
                "combined_route_forbidden": True,
            })
            schema = json.loads((ROOT / "contracts/main-group-open-shell/minimum-two-stage-family-contracts.schema.json").read_text())
            for artifact in (handoff, chain["checkpoint"], chain["manifest"], chain["opt_receipt"], chain["stable_receipt"]):
                SCHEMA._validate_schema_instance(artifact, schema, schema)
            report = TRANSPORT.parse_gaussian(chain["stable_input"])
            receipt = TRANSPORT.validate_input_approval(chain["stable_receipt_path"], chain["stable_input"], report, "minimum")
            schema_name, _scope = TRANSPORT.expected_live_approval_scope(
                TRANSPORT.live_approval_summary("prospective", report, None, "minimum", receipt)
            )
            self.assertEqual(schema_name, TRANSPORT.OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA)

            forged = copy.deepcopy(handoff)
            forged["prospective_lineage"]["prior_failed_input_sha256"] = "0" * 64
            forged["payload_sha256"] = FAMILY.payload_sha256(forged)
            with self.assertRaises(FAMILY.ContractError):
                FAMILY.validate_handoff(forged)

            spec = json.loads(chain["spec_path"].read_text())
            spec["superseded_input_sha256"] = "1" * 64
            mixed = root / "mixed-spec.json"; mixed.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(FAMILY.ContractError):
                FAMILY.build_family(mixed, root / "mixed-family.json", root / "mixed-opt.gjf", root / "mixed-stable.gjf")

    def test_C_receipt_v3_live_v5_direct_and_wrapper_dry_run_no_network(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve(); chain = self.build_chain(root)
            report = TRANSPORT.parse_gaussian(chain["stable_input"])
            receipt_result = TRANSPORT.validate_input_approval(chain["stable_receipt_path"], chain["stable_input"], report, "minimum")
            self.assertEqual(receipt_result["schema"], TRANSPORT.OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA)
            summary = TRANSPORT.live_approval_summary("ohfamily", report, None, "minimum", receipt_result)
            schema, scope = TRANSPORT.expected_live_approval_scope(summary)
            self.assertEqual(schema, TRANSPORT.OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA)
            approval = {"schema": schema, "decision": "approved", "explicit_confirmation": True, "scope": scope, "authorizations": copy.deepcopy(AUTHORIZATIONS)}
            approval_path = root / "live-v5.json"; approval_path.write_text(json.dumps(approval), encoding="utf-8")
            schema_doc = json.loads((ROOT / "contracts/rtwin-pbs/live-submission-approval-v5.schema.json").read_text())
            SCHEMA._validate_schema_instance(approval, schema_doc, schema_doc)
            opt_report = TRANSPORT.parse_gaussian(chain["opt_input"])
            opt_receipt_result = TRANSPORT.validate_input_approval(chain["opt_receipt_path"], chain["opt_input"], opt_report, "minimum")
            opt_summary = TRANSPORT.live_approval_summary("ohfamily", opt_report, None, "minimum", opt_receipt_result)
            opt_schema, opt_scope = TRANSPORT.expected_live_approval_scope(opt_summary)
            self.assertEqual(opt_schema, TRANSPORT.OPEN_SHELL_FAMILY_LIVE_APPROVAL_SCHEMA)
            self.assertEqual(opt_scope["open_shell_family"]["stage"], "opt_freq")
            self.assertIsNone(opt_scope["open_shell_family"]["checkpoint_sha256"])

            tamper_cases = {
                "project": lambda value: value["scope"].__setitem__("project", "other"),
                "remote directory": lambda value: value["scope"].__setitem__("remote_workdir", "/home/user100/SDL/other"),
                "input SHA": lambda value: value["scope"].__setitem__("input_sha256", "0" * 64),
                "route": lambda value: value["scope"].__setitem__("route", "#p other"),
                "memory": lambda value: value["scope"].__setitem__("mem", "1GB"),
                "cores": lambda value: value["scope"].__setitem__("nprocshared", 1),
                "state": lambda value: value["scope"].__setitem__("multiplicity", 3),
                "receipt": lambda value: value["scope"]["input_approval"].__setitem__("payload_sha256", "1" * 64),
                "family": lambda value: value["scope"]["open_shell_family"].__setitem__("family_payload_sha256", "2" * 64),
                "stage": lambda value: value["scope"]["open_shell_family"].__setitem__("stage", "opt_freq"),
                "checkpoint": lambda value: value["scope"]["open_shell_family"].__setitem__("checkpoint_sha256", "3" * 64),
                "reference": lambda value: value["scope"]["open_shell_family"].__setitem__("reference_family", "RO"),
                "method": lambda value: value["scope"]["open_shell_family"].__setitem__("method", "urohf"),
                "basis": lambda value: value["scope"]["open_shell_family"].__setitem__("basis", "sto-3g"),
                "tier": lambda value: value["scope"]["open_shell_family"]["resources"].__setitem__("resource_tier", "general"),
                "owner replay": lambda value: value["scope"]["open_shell_family"].__setitem__("owner_replay_passed", False),
                "retry": lambda value: value["authorizations"].__setitem__("retry", True),
                "cancel": lambda value: value["authorizations"].__setitem__("cancel", True),
                "cleanup": lambda value: value["authorizations"].__setitem__("cleanup", True),
                "delete": lambda value: value["authorizations"].__setitem__("delete_server_data", True),
                "unknown": lambda value: value.__setitem__("note", "not closed"),
            }
            for index, (label, mutate) in enumerate(tamper_cases.items()):
                with self.subTest(live_v5_tamper=label):
                    forged = copy.deepcopy(approval); mutate(forged)
                    forged_path = root / f"forged-live-{index}.json"; forged_path.write_text(json.dumps(forged), encoding="utf-8")
                    with self.assertRaises(SystemExit): TRANSPORT.validate_live_approval(forged_path, summary)

            args = TRANSPORT.build_parser().parse_args(["submit", str(chain["stable_input"]), "--project", "ohfamily", "--local-dir", str(root / "direct"), "--work-kind", "minimum", "--input-approval-record", str(chain["stable_receipt_path"]), "--approval-record", str(approval_path), "--confirmed", "--dry-run"])
            with mock.patch.object(TRANSPORT, "run", side_effect=AssertionError("network function called")) as network:
                output = StringIO()
                with redirect_stdout(output): args.func(args)
                plan = json.loads(output.getvalue())
            self.assertFalse(network.called); self.assertTrue(plan["live_submission_ready"])

            wrapper_args = AUTO.build_parser().parse_args(["auto", str(chain["stable_input"]), "--project", "ohfamily", "--local-dir", str(root / "wrapper"), "--work-kind", "minimum", "--input-approval-record", str(chain["stable_receipt_path"]), "--approval-record", str(approval_path), "--confirmed", "--dry-run"])
            def run_direct(command: list[str], **_kwargs) -> SimpleNamespace:
                parsed = TRANSPORT.build_parser().parse_args(command[2:]); parsed.func(parsed)
                return SimpleNamespace(returncode=0)
            with mock.patch.object(TRANSPORT, "run", side_effect=AssertionError("network function called")) as network, mock.patch.object(AUTO.subprocess, "run", side_effect=run_direct):
                output = StringIO()
                with redirect_stdout(output): wrapper_args.func(wrapper_args)
            self.assertFalse(network.called)
            preflight = json.loads((root / "wrapper" / "automation_preflight.json").read_text())
            self.assertEqual(preflight["live_approval_requirement"]["status"], "incomplete_non_authorizing_preflight")
            self.assertIsNone(preflight["live_approval_requirement"]["required_schema"])
            self.assertIsNone(preflight["live_approval_requirement"]["scope_proposal"])

    def test_D_old_failed_combined_route_is_classified_and_receipt_generations_fail_closed(self) -> None:
        route = "#p UB3LYP/cc-pVTZ Opt=Tight Freq Stable=Opt SCF=(Tight,XQC) Int=UltraFine NoSymm"
        report = {"route": route, "multiplicity": 2, "geometry_source": "explicit_cartesian", "oldcheckpoint": None, "link1_count": 0, "route_section_count": 1}
        classification = TRANSPORT.input_approval_compatibility(report, "minimum")
        self.assertEqual(classification["status"], "blocked_combined_open_shell_minimum_stability_parse_risk")
        self.assertEqual(classification["failure_classification"], "gaussian_link1_combined_opt_freq_stable_parse_failure")
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            chain = self.build_chain(Path(temp).resolve())
            parsed = TRANSPORT.parse_gaussian(chain["stable_input"])
            generic = copy.deepcopy(chain["stable_receipt"]); generic["schema"] = TRANSPORT.OPEN_SHELL_INPUT_APPROVAL_SCHEMA
            generic_path = Path(temp) / "mixed-v2.json"; generic_path.write_text(json.dumps(generic), encoding="utf-8")
            with self.assertRaises(SystemExit): TRANSPORT.validate_input_approval(generic_path, chain["stable_input"], parsed, "minimum")


if __name__ == "__main__":
    unittest.main()
