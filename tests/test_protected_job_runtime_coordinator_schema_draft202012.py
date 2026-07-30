#!/usr/bin/env python3
"""Draft 2020-12 structural checks for the coordinator projection."""

from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path

from tests import test_protected_job_runtime_coordinator as SUPPORT

try:
    import jsonschema
except ImportError:  # pragma: no cover - pinned validator environments own this.
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
    / "execution"
    / "protected-job-runtime-coordinator.schema.json"
)


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class ProtectedJobRuntimeCoordinatorDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.validator = jsonschema.Draft202012Validator(self.schema)
        self.document = (
            SUPPORT.ProtectedJobRuntimeCoordinatorTests().valid_projection()
        )

    def test_valid_projection_is_structurally_accepted(self) -> None:
        self.validator.validate(self.document)

    def test_top_level_missing_and_additional_fields_are_rejected(self) -> None:
        missing = copy.deepcopy(self.document)
        missing.pop("authority")
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(missing)
        additional = copy.deepcopy(self.document)
        additional["raw_projection_authority"] = True
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(additional)

    def test_semantic_owner_still_rejects_schema_valid_splice(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["authority"]["portable_projection_authorizes"] = True
        self.validator.validate(changed)
        with self.assertRaises(
            SUPPORT.COORDINATOR.ProtectedJobRuntimeCoordinatorError
        ):
            SUPPORT.COORDINATOR.validate_protected_job_runtime_coordinator(
                changed
            )


if __name__ == "__main__":
    unittest.main()
