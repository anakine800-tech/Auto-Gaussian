"""Real Core/Transport stores and native lock; synthetic effects only."""
from unittest.mock import patch

from auto_g16 import core
from auto_g16.execution import _presubmit_recovery as recovery
from auto_g16.transport import program as transport
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport import test_program_completion as completion
from tests.v31.transport import test_program_composition as composition


class PreSubmitRecoveryTests(lane.LaneAFixture):
    profile = completion.CompletionTests.profile
    resolved = completion.CompletionTests.resolved
    completion_spec = completion.CompletionTests.completion_spec
    completion_snapshot = completion.CompletionTests.completion_snapshot
    # These helpers use super(), so explicitly construct the equivalent fixture.
    def profile(self, **kwargs):
        from dataclasses import replace
        p = super().profile(**kwargs)
        return replace(p, runtime_contents={**p.runtime_contents, completion.completion._DEPLOYMENT_NAME:
                       completion.completion._receipt_json(completion.manifest())})

    def setUp(self):
        super().setUp()
        root = self.root / 'transport'
        root.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(root / 'program.sqlite3', approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.snapshot = self.completion_snapshot()
        self.driver = composition._Driver()
        self.input_bytes = {'input.xyz': lane.XYZ}
        self.scheduler_bytes = {'xtb.pbs': self.snapshot.scheduler_artifacts[0]['content_utf8'].encode()}

    execute = composition.ProgramCompositionTests.execute

    def stop(self, operation='STAGE_EXACT_FILE'):
        self.driver.raise_operation = (operation, transport._ProgramEffectUnknown('synthetic transport loss'))
        self.execute()
        self.stopped = self.store.observations_for_attempt('attempt-1')[-1].observation_id
        self.decision = {'reviewer_id':'synthetic-owner','evidence':'explicit recovery approval', 'attempt_id':'attempt-1',
                         'snapshot_id':self.snapshot.program_execution_snapshot_id,'decision':'reconcile-not-submitted'}

    def recover(self, **kwargs):
        return recovery.reconcile(self.store, snapshot=self.snapshot, program_transport_store=self.program_transport_store,
                                  driver=self.driver, stopped_receipt_id=kwargs.pop('receipt', self.stopped),
                                  decision=kwargs.pop('decision', self.decision), **kwargs)

    def test_local_recovery_replay_and_explicit_child(self):
        self.stop()
        history = self.store.observations_for_attempt('attempt-1')
        calls = list(self.driver.calls)
        proof = self.recover()
        self.assertEqual(self.store.attempt_state('attempt-1'), core.AttemptState.NOT_SUBMITTED)
        self.assertEqual(self.store.observations_for_attempt('attempt-1')[:-1], history)
        self.assertEqual(self.recover(), proof)
        self.assertEqual(self.driver.calls, calls)
        self.store.create_child_attempt('attempt-1', core.Attempt(attempt_id='child', task_id='task-1', ordinal=2))
        self.assertEqual(self.store.parent_attempt_id('child'), 'attempt-1')
        self.assertEqual(self.store.attempt_state('child'), core.AttemptState.PLANNED)
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent('attempt-1', 'new-intent')

    def test_crash_after_proof_allows_only_local_replay(self):
        self.stop()
        calls = list(self.driver.calls)
        with patch.object(self.store, 'reconcile_unknown', side_effect=RuntimeError('crash')):
            with self.assertRaisesRegex(RuntimeError, 'crash'):
                self.recover()
        self.assertEqual(self.store.attempt_state('attempt-1'), core.AttemptState.UNKNOWN)
        self.recover()
        self.assertEqual(self.driver.calls, calls)
        self.assertEqual(sum(o.observation_type==recovery.PROOF for o in self.store.observations_for_attempt('attempt-1')),1)

    def test_assessment_has_no_persistence_or_effect(self):
        self.stop()
        prior = self.store.observations_for_attempt('attempt-1')
        calls = list(self.driver.calls)
        self.recover(apply=False)
        self.assertEqual(self.store.observations_for_attempt('attempt-1'),prior)
        self.assertEqual(self.store.attempt_state('attempt-1'),core.AttemptState.UNKNOWN)
        self.assertEqual(self.driver.calls,calls)

    def test_submit_unknown_rejected(self):
        self.stop('SUBMIT_QSUB_ONCE')
        with self.assertRaises(transport.TransportBoundaryError): self.recover()
        self.assertEqual(self.store.attempt_state('attempt-1'), core.AttemptState.UNKNOWN)

    def test_allocation_unknown_rejected(self):
        self.stop('ALLOCATE_WORKSPACE')
        with self.assertRaises(transport.TransportBoundaryError): self.recover()

    def test_wrong_stopped_receipt_rejected(self):
        self.stop()
        with self.assertRaises(transport.TransportBoundaryError): self.recover(receipt='wrong')

    def test_wrong_decision_rejected(self):
        self.stop()
        with self.assertRaises(transport.TransportBoundaryError): self.recover(decision={**self.decision,'attempt_id':'other'})

    def test_missing_physical_effect_rejected(self):
        self.stop()
        db = self.program_transport_store._connection
        triggers = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='program_effect_physical_authority'").fetchall()
        for name, _ in triggers:
            db.execute('DROP TRIGGER "'+name+'"')
        db.execute("DELETE FROM program_effect_physical_authority WHERE operation='STAGE_EXACT_FILE'")
        for _, sql in triggers:
            db.execute(sql)
        db.commit()
        with self.assertRaises(transport.TransportBoundaryError): self.recover()

    def test_extra_physical_effect_rejected(self):
        self.stop()
        last = self.store.observations_for_attempt('attempt-1')[-1].data
        self.program_transport_store.record_effect(binding=last['request']['binding'],request=last['request'],classification='FAILED',response={'reason':'extra'})
        with self.assertRaisesRegex(transport.TransportBoundaryError,'physical effect history'): self.recover()

    def test_decision_drift_after_proof_rejected(self):
        self.stop(); self.recover()
        with self.assertRaises(transport.TransportBoundaryError): self.recover(decision={**self.decision,'evidence':'different'})

    def test_second_stage_unknown_can_recover(self):
        original = self.driver.stage_exact_file
        def stage(request, content):
            if request['payload']['portable_name']=='xtb.pbs':
                self.driver._record('STAGE_EXACT_FILE', request)
                raise transport._ProgramEffectUnknown('last-stage loss')
            return original(request, content)
        self.driver.stage_exact_file = stage
        self.execute()
        self.stopped = self.store.observations_for_attempt('attempt-1')[-1].observation_id
        self.decision = {'reviewer_id':'owner','evidence':'approved','attempt_id':'attempt-1',
                         'snapshot_id':self.snapshot.program_execution_snapshot_id,'decision':'reconcile-not-submitted'}
        self.recover()
        self.assertEqual(self.store.attempt_state('attempt-1'),core.AttemptState.NOT_SUBMITTED)
