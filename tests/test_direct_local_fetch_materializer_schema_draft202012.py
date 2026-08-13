#!/usr/bin/env python3
"""Pinned Draft 2020-12 checks for direct local fetch artifacts."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import pathlib
import sys
import tempfile
import unittest


REQUIRE_ENV = "AUTO_G16_REQUIRE_JSONSCHEMA"
EXPECTED_JSONSCHEMA_VERSION = "4.26.0"
raw_requirement = os.environ.get(REQUIRE_ENV, "")
if raw_requirement not in {"", "0", "1"}:
    raise RuntimeError(f"{REQUIRE_ENV} must be unset, 0, or 1")
REQUIRE_JSONSCHEMA = raw_requirement == "1"

try:
    import jsonschema
except ImportError as exc:
    jsonschema = None
    JSONSCHEMA_IMPORT_ERROR: Exception | None = exc
else:
    JSONSCHEMA_IMPORT_ERROR = None

installed_jsonschema = importlib.metadata.version("jsonschema") if jsonschema else None
EXACT_VALIDATOR_AVAILABLE = jsonschema is not None and installed_jsonschema == EXPECTED_JSONSCHEMA_VERSION
if REQUIRE_JSONSCHEMA and not EXACT_VALIDATOR_AVAILABLE:
    detail = f"installed jsonschema={installed_jsonschema!r}" if JSONSCHEMA_IMPORT_ERROR is None else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    raise RuntimeError(f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}")


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import direct_local_fetch_materializer as MATERIALIZER  # noqa: E402


SCHEMA_PATHS = {
    "policy": ROOT / "contracts/direct-execution/direct-local-fetch-target-policy.schema.json",
    "manifest": ROOT / "contracts/direct-execution/direct-fetch-manifest.schema.json",
}


@unittest.skipUnless(EXACT_VALIDATOR_AVAILABLE, "real Draft 2020-12 checks require jsonschema==4.26.0")
class DirectLocalFetchMaterializerSchemaDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert jsonschema is not None
        cls.schemas = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in SCHEMA_PATHS.items()}
        cls.validators = {
            name: jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
            for name, schema in cls.schemas.items()
        }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        target_root = str(pathlib.Path(self.temporary.name).resolve())
        self.policy = MATERIALIZER._build_reviewed_target_policy_for_tests(
            target_root=target_root,
            review_id="local-fetch-target-review-" + "1" * 64,
        )
        owner = MATERIALIZER._issue_offline_target_owner_for_tests(
            target_root=target_root,
            review_id="local-fetch-target-review-" + "1" * 64,
        )
        capability = owner.issue_target_once(
            project="schema_project",
            attempt_id="qsub-attempt-" + "2" * 64,
            job_id="123.master",
            w5_receipt_sha256="3" * 64,
            read_profile_sha256="4" * 64,
        )
        lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(
            capability, (b"a", b"b", b"c", b"d", b"e")
        )
        self.manifest = MATERIALIZER.materialize_direct_fetch_once(capability, lease)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def owner_validate(self, name: str, document: dict[str, object]) -> dict[str, object]:
        if name == "policy":
            return MATERIALIZER.validate_target_policy(document)
        return MATERIALIZER.validate_manifest(document)

    def rehash(self, name: str, document: dict[str, object]) -> dict[str, object]:
        changed = copy.deepcopy(document)
        field = "policy_payload_sha256" if name == "policy" else "manifest_payload_sha256"
        changed[field] = ""
        changed[field] = MATERIALIZER.digest(changed)
        return changed

    def assert_both_reject(self, name: str, document: dict[str, object]) -> None:
        assert jsonschema is not None
        with self.assertRaises(jsonschema.ValidationError):
            self.validators[name].validate(document)
        with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
            self.owner_validate(name, document)

    def test_real_draft_accepts_owner_documents(self) -> None:
        for name, document in (("policy", self.policy), ("manifest", self.manifest)):
            with self.subTest(name=name):
                self.validators[name].validate(document)
                self.assertEqual(self.owner_validate(name, document), document)

    def test_real_draft_accepts_fixed_production_target_policy_shape(self) -> None:
        production = copy.deepcopy(self.policy)
        production["authority"] = {
            "portable_policy": True,
            "authorizes_effect": False,
            "production_integration": True,
            "caller_bytes_can_issue_owner": False,
            "fixed_policy_path": str(
                MATERIALIZER.FIXED_PRODUCTION_TARGET_POLICY_PATH
            ),
            "policy_file_is_authority": False,
            "backend_owner_descriptor_issuance_required": True,
        }
        production = self.rehash("policy", production)
        self.validators["policy"].validate(production)
        self.assertEqual(MATERIALIZER.validate_target_policy(production), production)

    def test_real_draft_preserves_historical_mode_and_accepts_closed_owner_mode(self) -> None:
        historical_policy_raw = MATERIALIZER.canonical_bytes(self.policy)
        historical_policy = json.loads(historical_policy_raw.decode("utf-8"))
        self.assertEqual(
            historical_policy["authority"]["required_production_predecessor"],
            MATERIALIZER.LEGACY_PRODUCTION_TARGET_PREDECESSOR,
        )
        self.validators["policy"].validate(historical_policy)
        self.assertEqual(
            MATERIALIZER.validate_target_policy(historical_policy),
            historical_policy,
        )
        self.assertEqual(
            MATERIALIZER.canonical_bytes(historical_policy),
            historical_policy_raw,
        )

        historical_closed = copy.deepcopy(self.manifest)
        historical_closed["stream"]["stream_mode"] = (
            MATERIALIZER.LEGACY_CLOSED_STREAM_MODE
        )
        historical_closed["integration"]["required_production_successor"] = (
            MATERIALIZER.CLOSED_PRODUCTION_SUCCESSOR
        )
        historical_closed = self.rehash("manifest", historical_closed)
        historical_closed_raw = MATERIALIZER.canonical_bytes(historical_closed)
        replayed = json.loads(historical_closed_raw.decode("utf-8"))
        self.validators["manifest"].validate(replayed)
        self.assertEqual(MATERIALIZER.validate_manifest(replayed), replayed)
        self.assertEqual(
            MATERIALIZER.canonical_bytes(replayed), historical_closed_raw,
        )

        closed = copy.deepcopy(self.manifest)
        closed["stream"]["stream_mode"] = MATERIALIZER.CLOSED_STREAM_MODE
        closed["stream"]["source_bundle_commitment_sha256"] = "a" * 64
        closed["stream"]["terminal_bundle_sha256"] = "b" * 64
        closed["authority"]["remote_fetch_performed"] = True
        closed["authority"]["scheduler_inspection_performed"] = True
        closed["integration"]["production_integration"] = True
        closed["integration"]["required_production_successor"] = (
            MATERIALIZER.CLOSED_PRODUCTION_SUCCESSOR
        )
        closed["integration"]["required_production_target_predecessor"] = (
            MATERIALIZER.PRODUCTION_TARGET_PREDECESSOR
        )
        closed = self.rehash("manifest", closed)
        self.validators["manifest"].validate(self.manifest)
        self.validators["manifest"].validate(closed)
        self.assertEqual(MATERIALIZER.validate_manifest(closed), closed)

        crossed = copy.deepcopy(closed)
        crossed["integration"]["required_production_successor"] = (
            MATERIALIZER.PRODUCTION_SUCCESSOR
        )
        self.assert_both_reject("manifest", self.rehash("manifest", crossed))

    def test_top_level_and_all_material_object_definitions_are_closed(self) -> None:
        assert jsonschema is not None
        object_defs = {
            "policy": ("policy", "offline_authority", "production_authority"),
            "manifest": (
                "materialization", "binding", "target", "stream",
                "input_file_object", "pbs_file_object", "checksums_file_object",
                "receipt_file_object", "log_file_object", "totals", "safety",
                "authority", "integration",
            ),
        }
        for name, schema in self.schemas.items():
            jsonschema.Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            for definition in object_defs[name]:
                value = schema["$defs"][definition]
                self.assertEqual(value["type"], "object")
                self.assertFalse(value["additionalProperties"])
                conditional = set()
                if name == "manifest" and definition == "stream":
                    conditional = {
                        "source_bundle_commitment_sha256",
                        "terminal_bundle_sha256",
                    }
                self.assertEqual(
                    set(value["required"]),
                    set(value["properties"]) - conditional,
                )
        authority = self.schemas["policy"]["$defs"]["authority"]
        self.assertEqual(
            authority,
            {
                "oneOf": [
                    {"$ref": "#/$defs/offline_authority"},
                    {"$ref": "#/$defs/production_authority"},
                ]
            },
        )

    def test_unknown_missing_const_and_boolean_mutations_reject_both(self) -> None:
        for name, source in (("policy", self.policy), ("manifest", self.manifest)):
            changed = copy.deepcopy(source)
            changed["unexpected"] = False
            self.assert_both_reject(name, changed)
            changed = copy.deepcopy(source)
            del changed[next(iter(changed))]
            self.assert_both_reject(name, changed)
        cases = []
        changed = copy.deepcopy(self.policy)
        changed["policy"]["caller_root_override_allowed"] = True
        cases.append(("policy", changed))
        changed = copy.deepcopy(self.policy)
        changed["authority"]["production_integration"] = True
        cases.append(("policy", changed))
        changed = copy.deepcopy(self.manifest)
        changed["authority"]["scientific_acceptance"] = True
        cases.append(("manifest", changed))
        changed = copy.deepcopy(self.manifest)
        changed["integration"]["production_integration"] = True
        cases.append(("manifest", changed))
        changed = copy.deepcopy(self.manifest)
        changed["safety"]["delete_allowed"] = True
        cases.append(("manifest", changed))
        for name, changed in cases:
            self.assert_both_reject(name, self.rehash(name, changed))
        changed = copy.deepcopy(self.manifest)
        changed["binding"]["project"] = "spliced_project"
        changed = self.rehash("manifest", changed)
        self.validators["manifest"].validate(changed)
        with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
            MATERIALIZER.validate_manifest(changed)

    def test_fixed_file_order_count_caps_and_canonical_decimals_reject_both(self) -> None:
        mutations = []
        changed = copy.deepcopy(self.manifest)
        changed["files"][0], changed["files"][1] = changed["files"][1], changed["files"][0]
        mutations.append(changed)
        changed = copy.deepcopy(self.manifest)
        changed["files"].append(copy.deepcopy(changed["files"][-1]))
        mutations.append(changed)
        changed = copy.deepcopy(self.manifest)
        changed["files"][0]["basename"] = "scheduler.out"
        mutations.append(changed)
        changed = copy.deepcopy(self.manifest)
        changed["files"][4]["cap_bytes"] = "1073741825"
        mutations.append(changed)
        changed = copy.deepcopy(self.manifest)
        changed["files"][0]["size_bytes"] = "01"
        mutations.append(changed)
        changed = copy.deepcopy(self.manifest)
        changed["totals"]["file_count"] = "05"
        mutations.append(changed)
        for changed in mutations:
            self.assert_both_reject("manifest", self.rehash("manifest", changed))

    def test_hash_replay_and_nested_unknown_fields_reject_both(self) -> None:
        for name, source, nested in (
            ("policy", self.policy, "policy"),
            ("manifest", self.manifest, "authority"),
        ):
            changed = copy.deepcopy(source)
            changed[nested]["unexpected"] = False
            self.assert_both_reject(name, self.rehash(name, changed))
            changed = copy.deepcopy(source)
            changed["policy_payload_sha256" if name == "policy" else "manifest_payload_sha256"] = "f" * 64
            self.validators[name].validate(changed)
            with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
                self.owner_validate(name, changed)


if __name__ == "__main__":
    unittest.main()
