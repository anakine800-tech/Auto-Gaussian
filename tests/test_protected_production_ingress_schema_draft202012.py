#!/usr/bin/env python3
"""Pinned Draft 2020-12 tests for production-ingress Schema."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import test_protected_production_ingress_contract as SUPPORT


try:
    import jsonschema
except ImportError:
    jsonschema = None


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts/execution/"
    "protected-production-ingress-contract.schema.json"
)


@unittest.skipIf(
    jsonschema is None,
    "jsonschema is not installed in the current profile",
)
class ProtectedProductionIngressSchemaDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert jsonschema is not None
        cls.validator = jsonschema.Draft202012Validator(
            cls.schema,
            format_checker=jsonschema.FormatChecker(),
        )
        cls.validator.check_schema(cls.schema)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-production-ingress-schema-",
            dir=SUPPORT.TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = SUPPORT.RuntimeStateFixture(self.root)
        runtime = self.fixture.owner().seal(self.fixture.handoff())
        predecessor = (
            SUPPORT.CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .prepare_once(runtime)
        )
        self.sealed = (
            SUPPORT.INGRESS.ProtectedProductionIngressContractOwner.production()
            .seal_once(predecessor)
        )
        self.document = self.sealed.document()

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def test_real_draft_accepts_owner_document(self) -> None:
        self.validator.validate(self.document)
        self.assertEqual(
            SUPPORT.INGRESS.validate_protected_production_ingress_contract(
                self.document
            ),
            self.document,
        )

    def test_real_draft_and_owner_reject_closed_structure_matrix(self) -> None:
        cases = []
        extra = copy.deepcopy(self.document)
        extra["unexpected"] = False
        cases.append(extra)
        missing = copy.deepcopy(self.document)
        del missing["predecessor"]
        cases.append(missing)
        bad_bool = copy.deepcopy(self.document)
        bad_bool["scope"]["write"] = 0
        cases.append(bad_bool)
        bad_bool_true = copy.deepcopy(self.document)
        bad_bool_true["legacy_factory_port"]["factory_invoked"] = True
        cases.append(bad_bool_true)
        false_seal_claim = copy.deepcopy(self.document)
        false_seal_claim["validation"]["schema_valid_is_sealed"] = True
        cases.append(false_seal_claim)
        overstated_threat = copy.deepcopy(self.document)
        overstated_threat["threat_model"][
            "post_check_arbitrary_same_process_mutation_prevented"
        ] = True
        cases.append(overstated_threat)
        bad_pattern = copy.deepcopy(self.document)
        bad_pattern["contract_id"] += "\n"
        cases.append(bad_pattern)
        unsafe_file = copy.deepcopy(self.document)
        unsafe_file["legacy_factory_port"]["plan_inputs"]["files"][0] = (
            "../forged"
        )
        cases.append(unsafe_file)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(jsonschema.ValidationError):
                    self.validator.validate(changed)
                with self.assertRaises(
                    SUPPORT.INGRESS.ProtectedProductionIngressError
                ):
                    SUPPORT.INGRESS.validate_protected_production_ingress_contract(
                        changed
                    )

    def test_all_integer_fields_have_draft_helper_acceptance_parity(
        self,
    ) -> None:
        for field in SUPPORT.PUBLIC_INTEGER_FIELDS:
            with self.subTest(field=field, representation="exact-int"):
                self.validator.validate(self.document)
                normalized = (
                    SUPPORT.INGRESS
                    .validate_protected_production_ingress_contract(
                        copy.deepcopy(self.document)
                    )
                )
                self.assertIs(
                    type(SUPPORT.get_public_integer(normalized, field)),
                    int,
                )

            integral = copy.deepcopy(self.document)
            SUPPORT.set_public_integer(
                integral,
                field,
                float(SUPPORT.get_public_integer(integral, field)),
            )
            SUPPORT.reclose_public_document(integral)
            with self.subTest(field=field, representation="integral-float"):
                self.validator.validate(integral)
                normalized = (
                    SUPPORT.INGRESS
                    .validate_protected_production_ingress_contract(integral)
                )
                self.assertEqual(normalized, self.document)
                self.assertIs(
                    type(SUPPORT.get_public_integer(normalized, field)),
                    int,
                )

            for label, replacement in (
                ("bool", True),
                ("fractional", 1.5),
                ("zero", 0),
                ("negative", -1),
                ("nan", float("nan")),
                ("positive-infinity", float("inf")),
                ("negative-infinity", float("-inf")),
            ):
                changed = copy.deepcopy(self.document)
                SUPPORT.set_public_integer(
                    changed,
                    field,
                    replacement,
                )
                if label not in {
                    "nan",
                    "positive-infinity",
                    "negative-infinity",
                }:
                    SUPPORT.reclose_public_document(changed)
                with self.subTest(field=field, representation=label):
                    self.assertFalse(self.validator.is_valid(changed))
                    with self.assertRaises(
                        SUPPORT.INGRESS.ProtectedProductionIngressError
                    ):
                        (
                            SUPPORT.INGRESS
                            .validate_protected_production_ingress_contract(
                                changed
                            )
                        )

    def test_schema_validity_does_not_issue_owner_seal(self) -> None:
        self.validator.validate(self.document)
        structural = copy.deepcopy(self.document)
        self.assertIsInstance(structural, dict)
        self.assertFalse(
            isinstance(
                structural,
                SUPPORT.INGRESS.SealedProtectedProductionIngressCapability,
            )
        )
        with self.assertRaises(TypeError):
            SUPPORT.INGRESS.SealedProtectedProductionIngressCapability(
                structural
            )


if __name__ == "__main__":
    if (
        os.environ.get("AUTO_G16_REQUIRE_JSONSCHEMA") == "1"
        and jsonschema is None
    ):
        raise SystemExit("jsonschema is required but unavailable")
    unittest.main()
