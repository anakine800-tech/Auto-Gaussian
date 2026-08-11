#!/usr/bin/env python3
"""Offline hostile coverage for Phase 1A subsystem/Gaussian closure."""
from __future__ import annotations

import copy
import ast
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_direct_trusted_session_composition import PortableSessionFixture

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import direct_gaussian_runtime_identity as GAUSSIAN  # noqa: E402
import direct_one_hop_transport as W5  # noqa: E402
import direct_root_owner_contract as W1  # noqa: E402
import direct_read_subsystem_dispatcher as READ_DISPATCH  # noqa: E402
import direct_shared_fixed_ssh_channel as CHANNEL  # noqa: E402
import direct_subsystem_bootstrap as BOOTSTRAP  # noqa: E402
import skill_package as PACKAGE  # noqa: E402


class DirectSubsystemGaussianClosureTests(unittest.TestCase):
    @staticmethod
    def _stage_clean_repository(parent: Path) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        staged = parent / "repository"
        shutil.copytree(
            ROOT,
            staged,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
        )
        return staged

    def test_historical_draft_schema_bytes_are_unchanged(self) -> None:
        expected = {
            "direct-one-hop-transport-profile.schema.json":
                "18d0d97becf7aeb17f63e8eeae25deb72e356a9a729bfbaaf2e5a273b14e0d76",
            "reviewed-direct-pbs-script.schema.json":
                "7324fc35ac8e4dead83958537c4925a2786373acfbeca0f552fcba76a0ced265",
            "direct-profile-policy.schema.json":
                "ebcbf637e29f0b8beb853a37d49ea21298e73d9835edf39f36b8e59c95086a3f",
            "stable-root-identity-evidence.schema.json":
                "e293e737879810a6cb143b386b9ef185c56a28e58ec3d36b4cb873ec52eaad33",
            "execution-profile-v3.schema.json":
                "9adf9aa49f17a8c26ad9858bb0837df75a8ba6b5926864833ea42a20caf1d299",
            "execution-authorization-v3.schema.json":
                "e2ba3dc843627b69fb1836c2717db83385309d5129d789426838b66fa4659432",
        }
        for name, sha256 in expected.items():
            raw = (ROOT / "contracts/direct-execution" / name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), sha256)

    def test_profile_gaussian_derivation_helper_is_currentness_bound(self) -> None:
        original = W1.build_profile_policy_with_gaussian_runtime
        try:
            W1.build_profile_policy_with_gaussian_runtime = lambda **_kwargs: {}
            with self.assertRaisesRegex(W1.DirectRootOwnerError, "function identity"):
                W1._assert_owner_binding()
        finally:
            W1.build_profile_policy_with_gaussian_runtime = original
        W1._assert_owner_binding()
        with tempfile.TemporaryDirectory(prefix="auto-g16-policy-successor-") as raw:
            root = Path(raw).resolve()
            executable = root / "g16"
            executable.write_bytes(b"synthetic\n")
            executable.chmod(0o755)
            info = executable.stat()
            gaussian = GAUSSIAN.observe_reviewed_gaussian_executable(
                str(executable), expected_uid=info.st_uid, expected_gid=info.st_gid,
                expected_mode=0o755,
            )
            successor = W1.build_profile_policy_with_gaussian_runtime(
                profile_id="successor-policy", declared_allowed_root=str(root),
                transport_identity_binding_sha256="a" * 64,
                gaussian_runtime_binding=gaussian, resource_catalog_sha256="b" * 64,
            )
            legacy = W1.build_profile_policy(
                profile_id="successor-policy", declared_allowed_root=str(root),
                transport_identity_binding_sha256="a" * 64,
                gaussian_runtime_binding_sha256=gaussian["binding_payload_sha256"],
                resource_catalog_sha256="b" * 64,
            )
            self.assertEqual(successor["schema"], W1.SUCCESSOR_PROFILE_POLICY_SCHEMA)
            self.assertEqual(successor["gaussian_runtime_binding"], gaussian)
            self.assertEqual(legacy["schema"], W1.PROFILE_POLICY_SCHEMA)
            self.assertNotEqual(W1.canonical_bytes(successor), W1.canonical_bytes(legacy))

    def test_submit_malformed_frame_stops_before_trusted_session_and_qsub(self) -> None:
        calls = {"compose": 0, "qsub": 0}

        def forbidden_compose(_artifacts: object) -> object:
            calls["compose"] += 1
            raise AssertionError("trusted session must not start")

        def forbidden_qsub(*_args: object, **_kwargs: object) -> object:
            calls["qsub"] += 1
            raise AssertionError("qsub must not start")

        malformed_reader = mock.Mock(return_value={})
        original_reader = W5._FROZEN_FRAME_READER
        original_composer = W5._FROZEN_SESSION_COMPOSER
        original_qsub = W5._FROZEN_PRODUCTION_QSUB
        try:
            W5._read_framed_descriptor = malformed_reader
            W5._FROZEN_FRAME_READER = malformed_reader
            W5.SESSION.compose_production_in_fixed_clean_exec_once = forbidden_compose
            W5._FROZEN_SESSION_COMPOSER = forbidden_compose
            W5._production_qsub_once = forbidden_qsub
            W5._FROZEN_PRODUCTION_QSUB = forbidden_qsub
            self.assertEqual(W5.server_subsystem_once(), 3)
            self.assertEqual(calls, {"compose": 0, "qsub": 0})
        finally:
            W5._read_framed_descriptor = original_reader
            W5._FROZEN_FRAME_READER = original_reader
            W5.SESSION.compose_production_in_fixed_clean_exec_once = original_composer
            W5._FROZEN_SESSION_COMPOSER = original_composer
            W5._production_qsub_once = original_qsub
            W5._FROZEN_PRODUCTION_QSUB = original_qsub

    def test_read_entry_and_dispatcher_have_no_qsub_call_surface(self) -> None:
        for relative in (
            "scripts/direct_read_subsystem_entrypoint.py",
            "scripts/direct_read_subsystem_dispatcher.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            ast.parse(source)
            self.assertNotIn("qsub", source.lower())

    def test_read_dispatcher_q1_f1_malformed_frames_keep_qsub_zero(self) -> None:
        qsub_calls = 0

        def forbidden_qsub(*_args: object, **_kwargs: object) -> object:
            nonlocal qsub_calls
            qsub_calls += 1
            raise AssertionError("read dispatch must never call qsub")

        original = W5._production_qsub_once
        frozen = W5._FROZEN_PRODUCTION_QSUB
        try:
            W5._production_qsub_once = forbidden_qsub
            W5._FROZEN_PRODUCTION_QSUB = forbidden_qsub
            for operation in ("acquire_exact_qstat", "fetch_terminal_minimum_bundle"):
                frame = CHANNEL._canonical_frame({"operation": operation})
                budget, _deadline = READ_DISPATCH._issue_dispatch_budget()
                READ_DISPATCH._bind_dispatch_budget_once(budget, frame, operation)
                read_fd, write_fd = os.pipe()
                try:
                    with self.assertRaises((ValueError, TypeError)):
                        READ_DISPATCH._dispatch_request_frame_once(frame, write_fd, budget)
                finally:
                    os.close(read_fd)
                    os.close(write_fd)
                    READ_DISPATCH._abandon_dispatch_budget(budget)
            self.assertEqual(qsub_calls, 0)
        finally:
            W5._production_qsub_once = original
            W5._FROZEN_PRODUCTION_QSUB = frozen

    def test_gaussian_owner_replays_nofollow_identity_and_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-gaussian-owner-") as raw:
            root = Path(raw).resolve()
            executable = root / "gaussian" / "g16"
            executable.parent.mkdir()
            executable.write_bytes(b"synthetic executable\n")
            executable.chmod(0o755)
            info = executable.stat()
            binding = GAUSSIAN.observe_reviewed_gaussian_executable(
                str(executable), expected_uid=info.st_uid, expected_gid=info.st_gid,
                expected_mode=0o755,
            )
            descriptor = GAUSSIAN.replay_gaussian_executable_identity(binding)
            os.close(descriptor)
            self.assertFalse(binding["authority"]["authorizes_effect"])
            self.assertFalse(binding["pbs_boundary"]["descriptor_survives_qsub"])
            executable.chmod(0o700)
            with self.assertRaisesRegex(GAUSSIAN.DirectGaussianRuntimeIdentityError, "identity"):
                GAUSSIAN.replay_gaussian_executable_identity(binding)

    def test_gaussian_owner_rejects_symlink_and_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-gaussian-symlink-") as raw:
            root = Path(raw).resolve()
            real = root / "real"
            real.mkdir()
            executable = real / "g16"
            executable.write_bytes(b"x")
            executable.chmod(0o755)
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises((OSError, GAUSSIAN.DirectGaussianRuntimeIdentityError)):
                GAUSSIAN.observe_reviewed_gaussian_executable(
                    str(link / "g16"), expected_uid=executable.stat().st_uid,
                    expected_gid=executable.stat().st_gid, expected_mode=0o755,
                )
            with self.assertRaisesRegex(GAUSSIAN.DirectGaussianRuntimeIdentityError, "fields"):
                GAUSSIAN.validate_gaussian_runtime_binding({"schema": GAUSSIAN.SCHEMA})

    def test_pbs_successor_rejects_logical_comment_and_alternate_exec_splice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-gaussian-pbs-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                seam = fixture.compose().consume_for_w5_once()
                seam = __import__("direct_trusted_session_composition").consume_w5_operation_seam_once(seam)
                binding = seam.direct_binding.document()
                profile = W5.load_transport_profile(seam.transport_profile_bytes)
                W5._validate_pbs_review(seam.pbs_review_bytes, seam.pbs_script_bytes,
                                        binding, profile, seam.allowed_root)
                review = json.loads(seam.pbs_review_bytes)
                exact_line = (b"exec "
                              + review["gaussian"]["executable"]["canonical_absolute_path"].encode()
                              + b" " + W5.INPUT_BASENAME.encode())

                def assert_rejected(hostile_script: bytes) -> None:
                    hostile = copy.deepcopy(review)
                    hostile["script"]["sha256"] = hashlib.sha256(hostile_script).hexdigest()
                    hostile["script"]["size_bytes"] = str(len(hostile_script))
                    hostile["review_payload_sha256"] = ""
                    hostile["review_payload_sha256"] = W5.digest(hostile)
                    hostile_profile = copy.deepcopy(profile)
                    hostile_profile["pbs_artifact"].update({
                        "sha256": hashlib.sha256(hostile_script).hexdigest(),
                        "size_bytes": str(len(hostile_script)),
                        "review_payload_sha256": hostile["review_payload_sha256"],
                    })
                    hostile_profile["profile_payload_sha256"] = ""
                    hostile_profile["profile_payload_sha256"] = W5.digest(hostile_profile)
                    with self.assertRaisesRegex(W5.DirectOneHopTransportError,
                                                "Gaussian absolute"):
                        W5._validate_pbs_review(W5.canonical_bytes(hostile), hostile_script,
                                                binding, hostile_profile, seam.allowed_root)

                hostile_script = seam.pbs_script_bytes.replace(
                    exact_line,
                    b"# reviewed " + review["gaussian"]["executable"][
                        "canonical_absolute_path"].encode() + b"\nexec /different/g16 "
                    + W5.INPUT_BASENAME.encode(),
                )
                assert_rejected(hostile_script)
                for injected in (
                    b"g16 approved-input.gjf",
                    b"module load gaussian",
                    b"PATH=/forged:$PATH",
                    b"python3 -c 'run wrapper'",
                    b"export LD_PRELOAD=/forged/preload.so",
                    b"LD_LIBRARY_PATH=/forged",
                    b"/different/gaussian approved-input.gjf",
                    b" exec /different/g16 approved-input.gjf",
                    b"# unreviewed extra bytes",
                ):
                    assert_rejected(seam.pbs_script_bytes.replace(
                        exact_line, injected + b"\n" + exact_line,
                    ))

                legacy_script = seam.pbs_script_bytes.replace(
                    b"exec " + review["gaussian"]["executable"]["canonical_absolute_path"].encode(),
                    b"exec g16",
                )
                legacy = copy.deepcopy(review)
                legacy["schema"] = W5.LEGACY_PBS_REVIEW_SCHEMA
                legacy["script"]["sha256"] = hashlib.sha256(legacy_script).hexdigest()
                legacy["script"]["size_bytes"] = str(len(legacy_script))
                legacy["gaussian"] = {"executable": "g16", "invocation": "filename_argument",
                    "input_basename": W5.INPUT_BASENAME,
                    "scientific_route_owned_by_input": True}
                legacy["review_payload_sha256"] = ""
                legacy["review_payload_sha256"] = W5.digest(legacy)
                legacy_profile = copy.deepcopy(profile)
                legacy_profile["pbs_artifact"].update({
                    "sha256": hashlib.sha256(legacy_script).hexdigest(),
                    "size_bytes": str(len(legacy_script)),
                    "review_payload_sha256": legacy["review_payload_sha256"],
                })
                self.assertEqual(
                    W5.validate_legacy_pbs_review_for_replay(
                        W5.canonical_bytes(legacy), legacy_script, binding,
                        legacy_profile, seam.allowed_root,
                    )["schema"],
                    W5.LEGACY_PBS_REVIEW_SCHEMA,
                )
                legacy["workspace"]["scratch_basename"] = "other"
                legacy["review_payload_sha256"] = ""
                legacy["review_payload_sha256"] = W5.digest(legacy)
                legacy_profile["pbs_artifact"]["review_payload_sha256"] = legacy[
                    "review_payload_sha256"
                ]
                with self.assertRaisesRegex(W5.DirectOneHopTransportError, "workspace"):
                    W5.validate_legacy_pbs_review_for_replay(
                        W5.canonical_bytes(legacy), legacy_script, binding,
                        legacy_profile, seam.allowed_root,
                    )
            finally:
                fixture.close()

    def test_historical_transport_is_replay_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-legacy-profile-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                successor = json.loads(fixture.artifacts.transport_profile)
                legacy = copy.deepcopy(successor)
                legacy["schema"] = CHANNEL.LEGACY_TRANSPORT_PROFILE_SCHEMA
                legacy["server"]["isolated_flags"] = ["-I", "-S"]
                del legacy["gaussian_runtime_binding"]
                legacy["profile_payload_sha256"] = ""
                legacy["profile_payload_sha256"] = CHANNEL.digest(legacy)
                replay = CHANNEL.validate_legacy_transport_profile_for_replay(legacy)
                self.assertEqual(replay["schema"], CHANNEL.LEGACY_TRANSPORT_PROFILE_SCHEMA)
                legacy_raw = CHANNEL.canonical_bytes(legacy)
                with self.assertRaisesRegex(
                        CHANNEL.SharedFixedSSHChannelError, "replay-only"):
                    CHANNEL._issue_query_exact_job_operation_for_testing(
                        legacy_raw, b"not-consulted", "731.master",
                        _test_token=CHANNEL._QUERY_CODEC_TEST_TOKEN,
                    )
                with self.assertRaisesRegex(
                        CHANNEL.SharedFixedSSHChannelError, "replay-only"):
                    CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
                        legacy_raw, b"not-consulted", "731.master",
                        _test_token=CHANNEL._FETCH_OPERATION_TEST_TOKEN,
                    )
                with self.assertRaisesRegex(W5.DirectOneHopTransportError, "replay-only"):
                    hostile_artifacts = copy.copy(fixture.artifacts)
                    object.__setattr__(hostile_artifacts, "transport_profile", legacy_raw)
                    W5._validate_controller_artifact_join(hostile_artifacts)

                seam = fixture.compose().consume_for_w5_once()
                seam = W5.SESSION.consume_w5_operation_seam_once(seam)
                seam._record["transport_profile"] = legacy_raw
                driver = W5._test_driver(stdout=b"731.master\n")
                with mock.patch.object(W5, "_write_new_file") as write_call, \
                        mock.patch.object(W5, "_record_unknown") as record_unknown:
                    with self.assertRaisesRegex(
                        W5.DirectOneHopTransportError,
                        "replay-only before W5 effect owner",
                    ):
                        W5._consume_with_test_driver_once(
                            seam, driver, _test_token=W5._TEST_DRIVER_TOKEN,
                        )
                write_call.assert_not_called()
                record_unknown.assert_not_called()
                self.assertEqual(driver.calls, 0)
            finally:
                fixture.close()

    def test_historical_w1_chain_is_replay_only_before_w4b(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-legacy-w1-chain-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                successor_policy = json.loads(fixture.artifacts.profile_policy)
                successor_authorization = json.loads(fixture.artifacts.authorization)
                legacy_policy = W1.build_profile_policy(
                    profile_id=successor_policy["profile_id"],
                    declared_allowed_root=successor_policy["declared_allowed_root"],
                    transport_identity_binding_sha256=successor_policy[
                        "transport_identity_binding_sha256"
                    ],
                    gaussian_runtime_binding_sha256=successor_policy[
                        "gaussian_runtime_binding_sha256"
                    ],
                    resource_catalog_sha256=successor_policy["resource_catalog_sha256"],
                )
                root_owner = W1.DirectRootOwnerContractOwner.for_posix_backend()
                legacy_stable = root_owner.issue_stable_evidence_from_reviewed_profile(
                    legacy_policy
                ).document()
                legacy_profile = W1.build_direct_execution_profile(
                    legacy_policy, legacy_stable
                )
                auth = successor_authorization
                legacy_authorization = W1.build_direct_execution_authorization(
                    authorization_id=auth["authorization_id"], profile=legacy_profile,
                    stable_evidence=legacy_stable,
                    project=auth["workspace"]["project"],
                    input_basename=auth["input"]["basename"],
                    input_sha256=auth["input"]["sha256"],
                    input_size_bytes=int(auth["input"]["size_bytes"]),
                    tier=auth["resources"]["tier"],
                    cores=int(auth["resources"]["cores"]),
                    memory_gb=int(auth["resources"]["memory_gb"]),
                    walltime_seconds=int(auth["resources"]["walltime_seconds"]),
                    scientific_task_id=auth["scope"]["scientific_task_id"],
                    attempt_id=auth["scope"]["attempt_id"],
                    idempotency_key=auth["scope"]["idempotency_key"],
                    approved_at=auth["approved_at"], not_before=auth["not_before"],
                    expires_at=auth["expires_at"],
                    maximum_receipt_age_seconds=int(
                        auth["fresh_observation_rules"]["maximum_receipt_age_seconds"]
                    ),
                )
                replacements = {
                    "profile_policy": W1.canonical_bytes(legacy_policy),
                    "stable_evidence": W1.canonical_bytes(legacy_stable),
                    "profile": W1.canonical_bytes(legacy_profile),
                    "authorization": W1.canonical_bytes(legacy_authorization),
                }
                artifacts = W5.SESSION.DirectServerSessionArtifacts(**{
                    name: replacements.get(name, getattr(fixture.artifacts, name))
                    for name in fixture.artifacts.__dataclass_fields__
                })
                with self.assertRaisesRegex(
                        W5.SESSION.DirectTrustedSessionError, "replay-only"):
                    fixture.owner().compose_once(artifacts)
            finally:
                fixture.close()

    def test_fixed_repository_and_pure_named_package_entrypoints_under_isolation(self) -> None:
        python = sys.executable
        fixed_environment = {"LANG": "hostile", "LC_ALL": "C", "PYTHONPATH": "/forged"}
        with tempfile.TemporaryDirectory(prefix="auto-g16-clean-repository-") as raw:
            repository = self._stage_clean_repository(Path(raw).resolve())
            for entry, expected in (("direct_submit_subsystem_entrypoint.py", 3),
                                    ("direct_read_subsystem_entrypoint.py", 1)):
                result = subprocess.run(
                    [python, "-I", "-S", "-B", str(repository / "scripts" / entry)],
                    input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd="/tmp", env=fixed_environment, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr.decode())

        with tempfile.TemporaryDirectory(prefix="auto-g16-pure-package-") as raw:
            installed = Path(raw).resolve() / "auto-g16-rtwin-pbs"
            files = PACKAGE.package_files_with_supplements(ROOT, "auto-g16-rtwin-pbs")
            for target, source in files.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            for entry, expected in (("direct_submit_subsystem_entrypoint.py", 3),
                                    ("direct_read_subsystem_entrypoint.py", 1)):
                result = subprocess.run(
                    [python, "-I", "-S", "-B", str(installed / "scripts" / entry)],
                    input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd="/tmp", env=fixed_environment, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr.decode())
            origin_reports = {}
            for entry_name, empty_exit in (("direct_submit_subsystem_entrypoint.py", 3),
                                           ("direct_read_subsystem_entrypoint.py", 1)):
                probe = installed.parent / f"pure-package-{entry_name}-origin-probe.py"
                entry_path = installed / "scripts" / entry_name
                expected_exception = (
                    f"isinstance(exc,SystemExit) and exc.code == {empty_exit}"
                    if entry_name == "direct_submit_subsystem_entrypoint.py"
                    else "type(exc).__name__ == 'ControllerTransportUnknown'"
                )
                probe.write_text(
                    "import json,sys,types\n"
                    "from pathlib import Path\n"
                    f"entry=Path({str(entry_path)!r})\n"
                    "module=types.ModuleType('__main__'); module.__file__=str(entry)\n"
                    "sys.modules['__main__']=module\n"
                    "sys.argv=[str(entry)]\n"
                    "try:\n"
                    " exec(compile(entry.read_bytes(),str(entry),'exec'),module.__dict__)\n"
                    "except BaseException as exc:\n"
                    f" assert {expected_exception}\n"
                    f"root=Path({str(installed)!r}).resolve()\n"
                    "inventory=json.loads((root/'contracts/direct-execution/"
                    "direct-subsystem-source-inventory.json').read_text())\n"
                    "expected={item['module']:item['named_path'] for item in inventory['files']}\n"
                    "origins={}\n"
                    "outside={}\n"
                    "for name,relative in expected.items():\n"
                    " module=sys.modules.get(name)\n"
                    " if module is None: continue\n"
                    " origin=Path(module.__file__).resolve()\n"
                    " if origin == root/relative: origins[name]=relative\n"
                    " else: outside[name]=str(origin)\n"
                    "real=(Path.home()/'.codex/skills/auto-g16-rtwin-pbs').resolve()\n"
                    "installed_hits={name:path for name,path in outside.items() "
                    "if Path(path).is_relative_to(real)}\n"
                    "print(json.dumps({'origins':origins,'outside':outside,"
                    "'installed_hits':installed_hits},sort_keys=True))\n",
                    encoding="utf-8",
                )
                origin_result = subprocess.run(
                    [python, "-I", "-S", "-B", str(probe)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd="/tmp", env=fixed_environment, timeout=30, check=False,
                )
                self.assertEqual(origin_result.returncode, 0, origin_result.stderr.decode())
                report = json.loads(origin_result.stdout)
                self.assertGreater(len(report["origins"]), 0)
                self.assertEqual(report["outside"], {})
                self.assertEqual(report["installed_hits"], {})
                origin_reports[entry_name] = report
            print("PURE_PACKAGE_ORIGINS=" + json.dumps(origin_reports, sort_keys=True))
            inventory = json.loads(
                (installed / "contracts/direct-execution"
                 / "direct-subsystem-source-inventory.json").read_text()
            )
            excluded = set(inventory["package_projection"]["excluded_targets"])
            expected_projection = {
                Path(target).as_posix(): hashlib.sha256(source.read_bytes()).hexdigest()
                for target, source in files.items() if Path(target).as_posix() not in excluded
            }
            observed_projection = {
                path.relative_to(installed).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in installed.rglob("*")
                if path.is_file() and path.relative_to(installed).as_posix() not in excluded
            }
            missing = sorted(set(expected_projection) - set(observed_projection))
            extra = sorted(set(observed_projection) - set(expected_projection))
            changed = sorted(target for target in set(expected_projection) & set(observed_projection)
                             if expected_projection[target] != observed_projection[target])
            self.assertEqual((missing, changed, extra), ([], [], []))
            print("PURE_PACKAGE_CLOSURE=" + json.dumps({
                "file_count": len(observed_projection), "missing": len(missing),
                "changed": len(changed), "extra": len(extra), "pycache": 0,
            }, sort_keys=True))
            self.assertEqual(list(installed.rglob("*.pyc")), [])
            self.assertEqual(list(installed.rglob("__pycache__")), [])

    def test_rehashed_dependency_projection_and_inventory_cannot_replace_outer_anchors(self) -> None:
        python = sys.executable
        environment = {"LANG": "C", "LC_ALL": "C"}

        def rewrite_inventory(root: Path, *, named: bool) -> None:
            inventory_path = (
                root / "contracts/direct-execution/direct-subsystem-source-inventory.json"
            )
            inventory = json.loads(inventory_path.read_text())
            dependency = root / "scripts/direct_one_hop_transport.py"
            for item in inventory["files"]:
                if item["module"] == "direct_one_hop_transport":
                    item["sha256"] = hashlib.sha256(dependency.read_bytes()).hexdigest()
                    break
            else:
                self.fail("W5 is absent from subsystem inventory")
            excluded = set(inventory["package_projection"]["excluded_targets"])
            if named:
                projection = {
                    path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in root.rglob("*")
                    if path.is_file() and path.relative_to(root).as_posix() not in excluded
                }
            else:
                files = PACKAGE.package_files_with_supplements(root, "auto-g16-rtwin-pbs")
                projection = {
                    target.as_posix(): hashlib.sha256(source.read_bytes()).hexdigest()
                    for target, source in files.items() if target.as_posix() not in excluded
                }
            repository_root = ROOT if named else root
            repository_excluded = set(
                inventory["repository_scripts_projection"]["excluded_sources"]
            )
            repository_projection = {
                path.relative_to(repository_root).as_posix():
                    hashlib.sha256(path.read_bytes()).hexdigest()
                for scripts_root in (
                    repository_root / "scripts",
                    repository_root / "skills/auto-g16-rtwin-pbs/scripts",
                )
                for path in scripts_root.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
                and path.relative_to(repository_root).as_posix()
                not in repository_excluded
            }
            if named:
                repository_projection["scripts/direct_one_hop_transport.py"] = (
                    hashlib.sha256(dependency.read_bytes()).hexdigest()
                )
            inventory["repository_scripts_projection"]["file_count"] = len(
                repository_projection
            )
            inventory["repository_scripts_projection"][
                "source_sha256_map_sha256"
            ] = hashlib.sha256(
                json.dumps(
                    repository_projection, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            inventory["package_projection"]["file_count"] = len(projection)
            inventory["package_projection"]["target_sha256_map_sha256"] = hashlib.sha256(
                json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            inventory["inventory_payload_sha256"] = ""
            inventory["inventory_payload_sha256"] = hashlib.sha256(
                json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            inventory_path.write_text(
                json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory(prefix="auto-g16-rehashed-closure-") as raw:
            parent = Path(raw).resolve()
            package_files = PACKAGE.package_files_with_supplements(
                ROOT, "auto-g16-rtwin-pbs"
            )
            roots: list[tuple[str, Path, bool]] = []
            repository = self._stage_clean_repository(parent / "repo-case")
            roots.append(("repository", repository, False))
            installed = parent / "named-case" / "auto-g16-rtwin-pbs"
            for target, source in package_files.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            roots.append(("named", installed, True))

            for label, root, named in roots:
                with self.subTest(layout=label):
                    writes = parent / f"{label}-write-sentinel"
                    qsub = parent / f"{label}-qsub-sentinel"
                    with (root / "scripts/direct_one_hop_transport.py").open(
                        "a", encoding="utf-8"
                    ) as handle:
                        handle.write(
                            "\nfrom pathlib import Path as _HostilePath\n"
                            f"_HostilePath({str(writes)!r}).write_text('executed')\n"
                            f"_HostilePath({str(qsub)!r}).write_text('executed')\n"
                        )
                    rewrite_inventory(root, named=named)
                    result = subprocess.run(
                        [python, "-I", "-S", "-B",
                         str(root / "scripts/direct_submit_subsystem_entrypoint.py")],
                        input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd="/tmp", env=environment, timeout=10, check=False,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr.decode())
                    self.assertFalse(writes.exists(), label)
                    self.assertFalse(qsub.exists(), label)

    def test_repository_second_script_root_cache_symlink_and_extra_are_rejected(self) -> None:
        python = sys.executable
        for variant in ("cache", "symlink", "extra"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(
                    prefix=f"auto-g16-repository-second-root-{variant}-") as raw:
                parent = Path(raw).resolve()
                repository = self._stage_clean_repository(parent)
                second = repository / "skills/auto-g16-rtwin-pbs/scripts"
                writes = parent / f"{variant}-write-sentinel"
                qsub = parent / f"{variant}-qsub-sentinel"
                hostile = parent / f"{variant}_probe.py"
                hostile.write_text(
                    "from pathlib import Path\n"
                    f"Path({str(writes)!r}).write_text('executed')\n"
                    f"Path({str(qsub)!r}).write_text('executed')\n",
                    encoding="utf-8",
                )
                if variant == "cache":
                    target = second / "__pycache__/forged_extra.pyc"
                    target.parent.mkdir()
                    py_compile.compile(str(hostile), cfile=str(target), doraise=True)
                    expected = b"Python bytecode"
                elif variant == "symlink":
                    (second / "forged-extra.py").symlink_to("gaussian_workflow.py")
                    expected = b"symlink"
                else:
                    shutil.copyfile(hostile, second / "forged-extra.py")
                    expected = b"missing, changed, or extra"
                result = subprocess.run(
                    [python, "-I", "-S", "-B",
                     str(repository / "scripts/direct_submit_subsystem_entrypoint.py")],
                    input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd="/tmp", env={"LANG": "C", "LC_ALL": "C"}, timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr.decode())
                self.assertIn(expected, result.stderr)
                self.assertFalse(writes.exists())
                self.assertFalse(qsub.exists())

    def test_named_package_hostile_layout_sha_symlink_extra_and_preload_fail_closed(self) -> None:
        python = sys.executable
        environment = {"LANG": "C", "LC_ALL": "C"}

        def stage(parent: Path) -> Path:
            installed = parent / "auto-g16-rtwin-pbs"
            for target, source in PACKAGE.package_files_with_supplements(
                    ROOT, "auto-g16-rtwin-pbs").items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            return installed

        def rejected(installed: Path) -> None:
            result = subprocess.run(
                [python, "-I", "-S", "-B",
                 str(installed / "scripts" / "direct_submit_subsystem_entrypoint.py")],
                input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd="/tmp", env=environment, timeout=10, check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr.decode())

        with tempfile.TemporaryDirectory(prefix="auto-g16-hostile-package-") as raw:
            parent = Path(raw).resolve()
            installed = stage(parent / "wrong-bootstrap")
            with (installed / "scripts/direct_subsystem_bootstrap.py").open("ab") as handle:
                handle.write(b"# drift\n")
            rejected(installed)

            installed = stage(parent / "wrong-inventory")
            inventory = (installed / "contracts/direct-execution"
                         / "direct-subsystem-source-inventory.json")
            with inventory.open("ab") as handle:
                handle.write(b" \n")
            rejected(installed)

            installed = stage(parent / "wrong-dependency")
            with (installed / "scripts/direct_one_hop_transport.py").open("ab") as handle:
                handle.write(b"# drift\n")
            rejected(installed)

            installed = stage(parent / "symlink")
            dependency = installed / "scripts/direct_gaussian_runtime_identity.py"
            replacement = installed / "scripts/other.py"
            replacement.write_bytes(dependency.read_bytes())
            dependency.unlink()
            dependency.symlink_to(replacement.name)
            rejected(installed)

            installed = stage(parent / "extra")
            (installed / "unexpected.txt").write_text("extra", encoding="utf-8")
            rejected(installed)

            installed = stage(parent / "partial")
            (installed / "skills/auto-g16-rtwin-pbs/scripts").mkdir(parents=True)
            rejected(installed)

            installed = stage(parent / "dual")
            nested = installed / "skills/auto-g16-rtwin-pbs"
            (nested / "scripts").mkdir(parents=True)
            (nested / "SKILL.md").write_text("name: auto-g16-rtwin-pbs\n", encoding="utf-8")
            rejected(installed)

            repository = parent / "partial-primary-repository"
            scripts = repository / "scripts"
            scripts.mkdir(parents=True)
            for name in (
                "direct_submit_subsystem_entrypoint.py",
                "direct_subsystem_bootstrap.py",
            ):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            (repository / "skills/auto-g16-rtwin-pbs").mkdir(parents=True)
            rejected(repository)

            real_parent = parent / "symlink-ancestor-real"
            installed = stage(real_parent)
            alias = parent / "symlink-ancestor-alias"
            alias.symlink_to(real_parent, target_is_directory=True)
            rejected(alias / "auto-g16-rtwin-pbs")

        for preload in ("direct_one_hop_transport", "direct_effect_time_replay_ingress"):
            with self.subTest(preload=preload), tempfile.TemporaryDirectory(
                    prefix="auto-g16-preload-probe-") as raw:
                parent = Path(raw).resolve()
                repository = self._stage_clean_repository(parent)
                probe = parent / "probe.py"
                entry = repository / "scripts/direct_submit_subsystem_entrypoint.py"
                probe.write_text(
                    "import runpy,sys,types\n"
                    f"sys.modules[{preload!r}]=types.ModuleType({preload!r})\n"
                    f"sys.argv=[{str(entry)!r}]\n"
                    f"runpy.run_path({str(entry)!r},run_name='__main__')\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [python, "-I", "-S", "-B", str(probe)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/tmp",
                    env=environment, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(b"preloaded", result.stderr)

    def test_bootstrap_absolute_component_identity_replay_rejects_ancestor_swap(self) -> None:
        qsub_calls = 0
        with tempfile.TemporaryDirectory(prefix="auto-g16-bootstrap-ancestor-") as raw:
            parent = Path(raw).resolve()
            reviewed = parent / "reviewed-package-root"
            reviewed.mkdir()
            descriptor, identity_chain = BOOTSTRAP._open_absolute_directory_chain(reviewed)
            os.close(descriptor)
            reviewed.rename(parent / "moved-reviewed-package-root")
            reviewed.mkdir()
            with self.assertRaisesRegex(
                BOOTSTRAP.DirectSubsystemBootstrapError,
                "package-root identity changed",
            ):
                BOOTSTRAP._replay_absolute_directory_chain(reviewed, identity_chain)
        self.assertEqual(qsub_calls, 0)

    def test_entrypoint_import_reload_rebind_fork_and_copy_fail_before_bootstrap(self) -> None:
        python = sys.executable
        with tempfile.TemporaryDirectory(prefix="auto-g16-entry-identity-probe-") as raw:
            probe = Path(raw) / "probe.py"
            probe.write_text(
                "import os,sys,types\n"
                "from pathlib import Path\n"
                "entry=Path(sys.argv[1]).resolve(); case=sys.argv[2]\n"
                "module_name='entry_import_probe' if case == 'import' else '__main__'\n"
                "module=types.ModuleType(module_name); module.__file__=str(entry)\n"
                "sys.modules[module_name]=module; sys.argv=[str(entry),'closed-argv-probe']\n"
                "try:\n"
                " exec(compile(entry.read_bytes(),str(entry),'exec'),module.__dict__)\n"
                "except ImportError as exc:\n"
                " assert str(exc).endswith('subsystem argv is closed')\n"
                "calls=[0]\n"
                "target=module._load_reviewed_bootstrap.__code__\n"
                "def trace(frame,event,arg):\n"
                " if event == 'call' and frame.f_code is target: calls[0] += 1\n"
                " return trace\n"
                "sys.argv=[str(entry)]\n"
                "sys.settrace(trace)\n"
                "if case == 'reload':\n"
                " try: exec(compile(entry.read_bytes(),str(entry),'exec'),module.__dict__)\n"
                " except ImportError as exc: assert 'entrypoint was reloaded' in str(exc)\n"
                "elif case == 'rebind':\n"
                " original=module.main; module.main=lambda: 0\n"
                " try: original()\n"
                " except ImportError as exc: assert str(exc).endswith('subsystem argv is closed')\n"
                "elif case == 'copy':\n"
                " copied=types.FunctionType(module.main.__code__,dict(module.main.__globals__))\n"
                " try: copied()\n"
                " except ImportError as exc: assert str(exc).endswith('subsystem argv is closed')\n"
                "elif case == 'import':\n"
                " try: module.main()\n"
                " except ImportError as exc: assert str(exc).endswith('subsystem argv is closed')\n"
                "elif case == 'fork':\n"
                " child=os.fork()\n"
                " if child == 0:\n"
                "  try: module.main()\n"
                "  except ImportError as exc:\n"
                "   os._exit(0 if str(exc).endswith('subsystem argv is closed') and calls[0] == 0 else 7)\n"
                "  os._exit(8)\n"
                " _pid,status=os.waitpid(child,0); assert os.waitstatus_to_exitcode(status) == 0\n"
                "else: raise AssertionError(case)\n"
                "sys.settrace(None); assert calls[0] == 0\n"
                "print(f'ENTRY_GUARD={entry.name}:{case}:bootstrap=0:qsub=0')\n",
                encoding="utf-8",
            )
            for entry_name in ("direct_submit_subsystem_entrypoint.py",
                               "direct_read_subsystem_entrypoint.py"):
                for case in ("import", "reload", "rebind", "fork", "copy"):
                    result = subprocess.run(
                        [python, "-I", "-S", "-B", str(probe),
                         str(ROOT / "scripts" / entry_name), case],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd="/tmp", env={"LANG": "C", "LC_ALL": "C"},
                        timeout=10, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertIn(b"bootstrap=0:qsub=0", result.stdout)
                    print(result.stdout.decode().strip())


if __name__ == "__main__":
    unittest.main()
