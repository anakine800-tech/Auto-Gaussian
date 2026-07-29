#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for the reservation capability projection."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_execution_batch_reservation_capability as SUPPORT


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
class ReservationCapabilityDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert jsonschema is not None
        cls.schema = json.loads(
            SUPPORT.SCHEMA_PATH.read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(cls.schema)
        cls.validator = jsonschema.Draft202012Validator(
            cls.schema,
            format_checker=jsonschema.FormatChecker(),
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        fixture = SUPPORT.ReservationCapabilityFixture(
            Path(self.temporary.name)
        )
        self.document = fixture.capability().portable_projection()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_both_reject(self, changed: dict) -> None:
        assert jsonschema is not None
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(changed)
        with self.assertRaises(SUPPORT.RESOURCE.ResourceError):
            SUPPORT.RESOURCE.validate_reservation_capability_document(
                changed
            )

    def test_owner_projection_and_closed_schema_validate(self) -> None:
        self.validator.validate(self.document)
        self.assertEqual(
            SUPPORT.RESOURCE.validate_reservation_capability_document(
                self.document
            ),
            self.document,
        )
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(
            set(self.schema["required"]),
            set(self.schema["properties"]),
        )

    def test_projection_hash_or_raw_json_never_becomes_authority(self) -> None:
        for field in (
            "portable_projection_authorizes",
            "raw_reservation_json_is_authority",
            "raw_reservation_sha256_is_authority",
            "capability_authorizes_runner",
            "capability_authorizes_transport",
            "capability_authorizes_qsub",
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.document)
                changed["authority"][field] = True
                self.assert_both_reject(changed)

    def test_all_fifteen_fixed_bool_integer_fields_have_bidirectional_parity(
        self,
    ) -> None:
        fields_by_section = SUPPORT.FIXED_BOOL_INTEGER_FIELDS
        self.assertEqual(
            sum(len(fields) for fields in fields_by_section.values()),
            15,
        )
        for section, fields in fields_by_section.items():
            for field, expected in fields.items():
                replacements = (
                    (0, 1)
                    if type(expected) is bool
                    else (False, True)
                )
                for replacement in replacements:
                    with self.subTest(
                        section=section,
                        field=field,
                        replacement=replacement,
                    ):
                        changed = copy.deepcopy(self.document)
                        changed[section][field] = replacement
                        changed["payload_sha256"] = (
                            SUPPORT.RESOURCE._payload(changed)
                        )
                        self.assert_both_reject(changed)

    def test_unknown_missing_pattern_and_numeric_confusion_reject(self) -> None:
        cases = []
        changed = copy.deepcopy(self.document)
        changed["unexpected"] = False
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        del changed["failure_policy"]
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["identity"]["attempt_id"] = "qsub-attempt-not-a-hash"
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["reservation"]["physical_attempt_count"] = 1.5
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["ledger"]["resource_state_revision"] = True
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                self.assert_both_reject(changed)


if __name__ == "__main__":
    unittest.main()
