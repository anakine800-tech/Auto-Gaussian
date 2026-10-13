from datetime import timedelta
from unittest.mock import patch

from auto_g16.approval import ApprovalStoreNotFoundError
from auto_g16._managed_offline.common import Rejected, decode_frame, frame, json_bytes
from auto_g16._managed_offline.registry import CAPACITY, MAX_GENERATION
from auto_g16._managed_offline.review import HumanRelay, PROTOCOL
from ._fixtures import Fixture, payload


class ReviewTests(Fixture):
    def test_missing_profile_review_uses_closed_store_unavailable_reason(self):
        slot = self.make()
        self.intake.profile = None
        result = self.prepare(slot, "scientific")
        self.assertEqual((result["status"], result["reason"], result["payload"]),
                         ("REJECTED", "STORE_UNAVAILABLE", None))
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(slot.cells["scientific"].state, "UNPREPARED")
        self.assertEqual(self.registry.allocated_count, 1)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.native.shapes, [])

    def test_review_internal_rejections_never_extend_wire_reason_enum(self):
        allowed = {"NONE", "BAD_FRAME", "BAD_PEER", "BUSY", "UNKNOWN_VIEW", "EXPIRED",
                   "STALE", "SCOPE", "CONFLICT", "STORE_UNAVAILABLE", "LIFECYCLE_BLOCKED"}
        cases = [(x, x) for x in sorted(allowed - {"NONE"})]
        cases += [("MISSING_DEPENDENCY", "STORE_UNAVAILABLE"), ("INCOMPLETE", "STORE_UNAVAILABLE"),
                  ("BAD_MATERIAL", "STALE"), ("UNKNOWN_INTERNAL", "STORE_UNAVAILABLE"),
                  ("NONE", "STORE_UNAVAILABLE"), (None, "STORE_UNAVAILABLE"), ([], "STORE_UNAVAILABLE")]
        self.life.poison()
        for internal, expected in cases:
            with self.subTest(internal=internal), patch.object(self.review, "prepare", side_effect=Rejected(internal)) as prepare:
                result = self.rpc("PREPARE_REVIEW", {"gate": "scientific", "subject_id": "missing"})
                self.assertIn(result["reason"], allowed)
                self.assertEqual(result["reason"], expected)
                self.assertEqual(result["status"], "REJECTED")
                self.assertIsNone(result["payload"])
                prepare.assert_called_once()
                self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.registry.allocated_count, 0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.native.shapes, [])

    def test_root_cannot_be_reinitialized_in_same_lifetime(self):
        from auto_g16._managed_offline.registry import Registry
        with self.assertRaises(Rejected):
            Registry(self.life, "a" * 64)

    def test_lost_pending_association_blocks_instead_of_reopening(self):
        slot = self.make()
        self.prepare(slot, "scientific")
        self.review.pending = None
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "LIFECYCLE_BLOCKED")

    def test_modified_relay_display_rejected_even_when_ids_unchanged(self):
        slot = self.make()
        result = self.prepare(slot, "scientific")
        result["payload"]["display"]["intent"]["model"] = "gfn1"
        with self.assertRaises(Rejected):
            HumanRelay(self.review, "task").display(frame(result, 262144))

    def test_pending_composition_busy_no_second_write(self):
        from threading import Thread
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        results = []
        with self.life.composition():
            thread = Thread(target=lambda: results.append(self.decide(view)))
            thread.start()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["reason"], "BUSY")
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.decide(view)["status"], "RECORDED")

    def test_rejection_survives_other_view_eviction_and_no_client_ids(self):
        a, b = self.make(), self.make()
        view = self.prepare(a, "scientific")["payload"]
        rejected = self.decide(view, "REJECTED")
        self.assertEqual(rejected["status"], "RECORDED")
        bview = self.prepare(b, "scientific")
        found = self.prepare(a, "scientific")
        self.assertEqual(found["status"], "FOUND")
        self.assertEqual(found["payload"]["approval_id"], view["rejected_id"])
        self.assertEqual(found["payload"]["decision"], "REJECTED")
        self.assertEqual(self.decide(view)["reason"], "UNKNOWN_VIEW")
        self.decide(bview["payload"])
        self.assertEqual(self.prepare(a, "batch")["reason"], "SCOPE")
        self.assertEqual(self.approvals.evidence_count(), 2)

    def test_interleaved_bundles_keep_original_ids_through_all_three_gates(self):
        a, b = self.make(model="gfn1"), self.make(model="gfn2")
        a_s, b_s = self.approve(a, "scientific"), self.approve(b, "scientific")
        a_b, b_b = self.approve(a, "batch"), self.approve(b, "batch")
        self.bind_snapshot(a)
        self.bind_snapshot(b)
        a_o, b_o = self.approve(a, "operational"), self.approve(b, "operational")
        for slot, ids in ((a, (a_s, a_b, a_o)), (b, (b_s, b_b, b_o))):
            for gate, key in zip(("scientific", "batch", "operational"), ids):
                self.assertEqual(self.prepare(slot, gate)["payload"]["approval_id"], key)
            member = self.approvals.load_batch_submit_approval(ids[1]).members[0]
            self.assertEqual(member.scientific_approval_id, ids[0])
            self.assertEqual(member.attempt_id, slot.records[3].attempt_id)
        self.clock.advance(1200)
        self.life.manage("OPEN", peer_uid=0)
        with self.life.composition():
            self.assertIs(self.review.validate_execution(a.key[2], ids=(a_s, a_b, a_o), peer_uid=501), a.snapshot)
            with self.assertRaises(Rejected):
                self.review.validate_execution(a.key[2], ids=(b_s, b_b, b_o), peer_uid=501)
        self.assertEqual(self.approvals.evidence_count(), 6)

    def test_repeated_decision_only_reads_and_opposite_rejected(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        with patch.object(self.approvals, "store_scientific_approval", wraps=self.approvals.store_scientific_approval) as write:
            self.assertEqual(self.decide(view)["status"], "RECORDED")
            self.assertEqual(self.decide(view)["status"], "FOUND")
            self.assertEqual(self.decide(view, "REJECTED")["reason"], "CONFLICT")
            self.assertEqual(write.call_count, 1)

    def test_write_failure_before_commit_absent_never_reopens(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        cell = slot.cells["scientific"]
        def fail(record):
            self.assertEqual(cell.state, "CHOSEN")
            self.assertEqual(cell.selected_id, record.scientific_approval_id)
            raise OSError("injected")
        with patch.object(self.approvals, "store_scientific_approval", side_effect=fail) as write:
            self.assertEqual(self.decide(view)["status"], "UNCERTAIN")
            self.assertEqual(self.decide(view)["status"], "ABSENT")
            self.assertEqual(self.prepare(slot, "scientific")["status"], "ABSENT")
            self.assertEqual(write.call_count, 1)
        self.assertEqual(cell.state, "UNCERTAIN")
        self.assertEqual(self.life.state, "BLOCKED")

    def test_write_commits_then_raises_found_still_blocked_and_never_rewrites(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        original = self.approvals.store_scientific_approval
        def lost(record):
            original(record)
            raise OSError("lost acknowledgement")
        with patch.object(self.approvals, "store_scientific_approval", side_effect=lost) as write:
            self.assertEqual(self.decide(view)["status"], "UNCERTAIN")
            self.assertEqual(self.prepare(slot, "scientific")["status"], "FOUND")
            self.assertEqual(self.decide(view)["status"], "FOUND")
            self.assertEqual(write.call_count, 1)
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.approvals.evidence_count(), 1)

    def test_recorded_loss_not_absent_and_downstream_blocked(self):
        slot = self.make()
        key = self.approve(slot, "scientific")
        with patch.object(self.approvals, "load_scientific_approval", side_effect=ApprovalStoreNotFoundError(key)):
            self.assertEqual(self.prepare(slot, "scientific")["reason"], "CONFLICT")
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.prepare(slot, "batch")["reason"], "LIFECYCLE_BLOCKED")

    def test_opposite_record_or_foreign_record_blocks(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        candidates = self.review.view.candidates
        self.decide(view)
        self.approvals.store_scientific_approval(candidates[1])
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "CONFLICT")
        self.assertEqual(self.life.state, "BLOCKED")

    def test_unselected_preexisting_candidate_not_adopted(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        self.approvals.store_scientific_approval(self.review.view.candidates[0])
        self.assertEqual(self.decide(view)["reason"], "CONFLICT")
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertIsNone(slot.cells["scientific"].selected_id)

    def test_expired_generation_cannot_decide_old_event(self):
        slot = self.make()
        old = self.prepare(slot, "scientific")["payload"]
        self.assertEqual(self.prepare(slot, "scientific")["payload"], old)
        self.clock.advance(600)
        self.assertEqual(self.decide(old)["reason"], "EXPIRED")
        new = self.prepare(slot, "scientific")["payload"]
        self.assertNotEqual(old["approved_id"], new["approved_id"])
        self.assertEqual(slot.cells["scientific"].generation, 2)
        self.assertEqual(self.decide(old)["reason"], "UNKNOWN_VIEW")
        self.assertEqual(self.decide(new)["status"], "RECORDED")

    def test_generation_exhaustion_and_unknown_subject_no_allocation(self):
        slot = self.make()
        slot.cells["scientific"].generation = MAX_GENERATION
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "SCOPE")
        result = self.rpc("PREPARE_REVIEW", {"gate": "scientific", "subject_id": "unknown"})
        self.assertEqual(result["reason"], "SCOPE")
        self.assertEqual(self.registry.allocated_count, 1)

    def test_capacity_including_incomplete_slots_refuses_before_writes(self):
        from auto_g16._managed_offline.material import validate_material, build_spec
        with self.life.composition():
            for _ in range(CAPACITY):
                m = validate_material(payload())
                slot = self.registry.reserve(m, self.intake._records(m), build_spec(m, self.resolved))
                slot.state = "INCOMPLETE"
        with patch.object(self.intake.files, "create", side_effect=AssertionError("no file write")), patch.object(self.core, "store_task", side_effect=AssertionError("no Core write")):
            with self.assertRaisesRegex(Rejected, "BUSY"):
                self.intake.prepare(payload())
        self.assertEqual(self.registry.allocated_count, CAPACITY)

    def test_missing_root_refuses_even_with_valid_client_ids(self):
        slot = self.make()
        view = self.prepare(slot, "scientific")["payload"]
        self.decide(view)
        self.intake.registry = None
        found = self.rpc("READ_DECISION", {"gate": "scientific", "approved_id": view["approved_id"], "rejected_id": view["rejected_id"]})
        self.assertEqual(found["reason"], "LIFECYCLE_BLOCKED")
        self.assertEqual(self.life.state, "BLOCKED")

    def test_registry_missing_cell_index_slot_or_count_corruption(self):
        slot = self.make()
        mutations = [(lambda: slot.cells.pop("batch"), lambda value: slot.cells.update(batch=value)),
                     (lambda: self.registry.index.pop(slot.key[2]), lambda value: self.registry.index.update({slot.key[2]: value})),
                     (lambda: self.registry.slots.pop(0), lambda value: self.registry.slots.insert(0, value))]
        for damage, restore in mutations:
            value = damage()
            with self.assertRaises(Rejected):
                self.registry.check()
            restore(value)
        self.registry.allocated_count = 0
        with self.assertRaises(Rejected):
            self.registry.check()
        self.assertEqual(self.life.state, "BLOCKED")

    def test_pending_view_cache_loss_blocks_and_wrong_pair_never_queries_store(self):
        slot = self.make()
        self.prepare(slot, "scientific")
        with patch.object(self.approvals, "load_scientific_approval", side_effect=AssertionError("no scan")):
            response = self.rpc("READ_DECISION", {"gate": "scientific", "approved_id": "foreign", "rejected_id": "foreign"})
            self.assertEqual(response["reason"], "SCOPE")
        self.review.view = None
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "LIFECYCLE_BLOCKED")

    def test_complete_current_human_relay_rejects_old_ambiguous_model_tool_and_truncation(self):
        slot = self.make()
        raw = self.review.request(frame({"protocol": PROTOCOL, "operation": "PREPARE_REVIEW", "payload": {"gate": "scientific", "subject_id": slot.cells["scientific"].subject}}, 16384), peer_uid=501)
        relay = HumanRelay(self.review, "current-task")
        text = relay.display(raw)
        view = relay.shown
        good = {"task_id": "current-task", "source_role": "user", "displayed_text": text,
                "reply": f"批准 scientific {view['review_view_id']}"}
        for delta in ({"task_id": "old-task"}, {"source_role": "assistant"}, {"source_role": "tool"},
                      {"reply": "继续"}, {"reply": "approved"}, {"displayed_text": text[:100]}):
            with self.assertRaises(Rejected):
                relay.transcribe(**{**good, **delta})
        self.assertEqual(self.approvals.evidence_count(), 0)
        answer = decode_frame(relay.transcribe(**good), 262144, eof=True)
        self.assertEqual(answer["status"], "RECORDED")
        with self.assertRaises(Rejected):
            relay.transcribe(**good)

    def test_no_operational_snapshot_and_window_or_uid_denied(self):
        slot = self.make()
        self.approve(slot, "scientific")
        self.approve(slot, "batch")
        self.assertEqual(self.prepare(slot, "operational")["reason"], "SCOPE")
        self.bind_snapshot(slot)
        self.approve(slot, "operational")
        ids = tuple(slot.cells[g].selected_id for g in ("scientific", "batch", "operational"))
        self.life.manage("OPEN", peer_uid=0)
        with self.life.composition(), self.assertRaises(Rejected):
            self.review.validate_execution(slot.key[2], ids=ids, peer_uid=501)
        self.clock.advance(1200)
        with self.life.composition(), self.assertRaises(Rejected):
            self.review.validate_execution(slot.key[2], ids=ids, peer_uid=502)
        self.clock.advance(2401)
        with self.life.composition(), self.assertRaises(Rejected):
            self.review.validate_execution(slot.key[2], ids=ids, peer_uid=501)

    def test_clock_rollback_blocks_lifetime(self):
        slot = self.make()
        self.prepare(slot, "scientific")
        self.clock.wall -= timedelta(seconds=1)
        self.assertEqual(self.prepare(slot, "scientific")["reason"], "LIFECYCLE_BLOCKED")

    def test_closed_frame_rejections_zero_approval_writes(self):
        data = {"protocol": PROTOCOL, "operation": "PREPARE_REVIEW", "payload": {"gate": "scientific", "subject_id": "none"}}
        good = frame(data, 16384)
        duplicate = b'{"operation":"READ_DECISION","operation":"DECIDE","payload":{},"protocol":"auto-g16-review-bridge/1"}'
        bad = [good + b"x", good[:-1], (16385).to_bytes(4, "big") + b"x", len(duplicate).to_bytes(4, "big") + duplicate]
        bad.append(frame({**data, "approved": True}, 16384))
        for raw in bad:
            reply = decode_frame(self.review.request(raw, peer_uid=501), 262144, eof=True)
            self.assertEqual(reply["reason"], "BAD_FRAME")
        for opts in ({"eof": False}, {"ancillary": True}, {"peer_uid": 502}):
            reply = decode_frame(self.review.request(good, **{"peer_uid": 501, **opts}), 262144, eof=True)
            self.assertEqual(reply["status"], "REJECTED")
        self.assertEqual(self.approvals.evidence_count(), 0)
