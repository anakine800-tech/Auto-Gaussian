#!/usr/bin/env python3
"""Pinned Draft 2020-12 checks for the effect-time replay Schema."""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

REQUIRE_JSONSCHEMA = os.environ.get("AUTO_G16_REQUIRE_JSONSCHEMA") == "1"
try:
    import jsonschema
except ImportError:
    jsonschema = None

from tests import test_live_approval_effect_time_replay as SUPPORT  # noqa: E402


SCHEMA_PATH = (
    ROOT
    / "contracts/live-approval-replay/"
    "live-approval-effect-time-replay.schema.json"
)


@unittest.skipIf(
    jsonschema is None and not REQUIRE_JSONSCHEMA,
    "jsonschema is not installed",
)
class LiveApprovalEffectTimeReplayDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        if jsonschema is None:
            self.fail(
                "AUTO_G16_REQUIRE_JSONSCHEMA=1 requires pinned jsonschema"
            )
        self.support = SUPPORT.LiveApprovalEffectTimeReplayTests(
            "test_structural_validation_never_issues_a_capability"
        )
        self.support.setUp()
        self.schema = json.loads(
            SCHEMA_PATH.read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def tearDown(self) -> None:
        self.support.tearDown()

    def test_owner_issued_projection_is_draft_2020_12_valid(self) -> None:
        document = self.support.capability().document()
        self.validator.validate(document)

    def test_schema_and_owner_both_reject_effect_or_authority_drift(self) -> None:
        document = self.support.capability().document()
        cases = (
            ("qsub", ("effect_boundary", "qsub_calls"), 1),
            (
                "authorizing",
                ("effect_boundary", "non_authorizing"),
                False,
            ),
            (
                "multi-use",
                ("replay", "single_use"),
                False,
            ),
            (
                "revoked",
                ("approval_artifact", "revocation", "revoked"),
                True,
            ),
        )
        for label, path, replacement in cases:
            changed = copy.deepcopy(document)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            with self.subTest(label=label):
                self.assertTrue(
                    list(self.validator.iter_errors(changed)),
                    "Draft validator accepted a fixed boundary drift",
                )
                with self.assertRaises(Exception):
                    sys.modules[
                        "live_approval_effect_time_replay"
                    ].validate_live_approval_effect_time_replay(changed)

    def test_fixed_bool_int_acceptance_matches_semantic_owner(self) -> None:
        document = self.support.capability().document()
        owner = sys.modules["live_approval_effect_time_replay"]
        for section, field, expected in SUPPORT.FIXED_BOOL_INT_FIELDS:
            for replacement in SUPPORT.BOOL_INT_SPLICES:
                changed = copy.deepcopy(document)
                changed[section][field] = replacement
                SUPPORT.reseal_projection(changed)
                schema_accepts = not list(
                    self.validator.iter_errors(changed)
                )
                try:
                    owner.validate_live_approval_effect_time_replay(
                        changed
                    )
                    owner_accepts = True
                except SUPPORT.REPLAY.LiveApprovalEffectTimeReplayError:
                    owner_accepts = False
                exact = (
                    type(replacement) is type(expected)
                    and replacement == expected
                )
                with self.subTest(
                    section=section,
                    field=field,
                    replacement=repr(replacement),
                    replacement_type=type(replacement).__name__,
                ):
                    self.assertEqual(schema_accepts, exact)
                    self.assertEqual(owner_accepts, exact)
                    self.assertEqual(owner_accepts, schema_accepts)

    def test_schema_valid_document_does_not_mint_owner_capability(self) -> None:
        document = self.support.capability().document()
        self.validator.validate(document)
        with self.assertRaises(TypeError):
            sys.modules[
                "live_approval_effect_time_replay"
            ].PreQsubLiveApprovalReplayCapability()


if __name__ == "__main__":
    unittest.main()
