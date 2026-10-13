"""One original-child owner; offline adapters prove order, never native facts."""

from dataclasses import dataclass
import math
import time

from auto_g16._managed_offline.common import Rejected


@dataclass(frozen=True, slots=True)
class Observation:
    pid: int
    registered: bool
    fork: bool = False
    exec: bool = False
    fault: bool = False
    exit_status: int | None = None


class Supervisor:
    def __init__(self, adapter, poison, *, clock=time.monotonic):
        self.adapter, self.poison, self.clock = adapter, poison, clock
        self.handle = None
        self.started = self.reaped = self.registered = False
        self.fork_seen = self.exec_seen = self.fault_seen = False
        self.exit_status = None
        self.output = {"stdout": bytearray(), "stderr": bytearray()}
        self.eof = {"stdout": False, "stderr": False}
        self.offset = 0

    def _fail(self):
        self.fault_seen = True
        self.poison()
        raise Rejected("NATIVE_OBSERVATION_BLOCKED")

    def start(self, request, operation):
        if self.started or type(request) is not bytes or len(request) > operation.stdin_cap:
            self._fail()
        self.started = True
        self.request, self.operation = request, operation
        self.last_clock = self.clock()
        if not math.isfinite(self.last_clock) or operation.timeout_seconds <= 0:
            self._fail()
        self.deadline = self.last_clock + operation.timeout_seconds
        try:
            self.adapter.check_reaper()
            self.handle = self.adapter.spawn_suspended()
            # Adapter owns a handle immediately on successful spawn, even if
            # subsequent observer registration fails. Never reconstruct from PID.
            self.adapter.register(self.handle)
            self.registered = True
            self.adapter.resume(self.handle)
            self.adapter.record_owner(self.handle)
        except BaseException:
            # A native spawn error can still have assigned a retained handle.
            if self.handle is None:
                self.handle = getattr(self.adapter, "handle", None)
            self.poison()
            self.fault_seen = True
            raise

    def _observe(self):
        self.adapter.check_reaper()
        event = self.adapter.observe(self.handle)
        if event is None:
            return
        if (type(event) is not Observation or not event.registered
                or event.pid != self.adapter.pid(self.handle)):
            self._fail()
        self.fork_seen |= event.fork
        self.exec_seen |= event.exec
        self.fault_seen |= event.fault
        if event.exit_status is not None:
            if type(event.exit_status) is not int or (self.exit_status is not None and self.exit_status != event.exit_status):
                self._fail()
            self.exit_status = event.exit_status
        if self.fork_seen or self.exec_seen or self.fault_seen:
            self._fail()

    def _now(self):
        now = self.clock()
        if not math.isfinite(now) or now < self.last_clock:
            self._fail()
        self.last_clock = now
        return now

    def finish(self):
        try:
            while self._now() < self.deadline:
                # Observe every iteration including before final waitid/reap.
                self._observe()
                if self.offset < len(self.request):
                    count = self.adapter.write(self.handle, self.request[self.offset:self.offset + 65536])
                    if type(count) is not int or not 0 <= count <= min(65536, len(self.request) - self.offset):
                        self._fail()
                    self.offset += count
                if self.offset == len(self.request):
                    self.adapter.close_input(self.handle)
                for name in self.output:
                    if self.eof[name]:
                        continue
                    cap = self.operation.stdout_cap if name == "stdout" else self.operation.stderr_cap
                    data = self.adapter.read(self.handle, name, min(65536, cap + 1 - len(self.output[name])))
                    if data is None:
                        continue
                    if type(data) is not bytes:
                        self._fail()
                    self.eof[name] = not data
                    self.output[name].extend(data)
                    if len(self.output[name]) > cap:
                        self._fail()
                if self.exit_status is not None and all(self.eof.values()) and self.offset == len(self.request):
                    # History is retained before the real unreaped-child query.
                    status = self.adapter.peek_exit(self.handle)
                    if status is None or status != self.exit_status:
                        self._fail()
                    self._observe()
                    if self.adapter.reap_once(self.handle) != status:
                        self._fail()
                    self.reaped = True
                    self.adapter.release(self.handle)
                    return (bytes(self.output["stdout"]), bytes(self.output["stderr"]),
                            status, "completed", True, True)
                self.adapter.pause(min(0.01, max(0.0, self.deadline - self._now())))
            self._fail()
        except BaseException:
            self.poison()
            self.fault_seen = True
            # No ancestry inference, PID lookup, replacement handle or retry.
            # Retaining unknown ownership is permitted; no signal is necessary
            # to claim a successful cleanup, and cleanup is never claimed here.
            raise

    def retain_unknown(self):
        self.poison()
        return {"original_handle_retained": self.handle is not None,
                "reaped": self.reaped, "native_completed": False}
