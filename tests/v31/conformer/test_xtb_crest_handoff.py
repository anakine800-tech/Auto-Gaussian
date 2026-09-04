"""Exact-byte and splice tests for the private xTB -> CREST seed handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import unittest

import auto_g16.core as core
import auto_g16.execution as execution
from auto_g16.conformer.ingest import (
    _CrestOutputArtifactBinding,
    _ingest_crest_conformers_xyz,
    _ingest_preoptimized_crest_conformers_xyz,
    _preoptimized_crest_sampling_plan_intent,
)
from auto_g16.conformer.models import ConformerError, _payload_sha256
from auto_g16.execution.program import (
    _ProgramExecutionSnapshotService,
    _prepare_program_execution_spec,
)
from auto_g16.execution.program_runtime import (
    _assert_program_output_capture_authority,
    _capture_program_outputs,
    _execute_program_once,
)
from auto_g16.execution.project_provisioning import (
    _ProjectProvisioningService,
    _SYNTHETIC_TEST_HARNESS_PRIVILEGE,
    _SyntheticRemoteProjectAttestor,
)
from auto_g16.execution.xtb_crest_handoff import (
    _XtbCrestSeedHandoff,
    _build_xtb_crest_seed_handoff,
)
from auto_g16.transport.program import (
    _PROGRAM_STORE_TRIGGERS,
    _ProgramEffectDriver,
    _ProgramOutputArtifact,
    _ProgramOutputCapture,
    _ProgramTransportStore,
    _identity,
)
from auto_g16.transport._canonical import TransportBoundaryError
from tests.v3.execution.test_v31_lane_a import (
    CREST_EXECUTABLE_BYTES,
    CREST_EXECUTABLE_PATH,
    XTB_EXECUTABLE_BYTES,
    XTB_EXECUTABLE_PATH,
    LaneAFixture,
)
from tests.v31.conformer import test_ingest as _ingest_tests
from tests.v31.transport.test_program_composition import _Driver


SEED = b"3\nseed\nC 0 0 0\nO 1.2 0 0\nH 2.1 0 0\n"


class _NoEffectValidationDriver:
    def __init__(self, runtime_qualification: Mapping[str, object]) -> None:
        self.runtime_qualification = runtime_qualification
        self.effect_calls = 0

    def _reject_effect(self, *_args: object) -> object:
        self.effect_calls += 1
        raise AssertionError("capture re-attestation called an effect method")

    allocate_workspace = _reject_effect
    stage_exact_file = _reject_effect
    submit_qsub_once = _reject_effect
    query_scheduler = _reject_effect
    stat_exact_file = _reject_effect
    fetch_exact_file = _reject_effect
    reconcile_submission = _reject_effect


class XtbCrestSeedHandoffTests(LaneAFixture):
    def setUp(self) -> None:
        super().setUp()
        transport_root = self.root / "handoff-transport"
        transport_root.mkdir()
        self.program_transport_store = _ProgramTransportStore.create_new(
            transport_root / "program-transport.sqlite3",
            approved_root=transport_root,
        )
        self.addCleanup(self.program_transport_store.close)

    def profile(self, **changes: object):
        return _ingest_tests.CrestIngestTests.profile(self, **changes)

    @staticmethod
    def crest_frame() -> bytes:
        return _ingest_tests.CrestIngestTests.frame(-1.0)

    def xtb_spec(self, **changes: object) -> execution.ProgramExecutionSpec:
        data = {
            "model": "gfn2",
            "charge": 0,
            "unpaired_electrons": 0,
            "task": "optimize",
            "solvent": "thf",
        }
        data.update(changes)
        return _prepare_program_execution_spec(
            program_kind="xtb",
            executable_path=XTB_EXECUTABLE_PATH,
            executable_size_bytes=len(XTB_EXECUTABLE_BYTES),
            executable_sha256=sha256(XTB_EXECUTABLE_BYTES).hexdigest(),
            input_name="input.xyz",
            input_bytes=SEED,
            program_data=data,
        )

    def crest_spec(
        self,
        profile: object,
        *,
        seed: bytes = SEED,
    ) -> execution.ProgramExecutionSpec:
        route = profile.crest_imtd_gc_profile
        controls = route["imtd_gc_controls"]
        return _prepare_program_execution_spec(
            program_kind="crest",
            executable_path=CREST_EXECUTABLE_PATH,
            executable_size_bytes=len(CREST_EXECUTABLE_BYTES),
            executable_sha256=sha256(CREST_EXECUTABLE_BYTES).hexdigest(),
            input_name="seed.xyz",
            input_bytes=seed,
            program_data={
                "provider": "crest",
                "sampling_mode": "imtd-gc",
                "engine_version": "3.0.2",
                "runtype_selector": "-v3",
                "model": controls["model"],
                "charge": controls["charge"],
                "unpaired_electrons": controls["unpaired_electrons"],
                "metadynamics_length_millipicoseconds": 5000,
                "cregen_energy_window_millikcal_per_mol": 6000,
                "cregen_rmsd_threshold_milliangstrom": 500,
                "cregen_temperature_millikelvin": 298150,
                "normal_md_temperature_millikelvin": 300000,
                "stochastic_policy": dict(route["seed_policy"]),
                "sampling_configuration_identity": _payload_sha256(route),
            },
        )

    def workspace_for(
        self,
        attempt_id: str,
        *,
        project_id: str = "project-1",
    ) -> execution.WorkspaceBinding:
        (self.local_root / project_id).mkdir(parents=True, exist_ok=True)
        return execution.WorkspaceBinding(
            project=self.store.load_project(project_id),
            attempt_id=attempt_id,
            local_approved_root=str(self.local_root),
            local_attempt_dir=str(self.local_root / project_id / attempt_id),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=rf"C:\RTWIN\{project_id}\{attempt_id}",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir=f"/home/user100/SDL/{project_id}/{attempt_id}",
        )

    def xtb_snapshot(
        self,
        spec: execution.ProgramExecutionSpec,
        *,
        attempt_id: str = "attempt-1",
    ) -> execution.ProgramExecutionSnapshot:
        if attempt_id == "attempt-1":
            plan_id = "plan-1"
            resource_id = "resource-1"
            resources = self.resources()
        else:
            task_id = f"task-{attempt_id}"
            plan_id = f"plan-{attempt_id}"
            resource_id = f"resource-{attempt_id}"
            self.store.store_task(
                core.Task(
                    task_id=task_id,
                    workflow_run_id="run-1",
                    task_kind="successor-program",
                )
            )
            self.store.store_calculation_plan(
                core.CalculationPlan(
                    calculation_plan_id=plan_id,
                    task_id=task_id,
                    revision=1,
                    intent={"program": "xtb", "charge": 0},
                )
            )
            resource_spec = core.ResourceSpec(
                resource_spec_id=resource_id,
                task_id=task_id,
                resources={"tier": "simple"},
            )
            self.store.store_resource_spec(resource_spec)
            self.store.create_attempt(
                core.Attempt(attempt_id=attempt_id, task_id=task_id, ordinal=1)
            )
            resources = execution.ResolvedResourceRequest(
                resource_spec=resource_spec,
                cores=8,
                memory_mb=12_288,
                walltime_seconds=3_600,
                queue="simple",
            )
        return self.snapshot_service.prepare(
            self.store,
            attempt_id=attempt_id,
            calculation_plan_id=plan_id,
            resource_spec_id=resource_id,
            program_execution_spec=spec,
            project_physical_binding=self.physical_binding(),
            resolved_resource_request=resources,
            resolved_server_profile=self.resolved(),
            workspace_binding=self.workspace_for(attempt_id),
        )

    def capture_xtb(
        self,
        *,
        spec: execution.ProgramExecutionSpec | None = None,
        attempt_id: str = "attempt-1",
        outputs: Mapping[str, bytes] | None = None,
    ) -> tuple[execution.ProgramExecutionSnapshot, _ProgramOutputCapture]:
        selected_spec = self.xtb_spec() if spec is None else spec
        snapshot = self.xtb_snapshot(selected_spec, attempt_id=attempt_id)
        scheduler = snapshot.scheduler_artifacts[0]
        driver = _Driver(
            outputs=(
                {"xtb.out": b"normal xtb\n", "xtbopt.xyz": SEED}
                if outputs is None
                else outputs
            )
        )
        _execute_program_once(
            self.store,
            snapshot=snapshot,
            program_transport_store=self.program_transport_store,
            input_bytes={"input.xyz": SEED},
            scheduler_artifact_bytes={
                str(scheduler["portable_name"]): str(
                    scheduler["content_utf8"]
                ).encode("utf-8")
            },
            driver=driver,
        )
        capture = _capture_program_outputs(
            self.store,
            snapshot=snapshot,
            program_transport_store=self.program_transport_store,
            driver=driver,
        )
        return snapshot, capture

    @staticmethod
    def recapture(
        capture: _ProgramOutputCapture,
        artifacts: tuple[object, ...],
    ) -> _ProgramOutputCapture:
        payload = {
            "program_execution_snapshot_id": capture.program_execution_snapshot_id,
            "effect_intent_id": capture.effect_intent_id,
            "job_authority_id": capture.job_authority_id,
            "artifacts": tuple(item.identity_payload() for item in artifacts),
        }
        return replace(
            capture,
            capture_authority_id=_identity("output-capture", payload),
            artifacts=artifacts,
        )

    def submitted_core_without_receipts(
        self,
        snapshot: execution.ProgramExecutionSnapshot,
    ) -> core.SQLiteRuntimeStore:
        store = core.SQLiteRuntimeStore(self.root / "core-without-receipts.sqlite3")
        self.addCleanup(store.close)
        attempt = self.store.load_attempt(snapshot.attempt_id)
        task = self.store.load_task(attempt.task_id)
        workflow = self.store.load_workflow_run(task.workflow_run_id)
        store.store_project(self.store.load_project(workflow.project_id))
        store.store_workflow_run(workflow)
        store.store_task(task)
        store.store_calculation_plan(
            self.store.load_calculation_plan(snapshot.calculation_plan_id)
        )
        store.store_resource_spec(
            self.store.load_resource_spec(
                snapshot.resolved_resource_request.resource_spec_id
            )
        )
        store.create_attempt(attempt)
        store.record_submission_intent(snapshot.attempt_id, snapshot.effect_intent_id)
        store.record_submission_outcome(
            snapshot.attempt_id,
            snapshot.effect_intent_id,
            core.SubmissionOutcome.SUBMITTED,
        )
        return store

    def handoff(
        self,
        snapshot: execution.ProgramExecutionSnapshot,
        capture: _ProgramOutputCapture,
        *,
        profile: object | None = None,
        crest_spec: execution.ProgramExecutionSpec | None = None,
        crest_seed: bytes = SEED,
        core_store: core.SQLiteRuntimeStore | None = None,
        program_transport_store: _ProgramTransportStore | None = None,
        validation_driver: _ProgramEffectDriver | None = None,
    ) -> _XtbCrestSeedHandoff:
        selected_profile = self.profile() if profile is None else profile
        selected_crest_spec = (
            self.crest_spec(selected_profile, seed=crest_seed)
            if crest_spec is None
            else crest_spec
        )
        selected_driver = (
            _NoEffectValidationDriver(_Driver().runtime_qualification)
            if validation_driver is None
            else validation_driver
        )
        return _build_xtb_crest_seed_handoff(
            core_store=self.store if core_store is None else core_store,
            xtb_program_execution_snapshot=snapshot,
            xtb_program_transport_store=(
                self.program_transport_store
                if program_transport_store is None
                else program_transport_store
            ),
            xtb_validation_driver=selected_driver,
            xtb_output_capture=capture,
            crest_program_execution_spec=selected_crest_spec,
            crest_exact_input_bytes=crest_seed,
            sampling_profile=selected_profile,
        )

    def crest_snapshot(
        self,
        *,
        profile: object,
        spec: execution.ProgramExecutionSpec,
        handoff: _XtbCrestSeedHandoff,
        intent: object | None = None,
        project_binding: execution.ProjectPhysicalBinding | None = None,
        snapshot_service: object | None = None,
        project_id: str = "project-1",
    ) -> execution.ProgramExecutionSnapshot:
        self.store.store_task(
            core.Task(
                task_id=f"task-crest-{project_id}",
                workflow_run_id="run-1" if project_id == "project-1" else "run-2",
                task_kind="successor-program",
            )
        )
        selected_intent = (
            _preoptimized_crest_sampling_plan_intent(
                profile=profile,
                program_execution_spec=spec,
                preoptimization_handoff=handoff,
            )
            if intent is None
            else intent
        )
        plan_id = f"plan-crest-{project_id}"
        resource_id = f"resource-crest-{project_id}"
        attempt_id = f"attempt-crest-{project_id}"
        self.store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id=plan_id,
                task_id=f"task-crest-{project_id}",
                revision=1,
                intent=selected_intent,
            )
        )
        resource_spec = core.ResourceSpec(
            resource_spec_id=resource_id,
            task_id=f"task-crest-{project_id}",
            resources={"tier": "simple"},
        )
        self.store.store_resource_spec(resource_spec)
        self.store.create_attempt(
            core.Attempt(
                attempt_id=attempt_id,
                task_id=f"task-crest-{project_id}",
                ordinal=1,
            )
        )
        resources = execution.ResolvedResourceRequest(
            resource_spec=resource_spec,
            cores=8,
            memory_mb=12_288,
            walltime_seconds=3_600,
            queue="simple",
        )
        service = self.snapshot_service if snapshot_service is None else snapshot_service
        return service.prepare(
            self.store,
            attempt_id=attempt_id,
            calculation_plan_id=plan_id,
            resource_spec_id=resource_id,
            program_execution_spec=spec,
            project_physical_binding=(
                self.physical_binding() if project_binding is None else project_binding
            ),
            resolved_resource_request=resources,
            resolved_server_profile=self.resolved(),
            workspace_binding=self.workspace_for(attempt_id, project_id=project_id),
        )

    def ingest(
        self,
        *,
        profile: object,
        spec: execution.ProgramExecutionSpec,
        handoff: _XtbCrestSeedHandoff,
        snapshot: execution.ProgramExecutionSnapshot,
        xtb_snapshot: execution.ProgramExecutionSnapshot,
        xtb_capture: _ProgramOutputCapture,
        validation_driver: _ProgramEffectDriver | None = None,
    ):
        raw = self.crest_frame()
        artifact = _CrestOutputArtifactBinding(
            program_execution_snapshot_id=snapshot.program_execution_snapshot_id,
            effect_intent_id=snapshot.effect_intent_id,
            program_execution_spec_id=snapshot.program_execution_spec_id,
            logical_role="conformer-ensemble",
            portable_name="crest_conformers.xyz",
            format="xyz-trajectory",
            sha256=sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        return _ingest_preoptimized_crest_conformers_xyz(
            profile=profile,
            program_execution_snapshot=snapshot,
            core_store=self.store,
            preoptimization_handoff=handoff,
            xtb_program_execution_snapshot=xtb_snapshot,
            xtb_program_transport_store=self.program_transport_store,
            xtb_validation_driver=(
                _NoEffectValidationDriver(_Driver().runtime_qualification)
                if validation_driver is None
                else validation_driver
            ),
            xtb_output_capture=xtb_capture,
            artifact_binding=artifact,
            artifact_bytes=raw,
            descriptors_by_member_index=None,
        )

    def test_positive_exact_byte_capture_handoff_plan_v2_and_ingest(self) -> None:
        xtb_snapshot, capture = self.capture_xtb()
        profile = self.profile()
        crest_spec = self.crest_spec(profile)
        handoff = self.handoff(
            xtb_snapshot,
            capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        crest_snapshot = self.crest_snapshot(
            profile=profile,
            spec=crest_spec,
            handoff=handoff,
        )
        observations = self.ingest(
            profile=profile,
            spec=crest_spec,
            handoff=handoff,
            snapshot=crest_snapshot,
            xtb_snapshot=xtb_snapshot,
            xtb_capture=capture,
        )
        geometry = next(
            item for item in capture.artifacts if item.logical_role == "optimized-geometry"
        )
        self.assertEqual(geometry.content, SEED)
        self.assertEqual(handoff.optimized_geometry_sha256, sha256(SEED).hexdigest())
        self.assertEqual(handoff.crest_exact_input_sha256, sha256(SEED).hexdigest())
        self.assertEqual(handoff.optimized_geometry_size_bytes, len(SEED))
        self.assertEqual(handoff.crest_exact_input_size_bytes, len(SEED))
        self.assertEqual(len(observations), 1)
        self.assertEqual(
            observations[0]["source_binding"]["source_run_id"],
            crest_snapshot.program_execution_snapshot_id,
        )
        self.assertTrue(observations[0]["source_binding"]["source_artifact_identity"])
        self.assertEqual(observations[0]["source_binding"]["source_member_index"], 0)

    def test_original_forged_job_authority_attack_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        forged_job = "00000000-0000-0000-0000-000000000000"
        artifacts = tuple(
            replace(artifact, job_authority_id=forged_job)
            for artifact in capture.artifacts
        )
        forged = self.recapture(
            replace(capture, job_authority_id=forged_job), artifacts
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "replayed job authority"
        ):
            self.handoff(snapshot, forged)

    def test_runtime_capture_reattestation_makes_zero_effect_calls(self) -> None:
        snapshot, capture = self.capture_xtb()
        driver = _NoEffectValidationDriver(_Driver().runtime_qualification)
        recovered = _assert_program_output_capture_authority(
            self.store,
            snapshot=snapshot,
            program_transport_store=self.program_transport_store,
            driver=driver,
            capture=capture,
        )
        self.assertEqual(recovered["job_authority_id"], capture.job_authority_id)
        self.assertEqual(driver.effect_calls, 0)

    def test_missing_persisted_submit_receipt_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        store = self.submitted_core_without_receipts(snapshot)
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "job-establishing receipt"
        ):
            self.handoff(snapshot, capture, core_store=store)

    def test_missing_matching_physical_fetch_effect_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        trigger_name, trigger_sql = next(
            item
            for item in _PROGRAM_STORE_TRIGGERS
            if item[0] == "program_effect_physical_authority_no_delete"
        )
        connection = self.program_transport_store._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(f'DROP TRIGGER "{trigger_name}"')
            deleted = connection.execute(
                "DELETE FROM program_effect_physical_authority "
                "WHERE physical_effect_authority_id IN "
                "(SELECT physical_effect_authority_id "
                "FROM program_effect_physical_authority "
                "WHERE operation='FETCH_EXACT_FILE' ORDER BY rowid LIMIT 1)"
            ).rowcount
            connection.execute(trigger_sql)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        self.assertEqual(deleted, 1)
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "physical-effect authority"
        ):
            self.handoff(snapshot, capture)

    def test_capture_from_another_program_transport_store_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        root = self.root / "other-program-transport"
        root.mkdir()
        other = _ProgramTransportStore.create_new(
            root / "program-transport.sqlite3", approved_root=root
        )
        self.addCleanup(other.close)
        self.assertNotEqual(
            other.program_transport_store_id,
            self.program_transport_store.program_transport_store_id,
        )
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture, program_transport_store=other)

    def test_capture_from_another_store_instance_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        path = Path(self.program_transport_store._path)
        root = Path(self.program_transport_store._root)
        store_id = self.program_transport_store.program_transport_store_id
        instance_id = self.program_transport_store.store_instance_id
        self.program_transport_store.close()
        path.rename(path.with_name("retired-program-transport.sqlite3"))
        replacement = _ProgramTransportStore.create_new(path, approved_root=root)
        self.addCleanup(replacement.close)
        self.assertEqual(replacement.program_transport_store_id, store_id)
        self.assertNotEqual(replacement.store_instance_id, instance_id)
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture, program_transport_store=replacement)

    def test_different_runtime_qualification_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        qualification = dict(_Driver().runtime_qualification)
        qualification["deployment_id"] = "different-qualified-runtime"
        driver = _NoEffectValidationDriver(qualification)
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture, validation_driver=driver)
        self.assertEqual(driver.effect_calls, 0)

    def test_snapshot_with_different_resolved_profile_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        target = self.resolved(server_profile_id="different-profile")
        _attestor, provisioning, service = self.synthetic_authority(
            target=target,
            observed_state="ABSENT",
            observed_project_physical_identity=None,
            provisioned_project_physical_identity=(
                "different-profile-project-token"
            ),
        )
        binding = provisioning.provision_remote_project(
            project=self.store.load_project("project-1"),
            target=target,
            remote_project_dir=self.remote_project_dir,
            evidence_identity="different-profile-authority",
        )
        changed = service.prepare(
            self.store,
            attempt_id=snapshot.attempt_id,
            calculation_plan_id=snapshot.calculation_plan_id,
            resource_spec_id=snapshot.resolved_resource_request.resource_spec_id,
            program_execution_spec=snapshot.program_execution_spec,
            project_physical_binding=binding,
            resolved_resource_request=snapshot.resolved_resource_request,
            resolved_server_profile=target,
            workspace_binding=snapshot.workspace_binding,
        )
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(changed, capture)

    def test_snapshot_with_different_workspace_binding_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        other_local_root = self.root / "other-local"
        other_local_project = other_local_root / "project-1"
        other_local_project.mkdir(parents=True)
        workspace = execution.WorkspaceBinding(
            project=self.store.load_project("project-1"),
            attempt_id=snapshot.attempt_id,
            local_approved_root=str(other_local_root),
            local_attempt_dir=str(other_local_project / snapshot.attempt_id),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=rf"C:\RTWIN\project-1\{snapshot.attempt_id}",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir=snapshot.workspace_binding.remote_attempt_dir,
        )
        changed = self.snapshot_service.prepare(
            self.store,
            attempt_id=snapshot.attempt_id,
            calculation_plan_id=snapshot.calculation_plan_id,
            resource_spec_id=snapshot.resolved_resource_request.resource_spec_id,
            program_execution_spec=snapshot.program_execution_spec,
            project_physical_binding=snapshot.project_physical_binding,
            resolved_resource_request=snapshot.resolved_resource_request,
            resolved_server_profile=snapshot.resolved_server_profile,
            workspace_binding=workspace,
        )
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(changed, capture)

    def test_one_artifact_job_authority_splice_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        artifacts = (
            replace(
                capture.artifacts[0],
                job_authority_id="00000000-0000-0000-0000-000000000000",
            ),
            *capture.artifacts[1:],
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "artifact differs"
        ):
            self.handoff(snapshot, self.recapture(capture, artifacts))

    def test_fetch_receipt_id_replaced_with_unrelated_observation_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        first, geometry = capture.artifacts
        assert first.fetch_receipt_id is not None
        changed = replace(geometry, fetch_receipt_id=first.fetch_receipt_id)
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(
                snapshot,
                self.recapture(capture, (first, changed)),
            )

    def test_fetch_receipt_digest_and_size_cannot_be_overridden_locally(self) -> None:
        snapshot, capture = self.capture_xtb()
        first, geometry = capture.artifacts
        changed_content = SEED.replace(b"1.2", b"1.3")
        self.assertEqual(len(changed_content), len(SEED))
        changed = replace(
            geometry,
            content=changed_content,
            sha256=sha256(changed_content).hexdigest(),
            size_bytes=len(changed_content),
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "persisted FETCH authority"
        ):
            self.handoff(
                snapshot,
                self.recapture(capture, (first, changed)),
            )

    def test_locally_recomputed_content_and_size_cannot_override_stat(self) -> None:
        snapshot, capture = self.capture_xtb()
        first, geometry = capture.artifacts
        changed_content = SEED + b"X"
        changed = replace(
            geometry,
            content=changed_content,
            sha256=sha256(changed_content).hexdigest(),
            size_bytes=len(changed_content),
        )
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(
                snapshot,
                self.recapture(capture, (first, changed)),
            )

    def test_optional_absent_output_with_forged_fetch_content_rejects(self) -> None:
        snapshot, capture = self.capture_xtb(
            spec=self.xtb_spec(task="single-point"),
            outputs={"xtb.out": b"normal xtb\n"},
        )
        present, absent = capture.artifacts
        self.assertEqual(absent.presence, "absent")
        assert present.fetch_receipt_id is not None
        forged = replace(
            absent,
            sha256=sha256(b"forged").hexdigest(),
            size_bytes=len(b"forged"),
            fetch_receipt_id=present.fetch_receipt_id,
            content=b"forged",
        )
        changed = self.recapture(capture, (present, forged))
        driver = _NoEffectValidationDriver(_Driver().runtime_qualification)
        with self.assertRaisesRegex(TransportBoundaryError, "optional output"):
            _assert_program_output_capture_authority(
                self.store,
                snapshot=snapshot,
                program_transport_store=self.program_transport_store,
                driver=driver,
                capture=changed,
            )
        self.assertEqual(driver.effect_calls, 0)

    def test_wrong_xtb_snapshot_id_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        object.__setattr__(snapshot, "program_execution_snapshot_id", "forged")
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture)

    def test_wrong_xtb_effect_intent_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        object.__setattr__(snapshot, "effect_intent_id", "forged")
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture)

    def test_wrong_xtb_spec_id_rejects(self) -> None:
        snapshot, capture = self.capture_xtb()
        object.__setattr__(
            snapshot.program_execution_spec,
            "program_execution_spec_id",
            "forged",
        )
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture)

    def test_caller_capture_authority_id_is_recomputed(self) -> None:
        snapshot, capture = self.capture_xtb()
        with self.assertRaisesRegex(execution.ExecutionValueError, "capture authority"):
            self.handoff(snapshot, replace(capture, capture_authority_id="forged"))

    def test_capture_snapshot_and_effect_splices_reject(self) -> None:
        snapshot, capture = self.capture_xtb()
        for field in ("program_execution_snapshot_id", "effect_intent_id"):
            artifacts = tuple(
                replace(artifact, **{field: "other"})
                for artifact in capture.artifacts
            )
            changed = replace(capture, **{field: "other"}, artifacts=artifacts)
            changed = self.recapture(changed, artifacts)
            with self.subTest(field=field), self.assertRaisesRegex(
                execution.ExecutionValueError,
                "differs from the exact execution snapshot",
            ):
                self.handoff(snapshot, changed)

    def test_single_point_output_cannot_authorize_preoptimization(self) -> None:
        snapshot, capture = self.capture_xtb(spec=self.xtb_spec(task="single-point"))
        with self.assertRaisesRegex(execution.ExecutionValueError, "xTB optimize"):
            self.handoff(snapshot, capture)

    def test_missing_absent_duplicate_role_name_and_format_reject(self) -> None:
        snapshot, capture = self.capture_xtb()
        geometry = capture.artifacts[1]
        absent = replace(
            geometry,
            presence="absent",
            sha256=None,
            size_bytes=None,
            fetch_receipt_id=None,
            content=None,
        )
        variants = (
            capture.artifacts[:1],
            (capture.artifacts[0], absent),
            (*capture.artifacts, geometry),
            (capture.artifacts[0], replace(geometry, logical_role="program-log")),
            (capture.artifacts[0], replace(geometry, portable_name="other.xyz")),
            (capture.artifacts[0], replace(geometry, format="text")),
        )
        for index, artifacts in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(execution.ExecutionValueError):
                self.handoff(snapshot, self.recapture(capture, artifacts))

    def test_output_sha_size_and_content_mismatch_reject(self) -> None:
        snapshot, capture = self.capture_xtb()
        geometry = capture.artifacts[1]
        variants = (
            replace(geometry, sha256="0" * 64),
            replace(geometry, size_bytes=len(SEED) + 1),
            replace(geometry, content=SEED[:-1] + b"X"),
        )
        for index, changed in enumerate(variants):
            artifacts = (capture.artifacts[0], changed)
            with self.subTest(index=index), self.assertRaises(execution.ExecutionValueError):
                self.handoff(snapshot, self.recapture(capture, artifacts))

    def test_one_byte_and_rerendered_seed_splices_reject(self) -> None:
        snapshot, capture = self.capture_xtb()
        variants = (
            SEED[:-1] + b" ",
            SEED.replace(b"1.2", b"1.200"),
            SEED.replace(b"\n", b"\r\n"),
        )
        for seed in variants:
            profile = self.profile()
            spec = self.crest_spec(profile, seed=seed)
            with self.subTest(seed=seed), self.assertRaisesRegex(
                execution.ExecutionValueError,
                "seed bytes",
            ):
                self.handoff(
                    snapshot,
                    capture,
                    profile=profile,
                    crest_spec=spec,
                    crest_seed=seed,
                )

    def test_charge_splice_rejects(self) -> None:
        snapshot, capture = self.capture_xtb(spec=self.xtb_spec(charge=1))
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture)

    def test_unpaired_electron_splice_rejects(self) -> None:
        snapshot, capture = self.capture_xtb(
            spec=self.xtb_spec(unpaired_electrons=1)
        )
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture)

    def test_gfn_model_splice_rejects(self) -> None:
        snapshot, capture = self.capture_xtb(spec=self.xtb_spec(model="gfn1"))
        with self.assertRaises(execution.ExecutionValueError):
            self.handoff(snapshot, capture)

    def test_other_sampling_profile_rejects_before_ingest(self) -> None:
        xtb_snapshot, capture = self.capture_xtb()
        profile = self.profile()
        crest_spec = self.crest_spec(profile)
        handoff = self.handoff(
            xtb_snapshot,
            capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        other_profile = self.profile(stereo_assignment="S")
        intent = _preoptimized_crest_sampling_plan_intent(
            profile=profile,
            program_execution_spec=crest_spec,
            preoptimization_handoff=handoff,
        )
        snapshot = self.crest_snapshot(
            profile=other_profile,
            spec=crest_spec,
            handoff=handoff,
            intent=intent,
        )
        with self.assertRaisesRegex(ConformerError, "different SamplingProfile"):
            self.ingest(
                profile=other_profile,
                spec=crest_spec,
                handoff=handoff,
                snapshot=snapshot,
                xtb_snapshot=xtb_snapshot,
                xtb_capture=capture,
            )

    def assert_plan_handoff_field_rejects(self, field: str) -> None:
        xtb_snapshot, capture = self.capture_xtb()
        profile = self.profile()
        crest_spec = self.crest_spec(profile)
        handoff = self.handoff(
            xtb_snapshot,
            capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        intent = dict(
            _preoptimized_crest_sampling_plan_intent(
                profile=profile,
                program_execution_spec=crest_spec,
                preoptimization_handoff=handoff,
            )
        )
        intent[field] = "0" * 64
        crest_snapshot = self.crest_snapshot(
            profile=profile,
            spec=crest_spec,
            handoff=handoff,
            intent=intent,
        )
        with self.assertRaisesRegex(ConformerError, "different preoptimization"):
            self.ingest(
                profile=profile,
                spec=crest_spec,
                handoff=handoff,
                snapshot=crest_snapshot,
                xtb_snapshot=xtb_snapshot,
                xtb_capture=capture,
            )

    def test_plan_v2_wrong_handoff_id_rejects(self) -> None:
        self.assert_plan_handoff_field_rejects(
            "preoptimization_handoff_authority_id"
        )

    def test_plan_v2_wrong_handoff_payload_hash_rejects(self) -> None:
        self.assert_plan_handoff_field_rejects(
            "preoptimization_handoff_payload_sha256"
        )

    def test_handoff_from_another_xtb_attempt_rejects(self) -> None:
        first_snapshot, first_capture = self.capture_xtb()
        profile = self.profile()
        crest_spec = self.crest_spec(profile)
        first_handoff = self.handoff(
            first_snapshot,
            first_capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        other_snapshot, other_capture = self.capture_xtb(attempt_id="attempt-2")
        other_handoff = self.handoff(
            other_snapshot,
            other_capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        intent = _preoptimized_crest_sampling_plan_intent(
            profile=profile,
            program_execution_spec=crest_spec,
            preoptimization_handoff=first_handoff,
        )
        crest_snapshot = self.crest_snapshot(
            profile=profile,
            spec=crest_spec,
            handoff=first_handoff,
            intent=intent,
        )
        with self.assertRaisesRegex(ConformerError, "runtime-attested xTB capture"):
            self.ingest(
                profile=profile,
                spec=crest_spec,
                handoff=other_handoff,
                snapshot=crest_snapshot,
                xtb_snapshot=first_snapshot,
                xtb_capture=first_capture,
            )

    def test_cross_project_snapshot_lineage_rejects(self) -> None:
        xtb_snapshot, capture = self.capture_xtb()
        profile = self.profile()
        crest_spec = self.crest_spec(profile)
        handoff = self.handoff(
            xtb_snapshot,
            capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        self.store.store_project(core.Project(project_id="project-2"))
        self.store.store_workflow_run(
            core.WorkflowRun(
                workflow_run_id="run-2",
                project_id="project-2",
                workflow_name="v31-cross-project-negative",
            )
        )
        target = self.resolved()
        attestor = _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
            target=target,
            observed_project_dir="/home/user100/SDL/project-2",
            observed_state="ABSENT",
            observed_parent_physical_identity="opaque-server-parent-v2",
            observed_project_physical_identity=None,
            provisioned_project_physical_identity="opaque-server-project-v2",
        )
        provisioning = _ProjectProvisioningService._from_privileged_synthetic_attestor(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
            attestor=attestor,
        )
        binding = provisioning.provision_remote_project(
            project=self.store.load_project("project-2"),
            target=target,
            remote_project_dir="/home/user100/SDL/project-2",
            evidence_identity="synthetic-cross-project",
        )
        snapshot_service = _ProgramExecutionSnapshotService._for_privileged_synthetic_tests(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
            project_provisioning=provisioning,
        )
        crest_snapshot = self.crest_snapshot(
            profile=profile,
            spec=crest_spec,
            handoff=handoff,
            project_binding=binding,
            snapshot_service=snapshot_service,
            project_id="project-2",
        )
        with self.assertRaisesRegex(ConformerError, "different Project authority"):
            self.ingest(
                profile=profile,
                spec=crest_spec,
                handoff=handoff,
                snapshot=crest_snapshot,
                xtb_snapshot=xtb_snapshot,
                xtb_capture=capture,
            )

    def test_v1_and_v2_plan_meanings_remain_disjoint(self) -> None:
        xtb_snapshot, capture = self.capture_xtb()
        profile = self.profile()
        crest_spec = self.crest_spec(profile)
        handoff = self.handoff(
            xtb_snapshot,
            capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        v2_snapshot = self.crest_snapshot(
            profile=profile,
            spec=crest_spec,
            handoff=handoff,
        )
        raw = self.crest_frame()
        artifact = _CrestOutputArtifactBinding(
            program_execution_snapshot_id=v2_snapshot.program_execution_snapshot_id,
            effect_intent_id=v2_snapshot.effect_intent_id,
            program_execution_spec_id=v2_snapshot.program_execution_spec_id,
            logical_role="conformer-ensemble",
            portable_name="crest_conformers.xyz",
            format="xyz-trajectory",
            sha256=sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        with self.assertRaisesRegex(ConformerError, "contract v1"):
            _ingest_crest_conformers_xyz(
                profile=profile,
                program_execution_snapshot=v2_snapshot,
                core_store=self.store,
                artifact_binding=artifact,
                artifact_bytes=raw,
                descriptors_by_member_index=None,
            )

    def test_handoff_and_preoptimized_ingest_remain_private(self) -> None:
        self.assertNotIn("XtbCrestSeedHandoff", execution.__all__)
        self.assertNotIn("build_xtb_crest_seed_handoff", execution.__all__)
        self.assertEqual(_XtbCrestSeedHandoff.__module__, "auto_g16.execution.xtb_crest_handoff")
        source = Path(execution.__file__).read_text(encoding="utf-8")
        self.assertNotIn("xtb_crest_handoff", source)


if __name__ == "__main__":
    unittest.main()
