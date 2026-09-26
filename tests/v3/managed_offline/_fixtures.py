from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from auto_g16 import core, execution
from auto_g16.approval import SQLiteApprovalStore
from auto_g16.execution import _program_completion as completion
from auto_g16.execution.program import _ProgramExecutionSnapshotService
from auto_g16.execution.project_provisioning import (
    _ProjectProvisioningService, _SyntheticRemoteProjectAttestor, _SYNTHETIC_TEST_HARNESS_PRIVILEGE,
)
from auto_g16._managed_offline.common import decode_frame, frame
from auto_g16._managed_offline.intake import Intake
from auto_g16._managed_offline.lifecycle import FakeInstallation, FakeNative, Lifecycle
from auto_g16._managed_offline.registry import Registry
from auto_g16._managed_offline.review import PROTOCOL, Review, _timestamp
from tests.v3.execution.test_v31_lane_a import LaneAFixture
from tests.v31.transport.test_program_completion import manifest


def payload(**changes):
    value = {"schema": "auto-g16-xtb-local-material/1", "intake_id": str(uuid4()),
             "structure_identity": "Synthetic H2 geometry; no scientific acceptance",
             "stereochemistry_review": "Fixture has no stereocentre; requires human review",
             "atoms": [{"element": "H", "x_microangstrom": 0, "y_microangstrom": 0, "z_microangstrom": 0},
                       {"element": "H", "x_microangstrom": 0, "y_microangstrom": 0, "z_microangstrom": 740000}],
             "model": "gfn2", "task": "single-point", "charge": 0, "multiplicity": 1,
             "unpaired_electrons": 0, "solvent": None}
    return {**value, **changes}


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 9, 24, 15, tzinfo=timezone.utc)
        self.mono = 10.0

    def __call__(self):
        return self.wall, self.mono

    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


class Fixture(unittest.TestCase):
    def setUp(self):
        # Retained task scratch, not system temporary directories or real keys.
        base = Path(os.environ.get("AUTO_G16_MANAGED_TEST_SCRATCH", tempfile.gettempdir())).resolve()
        self.root = base / str(uuid4())
        self.root.mkdir(parents=True)
        for name in ("intake", "local", "transport"):
            (self.root / name).mkdir()
        self.addCleanup(patch.stopall)
        patch("subprocess.Popen", side_effect=AssertionError("real process forbidden")).start()
        patch("socket.socket", side_effect=AssertionError("network/socket forbidden")).start()
        self.core = core.SQLiteRuntimeStore(self.root / "core.sqlite3")
        self.approvals = SQLiteApprovalStore(self.root / "approval.sqlite3")
        self.addCleanup(self.core.close)
        self.addCleanup(self.approvals.close)
        self.core.store_project(core.Project(project_id="project-1"))
        self.core.store_workflow_run(core.WorkflowRun(workflow_run_id="run-1", project_id="project-1", workflow_name="offline-prototype"))
        profile = LaneAFixture.profile(self)
        self.profile = replace(profile, runtime_contents={**profile.runtime_contents, completion._DEPLOYMENT_NAME: completion._receipt_json(manifest())})
        self.resolved = execution.resolve_server_profile(self.profile)
        self.native, self.installation = FakeNative(), FakeInstallation()
        self.life = Lifecycle.offline(self.installation, self.native)
        self.addCleanup(self.life.close)
        self.registry = Registry(self.life, "a" * 64)
        self.intake = Intake(store=self.core, registry=self.registry, scratch=self.root / "intake",
            project_id="project-1", workflow_run_id="run-1", namespace="403f2c33-8d00-4e5e-b3bd-1b9cbbda41b6",
            profile=self.resolved, resources={"tier": "simple", "cores": 8, "memory_mb": 12288, "walltime_seconds": 3600, "queue": "fixture"},
            completion_material=completion._prepare_completion_rendering_material(self.profile, self.resolved), requester_uid=501)
        self.addCleanup(self.intake.files.close)
        self.clock = Clock()
        self.review = Review(intake=self.intake, approval_store=self.approvals, reviewer_uid=501,
            installation_hash="a" * 64, requester_uids=(501,), not_before=_timestamp(self.clock.wall + timedelta(seconds=1200)),
            not_after=_timestamp(self.clock.wall + timedelta(seconds=3600)), clock=self.clock)

    def make(self, **changes):
        p = payload(**changes)
        self.intake.prepare(p)
        return self.registry.index[p["intake_id"]]

    def rpc(self, operation, payload, **kwargs):
        raw = self.review.request(frame({"protocol": PROTOCOL, "operation": operation, "payload": payload}, 16384), peer_uid=501, **kwargs)
        return decode_frame(raw, 262144, eof=True)

    def prepare(self, slot, gate):
        return self.rpc("PREPARE_REVIEW", {"gate": gate, "subject_id": slot.cells[gate].subject})

    def decide(self, view, decision="APPROVED"):
        return self.rpc("DECIDE", {**{k: view[k] for k in ("review_view_id", "view_sha256", "source_event_id")}, "decision": decision})

    def approve(self, slot, gate):
        response = self.prepare(slot, gate)
        self.assertEqual(response["status"], "VIEW_READY", response)
        result = self.decide(response["payload"])
        self.assertEqual(result["status"], "RECORDED", result)
        return result["payload"]["approval_id"]

    def bind_snapshot(self, slot):
        remote = "/home/user100/SDL/project-1"
        attestor = _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(
            privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE, target=self.resolved, observed_project_dir=remote,
            observed_state="ABSENT", observed_parent_physical_identity="synthetic-parent",
            observed_project_physical_identity=None, provisioned_project_physical_identity="synthetic-project")
        provisioning = _ProjectProvisioningService._from_privileged_synthetic_attestor(privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE, attestor=attestor)
        binding = provisioning.provision_remote_project(project=self.intake.project, target=self.resolved,
            remote_project_dir=remote, evidence_identity="synthetic-only")
        service = _ProgramExecutionSnapshotService._for_privileged_synthetic_tests(privilege=_SYNTHETIC_TEST_HARNESS_PRIVILEGE, project_provisioning=provisioning)
        attempt = slot.records[3].attempt_id
        (self.root / "local" / "project-1").mkdir(exist_ok=True)
        workspace = execution.WorkspaceBinding(project=self.intake.project, attempt_id=attempt,
            local_approved_root=str(self.root / "local"), local_attempt_dir=str(self.root / "local" / "project-1" / attempt),
            rtwin_approved_root=r"C:\RTWIN", rtwin_attempt_dir=rf"C:\RTWIN\project-1\{attempt}",
            remote_approved_root="/home/user100/SDL", remote_attempt_dir=remote + "/" + attempt)
        resource = execution.ResolvedResourceRequest(resource_spec=slot.records[2], cores=8, memory_mb=12288, walltime_seconds=3600, queue="fixture")
        snapshot = service.prepare(self.core, attempt_id=attempt, calculation_plan_id=slot.records[1].calculation_plan_id,
            resource_spec_id=slot.records[2].resource_spec_id, program_execution_spec=slot.spec,
            project_physical_binding=binding, resolved_resource_request=resource, resolved_server_profile=self.resolved,
            workspace_binding=workspace, completion_rendering_material=completion._prepare_completion_rendering_material(self.profile, self.resolved))
        self.review.bind_offline_snapshot(slot.key[2], snapshot)
        return snapshot

    def chain(self):
        slot = self.make()
        scientific, batch = self.approve(slot, "scientific"), self.approve(slot, "batch")
        self.bind_snapshot(slot)
        operational = self.approve(slot, "operational")
        return slot, (scientific, batch, operational)
