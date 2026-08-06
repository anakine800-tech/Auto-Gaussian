#!/usr/bin/env python3
"""Draft 2020-12 parity for the shared fixed-SSH read profile."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.test_direct_trusted_session_composition import PortableSessionFixture

import direct_shared_fixed_ssh_channel as CHANNEL

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
class DirectSharedFixedSSHChannelDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        assert jsonschema is not None
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-shared-channel-schema-")
        self.fixture = PortableSessionFixture(Path(self.temporary.name).resolve())
        self.transport_raw = self.fixture.artifacts.transport_profile
        transport = CHANNEL.load_transport_profile(self.transport_raw)
        self.read_profile = {
            "schema": CHANNEL.READ_PROFILE_SCHEMA,
            "profile_id": "fixture-read-profile",
            "transport_binding": {
                "schema": "exact_w5_transport_profile_bytes/1",
                "transport_profile_bytes_sha256": hashlib.sha256(self.transport_raw).hexdigest(),
                "transport_profile_payload_sha256": transport["profile_payload_sha256"],
            },
            "server_read": {
                "source_sha256": CHANNEL._EXECUTED_SOURCE_SHA256,
                "qstat": {"executable": "/usr/bin/qstat", "executable_sha256": "a" * 64, "max_stdout_bytes": "4096", "timeout_seconds": "30"},
                "fetch": {"max_total_bytes": "1048576", "max_chunk_bytes": "65536", "max_chunks": "64", "timeout_seconds": "30"},
            },
            "safety": copy.deepcopy(CHANNEL.READ_POLICY),
            "read_profile_payload_sha256": "",
        }
        self.read_profile["read_profile_payload_sha256"] = CHANNEL.digest(self.read_profile)
        schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-shared-fixed-ssh-read-profile.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        self.validator = jsonschema.Draft202012Validator(schema)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def test_read_profile_is_draft_valid_owner_valid_and_non_authorizing(self) -> None:
        self.validator.validate(self.read_profile)
        self.assertEqual(
            self.read_profile,
            CHANNEL.validate_read_profile(self.read_profile, self.transport_raw),
        )
        self.assertFalse(self.read_profile["safety"]["authorizes_effect"])
        self.assertEqual(self.read_profile["safety"]["qsub_calls"], "0")

    def test_unknown_identity_copy_effect_and_noncanonical_limits_fail_both_layers(self) -> None:
        mutations = (
            lambda value: value.__setitem__("host", "caller.invalid"),
            lambda value: value["transport_binding"].__setitem__("user", "caller"),
            lambda value: value["safety"].__setitem__("authorizes_effect", True),
            lambda value: value["server_read"]["qstat"].__setitem__("max_stdout_bytes", True),
            lambda value: value["server_read"]["fetch"].__setitem__("max_chunks", "01"),
        )
        for mutate in mutations:
            hostile = copy.deepcopy(self.read_profile)
            mutate(hostile)
            hostile["read_profile_payload_sha256"] = ""
            hostile["read_profile_payload_sha256"] = CHANNEL.digest(hostile)
            self.assertFalse(self.validator.is_valid(hostile))
            with self.assertRaises((CHANNEL.SharedFixedSSHChannelError, TypeError)):
                CHANNEL.validate_read_profile(hostile, self.transport_raw)


if __name__ == "__main__":
    unittest.main()
