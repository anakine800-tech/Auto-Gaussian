#!/usr/bin/env python3
"""Offline tests for the TS–Freq–IRC skill; no network or scheduler access."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-ts-irc" / "scripts" / "ts_irc.py"
DA_FRAGMENT_FIXTURES = ROOT / "tests" / "fixtures" / "da_fragment_endpoint"
SPEC = importlib.util.spec_from_file_location("ts_irc", MODULE)
assert SPEC and SPEC.loader
TS = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(TS)

LOG = """\
 Gaussian 16, Revision A.03,
 Optimization completed.
 -- Stationary point found.
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          1           0        0.000000    0.000000    0.000000
      2          1           0        1.000000    0.000000    0.000000
 ---------------------------------------------------------------------
 Frequencies --  -500.00  100.00  200.00
 Red. masses --     1.00    1.00    1.00
 Frc consts  --     0.10    0.10    0.10
 IR Inten    --     1.00    1.00    1.00
  Atom  AN      X      Y      Z        X      Y      Z        X      Y      Z
    1   1     0.10   0.00   0.00     0.00   0.10   0.00     0.00   0.00   0.10
    2   1    -0.10   0.00   0.00     0.00  -0.10   0.00     0.00   0.00  -0.10
 SCF Done:  E(RHF) =  -1.100000 A.U.
 Normal termination of Gaussian 16
"""


class TsIrcTests(unittest.TestCase):
    def _terminal_job(
        self, project: str, input_path: Path, log_path: Path, *, state: str = "completed"
    ) -> dict:
        return {
            "schema": "gaussian-rtwin-pbs/1",
            "project": project,
            "job_id": "900.master",
            "status": state,
            "results_fetched": True,
            "input_sha256": TS.sha256(input_path),
            "rtwin_sha256_verified": True,
            "server_sha256_verified": True,
            "last_inspection": {
                "schema": "gaussian-job-inspection/1",
                "project": project,
                "job_id": "900.master",
                "state": state,
                "process_alive": False,
                "log_size": log_path.stat().st_size,
                "full_normal_termination_count": log_path.read_text().count(
                    "Normal termination of Gaussian"
                ),
                "full_error_termination_count": log_path.read_text().count(
                    "Error termination"
                ),
            },
        }

    def _terminal_template(
        self, project: str, input_path: Path, task_kind: str, acceptance: dict
    ) -> dict:
        template = {
            "schema": TS.TERMINAL_TEMPLATE_SCHEMA,
            "template_id": f"{project}_{task_kind}_terminal",
            "status": "prepared_offline",
            "task_kind": task_kind,
            "project": project,
            "input_sha256": TS.sha256(input_path),
            "expected_system": {"atom_count": 2, "charge": 0, "multiplicity": 1},
            "acceptance_gate": acceptance,
            "no_submission_authorization": True,
        }
        template["template_payload_sha256"] = TS.terminal_template_payload_sha256(template)
        return template

    def test_one_imaginary_mode_is_candidate_and_displacement_parses(self) -> None:
        result = TS.analyze_ts_log_text(LOG)
        self.assertTrue(result["first_order_saddle_candidate"])
        self.assertEqual(result["g16_revision"], "A.03")
        self.assertEqual(result["frequency_count"], 3)
        self.assertEqual(result["raw_imaginary_frequency_count"], 1)
        self.assertEqual(len(result["imaginary_modes"][0]["displacements"]), 2)

    def test_two_imaginary_modes_is_not_candidate(self) -> None:
        result = TS.analyze_ts_log_text(LOG.replace("-500.00  100.00  200.00", "-500.00 -100.00  200.00"))
        self.assertFalse(result["first_order_saddle_candidate"])
        self.assertEqual(result["raw_imaginary_frequency_count"], 2)

    def test_offline_ts_terminal_intake_stops_at_manual_mode_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "ts.gjf"
            input_path.write_text("%chk=ts.chk\n#p opt=(ts) freq\n\nTS\n\n0 1\nH 0 0 0\nH 1 0 0\n\n")
            log_path = root / "ts.log"
            log_path.write_text(" Charge = 0 Multiplicity = 1\n" + LOG)
            template = self._terminal_template(
                "test_ts", input_path, "ts_freq",
                {"expected_frequency_count": 3, "required_raw_imaginary_frequency_count": 1},
            )
            template_path = root / "template.json"
            template_path.write_text(json.dumps(template))
            job_path = root / "job.json"
            job_path.write_text(json.dumps(self._terminal_job("test_ts", input_path, log_path)))

            intake = TS.ingest_terminal_artifacts(
                template_path, input_path, job_path, log_path
            )
            self.assertEqual(intake["outcome"], "ready_for_manual_mode_review")
            self.assertEqual(intake["acceptance_status"], "manual_review_required")
            self.assertFalse(intake["path_validated"])
            self.assertFalse(intake["automatic_action_authorized"])
            self.assertEqual(intake["scientific_evidence"]["raw_imaginary_frequency_count"], 1)

            template["acceptance_gate"]["expected_frequency_count"] = 4
            template["template_payload_sha256"] = TS.terminal_template_payload_sha256(template)
            template_path.write_text(json.dumps(template))
            incomplete = TS.ingest_terminal_artifacts(
                template_path, input_path, job_path, log_path
            )
            self.assertEqual(incomplete["outcome"], "incomplete_frequency_analysis")
            self.assertEqual(incomplete["acceptance_status"], "not_accepted")

    def test_offline_irc_terminal_intake_requires_endpoint_identity_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "irc.gjf"
            input_path.write_text(
                "%oldchk=ts.chk\n%chk=irc.chk\n"
                "#p irc=(rcfc,forward,maxpoints=2) geom=allcheck guess=read\n\n"
            )
            log_path = root / "irc.log"
            log_path.write_text(
                " Charge = 0 Multiplicity = 1\n"
                " Delta-x Convergence Met\n Point Number: 1 Path Number: 1\n"
                " Delta-x Convergence Met\n Point Number: 2 Path Number: 1\n"
                " Standard orientation:\n"
                " ---------------------------------------------------------------------\n"
                " Center     Atomic      Atomic             Coordinates (Angstroms)\n"
                " Number     Number       Type             X           Y           Z\n"
                " ---------------------------------------------------------------------\n"
                "      1          1           0        0.000000    0.000000    0.000000\n"
                "      2          1           0        1.000000    0.000000    0.000000\n"
                " ---------------------------------------------------------------------\n"
                " Calculation of FORWARD path complete.\n"
                " Normal termination of Gaussian 16\n"
            )
            template = self._terminal_template(
                "test_if", input_path, "irc",
                {"direction": "forward", "maximum_points": 2},
            )
            template_path = root / "template.json"
            template_path.write_text(json.dumps(template))
            job = self._terminal_job("test_if", input_path, log_path)
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job))

            intake = TS.ingest_terminal_artifacts(
                template_path, input_path, job_path, log_path
            )
            self.assertEqual(intake["outcome"], "ready_for_endpoint_structure_review")
            self.assertEqual(intake["acceptance_status"], "structural_review_required")
            self.assertEqual(
                intake["scientific_evidence"]["chemical_side_assignment"],
                "pending_structural_review",
            )
            self.assertFalse(intake["path_validated"])

            job["last_inspection"]["process_alive"] = True
            job_path.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError, "still alive"):
                TS.ingest_terminal_artifacts(template_path, input_path, job_path, log_path)

    def test_terminal_intake_rejects_template_or_job_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "ts.gjf"
            input_path.write_text("input\n")
            log_path = root / "ts.log"
            log_path.write_text(" Charge = 0 Multiplicity = 1\n" + LOG)
            template = self._terminal_template(
                "hash_ts", input_path, "ts_freq",
                {"expected_frequency_count": 3, "required_raw_imaginary_frequency_count": 1},
            )
            template_path = root / "template.json"
            template_path.write_text(json.dumps(template))
            job = self._terminal_job("hash_ts", input_path, log_path)
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job))

            template["expected_system"]["atom_count"] = 3
            template_path.write_text(json.dumps(template))
            with self.assertRaisesRegex(ValueError, "payload hash"):
                TS.ingest_terminal_artifacts(template_path, input_path, job_path, log_path)

            template["expected_system"]["atom_count"] = 2
            template["template_payload_sha256"] = TS.terminal_template_payload_sha256(template)
            template_path.write_text(json.dumps(template))
            job["input_sha256"] = "0" * 64
            job_path.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError, "input hash"):
                TS.ingest_terminal_artifacts(template_path, input_path, job_path, log_path)

    def test_qst2_rejects_atom_order_mismatch(self) -> None:
        structure = {"charge": 0, "multiplicity": 1, "atoms": [{"element": "C"}, {"element": "H"}]}
        swapped = {"charge": 0, "multiplicity": 1, "atoms": [{"element": "H"}, {"element": "C"}]}
        report = TS.validate_input_family("qst2", {"reactant": structure, "product": swapped}, [1, 2])
        self.assertFalse(report["valid"])

    def test_cartesian_input_allows_multiline_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.gjf"
            path.write_text("%mem=1GB\n#p Opt=(TS)\n B3LYP/6-31G(d)\n\nTitle\n\n0 1\nH 0 0 0\nH 0 0 1\n\n")
            parsed = TS.parse_cartesian_input(path)
            self.assertEqual(parsed["charge"], 0)
            self.assertEqual(len(parsed["atoms"]), 2)

    def test_mode_review_and_irc_plan_require_explicit_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); result = TS.analyze_ts_log_text(LOG)
            result_path = root / "ts.json"; result_path.write_text(json.dumps(result))
            TS.create_mode_review(result, [(1, 2)], root / "review", 0.1, TS.sha256(result_path))
            self.assertTrue((root / "review" / "mode_plus.xyz").is_file())
            self.assertTrue((root / "review" / "mode_minus.xyz").is_file())
            decision_path = root / "mode_decision.json"
            TS.record_mode_decision(root / "review" / "mode_review.json", "accepted", decision_path)
            self.assertEqual(json.loads(result_path.read_text())["mode_review_status"], "pending")
            checkpoint = root / "ts.chk"; checkpoint.write_bytes(b"checkpoint")
            plan = TS.build_irc_plan({"schema": TS.SCHEMA, "workflow_id": "test"}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir")
            self.assertEqual(plan["submission_status"], "planned_not_submitted")
            self.assertEqual(plan["g16_revision"], "A.03")

    def test_irc_plan_rejects_swapped_directions_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); result = TS.analyze_ts_log_text(LOG)
            result_path = root / "ts.json"; result_path.write_text(json.dumps(result))
            TS.create_mode_review(result, [(1, 2)], root / "review", 0.1, TS.sha256(result_path))
            decision_path = root / "decision.json"
            TS.record_mode_decision(root / "review" / "mode_review.json", "accepted", decision_path)
            checkpoint = root / "ts.chk"; checkpoint.write_bytes(b"checkpoint")
            with self.assertRaises(ValueError):
                TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Reverse)", "#p IRC=(Forward)", "abc_if", "abc_ir")
            review_path = root / "review" / "mode_review.json"
            review = json.loads(review_path.read_text())
            review_path.write_text(json.dumps({**review, "amplitude": 0.2}))
            with self.assertRaises(ValueError):
                TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, checkpoint, review_path, decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir")
            review_path.write_text(json.dumps(review, indent=2) + "\n")
            result_path.write_text(json.dumps({**result, "diagnostics": ["changed"]}))
            with self.assertRaises(ValueError):
                TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir")

    def test_family_manifest_requires_explicit_routes_and_tiers(self) -> None:
        audit = {"schema": TS.SCHEMA, "valid": True}
        protocol = {"workflow_id": "test", "project_prefix": "test_ts", "expected_reactant_identity": "A", "expected_product_identity": "B", "coordinate_changes": [{"forming": [1, 2]}], "routes": {"ts_freq": "#p Opt=(TS) Freq", "irc_forward": "#p IRC=(Forward)", "irc_reverse": "#p IRC=(Reverse)", "endpoint_opt_freq": "#p Opt Freq"}, "resource_tiers": {"ts_freq": "simple", "irc": "simple", "endpoint": "simple"}, "temperature_k": 298.15, "standard_state": "1M"}
        manifest = TS.create_family_manifest(audit, protocol)
        self.assertEqual(manifest["status"], "prepared_not_submitted")
        self.assertTrue(manifest["safety"]["no_submission_authorization"])

    def test_checkpoint_atom_order_audit_and_coordinate_free_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ts_input = root / "ts.gjf"
            ts_input.write_text(
                "%chk=ts.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p b3lyp/6-31g(d) opt=(ts,calcfc,noeigentest) freq\n\n"
                "TS\n\n0 1\nH 0 0 0\nH 1 0 0\n\n"
            )
            ts_log = root / "ts.log"
            ts_log.write_text(" Charge = 0 Multiplicity = 1\n" + LOG)
            result = TS.analyze_ts_log_text(ts_log.read_text())
            result["log_sha256"] = TS.sha256(ts_log)
            result_path = root / "ts_result.json"
            result_path.write_text(json.dumps(result))
            TS.create_mode_review(result, [(1, 2)], root / "review", 0.1, TS.sha256(result_path))
            review_path = root / "review" / "mode_review.json"
            decision_path = root / "decision.json"
            TS.record_mode_decision(review_path, "accepted", decision_path)
            checkpoint = root / "ts.chk"
            checkpoint.write_bytes(b"reviewed checkpoint")
            audit = TS.audit_checkpoint_provenance(
                ts_input, ts_log, result_path, checkpoint, review_path, decision_path
            )
            self.assertEqual(audit["audit_status"], "passed")
            self.assertEqual([item["element"] for item in audit["atom_order"]], ["H", "H"])
            audit_path = root / "checkpoint_audit.json"
            audit_path.write_text(json.dumps(audit))
            output = root / "irc_f.gjf"
            manifest = TS.build_allcheck_irc_input(
                audit_path,
                checkpoint,
                output,
                "#p b3lyp/6-31g(d) irc=(rcfc,forward,maxpoints=30,stepsize=5,maxcycle=40,recorrect=yes) geom=allcheck guess=read",
                "forward",
                "12GB",
                8,
            )
            text = output.read_text()
            self.assertIn("%oldchk=ts.chk", text)
            self.assertIn("geom=allcheck", text.lower())
            self.assertNotIn("\n0 1\n", text)
            self.assertEqual(manifest["checkpoint_sha256"], TS.sha256(checkpoint))

    def test_allcheck_builder_rejects_recorrect_never(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint = root / "ts.chk"
            checkpoint.write_bytes(b"checkpoint")
            audit = {
                "schema": "gaussian-checkpoint-geometry-audit/1",
                "audit_status": "passed",
                "checkpoint_file": "ts.chk",
                "checkpoint_sha256": TS.sha256(checkpoint),
                "charge": 0,
                "multiplicity": 1,
                "atom_count": 1,
                "atom_order": [{"index": 1, "atomic_number": 1, "element": "H"}],
            }
            audit_path = root / "audit.json"
            audit_path.write_text(json.dumps(audit))
            with self.assertRaises(ValueError):
                TS.build_allcheck_irc_input(
                    audit_path,
                    checkpoint,
                    root / "irc.gjf",
                    "#p hf/sto-3g irc=(rcfc,forward,recorrect=never) geom=allcheck guess=read",
                    "forward",
                    "12GB",
                    8,
                )

    def test_successful_irc_endpoint_audit_and_allcheck_opt_freq_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            irc_input = root / "irc_f.gjf"
            irc_input.write_text(
                "%oldchk=ts.chk\n%chk=irc_f.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p b3lyp/6-31g(d) irc=(rcfc,forward,maxpoints=2) geom=allcheck guess=read\n\n"
            )
            log = (
                " Charge = 0 Multiplicity = 1\n"
                " Delta-x Convergence Met\n Point Number: 1 Path Number: 1\n"
                " Delta-x Convergence Met\n Point Number: 2 Path Number: 1\n"
                " Standard orientation:\n"
                " ---------------------------------------------------------------------\n"
                " Center     Atomic      Atomic             Coordinates (Angstroms)\n"
                " Number     Number       Type             X           Y           Z\n"
                " ---------------------------------------------------------------------\n"
                "      1          6           0        0.000000    0.000000    0.000000\n"
                "      2          6           0        1.500000    0.000000    0.000000\n"
                " ---------------------------------------------------------------------\n"
                " Calculation of FORWARD path complete.\n"
                " Normal termination of Gaussian 16\n"
            )
            irc_log = root / "irc_f.log"; irc_log.write_text(log)
            result = {
                "schema": "gaussian-result/1",
                "status": "completed",
                "normal_termination": True,
                "error_termination": False,
                "final_energy_hartree": -10.0,
                "final_coordinates": [
                    {"center": 1, "atomic_number": 6, "element": "C", "x": 0.0, "y": 0.0, "z": 0.0},
                    {"center": 2, "atomic_number": 6, "element": "C", "x": 1.5, "y": 0.0, "z": 0.0},
                ],
            }
            result_path = root / "result.json"; result_path.write_text(json.dumps(result))
            checkpoint = root / "irc_f.chk"; checkpoint.write_bytes(b"final irc point")
            job = {
                "schema": "gaussian-rtwin-pbs/1",
                "project": "irc_f",
                "job_id": "1.master",
                "status": "completed",
                "results_fetched": True,
                "input_sha256": TS.sha256(irc_input),
                "gaussian": {
                    "checkpoint": "irc_f.chk",
                    "route": "#p b3lyp/6-31g(d) irc=(rcfc,forward,maxpoints=2) geom=allcheck guess=read",
                },
            }
            job_path = root / "job.json"; job_path.write_text(json.dumps(job))
            audit = TS.audit_irc_endpoint_provenance(
                irc_input, irc_log, result_path, job_path, checkpoint,
                "forward", "reactant", 2, [(1, 2)],
            )
            self.assertEqual(audit["completed_point"], 2)
            self.assertEqual(audit["reviewed_forming_bond_distances"][0]["distance_angstrom"], 1.5)
            audit_path = root / "endpoint_audit.json"; audit_path.write_text(json.dumps(audit))
            endpoint = root / "endpoint.gjf"
            manifest = TS.build_allcheck_endpoint_input(
                audit_path, checkpoint, endpoint,
                "#p b3lyp/6-31g(d) opt freq geom=allcheck guess=read",
                "12GB", 8,
            )
            self.assertEqual(manifest["continuation_kind"], "endpoint_opt_freq")
            self.assertNotIn("\n0 1\n", endpoint.read_text())

    def test_endpoint_builder_rejects_ts_or_missing_freq(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint = root / "irc.chk"; checkpoint.write_bytes(b"checkpoint")
            audit = {
                "schema": "gaussian-irc-endpoint-audit/1",
                "audit_status": "passed",
                "checkpoint_file": "irc.chk",
                "checkpoint_sha256": TS.sha256(checkpoint),
                "chemical_side": "product",
                "direction": "reverse",
                "charge": 0,
                "multiplicity": 1,
                "atom_count": 1,
                "atom_order": [{"index": 1, "atomic_number": 1, "element": "H"}],
            }
            audit_path = root / "audit.json"; audit_path.write_text(json.dumps(audit))
            for route in (
                "#p hf/sto-3g opt geom=allcheck guess=read",
                "#p hf/sto-3g opt=(ts) freq geom=allcheck guess=read",
            ):
                with self.assertRaises(ValueError):
                    TS.build_allcheck_endpoint_input(
                        audit_path, checkpoint, root / ("bad_" + str(len(route)) + ".gjf"),
                        route, "12GB", 8,
                    )

    def test_da_endpoint_component_proposal_detects_reviewable_fragments(self) -> None:
        proposal = TS.propose_endpoint_components(
            DA_FRAGMENT_FIXTURES / "endpoint_audit.json",
            DA_FRAGMENT_FIXTURES / "source_irc_result.json",
        )
        self.assertFalse(proposal["calculation_ready"])
        self.assertEqual(proposal["component_count"], 2)
        self.assertEqual([item["formula"] for item in proposal["components"]], ["C4H6", "C2H4"])
        self.assertEqual(
            proposal["components"][0]["source_atom_indices"],
            [1, 2, 3, 4, 7, 8, 9, 10, 11, 12],
        )
        self.assertEqual(proposal["components"][1]["source_atom_indices"], [5, 6, 13, 14, 15, 16])

    def test_da_fragment_build_and_zero_imaginary_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proposal = TS.propose_endpoint_components(
                DA_FRAGMENT_FIXTURES / "endpoint_audit.json",
                DA_FRAGMENT_FIXTURES / "source_irc_result.json",
            )
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(proposal))
            review = {
                "schema": "gaussian-irc-component-review/1",
                "proposal_sha256": TS.sha256(proposal_path),
                "decision": "accepted",
                "confirmed": True,
                "spin_coupling_note": "Two reviewed closed-shell singlet reactant fragments.",
                "components": [
                    {
                        "component_id": 1,
                        "source_atom_indices": [1, 2, 3, 4, 7, 8, 9, 10, 11, 12],
                        "identity": "1,3-butadiene",
                        "project": "fixture_butad",
                        "charge": 0,
                        "multiplicity": 1,
                    },
                    {
                        "component_id": 2,
                        "source_atom_indices": [5, 6, 13, 14, 15, 16],
                        "identity": "ethene",
                        "project": "fixture_ethene",
                        "charge": 0,
                        "multiplicity": 1,
                    },
                ],
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review))
            output_dir = root / "built"
            plan = TS.build_fragment_endpoint_inputs(
                proposal_path,
                review_path,
                output_dir,
                "#p b3lyp/6-31g(d) opt=(tight,calcfc) freq int=ultrafine",
                "50GB",
                22,
            )
            self.assertEqual(plan["status"], "planned_not_submitted")
            self.assertTrue((output_dir / "fixture_butad" / "fixture_butad.gjf").is_file())
            self.assertTrue((output_dir / "fixture_ethene" / "fixture_ethene.gjf").is_file())
            self.assertNotIn("geom=allcheck", (output_dir / "fixture_butad" / "fixture_butad.gjf").read_text().lower())
            plan_path = output_dir / "fragment_endpoint_plan.json"
            job_paths = {}
            for fragment in plan["fragments"]:
                project = fragment["project"]
                job_path = root / f"{project}_job.json"
                job_path.write_text(
                    json.dumps(
                        {
                            "schema": "gaussian-rtwin-pbs/1",
                            "project": project,
                            "job_id": f"{fragment['component_id']}.master",
                            "status": "completed",
                            "results_fetched": True,
                            "input_sha256": fragment["input_sha256"],
                        }
                    )
                )
                job_paths[project] = job_path
            validation = TS.audit_fragment_endpoint_results(
                plan_path,
                {
                    "fixture_butad": DA_FRAGMENT_FIXTURES / "butadiene_result.json",
                    "fixture_ethene": DA_FRAGMENT_FIXTURES / "ethene_result.json",
                },
                job_paths,
            )
            self.assertEqual(validation["validation_status"], "passed")
            self.assertAlmostEqual(
                validation["isolated_fragment_electronic_energy_sum_hartree"],
                -234.5739442852,
                places=10,
            )
            self.assertTrue(all(item["minimum_accepted"] for item in validation["fragments"]))
            wrong_job = json.loads(job_paths["fixture_butad"].read_text())
            wrong_job["input_sha256"] = "0" * 64
            job_paths["fixture_butad"].write_text(json.dumps(wrong_job))
            with self.assertRaises(ValueError):
                TS.audit_fragment_endpoint_results(
                    plan_path,
                    {
                        "fixture_butad": DA_FRAGMENT_FIXTURES / "butadiene_result.json",
                        "fixture_ethene": DA_FRAGMENT_FIXTURES / "ethene_result.json",
                    },
                    job_paths,
                )

    def test_fragment_builder_and_result_audit_preserve_scientific_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proposal = TS.propose_endpoint_components(
                DA_FRAGMENT_FIXTURES / "endpoint_audit.json",
                DA_FRAGMENT_FIXTURES / "source_irc_result.json",
            )
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(proposal))
            review = {
                "schema": "gaussian-irc-component-review/1",
                "proposal_sha256": TS.sha256(proposal_path),
                "decision": "accepted",
                "confirmed": False,
                "spin_coupling_note": "Not yet approved.",
                "components": [],
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review))
            with self.assertRaises(ValueError):
                TS.build_fragment_endpoint_inputs(
                    proposal_path,
                    review_path,
                    root / "unapproved",
                    "#p b3lyp/6-31g(d) opt freq",
                    "50GB",
                    22,
                )
            failure = json.loads((DA_FRAGMENT_FIXTURES / "combined_endpoint_failure.json").read_text())
            self.assertEqual(failure["optimization_steps"], 99)
            self.assertFalse(failure["optimization_success"])
            self.assertIn("Number of steps exceeded", failure["diagnostics"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()
