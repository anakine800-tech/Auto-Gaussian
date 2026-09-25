"""C2 incremental recovery: real SQLite/guard/driver, inert final wire peer only."""
from contextlib import ExitStack
from dataclasses import replace
from dataclasses import fields, is_dataclass
from hashlib import sha256
from pathlib import Path
import copy
import json
import os
import sys
import unittest
import subprocess
import sqlite3
import tempfile
import threading
import base64
from unittest.mock import patch

from auto_g16 import approval, core, execution
from auto_g16.execution import program as p, program_runtime as runtime
from auto_g16.execution import _program_completion as c
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal, _ProjectProvisioningService
from auto_g16.transport import _program_rtwin as rtwin, _driver, _bridge, program as transport
from auto_g16.transport._canonical import TransportBoundaryError, canonical_json_bytes
from scripts import run_v31_publisher_pilot as controller
from tests.v3.execution import test_v31_lane_a as lane
from tests.v3.transport import _fixtures as v30
from tests.v31.transport import test_publisher_pilot_orchestration as pilot
from tests.v31.transport import test_rtwin_successor_bridge as bridge_tests


EXPIRED = {"started_at": "2000-01-01T00:00:00.000000Z", "finished_at": "2001-01-01T00:00:00.000000Z"}


class _RecoveryFixture(lane.LaneAFixture):
    split_store_roots = False

    def resolved(self, **kwargs):
        if hasattr(self, "current_profile"):
            return execution.resolve_server_profile(self.current_profile)
        return super().resolved(**kwargs)

    def resources(self):
        return execution.ResolvedResourceRequest(resource_spec=self.store.load_resource_spec("resource-1"), cores=8, memory_mb=12288, walltime_seconds=3600, queue="batch")

    def setUp(self):
        super().setUp()
        fixture = v30.TransportFixture(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = fixture.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        manifest = json.loads(raw.runtime_contents["transport-deployment-manifest-v2.json"])
        manifest.update(schema="auto-g16-v3-transport-deployment-manifest/3", bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
        manifest["trust_roots"] = {k: v for k, v in manifest["trust_roots"].items() if k in c._ROOT_RULES}
        self.current_profile = replace(raw, platform_paths={**raw.platform_paths, "xtb_executable_path": "/opt/xtb/6.7.1/bin/xtb", "xtb_data_path": "/opt/xtb/6.7.1/share/xtb"},
            runtime_contents={_driver._TABLE_NAME: _driver._OPERATION_TABLE_BYTES, _driver._RESOURCE_DESCRIPTOR_NAME: v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES,
                              c._DEPLOYMENT_NAME: canonical_json_bytes(manifest), _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME: _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES,
                              "xtb": b"inert exact binary image", c._DATA_NAME: lane.xtb_runtime_data_manifest_bytes()})
        self.q, _ = pilot.qualification_fixture(self.current_profile, queue="batch")
        self.current_profile = replace(self.current_profile, runtime_contents={**self.current_profile.runtime_contents, c._Q_NAME: pilot.seal(self.q)})
        self.wire = bridge_tests._Wire()
        # This peer calls actual _prepare_program_invocation then replies with
        # framed synthetic bytes. No _wire_call or authority check is replaced.
        self.wire_patch = patch.object(_driver._SubprocessRTWinDriver, "_run", side_effect=self.wire.run)
        self.wire_patch.start(); self.addCleanup(self.wire_patch.stop)
        folder = self.root / "durable"; folder.mkdir()
        self.journal_root = self.root / "journal-root" if self.split_store_roots else self.root
        if self.split_store_roots:
            self.journal_root.mkdir()
        journal_path = self.journal_root / "projects.sqlite3" if self.split_store_roots else folder / "projects.sqlite3"
        self.journal = _ProductionProvisioningJournal.create_new(journal_path, approved_root=self.journal_root)
        self.addCleanup(self.journal.close)
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(folder / "program.sqlite3", approved_root=self.root)
        self.addCleanup(self.program_transport_store.close)
        self.service = _ProjectProvisioningService._from_project_attestor(
            attestor=rtwin._RTWinProjectAttestor(current_profile=self.current_profile, target=self.resolved()), target=self.resolved(), journal=self.journal)
        self.project_binding = self.service.provision_remote_project(project=self.store.load_project("project-1"), target=self.resolved(), remote_project_dir=self.remote_project_dir)
        self.snapshot_service = p._ProgramExecutionSnapshotService._for_production(project_provisioning=self.service, target=self.resolved())
        self.spec = p._prepare_program_execution_spec(program_kind="xtb", executable_path=self.current_profile.platform_paths["xtb_executable_path"],
                    executable_size_bytes=len(self.current_profile.runtime_contents["xtb"]), executable_sha256=sha256(self.current_profile.runtime_contents["xtb"]).hexdigest(),
                    input_name="input.xyz", input_bytes=lane.XYZ, program_data=self.xtb_data(), resolved_profile=self.resolved(), completion_mode=c._MODE)
        self.material = c._prepare_publisher_pilot_rendering_material(self.current_profile, self.resolved())
        self.snapshot = pilot._PilotFixture.make_snapshot(self, self.material)
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}
        with patch.object(pilot, "PILOT", EXPIRED):
            self.original, _authority, self.original_run, self.confirmation = pilot._PilotFixture.install_fixture(self)
        # Build historical synthetic submitted state; expiry is bypassed only in
        # setup, never in restoration/collection/replay or a production process.
        with patch.object(rtwin, "_FIXED_PUBLISHER_INSTALLATION", self.original), patch.object(controller, "_FIXED_PILOT_RUN", self.original_run), patch.object(rtwin, "_publisher_window", return_value=None):
            controller._run_first_publisher_pilot()
        self.wire.calls.clear()
        self.wire.scheduler = (153, b"", b"qstat: Unknown Job Id Error 123.server\n")
        receipt = dict(c._receipt_binding(self.snapshot, "123.server", bridge_tests.directory_token(self.snapshot.workspace_binding.remote_attempt_dir)))
        receipt.update(termination={"kind": "exited", "returncode": 0, "signal": None}, finished_at="2001-01-02T00:00:00.000000Z", outputs=[])
        for declaration in (*self.spec.required_outputs, *self.spec.optional_outputs):
            raw = self.wire.outputs.get(declaration["portable_name"])
            receipt["outputs"].append({**{k: declaration[k] for k in ("logical_role", "portable_name", "format")},
                                      "presence": "present" if raw is not None else "absent", "size_bytes": len(raw) if raw else None, "sha256": sha256(raw).hexdigest() if raw else None})
        self.wire.outputs["v31-completion.json"] = c._receipt_json(receipt)
        self.recovery_root = self.root / "recovery"; self.recovery_root.mkdir()
        self.run, self.installation, self.document = self.install_recovery()

    def write(self, name, raw):
        path = self.recovery_root / name
        with path.open("xb") as out:
            out.write(raw)
        return pilot.file_binding(path)

    def install_recovery(self):
        databases = tuple(controller._CollectionDatabaseBinding(b.role, b.path, b.parent_chain, b.file_identity) for b in self.original_run.stores)
        jb = pilot.file_binding(Path(self.journal._path))
        databases += (controller._CollectionDatabaseBinding("project-journal", jb.path, jb.parent_chain, jb.file_identity),)
        snapshot_pin = self.write("snapshot.json", c._receipt_json(self.snapshot._approval_semantics()))
        run = controller._FixedCollectionRun(self.current_profile, databases, str(self.root), snapshot_pin,
                self.write("input.xyz", lane.XYZ), self.write(self.snapshot.scheduler_artifacts[0]["portable_name"], self.scheduler_bytes[self.snapshot.scheduler_artifacts[0]["portable_name"]]),
                self.original_run.reviewed_semantics, {"intent": "inert"})
        if getattr(self, "split_store_roots", False):
            run = replace(run, project_journal_root=str(self.journal_root))
        root = Path(controller.__file__).resolve().parents[1]
        code_paths = {Path(module.__file__).resolve() for name, module in tuple(sys.modules.items()) if (name == "auto_g16" or name.startswith("auto_g16.")) and getattr(module, "__file__", None)}
        code_paths.add(Path(controller.__file__).resolve())
        code = tuple(pilot.file_binding(path) for path in sorted(code_paths))
        source = {"commit": "c"*40, "tree": "d"*40, "files": [{"path": str(Path(b.path).relative_to(root)), "sha256": b.sha256, "size_bytes": b.size_bytes} for b in code]}
        # Original native runtime binding is loaded without a new attestation.
        with patch.object(rtwin, "_FIXED_PUBLISHER_INSTALLATION", self.original), patch.object(rtwin, "_publisher_window", return_value=None):
            driver = rtwin._RTWinProgramEffectDriver(snapshot=self.snapshot, current_profile=self.current_profile, program_transport_store=self.program_transport_store)
            try:
                base = runtime._snapshot_binding(self.snapshot, self.program_transport_store, driver)
            finally:
                driver.close()
        evidence = (self.write("owner.txt", b"inert accepted continuation\n"), self.write("source-review.txt", b"inert accepted collector delta\n"))
        document = {"schema": rtwin._COLLECTION_SCHEMA,
                    "original": {"attempt_id": self.snapshot.attempt_id, "snapshot_id": self.snapshot.program_execution_snapshot_id,
                                 "effect_intent_id": self.snapshot.effect_intent_id, "job_id": "123.server", "project_physical_binding_id": self.snapshot.project_physical_binding_id,
                                 "resolved_server_profile_id": self.resolved().resolved_server_profile_id, "original_basis_sha256": self.original.basis.sha256,
                                 "snapshot_semantics_sha256": snapshot_pin.sha256, "scientific_approval_id": self.original_run.scientific_approval_id,
                                 "batch_submit_approval_id": self.original_run.batch_submit_approval_id, "operational_confirmation_id": self.original_run.operational_confirmation_id},
                    "stores": controller._collection_store_identity(run, {"project-journal": self.journal}, base), "collector_source": source,
                    "original_source": {"commit": "a"*40, "tree": "b"*40, "wrapper_source": self.q["implementation"]["wrapper_source"],
                                        "qualification_file_sha256": self.original.qualification.sha256, "qualification_payload_sha256": json.loads(pilot.seal(self.q))["payload_sha256"]},
                    "window": pilot.PILOT, "scope": {"action": "collect-existing-job", "maximum_remote_epochs": 1,
                        "operations": list(rtwin._COLLECTION_OPERATIONS), "files": ["v31-completion.json", *(v["portable_name"] for v in self.spec.required_outputs), *(v["portable_name"] for v in self.spec.optional_outputs)], "local_replay": True},
                    "review_evidence": {role: {"sha256": pin.sha256, "size_bytes": pin.size_bytes} for role, pin in zip(("owner_continuation", "source_compatibility"), evidence)}}
        scope_hash = c.semantic_sha256(c.freeze_mapping({k: v for k, v in document.items() if k != "review_evidence"}, "scope"))
        reviewed = {"schema": "v31-collection-reviewed-scope/1", **{role: {"raw": value, "scope_sha256": scope_hash} for role, value in document["review_evidence"].items()}}
        installation = rtwin._FixedCollectionInstallation(self.write("continuation.json", canonical_json_bytes(document)), self.write("scope.json", canonical_json_bytes(reviewed)), evidence, str(root), code, "c"*40, "d"*40)
        return run, installation, document

    def resume(self, run=None, installation=None):
        with patch.object(rtwin, "_FIXED_PUBLISHER_INSTALLATION", self.original), patch.object(rtwin, "_FIXED_COLLECTION_INSTALLATION", installation or self.installation), patch.object(controller, "_FIXED_COLLECTION_RUN", run or self.run), patch.object(_driver.subprocess, "Popen", side_effect=AssertionError("no process")):
            return controller._resume_fixed_publisher_collection()

    def changed_installation(self, mutate):
        document = copy.deepcopy(self.document)
        mutate(document)
        ordinal = len(tuple(self.recovery_root.iterdir()))
        binding = self.write(f"changed-{ordinal}.json", canonical_json_bytes(document))
        scope_hash = c.semantic_sha256(c.freeze_mapping({k: v for k, v in document.items() if k != "review_evidence"}, "scope"))
        reviewed = {"schema": "v31-collection-reviewed-scope/1", **{role: {"raw": value, "scope_sha256": scope_hash} for role, value in document["review_evidence"].items()}}
        return replace(self.installation, continuation=binding, reviewed_scope=self.write(f"changed-scope-{ordinal}.json", canonical_json_bytes(reviewed)))

    def export_state(self, path):
        value = {"run": self.run, "installation": self.installation, "original": self.original, "outputs": self.wire.outputs}
        Path(path).write_text(json.dumps(_pack(value)))


_TEST_TYPES = {cls.__name__: cls for cls in (execution.ServerProfile, rtwin._PublisherFileBinding, rtwin._FixedPublisherInstallation,
                rtwin._FixedCollectionInstallation, controller._CollectionDatabaseBinding, controller._FixedCollectionRun)}


def _pack(value):
    if is_dataclass(value):
        return {"fixture_type": type(value).__name__, "fields": {f.name: _pack(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, bytes):
        return {"fixture_bytes": base64.b64encode(value).decode()}
    if isinstance(value, tuple):
        return {"fixture_tuple": [_pack(v) for v in value]}
    if isinstance(value, list):
        return [_pack(v) for v in value]
    if isinstance(value, dict):
        return {k: _pack(v) for k, v in value.items()}
    return value


def _unpack(value):
    if isinstance(value, list):
        return [_unpack(v) for v in value]
    if isinstance(value, dict):
        if set(value) == {"fixture_type", "fields"}:
            return _TEST_TYPES[value["fixture_type"]](**{k: _unpack(v) for k, v in value["fields"].items()})
        if set(value) == {"fixture_bytes"}:
            return base64.b64decode(value["fixture_bytes"])
        if set(value) == {"fixture_tuple"}:
            return tuple(_unpack(v) for v in value["fixture_tuple"])
        return {k: _unpack(v) for k, v in value.items()}
    return value


def _next_process_installation(installation):
    document = json.loads(Path(installation.continuation.path).read_text())
    document["window"]["started_at"] = "2000-01-01T00:00:00.000001Z"
    root = Path(installation.continuation.path).parent

    def exact_file(name, raw):
        path = root / name
        if path.exists():
            if path.read_bytes() != raw:
                raise AssertionError("next-process installation bytes differ")
        else:
            with path.open("xb") as out:
                out.write(raw)
        return pilot.file_binding(path)

    continuation = exact_file(
        "next-process-continuation.json", canonical_json_bytes(document)
    )
    scope_hash = c.semantic_sha256(
        c.freeze_mapping(
            {key: value for key, value in document.items() if key != "review_evidence"},
            "scope",
        )
    )
    reviewed = {
        "schema": "v31-collection-reviewed-scope/1",
        **{
            role: {"raw": value, "scope_sha256": scope_hash}
            for role, value in document["review_evidence"].items()
        },
    }
    return replace(
        installation,
        continuation=continuation,
        reviewed_scope=exact_file(
            "next-process-reviewed-scope.json", canonical_json_bytes(reviewed)
        ),
    )


def _process_entry(mode, path):
    """Only synthetic fixture processes, with no real wire or scientific child."""
    if mode in {"build", "build-split"}:
        fixture = _RecoveryFixture()
        fixture.split_store_roots = mode == "build-split"
        fixture.setUp()
        fixture.export_state(path)
        # The parent owns a finite outer TemporaryDirectory. Abrupt process exit
        # deliberately preserves these synthetic stores and releases real locks.
        os._exit(0)
    state = _unpack(json.loads(Path(path).read_text()))
    selected_installation = (
        _next_process_installation(state["installation"])
        if mode == "resume-next"
        else state["installation"]
    )
    wire = bridge_tests._Wire(); wire.outputs = state["outputs"]
    wire.scheduler = (153, b"", b"qstat: Unknown Job Id Error 123.server\n")
    with ExitStack() as stack:
        for target, name, value in ((rtwin, "_FIXED_PUBLISHER_INSTALLATION", state["original"]),
                                    (rtwin, "_FIXED_COLLECTION_INSTALLATION", selected_installation),
                                    (controller, "_FIXED_COLLECTION_RUN", state["run"])):
            stack.enter_context(patch.object(target, name, value))
        stack.enter_context(patch.object(_driver._SubprocessRTWinDriver, "_run", side_effect=wire.run))
        stack.enter_context(patch.object(_driver.subprocess, "Popen", side_effect=AssertionError("no live process")))
        if mode.startswith("crash-"):
            phase = mode[6:]
            append_observation, append_result, advance = core.SQLiteRuntimeStore.append_observation, core.SQLiteRuntimeStore.append_result, core.SQLiteRuntimeStore.advance_attempt
            def observation(store, record):
                if phase == "before-audit" and record.observation_type == runtime._COLLECTION_START:
                    os._exit(17)
                append_observation(store, record)
                if (phase == "audit" and record.observation_type == runtime._COLLECTION_START) or (phase == "assessment" and record.observation_type == runtime._COMPLETION_ASSESSMENT):
                    os._exit(17)
                if (
                    phase == "after-present-stat"
                    and record.observation_type == transport._RECEIPT_TYPE
                    and record.data.get("operation") == "STAT_EXACT_FILE"
                    and record.data.get("outcome") == "SUCCEEDED"
                    and record.data.get("response", {}).get("presence") == "present"
                    and record.data.get("response", {}).get("portable_name")
                    != "v31-completion.json"
                ):
                    os._exit(17)
            def result(store, record):
                if phase == "before-result":
                    os._exit(17)
                append_result(store, record)
                if phase == "result":
                    os._exit(17)
            def transition(store, *args):
                value = advance(store, *args)
                if phase == "transition":
                    os._exit(17)
                return value
            stack.enter_context(patch.object(core.SQLiteRuntimeStore, "append_observation", observation))
            stack.enter_context(patch.object(core.SQLiteRuntimeStore, "append_result", result))
            stack.enter_context(patch.object(core.SQLiteRuntimeStore, "advance_attempt", transition))
            if phase == "wire":
                def wire_exit(*args, **kwargs):
                    wire.run(*args, **kwargs)
                    os._exit(17)
                stack.enter_context(patch.object(_driver._SubprocessRTWinDriver, "_run", side_effect=wire_exit))
        try:
            result = controller._resume_fixed_publisher_collection()
            result = {"assessment": result.observation_id, "verdict": result.data["verdict"],
                      "capture_authority_id": result.data["capture_authority_id"], "evidence_result_id": result.data["evidence_result_id"]}
        except (TransportBoundaryError, execution.ExecutionValueError) as exc:
            result = {"rejected": str(exc)}
        connection = sqlite3.connect(Path(state["run"].databases[0].path).as_uri() + "?mode=ro", uri=True)
        try:
            persisted = {"results": connection.execute("SELECT result_id,data FROM results ORDER BY sequence").fetchall(),
                         "observation_count": connection.execute("SELECT count(*) FROM observations").fetchone()[0],
                         "audit_count": connection.execute("SELECT count(*) FROM observations WHERE observation_type=?", (runtime._COLLECTION_START,)).fetchone()[0],
                         "state": connection.execute("SELECT state FROM attempts").fetchone()[0]}
        finally:
            connection.close()
        persisted["four_store_counts"] = {}
        for binding in state["run"].databases:
            connection = sqlite3.connect(Path(binding.path).as_uri() + "?mode=ro", uri=True)
            try:
                names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                persisted["four_store_counts"][binding.role] = {name: connection.execute('SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in names}
            finally:
                connection.close()
        if mode == "resume-next":
            result["wire_operations"] = [operation for operation, _request in wire.calls]
        print(json.dumps({**result, "persisted": persisted, "wire_calls": len(wire.calls)}), flush=True)


def _child(mode, path, *, scratch=None):
    environment = dict(os.environ)
    if scratch is not None:
        environment["TMPDIR"] = str(scratch)
    result = subprocess.run([sys.executable, "-m", "tests.v31.transport.test_publisher_collection_recovery", mode, str(path)],
                            env=environment, capture_output=True, text=True, timeout=120)
    if result.returncode not in {0, 17}:
        raise AssertionError(result.stdout + result.stderr)
    return result


class CollectionRecoveryTests(_RecoveryFixture):
    def test_artifact_module_requires_inventory_and_actual_loaded_path(self):
        from auto_g16.execution import _program_artifacts
        artifact_path = str(Path(_program_artifacts.__file__).resolve())
        rtwin._collection_source_files(self.installation, self.document)
        files = tuple(binding for binding in self.installation.code_files if binding.path != artifact_path)
        self.assertEqual(len(files), len(self.installation.code_files) - 1)
        document = copy.deepcopy(self.document)
        document["collector_source"]["files"] = [item for item in document["collector_source"]["files"]
            if item["path"] != "auto_g16/execution/_program_artifacts.py"]
        with self.assertRaisesRegex(TransportBoundaryError, "collection owner code is not pinned"):
            rtwin._collection_source_files(replace(self.installation, code_files=files), document)
        with patch.object(_program_artifacts, "__file__", str(self.root / "unreviewed.py")):
            with self.assertRaisesRegex(TransportBoundaryError, "unreviewed collection import"):
                rtwin._collection_source_files(self.installation, self.document)

    def _leave_present_stat_without_fetch(self):
        target = self.spec.required_outputs[0]["portable_name"]
        original = runtime._completion_file_effect

        class StopAfterStat(BaseException):
            pass

        def stop_after_stat(*args, **kwargs):
            result = original(*args, **kwargs)
            declaration = args[6]
            if kwargs.get("stat") is None and declaration["portable_name"] == target:
                raise StopAfterStat()
            return result

        with patch.object(runtime, "_completion_file_effect", side_effect=stop_after_stat):
            with self.assertRaises(StopAfterStat):
                self.resume()
        receipts = tuple(
            item
            for item in self.store.observations_for_attempt("attempt-1")
            if item.observation_type == transport._RECEIPT_TYPE
        )
        candidate = runtime._interrupted_present_stat(
            self.snapshot,
            self.store.observations_for_attempt("attempt-1"),
            receipts,
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.data["response"]["portable_name"], target)
        return target, candidate

    def _next_continuation(self):
        return self.changed_installation(
            lambda document: document["window"].update(
                started_at="2000-01-01T00:00:00.000001Z"
            )
        )

    def test_ir01_ir04_new_continuation_finishes_orphan_then_collects_clean_epoch(self):
        target, candidate = self._leave_present_stat_without_fetch()
        self.wire.calls.clear()
        result = self.resume(installation=self._next_continuation())
        self.assertEqual(result.data["verdict"], "SUCCEEDED")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertGreaterEqual(len(self.wire.calls), 2)
        self.assertEqual(self.wire.calls[0][0], "FETCH_EXACT_FILE")
        self.assertEqual(
            self.wire.calls[0][1]["payload"]["request_payload"]["portable_name"],
            target,
        )
        self.assertEqual(
            self.wire.calls[0][1]["payload"]["request_payload"]["stat_receipt_id"],
            candidate.observation_id,
        )
        self.assertEqual(self.wire.calls[1][0], "QUERY_SCHEDULER")
        self.wire.calls.clear()
        self.assertEqual(self.resume(installation=self._next_continuation()), result)
        self.assertEqual(self.wire.calls, [])

    def test_ir05_failed_repair_consumes_only_new_continuation(self):
        _target, candidate = self._leave_present_stat_without_fetch()
        continuation = self._next_continuation()
        self.wire.calls.clear()
        self.wire.fail_operation = "FETCH_EXACT_FILE"
        with self.assertRaises(Exception):
            self.resume(installation=continuation)
        self.assertEqual([item[0] for item in self.wire.calls], ["FETCH_EXACT_FILE"])
        receipts = tuple(
            item
            for item in self.store.observations_for_attempt("attempt-1")
            if item.observation_type == transport._RECEIPT_TYPE
        )
        self.assertEqual(
            runtime._interrupted_present_stat(
                self.snapshot,
                self.store.observations_for_attempt("attempt-1"),
                receipts,
            ),
            candidate,
        )
        self.wire.calls.clear()
        with self.assertRaisesRegex(TransportBoundaryError, "already consumed"):
            self.resume(installation=continuation)
        self.assertEqual(self.wire.calls, [])

    def test_ir01_ir06_selector_rejects_ambiguous_or_malformed_prefix(self):
        _target, candidate = self._leave_present_stat_without_fetch()
        observations = self.store.observations_for_attempt("attempt-1")
        receipts = tuple(
            item for item in observations if item.observation_type == transport._RECEIPT_TYPE
        )
        duplicate = core.Observation(
            observation_id="duplicate-unmatched-stat",
            attempt_id=candidate.attempt_id,
            observation_type=candidate.observation_type,
            data=candidate.data,
        )
        with self.assertRaisesRegex(TransportBoundaryError, "malformed or ambiguous"):
            runtime._interrupted_present_stat(
                self.snapshot, (*observations, duplicate), (*receipts, duplicate)
            )
        malformed = core.Observation(
            observation_id="malformed-fetch",
            attempt_id=candidate.attempt_id,
            observation_type=candidate.observation_type,
            data={**candidate.data, "operation": "FETCH_EXACT_FILE"},
        )
        with self.assertRaisesRegex(TransportBoundaryError, "malformed or ambiguous"):
            runtime._interrupted_present_stat(
                self.snapshot, (*observations, malformed), (*receipts, malformed)
            )
        absent = core.Observation(
            observation_id="unmatched-absent-stat",
            attempt_id=candidate.attempt_id,
            observation_type=candidate.observation_type,
            data={
                **candidate.data,
                "response": {
                    "portable_name": candidate.data["response"]["portable_name"],
                    "presence": "absent",
                },
            },
        )
        replaced_observations = tuple(
            absent if item == candidate else item for item in observations
        )
        replaced_receipts = tuple(absent if item == candidate else item for item in receipts)
        with self.assertRaisesRegex(TransportBoundaryError, "malformed or ambiguous"):
            runtime._interrupted_present_stat(
                self.snapshot, replaced_observations, replaced_receipts
            )
        binding = dict(candidate.data["request"]["binding"])
        expected_job = binding["job_authority_id"]
        binding["job_authority_id"] = "foreign-job-authority"
        foreign_request = {**candidate.data["request"], "binding": binding}
        foreign = core.Observation(
            observation_id="foreign-job-stat",
            attempt_id=candidate.attempt_id,
            observation_type=candidate.observation_type,
            data={**candidate.data, "request": foreign_request},
        )
        replaced_observations = tuple(
            foreign if item == candidate else item for item in observations
        )
        replaced_receipts = tuple(
            foreign if item == candidate else item for item in receipts
        )
        with self.assertRaisesRegex(TransportBoundaryError, "malformed or ambiguous"):
            runtime._interrupted_present_stat(
                self.snapshot,
                replaced_observations,
                replaced_receipts,
                expected_job_authority_id=expected_job,
            )
        conflicting_request = {
            **candidate.data["request"],
            "operation": "FETCH_EXACT_FILE",
            "payload": {
                **candidate.data["request"]["payload"],
                "stat_receipt_id": candidate.observation_id,
            },
        }
        conflicting = core.Observation(
            observation_id="conflicting-fetch",
            attempt_id=candidate.attempt_id,
            observation_type=candidate.observation_type,
            data={
                **candidate.data,
                "operation": "FETCH_EXACT_FILE",
                "outcome": "UNKNOWN",
                "request": conflicting_request,
                "response": {"reason": "ambiguous-operation-outcome"},
            },
        )
        with self.assertRaisesRegex(TransportBoundaryError, "malformed or ambiguous"):
            runtime._interrupted_present_stat(
                self.snapshot,
                (*observations, conflicting),
                (*receipts, conflicting),
            )

    def test_cr01_cr03_native_restore_expired_window_collect_and_zero_wire_replay(self):
        old_approval = Path(self.original_run.stores[1].path).read_bytes()
        journal = Path(self.journal._path).read_bytes()
        with patch.object(rtwin, "_FIXED_PUBLISHER_INSTALLATION", self.original), self.assertRaisesRegex(TransportBoundaryError, "window|ingestion"):
            rtwin._RTWinProgramEffectDriver(snapshot=self.snapshot, current_profile=self.current_profile, program_transport_store=self.program_transport_store)
        result = self.resume()
        self.assertEqual(result.data["verdict"], "SUCCEEDED")
        self.assertEqual(len(self.wire.calls), 11)
        self.assertEqual({op for op, _ in self.wire.calls}, set(rtwin._COLLECTION_OPERATIONS))
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        before = self.store.observations_for_attempt("attempt-1"), self.store.results_for_attempt("attempt-1")
        self.wire.calls.clear()
        self.assertEqual(self.resume(), result)
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(before, (self.store.observations_for_attempt("attempt-1"), self.store.results_for_attempt("attempt-1")))
        self.assertEqual(old_approval, Path(self.original_run.stores[1].path).read_bytes())
        self.assertEqual(journal, Path(self.journal._path).read_bytes())

    def test_cr02_refuses_unsubmitted_uncertain_and_terminal_without_bundle(self):
        before = self.store.observations_for_attempt("attempt-1")
        for state in ("PLANNED", "SUBMISSION_INTENT_RECORDED", "UNKNOWN", "NOT_SUBMITTED", "SUCCEEDED", "FAILED"):
            with self.subTest(state=state):
                self.store._connection.execute("UPDATE attempts SET state=?", (state,))  # adversarial synthetic store only
                with self.assertRaises((execution.ExecutionValueError, TransportBoundaryError)):
                    self.resume()
                self.assertEqual(self.wire.calls, [])
                self.assertEqual(before, self.store.observations_for_attempt("attempt-1"))
        self.store._connection.execute("UPDATE attempts SET state='SUBMITTED'")
        with self.assertRaisesRegex(execution.ExecutionValueError, "fresh unconsumed"):
            pilot._PilotFixture.make_snapshot(self, self.material)

    def test_cr03_cr04_closed_scope_window_and_source_mismatches(self):
        mutations = (
            lambda d: d.update(window=EXPIRED),
            lambda d: d.update(window={"started_at": "2999-01-01T00:00:00.000000Z", "finished_at": "2999-01-02T00:00:00.000000Z"}),
            lambda d: d.update(window={"started_at": "malformed", "finished_at": "malformed"}),
            lambda d: d["scope"]["files"].pop(),
            lambda d: d["scope"]["files"].reverse(),
            lambda d: d["scope"].update(maximum_remote_epochs=True),
            lambda d: d["scope"]["operations"].append("SUBMIT_QSUB_ONCE"),
            lambda d: d["original"].update(snapshot_id="foreign"),
            lambda d: d["original_source"].update(commit="c"*40),
            lambda d: d["collector_source"].update(tree="e"*40),
            lambda d: d["stores"][2].update(store_instance_id="foreign"),
            lambda d: d["original"].update(scientific_approval_id="missing"),
            lambda d: d["stores"][3].update(journal_identity="foreign"),
        )
        before = self.store.observations_for_attempt("attempt-1")
        for mutate in mutations:
            with self.subTest(mutation=mutate), self.assertRaises(Exception):
                self.resume(installation=self.changed_installation(mutate))
            self.assertEqual(self.wire.calls, [])
            self.assertEqual(before, self.store.observations_for_attempt("attempt-1"))

    def test_cr02_missing_intent_outcome_and_reconciled_history_reject(self):
        before = self.store.observations_for_attempt("attempt-1")
        connection = self.store._connection
        outcome = connection.execute("SELECT * FROM submission_outcomes").fetchone()
        intent = connection.execute("SELECT * FROM submission_intents").fetchone()
        # Remove and restore only this isolated synthetic fixture's rows.
        connection.execute("DELETE FROM submission_outcomes")
        with self.assertRaises(Exception):
            self.resume()
        connection.execute("DELETE FROM submission_intents")
        with self.assertRaises(Exception):
            self.resume()
        connection.execute("INSERT INTO submission_intents VALUES (?,?)", intent)
        connection.execute("INSERT INTO submission_outcomes VALUES (?,?,?)", outcome)
        self.assertEqual(before, self.store.observations_for_attempt("attempt-1"))
        self.store.append_observation(core.Observation(observation_id="inert-reconcile", attempt_id="attempt-1", observation_type=transport._RECEIPT_TYPE, data={"operation": "RECONCILE_SUBMISSION"}))
        with self.assertRaisesRegex(execution.ExecutionValueError, "original successful submission"):
            self.resume()
        self.assertEqual(self.wire.calls, [])

    def test_cr02_running_admission_uses_original_submission(self):
        self.store._connection.execute("UPDATE attempts SET state='RUNNING'")
        self.assertEqual(self.resume().data["verdict"], "SUCCEEDED")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM submission_intents").fetchone()[0], 1)

    def test_cr04_rebound_wrong_input_and_pbs_refuse_before_audit(self):
        before = self.store.observations_for_attempt("attempt-1")
        for field in ("prepared_input", "pbs_script"):
            with self.subTest(field=field), self.assertRaises((TransportBoundaryError, execution.ExecutionValueError)):
                self.resume(run=replace(self.run, **{field: self.write(field + "-wrong", b"wrong original bytes\n")}))
            self.assertEqual(self.wire.calls, [])
            self.assertEqual(before, self.store.observations_for_attempt("attempt-1"))

    def test_cr04_same_bytes_new_inode_missing_and_symlink_no_create(self):
        binding = self.run.databases[0]
        missing = str(self.root / "must-not-create.sqlite3")
        bad = replace(binding, path=missing)
        with self.assertRaises((OSError, TransportBoundaryError)):
            self.resume(run=replace(self.run, databases=(bad, *self.run.databases[1:])))
        self.assertFalse(Path(missing).exists())
        original = Path(binding.path); retained = original.with_suffix(".retained")
        original.rename(retained)
        original.write_bytes(retained.read_bytes())
        with self.assertRaises(TransportBoundaryError):
            self.resume()
        original.rename(original.with_suffix(".copy"))
        original.symlink_to(retained)
        with self.assertRaises((OSError, TransportBoundaryError)):
            self.resume()
        self.assertEqual(self.wire.calls, [])

    def test_cr05_mutation_entrypoints_tripwire_and_original_job_identity(self):
        with patch.object(execution, "execute_once", side_effect=AssertionError("new execution")), patch.object(core.SQLiteRuntimeStore, "create_attempt", side_effect=AssertionError("new Attempt")), patch.object(rtwin._RTWinProjectAttestor, "_invoke", side_effect=AssertionError("project wire")):
            result = self.resume()
        self.assertEqual(result.data["verdict"], "SUCCEEDED")
        with patch.object(rtwin, "_FIXED_PUBLISHER_INSTALLATION", self.original), patch.object(rtwin, "_FIXED_COLLECTION_INSTALLATION", self.installation):
            driver = rtwin._RTWinProgramEffectDriver._for_fixed_collection(snapshot=self.snapshot, current_profile=self.current_profile, program_transport_store=self.program_transport_store)
            try:
                for operation in ("ALLOCATE_WORKSPACE", "STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE", "RECONCILE_SUBMISSION"):
                    for call in (lambda: driver._invoke(operation, {}), lambda: driver._invoke_owned({"operation": operation}, ())):
                        with self.assertRaisesRegex(TransportBoundaryError, "forbids"):
                            call()
            finally:
                driver.close()
        self.assertEqual(self.store._connection.execute("select count(*) from attempts").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("select count(*) from submission_intents").fetchone()[0], 1)

    def test_cr06_real_guard_rejects_thread_handle_and_process_contenders(self):
        state = self.root / "state.json"; self.export_state(state)
        errors = []
        def contender():
            try:
                self.resume()
            except TransportBoundaryError as exc:
                errors.append(str(exc))
        before = self.store.observations_for_attempt("attempt-1")
        with self.program_transport_store._completion_guard():
            thread = threading.Thread(target=contender); thread.start(); thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            child = json.loads(_child("resume", state).stdout)
            self.assertIn("rejected", child); self.assertEqual(child["wire_calls"], 0)
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(before, self.store.observations_for_attempt("attempt-1"))

    def test_cr07_audit_prefix_and_consumption_without_following_receipt(self):
        original = core.SQLiteRuntimeStore.append_observation
        class Stop(BaseException):
            pass
        def stop(store, record):
            original(store, record)
            if record.observation_type == runtime._COLLECTION_START:
                raise Stop()
        with patch.object(core.SQLiteRuntimeStore, "append_observation", stop), self.assertRaises(Stop):
            self.resume()
        self.assertEqual(self.wire.calls, [])
        observations = self.store.observations_for_attempt("attempt-1")
        audit = observations[-1]
        self.assertEqual(audit.data["observation_prefix_sha256"], runtime._observation_prefix(observations[:-1]))
        with self.assertRaisesRegex(TransportBoundaryError, "already consumed"):
            self.resume()
        self.assertEqual(observations, self.store.observations_for_attempt("attempt-1"))
        data = dict(audit.data); data["observation_prefix_sha256"] = runtime._observation_prefix(observations)
        duplicate = core.Observation(observation_id=runtime.semantic_id("program-collection-continuation-start", data), attempt_id="attempt-1", observation_type=runtime._COLLECTION_START, data=data)
        self.store.append_observation(duplicate)
        with self.assertRaisesRegex(TransportBoundaryError, "audit/history"):
            self.resume()
        self.assertEqual(self.wire.calls, [])

    def test_cr07_audit_tamper_during_wire_stops_before_receipt_and_result(self):
        before = self.store.observations_for_attempt("attempt-1")
        def tamper(*args, **kwargs):
            response = self.wire.run(*args, **kwargs)
            self.store._connection.execute("UPDATE observations SET observation_id='tampered-audit' WHERE observation_type=?", (runtime._COLLECTION_START,))
            return response
        with patch.object(_driver._SubprocessRTWinDriver, "_run", side_effect=tamper), self.assertRaisesRegex(TransportBoundaryError, "prefix changed"):
            self.resume()
        current = self.store.observations_for_attempt("attempt-1")
        self.assertEqual(current[:-1], before)
        self.assertEqual(current[-1].observation_type, runtime._COLLECTION_START)
        self.assertEqual(len(self.wire.calls), 1)
        self.assertEqual(self.store.results_for_attempt("attempt-1"), ())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)
        self.assertIsNone(runtime._COLLECTION_CHECKPOINT.get())
        self.assertIsNone(rtwin._COLLECTION_WIRE_OWNER.get())

    def test_cr07_foreign_audit_after_result_stops_assessment_and_transition(self):
        append_result = core.SQLiteRuntimeStore.append_result
        def insert(store, result):
            append_result(store, result)
            observations = store.observations_for_attempt("attempt-1")
            original = next(record for record in observations if record.observation_type == runtime._COLLECTION_START)
            data = dict(original.data)
            data.update(continuation_sha256="f"*64, observation_prefix_sha256=runtime._observation_prefix(observations))
            store.append_observation(core.Observation(observation_id=runtime.semantic_id("program-collection-continuation-start", data), attempt_id="attempt-1", observation_type=runtime._COLLECTION_START, data=data))
        with patch.object(core.SQLiteRuntimeStore, "append_result", insert), self.assertRaisesRegex(TransportBoundaryError, "audit history changed"):
            self.resume()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        self.assertFalse(any(record.observation_type == runtime._COMPLETION_ASSESSMENT for record in self.store.observations_for_attempt("attempt-1")))
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)
        self.assertIsNone(runtime._COLLECTION_CHECKPOINT.get())


class SplitRootCollectionTests(_RecoveryFixture):
    split_store_roots = True

    def test_split_roots_wrong_roots_fail_without_wire_or_store_changes(self):
        before = {binding.path: Path(binding.path).read_bytes() for binding in self.run.databases}
        cases = (
            {"project_journal_root": None},  # old shared root cannot widen this journal
            {"project_journal_root": str(self.root.parent)},
            {"store_root": str(self.journal_root), "project_journal_root": str(self.root)},
            {"store_root": str(self.root.parent)},
            {"project_journal_root": str(self.root / "missing-root")},
        )
        for roots in cases:
            with self.subTest(roots=roots):
                with self.assertRaises((execution.ExecutionValueError, TransportBoundaryError)):
                    self.resume(run=replace(self.run, **roots))
                self.assertEqual(self.wire.calls, [])
                self.assertEqual(before, {path: Path(path).read_bytes() for path in before})
        self.assertFalse((self.root / "missing-root").exists())

    def test_invalid_root_values_reject_before_store_open(self):
        for field in ("store_root", "project_journal_root"):
            for root in ("", ".", "relative/root", 1, Path(self.root)):
                with self.subTest(field=field, root=root):
                    with patch.object(sqlite3, "connect", side_effect=AssertionError("store opened")):
                        with self.assertRaisesRegex(TransportBoundaryError, "explicit absolute"):
                            self.resume(run=replace(self.run, **{field: root}))
                    self.assertEqual(self.wire.calls, [])


class CollectionProcessRecoveryTests(unittest.TestCase):
    def test_split_roots_fresh_process_restore_collect_and_zero_wire_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder).resolve() / "state.json"
            self.assertEqual(_child("build-split", state, scratch=folder).returncode, 0)
            run = _unpack(json.loads(state.read_text()))["run"]
            self.assertNotEqual(run.store_root, run.project_journal_root)
            collected = json.loads(_child("resume", state).stdout)
            self.assertEqual(collected["verdict"], "SUCCEEDED")
            self.assertEqual(collected["wire_calls"], 11)
            self.assertEqual(collected["persisted"]["state"], "SUCCEEDED")
            self.assertEqual(len(collected["persisted"]["results"]), 1)
            self.assertEqual(collected["persisted"]["audit_count"], 1)
            before = {binding.path: Path(binding.path).read_bytes() for binding in run.databases}
            replayed = json.loads(_child("resume", state).stdout)
            self.assertEqual(replayed, {**collected, "wire_calls": 0})
            self.assertEqual(before, {path: Path(path).read_bytes() for path in before})

    def test_ir07_actual_exit_after_present_stat_and_fresh_process_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder).resolve() / "state.json"
            self.assertEqual(_child("build", state, scratch=folder).returncode, 0)
            self.assertEqual(
                _child("crash-after-present-stat", state).returncode, 17
            )
            recovered = json.loads(_child("resume-next", state).stdout)
            self.assertEqual(recovered["verdict"], "SUCCEEDED")
            self.assertEqual(recovered["persisted"]["state"], "SUCCEEDED")
            self.assertGreaterEqual(len(recovered["wire_operations"]), 2)
            self.assertEqual(recovered["wire_operations"][0], "FETCH_EXACT_FILE")
            self.assertEqual(recovered["wire_operations"][1], "QUERY_SCHEDULER")
            replayed = json.loads(_child("resume", state).stdout)
            self.assertEqual(replayed["verdict"], "SUCCEEDED")
            self.assertEqual(replayed["wire_calls"], 0)

    def test_cr01_fresh_process_submission_restore_collection_and_terminal_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder).resolve() / "state.json"
            self.assertEqual(_child("build", state, scratch=folder).returncode, 0)
            collected = json.loads(_child("resume", state).stdout)
            self.assertEqual(collected["verdict"], "SUCCEEDED")
            self.assertEqual(collected["wire_calls"], 11)
            self.assertEqual(len(collected["persisted"]["results"]), 1)
            self.assertEqual(collected["persisted"]["audit_count"], 1)
            self.assertEqual(collected["persisted"]["state"], "SUCCEEDED")
            self.assertEqual(collected["evidence_result_id"], collected["persisted"]["results"][0][0])
            self.assertTrue(collected["capture_authority_id"])
            self.assertEqual(set(collected["persisted"]["four_store_counts"]), {"core", "approval", "transport", "project-journal"})
            replayed = json.loads(_child("resume", state).stdout)
            self.assertEqual(replayed, {**collected, "wire_calls": 0})

    def test_cr07_cr08_actual_exit_at_persistence_boundaries(self):
        for phase in ("before-audit", "audit", "wire", "before-result", "result", "assessment", "transition"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as folder:
                state = Path(folder).resolve() / "state.json"
                _child("build", state, scratch=folder)
                self.assertEqual(_child("crash-" + phase, state).returncode, 17)
                result = json.loads(_child("resume", state).stdout)
                self.assertEqual(result["wire_calls"], 11 if phase == "before-audit" else 0)
                if phase in {"audit", "wire", "before-result"}:
                    self.assertIn("already consumed", result["rejected"])
                    self.assertEqual(result["persisted"]["state"], "SUBMITTED")
                    self.assertEqual(result["persisted"]["results"], [])
                    self.assertEqual(result["persisted"]["audit_count"], 1)
                    self.assertEqual(json.loads(_child("resume", state).stdout), result)
                else:
                    self.assertEqual(result["verdict"], "SUCCEEDED")
                    self.assertEqual(result["persisted"]["state"], "SUCCEEDED")
                    self.assertEqual(json.loads(_child("resume", state).stdout), {**result, "wire_calls": 0})


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in {"build", "build-split", "resume", "resume-next", "crash-before-audit", "crash-audit", "crash-wire", "crash-after-present-stat", "crash-before-result", "crash-result", "crash-assessment", "crash-transition"}:
        _process_entry(sys.argv[1], sys.argv[2])
    else:
        unittest.main()
