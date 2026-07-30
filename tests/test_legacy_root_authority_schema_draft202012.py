#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for fixed legacy root authority schemas."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_legacy_root_authority_contract as SUPPORT


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
    "stable": (
        ROOT
        / "contracts/legacy-root-authority/"
        "legacy-stable-root-identity-evidence.schema.json"
    ),
    "authorization": (
        ROOT
        / "contracts/legacy-root-authority/"
        "legacy-root-authority-authorization.schema.json"
    ),
    "receipt": (
        ROOT
        / "contracts/legacy-root-authority/"
        "legacy-fresh-root-observation-receipt.schema.json"
    ),
    "mutation": (
        ROOT
        / "contracts/legacy-root-authority/"
        "legacy-descriptor-relative-mutation-capability-binding.schema.json"
    ),
}


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class LegacyRootAuthoritySchemaDraft202012Tests(unittest.TestCase):
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
            "stable": (
                SUPPORT.ROOT_AUTHORITY
                .validate_legacy_stable_root_identity_evidence
            ),
            "authorization": (
                SUPPORT.ROOT_AUTHORITY
                .validate_legacy_root_authority_authorization
            ),
            "receipt": (
                SUPPORT.ROOT_AUTHORITY
                .validate_legacy_fresh_root_observation_receipt
            ),
            "mutation": (
                SUPPORT.ROOT_AUTHORITY
                .validate_legacy_descriptor_relative_mutation_binding
            ),
        }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-legacy-root-schema-",
            dir=SUPPORT.TEMP_PARENT,
        )
        self.fixture = SUPPORT.LegacyRootFixture(
            Path(self.temporary.name).resolve()
        )
        capability = self.fixture.capability()
        mutation = {
            "schema": SUPPORT.ROOT_AUTHORITY.MUTATION_BINDING_SCHEMA,
            "fixed_root": SUPPORT.ROOT_AUTHORITY.FIXED_REMOTE_ROOT,
            "fresh_receipt_sha256": "a" * 64,
            "descriptor_set_sha256": "b" * 64,
            "production_factory_result_sha256": "c" * 64,
            "coordinator_id": "coordinator-1",
            "operation_identity": {
                "module": SUPPORT.ROOT_AUTHORITY.MODULE_NAME,
                "class": "_DescriptorRelativeMutationOperation",
                "method": "perform_descriptor_relative_once",
            },
            "path_reopen_allowed": False,
            "automatic_retry": False,
        }
        self.documents = {
            "stable": self.fixture.evidence.document(),
            "authorization": self.fixture.authorization,
            "receipt": capability.portable_receipt(),
            "mutation": copy.deepcopy(mutation),
        }

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def assert_both_reject(
        self, name: str, changed: dict[str, object]
    ) -> None:
        assert jsonschema is not None
        with self.assertRaises(jsonschema.ValidationError):
            self.validators[name].validate(changed)
        with self.assertRaises(
            SUPPORT.ROOT_AUTHORITY.LegacyRootAuthorityError
        ):
            self.owner_validators[name](changed)

    def test_real_draft_accepts_every_owner_document(self) -> None:
        for name, document in self.documents.items():
            with self.subTest(name=name):
                self.validators[name].validate(document)
                self.assertEqual(
                    self.owner_validators[name](document),
                    document,
                )

    def test_every_schema_is_closed_and_required_equals_properties(self) -> None:
        assert jsonschema is not None
        for name, schema in self.schemas.items():
            with self.subTest(name=name):
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(
                    set(schema["required"]),
                    set(schema["properties"]),
                )
                jsonschema.Draft202012Validator.check_schema(schema)

    def test_unknown_and_missing_fields_reject_bidirectionally(self) -> None:
        for name, document in self.documents.items():
            changed = copy.deepcopy(document)
            changed["unexpected"] = False
            self.assert_both_reject(name, changed)
            changed = copy.deepcopy(document)
            del changed[next(iter(changed))]
            self.assert_both_reject(name, changed)

    def test_fixed_root_boolean_pattern_and_range_matrix_rejects(self) -> None:
        cases = []
        stable = copy.deepcopy(self.documents["stable"])
        stable["fixed_root_policy"]["allowed_root"] = "/tmp"
        cases.append(("stable", stable))
        stable = copy.deepcopy(self.documents["stable"])
        stable["safety"]["no_reparse_point"] = 1
        cases.append(("stable", stable))
        authorization = copy.deepcopy(self.documents["authorization"])
        authorization["protected_production_ingress"]["attempt_id"] = "bad"
        cases.append(("authorization", authorization))
        authorization = copy.deepcopy(self.documents["authorization"])
        authorization["scope"]["maximum_receipt_age_seconds"] = "301"
        cases.append(("authorization", authorization))
        receipt = copy.deepcopy(self.documents["receipt"])
        receipt["observed_root"]["reparse_point_detected"] = True
        cases.append(("receipt", receipt))
        mutation = copy.deepcopy(self.documents["mutation"])
        mutation["fixed_root"] = "/tmp"
        cases.append(("mutation", mutation))
        receipt = copy.deepcopy(self.documents["receipt"])
        receipt["authority"][
            "synthetic_observation_authorizes_remote_effect"
        ] = True
        cases.append(("receipt", receipt))
        for name, changed in cases:
            with self.subTest(name=name):
                self.assert_both_reject(name, changed)

    def test_all_ordinal_and_duration_positions_reject_numbers(self) -> None:
        cases = []
        stable = copy.deepcopy(self.documents["stable"])
        stable["expected_root_identity"]["components"][0]["ordinal"] = 0
        cases.append(("stable", stable))
        authorization = copy.deepcopy(self.documents["authorization"])
        authorization["scope"]["maximum_receipt_age_seconds"] = 60
        cases.append(("authorization", authorization))
        receipt = copy.deepcopy(self.documents["receipt"])
        receipt["observed_root"]["identity"]["components"][0]["ordinal"] = 0.0
        cases.append(("receipt", receipt))
        receipt = copy.deepcopy(self.documents["receipt"])
        receipt["window"]["maximum_receipt_age_seconds"] = 60.0
        cases.append(("receipt", receipt))
        self.assertEqual(len(cases), 4)
        for name, changed in cases:
            with self.subTest(name=name):
                self.assert_both_reject(name, changed)

    def test_schema_acceptance_never_issues_owner_seals(self) -> None:
        receipt = copy.deepcopy(self.documents["receipt"])
        self.validators["receipt"].validate(receipt)
        self.assertIsInstance(receipt, dict)
        with self.assertRaises(TypeError):
            SUPPORT.ROOT_AUTHORITY.LegacyFreshRootObservationReceipt(receipt)
        with self.assertRaises(TypeError):
            SUPPORT.ROOT_AUTHORITY.SingleUseLegacyWorkspaceDescriptorCapability(
                receipt
            )


if __name__ == "__main__":
    unittest.main()
