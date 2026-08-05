#!/usr/bin/env python3
"""Draft 2020-12 parity for the synthetic direct-root result projection."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import unittest
from pathlib import Path

from tests.test_direct_root_owner_contract import DirectRootFixture


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import direct_root_mutation_boundary as BOUNDARY  # noqa: E402

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


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class DirectRootMutationBoundaryDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = DirectRootFixture()
        owner = BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=BOUNDARY._TEST_TOKEN
        )
        helper = owner._synthetic_helper_for_testing(
            _test_token=BOUNDARY._TEST_TOKEN
        )
        transaction = owner.issue_synthetic_transaction_once(
            root_capability=fixture.capability(),
            helper=helper,
        )
        self.result = transaction.consume_and_apply_synthetic_once()
        schema_path = (
            ROOT
            / "contracts/direct-execution"
            / "direct-root-synthetic-mutation-result.schema.json"
        )
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert jsonschema is not None
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def test_owner_result_is_schema_valid_and_still_non_authorizing(self) -> None:
        self.validator.validate(self.result)
        self.assertFalse(self.result["authority"]["remote_effect_performed"])
        self.assertFalse(self.result["authority"]["transport_authorized"])
        self.assertFalse(self.result["authority"]["qsub_authorized"])
        owner = BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=BOUNDARY._TEST_TOKEN
        )
        helper = owner._synthetic_helper_for_testing(
            _test_token=BOUNDARY._TEST_TOKEN
        )
        with self.assertRaises(BOUNDARY.DirectRootMutationBoundaryError):
            owner.issue_synthetic_transaction_once(
                root_capability=self.result,
                helper=helper,
            )

    def test_schema_and_owner_reject_operation_or_authority_drift(self) -> None:
        cases = []
        changed = copy.deepcopy(self.result)
        changed["operations"].reverse()
        cases.append(changed)
        changed = copy.deepcopy(self.result)
        changed["operations"][0]["overwrite_allowed"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.result)
        changed["authority"]["remote_effect_performed"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.result)
        changed["authority"]["backend_supported"] = True
        cases.append(changed)
        for document in cases:
            with self.subTest(document=document):
                self.assertTrue(list(self.validator.iter_errors(document)))
                with self.assertRaises(BOUNDARY.DirectRootMutationBoundaryError):
                    BOUNDARY.validate_synthetic_mutation_result(document)


if __name__ == "__main__":
    unittest.main()
