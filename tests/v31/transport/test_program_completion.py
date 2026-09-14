"""FC01–FC15 inert synthetic completion evidence; no production qualification."""
from dataclasses import replace
from hashlib import sha256
import json
import os
import sys
import subprocess
import threading
import sqlite3
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core, execution
from auto_g16.execution import program as adapter
from auto_g16.execution import program_runtime as runtime
from auto_g16.execution import _program_completion as completion
from auto_g16.execution._program_completion_wrapper import _WRAPPER_SOURCE
from auto_g16.transport import program as transport
from auto_g16.transport._canonical import TransportBoundaryError
from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport import test_program_composition as composition


def manifest():
    roots = {}
    for name, (platform, attestation) in completion._ROOT_RULES.items():
        shell = name == "server_remote_shell"
        content = (name + " synthetic\n").encode()
        roots[name] = {"path": "/opt/auto-g16-fixtures/bin/" + name, "platform": platform, "attestation_mode": attestation, "deployment_identity": "synthetic-only", "expected_sha256": None if shell else sha256(content).hexdigest(), "expected_size_bytes": None if shell else len(content), "shell_grammar": "posix-sh-v1" if shell else None}
    return {"schema": "auto-g16-v3-transport-deployment-manifest/3", "deployment_id": "synthetic-completion", "bootstrap_protocol": "auto-g16-v31-rtwin-bootstrap/1", "trust_roots": roots}


class CompletionTests(lane.LaneAFixture):
    """Native directory flock and default SQLite, including on Darwin."""
    def profile(self, **kwargs):
        profile = super().profile(**kwargs)
        return replace(profile, runtime_contents={**profile.runtime_contents, completion._DEPLOYMENT_NAME: completion._receipt_json(manifest())})

    def resolved(self, **kwargs):
        return execution.resolve_server_profile(self.profile(**kwargs))

    def completion_spec(self, **changes):
        return adapter._prepare_program_execution_spec(program_kind="xtb", executable_path=lane.XTB_EXECUTABLE_PATH, executable_size_bytes=len(lane.XTB_EXECUTABLE_BYTES), executable_sha256=sha256(lane.XTB_EXECUTABLE_BYTES).hexdigest(), input_name="input.xyz", input_bytes=lane.XYZ, program_data=self.xtb_data(**changes), resolved_profile=self.resolved(), completion_mode=completion._MODE)

    def completion_snapshot(self, **changes):
        return self.snapshot_service.prepare(self.store, attempt_id="attempt-1", calculation_plan_id="plan-1", resource_spec_id="resource-1", program_execution_spec=self.completion_spec(**changes), project_physical_binding=self.physical_binding(), resolved_resource_request=self.resources(), resolved_server_profile=self.resolved(), workspace_binding=self.workspace(), completion_rendering_material=completion._prepare_completion_rendering_material(self.profile(), self.resolved()))

    def setUp(self):
        super().setUp()
        root = self.root / "transport"
        root.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(root / "program.sqlite3", approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.snapshot = self.completion_snapshot()
        self.driver = composition._Driver()
        self.input_bytes = {"input.xyz": lane.XYZ}
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}

    execute = composition.ProgramCompositionTests.execute

    def kwargs(self):
        return dict(snapshot=self.snapshot, program_transport_store=self.program_transport_store, driver=self.driver)

    def publish(self, *, code=0, signal=None, **overrides):
        receipt = dict(completion._receipt_binding(self.snapshot, "123.server", "workspace-token-v31"))
        receipt.update(termination={"kind": "signaled" if signal else "exited", "returncode": None if signal else code, "signal": signal}, finished_at="2026-09-14T01:02:03.000004Z", outputs=[])
        for declaration in (*self.snapshot.program_execution_spec.required_outputs, *self.snapshot.program_execution_spec.optional_outputs):
            content = self.driver.outputs.get(declaration["portable_name"])
            receipt["outputs"].append({**{key: declaration[key] for key in ("logical_role", "portable_name", "format")}, "presence": "absent" if content is None else "present", "sha256": None if content is None else sha256(content).hexdigest(), "size_bytes": None if content is None else len(content)})
        receipt.update(overrides)
        self.driver.outputs["v31-completion.json"] = completion._receipt_json(receipt)
        self.driver.query_response = {"job_id": "123.server", "state": "absent"}
        return receipt

    def collect(self):
        return runtime._collect_program_completion(self.store, **self.kwargs(), input_bytes=self.input_bytes)

    def test_success_durable_bundle_and_zero_read_replay(self):
        self.execute(); self.publish()
        assessment = self.collect()
        self.assertEqual(assessment.data["diagnostic"], "completed")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()), assessment)
        proof = runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())
        self.assertEqual(proof["schema"], "program-terminal-success-authority/2")
        self.assertEqual(len(self.driver.calls), calls)

    def test_default_strict_renderer_and_mode_are_unchanged(self):
        strict = self.successor_snapshot()
        self.assertEqual(strict.program_execution_spec.adapter_contract_version, 2)
        self.assertNotIn("completion_mode", strict.program_execution_spec.program_data)
        self.assertEqual(strict.scheduler_artifacts[0]["content_utf8"].splitlines()[1], "# auto-g16-v31-scheduler/1")
        self.assertNotEqual(strict.program_execution_snapshot_id, self.snapshot.program_execution_snapshot_id)
        self.snapshot.assert_identity_closed()

    def test_material_missing_or_strict_injection_rejected(self):
        with self.assertRaises(ValueError):
            self.successor_snapshot(spec=self.completion_spec())
        with self.assertRaises(ValueError):
            adapter._render_scheduler_artifact(self.xtb_spec(), self.resources(), self.resolved(), completion_rendering_material=self.snapshot._completion_material())

    def test_rendered_source_and_material_reclose(self):
        script = self.snapshot.scheduler_artifacts[0]["content_utf8"]
        self.assertIn(" -I -S -B -c ", script)
        material = self.snapshot._completion_material()
        self.assertEqual(material, completion._prepare_completion_rendering_material(self.profile(), self.resolved()))
        for changed in (script.replace("# completion-material-base64:", "# moved:"), script + script.splitlines()[2] + "\n"):
            with self.assertRaises(ValueError):
                completion._material_from_artifact(({"content_utf8": changed},), self.resolved())

    def test_production_driver_is_unconditionally_blocked(self):
        with self.assertRaisesRegex(TransportBoundaryError, "publisher-not-qualified"):
            _RTWinProgramEffectDriver(snapshot=self.snapshot, current_profile=self.profile(), program_transport_store=self.program_transport_store)
        self.driver.runtime_qualification = {**self.driver.runtime_qualification, "bootstrap_protocol": "auto-g16-v31-rtwin-bootstrap/1"}
        with self.assertRaisesRegex(TransportBoundaryError, "publisher-not-qualified"):
            runtime._snapshot_binding(self.snapshot, self.program_transport_store, self.driver)
        self.assertEqual(self.driver.calls, [])

    def test_terminal_scheduler_cannot_complete_receipt_mode(self):
        self.execute()
        self.driver.query_response = {"job_id": "123.server", "state": "terminal", "exit_status": 0}
        result = self.collect()
        self.assertEqual(result.data["diagnostic"], "awaiting-absence")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_running_receipt_cannot_complete(self):
        self.execute(); self.publish()
        self.driver.query_response = {"job_id": "123.server", "state": "running"}
        self.assertEqual(self.collect().data["diagnostic"], "scheduler-active")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.RUNNING)

    def test_absence_without_receipt_is_unknown(self):
        self.execute(); self.driver.query_response = {"job_id": "123.server", "state": "absent"}
        self.assertEqual(self.collect().data["diagnostic"], "receipt-missing")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_nonzero_with_absent_required_output_is_failed(self):
        self.execute(); self.driver.outputs = {}; self.publish(code=7)
        self.assertEqual(self.collect().data["diagnostic"], "program-nonzero")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.FAILED)

    def test_zero_with_absent_required_output_is_failed(self):
        self.execute(); self.driver.outputs = {}; self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "output-incomplete")

    def test_direct_signal_with_absent_output_is_failed(self):
        self.execute(); self.driver.outputs = {}; self.publish(signal=15)
        self.assertEqual(self.collect().data["diagnostic"], "program-signaled")

    def test_invalid_geometry_is_execution_failure(self):
        self.execute(); self.driver.outputs["xtbopt.xyz"] = b"1\nfixture\nH nan 0 0\n"; self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "output-invalid")

    def test_changed_receipt_binding_precedes_nonzero(self):
        self.execute(); self.publish(code=8, effect_intent_id="foreign-intent")
        self.assertEqual(self.collect().data["diagnostic"], "receipt-invalid")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_missing_input_bytes_stops_without_remote_reads(self):
        self.execute(); self.publish(); self.input_bytes = {}
        calls = len(self.driver.calls)
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")
        self.assertEqual(len(self.driver.calls), calls)

    def test_fetch_timeout_is_not_absence_or_nonzero(self):
        self.execute(); self.publish(code=4)
        self.driver.raise_operation = ("FETCH_EXACT_FILE", TimeoutError())
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")

    def test_guard_blocks_another_store_handle_without_effects(self):
        self.execute(); self.publish()
        other = transport._ProgramTransportStore.open_existing(self.program_transport_store._path, approved_root=self.program_transport_store._root)
        self.addCleanup(other.close)
        before = self.store.observations_for_attempt("attempt-1")
        calls = len(self.driver.calls)
        with other._completion_guard():
            with self.assertRaisesRegex(TransportBoundaryError, "busy"):
                self.collect()
        self.assertEqual(len(self.driver.calls), calls)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), before)

    def test_later_unknown_blocks_promotion_without_rollback(self):
        self.execute(); self.publish(); self.collect()
        self.driver.query_response = {"job_id": "123.server", "state": "unknown"}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "acquisition-unknown")
        with self.assertRaises(TransportBoundaryError):
            runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)

    def test_later_active_is_conflict_without_rollback(self):
        self.execute(); self.publish(); self.collect()
        self.driver.query_response = {"job_id": "123.server", "state": "queued"}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "evidence-conflict")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)

    def test_contradictory_terminal_exit_blocks_nonzero(self):
        self.execute()
        self.driver.query_response = {"job_id": "123.server", "state": "terminal", "exit_status": 0}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        self.publish(code=1)
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_receipt_grammar_rejects_duplicate_fields_and_bad_types(self):
        valid = self.publish()
        for raw in (completion._receipt_json(valid).replace(b'"schema":', b'"schema":"duplicate","schema":', 1), completion._receipt_json({**valid, "adapter_contract_version": True}), completion._receipt_json({**valid, "extra": 1}), b"\xef\xbb\xbf" + completion._receipt_json(valid), completion._receipt_json(valid) + b"\n"):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                completion._decode_receipt(raw)

    def test_wrapper_source_compiles_and_no_replace_publication(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "publication"
        directory.mkdir()
        fd, token = namespace["directory"](str(directory))
        self.addCleanup(os.close, fd)
        raw = b'{"inert":true}\n'
        namespace["publish"](fd, str(directory), token, raw)
        self.assertEqual((directory / "v31-completion.json").read_bytes(), raw)
        self.assertEqual((directory / "v31-completion.pending").stat().st_ino, (directory / "v31-completion.json").stat().st_ino)
        with self.assertRaises(FileExistsError):
            namespace["publish"](fd, str(directory), token, b"different")
        self.assertEqual((directory / "v31-completion.json").read_bytes(), raw)

    def test_single_point_optional_absence_succeeds(self):
        self.snapshot = self.completion_snapshot(task="single-point")
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}
        self.execute(); self.driver.outputs.pop("xtbopt.xyz"); self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "completed")

    def test_fresh_attempt_only_and_bad_material_before_attestation(self):
        with patch.object(type(self.project_provisioning), "_attest_current", side_effect=AssertionError("must not attest")):
            with self.assertRaises(ValueError):
                self.successor_snapshot(spec=self.completion_spec())
        self.execute()
        with self.assertRaisesRegex(ValueError, "fresh unconsumed"):
            self.completion_snapshot()

    def test_material_and_manifest_adversarial_vectors(self):
        from auto_g16.transport._driver import _parse_deployment_manifest
        raw = completion._receipt_json(manifest())
        self.assertEqual(_parse_deployment_manifest(raw, successor=True).deployment_id, "synthetic-completion")
        for path in ("deployment_id", "root"):
            value = manifest()
            if path == "root":
                value["trust_roots"]["server_python"]["deployment_identity"] = "a\nb"
            else:
                value[path] = "a\nb"
            raw = completion._receipt_json(value)
            with self.assertRaises(ValueError):
                completion._deployment_projection(raw)
            with self.assertRaises(TransportBoundaryError):
                _parse_deployment_manifest(raw, successor=True)
        material = dict(self.snapshot._completion_material())
        for key, value in (("schema", "unknown"), ("resolved_server_profile_id", "foreign"), ("deployment_manifest_base64", material["deployment_manifest_base64"] + "="), ("xtb_runtime_data_manifest_base64", completion.base64.b64encode(b"{}\n").decode())):
            with self.subTest(key=key), self.assertRaises(ValueError):
                completion._validate_material({**material, key: value}, self.resolved())
        with self.assertRaises(ValueError):
            completion._prepare_completion_rendering_material(self.profile(profile_revision=2), self.resolved())

    def test_byte_bundle_missing_or_spliced_stops_replay(self):
        self.execute(); self.publish(); self.collect()
        calls = len(self.driver.calls)
        with patch.object(self.store, "results_for_attempt", return_value=()):
            self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "evidence-conflict")
        self.assertEqual(len(self.driver.calls), calls)
        with self.assertRaises(TransportBoundaryError):
            runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())

    def test_assessment_transition_crash_reopens_without_reads(self):
        self.execute(); self.publish()
        advance = self.store.advance_attempt
        def crash(attempt, state):
            if state is core.AttemptState.SUCCEEDED:
                raise RuntimeError("synthetic crash after assessment")
            return advance(attempt, state)
        with patch.object(self.store, "advance_attempt", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.collect()
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)
        self.store.close()
        self.store = core.SQLiteRuntimeStore(self.database)
        self.addCleanup(self.store.close)
        self.program_transport_store.close()
        self.program_transport_store = transport._ProgramTransportStore.open_existing(self.program_transport_store._path, approved_root=self.program_transport_store._root)
        self.addCleanup(self.program_transport_store.close)
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "completed")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertEqual(len(self.driver.calls), calls)

    def test_bundle_before_assessment_crash_replays(self):
        self.execute(); self.publish()
        with patch.object(runtime, "_persist_completion_assessment", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaises(RuntimeError):
                self.collect()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "completed")
        self.assertEqual(len(self.driver.calls), calls)

    def test_restat_identity_drift_overrides_exit(self):
        self.execute(); self.publish(code=5)
        original = self.driver.stat_exact_file
        count = {}
        def changed(request):
            name = request["payload"]["portable_name"]
            count[name] = count.get(name, 0) + 1
            response = original(request)
            if name == "xtb.out" and count[name] == 2:
                return {**response, "file_physical_token": "same-size-new-inode"}
            return response
        self.driver.stat_exact_file = changed
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_optional_absence_drift_is_conflict(self):
        self.snapshot = self.completion_snapshot(task="single-point")
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}
        self.execute(); self.driver.outputs.pop("xtbopt.xyz"); self.publish()
        original = self.driver.stat_exact_file
        count = 0
        def changed(request):
            nonlocal count
            if request["payload"]["portable_name"] == "xtbopt.xyz":
                count += 1
                if count == 2:
                    self.driver.outputs["xtbopt.xyz"] = lane.XYZ
            return original(request)
        self.driver.stat_exact_file = changed
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_final_query_unknown_is_not_absence(self):
        self.execute(); self.publish()
        original = self.driver.query_scheduler
        count = 0
        def changed(request):
            nonlocal count
            count += 1
            if count == 2:
                self.driver.query_response = {"job_id": "123.server", "state": "unknown"}
            return original(request)
        self.driver.query_scheduler = changed
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")

    def test_guard_rejects_foreign_token_and_allows_native_sqlite(self):
        with self.assertRaises(TransportBoundaryError):
            runtime._collect_program_completion(self.store, **self.kwargs(), input_bytes=self.input_bytes, _completion_token=object())
        self.execute(); self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "completed")
        self.assertIsNone(self.program_transport_store._completion_owner)
        self.assertFalse(self.program_transport_store._completion_lock.locked())

    def test_wrapper_runtime_dotfiles_and_symlinks(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "runtime-data"
        directory.mkdir()
        for name in lane.XTB_RUNTIME_DATA_FILES:
            raw = name.encode()
            path = directory / name
            path.write_bytes(raw)
            namespace["file_identity"](str(path), len(raw), sha256(raw).hexdigest())
        link = directory / "linked"
        link.symlink_to(directory / ".param_gfnff.xtb")
        with self.assertRaises(OSError):
            namespace["file_identity"](str(link), 1, "0" * 64)

    def test_wrapper_pinned_parent_chain_rejects_replacement(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "workspace"
        directory.mkdir()
        fd, token, chain = namespace["pin_directory"](str(directory))
        try:
            directory.rename(self.root / "retained-workspace")
            directory.mkdir()
            with self.assertRaises(ValueError):
                namespace["reattest_directory"](str(directory), token, chain)
            with self.assertRaises(ValueError):
                namespace["publish"](fd, str(directory), token, b"{}\n", chain)
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(list((self.root / "retained-workspace").iterdir()), [])
        finally:
            for descriptor in reversed(chain):
                os.close(descriptor)

    def test_wrapper_waits_adopted_descendants_and_uses_direct_status(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        with patch("os.waitpid", side_effect=[(123, 7 << 8), (456, 0), ChildProcessError()] ) as waiting:
            self.assertEqual(namespace["wait_all"](123, namespace["time"].monotonic() + 1), 7 << 8)
            self.assertEqual(waiting.call_count, 3)
        with patch("os.waitpid", return_value=(0, 0)):
            with self.assertRaisesRegex(ValueError, "not-terminated"):
                namespace["wait_all"](123, 0)

    def test_wrapper_prelink_failure_retains_pending_only(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "publish-failure"
        directory.mkdir()
        fd, token = namespace["directory"](str(directory))
        try:
            with patch("os.link", side_effect=OSError("synthetic link failure")):
                with self.assertRaises(OSError):
                    namespace["publish"](fd, str(directory), token, b"{}\n")
            self.assertTrue((directory / "v31-completion.pending").is_file())
            self.assertFalse((directory / "v31-completion.json").exists())
        finally:
            os.close(fd)

    def test_new_epoch_cannot_replace_accepted_capture(self):
        self.execute(); self.publish(); self.collect()
        self.driver.outputs["xtb.out"] = b"different log\n"
        self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")
        with self.assertRaises(TransportBoundaryError):
            runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())

    def test_null_result_unknown_cannot_erase_accepted_capture(self):
        self.execute(); self.publish(); self.collect()
        self.input_bytes = {}
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")
        self.input_bytes = {"input.xyz": lane.XYZ}
        self.driver.outputs["xtb.out"] = b"different log\n"
        self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_null_result_unknown_cannot_hide_missing_accepted_bundle(self):
        self.execute(); self.publish(); self.collect()
        self.input_bytes = {}; self.collect()
        calls = len(self.driver.calls)
        with patch.object(self.store, "results_for_attempt", return_value=()):
            self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "evidence-conflict")
        self.assertEqual(len(self.driver.calls), calls)

    def test_newer_orphan_bundle_after_unknown_is_replayed_without_reads(self):
        self.execute(); self.publish(); self.input_bytes = {}; self.collect()
        self.input_bytes = {"input.xyz": lane.XYZ}
        with patch.object(runtime, "_persist_completion_assessment", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaises(RuntimeError):
                self.collect()
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "completed")
        self.assertEqual(len(self.driver.calls), calls)

    def test_conflict_replay_is_idempotent(self):
        self.execute(); self.publish(); self.collect()
        self.driver.query_response = {"job_id": "123.server", "state": "queued"}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        conflict = runtime._replay_program_completion(self.store, **self.kwargs())
        before = self.store.observations_for_attempt("attempt-1")
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()), conflict)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), before)

    def test_boolean_bundle_size_and_missing_assessment_refs_rejected(self):
        self.execute(); self.driver.outputs["xtb.out"] = b"a"; self.publish(); self.collect()
        _base, receipts, job, workspace = runtime._completion_context(self.store, self.snapshot, self.program_transport_store, self.driver)
        record = self.store.results_for_attempt("attempt-1")[0]
        data = json.loads(completion._receipt_json(record.data))
        data["captured_files"][1]["size_bytes"] = True
        altered = core.Result(result_id=runtime.semantic_id("program-completion-evidence", data), attempt_id="attempt-1", result_type=record.result_type, data=data)
        observations = self.store.observations_for_attempt("attempt-1")
        with self.assertRaises((ValueError, TransportBoundaryError)):
            runtime._validate_completion_bundle(altered, self.snapshot, job, workspace, receipts, observations)
        data = {**observations[-1].data, "evidence_observation_ids": ()}
        altered = core.Observation(observation_id=runtime.semantic_id("program-completion-assessment", data), attempt_id="attempt-1", observation_type=runtime._COMPLETION_ASSESSMENT, data=data)
        with self.assertRaisesRegex(TransportBoundaryError, "omits exact"):
            runtime._verify_completion_assessments((*observations[:-1], altered), self.snapshot, job)

    def test_unlock_failure_releases_in_process_guard(self):
        original = fcntl.flock
        def failure(fd, operation):
            original(fd, operation)
            if operation == fcntl.LOCK_UN:
                raise OSError("synthetic unlock failure")
        with patch("fcntl.flock", side_effect=failure):
            with self.assertRaisesRegex(TransportBoundaryError, "unlock failed"):
                with self.program_transport_store._completion_guard():
                    pass
        self.assertFalse(self.program_transport_store._completion_lock.locked())
        self.assertIsNone(self.program_transport_store._completion_owner)
        self.assertTrue(self.program_transport_store._invalid)
        with self.assertRaises(TransportBoundaryError):
            with self.program_transport_store._completion_guard():
                self.fail("uncertain owner reused")

    def test_wrapper_inert_invocation_failure_and_publication_matrix(self):
        """Exercise full wrapper control flow with Popen/wait/subreaper replaced.

        This proves no Linux kernel/host qualification and executes no program.
        """
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        python_path = Path(sys.executable).resolve()
        python_raw = python_path.read_bytes()
        for scenario in ("zero", "nonzero", "signal", "launch-failure", "log-replaced", "log-same-bytes-new-inode", "log-missing-after-close"):
            with self.subTest(scenario=scenario):
                workspace = self.root / ("wrapper-" + scenario)
                workspace.mkdir(mode=0o700)
                data_path = workspace / "runtime-data"
                data_path.mkdir()
                for name in lane.XTB_RUNTIME_DATA_FILES:
                    (data_path / name).write_bytes(name.encode())
                executable = workspace / "inert-xtb"
                executable.write_bytes(b"inert synthetic bytes; never executed\n")
                (workspace / "input.xyz").write_bytes(lane.XYZ)
                (workspace / ".auto-g16-v31-submit-intent").write_bytes(completion._receipt_json({"program_execution_snapshot_id": "synthetic-snapshot", "effect_intent_id": "synthetic-intent"}))
                spec = json.loads(completion._receipt_json(self.snapshot.program_execution_spec.semantic_payload()))
                spec["invocation"]["executable_identity"] = {"absolute_path": str(executable), "size_bytes": executable.stat().st_size, "sha256": sha256(executable.read_bytes()).hexdigest()}
                spec["invocation"]["argv"][0] = str(executable)
                material = dict(self.snapshot._completion_material())
                deployment = manifest()
                deployment["trust_roots"]["server_python"].update(path=str(python_path), expected_size_bytes=len(python_raw), expected_sha256=sha256(python_raw).hexdigest())
                material["deployment_manifest_base64"] = completion.base64.b64encode(completion._receipt_json(deployment)).decode()
                fields = {key: value for key, value in self.snapshot._identity_payload.items() if key != "scheduler_artifacts"}
                fields.update(cwd_binding={"location_kind": "server", "path": str(workspace)}, program_execution_spec_payload_sha256=runtime.semantic_sha256(spec))
                binding = completion._prebinding(fields, material)
                config = json.loads(completion._receipt_json({"prebinding": binding, "prebinding_sha256": runtime.semantic_sha256(binding), "spec": spec, "material": material, "xtb_data_path": str(data_path), "cores": 8, "walltime_seconds": 1}))
                self.assertEqual(namespace["semantic"](config["prebinding"]), config["prebinding_sha256"])
                launches = []
                class InertChild:
                    pid = 123
                    returncode = None
                def launch(argv, **kwargs):
                    launches.append((argv, kwargs))
                    self.assertFalse(kwargs["shell"])
                    self.assertEqual(kwargs["env"], {"OMP_NUM_THREADS": "8", "XTBPATH": str(data_path)})
                    if scenario == "launch-failure":
                        raise OSError("synthetic launch failure")
                    os.write(kwargs["stdout"], b"inert program log\n")
                    if scenario in {"log-replaced", "log-same-bytes-new-inode"}:
                        (workspace / "xtb.out").rename(workspace / "original-log")
                        (workspace / "xtb.out").write_bytes(b"inert program log\n" if scenario == "log-same-bytes-new-inode" else b"substitute log\n")
                    return InertChild()
                status = 15 if scenario == "signal" else (7 << 8 if scenario == "nonzero" else 0)
                original_read = namespace["read_name"]
                def read_after_close(parent, name, *args, **kwargs):
                    if scenario == "log-missing-after-close" and name == "xtb.out":
                        (workspace / "xtb.out").rename(workspace / "retained-closed-log")
                    return original_read(parent, name, *args, **kwargs)
                original_cwd = Path.cwd()
                try:
                    with patch.dict(os.environ, {"PBS_JOBID": "123.server"}), patch.object(sys, "executable", str(python_path)), patch.dict(namespace, {"subreaper": lambda: None, "wait_all": lambda pid, deadline: status, "read_name": read_after_close}), patch("subprocess.Popen", side_effect=launch):
                        if scenario in {"launch-failure", "log-replaced", "log-same-bytes-new-inode", "log-missing-after-close"}:
                            with self.assertRaises((OSError, ValueError)):
                                namespace["run"](config)
                            self.assertFalse((workspace / "v31-completion.json").exists())
                        else:
                            self.assertEqual(namespace["run"](config), 143 if scenario == "signal" else 7 if scenario == "nonzero" else 0)
                            receipt = completion._decode_receipt((workspace / "v31-completion.json").read_bytes())
                            self.assertEqual(receipt["termination"]["kind"], "signaled" if scenario == "signal" else "exited")
                            self.assertEqual(receipt["outputs"][1]["presence"], "absent")
                        with self.assertRaises((ValueError, FileExistsError)):
                            namespace["run"](config)
                    self.assertEqual(len(launches), 1)
                finally:
                    os.chdir(original_cwd)

    def test_changed_original_input_bytes_is_conflict_before_reads(self):
        self.execute(); self.publish(); self.input_bytes = {"input.xyz": b"changed"}
        calls = len(self.driver.calls)
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")
        self.assertEqual(len(self.driver.calls), calls)

    def test_fetch_identity_mismatch_is_conflict_before_exit(self):
        self.execute(); self.publish(code=5)
        original = self.driver.fetch_exact_file
        def replaced(request):
            return {**original(request), "file_physical_token": "new-file-object"}
        self.driver.fetch_exact_file = replaced
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_final_terminal_contradiction_precedes_awaiting_absence(self):
        self.execute(); self.publish(code=7)
        original = self.driver.query_scheduler
        count = 0
        def changed(request):
            nonlocal count
            count += 1
            if count == 2:
                self.driver.query_response = {"job_id": "123.server", "state": "terminal", "exit_status": 0}
            return original(request)
        self.driver.query_scheduler = changed
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_all_receipt_authority_fields_checked_before_returncode(self):
        receipt = self.publish(code=7)
        expected = completion._receipt_binding(self.snapshot, "123.server", "workspace-token-v31")
        for key, value in expected.items():
            if key == "inputs":
                replacement = [*receipt["inputs"], *receipt["inputs"]]
            elif key.endswith("sha256"):
                replacement = "f" * 64 if value != "f" * 64 else "e" * 64
            elif type(value) is int:
                replacement = value + 1
            elif key == "remote_workspace":
                replacement = "/home/user100/SDL/foreign/attempt-1"
            else:
                replacement = "foreign"
            with self.subTest(key=key), self.assertRaises(ValueError):
                completion._bound_receipt(completion._receipt_json({**receipt, key: replacement}), self.snapshot, "123.server", "workspace-token-v31")

    def test_snapshot_review_reopen_uses_only_embedded_material(self):
        from auto_g16.execution.program import _validate_program_review_semantics
        reviewed = self.snapshot._approval_semantics()
        with patch("auto_g16.execution._program_completion.resolve_server_profile", side_effect=AssertionError("no current profile source")):
            self.assertEqual(_validate_program_review_semantics(reviewed), reviewed)
        altered = json.loads(completion._receipt_json(reviewed))
        altered["scheduler_artifacts"][0]["content_utf8"] += "# altered\n"
        with self.assertRaises(ValueError):
            _validate_program_review_semantics(altered)

    def test_strict_consumer_and_historical_collection_reject(self):
        with self.assertRaisesRegex(TransportBoundaryError, "strict consumer"):
            runtime._assert_program_terminal_success_authority(self.store, **self.kwargs(), capture=None)
        with self.assertRaises(TransportBoundaryError):
            runtime._capture_program_outputs(self.store, **self.kwargs())
        strict = self.successor_snapshot()
        with self.assertRaises(TransportBoundaryError):
            runtime._collect_program_completion(self.store, snapshot=strict, program_transport_store=self.program_transport_store, driver=self.driver, input_bytes=self.input_bytes)
        self.assertEqual(self.driver.calls, [])


    def test_wrapper_post_open_enoent_is_not_safe_absence(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "metadata-failure"
        directory.mkdir()
        (directory / "xtb.out").write_bytes(b"still exists\n")
        fd, _token = namespace["directory"](str(directory))
        try:
            with patch("os.stat", side_effect=FileNotFoundError("synthetic final metadata failure")):
                with self.assertRaises(FileNotFoundError) as error:
                    namespace["read_name"](fd, "xtb.out")
                self.assertNotIsInstance(error.exception, namespace["AbsentFile"])
            self.assertEqual((directory / "xtb.out").read_bytes(), b"still exists\n")
            with self.assertRaises(namespace["AbsentFile"]):
                namespace["read_name"](fd, "not-created")
        finally:
            os.close(fd)

    def test_c4_old_receipt_store_and_strict_v2_reject_before_effects(self):
        legacy = transport._ProgramTransportStore.create_new(self.root / "old.sqlite3", approved_root=self.root)
        self.addCleanup(legacy.close)
        observations = self.store.observations_for_attempt("attempt-1")
        with self.assertRaisesRegex(TransportBoundaryError, "completion-store-not-qualified"):
            runtime._collect_program_completion(self.store, snapshot=self.snapshot, program_transport_store=legacy, driver=self.driver, input_bytes=self.input_bytes)
        with self.assertRaisesRegex(TransportBoundaryError, "completion-store-not-qualified"):
            runtime._snapshot_binding(self.snapshot, legacy, self.driver)
        with self.assertRaisesRegex(TransportBoundaryError, "strict requires"):
            runtime._snapshot_binding(self.successor_snapshot(), self.program_transport_store, self.driver)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), observations)
        self.assertEqual(self.driver.calls, [])

    def test_c4_drift_during_driver_stops_before_receipt_or_assessment(self):
        self.execute(); self.publish()
        observations = self.store.observations_for_attempt("attempt-1")
        original = self.driver.query_scheduler
        def drift(request):
            response = original(request)
            os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
            return response
        self.driver.query_scheduler = drift
        with self.assertRaises(TransportBoundaryError):
            self.collect()
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), observations)
        self.assertEqual(self.store.results_for_attempt("attempt-1"), ())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_c4_drift_after_bundle_keeps_bytes_without_assessment_or_transition(self):
        self.execute(); self.publish()
        original = self.store.append_result
        def append_then_drift(record):
            original(record)
            os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
        with patch.object(self.store, "append_result", side_effect=append_then_drift):
            with self.assertRaises(TransportBoundaryError):
                self.collect()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        self.assertFalse(any(o.observation_type == runtime._COMPLETION_ASSESSMENT for o in self.store.observations_for_attempt("attempt-1")))
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_c4_drift_after_assessment_prevents_core_transition(self):
        self.execute(); self.publish()
        original = self.store.append_observation
        def append_then_drift(record):
            original(record)
            if record.observation_type == runtime._COMPLETION_ASSESSMENT:
                os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
        with patch.object(self.store, "append_observation", side_effect=append_then_drift):
            with self.assertRaises(TransportBoundaryError):
                self.collect()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        self.assertTrue(any(o.observation_type == runtime._COMPLETION_ASSESSMENT for o in self.store.observations_for_attempt("attempt-1")))
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_c4_reconcile_drift_cannot_advance_unknown(self):
        self.driver.raise_operation = ("SUBMIT_QSUB_ONCE", transport._ProgramEffectUnknown("synthetic uncertain submission"))
        self.execute()
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)
        self.driver.raise_operation = None
        self.driver.reconcile_response = {"outcome": "SUCCEEDED", "job_id": "999.server"}
        original = runtime._append_receipt
        def append_then_drift(*args, **kwargs):
            record = original(*args, **kwargs)
            if kwargs["operation"] == "RECONCILE_SUBMISSION":
                os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
            return record
        with patch.object(runtime, "_append_receipt", side_effect=append_then_drift):
            with self.assertRaises(TransportBoundaryError):
                runtime._reconcile_program_submission(self.store, **self.kwargs())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)
        self.assertEqual(self.store.observations_for_attempt("attempt-1")[-1].data["operation"], "RECONCILE_SUBMISSION")


class NativeCompletionStoreTests(unittest.TestCase):
    """Real OS ownership, unmodified SQLite; never a remote driver."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "program.sqlite3"
        self.owner = transport._ProgramTransportStore._create_completion_store(self.path, approved_root=self.root)
        self.addCleanup(self.owner.close)

    def subprocess_open(self, path=None, root=None):
        code = """
import sys
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.transport._canonical import TransportBoundaryError
try:
    value = _ProgramTransportStore.open_existing(sys.argv[1], approved_root=sys.argv[2])
    with value._completion_guard():
        value._connection.execute('SELECT * FROM program_transport_meta').fetchall()
    value.close()
    print('acquired')
except TransportBoundaryError:
    print('rejected')
"""
        result = subprocess.run([sys.executable, "-c", code, str(path or self.path), str(root or self.root)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_native_cross_process_and_same_parent_ownership(self):
        other = transport._ProgramTransportStore.open_existing(self.path, approved_root=self.root)
        self.addCleanup(other.close)
        sibling = transport._ProgramTransportStore._create_completion_store(self.root / "sibling.sqlite3", approved_root=self.root)
        self.addCleanup(sibling.close)
        with self.owner._completion_guard() as token:
            self.assertEqual(self.subprocess_open(), "rejected")
            for candidate in (other, sibling):
                with self.assertRaises(TransportBoundaryError):
                    with candidate._completion_guard():
                        self.fail("contender entered")
            with self.assertRaises(TransportBoundaryError):
                other.attest_runtime(program_execution_snapshot_id="snapshot", resolved_server_profile_id="profile", qualification=composition._Driver().runtime_qualification)
            self.owner._require_completion_guard(token)
            self.assertFalse(os.get_inheritable(self.owner._completion_owner[3]))
        self.assertEqual(self.subprocess_open(), "acquired")

    def test_native_threads_foreign_tokens_and_close_lifecycle(self):
        other = transport._ProgramTransportStore.open_existing(self.path, approved_root=self.root)
        with self.owner._completion_guard() as token:
            errors = []
            def contender():
                for operation in (lambda: self.owner._require_completion_guard(token), self.owner.close, lambda: self.owner.attest_runtime(program_execution_snapshot_id="s", resolved_server_profile_id="p", qualification=composition._Driver().runtime_qualification)):
                    try:
                        operation()
                    except TransportBoundaryError:
                        errors.append(True)
            thread = threading.Thread(target=contender)
            thread.start(); thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [True, True, True])
            other.close()
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            os.close(fd)
            self.assertEqual(self.subprocess_open(), "rejected")
            with self.assertRaises(TransportBoundaryError):
                self.owner.close()
            with self.assertRaises(TransportBoundaryError):
                other._require_completion_guard(token)
        with self.assertRaises(TransportBoundaryError):
            self.owner._require_completion_guard(token)
        self.assertEqual(self.subprocess_open(), "acquired")

    def test_separate_parent_progress_and_strict_open_unchanged(self):
        strict_path = self.root / "strict.sqlite3"
        strict = transport._ProgramTransportStore.create_new(strict_path, approved_root=self.root)
        strict_id = strict.program_transport_store_id
        strict.close()
        separate_root = self.root / "separate"
        separate_root.mkdir()
        separate = transport._ProgramTransportStore._create_completion_store(separate_root / "program.sqlite3", approved_root=self.root)
        self.addCleanup(separate.close)
        with self.owner._completion_guard():
            reopened = transport._ProgramTransportStore.open_existing(strict_path, approved_root=self.root)
            self.assertEqual(reopened.program_transport_store_id, strict_id)
            reopened.close()
            with separate._completion_guard():
                separate._attest()

    def test_no_create_retry_or_existing_target_overwrite(self):
        before = self.path.read_bytes()
        with self.assertRaises((TransportBoundaryError, OSError)):
            transport._ProgramTransportStore._create_completion_store(self.path, approved_root=self.root)
        self.assertEqual(self.path.read_bytes(), before)
        incomplete = self.root / "incomplete.sqlite3"
        with patch.object(transport._ProgramTransportStore, "_create_schema", side_effect=RuntimeError("inert initialization crash")):
            with self.assertRaisesRegex(RuntimeError, "initialization crash"):
                transport._ProgramTransportStore._create_completion_store(incomplete, approved_root=self.root)
        self.assertTrue(incomplete.is_file())
        with self.assertRaises(TransportBoundaryError):
            transport._ProgramTransportStore.open_existing(incomplete, approved_root=self.root)
        with self.assertRaises((TransportBoundaryError, OSError)):
            transport._ProgramTransportStore._create_completion_store(incomplete, approved_root=self.root)

    def test_schema_binding_is_closed_and_append_only(self):
        row = self.owner._connection.execute("SELECT * FROM program_transport_meta").fetchone()
        self.assertEqual(len(row), 10)
        self.assertEqual(row[-1], transport.canonical_bytes(self.owner._guard_binding))
        self.assertEqual(self.owner._connection.execute("PRAGMA user_version").fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.owner._connection.execute("UPDATE program_transport_meta SET completion_guard_binding=?", (b"wrong",))
        for raw in (b"wrong", transport.canonical_bytes({**self.owner._guard_binding, "extra": 1}), transport.canonical_bytes({**self.owner._guard_binding, "component_identities": [[True, 1]]})):
            directory = self.root / str(len(list(self.root.iterdir())))
            directory.mkdir()
            path = directory / "bad.sqlite3"
            bad = transport._ProgramTransportStore._create_completion_store(path, approved_root=directory)
            bad.close()
            with sqlite3.connect(path) as database:
                database.execute("DROP TRIGGER program_transport_meta_no_update")
                database.execute("UPDATE program_transport_meta SET completion_guard_binding=?", (raw,))
                database.execute(dict(transport._PROGRAM_STORE_TRIGGERS)["program_transport_meta_no_update"])
            database.close()
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore.open_existing(path, approved_root=directory)

    def test_hardlink_copy_and_lexical_alias_rejected(self):
        alias = self.root / "alias.sqlite3"
        os.link(self.path, alias)
        with self.assertRaises(TransportBoundaryError):
            with self.owner._completion_guard():
                self.fail("hardlinked database accepted")
        self.assertEqual(self.subprocess_open(alias), "rejected")
        copied = self.root / "copy.sqlite3"
        copied.write_bytes(self.path.read_bytes())
        self.assertEqual(self.subprocess_open(copied), "rejected")
        self.assertEqual(self.subprocess_open(str(self.root) + "/./program.sqlite3"), "rejected")

    def test_persistent_parent_anchor_rejects_same_inode_relocation(self):
        parent = self.root / "parent"
        parent.mkdir()
        path = parent / "program.sqlite3"
        bound = transport._ProgramTransportStore._create_completion_store(path, approved_root=self.root)
        self.addCleanup(bound.close)
        with self.assertRaises(TransportBoundaryError), bound._completion_guard():
            parent.rename(self.root / "retained-parent")
            parent.mkdir()
            (self.root / "retained-parent" / "program.sqlite3").rename(path)
            self.assertEqual(self.subprocess_open(path, self.root), "rejected")
            with self.assertRaises(TransportBoundaryError):
                bound._require_current_completion_owner()
            # Final guard attestation also rejects; preserve the invalidated owner.

    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_fork_child_rejects_inherited_handles_before_locks(self):
        read_fd, write_fd = os.pipe()
        with self.owner._completion_guard():
            with self.owner._lock:
                pid = os.fork()
                if pid == 0:
                    try:
                        os.close(read_fd)
                        rejected = 0
                        for operation in (
                            self.owner.close, self.owner._attest, self.owner._require_current_completion_owner,
                            lambda: transport._ProgramTransportStore.create_new(self.root / "child-v1.sqlite3", approved_root=self.root),
                            lambda: transport._ProgramTransportStore._create_completion_store(self.root / "child-v2.sqlite3", approved_root=self.root),
                            lambda: transport._ProgramTransportStore.open_existing(self.path, approved_root=self.root),
                        ):
                            try:
                                operation()
                            except TransportBoundaryError:
                                rejected += 1
                        os.write(write_fd, str(rejected).encode())
                    finally:
                        os._exit(0)
                os.close(write_fd)
                self.assertEqual(os.read(read_fd, 8), b"6")
                os.close(read_fd)
                self.assertEqual(os.waitpid(pid, 0)[1], 0)
                self.assertFalse((self.root / "child-v1.sqlite3").exists())
                self.assertFalse((self.root / "child-v2.sqlite3").exists())
                self.assertEqual(self.subprocess_open(), "rejected")
        self.assertEqual(self.subprocess_open(), "acquired")

    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_abrupt_owner_exit_with_living_fork_child_releases_lock(self):
        code = """
import os,sys,json
from auto_g16.transport.program import _ProgramTransportStore
value = _ProgramTransportStore.open_existing(sys.argv[1], approved_root=sys.argv[2])
with value._completion_guard():
    r,w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        os.write(w,b'ready')
        os.close(w)
        os.read(int(sys.argv[3]),1)
        os._exit(0)
    os.close(w)
    assert os.read(r,5)==b'ready'
    os.close(r)
    os.close(int(sys.argv[3]))
    print(json.dumps({'child_pid':pid}),flush=True)
    sys.stdin.read(1)
    os._exit(77)
"""
        read_fd, write_fd = os.pipe()
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.path), str(self.root), str(read_fd)], pass_fds=(read_fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        os.close(read_fd)
        try:
            child = json.loads(holder.stdout.readline())["child_pid"]
            self.assertEqual(self.subprocess_open(), "rejected")
            holder.stdin.write("x"); holder.stdin.flush()
            self.assertEqual(holder.wait(timeout=10), 77)
            os.kill(child, 0)
            self.assertEqual(self.subprocess_open(), "acquired")
        finally:
            os.write(write_fd, b"x"); os.close(write_fd)
            holder.stdin.close(); holder.stdout.close()


    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_real_exec_restores_fork_child_store_open(self):
        code = """
import sys
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.transport._canonical import TransportBoundaryError
try:
    value=_ProgramTransportStore.open_existing(sys.argv[1],approved_root=sys.argv[2])
    value.close()
    print('acquired',flush=True)
except TransportBoundaryError:
    print('rejected',flush=True)
"""
        def fork_exec():
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(read_fd)
                    os.dup2(write_fd, 1)
                    os.close(write_fd)
                    os.execv(sys.executable, [sys.executable, "-c", code, str(self.path), str(self.root)])
                finally:
                    os._exit(91)
            os.close(write_fd)
            result = os.read(read_fd, 100)
            os.close(read_fd)
            self.assertEqual(os.waitpid(pid, 0)[1], 0)
            return result.strip()
        with self.owner._completion_guard():
            self.assertEqual(fork_exec(), b"rejected")
        self.assertEqual(fork_exec(), b"acquired")

    def test_close_admission_race_rechecks_after_lock(self):
        original = self.owner._lock
        entered, proceed = threading.Event(), threading.Event()
        errors = []
        class AdmissionLock:
            def __enter__(inner):
                if threading.current_thread().name == "inert-close-contender":
                    entered.set()
                    if not proceed.wait(10):
                        raise AssertionError("test rendezvous timed out")
                original.acquire()
                return inner
            def __exit__(inner, *args):
                original.release()
        def close_contender():
            try:
                self.owner.close()
            except TransportBoundaryError:
                errors.append(True)
        with patch.object(self.owner, "_lock", AdmissionLock()):
            thread = threading.Thread(target=close_contender, name="inert-close-contender")
            thread.start()
            self.assertTrue(entered.wait(10))
            with self.owner._completion_guard():
                proceed.set(); thread.join(10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [True])
                self.assertFalse(self.owner._closed)
        self.owner._attest()

    def test_factory_teardown_failure_closes_connection_and_keeps_artifact(self):
        captured = []
        original_open = transport._ProgramTransportStore._open
        original_flock = fcntl.flock
        def observe(*args, **kwargs):
            value = original_open(*args, **kwargs)
            captured.append(value)
            return value
        def fail_unlock(fd, operation):
            original_flock(fd, operation)
            if operation == fcntl.LOCK_UN:
                raise OSError("inert release failure")
        fresh = self.root / "retained.sqlite3"
        with patch.object(transport._ProgramTransportStore, "_open", side_effect=observe), patch("fcntl.flock", side_effect=fail_unlock):
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore._create_completion_store(fresh, approved_root=self.root)
        self.assertTrue(fresh.exists())
        self.assertTrue(captured and all(value._closed for value in captured))
        captured.clear()
        with patch.object(transport._ProgramTransportStore, "_open", side_effect=observe), patch("fcntl.flock", side_effect=fail_unlock):
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore.open_existing(fresh, approved_root=self.root)
        self.assertTrue(captured and all(value._closed for value in captured))

    def test_ancestor_symlink_and_replacement_are_not_rebound(self):
        ancestor = self.root / "ancestor"
        parent = ancestor / "parent"
        parent.mkdir(parents=True)
        path = parent / "program.sqlite3"
        value = transport._ProgramTransportStore._create_completion_store(path, approved_root=self.root)
        self.addCleanup(value.close)
        saved = self.root / "retained-ancestor"
        ancestor.rename(saved)
        ancestor.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(TransportBoundaryError):
            transport._ProgramTransportStore.open_existing(path, approved_root=self.root)
        with self.assertRaises(TransportBoundaryError):
            with value._completion_guard():
                self.fail("symlink ancestor entered")
        alias = str(saved / "parent" / "program.sqlite3")
        self.assertEqual(self.subprocess_open(alias, self.root), "rejected")
