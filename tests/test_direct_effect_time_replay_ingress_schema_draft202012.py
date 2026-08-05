#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for the direct replay ingress."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tests.test_direct_effect_time_replay_ingress import (  # noqa: E402
    DirectReplayIngressFixture,
)
import direct_effect_time_replay_ingress as INGRESS  # noqa: E402


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
    importlib.metadata.version("jsonschema") if jsonschema is not None else None
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
        f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}"
    )


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class DirectEffectTimeReplayIngressDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = DirectReplayIngressFixture()
        self.document = self.fixture.ingress().document()
        schema_path = (
            ROOT
            / "contracts/direct-execution/direct-effect-time-replay-ingress.schema.json"
        )
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert jsonschema is not None
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def tearDown(self) -> None:
        self.fixture.close()

    def test_exact_owner_projection_is_draft_valid_and_non_authorizing(self) -> None:
        self.validator.validate(self.document)
        self.assertEqual(
            INGRESS.validate_direct_effect_time_replay_ingress(self.document),
            self.document,
        )
        self.assertFalse(self.document["authority"]["transport_connected"])
        self.assertFalse(self.document["authority"]["live_ready"])
        self.assertFalse(self.document["authority"]["qsub_authorized"])
        self.assertFalse(
            self.document["policy"]["arbitrary_same_process_reflection_isolated"]
        )
        self.assertFalse(self.document["policy"]["production_closure"])

    def test_schema_and_owner_reject_hostile_rehashed_splices(self) -> None:
        cases = []
        changed = copy.deepcopy(self.document)
        changed["direct"]["profile"]["schema"] = "auto-g16-execution-profile/2"
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["direct"]["resources"]["cores"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["effect_time"]["resource_consume_order"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["authority"]["qsub_authorized"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["policy"]["arbitrary_same_process_reflection_isolated"] = True
        cases.append(changed)
        changed = copy.deepcopy(self.document)
        changed["predecessors"]["live_approval_effect_time_replay"]["owner"] = "foreign"
        cases.append(changed)
        for document in cases:
            projection = copy.deepcopy(document)
            projection["ingress_id"] = ""
            projection["ingress_payload_sha256"] = ""
            document["ingress_payload_sha256"] = INGRESS.digest(projection)
            document["ingress_id"] = "direct-effect-time-replay-ingress-" + INGRESS.digest(
                {
                    "schema": INGRESS.SCHEMA,
                    "binding_payload_sha256": document["direct"]["binding_payload_sha256"],
                    "resource_capability_id": document["predecessors"]["resource_effect_time_replay"]["capability_id"],
                    "live_capability_id": document["predecessors"]["live_approval_effect_time_replay"]["capability_id"],
                    "ingress_payload_sha256": document["ingress_payload_sha256"],
                }
            )
            with self.subTest(document=document):
                self.assertTrue(list(self.validator.iter_errors(document)))
                with self.assertRaises(INGRESS.DirectEffectTimeReplayIngressError):
                    INGRESS.validate_direct_effect_time_replay_ingress(document)


if __name__ == "__main__":
    unittest.main()
