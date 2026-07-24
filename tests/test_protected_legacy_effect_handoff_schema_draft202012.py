#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the PR4N handoff Schema."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_legacy_effect_handoff as SUPPORT
from tests import test_protected_submit_contract as PR4D_SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts/execution/"
    "protected-legacy-effect-handoff.schema.json"
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
class ProtectedLegacyEffectHandoffDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-pr4n-schema-",
            dir=SUPPORT.TEST_TEMP_PARENT,
        )
        cls.root = Path(cls.temporary.name).resolve()
        cls.fixture = (
            SUPPORT.SUPPORT.ProtectedLocalMaterializationFixture(cls.root)
        )
        with (
            SUPPORT.FACADE._exact_protected_local_materialization()
            as owner_module
        ):
            owner = (
                owner_module.ProtectedLocalMaterializationOwner
                ._for_testing_with_clock(
                    cls.fixture.state_root,
                    lambda: PR4D_SUPPORT.parse_utc(PR4D_SUPPORT.NOW),
                    _test_token=owner_module._TEST_OWNER_TOKEN,
                )
            )
            materialization = owner.materialize_once(cls.fixture.evidence)
        cls.sealed = (
            SUPPORT.FACADE.seal_protected_legacy_effect_handoff(
                materialization=materialization
            )
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
            SUPPORT.HANDOFF.ProtectedLegacyEffectHandoffError
        ):
            SUPPORT.HANDOFF.validate_protected_legacy_effect_handoff(
                document
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
            SUPPORT.HANDOFF.validate_protected_legacy_effect_handoff(
                self.document
            ),
            self.document,
        )
        self.sealed.assert_current()

    def test_all_fixed_boolean_fields_reject_zero_and_one(self) -> None:
        fixed = {
            ("scope",): SUPPORT.HANDOFF.SCOPE,
            ("status",): SUPPORT.HANDOFF.STATUS,
            ("policy",): SUPPORT.HANDOFF.POLICY,
            (
                "lifecycle_readiness",
                "lifecycle_guards",
            ): {
                "one_plan_one_owner": True,
                "single_active_lifecycle": True,
                "terminal_retirement": True,
                "registry_retired_on_every_terminal_exit": True,
            },
            (
                "lifecycle_readiness",
                "status",
            ): {
                "effect_plan_created": False,
                "raw_effect_owner_created": False,
                "registry_entry_created": False,
                "effects_performed": False,
                "runner_called": False,
                "adapter_connected": False,
            },
        }
        for path, expected in fixed.items():
            for field in expected:
                for replacement in (0, 1):
                    with self.subTest(
                        path=path,
                        field=field,
                        replacement=replacement,
                    ):
                        changed = copy.deepcopy(self.document)
                        target = changed
                        for component in path:
                            target = target[component]
                        target[field] = replacement
                        self.assert_both_reject(changed)

    def test_required_unknown_hash_length_and_newline_matrix(self) -> None:
        for field in self.document:
            with self.subTest(missing=field):
                changed = copy.deepcopy(self.document)
                del changed[field]
                self.assert_both_reject(changed)
        changed = copy.deepcopy(self.document)
        changed["unknown"] = None
        self.assert_both_reject(changed)

        paths = (
            ("handoff_id",),
            ("handoff_payload_sha256",),
            ("materialization", "materialization_id"),
            ("materialization", "state_payload_sha256"),
            ("materialization", "lifecycle_id"),
            ("materialization", "invocation_id"),
            ("materialization", "attempt_id"),
            (
                "lifecycle_readiness",
                "witness_payload_sha256",
            ),
            (
                "owner_bindings",
                "legacy_owner_source_sha256",
            ),
            (
                "owner_bindings",
                "handoff_owner_source_sha256",
            ),
        )
        for path in paths:
            target = self.document
            for component in path:
                target = target[component]
            for replacement in (
                target[:-1],
                target + "0",
                target + "\n",
                target + "\r\n",
            ):
                with self.subTest(path=path, replacement=repr(replacement)):
                    changed = copy.deepcopy(self.document)
                    changed_target = changed
                    for component in path[:-1]:
                        changed_target = changed_target[component]
                    changed_target[path[-1]] = replacement
                    self.assert_both_reject(changed)

    def test_schema_is_structural_and_cannot_issue_owner_seal(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["owner_bindings"]["legacy_owner_source_sha256"] = "f" * 64
        changed["handoff_payload_sha256"] = (
            SUPPORT.HANDOFF._payload_sha256(changed)
        )
        changed["handoff_id"] = (
            "protected-legacy-effect-handoff-"
            + SUPPORT.HANDOFF.digest(
                {
                    "schema": (
                        "auto-g16-protected-legacy-effect-handoff-id/1"
                    ),
                    "materialization_id": changed["materialization"][
                        "materialization_id"
                    ],
                    "witness_payload_sha256": changed[
                        "lifecycle_readiness"
                    ]["witness_payload_sha256"],
                    "handoff_payload_sha256": changed[
                        "handoff_payload_sha256"
                    ],
                }
            )
        )
        self.validator.validate(changed)
        self.assertEqual(
            SUPPORT.HANDOFF.validate_protected_legacy_effect_handoff(
                changed
            ),
            changed,
        )
        self.assertNotEqual(changed, self.sealed.document())
        self.sealed.assert_current()


if __name__ == "__main__":
    unittest.main()
