"""Offline G/C/M state model. No OS lock, durable marker or process API."""

from contextlib import contextmanager
from threading import Event, Lock, get_ident

from .common import Rejected


class FakeNative:
    """Closed, inert launch adapter; cannot wrap a callable or command."""
    __slots__ = ("shapes", "fail", "entered", "release")

    def __init__(self):
        self.shapes = []
        self.fail = False
        self.entered = None
        self.release = None

    def _create(self, shape):
        if shape not in ("normal", "recovery"):
            raise Rejected("SCOPE")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None and not self.release.wait(5):
            raise Rejected("LIFECYCLE_BLOCKED")
        self.shapes.append(shape)
        if self.fail:
            raise Rejected("LIFECYCLE_BLOCKED")
        return ("inert-child", len(self.shapes))


class FakeInstallation:
    """Memory-only restart veto used solely in offline tests."""
    def __init__(self):
        self.g = Lock()
        self.used = False
        self.valid = True


class Lifecycle:
    @property
    def state(self):
        return "BLOCKED" if self._poisoned.is_set() else self._state

    @state.setter
    def state(self, value):
        self._state = value

    def __init__(self):
        raise Rejected("NATIVE_NOT_QUALIFIED")

    @classmethod
    def offline(cls, installation, native):
        if type(installation) is not FakeInstallation or type(native) is not FakeNative:
            raise Rejected("NATIVE_NOT_QUALIFIED")
        obj = object.__new__(cls)
        obj._poisoned = Event()
        obj._registry_created = False
        obj.c, obj.m = Lock(), Lock()
        obj.installation, obj.native = installation, native
        obj._installation, obj._native = installation, native
        obj._c, obj._m = obj.c, obj.m
        obj.state, obj.owner, obj.children = "BLOCKED", None, []
        obj._g_owned = installation.g.acquire(False)
        if obj._g_owned and not installation.used and installation.valid:
            installation.used = True
            obj.state = "READY_CLOSED"
        return obj

    def _integrity(self):
        if (self.installation is not self._installation or self.native is not self._native
                or type(self.native) is not FakeNative or self.c is not self._c or self.m is not self._m
                or not self._g_owned or not self.installation.used or not self.installation.valid):
            self.poison()
            raise Rejected("LIFECYCLE_BLOCKED")

    def poison(self):
        # A one-way veto; never waits for C or M and never reports STOP success.
        self._poisoned.set()

    def manage(self, operation, *, peer_uid):
        if type(peer_uid) is not int or peer_uid != 0:
            raise Rejected("BAD_PEER")
        if operation not in ("OPEN", "STOP", "STATUS"):
            raise Rejected("BAD_FRAME")
        if not self.m.acquire(False):
            raise Rejected("BUSY")
        try:
            self._integrity()
            if operation == "OPEN":
                if self.state != "READY_CLOSED" or self.c.locked():
                    raise Rejected("LIFECYCLE_BLOCKED")
                self.state = "OPEN"
            elif operation == "STOP" and self.state in ("OPEN", "READY_CLOSED"):
                self.state = "STOPPED"
            return self.state
        finally:
            self.m.release()

    @contextmanager
    def composition(self, *, readonly=False):
        if not self.c.acquire(False):
            raise Rejected("BUSY")
        try:
            self._integrity()
            if not readonly and self.state not in ("READY_CLOSED", "OPEN"):
                raise Rejected("LIFECYCLE_BLOCKED")
            self.owner = get_ident()
            yield
        finally:
            self.owner = None
            self.c.release()

    def launch(self, shape):
        """For offline compositions only; lock spans inert creation/registration."""
        if self.owner != get_ident():
            raise Rejected("SCOPE")
        if not self.m.acquire(False):
            raise Rejected("BUSY")
        try:
            self._integrity()
            if self.state != "OPEN":
                raise Rejected("LIFECYCLE_BLOCKED")
            try:
                child = self.native._create(shape)
                self.children.append(child)
                return child
            except BaseException:
                self.poison()
                raise
        finally:
            self.m.release()

    def close(self):
        self.poison()
        if self._g_owned:
            self._installation.g.release()
            self._g_owned = False
