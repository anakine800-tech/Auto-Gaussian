#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the protected-submit public Schema."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_protected_submit_contract as SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "contracts/execution/protected-submit-bundle.schema.json"
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


def at_path(value: object, path: tuple[object, ...]) -> object:
    current = value
    for part in path:
        current = current[part]  # type: ignore[index]
    return current


def set_path(
    value: dict[str, Any],
    path: tuple[object, ...],
    replacement: object,
) -> None:
    parent = at_path(value, path[:-1])
    parent[path[-1]] = replacement  # type: ignore[index]


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require test-only jsonschema==4.26.0; "
    f"set {REQUIRE_ENV}=1 in the reviewed validator environment",
)
class ProtectedSubmitDraft202012Tests(unittest.TestCase):
    """Keep structural Schema claims distinct from owner semantic claims."""

    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fixture = SUPPORT.ProtectedSubmitFixture(self.root)
        self.owner = (
            SUPPORT.CONTRACT.ProtectedSubmitContractOwner._for_testing_with_clock(
                self.root / "trusted-state",
                SUPPORT.PrivateTestClock(SUPPORT.NOW),
                _test_token=SUPPORT.CONTRACT._TEST_OWNER_TOKEN,
            )
        )
        self.document = self.owner.seal(self.fixture.evidence()).document()

    def tearDown(self) -> None:
        self.fixture.transport.tearDown()
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
        actual = {
            name: importlib.metadata.version(name)
            for name in required_names
        }
        self.assertEqual(
            actual,
            {
                name: version
                for name, version in EXPECTED_PINS.items()
                if name in required_names
            },
        )
        if sys.version_info >= (3, 13):
            try:
                typing_extensions_version = importlib.metadata.version(
                    "typing-extensions"
                )
            except importlib.metadata.PackageNotFoundError:
                pass
            else:
                self.assertEqual(
                    typing_extensions_version,
                    EXPECTED_PINS["typing-extensions"],
                )
        self.validator.validate(self.document)
        self.assertEqual(list(self.validator.iter_errors(self.document)), [])

    def test_draft_integer_semantics_normalize_one_and_one_point_zero(self) -> None:
        integer_fields = (
            (("execution", "resource_state_revision"), 1),
            (("resources", "cores"), 1),
            (("resources", "memory_gb"), 1),
            (("resources", "walltime_seconds"), 1),
            (("stage", "artifact_count"), 2),
        )
        for path, canonical_value in integer_fields:
            with self.subTest(path=path):
                integer_document = copy.deepcopy(self.document)
                set_path(integer_document, path, canonical_value)
                integer_document = SUPPORT.CONTRACT.finalize(integer_document)

                draft_integral = copy.deepcopy(integer_document)
                set_path(draft_integral, path, float(canonical_value))
                self.validator.validate(draft_integral)
                normalized = (
                    SUPPORT.CONTRACT.validate_protected_submit_bundle(
                        draft_integral
                    )
                )
                self.assertEqual(
                    SUPPORT.CONTRACT.canonical_bytes(normalized),
                    SUPPORT.CONTRACT.canonical_bytes(integer_document),
                )
                self.assertIsInstance(at_path(normalized, path), int)

                boolean_document = copy.deepcopy(integer_document)
                set_path(boolean_document, path, True)
                with self.assertRaises(ValidationError):
                    self.validator.validate(boolean_document)
                self.assertTrue(
                    list(self.validator.iter_errors(boolean_document))
                )
                with self.assertRaises(SUPPORT.CONTRACT.ProtectedSubmitError):
                    SUPPORT.CONTRACT.validate_protected_submit_bundle(
                        boolean_document
                    )

    def test_canonical_utc_shape_and_owner_calendar_semantics_are_layered(self) -> None:
        time_path = (
            "approvals",
            "live_submission_approval",
            "not_before",
        )
        leap_day = copy.deepcopy(self.document)
        set_path(leap_day, time_path, "2032-02-29T12:00:00Z")
        leap_day = SUPPORT.CONTRACT.finalize(leap_day)
        self.validator.validate(leap_day)
        self.assertEqual(
            SUPPORT.CONTRACT.validate_protected_submit_bundle(leap_day),
            leap_day,
        )

        invalid_calendar = copy.deepcopy(self.document)
        set_path(invalid_calendar, time_path, "2032-02-30T12:00:00Z")
        invalid_calendar = SUPPORT.CONTRACT.finalize(invalid_calendar)
        self.validator.validate(invalid_calendar)
        self.assertEqual(
            list(self.validator.iter_errors(invalid_calendar)),
            [],
        )
        with self.assertRaisesRegex(
            SUPPORT.CONTRACT.ProtectedSubmitError,
            "real calendar",
        ):
            SUPPORT.CONTRACT.validate_protected_submit_bundle(
                invalid_calendar
            )

        offset = copy.deepcopy(self.document)
        set_path(offset, time_path, "2032-02-29T12:00:00+00:00")
        offset = SUPPORT.CONTRACT.finalize(offset)
        with self.assertRaises(ValidationError):
            self.validator.validate(offset)
        with self.assertRaisesRegex(
            SUPPORT.CONTRACT.ProtectedSubmitError,
            "canonical second-precision UTC",
        ):
            SUPPORT.CONTRACT.validate_protected_submit_bundle(offset)

    def test_structural_schema_validity_does_not_issue_or_replace_owner_seal(self) -> None:
        wrong_self_hash = copy.deepcopy(self.document)
        wrong_self_hash["bundle_payload_sha256"] = "f" * 64
        self.validator.validate(wrong_self_hash)
        with self.assertRaisesRegex(
            SUPPORT.CONTRACT.ProtectedSubmitError,
            "payload hash differs",
        ):
            SUPPORT.CONTRACT.validate_protected_submit_bundle(wrong_self_hash)
        with self.assertRaises(TypeError):
            SUPPORT.CONTRACT.SealedProtectedSubmitBundle()


if __name__ == "__main__":
    unittest.main()
