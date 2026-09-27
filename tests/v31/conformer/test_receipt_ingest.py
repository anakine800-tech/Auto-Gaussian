"""Receipt-backed CREST ingestion closes both native sources without effects."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from auto_g16 import core
from auto_g16.conformer import ingest
from auto_g16.conformer.models import ConformerError, _plain_value, _identified_payload
from auto_g16.conformer.service import build_conformer_ensemble, create_sampling_profile
from auto_g16.execution import program_runtime as runtime
from auto_g16.execution import _crest_seed_handoff as handoffs
from tests.v31.conformer import test_crest_receipt_handoff as seed_tests
from tests.v3.execution import test_v31_lane_a as lane


class ReceiptIngestTests(unittest.TestCase):
    def setUp(self):
        self.source = seed_tests.ReceiptSeedTests()
        original_profile = seed_tests.profile3
        def all_atom_profile():
            data = _plain_value(original_profile()._identity_payload())
            data.pop('schema_version')
            # H2 has no heavy atoms; this synthetic fixture needs all-atom RMSD.
            data['rmsd_policy']['atom_selection'] = 'all'
            # The reused C/O/dihedral descriptors do not apply to H2.
            data['descriptor_policy'] = []
            return create_sampling_profile(**data)
        with patch.object(seed_tests, 'profile3', side_effect=all_atom_profile):
            self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.source.execute(); self.source.publish(); self.source.collect()
        self.handoff = self.source.readonly_build()
        self.target, self.snapshot, self.fixed = self.source.destination(self.handoff)
        self.target.snapshot = self.snapshot
        self.target.spec = self.snapshot.program_execution_spec
        self.target.scheduler_bytes = {a['portable_name']: a['content_utf8'].encode()
                                       for a in self.snapshot.scheduler_artifacts}
        frame = ('  2\n' + f'  {-1.0:18.8f}\n' +
                 ''.join(f' H  {x:20.10f}{y:20.10f}{z:20.10f}\n'
                         for x,y,z in ((0,0,0),(0,0,0.74)))).encode()
        self.target.driver.outputs.update({'crest_best.xyz': frame, 'crest_conformers.xyz': frame})
        with patch.object(handoffs, '_FIXED_RECEIPT_SUBMISSION', self.fixed):
            self.target.execute()
        self.target.publish()
        self.assertEqual(self.target.collect().data['diagnostic'], 'completed')

    def args(self):
        return dict(profile=self.source.sampling, program_execution_snapshot=self.snapshot,
                    core_store=self.target.store, program_transport_store=self.target.program_transport_store,
                    preoptimization_handoff=self.handoff, xtb_core_store=self.source.store,
                    xtb_program_execution_snapshot=self.source.snapshot,
                    xtb_program_transport_store=self.source.program_transport_store,
                    crest_exact_input_bytes=lane.XYZ, descriptors_by_member_index=None,
                    validation_driver=self.target.driver, xtb_validation_driver=self.source.driver)

    def read(self, **changes):
        def state():
            return tuple((f.store.observations_for_attempt(f.snapshot.attempt_id),
                          f.store.results_for_attempt(f.snapshot.attempt_id),
                          f.store.attempt_state(f.snapshot.attempt_id), len(f.driver.calls))
                         for f in (self.source,self.target))
        before = state()
        try:
            with patch.object(core.SQLiteRuntimeStore, 'append_observation', side_effect=AssertionError('write')), \
                 patch.object(core.SQLiteRuntimeStore, 'append_result', side_effect=AssertionError('write')):
                return ingest._ingest_receipt_crest_conformers_xyz(**{**self.args(), **changes})
        finally:
            self.assertEqual(before, state())

    def test_receipt_import_ensemble_and_json_identity_retention(self):
        observations = self.read()
        self.assertEqual(observations, self.read())
        self.assertEqual(len(observations), 1)
        ensemble = build_conformer_ensemble(project_id='crest-project', calculation_plan_id='crest-plan',
            calculation_plan_revision=1, profile=self.source.sampling, observations=observations)
        raw = json.dumps(_plain_value(ensemble._identity_payload()), sort_keys=True, allow_nan=False)
        self.assertEqual(_identified_payload('conformer-ensemble', json.loads(raw)),
                         (ensemble.conformer_ensemble_id, ensemble.payload_sha256))
        self.assertEqual(len(ensemble.members), 1)
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_seed_profile_handoff_and_destination_splices_reject(self):
        from tests.v31.conformer.test_core import ConformerCoreTests
        for change in ({'crest_exact_input_bytes':lane.XYZ+b'\n'}, {'preoptimization_handoff':None},
                       {'profile':ConformerCoreTests().profile()},
                       {'program_execution_snapshot':self.source.snapshot}):
            with self.subTest(change=tuple(change)), self.assertRaises(ConformerError):
                self.read(**change)

    def test_later_source_unknown_invalidates_import(self):
        self.source.driver.query_response={'job_id':'123.server','state':'unknown'}
        runtime._query_program_scheduler(self.source.store, **self.source.kwargs())
        with self.assertRaises(ConformerError): self.read()

    def test_later_destination_unknown_invalidates_import(self):
        self.target.driver.query_response={'job_id':'123.server','state':'unknown'}
        runtime._query_program_scheduler(self.target.store, **self.target.kwargs())
        with self.assertRaises(ConformerError): self.read()

    def test_wrong_persisted_plan_handoff_rejects(self):
        plan=self.target.store.load_calculation_plan('crest-plan')
        with patch.object(self.target.store, 'load_calculation_plan', return_value=replace(plan, intent={})), self.assertRaises(ConformerError):
            self.read()

    def test_legacy_entry_does_not_bypass_receipt_authority(self):
        raw=self.target.driver.outputs['crest_conformers.xyz']
        from tests.v31.conformer.test_ingest import CrestIngestTests
        with self.assertRaisesRegex(ConformerError,'v2 adapter'):
            ingest._ingest_crest_conformers_xyz(profile=self.source.sampling,
                program_execution_snapshot=self.snapshot, core_store=self.target.store,
                artifact_binding=CrestIngestTests.artifact(self.snapshot,raw), artifact_bytes=raw,
                descriptors_by_member_index=None)


class ReadonlyReconciliationTests(lane.LaneAFixture):
    def setUp(self):
        super().setUp()
        from types import SimpleNamespace
        self.bound_snapshot = SimpleNamespace(attempt_id='attempt-1')
        self.receipt = core.Observation(observation_id='reconciled-job', attempt_id='attempt-1',
            observation_type='synthetic-reconciliation', data={})
        self.store.append_observation(self.receipt)
        self.store._connection.execute("UPDATE attempts SET state='UNKNOWN' WHERE attempt_id='attempt-1'")
        self.store.reconcile_unknown('attempt-1', self.receipt.observation_id, core.ReconciliationResolution.SUBMITTED)
        self.store.advance_attempt('attempt-1', core.AttemptState.SUCCEEDED)

    def read_reconciliation(self):
        before = self.store._connection.total_changes
        self.store._connection.execute('PRAGMA query_only=ON')
        token = runtime._READONLY_RECEIPT_SOURCE.set(self.store)
        try:
            with patch.object(self.store, 'reconcile_unknown', side_effect=AssertionError('write transaction')):
                return runtime._replay_submitted_reconciliation(self.store, self.bound_snapshot, self.receipt)
        finally:
            runtime._READONLY_RECEIPT_SOURCE.reset(token)
            self.assertEqual(before, self.store._connection.total_changes)
            self.store._connection.execute('PRAGMA query_only=OFF')

    def test_exact_existing_reconciliation_is_read_without_transaction(self):
        self.assertEqual(self.read_reconciliation(), core.AttemptState.SUCCEEDED)

    def test_missing_or_spliced_terminal_reconciliation_rejects(self):
        from auto_g16.transport._canonical import TransportBoundaryError
        for query in (
            "UPDATE reconciliations SET resolution='UNRESOLVED'",
            "UPDATE reconciliations SET resolution='NOT_SUBMITTED'",
        ):
            self.store._connection.execute(query)
            with self.assertRaises(TransportBoundaryError): self.read_reconciliation()
        self.store._connection.execute("UPDATE reconciliations SET resolution='SUBMITTED'")
        old = self.receipt
        self.receipt = replace(old, observation_id='other-receipt')
        with self.assertRaises(TransportBoundaryError): self.read_reconciliation()

    def test_normal_runtime_still_uses_public_core_replay(self):
        with patch.object(self.store, 'reconcile_unknown', wraps=self.store.reconcile_unknown) as replay:
            self.assertEqual(runtime._replay_submitted_reconciliation(self.store, self.bound_snapshot, self.receipt), core.AttemptState.SUCCEEDED)
        replay.assert_called_once_with('attempt-1', 'reconciled-job', core.ReconciliationResolution.SUBMITTED)
