"""Current-view relay and retained Gate links to the original ApprovalStore."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import math
from threading import Lock
import time
from uuid import uuid4

from auto_g16.approval import (
    ApprovalDecision, ApprovalStoreNotFoundError, BatchSubmitApproval,
    ExactOperationalConfirmation, ScientificApproval, validate_effect_authority,
)
from auto_g16.core import AttemptState
from auto_g16.execution.program import ProgramExecutionSnapshot

from .common import Rejected, RequestRejected, copy_data, decode_frame, digest, exact, frame, json_bytes
from .material import semantic_join
from .registry import GATES, MAX_GENERATION

PROTOCOL = "auto-g16-review-bridge/1"
_ID_NAMES = ("scientific_approval_id", "batch_submit_approval_id", "operational_confirmation_id")
_METHODS = ("scientific_approval", "batch_submit_approval", "operational_confirmation")


def _timestamp(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_time(value):
    try:
        result = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        if _timestamp(result) != value:
            raise ValueError
        return result
    except (ValueError, TypeError) as exc:
        raise Rejected("SCOPE") from exc


@dataclass
class View:
    slot: object
    gate: str
    payload: dict
    candidates: tuple
    deadline: float


class Review:
    def __init__(self, *, intake, approval_store, reviewer_uid, installation_hash,
                 requester_uids, not_before, not_after, clock=None):
        self.intake, self.store = intake, approval_store
        self.life = intake._root.lifecycle
        self.installation_hash = installation_hash
        if not re.fullmatch(r"[0-9a-f]{64}", installation_hash) or installation_hash != intake._root.installation_hash:
            raise Rejected("SCOPE")
        if type(reviewer_uid) is not int or not 1 <= reviewer_uid <= 4294967294:
            raise Rejected("SCOPE")
        if (type(requester_uids) is not tuple or not 1 <= len(requester_uids) <= 16
                or any(type(uid) is not int or not 1 <= uid <= 4294967294 for uid in requester_uids)
                or tuple(sorted(set(requester_uids))) != requester_uids):
            raise Rejected("SCOPE")
        before, after = _parse_time(not_before), _parse_time(not_after)
        if not timedelta(0) < after - before <= timedelta(seconds=86400):
            raise Rejected("SCOPE")
        self.uid = reviewer_uid
        self.scope = {"trigger_policy": "preapproved-no-presence", "requester_uids": list(requester_uids),
                      "not_before": not_before, "not_after": not_after}
        self._scope_hash = digest(self.scope)
        self.clock = clock or (lambda: (datetime.now(timezone.utc), time.monotonic()))
        self.last_wall, self.last_mono = None, None
        self.view, self.pending = None, None
        self.mutex = Lock()

    def now(self):
        wall, mono = self.clock()
        if (wall.tzinfo != timezone.utc or type(mono) not in (int, float) or not math.isfinite(mono)
                or (self.last_wall is not None and (wall < self.last_wall or mono < self.last_mono))):
            self.life.poison()
            raise Rejected("LIFECYCLE_BLOCKED")
        self.last_wall, self.last_mono = wall, mono
        if digest(self.scope) != self._scope_hash:
            self.life.poison()
            raise Rejected("SCOPE")
        return wall, mono

    def _load(self, gate, evidence_id):
        try:
            return getattr(self.store, "load_" + _METHODS[GATES.index(gate)])(evidence_id)
        except ApprovalStoreNotFoundError:
            return None
        except Exception as exc:
            self.life.poison()
            raise Rejected("STORE_UNAVAILABLE") from exc

    def _pair(self, gate, cell):
        records = tuple(self._load(gate, key) for key in cell.ids)
        for i, record in enumerate(records):
            if record is not None and (getattr(record, _ID_NAMES[GATES.index(gate)]) != cell.ids[i]
                                       or digest(record.authority_payload()) != cell.hashes[i]):
                self.life.poison()
                raise Rejected("CONFLICT")
        if all(r is not None for r in records):
            self.life.poison()
            raise Rejected("CONFLICT")
        if cell.state in {"CHOSEN", "RECORDED", "UNCERTAIN"}:
            index = int(cell.selected == "REJECTED")
            if records[1 - index] is not None or (cell.state == "RECORDED" and records[index] is None):
                self.life.poison()
                raise Rejected("CONFLICT")
            return records[index]
        if any(r is not None for r in records):
            self.life.poison()
            raise Rejected("CONFLICT")
        return None

    def _approved(self, slot, gate):
        cell = slot.cells[gate]
        if cell.state != "RECORDED":
            raise Rejected("SCOPE")
        record = self._pair(gate, cell)
        if record.decision is not ApprovalDecision.APPROVED:
            raise Rejected("SCOPE")
        return record

    def _display(self, slot, gate):
        self.intake.read_slot(slot)
        plan, attempt = slot.records[1], slot.records[3]
        semantic_join(slot.material, plan, slot.spec)
        if gate == "scientific":
            return {"calculation_plan_id": plan.calculation_plan_id, "task_id": plan.task_id,
                    "revision": plan.revision, **slot.material.display}
        scientific = self._approved(slot, "scientific")
        scientific.assert_current(plan, displayed_semantic_meaning=slot.material.display)
        if self.intake.store.attempt_state(attempt.attempt_id) is not AttemptState.PLANNED:
            raise Rejected("SCOPE")
        member = {"attempt_id": attempt.attempt_id, "task_id": plan.task_id,
                  "calculation_plan_id": plan.calculation_plan_id, "calculation_plan_revision": plan.revision,
                  "scientific_approval_id": scientific.scientific_approval_id}
        if gate == "batch":
            return {"members": [member]}
        batch = self._approved(slot, "batch")
        if len(batch.members) != 1 or copy_data(batch.member_for(attempt.attempt_id).payload()) != member:
            raise Rejected("CONFLICT")
        if slot.snapshot is None:
            raise Rejected("SCOPE")
        self._snapshot(slot, slot.snapshot)
        return {"snapshot": copy_data(slot.snapshot._approval_semantics()),
                "scientific_approval_id": scientific.scientific_approval_id,
                "batch_submit_approval_id": batch.batch_submit_approval_id,
                "scope": copy_data(self.scope)}

    def _snapshot(self, slot, snapshot):
        if type(snapshot) is not ProgramExecutionSnapshot:
            raise Rejected("MISSING_DEPENDENCY")
        snapshot.assert_identity_closed()
        snapshot._assert_current_core(self.intake.store)
        if (snapshot.attempt_id != slot.records[3].attempt_id
                or snapshot.calculation_plan_id != slot.records[1].calculation_plan_id
                or snapshot.resolved_resource_request.resource_spec_id != slot.records[2].resource_spec_id
                or snapshot.program_execution_spec != slot.spec
                or snapshot.resolved_server_profile != self.intake.profile):
            raise Rejected("CONFLICT")
        resources = snapshot.resolved_resource_request
        if (any(getattr(resources, k) != self.intake.resources[k] for k in ("cores", "memory_mb", "walltime_seconds", "queue"))
                or snapshot._completion_material() != self.intake.completion_material):
            raise Rejected("CONFLICT")
        semantic_join(slot.material, slot.records[1], snapshot.program_execution_spec)

    def bind_offline_snapshot(self, intake_id, snapshot):
        """In-process test composition only. No snapshot creation/provision RPC."""
        with self.life.composition():
            root = self.intake.root()
            slot = root.index.get(intake_id)
            if slot is None or slot.snapshot is not None:
                raise Rejected("SCOPE")
            self._approved(slot, "scientific")
            self._approved(slot, "batch")
            self._snapshot(slot, snapshot)
            slot.snapshot = slot._snapshot = snapshot
            slot.cells["operational"].subject = snapshot.program_execution_snapshot_id
            root.check()

    def _candidates(self, slot, gate, evidence):
        plan = slot.records[1]
        result = []
        for decision in (ApprovalDecision.APPROVED, ApprovalDecision.REJECTED):
            common = {"decision": decision, "reviewer_id": f"local-session:{self.uid}", "reviewer_evidence": evidence}
            if gate == "scientific":
                record = ScientificApproval.for_plan(self.intake.store, plan, displayed_semantic_meaning=slot.material.display, **common)
            elif gate == "batch":
                record = BatchSubmitApproval.for_existing_attempts(self.intake.store,
                    [(slot.records[3].attempt_id, self._approved(slot, "scientific"))], **common)
            else:
                record = ExactOperationalConfirmation.for_snapshot(self.intake.store, slot.snapshot,
                    confirmer_id=common["reviewer_id"], confirmer_evidence=evidence, decision=decision)
            result.append(record)
        return tuple(result)

    @staticmethod
    def _found(gate, cell, record):
        if record is None:
            return "ABSENT", None
        return "FOUND", {"gate": gate, "approval_id": cell.selected_id, "decision": record.decision.name,
                         "review_view_id": cell.view_id, "source_event_id": cell.event_id}

    def _expire(self, mono):
        if self.pending is not None:
            slot, gate = self.pending
            cell = slot.cells[gate]
            if self.view is None or self.view.slot is not slot or self.view.gate != gate or cell.state != "PENDING":
                self.life.poison()
                raise Rejected("LIFECYCLE_BLOCKED")
            if mono >= self.view.deadline:
                cell.state = "EXPIRED_UNDECIDED"
                self.pending = self.view = None

    def _check_views(self):
        root = self.intake.root()
        pending = [(s, gate) for s in root._allocated for gate in GATES if s.cells[gate].state == "PENDING"]
        if (len(pending) > 1 or (pending[0] if pending else None) != self.pending
                or (pending and (self.view is None or (self.view.slot, self.view.gate) != pending[0]))):
            self.life.poison()
            raise Rejected("LIFECYCLE_BLOCKED")
        if self.view is not None:
            view = self.view
            cell = view.slot.cells[view.gate]
            if (digest(view.payload["display"]) != cell.view_hash
                    or view.payload["review_view_id"] != cell.view_id
                    or (view.payload["approved_id"], view.payload["rejected_id"]) != cell.ids):
                self.life.poison()
                raise Rejected("LIFECYCLE_BLOCKED")

    def prepare(self, gate, subject):
        self._check_views()
        wall, mono = self.now()
        slot, cell = self.intake.root().subject(gate, subject)
        if cell.state in {"RECORDED", "CHOSEN", "UNCERTAIN"}:
            return self._found(gate, cell, self._pair(gate, cell))
        if self.life.state not in {"READY_CLOSED", "OPEN"}:
            raise Rejected("LIFECYCLE_BLOCKED")
        self._expire(mono)
        if self.pending is not None:
            if self.pending != (slot, gate):
                raise Rejected("BUSY")
            if digest(self._display(slot, gate)) != cell.view_hash:
                raise Rejected("STALE")
            self._pair(gate, cell)
            return "VIEW_READY", copy_data(self.view.payload)
        if cell.state not in {"UNPREPARED", "EXPIRED_UNDECIDED"} or cell.generation == MAX_GENERATION:
            raise Rejected("SCOPE")
        if cell.ids:
            self._pair(gate, cell)
        display = self._display(slot, gate)
        if gate == "operational" and wall > _parse_time(self.scope["not_before"]):
            raise Rejected("SCOPE")
        view_id, event_id, view_hash = str(uuid4()), str(uuid4()), digest(display)
        prepared_at, expires_at = _timestamp(wall), _timestamp(wall + timedelta(seconds=600))
        evidence = {"schema": "auto-g16-managed-review-evidence/2", "gate": gate,
                    "source_channel": "codex-human-relay", "source_event_id": event_id,
                    "review_view_id": view_id, "display_semantics_sha256": view_hash,
                    "writer_installation_sha256": self.installation_hash,
                    "prepared_at": prepared_at, "expires_at": expires_at}
        if gate == "operational":
            evidence.update(copy_data(self.scope))
        candidates = self._candidates(slot, gate, evidence)
        ids = tuple(getattr(r, _ID_NAMES[GATES.index(gate)]) for r in candidates)
        hashes = tuple(digest(r.authority_payload()) for r in candidates)
        payload = {"gate": gate, "subject_id": subject, "review_view_id": view_id, "view_sha256": view_hash,
                   "source_event_id": event_id, "prepared_at": prepared_at, "expires_at": expires_at,
                   "reviewer_id": f"local-session:{self.uid}", "display": display,
                   "approved_id": ids[0], "rejected_id": ids[1]}
        frame({"protocol": PROTOCOL, "operation": "PREPARE_REVIEW", "status": "VIEW_READY", "reason": "NONE", "payload": payload}, 262144)
        cell.generation += 1
        cell.state, cell.view_id, cell.event_id, cell.view_hash = "PENDING", view_id, event_id, view_hash
        cell.ids, cell.hashes = ids, hashes
        self.view = View(slot, gate, payload, candidates, mono + 600)
        self.pending = slot, gate
        self._pair(gate, cell)
        return "VIEW_READY", copy_data(payload)

    def decide(self, payload):
        exact(payload, {"review_view_id", "view_sha256", "source_event_id", "decision"})
        if payload["decision"] not in ("APPROVED", "REJECTED"):
            raise Rejected("BAD_FRAME")
        self._check_views()
        view = self.view
        if view is None or payload["review_view_id"] != view.payload["review_view_id"]:
            raise RequestRejected("UNKNOWN_VIEW")
        cell = view.slot.cells[view.gate]
        if payload["view_sha256"] != cell.view_hash or payload["source_event_id"] != cell.event_id:
            raise Rejected("SCOPE")
        if cell.state in {"CHOSEN", "RECORDED", "UNCERTAIN"}:
            if payload["decision"] != cell.selected:
                raise Rejected("CONFLICT")
            return self._found(view.gate, cell, self._pair(view.gate, cell))
        if self.life.state not in {"READY_CLOSED", "OPEN"}:
            raise Rejected("LIFECYCLE_BLOCKED")
        _wall, mono = self.now()
        self._expire(mono)
        if self.view is None:
            raise RequestRejected("EXPIRED")
        if cell.state != "PENDING" or digest(self._display(view.slot, view.gate)) != cell.view_hash:
            raise Rejected("STALE")
        self._pair(view.gate, cell)
        index = int(payload["decision"] == "REJECTED")
        record = view.candidates[index]
        if digest(record.authority_payload()) != cell.hashes[index]:
            self.life.poison()
            raise Rejected("CONFLICT")
        cell.state, cell.selected, cell.selected_id = "CHOSEN", payload["decision"], cell.ids[index]
        self.pending = None
        try:
            getattr(self.store, "store_" + _METHODS[GATES.index(view.gate)])(record)
            loaded = self._pair(view.gate, cell)
            if loaded is None:
                raise Rejected("STORE_UNAVAILABLE")
            cell.state = "RECORDED"
        except BaseException:
            cell.state = "UNCERTAIN"
            self.life.poison()
            raise
        _status, result = self._found(view.gate, cell, loaded)
        return "RECORDED", result

    def read(self, gate, approved_id, rejected_id):
        self._check_views()
        _slot, cell = self.intake.root().pair(gate, (approved_id, rejected_id))
        return self._found(gate, cell, self._pair(gate, cell))

    def request(self, raw, *, peer_uid, eof=True, ancillary=False):
        operation = None
        try:
            if type(peer_uid) is not int or peer_uid != self.uid:
                raise Rejected("BAD_PEER")
            data = decode_frame(raw, 16384, eof=eof, ancillary=ancillary)
            exact(data, {"protocol", "operation", "payload"})
            if data["protocol"] != PROTOCOL or data["operation"] not in ("PREPARE_REVIEW", "DECIDE", "READ_DECISION"):
                raise Rejected("BAD_FRAME")
            operation, payload = data["operation"], data["payload"]
            with self.life.composition(readonly=True):
                if not self.mutex.acquire(False):
                    raise Rejected("BUSY")
                try:
                    if operation == "PREPARE_REVIEW":
                        exact(payload, {"gate", "subject_id"})
                        status, result = self.prepare(payload["gate"], payload["subject_id"])
                    elif operation == "DECIDE":
                        status, result = self.decide(payload)
                    else:
                        exact(payload, {"gate", "approved_id", "rejected_id"})
                        status, result = self.read(payload["gate"], payload["approved_id"], payload["rejected_id"])
                finally:
                    self.mutex.release()
            reason = "NONE"
        except Rejected as exc:
            # A2 cannot expose MISSING_DEPENDENCY: the review owner cannot
            # load its current materials. Preserve any existing poison veto.
            reasons = {
                "BAD_FRAME": "BAD_FRAME", "BAD_PEER": "BAD_PEER",
                "BUSY": "BUSY", "UNKNOWN_VIEW": "UNKNOWN_VIEW",
                "EXPIRED": "EXPIRED", "STALE": "STALE", "SCOPE": "SCOPE",
                "CONFLICT": "CONFLICT", "STORE_UNAVAILABLE": "STORE_UNAVAILABLE",
                "LIFECYCLE_BLOCKED": "LIFECYCLE_BLOCKED",
                "MISSING_DEPENDENCY": "STORE_UNAVAILABLE",
                "INCOMPLETE": "STORE_UNAVAILABLE", "BAD_MATERIAL": "STALE",
            }
            reason = reasons.get(exc.reason, "STORE_UNAVAILABLE") if isinstance(exc.reason, str) else "STORE_UNAVAILABLE"
            status, result = "REJECTED", None
        except Exception:
            self.life.poison()
            status, reason, result = "UNCERTAIN", "STORE_UNAVAILABLE", None
        return frame({"protocol": PROTOCOL, "operation": operation, "status": status, "reason": reason, "payload": result}, 262144)

    def validate_execution(self, intake_id, *, ids, peer_uid):
        """Call only while C is held; validation does not claim or execute."""
        from threading import get_ident
        if self.life.owner != get_ident() or self.life.state != "OPEN":
            raise Rejected("LIFECYCLE_BLOCKED")
        wall, _mono = self.now()
        slot = self.intake.root().index.get(intake_id)
        if slot is None or slot.snapshot is None:
            raise Rejected("SCOPE")
        self.intake.read_slot(slot)
        if tuple(ids) != tuple(slot.cells[g].selected_id for g in GATES):
            raise Rejected("SCOPE")
        scientific, batch, operational = (self._approved(slot, gate) for gate in GATES)
        if type(peer_uid) is not int or peer_uid not in self.scope["requester_uids"] or not _parse_time(self.scope["not_before"]) <= wall <= _parse_time(self.scope["not_after"]):
            raise Rejected("SCOPE")
        self._snapshot(slot, slot.snapshot)
        validate_effect_authority(runtime_store=self.intake.store, attempt=slot.records[3], plan=slot.records[1],
            displayed_semantic_meaning=slot.material.display, scientific_approval=scientific,
            batch_submit_approval=batch, execution_snapshot=slot.snapshot, operational_confirmation=operational)
        return slot.snapshot

    def recheck_launch_scope(self, intake_id, *, ids, peer_uid):
        """Narrow post-claim check; never creates claim/START or retry authority."""
        from threading import get_ident
        if self.life.owner != get_ident() or self.life.state != "OPEN":
            raise Rejected("LIFECYCLE_BLOCKED")
        wall, _mono = self.now()
        slot = self.intake.root().index.get(intake_id)
        if slot is None or slot.snapshot is None or tuple(ids) != tuple(slot.cells[g].selected_id for g in GATES):
            raise Rejected("SCOPE")
        self.intake.read_slot(slot)
        scientific, batch, operational = (self._approved(slot, g) for g in GATES)
        scientific.assert_current(slot.records[1], displayed_semantic_meaning=slot.material.display)
        member = batch.member_for(slot.records[3].attempt_id)
        if len(batch.members) != 1 or member.scientific_approval_id != scientific.scientific_approval_id or member.calculation_plan_id != slot.records[1].calculation_plan_id:
            raise Rejected("CONFLICT")
        self._snapshot(slot, slot.snapshot)
        operational.assert_current(self.intake.store, slot.snapshot)
        if type(peer_uid) is not int or peer_uid not in self.scope["requester_uids"] or not _parse_time(self.scope["not_before"]) <= wall <= _parse_time(self.scope["not_after"]):
            raise Rejected("SCOPE")


class HumanRelay:
    """Explicit current-user-event adapter, not human authentication.

    Caller must display returned text completely in the same task and supply
    the actual subsequent user event. No logs, transcript scanning or default.
    Anyone controlling this trusted caller can forge source_role; that is the
    accepted source assumption, not a signed Codex API.
    """
    def __init__(self, review, task_id):
        if not isinstance(task_id, str) or not task_id:
            raise Rejected("SCOPE")
        self.review, self.task_id, self.shown = review, task_id, None

    def display(self, response):
        value = decode_frame(response, 262144, eof=True)
        exact(value, {"protocol", "operation", "status", "reason", "payload"})
        if value["protocol"] != PROTOCOL or value["operation"] != "PREPARE_REVIEW" or value["status"] != "VIEW_READY" or value["reason"] != "NONE":
            raise Rejected("SCOPE")
        exact(value["payload"], {"gate", "subject_id", "review_view_id", "view_sha256", "source_event_id",
                                 "prepared_at", "expires_at", "reviewer_id", "display", "approved_id", "rejected_id"})
        if digest(value["payload"]["display"]) != value["payload"]["view_sha256"]:
            raise Rejected("STALE")
        self.shown = copy_data(value["payload"])
        return json_bytes(self.shown).decode("utf-8")

    def transcribe(self, *, task_id, source_role, displayed_text, reply):
        view = self.shown
        if task_id != self.task_id or source_role != "user" or view is None or displayed_text != json_bytes(view).decode("utf-8"):
            raise Rejected("SCOPE")
        choices = {f"{word} {view['gate']} {view['review_view_id']}": decision
                   for word, decision in (("批准", "APPROVED"), ("拒绝", "REJECTED"))}
        if reply not in choices:
            raise Rejected("SCOPE")
        payload = {k: view[k] for k in ("review_view_id", "view_sha256", "source_event_id")}
        payload["decision"] = choices[reply]
        self.shown = None
        return self.review.request(frame({"protocol": PROTOCOL, "operation": "DECIDE", "payload": payload}, 16384), peer_uid=self.review.uid)
