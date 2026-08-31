"""Offline product-level proof of the complete V30-A minimum chain."""

from __future__ import annotations

import copy
from dataclasses import replace
from hashlib import sha256
import threading
import unittest
from unittest import mock

import auto_g16.approval as approval
import auto_g16.core as core
import auto_g16.execution as execution
import auto_g16.observe as observe
import auto_g16.result as result
import auto_g16.review as review
import auto_g16.scientific_validation as scientific_validation
import auto_g16.transport as transport
import auto_g16.workflow as workflow
from tests.v3.execution.test_execution import INPUT_BYTES, TEMPLATE_BYTES

from ._fixtures import FakeDriver, NOW, TORQUE_RESOURCE_DESCRIPTOR_BYTES, TransportFixture, found, qstat, response
from .test_execution import execution_successes


DISPLAYED_MEANING = {
    "job": "closed-shell minimum optimization and frequencies",
    "method": "B3LYP/6-31G(d)",
}

# A grammar-valid, single-job, nonlinear three-atom minimum.  It is immutable
# test evidence, not a replacement parser or a scientific-policy shortcut.
MINIMUM_GAUSSIAN_BYTES = "\n".join(
    (
        " Entering Gaussian System, Link 0=g16",
        " Symbolic Z-matrix:",
        " Charge = 0 Multiplicity = 1",
        " H",
        " GradGradGrad",
        " Input orientation:",
        " -----",
        " Center Atomic Atomic Coordinates (Angstroms)",
        " Number Number Type X Y Z",
        " -----",
        " 1 8 0 0 0 0",
        " 2 1 0 0 0 0",
        " 3 1 0 0 0 0",
        " -----",
        " Item Value Threshold Converged?",
        " Maximum Force 0 0 YES",
        " RMS Force 0 0 YES",
        " Maximum Displacement 0 0 YES",
        " RMS Displacement 0 0 YES",
        " Optimization completed.",
        " -- Stationary point found.",
        " Harmonic frequencies (cm**-1), IR intensities (KM/Mole), Raman scattering",
        " activities (A**4/AMU), depolarization ratios for plane and unpolarized",
        " incident light, reduced masses (AMU), force constants (mDyne/A),",
        " and normal coordinates:",
        " 1 2 3",
        " A A A",
        " Frequencies -- 1 2 3",
        " Red. masses -- 1 1 1",
        " Frc consts -- 1 1 1",
        " IR Inten -- 0 0 0",
        " Normal termination of Gaussian 16",
    )
).encode("ascii")


class V30ASyntheticCompositionTests(TransportFixture):
    """Compose public authorities while keeping all mechanics synthetic."""

    def setUp(self) -> None:
        super().setUp()
        process_patcher = mock.patch("subprocess.Popen")
        self.process_spy = process_patcher.start()
        self.addCleanup(process_patcher.stop)
        self.addCleanup(self.process_spy.assert_not_called)
        self.approval_store = approval.SQLiteApprovalStore(
            self.temporary / "approval.sqlite3"
        )
        self.addCleanup(self.approval_store.close)
        self.workflow_store = workflow.SQLiteWorkflowStore.create_new(
            self.temporary / "workflow.sqlite3"
        )
        self.addCleanup(self.workflow_store.close)
        self.validation_store = scientific_validation.SQLiteScientificValidationStore.create_new(
            self.temporary / "scientific-validation.sqlite3"
        )
        self.addCleanup(self.validation_store.close)

    def _workflow_ready(self, runtime_store: core.SQLiteRuntimeStore) -> workflow.WorkflowRunView:
        definition = workflow.WorkflowDefinition(
            schema_version=1,
            workflow_run_id="run-1",
            workflow_name="minimum",
            nodes=(
                workflow.Node(
                    node_id="node-1",
                    task_id="task-1",
                    calculation_plan_id="plan-1",
                    calculation_plan_revision=3,
                    node_kind="gaussian-minimum",
                    input_roles=(),
                    output_roles=("result",),
                ),
            ),
        )
        workflow.record_workflow_definition(
            self.workflow_store, runtime_store, definition
        )
        view = workflow.replay_workflow(
            self.workflow_store,
            runtime_store,
            definition.workflow_definition_id,
            workflow.WorkflowEvaluationInput(
                workflow_definition_id=definition.workflow_definition_id,
                node_attempt_ids={},
            ),
        )
        self.assertEqual(view.active_node_ids, ("node-1",))
        self.assertEqual(view.ready_node_ids, ("node-1",))
        self.assertEqual(view.pending_node_ids, ())
        self.assertEqual(view.blocked_node_ids, ())
        return view

    def _approval_chain(
        self,
        snapshot: execution.ExecutionSnapshot,
    ) -> tuple[
        approval.ScientificApproval,
        approval.BatchSubmitApproval,
        approval.ExactOperationalConfirmation,
    ]:
        plan = self.store.load_calculation_plan("plan-1")
        scientific = approval.ScientificApproval.for_plan(
            self.store,
            plan,
            displayed_semantic_meaning=DISPLAYED_MEANING,
            reviewer_id="scientific-reviewer",
            reviewer_evidence={"decision": "approve exact displayed meaning"},
        )
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", scientific)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": ["attempt-1"]},
        )
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            self.store,
            snapshot,
            confirmer_id="operator",
            confirmer_evidence={"displayed": "exact execution snapshot"},
        )
        self.approval_store.store_scientific_approval(scientific)
        self.approval_store.store_batch_submit_approval(batch)
        self.approval_store.store_operational_confirmation(confirmation)
        return (
            self.approval_store.load_scientific_approval(
                scientific.scientific_approval_id
            ),
            self.approval_store.load_batch_submit_approval(
                batch.batch_submit_approval_id
            ),
            self.approval_store.load_current_operational_confirmation(
                confirmation.operational_confirmation_id, snapshot
            ),
        )

    @staticmethod
    def _validate_authority(
        runtime_store: core.SQLiteRuntimeStore,
        snapshot: execution.ExecutionSnapshot,
        authorities: tuple[
            approval.ScientificApproval,
            approval.BatchSubmitApproval,
            approval.ExactOperationalConfirmation,
        ],
        *,
        displayed_meaning: object = DISPLAYED_MEANING,
    ) -> None:
        scientific, batch, confirmation = authorities
        approval.validate_effect_authority(
            runtime_store=runtime_store,
            attempt=runtime_store.load_attempt(snapshot.attempt_id),
            plan=runtime_store.load_calculation_plan(snapshot.calculation_plan_id),
            displayed_semantic_meaning=displayed_meaning,  # type: ignore[arg-type]
            scientific_approval=scientific,
            batch_submit_approval=batch,
            execution_snapshot=snapshot,
            operational_confirmation=confirmation,
        )

    def _execute_single(
        self,
    ) -> tuple[
        core.SQLiteRuntimeStore,
        execution.ExecutionSnapshot,
        execution.ServerProfile,
        FakeDriver,
        execution.ExecutionAttemptResult,
    ]:
        profile = self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        snapshot, _ = self.transport_snapshot(profile=profile, queue="batch")
        authorities = self._approval_chain(snapshot)
        self._workflow_ready(self.store)
        self._validate_authority(self.store, snapshot, authorities)
        driver = FakeDriver(text_results=execution_successes())
        adapter = self.execution_adapter(driver, profile)
        outcome = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        self.assertIs(outcome.claim, core.SubmissionIntentClaim.WINNER)
        self.assertIs(outcome.attempt_state, core.AttemptState.SUBMITTED)
        self.assertEqual(driver.text_calls[-1][1].argv, (
            "-d", snapshot.workspace_binding.remote_attempt_dir,
            "-l", "nodes=1:ppn=8,mem=12288mb,walltime=3600",
            "-q", "batch", "job.pbs",
        ))
        return self.store, snapshot, profile, driver, outcome

    @staticmethod
    def _input_binding(snapshot: execution.ExecutionSnapshot) -> result.InputBinding:
        prepared = snapshot.prepared_input_binding
        return result.InputBinding(
            attempt_id=snapshot.attempt_id,
            calculation_plan_id=snapshot.calculation_plan_id,
            calculation_plan_revision=snapshot.calculation_plan_revision,
            prepared_input_binding_id=prepared.prepared_input_binding_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            input_format=prepared.input_format,
            logical_name=prepared.logical_name,
            sha256=prepared.sha256,
            size_bytes=prepared.size_bytes,
        )

    @staticmethod
    def _output_envelope(
        capture: transport.FetchedOutputCapture,
    ) -> tuple[result.OutputEnvelope, dict[str, bytes]]:
        artifacts = tuple(
            result.OutputArtifact(
                artifact_kind=item.request.artifact_kind,
                logical_name=item.request.logical_name,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
            for item in capture.artifacts
        )
        for fetched, metadata in zip(capture.artifacts, artifacts, strict=True):
            if sha256(fetched.content).hexdigest() != metadata.sha256:
                raise AssertionError("fetched bytes do not match mapped Result metadata")
            if len(fetched.content) != metadata.size_bytes:
                raise AssertionError("fetched byte size does not match Result metadata")
        envelope = result.OutputEnvelope(
            attempt_id=capture.binding.attempt_id,
            input_binding_observation_id=capture.input_binding_observation_id,
            execution_snapshot_id=capture.binding.execution_snapshot_id,
            capture_source_id=capture.capture_source_id,
            capture_sequence=capture.capture_sequence,
            capture_status=result.CaptureStatus(capture.capture_status),
            capture_completeness=result.CaptureCompleteness(
                capture.capture_completeness
            ),
            artifacts=artifacts,
            capture_manifest_sha256=capture.capture_manifest_sha256,
            captured_at_utc=capture.captured_at_utc,
        )
        return envelope, {
            item.request.logical_name: item.content for item in capture.artifacts
        }

    def _binding_from_submission(
        self,
        runtime_store: core.SQLiteRuntimeStore,
        snapshot: execution.ExecutionSnapshot,
        profile: execution.ServerProfile,
    ) -> transport.ExactRemoteJobBinding:
        journal = execution.ReceiptJournal(runtime_store)
        submissions = tuple(
            item
            for item in journal.receipts_for_attempt(snapshot.attempt_id)
            if item.effect_kind is execution.EffectKind.SUBMISSION
            and item.effect_state is execution.EffectState.CONFIRMED_EFFECT
        )
        self.assertEqual(len(submissions), 1)
        return transport.ExactRemoteJobBinding.from_persisted_receipt(
            snapshot,
            journal,
            remote_effect_receipt_id=submissions[0].remote_effect_receipt_id,
            current_profile=profile,
            transport_store=self.transport_store,
        )

    def test_two_controllers_complete_public_chain_one_winner_one_replay(self) -> None:
        self.assertEqual(len(MINIMUM_GAUSSIAN_BYTES), 810)
        self.assertEqual(
            sha256(MINIMUM_GAUSSIAN_BYTES).hexdigest(),
            "9bb25969090345db5a8ff91d603baf4bbb4a4e49a707aed9676fc9ff5eb8cf65",
        )
        snapshot, profile = self.transport_snapshot()
        authorities = self._approval_chain(snapshot)
        self._workflow_ready(self.store)
        self.store.close()

        barrier = threading.Barrier(2)
        drivers = [
            FakeDriver(text_results=execution_successes()),
            FakeDriver(text_results=execution_successes()),
        ]
        outcomes: list[tuple[int, execution.ExecutionAttemptResult]] = []
        errors: list[BaseException] = []

        def controller(index: int) -> None:
            try:
                with core.SQLiteRuntimeStore(self.database) as runtime_store:
                    self._validate_authority(runtime_store, snapshot, authorities)
                    barrier.wait()
                    outcome = execution.execute_once(
                        runtime_store,
                        snapshot=snapshot,
                        current_profile=profile,
                        prepared_input_bytes=INPUT_BYTES,
                        pbs_template_bytes=TEMPLATE_BYTES,
                        confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                        port=self.execution_adapter(drivers[index], profile),
                    )
                    outcomes.append((index, outcome))
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=controller, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertCountEqual(
            [item.claim for _index, item in outcomes],
            [core.SubmissionIntentClaim.WINNER, core.SubmissionIntentClaim.REPLAY],
        )
        replay_index = next(
            index
            for index, item in outcomes
            if item.claim is core.SubmissionIntentClaim.REPLAY
        )
        self.assertEqual(drivers[replay_index].text_calls, [])
        self.assertEqual(
            sum(
                call[1].operation.name == "SUBMIT_QSUB_ONCE"
                for driver in drivers
                for call in driver.text_calls
            ),
            1,
        )

        runtime_store = core.SQLiteRuntimeStore(self.database)
        self.store = runtime_store
        self.addCleanup(runtime_store.close)
        self.assertIs(runtime_store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

        with self.assertRaises(approval.ApprovalScopeError):
            self._validate_authority(runtime_store, snapshot, authorities)
        later_driver = FakeDriver(text_results=execution_successes())
        self.assertEqual(later_driver.text_calls, [])

        binding = self._binding_from_submission(runtime_store, snapshot, profile)
        input_binding = self._input_binding(snapshot)
        provenance = result.ResultProvenanceService(runtime_store)
        provenance.record_input_binding(input_binding)

        required_log = transport.ExactArtifactRequest(
            artifact_kind="gaussian-log",
            logical_name="input.log",
            remote_relative_name="input.log",
            required=True,
        )
        read_driver = FakeDriver(
            text_results=(
                qstat(b"Job Id: 123.server\n    job_state = R\n"),
                response(
                    "STAT_EXACT_FILE",
                    {
                        "presence": "present",
                        "remote_relative_name": "input.log",
                        "size_bytes": len(MINIMUM_GAUSSIAN_BYTES),
                        "file_physical_token_base64": "ZmlsZS10b2tlbi12MQ==",
                    },
                ),
            ),
            fetch_results=(found(MINIMUM_GAUSSIAN_BYTES),),
        )
        reader = self.read_adapter(read_driver)
        scheduler = reader.read_scheduler(snapshot, binding, profile)
        state_before_observe = runtime_store.attempt_state("attempt-1")
        observation = observe.AttemptObservation(
            attempt_id=scheduler.binding.attempt_id,
            source_kind=scheduler.source_kind,
            source_identity=scheduler.source_identity,
            observed_at_utc=scheduler.observed_at_utc,
            freshness=scheduler.freshness,
            state=scheduler.state,
            progress_position=scheduler.progress_position,
        )
        observe.record_attempt_observation(runtime_store, observation)
        projection = observe.project_attempt_observations(
            runtime_store, attempt_id="attempt-1"
        )
        self.assertEqual(projection.scheduler, observation)
        self.assertIs(runtime_store.attempt_state("attempt-1"), state_before_observe)

        capture = reader.fetch_exact_output(
            snapshot,
            binding,
            profile,
            input_binding_observation_id=input_binding.observation_id,
            requests=(required_log,),
            capture_sequence=1,
        )
        envelope, artifact_bytes = self._output_envelope(capture)
        provenance.record_output_envelope(envelope)
        parser = result.GaussianJobParser()
        with mock.patch.object(parser, "parse", wraps=parser.parse) as parse_spy:
            parse_outcome = parser.parse(envelope, artifact_bytes)
            parse_spy.assert_called_once_with(envelope, artifact_bytes)
        self.assertIs(parse_outcome.parse_status, result.ParseStatus.PARSED)
        provenance.record_parse_outcome(parse_outcome)

        minimum = scientific_validation.record_minimum_validation(
            self.validation_store,
            scientific_validation.validate_minimum(
                runtime_store, input_binding, envelope, parse_outcome
            ),
        )
        self.assertIs(
            minimum.classification,
            scientific_validation.MinimumValidationClassification.VALIDATED_MINIMUM,
        )
        self.assertEqual(minimum.reason_code, "validated-minimum")
        review_before = review.build_review_bundle(
            runtime_store,
            self.validation_store,
            input_binding=input_binding,
            output_envelope=envelope,
            parse_outcome=parse_outcome,
            minimum_validation_outcome_id=minimum.minimum_validation_outcome_id,
        )
        self.assertIs(
            review_before.scientific_acceptance_state,
            review.ReviewAcceptanceState.ELIGIBLE_UNACCEPTED,
        )
        acceptance = scientific_validation.record_scientific_acceptance(
            self.validation_store,
            minimum_validation_outcome_id=minimum.minimum_validation_outcome_id,
            reviewer_id="result-reviewer",
            review_evidence={"decision": "accept exact minimum evidence"},
        )
        replayed_minimum, replayed_acceptance = (
            scientific_validation.require_scientific_acceptance(
                self.validation_store,
                minimum_validation_outcome_id=minimum.minimum_validation_outcome_id,
                scientific_acceptance_id=acceptance.scientific_acceptance_id,
            )
        )
        self.assertEqual((replayed_minimum, replayed_acceptance), (minimum, acceptance))
        accepted_bundle = review.build_review_bundle(
            runtime_store,
            self.validation_store,
            input_binding=input_binding,
            output_envelope=envelope,
            parse_outcome=parse_outcome,
            minimum_validation_outcome_id=minimum.minimum_validation_outcome_id,
            scientific_acceptance_ids=(acceptance.scientific_acceptance_id,),
        )
        self.assertIs(
            accepted_bundle.scientific_acceptance_state,
            review.ReviewAcceptanceState.ACCEPTED,
        )
        self.assertIs(runtime_store.attempt_state("attempt-1"), state_before_observe)

    def test_stale_and_preclaimed_authority_have_zero_transport_calls(self) -> None:
        snapshot, profile = self.transport_snapshot()
        authorities = self._approval_chain(snapshot)
        self._workflow_ready(self.store)
        stale_driver = FakeDriver(text_results=execution_successes())
        with self.assertRaises(approval.StaleApprovalError):
            self._validate_authority(
                self.store,
                snapshot,
                authorities,
                displayed_meaning={"job": "different displayed meaning"},
            )
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
        self.assertEqual(stale_driver.text_calls, [])

        scientific, _batch, confirmation = authorities
        self.store.store_task(
            core.Task(
                task_id="task-2",
                workflow_run_id="run-1",
                task_kind="gaussian-minimum",
            )
        )
        self.store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id="plan-2",
                task_id="task-2",
                revision=1,
                intent={"job": "other minimum"},
            )
        )
        self.store.create_attempt(
            core.Attempt(attempt_id="attempt-2", task_id="task-2", ordinal=1)
        )
        other_scientific = approval.ScientificApproval.for_plan(
            self.store,
            self.store.load_calculation_plan("plan-2"),
            displayed_semantic_meaning={"job": "other minimum"},
            reviewer_id="scientific-reviewer",
            reviewer_evidence={"decision": "approve other exact meaning"},
        )
        wrong_member_batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-2", other_scientific)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": ["attempt-2"]},
        )
        self.approval_store.store_batch_submit_approval(wrong_member_batch)
        batch_driver = FakeDriver(text_results=execution_successes())
        with self.assertRaises(approval.ApprovalScopeError):
            self._validate_authority(
                self.store,
                snapshot,
                (scientific, wrong_member_batch, confirmation),
            )
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
        self.assertEqual(batch_driver.text_calls, [])

        other_profile = self.profile(deployment_id="other-deployment")
        other_snapshot, _ = self.transport_snapshot(profile=other_profile)
        stale_confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            self.store,
            other_snapshot,
            confirmer_id="operator",
            confirmer_evidence={"displayed": "different execution snapshot"},
        )
        self.approval_store.store_operational_confirmation(stale_confirmation)
        stale_confirmation = self.approval_store.load_current_operational_confirmation(
            stale_confirmation.operational_confirmation_id, other_snapshot
        )
        confirmation_driver = FakeDriver(text_results=execution_successes())
        with self.assertRaises(approval.StaleApprovalError):
            self._validate_authority(
                self.store,
                snapshot,
                (scientific, authorities[1], stale_confirmation),
            )
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
        self.assertEqual(confirmation_driver.text_calls, [])

        self.assertIs(
            self.store.record_submission_intent(
                snapshot.attempt_id, snapshot.submission_intent_id
            ),
            core.SubmissionIntentClaim.WINNER,
        )
        with self.assertRaises(approval.ApprovalScopeError):
            self._validate_authority(self.store, snapshot, authorities)
        preclaimed_driver = FakeDriver(text_results=execution_successes())
        replay = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=self.execution_adapter(preclaimed_driver, profile),
        )
        self.assertIs(replay.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(preclaimed_driver.text_calls, [])

    def test_post_winner_ambiguity_is_unknown_and_never_retries(self) -> None:
        snapshot, profile = self.transport_snapshot()
        authorities = self._approval_chain(snapshot)
        self._workflow_ready(self.store)
        self._validate_authority(self.store, snapshot, authorities)
        responses = list(execution_successes())
        responses[-1] = replace(
            responses[-1],
            stdout=b"",
            stderr=b"",
            returncode=None,
            eof_stdout=False,
            eof_stderr=False,
            completion_status="transport-error",
        )
        driver = FakeDriver(text_results=tuple(responses))
        adapter = self.execution_adapter(driver, profile)
        first = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        calls_after_unknown = len(driver.text_calls)
        second = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=adapter,
        )
        self.assertIs(first.claim, core.SubmissionIntentClaim.WINNER)
        self.assertIs(first.attempt_state, core.AttemptState.UNKNOWN)
        self.assertIs(second.claim, core.SubmissionIntentClaim.REPLAY)
        self.assertEqual(len(driver.text_calls), calls_after_unknown)
        self.assertEqual(
            tuple(call[1].operation.name for call in driver.text_calls).count(
                "SUBMIT_QSUB_ONCE"
            ),
            1,
        )
        with self.assertRaises(approval.ApprovalScopeError):
            self._validate_authority(self.store, snapshot, authorities)
        with self.assertRaises(core.RecordNotFoundError):
            self.store.load_attempt("attempt-2")
        uncertain_receipt = first.receipts[-1]
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(
                snapshot,
                execution.ReceiptJournal(self.store),
                remote_effect_receipt_id=uncertain_receipt.remote_effect_receipt_id,
                current_profile=profile,
                transport_store=self.transport_store,
            )

    def test_receipt_profile_binding_and_fetch_splices_fail_closed(self) -> None:
        runtime_store, snapshot, profile, _driver, _outcome = self._execute_single()
        journal = execution.ReceiptJournal(runtime_store)
        forged = execution.RemoteEffectReceipt(
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=99,
            effect_kind=execution.EffectKind.SUBMISSION,
            effect_state=execution.EffectState.CONFIRMED_EFFECT,
            remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
            job_id="123.server",
            details={"source": "unpersisted-forgery"},
        )
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(
                snapshot,
                journal,
                remote_effect_receipt_id=forged.remote_effect_receipt_id,
                current_profile=profile,
                transport_store=self.transport_store,
            )

        binding = self._binding_from_submission(runtime_store, snapshot, profile)
        receipts = journal.receipts_for_attempt(snapshot.attempt_id)
        persisted_cross_receipt = next(
            item
            for item in receipts
            if item.effect_kind is not execution.EffectKind.SUBMISSION
        )
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(
                snapshot,
                journal,
                remote_effect_receipt_id=(
                    persisted_cross_receipt.remote_effect_receipt_id
                ),
                current_profile=profile,
                transport_store=self.transport_store,
            )

        submission = next(
            item
            for item in receipts
            if item.effect_kind is execution.EffectKind.SUBMISSION
            and item.effect_state is execution.EffectState.CONFIRMED_EFFECT
        )
        before_receipts = journal.receipts_for_attempt(snapshot.attempt_id)
        journal.append(submission)
        self.assertEqual(journal.receipts_for_attempt(snapshot.attempt_id), before_receipts)
        conflicting_duplicate = execution.RemoteEffectReceipt(
            attempt_id=submission.attempt_id,
            execution_snapshot_id=submission.execution_snapshot_id,
            submission_intent_id=submission.submission_intent_id,
            effect_sequence=submission.effect_sequence,
            effect_kind=execution.EffectKind.SUBMISSION_RECONCILIATION,
            effect_state=execution.EffectState.CONFIRMED_EFFECT,
            remote_workspace=submission.remote_workspace,
            job_id=submission.job_id,
            details={"source": "conflicting durable evidence"},
        )
        self.assertEqual(
            conflicting_duplicate.remote_effect_receipt_id,
            submission.remote_effect_receipt_id,
        )
        with self.assertRaises(execution.ExecutionConflictError):
            journal.append(conflicting_duplicate)
        self.assertEqual(journal.receipts_for_attempt(snapshot.attempt_id), before_receipts)

        frozen_profile = snapshot.resolved_server_profile
        drifted_profiles: list[execution.ServerProfile] = []
        semantic_drift = copy.deepcopy(profile)
        semantic_drift.target_host = "10.0.0.51"
        drifted_profiles.append(semantic_drift)
        identity_drift = copy.deepcopy(profile)
        identity_drift.server_profile_id = "profile-transport-other"
        drifted_profiles.append(identity_drift)
        digest_drift = copy.deepcopy(profile)
        digest_drift.config_files[0] = ("ssh_config", b"changed")
        drifted_profiles.append(digest_drift)
        resolved_drifts = tuple(
            execution.resolve_server_profile(item) for item in drifted_profiles
        )
        self.assertNotEqual(
            resolved_drifts[0].semantic_payload(), frozen_profile.semantic_payload()
        )
        self.assertNotEqual(
            resolved_drifts[1].resolved_server_profile_id,
            frozen_profile.resolved_server_profile_id,
        )
        self.assertNotEqual(
            resolved_drifts[2].effective_config_sha256,
            frozen_profile.effective_config_sha256,
        )
        for drifted_profile in drifted_profiles:
            profile_driver = FakeDriver(text_results=(qstat(b""),))
            with self.assertRaises(transport.TransportBoundaryError):
                self.read_adapter(profile_driver).read_scheduler(
                    snapshot, binding, drifted_profile
                )
            self.assertEqual(profile_driver.text_calls, [])

        for field_name, forged_value in (
            ("transport_store_id", "store-other"),
            ("store_instance_id", "store-instance-other"),
            ("attempt_id", "attempt-other"),
            ("execution_snapshot_id", "snapshot-other"),
            ("submission_intent_id", "intent-other"),
            ("remote_effect_receipt_id", "receipt-other"),
            ("remote_workspace", "/home/user100/SDL/project-1/attempt-other"),
            ("job_id", "999.server"),
        ):
            original = getattr(binding, field_name)
            object.__setattr__(binding, field_name, forged_value)
            driver = FakeDriver(text_results=(qstat(b""),))
            try:
                with self.assertRaises(transport.TransportBoundaryError):
                    self.read_adapter(driver).read_scheduler(snapshot, binding, profile)
                self.assertEqual(driver.text_calls, [])
            finally:
                object.__setattr__(binding, field_name, original)

        input_binding = self._input_binding(snapshot)
        request = transport.ExactArtifactRequest(
            artifact_kind="gaussian-log",
            logical_name="input.log",
            remote_relative_name="input.log",
            required=True,
        )
        stat_result = response(
            "STAT_EXACT_FILE",
            {
                "presence": "present",
                "remote_relative_name": "input.log",
                "size_bytes": len(MINIMUM_GAUSSIAN_BYTES),
                "file_physical_token_base64": "ZmlsZS10b2tlbi12MQ==",
            },
        )
        mismatch_driver = FakeDriver(
            text_results=(stat_result,),
            fetch_results=(found(MINIMUM_GAUSSIAN_BYTES, identity="d3JvbmctdG9rZW4="),),
        )
        before_results = runtime_store.results_for_attempt("attempt-1")
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(mismatch_driver).fetch_exact_output(
                snapshot,
                binding,
                profile,
                input_binding_observation_id=input_binding.observation_id,
                requests=(request,),
                capture_sequence=1,
            )
        self.assertEqual(runtime_store.results_for_attempt("attempt-1"), before_results)

    def test_partial_capture_and_provenance_splices_never_promote(self) -> None:
        runtime_store, snapshot, profile, _driver, _outcome = self._execute_single()
        binding = self._binding_from_submission(runtime_store, snapshot, profile)
        input_binding = self._input_binding(snapshot)
        provenance = result.ResultProvenanceService(runtime_store)
        provenance.record_input_binding(input_binding)
        required_log = transport.ExactArtifactRequest(
            artifact_kind="gaussian-log",
            logical_name="input.log",
            remote_relative_name="input.log",
            required=True,
        )
        optional_stdout = transport.ExactArtifactRequest(
            artifact_kind="stdout",
            logical_name="stdout.txt",
            remote_relative_name="stdout.txt",
            required=False,
        )
        driver = FakeDriver(
            text_results=(
                response(
                    "STAT_EXACT_FILE",
                    {
                        "presence": "present",
                        "remote_relative_name": "input.log",
                        "size_bytes": len(MINIMUM_GAUSSIAN_BYTES),
                        "file_physical_token_base64": "ZmlsZS10b2tlbi12MQ==",
                    },
                ),
                response(
                    "STAT_EXACT_FILE",
                    {"presence": "absent", "remote_relative_name": "stdout.txt"},
                ),
            ),
            fetch_results=(found(MINIMUM_GAUSSIAN_BYTES),),
        )
        capture = self.read_adapter(driver).fetch_exact_output(
            snapshot,
            binding,
            profile,
            input_binding_observation_id=input_binding.observation_id,
            requests=(required_log, optional_stdout),
            capture_sequence=1,
        )
        self.assertEqual(capture.capture_completeness, "partial")
        envelope, artifact_bytes = self._output_envelope(capture)
        provenance.record_output_envelope(envelope)
        parse_outcome = result.GaussianJobParser().parse(envelope, artifact_bytes)
        self.assertIs(parse_outcome.parse_status, result.ParseStatus.PARTIAL)
        provenance.record_parse_outcome(parse_outcome)
        parse_splice = replace(
            parse_outcome,
            envelope_observation_id="output-envelope-other",
        )
        with self.assertRaises(result.ProvenanceConflictError):
            provenance.record_parse_outcome(parse_splice)
        minimum = scientific_validation.record_minimum_validation(
            self.validation_store,
            scientific_validation.validate_minimum(
                runtime_store, input_binding, envelope, parse_outcome
            ),
        )
        self.assertIs(
            minimum.classification,
            scientific_validation.MinimumValidationClassification.INCOMPLETE,
        )
        self.assertEqual(minimum.reason_code, "incomplete-capture")
        bundle = review.build_review_bundle(
            runtime_store,
            self.validation_store,
            input_binding=input_binding,
            output_envelope=envelope,
            parse_outcome=parse_outcome,
            minimum_validation_outcome_id=minimum.minimum_validation_outcome_id,
        )
        self.assertIs(
            bundle.scientific_acceptance_state,
            review.ReviewAcceptanceState.INELIGIBLE,
        )
        with self.assertRaises(scientific_validation.ScientificValidationError):
            scientific_validation.record_scientific_acceptance(
                self.validation_store,
                minimum_validation_outcome_id=minimum.minimum_validation_outcome_id,
                reviewer_id="reviewer",
                review_evidence={"decision": "must reject incomplete"},
            )

        latest = transport.ExactArtifactRequest(
            artifact_kind="gaussian-log",
            logical_name="latest.log",
            remote_relative_name="latest.log",
            required=True,
        )
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(FakeDriver()).fetch_exact_output(
                snapshot,
                binding,
                profile,
                input_binding_observation_id=input_binding.observation_id,
                requests=(latest,),
                capture_sequence=2,
            )

        spliced = replace(
            envelope,
            input_binding_observation_id="input-binding-other",
            capture_sequence=2,
        )
        with self.assertRaises(result.ProvenanceConflictError):
            provenance.record_output_envelope(spliced)


if __name__ == "__main__":
    unittest.main()
