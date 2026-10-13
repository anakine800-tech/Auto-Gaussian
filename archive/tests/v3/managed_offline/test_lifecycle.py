from threading import Event, Thread
import unittest
from unittest.mock import patch

from auto_g16 import core, execution
from auto_g16.execution.program_runtime import _ProgramExecutionPort
from auto_g16.transport.program import _ProgramEffectUnknown, _ProgramTransportStore
from auto_g16._managed_offline.common import Rejected
from auto_g16._managed_offline.lifecycle import FakeInstallation, FakeNative, Lifecycle
from tests.v31.transport.test_program_composition import _Driver
from ._fixtures import Fixture


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.installation, self.native = FakeInstallation(), FakeNative()
        self.life = Lifecycle.offline(self.installation, self.native)
        self.addCleanup(self.life.close)

    def test_production_constructor_and_non_closed_adapter_cannot_activate(self):
        with self.assertRaisesRegex(Rejected, "NATIVE_NOT_QUALIFIED"):
            Lifecycle()
        with self.assertRaises(Rejected):
            Lifecycle.offline(self.installation, lambda: None)
        self.assertEqual(self.life.state, "READY_CLOSED")
        with self.life.composition(), self.assertRaises(Rejected):
            self.life.launch("normal")
        self.assertEqual(self.native.shapes, [])

    def test_stop_first_prevents_both_shapes_and_never_reopens(self):
        self.life.manage("OPEN", peer_uid=0)
        with self.life.composition():
            self.assertEqual(self.life.manage("STOP", peer_uid=0), "STOPPED")
            for shape in ("normal", "recovery"):
                with self.assertRaises(Rejected):
                    self.life.launch(shape)
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual(self.native.shapes, [])

    def test_launch_first_stop_busy_until_handle_registered_then_no_next_launch(self):
        for shape in ("normal", "recovery"):
            with self.subTest(shape=shape):
                installation, native = FakeInstallation(), FakeNative()
                life = Lifecycle.offline(installation, native)
                life.manage("OPEN", peer_uid=0)
                native.entered, native.release = Event(), Event()
                errors = []
                def run():
                    try:
                        with life.composition():
                            life.launch(shape)
                    except Exception as exc:
                        errors.append(exc)
                thread = Thread(target=run)
                thread.start()
                self.assertTrue(native.entered.wait(2))
                with self.assertRaisesRegex(Rejected, "BUSY"):
                    life.manage("STOP", peer_uid=0)
                with self.assertRaisesRegex(Rejected, "BUSY"), life.composition():
                    pass
                native.release.set()
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(life.children), 1)
                self.assertEqual(life.manage("STOP", peer_uid=0), "STOPPED")
                with self.assertRaises(Rejected), life.composition():
                    pass
                self.assertEqual(native.shapes, [shape])
                life.close()

    def test_exception_and_restart_poison_permanent_memory_model_only(self):
        self.life.manage("OPEN", peer_uid=0)
        self.native.fail = True
        with self.life.composition(), self.assertRaises(Rejected):
            self.life.launch("recovery")
        self.assertEqual(self.life.state, "BLOCKED")
        self.life.close()
        restarted = Lifecycle.offline(self.installation, FakeNative())
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.state, "BLOCKED")
        with self.assertRaises(Rejected):
            restarted.manage("OPEN", peer_uid=0)

    def test_poison_latch_wins_even_after_open_has_read_ready_state(self):
        # Pause exactly after OPEN reads READY, before its assignment; no GIL claim.
        read_ready, continue_open = Event(), Event()
        original = Lifecycle.state
        def getter(value):
            state = original.fget(value)
            if state == "READY_CLOSED":
                read_ready.set()
                if not continue_open.wait(2):
                    raise AssertionError("missing synchronization")
            return state
        outcome = []
        with patch.object(Lifecycle, "state", property(getter, original.fset)):
            thread = Thread(target=lambda: outcome.append(self.life.manage("OPEN", peer_uid=0)))
            thread.start()
            self.assertTrue(read_ready.wait(2))
            self.life.poison()
            continue_open.set()
            thread.join(3)
        self.assertEqual(outcome, ["BLOCKED"])
        self.assertEqual(self.life.state, "BLOCKED")
        with self.assertRaises(Rejected), self.life.composition():
            pass

    def test_identity_failure_is_latched_after_field_is_restored(self):
        self.installation.valid = False
        with self.assertRaises(Rejected):
            self.life.manage("STATUS", peer_uid=0)
        self.installation.valid = True
        with self.assertRaises(Rejected):
            self.life.manage("OPEN", peer_uid=0)
        self.assertEqual(self.life.state, "BLOCKED")

    def test_peer_unknown_opcode_and_g_overlap_fail_closed(self):
        for uid in (501, True, "0"):
            with self.assertRaises(Rejected):
                self.life.manage("OPEN", peer_uid=uid)
        with self.assertRaises(Rejected):
            self.life.manage("RESET", peer_uid=0)
        duplicate = Lifecycle.offline(self.installation, FakeNative())
        self.addCleanup(duplicate.close)
        self.assertEqual(duplicate.state, "BLOCKED")


class OwnerCompositionTests(Fixture):
    def _execute(self, slot, ids, *, uncertain=False, stop_before_first=False):
        """Use existing privileged synthetic driver seam; no production changes."""
        outer = self
        class GuardedSyntheticDriver(_Driver):
            def _record(self, operation, request):
                if stop_before_first:
                    outer.life.manage("STOP", peer_uid=0)
                outer.review.recheck_launch_scope(slot.key[2], ids=ids, peer_uid=501)
                outer.life.launch("normal")
                super()._record(operation, request)
        driver = GuardedSyntheticDriver()
        if uncertain:
            driver.raise_operation = ("SUBMIT_QSUB_ONCE", _ProgramEffectUnknown("synthetic ambiguity"))
        transport = _ProgramTransportStore._create_completion_store(self.root / "transport" / "program.sqlite3", approved_root=self.root / "transport")
        self.addCleanup(transport.close)
        with self.life.composition():
            snapshot = self.review.validate_execution(slot.key[2], ids=ids, peer_uid=501)
            result = execution.execute_once(self.core, snapshot=snapshot, current_profile=self.profile,
                prepared_input_bytes=slot.material.xyz, pbs_template_bytes=snapshot.scheduler_artifacts[0]["content_utf8"].encode(),
                confirmed_execution_snapshot_id=snapshot.program_execution_snapshot_id,
                port=_ProgramExecutionPort(snapshot=snapshot, program_transport_store=transport, driver=driver))
        return result, driver, transport

    def test_existing_owner_executes_synthetic_chain_claims_once_and_rejects_second_admission(self):
        slot, ids = self.chain()
        self.clock.advance(1200)
        self.life.manage("OPEN", peer_uid=0)
        result, driver, _transport = self._execute(slot, ids)
        self.assertEqual(result.claim, core.SubmissionIntentClaim.WINNER)
        self.assertEqual(result.attempt_state, core.AttemptState.SUBMITTED)
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in driver.calls), 1)
        count = len(self.native.shapes)
        with self.life.composition(), self.assertRaises(Exception):
            self.review.validate_execution(slot.key[2], ids=ids, peer_uid=501)
        self.assertEqual(len(self.native.shapes), count)

    def test_unknown_has_no_second_wire_or_replacement_attempt(self):
        slot, ids = self.chain()
        self.clock.advance(1200)
        self.life.manage("OPEN", peer_uid=0)
        result, driver, _transport = self._execute(slot, ids, uncertain=True)
        self.assertEqual(result.attempt_state, core.AttemptState.UNKNOWN)
        count = len(self.native.shapes)
        with self.life.composition(), self.assertRaises(Exception):
            self.review.validate_execution(slot.key[2], ids=ids, peer_uid=501)
        self.assertEqual(len(self.native.shapes), count)
        self.assertEqual(self.registry.allocated_count, 1)
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in driver.calls), 1)

    def test_stop_after_core_claim_preserves_consumed_state_without_wire(self):
        slot, ids = self.chain()
        self.clock.advance(1200)
        self.life.manage("OPEN", peer_uid=0)
        result, driver, _transport = self._execute(slot, ids, stop_before_first=True)
        self.assertEqual(result.claim, core.SubmissionIntentClaim.WINNER)
        self.assertNotEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)
        self.assertEqual(driver.calls, [])
        self.assertEqual(self.native.shapes, [])
