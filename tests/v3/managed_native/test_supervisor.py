"""Adversarial call-order evidence only, never Darwin process evidence."""

from types import SimpleNamespace
import unittest

from auto_g16._managed_native.lifecycle import Lifecycle
from auto_g16._managed_native.supervisor import Observation, Supervisor
from auto_g16._managed_offline.common import Rejected


class Veto:
    def __init__(self):
        self.used = False
        self.valid = True
    def establish(self):
        if self.used:
            raise Rejected("LIFECYCLE_BLOCKED")
        self.used = True
    def check(self):
        if not self.valid:
            raise Rejected("LIFECYCLE_BLOCKED")


class Adapter:
    def __init__(self):
        self.calls = []
        self.handle = object()
        self.events = [Observation(37, True, exit_status=0)]
        self.peek = 0
        self.reap = 0
        self.fail_at = None
        self.after_spawn = None
    def step(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise OSError("injected native failure")
    def check_reaper(self): self.step("check_reaper")
    def spawn_suspended(self):
        self.step("spawn")
        if self.after_spawn: self.after_spawn()
        return self.handle
    def register(self, h): self.step("register")
    def resume(self, h): self.step("resume")
    def record_owner(self, h): self.step("owner")
    def observe(self, h):
        self.step("observe")
        return self.events.pop(0) if self.events else None
    def pid(self, h): return 37
    def write(self, h, data): self.step("write"); return len(data)
    def close_input(self, h): self.step("input_eof")
    def read(self, h, name, cap): self.step(name + "_eof"); return b""
    def peek_exit(self, h): self.step("peek"); return self.peek
    def reap_once(self, h): self.step("reap"); return self.reap
    def release(self, h): self.step("release")
    def pause(self, seconds): self.step("pause")


class SupervisorTests(unittest.TestCase):
    def setup_case(self):
        life = Lifecycle(object(), Veto())
        life.manage("OPEN", peer_uid=0)
        adapter = Adapter()
        supervisor = Supervisor(adapter, life.poison)
        operation = SimpleNamespace(stdin_cap=16, stdout_cap=16, stderr_cap=16, timeout_seconds=1)
        return life, adapter, supervisor, operation

    def test_normal_exit_peek_precedes_one_reap_and_release(self):
        life, adapter, supervisor, op = self.setup_case()
        with life.composition():
            life.launch(supervisor, b"request", op, lambda: adapter.step("original_owner_recheck"))
            self.assertEqual(supervisor.finish(), (b"", b"", 0, "completed", True, True))
        calls = adapter.calls
        self.assertEqual(calls[:6], ["original_owner_recheck", "check_reaper", "spawn", "register", "resume", "owner"])
        self.assertLess(calls.index("observe"), calls.index("peek"))
        self.assertLess(calls.index("stderr_eof"), calls.index("peek"))
        self.assertEqual(calls.count("reap"), 1)
        self.assertEqual(calls[-1], "release")
        self.assertEqual(life.state, "OPEN")

    def test_stop_during_creation_is_busy_not_success(self):
        life, adapter, supervisor, op = self.setup_case()
        def stopped():
            with self.assertRaisesRegex(Rejected, "BUSY"):
                life.manage("STOP", peer_uid=0)
        adapter.after_spawn = stopped
        with life.composition(): life.launch(supervisor, b"x", op, lambda: None)
        self.assertEqual(life.manage("STOP", peer_uid=0), "STOPPED")

    def test_stop_before_launch_consumes_no_child(self):
        life, adapter, supervisor, op = self.setup_case()
        with life.composition():
            life.manage("STOP", peer_uid=0)
            with self.assertRaises(Rejected): life.launch(supervisor, b"x", op, lambda: None)
        self.assertNotIn("spawn", adapter.calls)

    def test_registration_and_resume_failures_permanently_poison(self):
        for failure in ("spawn", "register", "resume", "owner"):
            with self.subTest(failure=failure):
                life, adapter, supervisor, op = self.setup_case()
                adapter.fail_at = failure
                with life.composition():
                    with self.assertRaises(OSError): life.launch(supervisor, b"x", op, lambda: None)
                self.assertEqual(life.state, "BLOCKED")
                self.assertIn(supervisor, life.children)
                with self.assertRaises(Rejected): life.manage("OPEN", peer_uid=0)

    def test_fork_exec_fault_or_mismatched_pid_never_reap(self):
        for event in (Observation(37, True, fork=True, exit_status=0),
                      Observation(37, True, exec=True, exit_status=0),
                      Observation(37, True, fault=True),
                      Observation(38, True, exit_status=0), Observation(37, False, exit_status=0)):
            with self.subTest(event=event):
                life, adapter, supervisor, op = self.setup_case()
                adapter.events = [event, Observation(37, True, exit_status=0)]
                with life.composition():
                    life.launch(supervisor, b"x", op, lambda: None)
                    with self.assertRaises(Rejected): supervisor.finish()
                self.assertEqual(life.state, "BLOCKED")
                self.assertNotIn("reap", adapter.calls)
                self.assertTrue(supervisor.retain_unknown()["original_handle_retained"])

    def test_missing_or_conflicting_waitid_is_not_exit(self):
        for peek in (None, 1, -9):
            with self.subTest(peek=peek):
                life, adapter, supervisor, op = self.setup_case()
                adapter.peek = peek
                with life.composition():
                    life.launch(supervisor, b"x", op, lambda: None)
                    with self.assertRaises(Rejected): supervisor.finish()
                self.assertNotIn("reap", adapter.calls)
                self.assertEqual(life.state, "BLOCKED")

    def test_echild_or_eperm_does_not_release(self):
        for failure in ("check_reaper", "observe", "peek", "reap"):
            with self.subTest(failure=failure):
                life, adapter, supervisor, op = self.setup_case()
                with life.composition():
                    life.launch(supervisor, b"x", op, lambda: None)
                    adapter.fail_at = failure
                    with self.assertRaises(OSError): supervisor.finish()
                self.assertNotIn("release", adapter.calls)
                self.assertEqual(life.state, "BLOCKED")

    def test_second_observation_cannot_erase_prior_or_late_fault(self):
        life, adapter, supervisor, op = self.setup_case()
        adapter.events.append(Observation(37, True, fork=True, exit_status=0))
        with life.composition():
            life.launch(supervisor, b"x", op, lambda: None)
            with self.assertRaises(Rejected): supervisor.finish()
        self.assertNotIn("reap", adapter.calls)

    def test_veto_restart_and_identity_drift(self):
        veto = Veto()
        life = Lifecycle(object(), veto)
        with self.assertRaises(Rejected): Lifecycle(object(), veto)
        veto.valid = False
        with self.assertRaises(Rejected): life.manage("OPEN", peer_uid=0)
        self.assertEqual(life.state, "BLOCKED")

    def test_unprivileged_management_and_reopen_rejected(self):
        life = Lifecycle(object(), Veto())
        with self.assertRaises(Rejected): life.manage("OPEN", peer_uid=501)
        life.manage("STOP", peer_uid=0)
        with self.assertRaises(Rejected): life.manage("OPEN", peer_uid=0)
