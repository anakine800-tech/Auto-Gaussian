#!/usr/bin/env python3
"""Draft 2020-12 checks for the production factory result projection."""

from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path

from tests import test_protected_production_factory_consumer as SUPPORT

try:
    import jsonschema
except ImportError:  # pragma: no cover - pinned validator owns this branch.
    jsonschema = None

REQUIRE_JSONSCHEMA = os.environ.get("AUTO_G16_REQUIRE_JSONSCHEMA") == "1"
if REQUIRE_JSONSCHEMA and jsonschema is None:
    raise RuntimeError(
        "AUTO_G16_REQUIRE_JSONSCHEMA=1 requires pinned jsonschema"
    )


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts"
    / "production-factory-consumer"
    / "protected-production-factory-result.schema.json"
)


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class ProtectedProductionFactoryConsumerDraft202012Tests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.validator = jsonschema.Draft202012Validator(self.schema)
        self.document = (
            SUPPORT.ProtectedProductionFactoryConsumerTests()
            .valid_projection()
        )

    def test_valid_projection_is_structurally_accepted(self) -> None:
        self.validator.validate(self.document)

    def test_missing_additional_and_authorizing_fields_are_rejected(
        self,
    ) -> None:
        missing = copy.deepcopy(self.document)
        missing.pop("uncertain_boundary")
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(missing)
        additional = copy.deepcopy(self.document)
        additional["effect_plan"] = {}
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(additional)
        authorizing = copy.deepcopy(self.document)
        authorizing["authority"][
            "thirteen_field_projection_authorizes"
        ] = True
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(authorizing)

    def test_schema_valid_projection_is_not_owner_sealed(self) -> None:
        self.validator.validate(self.document)
        with self.assertRaises(TypeError):
            SUPPORT.CONSUMER.SealedProtectedProductionFactoryResult()

    def test_semantic_owner_rejects_rehashed_legacy_source_splice(
        self,
    ) -> None:
        changed = copy.deepcopy(self.document)
        changed["legacy_factory_binding"]["legacy_source_sha256"] = "a" * 64
        changed["payload_sha256"] = SUPPORT.CONSUMER._payload(changed)
        changed["result_id"] = SUPPORT.CONSUMER._result_id(changed)
        self.validator.validate(changed)
        with self.assertRaises(
            SUPPORT.CONSUMER.ProtectedProductionFactoryConsumerError
        ):
            SUPPORT.CONSUMER.validate_protected_production_factory_result(
                changed
            )


if __name__ == "__main__":
    unittest.main()
