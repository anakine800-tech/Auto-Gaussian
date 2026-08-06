#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for the existing-job lineage projection."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_direct_trusted_session_composition import PortableSessionFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_existing_job_lineage as LINEAGE  # noqa: E402
import direct_one_hop_transport as W5  # noqa: E402
import direct_trusted_session_composition as SESSION  # noqa: E402

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


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
class DirectExistingJobLineageSchemaDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert jsonschema is not None
        cls.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-schema-")
        cls.fixture = PortableSessionFixture(Path(cls.temporary.name).resolve())
        session = cls.fixture.compose()
        seam = SESSION.consume_w5_operation_seam_once(session.consume_for_w5_once())
        receipt = W5._consume_with_test_driver_once(
            seam,
            W5._test_driver(stdout=b"913.master\n"),
            _test_token=W5._TEST_DRIVER_TOKEN,
        ).portable_projection()
        owner = LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
            durable_state_root=cls.fixture.state,
            _test_token=LINEAGE._TEST_OWNER_TOKEN,
        )
        capability = owner.issue_once(W5.canonical_bytes(receipt), cls.fixture.artifacts)
        cls.document = capability.portable_projection()
        cls.lease = capability.consume_once()
        cls.schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-submitted-job-read-lineage.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(cls.schema)
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.lease.close_once()
        cls.fixture.close()
        cls.temporary.cleanup()

    def test_exact_owner_projection_is_draft_valid_and_non_authorizing(self) -> None:
        self.validator.validate(self.document)
        self.assertEqual(self.document, LINEAGE.validate_lineage_projection(self.document))
        self.assertFalse(self.document["authority"]["authorizes_effect"])
        self.assertFalse(self.document["authority"]["portable_projection_authorizes_read"])
        self.assertFalse(self.document["authority"]["scientific_acceptance"])

    def test_closed_objects_and_required_fields(self) -> None:
        assert jsonschema is not None
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(set(self.schema["required"]), set(self.schema["properties"]))
        for name in ("artifact_sha256", "binding", "durable", "descriptor_identity", "policy", "authority"):
            value = self.schema["properties"][name]
            self.assertEqual(value["type"], "object")
            self.assertFalse(value["additionalProperties"])
            self.assertEqual(set(value["required"]), set(value["properties"]))

    def test_every_artifact_zero_hash_rejects_schema_and_owner_after_result_rehash(self) -> None:
        for field in sorted(self.document["artifact_sha256"]):
            with self.subTest(field=field):
                hostile = copy.deepcopy(self.document)
                hostile["artifact_sha256"][field] = LINEAGE.ZERO_SHA
                hostile["result_payload_sha256"] = LINEAGE.digest(
                    {**hostile, "result_payload_sha256": ""}
                )
                self.assertFalse(self.validator.is_valid(hostile))
                with self.assertRaisesRegex(
                    LINEAGE.DirectExistingJobLineageError,
                    f"lineage artifact {field}",
                ):
                    LINEAGE.validate_lineage_projection(hostile)

    def test_unknown_const_pattern_and_hash_mutations_reject_schema_and_owner(self) -> None:
        mutations = (
            lambda value: value.__setitem__("unexpected", False),
            lambda value: value["authority"].__setitem__("authorizes_effect", True),
            lambda value: value["authority"].__setitem__("scientific_acceptance", True),
            lambda value: value["binding"].__setitem__("qsub_calls", "2"),
            lambda value: value["binding"].__setitem__("job_id", "913.master\n914.master"),
            lambda value: value["durable"].__setitem__("effective_outcome", "unknown"),
            lambda value: value["descriptor_identity"].__setitem__("project_sha256", "0" * 64),
        )
        for mutate in mutations:
            hostile = copy.deepcopy(self.document)
            mutate(hostile)
            hostile["result_payload_sha256"] = LINEAGE.digest(
                {**hostile, "result_payload_sha256": ""}
            )
            self.assertFalse(self.validator.is_valid(hostile))
            with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                LINEAGE.validate_lineage_projection(hostile)

        rederived = copy.deepcopy(self.document)
        rederived["lineage_id"] = "direct-submitted-job-read-" + "a" * 64
        rederived["result_payload_sha256"] = LINEAGE.digest(
            {**rederived, "result_payload_sha256": ""}
        )
        self.validator.validate(rederived)
        with self.assertRaisesRegex(
            LINEAGE.DirectExistingJobLineageError,
            "lineage id derivation",
        ):
            LINEAGE.validate_lineage_projection(rederived)


if __name__ == "__main__":
    unittest.main()
