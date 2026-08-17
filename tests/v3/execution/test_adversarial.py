from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import auto_g16.core as core
import auto_g16.execution as execution
import auto_g16.execution.runtime as execution_runtime

from .test_execution import ExecutionFixture, INPUT_BYTES, TEMPLATE_BYTES


class PathBoundaryTests(ExecutionFixture):
    def test_windows_ambient_and_noncanonical_paths_fail_closed(self) -> None:
        invalid = [
            r"relative\path",
            r"~\RTWIN\attempt-1",
            r"c:\RTWIN\attempt-1",
            r"C:RTWIN\attempt-1",
            r"C:\RTWIN\\attempt-1",
            r"C:\RTWIN\..\attempt-1",
            r"C:\RTWIN\NUL",
            r"\\server\share\attempt-1",
        ]
        for value in invalid:
            profile = self.profile()
            profile.platform_paths["rtwin_root"] = value
            with self.subTest(value=value), self.assertRaises(execution.ExecutionValueError):
                execution.resolve_server_profile(profile)

    def test_posix_noncanonical_and_relative_paths_fail_closed(self) -> None:
        invalid = [
            "relative/path",
            "~/SDL",
            "/home//user100/SDL",
            "/home/user100/../SDL",
            "/home/user100/SDL/",
        ]
        for value in invalid:
            profile = self.profile()
            profile.remote_root = value
            with self.subTest(value=value), self.assertRaises(execution.ExecutionValueError):
                execution.resolve_server_profile(profile)

    def test_workspace_parent_symlink_is_rejected(self) -> None:
        real = self.local_root / "real-project"
        real.mkdir()
        linked = self.local_root / "linked-project"
        linked.symlink_to(real, target_is_directory=True)
        with self.assertRaises(execution.ExecutionValueError):
            execution.WorkspaceBinding(
                project=self.store.load_project("project-1"),
                attempt_id="attempt-1",
                local_approved_root=str(self.local_root),
                local_attempt_dir=str(linked / "attempt-1"),
                rtwin_approved_root=r"C:\RTWIN",
                rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
                remote_approved_root=execution.LEGACY_REMOTE_ROOT,
                remote_attempt_dir="/home/user100/SDL/project-1/attempt-1",
            )

    def test_workspace_outside_reviewed_roots_is_rejected(self) -> None:
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(outside.rmdir)
        with self.assertRaises(execution.ExecutionValueError):
            execution.WorkspaceBinding(
                project=self.store.load_project("project-1"),
                attempt_id="attempt-1",
                local_approved_root=str(self.local_root),
                local_attempt_dir=str(outside / "attempt-1"),
                rtwin_approved_root=r"C:\RTWIN",
                rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
                remote_approved_root=execution.LEGACY_REMOTE_ROOT,
                remote_attempt_dir="/tmp/attempt-1",
            )

    def test_parent_component_replacement_before_allocation_fails_no_effect(self) -> None:
        snapshot, profile = self.snapshot()
        moved_parent = self.local_root / "moved-project-1"
        escape = self.temporary / "escape-before-allocation"
        escape.mkdir()

        def replace_parent(stage: str, _binding: execution.WorkspaceBinding) -> None:
            if stage != "before-allocation":
                return
            self.local_project.rename(moved_parent)
            self.local_project.symlink_to(escape, target_is_directory=True)

        adapter = execution.SyntheticRTWinAdapter()
        try:
            with mock.patch.object(
                execution_runtime,
                "_local_allocation_checkpoint",
                side_effect=replace_parent,
            ):
                result = execution.execute_once(
                    self.store,
                    snapshot=snapshot,
                    current_profile=profile,
                    prepared_input_bytes=INPUT_BYTES,
                    pbs_template_bytes=TEMPLATE_BYTES,
                    confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                    port=adapter,
                )
            self.assertIs(
                result.receipts[-1].effect_state,
                execution.EffectState.CONFIRMED_NO_EFFECT,
            )
            self.assertEqual(adapter.calls, ())
            self.assertEqual(list(escape.iterdir()), [])
            self.assertFalse((moved_parent / "attempt-1").exists())
        finally:
            if self.local_project.is_symlink():
                self.local_project.unlink()
            if moved_parent.exists():
                moved_parent.rename(self.local_project)

    def _assert_attempt_replacement_cannot_escape(self, checkpoint: str) -> None:
        snapshot, profile = self.snapshot()
        attempt = Path(snapshot.workspace_binding.local_attempt_dir)
        moved = self.local_project / f"moved-{checkpoint}"
        escape = self.temporary / f"escape-{checkpoint}"
        escape.mkdir()

        def replace_attempt(
            stage: str, _binding: execution.WorkspaceBinding
        ) -> None:
            if stage != checkpoint:
                return
            attempt.rename(moved)
            attempt.symlink_to(escape, target_is_directory=True)

        adapter = execution.SyntheticRTWinAdapter()
        try:
            with mock.patch.object(
                execution_runtime,
                "_local_allocation_checkpoint",
                side_effect=replace_attempt,
            ):
                result = execution.execute_once(
                    self.store,
                    snapshot=snapshot,
                    current_profile=profile,
                    prepared_input_bytes=INPUT_BYTES,
                    pbs_template_bytes=TEMPLATE_BYTES,
                    confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                    port=adapter,
                )
            self.assertIs(
                result.receipts[-1].effect_state,
                execution.EffectState.CONFIRMED_EFFECT,
            )
            self.assertEqual(result.receipts[-1].details["status"], "incomplete")
            self.assertEqual(adapter.calls, ())
            self.assertEqual(list(escape.iterdir()), [])
            self.assertEqual(list(moved.iterdir()), [])
        finally:
            if attempt.is_symlink():
                attempt.unlink()
            if moved.exists():
                moved.rename(attempt)

    def test_attempt_replacement_after_creation_cannot_escape(self) -> None:
        self._assert_attempt_replacement_cannot_escape("after-directory-creation")

    def test_attempt_replacement_before_writes_cannot_escape(self) -> None:
        self._assert_attempt_replacement_cannot_escape("before-handoff-write")


class ReceiptAndAuthorityTests(ExecutionFixture):
    def test_public_execution_record_fields_match_the_frozen_contract(self) -> None:
        expected = {
            execution.PreparedInputBinding: {
                "prepared_input_binding_id",
                "attempt_id",
                "calculation_plan_id",
                "calculation_plan_revision",
                "input_format",
                "logical_name",
                "sha256",
                "size_bytes",
            },
            execution.ResolvedResourceRequest: {
                "resolved_resource_request_id",
                "resource_spec_id",
                "cores",
                "memory_mb",
                "walltime_seconds",
                "queue",
            },
            execution.ResolvedServerProfile: {
                "resolved_server_profile_id",
                "server_profile_id",
                "profile_revision",
                "effective_config_sha256",
                "transport_kind",
                "target_identity",
                "remote_user",
                "remote_root",
                "platform_paths",
                "runtime_identities",
            },
            execution.PbsTemplateBinding: {
                "pbs_template_binding_id",
                "logical_name",
                "sha256",
                "size_bytes",
                "template_contract_version",
            },
            execution.WorkspaceBinding: {
                "workspace_binding_id",
                "project_id",
                "attempt_id",
                "local_attempt_dir",
                "rtwin_attempt_dir",
                "remote_attempt_dir",
            },
            execution.ExecutionSnapshot: {
                "execution_snapshot_id",
                "attempt_id",
                "submission_intent_id",
                "calculation_plan_id",
                "calculation_plan_revision",
                "prepared_input_binding",
                "resolved_resource_request",
                "resolved_server_profile",
                "workspace_binding",
                "pbs_template_binding",
                "adapter_contract_version",
            },
            execution.RemoteEffectReceipt: {
                "remote_effect_receipt_id",
                "attempt_id",
                "execution_snapshot_id",
                "submission_intent_id",
                "effect_sequence",
                "effect_kind",
                "effect_state",
                "remote_workspace",
                "job_id",
                "details",
            },
        }
        for record_type, names in expected.items():
            with self.subTest(record_type=record_type.__name__):
                self.assertEqual(
                    {item.name for item in fields(record_type) if not item.name.startswith("_")},
                    names,
                )

    def test_snapshot_records_are_slot_bound_and_nested_mutation_fails(self) -> None:
        snapshot, _profile = self.snapshot()
        records = (
            snapshot,
            snapshot.prepared_input_binding,
            snapshot.resolved_resource_request,
            snapshot.resolved_server_profile,
            snapshot.workspace_binding,
            snapshot.pbs_template_binding,
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertFalse(hasattr(record, "__dict__"))
                with self.assertRaises((AttributeError, TypeError)):
                    setattr(record, "injected", "forged")
        with self.assertRaises((AttributeError, TypeError)):
            snapshot.resolved_server_profile.platform_paths["rtwin_root"] = "forged"  # type: ignore[index]

    def test_mutated_snapshot_graph_is_rejected_before_adapter_call(self) -> None:
        mutations = (
            ("prepared-input", "prepared_input_binding", "sha256", "0" * 64),
            ("resource", "resolved_resource_request", "cores", 99),
            ("profile", "resolved_server_profile", "remote_root", "/tmp/forged"),
            ("workspace", "workspace_binding", "remote_attempt_dir", "/tmp/forged"),
            ("workspace-parent", "workspace_binding", "_local_parent_identity", (0, 0)),
            ("template", "pbs_template_binding", "sha256", "0" * 64),
            (
                "template-input-target",
                "pbs_template_binding",
                "_prepared_input_logical_name",
                "other.gjf",
            ),
            ("snapshot", None, "execution_snapshot_id", "forged"),
        )
        for label, nested_name, field_name, forged_value in mutations:
            with self.subTest(label=label):
                snapshot, profile = self.snapshot()
                target = snapshot if nested_name is None else getattr(snapshot, nested_name)
                original = getattr(target, field_name)
                object.__setattr__(target, field_name, forged_value)
                adapter = execution.SyntheticRTWinAdapter()
                try:
                    with self.assertRaises(execution.ExecutionValueError):
                        execution.execute_once(
                            self.store,
                            snapshot=snapshot,
                            current_profile=profile,
                            prepared_input_bytes=INPUT_BYTES,
                            pbs_template_bytes=TEMPLATE_BYTES,
                            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                            port=adapter,
                        )
                    self.assertEqual(adapter.calls, ())
                    self.assertIs(
                        self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED
                    )
                finally:
                    object.__setattr__(target, field_name, original)

    def test_mutated_snapshot_cannot_reconcile_unknown_by_port_or_receipt(self) -> None:
        snapshot, profile = self.snapshot()
        failing = execution.SyntheticRTWinAdapter(
            fail_stage=execution.EffectKind.SUBMISSION,
            ambiguous=True,
        )
        result = execution.execute_once(
            self.store,
            snapshot=snapshot,
            current_profile=profile,
            prepared_input_bytes=INPUT_BYTES,
            pbs_template_bytes=TEMPLATE_BYTES,
            confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
            port=failing,
        )
        self.assertIs(result.attempt_state, core.AttemptState.UNKNOWN)
        receipt = execution.RemoteEffectReceipt(
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=len(result.receipts) + 1,
            effect_kind=execution.EffectKind.SUBMISSION_RECONCILIATION,
            effect_state=execution.EffectState.CONFIRMED_NO_EFFECT,
            details={"source": "synthetic-read-only"},
        )
        mutations = (
            (snapshot.prepared_input_binding, "sha256", "0" * 64),
            (snapshot.resolved_resource_request, "cores", 99),
            (snapshot.resolved_server_profile, "remote_root", "/tmp/forged"),
            (snapshot.workspace_binding, "remote_attempt_dir", "/tmp/forged"),
            (snapshot.pbs_template_binding, "sha256", "0" * 64),
            (snapshot, "execution_snapshot_id", "forged"),
        )
        for target, field_name, forged_value in mutations:
            with self.subTest(target=type(target).__name__, field=field_name):
                original = getattr(target, field_name)
                before_observations = len(
                    self.store.observations_for_attempt(snapshot.attempt_id)
                )
                before_results = len(
                    self.store.results_for_attempt(snapshot.attempt_id)
                )
                object.__setattr__(target, field_name, forged_value)
                reconciler = execution.SyntheticRTWinAdapter(
                    reconciliation_state=execution.EffectState.CONFIRMED_NO_EFFECT
                )
                try:
                    with self.assertRaises(execution.ExecutionValueError):
                        execution.reconcile_unknown(
                            self.store, snapshot=snapshot, port=reconciler
                        )
                    self.assertEqual(reconciler.calls, ())
                    with self.assertRaises(execution.ExecutionValueError):
                        execution.reconcile_unknown_from_receipt(
                            self.store, snapshot=snapshot, receipt=receipt
                        )
                    self.assertIs(
                        self.store.attempt_state(snapshot.attempt_id),
                        core.AttemptState.UNKNOWN,
                    )
                    self.assertEqual(
                        len(self.store.observations_for_attempt(snapshot.attempt_id)),
                        before_observations,
                    )
                    self.assertEqual(
                        len(self.store.results_for_attempt(snapshot.attempt_id)),
                        before_results,
                    )
                finally:
                    object.__setattr__(target, field_name, original)

    def test_receipt_exact_replay_is_idempotent_and_sequence_conflict_fails(self) -> None:
        snapshot, _profile = self.snapshot()
        journal = execution.ReceiptJournal(self.store)
        first = execution.RemoteEffectReceipt(
            attempt_id="attempt-1",
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=1,
            effect_kind=execution.EffectKind.LOCAL_WORKSPACE,
            effect_state=execution.EffectState.CONFIRMED_EFFECT,
            details={"status": "sealed"},
        )
        journal.append(first)
        journal.append(first)
        self.assertEqual(len(journal.receipts_for_attempt("attempt-1")), 1)
        conflict = execution.RemoteEffectReceipt(
            attempt_id="attempt-1",
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=1,
            effect_kind=execution.EffectKind.LOCAL_WORKSPACE,
            effect_state=execution.EffectState.CONFIRMED_NO_EFFECT,
            details={"code": "different"},
        )
        self.assertEqual(
            first.remote_effect_receipt_id, conflict.remote_effect_receipt_id
        )
        with self.assertRaises(execution.ExecutionConflictError):
            journal.append(conflict)

    def test_tampered_stored_receipt_identity_fails_closed(self) -> None:
        snapshot, _profile = self.snapshot()
        self.store.append_observation(
            core.Observation(
                observation_id="forged-receipt-id",
                attempt_id="attempt-1",
                observation_type="v3.remote-effect-receipt",
                data={
                    "remote_effect_receipt_id": "forged-receipt-id",
                    "attempt_id": "attempt-1",
                    "execution_snapshot_id": snapshot.execution_snapshot_id,
                    "submission_intent_id": snapshot.submission_intent_id,
                    "effect_sequence": 1,
                    "effect_kind": "local-workspace",
                    "effect_state": "confirmed_effect",
                    "remote_workspace": None,
                    "job_id": None,
                    "details": {},
                },
            )
        )
        with self.assertRaises(execution.ExecutionConflictError):
            execution.ReceiptJournal(self.store).receipts_for_attempt("attempt-1")

    def test_wrong_snapshot_confirmation_stops_before_core_claim(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter()
        with self.assertRaises(execution.ExecutionValueError):
            execution.execute_once(
                self.store,
                snapshot=snapshot,
                current_profile=profile,
                prepared_input_bytes=INPUT_BYTES,
                pbs_template_bytes=TEMPLATE_BYTES,
                confirmed_execution_snapshot_id="wrong",
                port=adapter,
            )
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
        self.assertEqual(adapter.calls, ())

    def test_resolved_profile_and_snapshot_cannot_accept_opaque_authority(self) -> None:
        with self.assertRaises(TypeError):
            execution.ResolvedServerProfile(  # type: ignore[call-arg]
                server_profile_id="forged",
                effective_config_sha256="0" * 64,
            )
        with self.assertRaises(TypeError):
            execution.ExecutionSnapshot(  # type: ignore[call-arg]
                execution_snapshot_id="forged",
                attempt_id="attempt-1",
            )

    def test_prepared_or_template_bytes_cannot_be_reread_from_ambient_path(self) -> None:
        snapshot, profile = self.snapshot()
        adapter = execution.SyntheticRTWinAdapter()
        with self.assertRaises(execution.ExecutionValueError):
            execution.execute_once(
                self.store,
                snapshot=snapshot,
                current_profile=profile,
                prepared_input_bytes=INPUT_BYTES + b"changed",
                pbs_template_bytes=TEMPLATE_BYTES,
                confirmed_execution_snapshot_id=snapshot.execution_snapshot_id,
                port=adapter,
            )
        self.assertEqual(adapter.calls, ())

    def test_pbs_template_rejects_resource_bypass_and_arbitrary_commands(self) -> None:
        for value in (
            b"#!/bin/bash\n#PBS -l mem=999gb\nexec g16 input.gjf\n",
            b"#!/bin/bash\nrm -rf forbidden\n",
            b"#!/bin/bash\nexec g16 input.gjf\nexec g16 second.gjf\n",
        ):
            with self.subTest(value=value), self.assertRaises(execution.ExecutionValueError):
                execution.PbsTemplateBinding(
                    logical_name="job.pbs",
                    template_bytes=value,
                    template_contract_version="pbs-template-v1",
                    prepared_input_logical_name="input.gjf",
                )

        with self.assertRaises(execution.ExecutionValueError):
            execution.PbsTemplateBinding(
                logical_name="job.pbs",
                template_bytes=b"#!/bin/bash\nexec g16 other.gjf\n",
                template_contract_version="pbs-template-v1",
                prepared_input_logical_name="input.gjf",
            )

    def test_profile_resolution_rejects_secret_bytes(self) -> None:
        profile = self.profile(
            config=b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----\n"
        )
        with self.assertRaises(execution.ExecutionValueError):
            execution.resolve_server_profile(profile)

    def test_public_core_remains_transport_free(self) -> None:
        self.assertNotIn("ExecutionSnapshot", core.__all__)
        self.assertFalse(hasattr(core, "ExecutionSnapshot"))
        self.assertFalse(any(name in core.__all__ for name in {"ExecutionPort", "RTwin"}))

    def test_synthetic_adapter_has_no_live_transport_imports(self) -> None:
        source = (
            Path(execution.__file__).resolve().with_name("synthetic_rtwin.py").read_text(
                encoding="utf-8"
            )
        )
        for forbidden in ("subprocess", "socket", "paramiko", "qsub", "qdel", "ssh"):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
