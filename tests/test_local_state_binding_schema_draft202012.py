#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the local-state public Schema."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests import test_local_state_binding as SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "contracts/execution/local-state-binding.schema.json"
REQUIRE_ENV = "AUTO_G16_REQUIRE_JSONSCHEMA"
EXPECTED_PINS = {
    "attrs": "26.1.0",
    "jsonschema": "4.26.0",
    "jsonschema-specifications": "2025.9.1",
    "referencing": "0.37.0",
    "rpds-py": "2026.6.3",
    "typing-extensions": "4.16.0",
}

raw_requirement = os.environ.get(REQUIRE_ENV, "")
if raw_requirement not in {"", "0", "1"}:
    raise RuntimeError(f"{REQUIRE_ENV} must be unset, 0, or 1")
REQUIRE_JSONSCHEMA = raw_requirement == "1"

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
except ImportError as exc:
    Draft202012Validator = None  # type: ignore[assignment,misc]
    ValidationError = Exception  # type: ignore[assignment,misc]
    JSONSCHEMA_IMPORT_ERROR: Exception | None = exc
else:
    JSONSCHEMA_IMPORT_ERROR = None

installed_jsonschema = (
    importlib.metadata.version("jsonschema")
    if Draft202012Validator is not None
    else None
)
EXACT_VALIDATOR_AVAILABLE = (
    Draft202012Validator is not None
    and installed_jsonschema == EXPECTED_PINS["jsonschema"]
)
if REQUIRE_JSONSCHEMA and not EXACT_VALIDATOR_AVAILABLE:
    detail = (
        f"installed jsonschema={installed_jsonschema!r}"
        if JSONSCHEMA_IMPORT_ERROR is None
        else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    )
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires jsonschema==4.26.0; {detail}"
    )


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require test-only jsonschema==4.26.0; "
    f"set {REQUIRE_ENV}=1 in the reviewed validator environment",
)
class LocalStateBindingDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fixture = SUPPORT.LocalStateFixture(self.root)
        self.document = self.fixture.owner().seal(
            self.fixture.evidence
        ).document()

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def test_exact_reviewed_dependencies_and_schema_are_real(self) -> None:
        declared = {}
        lock = (
            ROOT / "requirements/schema-validation.lock.txt"
        ).read_text(encoding="utf-8")
        for line in lock.splitlines():
            if not line or line.startswith("#"):
                continue
            name, version = line.split("==", 1)
            declared[name] = version
        self.assertEqual(declared, EXPECTED_PINS)
        required_names = set(EXPECTED_PINS)
        if sys.version_info >= (3, 13):
            required_names.remove("typing-extensions")
        self.assertEqual(
            {
                name: importlib.metadata.version(name)
                for name in required_names
            },
            {
                name: version
                for name, version in EXPECTED_PINS.items()
                if name in required_names
            },
        )
        self.validator.validate(self.document)
        self.assertEqual(list(self.validator.iter_errors(self.document)), [])

    def test_draft_integral_numbers_normalize_but_booleans_fail(self) -> None:
        for field in (
            "artifact_size_bytes",
            "revision",
            "resource_state_revision",
        ):
            with self.subTest(field=field):
                draft_integral = copy.deepcopy(self.document)
                draft_integral["ledger"][field] = float(
                    draft_integral["ledger"][field]
                )
                self.validator.validate(draft_integral)
                normalized = (
                    SUPPORT.LOCAL.validate_local_state_binding(
                        draft_integral
                    )
                )
                self.assertIsInstance(normalized["ledger"][field], int)

                boolean_value = copy.deepcopy(self.document)
                boolean_value["ledger"][field] = True
                with self.assertRaises(ValidationError):
                    self.validator.validate(boolean_value)
                with self.assertRaises(
                    SUPPORT.LOCAL.LocalStateBindingError
                ):
                    SUPPORT.LOCAL.validate_local_state_binding(boolean_value)

    def test_schema_structure_and_owner_cross_field_semantics_are_layered(self) -> None:
        structural = copy.deepcopy(self.document)
        structural["layout"]["relative_local_dir"] = (
            f"outputs/other/{self.fixture.protected.attempt_id}"
        )
        structural["binding_payload_sha256"] = SUPPORT.LOCAL.digest(
            {
                key: value
                for key, value in structural.items()
                if key != "binding_payload_sha256"
            }
        )
        self.validator.validate(structural)
        with self.assertRaisesRegex(
            SUPPORT.LOCAL.LocalStateBindingError,
            "owner-derived identity",
        ):
            SUPPORT.LOCAL.validate_local_state_binding(structural)

        absolute = copy.deepcopy(self.document)
        absolute["layout"]["relative_local_dir"] = "/placeholder/absolute"
        with self.assertRaises(ValidationError):
            self.validator.validate(absolute)

    def test_schema_and_owner_reject_every_redundant_ledger_topology(self) -> None:
        different_attempt = "qsub-attempt-" + ("f" * 64)
        if different_attempt == self.fixture.protected.attempt_id:
            different_attempt = "qsub-attempt-" + ("e" * 64)
        cases = {
            "different_project": {
                "relative_ledger_path": (
                    "outputs/other/"
                    f"{self.fixture.protected.attempt_id}/"
                    "execution-batch-v3.json"
                )
            },
            "different_attempt": {
                "relative_ledger_path": (
                    f"outputs/safejob/{different_attempt}/"
                    "execution-batch-v3.json"
                )
            },
            "injected_exact_ledger_path": {
                "relative_ledger_path": (
                    self.document["layout"]["relative_local_dir"]
                    + "/execution-batch-v3.json"
                )
            },
            "selectable_basename": {
                "ledger_basename": "other.json",
            },
            "injected_basename": {
                "caller_ledger_basename": "other.json",
            },
        }
        for label, mutation in cases.items():
            with self.subTest(case=label):
                invalid = copy.deepcopy(self.document)
                invalid["layout"].update(mutation)
                invalid["binding_payload_sha256"] = SUPPORT.LOCAL.digest(
                    {
                        key: value
                        for key, value in invalid.items()
                        if key != "binding_payload_sha256"
                    }
                )
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)
                with self.assertRaises(
                    SUPPORT.LOCAL.LocalStateBindingError
                ):
                    SUPPORT.LOCAL.validate_local_state_binding(invalid)

        self.validator.validate(self.document)
        self.assertEqual(
            SUPPORT.LOCAL.validate_local_state_binding(self.document),
            self.document,
        )
        self.assertNotIn(
            "relative_ledger_path",
            self.document["layout"],
        )

    def test_portable_contract_contains_no_absolute_path(self) -> None:
        strings: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(self.document)
        self.assertFalse(any(item.startswith("/") for item in strings))
        self.assertFalse(any(":\\" in item for item in strings))
        self.validator.validate(self.document)


if __name__ == "__main__":
    unittest.main()
