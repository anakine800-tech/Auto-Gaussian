#!/usr/bin/env python3
"""Offline tests for the TS–Freq–IRC skill; no network or scheduler access."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-ts-irc" / "scripts" / "ts_irc.py"
DA_FRAGMENT_FIXTURES = ROOT / "tests" / "fixtures" / "da_fragment_endpoint"
QST_RAW_FIXTURES = ROOT / "tests" / "fixtures" / "qst_raw_input"
QST_RAW_AUDIT_SCHEMA = ROOT / "skills" / "auto-g16-ts-irc" / "contracts" / "qst-raw-input-syntax-audit.schema.json"
QST_REVISION_SCHEMA = ROOT / "skills" / "auto-g16-ts-irc" / "contracts" / "installed-g16-qst-syntax-evidence.schema.json"
SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SPEC = importlib.util.spec_from_file_location("ts_irc", MODULE)
assert SPEC and SPEC.loader
TS = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(TS)
SCHEMA_SPEC = importlib.util.spec_from_file_location("qst_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC); SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)

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
    def _qst_fixture_root(self, parent: Path) -> Path:
        destination = parent / "qst_case"
        shutil.copytree(QST_RAW_FIXTURES, destination)
        return destination

    def _qst_atom_map_audit(self, root: Path, mode: str) -> Path:
        labels = ["reactant", "product"] if mode == "qst2" else ["reactant", "product", "ts"]
        source_names = {
            "reactant": "reactant.gjf",
            "product": "product.gjf",
            "ts": "reviewed_guess.gjf",
        }
        structures = {label: TS.parse_cartesian_input(root / source_names[label]) for label in labels}
        report = TS.validate_input_family(mode, structures, [1, 2])
        if mode == "qst3":
            report["qst3_guess_review"] = {
                "decision": "reviewed_guess",
                "confirmed": True,
                "minimum_claim": False,
                "reviewed_structure_sha256": structures["ts"]["sha256"],
                "reviewer": "synthetic_offline_fixture_reviewer",
                "rationale": "The third structure is reviewed only as a QST3 guess and is not a minimum claim.",
            }
        path = root / f"{mode}_atom_map_audit.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return path

    def _qst_revision_evidence(
        self,
        root: Path,
        mode: str,
        *,
        verification_status: str = "verified",
        source_kind: str = "successful_installed_revision_run",
        exact_binding: bool = True,
    ) -> Path:
        if verification_status == "pending":
            example = None
        else:
            input_path = root / f"{mode}_plain.gjf"
            if source_kind == "official_installed_revision_documentation":
                source_path = root / "official_source_nonbinding.synthetic.txt"
            else:
                source_path = root / f"known_good_{mode}.synthetic.txt"
            binding = None
            if exact_binding:
                binding = {
                    "syntax_profile": "gaussian-qst-cartesian-multistructure/1",
                    "exact_assertion": "exact_qst_multistructure_syntax_supported_for_installed_revision",
                    "source_locator": "Normal termination of Gaussian 16",
                    "reviewed": True,
                    "reviewer": "synthetic_offline_fixture_reviewer",
                    "rationale": "Synthetic binding used only to exercise deterministic offline validation.",
                }
            example = {
                "mode": mode,
                "input": {"path": input_path.name, "sha256": TS.sha256(input_path), "size_bytes": input_path.stat().st_size},
                "source": {"path": source_path.name, "sha256": TS.sha256(source_path), "size_bytes": source_path.stat().st_size},
                "source_kind": source_kind,
                "usable_status": "known_usable",
                "source_assertion": "known_usable_for_installed_revision",
                "support_binding": binding,
            }
        evidence = {
            "schema": TS.QST_REVISION_EVIDENCE_SCHEMA,
            "evidence_id": f"synthetic_{mode}_{verification_status}_{source_kind}",
            "installed_revision": "Gaussian 16 Revision A.03",
            "verification_status": verification_status,
            "known_good_example": example,
            "limitations": ["Synthetic offline fixture only; it grants no scientific or live authority."],
            "no_submission_authorization": True,
        }
        evidence["evidence_payload_sha256"] = TS._canonical_payload_sha256(evidence, "evidence_payload_sha256")
        path = root / f"{mode}_{verification_status}_{source_kind}_{exact_binding}.json"
        path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return path

    def _audit_qst(self, root: Path, mode: str, raw_name: str | None = None, **evidence_options: object) -> tuple[dict, Path]:
        raw = root / (raw_name or f"{mode}_plain.gjf")
        atom_map = self._qst_atom_map_audit(root, mode)
        evidence = self._qst_revision_evidence(root, mode, **evidence_options)
        output = root / f"{raw.stem}_audit.json"
        result = TS.audit_raw_qst_input(
            raw,
            TS.sha256(raw),
            atom_map,
            TS.sha256(atom_map),
            evidence,
            TS.sha256(evidence),
            output,
        )
        return result, output

    def _terminal_job(
        self, project: str, input_path: Path, log_path: Path, *, state: str = "completed", inspection_v2: bool = False,
    ) -> dict:
        job = {
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
        if inspection_v2:
            inspection = job["last_inspection"]
            inspection.update({
                "schema": "gaussian-job-inspection/2", "source": "single_remote_read_only_snapshot",
                "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0,
                "termination_counts_known": True, "evidence_conflict": False,
            })
            inspection["evidence_sha256"] = TS._transport_digest(inspection)
        return job

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

    def test_specialist_classification_and_mode_geometry_helpers_fail_closed(self) -> None:
        result = TS.analyze_ts_log_text(LOG)
        classification = TS.classify_ts_freq_result_facts(result)
        self.assertEqual(classification["status"], "completed")
        self.assertTrue(classification["first_order_saddle_candidate"])
        terminal = TS.classify_ts_freq_terminal_facts(
            job_state="completed",
            error_termination_count=0,
            optimization_completed=True,
            stationary_point_found=True,
            atom_count=2,
            expected_atom_count=2,
            frequency_count=3,
            expected_frequency_count=3,
            raw_imaginary_frequency_count=1,
        )
        self.assertEqual(terminal["outcome"], "ready_for_manual_mode_review")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "ts.json"
            result_path.write_text(json.dumps(result))
            review = TS.create_mode_review(
                result, [(1, 2)], root / "review", 0.1, TS.sha256(result_path)
            )
            TS.validate_mode_review_geometry(result, review)
            review["distance_projections"][0]["plus_angstrom"] += 0.1
            with self.assertRaisesRegex(ValueError, "displacement arithmetic"):
                TS.validate_mode_review_geometry(result, review)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nonfinite = json.loads(json.dumps(result))
            nonfinite["final_coordinates"][0]["x"] = float("nan")
            with self.assertRaisesRegex(ValueError, "finite number"):
                TS.create_mode_review(nonfinite, [], root / "nonfinite", 0.1, "a" * 64)
            self.assertFalse((root / "nonfinite").exists())
            wrong_atom = json.loads(json.dumps(result))
            wrong_atom["final_coordinates"][0]["atomic_number"] = 999
            wrong_atom["imaginary_modes"][0]["displacements"][0]["atomic_number"] = 999
            with self.assertRaisesRegex(ValueError, "element and atomic number"):
                TS.create_mode_review(wrong_atom, [(1, 2)], root / "wrong-atom", 0.1, "a" * 64)
            self.assertFalse((root / "wrong-atom").exists())

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

    def test_terminal_intake_accepts_exact_inspection_v2_and_rejects_unknown_or_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); input_path = root / "ts.gjf"; input_path.write_text("%chk=ts.chk\n#p opt=(ts) freq\n\nTS\n\n0 1\nH 0 0 0\nH 1 0 0\n\n")
            log_path = root / "ts.log"; log_path.write_text(" Charge = 0 Multiplicity = 1\n" + LOG)
            template = self._terminal_template("test_v2", input_path, "ts_freq", {"expected_frequency_count": 3, "required_raw_imaginary_frequency_count": 1})
            template_path = root / "template.json"; template_path.write_text(json.dumps(template))
            job = self._terminal_job("test_v2", input_path, log_path, inspection_v2=True)
            job_path = root / "job.json"; job_path.write_text(json.dumps(job))
            self.assertEqual(TS.ingest_terminal_artifacts(template_path, input_path, job_path, log_path)["outcome"], "ready_for_manual_mode_review")
            job["last_inspection"]["freshness"] = "stale"; job_path.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError, "stale, malformed, tampered"):
                TS.ingest_terminal_artifacts(template_path, input_path, job_path, log_path)
            job["last_inspection"]["schema"] = "gaussian-job-inspection/99"; job_path.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError, "terminal Gaussian inspection"):
                TS.ingest_terminal_artifacts(template_path, input_path, job_path, log_path)

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

    def test_raw_qst2_and_qst3_audits_bind_revision_and_never_authorize_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            for mode in ("qst2", "qst3"):
                with self.subTest(mode=mode):
                    result, output = self._audit_qst(root, mode)
                    self.assertEqual(result["audit_status"], "syntax_verified_for_installed_revision")
                    self.assertEqual(result["supported_syntax_subset"], "plain_cartesian_qst_multistructure/1")
                    self.assertFalse(result["calculation_ready"])
                    self.assertTrue(result["no_submission_authorization"])
                    self.assertEqual(result["next_step"], "manual_input_review_only")
                    self.assertEqual(result["audit_payload_sha256"], TS.qst_raw_audit_payload_sha256(result))
                    replay = TS.validate_qst_raw_audit_artifact(output)
                    self.assertEqual(replay["audit_payload_sha256"], result["audit_payload_sha256"])
                    if mode == "qst3":
                        self.assertEqual(result["structures"][2]["role"], "reviewed_guess")
                        self.assertTrue(result["qst3_third_structure"]["reviewed_guess_confirmed"])
                        self.assertFalse(result["qst3_third_structure"]["minimum_claim_allowed"])

    def test_raw_qst_audit_blocks_pending_or_nonbinding_revision_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            pending, _ = self._audit_qst(root, "qst2", verification_status="pending")
            self.assertEqual(pending["audit_status"], "blocked_pending_installed_revision_verification")
            self.assertEqual(pending["syntax_runnable_claim"], "not_claimed")
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            nonbinding, _ = self._audit_qst(
                root,
                "qst2",
                source_kind="official_installed_revision_documentation",
                exact_binding=False,
            )
            self.assertEqual(nonbinding["audit_status"], "blocked_pending_installed_revision_verification")
            self.assertEqual(nonbinding["checks"]["installed_revision_applicability"], "blocked")

    def test_raw_qst_audit_distinguishes_unsupported_legal_forms_from_invalid_plain_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            unsupported, _ = self._audit_qst(root, "qst2", "qst2_unsupported_freeze_flag.gjf")
            self.assertEqual(unsupported["audit_status"], "blocked_unsupported_syntax")
            self.assertEqual(unsupported["diagnostics"][0]["code"], "unsupported_cartesian_columns")
            self.assertEqual(unsupported["checks"]["installed_revision_applicability"], "not_evaluated")
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            invalid, _ = self._audit_qst(root, "qst2", "qst2_invalid_missing_separator.gjf")
            self.assertEqual(invalid["audit_status"], "failed")
            self.assertEqual(invalid["syntax_runnable_claim"], "not_claimed")

    def test_raw_qst_audit_rejects_unreviewed_qst3_guess_and_atom_map_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            atom_map = self._qst_atom_map_audit(root, "qst3")
            document = json.loads(atom_map.read_text(encoding="utf-8"))
            document.pop("qst3_guess_review")
            atom_map.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            evidence = self._qst_revision_evidence(root, "qst3")
            raw = root / "qst3_plain.gjf"
            output = root / "unreviewed_qst3_audit.json"
            result = TS.audit_raw_qst_input(
                raw, TS.sha256(raw), atom_map, TS.sha256(atom_map), evidence, TS.sha256(evidence), output
            )
            self.assertEqual(result["audit_status"], "failed")
            self.assertEqual(result["checks"]["qst3_reviewed_guess_role"], "failed")
            self.assertFalse(result["qst3_third_structure"]["minimum_claim_allowed"])
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            atom_map = self._qst_atom_map_audit(root, "qst2")
            document = json.loads(atom_map.read_text(encoding="utf-8"))
            document["structures"]["product"]["charge"] = 1
            atom_map.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            evidence = self._qst_revision_evidence(root, "qst2")
            raw = root / "qst2_plain.gjf"
            output = root / "drifted_map_audit.json"
            result = TS.audit_raw_qst_input(
                raw, TS.sha256(raw), atom_map, TS.sha256(atom_map), evidence, TS.sha256(evidence), output
            )
            self.assertEqual(result["audit_status"], "failed")
            self.assertEqual(result["checks"]["atom_map_and_structure_identity"], "failed")

    def test_raw_qst_zsymb_failure_is_preserved_without_rewrite_or_resubmission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            raw = root / "qst2_plain.gjf"
            atom_map = self._qst_atom_map_audit(root, "qst2")
            evidence = self._qst_revision_evidence(root, "qst2")
            failure = root / "zsymb_eof.synthetic.txt"
            output = root / "zsymb_audit.json"
            result = TS.audit_raw_qst_input(
                raw, TS.sha256(raw), atom_map, TS.sha256(atom_map), evidence, TS.sha256(evidence), output,
                zsymb_failure_log_path=failure, zsymb_failure_log_sha256=TS.sha256(failure),
            )
            self.assertEqual(result["audit_status"], "failed_preserved_zsymb_eof")
            self.assertFalse(result["automatic_rewrite_authorized"])
            self.assertFalse(result["automatic_resubmission_authorized"])
            TS.validate_qst_raw_audit_artifact(output)

    def test_raw_qst_artifact_is_portable_immutable_and_replay_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            result, output = self._audit_qst(root, "qst2")
            self.assertFalse(Path(result["raw_input"]["path"]).is_absolute())
            with self.assertRaisesRegex(ValueError, "overwrite"):
                TS.audit_raw_qst_input(
                    root / "qst2_plain.gjf", TS.sha256(root / "qst2_plain.gjf"),
                    root / "qst2_atom_map_audit.json", TS.sha256(root / "qst2_atom_map_audit.json"),
                    root / "qst2_verified_successful_installed_revision_run_True.json",
                    TS.sha256(root / "qst2_verified_successful_installed_revision_run_True.json"), output,
                )
            raw = root / "qst2_plain.gjf"
            raw.write_text(raw.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference changed"):
                TS.validate_qst_raw_audit_artifact(output)

    def test_raw_qst_schemas_and_cli_offline_integration(self) -> None:
        for schema_path in (QST_RAW_AUDIT_SCHEMA, QST_REVISION_SCHEMA):
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR.validate_schema_document(schema)
        with tempfile.TemporaryDirectory() as temp:
            root = self._qst_fixture_root(Path(temp))
            atom_map = self._qst_atom_map_audit(root, "qst2")
            evidence = self._qst_revision_evidence(root, "qst2")
            evidence_document = json.loads(evidence.read_text(encoding="utf-8"))
            revision_schema = json.loads(QST_REVISION_SCHEMA.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(evidence_document, revision_schema, revision_schema)
            raw = root / "qst2_plain.gjf"
            output = root / "cli_audit.json"
            completed = subprocess.run(
                [
                    sys.executable, str(MODULE), "audit-qst-raw-input",
                    "--input", str(raw), "--input-sha256", TS.sha256(raw),
                    "--atom-map-audit", str(atom_map), "--atom-map-audit-sha256", TS.sha256(atom_map),
                    "--installed-revision-evidence", str(evidence),
                    "--installed-revision-evidence-sha256", TS.sha256(evidence),
                    "--output", str(output),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("syntax_verified_for_installed_revision", completed.stdout)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(
                artifact,
                json.loads(QST_RAW_AUDIT_SCHEMA.read_text(encoding="utf-8")),
                json.loads(QST_RAW_AUDIT_SCHEMA.read_text(encoding="utf-8")),
            )
            replay = subprocess.run(
                [sys.executable, str(MODULE), "validate-qst-raw-audit", str(output)],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("gaussian-qst-raw-input-syntax-audit-validation/1", replay.stdout)

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
            with self.assertRaisesRegex(ValueError, "replay-only"):
                TS.build_irc_plan({"schema": TS.SCHEMA, "workflow_id": "test"}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir")
            plan = TS.build_irc_plan({"schema": TS.SCHEMA, "workflow_id": "test"}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir", allow_historical_replay=True)
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
                TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Reverse)", "#p IRC=(Forward)", "abc_if", "abc_ir", allow_historical_replay=True)
            review_path = root / "review" / "mode_review.json"
            review = json.loads(review_path.read_text())
            review_path.write_text(json.dumps({**review, "amplitude": 0.2}))
            with self.assertRaises(ValueError):
                TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, checkpoint, review_path, decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir", allow_historical_replay=True)
            review_path.write_text(json.dumps(review, indent=2) + "\n")
            result_path.write_text(json.dumps({**result, "diagnostics": ["changed"]}))
            with self.assertRaises(ValueError):
                TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, checkpoint, root / "review" / "mode_review.json", decision_path, "A.03", "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir", allow_historical_replay=True)

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
                "execution_batch": {"attempt_id": "qsub-attempt-irc-forward"},
                "gaussian": {
                    "checkpoint": "irc_f.chk",
                    "route": "#p b3lyp/6-31g(d) irc=(rcfc,forward,maxpoints=2) geom=allcheck guess=read",
                },
            }
            inspection = {"schema": "gaussian-job-inspection/2", "project": "irc_f", "job_id": "1.master", "state": "completed", "collected_at": "2026-07-19T12:00:00Z", "source": "single_remote_read_only_snapshot", "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0, "termination_counts_known": True, "evidence_conflict": False, "process_alive": False, "log_size": irc_log.stat().st_size, "full_normal_termination_count": irc_log.read_text().count("Normal termination of Gaussian"), "full_error_termination_count": 0}
            inspection["evidence_sha256"] = TS._transport_digest(inspection)
            receipt = {"schema": "gaussian-terminal-inspection-receipt/1", "project": "irc_f", "job_id": "1.master", "input_stem": irc_input.stem, "input_sha256": TS.sha256(irc_input), "attempt_id": "qsub-attempt-irc-forward", "terminal_state": "completed", "collected_at": inspection["collected_at"], "inspection_evidence_sha256": inspection["evidence_sha256"], "inspection": inspection, "scientific_acceptance": False}
            receipt["receipt_sha256"] = TS._transport_digest(receipt); receipt_path = root / "terminal-inspection.json"; receipt_path.write_text(json.dumps(receipt))
            artifacts = {}; per_hop = {}
            for source in (irc_log, result_path, checkpoint):
                digest = TS.sha256(source); artifacts[source.name] = {"sha256": digest, "size": source.stat().st_size}; per_hop[source.name] = {"server_sha256": digest, "rtwin_sha256": digest, "mac_sha256": digest, "size": source.stat().st_size}
            snapshot = {"schema": "gaussian-fetch-snapshot/1", "project": "irc_f", "job_id": "1.master", "input_stem": irc_input.stem, "input_sha256": TS.sha256(irc_input), "snapshot_complete": True, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "per_hop_sha256_verified": True, "exact_log": irc_log.name, "artifacts": artifacts, "per_hop": per_hop}
            snapshot["payload_sha256"] = TS._transport_digest(snapshot); snapshot_path = root / "transfer.json"; snapshot_path.write_text(json.dumps(snapshot))
            job["terminal_inspection_receipt_sha256"] = receipt["receipt_sha256"]; job["fetch_snapshot_sha256"] = TS.sha256(snapshot_path); job["fetch_snapshot_size"] = snapshot_path.stat().st_size
            job_path = root / "job.json"; job_path.write_text(json.dumps(job))
            audit = TS.audit_irc_endpoint_provenance(
                irc_input, irc_log, result_path, job_path, checkpoint,
                "forward", "reactant", 2, [(1, 2)],
            )
            self.assertEqual(audit["completed_point"], 2)
            self.assertEqual(audit["reviewed_forming_bond_distances"][0]["distance_angstrom"], 1.5)
            audit_path = root / "endpoint_audit.json"; audit_path.write_text(json.dumps(audit))
            review_draft = {
                "schema": "gaussian-endpoint-structure-review-draft/1",
                "review_id": "synthetic_forward_endpoint_review",
                "direction": "forward", "chemical_side": "reactant",
                "stable_atom_ids": ["atom_c1", "atom_c2"],
                "structure_identity": {
                    "state_id": "synthetic_reactant_state", "identity_label": "reviewed synthetic C2 endpoint",
                    "formula": "C2", "connectivity": [{"atom_ids": ["atom_c1", "atom_c2"], "order": 1.0}],
                    "stereochemistry": [],
                },
                "decision": "accepted", "explicit_human_review": True,
                "reviewer": "synthetic_offline_reviewer",
                "rationale": "Synthetic connectivity and identity were reviewed against the exact endpoint coordinates.",
                "reviewed_at": "2026-07-19T12:00:00+08:00",
            }
            review_draft_path = root / "endpoint_review.draft.json"; review_draft_path.write_text(json.dumps(review_draft))
            review_path = root / "endpoint_review.json"
            family_path = root / "family.json"; family_path.write_text(json.dumps({"schema": TS.SCHEMA_V2, "pilot": False, "project_prefix": "irc"}))
            sources = {"family": family_path, "audit": audit_path, "irc_input": irc_input, "irc_log": irc_log, "irc_result": result_path, "job": job_path, "checkpoint": checkpoint, "terminal_inspection_receipt": receipt_path, "fetch_snapshot": snapshot_path}
            reviewed = TS.build_endpoint_structure_review_artifact(sources, review_draft_path, review_path)
            self.assertEqual(reviewed["schema"], TS.ENDPOINT_REVIEW_SCHEMA_V2)
            self.assertEqual(reviewed["structure_identity"]["formula"], "C2")
            self.assertEqual(reviewed["endpoint_coordinates"]["records"][0]["atom_id"], "atom_c1")
            self.assertEqual(reviewed["parser"], TS.PARSER_ID)
            TS.validate_endpoint_structure_review_artifact(review_path)
            receipt_original = receipt_path.read_bytes(); crossed = json.loads(receipt_path.read_text()); crossed["attempt_id"] = "qsub-attempt-other"; crossed["receipt_sha256"] = TS._transport_digest({key: value for key, value in crossed.items() if key != "receipt_sha256"}); receipt_path.write_text(json.dumps(crossed))
            with self.assertRaisesRegex(ValueError, "exact project/job/attempt/input"):
                TS.build_endpoint_structure_review_artifact(sources, review_draft_path, root / "cross-attempt-review.json")
            receipt_path.write_bytes(receipt_original)
            immutable_review = review_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "concurrent or overwrite"):
                TS.build_endpoint_structure_review_artifact(sources, review_draft_path, review_path)
            self.assertEqual(review_path.read_bytes(), immutable_review)
            stale = json.loads(review_path.read_text()); stale["structure_identity"]["formula"] = "C3"; stale["payload_sha256"] = TS._payload_sha256(stale)
            review_path.write_text(json.dumps(stale))
            with self.assertRaisesRegex(ValueError, "formula differs"):
                TS.validate_endpoint_structure_review_artifact(review_path)
            review_path.write_text(json.dumps(reviewed))
            original_log = irc_log.read_text()
            irc_log.write_text(original_log + " stale mutation\n")
            with self.assertRaisesRegex(ValueError, "reference changed"):
                TS.validate_endpoint_structure_review_artifact(review_path)
            irc_log.write_text(original_log)
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
