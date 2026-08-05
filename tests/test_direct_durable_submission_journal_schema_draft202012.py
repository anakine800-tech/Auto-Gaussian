#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for the direct durable journal snapshot."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_direct_durable_submission_journal import DirectDurableSubmissionJournalTests


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import direct_durable_submission_journal as JOURNAL  # noqa: E402

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

installed_jsonschema = importlib.metadata.version("jsonschema") if jsonschema is not None else None
EXACT_VALIDATOR_AVAILABLE = jsonschema is not None and installed_jsonschema == EXPECTED_JSONSCHEMA_VERSION
if REQUIRE_JSONSCHEMA and not EXACT_VALIDATOR_AVAILABLE:
    detail = f"installed jsonschema={installed_jsonschema!r}" if JSONSCHEMA_IMPORT_ERROR is None else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    raise RuntimeError(f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}")


@unittest.skipUnless(EXACT_VALIDATOR_AVAILABLE, "real Draft 2020-12 checks require jsonschema==4.26.0")
class DirectDurableSubmissionJournalDraft202012Tests(unittest.TestCase):
    def setUp(self) -> None:
        support = DirectDurableSubmissionJournalTests(methodName="runTest")
        support.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-direct-draft-")
        self.addCleanup(support.temporary.cleanup)
        support.local_state_dir = Path(support.temporary.name).resolve()
        support.binding = support.build_binding()
        self.binding = support.binding
        self.local_state_dir = support.local_state_dir
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        JOURNAL.record_outcome_once(claim, outcome="completed", evidence_sha256="a" * 64)
        self.snapshot = JOURNAL.reconcile_read_only(self.local_state_dir, claim.journal_id, self.binding).document()
        schema_path = ROOT / "contracts/direct-execution/direct-durable-submission-journal.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert jsonschema is not None
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def test_owner_snapshot_is_schema_valid_and_non_authorizing(self) -> None:
        self.validator.validate(self.snapshot)
        self.assertFalse(self.snapshot["policy"]["portable_document_authorizes_effect"])
        self.assertFalse(self.snapshot["policy"]["qsub_authorized"])
        self.assertFalse(self.snapshot["reconciliation"]["mutation_performed"])

    def test_schema_and_owner_reject_outcome_policy_chain_and_type_drift(self) -> None:
        candidates: list[tuple[dict[str, object], bool]] = []
        changed = copy.deepcopy(self.snapshot)
        changed["effective_outcome"] = "unknown"
        candidates.append((changed, True))
        changed = copy.deepcopy(self.snapshot)
        changed["policy"]["automatic_retry"] = True
        candidates.append((changed, True))
        changed = copy.deepcopy(self.snapshot)
        changed["events"][1]["previous_event_sha256"] = "b" * 64
        candidates.append((changed, False))
        changed = copy.deepcopy(self.snapshot)
        changed["events"][1]["sequence"] = True
        candidates.append((changed, True))
        changed = copy.deepcopy(self.snapshot)
        changed["identity"]["unexpected"] = "x"
        candidates.append((changed, True))
        changed = copy.deepcopy(self.snapshot)
        changed["identity"]["attempt_id"] = "different-attempt"
        candidates.append((changed, True))
        for document, schema_must_reject in candidates:
            with self.subTest(document=document):
                document = JOURNAL._finalize(document, "journal_payload_sha256")
                schema_errors = list(self.validator.iter_errors(document))
                if schema_must_reject:
                    self.assertTrue(schema_errors)
                else:
                    # Draft 2020-12 cannot express equality between two dynamic
                    # instance values. The owner remains authoritative for the
                    # started-event-to-terminal hash-chain comparison.
                    self.assertFalse(schema_errors)
                with self.assertRaises(JOURNAL.DirectDurableJournalError):
                    JOURNAL.validate_durable_journal_snapshot(document)


if __name__ == "__main__":
    unittest.main()
