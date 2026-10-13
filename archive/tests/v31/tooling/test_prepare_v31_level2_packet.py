"""Offline candidate packets must never become live or human authority."""

from __future__ import annotations

import base64
from contextlib import ExitStack
import copy
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_v31_level2_packet as packet
from tests.v3.execution import test_v31_lane_a as fixtures

MAIN = "065d016830240962c0aeb22873d3c82aa2f016d3"


def request(kind="xtb"):
    profile = fixtures.LaneAFixture.profile(object())
    encoded_profile = {field.name: getattr(profile, field.name) for field in fields(profile)}
    encoded_profile["jump_topology"] = [list(hop) for hop in profile.jump_topology]
    encoded_profile["config_files"] = [{"logical_name": name, "content_base64": base64.b64encode(raw).decode()} for name, raw in profile.config_files]
    encoded_profile["runtime_contents"] = {name: base64.b64encode(raw).decode() for name, raw in profile.runtime_contents.items()}
    data = fixtures.LaneAFixture.xtb_data() if kind == "xtb" else fixtures.LaneAFixture.crest_data()
    raw = fixtures.XYZ
    return {"schema": packet.SCHEMA, "main_sha": MAIN,
            "request_id": "72b5f4d8-f215-4af4-81f0-58a9d5b06210",
            "project": {"project_id": "project-1", "remote_project_dir": "/home/user100/SDL/project-1"},
            "workflow": {"workflow_run_id": "workflow-1", "workflow_name": "qualification", "project_id": "project-1"},
            "batch_purpose": "fresh isolated Level-2 candidate", "program_kind": kind, "program_data": data,
            "plan_intent": {"program_kind": kind, "program_data": copy.deepcopy(data), "input_sha256": sha256(raw).hexdigest()},
            "displayed_scientific_meaning": {"structure": "synthetic H2", "charge": 0, "multiplicity": 1},
            "resources": {"cores": 8, "memory_mb": 12288, "walltime_seconds": 3600, "queue": "batch"},
            "input": {"portable_name": "input.xyz", "content_base64": base64.b64encode(raw).decode(), "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)},
            "server_profile": encoded_profile,
            "program_identities": {key: {"absolute_path": profile.platform_paths[f"{key}_executable_path"],
                                          "sha256": sha256(profile.runtime_contents[key]).hexdigest(),
                                          "size_bytes": len(profile.runtime_contents[key]),
                                          "version": "3.0.2" if key == "crest" else "6.7.1"} for key in ("xtb", "crest")}}


class Level2PacketTests(unittest.TestCase):
    def build(self, value=None):
        return packet.build_packet(request() if value is None else value, expected_main_sha=MAIN)

    def test_deterministic_packet_and_candidate_lineage(self):
        value = request()
        before = copy.deepcopy(value)
        first = self.build(value)
        self.assertEqual(first, self.build(value))
        self.assertEqual(value, before)
        records = first["candidate_records"]
        self.assertEqual(records["task"]["task_id"], records["attempt"]["task_id"])
        self.assertEqual(records["plan"]["task_id"], records["task"]["task_id"])
        self.assertEqual(records["batch"]["batch_id"], records["task"]["batch_id"])
        digest = first.pop("packet_sha256")
        self.assertEqual(digest, sha256(packet.encode(first)).hexdigest())
        value["input"]["portable_name"] = "changed.xyz"
        self.assertEqual(first["input"]["portable_name"], "input.xyz")

    def test_fresh_request_or_changed_bytes_change_candidate_ids(self):
        first = self.build()["candidate_records"]["attempt"]["attempt_id"]
        value = request()
        value["request_id"] = "adafb089-eaed-44f3-bfc3-fb1b6cba8831"
        self.assertNotEqual(first, self.build(value)["candidate_records"]["attempt"]["attempt_id"])
        value = request()
        value["resources"]["cores"] = 4
        self.assertNotEqual(first, self.build(value)["candidate_records"]["attempt"]["attempt_id"])

    def test_both_adapters_render_without_live_or_approval_factories(self):
        forbidden = ["subprocess.Popen", "socket.socket", "os.system",
                     "auto_g16.approval.ScientificApproval.for_plan",
                     "auto_g16.approval.BatchSubmitApproval.for_existing_attempts",
                     "auto_g16.approval.ExactOperationalConfirmation.for_snapshot",
                     "auto_g16.execution.program._ProgramExecutionSnapshotService.prepare",
                     "auto_g16.execution.project_provisioning._ProjectProvisioningService._attest_current",
                     "auto_g16.execution.execute_once"]
        with ExitStack() as stack:
            for name in forbidden:
                stack.enter_context(patch(name, side_effect=AssertionError(f"forbidden call: {name}")))
            for kind in ("xtb", "crest"):
                with self.subTest(kind=kind):
                    result = self.build(request(kind))
                    self.assertEqual(result["program_execution_spec_candidate"]["program_kind"], kind)
                    self.assertEqual(len(result["scheduler_artifact_candidates"]), 1)
                    self.assertFalse(result["live_authorized"])
                    self.assertFalse(result["execution_ready"])
                    self.assertEqual(result["status"], "BLOCKED_ON_LIVE_PREREQUISITES")
                    self.assertIsNone(result["program_execution_snapshot"]["value"])
                    for candidate in result["approval_candidates"].values():
                        self.assertIsNone(candidate["decision"])

    def test_missing_production_prerequisites_produce_truthful_partial_packet(self):
        value = request()
        value["server_profile"] = None
        value["program_identities"] = {"xtb": None, "crest": None}
        result = self.build(value)
        self.assertIsNone(result["qsub_preview"])
        self.assertIsNone(result["program_execution_spec_candidate"])
        self.assertIn("MISSING_PRODUCTION_SERVER_PROFILE", result["blockers"])
        self.assertIn("MISSING_XTB_IDENTITY", result["blockers"])
        self.assertNotEqual(result["status"], "READY_FOR_OWNER_LIVE_GATE")

    def test_qsub_resources_and_pbs_are_source_renderer_previews(self):
        result = self.build()
        preview = result["qsub_preview"]
        self.assertEqual(preview["argv_tail"], ["-d", preview["cwd"], "-l", "nodes=1:ppn=8,mem=12288mb,walltime=3600", "-q", "batch", "xtb.pbs"])
        self.assertIsNone(preview["executable"])
        pbs = result["scheduler_artifact_candidates"][0]
        self.assertEqual(sha256(pbs["content_utf8"].encode()).hexdigest(), pbs["sha256"])
        self.assertIn("export XTBPATH=", pbs["content_utf8"])

    def test_exact_qsub_argv_uses_closed_supplied_manifest_and_torque_descriptor(self):
        from auto_g16.transport import _bridge, _driver
        from auto_g16.transport._canonical import canonical_json_bytes

        value = request()
        roots = {}
        for name in ("mac_ssh", "server_remote_shell", "server_python", "server_qsub", "server_qstat"):
            platform, mode, required, grammars = _driver._ROOT_RULES[name]
            path, size, digest = _driver._TORQUE_EXECUTABLES.get(name, (f"/synthetic/{name}", 1, "1" * 64))
            roots[name] = {"attestation_mode": mode, "deployment_identity": "synthetic-only",
                           "expected_sha256": digest if required else None,
                           "expected_size_bytes": size if required else None, "path": path,
                           "platform": platform, "shell_grammar": None if required else sorted(grammars)[0]}
        manifest = {"bootstrap_protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL,
                    "deployment_id": "synthetic-only", "schema": "auto-g16-v3-transport-deployment-manifest/3", "trust_roots": roots}
        descriptor = {"schema": _driver._RESOURCE_DESCRIPTOR_SCHEMA, "dialect": _driver._TORQUE_RESOURCE_DIALECT}
        contents = value["server_profile"]["runtime_contents"]
        contents["transport-deployment-manifest-v3.json"] = base64.b64encode(canonical_json_bytes(manifest)).decode()
        contents[_driver._RESOURCE_DESCRIPTOR_NAME] = base64.b64encode(canonical_json_bytes(descriptor)).decode()
        result = self.build(value)
        self.assertEqual(result["qsub_preview"]["argv"][0], _driver._TORQUE_EXECUTABLES["server_qsub"][0])
        self.assertEqual(result["qsub_preview"]["argv"][1:], result["qsub_preview"]["argv_tail"])
        self.assertFalse(result["execution_ready"])
        for missing_name, blocker in (
            ("transport-deployment-manifest-v3.json", "MISSING_SUCCESSOR_DEPLOYMENT_MANIFEST"),
            (_driver._RESOURCE_DESCRIPTOR_NAME, "MISSING_RESOURCE_DESCRIPTOR"),
        ):
            for selected_identity_present in (True, False):
                partial = copy.deepcopy(value)
                del partial["server_profile"]["runtime_contents"][missing_name]
                if not selected_identity_present:
                    partial["program_identities"]["xtb"] = None
                partial_result = self.build(partial)
                self.assertIn(blocker, partial_result["blockers"])
                self.assertEqual(partial_result["status"], "BLOCKED_ON_LIVE_PREREQUISITES")
                if selected_identity_present:
                    self.assertNotIn("argv", partial_result["qsub_preview"])
                else:
                    self.assertIsNone(partial_result["qsub_preview"])
        roots["server_qsub"]["expected_sha256"] = "0" * 64
        contents["transport-deployment-manifest-v3.json"] = base64.b64encode(canonical_json_bytes(manifest)).decode()
        with self.assertRaises(ValueError):
            self.build(value)

    def test_invalid_supplied_deployment_fact_rejects_despite_missing_prerequisites(self):
        from auto_g16.transport import _driver

        for name in ("transport-deployment-manifest-v3.json", _driver._RESOURCE_DESCRIPTOR_NAME):
            for selected_identity_present in (True, False):
                with self.subTest(name=name, selected_identity_present=selected_identity_present):
                    value = request()
                    value["server_profile"]["runtime_contents"][name] = base64.b64encode(b"{}\n").decode()
                    if not selected_identity_present:
                        value["program_identities"]["xtb"] = None
                    with self.assertRaises(ValueError):
                        self.build(value)

    def test_exact_main_and_program_identity_drift_reject(self):
        for mutate in (
            lambda r: r.update(main_sha=MAIN[:12]),
            lambda r: r.update(main_sha="0" * 40),
            lambda r: r["program_identities"]["xtb"].update(sha256="0" * 64),
            lambda r: r["program_identities"]["crest"].update(version="3.0.3"),
            lambda r: r["program_identities"]["xtb"].update(size_bytes=True),
            lambda r: r["program_identities"]["crest"].update(absolute_path="/elsewhere/crest"),
        ):
            value = request()
            mutate(value)
            with self.assertRaises(ValueError):
                self.build(value)

    def test_missing_xtb_runtime_authority_rejects(self):
        for missing in ("xtb_data_path", fixtures.XTB_RUNTIME_DATA_MANIFEST_NAME):
            value = request()
            container = "platform_paths" if missing == "xtb_data_path" else "runtime_contents"
            del value["server_profile"][container][missing]
            with self.assertRaises(ValueError):
                self.build(value)

    def test_scientific_input_resources_ownership_and_scope_drift_reject(self):
        for mutate in (
            lambda r: r.update(extra="unexpected"),
            lambda r: r["input"].update(sha256="0" * 64),
            lambda r: r["input"].update(portable_name="xtb.pbs"),
            lambda r: r["input"].update(portable_name="xtb.out"),
            lambda r: r["resources"].update(queue="other"),
            lambda r: r["resources"].update(cores=False),
            lambda r: r["workflow"].update(project_id="other-project"),
            lambda r: r["project"].update(remote_project_dir="/home/user100/SDL"),
            lambda r: r["project"].update(remote_project_dir="/outside/project"),
            lambda r: r["plan_intent"].update(program_kind="crest"),
            lambda r: r["plan_intent"].update(input_sha256="0" * 64),
            lambda r: r["program_data"].update(extra="arbitrary"),
        ):
            value = request()
            mutate(value)
            with self.assertRaises(ValueError):
                self.build(value)

    def test_single_xyz_frame_and_finite_coordinates_required(self):
        for raw in (b"1\nx\nH nan 0 0\n", fixtures.XYZ + fixtures.XYZ, b"0\nx\n"):
            value = request()
            value["input"].update(content_base64=base64.b64encode(raw).decode(), sha256=sha256(raw).hexdigest(), size_bytes=len(raw))
            value["plan_intent"]["input_sha256"] = sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                self.build(value)

    def test_json_duplicates_unknown_schema_and_nonfinite_fail_closed(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):
                packet.decode(raw)
        value = request()
        value["schema"] += "-unknown"
        with self.assertRaises(ValueError):
            self.build(value)

    def test_historical_failure_and_zero_effect_budget_are_preserved(self):
        result = self.build()
        self.assertEqual(result["historical_level2"]["job_id"], "682.master")
        self.assertFalse(result["historical_level2"]["retroactively_repaired"])
        self.assertTrue(all(value == 0 for value in result["effect_budget"]["authorized_now"].values()))
        self.assertEqual(result["effect_budget"]["proposed_after_separate_gates"]["qsub_max"], 1)
        self.assertTrue(any("UNKNOWN" in item and "never retry" in item for item in result["stop_conditions"]))

    def test_cli_persists_only_new_private_local_packet(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "request.json"
            output = root / "packet.json"
            source.write_bytes(packet.encode(request()))
            args = ["--request", str(source), "--expected-main-sha", MAIN, "--output", str(output)]
            self.assertEqual(packet.main(args), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            before = output.read_bytes()
            self.assertEqual(packet.main(args), 2)
            self.assertEqual(before, output.read_bytes())
            self.assertEqual(json.loads(before)["status"], "BLOCKED_ON_LIVE_PREREQUISITES")

    def test_local_symlink_parents_and_terminal_objects_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "request.json"
            source.write_bytes(packet.encode(request()))
            (root / "alias").symlink_to(root, target_is_directory=True)
            (root / "linked.json").symlink_to(source)
            for path in (root / "alias" / "request.json", root / "linked.json"):
                with self.assertRaises(OSError):
                    packet.read_request(path)
            with self.assertRaises(OSError):
                packet.write_new(root / "alias" / "out.json", {})
            with self.assertRaises(OSError):
                packet.write_new(root / "linked.json", {})


if __name__ == "__main__":
    unittest.main()
