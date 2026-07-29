#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity tests for PR6A direct-root schemas."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import unittest
from pathlib import Path

from tests import test_direct_root_owner_contract as SUPPORT


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

installed_jsonschema = (
    importlib.metadata.version("jsonschema")
    if jsonschema is not None
    else None
)
EXACT_VALIDATOR_AVAILABLE = (
    jsonschema is not None
    and installed_jsonschema == EXPECTED_JSONSCHEMA_VERSION
)
if REQUIRE_JSONSCHEMA and not EXACT_VALIDATOR_AVAILABLE:
    detail = (
        f"installed jsonschema={installed_jsonschema!r}"
        if JSONSCHEMA_IMPORT_ERROR is None
        else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    )
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires "
        f"jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}"
    )


ROOT = Path(__file__).parents[1]
SCHEMA_PATHS = {
    "policy": ROOT / "contracts/direct-execution/direct-profile-policy.schema.json",
    "stable": ROOT / "contracts/direct-execution/stable-root-identity-evidence.schema.json",
    "profile": ROOT / "contracts/direct-execution/execution-profile-v3.schema.json",
    "authorization": ROOT / "contracts/direct-execution/execution-authorization-v3.schema.json",
    "receipt": ROOT / "contracts/direct-execution/fresh-root-observation-receipt.schema.json",
}


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class DirectRootOwnerSchemaDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert jsonschema is not None
        cls.schemas = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in SCHEMA_PATHS.items()
        }
        cls.validators = {
            name: jsonschema.Draft202012Validator(
                schema,
                format_checker=jsonschema.FormatChecker(),
            )
            for name, schema in cls.schemas.items()
        }
        cls.owner_validators = {
            "policy": SUPPORT.DIRECT.validate_profile_policy,
            "stable": SUPPORT.DIRECT.validate_stable_root_identity_evidence,
            "profile": SUPPORT.DIRECT.validate_direct_execution_profile,
            "authorization": SUPPORT.DIRECT.validate_direct_execution_authorization,
            "receipt": SUPPORT.DIRECT.validate_fresh_root_observation_receipt,
        }

    def setUp(self) -> None:
        fixture = SUPPORT.DirectRootFixture()
        capability = fixture.capability()
        self.documents = {
            "policy": fixture.policy,
            "stable": fixture.evidence.document(),
            "profile": fixture.profile,
            "authorization": fixture.authorization,
            "receipt": capability.portable_receipt(),
        }

    def assert_both_reject(self, name: str, changed: dict[str, object]) -> None:
        assert jsonschema is not None
        with self.assertRaises(jsonschema.ValidationError):
            self.validators[name].validate(changed)
        with self.assertRaises(SUPPORT.DIRECT.DirectRootOwnerError):
            self.owner_validators[name](changed)

    def test_real_draft_accepts_all_owner_documents(self) -> None:
        for name, document in self.documents.items():
            with self.subTest(name=name):
                self.validators[name].validate(document)
                self.assertEqual(
                    self.owner_validators[name](document),
                    document,
                )

    def test_every_schema_is_closed_and_required_equals_properties(self) -> None:
        for name, schema in self.schemas.items():
            with self.subTest(name=name):
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(
                    set(schema["required"]),
                    set(schema["properties"]),
                )
                jsonschema.Draft202012Validator.check_schema(schema)

    def test_unknown_and_missing_top_level_fields_reject_bidirectionally(self) -> None:
        for name, document in self.documents.items():
            with self.subTest(name=name, case="unknown"):
                changed = copy.deepcopy(document)
                changed["unexpected"] = False
                self.assert_both_reject(name, changed)
            with self.subTest(name=name, case="missing"):
                changed = copy.deepcopy(document)
                del changed[next(iter(changed))]
                self.assert_both_reject(name, changed)

    def test_const_boolean_pattern_and_integer_matrix_rejects_both(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        policy = copy.deepcopy(self.documents["policy"])
        policy["backend_kind"] = "legacy_rtwin_pbs"
        cases.append(("policy", policy))
        stable = copy.deepcopy(self.documents["stable"])
        stable["safety"]["no_delete"] = 0
        cases.append(("stable", stable))
        profile = copy.deepcopy(self.documents["profile"])
        profile["declared_capabilities"] = list(reversed(profile["declared_capabilities"]))
        cases.append(("profile", profile))
        authorization = copy.deepcopy(self.documents["authorization"])
        authorization["fresh_observation_rules"]["maximum_receipt_age_seconds"] = 301
        cases.append(("authorization", authorization))
        authorization = copy.deepcopy(self.documents["authorization"])
        authorization["scope"]["scientific_task_id"] += "\n"
        cases.append(("authorization", authorization))
        receipt = copy.deepcopy(self.documents["receipt"])
        receipt["operation"]["nonce"] = "x" * 32
        cases.append(("receipt", receipt))
        receipt = copy.deepcopy(self.documents["receipt"])
        receipt["authority"]["portable_receipt_authorizes_effect"] = True
        cases.append(("receipt", receipt))
        for name, changed in cases:
            with self.subTest(name=name, changed=changed):
                self.assert_both_reject(name, changed)

    def test_schema_acceptance_does_not_issue_owner_capability(self) -> None:
        receipt = self.documents["receipt"]
        self.validators["receipt"].validate(receipt)
        structural = copy.deepcopy(receipt)
        self.assertIsInstance(structural, dict)
        self.assertNotIsInstance(
            structural,
            SUPPORT.DIRECT.FreshRootObservationReceipt,
        )
        with self.assertRaises(TypeError):
            SUPPORT.DIRECT.FreshRootObservationReceipt(structural)
        with self.assertRaises(TypeError):
            SUPPORT.DIRECT.SingleUseWorkspaceDescriptorCapability(structural)


if __name__ == "__main__":
    unittest.main()
