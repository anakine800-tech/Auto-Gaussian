"""Historical lifecycle regressions through native owners; no remote acquisition."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.execution import program_runtime as runtime
from auto_g16.execution.readonly import ProgramReadQuery
from auto_g16.query import NativeQueryService, NativeSource, QueryError
from tests.v31.transport import test_program_completion as fixture
from tests.v3.query.test_execution_readonly import registration


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.CompletionTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.execute()
        self.reg = registration(self.f.snapshot)

    def read(self):
        return ProgramReadQuery(self.f.store).get_lifecycle(self.reg)

    def test_running_is_not_program_running_and_active_unknown_is_not_failure(self):
        self.f.driver.query_response = {'job_id': '123.server', 'state': 'running'}
        assessment = self.f.collect()
        self.assertEqual(assessment.data['verdict'], 'UNKNOWN')
        before = len(self.f.driver.calls)
        value = self.read()
        self.assertEqual(value['core_state'], 'RUNNING')
        self.assertEqual(value['scheduler']['state'], 'running')
        self.assertIsNone(value['scheduler']['raw_state'])
        self.assertIsNone(value['scheduler']['observed_at'])
        self.assertEqual(value['program']['state'], 'unknown')
        self.assertEqual(value['collection']['state'], 'pending')
        self.assertEqual(value['collection']['condition'], 'awaiting_scheduler_absence')
        self.assertEqual(len(self.f.driver.calls), before)
        self.assertEqual(ProgramReadQuery(self.f.store).get_summary(self.reg)['capture'], None)

    def test_completed_collected_absent_are_separate_and_detached(self):
        self.f.publish(); self.f.collect()
        before = len(self.f.driver.calls)
        with patch.object(fixture.completion, '_output_closure', side_effect=AssertionError('science')):
            value = self.read()
        self.assertEqual(value['program']['state'], 'completed')
        self.assertEqual(value['program']['completed_at'], '2026-09-14T01:02:03.000004Z')
        self.assertIsNone(value['program']['observed_at'])
        self.assertEqual(value['scheduler']['state'], 'absent')
        self.assertEqual(value['collection']['state'], 'collected')
        self.assertEqual(len(self.f.driver.calls), before)
        value['program']['evidence_refs'].clear()
        self.assertTrue(self.read()['program']['evidence_refs'])
        self.assertNotIn('content_base64', json.dumps(value))
        self.assertNotIn('/home/', json.dumps(value))

    def test_collected_bundle_before_core_transition(self):
        self.f.publish()
        advance = self.f.store.advance_attempt
        def stop(attempt, state):
            if state == core.AttemptState.SUCCEEDED:
                raise RuntimeError('injected before terminal transition')
            return advance(attempt, state)
        with patch.object(self.f.store, 'advance_attempt', side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.f.collect()
        value = self.read()
        self.assertEqual(value['core_state'], 'SUBMITTED')
        self.assertEqual(value['program']['state'], 'completed')
        self.assertEqual(value['collection']['state'], 'collected')

    def test_program_nonzero_does_not_erase_collection(self):
        self.f.publish(code=7); self.f.collect()
        value = self.read()
        self.assertEqual(value['program']['state'], 'failed')
        self.assertEqual(value['program']['exit_code'], 7)
        self.assertEqual(value['collection']['state'], 'collected')

    def test_latest_scheduler_unknown_replaces_known(self):
        self.f.driver.query_response = {'job_id': '123.server', 'state': 'running'}
        self.f.collect()
        self.f.driver.query_response = {'job_id': '123.server', 'state': 'unknown'}
        self.f.collect()
        value = self.read()
        self.assertEqual(value['scheduler']['state'], 'unknown')
        self.assertEqual(value['scheduler']['availability'], 'unavailable')
        self.assertEqual(value['core_state'], 'RUNNING')
        self.assertEqual(value['collection']['condition'], 'reconciliation_required')

    def test_active_forged_prefix_and_foreign_job_rejected(self):
        self.f.driver.query_response = {'job_id': '123.server', 'state': 'running'}
        assessment = self.f.collect()
        observations = self.f.store.observations_for_attempt('attempt-1')
        for field, wrong in [('observation_prefix_sha256', '0'*64), ('job_authority_id', 'foreign')]:
            data = dict(assessment.data); data[field] = wrong
            forged = replace(assessment, observation_id=runtime.semantic_id('program-completion-assessment', data), data=data)
            changed = tuple(forged if item == assessment else item for item in observations)
            with self.subTest(field=field), patch.object(self.f.store, 'observations_for_attempt', return_value=changed):
                with self.assertRaises(ValueError): self.read()

    def test_terminal_orphan_still_rejected(self):
        self.f.publish(); self.f.collect()
        with patch.object(self.f.store, 'results_for_attempt', return_value=()):
            with self.assertRaises(ValueError): self.read()

    def test_rehashed_read_before_submit_is_rejected_by_predecessor_order(self):
        self.f.driver.query_response = {'job_id': '123.server', 'state': 'running'}
        self.f.collect()
        old = self.f.store.observations_for_attempt('attempt-1')
        receipts = [r for r in old if r.observation_type == runtime._transport._RECEIPT_TYPE]
        query = next(r for r in receipts if r.data['operation'] == 'QUERY_SCHEDULER')
        submitted = next(r for r in receipts if r.data['operation'] == 'SUBMIT_QSUB_ONCE')
        receipts.remove(query)
        receipts.insert(receipts.index(submitted), query)
        changed = []
        for index, record in enumerate(receipts, 1):
            data = dict(record.data, effect_sequence=index)
            data['request_sha256'] = runtime._transport._digest(data['request'])
            changed.append(replace(record, observation_id=runtime._transport._identity('effect-receipt', data), data=data))
        # Reclose the active assessment too: failure must be the predecessor
        # order, not a stale outer digest or an accidentally missing prefix.
        assessment = old[-1]
        self.assertEqual(assessment.observation_type, runtime._COMPLETION_ASSESSMENT)
        prefix = tuple(r for r in old if r.observation_type not in
                       {runtime._transport._RECEIPT_TYPE, runtime._COMPLETION_ASSESSMENT}) + tuple(changed)
        data = dict(assessment.data, evidence_observation_ids=tuple(r.observation_id for r in changed),
                    observation_prefix_sha256=runtime._observation_prefix(prefix))
        changed_assessment = replace(assessment, observation_id=runtime.semantic_id('program-completion-assessment', data), data=data)
        with patch.object(self.f.store, 'observations_for_attempt', return_value=(*prefix, changed_assessment)):
            with self.assertRaisesRegex(ValueError, 'read precedes establishment'):
                self.read()

    def test_submitted_without_observation_has_no_inferred_program_state(self):
        value = self.read()
        self.assertEqual(value['scheduler']['availability'], 'missing')
        self.assertEqual(value['program']['state'], 'unknown')
        self.assertEqual(value['collection']['availability'], 'missing')

    def test_query_has_independent_schema_and_no_scientific_reads(self):
        self.f.driver.query_response = {'job_id': '123.server', 'state': 'running'}
        self.f.collect()
        query = NativeQueryService((NativeSource(source_id='one', database=self.f.store._connection.execute('PRAGMA database_list').fetchone()[2], snapshots=(self.reg,)),))
        with patch.object(query, '_attempt', side_effect=AssertionError('full scientific detail')):
            value = query.get_lifecycle('one', 'attempt-1')
        self.assertEqual(value['schema'], 'auto-g16-native-lifecycle-query/1')
        self.assertEqual(value['data']['availability'], 'available')
        self.assertEqual(value['data']['result']['scheduler']['state'], 'running')
        for source, attempt in [('other', 'attempt-1'), ('one', 'missing')]:
            with self.assertRaisesRegex(QueryError, 'not-found'):
                query.get_lifecycle(source, attempt)


if __name__ == '__main__':
    unittest.main()
