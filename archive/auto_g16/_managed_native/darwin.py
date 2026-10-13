"""Actual Darwin C ABI adapter source; loading is hard-disabled pending qualification."""

import ctypes
import os
import sys
import time

from auto_g16._managed_offline.common import Rejected
from auto_g16.transport._direct import _attest_direct_local, _build_mac_direct_command
from .installation import require_qualified_installation
from .supervisor import Observation


class DarwinOwner:
    def __init__(self, installation, scope, authority, source):
        require_qualified_installation()
        if sys.platform != "darwin":
            raise Rejected("NATIVE_NOT_QUALIFIED")
        self.command = _build_mac_direct_command(scope, authority, source=source)
        self.authority, self.installation = authority, installation
        self.before = _attest_direct_local(authority)
        self.handle = ctypes.c_void_p()
        self.library = ctypes.CDLL(installation.root + "/native/libmanaged-direct.dylib", use_errno=True)
        handle = ctypes.c_void_p
        integer = ctypes.POINTER(ctypes.c_int)
        self._declare("ag_spawn", (ctypes.c_char_p,) * 4 + (ctypes.POINTER(handle),))
        for name in ("ag_reaper_check", "ag_register", "ag_resume", "ag_owner", "ag_pid", "ag_close_input", "ag_release"):
            self._declare(name, (handle,))
        self._declare("ag_fd", (handle, ctypes.c_int))
        self._declare("ag_observe", (handle, integer, integer, ctypes.POINTER(ctypes.c_uint32)))
        self._declare("ag_peek", (handle, integer, integer))
        self._declare("ag_reap", (handle, integer))
        self.released = False

    def _declare(self, name, arguments):
        function = getattr(self.library, name)
        function.argtypes, function.restype = arguments, ctypes.c_int

    def _call(self, name, *arguments):
        error = getattr(self.library, name)(*arguments)
        if error:
            raise OSError(error, "managed native boundary rejected")

    def _same(self, handle):
        if handle is not self.handle or not handle.value or self.released:
            raise Rejected("NATIVE_OBSERVATION_BLOCKED")

    def check_reaper(self):
        self._call("ag_reaper_check", self.handle)

    def spawn_suspended(self):
        if self.handle.value:
            raise Rejected("NATIVE_OBSERVATION_BLOCKED")
        command = self.command
        # C owns/retains self.handle even when it reports a post-spawn error.
        self._call("ag_spawn", command[2].encode(), command[4].encode(), command[5].encode(),
                   self.installation.root.encode(), ctypes.byref(self.handle))
        return self.handle

    def register(self, handle):
        self._same(handle)
        self._call("ag_register", handle)

    def resume(self, handle):
        self._same(handle)
        self._call("ag_resume", handle)

    def record_owner(self, handle):
        self._same(handle)
        self._call("ag_owner", handle)

    def pid(self, handle):
        self._same(handle)
        return self.library.ag_pid(handle)

    def observe(self, handle):
        self._same(handle)
        ready, status, history = ctypes.c_int(), ctypes.c_int(), ctypes.c_uint32()
        self._call("ag_observe", handle, ctypes.byref(ready), ctypes.byref(status), ctypes.byref(history))
        return Observation(self.pid(handle), True, bool(history.value & 0x40000000),
                           bool(history.value & 0x20000000), False, status.value if ready.value else None)

    def write(self, handle, data):
        self._same(handle)
        try:
            return os.write(self.library.ag_fd(handle, 0), data)
        except BlockingIOError:
            return 0

    def close_input(self, handle):
        self._same(handle)
        self._call("ag_close_input", handle)

    def read(self, handle, name, cap):
        self._same(handle)
        try:
            return os.read(self.library.ag_fd(handle, {"stdout": 1, "stderr": 2}[name]), cap)
        except BlockingIOError:
            return None

    def peek_exit(self, handle):
        self._same(handle)
        ready, status = ctypes.c_int(), ctypes.c_int()
        self._call("ag_peek", handle, ctypes.byref(ready), ctypes.byref(status))
        return status.value if ready.value else None

    def reap_once(self, handle):
        self._same(handle)
        if _attest_direct_local(self.authority) != self.before:
            raise Rejected("NATIVE_OBSERVATION_BLOCKED")
        status = ctypes.c_int()
        self._call("ag_reap", handle, ctypes.byref(status))
        return status.value

    def release(self, handle):
        self._same(handle)
        self._call("ag_release", handle)
        self.released = True

    @staticmethod
    def pause(seconds):
        time.sleep(seconds)
