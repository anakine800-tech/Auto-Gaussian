from __future__ import annotations

from dataclasses import fields, is_dataclass
import ast
from hashlib import sha256
import inspect
from pathlib import Path
import shlex
import unittest
from unittest.mock import patch

import auto_g16.transport as transport
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
from auto_g16.transport._driver import _OPERATION_TABLE_BYTES, _OPERATION_TABLE_SHA256

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
        self.assertEqual(len(_OPERATION_TABLE_BYTES), 1490)
        self.assertEqual(sha256(_OPERATION_TABLE_BYTES).hexdigest(), _OPERATION_TABLE_SHA256)
        self.assertEqual(_OPERATION_TABLE_SHA256, "6b9c1f8574bb3541a884ca1532aae0d12a54d52cb158c8f8a9521f2421dc4cc6")
        self.assertEqual(_BOOTSTRAP_SOURCE_NAME, "auto-g16-v3-rtwin-bootstrap-v1.py")
        self.assertEqual(_BOOTSTRAP_SOURCE_BYTES, _BOOTSTRAP_SOURCE.encode("utf-8"))
        self.assertEqual(len(_BOOTSTRAP_SOURCE_BYTES), 12540)
        self.assertEqual(_BOOTSTRAP_SOURCE_BYTES.count(b"\n"), 170)
        self.assertNotIn(b"\r", _BOOTSTRAP_SOURCE_BYTES)
        self.assertNotIn(b"\x00", _BOOTSTRAP_SOURCE_BYTES)
        self.assertEqual(sha256(_BOOTSTRAP_SOURCE_BYTES).hexdigest(), "724869c6767c1570075812832d57c94e8c9e17ae2d4cd1d9f8781b0796671d2f")
        self.assertTrue(_BOOTSTRAP_SOURCE_BYTES.startswith(b"from __future__ import annotations\n"))
        self.assertTrue(_BOOTSTRAP_SOURCE_BYTES.endswith(b"main()\n"))
        self.assertNotIn("eval(", _BOOTSTRAP_SOURCE)
        self.assertNotIn("exec(", _BOOTSTRAP_SOURCE)
        self.assertNotIn("qdel", _BOOTSTRAP_SOURCE)

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
                "runtime_attestation_id": "e42ac09e-e7da-50a3-b03f-54a5199d1686",
                "store_instance_id": "28c10d1a-9f8f-5ce6-84d1-555175c0fcde",
                "submission_intent_id": "intent-1",
                "transport_store_id": "108c8d43-2ea9-5658-9607-ade4cbbeac85",
            },
            "operation": "ALLOCATE_WORKSPACE", "payload": {},
            "protocol": "auto-g16-v3-rtwin-bootstrap/1",
        }
        fetch = {
            "binding": {
                **allocate["binding"],
                "job_authority_id": "fcea1641-0bd5-5892-a66d-f0984eb6bfba",
                "job_id": "123.server",
                "receipt_binding_id": "cb3c8a2a-fa8e-5562-be86-e6b49959ee22",
                "remote_effect_receipt_id": "receipt-1",
                "workspace_authority_id": "c3e44fc0-1907-542b-8ff9-2acf63034d60",
                "workspace_physical_token_base64": "d29ya3NwYWNlLXRva2VuLXYx",
            },
            "operation": "FETCH_EXACT_FILE",
            "payload": {"expected_file_physical_token_base64": "YXJ0aWZhY3QtdG9rZW4tdjE=", "expected_size_bytes": 19, "remote_relative_name": "job.log"},
            "protocol": "auto-g16-v3-rtwin-bootstrap/1",
        }
        for value, size, digest in (
            (allocate, 420, "3ae2f4631874b71c0a023439f51d3a877c87f5f11dd6ba187ccf4ca2c2d81c2a"),
            (fetch, 844, "6bf99083230b68c89593eff76fc93d8458459a87e39695b358a5c71f3f56c9bc"),
        ):
            raw = canonical_json_bytes(value)
            self.assertEqual(len(raw), size)
            self.assertEqual(sha256(raw).hexdigest(), digest)

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
