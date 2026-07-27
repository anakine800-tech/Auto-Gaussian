#!/usr/bin/env python3
"""Pinned Draft 2020-12 tests for the protected owner-consumer Schemas."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_owner_consumer_contract as SUPPORT


try:
    import jsonschema
    from referencing import Registry, Resource
except ImportError:
    jsonschema = None
    Registry = None
    Resource = None


ROOT = Path(__file__).parents[1]
CONTRACT_SCHEMA_PATH = (
    ROOT
    / "contracts/execution/protected-owner-consumer-contract.schema.json"
)
INTENT_SCHEMA_PATH = (
    ROOT
    / "contracts/execution/protected-owner-submission-intent.schema.json"
)


@unittest.skipIf(
    jsonschema is None,
    "jsonschema is not installed in the current profile",
)
class ProtectedOwnerConsumerSchemaDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract_schema = json.loads(
            CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        cls.intent_schema = json.loads(
            INTENT_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        assert jsonschema is not None
        assert Registry is not None
        assert Resource is not None
        cls.registry = Registry().with_resource(
            cls.intent_schema["$id"],
            Resource.from_contents(cls.intent_schema),
        )
        cls.contract_validator = jsonschema.Draft202012Validator(
            cls.contract_schema,
            registry=cls.registry,
            format_checker=jsonschema.FormatChecker(),
        )
        cls.intent_validator = jsonschema.Draft202012Validator(
            cls.intent_schema,
            format_checker=jsonschema.FormatChecker(),
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-owner-consumer-schema-",
            dir=SUPPORT.TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = SUPPORT.RuntimeStateFixture(self.root)
        runtime = self.fixture.owner().seal(self.fixture.handoff())
        self.sealed = (
            SUPPORT.CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .prepare_once(runtime)
        )
        self.document = self.sealed.document()

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def test_real_draft_accepts_owner_documents(self) -> None:
        self.contract_validator.validate(self.document)
        self.intent_validator.validate(self.document["intent"])
        self.assertEqual(
            SUPPORT.CONSUMER.validate_protected_owner_consumer_contract(
                self.document
            ),
            self.document,
        )
        self.assertEqual(
            SUPPORT.CONSUMER.validate_protected_owner_submission_intent(
                self.document["intent"]
            ),
            self.document["intent"],
        )

    def test_real_draft_and_owner_reject_closed_structure_matrix(self) -> None:
        cases = []
        extra = copy.deepcopy(self.document)
        extra["unexpected"] = False
        cases.append(extra)
        missing = copy.deepcopy(self.document)
        del missing["runtime_state"]
        cases.append(missing)
        bad_bool = copy.deepcopy(self.document)
        bad_bool["scope"]["transfer"] = 0
        cases.append(bad_bool)
        bad_pattern = copy.deepcopy(self.document)
        bad_pattern["contract_id"] += "\n"
        cases.append(bad_pattern)
        bad_artifact = copy.deepcopy(self.document)
        bad_artifact["upload_bundle"]["artifacts"][-1][
            "relative_name"
        ] = "../checksums.sha256"
        cases.append(bad_artifact)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(jsonschema.ValidationError):
                    self.contract_validator.validate(changed)
                with self.assertRaises(
                    SUPPORT.CONSUMER.ProtectedOwnerConsumerError
                ):
                    SUPPORT.CONSUMER.validate_protected_owner_consumer_contract(
                        changed
                    )

    def test_schema_validity_does_not_issue_owner_seal(self) -> None:
        self.contract_validator.validate(self.document)
        structural = copy.deepcopy(self.document)
        self.assertIsInstance(structural, dict)
        self.assertFalse(
            isinstance(
                structural,
                SUPPORT.CONSUMER.SealedProtectedOwnerConsumerContract,
            )
        )
        with self.assertRaises(TypeError):
            SUPPORT.CONSUMER.SealedProtectedOwnerConsumerContract(structural)


if __name__ == "__main__":
    if (
        os.environ.get("AUTO_G16_REQUIRE_JSONSCHEMA") == "1"
        and jsonschema is None
    ):
        raise SystemExit("jsonschema is required but unavailable")
    unittest.main()
