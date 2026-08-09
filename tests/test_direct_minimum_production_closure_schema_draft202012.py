#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for the terminal fetch grant."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import pathlib
import sys
import unittest

import tests.test_direct_qstat_acquisition as Q1_TESTS


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
installed = importlib.metadata.version("jsonschema") if jsonschema else None
AVAILABLE = jsonschema is not None and installed == EXPECTED_JSONSCHEMA_VERSION
if REQUIRE_JSONSCHEMA and not AVAILABLE:
    detail = (
        f"installed jsonschema={installed!r}"
        if JSONSCHEMA_IMPORT_ERROR is None
        else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    )
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}"
    )


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import direct_minimum_production_closure as CLOSURE  # noqa: E402
import direct_qstat_acquisition as Q1  # noqa: E402


@unittest.skipUnless(AVAILABLE, "real Draft 2020-12 checks require jsonschema==4.26.0")
class DirectMinimumProductionClosureSchemaDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        assert jsonschema is not None
        schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-terminal-fetch-grant.schema.json")
            .read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        self.validator = jsonschema.Draft202012Validator(schema)
        resume_schema = json.loads(
            (ROOT / "contracts/direct-execution/direct-minimum-resume-result.schema.json")
            .read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(resume_schema)
        self.resume_validator = jsonschema.Draft202012Validator(resume_schema)
        self.q1 = Q1_TESTS.DirectQstatAcquisitionTests(methodName="runTest")
        self.q1.setUp()

    def tearDown(self) -> None:
        self.q1.tearDown()

    def grant(self) -> dict[str, object]:
        stdout = (
            f"Job Id: {self.q1.receipt['qsub']['job_id']}\n"
            f"    Job_Name = {self.q1.receipt['project']}\n"
            "    job_state = C\n"
        ).encode("ascii")
        acquisition, _, _ = self.q1.acquire(self.q1.observation(stdout=stdout))
        inspection = Q1.build_final_scheduler_inspection_once(acquisition)
        return CLOSURE.issue_terminal_fetch_grant_once(inspection).portable_projection()

    def test_real_draft_accepts_exact_owner_projection(self) -> None:
        document = self.grant()
        self.validator.validate(document)
        self.assertEqual(
            CLOSURE.validate_terminal_fetch_grant_projection(document), document
        )

    def test_rehashed_nonterminal_unknown_extra_and_authority_upgrade_reject_both(self) -> None:
        source = self.grant()
        mutations: list[dict[str, object]] = []
        for field, value in (
            ("state", "running"),
            ("freshness", "stale"),
            ("terminal_fetch_allowed", False),
        ):
            changed = copy.deepcopy(source)
            changed["classification"][field] = value  # type: ignore[index]
            mutations.append(changed)
        changed = copy.deepcopy(source)
        changed["authority"]["retry"] = True  # type: ignore[index]
        mutations.append(changed)
        changed = copy.deepcopy(source)
        changed["unexpected"] = False
        mutations.append(changed)
        for changed in mutations:
            changed["grant_payload_sha256"] = ""
            changed["grant_payload_sha256"] = CLOSURE.digest(changed)
            with self.assertRaises(jsonschema.ValidationError):
                self.validator.validate(changed)
            with self.assertRaises(CLOSURE.DirectMinimumProductionClosureError):
                CLOSURE.validate_terminal_fetch_grant_projection(changed)

    def test_real_draft_accepts_query_union_and_rejects_authority_upgrade(self) -> None:
        stdout = (
            f"Job Id: {self.q1.receipt['qsub']['job_id']}\n"
            f"    Job_Name = {self.q1.receipt['project']}\n"
            "    job_state = Q\n"
        ).encode("ascii")
        acquisition, _, _ = self.q1.acquire(self.q1.observation(stdout=stdout))
        inspection = Q1.build_final_scheduler_inspection_once(acquisition)
        inspection_document, grant = CLOSURE._ROUTE_INSPECTION_ONCE(inspection)
        self.assertIsNone(grant)
        document = CLOSURE._resume_result(
            self.q1.receipt_raw,
            self.q1.receipt,
            "query_nonterminal",
            inspection_document,
            None,
            None,
        )
        self.resume_validator.validate(document)
        self.assertEqual(CLOSURE.validate_minimum_resume_result(document), document)
        hostile = copy.deepcopy(document)
        hostile["authority"]["this_call_qsub_calls"] = "1"
        hostile["result_payload_sha256"] = ""
        hostile["result_payload_sha256"] = CLOSURE.digest(hostile)
        with self.assertRaises(jsonschema.ValidationError):
            self.resume_validator.validate(hostile)
        with self.assertRaises(CLOSURE.DirectMinimumProductionClosureError):
            CLOSURE.validate_minimum_resume_result(hostile)
        switched = copy.deepcopy(document)
        switched["status"] = "query_unknown"
        switched["result_payload_sha256"] = ""
        switched["result_payload_sha256"] = CLOSURE.digest(switched)
        with self.assertRaises(jsonschema.ValidationError):
            self.resume_validator.validate(switched)
        with self.assertRaises(CLOSURE.DirectMinimumProductionClosureError):
            CLOSURE.validate_minimum_resume_result(switched)
        offline_materialized = copy.deepcopy(document)
        offline_materialized["status"] = "materialized"
        offline_materialized["terminal_fetch_grant"] = self.grant()
        offline_materialized["materialization_manifest"] = {
            "stream": {"stream_mode": "offline_synthetic"},
            "authority": {
                "remote_fetch_performed": False,
                "scheduler_inspection_performed": False,
            },
            "integration": {"production_integration": False},
        }
        offline_materialized["authority"]["fetch_performed"] = True
        offline_materialized["authority"]["local_materialization_performed"] = True
        offline_materialized["authority"]["explicit_future_query_required"] = False
        offline_materialized["result_payload_sha256"] = ""
        offline_materialized["result_payload_sha256"] = CLOSURE.digest(
            offline_materialized
        )
        with self.assertRaises(jsonschema.ValidationError):
            self.resume_validator.validate(offline_materialized)


if __name__ == "__main__":
    unittest.main()
