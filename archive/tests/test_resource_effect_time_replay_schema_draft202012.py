#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for resource effect-time replay projections."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_resource_effect_time_replay_owner as SUPPORT


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
class ResourceEffectReplayDraft202012Tests(unittest.TestCase):
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
        self.document = SUPPORT.ResourceEffectReplayFixture(
            Path(self.temporary.name)
        ).issue().portable_projection()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_both_reject(self, changed: dict) -> None:
        assert jsonschema is not None
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(changed)
        with self.assertRaises(SUPPORT.REPLAY.ResourceError):
            SUPPORT.REPLAY.validate_resource_effect_time_replay_capability_document(
                changed
            )

    def test_owner_projection_and_closed_schema_validate(self) -> None:
        self.validator.validate(self.document)
        self.assertEqual(
            SUPPORT.REPLAY.validate_resource_effect_time_replay_capability_document(
                self.document
            ),
            self.document,
        )
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(
            set(self.schema["required"]),
            set(self.schema["properties"]),
        )

    def test_all_non_authorizing_markers_have_parity(self) -> None:
        for field in (
            "schema_valid_is_capability",
            "portable_projection_authorizes",
            "raw_json_authorizes",
            "raw_hash_authorizes",
            "cli_argument_authorizes",
            "capability_authorizes_runner",
            "capability_authorizes_transport",
            "capability_authorizes_qsub",
            "production_port_wired",
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.document)
                changed["authority"][field] = True
                changed["payload_sha256"] = SUPPORT.REPLAY._payload(changed)
                self.assert_both_reject(changed)

    def test_fixed_boolean_integer_fields_reject_numeric_confusion(self) -> None:
        fields = {
            "freshness": {
                "max_age_seconds": 30,
                "wall_clock_enforced": True,
                "monotonic_clock_enforced": True,
            },
            "authority": {
                "owner_private_registry_required": True,
                "canonical_module_cache_required": True,
                "single_consumption": True,
                "schema_valid_is_capability": False,
                "portable_projection_authorizes": False,
                "raw_json_authorizes": False,
                "raw_hash_authorizes": False,
                "cli_argument_authorizes": False,
                "capability_authorizes_runner": False,
                "capability_authorizes_transport": False,
                "capability_authorizes_qsub": False,
                "production_port_wired": False,
            },
            "failure_policy": {
                "fail_closed_on_drift": True,
                "failed_consumption_terminal": True,
                "automatic_retry": False,
                "external_effect": False,
            },
        }
        self.assertEqual(sum(len(value) for value in fields.values()), 19)
        for section, section_fields in fields.items():
            for field, expected in section_fields.items():
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
                        changed["payload_sha256"] = SUPPORT.REPLAY._payload(
                            changed
                        )
                        self.assert_both_reject(changed)

    def test_unknown_missing_patterns_and_numeric_types_reject(self) -> None:
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
        changed["identity"]["cores"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["current_resource_state"]["ledger_revision"] = 1.5
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["resource_policy"]["artifact_size"] = False
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                self.assert_both_reject(changed)

    def test_named_resource_tuple_splices_have_parity(self) -> None:
        for field, value in (
            ("resource_tier", "general"),
            ("cores", 22),
            ("memory_gb", 50),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.document)
                changed["identity"][field] = value
                changed["payload_sha256"] = SUPPORT.REPLAY._payload(changed)
                self.assert_both_reject(changed)


if __name__ == "__main__":
    unittest.main()
