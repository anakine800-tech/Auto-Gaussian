#!/usr/bin/env python3
"""Offline baseline checks for version-controlled Gaussian Skills."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[1]
PBS_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
MODULE = PBS_SCRIPTS / "gaussian_rtwin_pbs.py"
sys.path.insert(0, str(PBS_SCRIPTS))
SPEC = importlib.util.spec_from_file_location("gaussian_rtwin_pbs", MODULE)
assert SPEC and SPEC.loader
PBS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PBS)


class RepositoryBaselineTests(unittest.TestCase):
    def test_pbs_q_is_documented_as_normal_waiting_not_failure(self) -> None:
        skill = (ROOT / "skills" / "auto-g16-rtwin-pbs" / "SKILL.md").read_text()
        failures = (
            ROOT
            / "skills"
            / "auto-g16-rtwin-pbs"
            / "references"
            / "environment-and-failures.md"
        ).read_text()
        self.assertIn("Treat PBS `Q`", skill)
        self.assertIn("not a failed launch", skill)
        self.assertIn("`Q` alone does not prove the server is full", skill)
        self.assertIn("Wait without duplicate submission", skill)
        self.assertIn("44-core full-node job", failures)
        self.assertIn("do not submit another copy", failures)
        self.assertIn("Absence of a session, Gaussian process, or log is expected", failures)

    def test_fixed_server_root(self) -> None:
        self.assertEqual(PBS.DEFAULT_REMOTE_ROOT, "/home/user100/SDL")
        self.assertEqual(
            PBS.remote_project_dir("safe_job"), "/home/user100/SDL/safe_job"
        )

    def test_existing_and_empty_directory_guards_are_contained(self) -> None:
        for script in (
            PBS.remote_existing_directory_guard("safe_job"),
            PBS.remote_empty_directory_guard("safe_job"),
        ):
            self.assertIn("/home/user100/SDL", script)
            self.assertIn("realpath", script)
            self.assertNotIn("codex-gaussian", script)
        self.assertIn(
            "REFUSING_OVERWRITE", PBS.remote_empty_directory_guard("safe_job")
        )

    def test_pbs_scratch_is_inside_project(self) -> None:
        script = PBS.pbs_text("safe_job", "safe_job.gjf", 8)
        self.assertIn('scratch="$work_real/scratch"', script)
        self.assertIn('export GAUSS_SCRDIR="$scratch_real"', script)
        self.assertNotIn("/tmp", script)

    def test_oldcheckpoint_is_explicit_hashed_companion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            bundle = root / "bundle"
            source.mkdir()
            checkpoint = source / "reviewed_ts.chk"
            checkpoint.write_bytes(b"reviewed checkpoint")
            input_path = source / "irc_f.gjf"
            input_path.write_text(
                "%oldchk=reviewed_ts.chk\n"
                "%chk=irc_f.chk\n"
                "%mem=12GB\n"
                "%nprocshared=8\n"
                "#p b3lyp/6-31g(d) irc=(rcfc,forward,maxpoints=30) guess=read\n\n"
                "IRC forward\n\n"
                "0 1\n"
                "H 0.0 0.0 0.0\n"
                "H 0.0 0.0 0.7\n\n",
                encoding="utf-8",
            )
            job, files = PBS.stage(input_path, "irc_f", bundle)
            names = {path.name for path in files}
            self.assertEqual(job["gaussian"]["oldcheckpoint"], "reviewed_ts.chk")
            self.assertIn("reviewed_ts.chk", names)
            checksums = (bundle / "checksums.sha256").read_text()
            self.assertIn("reviewed_ts.chk", checksums)

    def test_oldcheckpoint_rejects_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unsafe.gjf"
            path.write_text(
                "%oldchk=../outside.chk\n%chk=new.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p b3lyp/6-31g(d) irc=(rcfc,forward)\n\nTitle\n\n0 1\nH 0 0 0\n\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                PBS.parse_gaussian(path)

    def test_geom_allcheck_is_hash_bound_and_has_audited_atom_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint = root / "reviewed_ts.chk"
            checkpoint.write_bytes(b"reviewed checkpoint")
            input_path = root / "irc_f.gjf"
            input_path.write_text(
                "%oldchk=reviewed_ts.chk\n%chk=irc_f.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p b3lyp/6-31g(d) irc=(rcfc,forward) geom=allcheck guess=read\n\n"
            )
            manifest = {
                "schema": "gaussian-allcheck-input-manifest/1",
                "calculation_ready": True,
                "candidate_only": False,
                "warnings": [],
                "geometry_source": "geom_allcheck_from_reviewed_checkpoint",
                "no_explicit_molecule_specification": True,
                "input_sha256": PBS.sha256(input_path),
                "checkpoint_file": checkpoint.name,
                "checkpoint_sha256": PBS.sha256(checkpoint),
                "charge": 0,
                "multiplicity": 1,
                "atom_count": 2,
                "atom_order": [
                    {"index": 1, "atomic_number": 1, "element": "H"},
                    {"index": 2, "atomic_number": 1, "element": "H"},
                ],
            }
            input_path.with_suffix(".json").write_text(json.dumps(manifest))
            audit = PBS.parse_gaussian(input_path)
            self.assertEqual(audit["geometry_source"], "geom_allcheck_from_reviewed_checkpoint")
            self.assertEqual(audit["oldcheckpoint_sha256"], PBS.sha256(checkpoint))
            self.assertEqual(audit["atom_count"], 2)
            self.assertEqual([item["element"] for item in audit["atom_order"]], ["H", "H"])

    def test_geom_allcheck_rejects_checkpoint_hash_change_and_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint = root / "ts.chk"
            checkpoint.write_bytes(b"original")
            input_path = root / "irc.gjf"
            input_path.write_text(
                "%oldchk=ts.chk\n%chk=irc.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p hf/sto-3g irc=(rcfc,forward) geom=allcheck guess=read\n\n"
            )
            manifest = {
                "schema": "gaussian-allcheck-input-manifest/1",
                "calculation_ready": True,
                "warnings": [],
                "geometry_source": "geom_allcheck_from_reviewed_checkpoint",
                "no_explicit_molecule_specification": True,
                "input_sha256": PBS.sha256(input_path),
                "checkpoint_file": "ts.chk",
                "checkpoint_sha256": PBS.sha256(checkpoint),
                "charge": 0,
                "multiplicity": 1,
                "atom_count": 1,
                "atom_order": [{"index": 1, "atomic_number": 1, "element": "H"}],
            }
            input_path.with_suffix(".json").write_text(json.dumps(manifest))
            checkpoint.write_bytes(b"changed")
            with self.assertRaises(SystemExit):
                PBS.parse_gaussian(input_path)
            checkpoint.write_bytes(b"original")
            input_path.write_text(input_path.read_text() + "0 1\nH 0 0 0\n\n")
            manifest["input_sha256"] = PBS.sha256(input_path)
            input_path.with_suffix(".json").write_text(json.dumps(manifest))
            with self.assertRaises(SystemExit):
                PBS.parse_gaussian(input_path)

    def test_zombie_requires_repeated_stable_evidence(self) -> None:
        observation = {
            "pbs_job_name": "safe_job",
            "pbs_state": "R",
            "pbs_record_present": True,
            "session_id": "1234",
            "process_alive": False,
            "log_size": 100,
            "log_mtime_epoch": 200,
            "workflow_expected_stages": 3,
            "full_normal_termination_count": 3,
            "full_error_termination_count": 0,
            "analysis": {},
        }
        result = PBS.assess_zombie_observations(
            "safe_job", "123.master", [observation, dict(observation)]
        )
        self.assertTrue(result["cleanup_eligible"])
        live = dict(observation, process_alive=True)
        refused = PBS.assess_zombie_observations(
            "safe_job", "123.master", [observation, live]
        )
        self.assertFalse(refused["cleanup_eligible"])

    def test_zombie_cleanup_is_automatic_but_still_evidence_gated(self) -> None:
        parser = PBS.build_parser()
        cleanup_args = parser.parse_args(
            [
                "cleanup-zombie",
                "--project",
                "safe_job",
                "--job-id",
                "123.master",
                "--input-stem",
                "safe_job",
                "--local-dir",
                str(Path(tempfile.gettempdir()).resolve() / "safe_job"),
            ]
        )
        self.assertFalse(cleanup_args.confirmed)
        diagnosis = {
            "schema": "pbs-zombie-diagnosis/1",
            "project": "safe_job",
            "job_id": "123.master",
            "classification": "confirmed_scheduler_zombie",
            "cleanup_eligible": True,
            "observations": [{"pbs_record_present": True}] * 2,
        }
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        purged = SimpleNamespace(
            returncode=153, stdout="", stderr="qstat: Unknown Job Id"
        )
        with (
            mock.patch.object(PBS, "diagnose_zombie", return_value=diagnosis),
            mock.patch.object(
                PBS, "nested_ssh", side_effect=lambda _args, *command: list(command)
            ),
            mock.patch.object(PBS, "run", side_effect=[completed, purged]) as run,
            mock.patch.object(PBS.time, "sleep"),
            mock.patch.object(PBS, "update_job"),
        ):
            cleanup = PBS.cleanup_zombie_record(cleanup_args)
        self.assertEqual(cleanup["status"], "cleared")
        self.assertTrue(cleanup["qdel_issued"])
        self.assertEqual(sum("qdel" in call.args[0] for call in run.call_args_list), 1)

        refused_diagnosis = dict(
            diagnosis,
            classification="not_confirmed_zombie",
            cleanup_eligible=False,
        )
        with (
            mock.patch.object(PBS, "diagnose_zombie", return_value=refused_diagnosis),
            mock.patch.object(PBS, "run") as run,
            mock.patch.object(PBS, "update_job"),
        ):
            refused_cleanup = PBS.cleanup_zombie_record(cleanup_args)
        self.assertEqual(refused_cleanup["status"], "not_eligible")
        self.assertFalse(refused_cleanup["qdel_issued"])
        self.assertTrue(refused_cleanup["scheduler_record_present"])
        self.assertEqual(
            refused_cleanup["scheduler_record_evidence_status"], "present"
        )
        run.assert_not_called()

        cancel_args = parser.parse_args(["cancel", "--job-id", "123.master"])
        with (
            self.assertRaises(SystemExit),
            mock.patch.object(PBS, "run") as cancel_run,
        ):
            PBS.command_cancel(cancel_args)
        cancel_run.assert_not_called()

    def test_watch_fetch_defaults_to_automatic_zombie_cleanup(self) -> None:
        parser = PBS.build_parser()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            local_dir = root / "bundle"
            output_dir = root / "results"
            local_dir.mkdir()
            (local_dir / "job.json").write_text("{}")
            args = parser.parse_args(
                [
                    "watch",
                    "--project",
                    "safe_job",
                    "--job-id",
                    "123.master",
                    "--input-stem",
                    "safe_job",
                    "--local-dir",
                    str(local_dir),
                    "--output-dir",
                    str(output_dir),
                    "--fetch",
                ]
            )
            self.assertTrue(args.auto_cleanup_zombie)
            final = {
                "state": "completed",
                "pbs_state": "R",
                "log_size": 100,
                "log_mtime_epoch": 200,
                "scheduler_zombie_candidate": True,
                "analysis": {},
            }
            cleanup = {
                "schema": "pbs-zombie-cleanup/1",
                "status": "cleared",
                "qdel_issued": True,
            }
            with (
                mock.patch.object(PBS, "inspect_job", return_value=final),
                mock.patch.object(
                    PBS,
                    "fetch_results",
                    return_value={"analysis": {}, "snapshot_complete": True},
                ),
                mock.patch.object(PBS, "update_job") as update,
                mock.patch.object(
                    PBS, "cleanup_zombie_record", return_value=cleanup
                ) as automatic_cleanup,
            ):
                PBS.command_watch(args)
            automatic_cleanup.assert_called_once()
            completion_updates = [
                call for call in update.call_args_list if "results_fetched" in call.kwargs
            ]
            self.assertEqual(len(completion_updates), 1)
            self.assertTrue(completion_updates[0].kwargs["results_fetched"])
            self.assertEqual(
                completion_updates[0].kwargs["fetch_snapshot"],
                str(output_dir / "transfer.json"),
            )
            self.assertEqual(
                completion_updates[0].kwargs["result_file"],
                str(output_dir / "result.json"),
            )
            called_args = automatic_cleanup.call_args.args[0]
            self.assertEqual(called_args.stability_seconds, 10)
            self.assertEqual(called_args.verify_seconds, 5)

            disabled = parser.parse_args(
                [
                    "watch",
                    "--project",
                    "safe_job",
                    "--job-id",
                    "123.master",
                    "--input-stem",
                    "safe_job",
                    "--local-dir",
                    str(local_dir),
                    "--output-dir",
                    str(output_dir),
                    "--fetch",
                    "--no-auto-cleanup-zombie",
                ]
            )
            self.assertFalse(disabled.auto_cleanup_zombie)

    def test_live_freq_stage_is_not_completed_from_opt_marker(self) -> None:
        analysis = {
            "normal_termination": True,
            "error_termination": False,
            "scf_calculations": 1,
            "final_coordinate_count": 1,
            "normal_termination_count": 1,
            "error_termination_count": 0,
        }
        state, _, _, _ = PBS.classify_inspection_state(
            workflow_manifest=None,
            full_normal_count=1,
            full_error_count=0,
            analysis=analysis,
            qstate="R",
            process_alive=True,
        )
        self.assertEqual(state, "running")

    def test_opt_freq_sp_fixture_is_sanitized_and_complete(self) -> None:
        manifest = json.loads(
            (ROOT / "tests" / "fixtures" / "opt_freq_sp_success.json").read_text()
        )
        self.assertEqual(manifest["schema"], "gaussian-opt-freq-sp/1")
        self.assertEqual(manifest["expected_stage_count"], 3)
        self.assertEqual(manifest["chemical_identity"]["formula"], "H2O")

    def test_irc_corrector_failure_has_specific_diagnostic(self) -> None:
        text = (ROOT / "tests" / "fixtures" / "irc_corrector_failure.log").read_text()
        result = PBS.analyze_log_text(text)
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "irc_corrector_convergence",
            {item["code"] for item in result["diagnostics"]},
        )

    def test_da_fragment_endpoint_fixture_is_sanitized_and_compact(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "da_fragment_endpoint"
        case = json.loads((fixture / "case.json").read_text())
        self.assertEqual(case["schema"], "gaussian-ts-irc-regression-case/1")
        self.assertTrue(case["sanitized"])
        self.assertFalse(case["contains_gaussian_log"])
        self.assertFalse(case["contains_checkpoint"])
        self.assertEqual(
            [item["formula"] for item in case["expected_components"]],
            ["C4H6", "C2H4"],
        )
        self.assertFalse(any(path.suffix.lower() in {".log", ".chk"} for path in fixture.iterdir()))

    def test_da_fragment_live_smoke_evidence_is_sanitized_and_passed(self) -> None:
        path = (
            ROOT
            / "tests"
            / "fixtures"
            / "da_fragment_endpoint"
            / "live_smoke_evidence.json"
        )
        evidence = json.loads(path.read_text())
        self.assertEqual(
            evidence["schema"], "gaussian-ts-irc-live-smoke-evidence/1"
        )
        self.assertTrue(evidence["sanitized"])
        for forbidden_flag in (
            "contains_job_ids",
            "contains_server_paths",
            "contains_gaussian_log",
            "contains_checkpoint",
        ):
            self.assertFalse(evidence[forbidden_flag])
        self.assertEqual(evidence["validation_status"], "passed")
        self.assertEqual(evidence["installed_gaussian_revision"], "Gaussian 16 Revision A.03")
        self.assertEqual(evidence["resources"]["memory"], "50GB")
        self.assertEqual(evidence["resources"]["nprocshared"], 22)
        self.assertEqual(
            [fragment["formula"] for fragment in evidence["fragments"]],
            ["C4H6", "C2H4"],
        )
        for fragment in evidence["fragments"]:
            self.assertEqual(fragment["imaginary_frequency_count"], 0)
            self.assertTrue(fragment["minimum_accepted"])
            self.assertRegex(fragment["input_sha256"], re.compile(r"^[0-9a-f]{64}$"))
            self.assertRegex(
                fragment["parsed_result_sha256"], re.compile(r"^[0-9a-f]{64}$")
            )
        serialized = path.read_text()
        self.assertNotIn("/home/", serialized)
        self.assertNotIn(".master", serialized)

    def test_auto_zombie_cleanup_live_smoke_is_sanitized_and_passed(self) -> None:
        path = ROOT / "tests" / "fixtures" / "auto_zombie_cleanup_live_smoke.json"
        evidence = json.loads(path.read_text())
        self.assertEqual(evidence["schema"], "pbs-auto-zombie-cleanup-live-smoke/1")
        self.assertTrue(evidence["sanitized"])
        for forbidden_flag in (
            "contains_job_id",
            "contains_server_path",
            "contains_gaussian_log",
            "contains_checkpoint",
        ):
            self.assertFalse(evidence[forbidden_flag])
        self.assertEqual(evidence["calculation"]["status"], "completed")
        cleanup = evidence["automatic_scheduler_cleanup"]
        self.assertEqual(cleanup["classification"], "confirmed_scheduler_zombie")
        self.assertEqual(cleanup["observation_count"], 2)
        self.assertTrue(cleanup["all_eligibility_checks_passed"])
        self.assertFalse(cleanup["confirmation_required_for_qdel"])
        self.assertEqual(cleanup["qdel_issued_count"], 1)
        self.assertEqual(cleanup["qdel_returncode"], 0)
        self.assertFalse(cleanup["scheduler_record_present_after_verification"])
        self.assertFalse(cleanup["server_project_files_changed"])
        self.assertFalse(cleanup["automatic_retry_performed"])
        serialized = path.read_text()
        self.assertNotIn("/home/", serialized)
        self.assertNotIn(".master", serialized)

    def test_ts_skill_documents_disconnected_endpoint_gates(self) -> None:
        text = (ROOT / "skills" / "auto-g16-ts-irc" / "SKILL.md").read_text()
        for command in (
            "propose-endpoint-components",
            "build-fragment-endpoints",
            "audit-fragment-endpoints",
        ):
            self.assertIn(command, text)
        self.assertIn("50 GB/22 cores", text)


if __name__ == "__main__":
    unittest.main()
