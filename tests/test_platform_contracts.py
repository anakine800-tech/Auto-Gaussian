#!/usr/bin/env python3
"""Focused offline tests for Auto-G16 v2.6 platform contracts."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import platform_contracts as contracts  # noqa: E402
import skill_package  # noqa: E402


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def hop(kind: str, label: str) -> dict[str, str]:
    return {
        "transport_kind": kind,
        "config_source_bundle_sha256": digest(f"{label}-config"),
        "alias_utf8_sha256": digest(f"{label}-alias"),
        "effective_target_identity_sha256": digest(f"{label}-target"),
        "host_key_policy": "strict_pinned",
        "host_key_evidence_sha256": digest(f"{label}-host-key"),
        "resolver_version": "synthetic-resolver-v1",
    }


def legacy_binding(profile_id: str = "profile-placeholder") -> dict[str, object]:
    return contracts.build_transport_identity_binding(
        binding_id="binding-placeholder",
        profile_id=profile_id,
        hops=[
            hop("legacy_rtwin_first_hop", "first"),
            hop("legacy_rtwin_nested_hop", "nested"),
        ],
    )


class CanonicalJsonTests(unittest.TestCase):
    def test_canonical_projection_orders_unicode_scalars_and_uses_minimal_escapes(self) -> None:
        value = {
            "\U00010000": 4,
            "\ue000": 3,
            "\u00e9": 2,
            "a": ["x/y", "\x00\b\t\n\f\r\"\\"],
        }
        expected = (
            '{"a":["x/y","\\u0000\\b\\t\\n\\f\\r\\\"\\\\"],'
            '"\u00e9":2,"\ue000":3,"\U00010000":4}\n'
        ).encode("utf-8")
        self.assertEqual(contracts.canonical_bytes(value), expected)
        self.assertEqual(contracts.canonical_bytes(value).count(b"\n"), 1)

    def test_canonical_projection_preserves_array_order_and_codepoint_sequences(self) -> None:
        first = {"items": ["e\u0301", "\u00e9"]}
        second = {"items": ["\u00e9", "e\u0301"]}
        self.assertNotEqual(contracts.canonical_bytes(first), contracts.canonical_bytes(second))
        self.assertIn("e\u0301".encode("utf-8"), contracts.canonical_bytes(first))
        self.assertIn("\u00e9".encode("utf-8"), contracts.canonical_bytes(first))

    def test_strict_decoder_rejects_duplicate_bom_utf8_and_non_integer_numbers(self) -> None:
        invalid = (
            b'{"a":1,"a":2}',
            b"\xef\xbb\xbf{}",
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":1.0}',
            b'{"value":1e2}',
            b'{"value":-0}',
            b'{"value":01}',
            b'{"value":+1}',
            b'{"value":"\xff"}',
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.strict_json_loads(raw)

    def test_canonical_projection_rejects_float_and_non_scalar_unicode(self) -> None:
        with self.assertRaisesRegex(contracts.PlatformContractError, "floating-point"):
            contracts.canonical_bytes({"value": 1.0})
        with self.assertRaisesRegex(contracts.PlatformContractError, "non-scalar"):
            contracts.canonical_bytes({"value": "\ud800"})

    def test_synthetic_platform_digest_golden_is_byte_exact(self) -> None:
        golden = json.loads(
            (ROOT / "tests" / "fixtures" / "rtwin_pbs" / "v26_platform_contract_golden.json").read_text(
                encoding="utf-8"
            )
        )
        runtime = {
            "rtwin_ssh_config": "/opt/placeholder/config/rtwin-ssh-config",
            "windows_project_root": "C:\\Placeholder\\Projects",
            "windows_server_config": "C:\\Placeholder\\server-ssh-config",
        }
        mapping = contracts.map_legacy_runtime(runtime)
        binding = legacy_binding(mapping["derived_profile_summary"]["profile_id"])
        profile = contracts.derive_legacy_profile(runtime, binding)
        report = contracts.build_capability_report(profile)
        sample = {
            "\U00010000": 4,
            "\ue000": 3,
            "\u00e9": 2,
            "a": ["x/y", "\x00\b\t\n\f\r\"\\"],
        }
        actual = {
            "schema": "auto-g16-platform-contract-golden/1",
            "canonical_sample_sha256": hashlib.sha256(contracts.canonical_bytes(sample)).hexdigest(),
            "config_source_bundle_vectors": {
                "a_bc": contracts.config_source_bundle_sha256([b"a", b"bc"]),
                "ab_c": contracts.config_source_bundle_sha256([b"ab", b"c"]),
            },
            "catalog_payload_sha256": contracts.build_resource_catalog()["catalog_payload_sha256"],
            "binding_payload_sha256": binding["binding_payload_sha256"],
            "profile_payload_sha256": profile["profile_payload_sha256"],
            "capability_report_payload_sha256": report["report_payload_sha256"],
            "legacy_mapping_payload_sha256": mapping["mapping_payload_sha256"],
        }
        self.assertEqual(actual, golden)


class ResourceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = contracts.build_resource_catalog()

    def test_catalog_reuses_exact_legacy_owner_facts_and_self_hash(self) -> None:
        self.assertEqual(
            self.catalog["reviewed_tuples"],
            [
                {"tier": "simple", "cores": 8, "memory_gb": 12},
                {"tier": "general", "cores": 22, "memory_gb": 50},
                {"tier": "complex", "cores": 44, "memory_gb": 120},
            ],
        )
        self.assertEqual(
            self.catalog["capacity"],
            {"max_job_cores": 44, "max_job_memory_gb": 120},
        )
        self.assertTrue(self.catalog["custom_reviewed_allowed"])
        self.assertTrue(self.catalog["walltime_must_be_explicitly_reviewed"])
        self.assertEqual(
            self.catalog["catalog_payload_sha256"],
            contracts.payload_sha256(self.catalog, "catalog_payload_sha256"),
        )

    def test_catalog_rejects_unknown_duplicate_tier_drift_and_forgery(self) -> None:
        cases: list[dict[str, object]] = []
        unknown = copy.deepcopy(self.catalog)
        unknown["unexpected"] = True
        cases.append(unknown)
        duplicate = copy.deepcopy(self.catalog)
        duplicate["reviewed_tuples"][1]["tier"] = "simple"
        duplicate = contracts.finalize(duplicate, "catalog_payload_sha256")
        cases.append(duplicate)
        drift = copy.deepcopy(self.catalog)
        drift["reviewed_tuples"][0]["cores"] = 7
        drift = contracts.finalize(drift, "catalog_payload_sha256")
        cases.append(drift)
        forged = copy.deepcopy(self.catalog)
        forged["catalog_payload_sha256"] = "0" * 64
        cases.append(forged)
        boolean_integer = copy.deepcopy(self.catalog)
        boolean_integer["capacity"]["max_job_cores"] = True
        boolean_integer = contracts.finalize(boolean_integer, "catalog_payload_sha256")
        cases.append(boolean_integer)
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_resource_catalog(case)

    def test_exact_named_and_custom_resources_are_bounded_and_non_authorizing(self) -> None:
        exact = contracts.validate_exact_resource(
            self.catalog,
            tier="simple",
            cores=8,
            memory_gb=12,
            walltime_seconds=3600,
        )
        self.assertEqual(exact["walltime_seconds"], 3600)
        custom = contracts.build_resource_proposal(
            self.catalog,
            tier="custom_reviewed",
            cores=10,
            memory_gb=20,
            walltime_seconds=1800,
        )
        self.assertTrue(custom["proposal_only"])
        self.assertFalse(custom["calculation_ready"])
        self.assertTrue(custom["no_submission_authorization"])
        for values in (
            {"tier": "simple", "cores": 9, "memory_gb": 12, "walltime_seconds": 1},
            {"tier": "custom_reviewed", "cores": 45, "memory_gb": 10, "walltime_seconds": 1},
            {"tier": "custom_reviewed", "cores": 1, "memory_gb": 121, "walltime_seconds": 1},
            {"tier": "custom_reviewed", "cores": True, "memory_gb": 1, "walltime_seconds": 1},
            {"tier": "unknown", "cores": 1, "memory_gb": 1, "walltime_seconds": 1},
        ):
            with self.subTest(values=values):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_exact_resource(self.catalog, **values)

    def test_catalog_schema_is_closed_and_packaged_from_one_owner(self) -> None:
        schema_path = ROOT / "contracts" / "execution" / "resource-catalog.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        def inspect(node: object) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object" and "properties" in node:
                    self.assertFalse(node.get("additionalProperties", True))
                    self.assertEqual(set(node.get("required", [])), set(node["properties"]))
                for value in node.values():
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)

        inspect(schema)
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("contracts/execution/resource-catalog.schema.json")],
            schema_path,
        )
        self.assertEqual(
            package[Path("scripts/platform_contracts.py")],
            ROOT / "scripts" / "platform_contracts.py",
        )
        self.assertFalse((ROOT / "skills" / "auto-g16-rtwin-pbs" / "contracts").exists())
        self.assertFalse((ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "platform_contracts.py").exists())

    def test_catalog_is_deterministic_from_a_git_free_second_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for source in (
                ROOT / "scripts" / "platform_contracts.py",
                ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "resource_efficiency.py",
                ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "execution_batch.py",
            ):
                shutil.copyfile(source, root / source.name)
            spec = importlib.util.spec_from_file_location("second_tree_platform_contracts", root / "platform_contracts.py")
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader if spec else None)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            second = module.build_resource_catalog()
            self.assertEqual(contracts.canonical_bytes(second), contracts.canonical_bytes(self.catalog))


class IdentityBindingAndProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = legacy_binding()
        self.profile = contracts.build_execution_profile(
            profile_id="profile-placeholder",
            backend_kind="legacy_rtwin_pbs",
            transport_config_ref="/opt/auto-g16/config/placeholder-ssh-config",
            identity_binding=self.binding,
        )

    def test_config_source_bundle_framing_is_ordered_and_unambiguous(self) -> None:
        self.assertNotEqual(
            contracts.config_source_bundle_sha256([b"a", b"bc"]),
            contracts.config_source_bundle_sha256([b"ab", b"c"]),
        )
        self.assertNotEqual(
            contracts.config_source_bundle_sha256([b"first", b"second"]),
            contracts.config_source_bundle_sha256([b"second", b"first"]),
        )
        self.assertEqual(
            contracts.config_source_bundle_sha256([b"first", b"second"]),
            contracts.config_source_bundle_sha256([b"first", b"second"]),
        )
        with self.assertRaises(contracts.PlatformContractError):
            contracts.config_source_bundle_sha256([])
        with self.assertRaises(contracts.PlatformContractError):
            contracts.config_source_bundle_sha256([b"ok", "not-bytes"])
        with self.assertRaises(contracts.PlatformContractError):
            contracts.config_source_bundle_sha256([b""] * (contracts.MAX_CONFIG_SOURCES + 1))
        with self.assertRaises(contracts.PlatformContractError):
            contracts.config_source_bundle_sha256([b"x" * (contracts.MAX_CONFIG_SOURCE_BUNDLE_BYTES + 1)])

    def test_binding_contains_only_ordered_digest_hops_and_rejects_type_forgery(self) -> None:
        serialized = contracts.canonical_bytes(self.binding).decode("utf-8")
        for forbidden in (
            "placeholder.example",
            "192.0.2.10",
            "placeholder-user",
            "2222",
            "/opt/ssh/config",
            "IdentityFile",
            "SHA256:fingerprint",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            [item["transport_kind"] for item in self.binding["hops"]],
            ["legacy_rtwin_first_hop", "legacy_rtwin_nested_hop"],
        )
        raw = copy.deepcopy(self.binding)
        raw["hops"][0]["host"] = "placeholder.example"
        raw = contracts.finalize(raw, "binding_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_transport_identity_binding(raw)
        bool_digest = copy.deepcopy(self.binding)
        bool_digest["hops"][0]["alias_utf8_sha256"] = True
        bool_digest = contracts.finalize(bool_digest, "binding_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_transport_identity_binding(bool_digest)
        zero_digest = copy.deepcopy(self.binding)
        zero_digest["hops"][0]["alias_utf8_sha256"] = "0" * 64
        zero_digest = contracts.finalize(zero_digest, "binding_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_transport_identity_binding(zero_digest)

    def test_binding_rejects_hop_reorder_combination_and_self_hash_forgery(self) -> None:
        reversed_binding = copy.deepcopy(self.binding)
        reversed_binding["hops"].reverse()
        reversed_binding = contracts.finalize(reversed_binding, "binding_payload_sha256")
        with self.assertRaisesRegex(contracts.PlatformContractError, "order"):
            contracts.validate_transport_identity_binding(reversed_binding)
        direct_plus_nested = copy.deepcopy(self.binding)
        direct_plus_nested["hops"][0]["transport_kind"] = "direct_ssh"
        direct_plus_nested = contracts.finalize(direct_plus_nested, "binding_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_transport_identity_binding(direct_plus_nested)
        forged = copy.deepcopy(self.binding)
        forged["binding_payload_sha256"] = "0" * 64
        with self.assertRaisesRegex(contracts.PlatformContractError, "zero sentinel|mismatch"):
            contracts.validate_transport_identity_binding(forged)

    def test_binding_schema_exact_topology_matches_owner_case_set(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "execution" / "transport-identity-binding.schema.json").read_text(
                encoding="utf-8"
            )
        )
        topology = schema["properties"]["hops"]
        self.assertEqual(set(topology), {"oneOf"})
        branches = topology["oneOf"]
        self.assertEqual(len(branches), 2)
        expected_branches = (
            (1, ("direct_ssh",), ("#/$defs/direct_hop",)),
            (
                2,
                ("legacy_rtwin_first_hop", "legacy_rtwin_nested_hop"),
                ("#/$defs/legacy_first_hop", "#/$defs/legacy_nested_hop"),
            ),
        )
        schema_shapes: set[tuple[str, ...]] = set()
        for branch, (length, kinds, references) in zip(branches, expected_branches, strict=True):
            self.assertEqual(branch["type"], "array")
            self.assertIs(branch["items"], False)
            self.assertEqual(branch["minItems"], length)
            self.assertEqual(branch["maxItems"], length)
            self.assertEqual(tuple(item["$ref"] for item in branch["prefixItems"]), references)
            actual_kinds = tuple(
                schema["$defs"][reference.rsplit("/", 1)[-1]]["properties"]["transport_kind"]["const"]
                for reference in references
            )
            self.assertEqual(actual_kinds, kinds)
            schema_shapes.add(actual_kinds)
        self.assertEqual(schema_shapes, {
            ("direct_ssh",),
            ("legacy_rtwin_first_hop", "legacy_rtwin_nested_hop"),
        })

        direct = contracts.build_transport_identity_binding(
            binding_id="direct-binding",
            profile_id="direct-profile",
            hops=[hop("direct_ssh", "direct")],
        )
        for accepted in (direct, self.binding):
            kinds = tuple(item["transport_kind"] for item in accepted["hops"])
            with self.subTest(accepted=kinds):
                self.assertIn(kinds, schema_shapes)
                self.assertEqual(contracts.validate_transport_identity_binding(accepted), accepted)

        rejected_hops = (
            [hop("direct_ssh", "first"), hop("direct_ssh", "second")],
            [hop("legacy_rtwin_first_hop", "first")],
            [hop("legacy_rtwin_nested_hop", "nested"), hop("legacy_rtwin_first_hop", "first")],
            [hop("legacy_rtwin_nested_hop", "first"), hop("legacy_rtwin_nested_hop", "second")],
            [
                hop("legacy_rtwin_first_hop", "first"),
                hop("legacy_rtwin_nested_hop", "nested"),
                hop("legacy_rtwin_nested_hop", "extra"),
            ],
        )
        for hops in rejected_hops:
            kinds = tuple(item["transport_kind"] for item in hops)
            document = contracts.finalize({
                "schema": contracts.BINDING_SCHEMA,
                "binding_id": "binding-placeholder",
                "profile_id": "profile-placeholder",
                "hops": hops,
                "binding_payload_sha256": "",
            }, "binding_payload_sha256")
            with self.subTest(rejected=kinds):
                self.assertNotIn(kinds, schema_shapes)
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_transport_identity_binding(document)

    def test_profile_binds_complete_catalog_identity_and_fixed_sdl_policy(self) -> None:
        self.assertEqual(
            self.profile["transport_identity_binding_sha256"],
            self.binding["binding_payload_sha256"],
        )
        self.assertEqual(self.profile["workspace_policy"]["allowed_root"], "/home/user100/SDL")
        self.assertEqual(
            self.profile["profile_payload_sha256"],
            contracts.payload_sha256(self.profile, "profile_payload_sha256"),
        )
        changed_catalog = copy.deepcopy(self.profile)
        changed_catalog["resource_catalog"]["reviewed_tuples"][0]["cores"] = 7
        changed_catalog["resource_catalog"] = contracts.finalize(
            changed_catalog["resource_catalog"], "catalog_payload_sha256"
        )
        changed_catalog = contracts.finalize(changed_catalog, "profile_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_execution_profile(changed_catalog)

    def test_profile_rejects_unsupported_backend_root_and_sensitive_or_unsafe_refs(self) -> None:
        for backend in ("local_gaussian", "slurm", "mcp", "unknown"):
            with self.subTest(backend=backend):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.build_execution_profile(
                        profile_id="profile-placeholder",
                        backend_kind=backend,
                        transport_config_ref="/opt/auto-g16/config/placeholder-ssh-config",
                        identity_binding=self.binding,
                    )
        for reference in (
            "relative/config",
            "/opt/../etc/config",
            "/home/placeholder/.ssh/config",
            "/opt/auto-g16/id_rsa",
            "/opt/auto-g16/private.pem",
            "/",
        ):
            with self.subTest(reference=reference):
                changed = copy.deepcopy(self.profile)
                changed["transport_config_ref"] = reference
                changed = contracts.finalize(changed, "profile_payload_sha256")
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_execution_profile(changed)
        changed_root = copy.deepcopy(self.profile)
        changed_root["workspace_policy"]["allowed_root"] = "/srv/other"
        changed_root = contracts.finalize(changed_root, "profile_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_execution_profile(changed_root)
        blank = copy.deepcopy(self.profile)
        blank["profile_id"] = ""
        blank = contracts.finalize(blank, "profile_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_execution_profile(blank)
        forged = copy.deepcopy(self.profile)
        forged["profile_payload_sha256"] = "0" * 64
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_execution_profile(forged)

    def test_profile_backend_must_match_hop_shape(self) -> None:
        with self.assertRaises(contracts.PlatformContractError):
            contracts.build_execution_profile(
                profile_id="profile-placeholder",
                backend_kind="direct_ssh_pbs",
                transport_config_ref="/opt/auto-g16/config/placeholder-ssh-config",
                identity_binding=self.binding,
            )
        direct = contracts.build_transport_identity_binding(
            binding_id="direct-binding",
            profile_id="direct-profile",
            hops=[hop("direct_ssh", "direct")],
        )
        profile = contracts.build_execution_profile(
            profile_id="direct-profile",
            backend_kind="direct_ssh_pbs",
            transport_config_ref="/opt/auto-g16/config/direct-placeholder",
            identity_binding=direct,
        )
        self.assertEqual(profile["backend_kind"], "direct_ssh_pbs")

    def test_profile_rejects_existing_symlink_transport_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target-config"
            target.write_text("placeholder only\n", encoding="utf-8")
            linked = root / "linked-config"
            try:
                linked.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            changed = copy.deepcopy(self.profile)
            changed["transport_config_ref"] = str(linked)
            changed = contracts.finalize(changed, "profile_payload_sha256")
            with self.assertRaisesRegex(contracts.PlatformContractError, "symlink"):
                contracts.validate_execution_profile(changed)


class AttestationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = legacy_binding()
        self.profile = contracts.build_execution_profile(
            profile_id="profile-placeholder",
            backend_kind="legacy_rtwin_pbs",
            transport_config_ref="/opt/auto-g16/config/placeholder-ssh-config",
            identity_binding=self.binding,
        )
        self.first_request = contracts.build_first_hop_request(
            profile_sha256=self.profile["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            request_nonce="1" * 32,
            issued_at="2030-01-01T12:00:00Z",
            expires_at="2030-01-01T12:05:00Z",
        )
        self.first_receipt = contracts.build_first_hop_receipt(
            request=self.first_request,
            binding=self.binding,
            observed_fingerprint_evidence_sha256=digest("observed-first-hop-fingerprint"),
        )
        self.nested_request = contracts.build_nested_hop_request(
            profile_sha256=self.profile["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            first_hop_receipt_sha256=self.first_receipt["receipt_payload_sha256"],
            request_nonce="2" * 32,
            issued_at="2030-01-01T12:01:00Z",
            expires_at="2030-01-01T12:04:00Z",
        )
        self.nested_receipt = contracts.build_nested_hop_receipt(
            request=self.nested_request,
            binding=self.binding,
            first_hop_receipt=self.first_receipt,
            first_hop_request=self.first_request,
        )

    def test_typed_receipts_bind_profile_hops_nonce_time_and_first_receipt(self) -> None:
        first = contracts.validate_first_hop_receipt(
            self.first_receipt,
            request=self.first_request,
            binding=self.binding,
            now="2030-01-01T12:02:00Z",
        )
        nested = contracts.validate_nested_hop_receipt(
            self.nested_receipt,
            request=self.nested_request,
            binding=self.binding,
            first_hop_receipt=first,
            first_hop_request=self.first_request,
            now="2030-01-01T12:02:00Z",
        )
        self.assertEqual(nested["first_hop_receipt_sha256"], first["receipt_payload_sha256"])
        self.assertEqual(nested["classification"], "verified")
        self.assertTrue(nested["read_only_attestation"])
        self.assertFalse(nested["automatic_retry"])
        self.assertTrue(nested["no_execution_authorization"])

    def test_first_hop_unknown_partial_expired_and_mismatch_fail_closed(self) -> None:
        mutations = {
            "classification": "partial",
            "profile_sha256": digest("wrong-profile"),
            "transport_identity_binding_sha256": digest("wrong-binding"),
            "config_source_bundle_sha256": digest("wrong-config"),
            "alias_utf8_sha256": digest("wrong-alias"),
            "effective_target_identity_sha256": digest("wrong-target"),
            "host_key_evidence_sha256": digest("wrong-host-key"),
            "request_nonce": "3" * 32,
            "operation_version": "first-hop-identity-attestation/2",
            "read_only_attestation": False,
            "automatic_retry": True,
            "no_execution_authorization": False,
        }
        for field, value in mutations.items():
            changed = copy.deepcopy(self.first_receipt)
            changed[field] = value
            changed = contracts.finalize(changed, "receipt_payload_sha256")
            with self.subTest(field=field):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_first_hop_receipt(
                        changed,
                        request=self.first_request,
                        binding=self.binding,
                        now="2030-01-01T12:02:00Z",
                    )
        with self.assertRaisesRegex(contracts.PlatformContractError, "not currently valid"):
            contracts.validate_first_hop_receipt(
                self.first_receipt,
                request=self.first_request,
                binding=self.binding,
                now="2030-01-01T12:05:00Z",
            )
        forged = copy.deepcopy(self.first_receipt)
        forged["receipt_payload_sha256"] = "0" * 64
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_first_hop_receipt(
                forged,
                request=self.first_request,
                binding=self.binding,
                now="2030-01-01T12:02:00Z",
            )

    def test_nested_unknown_partial_nonce_profile_first_hop_and_version_fail_closed(self) -> None:
        mutations = {
            "classification": "unknown",
            "profile_sha256": digest("wrong-profile"),
            "transport_identity_binding_sha256": digest("wrong-binding"),
            "first_hop_identity_sha256": digest("wrong-first-hop"),
            "first_hop_receipt_sha256": digest("wrong-first-receipt"),
            "config_source_bundle_sha256": digest("wrong-config"),
            "request_nonce": "4" * 32,
            "operation_version": "nested-hop-identity-attestation/2",
            "read_only_attestation": False,
            "automatic_retry": True,
            "no_execution_authorization": False,
        }
        for field, value in mutations.items():
            changed = copy.deepcopy(self.nested_receipt)
            changed[field] = value
            changed = contracts.finalize(changed, "receipt_payload_sha256")
            with self.subTest(field=field):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_nested_hop_receipt(
                        changed,
                        request=self.nested_request,
                        binding=self.binding,
                        first_hop_receipt=self.first_receipt,
                        first_hop_request=self.first_request,
                        now="2030-01-01T12:02:00Z",
                    )

    def test_receipts_reject_request_chain_mismatch_even_when_receipt_is_unchanged(self) -> None:
        wrong_first_binding = copy.deepcopy(self.first_request)
        wrong_first_binding["transport_identity_binding_sha256"] = digest("wrong-request-binding")
        with self.assertRaisesRegex(contracts.PlatformContractError, "request transport identity binding mismatch"):
            contracts.validate_first_hop_receipt(
                self.first_receipt,
                request=wrong_first_binding,
                binding=self.binding,
                now="2030-01-01T12:02:00Z",
            )

        mutations = {
            "transport_identity_binding_sha256": digest("wrong-nested-request-binding"),
            "first_hop_receipt_sha256": digest("wrong-request-first-receipt"),
            "profile_sha256": digest("wrong-request-profile"),
        }
        for field, value in mutations.items():
            changed_request = copy.deepcopy(self.nested_request)
            changed_request[field] = value
            with self.subTest(field=field):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_nested_hop_receipt(
                        self.nested_receipt,
                        request=changed_request,
                        binding=self.binding,
                        first_hop_receipt=self.first_receipt,
                        first_hop_request=self.first_request,
                        now="2030-01-01T12:02:00Z",
                    )

    def test_inverted_oversized_and_expired_request_windows_fail_closed(self) -> None:
        for issued, expires, now in (
            ("2030-01-01T12:05:00Z", "2030-01-01T12:04:00Z", "2030-01-01T12:04:00Z"),
            ("2030-01-01T12:00:00Z", "2030-01-01T12:05:01Z", "2030-01-01T12:00:00Z"),
            ("2030-01-01T12:00:00Z", "2030-01-01T12:05:00Z", "2030-01-01T12:06:00Z"),
        ):
            request = copy.deepcopy(self.first_request)
            request["issued_at"] = issued
            request["expires_at"] = expires
            with self.subTest(issued=issued, expires=expires, now=now):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_first_hop_request(request, now=now)

    def test_valid_receipt_validation_is_idempotent_but_never_authorizing(self) -> None:
        first = [
            contracts.validate_first_hop_receipt(
                self.first_receipt,
                request=self.first_request,
                binding=self.binding,
                now="2030-01-01T12:02:00Z",
            )
            for _ in range(2)
        ]
        nested = [
            contracts.validate_nested_hop_receipt(
                self.nested_receipt,
                request=self.nested_request,
                binding=self.binding,
                first_hop_receipt=self.first_receipt,
                first_hop_request=self.first_request,
                now="2030-01-01T12:02:00Z",
            )
            for _ in range(2)
        ]
        self.assertEqual(first[0], first[1])
        self.assertEqual(nested[0], nested[1])
        self.assertTrue(all(item["no_execution_authorization"] for item in first + nested))
        self.assertTrue(all(item["read_only_attestation"] for item in first + nested))

    def test_nested_receipt_binds_approved_host_key_evidence_not_an_observed_handshake(self) -> None:
        self.assertIn("observed_fingerprint_evidence_sha256", self.first_receipt)
        self.assertNotIn("observed_fingerprint_evidence_sha256", self.nested_receipt)
        self.assertEqual(
            self.nested_receipt["host_key_evidence_sha256"],
            self.binding["hops"][1]["host_key_evidence_sha256"],
        )
        self.assertTrue(self.nested_receipt["no_execution_authorization"])

    def test_attestation_requests_reject_caller_command_surfaces_and_type_forgery(self) -> None:
        for field in (
            "command", "argv", "shell", "powershell", "script", "path_fragment",
            "config_path", "known_hosts_path", "reparse_point", "retry",
        ):
            changed = copy.deepcopy(self.nested_request)
            changed[field] = "forbidden"
            with self.subTest(field=field):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_nested_hop_request(changed, now="2030-01-01T12:02:00Z")
        wrong_nonce = copy.deepcopy(self.nested_request)
        wrong_nonce["request_nonce"] = True
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_nested_hop_request(wrong_nonce, now="2030-01-01T12:02:00Z")
        retry = copy.deepcopy(self.nested_request)
        retry["automatic_retry"] = True
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_nested_hop_request(retry, now="2030-01-01T12:02:00Z")

    def test_identity_and_attestation_schemas_are_closed_and_packaged(self) -> None:
        paths = (
            "execution-profile.schema.json",
            "transport-identity-binding.schema.json",
            "transport-identity-attestation-request.schema.json",
            "transport-identity-attestation-receipt.schema.json",
        )
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        for name in paths:
            with self.subTest(name=name):
                path = ROOT / "contracts" / "execution" / name
                schema = json.loads(path.read_text(encoding="utf-8"))

                def inspect(node: object) -> None:
                    if isinstance(node, dict):
                        if node.get("type") == "object" and "properties" in node:
                            self.assertFalse(node.get("additionalProperties", True))
                            self.assertEqual(set(node.get("required", [])), set(node["properties"]))
                        for value in node.values():
                            inspect(value)
                    elif isinstance(node, list):
                        for value in node:
                            inspect(value)

                inspect(schema)
                self.assertEqual(package[Path("contracts/execution") / name], path)

    def test_all_seven_schema_documents_and_owner_accept_reject_samples_are_aligned(self) -> None:
        schema_root = ROOT / "contracts" / "execution"
        schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(schema_root.glob("*.schema.json"))
        }
        self.assertEqual(set(schemas), {
            "capability-report.schema.json",
            "execution-profile.schema.json",
            "legacy-runtime-mapping-result.schema.json",
            "resource-catalog.schema.json",
            "transport-identity-attestation-receipt.schema.json",
            "transport-identity-attestation-request.schema.json",
            "transport-identity-binding.schema.json",
        })
        for name, schema in schemas.items():
            with self.subTest(schema=name):
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            schemas["resource-catalog.schema.json"]["properties"]["catalog_id"]["const"],
            contracts.CATALOG_ID,
        )
        self.assertEqual(
            set(schemas["execution-profile.schema.json"]["properties"]["backend_kind"]["enum"]),
            contracts.BACKENDS,
        )
        request_defs = schemas["transport-identity-attestation-request.schema.json"]["$defs"]
        for name in ("first_hop_request", "nested_hop_request"):
            self.assertIs(request_defs[name]["properties"]["automatic_retry"]["const"], False)
        receipt_defs = schemas["transport-identity-attestation-receipt.schema.json"]["$defs"]
        for name in ("first_hop_receipt", "nested_hop_receipt"):
            self.assertEqual(receipt_defs[name]["properties"]["classification"]["const"], "verified")
            self.assertIs(receipt_defs[name]["properties"]["no_execution_authorization"]["const"], True)
        self.assertIs(
            schemas["capability-report.schema.json"]["properties"]["offline_only"]["const"],
            True,
        )
        self.assertIs(
            schemas["legacy-runtime-mapping-result.schema.json"]["properties"]["migration_performed"]["const"],
            False,
        )

        catalog = contracts.build_resource_catalog()
        report = contracts.build_capability_report(self.profile)
        mapping = contracts.map_legacy_runtime({
            "rtwin_ssh_config": "/opt/placeholder/config/rtwin-ssh-config",
            "windows_project_root": "C:\\Placeholder\\Projects",
            "windows_server_config": "C:\\Placeholder\\server-ssh-config",
        })
        direct = contracts.build_transport_identity_binding(
            binding_id="direct-binding",
            profile_id="direct-profile",
            hops=[hop("direct_ssh", "direct")],
        )
        contracts.validate_resource_catalog(catalog)
        contracts.validate_transport_identity_binding(direct)
        contracts.validate_transport_identity_binding(self.binding)
        contracts.validate_execution_profile(self.profile)
        contracts.validate_first_hop_request(self.first_request, now="2030-01-01T12:02:00Z")
        contracts.validate_nested_hop_request(self.nested_request, now="2030-01-01T12:02:00Z")
        contracts.validate_first_hop_receipt(
            self.first_receipt,
            request=self.first_request,
            binding=self.binding,
            now="2030-01-01T12:02:00Z",
        )
        contracts.validate_nested_hop_receipt(
            self.nested_receipt,
            request=self.nested_request,
            binding=self.binding,
            first_hop_receipt=self.first_receipt,
            first_hop_request=self.first_request,
            now="2030-01-01T12:02:00Z",
        )
        contracts.validate_capability_report(report)
        contracts.validate_legacy_mapping_result(mapping)

        invalid_catalog = copy.deepcopy(catalog)
        invalid_catalog["catalog_id"] = "unreviewed-catalog"
        invalid_binding = copy.deepcopy(direct)
        invalid_binding["hops"].append(hop("direct_ssh", "second-direct"))
        invalid_binding = contracts.finalize(invalid_binding, "binding_payload_sha256")
        invalid_profile = copy.deepcopy(self.profile)
        invalid_profile["backend_kind"] = "slurm"
        invalid_request = copy.deepcopy(self.first_request)
        invalid_request["automatic_retry"] = True
        invalid_receipt = copy.deepcopy(self.first_receipt)
        invalid_receipt["classification"] = "unknown"
        invalid_receipt = contracts.finalize(invalid_receipt, "receipt_payload_sha256")
        invalid_report = copy.deepcopy(report)
        invalid_report["offline_only"] = False
        invalid_report = contracts.finalize(invalid_report, "report_payload_sha256")
        invalid_mapping = copy.deepcopy(mapping)
        invalid_mapping["migration_performed"] = True
        invalid_mapping = contracts.finalize(invalid_mapping, "mapping_payload_sha256")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_resource_catalog(invalid_catalog)
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_transport_identity_binding(invalid_binding)
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_execution_profile(invalid_profile)
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_first_hop_request(invalid_request, now="2030-01-01T12:02:00Z")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_first_hop_receipt(
                invalid_receipt,
                request=self.first_request,
                binding=self.binding,
                now="2030-01-01T12:02:00Z",
            )
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_capability_report(invalid_report)
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_legacy_mapping_result(invalid_mapping)


class CapabilityAndLegacyMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = {
            "core_python": "/opt/placeholder/core-python",
            "rdkit_python": "/opt/placeholder/chem-python",
            "chemdraw_pipeline_scripts": "/opt/placeholder/pipeline",
            "rtwin_ssh_config": "/opt/placeholder/config/rtwin-ssh-config",
            "windows_target": "placeholder-windows-target",
            "windows_control_socket": "/opt/placeholder/control.sock",
            "windows_project_root": "C:\\Placeholder\\Projects",
            "windows_server_config": "C:\\Placeholder\\server-ssh-config",
            "gaussview_exe": "C:\\Placeholder\\GaussView.exe",
        }
        self.mapping = contracts.map_legacy_runtime(self.runtime)
        profile_id = self.mapping["derived_profile_summary"]["profile_id"]
        self.binding = legacy_binding(profile_id)
        self.profile = contracts.derive_legacy_profile(self.runtime, self.binding)

    def test_capability_is_sanitized_offline_configured_expressibility_only(self) -> None:
        report = contracts.build_capability_report(self.profile)
        self.assertTrue(report["offline_only"])
        self.assertEqual(report["unsupported_backends"], ["local_gaussian", "slurm", "mcp"])
        self.assertIn("network_reachability", report["unknown_live_properties"])
        self.assertIn("license_validity", report["unknown_live_properties"])
        self.assertIn("gaussian_availability", report["unknown_live_properties"])
        self.assertIn("live_authority", report["unknown_live_properties"])
        self.assertTrue(all(
            item["status"] == "configured_expressible_unverified"
            for item in report["configured_typed_operations"]
        ))
        serialized = contracts.canonical_bytes(report).decode("utf-8")
        for value in self.runtime.values():
            self.assertNotIn(value, serialized)
        for forbidden in ("placeholder.example", "192.0.2.20", "placeholder-user", "SHA256:fingerprint"):
            self.assertNotIn(forbidden, serialized)

    def test_capability_rejects_overclaim_unsupported_fallback_and_self_hash_forgery(self) -> None:
        report = contracts.build_capability_report(self.profile)
        cases = []
        live = copy.deepcopy(report)
        live["configured_typed_operations"][0]["status"] = "reachable"
        cases.append(contracts.finalize(live, "report_payload_sha256"))
        online = copy.deepcopy(report)
        online["offline_only"] = False
        cases.append(contracts.finalize(online, "report_payload_sha256"))
        fallback = copy.deepcopy(report)
        fallback["unsupported_backends"].remove("slurm")
        cases.append(contracts.finalize(fallback, "report_payload_sha256"))
        forged = copy.deepcopy(report)
        forged["report_payload_sha256"] = "0" * 64
        cases.append(forged)
        leak = copy.deepcopy(report)
        leak["hostname"] = "placeholder.example"
        cases.append(contracts.finalize(leak, "report_payload_sha256"))
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.validate_capability_report(case)

    def test_legacy_mapping_is_deterministic_redacted_and_non_authorizing(self) -> None:
        reordered = dict(reversed(list(self.runtime.items())))
        second = contracts.map_legacy_runtime(reordered)
        self.assertEqual(contracts.canonical_bytes(self.mapping), contracts.canonical_bytes(second))
        self.assertTrue(self.mapping["live_attestation_required"])
        self.assertFalse(self.mapping["migration_performed"])
        self.assertFalse(self.mapping["legacy_approval_authorizes_profile_mode"])
        self.assertFalse(self.mapping["legacy_approval_authorizes_direct"])
        self.assertIsNone(self.mapping["derived_profile_summary"]["profile_payload_sha256"])
        serialized = contracts.canonical_bytes(self.mapping).decode("utf-8")
        for value in self.runtime.values():
            self.assertNotIn(value, serialized)
        forged = copy.deepcopy(self.mapping)
        forged["mapping_payload_sha256"] = "0" * 64
        with self.assertRaises(contracts.PlatformContractError):
            contracts.validate_legacy_mapping_result(forged)

    def test_legacy_conflicts_report_only_field_names_and_never_silently_migrate(self) -> None:
        result = contracts.map_legacy_runtime(
            self.runtime,
            legacy_cli_values={
                "mac_ssh_config": "/opt/placeholder/conflicting-config",
                "windows_root": "D:\\Placeholder\\Other",
                "windows_server_config": "D:\\Placeholder\\other-server-config",
            },
        )
        self.assertEqual(
            [item["field"] for item in result["conflicts"]],
            ["rtwin_ssh_config", "windows_project_root", "windows_server_config"],
        )
        self.assertEqual(result["derived_profile_summary"]["profile_status"], "conflict")
        serialized = contracts.canonical_bytes(result).decode("utf-8")
        self.assertNotIn("conflicting-config", serialized)
        self.assertNotIn("Placeholder\\Other", serialized)
        direct_binding = contracts.build_transport_identity_binding(
            binding_id="direct-binding",
            profile_id="direct-profile",
            hops=[hop("direct_ssh", "direct")],
        )
        direct_profile = contracts.build_execution_profile(
            profile_id="direct-profile",
            backend_kind="direct_ssh_pbs",
            transport_config_ref="/opt/placeholder/config/direct",
            identity_binding=direct_binding,
        )
        conflict = contracts.map_legacy_runtime(self.runtime, explicit_profile=direct_profile)
        self.assertIn("backend_kind", [item["field"] for item in conflict["conflicts"]])

    def test_legacy_runtime_is_read_by_the_unchanged_owner_and_derived_profile_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "runtime.json"
            path.write_bytes(contracts.canonical_bytes(self.runtime))
            loaded = contracts.load_legacy_runtime_exact(path)
            self.assertEqual(loaded, self.runtime)
            profile = contracts.derive_legacy_profile(loaded, self.binding)
            self.assertEqual(profile["backend_kind"], "legacy_rtwin_pbs")
            self.assertEqual(profile["transport_config_ref"], self.runtime["rtwin_ssh_config"])
            self.assertEqual(profile["workspace_policy"]["allowed_root"], "/home/user100/SDL")
        invalid = copy.deepcopy(self.runtime)
        invalid["rtwin_ssh_config"] = "relative/config"
        with self.assertRaises(ValueError):
            contracts.map_legacy_runtime(invalid)

    def test_capability_and_mapping_schemas_are_closed_and_packaged(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("scripts/platform_runtime_config_owner.py")],
            ROOT / "scripts" / "runtime_config.py",
        )
        for name in ("capability-report.schema.json", "legacy-runtime-mapping-result.schema.json"):
            with self.subTest(name=name):
                path = ROOT / "contracts" / "execution" / name
                schema = json.loads(path.read_text(encoding="utf-8"))

                def inspect(node: object) -> None:
                    if isinstance(node, dict):
                        if node.get("type") == "object" and "properties" in node:
                            self.assertFalse(node.get("additionalProperties", True))
                            self.assertEqual(set(node.get("required", [])), set(node["properties"]))
                        for value in node.values():
                            inspect(value)
                    elif isinstance(node, list):
                        for value in node:
                            inspect(value)

                inspect(schema)
                self.assertEqual(package[Path("contracts/execution") / name], path)

    def test_git_free_packaged_owner_is_deterministic_for_profile_mapping_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary).resolve() / "auto-g16-rtwin-pbs"
            package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
            for target, source in package.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            self.assertFalse((installed / ".git").exists())
            script = installed / "scripts" / "platform_contracts.py"
            spec = importlib.util.spec_from_file_location("packaged_platform_contracts", script)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader if spec else None)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            packaged_mapping = module.map_legacy_runtime(self.runtime)
            self.assertEqual(
                contracts.canonical_bytes(packaged_mapping),
                contracts.canonical_bytes(self.mapping),
            )
            profile_id = packaged_mapping["derived_profile_summary"]["profile_id"]
            packaged_binding = module.build_transport_identity_binding(
                binding_id="binding-placeholder",
                profile_id=profile_id,
                hops=[
                    hop("legacy_rtwin_first_hop", "first"),
                    hop("legacy_rtwin_nested_hop", "nested"),
                ],
            )
            packaged_profile = module.derive_legacy_profile(self.runtime, packaged_binding)
            packaged_report = module.build_capability_report(packaged_profile)
            local_report = contracts.build_capability_report(self.profile)
            self.assertEqual(
                contracts.canonical_bytes(packaged_profile),
                contracts.canonical_bytes(self.profile),
            )
            self.assertEqual(
                contracts.canonical_bytes(packaged_report),
                contracts.canonical_bytes(local_report),
            )
            runtime_path = Path(temporary).resolve() / "runtime.json"
            runtime_path.write_bytes(contracts.canonical_bytes(self.runtime))
            self.assertEqual(module.load_legacy_runtime_exact(runtime_path), self.runtime)


class OfflineCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.runtime = {
            "rtwin_ssh_config": "/opt/placeholder/config/rtwin-ssh-config",
            "windows_project_root": "C:\\Placeholder\\Projects",
            "windows_server_config": "C:\\Placeholder\\server-ssh-config",
        }
        self.runtime_path = self.root / "runtime.json"
        self.runtime_path.write_bytes(contracts.canonical_bytes(self.runtime))
        mapping = contracts.map_legacy_runtime(self.runtime)
        profile_id = mapping["derived_profile_summary"]["profile_id"]
        self.binding = legacy_binding(profile_id)
        self.binding_path = self.root / "binding.json"
        self.binding_path.write_bytes(contracts.canonical_bytes(self.binding))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, argv: list[str]) -> tuple[int, dict[str, object] | None, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = contracts.main(argv)
        document = json.loads(output.getvalue()) if output.getvalue() else None
        return result, document, errors.getvalue()

    def test_doctor_legacy_is_read_only_redacted_and_requires_live_attestation(self) -> None:
        before = self.runtime_path.read_bytes()
        result, document, errors = self.run_cli([
            "doctor", "--legacy-runtime", str(self.runtime_path),
        ])
        self.assertEqual(result, 0, errors)
        assert document is not None
        self.assertEqual(document["status"], "live_attestation_required")
        self.assertTrue(document["offline_only"])
        self.assertFalse(document["live_authority"])
        self.assertEqual(self.runtime_path.read_bytes(), before)
        serialized = json.dumps(document, sort_keys=True)
        for value in self.runtime.values():
            self.assertNotIn(value, serialized)

    def test_init_dry_run_is_read_only_and_real_init_is_private_atomic_no_clobber(self) -> None:
        output = self.root / "profiles" / "profile.json"
        output.parent.mkdir(mode=0o700)
        common = [
            "init",
            "--output", str(output),
            "--profile-id", self.binding["profile_id"],
            "--backend-kind", "legacy_rtwin_pbs",
            "--transport-config-ref", self.runtime["rtwin_ssh_config"],
            "--identity-binding", str(self.binding_path),
        ]
        result, dry, errors = self.run_cli([*common, "--dry-run"])
        self.assertEqual(result, 0, errors)
        assert dry is not None
        self.assertFalse(dry["written"])
        self.assertEqual(dry["path"], str(output))
        self.assertFalse(output.exists())
        result, applied, errors = self.run_cli(common)
        self.assertEqual(result, 0, errors)
        assert applied is not None
        self.assertTrue(applied["written"])
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        profile = contracts.load_execution_profile(output)
        self.assertEqual(profile["profile_payload_sha256"], applied["payload_sha256"])
        original = output.read_bytes()
        result, _, errors = self.run_cli(common)
        self.assertEqual(result, 2)
        self.assertIn("refuses to overwrite", errors)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(list(output.parent.glob(".profile.json.tmp.*")), [])
        result, _, errors = self.run_cli([
            "init",
            "--output", "relative-profile.json",
            "--profile-id", self.binding["profile_id"],
            "--backend-kind", "legacy_rtwin_pbs",
            "--transport-config-ref", self.runtime["rtwin_ssh_config"],
            "--identity-binding", str(self.binding_path),
        ])
        self.assertEqual(result, 2)
        self.assertIn("explicit absolute path", errors)

    def test_validate_and_doctor_profile_never_emit_private_transport_reference(self) -> None:
        profile = contracts.derive_legacy_profile(self.runtime, self.binding)
        profile_path = self.root / "profile.json"
        profile_path.write_bytes(contracts.canonical_bytes(profile))
        result, validated, errors = self.run_cli(["validate", "profile", str(profile_path)])
        self.assertEqual(result, 0, errors)
        assert validated is not None
        self.assertNotIn(self.runtime["rtwin_ssh_config"], json.dumps(validated))
        result, doctor, errors = self.run_cli(["doctor", "--profile", str(profile_path)])
        self.assertEqual(result, 0, errors)
        assert doctor is not None
        self.assertNotIn(self.runtime["rtwin_ssh_config"], json.dumps(doctor))
        self.assertEqual(doctor["status"], "configured_expressibility_only")
        self.assertTrue(doctor["live_attestation_required"])

    def test_doctor_reports_profile_legacy_conflict_without_values_or_fallback(self) -> None:
        profile = contracts.derive_legacy_profile(self.runtime, self.binding)
        profile["transport_config_ref"] = "/opt/placeholder/config/different-ref"
        profile = contracts.finalize(profile, "profile_payload_sha256")
        profile_path = self.root / "conflicting-profile.json"
        profile_path.write_bytes(contracts.canonical_bytes(profile))
        result, doctor, errors = self.run_cli([
            "doctor",
            "--profile", str(profile_path),
            "--legacy-runtime", str(self.runtime_path),
        ])
        self.assertEqual(result, 0, errors)
        assert doctor is not None
        self.assertEqual(doctor["status"], "conflict")
        conflicts = doctor["legacy_mapping"]["conflicts"]
        self.assertEqual(conflicts, [{
            "field": "rtwin_ssh_config",
            "classification": "execution_relevant_value_conflict",
        }])
        serialized = json.dumps(doctor, sort_keys=True)
        self.assertNotIn(self.runtime["rtwin_ssh_config"], serialized)
        self.assertNotIn("different-ref", serialized)

    def test_validate_cli_cross_checks_first_and_nested_receipts(self) -> None:
        profile = contracts.derive_legacy_profile(self.runtime, self.binding)
        first_request = contracts.build_first_hop_request(
            profile_sha256=profile["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            request_nonce="5" * 32,
            issued_at="2030-01-01T12:00:00Z",
            expires_at="2030-01-01T12:05:00Z",
        )
        first_receipt = contracts.build_first_hop_receipt(
            request=first_request,
            binding=self.binding,
            observed_fingerprint_evidence_sha256=digest("cli-observed-first"),
        )
        nested_request = contracts.build_nested_hop_request(
            profile_sha256=profile["profile_payload_sha256"],
            binding_sha256=self.binding["binding_payload_sha256"],
            first_hop_receipt_sha256=first_receipt["receipt_payload_sha256"],
            request_nonce="6" * 32,
            issued_at="2030-01-01T12:01:00Z",
            expires_at="2030-01-01T12:04:00Z",
        )
        nested_receipt = contracts.build_nested_hop_receipt(
            request=nested_request,
            binding=self.binding,
            first_hop_receipt=first_receipt,
            first_hop_request=first_request,
        )
        paths: dict[str, Path] = {}
        for name, document in (
            ("first-request", first_request),
            ("first-receipt", first_receipt),
            ("nested-request", nested_request),
            ("nested-receipt", nested_receipt),
        ):
            paths[name] = self.root / f"{name}.json"
            paths[name].write_bytes(contracts.canonical_bytes(document))
        result, summary, errors = self.run_cli([
            "validate", "first-hop-receipt", str(paths["first-receipt"]),
            "--request", str(paths["first-request"]),
            "--identity-binding", str(self.binding_path),
            "--now", "2030-01-01T12:02:00Z",
        ])
        self.assertEqual(result, 0, errors)
        assert summary is not None
        self.assertEqual(summary["payload_sha256"], first_receipt["receipt_payload_sha256"])
        result, summary, errors = self.run_cli([
            "validate", "nested-hop-receipt", str(paths["nested-receipt"]),
            "--request", str(paths["nested-request"]),
            "--identity-binding", str(self.binding_path),
            "--first-hop-request", str(paths["first-request"]),
            "--first-hop-receipt", str(paths["first-receipt"]),
            "--now", "2030-01-01T12:02:00Z",
        ])
        self.assertEqual(result, 0, errors)
        assert summary is not None
        self.assertEqual(summary["payload_sha256"], nested_receipt["receipt_payload_sha256"])
        result, _, errors = self.run_cli([
            "validate", "nested-hop-receipt", str(paths["nested-receipt"]),
            "--request", str(paths["nested-request"]),
            "--identity-binding", str(self.binding_path),
            "--now", "2030-01-01T12:02:00Z",
        ])
        self.assertEqual(result, 2)
        self.assertIn("--first-hop-request", errors)

    def test_loader_and_init_reject_bom_malformed_utf8_symlink_and_traversal(self) -> None:
        invalid = self.root / "invalid.json"
        for raw in (b"\xef\xbb\xbf{}", b'{"schema":"\xff"}'):
            invalid.write_bytes(raw)
            with self.subTest(raw=raw):
                with self.assertRaises(contracts.PlatformContractError):
                    contracts.load_execution_profile(invalid)
        target = self.root / "target.json"
        target.write_bytes(contracts.canonical_bytes(contracts.derive_legacy_profile(self.runtime, self.binding)))
        linked = self.root / "linked.json"
        try:
            linked.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(contracts.PlatformContractError):
            contracts.load_execution_profile(linked)
        real_directory = self.root / "real"
        real_directory.mkdir()
        linked_directory = self.root / "linked-directory"
        linked_directory.symlink_to(real_directory, target_is_directory=True)
        result, _, errors = self.run_cli([
            "init",
            "--output", str(linked_directory / "profile.json"),
            "--profile-id", self.binding["profile_id"],
            "--backend-kind", "legacy_rtwin_pbs",
            "--transport-config-ref", self.runtime["rtwin_ssh_config"],
            "--identity-binding", str(self.binding_path),
        ])
        self.assertEqual(result, 2)
        self.assertRegex(errors, "symlink|non-directory")
        self.assertFalse((real_directory / "profile.json").exists())

    def test_loader_and_dry_run_reject_sensitive_artifact_paths_without_reading_them(self) -> None:
        sensitive = self.root / ".ssh"
        sensitive.mkdir()
        profile_path = sensitive / "profile.json"
        profile_path.write_bytes(contracts.canonical_bytes(contracts.derive_legacy_profile(self.runtime, self.binding)))
        with self.assertRaisesRegex(contracts.PlatformContractError, "sensitive credential location"):
            contracts.load_execution_profile(profile_path)
        output = sensitive / "new-profile.json"
        result, _, errors = self.run_cli([
            "init",
            "--output", str(output),
            "--profile-id", self.binding["profile_id"],
            "--backend-kind", "legacy_rtwin_pbs",
            "--transport-config-ref", self.runtime["rtwin_ssh_config"],
            "--identity-binding", str(self.binding_path),
            "--dry-run",
        ])
        self.assertEqual(result, 2)
        self.assertIn("sensitive credential location", errors)
        self.assertFalse(output.exists())

    def test_platform_owner_has_no_subprocess_socket_or_network_client_surface(self) -> None:
        source = (ROOT / "scripts" / "platform_contracts.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        self.assertTrue(imports.isdisjoint({"subprocess", "socket", "urllib", "http", "requests", "paramiko"}))
        self.assertNotIn("doctor --live-readonly", source)
        forbidden = {"command", "argv", "shell", "powershell", "script", "path_fragment", "path"}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                "attestation" in node.name or "hop_request" in node.name or "hop_receipt" in node.name
            ):
                parameters = {
                    argument.arg
                    for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                }
                self.assertTrue(parameters.isdisjoint(forbidden), node.name)


if __name__ == "__main__":
    unittest.main()
