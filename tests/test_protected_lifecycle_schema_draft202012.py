#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the PR4K structural projection."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_lifecycle_contract as SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts/execution/protected-lifecycle-contract.schema.json"
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


def reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class ProtectedLifecycleDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-lifecycle-schema-",
            dir=SUPPORT.TEST_TEMP_PARENT,
        )
        cls.fixture = SUPPORT.ProtectedLifecycleFixture(
            Path(cls.temporary.name).resolve()
        )
        cls.sealed = cls.fixture.owner().seal(cls.fixture.evidence)
        cls.document = cls.sealed.document()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()
        cls.temporary.cleanup()

    def assert_both_reject(self, document: dict) -> None:
        with self.assertRaises(ValidationError):
            self.validator.validate(document)
        with self.assertRaises(
            SUPPORT.LIFECYCLE.ProtectedLifecycleError
        ):
            SUPPORT.LIFECYCLE.validate_protected_lifecycle_structure(
                document
            )

    def test_exact_dependencies_and_owner_projection_validate(self) -> None:
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
            SUPPORT.LIFECYCLE.validate_protected_lifecycle_structure(
                self.document
            ),
            self.document,
        )
        self.sealed.assert_owner_sealed()

    def test_integral_number_normalization_and_bool_rejection(self) -> None:
        draft = copy.deepcopy(self.document)
        draft["protected_invocation_projection"][
            "stage_artifact_count"
        ] = float(
            draft["protected_invocation_projection"][
                "stage_artifact_count"
            ]
        )
        self.validator.validate(draft)
        normalized = (
            SUPPORT.LIFECYCLE
            .validate_protected_lifecycle_structure(draft)
        )
        self.assertIsInstance(
            normalized["protected_invocation_projection"][
                "stage_artifact_count"
            ],
            int,
        )
        boolean = copy.deepcopy(self.document)
        boolean["protected_invocation_projection"][
            "stage_artifact_count"
        ] = True
        self.assert_both_reject(boolean)

    def test_all_fixed_boolean_fields_reject_zero_and_one_bidirectionally(
        self,
    ) -> None:
        fixed_mappings = {
            "validation": SUPPORT.LIFECYCLE.VALIDATION_LAYERS,
            "scope": SUPPORT.LIFECYCLE.SCOPE,
            "status": SUPPORT.LIFECYCLE.STATUS,
            "legacy_compatibility": (
                SUPPORT.LIFECYCLE.LEGACY_COMPATIBILITY
            ),
        }
        for section, expected in fixed_mappings.items():
            for field in expected:
                for replacement in (0, 1):
                    with self.subTest(
                        section=section,
                        field=field,
                        replacement=replacement,
                    ):
                        draft = copy.deepcopy(self.document)
                        draft[section][field] = replacement
                        self.assert_both_reject(draft)

    def test_generated_structural_acceptance_matrix_is_bidirectional(
        self,
    ) -> None:
        cases = [copy.deepcopy(self.document)]
        for field, replacement in (
            ("invocation_id", "protected-invocation-" + "0" * 64),
            ("invocation_payload_sha256", "0" * 64),
            ("ledger_identity_sha256", "1" * 64),
            ("stage_manifest_sha256", "2" * 64),
        ):
            draft = copy.deepcopy(self.document)
            draft["protected_invocation_projection"][field] = replacement
            draft = SUPPORT.LIFECYCLE._finalize_owner_projection(draft)
            cases.append(draft)
        for index, draft in enumerate(cases):
            with self.subTest(index=index):
                self.validator.validate(draft)
                SUPPORT.LIFECYCLE.validate_protected_lifecycle_structure(
                    draft
                )

    def test_unknown_status_and_orders_reject_bidirectionally(self) -> None:
        cases = []
        unknown = copy.deepcopy(self.document)
        unknown["unknown"] = False
        cases.append(unknown)
        marker = copy.deepcopy(self.document)
        marker["validation"]["schema_validity_grants_seal"] = True
        cases.append(marker)
        status = copy.deepcopy(self.document)
        status["status"]["reserved"] = True
        cases.append(status)
        effect = copy.deepcopy(self.document)
        effect["status"]["effects_performed"] = True
        cases.append(effect)
        order = copy.deepcopy(self.document)
        order["required_future_implementation_order"] = list(
            reversed(order["required_future_implementation_order"])
        )
        cases.append(order)
        for index, draft in enumerate(cases):
            with self.subTest(index=index):
                self.assert_both_reject(draft)

    def test_nonfinite_and_malformed_hashes_reject_bidirectionally(
        self,
    ) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            self.assertFalse(math.isfinite(value))
            draft = copy.deepcopy(self.document)
            draft["protected_invocation_projection"][
                "stage_artifact_count"
            ] = value
            self.assert_both_reject(draft)
        malformed = copy.deepcopy(self.document)
        malformed["protected_invocation_projection"][
            "stage_manifest_sha256"
        ] = "not-a-sha"
        self.assert_both_reject(malformed)

    def test_schema_valid_splices_are_not_owner_acceptance(self) -> None:
        cases = []
        for field, replacement in (
            ("invocation_id", "protected-invocation-" + "0" * 64),
            ("invocation_payload_sha256", "0" * 64),
            ("ledger_identity_sha256", "1" * 64),
            ("stage_manifest_sha256", "2" * 64),
        ):
            draft = copy.deepcopy(self.document)
            draft["protected_invocation_projection"][field] = replacement
            cases.append(
                SUPPORT.LIFECYCLE._finalize_owner_projection(draft)
            )
        for index, draft in enumerate(cases):
            with self.subTest(index=index):
                self.validator.validate(draft)
                SUPPORT.LIFECYCLE.validate_protected_lifecycle_structure(
                    draft
                )
                with self.assertRaises(
                    SUPPORT.LIFECYCLE.ProtectedLifecycleError
                ):
                    SUPPORT.LIFECYCLE._validate_owner_projection(
                        draft,
                        self.sealed.protected_invocation_bundle.document(),
                    )
                self.assertTrue(
                    draft["validation"]["structural_validation_only"]
                )
                self.assertTrue(
                    draft["validation"]["owner_replay_required"]
                )
                self.assertFalse(
                    draft["validation"][
                        "schema_validity_grants_owner_acceptance"
                    ]
                )
                self.assertFalse(
                    draft["validation"]["schema_validity_grants_seal"]
                )

    def test_duplicate_keys_rejected_before_validation(self) -> None:
        encoded = json.dumps(self.document, separators=(",", ":"))
        duplicate = encoded.replace(
            (
                '"schema":'
                '"auto-g16-protected-lifecycle-structural-projection/1"'
            ),
            (
                '"schema":'
                '"auto-g16-protected-lifecycle-structural-projection/1",'
                '"schema":'
                '"auto-g16-protected-lifecycle-structural-projection/1"'
            ),
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate key"):
            json.loads(
                duplicate,
                object_pairs_hook=reject_duplicate_pairs,
            )


if __name__ == "__main__":
    unittest.main()
