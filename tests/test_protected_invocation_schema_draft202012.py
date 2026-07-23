#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the invocation successor Schema."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_invocation_contract as SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = (
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
class ProtectedInvocationDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-invocation-schema-",
            dir=SUPPORT.TEST_TEMP_PARENT,
        )
        self.fixture = SUPPORT.ProtectedInvocationFixture(
            Path(self.temporary.name).resolve()
        )
        self.document = self.fixture.owner().seal(
            self.fixture.evidence
        ).document()

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def with_topology(self, roles: tuple[str, ...]) -> dict:
        names = {
            "gaussian_input": "minimum.gjf",
            "companion_json": "minimum.json",
            "companion_xyz": "minimum.xyz",
            "old_checkpoint": "old.chk",
            "pbs_script": "safejob.pbs",
            "checksums_manifest": "checksums.sha256",
        }
        artifacts = []
        for order, role in enumerate(roles, start=1):
            artifact_hash = (
                self.document["identity"]["input_sha256"]
                if role == "gaussian_input"
                else hashlib.sha256(role.encode("utf-8")).hexdigest()
            )
            artifacts.append(
                {
                    "role": role,
                    "relative_name": names[role],
                    "order": order,
                    "sha256": artifact_hash,
                    "size_bytes": order,
                }
            )
        draft = copy.deepcopy(self.document)
        stage = draft["stage_plan"]
        stage["artifact_count"] = len(artifacts)
        stage["artifacts"] = artifacts
        stage["manifest_sha256"] = (
            SUPPORT.INVOCATION._compact_digest(
                {
                    "schema": stage["manifest_schema"],
                    "artifacts": artifacts,
                }
            )
        )
        seed = SUPPORT.INVOCATION.digest(
            {
                "schema": "auto-g16-protected-invocation-id/1",
                "protected_submit_bundle_payload_sha256": draft[
                    "predecessors"
                ]["protected_submit"]["bundle_payload_sha256"],
                "local_state_binding_payload_sha256": draft[
                    "predecessors"
                ]["local_state_binding"]["binding_payload_sha256"],
                "stage_manifest_sha256": stage["manifest_sha256"],
                "ledger_identity_sha256": draft["ledger"][
                    "ledger_identity_sha256"
                ],
            }
        )
        draft["invocation_id"] = f"protected-invocation-{seed}"
        return SUPPORT.INVOCATION.finalize(draft)

    def test_exact_dependencies_and_real_schema_validate(self) -> None:
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
                draft[parent][field] = float(draft[parent][field])
                self.validator.validate(draft)
                normalized = (
                    SUPPORT.INVOCATION
                    .validate_protected_invocation_bundle(draft)
                )
                self.assertIsInstance(normalized[parent][field], int)

                boolean = copy.deepcopy(self.document)
                boolean[parent][field] = True
                with self.assertRaises(ValidationError):
                    self.validator.validate(boolean)
                with self.assertRaises(
                    SUPPORT.INVOCATION.ProtectedInvocationError
                ):
                    (
                        SUPPORT.INVOCATION
                        .validate_protected_invocation_bundle(boolean)
                    )

    def test_schema_structure_and_owner_semantics_are_layered(self) -> None:
        structural = copy.deepcopy(self.document)
        structural["local_state"]["relative_local_dir"] = (
            "outputs/other/"
            f"{self.document['identity']['attempt_id']}"
        )
        structural["invocation_payload_sha256"] = (
            SUPPORT.INVOCATION.digest(
                {
                    key: value
                    for key, value in structural.items()
                    if key != "invocation_payload_sha256"
                }
            )
        )
        self.validator.validate(structural)
        with self.assertRaisesRegex(
            SUPPORT.INVOCATION.ProtectedInvocationError,
            "logical identity",
        ):
            (
                SUPPORT.INVOCATION
                .validate_protected_invocation_bundle(structural)
            )

    def test_stage_topology_schema_and_owner_acceptance_sets_match(self) -> None:
        allowed = (
            ("gaussian_input", "pbs_script", "checksums_manifest"),
            (
                "gaussian_input",
                "companion_json",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_xyz",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "old_checkpoint",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_json",
                "companion_xyz",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_json",
                "old_checkpoint",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_xyz",
                "old_checkpoint",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_json",
                "companion_xyz",
                "old_checkpoint",
                "pbs_script",
                "checksums_manifest",
            ),
        )
        for roles in allowed:
            with self.subTest(allowed=roles):
                candidate = self.with_topology(roles)
                self.validator.validate(candidate)
                SUPPORT.INVOCATION.validate_protected_invocation_bundle(
                    candidate
                )

        rejected = (
            (
                "gaussian_input",
                "companion_xyz",
                "companion_json",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_json",
                "companion_json",
                "pbs_script",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "pbs_script",
                "old_checkpoint",
                "checksums_manifest",
            ),
            (
                "gaussian_input",
                "companion_json",
                "companion_xyz",
                "old_checkpoint",
                "pbs_script",
                "checksums_manifest",
                "checksums_manifest",
            ),
        )
        for roles in rejected:
            with self.subTest(rejected=roles):
                candidate = self.with_topology(roles)
                with self.assertRaises(ValidationError):
                    self.validator.validate(candidate)
                with self.assertRaises(
                    SUPPORT.INVOCATION.ProtectedInvocationError
                ):
                    SUPPORT.INVOCATION.validate_protected_invocation_bundle(
                        candidate
                    )

        count_mismatch = self.with_topology(allowed[0])
        count_mismatch["stage_plan"]["artifact_count"] = 4
        count_mismatch = SUPPORT.INVOCATION.finalize(count_mismatch)
        with self.assertRaises(ValidationError):
            self.validator.validate(count_mismatch)
        with self.assertRaises(
            SUPPORT.INVOCATION.ProtectedInvocationError
        ):
            SUPPORT.INVOCATION.validate_protected_invocation_bundle(
                count_mismatch
            )

        absolute = copy.deepcopy(self.document)
        absolute["local_state"]["relative_local_dir"] = "/tmp/escape"
        with self.assertRaises(ValidationError):
            self.validator.validate(absolute)

    def test_schema_is_closed_and_portable(self) -> None:
        injected = copy.deepcopy(self.document)
        injected["local_dir"] = "/tmp/escape"
        with self.assertRaises(ValidationError):
            self.validator.validate(injected)
        with self.assertRaises(
            SUPPORT.INVOCATION.ProtectedInvocationError
        ):
            SUPPORT.INVOCATION.validate_protected_invocation_bundle(
                injected
            )
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
