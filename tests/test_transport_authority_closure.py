#!/usr/bin/env python3
"""Offline L3 reviewer reproductions for the transport-authority closure."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import execution_authorization as AUTH  # noqa: E402
import platform_contracts as PLATFORM  # noqa: E402
import skill_package  # noqa: E402
import transport_authority_closure as CLOSURE  # noqa: E402
from tests import test_execution_authorization as AUTH_TESTS  # noqa: E402


def schema_errors(schema_path: Path, value: Any) -> list[str]:
    """Evaluate the closed Draft 2020-12 subset used by these four schemas."""
    root = json.loads(schema_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    def resolve(ref: str, current_root: dict[str, Any], current_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
        if ref.startswith("#/"):
            node: Any = current_root
            for part in ref[2:].split("/"):
                node = node[part.replace("~1", "/").replace("~0", "~")]
            return node, current_root, current_path
        target_path = current_path.with_name(ref)
        target_root = json.loads(target_path.read_text(encoding="utf-8"))
        return target_root, target_root, target_path

    def walk(node: dict[str, Any], item: Any, label: str, current_root: dict[str, Any], current_path: Path) -> None:
        if "$ref" in node:
            target, target_root, target_path = resolve(node["$ref"], current_root, current_path)
            walk(target, item, label, target_root, target_path)
            return
        if "oneOf" in node:
            matches = 0
            for option in node["oneOf"]:
                before = len(errors)
                walk(option, item, label, current_root, current_path)
                if len(errors) == before:
                    matches += 1
                else:
                    del errors[before:]
            if matches != 1:
                errors.append(f"{label}: oneOf matched {matches}")
            return
        if "const" in node and item != node["const"]:
            errors.append(f"{label}: const")
        if "enum" in node and item not in node["enum"]:
            errors.append(f"{label}: enum")
        kind = node.get("type")
        valid_type = {
            "object": isinstance(item, dict),
            "array": isinstance(item, list),
            "string": isinstance(item, str),
            "integer": isinstance(item, int) and not isinstance(item, bool),
            "boolean": isinstance(item, bool),
            "null": item is None,
        }.get(kind, True)
        if not valid_type:
            errors.append(f"{label}: type {kind}")
            return
        if isinstance(item, str) and "pattern" in node and re.fullmatch(node["pattern"], item) is None:
            errors.append(f"{label}: pattern")
        if isinstance(item, dict):
            properties = node.get("properties", {})
            required = set(node.get("required", []))
            if not required.issubset(item):
                errors.append(f"{label}: missing {sorted(required - set(item))}")
            if node.get("additionalProperties") is False and not set(item).issubset(properties):
                errors.append(f"{label}: extra {sorted(set(item) - set(properties))}")
            for key in set(item) & set(properties):
                walk(properties[key], item[key], f"{label}.{key}", current_root, current_path)
        if isinstance(item, list):
            if len(item) < node.get("minItems", 0) or len(item) > node.get("maxItems", len(item)):
                errors.append(f"{label}: item count")
            if node.get("uniqueItems") and len({json.dumps(entry, sort_keys=True) for entry in item}) != len(item):
                errors.append(f"{label}: duplicates")
            prefix = node.get("prefixItems", [])
            for index, child in enumerate(prefix[:len(item)]):
                walk(child, item[index], f"{label}[{index}]", current_root, current_path)
            if isinstance(node.get("items"), dict):
                for index, child in enumerate(item[len(prefix):], start=len(prefix)):
                    walk(node["items"], child, f"{label}[{index}]", current_root, current_path)
            if node.get("items") is False and len(item) > len(prefix):
                errors.append(f"{label}: extra items")

    walk(root, value, "$", root, schema_path)
    return errors


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
        self.fixture = json.loads((ROOT / "tests/fixtures/rtwin_pbs/transport_authority_closure.json").read_text(encoding="utf-8"))
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
        self.operations = copy.deepcopy(self.base_authorization["identity_attestation"]["operations"])
        for operation in self.operations:
            operation["single_attempt"] = True
        self.operations.append({
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
        self.request_v2 = CLOSURE.build_execution_request_v2(
            request_id=self.fixture["execution_request_id"],
            historical_request=self.base_request,
            profile_v2=self.profile_v2,
            identity_binding=self.binding,
            project=self.base_authorization["workspace_binding"]["project"],
            operations=self.operations,
        )
        self.authorization_v2 = {
            "schema": CLOSURE.AUTHORIZATION_SCHEMA_V2,
            "authorization_id": self.fixture["execution_authorization_id"],
            "request": CLOSURE._request_ref(self.request_v2),
            "historical_execution_authorization": CLOSURE._historical_authorization_ref(self.base_authorization),
            "approver": copy.deepcopy(self.base_authorization["approver"]),
            "approved_at": self.fixture["not_before"],
            "not_before": self.fixture["not_before"],
            "expires_at": self.fixture["expires_at"],
            "decision": "approved",
            "explicit_human_approval": True,
            "profile": copy.deepcopy(self.request_v2["profile"]),
            "project": self.request_v2["project"],
            "transport": {
                "identity_binding_sha256": self.binding["binding_payload_sha256"],
                "hop_count": 2,
                "transport_config_bindings_sha256": self.config_bindings["bindings_payload_sha256"],
            },
            "identity_attestation": {"mode": "legacy_two_stage_then_nested_handshake", "operations": copy.deepcopy(self.operations)},
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
        self.authorization_v2 = self.reseal_authorization(self.authorization_v2)
        self.first_request = PLATFORM.build_first_hop_request(
            profile_sha256=self.profile_v2["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            request_nonce=self.fixture["first_hop_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        self.first_receipt = PLATFORM.build_first_hop_receipt(
            request=self.first_request,
            binding=self.binding,
            observed_fingerprint_evidence_sha256=self.binding["hops"][0]["host_key_evidence_sha256"],
        )
        self.nested_request = PLATFORM.build_nested_hop_request(
            profile_sha256=self.profile_v2["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            first_hop_receipt_sha256=self.first_receipt["receipt_payload_sha256"],
            request_nonce=self.fixture["nested_hop_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        self.nested_receipt = PLATFORM.build_nested_hop_receipt(
            request=self.nested_request,
            binding=self.binding,
            first_hop_receipt=self.first_receipt,
            first_hop_request=self.first_request,
        )
        self.handshake_request = CLOSURE.build_nested_handshake_request(
            profile_v2=self.profile_v2,
            identity_binding=self.binding,
            first_hop_request=self.first_request,
            first_hop_receipt=self.first_receipt,
            nested_hop_request=self.nested_request,
            nested_hop_receipt=self.nested_receipt,
            request_nonce=self.fixture["handshake_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        self.observation = CLOSURE.finalize({
            "schema": CLOSURE.HANDSHAKE_OBSERVATION_SCHEMA,
            **{key: self.handshake_request[key] for key in (
                "profile_sha256", "transport_identity_binding_sha256",
                "transport_config_bindings_sha256", "first_hop_receipt_sha256",
                "nested_hop_receipt_sha256", "request_nonce", "issued_at",
                "expires_at", "operation_version",
            )},
            "second_hop_identity_sha256": PLATFORM._hop_identity_sha256(self.binding["hops"][1]),
            "approved_host_key_evidence_sha256": self.binding["hops"][1]["host_key_evidence_sha256"],
            "observed_fingerprint_evidence_sha256": self.binding["hops"][1]["host_key_evidence_sha256"],
            "classification": "observed",
            "read_only": True,
            "single_attempt": True,
            "automatic_retry": False,
            "mutation_allowed": False,
            "no_execution_authorization": True,
            "observation_payload_sha256": "",
        }, "observation_payload_sha256")
        self.handshake_receipt = CLOSURE.build_nested_handshake_receipt(
            request=self.handshake_request,
            observation=self.observation,
            **self.stage_arguments(),
        )

    def tearDown(self) -> None:
        self.helper.tearDown()

    def stage_arguments(self) -> dict[str, Any]:
        return {
            "profile_v2": self.profile_v2,
            "identity_binding": self.binding,
            "first_hop_request": self.first_request,
            "first_hop_receipt": self.first_receipt,
            "nested_hop_request": self.nested_request,
            "nested_hop_receipt": self.nested_receipt,
        }

    def handshake_stage_arguments(self) -> dict[str, Any]:
        arguments = self.stage_arguments()
        arguments.pop("profile_v2")
        arguments.pop("identity_binding")
        return arguments

    def successor_closure(self) -> CLOSURE.SealedSuccessorClosure:
        return CLOSURE.validate_successor_closure(
            successor_request=self.request_v2,
            successor_authorization=self.authorization_v2,
            base_request=self.base_request,
            base_authorization=self.base_authorization,
            profile_v1=self.profile_v1,
            profile_v2=self.profile_v2,
            identity_binding=self.binding,
            now=self.now,
        )

    @staticmethod
    def reseal_authorization(document: dict[str, Any]) -> dict[str, Any]:
        document["scope_sha256"] = CLOSURE._scope_sha256(document)
        return CLOSURE.finalize(document, "authorization_payload_sha256")

    def assert_schema_valid(self, name: str, value: Any) -> None:
        self.assertEqual(schema_errors(ROOT / "contracts/execution" / name, value), [])

    def test_request_authorization_and_actual_receipt_chain_close_offline(self) -> None:
        checked = self.successor_closure()
        self.assertIsInstance(checked, CLOSURE.SealedSuccessorClosure)
        self.assertRegex(checked.payload_sha256, r"^[a-f0-9]{64}$")
        with self.assertRaises(TypeError):
            CLOSURE.SealedSuccessorClosure(b"{}", "a" * 64, seal=object())
        with self.assertRaises(AttributeError):
            checked._payload_sha256 = "a" * 64
        result = CLOSURE.validate_handshake_authority_binding(
            successor_closure=checked,
            request=self.handshake_request,
            observation=self.observation,
            receipt=self.handshake_receipt,
            now=self.now,
            **self.handshake_stage_arguments(),
        )
        self.assertEqual(result, self.handshake_receipt)
        self.assertTrue(result["no_execution_authorization"])

    def test_request2_is_permanently_non_authorizing_and_exactly_bound(self) -> None:
        for field, value in (
            ("intent_only", False),
            ("proposal_only", False),
            ("no_execution_authorization", False),
            ("live_actions_performed", True),
        ):
            changed = copy.deepcopy(self.request_v2)
            changed[field] = value
            changed = CLOSURE.finalize(changed, "request_payload_sha256")
            with self.subTest(field=field), self.assertRaises(CLOSURE.TransportAuthorityError):
                CLOSURE.validate_execution_request_v2(changed)
        unrelated = copy.deepcopy(self.request_v2)
        unrelated["request_id"] = "unrelated-request-placeholder"
        unrelated = CLOSURE.finalize(unrelated, "request_payload_sha256")
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "binding mismatch"):
            CLOSURE.validate_successor_closure(
                successor_request=unrelated,
                successor_authorization=self.authorization_v2,
                base_request=self.base_request,
                base_authorization=self.base_authorization,
                profile_v1=self.profile_v1,
                profile_v2=self.profile_v2,
                identity_binding=self.binding,
                now=self.now,
            )

    def test_historical_overlay_cannot_splice_unrelated_request_or_authorization(self) -> None:
        unrelated_base = copy.deepcopy(self.base_request)
        unrelated_base["request_id"] = "unrelated-historical-request"
        unrelated_base = AUTH.finalize(unrelated_base, "request_payload_sha256")
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "historical authorization/request"):
            CLOSURE.validate_successor_closure(
                successor_request=self.request_v2,
                successor_authorization=self.authorization_v2,
                base_request=unrelated_base,
                base_authorization=self.base_authorization,
                profile_v1=self.profile_v1,
                profile_v2=self.profile_v2,
                identity_binding=self.binding,
                now=self.now,
            )
        changed = copy.deepcopy(self.authorization_v2)
        changed["historical_execution_authorization"]["authorization_payload_sha256"] = "a" * 64
        changed = self.reseal_authorization(changed)
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "historical authorization provenance"):
            CLOSURE.validate_successor_closure(
                successor_request=self.request_v2,
                successor_authorization=changed,
                base_request=self.base_request,
                base_authorization=self.base_authorization,
                profile_v1=self.profile_v1,
                profile_v2=self.profile_v2,
                identity_binding=self.binding,
                now=self.now,
            )

    def test_actual_stage_receipts_are_owner_validated_and_caller_digests_are_not_an_api(self) -> None:
        self.assertNotIn("first_hop_receipt_sha256", inspect.signature(CLOSURE.build_nested_handshake_request).parameters)
        self.assertNotIn("nested_hop_receipt_sha256", inspect.signature(CLOSURE.build_nested_handshake_request).parameters)
        changed_first = copy.deepcopy(self.first_receipt)
        changed_first["request_nonce"] = "4" * 32
        changed_first = PLATFORM.finalize(changed_first, "receipt_payload_sha256")
        with self.assertRaises(ValueError):
            CLOSURE.validate_handshake_authority_binding(
                successor_closure=self.successor_closure(),
                request=self.handshake_request,
                observation=self.observation,
                receipt=self.handshake_receipt,
                first_hop_request=self.first_request,
                first_hop_receipt=changed_first,
                nested_hop_request=self.nested_request,
                nested_hop_receipt=self.nested_receipt,
                now=self.now,
            )

    def test_observation_is_owner_validated_before_verified_receipt(self) -> None:
        self.assertNotIn("observed_fingerprint_evidence_sha256", inspect.signature(CLOSURE.build_nested_handshake_receipt).parameters)
        changed = copy.deepcopy(self.observation)
        changed["approved_host_key_evidence_sha256"] = "a" * 64
        changed = CLOSURE.finalize(changed, "observation_payload_sha256")
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "approved_host_key"):
            CLOSURE.build_nested_handshake_receipt(
                request=self.handshake_request,
                observation=changed,
                **self.stage_arguments(),
            )

    def test_self_hashed_arbitrary_fingerprint_evidence_cannot_be_promoted(self) -> None:
        changed = copy.deepcopy(self.observation)
        changed["observed_fingerprint_evidence_sha256"] = "f" * 64
        changed = CLOSURE.finalize(changed, "observation_payload_sha256")
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "fingerprint evidence"):
            CLOSURE.build_nested_handshake_receipt(
                request=self.handshake_request,
                observation=changed,
                **self.stage_arguments(),
            )

    def test_handshake_entry_cannot_skip_the_full_successor_closure(self) -> None:
        parameters = inspect.signature(CLOSURE.validate_handshake_authority_binding).parameters
        self.assertIn("successor_closure", parameters)
        self.assertNotIn("successor_request", parameters)
        self.assertNotIn("successor_authorization", parameters)
        spliced_request = copy.deepcopy(self.request_v2)
        spliced_request["historical_request"]["request_payload_sha256"] = "f" * 64
        spliced_request = CLOSURE.finalize(spliced_request, "request_payload_sha256")
        spliced_authorization = copy.deepcopy(self.authorization_v2)
        spliced_authorization["request"] = CLOSURE._request_ref(spliced_request)
        spliced_authorization = self.reseal_authorization(spliced_authorization)
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "historical request provenance"):
            CLOSURE.validate_successor_closure(
                successor_request=spliced_request,
                successor_authorization=spliced_authorization,
                base_request=self.base_request,
                base_authorization=self.base_authorization,
                profile_v1=self.profile_v1,
                profile_v2=self.profile_v2,
                identity_binding=self.binding,
                now=self.now,
            )
        with self.assertRaises(TypeError):
            CLOSURE.validate_handshake_authority_binding(
                successor_request=spliced_request,
                successor_authorization=spliced_authorization,
                request=self.handshake_request,
                observation=self.observation,
                receipt=self.handshake_receipt,
                now=self.now,
                **self.handshake_stage_arguments(),
            )
        forged = self.successor_closure()
        forged_payload = json.loads(forged._canonical_payload)
        forged_payload["successor_request"] = spliced_request
        forged_payload["successor_authorization"] = spliced_authorization
        forged_bytes = PLATFORM.canonical_bytes(forged_payload)
        object.__setattr__(forged, "_canonical_payload", forged_bytes)
        object.__setattr__(forged, "_payload_sha256", hashlib.sha256(forged_bytes).hexdigest())
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "historical request provenance"):
            CLOSURE.validate_handshake_authority_binding(
                successor_closure=forged,
                request=self.handshake_request,
                observation=self.observation,
                receipt=self.handshake_receipt,
                now=self.now,
                **self.handshake_stage_arguments(),
            )

    def test_actual_stage_a_chain_must_match_authorized_operation_zero(self) -> None:
        first_request = PLATFORM.build_first_hop_request(
            profile_sha256=self.profile_v2["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            request_nonce="4" * 32,
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        first_receipt = PLATFORM.build_first_hop_receipt(
            request=first_request,
            binding=self.binding,
            observed_fingerprint_evidence_sha256=self.binding["hops"][0]["host_key_evidence_sha256"],
        )
        nested_request = PLATFORM.build_nested_hop_request(
            profile_sha256=self.profile_v2["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            first_hop_receipt_sha256=first_receipt["receipt_payload_sha256"],
            request_nonce=self.fixture["nested_hop_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        nested_receipt = PLATFORM.build_nested_hop_receipt(
            request=nested_request,
            binding=self.binding,
            first_hop_receipt=first_receipt,
            first_hop_request=first_request,
        )
        stage_arguments = {
            "profile_v2": self.profile_v2,
            "identity_binding": self.binding,
            "first_hop_request": first_request,
            "first_hop_receipt": first_receipt,
            "nested_hop_request": nested_request,
            "nested_hop_receipt": nested_receipt,
        }
        handshake_request = CLOSURE.build_nested_handshake_request(
            request_nonce=self.fixture["handshake_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
            **stage_arguments,
        )
        observation = copy.deepcopy(self.observation)
        for field in (
            "profile_sha256", "transport_identity_binding_sha256",
            "transport_config_bindings_sha256", "first_hop_receipt_sha256",
            "nested_hop_receipt_sha256", "request_nonce", "issued_at",
            "expires_at", "operation_version",
        ):
            observation[field] = handshake_request[field]
        observation = CLOSURE.finalize(observation, "observation_payload_sha256")
        receipt = CLOSURE.build_nested_handshake_receipt(
            request=handshake_request,
            observation=observation,
            **stage_arguments,
        )
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "operation 0"):
            handshake_stage_arguments = copy.deepcopy(stage_arguments)
            handshake_stage_arguments.pop("profile_v2")
            handshake_stage_arguments.pop("identity_binding")
            CLOSURE.validate_handshake_authority_binding(
                successor_closure=self.successor_closure(),
                request=handshake_request,
                observation=observation,
                receipt=receipt,
                now=self.now,
                **handshake_stage_arguments,
            )

    def test_actual_stage_b_chain_must_match_authorized_operation_one(self) -> None:
        nested_request = PLATFORM.build_nested_hop_request(
            profile_sha256=self.profile_v2["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            first_hop_receipt_sha256=self.first_receipt["receipt_payload_sha256"],
            request_nonce="5" * 32,
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
        )
        nested_receipt = PLATFORM.build_nested_hop_receipt(
            request=nested_request,
            binding=self.binding,
            first_hop_receipt=self.first_receipt,
            first_hop_request=self.first_request,
        )
        stage_arguments = {
            "profile_v2": self.profile_v2,
            "identity_binding": self.binding,
            "first_hop_request": self.first_request,
            "first_hop_receipt": self.first_receipt,
            "nested_hop_request": nested_request,
            "nested_hop_receipt": nested_receipt,
        }
        handshake_request = CLOSURE.build_nested_handshake_request(
            request_nonce=self.fixture["handshake_nonce"],
            issued_at=self.fixture["not_before"],
            expires_at=self.fixture["expires_at"],
            **stage_arguments,
        )
        observation = copy.deepcopy(self.observation)
        for field in (
            "profile_sha256", "transport_identity_binding_sha256",
            "transport_config_bindings_sha256", "first_hop_receipt_sha256",
            "nested_hop_receipt_sha256", "request_nonce", "issued_at",
            "expires_at", "operation_version",
        ):
            observation[field] = handshake_request[field]
        observation = CLOSURE.finalize(observation, "observation_payload_sha256")
        receipt = CLOSURE.build_nested_handshake_receipt(
            request=handshake_request,
            observation=observation,
            **stage_arguments,
        )
        handshake_stage_arguments = copy.deepcopy(stage_arguments)
        handshake_stage_arguments.pop("profile_v2")
        handshake_stage_arguments.pop("identity_binding")
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "operation 1"):
            CLOSURE.validate_handshake_authority_binding(
                successor_closure=self.successor_closure(),
                request=handshake_request,
                observation=observation,
                receipt=receipt,
                now=self.now,
                **handshake_stage_arguments,
            )

    def test_handshake_chain_must_match_authorized_operation_two(self) -> None:
        request_v2 = copy.deepcopy(self.request_v2)
        request_v2["requested_operations"][2]["request_nonce"] = "6" * 32
        request_v2 = CLOSURE.finalize(request_v2, "request_payload_sha256")
        authorization_v2 = copy.deepcopy(self.authorization_v2)
        authorization_v2["request"] = CLOSURE._request_ref(request_v2)
        authorization_v2["identity_attestation"]["operations"][2]["request_nonce"] = "6" * 32
        authorization_v2 = self.reseal_authorization(authorization_v2)
        successor_closure = CLOSURE.validate_successor_closure(
            successor_request=request_v2,
            successor_authorization=authorization_v2,
            base_request=self.base_request,
            base_authorization=self.base_authorization,
            profile_v1=self.profile_v1,
            profile_v2=self.profile_v2,
            identity_binding=self.binding,
            now=self.now,
        )
        with self.assertRaisesRegex(CLOSURE.TransportAuthorityError, "request_nonce"):
            CLOSURE.validate_handshake_authority_binding(
                successor_closure=successor_closure,
                request=self.handshake_request,
                observation=self.observation,
                receipt=self.handshake_receipt,
                now=self.now,
                **self.handshake_stage_arguments(),
            )

    def test_schema_python_parity_for_finite_critical_surfaces(self) -> None:
        samples = (
            ("execution-profile-v2.schema.json", self.profile_v2, CLOSURE.validate_execution_profile_v2),
            ("execution-request-v2.schema.json", self.request_v2, CLOSURE.validate_execution_request_v2),
            ("execution-authorization-v2.schema.json", self.authorization_v2, lambda value: CLOSURE.validate_execution_authorization_v2(value, now=self.now)),
            ("nested-hop-identity-handshake.schema.json", self.handshake_request, lambda value: CLOSURE.validate_nested_handshake_request(value, now=self.now)),
            ("nested-hop-identity-handshake.schema.json", self.observation, lambda value: CLOSURE.validate_nested_handshake_observation(value, request=self.handshake_request, now=self.now, **self.stage_arguments())),
            ("nested-hop-identity-handshake.schema.json", self.handshake_receipt, lambda value: CLOSURE.validate_nested_handshake_receipt(value, request=self.handshake_request, observation=self.observation, now=self.now, **self.stage_arguments())),
        )
        for schema_name, sample, validator in samples:
            with self.subTest(schema=schema_name, kind=sample["schema"]):
                self.assert_schema_valid(schema_name, sample)
                self.assertEqual(validator(sample), sample)
        unsorted = copy.deepcopy(self.profile_v2)
        unsorted["declared_capabilities"] = list(reversed(unsorted["declared_capabilities"]))
        unsorted = CLOSURE.finalize(unsorted, "profile_payload_sha256")
        self.assert_schema_valid("execution-profile-v2.schema.json", unsorted)
        self.assertEqual(CLOSURE.validate_execution_profile_v2(unsorted), unsorted)
        same_digest_bindings = CLOSURE.build_transport_config_bindings(
            first_hop_ref_sha256=self.fixture["first_hop_adapter_config_ref_sha256"],
            second_hop_ref_sha256=self.fixture["first_hop_adapter_config_ref_sha256"],
        )
        same_digest_profile = CLOSURE.build_execution_profile_v2(
            profile_id=self.profile_v1["profile_id"],
            identity_binding=self.binding,
            transport_config_bindings=same_digest_bindings,
            declared_capabilities=self.profile_v1["declared_capabilities"],
            executable_ref=self.profile_v1["gaussian_runtime"]["executable_ref"],
        )
        self.assert_schema_valid("execution-profile-v2.schema.json", same_digest_profile)
        self.assertEqual(CLOSURE.validate_execution_profile_v2(same_digest_profile), same_digest_profile)
        long_historical = copy.deepcopy(self.request_v2)
        long_historical["historical_request"]["request_id"] = "a" * 65
        long_historical = CLOSURE.finalize(long_historical, "request_payload_sha256")
        self.assert_schema_valid("execution-request-v2.schema.json", long_historical)
        self.assertEqual(CLOSURE.validate_execution_request_v2(long_historical), long_historical)
        long_principal = copy.deepcopy(self.authorization_v2)
        long_principal["approver"]["principal_id"] = "a" * 65
        long_principal = self.reseal_authorization(long_principal)
        self.assert_schema_valid("execution-authorization-v2.schema.json", long_principal)
        self.assertEqual(
            CLOSURE.validate_execution_authorization_v2(long_principal, now=self.now),
            long_principal,
        )
        invalid_cases = []
        empty = copy.deepcopy(self.profile_v2)
        empty["declared_capabilities"] = []
        invalid_cases.append(("execution-profile-v2.schema.json", CLOSURE.finalize(empty, "profile_payload_sha256"), CLOSURE.validate_execution_profile_v2))
        long_id = copy.deepcopy(self.authorization_v2)
        long_id["authorization_id"] = "a" * 65
        invalid_cases.append(("execution-authorization-v2.schema.json", self.reseal_authorization(long_id), lambda value: CLOSURE.validate_execution_authorization_v2(value, now=self.now)))
        bad_operation = copy.deepcopy(self.request_v2)
        bad_operation["requested_operations"][2]["operation"] = "transfer_exact_bundle_once"
        invalid_cases.append(("execution-request-v2.schema.json", CLOSURE.finalize(bad_operation, "request_payload_sha256"), CLOSURE.validate_execution_request_v2))
        extra_handshake = copy.deepcopy(self.handshake_request)
        extra_handshake["caller_digest"] = "a" * 64
        invalid_cases.append(("nested-hop-identity-handshake.schema.json", extra_handshake, lambda value: CLOSURE.validate_nested_handshake_request(value, now=self.now)))
        bad_observation = copy.deepcopy(self.observation)
        bad_observation["classification"] = "verified"
        bad_observation = CLOSURE.finalize(bad_observation, "observation_payload_sha256")
        invalid_cases.append(("nested-hop-identity-handshake.schema.json", bad_observation, lambda value: CLOSURE.validate_nested_handshake_observation(value, request=self.handshake_request, now=self.now, **self.stage_arguments())))
        caller_verdict = copy.deepcopy(self.observation)
        caller_verdict["observed_fingerprint_matches_approved"] = True
        caller_verdict = CLOSURE.finalize(caller_verdict, "observation_payload_sha256")
        invalid_cases.append(("nested-hop-identity-handshake.schema.json", caller_verdict, lambda value: CLOSURE.validate_nested_handshake_observation(value, request=self.handshake_request, now=self.now, **self.stage_arguments())))
        for schema_name, sample, validator in invalid_cases:
            with self.subTest(schema=schema_name, invalid=True):
                self.assertTrue(schema_errors(ROOT / "contracts/execution" / schema_name, sample))
                with self.assertRaises(CLOSURE.TransportAuthorityError):
                    validator(sample)

    def test_schemas_are_closed_package_complete_and_owner_relocates(self) -> None:
        schema_names = (
            "execution-profile-v2.schema.json",
            "execution-request-v2.schema.json",
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

        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        for name in schema_names:
            schema = json.loads((ROOT / "contracts/execution" / name).read_text(encoding="utf-8"))
            inspect_closed(schema)
            self.assertIn(Path("contracts/execution") / name, package)
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "auto-g16-rtwin-pbs"
            for target, source in package.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            script = installed / "scripts/transport_authority_closure.py"
            spec = importlib.util.spec_from_file_location("relocated_transport_authority_closure", script)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.validate_execution_request_v2(self.request_v2), self.request_v2)

    def test_pr4a_recognition_and_unique_b1_legacy_effect_chain_are_bound(self) -> None:
        source = (ROOT / "scripts/transport_authority_closure.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        self.assertTrue(imports.isdisjoint({"argparse", "subprocess", "socket", "urllib", "requests", "paramiko"}))
        model_source = (ROOT / "skills/auto-g16-rtwin-pbs/scripts/execution_models.py").read_text(encoding="utf-8")
        backend_source = (ROOT / "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py").read_text(encoding="utf-8")
        self.assertIn("TransportAuthorityReplay", model_source)
        backend_tree = ast.parse(backend_source)

        def method(class_name: str, method_name: str) -> ast.FunctionDef:
            owner = next(
                node
                for node in backend_tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            )
            return next(
                node
                for node in owner.body
                if isinstance(node, ast.FunctionDef) and node.name == method_name
            )

        def function(function_name: str) -> ast.FunctionDef:
            return next(
                node
                for node in backend_tree.body
                if isinstance(node, ast.FunctionDef) and node.name == function_name
            )

        def call_name(call: ast.Call) -> str:
            parts: list[str] = []
            value = call.func
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            return ".".join(reversed(parts))

        def calls(node: ast.AST) -> list[str]:
            return [
                call_name(child)
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
            ]

        cli_calls = calls(method("LegacyCLICompatibilityAdapter", "_submit_new"))
        transport_calls = calls(method("LegacyTransportAdapter", "invoke_reserved_once"))
        transaction_calls = calls(function("_execute_legacy_transaction_once"))
        self.assertEqual(
            cli_calls.count("_legacy_transaction_plan_from_cli_namespace"),
            1,
        )
        self.assertEqual(
            cli_calls.count("self.backend.transport.invoke_reserved_once"),
            1,
        )
        self.assertEqual(
            transport_calls.count("_execute_legacy_transaction_once"),
            1,
        )
        self.assertEqual(
            transaction_calls.count("_legacy_effect_plan_from_transaction"),
            1,
        )
        self.assertEqual(
            transaction_calls.count("_legacy_raw_effect_owner_from_plan"),
            1,
        )
        self.assertEqual(
            transaction_calls.count("effect_owner.submit_qsub_once"),
            1,
        )
        skill_scripts = ROOT / "skills/auto-g16-rtwin-pbs/scripts"
        sys.path.insert(0, str(skill_scripts))
        try:
            from execution_models import TransportAuthorityReplay

            path = self.helper.write_new("execution-authorization-v2.json", self.authorization_v2)
            replay = TransportAuthorityReplay.from_successor_owner(path, now=self.now)
            self.assertEqual(replay.request_id, self.request_v2["request_id"])
            self.assertEqual(
                replay.historical_authorization_id,
                self.base_authorization["authorization_id"],
            )
            self.assertEqual(len(replay.operations), 3)
        finally:
            sys.path.remove(str(skill_scripts))
        for forbidden in ("ready_to_submit", "authorized_for_live"):
            self.assertNotIn(forbidden, source)

    def test_combined_process_runtime_config_import_orders_are_isolated_in_both_layouts(self) -> None:
        def load_named(path: Path, name: str) -> Any:
            spec = importlib.util.spec_from_file_location(name, path)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        prior_runtime = sys.modules.get("runtime_config")
        try:
            root_runtime = load_named(ROOT / "scripts/runtime_config.py", "runtime_config")
            with AUTH._controlled_owner_bundle() as owners:
                self.assertEqual(
                    Path(owners.runtime_config.__file__).resolve(),
                    (ROOT / "skills/auto-g16-rtwin-pbs/scripts/runtime_config.py").resolve(),
                )
                self.assertIs(owners.gaussian_rtwin_pbs.setting, owners.runtime_config.setting)
            self.assertIs(sys.modules.get("runtime_config"), root_runtime)

            package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
            with tempfile.TemporaryDirectory() as temporary:
                installed = Path(temporary) / "auto-g16-rtwin-pbs"
                for target, source in package.items():
                    destination = installed / target
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                script_dir = installed / "scripts"
                packaged_spec = importlib.util.spec_from_file_location(
                    "packaged_execution_authorization_import_order",
                    script_dir / "execution_authorization.py",
                )
                assert packaged_spec and packaged_spec.loader
                packaged_auth = importlib.util.module_from_spec(packaged_spec)
                sys.modules[packaged_spec.name] = packaged_auth
                try:
                    packaged_spec.loader.exec_module(packaged_auth)
                finally:
                    sys.modules.pop(packaged_spec.name, None)

                packaged_root_runtime = load_named(
                    script_dir / "platform_runtime_config_owner.py",
                    "runtime_config",
                )
                with packaged_auth._controlled_owner_bundle() as owners:
                    self.assertEqual(
                        Path(owners.runtime_config.__file__).resolve(),
                        (script_dir / "runtime_config.py").resolve(),
                    )
                    self.assertIs(owners.gaussian_rtwin_pbs.setting, owners.runtime_config.setting)
                self.assertIs(sys.modules.get("runtime_config"), packaged_root_runtime)

                packaged_skill_runtime = load_named(script_dir / "runtime_config.py", "runtime_config")
                with AUTH._controlled_owner_bundle() as owners:
                    self.assertEqual(
                        Path(owners.runtime_config.__file__).resolve(),
                        (ROOT / "skills/auto-g16-rtwin-pbs/scripts/runtime_config.py").resolve(),
                    )
                self.assertIs(sys.modules.get("runtime_config"), packaged_skill_runtime)
        finally:
            sys.modules.pop("runtime_config", None)
            if prior_runtime is not None:
                sys.modules["runtime_config"] = prior_runtime


if __name__ == "__main__":
    unittest.main()
