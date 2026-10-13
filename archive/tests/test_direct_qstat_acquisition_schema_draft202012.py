#!/usr/bin/env python3
"""Draft 2020-12 parity for reviewed qstat acquisition and final /3."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import unittest
from pathlib import Path

from tests import test_direct_qstat_acquisition as Q1_TESTS

import direct_qstat_acquisition as Q1
import direct_reviewed_read_profile as READ_PROFILE

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


ROOT = Path(__file__).parents[1]
EXPECTED_JSONSCHEMA_VERSION = "4.26.0"
REQUIRE_ENV = "AUTO_G16_REQUIRE_JSONSCHEMA"
INSTALLED_JSONSCHEMA_VERSION = importlib.metadata.version("jsonschema") if jsonschema is not None else None
EXACT_VALIDATOR_AVAILABLE = jsonschema is not None and INSTALLED_JSONSCHEMA_VERSION == EXPECTED_JSONSCHEMA_VERSION
if os.environ.get(REQUIRE_ENV) == "1" and not EXACT_VALIDATOR_AVAILABLE:
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; "
        f"installed jsonschema={INSTALLED_JSONSCHEMA_VERSION!r}"
    )


@unittest.skipUnless(EXACT_VALIDATOR_AVAILABLE, "real Draft 2020-12 checks require jsonschema==4.26.0")
class DirectQstatAcquisitionDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        assert jsonschema is not None
        self.fixture = Q1_TESTS.DirectQstatAcquisitionTests(
            "test_server_l1_lease_to_fixed_qstat_and_final_v3_success"
        )
        self.fixture.setUp()
        contracts = {
            "profile": "direct-reviewed-read-profile-capability.schema.json",
            "acquisition": "direct-qstat-acquisition.schema.json",
            "inspection": "gaussian-job-inspection-v3.schema.json",
        }
        self.validators = {}
        for name, filename in contracts.items():
            schema = json.loads(
                (ROOT / "contracts/direct-execution" / filename).read_text(encoding="utf-8")
            )
            jsonschema.Draft202012Validator.check_schema(schema)
            self.validators[name] = jsonschema.Draft202012Validator(schema)

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_owner_issued_profile_acquisition_and_final_v3_are_draft_valid(self) -> None:
        profile_capability = self.fixture.controller_profile_capability()
        profile_projection = profile_capability.portable_projection()
        self.validators["profile"].validate(profile_projection)
        lease, _raw, _projection = READ_PROFILE._consume_for_q1_once(profile_capability)
        lease.close_once()

        result, driver, transport = self.fixture.acquire(
            self.fixture.observation(
                stdout=self.fixture.present(project=self.fixture.receipt["project"])
            )
        )
        acquisition = result.portable_projection()
        self.validators["acquisition"].validate(acquisition)
        inspection = Q1.build_final_scheduler_inspection_once(result).document()
        self.validators["inspection"].validate(inspection)
        self.assertEqual(driver.calls, 1)
        self.assertEqual(transport.calls, 1)
        self.assertFalse(inspection["authority"]["authorizes_effect"])
        self.assertFalse(inspection["authority"]["gaussian_completion"])
        self.assertFalse(inspection["authority"]["scientific_acceptance"])

    def test_effect_mutations_fail_both_layers_and_cross_identity_fails_owner(self) -> None:
        profile_capability = self.fixture.controller_profile_capability()
        profile_projection = profile_capability.portable_projection()
        hostile_profile = copy.deepcopy(profile_projection)
        hostile_profile["authority"]["qsub"] = True
        self.assertFalse(self.validators["profile"].is_valid(hostile_profile))
        with self.assertRaises(READ_PROFILE.DirectReviewedReadProfileError):
            READ_PROFILE.validate_capability_projection(hostile_profile)
        for field, value in (
            ("qstat_executable_owner_uid", "501"),
            ("qstat_executable_mode", "0555"),
        ):
            hostile_profile = copy.deepcopy(profile_projection)
            hostile_profile[field] = value
            hostile_profile["projection_payload_sha256"] = ""
            hostile_profile["projection_payload_sha256"] = READ_PROFILE.digest(
                hostile_profile
            )
            self.assertFalse(self.validators["profile"].is_valid(hostile_profile))
            with self.assertRaises(READ_PROFILE.DirectReviewedReadProfileError):
                READ_PROFILE.validate_capability_projection(hostile_profile)

        result, _driver, _transport = self.fixture.acquire(
            self.fixture.observation(
                stdout=self.fixture.present(project=self.fixture.receipt["project"])
            )
        )
        acquisition = result.portable_projection()
        hostile_acquisition = copy.deepcopy(acquisition)
        hostile_acquisition["channel"]["server_read_profile_capability_id"] = (
            "direct-reviewed-read-profile-" + "f" * 64
        )
        self.assertTrue(self.validators["acquisition"].is_valid(hostile_acquisition))
        with self.assertRaises(Q1.DirectQstatAcquisitionError):
            Q1.validate_acquisition_projection(hostile_acquisition)

        rehashed_acquisition = copy.deepcopy(acquisition)
        rehashed_acquisition["acquisition_id"] = "direct-qstat-acquisition-" + "f" * 64
        rehashed_acquisition["acquisition_payload_sha256"] = ""
        rehashed_acquisition["acquisition_payload_sha256"] = Q1.digest(rehashed_acquisition)
        self.assertTrue(self.validators["acquisition"].is_valid(rehashed_acquisition))
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "acquisition id"):
            Q1.validate_acquisition_projection(rehashed_acquisition)

        inspection = Q1.build_final_scheduler_inspection_once(result).document()
        hostile_inspection = copy.deepcopy(inspection)
        hostile_inspection["scheduler"]["pbs_terminal_is_gaussian_completion"] = True
        self.assertFalse(self.validators["inspection"].is_valid(hostile_inspection))
        with self.assertRaises(Q1.DirectQstatAcquisitionError):
            Q1.validate_final_inspection(hostile_inspection)

        rehashed_inspection = copy.deepcopy(inspection)
        rehashed_inspection["inspection_id"] = "direct-scheduler-inspection-" + "f" * 64
        rehashed_inspection["evidence_sha256"] = ""
        rehashed_inspection["evidence_sha256"] = Q1.digest(rehashed_inspection)
        self.assertTrue(self.validators["inspection"].is_valid(rehashed_inspection))
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "inspection id"):
            Q1.validate_final_inspection(rehashed_inspection)


if __name__ == "__main__":
    unittest.main()
