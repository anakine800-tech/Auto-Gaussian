from __future__ import annotations

from dataclasses import fields, is_dataclass
import ast
from hashlib import sha256
import inspect
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import auto_g16.transport as transport
import auto_g16.execution as execution
from auto_g16.transport._bridge import (
    _BOOTSTRAP_PROTOCOL,
    _BOOTSTRAP_SOURCE,
    _BOOTSTRAP_SOURCE_BYTES,
    _BOOTSTRAP_SOURCE_NAME,
    _cmd_quote_v1,
    _decode_response_frame,
    _encode_request_frame,
    _posix_quote_bootstrap_source_v1,
    _posix_quote_v1,
    _powershell_quote_fixed_launcher_v1,
    _powershell_quote_v1,
)
from auto_g16.transport._canonical import canonical_json_bytes
from auto_g16.transport._driver import _OPERATION_TABLE_BYTES, _OPERATION_TABLE_SHA256, _validate_result

from ._fixtures import TransportFixture


class TransportContractTests(unittest.TestCase):
    def test_public_inventory_is_exact(self) -> None:
        self.assertEqual(tuple(transport.__all__), (
            "TransportBoundaryError", "TransportStore", "ExactRemoteJobBinding",
            "SchedulerReadEvidence", "ExactArtifactRequest", "FetchedArtifact",
            "FetchedOutputCapture", "RTWinExecutionAdapter", "RTWinReadAdapter",
        ))
        self.assertTrue(issubclass(transport.TransportBoundaryError, ValueError))

    def test_public_records_are_frozen_slotted_keyword_only(self) -> None:
        expected = {
            transport.ExactRemoteJobBinding: ("transport_store_id", "store_instance_id", "attempt_id", "execution_snapshot_id", "submission_intent_id", "remote_effect_receipt_id", "remote_workspace", "job_id"),
            transport.SchedulerReadEvidence: ("binding", "source_identity", "observed_at_utc", "freshness", "state", "evidence_sha256", "evidence_size_bytes", "schema_version", "source_kind", "progress_position"),
            transport.ExactArtifactRequest: ("artifact_kind", "logical_name", "remote_relative_name", "required"),
            transport.FetchedArtifact: ("request", "content", "sha256", "size_bytes"),
            transport.FetchedOutputCapture: ("binding", "input_binding_observation_id", "capture_source_id", "capture_sequence", "capture_status", "capture_completeness", "requests", "artifacts", "missing_requests", "capture_manifest_sha256", "captured_at_utc", "schema_version"),
        }
        for record, names in expected.items():
            self.assertTrue(is_dataclass(record))
            self.assertEqual(tuple(field.name for field in fields(record)), names)
            self.assertTrue(record.__dataclass_params__.frozen)
            self.assertTrue(hasattr(record, "__slots__"))

    def test_public_signatures_are_exact(self) -> None:
        self.assertEqual(tuple(inspect.signature(transport.TransportStore.create_new).parameters), ("path", "approved_root"))
        self.assertEqual(tuple(inspect.signature(transport.TransportStore.open_existing).parameters), ("path", "approved_root"))
        self.assertEqual(tuple(inspect.signature(transport.ExactRemoteJobBinding.from_persisted_receipt).parameters), ("snapshot", "journal", "remote_effect_receipt_id", "current_profile", "transport_store"))
        self.assertEqual(tuple(inspect.signature(transport.RTWinExecutionAdapter).parameters), ("transport_store", "current_profile"))
        self.assertEqual(tuple(inspect.signature(transport.RTWinReadAdapter).parameters), ("transport_store",))

    def test_operation_table_and_fixed_bootstrap_are_source_controlled(self) -> None:
        self.assertEqual(len(_OPERATION_TABLE_BYTES), 1570)
        self.assertEqual(sha256(_OPERATION_TABLE_BYTES).hexdigest(), _OPERATION_TABLE_SHA256)
        self.assertEqual(_OPERATION_TABLE_SHA256, "14cdd511bb6c4eb78af8f07d774cfdae27fc1c661dae8692b45e48ccd7fa31af")
        self.assertEqual(_BOOTSTRAP_SOURCE_NAME, "auto-g16-v3-rtwin-bootstrap-v2.py")
        self.assertEqual(_BOOTSTRAP_SOURCE_BYTES, _BOOTSTRAP_SOURCE.encode("utf-8"))
        self.assertEqual(len(_BOOTSTRAP_SOURCE_BYTES), 15597)
        self.assertEqual(_BOOTSTRAP_SOURCE_BYTES.count(b"\n"), 204)
        self.assertNotIn(b"\r", _BOOTSTRAP_SOURCE_BYTES)
        self.assertNotIn(b"\x00", _BOOTSTRAP_SOURCE_BYTES)
        self.assertEqual(sha256(_BOOTSTRAP_SOURCE_BYTES).hexdigest(), "b0b1bcaf8ab8697a80676ac1015503a2fb64c21949678f20bf05f3bd849fb10e")
        self.assertTrue(_BOOTSTRAP_SOURCE_BYTES.startswith(b"from __future__ import annotations\n"))
        self.assertTrue(_BOOTSTRAP_SOURCE_BYTES.endswith(b"main()\n"))
        self.assertNotIn("eval(", _BOOTSTRAP_SOURCE)
        self.assertNotIn("exec(", _BOOTSTRAP_SOURCE)
        self.assertNotIn("qdel", _BOOTSTRAP_SOURCE)

    def test_bootstrap_caps_reads_and_reattests_executables_after_launch(self) -> None:
        tree = ast.parse(_BOOTSTRAP_SOURCE)
        functions = {node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
        read_source = ast.get_source_segment(_BOOTSTRAP_SOURCE, functions["read_bounded"])
        identity_source = ast.get_source_segment(_BOOTSTRAP_SOURCE, functions["regular_identity"])
        run_source = ast.get_source_segment(_BOOTSTRAP_SOURCE, functions["run_exact"])
        self.assertIsNotNone(read_source)
        self.assertIsNotNone(identity_source)
        self.assertIsNotNone(run_source)
        self.assertLess(read_source.index("expected_size>FILE_CAP"), read_source.index("os.read"))
        self.assertIn("st_mode&0o111==0", identity_source)
        self.assertEqual(run_source.count("regular_identity("), 2)
        self.assertLess(run_source.index("before=regular_identity"), run_source.index("subprocess.run"))
        self.assertLess(run_source.index("subprocess.run"), run_source.index("after=regular_identity"))
        self.assertIn('if before!=after: die("runtime-drift")', run_source)
        self.assertIn('if before.st_size>FILE_CAP: die("artifact-too-large")', _BOOTSTRAP_SOURCE)
        self.assertIn('if type(p["size_bytes"]) is not int or p["size_bytes"]<0 or p["size_bytes"]>FILE_CAP', _BOOTSTRAP_SOURCE)
        self.assertIn('content=decode64_bounded(p["content_base64"],FILE_CAP)', _BOOTSTRAP_SOURCE)
        self.assertIn('set(p)!={"pbs_basename","resource_enactment"}', _BOOTSTRAP_SOURCE)
        self.assertIn('set(r)!={"execution_snapshot_id","resolved_resource_request_id","cores","memory_mb","walltime_seconds","queue","scheduler_dialect_id"}', _BOOTSTRAP_SOURCE)
        self.assertLess(_BOOTSTRAP_SOURCE.index('args.append(p["pbs_basename"]); die("non-production-resource-dialect")'), _BOOTSTRAP_SOURCE.index('completed=run_exact(roots["server_qsub"],args'))
        self.assertIn('if r["queue"]!="batch": die("invalid-torque-queue")', _BOOTSTRAP_SOURCE)
        self.assertIn('args=["-l","nodes=1:ppn="+str(r["cores"])+",mem="+str(r["memory_mb"])+"mb,walltime="+str(r["walltime_seconds"]),"-q","batch",p["pbs_basename"]]', _BOOTSTRAP_SOURCE)

    def test_bootstrap_rejects_nonexecutables_and_postlaunch_replacement(self) -> None:
        tree = ast.parse(_BOOTSTRAP_SOURCE)
        namespace: dict[str, object] = {}
        definitions = ast.Module(body=tree.body[:-1], type_ignores=[])
        exec(compile(definitions, "<fixed-bootstrap-test>", "exec"), namespace)
        regular_identity = namespace["regular_identity"]
        read_bounded = namespace["read_bounded"]
        run_exact = namespace["run_exact"]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "qsub"
            executable.write_bytes(b"fixed-qsub")
            executable.chmod(0o600)
            with self.assertRaises(SystemExit):
                regular_identity(str(executable), 10, sha256(b"fixed-qsub").hexdigest())
            executable.chmod(0o700)
            oversized_fd = os.open(executable, os.O_RDONLY)
            try:
                with patch("os.read") as read, self.assertRaises(SystemExit):
                    read_bounded(oversized_fd, 134_217_729, "artifact-too-large")
                read.assert_not_called()
            finally:
                os.close(oversized_fd)
            root = {"path":str(executable), "expected_size_bytes":10, "expected_sha256":sha256(b"fixed-qsub").hexdigest()}
            cwd_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            def replace_after_launch(*_args, **_kwargs):
                replacement = Path(directory) / "replacement"
                replacement.write_bytes(b"fixed-qsub")
                replacement.chmod(0o700)
                os.replace(replacement, executable)
                return subprocess.CompletedProcess([], 0, stdout=b"123.server\n", stderr=b"")
            try:
                with patch("subprocess.run", side_effect=replace_after_launch), self.assertRaises(SystemExit):
                    run_exact(root, ["job.pbs"], cwd_fd, 65536, 65536)
            finally:
                os.close(cwd_fd)

    def test_bootstrap_runs_exact_torque_vector_through_manifest_path_without_shell(self) -> None:
        tree = ast.parse(_BOOTSTRAP_SOURCE)
        namespace: dict[str, object] = {}
        exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "<fixed-bootstrap-test>", "exec"), namespace)
        run_exact = namespace["run_exact"]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "qsub"
            executable.write_bytes(b"fixed-qsub")
            executable.chmod(0o700)
            root = {"path":str(executable), "expected_size_bytes":10, "expected_sha256":sha256(b"fixed-qsub").hexdigest()}
            cwd_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            argv = ["-l", "nodes=1:ppn=8,mem=12288mb,walltime=3600", "-q", "batch", "job.pbs"]
            try:
                with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=b"123.server\n", stderr=b"")) as run:
                    completed = run_exact(root, argv, cwd_fd, 65536, 65536)
                self.assertEqual(completed.stdout, b"123.server\n")
                self.assertEqual(run.call_args.args[0], [str(executable), *argv])
                self.assertFalse(run.call_args.kwargs["shell"])
            finally:
                os.close(cwd_fd)

    def test_bootstrap_main_derives_torque_vector_from_closed_request(self) -> None:
        tree = ast.parse(_BOOTSTRAP_SOURCE)
        namespace: dict[str, object] = {}
        exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]), "<fixed-bootstrap-test>", "exec"), namespace)
        binding = {
            "transport_store_id":"store-1", "store_instance_id":"instance-1",
            "runtime_attestation_id":"runtime-1", "attempt_id":"attempt-1",
            "execution_snapshot_id":"snapshot-1", "submission_intent_id":"intent-1",
            "remote_workspace":"/srv/p/attempt-1", "workspace_authority_id":"workspace-1",
            "workspace_physical_token_base64":"d29ya3NwYWNlLTE=",
            "prepared_input_artifact_authority_id":"input-artifact-1",
            "prepared_input_artifact_physical_token_base64":"aW5wdXQtdG9rZW4tMQ==",
            "pbs_template_artifact_authority_id":"pbs-artifact-1",
            "pbs_template_artifact_physical_token_base64":"cGJzLXRva2VuLTE=",
        }
        resource = {
            "execution_snapshot_id":"snapshot-1", "resolved_resource_request_id":"resources-1",
            "cores":22, "memory_mb":51_200, "walltime_seconds":43_200,
            "queue":"batch", "scheduler_dialect_id":"auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1",
        }
        request = {"binding":binding, "operation":"SUBMIT_QSUB_ONCE", "payload":{"pbs_basename":"job.pbs", "resource_enactment":resource}, "protocol":"auto-g16-v3-rtwin-bootstrap/2"}
        qsub_root = {"path":"/usr/local/bin/qsub", "expected_size_bytes":418_920, "expected_sha256":"f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d"}
        namespace["manifest"] = Mock(return_value={"server_qsub":qsub_root})
        namespace["read_frame"] = Mock(return_value=request)
        namespace["open_workspace"] = Mock(return_value=(10, 11, 12))
        namespace["closefds"] = Mock()
        namespace["attest_artifact"] = Mock(side_effect=lambda _fd, _binding, kind, _identity: "input.gjf" if kind=="prepared-input" else "job.pbs")
        namespace["run_exact"] = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"123.server\n", stderr=b""))
        namespace["respond"] = Mock()
        namespace["main"]()
        expected = ["-l", "nodes=1:ppn=22,mem=51200mb,walltime=43200", "-q", "batch", "job.pbs"]
        namespace["run_exact"].assert_called_once_with(qsub_root, expected, 12, 65536, 65536)
        namespace["respond"].assert_called_once_with("SUBMIT_QSUB_ONCE", {"job_id":"123.server"})
        self.assertNotIn("argv", request["payload"])

    def test_posix_variable_and_fixed_source_quoting_are_separate(self) -> None:
        self.assertEqual(shlex.split(_posix_quote_v1("")), [""])
        self.assertEqual(shlex.split(_posix_quote_v1("alpha'beta")), ["alpha'beta"])
        for token in ("alpha\nbeta", "alpha\rbeta", "alpha\x00beta"):
            with self.assertRaises(transport.TransportBoundaryError):
                _posix_quote_v1(token)
        source = "alpha'\nbeta\n"
        quoted = _posix_quote_bootstrap_source_v1(source)
        self.assertEqual(source.encode("ascii"), b"alpha'\nbeta\n")
        self.assertEqual(len(source.encode("ascii")), 12)
        self.assertEqual(sha256(source.encode("ascii")).hexdigest(), "6053f05b9d4ccfee917933fbaf678ce477573102c2c6b62eaaa3d0290d8dcfb7")
        self.assertEqual(quoted.encode("ascii"), b"'alpha'\"'\"'\nbeta\n'")
        self.assertEqual(len(quoted.encode("ascii")), 18)
        self.assertEqual(sha256(quoted.encode("ascii")).hexdigest(), "582f76adb6db7219ffaea960e5b01ee95939b0600c002c92d0601199369e9735")
        self.assertEqual(shlex.split(quoted), [source])
        self.assertEqual(shlex.split(_posix_quote_bootstrap_source_v1(_BOOTSTRAP_SOURCE)), [_BOOTSTRAP_SOURCE])
        for bad in ("alpha\rbeta", "alpha\x00beta", "α"):
            with self.assertRaises(transport.TransportBoundaryError):
                _posix_quote_bootstrap_source_v1(bad)

    def test_fixed_nested_launcher_preserves_source_lf_without_widening_variable_tokens(self) -> None:
        launcher = "ssh -- " + _posix_quote_bootstrap_source_v1("alpha\nbeta\n")
        quoted = _powershell_quote_fixed_launcher_v1(launcher)
        self.assertIn("\n", quoted)
        self.assertTrue(quoted.startswith("'") and quoted.endswith("'"))
        for token in ("alpha\nbeta", "alpha\rbeta", "alpha\x00beta"):
            with self.assertRaises(transport.TransportBoundaryError):
                _powershell_quote_v1(token)
        for bad in ("alpha\rbeta", "alpha\x00beta", "α"):
            with self.assertRaises(transport.TransportBoundaryError):
                _powershell_quote_fixed_launcher_v1(bad)

    def test_agv3_frame_is_canonical_single_frame(self) -> None:
        request = {"binding": {}, "operation": "ALLOCATE_WORKSPACE", "payload": {}, "protocol": _BOOTSTRAP_PROTOCOL}
        framed = _encode_request_frame(request, cap=65536)
        self.assertEqual(framed[:4], b"AGV3")
        self.assertEqual(int.from_bytes(framed[4:12], "big"), len(framed) - 12)
        response = {"operation": "ALLOCATE_WORKSPACE", "protocol": _BOOTSTRAP_PROTOCOL, "result": {"remote_workspace": "/srv/p/a", "workspace_physical_token_base64": "eA=="}, "status": "ok"}
        raw = canonical_json_bytes(response)
        self.assertEqual(_decode_response_frame(b"AGV3" + len(raw).to_bytes(8, "big") + raw, operation="ALLOCATE_WORKSPACE", cap=65536), response["result"])
        with self.assertRaises(transport.TransportBoundaryError):
            _decode_response_frame(b"AGV3" + len(raw).to_bytes(8, "big") + raw + b"x", operation="ALLOCATE_WORKSPACE", cap=65536)

    def test_active_source_dependent_wire_vectors_are_exact(self) -> None:
        allocate = {
            "binding": {
                "attempt_id": "attempt-1", "execution_snapshot_id": "snapshot-1",
                "remote_workspace": "/srv/p/attempt-1",
                "runtime_attestation_id": "26153064-bd77-505b-b785-b97f5255f7a8",
                "store_instance_id": "28c10d1a-9f8f-5ce6-84d1-555175c0fcde",
                "submission_intent_id": "intent-1",
                "transport_store_id": "108c8d43-2ea9-5658-9607-ade4cbbeac85",
            },
            "operation": "ALLOCATE_WORKSPACE", "payload": {},
            "protocol": "auto-g16-v3-rtwin-bootstrap/2",
        }
        fetch = {
            "binding": {
                **allocate["binding"],
                "job_authority_id": "382c7632-b0f4-5c61-baa9-e35f8cce1527",
                "job_id": "123.server",
                "receipt_binding_id": "1183cdad-9dc5-53d9-8d35-32a4fc01dd8c",
                "remote_effect_receipt_id": "receipt-1",
                "workspace_authority_id": "a91afb55-a950-56f1-83de-31a36954ad25",
                "workspace_physical_token_base64": "d29ya3NwYWNlLXRva2VuLXYx",
            },
            "operation": "FETCH_EXACT_FILE",
            "payload": {"expected_file_physical_token_base64": "YXJ0aWZhY3QtdG9rZW4tdjE=", "expected_size_bytes": 19, "remote_relative_name": "job.log"},
            "protocol": "auto-g16-v3-rtwin-bootstrap/2",
        }
        for value, size, digest in (
            (allocate, 420, "c2556e89b3598eb375bc821a9e650c155b39729cf9b003e82b5ee5418d2dadb0"),
            (fetch, 844, "6e0ad4e5f7ab99d6376959d2a55b6c36443f7bf10286bfc58d21bbebc00fd4a7"),
        ):
            raw = canonical_json_bytes(value)
            self.assertEqual(len(raw), size)
            self.assertEqual(sha256(raw).hexdigest(), digest)

    def test_qsub_v2_wire_vectors_and_response_are_exact(self) -> None:
        request = {
            "binding": {
                "attempt_id": "attempt-1", "execution_snapshot_id": "snapshot-1",
                "pbs_template_artifact_authority_id": "pbs-artifact-1",
                "pbs_template_artifact_physical_token_base64": "cGJzLXRva2VuLTE=",
                "prepared_input_artifact_authority_id": "input-artifact-1",
                "prepared_input_artifact_physical_token_base64": "aW5wdXQtdG9rZW4tMQ==",
                "remote_workspace": "/srv/p/attempt-1", "runtime_attestation_id": "runtime-1",
                "store_instance_id": "instance-1", "submission_intent_id": "intent-1",
                "transport_store_id": "store-1", "workspace_authority_id": "workspace-1",
                "workspace_physical_token_base64": "d29ya3NwYWNlLTE=",
            },
            "operation": "SUBMIT_QSUB_ONCE",
            "payload": {"pbs_basename": "job.pbs", "resource_enactment": {
                "cores": 8, "execution_snapshot_id": "snapshot-1", "memory_mb": 12288,
                "queue": "simple", "resolved_resource_request_id": "resource-request-1",
                "scheduler_dialect_id": "auto-g16-v3-pbs-resource-enactment/synthetic-test/1",
                "walltime_seconds": 3600,
            }},
            "protocol": "auto-g16-v3-rtwin-bootstrap/2",
        }
        response = {"operation": "SUBMIT_QSUB_ONCE", "protocol": "auto-g16-v3-rtwin-bootstrap/2", "result": {"job_id": "123.server"}, "status": "ok"}
        for value, size, digest in (
            (request, 958, "73c94b0942724b8627016de958bcea247098a5b68b47a3baf0f8c0b9dd8253ad"),
            (response, 123, "c1a9556d75c9f0fc390ed89100a1241c1fc44abb6d1f2b568a476445672fa2d3"),
        ):
            raw = canonical_json_bytes(value)
            self.assertEqual((len(raw), sha256(raw).hexdigest()), (size, digest))
        _validate_result("SUBMIT_QSUB_ONCE", response["result"])
        with self.assertRaises(transport.TransportBoundaryError):
            _validate_result("SUBMIT_QSUB_ONCE", {"job_id": "123.server", "argv": []})

    def test_pbs_template_resource_directives_remain_forbidden(self) -> None:
        for directive in (b"#PBS -l mem=1gb\n", b"#PBS -q other\n"):
            with self.subTest(directive=directive):
                with self.assertRaises(execution.ExecutionValueError):
                    execution.PbsTemplateBinding(
                        logical_name="job.pbs",
                        template_bytes=b"#!/bin/bash\n" + directive + b"exec g16 input.gjf\n",
                        template_contract_version="pbs-template-v1",
                        prepared_input_logical_name="input.gjf",
                    )

    def test_cmd_grammar_is_deterministic_but_rejects_metacharacters(self) -> None:
        self.assertEqual(_cmd_quote_v1(r"C:\RTWIN\ssh.exe"), '"C:\\RTWIN\\ssh.exe"')
        for token in ("a&b", "a%b", "a!b", 'a"b', "a\nb"):
            with self.assertRaises(transport.TransportBoundaryError):
                _cmd_quote_v1(token)

    def test_transport_has_no_legacy_or_scientific_authority_import(self) -> None:
        package = Path(transport.__file__).resolve().parent
        forbidden = {"auto_g16.approval", "auto_g16.core", "auto_g16.observe", "auto_g16.result", "auto_g16.review", "auto_g16.scientific_validation", "auto_g16.workflow", "legacy_rtwin_pbs"}
        for path in package.glob("*.py"):
            imports: set[str] = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            self.assertTrue(imports.isdisjoint(forbidden), path.name)


class ConstructionTests(TransportFixture):
    def test_public_adapter_construction_is_non_effectful(self) -> None:
        profile = self.profile()
        with patch("subprocess.Popen") as popen:
            effect = transport.RTWinExecutionAdapter(transport_store=self.transport_store, current_profile=profile)
            reading = transport.RTWinReadAdapter(transport_store=self.transport_store)
        popen.assert_not_called()
        self.assertEqual(effect.contract_version, "rtwin-pbs-v1")
        self.assertIsInstance(reading, transport.RTWinReadAdapter)


if __name__ == "__main__":
    unittest.main()
