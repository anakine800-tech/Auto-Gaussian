#!/usr/bin/env python3
"""Real Draft 2020-12 checks for the runtime/state successor Schemas."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_runtime_state_contract as SUPPORT


ROOT = Path(__file__).parents[1]
SCHEMA_PATHS = {
    "contract": ROOT / "contracts/execution/protected-runtime-state-contract.schema.json",
    "receipt": ROOT / "contracts/execution/protected-runtime-state-receipt.schema.json",
    "reconciliation": ROOT / "contracts/execution/protected-read-only-reconciliation-handoff.schema.json",
}
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
class ProtectedRuntimeStateDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert Draft202012Validator is not None
        cls.schemas = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in SCHEMA_PATHS.items()
        }
        for schema in cls.schemas.values():
            Draft202012Validator.check_schema(schema)
        cls.validators = {
            name: Draft202012Validator(schema)
            for name, schema in cls.schemas.items()
        }
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-runtime-state-schema-",
            dir=SUPPORT.TEST_TEMP_PARENT,
        )
        cls.root = Path(cls.temporary.name).resolve()
        cls.fixture = SUPPORT.RuntimeStateFixture(cls.root)
        cls.sealed = cls.fixture.owner().seal(cls.fixture.handoff())
        cls.contract = cls.sealed.document()
        cls.ready = cls.sealed.current_receipt.document()
        not_started = cls.sealed.consume_for_effect_once()
        cls.uncertain_sealed = cls.sealed.prepare_effect_boundary_once(
            not_started
        )
        cls.uncertain = cls.uncertain_sealed.document()
        cls.reconciliation_sealed = (
            SUPPORT.STATE.ProtectedReadOnlyReconciliationHandoffOwner
            .production()
            .seal(
                uncertain_receipt=cls.uncertain_sealed,
                evidence=SUPPORT.STATE.ProtectedReadOnlyReconciliationEvidence(
                    classification="definitely_not_submitted",
                    job_ids=(),
                    evidence_sha256="a" * 64,
                    observed_at="2030-01-01T12:03:00Z",
                ),
            )
        )
        cls.reconciliation = cls.reconciliation_sealed.document()
        cls.terminal = cls.sealed.accept_reconciliation_once(
            uncertain_receipt=cls.uncertain_sealed,
            reconciliation=cls.reconciliation_sealed,
        ).document()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.close()
        cls.temporary.cleanup()

    def assert_both_reject(
        self,
        kind: str,
        document: dict,
    ) -> None:
        with self.assertRaises(ValidationError):
            self.validators[kind].validate(document)
        validators = {
            "contract": SUPPORT.STATE.validate_protected_runtime_state_contract,
            "receipt": SUPPORT.STATE.validate_protected_runtime_state_receipt,
            "reconciliation": (
                SUPPORT.STATE
                .validate_protected_read_only_reconciliation_handoff
            ),
        }
        with self.assertRaises(SUPPORT.STATE.ProtectedRuntimeStateError):
            validators[kind](document)

    def rebind_successor_hashes(self, kind: str, document: dict) -> None:
        if kind == "contract":
            document["contract_payload_sha256"] = (
                SUPPORT.STATE._contract_payload_sha256(document)
            )
            document["contract_id"] = (
                "protected-runtime-state-"
                + SUPPORT.STATE.digest(
                    {
                        "schema": "auto-g16-protected-runtime-state-id/1",
                        "handoff_id": document["handoff"]["handoff_id"],
                        "attempt_id": document["identity"]["attempt_id"],
                        "runtime_binding_payload_sha256": document[
                            "runtime_binding"
                        ]["binding_payload_sha256"],
                        "journal_path_sha256": document["journal"][
                            "journal_path_sha256"
                        ],
                        "contract_payload_sha256": document[
                            "contract_payload_sha256"
                        ],
                    }
                )
            )
            document["journal"]["journal_id"] = (
                "protected-runtime-journal-"
                + SUPPORT.STATE.digest(
                    {
                        "schema": "auto-g16-protected-runtime-journal-id/1",
                        "contract_id": document["contract_id"],
                        "attempt_id": document["identity"]["attempt_id"],
                    }
                )
            )
        elif kind == "receipt":
            document["receipt_payload_sha256"] = SUPPORT.STATE._payload_sha256(
                document,
                id_field="receipt_id",
                payload_field="receipt_payload_sha256",
            )
            document["receipt_id"] = (
                "protected-runtime-receipt-"
                + SUPPORT.STATE.digest(
                    {
                        "schema": "auto-g16-protected-runtime-receipt-id/1",
                        "journal_id": document["journal_id"],
                        "sequence": document["sequence"],
                        "previous_receipt_sha256": document[
                            "previous_receipt_sha256"
                        ],
                        "receipt_payload_sha256": document[
                            "receipt_payload_sha256"
                        ],
                    }
                )
            )
        else:
            document["handoff_payload_sha256"] = SUPPORT.STATE._payload_sha256(
                document,
                id_field="handoff_id",
                payload_field="handoff_payload_sha256",
            )
            document["handoff_id"] = (
                "protected-read-only-reconciliation-"
                + SUPPORT.STATE.digest(
                    {
                        "schema": (
                            "auto-g16-protected-read-only-"
                            "reconciliation-id/1"
                        ),
                        "uncertain_receipt_payload_sha256": document[
                            "uncertain_receipt"
                        ]["receipt_payload_sha256"],
                        "evidence_sha256": document["observation"][
                            "evidence_sha256"
                        ],
                        "classification": document["observation"][
                            "classification"
                        ],
                        "handoff_payload_sha256": document[
                            "handoff_payload_sha256"
                        ],
                    }
                )
            )

    def test_exact_pins_schemas_and_owner_documents_validate(self) -> None:
        declared = {}
        for line in (
            ROOT / "requirements/schema-validation.lock.txt"
        ).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                name, version = line.split("==", 1)
                declared[name] = version
        self.assertEqual(declared, EXPECTED_PINS)
        documents = {
            "contract": self.contract,
            "receipt": self.ready,
            "reconciliation": self.reconciliation,
        }
        for kind, document in documents.items():
            with self.subTest(kind=kind):
                self.validators[kind].validate(document)
        for receipt in (self.ready, self.uncertain, self.terminal):
            self.validators["receipt"].validate(receipt)
            self.assertEqual(
                SUPPORT.STATE.validate_protected_runtime_state_receipt(
                    receipt
                ),
                receipt,
            )
        self.sealed.assert_current()

    def test_all_fixed_boolean_fields_reject_integer_zero_and_one(self) -> None:
        for field in SUPPORT.STATE.SCOPE:
            for replacement in (0, 1):
                with self.subTest(field=field, replacement=replacement):
                    changed = copy.deepcopy(self.contract)
                    changed["scope"][field] = replacement
                    self.assert_both_reject("contract", changed)
        for field in SUPPORT.STATE.POLICY:
            for replacement in (0, 1):
                with self.subTest(policy=field, replacement=replacement):
                    changed = copy.deepcopy(self.ready)
                    changed["policy"][field] = replacement
                    self.assert_both_reject("receipt", changed)

    def test_state_sequence_reconciliation_and_splice_boundaries(self) -> None:
        changed = copy.deepcopy(self.ready)
        changed["sequence"] = 2
        self.assert_both_reject("receipt", changed)
        changed = copy.deepcopy(self.uncertain)
        changed["reconciliation"] = copy.deepcopy(
            self.terminal["reconciliation"]
        )
        self.assert_both_reject("receipt", changed)
        changed = copy.deepcopy(self.reconciliation)
        changed["observation"]["job_ids"] = ["123.placeholder"]
        # Draft structure cannot express the classification-dependent job
        # cardinality; the semantic public validator owns this boundary.
        self.validators["reconciliation"].validate(changed)
        with self.assertRaises(SUPPORT.STATE.ProtectedRuntimeStateError):
            SUPPORT.STATE.validate_protected_read_only_reconciliation_handoff(
                changed
            )

    def test_required_unknown_short_long_lf_crlf_matrix(self) -> None:
        for kind, document in (
            ("contract", self.contract),
            ("receipt", self.ready),
            ("reconciliation", self.reconciliation),
        ):
            changed = copy.deepcopy(document)
            changed["unknown"] = None
            self.assert_both_reject(kind, changed)
        paths = (
            ("contract", self.contract, ("contract_id",)),
            (
                "contract",
                self.contract,
                ("handoff", "handoff_id"),
            ),
            (
                "contract",
                self.contract,
                ("handoff", "materialization_id"),
            ),
            (
                "contract",
                self.contract,
                ("identity", "invocation_id"),
            ),
            (
                "contract",
                self.contract,
                ("runtime_binding", "binding_payload_sha256"),
            ),
            ("receipt", self.ready, ("receipt_id",)),
            ("receipt", self.ready, ("handoff_id",)),
            ("receipt", self.ready, ("materialization_id",)),
            (
                "receipt",
                self.ready,
                ("receipt_payload_sha256",),
            ),
            (
                "receipt",
                self.terminal,
                ("reconciliation", "handoff_id"),
            ),
            (
                "reconciliation",
                self.reconciliation,
                ("handoff_id",),
            ),
            (
                "reconciliation",
                self.reconciliation,
                ("uncertain_receipt", "receipt_id"),
            ),
            (
                "reconciliation",
                self.reconciliation,
                ("uncertain_receipt", "journal_id"),
            ),
            (
                "reconciliation",
                self.reconciliation,
                ("uncertain_receipt", "contract_id"),
            ),
            (
                "reconciliation",
                self.reconciliation,
                ("uncertain_receipt", "attempt_id"),
            ),
        )
        for kind, source, path in paths:
            target = source
            for component in path:
                target = target[component]
            for replacement in (
                target[:-1],
                target + "0",
                target + "\n",
                target + "\r\n",
            ):
                changed = copy.deepcopy(source)
                changed_target = changed
                for component in path[:-1]:
                    changed_target = changed_target[component]
                changed_target[path[-1]] = replacement
                if (kind, path) not in {
                    ("contract", ("contract_id",)),
                    (
                        "contract",
                        ("runtime_binding", "binding_payload_sha256"),
                    ),
                    ("receipt", ("receipt_id",)),
                    ("receipt", ("receipt_payload_sha256",)),
                    ("reconciliation", ("handoff_id",)),
                }:
                    self.rebind_successor_hashes(kind, changed)
                with self.subTest(
                    kind=kind,
                    path=path,
                    replacement=repr(replacement),
                ):
                    self.assert_both_reject(kind, changed)

    def test_schema_and_public_validator_do_not_issue_owner_capability(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["runtime_binding"]["runtime_config_sha256"] = "f" * 64
        changed["runtime_binding"]["binding_payload_sha256"] = (
            SUPPORT.STATE.digest(
                {
                    key: item
                    for key, item in changed["runtime_binding"].items()
                    if key != "binding_payload_sha256"
                }
            )
        )
        changed["contract_payload_sha256"] = (
            SUPPORT.STATE._contract_payload_sha256(changed)
        )
        changed["contract_id"] = "protected-runtime-state-" + SUPPORT.STATE.digest(
            {
                "schema": "auto-g16-protected-runtime-state-id/1",
                "handoff_id": changed["handoff"]["handoff_id"],
                "attempt_id": changed["identity"]["attempt_id"],
                "runtime_binding_payload_sha256": changed[
                    "runtime_binding"
                ]["binding_payload_sha256"],
                "journal_path_sha256": changed["journal"][
                    "journal_path_sha256"
                ],
                "contract_payload_sha256": changed[
                    "contract_payload_sha256"
                ],
            }
        )
        changed["journal"]["journal_id"] = (
            "protected-runtime-journal-"
            + SUPPORT.STATE.digest(
                {
                    "schema": "auto-g16-protected-runtime-journal-id/1",
                    "contract_id": changed["contract_id"],
                    "attempt_id": changed["identity"]["attempt_id"],
                }
            )
        )
        self.validators["contract"].validate(changed)
        self.assertEqual(
            SUPPORT.STATE.validate_protected_runtime_state_contract(changed),
            changed,
        )
        self.assertNotEqual(changed, self.sealed.document())
        self.sealed.assert_current()


if __name__ == "__main__":
    unittest.main()
