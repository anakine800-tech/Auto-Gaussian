from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import inspect
import os
from pathlib import Path
import secrets
import tempfile
import unittest

import auto_g16.core as core
import auto_g16.execution as execution
from auto_g16.execution.program import (
    _prepare_program_execution_snapshot,
    _prepare_program_execution_spec,
)
from auto_g16.execution.project_provisioning import (
    _ACTIVE_PROOFS,
    _PROOF_LOCK,
    _ProjectBindingReattestation,
    _ProvisioningJournal,
    _binding_from_existing_local_target,
    _classify_project_target,
    _reattest_project_binding,
)


XYZ = b"2\nH2\nH 0 0 0\nH 0 0 0.74\n"
XTB_EXECUTABLE_BYTES = b"auto-g16 synthetic non-production xtb fixture\n"
CREST_EXECUTABLE_BYTES = b"auto-g16 synthetic non-production crest fixture\n"
XTB_EXECUTABLE_PATH = "/opt/auto-g16-fixtures/bin/xtb"
CREST_EXECUTABLE_PATH = "/opt/auto-g16-fixtures/bin/crest"
GAUSSIAN_INPUT = b"#p hf/sto-3g\n\nfixture\n\n0 1\nH 0 0 0\n\n"
PBS_TEMPLATE = b"#!/bin/bash\n#PBS -N synthetic\nexec g16 input.gjf\n"


class LaneAFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.local_root = self.root / "local"
        self.local_project = self.local_root / "project-1"
        self.local_project.mkdir(parents=True)
        self.database = self.root / "core.sqlite3"
        self.store = core.SQLiteRuntimeStore(self.database)
        self.addCleanup(self.store.close)
        self.store.store_project(core.Project(project_id="project-1"))
        self.store.store_workflow_run(
            core.WorkflowRun(
                workflow_run_id="run-1",
                project_id="project-1",
                workflow_name="v31-flexible-molecule",
            )
        )
        self.store.store_task(
            core.Task(
                task_id="task-1",
                workflow_run_id="run-1",
                task_kind="successor-program",
            )
        )
        self.store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id="plan-1",
                task_id="task-1",
                revision=1,
                intent={"program": "xtb", "charge": 0},
            )
        )
        self.store.store_resource_spec(
            core.ResourceSpec(
                resource_spec_id="resource-1",
                task_id="task-1",
                resources={"tier": "simple"},
            )
        )
        self.store.create_attempt(
            core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1)
        )

    def resolved(self) -> execution.ResolvedServerProfile:
        return execution.resolve_server_profile(
            execution.ServerProfile(
                server_profile_id="profile-v31",
                profile_revision=1,
                transport_kind="legacy_rtwin_pbs",
                target_host="server.example",
                target_port=22,
                remote_user="user100",
                jump_topology=[],
                host_key_policy="strict",
                batch_mode=True,
                identities_only=True,
                remote_root=execution.LEGACY_REMOTE_ROOT,
                platform_paths={"rtwin_root": r"C:\RTWIN"},
                config_files=[("ssh_config", b"Host server.example\n")],
                runtime_contents={
                    "xtb": XTB_EXECUTABLE_BYTES,
                    "crest": CREST_EXECUTABLE_BYTES,
                },
            )
        )

    def resources(self) -> execution.ResolvedResourceRequest:
        return execution.ResolvedResourceRequest(
            resource_spec=self.store.load_resource_spec("resource-1"),
            cores=8,
            memory_mb=12_288,
            walltime_seconds=3_600,
            queue="simple",
        )

    def workspace(self) -> execution.WorkspaceBinding:
        return execution.WorkspaceBinding(
            project=self.store.load_project("project-1"),
            attempt_id="attempt-1",
            local_approved_root=str(self.local_root),
            local_attempt_dir=str(self.local_project / "attempt-1"),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir="/home/user100/SDL/project-1/attempt-1",
        )

    def physical_binding(self) -> execution.ProjectPhysicalBinding:
        project = self.store.load_project("project-1")
        local_binding = _binding_from_existing_local_target(
            project=project,
            reviewed_root=str(self.local_root),
            project_directory=str(self.local_project),
            evidence_identity="synthetic-local-inspection",
        )
        locations = (
            local_binding.locations[0],
            {
                "location_kind": "server",
                "reviewed_root": execution.LEGACY_REMOTE_ROOT,
                "project_directory": "/home/user100/SDL/project-1",
                "provisioning_disposition": "PRODUCT_BOUND_EXISTING",
                "parent_physical_identity": "opaque-server-parent",
                "project_physical_identity": "opaque-server-project",
                "evidence_identity": "evidence-server",
            },
            {
                "location_kind": "rtwin",
                "reviewed_root": r"C:\RTWIN",
                "project_directory": r"C:\RTWIN\project-1",
                "provisioning_disposition": "PRODUCT_BOUND_EXISTING",
                "parent_physical_identity": "opaque-rtwin-parent",
                "project_physical_identity": "opaque-rtwin-project",
                "evidence_identity": "evidence-rtwin",
            },
        )
        return execution.ProjectPhysicalBinding._from_inspected(
            project=project, locations=locations
        )

    def xtb_spec(self, **changes: object) -> execution.ProgramExecutionSpec:
        return _prepare_program_execution_spec(
            program_kind="xtb",
            executable_path=XTB_EXECUTABLE_PATH,
            executable_size_bytes=len(XTB_EXECUTABLE_BYTES),
            executable_sha256=sha256(XTB_EXECUTABLE_BYTES).hexdigest(),
            input_name="input.xyz",
            input_bytes=XYZ,
            program_data=self.xtb_data(**changes),
        )

    def crest_spec(self, **changes: object) -> execution.ProgramExecutionSpec:
        return _prepare_program_execution_spec(
            program_kind="crest",
            executable_path=CREST_EXECUTABLE_PATH,
            executable_size_bytes=len(CREST_EXECUTABLE_BYTES),
            executable_sha256=sha256(CREST_EXECUTABLE_BYTES).hexdigest(),
            input_name="seed.xyz",
            input_bytes=XYZ,
            program_data=self.crest_data(**changes),
        )

    def v30_snapshot(self) -> execution.ExecutionSnapshot:
        prepared = execution.PreparedInputBinding(
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            calculation_plan_revision=1,
            input_format="gaussian-gjf",
            logical_name="input.gjf",
            prepared_bytes=GAUSSIAN_INPUT,
        )
        template = execution.PbsTemplateBinding(
            logical_name="submit.pbs",
            template_bytes=PBS_TEMPLATE,
            template_contract_version="pbs-template-v1",
            prepared_input_logical_name="input.gjf",
        )
        return execution.prepare_execution_snapshot(
            self.store,
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            resource_spec_id="resource-1",
            prepared_input_binding=prepared,
            resolved_resource_request=self.resources(),
            resolved_server_profile=self.resolved(),
            workspace_binding=self.workspace(),
            pbs_template_binding=template,
            adapter_contract_version="synthetic-v30",
        )

    def successor_snapshot(
        self,
        *,
        spec: execution.ProgramExecutionSpec | None = None,
        binding: execution.ProjectPhysicalBinding | None = None,
    ) -> execution.ProgramExecutionSnapshot:
        selected_spec = self.xtb_spec() if spec is None else spec
        selected_binding = self.physical_binding() if binding is None else binding
        return _prepare_program_execution_snapshot(
            self.store,
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            resource_spec_id="resource-1",
            program_execution_spec=selected_spec,
            project_physical_binding=selected_binding,
            resolved_resource_request=self.resources(),
            resolved_server_profile=self.resolved(),
            workspace_binding=self.workspace(),
            project_reattestation=self.synthetic_server_reattestation(
                selected_binding
            ),
        )

    @staticmethod
    def synthetic_server_reattestation(
        binding: execution.ProjectPhysicalBinding,
    ) -> _ProjectBindingReattestation:
        """Register a test-only server proof; no production issuer exists in Lane A."""

        locations = tuple(
            item for item in binding.locations if item["location_kind"] == "server"
        )
        if len(locations) != 1:
            raise AssertionError("synthetic fixture requires one server location")
        location = locations[0]
        proof = object.__new__(_ProjectBindingReattestation)
        nonce = secrets.token_bytes(32)
        proof._binding_id = binding.project_physical_binding_id
        proof._location_kind = "server"
        proof._reviewed_root = str(location["reviewed_root"])
        proof._project_directory = str(location["project_directory"])
        proof._parent_identity = str(location["parent_physical_identity"])
        proof._target_identity = str(location["project_physical_identity"])
        proof._local_reinspection = False
        proof._nonce = nonce
        with _PROOF_LOCK:
            _ACTIVE_PROOFS[nonce] = (
                proof,
                proof._binding_id,
                proof._location_kind,
                proof._reviewed_root,
                proof._project_directory,
                proof._parent_identity,
                proof._target_identity,
                proof._local_reinspection,
            )
        return proof

    @staticmethod
    def xtb_data(**changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "model": "gfn2",
            "charge": 0,
            "unpaired_electrons": 0,
            "task": "optimize",
            "solvent": "thf",
        }
        value.update(changes)
        return value

    @staticmethod
    def crest_data(**changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "model": "gfn2",
            "search_mode": "ttconf",
            "preset": "normal",
            "charge": 0,
            "unpaired_electrons": 0,
            "energy_window_millikcal_per_mol": 6000,
            "rmsd_threshold_milliangstrom": 500,
            "temperature_millikelvin": 298150,
            "random_seed": 17,
        }
        value.update(changes)
        return value


class ProgramSpecTests(LaneAFixture):
    def test_public_budget_adds_exactly_three_records_and_no_adapter_surface(self) -> None:
        self.assertTrue(
            {
                "ProgramExecutionSpec",
                "ProgramExecutionSnapshot",
                "ProjectPhysicalBinding",
            }.issubset(execution.__all__)
        )
        self.assertFalse(
            {"ProgramAdapter", "ProgramRegistry", "ExecutablePlugin"}.intersection(
                execution.__all__
            )
        )
        self.assertEqual(
            tuple(inspect.signature(execution.ProgramExecutionSpec).parameters), ()
        )
        self.assertEqual(
            tuple(inspect.signature(execution.ProgramExecutionSnapshot).parameters), ()
        )
        self.assertEqual(
            tuple(inspect.signature(execution.ProjectPhysicalBinding).parameters), ()
        )
        self.assertEqual(
            {item.name for item in fields(execution.ProgramExecutionSpec) if not item.name.startswith("_")},
            {
                "program_execution_spec_id",
                "program_kind",
                "adapter_id",
                "adapter_contract_version",
                "exact_inputs",
                "program_data",
                "invocation",
                "required_outputs",
                "optional_outputs",
            },
        )

    def test_xtb_closed_fixture_is_deterministic_and_effect_fields_change_identity(self) -> None:
        first = self.xtb_spec()
        replay = _prepare_program_execution_spec(
            program_kind="xtb",
            executable_path=XTB_EXECUTABLE_PATH,
            executable_size_bytes=len(XTB_EXECUTABLE_BYTES),
            executable_sha256=sha256(XTB_EXECUTABLE_BYTES).hexdigest(),
            input_name="input.xyz",
            input_bytes=XYZ,
            program_data={
                "solvent": "thf",
                "task": "optimize",
                "unpaired_electrons": 0,
                "charge": 0,
                "model": "gfn2",
            },
        )
        changed = self.xtb_spec(charge=-1)
        self.assertEqual(first.semantic_payload(), replay.semantic_payload())
        self.assertNotEqual(first.program_execution_spec_id, changed.program_execution_spec_id)
        self.assertEqual(
            first.invocation["argv"],
            (
                XTB_EXECUTABLE_PATH,
                "input.xyz",
                "--gfn",
                "2",
                "--chrg",
                "0",
                "--uhf",
                "0",
                "--opt",
                "--alpb",
                "thf",
            ),
        )
        self.assertEqual(first.required_outputs[1]["portable_name"], "xtbopt.xyz")
        self.assertEqual(first.optional_outputs, ())

    def test_crest_closed_fixture_has_exact_tokens_and_output_requests(self) -> None:
        spec = self.crest_spec()
        self.assertEqual(
            spec.invocation["argv"],
            (
                CREST_EXECUTABLE_PATH,
                "seed.xyz",
                "-ttconf",
                "normal",
                "--gfn2",
                "--chrg",
                "0",
                "--uhf",
                "0",
                "-ttewin",
                "6.000",
                "-ttseed",
                "17",
                "--rthr",
                "0.500",
                "--temp",
                "298.150",
            ),
        )
        self.assertEqual(
            tuple(item["portable_name"] for item in spec.required_outputs),
            ("crest.out", "crest_conformers.xyz"),
        )
        self.assertEqual(spec.optional_outputs[0]["portable_name"], "crest.energies")

    def test_unknown_fields_shell_authority_and_gaussian_successor_fail_closed(self) -> None:
        cases = (
            ("xtb", self.xtb_data(command="xtb input.xyz")),
            ("xtb", self.xtb_data(environment={"PATH": "/tmp"})),
            ("crest", self.crest_data(extension={"plugin": "x"})),
        )
        for kind, data in cases:
            with self.subTest(kind=kind, keys=tuple(data)), self.assertRaises(
                execution.ExecutionValueError
            ):
                _prepare_program_execution_spec(
                    program_kind=kind,
                    executable_path=(
                        XTB_EXECUTABLE_PATH if kind == "xtb" else CREST_EXECUTABLE_PATH
                    ),
                    executable_size_bytes=(
                        len(XTB_EXECUTABLE_BYTES)
                        if kind == "xtb"
                        else len(CREST_EXECUTABLE_BYTES)
                    ),
                    executable_sha256=sha256(
                        XTB_EXECUTABLE_BYTES if kind == "xtb" else CREST_EXECUTABLE_BYTES
                    ).hexdigest(),
                    input_name="input.xyz",
                    input_bytes=XYZ,
                    program_data=data,
                )
        with self.assertRaisesRegex(execution.ExecutionValueError, "reserved"):
            _prepare_program_execution_spec(
                program_kind="gaussian",
                executable_path="/opt/auto-g16-fixtures/bin/gaussian",
                executable_size_bytes=1,
                executable_sha256="0" * 64,
                input_name="input.xyz",
                input_bytes=XYZ,
                program_data={},
            )

    def test_executable_identity_is_closed_and_argv_uses_exact_absolute_path(self) -> None:
        spec = self.xtb_spec()
        self.assertEqual(
            spec.invocation["executable_identity"],
            {
                "absolute_path": XTB_EXECUTABLE_PATH,
                "size_bytes": len(XTB_EXECUTABLE_BYTES),
                "sha256": sha256(XTB_EXECUTABLE_BYTES).hexdigest(),
            },
        )
        self.assertEqual(spec.invocation["argv"][0], XTB_EXECUTABLE_PATH)

    def test_relative_mismatched_and_malformed_executable_identities_fail_closed(self) -> None:
        cases = (
            {"executable_path": "xtb"},
            {"executable_path": "/opt/auto-g16-fixtures/bin/not-xtb"},
            {"executable_sha256": "A" * 64},
            {"executable_size_bytes": 0},
        )
        defaults: dict[str, object] = {
            "program_kind": "xtb",
            "executable_path": XTB_EXECUTABLE_PATH,
            "executable_size_bytes": len(XTB_EXECUTABLE_BYTES),
            "executable_sha256": sha256(XTB_EXECUTABLE_BYTES).hexdigest(),
            "input_name": "input.xyz",
            "input_bytes": XYZ,
            "program_data": self.xtb_data(),
        }
        for change in cases:
            with self.subTest(change=change), self.assertRaises(
                execution.ExecutionValueError
            ):
                _prepare_program_execution_spec(**{**defaults, **change})  # type: ignore[arg-type]


class ProvisioningTests(LaneAFixture):
    def test_exact_three_classifications_and_no_mkdir(self) -> None:
        project = self.store.load_project("project-1")
        absent = self.local_root / "absent-project"
        classification, binding = _classify_project_target(
            project=project,
            reviewed_root=str(self.local_root),
            project_directory=str(absent),
            stored_binding=None,
        )
        self.assertEqual(classification, "ABSENT")
        self.assertIsNone(binding)
        self.assertFalse(absent.exists())

        unbound = self.local_root / "unbound-project"
        unbound.mkdir()
        classification, binding = _classify_project_target(
            project=project,
            reviewed_root=str(self.local_root),
            project_directory=str(unbound),
            stored_binding=None,
        )
        self.assertEqual(classification, "UNBOUND_EXISTING")
        self.assertIsNone(binding)

        durable = _binding_from_existing_local_target(
            project=project,
            reviewed_root=str(self.local_root),
            project_directory=str(self.local_project),
            evidence_identity="synthetic-inspection-1",
        )
        classification, replay = _classify_project_target(
            project=project,
            reviewed_root=str(self.local_root),
            project_directory=str(self.local_project),
            stored_binding=durable,
        )
        self.assertEqual(classification, "PRODUCT_BOUND_EXISTING")
        self.assertIs(replay, durable)

    def test_binding_persistence_is_idempotent_and_reopens_exactly(self) -> None:
        binding = _binding_from_existing_local_target(
            project=self.store.load_project("project-1"),
            reviewed_root=str(self.local_root),
            project_directory=str(self.local_project),
            evidence_identity="synthetic-inspection-1",
        )
        journal_path = self.root / "provisioning.sqlite3"
        with _ProvisioningJournal(journal_path) as journal:
            journal.append_binding(binding)
            journal.append_binding(binding)
            loaded = journal.load_binding("project-1")
            self.assertEqual(loaded.semantic_payload(), binding.semantic_payload())
        with _ProvisioningJournal(journal_path) as reopened:
            self.assertEqual(
                reopened.load_binding("project-1").semantic_payload(),
                binding.semantic_payload(),
            )

    def test_replacement_symlink_and_physical_drift_fail_closed(self) -> None:
        project = self.store.load_project("project-1")
        binding = _binding_from_existing_local_target(
            project=project,
            reviewed_root=str(self.local_root),
            project_directory=str(self.local_project),
            evidence_identity="synthetic-inspection-1",
        )
        original = self.local_root / "project-old"
        self.local_project.rename(original)
        self.local_project.mkdir()
        with self.assertRaisesRegex(execution.ExecutionValueError, "drifted"):
            _classify_project_target(
                project=project,
                reviewed_root=str(self.local_root),
                project_directory=str(self.local_project),
                stored_binding=binding,
            )
        self.local_project.rmdir()
        self.local_project.symlink_to(original, target_is_directory=True)
        with self.assertRaisesRegex(execution.ExecutionValueError, "real directory"):
            _classify_project_target(
                project=project,
                reviewed_root=str(self.local_root),
                project_directory=str(self.local_project),
                stored_binding=binding,
            )


class ProgramSnapshotTests(LaneAFixture):
    def test_successor_snapshot_replay_is_exact_and_contains_no_v30_records(self) -> None:
        spec = self.xtb_spec()
        first = self.successor_snapshot(spec=spec)
        replay = self.successor_snapshot(spec=spec)
        self.assertEqual(first.semantic_payload(), replay.semantic_payload())
        scheduler = first.scheduler_artifacts[0]
        self.assertEqual(
            scheduler["sha256"],
            __import__("hashlib").sha256(scheduler["content_utf8"].encode()).hexdigest(),
        )
        names = {item.name for item in fields(execution.ProgramExecutionSnapshot)}
        self.assertTrue(
            {"prepared_input_binding", "pbs_template_binding", "execution_snapshot"}.isdisjoint(names)
        )
        self.assertIn(
            f"exec {XTB_EXECUTABLE_PATH} input.xyz",
            scheduler["content_utf8"],
        )
        self.assertEqual(
            first.cwd_binding,
            {
                "location_kind": "server",
                "path": "/home/user100/SDL/project-1/attempt-1",
            },
        )

    def test_snapshot_cwd_is_the_exact_location_selected_by_fresh_proof(self) -> None:
        binding = self.physical_binding()
        snapshot = self.successor_snapshot(binding=binding)
        self.assertEqual(snapshot.cwd_binding["location_kind"], "server")
        self.assertEqual(snapshot.cwd_binding["path"], self.workspace().remote_attempt_dir)
        self.assertIn(
            f"cd -- {self.workspace().remote_attempt_dir}",
            snapshot.scheduler_artifacts[0]["content_utf8"],
        )

    def test_v30_and_successor_candidates_can_coexist_before_effect(self) -> None:
        v30 = self.v30_snapshot()
        successor = self.successor_snapshot()
        self.assertNotEqual(v30.submission_intent_id, successor.effect_intent_id)
        self.assertEqual(
            self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED
        )

    def test_v30_first_wins_and_successor_conflicts_before_second_effect(self) -> None:
        v30 = self.v30_snapshot()
        successor = self.successor_snapshot()
        effects: list[str] = []
        claim = self.store.record_submission_intent(
            "attempt-1", v30.submission_intent_id
        )
        if claim is core.SubmissionIntentClaim.WINNER:
            effects.append("v30")
        self.assertEqual(claim, core.SubmissionIntentClaim.WINNER)
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent(
                "attempt-1", successor.effect_intent_id
            )
        self.assertEqual(effects, ["v30"])

    def test_successor_first_wins_and_v30_conflicts_before_second_effect(self) -> None:
        v30 = self.v30_snapshot()
        successor = self.successor_snapshot()
        effects: list[str] = []
        claim = self.store.record_submission_intent(
            "attempt-1", successor.effect_intent_id
        )
        if claim is core.SubmissionIntentClaim.WINNER:
            effects.append("successor")
        self.assertEqual(claim, core.SubmissionIntentClaim.WINNER)
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent(
                "attempt-1", v30.submission_intent_id
            )
        self.assertEqual(effects, ["successor"])

    def test_successor_exact_replay_returns_replay_and_has_no_second_effect(self) -> None:
        successor = self.successor_snapshot()
        replay = self.successor_snapshot()
        effects: list[str] = []
        first_claim = self.store.record_submission_intent(
            "attempt-1", successor.effect_intent_id
        )
        if first_claim is core.SubmissionIntentClaim.WINNER:
            effects.append("successor")
        replay_claim = self.store.record_submission_intent(
            "attempt-1", replay.effect_intent_id
        )
        if replay_claim is core.SubmissionIntentClaim.WINNER:
            effects.append("successor-replay")
        self.assertEqual(first_claim, core.SubmissionIntentClaim.WINNER)
        self.assertEqual(replay_claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(effects, ["successor"])

    def test_runtime_identity_mismatch_fails_before_snapshot_issuance(self) -> None:
        mismatched = _prepare_program_execution_spec(
            program_kind="xtb",
            executable_path=XTB_EXECUTABLE_PATH,
            executable_size_bytes=len(XTB_EXECUTABLE_BYTES),
            executable_sha256="0" * 64,
            input_name="input.xyz",
            input_bytes=XYZ,
            program_data=self.xtb_data(),
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "runtime identity"):
            self.successor_snapshot(spec=mismatched)

    def test_stale_project_reattestation_rejects_replaced_directory(self) -> None:
        binding = self.physical_binding()
        proof = _reattest_project_binding(binding)
        original = self.local_root / "project-original"
        self.local_project.rename(original)
        self.local_project.mkdir()
        with self.assertRaisesRegex(execution.ExecutionValueError, "changed"):
            _prepare_program_execution_snapshot(
                self.store,
                attempt_id="attempt-1",
                calculation_plan_id="plan-1",
                resource_spec_id="resource-1",
                program_execution_spec=self.xtb_spec(),
                project_physical_binding=binding,
                resolved_resource_request=self.resources(),
                resolved_server_profile=self.resolved(),
                workspace_binding=self.workspace(),
                project_reattestation=proof,
            )

    def test_project_reattestation_is_single_use(self) -> None:
        binding = self.physical_binding()
        proof = self.synthetic_server_reattestation(binding)
        arguments = {
            "attempt_id": "attempt-1",
            "calculation_plan_id": "plan-1",
            "resource_spec_id": "resource-1",
            "program_execution_spec": self.xtb_spec(),
            "project_physical_binding": binding,
            "resolved_resource_request": self.resources(),
            "resolved_server_profile": self.resolved(),
            "workspace_binding": self.workspace(),
            "project_reattestation": proof,
        }
        _prepare_program_execution_snapshot(self.store, **arguments)  # type: ignore[arg-type]
        with self.assertRaisesRegex(execution.ExecutionValueError, "already consumed"):
            _prepare_program_execution_snapshot(
                self.store, **arguments  # type: ignore[arg-type]
            )

    def test_local_proof_cannot_authorize_the_resolved_server_target(self) -> None:
        binding = self.physical_binding()
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "resolved target location"
        ):
            _prepare_program_execution_snapshot(
                self.store,
                attempt_id="attempt-1",
                calculation_plan_id="plan-1",
                resource_spec_id="resource-1",
                program_execution_spec=self.xtb_spec(),
                project_physical_binding=binding,
                resolved_resource_request=self.resources(),
                resolved_server_profile=self.resolved(),
                workspace_binding=self.workspace(),
                project_reattestation=_reattest_project_binding(binding),
            )

    def test_mutating_a_live_local_proof_cannot_forge_server_authority(self) -> None:
        binding = self.physical_binding()
        proof = _reattest_project_binding(binding)
        server = next(
            item for item in binding.locations if item["location_kind"] == "server"
        )
        proof._location_kind = "server"
        proof._reviewed_root = str(server["reviewed_root"])
        proof._project_directory = str(server["project_directory"])
        proof._parent_identity = str(server["parent_physical_identity"])
        proof._target_identity = str(server["project_physical_identity"])
        proof._local_reinspection = False
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "resolved target location"
        ):
            _prepare_program_execution_snapshot(
                self.store,
                attempt_id="attempt-1",
                calculation_plan_id="plan-1",
                resource_spec_id="resource-1",
                program_execution_spec=self.xtb_spec(),
                project_physical_binding=binding,
                resolved_resource_request=self.resources(),
                resolved_server_profile=self.resolved(),
                workspace_binding=self.workspace(),
                project_reattestation=proof,
            )

    def test_snapshot_rejects_caller_asserted_project_freshness(self) -> None:
        binding = self.physical_binding()
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "fresh Project reattestation proof"
        ):
            _prepare_program_execution_snapshot(
                self.store,
                attempt_id="attempt-1",
                calculation_plan_id="plan-1",
                resource_spec_id="resource-1",
                program_execution_spec=self.xtb_spec(),
                project_physical_binding=binding,
                resolved_resource_request=self.resources(),
                resolved_server_profile=self.resolved(),
                workspace_binding=self.workspace(),
                project_reattestation=object(),  # type: ignore[arg-type]
            )


class OfflineBoundaryTests(unittest.TestCase):
    def test_lane_a_modules_have_no_live_or_effect_imports(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = "\n".join(
            (root / path).read_text(encoding="utf-8")
            for path in (
                "auto_g16/execution/program.py",
                "auto_g16/execution/project_provisioning.py",
            )
        )
        forbidden = (
            "subprocess",
            "paramiko",
            "socket",
            "qsub",
            "qdel",
            "mkdir(",
            "auto_g16.transport",
            "legacy_rtwin_pbs",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_no_generation_journal_or_ambient_executable_resolution(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = "\n".join(
            (root / path).read_text(encoding="utf-8")
            for path in (
                "auto_g16/execution/program.py",
                "auto_g16/execution/project_provisioning.py",
            )
        )
        for token in (
            "attempt_execution_generations",
            "claim_generation",
            "shutil.which",
            "os.environ",
            'exec xtb',
            'exec crest',
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
