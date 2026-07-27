#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the PR4L materialized-state Schema."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_local_materialization as SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts/execution/"
    "protected-local-materialization.schema.json"
)
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
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class ProtectedLocalMaterializationDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-materialization-schema-",
            dir=SUPPORT.TEST_TEMP_PARENT,
        )
        cls.fixture = SUPPORT.ProtectedLocalMaterializationFixture(
            Path(cls.temporary.name).resolve()
        )
        cls.sealed = cls.fixture.owner().materialize_once(
            cls.fixture.evidence
        )
        cls.document = cls.sealed.document()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()
        cls.temporary.cleanup()

    def assert_both_reject(self, document: dict) -> None:
        with self.assertRaises(ValidationError):
            self.validator.validate(document)
        with self.assertRaises(
            SUPPORT.MATERIALIZATION.ProtectedLocalMaterializationError
        ):
            (
                SUPPORT.MATERIALIZATION
                .validate_protected_local_materialization_state(document)
            )

    def test_exact_dependencies_schema_and_owner_projection_validate(
        self,
    ) -> None:
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
        self.validator.validate(self.document)
        self.assertEqual(
            (
                SUPPORT.MATERIALIZATION
                .validate_protected_local_materialization_state(
                    self.document
                )
            ),
            self.document,
        )
        self.sealed.assert_owner_sealed()
        self.sealed.assert_current()

    def test_all_fixed_boolean_fields_reject_zero_and_one(self) -> None:
        fixed = {
            "scope": SUPPORT.MATERIALIZATION.SCOPE,
            "status": SUPPORT.MATERIALIZATION.STATUS,
            "policy": SUPPORT.MATERIALIZATION.POLICY,
        }
        for section, expected in fixed.items():
            for field in expected:
                for replacement in (0, 1):
                    with self.subTest(
                        section=section,
                        field=field,
                        replacement=replacement,
                    ):
                        changed = copy.deepcopy(self.document)
                        changed[section][field] = replacement
                        self.assert_both_reject(changed)

    def test_required_unknown_type_hash_and_integer_matrix(self) -> None:
        for field in self.document:
            with self.subTest(missing=field):
                changed = copy.deepcopy(self.document)
                del changed[field]
                self.assert_both_reject(changed)
        changed = copy.deepcopy(self.document)
        changed["unknown"] = None
        self.assert_both_reject(changed)

        for path in (
            ("invocation", "stage_artifact_count"),
            ("ledger", "size_bytes"),
            ("stage_plan", "artifact_count"),
        ):
            parent, field = path
            with self.subTest(integer=f"{parent}.{field}"):
                changed = copy.deepcopy(self.document)
                changed[parent][field] = float(changed[parent][field])
                self.validator.validate(changed)
                normalized = (
                    SUPPORT.MATERIALIZATION
                    .validate_protected_local_materialization_state(changed)
                )
                self.assertIsInstance(normalized[parent][field], int)
                changed[parent][field] = True
                self.assert_both_reject(changed)

        changed = copy.deepcopy(self.document)
        changed["lifecycle"]["structural_projection_sha256"] = "A" * 64
        self.assert_both_reject(changed)

    def test_schema_structure_does_not_issue_owner_acceptance(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["directory_topology"][-2:] = list(
            reversed(changed["directory_topology"][-2:])
        )
        self.validator.validate(changed)
        with self.assertRaises(
            SUPPORT.MATERIALIZATION.ProtectedLocalMaterializationError
        ):
            (
                SUPPORT.MATERIALIZATION
                .validate_protected_local_materialization_state(changed)
            )

        changed = copy.deepcopy(self.document)
        changed["lifecycle"]["structural_projection_sha256"] = "f" * 64
        changed["state_payload_sha256"] = (
            SUPPORT.MATERIALIZATION._state_payload_sha256(changed)
        )
        seed = SUPPORT.MATERIALIZATION.digest(
            {
                "schema": (
                    "auto-g16-protected-local-materialization-id/1"
                ),
                "lifecycle_id": changed["lifecycle"]["lifecycle_id"],
                "invocation_payload_sha256": changed["invocation"][
                    "invocation_payload_sha256"
                ],
                "consumption_sha256": changed["reservation"][
                    "consumption_sha256"
                ],
                "local_state_binding_payload_sha256": changed[
                    "local_state"
                ]["binding_payload_sha256"],
                "state_payload_sha256": changed[
                    "state_payload_sha256"
                ],
            }
        )
        changed["materialization_id"] = (
            f"protected-local-materialization-{seed}"
        )
        self.validator.validate(changed)
        (
            SUPPORT.MATERIALIZATION
            .validate_protected_local_materialization_state(changed)
        )
        self.assertNotEqual(changed, self.sealed.document())
        self.sealed.assert_owner_sealed()


if __name__ == "__main__":
    unittest.main()
