#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for the fixed mutation result."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests import test_direct_root_fixed_mutation_consumer as SUPPORT


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import direct_root_fixed_mutation_consumer as CONSUMER  # noqa: E402

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
    importlib.metadata.version("jsonschema") if jsonschema is not None else None
)
EXACT_VALIDATOR_AVAILABLE = (
    jsonschema is not None and installed_jsonschema == EXPECTED_JSONSCHEMA_VERSION
)
if REQUIRE_JSONSCHEMA and not EXACT_VALIDATOR_AVAILABLE:
    detail = (
        f"installed jsonschema={installed_jsonschema!r}"
        if JSONSCHEMA_IMPORT_ERROR is None
        else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    )
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}"
    )


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class DirectRootFixedMutationDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        support = SUPPORT.DirectRootFixedMutationConsumerTests()
        temporary = tempfile.TemporaryDirectory(prefix="auto-g16-fixed-schema-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / "reviewed-root"
        root.mkdir()
        capability = support.capability(root)
        self.result = support.transaction(capability).apply_once()
        self.schema = json.loads(
            (
                ROOT
                / "contracts/direct-execution"
                / "direct-root-fixed-mutation-result.schema.json"
            ).read_text(encoding="utf-8")
        )
        assert jsonschema is not None
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def test_completed_owner_result_has_real_draft_parity_and_no_remote_authority(self) -> None:
        self.validator.validate(self.result)
        CONSUMER.validate_fixed_mutation_result(self.result)
        self.assertFalse(self.result["authority"]["remote_effect_authorized"])
        self.assertFalse(self.result["authority"]["qsub_authorized"])

    def test_schema_and_owner_reject_outcome_boolean_operation_and_authority_drift(self) -> None:
        candidates = []
        changed = copy.deepcopy(self.result)
        changed["effect_boundary_crossed"] = 1
        candidates.append(changed)
        changed = copy.deepcopy(self.result)
        changed["operations_completed"].reverse()
        candidates.append(changed)
        changed = copy.deepcopy(self.result)
        changed["authority"]["automatic_retry"] = True
        candidates.append(changed)
        changed = copy.deepcopy(self.result)
        changed["authority"]["filesystem_mutation_completion_confirmed"] = False
        candidates.append(changed)
        for document in candidates:
            with self.subTest(document=document):
                document = CONSUMER._finalize(document)
                self.assertTrue(list(self.validator.iter_errors(document)))
                with self.assertRaises(CONSUMER.DirectRootFixedMutationError):
                    CONSUMER.validate_fixed_mutation_result(document)


if __name__ == "__main__":
    unittest.main()
