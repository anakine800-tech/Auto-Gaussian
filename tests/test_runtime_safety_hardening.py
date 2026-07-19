#!/usr/bin/env python3
"""Adversarial offline tests for PBS evidence and immutable result fetching."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
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
SPEC = importlib.util.spec_from_file_location("runtime_safety_gaussian_rtwin_pbs", MODULE)
assert SPEC and SPEC.loader
PBS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PBS)


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class RuntimeSafetyHardeningTests(unittest.TestCase):
    def test_qstat_and_ps_errors_are_unknown_not_absent(self) -> None:
        qstat = PBS.classify_qstat_evidence(
            completed(255, stderr="ssh: connection reset")
        )
        process = PBS.classify_process_evidence(
            completed(255, stderr="ssh: connection reset")
        )
        malformed = PBS.classify_qstat_evidence(completed(0, stdout="partial output"))
        absent = PBS.classify_qstat_evidence(
            completed(153, stderr="qstat: Unknown Job Id 123.master")
        )
        transport_with_stale_text = PBS.classify_qstat_evidence(
            completed(255, stderr="qstat: Unknown Job Id; ssh: connection reset")
        )
        self.assertEqual(qstat["status"], "unknown")
        self.assertIsNone(qstat["record_present"])
        self.assertEqual(process["status"], "unknown")
        self.assertIsNone(process["process_alive"])
        self.assertEqual(malformed["status"], "unknown")
        self.assertEqual(absent["status"], "absent")
        self.assertFalse(absent["record_present"])
        self.assertEqual(transport_with_stale_text["status"], "unknown")

        analysis = {
            "normal_termination": False,
            "error_termination": False,
            "scf_calculations": 1,
            "final_coordinate_count": 0,
            "normal_termination_count": 0,
            "error_termination_count": 0,
        }
        state, *_ = PBS.classify_inspection_state(
            workflow_manifest=None,
            full_normal_count=0,
            full_error_count=0,
            analysis=analysis,
            qstate=None,
            process_alive=None,
            pbs_evidence_status="unknown",
        )
        self.assertEqual(state, "unknown")

    def test_ps_rc_255_cannot_prove_stale_zombie_or_interrupted(self) -> None:
        args = SimpleNamespace(local_dir=None)
        qstat_text = (
            "Job Id: 123.master\n"
            "    Job_Name = safe_job\n"
            "    job_state = R\n"
            "    session_id = 456\n"
        )

        def fake_run(command, *, input_bytes=None, check=True):
            if "qstat" in command:
                return completed(0, qstat_text)
            if "ps" in command:
                return completed(255, stderr="ssh transport failed")
            if "cat" in command:
                return completed(1, stderr="No such file")
            if "tail" in command:
                return completed(0, stdout=" SCF Done: E(RHF) = -1.0\n")
            if "stat" in command:
                return completed(0, stdout="100:200\n")
            if input_bytes and b"normal=$(grep" in input_bytes:
                return completed(0, stdout="0:0\n")
            return completed(0)

        with (
            mock.patch.object(PBS, "nested_ssh", side_effect=lambda _args, *cmd: list(cmd)),
            mock.patch.object(PBS, "run", side_effect=fake_run),
        ):
            inspection = PBS.inspect_job(args, "safe_job", "safe_job", "123.master")
        self.assertEqual(inspection["process_evidence_status"], "unknown")
        self.assertIsNone(inspection["process_alive"])
        self.assertEqual(inspection["state"], "unknown")
        self.assertFalse(inspection["scheduler_zombie_candidate"])

    def test_zombie_assessment_does_not_turn_unknown_pbs_into_self_purged(self) -> None:
        observation = {
            "pbs_job_name": None,
            "pbs_state": None,
            "pbs_record_present": None,
            "pbs_evidence_status": "unknown",
            "session_id": None,
            "process_alive": None,
            "process_evidence_status": "unknown",
            "log_size": 100,
            "log_mtime_epoch": 200,
            "analysis": {"normal_termination": True},
        }
        diagnosis = PBS.assess_zombie_observations(
            "safe_job", "123.master", [observation, dict(observation)]
        )
        self.assertEqual(diagnosis["classification"], "not_confirmed_zombie")
        self.assertFalse(diagnosis["cleanup_eligible"])
        self.assertIn("pbs_evidence_present", diagnosis["failed_checks"])

    def test_qdel_failure_and_qstat_transport_failure_are_unverified(self) -> None:
        parser = PBS.build_parser()
        args = parser.parse_args(
            [
                "cleanup-zombie", "--project", "safe_job", "--job-id", "123.master",
                "--input-stem", "safe_job", "--local-dir",
                str(Path(tempfile.gettempdir()).resolve() / "safe_job"),
            ]
        )
        diagnosis = {
            "schema": "pbs-zombie-diagnosis/1",
            "project": "safe_job",
            "job_id": "123.master",
            "classification": "confirmed_scheduler_zombie",
            "cleanup_eligible": True,
            "observations": [{"pbs_record_present": True}] * 2,
        }
        with (
            mock.patch.object(PBS, "diagnose_zombie", return_value=diagnosis),
            mock.patch.object(PBS, "nested_ssh", side_effect=lambda _args, *cmd: list(cmd)),
            mock.patch.object(
                PBS,
                "run",
                side_effect=[
                    completed(255, stderr="qdel transport failed"),
                    completed(255, stderr="qstat transport failed"),
                ],
            ) as run,
            mock.patch.object(PBS.time, "sleep"),
            mock.patch.object(PBS, "update_job"),
        ):
            cleanup = PBS.cleanup_zombie_record(args)
        self.assertEqual(cleanup["status"], "cleanup_unverified")
        self.assertEqual(cleanup["qdel_outcome"], "failed")
        self.assertEqual(cleanup["verification_outcome"], "unknown")
        self.assertIsNone(cleanup["scheduler_record_present"])
        self.assertEqual(sum("qdel" in call.args[0] for call in run.call_args_list), 1)

        with (
            mock.patch.object(PBS, "diagnose_zombie", return_value=diagnosis),
            mock.patch.object(PBS, "nested_ssh", side_effect=lambda _args, *cmd: list(cmd)),
            mock.patch.object(
                PBS,
                "run",
                side_effect=[completed(0), completed(255, stderr="qstat transport failed")],
            ),
            mock.patch.object(PBS.time, "sleep"),
            mock.patch.object(PBS, "update_job"),
        ):
            unverifiable_after_success = PBS.cleanup_zombie_record(args)
        self.assertEqual(unverifiable_after_success["status"], "cleanup_unverified")
        self.assertEqual(unverifiable_after_success["qdel_outcome"], "success")
        self.assertEqual(unverifiable_after_success["verification_outcome"], "unknown")

    def test_not_eligible_cleanup_preserves_unknown_scheduler_evidence(self) -> None:
        parser = PBS.build_parser()
        args = parser.parse_args(
            [
                "cleanup-zombie", "--project", "safe_job", "--job-id", "123.master",
                "--input-stem", "safe_job", "--local-dir",
                str(Path(tempfile.gettempdir()).resolve() / "safe_job"),
            ]
        )
        diagnosis = {
            "schema": "pbs-zombie-diagnosis/1",
            "project": "safe_job",
            "job_id": "123.master",
            "classification": "not_confirmed_zombie",
            "cleanup_eligible": False,
            "observations": [
                {
                    "pbs_record_present": None,
                    "pbs_evidence_status": "unknown",
                }
            ],
        }
        with (
            mock.patch.object(PBS, "diagnose_zombie", return_value=diagnosis),
            mock.patch.object(PBS, "update_job"),
            mock.patch.object(PBS, "run") as run,
        ):
            cleanup = PBS.cleanup_zombie_record(args)
        self.assertEqual(cleanup["status"], "not_eligible")
        self.assertIsNone(cleanup["scheduler_record_present"])
        self.assertEqual(cleanup["scheduler_record_evidence_status"], "unknown")
        run.assert_not_called()

    def make_fetch_case(self, root: Path) -> tuple[SimpleNamespace, Path, dict[str, bytes]]:
        local_dir = root / "bundle"
        local_dir.mkdir()
        ssh_config = root / "ssh_config"
        ssh_config.write_text("Host rtwin\n", encoding="utf-8")
        files = {
            "safe_job.gjf": b"reviewed input\n",
            "safe_job.pbs": b"reviewed pbs\n",
            "checksums.sha256": b"",
            "safe_job.log": b"Normal termination of Gaussian 16\n",
        }
        for name in ("safe_job.gjf", "safe_job.pbs"):
            (local_dir / name).write_bytes(files[name])
        checksums = "".join(
            f"{PBS.sha256(local_dir / name)}  {name}\n"
            for name in ("safe_job.gjf", "safe_job.pbs")
        )
        (local_dir / "checksums.sha256").write_text(checksums, encoding="utf-8")
        files["checksums.sha256"] = checksums.encode("utf-8")
        job = {
            "schema": "gaussian-rtwin-pbs/1",
            "project": "safe_job",
            "job_id": "123.master",
            "status": "completed",
            "input": "safe_job.gjf",
            "input_sha256": PBS.sha256(local_dir / "safe_job.gjf"),
            "pbs_script": "safe_job.pbs",
            "checksums": "checksums.sha256",
            "remote_workdir": "/home/user100/SDL/safe_job",
            "gaussian": {},
        }
        (local_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        args = SimpleNamespace(
            project="safe_job",
            job_id="123.master",
            input_stem="safe_job",
            local_dir=str(local_dir),
            mac_ssh_config=str(ssh_config),
            rtwin_alias="rtwin",
            windows_root=r"C:\GaussianProjects",
            windows_server_config=r".ssh\gaussian_server_config",
            server_alias="gaussian-server",
        )
        return args, local_dir, files

    def inventory_text(self, files: dict[str, bytes], *, missing_log: bool = False) -> str:
        lines = []
        for name in sorted(files):
            if name == "safe_job.log" and missing_log:
                lines.append("MISSING_REQUIRED\tsafe_job.log")
            else:
                digest = __import__("hashlib").sha256(files[name]).hexdigest()
                lines.append(f"FILE\t{name}\t{digest}\t{len(files[name])}")
        lines.append("MISSING_OPTIONAL\tsafe_job.pbs.out")
        return "\n".join(lines) + "\n"

    def rtwin_hash_text(self, files: dict[str, bytes], *, mismatch: bool = False) -> str:
        lines = []
        for name in sorted(files):
            digest = __import__("hashlib").sha256(files[name]).hexdigest()
            if mismatch and name == "safe_job.log":
                digest = "0" * 64
            lines.append(f"{name}\t{digest}\t{len(files[name])}")
        return "\n".join(lines) + "\n"

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_fetch_rejects_output_symlink_and_symlink_ancestor_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args, _, _ = self.make_fetch_case(root)
            real_output = root / "real-output"
            real_output.mkdir()
            leaf_link = root / "snapshot-link"
            leaf_link.symlink_to(real_output, target_is_directory=True)
            with mock.patch.object(PBS, "run") as run:
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", leaf_link)
            run.assert_not_called()
            self.assertEqual(list(real_output.iterdir()), [])

            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            nested_snapshot = linked_parent / "nested-snapshot"
            with mock.patch.object(PBS, "run") as run:
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", nested_snapshot)
            run.assert_not_called()
            self.assertFalse((real_parent / "nested-snapshot").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_fetch_rejects_local_dir_symlink_before_snapshot_or_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args, local_dir, _ = self.make_fetch_case(root)
            local_link = root / "bundle-link"
            local_link.symlink_to(local_dir, target_is_directory=True)
            args.local_dir = str(local_link)
            output = root / "must-not-exist"
            with mock.patch.object(PBS, "run") as run:
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", output)
            run.assert_not_called()
            self.assertFalse(output.exists())

    def test_fetch_commands_write_results_only_for_complete_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            local_dir = root / "bundle"
            local_dir.mkdir()
            output = root / "snapshot"
            args = SimpleNamespace(
                project="safe_job",
                output_dir=str(output),
                local_dir=str(local_dir),
            )
            with (
                mock.patch.object(
                    PBS,
                    "fetch_results",
                    return_value={"snapshot_complete": False, "analysis": None},
                ),
                mock.patch.object(PBS, "update_job") as update,
            ):
                PBS.command_fetch(args)
            update.assert_not_called()

            with (
                mock.patch.object(
                    PBS,
                    "fetch_results",
                    return_value={"snapshot_complete": True, "analysis": {}},
                ),
                mock.patch.object(PBS, "update_job") as update,
            ):
                PBS.command_fetch(args)
            update.assert_called_once()
            self.assertTrue(update.call_args.kwargs["results_fetched"])
            self.assertEqual(
                update.call_args.kwargs["fetch_snapshot"],
                str(output / "transfer.json"),
            )

    def test_watch_does_not_record_or_cleanup_incomplete_snapshot(self) -> None:
        parser = PBS.build_parser()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            local_dir = root / "bundle"
            output_dir = root / "results"
            local_dir.mkdir()
            (local_dir / "job.json").write_text("{}", encoding="utf-8")
            args = parser.parse_args(
                [
                    "watch", "--project", "safe_job", "--job-id", "123.master",
                    "--input-stem", "safe_job", "--local-dir", str(local_dir),
                    "--output-dir", str(output_dir), "--fetch",
                ]
            )
            final = {
                "state": "completed",
                "pbs_state": "R",
                "log_size": 100,
                "log_mtime_epoch": 200,
                "scheduler_zombie_candidate": True,
                "analysis": {},
            }
            with (
                mock.patch.object(PBS, "inspect_job", return_value=final),
                mock.patch.object(
                    PBS,
                    "fetch_results",
                    return_value={"snapshot_complete": False, "analysis": None},
                ),
                mock.patch.object(PBS, "update_job") as update,
                mock.patch.object(PBS, "cleanup_zombie_record") as cleanup,
            ):
                PBS.command_watch(args)
            completion_updates = [
                call for call in update.call_args_list if "results_fetched" in call.kwargs
            ]
            self.assertEqual(len(completion_updates), 1)
            self.assertFalse(completion_updates[0].kwargs["results_fetched"])
            self.assertIsNone(completion_updates[0].kwargs["fetch_snapshot"])
            self.assertIsNone(completion_updates[0].kwargs["result_file"])
            cleanup.assert_not_called()

    def test_fetch_snapshot_selects_exact_log_and_verifies_both_hops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args, _, files = self.make_fetch_case(root)
            output = root / "snapshot"

            def fake_run(command, *, input_bytes=None, check=True):
                call = fake_run.calls
                fake_run.calls += 1
                if call == 0:
                    return completed(0, self.inventory_text(files))
                if call == 1:
                    encoded = command[-1]
                    script = base64.b64decode(encoded).decode("utf-16le")
                    self.assertIn("REFUSING_EXISTING_FETCH_SNAPSHOT", script)
                    self.assertNotIn("-Force", script)
                    return completed()
                if call == 2:
                    self.assertFalse(any("*" in part for part in command))
                    self.assertFalse(any("scratch" in part for part in command))
                    return completed()
                if call == 3:
                    return completed(0, self.rtwin_hash_text(files))
                if call == 4:
                    for name, data in files.items():
                        (output / name).write_bytes(data)
                    return completed()
                raise AssertionError(f"unexpected command: {command}")

            fake_run.calls = 0
            with (
                mock.patch.object(PBS, "run", side_effect=fake_run),
                mock.patch.object(
                    PBS, "analyze_log_file", return_value={"status": "completed"}
                ) as analyze,
            ):
                transfer = PBS.fetch_results(args, "safe_job", output)
            resolved_output = output.resolve()
            analyze.assert_called_once_with(resolved_output / "safe_job.log", resolved_output)
            self.assertEqual(transfer["schema"], "gaussian-fetch-snapshot/1")
            self.assertTrue(transfer["snapshot_complete"])
            self.assertTrue(transfer["per_hop_sha256_verified"])
            self.assertEqual(transfer["exact_log"], "safe_job.log")
            self.assertFalse((output / ".fetch-in-progress").exists())
            allowlist = json.loads((output / "server-allowlist.json").read_text())
            self.assertFalse(allowlist["scratch_included"])
            self.assertFalse(allowlist["unrelated_files_included"])

    def test_fetch_rejects_old_target_multiple_logs_and_missing_required_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args, _, files = self.make_fetch_case(root)
            old = root / "old"
            old.mkdir()
            (old / "old.log").write_text("stale", encoding="utf-8")
            with mock.patch.object(PBS, "run") as run:
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", old)
            run.assert_not_called()

            missing = root / "missing"
            with mock.patch.object(
                PBS, "run", return_value=completed(0, self.inventory_text(files, missing_log=True))
            ):
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", missing)
            self.assertTrue((missing / ".fetch-in-progress").is_file())

            multiple = root / "multiple"

            def fake_run(command, *, input_bytes=None, check=True):
                call = fake_run.calls
                fake_run.calls += 1
                if call == 0:
                    return completed(0, self.inventory_text(files))
                if call in {1, 2}:
                    return completed()
                if call == 3:
                    return completed(0, self.rtwin_hash_text(files))
                for name, data in files.items():
                    (multiple / name).write_bytes(data)
                (multiple / "old.log").write_text("stale", encoding="utf-8")
                return completed()

            fake_run.calls = 0
            with mock.patch.object(PBS, "run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", multiple)

    def test_fetch_hash_mismatch_and_partial_transfer_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args, _, files = self.make_fetch_case(root)
            mismatch = root / "mismatch"
            with mock.patch.object(
                PBS,
                "run",
                side_effect=[
                    completed(0, self.inventory_text(files)), completed(), completed(),
                    completed(0, self.rtwin_hash_text(files, mismatch=True)),
                ],
            ):
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", mismatch)
            self.assertTrue((mismatch / ".fetch-in-progress").is_file())

            partial = root / "partial"

            def fake_run(command, *, input_bytes=None, check=True):
                call = fake_run.calls
                fake_run.calls += 1
                if call == 0:
                    return completed(0, self.inventory_text(files))
                if call in {1, 2}:
                    return completed()
                if call == 3:
                    return completed(0, self.rtwin_hash_text(files))
                (partial / "safe_job.log").write_bytes(files["safe_job.log"])
                raise SystemExit(2)

            fake_run.calls = 0
            with mock.patch.object(PBS, "run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", partial)
            self.assertTrue((partial / ".fetch-in-progress").is_file())
            with mock.patch.object(PBS, "run") as retry_run:
                with self.assertRaises(SystemExit):
                    PBS.fetch_results(args, "safe_job", partial)
            retry_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
