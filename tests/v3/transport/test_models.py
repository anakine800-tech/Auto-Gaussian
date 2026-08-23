from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.transport._canonical import canonical_bytes
from auto_g16.transport.models import SchedulerReadEvidence

from ._fixtures import NOW, TransportFixture


class BindingAndModelTests(TransportFixture):
    def test_persisted_receipt_and_current_profile_are_mandatory(self) -> None:
        snapshot, profile = self.transport_snapshot()
        journal = execution.ReceiptJournal(self.store)
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(
                snapshot,
                journal,
                remote_effect_receipt_id="missing",
                current_profile=profile,
            )
        binding = self.persisted_binding(snapshot, profile)
        self.assertEqual(binding.attempt_id, snapshot.attempt_id)
        self.assertEqual(binding.execution_snapshot_id, snapshot.execution_snapshot_id)
        self.assertEqual(binding.remote_workspace, snapshot.workspace_binding.remote_attempt_dir)
        self.assertEqual(binding.job_id, "123.server")
        with self.assertRaises(TypeError):
            transport.ExactRemoteJobBinding()  # type: ignore[call-arg]

    def test_profile_drift_and_nonconfirmed_receipt_fail_closed(self) -> None:
        snapshot, profile = self.transport_snapshot()
        drifted = self.profile(wrapper=b"different wrapper")
        journal = execution.ReceiptJournal(self.store)
        receipt = execution.RemoteEffectReceipt(
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=1,
            effect_kind=execution.EffectKind.SUBMISSION,
            effect_state=execution.EffectState.POSSIBLY_EFFECTFUL,
            remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
            details={"code": "ambiguous"},
        )
        journal.append(receipt)
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(
                snapshot,
                journal,
                remote_effect_receipt_id=receipt.remote_effect_receipt_id,
                current_profile=profile,
            )
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(
                snapshot,
                journal,
                remote_effect_receipt_id=receipt.remote_effect_receipt_id,
                current_profile=drifted,
            )

    def test_request_names_and_duplicate_authority_are_closed(self) -> None:
        for name in ("../job.log", "/job.log", "job/*.log", "job;touch", "job log", "."):
            with self.subTest(name=name), self.assertRaises(transport.TransportBoundaryError):
                transport.ExactArtifactRequest(
                    artifact_kind="gaussian-log",
                    logical_name=name,
                    remote_relative_name="job.log",
                    required=True,
                )
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactArtifactRequest(
                artifact_kind="checkpoint",
                logical_name="job.chk",
                remote_relative_name="job.chk",
                required=False,
            )
        with self.assertRaises(transport.TransportBoundaryError):
            transport.ExactArtifactRequest(
                artifact_kind="stdout",
                logical_name="stdout.txt",
                remote_relative_name="stdout.txt",
                required=1,  # type: ignore[arg-type]
            )

    def test_capture_binds_complete_request_partition(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        log = transport.ExactArtifactRequest(
            artifact_kind="gaussian-log",
            logical_name="input.log",
            remote_relative_name="input.log",
            required=True,
        )
        stdout = transport.ExactArtifactRequest(
            artifact_kind="stdout",
            logical_name="stdout.txt",
            remote_relative_name="stdout.txt",
            required=False,
        )
        artifact = transport.FetchedArtifact(request=log, content=b"Normal termination\n")
        partial = transport.FetchedOutputCapture(
            binding=binding,
            input_binding_observation_id="input-observation-1",
            capture_sequence=1,
            capture_status="capture-in-progress",
            capture_completeness="partial",
            requests=(log, stdout),
            artifacts=(artifact,),
            missing_requests=(stdout,),
            captured_at_utc=NOW,
        )
        self.assertEqual(partial.missing_requests, (stdout,))
        for change in (
            {"missing_requests": ()},
            {"capture_completeness": "complete"},
            {"requests": (stdout, log)},
        ):
            with self.subTest(change=change), self.assertRaises(transport.TransportBoundaryError):
                replace(partial, **change)

    def test_normative_scheduler_and_capture_vectors(self) -> None:
        binding = object.__new__(transport.ExactRemoteJobBinding)
        for name, value in {
            "attempt_id": "attempt-1",
            "execution_snapshot_id": "snapshot-1",
            "submission_intent_id": "intent-1",
            "remote_effect_receipt_id": "receipt-1",
            "remote_workspace": "/srv/p/attempt-1",
            "job_id": "123.server",
        }.items():
            object.__setattr__(binding, name, value)
        from auto_g16.transport import models as transport_models

        identity = id(binding)
        marker = tuple(
            str(item) for item in transport_models._binding_payload(binding).values()
        )
        reference = transport_models.weakref.ref(binding)
        with transport_models._BINDING_REGISTRY_LOCK:
            transport_models._BINDING_REGISTRY[identity] = (reference, marker)
        self.addCleanup(transport_models._BINDING_REGISTRY.pop, identity, None)
        stdout = b"Job Id: 123.server\n    job_state = R\n"
        acquisition = [stdout, b"", 0, True, True, "completed"]
        self.assertEqual(
            canonical_bytes(acquisition),
            b"a6:y37:4a6f622049643a203132332e7365727665720a202020206a6f625f7374617465203d20520ay0:i0;b1;b1;s9:completed",
        )
        evidence = SchedulerReadEvidence._from_classified(
            binding=binding,
            observed_at_utc=NOW,
            freshness="fresh",
            state="running",
            evidence_sha256=sha256(canonical_bytes(acquisition)).hexdigest(),
            evidence_size_bytes=37,
        )
        self.assertEqual(evidence.source_identity, "1a30e48e-fa53-5eb8-b186-cc7b4ea5f996")
        request = transport.ExactArtifactRequest(
            artifact_kind="gaussian-log",
            logical_name="job.log",
            remote_relative_name="job.log",
            required=True,
        )
        artifact = transport.FetchedArtifact(request=request, content=b"Normal termination\n")
        capture = transport.FetchedOutputCapture(
            binding=binding,
            input_binding_observation_id="input-observation-1",
            capture_sequence=1,
            capture_status="captured",
            capture_completeness="complete",
            requests=(request,),
            artifacts=(artifact,),
            missing_requests=(),
            captured_at_utc="2026-08-23T00:01:00.000000Z",
        )
        self.assertEqual(
            capture.capture_manifest_sha256,
            "1636f90c920537ebc491e0c7a173377a66db2cef4c28d488d435dd537e43a25f",
        )
        self.assertEqual(capture.capture_source_id, "337f05ea-7f62-581b-b1bf-46af0914bd6c")


if __name__ == "__main__":
    unittest.main()
