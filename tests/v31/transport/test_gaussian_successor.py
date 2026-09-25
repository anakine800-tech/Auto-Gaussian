from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from hashlib import sha256
import base64
import copy
import json
import os
import unittest
from unittest.mock import DEFAULT, patch

import auto_g16.execution as execution
from auto_g16.execution import _gaussian_completion as gaussian
from auto_g16.execution import _program_completion as completion
from auto_g16.execution.program import (
    ProgramExecutionSpec,
    _ProgramExecutionSnapshotService,
    _prepare_program_execution_spec,
)
from auto_g16.execution.project_provisioning import (
    _ProjectProvisioningService,
    _SYNTHETIC_TEST_HARNESS_PRIVILEGE,
    _SyntheticRemoteProjectAttestor,
)
from tests.v3.execution.test_v31_lane_a import LaneAFixture
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport.test_program_completion import manifest
from tests.v31.transport.test_publisher_pilot_orchestration import (
    qualification_fixture,
    seal,
)


G16 = b"inert synthetic Gaussian executable identity\n"
G16_PATH = "/opt/auto-g16-fixtures/bin/g16"
TARGET_G16_PATH = "/opt/soft/g16/g16"
TARGET_G16_SIZE = 27186268
TARGET_G16_SHA256 = "ce86348e96640e032792d5479f6a7e7e79f3ff46f6a6dcac0718497222bfed43"
OPT = b"#p RHF/STO-3G opt integral=ultrafine scf=tight\n\nflow opt\n\n0 1\nH 0.0 0.0 0.0\n\n"
FREQ = b"%chk=gaussian.chk\n#p RHF/STO-3G freq integral=ultrafine scf=tight\n\nflow freq\n\n0 1\nH 0.0 0.0 0.0\n\n"


class GaussianSuccessorTests(LaneAFixture):
    def kwargs(self):
        return {
            "snapshot": self.snapshot,
            "program_transport_store": self.program_transport_store,
            "driver": self.driver,
        }

    def gaussian_profile(self, **changes):
        profile = self.profile()
        values = {
            "platform_paths": {
                **profile.platform_paths,
                "gaussian_executable_path": G16_PATH,
            },
            **changes,
        }
        return replace(profile, **values)

    def spec(self, *, stage="opt", raw=OPT, name="flow.gjf"):
        profile = execution.resolve_server_profile(self.gaussian_profile())
        return _prepare_program_execution_spec(
            program_kind="gaussian",
            executable_path=G16_PATH,
            executable_size_bytes=len(G16),
            executable_sha256=sha256(G16).hexdigest(),
            input_name=name,
            input_bytes=raw,
            program_data={"stage": stage},
            resolved_profile=profile,
            completion_mode=completion._MODE,
        )

    def test_opt_and_freq_close_to_exact_adapter(self):
        for stage, raw in (("opt", OPT), ("freq", FREQ)):
            with self.subTest(stage=stage):
                spec = self.spec(stage=stage, raw=raw)
                self.assertEqual(
                    (spec.program_kind, spec.adapter_id, spec.adapter_contract_version),
                    ("gaussian", "auto-g16-v31-gaussian", 3),
                )
                self.assertEqual(spec.program_data, {"stage": stage, "completion_mode": completion._MODE})
                self.assertEqual(spec.invocation["argv"], (G16_PATH,))
                self.assertEqual(
                    dict(spec.invocation["stdin"]),
                    {"mode": "exact-input", "logical_role": "gaussian-input"},
                )
                self.assertEqual(tuple(spec.invocation["environment"]), ({"name": "OMP_NUM_THREADS", "source": "resolved-resource-request.cores"},))
                self.assertEqual(spec.exact_inputs[0]["format"], "gaussian-gjf")
                self.assertEqual(spec.required_outputs[0]["portable_name"], "gaussian.log")
                self.assertEqual(spec.optional_outputs[0]["portable_name"], "gaussian.chk")
                spec.assert_identity_closed()

    def test_direct_construction_and_unknown_version_fail_closed(self):
        with self.assertRaises(TypeError):
            ProgramExecutionSpec()
        spec = self.spec()
        values = {
            key: getattr(spec, key)
            for key in (
                "program_kind", "adapter_id", "adapter_contract_version",
                "exact_inputs", "program_data", "invocation",
                "required_outputs", "optional_outputs",
            )
        }
        values["adapter_contract_version"] = 6
        with self.assertRaises(execution.ExecutionValueError):
            ProgramExecutionSpec._from_closed(**values)

    def test_input_adversarial_matrix(self):
        invalid = (
            (b"\xff", "opt"),
            (OPT.replace(b"\n", b"\r\n"), "opt"),
            (OPT + b"--Link1--\n#p hf/sto-3g opt\n", "opt"),
            (b"%oldchk=old.chk\n" + OPT, "opt"),
            (b"%chk=gaussian.chk\n%chk=gaussian.chk\n" + OPT, "opt"),
            (b"#p hf/sto-3g geom=allcheck guess=read freq\n\nt\n\n0 1\nH 0 0 0\n\n", "freq"),
            (b"#p hf/sto-3g geom=check freq\n\nt\n\n0 1\nH 0 0 0\n\n", "freq"),
            (b"#p hf/sto-3g geom=(check) freq\n\nt\n\n0 1\nH 0 0 0\n\n", "freq"),
            (b"#p hf/sto-3g geom=(allcheck,newdefinition) freq\n\nt\n\n0 1\nH 0 0 0\n\n", "freq"),
            (b"#p hf/sto-3g geom(check) freq\n\nt\n\n0 1\nH 0 0 0\n\n", "freq"),
            (b"#p hf/sto-3g guess=(read) freq\n\nt\n\n0 1\nH 0 0 0\n\n", "freq"),
            (b"#p hf/sto-3g opt=readfc\n\nt\n\n0 1\nH 0 0 0\n\n", "opt"),
            (b"#p hf/sto-3g opt=(readfc)\n\nt\n\n0 1\nH 0 0 0\n\n", "opt"),
            (b"#p hf/sto-3g opt(readfc)\n\nt\n\n0 1\nH 0 0 0\n\n", "opt"),
            (b"#p hf/sto-3g opt readfc\n\nt\n\n0 1\nH 0 0 0\n\n", "opt"),
            (OPT.replace(b"opt", b"freq", 1), "opt"),
            (OPT.replace(b"0 1\n", b"", 1), "opt"),
            (OPT.replace(b"H 0.0 0.0 0.0", b"H 0.0 0.0"), "opt"),
            (OPT + b"external basis\n", "opt"),
        )
        for raw, stage in invalid:
            with self.subTest(raw=raw[:30]), self.assertRaises(execution.ExecutionValueError):
                self.spec(stage=stage, raw=raw)

    def test_checkpoint_restart_is_rejected_before_spec_preparation(self):
        for option in (b"opt=restart", b"opt=(restart)", b"opt(restart)",
                       b"opt=(tight,restart)", b"opt = (Restart,MaxCycles=20)"):
            raw = b"%chk=gaussian.chk\n" + OPT.replace(b"opt", option, 1)
            with self.subTest(option=option), self.assertRaisesRegex(
                execution.ExecutionValueError, "depends on checkpoint state"
            ):
                self.spec(stage="opt", raw=raw)

    def test_frequency_checkpoint_reads_reject_and_self_contained_options_survive(self):
        for option in (b"freq=readfc", b"freq=(ReadFC)", b"freq(ReadFC)",
                       b"freq=(hinderedrotor,readfc)", b"freq=restart",
                       b"freq = (Numerical,Restart)"):
            raw = b"%chk=gaussian.chk\n" + OPT.replace(b"opt", option, 1)
            with self.subTest(option=option), self.assertRaisesRegex(
                execution.ExecutionValueError, "depends on checkpoint state"
            ):
                self.spec(stage="freq", raw=raw)
        for option in (b"freq", b"freq=raman", b"freq=(Numerical,Step=10)"):
            with self.subTest(option=option):
                self.spec(stage="freq", raw=OPT.replace(b"opt", option, 1))

    def test_program_data_and_filename_are_closed(self):
        for data in ({"stage": "sp"}, {"stage": "opt", "route": "caller"}):
            with self.subTest(data=data), self.assertRaises(execution.ExecutionValueError):
                _prepare_program_execution_spec(
                    program_kind="gaussian", executable_path=G16_PATH,
                    executable_size_bytes=len(G16), executable_sha256=sha256(G16).hexdigest(),
                    input_name="flow.gjf", input_bytes=OPT, program_data=data,
                    resolved_profile=execution.resolve_server_profile(self.gaussian_profile()),
                    completion_mode=completion._MODE,
                )
        with self.assertRaises(execution.ExecutionValueError):
            self.spec(name="flow.xyz")

    def test_unrelated_numeric_route_values_remain_accepted(self):
        raw = FREQ.replace(
            b"freq integral=ultrafine",
            b"freq temperature=298.15 scale=0.98 integral=ultrafine",
        )
        self.spec(stage="freq", raw=raw)

    def test_public_profile_shape_is_unchanged_and_executable_bytes_are_forbidden(self):
        profile = self.gaussian_profile()
        resolved = execution.resolve_server_profile(profile)
        self.assertFalse(hasattr(profile, "runtime_identity_declarations"))
        self.assertNotIn("gaussian", resolved.runtime_identities)
        with self.assertRaises(execution.ExecutionValueError):
            execution.resolve_server_profile(replace(profile, runtime_contents={**profile.runtime_contents, "gaussian": G16}))

    def test_profile_and_spec_identity_must_match(self):
        raw_profile = self.gaussian_profile()
        profile = execution.resolve_server_profile(
            replace(
                raw_profile,
                platform_paths={
                    **raw_profile.platform_paths,
                    "gaussian_executable_path": "/opt/other/g16",
                },
            )
        )
        with self.assertRaises(execution.ExecutionValueError):
            _prepare_program_execution_spec(
                program_kind="gaussian", executable_path=G16_PATH,
                executable_size_bytes=len(G16),
                executable_sha256=sha256(G16).hexdigest(), input_name="flow.gjf",
                input_bytes=OPT, program_data={"stage": "opt"},
                resolved_profile=profile, completion_mode=completion._MODE,
            )

    def test_wrapper_is_closed_and_compiles(self):
        wrapper, probe = gaussian._wrapper_sources()
        compile(wrapper, "gaussian-completion-wrapper", "exec")
        compile(probe, "gaussian-completion-probe", "exec")
        self.assertIn('spec["program_kind"]!="gaussian"', wrapper)
        self.assertIn('"program_kind":"gaussian"', wrapper)
        self.assertIn('"operation":spec["program_data"]["stage"]', wrapper)
        self.assertIn("stdin=inputfd", wrapper)
        self.assertNotIn("stdin=subprocess.DEVNULL", wrapper)
        self.assertNotIn("os.mkdir(", wrapper)
        self.assertIn('"GAUSS_SCRDIR":workspace', wrapper)
        self.assertIn(
            "publish(parent,workspace,token,canonical(receipt),workspace_chain",
            wrapper,
        )
        self.assertIn('"LD_LIBRARY_PATH":declared["LD_LIBRARY_PATH"]', wrapper)
        self.assertNotIn('"XTBPATH":config["xtb_data_path"]', wrapper)
        self.assertIn(gaussian._MATERIAL_SCHEMA, wrapper)
        self.assertIn("v31-completion-prebinding/6", wrapper)
        self.assertIn(gaussian._Q_SCHEMA, wrapper)
        for source in (wrapper, probe):
            self.assertNotIn('"workspace-root","server-python","xtb"', source)
            self.assertNotIn('runtime["xtb"]', source)
            self.assertNotIn('xtb_runtime_data_manifest', source)
            self.assertIn('runtime["gaussian"]["path"]', source)
            self.assertIn('("server_python","gaussian")', source)

        namespace = {"__name__": "gaussian_wrapper_fixture"}
        exec(compile(wrapper, "gaussian-completion-wrapper", "exec"), namespace)
        workspace = self.root / "gaussian-env-attempt"
        workspace.mkdir()
        parent = os.open(workspace, os.O_RDONLY)
        declared = {
            "g16root": "/opt/auto-g16-fixtures/bin",
            "GAUSS_EXEDIR": "/opt/auto-g16-fixtures/bin",
            "LD_LIBRARY_PATH": "/opt/auto-g16-fixtures/bin",
            "GAUSS_SCRDIR": {"mode": "attempt-workspace"},
        }
        qraw = completion._receipt_json(
            {"payload": {"runtime": {"gaussian_environment": declared}}}
        )
        config = {
            "material": {
                "publisher_qualification_base64": base64.b64encode(qraw).decode()
            },
            "spec": {
                "invocation": {
                    "executable_identity": {"absolute_path": G16_PATH}
                }
            },
            "cores": 8,
        }
        try:
            env = namespace["gaussian_environment"](config, str(workspace))
            self.assertEqual(
                set(env),
                {"OMP_NUM_THREADS", "g16root", "GAUSS_EXEDIR", "LD_LIBRARY_PATH", "GAUSS_SCRDIR"},
            )
            self.assertEqual(env["GAUSS_SCRDIR"], str(workspace))
            pinned, token, chain = namespace["pin_directory"](str(workspace))
            displaced = self.root / "displaced-attempt"
            workspace.rename(displaced)
            workspace.mkdir()
            try:
                with self.assertRaisesRegex(ValueError, "workspace-replaced"):
                    namespace["reattest_directory"](str(workspace), token, chain)
            finally:
                os.close(pinned)
                for descriptor in reversed(chain[:-1]):
                    os.close(descriptor)
                workspace.rmdir()
                displaced.rename(workspace)
        finally:
            os.close(parent)

    def qualified_case(
        self,
        *,
        g16_path=G16_PATH,
        g16_size=len(G16),
        g16_sha256=sha256(G16).hexdigest(),
        production_generation=False,
        base_profile_override=None,
        startup=False,
    ):
        from scripts import run_v31_publisher_pilot as controller

        if base_profile_override is None:
            base_profile = self.gaussian_profile()
            base_profile = replace(
                base_profile,
                runtime_contents={
                    **base_profile.runtime_contents,
                    completion._DEPLOYMENT_NAME: completion._receipt_json(manifest()),
                },
            )
        else:
            base_profile = base_profile_override
        base_profile = replace(
            base_profile,
            platform_paths={
                **base_profile.platform_paths,
                "gaussian_executable_path": g16_path,
            },
        )
        if startup:
            from auto_g16.transport import _gaussian_file_submit, _gaussian_submit, _bridge
            submit_owner = _gaussian_file_submit if startup == "file" else _gaussian_submit
            base_profile = replace(base_profile, runtime_contents={**{k:v for k,v in base_profile.runtime_contents.items() if k != _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME}, submit_owner.SOURCE_NAME: submit_owner.source_bytes()})
        payload, evidence = qualification_fixture(
            base_profile, queue="batch" if production_generation else "simple"
        )
        payload = copy.deepcopy(payload)
        profile = replace(
            base_profile,
            platform_paths={
                key: value for key, value in base_profile.platform_paths.items()
                if key not in {"xtb_executable_path", "xtb_data_path"}
            },
            runtime_contents={
                key: value for key, value in base_profile.runtime_contents.items()
                if key not in {"xtb", completion._DATA_NAME}
            },
        )
        from auto_g16.execution import _gaussian_file_carrier, _gaussian_startup
        owner = _gaussian_file_carrier if startup == "file" else _gaussian_startup if startup else gaussian
        wrapper, probe = owner._wrapper_sources()
        payload.update(
            schema=owner._Q_SCHEMA,
            contract_sha256=owner._CONTRACT_SHA256,
            profile_basis_sha256=completion._publisher_profile_basis(
                execution.resolve_server_profile(profile), gaussian=not startup, gstartup=startup is True, gfile=startup == "file"
            ),
        )
        payload["scope"] = {
            "backend": "legacy_rtwin_pbs",
            "program_kind": "gaussian",
            "adapter_id": "auto-g16-v31-gaussian",
            "adapter_contract_version": 5 if startup == "file" else 4 if startup else 3,
            "completion_mode": completion._MODE,
            "operations": ["opt", "freq"],
        }
        payload["implementation"]["wrapper_source"] = {
            "sha256": sha256(wrapper.encode()).hexdigest(),
            "size_bytes": len(wrapper.encode()),
        }
        payload["implementation"]["probe_source"] = {
            "sha256": sha256(probe.encode()).hexdigest(),
            "size_bytes": len(probe.encode()),
        }
        payload["runtime"]["gaussian"] = {
            "path": g16_path,
            "sha256": g16_sha256,
            "size_bytes": g16_size,
        }
        g16_root = g16_path.rsplit("/", 1)[0]
        payload["runtime"]["gaussian_environment"] = {
            "g16root": g16_root,
            "GAUSS_EXEDIR": g16_root,
            "LD_LIBRARY_PATH": g16_root,
            "GAUSS_SCRDIR": {"mode": "attempt-workspace"},
        }
        payload["runtime"].pop("xtb")
        payload["runtime"].pop("xtb_runtime_data_manifest")
        source = payload["hosts"][0]["locations"][-1]
        payload["hosts"][0]["locations"] = payload["hosts"][0]["locations"][:2] + [
            {
                **source,
                "role": "gaussian",
                "path": g16_path,
                "parent_chain": [source["object"]] * (len(g16_path.split("/")) - 1),
            }
        ]
        if startup:
            payload["implementation"]["loader_source"] = {"sha256": sha256(owner._LOADER_SOURCE.encode()).hexdigest(), "size_bytes": len(owner._LOADER_SOURCE.encode())}
            payload["delivery_probe"] = {**copy.deepcopy(payload["controller_probe"]), "case_id": "P09"}
        probe_index = completion._receipt_json(controller._probe_index(payload))
        payload["evidence_manifest_sha256"] = sha256(probe_index).hexdigest()
        evidence[payload["evidence_manifest_sha256"]] = probe_index
        qualified = replace(
            profile,
            runtime_contents={
                **profile.runtime_contents,
                owner._Q_NAME: seal(payload),
            },
        )
        target = execution.resolve_server_profile(qualified)
        spec = _prepare_program_execution_spec(
            program_kind="gaussian", executable_path=g16_path,
            executable_size_bytes=g16_size, executable_sha256=g16_sha256,
            input_name="flow.gjf", input_bytes=OPT, program_data={"stage": "opt"},
            resolved_profile=target, completion_mode=completion._MODE,
            startup_mode="short-entry-file-carrier-v2" if startup == "file" else "short-entry-physical-handoff-v1" if startup else None,
        )
        parent_identity = "gaussian-parent"
        project_identity = "gaussian-project"
        if production_generation:
            from tests.v31.transport.test_rtwin_successor_bridge import (
                directory_token,
            )

            parent_identity = directory_token(
                self.remote_project_dir.rsplit("/", 1)[0], inode=700
            )
            project_identity = directory_token(self.remote_project_dir, inode=800)
        attestor = _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
            target=target,
            observed_project_dir=self.remote_project_dir,
            observed_state="ABSENT",
            observed_parent_physical_identity=parent_identity,
            observed_project_physical_identity=None,
            provisioned_project_physical_identity=project_identity,
        )
        provisioning = _ProjectProvisioningService._from_privileged_synthetic_attestor(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE, attestor=attestor
        )
        binding = provisioning.provision_remote_project(
            project=self.store.load_project("project-1"), target=target,
            remote_project_dir=self.remote_project_dir,
            evidence_identity="synthetic-gaussian-project",
        )
        service = _ProgramExecutionSnapshotService._for_privileged_synthetic_tests(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE,
            project_provisioning=provisioning,
        )
        material = completion._prepare_publisher_pilot_rendering_material(
            qualified, target
        )
        if production_generation:
            from auto_g16.execution.project_provisioning import (
                _ProductionProvisioningJournal,
            )

            journal_root = self.root / "gaussian-production-generation"
            journal_root.mkdir()
            journal = _ProductionProvisioningJournal.create_new(
                journal_root / "project.sqlite3", approved_root=journal_root
            )
            self.addCleanup(journal.close)
            object.__setattr__(provisioning, "_journal", journal)
            binding_guard = patch.multiple(
                _ProjectProvisioningService,
                _assert_owned_binding=DEFAULT,
                _assert_production_authority=DEFAULT,
            )
        else:
            binding_guard = nullcontext()
        with binding_guard:
            resources = self.resources()
            if production_generation:
                resources = execution.ResolvedResourceRequest(
                    resource_spec=self.store.load_resource_spec("resource-1"),
                    cores=resources.cores,
                    memory_mb=resources.memory_mb,
                    walltime_seconds=resources.walltime_seconds,
                    queue="batch",
                )
            snapshot = service.prepare(
                self.store, attempt_id="attempt-1", calculation_plan_id="plan-1",
                resource_spec_id="resource-1", program_execution_spec=spec,
                project_physical_binding=binding,
                resolved_resource_request=resources,
                resolved_server_profile=target, workspace_binding=self.workspace(),
                completion_rendering_material=material,
            )
        return qualified, target, payload, evidence, spec, service, binding, material, snapshot

    def installed_case(self, qualified, target, payload, evidence, snapshot):
        from auto_g16.transport import _driver, _program_rtwin as rtwin
        from tests.v31.transport.test_publisher_pilot_orchestration import (
            PILOT,
            file_binding,
        )

        root = self.root / "gaussian-installation"
        root.mkdir()

        def write(name, raw):
            path = root / name
            path.write_bytes(raw)
            return file_binding(path)

        from auto_g16.execution import _gaussian_file_carrier, _gaussian_startup
        short = snapshot.program_execution_spec.adapter_contract_version in (4, 5)
        qname = _gaussian_file_carrier._Q_NAME if snapshot.program_execution_spec.adapter_contract_version == 5 else _gaussian_startup._Q_NAME if short else gaussian._Q_NAME
        qpin = write(qname, qualified.runtime_contents[qname])
        owner = b"SYNTHETIC Gaussian Q/4 owner acceptance\n"
        live = b"SYNTHETIC Gaussian Q/4 offline driver construction\n"
        evidence = {**evidence, sha256(owner).hexdigest(): owner, sha256(live).hexdigest(): live}
        pins = tuple(
            write(f"evidence-{index}.txt", raw)
            for index, raw in enumerate(evidence.values())
        )
        basis = {
            "schema": "auto-g16-v31-publisher-pilot-deployment/6" if snapshot.program_execution_spec.adapter_contract_version == 5 else "auto-g16-v31-publisher-pilot-deployment/5" if short else "auto-g16-v31-publisher-pilot-deployment/4",
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "resolved_server_profile_id": target.resolved_server_profile_id,
            "effective_config_sha256": target.effective_config_sha256,
            "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
            "qualification_payload_sha256": json.loads(
                qualified.runtime_contents[qname]
            )["payload_sha256"],
            "qualification_file_sha256": qpin.sha256,
            "qualification_size_bytes": qpin.size_bytes,
            "qualification_path": qpin.path,
            "qualification_parent_chain": [
                {"device": device, "inode": inode}
                for device, inode in qpin.parent_chain
            ],
            "qualification_file_identity": {
                "device": qpin.file_identity[0],
                "inode": qpin.file_identity[1],
            },
            "probe_evidence_manifest_sha256": payload["evidence_manifest_sha256"],
            "owner_q_acceptance_evidence_sha256": sha256(owner).hexdigest(),
            "pilot_live_gate_evidence_sha256": sha256(live).hexdigest(),
            "pilot_window": PILOT,
        }
        bpin = write(
            "v31-publisher-pilot-deployment.json",
            completion._receipt_json(basis),
        )
        installation = rtwin._FixedPublisherInstallation(
            bpin, qpin, pins, "a" * 40, "b" * 40
        )
        authority = _driver._DeploymentAuthority(
            None, None, None,
            target.resolved_server_profile_id,
            target.effective_config_sha256,
            snapshot.program_execution_snapshot_id,
            "c" * 64, 1, None, None,
        )
        return installation, authority

    def test_qualified_snapshot_renders_exact_gaussian_scheduler(self):
        qualified, target, _payload, _evidence, _spec, service, binding, material, snapshot = self.qualified_case()
        scheduler = snapshot.scheduler_artifacts[0]
        self.assertEqual(scheduler["portable_name"], "gaussian.pbs")
        self.assertTrue(scheduler["content_utf8"].startswith("#!/bin/bash\n# auto-g16-v31-scheduler/6\n"))
        encoded = scheduler["content_utf8"].splitlines()[2].split(": ", 1)[1]
        embedded = json.loads(base64.b64decode(encoded, validate=True))
        self.assertEqual(embedded["schema"], gaussian._MATERIAL_SCHEMA)
        self.assertNotIn("xtb_runtime_data_manifest_base64", embedded)
        snapshot.assert_identity_closed()
        mismatched = _prepare_program_execution_spec(
            program_kind="gaussian", executable_path=G16_PATH,
            executable_size_bytes=len(G16), executable_sha256="0" * 64,
            input_name="flow.gjf", input_bytes=OPT, program_data={"stage": "opt"},
            resolved_profile=target, completion_mode=completion._MODE,
        )
        with self.assertRaises(execution.ExecutionValueError):
            service.prepare(
                self.store, attempt_id="attempt-1", calculation_plan_id="plan-1",
                resource_spec_id="resource-1", program_execution_spec=mismatched,
                project_physical_binding=binding,
                resolved_resource_request=self.resources(),
                resolved_server_profile=target, workspace_binding=self.workspace(),
                completion_rendering_material=material,
            )

    def test_q4_environment_is_closed_and_does_not_accept_ambient_names(self):
        qualified, target, payload, _evidence, *_rest = self.qualified_case()
        self.assertEqual(
            set(payload["runtime"]["gaussian_environment"]),
            gaussian._ENVIRONMENT_KEYS,
        )
        mutations = (
            lambda env: env.update(PATH="/ambient/bin"),
            lambda env: env.update(HOME="/ambient/home"),
            lambda env: env.update(LD_LIBRARY_PATH="/tmp"),
            lambda env: env["GAUSS_SCRDIR"].update(relative_name="../tmp"),
            lambda env: env["GAUSS_SCRDIR"].update(mode="ambient"),
        )
        for mutate in mutations:
            altered = copy.deepcopy(payload)
            mutate(altered["runtime"]["gaussian_environment"])
            raw = seal(altered)
            profile = replace(
                qualified,
                runtime_contents={**qualified.runtime_contents, gaussian._Q_NAME: raw},
            )
            with self.subTest(mutation=mutate), self.assertRaises(
                execution.ExecutionValueError
            ):
                completion._prepare_publisher_pilot_rendering_material(
                    profile, execution.resolve_server_profile(profile)
                )
        self.assertEqual(
            payload["runtime"]["gaussian_environment"]["g16root"],
            G16_PATH.rsplit("/", 1)[0],
        )
        self.assertNotIn("xtb", target.runtime_identities)

    def test_fixed_deployment_v4_and_real_driver_construct_offline(self):
        from auto_g16.transport import _bridge, _driver, _program_rtwin as rtwin
        from auto_g16.transport.program import _ProgramTransportStore
        from tests.v3.transport import _fixtures as v30

        fixture = v30.TransportFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = fixture.proxyjump_profile(
            resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES
        )
        transport_manifest = json.loads(
            raw.runtime_contents["transport-deployment-manifest-v2.json"]
        )
        transport_manifest.update(
            schema="auto-g16-v3-transport-deployment-manifest/3",
            bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL,
        )
        transport_manifest["trust_roots"] = {
            key: value
            for key, value in transport_manifest["trust_roots"].items()
            if key in completion._ROOT_RULES
        }
        full_profile = replace(
            raw,
            platform_paths={
                **raw.platform_paths,
                "xtb_executable_path": lane.XTB_EXECUTABLE_PATH,
                "crest_executable_path": lane.CREST_EXECUTABLE_PATH,
                "xtb_data_path": lane.XTB_DATA_PATH,
                "gaussian_executable_path": TARGET_G16_PATH,
            },
            runtime_contents={
                _driver._TABLE_NAME: _driver._OPERATION_TABLE_BYTES,
                _driver._RESOURCE_DESCRIPTOR_NAME: v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES,
                completion._DEPLOYMENT_NAME: completion._receipt_json(transport_manifest),
                _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME: _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES,
                "xtb": lane.XTB_EXECUTABLE_BYTES,
                "crest": lane.CREST_EXECUTABLE_BYTES,
                completion._DATA_NAME: lane.xtb_runtime_data_manifest_bytes(),
            },
        )

        qualified, target, payload, evidence, _spec, _service, _binding, _material, snapshot = self.qualified_case(
            g16_path=TARGET_G16_PATH,
            g16_size=TARGET_G16_SIZE,
            g16_sha256=TARGET_G16_SHA256,
            production_generation=True,
            base_profile_override=full_profile,
        )
        installation, authority = self.installed_case(
            qualified, target, payload, evidence, snapshot
        )
        store_root = self.root / "gaussian-program-store"
        store_root.mkdir()
        program_store = _ProgramTransportStore._create_completion_store(
            store_root / "program.sqlite3", approved_root=store_root
        )
        self.addCleanup(program_store.close)
        with patch.object(rtwin, "_FIXED_PUBLISHER_INSTALLATION", installation), patch.object(
            rtwin, "_publisher_window", return_value=None
        ):
            installed = rtwin._read_fixed_publisher_deployment(authority, snapshot)
            try:
                self.assertEqual(
                    installed.qualification["payload"]["schema"], gaussian._Q_SCHEMA
                )
                self.assertEqual(installed.basis["schema"], "auto-g16-v31-publisher-pilot-deployment/4")
            finally:
                installed.close()
            driver = rtwin._RTWinProgramEffectDriver(
                snapshot=snapshot,
                current_profile=qualified,
                program_transport_store=program_store,
            )
            driver.close()

    def test_stage_submit_absence_capture_and_same_attempt_restore(self):
        from auto_g16 import core
        from auto_g16.execution import program_runtime as runtime
        from auto_g16.execution.project_provisioning import (
            _ProductionProvisioningJournal,
        )
        from auto_g16.execution.program_runtime import _ProgramExecutionPort
        from auto_g16.transport.program import _ProgramTransportStore
        from tests.v31.transport import test_program_composition as composition
        from tests.v31.transport import test_program_completion as old

        qualified, _target, _payload, _evidence, _spec, service, _binding, _material, snapshot = self.qualified_case()
        store_root = self.root / "gaussian-synthetic-effects"
        store_root.mkdir()
        program_store = _ProgramTransportStore._create_completion_store(
            store_root / "program.sqlite3", approved_root=store_root
        )
        self.addCleanup(program_store.close)
        driver = composition._Driver(
            {"gaussian.log": b"Normal termination of Gaussian 16\n"}
        )
        input_bytes = {"flow.gjf": OPT}
        scheduler_bytes = {
            "gaussian.pbs": snapshot.scheduler_artifacts[0]["content_utf8"].encode()
        }
        runtime._prepare_program_execution(
            self.store,
            snapshot=snapshot,
            program_transport_store=program_store,
            input_bytes=input_bytes,
            scheduler_artifact_bytes=scheduler_bytes,
            driver=driver,
        )
        result = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=qualified,
            confirmed_execution_snapshot_id=snapshot.program_execution_snapshot_id,
            prepared_input_bytes=OPT,
            pbs_template_bytes=scheduler_bytes["gaussian.pbs"],
            port=_ProgramExecutionPort(
                snapshot=snapshot,
                program_transport_store=program_store,
                driver=driver,
            ),
        )
        self.assertIs(result.claim, core.SubmissionIntentClaim.WINNER)
        self.assertEqual(
            [operation for operation, _request in driver.calls],
            ["ALLOCATE_WORKSPACE", "STAGE_EXACT_FILE", "STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE"],
        )

        self.snapshot = snapshot
        self.program_transport_store = program_store
        self.driver = driver
        self.input_bytes = input_bytes
        self.scheduler_bytes = scheduler_bytes
        journal_root = self.root / "gaussian-restore-journal"
        journal_root.mkdir()
        journal = _ProductionProvisioningJournal.create_new(
            journal_root / "project.sqlite3", approved_root=journal_root
        )
        self.addCleanup(journal.close)
        object.__setattr__(service._project_provisioning, "_journal", journal)
        calls = len(driver.calls)
        with patch.object(
            _ProjectProvisioningService, "_assert_production_authority", return_value=None
        ), patch.object(
            _ProjectProvisioningService, "_assert_owned_binding", return_value=None
        ):
            collected = service.restore_for_collection(
                self.store, reviewed_semantics=snapshot._approval_semantics()
            )
            reconciled = service.restore_for_reconciliation(
                self.store, reviewed_semantics=snapshot._approval_semantics()
            )
        self.assertEqual(collected, reconciled)
        self.assertEqual(collected, snapshot)
        self.assertEqual(len(driver.calls), calls)

        old.CompletionTests.publish(self)
        assessment = old.CompletionTests.collect(self)
        self.assertEqual(assessment.data["diagnostic"], "completed")
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertTrue(
            any(
                operation == "QUERY_SCHEDULER"
                and request["payload"].get("job_id") == "123.server"
                for operation, request in driver.calls
            )
        )

    def test_flow_completion_requires_exit_zero_and_normal_log(self):
        self.assertIsNone(gaussian._output_closure({"gaussian.log": b"Normal termination of Gaussian 16\n", "gaussian.chk": None}))
        self.assertEqual(gaussian._output_closure({"gaussian.log": b"started\n", "gaussian.chk": None}), "output-invalid")
        self.assertEqual(gaussian._output_closure({"gaussian.log": b"Normal termination of Gaussian 16\nError termination\n", "gaussian.chk": None}), "output-invalid")
        self.assertEqual(gaussian._output_closure({"gaussian.log": None, "gaussian.chk": None}), "output-incomplete")


if __name__ == "__main__":
    unittest.main()
