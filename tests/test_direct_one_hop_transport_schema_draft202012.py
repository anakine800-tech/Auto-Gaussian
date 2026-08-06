#!/usr/bin/env python3
"""Draft 2020-12 parity for the closed W5 transport contracts."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.test_direct_trusted_session_composition import PortableSessionFixture

import direct_one_hop_transport as W5

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


ROOT = Path(__file__).parents[1]
EXPECTED_JSONSCHEMA_VERSION = "4.26.0"
REQUIRE_ENV = "AUTO_G16_REQUIRE_JSONSCHEMA"
INSTALLED_JSONSCHEMA_VERSION = (
    importlib.metadata.version("jsonschema") if jsonschema is not None else None
)
EXACT_VALIDATOR_AVAILABLE = (
    jsonschema is not None and INSTALLED_JSONSCHEMA_VERSION == EXPECTED_JSONSCHEMA_VERSION
)
if os.environ.get(REQUIRE_ENV) == "1" and not EXACT_VALIDATOR_AVAILABLE:
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; "
        f"installed jsonschema={INSTALLED_JSONSCHEMA_VERSION!r}"
    )


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class DirectOneHopTransportDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        assert jsonschema is not None
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-w5-schema-")
        self.fixture = PortableSessionFixture(Path(self.temporary.name).resolve())
        capability = self.fixture.compose()
        lease = capability.consume_for_w5_once()
        seam = W5.SESSION.consume_w5_operation_seam_once(lease)
        self.binding = seam.direct_binding.document()
        self.allowed_root = seam.allowed_root
        self.script = seam.pbs_script_bytes
        receipt = W5._consume_with_test_driver_once(
            seam,
            W5._test_driver(stdout=b"123.master\n"),
            _test_token=W5._TEST_DRIVER_TOKEN,
        )
        self.result = receipt.portable_projection()
        result_schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-one-hop-submission-result.schema.json").read_text(encoding="utf-8")
        )
        profile_schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-one-hop-transport-profile.schema.json").read_text(encoding="utf-8")
        )
        review_schema = json.loads(
            (ROOT / "contracts/direct-execution/reviewed-direct-pbs-script.schema.json").read_text(encoding="utf-8")
        )
        self.validator = jsonschema.Draft202012Validator(result_schema)
        self.profile_validator = jsonschema.Draft202012Validator(profile_schema)
        self.review_validator = jsonschema.Draft202012Validator(review_schema)
        for schema in (result_schema, profile_schema, review_schema):
            jsonschema.Draft202012Validator.check_schema(schema)
        self.profile = json.loads(self.fixture.artifacts.transport_profile)
        self.review = json.loads(self.fixture.artifacts.pbs_review)

    def tearDown(self) -> None:
        if hasattr(self, "fixture"):
            self.fixture.close()
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def test_exact_projection_is_draft_valid_owner_valid_and_non_authorizing(self) -> None:
        self.validator.validate(self.result)
        self.assertEqual(self.result, W5.validate_submission_receipt(self.result))
        self.assertFalse(self.result["authority"]["authorizes_effect"])
        self.assertFalse(self.result["qsub"]["raw_stdout_included"])

    def test_unknown_fields_bool_int_job_injection_and_raw_stdout_fail_closed(self) -> None:
        mutations = (
            lambda value: value.__setitem__("extra", True),
            lambda value: value["qsub"].__setitem__("calls", True),
            lambda value: value["qsub"].__setitem__("job_id", "1.master\n2.master"),
            lambda value: value["outcome"].__setitem__("raw_stdout", "1.master\\n"),
            lambda value: value["authority"].__setitem__("authorizes_effect", True),
        )
        for mutate in mutations:
            hostile = copy.deepcopy(self.result)
            mutate(hostile)
            hostile["result_payload_sha256"] = W5.digest({**hostile, "result_payload_sha256": ""})
            self.assertFalse(self.validator.is_valid(hostile))
            with self.assertRaises(W5.DirectOneHopTransportError):
                W5.validate_submission_receipt(hostile)

    def test_profile_and_review_are_draft_valid_and_owner_valid(self) -> None:
        self.profile_validator.validate(self.profile)
        self.review_validator.validate(self.review)
        self.assertEqual(self.profile, W5.validate_transport_profile(self.profile))

    def test_profile_safety_and_review_semantics_are_closed(self) -> None:
        hostile_profile = copy.deepcopy(self.profile)
        hostile_profile["safety"]["inspect"] = True
        hostile_profile["profile_payload_sha256"] = W5.digest(
            {**hostile_profile, "profile_payload_sha256": ""}
        )
        self.assertFalse(self.profile_validator.is_valid(hostile_profile))
        with self.assertRaises(W5.DirectOneHopTransportError):
            W5.validate_transport_profile(hostile_profile)

        hostile_review = copy.deepcopy(self.review)
        hostile_review["gaussian"]["invocation"] = "stdin_redirection"
        self.assertFalse(self.review_validator.is_valid(hostile_review))

    def test_every_portable_integer_position_rejects_float_bool_and_noncanonical_decimal(self) -> None:
        positive_hostiles = (1.0, True, "01", "-0", "1\n")
        zero_hostiles = (0.0, False, "00", "-0", "0\n")

        for path in (("ssh", "port"), ("pbs_artifact", "size_bytes"), ("safety", "qsub_max_calls")):
            for hostile_value in positive_hostiles:
                with self.subTest(schema="profile", path=path, value=repr(hostile_value)):
                    hostile = copy.deepcopy(self.profile)
                    hostile[path[0]][path[1]] = hostile_value
                    hostile["profile_payload_sha256"] = W5.digest(
                        {**hostile, "profile_payload_sha256": ""}
                    )
                    self.assertFalse(self.profile_validator.is_valid(hostile))
                    with self.assertRaises((W5.DirectOneHopTransportError, TypeError)):
                        W5.validate_transport_profile(hostile)

        for path in (
            ("script", "size_bytes"),
            ("resources", "cores"),
            ("resources", "memory_gb"),
            ("resources", "walltime_seconds"),
        ):
            for hostile_value in positive_hostiles:
                with self.subTest(schema="pbs-review", path=path, value=repr(hostile_value)):
                    hostile = copy.deepcopy(self.review)
                    hostile[path[0]][path[1]] = hostile_value
                    hostile["review_payload_sha256"] = W5.digest(
                        {**hostile, "review_payload_sha256": ""}
                    )
                    profile = copy.deepcopy(self.profile)
                    profile["pbs_artifact"]["review_payload_sha256"] = hostile["review_payload_sha256"]
                    self.assertFalse(self.review_validator.is_valid(hostile))
                    with self.assertRaises((W5.DirectOneHopTransportError, TypeError)):
                        W5._validate_pbs_review(
                            W5.canonical_bytes(hostile),
                            self.script,
                            self.binding,
                            profile,
                            self.allowed_root,
                        )

        receipt_cases = (
            ("qsub.calls", positive_hostiles),
            ("invocation.call_count", positive_hostiles),
            ("outcome.returncode", zero_hostiles),
            ("uploaded.size_bytes", positive_hostiles),
        )
        for path, hostile_values in receipt_cases:
            for hostile_value in hostile_values:
                with self.subTest(schema="receipt", path=path, value=repr(hostile_value)):
                    hostile = copy.deepcopy(self.result)
                    if path == "qsub.calls":
                        hostile["qsub"]["calls"] = hostile_value
                    elif path == "invocation.call_count":
                        hostile["invocation"]["call_count"] = hostile_value
                        hostile["invocation"]["invocation_payload_sha256"] = W5.digest(
                            {key: item for key, item in hostile["invocation"].items() if key != "invocation_payload_sha256"}
                        )
                        hostile["qsub"]["invocation_payload_sha256"] = hostile["invocation"]["invocation_payload_sha256"]
                    elif path == "outcome.returncode":
                        hostile["outcome"]["returncode"] = hostile_value
                        hostile["outcome"]["outcome_payload_sha256"] = W5.digest(
                            {key: item for key, item in hostile["outcome"].items() if key != "outcome_payload_sha256"}
                        )
                        hostile["qsub"]["outcome_payload_sha256"] = hostile["outcome"]["outcome_payload_sha256"]
                    else:
                        hostile["uploaded"][0]["size_bytes"] = hostile_value
                    hostile["result_payload_sha256"] = W5.digest(
                        {**hostile, "result_payload_sha256": ""}
                    )
                    self.assertFalse(self.validator.is_valid(hostile))
                    with self.assertRaises((W5.DirectOneHopTransportError, TypeError)):
                        W5.validate_submission_receipt(hostile)


if __name__ == "__main__":
    unittest.main()
