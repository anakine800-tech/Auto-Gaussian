#!/usr/bin/env python3
"""Draft 2020-12 parity for the trusted session closed result."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tests.test_direct_trusted_session_composition import PortableSessionFixture  # noqa: E402
import direct_trusted_session_composition as SESSION  # noqa: E402


try:
    import jsonschema
except ImportError:  # pragma: no cover - core profile intentionally lacks it
    jsonschema = None


class DirectTrustedSessionDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        if jsonschema is None or jsonschema.__version__ != "4.26.0":
            self.skipTest("real Draft 2020-12 checks require jsonschema==4.26.0")
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-session-schema-")
        self.fixture = PortableSessionFixture(Path(self.temporary.name).resolve())
        capability = self.fixture.compose()
        self.result = SESSION._session_ready_document(capability)
        self.lease = capability.consume_for_w5_once()
        self.lease.assert_current()
        self.schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-trusted-session-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def tearDown(self) -> None:
        if hasattr(self, "lease"):
            SESSION._retire_w5_lease_for_testing(
                self.lease,
                _test_token=SESSION._TEST_TOKEN,
            )
        if hasattr(self, "fixture"):
            self.fixture.close()
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def test_exact_result_is_draft_valid_and_non_authorizing(self) -> None:
        self.validator.validate(self.result)
        self.assertEqual(self.result, SESSION.validate_trusted_session_result(self.result))
        self.assertFalse(self.result["authority"]["authorizes_effect"])
        self.assertFalse(self.result["authority"]["transport_connected"])
        self.assertEqual(self.result["authority"]["qsub_calls"], 0)
        self.assertFalse(self.result["policy"]["production_closure"])

    def test_owner_and_schema_reject_bool_int_authority_and_unknown_fields(self) -> None:
        for path, replacement in (
            (("authority", "qsub_calls"), False),
            (("authority", "external_effects"), False),
            (("policy", "portable_artifacts_are_authority"), 0),
            (("durable_terminal_outcome",), "unknown"),
        ):
            hostile = copy.deepcopy(self.result)
            target = hostile
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            hostile["result_payload_sha256"] = ""
            hostile["result_payload_sha256"] = SESSION.digest(hostile)
            self.assertFalse(self.validator.is_valid(hostile))
            with self.assertRaises(SESSION.DirectTrustedSessionError):
                SESSION.validate_trusted_session_result(hostile)

    def test_four_identifiers_have_exact_owner_and_draft_pattern_parity(self) -> None:
        for field, prefix in (
            ("session_id", "direct-trusted-session-"),
            ("journal_id", "direct-durable-submission-journal-"),
            ("w3_ingress_id", "direct-effect-time-replay-ingress-"),
            ("w4_project_session_id", "direct-project-session-"),
        ):
            for label, replacement in (
                ("bool", False),
                ("short", prefix + "a" * 63),
                ("long", prefix + "a" * 65),
                ("uppercase", prefix + "A" * 64),
                ("nonhex", prefix + "g" * 64),
                ("suffix", prefix + "not-a-sha"),
            ):
                with self.subTest(field=field, mutation=label):
                    hostile = copy.deepcopy(self.result)
                    hostile[field] = replacement
                    hostile["result_payload_sha256"] = ""
                    hostile["result_payload_sha256"] = SESSION.digest(hostile)
                    self.assertFalse(self.validator.is_valid(hostile))
                    with self.assertRaises(SESSION.DirectTrustedSessionError):
                        SESSION.validate_trusted_session_result(hostile)


if __name__ == "__main__":
    unittest.main()
