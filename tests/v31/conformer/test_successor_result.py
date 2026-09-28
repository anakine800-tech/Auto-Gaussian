"""Exact-byte successor parsing and pure Opt classification, without live effects."""
from hashlib import sha256
import unittest
from dataclasses import replace

from auto_g16.result._successor import parse_source, require_pair, append_pair, payload_hash, SOURCE, PARSED
from auto_g16.result.models import ProvenanceConflictError, NS_PARSED_RESULT, _identity
from auto_g16.core import Result
from auto_g16.scientific_validation._successor_opt import assess_opt
from tests.v3.scientific_validation._fixtures import initialized_core
from tests.v3.result.test_gaussian_job import LINES


def opt_log():
    return b"\n".join((LINES[0], *LINES[5:10], *LINES[27:33],
                        b" 2 1 0 0.0 0.0 1.0", b" 3 1 0 1.0 0.0 0.0",
                        LINES[34], *LINES[10:17], LINES[36])) + b"\n"


def source_payload(raw):
    return {
        "schema": SOURCE, "attempt_id": "attempt-1", "calculation_plan_id": "plan-1",
        "calculation_plan_revision": 1, "program_execution_snapshot_id": "snapshot-1",
        "snapshot_payload_sha256": "1"*64, "effect_intent_id": "intent-1",
        "program_execution_spec_id": "spec-1", "spec_payload_sha256": "2"*64,
        "terminal_success_authority_id": "proof-1", "completion_result_id": "completion-1",
        "completion_result_payload_sha256": "3"*64, "capture_authority_id": "capture-1",
        "assessment_observation_id": "assessment-1", "receipt_sha256": "4"*64, "epoch_id": "epoch-1",
        "input": {"logical_role": "gaussian-input", "portable_name": "flow.gjf", "format": "gaussian-gjf",
                  "sha256": "5"*64, "size_bytes": 1, "stage_observation_id": "stage-1"},
        "log": {"logical_role": "program-log", "portable_name": "gaussian.log", "format": "text",
                "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw), "fetch_observation_id": "fetch-1"},
    }


class SuccessorResultTests(unittest.TestCase):
    def test_opt_bytes_and_frequency_pending_assessment(self):
        raw = opt_log()
        source, result, envelope, parsed = parse_source(source_payload(raw), raw)
        self.assertEqual(result.data['parse_status'], 'parsed')
        geometry, assessment = assess_opt(envelope, parsed)
        self.assertEqual(len(geometry['atoms']), 3)
        self.assertEqual(assessment['classification'], 'INCOMPLETE')
        self.assertEqual(assessment['reason_codes'], ('incomplete-mode-count',))
        self.assertEqual(assessment['geometry_disposition'], 'accepted_opt_geometry')
        self.assertEqual((source, result), parse_source(source_payload(raw), raw)[:2])

    def test_byte_drift_and_incomplete_content(self):
        raw = opt_log()
        with self.assertRaises(ProvenanceConflictError):
            parse_source(source_payload(raw), raw+b'x')
        truncated = raw[:-55]
        _, result, envelope, parsed = parse_source(source_payload(truncated), truncated)
        geometry, assessment = assess_opt(envelope, parsed)
        self.assertIsNone(geometry)
        self.assertEqual(assessment['geometry_disposition'], 'rejected_opt_geometry')

    def test_explicit_partial_pair_completion_and_rehashed_forgery(self):
        store = initialized_core()
        self.addCleanup(store.close)
        raw = opt_log()
        source, result, _, _ = parse_source(source_payload(raw), raw)
        store.append_observation(source)
        with self.assertRaises(ProvenanceConflictError):
            require_pair(store, source, result)
        append_pair(store, source, result)
        append_pair(store, source, result)
        self.assertEqual(len(store.results_for_attempt('attempt-1')), 1)
        # Store forged facts under their correctly recomputed semantic identity.
        # The reader must reject them against original-byte replay, not a hash check.
        forged_data = {**result.data, 'facts': {}}
        forged = replace(result, result_id=_identity(NS_PARSED_RESULT,
                         ('v31-gaussian-parsed-result', payload_hash(forged_data))), data=forged_data)
        corrupted = initialized_core()
        self.addCleanup(corrupted.close)
        corrupted.append_observation(source)
        corrupted.append_result(forged)
        with self.assertRaises(ProvenanceConflictError):
            require_pair(corrupted, source, result)

    def test_orphan_conflict_and_mixed_generation(self):
        raw = opt_log()
        source, result, _, _ = parse_source(source_payload(raw), raw)
        store = initialized_core()
        self.addCleanup(store.close)
        store.append_result(result)
        with self.assertRaises(ProvenanceConflictError):
            append_pair(store, source, result)
        other = initialized_core()
        self.addCleanup(other.close)
        other.append_result(Result(result_id='legacy', attempt_id='attempt-1',
                                   result_type='v30-result-parse-outcome', data={}))
        with self.assertRaises(ProvenanceConflictError):
            append_pair(other, source, result)
