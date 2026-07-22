#!/usr/bin/env python3
"""Offline tests for the PR4B transport-authority prerequisite contracts."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import execution_authorization as AUTH  # noqa: E402
import platform_contracts as PLATFORM  # noqa: E402
import skill_package  # noqa: E402
import transport_authority_closure as CLOSURE  # noqa: E402
from tests import test_execution_authorization as AUTH_TESTS  # noqa: E402


class TransportAuthorityClosureTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.helper = AUTH_TESTS.ExecutionAuthorizationTests("test_exact_synthetic_happy_path_is_only_closure_valid_offline")
        self.helper.setUp()
        self.now = self.helper.now
        self.base_request = self.helper.fixture["request"]
        self.base_authorization = self.helper.fixture["authorization"]
        self.profile_v1 = PLATFORM.load_execution_profile(self.helper.fixture["profile_path"])
        self.binding = PLATFORM.load_transport_identity_binding(self.helper.fixture["binding_path"])
        self.fixture = json.loads((ROOT / "tests" / "fixtures" / "rtwin_pbs" / "transport_authority_closure.json").read_text(encoding="utf-8"))
        self.config_bindings = CLOSURE.build_transport_config_bindings(
            first_hop_ref_sha256=self.fixture["first_hop_adapter_config_ref_sha256"],
            second_hop_ref_sha256=self.fixture["second_hop_adapter_config_ref_sha256"],
        )
        self.profile_v2 = CLOSURE.build_execution_profile_v2(
            profile_id=self.profile_v1["profile_id"],
            identity_binding=self.binding,
            transport_config_bindings=self.config_bindings,
            declared_capabilities=self.profile_v1["declared_capabilities"],
            executable_ref=self.profile_v1["gaussian_runtime"]["executable_ref"],
        )
        operations = copy.deepcopy(self.base_authorization["identity_attestation"]["operations"])
        for operation in operations:
            operation["single_attempt"] = True
        operations.append({
            "operation": "handshake_nested_hop_identity_once",
            "operation_version": CLOSURE.HANDSHAKE_OPERATION_VERSION,
            "request_nonce": self.fixture["handshake_nonce"],
            "not_before": self.fixture["not_before"],
            "expires_at": self.fixture["expires_at"],
            "allowed_read_only_side_effects": ["network_identity_handshake"],
            "read_only": True,
            "single_attempt": True,
            "automatic_retry": False,
            "mutation_allowed": False,
        })
        self.successor = {
            "schema": CLOSURE.AUTHORIZATION_SCHEMA_V2,
            "authorization_id": "transport-authority-placeholder",
            "base_request": {
                "schema": self.base_request["schema"],
                "request_id": self.base_request["request_id"],
                "request_payload_sha256": self.base_request["request_payload_sha256"],
            },
            "base_execution_authorization": {
                "schema": self.base_authorization["schema"],
                "authorization_id": self.base_authorization["authorization_id"],
                "scope_sha256": self.base_authorization["scope_sha256"],
                "authorization_payload_sha256": self.base_authorization["authorization_payload_sha256"],
            },
            "approver": copy.deepcopy(self.base_authorization["approver"]),
            "approved_at": self.fixture["not_before"],
            "not_before": self.fixture["not_before"],
            "expires_at": self.fixture["expires_at"],
            "decision": "approved",
            "explicit_human_approval": True,
            "profile": {
                "schema": self.profile_v2["schema"],
                "profile_id": self.profile_v2["profile_id"],
                "profile_sha256": self.profile_v2["profile_payload_sha256"],
                "backend_kind": self.profile_v2["backend_kind"],
            },
            "project": self.base_authorization["workspace_binding"]["project"],
            "transport": {
                "identity_binding_sha256": self.binding["binding_payload_sha256"],
                "hop_count": 2,
                "transport_config_bindings_sha256": self.config_bindings["bindings_payload_sha256"],
            },
            "identity_attestation": {
                "mode": "legacy_two_stage_then_nested_handshake",
                "operations": operations,
            },
            "authority_delta": {
                "read_only_identity_handshake_only": True,
                "stage_authorized": False,
                "submit_authorized": False,
                "cancel_authorized": False,
                "fetch_authorized": False,
                "arbitrary_command_authorized": False,
            },
            "revocation": {"revoked": False, "revoked_at": None, "reason": None},
            "consumption": {"single_use": True, "consumed": False},
            "scope_sha256": "",
            "authorization_payload_sha256": "",
        }
        self.successor["scope_sha256"] = CLOSURE._scope_sha256(self.successor)
        self.successor = CLOSURE.finalize(self.successor, "authorization_payload_sha256")

    def tearDown(self) -> None:
        self.helper.tearDown()

    def reseal(self, document: dict[str, object]) -> dict[str, object]:
        document["scope_sha256"] = CLOSURE._scope_sha256(document)
        return CLOSURE.finalize(document, "authorization_payload_sha256")

    def test_valid_successor_closes_profile_pr3_and_handshake_receipt_offline(self) -> None:
        checked = CLOSURE.validate_successor_closure(
            successor_authorization=self.successor,
            base_request=self.base_request,
            base_authorization=self.base_authorization,
            profile_v1=self.profile_v1,
            profile_v2=self.profile_v2,
            identity_binding=self.binding,
            now=self.now,
        )
        self.assertEqual(len(checked["identity_attestation"]["operations"]), 3)
        request = CLOSURE.build_nested_handshake_request(
            profile_sha256=self.profile_v2["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            config_bindings_sha256=self.config_bindings["bindings_payload_sha256"],
            first_hop_receipt_sha256=self.fixture["first_hop_receipt_sha256"],
            nested_hop_receipt_sha256=self.fixture["nested_hop_receipt_sha256"],
            request_nonce=self.fixture["handshake_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        receipt = CLOSURE.build_nested_handshake_receipt(
            request=request,
            profile_v2=self.profile_v2,
            identity_binding=self.binding,
            observed_fingerprint_evidence_sha256=self.fixture["observed_fingerprint_evidence_sha256"],
        )
        self.assertTrue(receipt["no_execution_authorization"])
        self.assertFalse(receipt["mutation_allowed"])
        self.assertEqual(receipt, CLOSURE.validate_nested_handshake_receipt(
            receipt, request=request, profile_v2=self.profile_v2,
            identity_binding=self.binding, now=self.now,
        ))
        self.assertEqual(receipt, CLOSURE.validate_handshake_authority_binding(
            successor_authorization=self.successor, request=request, receipt=receipt,
            profile_v2=self.profile_v2, identity_binding=self.binding, now=self.now,
        ))
        mismatched_request = copy.deepcopy(request)
        mismatched_request["request_nonce"] = "4" * 32
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "differs from authorized operation"):
            CLOSURE.validate_handshake_authority_binding(
                successor_authorization=self.successor, request=mismatched_request,
                receipt=receipt, profile_v2=self.profile_v2,
                identity_binding=self.binding, now=self.now,
            )
        wrong_binding = copy.deepcopy(self.binding)
        wrong_binding["hops"][1]["effective_target_identity_sha256"] = self.fixture["second_hop_identity_sha256"]
        wrong_binding = PLATFORM.finalize(wrong_binding, "binding_payload_sha256")
        with self.assertRaises(CLOSURE.TransportAuthorityError):
            CLOSURE.validate_nested_handshake_receipt(
                receipt, request=request, profile_v2=self.profile_v2,
                identity_binding=wrong_binding, now=self.now,
            )

    def test_two_hop_config_refs_are_distinct_hash_only_and_profile_bound(self) -> None:
        serialized = PLATFORM.canonical_bytes(self.profile_v2).decode("utf-8").lower()
        for forbidden in ("/opt/", "/users/", "c:\\", "hostname", "username", "fingerprint", "private key"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(self.profile_v2["transport_config_bindings"], self.config_bindings)
        for mutation in ("missing", "swapped", "confused"):
            changed = copy.deepcopy(self.profile_v2)
            if mutation == "missing":
                del changed["transport_config_bindings"]["second_hop"]
            elif mutation == "swapped":
                changed["transport_config_bindings"]["first_hop"], changed["transport_config_bindings"]["second_hop"] = changed["transport_config_bindings"]["second_hop"], changed["transport_config_bindings"]["first_hop"]
            else:
                changed["transport_config_bindings"]["second_hop"]["adapter_config_ref_sha256"] = changed["transport_config_bindings"]["first_hop"]["adapter_config_ref_sha256"]
                changed["transport_config_bindings"] = CLOSURE.finalize(changed["transport_config_bindings"], "bindings_payload_sha256")
            changed = CLOSURE.finalize(changed, "profile_payload_sha256")
            with self.subTest(mutation=mutation), self.assertRaises(CLOSURE.TransportAuthorityError):
                CLOSURE.validate_execution_profile_v2(changed)

    def test_operation_version_effect_retry_time_and_binding_mismatches_fail_closed(self) -> None:
        cases = (
            ("operation_version", "nested-hop-host-key-identity-handshake/2"),
            ("allowed_read_only_side_effects", ["network_identity_handshake", "run_remote_command"]),
            ("automatic_retry", True),
            ("mutation_allowed", True),
            ("expires_at", "2030-01-01T12:10:00Z"),
        )
        for field, value in cases:
            changed = copy.deepcopy(self.successor)
            changed["identity_attestation"]["operations"][2][field] = value
            changed = self.reseal(changed)
            with self.subTest(field=field), self.assertRaises(CLOSURE.TransportAuthorityError):
                CLOSURE.validate_execution_authorization_v2(changed, now=self.now)
        changed = copy.deepcopy(self.successor)
        changed["transport"]["transport_config_bindings_sha256"] = self.fixture["first_hop_adapter_config_ref_sha256"]
        changed = self.reseal(changed)
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "transport closure"):
            CLOSURE.validate_successor_closure(
                successor_authorization=changed, base_request=self.base_request,
                base_authorization=self.base_authorization, profile_v1=self.profile_v1,
                profile_v2=self.profile_v2, identity_binding=self.binding, now=self.now,
            )

    def test_published_v1_is_replay_only_and_cannot_enter_successor_model(self) -> None:
        with self.assertRaises(CLOSURE.TransportAuthorityError):
            CLOSURE.validate_execution_profile_v2(self.profile_v1)
        with self.assertRaises(CLOSURE.TransportAuthorityError):
            CLOSURE.validate_execution_authorization_v2(self.base_authorization, now=self.now)
        skill_scripts = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
        sys.path.insert(0, str(skill_scripts))
        try:
            from execution_models import ModelError, TransportAuthorityReplay
            with self.assertRaises(ModelError):
                TransportAuthorityReplay.from_successor_owner(self.helper.fixture["authorization_path"], now=self.now)
            successor_path = self.helper.write_new("execution-authorization-v2.json", self.successor)
            replay = TransportAuthorityReplay.from_successor_owner(successor_path, now=self.now)
            self.assertEqual(len(replay.operations), 3)
            self.assertEqual(replay.backend_kind, "legacy_rtwin_pbs")
        finally:
            sys.path.remove(str(skill_scripts))

    def test_schemas_are_closed_package_is_complete_and_owner_relocates(self) -> None:
        schema_names = (
            "execution-profile-v2.schema.json",
            "execution-authorization-v2.schema.json",
            "nested-hop-identity-handshake.schema.json",
        )
        def inspect_closed(node: object) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object" and "properties" in node:
                    self.assertFalse(node.get("additionalProperties", True))
                    self.assertEqual(set(node.get("required", [])), set(node["properties"]))
                for child in node.values():
                    inspect_closed(child)
            elif isinstance(node, list):
                for child in node:
                    inspect_closed(child)
        for name in schema_names:
            schema = json.loads((ROOT / "contracts" / "execution" / name).read_text(encoding="utf-8"))
            inspect_closed(schema)
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(package[Path("scripts/transport_authority_closure.py")], ROOT / "scripts" / "transport_authority_closure.py")
        for name in schema_names:
            self.assertIn(Path("contracts/execution") / name, package)
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "auto-g16-rtwin-pbs"
            for target, source in package.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            script = installed / "scripts" / "transport_authority_closure.py"
            spec = importlib.util.spec_from_file_location("relocated_transport_authority_closure", script)
            self.assertIsNotNone(spec and spec.loader)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            self.assertEqual(module.validate_execution_profile_v2(self.profile_v2), self.profile_v2)

    def test_owner_and_pr4a_models_remain_offline_non_executable(self) -> None:
        source = (ROOT / "scripts" / "transport_authority_closure.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        self.assertTrue(imports.isdisjoint({"argparse", "subprocess", "socket", "urllib", "requests", "paramiko"}))
        for forbidden in ("ssh ", "qsub", "qdel", "ready_to_submit", "authorized_for_live"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
