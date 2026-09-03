from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import inspect
from pathlib import Path
import tempfile
import unittest

import auto_g16.core as core
import auto_g16.execution as execution
from auto_g16.execution.program import (
    _CREST_SUPPORTED_V2_OPTION_TOKENS,
    _ADAPTER_REGISTRY,
    _ProgramExecutionSnapshotService,
    _prepare_program_execution_spec,
    _validate_crest_v2_option_tokens,
)
from auto_g16.execution.project_provisioning import (
    _ProjectProvisioningService,
    _ProvisioningJournal,
    _SYNTHETIC_TEST_HARNESS_PRIVILEGE,
    _SyntheticRemoteProjectAttestor,
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
        self.remote_project_dir = "/home/user100/SDL/project-1"
        self.remote_physical_identity = "opaque-server-project-v1"
        self.remote_attestor = (
            _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(
                privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
                target=self.resolved(),
                observed_project_dir=self.remote_project_dir,
                observed_state="ABSENT",
                observed_parent_physical_identity="opaque-server-parent-v1",
                observed_project_physical_identity=None,
                provisioned_project_physical_identity=(
                    self.remote_physical_identity
                ),
            )
        )
        self.project_provisioning = (
            _ProjectProvisioningService._from_privileged_synthetic_attestor(
                privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
                attestor=self.remote_attestor,
            )
        )
        self.project_binding = self.project_provisioning.provision_remote_project(
            project=self.store.load_project("project-1"),
            target=self.resolved(),
            remote_project_dir=self.remote_project_dir,
            evidence_identity="synthetic-remote-create",
        )
        self.snapshot_service = (
            _ProgramExecutionSnapshotService._for_privileged_synthetic_tests(
                privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
                project_provisioning=self.project_provisioning,
            )
        )

    def resolved(
        self,
        *,
        server_profile_id: str = "profile-v31",
        profile_revision: int = 1,
        target_host: str = "server.example",
        xtb_executable_path: str = XTB_EXECUTABLE_PATH,
        crest_executable_path: str = CREST_EXECUTABLE_PATH,
    ) -> execution.ResolvedServerProfile:
        return execution.resolve_server_profile(
            execution.ServerProfile(
                server_profile_id=server_profile_id,
                profile_revision=profile_revision,
                transport_kind="legacy_rtwin_pbs",
                target_host=target_host,
                target_port=22,
                remote_user="user100",
                jump_topology=[],
                host_key_policy="strict",
                batch_mode=True,
                identities_only=True,
                remote_root=execution.LEGACY_REMOTE_ROOT,
                platform_paths={
                    "rtwin_root": r"C:\RTWIN",
                    "xtb_executable_path": xtb_executable_path,
                    "crest_executable_path": crest_executable_path,
                },
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
        return self.project_binding

    def synthetic_authority(
        self,
        *,
        target: execution.ResolvedServerProfile | None = None,
        observed_project_dir: str | None = None,
        observed_state: str = "EXISTING",
        observed_parent_physical_identity: str = "opaque-synthetic-parent",
        observed_project_physical_identity: str | None = "opaque-synthetic-project",
        provisioned_project_physical_identity: str | None = None,
    ) -> tuple[
        _SyntheticRemoteProjectAttestor,
        _ProjectProvisioningService,
        _ProgramExecutionSnapshotService,
    ]:
        selected_target = self.resolved() if target is None else target
        selected_path = (
            self.remote_project_dir
            if observed_project_dir is None
            else observed_project_dir
        )
        attestor = _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
            target=selected_target,
            observed_project_dir=selected_path,
            observed_state=observed_state,
            observed_parent_physical_identity=observed_parent_physical_identity,
            observed_project_physical_identity=observed_project_physical_identity,
            provisioned_project_physical_identity=(
                provisioned_project_physical_identity
            ),
        )
        provisioning = (
            _ProjectProvisioningService._from_privileged_synthetic_attestor(
                privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
                attestor=attestor,
            )
        )
        snapshot_service = (
            _ProgramExecutionSnapshotService._for_privileged_synthetic_tests(
                privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
                project_provisioning=provisioning,
            )
        )
        return attestor, provisioning, snapshot_service

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
        target: execution.ResolvedServerProfile | None = None,
        workspace: execution.WorkspaceBinding | None = None,
        snapshot_service: _ProgramExecutionSnapshotService | None = None,
    ) -> execution.ProgramExecutionSnapshot:
        selected_spec = self.xtb_spec() if spec is None else spec
        selected_binding = self.physical_binding() if binding is None else binding
        selected_service = (
            self.snapshot_service if snapshot_service is None else snapshot_service
        )
        return selected_service.prepare(
            self.store,
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            resource_spec_id="resource-1",
            program_execution_spec=selected_spec,
            project_physical_binding=selected_binding,
            resolved_resource_request=self.resources(),
            resolved_server_profile=self.resolved() if target is None else target,
            workspace_binding=self.workspace() if workspace is None else workspace,
        )

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
            "provider": "crest",
            "sampling_mode": "imtd-gc",
            "engine_version": "3.0.2",
            "runtype_selector": "-v3",
            "model": "gfn2",
            "charge": 0,
            "unpaired_electrons": 0,
            "metadynamics_length_millipicoseconds": 5000,
            "cregen_energy_window_millikcal_per_mol": 6000,
            "cregen_rmsd_threshold_milliangstrom": 500,
            "cregen_temperature_millikelvin": 298150,
            "normal_md_temperature_millikelvin": 300000,
            "stochastic_policy": {
                "mode": "engine_managed_stochastic",
                "seed": None,
                "replay_semantics": (
                    "configuration_replay_not_bitwise_trajectory_replay"
                ),
            },
            "sampling_configuration_identity": "1" * 64,
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
            {
                "ProgramAdapter",
                "ProgramRegistry",
                "ExecutablePlugin",
                "ProjectProvisioningService",
                "ProjectNamespaceAttestor",
                "CurrentProjectProof",
            }.intersection(execution.__all__)
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
        self.assertEqual(
            {
                item.name
                for item in fields(execution.ProjectPhysicalBinding)
                if not item.name.startswith("_")
            },
            {
                "project_physical_binding_id",
                "project_id",
                "provisioning_contract_version",
                "transport_kind",
                "resolved_server_profile_id",
                "resolved_target_identity",
                "provisioning_authority_id",
                "locations",
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

    def test_crest_v2_closed_imtd_gc_fixture_has_exact_semantic_tokens(self) -> None:
        spec = self.crest_spec()
        self.assertEqual(spec.adapter_id, "auto-g16-v31-crest")
        self.assertEqual(spec.adapter_contract_version, 2)
        self.assertEqual(
            spec.invocation["argv"],
            (
                CREST_EXECUTABLE_PATH,
                "seed.xyz",
                "-v3",
                "-cross",
                "-gfn2",
                "-chrg",
                "0",
                "-uhf",
                "0",
                "-mdlen",
                "5.000",
                "-ewin",
                "6.000",
                "-rthr",
                "0.500",
                "-temp",
                "298.150",
                "-tnmd",
                "300.000",
            ),
        )
        self.assertEqual(spec.program_data["sampling_mode"], "imtd-gc")
        self.assertEqual(
            spec.program_data["runtype_selector"],
            "-v3",
        )
        self.assertEqual(spec.invocation["argv"].count("-v3"), 1)
        self.assertEqual(spec.invocation["argv"].count("-cross"), 1)
        self.assertNotIn("-nocross", spec.invocation["argv"])
        self.assertFalse(any(token.startswith("--") for token in spec.invocation["argv"]))
        self.assertEqual(
            spec.program_data["stochastic_policy"],
            {
                "mode": "engine_managed_stochastic",
                "seed": None,
                "replay_semantics": (
                    "configuration_replay_not_bitwise_trajectory_replay"
                ),
            },
        )
        self.assertFalse(any("ttconf" in token.lower() for token in spec.invocation["argv"]))
        self.assertTrue(
            {"-ttconf", "-ttseed", "-ttewin", "-ttrank", "-ttsweeps", "-ttgrid"}.isdisjoint(
                spec.invocation["argv"]
            )
        )
        self.assertEqual(
            tuple(item["portable_name"] for item in spec.required_outputs),
            ("crest.out", "crest_conformers.xyz"),
        )
        self.assertEqual(spec.optional_outputs[0]["portable_name"], "crest.energies")

    def test_crest_v2_option_tokens_use_the_exact_private_allowlist(self) -> None:
        def actual_option_tokens(spec: execution.ProgramExecutionSpec) -> tuple[str, ...]:
            tokens: list[str] = []
            for token in spec.invocation["argv"][2:]:
                if not token.startswith("-"):
                    continue
                try:
                    float(token)
                except ValueError:
                    tokens.append(token)
            return tuple(tokens)

        specs = tuple(
            self.crest_spec(
                model=model,
                charge=charge,
                unpaired_electrons=unpaired_electrons,
            )
            for model in ("gfn1", "gfn2")
            for charge in (-1, 0, 1)
            for unpaired_electrons in (0, 1)
        )
        emission_union: set[str] = set()
        for spec in specs:
            emitted = actual_option_tokens(spec)
            emission_union.update(emitted)
            self.assertEqual(emitted.count("-v3"), 1)
            self.assertEqual(emitted.count("-cross"), 1)
            self.assertNotIn("-nocross", emitted)
            self.assertFalse(any(token.startswith("--") for token in emitted))
            model = spec.program_data["model"]
            self.assertEqual(emitted.count(f"-{model}"), 1)
            self.assertNotIn("-gfn1" if model == "gfn2" else "-gfn2", emitted)
        self.assertEqual(emission_union, _CREST_SUPPORTED_V2_OPTION_TOKENS)
        self.assertNotIn("-nocross", _CREST_SUPPORTED_V2_OPTION_TOKENS)

        negative_charge = self.crest_spec(charge=-1)
        charge_index = negative_charge.invocation["argv"].index("-chrg")
        self.assertEqual(negative_charge.invocation["argv"][charge_index + 1], "-1")
        self.assertNotIn("-1", actual_option_tokens(negative_charge))

        for token in emission_union:
            with self.subTest(token=token), self.assertRaisesRegex(
                execution.ExecutionValueError, "single-dash allowlist"
            ):
                _validate_crest_v2_option_tokens(((f"--{token[1:]}", ()),))

    def test_crest_v1_ttconf_is_replay_readable_but_not_constructed_initially(self) -> None:
        old_data = {
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
        adapter = _ADAPTER_REGISTRY[("crest", "auto-g16-v31-crest", 1)]
        executable = {
            "absolute_path": CREST_EXECUTABLE_PATH,
            "size_bytes": len(CREST_EXECUTABLE_BYTES),
            "sha256": sha256(CREST_EXECUTABLE_BYTES).hexdigest(),
        }
        invocation, required, optional = adapter[3](executable, "seed.xyz", old_data)
        legacy = execution.ProgramExecutionSpec._from_closed(
            program_kind="crest",
            adapter_id="auto-g16-v31-crest",
            adapter_contract_version=1,
            exact_inputs=(
                {
                    "logical_role": "structure",
                    "portable_name": "seed.xyz",
                    "format": "xyz",
                    "sha256": sha256(XYZ).hexdigest(),
                    "size_bytes": len(XYZ),
                },
            ),
            program_data=old_data,
            invocation=invocation,
            required_outputs=required,
            optional_outputs=optional,
        )
        legacy.assert_identity_closed()
        self.assertEqual(legacy.adapter_contract_version, 1)
        self.assertIn("-ttconf", legacy.invocation["argv"])
        self.assertEqual(self.crest_spec().adapter_contract_version, 2)

    def test_crest_v2_identity_cannot_carry_ttconf_invocation_bytes(self) -> None:
        spec = self.crest_spec()
        invocation = dict(spec.invocation)
        invocation["argv"] = (
            CREST_EXECUTABLE_PATH,
            "seed.xyz",
            "-ttconf",
            "normal",
            "-gfn2",
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "exact adapter"
        ):
            execution.ProgramExecutionSpec._from_closed(
                program_kind="crest",
                adapter_id="auto-g16-v31-crest",
                adapter_contract_version=2,
                exact_inputs=spec.exact_inputs,
                program_data=spec.program_data,
                invocation=invocation,
                required_outputs=spec.required_outputs,
                optional_outputs=spec.optional_outputs,
            )

    def test_crest_v2_identity_cannot_omit_explicit_v3_selector(self) -> None:
        spec = self.crest_spec()
        invocation = dict(spec.invocation)
        invocation["argv"] = tuple(
            token for token in spec.invocation["argv"] if token != "-v3"
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "exact adapter"):
            execution.ProgramExecutionSpec._from_closed(
                program_kind="crest",
                adapter_id="auto-g16-v31-crest",
                adapter_contract_version=2,
                exact_inputs=spec.exact_inputs,
                program_data=spec.program_data,
                invocation=invocation,
                required_outputs=spec.required_outputs,
                optional_outputs=spec.optional_outputs,
            )

    def test_crest_v2_semantic_options_are_distinct_and_unsupported_inputs_reject(self) -> None:
        base = self.crest_spec()
        mutations = {
            "metadynamics_length_millipicoseconds": (6000, "-mdlen", "6.000"),
            "cregen_energy_window_millikcal_per_mol": (7000, "-ewin", "7.000"),
            "cregen_rmsd_threshold_milliangstrom": (600, "-rthr", "0.600"),
            "cregen_temperature_millikelvin": (310000, "-temp", "310.000"),
            "normal_md_temperature_millikelvin": (350000, "-tnmd", "350.000"),
        }
        for field, (value, option, rendered) in mutations.items():
            with self.subTest(field=field):
                changed = self.crest_spec(**{field: value})
                self.assertNotEqual(
                    changed.program_execution_spec_id,
                    base.program_execution_spec_id,
                )
                option_index = changed.invocation["argv"].index(option)
                self.assertEqual(changed.invocation["argv"][option_index + 1], rendered)
        self.assertTrue(
            {"--mdlen", "--ewin", "--rthr", "--temp", "--tnmd"}.isdisjoint(
                base.invocation["argv"]
            )
        )
        for changes in (
            {"runtype_selector": "-v2i"},
            {"engine_version": "3.0.1"},
            {"random_seed": 17},
            {
                "stochastic_policy": {
                    "mode": "explicit_seed",
                    "seed": 17,
                    "replay_semantics": "bitwise",
                }
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(
                execution.ExecutionValueError
            ):
                self.crest_spec(**changes)

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
            {"executable_path": "/usr/local/bin/xtb"},
            {"executable_path": "/Users/<LOCAL_USER>/project/xtb"},
            {"executable_path": r"C:\Programs\xtb.exe"},
            {"executable_path": "/tmp/PATH/xtb"},
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
    def test_binding_is_only_the_exact_remote_final_server_namespace(self) -> None:
        binding = self.physical_binding()
        self.assertEqual(binding.transport_kind, "legacy_rtwin_pbs")
        self.assertEqual(binding.resolved_server_profile_id, self.resolved().resolved_server_profile_id)
        self.assertEqual(binding.resolved_target_identity, self.resolved().target_identity)
        self.assertEqual(binding.remote_root, execution.LEGACY_REMOTE_ROOT)
        self.assertEqual(binding.remote_project_dir, self.remote_project_dir)
        self.assertEqual(binding.project_physical_identity, self.remote_physical_identity)
        self.assertEqual(len(binding.locations), 1)
        self.assertEqual(
            set(binding.locations[0]),
            {
                "location_kind",
                "reviewed_root",
                "project_directory",
                "provisioning_disposition",
                "parent_physical_identity",
                "project_physical_identity",
                "evidence_identity",
            },
        )
        self.assertEqual(binding.locations[0]["location_kind"], "server")
        self.assertEqual(binding.locations[0]["provisioning_disposition"], "ABSENT")
        payload_text = repr(binding.semantic_payload())
        self.assertNotIn(str(self.local_project), payload_text)
        self.assertNotIn("st_dev", payload_text)
        self.assertNotIn("st_ino", payload_text)

    def test_exact_three_provisioning_branches_and_no_implicit_adoption(self) -> None:
        replay_state, replay = self.project_provisioning.classify_remote_project(
            project=self.store.load_project("project-1"),
            target=self.resolved(),
            remote_project_dir=self.remote_project_dir,
            stored_binding=self.physical_binding(),
        )
        self.assertEqual(replay_state, "PRODUCT_BOUND_EXISTING")
        self.assertIs(replay, self.physical_binding())
        self.assertEqual(self.remote_attestor._provision_count, 1)
        self.assertIs(
            self.project_provisioning.provision_remote_project(
                project=self.store.load_project("project-1"),
                target=self.resolved(),
                remote_project_dir=self.remote_project_dir,
                evidence_identity="ignored-on-replay",
                stored_binding=self.physical_binding(),
            ),
            self.physical_binding(),
        )
        self.assertEqual(self.remote_attestor._provision_count, 1)

        absent_attestor, absent_owner, _snapshot_service = self.synthetic_authority(
            observed_state="ABSENT",
            observed_project_physical_identity=None,
            provisioned_project_physical_identity="new-synthetic-project",
        )
        absent_state, absent_binding = absent_owner.classify_remote_project(
            project=self.store.load_project("project-1"),
            target=self.resolved(),
            remote_project_dir=self.remote_project_dir,
            stored_binding=None,
        )
        self.assertEqual(absent_state, "ABSENT")
        self.assertIsNone(absent_binding)
        self.assertEqual(absent_attestor._provision_count, 0)

        existing_attestor, unbound_owner, _snapshot_service = self.synthetic_authority(
            observed_state="EXISTING",
            observed_project_physical_identity="unbound-existing-project",
        )
        unbound_state, unbound_binding = unbound_owner.classify_remote_project(
            project=self.store.load_project("project-1"),
            target=self.resolved(),
            remote_project_dir=self.remote_project_dir,
            stored_binding=None,
        )
        self.assertEqual(unbound_state, "UNBOUND_EXISTING")
        self.assertIsNone(unbound_binding)
        with self.assertRaisesRegex(execution.ExecutionValueError, "Owner adoption"):
            unbound_owner.provision_remote_project(
                project=self.store.load_project("project-1"),
                target=self.resolved(),
                remote_project_dir=self.remote_project_dir,
                evidence_identity="implicit-adoption-forbidden",
            )
        self.assertEqual(existing_attestor._provision_count, 0)

    def test_binding_persistence_is_idempotent_and_reopens_exactly(self) -> None:
        binding = self.physical_binding()
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

    def test_local_observation_cannot_create_a_remote_project_binding(self) -> None:
        _attestor, local_only, _snapshot_service = self.synthetic_authority(
            observed_project_dir=str(self.local_project)
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "exact remote Project target"
        ):
            local_only.provision_remote_project(
                project=self.store.load_project("project-1"),
                target=self.resolved(),
                remote_project_dir=self.remote_project_dir,
                evidence_identity="caller-local-observation",
            )

    def test_remote_project_path_must_be_below_the_profile_root(self) -> None:
        _attestor, local_only, _snapshot_service = self.synthetic_authority(
            observed_project_dir=str(self.local_project)
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "not strictly contained"
        ):
            local_only.provision_remote_project(
                project=self.store.load_project("project-1"),
                target=self.resolved(),
                remote_project_dir=str(self.local_project),
                evidence_identity="caller-local-observation",
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

    def test_snapshot_cwd_is_exact_remote_attempt_dir_and_pbs_has_no_cd(self) -> None:
        binding = self.physical_binding()
        snapshot = self.successor_snapshot(binding=binding)
        self.assertEqual(snapshot.cwd_binding["location_kind"], "server")
        self.assertEqual(snapshot.cwd_binding["path"], self.workspace().remote_attempt_dir)
        scheduler = snapshot.scheduler_artifacts[0]["content_utf8"]
        self.assertNotIn("cd ", scheduler)
        self.assertNotIn(self.workspace().remote_attempt_dir, scheduler)
        self.assertNotIn(str(self.local_project), scheduler)

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
        with self.assertRaisesRegex(execution.ExecutionValueError, "profile executable"):
            self.successor_snapshot(spec=mismatched)

    def test_executable_path_is_owned_by_the_exact_resolved_profile(self) -> None:
        for path in (
            "/usr/local/bin/xtb",
            "/Users/<LOCAL_USER>/project/xtb",
            r"C:\Programs\xtb.exe",
        ):
            with self.subTest(path=path), self.assertRaises(
                execution.ExecutionValueError
            ):
                self.successor_snapshot(
                    target=self.resolved(xtb_executable_path=path)
                )

    def test_replaced_remote_project_rejects_snapshot_issuance(self) -> None:
        binding = self.physical_binding()
        self.remote_attestor._replace_fixture_identity(
            target=self.resolved(),
            remote_project_dir=self.remote_project_dir,
            observed_project_physical_identity="opaque-server-project-replaced",
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "exact binding"):
            self.successor_snapshot(binding=binding)

    def test_private_current_proof_is_target_scoped_and_single_use(self) -> None:
        binding = self.physical_binding()
        proof = self.project_provisioning._attest_current(binding, self.resolved())
        self.assertEqual(
            self.project_provisioning._consume_current(
                binding=binding, target=self.resolved(), proof=proof
            ),
            self.remote_project_dir,
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "already consumed"):
            self.project_provisioning._consume_current(
                binding=binding, target=self.resolved(), proof=proof
            )

    def test_local_observation_cannot_authorize_remote_snapshot(self) -> None:
        binding = self.physical_binding()
        _attestor, _local_owner, local_snapshot_service = self.synthetic_authority(
            observed_project_dir=str(self.local_project)
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "owning provisioning authority"
        ):
            self.successor_snapshot(
                binding=binding, snapshot_service=local_snapshot_service
            )

    def test_cross_target_and_profile_revision_cannot_authorize_binding(self) -> None:
        binding = self.physical_binding()
        other_target = self.resolved(target_host="other-server.example")
        _attestor, _owner, other_snapshot_service = self.synthetic_authority(
            target=other_target,
            observed_project_dir=self.remote_project_dir,
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "owning"):
            self.successor_snapshot(
                binding=binding,
                target=other_target,
                snapshot_service=other_snapshot_service,
            )
        revised_target = self.resolved(profile_revision=2)
        _attestor, _owner, revised_snapshot_service = self.synthetic_authority(
            target=revised_target,
            observed_project_dir=self.remote_project_dir,
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "owning"):
            self.successor_snapshot(
                binding=binding,
                target=revised_target,
                snapshot_service=revised_snapshot_service,
            )

    def test_cross_path_observation_and_workspace_path_drift_reject(self) -> None:
        binding = self.physical_binding()
        _attestor, _owner, cross_path_snapshot_service = self.synthetic_authority(
            observed_project_dir="/home/user100/SDL/other-project"
        )
        with self.assertRaisesRegex(
            execution.ExecutionValueError, "owning provisioning authority"
        ):
            self.successor_snapshot(
                binding=binding, snapshot_service=cross_path_snapshot_service
            )
        wrong_workspace = execution.WorkspaceBinding(
            project=self.store.load_project("project-1"),
            attempt_id="attempt-1",
            local_approved_root=str(self.local_root),
            local_attempt_dir=str(self.local_project / "attempt-1"),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir="/home/user100/SDL/other-project/attempt-1",
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "exact remote"):
            self.successor_snapshot(binding=binding, workspace=wrong_workspace)

    def test_snapshot_accepts_no_caller_proof_or_raw_current_identity(self) -> None:
        parameters = inspect.signature(self.snapshot_service.prepare).parameters
        for forbidden in (
            "project_provisioning_service",
            "project_reattestation",
            "proof",
            "current_identity",
            "st_dev",
            "st_ino",
        ):
            self.assertNotIn(forbidden, parameters)
        binding = self.physical_binding()
        with self.assertRaisesRegex(
            TypeError, "unexpected keyword argument"
        ):
            self.snapshot_service.prepare(
                self.store,
                attempt_id="attempt-1",
                calculation_plan_id="plan-1",
                resource_spec_id="resource-1",
                program_execution_spec=self.xtb_spec(),
                project_physical_binding=binding,
                resolved_resource_request=self.resources(),
                resolved_server_profile=self.resolved(),
                workspace_binding=self.workspace(),
                project_reattestation={  # type: ignore[call-arg]
                    "current_identity": self.remote_physical_identity
                },
            )

    def test_second_service_from_persisted_raw_identity_cannot_claim_freshness(self) -> None:
        binding = self.physical_binding()
        journal_path = self.root / "second-service.sqlite3"
        with _ProvisioningJournal(journal_path) as journal:
            journal.append_binding(binding)
            persisted = journal.load_binding("project-1")
        _attestor, _owner, second_snapshot_service = self.synthetic_authority(
            observed_state="EXISTING",
            observed_parent_physical_identity=persisted.parent_physical_identity,
            observed_project_physical_identity=persisted.project_physical_identity,
        )
        with self.assertRaisesRegex(execution.ExecutionValueError, "owning"):
            self.successor_snapshot(
                binding=persisted,
                snapshot_service=second_snapshot_service,
            )

    def test_snapshot_embedded_authorities_and_payload_are_self_authenticating(self) -> None:
        _attestor, alternate_owner, _snapshot_service = self.synthetic_authority(
            observed_project_dir="/home/user100/SDL/project-2",
            observed_state="ABSENT",
            observed_project_physical_identity=None,
            provisioned_project_physical_identity="alternate-project-physical",
        )
        alternate_binding = alternate_owner.provision_remote_project(
            project=self.store.load_project("project-1"),
            target=self.resolved(),
            remote_project_dir="/home/user100/SDL/project-2",
            evidence_identity="alternate-binding",
        )
        alternate_resources = execution.ResolvedResourceRequest(
            resource_spec=self.store.load_resource_spec("resource-1"),
            cores=4,
            memory_mb=12_288,
            walltime_seconds=3_600,
            queue="simple",
        )
        alternate_workspace = execution.WorkspaceBinding(
            project=self.store.load_project("project-1"),
            attempt_id="attempt-1",
            local_approved_root=str(self.local_root),
            local_attempt_dir=str(self.local_project / "attempt-1"),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir="/home/user100/SDL/project-2/attempt-1",
        )
        mutations = (
            ("attempt_id", "attempt-other"),
            ("calculation_plan_id", "plan-other"),
            ("calculation_plan_revision", 2),
            ("program_execution_spec", self.xtb_spec(charge=-1)),
            ("project_physical_binding", alternate_binding),
            ("resolved_resource_request", alternate_resources),
            (
                "resolved_server_profile",
                self.resolved(profile_revision=2),
            ),
            ("workspace_binding", alternate_workspace),
            ("cwd_binding", {"location_kind": "server", "path": "/tmp"}),
            ("scheduler_artifacts", ()),
        )
        for field_name, replacement in mutations:
            with self.subTest(field_name=field_name):
                snapshot = self.successor_snapshot()
                object.__setattr__(snapshot, field_name, replacement)
                with self.assertRaises(execution.ExecutionValueError):
                    snapshot.assert_identity_closed()


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
