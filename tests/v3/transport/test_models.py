from __future__ import annotations

from dataclasses import replace
import os
import shutil
import sqlite3
import unittest

import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.transport._canonical import physical_id

from ._fixtures import NOW, TransportFixture


class TransportStoreTests(TransportFixture):
    def test_active_source_dependent_physical_identity_vectors(self) -> None:
        store_id = "108c8d43-2ea9-5658-9607-ade4cbbeac85"
        instance_id = "28c10d1a-9f8f-5ce6-84d1-555175c0fcde"
        runtime = ["auto-g16-transport/runtime-attestation", 1, store_id, instance_id, "snapshot-1", "profile-1", "a" * 64, "transport-deployment-manifest-v1.json", "70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983a", 2753, "synthetic-rtwin-deployment-v1", "auto-g16-v3-rtwin-bootstrap/1", "6b9c1f8574bb3541a884ca1532aae0d12a54d52cb158c8f8a9521f2421dc4cc6", 1490, "auto-g16-v3-rtwin-bootstrap-v1.py", "724869c6767c1570075812832d57c94e8c9e17ae2d4cd1d9f8781b0796671d2f", 12540]
        runtime_id = physical_id("runtime-attestation", runtime)
        self.assertEqual(runtime_id, "e42ac09e-e7da-50a3-b03f-54a5199d1686")
        workspace = ["auto-g16-transport/workspace-physical", 1, store_id, instance_id, runtime_id, "attempt-1", "snapshot-1", "intent-1", "/srv/p/attempt-1", b"workspace-token-v1"]
        workspace_id = physical_id("workspace-physical", workspace)
        self.assertEqual(workspace_id, "c3e44fc0-1907-542b-8ff9-2acf63034d60")
        artifact = ["auto-g16-transport/artifact-physical", 1, store_id, instance_id, workspace_id, runtime_id, "attempt-1", "snapshot-1", "intent-1", "prepared-input", "job.gjf", "job.gjf", "d" * 64, 123, b"artifact-token-v1"]
        self.assertEqual(physical_id("artifact-physical", artifact), "d716e8fa-09b3-5afb-920b-42647adaa65c")
        job = ["auto-g16-transport/job-physical", 1, store_id, instance_id, workspace_id, runtime_id, "attempt-1", "snapshot-1", "intent-1", "123.server"]
        job_id = physical_id("job-physical", job)
        self.assertEqual(job_id, "fcea1641-0bd5-5892-a66d-f0984eb6bfba")
        receipt = ["auto-g16-transport/receipt-binding", 1, store_id, instance_id, job_id, workspace_id, "attempt-1", "snapshot-1", "intent-1", "receipt-1", "123.server"]
        self.assertEqual(physical_id("receipt-binding", receipt), "cb3c8a2a-fa8e-5562-be86-e6b49959ee22")

    def test_create_reopen_preserves_exact_store_identity(self) -> None:
        store_id = self.transport_store.transport_store_id
        instance_id = self.transport_store.store_instance_id
        self.transport_store.close()
        reopened = transport.TransportStore.open_existing(self.transport_database, approved_root=self.transport_database.parent)
        self.addCleanup(reopened.close)
        self.assertEqual((reopened.transport_store_id, reopened.store_instance_id), (store_id, instance_id))

    def test_create_existing_and_terminal_symlink_fail_closed(self) -> None:
        with self.assertRaises(transport.TransportBoundaryError):
            transport.TransportStore.create_new(self.transport_database, approved_root=self.transport_database.parent)
        alias = self.transport_database.parent / "alias.sqlite3"
        alias.symlink_to(self.transport_database)
        with self.assertRaises(transport.TransportBoundaryError):
            transport.TransportStore.open_existing(alias, approved_root=self.transport_database.parent)

    def test_parent_symlink_is_rejected_by_descriptor_relative_traversal(self) -> None:
        root = self.temporary / "descriptor-root"
        real_parent = root / "real"
        root.mkdir()
        real_parent.mkdir()
        alias = root / "alias"
        alias.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(transport.TransportBoundaryError):
            transport.TransportStore.create_new(alias / "store.sqlite3", approved_root=root)
        self.assertFalse((real_parent / "store.sqlite3").exists())

    def test_copy_to_another_path_cannot_replay_store_identity(self) -> None:
        clone = self.transport_database.parent / "clone.sqlite3"
        self.transport_store.close()
        shutil.copyfile(self.transport_database, clone)
        with self.assertRaises(transport.TransportBoundaryError):
            transport.TransportStore.open_existing(clone, approved_root=self.transport_database.parent)

    def test_schema_inventory_and_append_only_triggers_are_closed(self) -> None:
        connection = self.transport_store._connection
        objects = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        self.assertEqual(len(tuple(name for name in objects if name.startswith("transport_") and not name.endswith(("_no_update", "_no_delete")))), 6)
        self.assertEqual(len(tuple(name for name in objects if name.endswith(("_no_update", "_no_delete")))), 12)
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute("UPDATE transport_meta SET transport_store_id='forged'")
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM transport_meta")

    def test_recreated_trigger_does_not_hide_row_payload_mutation(self) -> None:
        from auto_g16.transport import models

        snapshot, profile = self.transport_snapshot()
        authority = __import__("auto_g16.transport._driver", fromlist=["_resolve_deployment_authority"])._resolve_deployment_authority(snapshot, profile)
        runtime = self.transport_store._runtime(snapshot, authority)
        self.transport_store._record_workspace(snapshot, runtime["runtime_attestation_id"], b"workspace-token-v1")
        connection = self.transport_store._connection
        connection.execute("DROP TRIGGER transport_workspace_authority_no_update")
        connection.execute("UPDATE transport_workspace_authority SET payload=X'00'")
        trigger = dict(models._TRIGGERS)["transport_workspace_authority_no_update"]
        connection.execute(trigger)
        with self.assertRaises(transport.TransportBoundaryError):
            self.transport_store._workspace(snapshot)

    def test_closed_store_fails_before_adapter_driver(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        self.transport_store.close()
        adapter = transport.RTWinExecutionAdapter(transport_store=self.transport_store, current_profile=profile)
        with self.assertRaises(transport.TransportBoundaryError):
            adapter.allocate_attempt_workspace(snapshot)


class BindingAndRecordTests(TransportFixture):
    def test_persisted_receipt_and_shared_store_are_mandatory(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        self.assertEqual(binding.transport_store_id, self.transport_store.transport_store_id)
        self.assertEqual(binding.store_instance_id, self.transport_store.store_instance_id)
        self.assertEqual(binding.job_id, "123.server")
        with self.assertRaises(TypeError):
            transport.ExactRemoteJobBinding()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            transport.ExactRemoteJobBinding.from_persisted_receipt(  # type: ignore[call-arg]
                snapshot, execution.ReceiptJournal(self.store), remote_effect_receipt_id="x", current_profile=profile
            )

    def test_wrong_store_rejects_receipt_splice(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        other_root = self.temporary / "other-store"
        other_root.mkdir()
        other = transport.TransportStore.create_new(other_root / "db.sqlite3", approved_root=other_root)
        self.addCleanup(other.close)
        driver = type("NoCall", (), {"invoke_text": lambda *_: (_ for _ in ()).throw(AssertionError("driver called"))})()
        adapter = transport.RTWinReadAdapter._from_driver(driver, transport_store=other)
        with self.assertRaises(transport.TransportBoundaryError):
            adapter.read_scheduler(snapshot, binding, profile)

    def test_request_names_and_capture_partition_fail_closed(self) -> None:
        for name in ("../job.log", "/job.log", "job/*.log", "job;touch", "job log", "."):
            with self.subTest(name=name), self.assertRaises(transport.TransportBoundaryError):
                transport.ExactArtifactRequest(artifact_kind="gaussian-log", logical_name=name, remote_relative_name="job.log", required=True)
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        log = transport.ExactArtifactRequest(artifact_kind="gaussian-log", logical_name="input.log", remote_relative_name="input.log", required=True)
        stdout = transport.ExactArtifactRequest(artifact_kind="stdout", logical_name="stdout.txt", remote_relative_name="stdout.txt", required=False)
        artifact = transport.FetchedArtifact(request=log, content=b"Normal termination\n")
        partial = transport.FetchedOutputCapture(binding=binding, input_binding_observation_id="input-observation-1", capture_sequence=1, capture_status="capture-in-progress", capture_completeness="partial", requests=(log, stdout), artifacts=(artifact,), missing_requests=(stdout,), captured_at_utc=NOW)
        for change in ({"missing_requests": ()}, {"capture_completeness": "complete"}, {"requests": (stdout, log)}):
            with self.subTest(change=change), self.assertRaises(transport.TransportBoundaryError):
                replace(partial, **change)


if __name__ == "__main__":
    unittest.main()
