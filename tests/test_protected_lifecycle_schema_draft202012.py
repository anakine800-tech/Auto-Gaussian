#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the PR4K lifecycle Schema."""

from __future__ import annotations

import copy
import importlib.metadata
import json
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
INVOCATION_SCHEMA_PATH = (
    ROOT
    / "contracts/execution/protected-invocation-bundle.schema.json"
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
    from referencing import Registry, Resource
except ImportError as exc:
    Draft202012Validator = None  # type: ignore[assignment,misc]
    ValidationError = Exception  # type: ignore[assignment,misc]
    Registry = None  # type: ignore[assignment,misc]
    Resource = None  # type: ignore[assignment,misc]
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
        assert Registry is not None
        assert Resource is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.invocation_schema = json.loads(
            INVOCATION_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(cls.schema)
        Draft202012Validator.check_schema(cls.invocation_schema)
        registry = Registry().with_resource(
            "urn:auto-g16:protected-invocation-bundle:1",
            Resource.from_contents(cls.invocation_schema),
        )
        cls.validator = Draft202012Validator(
            cls.schema,
            registry=registry,
        )
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-lifecycle-schema-",
            dir=SUPPORT.TEST_TEMP_PARENT,
        )
        cls.fixture = SUPPORT.ProtectedLifecycleFixture(
            Path(cls.temporary.name).resolve()
        )
        cls.document = cls.fixture.owner().seal(
            cls.fixture.evidence
        ).document()

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
            SUPPORT.LIFECYCLE.validate_protected_lifecycle_contract(
                SUPPORT.LIFECYCLE.finalize(document)
            )

    def test_exact_dependencies_and_owner_output_validate(self) -> None:
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
            SUPPORT.LIFECYCLE.validate_protected_lifecycle_contract(
                self.document
            ),
            self.document,
        )

    def test_draft_integral_numbers_normalize_and_booleans_fail(self) -> None:
        paths = (
            ("ledger", "artifact_size_bytes"),
            ("ledger", "revision"),
            ("resources", "cores"),
            ("stage_plan", "artifact_count"),
        )
        for parent, field in paths:
            with self.subTest(field=f"{parent}.{field}"):
                draft = copy.deepcopy(self.document)
                for root in ("protected_invocation", "closure"):
                    draft[root][parent][field] = float(
                        draft[root][parent][field]
                    )
                self.validator.validate(draft)
                normalized = (
                    SUPPORT.LIFECYCLE
                    .validate_protected_lifecycle_contract(draft)
                )
                self.assertIsInstance(
                    normalized["closure"][parent][field],
                    int,
                )

                boolean = copy.deepcopy(self.document)
                for root in ("protected_invocation", "closure"):
                    boolean[root][parent][field] = True
                self.assert_both_reject(boolean)

    def test_unknown_fields_and_fixed_status_are_bidirectional(self) -> None:
        cases = []
        top = copy.deepcopy(self.document)
        top["unknown"] = False
        cases.append(top)
        nested = copy.deepcopy(self.document)
        nested["closure"]["unknown"] = False
        cases.append(nested)
        status = copy.deepcopy(self.document)
        status["status"]["reserved"] = True
        cases.append(status)
        effects = copy.deepcopy(self.document)
        effects["status"]["effects_performed"] = True
        cases.append(effects)
        retry = copy.deepcopy(self.document)
        retry["status"]["automatic_retry"] = True
        cases.append(retry)
        raw = copy.deepcopy(self.document)
        raw["status"]["raw_effect_owner_created"] = True
        cases.append(raw)
        for index, draft in enumerate(cases):
            with self.subTest(index=index):
                self.assert_both_reject(draft)

    def test_orders_are_closed_and_bidirectional(self) -> None:
        for field in (
            "protected_submit_order",
            "protected_invocation_order",
            "legacy_effect_sequence",
            "required_future_implementation_order",
            "effect_time_revalidation",
        ):
            with self.subTest(field=field):
                draft = copy.deepcopy(self.document)
                draft[field] = list(reversed(draft[field]))
                self.assert_both_reject(draft)
                extra = copy.deepcopy(self.document)
                extra[field].append("unexpected")
                self.assert_both_reject(extra)

    def test_unsafe_names_stage_topology_and_nonfinite_fail(self) -> None:
        unsafe = copy.deepcopy(self.document)
        for root in ("protected_invocation", "closure"):
            unsafe[root]["stage_plan"]["artifacts"][0][
                "relative_name"
            ] = "../unsafe.gjf"
        self.assert_both_reject(unsafe)

        reorder = copy.deepcopy(self.document)
        for root in ("protected_invocation", "closure"):
            artifacts = reorder[root]["stage_plan"]["artifacts"]
            artifacts[0], artifacts[1] = artifacts[1], artifacts[0]
        self.assert_both_reject(reorder)

        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                draft = copy.deepcopy(self.document)
                for root in ("protected_invocation", "closure"):
                    draft[root]["ledger"]["artifact_size_bytes"] = value
                self.assert_both_reject(draft)

    def test_duplicate_keys_are_rejected_before_either_validator(self) -> None:
        encoded = json.dumps(self.document, separators=(",", ":"))
        duplicate = encoded.replace(
            '"schema":"auto-g16-protected-lifecycle-contract/1"',
            (
                '"schema":"auto-g16-protected-lifecycle-contract/1",'
                '"schema":"auto-g16-protected-lifecycle-contract/1"'
            ),
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate key"):
            json.loads(
                duplicate,
                object_pairs_hook=reject_duplicate_pairs,
            )

    def test_semantic_splices_are_owner_rejected(self) -> None:
        cases = []
        identity = copy.deepcopy(self.document)
        identity["closure"]["identity"]["input_sha256"] = "0" * 64
        cases.append(identity)
        local = copy.deepcopy(self.document)
        local["closure"]["local_state"]["relative_local_dir"] = (
            "outputs/other/"
            + local["closure"]["identity"]["attempt_id"]
        )
        cases.append(local)
        stage = copy.deepcopy(self.document)
        stage["closure"]["stage_plan"]["artifacts"][0][
            "sha256"
        ] = "1" * 64
        cases.append(stage)
        for index, draft in enumerate(cases):
            with self.subTest(index=index):
                self.validator.validate(draft)
                with self.assertRaises(
                    SUPPORT.LIFECYCLE.ProtectedLifecycleError
                ):
                    SUPPORT.LIFECYCLE.validate_protected_lifecycle_contract(
                        SUPPORT.LIFECYCLE.finalize(draft)
                    )


if __name__ == "__main__":
    unittest.main()
